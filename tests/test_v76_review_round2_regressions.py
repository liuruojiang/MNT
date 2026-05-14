from __future__ import annotations

import importlib.util
from pathlib import Path
import threading
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mnt_bot V 7.6 plus.py"


def load_v76_module():
    spec = importlib.util.spec_from_file_location("mnt_bot_v76_round2", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V76ReviewRound2RegressionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.m = load_v76_module()

    def test_parse_no_year_future_range_rolls_back_to_previous_year(self) -> None:
        start, end = self.m.parse_date_range("6月1日到8月31日")

        self.assertEqual(start, pd.Timestamp("2025-06-01"))
        self.assertEqual(end, pd.Timestamp("2025-08-31"))

    def test_parse_no_year_future_month_range_rolls_back_to_previous_year(self) -> None:
        start, end = self.m.parse_date_range("6月到8月")

        self.assertEqual(start, pd.Timestamp("2025-06-01"))
        self.assertEqual(end, pd.Timestamp("2025-08-31"))

    def test_dk_score_decay_overlay_waits_for_trade_warmup(self) -> None:
        idx = pd.date_range("2026-01-05", periods=6, freq="B")
        result = pd.DataFrame(
            {
                "return": [0.0] * len(idx),
                "holding": ["pair_ab"] * len(idx),
                "top_pair": ["pair_ab"] * len(idx),
                "weight": [1.0] * len(idx),
            },
            index=idx,
        )
        result.attrs["signals_df"] = pd.DataFrame({"pair_ab": [10.0, 3.0, 3.0, 3.0, 3.0, 3.0]}, index=idx)

        out = self.m.apply_dk_pair_score_peak_decay_overlay(
            result,
            decay_ratio_threshold=0.5,
            recovery_ratio_threshold=0.8,
            derisk_scale=0.25,
            commission=0.0,
        )

        self.assertFalse(bool(out["overlay_on"].iloc[2]))
        self.assertFalse(bool(out["overlay_on"].iloc[3]))
        self.assertFalse(bool(out["overlay_on"].iloc[4]))
        self.assertTrue(bool(out["overlay_on"].iloc[5]))

    def test_single_asset_turnover_rejects_cash_with_nonzero_weight(self) -> None:
        with self.assertRaisesRegex(ValueError, "cash holding has non-zero weight"):
            self.m._single_asset_position_turnover("cash", 0.8, "cash", 0.0)

    def test_sp500_expected_weekly_label_uses_beijing_now(self) -> None:
        original = self.m.beijing_now
        self.m.beijing_now = lambda: pd.Timestamp("2026-05-16 01:00:00")
        try:
            self.assertEqual(
                self.m._sp500_risk_regime_expected_weekly_label(),
                pd.Timestamp("2026-05-15"),
            )
        finally:
            self.m.beijing_now = original

    def test_extract_us_rot_rebalances_shows_volreg_cash_transition(self) -> None:
        idx = pd.to_datetime(["2026-01-05", "2026-01-06"])
        frame = pd.DataFrame(
            {
                "rebalanced": [False, True],
                "w_SPY": [1.0, 0.0],
                "w_CASH": [0.0, 1.0],
                "volreg_action": ["", "enter_cash"],
            },
            index=idx,
        )

        records = self.m.extract_us_rot_rebalances(frame)

        self.assertEqual(len(records), 1)
        buy_text = " ".join(str(v) for k, v in records[0].items() if "买" in k or "涔" in k)
        self.assertIn("CASH", buy_text)

    def test_us_model_b_scales_live_and_proxy_leveraged_assets(self) -> None:
        self.assertIn("QQQM", self.m.US_ROT_FUTURES)
        self.assertIn("GLDM", self.m.US_ROT_FUTURES)
        self.assertNotIn("QQQ", self.m.US_ROT_FUTURES)

        live_scaled = self.m._us_model_b({"QQQM": 0.40, "EMXC": 0.40}, 2.0)
        proxy_scaled = self.m._us_model_b({"QQQ": 0.40, "EMXC": 0.40}, 2.0)

        self.assertAlmostEqual(live_scaled["QQQM"], 0.80)
        self.assertAlmostEqual(proxy_scaled["QQQ"], 0.80)
        self.assertAlmostEqual(live_scaled["EMXC"], 0.40)
        self.assertAlmostEqual(proxy_scaled["EMXC"], 0.40)

    def test_future_cn_calendar_falls_back_with_warning(self) -> None:
        with self.assertWarnsRegex(RuntimeWarning, "CN market holiday calendar"):
            self.assertFalse(self.m._is_cn_required_close_day(pd.Timestamp("2027-01-01")))
        with self.assertWarnsRegex(RuntimeWarning, "CN market holiday calendar"):
            self.assertTrue(self.m._is_cn_required_close_day(pd.Timestamp("2027-01-04")))

    def test_us_mix_threshold_check_uses_raw_weight_source_of_truth(self) -> None:
        calls = []
        original = self.m._us_raw_weights

        def fake_raw_weights(mom_row, vol_row, ranking_codes, top_n, abs_threshold, prev_risky=None, threshold=1.0):
            calls.append((tuple(prev_risky or ()), threshold))
            return {"QQQ": 1.0}

        self.m._us_raw_weights = fake_raw_weights
        try:
            momentum_rows = {
                lb: pd.Series({"QQQ": 0.20, "GLD": 0.19, "TLT": 0.18})
                for lb in self.m.US_ROT_LBS
            }
            vol_row = pd.Series({"QQQ": 0.20, "GLD": 0.20, "TLT": 0.20})
            self.m._us_mix_threshold_check(
                momentum_rows,
                vol_row,
                ["QQQ", "GLD", "TLT"],
                {self.m.US_ROT_LBS[0]: {"GLD"}},
                1.05,
            )
        finally:
            self.m._us_raw_weights = original

        self.assertGreaterEqual(len(calls), 1)

    def test_us_mix_prev_risky_keeps_other_windows_when_one_is_empty(self) -> None:
        row = pd.Series({f"sel_{self.m.US_ROT_LBS[0]}": "", f"sel_{self.m.US_ROT_LBS[1]}": "QQQ"})

        prev = self.m._us_mix_prev_risky_by_lb_from_row(row)

        self.assertIsNotNone(prev)
        self.assertEqual(prev[self.m.US_ROT_LBS[0]], set())
        self.assertEqual(prev[self.m.US_ROT_LBS[1]], {"QQQ"})

    def test_user_query_handlers_do_not_print_combo_budget_panel(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("_write_combo_advisory_panel", source)
        self.assertNotIn("ACTIVE DYNAMIC BUDGET", source)
        self.assertNotIn("动态明细暂未加载", source)

    def test_csindex_fail_counter_is_thread_local(self) -> None:
        self.m._set_csindex_consecutive_fails(2)
        worker_values: list[int] = []

        def worker() -> None:
            worker_values.append(self.m._get_csindex_consecutive_fails())
            self.m._increment_csindex_consecutive_fails()
            worker_values.append(self.m._get_csindex_consecutive_fails())

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        self.assertEqual(worker_values, [0, 1])
        self.assertEqual(self.m._get_csindex_consecutive_fails(), 2)
        self.m._reset_csindex_consecutive_fails()

    def test_request_cache_reuses_fetch_and_strategy_results(self) -> None:
        class Msg:
            def write(self, _text: str) -> None:
                return None

        class Stub(self.m.CombinedStrategyBase):
            def __init__(self) -> None:
                self.fetch_calls = 0
                self.run_calls = 0

            def _fetch_data(self, msg, include_cn_live_snapshot=False, include_us_live_snapshot=False):
                self.fetch_calls += 1
                return tuple(pd.DataFrame({"x": [float(self.fetch_calls)]}) for _ in range(4))

            def _run_strategies(self, cn_close, cn_dk_close, us_rot_close, us_prod_daily,
                                allow_unresolved_suba_volume=False):
                self.run_calls += 1
                return (self.run_calls, allow_unresolved_suba_volume)

        stub = Stub()
        msg = Msg()

        first = stub._cached_fetch_data(msg, include_cn_live_snapshot=True)
        second = stub._cached_fetch_data(msg, include_cn_live_snapshot=True)
        third = stub._cached_fetch_data(msg, include_cn_live_snapshot=False)

        self.assertIs(first, second)
        self.assertIsNot(first, third)
        self.assertEqual(stub.fetch_calls, 2)

        run1 = stub._cached_run_strategies(*first)
        run2 = stub._cached_run_strategies(*first)
        run3 = stub._cached_run_strategies(*first, allow_unresolved_suba_volume=True)

        self.assertIs(run1, run2)
        self.assertNotEqual(run1, run3)
        self.assertEqual(stub.run_calls, 2)

    def test_add_cn_bond_column_degrades_on_bot_error(self) -> None:
        class Msg:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def write(self, text: str) -> None:
                self.lines.append(text)

        original_fetch = self.m.fetch_cn_kline

        def raise_bot_error(secid):
            if secid == self.m.CN_BOND_CODE:
                raise self.m.poe.BotError("bond source unavailable")
            return original_fetch(secid)

        cn_close = pd.DataFrame({"0.399606": [1.0, 1.1]}, index=pd.to_datetime(["2026-01-05", "2026-01-06"]))
        msg = Msg()
        self.m.fetch_cn_kline = raise_bot_error
        try:
            out = self.m._add_cn_bond_column(cn_close, msg=msg, context="Sub-A test")
        finally:
            self.m.fetch_cn_kline = original_fetch

        self.assertEqual(list(out.columns), ["0.399606"])
        self.assertTrue(any("缺少国债避险通道" in line for line in msg.lines))


if __name__ == "__main__":
    unittest.main()

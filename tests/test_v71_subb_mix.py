import builtins
import importlib.util
import inspect
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
V71_BOT_PATH = ROOT / "mnt_bot V 7.1 plus.py"


class _PoeStub:
    class BotError(Exception):
        pass

    def __init__(self):
        self.settings = None

    def update_settings(self, settings):
        self.settings = settings


def load_module(path, name):
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = _PoeStub()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        if had_poe:
            builtins.poe = old_poe
        else:
            delattr(builtins, "poe")


class V71SubBMixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(V71_BOT_PATH, "mnt_bot_v71")
        cls.cls = cls.module.CombinedStrategyV71

    def _source(self, name):
        return inspect.getsource(getattr(self.cls, name))

    def test_public_version_markers_are_updated(self):
        text = V71_BOT_PATH.read_text(encoding="utf-8")
        self.assertIn("# poe: name=Strategy-Signal-V71", text)
        self.assertIn('"""V7.1"""', text)
        self.assertIn("Strategy Signal V7.1", text)
        self.assertIn("CombinedStrategyV71().run()", text)

    def test_sub_b_pool_uses_mix_windows_and_includes_ibit(self):
        mod = self.module
        self.assertEqual(tuple(mod.US_ROT_LBS), (130, 260, 390))
        self.assertEqual(mod.US_ROT_MAX_LB, 390)
        self.assertAlmostEqual(mod.US_ROT_REBALANCE_THRESHOLD, 1.05)
        self.assertIn("BTC-USD", mod.US_ROT_POOL)
        self.assertIn("IBIT", mod.US_ROT_ASSETS)
        self.assertEqual(mod.US_ROT_BTC_TICKER, "BTC-USD")
        self.assertEqual(mod.US_ROT_BTC_START, mod.pd.Timestamp("2022-01-01"))
        self.assertEqual(mod.US_ROT_BTC_MAX_W, 0.30)

    def test_mix_target_weights_average_per_window_model_b_targets(self):
        mod = self.module
        ranking_codes = ["QQQ", "GLD", "EFA"]
        vol_row = pd.Series({"QQQ": 0.20, "GLD": 0.25, "EFA": 0.40, "BIL": 0.01})
        momentum_rows = {
            130: pd.Series({"QQQ": 0.30, "GLD": 0.10, "EFA": 0.05, "BIL": 0.00}),
            260: pd.Series({"QQQ": 0.12, "GLD": 0.35, "EFA": 0.08, "BIL": 0.00}),
            390: pd.Series({"QQQ": 0.09, "GLD": 0.07, "EFA": 0.28, "BIL": 0.00}),
        }

        mix_act, per_lb = mod._us_mix_target_weights(momentum_rows, vol_row, ranking_codes, scale=1.25)

        expected_acts = []
        for lb in mod.US_ROT_LBS:
            raw = mod._us_raw_weights(momentum_rows[lb], vol_row, ranking_codes, 3, mod.US_ROT_ABS_THRESHOLD)
            expected_acts.append(mod._us_model_b(raw, 1.25))
            self.assertEqual(per_lb[lb]["raw"], raw)

        keys = set().union(*[a.keys() for a in expected_acts])
        expected_mix = {k: sum(a.get(k, 0.0) for a in expected_acts) / len(expected_acts) for k in keys}

        self.assertEqual(set(mix_act), set(expected_mix))
        for key, val in expected_mix.items():
            self.assertAlmostEqual(mix_act[key], val)

    def test_mix_target_weights_can_apply_per_window_buffer(self):
        mod = self.module
        ranking_codes = ["QQQ", "GLD", "EFA", "DBC"]
        vol_row = pd.Series({asset: 0.20 for asset in ranking_codes})
        momentum_rows = {
            130: pd.Series({"QQQ": 0.30, "GLD": 0.29, "EFA": 0.20, "DBC": 0.205}),
            260: pd.Series({"QQQ": 0.31, "GLD": 0.28, "EFA": 0.19, "DBC": 0.198}),
            390: pd.Series({"QQQ": 0.32, "GLD": 0.27, "EFA": 0.18, "DBC": 0.189}),
        }
        prev_risky_by_lb = {lb: {"QQQ", "GLD", "EFA"} for lb in mod.US_ROT_LBS}

        unbuffered_mix, _ = mod._us_mix_target_weights(
            momentum_rows,
            vol_row,
            ranking_codes,
            scale=1.0,
            top_n=3,
            abs_threshold=mod.US_ROT_ABS_THRESHOLD,
        )
        buffered_mix, per_lb = mod._us_mix_target_weights(
            momentum_rows,
            vol_row,
            ranking_codes,
            scale=1.0,
            top_n=3,
            abs_threshold=mod.US_ROT_ABS_THRESHOLD,
            prev_risky_by_lb=prev_risky_by_lb,
            threshold=1.05,
        )

        self.assertGreater(unbuffered_mix.get("DBC", 0.0), 0.0)
        self.assertAlmostEqual(unbuffered_mix.get("EFA", 0.0), 0.0)
        self.assertAlmostEqual(buffered_mix.get("DBC", 0.0), 0.0)
        self.assertGreater(buffered_mix.get("EFA", 0.0), 0.0)
        for lb in mod.US_ROT_LBS:
            self.assertSetEqual(
                {asset for asset, weight in per_lb[lb]["raw"].items() if asset != "BIL" and weight > 0.0},
                {"QQQ", "GLD", "EFA"},
            )

    def test_mix_display_context_can_apply_buffer_with_prev_window_selection(self):
        mod = self.module
        close_df = pd.DataFrame(
            {
                "QQQ": [100, 110, 120, 130, 150],
                "GLD": [100, 109, 118, 128, 145],
                "EFA": [100, 105, 110, 115, 126.5],
                "DBC": [100, 105, 110, 115, 127.0],
            },
            index=pd.date_range("2026-01-01", periods=5, freq="D"),
        )
        orig_lbs = mod.US_ROT_LBS
        orig_vol_lb = mod.US_ROT_VOL_LB
        try:
            mod.US_ROT_LBS = (1, 2, 3)
            mod.US_ROT_VOL_LB = 2
            prev_risky_by_lb = {lb: {"QQQ", "GLD", "EFA"} for lb in mod.US_ROT_LBS}
            ctx = mod._us_mix_display_context(
                close_df,
                -1,
                ["QQQ", "GLD", "EFA", "DBC"],
                1.0,
                prev_risky_by_lb=prev_risky_by_lb,
                threshold=1.05,
                reference_assets=[],
            )
        finally:
            mod.US_ROT_LBS = orig_lbs
            mod.US_ROT_VOL_LB = orig_vol_lb

        self.assertGreater(ctx["mix_act"].get("EFA", 0.0), 0.0)
        self.assertAlmostEqual(ctx["mix_act"].get("DBC", 0.0), 0.0)

    def test_sp500_risk_regime_can_prefer_fresh_csv_without_live_fetch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "sp500_risk_regime.csv"
            df = self.module.pd.DataFrame(
                {
                    "risk_score": [41.0, 45.0],
                    "regime": ["3-困难模式", "3-困难模式"],
                    "suggested_equity_budget": ["70%", "70%"],
                    "credit_proxy": ["hy_oas", "hy_oas"],
                    "credit_series": ["BAMLH0A0HYM2", "BAMLH0A0HYM2"],
                    "feature_veto": [False, False],
                    "oversold_turn_rule": [False, False],
                },
                index=self.module.pd.to_datetime(["2026-04-17", "2026-04-24"]),
            )
            df.to_csv(csv_path, encoding="utf-8-sig")

            def fail_live_fetch():
                raise AssertionError("live fetch should not run when fresh CSV is available")

            old_fetch = self.module._fetch_sp500_risk_regime_live_snapshot
            self.module._fetch_sp500_risk_regime_live_snapshot = fail_live_fetch
            try:
                snapshot = self.module._load_sp500_risk_regime_snapshot(
                    search_paths=[(str(csv_path), "hy_oas", "HY OAS(BAMLH0A0HYM2)")],
                    live_fetch=True,
                    prefer_recent_csv=True,
                    asof_date=self.module.pd.Timestamp("2026-04-24"),
                )
            finally:
                self.module._fetch_sp500_risk_regime_live_snapshot = old_fetch

        self.assertEqual(snapshot["source_type"], "csv")
        self.assertEqual(snapshot["regime"], "3-困难模式")
        self.assertEqual(snapshot["latest_date"], self.module.pd.Timestamp("2026-04-24"))
        self.assertIsNone(snapshot.get("live_error"))

    def test_live_signal_prefers_recent_sp500_risk_regime_csv(self):
        src = self._source("_handle_live_signal")
        self.assertIn("_write_sp500_risk_regime_note(msg, prefer_recent_csv=True)", src)

    def test_compute_signal_data_uses_actual_dk_signal_flag(self):
        src = self._source("_compute_signal_data")
        self.assertIn('bool(cn_dk_result["is_signal"].iloc[-1])', src)
        self.assertNotIn("is_dk_signal = True", src)

    def test_signal_query_sub_b_uses_mix_display_context(self):
        src = self._source("_handle_signal")
        self.assertIn("_us_mix_display_context(", src)
        self.assertIn("IBIT(参考", src)

    def test_live_signal_sub_b_labels_mix_context(self):
        src = self._source("_handle_live_signal")
        self.assertIn("_us_mix_display_context(", src)
        self.assertIn("130/260/390", src)

    def test_run_us_rotation_mix_uses_threshold_buffer_in_mixed_path(self):
        src = inspect.getsource(self.module.run_us_rotation_mix)
        self.assertIn("threshold=US_ROT_REBALANCE_THRESHOLD", src)
        self.assertIn("prev_risky_by_lb", src)
        self.assertIn("_us_mix_target_weights(", src)
        self.assertIn("prev_risky_by_lb=prev_risky_by_lb", src)

    def test_live_params_sub_b_discloses_each_mix_window(self):
        src = self._source("_handle_live_params")
        self.assertIn("_us_mix_display_context(", src)
        self.assertIn("for lb in US_ROT_LBS", src)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import inspect
import unittest
import builtins
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V683_BOT_PATH = ROOT / "mnt_bot V 6.8.3 plus.py"
V70_BOT_PATH = ROOT / "mnt_bot V 7.0 plus.py"


class _PoeStub:
    class BotError(Exception):
        pass

    def __init__(self):
        self.settings = None

    def update_settings(self, settings):
        self.settings = settings


def load_module(path, name, *, inject_native_poe=False):
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    if inject_native_poe:
        builtins.poe = _PoeStub()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        if inject_native_poe:
            if had_poe:
                builtins.poe = old_poe
            else:
                delattr(builtins, "poe")


class V683QueryDisclosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(V683_BOT_PATH, "mnt_bot_v683", inject_native_poe=True)
        cls.cls = cls.module.CombinedStrategyV681

    def _source(self, name):
        return inspect.getsource(getattr(self.cls, name))

    def test_sub_b_leverage_assets_are_disclosed_in_signal_queries(self):
        for handler in ("_handle_signal", "_handle_live_signal"):
            with self.subTest(handler=handler):
                src = self._source(handler)
                self.assertIn("QQQM/GLDM", src)
                self.assertIn("US_ROT_FUTURES", src)

    def test_sub_b_leverage_assets_are_disclosed_in_param_queries(self):
        for handler in ("_handle_params", "_handle_live_params"):
            with self.subTest(handler=handler):
                src = self._source(handler)
                self.assertIn("QQQM/GLDM", src)
                self.assertIn("US_ROT_FUTURES", src)

    def test_sub_a_and_adk_overheat_rules_are_disclosed_in_param_queries(self):
        for handler in ("_handle_params", "_handle_live_params"):
            with self.subTest(handler=handler):
                src = self._source(handler)
                self.assertIn("CN_SA_SAME_SIDE_OVERHEAT_ENTER", src)
                self.assertIn("CN_SA_SAME_SIDE_OVERHEAT_EXIT", src)
                self.assertIn("CN_DK_SAME_SIDE_OVERHEAT_ENTER", src)
                self.assertIn("CN_DK_SAME_SIDE_OVERHEAT_EXIT", src)

    def test_sub_a_live_params_disclose_effective_and_current_momentum(self):
        src = self._source("_handle_live_params")
        self.assertIn("生效动量", src)
        self.assertIn("当前动量", src)
        self.assertIn("生效R²", src)
        self.assertIn("当前R²", src)
        self.assertIn("当前已生效", src)
        self.assertIn("若现在收盘", src)
        self.assertIn("| 排名 | 资产 | 标记 |", src)

    def test_sub_a_effective_momentum_uses_last_signal_day_not_latest_snapshot(self):
        pd = self.module.pd
        idx = pd.to_datetime(["2026-04-20", "2026-04-21", "2026-04-22"])
        cn_result = pd.DataFrame(
            {
                "holding": ["cash", "0.399606", "0.399606"],
                "is_signal": [False, True, False],
            },
            index=idx,
        )
        bias_mom = {
            "0.399606": pd.Series([10.0, 92.6, 70.0], index=idx),
            "1.H00852": pd.Series([8.0, 60.7, 80.0], index=idx),
        }
        r2 = {
            "0.399606": pd.Series([0.7, 0.822, 0.710], index=idx),
            "1.H00852": pd.Series([0.6, 0.851, 0.900], index=idx),
        }

        rows, meta = self.module._build_suba_momentum_rank_rows(
            cn_result, bias_mom, r2, ["0.399606", "1.H00852"]
        )

        cyb = next(row for row in rows if row["code"] == "0.399606")
        self.assertEqual(cyb["asset_name"], "创业板")
        self.assertEqual(cyb["marker"], "当前已生效")
        self.assertAlmostEqual(cyb["effective_momentum"], 92.6)
        self.assertAlmostEqual(cyb["current_momentum"], 70.0)
        self.assertAlmostEqual(cyb["effective_r2"], 0.822)
        self.assertAlmostEqual(cyb["current_r2"], 0.710)
        self.assertEqual(meta["effective_date"], idx[1])
        self.assertEqual(meta["current_date"], idx[2])


class V70UpgradeDisclosureTests(V683QueryDisclosureTests):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(V70_BOT_PATH, "mnt_bot_v70", inject_native_poe=True)
        cls.cls = cls.module.CombinedStrategyV70

    def test_v70_public_version_markers_are_updated(self):
        text = V70_BOT_PATH.read_text(encoding="utf-8")
        self.assertIn("# poe: name=Strategy-Signal-V70", text)
        self.assertIn('"""V7.0"""', text)
        self.assertIn("Strategy Signal V7.0", text)
        self.assertNotIn("Strategy Signal V6.8.3", text)

    def test_sub_a_and_adk_overheat_rules_are_disclosed_in_signal_queries(self):
        for handler in ("_handle_signal", "_handle_live_signal"):
            with self.subTest(handler=handler):
                src = self._source(handler)
                self.assertIn("CN_SA_SAME_SIDE_OVERHEAT_ENTER", src)
                self.assertIn("CN_SA_SAME_SIDE_OVERHEAT_EXIT", src)
                self.assertIn("CN_DK_SAME_SIDE_OVERHEAT_ENTER", src)
                self.assertIn("CN_DK_SAME_SIDE_OVERHEAT_EXIT", src)

    def test_v70_uses_native_poe_namespace_without_compat_runtime(self):
        text = V70_BOT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("import fastapi_poe as poe", text)
        self.assertNotIn("import asyncio", text)
        self.assertNotIn("import queue", text)
        self.assertNotIn("import threading", text)
        self.assertNotIn("from types import SimpleNamespace", text)
        self.assertIn("from fastapi_poe.types import SettingsResponse", text)
        for removed_name in (
            "ProtocolMessage",
            "QueryRequest",
            "SettingsRequest",
            "_safe_poe_update_settings",
            "_CompatChatMessage",
            "_CompatAttachment",
            "_CompatQuery",
            "_CompatMessage",
            "_LegacyPoeRuntime",
            "_POE_RUNTIME_LOCK",
            "CombinedStrategyV70PoeBot",
        ):
            with self.subTest(removed_name=removed_name):
                self.assertNotIn(removed_name, text)
        self.assertIn("def _fetch_or_bot_errors(", text)
        self.assertIn("poe.update_settings(_BOT_SETTINGS)", text)
        self.assertIn("CombinedStrategyV70().run()", text)
        self.assertNotIn("runner(", text)
        self.assertIn('US_ROT_FUTURES = {"QQQ", "GLD"}', text)
        self.assertIn("CN_SA_SAME_SIDE_OVERHEAT_ENTER = 0.36", text)
        self.assertIn("CN_DK_SAME_SIDE_OVERHEAT_ENTER = 0.22", text)

    def test_sp500_risk_regime_snapshot_is_available_for_queries(self):
        snapshot = self.module._load_sp500_risk_regime_snapshot(live_fetch=False)
        self.assertIsNotNone(snapshot)
        self.assertIn("regime", snapshot)
        self.assertIn("risk_score", snapshot)
        self.assertIn("latest_date", snapshot)
        self.assertIn("regime_changed_date", snapshot)
        self.assertIn("suggested_equity_budget", snapshot)
        self.assertIn(snapshot["credit_proxy"], {"hy_oas", "baa10y"})

    def test_sp500_risk_regime_snapshot_falls_back_to_embedded_for_poe_single_file(self):
        snapshot = self.module._load_sp500_risk_regime_snapshot(
            search_paths=[("Z:/missing/sp500_risk_regime.csv", "hy_oas", "missing")],
            live_fetch=False,
        )
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["source_type"], "embedded")
        self.assertEqual(snapshot["regime"], "3-困难模式")
        self.assertEqual(snapshot["suggested_equity_budget"], "70%")

    def test_sp500_risk_regime_prefers_live_fetch_for_poe_queries(self):
        def fake_live_snapshot():
            snap = dict(self.module.SP500_RISK_REGIME_EMBEDDED_SNAPSHOT)
            snap.update({
                "latest_date": self.module.pd.Timestamp("2026-04-17"),
                "regime_changed_date": self.module.pd.Timestamp("2026-04-17"),
                "risk_score": 61.25,
                "regime": "4-噩梦模式",
                "suggested_equity_budget": "50%",
                "source_type": "live",
                "source_file": "FRED+Yahoo实时计算",
                "input_dates": {
                    "SPX": "2026-04-17",
                    "VIXCLS": "2026-04-17",
                    "BAMLH0A0HYM2": "2026-04-17",
                    "T10Y2Y": "2026-04-17",
                },
            })
            return snap

        old_fetch = self.module._fetch_sp500_risk_regime_live_snapshot
        self.module._fetch_sp500_risk_regime_live_snapshot = fake_live_snapshot
        try:
            snapshot = self.module._load_sp500_risk_regime_snapshot(
                search_paths=[("Z:/missing/sp500_risk_regime.csv", "hy_oas", "missing")]
            )
        finally:
            self.module._fetch_sp500_risk_regime_live_snapshot = old_fetch
        self.assertEqual(snapshot["source_type"], "live")
        self.assertEqual(snapshot["regime"], "4-噩梦模式")

    def test_sp500_risk_regime_is_disclosed_in_signal_queries(self):
        for handler in ("_handle_signal", "_handle_live_signal"):
            with self.subTest(handler=handler):
                src = self._source(handler)
                self.assertIn("_write_sp500_risk_regime_note", src)

    def test_sp500_risk_regime_can_prefer_fresh_csv_without_live_fetch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "sp500_risk_regime.csv"
            df = self.module.pd.DataFrame(
                {
                    "risk_score": [41.0, 45.0],
                    "regime": ["3-鍥伴毦妯″紡", "3-鍥伴毦妯″紡"],
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
        self.assertEqual(snapshot["regime"], "3-鍥伴毦妯″紡")
        self.assertEqual(snapshot["latest_date"], self.module.pd.Timestamp("2026-04-24"))
        self.assertIsNone(snapshot.get("live_error"))

    def test_live_signal_prefers_recent_sp500_risk_regime_csv(self):
        src = self._source("_handle_live_signal")
        self.assertIn("_write_sp500_risk_regime_note(msg, prefer_recent_csv=True)", src)


if __name__ == "__main__":
    unittest.main()

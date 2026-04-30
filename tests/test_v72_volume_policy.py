import builtins
import importlib.util
import inspect
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
V72_BOT_PATH = ROOT / "mnt_bot V 7.2 plus.py"


class _PoeStub:
    class BotError(Exception):
        pass

    def __init__(self):
        self.settings = None

    def update_settings(self, settings):
        self.settings = settings


class _MsgStub:
    def __init__(self):
        self.parts = []

    def write(self, text):
        self.parts.append(text)

    @property
    def text(self):
        return "".join(self.parts)


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


class V72VolumePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(V72_BOT_PATH, "mnt_bot_v72_volume_policy")

    def test_suba_volume_rule_is_formal_or_trigger(self):
        mod = self.module
        self.assertTrue(mod.CN_SA_VOLUME_OVERLAY_ENABLED)
        self.assertEqual(mod.CN_SA_VOLUME_SCALE, 0.5)
        self.assertEqual(mod.CN_SA_VOLUME_RULE_MODE, "or")

        idx = pd.date_range("2024-01-01", periods=6, freq="D")
        zz = pd.Series([100, 100, 90, 80, 70, 60], index=idx, dtype=float)
        cyb = pd.Series([100, 100, 120, 130, 140, 150], index=idx, dtype=float)
        signal, feature = mod._build_consecutive_below_amount_signal(
            {
                "zz2000": {"amount": zz, "ma": 2, "days": 3},
                "cyb": {"amount": cyb, "ma": 2, "days": 3},
            },
            mode="or",
        )

        self.assertFalse(bool(signal.iloc[3]))
        self.assertTrue(bool(signal.iloc[4]))
        self.assertEqual(int(feature.loc[idx[4], "zz2000_streak"]), 3)
        self.assertEqual(int(feature.loc[idx[4], "cyb_streak"]), 0)

    def test_dk_and_microcap_volume_rules_are_warning_only(self):
        mod = self.module
        self.assertEqual(mod.CN_DK_VOLUME_POLICY, "warning_only")
        self.assertEqual(mod.MICROCAP_VOLUME_POLICY, "warning_only")
        self.assertEqual(mod.CN_DK_VOLUME_YELLOW_MA, 40)
        self.assertEqual(mod.CN_DK_VOLUME_YELLOW_DAYS, 16)
        self.assertEqual(mod.MICROCAP_BROAD_VOLUME_RULE_MODE, "and")
        self.assertNotIn("CN_DK_VOLUME_DERISK_ENABLED = True", V72_BOT_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("MICROCAP_VOLUME_DERISK_ENABLED = True", V72_BOT_PATH.read_text(encoding="utf-8"))

    def test_v72_query_aliases_are_exposed(self):
        source = V72_BOT_PATH.read_text(encoding="utf-8")
        self.assertIn("信号实时", source)
        self.assertIn("参数实时", source)
        self.assertIn("信号参数", source)
        self.assertIn('query_compact = re.sub(r"\\s+", "", query)', source)

    def test_suba_volume_fetch_failure_degrades_without_crashing(self):
        mod = self.module
        idx = pd.date_range("2024-01-01", periods=3, freq="D")
        cn_result = pd.DataFrame(
            {
                "return": [0.0, 0.01, -0.005],
                "holding": ["cash", "1.H00852", "1.H00852"],
                "weight": [0.0, 1.0, 1.0],
            },
            index=idx,
        )
        out = mod._mark_suba_volume_unavailable(cn_result, RuntimeError("EastMoney down"))
        self.assertIn("suba_volume_rule_on", out.columns)
        self.assertFalse(bool(out["suba_volume_rule_on"].iloc[-1]))
        self.assertEqual(float(out["suba_volume_rule_scale"].iloc[-1]), 1.0)
        self.assertTrue(bool(out["suba_volume_unavailable"].iloc[-1]))
        self.assertIn("EastMoney down", out["suba_volume_error"].iloc[-1])

    def test_suba_volume_loader_falls_back_to_proxy_source(self):
        mod = self.module
        idx = pd.date_range("2024-01-01", periods=80, freq="D")

        def fail_eastmoney(secid):
            raise RuntimeError("EastMoney down")

        def fake_sina(secid):
            vals = [100.0] * 70 + [90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0, 5.0]
            return pd.DataFrame(
                {"close": vals, "volume": vals, "amount": vals, "source": "Sina volume proxy"},
                index=idx,
            )

        old_eastmoney = mod._fetch_cn_eastmoney_amount
        old_sina = mod._fetch_cn_sina_amount_proxy
        try:
            mod._fetch_cn_eastmoney_amount = fail_eastmoney
            mod._fetch_cn_sina_amount_proxy = fake_sina
            signal, feature = mod._load_suba_volume_signal()
        finally:
            mod._fetch_cn_eastmoney_amount = old_eastmoney
            mod._fetch_cn_sina_amount_proxy = old_sina

        self.assertTrue(bool(signal.iloc[-1]))
        self.assertEqual(feature["zz2000_source"].iloc[-1], "Sina volume proxy")
        self.assertEqual(feature["cyb_source"].iloc[-1], "Sina volume proxy")

    def test_suba_volume_loader_uses_available_or_leg(self):
        mod = self.module
        idx = pd.date_range("2024-01-01", periods=80, freq="D")
        vals = [100.0] * 70 + [90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0, 5.0]

        def fake_fetch(secid, label):
            if label == "ZZ2000":
                raise RuntimeError("ZZ2000 unavailable")
            return pd.DataFrame({"amount": vals}, index=idx), "Sina volume proxy"

        old_fetch = mod._fetch_cn_amount_with_fallback
        try:
            mod._fetch_cn_amount_with_fallback = fake_fetch
            signal, feature = mod._load_suba_volume_signal()
        finally:
            mod._fetch_cn_amount_with_fallback = old_fetch

        self.assertTrue(bool(signal.iloc[-1]))
        self.assertEqual(feature["zz2000_source"].iloc[-1], "unavailable")
        self.assertEqual(feature["cyb_source"].iloc[-1], "Sina volume proxy")
        self.assertTrue(bool(feature["partial_unavailable"].iloc[-1]))

    def test_volume_status_wording_distinguishes_rule_from_trigger(self):
        mod = self.module
        idx = pd.date_range("2024-01-01", periods=1, freq="D")
        cn_result = pd.DataFrame(
            {
                "suba_volume_rule_on": [False],
                "suba_volume_rule_scale": [1.0],
                "suba_volume_zz2000_streak": [0],
                "suba_volume_cyb_streak": [0],
                "suba_volume_zz2000_source": ["EastMoney amount"],
                "suba_volume_cyb_source": ["EastMoney amount"],
            },
            index=idx,
        )

        msg = _MsgStub()
        mod._write_suba_volume_overlay_status(msg, cn_result, compact=True)

        self.assertIn("规则启用", msg.text)
        self.assertIn("当前**未触发**", msg.text)
        self.assertIn("成交额scale=1.00", msg.text)
        self.assertNotIn("**OFF**", msg.text)

    def test_warning_panel_always_includes_direct_microcap_volume_note(self):
        mod = self.module

        def fake_warning_status(secid, ma, days, label):
            return {
                "label": label,
                "date": pd.Timestamp("2026-04-30"),
                "streak": 0,
                "triggered": False,
                "ma": ma,
                "days": days,
            }

        old = mod._volume_warning_status
        try:
            mod._volume_warning_status = fake_warning_status
            msg = _MsgStub()
            mod._write_volume_warning_panel(msg, compact=True)
        finally:
            mod._volume_warning_status = old

        self.assertIn("微盘指数成交量: QVeris/同花顺 883418.TI 仅观察，不作为 V7.2 实盘参数。", msg.text)
        self.assertIn("Sub-A-DK黄灯: **未触发**", msg.text)
        self.assertIn("微盘宽口径黄灯: **未触发**", msg.text)
        self.assertNotIn("**OFF**", msg.text)

    def test_v72_user_facing_paths_do_not_show_sub_c(self):
        mod = self.module
        source = V72_BOT_PATH.read_text(encoding="utf-8")
        self.assertNotIn('signal_info["Sub-C"] = self._write_sub_c', source)
        self.assertNotIn('self._write_sub_c(msg, d, us_prod_daily)', source)

        for method_name in ["_handle_params", "_handle_live_params", "_handle_signal_history", "_handle_nav_chart", "_handle_performance"]:
            method_source = inspect.getsource(getattr(mod.CombinedStrategyV72, method_name))
            self.assertNotIn("### Sub-C", method_source)
            self.assertNotIn('"Sub-C"', method_source)


if __name__ == "__main__":
    unittest.main()

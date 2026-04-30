import builtins
import importlib.util
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


if __name__ == "__main__":
    unittest.main()

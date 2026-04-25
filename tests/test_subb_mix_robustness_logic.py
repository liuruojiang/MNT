import builtins
import importlib.util
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "analyze_subb_mix_robustness.py"


class _PoeStub:
    class BotError(Exception):
        pass

    def update_settings(self, settings):
        self.settings = settings


def _load_module():
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = _PoeStub()
    spec = importlib.util.spec_from_file_location("subb_mix_robustness", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        if had_poe:
            builtins.poe = old_poe
        else:
            delattr(builtins, "poe")


class SubBMixRobustnessLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def test_signal_average_then_top3_keeps_only_global_top3(self):
        momentum_rows = {
            130: pd.Series({"QQQ": 0.30, "GLD": 0.05, "EFA": 0.28, "DBC": 0.27, "TLT": -0.01}),
            260: pd.Series({"QQQ": 0.35, "GLD": 0.29, "EFA": 0.10, "DBC": 0.31, "TLT": 0.02}),
            390: pd.Series({"QQQ": 0.20, "GLD": 0.34, "EFA": 0.08, "DBC": 0.32, "TLT": -0.03}),
        }
        vol_row = pd.Series({"QQQ": 0.20, "GLD": 0.25, "EFA": 0.30, "DBC": 0.22, "TLT": 0.15})
        ranking_codes = ["QQQ", "GLD", "EFA", "DBC", "TLT"]

        act, avg_signal = self.mod.mix_signal_then_top_weights(
            momentum_rows,
            vol_row,
            ranking_codes,
            scale=1.0,
            top_n=3,
            abs_threshold=0.0,
        )

        positive_assets = {k for k, v in act.items() if k != "BIL" and v > 1e-9}
        self.assertEqual(positive_assets, {"QQQ", "DBC", "GLD"})
        self.assertAlmostEqual(avg_signal["QQQ"], np.mean([0.30, 0.35, 0.20]))
        self.assertAlmostEqual(avg_signal["DBC"], np.mean([0.27, 0.31, 0.32]))
        self.assertAlmostEqual(avg_signal["GLD"], np.mean([0.05, 0.29, 0.34]))
        self.assertAlmostEqual(act.get("EFA", 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()

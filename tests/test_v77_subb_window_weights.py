from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mnt_bot V 7.7 plus.py"


def load_v77_module():
    spec = importlib.util.spec_from_file_location("mnt_bot_v77_window_weights", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V77SubBWindowWeightsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.m = load_v77_module()

    def test_official_subb_windows_use_recent_heavy_weights(self) -> None:
        self.assertEqual(self.m.US_ROT_LBS, (160, 260, 390))
        self.assertEqual(
            self.m.US_ROT_WINDOW_WEIGHTS,
            {160: 0.60, 260: 0.30, 390: 0.10},
        )

    def test_us_mix_target_weights_applies_window_weights(self) -> None:
        original_raw_weights = self.m._us_raw_weights
        by_lb = {
            160: {"QQQ": 1.0},
            260: {"GLD": 1.0},
            390: {"TLT": 1.0},
        }

        def fake_raw_weights(mom_row, vol_row, ranking_codes, top_n, abs_threshold, prev_risky=None, threshold=1.0):
            return by_lb[int(mom_row.name)]

        self.m._us_raw_weights = fake_raw_weights
        try:
            momentum_rows = {
                lb: pd.Series({"QQQ": 1.0, "GLD": 1.0, "TLT": 1.0}, name=lb)
                for lb in self.m.US_ROT_LBS
            }
            vol_row = pd.Series({"QQQ": 0.20, "GLD": 0.20, "TLT": 0.20})

            weights, _per_lb = self.m._us_mix_target_weights(
                momentum_rows,
                vol_row,
                ["QQQ", "GLD", "TLT"],
                scale=1.0,
            )
        finally:
            self.m._us_raw_weights = original_raw_weights

        self.assertAlmostEqual(weights["QQQ"], 0.60)
        self.assertAlmostEqual(weights["GLD"], 0.30)
        self.assertAlmostEqual(weights["TLT"], 0.10)
        self.assertAlmostEqual(weights.get("BIL", 0.0), 0.0)

    def test_user_facing_subb_query_text_is_v77_weighted(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("V7.6 Sub-B", source)
        self.assertNotIn("V7.6收益型", source)
        self.assertNotIn("V7.6 Sub-B收益型", source)
        self.assertNotIn("等权混合", source)
        self.assertNotIn("等权平均", source)

        expected_fragments = [
            "V7.7 active组合",
            "_handle_set_position",
            "_handle_signal",
            "_handle_live_signal",
            "_handle_params",
            "_handle_live_params",
            "US_ROT_WINDOW_WEIGHT_LABEL",
            "加权动量",
        ]
        for fragment in expected_fragments:
            self.assertIn(fragment, source)


if __name__ == "__main__":
    unittest.main()

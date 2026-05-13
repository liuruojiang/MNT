from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "quant_param_scan_runs"
    / "20260512_v76_five_sleeve_real_subd_v16_rebalance_validation"
    / "run_real_subd_v16_rebalance_validation.py"
)


def load_script_module():
    spec = importlib.util.spec_from_file_location("v76_source_returns", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SourceReturnsFreshnessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_script_module()

    def test_required_close_date_uses_previous_business_day(self) -> None:
        required = self.module.latest_required_close_date(pd.Timestamp("2026-05-13"))
        self.assertEqual(required.date().isoformat(), "2026-05-12")

    def test_stale_common_end_fails_with_sleeve_ranges(self) -> None:
        meta = {
            "common_end": "2026-05-11",
            "series_ranges": {
                "Sub-A": {"end": "2026-05-12"},
                "Microcap": {"end": "2026-05-11"},
                "Sub-D": {"end": "2026-05-12"},
            },
        }

        with self.assertRaisesRegex(RuntimeError, "common_end 2026-05-11 < required 2026-05-12") as ctx:
            self.module.validate_common_end_freshness(meta, pd.Timestamp("2026-05-13"))

        message = str(ctx.exception)
        self.assertIn("Microcap: end=2026-05-11", message)
        self.assertIn("Sub-A: end=2026-05-12", message)

    def test_fresh_common_end_passes(self) -> None:
        meta = {
            "common_end": "2026-05-12",
            "series_ranges": {"Microcap": {"end": "2026-05-12"}},
        }

        self.module.validate_common_end_freshness(meta, pd.Timestamp("2026-05-13"))

    def test_advisory_bot_fallback_snapshot_is_close_confirmed(self) -> None:
        import poe_v76_level8_advisory_bot as bot

        latest = pd.Timestamp(bot.LEVEL8_ADVISORY_SNAPSHOT["latest_data_date"])
        required = self.module.latest_required_close_date(pd.Timestamp("2026-05-13"))
        self.assertGreaterEqual(latest, required)


if __name__ == "__main__":
    unittest.main()

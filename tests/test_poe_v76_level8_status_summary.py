from __future__ import annotations

import unittest
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import poe_v76_level8_advisory_bot as bot


class PoeLevel8StatusSummaryTest(unittest.TestCase):
    def test_status_summary_uses_fixed_portfolio_weights(self) -> None:
        snap = dict(bot.LEVEL8_ADVISORY_SNAPSHOT)
        snap["latest_data_date"] = "2026-05-13"
        snap["sleeves"] = [
            {"name": "Sub-A", "weight": 0.15, "role": "dynamic"},
            {"name": "Sub-A-DK", "weight": 0.15, "role": "fixed"},
            {"name": "Microcap", "weight": 0.15, "role": "dynamic"},
            {"name": "Sub-D", "weight": 0.20, "role": "fixed"},
            {"name": "Sub-B", "weight": 0.35, "role": "absorber"},
        ]

        text = bot.render_status_summary(snap)

        self.assertIn("Sub-A 15%", text)
        self.assertIn("Sub-A-DK 15%", text)
        self.assertIn("Microcap 10%", text)
        self.assertIn("Sub-D 20%", text)
        self.assertIn("Sub-B 40%", text)
        self.assertNotIn("Microcap 15%", text)
        self.assertNotIn("Sub-B 35%", text)

    def test_poe_queries_do_not_display_dynamic_position_panel(self) -> None:
        snap = dict(bot.LEVEL8_ADVISORY_SNAPSHOT)
        snap["latest_data_date"] = "2026-05-13"
        outputs = [
            bot.render_level8_advisory(snap),
            bot.render_status_summary(snap),
            bot.render_weights(snap),
            bot.render_governance(snap),
            bot.render_rollback(snap),
        ]

        for text in outputs:
            self.assertNotIn("Dynamic sleeves", text)
            self.assertNotIn("Advisory weight", text)
            self.assertNotIn("dynamic budget", text)
            self.assertNotIn("active budget", text)
            self.assertNotIn("动态仓位", text)
            self.assertNotIn("动态调整", text)

    def test_explicit_old_snapshot_is_marked_stale(self) -> None:
        snap = dict(bot.LEVEL8_ADVISORY_SNAPSHOT)
        snap["latest_data_date"] = "2026-05-12"

        checked = bot._with_snapshot_freshness(
            snap,
            current_date=pd.Timestamp("2026-05-14"),
        )

        self.assertTrue(checked["is_stale"])
        self.assertEqual(checked["required_close_date"], "2026-05-13")
        self.assertEqual(checked["status"], "STALE_SNAPSHOT")


if __name__ == "__main__":
    unittest.main()

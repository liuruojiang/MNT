from __future__ import annotations

import unittest

import pandas as pd

import poe_v76_level8_advisory_bot as bot


class PoeLevel8StatusSummaryTest(unittest.TestCase):
    def test_status_summary_uses_snapshot_weights(self) -> None:
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

        self.assertIn("Microcap 15%", text)
        self.assertIn("Sub-B 35%", text)
        self.assertNotIn("Microcap 10%", text)
        self.assertNotIn("Sub-B 40%", text)

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

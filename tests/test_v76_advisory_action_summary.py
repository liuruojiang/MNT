from __future__ import annotations

import unittest
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_v76_level8_decision_dashboard as dashboard


class AdvisoryActionSummaryTest(unittest.TestCase):
    def test_action_summary_leads_with_current_allocation(self) -> None:
        summary = pd.DataFrame(
            [
                {
                    "scenario": dashboard.FIXED_SCENARIO,
                    "label": "Fixed default",
                    "latest_date": "2026-05-12",
                    "latest_suba": 0.10,
                    "latest_subadk": 0.15,
                    "latest_microcap": 0.15,
                    "latest_subd": 0.20,
                    "latest_subb": 0.40,
                    "dynamic_sleeves": "none",
                    "candidate_status": "BASELINE",
                    "latest_excess_nav_vs_fixed": float("nan"),
                    "full_annual_delta": 0.0,
                    "full_max_dd_delta": 0.0,
                    "full_sharpe_delta": 0.0,
                    "last_1y_annual_delta": 0.0,
                    "last_1y_max_dd_delta": 0.0,
                    "last_1y_sharpe_delta": 0.0,
                    "rebalance_count": 0,
                    "allocation_turnover": 0.0,
                },
                {
                    "scenario": dashboard.STACKED_ADVISORY_SCENARIO,
                    "label": "Stacked Sub-A 5/8 weekly + Microcap 3/10 month-end",
                    "latest_date": "2026-05-12",
                    "latest_suba": 0.15,
                    "latest_subadk": 0.15,
                    "latest_microcap": 0.10,
                    "latest_subd": 0.20,
                    "latest_subb": 0.40,
                    "dynamic_sleeves": "Sub-A,Microcap",
                    "candidate_status": "ACTIVE_DEFAULT",
                    "latest_excess_nav_vs_fixed": 0.2667,
                    "full_annual_delta": 0.0215,
                    "full_max_dd_delta": 0.0072,
                    "full_sharpe_delta": 0.1648,
                    "last_1y_annual_delta": 0.0379,
                    "last_1y_max_dd_delta": 0.0018,
                    "last_1y_sharpe_delta": 0.3440,
                    "rebalance_count": 123,
                    "allocation_turnover": 13.9,
                },
            ]
        )
        decision = {
            "decision_status": "ACTIVE_DEFAULT",
            "data_freshness": "fresh",
            "freshness_note": "scenario curve latest 2026-05-12",
            "latest_date": "2026-05-12",
            "primary_action": "Use stacked active budget.",
            "watch_scenario": dashboard.STACKED_ADVISORY_SCENARIO,
        }

        text = dashboard.render_action_summary(summary, decision)

        self.assertIn("## 今日执行仓位", text)
        self.assertIn("数据日期: `2026-05-12`", text)
        self.assertIn("| Sub-A | 15% | +5pp |", text)
        self.assertIn("| Microcap | 10% | -5pp |", text)
        self.assertIn("| Sub-B | 40% | 0pp |", text)
        self.assertIn("固定回滚线: `10% / 15% / 15% / 20% / 40%`", text)
        self.assertNotIn("Scenario Snapshot", text)


if __name__ == "__main__":
    unittest.main()

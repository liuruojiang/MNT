# V7.6 Level-8 Decision Dashboard

## Decision Status

- Status: **WATCH**
- Data freshness: **fresh** (scenario curve latest 2026-05-13)
- Latest date: `2026-05-13`
- Primary action: Keep fixed default execution; continue observing report-layer candidates.
- Watch scenario: `advisory_suba_microcap_subd_dd_7_10_month_end`

## Scenario Snapshot

| Scenario | Status | Sub-A | Sub-A-DK | Microcap | Sub-D | Sub-B | Dynamic sleeves | Since 2020 annual / MaxDD / Sharpe | 1Y annual / MaxDD / Sharpe | Excess NAV | Switches | Turnover | Note |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---|
| Fixed default | BASELINE | 10% | 15% | 15% | 20% | 40% | none | 41.02% / -7.08% / 4.07 | 61.54% / -5.65% / 5.43 | n/a | 0 | 0.0 | Executable default benchmark. |
| Active Sub-A 5/8 weekly + Microcap 3/10 month-end + Sub-D 7/10 month-end | REPORT_WATCH_ONLY | 10% | 15% | 15% | 20% | 40% | Sub-A,Microcap,Sub-D | 41.52% / -7.70% / 4.06 | 62.93% / -5.74% / 5.51 | 1.67% | 109 | 11.7 | Sub-A + Microcap + Sub-D rule is adopted only when return, Sharpe, and drawdown all improve versus fixed; Sub-A-DK is not a portfolio-layer dynamic sleeve. |
| Sub-A 5/8 weekly advisory | REPORT_WATCH_ONLY | 10% | 15% | 15% | 20% | 40% | Sub-A | 41.44% / -7.08% / 4.08 | 61.54% / -5.65% / 5.43 | 3.42% | 40 | 4.0 | Positive return evidence but max drawdown worsens versus fixed default. |
| Legacy stacked Sub-A 5/8 weekly + Microcap 3/10 month-end | REPORT_WATCH_ONLY | 10% | 15% | 15% | 20% | 40% | Sub-A,Microcap | 41.38% / -7.48% / 4.06 | 61.75% / -5.74% / 5.46 | 4.44% | 76 | 7.9 | Former active A+Microcap advisory; superseded by the Sub-D dynamic-budget candidate. |
| Microcap advisory | DEFER | 10% | 15% | 15% | 20% | 40% | Microcap | 41.04% / -7.88% / 4.02 | 62.41% / -5.87% / 5.45 | -0.44% | 12 | 1.2 | No robust since-2020 improvement versus fixed default. |

## Read

This dashboard is the portfolio-level budget decision surface. The Sub-A 5/8 weekly + Microcap 3/10 month-end + Sub-D 7/10 month-end rule is tracked as the dynamic-budget candidate; fixed weights remain the benchmark and rollback line until a candidate is ACTIVE_DEFAULT.

Status labels: ACTIVE_DEFAULT means the current portfolio-level dynamic budget; LANDING_CANDIDATE means next implementation candidate; REPORT_WATCH_ONLY means useful evidence but not a default; DEFER means not suitable under the current test design.
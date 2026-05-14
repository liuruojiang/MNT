# V7.6 Portfolio Scenario Decision Summary

## Scope

This report compares the fixed five-sleeve benchmark with portfolio-layer dynamic-budget scenarios.
Active dynamic budget default: `advisory_suba_microcap_subd_dd_7_10_month_end`.
Fixed 10/15/15/20/40 remains the benchmark for attribution and rollback.

## Latest Advisory State

- Scenario: `advisory_dd_3_10_month_end`
- Latest date: `2026-05-13`
- Latest Microcap advisory weight: 15.00%
- Latest Sub-B residual weight: 40.00%
- Advisory excess NAV versus fixed: -0.44%

- Scenario: `advisory_suba_dd_5_8_weekly`
- Latest Sub-A advisory weight: 10.00%
- Latest Microcap fixed weight: 15.00%
- Latest Sub-B residual weight: 40.00%
- Sub-A advisory excess NAV versus fixed: 3.42%

- Scenario: `advisory_suba_microcap_subd_dd_7_10_month_end`
- Latest Sub-A advisory weight: 10.00%
- Latest Microcap advisory weight: 15.00%
- Latest Sub-D advisory weight: 20.00%
- Latest Sub-B residual weight: 40.00%
- Active advisory excess NAV versus fixed: 1.67%

## Metric Comparison

| Window | Fixed annual / MaxDD / Sharpe | Microcap advisory annual / MaxDD / Sharpe | Sub-A advisory annual / MaxDD / Sharpe | Active A+Microcap+D annual / MaxDD / Sharpe |
|---|---:|---:|---:|---:|
| Since 2020-01-01 | 41.02% / -7.08% / 4.07 | 41.04% / -7.88% / 4.02 | 41.44% / -7.08% / 4.08 | 41.52% / -7.70% / 4.06 |
| 1Y | 61.54% / -5.65% / 5.43 | 62.41% / -5.87% / 5.45 | 61.54% / -5.65% / 5.43 | 62.93% / -5.74% / 5.51 |

## Decision

Use `advisory_suba_microcap_subd_dd_7_10_month_end` as the active portfolio-level dynamic budget. Keep Sub-A-only, Microcap-only, and A+Microcap-only rules as report-layer comparisons.
# V7.6 Portfolio Scenario Decision Summary

## Scope

This report compares the fixed five-sleeve benchmark with portfolio-layer dynamic-budget scenarios.
Active dynamic budget default: `advisory_suba_microcap_dd_3_10_month_end`.
Fixed 10/15/15/20/40 remains the benchmark for attribution and rollback.

## Latest Advisory State

- Scenario: `advisory_dd_3_10_month_end`
- Latest date: `2026-05-11`
- Latest Microcap advisory weight: 10.00%
- Latest Sub-B absorbing weight: 45.00%
- Advisory excess NAV versus fixed: 9.64%

- Scenario: `advisory_suba_dd_5_8_weekly`
- Latest Sub-A advisory weight: 15.00%
- Latest Microcap fixed weight: 15.00%
- Latest Sub-B absorbing weight: 35.00%
- Sub-A advisory excess NAV versus fixed: 15.22%

- Scenario: `advisory_suba_microcap_dd_3_10_month_end`
- Latest Sub-A advisory weight: 15.00%
- Latest Microcap advisory weight: 10.00%
- Latest Sub-B absorbing weight: 40.00%
- Stacked advisory excess NAV versus fixed: 26.32%

## Metric Comparison

| Window | Fixed annual / MaxDD / Sharpe | Microcap advisory annual / MaxDD / Sharpe | Sub-A advisory annual / MaxDD / Sharpe | Stacked advisory annual / MaxDD / Sharpe |
|---|---:|---:|---:|---:|
| Full | 30.79% / -8.11% / 3.32 | 31.63% / -8.16% / 3.40 | 32.08% / -7.22% / 3.40 | 32.93% / -7.27% / 3.48 |
| 1Y | 60.67% / -5.50% / 5.32 | 62.06% / -5.73% / 5.41 | 63.03% / -5.10% / 5.56 | 64.45% / -5.33% / 5.66 |

## Decision

Use `advisory_suba_microcap_dd_3_10_month_end` as the active portfolio-level dynamic budget. Keep Sub-A-only and Microcap-only rules as report-layer comparisons.
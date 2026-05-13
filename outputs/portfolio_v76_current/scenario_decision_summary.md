# V7.6 Portfolio Scenario Decision Summary

## Scope

This report compares the fixed five-sleeve benchmark with portfolio-layer dynamic-budget scenarios.
Active dynamic budget default: `advisory_suba_microcap_dd_3_10_month_end`.
Fixed 10/15/15/20/40 remains the benchmark for attribution and rollback.

## Latest Advisory State

- Scenario: `advisory_dd_3_10_month_end`
- Latest date: `2026-05-08`
- Latest Microcap advisory weight: 10.00%
- Latest Sub-B absorbing weight: 45.00%
- Advisory excess NAV versus fixed: 9.57%

- Scenario: `advisory_suba_dd_5_8_weekly`
- Latest Sub-A advisory weight: 15.00%
- Latest Microcap fixed weight: 15.00%
- Latest Sub-B absorbing weight: 35.00%
- Sub-A advisory excess NAV versus fixed: 14.99%

- Scenario: `advisory_suba_microcap_dd_3_10_month_end`
- Latest Sub-A advisory weight: 15.00%
- Latest Microcap advisory weight: 10.00%
- Latest Sub-B absorbing weight: 40.00%
- Stacked advisory excess NAV versus fixed: 25.99%

## Metric Comparison

| Window | Fixed annual / MaxDD / Sharpe | Microcap advisory annual / MaxDD / Sharpe | Sub-A advisory annual / MaxDD / Sharpe | Stacked advisory annual / MaxDD / Sharpe |
|---|---:|---:|---:|---:|
| Full | 30.70% / -8.11% / 3.31 | 31.53% / -8.16% / 3.39 | 31.97% / -7.22% / 3.39 | 32.81% / -7.27% / 3.47 |
| 1Y | 59.46% / -5.50% / 5.24 | 60.72% / -5.73% / 5.32 | 61.72% / -5.10% / 5.49 | 63.00% / -5.33% / 5.58 |

## Decision

Use `advisory_suba_microcap_dd_3_10_month_end` as the active portfolio-level dynamic budget. Keep Sub-A-only and Microcap-only rules as report-layer comparisons.
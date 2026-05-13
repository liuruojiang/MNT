# V7.6 Portfolio Scenario Decision Summary

## Scope

This report compares the fixed five-sleeve benchmark with portfolio-layer dynamic-budget scenarios.
Active dynamic budget default: `advisory_suba_microcap_dd_3_10_month_end`.
Fixed 10/15/15/20/40 remains the benchmark for attribution and rollback.

## Latest Advisory State

- Scenario: `advisory_dd_3_10_month_end`
- Latest date: `2026-05-12`
- Latest Microcap advisory weight: 10.00%
- Latest Sub-B absorbing weight: 45.00%
- Advisory excess NAV versus fixed: 9.69%

- Scenario: `advisory_suba_dd_5_8_weekly`
- Latest Sub-A advisory weight: 15.00%
- Latest Microcap fixed weight: 15.00%
- Latest Sub-B absorbing weight: 35.00%
- Sub-A advisory excess NAV versus fixed: 15.48%

- Scenario: `advisory_suba_microcap_dd_3_10_month_end`
- Latest Sub-A advisory weight: 15.00%
- Latest Microcap advisory weight: 10.00%
- Latest Sub-B absorbing weight: 40.00%
- Stacked advisory excess NAV versus fixed: 26.67%

## Metric Comparison

| Window | Fixed annual / MaxDD / Sharpe | Microcap advisory annual / MaxDD / Sharpe | Sub-A advisory annual / MaxDD / Sharpe | Stacked advisory annual / MaxDD / Sharpe |
|---|---:|---:|---:|---:|
| Full | 30.43% / -7.87% / 3.28 | 31.27% / -7.92% / 3.36 | 31.74% / -7.10% / 3.36 | 32.58% / -7.16% / 3.44 |
| 1Y | 59.24% / -5.50% / 5.19 | 60.69% / -5.73% / 5.28 | 61.56% / -5.10% / 5.43 | 63.04% / -5.33% / 5.53 |

## Decision

Use `advisory_suba_microcap_dd_3_10_month_end` as the active portfolio-level dynamic budget. Keep Sub-A-only and Microcap-only rules as report-layer comparisons.
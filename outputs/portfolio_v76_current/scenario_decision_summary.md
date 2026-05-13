# V7.6 Portfolio Scenario Decision Summary

## Scope

This report compares the fixed five-sleeve benchmark with portfolio-layer dynamic-budget scenarios.
Active dynamic budget default: `advisory_suba_microcap_dd_3_10_month_end`.
Fixed 10/15/15/20/40 remains the benchmark for attribution and rollback.

## Latest Advisory State

- Scenario: `advisory_dd_3_10_month_end`
- Latest date: `2026-05-13`
- Latest Microcap advisory weight: 15.00%
- Latest Sub-B absorbing weight: 40.00%
- Advisory excess NAV versus fixed: 10.53%

- Scenario: `advisory_suba_dd_5_8_weekly`
- Latest Sub-A advisory weight: 15.00%
- Latest Microcap fixed weight: 15.00%
- Latest Sub-B absorbing weight: 35.00%
- Sub-A advisory excess NAV versus fixed: 15.32%

- Scenario: `advisory_suba_microcap_dd_3_10_month_end`
- Latest Sub-A advisory weight: 15.00%
- Latest Microcap advisory weight: 15.00%
- Latest Sub-B absorbing weight: 35.00%
- Stacked advisory excess NAV versus fixed: 27.46%

## Metric Comparison

| Window | Fixed annual / MaxDD / Sharpe | Microcap advisory annual / MaxDD / Sharpe | Sub-A advisory annual / MaxDD / Sharpe | Stacked advisory annual / MaxDD / Sharpe |
|---|---:|---:|---:|---:|
| Full | 30.60% / -8.11% / 3.33 | 31.51% / -8.16% / 3.43 | 31.90% / -7.22% / 3.42 | 32.82% / -7.36% / 3.51 |
| 1Y | 61.54% / -5.65% / 5.43 | 62.82% / -5.87% / 5.54 | 64.14% / -5.29% / 5.70 | 65.44% / -5.51% / 5.81 |

## Decision

Use `advisory_suba_microcap_dd_3_10_month_end` as the active portfolio-level dynamic budget. Keep Sub-A-only and Microcap-only rules as report-layer comparisons.
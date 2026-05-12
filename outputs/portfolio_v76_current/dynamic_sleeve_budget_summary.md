# V7.6 Dynamic Sleeve Budget Scan

## Scope

Each candidate applies the same prior-NAV-drawdown rule to one sleeve only. Sub-B absorbs the weight delta. This is research output only and does not change executable defaults.

Rule: month-end execution, +5pp when prior sleeve drawdown is within 3%, -5pp when prior drawdown is at or below -10%, otherwise base weight.

## Candidate Summary

| Candidate | Sleeve | Full Ann. Delta | Full MaxDD Delta | Full Sharpe Delta | 1Y Ann. Delta | 1Y Sharpe Delta | Latest sleeve | Latest Sub-B | Switches | Turnover |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `advisory_suba_dd_3_10_month_end` | Sub-A | 0.55% | 0.39% | +0.01 | 2.34% | +0.25 | 15.00% | 35.00% | 47 | 5.3 |
| `advisory_subadk_dd_3_10_month_end` | Sub-A-DK | 0.00% | -0.84% | -0.02 | 0.53% | +0.01 | 10.00% | 45.00% | 74 | 7.9 |
| `advisory_microcap_dd_3_10_month_end` | Microcap | 0.88% | -0.05% | +0.09 | 2.06% | +0.14 | 10.00% | 45.00% | 59 | 6.3 |
| `advisory_subd_dd_3_10_month_end` | Sub-D | -0.25% | -0.08% | -0.04 | 2.25% | +0.16 | 25.00% | 35.00% | 81 | 8.9 |
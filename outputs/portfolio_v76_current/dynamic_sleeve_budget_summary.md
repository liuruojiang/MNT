# V7.6 Dynamic Sleeve Budget Scan

## Scope

Each candidate applies the same prior-NAV-drawdown rule to one sleeve only. Sub-B absorbs the weight delta. This is research output only and does not change executable defaults.

Rule: month-end execution, +5pp when prior sleeve drawdown is within 3%, -5pp when prior drawdown is at or below -10%, otherwise base weight.

## Candidate Summary

| Candidate | Sleeve | Full Ann. Delta | Full MaxDD Delta | Full Sharpe Delta | 1Y Ann. Delta | 1Y Sharpe Delta | Latest sleeve | Latest Sub-B | Switches | Turnover |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `advisory_suba_dd_3_10_month_end` | Sub-A | 0.58% | 0.50% | +0.01 | 2.67% | +0.27 | 15.00% | 35.00% | 51 | 5.7 |
| `advisory_subadk_dd_3_10_month_end` | Sub-A-DK | 0.07% | -0.84% | -0.01 | 0.58% | +0.02 | 10.00% | 45.00% | 74 | 7.9 |
| `advisory_microcap_dd_3_10_month_end` | Microcap | 0.81% | -0.05% | +0.08 | 0.93% | +0.06 | 15.00% | 40.00% | 58 | 6.2 |
| `advisory_subd_dd_3_10_month_end` | Sub-D | -0.24% | -0.08% | -0.04 | 2.37% | +0.16 | 25.00% | 35.00% | 81 | 8.9 |
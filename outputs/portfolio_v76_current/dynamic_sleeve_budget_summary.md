# V7.6 Dynamic Sleeve Budget Scan

## Scope

Each candidate applies the same prior-NAV-drawdown rule to one sleeve only. Sub-A-DK is excluded because it already has an internal DD RiskGate. Sub-B receives unused cut budget but does not fund unmatched boost requests. This is research output only and does not change executable defaults.

Rule: month-end execution, +5pp when prior sleeve drawdown is within 3%, -5pp when prior drawdown is at or below -10%, otherwise base weight.

## Candidate Summary

| Candidate | Sleeve | Since 2020 Ann. Delta | Since 2020 MaxDD Delta | Since 2020 Sharpe Delta | 1Y Ann. Delta | 1Y Sharpe Delta | Latest sleeve | Latest Sub-B | Switches | Turnover |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `advisory_suba_dd_3_10_month_end` | Sub-A | -0.20% | 0.00% | -0.04 | -0.00% | -0.00 | 10.00% | 40.00% | 22 | 2.2 |
| `advisory_microcap_dd_3_10_month_end` | Microcap | 0.02% | -0.80% | -0.05 | 0.87% | +0.01 | 15.00% | 40.00% | 12 | 1.2 |
| `advisory_subd_dd_3_10_month_end` | Sub-D | -0.07% | -0.00% | -0.00 | 0.42% | +0.04 | 20.00% | 40.00% | 30 | 3.0 |
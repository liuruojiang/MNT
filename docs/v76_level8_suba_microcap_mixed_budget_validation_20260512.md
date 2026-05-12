# V7.6 Level-8 Sub-A + Microcap Mixed Dynamic Budget Validation - 2026-05-12

## Scope

This note records the corrected four-scenario portfolio-layer validation after separating two layers:

- Microcap own strategy layer: v1.6 uses target-vol 25% with max leverage 1.5x.
- Portfolio budget layer: Sub-A and Microcap can each have an advisory budget rule, with Sub-B absorbing the delta.

The corrected stacked portfolio scenario is:

- Sub-A: prior Sub-A NAV DD within 5% -> 15%; below -8% -> 5%; otherwise 10%; weekly execution.
- Microcap: prior Microcap NAV DD within 3% -> 20%; below -10% -> 10%; otherwise 15%; confirmed month-end execution.
- Sub-B absorbs both deltas.
- Sub-A-DK stays 15%, Sub-D stays 20%.

This supersedes any older wording that described the stacked scenario as both sleeves using `3/10 month_end`.

## Commands

```powershell
python -m unittest discover -s tests -p 'test_build_v76_portfolio_nav.py' -v
python -m unittest discover -s tests -p 'test_build_v76_level8_decision_dashboard.py' -v
python -m unittest discover -s tests -p 'test_v76_combo_advisory_display.py' -v
python -m py_compile build_v76_portfolio_nav.py build_v76_level8_decision_dashboard.py 'mnt_bot V 7.6 plus.py'
python build_v76_portfolio_nav.py
python build_v76_level8_decision_dashboard.py
```

All tests and compile checks passed.

## Data

- Aligned return source: `quant_param_scan_runs/20260512_v76_five_sleeve_real_subd_v16_rebalance_validation/aligned_five_sleeve_real_subd_returns.csv`
- Portfolio manifest: `portfolio_manifests/v76_current.json`
- Common sample: 2011-12-09 to 2026-05-08
- Rows: 3743
- Output directory: `outputs/portfolio_v76_current/`

## Four-Scenario Result

| Scenario | Full annual | Full MaxDD | Full Sharpe | 1Y annual | 1Y MaxDD | 1Y Sharpe | Latest Sub-A | Latest Microcap | Latest Sub-B | Switches | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fixed 10/15/15/20/40 | 30.38% | -7.87% | 3.27 | 59.01% | -5.71% | 5.21 | 10% | 15% | 40% | 0 | 0.0 |
| Sub-A 5/8 weekly only | 31.67% | -7.10% | 3.36 | 61.26% | -5.24% | 5.46 | 15% | 15% | 35% | 68 | 7.7 |
| Microcap 3/10 month-end only | 31.26% | -7.92% | 3.36 | 61.07% | -5.73% | 5.35 | 10% | 10% | 45% | 59 | 6.3 |
| Sub-A 5/8 weekly + Microcap 3/10 month-end | 32.56% | -7.16% | 3.44 | 63.36% | -5.33% | 5.61 | 15% | 10% | 40% | 123 | 13.9 |

## Read

The mixed stacked line is promoted from watch-only to the active portfolio-level dynamic budget. It has the best full-sample annual return and Sharpe among the four local scenarios, improves drawdown versus fixed, and still keeps the latest Sub-B absorber weight at 40%.

Microcap 3/10 month-end remains `REPORT_WATCH_ONLY`. It improves return and Sharpe, but full-sample MaxDD is slightly worse than fixed.

Sub-A 5/8 weekly only is retained as a report-layer comparison and fallback reference. It remains cleaner operationally, but it is no longer the active dynamic-budget default after the stacked promotion.

Current latest weights from the corrected stacked line:

- Sub-A 15%
- Sub-A-DK 15%
- Microcap 10%
- Sub-D 20%
- Sub-B 40%

## Decision

Promote the stacked dynamic budget to active default.

Use:

- Active default: `advisory_suba_microcap_dd_3_10_month_end`
- Report-layer comparison: Sub-A-only `advisory_suba_dd_5_8_weekly` and Microcap-only `advisory_dd_3_10_month_end`
- Benchmark and rollback: fixed `10/15/15/20/40`

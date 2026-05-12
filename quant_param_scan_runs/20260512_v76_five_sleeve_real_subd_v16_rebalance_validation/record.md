# V7.6 Five-Sleeve Real Sub-D V1.6 Validation

## Scope

This run corrects the combo definition to:

`Sub-A / Sub-A-DK / Microcap / Sub-D / Sub-B = 10 / 15 / 15 / 20 / 40`.

Sub-D is the real six-ETF `v1.1_staged_50_plus_ma60_overheat` strategy loaded read-only from git HEAD. The deleted working-tree files were not restored.

## Data

- V7.6 source: `mnt_bot V 7.6 plus.py`
- Microcap source: `sibling_repo_outputs/microcap_top100_mom16_targetvol25_max1p5_v1_6_costed_nav.csv`
- Sub-D source: `git HEAD:run_subd_six_etf_v1_1.py + git HEAD:research_subd_six_etf_weighted_slope.py`
- Sub-D data source: `akshare.fund_etf_hist_sina raw close`
- Common start: `2011-12-09`
- Common end: `2026-05-08`
- Aligned daily rows: `3743`
- Signal timing: Microcap weight target for date `t` uses Microcap NAV information through `t-1`.

## Results

Metrics are annual return / daily max drawdown / Sharpe.

| Candidate | Full | Latest 1Y |
|---|---:|---:|
| Fixed `10/15/15/20/40` | 30.38% / -7.87% / 3.27 | 59.01% / -5.71% / 5.21 |
| `dd_3_10_daily` | 31.45% / -7.76% / 3.38 | 62.41% / -5.51% / 5.53 |
| `dd_3_10_month_end` | 31.26% / -7.92% / 3.36 | 61.07% / -5.73% / 5.35 |

## Latest Executed Weights

For `dd_3_10_month_end`, latest Microcap weight is 10%; latest Sub-B weight is 45%.

## Decision

Decision: `real_subd_five_sleeve_validation_completed`.

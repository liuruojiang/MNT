# V7.6 Five-Sleeve Real Sub-D V2.0 Validation

## Scope

This run corrects the combo definition to:

`Sub-A / Sub-A-DK / Microcap / Sub-D / Sub-B = 10 / 15 / 15 / 20 / 40`.

Sub-D is the real six-ETF `v1.1_staged_50_plus_ma60_overheat` strategy loaded read-only from git HEAD. The deleted working-tree files were not restored.

## Data

- V7.6 source: `mnt_bot V 7.6 plus.py`
- Microcap source: `sibling_repo_outputs/microcap_top100_mom16_targetvol25_max1p5_v2_0_costed_nav.csv`
- Sub-D source: `git 885fbf4178d01cbd3aba11035e28ba172cc4221b:run_subd_six_etf_v1_1.py + git 885fbf4178d01cbd3aba11035e28ba172cc4221b:research_subd_six_etf_weighted_slope.py`
- Sub-D data source: `akshare.fund_etf_hist_sina raw close`
- Common start: `2011-12-09`
- Common end: `2026-05-13`
- Aligned daily rows: `3746`
- Signal timing: Microcap weight target for date `t` uses Microcap NAV information through `t-1`.

## Results

Metrics are annual return / daily max drawdown / Sharpe.

| Candidate | Full | Latest 1Y |
|---|---:|---:|
| Fixed `10/15/15/20/40` | 30.60% / -8.11% / 3.33 | 61.54% / -5.65% / 5.43 |
| `dd_3_10_daily` | 31.61% / -7.99% / 3.44 | 63.47% / -5.35% / 5.64 |
| `dd_3_10_month_end` | 31.51% / -8.16% / 3.43 | 62.82% / -5.87% / 5.54 |

## Latest Executed Weights

For `dd_3_10_month_end`, latest Microcap weight is 15%; latest Sub-B weight is 40%.

## Decision

Decision: `real_subd_five_sleeve_validation_completed`.

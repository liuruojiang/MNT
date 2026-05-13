# V7.6 Five-Sleeve Real Sub-D V1.6 Validation

## Scope

This run corrects the combo definition to:

`Sub-A / Sub-A-DK / Microcap / Sub-D / Sub-B = 10 / 15 / 15 / 20 / 40`.

Sub-D is the real six-ETF `v1.1_staged_50_plus_ma60_overheat` strategy loaded read-only from git HEAD. The deleted working-tree files were not restored.

## Data

- V7.6 source: `mnt_bot V 7.6 plus.py`
- Microcap source: `sibling_repo_outputs/microcap_top100_mom16_targetvol25_max1p5_v1_6_costed_nav.csv`
- Sub-D source: `git 885fbf4178d01cbd3aba11035e28ba172cc4221b:run_subd_six_etf_v1_1.py + git 885fbf4178d01cbd3aba11035e28ba172cc4221b:research_subd_six_etf_weighted_slope.py`
- Sub-D data source: `akshare.fund_etf_hist_sina raw close`
- Common start: `2011-12-09`
- Common end: `2026-05-12`
- Aligned daily rows: `3745`
- Signal timing: Microcap weight target for date `t` uses Microcap NAV information through `t-1`.

## Results

Metrics are annual return / daily max drawdown / Sharpe.

| Candidate | Full | Latest 1Y |
|---|---:|---:|
| Fixed `10/15/15/20/40` | 30.43% / -7.87% / 3.28 | 59.24% / -5.50% / 5.19 |
| `dd_3_10_daily` | 31.49% / -7.76% / 3.39 | 62.57% / -5.18% / 5.50 |
| `dd_3_10_month_end` | 31.27% / -7.92% / 3.36 | 60.69% / -5.73% / 5.28 |

## Latest Executed Weights

For `dd_3_10_month_end`, latest Microcap weight is 10%; latest Sub-B weight is 45%.

## Decision

Decision: `real_subd_five_sleeve_validation_completed`.

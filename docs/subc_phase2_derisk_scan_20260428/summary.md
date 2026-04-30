# Sub-C Phase2 drawdown derisk parameter scan - 2026-04-28

## Method

- Production file: `mnt_bot V 7.1 plus.py`
- Sub-C parity max_abs_diff: `0`
- Effective-scale cost parity max_abs_diff: `0`
- Gate: Phase2-only, from `BTC_BT_START` onward.
- Grid: trigger drawdown 3%-8%, cut 10%-50%, recover drawdown 1%-4%; invalid recover >= trigger rows excluded.
- References tested: `baseline_nav` and `self_nav` drawdown.
- Robustness tag requires near-baseline full return/Sharpe, at least 3 percentage points Phase2 max-dd improvement, and no large post-2022/recent-1Y return damage.

## Overfit read

The strict no-overfit filter found no `robust_candidate` rows. That is a warning: every useful row still pays for the 2022 protection with some post-2022 or recent-1Y return drag.

This is not a single-point curve fit, though. A looser defensive platform exists: 40 rows keep full annual return near baseline, improve Sharpe, and reduce max drawdown. The cluster is concentrated around:

- trigger drawdown: 3%-4%, with some acceptable rows up to 5%-7%;
- cut: 25%-40%;
- recover drawdown: mostly 2%-3%;
- reference: `baseline_nav` is more stable than `self_nav`.

Practical conclusion: treat Phase2-only drawdown derisk as a defensive overlay candidate, not as a confirmed alpha improvement. The least curve-fit candidate is closer to `baseline_nav`, trigger 4%, cut 25%-30%, recover 2%-2.5%, not the single best row.

## Baseline

|               |   full_ann_return |   full_sharpe |   full_max_dd |   full_calmar |   phase2_total_return |   phase2_max_dd |   recent_1y_total_return |   recent_1y_max_dd |
|:--------------|------------------:|--------------:|--------------:|--------------:|----------------------:|----------------:|-------------------------:|-------------------:|
| baseline_subc |          0.118695 |      0.876262 |     -0.234003 |      0.507238 |              0.650388 |       -0.223645 |                 0.297993 |          -0.116247 |

## Top robust candidates

No rows passed the robust_candidate filter.

## Parameter platform

No robust parameter platform found.

## Looser defensive platform

| platform | count | read |
|:--|--:|:--|
| trigger 4%, cut 25% | 9 | most repeated relaxed cluster; practical default zone |
| trigger 4%, cut 30% | 6 | similar, slightly more defensive |
| trigger 3%, cut 25% | 4 | earlier trigger, more activity |
| trigger 4%, cut 35% | 4 | stronger protection, more return drag |

Representative rows:

| variant | full ann | full Sharpe | full max DD | phase2 total | phase2 max DD | recent 1Y |
|:--|--:|--:|--:|--:|--:|--:|
| phase2_baseline_nav_trigger0.040_cut0.25_recover0.020 | 11.81% | 0.92 | -18.70% | 63.50% | -17.59% | 28.03% |
| phase2_baseline_nav_trigger0.040_cut0.30_recover0.020 | 11.79% | 0.92 | -18.70% | 63.05% | -16.62% | 27.66% |
| phase2_self_nav_trigger0.040_cut0.35_recover0.030 | 11.81% | 0.93 | -18.70% | 63.60% | -15.65% | 27.76% |

## Top by full Calmar

| variant                                               | reference    |   trigger_dd |   cut |   recover_dd |   full_ann_return |   full_sharpe |   full_max_dd |   full_calmar |   phase2_total_return |   phase2_max_dd | robustness     |
|:------------------------------------------------------|:-------------|-------------:|------:|-------------:|------------------:|--------------:|--------------:|--------------:|----------------------:|----------------:|:---------------|
| phase2_self_nav_trigger0.040_cut0.35_recover0.030     | self_nav     |         0.04 |  0.35 |        0.03  |          0.118097 |      0.930193 |     -0.186968 |      0.631642 |              0.635953 |       -0.156499 | defensive_only |
| phase2_baseline_nav_trigger0.030_cut0.25_recover0.020 | baseline_nav |         0.03 |  0.25 |        0.02  |          0.118092 |      0.918105 |     -0.186968 |      0.631615 |              0.635832 |       -0.174238 | defensive_only |
| phase2_baseline_nav_trigger0.040_cut0.25_recover0.020 | baseline_nav |         0.04 |  0.25 |        0.02  |          0.118056 |      0.915838 |     -0.186968 |      0.63142  |              0.634958 |       -0.175892 | defensive_only |
| phase2_self_nav_trigger0.040_cut0.40_recover0.030     | self_nav     |         0.04 |  0.4  |        0.03  |          0.118051 |      0.936517 |     -0.186968 |      0.631396 |              0.634847 |       -0.146712 | defensive_only |
| phase2_baseline_nav_trigger0.040_cut0.25_recover0.025 | baseline_nav |         0.04 |  0.25 |        0.025 |          0.117969 |      0.914378 |     -0.186968 |      0.630957 |              0.632878 |       -0.175892 | defensive_only |
| phase2_baseline_nav_trigger0.030_cut0.30_recover0.020 | baseline_nav |         0.03 |  0.3  |        0.02  |          0.117912 |      0.925098 |     -0.186968 |      0.630652 |              0.631513 |       -0.164187 | defensive_only |
| phase2_self_nav_trigger0.040_cut0.25_recover0.025     | self_nav     |         0.04 |  0.25 |        0.025 |          0.117908 |      0.91395  |     -0.186968 |      0.630632 |              0.631423 |       -0.175892 | defensive_only |
| phase2_baseline_nav_trigger0.040_cut0.30_recover0.020 | baseline_nav |         0.04 |  0.3  |        0.02  |          0.117871 |      0.922409 |     -0.186968 |      0.630436 |              0.630542 |       -0.166218 | defensive_only |
| phase2_baseline_nav_trigger0.040_cut0.30_recover0.025 | baseline_nav |         0.04 |  0.3  |        0.025 |          0.117768 |      0.920661 |     -0.186968 |      0.629884 |              0.628074 |       -0.166218 | defensive_only |
| phase2_baseline_nav_trigger0.030_cut0.35_recover0.020 | baseline_nav |         0.03 |  0.35 |        0.02  |          0.117686 |      0.931334 |     -0.186968 |      0.629445 |              0.62611  |       -0.154081 | defensive_only |
| phase2_baseline_nav_trigger0.040_cut0.35_recover0.020 | baseline_nav |         0.04 |  0.35 |        0.02  |          0.117643 |      0.928245 |     -0.186968 |      0.629214 |              0.625079 |       -0.156499 | defensive_only |
| phase2_self_nav_trigger0.040_cut0.30_recover0.030     | self_nav     |         0.04 |  0.3  |        0.03  |          0.117608 |      0.918576 |     -0.186968 |      0.629025 |              0.624235 |       -0.166218 | defensive_only |
| phase2_baseline_nav_trigger0.040_cut0.35_recover0.025 | baseline_nav |         0.04 |  0.35 |        0.025 |          0.117524 |      0.926218 |     -0.186968 |      0.62858  |              0.622249 |       -0.156499 | defensive_only |
| phase2_self_nav_trigger0.040_cut0.30_recover0.025     | self_nav     |         0.04 |  0.3  |        0.025 |          0.117496 |      0.918659 |     -0.186968 |      0.628429 |              0.621575 |       -0.166218 | defensive_only |
| phase2_self_nav_trigger0.030_cut0.25_recover0.025     | self_nav     |         0.03 |  0.25 |        0.025 |          0.11745  |      0.912543 |     -0.186968 |      0.628182 |              0.620479 |       -0.174238 | defensive_only |

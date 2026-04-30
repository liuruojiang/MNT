# Sub-C drawdown derisk overlay - 2026-04-28

## Method

- Production file: `mnt_bot V 7.1 plus.py`
- Return path: `_compute_daily_subc_phased()` plus official Sub-C vol scaling semantics.
- Parity check against `_get_subc_daily_ret()`: max absolute difference `0`.
- Execution: drawdown is measured after the previous close; budget changes apply on the next Sub-C trading day.
- Overlay: final effective scale = official `actual_scale` times the drawdown budget.
- High-scale gate: budget may activate only when official `actual_scale > 1.25x`.
- Phase2 gate: budget may activate only from `BTC_BT_START` onward.
- Costs: recomputed from final effective scale with official spread and rebalance cost parameters.

## Main read

The targeted gates are materially better than the full-history drawdown overlay. Baseline Sub-C has annual return 11.87%, max drawdown -23.40%, Sharpe 0.88, and Calmar 0.51.

The best Calmar row is `phase2_only_baseline_nav_dd5_cut30_recover2` with annual return 11.69%, max drawdown -18.70%, Sharpe 0.91, and Calmar 0.63. This keeps most of the baseline return while reducing drawdown materially.

The best Sharpe row is `phase2_only_baseline_nav_dd7_cut50_recover3` with annual return 11.55%, max drawdown -18.70%, Sharpe 0.92, and Calmar 0.62.

Practical read: Phase2-only is the useful gate. High-scale-only by itself reduces return without enough drawdown improvement, so it should not be the next production candidate.

## Best rows by Calmar

| variant                                      |   ann_return |   ann_vol |   sharpe |    max_dd |   calmar |     ulcer |   final_nav |
|:---------------------------------------------|-------------:|----------:|---------:|----------:|---------:|----------:|------------:|
| phase2_only_baseline_nav_dd5_cut30_recover2  |    0.116936  |  0.128154 | 0.912464 | -0.186968 | 0.625431 | 0.0598886 |     6.14939 |
| phase2_only_self_nav_dd5_cut30_recover2      |    0.116389  |  0.128023 | 0.909133 | -0.186968 | 0.622509 | 0.0599051 |     6.10019 |
| phase2_only_baseline_nav_dd7_cut50_recover3  |    0.115522  |  0.126082 | 0.916245 | -0.186968 | 0.61787  | 0.0575141 |     6.0228  |
| phase2_only_baseline_nav_dd3_cut20_recover1  |    0.116987  |  0.129742 | 0.901689 | -0.195108 | 0.5996   | 0.06113   |     6.154   |
| phase2_only_self_nav_dd3_cut20_recover1      |    0.116674  |  0.129544 | 0.90065  | -0.195108 | 0.597995 | 0.0611115 |     6.12573 |
| phase2_only_baseline_nav_dd10_cut50_recover5 |    0.111216  |  0.127899 | 0.869558 | -0.186968 | 0.594837 | 0.0619014 |     5.65209 |
| phase2_only_self_nav_dd7_cut50_recover3      |    0.11014   |  0.125492 | 0.877663 | -0.186968 | 0.589081 | 0.0581264 |     5.56285 |
| baseline_nav_dd7_cut50_recover3              |    0.0889508 |  0.111374 | 0.798667 | -0.151482 | 0.587204 | 0.0612828 |     4.05357 |

## Full summary

| variant                                            |   ann_return |   ann_vol |   sharpe |    max_dd |   calmar |     ulcer |   final_nav |
|:---------------------------------------------------|-------------:|----------:|---------:|----------:|---------:|----------:|------------:|
| baseline_subc                                      |    0.118675  |  0.135458 | 0.876101 | -0.234003 | 0.507151 | 0.0670577 |     6.30855 |
| self_nav_dd3_cut20_recover1                        |    0.101339  |  0.116116 | 0.872743 | -0.196196 | 0.516521 | 0.0578523 |     4.88123 |
| phase2_only_self_nav_dd3_cut20_recover1            |    0.116674  |  0.129544 | 0.90065  | -0.195108 | 0.597995 | 0.0611115 |     6.12573 |
| high_scale_only_self_nav_dd3_cut20_recover1        |    0.112106  |  0.126062 | 0.889292 | -0.223798 | 0.500926 | 0.060853  |     5.72695 |
| phase2_high_scale_self_nav_dd3_cut20_recover1      |    0.1182    |  0.13317  | 0.887587 | -0.2211   | 0.534601 | 0.0640903 |     6.26476 |
| baseline_nav_dd3_cut20_recover1                    |    0.101246  |  0.117389 | 0.862486 | -0.200736 | 0.504374 | 0.0594385 |     4.87442 |
| phase2_only_baseline_nav_dd3_cut20_recover1        |    0.116987  |  0.129742 | 0.901689 | -0.195108 | 0.5996   | 0.06113   |     6.154   |
| high_scale_only_baseline_nav_dd3_cut20_recover1    |    0.111831  |  0.126194 | 0.886188 | -0.223798 | 0.499697 | 0.0611401 |     5.70373 |
| phase2_high_scale_baseline_nav_dd3_cut20_recover1  |    0.118076  |  0.133135 | 0.886887 | -0.2211   | 0.534039 | 0.0640876 |     6.25332 |
| self_nav_dd5_cut30_recover2                        |    0.0966187 |  0.111706 | 0.864936 | -0.181697 | 0.531758 | 0.0574673 |     4.54871 |
| phase2_only_self_nav_dd5_cut30_recover2            |    0.116389  |  0.128023 | 0.909133 | -0.186968 | 0.622509 | 0.0599051 |     6.10019 |
| high_scale_only_self_nav_dd5_cut30_recover2        |    0.110933  |  0.126347 | 0.878007 | -0.225645 | 0.491626 | 0.0623539 |     5.62853 |
| phase2_high_scale_self_nav_dd5_cut30_recover2      |    0.117573  |  0.132918 | 0.884547 | -0.220771 | 0.532553 | 0.0642665 |     6.20724 |
| baseline_nav_dd5_cut30_recover2                    |    0.0979013 |  0.114943 | 0.85174  | -0.191995 | 0.509916 | 0.0609851 |     4.63689 |
| phase2_only_baseline_nav_dd5_cut30_recover2        |    0.116936  |  0.128154 | 0.912464 | -0.186968 | 0.625431 | 0.0598886 |     6.14939 |
| high_scale_only_baseline_nav_dd5_cut30_recover2    |    0.112354  |  0.127054 | 0.884302 | -0.229301 | 0.489984 | 0.0632635 |     5.74792 |
| phase2_high_scale_baseline_nav_dd5_cut30_recover2  |    0.117797  |  0.132909 | 0.886299 | -0.220771 | 0.533572 | 0.0642629 |     6.22778 |
| self_nav_dd7_cut50_recover3                        |    0.0771295 |  0.100258 | 0.769314 | -0.151482 | 0.509167 | 0.0590322 |     3.38829 |
| phase2_only_self_nav_dd7_cut50_recover3            |    0.11014   |  0.125492 | 0.877663 | -0.186968 | 0.589081 | 0.0581264 |     5.56285 |
| high_scale_only_self_nav_dd7_cut50_recover3        |    0.104536  |  0.124605 | 0.838939 | -0.218533 | 0.478354 | 0.0643438 |     5.1192  |
| phase2_high_scale_self_nav_dd7_cut50_recover3      |    0.116355  |  0.132527 | 0.877976 | -0.218533 | 0.532439 | 0.0643304 |     6.09712 |
| baseline_nav_dd7_cut50_recover3                    |    0.0889508 |  0.111374 | 0.798667 | -0.151482 | 0.587204 | 0.0612828 |     4.05357 |
| phase2_only_baseline_nav_dd7_cut50_recover3        |    0.115522  |  0.126082 | 0.916245 | -0.186968 | 0.61787  | 0.0575141 |     6.0228  |
| high_scale_only_baseline_nav_dd7_cut50_recover3    |    0.108476  |  0.1271   | 0.853472 | -0.218533 | 0.496384 | 0.0640566 |     5.42752 |
| phase2_high_scale_baseline_nav_dd7_cut50_recover3  |    0.117617  |  0.132653 | 0.886648 | -0.218533 | 0.538211 | 0.0643228 |     6.21126 |
| self_nav_dd10_cut50_recover5                       |    0.0885083 |  0.114158 | 0.775314 | -0.167763 | 0.527579 | 0.0665738 |     4.0266  |
| phase2_only_self_nav_dd10_cut50_recover5           |    0.107915  |  0.127366 | 0.847282 | -0.186968 | 0.577183 | 0.0621302 |     5.38257 |
| high_scale_only_self_nav_dd10_cut50_recover5       |    0.110843  |  0.128795 | 0.860611 | -0.233527 | 0.474646 | 0.0686546 |     5.62102 |
| phase2_high_scale_self_nav_dd10_cut50_recover5     |    0.115779  |  0.132743 | 0.872199 | -0.233527 | 0.495782 | 0.0679974 |     6.04561 |
| baseline_nav_dd10_cut50_recover5                   |    0.0980183 |  0.119487 | 0.820323 | -0.167763 | 0.584265 | 0.0679526 |     4.64501 |
| phase2_only_baseline_nav_dd10_cut50_recover5       |    0.111216  |  0.127899 | 0.869558 | -0.186968 | 0.594837 | 0.0619014 |     5.65209 |
| high_scale_only_baseline_nav_dd10_cut50_recover5   |    0.109618  |  0.13059  | 0.83941  | -0.233527 | 0.469403 | 0.0703866 |     5.52013 |
| phase2_high_scale_baseline_nav_dd10_cut50_recover5 |    0.114415  |  0.133062 | 0.859859 | -0.233527 | 0.489942 | 0.0690782 |     5.92537 |

## Recent windows

| variant                                            | window   | start      | end        |   total_return |     max_dd |     ulcer |
|:---------------------------------------------------|:---------|:-----------|:-----------|---------------:|-----------:|----------:|
| baseline_subc                                      | 1Y       | 2025-04-28 | 2026-04-28 |       0.297608 | -0.116247  | 0.0347245 |
| baseline_subc                                      | 3Y       | 2023-04-28 | 2026-04-28 |       0.823677 | -0.138376  | 0.0388034 |
| baseline_subc                                      | 5Y       | 2021-04-28 | 2026-04-28 |       0.793333 | -0.234003  | 0.0907729 |
| baseline_subc                                      | 10Y      | 2016-04-28 | 2026-04-28 |       2.59326  | -0.234003  | 0.074485  |
| self_nav_dd3_cut20_recover1                        | 1Y       | 2025-04-28 | 2026-04-28 |       0.263028 | -0.0997171 | 0.0321402 |
| self_nav_dd3_cut20_recover1                        | 3Y       | 2023-04-28 | 2026-04-28 |       0.723794 | -0.116505  | 0.0340381 |
| self_nav_dd3_cut20_recover1                        | 5Y       | 2021-04-28 | 2026-04-28 |       0.684331 | -0.196196  | 0.0763476 |
| self_nav_dd3_cut20_recover1                        | 10Y      | 2016-04-28 | 2026-04-28 |       2.16158  | -0.196196  | 0.0632334 |
| phase2_only_self_nav_dd3_cut20_recover1            | 1Y       | 2025-04-28 | 2026-04-28 |       0.263028 | -0.0997171 | 0.0321402 |
| phase2_only_self_nav_dd3_cut20_recover1            | 3Y       | 2023-04-28 | 2026-04-28 |       0.727906 | -0.116505  | 0.034038  |
| phase2_only_self_nav_dd3_cut20_recover1            | 5Y       | 2021-04-28 | 2026-04-28 |       0.741364 | -0.195108  | 0.0757161 |
| phase2_only_self_nav_dd3_cut20_recover1            | 10Y      | 2016-04-28 | 2026-04-28 |       2.48913  | -0.195108  | 0.0655409 |
| high_scale_only_self_nav_dd3_cut20_recover1        | 1Y       | 2025-04-28 | 2026-04-28 |       0.276814 | -0.116247  | 0.034813  |
| high_scale_only_self_nav_dd3_cut20_recover1        | 3Y       | 2023-04-28 | 2026-04-28 |       0.777188 | -0.123764  | 0.0345031 |
| high_scale_only_self_nav_dd3_cut20_recover1        | 5Y       | 2021-04-28 | 2026-04-28 |       0.720639 | -0.223798  | 0.0850295 |
| high_scale_only_self_nav_dd3_cut20_recover1        | 10Y      | 2016-04-28 | 2026-04-28 |       2.38993  | -0.223798  | 0.0685194 |
| phase2_high_scale_self_nav_dd3_cut20_recover1      | 1Y       | 2025-04-28 | 2026-04-28 |       0.276814 | -0.116247  | 0.034813  |
| phase2_high_scale_self_nav_dd3_cut20_recover1      | 3Y       | 2023-04-28 | 2026-04-28 |       0.785553 | -0.123764  | 0.0345035 |
| phase2_high_scale_self_nav_dd3_cut20_recover1      | 5Y       | 2021-04-28 | 2026-04-28 |       0.780885 | -0.2211    | 0.0834245 |
| phase2_high_scale_self_nav_dd3_cut20_recover1      | 10Y      | 2016-04-28 | 2026-04-28 |       2.56831  | -0.2211    | 0.0700605 |
| baseline_nav_dd3_cut20_recover1                    | 1Y       | 2025-04-28 | 2026-04-28 |       0.261531 | -0.0997171 | 0.0327446 |
| baseline_nav_dd3_cut20_recover1                    | 3Y       | 2023-04-28 | 2026-04-28 |       0.73588  | -0.116505  | 0.0342202 |
| baseline_nav_dd3_cut20_recover1                    | 5Y       | 2021-04-28 | 2026-04-28 |       0.69582  | -0.200736  | 0.079044  |
| baseline_nav_dd3_cut20_recover1                    | 10Y      | 2016-04-28 | 2026-04-28 |       2.15503  | -0.200736  | 0.0650508 |
| phase2_only_baseline_nav_dd3_cut20_recover1        | 1Y       | 2025-04-28 | 2026-04-28 |       0.261531 | -0.0997171 | 0.0327446 |
| phase2_only_baseline_nav_dd3_cut20_recover1        | 3Y       | 2023-04-28 | 2026-04-28 |       0.73588  | -0.116505  | 0.0342202 |
| phase2_only_baseline_nav_dd3_cut20_recover1        | 5Y       | 2021-04-28 | 2026-04-28 |       0.7494   | -0.195108  | 0.0757652 |
| phase2_only_baseline_nav_dd3_cut20_recover1        | 10Y      | 2016-04-28 | 2026-04-28 |       2.50523  | -0.195108  | 0.0655693 |
| high_scale_only_baseline_nav_dd3_cut20_recover1    | 1Y       | 2025-04-28 | 2026-04-28 |       0.278105 | -0.116247  | 0.0347316 |
| high_scale_only_baseline_nav_dd3_cut20_recover1    | 3Y       | 2023-04-28 | 2026-04-28 |       0.782292 | -0.123764  | 0.0344764 |
| high_scale_only_baseline_nav_dd3_cut20_recover1    | 5Y       | 2021-04-28 | 2026-04-28 |       0.73382  | -0.223798  | 0.0850221 |
| high_scale_only_baseline_nav_dd3_cut20_recover1    | 10Y      | 2016-04-28 | 2026-04-28 |       2.4192   | -0.223798  | 0.0686068 |
| phase2_high_scale_baseline_nav_dd3_cut20_recover1  | 1Y       | 2025-04-28 | 2026-04-28 |       0.278105 | -0.116247  | 0.0347316 |
| phase2_high_scale_baseline_nav_dd3_cut20_recover1  | 3Y       | 2023-04-28 | 2026-04-28 |       0.782292 | -0.123764  | 0.0344764 |
| phase2_high_scale_baseline_nav_dd3_cut20_recover1  | 5Y       | 2021-04-28 | 2026-04-28 |       0.777633 | -0.2211    | 0.0834176 |
| phase2_high_scale_baseline_nav_dd3_cut20_recover1  | 10Y      | 2016-04-28 | 2026-04-28 |       2.5618   | -0.2211    | 0.0700564 |
| self_nav_dd5_cut30_recover2                        | 1Y       | 2025-04-28 | 2026-04-28 |       0.252612 | -0.0993463 | 0.0341709 |
| self_nav_dd5_cut30_recover2                        | 3Y       | 2023-04-28 | 2026-04-28 |       0.713475 | -0.111457  | 0.0345479 |
| self_nav_dd5_cut30_recover2                        | 5Y       | 2021-04-28 | 2026-04-28 |       0.700915 | -0.181697  | 0.072876  |
| self_nav_dd5_cut30_recover2                        | 10Y      | 2016-04-28 | 2026-04-28 |       2.08887  | -0.181697  | 0.0619902 |
| phase2_only_self_nav_dd5_cut30_recover2            | 1Y       | 2025-04-28 | 2026-04-28 |       0.252612 | -0.0993463 | 0.0341709 |
| phase2_only_self_nav_dd5_cut30_recover2            | 3Y       | 2023-04-28 | 2026-04-28 |       0.713475 | -0.111457  | 0.0345479 |
| phase2_only_self_nav_dd5_cut30_recover2            | 5Y       | 2021-04-28 | 2026-04-28 |       0.734103 | -0.181226  | 0.0724754 |
| phase2_only_self_nav_dd5_cut30_recover2            | 10Y      | 2016-04-28 | 2026-04-28 |       2.47458  | -0.186968  | 0.0636842 |
| high_scale_only_self_nav_dd5_cut30_recover2        | 1Y       | 2025-04-28 | 2026-04-28 |       0.284869 | -0.116247  | 0.0346784 |
| high_scale_only_self_nav_dd5_cut30_recover2        | 3Y       | 2023-04-28 | 2026-04-28 |       0.759555 | -0.122576  | 0.0342376 |
| high_scale_only_self_nav_dd5_cut30_recover2        | 5Y       | 2021-04-28 | 2026-04-28 |       0.708834 | -0.225645  | 0.0868988 |
| high_scale_only_self_nav_dd5_cut30_recover2        | 10Y      | 2016-04-28 | 2026-04-28 |       2.37839  | -0.225645  | 0.0702785 |
| phase2_high_scale_self_nav_dd5_cut30_recover2      | 1Y       | 2025-04-28 | 2026-04-28 |       0.284869 | -0.116247  | 0.0346784 |
| phase2_high_scale_self_nav_dd5_cut30_recover2      | 3Y       | 2023-04-28 | 2026-04-28 |       0.772007 | -0.122576  | 0.0342383 |
| phase2_high_scale_self_nav_dd5_cut30_recover2      | 5Y       | 2021-04-28 | 2026-04-28 |       0.764534 | -0.220771  | 0.0838691 |
| phase2_high_scale_self_nav_dd5_cut30_recover2      | 10Y      | 2016-04-28 | 2026-04-28 |       2.53555  | -0.220771  | 0.0703253 |
| baseline_nav_dd5_cut30_recover2                    | 1Y       | 2025-04-28 | 2026-04-28 |       0.260298 | -0.0993463 | 0.0341506 |
| baseline_nav_dd5_cut30_recover2                    | 3Y       | 2023-04-28 | 2026-04-28 |       0.727296 | -0.111457  | 0.0343882 |
| baseline_nav_dd5_cut30_recover2                    | 5Y       | 2021-04-28 | 2026-04-28 |       0.701796 | -0.191995  | 0.0787693 |
| baseline_nav_dd5_cut30_recover2                    | 10Y      | 2016-04-28 | 2026-04-28 |       2.04664  | -0.191995  | 0.0657598 |
| phase2_only_baseline_nav_dd5_cut30_recover2        | 1Y       | 2025-04-28 | 2026-04-28 |       0.260298 | -0.0993463 | 0.0341506 |
| phase2_only_baseline_nav_dd5_cut30_recover2        | 3Y       | 2023-04-28 | 2026-04-28 |       0.727296 | -0.111457  | 0.0343882 |
| phase2_only_baseline_nav_dd5_cut30_recover2        | 5Y       | 2021-04-28 | 2026-04-28 |       0.74809  | -0.181226  | 0.0724308 |
| phase2_only_baseline_nav_dd5_cut30_recover2        | 10Y      | 2016-04-28 | 2026-04-28 |       2.5026   | -0.186968  | 0.0636589 |
| high_scale_only_baseline_nav_dd5_cut30_recover2    | 1Y       | 2025-04-28 | 2026-04-28 |       0.283433 | -0.116247  | 0.0346702 |
| high_scale_only_baseline_nav_dd5_cut30_recover2    | 3Y       | 2023-04-28 | 2026-04-28 |       0.777872 | -0.122576  | 0.0342013 |
| high_scale_only_baseline_nav_dd5_cut30_recover2    | 5Y       | 2021-04-28 | 2026-04-28 |       0.727342 | -0.229301  | 0.0890778 |
| high_scale_only_baseline_nav_dd5_cut30_recover2    | 10Y      | 2016-04-28 | 2026-04-28 |       2.37831  | -0.229301  | 0.0716598 |
| phase2_high_scale_baseline_nav_dd5_cut30_recover2  | 1Y       | 2025-04-28 | 2026-04-28 |       0.283433 | -0.116247  | 0.0346702 |
| phase2_high_scale_baseline_nav_dd5_cut30_recover2  | 3Y       | 2023-04-28 | 2026-04-28 |       0.777872 | -0.122576  | 0.0342013 |
| phase2_high_scale_baseline_nav_dd5_cut30_recover2  | 5Y       | 2021-04-28 | 2026-04-28 |       0.770374 | -0.220771  | 0.0838601 |
| phase2_high_scale_baseline_nav_dd5_cut30_recover2  | 10Y      | 2016-04-28 | 2026-04-28 |       2.54725  | -0.220771  | 0.0703199 |
| self_nav_dd7_cut50_recover3                        | 1Y       | 2025-04-28 | 2026-04-28 |       0.237748 | -0.0932482 | 0.0329033 |
| self_nav_dd7_cut50_recover3                        | 3Y       | 2023-04-28 | 2026-04-28 |       0.548293 | -0.108637  | 0.039566  |
| self_nav_dd7_cut50_recover3                        | 5Y       | 2021-04-28 | 2026-04-28 |       0.581355 | -0.151482  | 0.0675436 |
| self_nav_dd7_cut50_recover3                        | 10Y      | 2016-04-28 | 2026-04-28 |       1.72395  | -0.151482  | 0.0584697 |
| phase2_only_self_nav_dd7_cut50_recover3            | 1Y       | 2025-04-28 | 2026-04-28 |       0.237748 | -0.0932482 | 0.0329033 |
| phase2_only_self_nav_dd7_cut50_recover3            | 3Y       | 2023-04-28 | 2026-04-28 |       0.548293 | -0.108637  | 0.039566  |
| phase2_only_self_nav_dd7_cut50_recover3            | 5Y       | 2021-04-28 | 2026-04-28 |       0.581355 | -0.151482  | 0.0675436 |
| phase2_only_self_nav_dd7_cut50_recover3            | 10Y      | 2016-04-28 | 2026-04-28 |       2.16852  | -0.186968  | 0.0609154 |
| high_scale_only_self_nav_dd7_cut50_recover3        | 1Y       | 2025-04-28 | 2026-04-28 |       0.297608 | -0.116247  | 0.0347245 |
| high_scale_only_self_nav_dd7_cut50_recover3        | 3Y       | 2023-04-28 | 2026-04-28 |       0.743573 | -0.138376  | 0.0341938 |
| high_scale_only_self_nav_dd7_cut50_recover3        | 5Y       | 2021-04-28 | 2026-04-28 |       0.733231 | -0.218533  | 0.0840301 |
| high_scale_only_self_nav_dd7_cut50_recover3        | 10Y      | 2016-04-28 | 2026-04-28 |       2.39571  | -0.218533  | 0.0684192 |
| phase2_high_scale_self_nav_dd7_cut50_recover3      | 1Y       | 2025-04-28 | 2026-04-28 |       0.297608 | -0.116247  | 0.0347245 |
| phase2_high_scale_self_nav_dd7_cut50_recover3      | 3Y       | 2023-04-28 | 2026-04-28 |       0.743573 | -0.138376  | 0.0341938 |
| phase2_high_scale_self_nav_dd7_cut50_recover3      | 5Y       | 2021-04-28 | 2026-04-28 |       0.733231 | -0.218533  | 0.0840301 |
| phase2_high_scale_self_nav_dd7_cut50_recover3      | 10Y      | 2016-04-28 | 2026-04-28 |       2.47283  | -0.218533  | 0.0704212 |
| baseline_nav_dd7_cut50_recover3                    | 1Y       | 2025-04-28 | 2026-04-28 |       0.261381 | -0.0932482 | 0.0329648 |
| baseline_nav_dd7_cut50_recover3                    | 3Y       | 2023-04-28 | 2026-04-28 |       0.676309 | -0.108637  | 0.0365138 |
| baseline_nav_dd7_cut50_recover3                    | 5Y       | 2021-04-28 | 2026-04-28 |       0.712105 | -0.151482  | 0.065797  |
| baseline_nav_dd7_cut50_recover3                    | 10Y      | 2016-04-28 | 2026-04-28 |       2.02693  | -0.151482  | 0.0585888 |
| phase2_only_baseline_nav_dd7_cut50_recover3        | 1Y       | 2025-04-28 | 2026-04-28 |       0.261381 | -0.0932482 | 0.0329648 |
| phase2_only_baseline_nav_dd7_cut50_recover3        | 3Y       | 2023-04-28 | 2026-04-28 |       0.676309 | -0.108637  | 0.0365138 |
| phase2_only_baseline_nav_dd7_cut50_recover3        | 5Y       | 2021-04-28 | 2026-04-28 |       0.712105 | -0.151482  | 0.065797  |
| phase2_only_baseline_nav_dd7_cut50_recover3        | 10Y      | 2016-04-28 | 2026-04-28 |       2.4305   | -0.186968  | 0.0599527 |
| high_scale_only_baseline_nav_dd7_cut50_recover3    | 1Y       | 2025-04-28 | 2026-04-28 |       0.297608 | -0.116247  | 0.0347245 |
| high_scale_only_baseline_nav_dd7_cut50_recover3    | 3Y       | 2023-04-28 | 2026-04-28 |       0.776213 | -0.138376  | 0.0341945 |
| high_scale_only_baseline_nav_dd7_cut50_recover3    | 5Y       | 2021-04-28 | 2026-04-28 |       0.765677 | -0.218533  | 0.0840109 |
| high_scale_only_baseline_nav_dd7_cut50_recover3    | 10Y      | 2016-04-28 | 2026-04-28 |       2.41903  | -0.218533  | 0.0687092 |
| phase2_high_scale_baseline_nav_dd7_cut50_recover3  | 1Y       | 2025-04-28 | 2026-04-28 |       0.297608 | -0.116247  | 0.0347245 |
| phase2_high_scale_baseline_nav_dd7_cut50_recover3  | 3Y       | 2023-04-28 | 2026-04-28 |       0.776213 | -0.138376  | 0.0341945 |
| phase2_high_scale_baseline_nav_dd7_cut50_recover3  | 5Y       | 2021-04-28 | 2026-04-28 |       0.765677 | -0.218533  | 0.0840109 |
| phase2_high_scale_baseline_nav_dd7_cut50_recover3  | 10Y      | 2016-04-28 | 2026-04-28 |       2.53784  | -0.218533  | 0.0704098 |
| self_nav_dd10_cut50_recover5                       | 1Y       | 2025-04-28 | 2026-04-28 |       0.208526 | -0.111694  | 0.0377358 |
| self_nav_dd10_cut50_recover5                       | 3Y       | 2023-04-28 | 2026-04-28 |       0.527423 | -0.131804  | 0.0435372 |
| self_nav_dd10_cut50_recover5                       | 5Y       | 2021-04-28 | 2026-04-28 |       0.530105 | -0.167763  | 0.0783956 |
| self_nav_dd10_cut50_recover5                       | 10Y      | 2016-04-28 | 2026-04-28 |       1.58744  | -0.167763  | 0.0670819 |
| phase2_only_self_nav_dd10_cut50_recover5           | 1Y       | 2025-04-28 | 2026-04-28 |       0.208526 | -0.111694  | 0.0377358 |
| phase2_only_self_nav_dd10_cut50_recover5           | 3Y       | 2023-04-28 | 2026-04-28 |       0.527423 | -0.131804  | 0.0435372 |
| phase2_only_self_nav_dd10_cut50_recover5           | 5Y       | 2021-04-28 | 2026-04-28 |       0.530105 | -0.167763  | 0.0783956 |
| phase2_only_self_nav_dd10_cut50_recover5           | 10Y      | 2016-04-28 | 2026-04-28 |       2.06583  | -0.186968  | 0.0670963 |
| high_scale_only_self_nav_dd10_cut50_recover5       | 1Y       | 2025-04-28 | 2026-04-28 |       0.297608 | -0.116247  | 0.0347245 |
| high_scale_only_self_nav_dd10_cut50_recover5       | 3Y       | 2023-04-28 | 2026-04-28 |       0.762664 | -0.138376  | 0.034194  |
| high_scale_only_self_nav_dd10_cut50_recover5       | 5Y       | 2021-04-28 | 2026-04-28 |       0.718587 | -0.233527  | 0.0930438 |
| high_scale_only_self_nav_dd10_cut50_recover5       | 10Y      | 2016-04-28 | 2026-04-28 |       2.32725  | -0.233527  | 0.0759548 |
| phase2_high_scale_self_nav_dd10_cut50_recover5     | 1Y       | 2025-04-28 | 2026-04-28 |       0.297608 | -0.116247  | 0.0347245 |
| phase2_high_scale_self_nav_dd10_cut50_recover5     | 3Y       | 2023-04-28 | 2026-04-28 |       0.762664 | -0.138376  | 0.034194  |
| phase2_high_scale_self_nav_dd10_cut50_recover5     | 5Y       | 2021-04-28 | 2026-04-28 |       0.718587 | -0.233527  | 0.0930438 |
| phase2_high_scale_self_nav_dd10_cut50_recover5     | 10Y      | 2016-04-28 | 2026-04-28 |       2.44349  | -0.233527  | 0.075872  |
| baseline_nav_dd10_cut50_recover5                   | 1Y       | 2025-04-28 | 2026-04-28 |       0.234427 | -0.111694  | 0.0381273 |
| baseline_nav_dd10_cut50_recover5                   | 3Y       | 2023-04-28 | 2026-04-28 |       0.603906 | -0.131804  | 0.0424147 |
| baseline_nav_dd10_cut50_recover5                   | 5Y       | 2021-04-28 | 2026-04-28 |       0.606722 | -0.167763  | 0.0777981 |
| baseline_nav_dd10_cut50_recover5                   | 10Y      | 2016-04-28 | 2026-04-28 |       2.06295  | -0.167763  | 0.0664817 |
| phase2_only_baseline_nav_dd10_cut50_recover5       | 1Y       | 2025-04-28 | 2026-04-28 |       0.234427 | -0.111694  | 0.0381273 |
| phase2_only_baseline_nav_dd10_cut50_recover5       | 3Y       | 2023-04-28 | 2026-04-28 |       0.603906 | -0.131804  | 0.0424147 |
| phase2_only_baseline_nav_dd10_cut50_recover5       | 5Y       | 2021-04-28 | 2026-04-28 |       0.606722 | -0.167763  | 0.0777981 |
| phase2_only_baseline_nav_dd10_cut50_recover5       | 10Y      | 2016-04-28 | 2026-04-28 |       2.21935  | -0.186968  | 0.066748  |
| high_scale_only_baseline_nav_dd10_cut50_recover5   | 1Y       | 2025-04-28 | 2026-04-28 |       0.297608 | -0.116247  | 0.0347245 |
| high_scale_only_baseline_nav_dd10_cut50_recover5   | 3Y       | 2023-04-28 | 2026-04-28 |       0.727609 | -0.138376  | 0.038615  |
| high_scale_only_baseline_nav_dd10_cut50_recover5   | 5Y       | 2021-04-28 | 2026-04-28 |       0.684408 | -0.233527  | 0.0956266 |
| high_scale_only_baseline_nav_dd10_cut50_recover5   | 10Y      | 2016-04-28 | 2026-04-28 |       2.29547  | -0.233527  | 0.0774166 |
| phase2_high_scale_baseline_nav_dd10_cut50_recover5 | 1Y       | 2025-04-28 | 2026-04-28 |       0.297608 | -0.116247  | 0.0347245 |
| phase2_high_scale_baseline_nav_dd10_cut50_recover5 | 3Y       | 2023-04-28 | 2026-04-28 |       0.727609 | -0.138376  | 0.038615  |
| phase2_high_scale_baseline_nav_dd10_cut50_recover5 | 5Y       | 2021-04-28 | 2026-04-28 |       0.684408 | -0.233527  | 0.0956266 |
| phase2_high_scale_baseline_nav_dd10_cut50_recover5 | 10Y      | 2016-04-28 | 2026-04-28 |       2.37501  | -0.233527  | 0.0774597 |

## Pressure windows

| variant                                            | window       | start      | end        |   total_return |     max_dd |     ulcer |
|:---------------------------------------------------|:-------------|:-----------|:-----------|---------------:|-----------:|----------:|
| baseline_subc                                      | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| baseline_subc                                      | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.224749   | -0.223644  | 0.140165  |
| baseline_subc                                      | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.090729   | -0.138376  | 0.0704462 |
| baseline_subc                                      | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0231135  | -0.116247  | 0.0575626 |
| baseline_subc                                      | since_phase2 | 2022-01-03 | 2026-04-28 |     0.649899   | -0.223644  | 0.0906307 |
| self_nav_dd3_cut20_recover1                        | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.140642   | -0.146681  | 0.0976305 |
| self_nav_dd3_cut20_recover1                        | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.181454   | -0.180546  | 0.11278   |
| self_nav_dd3_cut20_recover1                        | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.0764849  | -0.116505  | 0.061166  |
| self_nav_dd3_cut20_recover1                        | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0312691  | -0.0997171 | 0.0514331 |
| self_nav_dd3_cut20_recover1                        | since_phase2 | 2022-01-03 | 2026-04-28 |     0.605984   | -0.180546  | 0.0720812 |
| phase2_only_self_nav_dd3_cut20_recover1            | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_only_self_nav_dd3_cut20_recover1            | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.185384   | -0.184223  | 0.116383  |
| phase2_only_self_nav_dd3_cut20_recover1            | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.0764849  | -0.116505  | 0.061166  |
| phase2_only_self_nav_dd3_cut20_recover1            | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0312691  | -0.0997171 | 0.0514331 |
| phase2_only_self_nav_dd3_cut20_recover1            | since_phase2 | 2022-01-03 | 2026-04-28 |     0.602086   | -0.184223  | 0.0742804 |
| high_scale_only_self_nav_dd3_cut20_recover1        | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.161953   | -0.167842  | 0.10866   |
| high_scale_only_self_nav_dd3_cut20_recover1        | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.21169    | -0.210567  | 0.129549  |
| high_scale_only_self_nav_dd3_cut20_recover1        | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.0753087  | -0.123764  | 0.0605814 |
| high_scale_only_self_nav_dd3_cut20_recover1        | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0261462  | -0.116247  | 0.057499  |
| high_scale_only_self_nav_dd3_cut20_recover1        | since_phase2 | 2022-01-03 | 2026-04-28 |     0.630771   | -0.210567  | 0.0826944 |
| phase2_high_scale_self_nav_dd3_cut20_recover1      | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_high_scale_self_nav_dd3_cut20_recover1      | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.21169    | -0.210567  | 0.129549  |
| phase2_high_scale_self_nav_dd3_cut20_recover1      | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.0753087  | -0.123764  | 0.0605814 |
| phase2_high_scale_self_nav_dd3_cut20_recover1      | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0261462  | -0.116247  | 0.057499  |
| phase2_high_scale_self_nav_dd3_cut20_recover1      | since_phase2 | 2022-01-03 | 2026-04-28 |     0.638446   | -0.210567  | 0.0826945 |
| baseline_nav_dd3_cut20_recover1                    | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.140642   | -0.146681  | 0.0976305 |
| baseline_nav_dd3_cut20_recover1                    | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.185384   | -0.184223  | 0.116383  |
| baseline_nav_dd3_cut20_recover1                    | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.0764849  | -0.116505  | 0.061166  |
| baseline_nav_dd3_cut20_recover1                    | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0312691  | -0.0997171 | 0.0514331 |
| baseline_nav_dd3_cut20_recover1                    | since_phase2 | 2022-01-03 | 2026-04-28 |     0.609479   | -0.184223  | 0.0743386 |
| phase2_only_baseline_nav_dd3_cut20_recover1        | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_only_baseline_nav_dd3_cut20_recover1        | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.185384   | -0.184223  | 0.116383  |
| phase2_only_baseline_nav_dd3_cut20_recover1        | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.0764849  | -0.116505  | 0.061166  |
| phase2_only_baseline_nav_dd3_cut20_recover1        | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0312691  | -0.0997171 | 0.0514331 |
| phase2_only_baseline_nav_dd3_cut20_recover1        | since_phase2 | 2022-01-03 | 2026-04-28 |     0.609479   | -0.184223  | 0.0743386 |
| high_scale_only_baseline_nav_dd3_cut20_recover1    | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.161953   | -0.167842  | 0.10866   |
| high_scale_only_baseline_nav_dd3_cut20_recover1    | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.21169    | -0.210567  | 0.129549  |
| high_scale_only_baseline_nav_dd3_cut20_recover1    | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.0753087  | -0.123764  | 0.0605814 |
| high_scale_only_baseline_nav_dd3_cut20_recover1    | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0261462  | -0.116247  | 0.057499  |
| high_scale_only_baseline_nav_dd3_cut20_recover1    | since_phase2 | 2022-01-03 | 2026-04-28 |     0.635454   | -0.210567  | 0.0826867 |
| phase2_high_scale_baseline_nav_dd3_cut20_recover1  | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_high_scale_baseline_nav_dd3_cut20_recover1  | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.21169    | -0.210567  | 0.129549  |
| phase2_high_scale_baseline_nav_dd3_cut20_recover1  | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.0753087  | -0.123764  | 0.0605814 |
| phase2_high_scale_baseline_nav_dd3_cut20_recover1  | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0261462  | -0.116247  | 0.057499  |
| phase2_high_scale_baseline_nav_dd3_cut20_recover1  | since_phase2 | 2022-01-03 | 2026-04-28 |     0.635454   | -0.210567  | 0.0826867 |
| self_nav_dd5_cut30_recover2                        | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.134613   | -0.140694  | 0.0964165 |
| self_nav_dd5_cut30_recover2                        | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.159336   | -0.158535  | 0.0989469 |
| self_nav_dd5_cut30_recover2                        | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.075652   | -0.111457  | 0.0618886 |
| self_nav_dd5_cut30_recover2                        | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0261984  | -0.0993463 | 0.0550314 |
| self_nav_dd5_cut30_recover2                        | since_phase2 | 2022-01-03 | 2026-04-28 |     0.618508   | -0.158535  | 0.064232  |
| phase2_only_self_nav_dd5_cut30_recover2            | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_only_self_nav_dd5_cut30_recover2            | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.171335   | -0.170154  | 0.110256  |
| phase2_only_self_nav_dd5_cut30_recover2            | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.075652   | -0.111457  | 0.0618886 |
| phase2_only_self_nav_dd5_cut30_recover2            | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0261984  | -0.0993463 | 0.0550314 |
| phase2_only_self_nav_dd5_cut30_recover2            | since_phase2 | 2022-01-03 | 2026-04-28 |     0.595406   | -0.170154  | 0.0707537 |
| high_scale_only_self_nav_dd5_cut30_recover2        | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| high_scale_only_self_nav_dd5_cut30_recover2        | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.207617   | -0.206488  | 0.126433  |
| high_scale_only_self_nav_dd5_cut30_recover2        | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.0740552  | -0.122576  | 0.0610274 |
| high_scale_only_self_nav_dd5_cut30_recover2        | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0274883  | -0.116247  | 0.0574755 |
| high_scale_only_self_nav_dd5_cut30_recover2        | since_phase2 | 2022-01-03 | 2026-04-28 |     0.619642   | -0.206488  | 0.0808455 |
| phase2_high_scale_self_nav_dd5_cut30_recover2      | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_high_scale_self_nav_dd5_cut30_recover2      | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.211358   | -0.210234  | 0.130044  |
| phase2_high_scale_self_nav_dd5_cut30_recover2      | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.0740552  | -0.122576  | 0.0610274 |
| phase2_high_scale_self_nav_dd5_cut30_recover2      | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0274883  | -0.116247  | 0.0574755 |
| phase2_high_scale_self_nav_dd5_cut30_recover2      | since_phase2 | 2022-01-03 | 2026-04-28 |     0.623403   | -0.210234  | 0.0831444 |
| baseline_nav_dd5_cut30_recover2                    | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.134613   | -0.140694  | 0.0964165 |
| baseline_nav_dd5_cut30_recover2                    | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.171335   | -0.170154  | 0.110256  |
| baseline_nav_dd5_cut30_recover2                    | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.075652   | -0.111457  | 0.0618886 |
| baseline_nav_dd5_cut30_recover2                    | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0261984  | -0.0993463 | 0.0550314 |
| baseline_nav_dd5_cut30_recover2                    | since_phase2 | 2022-01-03 | 2026-04-28 |     0.608274   | -0.170154  | 0.0706996 |
| phase2_only_baseline_nav_dd5_cut30_recover2        | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_only_baseline_nav_dd5_cut30_recover2        | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.171335   | -0.170154  | 0.110256  |
| phase2_only_baseline_nav_dd5_cut30_recover2        | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.075652   | -0.111457  | 0.0618886 |
| phase2_only_baseline_nav_dd5_cut30_recover2        | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0261984  | -0.0993463 | 0.0550314 |
| phase2_only_baseline_nav_dd5_cut30_recover2        | since_phase2 | 2022-01-03 | 2026-04-28 |     0.608274   | -0.170154  | 0.0706996 |
| high_scale_only_baseline_nav_dd5_cut30_recover2    | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| high_scale_only_baseline_nav_dd5_cut30_recover2    | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.211358   | -0.210234  | 0.130044  |
| high_scale_only_baseline_nav_dd5_cut30_recover2    | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.0740552  | -0.122576  | 0.0610274 |
| high_scale_only_baseline_nav_dd5_cut30_recover2    | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0274883  | -0.116247  | 0.0574755 |
| high_scale_only_baseline_nav_dd5_cut30_recover2    | since_phase2 | 2022-01-03 | 2026-04-28 |     0.628776   | -0.210234  | 0.0831339 |
| phase2_high_scale_baseline_nav_dd5_cut30_recover2  | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_high_scale_baseline_nav_dd5_cut30_recover2  | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.211358   | -0.210234  | 0.130044  |
| phase2_high_scale_baseline_nav_dd5_cut30_recover2  | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.0740552  | -0.122576  | 0.0610274 |
| phase2_high_scale_baseline_nav_dd5_cut30_recover2  | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0274883  | -0.116247  | 0.0574755 |
| phase2_high_scale_baseline_nav_dd5_cut30_recover2  | since_phase2 | 2022-01-03 | 2026-04-28 |     0.628776   | -0.210234  | 0.0831339 |
| self_nav_dd7_cut50_recover3                        | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.126506   | -0.132644  | 0.0970531 |
| self_nav_dd7_cut50_recover3                        | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.141231   | -0.140008  | 0.0966181 |
| self_nav_dd7_cut50_recover3                        | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.081637   | -0.108637  | 0.068296  |
| self_nav_dd7_cut50_recover3                        | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0221147  | -0.0932482 | 0.054209  |
| self_nav_dd7_cut50_recover3                        | since_phase2 | 2022-01-03 | 2026-04-28 |     0.454875   | -0.140008  | 0.0652308 |
| phase2_only_self_nav_dd7_cut50_recover3            | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_only_self_nav_dd7_cut50_recover3            | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.141231   | -0.140008  | 0.0966181 |
| phase2_only_self_nav_dd7_cut50_recover3            | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.081637   | -0.108637  | 0.068296  |
| phase2_only_self_nav_dd7_cut50_recover3            | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0221147  | -0.0932482 | 0.054209  |
| phase2_only_self_nav_dd7_cut50_recover3            | since_phase2 | 2022-01-03 | 2026-04-28 |     0.454875   | -0.140008  | 0.0652308 |
| high_scale_only_self_nav_dd7_cut50_recover3        | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| high_scale_only_self_nav_dd7_cut50_recover3        | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.209092   | -0.207965  | 0.12944   |
| high_scale_only_self_nav_dd7_cut50_recover3        | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.090729   | -0.138376  | 0.0704462 |
| high_scale_only_self_nav_dd7_cut50_recover3        | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0231135  | -0.116247  | 0.0575626 |
| high_scale_only_self_nav_dd7_cut50_recover3        | since_phase2 | 2022-01-03 | 2026-04-28 |     0.594603   | -0.207965  | 0.083261  |
| phase2_high_scale_self_nav_dd7_cut50_recover3      | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_high_scale_self_nav_dd7_cut50_recover3      | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.209092   | -0.207965  | 0.12944   |
| phase2_high_scale_self_nav_dd7_cut50_recover3      | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.090729   | -0.138376  | 0.0704462 |
| phase2_high_scale_self_nav_dd7_cut50_recover3      | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0231135  | -0.116247  | 0.0575626 |
| phase2_high_scale_self_nav_dd7_cut50_recover3      | since_phase2 | 2022-01-03 | 2026-04-28 |     0.594603   | -0.207965  | 0.083261  |
| baseline_nav_dd7_cut50_recover3                    | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.126506   | -0.132644  | 0.0970531 |
| baseline_nav_dd7_cut50_recover3                    | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.141231   | -0.140008  | 0.0966181 |
| baseline_nav_dd7_cut50_recover3                    | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.081637   | -0.108637  | 0.068296  |
| baseline_nav_dd7_cut50_recover3                    | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0221147  | -0.0932482 | 0.054209  |
| baseline_nav_dd7_cut50_recover3                    | since_phase2 | 2022-01-03 | 2026-04-28 |     0.575167   | -0.140008  | 0.063555  |
| phase2_only_baseline_nav_dd7_cut50_recover3        | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_only_baseline_nav_dd7_cut50_recover3        | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.141231   | -0.140008  | 0.0966181 |
| phase2_only_baseline_nav_dd7_cut50_recover3        | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.081637   | -0.108637  | 0.068296  |
| phase2_only_baseline_nav_dd7_cut50_recover3        | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0221147  | -0.0932482 | 0.054209  |
| phase2_only_baseline_nav_dd7_cut50_recover3        | since_phase2 | 2022-01-03 | 2026-04-28 |     0.575167   | -0.140008  | 0.063555  |
| high_scale_only_baseline_nav_dd7_cut50_recover3    | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| high_scale_only_baseline_nav_dd7_cut50_recover3    | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.209092   | -0.207965  | 0.12944   |
| high_scale_only_baseline_nav_dd7_cut50_recover3    | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.090729   | -0.138376  | 0.0704462 |
| high_scale_only_baseline_nav_dd7_cut50_recover3    | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0231135  | -0.116247  | 0.0575626 |
| high_scale_only_baseline_nav_dd7_cut50_recover3    | since_phase2 | 2022-01-03 | 2026-04-28 |     0.624455   | -0.207965  | 0.0832525 |
| phase2_high_scale_baseline_nav_dd7_cut50_recover3  | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_high_scale_baseline_nav_dd7_cut50_recover3  | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.209092   | -0.207965  | 0.12944   |
| phase2_high_scale_baseline_nav_dd7_cut50_recover3  | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.090729   | -0.138376  | 0.0704462 |
| phase2_high_scale_baseline_nav_dd7_cut50_recover3  | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0231135  | -0.116247  | 0.0575626 |
| phase2_high_scale_baseline_nav_dd7_cut50_recover3  | since_phase2 | 2022-01-03 | 2026-04-28 |     0.624455   | -0.207965  | 0.0832525 |
| self_nav_dd10_cut50_recover5                       | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.129745   | -0.13586   | 0.0996638 |
| self_nav_dd10_cut50_recover5                       | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.157709   | -0.156509  | 0.1127    |
| self_nav_dd10_cut50_recover5                       | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.105506   | -0.131804  | 0.0731577 |
| self_nav_dd10_cut50_recover5                       | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.00132232 | -0.111694  | 0.0633554 |
| self_nav_dd10_cut50_recover5                       | since_phase2 | 2022-01-03 | 2026-04-28 |     0.407724   | -0.156509  | 0.0767495 |
| phase2_only_self_nav_dd10_cut50_recover5           | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_only_self_nav_dd10_cut50_recover5           | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.157709   | -0.156509  | 0.1127    |
| phase2_only_self_nav_dd10_cut50_recover5           | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.105506   | -0.131804  | 0.0731577 |
| phase2_only_self_nav_dd10_cut50_recover5           | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.00132232 | -0.111694  | 0.0633554 |
| phase2_only_self_nav_dd10_cut50_recover5           | since_phase2 | 2022-01-03 | 2026-04-28 |     0.407724   | -0.156509  | 0.0767495 |
| high_scale_only_self_nav_dd10_cut50_recover5       | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| high_scale_only_self_nav_dd10_cut50_recover5       | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.224268   | -0.223163  | 0.144165  |
| high_scale_only_self_nav_dd10_cut50_recover5       | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.090729   | -0.138376  | 0.0704462 |
| high_scale_only_self_nav_dd10_cut50_recover5       | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0231135  | -0.116247  | 0.0575626 |
| high_scale_only_self_nav_dd10_cut50_recover5       | since_phase2 | 2022-01-03 | 2026-04-28 |     0.581131   | -0.223163  | 0.0928925 |
| phase2_high_scale_self_nav_dd10_cut50_recover5     | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_high_scale_self_nav_dd10_cut50_recover5     | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.224268   | -0.223163  | 0.144165  |
| phase2_high_scale_self_nav_dd10_cut50_recover5     | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.090729   | -0.138376  | 0.0704462 |
| phase2_high_scale_self_nav_dd10_cut50_recover5     | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0231135  | -0.116247  | 0.0575626 |
| phase2_high_scale_self_nav_dd10_cut50_recover5     | since_phase2 | 2022-01-03 | 2026-04-28 |     0.581131   | -0.223163  | 0.0928925 |
| baseline_nav_dd10_cut50_recover5                   | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.129745   | -0.13586   | 0.0996638 |
| baseline_nav_dd10_cut50_recover5                   | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.157709   | -0.156509  | 0.1127    |
| baseline_nav_dd10_cut50_recover5                   | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.105506   | -0.131804  | 0.0731577 |
| baseline_nav_dd10_cut50_recover5                   | 2026_ytd     | 2026-01-01 | 2026-04-28 |    -0.0094326  | -0.111694  | 0.0639873 |
| baseline_nav_dd10_cut50_recover5                   | since_phase2 | 2022-01-03 | 2026-04-28 |     0.478213   | -0.156509  | 0.0761947 |
| phase2_only_baseline_nav_dd10_cut50_recover5       | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_only_baseline_nav_dd10_cut50_recover5       | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.157709   | -0.156509  | 0.1127    |
| phase2_only_baseline_nav_dd10_cut50_recover5       | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.105506   | -0.131804  | 0.0731577 |
| phase2_only_baseline_nav_dd10_cut50_recover5       | 2026_ytd     | 2026-01-01 | 2026-04-28 |    -0.0094326  | -0.111694  | 0.0639873 |
| phase2_only_baseline_nav_dd10_cut50_recover5       | since_phase2 | 2022-01-03 | 2026-04-28 |     0.478213   | -0.156509  | 0.0761947 |
| high_scale_only_baseline_nav_dd10_cut50_recover5   | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| high_scale_only_baseline_nav_dd10_cut50_recover5   | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.224268   | -0.223163  | 0.144165  |
| high_scale_only_baseline_nav_dd10_cut50_recover5   | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.090729   | -0.138376  | 0.0704462 |
| high_scale_only_baseline_nav_dd10_cut50_recover5   | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0231135  | -0.116247  | 0.0575626 |
| high_scale_only_baseline_nav_dd10_cut50_recover5   | since_phase2 | 2022-01-03 | 2026-04-28 |     0.549686   | -0.223163  | 0.0954981 |
| phase2_high_scale_baseline_nav_dd10_cut50_recover5 | 2020_crash   | 2020-02-19 | 2020-03-23 |    -0.166476   | -0.172333  | 0.11274   |
| phase2_high_scale_baseline_nav_dd10_cut50_recover5 | 2022_bear    | 2022-01-03 | 2022-10-14 |    -0.224268   | -0.223163  | 0.144165  |
| phase2_high_scale_baseline_nav_dd10_cut50_recover5 | 2025_tariff  | 2025-02-14 | 2025-04-17 |    -0.090729   | -0.138376  | 0.0704462 |
| phase2_high_scale_baseline_nav_dd10_cut50_recover5 | 2026_ytd     | 2026-01-01 | 2026-04-28 |     0.0231135  | -0.116247  | 0.0575626 |
| phase2_high_scale_baseline_nav_dd10_cut50_recover5 | since_phase2 | 2022-01-03 | 2026-04-28 |     0.549686   | -0.223163  | 0.0954981 |

## Budget use

| variant                                            |   min_budget |   avg_budget |   days_derisked_pct |   budget_change_days |   budget_abs_change_sum |   effective_scale_cost_sum |
|:---------------------------------------------------|-------------:|-------------:|--------------------:|---------------------:|------------------------:|---------------------------:|
| baseline_subc                                      |          1   |     1        |           0         |                    0 |                     0   |                  0.0368966 |
| self_nav_dd3_cut20_recover1                        |          0.8 |     0.870397 |           0.648014  |                   85 |                    17   |                  0.0444547 |
| phase2_only_self_nav_dd3_cut20_recover1            |          0.8 |     0.963081 |           0.184593  |                   21 |                     4.2 |                  0.0381427 |
| high_scale_only_self_nav_dd3_cut20_recover1        |          0.8 |     0.930523 |           0.347384  |                  139 |                    27.8 |                  0.0413444 |
| phase2_high_scale_self_nav_dd3_cut20_recover1      |          0.8 |     0.984835 |           0.0758236 |                   37 |                     7.4 |                  0.0370315 |
| baseline_nav_dd3_cut20_recover1                    |          0.8 |     0.878828 |           0.605862  |                   97 |                    19.4 |                  0.0467336 |
| phase2_only_baseline_nav_dd3_cut20_recover1        |          0.8 |     0.964438 |           0.17781   |                   21 |                     4.2 |                  0.0381458 |
| high_scale_only_baseline_nav_dd3_cut20_recover1    |          0.8 |     0.932849 |           0.335756  |                  147 |                    29.4 |                  0.0420888 |
| phase2_high_scale_baseline_nav_dd3_cut20_recover1  |          0.8 |     0.984496 |           0.0775194 |                   39 |                     7.8 |                  0.0372636 |
| self_nav_dd5_cut30_recover2                        |          0.7 |     0.839026 |           0.536579  |                   47 |                    14.1 |                  0.0399134 |
| phase2_only_self_nav_dd5_cut30_recover2            |          0.7 |     0.951672 |           0.161095  |                   11 |                     3.3 |                  0.0364368 |
| high_scale_only_self_nav_dd5_cut30_recover2        |          0.7 |     0.930959 |           0.230136  |                   85 |                    25.5 |                  0.0419003 |
| phase2_high_scale_self_nav_dd5_cut30_recover2      |          0.7 |     0.981686 |           0.0610465 |                   25 |                     7.5 |                  0.0375192 |
| baseline_nav_dd5_cut30_recover2                    |          0.7 |     0.859302 |           0.468992  |                   57 |                    17.1 |                  0.0427909 |
| phase2_only_baseline_nav_dd5_cut30_recover2        |          0.7 |     0.952616 |           0.157946  |                   11 |                     3.3 |                  0.0365967 |
| high_scale_only_baseline_nav_dd5_cut30_recover2    |          0.7 |     0.935247 |           0.215843  |                   83 |                    24.9 |                  0.0420509 |
| phase2_high_scale_baseline_nav_dd5_cut30_recover2  |          0.7 |     0.981468 |           0.0617733 |                   25 |                     7.5 |                  0.0376791 |
| self_nav_dd7_cut50_recover3                        |          0.5 |     0.723595 |           0.55281   |                   31 |                    15.5 |                  0.03693   |
| phase2_only_self_nav_dd7_cut50_recover3            |          0.5 |     0.923328 |           0.153343  |                    9 |                     4.5 |                  0.0363807 |
| high_scale_only_self_nav_dd7_cut50_recover3        |          0.5 |     0.896681 |           0.206638  |                   52 |                    26   |                  0.0476068 |
| phase2_high_scale_self_nav_dd7_cut50_recover3      |          0.5 |     0.972747 |           0.0545058 |                   14 |                     7   |                  0.039629  |
| baseline_nav_dd7_cut50_recover3                    |          0.5 |     0.817829 |           0.364341  |                   37 |                    18.5 |                  0.0413885 |
| phase2_only_baseline_nav_dd7_cut50_recover3        |          0.5 |     0.929869 |           0.140262  |                    7 |                     3.5 |                  0.0355836 |
| high_scale_only_baseline_nav_dd7_cut50_recover3    |          0.5 |     0.923207 |           0.153585  |                   52 |                    26   |                  0.048225  |
| phase2_high_scale_baseline_nav_dd7_cut50_recover3  |          0.5 |     0.974079 |           0.0518411 |                   14 |                     7   |                  0.039629  |
| self_nav_dd10_cut50_recover5                       |          0.5 |     0.828125 |           0.34375   |                   17 |                     8.5 |                  0.0357347 |
| phase2_only_self_nav_dd10_cut50_recover5           |          0.5 |     0.935562 |           0.128876  |                    7 |                     3.5 |                  0.0363552 |
| high_scale_only_self_nav_dd10_cut50_recover5       |          0.5 |     0.940407 |           0.119186  |                   34 |                    17   |                  0.0438012 |
| phase2_high_scale_self_nav_dd10_cut50_recover5     |          0.5 |     0.973595 |           0.0528101 |                   14 |                     7   |                  0.039629  |
| baseline_nav_dd10_cut50_recover5                   |          0.5 |     0.886507 |           0.226986  |                   20 |                    10   |                  0.0381018 |
| phase2_only_baseline_nav_dd10_cut50_recover5       |          0.5 |     0.942829 |           0.114341  |                    8 |                     4   |                  0.0368035 |
| high_scale_only_baseline_nav_dd10_cut50_recover5   |          0.5 |     0.961604 |           0.0767926 |                   36 |                    18   |                  0.044758  |
| phase2_high_scale_baseline_nav_dd10_cut50_recover5 |          0.5 |     0.978682 |           0.0426357 |                   16 |                     8   |                  0.0404988 |

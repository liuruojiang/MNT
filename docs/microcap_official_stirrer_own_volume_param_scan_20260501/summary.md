# Microcap Official Stirrer + Own Broad Volume Param Scan

## Method

- Strategy: microcap Top100 `v1.0 + costed` return stream.
- Stirrer condition: official SW industry breadth top1 is one of steel/nonferrous/bank/coal/legacy mining.
- Volume condition: microcap own broad warning leg, `ZZ2000 amount below MA N for D days AND ChiNext amount below MA N for D days`.
- Execution: if condition is true on T close, next trading day microcap scale is 0.50; overlay transition cost is 10bp * abs(scale change).

## Baseline

| window   | start      | end        |   n_days |   annual |     vol |   sharpe |   max_dd |   calmar |   total_return |
|:---------|:-----------|:-----------|---------:|---------:|--------:|---------:|---------:|---------:|---------------:|
| full     | 2010-02-02 | 2026-04-30 |     3940 |  31.0556 | 11.7325 |   2.4540 | -12.2016 |   2.5452 |      7977.2817 |
| last_10y | 2016-05-03 | 2026-04-30 |     2426 |  31.8368 | 13.6082 |   2.1769 | -12.2016 |   2.6092 |      1482.0379 |
| last_5y  | 2021-04-30 | 2026-04-30 |     1208 |  32.3968 | 16.3103 |   1.8769 | -12.2016 |   2.6551 |       306.7286 |
| last_3y  | 2023-05-04 | 2026-04-30 |      723 |  27.5587 | 15.5117 |   1.7137 | -12.2016 |   2.2586 |       107.0354 |

## Best Full-Sample Rows By Sharpe Delta

|      ma |    days |   annual |   sharpe |   max_dd |   annual_delta |   sharpe_delta |   max_dd_delta |   defense_days |   defense_days_pct |
|--------:|--------:|---------:|---------:|---------:|---------------:|---------------:|---------------:|---------------:|-------------------:|
| 53.0000 | 13.0000 |  31.4594 |   2.5211 | -11.9369 |         0.4038 |         0.0671 |         0.2647 |       114.0000 |             2.8934 |
| 60.0000 | 14.0000 |  31.3335 |   2.5172 | -11.9251 |         0.2779 |         0.0631 |         0.2765 |       118.0000 |             2.9949 |
| 45.0000 | 12.0000 |  31.2952 |   2.5171 | -11.2922 |         0.2396 |         0.0631 |         0.9094 |       119.0000 |             3.0203 |
| 45.0000 |  8.0000 |  31.0709 |   2.5156 | -11.2922 |         0.0153 |         0.0616 |         0.9094 |       184.0000 |             4.6701 |
| 50.0000 |  8.0000 |  31.0363 |   2.5154 | -11.2352 |        -0.0193 |         0.0614 |         0.9664 |       200.0000 |             5.0761 |
| 65.0000 | 14.0000 |  31.3184 |   2.5147 | -12.2016 |         0.2628 |         0.0607 |        -0.0000 |       110.0000 |             2.7919 |
| 50.0000 | 12.0000 |  31.2065 |   2.5125 | -11.2922 |         0.1509 |         0.0585 |         0.9094 |       138.0000 |             3.5025 |
| 60.0000 | 12.0000 |  31.1079 |   2.5124 | -12.0251 |         0.0523 |         0.0584 |         0.1765 |       145.0000 |             3.6802 |
| 55.0000 | 12.0000 |  31.2445 |   2.5112 | -11.9369 |         0.1889 |         0.0572 |         0.2647 |       131.0000 |             3.3249 |
| 60.0000 | 13.0000 |  31.1985 |   2.5104 | -12.0251 |         0.1429 |         0.0564 |         0.1765 |       129.0000 |             3.2741 |
| 45.0000 | 13.0000 |  31.2882 |   2.5096 | -12.5666 |         0.2327 |         0.0555 |        -0.3650 |       105.0000 |             2.6650 |
| 53.0000 | 12.0000 |  31.2094 |   2.5092 | -11.9369 |         0.1538 |         0.0552 |         0.2647 |       130.0000 |             3.2995 |

## Current Parameter Row

| scope                                                   | window   |   ma |   days | start      | end        |   n_days |   annual |     vol |   sharpe |   max_dd |   calmar |   total_return |   annual_delta |   sharpe_delta |   max_dd_delta |   signal_days |   signal_days_pct |   defense_days |   defense_days_pct |   switch_count |
|:--------------------------------------------------------|:---------|-----:|-------:|:-----------|:-----------|---------:|---------:|--------:|---------:|---------:|---------:|---------------:|---------------:|---------------:|---------------:|--------------:|------------------:|---------------:|-------------------:|---------------:|
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   53 |     13 | 2010-02-02 | 2026-04-30 |     3940 |  31.4594 | 11.5379 |   2.5211 | -11.9369 |   2.6355 |      8391.0195 |         0.4038 |         0.0671 |         0.2647 |           114 |            2.8934 |            114 |             2.8934 |             64 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   53 |     13 | 2016-05-03 | 2026-04-30 |     2426 |  32.7461 | 13.3450 |   2.2707 | -11.9369 |   2.7433 |      1594.4918 |         0.9093 |         0.0938 |         0.2647 |            92 |            3.7923 |             92 |             3.7923 |             48 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   53 |     13 | 2021-04-30 | 2026-04-30 |     1208 |  34.1688 | 15.9180 |   2.0064 | -11.9369 |   2.8624 |       334.6806 |         1.7720 |         0.1295 |         0.2647 |            62 |            5.1325 |             62 |             5.1325 |             30 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   53 |     13 | 2023-05-04 | 2026-04-30 |      723 |  30.0560 | 14.8652 |   1.9176 | -11.9369 |   2.5179 |       119.3912 |         2.4973 |         0.2039 |         0.2647 |            54 |            7.4689 |             54 |             7.4689 |             22 |

## MA30-90 / 4 Days

| scope                                                   | window   |   ma |   days | start      | end        |   n_days |   annual |     vol |   sharpe |   max_dd |   calmar |   total_return |   annual_delta |   sharpe_delta |   max_dd_delta |   signal_days |   signal_days_pct |   defense_days |   defense_days_pct |   switch_count |
|:--------------------------------------------------------|:---------|-----:|-------:|:-----------|:-----------|---------:|---------:|--------:|---------:|---------:|---------:|---------------:|---------------:|---------------:|---------------:|--------------:|------------------:|---------------:|-------------------:|---------------:|
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   30 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  30.0779 | 11.3210 |   2.4702 | -11.1027 |   2.7091 |      7052.5431 |        -0.9776 |         0.0162 |         1.0989 |           264 |            6.7005 |            264 |             6.7005 |            178 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   30 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  31.2250 | 13.0871 |   2.2214 | -11.1027 |   2.8124 |      1410.1970 |        -0.6119 |         0.0444 |         1.0989 |           211 |            8.6974 |            211 |             8.6974 |            140 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   30 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  32.7684 | 15.5535 |   1.9793 | -10.7763 |   3.0408 |       312.4679 |         0.3716 |         0.1024 |         1.4253 |           134 |           11.0927 |            134 |            11.0927 |             80 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   30 |      4 | 2023-05-04 | 2026-04-30 |      723 |  28.8219 | 14.5056 |   1.8929 |  -9.9443 |   2.8983 |       113.2258 |         1.2632 |         0.1793 |         2.2573 |           108 |           14.9378 |            108 |            14.9378 |             60 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   35 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  29.7714 | 11.3231 |   2.4481 | -11.1969 |   2.6589 |      6783.6976 |        -1.2842 |        -0.0059 |         1.0047 |           279 |            7.0812 |            279 |             7.0812 |            176 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   35 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  30.9171 | 13.0939 |   2.2016 | -11.1969 |   2.7612 |      1375.1725 |        -0.9197 |         0.0247 |         1.0047 |           221 |            9.1096 |            221 |             9.1096 |            138 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   35 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  32.1471 | 15.5820 |   1.9445 | -11.1969 |   2.8711 |       302.9070 |        -0.2498 |         0.0676 |         1.0047 |           141 |           11.6722 |            141 |            11.6722 |             78 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   35 |      4 | 2023-05-04 | 2026-04-30 |      723 |  27.8536 | 14.5616 |   1.8322 |  -9.9443 |   2.8010 |       108.4700 |         0.2950 |         0.1185 |         2.2573 |           114 |           15.7676 |            114 |            15.7676 |             58 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   40 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  30.0589 | 11.3009 |   2.4731 | -11.1969 |   2.6846 |      7035.5737 |        -0.9967 |         0.0191 |         1.0047 |           281 |            7.1320 |            281 |             7.1320 |            188 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   40 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  31.3596 | 13.0639 |   2.2332 | -11.1969 |   2.8007 |      1425.7464 |        -0.4772 |         0.0563 |         1.0047 |           221 |            9.1096 |            221 |             9.1096 |            150 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   40 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  32.6230 | 15.5209 |   1.9758 | -11.1969 |   2.9136 |       310.2133 |         0.2261 |         0.0988 |         1.0047 |           146 |           12.0861 |            146 |            12.0861 |             84 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   40 |      4 | 2023-05-04 | 2026-04-30 |      723 |  28.2260 | 14.4656 |   1.8643 |  -9.9443 |   2.8384 |       110.2907 |         0.6674 |         0.1507 |         2.2573 |           117 |           16.1826 |            117 |            16.1826 |             62 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   45 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  29.9777 | 11.2724 |   2.4733 | -11.1969 |   2.6773 |      6963.5458 |        -1.0779 |         0.0193 |         1.0047 |           298 |            7.5635 |            298 |             7.5635 |            190 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   45 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  31.2796 | 13.0254 |   2.2346 | -11.1969 |   2.7936 |      1416.4924 |        -0.5572 |         0.0576 |         1.0047 |           237 |            9.7692 |            237 |             9.7692 |            148 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   45 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  32.8031 | 15.4800 |   1.9897 | -11.1969 |   2.9297 |       313.0064 |         0.4063 |         0.1128 |         1.0047 |           152 |           12.5828 |            152 |            12.5828 |             80 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   45 |      4 | 2023-05-04 | 2026-04-30 |      723 |  28.3598 | 14.3880 |   1.8812 |  -9.9526 |   2.8495 |       110.9473 |         0.8011 |         0.1675 |         2.2490 |           124 |           17.1508 |            124 |            17.1508 |             58 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   50 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  30.1754 | 11.2741 |   2.4869 | -11.1969 |   2.6950 |      7140.0472 |        -0.8802 |         0.0329 |         1.0047 |           315 |            7.9949 |            315 |             7.9949 |            192 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   50 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  31.3508 | 12.9997 |   2.2431 | -11.1969 |   2.8000 |      1424.7305 |        -0.4860 |         0.0661 |         1.0047 |           252 |           10.3875 |            252 |            10.3875 |            150 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   50 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  32.8912 | 15.4592 |   1.9967 | -11.1969 |   2.9375 |       314.3779 |         0.4944 |         0.1197 |         1.0047 |           156 |           12.9139 |            156 |            12.9139 |             82 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   50 |      4 | 2023-05-04 | 2026-04-30 |      723 |  28.5022 | 14.3507 |   1.8937 |  -9.9526 |   2.8638 |       111.6478 |         0.9436 |         0.1801 |         2.2490 |           128 |           17.7040 |            128 |            17.7040 |             60 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   53 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  29.5930 | 11.2504 |   2.4505 | -11.8260 |   2.5024 |      6631.6360 |        -1.4626 |        -0.0035 |         0.3756 |           321 |            8.1472 |            321 |             8.1472 |            184 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   53 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  30.5122 | 12.9626 |   2.1978 | -11.8260 |   2.5801 |      1330.2149 |        -1.3247 |         0.0209 |         0.3756 |           261 |           10.7585 |            261 |            10.7585 |            152 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   53 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  31.7993 | 15.4163 |   1.9459 | -11.1969 |   2.8400 |       297.6333 |        -0.5976 |         0.0690 |         1.0047 |           156 |           12.9139 |            156 |            12.9139 |             84 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   53 |      4 | 2023-05-04 | 2026-04-30 |      723 |  26.9225 | 14.3021 |   1.8095 | -10.9609 |   2.4562 |       103.9639 |        -0.6361 |         0.0958 |         1.2407 |           125 |           17.2891 |            125 |            17.2891 |             60 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   55 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  29.6020 | 11.2523 |   2.4508 | -11.8260 |   2.5031 |      6639.2578 |        -1.4536 |        -0.0033 |         0.3756 |           324 |            8.2234 |            324 |             8.2234 |            186 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   55 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  30.4718 | 12.9634 |   2.1952 | -11.8260 |   2.5767 |      1325.8066 |        -1.3650 |         0.0182 |         0.3756 |           265 |           10.9233 |            265 |            10.9233 |            154 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   55 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  31.6305 | 15.4184 |   1.9370 | -11.1969 |   2.8249 |       295.0938 |        -0.7664 |         0.0601 |         1.0047 |           159 |           13.1623 |            159 |            13.1623 |             88 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   55 |      4 | 2023-05-04 | 2026-04-30 |      723 |  26.9485 | 14.3183 |   1.8091 | -10.2654 |   2.6252 |       104.0888 |        -0.6101 |         0.0954 |         1.9362 |           127 |           17.5657 |            127 |            17.5657 |             62 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   60 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  29.5025 | 11.2338 |   2.4475 | -11.8260 |   2.4947 |      6555.6849 |        -1.5531 |        -0.0065 |         0.3756 |           329 |            8.3503 |            329 |             8.3503 |            190 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   60 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  30.3633 | 12.9395 |   2.1923 | -11.8260 |   2.5675 |      1314.0040 |        -1.4735 |         0.0154 |         0.3756 |           273 |           11.2531 |            273 |            11.2531 |            156 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   60 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  31.1640 | 15.3703 |   1.9185 | -11.1969 |   2.7833 |       288.1433 |        -1.2329 |         0.0415 |         1.0047 |           169 |           13.9901 |            169 |            13.9901 |             90 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   60 |      4 | 2023-05-04 | 2026-04-30 |      723 |  26.5009 | 14.3095 |   1.7844 | -10.3553 |   2.5592 |       101.9448 |        -1.0578 |         0.0707 |         1.8463 |           134 |           18.5339 |            134 |            18.5339 |             64 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   65 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  29.6844 | 11.2542 |   2.4562 | -11.8260 |   2.5101 |      6709.1492 |        -1.3712 |         0.0022 |         0.3756 |           309 |            7.8426 |            309 |             7.8426 |            182 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   65 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  30.7279 | 12.9772 |   2.2087 | -11.8260 |   2.5983 |      1354.0098 |        -1.1089 |         0.0317 |         0.3756 |           254 |           10.4699 |            254 |            10.4699 |            152 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   65 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  31.5396 | 15.4191 |   1.9322 | -11.1969 |   2.8168 |       293.7319 |        -0.8573 |         0.0553 |         1.0047 |           154 |           12.7483 |            154 |            12.7483 |             84 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   65 |      4 | 2023-05-04 | 2026-04-30 |      723 |  26.8376 | 14.3854 |   1.7950 | -10.4674 |   2.5639 |       103.5560 |        -0.7211 |         0.0813 |         1.7342 |           120 |           16.5975 |            120 |            16.5975 |             60 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   70 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  29.6060 | 11.2573 |   2.4500 | -11.9591 |   2.4756 |      6642.6310 |        -1.4496 |        -0.0040 |         0.2425 |           305 |            7.7411 |            305 |             7.7411 |            186 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   70 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  30.5481 | 12.9806 |   2.1971 | -11.9591 |   2.5544 |      1334.1583 |        -1.2887 |         0.0202 |         0.2425 |           252 |           10.3875 |            252 |            10.3875 |            156 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   70 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  31.5434 | 15.4309 |   1.9311 | -11.1969 |   2.8172 |       293.7896 |        -0.8534 |         0.0541 |         1.0047 |           150 |           12.4172 |            150 |            12.4172 |             84 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   70 |      4 | 2023-05-04 | 2026-04-30 |      723 |  27.0880 | 14.3930 |   1.8084 | -10.4674 |   2.5878 |       104.7598 |        -0.4707 |         0.0947 |         1.7342 |           117 |           16.1826 |            117 |            16.1826 |             60 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   75 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  29.5417 | 11.2524 |   2.4464 | -11.5170 |   2.5650 |      6588.4616 |        -1.5139 |        -0.0076 |         0.6846 |           307 |            7.7919 |            307 |             7.7919 |            192 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   75 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  30.4428 | 12.9738 |   2.1917 | -11.5170 |   2.6433 |      1322.6365 |        -1.3941 |         0.0148 |         0.6846 |           254 |           10.4699 |            254 |            10.4699 |            162 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   75 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  31.4225 | 15.4378 |   1.9241 | -11.1969 |   2.8064 |       291.9829 |        -0.9744 |         0.0471 |         1.0047 |           147 |           12.1689 |            147 |            12.1689 |             88 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   75 |      4 | 2023-05-04 | 2026-04-30 |      723 |  26.6872 | 14.4048 |   1.7842 | -10.4674 |   2.5496 |       102.8351 |        -0.8715 |         0.0705 |         1.7342 |           117 |           16.1826 |            117 |            16.1826 |             64 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   80 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  29.6268 | 11.2569 |   2.4516 | -11.5170 |   2.5724 |      6660.2449 |        -1.4287 |        -0.0024 |         0.6846 |           302 |            7.6650 |            302 |             7.6650 |            188 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   80 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  30.5007 | 12.9796 |   2.1944 | -11.5170 |   2.6483 |      1328.9646 |        -1.3361 |         0.0174 |         0.6846 |           253 |           10.4287 |            253 |            10.4287 |            162 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   80 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  31.4009 | 15.4368 |   1.9231 | -11.1969 |   2.8044 |       291.6605 |        -0.9960 |         0.0461 |         1.0047 |           146 |           12.0861 |            146 |            12.0861 |             84 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   80 |      4 | 2023-05-04 | 2026-04-30 |      723 |  26.6523 | 14.4030 |   1.7824 | -10.6020 |   2.5139 |       102.6683 |        -0.9064 |         0.0687 |         1.5996 |           116 |           16.0443 |            116 |            16.0443 |             60 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   85 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  29.7022 | 11.2633 |   2.4556 | -11.5170 |   2.5790 |      6724.3005 |        -1.3534 |         0.0016 |         0.6846 |           292 |            7.4112 |            292 |             7.4112 |            182 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   85 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  30.6345 | 12.9885 |   2.2012 | -11.5170 |   2.6599 |      1343.6680 |        -1.2023 |         0.0242 |         0.6846 |           244 |           10.0577 |            244 |            10.0577 |            156 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   85 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  31.4396 | 15.4510 |   1.9234 | -11.1969 |   2.8079 |       292.2378 |        -0.9573 |         0.0465 |         1.0047 |           141 |           11.6722 |            141 |            11.6722 |             82 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   85 |      4 | 2023-05-04 | 2026-04-30 |      723 |  26.7147 | 14.4286 |   1.7830 | -10.6020 |   2.5198 |       102.9670 |        -0.8440 |         0.0694 |         1.5996 |           111 |           15.3527 |            111 |            15.3527 |             58 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | full     |   90 |      4 | 2010-02-02 | 2026-04-30 |     3940 |  29.5759 | 11.2606 |   2.4472 | -11.5170 |   2.5680 |      6617.2543 |        -1.4796 |        -0.0068 |         0.6846 |           291 |            7.3858 |            291 |             7.3858 |            178 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_10y |   90 |      4 | 2016-05-03 | 2026-04-30 |     2426 |  30.3488 | 12.9825 |   2.1846 | -11.5170 |   2.6351 |      1312.4312 |        -1.4880 |         0.0077 |         0.6846 |           249 |           10.2638 |            249 |            10.2638 |            154 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_5y  |   90 |      4 | 2021-04-30 | 2026-04-30 |     1208 |  30.8864 | 15.4510 |   1.8949 | -11.1969 |   2.7585 |       284.0545 |        -1.5104 |         0.0180 |         1.0047 |           140 |           11.5894 |            140 |            11.5894 |             82 |
| microcap_v1_0_costed_top1_stirrer_broad_own_volume_half | last_3y  |   90 |      4 | 2023-05-04 | 2026-04-30 |      723 |  26.1983 | 14.3961 |   1.7572 | -10.3116 |   2.5407 |       100.5042 |        -1.3603 |         0.0435 |         1.8900 |           111 |           15.3527 |            111 |            15.3527 |             58 |

## Ridge

- Full-sample best: MA53 / 13 days.
- Near-ridge count within Sharpe delta 0.02: 23.
- MA range: 45 to 65; days range: 6 to 16.

## Direct 883418.TI Volume Leg

- Available in this run: False.
- Detail: RuntimeError: 883418.TI volume data unavailable; set MICROCAP_DIRECT_VOLUME_CSV or place 883418.TI.csv under .microcap_index_cache. no candidate file found

## Meta

```json
{
  "microcap_costed_nav_path": "C:\\Users\\Administrator.DESKTOP-95I7VVU\\Desktop\\动量策略\\微盘股对冲策略\\outputs\\microcap_top100_mom16_hedge_zz1000_biweekly_thursday_16y_costed_nav.csv",
  "microcap_costed_nav_rows": 3940,
  "microcap_return_start": "2010-02-02",
  "microcap_return_end": "2026-04-30",
  "microcap_latest_trade_date": "2026-04-30",
  "microcap_history_anchor": {
    "latest_trade_date": "2026-04-30",
    "current_date": "2026-05-01",
    "stale_calendar_days": 1,
    "max_stale_anchor_days": 5,
    "is_stale": false,
    "status": "fresh"
  },
  "microcap_proxy_source_used": "local_cache_proxy_recent_extension",
  "microcap_proxy_method_note": "Local cache reconstruction using raw close data, OHLC tradeability checks, and share-change data. This practical version anchors biweekly rebalances to Thursday signal dates, excludes suspended names from signal-date ranking, and applies conservative close execution: if the signal-date close is locked at the price limit, buys or sells are blocked at the close.",
  "official_sw_signal_path": "C:\\Users\\Administrator.DESKTOP-95I7VVU\\Desktop\\动量策略\\A股美股动量组合策略\\docs\\dadk_microcap_official_sw_width_volume_filter_20260501\\official_sw_width_signals.csv",
  "official_sw_rows": 3944,
  "official_sw_start": "2010-01-29",
  "official_sw_end": "2026-04-30",
  "stirrer_condition": "official SW industry breadth top1 is one of steel/nonferrous/bank/coal/legacy mining",
  "volume_meta": {
    "broad_volume_mode": "and",
    "sources": {
      "zz2000": {
        "secid": "2.932000",
        "label": "中证2000",
        "source": "CSIndex official amount",
        "rows": 2998,
        "start": "2010-01-01",
        "end": "2026-04-30"
      },
      "cyb": {
        "secid": "0.399006",
        "label": "创业板",
        "source": "Sohu amount",
        "rows": 3861,
        "start": "2010-06-01",
        "end": "2026-04-30"
      }
    }
  },
  "direct_volume": {
    "available": false,
    "error": "RuntimeError: 883418.TI volume data unavailable; set MICROCAP_DIRECT_VOLUME_CSV or place 883418.TI.csv under .microcap_index_cache. no candidate file found"
  },
  "current_formal_broad_param": {
    "ma": 53,
    "days": 13,
    "mode": "and"
  },
  "scale_when_true": 0.5,
  "extra_cost_bps_per_abs_scale_change": 10.0,
  "ma_values": [
    20,
    25,
    30,
    35,
    40,
    45,
    50,
    53,
    55,
    60,
    65,
    70,
    75,
    80,
    85,
    90
  ],
  "day_values": [
    2,
    4,
    6,
    8,
    10,
    12,
    13,
    14,
    16,
    18,
    20,
    22,
    24,
    26,
    28,
    30
  ],
  "ridge": {
    "window": "full",
    "tolerance_sharpe_delta": 0.02,
    "best": {
      "ma": 53,
      "days": 13,
      "annual": 31.45936584231659,
      "sharpe": 2.521144214461152,
      "max_dd": -11.936913813673977,
      "annual_delta": 0.40378816314177257,
      "sharpe_delta": 0.06713469462493427,
      "max_dd_delta": 0.2646986274757239,
      "defense_days_pct": 2.8934010152284264
    },
    "near_count": 23,
    "near_ma_min": 45,
    "near_ma_max": 65,
    "near_days_min": 6,
    "near_days_max": 16
  }
}
```
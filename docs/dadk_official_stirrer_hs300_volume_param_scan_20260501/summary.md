# DK HS300 Volume Parameter Scan With Fixed Official Stirrer

## Fixed Conditions

- Stirrer condition: official SW stock breadth `top1_is_stirrer`.
- Volume condition: HS300 amount below its MA for consecutive days.
- Main action: next-day DK/ADK exposure is scaled to 50%.
- Main cost: `10bp * abs(DK scale change)`.

## Current DK Volume Parameter

- Current DK warning-only parameter: HS300 `MA40` / `16` days.
- It is warning-only in V7.2 and is not part of DK backtest sizing unless explicitly overlaid.

## Baseline Scope Check

- DK/ADK production-aligned full-history MaxDD: -20.01% (2016-12-12 to 2017-02-20).
- DK/ADK valid return sample: 2015-04-03 to 2026-04-17.
- PV A/DK/B common-sample MaxDD, shown only as cross-check: -9.54%.
- Earlier 2004-start results are invalid because the DK five-index universe was incomplete before `000852` existed.

## Best By Sharpe Delta

- Scope: `dk_sleeve`, window: `full`
- Best: MA65 / 4 days
- Annual: 32.94%, delta 0.23pp
- Sharpe: 1.631, delta 0.095
- MaxDD: -16.44%, improvement 3.57pp
- Defense days: 12.93%

## Ridge Width

- Near-best tolerance: Sharpe delta within 0.020
- Near-best count: 5
- MA range: 60 to 70
- Days range: 4 to 14

## Recorded Candidate

- Current working candidate for DK/ADK + four-stirrer + HS300 volume: `MA60 / 4 days`, scale DK to `50%` on the next trading day.
- Reason: within the main `MA60~70 / 4 days` ridge, while slightly less fitted than `MA65 / 4 days`; full-sample annual delta `+0.12pp`, MaxDD improvement `+3.57pp`.

## Current Parameter Row

| scope     | window   |   ma |   days | start      | end        |   n_days |   annual |     vol |   sharpe |   max_dd |   calmar |   total_return |   annual_delta |   sharpe_delta |   max_dd_delta |   signal_days_pct |   defense_days_pct |   switch_count |
|:----------|:---------|-----:|-------:|:-----------|:-----------|---------:|---------:|--------:|---------:|---------:|---------:|---------------:|---------------:|---------------:|---------------:|------------------:|-------------------:|---------------:|
| dk_sleeve | full     |   40 |     16 | 2015-04-03 | 2026-04-17 |     2684 |  32.7611 | 20.1094 |   1.5613 | -17.4621 |   1.8761 |         2183.4 |         0.0553 |         0.0252 |         2.5441 |            2.7571 |             2.7571 |             62 |

## Top 15

| scope     | window   |   ma |   days | start      | end        |   n_days |   annual |     vol |   sharpe |   max_dd |   calmar |   total_return |   annual_delta |   sharpe_delta |   max_dd_delta |   signal_days_pct |   defense_days_pct |   switch_count |
|:----------|:---------|-----:|-------:|:-----------|:-----------|---------:|---------:|--------:|---------:|---------:|---------:|---------------:|---------------:|---------------:|---------------:|------------------:|-------------------:|---------------:|
| dk_sleeve | full     |   65 |      4 | 2015-04-03 | 2026-04-17 |     2684 |  32.9398 | 19.2324 |   1.6308 | -16.439  |   2.0038 |        2217.55 |         0.2339 |         0.0947 |         3.5672 |           12.9285 |            12.9285 |            223 |
| dk_sleeve | full     |   60 |      4 | 2015-04-03 | 2026-04-17 |     2684 |  32.8299 | 19.237  |   1.626  | -16.439  |   1.9971 |        2196.49 |         0.124  |         0.0899 |         3.5672 |           12.7794 |            12.7794 |            230 |
| dk_sleeve | full     |   70 |      4 | 2015-04-03 | 2026-04-17 |     2684 |  32.7714 | 19.2252 |   1.6245 | -16.439  |   1.9935 |        2185.36 |         0.0656 |         0.0884 |         3.5672 |           12.8912 |            12.8912 |            222 |
| dk_sleeve | full     |   70 |     14 | 2015-04-03 | 2026-04-17 |     2684 |  33.617  | 19.7801 |   1.6177 | -17.4621 |   1.9251 |        2351.27 |         0.9112 |         0.0816 |         2.5441 |            5.6632 |             5.6632 |            110 |
| dk_sleeve | full     |   65 |     14 | 2015-04-03 | 2026-04-17 |     2684 |  33.5629 | 19.7816 |   1.6155 | -17.4621 |   1.922  |        2340.33 |         0.8571 |         0.0794 |         2.5441 |            5.7004 |             5.7004 |            112 |
| dk_sleeve | full     |   80 |      4 | 2015-04-03 | 2026-04-17 |     2684 |  32.354  | 19.2224 |   1.6077 | -16.439  |   1.9681 |        2107.27 |        -0.3519 |         0.0716 |         3.5672 |           13.0775 |            13.0775 |            218 |
| dk_sleeve | full     |   75 |      4 | 2015-04-03 | 2026-04-17 |     2684 |  32.2426 | 19.1951 |   1.6052 | -16.439  |   1.9613 |        2086.87 |        -0.4632 |         0.0691 |         3.5672 |           13.0775 |            13.0775 |            224 |
| dk_sleeve | full     |   70 |      2 | 2015-04-03 | 2026-04-17 |     2684 |  31.7301 | 18.9414 |   1.6029 | -16.0793 |   1.9734 |        1995.1  |        -0.9757 |         0.0668 |         3.927  |           16.8405 |            16.8405 |            306 |
| dk_sleeve | full     |   70 |     12 | 2015-04-03 | 2026-04-17 |     2684 |  33.0515 | 19.7209 |   1.5997 | -17.4621 |   1.8928 |        2239.14 |         0.3457 |         0.0636 |         2.5441 |            6.5201 |             6.5201 |            118 |
| dk_sleeve | full     |   60 |     14 | 2015-04-03 | 2026-04-17 |     2684 |  33.2298 | 19.832  |   1.5988 | -17.4621 |   1.903  |        2273.97 |         0.5239 |         0.0627 |         2.5441 |            5.1788 |             5.1788 |            108 |
| dk_sleeve | full     |   70 |     16 | 2015-04-03 | 2026-04-17 |     2684 |  33.489  | 19.9934 |   1.5975 | -17.4621 |   1.9178 |        2325.45 |         0.7831 |         0.0614 |         2.5441 |            4.769  |             4.769  |             98 |
| dk_sleeve | full     |   65 |     12 | 2015-04-03 | 2026-04-17 |     2684 |  32.9976 | 19.7224 |   1.5974 | -17.4621 |   1.8897 |        2228.71 |         0.2918 |         0.0613 |         2.5441 |            6.5574 |             6.5574 |            120 |
| dk_sleeve | full     |   65 |     16 | 2015-04-03 | 2026-04-17 |     2684 |  33.4409 | 19.995  |   1.5955 | -17.4621 |   1.9151 |        2315.83 |         0.735  |         0.0594 |         2.5441 |            4.7317 |             4.7317 |             98 |
| dk_sleeve | full     |   55 |     14 | 2015-04-03 | 2026-04-17 |     2684 |  33.1166 | 19.9075 |   1.5891 | -17.4621 |   1.8965 |        2251.81 |         0.4108 |         0.053  |         2.5441 |            4.9925 |             4.9925 |            108 |
| dk_sleeve | full     |   75 |      2 | 2015-04-03 | 2026-04-17 |     2684 |  31.2952 | 18.892  |   1.5884 | -16.0793 |   1.9463 |        1920    |        -1.4106 |         0.0523 |         3.927  |           16.8778 |            16.8778 |            308 |

# Official SW Width + Volume Filter on DADK and Microcap

## Data

- SW classification: `C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\新策略学习\outputs\sws_official_probe_20260501\StockClassifyUse_stock.xls`
- Stock prices: `C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\微盘股对冲策略\.microcap_index_cache\prices_raw`
- Price files: `5014`, used stocks: `5012`
- Width sample: `2010-01-04` to `2026-04-30`
- Universe caveat: local `prices_raw` cache, not exact point-in-time `000985` constituents.
- Volume leg: V7.2 formal broad amount contraction rule, observed at close and applied to next return.
- Overlay cost: `10bp * abs(scale change)` in addition to source sleeve costs.

## Signal Coverage

| signal | coverage |
|---|---:|
| volume_risk | 40.44% |
| official_top1_width | 31.54% |
| official_top3_width | 51.57% |
| official_top1_and_volume | 15.57% |
| official_top3_and_volume | 22.92% |

## Full-Sample Results

| sleeve | scenario | annual | sharpe | max_dd | annual_delta | sharpe_delta | max_dd_delta | defense_days |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Sub-A-DK | baseline | 21.41% | 1.113 | -40.96% | 0.00% | 0.000 | 0.00% | 0.00% |
| Sub-A-DK | official_top1_volume_half | 19.28% | 1.161 | -32.81% | -2.13% | 0.048 | 8.15% | 37.33% |
| Sub-A-DK | official_top1_volume_cash | 16.79% | 1.090 | -33.03% | -4.62% | -0.023 | 7.94% | 37.33% |
| Sub-A-DK | official_top3_volume_half | 19.04% | 1.175 | -30.26% | -2.38% | 0.062 | 10.70% | 42.80% |
| Sub-A-DK | official_top3_volume_cash | 16.25% | 1.097 | -28.15% | -5.16% | -0.016 | 12.81% | 42.80% |
| Microcap | baseline | 32.22% | 2.547 | -11.29% | 0.00% | 0.000 | 0.00% | 0.00% |
| Microcap | official_top1_volume_half | 27.97% | 2.411 | -10.76% | -4.24% | -0.136 | 0.54% | 15.46% |
| Microcap | official_top1_volume_cash | 23.79% | 2.139 | -10.88% | -8.42% | -0.408 | 0.42% | 15.46% |
| Microcap | official_top3_volume_half | 25.90% | 2.334 | -10.85% | -6.32% | -0.214 | 0.44% | 22.73% |
| Microcap | official_top3_volume_cash | 19.78% | 1.906 | -13.19% | -12.43% | -0.641 | -1.90% | 22.73% |

## Top1 + Volume Half, Recent Windows

| sleeve | window | annual_delta | sharpe_delta | max_dd_delta | defense_days |
|---|---|---:|---:|---:|---:|
| Sub-A-DK | last_10y | -2.68% | 0.018 | 3.70% | 18.93% |
| Sub-A-DK | last_5y | -4.00% | -0.034 | 2.25% | 19.65% |
| Sub-A-DK | last_3y | -1.21% | 0.067 | 2.25% | 21.46% |
| Microcap | last_10y | -4.93% | -0.137 | 0.54% | 18.57% |
| Microcap | last_5y | -5.80% | -0.147 | 0.02% | 19.25% |
| Microcap | last_3y | -3.53% | -0.034 | 0.19% | 20.31% |

## Readout

- This is a stricter and more official breadth version than the earlier SW-index proxy test.
- Treat the result as research-grade until exact historical CSI All Share constituents are added.
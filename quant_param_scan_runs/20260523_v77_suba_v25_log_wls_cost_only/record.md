# V7.7 Sub-A With Microcap v2.5 Log-WLS Momentum, Cost Only

## Decision

Do not replace the A-strategy original momentum with this v2.5 log-WLS family yet. The best scan rows improve drawdown, but the original Sub-A cost-only baseline still has the cleaner 5Y/3Y/1Y return and Sharpe profile.

## Stability

Research lead only. Best rows cluster around LB 20-28 and HL 8-12, so the grid has a platform, but recent-window underperformance keeps it below promotion quality.

## Scope

- A-share pool: V7.7 Sub-A current 5 equity total-return indexes plus 10Y treasury total-return index.
- Baseline: V7.7 Sub-A original `price / MA60` weighted slope momentum, cost only.
- Test signal: microcap v2.5 `annualized_log_wls_score` applied to each Sub-A asset close series.
- Grid: lookback `4..40`, halflife `[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0]`, threshold `[0.0, 0.4]`.
- Removed: R2, absolute momentum, target-vol, same-side overheat, volume overlay, cash peak-decay, staged entry, and cash yield.
- Retained: V7.7 `CN_COMMISSION=0.001` one-way turnover cost.

## Data

- Close data: 2010-06-01 to 2026-05-22, rows 3878.
- Raw common start by first available local series: 2010-06-01.
- Formal full-sample floor: 2014-10-17 (workspace rule: replacement-signal test uses full current Sub-A pool including ZZ1000; formal conclusions start no earlier than ZZ1000 publication date).

## Results

### full
- `suba_original_bias60_20_cost_only`: annual 20.97%, maxDD -38.78%, Sharpe 0.91, holding 92.1%, trades 302
- `v25_lb22_hl8_th0p4_cost_only`: annual 20.74%, maxDD -34.36%, Sharpe 0.94, holding 58.4%, trades 225
- `v25_lb23_hl8_th0p4_cost_only`: annual 20.66%, maxDD -35.27%, Sharpe 0.93, holding 57.8%, trades 210
- `v25_lb25_hl10_th0p4_cost_only`: annual 20.46%, maxDD -35.56%, Sharpe 0.92, holding 56.7%, trades 208
- `v25_lb24_hl10_th0p4_cost_only`: annual 20.21%, maxDD -34.93%, Sharpe 0.91, holding 57.1%, trades 207
- `v25_lb22_hl10_th0p4_cost_only`: annual 20.19%, maxDD -33.44%, Sharpe 0.91, holding 58.2%, trades 217

### full_proxy
- `suba_original_bias60_20_cost_only`: annual 21.86%, maxDD -38.78%, Sharpe 0.98, holding 90.9%, trades 400
- `v25_lb25_hl10_th0p4_cost_only`: annual 19.06%, maxDD -35.56%, Sharpe 0.89, holding 56.2%, trades 284
- `v25_lb24_hl10_th0p4_cost_only`: annual 18.17%, maxDD -34.93%, Sharpe 0.85, holding 56.8%, trades 289
- `v25_lb19_hl3_th0p4_cost_only`: annual 17.59%, maxDD -30.87%, Sharpe 0.84, holding 61.1%, trades 491
- `v25_lb22_hl8_th0p4_cost_only`: annual 17.95%, maxDD -34.36%, Sharpe 0.83, holding 57.8%, trades 316
- `v25_lb24_hl12_th0p4_cost_only`: annual 17.75%, maxDD -35.62%, Sharpe 0.83, holding 56.6%, trades 281

### last_10y
- `suba_original_bias60_20_cost_only`: annual 12.12%, maxDD -32.88%, Sharpe 0.59, holding 91.9%, trades 257
- `v25_lb22_hl8_th0p4_cost_only`: annual 15.47%, maxDD -24.42%, Sharpe 0.80, holding 56.3%, trades 191
- `v25_lb21_hl10_th0p4_cost_only`: annual 15.37%, maxDD -21.60%, Sharpe 0.79, holding 57.0%, trades 203
- `v25_lb21_hl12_th0p4_cost_only`: annual 15.18%, maxDD -22.48%, Sharpe 0.78, holding 56.9%, trades 199
- `v25_lb22_hl10_th0p4_cost_only`: annual 14.91%, maxDD -23.60%, Sharpe 0.77, holding 56.2%, trades 184
- `v25_lb20_hl8_th0p4_cost_only`: annual 14.60%, maxDD -22.14%, Sharpe 0.76, holding 57.6%, trades 227

### last_5y
- `suba_original_bias60_20_cost_only`: annual 18.19%, maxDD -26.04%, Sharpe 0.81, holding 93.1%, trades 119
- `v25_lb40_hl8_th0p0_cost_only`: annual 21.61%, maxDD -20.25%, Sharpe 0.96, holding 94.1%, trades 73
- `v25_lb39_hl8_th0p0_cost_only`: annual 21.12%, maxDD -20.25%, Sharpe 0.94, holding 94.1%, trades 74
- `v25_lb38_hl10_th0p0_cost_only`: annual 21.22%, maxDD -20.25%, Sharpe 0.93, holding 94.5%, trades 76
- `v25_lb39_hl10_th0p0_cost_only`: annual 20.56%, maxDD -20.25%, Sharpe 0.91, holding 94.7%, trades 72
- `v25_lb28_hl12_th0p4_cost_only`: annual 18.40%, maxDD -20.25%, Sharpe 0.89, holding 51.2%, trades 68

### last_3y
- `suba_original_bias60_20_cost_only`: annual 27.57%, maxDD -23.60%, Sharpe 1.10, holding 93.3%, trades 75
- `v25_lb38_hl10_th0p0_cost_only`: annual 29.68%, maxDD -20.25%, Sharpe 1.17, holding 95.6%, trades 45
- `v25_lb40_hl10_th0p0_cost_only`: annual 29.18%, maxDD -20.25%, Sharpe 1.15, holding 96.3%, trades 38
- `v25_lb39_hl10_th0p0_cost_only`: annual 29.14%, maxDD -20.25%, Sharpe 1.15, holding 95.9%, trades 41
- `v25_lb40_hl8_th0p0_cost_only`: annual 28.60%, maxDD -20.25%, Sharpe 1.13, holding 95.3%, trades 42
- `v25_lb20_hl8_th0p4_cost_only`: annual 26.59%, maxDD -20.25%, Sharpe 1.12, holding 48.1%, trades 54

### last_1y
- `suba_original_bias60_20_cost_only`: annual 65.45%, maxDD -8.47%, Sharpe 3.11, holding 90.9%, trades 22
- `v25_lb37_hl12_th0p0_cost_only`: annual 96.76%, maxDD -10.00%, Sharpe 3.93, holding 96.7%, trades 7
- `v25_lb35_hl12_th0p0_cost_only`: annual 95.48%, maxDD -10.00%, Sharpe 3.85, holding 97.1%, trades 11
- `v25_lb38_hl10_th0p0_cost_only`: annual 93.69%, maxDD -10.00%, Sharpe 3.74, holding 97.9%, trades 7
- `v25_lb39_hl10_th0p0_cost_only`: annual 93.64%, maxDD -10.00%, Sharpe 3.74, holding 98.4%, trades 7
- `v25_lb36_hl12_th0p0_cost_only`: annual 92.26%, maxDD -10.00%, Sharpe 3.73, holding 96.7%, trades 9

## Top Formal Candidates

- `v25_lb22_hl8_th0p4_cost_only`: annual 20.74%, maxDD -34.36%, Sharpe 0.94, LB 22, HL 8.0, threshold 0.40
- `v25_lb23_hl8_th0p4_cost_only`: annual 20.66%, maxDD -35.27%, Sharpe 0.93, LB 23, HL 8.0, threshold 0.40
- `v25_lb25_hl10_th0p4_cost_only`: annual 20.46%, maxDD -35.56%, Sharpe 0.92, LB 25, HL 10.0, threshold 0.40
- `v25_lb24_hl10_th0p4_cost_only`: annual 20.21%, maxDD -34.93%, Sharpe 0.91, LB 24, HL 10.0, threshold 0.40
- `v25_lb22_hl10_th0p4_cost_only`: annual 20.19%, maxDD -33.44%, Sharpe 0.91, LB 22, HL 10.0, threshold 0.40
- `v25_lb24_hl6_th0p4_cost_only`: annual 20.26%, maxDD -33.13%, Sharpe 0.91, LB 24, HL 6.0, threshold 0.40
- `v25_lb26_hl12_th0p4_cost_only`: annual 20.08%, maxDD -35.49%, Sharpe 0.90, LB 26, HL 12.0, threshold 0.40
- `v25_lb24_hl12_th0p4_cost_only`: annual 20.02%, maxDD -35.62%, Sharpe 0.90, LB 24, HL 12.0, threshold 0.40
- `v25_lb27_hl10_th0p4_cost_only`: annual 19.89%, maxDD -36.60%, Sharpe 0.90, LB 27, HL 10.0, threshold 0.40
- `v25_lb21_hl10_th0p4_cost_only`: annual 19.91%, maxDD -39.21%, Sharpe 0.89, LB 21, HL 10.0, threshold 0.40

## Top 10Y Candidates

- `v25_lb22_hl8_th0p4_cost_only`: annual 15.47%, maxDD -24.42%, Sharpe 0.80, LB 22, HL 8.0, threshold 0.40
- `v25_lb21_hl10_th0p4_cost_only`: annual 15.37%, maxDD -21.60%, Sharpe 0.79, LB 21, HL 10.0, threshold 0.40
- `v25_lb21_hl12_th0p4_cost_only`: annual 15.18%, maxDD -22.48%, Sharpe 0.78, LB 21, HL 12.0, threshold 0.40
- `v25_lb22_hl10_th0p4_cost_only`: annual 14.91%, maxDD -23.60%, Sharpe 0.77, LB 22, HL 10.0, threshold 0.40
- `v25_lb20_hl8_th0p4_cost_only`: annual 14.60%, maxDD -22.14%, Sharpe 0.76, LB 20, HL 8.0, threshold 0.40
- `v25_lb26_hl12_th0p0_cost_only`: annual 16.17%, maxDD -25.33%, Sharpe 0.76, LB 26, HL 12.0, threshold 0.00
- `v25_lb22_hl12_th0p4_cost_only`: annual 14.66%, maxDD -22.91%, Sharpe 0.75, LB 22, HL 12.0, threshold 0.40
- `v25_lb23_hl8_th0p4_cost_only`: annual 14.65%, maxDD -23.47%, Sharpe 0.75, LB 23, HL 8.0, threshold 0.40
- `v25_lb27_hl10_th0p0_cost_only`: annual 16.12%, maxDD -25.91%, Sharpe 0.75, LB 27, HL 10.0, threshold 0.00
- `v25_lb19_hl12_th0p4_cost_only`: annual 14.48%, maxDD -20.69%, Sharpe 0.75, LB 19, HL 12.0, threshold 0.40
## Outputs

- `daily_*.csv`
- `scan_summary.csv`
- `window_metrics.csv`
- `scan_meta.json`

## Finalization

- Finalized at: 2026-05-23T21:27:00+08:00
- Decision: do_not_replace_original_momentum_yet; best v2.5 log-WLS rows are research leads only because recent-window returns and Sharpe remain weaker than the Sub-A original momentum baseline
- Stability label: research_lead_not_promoted
- Complete checker: PASS

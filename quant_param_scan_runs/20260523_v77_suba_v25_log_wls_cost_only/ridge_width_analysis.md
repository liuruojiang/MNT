# Ridge Width Analysis

Definitions:

- Axis width: contiguous lookback or halflife values through the target point with Sharpe >= 95% of that target point in the same window.
- Surface plateau: all points in the same threshold surface with Sharpe >= 95% of that window's peak Sharpe.

## formal_defensive_ridge `v25_lb22_hl8_th0p4_cost_only`

- `full` target 20.74% / -34.36% / Sharpe 0.94; LB axis `22..23` (left 0, right 1); HL axis `8..10`; surface 95% peak LB `21..27`, HL `6..12`, count 10.
- `last_10y` target 15.47% / -24.42% / Sharpe 0.80; LB axis `22` (left 0, right 0); HL axis `8..10`; surface 95% peak LB `21..22`, HL `8..12`, count 4.
- `last_5y` target 15.64% / -21.19% / Sharpe 0.74; LB axis `19..22` (left 3, right 0); HL axis `6..8`; surface 95% peak LB `20..29`, HL `8..12`, count 4.
- `last_3y` target 22.48% / -21.19% / Sharpe 0.95; LB axis `19..22` (left 3, right 0); HL axis `6..8`; surface 95% peak LB `20..30`, HL `8..12`, count 7.
- `last_1y` target 46.51% / -19.31% / Sharpe 2.13; LB axis `22` (left 0, right 0); HL axis `8`; surface 95% peak LB `7..7`, HL `10..12`, count 2.

## recent_fast_ridge `v25_lb38_hl10_th0p0_cost_only`

- `full` target 18.08% / -50.76% / Sharpe 0.76; LB axis `37..38` (left 1, right 0); HL axis `5..10`; surface 95% peak LB `22..27`, HL `10..12`, count 5.
- `last_10y` target 14.10% / -32.18% / Sharpe 0.66; LB axis `37..39` (left 1, right 1); HL axis `8..10`; surface 95% peak LB `25..27`, HL `10..12`, count 4.
- `last_5y` target 21.22% / -20.25% / Sharpe 0.93; LB axis `38..39` (left 0, right 1); HL axis `10`; surface 95% peak LB `38..40`, HL `8..10`, count 3.
- `last_3y` target 29.68% / -20.25% / Sharpe 1.17; LB axis `38..40` (left 0, right 2); HL axis `10`; surface 95% peak LB `38..40`, HL `8..10`, count 4.
- `last_1y` target 93.69% / -10.00% / Sharpe 3.74; LB axis `37..39` (left 1, right 1); HL axis `10`; surface 95% peak LB `35..39`, HL `10..12`, count 4.

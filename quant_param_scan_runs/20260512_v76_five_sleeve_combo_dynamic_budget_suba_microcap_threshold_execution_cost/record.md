# V7.6 Sub-A + Microcap Dynamic Budget Validation

## Research Question

Validate whether Sub-A dynamic budget should advance beyond first-pass advisory evidence, and whether combining it with the existing Microcap advisory improves the five-sleeve portfolio after allocation-turnover costs.

## Data Snapshot

- Return source: `quant_param_scan_runs/20260512_v76_five_sleeve_real_subd_v16_rebalance_validation/aligned_five_sleeve_real_subd_returns.csv`
- Manifest: `portfolio_manifests/v76_current.json`
- Common start: `2011-12-09`
- Common end: `2026-05-08`
- Rows: `3743`
- Sleeve returns are already net/costed at their own sleeve level where applicable.
- Missing-market-session returns are treated as 0 inside the aligned five-sleeve return file.

## Cost And Execution Assumptions

- Dynamic signal uses only prior sleeve NAV drawdown through `t-1`.
- Allocation execution variants: daily, weekly last available trading date, and confirmed calendar month-end.
- Allocation cost: `daily_cost = sum(abs(delta weights)) * cost_bps / 10000`.
- Tested allocation cost levels: `0, 5, 10, 20 bps`.
- Sub-B absorbs all Sub-A and Microcap dynamic-budget deltas.
- No production source default or executable weight was changed.

## Candidate Grid

- Baseline: fixed `10/15/15/20/40`.
- Sub-A bands: `dd_3_10`, `dd_5_10`, `dd_5_12`.
- Sub-A executions: daily, weekly, month_end.
- Microcap advisory anchor: `dd_3_10_month_end`.
- Combo candidates: Sub-A dynamic candidate plus Microcap `dd_3_10_month_end`.

## Best Candidates

- Best full-sample Sharpe delta: `combo_suba_dd_5_10_weekly_microcap_dd_3_10_month_end_cost0bps` = `+0.1543`.
- Best latest-1Y Sharpe delta: `combo_suba_dd_3_10_month_end_microcap_dd_3_10_month_end_cost0bps` = `+0.4081`.

## Output Files

- `scan_summary.csv`
- `window_metrics.csv`
- `weight_diagnostics.csv`
- `scan_meta.json`
- `command_log.txt`

## Decision

Pending finalization after strict artifact check.

## User-Facing Summary

This run is a research-only validation of Sub-A dynamic budget and Sub-A+Microcap stacked advisory candidates. Use the CSVs for exact ranking.
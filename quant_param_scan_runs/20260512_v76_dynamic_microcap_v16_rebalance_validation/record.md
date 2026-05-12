# V7.6 Dynamic Microcap V1.6 Rebalance Validation

## Research Question

Correct the Microcap sleeve source from v1.8 to the current mainline v1.6 and retest DD-tier rebalance frequency and allocation-turnover cost sensitivity.

## Data

- Microcap source: `C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\微盘股对冲策略\outputs\microcap_top100_mom16_targetvol25_max1p5_v1_6_costed_nav.csv`
- Microcap return column: `return_net`
- Non-Microcap sleeve source: `C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\A股美股动量组合策略\outputs\v76_dynamic_microcap_risk_budget_20260512\aligned_sleeve_returns.csv` columns `Sub-A`, `Sub-A-DK`, `Sub-B`
- Common start: `2010-11-22`
- Common end: `2026-05-08`
- Source-change rule: `research_only_no_source_change`
- Signal timing: Microcap weight target for date `t` uses Microcap NAV information through `t-1`.

## Cost And Execution Assumptions

- Inter-sleeve allocation turnover cost: `daily_cost = sum(abs(delta weights)) * cost_bps / 10000`.
- Tested cost levels: `0, 5, 10, 20 bps`.
- Intra-sleeve costs are inherited from the v1.6 `return_net` and the existing sleeve return sources.

## Candidates

- Baseline: `fixed_10_15_15_60_cost0`
- Bands: `dd_5_10`, `dd_5_12`, `dd_3_10`
- Executions: daily, weekly, month_end

## Best Cost-0 Candidate By Latest 1Y Sharpe

- Candidate: `dd_3_10_daily_cost0bps`
- 1Y annual return: `0.4725`
- 1Y max drawdown: `-0.0822`
- 1Y Sharpe: `3.8856`
- 1Y Sharpe delta vs baseline: `0.2334`

## Stability Classification

- Stability label: `v1_6_corrected_watchlist`
- Evidence: corrected to current Microcap v1.6 costed return source.
- Caveat: this remains research-only and does not change production `COMBINED_WEIGHTS`.

## Output Files

- `scan_summary.csv`
- `window_metrics.csv`
- `weight_diagnostics.csv`
- `scan_meta.json`
- `command_log.txt`

## Decision

Decision: `corrected_to_v1_6_watchlist_not_source_default`.

## Finalization

- Finalized at: 2026-05-12T10:34:47+08:00
- Decision: corrected_to_v1_6_watchlist_not_source_default
- Stability label: v1_6_corrected_watchlist
- Complete checker: PASS

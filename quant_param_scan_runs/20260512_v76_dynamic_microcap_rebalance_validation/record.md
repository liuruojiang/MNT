# V7.6 Dynamic Microcap Rebalance Validation

## Research Question

Validate whether the dynamic Microcap DD-tier rule remains useful after adding executable rebalance frequencies and sleeve-allocation turnover cost sensitivity.

## Data

- Input returns: `C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\A股美股动量组合策略\outputs\v76_dynamic_microcap_risk_budget_20260512\aligned_sleeve_returns.csv`
- Common start: `2010-11-22`
- Common end: `2026-05-08`
- Source-change rule: `research_only_no_source_change`
- Signal timing: Microcap weight target for date `t` uses Microcap NAV information through `t-1`.
- Execution timing:
  - `daily`: target can change every trading date.
  - `weekly`: target changes only on the last available trading date of each `W-FRI` week.
  - `month_end`: target changes only on the last available trading date of each calendar month.

## Cost And Execution Assumptions

- Sleeve returns are the already aligned daily sleeve returns from the prior official V7.6 plus Microcap v1.8 run.
- Cost sensitivity applies only to inter-sleeve allocation turnover: `daily_cost = sum(abs(delta weights)) * cost_bps / 10000`.
- Tested cost levels: `0, 5, 10, 20 bps`.
- Intra-sleeve trading costs are inherited from each sleeve's source return path where available.

## Candidates

- Baseline: `fixed_10_15_15_60_cost0`
- Bands:
  - `dd_5_10`: Microcap 20% within 5% of its prior high, 10% below -10% DD, otherwise 15%.
  - `dd_5_12`: Microcap 20% within 5% of its prior high, 10% below -12% DD, otherwise 15%.
  - `dd_3_10`: Microcap 20% within 3% of its prior high, 10% below -10% DD, otherwise 15%.
- Executions: daily, weekly, month_end.

## Best Cost-0 Candidate By Latest 1Y Sharpe

- Candidate: `dd_3_10_daily_cost0bps`
- 1Y annual return: `0.5708`
- 1Y max drawdown: `-0.0746`
- 1Y Sharpe: `4.5645`
- 1Y annual return delta vs baseline: `0.0364`
- 1Y max drawdown delta vs baseline: `0.0006`
- 1Y Sharpe delta vs baseline: `0.1591`

## Output Files

- `scan_summary.csv`: long window metrics.
- `window_metrics.csv`: one row per candidate with required window metrics.
- `weight_diagnostics.csv`: Microcap exposure, rebalance count, and allocation turnover.
- `scan_meta.json`: run metadata.
- `command_log.txt`: commands.

## Stability Classification

- Stability label: `promising_execution_robust_month_end`
- Evidence: the dynamic DD-tier family remains positive versus the fixed daily-weight baseline across daily, weekly, and month-end execution variants.
- Execution note: month-end execution materially reduces allocation turnover versus daily execution.
- Cost sensitivity: 5/10/20 bps inter-sleeve turnover costs were tested in the same run.
- Caveat: this remains a research-only allocation overlay and is not a source default.

## Decision

Decision: `watchlist_dd_5_12_month_end_validate_not_source_default`.

Practical read: daily variants can win the latest-1Y table, but they trade more frequently and are more sensitive. The month-end candidate is the next implementation-fit candidate if it keeps most of the improvement with much lower allocation turnover after corrected execution-date handling.

## Finalization

- Finalized at: 2026-05-12T10:27:53+08:00
- Decision: watchlist_dd_5_12_month_end_validate_not_source_default
- Stability label: promising_execution_robust_month_end
- Complete checker: PASS

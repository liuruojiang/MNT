# V7.6 Five-Sleeve Microcap V1.6 Rebalance Validation

## Research Question

Retest the Microcap dynamic risk-budget rule on the current five-sleeve allocation:

`Sub-A / Sub-A-DK / Microcap / Sub-D / Sub-B = 10 / 15 / 15 / 20 / 40`.

`Sub-D` is mapped to the official V7.6 legacy `Sub-C` daily return engine for this run.

## Data

- Official source: `C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\A股美股动量组合策略\mnt_bot V 7.6 plus.py`
- Microcap source: `C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\微盘股对冲策略\outputs\microcap_top100_mom16_targetvol25_max1p5_v1_6_costed_nav.csv`
- Microcap return column: `return_net`
- Sub-D source: `official V7.6 legacy Sub-C daily return mapped to Sub-D`
- Common start: `2010-11-22`
- Common end: `2026-05-08`
- Aligned daily rows: `4017`
- Source-change rule: `research_only_no_production_weight_change`
- Signal timing: Microcap weight target for date `t` uses Microcap NAV information through `t-1`.

## Cost And Execution Assumptions

- Inter-sleeve allocation turnover cost: `daily_cost = sum(abs(delta weights)) * cost_bps / 10000`.
- Tested cost levels: `0, 5, 10, 20 bps`.
- Dynamic Microcap changes are funded only by Sub-B.
- Sub-A, Sub-A-DK, Sub-D, and Microcap intra-sleeve costs are inherited from their official return sources.

## Baseline

- Candidate: `fixed_10_15_15_20_40_cost0`
- Full annual return: `0.2438`
- Full max drawdown: `-0.0796`
- Full Sharpe: `2.8206`
- Latest 1Y annual return: `0.4781`
- Latest 1Y max drawdown: `-0.0796`
- Latest 1Y Sharpe: `4.3724`

## Best Cost-0 Candidate By Latest 1Y Sharpe

- Candidate: `dd_3_10_daily_cost0bps`
- 1Y annual return: `0.5097`
- 1Y max drawdown: `-0.0785`
- 1Y Sharpe: `4.6500`
- 1Y Sharpe delta vs baseline: `0.2776`

## Practical Month-End Candidate

- Candidate: `dd_3_10_month_end_cost0bps`
- Full annual return: `0.2516`
- Full max drawdown: `-0.0796`
- Full Sharpe: `2.9243`
- Latest 1Y annual return: `0.4972`
- Latest 1Y max drawdown: `-0.0796`
- Latest 1Y Sharpe: `4.4954`

## Decision

Decision: `five_sleeve_corrected_validation_completed`.

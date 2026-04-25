# Sub-B Grouped Lookback Scan

- Data source: production `fetch_yahoo()` path from `mnt_bot V 7.1 plus.py`
- Ranking pool: `QQQ, EMXC, EFA, GLD, TLT, DBC`
- BTC excluded from backtest
- Execution: weekly signal day, `T` close signal -> `T+1` open execution
- Weighting: same production `Top3 + inverse-vol + target-vol + VolReg` path
- Costs: `US_ROT_COMMISSION = 0.001`
- This study only changed lookback assignment by asset group. No production logic was modified.
- Ranking should use `group_scan_rankfixed.csv` and `rolling_top_compare_rankfixed.csv`. The earlier raw ranking file used an inverted sort direction and should not be used for candidate ranking.

## Purpose

Test whether Sub-B should move from the current shared mixed lookback (`130/260/390`) to grouped lookbacks with different signal half-lives by asset role.

## Schemes Tested

- 2-group:
  - `equity_vs_macro`: `QQQ/EMXC/EFA` vs `GLD/TLT/DBC`
  - `risk_vs_defense`: `QQQ/EMXC/EFA/DBC` vs `GLD/TLT`
  - `qqq_gold_vs_rest`: `QQQ/GLD` vs `EMXC/EFA/TLT/DBC`
  - `qqq_vs_rest`: `QQQ` vs all others
- 3-group:
  - `qqq_exus_macro`: `QQQ` / `EMXC+EFA` / `GLD+TLT+DBC`
  - `equity_rates_commodity`: `QQQ+EMXC+EFA` / `GLD+TLT` / `DBC`

## Current Baseline

- Current production-style benchmark for comparison: mixed lookback `130/260/390`
- Baseline metrics:
  - last 5Y: CAGR `32.90%`, MaxDD `-9.29%`
  - last 10Y: CAGR `28.30%`, MaxDD `-16.97%`
  - full common (`2009-02-27` to `2026-04-24`): CAGR `20.59%`, MaxDD `-16.97%`

## Best Candidates Observed

### Best 2-group candidate

- Scheme: `equity_vs_macro`
- Lookbacks: `260 + 100`
  - `QQQ/EMXC/EFA = 260`
  - `GLD/TLT/DBC = 100`
- Metrics:
  - last 5Y: CAGR `31.97%`, MaxDD `-10.54%`
  - last 10Y: CAGR `29.80%`, MaxDD `-11.46%`
  - full common: CAGR `20.00%`, MaxDD `-15.92%`
- Interpretation:
  - Better drawdown profile than baseline on 10Y and full sample
  - Return improvement is modest and not uniform across windows

### Best 3-group candidate

- Scheme: `equity_rates_commodity`
- Lookbacks: `260 + 100 + 160`
  - `QQQ/EMXC/EFA = 260`
  - `GLD/TLT = 100`
  - `DBC = 160`
- Metrics:
  - last 5Y: CAGR `35.52%`, MaxDD `-10.38%`
  - last 10Y: CAGR `32.30%`, MaxDD `-14.25%`
  - full common: CAGR `20.63%`, MaxDD `-15.92%`
- Interpretation:
  - This is the strongest candidate in the tested grid
  - Improvement over baseline exists, but the gain is not large enough to justify immediate production adoption given the added complexity

## Negative Findings

- `QQQ + GLD` grouped together was not the best structure.
- `QQQ` as a standalone group was also not necessary to reach the top of the tested set.
- The strongest patterns were closer to:
  - equities need longer lookbacks
  - `GLD/TLT` need shorter lookbacks
  - `DBC` may deserve its own intermediate lookback

## Rolling Comparison

- Baseline `130/260/390`
  - 3Y rolling median CAGR: `17.97%`
  - 5Y rolling median CAGR: `14.59%`
  - worst rolling MaxDD: `-16.97%`
- Best 2-group `260/100`
  - 3Y rolling median CAGR: `20.52%`
  - 5Y rolling median CAGR: `16.79%`
  - worst rolling MaxDD: `-15.92%`
- Best 3-group `260/100/160`
  - 3Y rolling median CAGR: `22.42%`
  - 5Y rolling median CAGR: `17.91%`
  - worst rolling MaxDD: `-21.50%`

## Decision

Current decision: **record only, do not promote to formal Sub-B parameters yet**.

Reason:

1. The observed improvement is real but not overwhelming.
2. Moving from one shared mix to two or three grouped lookbacks increases parameter count and structural complexity.
3. The more complex grouped variants are more exposed to overfitting risk.
4. At this stage the baseline `130/260/390` remains simpler, easier to explain, and still competitive.

## If Revisited Later

If this topic is revisited, the next validation step should be:

1. compare yearly return decomposition
2. compare turnover and holding composition
3. test out-of-sample stability on rolling windows without expanding group freedom further

Only if grouped variants continue to dominate under those checks should they be considered for production rollout.

## Files

- Main scan: `group_scan.csv`
- Corrected ranking view: `group_scan_rankfixed.csv`
- Baseline comparison: `group_scan_with_baselines.csv`
- Per-scheme top rows: `scheme_top5.csv`
- Global top rows: `global_top20.csv`
- Rolling comparison of top candidates: `rolling_top_compare_rankfixed.csv`

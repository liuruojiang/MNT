# Quant Parameter Scan Record

## Run Metadata

- Run id: `20260910_momentum_v80_subb_correlation_allocation`
- Created at: 2026-09-10T11:04:50+08:00
- Project: momentum
- Strategy or version: v80
- Sleeve or subsystem: subb
- Parameter group: `correlation_allocation`
- Scan type:
- Repo or workspace path: `D:\动量策略\A股美股动量组合策略`
- Target entrypoint: `mnt_bot V 8.0 plus.py`
- Git branch: `main`
- Git commit: `a7353eebc17c94e0d3566404d72fb395776fc54f`
- Working tree status before:

```text
?? research_v80_subb_rebalance_period.py
```

## Research Question

- Baseline:
- Candidate grid:
- Decision target:
- Source-change rule: `research_only_no_source_change`
- Required windows: full, 10Y, 5Y, 3Y, 1Y
- Required metrics: annual return, annualized volatility, Sharpe, max drawdown, and strategy-specific exposure/cost metrics
- Promotion threshold:
- Rerun triggers:

## Implementation Anchor

- Official entrypoint:
- Function or command path:
- Existing loaders reused:
- Existing metrics reused:
- Default values and source locations:

| parameter | default | source location |
| --- | ---: | --- |
| `correlation_allocation` |  |  |

## Data Snapshot

- Run timestamp:
- Raw data start:
- Raw data end:
- Metrics start after warmup:
- Metrics end:
- Latest trading date or snapshot:
- Data sources:
- Local cache paths:
- Cache write risk:
- Missing or stale data:
- Alignment rules:
- Adjustment mode:
- Trading calendar:
- Timezone assumptions:

## Cost and Execution Assumptions

- Commission:
- Slippage:
- Open-impact:
- Financing:
- Borrow or shorting cost:
- Rebalance timing:
- Fill timing:
- Leverage or sizing rules:
- Hedge assumptions:

## Runtime Override Plan

- Override mechanism:
- Values restored after each candidate:
- Default candidate included in same run:
- Parity check against official/default output:
- If parity check failed, explanation:

## Commands

```powershell
# Add scan commands here as they are run.
```

## Output Files

- `scan_summary.csv`:
- `window_metrics.csv`:
- `scan_meta.json`: this run metadata
- `command_log.txt`: initialization command and future scan commands

## Full-Sample Results

To be filled after the scan writes `scan_summary.csv`.

## Window Results

To be filled after the scan writes `window_metrics.csv`.

## Stability Classification

- Label:
- Evidence:
- Nearby-candidate behavior:
- Recent-window behavior:
- Cost sensitivity:
- Data sensitivity:
- Leverage or exposure caveat:

## Decision

- Decision:
- Recommended next action:

## Predeclared allocation experiment
Baseline: current V8.0 inverse-vol sizing, exact production raw selection and downstream account engine.
Primary: constrained minimum variance using existing 20-day asset volatilities and 63-session correlations shrunk 50% to identity. Bounds 0.5-1.5 times baseline risky-relative allocation; preserve total risky allocation and BIL weight. No forecast return objective.
Controls: diagonal covariance (no correlation), correlation windows 42 and 126. All settings fixed before results. No optimization of parameters based on results.
Preserve Top-N, absolute gates, replacement buffer, all four signal families, weekly schedule, BTC cap, target-vol rules, VolReg, next adjusted open execution, net trading costs, financing. Endogenous scale values may change because return histories change.
Use accepted frozen September 4 production inputs, baseline parity <=1e-12 to full-entrypoint saved result. Long history is phased/proxy research, not all-live ETF performance. Selection, cash and schedule invariants required. Production file and unrelated untracked cadence experiment untouched.
Decision: research only. Assess Full/10Y/5Y/3Y/1Y return and drawdown, turnover, and incremental effect versus diagonal control. Do not promote automatically or claim out-of-sample evidence.

## Completed results and decision
Execution completed on 2026-09-10 using frozen 2008-12-15 through 2026-09-04 Sub-B returns (4,458 sessions); phased/proxy historical research only. Each B account begins with 50% capital then drifts. Trailing windows preserve the original full-path holdings/state.
Baseline parity to accepted full-entrypoint artifact: B78 max absolute daily delta 8.88e-16; B79 3.33e-16. Every case made 11,248 calls with unchanged selected sets, raw BIL weight and model signal dates; bounds and risky budget verified. 126-day correlation had 26 insufficient-history fallbacks to baseline, explicitly counted. Production source SHA unchanged.
Primary corr63 combined CAGR/maxDD: Full 14.9451%/-14.3802%; 10Y 21.2215%/-13.9038%; 5Y 27.1056%/-13.9038%; 3Y 37.7806%/-12.3645%; 1Y 36.7088%/-12.3645%.
Baseline: Full 15.3756%/-14.0387%; 10Y 22.4129%/-14.0387%; 5Y 28.5065%/-14.0387%; 3Y 40.7209%/-12.9206%; 1Y 37.2103%/-12.9206%.
All 42/63/126 correlation candidates lower Full CAGR and worsen Full drawdown. This is not a supported replacement. 10Y/5Y primary CAGR losses exceed the default 1pp tolerance. Mainline remains inverse volatility.
Correlation itself adds modest value relative to the diagonal-minimum-variance control (+0.14pp Full CAGR), but the entire change remains below baseline and Full drawdown worsens. Full daily vol declines 13.55% to 13.15%; mean risky exposures do not decline, so this is not simply less invested capital. Average annual execution-cost sums increase B78 1.239% to 1.587%, B79 1.072% to 1.282%; this is an additive cost diagnostic, not an exact CAGR attribution. Raw allocations conditionally favor lower-risk assets; detailed asset shifts saved separately. No claim that all covariance-aware methods fail.
B78 primary recent 3Y/1Y drawdowns improve, but Full drawdown worsens and returns fall; watch only. B79 does not show comparable recent drawdown gains. No after-the-fact hybrid promoted or tested as a new primary.
No latest-data refresh, no out-of-sample claim, no production edits, no cloud sync. Full/10Y history is not all-live-ETF formal history. Formal all-live ETF validation is not established in this experiment; these research results do not authorize promotion.
Artifacts: all_sleeve_metrics.csv, scan_summary.csv, window_metrics.csv, daily_returns.csv, *_accounts.pkl, allocation_audit.csv, allocation_changes.csv, asset_allocation_deltas.csv, turnover.csv, exposure.csv, correlation_increment_over_diagonal.csv, parity.json, verification.json, nav_comparison.png. Chart visually checked.
Decision: retain_inverse_vol_no_promotion. Stability: three tested correlation windows consistently fail replacement criteria; limited neighboring-window check, not an exhaustive parameter grid or 80-percent width certification.

## Finalization

- Finalized at: 2026-09-10T11:14:46+08:00
- Decision: retain_inverse_vol_no_promotion
- Stability label: tested_windows_consistently_fail_replacement
- Complete checker: PASS

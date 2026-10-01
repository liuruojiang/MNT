# Quant Parameter Scan Record

## Run Metadata

- Run id: `20260910_momentum_v80_subc_joint_risk`
- Created at: 2026-09-10T11:47:41+08:00
- Project: momentum
- Strategy or version: v80
- Sleeve or subsystem: subc
- Parameter group: `joint_risk`
- Scan type:
- Repo or workspace path: ``
- Target entrypoint: ``
- Git branch: ``
- Git commit: ``
- Working tree status before:

```text

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
| `joint_risk` |  |  |

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

## Preregistered scope
Joint replacement, not overlay: assess risk of all ten C assets, adjust only equity+gold using common scale, keep bonds/CTA/BTC at 1x. Keep base allocations, annual MOC rebalance, independent contribution ledger, BIL cash, BIL+100bps debt, 6bps scale transaction costs, lag1, 0.5-1.5 scale bounds, 0.35 deadband.
Covariance window63 sessions, 50% shrink to diagonal. Primary total C annual risk target10%; 8% and12% target controls; diagonal covariance10% isolates correlation effect. Targets fixed before seeing output, no paper7% copied. Select highest scale within bounds satisfying forecast risk, or minimum-risk feasible-bound scale if target unreachable; log violations, never call nominal risk target a guaranteed cap. Cash treated as zero-risk in risk estimate; actual BIL and financing retained in P&L.
Same frozen input as preceding Sub-B study through2026-09-04. Confirm C baseline against accepted full-entrypoint daily output; use common sample after all required63-day histories mature. All-live ETF formal history not claimed. No production changes or full V8 refresh.
Compare Full/10Y/5Y/3Y/1Y, with unavailable windows explicit. Preserve same base component ledger and use existing production open-transition routine. Research-only; no promotion or next-layer scan without user instruction.

## Completed comparison
Common sample after all ten assets'63-session covariance warmup: 2021-03-08 through2026-09-04, 1,382 sessions. 10Y explicitly N/A for every candidate. Input retains production proxy/live splices; no all-live ETF history claim. Baseline daily-return parity to accepted full-path output is exactly0.
Primary joint10% versus current: Full CAGR13.8653% vs14.5865%, MaxDD23.1011% vs20.5662%; 5Y13.5142%/23.1011% vs13.6618%/20.5662%; 3Y23.6004%/14.4444% vs24.2652%/9.7728%; 1Y24.2571%/8.1939% vs24.0750%/8.1406%. Returns/costs computed using unchanged production contribution and next-open transition routines.
All variants' Full peak/trough are2021-11-08/2022-09-27. Joint8% reduces Full DD by1.37pp but loses3.71pp annual return and also worsens3Y DD. Joint12% adds0.15pp Full CAGR with4.91pp deeper DD. No candidate supports replacing current sleeves under project tolerances.
Ignoring correlation at target10% over-allocates: Full realized vol16.65%, DD28.24%, mean scale1.36. Joint covariance10% realized vol13.66%, versus current12.92%; target is ex-ante, not realized-risk guarantee. Correlation improves risk assessment relative to diagonal, but does not beat the established independent controls.
Current equity/gold scale changes48/18 during common sample; joint10%9 changes. Joint10% has24 signal days where target cannot be achieved under bounds and888 days forecast above target after applying original0.35 deadband. These constraints are deliberately preserved, not relaxed after seeing outcomes. They limit the interpretation of this common-scale implementation; no general claim that joint control can never work.
Annual scale-execution-cost sums: current14.30bps, joint10%3.10bps. Joint underperformance is not explained by higher scale trading costs. Annual base turnover costs and BIL/financing preserved.
Decision retain_current_sleeve_scaling_no_promotion. Fixed target-neighbor check only; no window/deadband search, no production change, no full V8 portfolio claim. If later authorized, independently varying joint deadband/control design would be a new layer, not automatic continuation.
Artifacts: scan_summary.csv,window_metrics.csv,daily_returns.csv,scales.csv,risk_forecasts.csv,risk_diagnostics.csv,scale_execution_costs.csv,cost_summary.csv,base_components.pkl,verification.json,nav_comparison.png. Chart visually inspected; source compilation and diff checks passed.

## Finalization

- Finalized at: 2026-09-10T11:51:45+08:00
- Decision: retain_current_sleeve_scaling_no_promotion
- Stability label: tested_targets_fail_replacement
- Complete checker: PASS

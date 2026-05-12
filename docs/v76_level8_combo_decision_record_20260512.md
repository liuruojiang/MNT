# V7.6 Level-8 Combo Decision Record - 2026-05-12

## Purpose

This record moves the V7.6 work from single-parameter tuning to portfolio-level decision making.

The goal is not to keep finding a better decimal value for one sleeve. The goal is to decide which changes improve the executable combined portfolio, and to stop work that is only locally interesting.

## Microcap Source Correction

Correction after review: the current mainline Microcap version is `v1.6`, not `v1.8`.

The earlier four-sleeve and advisory checks that used `microcap_top100_mom11_targetvol30_max2_v1_8_costed_nav.csv` should be treated as superseded for production decision making. They remain useful only as a stale-source diagnostic.

Current corrected source:

- Version: Microcap `v1.6`
- File: `../微盘股对冲策略/outputs/microcap_top100_mom16_targetvol25_max1p5_v1_6_costed_nav.csv`
- Return column: `return_net`
- V7.6 source loader corrected from v1.8 to v1.6 in `mnt_bot V 7.6 plus.py`.

## Current Combo Shape

Source: `mnt_bot V 7.6 plus.py`.

Important correction after user review: the current portfolio design is five-sleeve, not the older four-sleeve source snapshot.

Current intended allocation:

| Sleeve | Intended weight |
|---|---:|
| Sub-A | 10% |
| Sub-A-DK | 15% |
| Microcap v1.6 | 15% |
| Sub-D v1.1 six-ETF | 20% |
| Sub-B | 40% |

V7.6 source default/display shape has now been synced to the intended five-sleeve allocation:

| Sleeve | V7.6 synced weight |
|---|---:|
| Sub-A | 10% |
| Sub-A-DK | 15% |
| Microcap v1.6 | 15% |
| Sub-D v1.1 six-ETF | 20% |
| Sub-B | 40% |

Therefore the four-sleeve combo checks below are superseded for production allocation decisions. They remain useful only as diagnostics for how the old source snapshot behaved.

Current performance-query order excludes Microcap and Sub-D because both are still handled by independent scripts:

| Performance sleeve | Normalized no-microcap weight |
|---|---:|
| Sub-A | 15.38% |
| Sub-A-DK | 23.08% |
| Sub-B | 61.54% |

This means the built-in PV/performance query is useful for the bot-local three-sleeve view, but it is not the final five-sleeve portfolio objective.

## Portfolio Manifest Boundary

Manifest: `portfolio_manifests/v76_current.json`.

Architecture decision:

- V7.6 main bot keeps only Sub-A, Sub-A-DK, and Sub-B strategy logic.
- Microcap remains an independent v1.6 script/output source.
- Sub-D remains an independent v1.1 six-ETF script/output source.
- Five-sleeve merged NAV, combined performance, or economic curves should be built by a separate portfolio-level script that reads the manifest and standardized sleeve outputs.
- Do not copy Microcap or Sub-D strategy internals into `mnt_bot V 7.6 plus.py`.

This keeps the V7.6 bot as the signal and configuration surface, not a monolithic container for every sleeve.

## Portfolio NAV Builder

Script: `build_v76_portfolio_nav.py`.

Default inputs:

- Manifest: `portfolio_manifests/v76_current.json`
- Aligned sleeve returns: `quant_param_scan_runs/20260512_v76_five_sleeve_real_subd_v16_rebalance_validation/aligned_five_sleeve_real_subd_returns.csv`

Default outputs:

- `outputs/portfolio_v76_current/aligned_sleeve_returns.csv`
- `outputs/portfolio_v76_current/portfolio_nav.csv`
- `outputs/portfolio_v76_current/window_metrics.csv`
- `outputs/portfolio_v76_current/scenario_nav.csv`
- `outputs/portfolio_v76_current/scenario_window_metrics.csv`
- `outputs/portfolio_v76_current/scenario_economic_curve.csv`
- `outputs/portfolio_v76_current/scenario_decision_summary.md`
- `outputs/portfolio_v76_current/scenario_visual_report.html`
- `outputs/portfolio_v76_current/dynamic_sleeve_budget_scan.csv`
- `outputs/portfolio_v76_current/dynamic_sleeve_budget_summary.md`
- `outputs/portfolio_v76_current/weights_advisory_dd_3_10_month_end.csv`
- `outputs/portfolio_v76_current/weights_advisory_suba_microcap_dd_3_10_month_end.csv`
- `outputs/portfolio_v76_current/meta.json`

Current five-sleeve baseline from the builder:

| Window | Annual return | MaxDD | Sharpe |
|---|---:|---:|---:|
| Full | 30.38% | -7.87% | 3.27 |
| 10Y | 33.82% | -6.78% | 3.52 |
| 5Y | 38.24% | -6.78% | 3.86 |
| 3Y | 51.42% | -6.78% | 4.80 |
| 1Y | 59.01% | -5.71% | 5.21 |

This is now the lightweight default entrypoint for five-sleeve portfolio-level NAV and drawdown checks. It reads already-standardized return outputs and does not embed Microcap or Sub-D strategy internals into V7.6.

## A/ADK/B/Sub-D Dynamic-Budget Decision Refresh

Refresh command:

```powershell
python build_v76_level8_decision_dashboard.py
```

Source evidence:

- Portfolio scenario metrics: `outputs/portfolio_v76_current/scenario_window_metrics.csv`
- Portfolio economic curve: `outputs/portfolio_v76_current/scenario_economic_curve.csv`
- A/ADK/B/Sub-D scan: `quant_param_scan_runs/20260512_v76_level8_v7_6_five_sleeve_a_adk_b_subd_dynamic_budget_prior_nav_dd_threshold_execution_step/window_metrics.csv`
- Common aligned return sample: `2011-12-09` to `2026-05-08`

Decision status after adding the A/ADK/B/Sub-D optimized candidates and promoting the approved stacked budget:

| Candidate | Status | Latest weights Sub-A / ADK / Microcap / Sub-D / Sub-B | Full annual / MaxDD / Sharpe | 1Y annual / MaxDD / Sharpe | Read |
|---|---|---:|---:|---:|---|
| Fixed default | BASELINE | 10% / 15% / 15% / 20% / 40% | 30.38% / -7.87% / 3.27 | 59.01% / -5.71% / 5.21 | Executable benchmark. |
| Stacked Sub-A + Microcap advisory | ACTIVE_DEFAULT | 15% / 15% / 10% / 20% / 40% | 32.56% / -7.16% / 3.44 | 63.36% / -5.33% / 5.61 | Active portfolio-level dynamic budget; fixed weights remain benchmark and rollback. |
| Sub-A 5/8 weekly advisory | REPORT_WATCH_ONLY | 15% / 15% / 15% / 20% / 35% | 31.67% / -7.10% / 3.36 | 61.26% / -5.24% / 5.46 | Former active component; retained as comparison/fallback reference. |
| Microcap advisory | REPORT_WATCH_ONLY | 10% / 15% / 10% / 20% / 45% | 31.26% / -7.92% / 3.36 | 61.07% / -5.73% / 5.35 | Positive return evidence, but max drawdown worsens slightly. |
| ADK own-DD advisory | REPORT_WATCH_ONLY | 10% / 10% / 15% / 20% / 45% | 30.78% / -9.12% / 3.29 | 60.60% / -6.38% / 5.28 | Too much drawdown and turnover for first promotion. |
| Sub-D own-DD advisory | REPORT_WATCH_ONLY | 10% / 15% / 15% / 25% / 35% | 30.59% / -7.99% / 3.23 | 62.52% / -5.33% / 5.47 | Strong recent-window evidence, but full-sample Sharpe is not robust. |
| Sub-B own-DD advisory | DEFER | 10% / 14% / 14% / 19% / 42% | 30.20% / -7.82% / 3.25 | 58.85% / -5.89% / 5.15 | Weak under the proportional-absorber design. |

Conclusion:

- Do not promote ADK, Sub-B, Sub-D, or Microcap-only rules as active defaults in this step.
- Promote `advisory_suba_microcap_dd_3_10_month_end` to the active portfolio-level dynamic budget.
- Keep fixed `10/15/15/20/40` weights as the benchmark and rollback line.
- Keep `Sub-D` on the report watchlist because the optimized version is meaningful in the recent window, but it is not broad-window stable enough to lead the next landing.

### Builder Advisory Scenario

The builder now also emits an advisory scenario beside the fixed baseline:

```text
advisory_dd_3_10_month_end
```

Rule:

- Microcap weight is 20% when prior Microcap NAV drawdown is within 3%.
- Microcap weight is 10% when prior Microcap NAV drawdown is at or below -10%.
- Otherwise Microcap weight stays at 15%.
- Execution is month-end only.
- Sub-B absorbs the Microcap delta.
- Sub-A, Sub-A-DK, and Sub-D stay fixed at 10%, 15%, and 20%.

Implementation status:

- This is a portfolio-layer advisory output, not a production default allocation change.
- V7.6 source does not embed Microcap or Sub-D internals.
- The latest incomplete month is not treated as a confirmed month-end execution point.

Scenario output from `python build_v76_portfolio_nav.py`:

| Scenario | Full | 10Y | 5Y | 3Y | 1Y |
|---|---:|---:|---:|---:|---:|
| Fixed `10/15/15/20/40` | 30.38% / -7.87% / 3.27 | 33.82% / -6.78% / 3.52 | 38.24% / -6.78% / 3.86 | 51.42% / -6.78% / 4.80 | 59.01% / -5.71% / 5.21 |
| Advisory `dd_3_10_month_end` | 31.26% / -7.92% / 3.36 | 34.01% / -7.68% / 3.53 | 38.64% / -7.68% / 3.84 | 52.53% / -7.68% / 4.84 | 61.07% / -5.73% / 5.35 |

Weight diagnostics:

| Scenario | Avg Microcap | Latest Microcap | Latest Sub-B | Rebalance count | Allocation turnover |
|---|---:|---:|---:|---:|---:|
| Fixed `10/15/15/20/40` | 15.00% | 15% | 40% | 0 | 0.0 |
| Advisory `dd_3_10_month_end` | 16.93% | 10% | 45% | 59 | 6.3 |

Economic curve output:

- `scenario_economic_curve.csv` contains fixed/advisory daily returns, NAV, drawdown, advisory excess return, advisory excess NAV, and advisory Microcap/Sub-B weights.
- `scenario_decision_summary.md` is a short human-readable decision memo generated from the same real-data run.
- `scenario_visual_report.html` is a self-contained visual report with NAV, drawdown, excess-NAV, and advisory-weight charts.
- Latest advisory excess NAV versus fixed at `2026-05-08`: `+10.12%`.
- Metadata paths in `meta.json` are repo-relative to avoid Windows console encoding noise from Chinese absolute paths.

Decision:

Keep this as the default portfolio-level advisory scenario. It is now available in the builder outputs for combined NAV and economic-curve work, but it is not yet promoted into executable default weights.

### Dynamic Sleeve Budget Scan

Run output:

- `outputs/portfolio_v76_current/dynamic_sleeve_budget_scan.csv`
- `outputs/portfolio_v76_current/dynamic_sleeve_budget_summary.md`

Purpose:

Check whether the same simple dynamic-budget rule should be considered for other sleeves, instead of assuming Microcap is the only possible feedback source.

Rule:

- Each candidate changes only one sleeve.
- Sub-B absorbs the weight delta.
- Month-end execution only.
- +5 pp when prior sleeve NAV drawdown is within 3%.
- -5 pp when prior sleeve NAV drawdown is at or below -10%.
- Otherwise use the base manifest weight.

Candidate comparison versus fixed `10/15/15/20/40`:

| Candidate | Sleeve | Full annual delta | Full MaxDD delta | Full Sharpe delta | 1Y annual delta | 1Y Sharpe delta | Latest sleeve | Latest Sub-B | Switches | Turnover |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `advisory_suba_dd_3_10_month_end` | Sub-A | +0.55 pp | +0.39 pp | +0.01 | +2.34 pp | +0.25 | 15% | 35% | 47 | 5.3 |
| `advisory_subadk_dd_3_10_month_end` | Sub-A-DK | +0.00 pp | -0.84 pp | -0.02 | +0.53 pp | +0.01 | 10% | 45% | 74 | 7.9 |
| `advisory_microcap_dd_3_10_month_end` | Microcap | +0.88 pp | -0.05 pp | +0.09 | +2.06 pp | +0.14 | 10% | 45% | 59 | 6.3 |
| `advisory_subd_dd_3_10_month_end` | Sub-D | -0.25 pp | -0.08 pp | -0.04 | +2.25 pp | +0.16 | 25% | 35% | 81 | 8.9 |

Read:

- Microcap remains a valid advisory candidate. It has the best full-sample annual and Sharpe improvement, but slightly worsens full-sample MaxDD.
- Sub-A is now the strongest second candidate. It improves full-sample annual return, full-sample MaxDD, and recent 1Y behavior at the same time.
- Sub-A-DK is not attractive under this simple rule because full-sample drawdown worsens and Sharpe declines.
- Sub-D is not attractive as a default dynamic-budget candidate because it sacrifices full-sample annual return and Sharpe despite good recent 1Y behavior.
- Sub-B is not tested as an active dynamic sleeve in this pass because it is the absorber. Testing Sub-B actively would require a separate cash or reserve sleeve.

Next decision:

Keep Microcap advisory as the current default combo-layer advisory. Promote Sub-A dynamic budget to the next validation stage before considering any production display or default-weight change.

### Sub-A + Microcap Stacked Dynamic Budget Validation

Run folder: `quant_param_scan_runs/20260512_v76_five_sleeve_combo_dynamic_budget_suba_microcap_threshold_execution_cost/`.

Purpose:

Validate whether Sub-A dynamic budget still works after a stricter scan, and whether it should be stacked with the existing Microcap advisory.

Candidate grid:

- Baseline: fixed `10/15/15/20/40`.
- Sub-A bands: `dd_3_10`, `dd_5_10`, `dd_5_12`.
- Sub-A execution: daily, weekly, month-end.
- Microcap anchor: `dd_3_10_month_end`.
- Cost stress: `0 / 5 / 10 / 20 bps` on allocation turnover.
- Cost formula: `daily_cost = sum(abs(delta weights)) * cost_bps / 10000`.

Key candidates:

| Candidate | Cost | Full annual | Full MaxDD | Full Sharpe | 1Y annual | 1Y MaxDD | 1Y Sharpe | Turnover | Switches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fixed `10/15/15/20/40` | 0 bps | 30.38% | -7.87% | 3.27 | 59.01% | -5.71% | 5.21 | 0.0 | 0 |
| Sub-A only `dd_3_10_month_end` | 0 bps | 30.93% | -7.49% | 3.29 | 61.34% | -5.24% | 5.46 | 5.3 | 47 |
| Sub-A only `dd_3_10_month_end` | 20 bps | 30.83% | -7.53% | 3.28 | 61.31% | -5.24% | 5.46 | 5.3 | 47 |
| Microcap only `dd_3_10_month_end` | 0 bps | 31.26% | -7.92% | 3.36 | 61.07% | -5.73% | 5.35 | 6.3 | 59 |
| Microcap only `dd_3_10_month_end` | 20 bps | 31.14% | -8.02% | 3.35 | 60.94% | -5.75% | 5.34 | 6.3 | 59 |
| Stacked `Sub-A dd_3_10_month_end + Microcap dd_3_10_month_end` | 0 bps | 31.81% | -7.68% | 3.37 | 63.44% | -5.33% | 5.62 | 10.8 | 90 |
| Stacked `Sub-A dd_3_10_month_end + Microcap dd_3_10_month_end` | 20 bps | 31.61% | -7.72% | 3.35 | 63.28% | -5.35% | 5.60 | 10.8 | 90 |
| Stacked `Sub-A dd_5_10_weekly + Microcap dd_3_10_month_end` | 0 bps | 32.47% | -7.38% | 3.43 | 63.36% | -5.33% | 5.61 | 13.0 | 121 |
| Stacked `Sub-A dd_5_10_weekly + Microcap dd_3_10_month_end` | 20 bps | 32.23% | -7.49% | 3.40 | 63.23% | -5.35% | 5.60 | 13.0 | 121 |

Decision:

Promote the stacked month-end candidate to the next advisory-validation stage:

```text
Sub-A dd_3_10_month_end + Microcap dd_3_10_month_end
```

Do not change executable defaults yet.

### Builder Stacked Advisory Output

Implementation:

- `build_v76_portfolio_nav.py` now emits the stacked active scenario beside the fixed baseline, Sub-A-only reference, and Microcap-only advisory.
- Scenario name: `advisory_suba_microcap_dd_3_10_month_end`.
- Rule: Sub-A and Microcap each move by +/-5 pp from their base weights using their own prior NAV drawdown; execution is confirmed month-end only; Sub-B absorbs both deltas.
- This is now the portfolio-layer active dynamic-budget output; fixed 10/15/15/20/40 remains the benchmark and rollback line.

Latest real-data output from `python build_v76_portfolio_nav.py`:

| Scenario | Full annual | Full MaxDD | Full Sharpe | 1Y annual | 1Y MaxDD | 1Y Sharpe | Latest Sub-A | Latest Microcap | Latest Sub-B | Switches | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fixed `10/15/15/20/40` | 30.38% | -7.87% | 3.27 | 59.01% | -5.71% | 5.21 | 10% | 15% | 40% | 0 | 0.0 |
| Microcap advisory `dd_3_10_month_end` | 31.26% | -7.92% | 3.36 | 61.07% | -5.73% | 5.35 | 10% | 10% | 45% | 59 | 6.3 |
| Stacked advisory `Sub-A 5/8 weekly + Microcap 3/10 month-end` | 32.56% | -7.16% | 3.44 | 63.36% | -5.33% | 5.61 | 15% | 10% | 40% | 123 | 13.9 |

Additional outputs:

- `scenario_nav.csv` now includes fixed, Microcap advisory, and stacked advisory NAV/return columns.
- `scenario_window_metrics.csv` now includes fixed, Microcap advisory, and stacked advisory rows for all windows.
- `scenario_economic_curve.csv` now includes stacked advisory NAV, drawdown, excess NAV, Sub-A weight, Microcap weight, and Sub-B weight columns.
- `scenario_visual_report.html` now compares all three scenarios visually.
- `meta.json` records both advisory scenarios and the stacked advisory weight file.

Current decision:

Use stacked Sub-A 5/8 weekly + Microcap 3/10 month-end as the active portfolio-level dynamic budget. Keep Microcap-only and Sub-A-only advisory rows as comparison/fallback lines.

### V7.6 Params Display Integration

Implementation:

- `mnt_bot V 7.6 plus.py` now shows a portfolio-layer advisory panel in both `参数` and `实时参数`.
- The panel reads the existing portfolio report outputs under `outputs/portfolio_v76_current/`.
- It does not recalculate Microcap or Sub-D strategy internals inside the V7.6 bot.
- It does not change `COMBINED_WEIGHTS` or executable default weights.

Current panel snapshot from the real output files:

| Item | Value |
|---|---:|
| Data date | 2026-05-08 |
| Sub-A prior NAV DD | 0.00% |
| Microcap prior NAV DD | -18.68% |
| Fixed default | Sub-A 10% / Microcap 15% / Sub-B 40% |
| Microcap advisory | Sub-A 10% / Microcap 10% / Sub-B 45% |
| Stacked advisory | Sub-A 15% / Microcap 10% / Sub-B 40% |
| Stacked excess NAV vs fixed | +16.96% |

User-facing wording:

- The panel is explicitly labeled `ACTIVE DYNAMIC BUDGET`.
- It states that stacked Sub-A 5/8 weekly + Microcap 3/10 month-end is active.
- It states that fixed 10/15/15/20/40 remains the benchmark and rollback line.

Decision:

This completes the handoff from report-only evidence to daily query visibility. The next gate is not another threshold scan; it is whether this advisory line remains easy to understand after a few live query cycles.

### Advisory Freshness Guard

Implementation:

- `参数` / `实时参数` now compare `outputs/portfolio_v76_current/scenario_economic_curve.csv` against the source aligned return file used by the portfolio builder.
- If the portfolio report date is older than the source return date, the advisory panel is marked unavailable.
- In that stale state, the panel tells the user to run `python build_v76_portfolio_nav.py` and does not print the old stacked advisory weights.

Current source comparison:

| Path | Role |
|---|---|
| `outputs/portfolio_v76_current/scenario_economic_curve.csv` | displayed advisory report |
| `quant_param_scan_runs/20260512_v76_five_sleeve_real_subd_v16_rebalance_validation/aligned_five_sleeve_real_subd_returns.csv` | source aligned sleeve returns |

Decision:

Keep the guard conservative. A stale report should degrade to a refresh instruction, not a possibly misleading allocation suggestion.

## Level-8 Decision Dashboard

Script: `build_v76_level8_decision_dashboard.py`.

Outputs:

- `outputs/portfolio_v76_current/level8_decision_dashboard.md`
- `outputs/portfolio_v76_current/level8_decision_dashboard.csv`
- `outputs/portfolio_v76_current/level8_decision_history.csv`

Purpose:

Turn the V7.6 combo work into a decision surface instead of another parameter table. The dashboard reads the existing portfolio report outputs and answers:

- whether the advisory report is fresh;
- what the current fixed, Microcap advisory, and stacked advisory weights are;
- whether the stacked active line still improves the fixed baseline across full and 1Y windows;
- what action should be taken now.

Current real-data output:

| Scenario | Sub-A | Sub-A-DK | Microcap | Sub-D | Sub-B | Dynamic sleeves | Full annual / MaxDD / Sharpe | 1Y annual / MaxDD / Sharpe | Excess NAV | Switches | Turnover |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|
| Fixed default | 10% | 15% | 15% | 20% | 40% | none | 30.38% / -7.87% / 3.27 | 59.01% / -5.71% / 5.21 | n/a | 0 | 0.0 |
| Stacked Sub-A + Microcap advisory | 15% | 15% | 10% | 20% | 40% | Sub-A,Microcap | 32.56% / -7.16% / 3.44 | 63.36% / -5.33% / 5.61 | 26.93% | 123 | 13.9 |
| Microcap advisory | 10% | 15% | 10% | 20% | 45% | Microcap | 31.26% / -7.92% / 3.36 | 61.07% / -5.73% / 5.35 | 10.12% | 59 | 6.3 |

Dashboard display rule:

- Sub-A-DK and Sub-D must stay visible even when they are fixed-weight sleeves.
- In the current active dynamic-budget line, only Sub-A and Microcap are dynamic; Sub-A-DK and Sub-D remain at 15% and 20%.

Live-cycle tracking:

- `level8_decision_history.csv` records the selected decision row each time the dashboard is refreshed.
- The history file is de-duplicated by `latest_date`, `decision_status`, and `watch_scenario`, so rerunning the same daily snapshot updates the observation timestamp instead of adding duplicate rows.
- This records daily evidence for the active dynamic-budget line while preserving fixed weights as the rollback reference.

Current first history row:

| Latest date | Status | Scenario | Sub-A | Sub-A-DK | Microcap | Sub-D | Sub-B | Dynamic sleeves |
|---|---|---|---:|---:|---:|---:|---:|---|
| 2026-05-08 | ACTIVE_DEFAULT | `advisory_suba_microcap_dd_3_10_month_end` | 15% | 15% | 10% | 20% | 40% | Sub-A,Microcap |

### Poe Single-File Advisory Bot

Script: `poe_v76_level8_advisory_bot.py`.

Purpose:

- Provide a Poe-native single-file display bot for the current Level-8 advisory snapshot.
- Keep this out of `mnt_bot V 7.6 plus.py` so the formal V7.6 signal bot does not keep growing.
- Do not import local research modules and do not read local CSV files in Poe.
- Treat the embedded row as the active portfolio-level dynamic-budget snapshot; fixed weights remain the benchmark and rollback line.

Embedded snapshot:

| Latest data date | Status | Scenario | Sub-A | Sub-A-DK | Microcap | Sub-D | Sub-B | Dynamic sleeves |
|---|---|---|---:|---:|---:|---:|---:|---|
| 2026-05-08 | ACTIVE_DEFAULT | `advisory_suba_microcap_dd_3_10_month_end` | 15% | 15% | 10% | 20% | 40% | Sub-A,Microcap |

Poe boundary:

- `mnt_bot V 7.6 plus.py` remains the formal V7.6 signal bot.
- `poe_v76_level8_advisory_bot.py` is a separate display bot for Level-8 portfolio advisory state.
- Refreshing the embedded snapshot should happen only after rerunning the local portfolio builder/dashboard and verifying the new row.

Decision status:

```text
ACTIVE_DEFAULT
```

Interpretation:

Use stacked Sub-A 5/8 weekly + Microcap 3/10 month-end as the active portfolio-level dynamic budget. Keep fixed default weights as benchmark and rollback.

Reason:

- It improves full-sample return, drawdown, and Sharpe versus fixed.
- It improves latest-1Y return, drawdown, and Sharpe versus fixed.
- It survives 20 bps allocation-turnover stress.
- It keeps both moving sleeves on month-end execution, which is easier to explain than mixing weekly/daily execution.

Keep the Sub-A-only and Microcap-only rows as report-layer comparisons. The active row is the corrected stacked `Sub-A 5/8 weekly + Microcap 3/10 month-end` budget.

Validation:

- `finalize_quant_param_scan_run.py`: PASS.
- `check_quant_param_scan_artifacts.py --phase complete --strict`: PASS.

## Latest Evidence: R2 0.20 vs 0.25

Run output: `outputs/v76_r2_020_vs_025_no_microcap_20260511/summary.csv`.

Path: official V7.6 `_fetch_data(..., include_cn_live_snapshot=False, include_us_live_snapshot=False)` plus `_run_strategies()`, no Microcap, no Sub-C.

Data:

- A-share data through `2026-05-11`
- US data through Beijing time `2026-05-12 04:00`
- Common comparison end: `2026-05-11`

Delta of current `CN_R2_THRESHOLD=0.25` versus old `0.20`:

| Window | Annual return delta | MaxDD delta | Sharpe delta |
|---|---:|---:|---:|
| 10Y | +0.03 pp | +0.60 pp | -0.000 |
| 8Y | +0.43 pp | +0.60 pp | +0.031 |
| 6Y | +0.51 pp | +0.60 pp | +0.053 |
| 4Y | +0.90 pp | +0.60 pp | +0.075 |
| 2Y | +2.18 pp | +0.60 pp | +0.112 |
| 1Y | +2.52 pp | +0.21 pp | +0.109 |

Decision: keep `0.25`. It is directionally positive at the combo-screening level, but it is not a strategic edge by itself. Stop optimizing this parameter for now.

## Existing Candidate Hierarchy

From `docs/v76_candidate_incremental_no_microcap_window_compare_20260506.md`:

| Candidate | Combo-level status |
|---|---|
| `CN_TARGET_VOL=0.25 / CN_VOL_WINDOW=120 / CN_SCALE_THRESHOLD=0.15` | Reject for default; it lowered annual return across tested windows. |
| `CN_ENTRY_WAIT_DAYS=3` | Weak positive; not strong enough alone. |
| `CN_SA_VOLUME_CYB_MA=15 / CN_SA_VOLUME_CYB_DAYS=5` | Promoted and already present in current source. |
| `wait3_plus_volume` | Best historical bundle among tested no-microcap cases, but volume is already landed; remaining open component is only `wait3`. |

Practical read: the next major decision is not another Sub-A micro-tweak. The remaining high-value question is whether the full five-sleeve portfolio allocation and dynamic Microcap risk budget should become the executable default.

## Corrected Five-Sleeve Real Sub-D Validation

Run output: `quant_param_scan_runs/20260512_v76_five_sleeve_real_subd_v16_rebalance_validation/`.

This is the corrected Level-8 run after the portfolio-shape correction:

```text
Sub-A / Sub-A-DK / Microcap / Sub-D / Sub-B = 10 / 15 / 15 / 20 / 40
```

Data and mapping:

- Sub-A, Sub-A-DK, Sub-B: official V7.6 source path.
- Microcap: v1.6 `return_net`.
- Sub-D: real six-ETF `v1.1_staged_50_plus_ma60_overheat`, loaded read-only from git HEAD `run_subd_six_etf_v1_1.py` and `research_subd_six_etf_weighted_slope.py`.
- Common daily window: `2011-12-09` to `2026-05-08`.
- Aligned daily rows: `3743`.
- Missing-market-session returns are held at 0 for closed sleeves inside the aligned daily portfolio.

Metrics are annual return / daily max drawdown / Sharpe.

| Candidate | Full | 10Y | 5Y | 3Y | 1Y |
|---|---:|---:|---:|---:|---:|
| Fixed `10/15/15/20/40` | 30.38% / -7.87% / 3.27 | 36.39% / -7.87% / 3.77 | 39.48% / -7.87% / 3.86 | 53.75% / -7.87% / 4.85 | 59.01% / -5.71% / 5.21 |
| `dd_3_10_daily` | 31.45% / -7.76% / 3.38 | 36.87% / -7.76% / 3.86 | 40.12% / -7.76% / 3.96 | 54.49% / -7.76% / 4.95 | 62.41% / -5.51% / 5.53 |
| `dd_3_10_month_end` | 31.26% / -7.92% / 3.36 | 36.69% / -7.92% / 3.83 | 39.76% / -7.92% / 3.90 | 54.03% / -7.92% / 4.88 | 61.07% / -5.73% / 5.35 |
| `dd_5_12_month_end` | 31.29% / -7.82% / 3.38 | 37.05% / -7.82% / 3.89 | 39.98% / -7.82% / 3.94 | 53.16% / -7.82% / 4.90 | 59.70% / -5.99% / 5.29 |

Weight diagnostics:

| Candidate | Avg Microcap | Latest Microcap | Latest Sub-B | Rebalance count | Allocation turnover |
|---|---:|---:|---:|---:|---:|
| Fixed `10/15/15/20/40` | 15.00% | 15% | 40% | 0 | 0.0 |
| `dd_3_10_daily` | 17.03% | 10% | 45% | 223 | 22.3 |
| `dd_3_10_month_end` | 16.93% | 10% | 45% | 59 | 6.3 |
| `dd_5_12_month_end` | 17.85% | 10% | 45% | 43 | 4.7 |

Decision:

Use the real Sub-D five-sleeve run as the active combo-level evidence. The earlier `Sub-C` proxy run and all four-sleeve runs are superseded for allocation decisions.

The practical candidate remains `dd_3_10_month_end`: it keeps execution complexity low, ends with Microcap at 10% / Sub-B at 45%, and improves latest-1Y return and Sharpe versus fixed five-sleeve baseline. The daily version has the best headline metrics but much higher allocation turnover.

## Level-8 Decision Rules

Use these rules before promoting future research into source defaults:

1. Portfolio first.
   A candidate must improve merged daily NAV behavior at the combined-portfolio level, not only its own sleeve.

2. Daily drawdown only.
   Max drawdown must be computed from daily merged NAV, not monthly summaries.

3. Sleeve role clarity.
   Every sleeve must have an explicit job:
   - Sub-A: high-beta A-share upside, capped because it is regime-sensitive.
   - Sub-A-DK: A-share relative/hedged convexity and diversification.
   - Microcap: independent China small-cap momentum sleeve, high standalone value but must be freshness-checked.
   - Sub-B: global multi-asset core and stabilizer.

4. Default changes need a materiality bar.
   A small positive single-sleeve change can land only when it has no obvious portfolio downside. A strategic default change needs visible portfolio impact across recent windows.

5. Complexity budget.
   Do not add a new rule unless it improves either return, drawdown, or robustness enough to justify another branch in live interpretation.

## Full Four-Sleeve Weight Check

Status: superseded by the corrected five-sleeve real Sub-D validation above.

Run output: `outputs/v76_four_sleeve_weight_check_20260512/summary.csv`.

Path:

- Official V7.6 `_fetch_data(..., include_cn_live_snapshot=False, include_us_live_snapshot=False)`
- Official V7.6 `_run_strategies()`
- Microcap source: `../微盘股对冲策略/outputs/microcap_top100_mom11_targetvol30_max2_v1_8_costed_nav.csv`
- Combo NAV: daily sleeve NAV merge, weighted by production/candidate capital weights

Data:

| Component | Start | End | Rows |
|---|---:|---:|---:|
| Sub-A | 2010-11-22 | 2026-05-08 | 3755 |
| Sub-A-DK | 2010-11-22 | 2026-05-08 | 3754 |
| Sub-B | 2010-11-22 | 2026-05-08 | 3888 |
| Microcap | 2010-11-22 | 2026-05-08 | 3752 |

Common comparison window: `2010-11-22` to `2026-05-08`.

### Candidate Results

Metrics are annual return / daily max drawdown / Sharpe.

| Scenario | Full | 10Y | 5Y | 3Y | 1Y |
|---|---:|---:|---:|---:|---:|
| Current `10/15/15/60` | 37.72% / -16.53% / 2.67 | 41.85% / -16.53% / 2.60 | 45.18% / -16.53% / 2.32 | 55.71% / -16.53% / 2.77 | 20.52% / -16.53% / 0.97 |
| `5/15/20/60` | 39.69% / -18.24% / 2.64 | 43.24% / -18.24% / 2.49 | 46.39% / -18.24% / 2.23 | 56.70% / -18.24% / 2.66 | 17.73% / -18.24% / 0.80 |
| `10/15/20/55` | 39.86% / -17.77% / 2.68 | 42.82% / -17.77% / 2.51 | 46.21% / -17.77% / 2.25 | 56.66% / -17.77% / 2.69 | 18.84% / -17.77% / 0.86 |
| `5/15/15/65` | 37.51% / -17.12% / 2.63 | 42.32% / -17.12% / 2.58 | 45.38% / -17.12% / 2.29 | 55.73% / -17.12% / 2.72 | 19.11% / -17.12% / 0.89 |
| `5/20/20/55` | 39.71% / -18.29% / 2.66 | 43.05% / -18.29% / 2.49 | 46.31% / -18.29% / 2.23 | 56.37% / -18.29% / 2.66 | 17.63% / -18.29% / 0.80 |

Delta versus current:

| Scenario | Full annual delta | MaxDD delta | Full Sharpe delta | 1Y annual delta | 1Y Sharpe delta |
|---|---:|---:|---:|---:|---:|
| `5/15/20/60` | +1.96 pp | -1.70 pp | -0.03 | -2.78 pp | -0.17 |
| `10/15/20/55` | +2.13 pp | -1.23 pp | +0.01 | -1.68 pp | -0.11 |
| `5/15/15/65` | -0.22 pp | -0.59 pp | -0.05 | -1.41 pp | -0.08 |
| `5/20/20/55` | +1.99 pp | -1.75 pp | -0.01 | -2.89 pp | -0.18 |

Underwater diagnostic:

- All tested scenarios are still underwater at the common end date.
- Current open underwater days: 170.
- Candidate open underwater days: 170.
- This means the tested static weight changes do not solve the current recovery-duration problem.

### Decision

Do not change production weights now.

The current `10/15/15/60` default still has the best 1Y behavior and the shallowest daily max drawdown among the tested cases. Increasing Microcap to 20% improves long-run annual return, but the improvement is paid for with deeper drawdown and weaker recent-window Sharpe.

Promote `10/15/20/55` to a watchlist candidate only. It is the cleanest higher-Microcap variant because full-sample Sharpe is slightly positive versus current, but the evidence is not strong enough for a production default change.

Reject `5/15/15/65` as a defensive default. It does not improve full-sample return or Sharpe and still worsens drawdown.

## Dynamic Microcap Risk-Budget Check

Run output: `outputs/v76_dynamic_microcap_risk_budget_20260512/summary.csv`.

This run tests the portfolio-state question directly: keep the base V7.6 sleeve roles, but let Microcap risk budget move between 10%, 15%, and 20% based on Microcap's own prior-day NAV state. Sub-B absorbs the difference.

Important metric caveat:

- The static four-sleeve check above used weighted sleeve NAVs.
- This dynamic check uses daily sleeve returns and daily weights.
- Therefore the fair baseline inside this section is `fixed_rebalanced_10/15/15/60`, not the earlier weighted-NAV static table.
- Dynamic weights for date `t` use only information through `t-1`.
- Inter-sleeve allocation turnover cost is not modeled.

Metrics are annual return / daily max drawdown / Sharpe.

| Scenario | Full | 10Y | 5Y | 3Y | 1Y |
|---|---:|---:|---:|---:|---:|
| Fixed rebalanced `10/15/15/60` | 28.35% / -8.52% / 2.98 | 34.42% / -7.52% / 3.36 | 34.08% / -7.52% / 3.18 | 44.00% / -7.52% / 3.79 | 53.44% / -7.52% / 4.41 |
| Fixed rebalanced `10/15/20/55` | 29.98% / -8.08% / 3.24 | 35.24% / -7.63% / 3.56 | 35.22% / -7.63% / 3.36 | 45.04% / -7.63% / 4.00 | 50.98% / -7.63% / 4.34 |
| Dynamic: Microcap 20% if DD within 5%, else 15% | 29.86% / -8.08% / 3.19 | 35.21% / -7.52% / 3.49 | 34.86% / -7.52% / 3.28 | 45.19% / -7.52% / 3.94 | 54.29% / -7.52% / 4.45 |
| Dynamic: Microcap 20% if above 126D MA, else 15% | 29.77% / -8.08% / 3.20 | 34.96% / -7.56% / 3.51 | 35.15% / -7.56% / 3.34 | 45.40% / -7.56% / 4.01 | 52.45% / -7.56% / 4.40 |
| Dynamic: above 126D MA and within 10% DD | 29.72% / -8.08% / 3.19 | 34.92% / -7.56% / 3.49 | 35.06% / -7.56% / 3.31 | 45.44% / -7.56% / 3.99 | 53.65% / -7.56% / 4.45 |
| Dynamic: Microcap 20% within 5% DD, 10% below -10% DD, else 15% | 29.82% / -8.08% / 3.16 | 35.21% / -7.46% / 3.46 | 34.95% / -7.46% / 3.25 | 45.65% / -7.46% / 3.94 | 57.01% / -7.46% / 4.54 |

Weight diagnostics:

| Scenario | Avg Microcap | Last Microcap | Weight changes |
|---|---:|---:|---:|
| Fixed `10/15/15/60` | 15.00% | 15.00% | 0 |
| Fixed `10/15/20/55` | 20.00% | 20.00% | 0 |
| DD within 5% boost | 18.34% | 15.00% | 142 |
| Above 126D MA boost | 19.28% | 15.00% | 90 |
| MA + DD boost | 19.05% | 15.00% | 108 |
| DD 5/10 tier | 17.75% | 10.00% | 198 |

Decision:

Do not land any dynamic allocation rule into production yet.

Promote `dyn_microcap_10_15_20_by_dd_5_10` to the next candidate validation stage. It is the only tested rule that improves the latest 1Y return, latest 1Y Sharpe, and daily max drawdown at the same time under the daily-weight baseline. It also ends at Microcap 10%, which matches the current weak Microcap recovery state and directly addresses the present drawdown-duration problem.

The rule is promising, but it is not production-ready because it introduces dynamic inter-sleeve allocation turnover. The next validation must measure turnover timing and compare weekly or monthly rebalance versions before treating it as executable.

## Next Work Item

Run a rebalance-frequency validation for `dyn_microcap_10_15_20_by_dd_5_10`:

- daily signal, weekly execution;
- daily signal, month-end execution;
- same rule with 5% / 12% and 3% / 10% DD bands;
- include inter-sleeve turnover counts and approximate allocation turnover cost sensitivity.

This keeps the work at the level-8 question: dynamic risk budget and recovery behavior, not more single-sleeve parameter tuning.

## Rebalance-Frequency And Cost Validation

Run folder: `quant_param_scan_runs/20260512_v76_dynamic_microcap_rebalance_validation/`.

Inputs:

- `outputs/v76_dynamic_microcap_risk_budget_20260512/aligned_sleeve_returns.csv`
- No production source change.
- Weight target for date `t` uses Microcap NAV information through `t-1`.
- Weekly execution means the target changes only on the last available trading date of each `W-FRI` week.
- Month-end execution means the target changes only on the last available trading date of each calendar month.
- Inter-sleeve allocation turnover cost sensitivity: 0 / 5 / 10 / 20 bps.

### Cost-0 Summary

| Candidate | Full annual | Full maxDD | Full Sharpe | 1Y annual | 1Y maxDD | 1Y Sharpe | Turnover | Switches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Fixed `10/15/15/60` | 28.35% | -8.52% | 2.98 | 53.44% | -7.52% | 4.41 | 0.0 | 0 |
| `dd_3_10` daily | 29.71% | -8.08% | 3.13 | 57.08% | -7.46% | 4.56 | 29.1 | 290 |
| `dd_5_12` daily | 29.82% | -8.08% | 3.17 | 57.02% | -7.46% | 4.56 | 17.7 | 176 |
| `dd_5_10` daily | 29.82% | -8.08% | 3.16 | 57.01% | -7.46% | 4.54 | 20.1 | 198 |
| `dd_5_12` month-end | 29.80% | -8.08% | 3.16 | 56.10% | -7.52% | 4.47 | 5.7 | 52 |
| `dd_5_12` weekly | 29.64% | -8.08% | 3.15 | 56.36% | -7.52% | 4.46 | 9.7 | 96 |

### Month-End Cost Sensitivity

| Candidate | Cost | Full annual | Full Sharpe | 1Y annual | 1Y Sharpe | Turnover | Switches |
|---|---:|---:|---:|---:|---:|---:|---:|
| `dd_5_12` month-end | 0 bps | 29.80% | 3.16 | 56.10% | 4.47 | 5.7 | 52 |
| `dd_5_12` month-end | 5 bps | 29.77% | 3.16 | 56.06% | 4.47 | 5.7 | 52 |
| `dd_5_12` month-end | 10 bps | 29.75% | 3.16 | 56.01% | 4.47 | 5.7 | 52 |
| `dd_5_12` month-end | 20 bps | 29.70% | 3.15 | 55.92% | 4.46 | 5.7 | 52 |

Decision:

Do not land dynamic allocation into production yet.

Promote `dd_5_12_month_end` as the next practical candidate. The pure latest-1Y winner is `dd_3_10_daily`, but it is too active: 290 Microcap weight switches and 29.1 total allocation turnover. `dd_5_12_month_end` keeps most of the return and Sharpe improvement while reducing total allocation turnover to 5.7 and switches to 52. It also remains stable under 20 bps inter-sleeve turnover cost.

Next validation should not widen the threshold grid. The next question is implementation fit:

- whether V7.6 can display a dynamic Microcap risk-budget recommendation clearly without changing sleeve internals;
- whether the Microcap v1.8 live output already exposes enough NAV state to compute the rule in the combo layer;
- whether the production query should show this as an advisory overlay first, not an executed default.

## Advisory Implementation Fit Check

Run output: `outputs/v76_microcap_dynamic_advisory_fit_20260512/advisory_summary.md`.

Status: superseded because this run used Microcap v1.8. Use the corrected v1.6 section below for current decisions.

This check used the official V7.6 `_load_microcap_daily_ret()` path, which reads Microcap v1.8 `return_net`. That is enough to rebuild Microcap NAV, peak, and drawdown in the combo layer.

Current state:

| Item | Value |
|---|---:|
| Latest Microcap date | 2026-05-08 |
| Latest Microcap NAV drawdown | -19.82% |
| Prior drawdown used for latest daily signal | -21.05% |
| Latest daily signal Microcap weight | 10% |
| Last valid month-end execution date | 2026-04-30 |
| Current executed month-end Microcap weight | 10% |

Current advisory combo weights:

| Sleeve | Advisory weight |
|---|---:|
| Sub-A | 10% |
| Sub-A-DK | 15% |
| Microcap | 10% |
| Sub-B | 65% |

Implementation decision:

- Existing V7.6 data path is sufficient.
- No Microcap v1.8 internal strategy change is needed.
- Do not change `COMBINED_WEIGHTS` yet.
- Do not change the existing no-Microcap `PERFORMANCE_COMBO_ORDER` query yet.
- If implemented, first show this as an advisory line in the parameters/live-parameters combo section.

Important correction: for live/advisory use, the current incomplete month must not be treated as month-end. The fit-check now treats `2026-04-30` as the last valid month-end execution date, not the latest available date `2026-05-08`.

## Corrected V1.6 Dynamic Risk-Budget Check

Run folder: `quant_param_scan_runs/20260512_v76_dynamic_microcap_v16_rebalance_validation/`.

Inputs:

- Microcap source: `../微盘股对冲策略/outputs/microcap_top100_mom16_targetvol25_max1p5_v1_6_costed_nav.csv`
- Microcap return column: `return_net`
- Non-Microcap sleeves: same V7.6 aligned Sub-A / Sub-A-DK / Sub-B returns used in the earlier dynamic validation
- Source-change rule: corrected source only; no Microcap v1.6 internal strategy change

### V1.6 Cost-0 Summary

| Candidate | Full annual | Full maxDD | Full Sharpe | 1Y annual | 1Y maxDD | 1Y Sharpe | Turnover | Switches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Fixed `10/15/15/60` | 24.87% | -8.33% | 2.61 | 44.39% | -8.33% | 3.65 | 0.0 | 0 |
| `dd_3_10` daily | 25.89% | -8.22% | 2.74 | 47.25% | -8.22% | 3.89 | 22.9 | 229 |
| `dd_5_10` daily | 25.91% | -8.41% | 2.75 | 46.26% | -8.41% | 3.80 | 17.9 | 178 |
| `dd_5_12` daily | 25.95% | -8.44% | 2.76 | 45.23% | -8.44% | 3.75 | 16.7 | 166 |
| `dd_3_10` month-end | 25.64% | -8.33% | 2.71 | 45.91% | -8.33% | 3.74 | 6.5 | 60 |
| `dd_5_12` month-end | 25.75% | -8.61% | 2.74 | 45.11% | -8.61% | 3.73 | 5.3 | 49 |
| `dd_5_10` month-end | 25.80% | -8.61% | 2.74 | 45.50% | -8.61% | 3.72 | 5.7 | 49 |

### V1.6 Current Advisory

Run output: `outputs/v76_microcap_v16_dynamic_advisory_fit_20260512/advisory_summary.md`.

Rule: `dd_3_10_month_end`, because the corrected v1.6 scan favored this over `dd_5_12_month_end` on the practical month-end comparison.

| Item | Value |
|---|---:|
| Latest Microcap date | 2026-05-08 |
| Latest Microcap NAV drawdown | -17.49% |
| Prior drawdown used for latest daily signal | -18.68% |
| Latest daily signal Microcap weight | 10% |
| Last valid month-end execution date | 2026-04-30 |
| Current executed month-end Microcap weight | 10% |

Current advisory combo weights:

| Sleeve | Advisory weight |
|---|---:|
| Sub-A | 10% |
| Sub-A-DK | 15% |
| Microcap | 10% |
| Sub-B | 65% |

Corrected decision:

The dynamic Microcap risk-budget idea still works directionally under the correct v1.6 source, but the effect is smaller than the v1.8 run suggested. Treat this as a watchlist/advisory feature only.

Among executable candidates, `dd_3_10_month_end` is now the cleanest practical candidate because it improves 1Y return and Sharpe while keeping maxDD near the fixed baseline and turnover low. `dd_5_12_month_end` is more conservative in switching count but worsens maxDD more under v1.6.

Do not land a dynamic allocation default yet. If implemented next, show it as an advisory line only and label the Microcap source explicitly as v1.6.

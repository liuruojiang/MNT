# V7.6 A/ADK/B/Sub-D Dynamic Budget Optimization

## Run Metadata

- Project: V7.6 Level-8 five-sleeve portfolio.
- Entrypoint: `run_v76_adk_b_subd_dynamic_budget_optimization.py`.
- Source-change rule: no production strategy source defaults are changed by this scan.

## Research Question

Microcap's `3/10` dynamic budget rule should not be assumed to fit Sub-A, ADK, Sub-B, or Sub-D. This scan tests each sleeve against its own prior NAV drawdown state.

## Implementation Anchor

- Input returns: `quant_param_scan_runs/20260512_v76_five_sleeve_real_subd_v16_rebalance_validation/aligned_five_sleeve_real_subd_returns.csv`.
- Manifest: `portfolio_manifests/v76_current.json`.
- Portfolio math reuses `build_v76_portfolio_nav.py` helpers.

## Data Snapshot

- Common daily aligned sleeve-return sample: 2011-12-09 to 2026-05-08.
- Sleeves: Sub-A, Sub-A-DK, Microcap v1.6, Sub-D v1.1, Sub-B.

## Cost and Execution Assumptions

- Daily return cost stress: allocation turnover times cost bps / 10000.
- Cost bps grid: 0, 5, 10, 20.
- Execution grid: daily, weekly, month-end.
- Weight target for date t uses sleeve NAV drawdown through t-1.

## Runtime Override Plan

- Research-only runtime overlay on aligned return series.
- No `mnt_bot V 7.6 plus.py` default is changed.

## Commands

- `python run_v76_adk_b_subd_dynamic_budget_optimization.py`

## Output Files

- `C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/动量策略/A股美股动量组合策略/quant_param_scan_runs/20260512_v76_level8_v7_6_five_sleeve_a_adk_b_subd_dynamic_budget_prior_nav_dd_threshold_execution_step/scan_summary.csv`
- `C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/动量策略/A股美股动量组合策略/quant_param_scan_runs/20260512_v76_level8_v7_6_five_sleeve_a_adk_b_subd_dynamic_budget_prior_nav_dd_threshold_execution_step/window_metrics.csv`
- `C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/动量策略/A股美股动量组合策略/quant_param_scan_runs/20260512_v76_level8_v7_6_five_sleeve_a_adk_b_subd_dynamic_budget_prior_nav_dd_threshold_execution_step/scan_meta.json`

## Full-Sample Results

See `scan_summary.csv` for the full long-form table and `window_metrics.csv` for the wide comparison.

## Window Results

The table below shows the best candidate per sleeve under the recent-weighted score.

## Microcap 3/10 Implicit Logic

- Prior NAV drawdown within 3% means the sleeve is near its high-water mark, so risk budget can be boosted.
- Prior NAV drawdown at or below -10% means the sleeve is materially underwater, so risk budget is cut.
- The middle zone keeps the base weight to avoid reacting to ordinary noise.
- This is a sleeve-state rule, not a universal parameter set.

## Scan Design

- Sleeves tested: Sub-A, Sub-A-DK, Sub-B, Sub-D.
- Sub-A, ADK, and Sub-D use Sub-B as absorber.
- Sub-B uses the other four sleeves as a proportional absorber group, because Sub-B cannot absorb its own weight delta.
- Grid: boost DD 2/3/5/7%, cut DD 8/10/12/15%, execution daily/weekly/month-end, step 2.5/5pp, cost 0/5/10/20 bps.
- Candidate weights use only prior sleeve NAV drawdown, so the signal timing is non-lookahead.

## Best By Sleeve

| Sleeve | Candidate | Cost | Full annual | Full maxDD | Full Sharpe | 1Y annual delta | 1Y Sharpe delta | Turnover | Switches |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Sub-A | `advisory_suba_dd_5_8_weekly_step5_cost0bps` | 0 bps | 31.67% | -7.10% | 3.36 | 2.26% | +0.25 | 7.7 | 68 |
| Sub-A-DK | `advisory_subadk_dd_3_8_weekly_step5_cost0bps` | 0 bps | 30.78% | -9.12% | 3.29 | 1.60% | +0.07 | 19.3 | 190 |
| Sub-B | `advisory_subb_dd_2_12_month_end_step2_cost0bps` | 0 bps | 30.20% | -7.82% | 3.25 | -0.16% | -0.06 | 2.8 | 55 |
| Sub-D | `advisory_subd_dd_7_8_weekly_step5_cost0bps` | 0 bps | 30.59% | -7.99% | 3.23 | 3.51% | +0.27 | 15.9 | 117 |

## Stability Classification

candidate evidence; requires follow-up stability validation.

## Decision

Use this run as candidate-selection evidence only. Do not promote Sub-A, ADK, Sub-B, or Sub-D dynamic budget rules without a follow-up stability read against the chosen candidate's role and live display complexity.

## User-Facing Summary

Microcap's 3/10 rule is a valid framework seed, but Sub-A, ADK, Sub-B, and Sub-D require sleeve-specific parameters. In this run, Sub-A is the cleaner broad-window candidate, Sub-D is the stronger recent-window candidate, Sub-B is weak under this design, and ADK is only narrow-positive.
## Finalization

- Finalized at: 2026-05-12T14:20:33+08:00
- Decision: A/ADK/B/Sub-D require sleeve-specific dynamic-budget tests. Current evidence: Sub-A is the cleaner broad-window candidate, Sub-D is the strongest recent-window candidate, Sub-B dynamic budget is weak under this proportional-absorber design, and ADK is only narrow-positive.
- Stability label: candidate evidence; Sub-A and Sub-D require follow-up stability validation
- Complete checker: PASS

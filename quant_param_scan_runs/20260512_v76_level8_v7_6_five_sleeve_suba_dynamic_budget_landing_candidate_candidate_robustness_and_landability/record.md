# V7.6 Sub-A Dynamic Budget Landing Candidate Validation

## Research Question

Validate whether the selected Sub-A dynamic-budget rule is robust enough to become the next landing candidate, before changing production defaults.

## Selected Candidate

- Candidate: `advisory_suba_dd_5_8_weekly_step5_cost0bps`.
- Rule: Sub-A prior NAV drawdown within 5% -> 15%; drawdown at or below 8% -> 5%; otherwise 10%; weekly execution; Sub-B absorbs the delta.
- Source scan: `run_v76_adk_b_subd_dynamic_budget_optimization.py`.

## Data Snapshot

- Common daily aligned sleeve-return sample: 2011-12-09 to 2026-05-08.
- Baseline weights: Sub-A 10%, Sub-A-DK 15%, Microcap 15%, Sub-D 20%, Sub-B 40%.

## Measured Result

- Target full annual: 31.67%; delta vs fixed: 1.29%.
- Target full maxDD: -7.10%; delta vs fixed: 0.77%.
- Target full Sharpe: 3.36; delta vs fixed: +0.081.
- 10Y/5Y/3Y/1Y annual deltas: 1.04%, 1.12%, 2.06%, 2.26%.
- 20bps stress full annual delta: 1.15%; 20bps full Sharpe delta: +0.067.

## Neighborhood Stability

- Passing non-target neighbors under the same strict check: 67.
- Strict check used here: all full/10Y/5Y/3Y/1Y annual deltas positive, full maxDD not worse, full Sharpe positive.

| Candidate | Cost | Full annual delta | Full maxDD delta | Full Sharpe delta | 1Y annual delta | Score |
|---|---:|---:|---:|---:|---:|---:|
| `advisory_suba_dd_5_8_weekly_step5_cost0bps` | 0 bps | 1.29% | 0.77% | +0.081 | 2.26% | 0.1149 |
| `advisory_suba_dd_7_8_weekly_step5_cost0bps` | 0 bps | 1.40% | 0.77% | +0.080 | 2.26% | 0.1139 |
| `advisory_suba_dd_5_8_weekly_step5_cost5bps` | 5 bps | 1.26% | 0.76% | +0.078 | 2.26% | 0.1136 |
| `advisory_suba_dd_7_8_weekly_step5_cost5bps` | 5 bps | 1.36% | 0.76% | +0.077 | 2.26% | 0.1126 |
| `advisory_suba_dd_5_8_weekly_step5_cost10bps` | 10 bps | 1.22% | 0.75% | +0.074 | 2.26% | 0.1124 |
| `advisory_suba_dd_7_8_daily_step5_cost0bps` | 0 bps | 1.20% | 0.68% | +0.060 | 2.26% | 0.1120 |
| `advisory_suba_dd_7_8_weekly_step5_cost10bps` | 10 bps | 1.33% | 0.75% | +0.073 | 2.26% | 0.1114 |
| `advisory_suba_dd_7_8_daily_step5_cost5bps` | 5 bps | 1.14% | 0.66% | +0.054 | 2.26% | 0.1100 |

## Landability Surface

| Surface | Path | Notes |
|---|---|---|
| scenario constants | `mnt_bot V 7.6 plus.py` | PORTFOLIO_ADVISORY_SCENARIO / PORTFOLIO_STACKED_ADVISORY_SCENARIO currently name the old microcap and Sub-A+microcap advisory scenarios. |
| snapshot loader | `mnt_bot V 7.6 plus.py` | _load_combo_advisory_snapshot reads outputs/portfolio_v76_current scenario files; landing A-only should either add a new scenario or update the selected advisory scenario deliberately. |
| signal display | `mnt_bot V 7.6 plus.py` | Signal/live-signal output must show Sub-A target 5/10/15%, Sub-B absorber target, trigger 5%, cut 8%, and prior Sub-A NAV drawdown. |
| params display | `mnt_bot V 7.6 plus.py` | 参数 / 实时参数 should expose the same thresholds and execution frequency if promoted. |

## Stability Classification

landing candidate; acceptable broad-window stability, but not yet production default.

## Decision

Promote Sub-A 5/8 weekly step5 to the next implementation candidate. Do not enable it as production default until the V7.6 scenario output, signal, live-signal, params, and live-params display surfaces are updated and verified.

## Output Files

- `C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/动量策略/A股美股动量组合策略/quant_param_scan_runs/20260512_v76_level8_v7_6_five_sleeve_suba_dynamic_budget_landing_candidate_candidate_robustness_and_landability/scan_summary.csv`
- `C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/动量策略/A股美股动量组合策略/quant_param_scan_runs/20260512_v76_level8_v7_6_five_sleeve_suba_dynamic_budget_landing_candidate_candidate_robustness_and_landability/window_metrics.csv`
- `C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/动量策略/A股美股动量组合策略/quant_param_scan_runs/20260512_v76_level8_v7_6_five_sleeve_suba_dynamic_budget_landing_candidate_candidate_robustness_and_landability/ranked_validation.csv`
- `C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/动量策略/A股美股动量组合策略/quant_param_scan_runs/20260512_v76_level8_v7_6_five_sleeve_suba_dynamic_budget_landing_candidate_candidate_robustness_and_landability/landability_surface.csv`
- `C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/动量策略/A股美股动量组合策略/quant_param_scan_runs/20260512_v76_level8_v7_6_five_sleeve_suba_dynamic_budget_landing_candidate_candidate_robustness_and_landability/scan_meta.json`
## Finalization

- Finalized at: 2026-05-12T14:32:00+08:00
- Decision: Sub-A 5/8 weekly step5 is promoted to the next implementation candidate. It is not yet production default; landing requires V7.6 scenario output plus signal/live-signal/params/live-params display updates and verification.
- Stability label: landing candidate; acceptable broad-window stability, but not yet production default
- Complete checker: PASS

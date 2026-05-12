# V7.6 Sub-A/Sub-D Dynamic Budget Interaction Validation

## Run Metadata

- Project: V7.6 Level-8 five-sleeve portfolio.
- Entrypoint: `run_v76_suba_subd_dynamic_budget_interaction_validation.py`.
- Source-change rule: no production strategy defaults are changed by this validation.

## Research Question

Validate whether the selected Sub-A dynamic-budget candidate and selected Sub-D candidate remain useful alone and together after cost pressure.

## Implementation Anchor

- Input returns: `quant_param_scan_runs/20260512_v76_five_sleeve_real_subd_v16_rebalance_validation/aligned_five_sleeve_real_subd_returns.csv`.
- Manifest: `portfolio_manifests/v76_current.json`.
- Portfolio math reuses `build_v76_portfolio_nav.py` helpers.

## Data Snapshot

- Common daily aligned sleeve-return sample: 2011-12-09 to 2026-05-08.
- Baseline weights: Sub-A 10%, Sub-A-DK 15%, Microcap 15%, Sub-D 20%, Sub-B 40%.

## Cost and Execution Assumptions

- Daily return cost stress: allocation turnover times cost bps / 10000.
- Cost bps grid: 0, 5, 10, 20.
- Selected dynamic rules execute weekly and use only each sleeve's prior NAV drawdown.
- Sub-B absorbs the total weight delta when Sub-A and Sub-D are both dynamic.

## Candidates

- Sub-A selected family: `5/8 weekly step5`, plus neighbor `7/8 weekly step5`.
- Sub-D selected family: `7/8 weekly step5`.
- Combined candidates: Sub-A selected family plus Sub-D selected family together.

## Best Candidate

- `suba_dd_5_8_plus_subd_dd_7_8_weekly_step5_cost0bps`
- Full annual: 31.88%
- Full maxDD: -7.23%
- Full Sharpe: 3.31
- 1Y annual delta: 5.80%
- 1Y Sharpe delta: +0.49
- Turnover: 23.1

## Ranked Summary

| Candidate | Cost | Full annual | Full maxDD | Full Sharpe | 5Y ann delta | 3Y ann delta | 1Y ann delta | Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `suba_dd_5_8_plus_subd_dd_7_8_weekly_step5_cost0bps` | 0 bps | 31.88% | -7.23% | 3.31 | 2.47% | 5.16% | 5.80% | 0.2389 |
| `suba_dd_7_8_plus_subd_dd_7_8_weekly_step5_cost0bps` | 0 bps | 31.99% | -7.22% | 3.30 | 2.41% | 5.10% | 5.80% | 0.2377 |
| `suba_dd_5_8_plus_subd_dd_7_8_weekly_step5_cost5bps` | 5 bps | 31.78% | -7.25% | 3.30 | 2.38% | 5.10% | 5.75% | 0.2333 |
| `suba_dd_7_8_plus_subd_dd_7_8_weekly_step5_cost5bps` | 5 bps | 31.88% | -7.25% | 3.29 | 2.31% | 5.03% | 5.75% | 0.2320 |
| `suba_dd_5_8_plus_subd_dd_7_8_weekly_step5_cost10bps` | 10 bps | 31.67% | -7.28% | 3.29 | 2.28% | 5.05% | 5.71% | 0.2277 |
| `suba_dd_7_8_plus_subd_dd_7_8_weekly_step5_cost10bps` | 10 bps | 31.78% | -7.28% | 3.28 | 2.22% | 4.97% | 5.71% | 0.2263 |
| `suba_dd_5_8_plus_subd_dd_7_8_weekly_step5_cost20bps` | 20 bps | 31.46% | -7.34% | 3.26 | 2.09% | 4.94% | 5.61% | 0.2164 |
| `suba_dd_7_8_plus_subd_dd_7_8_weekly_step5_cost20bps` | 20 bps | 31.57% | -7.33% | 3.26 | 2.03% | 4.85% | 5.61% | 0.2149 |
| `subd_dd_7_8_weekly_step5_cost0bps` | 0 bps | 30.59% | -7.99% | 3.23 | 1.34% | 3.05% | 3.51% | 0.1259 |
| `subd_dd_7_8_weekly_step5_cost5bps` | 5 bps | 30.52% | -8.01% | 3.23 | 1.28% | 3.01% | 3.46% | 0.1215 |
| `subd_dd_7_8_weekly_step5_cost10bps` | 10 bps | 30.45% | -8.03% | 3.22 | 1.21% | 2.96% | 3.41% | 0.1170 |
| `suba_dd_5_8_weekly_step5_cost0bps` | 0 bps | 31.67% | -7.10% | 3.36 | 1.12% | 2.06% | 2.26% | 0.1149 |

## Stability Classification

interaction candidate evidence; do not promote by default.

## Decision

Candidate evidence only. Sub-A alone remains the cleaner broad-window candidate; adding Sub-D together should be treated as an interaction candidate and not promoted until robustness and display complexity are reviewed.

## Output Files

- `C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/动量策略/A股美股动量组合策略/quant_param_scan_runs/20260512_v76_level8_v7_6_five_sleeve_suba_subd_combined_dynamic_budget_selected_candidate_interaction_cost/scan_summary.csv`
- `C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/动量策略/A股美股动量组合策略/quant_param_scan_runs/20260512_v76_level8_v7_6_five_sleeve_suba_subd_combined_dynamic_budget_selected_candidate_interaction_cost/window_metrics.csv`
- `C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/动量策略/A股美股动量组合策略/quant_param_scan_runs/20260512_v76_level8_v7_6_five_sleeve_suba_subd_combined_dynamic_budget_selected_candidate_interaction_cost/scan_meta.json`
## Finalization

- Finalized at: 2026-05-12T14:27:25+08:00
- Decision: Sub-A-only remains the cleaner broad-window candidate. Sub-A plus Sub-D is the strongest recent-window interaction candidate but uses more Sub-B absorption and should not be promoted without further robustness/display validation.
- Stability label: interaction candidate evidence; do not promote by default
- Complete checker: PASS

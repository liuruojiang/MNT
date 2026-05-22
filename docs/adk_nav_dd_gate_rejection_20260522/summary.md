# ADK NAV-DD Gate Rejection Record

Date: 2026-05-22

## Decision

Do not adopt the ADK NAV-DD half-scale gate.

The best local candidate, `dd10_5_scale0p5`, improved standalone ADK 10Y drawdown and Return/DD, but the fine scan showed the usable ridge was too narrow. The only strong plateau was around `9/5` to `10/5`; loosening the right side quickly fell below the baseline on Return/DD, and `12/6` was worse than the baseline on both return efficiency and drawdown.

## Evidence

Source data and assumptions:

- Baseline daily source: `quant_param_scan_runs/20260522_a_us_momentum_combo_v7_7_adk_original_ratio_chaos_filters_top_score_gap_r2_confirm/daily_curves.csv`
- Formal ADK start: `2014-10-17`
- Data end: `2026-05-14`
- Cost model: one-way commission `0.050%`, turnover rebuilt from final long/short legs
- Execution timing: prior ADK NAV drawdown state affects the next trading row

Key fine-scan results:

| Candidate | 10Y ann | 10Y max DD | Return/DD | Note |
|---|---:|---:|---:|---|
| baseline | 20.06% | -15.49% | 1.30 | Production comparison baseline |
| `dd9_5_scale0p5` | 18.02% | -13.25% | 1.36 | Close robustness neighbor, more derisking |
| `dd10_5_scale0p5` | 18.13% | -13.25% | 1.37 | Best local point, but not adopted |
| `dd10_6_scale0p5` | 18.01% | -14.28% | 1.26 | Right side already below baseline Return/DD |
| `dd11_5_scale0p5` | 17.75% | -14.15% | 1.25 | Below baseline Return/DD |
| `dd12_6_scale0p5` | 17.46% | -15.81% | 1.10 | Worse than baseline on DD and Return/DD |

## Cleanup

Removed scratch parameter-scan directories under `quant_param_scan_runs/` after preserving this decision record.

Backup before deletion:

- `.codex_backups/20260522_160754_adk_dd_rejected_cleanup/`

Deleted scratch runs:

- `20260522_a_us_momentum_combo_v7_7_adk_fine_nav_dd_gate_around_dd10_5_scale0p5`
- `20260522_a_us_momentum_combo_v7_7_adk_leg_abs8_low_return_low_drawdown_strong_overheat_scale`
- `20260522_a_us_momentum_combo_v7_7_adk_leg_abs8_risk_controls_target_vol_max_lev_risk_gate_overheat`
- `20260522_a_us_momentum_combo_v7_7_adk_leg_bias_layer_buffer_abs_threshold`
- `20260522_a_us_momentum_combo_v7_7_adk_leg_momentum_relative_naked_cost_only`
- `20260522_a_us_momentum_combo_v7_7_adk_leg_momentum_source_bias_mom_buffer_abs_low_drawdown`
- `20260522_a_us_momentum_combo_v7_7_adk_log_ratio_slope_naked_cost_only`
- `20260522_a_us_momentum_combo_v7_7_adk_original_ratio_chaos_filters_top_score_gap_r2_confirm`
- `20260522_a_us_momentum_combo_v7_7_adk_outer_state_filters_nav_trend_dd_market_regime`
- `20260522_adk_pair_score_decay_overlay_v76_defaults_and_grid`
- `20260522_v77_combo_adk_nav_dd_10_5_scale0p5_impact`

## Follow-Up

No production strategy change should be made from this DD Gate family. If ADK risk control is revisited, start from a different regime definition rather than continuing to tune this NAV-DD gate.

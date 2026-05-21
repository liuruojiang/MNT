# V7.7 Sub-A Target-Vol / Leverage Threshold Test Record

Date: 2026-05-19

## Scope

This record summarizes the V7.7 Sub-A tests for:

- `CN_TARGET_VOL`
- `CN_MAX_LEV`
- `CN_SCALE_THRESHOLD`

Production strategy defaults were not changed in this cleanup step. The tests reused the current `mnt_bot V 7.7 plus.py` Sub-A path, including the formal ranking model, R2/abs-momentum gates, MA60 overheat take-profit, amount overlay, commission, and close-to-close rebuild path.

## Data And Cost Assumptions

- Data cutoff: 2026-05-18.
- Core price window: 2010-06-01 to 2026-05-18.
- Cost model: existing V7.7 Sub-A commission and scale-turnover cost.
- Execution timing: close-derived signal/overlay state affects the next close-to-close exposure segment.
- Slippage/open impact: not separately modeled beyond the repo's current commission/turnover model.

## Main Findings

The current `30% / 1.5x` setting is the most aggressive tested version. It keeps the highest recent-window return, but it relies heavily on capped leverage:

- 10Y held-period average VolScale: about `1.46x`.
- 10Y cap-hit ratio at `1.5x`: about `92%`.
- 10Y annual / max drawdown: about `35.32% / -25.50%`.

For lower-risk alternatives:

| Candidate | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | Comment |
|---|---:|---:|---:|---|
| `20% / 1.3x` | `2.181` | `57.53%` | `-22.17%` | Best broad four-way balance before threshold tests. |
| `30% / 1.2x` | `2.165` | `55.42%` | `-20.46%` | More defensive; slightly stronger than `25% / 1.2x` in same-run comparison. |
| `25% / 1.2x` | `2.155` | `55.00%` | `-20.46%` | Usable, but no clear edge over `30% / 1.2x`. |
| `30% / 1.5x` | `2.122` | `71.02%` | `-25.50%` | Current aggressive default. |

For fixed `1.5x` max leverage:

| Candidate | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | Comment |
|---|---:|---:|---:|---|
| `20% / 1.5x` | `2.171` | `64.28%` | `-25.13%` | Better Sharpe than `25% / 1.5x` and current `30% / 1.5x`. |
| `25% / 1.5x` | `2.148` | `69.36%` | `-25.50%` | Return closer to current, but risk barely improves. |
| `30% / 1.5x` | `2.122` | `71.02%` | `-25.50%` | Highest return, weakest risk-adjusted ranking in this group. |

## Scale-Threshold Follow-Up

The user's hypothesis was that `20%` and `25%`, especially `20%`, may underuse leverage and could improve if a VolScale switching threshold is added.

The scan supports this for `20% / 1.5x`, but not strongly for `25% / 1.5x`.

| Candidate | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | Comment |
|---|---:|---:|---:|---|
| `20% / 1.5x, threshold 0.15` | `2.196` | `63.61%` | `-25.50%` | Best Sharpe in the threshold scan. |
| `20% / 1.5x, threshold 0.20` | `2.155` | `63.90%` | `-22.21%` | Better drawdown, weaker Sharpe. |
| `20% / 1.5x, threshold 0.00` | `2.171` | `64.28%` | `-25.13%` | Baseline for the 20% threshold test. |
| `25% / 1.5x, threshold 0.10` | `2.150` | `68.68%` | `-25.50%` | Only tiny Sharpe improvement. |
| `25% / 1.5x, threshold 0.00` | `2.148` | `69.36%` | `-25.50%` | Baseline for the 25% threshold test. |

## Decision

No production constant was changed.

Current research priority:

1. Keep `20% / 1.5x / scale_threshold 0.15` as the leading follow-up candidate if preserving the `1.5x` max-leverage framework.
2. Keep `20% / 1.3x` as the cleaner lower-risk candidate if the goal is to reduce structural capped leverage.
3. Do not prioritize `25% / 1.5x`; it remains too close to current capped-risk behavior.
4. Treat `25% / 1.2x` as acceptable but not preferred versus `30% / 1.2x` in the same-run table.

## Preserved Evidence

- `quant_param_scan_runs/20260519_v77_suba_v7_7_sub_a_four_target_vol_max_lev_compare/`
- `quant_param_scan_runs/20260519_v77_suba_v7_7_sub_a_target_vol_20_25_lev1p5_compare/`
- `quant_param_scan_runs/20260519_v77_suba_v7_7_sub_a_target_vol_scale_threshold/`

All three preserved runs passed the strict quant-param-scan artifact checker.

## Cleanup Notes

- Formal strategy file `mnt_bot V 7.7 plus.py` was not edited.
- The scan folders are retained as evidence because their `scan_summary.csv`, `window_metrics.csv`, `scan_meta.json`, `record.md`, and `command_log.txt` are the reproducibility record.
- No active production test suite files were added for this research pass.

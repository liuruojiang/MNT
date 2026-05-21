# Power-WMA Cost-Only Signal Screen

Date: 2026-05-17

## Scope

This note records the direct Power-WMA replacement tests for the A-share momentum family in `mnt_bot V 7.6 plus.py`.

Common research rule:

- Keep only close-to-close signal timing and transaction cost.
- Remove overlays/gates such as R2 filters, target volatility, switch buffers, score-decay, RiskGate, overheat, volume rules, and other defensive layers.
- Compare original raw momentum signal against Power-WMA on the same asset universe and same data slice.
- Scan `lookback = [5, 10, 15, 20, 25, 30, 40, 60]` and `power = [0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2]`.

## ADK Result

Run folder:

`quant_param_scan_runs/20260517_a_v7_6_sub_a_dk_power_wma_cost_only_lookback_power`

Cost and execution:

- Universe: ADK pair spread universe from V7.6.
- Original signal: `_dk_calc_bias_momentum` on pair ratio.
- Power signal: Power-WMA on pair daily spread return.
- Positioning: daily Top-1 pair by prior-day absolute score, direction from sign.
- Cost: `CN_DK_COMMISSION = 0.0005`; no financing, cash yield, slippage, or open impact.

| Candidate | Full Ann / DD | 10Y Ann / DD | 5Y Ann / DD | 3Y Ann / DD | 1Y Ann / DD |
|---|---:|---:|---:|---:|---:|
| Original ADK | 19.83% / -43.25% | 18.44% / -25.37% | 17.70% / -25.37% | 11.02% / -25.37% | 9.14% / -18.47% |
| Best 5Y Power p0/lb25 | 16.12% / -53.64% | 13.66% / -32.42% | 12.13% / -32.42% | 14.65% / -32.42% | 38.75% / -16.39% |
| Power p0.25/lb30 | 11.51% / -56.62% | 10.04% / -32.06% | 11.39% / -32.06% | 15.55% / -32.06% | 47.32% / -9.78% |

Decision: reject as direct replacement. No Power candidate beats original across all recent windows by both return and drawdown. The p0/lb25 area has some short-window lift, but the ridge is not broad enough and full/10Y/5Y drawdown is worse.

## Sub-A Result

Run folder:

`quant_param_scan_runs/20260517_a_share_us_momentum_combo_v7_6_sub_a_cost_only_power_wma_lookback_power`

Cost and execution:

- Universe: Sub-A equity codes only.
- Original signal: `calc_bias_momentum`, `CN_BIAS_N=60`, `CN_MOM_DAY=20`.
- Power signal: Power-WMA on each index daily return.
- Positioning: top positive score holds 100%; all non-positive scores hold cash.
- Cost: `CN_COMMISSION = 0.001`; cash daily return forced to `0.0`; no slippage or open impact.
- Data: local `.cn_official_cache`, common close through 2026-05-15.

| Candidate | Full Ann / DD | 10Y Ann / DD | 5Y Ann / DD | 3Y Ann / DD | 1Y Ann / DD |
|---|---:|---:|---:|---:|---:|
| Original Sub-A | 17.56% / -50.67% | 12.46% / -35.66% | 18.01% / -31.25% | 25.89% / -25.24% | 75.62% / -6.56% |
| Best 5Y Power p0/lb10 | 14.28% / -54.57% | 10.83% / -35.32% | 16.18% / -24.12% | 15.33% / -24.12% | 53.99% / -13.47% |
| Power p0/lb25 | 15.14% / -39.90% | 10.63% / -31.80% | 12.09% / -23.93% | 18.41% / -23.18% | 64.95% / -13.74% |
| Best Full Power p0.5/lb25 | 16.98% / -39.03% | 9.25% / -33.99% | 7.81% / -33.45% | 5.96% / -31.04% | 42.05% / -17.27% |

Decision: reject as direct replacement. Power can reduce some drawdown windows, but the return loss is too large and no candidate clears the 5Y/3Y/1Y return-plus-drawdown bar.

## Cleanup Note

Key results from the formal scan folders were copied into this note. The one-off scripts, single-point output folders, and Power-WMA scan folders created for this exploration were removed after this record was written.

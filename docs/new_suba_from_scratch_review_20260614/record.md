# New Sub-A From-Scratch Review - 2026-06-14

## Scope

- Objective: Treat V7.7 Sub-A as a new strategy idea and rerun the new-strategy standard process from Layer 1.
- Original V7.7 role: reference only. Its own original conditions are added back only when the tested layer reaches that condition.
- Data panel: proxy-extended A-share index panel from Layer 1 `close_panel_used.csv`.
- Sample used by the proxy research run: 2011-05-03 to 2026-06-12.
- Mandatory windows: full sample, 10Y, 5Y, 3Y, and 1Y are shown in every layer artifact.
- Cost/timing: 10 bps turnover commission; T close signal changes exposure for the next close-to-close return; cash return is 0; financing cost above 1x is not separately modeled.
- Formality note: REDLOW100, ZZ1000, and ZZ500 proxy extensions are proxy research. Production promotion still needs a separate formal no-pre-publication-backfill review.

## Layer Decisions

| Layer | Test | Decision |
|---|---|---|
| 1 | Raw momentum signal and parameter width | Promote `bias_slope`; primary tuple `MA40 / mom20 / weight_end 3.0`. |
| 2 | R2 window and threshold | Do not add to primary. R2 was useful as reference/confirmation only. |
| 3 | Score threshold and absolute momentum threshold | Promote `score >= 10 / 10000` and `abs20 > 2%`. |
| 4 | Target volatility | Carry three lines: no target-vol main, TV 30%/80d/max 1.0, and TV 30%/80d/max 1.5 watch. |
| 5 | Static/NAV defense and momentum decay | Reject; no robust improvement worth adding. |
| 6 | Overheat: bias, score, volatility | Reject as promoted layer. Score-hot has diagnostic defensive value, especially for TV1.5, but return cost/width rule failed. |
| 7 | First-entry half position, wait first down day to add | Reject; exact rule worsened key windows. |
| 8 | CYB-only amount contraction | Reject; sparse single points only, no width-supported patch. ZZ2000 amount was kept out of the new strategy scan. |

## Final New-Strategy Lines

| Candidate | Role | Full | 10Y | 5Y | 3Y | 1Y |
|---|---|---:|---:|---:|---:|---:|
| `main_no_tv_base` | current main | 21.87% / -20.30% | 13.34% / -20.30% | 17.15% / -20.26% | 24.38% / -20.26% | 50.07% / -7.81% |
| `tv30_w80_max1p0_base` | no-leverage TV parallel main | 22.14% / -20.30% | 13.78% / -20.30% | 18.06% / -13.43% | 26.00% / -13.43% | 50.07% / -7.81% |
| `tv30_w80_max1p5_base` | 1.5x TV comparison watch | 29.68% / -29.23% | 19.68% / -29.23% | 26.48% / -18.24% | 38.72% / -15.48% | 81.13% / -10.49% |

## V7.7 Reference

Layer-progressive reference in the same proxy research panel:

| Candidate | Conditions included | Full | 10Y | 5Y | 3Y | 1Y |
|---|---|---:|---:|---:|---:|---:|
| `v77_reference_before_amount_tv30_w80_max1p5_same_side_oh27_24_s0` | original R2/abs momentum, target-vol, same-side overheat | 28.82% / -29.84% | 22.54% / -29.39% | 30.41% / -22.18% | 49.75% / -18.65% | 121.05% / -10.64% |
| `v77_reference_with_original_amount_zz2000_ma20_d3_or_cyb_ma20_d4_s0` | plus original ZZ2000/CYB amount overlay | 25.67% / -29.59% | 25.89% / -22.92% | 29.32% / -19.11% | 49.23% / -16.02% | 105.15% / -10.64% |

Official V7.7 full-chain review is stored separately in `docs/v77_suba_standard_review_20260614/`. Because official V7.7 Sub-A includes the CSI 2000 amount overlay, its formal sample starts on 2023-08-11.

## Diagnostic Notes

- TV1.5 score-hot diagnostic: `score >= 0.006`, recover at `0.003`, defense scale `0.75`.
- Diagnostic metrics: 25.65% / -25.92% full; 17.44% / -25.72% 10Y; 22.53% / -18.24% 5Y; 33.82% / -14.21% 3Y; 72.82% / -10.49% 1Y.
- It was not promoted because the return cost was too high and the pass/width standard was not met.

## Artifact Map

- Layer 1: `quant_param_scan_runs/20260614_a_share_new_sub_a_strategy_new_suba_from_scratch_proxy_extended_layer1_signal_width_bias_slope_width_proxy_extended/`
- Layer 2: `quant_param_scan_runs/20260614_a_share_new_sub_a_strategy_new_suba_from_scratch_proxy_extended_layer2_r2_filter_r2_window_threshold/`
- Layer 3: `quant_param_scan_runs/20260614_a_share_new_sub_a_strategy_new_suba_from_scratch_proxy_extended_layer3_score_abs_momentum_filter_score_threshold_abs_momentum_threshold/`
- Layer 4: `quant_param_scan_runs/20260614_a_share_new_sub_a_strategy_new_suba_from_scratch_proxy_extended_layer4_target_vol_target_vol_window_max_leverage/`
- Layer 5: `quant_param_scan_runs/20260614_a_share_new_sub_a_strategy_new_suba_from_scratch_proxy_extended_layer5_static_defense_and_momentum_decay_nav_drawdown_defense_score_peak_decay/`
- Layer 6: `quant_param_scan_runs/20260614_a_share_new_sub_a_strategy_new_suba_from_scratch_proxy_extended_layer6_three_overheat_bias_score_vol_overheat/`
- Layer 7: `quant_param_scan_runs/20260614_a_share_new_sub_a_strategy_new_suba_from_scratch_proxy_extended_layer7_entry_staging_initial_half_then_first_down_day_add/`
- Layer 8: `quant_param_scan_runs/20260614_a_share_new_sub_a_strategy_new_suba_from_scratch_proxy_extended_layer8_volume_amount_cyb_amount_contraction/`

## Verification

- Layer 8 strict artifact checker: PASS.
- Layer 8 runner compile check: PASS.
- `git diff --check`: PASS with an existing LF-to-CRLF warning on `docs/new_strategy_test_standard_process.md`.

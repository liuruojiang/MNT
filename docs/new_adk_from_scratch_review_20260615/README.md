# 7.7 ADK From-Scratch Retest Record

Date: 2026-06-15

## Scope

This records the from-scratch ADK retest that treated V7.7 ADK as reference only. The test followed `docs/new_strategy_test_standard_process.md` layer by layer. The final volume/amount layer was skipped by user decision; V7.7 ADK amount/volume is warning-only and does not change ADK position or NAV.

Long-sample caveat: the extended sample starts from 2011-05-03, but any ZZ1000-dependent window before the formal ZZ1000 publication date, 2014-10-17, is proxy research rather than formal publication-window evidence.

## Final Carried Lines

| line | parameters |
|---|---|
| New ADK primary | all 10 pairs; MA60/20 bias-slope momentum; no R2; no score/absolute-momentum gate; target vol 14%, window 40, max leverage 1.5, min leverage 0.1, scale-change threshold 0.25; score overheat enter 80 / exit 20 / scale 0 |
| New ADK soft confirmation | same as primary, but score overheat scale 0.25 |
| New ADK official-8 confirmation | official 8-pair pool; same TV14 and score-overheat settings as primary |
| New ADK return watch | all 10 pairs; TV20/window40/max1.5/scale threshold 0; score overheat enter 80 / exit 20 / scale 0 |
| V7.7 ADK reference | official 8-pair pool; MA60/20 bias momentum; R2 threshold 0.05; target vol 14%, window 40, max leverage 1.5, min leverage 0.1, scale-change threshold 0.25; same-side bias overheat 22% / 18% / scale 0; score decay off; risk gate off; amount warning only |

## Layer Decisions

| layer | tested item | decision |
|---|---|---|
| 1 | Raw momentum signal and width | Use MA60 + 20-day bias-slope momentum with 1->10 recency weight. All-10 pool was stronger than official-8 for the new branch. |
| 2 | R2 quality | Rejected. Width pass count was 0. |
| 3 | Score threshold and directional absolute momentum threshold | Rejected. Width pass count was 0. |
| 4 | Target volatility | Passed. Defensive main line moved to TV14/window40/max1.5/threshold0.25; TV20/window40/max1.5/threshold0 retained as return watch. |
| 5 | NAV drawdown defense | Rejected for primary and return-watch lines. Low-leverage diagnostic only. |
| 6 | Pair score decay | Rejected for primary and return-watch lines. Low-leverage diagnostic only. |
| 7 | Overheat: bias, score, volatility | Promoted score overheat for primary. Primary score-overheat patch had 14 connected passing points around enter 60-80, exit 20-60, scale 0-0.75. Bias and volatility were not promoted for the primary. |
| 8 | First entry half, add after first down day | Rejected. Width pass count was 0. |
| 9 | Volume/amount | Skipped by user decision. |

## Performance Comparison

Annualized return / max drawdown:

| strategy | full sample | last 10Y | last 5Y | last 3Y | last 1Y |
|---|---:|---:|---:|---:|---:|
| New ADK primary: all10 TV14 + score overheat | 19.56% / -17.66% | 21.77% / -17.24% | 22.56% / -16.23% | 22.33% / -16.23% | 29.20% / -16.23% |
| New ADK soft: score overheat scale 0.25 | 19.55% / -17.36% | 21.27% / -17.24% | 22.31% / -16.23% | 21.84% / -16.23% | 27.07% / -16.23% |
| New ADK official-8 confirmation | 19.08% / -17.79% | 21.15% / -17.24% | 22.50% / -14.57% | 23.10% / -14.57% | 31.52% / -14.57% |
| New ADK return watch: all10 TV20 + score overheat | 26.03% / -23.16% | 28.64% / -21.69% | 28.22% / -20.78% | 25.83% / -20.78% | 34.59% / -20.78% |
| V7.7 ADK full reference | 20.16% / -20.24% | 20.47% / -15.49% | 23.88% / -14.05% | 25.34% / -14.05% | 24.11% / -14.05% |

## Interpretation

The new ADK primary is not a clean replacement for V7.7 ADK. It improves full-sample drawdown and has stronger 10Y and 1Y return, while V7.7 remains stronger on 5Y/3Y return and recent-window drawdown.

The main research value is negative filtering evidence: R2, score/absolute-momentum gates, NAV defense, pair score decay, and entry staging all failed the width standard on the new branch. The only promoted later-layer overlay was active-pair score overheat.

The score-overheat result should not be read as a contradiction of V7.7 bias overheat. By Layer 7, the new branch and V7.7 reference are no longer the same base: the new branch uses all 10 pairs and does not carry R2, while V7.7 uses official 8 pairs and R2 threshold 0.05. Score overheat measures active-pair momentum slope intensity; bias overheat measures active-pair distance from MA60 and requires same-side direction.

## 50/50 Combination Check

After the Sub-B post-layer combination check, the ADK primary was also tested as a complement to the V7.7 ADK original:

- 50% `New ADK primary: all10 TV14 + score overheat`
- 50% `V7.7 ADK full reference`

Metrics use the Layer 8 daily outputs with the same report convention as the scan: first date is the base NAV date, and annualization is based on the actual date span.

| strategy | full sample | last 10Y | last 5Y | last 3Y | last 1Y |
|---|---:|---:|---:|---:|---:|
| New ADK primary | 19.56% / -17.66% | 21.77% / -17.24% | 22.56% / -16.23% | 22.33% / -16.23% | 29.20% / -16.23% |
| V7.7 ADK full reference | 20.16% / -20.24% | 20.47% / -15.49% | 23.88% / -14.05% | 25.34% / -14.05% | 24.11% / -14.05% |
| 50% New ADK primary + 50% V7.7 ADK | 19.92% / -16.38% | 21.15% / -16.36% | 23.25% / -15.02% | 23.87% / -15.02% | 26.65% / -15.02% |

Correlation to V7.7 ADK:

| object | full sample | last 10Y | last 5Y | last 3Y | last 1Y |
|---|---:|---:|---:|---:|---:|
| New ADK primary vs V7.7 ADK | 0.924 | 0.957 | 0.962 | 0.950 | 0.971 |
| 50/50 combo vs V7.7 ADK | 0.982 | 0.990 | 0.991 | 0.988 | 0.993 |

The 50/50 blend improves full-sample max drawdown versus both standalone lines, but its return is close to the midpoint and the correlation to V7.7 ADK becomes very high.

## Evidence Artifacts

- Layer 1 all-10 raw momentum: `quant_param_scan_runs/20260614_a_share_new_adk_strategy_new_adk_from_scratch_proxy_extended_layer1_raw_momentum_signal_and_width`
- Layer 1 official-8 raw momentum: `quant_param_scan_runs/20260614_a_share_new_adk_strategy_new_adk_from_scratch_proxy_extended_layer1_raw_momentum_official8_pair_pool_signal_and_width`
- Layer 2 R2: `quant_param_scan_runs/20260614_a_share_new_adk_strategy_new_adk_from_scratch_proxy_extended_layer2_r2_quality_r2_window_threshold`
- Layer 3 score/absolute momentum: `quant_param_scan_runs/20260614_a_share_new_adk_strategy_new_adk_from_scratch_proxy_extended_layer3_score_abs_momentum_filter_score_threshold_abs_momentum_threshold`
- Layer 4 target vol: `quant_param_scan_runs/20260614_a_share_new_adk_strategy_new_adk_from_scratch_proxy_extended_layer4_target_vol_target_vol_window_max_leverage_scale_threshold`
- Layer 5 NAV defense: `quant_param_scan_runs/20260614_a_share_new_adk_strategy_new_adk_from_scratch_proxy_extended_layer5_nav_drawdown_defense_nav_drawdown_enter_exit_defense_scale`
- Layer 6 pair score decay: `quant_param_scan_runs/20260614_a_share_new_adk_strategy_new_adk_from_scratch_proxy_extended_layer6_pair_score_decay_pair_score_decay_recovery_derisk_scale`
- Layer 7 overheat: `quant_param_scan_runs/20260615_a_share_new_adk_strategy_new_adk_from_scratch_proxy_extended_layer7_overheat_bias_score_vol_bias_score_vol_overheat_enter_exit_derisk`
- Layer 8 entry staging: `quant_param_scan_runs/20260615_a_share_new_adk_strategy_new_adk_from_scratch_proxy_extended_layer8_entry_staging_initial_half_then_first_down_day_add`

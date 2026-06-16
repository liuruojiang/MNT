# V7.8 Candidate Version Spec - 2026-06-15

## Status

Research candidate specification only. Do not treat this file as a production implementation.

V7.8 is defined as a 7.7-style extension of the A, ADK, and B sleeves. The implementation must start from `mnt_bot V 7.7 plus.py` and preserve the V7.7 query and display style unless a displayed rule has actually changed.

Local file check on 2026-06-15 found `mnt_bot V 7.0 plus.py` through `mnt_bot V 7.7 plus.py`, with no separate `mnt_bot V 7.7.7 plus.py` file in this workspace. If "7.7.7" refers to the latest finalized 7.7 operating style, the executable implementation anchor is therefore `mnt_bot V 7.7 plus.py`; do not rebuild query text from scratch.

## Query Parity Requirements

The following query surfaces must remain structurally consistent with V7.7:

- `_handle_signal`
- `_handle_live_signal`
- `_handle_params`
- `_handle_live_params`
- `_handle_signal_history`
- Performance/monthly display sections that expose Sub-A, Sub-A-DK, Sub-B, Sub-C, Microcap, Sub-D, and Combined.

Before any V7.8 code promotion, each of the above handlers must be diff-reviewed against `mnt_bot V 7.7 plus.py`. The goal is style parity with V7.7: same section order, same table rhythm, same naming conventions, and only the minimum extra rows needed to show V7.8's mixed-leg composition.

For every V7.8 sleeve mix, displays must expose:

- original V7.7 component weight
- new component weight
- each component's current target asset or pair
- each component's raw scale / target-vol scale / overlay scale where applicable
- final blended execution weight
- the original V7.7 rule labels retained from `mnt_bot V 7.7 plus.py`

Do not introduce a new query layout unless it is required to show the new mixed-leg composition. Any added row should follow the V7.7 table and wording style.

## Sleeve Definitions

### Sub-A

Use the selected 50/50 blend:

- 50% V7.7 Sub-A original
- 50% New A TV1.0 line

New A TV1.0 line:

- candidate: `tv30_w80_max1p0_base`
- raw signal: bias-slope, MA40 / momentum 20 / weight_end 3.0
- filters: score >= 10 / 10000 and abs20 > 2%
- target vol: 30%, window 80, max leverage 1.0
- no Layer 5 NAV/static defense
- no Layer 6 overheat
- no Layer 7 entry staging
- no Layer 8 amount overlay

Reference result from the proxy-extended research panel:

| strategy | full | 10Y | 5Y | 3Y | 1Y |
|---|---:|---:|---:|---:|---:|
| V7.7A original | 25.67% / -29.59% | 25.89% / -22.92% | 29.32% / -19.11% | 49.23% / -16.02% | 105.15% / -10.64% |
| New A TV1.0 | 22.14% / -20.30% | 13.78% / -20.30% | 18.06% / -13.43% | 26.00% / -13.43% | 50.07% / -7.81% |
| 50% New A TV1.0 + 50% V7.7A | 24.19% / -24.00% | 19.91% / -21.18% | 23.80% / -13.21% | 37.40% / -13.21% | 75.92% / -8.44% |

### Sub-A-DK / ADK

Use the selected 50/50 blend:

- 50% V7.7 ADK original
- 50% New ADK primary

New ADK primary:

- all 10 pairs
- MA60/20 bias-slope momentum
- no R2
- no score/absolute momentum gate
- target vol 14%, window 40, max leverage 1.5, min leverage 0.1, scale-change threshold 0.25
- score overheat enter 80 / exit 20 / scale 0
- no entry staging
- volume/amount layer skipped

Reference result from the proxy-extended research panel:

| strategy | full | 10Y | 5Y | 3Y | 1Y |
|---|---:|---:|---:|---:|---:|
| New ADK primary | 19.56% / -17.66% | 21.77% / -17.24% | 22.56% / -16.23% | 22.33% / -16.23% | 29.20% / -16.23% |
| V7.7 ADK full reference | 20.16% / -20.24% | 20.47% / -15.49% | 23.88% / -14.05% | 25.34% / -14.05% | 24.11% / -14.05% |
| 50% New ADK primary + 50% V7.7 ADK | 19.92% / -16.38% | 21.15% / -16.36% | 23.25% / -15.02% | 23.87% / -15.02% | 26.65% / -15.02% |

### Sub-B

Use the selected four-bottom-line equal blend:

- 50% V7.7 Sub-B original
- 25% New B bias-level line
- 25% New B log-weighted overheat line

Because V7.7 Sub-B original is itself a 50/50 official/EMA blend, this is equivalent to four bottom-level lines at 25% each.

New B bias-level line:

- `bias_level_window_target_lbs160_260_390_recent_3_2_1__tv0p25_w40_max1p5__entry_f0p5_down0_waitnone__spyvol_high_w60_thr1p5_d1_eqs0p75`

New B log-overheat line:

- `log_momentum_weighted_signal_lbs120_200_320_recent_60_30_10__tv0p3_w40_max1p25__vol_w20_e0p5_x0p22_s0p75__spyvol_high_w60_thr1p5_d1_eqs0p75`

SPY volume rule for both new B lines:

- signal: `SPY volume / SPY MA60 >= 1.5`
- T close signal applies to T+1 adjusted open
- scale only `QQQ`, `EMXC`, and `EFA` to 75%; non-equity assets unchanged; residual to `BIL`

Reference result from the proxy-extended research panel:

| strategy | full | 10Y | 5Y | 3Y | 1Y |
|---|---:|---:|---:|---:|---:|
| V7.7B original | 20.07% / -17.33% | 32.05% / -12.31% | 29.76% / -12.31% | 40.09% / -11.03% | 53.44% / -10.56% |
| V7.7B 50% + Bias 25% + LogW overheat 25% | 24.99% / -14.10% | 39.27% / -12.58% | 33.06% / -12.58% | 45.49% / -10.56% | 56.38% / -8.90% |

## Implementation Notes

- The V7.8 script should be created as a copy of `mnt_bot V 7.7 plus.py`, not as a fresh rewrite.
- Keep V7.7 data loaders, cost paths, calendars, execution timing, asset labels, and query text style.
- Add mixed-leg output columns instead of replacing original columns blindly. The signal and parameter queries must show both component and final blended targets.
- Formal production review still needs a no-pre-publication-backfill pass. The above long-window results are proxy research where REDLOW100, ZZ1000, ZZ500, and CSI2000-related history require caution.

## Evidence Artifacts

- A strategy record: `docs/new_suba_from_scratch_review_20260614/record.md`
- ADK strategy record: `docs/new_adk_from_scratch_review_20260615/README.md`
- B strategy Layer8 record: `quant_param_scan_runs/20260615_a_share_us_momentum_combo_new_subb_from_scratch_proxy_extended_layer8_spy_volume_equity_only_spy_volume_gate_equity_assets_only_layer7_carry/record.md`

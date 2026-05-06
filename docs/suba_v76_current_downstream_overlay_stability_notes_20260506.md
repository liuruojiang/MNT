# Sub-A V7.6 Current Downstream Overlay Stability Notes - 2026-05-06

## Validity

- This document uses current root `mnt_bot V 7.6 plus.py`.
- No strategy parameters were changed for these runs.
- The position-scaling candidate `CN_TARGET_VOL=0.25`, `CN_VOL_WINDOW=120`, `CN_SCALE_THRESHOLD=0.15` was not applied here. These overlay scans use the current V7.6 baseline in the script.
- Data audit: `2010-06-01` to `2026-04-30`, `3865` rows, duplicate dates `0`.
- Recent-weighted Sharpe score = 1Y 15% + 3Y 35% + 5Y 35% + 10Y 15%.

## Evidence

| Group | Evidence path | Variants |
|---|---|---:|
| Cash overlay | `docs/suba_v76_current_stability_A_cash_overlay_20260506/` | 42 |
| Same-side overheat overlay | `docs/suba_v76_current_stability_A_overheat_20260506/` | 31 |
| Volume overlay | `docs/suba_v76_current_stability_A_volume_20260506/` | 33 |

Commands:

```powershell
python 'analyze_suba_v76_cash_overlay_stability.py' --script 'mnt_bot V 7.6 plus.py' --out-dir 'docs\suba_v76_current_stability_A_cash_overlay_20260506' --decays '0.45,0.50,0.55,0.60,0.65,0.70' --recoveries '0.70,0.75,0.80,0.85,0.90,0.95,1.00' --include-off
python 'analyze_suba_v76_overheat_stability.py' --script 'mnt_bot V 7.6 plus.py' --out-dir 'docs\suba_v76_current_stability_A_overheat_20260506' --enters '0.28,0.32,0.36,0.40,0.44' --exit-gaps '0.02,0.04' --derisk-scales '0,0.25,0.50' --include-off
python 'analyze_suba_v76_volume_stability.py' --script 'mnt_bot V 7.6 plus.py' --out-dir 'docs\suba_v76_current_stability_A_volume_20260506'
```

## 5. Cash Overlay

Baseline/default: `CN_SA_CASH_OVERLAY_DECAY_RATIO=0.55`, `CN_SA_CASH_OVERLAY_RECOVERY_RATIO=0.90`.

| Case | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe | 10Y triggers | 10Y overlay days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Best: `0.50 / 1.00` | 2.078 | 52.71% | -25.26% | 29.19% | -25.26% | 1.458 | 37 | 134 |
| Conservative best: `0.55 / 1.00` | 2.078 | 52.12% | -19.16% | 30.40% | -19.16% | 1.532 | 47 | 173 |
| Default: `0.55 / 0.90` | 2.076 | 52.08% | -19.16% | 30.25% | -19.16% | 1.525 | 48 | 169 |
| Cash overlay off | 1.838 | 47.94% | -23.59% | 28.99% | -23.59% | 1.415 | 0 | 0 |

Readout: cash overlay remains useful. The absolute Sharpe top `0.50/1.00` has much deeper worst recent MaxDD, so it is not a clean default candidate. Current default `0.55/0.90` stays inside the top plateau and preserves the drawdown profile.

## 6. Same-Side Overheat Overlay

Baseline/default: `CN_SA_SAME_SIDE_OVERHEAT_ENTER=0.36`, `CN_SA_SAME_SIDE_OVERHEAT_EXIT=0.34`, `CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE=0.0`.

| Case | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe | 10Y triggers | 10Y overlay days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Best: `0.28 / 0.24 / 0.00` | 2.116 | 52.78% | -19.16% | 31.08% | -19.16% | 1.565 | 3 | 12 |
| `0.28 / 0.26 / 0.00` | 2.111 | 52.68% | -19.16% | 31.02% | -19.16% | 1.563 | 3 | 11 |
| Default: `0.36 / 0.34 / 0.00` | 2.076 | 52.08% | -19.16% | 30.25% | -19.16% | 1.525 | 1 | 2 |
| Overheat overlay off | 2.076 | 52.08% | -19.16% | 30.25% | -19.16% | 1.525 | 0 | 0 |

Readout: the top-ranked lower threshold `0.28` improves the tested window, but only triggers 3 times over 10Y. Default `0.36/0.34/0` is effectively identical to overlay-off in recent metrics because it almost never triggers. Treat this as a low-frequency insurance layer; do not change it solely from this sparse trigger count.

## 7. Volume Overlay

Current baseline/default has `CN_SA_VOLUME_SCALE=0.25`, old-rule `ZZ2000 MA15 / 3 days OR CYB MA10 / 3 days`, clear-rule `ratio MA30 / 15 days`, and `clear_scale=0.0`.

| Case | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe | 10Y old signal days | 10Y clear signal days | 10Y overlay days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Best: `cyb_ma15_d5` | 2.154 | 56.26% | -17.41% | 33.46% | -17.41% | 1.614 | 976 | 183 | 1065 |
| `cyb_ma15_d3` | 2.122 | 54.15% | -17.91% | 31.19% | -17.91% | 1.562 | 1101 | 183 | 1181 |
| `cyb_ma10_d5` | 2.105 | 54.99% | -17.41% | 31.65% | -17.41% | 1.534 | 955 | 183 | 1045 |
| Default / `old_scale_0.25` | 2.076 | 52.08% | -19.16% | 30.25% | -19.16% | 1.525 | 1107 | 183 | 1186 |
| `old_scale_0.50` | 1.992 | 51.85% | -20.19% | 30.18% | -20.19% | 1.475 | 1107 | 183 | 1186 |
| Volume overlay off | 1.529 | 48.84% | -29.99% | 25.43% | -29.99% | 1.111 | 0 | 0 | 0 |

Readout: volume overlay is clearly valuable. Current default with `CN_SA_VOLUME_SCALE=0.25` remains much better than `0.50` and much better than overlay-off. `cyb_ma15_d5` is the strongest tested case, but it changes trigger shape/frequency and should be treated as a candidate for later confirmation rather than a default change during this baseline pass.

## Current Decisions

- Do not change V7.6 baseline during testing.
- Keep cash overlay default for now: `0.55 / 0.90`.
- Keep overheat default for now: `0.36 / 0.34 / 0.0`; evidence is too sparse to justify tuning.
- Keep current volume baseline for now: `CN_SA_VOLUME_SCALE=0.25`; record `cyb_ma15_d5` as a later candidate.
- Keep position-scaling `0.25 / 120 / 0.15` as a later candidate only, not applied in this downstream overlay pass.


# Sub-A V7.5 vs Current V7.6 Parameter Stability Compare - 2026-05-06

## Validity

- This document compares current `mnt_bot V 7.5 plus.py` against current root `mnt_bot V 7.6 plus.py`.
- Old `docs/suba_v76_stability_A_*_20260506/` artifacts are not used as comparison evidence here.
- Current V7.6 was rerun into `docs/suba_v76_current_stability_A_*_20260506/`.
- Recent-weighted Sharpe score = 1Y 15% + 3Y 35% + 5Y 35% + 10Y 15%.

## Run Evidence

| Group | V7.5 evidence | Current V7.6 evidence | Variants |
|---|---|---|---:|
| MA / slope | `docs/suba_v75_stability_A_ma_slope_20260506/` | `docs/suba_v76_current_stability_A_ma_slope_20260506/` | 25 / 25 |
| R2 | `docs/suba_v75_stability_A_r2_20260506/` | `docs/suba_v76_current_stability_A_r2_20260506/` | 24 / 24 |
| Execution | `docs/suba_v75_stability_A_execution_20260506/` | `docs/suba_v76_current_stability_A_execution_20260506/` | 24 / 24 |
| Position scaling | `docs/suba_v75_stability_A_position_scaling_20260506/` | `docs/suba_v76_current_stability_A_position_scaling_20260506/` | 100 / 100 |

Data audit for both current-code runs: `2010-06-01` to `2026-04-30`, `3865` rows, duplicate dates `0`. Symbols: `1.H20955`, `0.399606`, `1.H00016`, `1.H00852`, `1.H00905`, `1.H11077`.

Current V7.6 rerun commands:

```powershell
python '.codex_backups\20260506_021359\analyze_suba_ma_slope_grid.py' --script 'mnt_bot V 7.6 plus.py' --out-dir 'docs\suba_v76_current_stability_A_ma_slope_20260506' --ma-start 40 --ma-end 80 --ma-step 10 --slope-start 10 --slope-end 30 --slope-step 5
python '.codex_backups\20260506_021359\analyze_suba_r2_layer_scan.py' --script 'mnt_bot V 7.6 plus.py' --out-dir 'docs\suba_v76_current_stability_A_r2_20260506' --pairs '60:20' --r2-windows '10,15,20,30' --r2-thresholds '0,0.1,0.2,0.3,0.4,0.5' --modes 'formal'
python '.codex_backups\20260506_021359\analyze_suba_execution_layer_scan.py' --script 'mnt_bot V 7.6 plus.py' --out-dir 'docs\suba_v76_current_stability_A_execution_20260506' --combos '60:20:20:0.2' --buffers '1.00,1.03,1.06,1.10' --entry-fractions '0.5,1.0' --wait-days 'none,0,3,5,10' --modes 'formal'
python '.codex_backups\20260506_021359\analyze_suba_position_scaling_scan.py' --script 'mnt_bot V 7.6 plus.py' --out-dir 'docs\suba_v76_current_stability_A_position_scaling_20260506' --combos '60:20:20:0.2:1.03:0.5:none' --target-vols '0.20,0.25,0.30,0.35,0.40' --vol-windows '40,60,80,100,120' --scale-thresholds '0,0.05,0.10,0.15' --modes 'formal'
```

Important code-state differences visible in the root scripts:

| Parameter | V7.5 | Current V7.6 |
|---|---:|---:|
| `CN_R2_THRESHOLD` | 0.30 | 0.20 |
| `CN_SWITCH_BUFFER` | 1.06 | 1.03 |
| `CN_TARGET_VOL` | 0.20 | 0.30 |
| `CN_VOL_WINDOW` | 60 | 80 |
| `CN_SCALE_THRESHOLD` | 0.15 | 0.00 |
| `CN_SA_VOLUME_SCALE` | 0.50 | 0.25 |

## Overall Conclusion

Current V7.6 is not equal to V7.5, and the old "position-scaling ties exactly" conclusion is false for current code. Under the four rerun grids, current V7.6 is generally stronger on recent-weighted Sharpe and 10Y CAGR, while drawdown is mixed but not worse enough to overturn the result:

| Group | Best point V7.5 | Best point current V7.6 | Stability readout |
|---|---|---|---|
| MA / slope | `60 / 20` | `60 / 20` | Same winner; V7.6 stronger return, slightly deeper DD at default |
| R2 | `20 / 0.20` | `20 / 0.20` | Same winner; V7.6 broader near-top plateau |
| Execution | `1.06 / 0.5 / 3` | `1.03 / 0.5 / 3` | Same practical plateau: half-entry, buffer `1.03-1.06`, wait `None/3/5/10` |
| Position scaling | `0.25 / 120 / 0.15` | `0.25 / 120 / 0.15` | Same winner; V7.6 materially higher score, full grid remains broad |

## 1. MA / Slope

| Version | Best point | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD |
|---|---|---:|---:|---:|---:|---:|
| V7.5 | `60 / 20` | 1.915 | 45.04% | -17.89% | 25.58% | -17.89% |
| Current V7.6 | `60 / 20` | 2.076 | 52.08% | -19.16% | 30.25% | -19.16% |

Same-parameter checks:

| Point | V7.5 Sharpe | V7.6 Sharpe | Delta | V7.5 10Y CAGR | V7.6 10Y CAGR | V7.5 10Y DD | V7.6 10Y DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `60 / 20` | 1.915 | 2.076 | +0.161 | 25.58% | 30.25% | -17.89% | -19.16% |
| `50 / 20` | 1.718 | 1.888 | +0.170 | 22.02% | 26.10% | -21.54% | -30.13% |
| `60 / 25` | 1.582 | 1.807 | +0.225 | 22.18% | 26.64% | -31.16% | -30.95% |
| `70 / 20` | 1.529 | 1.753 | +0.224 | 20.67% | 25.36% | -22.75% | -20.46% |

Readout: `60 / 20` remains the clean cross-version core setting. Current V7.6 lifts return and Sharpe, but some neighboring MA points have meaningfully deeper drawdown, especially `50 / 20`.

## 2. R2

| Version | Best point | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD |
|---|---|---:|---:|---:|---:|---:|
| V7.5 | `20 / 0.20` | 2.025 | 48.76% | -19.85% | 27.07% | -19.85% |
| Current V7.6 | `20 / 0.20` | 2.076 | 52.08% | -19.16% | 30.25% | -19.16% |

Same-parameter checks:

| Point | V7.5 Sharpe | V7.6 Sharpe | Delta | V7.5 10Y CAGR | V7.6 10Y CAGR | V7.5 10Y DD | V7.6 10Y DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `20 / 0.20` | 2.025 | 2.076 | +0.051 | 27.07% | 30.25% | -19.85% | -19.16% |
| `20 / 0.10` | 1.940 | 2.040 | +0.100 | 26.79% | 29.73% | -22.92% | -21.72% |
| `20 / 0.30` | 1.915 | 1.995 | +0.080 | 25.58% | 28.21% | -17.89% | -17.56% |
| `15 / 0.30` | 1.784 | 1.934 | +0.150 | 17.99% | 22.46% | -31.35% | -28.42% |

Stability counts by recent-weighted Sharpe:

| Version | Median | Std | Within 99% of best | Within 95% of best | Within 90% of best |
|---|---:|---:|---:|---:|---:|
| V7.5 | 1.669 | 0.203 | 1 / 24 | 2 / 24 | 3 / 24 |
| Current V7.6 | 1.773 | 0.203 | 1 / 24 | 3 / 24 | 4 / 24 |

Readout: `20 / 0.20` is confirmed as the best R2 point in both versions. V7.6's current default is on the best point; V7.5's historical `20 / 0.30` remains a drawdown-control point, not the Sharpe winner.

## 3. Execution Layer

| Version | Best point | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD |
|---|---|---:|---:|---:|---:|---:|
| V7.5 | `1.06 / 0.5 / 3` | 2.034 | 48.93% | -19.88% | 27.20% | -19.88% |
| Current V7.6 | `1.03 / 0.5 / 3` | 2.084 | 52.26% | -19.19% | 30.34% | -19.19% |

Top plateau same-parameter checks:

| Point | V7.5 Sharpe | V7.6 Sharpe | Delta | V7.5 10Y CAGR | V7.6 10Y CAGR | V7.5 10Y DD | V7.6 10Y DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `1.06 / 0.5 / 3` | 2.034 | 2.083 | +0.049 | 27.20% | 30.18% | -19.88% | -19.19% |
| `1.03 / 0.5 / 3` | 2.029 | 2.084 | +0.054 | 27.32% | 30.34% | -19.88% | -19.19% |
| `1.06 / 0.5 / None` | 2.025 | 2.075 | +0.050 | 27.07% | 30.09% | -19.85% | -19.16% |
| `1.03 / 0.5 / None` | 2.021 | 2.076 | +0.055 | 27.20% | 30.25% | -19.85% | -19.16% |

Stability counts by recent-weighted Sharpe:

| Version | Median | Std | Within 99% of best | Within 95% of best | Within 90% of best |
|---|---:|---:|---:|---:|---:|
| V7.5 | 1.966 | 0.114 | 8 / 24 | 16 / 24 | 16 / 24 |
| Current V7.6 | 2.018 | 0.111 | 8 / 24 | 16 / 24 | 18 / 24 |

Readout: execution parameters are stable in both versions. The practical default region is still half-entry with `buffer=1.03-1.06`; `wait=3` ranks first, but `None/5/10` are effectively in the same plateau.

## 4. Position Scaling

| Version | Best point | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD |
|---|---|---:|---:|---:|---:|---:|
| V7.5 | `0.25 / 120 / 0.15` | 2.057 | 51.03% | -17.94% | 27.34% | -17.94% |
| Current V7.6 | `0.25 / 120 / 0.15` | 2.118 | 51.22% | -17.88% | 28.58% | -17.88% |

Same-parameter checks:

| Point | V7.5 Sharpe | V7.6 Sharpe | Delta | V7.5 10Y CAGR | V7.6 10Y CAGR | V7.5 10Y DD | V7.6 10Y DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `0.25 / 120 / 0.15` | 2.057 | 2.118 | +0.061 | 27.34% | 28.58% | -17.94% | -17.88% |
| `0.25 / 100 / 0.15` | 2.035 | 2.103 | +0.069 | 26.99% | 28.31% | -19.16% | -19.16% |
| `0.25 / 120 / 0.05` | 2.030 | 2.091 | +0.062 | 28.56% | 29.71% | -19.85% | -19.16% |
| `0.30 / 120 / 0.10` | 2.007 | 2.108 | +0.100 | 29.38% | 29.37% | -19.43% | -17.97% |

Stability counts by recent-weighted Sharpe:

| Version | Median | Std | Within 99% of best | Within 95% of best | Within 90% of best |
|---|---:|---:|---:|---:|---:|
| V7.5 | 2.009 | 0.014 | 1 / 100 | 100 / 100 | 100 / 100 |
| Current V7.6 | 2.082 | 0.015 | 8 / 100 | 100 / 100 | 100 / 100 |

Readout: this is the group where the previous old-doc comparison was most misleading. Current V7.6 does not tie V7.5; it improves the whole surface. The same best point remains `0.25 / 120 / 0.15`, while the current V7.6 default-style `0.30 / 80 / 0.00` is still competitive but not the top of this grid.

## Final Interpretation

Measured from current-code reruns only:

- Keep `CN_BIAS_N=60`, `CN_MOM_DAY=20`.
- Use `CN_R2_WINDOW=20`, `CN_R2_THRESHOLD=0.20` if optimizing Sharpe/return. `0.30` is the defensive alternative.
- Keep half-entry. `CN_SWITCH_BUFFER=1.03` is now slightly better in current V7.6, but `1.06` is still inside the same plateau.
- Position scaling winner in both versions is `CN_TARGET_VOL=0.25`, `CN_VOL_WINDOW=120`, `CN_SCALE_THRESHOLD=0.15` by recent-weighted Sharpe and drawdown balance. Record it as a V7.6 candidate default only; do not change the live V7.6 default until the six-group/current-code testing and full-strategy confirmation are complete.
- Current V7.6 is the better current-code baseline across these four grids, mainly because it lifts recent-weighted Sharpe and 10Y CAGR while preserving or improving drawdown in R2, execution, and position-scaling scans.

Residual risks:

- This is a Sub-A parameter stability comparison only. It does not rerun Sub-A-DK, Sub-B, microcap, combo weights, cash overlay, overheat overlay, or volume overlay standalone scans.
- The run uses the repository's existing data loaders and formal overlay stack. Market-friction assumptions are the script defaults, including `CN_COMMISSION=0.001`, daily close-to-close execution, vol scaling shifted by one bar, and enabled cash/same-side-overheat/volume overlays.
- V7.5 audit recorded `0.399606` source as EastMoney while current V7.6 audit recorded it as Sina; both runs use the same date range and row count, but exact vendor parity for that series was not separately audited in this comparison.

# Sub-A V7.5 Parameter Stability Notes - 2026-05-06

## Current Validity Note

- 2026-05-08 follow-up: current `mnt_bot V 7.5 plus.py` now syncs the Sub-A volume-overlay CYB trigger to `CN_SA_VOLUME_CYB_MA=15`, `CN_SA_VOLUME_CYB_DAYS=5`, matching the V7.6 follow-up default.
- The V7.5 runs recorded in this document predate that 2026-05-08 CYB trigger sync. Treat their numeric rows as historical scan evidence for the stated fixed-parameter designs, not as a fresh current-code rerun.
- The V7.6 comparison rows copied from existing `docs/suba_v76_stability_A_*_20260506/` artifacts should be treated as historical-document comparisons, not final comparisons against the current `mnt_bot V 7.6 plus.py`.
- Reason: the current root `mnt_bot V 7.6 plus.py` differs from those V7.6 artifacts in at least one formal-overlay parameter not recorded in the old V7.6 audits: `CN_SA_VOLUME_SCALE=0.25` currently, while the old full-grid artifacts behave like the earlier volume-overlay scale. A current-code spot-check under position scaling produced different results from the existing V7.6 document.
- Therefore, cross-version stability conclusions for groups 1-4 below are superseded by the current-code rerun report: `docs/suba_v75_vs_v76_current_parameter_stability_compare_20260506.md`.

## Confirmed

### 1. `CN_BIAS_N / CN_MOM_DAY`

- Checked values: `CN_BIAS_N` in `40,50,60,70,80`; `CN_MOM_DAY` in `10,15,20,25,30`.
- Baseline/default: `CN_BIAS_N=60`, `CN_MOM_DAY=20`.
- Evidence path: `docs/suba_v75_stability_A_ma_slope_20260506/`.
- Comparison baseline: `docs/suba_v76_stability_A_ma_slope_20260506/`.
- Audit: target script `mnt_bot V 7.5 plus.py`; formal Sub-A path; data `2010-06-01` to `2026-04-30`; rows `3865`; duplicate dates `0`; fast-indicator parity max diffs all `0.0`.
- Fixed V7.5 formal parameters: `CN_R2_WINDOW=20`, `CN_R2_THRESHOLD=0.30`, `CN_TARGET_VOL=0.20`, `CN_SWITCH_BUFFER=1.06`, `CN_ENTRY_INITIAL_FRACTION=0.5`, `CN_SCALE_THRESHOLD=0.15`; cash, same-side overheat, and volume overlays all enabled.
- Decision: V7.5 and V7.6 both rank `60/20` first, so the core MA/slope default is directionally stable across versions. V7.5's surface is less profitable than V7.6 at the same default, but has shallower worst recent drawdown because V7.5 still uses the more defensive downstream defaults.

V7.5 top results:

| Rank | `CN_BIAS_N` | `CN_MOM_DAY` | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 20 | 1.915 | 45.04% | -17.89% | 25.58% | -17.89% | 1.399 |
| 2 | 50 | 20 | 1.718 | 40.28% | -21.54% | 22.02% | -21.54% | 1.245 |
| 3 | 50 | 25 | 1.641 | 36.61% | -27.43% | 23.19% | -27.43% | 1.261 |
| 4 | 60 | 25 | 1.582 | 35.62% | -31.16% | 22.18% | -31.16% | 1.208 |
| 5 | 80 | 20 | 1.569 | 36.29% | -27.51% | 20.55% | -27.51% | 1.152 |
| 6 | 40 | 25 | 1.529 | 33.27% | -29.95% | 21.87% | -29.95% | 1.215 |
| 7 | 70 | 20 | 1.529 | 35.41% | -22.75% | 20.67% | -22.75% | 1.150 |
| 8 | 40 | 20 | 1.522 | 34.46% | -24.58% | 18.63% | -24.58% | 1.074 |

Same-parameter comparison with V7.6:

| `CN_BIAS_N` | `CN_MOM_DAY` | V7.5 Recent Sharpe | V7.6 Recent Sharpe | V7.5 Mean recent CAGR | V7.6 Mean recent CAGR | V7.5 Worst recent MaxDD | V7.6 Worst recent MaxDD | V7.5 10Y CAGR | V7.6 10Y CAGR |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 60 | 20 | 1.915 | 2.004 | 45.04% | 51.96% | -17.89% | -19.85% | 25.58% | 29.24% |
| 50 | 20 | 1.718 | 1.803 | 40.28% | 47.15% | -21.54% | -31.16% | 22.02% | 24.90% |
| 50 | 25 | 1.641 | 1.677 | 36.61% | 41.37% | -27.43% | -28.98% | 23.19% | 23.83% |
| 60 | 25 | 1.582 | 1.727 | 35.62% | 44.03% | -31.16% | -31.77% | 22.18% | 25.30% |
| 80 | 20 | 1.569 | 1.531 | 36.29% | 41.80% | -27.51% | -26.57% | 20.55% | 22.59% |

Notes:

- The rank leader is identical across versions: `60/20`.
- V7.6 improves the `60/20` default by `+0.089` recent-weighted Sharpe and `+3.67pp` 10Y CAGR, while V7.5 has `1.96pp` shallower 10Y MaxDD.
- Neighbor order is similar, but V7.6 lifts `60/25` above `50/25`; V7.5 keeps `50/25` above `60/25`.
- This test only covers the Sub-A MA/slope group and does not rescan R2, execution, position scaling, cash overlay, overheat overlay, or volume overlay yet.

### 2. `CN_R2_WINDOW / CN_R2_THRESHOLD`

- Checked values: `CN_R2_WINDOW` in `10,15,20,30`; `CN_R2_THRESHOLD` in `0,0.1,0.2,0.3,0.4,0.5`.
- Fixed parameters: `CN_BIAS_N=60`, `CN_MOM_DAY=20`; other V7.5 formal Sub-A defaults preserved.
- V7.5 baseline/default: `CN_R2_WINDOW=20`, `CN_R2_THRESHOLD=0.30`.
- Evidence path: `docs/suba_v75_stability_A_r2_20260506/`.
- Comparison baseline: `docs/suba_v76_stability_A_r2_20260506/`.
- Audit: target script `mnt_bot V 7.5 plus.py`; formal Sub-A path; data `2010-06-01` to `2026-04-30`; rows `3865`; duplicate dates `0`.
- Decision: R2 window `20` is the clear winner in both V7.5 and V7.6. V7.5's current default threshold `0.30` is more defensive but is not the best recent-weighted Sharpe point; the same `20/0.20` promoted in V7.6 is also the best V7.5 point in this same-grid formal scan.

V7.5 top results:

| Rank | `CN_R2_WINDOW` | `CN_R2_THRESHOLD` | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20 | 0.20 | 2.025 | 48.76% | -19.85% | 27.07% | -19.85% | 1.452 |
| 2 | 20 | 0.10 | 1.940 | 50.45% | -22.92% | 26.79% | -22.92% | 1.378 |
| 3 | 20 | 0.30 | 1.915 | 45.04% | -17.89% | 25.58% | -17.89% | 1.399 |
| 4 | 15 | 0.30 | 1.784 | 43.13% | -31.35% | 17.99% | -31.35% | 1.022 |
| 5 | 10 | 0.00 | 1.748 | 50.76% | -27.99% | 24.03% | -27.99% | 1.148 |
| 6 | 15 | 0.00 | 1.748 | 50.76% | -27.99% | 24.03% | -27.99% | 1.148 |
| 7 | 20 | 0.00 | 1.748 | 50.76% | -27.99% | 24.03% | -27.99% | 1.148 |
| 8 | 30 | 0.00 | 1.748 | 50.76% | -27.99% | 24.03% | -27.99% | 1.148 |
| 9 | 15 | 0.10 | 1.724 | 44.20% | -28.91% | 20.01% | -28.91% | 1.061 |
| 10 | 30 | 0.10 | 1.704 | 42.95% | -33.53% | 18.92% | -33.53% | 1.058 |
| 11 | 30 | 0.20 | 1.697 | 37.94% | -27.09% | 17.67% | -27.09% | 1.065 |
| 12 | 20 | 0.40 | 1.683 | 37.36% | -20.11% | 20.81% | -20.11% | 1.230 |

Same-parameter comparison with V7.6:

| `CN_R2_WINDOW` | `CN_R2_THRESHOLD` | V7.5 Recent Sharpe | V7.6 Recent Sharpe | V7.5 Mean recent CAGR | V7.6 Mean recent CAGR | V7.5 Worst recent MaxDD | V7.6 Worst recent MaxDD | V7.5 10Y CAGR | V7.6 10Y CAGR |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | 0.20 | 2.025 | 2.004 | 48.76% | 51.96% | -19.85% | -19.85% | 27.07% | 29.24% |
| 20 | 0.10 | 1.940 | 1.932 | 50.45% | 53.03% | -22.92% | -23.06% | 26.79% | 28.12% |
| 20 | 0.30 | 1.915 | 1.914 | 45.04% | 47.71% | -17.89% | -17.89% | 25.58% | 27.35% |
| 15 | 0.30 | 1.784 | 1.801 | 43.13% | 46.71% | -31.35% | -31.35% | 17.99% | 19.51% |
| 10 | 0.00 | 1.748 | 1.758 | 50.76% | 56.99% | -27.99% | -28.98% | 24.03% | 26.97% |
| 15 | 0.10 | 1.724 | 1.736 | 44.20% | 47.02% | -28.91% | -30.33% | 20.01% | 21.31% |
| 30 | 0.10 | 1.704 | 1.722 | 42.95% | 45.43% | -33.53% | -34.34% | 18.92% | 19.78% |
| 30 | 0.20 | 1.697 | 1.711 | 37.94% | 40.91% | -27.09% | -28.54% | 17.67% | 19.14% |
| 20 | 0.40 | 1.683 | 1.657 | 37.36% | 38.39% | -20.11% | -20.12% | 20.81% | 21.58% |

Stability comparison:

| Metric | V7.5 | V7.6 | Readout |
|---|---:|---:|---|
| Best point | 20 / 0.20 | 20 / 0.20 | Same winner |
| Default point | 20 / 0.30 | 20 / 0.20 | V7.6 default sits on best point |
| Rank 1 to Rank 2 Sharpe gap | 0.085 | 0.073 | V7.6 peak is slightly less isolated |
| Local grid median Sharpe, windows 15/20/30 and thresholds 0.1/0.2/0.3 | 1.724 | 1.736 | V7.6 local region slightly stronger |
| Local grid Sharpe std | 0.171 | 0.153 | V7.6 local region flatter |
| Count within 90% of best, full grid | 3 / 24 | 3 / 24 | Same |
| Count within 80% of best, full grid | 13 / 24 | 14 / 24 | V7.6 slightly broader |

Notes:

- This group is more clearly stable in V7.6 than V7.5 under the same stability definition.
- Both versions strongly prefer `CN_R2_WINDOW=20`; windows `15` and `30` degrade materially once threshold is above `0`.
- Threshold `0.1-0.3` at window `20` is an acceptable plateau in both versions. `0.20` is the best balance point; `0.30` is the more defensive point with shallower drawdown.
- V7.5's historical default `20/0.30` is defensible as a drawdown-control setting, but the formal scan supports V7.6's `20/0.20` as the better default if return and Sharpe are prioritized.

### 3. `CN_SWITCH_BUFFER / CN_ENTRY_INITIAL_FRACTION / CN_ENTRY_WAIT_DAYS`

- Checked values: `CN_SWITCH_BUFFER` in `1.00,1.03,1.06,1.10`; `CN_ENTRY_INITIAL_FRACTION` in `0.5,1.0`; `CN_ENTRY_WAIT_DAYS` in `None,0,3,5,10` for half-entry cases, and `None` for full-entry cases.
- Fixed parameters for same-parameter comparison: `CN_BIAS_N=60`, `CN_MOM_DAY=20`, `CN_R2_WINDOW=20`, `CN_R2_THRESHOLD=0.20`; other formal Sub-A defaults preserved.
- V7.5 script historical execution baseline: `CN_SWITCH_BUFFER=1.06`, `CN_ENTRY_INITIAL_FRACTION=0.5`, `CN_ENTRY_WAIT_DAYS=None`.
- Evidence path: `docs/suba_v75_stability_A_execution_20260506/`.
- Comparison baseline: `docs/suba_v76_stability_A_execution_20260506/`.
- Audit: target script `mnt_bot V 7.5 plus.py`; formal Sub-A path; data `2010-06-01` to `2026-04-30`; rows `3865`; duplicate dates `0`.
- Decision: execution-layer parameters are stable in both versions. The broad stable region is half-entry with `buffer=1.03-1.06` and `wait=None/3/5/10`. Full-entry increases 10Y CAGR but has worse recent-weighted Sharpe and deeper drawdown, so it remains a stress candidate rather than a default.

V7.5 top results:

| Rank | `CN_SWITCH_BUFFER` | `CN_ENTRY_INITIAL_FRACTION` | `CN_ENTRY_WAIT_DAYS` | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | 1.06 | 0.5 | 3 | 2.034 | 48.93% | -19.88% | 27.20% | -19.88% | 1.459 |
| 2 | 1.03 | 0.5 | 3 | 2.029 | 48.57% | -19.88% | 27.32% | -19.88% | 1.466 |
| 3 | 1.06 | 0.5 | 10 | 2.025 | 48.76% | -19.85% | 27.07% | -19.85% | 1.452 |
| 4 | 1.06 | 0.5 | None | 2.025 | 48.76% | -19.85% | 27.07% | -19.85% | 1.452 |
| 5 | 1.06 | 0.5 | 5 | 2.025 | 48.75% | -19.85% | 27.05% | -19.85% | 1.451 |
| 6 | 1.03 | 0.5 | 10 | 2.021 | 48.40% | -19.85% | 27.20% | -19.85% | 1.460 |
| 7 | 1.03 | 0.5 | None | 2.021 | 48.40% | -19.85% | 27.20% | -19.85% | 1.460 |
| 8 | 1.03 | 0.5 | 5 | 2.020 | 48.39% | -19.85% | 27.18% | -19.85% | 1.459 |
| 9 | 1.10 | 0.5 | 3 | 1.982 | 46.84% | -19.88% | 26.73% | -19.88% | 1.437 |
| 10 | 1.10 | 0.5 | 10 | 1.973 | 46.66% | -19.85% | 26.60% | -19.85% | 1.430 |
| 11 | 1.10 | 0.5 | None | 1.973 | 46.66% | -19.85% | 26.60% | -19.85% | 1.430 |
| 12 | 1.10 | 0.5 | 5 | 1.972 | 46.66% | -19.85% | 26.58% | -19.85% | 1.429 |

Same-parameter comparison with V7.6:

| `CN_SWITCH_BUFFER` | `CN_ENTRY_INITIAL_FRACTION` | `CN_ENTRY_WAIT_DAYS` | V7.5 Recent Sharpe | V7.6 Recent Sharpe | V7.5 10Y CAGR | V7.6 10Y CAGR | V7.5 10Y MaxDD | V7.6 10Y MaxDD |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 1.06 | 0.5 | 3 | 2.034 | 2.013 | 27.20% | 29.17% | -19.88% | -19.88% |
| 1.03 | 0.5 | 3 | 2.029 | 2.012 | 27.32% | 29.33% | -19.88% | -19.88% |
| 1.06 | 0.5 | 10 | 2.025 | 2.006 | 27.07% | 29.08% | -19.85% | -19.85% |
| 1.06 | 0.5 | None | 2.025 | 2.006 | 27.07% | 29.08% | -19.85% | -19.85% |
| 1.06 | 0.5 | 5 | 2.025 | 2.005 | 27.05% | 29.06% | -19.85% | -19.85% |
| 1.03 | 0.5 | 10 | 2.021 | 2.004 | 27.20% | 29.24% | -19.85% | -19.85% |
| 1.03 | 0.5 | None | 2.021 | 2.004 | 27.20% | 29.24% | -19.85% | -19.85% |
| 1.03 | 0.5 | 5 | 2.020 | 2.004 | 27.18% | 29.22% | -19.85% | -19.85% |
| 1.10 | 0.5 | 3 | 1.982 | 1.971 | 26.73% | 28.94% | -19.88% | -19.88% |
| 1.10 | 0.5 | None | 1.973 | 1.964 | 26.60% | 28.83% | -19.85% | -19.85% |

Full-entry downside checks:

| Version | `CN_SWITCH_BUFFER` | `CN_ENTRY_INITIAL_FRACTION` | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| V7.5 | 1.06 | 1.0 | 1.822 | 50.15% | -23.52% | 28.04% | -23.52% | 1.332 |
| V7.5 | 1.03 | 1.0 | 1.821 | 50.06% | -23.52% | 28.22% | -23.52% | 1.340 |
| V7.5 | 1.00 | 1.0 | 1.783 | 49.04% | -23.99% | 27.32% | -23.99% | 1.307 |
| V7.6 | 1.06 | 1.0 | 1.816 | 55.23% | -23.52% | 30.35% | -23.52% | 1.303 |
| V7.6 | 1.03 | 1.0 | 1.815 | 55.13% | -23.52% | 30.51% | -23.52% | 1.309 |
| V7.6 | 1.00 | 1.0 | 1.774 | 53.88% | -23.99% | 29.45% | -23.99% | 1.274 |

Stability comparison:

| Metric | V7.5 | V7.6 | Readout |
|---|---:|---:|---|
| Best point | 1.06 / 0.5 / 3 | 1.06 / 0.5 / 3 | Same best by recent-weighted Sharpe |
| Default-style point | 1.06 / 0.5 / None | 1.03 / 0.5 / None | Both are in the stable plateau |
| Rank 1 to Rank 2 Sharpe gap | 0.005 | 0.002 | Both very flat; V7.6 slightly flatter at the top |
| Stable half-entry plateau median Sharpe | 2.021 | 2.004 | V7.5 higher Sharpe in this fixed-parameter run |
| Stable half-entry plateau Sharpe std | 0.024 | 0.020 | V7.6 slightly flatter |
| Count within 99% of best, full grid | 8 / 24 | 8 / 24 | Same |
| Count within 95% of best, full grid | 16 / 24 | 16 / 24 | Same |
| Full-entry median Sharpe | 1.810 | 1.802 | Full-entry weaker in both versions |
| Full-entry median worst MaxDD | -23.52% | -23.52% | Same drawdown penalty |

Notes:

- This execution group is stable in both versions; the practical plateau is `entry=0.5`, `buffer=1.03-1.06`, and `wait=None/3/5/10`.
- V7.6 is marginally flatter at the very top, but V7.5 has a slightly higher recent-weighted Sharpe in this fixed `R2=0.20` execution-layer scan.
- Full-entry can raise 10Y CAGR, especially in V7.6, but it degrades Sharpe and increases MaxDD to roughly `-23.5%`; it should stay as a stress/return candidate, not the clean default.

### 4. `CN_TARGET_VOL / CN_VOL_WINDOW / CN_SCALE_THRESHOLD`

- Superseded status: current V7.6 full-grid rerun is now complete. Use `docs/suba_v75_vs_v76_current_parameter_stability_compare_20260506.md` for all current V7.5-vs-V7.6 conclusions; the same-parameter comparison and pending rows in this section are preserved only as historical notes.

- Checked values: `CN_TARGET_VOL` in `0.20,0.25,0.30,0.35,0.40`; `CN_VOL_WINDOW` in `40,60,80,100,120`; `CN_SCALE_THRESHOLD` in `0,0.05,0.10,0.15`.
- Fixed parameters for same-parameter comparison: `CN_BIAS_N=60`, `CN_MOM_DAY=20`, `CN_R2_WINDOW=20`, `CN_R2_THRESHOLD=0.20`, `CN_SWITCH_BUFFER=1.03`, `CN_ENTRY_INITIAL_FRACTION=0.5`, `CN_ENTRY_WAIT_DAYS=None`; other formal Sub-A defaults preserved.
- V7.5 current script scaling baseline: `CN_TARGET_VOL=0.20`, `CN_VOL_WINDOW=60`, `CN_SCALE_THRESHOLD=0.15`.
- V7.6 scaling baseline: `CN_TARGET_VOL=0.30`, `CN_VOL_WINDOW=80`, `CN_SCALE_THRESHOLD=0.00`.
- Evidence path: `docs/suba_v75_stability_A_position_scaling_20260506/`.
- Comparison baseline: `docs/suba_v76_stability_A_position_scaling_20260506/`.
- Audit: target script `mnt_bot V 7.5 plus.py`; formal Sub-A path; data `2010-06-01` to `2026-04-30`; rows `3865`; duplicate dates `0`.
- Decision update: the V7.5 full-grid run is valid, but the initial same-parameter comparison against the existing V7.6 document is not valid for current-code comparison. A spot-check rerun against the current `mnt_bot V 7.6 plus.py` shows the existing V7.6 position-scaling document is stale relative to the current V7.6 file. Current V7.6 differs from V7.5 because the current root files differ in defaults such as `CN_SA_VOLUME_SCALE` (`0.50` in V7.5 vs `0.25` in V7.6), which affects the formal overlay stack. This group needs a current V7.6 full-grid rerun before making a final V7.5-vs-V7.6 stability judgment.

V7.5 top results by recent-weighted Sharpe:

| Rank | `CN_TARGET_VOL` | `CN_VOL_WINDOW` | `CN_SCALE_THRESHOLD` | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe | 10Y Avg Weight | 10Y Avg Turnover |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.25 | 120 | 0.15 | 2.057 | 51.03% | -17.94% | 27.34% | -17.94% | 1.446 | 0.699 | 0.216 |
| 2 | 0.25 | 100 | 0.15 | 2.035 | 49.06% | -19.16% | 26.99% | -19.16% | 1.435 | 0.700 | 0.218 |
| 3 | 0.25 | 120 | 0.05 | 2.030 | 51.65% | -19.85% | 28.56% | -19.85% | 1.435 | 0.741 | 0.231 |
| 4 | 0.25 | 120 | 0.10 | 2.029 | 51.65% | -19.85% | 28.60% | -19.85% | 1.438 | 0.741 | 0.231 |
| 5 | 0.40 | 40 | 0.10 | 2.028 | 51.75% | -19.85% | 28.92% | -19.85% | 1.428 | 0.757 | 0.234 |
| 6 | 0.35 | 40 | 0.15 | 2.026 | 51.63% | -18.97% | 28.75% | -18.97% | 1.446 | 0.746 | 0.230 |
| 7 | 0.35 | 40 | 0.05 | 2.025 | 51.72% | -19.85% | 29.11% | -19.85% | 1.440 | 0.760 | 0.235 |
| 8 | 0.40 | 40 | 0.15 | 2.024 | 51.56% | -19.22% | 28.62% | -19.22% | 1.428 | 0.748 | 0.231 |
| 9 | 0.40 | 60 | 0.10 | 2.024 | 51.88% | -18.95% | 28.75% | -18.95% | 1.434 | 0.745 | 0.230 |
| 10 | 0.35 | 40 | 0.10 | 2.023 | 51.71% | -18.97% | 28.94% | -18.97% | 1.442 | 0.752 | 0.232 |
| 11 | 0.20 | 120 | 0.15 | 2.023 | 48.97% | -18.66% | 26.98% | -18.66% | 1.446 | 0.697 | 0.218 |
| 12 | 0.30 | 80 | 0.10 | 2.023 | 51.56% | -19.85% | 28.64% | -19.85% | 1.429 | 0.744 | 0.232 |

Same-parameter comparison with existing V7.6 document only:

| `CN_TARGET_VOL` | `CN_VOL_WINDOW` | `CN_SCALE_THRESHOLD` | V7.5 Recent Sharpe | Existing V7.6-doc Recent Sharpe | V7.5 10Y CAGR | Existing V7.6-doc 10Y CAGR | V7.5 10Y MaxDD | Existing V7.6-doc 10Y MaxDD |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.25 | 120 | 0.15 | 2.057 | 2.057 | 27.34% | 27.34% | -17.94% | -17.94% |
| 0.25 | 100 | 0.15 | 2.035 | 2.035 | 26.99% | 26.99% | -19.16% | -19.16% |
| 0.25 | 120 | 0.05 | 2.030 | 2.030 | 28.56% | 28.56% | -19.85% | -19.85% |
| 0.25 | 120 | 0.10 | 2.029 | 2.029 | 28.60% | 28.60% | -19.85% | -19.85% |
| 0.40 | 40 | 0.10 | 2.028 | 2.028 | 28.92% | 28.92% | -19.85% | -19.85% |
| 0.35 | 40 | 0.15 | 2.026 | 2.026 | 28.75% | 28.75% | -18.97% | -18.97% |
| 0.35 | 40 | 0.05 | 2.025 | 2.025 | 29.11% | 29.11% | -19.85% | -19.85% |
| 0.40 | 40 | 0.15 | 2.024 | 2.024 | 28.62% | 28.62% | -19.22% | -19.22% |
| 0.40 | 60 | 0.10 | 2.024 | 2.024 | 28.75% | 28.75% | -18.95% | -18.95% |
| 0.35 | 40 | 0.10 | 2.023 | 2.023 | 28.94% | 28.94% | -18.97% | -18.97% |
| 0.30 | 80 | 0.00 | 2.004 | 2.004 | 29.24% | 29.24% | -19.85% | -19.85% |

Target-vol sensitivity:

| `CN_TARGET_VOL` | Median recent Sharpe | Max recent Sharpe | Median 10Y CAGR | Median 10Y MaxDD | Median 10Y Avg Weight |
|---:|---:|---:|---:|---:|---:|
| 0.20 | 1.992 | 2.023 | 26.58% | -19.85% | 0.706 |
| 0.25 | 2.006 | 2.057 | 28.39% | -19.85% | 0.742 |
| 0.30 | 2.008 | 2.023 | 29.13% | -19.85% | 0.762 |
| 0.35 | 2.010 | 2.026 | 29.35% | -19.85% | 0.768 |
| 0.40 | 2.010 | 2.028 | 29.55% | -19.85% | 0.773 |

Stability comparison:

| Metric | V7.5 | V7.6 | Readout |
|---|---:|---:|---|
| Best point | 0.25 / 120 / 0.15 | pending current V7.6 rerun | Existing V7.6 doc matched V7.5, but current-code spot-check does not |
| Same-parameter output equality | No current-code equality observed | No current-code equality observed | Existing V7.6 doc is stale for this group |
| Rank 1 to Rank 2 Sharpe gap | 0.022 | pending current V7.6 rerun | V7.5 only confirmed |
| Full-grid Sharpe std | 0.014 | pending current V7.6 rerun | V7.5 only confirmed |
| Full-grid median Sharpe | 2.009 | pending current V7.6 rerun | V7.5 only confirmed |
| Count within 99% of best | 1 / 100 | pending current V7.6 rerun | V7.5 only confirmed |
| Count within 95% of best | 100 / 100 | pending current V7.6 rerun | V7.5 broad acceptable platform |
| V7.5 current scaling default | 0.20 / 60 / 0.15 | NA | Recent Sharpe 2.021; 10Y CAGR 27.20%; MaxDD -19.85% |
| Current V7.6 spot-check default-style point | NA | 0.30 / 80 / 0.00 | Current rerun: Recent Sharpe 2.095; 10Y CAGR 28.86%; MaxDD -18.64% |

Notes:

- This group is stable and broad by practical acceptability, but not by exact top-pick uniqueness: all points are within 95% of best, while only one point is within 99%.
- The existing V7.6 position-scaling document should not be used as the current-code comparison baseline without rerunning it. Spot-check output path: `docs/suba_v76_stability_A_position_scaling_current_spotcheck_20260506/`.
- If prioritizing Sharpe/drawdown within the V7.5 grid, `0.25/120/0.15` is the V7.5 grid winner. Current V7.6 needs full-grid rerun before comparing stability or picking a cross-version winner.

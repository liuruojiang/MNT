# Sub-A V7.6 Parameter Stability Notes - 2026-05-06

## Confirmed

2026-05-11 follow-up: the original R2 section below is a coarse-grid historical scan. A finer fixed-window scan on `CN_R2_WINDOW=20` tested `CN_R2_THRESHOLD=0.20/0.225/0.25/0.275/0.30` through 2026-05-11, then added 0/5/10 bps incremental impact stress. The approved current V7.6 default is now `CN_R2_THRESHOLD=0.25`. See `docs/suba_v76_r2_threshold_confirm_20260511.md`.

### 1. `CN_BIAS_N / CN_MOM_DAY`

- Checked values: `CN_BIAS_N` in `40,50,60,70,80`; `CN_MOM_DAY` in `10,15,20,25,30`.
- Baseline/default: `CN_BIAS_N=60`, `CN_MOM_DAY=20`.
- Evidence path: `docs/suba_v76_stability_A_ma_slope_20260506/`.
- Audit: target script `mnt_bot V 7.6 plus.py`; formal Sub-A path; data `2010-06-01` to `2026-04-30`; rows `3865`; duplicate dates `0`; fast-indicator parity max diffs all `0.0`.
- Decision: 可接受稳定，但不是宽平台型稳定。

| Rank | `CN_BIAS_N` | `CN_MOM_DAY` | Recent weighted Sharpe | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 20 | 2.004 | 29.24% | -19.85% | 1.426 |
| 2 | 50 | 20 | 1.803 | 24.90% | -31.16% | 1.237 |
| 3 | 60 | 25 | 1.727 | 25.30% | -31.77% | 1.228 |
| 4 | 50 | 25 | 1.677 | 23.83% | -28.98% | 1.196 |
| 5 | 70 | 20 | 1.618 | 22.86% | -21.56% | 1.143 |
| 6 | 40 | 20 | 1.591 | 20.35% | -32.98% | 1.054 |
| 7 | 40 | 25 | 1.552 | 21.65% | -34.99% | 1.103 |
| 8 | 80 | 20 | 1.531 | 22.59% | -26.57% | 1.122 |

### 2. `CN_R2_WINDOW / CN_R2_THRESHOLD`

- Checked values: `CN_R2_WINDOW` in `10,15,20,30`; `CN_R2_THRESHOLD` in `0,0.1,0.2,0.3,0.4,0.5`.
- Fixed parameters: `CN_BIAS_N=60`, `CN_MOM_DAY=20`; other V7.6 formal Sub-A defaults preserved.
- Historical baseline/default at the time of this 2026-05-06 coarse scan: `CN_R2_WINDOW=20`, `CN_R2_THRESHOLD=0.20`. Current approved V7.6 default after the 2026-05-11 fine scan: `CN_R2_WINDOW=20`, `CN_R2_THRESHOLD=0.25`.
- Evidence path: `docs/suba_v76_stability_A_r2_20260506/`.
- Audit: target script `mnt_bot V 7.6 plus.py`; formal Sub-A path; data `2010-06-01` to `2026-04-30`; rows `3865`; duplicate dates `0`.
- Decision: R2 窗口不宽，`window=20` 明显占优；阈值在 `0.1-0.3` 内可接受稳定，默认 `0.20` 为平衡最优点。

| Rank | `CN_R2_WINDOW` | `CN_R2_THRESHOLD` | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20 | 0.20 | 2.004 | 51.96% | -19.85% | 29.24% | -19.85% | 1.426 |
| 2 | 20 | 0.10 | 1.932 | 53.03% | -23.06% | 28.12% | -23.06% | 1.341 |
| 3 | 20 | 0.30 | 1.914 | 47.71% | -17.89% | 27.35% | -17.89% | 1.379 |
| 4 | 15 | 0.30 | 1.801 | 46.71% | -31.35% | 19.51% | -31.35% | 1.024 |
| 5 | 10 | 0.00 | 1.758 | 56.99% | -28.98% | 26.97% | -28.98% | 1.149 |
| 6 | 20 | 0.00 | 1.758 | 56.99% | -28.98% | 26.97% | -28.98% | 1.149 |
| 7 | 15 | 0.00 | 1.758 | 56.99% | -28.98% | 26.97% | -28.98% | 1.149 |
| 8 | 30 | 0.00 | 1.758 | 56.99% | -28.98% | 26.97% | -28.98% | 1.149 |
| 9 | 15 | 0.10 | 1.736 | 47.02% | -30.33% | 21.31% | -30.33% | 1.048 |
| 10 | 30 | 0.10 | 1.722 | 45.43% | -34.34% | 19.78% | -34.34% | 1.039 |
| 11 | 30 | 0.20 | 1.711 | 40.91% | -28.54% | 19.14% | -28.54% | 1.068 |
| 12 | 15 | 0.20 | 1.683 | 43.44% | -35.20% | 19.35% | -35.20% | 0.997 |

### 3. `CN_SWITCH_BUFFER / CN_ENTRY_INITIAL_FRACTION / CN_ENTRY_WAIT_DAYS`

- Checked values: `CN_SWITCH_BUFFER` in `1.00,1.03,1.06,1.10`; `CN_ENTRY_INITIAL_FRACTION` in `0.5,1.0`; `CN_ENTRY_WAIT_DAYS` in `None,0,3,5,10`.
- Fixed parameters: `CN_BIAS_N=60`, `CN_MOM_DAY=20`, `CN_R2_WINDOW=20`, `CN_R2_THRESHOLD=0.20`; other V7.6 formal Sub-A defaults preserved.
- Baseline/default: `CN_SWITCH_BUFFER=1.03`, `CN_ENTRY_INITIAL_FRACTION=0.5`, `CN_ENTRY_WAIT_DAYS=None`.
- Evidence path: `docs/suba_v76_stability_A_execution_20260506/`.
- Audit: target script `mnt_bot V 7.6 plus.py`; formal Sub-A path; data `2010-06-01` to `2026-04-30`; rows `3865`; duplicate dates `0`.
- Decision: 执行层参数稳定性较好，稳定平台集中在 `entry=0.5`、`buffer=1.03-1.06`、`wait=None/3/5/10`；默认值接近最优且回撤控制更优，保留默认。

| Rank | `CN_SWITCH_BUFFER` | `CN_ENTRY_INITIAL_FRACTION` | `CN_ENTRY_WAIT_DAYS` | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.06 | 0.5 | 3 | 2.013 | 52.25% | -19.88% | 29.17% | -19.88% | 1.421 |
| 2 | 1.03 | 0.5 | 3 | 2.012 | 52.14% | -19.88% | 29.33% | -19.88% | 1.428 |
| 3 | 1.06 | 0.5 | 10 | 2.006 | 52.07% | -19.85% | 29.08% | -19.85% | 1.419 |
| 4 | 1.06 | 0.5 | None | 2.006 | 52.07% | -19.85% | 29.08% | -19.85% | 1.419 |
| 5 | 1.06 | 0.5 | 5 | 2.005 | 52.06% | -19.85% | 29.06% | -19.85% | 1.419 |
| 6 | 1.03 | 0.5 | None | 2.004 | 51.96% | -19.85% | 29.24% | -19.85% | 1.426 |
| 7 | 1.03 | 0.5 | 10 | 2.004 | 51.96% | -19.85% | 29.24% | -19.85% | 1.426 |
| 8 | 1.03 | 0.5 | 5 | 2.004 | 51.95% | -19.85% | 29.22% | -19.85% | 1.425 |
| 9 | 1.10 | 0.5 | 3 | 1.971 | 51.26% | -19.88% | 28.94% | -19.88% | 1.408 |
| 10 | 1.10 | 0.5 | None | 1.964 | 51.08% | -19.85% | 28.83% | -19.85% | 1.406 |
| 11 | 1.10 | 0.5 | 10 | 1.964 | 51.08% | -19.85% | 28.83% | -19.85% | 1.406 |
| 12 | 1.10 | 0.5 | 5 | 1.963 | 51.07% | -19.85% | 28.81% | -19.85% | 1.405 |

Key downside checks:

| `CN_SWITCH_BUFFER` | `CN_ENTRY_INITIAL_FRACTION` | `CN_ENTRY_WAIT_DAYS` | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.06 | 1.0 | None | 1.816 | 55.23% | -23.52% | 30.35% | -23.52% | 1.303 |
| 1.03 | 1.0 | None | 1.815 | 55.13% | -23.52% | 30.51% | -23.52% | 1.309 |
| 1.10 | 1.0 | None | 1.788 | 54.27% | -23.52% | 30.13% | -23.52% | 1.293 |
| 1.00 | 1.0 | None | 1.774 | 53.88% | -23.99% | 29.45% | -23.99% | 1.274 |
| 1.06 | 0.5 | 0 | 1.761 | 51.37% | -23.57% | 28.73% | -23.57% | 1.275 |
| 1.03 | 0.5 | 0 | 1.759 | 51.26% | -23.57% | 28.90% | -23.57% | 1.281 |

### 4. `CN_TARGET_VOL / CN_VOL_WINDOW / CN_SCALE_THRESHOLD`

- Checked values: `CN_TARGET_VOL` in `0.20,0.25,0.30,0.35,0.40`; `CN_VOL_WINDOW` in `40,60,80,100,120`; `CN_SCALE_THRESHOLD` in `0,0.05,0.10,0.15`.
- Fixed parameters: `CN_BIAS_N=60`, `CN_MOM_DAY=20`, `CN_R2_WINDOW=20`, `CN_R2_THRESHOLD=0.20`, `CN_SWITCH_BUFFER=1.03`, `CN_ENTRY_INITIAL_FRACTION=0.5`, `CN_ENTRY_WAIT_DAYS=None`; other V7.6 formal Sub-A defaults preserved.
- Baseline/default: `CN_TARGET_VOL=0.30`, `CN_VOL_WINDOW=80`, `CN_SCALE_THRESHOLD=0.00`.
- Evidence path: `docs/suba_v76_stability_A_position_scaling_20260506/`.
- Audit: target script `mnt_bot V 7.6 plus.py`; formal Sub-A path; data `2010-06-01` to `2026-04-30`; rows `3865`; duplicate dates `0`.
- Decision: 波动率缩放层相对宽平台稳定；默认 `0.30/80/0` 可保留，若偏防守可研究 `0.25/120/0.10-0.15`，若偏收益 `0.35-0.40` 边际提升有限且受最大杠杆约束。

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
| Default | 0.30 | 80 | 0.00 | 2.004 | 51.96% | -19.85% | 29.24% | -19.85% | 1.426 | 0.762 | 0.238 |

Target-vol sensitivity with `CN_VOL_WINDOW=80` and `CN_SCALE_THRESHOLD=0`:

| `CN_TARGET_VOL` | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---:|---:|---:|---:|---:|---:|---:|
| 0.20 | 1.983 | 48.69% | -19.85% | 26.39% | -19.85% | 1.410 |
| 0.25 | 2.001 | 51.27% | -19.85% | 28.40% | -19.85% | 1.428 |
| 0.30 | 2.004 | 51.96% | -19.85% | 29.24% | -19.85% | 1.426 |
| 0.35 | 2.005 | 52.37% | -19.85% | 29.51% | -19.85% | 1.423 |
| 0.40 | 2.010 | 52.56% | -19.85% | 29.68% | -19.85% | 1.421 |

### 5. `CN_SA_CASH_OVERLAY_DECAY_RATIO / CN_SA_CASH_OVERLAY_RECOVERY_RATIO`

- Checked values: `CN_SA_CASH_OVERLAY_DECAY_RATIO` in `0.45,0.50,0.55,0.60,0.65,0.70`; `CN_SA_CASH_OVERLAY_RECOVERY_RATIO` in `0.70,0.75,0.80,0.85,0.90,0.95,1.00`; plus cash-overlay-off case.
- Fixed parameters: V7.6 formal Sub-A defaults preserved, including same-side overheat overlay and volume overlay.
- Baseline/default: `CN_SA_CASH_OVERLAY_DECAY_RATIO=0.55`, `CN_SA_CASH_OVERLAY_RECOVERY_RATIO=0.90`.
- Evidence path: `docs/suba_v76_stability_A_cash_overlay_20260506/`.
- Audit: target script `mnt_bot V 7.6 plus.py`; formal Sub-A path; data `2010-06-01` to `2026-04-30`; rows `3865`; duplicate dates `0`.
- Decision: 现金 overlay 有效；稳定平台集中在 `decay=0.55-0.60`、`recovery=0.90-1.00`；默认 `0.55/0.90` 接近最优且收益/触发频率更均衡，保留默认。

| Rank | Cash enabled | `CN_SA_CASH_OVERLAY_DECAY_RATIO` | `CN_SA_CASH_OVERLAY_RECOVERY_RATIO` | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe | 10Y Trigger Count | 10Y Overlay Days |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | True | 0.60 | 1.00 | 2.008 | 50.67% | -19.85% | 27.55% | -19.85% | 1.380 | 53 | 236 |
| 2 | True | 0.55 | 1.00 | 2.007 | 52.04% | -19.85% | 29.52% | -19.85% | 1.438 | 47 | 173 |
| 3 | True | 0.60 | 0.95 | 2.006 | 50.60% | -19.85% | 27.29% | -19.85% | 1.369 | 54 | 236 |
| 4 | True | 0.55 | 0.95 | 2.005 | 51.97% | -19.85% | 29.25% | -19.85% | 1.427 | 48 | 173 |
| 5 | True | 0.60 | 0.90 | 2.005 | 50.59% | -19.85% | 27.28% | -19.85% | 1.368 | 54 | 232 |
| 6 | True | 0.55 | 0.90 | 2.004 | 51.96% | -19.85% | 29.24% | -19.85% | 1.426 | 48 | 169 |
| 7 | True | 0.50 | 1.00 | 1.997 | 52.43% | -25.89% | 27.66% | -25.89% | 1.341 | 37 | 134 |
| Off | False | NA | NA | 1.708 | 46.08% | -23.22% | 26.54% | -23.22% | 1.260 | 0 | 0 |

### 6. `CN_SA_SAME_SIDE_OVERHEAT_ENTER / CN_SA_SAME_SIDE_OVERHEAT_EXIT / CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE`

- Checked values: `CN_SA_SAME_SIDE_OVERHEAT_ENTER` in `0.28,0.32,0.36,0.40,0.44`; `CN_SA_SAME_SIDE_OVERHEAT_EXIT = enter - 0.02 / enter - 0.04`; `CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE` in `0,0.25,0.50`; plus overheat-overlay-off case.
- Fixed parameters: V7.6 formal Sub-A defaults preserved, including cash overlay and volume overlay.
- Baseline/default: `CN_SA_SAME_SIDE_OVERHEAT_ENTER=0.36`, `CN_SA_SAME_SIDE_OVERHEAT_EXIT=0.34`, `CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE=0.0`.
- Evidence path: `docs/suba_v76_stability_A_overheat_20260506/`.
- Audit: target script `mnt_bot V 7.6 plus.py`; formal Sub-A path; data `2010-06-01` to `2026-04-30`; rows `3865`; duplicate dates `0`.
- Decision: 默认 `0.36/0.34/0.0` 稳定但触发很少，属于低频保险层；不建议下调到 `0.28`，因为近期改善伴随全样本退化；保留默认。

| Rank | Enabled | `CN_SA_SAME_SIDE_OVERHEAT_ENTER` | `CN_SA_SAME_SIDE_OVERHEAT_EXIT` | `CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE` | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe | 10Y Trigger Count | 10Y Overlay Days | Full CAGR |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | True | 0.28 | 0.24 | 0.00 | 2.042 | 52.64% | -19.85% | 30.03% | -19.85% | 1.462 | 3 | 12 | 28.80% |
| 2 | True | 0.28 | 0.26 | 0.00 | 2.037 | 52.54% | -19.85% | 29.97% | -19.85% | 1.460 | 3 | 11 | 28.77% |
| 3 | True | 0.28 | 0.24 | 0.25 | 2.035 | 52.49% | -19.85% | 29.85% | -19.85% | 1.455 | 3 | 12 | 29.18% |
| 4 | True | 0.28 | 0.26 | 0.25 | 2.031 | 52.42% | -19.85% | 29.81% | -19.85% | 1.453 | 3 | 11 | 29.15% |
| 5 | True | 0.28 | 0.24 | 0.50 | 2.026 | 52.33% | -19.85% | 29.66% | -19.85% | 1.446 | 3 | 12 | 29.54% |
| 6 | True | 0.28 | 0.26 | 0.50 | 2.024 | 52.28% | -19.85% | 29.63% | -19.85% | 1.445 | 3 | 11 | 29.52% |
| Off | False | NA | NA | NA | 2.004 | 51.96% | -19.85% | 29.24% | -19.85% | 1.426 | 0 | 0 | 30.32% |
| Default | True | 0.36 | 0.34 | 0.00 | 2.004 | 51.96% | -19.85% | 29.24% | -19.85% | 1.426 | 1 | 2 | 31.18% |

### 7. `CN_SA_VOLUME_SCALE / CN_SA_VOLUME_*`

- Checked values: 成交额 overlay 开关、旧缩仓规则 `ZZ2000 amount < MA15` 连续 3 天或 `CYB amount < MA10` 连续 3 天、新清仓规则 `ZZ2000/SZ50 amount ratio < MA30` 连续 15 天，以及旧规则触发后仓位 `CN_SA_VOLUME_SCALE`。
- Fixed parameters: V7.6 formal Sub-A defaults preserved, including cash overlay and same-side overheat overlay.
- Baseline/default before this round: `CN_SA_VOLUME_SCALE=0.50`, `CN_SA_VOLUME_CLEAR_RATIO_SCALE=0.0`。
- Evidence path: `docs/suba_v76_stability_A_volume_20260506/`。
- Audit: target script `mnt_bot V 7.6 plus.py`; formal Sub-A path; data `2010-06-01` to `2026-04-30`; rows `3865`; duplicate dates `0`。
- Decision: 成交额 overlay 有效；旧缩仓比例从 `50%` 改为 `25%`。该改动在旧规则触发天数不变的情况下，最近 3Y/5Y 同时提高 CAGR、Sharpe、Calmar 并降低 MaxDD；10Y 回撤也从 `-19.85%` 降到 `-18.64%`。`CYB_DAYS=5` 的 10Y CAGR 更高，但不是本次默认，因为它同时改变触发频率和规则形态；本轮仅固化更直接、更稳健的仓位比例改动。

Main comparison:

| Case | Family | Old scale | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe | 10Y Overlay Days | Full CAGR | Full MaxDD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `old_scale_0.25` | scale scan | 0.25 | 2.095 | 52.25% | -18.64% | 28.86% | -18.64% | 1.451 | 1112 | 29.80% | -34.79% |
| `default` / `old_scale_0.50` | default | 0.50 | 2.004 | 51.96% | -19.85% | 29.24% | -19.85% | 1.426 | 1112 | 31.18% | -32.53% |
| `cyb_ma10_d5` | CYB days scan | 0.50 | 2.012 | 53.84% | -18.71% | 31.00% | -18.71% | 1.471 | 999 | 32.65% | -29.72% |
| `old_only_default` | old only | 0.50 | 1.796 | 51.63% | -24.67% | 27.34% | -24.67% | 1.291 | 1034 | 31.77% | -32.53% |
| `clear_only_default` | clear only | NA | 1.755 | 51.05% | -23.31% | 29.54% | -23.31% | 1.309 | 183 | 33.24% | -27.76% |
| `volume_off` | off | NA | 1.529 | 48.84% | -29.99% | 25.43% | -29.99% | 1.111 | 0 | 32.16% | -29.99% |

Recent 3Y/5Y check for `CN_SA_VOLUME_SCALE=0.25` vs old default `0.50`:

| Scale | Window | CAGR | MaxDD | Sharpe | Calmar | Overlay Days |
|---:|---|---:|---:|---:|---:|---:|
| 0.25 | 3Y | 45.64% | -11.04% | 2.056 | 4.133 | 366 |
| 0.50 | 3Y | 44.24% | -12.79% | 1.958 | 3.459 | 366 |
| 0.25 | 5Y | 35.71% | -15.01% | 1.778 | 2.379 | 563 |
| 0.50 | 5Y | 33.76% | -17.72% | 1.642 | 1.906 | 563 |

Implementation note:

- `mnt_bot V 7.6 plus.py` now sets `CN_SA_VOLUME_SCALE = 0.25`。
- Runtime display text changed from hard-coded “旧半仓规则” to “旧缩仓规则”，and the shown trigger position now follows `CN_SA_VOLUME_SCALE` dynamically.

Post-change verification:

- Re-ran `analyze_suba_v76_volume_stability.py --out-dir docs\suba_v76_stability_A_volume_after_scale25_20260506` after editing V7.6.
- New `default` row has `old_scale=0.25` and matches `old_scale_0.25` exactly in the rerun output: recent weighted Sharpe `2.095`, 3Y `45.64% / -11.04% / 2.056`, 5Y `35.71% / -15.01% / 1.778`, 10Y `28.86% / -18.64% / 1.451`。

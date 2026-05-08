# Sub-B V7.5/V7.6 Parameter Stability Notes - 2026-05-06

## Audit Scope

- Target scripts: `mnt_bot V 7.5 plus.py`, `mnt_bot V 7.6 plus.py`.
- Formal path: production Sub-B data construction, `run_us_rotation_mix()` official macro-gated leg, `run_subb_v75_ema_base7_rotation()` EMA leg, `blend_subb_v75_results()`, then VolReg when enabled.
- Execution: T close signal -> T+1 adjusted open execution with `us_open`.
- Data checks in completed runs: duplicate dates = 0, weekend rows = 0, missing open = none.

## Completed Groups

### US_ROT_LBS coarse grid

- Output: `docs/subb_v75_v76_parameter_stability_lbs_20260506/`.
- Result: horizontal stability is very strong. V7.5 and V7.6 rank all 9 lookback tuples in the same order.
- Platform coverage by recent weighted Sharpe:

| Version | 99% within | 95% within | 90% within | 80% within |
|---|---:|---:|---:|---:|
| V7.5 | 2 / 9 | 8 / 9 | 9 / 9 | 9 / 9 |
| V7.6 | 2 / 9 | 9 / 9 | 9 / 9 | 9 / 9 |

### US_ROT_LBS local platform grid

- Output: `docs/subb_v75_v76_parameter_stability_lbs_local_20260506/`.
- Grid: short `140/160/180`, mid `240/260/280`, long `360/390/420`.
- Result: platform is broad, especially in V7.6. Local high point is `(180,240,390)`, not the previous center `(160,260,390)`.
- Platform coverage by recent weighted Sharpe:

| Version | 99% within | 95% within | 90% within | 80% within |
|---|---:|---:|---:|---:|
| V7.5 | 2 / 27 | 25 / 27 | 27 / 27 | 27 / 27 |
| V7.6 | 9 / 27 | 27 / 27 | 27 / 27 | 27 / 27 |

### Official/EMA blend and EMA parameters

- Output: `docs/subb_v75_v76_parameter_stability_blend_ema_20260506/`.
- Grid: official/EMA weights `75/25`, `50/50`, `25/75`; EMA `(half_life, threshold)` = `(60,0.16)`, `(100,0.08)`, `(100,0.16)`, `(100,0.24)`, `(150,0.16)`.
- Platform coverage by recent weighted Sharpe:

| Version | 99% within | 95% within | 90% within | 80% within |
|---|---:|---:|---:|---:|
| V7.5 | 2 / 15 | 4 / 15 | 12 / 15 | 15 / 15 |
| V7.6 | 2 / 15 | 8 / 15 | 11 / 15 | 15 / 15 |

#### Drawdown sanity check

The `blend_ema` group has different optima depending on objective:

| Version | Candidate | 10Y CAGR | 10Y MaxDD | Peak | Trough |
|---|---|---:|---:|---|---|
| V7.5 | official 25% / EMA 75%, EMA 100 / threshold 0.16 | 31.53% | -12.38% | 2025-10-20 | 2025-11-20 |
| V7.5 default | official 50% / EMA 50%, EMA 100 / threshold 0.16 | 30.90% | -13.87% | 2018-10-03 | 2018-12-24 |
| V7.6 | official 75% / EMA 25%, EMA 100 / threshold 0.16 | 32.35% | -17.64% | 2018-10-03 | 2018-12-24 |
| V7.6 default | official 25% / EMA 75%, EMA 100 / threshold 0.16 | 32.27% | -12.11% | 2025-10-20 | 2025-11-20 |

Interpretation: V7.6's `recent_weighted_sharpe` optimum is not the lowest-drawdown point. The current V7.6 default is a lower-drawdown robust point inside the 95% platform, not the 99% Sharpe optimum.

### Absolute momentum and rebalance thresholds

- Output: `docs/subb_v75_v76_parameter_stability_thresholds_20260506/`.
- Grid: `US_ROT_ABS_THRESHOLD = 0.00/0.04/0.08`; `US_ROT_REBALANCE_THRESHOLD = 1.00/1.03/1.05/1.08/1.10`.
- Platform coverage by recent weighted Sharpe:

| Version | 99% within | 95% within | 90% within | 80% within |
|---|---:|---:|---:|---:|
| V7.5 | 3 / 15 | 15 / 15 | 15 / 15 | 15 / 15 |
| V7.6 | 6 / 15 | 15 / 15 | 15 / 15 | 15 / 15 |

- V7.5 optimum by recent weighted Sharpe: `abs_threshold=0.00`, `rebalance_threshold=1.03`.
- V7.6 optimum by recent weighted Sharpe: `abs_threshold=0.04`, `rebalance_threshold=1.08`.
- V7.5/V7.6 horizontal rank stability is weak for this group: Spearman rank correlation `0.418`, exact same rank count `2 / 15`.
- Current default `abs_threshold=0.04`, `rebalance_threshold=1.05`:
  - V7.5 rank `10 / 15`; 10Y CAGR `30.92%`; 10Y MaxDD `-13.87%`.
  - V7.6 rank `3 / 15`; 10Y CAGR `32.25%`; 10Y MaxDD `-12.11%`.

### Sizing, target volatility, and VolReg

- Output: `docs/subb_v75_v76_parameter_stability_sizing_volreg_20260507/`.
- Grid: `US_ROT_TARGET_VOL = 0.20/0.25/0.30`; `US_ROT_VOL_WINDOW = 40/80`; `US_ROT_MAX_LEV = 1.5/2.0`; VolReg modes = `on 2.0/1.6`, `on 1.8/1.4`, `off`.
- Run note: the scan was resumed from `partial_*` outputs after an external background-process interruption; final files are complete with `summary.csv` 360 rows, `rank.csv` 72 rows, and `v75_v76_compare.csv` 36 rows.
- Platform coverage by recent weighted Sharpe:

| Version | 99% within | 95% within | 90% within | 80% within |
|---|---:|---:|---:|---:|
| V7.5 | 8 / 36 | 12 / 36 | 26 / 36 | 36 / 36 |
| V7.6 | 10 / 36 | 12 / 36 | 33 / 36 | 36 / 36 |

- V7.5/V7.6 horizontal rank stability is strong for this group: Spearman rank correlation `0.972`, exact same rank count `12 / 36`, and the top-10 sets fully overlap.
- Recent weighted Sharpe optima:

| Version | Candidate | Recent weighted Sharpe | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---|---|---:|---:|---:|---:|
| V7.5 | `target_vol=0.25`, `vol_window=80`, `max_lev=2.0`, VolReg off | 2.023 | 33.61% | -19.42% | 1.810 |
| V7.6 | `target_vol=0.25`, `vol_window=40`, `max_lev=2.0`, VolReg off | 2.070 | 34.78% | -18.64% | 1.808 |

- Current default `target_vol=0.25`, `vol_window=40`, `max_lev=2.0`, VolReg `on 2.0/1.6`:

| Version | Rank | Recent weighted Sharpe | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---|---:|---:|---:|---:|---:|
| V7.5 | 18 / 36 | 1.898 | 30.91% | -13.87% | 1.810 |
| V7.6 | 14 / 36 | 1.962 | 32.25% | -12.11% | 1.824 |

- Interpretation: `VolReg off` is the return/Sharpe optimum, but it raises 10Y max drawdown by roughly 5-7 percentage points versus the current VolReg default. The current `2.0/1.6` VolReg is therefore a drawdown-control choice, not a Sharpe-maximizing choice.
- The tighter `1.8/1.4` VolReg mode is dominated in both versions: it lowers recent weighted Sharpe and CAGR while not improving worst recent drawdown versus the current `2.0/1.6` mode.
- Sizing stability is broad. `max_lev=2.0` is usually ahead on Sharpe/CAGR, but `max_lev=1.5` remains close in the stable platform; `vol_window=40` and `80` are both acceptable. No default change is justified from this group unless the objective is explicitly changed from drawdown-controlled to return/Sharpe-maximized.

### Turnover threshold and transaction cost sensitivity

- Output: `docs/subb_v75_v76_parameter_stability_turnover_cost_20260507/`.
- Grid: `US_ROT_MIN_TURNOVER = 0.00/0.01/0.03/0.05/0.08`; `US_ROT_COMMISSION = 0.0005/0.0010/0.0020/0.0030`.
- Run note: the scan was resumed from `partial_*` outputs and completed locally as a single group; final files are complete with `summary.csv` 200 rows, `rank.csv` 40 rows, and `v75_v76_compare.csv` 20 rows.
- Platform coverage by recent weighted Sharpe:

| Version | 99% within | 95% within | 90% within | 80% within |
|---|---:|---:|---:|---:|
| V7.5 | 3 / 20 | 9 / 20 | 14 / 20 | 20 / 20 |
| V7.6 | 3 / 20 | 9 / 20 | 17 / 20 | 20 / 20 |

- V7.5/V7.6 horizontal rank stability is strong for this group: Spearman rank correlation `0.986`, exact same rank count `11 / 20`, and the top-10 sets fully overlap.
- Recent weighted Sharpe optima:

| Version | Candidate | Recent weighted Sharpe | 10Y CAGR | 10Y MaxDD | 10Y Sharpe | 10Y annual turnover | 10Y total trade cost |
|---|---|---:|---:|---:|---:|---:|---:|
| V7.5 | `min_turnover=0.01`, `commission=0.0005` | 1.944 | 31.90% | -13.73% | 1.858 | 14.82 | 7.39% |
| V7.6 | `min_turnover=0.01`, `commission=0.0005` | 2.003 | 33.22% | -12.06% | 1.869 | 14.35 | 7.16% |

- Current default `min_turnover=0.00`, `commission=0.0010`:

| Version | Rank | Recent weighted Sharpe | 10Y CAGR | 10Y MaxDD | 10Y Sharpe | 10Y annual turnover | 10Y total trade cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| V7.5 | 6 / 20 | 1.898 | 30.91% | -13.87% | 1.810 | 14.83 | 14.79% |
| V7.6 | 5 / 20 | 1.964 | 32.27% | -12.11% | 1.825 | 14.35 | 14.32% |

- Interpretation: this group mainly measures cost-assumption sensitivity, not a pure strategy-logic improvement. Lowering the modeled commission from `0.0010` to `0.0005` mechanically improves CAGR and Sharpe by reducing deducted trade cost; it should not be treated as a default change unless the real execution-cost assumption is also changed.
- `min_turnover=0.01` is marginally better than `0.00` in both versions, with almost unchanged turnover and drawdown. `min_turnover=0.03` remains close, but `0.05` and especially `0.08` start to sacrifice CAGR/Sharpe for only modest turnover reduction. Current `min_turnover=0.00` remains inside the 95% platform; no default change is forced from this group.

### VolReg short/long volatility windows

- Output: `docs/subb_v75_v76_parameter_stability_volreg_windows_20260507/`.
- Grid: `US_ROT_VOLREG_SHORT_W / US_ROT_VOLREG_LONG_W` = `10/250`, `15/90`, `20/120`, `20/180`, `30/120`, `30/180`, `40/180`, `40/252`.
- Run note: the initial run covered 7 alternate windows; after verifying that the current default `10/250` was missing, the scan script was backed up and the grid was expanded to include `10/250`, then resumed in the same output directory. Final files are complete with `summary.csv` 80 rows, `rank.csv` 16 rows, and `v75_v76_compare.csv` 8 rows.
- Platform coverage by recent weighted Sharpe:

| Version | 99% within | 95% within | 90% within | 80% within |
|---|---:|---:|---:|---:|
| V7.5 | 2 / 8 | 4 / 8 | 8 / 8 | 8 / 8 |
| V7.6 | 2 / 8 | 6 / 8 | 8 / 8 | 8 / 8 |

- V7.5/V7.6 horizontal rank stability is strong for this group: Spearman rank correlation `0.929`, exact same rank count `5 / 8`, and the top-5 sets overlap by `4 / 5`.
- Recent weighted Sharpe optima:

| Version | Candidate | Recent weighted Sharpe | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---|---|---:|---:|---:|---:|
| V7.5 | `30/120` | 2.016 | 33.46% | -19.00% | 1.810 |
| V7.6 | `30/120` | 2.073 | 34.80% | -18.64% | 1.809 |

- Current default `10/250`:

| Version | Rank | Recent weighted Sharpe | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---|---:|---:|---:|---:|---:|
| V7.5 | 7 / 8 | 1.901 | 30.94% | -13.87% | 1.811 |
| V7.6 | 7 / 8 | 1.964 | 32.27% | -12.11% | 1.825 |

- Interpretation: shorter/faster VolReg windows such as `30/120` and `40/180` lift recent weighted Sharpe and CAGR, but they do so by materially increasing 10Y drawdown to roughly `-18.6%` to `-19.0%`. The current `10/250` default is not a Sharpe-maximizing window, but it is a lower-drawdown wind-down choice consistent with the earlier VolReg conclusion.
- `20/120`, `20/180`, and `40/252` are intermediate alternatives. None clearly dominates the current default on the stated drawdown-control objective, so no default change is justified from this group unless the objective is explicitly changed toward return/Sharpe maximization.

### Volatility weighting lookback

- Output: `docs/subb_v75_v76_parameter_stability_vol_weight_20260507/`.
- Grid: `US_ROT_VOL_LB = 10/20/40/60`.
- Run note: final files are complete with `summary.csv` 40 rows, `rank.csv` 8 rows, and `v75_v76_compare.csv` 4 rows.
- Platform coverage by recent weighted Sharpe:

| Version | 99% within | 95% within | 90% within | 80% within |
|---|---:|---:|---:|---:|
| V7.5 | 2 / 4 | 4 / 4 | 4 / 4 | 4 / 4 |
| V7.6 | 3 / 4 | 4 / 4 | 4 / 4 | 4 / 4 |

- V7.5/V7.6 horizontal rank stability is perfect for this group: Spearman rank correlation `1.000`, exact same rank count `4 / 4`.
- Recent weighted Sharpe optima:

| Version | Candidate | Recent weighted Sharpe | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---|---|---:|---:|---:|---:|
| V7.5 | `vol_lb=40` | 1.902 | 30.43% | -14.01% | 1.782 |
| V7.6 | `vol_lb=40` | 1.967 | 31.73% | -12.07% | 1.799 |

- Current default `vol_lb=20`:

| Version | Rank | Recent weighted Sharpe | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---|---:|---:|---:|---:|---:|
| V7.5 | 2 / 4 | 1.901 | 30.94% | -13.87% | 1.811 |
| V7.6 | 2 / 4 | 1.964 | 32.27% | -12.11% | 1.825 |

- Interpretation: this parameter is broadly stable. `vol_lb=40` wins narrowly on recent weighted Sharpe, but `vol_lb=20` has better 10Y CAGR and 10Y Sharpe in both versions with essentially the same drawdown profile. `vol_lb=10` is weakest, and `vol_lb=60` is acceptable but not better than `20/40`. No default change is justified from this group.

### EMA leg volatility-scaling half-life

- Output: `docs/subb_v75_v76_parameter_stability_ema_volscale_20260507/`.
- Grid: `SUBB_V75_EMA_VOL_HALFLIFE_DAYS = 63/126/189/252`.
- Run note: final files are complete with `summary.csv` 40 rows, `rank.csv` 8 rows, and `v75_v76_compare.csv` 4 rows.
- Platform coverage by recent weighted Sharpe:

| Version | 99% within | 95% within | 90% within | 80% within |
|---|---:|---:|---:|---:|
| V7.5 | 4 / 4 | 4 / 4 | 4 / 4 | 4 / 4 |
| V7.6 | 3 / 4 | 4 / 4 | 4 / 4 | 4 / 4 |

- V7.5/V7.6 horizontal rank stability is perfect for this group: Spearman rank correlation `1.000`, exact same rank count `4 / 4`.
- Recent weighted Sharpe optima:

| Version | Candidate | Recent weighted Sharpe | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---|---|---:|---:|---:|---:|
| V7.5 | `ema_vol_halflife_days=63` | 1.906 | 30.64% | -14.04% | 1.801 |
| V7.6 | `ema_vol_halflife_days=63` | 1.972 | 31.82% | -12.19% | 1.811 |

- Current default `ema_vol_halflife_days=126`:

| Version | Rank | Recent weighted Sharpe | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---|---:|---:|---:|---:|---:|
| V7.5 | 2 / 4 | 1.901 | 30.94% | -13.87% | 1.811 |
| V7.6 | 2 / 4 | 1.964 | 32.27% | -12.11% | 1.825 |

- Interpretation: the platform is very broad. Shorter half-life `63` reacts fastest and wins narrowly on recent weighted Sharpe, but longer half-lives improve 10Y CAGR and 10Y Sharpe. The current `126` default is a balanced middle point inside the 99% platform in both versions, so no default change is justified.

## Overall Recommendations

### Recommended default changes

No parameter has enough evidence to force an immediate default change under the current objective: robust return with controlled drawdown. Most return/Sharpe improvements come from either weakening VolReg drawdown control or lowering the transaction-cost assumption, neither of which is a clean strategy-logic improvement.

### Candidate optimizations worth a separate decision

| Area | Candidate | Why it is tempting | Why not change automatically |
|---|---|---|---|
| Lookback tuple | `US_ROT_LBS = (180, 240, 390)` | Strong local high point in both V7.5 and V7.6 | Current lookback area is already a broad platform; needs a final direct default-vs-candidate run before changing production defaults |
| Absolute/rebalance thresholds | `abs_threshold=0.04`, `rebalance_threshold=1.08` for V7.6 | V7.6 rank 1 and current V7.6 default is rank 3 | V7.5 prefers `abs_threshold=0.00`; cross-version rank stability is weak, so this is version-specific tuning rather than robust family-wide tuning |
| VolReg windows | `30/120` or `40/180` | materially higher recent weighted Sharpe and CAGR | 10Y MaxDD expands to roughly `-18.6%` to `-19.0%`; this changes VolReg from drawdown-control to return-seeking behavior |
| VolReg off | disable VolReg | best return/Sharpe in sizing group | raises 10Y MaxDD by roughly 5-7 percentage points versus current VolReg default |

### Keep current defaults

| Area | Current default | Judgment |
|---|---|---|
| Official/EMA blend | V7.6 `official=25%`, `EMA=75%` | keep; it is a lower-drawdown robust point even though not the recent-Sharpe optimum |
| Target vol / vol window / max leverage | `0.25 / 40 / 2.0` | keep; sizing platform is broad and current drawdown-control objective argues against chasing VolReg-off optima |
| VolReg thresholds | `2.0 / 1.6` | keep; tighter `1.8 / 1.4` is dominated |
| Transaction cost | `commission=0.0010` | keep unless real execution cost assumption is changed; `0.0005` improvement is mainly cost-model sensitivity |
| Minimum turnover | `0.00` | keep; `0.01` is only marginally better and does not justify adding another execution gate by itself |
| Volatility weighting lookback | `US_ROT_VOL_LB = 20` | keep; `40` wins recent Sharpe by a hair, but `20` has better 10Y CAGR and Sharpe |
| EMA vol-scale half-life | `126` | keep; `63` wins recent Sharpe narrowly, but `126/189/252` have better long-window CAGR/Sharpe profiles |

### Practical next step

If changing only one thing after this scan, test `US_ROT_LBS = (180, 240, 390)` as a formal candidate against the current defaults in a single same-run comparison. It is the cleanest potential optimization because it improves inside a broad local platform without relying on lower cost assumptions or higher drawdown tolerance. The thresholds candidate `abs=0.04 / rebalance=1.08` is second priority, but should be treated as V7.6-specific because V7.5 does not agree.

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

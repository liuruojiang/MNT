# Sub-A / ADK / Sub-B V7.5 vs V7.6 Return, Drawdown, Holding, and Leverage Compare - 2026-05-07

## Scope

2026-05-08 validity note: this report compares the local source files as rerun on 2026-05-07. It is now historical after the V7.5 follow-up sync of `CN_SA_VOLUME_CYB_MA=15` and `CN_SA_VOLUME_CYB_DAYS=5`.

This report compared local source files:

- `mnt_bot V 7.5 plus.py`
- `mnt_bot V 7.6 plus.py`

The measured sleeves are:

- Sub-A: `cn_result`
- ADK / Sub-A-DK: `cn_dk_result`
- Sub-B: `us_rot_result`

Published windows are `10Y`, `8Y`, `5Y`, `3Y`, and `1Y`, all ending on `2026-05-06`.

## Method

Both versions were rerun through the formal local path:

```powershell
CombinedStrategyV75._fetch_data(
    msg,
    include_cn_live_snapshot=False,
    include_us_live_snapshot=False,
)
CombinedStrategyV75._run_strategies(
    cn_close,
    cn_dk_close,
    us_rot_close,
    us_prod_daily,
    allow_unresolved_suba_volume=False,
)
```

Metric definitions:

- Annualized return: compounded from the sleeve daily `return` column inside each window.
- Max drawdown: max drawdown from the sleeve daily NAV rebuilt from daily `return`.
- Holding time: count and ratio of days where `weight > 0`.
- Leverage: average `weight` across all days in the window.
- Held-day leverage: average `weight` only on days where `weight > 0`.
- Median held-day leverage is shown to distinguish persistent high leverage from low-exposure/cash days.
- For Sub-B, which is a multi-asset sleeve, leverage is computed from the sum of `actual_w_*` absolute weights. Holding time is defined as days with non-`BIL` risky exposure greater than zero.

The run used current-code parameters. Important checked values:

| Parameter | V7.5 | V7.6 |
|---|---:|---:|
| `CN_R2_THRESHOLD` | 0.30 | 0.20 |
| `CN_SWITCH_BUFFER` | 1.06 | 1.03 |
| `CN_TARGET_VOL` | 0.20 | 0.30 |
| `CN_VOL_WINDOW` | 60 | 80 |
| `CN_SCALE_THRESHOLD` | 0.15 | 0.00 |
| `CN_SA_VOLUME_SCALE` | 0.25 | 0.25 |
| `CN_SA_VOLUME_CYB_MA` | 10 | 15 |
| `CN_SA_VOLUME_CYB_DAYS` | 3 | 5 |
| `CN_DK_RISK_GATE_ENABLED` | False | True |
| `CN_DK_VOLUME_POLICY` | warning_only | warning_only |

Run audit:

| Version | Sleeve | Rows | Start | End |
|---|---|---:|---|---|
| V7.5 | Sub-A | 3786 | 2010-09-29 | 2026-05-06 |
| V7.6 | Sub-A | 3786 | 2010-09-29 | 2026-05-06 |
| V7.5 | ADK | 3752 | 2010-11-22 | 2026-05-06 |
| V7.6 | ADK | 3752 | 2010-11-22 | 2026-05-06 |
| V7.5 | Sub-B | 4374 | 2008-12-15 | 2026-05-06 |
| V7.6 | Sub-B | 4374 | 2008-12-15 | 2026-05-06 |

## Sub-B Parameter Changes

Current-code `US_ROT_*` and `SUBB_*` diff shows three direct Sub-B parameter differences:

| Parameter | V7.5 | V7.6 | Effect |
|---|---:|---:|---|
| `US_ROT_LBS` | `(130, 260, 390)` | `(160, 260, 390)` | V7.6 lengthens the short lookback leg from 130 to 160 trading days. Mid and long lookbacks are unchanged. |
| `SUBB_V75_OFFICIAL_WEIGHT` | 0.50 | 0.25 | V7.6 reduces the official macro-gated leg contribution. |
| `SUBB_V75_EMA_WEIGHT` | 0.50 | 0.75 | V7.6 increases the EMA base-7 leg contribution. |

Core Sub-B rotation, sizing, and cost parameters are unchanged:

| Parameter | V7.5 | V7.6 |
|---|---:|---:|
| `US_ROT_TARGET_VOL` | 0.25 | 0.25 |
| `US_ROT_MAX_LEV` | 2.0 | 2.0 |
| `US_ROT_VOL_WINDOW` | 40 | 40 |
| `US_ROT_VOL_LB` | 20 | 20 |
| `US_ROT_MIN_TURNOVER` | 0.0 | 0.0 |
| `US_ROT_ABS_THRESHOLD` | 0.04 | 0.04 |
| `US_ROT_REBALANCE_THRESHOLD` | 1.05 | 1.05 |
| `US_ROT_COMMISSION` | 0.001 | 0.001 |

EMA leg parameters are unchanged except for the blend weight:

| Parameter | V7.5 | V7.6 |
|---|---:|---:|
| `SUBB_V75_EMA_HALF_LIFE` | 100 | 100 |
| `SUBB_V75_EMA_ABS_THRESHOLD` | 0.16 | 0.16 |
| `SUBB_V75_EMA_VOL_MODE` | `ewma6m_1vol` | `ewma6m_1vol` |
| `SUBB_V75_EMA_VOL_HALFLIFE_DAYS` | 126 | 126 |

VolReg parameters are unchanged:

| Parameter | V7.5 | V7.6 |
|---|---:|---:|
| `US_ROT_VOLREG_ENABLED` | True | True |
| `US_ROT_VOLREG_SHORT_W` | 10 | 10 |
| `US_ROT_VOLREG_LONG_W` | 250 | 250 |
| `US_ROT_VOLREG_THRESHOLD` | 2.0 | 2.0 |
| `US_ROT_VOLREG_EXIT_THRESHOLD` | 1.6 | 1.6 |

Sub-B universe is unchanged:

| Group | Assets |
|---|---|
| Base assets | `QQQ`, `EMXC`, `EFA`, `GLD`, `TLT`, `DBC`, `BTC-USD` through live/proxy mappings `QQQM`, `EMXC`, `VEA`, `GLDM`, `VGLT`, `PDBC`, `IBIT` |
| Macro assets | `UUP`, `DBMF`, `KMLM` |
| Safe asset | `BIL` |
| Levered asset subset | `QQQ`, `GLD` only |

Sub-B implementation path:

- Official leg: macro-gated `run_us_rotation_mix(...)`.
- EMA leg: base-7-only `run_subb_v75_ema_base7_rotation(...)`.
- Blend: `blend_subb_v75_results(...)`, using the version-specific official/EMA weights above.
- VolReg: applied after blend when `US_ROT_VOLREG_ENABLED=True`.
- Execution model: T close signal to T+1 adjusted open execution using `us_open`.

## ADK Parameter Changes

Current-code `CN_DK_*` diff shows only two direct parameter differences:

| Parameter | V7.5 | V7.6 | Effect |
|---|---:|---:|---|
| `CN_DK_RISK_GATE_ENABLED` | False | True | V7.6 enables the ADK drawdown risk gate. |
| `CN_DK_VOLUME_CLEAR_SCALE` | missing | 0.0 | V7.6 adds a formal clear-scale constant for the DK volume-clear helper. Current source only defines `apply_dk_volume_clear_overlay(...)`; the formal `_run_strategies(...)` path does not call it, and the current ADK parameter display keeps volume as warning-only with no position, return, or NAV effect. |

ADK drawdown risk gate:

| Parameter | V7.5 | V7.6 | Meaning |
|---|---:|---:|---|
| `CN_DK_RISK_GATE_ENABLED` | False | True | Whether the strategy-level drawdown gate is active. |
| `CN_DK_RISK_GATE_ENTER` | 0.15 | 0.15 | Prior-day raw strategy drawdown trigger. |
| `CN_DK_RISK_GATE_EXIT` | 0.08 | 0.08 | Recovery threshold before returning to full exposure. |
| `CN_DK_RISK_GATE_DEFENSE_SCALE` | 0.5 | 0.5 | Defensive exposure multiplier after trigger. |
| `CN_DK_RISK_GATE_COOLDOWN_DAYS` | 0 | 0 | No additional cooldown after recovery condition. |

The risk-gate rule is T+1 style: if prior-day raw DD is at or below `-15%`, the next day uses `0.5x` defensive exposure; once in defense, it returns to full exposure only after prior-day raw DD improves to at least `-8%`.

ADK volume-warning / clear-rule parameters:

| Parameter | V7.5 | V7.6 | Meaning |
|---|---:|---:|---|
| `CN_DK_VOLUME_POLICY` | warning_only | warning_only | Volume rule is advisory / warning-only in current published parameter text. |
| `CN_DK_VOLUME_YELLOW_SECID` | `1.000300` | `1.000300` | HS300 amount monitor. |
| `CN_DK_VOLUME_YELLOW_LABEL` | `沪深300` | `沪深300` | Monitor label. |
| `CN_DK_VOLUME_YELLOW_MA` | 40 | 40 | Amount moving-average window. |
| `CN_DK_VOLUME_YELLOW_DAYS` | 16 | 16 | Consecutive below-MA days for warning. |
| `CN_DK_VOLUME_CLEAR_SCALE` | missing | 0.0 | New V7.6 helper constant; current formal path does not call the clear overlay, and displayed rule says position remains unchanged because policy is warning-only. |

Core ADK rotation and leverage parameters are unchanged:

| Parameter | V7.5 | V7.6 |
|---|---:|---:|
| `CN_DK_BIAS_N` | 60 | 60 |
| `CN_DK_MOM_DAY` | 20 | 20 |
| `CN_DK_VOL_SCALE_ENABLED` | True | True |
| `CN_DK_TARGET_VOL` | 0.20 | 0.20 |
| `CN_DK_VOL_WINDOW` | 30 | 30 |
| `CN_DK_MAX_LEV` | 1.5 | 1.5 |
| `CN_DK_MIN_LEV` | 0.1 | 0.1 |
| `CN_DK_SCALE_THRESHOLD` | 0.10 | 0.10 |
| `CN_DK_TRADING_DAYS` | 242 | 242 |
| `CN_DK_TOP_N` | 1 | 1 |
| `CN_DK_COMMISSION` | 0.0005 | 0.0005 |

ADK overlay parameters other than the risk-gate switch are unchanged:

| Parameter | V7.5 | V7.6 |
|---|---:|---:|
| `CN_DK_PAIR_SCORE_DECAY_ENABLED` | True | True |
| `CN_DK_PAIR_SCORE_DECAY_RATIO` | 0.40 | 0.40 |
| `CN_DK_PAIR_SCORE_RECOVERY_RATIO` | 0.70 | 0.70 |
| `CN_DK_PAIR_SCORE_DERISK_SCALE` | 0.0 | 0.0 |
| `CN_DK_SAME_SIDE_OVERHEAT_ENABLED` | True | True |
| `CN_DK_SAME_SIDE_OVERHEAT_ENTER` | 0.22 | 0.22 |
| `CN_DK_SAME_SIDE_OVERHEAT_EXIT` | 0.18 | 0.18 |
| `CN_DK_SAME_SIDE_OVERHEAT_DERISK_SCALE` | 0.0 | 0.0 |

ADK universe and pair set are unchanged:

| Item | V7.5 | V7.6 |
|---|---|---|
| Columns | `DK_ZZ1000`, `DK_SZ50`, `DK_HS300`, `DK_ZZ500`, `DK_CYB` | Same |
| Human names | 中证1000, 上证50, 沪深300, 中证500, 创业板 | Same |
| Daily selected pairs | All 10 pair combinations from the 5 indices; top 1 pair selected each day | Same |

## Sub-A Comparison

| Window | V7.5 Ann. Ret. | V7.6 Ann. Ret. | V7.5 Max DD | V7.6 Max DD | V7.5 Holding Time | V7.6 Holding Time | V7.5 Leverage | V7.6 Leverage | V7.5 Held Lev. | V7.6 Held Lev. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10Y | 25.49% | 30.71% | -16.60% | -19.40% | 1498/2427 = 61.7% | 1578/2427 = 65.0% | 0.62x | 0.73x | 1.01x | 1.12x |
| 8Y | 31.35% | 37.30% | -14.76% | -19.40% | 1184/1941 = 61.0% | 1249/1941 = 64.3% | 0.61x | 0.72x | 1.00x | 1.11x |
| 5Y | 32.26% | 33.83% | -13.26% | -19.40% | 734/1211 = 60.6% | 764/1211 = 63.1% | 0.63x | 0.72x | 1.05x | 1.14x |
| 3Y | 38.77% | 49.77% | -9.08% | -12.65% | 396/725 = 54.6% | 411/725 = 56.7% | 0.55x | 0.62x | 1.00x | 1.09x |
| 1Y | 87.54% | 113.60% | -6.27% | -6.21% | 151/243 = 62.1% | 145/243 = 59.7% | 0.68x | 0.74x | 1.09x | 1.23x |

Held-day leverage details:

| Window | V7.5 Held Lev. Median | V7.6 Held Lev. Median | V7.5 Max Lev. | V7.6 Max Lev. |
|---|---:|---:|---:|---:|
| 10Y | 1.15x | 1.50x | 1.50x | 1.50x |
| 8Y | 1.17x | 1.50x | 1.50x | 1.50x |
| 5Y | 1.44x | 1.50x | 1.50x | 1.50x |
| 3Y | 1.10x | 1.50x | 1.50x | 1.50x |
| 1Y | 1.44x | 1.50x | 1.50x | 1.50x |

Sub-A readout:

- V7.6 has higher annualized return in every measured window.
- V7.6 has deeper drawdown in 10Y, 8Y, 5Y, and 3Y; 1Y drawdown is effectively tied.
- V7.6 carries higher all-day leverage and higher held-day leverage. Its held-day median is at the 1.50x cap in all reported windows.
- The return lift is therefore not free; it comes with higher effective exposure and a deeper multi-year drawdown profile.

## ADK Comparison

| Window | V7.5 Ann. Ret. | V7.6 Ann. Ret. | V7.5 Max DD | V7.6 Max DD | V7.5 Holding Time | V7.6 Holding Time | V7.5 Leverage | V7.6 Leverage | V7.5 Held Lev. | V7.6 Held Lev. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10Y | 28.78% | 26.92% | -20.78% | -18.00% | 2358/2426 = 97.2% | 2358/2426 = 97.2% | 1.14x | 1.07x | 1.17x | 1.10x |
| 8Y | 33.26% | 32.31% | -19.74% | -17.81% | 1881/1940 = 97.0% | 1881/1940 = 97.0% | 1.14x | 1.13x | 1.17x | 1.16x |
| 5Y | 29.49% | 28.01% | -19.74% | -17.81% | 1178/1211 = 97.3% | 1178/1211 = 97.3% | 1.13x | 1.11x | 1.16x | 1.15x |
| 3Y | 27.01% | 24.59% | -19.74% | -17.81% | 701/725 = 96.7% | 701/725 = 96.7% | 1.15x | 1.12x | 1.19x | 1.16x |
| 1Y | 27.21% | 27.05% | -16.58% | -15.84% | 236/243 = 97.1% | 236/243 = 97.1% | 1.13x | 1.10x | 1.17x | 1.14x |

Held-day leverage details:

| Window | V7.5 Held Lev. Median | V7.6 Held Lev. Median | V7.5 Max Lev. | V7.6 Max Lev. |
|---|---:|---:|---:|---:|
| 10Y | 1.18x | 1.09x | 1.50x | 1.50x |
| 8Y | 1.19x | 1.17x | 1.50x | 1.50x |
| 5Y | 1.17x | 1.15x | 1.50x | 1.50x |
| 3Y | 1.34x | 1.30x | 1.50x | 1.50x |
| 1Y | 1.17x | 1.15x | 1.50x | 1.50x |

ADK readout:

- V7.5 has slightly higher annualized return in every measured ADK window.
- V7.6 has lower max drawdown in every measured ADK window.
- ADK holding time is identical across V7.5 and V7.6 in these windows; both are invested about 97% of the time.
- V7.6 has lower average leverage and lower held-day leverage, consistent with `CN_DK_RISK_GATE_ENABLED=True`.
- Compared with Sub-A, ADK is much more continuously invested, so all-day leverage and held-day leverage are close to each other.

## Sub-B Comparison

For Sub-B, holding time is non-`BIL` risky exposure time. Leverage is total absolute `actual_w_*` exposure including `BIL`; because risky exposure is positive on every reported day, all-day leverage and held-day leverage are the same in these windows.

| Window | V7.5 Ann. Ret. | V7.6 Ann. Ret. | V7.5 Max DD | V7.6 Max DD | V7.5 Risk Holding Time | V7.6 Risk Holding Time | V7.5 Leverage | V7.6 Leverage | V7.5 Held Lev. | V7.6 Held Lev. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10Y | 30.80% | 32.16% | -13.87% | -12.11% | 2514/2514 = 100.0% | 2514/2514 = 100.0% | 1.17x | 1.15x | 1.17x | 1.15x |
| 8Y | 27.61% | 29.36% | -13.87% | -12.11% | 2011/2011 = 100.0% | 2011/2011 = 100.0% | 1.15x | 1.13x | 1.15x | 1.13x |
| 5Y | 27.64% | 28.62% | -11.90% | -12.11% | 1256/1256 = 100.0% | 1256/1256 = 100.0% | 1.14x | 1.12x | 1.14x | 1.12x |
| 3Y | 37.80% | 42.26% | -11.90% | -12.11% | 752/752 = 100.0% | 752/752 = 100.0% | 1.19x | 1.18x | 1.19x | 1.18x |
| 1Y | 57.48% | 58.93% | -11.63% | -12.11% | 252/252 = 100.0% | 252/252 = 100.0% | 1.22x | 1.22x | 1.22x | 1.22x |

Sub-B exposure details:

| Window | V7.5 Median Held Lev. | V7.6 Median Held Lev. | V7.5 Avg Risky Exposure | V7.6 Avg Risky Exposure | V7.5 Avg BIL | V7.6 Avg BIL | V7.5 Max Lev. | V7.6 Max Lev. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 10Y | 1.13x | 1.10x | 1.04x | 0.99x | 0.13x | 0.16x | 1.74x | 1.65x |
| 8Y | 1.11x | 1.09x | 1.01x | 0.97x | 0.13x | 0.16x | 1.74x | 1.65x |
| 5Y | 1.10x | 1.09x | 1.00x | 0.97x | 0.13x | 0.16x | 1.49x | 1.47x |
| 3Y | 1.16x | 1.16x | 1.17x | 1.14x | 0.03x | 0.04x | 1.49x | 1.47x |
| 1Y | 1.17x | 1.18x | 1.22x | 1.22x | 0.01x | 0.00x | 1.49x | 1.47x |

Sub-B readout:

- V7.6 has higher annualized return in every measured Sub-B window.
- V7.6 improves 10Y and 8Y max drawdown, is roughly tied/slightly worse in 5Y, 3Y, and 1Y max drawdown.
- V7.6 runs slightly lower average total leverage in most windows despite higher return, mainly because it shifts the blend toward the EMA leg and carries a slightly larger average `BIL` component in long windows.
- The main structural change is not target volatility, VolReg, cost, or universe. It is `US_ROT_LBS` short-window `130 -> 160` plus official/EMA blend `50/50 -> 25/75`.

## Overall Conclusion

Current V7.6 improves Sub-A return materially but does so by running more exposure and accepting deeper multi-year drawdowns. ADK moves in the opposite direction: V7.6 gives up a small amount of annualized return while reducing drawdown and realized leverage. Sub-B improves return with broadly similar or slightly lower average leverage, driven mainly by a heavier EMA leg and a longer short lookback.

Practical interpretation:

- If the goal is higher Sub-A upside, V7.6 is stronger, but the drawdown and leverage budget should be acknowledged.
- If the goal is ADK risk control, V7.6 is cleaner because the risk gate reduces drawdown with only modest return give-up.
- If the goal is Sub-B return and long-window drawdown balance, V7.6 is better than V7.5 on 10Y and 8Y. In shorter windows, V7.6's return remains higher but drawdown is not lower.
- The three sleeves should not be judged with the same exposure intuition: Sub-A is often cash/low weight, ADK is almost always invested, and Sub-B is a multi-asset blend whose leverage is the sum of asset weights.

## Verification Notes

The comparison was run from current source on 2026-05-07. Both scripts reached `2026-05-06` for CN, DK, and US Sub-B outputs. The run emitted pandas `FutureWarning` messages about future downcasting behavior in volume-signal fill operations, but the command exited successfully and produced complete metrics.

# Sub-A-DK Volume Overlay Decision Record

Date: 2026-04-30

## Scope

This record summarizes the Sub-A-DK volume-overlay research after the Sub-A volume study.

The tested path reused the current local `mnt_bot V 7.2 plus.py` DK implementation, including current pair-score decay and same-side overheat overlays. Price data came from `mnt_strategy_data_cn.csv`. Volume data came from real EastMoney daily K-line amount/volume and is cached under `raw_eastmoney_volume/`.

Timing is no-lookahead: T-day volume is treated as known after close and only affects the next DK trading day via a one-day shift. Extra exposure changes use the same two-leg commission convention as the existing DK overlays: `2 * CN_COMMISSION * current DK weight * abs(delta_scale)`.

## Baseline

Current DK baseline:

| Window | Annual | Sharpe | MaxDD |
|---|---:|---:|---:|
| Full sample, 2004-06-28 to 2026-04-17 | 21.41% | 1.11 | -40.96% |
| Last 10Y | 34.29% | 1.59 | -20.01% |
| Last 5Y | 37.47% | 1.66 | -17.37% |
| Last 3Y | 34.72% | 1.53 | -17.37% |

## Main Result

Do not add a DK volume overlay as a default rule from this scan.

The scan covered 3312 rules across:

- broad index amount below average and above average;
- DK-leg aggregate amount below average and above average;
- active pair local low/high participation;
- active pair long/short amount imbalance.

No rule passed the robust filter requiring positive annual-return, Sharpe, and drawdown deltas across 10Y, 5Y, and 3Y windows with limited full-sample return give-up.

## Best But Not Robust

The top-scored family was slow broad-market volume contraction, especially HS300 amount below MA20 for 10 consecutive days.

Best scored example:

```text
HS300 amount < MA20 for 10 consecutive days,
then scale DK exposure to 25%.
```

Observed versus current DK:

| Window | Annual delta | Sharpe delta | MaxDD delta |
|---|---:|---:|---:|
| Full sample | -0.49pp | +0.02 | +5.28pp |
| Last 10Y | -1.06pp | +0.03 | +5.28pp |
| Last 5Y | +1.14pp | +0.12 | +3.00pp |
| Last 3Y | +0.87pp | +0.12 | +3.00pp |

This is a drawdown-smoothing candidate, not a return-improving default. The 10Y annual-return drag is the key failure.

## Defensive Ridge Follow-Up

After allowing a small annual-return give-up in exchange for materially better drawdown, the HS300 low-volume family does form a usable defensive ridge.

Follow-up scan:

```text
HS300 amount < moving-average amount for N consecutive days,
then scale DK exposure.

MA grid: 10..70
Consecutive-day grid: 5..30
Scale grid: 0 / 0.25 / 0.50 / 0.75
```

Defensive pass definition:

- full annual delta >= -1.0pp;
- 10Y annual delta >= -1.5pp;
- 5Y and 3Y annual delta >= 0;
- 10Y/5Y/3Y Sharpe deltas >= 0;
- MaxDD improvement: 10Y >= 2.0pp, 5Y >= 1.5pp, 3Y >= 1.5pp.

Pass-cell count:

| Scale | Pass cells | MA range | Days range |
|---:|---:|---:|---:|
| 0.00 | 56 | 17..48 | 10..17 |
| 0.25 | 56 | 17..49 | 10..17 |
| 0.50 | 60 | 20..57 | 10..17 |
| 0.75 | 0 | - | - |

The pass cells cluster into two regions:

- fast confirmation: around `MA19..21 / days10`;
- slow confirmation: around `MA29..43 / days15..17`, with some extension into the high-40s and mid-50s depending on scale.

This is wide enough to treat as a defensive overlay candidate, but not wide enough to justify a very specific single default without checking portfolio-level interaction.

Practical candidates after the wider ridge check:

```text
Primary slow-ridge candidate:
HS300 amount < MA33 for 16 consecutive days, scale DK to 25% or 50%.

Aggressive defensive candidate:
HS300 amount < MA33 for 16 consecutive days, scale DK to 0%.

Faster but less dominant candidate:
HS300 amount < MA21 for 10 consecutive days, scale DK to 50% or 25%.
```

The `scale=0.75` version is too weak: it gives up little return but does not clear the drawdown-improvement threshold.

The stronger default candidate is the slow-ridge family around `MA31..36 / days16`. Unlike the faster `MA21 / days10` region, this area improves annual return and drawdown together across recent windows. Representative cells:

| Rule | Full annual delta | 10Y annual delta | 10Y MaxDD delta | 5Y annual delta | 3Y annual delta |
|---|---:|---:|---:|---:|---:|
| MA32 / days16 / scale0.50 | +0.23pp | +1.28pp | +3.71pp | +1.72pp | +3.69pp |
| MA33 / days16 / scale0.50 | +0.17pp | +1.46pp | +3.71pp | +1.72pp | +3.69pp |
| MA32 / days16 / scale0.25 | +0.32pp | +1.89pp | +4.30pp | +2.56pp | +5.54pp |
| MA33 / days16 / scale0.25 | +0.22pp | +2.17pp | +4.30pp | +2.56pp | +5.54pp |
| MA33 / days16 / scale0.00 | +0.26pp | +2.86pp | +4.30pp | +3.39pp | +7.39pp |

## Source Comparison

The same defensive ridge scan was also run for CSI2000 and ChiNext to avoid overfitting the HS300 result.

Common grid:

```text
MA10..70
Consecutive days 5..30
Scale 0 / 0.25 / 0.50 / 0.75
```

Pass-cell count under the same defensive standard:

| Source | Tested cells | Pass cells | Best score | Median score |
|---|---:|---:|---:|---:|
| HS300 | 6344 | 172 | 0.294 | -0.103 |
| ChiNext | 6344 | 1 | 0.220 | -0.254 |
| CSI2000 | 6344 | 0 | 0.259 | -0.351 |

Interpretation:

- HS300 has a real ridge for DK defense.
- ChiNext has only one marginal pass cell, so it is not a robust default source.
- CSI2000 can improve recent 5Y/3Y windows, but its top cells fail the 10Y drawdown-improvement requirement. It is weaker for DK than for Sub-A.

Representative cells:

| Source | Rule | Pass | Full annual delta | 10Y annual delta | 10Y MaxDD delta | 5Y annual delta | 3Y annual delta |
|---|---|---:|---:|---:|---:|---:|---:|
| HS300 | MA21 / days10 / scale0.50 | Yes | +0.06pp | -0.21pp | +3.50pp | +0.44pp | +0.62pp |
| HS300 | MA33 / days16 / scale0.50 | Yes | +0.17pp | +1.46pp | +3.71pp | +1.72pp | +3.69pp |
| ChiNext | MA31 / days16 / scale0.50 | Yes | -0.16pp | +0.85pp | +3.71pp | +0.01pp | +2.61pp |
| CSI2000 | MA28 / days11 / scale0.00 | No | -0.25pp | +1.19pp | -0.08pp | +4.33pp | +7.69pp |

So the current DK volume candidate should be HS300-based, not CSI2000/ChiNext-based. CSI2000 and ChiNext remain more relevant to Sub-A, where they represent small-cap/growth risk appetite directly.

## Negative Results

- Low-volume rules helped Sub-A more clearly than DK. DK already has vol scaling, score decay, and same-side overheat controls, so broad participation filters mostly duplicate existing risk reduction.
- Active-pair local volume did not form a useful ridge. Current pair leg volume, small/growth leg volume, and long/short volume imbalance all ranked below broad contraction rules.
- High-volume and crowding-style rules were weaker than low-volume rules in this scan.
- CSI2000 and ChiNext volume, which were useful for Sub-A, did not transfer cleanly to DK.

## Durable Outputs

- `summary.md`: top-level DK volume study.
- `dk_volume_rule_summary.csv`: all 3312 scanned rules plus baseline.
- `dk_volume_top80.csv`: top scored rules for inspection.
- `dk_volume_robust.csv`: robust-pass rules, empty in this run.
- `dk_volume_group_summary.csv`: family-level comparison.
- `v72_hs300_ma33_d16_s05/v72_dk_hs300_ma33_d16_s05_3y_nav.png`: V7.2 DK baseline versus V7.2 DK plus the selected HS300 volume filter over the last 3 years.

## V7.2 Three-Year Visual Check

Final chart test requested for the current V7.2 DK strategy:

```text
Baseline: current V7.2 DK path in `mnt_bot V 7.2 plus.py`
Overlay: HS300 amount < MA33 for 16 consecutive days, scale DK exposure to 0.5
Window: 2023-04-17 to 2026-04-17
```

| Strategy | Annual | Sharpe | MaxDD | Total Return |
|---|---:|---:|---:|---:|
| V7.2 DK | 34.72% | 1.53 | -17.37% | 144.58% |
| V7.2 DK + volume filter | 38.41% | 1.69 | -15.71% | 165.22% |
| Delta | +3.69pp | +0.16 | +1.66pp | +20.64pp |

This supports carrying the rule forward as the current DK volume-filter candidate before portfolio-level interaction testing.

# Sub-B Volume Overlay Initial Record

Date: 2026-04-30

## Scope

This records the first Sub-B volume-overlay pass after finishing the DK volume study.

The tested path reused the current local `mnt_bot V 7.2 plus.py` Sub-B implementation:

- `run_us_rotation_mix`;
- base ranking pool `QQQ / EMXC / EFA / GLD / TLT / DBC / BTC-USD`;
- inflation-gated macro candidates through `_subb_active_ranking_codes`;
- SPY short/long volatility regime overlay through `apply_vol_regime_overlay`.

Price data came from `mnt_strategy_data_us.csv`. Volume data came from Yahoo Finance daily volume and is cached under `raw_yfinance_volume/`.

Timing is no-lookahead: T-day volume is treated as known after close and only affects the next Sub-B trading day.

## Main Result

The first broad volume scan did not find a material Sub-B candidate.

After filtering out zero-trigger or near-zero-effect rules, no rule passed the initial robust filter. The best scored rules had tiny effects, usually less than 0.5pp annual delta in recent windows, and did not form a convincing improvement over the existing Sub-B VolReg and vol-target controls.

## Tested Families

- Broad market volume: `SPY / QQQ / IWM / DIA` amount below or above moving-average amount.
- Held-proxy volume: volume weakness in the currently held Sub-B proxy ETF.
- Grids: MA `10 / 20 / 30 / 50 / 60`, consecutive days `2 / 3 / 5 / 8 / 10 / 15`, scale `0 / 0.25 / 0.5 / 0.75`.

## Best But Weak Examples

| Rule | Trigger days | Full annual delta | 10Y annual delta | 5Y annual delta | 3Y annual delta |
|---|---:|---:|---:|---:|---:|
| DIA amount < MA30 for 15 days, scale 0.50 | 125 | -0.04pp | +0.10pp | -0.13pp | +0.28pp |
| DIA amount > MA10 for 8 days, scale 0.50 | 63 | -0.03pp | -0.11pp | +0.05pp | +0.42pp |
| Held proxy amount < MA30 for 15 days, scale 0.00 | 37 | +0.11pp | +0.00pp | +0.00pp | +0.00pp |

These are too small and sparse to justify a default rule.

## Interpretation

Simple volume contraction/expansion is much weaker for Sub-B than it was for Sub-A and weaker than the HS300 volume ridge found for DK. Sub-B already contains:

- weekly multi-window momentum selection;
- inverse-vol weighting;
- 25% target-vol scaling;
- SPY VolReg risk overlay;
- inflation-gated macro candidate expansion.

The first pass suggests that plain volume overlays mostly duplicate existing risk controls or trigger in periods where Sub-B is already defensive.

## Durable Outputs

- `summary.md`: top-level scan summary.
- `subb_volume_rule_summary.csv`: all scanned rules.
- `subb_volume_top100.csv`: top scored rules.
- `subb_volume_robust.csv`: robust-pass rules; empty after the corrected filter.
- `subb_volume_group_summary.csv`: family-level comparison.

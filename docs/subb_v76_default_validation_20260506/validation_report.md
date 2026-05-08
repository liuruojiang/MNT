# Sub-B V7.6 Default Validation - 2026-05-06

- Selected finalist: `formal_core_lb160_260_390_macro_gate_abs0.04_ow0.25`
- Script: `mnt_bot V 7.6 plus.py`
- Data: 2007-05-30 -> 2026-05-05, rows=4764, weekend_rows=0
- Common compare rows: 4373 (2008-12-15 -> 2026-05-05)
- Actual extra dates beyond stored finalist file: 0
- Same-run default vs explicit selected rows: 4373
- Same-run max absolute return diff: `0`
- Same-run nonzero diffs > 1e-12: `0`
- Stored finalist CSV max absolute return diff: `6.64534914931e-05`
- Stored finalist CSV nonzero diffs > 1e-12: `4206`

The same-run parity check validates the promoted defaults against an explicit selected-candidate configuration on the current fetched data. The stored finalist CSV comparison is retained as a historical-output drift check because Yahoo/Stooq adjusted data can refresh between runs.

## Defaults

| Parameter | Value |
|---|---:|
| `lbs` | `(160, 260, 390)` |
| `official_pool_mode` | `macro_gate` |
| `top_n` | `3` |
| `abs_threshold` | `0.04` |
| `rebalance_threshold` | `1.05` |
| `min_turnover` | `0.0` |
| `official_weight` | `0.25` |
| `ema_weight` | `0.75` |
| `ema_half_life` | `100` |
| `ema_abs_threshold` | `0.16` |
| `target_vol` | `0.25` |
| `vol_window` | `40` |
| `max_lev` | `2.0` |
| `volreg_enabled` | `True` |
| `volreg_enter` | `2.0` |
| `volreg_exit` | `1.6` |

# Sub-A 7.x Effective Momentum Display Fix - 2026-05-07

## Conclusion

This change only fixes the display path for the Sub-A parameter page section named "effective vs current momentum". It does not change formal backtest returns, holdings, weights, trade costs, or NAV.

Before the fix, the display treated the latest `is_signal=True` row as the effective momentum date. That can be wrong when the same asset remains held and later actions only rebalance, resize, recover from risk controls, or apply volume rules.

After the fix, effective momentum uses the first day of the current continuous holding period. Current momentum still uses the latest realtime or close snapshot.

## Scope

Touched scripts:

- `mnt_bot V 7.0 plus.py`
- `mnt_bot V 7.1 plus.py`
- `mnt_bot V 7.2 plus.py`
- `mnt_bot V 7.3 plus.py`
- `mnt_bot V 7.5 plus.py`
- `mnt_bot V 7.6 plus.py`

Changes:

- `_build_suba_momentum_rank_rows()` now derives `effective_pos` from the start of the current continuous `holding` segment.
- The parameter-page explanatory text now says the effective column is the current holding start confirmation date.

Regression tests:

- `tests/test_suba_effective_momentum_holding_start.py`
- `tests/test_v75_live_params_current_us_w_scope.py`

## Measured Impact

The V7.6 source-level comparison against the pre-fix backup showed zero differences in formal Sub-A results:

- `return`: max absolute diff `0`
- `nav`: max absolute diff `0`
- `weight`: max absolute diff `0`
- `holding_fraction`: max absolute diff `0`
- `effective_turnover`: max absolute diff `0`
- `trade_cost`: max absolute diff `0`
- `holding`, `target`, and `is_signal`: mismatched rows `0`

Measured data path:

- Source data: `mnt_strategy_data_cn.csv`
- Formal chain: `run_cn_strategy()` -> `apply_suba_cash_peak_decay_overlay()` -> `apply_suba_same_side_overheat_overlay()` -> `apply_suba_volume_overlay()`
- Input date range: 2010-06-01 to 2026-04-30, 3865 rows
- Sub-A result range: 2010-09-29 to 2026-04-30, 3785 rows

## Backup

Backups created before the script edits:

- `.codex_backups/20260507_000722/mnt_bot V 7.6 plus.py`
- `.codex_backups/20260507_002912/mnt_bot V 7.0 plus.py`
- `.codex_backups/20260507_002912/mnt_bot V 7.1 plus.py`
- `.codex_backups/20260507_002912/mnt_bot V 7.2 plus.py`
- `.codex_backups/20260507_002912/mnt_bot V 7.3 plus.py`
- `.codex_backups/20260507_002912/mnt_bot V 7.5 plus.py`

## Verification

Commands used:

```powershell
python tests\test_suba_effective_momentum_holding_start.py
python -m unittest discover -s tests -p "test_v75_live_params_current_us_w_scope.py" -v
python -m py_compile "mnt_bot V 7.0 plus.py" "mnt_bot V 7.1 plus.py" "mnt_bot V 7.2 plus.py" "mnt_bot V 7.3 plus.py" "mnt_bot V 7.5 plus.py" "mnt_bot V 7.6 plus.py"
git diff --check -- "mnt_bot V 7.0 plus.py" "mnt_bot V 7.1 plus.py" "mnt_bot V 7.2 plus.py" "mnt_bot V 7.3 plus.py" "mnt_bot V 7.5 plus.py" "mnt_bot V 7.6 plus.py" "tests/test_suba_effective_momentum_holding_start.py" "tests/test_v75_live_params_current_us_w_scope.py" "docs/suba_v76_effective_momentum_display_fix_20260507.md"
```

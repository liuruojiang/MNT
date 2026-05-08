# Sub-B V7.5/V7.6 Parameter Stability Cleanup And Sync - 2026-05-07

## Scope

- User decision after review: do not change defaults. `US_ROT_LBS = (180, 240, 390)` and `abs_threshold=0.04 / rebalance_threshold=1.08` are not being promoted.
- Preserved formal research outputs under `docs/subb_v75_v76_parameter_stability_*`.
- Preserved the summary and recommendation record in `docs/subb_v75_v76_parameter_stability_notes_20260506.md`.
- Preserved the scan harness fix in `analyze_subb_parameter_stability.py`: the `volreg_windows` grid includes the current default `10/250`.

## Cleanup

Backed up removed files before deletion:

- Backup directory: `.codex_backups/20260507_101933`
- Delete manifest: `.codex_backups/cleanup_delete_paths_20260507_subb.txt`

Removed disposable local test and aborted-run helper files:

- `tests/test_v76_adk_volume_warning_only.py`
- `tests/test_v76_performance_window_reporting.py`
- `tests/test_v7x_adk_volume_warning_only.py`
- `tests/test_v7x_nav_reporting_consistency.py`
- `docs/subb_v75_v76_parameter_stability_remaining_cloud_manifest_20260507.json`
- `docs/subb_v75_v76_parameter_stability_remaining_local_runner_20260507.err.log`
- `docs/subb_v75_v76_parameter_stability_remaining_local_runner_20260507.log`

## Verification

- All nine Sub-B parameter-scan groups have `summary.csv`, `rank.csv`, and `v75_v76_compare.csv`.
- Final row-count verification passed:
  - `lbs`: `90 / 18 / 9`
  - `lbs_local`: `270 / 54 / 27`
  - `blend_ema`: `150 / 30 / 15`
  - `thresholds`: `150 / 30 / 15`
  - `sizing_volreg`: `360 / 72 / 36`
  - `turnover_cost`: `200 / 40 / 20`
  - `volreg_windows`: `80 / 16 / 8`
  - `vol_weight`: `40 / 8 / 4`
  - `ema_volscale`: `40 / 8 / 4`

## Sync Notes

- Intended staged scope is limited to Sub-B scan outputs, the scan harness, this cleanup record, and the Sub-B notes file.
- Unrelated modified strategy scripts, A-share cache files, avatars, Sub-A outputs, and unrelated tracked tests are intentionally left unstaged.

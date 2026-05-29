# V7.7 Sub-A Volume Research Cleanup And Sync Record

Date: 2026-05-29

## Scope

- Preserved completed V7.7 Sub-A research artifacts under `quant_param_scan_runs/`.
- Removed generated Python bytecode caches from the workspace and scan folders.
- No production strategy code was changed in this cleanup pass.

## Preserved Research Runs

- `quant_param_scan_runs/20260523_v77_suba_v25_log_wls_cost_only`
- `quant_param_scan_runs/20260529_a_us_momentum_combo_v7_7_sub_a_target_vol_max_leverage`
- `quant_param_scan_runs/20260529_a_us_momentum_combo_v7_7_sub_a_target_vol_max_leverage_balanced_frontier`
- `quant_param_scan_runs/20260529_a_us_momentum_combo_v7_7_sub_a_no_volume_target_vol_max_leverage_balanced_frontier`
- `quant_param_scan_runs/20260529_a_us_momentum_combo_v7_7_sub_a_volume_overlay_on_off`
- `quant_param_scan_runs/20260529_a_us_momentum_combo_v7_7_sub_a_volume_field_amount_vs_volume`
- `quant_param_scan_runs/20260529_a_us_momentum_combo_v7_7_sub_a_volume_overlay_robustness_grid`
- `quant_param_scan_runs/20260529_a_us_momentum_combo_v7_7_sub_a_sub_a_volume_or_and_recovery_wait`

Each preserved run has `record.md`, `scan_meta.json`, `scan_summary.csv`, and `window_metrics.csv`.

## Cleanup

Removed only generated `__pycache__` / `.pyc` artifacts. Durable docs, outputs, scan CSVs, and metadata were kept.

## Verification

Run before sync:

- `python -m py_compile "mnt_bot V 7.7 plus.py"`
- `python -m py_compile` for active scan scripts under the preserved 2026-05-29 Sub-A folders
- `python C:\Users\Administrator.DESKTOP-95I7VVU\.codex\skills\quant-param-scan\scripts\check_quant_param_scan_artifacts.py --phase complete --strict` for finalized scan folders
- `git diff --check`

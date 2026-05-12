# V7.6 Level-8 Active Budget Cleanup and Sync - 2026-05-12

## Scope

This closeout records the final cleanup after promoting the stacked portfolio budget:

- Active dynamic budget: `advisory_suba_microcap_dd_3_10_month_end`
- Rule: Sub-A 5/8 weekly + Microcap 3/10 month-end, with Sub-B absorbing both deltas
- Benchmark and rollback: fixed `10/15/15/20/40`

## Preserved

- Production scripts:
  - `mnt_bot V 7.6 plus.py`
  - `build_v76_portfolio_nav.py`
  - `build_v76_level8_decision_dashboard.py`
  - `poe_v76_level8_advisory_bot.py`
- Portfolio manifest:
  - `portfolio_manifests/v76_current.json`
- Real-data outputs:
  - `outputs/portfolio_v76_current/`
- Decision records:
  - `docs/v76_level8_combo_decision_record_20260512.md`
  - `docs/v76_level8_suba_microcap_mixed_budget_validation_20260512.md`

## Removed

Temporary validation tests were removed after the active-stacked decision was verified:

- `tests/test_build_v76_level8_decision_dashboard.py`
- `tests/test_build_v76_portfolio_nav.py`
- `tests/test_poe_v76_level8_advisory_bot.py`
- `tests/test_run_v76_adk_b_subd_dynamic_budget_optimization.py`
- `tests/test_run_v76_suba_dynamic_budget_landing_validation.py`
- `tests/test_run_v76_suba_microcap_dynamic_budget_validation.py`
- `tests/test_run_v76_suba_subd_dynamic_budget_interaction_validation.py`
- `tests/test_v75_v76_nav_drawdown_chart.py`
- `tests/test_v76_combo_advisory_display.py`
- `tests/test_v76_five_sleeve_combo_default.py`
- `tests/test_v76_microcap_source_default.py`
- `tests/test_v76_portfolio_manifest.py`
- `tests/test_v76_suba_r2_threshold_default.py`

The two previously tracked test files already marked deleted remain part of the cleanup:

- `tests/test_cn_preopen_live_snapshot_guard.py`
- `tests/test_v76_signal_runtime_display.py`

Regenerated `__pycache__` directories were also removed.

## Backup

The test cleanup was backed up before deletion:

- `.codex_backups/20260512_165322`

## Verification

Pre-cleanup verification passed:

- `python build_v76_portfolio_nav.py`
- `python build_v76_level8_decision_dashboard.py`
- `python -m unittest discover -s tests -p 'test_build_v76_portfolio_nav.py' -v`
- `python -m unittest discover -s tests -p 'test_build_v76_level8_decision_dashboard.py' -v`
- `python -m unittest discover -s tests -p 'test_v76_combo_advisory_display.py' -v`
- `python -m unittest discover -s tests -p 'test_poe_v76_level8_advisory_bot.py' -v`
- `python -m py_compile build_v76_portfolio_nav.py build_v76_level8_decision_dashboard.py poe_v76_level8_advisory_bot.py "mnt_bot V 7.6 plus.py"`

Post-cleanup verification should use script-level checks because the temporary tests were intentionally removed.

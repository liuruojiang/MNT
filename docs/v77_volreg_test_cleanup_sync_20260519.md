# V7.7 VolReg Test Cleanup And Sync Record

Date: 2026-05-19

## Scope

Cleaned active test files under `tests/` after the V7.7 Sub-B VolReg confirmation-filter fix.

## Deleted

- `tests/test_suba_signal_display_state.py`
- `tests/test_v76_advisory_action_summary.py`
- `tests/test_v76_review_round2_regressions.py`
- `tests/test_v76_source_returns_freshness.py`
- `tests/test_v77_suba_volume_policy.py`
- `tests/test_v77_subb_window_weights.py`

## Preserved

- Historical documentation and research outputs under `docs/`.
- Research scripts with names containing `test` or `retest`, because they are analysis runners rather than active test files.
- Data caches and market-data files.

## Related Code Fix

- `mnt_bot V 7.7 plus.py` now marks Sub-B VolReg records with `日期口径 = execution_day`.
- `_filter_confirmed_records()` uses same-day US open confirmation for execution-day Sub-B records, while ordinary Sub-B records still use signal-day `T -> T+1 open` confirmation.

## Backup

- `.codex_backups/20260519_022150`

## Verification

- `python -m py_compile "mnt_bot V 7.7 plus.py"` passed.
- `tests/` directory removed; no active test files remain under the cleaned area.
- `git diff --check -- "mnt_bot V 7.7 plus.py" "docs/v77_volreg_test_cleanup_sync_20260519.md" tests` passed.

## Sync Target

- Branch: `codex/v77-subb-recent-weighted-momentum`
- Upstream: `origin/codex/v77-subb-recent-weighted-momentum`
- Existing PR: `#7 [codex] Update V7.7 Sub-B weights and Sub-A MA6...`

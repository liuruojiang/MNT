# V7.8 Sub-A Display Snapshot Cleanup And Sync Record

Date: 2026-06-26

## Scope

Cleaned runtime test artifacts and prepared the V7.8 Sub-A display fix for cloud
sync.

## Related Production Change

- `mnt_bot V 7.8 plus.py` now builds a Sub-A display snapshot for V7.8 mixed-leg
  tables and exposure lines.
- On a confirmed signal day, the V7.7A component display uses the pre-trade
  previous-row holding and weight, while New A TV1.0 continues to use the current
  shifted holding.
- This is display-only. It does not change Sub-A return generation, target
  columns, cost logic, or the V7.8 component-net blend calculation.

## Deleted Locally

- `.pytest_cache/`
- Root `__pycache__/`
- `tests/__pycache__/`

These are ignored Python/pytest runtime artifacts and are not part of the
production strategy surface.

## Preserved

- `tests/test_v78_suba_new_signal_display.py`

The file now includes regression coverage for the signal-day V7.7A pre-trade
display snapshot and for keeping signal, live signal, and live params exposure
lines on the same display basis. It is an active regression test, not a
temporary test artifact.

## Backup

- Production script backup before the display edit:
  `.codex_backups/20260626_224340`

## Verification

- `python -m pytest tests/test_v78_suba_new_signal_display.py -q` passed:
  `25 passed, 1 warning`.
- `python -m py_compile "mnt_bot V 7.8 plus.py"` passed.
- `git diff --check -- "mnt_bot V 7.8 plus.py" "tests/test_v78_suba_new_signal_display.py" "docs/v78_suba_display_snapshot_cleanup_sync_20260626.md"` passed with LF/CRLF normalization warnings only.
- Final active workspace cache scan found no `.pytest_cache`, `__pycache__`, or
  `_pycache` directories outside preserved backup/worktree/vendor areas.

## Sync Target

- Branch: current working branch
- Remote: repository default remote

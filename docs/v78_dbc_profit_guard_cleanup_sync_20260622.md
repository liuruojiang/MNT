# V7.8 DBC/PDBC Profit Guard Cleanup And Sync Record

Date: 2026-06-22

## Scope

Cleaned temporary test and Python runtime artifacts after adding the V7.8 Sub-B
DBC/PDBC profit-giveback guard.

## Related Production Change

- `mnt_bot V 7.8 plus.py` applies a DBC/PDBC-only, price-only profit guard after
  the V7.8 Sub-B four-leg blend and after VolReg.
- Rule: if current holding-wave profit retains `<=50%` of peak profit, next
  execution scale is `0.67`; if it retains `<=25%`, next execution scale is
  `0.00`; released weight moves to `BIL`.
- The guard does not use score decay and does not apply separately inside the
  official, EMA, Bias, or LogVol legs.

## Deleted

- `tests/test_v78_yahoo_adjusted_close.py` - untracked temporary test file.
- `.pytest_cache/`
- Root `__pycache__/`
- `tests/__pycache__/`
- `quant_param_scan_runs/**/__pycache__/` under the active project tree.

## Preserved

- Tracked tests under `tests/`, including:
  - `tests/test_poe_adk_16_spread_decay.py`
  - `tests/test_v77_adk_drawdown_warning_panel.py`
  - `tests/test_v78_adk_subb_blend_display.py`
  - `tests/test_v78_cn_live_freshness.py`
  - `tests/test_v78_suba_new_signal_display.py`
- `tests/fixtures/poe_adk_snapshot_panel.csv`
- Research scripts whose names contain `test`, such as
  `run_v78_substrategy_poe_overlay_test.py`.
- Historical research outputs, scan run records, market-data caches, and
  `.codex_backups/`.

## Backup

- Code backup before the V7.8 production edit:
  `.codex_backups/20260622_161417`
- Cleanup backup before deleting the temporary test file and top-level caches:
  `.codex_backups/20260622_171719`

## Verification

- `python -m py_compile "mnt_bot V 7.8 plus.py"` passed.
- Function-level smoke confirmed the DBC/PDBC guard boundary behavior:
  `retain=50% -> next scale 0.67`, `retain=25% -> next scale 0.00`.
- `git diff --check -- "mnt_bot V 7.8 plus.py"` passed before cleanup.
- Final sync verification should include `git status --short`, targeted
  `git diff --check`, commit, and push.

## Sync Target

- Branch: `codex/v78-display-sync`
- Upstream: `origin/codex/v78-display-sync`
- Remote: `https://github.com/liuruojiang/MNT.git`

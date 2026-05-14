# V7.6 Cleanup And Cloud Sync Record - 2026-05-14

## Scope

- Kept the production V7.6 strategy changes in `mnt_bot V 7.6 plus.py`.
- Removed temporary local test/probe artifacts before syncing:
  - `.codex_email_test/`
  - `tests/test_v76_review_regressions.py`
  - `tests/__pycache__/`
- Preserved tracked tests, strategy scripts, data files, docs, outputs, archives, and `.codex_backups/`.

## Strategy Changes Retained

- Harder stale-data handling for Sub-A volume, A-share close data, A-DK close data, and Sub-B price data.
- Sub-B execution display fixes for live ETF prices, position-value calculation, proxy-to-live ticker normalization, and mixed share/amount input validation.
- CN holiday override protection through the maintained 2026 calendar, with future-year fail-closed behavior.
- Portfolio advisory freshness guards for source returns and holiday-aware required close date.
- Debug-mode traceback output via `STRATEGY_DEBUG=1`.

## Verification

- Run after cleanup:
  - `python -m py_compile "mnt_bot V 7.6 plus.py" "poe_v76_level8_advisory_bot.py"`
  - `python -m unittest discover -s tests -v`

## Backup

- Deleted artifacts were backed up under `.codex_backups/20260514_135647`.

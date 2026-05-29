# V7.7 Sub-A Volume OR/AND Recovery Wait Scan

Goal: compare OR vs AND trigger logic and recovery waits around the selected amount MA20 / ZZ3 / CYB4 / scale0 rule.

Entry point: `mnt_bot V 7.7 plus.py`
Data end: 2026-05-28 close-confirmed.

Grid:
- field: `amount`
- MA: `20`
- ZZ2000 days: `3`
- CYB days: `4`
- mode: ['or', 'and']
- recovery wait days: [0, 1, 2, 3]
- scale after trigger: `0.0`

Recovery wait definition: keep the overlay active for N extra false-signal trading days before restoring exposure; 0 means immediate restore.

Decision: research_only_no_production_change
Stability: focused_or_and_recovery_wait_close_confirmed

Outputs:
- `scan_summary.csv`
- `window_metrics.csv`
- `trigger_episodes.csv`
- `recent_status.csv`
- `daily_curves.csv`
- `summary_cards.json`

No production file was edited.

## Finalization

- Finalized at: 2026-05-29T16:25:34+08:00
- Decision: prefer_or_with_recovery_wait_0_or_1_research_only
- Stability label: or_more_defensive_and_recovery_wait_beyond_1_costly
- Complete checker: PASS

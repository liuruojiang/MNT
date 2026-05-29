# V7.7 Sub-A Volume Overlay On/Off Scan

Goal: compare current production Sub-A amount overlay against removing the overlay.

Entry point: `mnt_bot V 7.7 plus.py`
Data end: 2026-05-28 close-confirmed

Rules held constant: V7.7 Sub-A defaults. Only the Sub-A amount overlay is toggled.

Decision: research_only_no_production_change
Stability: single_toggle_current_v77_close_confirmed

Outputs:
- `scan_summary.csv`: long-format metrics by candidate and segment.
- `window_metrics.csv`: wide-format required scan table.
- `reader_summary.csv`: compact table for discussion.
- `daily_comparison.csv`: daily returns/NAV and selected state columns.
- `scan_meta.json`: data, cost, git, and rule metadata.

## Finalization

- Finalized at: 2026-05-29T14:36:34+08:00
- Decision: research_only_no_production_change
- Stability label: single_toggle_current_v77_close_confirmed
- Complete checker: PASS
- Checker warnings:
  - scan_meta.json missing recommended field: parameter_group

# V7.7 Sub-A Volume Overlay Robustness Grid

Goal: test whether the current amount-based volume overlay is robust or suspiciously point-fit.

Entry point: `mnt_bot V 7.7 plus.py`
Data end: 2026-05-28 close-confirmed.

Grid:
- fields: ['amount', 'volume']
- MA: [10, 15, 20, 30]
- ZZ2000 days: [2, 3, 4, 5]
- CYB days: [3, 4, 5, 6]
- scale after trigger: [0.0, 0.25, 0.5, 0.75]

Decision: research_only_no_production_change
Stability: deep_robustness_grid_current_v77_close_confirmed

Outputs:
- `scan_summary.csv`
- `window_metrics.csv`
- `rolling_windows.csv`
- `rolling_summary.csv`
- `summary_cards.json`
- `daily_selected.csv`

No production file was edited.

## Finalization

- Finalized at: 2026-05-29T15:18:27+08:00
- Decision: research_only_no_production_change
- Stability label: deep_robustness_grid_current_v77_close_confirmed
- Complete checker: PASS

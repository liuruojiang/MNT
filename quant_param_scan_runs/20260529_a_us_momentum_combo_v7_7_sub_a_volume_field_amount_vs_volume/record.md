# V7.7 Sub-A Amount vs Volume Overlay Scan

Goal: compare current production amount overlay against a same-parameter volume overlay.

Entry point: `mnt_bot V 7.7 plus.py`
Data end: 2026-05-28 close-confirmed

Candidates:
- `amount_overlay_current`: current production amount field.
- `volume_overlay_candidate`: same thresholds but using volume field.
- `no_overlay_reference`: no Sub-A amount/volume overlay.

Decision: research_only_no_production_change
Stability: single_field_current_v77_close_confirmed

Outputs:
- `scan_summary.csv`
- `window_metrics.csv`
- `reader_summary.csv`
- `daily_comparison.csv`
- `scan_meta.json`

## Finalization

- Finalized at: 2026-05-29T14:58:53+08:00
- Decision: research_only_no_production_change
- Stability label: single_field_current_v77_close_confirmed
- Complete checker: PASS

# Sub-A R2 Layer Scan

- Target: V7.5 Sub-A R2 window / threshold layer
- Metrics shown first: recent 10Y CAGR and MaxDD
- Modes: `isolated_r2` neutralizes downstream execution/risk overlays; `formal` restores V7.5 current settings

## Audit

- `formal`: variants `24`, data `2010-06-01` -> `2026-04-30`, rows `3865`
  - target-vol `0.3`, R2 threshold seed `0.2`, volume overlay `True`

## Top 12 By Mode And 10Y CAGR

### formal

| rank | MA | slope | R2 window | R2 threshold | 10Y CAGR | 10Y MaxDD |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 20 | 20 | 0.20 | 29.24% | -19.85% |
| 2 | 60 | 20 | 20 | 0.10 | 28.12% | -23.06% |
| 3 | 60 | 20 | 20 | 0.30 | 27.35% | -17.89% |
| 4 | 60 | 20 | 10 | 0.00 | 26.97% | -28.98% |
| 5 | 60 | 20 | 15 | 0.00 | 26.97% | -28.98% |
| 6 | 60 | 20 | 20 | 0.00 | 26.97% | -28.98% |
| 7 | 60 | 20 | 30 | 0.00 | 26.97% | -28.98% |
| 8 | 60 | 20 | 20 | 0.40 | 21.58% | -20.12% |
| 9 | 60 | 20 | 15 | 0.10 | 21.31% | -30.33% |
| 10 | 60 | 20 | 30 | 0.10 | 19.78% | -34.34% |
| 11 | 60 | 20 | 15 | 0.30 | 19.51% | -31.35% |
| 12 | 60 | 20 | 15 | 0.20 | 19.35% | -35.20% |

## Interpretation Notes

- Use `isolated_r2` to judge the R2 filter's own contribution.
- Use `formal` to judge whether the setting survives interaction with current V7.5 execution and overlays.
- Do not promote a single high-CAGR point unless nearby MA/slope and R2 settings remain acceptable.
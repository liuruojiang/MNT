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
| 1 | 60 | 20 | 20 | 0.20 | 30.25% | -19.16% |
| 2 | 60 | 20 | 20 | 0.10 | 29.73% | -21.72% |
| 3 | 60 | 20 | 10 | 0.00 | 28.31% | -28.95% |
| 4 | 60 | 20 | 15 | 0.00 | 28.31% | -28.95% |
| 5 | 60 | 20 | 20 | 0.00 | 28.31% | -28.95% |
| 6 | 60 | 20 | 30 | 0.00 | 28.31% | -28.95% |
| 7 | 60 | 20 | 20 | 0.30 | 28.21% | -17.56% |
| 8 | 60 | 20 | 15 | 0.10 | 24.02% | -24.82% |
| 9 | 60 | 20 | 20 | 0.40 | 23.08% | -19.04% |
| 10 | 60 | 20 | 15 | 0.30 | 22.46% | -28.42% |
| 11 | 60 | 20 | 15 | 0.20 | 21.95% | -31.05% |
| 12 | 60 | 20 | 30 | 0.10 | 20.10% | -32.66% |

## Interpretation Notes

- Use `isolated_r2` to judge the R2 filter's own contribution.
- Use `formal` to judge whether the setting survives interaction with current V7.5 execution and overlays.
- Do not promote a single high-CAGR point unless nearby MA/slope and R2 settings remain acceptable.
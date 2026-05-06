# Sub-A R2 Layer Scan

- Target: V7.5 Sub-A R2 window / threshold layer
- Metrics shown first: recent 10Y CAGR and MaxDD
- Modes: `isolated_r2` neutralizes downstream execution/risk overlays; `formal` restores V7.5 current settings

## Audit

- `formal`: variants `24`, data `2010-06-01` -> `2026-04-30`, rows `3865`
  - target-vol `0.2`, R2 threshold seed `0.3`, volume overlay `True`

## Top 12 By Mode And 10Y CAGR

### formal

| rank | MA | slope | R2 window | R2 threshold | 10Y CAGR | 10Y MaxDD |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 20 | 20 | 0.20 | 27.07% | -19.85% |
| 2 | 60 | 20 | 20 | 0.10 | 26.79% | -22.92% |
| 3 | 60 | 20 | 20 | 0.30 | 25.58% | -17.89% |
| 4 | 60 | 20 | 10 | 0.00 | 24.03% | -27.99% |
| 5 | 60 | 20 | 15 | 0.00 | 24.03% | -27.99% |
| 6 | 60 | 20 | 20 | 0.00 | 24.03% | -27.99% |
| 7 | 60 | 20 | 30 | 0.00 | 24.03% | -27.99% |
| 8 | 60 | 20 | 20 | 0.40 | 20.81% | -20.11% |
| 9 | 60 | 20 | 15 | 0.10 | 20.01% | -28.91% |
| 10 | 60 | 20 | 30 | 0.10 | 18.92% | -33.53% |
| 11 | 60 | 20 | 15 | 0.30 | 17.99% | -31.35% |
| 12 | 60 | 20 | 30 | 0.20 | 17.67% | -27.09% |

## Interpretation Notes

- Use `isolated_r2` to judge the R2 filter's own contribution.
- Use `formal` to judge whether the setting survives interaction with current V7.5 execution and overlays.
- Do not promote a single high-CAGR point unless nearby MA/slope and R2 settings remain acceptable.
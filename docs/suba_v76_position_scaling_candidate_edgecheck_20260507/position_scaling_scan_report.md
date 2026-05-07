# Sub-A Position Scaling Layer Scan

- Target: target volatility, realized-vol window, and scale adjustment threshold
- Metrics shown first: recent 10Y CAGR and MaxDD
- Modes: `isolated_scaling` disables downstream overlays; `formal` restores V7.5 overlays

## Audit

- `formal`: variants `36`, data `2010-06-01` -> `2026-05-06`, rows `3866`
  - min/max leverage `0.1` / `1.5`, volume overlay `True`

## Top 12 By Mode And 10Y CAGR

### formal

| rank | MA | slope | R2 | buffer | entry | tvol | vwin | scale th | 10Y CAGR | 10Y MaxDD |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.28 | 160 | 0.20 | 34.61% | -17.41% |
| 2 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.28 | 140 | 0.20 | 34.59% | -17.41% |
| 3 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.28 | 160 | 0.15 | 34.55% | -17.41% |
| 4 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.28 | 140 | 0.15 | 34.14% | -17.41% |
| 5 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.28 | 140 | 0.10 | 33.92% | -17.33% |
| 6 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.25 | 140 | 0.10 | 33.86% | -17.35% |
| 7 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.23 | 160 | 0.20 | 33.80% | -17.41% |
| 8 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.28 | 120 | 0.20 | 33.58% | -17.05% |
| 9 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.25 | 160 | 0.15 | 33.58% | -17.41% |
| 10 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.23 | 140 | 0.20 | 33.53% | -17.41% |
| 11 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.28 | 100 | 0.20 | 33.49% | -17.41% |
| 12 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.28 | 160 | 0.10 | 33.44% | -16.58% |

## Interpretation Notes

- Higher target volatility can raise CAGR by leverage but must be judged against drawdown.
- `scale_threshold=0` updates exposure continuously; larger thresholds reduce adjustment churn.
- Keep the final decision anchored to 10Y CAGR/MaxDD first, then verify 3Y/5Y windows.
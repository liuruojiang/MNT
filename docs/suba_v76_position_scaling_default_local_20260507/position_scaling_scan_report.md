# Sub-A Position Scaling Layer Scan

- Target: target volatility, realized-vol window, and scale adjustment threshold
- Metrics shown first: recent 10Y CAGR and MaxDD
- Modes: `isolated_scaling` disables downstream overlays; `formal` restores V7.5 overlays

## Audit

- `formal`: variants `27`, data `2010-06-01` -> `2026-05-06`, rows `3866`
  - min/max leverage `0.1` / `1.5`, volume overlay `True`

## Top 12 By Mode And 10Y CAGR

### formal

| rank | MA | slope | R2 | buffer | entry | tvol | vwin | scale th | 10Y CAGR | 10Y MaxDD |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.33 | 100 | 0.00 | 34.14% | -17.41% |
| 2 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.33 | 100 | 0.05 | 34.11% | -17.41% |
| 3 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.33 | 100 | 0.10 | 34.11% | -17.41% |
| 4 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.33 | 80 | 0.00 | 34.07% | -17.41% |
| 5 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.33 | 60 | 0.05 | 34.00% | -17.39% |
| 6 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.33 | 60 | 0.00 | 33.96% | -17.41% |
| 7 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.33 | 60 | 0.10 | 33.96% | -17.39% |
| 8 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.30 | 80 | 0.00 | 33.93% | -17.41% |
| 9 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.33 | 80 | 0.05 | 33.82% | -17.21% |
| 10 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.30 | 80 | 0.05 | 33.81% | -17.12% |
| 11 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.30 | 80 | 0.10 | 33.78% | -17.12% |
| 12 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.30 | 100 | 0.00 | 33.78% | -17.41% |

## Interpretation Notes

- Higher target volatility can raise CAGR by leverage but must be judged against drawdown.
- `scale_threshold=0` updates exposure continuously; larger thresholds reduce adjustment churn.
- Keep the final decision anchored to 10Y CAGR/MaxDD first, then verify 3Y/5Y windows.
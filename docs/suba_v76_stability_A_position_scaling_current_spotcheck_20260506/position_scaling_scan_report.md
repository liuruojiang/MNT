# Sub-A Position Scaling Layer Scan

- Target: target volatility, realized-vol window, and scale adjustment threshold
- Metrics shown first: recent 10Y CAGR and MaxDD
- Modes: `isolated_scaling` disables downstream overlays; `formal` restores V7.5 overlays

## Audit

- `formal`: variants `8`, data `2010-06-01` -> `2026-04-30`, rows `3865`
  - min/max leverage `0.1` / `1.5`, volume overlay `True`

## Top 12 By Mode And 10Y CAGR

### formal

| rank | MA | slope | R2 | buffer | entry | tvol | vwin | scale th | 10Y CAGR | 10Y MaxDD |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.30 | 120 | 0.15 | 29.18% | -18.54% |
| 2 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.30 | 120 | 0.00 | 28.97% | -18.64% |
| 3 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.30 | 80 | 0.00 | 28.86% | -18.64% |
| 4 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.25 | 120 | 0.00 | 28.31% | -18.64% |
| 5 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.25 | 80 | 0.00 | 28.12% | -18.64% |
| 6 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.30 | 80 | 0.15 | 27.43% | -18.64% |
| 7 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.25 | 120 | 0.15 | 27.25% | -17.24% |
| 8 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.25 | 80 | 0.15 | 27.08% | -17.16% |

## Interpretation Notes

- Higher target volatility can raise CAGR by leverage but must be judged against drawdown.
- `scale_threshold=0` updates exposure continuously; larger thresholds reduce adjustment churn.
- Keep the final decision anchored to 10Y CAGR/MaxDD first, then verify 3Y/5Y windows.
# Sub-A Position Scaling Layer Scan

- Target: target volatility, realized-vol window, and scale adjustment threshold
- Metrics shown first: recent 10Y CAGR and MaxDD
- Modes: `isolated_scaling` disables downstream overlays; `formal` restores V7.5 overlays

## Audit

- `formal`: variants `100`, data `2010-06-01` -> `2026-04-30`, rows `3865`
  - min/max leverage `0.1` / `1.5`, volume overlay `True`

## Top 12 By Mode And 10Y CAGR

### formal

| rank | MA | slope | R2 | buffer | entry | tvol | vwin | scale th | 10Y CAGR | 10Y MaxDD |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.40 | 80 | 0.05 | 30.71% | -19.16% |
| 2 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.40 | 80 | 0.10 | 30.71% | -19.16% |
| 3 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.40 | 80 | 0.15 | 30.71% | -19.16% |
| 4 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.40 | 100 | 0.00 | 30.71% | -19.16% |
| 5 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.40 | 100 | 0.10 | 30.71% | -19.16% |
| 6 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.40 | 100 | 0.15 | 30.71% | -19.16% |
| 7 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.40 | 120 | 0.00 | 30.71% | -19.16% |
| 8 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.40 | 120 | 0.05 | 30.71% | -19.16% |
| 9 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.40 | 120 | 0.10 | 30.71% | -19.16% |
| 10 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.40 | 120 | 0.15 | 30.71% | -19.16% |
| 11 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.40 | 80 | 0.00 | 30.71% | -19.16% |
| 12 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 0.35 | 120 | 0.00 | 30.71% | -19.16% |

## Interpretation Notes

- Higher target volatility can raise CAGR by leverage but must be judged against drawdown.
- `scale_threshold=0` updates exposure continuously; larger thresholds reduce adjustment churn.
- Keep the final decision anchored to 10Y CAGR/MaxDD first, then verify 3Y/5Y windows.
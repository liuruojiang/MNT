# Sub-A MA/Slope Grid Scan

- Target script: `mnt_bot V 7.5 plus.py`
- Mode: `formal`
- Entrypoint: `fetch_cn_kline()` / `_add_cn_bond_column()` / `run_cn_strategy()`
- Scanned params: `CN_BIAS_N` and `CN_MOM_DAY`; `CN_MOM_DAY <= CN_BIAS_N`; `CN_R2_WINDOW` fixed at `20`
- Baseline: `MA=60, slope=20`
- Data window: `2010-06-01` -> `2026-04-30`, rows `3865`
- Costs: `CN_COMMISSION=0.0010` single-side
- Runtime: `121.9` seconds
- Formal overlays preserved when enabled by the target script
- Fast indicator parity: max return diff `0.000e+00`, max NAV diff `0.000e+00`

## Baseline

- Baseline recent-weighted Sharpe: `1.915`; mean recent CAGR `45.04%`; worst recent MaxDD `-17.89%`

## Top 15 By Recent Weighted Sharpe

| rank | MA | slope | recent Sharpe | mean recent CAGR | worst recent MaxDD | delta Sharpe vs base |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 20 | 1.915 | 45.04% | -17.89% | 0.000 |
| 2 | 50 | 20 | 1.718 | 40.28% | -21.54% | -0.197 |
| 3 | 50 | 25 | 1.641 | 36.61% | -27.43% | -0.273 |
| 4 | 60 | 25 | 1.582 | 35.62% | -31.16% | -0.333 |
| 5 | 80 | 20 | 1.569 | 36.29% | -27.51% | -0.345 |
| 6 | 40 | 25 | 1.529 | 33.27% | -29.95% | -0.385 |
| 7 | 70 | 20 | 1.529 | 35.41% | -22.75% | -0.386 |
| 8 | 40 | 20 | 1.522 | 34.46% | -24.58% | -0.393 |
| 9 | 70 | 25 | 1.453 | 33.24% | -33.18% | -0.461 |
| 10 | 80 | 25 | 1.424 | 33.21% | -33.02% | -0.491 |
| 11 | 40 | 30 | 1.394 | 29.84% | -28.31% | -0.521 |
| 12 | 70 | 15 | 1.347 | 30.99% | -22.59% | -0.568 |
| 13 | 70 | 10 | 1.335 | 26.72% | -24.15% | -0.580 |
| 14 | 50 | 30 | 1.322 | 28.31% | -26.15% | -0.593 |
| 15 | 60 | 30 | 1.314 | 30.60% | -30.80% | -0.601 |

## Segment Notes

- Recent-weighted score = 1Y 15% + 3Y 35% + 5Y 35% + 10Y 15% Sharpe.
- Official numeric conclusions should use `rank.csv` and `summary.csv` from this same run.
- This is a Sub-A parameter scan only; it does not rescan Sub-A-DK, Sub-B, Microcap, or combo weights.

## Sources

- `1.H20955`: `csindex+Sina-proxy:1.000827`
- `0.399606`: `EastMoney`
- `1.H00016`: `csindex+Sina-proxy:1.000016`
- `1.H00852`: `csindex+Sina-proxy:1.000852`
- `1.H00905`: `csindex+Sina-proxy:1.000905`
- `1.H11077`: `fetch_cn_kline via _add_cn_bond_column`
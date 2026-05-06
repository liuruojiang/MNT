# Sub-A MA/Slope Grid Scan

- Target script: `mnt_bot V 7.6 plus.py`
- Mode: `formal`
- Entrypoint: `fetch_cn_kline()` / `_add_cn_bond_column()` / `run_cn_strategy()`
- Scanned params: `CN_BIAS_N` and `CN_MOM_DAY`; `CN_MOM_DAY <= CN_BIAS_N`; `CN_R2_WINDOW` fixed at `20`
- Baseline: `MA=60, slope=20`
- Data window: `2010-06-01` -> `2026-04-30`, rows `3865`
- Costs: `CN_COMMISSION=0.0010` single-side
- Runtime: `120.5` seconds
- Formal overlays preserved when enabled by the target script
- Fast indicator parity: max return diff `0.000e+00`, max NAV diff `0.000e+00`

## Baseline

- Baseline recent-weighted Sharpe: `2.004`; mean recent CAGR `51.96%`; worst recent MaxDD `-19.85%`

## Top 15 By Recent Weighted Sharpe

| rank | MA | slope | recent Sharpe | mean recent CAGR | worst recent MaxDD | delta Sharpe vs base |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 20 | 2.004 | 51.96% | -19.85% | 0.000 |
| 2 | 50 | 20 | 1.803 | 47.15% | -31.16% | -0.201 |
| 3 | 60 | 25 | 1.727 | 44.03% | -31.77% | -0.277 |
| 4 | 50 | 25 | 1.677 | 41.37% | -28.98% | -0.328 |
| 5 | 70 | 20 | 1.618 | 41.35% | -21.56% | -0.386 |
| 6 | 40 | 20 | 1.591 | 38.63% | -32.98% | -0.414 |
| 7 | 40 | 25 | 1.552 | 37.53% | -34.99% | -0.452 |
| 8 | 80 | 20 | 1.531 | 41.80% | -26.57% | -0.473 |
| 9 | 40 | 30 | 1.500 | 34.51% | -29.93% | -0.504 |
| 10 | 70 | 25 | 1.425 | 35.98% | -31.74% | -0.579 |
| 11 | 70 | 15 | 1.415 | 34.87% | -28.22% | -0.589 |
| 12 | 50 | 30 | 1.408 | 32.70% | -30.68% | -0.596 |
| 13 | 80 | 25 | 1.406 | 35.93% | -36.10% | -0.598 |
| 14 | 80 | 15 | 1.396 | 35.21% | -26.50% | -0.608 |
| 15 | 70 | 10 | 1.335 | 30.57% | -28.77% | -0.669 |

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
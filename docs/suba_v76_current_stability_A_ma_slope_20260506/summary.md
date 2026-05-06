# Sub-A MA/Slope Grid Scan

- Target script: `mnt_bot V 7.6 plus.py`
- Mode: `formal`
- Entrypoint: `fetch_cn_kline()` / `_add_cn_bond_column()` / `run_cn_strategy()`
- Scanned params: `CN_BIAS_N` and `CN_MOM_DAY`; `CN_MOM_DAY <= CN_BIAS_N`; `CN_R2_WINDOW` fixed at `20`
- Baseline: `MA=60, slope=20`
- Data window: `2010-06-01` -> `2026-04-30`, rows `3865`
- Costs: `CN_COMMISSION=0.0010` single-side
- Runtime: `114.8` seconds
- Formal overlays preserved when enabled by the target script
- Fast indicator parity: max return diff `0.000e+00`, max NAV diff `0.000e+00`

## Baseline

- Baseline recent-weighted Sharpe: `2.076`; mean recent CAGR `52.08%`; worst recent MaxDD `-19.16%`

## Top 15 By Recent Weighted Sharpe

| rank | MA | slope | recent Sharpe | mean recent CAGR | worst recent MaxDD | delta Sharpe vs base |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 20 | 2.076 | 52.08% | -19.16% | 0.000 |
| 2 | 50 | 20 | 1.888 | 47.70% | -30.13% | -0.188 |
| 3 | 60 | 25 | 1.807 | 44.13% | -30.95% | -0.269 |
| 4 | 50 | 25 | 1.766 | 41.92% | -28.80% | -0.310 |
| 5 | 70 | 20 | 1.753 | 43.63% | -20.46% | -0.323 |
| 6 | 80 | 20 | 1.688 | 44.45% | -25.36% | -0.388 |
| 7 | 40 | 25 | 1.664 | 39.19% | -34.30% | -0.412 |
| 8 | 40 | 20 | 1.660 | 39.38% | -31.91% | -0.415 |
| 9 | 40 | 30 | 1.589 | 34.94% | -28.72% | -0.487 |
| 10 | 70 | 25 | 1.572 | 38.20% | -28.61% | -0.504 |
| 11 | 80 | 25 | 1.539 | 37.96% | -34.09% | -0.537 |
| 12 | 50 | 30 | 1.523 | 33.98% | -27.11% | -0.553 |
| 13 | 70 | 15 | 1.488 | 35.30% | -28.43% | -0.588 |
| 14 | 80 | 15 | 1.433 | 35.18% | -25.70% | -0.643 |
| 15 | 60 | 30 | 1.429 | 35.35% | -36.68% | -0.647 |

## Segment Notes

- Recent-weighted score = 1Y 15% + 3Y 35% + 5Y 35% + 10Y 15% Sharpe.
- Official numeric conclusions should use `rank.csv` and `summary.csv` from this same run.
- This is a Sub-A parameter scan only; it does not rescan Sub-A-DK, Sub-B, Microcap, or combo weights.

## Sources

- `1.H20955`: `csindex+Sina-proxy:1.000827`
- `0.399606`: `Sina`
- `1.H00016`: `csindex+Sina-proxy:1.000016`
- `1.H00852`: `csindex+Sina-proxy:1.000852`
- `1.H00905`: `csindex+Sina-proxy:1.000905`
- `1.H11077`: `fetch_cn_kline via _add_cn_bond_column`
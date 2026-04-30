# V7.2 Inflation / Trend-Following Protection Check

Generated: 2026-04-29T20:52:42.550810+08:00

## Scope

- Rebuilt official V7.2 daily sleeve NAV through the existing V7.2 diagnostics path.
- V7.2 definition: Sub-A 10% + Sub-A-DK 15% + Microcap 15% + Sub-B 60%.
- Proxy assets came from local `mnt_strategy_data_us.csv`: SPY, TLT, GLD, DBC, BIL.
- USD proxy uses FRED `DTWEXBGS` because the local asset cache has no UUP column.
- CPI regime came from FRED `CPIAUCSL`; `high/rising` means CPI YoY >= 4% and above its level 12 months earlier.
- Simple trend proxies use prior 252 trading day total return and one-day signal lag.

## Key Window Table

| Series                    | 2021-2022 Total   | 2021-2022 MaxDD   | 2022 Shock Total   | CPI High/Rising Annual   |   CPI High/Rising Sharpe |
|:--------------------------|:------------------|:------------------|:-------------------|:-------------------------|-------------------------:|
| V7.2                      | 57.26%            | -4.98%            | 16.89%             | 23.19%                   |                     1.89 |
| SPY                       | 5.33%             | -24.50%           | -17.74%            | 2.37%                    |                     0.21 |
| TLT                       | -34.40%           | -39.56%           | -34.10%            | -14.54%                  |                    -0.63 |
| GLD                       | -4.89%            | -21.03%           | -11.14%            | 1.05%                    |                     0.16 |
| DBC                       | 68.70%            | -23.19%           | 20.89%             | 28.05%                   |                     1    |
| USD_BROAD                 | 9.08%             | -5.47%            | 10.70%             | 5.08%                    |                     0.78 |
| DBC_long_if_uptrend       | 70.60%            | -23.19%           | 20.89%             | 26.80%                   |                     0.97 |
| TLT_short_if_downtrend    | 34.07%            | -16.60%           | 35.49%             | 8.99%                    |                     0.46 |
| USD_BROAD_long_if_uptrend | 7.16%             | -5.47%            | 10.70%             | 5.32%                    |                     0.88 |
| simple_macro_trend_equal  | 21.14%            | -6.42%            | 14.71%             | 9.15%                    |                     0.96 |

## Interpretation

- V7.2 made money through the 2021-2022 inflation window, so it did have some trend-following resilience.
- It did not look like a dedicated inflation-hedging trend program: the macro trend proxies, especially commodity trend and short-bond trend, were the cleaner inflation-specific legs.
- The main gap is cross-asset trend exposure, not just portfolio-level volatility management.
- If we add anything, test a small macro-trend sleeve first: commodity trend + Treasury short trend + USD trend, then decide whether gold deserves its own switch.

## Files

- `v72_inflation_window_metrics.csv`
- `v72_inflation_cpi_regime_metrics.csv`
- `v72_inflation_correlations.csv`
- `meta.json`
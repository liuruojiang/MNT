# Stagflation Context for CTA Candidate Test

Generated: 2026-04-29T21:26:43.186033+08:00

## Stagflation Rule

- Inflation leg: CPI YoY >= 4%.
- Stagnation/stress leg: real GDP YoY <= 1.5%, or real GDP QoQ annualized <= 0%, or NBER recession flag = 1, or unemployment rate up at least 1 percentage point YoY.
- This is a regime label using revised macro data, not a tradable signal.

## Historical Windows

| start      | end        |   months |   avg_cpi_yoy |   max_cpi_yoy |   avg_gdp_yoy |   min_gdp_qoq_ann |   recession_month_share |   avg_unrate_12m_change |
|:-----------|:-----------|---------:|--------------:|--------------:|--------------:|------------------:|------------------------:|------------------------:|
| 1970-01-01 | 1971-08-01 |       20 |        0.0534 |        0.0642 |        0.0113 |           -0.0422 |                  0.5500 |                  1.4300 |
| 1973-10-01 | 1975-12-01 |       27 |        0.0990 |        0.1220 |        0.0037 |           -0.0478 |                  0.5926 |                  1.5407 |
| 1980-01-01 | 1981-03-01 |       15 |        0.1308 |        0.1459 |        0.0005 |           -0.0799 |                  0.4000 |                  1.2867 |
| 1981-07-01 | 1982-11-01 |       17 |        0.0775 |        0.1097 |        0.0065 |           -0.0607 |                  0.9412 |                  1.4412 |
| 1990-08-01 | 1991-07-01 |       12 |        0.0545 |        0.0638 |        0.0070 |           -0.0359 |                  0.6667 |                  1.0917 |
| 2008-05-01 | 2008-09-01 |        5 |        0.0496 |        0.0550 |        0.0138 |           -0.0170 |                  1.0000 |                  1.2000 |
| 2022-04-01 | 2022-06-01 |        3 |        0.0858 |        0.0898 |        0.0403 |           -0.0102 |                  0.0000 |                 -2.3000 |
| 2023-01-01 | 2023-03-01 |        3 |        0.0573 |        0.0633 |        0.0132 |            0.0279 |                  0.0000 |                 -0.3333 |

## Modern ETF-Covered Window Metrics

| window                                   | series               |   rows | total_return_fmt   | annual_fmt   |   sharpe_fmt | max_dd_fmt   |
|:-----------------------------------------|:---------------------|-------:|:-------------------|:-------------|-------------:|:-------------|
| macro_stagflation_2022-04-01_2022-06-01  | Sub-B official       |     91 | -5.29%             | -19.78%      |        -1.85 | -7.04%       |
| macro_stagflation_2022-04-01_2022-06-01  | Sub-B + DBMF         |     91 | -1.00%             | -4.00%       |        -0.1  | -5.10%       |
| macro_stagflation_2022-04-01_2022-06-01  | V7.2 official        |     91 | -1.37%             | -5.46%       |        -0.7  | -4.05%       |
| macro_stagflation_2022-04-01_2022-06-01  | V7.2 + DBMF in Sub-B |     91 | 0.73%              | 2.98%        |         0.32 | -3.95%       |
| macro_stagflation_2022-04-01_2022-06-01  | SPY                  |     49 | -13.38%            | -44.18%      |        -2.36 | -14.40%      |
| macro_stagflation_2022-04-01_2022-06-01  | DBC                  |     49 | 2.72%              | 11.51%       |         0.84 | -11.34%      |
| macro_stagflation_2022-04-01_2022-06-01  | TLT                  |     49 | 0.35%              | 1.42%        |         0.29 | -10.96%      |
| macro_stagflation_2022-04-01_2022-06-01  | GLD                  |     49 | 0.70%              | 2.85%        |         0.08 | -4.66%       |
| macro_stagflation_2022-04-01_2022-06-01  | DBMF                 |     49 | 4.64%              | 20.19%       |         1.87 | -4.92%       |
| macro_stagflation_2023-01-01_2023-03-01  | Sub-B official       |     90 | 1.40%              | 5.87%        |         0.52 | -5.31%       |
| macro_stagflation_2023-01-01_2023-03-01  | Sub-B + DBMF         |     90 | 0.27%              | 1.11%        |         0.13 | -5.02%       |
| macro_stagflation_2023-01-01_2023-03-01  | V7.2 official        |     90 | 4.26%              | 18.69%       |         2.33 | -1.73%       |
| macro_stagflation_2023-01-01_2023-03-01  | V7.2 + DBMF in Sub-B |     90 | 3.71%              | 16.11%       |         2.06 | -1.70%       |
| macro_stagflation_2023-01-01_2023-03-01  | SPY                  |     49 | 7.48%              | 35.87%       |         2.44 | -6.63%       |
| macro_stagflation_2023-01-01_2023-03-01  | DBC                  |     49 | -1.74%             | -7.20%       |        -0.95 | -8.05%       |
| macro_stagflation_2023-01-01_2023-03-01  | TLT                  |     49 | 10.77%             | 54.40%       |         3.14 | -6.46%       |
| macro_stagflation_2023-01-01_2023-03-01  | GLD                  |     49 | 6.02%              | 28.17%       |         2.09 | -6.70%       |
| macro_stagflation_2023-01-01_2023-03-01  | DBMF                 |     49 | -11.34%            | -40.03%      |        -4.09 | -11.50%      |
| dbmf_available_detected_stagflation_days | Sub-B official       |    181 | -3.96%             | -3.97%       |        -0.67 | -9.79%       |
| dbmf_available_detected_stagflation_days | Sub-B + DBMF         |    181 | -0.73%             | -0.74%       |         0.01 | -8.15%       |
| dbmf_available_detected_stagflation_days | V7.2 official        |    181 | 2.83%              | 2.84%        |         0.6  | -4.10%       |
| dbmf_available_detected_stagflation_days | V7.2 + DBMF in Sub-B |    181 | 4.46%              | 4.48%        |         1.06 | -3.95%       |
| dbmf_available_detected_stagflation_days | SPY                  |     98 | -6.18%             | -6.20%       |        -0.53 | -14.40%      |
| dbmf_available_detected_stagflation_days | DBC                  |     98 | -0.87%             | -0.88%       |         0.08 | -16.40%      |
| dbmf_available_detected_stagflation_days | TLT                  |     98 | 12.68%             | 12.72%       |         1.72 | -10.96%      |
| dbmf_available_detected_stagflation_days | GLD                  |     98 | 7.76%              | 7.79%        |         1.26 | -6.70%       |
| dbmf_available_detected_stagflation_days | DBMF                 |     98 | -7.94%             | -7.96%       |        -1.11 | -15.88%      |

## Interpretation

- The previous 2021-2022 window was a high-inflation window, not a pure stagflation window. Under this stricter rule, 2021 mostly fails the stagnation leg; 2022 is the relevant modern ETF-covered stagflation-like episode.
- Classic U.S. stagflation windows show up in the 1970s and early 1980s, but DBMF and the current ETF candidate set did not exist then.
- Therefore a true 1970s CTA test needs a managed-futures index or continuous futures data. Testing DBMF itself can only validate the modern 2022-style episode.

## Files

- `macro_monthly_regimes.csv`
- `macro_stagflation_windows.csv`
- `modern_stagflation_window_metrics.csv`
- `meta.json`
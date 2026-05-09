# Sub-D Six ETF V1.1 QVeris Robustness - 2026-05-09

## Data Source Decision

The original Sina raw close series has a material discontinuity for `159941.SZ` on 2022-07-05:

- Sina/CNFin raw close: `2022-07-04 close=2.384`, `2022-07-05 close=0.604`
- QVeris raw-like `cps=0`: `2022-07-05 preClose=0.596`, `close=0.604`, `changeRatio=+1.3423%`
- QVeris continuous `cps=3`: `2022-07-04 close=2.384`, `2022-07-05 close=2.416`, same `+1.3423%` return

Conclusion: the `-74.66%` raw close-to-close move is a split/adjustment discontinuity, not an economic return. Use QVeris `cn_financial_pro.history_quotation.v1`, `indicators=stock_common`, `interval=D`, `cps=3` for further six-ETF scans.

With QVeris `cps=3`, `159941.SZ` max absolute daily return falls to about `10.01%`; no ETF in the six-ETF pool has `>30%` daily moves in the current data-quality check.

## V1.1 Overheat Threshold Re-scan

Held fixed: new Top1 enters 50%, fills after first down close, `R2 >= 0.20`, target vol `25%`, max leverage `1.5x`.

| Overheat Enter/Exit | Annual Return | Max DD | Sharpe | Overheat Days |
|---|---:|---:|---:|---:|
| 18% / 16% | 57.67% | -16.54% | 1.876 | 30 |
| 20% / 18% | 60.46% | -16.54% | 1.932 | 17 |
| 22% / 20% | 59.09% | -18.95% | 1.887 | 7 |
| 24% / 22% | 56.98% | -18.95% | 1.828 | 3 |

Conclusion: `20% / 18%` remains the best default after switching to QVeris continuous data and after staged entry.

## R2 x Target Vol Scan

Held fixed: staged entry, MA60 overheat `20% / 18%`, max leverage `1.5x`.

| R2 | Target Vol | Annual Return | Max DD | Sharpe |
|---:|---:|---:|---:|---:|
| 0.10 | 20% | 47.42% | -14.19% | 1.915 |
| 0.10 | 25% | 60.10% | -16.42% | 1.922 |
| 0.10 | 30% | 69.19% | -18.11% | 1.904 |
| 0.20 | 20% | 47.74% | -14.30% | 1.925 |
| 0.20 | 25% | 60.46% | -16.54% | 1.932 |
| 0.20 | 30% | 69.65% | -19.14% | 1.923 |
| 0.30 | 20% | 44.11% | -14.44% | 1.819 |
| 0.30 | 25% | 54.80% | -17.20% | 1.812 |
| 0.30 | 30% | 62.48% | -19.41% | 1.808 |

Conclusion:

- Keep `R2 >= 0.20`; it is still the best Sharpe point in this grid.
- Keep target vol `25%` as the balanced default. `30%` raises annual return to `69.65%`, but max drawdown widens to `-19.14%` and Sharpe is slightly lower. `20%` is a defensive variant with much lower return and lower drawdown.

## Durable Outputs

- `outputs/subd_six_etf_data_source_validation_20260509.md`
- `outputs/subd_six_etf_159941_data_source_check_20260509.csv`
- `outputs/subd_six_etf_qveris_cps3_sources_20260509.csv`
- `outputs/subd_six_etf_qveris_cps3_data_quality_20260509.csv`
- `outputs/subd_six_etf_v1_1_qveris_overheat_scan_20260509_summary.csv`
- `outputs/subd_six_etf_v1_1_qveris_overheat_scan_20260509_daily.csv`
- `outputs/subd_six_etf_v1_1_qveris_r2_targetvol_scan_20260509_summary.csv`
- `outputs/subd_six_etf_v1_1_qveris_r2_targetvol_scan_20260509_daily.csv`

## Verification

- `python -m py_compile .\analyze_subd_six_etf_v1_1_qveris_robustness.py` passed.
- Overheat scan daily output: 13,984 rows, 4 scenarios, no duplicate `scenario_tag/date`, no missing `return/nav`.
- R2/target-vol scan daily output: 31,464 rows, 9 scenarios, no duplicate `scenario_tag/date`, no missing `return/nav`.

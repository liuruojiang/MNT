# V7.2 Portfolio Diagnostics

Date: 2026-04-29

Scope: official V7.2 composition, using `mnt_bot V 7.1 plus.py` for Sub-A/Sub-A-DK/Sub-B and `PLUS 6/microcap_top100_mom16_biweekly_live.py` for Microcap via `run_signal + apply_cost_model`.
Common daily sample: 2015-10-13 to 2026-04-17, rows=3840.

## Baseline

| Weights A/ADK/Microcap/B | Annual | Sharpe | MaxDD | Calmar |
|---|---:|---:|---:|---:|
| 10/15/15/60 | 28.59% | 2.31 | -7.20% | 3.97 |

## Correlation Read

- Highest latest 252d sleeve correlation: Sub-A/Sub-A-DK = 0.58.
- Lowest latest 252d sleeve correlation: Sub-B/Microcap = -0.20.
- Full-sample correlation matrix is saved in `v72_full_correlation.csv`; latest 252d matrix is saved in `v72_recent_252d_correlation.csv`.

## Risk Concentration

- On the latest 252d covariance view, top variance contributor is Sub-B at 67.19%.

| Sleeve | Effective Weight | 252d Vol | Corr To Portfolio | Variance Contribution |
|---|---:|---:|---:|---:|
| Sub-B | 42.85% | 17.13% | 0.77 | 67.19% |
| Sub-A-DK | 20.14% | 16.90% | 0.48 | 17.78% |
| Microcap | 30.77% | 11.32% | 0.22 | 8.56% |
| Sub-A | 6.25% | 18.05% | 0.50 | 6.47% |

## Worst Drawdown Attribution

- Worst episode: 2015-12-25 to 2016-01-15, portfolio drawdown -7.20%.

| Sleeve | Sleeve Return | Weighted Contribution | Share Of Linear Loss |
|---|---:|---:|---:|
| Sub-B | -14.06% | -8.44% | 115.07% |
| Sub-A | -1.14% | -0.11% | 1.55% |
| Microcap | 3.08% | 0.46% | -6.30% |
| Sub-A-DK | 5.04% | 0.76% | -10.32% |

## Weight Sensitivity

| Case | A/ADK/Microcap/B | Annual | Sharpe | MaxDD | Calmar |
|---|---|---:|---:|---:|---:|
| baseline_10_15_15_60 | 10.0%/15.0%/15.0%/60.0% | 28.59% | 2.31 | -7.20% | 3.97 |
| balanced_sharpe_12p5_20_32p5_35 | 12.5%/20.0%/32.5%/35.0% | 31.48% | 2.70 | -6.76% | 4.66 |
| dd6_candidate_22p5_10_25_42p5 | 22.5%/10.0%/25.0%/42.5% | 29.66% | 2.59 | -5.99% | 4.95 |
| recent_sharpe_27p5_12p5_20_40 | 27.5%/12.5%/20.0%/40.0% | 29.02% | 2.54 | -5.86% | 4.96 |

Conclusion:
- Baseline is not broken, but risk is still concentrated: Sub-B remains the top risk contributor despite effective weight drift below nominal 60%.
- The strongest full-sample Sharpe case in this focused set is `balanced_sharpe_12p5_20_32p5_35`, versus baseline Sharpe 2.31.
- Before changing the official V7.2 definition, rerun this after any Microcap 1.6 substitution or data refresh; these numbers are for the current official sleeve paths.

Files:
- `v72_full_correlation.csv`
- `v72_recent_252d_correlation.csv`
- `v72_rolling_252d_correlation_summary.csv`
- `v72_variance_contribution.csv`
- `v72_drawdown_attribution.csv`
- `v72_weight_case_metrics.csv`
- `meta.json`

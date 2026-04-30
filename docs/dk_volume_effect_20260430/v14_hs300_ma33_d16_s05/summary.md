# DK Volume v1.4 Three-Year NAV Comparison

Rule: `DK volume v1.4: HS300 amount < MA33 for 16 days, scale DK to 0.5`.

Window: 2023-04-17 to 2026-04-17.

## Metrics

| Strategy | Annual | Sharpe | MaxDD | Total Return |
|---|---:|---:|---:|---:|
| baseline | 34.72% | 1.53 | -17.37% | 144.58% |
| v14_hs300_ma33_d16_s05 | 38.41% | 1.69 | -15.71% | 165.22% |
| delta | 3.69% | 0.16 | 1.66% | 20.64% |

## Files
- `dk_v14_hs300_ma33_d16_s05_3y_nav.png`: NAV comparison chart.
- `dk_v14_hs300_ma33_d16_s05_3y_daily.csv`: daily returns, NAVs, and volume-rule state.
- `dk_v14_hs300_ma33_d16_s05_3y_summary.csv`: metrics table.

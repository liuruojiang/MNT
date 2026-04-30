# DK HS300 Volume Overlay Rolling Candidate Test

## Setup
- Source: current local `mnt_bot V 7.2 plus.py` DK path via `analyze_dk_volume_effect.build_dk_baseline(...)`.
- Signal: HS300 amount below its own moving average for N consecutive days.
- Timing: T-day amount signal is shifted one DK trading day before affecting return.
- Cost: extra scale changes use the same two-leg commission convention as the existing DK overlay helper.
- Rolling windows: monthly endpoints, trailing 3Y and 5Y.

## Candidate Set
- `ma33_d16_s050`: MA33/days16/scale0.50; balanced candidate from the MA30-80 retest.
- `ma32_d16_s050`: MA32/days16/scale0.50; nearby robustness neighbor.
- `ma43_d16_s050`: MA43/days16/scale0.50; full-sample MaxDD-friendly neighbor.
- `ma21_d10_s025`: MA21/days10/scale0.25; older HS300 ridge-top defensive cell.
- `ma50_d13_s050`: MA50/days13/scale0.50; rounded reference, not selected as a preferred candidate.

## Full And Recent Windows

| Candidate | TrigDays | Full dAnn | Full dMaxDD | 10Y dAnn | 10Y dMaxDD | 5Y dAnn | 5Y dMaxDD | 3Y dAnn | 3Y dMaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `ma33_d16_s050` | 386 | +0.17pp | -1.04pp | +1.46pp | +3.71pp | +1.72pp | +1.66pp | +3.69pp | +1.66pp |
| `ma32_d16_s050` | 351 | +0.23pp | -0.95pp | +1.28pp | +3.71pp | +1.72pp | +1.66pp | +3.69pp | +1.66pp |
| `ma43_d16_s050` | 524 | +0.22pp | +0.70pp | +0.97pp | +3.71pp | +0.31pp | +1.66pp | +3.25pp | +1.66pp |
| `ma21_d10_s025` | 578 | +0.05pp | +0.43pp | -0.38pp | +5.28pp | +0.61pp | +3.00pp | +0.87pp | +3.00pp |
| `ma50_d13_s050` | 732 | -1.62pp | -1.85pp | -1.28pp | +3.51pp | -2.38pp | +1.66pp | -1.22pp | +1.66pp |

## Rolling Summary

| Window | Candidate | Windows | dAnn>=0 | dMaxDD>0 | Both | dSharpe>=0 | Median dAnn | Median dMaxDD | Worst dAnn | Worst dMaxDD |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3Y | `ma21_d10_s025` | 227 | 44.1% | 71.4% | 36.6% | 59.9% | -0.45pp | +1.76pp | -5.89pp | -1.37pp |
| 3Y | `ma32_d16_s050` | 227 | 51.5% | 73.6% | 46.7% | 52.0% | +0.03pp | +0.06pp | -4.82pp | -1.08pp |
| 3Y | `ma33_d16_s050` | 227 | 50.7% | 74.9% | 46.3% | 57.7% | +0.03pp | +0.06pp | -5.54pp | -1.18pp |
| 3Y | `ma43_d16_s050` | 227 | 60.4% | 77.5% | 55.5% | 62.6% | +0.81pp | +0.68pp | -6.46pp | -0.00pp |
| 3Y | `ma50_d13_s050` | 227 | 30.0% | 57.3% | 23.8% | 39.2% | -2.15pp | +0.06pp | -9.06pp | -1.99pp |
| 5Y | `ma21_d10_s025` | 203 | 38.4% | 86.2% | 34.5% | 74.4% | -0.69pp | +2.22pp | -3.62pp | -1.37pp |
| 5Y | `ma32_d16_s050` | 203 | 46.8% | 63.1% | 30.0% | 57.1% | -0.11pp | +0.06pp | -3.25pp | -1.08pp |
| 5Y | `ma33_d16_s050` | 203 | 45.8% | 64.0% | 31.0% | 59.1% | -0.28pp | +0.06pp | -3.75pp | -1.18pp |
| 5Y | `ma43_d16_s050` | 203 | 45.8% | 78.8% | 42.9% | 65.5% | -0.14pp | +0.70pp | -4.07pp | -0.00pp |
| 5Y | `ma50_d13_s050` | 203 | 13.3% | 53.7% | 10.3% | 30.0% | -1.87pp | +0.04pp | -5.86pp | -1.99pp |

## Ranking Interpretation
- Best rolling candidate by the combined score: `ma43_d16_s050` (avg score 0.266, min both-win 42.9%, avg median dAnn +0.33pp, avg median dMaxDD +0.69pp).
- A candidate should not be promoted if it only improves the latest fixed window but fails most rolling windows.

## Files
- `full_recent_summary.csv`: fixed full/10Y/5Y/3Y comparison.
- `rolling_windows.csv`: every rolling 3Y/5Y window.
- `rolling_summary.csv`: rolling win rates and median/worst deltas.
- `candidate_ranking.csv`: compact ranking derived from rolling summary.
- `rolling_worst_windows.csv`: worst annual-delta window for each candidate and horizon.

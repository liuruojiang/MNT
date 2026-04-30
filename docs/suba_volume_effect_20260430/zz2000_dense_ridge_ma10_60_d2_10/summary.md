# Sub-A CSI2000 Dense Volume Ridge

## Setup
- Strategy path: current local `mnt_bot V 7.2 plus.py` Sub-A path.
- Source: CSI2000 / EastMoney `2.932000` daily amount.
- Grid: MA10..60, consecutive days 2..10, scale 0.50.
- Timing: T-day amount is only used from the next close-to-close exposure.

## Ridge Width
- Largest robust component: 49 cells, MA 11..43, days 2..4.
- Robust cells: 110 / 459.
- Full annual >= baseline cells: 62 / 459.
- 10Y MaxDD non-worse cells: 296 / 459.

## Robust MA Bands By Consecutive Days

| Days | Robust MA bands | Cells | Longest width |
|---:|---|---:|---:|
| 2 | 11-20 | 10 | 10 |
| 3 | 12-43; 45; 47; 49-54; 56-60 | 45 | 32 |
| 4 | 18-21; 34-36; 50-51 | 9 | 4 |
| 5 | - | 0 | 0 |
| 6 | 23; 27; 31-36; 44-46; 50; 56-58 | 15 | 6 |
| 7 | 50-60 | 11 | 11 |
| 8 | 50-60 | 11 | 11 |
| 9 | 50; 60 | 2 | 1 |
| 10 | 50-52; 56-59 | 7 | 4 |

## Top Robust Cells

| MA | Days | Score | Full dAnn | 10Y dAnn | 10Y dMaxDD | 5Y dAnn | 3Y dAnn |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 12 | 2 | 0.272 | -0.36pp | +1.07pp | +3.77pp | +3.23pp | +4.39pp |
| 19 | 3 | 0.240 | +0.14pp | +1.88pp | +4.62pp | +3.24pp | +4.95pp |
| 11 | 2 | 0.230 | -0.43pp | +0.24pp | +2.79pp | +2.43pp | +3.49pp |
| 15 | 3 | 0.225 | -0.10pp | +1.72pp | +4.80pp | +2.87pp | +4.53pp |
| 14 | 3 | 0.225 | -0.14pp | +1.51pp | +4.80pp | +2.84pp | +4.41pp |
| 18 | 3 | 0.222 | +0.11pp | +2.06pp | +4.81pp | +2.88pp | +3.78pp |
| 20 | 3 | 0.222 | -0.11pp | +1.13pp | +4.63pp | +2.21pp | +5.11pp |
| 13 | 2 | 0.222 | -0.37pp | +0.59pp | +3.86pp | +1.90pp | +3.02pp |
| 28 | 3 | 0.215 | +0.23pp | +1.16pp | +2.86pp | +2.04pp | +3.46pp |
| 21 | 3 | 0.214 | -0.18pp | +1.03pp | +4.63pp | +2.21pp | +5.11pp |
| 13 | 3 | 0.212 | -0.31pp | +0.87pp | +5.12pp | +1.70pp | +3.19pp |
| 17 | 3 | 0.210 | +0.02pp | +1.77pp | +4.69pp | +2.13pp | +3.38pp |
| 56 | 3 | 0.209 | -0.28pp | +0.36pp | +3.17pp | +1.73pp | +5.54pp |
| 27 | 3 | 0.205 | +0.09pp | +0.86pp | +1.52pp | +2.02pp | +3.43pp |
| 58 | 3 | 0.199 | -0.27pp | +0.48pp | +3.17pp | +1.41pp | +4.99pp |

## Files
- `zz2000_dense_ridge_scale050.csv`: full dense grid.
- `pass_heatmap.csv`: robust-pass matrix.
- `score_heatmap.csv`: score matrix.
- `robust_ma_bands_by_days.csv`: contiguous robust MA bands for each consecutive-day value.
- `top80.csv` and `robust_cells.csv`: ranked outputs.

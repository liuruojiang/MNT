# Sub-A Mix Effect

- Data source: production `fetch_cn_kline()` path from `mnt_bot V 7.0 plus.py`
- Asset pool: 5 CN total-return indexes + 10Y treasury total-return index
- Baseline: `bias_n=60, mom_day=20, r2_window=20`
- Mix method: run each sleeve independently with production overlays, then average effective target weights and charge net turnover cost

## Candidates
- `mix_40_10__60_20__120_40`: ((40, 10, 10), (60, 20, 20), (120, 40, 40))
- `mix_45_15__60_20__90_30`: ((45, 15, 15), (60, 20, 20), (90, 30, 30))
- `mix_50_15__60_20__70_25`: ((50, 15, 15), (60, 20, 20), (70, 25, 25))
- `mix_55_15__60_20__80_25`: ((55, 15, 15), (60, 20, 20), (80, 25, 25))
- `mix_60_20__90_30__120_40`: ((60, 20, 20), (90, 30, 30), (120, 40, 40))

## Core
### last_5y
- baseline_60_20_20: CAGR 25.27%, Sharpe 1.226, MaxDD -16.60%
- mix_40_10__60_20__120_40: CAGR 16.90%, Sharpe 1.028, MaxDD -15.48%
- mix_50_15__60_20__70_25: CAGR 16.34%, Sharpe 0.928, MaxDD -21.76%
- mix_45_15__60_20__90_30: CAGR 14.17%, Sharpe 0.856, MaxDD -23.64%
- mix_55_15__60_20__80_25: CAGR 15.05%, Sharpe 0.851, MaxDD -18.44%
- mix_60_20__90_30__120_40: CAGR 12.85%, Sharpe 0.803, MaxDD -20.74%

### last_10y
- baseline_60_20_20: CAGR 22.00%, Sharpe 1.107, MaxDD -24.60%
- mix_50_15__60_20__70_25: CAGR 15.16%, Sharpe 0.879, MaxDD -29.14%
- mix_55_15__60_20__80_25: CAGR 14.08%, Sharpe 0.820, MaxDD -28.58%
- mix_45_15__60_20__90_30: CAGR 13.12%, Sharpe 0.807, MaxDD -33.06%
- mix_40_10__60_20__120_40: CAGR 10.67%, Sharpe 0.716, MaxDD -25.79%
- mix_60_20__90_30__120_40: CAGR 10.38%, Sharpe 0.670, MaxDD -31.07%

### full_common
- baseline_60_20_20: CAGR 26.43%, Sharpe 1.259, MaxDD -24.60%
- mix_50_15__60_20__70_25: CAGR 18.89%, Sharpe 1.044, MaxDD -29.14%
- mix_55_15__60_20__80_25: CAGR 17.60%, Sharpe 0.978, MaxDD -28.58%
- mix_45_15__60_20__90_30: CAGR 16.29%, Sharpe 0.963, MaxDD -33.06%
- mix_40_10__60_20__120_40: CAGR 14.39%, Sharpe 0.921, MaxDD -28.02%
- mix_60_20__90_30__120_40: CAGR 14.51%, Sharpe 0.880, MaxDD -31.07%

# Sub-A Relative Momentum Replacement

- Base script: `mnt_bot V 7.1 plus.py`
- Data source: production `fetch_cn_kline()` path via the script
- Replacement definition: `close / close.shift(n) - 1`
- Scope: replace Sub-A ranking signal only; keep existing `R²`, cash overlay, same-side overheat, vol scaling, and commission path

## Core Compare
### last_3y
- baseline_bias_60_20_20: CAGR 32.92%, Sharpe 1.538, MaxDD -12.78%
- relative_mom_20: CAGR 18.59%, Sharpe 0.942, MaxDD -17.65%

### last_5y
- baseline_bias_60_20_20: CAGR 28.22%, Sharpe 1.394, MaxDD -15.87%
- relative_mom_20: CAGR 18.61%, Sharpe 0.975, MaxDD -17.65%

### last_10y
- baseline_bias_60_20_20: CAGR 23.23%, Sharpe 1.192, MaxDD -23.24%
- relative_mom_20: CAGR 18.76%, Sharpe 0.994, MaxDD -25.65%

### full_common
- baseline_bias_60_20_20: CAGR 28.37%, Sharpe 1.359, MaxDD -23.24%
- relative_mom_20: CAGR 25.74%, Sharpe 1.251, MaxDD -25.65%

## Width Bands Around Relative 20
- last_3y: strict [10,11,12,13,17,18,19,20,21,22,24,25,26], loose [10,11,12,13,14,16,17,18,19,20,21,22,24,25,26]
- last_5y: strict [10,11,13,17,20,21,22,24,25,26], loose [10,11,13,14,17,18,20,21,22,24,25,26]
- last_10y: strict [10,14,16,17,18,19,20,22,24], loose [10,12,14,15,16,17,18,19,20,21,22,24,25]
- full_common: strict [10,12,14,16,17,19,20,22,24], loose [10,12,14,15,16,17,18,19,20,21,22,23,24,25]
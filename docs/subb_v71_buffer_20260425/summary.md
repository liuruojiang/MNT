# Sub-B V7.1 Buffer Study

- Data source: production `fetch_yahoo()` path from `mnt_bot V 7.1 plus.py`
- Strategy: current `run_us_rotation_mix()` logic with `130/260/390` windows; current formal production threshold = `1.05x`
- Pool: `QQQ, EMXC, EFA, GLD, TLT, DBC, BTC-USD`
- Execution: T close signal -> T+1 open execution
- Costs: `US_ROT_COMMISSION = 0.001`
- Buffer rule: each window remembers its prior Top3; challenger must beat the weakest incumbent by `threshold` before replacing it
- Production parity check: custom `1.05x` harness vs `run_us_rotation_mix()` max abs NAV diff = `0`

## last_1y
- candidate_1p02x: CAGR 41.31%, Sharpe 1.644, MaxDD -11.43%, Rebalances 52, QQQ changes<=7d 1
- legacy_no_buffer_1p00x: CAGR 40.64%, Sharpe 1.625, MaxDD -11.43%, Rebalances 52, QQQ changes<=7d 1
- formal_v71_1p05x: CAGR 40.17%, Sharpe 1.608, MaxDD -11.46%, Rebalances 52, QQQ changes<=7d 1
- candidate_1p10x: CAGR 38.13%, Sharpe 1.539, MaxDD -11.48%, Rebalances 52, QQQ changes<=7d 1
- Winners: cagr -> candidate_1p02x; sharpe -> candidate_1p02x; calmar -> candidate_1p02x; max_dd -> legacy_no_buffer_1p00x

## last_3y
- formal_v71_1p05x: CAGR 35.02%, Sharpe 1.458, MaxDD -11.46%, Rebalances 157, QQQ changes<=7d 2
- candidate_1p02x: CAGR 34.71%, Sharpe 1.445, MaxDD -11.43%, Rebalances 157, QQQ changes<=7d 2
- candidate_1p10x: CAGR 34.36%, Sharpe 1.435, MaxDD -11.48%, Rebalances 157, QQQ changes<=7d 2
- legacy_no_buffer_1p00x: CAGR 34.27%, Sharpe 1.427, MaxDD -11.43%, Rebalances 157, QQQ changes<=7d 2
- Winners: cagr -> formal_v71_1p05x; sharpe -> formal_v71_1p05x; calmar -> formal_v71_1p05x; max_dd -> legacy_no_buffer_1p00x

## last_5y
- formal_v71_1p05x: CAGR 25.09%, Sharpe 1.170, MaxDD -18.55%, Rebalances 261, QQQ changes<=7d 4
- candidate_1p10x: CAGR 24.72%, Sharpe 1.155, MaxDD -18.55%, Rebalances 261, QQQ changes<=7d 4
- candidate_1p02x: CAGR 24.36%, Sharpe 1.141, MaxDD -18.55%, Rebalances 261, QQQ changes<=7d 4
- legacy_no_buffer_1p00x: CAGR 24.02%, Sharpe 1.126, MaxDD -18.39%, Rebalances 261, QQQ changes<=7d 4
- Winners: cagr -> formal_v71_1p05x; sharpe -> formal_v71_1p05x; calmar -> formal_v71_1p05x; max_dd -> legacy_no_buffer_1p00x

## last_10y
- formal_v71_1p05x: CAGR 28.37%, Sharpe 1.354, MaxDD -18.55%, Rebalances 522, QQQ changes<=7d 11
- legacy_no_buffer_1p00x: CAGR 28.25%, Sharpe 1.348, MaxDD -18.39%, Rebalances 522, QQQ changes<=7d 11
- candidate_1p10x: CAGR 27.84%, Sharpe 1.332, MaxDD -18.55%, Rebalances 522, QQQ changes<=7d 11
- candidate_1p02x: CAGR 27.80%, Sharpe 1.330, MaxDD -18.55%, Rebalances 522, QQQ changes<=7d 11
- Winners: cagr -> formal_v71_1p05x; sharpe -> formal_v71_1p05x; calmar -> legacy_no_buffer_1p00x; max_dd -> legacy_no_buffer_1p00x

## full_common
- formal_v71_1p05x: CAGR 27.61%, Sharpe 1.330, MaxDD -18.55%, Rebalances 550, QQQ changes<=7d 13
- legacy_no_buffer_1p00x: CAGR 27.54%, Sharpe 1.326, MaxDD -18.39%, Rebalances 550, QQQ changes<=7d 13
- candidate_1p10x: CAGR 27.11%, Sharpe 1.309, MaxDD -18.55%, Rebalances 550, QQQ changes<=7d 13
- candidate_1p02x: CAGR 27.07%, Sharpe 1.308, MaxDD -18.55%, Rebalances 550, QQQ changes<=7d 13
- Winners: cagr -> formal_v71_1p05x; sharpe -> formal_v71_1p05x; calmar -> legacy_no_buffer_1p00x; max_dd -> legacy_no_buffer_1p00x

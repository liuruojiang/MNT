# Sub-B Volume Effect Study

## Setup
- Sub-B source: `mnt_bot V 7.2 plus.py` current V7.2 path.
- Baseline uses `run_us_rotation_mix`, inflation-gated macro candidates, and SPY VolReg overlay.
- Price data: `mnt_strategy_data_us.csv`.
- Volume data: Yahoo Finance daily volume cached under `raw_yfinance_volume/`.
- Timing: T-day volume affects the next Sub-B trading day only.

## Baseline
- 17.53% annual, Sharpe 1.08, MaxDD -16.54%, sample 2004-07-23 to 2026-04-17.

## Group Summary
- broad_consec_below / DIA / scale 0.50: tested 30, robust 0, best score 0.002, median -0.288; best dAnn 10Y/5Y/3Y +0.10/+0.00/+0.32pp.
- broad_consec_above / DIA / scale 0.50: tested 30, robust 0, best score 0.002, median -0.129; best dAnn 10Y/5Y/3Y +0.00/+0.08/+0.82pp.
- broad_consec_below / DIA / scale 0.75: tested 30, robust 0, best score 0.002, median -0.139; best dAnn 10Y/5Y/3Y +0.05/+0.00/+0.16pp.
- broad_consec_above / DIA / scale 0.75: tested 30, robust 0, best score 0.002, median -0.063; best dAnn 10Y/5Y/3Y +0.00/+0.04/+0.41pp.
- broad_consec_below / DIA / scale 0.25: tested 30, robust 0, best score 0.002, median -0.448; best dAnn 10Y/5Y/3Y +0.15/+0.00/+0.48pp.
- held_proxy_consec_below / held_proxy / scale 0.00: tested 30, robust 0, best score 0.001, median -0.226; best dAnn 10Y/5Y/3Y +0.00/+0.00/+0.00pp.
- broad_consec_above / DIA / scale 0.25: tested 30, robust 0, best score 0.001, median -0.196; best dAnn 10Y/5Y/3Y +0.00/+0.12/+1.22pp.
- held_proxy_consec_below / held_proxy / scale 0.25: tested 30, robust 0, best score 0.001, median -0.168; best dAnn 10Y/5Y/3Y +0.00/+0.00/+0.00pp.
- held_proxy_consec_below / held_proxy / scale 0.50: tested 30, robust 0, best score 0.000, median -0.112; best dAnn 10Y/5Y/3Y +0.00/+0.00/+0.00pp.
- held_proxy_consec_below / held_proxy / scale 0.75: tested 30, robust 0, best score 0.000, median -0.056; best dAnn 10Y/5Y/3Y +0.00/+0.00/+0.00pp.
- broad_consec_above / DIA / scale 0.00: tested 30, robust 0, best score 0.000, median -0.269; best dAnn 10Y/5Y/3Y +0.00/+0.16/+1.61pp.
- broad_consec_above / IWM / scale 0.00: tested 30, robust 0, best score 0.000, median -0.397; best dAnn 10Y/5Y/3Y +0.00/+0.05/+1.60pp.
- broad_consec_above / IWM / scale 0.25: tested 30, robust 0, best score 0.000, median -0.280; best dAnn 10Y/5Y/3Y +0.00/+0.04/+1.22pp.
- broad_consec_above / IWM / scale 0.50: tested 30, robust 0, best score 0.000, median -0.180; best dAnn 10Y/5Y/3Y +0.00/+0.03/+0.83pp.
- broad_consec_above / IWM / scale 0.75: tested 30, robust 0, best score 0.000, median -0.088; best dAnn 10Y/5Y/3Y +0.00/+0.01/+0.42pp.
- broad_consec_above / QQQ / scale 0.00: tested 30, robust 0, best score 0.000, median -0.419; best dAnn 10Y/5Y/3Y +0.00/+0.00/+0.00pp.
- broad_consec_above / QQQ / scale 0.25: tested 30, robust 0, best score 0.000, median -0.306; best dAnn 10Y/5Y/3Y +0.00/+0.00/+0.00pp.
- broad_consec_above / QQQ / scale 0.50: tested 30, robust 0, best score 0.000, median -0.198; best dAnn 10Y/5Y/3Y +0.00/+0.00/+0.00pp.
- broad_consec_above / QQQ / scale 0.75: tested 30, robust 0, best score 0.000, median -0.096; best dAnn 10Y/5Y/3Y +0.00/+0.00/+0.00pp.
- broad_consec_above / SPY / scale 0.00: tested 30, robust 0, best score 0.000, median -0.385; best dAnn 10Y/5Y/3Y +0.00/+0.00/+0.00pp.
- broad_consec_above / SPY / scale 0.25: tested 30, robust 0, best score 0.000, median -0.284; best dAnn 10Y/5Y/3Y +0.00/+0.00/+0.00pp.
- broad_consec_above / SPY / scale 0.50: tested 30, robust 0, best score 0.000, median -0.186; best dAnn 10Y/5Y/3Y +0.00/+0.00/+0.00pp.
- broad_consec_above / SPY / scale 0.75: tested 30, robust 0, best score 0.000, median -0.091; best dAnn 10Y/5Y/3Y +0.00/+0.00/+0.00pp.
- broad_consec_below / IWM / scale 0.00: tested 30, robust 0, best score 0.000, median -0.770; best dAnn 10Y/5Y/3Y +0.55/+0.07/+0.68pp.
- broad_consec_below / IWM / scale 0.25: tested 30, robust 0, best score 0.000, median -0.560; best dAnn 10Y/5Y/3Y +0.42/+0.05/+0.53pp.
- broad_consec_below / IWM / scale 0.50: tested 30, robust 0, best score 0.000, median -0.358; best dAnn 10Y/5Y/3Y +0.28/+0.04/+0.37pp.
- broad_consec_below / IWM / scale 0.75: tested 30, robust 0, best score 0.000, median -0.169; best dAnn 10Y/5Y/3Y +0.14/+0.02/+0.19pp.
- broad_consec_below / SPY / scale 0.00: tested 30, robust 0, best score 0.000, median -0.592; best dAnn 10Y/5Y/3Y +0.24/+1.53/+3.00pp.
- broad_consec_below / SPY / scale 0.25: tested 30, robust 0, best score 0.000, median -0.438; best dAnn 10Y/5Y/3Y +0.18/+1.15/+2.25pp.
- broad_consec_below / SPY / scale 0.50: tested 30, robust 0, best score 0.000, median -0.288; best dAnn 10Y/5Y/3Y +0.12/+0.77/+1.50pp.

## Top Robust Rules
- No rule passed the initial robust filter.

## Files
- `subb_volume_rule_summary.csv`: all scanned rules.
- `subb_volume_top100.csv`: top scored rules.
- `subb_volume_robust.csv`: robust-pass candidates.
- `subb_volume_group_summary.csv`: family-level comparison.

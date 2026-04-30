# Sub-B Macro Pool Filter Scan

## Setup
- Baseline: current V7.2 Sub-B path with inflation-gated macro candidates and SPY VolReg.
- Instead of scaling the whole sleeve, stress conditions alter the ranking candidate pool on signal days.
- Stress sources: VIX, HYG/LQD credit ratio, QQQ/SPY relative trend.

## Top Candidates
- `vix_gt30:no_btc`: score -0.028, stress days 449; 10Y dAnn -0.36pp, dSharpe -0.01, dMaxDD +0.00pp; 5Y dAnn -0.13pp; 3Y dAnn -0.04pp; full dAnn -0.16pp.
- `vix_gt30:defensive_plus_equity`: score -0.083, stress days 449; 10Y dAnn -0.73pp, dSharpe -0.03, dMaxDD +0.00pp; 5Y dAnn -0.11pp; 3Y dAnn -0.08pp; full dAnn -0.53pp.
- `vix_gt25:no_btc`: score -0.138, stress days 880; 10Y dAnn -1.61pp, dSharpe -0.06, dMaxDD +0.00pp; 5Y dAnn -0.48pp; 3Y dAnn -0.82pp; full dAnn -0.81pp.
- `growth_underperform_ma100_d5:no_btc`: score -0.150, stress days 1664; 10Y dAnn -1.99pp, dSharpe -0.06, dMaxDD +0.51pp; 5Y dAnn +0.14pp; 3Y dAnn -1.79pp; full dAnn -1.00pp.
- `vix_gt30:no_growth_btc`: score -0.153, stress days 449; 10Y dAnn -1.64pp, dSharpe -0.06, dMaxDD +0.00pp; 5Y dAnn -0.17pp; 3Y dAnn -0.04pp; full dAnn -1.00pp.
- `growth_underperform_ma100_d5:defensive_plus_equity`: score -0.156, stress days 1664; 10Y dAnn -1.53pp, dSharpe -0.04, dMaxDD +0.94pp; 5Y dAnn +1.26pp; 3Y dAnn -0.03pp; full dAnn -1.55pp.
- `credit_below_ma100_d3:defensive_plus_equity`: score -0.162, stress days 1711; 10Y dAnn -1.41pp, dSharpe -0.01, dMaxDD +0.26pp; 5Y dAnn -1.98pp; 3Y dAnn -2.35pp; full dAnn -1.21pp.
- `credit_below_ma100_d5:no_btc`: score -0.165, stress days 1551; 10Y dAnn -1.57pp, dSharpe -0.03, dMaxDD +0.00pp; 5Y dAnn -1.61pp; 3Y dAnn -1.22pp; full dAnn -1.05pp.
- `credit_below_ma100_d3:no_btc`: score -0.195, stress days 1711; 10Y dAnn -1.80pp, dSharpe -0.04, dMaxDD +0.26pp; 5Y dAnn -2.22pp; 3Y dAnn -2.35pp; full dAnn -1.13pp.
- `credit_below_ma100_d5:defensive_plus_equity`: score -0.199, stress days 1551; 10Y dAnn -1.64pp, dSharpe -0.03, dMaxDD +0.00pp; 5Y dAnn -2.11pp; 3Y dAnn -2.46pp; full dAnn -1.23pp.
- `vix_gt30:defensive_core`: score -0.200, stress days 449; 10Y dAnn -2.03pp, dSharpe -0.08, dMaxDD +0.00pp; 5Y dAnn -0.19pp; 3Y dAnn -0.08pp; full dAnn -1.31pp.
- `vix_gt30:no_equity_btc`: score -0.201, stress days 449; 10Y dAnn -2.03pp, dSharpe -0.08, dMaxDD +0.00pp; 5Y dAnn -0.23pp; 3Y dAnn -0.08pp; full dAnn -1.31pp.

## Robust Rules
- No rule passed the robust filter.

## Files
- `subb_macro_pool_filter_summary.csv`: all variants.
- `subb_macro_pool_filter_ranked.csv`: ranked variants.
- `subb_macro_pool_filter_robust.csv`: robust-pass variants.
- `subb_macro_pool_filter_top_curves.csv`: daily returns/NAVs for top variants.

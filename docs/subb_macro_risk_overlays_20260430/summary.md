# Sub-B Macro Risk Overlay Scan

## Setup
- Baseline: current V7.2 Sub-B path with inflation-gated macro candidates and SPY VolReg.
- Tested risk sources: VIX, HYG/LQD credit ratio, UUP, TLT, QQQ/SPY.
- Timing: T-day risk signal affects the next trading day only.

## Baseline
- 17.53% annual, Sharpe 1.08, MaxDD -16.54%, sample 2004-07-23 to 2026-04-17.

## Group Summary
- credit_mom / HYG/LQD / scale 0.75: tested 12, robust 0, best score -0.003, median -0.038; best dAnn 10Y/5Y/3Y -0.02/+0.00/+0.00pp.
- credit_mom / HYG/LQD / scale 0.50: tested 12, robust 0, best score -0.009, median -0.078; best dAnn 10Y/5Y/3Y -0.03/+0.00/+0.00pp.
- credit_mom / HYG/LQD / scale 0.25: tested 12, robust 0, best score -0.017, median -0.130; best dAnn 10Y/5Y/3Y -0.05/+0.00/+0.00pp.
- vix_abs / ^VIX / scale 0.75: tested 4, robust 0, best score -0.026, median -0.101; best dAnn 10Y/5Y/3Y -0.41/+0.06/-0.08pp.
- credit_mom / HYG/LQD / scale 0.00: tested 12, robust 0, best score -0.034, median -0.182; best dAnn 10Y/5Y/3Y -0.06/+0.00/+0.00pp.
- vix_rel / ^VIX / scale 0.75: tested 12, robust 0, best score -0.051, median -0.155; best dAnn 10Y/5Y/3Y -0.44/-0.75/-0.70pp.
- vix_abs / ^VIX / scale 0.50: tested 4, robust 0, best score -0.054, median -0.210; best dAnn 10Y/5Y/3Y -0.83/+0.11/-0.16pp.
- vix_abs / ^VIX / scale 0.25: tested 4, robust 0, best score -0.084, median -0.330; best dAnn 10Y/5Y/3Y -1.25/+0.16/-0.25pp.
- vix_rel / ^VIX / scale 0.50: tested 12, robust 0, best score -0.117, median -0.337; best dAnn 10Y/5Y/3Y -0.89/-1.52/-1.41pp.
- vix_abs / ^VIX / scale 0.00: tested 4, robust 0, best score -0.124, median -0.464; best dAnn 10Y/5Y/3Y -1.67/+0.21/-0.33pp.
- credit_below_ma / HYG/LQD / scale 0.75: tested 16, robust 0, best score -0.138, median -0.286; best dAnn 10Y/5Y/3Y -1.73/+0.09/+0.29pp.
- qqq_spy_below_ma / QQQ/SPY / scale 0.75: tested 12, robust 0, best score -0.182, median -0.300; best dAnn 10Y/5Y/3Y -1.84/-2.14/-2.78pp.
- vix_rel / ^VIX / scale 0.25: tested 12, robust 0, best score -0.205, median -0.545; best dAnn 10Y/5Y/3Y -1.36/-2.31/-2.14pp.
- rates_below_ma / TLT / scale 0.75: tested 12, robust 0, best score -0.231, median -0.328; best dAnn 10Y/5Y/3Y -2.27/-2.00/-2.42pp.
- usd_above_ma / UUP / scale 0.75: tested 12, robust 0, best score -0.249, median -0.367; best dAnn 10Y/5Y/3Y -3.08/-3.77/-3.61pp.
- credit_below_ma / HYG/LQD / scale 0.50: tested 16, robust 0, best score -0.288, median -0.594; best dAnn 10Y/5Y/3Y -3.48/+0.16/+0.56pp.
- vix_rel / ^VIX / scale 0.00: tested 12, robust 0, best score -0.308, median -0.781; best dAnn 10Y/5Y/3Y -1.84/-3.11/-2.88pp.
- combo_vix_credit / ^VIX|HYG/LQD / scale 0.75: tested 3, robust 0, best score -0.313, median -0.367; best dAnn 10Y/5Y/3Y -3.18/-2.85/-2.70pp.
- qqq_spy_below_ma / QQQ/SPY / scale 0.50: tested 12, robust 0, best score -0.400, median -0.671; best dAnn 10Y/5Y/3Y -3.69/-4.29/-5.55pp.
- credit_below_ma / HYG/LQD / scale 0.25: tested 16, robust 0, best score -0.474, median -0.940; best dAnn 10Y/5Y/3Y -5.23/+0.22/+0.81pp.
- rates_below_ma / TLT / scale 0.50: tested 12, robust 0, best score -0.502, median -0.703; best dAnn 10Y/5Y/3Y -4.54/-4.01/-4.85pp.
- usd_above_ma / UUP / scale 0.50: tested 12, robust 0, best score -0.552, median -0.819; best dAnn 10Y/5Y/3Y -6.15/-7.52/-7.24pp.
- combo_vix_credit / ^VIX|HYG/LQD / scale 0.50: tested 3, robust 0, best score -0.649, median -0.761; best dAnn 10Y/5Y/3Y -6.32/-5.67/-5.39pp.
- qqq_spy_below_ma / QQQ/SPY / scale 0.25: tested 12, robust 0, best score -0.661, median -1.083; best dAnn 10Y/5Y/3Y -5.53/-6.45/-8.30pp.
- credit_below_ma / HYG/LQD / scale 0.00: tested 16, robust 0, best score -0.694, median -1.328; best dAnn 10Y/5Y/3Y -6.98/+0.26/+1.03pp.
- rates_below_ma / TLT / scale 0.25: tested 12, robust 0, best score -0.808, median -1.136; best dAnn 10Y/5Y/3Y -6.80/-6.02/-7.26pp.
- qqq_spy_below_ma / QQQ/SPY / scale 0.00: tested 12, robust 0, best score -0.954, median -1.529; best dAnn 10Y/5Y/3Y -7.37/-8.61/-11.04pp.
- usd_above_ma / UUP / scale 0.25: tested 12, robust 0, best score -0.959, median -1.404; best dAnn 10Y/5Y/3Y -9.20/-11.24/-10.89pp.
- combo_vix_credit / ^VIX|HYG/LQD / scale 0.25: tested 3, robust 0, best score -1.025, median -1.199; best dAnn 10Y/5Y/3Y -9.42/-8.47/-8.07pp.
- rates_below_ma / TLT / scale 0.00: tested 12, robust 0, best score -1.152, median -1.614; best dAnn 10Y/5Y/3Y -9.06/-8.04/-9.67pp.
- combo_vix_credit / ^VIX|HYG/LQD / scale 0.00: tested 3, robust 0, best score -1.455, median -1.694; best dAnn 10Y/5Y/3Y -12.48/-11.24/-10.74pp.
- usd_above_ma / UUP / scale 0.00: tested 12, robust 0, best score -1.472, median -2.087; best dAnn 10Y/5Y/3Y -12.23/-14.93/-14.56pp.

## Top Robust Rules
- No rule passed the robust filter.

## Files
- `subb_macro_risk_overlay_summary.csv`: all scanned rules.
- `subb_macro_risk_overlay_top120.csv`: top scored rules.
- `subb_macro_risk_overlay_robust.csv`: robust-pass candidates.
- `subb_macro_risk_overlay_group_summary.csv`: family-level comparison.

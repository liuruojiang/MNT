# Sub-A-DK Volume Effect Study

## Setup
- DK source: `mnt_bot V 7.2 plus.py` current local V7.2 path.
- Baseline includes current DK pair-score decay and same-side overheat overlays.
- Volume data: EastMoney daily K-line amount/volume, cached in this directory; previously fetched matching secids were copied from the Sub-A volume cache.
- Timing: T-day volume is shifted one trading day before affecting DK returns.
- Cost model: extra volume-overlay scale changes pay the same two-leg commission convention used by existing DK overlays.

## Baseline
- 21.41% annual, Sharpe 1.11, MaxDD -40.96%, sample 2004-06-28 to 2026-04-17.

## Group Summary
- broad_consec_below / hs300 / scale 0.25: tested 30, robust 0, best score 0.106, median -0.617; best dAnn 10Y/5Y/3Y -1.06/+1.14/+1.16pp.
- broad_consec_below / hs300 / scale 0.00: tested 30, robust 0, best score 0.100, median -0.938; best dAnn 10Y/5Y/3Y -1.49/+1.45/+1.27pp.
- broad_consec_below / sh_comp / scale 0.00: tested 30, robust 0, best score 0.093, median -0.856; best dAnn 10Y/5Y/3Y -0.58/+1.13/+4.14pp.
- broad_consec_below / hs300 / scale 0.50: tested 30, robust 0, best score 0.090, median -0.369; best dAnn 10Y/5Y/3Y -0.67/+0.80/+0.91pp.
- broad_consec_below / large_sum / scale 0.25: tested 30, robust 0, best score 0.077, median -0.744; best dAnn 10Y/5Y/3Y +0.21/+0.75/+1.09pp.
- broad_consec_below / sh_comp / scale 0.25: tested 30, robust 0, best score 0.076, median -0.587; best dAnn 10Y/5Y/3Y -0.42/+0.87/+3.10pp.
- broad_consec_below / large_sum / scale 0.00: tested 30, robust 0, best score 0.074, median -1.090; best dAnn 10Y/5Y/3Y +0.26/+0.98/+1.45pp.
- broad_consec_below / large_sum / scale 0.50: tested 30, robust 0, best score 0.066, median -0.446; best dAnn 10Y/5Y/3Y +0.14/+0.50/+0.74pp.
- broad_consec_below / hs300 / scale 0.75: tested 30, robust 0, best score 0.055, median -0.165; best dAnn 10Y/5Y/3Y -0.32/+0.42/+0.52pp.
- broad_consec_below / sh_comp / scale 0.50: tested 30, robust 0, best score 0.054, median -0.359; best dAnn 10Y/5Y/3Y -0.27/+0.59/+2.07pp.
- broad_consec_below / large_sum / scale 0.75: tested 30, robust 0, best score 0.039, median -0.199; best dAnn 10Y/5Y/3Y +0.07/+0.25/+0.37pp.
- broad_consec_below / zz2000 / scale 0.50: tested 30, robust 0, best score 0.036, median -0.276; best dAnn 10Y/5Y/3Y -0.65/+0.03/+1.29pp.
- broad_consec_below / sh_comp / scale 0.75: tested 30, robust 0, best score 0.029, median -0.164; best dAnn 10Y/5Y/3Y -0.13/+0.30/+1.05pp.
- broad_consec_below / zz2000 / scale 0.75: tested 30, robust 0, best score 0.026, median -0.115; best dAnn 10Y/5Y/3Y -0.32/+0.05/+0.68pp.
- broad_consec_below / zz2000 / scale 0.25: tested 30, robust 0, best score 0.020, median -0.484; best dAnn 10Y/5Y/3Y -0.99/-0.04/+1.85pp.
- broad_consec_below / cyb / scale 0.75: tested 30, robust 0, best score 0.013, median -0.139; best dAnn 10Y/5Y/3Y -0.57/-0.93/-0.69pp.
- broad_consec_below / cyb / scale 0.50: tested 30, robust 0, best score 0.009, median -0.333; best dAnn 10Y/5Y/3Y -1.16/-1.88/-1.45pp.
- broad_consec_below / zz500 / scale 0.75: tested 30, robust 0, best score -0.007, median -0.182; best dAnn 10Y/5Y/3Y -0.54/-0.39/+0.49pp.
- broad_consec_below / cyb / scale 0.25: tested 30, robust 0, best score -0.011, median -0.561; best dAnn 10Y/5Y/3Y -1.77/-2.86/-2.26pp.
- broad_consec_below / small_growth_sum / scale 0.75: tested 30, robust 0, best score -0.011, median -0.184; best dAnn 10Y/5Y/3Y -0.89/-0.67/+0.26pp.
- broad_consec_below / dk_leg_sum / scale 0.75: tested 30, robust 0, best score -0.015, median -0.164; best dAnn 10Y/5Y/3Y -0.34/-0.44/-0.09pp.
- broad_consec_below / zz2000 / scale 0.00: tested 30, robust 0, best score -0.018, median -0.755; best dAnn 10Y/5Y/3Y -1.35/-0.17/+2.34pp.
- broad_consec_below / zz500 / scale 0.50: tested 30, robust 0, best score -0.021, median -0.404; best dAnn 10Y/5Y/3Y -1.09/-0.80/+0.86pp.
- active_pair_consec_below / small_growth_min / scale 0.75: tested 30, robust 0, best score -0.031, median -0.134; best dAnn 10Y/5Y/3Y -1.29/-1.39/-0.57pp.
- broad_consec_below / dk_leg_sum / scale 0.50: tested 30, robust 0, best score -0.038, median -0.374; best dAnn 10Y/5Y/3Y -0.69/-0.89/-0.22pp.

## Top Robust Rules
- No rule passed the 10Y/5Y/3Y robust filter.

## Top Scored Rules
- `broad_consec_below:hs300:ma20:days10:scale0.25`: score 0.106, 10Y/5Y/3Y dAnn -1.06/+1.14/+0.87pp, full dAnn -0.49pp.
- `broad_consec_below:hs300:ma20:days10:scale0.00`: score 0.100, 10Y/5Y/3Y dAnn -1.49/+1.45/+1.06pp, full dAnn -0.72pp.
- `broad_consec_below:sh_comp:ma10:days10:scale0.00`: score 0.093, 10Y/5Y/3Y dAnn -0.58/+1.13/+4.14pp, full dAnn -0.17pp.
- `broad_consec_below:hs300:ma20:days10:scale0.50`: score 0.090, 10Y/5Y/3Y dAnn -0.67/+0.80/+0.62pp, full dAnn -0.30pp.
- `broad_consec_below:large_sum:ma20:days10:scale0.25`: score 0.077, 10Y/5Y/3Y dAnn -0.63/-0.77/+0.69pp, full dAnn -0.26pp.
- `broad_consec_below:sh_comp:ma10:days10:scale0.25`: score 0.076, 10Y/5Y/3Y dAnn -0.42/+0.87/+3.10pp, full dAnn -0.11pp.
- `broad_consec_below:large_sum:ma20:days10:scale0.00`: score 0.074, 10Y/5Y/3Y dAnn -0.91/-1.10/+0.83pp, full dAnn -0.41pp.
- `broad_consec_below:large_sum:ma20:days10:scale0.50`: score 0.066, 10Y/5Y/3Y dAnn -0.39/-0.48/+0.50pp, full dAnn -0.15pp.
- `broad_consec_below:hs300:ma20:days10:scale0.75`: score 0.055, 10Y/5Y/3Y dAnn -0.32/+0.42/+0.34pp, full dAnn -0.13pp.
- `broad_consec_below:sh_comp:ma10:days10:scale0.50`: score 0.054, 10Y/5Y/3Y dAnn -0.27/+0.59/+2.07pp, full dAnn -0.07pp.
- `broad_consec_below:large_sum:ma20:days10:scale0.75`: score 0.039, 10Y/5Y/3Y dAnn -0.18/-0.22/+0.27pp, full dAnn -0.06pp.
- `broad_consec_below:zz2000:ma30:days10:scale0.50`: score 0.036, 10Y/5Y/3Y dAnn -0.92/+0.03/+1.29pp, full dAnn -0.77pp.

## Files
- `dk_volume_rule_summary.csv`: all scanned rules.
- `dk_volume_robust.csv`: rules passing the 10Y/5Y/3Y robust filter.
- `dk_volume_top80.csv`: top scored rules for inspection.
- `dk_volume_group_summary.csv`: family-level comparison.

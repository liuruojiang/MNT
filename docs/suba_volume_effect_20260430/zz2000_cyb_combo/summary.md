# CSI2000 + ChiNext Volume Combo Scan

## Setup
- `OR`: de-risk when either small-cap or growth participation contracts.
- `AND`: de-risk only when both small-cap and growth participation contract.
- Same-parameter grid plus focused cross-candidate grid around the existing CSI2000 and ChiNext ridges.

## Group Summary
- cross_candidates or scale 0.50: tested 27, robust 23, best score 0.334, median 0.230.
- cross_candidates or scale 0.25: tested 30, robust 21, best score 0.439, median 0.277.
- same_params or scale 0.50: tested 54, robust 20, best score 0.312, median 0.139.
- cross_candidates or scale 0.00: tested 27, robust 12, best score 0.439, median 0.282.
- same_params and scale 0.50: tested 54, robust 10, best score 0.167, median 0.034.
- cross_candidates and scale 0.50: tested 27, robust 9, best score 0.143, median 0.071.
- cross_candidates and scale 0.25: tested 30, robust 8, best score 0.165, median 0.076.
- cross_candidates and scale 0.00: tested 27, robust 6, best score 0.199, median 0.093.
- same_params or scale 0.00: tested 54, robust 5, best score 0.408, median 0.120.
- same_params and scale 0.00: tested 54, robust 4, best score 0.297, median 0.013.

## Interpretation
- The useful combination is `OR`, not `AND`: de-risk when either CSI2000 or ChiNext shows participation contraction. Requiring both to contract waits too long and produces much weaker median scores.
- The best `OR` families improve over the single-source CSI2000 scale0.5 rule. The clean production candidate is `ZZ2000 MA15/d3 OR CYB MA10/d3 -> scale 0.50`: full-sample annual return gives up only -0.11pp, while 10Y/5Y/3Y all improve annual return, Sharpe, and MaxDD.
- A more aggressive candidate is the same `OR` trigger with `scale 0.25`: stronger 10Y/5Y/3Y improvement, but more exposure cut and a larger full-sample annual give-up (-0.29pp). `scale 0.00` is strongest by score but is more tactical than default-worthy.
- This supports the "growth + small-cap" framing: CSI2000 catches small-cap liquidity/risk appetite, while ChiNext catches growth participation. The combination works best as a broad risk-off veto, not as a late confirmation.

## Top Robust Combos
- or scale 0.00, ZZ2000 MA15/d3, CYB MA10/d3: 10Y dAnn +2.92pp, dSharpe +0.29; 5Y dAnn +6.66pp, dSharpe +0.49; 3Y dAnn +8.79pp, dSharpe +0.53; full dAnn -0.75pp.
- or scale 0.25, ZZ2000 MA15/d3, CYB MA10/d3: 10Y dAnn +3.00pp, dSharpe +0.26; 5Y dAnn +6.81pp, dSharpe +0.46; 3Y dAnn +7.83pp, dSharpe +0.46; full dAnn -0.29pp.
- or scale 0.00, ZZ2000 MA20/d3, CYB MA10/d8: 10Y dAnn +2.70pp, dSharpe +0.22; 5Y dAnn +4.47pp, dSharpe +0.32; 3Y dAnn +11.07pp, dSharpe +0.60; full dAnn -0.34pp.
- or scale 0.00, ZZ2000 MA20/d3, CYB MA10/d3: 10Y dAnn +1.81pp, dSharpe +0.23; 5Y dAnn +5.92pp, dSharpe +0.45; 3Y dAnn +10.59pp, dSharpe +0.62; full dAnn -0.91pp.
- or scale 0.00, ZZ2000 MA15/d3, CYB MA15/d3: 10Y dAnn +2.41pp, dSharpe +0.27; 5Y dAnn +3.10pp, dSharpe +0.35; 3Y dAnn +8.11pp, dSharpe +0.53; full dAnn -0.53pp.
- or scale 0.25, ZZ2000 MA20/d3, CYB MA10/d3: 10Y dAnn +1.84pp, dSharpe +0.20; 5Y dAnn +5.84pp, dSharpe +0.40; 3Y dAnn +8.73pp, dSharpe +0.50; full dAnn -0.45pp.
- or scale 0.25, ZZ2000 MA13/d3, CYB MA10/d3: 10Y dAnn +1.27pp, dSharpe +0.21; 5Y dAnn +4.63pp, dSharpe +0.46; 3Y dAnn +6.59pp, dSharpe +0.49; full dAnn -0.74pp.
- or scale 0.00, ZZ2000 MA20/d3, CYB MA60/d8: 10Y dAnn +0.34pp, dSharpe +0.15; 5Y dAnn +2.35pp, dSharpe +0.23; 3Y dAnn +12.43pp, dSharpe +0.67; full dAnn -0.52pp.
- or scale 0.25, ZZ2000 MA30/d3, CYB MA10/d3: 10Y dAnn +1.96pp, dSharpe +0.21; 5Y dAnn +5.05pp, dSharpe +0.37; 3Y dAnn +6.58pp, dSharpe +0.41; full dAnn -0.41pp.
- or scale 0.00, ZZ2000 MA30/d3, CYB MA30/d3: 10Y dAnn +0.38pp, dSharpe +0.17; 5Y dAnn +2.16pp, dSharpe +0.28; 3Y dAnn +10.98pp, dSharpe +0.61; full dAnn -0.72pp.
- or scale 0.25, ZZ2000 MA20/d3, CYB MA60/d8: 10Y dAnn +0.57pp, dSharpe +0.14; 5Y dAnn +1.91pp, dSharpe +0.22; 3Y dAnn +9.77pp, dSharpe +0.55; full dAnn -0.24pp.
- or scale 0.00, ZZ2000 MA15/d3, CYB MA10/d8: 10Y dAnn +3.45pp, dSharpe +0.26; 5Y dAnn +4.37pp, dSharpe +0.29; 3Y dAnn +7.33pp, dSharpe +0.44; full dAnn -0.27pp.

## Files
- `zz2000_cyb_combo_scan.csv`: full combo scan.
- `zz2000_cyb_combo_robust.csv`: robust-pass combos.
- `zz2000_cyb_combo_vs_single.csv`: top combos plus key single-source rules.

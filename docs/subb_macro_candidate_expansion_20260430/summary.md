# Sub-B Macro Candidate Expansion

Stress periods add DBMF/TLT/GLD candidates instead of scaling or deleting assets.

## Baseline
- 17.53% annual, Sharpe 1.08, MaxDD -16.54%, sample 2004-07-23 to 2026-04-17.

## Top Results
- `credit_below_ma100_d5:add_dbmf`: score 0.007, stress 1551 days; 10Y dAnn +0.01pp, dSharpe +0.001, dMaxDD +0.00pp; 5Y dAnn +0.18pp; 3Y dAnn +0.31pp; full dAnn +0.01pp; robust=True, material=False.
- `credit_below_ma100_d5:add_dbmf_tlt`: score 0.007, stress 1551 days; 10Y dAnn +0.01pp, dSharpe +0.001, dMaxDD +0.00pp; 5Y dAnn +0.18pp; 3Y dAnn +0.31pp; full dAnn +0.01pp; robust=True, material=False.
- `credit_below_ma100_d5:add_dbmf_gld`: score 0.007, stress 1551 days; 10Y dAnn +0.01pp, dSharpe +0.001, dMaxDD +0.00pp; 5Y dAnn +0.18pp; 3Y dAnn +0.31pp; full dAnn +0.01pp; robust=True, material=False.
- `vix_gt30:add_dbmf`: score 0.001, stress 449 days; 10Y dAnn +0.03pp, dSharpe +0.001, dMaxDD +0.00pp; 5Y dAnn +0.04pp; 3Y dAnn +0.00pp; full dAnn +0.01pp; robust=True, material=False.
- `vix_gt30:add_dbmf_tlt`: score 0.001, stress 449 days; 10Y dAnn +0.03pp, dSharpe +0.001, dMaxDD +0.00pp; 5Y dAnn +0.04pp; 3Y dAnn +0.00pp; full dAnn +0.01pp; robust=True, material=False.
- `vix_gt30:add_dbmf_gld`: score 0.001, stress 449 days; 10Y dAnn +0.03pp, dSharpe +0.001, dMaxDD +0.00pp; 5Y dAnn +0.04pp; 3Y dAnn +0.00pp; full dAnn +0.01pp; robust=True, material=False.
- `credit_below_ma100_d3:add_dbmf`: score -0.005, stress 1711 days; 10Y dAnn -0.03pp, dSharpe -0.001, dMaxDD +0.00pp; 5Y dAnn +0.03pp; 3Y dAnn -0.10pp; full dAnn -0.01pp; robust=False, material=False.
- `credit_below_ma100_d3:add_dbmf_tlt`: score -0.005, stress 1711 days; 10Y dAnn -0.03pp, dSharpe -0.001, dMaxDD +0.00pp; 5Y dAnn +0.03pp; 3Y dAnn -0.10pp; full dAnn -0.01pp; robust=False, material=False.
- `credit_below_ma100_d3:add_dbmf_gld`: score -0.005, stress 1711 days; 10Y dAnn -0.03pp, dSharpe -0.001, dMaxDD +0.00pp; 5Y dAnn +0.03pp; 3Y dAnn -0.10pp; full dAnn -0.01pp; robust=False, material=False.
- `growth_underperform_ma100_d5:add_dbmf`: score -0.013, stress 1664 days; 10Y dAnn -0.12pp, dSharpe -0.006, dMaxDD +0.00pp; 5Y dAnn -0.12pp; 3Y dAnn +0.02pp; full dAnn -0.05pp; robust=False, material=False.
- `growth_underperform_ma100_d5:add_dbmf_tlt`: score -0.013, stress 1664 days; 10Y dAnn -0.12pp, dSharpe -0.006, dMaxDD +0.00pp; 5Y dAnn -0.12pp; 3Y dAnn +0.02pp; full dAnn -0.05pp; robust=False, material=False.
- `growth_underperform_ma100_d5:add_dbmf_gld`: score -0.013, stress 1664 days; 10Y dAnn -0.12pp, dSharpe -0.006, dMaxDD +0.00pp; 5Y dAnn -0.12pp; 3Y dAnn +0.02pp; full dAnn -0.05pp; robust=False, material=False.

## Interpretation
- No candidate expansion passed the material-effect threshold.
- The best loose robust result is credit stress adding DBMF, but the 10Y/full-sample improvement is near zero and drawdown is unchanged.

## Files
- `subb_macro_candidate_expansion_summary.csv`: all variants.
- `subb_macro_candidate_expansion_curves.csv`: daily returns/NAVs for top variants.
- `meta.json`: source paths, timing assumptions, and material-pass definition.

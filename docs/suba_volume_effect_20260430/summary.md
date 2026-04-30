# Sub-A Volume Effect Study

## Data and Timing
- Sub-A source: `mnt_bot V 7.2 plus.py` current local V7.2 script.
- Price data: `mnt_strategy_data_cn.csv`; strategy path reuses current Sub-A cash decay and same-side overheat overlays.
- Volume data: EastMoney daily K-line `amount` and `volume`, cached under this report directory.
- Timing: same-day volume is treated as known after close and only changes next close-to-close exposure.
- Costs: existing Sub-A commission and vol-scaling rebuild are included; added exposure changes pay turnover costs.

## Baseline
- Full: annual 19.95%, Sharpe 1.24, MaxDD -32.47%.
- 3Y: annual 33.64%, Sharpe 1.58, MaxDD -13.15%.

## Main Readout
- The earlier ChiNext-first readout was incomplete because CSI2000 was not in the first source set. After adding EastMoney `2.932000`, CSI2000 is the stronger small-cap participation signal.
- Tested 445 total rules after adding CSI2000. CSI2000 produced 6 robust candidates; held-ETF volume still produced no robust candidates.
- Best aggressive rule: `broad_consec_below:zz2000:ma20:days3:scale0.0`. It improves 10Y/5Y/3Y annual return, Sharpe, and MaxDD; full-sample annual return falls only -0.58pp and Sharpe improves +0.02.
- Best production-style first follow-up: `broad_consec_below:zz2000:ma20:days3:scale0.5`. It gives up only -0.11pp full-sample annual return, improves full-sample Sharpe +0.02, and still improves 10Y/5Y/3Y metrics.
- ChiNext remains useful as a growth-risk proxy, but for the specific "small-cap liquidity/risk appetite" question, CSI2000 should take priority over ChiNext and Shanghai Composite.

## Robust Candidates
- `broad_consec_below:zz2000:ma20:days3:scale0.0`: 10Y dAnn +1.56pp, dSharpe +0.18, dMaxDD +8.14pp; 5Y dAnn +4.06pp, dSharpe +0.30, dMaxDD +1.94pp; 3Y dAnn +10.13pp, dSharpe +0.56, dMaxDD +4.16pp.
- `broad_consec_below:zz2000:ma20:days3:scale0.5`: 10Y dAnn +1.13pp, dSharpe +0.11, dMaxDD +4.63pp; 5Y dAnn +2.21pp, dSharpe +0.17, dMaxDD +0.95pp; 3Y dAnn +5.11pp, dSharpe +0.30, dMaxDD +2.47pp.
- `broad_consec_below:cyb:ma10:days3:scale0.5`: 10Y dAnn +0.87pp, dSharpe +0.10, dMaxDD +4.83pp; 5Y dAnn +2.48pp, dSharpe +0.18, dMaxDD +4.23pp; 3Y dAnn +3.17pp, dSharpe +0.20, dMaxDD +3.08pp.

## Top Candidates
- `broad_consec_below:zz2000:ma20:days3:scale0.0`: 3Y dAnn +10.13pp, 3Y dSharpe +0.56, 3Y dMaxDD +4.16pp; 5Y dAnn +4.06pp, 5Y dSharpe +0.30, 5Y dMaxDD +1.94pp.
- `broad_consec_below:cyb:ma10:days3:scale0.0`: 3Y dAnn +4.80pp, 3Y dSharpe +0.31, 3Y dMaxDD +5.17pp; 5Y dAnn +2.40pp, 5Y dSharpe +0.24, 5Y dMaxDD +2.36pp.
- `broad_consec_below:zz2000:ma60:days3:scale0.0`: 3Y dAnn +7.92pp, 3Y dSharpe +0.49, 3Y dMaxDD +3.28pp; 5Y dAnn +1.20pp, 5Y dSharpe +0.17, 5Y dMaxDD -0.22pp.
- `broad_consec_below:zz1000:ma20:days3:scale0.0`: 3Y dAnn +4.83pp, 3Y dSharpe +0.35, 3Y dMaxDD +3.70pp; 5Y dAnn +1.72pp, 5Y dSharpe +0.22, 5Y dMaxDD +2.39pp.
- `broad_low_amount:zz1000:ma60:lt1.00:scale0.0`: 3Y dAnn +2.91pp, 3Y dSharpe +0.30, 3Y dMaxDD +3.71pp; 5Y dAnn +0.32pp, 5Y dSharpe +0.19, 5Y dMaxDD +3.88pp.
- `broad_consec_below:zz2000:ma60:days8:scale0.0`: 3Y dAnn +4.62pp, 3Y dSharpe +0.26, 3Y dMaxDD +4.63pp; 5Y dAnn +3.22pp, 5Y dSharpe +0.18, 5Y dMaxDD +1.05pp.
- `broad_consec_below:zz1000:ma10:days3:scale0.0`: 3Y dAnn -0.80pp, 3Y dSharpe +0.12, 3Y dMaxDD +5.00pp; 5Y dAnn +1.40pp, 5Y dSharpe +0.22, 5Y dMaxDD +4.80pp.
- `broad_consec_below:zz2000:ma20:days3:scale0.5`: 3Y dAnn +5.11pp, 3Y dSharpe +0.30, 3Y dMaxDD +2.47pp; 5Y dAnn +2.21pp, 5Y dSharpe +0.17, 5Y dMaxDD +0.95pp.
- `broad_consec_below:broad_amount_sum:ma20:days3:scale0.0`: 3Y dAnn +4.57pp, 3Y dSharpe +0.29, 3Y dMaxDD +3.68pp; 5Y dAnn -0.29pp, 5Y dSharpe +0.11, 5Y dMaxDD +2.23pp.
- `broad_consec_below:zz500:ma10:days3:scale0.0`: 3Y dAnn +1.22pp, 3Y dSharpe +0.22, 3Y dMaxDD +5.31pp; 5Y dAnn -1.59pp, 5Y dSharpe +0.08, 5Y dMaxDD +1.71pp.

## Files
- `suba_volume_rule_summary.csv`: all tested rules and window metrics.
- `suba_volume_top_candidates.csv`: ranked candidates by recent-window robustness score.
- `suba_volume_predictive_buckets.csv`: next-day return bucket check for raw volume features.
- `meta.json`: source paths, data sources, timing, and cost assumptions.

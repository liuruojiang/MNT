# DK Volume Source Ridge Comparison

## Setup
- Same defensive pass definition as the HS300 ridge scan.
- Grid: MA10..70, days5..30, scale 0/0.25/0.5/0.75.
- Timing: T-day volume is shifted one DK trading day before affecting returns.

## Source Summary
- hs300: pass 172/6344, best score 0.294, median -0.103, best 10Y dAnn +3.83pp, best 10Y dMaxDD +5.28pp.
- cyb: pass 1/6344, best score 0.220, median -0.254, best 10Y dAnn +1.78pp, best 10Y dMaxDD +5.28pp.
- zz2000: pass 0/6344, best score 0.259, median -0.351, best 10Y dAnn +3.40pp, best 10Y dMaxDD +3.45pp.

## Best Cells By Source
### cyb
- MA31/days16/scale0.25: pass=False, score 0.220, 10Y dAnn +1.24pp, dMaxDD +4.30pp; 5Y dAnn -0.03pp; 3Y dAnn +3.92pp; full dAnn -0.26pp.
- MA30/days17/scale0.25: pass=False, score 0.217, 10Y dAnn +1.31pp, dMaxDD +4.30pp; 5Y dAnn -0.02pp; 3Y dAnn +2.57pp; full dAnn -0.26pp.
- MA31/days15/scale0.25: pass=False, score 0.215, 10Y dAnn +1.34pp, dMaxDD +4.30pp; 5Y dAnn -0.18pp; 3Y dAnn +4.22pp; full dAnn -0.33pp.
- MA31/days16/scale0.00: pass=False, score 0.212, 10Y dAnn +1.59pp, dMaxDD +4.30pp; 5Y dAnn -0.11pp; 3Y dAnn +5.23pp; full dAnn -0.39pp.
- MA30/days16/scale0.25: pass=False, score 0.210, 10Y dAnn +1.19pp, dMaxDD +4.30pp; 5Y dAnn -0.18pp; 3Y dAnn +3.64pp; full dAnn -0.36pp.
- MA30/days17/scale0.00: pass=False, score 0.209, 10Y dAnn +1.70pp, dMaxDD +4.30pp; 5Y dAnn -0.08pp; 3Y dAnn +3.42pp; full dAnn -0.39pp.
- MA31/days15/scale0.00: pass=False, score 0.205, 10Y dAnn +1.73pp, dMaxDD +4.30pp; 5Y dAnn -0.31pp; 3Y dAnn +5.64pp; full dAnn -0.48pp.
- MA31/days17/scale0.25: pass=False, score 0.205, 10Y dAnn +1.00pp, dMaxDD +4.30pp; 5Y dAnn -0.14pp; 3Y dAnn +2.39pp; full dAnn -0.37pp.
### hs300
- MA21/days10/scale0.00: pass=True, score 0.294, 10Y dAnn -0.57pp, dMaxDD +5.28pp; 5Y dAnn +0.74pp; 3Y dAnn +1.06pp; full dAnn +0.00pp.
- MA21/days10/scale0.25: pass=True, score 0.289, 10Y dAnn -0.38pp, dMaxDD +5.28pp; 5Y dAnn +0.61pp; 3Y dAnn +0.87pp; full dAnn +0.05pp.
- MA33/days16/scale0.00: pass=True, score 0.264, 10Y dAnn +2.86pp, dMaxDD +4.30pp; 5Y dAnn +3.39pp; 3Y dAnn +7.39pp; full dAnn +0.26pp.
- MA32/days16/scale0.00: pass=True, score 0.262, 10Y dAnn +2.49pp, dMaxDD +4.30pp; 5Y dAnn +3.38pp; 3Y dAnn +7.39pp; full dAnn +0.39pp.
- MA39/days16/scale0.00: pass=True, score 0.261, 10Y dAnn +2.55pp, dMaxDD +4.30pp; 5Y dAnn +3.53pp; 3Y dAnn +6.39pp; full dAnn +0.26pp.
- MA32/days17/scale0.00: pass=True, score 0.257, 10Y dAnn +2.18pp, dMaxDD +4.30pp; 5Y dAnn +2.27pp; 3Y dAnn +6.80pp; full dAnn +0.38pp.
- MA33/days17/scale0.00: pass=True, score 0.256, 10Y dAnn +2.18pp, dMaxDD +4.30pp; 5Y dAnn +2.00pp; 3Y dAnn +6.80pp; full dAnn +0.15pp.
- MA41/days16/scale0.00: pass=True, score 0.256, 10Y dAnn +1.67pp, dMaxDD +4.30pp; 5Y dAnn +1.72pp; 3Y dAnn +6.29pp; full dAnn +0.23pp.
### zz2000
- MA28/days11/scale0.00: pass=False, score 0.259, 10Y dAnn +1.19pp, dMaxDD -0.08pp; 5Y dAnn +4.33pp; 3Y dAnn +7.69pp; full dAnn -0.25pp.
- MA27/days11/scale0.00: pass=False, score 0.245, 10Y dAnn +0.83pp, dMaxDD -0.08pp; 5Y dAnn +5.04pp; 3Y dAnn +8.48pp; full dAnn -0.40pp.
- MA28/days12/scale0.00: pass=False, score 0.240, 10Y dAnn +1.89pp, dMaxDD -0.00pp; 5Y dAnn +4.09pp; 3Y dAnn +8.20pp; full dAnn -0.04pp.
- MA28/days11/scale0.25: pass=False, score 0.220, 10Y dAnn +0.97pp, dMaxDD -0.06pp; 5Y dAnn +3.32pp; 3Y dAnn +5.81pp; full dAnn -0.15pp.
- MA28/days12/scale0.25: pass=False, score 0.220, 10Y dAnn +1.48pp, dMaxDD +0.00pp; 5Y dAnn +3.13pp; 3Y dAnn +6.18pp; full dAnn +0.00pp.
- MA27/days11/scale0.25: pass=False, score 0.209, 10Y dAnn +0.69pp, dMaxDD -0.06pp; 5Y dAnn +3.85pp; 3Y dAnn +6.39pp; full dAnn -0.26pp.
- MA27/days12/scale0.00: pass=False, score 0.206, 10Y dAnn +1.14pp, dMaxDD -0.00pp; 5Y dAnn +4.07pp; 3Y dAnn +8.00pp; full dAnn -0.34pp.
- MA28/days14/scale0.00: pass=False, score 0.199, 10Y dAnn +2.01pp, dMaxDD -0.00pp; 5Y dAnn +5.38pp; 3Y dAnn +8.25pp; full dAnn -0.03pp.

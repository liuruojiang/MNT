# HS300 Low-Volume DK Ridge Scan

## Setup
- Dense scan around the best DK defensive family from the broad scan.
- Rule form: HS300 amount below its moving average for N consecutive days, then scale DK exposure.
- Grid: MA10..70, days5..30, scale 0/0.25/0.5/0.75.
- Timing: T-day amount is shifted to affect the next DK trading day.

## Defensive Pass Definition
- Full annual delta >= -1.0pp; 10Y annual delta >= -1.5pp.
- 5Y and 3Y annual delta >= 0.
- 10Y/5Y/3Y Sharpe deltas >= 0.
- MaxDD improvement: 10Y >= 2.0pp, 5Y >= 1.5pp, 3Y >= 1.5pp.

## Ridge Extent By Scale
- scale 0.00: 56 pass cells, MA 17..48, days 10..17.
- scale 0.25: 56 pass cells, MA 17..49, days 10..17.
- scale 0.50: 60 pass cells, MA 20..57, days 10..17.
- scale 0.75: 0 pass cells.

## Top Defensive Cells
- MA21/days10/scale0.00: 10Y dAnn -0.57pp, dSharpe +0.06, dMaxDD +5.28pp; 5Y dAnn +0.74pp, dMaxDD +3.61pp; 3Y dAnn +1.06pp, dMaxDD +3.61pp; full dAnn +0.00pp.
- MA21/days10/scale0.25: 10Y dAnn -0.38pp, dSharpe +0.06, dMaxDD +5.28pp; 5Y dAnn +0.61pp, dMaxDD +3.00pp; 3Y dAnn +0.87pp, dMaxDD +3.00pp; full dAnn +0.05pp.
- MA33/days16/scale0.00: 10Y dAnn +2.86pp, dSharpe +0.15, dMaxDD +4.30pp; 5Y dAnn +3.39pp, dMaxDD +1.66pp; 3Y dAnn +7.39pp, dMaxDD +1.66pp; full dAnn +0.26pp.
- MA32/days16/scale0.00: 10Y dAnn +2.49pp, dSharpe +0.13, dMaxDD +4.30pp; 5Y dAnn +3.38pp, dMaxDD +1.66pp; 3Y dAnn +7.39pp, dMaxDD +1.66pp; full dAnn +0.39pp.
- MA39/days16/scale0.00: 10Y dAnn +2.55pp, dSharpe +0.14, dMaxDD +4.30pp; 5Y dAnn +3.53pp, dMaxDD +1.66pp; 3Y dAnn +6.39pp, dMaxDD +1.66pp; full dAnn +0.26pp.
- MA32/days17/scale0.00: 10Y dAnn +2.18pp, dSharpe +0.12, dMaxDD +4.30pp; 5Y dAnn +2.27pp, dMaxDD +1.66pp; 3Y dAnn +6.80pp, dMaxDD +1.66pp; full dAnn +0.38pp.
- MA33/days17/scale0.00: 10Y dAnn +2.18pp, dSharpe +0.12, dMaxDD +4.30pp; 5Y dAnn +2.00pp, dMaxDD +1.66pp; 3Y dAnn +6.80pp, dMaxDD +1.66pp; full dAnn +0.15pp.
- MA41/days16/scale0.00: 10Y dAnn +1.67pp, dSharpe +0.12, dMaxDD +4.30pp; 5Y dAnn +1.72pp, dMaxDD +1.66pp; 3Y dAnn +6.29pp, dMaxDD +1.66pp; full dAnn +0.23pp.
- MA31/days16/scale0.00: 10Y dAnn +1.42pp, dSharpe +0.09, dMaxDD +4.30pp; 5Y dAnn +2.81pp, dMaxDD +1.66pp; 3Y dAnn +7.39pp, dMaxDD +1.66pp; full dAnn +0.33pp.
- MA33/days16/scale0.25: 10Y dAnn +2.17pp, dSharpe +0.12, dMaxDD +4.30pp; 5Y dAnn +2.56pp, dMaxDD +1.66pp; 3Y dAnn +5.54pp, dMaxDD +1.66pp; full dAnn +0.22pp.
- MA43/days16/scale0.00: 10Y dAnn +1.83pp, dSharpe +0.13, dMaxDD +4.30pp; 5Y dAnn +0.51pp, dMaxDD +1.66pp; 3Y dAnn +6.48pp, dMaxDD +1.66pp; full dAnn +0.33pp.
- MA32/days16/scale0.25: 10Y dAnn +1.89pp, dSharpe +0.11, dMaxDD +4.30pp; 5Y dAnn +2.56pp, dMaxDD +1.66pp; 3Y dAnn +5.54pp, dMaxDD +1.66pp; full dAnn +0.32pp.
- MA40/days16/scale0.00: 10Y dAnn +1.55pp, dSharpe +0.11, dMaxDD +4.30pp; 5Y dAnn +1.58pp, dMaxDD +1.66pp; 3Y dAnn +6.05pp, dMaxDD +1.66pp; full dAnn +0.12pp.
- MA39/days16/scale0.25: 10Y dAnn +1.94pp, dSharpe +0.12, dMaxDD +4.30pp; 5Y dAnn +2.67pp, dMaxDD +1.66pp; 3Y dAnn +4.80pp, dMaxDD +1.66pp; full dAnn +0.23pp.
- MA31/days17/scale0.00: 10Y dAnn +1.52pp, dSharpe +0.09, dMaxDD +4.30pp; 5Y dAnn +1.71pp, dMaxDD +1.66pp; 3Y dAnn +6.80pp, dMaxDD +1.66pp; full dAnn +0.35pp.
- MA36/days16/scale0.00: 10Y dAnn +2.52pp, dSharpe +0.14, dMaxDD +4.30pp; 5Y dAnn +3.59pp, dMaxDD +1.66pp; 3Y dAnn +7.34pp, dMaxDD +1.66pp; full dAnn -0.11pp.
- MA41/days16/scale0.25: 10Y dAnn +1.28pp, dSharpe +0.10, dMaxDD +4.30pp; 5Y dAnn +1.33pp, dMaxDD +1.66pp; 3Y dAnn +4.73pp, dMaxDD +1.66pp; full dAnn +0.22pp.
- MA23/days17/scale0.00: 10Y dAnn +1.89pp, dSharpe +0.10, dMaxDD +4.30pp; 5Y dAnn +1.33pp, dMaxDD +1.66pp; 3Y dAnn +5.26pp, dMaxDD +1.66pp; full dAnn +0.12pp.
- MA32/days17/scale0.25: 10Y dAnn +1.65pp, dSharpe +0.09, dMaxDD +4.30pp; 5Y dAnn +1.73pp, dMaxDD +1.66pp; 3Y dAnn +5.10pp, dMaxDD +1.66pp; full dAnn +0.31pp.
- MA33/days17/scale0.25: 10Y dAnn +1.65pp, dSharpe +0.10, dMaxDD +4.30pp; 5Y dAnn +1.52pp, dMaxDD +1.66pp; 3Y dAnn +5.10pp, dMaxDD +1.66pp; full dAnn +0.14pp.

## Candidate Neighborhood
- MA18/days10/scale0.25: pass=False, 10Y dAnn -1.41pp, dMaxDD +4.45pp; 5Y dAnn -0.94pp; 3Y dAnn -1.00pp; full dAnn -0.79pp.
- MA20/days9/scale0.25: pass=False, 10Y dAnn -2.84pp, dMaxDD +3.00pp; 5Y dAnn -1.35pp; 3Y dAnn +0.71pp; full dAnn -1.12pp.
- MA20/days10/scale0.25: pass=True, 10Y dAnn -1.06pp, dMaxDD +5.28pp; 5Y dAnn +1.14pp; 3Y dAnn +0.87pp; full dAnn -0.49pp.
- MA20/days11/scale0.25: pass=False, 10Y dAnn -2.52pp, dMaxDD +5.19pp; 5Y dAnn -0.40pp; 3Y dAnn -0.88pp; full dAnn -1.51pp.
- MA22/days10/scale0.25: pass=False, 10Y dAnn -1.50pp, dMaxDD +2.72pp; 5Y dAnn -1.87pp; 3Y dAnn -0.88pp; full dAnn -0.01pp.
- MA20/days10/scale0.50: pass=True, 10Y dAnn -0.67pp, dMaxDD +3.50pp; 5Y dAnn +0.80pp; 3Y dAnn +0.62pp; full dAnn -0.30pp.
- MA20/days10/scale0.75: pass=False, 10Y dAnn -0.32pp, dMaxDD +1.74pp; 5Y dAnn +0.42pp; 3Y dAnn +0.34pp; full dAnn -0.13pp.

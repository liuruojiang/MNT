# CSI2000 Volume Ridge Scan

## Grid
- MA grid: [5, 8, 10, 13, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120]
- Consecutive-day grid: 1..15
- Scale grid: [0.0, 0.25, 0.5, 0.75]

## Ridge Summary
- scale 0.00: robust cells 26. Main fast ridge: MA 13..20, days 3..4. Main slow ridge: MA 40..60, days 7..15. Best robust: MA 20, days 3.
- scale 0.25: robust cells 29. Main fast ridge: MA 13..40, days 2..4. Main slow ridge: MA 50..60, days 7..15. Best robust: MA 15, days 3.
- scale 0.50: robust cells 32. Main fast ridge: MA 13..60, days 2..4. Main slow ridge: MA 50..60, days 6..15. Best robust: MA 15, days 3.
- scale 0.75: robust cells 12. Ridges are thinner; useful cells cluster around MA 40..60 days 3..4 plus a few long-window islands. Best robust: MA 20, days 3.

## Interpretation
- The signal is not a single-parameter spike. There are two visible ridges: a fast confirmation ridge around MA 13..30 with 2..4 consecutive below-average days, and a slower confirmation ridge around MA 50..60 with roughly 6..15 days.
- MA20 / days3 sits inside the fast ridge rather than alone. It remains the cleanest aggressive point for scale0.0, but MA13/15/20/30 with days2..4 broadly tells the same story.
- For production use, scale0.5 is still the safer family: it has the most robust cells, preserves full-sample annual return better, and its fast ridge is wider than scale0.0.

## Top Robust Rules
- scale 0.00, MA 20, days 3: 10Y dAnn +1.56pp, dSharpe +0.18, dMaxDD +8.14pp; 5Y dAnn +4.06pp, dSharpe +0.30, dMaxDD +1.94pp; 3Y dAnn +10.13pp, dSharpe +0.56, dMaxDD +4.16pp; full dAnn -0.58pp.
- scale 0.00, MA 13, days 3: 10Y dAnn +1.85pp, dSharpe +0.21, dMaxDD +8.35pp; 5Y dAnn +3.76pp, dSharpe +0.32, dMaxDD +1.36pp; 3Y dAnn +7.50pp, dSharpe +0.50, dMaxDD +2.01pp; full dAnn -0.62pp.
- scale 0.00, MA 15, days 3: 10Y dAnn +2.54pp, dSharpe +0.22, dMaxDD +8.37pp; 5Y dAnn +4.73pp, dSharpe +0.30, dMaxDD +1.32pp; 3Y dAnn +7.33pp, dSharpe +0.44, dMaxDD +1.38pp; full dAnn -0.46pp.
- scale 0.25, MA 15, days 3: 10Y dAnn +2.59pp, dSharpe +0.20, dMaxDD +6.88pp; 5Y dAnn +4.47pp, dSharpe +0.27, dMaxDD +0.66pp; 3Y dAnn +6.41pp, dSharpe +0.37, dMaxDD +1.35pp; full dAnn -0.12pp.
- scale 0.25, MA 20, days 3: 10Y dAnn +1.42pp, dSharpe +0.14, dMaxDD +6.14pp; 5Y dAnn +3.16pp, dSharpe +0.23, dMaxDD +1.34pp; 3Y dAnn +7.81pp, dSharpe +0.43, dMaxDD +3.03pp; full dAnn -0.29pp.
- scale 0.00, MA 30, days 3: 10Y dAnn +0.39pp, dSharpe +0.11, dMaxDD +1.15pp; 5Y dAnn +2.55pp, dSharpe +0.23, dMaxDD +1.94pp; 3Y dAnn +6.73pp, dSharpe +0.42, dMaxDD +4.15pp; full dAnn -0.24pp.
- scale 0.25, MA 13, days 3: 10Y dAnn +1.52pp, dSharpe +0.17, dMaxDD +7.33pp; 5Y dAnn +2.83pp, dSharpe +0.25, dMaxDD +0.70pp; 3Y dAnn +5.18pp, dSharpe +0.38, dMaxDD +1.53pp; full dAnn -0.40pp.
- scale 0.00, MA 50, days 8: 10Y dAnn +1.23pp, dSharpe +0.10, dMaxDD +2.67pp; 5Y dAnn +4.58pp, dSharpe +0.24, dMaxDD +1.04pp; 3Y dAnn +7.21pp, dSharpe +0.36, dMaxDD +3.73pp; full dAnn -0.33pp.
- scale 0.25, MA 20, days 2: 10Y dAnn +0.74pp, dSharpe +0.13, dMaxDD +5.78pp; 5Y dAnn +2.68pp, dSharpe +0.22, dMaxDD +1.08pp; 3Y dAnn +5.21pp, dSharpe +0.39, dMaxDD +4.02pp; full dAnn -0.60pp.
- scale 0.25, MA 30, days 3: 10Y dAnn +0.60pp, dSharpe +0.09, dMaxDD +1.94pp; 5Y dAnn +2.33pp, dSharpe +0.18, dMaxDD +1.14pp; 3Y dAnn +5.41pp, dSharpe +0.32, dMaxDD +3.07pp; full dAnn +0.00pp.
- scale 0.25, MA 13, days 2: 10Y dAnn +0.36pp, dSharpe +0.16, dMaxDD +4.99pp; 5Y dAnn +2.19pp, dSharpe +0.27, dMaxDD +1.31pp; 3Y dAnn +2.83pp, dSharpe +0.37, dMaxDD +2.67pp; full dAnn -0.75pp.
- scale 0.00, MA 20, days 4: 10Y dAnn +0.93pp, dSharpe +0.12, dMaxDD +7.97pp; 5Y dAnn +0.97pp, dSharpe +0.14, dMaxDD +1.17pp; 3Y dAnn +5.90pp, dSharpe +0.37, dMaxDD +3.73pp; full dAnn -0.41pp.

## Files
- `zz2000_volume_ridge_scan.csv`: full dense grid.
- `ridge_pass_scale_*.csv`: robust-pass heatmap matrices.
- `ridge_score_scale_*.csv`: score heatmap matrices.
- `zz2000_volume_ridge_robust.csv`: rules passing the robustness filter.

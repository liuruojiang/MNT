# V7.2 Sub-B CTA Candidate Test: DBMF

Generated: 2026-04-29T21:14:39.104662+08:00

## Scope

- Research only; no production strategy file changed.
- Official Sub-B candidate pool is unchanged for the baseline.
- Variant adds `DBMF` to Sub-B ranking candidates while preserving the existing 130/260/390 day momentum mix, absolute momentum gate, BIL cash fallback, target-vol scaling, commission model, and VolReg overlay.
- `DBMF` is allowed to participate only after its local price history supports the required momentum and volatility calculations.
- V7.2 composition is unchanged except that its 60% Sub-B sleeve uses the DBMF-added variant.

## Key Results

| Window                   | Series               | Total    | Annual   |   Sharpe | MaxDD   |
|:-------------------------|:---------------------|:---------|:---------|---------:|:--------|
| full_common              | Sub-B official       | 926.63%  | 24.80%   |     1.24 | -15.80% |
| full_common              | Sub-B + DBMF         | 967.70%  | 25.27%   |     1.27 | -14.40% |
| full_common              | V7.2 official        | 1319.29% | 28.71%   |     2.32 | -7.21%  |
| full_common              | V7.2 + DBMF in Sub-B | 1343.92% | 28.92%   |     2.34 | -7.21%  |
| since_dbmf_first_weight  | Sub-B official       | 395.61%  | 27.74%   |     1.29 | -15.80% |
| since_dbmf_first_weight  | Sub-B + DBMF         | 415.44%  | 28.51%   |     1.33 | -12.36% |
| since_dbmf_first_weight  | V7.2 official        | 474.57%  | 30.66%   |     2.37 | -5.83%  |
| since_dbmf_first_weight  | V7.2 + DBMF in Sub-B | 484.54%  | 31.00%   |     2.4  | -6.00%  |
| high_inflation_2021_2022 | Sub-B official       | 20.48%   | 9.79%    |     0.56 | -14.51% |
| high_inflation_2021_2022 | Sub-B + DBMF         | 27.27%   | 12.84%   |     0.72 | -10.65% |
| high_inflation_2021_2022 | V7.2 official        | 57.84%   | 25.69%   |     1.97 | -4.99%  |
| high_inflation_2021_2022 | V7.2 + DBMF in Sub-B | 61.62%   | 27.19%   |     2.1  | -4.47%  |
| inflation_shock_2022     | Sub-B official       | -3.41%   | -4.10%   |    -0.23 | -14.51% |
| inflation_shock_2022     | Sub-B + DBMF         | 5.24%    | 6.35%    |     0.47 | -9.17%  |
| inflation_shock_2022     | V7.2 official        | 17.10%   | 20.96%   |     1.74 | -4.99%  |
| inflation_shock_2022     | V7.2 + DBMF in Sub-B | 21.69%   | 26.70%   |     2.23 | -3.97%  |
| latest_3y                | Sub-B official       | 154.18%  | 36.46%   |     1.53 | -11.70% |
| latest_3y                | Sub-B + DBMF         | 153.81%  | 36.40%   |     1.54 | -12.36% |
| latest_3y                | V7.2 official        | 143.21%  | 34.47%   |     2.6  | -5.83%  |
| latest_3y                | V7.2 + DBMF in Sub-B | 143.24%  | 34.48%   |     2.6  | -6.00%  |

## DBMF Weight Usage

| window                   |   avg_weight |   max_weight |   active_day_rate_gt_1pct |
|:-------------------------|-------------:|-------------:|--------------------------:|
| full_subb                |       0.0524 |       0.5103 |                    0.2352 |
| since_dbmf_first_weight  |       0.0842 |       0.5103 |                    0.3780 |
| inflation_ramp_2021      |       0.0281 |       0.1959 |                    0.2110 |
| inflation_shock_2022     |       0.3179 |       0.5103 |                    0.8914 |
| high_inflation_2021_2022 |       0.1674 |       0.5103 |                    0.5603 |
| latest_3y                |       0.0476 |       0.3192 |                    0.2871 |

## Interpretation

- Full common V7.2 annual changed from 28.71% to 28.92%; MaxDD changed from -7.21% to -7.21%.
- 2021-2022 high-inflation V7.2 total return changed from 57.84% to 61.62%.
- Latest 3Y V7.2 annual changed from 34.47% to 34.48%; this is the cleanest live-era penalty/benefit check because DBMF is fully seasoned.
- Candidate-pool expansion is not free: DBMF must beat existing assets after the same ranking, absolute-momentum and turnover rules; otherwise it mainly adds an extra way to displace a stronger existing long asset.

## Files

- `subb_dbmf_window_metrics.csv`
- `subb_dbmf_weight_summary.csv`
- `subb_dbmf_signal_weights.csv`
- `meta.json`
# V7.6 Microcap V1.6 Dynamic Advisory Fit Check

- Rule: `dd_3_10_month_end`
- Microcap source version: `v1.6`
- Latest date: `2026-05-08`
- Latest Microcap drawdown: `-17.49%`
- Prior drawdown used for latest daily signal: `-18.68%`
- Latest daily signal Microcap weight: `10%`
- Last month-end execution date: `2026-04-30`
- Current executed month-end Microcap weight: `10%`

## Current Advisory Combo Weights

| Sleeve | Advisory weight |
|---|---:|
| Sub-A | 10% |
| Sub-A-DK | 15% |
| Microcap | 10% |
| Sub-B | 65% |

## Implementation Fit

- Use v1.6 as the current mainline Microcap source.
- V7.6 loader has been corrected to v1.6 for the current mainline source.
- No Microcap v1.6 internal change is required.
- Do not change production `COMBINED_WEIGHTS` yet.

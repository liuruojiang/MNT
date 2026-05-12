# V7.6 Microcap Dynamic Advisory Fit Check

- Rule: `dd_5_12_month_end`
- Latest date: `2026-05-08`
- Latest Microcap drawdown: `-19.82%`
- Prior drawdown used for latest daily signal: `-21.05%`
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

- Existing V7.6 Microcap loader is enough to compute the rule.
- No Microcap v1.8 internal source change is required.
- Treat this as advisory display first; do not change production `COMBINED_WEIGHTS` yet.
- Keep the no-microcap performance query unchanged unless a separate full-combo PV query is built.

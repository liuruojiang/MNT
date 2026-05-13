# V7.6 Level-8 Risk Governance

## Decision

- Status: **ACTIVE_OK**
- Action: Continue using stacked active dynamic budget.
- Curve latest: `2026-05-12`
- Source latest: `2026-05-12`
- Latest active excess NAV vs fixed: 26.25%
- Active relative NAV drawdown from its own peak: -0.37%

## Rules

| Rule | Status | Value | Threshold | Note |
|---|---|---:|---:|---|
| data_freshness | ACTIVE_OK | 2026-05-12 | fresh | Scenario curve is current relative to the aligned source returns. |
| active_row | ACTIVE_OK | advisory_suba_microcap_dd_3_10_month_end | advisory_suba_microcap_dd_3_10_month_end | Dashboard marks the stacked scenario as ACTIVE_DEFAULT. |
| full_window_evidence | ACTIVE_OK | annual 2.13%, maxDD 0.72%, sharpe 0.16 | all >= 0, annual/sharpe strictly > 0 | Full-window evidence must remain positive versus fixed. |
| latest_1y_evidence | ACTIVE_OK | annual 3.29%, maxDD 0.18%, sharpe 0.31 | all >= 0, annual/sharpe strictly > 0 | Recent-window evidence should remain positive; failure starts review before hard rollback. |
| execution_load | ACTIVE_OK | switches 122, turnover 13.8 | switches <= 140, turnover <= 15.0 | Execution load should stay near the accepted stacked-budget level. |
| weight_sanity | ACTIVE_OK | Sub-A 15.00%, Sub-A-DK 15.00%, Microcap 15.00%, Sub-D 20.00%, Sub-B 35.00% | sum = 100%, each sleeve in [0%, 100%] | Active budget must remain a valid five-sleeve allocation. |
| relative_nav_drawdown | ACTIVE_OK | current -0.37%, worst -2.54% | > -5.00% | Active budget has not breached the relative drawdown review threshold. |

## Read

This is a governance layer, not a new optimizer. It decides whether the current stacked active budget can remain active, should move to manual review, or should roll back to fixed `10/15/15/20/40`.
# V7.6 Level-8 Risk Governance

## Decision

- Status: **ROLLBACK_FIXED**
- Action: Use fixed 10/15/15/20/40 until the failed rule is repaired and rerun.
- Curve latest: `2026-05-13`
- Source latest: `2026-05-13`
- Latest active excess NAV vs fixed: 1.67%
- Active relative NAV drawdown from its own peak: -1.62%

## Rules

| Rule | Status | Value | Threshold | Note |
|---|---|---:|---:|---|
| data_freshness | ACTIVE_OK | 2026-05-13 | fresh | Scenario curve is current relative to the aligned source returns. |
| active_row | ROLLBACK_FIXED | missing | advisory_suba_microcap_subd_dd_7_10_month_end | Dashboard does not mark the stacked scenario as ACTIVE_DEFAULT. |
| relative_nav_drawdown | ACTIVE_OK | current -1.62%, worst -4.60% | > -5.00% | Active budget has not breached the relative drawdown review threshold. |

## Read

This is a governance layer, not a new optimizer. It decides whether the current stacked active budget can remain active, should move to manual review, or should roll back to fixed `10/15/15/20/40`.
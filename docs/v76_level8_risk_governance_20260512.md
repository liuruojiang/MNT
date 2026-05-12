# V7.6 Level-8 Risk Governance - 2026-05-12

## Purpose

After promoting `advisory_suba_microcap_dd_3_10_month_end` to active, the next Level-8 step is governance rather than another parameter scan.

This record defines when the stacked active budget can continue, when it needs manual review, and when it should roll back to fixed `10/15/15/20/40`.

## Script

```powershell
python build_v76_level8_risk_governance.py
```

Inputs:

- `outputs/portfolio_v76_current/level8_decision_dashboard.csv`
- `outputs/portfolio_v76_current/scenario_economic_curve.csv`
- `quant_param_scan_runs/20260512_v76_five_sleeve_real_subd_v16_rebalance_validation/aligned_five_sleeve_real_subd_returns.csv`

Outputs:

- `outputs/portfolio_v76_current/level8_risk_governance.csv`
- `outputs/portfolio_v76_current/level8_risk_governance.md`

## Governance Rules

| Rule | Continue | Review | Roll back fixed |
|---|---|---|---|
| Data freshness | Scenario curve latest date is at least source latest date | n/a | Scenario curve is stale or missing |
| Active row | Stacked scenario is `ACTIVE_DEFAULT` | n/a | Stacked scenario is missing or not active |
| Full-window evidence | Annual, maxDD delta, and Sharpe delta versus fixed all stay positive/non-negative | n/a | Full annual or Sharpe delta <= 0, or maxDD delta < 0 |
| Latest-1Y evidence | Annual, maxDD delta, and Sharpe delta versus fixed all stay positive/non-negative | Any latest-1Y evidence failure | n/a |
| Execution load | Switches <= 140 and allocation turnover <= 15.0 | Breach either execution-load limit | n/a |
| Weight sanity | Five sleeve weights sum to 100% and each sleeve is between 0% and 100% | n/a | Invalid weights |
| Relative NAV drawdown | Active-vs-fixed relative NAV drawdown > -5% | <= -5% | <= -10% |

## Current Result

Current real-data run:

```text
Status: ACTIVE_OK
Action: Continue using stacked active dynamic budget.
Curve latest: 2026-05-08
Source latest: 2026-05-08
Latest active excess NAV vs fixed: +26.93%
Active relative NAV drawdown from its own peak: -0.18%
Worst active relative NAV drawdown: -2.54%
```

Rule snapshot:

| Rule | Status | Value |
|---|---|---:|
| data_freshness | ACTIVE_OK | 2026-05-08 |
| active_row | ACTIVE_OK | `advisory_suba_microcap_dd_3_10_month_end` |
| full_window_evidence | ACTIVE_OK | annual +2.18%, maxDD +0.72%, Sharpe +0.17 |
| latest_1y_evidence | ACTIVE_OK | annual +4.35%, maxDD +0.38%, Sharpe +0.40 |
| execution_load | ACTIVE_OK | switches 123, turnover 13.9 |
| weight_sanity | ACTIVE_OK | 15% / 15% / 10% / 20% / 40% |
| relative_nav_drawdown | ACTIVE_OK | current -0.18%, worst -2.54% |

## Decision

Keep the stacked active dynamic budget live.

Do not promote another Level-8 candidate until this governance layer remains stable over live refresh cycles. If any rule moves to `REVIEW`, pause new candidate promotion and inspect the rule. If any rule moves to `ROLLBACK_FIXED`, use fixed `10/15/15/20/40` until the source problem is repaired and the dashboard is rerun.

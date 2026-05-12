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

## Display Integration

Follow-up implementation:

- `mnt_bot V 7.6 plus.py` reads `outputs/portfolio_v76_current/level8_risk_governance.csv` in the existing portfolio dynamic-budget panel.
- `poe_v76_level8_advisory_bot.py` embeds the current governance snapshot for the standalone Poe display bot.
- The displayed governance line shows:
  - current status: `ACTIVE_OK`
  - active-vs-fixed relative NAV drawdown: current `-0.18%`, worst `-2.54%`
  - execution load: `123` switches, turnover `13.9`
  - review line: `> -5.00%`

Validation:

```powershell
python -m py_compile "mnt_bot V 7.6 plus.py" poe_v76_level8_advisory_bot.py build_v76_level8_risk_governance.py
python poe_v76_level8_advisory_bot.py
```

The V7.6 panel smoke check confirmed the rendered line:

```text
Level-8 governance: ACTIVE_OK; relative NAV DD current -0.18%, worst -2.54%; execution load switches 123, turnover 13.9; review line > -5.00%.
```

## Freeze Observation

After PR #5 display integration was merged, the real refresh sequence was rerun on `main`:

```powershell
python build_v76_portfolio_nav.py
python build_v76_level8_decision_dashboard.py
python build_v76_level8_risk_governance.py
```

Refresh result:

- refreshed at: `2026-05-12T17:53:13`
- latest data date: `2026-05-08`
- active budget: `advisory_suba_microcap_dd_3_10_month_end`
- active latest weights: Sub-A `15%`, Sub-A-DK `15%`, Microcap `10%`, Sub-D `20%`, Sub-B `40%`
- benchmark / rollback: fixed `10/15/15/20/40`
- governance status: `ACTIVE_OK`
- relative NAV drawdown: current `-0.18%`, worst `-2.54%`
- execution load: `123` switches, turnover `13.9`

Freeze rule:

- Do not add another Level-8 overlay or promote another dynamic-budget candidate during the observation window.
- Each live refresh should rerun the same three-script sequence and check `level8_risk_governance.csv`.
- If governance remains `ACTIVE_OK`, keep the stacked budget active.
- If any rule becomes `REVIEW`, stop new promotion work and inspect the failed rule before changing allocations.
- If any rule becomes `ROLLBACK_FIXED`, use fixed `10/15/15/20/40` until the source output is repaired and the full refresh sequence returns to `ACTIVE_OK`.

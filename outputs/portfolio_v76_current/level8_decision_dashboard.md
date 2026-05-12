# V7.6 Level-8 Decision Dashboard

## Decision Status

- Status: **ACTIVE_DEFAULT**
- Data freshness: **fresh** (scenario curve latest 2026-05-08)
- Latest date: `2026-05-08`
- Primary action: Use stacked Sub-A 5/8 weekly + Microcap 3/10 month-end as the active portfolio-level dynamic budget; keep fixed weights as benchmark and rollback.
- Active scenario: `advisory_suba_microcap_dd_3_10_month_end`

## Scenario Snapshot

| Scenario | Status | Sub-A | Sub-A-DK | Microcap | Sub-D | Sub-B | Dynamic sleeves | Full annual / MaxDD / Sharpe | 1Y annual / MaxDD / Sharpe | Excess NAV | Switches | Turnover | Note |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---|
| Fixed default | BASELINE | 10% | 15% | 15% | 20% | 40% | none | 30.38% / -7.87% / 3.27 | 59.01% / -5.71% / 5.21 | n/a | 0 | 0.0 | Executable default benchmark. |
| Stacked Sub-A 5/8 weekly + Microcap 3/10 month-end | ACTIVE_DEFAULT | 15% | 15% | 10% | 20% | 40% | Sub-A,Microcap | 32.56% / -7.16% / 3.44 | 63.36% / -5.33% / 5.61 | 26.93% | 123 | 13.9 | Active stacked portfolio-level dynamic budget; fixed weights remain the benchmark and rollback line. |
| Sub-A 5/8 weekly advisory | REPORT_WATCH_ONLY | 15% | 15% | 15% | 20% | 35% | Sub-A | 31.67% / -7.10% / 3.36 | 61.26% / -5.24% / 5.46 | 15.26% | 68 | 7.7 | Former active component; superseded by the adopted stacked dynamic budget. |
| Microcap advisory | REPORT_WATCH_ONLY | 10% | 15% | 10% | 20% | 45% | Microcap | 31.26% / -7.92% / 3.36 | 61.07% / -5.73% / 5.35 | 10.12% | 59 | 6.3 | Positive return evidence but max drawdown worsens versus fixed default. |
| Sub-A-DK best own-DD advisory | REPORT_WATCH_ONLY | 10% | 10% | 15% | 20% | 45% | Sub-A-DK | 30.78% / -9.12% / 3.29 | 60.60% / -6.38% / 5.28 | n/a | 190 | 19.3 | Positive return evidence but max drawdown worsens versus fixed default. |
| Sub-D best own-DD advisory | REPORT_WATCH_ONLY | 10% | 15% | 15% | 25% | 35% | Sub-D | 30.59% / -7.99% / 3.23 | 62.52% / -5.33% / 5.47 | n/a | 117 | 15.9 | Strong recent-window evidence, but full-sample Sharpe is not robust enough for default promotion. |
| Sub-B best own-DD advisory | DEFER | 10% | 14% | 14% | 19% | 42% | Sub-B | 30.20% / -7.82% / 3.25 | 58.85% / -5.89% / 5.15 | n/a | 55 | 2.8 | Sub-B dynamic budget is weak under the proportional absorber design. |

## Read

This dashboard is the portfolio-level budget decision surface. The stacked Sub-A 5/8 weekly + Microcap 3/10 month-end rule is the active dynamic budget; fixed weights remain the benchmark and rollback line.

Status labels: ACTIVE_DEFAULT means the current portfolio-level dynamic budget; LANDING_CANDIDATE means next implementation candidate; REPORT_WATCH_ONLY means useful evidence but not a default; DEFER means not suitable under the current test design.
# Sub-A Execution Layer Scan

- Target: switch buffer, entry fraction, and entry wait behavior
- Metrics shown first: recent 10Y CAGR and MaxDD
- Modes: `isolated_execution` neutralizes downstream sizing/overlays; `formal` restores V7.5 current sizing/overlays

## Audit

- `formal`: variants `24`, data `2010-06-01` -> `2026-04-30`, rows `3865`
  - target-vol `0.3`, volume overlay `True`

## Top 12 By Mode And 10Y CAGR

### formal

| rank | MA | slope | R2 | buffer | entry | wait | 10Y CAGR | 10Y MaxDD |
|---:|---:|---:|---:|---:|---:|---|---:|---:|
| 1 | 60 | 20 | 20/0.20 | 1.03 | 1.00 | none | 30.51% | -23.52% |
| 2 | 60 | 20 | 20/0.20 | 1.06 | 1.00 | none | 30.35% | -23.52% |
| 3 | 60 | 20 | 20/0.20 | 1.10 | 1.00 | none | 30.13% | -23.52% |
| 4 | 60 | 20 | 20/0.20 | 1.00 | 1.00 | none | 29.45% | -23.99% |
| 5 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 3 | 29.33% | -19.88% |
| 6 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | none | 29.24% | -19.85% |
| 7 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 10 | 29.24% | -19.85% |
| 8 | 60 | 20 | 20/0.20 | 1.03 | 0.50 | 5 | 29.22% | -19.85% |
| 9 | 60 | 20 | 20/0.20 | 1.06 | 0.50 | 3 | 29.17% | -19.88% |
| 10 | 60 | 20 | 20/0.20 | 1.06 | 0.50 | none | 29.08% | -19.85% |
| 11 | 60 | 20 | 20/0.20 | 1.06 | 0.50 | 10 | 29.08% | -19.85% |
| 12 | 60 | 20 | 20/0.20 | 1.06 | 0.50 | 5 | 29.06% | -19.85% |

## Interpretation Notes

- Compare `isolated_execution` first to understand execution-rule contribution.
- Compare `formal` next to see whether the rule survives V7.5 target-vol and overlays.
- If full entry dominates, the current half-entry/wait rule is likely costing CAGR unless it materially improves drawdown.
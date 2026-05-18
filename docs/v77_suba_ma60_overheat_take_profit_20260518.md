# V7.7 Sub-A MA60 Overheat Take-Profit Promotion

Date: 2026-05-18

## Decision

Promote the Sub-A MA60 overheat take-profit overlay into the formal V7.7 path:

- Enabled: `CN_SA_SAME_SIDE_OVERHEAT_ENABLED = True`
- Trigger: `price / MA60 - 1 >= 27%` while bias momentum is same-side positive
- Recovery: `price / MA60 - 1 <= 24%`
- Defensive exposure: `0.00x`, effectively cash while the overlay is active
- Timing: close-derived signal affects the next close-to-close holding state

The overlay is applied after the core Sub-A signal path and before the formal Sub-A volume overlay.

## Evidence

The supporting scan was `quant_param_scan_runs/20260518_a_v7_7_sub_a_ma60_overheat_take_profit_narrow`.
It used the real V7.7 Sub-A code path and local CN data through 2026-05-14. The scratch scan directory was removed after promotion; this document preserves the decision table.

| Variant | 10Y Ann / Sharpe / MaxDD | 5Y Ann / Sharpe / MaxDD | 3Y Ann / Sharpe / MaxDD | 1Y Ann / Sharpe / MaxDD |
|:-|:-|:-|:-|:-|
| Baseline no take-profit | 34.90% / 1.48 / -21.66% | 47.58% / 1.73 / -16.18% | 68.28% / 2.03 / -6.80% | 117.96% / 3.83 / -6.21% |
| MA60 overheat 27/24 scale0 | 36.35% / 1.54 / -21.66% | 48.55% / 1.76 / -16.18% | 70.14% / 2.08 / -6.80% | 117.96% / 3.83 / -6.21% |

Candidate win counts versus baseline in the narrow MA60 scan:

- 10Y: annualized return 78/108, Sharpe 96/108, MaxDD 0/108
- 5Y: annualized return 63/108, Sharpe 63/108, MaxDD 0/108
- 3Y: annualized return 63/108, Sharpe 65/108, MaxDD 0/108
- 1Y: annualized return 0/108, Sharpe 0/108, MaxDD 0/108

The later score peak-decay and MFE giveback take-profit scans were rejected. Under the tested definitions, MA60 overheat 27/24 scale0 remained the only supported take-profit candidate.

## Current State Snapshot

As of the local data cutoff 2026-05-14, the promoted MA60 overheat overlay was not active. Its last active date in the scan was 2025-09-02.

## Notes

This promotion does not change the Sub-A base ranking model, R2 gate, absolute momentum gate, target-vol scaling, or volume overlay rule. It only enables the existing timing-safe MA60 overheat overlay with the selected thresholds.

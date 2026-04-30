# Sub-C Phase2 drawdown derisk decision note - 2026-04-28

## What was tested

- Production source: `mnt_bot V 7.1 plus.py`
- Verified Sub-C daily path: `_compute_daily_subc_phased()` + official vol-scaling semantics
- Parity checks:
  - `_get_subc_daily_ret()` parity: `0`
  - effective-scale cost-model parity: `0`
- Scan:
  - Phase2-only gate, from `BTC_BT_START` / 2022-01-01 onward
  - trigger drawdown: 3% to 8%
  - cut: 10% to 50%
  - recover drawdown: 1% to 4%
  - references: `baseline_nav` and `self_nav`

## Result

Strict no-overfit filter found no `robust_candidate` rows. This is a warning that the rule's benefit is still tied to 2022 stress protection and carries some post-2022 / recent-1Y return drag.

This is not a single-point fit. A defensive platform appears around:

- trigger drawdown: 3% to 4%
- cut: 25% to 40%
- recover drawdown: 2% to 3%
- preferred reference: `baseline_nav`

Representative conservative candidate:

- `phase2_baseline_nav_trigger0.040_cut0.25_recover0.020`
- full annual return: 11.81%
- full Sharpe: 0.92
- full max drawdown: -18.70%
- Phase2 total return: 63.50%
- Phase2 max drawdown: -17.59%
- recent 1Y return: 28.03%

Baseline Sub-C:

- full annual return: 11.87%
- full Sharpe: 0.88
- full max drawdown: -23.40%
- Phase2 total return: 65.04%
- Phase2 max drawdown: -22.36%
- recent 1Y return: 29.80%

## Decision

Do not treat this as confirmed alpha improvement. Treat it as a defensive overlay candidate.

If production testing continues, prefer the platform-center rule:

- Phase2-only
- reference: `baseline_nav`
- trigger: 4% drawdown
- cut: 25%
- recover: -2% drawdown

Do not choose the single best row just because it ranks first; the more defensible choice is the stable neighborhood.

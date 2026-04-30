# Sub-A Volume Overlay Decision Record

Date: 2026-04-30

## Scope

This record summarizes the Sub-A volume-overlay research before moving to Sub-A-DK.

The tested path reused the current local `mnt_bot V 7.2 plus.py` Sub-A implementation, including existing commission, vol-scaling, cash decay, and same-side overheat overlays. Volume data came from real EastMoney daily K-line amount/volume where available, with ETF fallback noted in `meta.json`.

## Main Result

The strongest practical family is broad risk-appetite volume contraction, not the current holding ETF's own volume.

Preferred production-style candidate:

```text
If CSI2000 amount < MA15 for 3 consecutive days
OR ChiNext amount < MA10 for 3 consecutive days,
then scale Sub-A equity exposure to 50%.
```

Observed versus current Sub-A:

| Window | Annual delta | Sharpe delta | MaxDD delta |
|---|---:|---:|---:|
| Full available Sub-A sample | -0.11pp | +0.04 | +0.00pp |
| Last 10Y | +2.43pp | +0.20 | +5.15pp |
| Last 5Y | +5.40pp | +0.33 | +3.70pp |
| Last 3Y | +5.59pp | +0.32 | +3.58pp |

More aggressive candidate:

```text
Same OR trigger, scale to 25%.
```

This improves recent windows more, but has a larger full-sample annual-return give-up, so it remains a tactical candidate rather than the first default.

## Ridge Check

CSI2000 alone is not a one-point fit. The dense ridge scan found two useful regions:

- Fast ridge: MA13..30 with 2..4 consecutive below-average days.
- Slow ridge: MA50..60 with roughly 6..15 consecutive below-average days.

`MA20 / 3 days` sits inside the fast ridge. It is not an isolated optimum.

## Negative Results

- Shanghai Composite volume was worse than CSI2000/ChiNext for this strategy. It is still useful for display, but not the best Sub-A overlay trigger.
- Held-ETF volume did not produce robust candidates. It was too local and gave up too much return.
- `CSI2000 AND ChiNext` was weaker than `OR`; waiting for both legs to contract delayed the defensive action.

## Durable Outputs

- `summary.md`: top-level volume study.
- `zz2000_ridge_scan/summary.md`: CSI2000 parameter ridge scan.
- `zz2000_cyb_combo/summary.md`: CSI2000 + ChiNext combined overlay scan.
- `zz2000_cyb_combo/zz2000_cyb_combo_scan.csv`: full combo results.

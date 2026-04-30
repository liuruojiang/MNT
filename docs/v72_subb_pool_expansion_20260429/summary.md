# V7.2 Sub-B Pool Expansion Scan

Date: 2026-04-29

Scope: research only. No production strategy file changed.

## Correction

The first version of this note treated `QQQM`, `GLDM`, and `PDBC` as new pool-expansion candidates. That was wrong.

In the production script, those are already the live trading ETFs for the historical proxies `QQQ`, `GLD`, and `DBC`:
- `QQQM -> QQQ`
- `GLDM -> GLD`
- `PDBC -> DBC`

Therefore any rows that add `QQQM`, `GLDM`, or `PDBC` as separate ranking candidates are invalid and should not be used. The corrected direct test requested after review is the `SPY` check below, because `SPY` is currently used for VolReg but is not part of `US_ROT_POOL`.

Baseline:
- Strategy file: `mnt_bot V 7.1 plus.py`
- Sub-B official pool: QQQ, EMXC, EFA, GLD, TLT, DBC, BTC-USD, with BIL cash fallback.
- Rules preserved: 130/260/390 day momentum mix, top 3 selection, 4% absolute momentum gate, 1.05x challenger protection, inverse-vol weighting, target-vol scaling, 0.1% commission, and SPY VolReg overlay.
- V7.2 composition used for portfolio check: Sub-A 10%, Sub-A-DK 15%, Sub-B 60%, Microcap 15%.
- Common sample: 2015-10-13 to 2026-04-17.

## Method

Each test adds only one candidate to the Sub-B ranking pool, then reruns the official Sub-B engine. This avoids mixing too many new assets at once and keeps attribution interpretable.

A-share candidates are tested as local CNY index proxies reindexed to the U.S. calendar. They do not include FX conversion, U.S.-listed ETF tracking error, A-share execution constraints, price-limit behavior, or T+1 sell constraints. Treat them as candidate-direction screens, not live-tradable Sub-B results.

## Main Read

| Candidate | Category | Full Sub-B dAnnual | Full Sub-B dSharpe | Full Sub-B dMaxDD | Latest 3Y Sub-B dAnnual | Latest 3Y Sub-B dSharpe | 2022 shock Sub-B dAnnual | 2022 shock Sub-B dSharpe |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| DBMF | CTA / managed futures | +0.47% | +0.026 | +1.39% | -0.07% | +0.010 | +10.45% | +0.698 |
| VGIT | intermediate Treasury | -0.37% | -0.015 | 0.00% | -0.54% | -0.021 | 0.00% | 0.000 |
| CN_STAR50 | A-share STAR proxy | -1.43% | -0.038 | +0.05% | -0.64% | +0.014 | +0.23% | -0.009 |
| CN_CHINEXT | A-share ChiNext proxy | -1.03% | -0.073 | -5.68% | +2.79% | +0.110 | -2.27% | -0.154 |
| SPY | U.S. broad equity | -2.06% | -0.086 | -1.00% | -3.13% | -0.086 | -0.34% | -0.059 |
| VTI | U.S. broad equity | -2.45% | -0.102 | -0.74% | -3.27% | -0.097 | -0.77% | -0.090 |
| CN_CSI300 | A-share CSI 300 proxy | -2.64% | -0.104 | -0.11% | -2.45% | -0.047 | -0.18% | -0.012 |
| CN_CSI500 | A-share CSI 500 proxy | -2.75% | -0.123 | -0.92% | -2.26% | -0.064 | -3.58% | -0.286 |
| CN_CSI1000 | A-share CSI 1000 proxy | -2.96% | -0.137 | -5.19% | -0.62% | +0.010 | -4.64% | -0.381 |

`dMaxDD` is variant max drawdown minus baseline max drawdown. Positive means shallower drawdown; negative means worse drawdown.

## Candidate Weight Usage

| Candidate | Full avg weight | Full max weight | Full active days >1% |
|---|---:|---:|---:|
| DBMF | 5.24% | 51.03% | 23.52% |
| VGIT | 1.50% | 60.72% | 5.29% |
| CN_CHINEXT | 8.07% | 47.09% | 44.53% |
| CN_STAR50 | 8.52% | 58.48% | 38.10% |
| VTI | 12.47% | 61.28% | 49.04% |
| SPY | 12.06% | 63.58% | 49.40% |

High usage is not automatically good. SPY/VTI mostly duplicate broad U.S. equity beta already represented by QQQ and tend to displace stronger existing exposures.

## Conclusions

1. DBMF is the only tested candidate that passes the first screen for direct Sub-B pool expansion.
   It improves full-sample Sub-B annual return, Sharpe, and drawdown, and it clearly helps the 2022 inflation shock window. The live-era benefit is small, so it should remain a research candidate rather than an immediate production default.

2. CTA should be tested as a class, not only as DBMF.
   The next real test should add current managed-futures ETFs with local histories, especially CTA, KMLM, FMF, and WTMF. These products can behave very differently, so using one ETF as the whole class is too narrow.

3. A-share index exposure is not ready for direct Sub-B inclusion.
   ChiNext looks good in the latest 3Y window, but full-sample Sub-B annual, Sharpe, and drawdown are worse. Also, the current test is a CNY index proxy, not a U.S.-tradable ETF or China execution model. If A-shares are pursued, use a separate A-share sleeve or test live instruments such as KBA/CNYA/ASHR equivalents with FX and tracking-error handling.

4. SPY should not be added to Sub-B's ranking pool.
   Exact original-engine retest gives full-sample Sub-B annual 24.80% -> 22.75%, Sharpe 1.24 -> 1.16, and MaxDD -15.80% -> -16.80%. It is selected often enough to matter, with a full-sample average weight of 12.06%, and mostly displaces QQQ, GLD, EMXC, and EFA.

5. Broad U.S. equity duplicates should not be added.
   SPY and VTI worsen the pool because Sub-B already has QQQ and other risk assets. They mainly cannibalize the existing winners.

## Recommended Next Step

Build a dedicated CTA class scan after adding real price history for `CTA`, `KMLM`, `FMF`, and `WTMF`, then test:
- one-at-a-time inclusion;
- managed-futures basket inclusion;
- regime-gated inclusion only during inflation/growth-stress windows;
- Sub-B-only metrics first, then V7.2 portfolio metrics.

Files:
- `subb_pool_candidate_window_metrics.csv`
- `subb_pool_candidate_weight_summary.csv`
- `meta.json`

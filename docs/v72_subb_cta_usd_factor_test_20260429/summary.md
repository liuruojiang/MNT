# V7.2 Sub-B CTA, USD, Low-Vol and Quality Candidate Test

Date: 2026-04-29

Scope: research only. No production strategy file changed.

## Setup

- Strategy file: `mnt_bot V 7.1 plus.py`
- Engine: `run_us_rotation_mix(...)` plus `apply_vol_regime_overlay(...)`
- Baseline Sub-B pool: `QQQ, EMXC, EFA, GLD, TLT, DBC, BTC-USD`, with `BIL` cash fallback.
- Rules preserved: 130/260/390 day momentum mix, top 3 selection, 4% absolute momentum gate, 1.05x challenger protection, inverse-vol weighting, target-vol scaling, 0.1% commission, and SPY VolReg overlay.
- Baseline sample: 2015-10-13 to 2026-04-17, rows=3840.
- Candidate data: `DBMF` from local `mnt_strategy_data_us.csv`; all other candidates from `mnt.fetch_yahoo(...)` adjusted close.

## Candidates

| Group | Candidates |
|---|---|
| CTA / managed futures | `DBMF`, `KMLM`, `CTA`, `WTMF`, `FMF` |
| USD trend / dollar index | `UUP`, `UDN` |
| Low-vol / quality | `USMV`, `SPLV`, `QUAL`, `SPHQ` |

Both one-at-a-time and group-all tests were run. One-at-a-time asks whether the single instrument deserves to enter the pool; group-all asks whether the category still works when all peers compete with each other.

## Full Sample: One-at-a-Time

| Candidate | Group | dAnnual | dSharpe | dMaxDD | Variant Annual | Variant Sharpe | Variant MaxDD | Avg Weight |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `UUP` | USD | +0.01% | +0.038 | +3.91% | 24.81% | 1.28 | -11.89% | 8.69% |
| `DBMF` | CTA | +0.47% | +0.026 | +1.39% | 25.27% | 1.27 | -14.40% | 5.24% |
| `FMF` | CTA | -0.18% | -0.004 | +0.94% | 24.62% | 1.24 | -14.86% | 2.94% |
| `UDN` | USD | -0.25% | -0.010 | -0.21% | 24.55% | 1.23 | -16.01% | 0.56% |
| `WTMF` | CTA | -0.50% | -0.012 | -0.14% | 24.30% | 1.23 | -15.94% | 1.96% |
| `KMLM` | CTA | -0.12% | -0.013 | +1.39% | 24.69% | 1.23 | -14.40% | 3.65% |
| `USMV` | Low-vol | -1.11% | -0.019 | +0.93% | 23.69% | 1.22 | -14.86% | 9.20% |
| `CTA` | CTA | -0.73% | -0.021 | -1.20% | 24.08% | 1.22 | -17.00% | 3.19% |
| `SPLV` | Low-vol | -1.37% | -0.026 | -0.82% | 23.44% | 1.22 | -16.62% | 9.29% |
| `SPHQ` | Quality | -1.84% | -0.065 | -0.05% | 22.97% | 1.18 | -15.85% | 13.83% |
| `QUAL` | Quality | -2.27% | -0.093 | -1.04% | 22.53% | 1.15 | -16.84% | 12.72% |

`dMaxDD` is variant max drawdown minus baseline max drawdown. Positive means shallower drawdown; negative means worse drawdown.

## Full Sample: Group-All

| Scenario | Tickers | dAnnual | dSharpe | dMaxDD | Variant Annual | Variant Sharpe | Variant MaxDD |
|---|---|---:|---:|---:|---:|---:|---:|
| `USD_ALL` | `UUP,UDN` | -0.24% | +0.027 | +3.91% | 24.56% | 1.27 | -11.89% |
| `CTA_ALL` | `DBMF,KMLM,CTA,WTMF,FMF` | -0.50% | -0.024 | -0.97% | 24.31% | 1.22 | -16.77% |
| `LowVolQuality_ALL` | `USMV,SPLV,QUAL,SPHQ` | -3.08% | -0.098 | -3.16% | 21.72% | 1.14 | -18.96% |

## 2022 Inflation Shock

| Candidate | dAnnual | dSharpe | dMaxDD |
|---|---:|---:|---:|
| `DBMF` | +10.45% | +0.698 | +5.34% |
| `KMLM` | +8.95% | +0.552 | +2.31% |
| `UUP` | +6.02% | +0.442 | +8.01% |
| `FMF` | +2.94% | +0.199 | +2.37% |
| `CTA_ALL` | +18.87% | +1.013 | +2.12% |
| `USD_ALL` | +6.02% | +0.442 | +8.01% |

## Recent 3Y Check

| Candidate | dAnnual | dSharpe | dMaxDD |
|---|---:|---:|---:|
| `SPHQ` | -0.78% | +0.012 | +0.00% |
| `QUAL` | -0.40% | +0.011 | +0.00% |
| `DBMF` | -0.07% | +0.010 | -0.66% |
| `FMF` | -0.45% | -0.009 | +0.00% |
| `WTMF` | -1.10% | -0.019 | +0.02% |
| `CTA` | -1.60% | -0.022 | +0.41% |
| `KMLM` | -1.60% | -0.045 | +0.00% |
| `UUP` | -3.02% | -0.079 | -0.19% |

## Interpretation

1. `UUP` is worth a second-stage test.
   It is the best full-sample single candidate by Sharpe improvement and drawdown reduction. It does not add much annual return, and it is weak in the latest 3Y window, but it clearly helped the 2022 shock. This looks like a useful macro-defense candidate, not a clear always-on default.

2. `DBMF` remains the best single CTA candidate.
   It improves full-sample annual return, Sharpe, and MaxDD, and it was strong in 2022. `KMLM` also helped 2022 materially, but full sample was slightly worse than baseline. `FMF` is mild; `CTA` and `WTMF` do not pass as single additions.

3. The full CTA basket is not automatically better.
   `CTA_ALL` is excellent in 2022, but full-sample annual, Sharpe, and drawdown are worse than baseline. If CTA is adopted, start with `DBMF` or a constrained `DBMF/KMLM` test rather than blindly adding all managed-futures ETFs to the ranking pool.

4. Low-vol and quality factors do not belong in the Sub-B pool.
   `QUAL/SPHQ` look slightly better in the latest 3Y Sharpe check, but the full-sample result is worse. They are equity-beta substitutes and mostly displace `QQQ/GLD/EMXC/EFA` without adding a clean new macro factor.

5. Best next research direction:
   test `UUP`, `DBMF`, `KMLM`, and a small `DBMF+KMLM+UUP` macro-defense candidate set. Also test a regime-gated version where these candidates are only eligible during inflation/rates/credit stress, because latest-3Y drag is the main concern.

## Files

- `metrics.csv`
- `weight_usage.csv`
- `full_sample_weight_displacement.csv`
- `latest_variant_weights.csv`
- `meta.json`

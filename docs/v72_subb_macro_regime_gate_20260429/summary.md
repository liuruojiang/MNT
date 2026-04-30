# V7.2 Sub-B Macro Regime Gate Test

Date: 2026-04-29

Scope: research only. No production strategy file changed.

## Rules Tested

Macro candidates: `UUP`, `DBMF`, `KMLM`.

Baseline Sub-B pool stays unchanged:
`QQQ, EMXC, EFA, GLD, TLT, DBC, BTC-USD`, with `BIL` cash fallback.

Candidate eligibility rules:

| Rule | Definition |
|---|---|
| `always_allow_uup_dbmf_kmlm` | `UUP/DBMF/KMLM` always participate in Sub-B ranking. |
| `inflation_pressure_only` | Candidates participate only when `DBC 126d momentum > 0` and `TLT 126d momentum < 0`. |
| `credit_stress_only` | Candidates participate only when lagged HY OAS is above trailing 252d mean + 1 std, or lagged HY OAS 63d change is >= 1.0 percentage point. |
| `inflation_or_credit` | Candidates participate when either inflation pressure or credit stress is on. |
| `inflation_and_credit` | Candidates participate only when both are on. |

Credit data uses FRED `BAMLH0A0HYM2`, lagged by one trading day to avoid same-day availability ambiguity.

## Backtest Results

Sample: 2015-10-13 to 2026-04-17.

### Full Sample

| Scenario | Annual | Sharpe | MaxDD | dAnnual | dSharpe | dMaxDD |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 24.80% | 1.24 | -15.80% | 0.00% | 0.000 | 0.00% |
| always allow | 25.07% | 1.26 | -14.75% | +0.27% | +0.020 | +1.05% |
| inflation only | 25.56% | 1.28 | -14.40% | +0.76% | +0.036 | +1.39% |
| credit only | 24.72% | 1.24 | -15.80% | -0.08% | -0.003 | 0.00% |
| inflation or credit | 25.55% | 1.28 | -14.40% | +0.75% | +0.035 | +1.39% |
| inflation and credit | 24.73% | 1.24 | -15.80% | -0.07% | -0.002 | 0.00% |

### Latest 3Y

| Scenario | Annual | Sharpe | MaxDD | dAnnual | dSharpe | dMaxDD |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 36.46% | 1.52 | -11.70% | 0.00% | 0.000 | 0.00% |
| always allow | 33.59% | 1.45 | -12.36% | -2.87% | -0.066 | -0.66% |
| inflation only | 35.05% | 1.50 | -12.21% | -1.41% | -0.023 | -0.51% |
| credit only | 36.16% | 1.51 | -11.75% | -0.31% | -0.010 | -0.05% |
| inflation or credit | 35.02% | 1.49 | -12.21% | -1.44% | -0.027 | -0.51% |
| inflation and credit | 36.19% | 1.51 | -11.75% | -0.27% | -0.007 | -0.05% |

### 2022 Inflation Shock

| Scenario | Annual | Sharpe | MaxDD | dAnnual | dSharpe | dMaxDD |
|---|---:|---:|---:|---:|---:|---:|
| baseline | -4.10% | -0.22 | -14.51% | 0.00% | 0.000 | 0.00% |
| always allow | 13.67% | 0.76 | -11.98% | +17.77% | +0.973 | +2.53% |
| inflation only | 8.92% | 0.57 | -10.58% | +13.02% | +0.792 | +3.93% |
| credit only | -4.10% | -0.22 | -14.51% | 0.00% | 0.000 | 0.00% |
| inflation or credit | 8.92% | 0.57 | -10.58% | +13.02% | +0.792 | +3.93% |
| inflation and credit | -4.10% | -0.22 | -14.51% | 0.00% | 0.000 | 0.00% |

## Current Regime Snapshot

As of market data date: 2026-04-29.

Current market data for `DBC/TLT/UUP/SPY` was refreshed with `mnt.fetch_yahoo(...)` instead of the local CSV, because the local base file ended at 2026-04-17.

| Signal | Current value | Trigger |
|---|---:|---|
| `DBC` 126d momentum | +40.09% | commodity leg ON |
| `TLT` 126d momentum | -4.44% | long-bond weakness leg ON |
| Inflation pressure | ON | both legs satisfied |
| `UUP` 126d momentum | +2.25% | context only |
| HY OAS lagged value | 2.85 | below stress threshold |
| HY OAS 252d mean + 1 std | 3.20 | threshold |
| HY OAS 63d change | +0.14 pct point | below +1.0 trigger |
| Credit stress | OFF | no credit trigger |
| CPI YoY, latest monthly | 3.32% | context only, March 2026 |

Interpretation: the market-based inflation-pressure warning is currently ON, while credit stress is OFF. Under the tested `inflation_pressure_only` rule, `UUP/DBMF/KMLM` would be eligible to participate in Sub-B ranking now.

## Conclusion

The useful gate is `inflation_pressure_only`, not the credit-stress gate as currently parameterized.

`inflation_pressure_only` improved full-sample annual return, Sharpe, and MaxDD, and it preserved most of the 2022 shock protection while reducing the latest-3Y drag versus always allowing `UUP/DBMF/KMLM`.

The rule is still not a clean production default because latest-3Y remains weaker than baseline. The next test should tune the trigger threshold, especially:
- require `DBC 126d momentum > 5%` or `>10%`;
- require `TLT 126d momentum < -2%` or `< -5%`;
- test a cooldown/hold period so the candidates do not flicker around the boundary.

## Files

- `scenario_metrics.csv`
- `candidate_weight_usage.csv`
- `regime_eligible_summary.csv`
- `regime_daily.csv`
- `current_regime_snapshot.json`
- `meta.json`

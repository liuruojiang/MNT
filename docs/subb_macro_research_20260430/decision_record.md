# Sub-B Volume and Macro Overlay Decision Record

Date: 2026-04-30

## Scope

This records the Sub-B follow-up research after the DK volume study. The goal was to see whether the V7.2 Sub-B sleeve can be improved through daily volume, market-risk, credit, dollar/rates, or stress-period candidate-pool rules.

The tested baseline is the current local `mnt_bot V 7.2 plus.py` Sub-B implementation:

- `run_us_rotation_mix`;
- base ranking pool `QQQ / EMXC / EFA / GLD / TLT / DBC / BTC-USD`;
- inflation-gated macro candidates through `_subb_active_ranking_codes`;
- SPY volatility-regime overlay through `apply_vol_regime_overlay`;
- local price source `mnt_strategy_data_us.csv`, sample `2004-07-23` to `2026-04-17`.

Yahoo Finance data was used only for external daily volume and macro-risk series, cached inside the relevant docs folders.

## Execution Assumptions

- No-lookahead timing: T-day external signal is only allowed to affect the next Sub-B trading day.
- The existing Sub-B cost model is retained. Whole-sleeve external scaling pays `US_ROT_COMMISSION * risky_gross_weight * abs(delta_scale)`.
- All comparisons are against the same V7.2 Sub-B baseline daily return series.

## Results

### 1. Plain Volume Overlay

Output folder: `docs/subb_volume_effect_20260430/`

Tested families:

- broad ETF amount signals on `SPY / QQQ / IWM / DIA`;
- currently held proxy ETF volume weakness;
- MA windows `10 / 20 / 30 / 50 / 60`;
- consecutive-day grid `2 / 3 / 5 / 8 / 10 / 15`;
- exposure scale `0 / 0.25 / 0.5 / 0.75`.

Result: no robust candidate after excluding zero-trigger or near-zero-effect rules.

Best weak examples:

| Rule | Trigger days | Full annual delta | 10Y annual delta | 5Y annual delta | 3Y annual delta |
|---|---:|---:|---:|---:|---:|
| DIA amount < MA30 for 15 days, scale 0.50 | 125 | -0.04pp | +0.10pp | -0.13pp | +0.28pp |
| DIA amount > MA10 for 8 days, scale 0.50 | 63 | -0.03pp | -0.11pp | +0.05pp | +0.42pp |
| Held proxy amount < MA30 for 15 days, scale 0.00 | 37 | +0.11pp | +0.00pp | +0.00pp | +0.00pp |

Decision: do not add a Sub-B daily volume filter.

### 2. Macro Risk Whole-Sleeve Scaling

Output folder: `docs/subb_macro_risk_overlays_20260430/`

Tested sources:

- VIX absolute and relative thresholds;
- HYG/LQD credit ratio below moving average and credit momentum;
- UUP above moving average;
- TLT below moving average;
- QQQ/SPY relative trend;
- VIX plus credit combinations.

Result: no robust candidate. The best group was credit momentum with scale `0.75`, but the best score was still negative and the 10Y annual delta was negative. VIX gates sometimes improved isolated drawdown behavior, but generally gave up too much return and Sharpe.

Decision: do not add a whole-sleeve Sub-B macro risk scaling overlay.

### 3. Stress-Period Pool Deletion

Output folder: `docs/subb_macro_pool_filters_20260430/`

Tested stress definitions:

- `vix_gt25`, `vix_gt30`;
- `credit_below_ma100_d3`, `credit_below_ma100_d5`;
- `combo_vix25_or_credit_d3`;
- `growth_underperform_ma100_d5`.

Tested deletion modes:

- remove BTC;
- remove QQQ and BTC;
- remove equities and BTC;
- defensive-only core;
- defensive plus QQQ.

Result: no robust candidate. The least harmful rule was `vix_gt30:no_btc`, but it still reduced annual return across full and recent windows.

Decision: do not delete growth/BTC/equity candidates during stress by default.

### 4. Stress-Period Candidate Expansion

Output folder: `docs/subb_macro_candidate_expansion_20260430/`

Tested adding `DBMF`, `DBMF + TLT`, or `DBMF + GLD` during the same stress definitions instead of reducing exposure or deleting candidates.

Best result:

| Rule | Stress days | Full annual delta | 10Y annual delta | 5Y annual delta | 3Y annual delta | Drawdown change |
|---|---:|---:|---:|---:|---:|---:|
| credit_below_ma100_d5:add_dbmf | 1551 | +0.01pp | +0.01pp | +0.18pp | +0.31pp | near 0 |

This passes a loose non-negative robustness filter but fails the material-effect threshold. The improvement is directionally useful but too small to justify a default logic change.

Decision: keep credit-stress DBMF expansion as a research reference only, not a V7.2 default rule.

## Interpretation

Sub-B behaves differently from the A-share sleeves. Daily ETF volume is not giving a wide ridge here. The more useful information for US ETF rotation appears to already be represented by:

- cross-asset momentum among growth, international, gold, bonds, commodities, BTC, and cash;
- inverse-vol weighting;
- 25% target-vol scaling;
- SPY VolReg overlay;
- inflation-gated macro candidates.

The most important negative result is that aggressive de-risking rules are mostly subtractive. The most interesting positive clue is not "turn Sub-B down in stress", but "allow a diversifying trend-follower such as DBMF under credit stress". On the current data this is too small to promote.

## Current Decision

No Sub-B production change from this research pass.

Keep the tested artifacts for reference:

- `docs/subb_volume_effect_20260430/decision_record.md`
- `docs/subb_macro_risk_overlays_20260430/summary.md`
- `docs/subb_macro_pool_filters_20260430/summary.md`
- `docs/subb_macro_candidate_expansion_20260430/summary.md`

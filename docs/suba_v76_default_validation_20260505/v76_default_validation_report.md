# Sub-A V7.6 Default Validation

- Target: verify V7.6 default Sub-A parameters equal the selected `balanced` finalist.
- Baseline: `docs/suba_finalist_robustness_20260505/daily_returns.csv`, `balanced`, cost x1.

## Default Parameters

- `CN_BIAS_N`: `60`
- `CN_MOM_DAY`: `20`
- `CN_R2_WINDOW`: `20`
- `CN_R2_THRESHOLD`: `0.2`
- `CN_SWITCH_BUFFER`: `1.03`
- `CN_ENTRY_INITIAL_FRACTION`: `0.5`
- `CN_ENTRY_WAIT_DAYS`: `None`
- `CN_TARGET_VOL`: `0.3`
- `CN_VOL_WINDOW`: `80`
- `CN_SCALE_THRESHOLD`: `0.0`
- `CN_COMMISSION`: `0.001`
- `CN_SA_CASH_OVERLAY_ENABLED`: `True`
- `CN_SA_SAME_SIDE_OVERHEAT_ENABLED`: `True`
- `CN_SA_VOLUME_OVERLAY_ENABLED`: `True`

## Segment Metrics

| segment | start | end | rows | CAGR | MaxDD | Sharpe | Calmar | avg weight | avg turnover |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| last_1y | 2025-05-06 | 2026-04-30 | 242 | 100.60% | -7.18% | 3.537 | 14.007 | 0.745 | 0.180 |
| last_3y | 2023-05-04 | 2026-04-30 | 726 | 44.24% | -12.79% | 1.958 | 3.459 | 0.650 | 0.194 |
| last_5y | 2021-05-06 | 2026-04-30 | 1210 | 33.76% | -17.72% | 1.642 | 1.906 | 0.746 | 0.219 |
| last_10y | 2016-05-04 | 2026-04-30 | 2428 | 29.24% | -19.85% | 1.426 | 1.474 | 0.762 | 0.238 |

## Daily Parity

| column | rows | max abs diff | mean abs diff | nonzero > 1e-12 |
|---|---:|---:|---:|---:|
| return | 3785 | 9.97465998687e-17 | 3.85876473328e-17 | 0 |
| nav | 3785 | 7.1054273576e-15 | 2.72701280315e-16 | 0 |
| weight | 3785 | 2.22044604925e-16 | 2.69856058826e-18 | 0 |
| holding_fraction | 3785 | 0 | 0 | 0 |
| effective_turnover | 3785 | 4.4408920985e-16 | 3.6964656566e-18 | 0 |
| trade_cost | 3785 | 9.97465998687e-17 | 1.96684704879e-18 | 0 |

## Audit

- Script: `mnt_bot V 7.6 plus.py`
- Entry path: `fetch_cn_kline() / _add_cn_bond_column() / run_cn_strategy() plus formal Sub-A overlays`
- Data: `2010-06-01` -> `2026-04-30`, rows `3865`, duplicate dates `0`
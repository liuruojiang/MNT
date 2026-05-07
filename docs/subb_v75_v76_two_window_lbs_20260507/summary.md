# Sub-B Two-Window Lookback Test - 2026-05-07

## Scope

- Production scripts: `mnt_bot V 7.5 plus.py`, `mnt_bot V 7.6 plus.py`.
- Test path: runtime override of `US_ROT_LBS` only; production source files were not changed.
- Official Sub-B path: `run_us_rotation_mix()` official macro-gated leg, cached EMA leg, `blend_subb_v75_results()`, then current VolReg.
- Execution and costs: T close signal -> T+1 adjusted open execution; `US_ROT_COMMISSION = 0.001`.
- Candidate grid: two-window `(mid, long)` with `mid = 180/200/210/220/240/260`, `long = 360/390/420`.
- References: current default and three-window `(180, 240, 390)`.

## Main Result

The two-window structure works, but it does not beat the best three-window candidate. The best two-window point is `(180, 390)`.

| Version | Candidate | Recent weighted Sharpe | Mean recent CAGR | Worst recent MaxDD | 10Y CAGR | 10Y MaxDD | 10Y Sharpe |
|---|---|---:|---:|---:|---:|---:|---:|
| V7.5 | three `(180,240,390)` | 2.063 | 42.29% | -13.90% | 33.45% | -13.90% | 1.937 |
| V7.5 | two `(180,390)` | 2.039 | 41.73% | -14.80% | 33.46% | -14.80% | 1.941 |
| V7.5 | current default | 1.901 | 39.12% | -13.87% | 30.94% | -13.87% | 1.811 |
| V7.6 | three `(180,240,390)` | 1.990 | 41.65% | -12.05% | 32.80% | -12.05% | 1.849 |
| V7.6 | two `(180,390)` | 1.982 | 41.38% | -12.07% | 32.81% | -12.07% | 1.854 |
| V7.6 | current default | 1.964 | 41.19% | -12.11% | 32.27% | -12.11% | 1.825 |

## Interpretation

- `(180,390)` is a valid two-window simplification: it stays very close to `(180,240,390)`, especially in V7.6.
- In V7.6, `(180,390)` has slightly higher 10Y CAGR and 10Y Sharpe than `(180,240,390)`, but lower recent weighted Sharpe.
- In V7.5, `(180,390)` keeps 10Y CAGR and Sharpe close, but its worst recent drawdown is about 0.9 percentage point deeper than `(180,240,390)`.
- The middle cluster is not centered at 240 if forced into two windows. The best simplification chooses the faster middle point `180`, not `210/220/240`.
- Candidates such as `(220,390)` and `(210,390)` are acceptable but weaker; `(240,390)` and `(260,390)` lose too much recent weighted Sharpe.

## Decision View

- If the objective is maximum robustness with no need to reduce parameter count: keep three-window `(180,240,390)`.
- If the objective is simpler production semantics: two-window `(180,390)` is defensible.
- Do not promote `(240,390)` just because `180-240` looked like one broad region. In this actual two-window run, the best representative of that region is `180`.

## Files

- `summary.csv`: segment metrics for all candidates.
- `rank.csv`: recent weighted ranking by version.
- `v75_v76_compare.csv`: cross-version comparison by `lbs`.
- `daily_returns.csv`: daily Sub-B return streams for each candidate.
- `yearly_returns.csv`: yearly return table.
- `audit.json`: data path, candidate grid, and run metadata.

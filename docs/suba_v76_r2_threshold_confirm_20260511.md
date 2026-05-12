# V7.6 Sub-A CN_R2_THRESHOLD Confirmation - 2026-05-11

## Decision

`CN_R2_THRESHOLD` is promoted from `0.20` to `0.25` for `mnt_bot V 7.6 plus.py`.

`CN_R2_WINDOW` remains `20`.

## Source And Data

- Official entrypoint: `mnt_bot V 7.6 plus.py`
- Formal path: `_add_cn_bond_column()` -> `run_cn_strategy()` -> cash overlay -> same-side overheat overlay -> volume overlay
- Data range: `2010-06-01` to `2026-05-11`
- Official commission: `0.001`
- Financing annual rate: `0.03`
- Trading days: `244`
- Target vol / vol window / leverage bounds: `0.30 / 80 / 1.5 max / 0.1 min`
- Incremental impact stress: `impact_bps * effective_turnover / 10000`, applied after official costs as diagnostic stress only

## Scan Grid

- Fixed `CN_R2_WINDOW=20`
- Tested thresholds: `0.20`, `0.225`, `0.25`, `0.275`, `0.30`
- Source-change rule during scan: runtime override only, no production source edits

## Full-Sample Official-Cost Results

| `CN_R2_THRESHOLD` | full annual | full maxDD | 10Y annual | 5Y annual | 3Y annual | 1Y annual |
|---:|---:|---:|---:|---:|---:|---:|
| 0.200 | 34.59% | -29.79% | 34.90% | 39.45% | 53.06% | 126.10% |
| 0.225 | 35.19% | -30.10% | 34.34% | 39.76% | 53.92% | 125.92% |
| 0.250 | 36.24% | -29.41% | 34.47% | 40.00% | 54.58% | 125.45% |
| 0.275 | 34.62% | -29.41% | 33.26% | 39.24% | 51.87% | 125.45% |
| 0.300 | 34.26% | -29.11% | 32.64% | 38.19% | 49.83% | 118.29% |

## Impact Sensitivity

| extra impact bps | threshold | full annual | full maxDD | Sharpe |
|---:|---:|---:|---:|---:|
| 0 | 0.200 | 34.59% | -29.79% | 1.60 |
| 0 | 0.225 | 35.19% | -30.10% | 1.64 |
| 0 | 0.250 | 36.24% | -29.41% | 1.71 |
| 0 | 0.275 | 34.62% | -29.41% | 1.64 |
| 0 | 0.300 | 34.26% | -29.11% | 1.63 |
| 5 | 0.200 | 30.72% | -30.95% | 1.42 |
| 5 | 0.225 | 31.38% | -31.27% | 1.46 |
| 5 | 0.250 | 32.46% | -30.66% | 1.53 |
| 5 | 0.275 | 30.94% | -30.66% | 1.47 |
| 5 | 0.300 | 30.65% | -30.34% | 1.46 |
| 10 | 0.200 | 26.97% | -34.01% | 1.24 |
| 10 | 0.225 | 27.67% | -35.28% | 1.28 |
| 10 | 0.250 | 28.78% | -33.18% | 1.35 |
| 10 | 0.275 | 27.36% | -33.59% | 1.29 |
| 10 | 0.300 | 27.13% | -31.54% | 1.29 |

## Interpretation

`0.25` is the strongest local candidate by full-sample annual return and Sharpe, and it remains first under 5 bps and 10 bps incremental turnover-impact stress. The useful plateau is narrow around `0.225-0.275`; `0.30` weakens the 10Y/5Y/3Y/1Y return profile.

The caveat is unchanged from the scan record: `0.20` still has the best 10Y annual return, so this is a return/Sharpe promotion with a recent-window tradeoff, not a free improvement.

## Verification

- `python run_v76_suba_r2_threshold_confirm_scan.py`
- `python C:\Users\Administrator.DESKTOP-95I7VVU\.codex\skills\quant-param-scan\scripts\finalize_quant_param_scan_run.py quant_param_scan_runs\20260511_v76_suba_cn_r2_threshold_confirm --decision candidate_confirmed_watchlist --stability-label threshold_0p25_local_preferred`
- `python C:\Users\Administrator.DESKTOP-95I7VVU\.codex\skills\quant-param-scan\scripts\check_quant_param_scan_artifacts.py --phase complete --strict quant_param_scan_runs\20260511_v76_suba_cn_r2_threshold_confirm`
- `python -m unittest discover -s tests -p 'test_v76_suba_r2_threshold_default.py' -v`


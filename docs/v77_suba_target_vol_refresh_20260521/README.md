# V7.7 Sub-A Target-Vol Refresh - 2026-05-21

## Scope

This record preserves the current-code scan for Strategy A / Sub-A target volatility.

The scan used the current `mnt_bot V 7.7 plus.py` Sub-A path:

- `run_cn_strategy()`
- MA60 same-side overheat take-profit overlay: enabled, `27% / 24%`, derisk scale `0`
- Sub-A volume overlay: enabled and required to be resolved
- Cash peak-decay overlay: disabled in the current V7.7 constants

No production strategy constants were changed.

## Data And Cost Assumptions

- Data mode: free fetchers with local cache.
- CN close window: `2010-06-01` to `2026-05-20`.
- CN close rows after alignment: `3876`.
- Volume feature window: `2000-01-01` to `2026-05-20`.
- Cost model: current `CN_COMMISSION=0.001`, current `CN_RF_ANNUAL=3%`.
- Execution timing: close-derived signal and overlay state affect the next close-to-close exposure segment.
- Slippage/open impact: not separately modeled.
- Fixed sizing settings in the main scan: `CN_VOL_WINDOW=80`, `CN_MAX_LEV=1.5`, `CN_SCALE_THRESHOLD=0`.

## Main Decision

Measured grid winner: `CN_TARGET_VOL=22.5%`.

Practical production band: `20%` to `25%`.

- `22.5%` had the best recent-window weighted Sharpe in this current-code scan.
- `20%` is the cleaner lower-cap-hit setting.
- `25%` has higher 10Y annualized return with nearly the same 10Y drawdown as `22.5%`.
- Current `30%` should be treated as the aggressive capped-leverage default, not as a clean volatility target.

## Key Rows

Annualized return / max drawdown:

| Target vol | 15Y | 10Y | 5Y | 3Y | 1Y |
|---:|---:|---:|---:|---:|---:|
| 20.0% | 33.34% / -22.13% | 34.16% / -21.45% | 47.78% / -16.49% | 66.37% / -7.87% | 116.82% / -7.87% |
| 22.5% | 35.29% / -23.43% | 35.91% / -21.69% | 49.79% / -16.49% | 69.58% / -8.84% | 123.47% / -8.84% |
| 25.0% | 36.96% / -24.52% | 37.38% / -21.69% | 51.33% / -16.49% | 71.98% / -9.80% | 126.30% / -9.80% |
| 30.0% | 38.89% / -25.81% | 38.69% / -21.69% | 52.77% / -16.49% | 74.75% / -10.64% | 127.48% / -10.64% |

Average leverage on holding days:

| Target vol | Full | 15Y | 10Y | 5Y | 3Y | 1Y |
|---:|---:|---:|---:|---:|---:|---:|
| 22.5% | 1.34x | 1.36x | 1.41x | 1.39x | 1.32x | 1.42x |
| 25.0% | 1.39x | 1.40x | 1.43x | 1.42x | 1.34x | 1.45x |
| 30.0% | 1.44x | 1.46x | 1.46x | 1.44x | 1.38x | 1.49x |

10Y cap-hit ratio on holding days:

| Target vol | 10Y cap-hit ratio |
|---:|---:|
| 22.5% | 74.16% |
| 25.0% | 81.58% |
| 30.0% | 91.89% |

## Preserved Files

- `scan_summary.csv`: long-form scan metrics.
- `window_metrics.csv`: wide metrics table for the main target-vol grid.
- `requested_15y_10y_5y_3y_1y_ann_dd.csv`: requested 15Y/10Y/5Y/3Y/1Y annualized return and max drawdown table.
- `requested_225_25_30_avg_leverage.csv`: requested average leverage table for `22.5%`, `25%`, and `30%`.
- `scan_meta.json`: machine-readable audit metadata from the run.

## Cleanup

After this docs archive was created, the temporary run folder under `quant_param_scan_runs/20260521_v77_suba_v7_7_sub_a_target_vol_refresh_20260521/` was removed. The removed folder included the large intermediate `daily_candidate_returns.csv` and the one-off runner script. The preserved docs CSVs are the durable evidence for this pass.

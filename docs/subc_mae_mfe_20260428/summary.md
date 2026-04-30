# Sub-C MAE/MFE segment study - 2026-04-28

## Method

- Script: `analyze_subc_mae_mfe.py`
- Production source file: `mnt_bot V 7.1 plus.py`
- Output directory: `docs/subc_mae_mfe_20260428/`
- Sub-C return path: `_compute_daily_subc_phased()` plus `_apply_subc_vol_scaling()`
- Parity check: reconstructed daily returns must match `_get_subc_daily_ret()` with max absolute difference <= `1e-12`
- Segment definition: a new segment starts when `actual_scale` changes or when the Sub-C asset availability phase changes.
- Phases:
  - `Phase0_pre_DBMF_no_BTC`
  - `Phase1_DBMF_no_BTC`
  - `Phase2_full`

## Window summary

| Window | Segments | Win rate | Avg profit | Avg MFE | Avg MAE | Median capture | Profit-then-loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1Y | 32 | 65.62% | 0.96% | 2.03% | -0.85% | 97.54% | 12.50% |
| 3Y | 62 | 61.29% | 1.12% | 2.47% | -1.01% | 92.01% | 20.97% |
| 5Y | 125 | 53.60% | 0.55% | 1.91% | -1.17% | 91.78% | 27.20% |
| 10Y | 209 | 58.37% | 0.72% | 2.09% | -1.16% | 91.78% | 22.49% |
| Full | 345 | 56.81% | 0.59% | 1.95% | -1.16% | 85.51% | 24.35% |

## Phase split

| Phase | Segments | Win rate | Avg profit | Median profit | Avg MFE | Avg MAE | Median capture | Profit-then-loss | Worst MAE | Max giveback |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Phase0_pre_DBMF_no_BTC | 172 | 56.40% | 0.51% | 0.26% | 1.93% | -1.18% | 79.44% | 26.16% | -9.94% | 12.38% |
| Phase1_DBMF_no_BTC | 59 | 62.71% | 0.95% | 0.81% | 2.21% | -1.02% | 81.97% | 15.25% | -6.35% | 5.84% |
| Phase2_full | 114 | 54.39% | 0.51% | 0.17% | 1.85% | -1.21% | 93.45% | 26.32% | -7.58% | 8.44% |

## Scale split

| Scale bucket | Segments | Win rate | Avg profit | Avg MFE | Avg MAE | Profit-then-loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| <=0.75x | 20 | 65.00% | 0.72% | 1.42% | -1.52% | 30.00% |
| 0.75-1.0x | 52 | 63.46% | 0.41% | 1.39% | -1.11% | 19.23% |
| 1.0-1.25x | 116 | 58.62% | 0.36% | 1.29% | -0.89% | 20.69% |
| 1.25-1.5x | 157 | 52.23% | 0.79% | 2.69% | -1.34% | 28.03% |

## Main read

Sub-C's segment-level behavior is steadier than a weekly rotation sleeve. The full-sample median profit capture is high at 85.51%, and recent windows are above 90%. The main issue is not systematic failure to capture winners, but occasional sharp drawdown/giveback inside scale segments.

The deepest MAE events are concentrated in early pre-DBMF/no-BTC history, but Phase2 still has meaningful stress: the 2022-04-04 to 2022-04-26 full-phase segment lost 7.58% with an 8.44% giveback. Recent 2026 segments are mixed, with the open 2026-04-23 to 2026-04-28 segment at -1.43% as of the output snapshot.

For rule testing, a blunt MAE stop is unlikely to be the first lever because `deep_mae_profit_rate` is 0.00% across all windows in this segmentation. Better follow-up tests are:

- giveback control after a segment has already reached a positive MFE threshold;
- scale-aware de-risking when `actual_scale` is above 1.25x;
- Phase2-specific stress handling, because current live semantics are closer to Phase2 than the long pre-DBMF sample.

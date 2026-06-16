# V7.7 Sub-A Standard Process Review

Generated: 2026-06-14

## Scope

- Objective: Treat V7.7 Sub-A as a new strategy candidate and rerun the standard first-pass test.
- Strategy: `mnt_bot V 7.7 plus.py` Sub-A A-share long rotation.
- Result status: observed by importing the real V7.7 script and executing the Sub-A chain used inside `_run_strategies`.

## Official Path Checked

- Official bot path: `_handle_performance` -> `_cached_fetch_data` -> `_cached_run_strategies` -> `_run_strategies`.
- Sub-A chain executed for this review: `fetch_cn_kline` / `_add_cn_bond_column` -> `run_cn_strategy` -> `apply_suba_same_side_overheat_overlay` -> `_load_suba_volume_signal` -> `_apply_suba_volume_overlay_policy`.
- Cash peak-decay overlay was off; same-side MA60 overheat and Sub-A amount overlay were on.

## Data And Formal Window

| Required item | Code | Role | Publication / availability date | Data source in run | Data range |
|:-|:-|:-|:-|:-|:-|
| CSI Dividend Low Volatility 100 | `1.930955` | price index | 2017-05-26 | `csindex:930955` | 2005-01-01 to 2026-06-12 |
| ChiNext Price Index | `0.399006` | price index and amount overlay leg | 2010-06-01 | `Sina`; amount from `Sohu amount` | 2010-06-01 to 2026-06-12 |
| SSE 50 | `1.000016` | price index | 2004-01-02 | `Sina` | 2004-01-02 to 2026-06-12 |
| CSI 1000 | `1.000852` | price index | 2014-10-17 | `Sina` | 2014-10-17 to 2026-06-12 |
| CSI 500 | `1.000905` | price index | 2007-01-15 | `Sina` | 2005-01-04 to 2026-06-12 |
| SSE 10Y Treasury Total Return | `1.H11077` | bond defensive asset | 2013-03-07 | `fetch_cn_kline` through `_add_cn_bond_column` | 2014-10-17 to 2026-06-12 |
| CSI 2000 amount | `2.932000` | formal Sub-A amount overlay leg | 2023-08-11 | `CSIndex official amount` | feature to 2026-06-12 |

Formal sample starts on `2023-08-11`, the latest required publication date, because V7.7 production Sub-A includes the CSI 2000 amount overlay. Earlier CSI 2000 history is treated as pre-publication backfill and is not used for formal conclusions.

## Mandatory Window Metrics

| Window | Sample used | Annualized return | Max drawdown | Status |
|:-|:-|--:|--:|:-|
| Full formal | 2023-08-11 to 2026-06-12, 685 rows | 66.45% | -11.28% | formal |
| Last 10Y | 2016-06-12 to 2026-06-12 | N/A | N/A | starts before formal sample |
| Last 5Y | 2021-06-12 to 2026-06-12 | N/A | N/A | starts before formal sample |
| Last 3Y | 2023-06-12 to 2026-06-12 | N/A | N/A | starts before formal sample |
| Last 1Y | 2025-06-12 to 2026-06-12, 244 rows | 94.81% | -11.28% | formal |

Diagnostic only: the raw strategy output from 2015-02-10 to 2026-06-12 produced 33.55% annualized return and -24.73% max drawdown, but that window includes pre-publication/backfilled history and must not be used as a formal conclusion.

## Trading Assumptions

- Market: A-share index rotation plus defensive bond index.
- Price mode: Sub-A equity legs use price indexes; bond defensive asset uses `1.H11077` total-return style series.
- Execution timing: close-to-close state machine; amount overlay is observed after close and affects the next close-to-close return segment.
- Cost: `CN_COMMISSION = 0.001` single-side turnover cost.
- Risk modules included: target-vol scaling `30%` target, 80-day vol, max leverage `1.5`; same-side overheat trigger `27%`, recovery `24%`, derisk scale `0`; Sub-A amount OR overlay `ZZ2000 MA20/3d or CYB MA20/4d`, scale `0`.
- Explicitly not modeled beyond existing script: intraday open execution, price-limit executability, suspension fills, and capacity/slippage beyond the configured commission.

## Artifacts

- `v77_suba_daily.csv`: full Sub-A daily result from the executed chain.
- `v77_suba_window_metrics.csv`: mandatory window table plus diagnostic raw-output window.
- `v77_suba_data_availability.csv`: required participant data ranges and sources.
- `v77_suba_metadata.json`: parameters, publication dates, command metadata, and volume overlay freshness.

## Verification

- `python -m py_compile "mnt_bot V 7.7 plus.py"`: exit 0.
- `git diff --check`: exit 0.

## Decision

This run is a strict standard-process first-pass review for V7.7 Sub-A. Under the no-pre-publication-backfill rule, only `2023-08-11` onward is formal because the production amount overlay requires CSI 2000. The long pre-2023 history is retained only as diagnostic context.

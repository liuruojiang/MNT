# V7.7 Sub-B Max Leverage 2008 Cash-Proxy Stress Scan

## Run Metadata
- Entrypoint: `mnt_bot V 7.7 plus.py`
- Data: Yahoo open/close via `fetch_yahoo`; BIL pre-listing segment replaced with 2.5% annualized cash.
- Candidate max leverage values: 1.0, 1.25, 1.5, 1.75, 2.0
- Levered assets under current code: QQQM/GLDM only, via QQQ/GLD proxies.

## Research Question
Does the current 2.0x max leverage cap on QQQ/GLD look too high in the 2008 stress window?

## Data Snapshot
- Panel: 2006-02-06 to 2026-06-01, rows=5111, weekend_rows=0
- First result date after 390-day warmup: 2007-08-27

## Decision
Diagnostic only. This run supports caution around 2.0x in the 2008 stress window, but production change needs confirmation on broader windows and the full portfolio objective.

## Stability
pressure-test-diagnostic

## Key Result
- Best GFC max-drawdown candidate: maxlev_1p0 max_dd=-7.46%, ann_return=2.46%
- Best 2008 max-drawdown candidate: maxlev_1p0 max_dd=-7.46%, ann_return=3.25%

See `scan_summary.csv` and `window_metrics.csv` for full metrics.

## Finalization

- Finalized at: 2026-06-02T03:13:47+08:00
- Decision: diagnostic only: evaluate max leverage mainly on 15Y/10Y/5Y/3Y return-drawdown tradeoff, with 2008/GFC as stress constraint
- Stability label: pressure-and-recent-window-diagnostic
- Complete checker: PASS

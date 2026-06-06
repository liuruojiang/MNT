# V7.7 Sub-B AGG Bond Sleeve Cleanup Sync

Date: 2026-06-06

## Scope

V7.7 Sub-B bond sleeve was changed from `VGLT` live / `TLT` proxy to direct `AGG` live / `AGG` proxy in `mnt_bot V 7.7 plus.py`.

The production ranking/trading pool is now:

`QQQ, EMXC, EFA, GLD, AGG, DBC, BTC-USD, UUP, DBMF, KMLM`

`TLT` is intentionally retained only as a required inflation-gate data series. It is not in `US_ROT_POOL` and is not a tradable/ranked Sub-B asset. The gate still uses the existing `DBC/TLT/UUP` logic to decide whether macro candidates enter the official leg.

## Code Changes

- `US_ROT_BASE_ASSETS`: replaced `VGLT -> TLT` with `AGG -> AGG`.
- `SUBB_INFLATION_GATE_TICKERS`: added `("DBC", "TLT", "UUP")` so the gate remains data-complete after `TLT` leaves the trading pool.
- `SUBB_REQUIRED_PRICE_TICKERS` and `US_ALL_TICKERS`: include inflation-gate tickers for freshness and fetch coverage.
- `rot_tickers` in `_cached_fetch_data`: includes gate tickers so `us_rot_close` has the `TLT` column needed by `_subb_active_ranking_codes`.
- Position parser display text: updated the Sub-B pool wording to show `AGG`.
- Regression test: added `test_subb_bond_sleeve_uses_agg_directly`.

## Backtest Impact

Comparison used the V7.7 Sub-B official path components: Yahoo adjusted close/open data, weekly signal, `T close -> T+1 open` execution, `US_ROT_COMMISSION=0.1%`, official leg 50% + EMA leg 50%, `EMXC/EEM`, `IBIT/BTC-USD`, and VolReg enabled.

Matched window: 2008-12-15 to 2026-06-05, 4395 trading days.

| Window | Old VGLT/TLT CAGR / Max DD | New AGG CAGR / Max DD | Main delta |
|:-|:-:|:-:|:-|
| Full | 20.00% / -12.87% | 20.00% / -17.33% | CAGR flat; max DD deeper by 4.45pp |
| 10Y | 31.67% / -12.31% | 31.78% / -12.31% | CAGR +0.12pp |
| 5Y | 29.14% / -12.31% | 29.18% / -12.31% | Near flat |
| 3Y | 39.07% / -11.03% | 39.07% / -11.03% | Near flat |
| 1Y | 51.02% / -10.56% | 51.02% / -10.56% | Near flat |

Full-window max drawdown for both variants ran from 2011-04-29 to 2013-06-24. The AGG variant had a deeper drawdown in that window.

## Data Availability

Yahoo data used in the comparison included:

- `AGG`: 5708 rows, 2003-09-29 to 2026-06-05, `close/open`.
- `TLT`: 5894 rows, 2003-01-02 to 2026-06-05, `close/open`, retained as gate data.
- `BIL`, `SPY`, `DBC`, `UUP`, `DBMF`, `KMLM`, `BTC-USD`, `IBIT`, `EMXC`, `EEM`, `EFA`, `GLD`, `QQQ`: available through 2026-06-05 or later for crypto.

## Verification

Commands run:

- `python -m py_compile "mnt_bot V 7.7 plus.py"`
- `python -m pytest tests/test_v77_suba_price_index_pool.py -q`
- `git diff --check -- "mnt_bot V 7.7 plus.py" "tests/test_v77_suba_price_index_pool.py"`
- Import check confirmed:
  - `US_ROT_POOL=QQQ,EMXC,EFA,GLD,AGG,DBC,BTC-USD,UUP,DBMF,KMLM`
  - `SUBB_REQUIRED_PRICE_TICKERS=QQQ,EMXC,EFA,GLD,AGG,DBC,BTC-USD,UUP,DBMF,KMLM,BIL,SPY,TLT`
  - `HAS_VGLT=False`

Latest verification result: `py_compile` passed, pytest passed with 8 tests, diff whitespace check passed with only CRLF/LF warnings.

## Cleanup

Removed local generated test/cache artifacts:

- `.pytest_cache/`
- `__pycache__/`
- `tests/__pycache__/`
- `TASK_STATE.md`

Regression tests in `tests/test_v77_suba_price_index_pool.py` are intentionally retained.

## Backup

Pre-edit backup:

`D:\动量策略\A股美股动量组合策略\.codex_backups\20260606_160039`

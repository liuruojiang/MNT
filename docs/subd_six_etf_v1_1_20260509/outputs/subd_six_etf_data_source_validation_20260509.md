# Sub-D Six ETF Data Source Validation - 2026-05-09

## 159941.SZ split / adjustment check

- Sina raw close and CNFin raw kline show `close=0.604` on 2022-07-05 after `2.384` on 2022-07-04, creating a raw close-to-close move near `-74.66%` if returns are computed directly from raw close.
- QVeris raw-like `cps=0` reports `preClose=0.596`, `close=0.604`, `changeRatio=+1.3423%`, confirming the exchange-style return was not `-74.66%`.
- QVeris continuous `cps=3` reports `2022-07-05 close=2.416` after `2.384`, preserving the same `+1.3423%` return while removing the price-level discontinuity.
- For momentum/backtest scans, QVeris `cps=3` is the cleaner source than Sina raw close for this ETF pool.

## Output files

- `outputs/subd_six_etf_159941_data_source_check_20260509.csv`
- `outputs/subd_six_etf_qveris_cps3_sources_20260509.csv`
- `outputs/subd_six_etf_qveris_cps3_data_quality_20260509.csv`

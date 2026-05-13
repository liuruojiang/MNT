# Agent Notes

## Market Data Source Defaults

- For live market data, total market capitalization checks, A-share pool checks, and realtime signal quote snapshots, prefer free data sources first: Xinhua Finance / CNFin, Sina, Eastmoney, Tencent, or local cache when fresh and coverage is sufficient.
- QVeris is no longer an available fallback. Do not use QVeris discovery, REST endpoints, tool execution, or `QVERIS_API_KEY` for new research, live market checks, pool checks, or realtime signal work.
- If free sources and local cache cannot provide the required field, freshness, or coverage, report the task as data-source blocked with the exact missing field/symbol/date.
- Historical documents or old output filenames may mention QVeris as provenance. Treat those as archived evidence only, not as an approved source for new runs.

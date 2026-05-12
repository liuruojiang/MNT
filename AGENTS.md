# Agent Notes

## Market Data Source Defaults

- For live market data, total market capitalization checks, A-share pool checks, and realtime signal quote snapshots, prefer free data sources first: Xinhua Finance / CNFin, Sina, Eastmoney, Tencent, or local cache when fresh and coverage is sufficient.
- Use QVeris as a paid fallback only when free sources are stale, incomplete, unavailable, or inconsistent enough to block a reliable answer.
- Report any QVeris fallback/source caveat in the answer.
- Never store QVeris API keys or other secrets in `AGENTS.md`, repo files, scripts, command lines, logs, or chat replies. Read keys from environment variables or a secure secret manager only.

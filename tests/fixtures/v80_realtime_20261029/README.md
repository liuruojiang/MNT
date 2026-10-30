# 930955 realtime regression receipts

These are unmodified JSON payloads returned by EastMoney on 2026-10-29,
wrapped with the requested URL, HTTP status and Beijing retrieval time.

- `quote.json`: market 2, code 930955; valid price fields but `f124=0`.
- `trends.json`: same market/index, explicit dated minute bars. Received at
  14:28:13 Beijing; the final in-progress bar is labelled 14:29. The parser
  selects the 14:28 bar (11496.27) and does not consume the future-labelled bar.

The tests replay these receipts offline. Rejection cases are deliberately
mutated copies, not claimed vendor observations. Other-index fixtures used
in the unit merge test are synthetic and are not strategy-performance data.

Fresh network probes and the official supplement/merge checks are recorded
separately in `outputs/v80_realtime_fix_20261029/`. Local network success does
not establish Poe-host connectivity or deployment.

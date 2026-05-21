# Agent Notes

Common rules live in `C:\Users\Administrator.DESKTOP-95I7VVU\AGENTS.md`. This file only adds local rules for the A-share / US momentum combo workspace.

## Window And Inception Rules

- For ATK, ADK, DK, expanded-pool, and replacement-signal tests, explicitly check the listing/availability/start date of every required index, ETF, or pool member before comparing results.
- Do not rely on inception-to-date metrics when a late-starting component truncates the true common sample.
- Do not include pre-publication vendor backfilled index prices in formal or quasi-formal conclusions. Mark those windows as proxy research or invalid.
- If DK uses the full current pool `SZ50 / HS300 / ZZ500 / ZZ1000 / CYB`, formal tests must start no earlier than `ZZ1000` publication on `2014-10-17`.
- If a reduced DK or ATK pool is used, the sample start must be the latest actual publication/listing date among that run's participants and must be recorded.
- When adding assets such as KCB100, distinguish price-index proxy data from total-return index data and record the formal publication date.

## Sleeve Rules

- `Sub-A` / `Sub-A-DK`: confirm A-share fields, DK fields, adjustment mode, latest available date, cost path, and whether R2, volume, overheat, decay, target-vol, and risk overlays affected returns.
- `Sub-B`: formal tests require `T close signal -> T+1 adjusted open execution -> T+1 close return`, real `us_open`, version-default VolReg, version-default asset overlay, fees, `EMXC/EEM`, `IBIT/BTC-USD`, and a US/crypto calendar not compressed to A-share dates.
- `Microcap`: refresh and read the official microcap output path before using it in a combined portfolio.
- Four-sleeve or five-sleeve combinations: refresh every sleeve to the latest available trading date first, then record each sleeve's usable start/end date before combining.

## Display And Query Surface Parity

- Strategy logic changes that affect user-visible state must keep signal, live signal, params, and live params in sync.
- For V7.x bot scripts, check `_handle_signal`, `_handle_live_signal`, `_handle_params`, and `_handle_live_params` when changing pools, defaults, thresholds, overlays, or display wording.
- When formalizing a pool or rule, remove obsolete warning-only wording from displays and show the actual production rule.
- For RiskGate, target-vol, NAV-DD, and overlays, expose trigger/recovery thresholds, current measured value, raw scale, overlay multiplier, and final execution scale.

## Local Verification

- If `tests/` is absent or intentionally cleaned, run the smallest real verification available, usually `python -m py_compile "mnt_bot V X.Y plus.py"` plus `git diff --check` on touched docs/code.

# V7.7 ADK 8-Pair Formalization

Date: 2026-05-20

## Decision

V7.7 Sub-A-DK now uses the 8-pair L4 pool as the formal production ADK path.

Formal pair pool:

- `SZ50/ZZ500`
- `SZ50/ZZ1000`
- `SZ50/CYB`
- `HS300/ZZ500`
- `HS300/ZZ1000`
- `HS300/CYB`
- `ZZ500/CYB`
- `ZZ1000/CYB`

## Formal Parameters

| Parameter | Value |
| --- | ---: |
| Pair pool | 8 pairs |
| R2 quality gate | enabled, `0.05` |
| Target volatility | `14%` |
| Volatility window | `40` trading days |
| Max leverage | `1.5x` |
| Min leverage | `0.1x` |
| Scale adjustment threshold | `0.25` |
| Same-side overheat | enabled |
| Same-side overheat enter / exit | `22% / 18%` |
| Same-side overheat derisk scale | `0.0x` |
| Pair score decay | disabled |
| DD RiskGate | disabled |
| DK single-side commission | `0.05%` |

## Evidence

The temporary scan folders were cleaned after promotion. The measured decision record is kept here so the production documentation does not depend on scratch outputs. The original scan artifacts were backed up before cleanup under `.codex_backups/20260520_222830`.

Measured before promotion:

| Candidate | Full annual | Full MDD | 10Y annual | 5Y annual | 3Y annual | 1Y annual |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original V7.7 official baseline | 28.79% | -20.37% | 26.92% | 31.45% | 26.64% | 22.34% |
| 8-pair L4 | 21.32% | -15.85% | 20.07% | 23.81% | 23.50% | 19.97% |
| 5-pair L4 | 21.77% | -16.07% | 21.21% | 26.33% | 22.23% | 20.56% |

The 8-pair path was chosen over 5-pair because it keeps `ZZ1000/CYB`, which remained the third-largest positive contributor in the L4 attribution. Removing only `ZZ1000/CYB` under the same L4 parameters reduced full annual return and worsened drawdown.

## Code Changes

- `CN_DK_TARGET_VOL`: `0.20 -> 0.14`
- `CN_DK_VOL_WINDOW`: `30 -> 40`
- Added `ADK_OFFICIAL_PAIR_ORDER`.
- `run_dk_strategy(...)` now builds and ranks only pairs in `ADK_OFFICIAL_PAIR_ORDER`.
- Query displays now describe the formal 8-pair pool instead of the old 10-pair universe and warning-only whitelist wording.
- User-facing warning text for weak, invalid, or outside-pool pairs was removed; those categories are no longer shown in query output.

## Query Surfaces To Keep In Sync

The following surfaces must all show the formal 8-pair pool:

- `_handle_signal`
- `_handle_live_signal`
- `_handle_params`
- `_handle_live_params`

Regression coverage:

- `tests/test_v77_adk_official_8pair.py`

## Rollback

To roll back this formalization:

- Restore `CN_DK_TARGET_VOL = 0.20`.
- Restore `CN_DK_VOL_WINDOW = 30`.
- Remove the official pair filter in `run_dk_strategy(...)`.
- Restore the former display wording for the 10-pair universe.

Filesystem backup before this edit:

`.codex_backups/20260520_220448`

Cleanup backup before removing temporary scan outputs:

`.codex_backups/20260520_222830`

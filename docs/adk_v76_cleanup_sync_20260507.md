# ADK V7.6 Cleanup Sync Record - 2026-05-07

## Scope

Removed disposable ADK parameter scan artifacts after the V7.5/V7.6 DK review pass.

Deleted after backup:

- `analyze_adk_parameter_stability.py`
- `docs/adk_v75_v76_current_stability_DK_*`

Preserved:

- Formal strategy scripts, including `mnt_bot V 7.5 plus.py` and `mnt_bot V 7.6 plus.py`
- Non-DK Sub-A/Sub-B research outputs
- Existing tests not specific to the ADK parameter scan
- Official data caches under `.cn_official_cache/`

## Backup

Backup path:

- `.codex_backups/20260507_005220`

## ADK Notes

V7.6 already has the formal DK volume-clear defaults in the strategy script:

- `CN_DK_VOLUME_POLICY = "formal_clear"`
- `CN_DK_VOLUME_YELLOW_MA = 40`
- `CN_DK_VOLUME_YELLOW_DAYS = 16`
- `CN_DK_VOLUME_CLEAR_SCALE = 0.0`

The removed scan directories were local test artifacts and are not required for runtime.

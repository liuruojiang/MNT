# ADK CYB/ZZ1000 Cleanup And Sync Record - 2026-06-12

## Scope

- Finalized the long CYB / short ZZ1000 sleeve at `tv14/max1.5/db0.375` with `volhot_w20_thr0.26_scale0`.
- Updated the ADK six-spread Poe script to expose both CYB/ZZ1000 forward and reverse sleeves plus the 50/50 pair.
- Cleaned temporary validation scaffolding after the landing verification was complete.

## Production Files Kept

- `final_adk_cyb_zz1000_spread.py`
- `substrategy_adk_cyb_zz1000_spread.py`
- `substrategy_adk_zz1000_cyb_spread.py`
- `poe_adk_six_spread_v1_0_bot.py`
- `outputs/final_adk_spread/final_cyb_zz1000_tv14_max1p5_db0p375_volhot_w20_thr0p26_scale0_daily.csv`
- `outputs/final_adk_spread/final_cyb_zz1000_tv14_max1p5_db0p375_volhot_w20_thr0p26_scale0_metrics.json`
- `outputs/final_adk_spread/substrategy_cyb_zz1000_tv14_max1p5_db0p375_volhot_w20_thr0p26_scale0_daily.csv`
- `outputs/final_adk_spread/substrategy_cyb_zz1000_tv14_max1p5_db0p375_volhot_w20_thr0p26_scale0_metrics.json`
- `outputs/final_adk_spread/substrategy_zz1000_cyb_tv14_db5_cybvol_w60_thr1p05_d6_scale0p25_daily.csv`
- `outputs/final_adk_spread/substrategy_zz1000_cyb_tv14_db5_cybvol_w60_thr1p05_d6_scale0p25_metrics.json`

## Test Artifacts Removed

- `tests/`
- `.pytest_cache/`
- `__pycache__/`

The removed files were temporary pytest regression and Poe registration checks used during landing. They were intentionally not kept as part of the production Poe bundle.

## Verification Before Cleanup

- `python -m py_compile "final_adk_cyb_zz1000_spread.py" "substrategy_adk_cyb_zz1000_spread.py" "poe_adk_six_spread_v1_0_bot.py"` passed.
- Targeted pytest verification for the landing and Poe CYB/ZZ1000 registration passed: `5 passed`.
- Poe smoke confirmed `len(STRATEGIES)=10`, `len(PAIR_DEFS)=5`, and embedded artifact fallback count `20`.
- Offline local-artifact CYB/ZZ1000 50/50 combo: Full `7.300461%/-5.715534%`, sample `2015-01-29` to `2026-06-05`.

## Current Production Parameters

- Forward sleeve: `target_vol=0.14`, `max_leverage=1.50`, `scale_deadband=0.375`, `vol_window=20`, `volhot_window=20`, `volhot_threshold=0.26`, `volhot_scale=0.0`.
- Reverse sleeve: `target_vol=0.14`, `vol_window=60`, `max_leverage=1.25`, `scale_deadband=0.05`, `cyb_vol_low w60/thr1.05/confirm6/scale0.25`.
- Poe pair: `cyb_zz1000_pair50`, equal-weighted forward and reverse sleeves.

## Rollback Notes

- Strategy backups: `.codex_backups/20260612_011200`.
- Poe backups: `.codex_backups/20260612_012227`.

# ADK HS300/ZZ500 Poe 14-Leg Cleanup Sync - 2026-06-12

## Scope

- Target bot: `poe_adk_six_spread_v1_0_bot.py` (`ADK-Six-Spread-V1`).
- Added the HS300/ZZ500 forward and reverse sub-strategies to the ADK Poe bot, taking the bot from 12 sub-strategies to 14 sub-strategies.

## Added Sleeves

- `forward_hs300_zz500`: long HS300 / short ZZ500.
- `reverse_zz500_hs300`: long ZZ500 / short HS300.
- `hs300_zz500_pair50`: 50/50 forward/reverse pair.

## Implementation Notes

- Added the two finalized standalone substrategy artifacts to the Poe registry:
  - `substrategy_hs300_zz500_primary_nav_zz500amthigh_w120_thr1p25_d1_scale0p25_*`
  - `substrategy_zz500_hs300_purple_mainconfirm_amtlow_volridge_*`
- Added `STRATEGY_LEGS` mappings for online price refresh and live signal reconstruction.
- Added the new pair to `PAIR_DEFS` and `PAIR_CHART_LABELS`; signal, live signal, params, live params, and combo performance render through the existing pair-driven loops.
- Restored the Poe-online architecture: embedded payload now contains only compact metrics/parameter JSON for all 14 sub-strategies; daily curves are rebuilt from Sina/EastMoney/Tencent public index data at runtime.
- Removed embedded daily CSV payloads after the first 14-leg pack pushed the script to `4,420,533` bytes and caused Poe editor save/edit failures.
- Current Poe script size after cleanup is about `141 KB`; embedded payload contains `14` metrics files, `0` daily CSV files.

## Verification

- Refreshed new substrategy artifacts:
  - `python "substrategy_adk_hs300_zz500_spread.py"`
  - `python "substrategy_adk_zz500_hs300_spread.py"`
- TDD registry test:
  - Red state before implementation: `12` strategies, `6` pairs, `24` embedded files.
  - Green state after implementation: `python -m pytest tests/test_poe_adk_six_spread_14leg_registry.py -q` -> `3 passed`.
  - Regression guard: test asserts the Poe script stays below `350 KB`, embedded blob below `50,000` chars, and no embedded `_daily.csv` files are present.
- Compile check:
  - `python -m py_compile "poe_adk_six_spread_v1_0_bot.py" "substrategy_adk_hs300_zz500_spread.py" "substrategy_adk_zz500_hs300_spread.py"`
- Structural smoke:
  - `len(STRATEGIES)=14`
  - `len(PAIR_DEFS)=7`
  - embedded artifact count `14`
  - embedded daily CSV count `0`
  - file size `141,182` bytes
- Real online smoke:
  - `python "poe_adk_six_spread_v1_0_bot.py" "组合表现 1Y"` -> exit `0`.
  - Data mode: `online_rebuild_full`; output says Poe online rebuild from Sina/EastMoney/Tencent public index data and does not read local files.
  - `hs300_zz500_pair50` 1Y online rebuilt annual return `7.74%`, max drawdown `-2.48%`, sample `2025-06-11` to `2026-06-11`.
- `git diff --check -- "poe_adk_six_spread_v1_0_bot.py" "tests/test_poe_adk_six_spread_14leg_registry.py"` passed.

## Backup

- Poe script backup: `.codex_backups/20260612_150850`.
- Oversized 14-leg artifact-pack backup before cleanup: `.codex_backups/20260612_152826`.

# ADK ZZ500/SZ50 Poe 12-Leg Cleanup Sync - 2026-06-12

## Scope

- Target bot: `poe_adk_six_spread_v1_0_bot.py` (`ADK-Six-Spread-V1`).
- Corrected target: ADK Poe bot only; `mnt_bot V 7.7 plus.py` is not part of this sync.
- Added the ZZ500/SZ50 forward and reverse sub-strategies to the existing ADK Poe bot, taking the bot from 10 sub-strategies to 12 sub-strategies.

## Added Sleeves

- `forward_zz500_sz50`: long ZZ500 / short SZ50.
- `reverse_sz50_zz500`: long SZ50 / short ZZ500.
- `zz500_sz50_pair50`: 50/50 forward/reverse pair.

The Poe bot now has 6 forward/reverse 50/50 pairs. The all-pair combo key was renamed internally from `three_pair_equal_weight` to `all_pair_equal_weight`.

## Implementation Notes

- Added ZZ500 public data mappings for EastMoney/Sina/Tencent online refresh.
- Added compatibility for the new metadata fields used by the finalized ZZ500/SZ50 scripts:
  - `abs_ma` as an alias for `abs_mom_day`.
  - `scale_deadband` as an alias for target-vol `deadband`.
  - `score_threshold` inside `score_overheat`.
  - `one_way_commission` in cost models.
  - `zz500_amount_low` / `zz500_amt_hot` amount overlays.
- Repacked the Poe embedded artifact payload with daily CSV and metrics JSON for all 12 sub-strategies, 24 embedded files total.
- `outputs/` remains ignored by git; the Poe bot embeds the finalized daily/metrics payload needed for Poe fallback.

## Cleanup

- Removed local Python bytecode cache: `__pycache__/`.
- No scan-layer source files were deleted because the finalized local scripts import them for reproducibility.

## Verification

- Rebuilt final ZZ500/SZ50 artifacts:
  - `python "final_adk_zz500_sz50_spread.py"`
  - `python "final_adk_sz50_zz500_spread.py"`
  - `python "final_adk_zz500_sz50_dual_50_50_combo.py"`
- Compile check:
  - `python -m py_compile "final_adk_zz500_sz50_spread.py" "final_adk_sz50_zz500_spread.py" "final_adk_zz500_sz50_dual_50_50_combo.py" "poe_adk_six_spread_v1_0_bot.py"`
- Offline Poe smoke with `POE_ADK_DISABLE_ONLINE=1`:
  - `len(STRATEGIES)=12`
  - `len(PAIR_DEFS)=6`
  - embedded artifact count `24`
  - `zz500_sz50_pair50` offline embedded curve: `2007-08-06` to `2026-06-05`, 4576 rows, annual return `6.267580%`, max drawdown `-8.963852%`.
- Online Poe smoke:
  - online refresh ok
  - `sources` includes `zz500`
  - new curves extended to `2026-06-11` during the smoke run.
- `git diff --check -- "poe_adk_six_spread_v1_0_bot.py"` passed with CRLF warnings only.

# Sub-B Turnover/Cost Cloud Handoff - 2026-05-07

## Goal

Run the remaining Sub-B V7.5/V7.6 numeric parameter stability groups without waiting for user confirmation.

The queue is:

1. `turnover_cost`
2. `volreg_windows`
3. `vol_weight`
4. `ema_volscale`

Structural studies such as asset-pool changes and macro-pool membership are intentionally not mixed into this numeric queue. They need separate candidate definitions and should be documented as a follow-up if requested.

## Local Stop Point

- Local process was stopped intentionally before sleep.
- Completed partial outputs are preserved in this directory.
- `partial_summary.csv` has 20 rows, meaning 4 completed candidates:
  - `V7.5 / mt0_fee0.0005`
  - `V7.5 / mt0_fee0.001`
  - `V7.5 / mt0_fee0.002`
  - `V7.5 / mt0_fee0.003`
- The script has resume logic. It loads `partial_*` files and skips candidates only when the candidate has all 5 segment rows plus a daily-return column.

## Run Command

From the repo root:

```powershell
python run_subb_remaining_parameter_groups.py
```

On Linux/cloud shell, the same command is:

```bash
python run_subb_remaining_parameter_groups.py
```

The runner writes a manifest to:

`docs/subb_v75_v76_parameter_stability_remaining_cloud_manifest_20260507.json`

## Expected Final Files

For `turnover_cost`, verify:

- `summary.csv`: 200 rows
- `rank.csv`: 40 rows
- `v75_v76_compare.csv`: 20 rows
- `yearly_returns.csv`
- `daily_returns.csv`
- `audit.json`

The expected row count comes from 2 versions x 20 candidates x 5 segment rows.

The runner also verifies expected row counts for the other groups and records them in the manifest.

## Follow-Up

After the run completes, summarize:

- best candidate by recent weighted Sharpe for V7.5 and V7.6 for every group
- current default row for every group
- platform coverage at 99%, 95%, 90%, and 80%
- whether higher cost assumptions change the default conclusion
- whether a nonzero `US_ROT_MIN_TURNOVER` improves net performance enough to justify changing the default
- whether VolReg window, inverse-vol weight window, or EMA VolScale half-life justify a default change

Append the conclusion to `docs/subb_v75_v76_parameter_stability_notes_20260506.md`.

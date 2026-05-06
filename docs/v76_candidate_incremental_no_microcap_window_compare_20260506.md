# V7.6 Candidate Incremental No-Microcap Compare - 2026-05-06

## Validity

- Target script: `mnt_bot V 7.6 plus.py`.
- This report records the pre-change runtime-override experiment. Candidate parameters were applied only through temporary globals during the run; the source default was changed afterward only for the accepted volume rule.
- Official entrypoint: `CombinedStrategyV75._fetch_data(include_cn_live_snapshot=False, include_us_live_snapshot=False)` plus `_run_strategies()`.
- Scope: no microcap, no Sub-C. Combined sleeves are `Sub-A`, `Sub-A-DK`, and `Sub-B` with no-microcap normalized performance weights.
- This is a same-run 8-case experiment. The final complete run overwrote earlier partial/resume artifacts and generated all daily files plus the summary in one process.
- Common end date: `2026-05-06`. This is one day later than the earlier V7.5/V7.6 no-microcap comparison ending `2026-05-05`, so this document should be used only for candidate-vs-current-V7.6 incremental judgment.

## Evidence

Output directory:

`docs/v76_candidate_incremental_no_microcap_window_compare_20260506`

Key files:

- `summary_no_microcap_windows.csv`
- `audit.json`
- `daily_V76_base.csv`
- `daily_pos_025_120_015.csv`
- `daily_wait3.csv`
- `daily_volume_cyb_ma15_d5.csv`
- `daily_pos_plus_wait3.csv`
- `daily_pos_plus_volume.csv`
- `daily_wait3_plus_volume.csv`
- `daily_all_three.csv`

Command:

```powershell
python analyze_v76_candidate_incremental_no_microcap_window_compare.py
```

The temporary runner was cleaned from the repository after the evidence files were generated. The formal evidence for this report is the same-run `summary_no_microcap_windows.csv`, `audit.json`, and per-case daily files in the output directory above.

Data audit from the complete run:

| Dataset | Start | End | Rows | Duplicate dates |
|---|---:|---:|---:|---:|
| CN close | 2010-06-01 | 2026-04-30 | 3865 | 0 |
| CN-DK close | 2010-06-01 | 2026-04-30 | 3865 | 0 |
| US rotation close | 2007-05-30 | 2026-05-06 | 4765 | 0 |
| US production daily | 2009-11-23 | 2026-05-06 | 4137 | 0 |

Sub-B audit: `uses_us_open=True`, `us_open_ticker_count=21`, `T close signal -> T+1 open execution=True`, `VolReg=True`, `EMXC/EEM splice=True`, `IBIT/BTC-USD splice=True`.

## Cases

| Case | Runtime override |
|---|---|
| `V76_base` | none |
| `pos_025_120_015` | `CN_TARGET_VOL=0.25`, `CN_VOL_WINDOW=120`, `CN_SCALE_THRESHOLD=0.15` |
| `wait3` | `CN_ENTRY_WAIT_DAYS=3` |
| `volume_cyb_ma15_d5` | `CN_SA_VOLUME_CYB_MA=15`, `CN_SA_VOLUME_CYB_DAYS=5` |
| `pos_plus_wait3` | position scaling + wait3 |
| `pos_plus_volume` | position scaling + volume |
| `wait3_plus_volume` | wait3 + volume |
| `all_three` | position scaling + wait3 + volume |

## Main Table

Annual return and MaxDD by window:

| Case | 10Y Ann | 10Y MaxDD | 8Y Ann | 8Y MaxDD | 6Y Ann | 6Y MaxDD | 4Y Ann | 4Y MaxDD | 2Y Ann | 2Y MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `V76_base` | 31.39% | -10.01% | 30.60% | -10.01% | 34.91% | -10.01% | 30.82% | -10.01% | 41.59% | -10.01% |
| `pos_025_120_015` | 31.15% | -10.03% | 30.35% | -10.03% | 34.63% | -10.03% | 30.62% | -10.03% | 41.24% | -10.03% |
| `wait3` | 31.41% | -10.01% | 30.61% | -10.01% | 34.97% | -10.01% | 30.88% | -10.01% | 41.60% | -10.01% |
| `volume_cyb_ma15_d5` | 31.90% | -9.82% | 31.25% | -9.82% | 35.57% | -9.82% | 31.53% | -9.82% | 43.07% | -9.82% |
| `pos_plus_wait3` | 31.16% | -10.03% | 30.37% | -10.03% | 34.68% | -10.03% | 30.68% | -10.03% | 41.24% | -10.03% |
| `pos_plus_volume` | 31.77% | -9.83% | 31.13% | -9.83% | 35.40% | -9.83% | 31.47% | -9.83% | 42.92% | -9.83% |
| `wait3_plus_volume` | 31.92% | -9.82% | 31.26% | -9.82% | 35.64% | -9.82% | 31.61% | -9.82% | 43.08% | -9.82% |
| `all_three` | 31.79% | -9.83% | 31.15% | -9.83% | 35.47% | -9.83% | 31.56% | -9.83% | 42.95% | -9.83% |

Delta vs current V7.6 base, annual return in basis points and MaxDD in basis points:

| Case | 10Y Ann Δ | 10Y DD Δ | 8Y Ann Δ | 8Y DD Δ | 6Y Ann Δ | 6Y DD Δ | 4Y Ann Δ | 4Y DD Δ | 2Y Ann Δ | 2Y DD Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `pos_025_120_015` | -24.5 | -1.9 | -24.4 | -1.9 | -27.9 | -1.9 | -19.9 | -1.9 | -35.3 | -1.9 |
| `wait3` | +1.4 | +0.1 | +1.1 | +0.1 | +6.0 | +0.1 | +6.5 | +0.1 | +0.8 | +0.1 |
| `volume_cyb_ma15_d5` | +50.8 | +19.0 | +65.0 | +19.0 | +66.7 | +19.0 | +71.6 | +19.0 | +147.7 | +19.0 |
| `pos_plus_wait3` | -23.2 | -1.8 | -23.4 | -1.8 | -22.3 | -1.8 | -14.2 | -1.8 | -34.7 | -1.8 |
| `pos_plus_volume` | +38.0 | +18.0 | +53.2 | +18.0 | +48.9 | +18.0 | +65.2 | +18.0 | +133.1 | +18.0 |
| `wait3_plus_volume` | +52.3 | +19.1 | +66.3 | +19.1 | +73.4 | +19.1 | +79.5 | +19.1 | +148.8 | +19.1 |
| `all_three` | +39.7 | +18.4 | +55.2 | +18.4 | +56.2 | +18.4 | +73.9 | +18.4 | +136.2 | +18.4 |

Positive MaxDD delta means shallower drawdown.

## Readout

- `CN_TARGET_VOL=0.25 / CN_VOL_WINDOW=120 / CN_SCALE_THRESHOLD=0.15` does not pass the combination-layer incremental test. It lowers annual return in all windows and slightly deepens MaxDD. This can remain a Sub-A-only candidate, but should not be promoted to the V7.6 combo baseline from this result.
- `CN_ENTRY_WAIT_DAYS=3` is effectively neutral to slightly positive. It adds only `+1.4 bp` to `+6.5 bp` annual return across tested windows and has negligible MaxDD impact. This is not strong enough by itself to justify a default change.
- `CN_SA_VOLUME_CYB_MA=15 / CN_SA_VOLUME_CYB_DAYS=5` is the strongest single candidate. It improves annual return in every window and makes MaxDD shallower by about `19 bp`.
- `wait3_plus_volume` is the best tested combination across all windows. It beats base by `+52.3 bp` 10Y annual return, `+66.3 bp` 8Y, `+73.4 bp` 6Y, `+79.5 bp` 4Y, and `+148.8 bp` 2Y, with MaxDD about `19.1 bp` shallower.
- `all_three` is worse than `wait3_plus_volume` because the position-scaling candidate drags the result down.

## Current Decision

For current V7.6 no-microcap combination-layer evidence:

- Do not add `0.25 / 120 / 0.15` to the combo default.
- Keep `wait=3` as optional but not decisive.
- Promote `volume_cyb_ma15_d5` to the next confirmation stage.
- If testing a bundled candidate, test `wait3_plus_volume`, not `all_three`.

Residual risks:

- This excludes microcap by design.
- This is a no-microcap combination test, not a live-code parameter change.
- A-share data in the run ended `2026-04-30`; US data ended `2026-05-06`. The audit log records an A-share data-delay warning for `2026-05-06`.

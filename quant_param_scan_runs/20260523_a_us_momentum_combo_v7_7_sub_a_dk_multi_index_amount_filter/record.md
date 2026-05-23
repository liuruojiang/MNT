# V7.7 ADK Multi-Index Amount Filter Scan

## Question

Check whether the prior HS300 amount rule remains the only useful DK/ADK volume source after V7.7 8-pair formalization, using the other ADK-involved indices on the same rule family.

## Baseline

- Entry point: `mnt_bot V 7.7 plus.py`
- ADK production path: formal 8-pair V7.7 Sub-A-DK.
- Formal evaluation start: `2014-10-17` because the current full ADK pool includes ZZ1000.
- Baseline data: `mnt_strategy_data_cn.csv`.
- Baseline return end: `2026-05-14`.

## Candidate Grid

- Sources: SZ50, HS300, ZZ500, ZZ1000, CYB.
- Rule: index amount below its own MA for N consecutive days.
- Grid: MA `10..80` step 1, days `2..20` step 1.
- Execution: T close volume state affects T+1 ADK total exposure.
- Defense action: scale ADK exposure to `50%`.
- Extra cost: `10.0bp * abs(scale change)`.

## Outputs

- `scan_summary.csv`: one row per source/MA/days candidate with full and recent windows.
- `window_metrics.csv`: long-form window metrics.
- `scan_summary_wide_detailed.csv`: full detailed wide table from the raw scan.
- `window_metrics_long_detailed.csv`: full detailed long table from the raw scan.
- `source_summary.csv`: best candidate and robust-pass count by source.
- `best_by_source.csv`: top candidate per source.
- `top_candidates.csv`: global top candidates.
- `amount_availability.csv`: price/amount availability and source checks.
- `baseline_metrics.csv`: V7.7 ADK baseline by window.
- `zz500_focus_platform_note.md`: focused ZZ500 platform interpretation.
- `zz500_focus_platform_candidates.csv`: selected top, recent-pass, and relaxed-recent ZZ500 rows.
- `zz500_focus_platform_by_days.csv`: ZZ500 recent-pass grouping by consecutive-day threshold.
- `zz500_focus_neighborhood_ma28_42_d2_8.csv`: ZZ500 local-neighborhood grouped diagnostics.

## Data Snapshot

- All metrics are computed from the local V7.7 ADK path and local `mnt_strategy_data_cn.csv`.
- Amount data is fetched through the script's `_fetch_cn_amount_with_fallback(...)`.
- Formal evaluation starts on 2014-10-17 because the current full ADK pool includes ZZ1000.

## Stability Classification

- Stability: pending finalizer.
- Source-change rule: research only, no production source change.

## Decision

Pending final interpretation after strict artifact check.

## Finalization

- Finalized at: 2026-05-23T11:57:44+08:00
- Decision: Do not promote any ADK amount filter to production. Under current V7.7 8-pair baseline, HS300 is not uniquely effective, but no index source passes the robust full/10Y/5Y/3Y bar; keep DK volume warning-only and use ZZ500/HS300/ZZ1000 only as research leads.
- Stability label: research_rejected_no_robust_pass
- Complete checker: FAIL
- Checker errors:
  - scan_summary.csv missing columns: segment, start, end, rows, ann_return, ann_vol, max_dd, sharpe_repo
  - window_metrics.csv missing columns: ann_return_full, max_dd_full, ann_return_last_10y, max_dd_last_10y, ann_return_last_5y, max_dd_last_5y, ann_return_last_3y, max_dd_last_3y, ann_return_last_1y, max_dd_last_1y
  - record.md missing required marker: stability

## Finalization

- Finalized at: 2026-05-23T11:59:05+08:00
- Decision: Do not promote any ADK amount filter to production. Under current V7.7 8-pair baseline, HS300 is not uniquely effective, but no index source passes the robust full/10Y/5Y/3Y bar; keep DK volume warning-only and use ZZ500/HS300/ZZ1000 only as research leads.
- Stability label: research_rejected_no_robust_pass
- Complete checker: PASS

## ZZ500 Focus Follow-Up

- Added at: 2026-05-23.
- Source: existing `scan_summary_wide_detailed.csv`; no production strategy script change.
- Result: ZZ500 is not a one-point accident. Recent-only criteria found 38 candidates, concentrated mainly around `days=5..7` and `MA34..41`, with broader support from `MA26..54`.
- Limitation: the useful ridge still gives effectively no 10Y drawdown improvement and usually costs about `2pp..3pp` 10Y annual return.
- Follow-up decision: treat `ZZ500 MA28..41 / days 5..6` as a research lead only; keep DK amount rules warning-only.

## Warning-Only Display Update

- Added at: 2026-05-23.
- Selected warning condition: `ZZ500 amount < MA28 for 5 consecutive days`.
- Rationale: among the ZZ500 platform rows, `MA28 / 5 days` has lower 10Y annual drag than the max-score `MA34 / 4 days`, while still improving 5Y/3Y/1Y drawdown in the current scan.
- Implementation scope: replace the V7.7 DK成交额 warning-bar condition only; do not change ADK exposure, return, or NAV calculation.
- Code path: `mnt_bot V 7.7 plus.py` constants `CN_DK_VOLUME_YELLOW_SECID`, `CN_DK_VOLUME_YELLOW_LABEL`, `CN_DK_VOLUME_YELLOW_MA`, and `CN_DK_VOLUME_YELLOW_DAYS`.

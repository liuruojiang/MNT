# Quant Parameter Scan Record

## Run Metadata

- Run id: `20260930_frozen_neighborhoods`
- Created at: 2026-09-30T19:45:39+08:00
- Project: A股美股动量组合策略
- Strategy or version: V8.0 L6
- Sleeve or subsystem: Sub-C
- Parameter group: `scales_and_10_asset_weights`
- Scan type: `candidate_bundle`; seven scale parameter groups plus ten constrained asset-weight groups.
- Repo or workspace path: `D:\动量策略\A股美股动量组合策略`
- Target entrypoint: `mnt_bot V 8.0 plus.py::_compute_subc_production_snapshot`
- Git branch: `main`
- Git commit: `a7353eebc17c94e0d3566404d72fb395776fc54f`
- Working tree status before:

```text
M "mnt_bot V 8.0 plus.py"
 M tests/test_v78_cn_live_freshness.py
?? docs/v80_recert_l0_20260926.md
?? docs/v80_recert_l1_20260926.md
?? docs/v80_recert_l2_20260926.md
?? docs/v80_recert_l3_20260926.md
?? docs/v80_recert_l4_20260926.md
?? docs/v80_recert_l5_20260930.md
?? research_v80_subb_correlation_allocation.py
?? research_v80_subb_rebalance_period.py
?? research_v80_subc_joint_risk.py
?? tests/test_v80_l1_input_boundaries.py
?? tests/test_v80_l2_annualization_period.py
```

## Research Question

- Baseline: the current V8.0 Sub-C ten-asset paper path on L1 frozen prices; replay must match L2 each day before comparing candidates.
- Candidate grid: equity target volatility 12/15/18%, equity window 10/15/20, gold short window 20/30/40, gold long window 189/252/378, scale deadband 0.25/0.35/0.45, minimum scale 0.4/0.5/0.6, maximum scale 1.25/1.5/1.75. For each of ten base asset weights, also test 0.8x/1.0x/1.2x and zero. Other asset weights are renormalized proportionally to keep the total at 100%. Every group includes the current value and a relevant module/leg-off path.
- Decision target: `keep_default` or `rerun_required`; an alternative cannot be promoted from this frozen proxy paper window alone.
- Source-change rule: `research_only_no_source_change`
- Required windows: full, 10Y, 5Y, 3Y, 1Y
- Required metrics: annual return, annualized volatility, Sharpe, max drawdown, and strategy-specific exposure/cost metrics
- Promotion threshold: a candidate must be no worse on relevant risk/return windows and stable on both neighboring values; it also needs a corrected continuous C account and proxy-free/PIT validation before production consideration. This study cannot itself authorize promotion.
- Rerun triggers: source/input hash change, baseline parity failure, missing execution open, malformed window, or new correction to C quantity/cost accounting.

## Implementation Anchor

- Official entrypoint: `CombinedStrategyV80._cached_run_strategies`, C branch `_compute_subc_production_snapshot` in `mnt_bot V 8.0 plus.py`.
- Function or command path: L1 frozen `formal_inputs.pkl` supplies `frames[3]`, `us_open`; L2 formal results supply the unchanged monthly signals. Candidate runtime overrides call production C component and scaling functions with strict adjusted-open execution.
- Existing loaders reused: L1 frozen formal path; no network or cache refresh.
- Existing metrics reused: L2 first-period anchor and production annualization/drawdown convention; independent output code also records BIL-excess Sharpe and 252-day volatility.
- Default values and source locations: `mnt_bot V 8.0 plus.py:375-400`; final run code SHA-256 `b54fdf3d0e4d83e0ac7171cc6272923536cbc3ce896d19e06b29b28739c76f36`.

| parameter | default | source location |
| --- | ---: | --- |
| `PROD_VS_TARGET_VOL` / `PROD_VS_VOL_WINDOW` | 15% / 15d | 389-390 |
| `PROD_GOLD_VS_SHORT_WINDOW` / `LONG_WINDOW` | 30d / 252d | 398-399 |
| `PROD_VS_MIN_LEV` / `MAX_LEV` / `THRESHOLD` | 0.5 / 1.5 / 0.35 | 391-393 |
| ten `PROD_PORTFOLIO` base weights | 20/10/10/10/10/15/2.5/2.5/15/5% | 383 |

## Data Snapshot

- Run timestamp: 2026-09-30 Asia/Shanghai.
- Raw data start/end: frozen L1 `frames[3]` through 2026-09-25; exact first date and rows are recorded by the runner.
- Metrics start after warmup: 2020-12-03.
- Metrics end/latest trading date: 2026-09-25.
- Data sources: L1 `formal_inputs.pkl` SHA-256 `182a5c54d5c81699d8e93038695a76febd15312aa48b5864e47a46318eeba00f` and L2 formal C snapshot SHA-256 `d0754188ef71f8ee938298398a994c3fe78782257df92fd544e7b1c53ed0fb9a`.
- Local cache paths/cache write risk: only frozen pickle reads; no network or repo cache writes.
- Missing or stale data: 10Y unavailable; IBIT uses BTC-USD proxy before 2024-01-11, and L5 found C scaled quantities/fees not continuous. All performance is paper research.
- Alignment rules: use each candidate's identical C daily date index; same-run formal path must match L2 exactly.
- Adjustment mode: L1 validated close prices and strict adjusted US open for scaling changes.
- Trading calendar/timezone assumptions: US session index, T close signal to next US adjusted open; BTC UTC proxy clock remains a separate known limitation.

## Cost and Execution Assumptions

- Commission: base annual ten-asset rebalance 10bp, scale-change model trade cost 6bp.
- Slippage/open-impact: the frozen formal model's adjusted-open path, no additional independent impact estimate.
- Financing: BIL on released capital; BIL plus 100bp annual spread on >1x scaled exposure.
- Borrow or shorting cost: no short leg in C; borrowing is the above model spread, not a broker quote.
- Rebalance timing: year-end last US session close for base assets; scale state changes on next eligible US session.
- Fill timing: strict T+1 adjusted open for scale change.
- Leverage or sizing rules: each group changes only named parameter, with other formal values fixed. Base-weight perturbations proportionally renormalize other assets to sum to 1.
- Hedge assumptions: none.

## Runtime Override Plan

- Override mechanism: `unittest.mock.patch` on the imported production module; no source edit.
- Values restored after each candidate: all patched constants or `PROD_PORTFOLIO` dictionary.
- Default candidate included in same run: yes, once per parameter group.
- Parity check against official/default output: required exact daily index and ≤1e-12 return difference against L2 frozen C snapshot.
- If parity check failed, explanation: run aborts before writing result tables.

## Commands

```powershell
python -X utf8 outputs/v80_recert_20260926/l6/subc/20260930_frozen_neighborhoods/run_subc_scan.py
```

## Output Files

- `scan_summary.csv`: 68 arms × five windows = 340 metric rows, including explicit 10Y `N/A`.
- `window_metrics.csv`: 68 wide rows with full/10Y/5Y/3Y/1Y return and drawdown.
- `scan_meta.json`: this run metadata
- `event_summary.csv`: first changed date, changed days, scale events and cost totals for each arm.
- `path_diagnostics.csv`: each arm's full-window peak/trough, ending NAV, scale event counts, charged days, and a static-base-weight × scale sum. The last sum omits asset drift and momentum cash switches and is not actual account occupancy.
- `post_ibit_listing_metrics.csv`: 68 same-window diagnostics from 2024-01-12, the frozen source's first full return date after IBIT listing.
- `daily_outputs/`: 68 compressed daily return, scale and cost traces.
- `audit_subc_independent.json`: 99,212 daily rows and 340 metric rows checked; negative fee fault injected and rejected.
- `../../adk/cross_audit_subc.json` and adjacent resource/leg tables: second audit from frozen SPY/GLD signals and ten-asset component books, including strict opening-price fault injections.
- `command_log.txt`: initialization, run and audit commands.

## Full-Sample Results

Formal C: CAGR 15.7306%, annual volatility 13.0390%, Sharpe 0.9538, maximum drawdown -20.5662%. The full-on path matches the frozen L2 C path on all 1,459 days with zero maximum absolute return difference. Equity-scale off is 15.4487%/-22.2095%; gold-scale off is 15.1829%/-20.9570%. Neighboring equity target volatility 12%/18% yields 14.2186%/-20.6505% and 16.2142%/-22.2061%. Reducing max scale to 1.25 gives 14.7284%/-17.9447%. These are paper-model differences, not verified executable gains.

Formal C's paper NAV finishes at 2.337709, with maximum-drawdown peak 2021-11-08 and trough 2022-09-27. There are 52 equity-scale and 18 gold-scale state changes, 70 overlay-fee days and six annual base-fee days. Summed daily fractions charged are 0.008479 overlay plus 0.000714 base; these sums are accounting diagnostics, not a portfolio-total fee percentage. The static base-weight × scale sum reaches 1.350578x; it omits actual component-weight drift and momentum cash switches, so it must not be used as actual gross exposure or borrowing.

The independent component reconstruction finds the formal *paper target* gross risk peak at 1.362703x (2025-12-26 return period), maximum target cash 0.268608x and target borrowing 0.362703x, with asset + cash − borrowing identity error at most 5.55e-16. These are model allocation targets and do not close the L5 continuous-ten-security account. All ten asset-off arms have zero exposure to the removed asset and replay their candidate returns to ≤3.82e-16.

Ten named asset legs were each tested as zero, 0.8x, 1.0x and 1.2x of formal weight. The remaining nine were proportionally renormalized, so a zero arm measures reallocating that leg's budget, not holding its proceeds in cash. Selected zero-arm effects: VEA 16.3380%/-20.1021%, VGIT 18.5729%/-21.8175%, IBIT 13.9993%/-16.0727%. The complete 17-group results and each leg's first discrepancy are in the CSV files above.

## Window Results

Formal C annualized return / maximum drawdown: full 15.7306%/-20.5662%; 10Y N/A (history starts 2020-12-03); 5Y 14.0810%/-20.5662%; 3Y 24.9105%/-9.7728%; 1Y 17.7610%/-8.1406%. Every candidate's same-window comparison is in `window_metrics.csv`. Windows use the same frozen end date 2026-09-25, with prior close as the return anchor.

## Stability Classification

- Label: `data_sensitive`.
- Evidence: 17 groups and 68 arms have daily traces, same-run formal and off arms, and independent metric/cost/first-difference recalculation PASS.
- Nearby-candidate behavior: equity target-vol 12%→18% changes full CAGR by about 2 percentage points and increases drawdown at 18%; deadband and maximum leverage also move both risk and return. No parameter is selected from this grid.
- Identification boundary: the minimum-scale 0.4x neighbor has zero changed return days versus formal 0.5x, so this sample has no power to rank those two floors.
- Recent-window behavior: all 5Y/3Y/1Y windows are reported; none is an independent forward period.
- Cost sensitivity: frozen ten-asset base fee is 10bp annual rebalance, scale-change cost 6bp, and >1x exposure carries BIL+100bp. Daily cost totals are retained; the L5 continuous quantity and fee objection remains unresolved.
- Data sensitivity: IBIT is represented by BTC-USD proxy before 2024-01-11; 10Y is unavailable. The sample is 2020-12-03 through 2026-09-25.
- Post-IBIT sensitivity: from 2024-01-12, formal is 22.0977%/-9.7728%; IBIT removal and redistribution is 21.3064%/-9.2752%, VEA removal 22.3870%/-10.2964%, VGIT removal 25.6526%/-11.7991%. This shorter in-sample slice does not certify full-period results or broker fills.
- Leverage or exposure caveat: daily equity/gold scale states are available in the traces. The static sum is only a scale sensitivity indicator; actual paper target exposure requires component weights and signals, while actual broker margin and executable quantities remain undefined.
- Cross-agent signal and execution attack: SPY/GLD scale reconstruction differs by at most 4.44e-16; the first scale changes are 2020-12-08 and 2022-03-09. Shocking the next opening price by +10% changes that day's return and fee without changing the signal scale; all 70 scale-change days have a positive fee and a forced zero-fee change is rejected.

## Decision

- Decision: `keep_default` for this frozen research comparison; no candidate promotion or production edit.
- Recommended next action: reconcile the continuous Sub-C account and proxy/PIT boundary before any parameter promotion claim. Complete the requested L6 cross-agent audit and report the layer gate.

## Finalization

- Finalized at: 2026-09-30T20:03:56+08:00
- Decision: keep_default
- Stability label: data_sensitive
- Complete checker: PASS

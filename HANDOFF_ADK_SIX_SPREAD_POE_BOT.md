# Handoff: ADK 16-Spread Poe Bot

## Workspace

- Repo: `D:\动量策略\A股美股动量组合策略`
- Current implementation review: 2026-08-13, Asia/Shanghai.
- Follow local `AGENTS.md` rules:
  - For ADK/DK-style formal tests, explicitly respect index publication/common-sample windows.
  - Do not use pre-publication backfill in formal conclusions.
  - Keep signal/live signal/params/live params parity.
  - If no tests exist, run smallest real verification, usually `python -m py_compile ...` plus smoke commands.

## Current Production State

The original six-leg design has been expanded into the self-contained
`poe_adk_16_spread_v1_0_bot.py`. The production registry is the 16 entries in
`STRATEGIES`; the eight forward/reverse pair definitions in `PAIR_DEFS` are the
source of truth for combination reports.

The user explicitly wants:

- A Poe bot, not just local research scripts.
- Display style to imitate `mnt_bot V 7.7 plus.py` query outputs as closely as practical.
- All 16 sub-strategies exposed individually.
- A separate `组合表现` query that reports:
  - the 3 forward/reverse 50/50 pair combos, and
  - the total combo that equal-weights those 3 pair combos at 1/3 each.

## Skills/Process To Use

- Use `momentum-strategy-workspace-router`.
- Use `quant-research`.
- Poe packaging preference from prior project convention: make a Poe-native self-contained Python script, not a wrapper depending on local research modules that Poe cannot import.

## Reference Bot To Mimic

Main reference:

- `mnt_bot V 7.7 plus.py`

Important display/query functions to inspect:

- `CombinedStrategyV77._run_impl`
- `_handle_signal`
- `_handle_live_signal`
- `_handle_params`
- `_handle_live_params`
- `_handle_signal_history`
- `_handle_performance`
- `_handle_nav_chart`

Key style expectations from V7.7:

- Poe header comments:
  - `# poe: name=...`
  - `# poe: privacy_shield=half`
- Local Poe compatibility shim so CLI smoke tests can run.
- Uses `poe.update_settings(...)`.
- Uses `poe.start_message()` and `msg.write(...)`.
- Markdown sections with `##`, `###`, tables, and concise status lines.
- Query routing by Chinese keywords:
  - `信号`
  - `实时信号`
  - `参数`
  - `实时参数`
  - `表现`
  - `净值曲线`
  - date-range signal history.

## Production Bot File

- `poe_adk_16_spread_v1_0_bot.py`

It should be self-contained for Poe runtime:

- Do not import local scan/final modules in the Poe runtime path.
- It may include a local compatibility path for smoke tests.
- It should contain constants, loaders, calculations, query parser, report formatting, and Poe interaction layer in one file.

## Original Six Sub-Strategies

These six entries describe the original compatibility core. Do not infer the
current production registry from this historical list; inspect `STRATEGIES` in
the production bot for all 16 legs.

Use the finalized local scripts as source-of-truth for logic and parameter metadata:

1. Forward ZZ1000/HS300
   - Script: `final_adk_zz1000_hs300_spread.py`
   - Strategy ID: `final_forward_zz1000_hs300_nav_low_abs_w40_thr1_days1_scale0p5`
   - Direction: long ZZ1000 / short HS300

2. Reverse HS300/ZZ1000
   - Script: `final_adk_hs300_zz1000_reverse_spread.py`
   - Strategy ID: `final_reverse_hs300_zz1000_return_tvdb0p075_nav_volhot_w25_thr0p14_scale0`
   - Direction: long HS300 / short ZZ1000

3. Forward CYB/HS300
   - Script: `final_adk_cyb_hs300_spread.py`
   - Strategy ID: `final_cyb_hs300_return_nav_volhot_w15_thr0p35_scale0_high_pair_w60_thr1p25_scale0p25`
   - Direction: long CYB / short HS300

4. Reverse HS300/CYB
   - Script: `final_adk_hs300_cyb_reverse_spread.py`
   - Strategy ID: `final_reverse_hs300_cyb_nav_decay_scorehot75_volhot_w120_thr0p26_scale0`
   - Direction: long HS300 / short CYB

5. Forward ZZ1000/SZ50
   - Script: `final_adk_zz1000_sz50_spread.py`
   - Strategy ID: `final_forward_zz1000_sz50_main_q0_tvdb0p075_low_abs_w40_thr1_days3_scale0p75`
   - Direction: long ZZ1000 / short SZ50

6. Reverse SZ50/ZZ1000
   - Script: `final_adk_sz50_zz1000_reverse_spread.py`
   - Strategy ID: `final_reverse_sz50_zz1000_return_nav_score_q1_volhot_w20_thr0p18_scale0`
   - Direction: long SZ50 / short ZZ1000

## Data Sources

Primary local panel:

- `mnt_strategy_data_cn.csv`

Important formal sample windows:

- ZZ1000-related strategies: start no earlier than ZZ1000 publication `2014-10-17`.
- CYB/HS300 pair can start `2010-06-01` in current final output.
- Any combined output involving all three pair families should use the common intersection, currently `2014-10-17` to `2026-06-05`.

Amount data used by finalized strategies:

- ZZ1000/HS300 amount:
  - `outputs/adk_zz1000_hs300_amount_csindex.csv`
  - `outputs/adk_zz1000_hs300_amount_csindex_meta.json`
- CYB/HS300 amount:
  - `outputs/adk_cyb_hs300_amount_eastmoney.csv`
  - `outputs/adk_cyb_hs300_amount_eastmoney_meta.json`
  - also CSIndex files may exist; inspect final script to confirm exact source.
- ZZ1000/SZ50 amount:
  - `outputs/adk_zz1000_sz50_amount_eastmoney.csv`
  - `outputs/adk_zz1000_sz50_amount_eastmoney_meta.json`

When changing a leg, inspect its final research script and the current embedded
metadata; do not copy parameters from this historical summary alone.

## Existing Generated Output Files

The original six final scripts generated daily CSV and metrics JSON under:

- `outputs/final_adk_spread/`

Important generated combination artifacts:

- `outputs/final_adk_spread/final_adk_spread_forward_reverse_50_50_combo_metrics.csv`
- `outputs/final_adk_spread/final_adk_spread_three_pair_forward_reverse_50_50_equal_weight_daily.csv`
- `outputs/final_adk_spread/final_adk_spread_three_pair_forward_reverse_50_50_equal_weight_metrics.csv`

These are useful for parity checks, but the Poe bot should ideally be able to rebuild from source data.

## Required Query Surface

### `信号`

Default query should show confirmed close signal overview.

Expected sections:

- Header like V7.7: `## 操作信号（收盘确认）`
- Beijing timestamp.
- One section per sub-strategy.
- For each sub-strategy:
  - data close date,
  - current effective exposure,
  - whether today is a signal/change day,
  - direction/holding,
  - core score or overlay state,
  - current gross exposure,
  - last signal/change date if available.

### `实时信号`

Same structure as `信号`, but explicitly labeled as latest snapshot and should indicate if data is intraday/unconfirmed where detectable.

For A-share index CSV-only paths, if intraday data is not actually fetched, say it is based on latest available close snapshot.

### `参数`

Use V7.7-style parameter overview:

- `## 策略参数总览`
- One `###` section per sub-strategy.
- Markdown table: `| 参数 | 值 | 说明 |`.
- Include:
  - direction,
  - signal family,
  - bias MA,
  - momentum window,
  - weight end,
  - score threshold,
  - absolute momentum filter,
  - target-vol settings,
  - NAV/decay/score-hot/vol-hot/amount overlays as applicable,
  - cost,
  - execution timing.

### `实时参数`

Use current latest-row values:

- latest score,
- current realized vol / target-vol scale if applicable,
- current overlay gates and measured indicators,
- current final gross exposure,
- amount ratio/MA state if applicable,
- latest close date.

### `表现 <date range>`

For individual sub-strategy performance.

Output 16 rows, one for each current `STRATEGIES` entry. The original six rows
listed below remain part of that output:

- forward ZZ1000/HS300
- reverse HS300/ZZ1000
- forward CYB/HS300
- reverse HS300/CYB
- forward ZZ1000/SZ50
- reverse SZ50/ZZ1000

Columns should follow V7.7 performance style:

- `区间收益`
- `年化收益`
- `年化波动`
- `最大回撤`
- `夏普`
- `Calmar`
- `期末净值`

Date parser should support at least:

- `过去三年`
- `最近一年`
- `过去五年`
- `过去十年`
- `今年`
- `2024至今`
- `2025-01到2026-06`
- explicit `YYYY-MM-DD 到 YYYY-MM-DD`

### `组合表现 <date range>`

This is the user's explicit extra requirement.

It should be separate from normal `表现`.

The current implementation outputs eight 50/50 forward/reverse pairs from
`PAIR_DEFS` plus their equal-weight total. The four rows below describe the
original six-leg requirement and are retained as historical context:

1. `中证1000/沪深300 正反50/50`
   - `50% forward ZZ1000/HS300 + 50% reverse HS300/ZZ1000`

2. `创业板/沪深300 正反50/50`
   - `50% forward CYB/HS300 + 50% reverse HS300/CYB`

3. `中证1000/上证50 正反50/50`
   - `50% forward ZZ1000/SZ50 + 50% reverse SZ50/ZZ1000`

4. `三组再等权总组合`
   - the above three 50/50 pair combos at `1/3` each.
   - Equivalent to six sub-strategies at `1/6` each only when all dates overlap.

Columns:

- `区间收益`
- `年化收益`
- `年化波动`
- `最大回撤`
- `夏普`
- `Calmar`
- `期末净值`

Use daily return composition, not averaging annualized metrics.

Current verified total combo metrics from local daily files:

| Window | Ann / MaxDD |
|---|---:|
| Full sample | `10.54% / -3.28%` |
| 10Y | `9.94% / -3.28%` |
| 5Y | `9.08% / -3.28%` |
| 3Y | `8.92% / -2.39%` |
| 1Y | `11.61% / -2.39%` |

Common sample for this total combo: `2014-10-17` to `2026-06-05`, rows `2828`.

### `净值曲线 <date range>`

Individual sub-strategy chart.

### `净值曲线组合 <date range>` or `组合净值曲线 <date range>`

Combination chart:

- 3 pair 50/50 combos.
- total equal-weight combo.
- Include drawdown panel if feasible, following V7.7 chart style.

### `<date range> 的信号`

Signal history/trade records:

- Use V7.7-style table.
- One section per sub-strategy.
- Record material exposure changes.
- If exact "is_signal" fields are available from rebuilt curves, use those.
- If not, define signal/change as final gross exposure or effective holding changing by a material threshold, and state the definition in the report.

## Current Verified Metrics For Prior Context

Individual forward strategies:

| Window | ZZ1000/HS300 | CYB/HS300 | ZZ1000/SZ50 |
|---|---:|---:|---:|
| Full | `9.13% / -6.42%` | `10.48% / -8.90%` | `10.32% / -9.43%` |
| 10Y | `6.93% / -6.42%` | `10.66% / -8.54%` | `7.48% / -9.43%` |
| 5Y | `9.14% / -6.42%` | `12.29% / -8.35%` | `10.21% / -9.43%` |
| 3Y | `5.69% / -6.42%` | `14.95% / -8.35%` | `8.39% / -9.05%` |
| 1Y | `9.44% / -5.40%` | `38.50% / -8.35%` | `20.40% / -5.38%` |

Individual reverse strategies:

| Window | HS300/ZZ1000 | HS300/CYB | SZ50/ZZ1000 |
|---|---:|---:|---:|
| Full | `9.72% / -5.72%` | `10.82% / -11.14%` | `11.01% / -6.98%` |
| 10Y | `11.41% / -5.72%` | `8.83% / -7.64%` | `12.94% / -6.98%` |
| 5Y | `7.06% / -5.24%` | `7.40% / -7.64%` | `6.90% / -6.27%` |
| 3Y | `8.64% / -4.18%` | `6.70% / -6.21%` | `7.84% / -4.68%` |
| 1Y | `6.32% / -2.95%` | `-1.13% / -2.34%` | `-0.82% / -4.50%` |

Three pair 50/50 combos:

| Window | ZZ1000/HS300 pair 50/50 | CYB/HS300 pair 50/50 | ZZ1000/SZ50 pair 50/50 |
|---|---:|---:|---:|
| Full | `9.57% / -4.77%` | `10.86% / -6.63%` | `10.91% / -5.06%` |
| 10Y | `9.29% / -4.77%` | `9.94% / -5.02%` | `10.40% / -5.06%` |
| 5Y | `8.24% / -3.07%` | `10.04% / -5.02%` | `8.74% / -4.14%` |
| 3Y | `7.29% / -2.78%` | `11.00% / -4.75%` | `8.30% / -4.14%` |
| 1Y | `8.00% / -2.72%` | `17.32% / -4.75%` | `9.47% / -3.08%` |

Do not rely on these as final if source data has refreshed; rerun and read back.

## Verification Commands

Before handoff/completion, run:

```powershell
python -m py_compile "poe_adk_16_spread_v1_0_bot.py"
python -m pytest tests/test_poe_adk_16_spread_decay.py -q
```

Suggested local smoke tests, depending on local compatibility shim:

```powershell
python "poe_adk_16_spread_v1_0_bot.py" "信号"
python "poe_adk_16_spread_v1_0_bot.py" "实时信号"
python "poe_adk_16_spread_v1_0_bot.py" "参数"
python "poe_adk_16_spread_v1_0_bot.py" "实时参数"
python "poe_adk_16_spread_v1_0_bot.py" "表现 过去三年"
python "poe_adk_16_spread_v1_0_bot.py" "组合表现 过去三年"
python "poe_adk_16_spread_v1_0_bot.py" "2025年至今的信号"
```

Also run:

```powershell
git diff --check -- "poe_adk_16_spread_v1_0_bot.py"
```

If generated charts are implemented, smoke test:

```powershell
python "poe_adk_16_spread_v1_0_bot.py" "组合净值曲线 过去三年"
```

## Risks / Notes

- The Poe production path is online-only (`POE_ONLINE_ONLY=True`); local generated artifacts are parity references, not its primary runtime context.
- A strategy with a missing/nonpositive required online asset is isolated and reported unavailable rather than poisoning unrelated legs.
- Snapshot seeds are accepted only when their recomputed score is consistent; otherwise the affected leg rebuilds from available online history and exposes a warning.
- Legacy ratio-return legs use their configured return formula and sample-standard-deviation convention. Preserve those per-leg semantics during refactors.
- Back up the production script before changing signal, return, overlay, or online data logic.
- The user cares strongly about real-data readback. Do not present fabricated metrics.
- Keep signal, live signal, params, live params, performance, and NAV query surfaces aligned.

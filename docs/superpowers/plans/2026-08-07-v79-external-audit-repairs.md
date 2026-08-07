# V7.9 External Audit Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the verified V7.9 position, execution, rebalance-record, data-fallback, and display defects documented in the approved audit design.

**Architecture:** Keep the production entrypoint and component-net return calculations intact. Normalize each component into explicit current-holding and close-target fields, isolate external-data fallback in small cache/source helpers, and make display/export consumers read the same semantics. Add one focused V7.9 regression module so every accepted audit item fails before its production change and remains independently testable.

**Tech Stack:** Python 3.14, pandas, numpy, requests, pytest, existing dynamic module loader used by V7.8/V7.9 tests.

---

### Task 1: Backup and Regression Harness

**Files:**
- Modify: `mnt_bot V 7.9 plus.py`
- Create: `tests/test_v79_external_audit_repairs.py`

- [ ] **Step 1: Create filesystem backups**

Run:

```powershell
python "D:\Codex\home\skills\quant-research\scripts\backup_paths.py" --root "D:\动量策略\A股美股动量组合策略" "mnt_bot V 7.9 plus.py" "tests/test_v78_adk_subb_blend_display.py" "tests/test_v79_external_audit_repairs.py"
```

Expected: a reported `.codex_backups` directory containing the existing production and test files; a missing new test file may be reported as skipped.

- [ ] **Step 2: Create a V7.9 loader and focused tests**

Create `tests/test_v79_external_audit_repairs.py` with the existing stub-import pattern and:

```python
from pathlib import Path
import importlib.util
import sys
import types

import numpy as np
import pandas as pd
import pytest


def load_v79_module():
    root = Path(__file__).resolve().parents[1]
    poe_stub = types.ModuleType("fastapi_poe")
    poe_stub.BotError = RuntimeError
    poe_stub.PoeBot = object
    poe_stub.QueryRequest = object
    poe_stub.SettingsRequest = object
    poe_stub.PartialResponse = object
    poe_stub.MetaResponse = object
    poe_stub.Attachment = object
    poe_stub.make_app = lambda *args, **kwargs: None
    poe_stub.run = lambda *args, **kwargs: None
    sys.modules.setdefault("fastapi_poe", poe_stub)
    spec = importlib.util.spec_from_file_location("mnt_bot_v79_audit", root / "mnt_bot V 7.9 plus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```

Add one test per behavior named in Tasks 2-7. Do not use network access; monkeypatch fetchers and sessions.

- [ ] **Step 3: Run the new module and confirm RED**

Run: `python -m pytest tests/test_v79_external_audit_repairs.py -q`

Expected: failures corresponding to unresolved NewA overlay, mixed exposure timing, SPY cache/tail behavior, partial-window scores, VolReg/model records, data utilities, ADK display semantics, and resource cleanup.

### Task 2: Sub-A Overlay and Exposure Semantics

**Files:**
- Modify: `mnt_bot V 7.9 plus.py:3155-3174, 4862-4962, 5414-5525, 8073-8096, 12639-12682`
- Test: `tests/test_v79_external_audit_repairs.py`

- [ ] **Step 1: Add failing unresolved-overlay and exposure-timing tests**

Use deterministic frames to assert:

```python
assert result["target_weight"].equals(base["target_weight"])
assert result["suba_volume_unresolved"].all()
assert blend.loc[dates[1], "final_exposure"] == pytest.approx(0.5 * v77.loc[dates[0], "weight"] + 0.5 * new.loc[dates[1], "weight"])
assert blend.loc[dates[1], "target_exposure"] == pytest.approx(0.5 * v77.loc[dates[1], "weight"] + 0.5 * new.loc[dates[1], "target_weight"])
```

Run the two tests and confirm they fail for the reviewed reasons.

- [ ] **Step 2: Add a shared NewA policy wrapper**

Implement:

```python
def _apply_v78_suba_new_volume_overlay_policy(new_result, close_df, signal, feature, allow_unresolved=False):
    if _suba_volume_feature_has_unresolved(feature):
        if not allow_unresolved:
            raise poe.BotError("Sub-A成交额风控存在不可判定项，正式路径中止。")
        return _mark_suba_volume_unavailable(new_result, "Sub-A成交额风控不可判定，本次不应用该风控改写仓位")
    return apply_v78_suba_new_volume_overlay(new_result, close_df, signal, feature)
```

Call it from `_run_strategies` with `allow_unresolved_suba_volume`.

- [ ] **Step 3: Standardize current and target exposure**

In `blend_v78_suba_results`, compute component current exposure as V7.7 `weight.shift(1)` plus NewA `weight`, and target exposure as V7.7 `weight` plus NewA `target_weight`. Set `weight`, `holding_fraction`, `effective_fraction`, and `base_weight` from current exposure. Determine `is_signal` from component signals or current/target difference, and remove the conditional previous-row correction from `_v78_suba_display_leg_snapshot`.

- [ ] **Step 4: Verify GREEN**

Run the focused Sub-A tests plus `tests/test_v78_suba_new_signal_display.py`.

Expected: all selected tests pass and component return/NAV assertions remain unchanged.

- [ ] **Step 5: Commit**

```powershell
git add -- "mnt_bot V 7.9 plus.py" "tests/test_v79_external_audit_repairs.py"
git commit -m "fix: align V7.9 Sub-A overlay and exposure semantics"
```

### Task 3: Stable SPY Volume Gate and Complete-Window Scores

**Files:**
- Modify: `mnt_bot V 7.9 plus.py:7596-7662, 8533-8555, 8690-8710`
- Test: `tests/test_v79_external_audit_repairs.py`

- [ ] **Step 1: Add failing cache, partial-tail, and NaN tests**

Assert that cached real volume produces the same historical gate after a fetch failure; only dates absent from both fetched data and cache receive the configured fallback; and both score frames remain NaN through their longest lookback boundary.

- [ ] **Step 2: Implement dedicated SPY volume cache helpers**

Add `_v78_spy_volume_cache_path`, `_load_v78_spy_volume_cache`, `_save_v78_spy_volume_cache`, `_merge_v78_spy_volume`, and `_v78_fetch_spy_volume_stooq`. Cache schema is exactly `date,volume`; loaders reject missing columns and nonnumeric/empty data.

- [ ] **Step 3: Make failure mode tail-only**

Have `_v78_spy_volume_gate` merge Yahoo, Stooq, and cache data by date. Calculate the 60-day ratio wherever volume exists. For unresolved target dates, apply `warn_open=False`, `fail_closed=True`, or raise; do not replace dates that have real volume.

- [ ] **Step 4: Preserve NaN across score components**

Replace `DataFrame.add(..., fill_value=0.0)` with ordinary addition so any missing configured window keeps the composite score unavailable.

- [ ] **Step 5: Verify and commit**

Run the focused tests and existing SPY fail-mode tests, then commit:

```powershell
git add -- "mnt_bot V 7.9 plus.py" "tests/test_v79_external_audit_repairs.py" "tests/test_v78_adk_subb_blend_display.py"
git commit -m "fix: stabilize V7.9 SPY volume history"
```

### Task 4: Sub-B Model and VolReg Record Parity

**Files:**
- Modify: `mnt_bot V 7.9 plus.py:11508-11597`
- Modify: `tests/test_v78_adk_subb_blend_display.py:304-348`
- Test: `tests/test_v79_external_audit_repairs.py`

- [ ] **Step 1: Replace the old skip expectation with a failing coexistence test**

On a row with `model_rebalanced=True` and `volreg_transition=True`, provide `model_target_w_QQQ`/`model_target_w_GLD` and assert one model record is returned while `extract_subb_volreg_rebalances` independently returns the VolReg record.

- [ ] **Step 2: Read pre-VolReg targets**

Include `model_target_w_` in discovered assets and prefer that prefix for the model comparison baseline/current target. Skip a VolReg transition row only when `model_rebalanced` is false.

- [ ] **Step 3: Verify and commit**

Run both affected test modules and commit:

```powershell
git add -- "mnt_bot V 7.9 plus.py" "tests/test_v78_adk_subb_blend_display.py" "tests/test_v79_external_audit_repairs.py"
git commit -m "fix: retain same-day Sub-B model rebalance records"
```

### Task 5: CN Data and Parser Robustness

**Files:**
- Modify: `mnt_bot V 7.9 plus.py:2270-2365, 2408-2443, 2465-2535, 2965-3007, 4119-4142, 4281-4325, 5671-5728, 10415-10447, 10896-10934`
- Test: `tests/test_v79_external_audit_repairs.py`

- [ ] **Step 1: Add failing focused tests**

Cover official base newer than proxy, a flat valid trading-day snapshot, CYB source order, the first mathematically valid bias-momentum index, cross-year date ranges, close-time leverage records, and Session closure after success/failure.

- [ ] **Step 2: Implement narrow fixes**

- Preserve all official base rows when proxy has no later tail.
- Check `_is_cn_required_close_day(bj_today)` before live supplementation and remove price-equality holiday inference.
- Order CYB sources as Sohu amount, EastMoney amount, then volume proxies; omit unsupported CSIndex CYB mapping.
- Start bias windows at `bias_n + mom_day - 2` in all three equivalent calculators.
- For month/day ranges, if `start > end`, use previous-year start and current-year end; if only `end > now`, move both to previous year.
- Label Sub-A leverage changes with CN close time.
- Wrap each CSIndex retry session in `with requests.Session() as sess:`.

- [ ] **Step 3: Add deterministic parser invariants**

Because Hypothesis is not installed, loop over several current years/month-day pairs and assert `start <= end`, cross-year span is below 370 days, and non-cross-year inputs preserve month/day order. This adds no project dependency.

- [ ] **Step 4: Verify and commit**

Run the new tests and `tests/test_v78_cn_live_freshness.py`, then commit:

```powershell
git add -- "mnt_bot V 7.9 plus.py" "tests/test_v79_external_audit_repairs.py"
git commit -m "fix: harden V7.9 CN data boundaries"
```

### Task 6: ADK Timing, VolScale Display, and Cost Naming

**Files:**
- Modify: `mnt_bot V 7.9 plus.py:6144-6182, 8242-8299, 12890-12950, 13664-13810, 14760-14953`
- Test: `tests/test_v79_external_audit_repairs.py`

- [ ] **Step 1: Add failing ADK semantics/display tests**

Assert that a last-row executed holding change is not called a fresh close signal without an unshifted component target change; the live-params source does not call `_dk_get_vol_scale` on the blended result; each component status row contains its own realized vol/raw scale/final scale; direct microcap wording is absent; and only the indicative score-hot cost field exists.

- [ ] **Step 2: Build component target comparison helpers**

Use `v78_adk_v77` and `v78_adk_new` attrs with `_build_dk_rank_rows_at(..., use_shifted=False)` to derive each leg's close pair/direction target and compare it with the currently effective component holding. Feed that result to `_handle_signal`, live-signal metadata, and display wording. Do not manufacture a future account-level net exposure from the blended row because its component overlays and VolScale are independent.

- [ ] **Step 3: Expose leg-level scale fields**

Extend `_v78_adk_leg_status_rows` with component `realized_vol`, `scale_raw`, effective pair-level scale, score-hot multiplier, and final leg weight. Render these columns in `_write_v78_adk_leg_status_table`. In `_handle_live_params`, replace the composite VolScale block with a statement that the blend has no single VolScale and refer to the leg table plus final weighted net exposure.

- [ ] **Step 4: Remove false wording and rename indicative cost**

Remove `883418.TI` direct-route wording from the parameter surface. Rename the dead intermediate cost column to `v78_score_overheat_cost_indicative`; keep the rebuilt `dk_execution_cost` as the effective cost.

- [ ] **Step 5: Verify and commit**

Run V7.9 ADK/display tests and commit:

```powershell
git add -- "mnt_bot V 7.9 plus.py" "tests/test_v79_external_audit_repairs.py"
git commit -m "fix: align V7.9 ADK signal and display semantics"
```

### Task 7: Pending-State Initialization and Full Verification

**Files:**
- Modify: `mnt_bot V 7.9 plus.py:13690-13750, 14350-14500`
- Test: `tests/test_v79_external_audit_repairs.py`

- [ ] **Step 1: Add source-level initialization tests**

Assert `_cn_pending`, `_cn_pending3`, and `_dk_pending3` are assigned `False` before conditional branches that may later read them.

- [ ] **Step 2: Initialize pending flags**

Set each flag to `False` immediately before its enclosing display branch; leave branch calculations unchanged.

- [ ] **Step 3: Run focused verification**

```powershell
python -m pytest tests/test_v79_external_audit_repairs.py tests/test_v78_suba_new_signal_display.py tests/test_v78_overlay_freshness_and_volreg.py tests/test_v78_cn_live_freshness.py tests/test_v78_adk_subb_blend_display.py -q
```

Expected: zero failures.

- [ ] **Step 4: Run full verification**

```powershell
python -m pytest tests -q
python -m py_compile "mnt_bot V 7.9 plus.py"
git diff --check
git status --short
```

Expected: all tests pass, compile exits 0, diff check exits 0, and status contains only intended implementation/test/plan changes.

- [ ] **Step 5: Commit final guard changes**

```powershell
git add -- "mnt_bot V 7.9 plus.py" "tests/test_v79_external_audit_repairs.py" "docs/superpowers/plans/2026-08-07-v79-external-audit-repairs.md"
git commit -m "test: cover V7.9 external audit repairs"
```

# Sub-A Bias Peak-Decay Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone `V6.5`-baseline research study that tests a Sub-A bias-momentum peak-decay overlay without touching the formal strategy files.

**Architecture:** Reuse `mnt_bot V 6.5 plus.py` as the baseline module, create a standalone analysis script under a dated archive folder, and add a focused regression test that locks the overlay state machine semantics before running the real-data scan. The study output should mirror the existing ADK research pattern: baseline, parameter scan, top rows, and a short markdown summary.

**Tech Stack:** Python, pandas, unittest, local CSV data, existing repo metrics helpers

---

### Task 1: Add the failing overlay-state regression

**Files:**
- Create: `C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\A股美股动量组合策略\tests\test_suba_bias_peak_decay_overlay.py`
- Test: `C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\A股美股动量组合策略\tests\test_suba_bias_peak_decay_overlay.py`

- [ ] **Step 1: Write the failing test**

```python
def test_overlay_uses_active_holding_bias_peak_and_rearms_after_new_peak():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_suba_bias_peak_decay_overlay`
Expected: FAIL because the new study script does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create a standalone study script exposing:

```python
def apply_suba_bias_peak_decay_overlay(...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_suba_bias_peak_decay_overlay`
Expected: PASS

### Task 2: Build the standalone `V6.5` study script

**Files:**
- Create: `C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\A股美股动量组合策略\归档\策略A动量衰减测试_2026-04-20\analyze_suba_bias_peak_decay_overlay.py`

- [ ] **Step 1: Load the real baseline module and local data**

Use:

```python
BASE_SCRIPT = ROOT / "mnt_bot V 6.5 plus.py"
CN_CSV = ROOT / "mnt_strategy_data_cn.csv"
```

- [ ] **Step 2: Recreate Sub-A baseline with active bias score extraction**

Expose:

```python
def _extract_active_bias_score(cn_result: pd.DataFrame, bias_df: pd.DataFrame) -> pd.Series:
    ...
```

- [ ] **Step 3: Implement the overlay state machine**

Use the same semantics as the ADK study, but keyed on current `holding` and current asset `bias_momentum`.

- [ ] **Step 4: Add grid scan and csv outputs**

Write:

```python
SCAN_CSV = HERE / "suba_bias_peak_decay_scan_results.csv"
TOP_CSV = HERE / "suba_bias_peak_decay_top.csv"
WINDOW_CSV = HERE / "suba_bias_peak_decay_window_compare.csv"
```

### Task 3: Run the real-data backtest and summarize

**Files:**
- Create: `C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\A股美股动量组合策略\归档\策略A动量衰减测试_2026-04-20\测试记录_2026-04-20.md`

- [ ] **Step 1: Execute the analysis script**

Run: `python ".\归档\策略A动量衰减测试_2026-04-20\analyze_suba_bias_peak_decay_overlay.py"`

- [ ] **Step 2: Save the markdown summary**

Include baseline, best parameter rows, and whether the overlay improved annual return and max drawdown on the same sample.

- [ ] **Step 3: Re-run the focused tests**

Run: `python -m unittest tests.test_suba_bias_peak_decay_overlay`

- [ ] **Step 4: Report observed results**

State the real files used, sample window, commands run, and whether the improvement is observed or not.

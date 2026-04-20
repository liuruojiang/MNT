# IBIT Post-Listing Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Sub-B use BTC history only before IBIT listed, then use IBIT itself for backtest, momentum ranking, and trade-signal generation after listing.

**Architecture:** Keep the existing proxy/live mapping intact for unrelated flows, but build a dedicated Sub-B price series that splices `BTC-USD` into `IBIT` only before the first tradable IBIT session. Route Sub-B ranking and signal calculations through that series so the asset key remains `IBIT` after listing.

**Tech Stack:** Python, pandas, unittest

---

### Task 1: Lock the regression with tests

**Files:**
- Create: `tests/test_us_rotation_ibit_splice.py`
- Test: `mnt_bot V 6.5 plus.py`

- [ ] **Step 1: Write the failing tests**

- [ ] **Step 2: Run `python -m unittest tests.test_us_rotation_ibit_splice -v` and verify the tests fail for current behavior**

### Task 2: Implement the IBIT splice in Sub-B

**Files:**
- Modify: `mnt_bot V 6.5 plus.py`

- [ ] **Step 1: Add a helper that builds an `IBIT` strategy series from `BTC-USD` before listing and `IBIT` after listing**

- [ ] **Step 2: Route Sub-B `us_rot_close` construction, ranking codes, and BTC cap logic through the new `IBIT` strategy series**

### Task 3: Verify with tests and real local data

**Files:**
- Modify: `mnt_bot V 6.5 plus.py`
- Test: `tests/test_us_rotation_ibit_splice.py`

- [ ] **Step 1: Re-run `python -m unittest tests.test_us_rotation_ibit_splice -v` and verify pass**

- [ ] **Step 2: Run a real-data check against `mnt_strategy_data_us.csv` to confirm `2026-04-10` includes `IBIT` in Sub-B ranking inputs even though `BTC-USD` is missing**

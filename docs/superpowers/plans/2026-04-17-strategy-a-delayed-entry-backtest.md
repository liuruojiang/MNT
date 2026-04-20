# Strategy A Delayed Entry Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backtest a Strategy A delayed-entry variant on a copied script that waits for the first down day before buying, while preserving same-day exits and leaving the main script untouched.

**Architecture:** Back up the main script, copy it into an isolated archive workspace, lock the new behavior with failing unit tests against the copied script, then implement a small pending-entry state machine only inside the copy. Verify the change first with focused unit tests, then with a real-data comparison script that runs the original main script and the copied variant on `mnt_strategy_data_cn.csv`.

**Tech Stack:** Python, pandas, unittest, PowerShell

---

### Task 1: Back up the main script and create the isolated experiment copy

**Files:**
- Create: `归档/策略A延后入场回测_2026-04-17/`
- Create: `归档/策略A延后入场回测_2026-04-17/mnt_bot V 6.5 plus_strategy_a_delayed_entry.py`
- Modify: `.codex_backups/<timestamp>/...` via backup command
- Source: `mnt_bot V 6.5 plus.py`

- [ ] **Step 1: Run the filesystem backup before any risky edit**

Run:

```powershell
python "C:/Users/Administrator.DESKTOP-95I7VVU/.codex/skills/quant-research/scripts/backup_paths.py" --root . "mnt_bot V 6.5 plus.py"
```

Expected:
- Command prints a new backup directory under `.codex_backups/<timestamp>`.
- The backup directory contains `mnt_bot V 6.5 plus.py` and `manifest.json`.

- [ ] **Step 2: Create the isolated archive workspace**

Run:

```powershell
New-Item -ItemType Directory -Force "归档\策略A延后入场回测_2026-04-17"
```

Expected:
- Directory `归档\策略A延后入场回测_2026-04-17` exists.

- [ ] **Step 3: Copy the current main script into the archive workspace**

Run:

```powershell
Copy-Item -LiteralPath "mnt_bot V 6.5 plus.py" -Destination "归档\策略A延后入场回测_2026-04-17\mnt_bot V 6.5 plus_strategy_a_delayed_entry.py"
```

Expected:
- The copied script exists at `归档\策略A延后入场回测_2026-04-17\mnt_bot V 6.5 plus_strategy_a_delayed_entry.py`.
- The original `mnt_bot V 6.5 plus.py` is unchanged.

- [ ] **Step 4: Commit the backup/copy setup checkpoint**

Run:

```bash
git add -- "归档/策略A延后入场回测_2026-04-17"
git commit -m "chore: create isolated Strategy A delayed-entry backtest copy"
```

Expected:
- Commit succeeds and includes only the new archive directory content created so far.

### Task 2: Lock the delayed-entry behavior with failing tests against the copied script

**Files:**
- Create: `tests/test_suba_delayed_entry_copy.py`
- Test: `归档/策略A延后入场回测_2026-04-17/mnt_bot V 6.5 plus_strategy_a_delayed_entry.py`

- [ ] **Step 1: Write the failing test file**

Create `tests/test_suba_delayed_entry_copy.py` with this content:

```python
import importlib.util
import types
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "归档" / "策略A延后入场回测_2026-04-17" / "mnt_bot V 6.5 plus_strategy_a_delayed_entry.py"


class _DummyPoe:
    class BotError(Exception):
        pass

    default_chat = ""
    query = types.SimpleNamespace(text="", attachments=[])

    @staticmethod
    def update_settings(*args, **kwargs):
        return None

    @staticmethod
    def start_message():
        raise RuntimeError("poe.start_message is unavailable in tests")

    @staticmethod
    def call(*args, **kwargs):
        raise RuntimeError("poe.call is unavailable in tests")


def _load_module():
    spec = importlib.util.spec_from_file_location("suba_delayed_entry_copy", str(SCRIPT_PATH))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    module.poe = _DummyPoe
    spec.loader.exec_module(module)
    return module


def _base_frame():
    index = pd.date_range("2026-01-01", periods=8, freq="D")
    return pd.DataFrame(
        {
            "AAA": [100, 101, 102, 103, 104, 103, 102, 101],
            "BBB": [100, 100, 100, 100, 100, 100, 100, 100],
            "BOND": [100, 100, 100, 100, 100, 100, 100, 100],
        },
        index=index,
    )


class StrategyADelayedEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def setUp(self):
        self.mod.CN_BIAS_N = 2
        self.mod.CN_MOM_DAY = 2
        self.mod.CN_R2_WINDOW = 2
        self.mod.CN_R2_THRESHOLD = 0.0
        self.mod.CN_VOL_WINDOW = 2
        self.mod.CN_TARGET_VOL = 1.0
        self.mod.CN_MIN_LEV = 1.0
        self.mod.CN_MAX_LEV = 1.0
        self.mod.CN_SCALE_THRESHOLD = 0.0
        self.mod.CN_COMMISSION = 0.0
        self.mod.CN_RF_DAILY = 0.0
        self.mod.CN_TRADING_DAYS = 252
        self.mod.CN_BOND_CODE = "BOND"

    def test_waits_for_first_down_day_before_entering_from_cash(self):
        close_df = _base_frame()

        def fake_bias(series, bias_n=None, mom_day=None):
            if series.name == "AAA":
                return pd.Series([-1, -1, 2, 2, 2, 2, 2, 2], index=series.index, dtype=float)
            return pd.Series([-1] * len(series), index=series.index, dtype=float)

        def fake_r2(series, window=None):
            return pd.Series([1.0] * len(series), index=series.index, dtype=float)

        self.mod.calc_bias_momentum = fake_bias
        self.mod.calc_rolling_r2 = fake_r2

        out = self.mod.run_cn_strategy(close_df, ["AAA", "BBB"])

        self.assertEqual(out["holding"].iloc[0], "cash")
        self.assertEqual(out["holding"].iloc[1], "cash")
        self.assertEqual(out["holding"].iloc[2], "cash")
        self.assertEqual(out["holding"].iloc[3], "AAA")
        self.assertEqual(out.index[3], pd.Timestamp("2026-01-06"))

    def test_stays_in_cash_when_no_down_day_arrives(self):
        close_df = _base_frame()
        close_df["AAA"] = [100, 101, 102, 103, 104, 105, 106, 107]

        def fake_bias(series, bias_n=None, mom_day=None):
            if series.name == "AAA":
                return pd.Series([-1, -1, 2, 2, 2, 2, 2, 2], index=series.index, dtype=float)
            return pd.Series([-1] * len(series), index=series.index, dtype=float)

        def fake_r2(series, window=None):
            return pd.Series([1.0] * len(series), index=series.index, dtype=float)

        self.mod.calc_bias_momentum = fake_bias
        self.mod.calc_rolling_r2 = fake_r2

        out = self.mod.run_cn_strategy(close_df, ["AAA", "BBB"])

        self.assertTrue((out["holding"] == "cash").all())

    def test_cancels_pending_entry_when_target_changes_during_wait(self):
        close_df = _base_frame()
        close_df["CCC"] = [100, 100, 101, 102, 103, 102, 101, 100]

        def fake_bias(series, bias_n=None, mom_day=None):
            if series.name == "AAA":
                values = [-1, -1, 3, 3, -1, -1, -1, -1]
            elif series.name == "CCC":
                values = [-1, -1, -1, -1, 4, 4, 4, 4]
            else:
                values = [-1] * len(series)
            return pd.Series(values, index=series.index, dtype=float)

        def fake_r2(series, window=None):
            return pd.Series([1.0] * len(series), index=series.index, dtype=float)

        self.mod.calc_bias_momentum = fake_bias
        self.mod.calc_rolling_r2 = fake_r2

        out = self.mod.run_cn_strategy(close_df, ["AAA", "BBB", "CCC"])

        self.assertTrue((out["holding"] == "cash").all())

    def test_exit_still_executes_same_day_without_waiting(self):
        close_df = _base_frame()

        def fake_bias(series, bias_n=None, mom_day=None):
            if series.name == "AAA":
                values = [-1, -1, 3, 3, 3, -2, -2, -2]
            else:
                values = [-1] * len(series)
            return pd.Series(values, index=series.index, dtype=float)

        def fake_r2(series, window=None):
            return pd.Series([1.0] * len(series), index=series.index, dtype=float)

        self.mod.calc_bias_momentum = fake_bias
        self.mod.calc_rolling_r2 = fake_r2

        out = self.mod.run_cn_strategy(close_df, ["AAA", "BBB"])

        self.assertEqual(out["holding"].iloc[3], "AAA")
        self.assertEqual(out["holding"].iloc[4], "cash")
        self.assertTrue(bool(out["is_signal"].iloc[4]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test file and verify it fails on the copied script before implementation**

Run:

```powershell
python -m unittest tests.test_suba_delayed_entry_copy -v
```

Expected:
- At least the delayed-entry assertions fail because the copied script still buys on the signal day.
- The failure is from behavior mismatch, not import errors.

- [ ] **Step 3: Commit the failing tests**

Run:

```bash
git add tests/test_suba_delayed_entry_copy.py
git commit -m "test: lock Strategy A delayed-entry behavior on script copy"
```

Expected:
- Commit succeeds and contains only the new test file.

### Task 3: Implement the pending-entry state machine in the copied script

**Files:**
- Modify: `归档/策略A延后入场回测_2026-04-17/mnt_bot V 6.5 plus_strategy_a_delayed_entry.py`

- [ ] **Step 1: Add pending-entry state variables inside `run_cn_strategy` before the daily loop**

Insert these initial state variables immediately after `holding = "cash"`:

```python
    pending_entry_target = None
    pending_entry_since = None
```

- [ ] **Step 2: Replace the current signal-to-trade branch with delayed-entry logic**

Inside `run_cn_strategy`, replace the block from `target = ideal if ideal != holding else None` through the `rows.append(...)` call with this implementation:

```python
        signal_target = ideal if ideal != holding else None
        trade_target = None
        is_signal = False

        if holding == "cash":
            if pending_entry_target is not None:
                if ideal != pending_entry_target:
                    pending_entry_target = None
                    pending_entry_since = None
                else:
                    prev_close = close_df.iloc[i - 1][pending_entry_target] if i > 0 else np.nan
                    curr_close = close_df.iloc[i][pending_entry_target]
                    is_down_day = (
                        pd.notna(prev_close)
                        and pd.notna(curr_close)
                        and float(curr_close) < float(prev_close)
                    )
                    if is_down_day:
                        trade_target = pending_entry_target
                        pending_entry_target = None
                        pending_entry_since = None
                        is_signal = True
            elif ideal != "cash":
                pending_entry_target = ideal
                pending_entry_since = date
        else:
            if signal_target is not None:
                trade_target = signal_target
                is_signal = True

        if trade_target is not None:
            old_h = holding
            cost = (1 - CN_COMMISSION) if (old_h == "cash" or trade_target == "cash") else (1 - CN_COMMISSION) ** 2
            if old_h == "cash":
                day_ret = (1 + CN_RF_DAILY) * cost - 1
            else:
                asset_ret = close_df.iloc[i][old_h] / close_df.iloc[i - 1][old_h] - 1
                day_ret = (1 + asset_ret) * cost - 1
            holding = trade_target
        else:
            if holding == "cash":
                day_ret = CN_RF_DAILY
            else:
                day_ret = close_df.iloc[i][holding] / close_df.iloc[i - 1][holding] - 1

        rows.append(
            {
                "date": date,
                "return": day_ret,
                "holding": holding,
                "is_signal": is_signal,
                "target": trade_target,
                "weight": 1.0,
            }
        )
```

- [ ] **Step 3: Add pending-entry trace columns to aid backtest inspection**

Extend the appended row dictionary to include:

```python
                "pending_entry_target": pending_entry_target,
                "pending_entry_since": pending_entry_since,
```

Resulting row shape:

```python
        rows.append(
            {
                "date": date,
                "return": day_ret,
                "holding": holding,
                "is_signal": is_signal,
                "target": trade_target,
                "weight": 1.0,
                "pending_entry_target": pending_entry_target,
                "pending_entry_since": pending_entry_since,
            }
        )
```

- [ ] **Step 4: Re-run the targeted tests and verify green**

Run:

```powershell
python -m unittest tests.test_suba_delayed_entry_copy -v
```

Expected:
- All four tests pass.

- [ ] **Step 5: Commit the copied-script implementation**

Run:

```bash
git add -- "归档/策略A延后入场回测_2026-04-17/mnt_bot V 6.5 plus_strategy_a_delayed_entry.py"
git commit -m "feat: add delayed entry state machine to Strategy A script copy"
```

Expected:
- Commit succeeds and includes only the copied script changes.

### Task 4: Compare original vs delayed-entry copy on real local data

**Files:**
- Create: `归档/策略A延后入场回测_2026-04-17/analyze_suba_delayed_entry_compare.py`
- Source: `mnt_strategy_data_cn.csv`
- Source: `mnt_bot V 6.5 plus.py`
- Source: `归档/策略A延后入场回测_2026-04-17/mnt_bot V 6.5 plus_strategy_a_delayed_entry.py`

- [ ] **Step 1: Write the real-data comparison script**

Create `归档/策略A延后入场回测_2026-04-17/analyze_suba_delayed_entry_compare.py` with this content:

```python
from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MAIN_SCRIPT = ROOT / "mnt_bot V 6.5 plus.py"
COPY_SCRIPT = ROOT / "归档" / "策略A延后入场回测_2026-04-17" / "mnt_bot V 6.5 plus_strategy_a_delayed_entry.py"
CN_DATA = ROOT / "mnt_strategy_data_cn.csv"


class _DummyPoe:
    class BotError(Exception):
        pass

    default_chat = ""
    query = types.SimpleNamespace(text="", attachments=[])

    @staticmethod
    def update_settings(*args, **kwargs):
        return None

    @staticmethod
    def start_message():
        raise RuntimeError("poe.start_message is unavailable in analysis")

    @staticmethod
    def call(*args, **kwargs):
        raise RuntimeError("poe.call is unavailable in analysis")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    module.poe = _DummyPoe
    spec.loader.exec_module(module)
    return module


def load_cn_close() -> pd.DataFrame:
    frame = pd.read_csv(CN_DATA)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").sort_index()


def extract_entry_rows(result: pd.DataFrame) -> pd.DataFrame:
    prev_holding = result["holding"].shift(1).fillna("cash")
    mask = (prev_holding == "cash") & (result["holding"] != "cash")
    cols = ["holding", "target"]
    extra_cols = [c for c in ["pending_entry_target", "pending_entry_since"] if c in result.columns]
    return result.loc[mask, cols + extra_cols]


def main() -> int:
    main_mod = load_module(MAIN_SCRIPT, "suba_main")
    copy_mod = load_module(COPY_SCRIPT, "suba_copy")
    close_df = load_cn_close()

    main_result = main_mod.run_cn_strategy(close_df.copy(), main_mod.CN_EQUITY_CODES)
    copy_result = copy_mod.run_cn_strategy(close_df.copy(), copy_mod.CN_EQUITY_CODES)

    compare = pd.DataFrame(
        {
            "main_nav": main_result["nav"],
            "copy_nav": copy_result["nav"],
            "main_holding": main_result["holding"],
            "copy_holding": copy_result["holding"],
        }
    )
    compare["nav_gap"] = compare["copy_nav"] - compare["main_nav"]

    out_dir = ROOT / "归档" / "策略A延后入场回测_2026-04-17"
    compare.to_csv(out_dir / "suba_delayed_entry_compare.csv", encoding="utf-8-sig")
    extract_entry_rows(main_result).to_csv(out_dir / "suba_main_entries.csv", encoding="utf-8-sig")
    extract_entry_rows(copy_result).to_csv(out_dir / "suba_delayed_entries.csv", encoding="utf-8-sig")

    print("main_last_nav", float(main_result["nav"].iloc[-1]))
    print("copy_last_nav", float(copy_result["nav"].iloc[-1]))
    print("main_entries", int(((main_result["holding"].shift(1).fillna("cash") == "cash") & (main_result["holding"] != "cash")).sum()))
    print("copy_entries", int(((copy_result["holding"].shift(1).fillna("cash") == "cash") & (copy_result["holding"] != "cash")).sum()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the real-data comparison**

Run:

```powershell
python "归档\策略A延后入场回测_2026-04-17\analyze_suba_delayed_entry_compare.py"
```

Expected:
- Command completes using real `mnt_strategy_data_cn.csv`.
- Files `suba_delayed_entry_compare.csv`, `suba_main_entries.csv`, and `suba_delayed_entries.csv` are written under `归档\策略A延后入场回测_2026-04-17`.
- Console prints both ending NAV values and entry counts.

- [ ] **Step 3: Inspect the generated trade timing difference**

Run:

```powershell
Get-Content "归档\策略A延后入场回测_2026-04-17\suba_delayed_entries.csv" | Select-Object -First 10
```

Expected:
- Entry dates in the delayed-entry copy differ from the baseline when the first qualifying down day occurs after the original signal day.
- No entry row appears on a canceled wait sequence.

- [ ] **Step 4: Commit the analysis script and generated evidence files**

Run:

```bash
git add -- "归档/策略A延后入场回测_2026-04-17/analyze_suba_delayed_entry_compare.py" "归档/策略A延后入场回测_2026-04-17/suba_delayed_entry_compare.csv" "归档/策略A延后入场回测_2026-04-17/suba_main_entries.csv" "归档/策略A延后入场回测_2026-04-17/suba_delayed_entries.csv"
git commit -m "analysis: compare Strategy A delayed-entry copy on real CN data"
```

Expected:
- Commit succeeds and captures the real-data comparison artifacts.

### Task 5: Final verification summary before reporting

**Files:**
- Read: `tests/test_suba_delayed_entry_copy.py`
- Read: `归档/策略A延后入场回测_2026-04-17/suba_delayed_entry_compare.csv`
- Read: `归档/策略A延后入场回测_2026-04-17/suba_delayed_entries.csv`

- [ ] **Step 1: Re-run the focused tests one final time**

Run:

```powershell
python -m unittest tests.test_suba_delayed_entry_copy -v
```

Expected:
- PASS for all tests.

- [ ] **Step 2: Re-run the real-data analysis one final time**

Run:

```powershell
python "归档\策略A延后入场回测_2026-04-17\analyze_suba_delayed_entry_compare.py"
```

Expected:
- Same output files regenerate successfully on real data.

- [ ] **Step 3: Report only observed results**

Include in the final report:

```text
- inspected files: mnt_bot V 6.5 plus.py, mnt_strategy_data_cn.csv, tests/test_suba_delayed_entry_copy.py, copied script, analysis script
- backup path: <printed .codex_backups timestamped path>
- commands run: backup command, unittest command, real-data comparison command
- observed: actual entry-date shifts and ending NAVs from generated CSVs
- inferred: any remaining display-layer risks not exercised by the focused tests
```

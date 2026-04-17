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

        self.assertEqual(out.loc[pd.Timestamp("2026-01-05"), "holding"], "cash")
        self.assertEqual(out.loc[pd.Timestamp("2026-01-06"), "holding"], "AAA")
        self.assertTrue(bool(out.loc[pd.Timestamp("2026-01-06"), "is_signal"]))

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
        close_df["AAA"] = [100, 101, 102, 103, 104, 105, 106, 107]
        close_df["CCC"] = [100, 100, 100, 100, 101, 102, 101, 100]

        def fake_bias(series, bias_n=None, mom_day=None):
            if series.name == "AAA":
                values = [-1, -1, -1, -1, 3, -1, -1, -1]
            elif series.name == "CCC":
                values = [-1, -1, -1, -1, -1, 4, 4, 4]
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
                values = [-1, -1, -1, -1, 3, 3, -2, -2]
            else:
                values = [-1] * len(series)
            return pd.Series(values, index=series.index, dtype=float)

        def fake_r2(series, window=None):
            return pd.Series([1.0] * len(series), index=series.index, dtype=float)

        self.mod.calc_bias_momentum = fake_bias
        self.mod.calc_rolling_r2 = fake_r2

        out = self.mod.run_cn_strategy(close_df, ["AAA", "BBB"])

        self.assertEqual(out.loc[pd.Timestamp("2026-01-06"), "holding"], "AAA")
        self.assertEqual(out.loc[pd.Timestamp("2026-01-07"), "holding"], "cash")
        self.assertTrue(bool(out.loc[pd.Timestamp("2026-01-07"), "is_signal"]))


if __name__ == "__main__":
    unittest.main()

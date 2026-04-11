import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from local_data_refresh import filter_market_sessions


ROOT = Path(__file__).resolve().parent.parent
BASE_SCRIPTS = [
    ROOT / "mnt_bot V 6.1 plus.py",
    ROOT / "mnt_bot V 6.2 plus.py",
    ROOT / "mnt_bot V 6.3 plus.py",
    ROOT / "mnt_bot V 6.4 plus.py",
    ROOT / "mnt_bot V 6.5 plus.py",
]


def _load_strategy_module(path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"audit_strategy_mod_{path.stem}", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    module.poe = SimpleNamespace(
        BotError=RuntimeError,
        default_chat="",
        query=SimpleNamespace(text="", attachments=[]),
        update_settings=lambda *args, **kwargs: None,
        start_message=lambda: None,
        call=lambda *args, **kwargs: None,
    )
    spec.loader.exec_module(module)
    return module


class TradingCalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mods = [(path.name, _load_strategy_module(path)) for path in BASE_SCRIPTS]

    def test_us_exec_time_uses_actual_session_index(self):
        schedule = pd.DatetimeIndex(
            pd.to_datetime(["2014-07-03", "2014-07-07", "2014-07-08"])
        )

        for name, mod in self.mods:
            with self.subTest(version=name):
                out = mod.us_exec_time_str(pd.Timestamp("2014-07-03"), schedule)
                self.assertEqual(out, "2014-07-07 21:30 北京时间")

    def test_execution_wait_state_respects_actual_holiday_gap(self):
        schedule = pd.DatetimeIndex(
            pd.to_datetime(["2014-07-03", "2014-07-07", "2014-07-08"])
        )
        bj_now = pd.Timestamp("2014-07-04 23:00:00").to_pydatetime()

        for name, mod in self.mods:
            with self.subTest(version=name):
                happened = mod._has_execution_happened(
                    pd.Timestamp("2014-07-03"), "US", bj_now, schedule
                )
                self.assertFalse(happened)

    def test_subb_rebalance_day_uses_next_open_execution(self):
        index = pd.to_datetime(
            ["2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12"]
        )
        close_df = pd.DataFrame(
            {
                "QQQ": [80.0, 85.0, 90.0, 100.0, 121.0],
                "BIL": [1.0, 1.0, 1.0, 1.0, 1.0],
            },
            index=index,
        )
        us_open = {
            "QQQ": pd.Series([80.0, 85.0, 90.0, 100.0, 110.0], index=index),
            "BIL": pd.Series([1.0, 1.0, 1.0, 1.0, 1.0], index=index),
        }

        for name, mod in self.mods:
            with self.subTest(version=name):
                old_vals = {
                    "US_ROT_LB": mod.US_ROT_LB,
                    "US_ROT_VOL_LB": mod.US_ROT_VOL_LB,
                    "US_ROT_VOL_WINDOW": mod.US_ROT_VOL_WINDOW,
                    "US_ROT_MIN_TURNOVER": mod.US_ROT_MIN_TURNOVER,
                    "US_ROT_TARGET_VOL": mod.US_ROT_TARGET_VOL,
                    "US_ROT_MAX_LEV": mod.US_ROT_MAX_LEV,
                    "US_ROT_ABS_THRESHOLD": mod.US_ROT_ABS_THRESHOLD,
                    "US_ROT_COMMISSION": mod.US_ROT_COMMISSION,
                    "US_ROT_FUTURES": mod.US_ROT_FUTURES,
                }
                try:
                    mod.US_ROT_LB = 1
                    mod.US_ROT_VOL_LB = 2
                    mod.US_ROT_VOL_WINDOW = 1
                    mod.US_ROT_MIN_TURNOVER = 0.0
                    mod.US_ROT_TARGET_VOL = 0.2
                    mod.US_ROT_MAX_LEV = 1.0
                    mod.US_ROT_ABS_THRESHOLD = 0.0
                    mod.US_ROT_COMMISSION = 0.0
                    mod.US_ROT_FUTURES = {"QQQ"}

                    result = mod.run_us_rotation(
                        close_df,
                        ["QQQ"],
                        top_n=1,
                        abs_threshold=0.0,
                        min_turnover=0.0,
                        threshold=1.0,
                        us_open=us_open,
                    )
                finally:
                    for key, value in old_vals.items():
                        setattr(mod, key, value)

                exec_day = pd.Timestamp("2024-01-12")
                self.assertAlmostEqual(result.loc[exec_day, "return"], 0.10, places=8)
                self.assertAlmostEqual(result.loc[pd.Timestamp("2024-01-11"), "w_QQQ"], 1.0, places=8)

    def test_default_us_turnover_threshold_is_zero_across_versions(self):
        for name, mod in self.mods:
            with self.subTest(version=name):
                self.assertEqual(mod.US_ROT_MIN_TURNOVER, 0.0)


class FilterMarketSessionsTests(unittest.TestCase):
    def test_removes_weekend_rows_for_stock_trading_panels(self):
        frame = pd.DataFrame(
            {
                "QQQ": [100.0, pd.NA, pd.NA, 101.0],
                "BIL": [10.0, pd.NA, pd.NA, 10.1],
                "BTC-USD": [50000.0, 51000.0, 52000.0, 53000.0],
            },
            index=pd.to_datetime(["2024-07-05", "2024-07-06", "2024-07-07", "2024-07-08"]),
        )

        out = filter_market_sessions(frame, ["QQQ", "BIL"])

        self.assertEqual(
            out.index.tolist(),
            pd.to_datetime(["2024-07-05", "2024-07-08"]).tolist(),
        )
        self.assertEqual(out["BTC-USD"].tolist(), [50000.0, 53000.0])

import importlib.util
import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


VERSION_FILES = [
    "mnt_bot V 7.0 plus.py",
    "mnt_bot V 7.1 plus.py",
    "mnt_bot V 7.2 plus.py",
    "mnt_bot V 7.3 plus.py",
    "mnt_bot V 7.5 plus.py",
    "mnt_bot V 7.6 plus.py",
]


def load_bot_module(filename):
    path = os.path.abspath(filename)
    module_name = "mnt_test_" + filename.replace(" ", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CnPreopenLiveSnapshotGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = [(filename, load_bot_module(filename)) for filename in VERSION_FILES]

    def test_preopen_realtime_supplement_does_not_create_today_close(self):
        for filename, bot in self.modules:
            with self.subTest(filename=filename):
                original_now = bot.beijing_now
                original_fetch = bot._fetch_cn_realtime_close
                try:
                    bot.beijing_now = lambda: datetime(
                        2026, 5, 8, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai")
                    )
                    bot._fetch_cn_realtime_close = lambda secid: 101.0
                    df = pd.DataFrame(
                        {"close": [100.0]},
                        index=pd.DatetimeIndex([pd.Timestamp("2026-05-07")], name="date"),
                    )

                    out = bot._supplement_today_close(
                        df, "1.000016", pd.Timestamp("2026-05-08").date(), None
                    )

                    self.assertEqual(out.index[-1], pd.Timestamp("2026-05-07"))
                    self.assertNotIn(pd.Timestamp("2026-05-08"), out.index)
                finally:
                    bot.beijing_now = original_now
                    bot._fetch_cn_realtime_close = original_fetch

    def test_preclose_strict_path_drops_today_bar(self):
        for filename, bot in self.modules:
            with self.subTest(filename=filename):
                original_now = bot.beijing_now
                try:
                    bot.beijing_now = lambda: datetime(
                        2026, 5, 8, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai")
                    )
                    df = pd.DataFrame(
                        {"close": [100.0, 101.0]},
                        index=pd.DatetimeIndex(
                            [pd.Timestamp("2026-05-07"), pd.Timestamp("2026-05-08")],
                            name="date",
                        ),
                    )

                    out = bot._drop_cn_unconfirmed_today(df)

                    self.assertEqual(out.index[-1], pd.Timestamp("2026-05-07"))
                    self.assertNotIn(pd.Timestamp("2026-05-08"), out.index)
                finally:
                    bot.beijing_now = original_now

    def test_vol_scale_assignment_arrays_are_explicit_writable_copies(self):
        for filename in VERSION_FILES:
            with self.subTest(filename=filename):
                with open(filename, "r", encoding="utf-8") as fh:
                    source = fh.read()

                self.assertNotIn("scale_arr = raw_scale.fillna(1.0).values", source)
                self.assertIn("scale_arr = raw_scale.fillna(1.0).to_numpy(copy=True)", source)


if __name__ == "__main__":
    unittest.main()

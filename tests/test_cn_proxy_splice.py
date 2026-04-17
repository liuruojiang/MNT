import importlib.util
import types
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "mnt_bot V 6.5 plus.py"


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
    spec = importlib.util.spec_from_file_location("mnt_bot_v65_plus_cn_proxy_test", str(SCRIPT_PATH))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    module.poe = _DummyPoe
    spec.loader.exec_module(module)
    return module


class CnProxySpliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def test_stitch_keeps_total_return_history_and_extends_with_proxy_returns(self):
        base = pd.DataFrame(
            {"close": [100.0, 110.0, 121.0]},
            index=pd.to_datetime(["2026-04-09", "2026-04-10", "2026-04-11"]),
        )
        proxy = pd.DataFrame(
            {"close": [50.0, 55.0, 60.5, 66.55]},
            index=pd.to_datetime(["2026-04-10", "2026-04-11", "2026-04-14", "2026-04-15"]),
        )

        out = self.mod._stitch_cn_proxy_returns(base, proxy)

        self.assertAlmostEqual(out.loc[pd.Timestamp("2026-04-09"), "close"], 100.0)
        self.assertAlmostEqual(out.loc[pd.Timestamp("2026-04-11"), "close"], 121.0)
        self.assertAlmostEqual(out.loc[pd.Timestamp("2026-04-14"), "close"], 133.1)
        self.assertAlmostEqual(out.loc[pd.Timestamp("2026-04-15"), "close"], 146.41)

    def test_project_realtime_close_uses_proxy_return_not_raw_proxy_level(self):
        base = pd.DataFrame(
            {"close": [110.0, 121.0]},
            index=pd.to_datetime(["2026-04-10", "2026-04-11"]),
        )
        proxy = pd.DataFrame(
            {"close": [55.0, 60.5]},
            index=pd.to_datetime(["2026-04-10", "2026-04-11"]),
        )

        out = self.mod._project_proxy_realtime_close(base, proxy, 66.55)

        self.assertAlmostEqual(out, 133.1)


if __name__ == "__main__":
    unittest.main()

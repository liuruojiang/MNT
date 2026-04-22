import importlib.util
import types
import unittest
from pathlib import Path

import fastapi_poe


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_NAMES = [
    "mnt_bot V 6.1 plus.py",
    "mnt_bot V 6.2 plus.py",
    "mnt_bot V 6.3 plus.py",
    "mnt_bot V 6.4 plus.py",
    "mnt_bot V 6.5 plus.py",
    "mnt_bot V 6.6 plus.py",
    "mnt_bot V 6.7 plus.py",
    "mnt_bot V 6.8 plus.py",
    "mnt_bot V 6.8.1 plus.py",
    "mnt_bot V 6.9 plus.py",
]

EXPECTED_FUTURES = {
    "mnt_bot V 6.8.1 plus.py": {"QQQ", "GLD"},
}


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


def _load_module(script_name):
    path = ROOT / script_name
    module_name = "mnt_bot_" + script_name.replace(" ", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    fastapi_poe.update_settings = _DummyPoe.update_settings
    fastapi_poe.start_message = _DummyPoe.start_message
    fastapi_poe.call = _DummyPoe.call
    module.poe = _DummyPoe
    spec.loader.exec_module(module)
    return module


class UsModelBSelfScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = {name: _load_module(name) for name in SCRIPT_NAMES}

    def test_positive_scale_only_leverages_each_allowed_asset_own_weight(self):
        raw_w = {"GLD": 0.30, "EMXC": 0.35, "DBC": 0.35, "BIL": 0.0}

        for name, mod in self.modules.items():
            with self.subTest(script=name):
                out = mod._us_model_b(raw_w, 1.5)

                self.assertAlmostEqual(out["GLD"], 0.45)
                self.assertAlmostEqual(out["EMXC"], 0.35)
                self.assertAlmostEqual(out["DBC"], 0.35)
                self.assertAlmostEqual(out["BIL"], 0.0)
                self.assertAlmostEqual(
                    out["GLD"] + out["EMXC"] + out["DBC"] + out["BIL"],
                    1.15,
                )

    def test_negative_scale_still_shrinks_all_risky_assets(self):
        raw_w = {"GLD": 0.30, "EMXC": 0.35, "DBC": 0.35, "BIL": 0.0}

        for name, mod in self.modules.items():
            with self.subTest(script=name):
                out = mod._us_model_b(raw_w, 0.8)

                self.assertAlmostEqual(out["GLD"], 0.24)
                self.assertAlmostEqual(out["EMXC"], 0.28)
                self.assertAlmostEqual(out["DBC"], 0.28)
                self.assertAlmostEqual(out["BIL"], 0.20)

    def test_expected_leverage_eligible_assets(self):
        for name, mod in self.modules.items():
            with self.subTest(script=name):
                expected = EXPECTED_FUTURES.get(name, {"QQQ", "GLD", "TLT"})
                self.assertEqual(set(mod.US_ROT_FUTURES), expected)


if __name__ == "__main__":
    unittest.main()

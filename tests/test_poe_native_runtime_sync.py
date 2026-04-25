import builtins
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

TARGETS = {
    "6.1": ("mnt_bot V 6.1 plus.py", "CombinedStrategyV61"),
    "6.5": ("mnt_bot V 6.5 plus.py", "CombinedStrategyV65"),
    "6.8": ("mnt_bot V 6.8 plus.py", "CombinedStrategyV68"),
    "6.8.1": ("mnt_bot V 6.8.1 plus.py", "CombinedStrategyV681"),
    "6.8.2": ("mnt_bot V 6.8.2 plus.py", "CombinedStrategyV681"),
    "6.8.3": ("mnt_bot V 6.8.3 plus.py", "CombinedStrategyV681"),
    "7.0": ("mnt_bot V 7.0 plus.py", "CombinedStrategyV70"),
    "7.1": ("mnt_bot V 7.1 plus.py", "CombinedStrategyV71"),
}


class _PoeStub:
    query = None
    default_chat = []

    class BotError(Exception):
        pass

    def __init__(self):
        self.settings = None

    def update_settings(self, settings):
        self.settings = settings

    def start_message(self):
        raise RuntimeError("start_message should not be called during import")


class _PoeNoBotErrorStub:
    query = None
    default_chat = []

    def __init__(self):
        self.settings = None

    def update_settings(self, settings):
        self.settings = settings

    def start_message(self):
        raise RuntimeError("start_message should not be called during import")

    def __getattr__(self, name):
        if name == "BotError":
            raise AttributeError(
                "'poe' module attribute 'BotError' is not available in this context. "
                "Wrap your code in if __name__ == \"__main__\": block"
            )
        raise AttributeError(name)


def load_with_native_poe(path, name, poe_stub=None):
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = poe_stub or _PoeStub()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        if had_poe:
            builtins.poe = old_poe
        else:
            delattr(builtins, "poe")


class PoeNativeRuntimeSyncTests(unittest.TestCase):
    def test_target_versions_use_native_poe_namespace(self):
        removed_tokens = (
            "import fastapi_poe as poe",
            "import asyncio",
            "import queue",
            "import threading",
            "from types import SimpleNamespace",
            "ProtocolMessage",
            "QueryRequest",
            "SettingsRequest",
            "_safe_poe_update_settings",
            "_CompatChatMessage",
            "_CompatAttachment",
            "_CompatQuery",
            "_CompatMessage",
            "_LegacyPoeRuntime",
            "_POE_RUNTIME_LOCK",
            "PoeBot",
            "runner(",
            "bot = CombinedStrategy",
        )
        for version, (filename, class_name) in TARGETS.items():
            with self.subTest(version=version):
                text = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn("from fastapi_poe.types import SettingsResponse", text)
                self.assertIn("def _fetch_or_bot_errors(", text)
                self.assertIn("poe.update_settings(", text)
                self.assertIn(f"{class_name}().run()", text)
                for token in removed_tokens:
                    self.assertNotIn(token, text)

    def test_target_versions_import_with_native_poe_stub(self):
        for version, (filename, class_name) in TARGETS.items():
            with self.subTest(version=version):
                module = load_with_native_poe(ROOT / filename, f"mnt_bot_v{version.replace('.', '_')}")
                self.assertTrue(hasattr(module, class_name))

    def test_target_versions_import_when_bot_error_is_unavailable_at_import(self):
        for version, (filename, class_name) in TARGETS.items():
            with self.subTest(version=version):
                module = load_with_native_poe(
                    ROOT / filename,
                    f"mnt_bot_v{version.replace('.', '_')}_no_bot_error",
                    poe_stub=_PoeNoBotErrorStub(),
                )
                self.assertTrue(hasattr(module, class_name))


if __name__ == "__main__":
    unittest.main()

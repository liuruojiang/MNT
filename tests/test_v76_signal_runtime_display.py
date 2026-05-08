import importlib.util
import inspect
import os
import types
import unittest


def load_bot_module():
    path = os.path.abspath("mnt_bot V 7.6 plus.py")
    spec = importlib.util.spec_from_file_location("mnt76_display_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CaptureMessage:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def write(self, value):
        self.sink.append(str(value))

    def attach_file(self, **_kwargs):
        pass


class V76SignalRuntimeDisplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_subb_rebalanced_waiting_execution_does_not_say_already_traded(self):
        line = self.bot._subb_turnover_execution_status_text(
            turnover=0.108,
            rebalanced=True,
            execution_happened=False,
        )

        self.assertIn("等待执行", line)
        self.assertNotIn("已调仓", line)

    def test_live_signal_fetch_failure_returns_visible_message(self):
        bot = self.bot
        writes = []
        starts = []
        original_poe = bot.poe

        class RaisingStrategy(bot.CombinedStrategyV75):
            def _fetch_data(self, *_args, **_kwargs):
                raise RuntimeError("fetch blocked")

        def start_message():
            starts.append(True)
            return CaptureMessage(writes)

        bot.poe = types.SimpleNamespace(
            start_message=start_message,
            query=types.SimpleNamespace(text="实时信号", attachments=[]),
            default_chat=[],
            BotError=RuntimeError,
        )
        try:
            RaisingStrategy()._handle_live_signal()
        finally:
            bot.poe = original_poe

        self.assertTrue(any("正在获取实时信号数据" in text for text in writes))
        self.assertTrue(any("实时信号查询失败" in text for text in writes))
        self.assertEqual(1, len(starts))

    def test_signal_fetch_failure_returns_visible_message(self):
        bot = self.bot
        writes = []
        starts = []
        original_poe = bot.poe

        class RaisingStrategy(bot.CombinedStrategyV75):
            def _fetch_data(self, *_args, **_kwargs):
                raise RuntimeError("fetch blocked")

        def start_message():
            starts.append(True)
            return CaptureMessage(writes)

        bot.poe = types.SimpleNamespace(
            start_message=start_message,
            query=types.SimpleNamespace(text="信号", attachments=[]),
            default_chat=[],
            BotError=RuntimeError,
        )
        try:
            RaisingStrategy()._handle_signal()
        finally:
            bot.poe = original_poe

        self.assertTrue(any("正在获取信号数据" in text for text in writes))
        self.assertTrue(any("信号查询失败" in text for text in writes))
        self.assertEqual(1, len(starts))

    def test_run_routing_failure_returns_visible_message(self):
        bot = self.bot
        writes = []
        original_poe = bot.poe

        class BrokenQuery:
            @property
            def text(self):
                raise RuntimeError("query unavailable")

        bot.poe = types.SimpleNamespace(
            start_message=lambda: CaptureMessage(writes),
            query=BrokenQuery(),
            default_chat=[],
            BotError=RuntimeError,
        )
        try:
            bot.CombinedStrategyV75().run()
        finally:
            bot.poe = original_poe

        self.assertTrue(any("查询入口失败" in text for text in writes))

    def test_live_signal_does_not_emit_official_window_breakdown(self):
        source = inspect.getsource(self.bot.CombinedStrategyV75._handle_live_signal)

        self.assertNotIn("_write_subb_official_leg_window_breakdown", source)


if __name__ == "__main__":
    unittest.main()

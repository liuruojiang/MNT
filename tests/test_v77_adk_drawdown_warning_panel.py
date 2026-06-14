import importlib.util
from pathlib import Path

import pandas as pd


def load_v77_module():
    path = Path(__file__).resolve().parents[1] / "mnt_bot V 7.7 plus.py"
    spec = importlib.util.spec_from_file_location("mnt_bot_v77_plus", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CaptureMessage:
    def __init__(self):
        self.parts = []

    def write(self, text):
        self.parts.append(str(text))

    @property
    def text(self):
        return "".join(self.parts)


def test_adk_drawdown_warning_panel_keeps_original_but_removes_16leg_cooldown():
    bot = load_v77_module()
    msg = CaptureMessage()
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    cn_dk_result = pd.DataFrame({"nav": [1.0, 0.96, 0.94, 0.95]}, index=index)

    bot._write_adk_drawdown_warning_panel(msg, cn_dk_result, compact=True)

    assert "原始ADK回撤警示" in msg.text
    assert "16腿叠加ADK回撤警示" not in msg.text
    assert "横向一致性否决" not in msg.text
    assert "16腿叠加净值" not in msg.text

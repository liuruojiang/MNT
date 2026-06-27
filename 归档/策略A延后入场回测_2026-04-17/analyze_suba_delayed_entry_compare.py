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
    extra_cols = [c for c in ["pending_entry_target", "pending_entry_since", "await_fresh_entry_signal"] if c in result.columns]
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

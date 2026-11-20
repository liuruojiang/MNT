"""Offline counterexamples for the V8.0 query/report layer. Run with python -B."""

from collections import defaultdict
from contextlib import ExitStack
import importlib.util
import io
from pathlib import Path
import sys
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / "outputs/v80_recert_20260926"
spec = importlib.util.spec_from_file_location("query_audit", ROOT / "mnt_bot V 8.0 plus.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Output(io.StringIO):
    def __exit__(self, *_):
        pass


def check_parser():
    bot = module.CombinedStrategyV80()
    for query, observed in [
        ("表现 2024-01-01 至 2025-12", [("2024-01-01", "2024-01-01")]),
        ("2024年和2025年表现", [("2024-01-01", "2024-12-31")]),
    ]:
        calls = []
        with patch.object(module.poe.query, "text", query), patch.object(
            bot, "_handle_performance", side_effect=lambda q, _forced_range: calls.append(
                tuple(x.date().isoformat() for x in _forced_range)
            )
        ):
            bot._run_impl()
        assert calls == observed
        print(query, calls)


def check_early_reports(frames):
    bot = module.CombinedStrategyV80()
    stock, adk, us, prod = frames
    # Replace the old bond with the actual broad-bond historical series used by V8.0.
    bond = pd.read_csv(
        ROOT / "research/data_quality/20261105_bond_replacement/native_bond_history.csv",
        index_col="date", parse_dates=True,
    )["close"]
    stock = stock.loc[:, module.CN_STOCK_CODES].copy()
    stock[module.CN_BOND_CODE] = bond.reindex(stock.index)
    assert stock[module.CN_BOND_CODE].notna().all()
    for mode in ("表现", "净值曲线"):
        for year_end, expected in [("2016-12-30", "empty requested bond window"),
                                   ("2017-06-30", "date")]:
            query = f"{mode} {year_end[:4]}-01-01 至 {year_end}"
            output = Output()
            with patch.object(bot, "_cached_fetch_data", return_value=(stock, adk, us, prod)), patch.object(
                module, "_sm", return_value=output
            ), patch.object(module.poe.query, "text", query):
                bot.run()
            assert "查询入口失败" in output.getvalue() and expected in output.getvalue()
            print(query, output.getvalue().split("查询入口失败")[1].strip().splitlines()[0])


def check_adk_end_date(frames):
    stock, adk = frames[:2]
    day = pd.Timestamp("2026-09-16")
    next_session = adk.index[adk.index > day][0]
    for end in (day, next_session):
        prices = adk.loc[:end]
        result = module.run_v80_adk_new_only(stock.loc[:end], prices)
        records = module.extract_v78_adk_rebalances(result, cn_dk_close=prices, since_date=day)
        same_day = [r for r in records if pd.Timestamp(r["日期"]) == day]
        if end == day:
            state = module._adk_query_overview(result)
            assert state["target_is_exact"] and state["changed"] and not same_day
            print("ADK", end.date(), state["rows"], "records", same_day)
        else:
            assert len(same_day) == 1 and "创业板" in same_day[0]["买入"]
            print("ADK", end.date(), same_day[0]["日期"], same_day[0]["买入"])


def check_close_rollover(frames):
    day = pd.Timestamp("2026-09-24")  # Thursday; real frozen model action
    b79 = pd.read_pickle(ARCHIVE / "l4/b_B79_formal.pkl").loc[:day]
    b78 = pd.read_pickle(ARCHIVE / "l4/b_B78_formal.pkl").loc[:day]
    b79.attrs["v80_b78"] = b78
    stock, adk, us, prod = (frame.loc[:day] for frame in frames)
    # Hold data/weights fixed to isolate the clock. No historical intraday trade is inferred.
    us.attrs["is_live_bar"] = True
    data = defaultdict(lambda: None, cn_date=day, dk_date=day, us_date=day, is_us_signal=True,
                       us_rot_result=b79, cn_result=pd.DataFrame(), cn_dk_result=pd.DataFrame())
    bot = module.CombinedStrategyV80()
    for t, expected in [("03:59", "当前只是盘中假设"), ("04:01", "本周信号日收盘目标已确认")]:
        now = pd.Timestamp(f"2026-09-25 {t}").to_pydatetime()
        sink = Output()
        with ExitStack() as stack:
            stack.enter_context(patch.object(module, "beijing_now", return_value=now))
            stack.enter_context(patch.object(module, "_sm", return_value=sink))
            stack.enter_context(patch.object(bot, "_cached_fetch_data", return_value=(stock, adk, us, prod)))
            stack.enter_context(patch.object(bot, "_compute_signal_data", return_value=data))
            for unrelated in ("_write_a_adk_query_overview", "_write_v80_subc_overview",
                              "_write_v80_a_adk_score_details", "_write_volume_warning_panel"):
                stack.enter_context(patch.object(module, unrelated))
            bot._handle_live_signal()
        assert expected in sink.getvalue()
        print(t, next(line for line in sink.getvalue().splitlines() if expected in line))


if __name__ == "__main__":
    with patch.object(module.requests.sessions.Session, "request",
                      side_effect=AssertionError("offline audit")):
        check_parser()
        source_frames = pd.read_pickle(ARCHIVE / "l1_final/formal_inputs.pkl")["frames"]
        check_early_reports(source_frames)
        check_close_rollover(source_frames)
        check_adk_end_date(source_frames)

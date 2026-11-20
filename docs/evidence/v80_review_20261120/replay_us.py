"""Replay Sub-B review cases offline. Run with python -B from any directory."""
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
FROZEN = ROOT / "outputs" / "v80_recert_20260926"
DAY = pd.Timestamp("2026-09-25")
PREVIOUS = pd.Timestamp("2026-09-24")


def load_bot():
    spec = importlib.util.spec_from_file_location("v80_review_us", ROOT / "mnt_bot V 8.0 plus.py")
    bot = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bot
    spec.loader.exec_module(bot)
    return bot


def ibit_proxy_tail(bot, raw, original_opens):
    truncated = {**raw, "BTC-USD": raw["BTC-USD"].loc[:PREVIOUS]}
    formal = bot._build_btc_ibit_formal_ohlc(truncated)
    bot._assert_us_internal_price_history({"BTC/IBIT": formal}, ["BTC/IBIT"])
    close = bot.build_ibit_spliced(pd.DataFrame({
        "BTC-USD": truncated["BTC-USD"]["close"],
        "IBIT": truncated["IBIT"]["close"],
    }).reindex(raw["SPY"].index))
    opens = bot._build_us_open_execution_dict(truncated)
    assert formal.index[-1] == DAY and pd.notna(close.loc[DAY])
    try:
        bot._us_open_row(DAY, ["BTC-USD"], opens, close.to_frame(), strict=True)
    except ValueError as exc:
        assert "missing T+1 adjusted open" in str(exc) and "BTC-USD" in str(exc)
        error = str(exc)
    else:
        raise AssertionError("The missing-open defect did not reproduce")
    return {
        "native_ibit_open": raw["IBIT"].loc[DAY, "open"],
        "mapped_open_before_proxy_truncation": original_opens["BTC-USD"].loc[DAY],
        "mapped_close_after_proxy_truncation": close.loc[DAY],
        "last_mapped_open": str(opens["BTC-USD"].index[-1].date()),
        "error": error,
    }


def late_open(bot, raw):
    spy = raw["SPY"]
    previous_open = spy.loc[PREVIOUS, "open"]
    native_open = spy.loc[DAY, "open"]
    # Diagnostic vendor-response shape: only the current quote's open is absent.
    def timestamp(day, hour):
        return int(day.tz_localize("America/New_York").replace(hour=hour).timestamp())

    result = {
        "meta": {"regularMarketPrice": spy.loc[DAY, "close"], "regularMarketTime": timestamp(DAY, 12)},
        "timestamp": [timestamp(PREVIOUS, 10), timestamp(DAY, 10)],
        "indicators": {"quote": [{"open": [previous_open, None]}]},
    }
    response = Mock(status_code=200, json=lambda: {"chart": {"result": [result]}})
    sample = {"SPY": spy.loc[:PREVIOUS].copy()}
    with patch.object(bot._session, "get", return_value=response), patch.object(bot.time, "sleep"):
        bot._supplement_us_today_close(sample, ["SPY"])
    stored = sample["SPY"].loc[DAY, "open"]
    assert stored == previous_open and stored != native_open
    return {"previous_open": previous_open, "stored_current_open": stored, "actual_current_open": native_open}


def emxc_report(bot, raw, opens):
    # Frozen model events are inputs. The current script rebuilds the account
    # over September and renders the real 25 September adjustment from that slice.
    close = pd.read_pickle(FROZEN / "l1_final" / "formal_inputs.pkl")["frames"][2]
    model = pd.read_pickle(FROZEN / "l4" / "b_B79_formal.pkl").loc["2026-09-01":DAY]
    account = bot._rebuild_subb_account_execution_costs(model, close, us_open=opens, strict_open_execution=True)
    records = bot._v80_subb_account_rebalance_records(account, close, opens, since_date=DAY, label="B7.9")
    event = next(record for record in records if "EMXC" in str(record["卖出"]))
    native = raw["EMXC"].loc[DAY, "open"]
    rendered = event["卖出价格"]
    assert f"EMXC ${opens['EMXC'].loc[DAY]:.2f}开" in rendered
    assert f"EMXC ${native:.2f}开" not in rendered
    return {"sale": event["卖出"], "reported": rendered, "native_etf_open": native}


if __name__ == "__main__":
    module = load_bot()
    original = pd.read_pickle(FROZEN / "l1_final" / "us_raw_ohlc.pkl")
    raw_prices = {ticker: payload["frame"].loc[:DAY] for ticker, payload in original.items()}
    open_series = module._build_us_open_execution_dict(raw_prices)
    checks = {
        "date": str(DAY.date()),
        "emxc_price_in_report": emxc_report(module, raw_prices, open_series),
        "cross_session_realtime_open": late_open(module, raw_prices),
        "ibit_native_open_lost": ibit_proxy_tail(module, raw_prices, open_series),
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2))

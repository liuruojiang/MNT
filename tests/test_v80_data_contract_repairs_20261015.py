"""Independent data-contract regressions for the October 15 V8.0 repairs.

All small price/return examples are synthetic boundary counterexamples, not
historical strategy performance. Frozen raw data is used only where named.
No network or production writes are allowed.
"""

from __future__ import annotations

import importlib.util
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def v80():
    spec = importlib.util.spec_from_file_location(
        "v80_data_contract_repairs_20261015",
        Path(os.environ.get("V80_DATA_CONTRACT_SOURCE", ROOT / "mnt_bot V 8.0 plus.py")),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def forbid_network(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Independent repair tests prohibit all network requests")

    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.time, "sleep", lambda *a, **k: None)


def ohlc(dates):
    return pd.DataFrame({"open": 100.0, "close": 100.0}, index=pd.DatetimeIndex(dates))


@pytest.mark.parametrize("extra", ["2026-07-03", "2026-07-04", "2026-07-02 12:00"])
def test_raw_etf_rejects_non_session_or_intraday_extra_row(v80, extra):
    frame = ohlc(pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-06"]))
    frame.loc[pd.Timestamp(extra)] = [100.0, 100.0]
    frame = frame.sort_index()
    with pytest.raises((v80.poe.BotError, v80.DataSchemaError, ValueError)):
        v80._assert_us_internal_price_history({"SPY": frame}, ["SPY"])


@pytest.mark.parametrize("kind", ["duplicate", "same_day_two_times", "timezone"])
def test_raw_etf_daily_date_contract(v80, kind):
    dates = pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-06"])
    if kind == "duplicate":
        dates = dates.insert(2, dates[1])
    elif kind == "same_day_two_times":
        dates = dates.insert(2, dates[1] + pd.Timedelta(hours=16))
    else:
        dates = dates.tz_localize("America/New_York")
    with pytest.raises((v80.poe.BotError, v80.DataSchemaError, ValueError)):
        v80._assert_us_internal_price_history({"SPY": ohlc(dates)}, ["SPY"])


def test_raw_etf_holiday_absence_is_legal(v80):
    frame = ohlc(pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-06"]))
    v80._assert_us_internal_price_history({"SPY": frame}, ["SPY"])


def test_raw_etf_missing_actual_session_is_rejected(v80):
    frame = ohlc(pd.to_datetime(["2026-07-01", "2026-07-06"]))
    with pytest.raises((v80.poe.BotError, v80.DataSchemaError, ValueError)):
        v80._assert_us_internal_price_history({"SPY": frame}, ["SPY"])


def test_btc_raw_history_keeps_24_7_calendar(v80):
    dates = pd.date_range("2026-07-01", "2026-07-06", freq="D")
    frame = ohlc(dates)
    v80._assert_us_internal_price_history({"BTC-USD": frame}, ["BTC-USD"])
    pd.testing.assert_index_equal(frame.index, dates)


def test_btc_missing_weekend_is_not_disguised_as_stock_holiday(v80):
    dates = pd.date_range("2026-07-01", "2026-07-06", freq="D")
    frame = ohlc(dates).drop(pd.Timestamp("2026-07-04"))
    with pytest.raises((v80.poe.BotError, v80.DataSchemaError, ValueError)):
        v80._assert_us_internal_price_history({"BTC-USD": frame}, ["BTC-USD"])


def test_btc_ibit_phased_history_uses_each_segments_real_calendar(v80):
    proxy = ohlc(pd.date_range("2024-01-05", "2024-01-16", freq="D"))
    live = ohlc(pd.to_datetime(["2024-01-11", "2024-01-12", "2024-01-16"]))
    frame = v80._build_btc_ibit_formal_ohlc({"BTC-USD": proxy, "IBIT": live})
    v80._assert_us_internal_price_history({"BTC/IBIT": frame}, ["BTC/IBIT"])
    assert pd.Timestamp("2024-01-06") in frame.index  # BTC weekend before IBIT
    assert pd.Timestamp("2024-01-13") not in frame.index  # ETF weekend after listing
    assert pd.Timestamp("2024-01-15") not in frame.index  # MLK market holiday


def test_native_ibit_prelisting_rows_cannot_advance_btc_proxy_switch(v80):
    # IBIT's officially documented first exchange trading day is 2024-01-11;
    # the preceding Monday-Wednesday are normal US sessions but not IBIT history.
    # Synthetic positive prelisting rows otherwise survive a session-only gate.
    proxy = ohlc(pd.date_range("2024-01-05", "2024-01-16", freq="D"))
    native = ohlc(pd.to_datetime([
        "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12", "2024-01-16",
    ]))
    with pytest.raises((v80.poe.BotError, v80.DataSchemaError, ValueError)):
        formal = v80._build_btc_ibit_formal_ohlc({"BTC-USD": proxy, "IBIT": native})
        v80._assert_us_internal_price_history({"IBIT": native, "BTC/IBIT": formal}, ["IBIT", "BTC/IBIT"])


@pytest.mark.parametrize("helper", ["_us_open_row", "_v80_b78_us_open_row"])
@pytest.mark.parametrize("dates", [
    ["2026-07-02", "2026-07-03"],  # holiday execution
    ["2026-07-02", "2026-07-04"],  # weekend execution
    ["2026-07-02", "2026-07-07"],  # skips July 6 actual session
])
def test_strict_execution_requires_real_next_market_session(v80, helper, dates):
    index = pd.to_datetime(dates)
    close = pd.DataFrame({"QQQ": 100.0}, index=index)
    opens = {"QQQ": pd.Series(100.0, index=index)}
    with pytest.raises((v80.poe.BotError, v80.DataSchemaError, ValueError)):
        getattr(v80, helper)(index[-1], ["QQQ"], opens, close, strict=True)


@pytest.mark.parametrize("helper", ["_us_open_row", "_v80_b78_us_open_row"])
def test_strict_execution_skips_real_holiday_and_weekend(v80, helper):
    index = pd.to_datetime(["2026-07-02", "2026-07-06"])
    close = pd.DataFrame({"QQQ": [100.0, 101.0]}, index=index)
    opens = {"QQQ": pd.Series([99.0, 100.5], index=index)}
    row = getattr(v80, helper)(index[-1], ["QQQ"], opens, close, strict=True)
    assert row["QQQ"] == pytest.approx(100.5)


@pytest.mark.parametrize("date", ["2026-07-03", "2026-07-04", "2026-07-07"])
def test_account_spread_allocation_cannot_skip_or_invent_session(v80, date):
    with pytest.raises((v80.poe.BotError, v80.DataSchemaError, ValueError)):
        v80._v80_us_spread_time_fractions("2026-07-02", date)


def test_account_spread_allocation_on_actual_next_session(v80):
    overnight, intraday = v80._v80_us_spread_time_fractions("2026-07-02", "2026-07-06")
    assert 0.0 < overnight < 1.0
    assert 0.0 < intraday < 1.0
    assert overnight + intraday == pytest.approx(1.0)


def return_inputs(v80, dates):
    return {name: pd.Series(0.0, index=pd.to_datetime(dates), name=name)
            for name in v80.PERFORMANCE_COMBO_ORDER}


@pytest.mark.parametrize("sleeve", ["Sub-A", "Sub-A-DK", "B7.8", "B7.9", "Sub-C"])
def test_combined_missing_whole_sleeve_row_is_not_a_holiday(v80, sleeve):
    data = return_inputs(v80, ["2026-09-21", "2026-09-22", "2026-09-23"])
    data[sleeve].loc[pd.Timestamp("2026-09-22")] = 0.1
    normal = v80._performance_combined_daily_returns(data)
    assert normal.loc[pd.Timestamp("2026-09-22")] > 0
    data[sleeve] = data[sleeve].drop(pd.Timestamp("2026-09-22"))
    with pytest.raises(ValueError, match="missing|缺|session|交易"):
        v80._performance_combined_daily_returns(data)


def test_combined_all_sleeves_missing_same_actual_session_is_rejected(v80):
    data = return_inputs(v80, ["2026-09-21", "2026-09-23"])
    with pytest.raises(ValueError, match="missing|缺|session|交易"):
        v80._performance_combined_daily_returns(data)


def test_combined_missing_cn_tail_session_is_not_zero_padded(v80):
    data = return_inputs(v80, ["2026-09-22", "2026-09-23", "2026-09-24"])
    data["Sub-A"] = data["Sub-A"].iloc[:-1]
    with pytest.raises(ValueError, match="missing|缺|session|交易|stale"):
        v80._performance_combined_daily_returns(data)


def test_combined_china_mid_autumn_holiday_is_zero_padded_legally(v80):
    data = return_inputs(v80, ["2026-09-24", "2026-09-25", "2026-09-28"])
    for sleeve in ("Sub-A", "Sub-A-DK"):
        data[sleeve] = data[sleeve].drop(pd.Timestamp("2026-09-25"))
    data["B7.9"].loc[pd.Timestamp("2026-09-25")] = 0.01
    combined = v80._performance_combined_daily_returns(data)
    assert combined.loc[pd.Timestamp("2026-09-25")] == pytest.approx(
        v80._performance_combo_weights()["B7.9"] * 0.01)


def test_combined_us_independence_holiday_does_not_delete_cn_session(v80):
    data = return_inputs(v80, ["2026-07-02", "2026-07-03", "2026-07-06"])
    for sleeve in ("B7.8", "B7.9", "Sub-C"):
        data[sleeve] = data[sleeve].drop(pd.Timestamp("2026-07-03"))
    data["Sub-A"].loc[pd.Timestamp("2026-07-03")] = 0.01
    combined = v80._performance_combined_daily_returns(data)
    assert combined.loc[pd.Timestamp("2026-07-03")] == pytest.approx(
        v80._performance_combo_weights()["Sub-A"] * 0.01)


@pytest.fixture(scope="module")
def frozen_dbmf():
    source = ROOT / "outputs/v80_recert_20260926/l1_final/us_raw_ohlc.pkl"
    if not source.is_file():
        pytest.skip("optional frozen real OHLC source is absent")
    return pickle.loads(source.read_bytes())["DBMF"]["frame"].copy()


def test_requested_existing_etf_history_start_cannot_silently_advance(
        v80, monkeypatch, frozen_dbmf):
    # DBMF is already observable in the frozen data before the explicit request;
    # 2023-01-03 is the requested window, NOT an invented inception date.
    truncated = frozen_dbmf.loc["2024-01-02":].copy()
    assert frozen_dbmf.index.min() < pd.Timestamp("2023-01-03")
    monkeypatch.setattr(v80, "_fetch_us_yahoo", lambda *a, **k: truncated.copy())
    monkeypatch.setattr(v80, "_fetch_us_stooq", lambda *a, **k: truncated.copy())
    try:
        frame, source = v80.fetch_yahoo("DBMF", start_date="2023-01-03")
    except (v80.poe.BotError, v80.DataSchemaError, v80.DataUnavailableError, ValueError):
        return
    assert frame is None or frame.empty, (
        f"Requested DBMF history starting 2023-01-03 silently became {frame.index.min()} ({source})")


def test_explicit_later_fetch_window_is_a_valid_history_contract(
        v80, monkeypatch, frozen_dbmf):
    valid = frozen_dbmf.loc["2024-01-02":].copy()
    monkeypatch.setattr(v80, "_fetch_us_yahoo", lambda *a, **k: valid.copy())
    frame, _ = v80.fetch_yahoo("DBMF", start_date="2024-01-02")
    assert frame is not None
    assert frame.index.min() == pd.Timestamp("2024-01-02")
    pd.testing.assert_frame_equal(frame, valid, check_flags=False)


def test_late_listed_native_etf_not_required_before_first_valid_quote(
        v80, monkeypatch, frozen_dbmf):
    # Normal control: default request predates this native ETF. Real frozen
    # native OHLC beginning at its existing recorded start must remain valid.
    monkeypatch.setattr(v80, "_fetch_us_yahoo", lambda *a, **k: frozen_dbmf.copy())
    frame, _ = v80.fetch_yahoo("DBMF", start_date="2003-01-01")
    assert frame is not None
    assert frame.index.min() == frozen_dbmf.index.min()


def yahoo_response(timestamps):
    """Synthetic documented Yahoo chart shape, with no network request."""
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"chart": {"result": [{
                "meta": {
                    "symbol": "SPY", "exchangeTimezoneName": "America/New_York",
                    "firstTradeDate": int(pd.Timestamp("2003-01-02", tz="UTC").timestamp()),
                },
                "timestamp": [int(pd.Timestamp(t, tz="UTC").timestamp()) for t in timestamps],
                "indicators": {
                    "quote": [{"open": [100.0] * len(timestamps), "close": [101.0] * len(timestamps)}],
                    "adjclose": [{"adjclose": [101.0] * len(timestamps)}],
                },
            }], "error": None}}
    return Response()


@pytest.mark.parametrize("extra", ["2026-07-02 13:30", "2026-07-02 16:00"])
def test_actual_yahoo_parser_rejects_duplicate_daily_provider_rows(v80, monkeypatch, extra):
    response = yahoo_response(["2026-07-02 13:30", extra, "2026-07-06 13:30"])
    monkeypatch.setattr(v80._session, "get", lambda *a, **k: response)
    with pytest.raises((v80.poe.BotError, v80.DataSchemaError, ValueError)):
        v80._fetch_us_yahoo("SPY", start_date="2026-07-02")


def test_actual_yahoo_parser_normal_daily_market_timestamps_remain_valid(v80, monkeypatch):
    response = yahoo_response(["2026-07-02 13:30", "2026-07-06 13:30"])
    monkeypatch.setattr(v80._session, "get", lambda *a, **k: response)
    frame = v80._fetch_us_yahoo("SPY", start_date="2026-07-02")
    pd.testing.assert_index_equal(frame.index, pd.DatetimeIndex(["2026-07-02", "2026-07-06"], name="date"))
    np.testing.assert_allclose(frame[["open", "close"]].to_numpy(), [[100, 101], [100, 101]])


@pytest.mark.parametrize("helper", ["_us_open_row", "_v80_b78_us_open_row"])
@pytest.mark.parametrize("source_dates", [["2026-07-02"], ["2026-07-06"]])
def test_strict_open_requires_both_source_signal_and_execution_rows(v80, helper, source_dates):
    # First example lacks the execution-day close row; second lacks any prior
    # source close. Neither can prove T close -> actual T+1 open.
    date = pd.Timestamp("2026-07-06")
    close = pd.DataFrame({"QQQ": 100.0}, index=pd.to_datetime(source_dates))
    opens = {"QQQ": pd.Series([100.0], index=[date])}
    with pytest.raises((v80.poe.BotError, v80.DataSchemaError, ValueError)):
        getattr(v80, helper)(date, ["QQQ"], opens, close, strict=True)


def test_explicit_expected_native_history_start_rejects_prefix_loss(v80):
    frame = ohlc(["2026-07-02", "2026-07-06"])
    with pytest.raises((v80.poe.BotError, v80.DataSchemaError, ValueError)):
        v80._assert_us_internal_price_history(
            {"SPY": frame}, ["SPY"], expected_starts={"SPY": "2026-07-01"})


def test_expected_native_history_start_is_rounded_to_first_real_session(v80):
    frame = ohlc(["2026-07-06", "2026-07-07"])
    v80._assert_us_internal_price_history(
        {"SPY": frame}, ["SPY"], expected_starts={"SPY": "2026-07-03"})


def test_historical_cn_calendar_distinguishes_real_closures(v80):
    sessions = v80._expected_cn_sessions("2018-06-15", "2018-06-20")
    pd.testing.assert_index_equal(sessions, pd.DatetimeIndex(["2018-06-15", "2018-06-19", "2018-06-20"]))
    # COVID closure extension: 2020-01-31 was a weekday but was not a session.
    sessions = v80._expected_cn_sessions("2020-01-23", "2020-02-04")
    pd.testing.assert_index_equal(sessions, pd.DatetimeIndex(["2020-01-23", "2020-02-03", "2020-02-04"]))


@pytest.mark.parametrize("date", ["2010-02-19", "2027-01-04"])
def test_cn_calendar_unknown_coverage_is_not_weekday_assumption(v80, date):
    with pytest.raises(ValueError):
        v80._expected_cn_sessions(date, date)


def test_combined_historical_cn_holiday_stays_legal(v80):
    data = return_inputs(v80, ["2018-06-15", "2018-06-18", "2018-06-19"])
    for sleeve in ("Sub-A", "Sub-A-DK"):
        data[sleeve] = data[sleeve].drop(pd.Timestamp("2018-06-18"))
    data["B7.9"].loc[pd.Timestamp("2018-06-18")] = 0.01
    combined = v80._performance_combined_daily_returns(data)
    assert combined.loc[pd.Timestamp("2018-06-18")] == pytest.approx(
        v80._performance_combo_weights()["B7.9"] * 0.01)

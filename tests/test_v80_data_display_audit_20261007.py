"""Adversarial checks against the production V8.0 data/query functions.

Fixtures are deliberately adversarial inputs, never measured strategy results.
No network requests or external writes are performed.
"""

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    path = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_data_display_audit", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.mark.parametrize("date_text", ["2026/09/28", "2026.09.28", "2026-09-28"])
def test_single_date_signal_routes_to_history(v80, monkeypatch, date_text):
    bot = v80.CombinedStrategyV80()
    observed = []
    monkeypatch.setattr(v80.poe, "query", types.SimpleNamespace(text=f"信号 {date_text}"))
    monkeypatch.setattr(bot, "_handle_signal", lambda: observed.append("current"))
    monkeypatch.setattr(bot, "_handle_signal_history", lambda query: observed.append("history"))
    bot._run_impl()
    assert observed == ["history"]


@pytest.mark.parametrize("start,end", [("2026-10-07", "2026-01-01"), ("NaT", "2026-10-07")])
def test_llm_date_fallback_rejects_invalid_ranges(v80, monkeypatch, start, end):
    monkeypatch.setattr(
        v80.poe, "call",
        lambda *args, **kwargs: types.SimpleNamespace(text=f'{{"start":"{start}","end":"{end}"}}'),
    )
    with pytest.raises(ValueError, match="日期"):
        v80.CombinedStrategyV80()._parse_date_with_llm_fallback("表现 夏季以来")


def test_relative_daily_query_does_not_discard_displayed_start_day(v80, monkeypatch):
    now = datetime(2026, 9, 29, 10, 0)
    monkeypatch.setattr(v80, "beijing_now", lambda: now)
    start, end = v80.parse_date_range("表现 过去一年")
    assert start == pd.Timestamp("2025-09-29")
    assert end == pd.Timestamp("2026-09-29")


def test_daily_return_cleaner_rejects_nat_date(v80):
    returns = pd.Series([0.01, 0.02], index=pd.DatetimeIndex(["2026-09-28", pd.NaT]))
    with pytest.raises(ValueError, match="date|日期|index"):
        v80._performance_clean_daily_returns(returns, name="adversarial NaT")


def test_h_proxy_projection_requires_exact_historical_anchor(v80):
    base = pd.DataFrame({"close": [100.0]}, index=pd.to_datetime(["2026-09-28"]))
    proxy = pd.DataFrame({"close": [200.0]}, index=pd.to_datetime(["2026-09-24"]))
    with pytest.raises((v80.DataSchemaError, v80.DataUnavailableError)):
        v80._project_proxy_realtime_close(base, proxy, 202.0)


def test_h_proxy_projection_never_returns_raw_quote_when_anchor_missing(v80):
    base = pd.DataFrame({"close": [100.0]}, index=pd.to_datetime(["2026-09-28"]))
    proxy = pd.DataFrame({"close": [200.0]}, index=pd.to_datetime(["2026-09-29"]))
    with pytest.raises((v80.DataSchemaError, v80.DataUnavailableError)):
        v80._project_proxy_realtime_close(base, proxy, 202.0)


def test_h_proxy_history_failure_cannot_append_raw_quote(v80, monkeypatch):
    now = datetime(2026, 9, 29, 10, 0)
    base = pd.DataFrame({"close": [100.0]}, index=pd.to_datetime(["2026-09-28"]))
    monkeypatch.setattr(v80, "beijing_now", lambda: now)
    monkeypatch.setattr(v80, "_fetch_cn_realtime_close", lambda *args, **kwargs: 202.0)

    def failed_proxy(*args, **kwargs):
        raise v80.DataUnavailableError("adversarial unavailable proxy history")

    monkeypatch.setattr(v80, "_fetch_cn_h_proxy", failed_proxy)
    try:
        result = v80._supplement_today_close(base.copy(), v80.CN_BOND_CODE, now.date())
    except (v80.DataSchemaError, v80.DataUnavailableError, v80.poe.BotError):
        return
    assert result.index.max() == base.index.max(), "raw proxy quote must not enter H-index price scale"


def test_valid_h_proxy_projection_preserves_scaled_return(v80):
    dates = pd.to_datetime(["2026-09-28"])
    base = pd.DataFrame({"close": [100.0]}, index=dates)
    proxy = pd.DataFrame({"close": [200.0]}, index=dates)
    assert v80._project_proxy_realtime_close(base, proxy, 202.0) == pytest.approx(101.0)


def test_first_loss_counts_toward_drawdown(v80):
    assert v80._max_drawdown_pct_from_nav(pd.Series([0.9, 0.95])) == pytest.approx(-10.0)


def test_cache_fingerprint_observes_intermediate_price_change(v80):
    prices = pd.DataFrame({"asset": [100.0, 101.0, 102.0]}, index=pd.bdate_range("2026-09-23", periods=3))
    before = v80._strategy_frame_cache_fingerprint(prices)
    prices.iloc[1, 0] = 99.0
    assert before != v80._strategy_frame_cache_fingerprint(prices)


def test_raw_cn_prices_reject_internal_missing_close(v80):
    prices = pd.DataFrame({"close": [100.0, np.nan, 102.0]}, index=pd.bdate_range("2026-09-23", periods=3))
    with pytest.raises(v80.DataSchemaError, match="missing"):
        v80._price_column_frame(prices, "close", "asset")


def test_cn_pool_joint_missing_known_session_is_rejected(v80):
    # 2026-09-22 is an actual session in the production-maintained calendar;
    # removing it from every participant must not disappear from integrity checks.
    dates = pd.to_datetime(["2026-09-21", "2026-09-23"])
    raw = {code: pd.DataFrame({"close": [100.0, 102.0]}, index=dates)
           for code in v80.CN_STOCK_CODES}
    assert v80._is_cn_required_close_day("2026-09-22")
    with pytest.raises(v80.DataSchemaError, match="2026-09-22"):
        v80._build_cn_stock_close_frame(raw)


def test_cn_pool_common_holiday_absence_is_valid(v80):
    dates = pd.to_datetime(["2026-09-24", "2026-09-28"])
    raw = {code: pd.DataFrame({"close": [100.0, 102.0]}, index=dates)
           for code in v80.CN_STOCK_CODES}
    assert not v80._is_cn_required_close_day("2026-09-25")
    assert v80._build_cn_stock_close_frame(raw).index.equals(dates)


def test_us_history_rejects_invalid_latest_open_with_valid_latest_close(v80):
    dates = pd.to_datetime(["2026-09-28", "2026-09-29"])
    raw = {"SPY": pd.DataFrame({"open": [100.0, np.nan], "close": [101.0, 102.0]}, index=dates)}
    with pytest.raises(v80.poe.BotError, match="SPY.*2026-09-29"):
        v80._assert_us_internal_price_history(raw, ["SPY"], label="Adversarial tail OHLC")

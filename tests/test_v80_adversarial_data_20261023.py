"""Offline counterexamples, not historical performance or a vendor incident.

Tests assert contracts that failed on the original audited V8.0.
They now run in ordinary test discovery to prevent regressions.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    source = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_data_adversary_20261023", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def offline(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network is forbidden in this audit")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.time, "sleep", lambda *a, **k: None)


def dividend_gap(v80, *, whole_row=False):
    dates = v80._expected_us_ohlc_index("2026-06-01", "2026-09-30")
    raw = pd.DataFrame({"open": 100.0, "close": 100.0}, index=dates)
    adjusted = raw.copy()
    gap = dates[-3]
    # Before a 0.5% distribution, Yahoo's adjusted/raw factor is .995;
    # on and after the ex-date it is 1. The raw path is illustrative only.
    adjusted.loc[adjusted.index < gap, ["open", "close"]] *= .995
    if whole_row:
        adjusted = adjusted.drop(gap)
    else:
        adjusted.loc[gap, "open"] = np.nan
    return adjusted, raw, gap


def test_missing_open_uses_its_own_known_adjustment_factor(v80, monkeypatch):
    adjusted, raw, gap = dividend_gap(v80)
    monkeypatch.setattr(v80, "_fetch_us_yahoo", lambda *a, **k: adjusted.copy())
    monkeypatch.setattr(v80, "_fetch_us_nasdaq_history", lambda *a, **k: raw.copy())
    result, source = v80.fetch_yahoo("SPY", start_date="2026-06-01")
    assert source == "Yahoo+Nasdaq-gap"
    # The formal validator accepts the resulting price history.
    v80._assert_us_internal_price_history({"SPY": result}, ["SPY"])
    factor = adjusted.loc[gap, "close"] / raw.loc[gap, "close"]
    assert result.loc[gap, "open"] == pytest.approx(raw.loc[gap, "open"] * factor)


def test_whole_missing_row_does_not_invent_a_cross_dividend_factor(v80):
    adjusted, raw, gap = dividend_gap(v80, whole_row=True)
    # Without the missing day's factor, the two adjacent regimes disagree.
    # A repair must reject the ambiguity rather than silently use a median.
    try:
        result, _ = v80._merge_same_ticker_gap_prices(adjusted, raw, [gap], "SPY")
    except (ValueError, v80.DataSchemaError):
        return
    assert gap not in v80._valid_us_ohlc_index(result), "Ambiguous adjustment factor must stay unresolved"


def test_constant_factor_positive_control(v80):
    adjusted, raw, gap = dividend_gap(v80)
    adjusted.loc[:, ["open", "close"]] = 99.5
    adjusted.loc[gap, "open"] = np.nan
    result, count = v80._merge_same_ticker_gap_prices(adjusted, raw, [gap], "SPY")
    assert count == 1
    assert result.loc[gap, "open"] == pytest.approx(99.5)

"""Offline regression and adversarial checks for session-local OHLC repairs."""
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    path = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_us_repair_20261023", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def offline(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network/LLM is forbidden in this regression")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.poe, "call", forbidden)


def price_pair():
    days = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"])
    raw = pd.DataFrame({"open": [98., 99., 100., 101., 102.],
                        "close": [100., 101., 102., 103., 104.]}, index=days)
    adjusted = raw * .75
    adjusted.attrs["provider"] = "original-adjusted-source"
    return days, raw, adjusted


def test_same_session_close_factor_is_invariant_to_remote_split_history(v80):
    days, raw, adjusted = price_pair()
    adjusted.loc[days[:2], ["open", "close"]] *= .5
    adjusted.loc[days[2], "open"] = np.nan
    repaired, count = v80._merge_same_ticker_gap_prices(adjusted, raw, [days[2]], "SPY")
    assert count == 1
    assert repaired.loc[days[2], "open"] == pytest.approx(75.)
    pd.testing.assert_series_equal(repaired["close"], adjusted["close"], check_freq=False)
    assert repaired.attrs["provider"] == "original-adjusted-source"
    record = repaired.attrs["nasdaq_gap_repair_evidence"][-1]
    assert record["method"] == "same_day_close_factor"
    assert record["factor"] == pytest.approx(.75)
    assert record["filled_columns"] == ["open"]
    assert record["open"] == {"raw": 100., "adjusted": 75.}


def test_missing_close_uses_the_existing_adjusted_open(v80):
    days, raw, adjusted = price_pair()
    adjusted.loc[days[2], "close"] = np.nan
    repaired, count = v80._merge_same_ticker_gap_prices(adjusted, raw, [days[2]], "SPY")
    assert count == 1
    assert repaired.loc[days[2], "close"] == pytest.approx(102. * .75)
    assert repaired.attrs["nasdaq_gap_repair_evidence"][-1]["method"] == "same_day_open_factor"


def test_whole_missing_row_requires_matching_immediate_session_anchors(v80):
    days, raw, adjusted = price_pair()
    repaired, count = v80._merge_same_ticker_gap_prices(adjusted.drop(days[2]), raw, [days[2]], "SPY")
    assert count == 1
    pd.testing.assert_frame_equal(repaired, adjusted, check_freq=False)
    record = repaired.attrs["nasdaq_gap_repair_evidence"][-1]
    assert record["method"] == "matching_adjacent_session_close_factors"
    assert [item["date"] for item in record["anchors"]] == ["2024-01-03", "2024-01-05"]


@pytest.mark.parametrize("gap_positions", [[0], [4], [1, 2]])
def test_no_extrapolation_or_chained_imputation_for_missing_factors(v80, gap_positions):
    days, raw, adjusted = price_pair()
    gaps = days[gap_positions]
    repaired, count = v80._merge_same_ticker_gap_prices(adjusted.drop(gaps), raw, gaps, "SPY")
    assert count == 0
    assert set(gaps).isdisjoint(v80._valid_us_ohlc_index(repaired))
    assert all(item["status"] == "unresolved" for item in repaired.attrs["nasdaq_gap_repair_evidence"])


def test_small_dividend_factor_step_is_rejected_for_whole_row(v80, monkeypatch):
    days, raw, adjusted = price_pair()
    adjusted.loc[days[:2], ["open", "close"]] *= .995
    adjusted = adjusted.drop(days[2])
    monkeypatch.setattr(v80, "_fetch_us_nasdaq_history", lambda *args, **kwargs: raw)
    repaired, count, remaining = v80._repair_us_yahoo_internal_gaps_with_nasdaq("SPY", adjusted)
    assert (count, remaining) == (0, 1)
    assert repaired.attrs["nasdaq_gap_repair_evidence"][-1]["reason"] == "adjacent_adjustment_factors_disagree"
    with pytest.raises(v80.poe.BotError, match="missing"):
        v80._assert_us_internal_price_history({"SPY": repaired}, ["SPY"])


def test_invalid_fallback_open_never_counts_as_repaired(v80):
    days, raw, adjusted = price_pair()
    adjusted.loc[days[2], "open"] = np.nan
    raw.loc[days[2], "open"] = -1.
    repaired, count = v80._merge_same_ticker_gap_prices(adjusted, raw, [days[2]], "SPY")
    assert count == 0
    assert pd.isna(repaired.loc[days[2], "open"])
    assert repaired.attrs["nasdaq_gap_repair_evidence"][-1]["status"] == "unresolved"


@pytest.mark.parametrize("validator", ["_validate_subb_price_input", "_v80_b78_validate_subb_price_input"])
@pytest.mark.parametrize("damage", ["warmup_gap", "holiday", "intraday", "timezone"])
def test_strict_calendar_rejects_all_index_damage(v80, validator, damage):
    days = v80._expected_us_ohlc_index("2024-01-02", "2024-01-19")
    frame = pd.DataFrame({"SPY": 100., "BIL": 100.}, index=days)
    if damage == "warmup_gap":
        frame = frame.drop(days[1])
    elif damage == "holiday":
        frame.loc[pd.Timestamp("2024-01-15")] = 100.
        frame = frame.sort_index()
    elif damage == "intraday":
        frame.index += pd.Timedelta(hours=1)
    else:
        frame.index = frame.index.tz_localize("UTC")
    with pytest.raises(ValueError, match="(?i)(session|calendar)"):
        getattr(v80, validator)(frame, ["SPY", "BIL"], 2, "strict test", strict_calendar=True)


@pytest.mark.parametrize("validator", ["_validate_subb_price_input", "_v80_b78_validate_subb_price_input"])
def test_nonstrict_diagnostic_gap_and_legitimate_prelisting_nans_preserved(v80, validator):
    days = v80._expected_us_ohlc_index("2024-01-02", "2024-01-19")
    frame = pd.DataFrame({"SPY": 100., "BIL": 100., "IBIT": np.nan}, index=days)
    frame.loc["2024-01-11":, "IBIT"] = 25.
    getattr(v80, validator)(frame, ["SPY", "BIL", "IBIT"], 2, "late history", strict_calendar=True)
    getattr(v80, validator)(frame.drop(days[1]), ["SPY", "BIL", "IBIT"], 2, "diagnostic")

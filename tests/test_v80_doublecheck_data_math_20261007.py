"""Independent second audit: data-boundary and arithmetic checks.

Synthetic vendor responses test rejection/acceptance contracts only. They are not
market data, strategy performance or evidence of an actual vendor incident.
Frozen-input tests explicitly identify the real local input file and never fetch.
"""

import importlib.util
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
        "v80_second_audit_data_math", ROOT / "mnt_bot V 8.0 plus.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def forbid_network(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("second audit forbids all network requests")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.time, "sleep", lambda *args, **kwargs: None)


class Message:
    def __init__(self):
        self.lines = []

    def write(self, text):
        self.lines.append(text)


def synthetic_vendor_fetch(v80, monkeypatch, clock, include_us_live,
                           include_cn_live=False, us_end="2026-10-09",
                           retry_spy_gap=False, probe_override=None):
    """Run real fetch validation, replacing only upstream vendor responses."""
    current = pd.Timestamp(clock).to_pydatetime()
    cn_dates = pd.bdate_range("2026-01-05", "2026-10-09")
    cn_dates = cn_dates[~cn_dates.isin(
        pd.to_datetime(sorted(v80.CN_MARKET_HOLIDAYS))
    )]
    cn = pd.DataFrame({"close": 100.0 + np.arange(len(cn_dates)) * 0.01},
                      index=cn_dates)
    us_dates = v80._expected_us_ohlc_index("2026-01-05", us_end)
    us = pd.DataFrame({"open": 100.0, "close": 100.0}, index=us_dates)
    monkeypatch.setattr(v80, "beijing_now", lambda: current)
    monkeypatch.setattr(v80, "fetch_cn_kline", lambda *a, **k:
                        (cn.copy(), "SYNTHETIC_TEST_ONLY"))
    monkeypatch.setattr(v80, "_fetch_cn_dk_price_index", lambda *a, **k:
                        (cn.copy(), "SYNTHETIC_TEST_ONLY"))
    fetch_counts = {}
    def vendor_us(ticker, *args, **kwargs):
        fetch_counts[ticker] = fetch_counts.get(ticker, 0) + 1
        response = us.copy()
        if retry_spy_gap and ticker == "SPY" and fetch_counts[ticker] == 1:
            response.loc[pd.Timestamp("2026-09-23"), "open"] = np.nan
        return response, "Yahoo"
    monkeypatch.setattr(v80, "fetch_yahoo", vendor_us)
    probe_date = (pd.Timestamp(current).tz_localize("Asia/Shanghai")
                  .tz_convert("America/New_York").strftime("%Y-%m-%d"))
    if probe_override is not None:
        probe_date = probe_override
    monkeypatch.setattr(v80, "_fetch_us_realtime_close", lambda *a, **k:
                        (100.0, probe_date, 100.0))
    bot = v80.CombinedStrategyV80()
    result = bot._fetch_data(Message(), include_cn_live_snapshot=include_cn_live,
                            include_us_live_snapshot=include_us_live)
    return result


@pytest.mark.parametrize("clock,live,expected", [
    ("2026-09-29 10:00", True, "2026-09-28"),
    ("2026-09-30 00:00", True, "2026-09-29"),
    ("2026-09-30 00:00", False, "2026-09-28"),
])
def test_formal_fetch_caps_us_vendor_rows_at_actual_available_session(
        v80, monkeypatch, clock, live, expected):
    result = synthetic_vendor_fetch(v80, monkeypatch, clock, live)
    assert result[2].index[-1] == pd.Timestamp(expected)
    assert result[3].index[-1] == pd.Timestamp(expected)


@pytest.mark.parametrize("clock,expected", [
    ("2026-09-29 10:00", "2026-09-28"),
    ("2026-09-30 00:00", "2026-09-29"),
])
def test_live_current_session_with_complete_ohlc_is_not_stale(
        v80, monkeypatch, clock, expected):
    # Positive control: the permitted current live session remains available.
    result = synthetic_vendor_fetch(v80, monkeypatch, clock, True, us_end=expected)
    assert result[2].index[-1] == pd.Timestamp(expected)
    assert result[3].index[-1] == pd.Timestamp(expected)


def test_formal_us_retry_cannot_reintroduce_future_vendor_rows(v80, monkeypatch):
    # The initial SPY history is missing an internal open. Its complete retry
    # also contains future dates, so capping only the first fetch is insufficient.
    result = synthetic_vendor_fetch(v80, monkeypatch, "2026-09-29 10:00", True,
                                    retry_spy_gap=True)
    assert result[2].index[-1] == pd.Timestamp("2026-09-28")
    assert result[3].index[-1] == pd.Timestamp("2026-09-28")


def test_formal_us_supplement_cannot_append_future_quote(v80, monkeypatch):
    result = synthetic_vendor_fetch(v80, monkeypatch, "2026-09-29 10:00", True,
                                    us_end="2026-09-28",
                                    probe_override="2026-10-09")
    assert result[2].index[-1] == pd.Timestamp("2026-09-28")
    assert result[3].index[-1] == pd.Timestamp("2026-09-28")


@pytest.mark.parametrize("live,expected", [(False, "2026-09-28"),
                                            (True, "2026-09-29")])
def test_formal_cn_fetch_already_caps_future_vendor_dates(
        v80, monkeypatch, live, expected):
    result = synthetic_vendor_fetch(v80, monkeypatch, "2026-09-29 10:00", False,
                                    include_cn_live=live)
    assert result[0].index[-1] == pd.Timestamp(expected)
    assert result[1].index[-1] == pd.Timestamp(expected)


def retry_frames():
    dates = pd.to_datetime(["2026-09-21", "2026-09-22", "2026-09-23",
                            "2026-09-24", "2026-09-25", "2026-09-28"])
    original = pd.DataFrame({"open": [np.nan, 100.0, np.nan, 100.0, 100.0, 100.0],
                             "close": 100.0}, index=dates)
    return original, dates


def test_retry_cannot_hide_observed_invalid_first_row_by_truncating_start(
        v80, monkeypatch):
    original, dates = retry_frames()
    retry = pd.DataFrame({"open": 100.0, "close": 100.0}, index=dates[1:])
    raw = {"SPY": original.copy()}
    monkeypatch.setattr(v80, "fetch_yahoo", lambda *a, **k: (retry.copy(), "Yahoo"))
    with pytest.raises(v80.poe.BotError):
        v80._retry_incomplete_us_price_history(raw, {"SPY": "Yahoo"}, ["SPY"])
        v80._assert_columns_fresh(raw, ["SPY"], expected_date=dates[-1], max_lag_days=0)
        v80._assert_us_internal_price_history(raw, ["SPY"])


def test_complete_retry_can_repair_observed_start_and_internal_gap(
        v80, monkeypatch):
    original, dates = retry_frames()
    retry = pd.DataFrame({"open": 100.0, "close": 100.0}, index=dates)
    raw = {"SPY": original.copy()}
    monkeypatch.setattr(v80, "fetch_yahoo", lambda *a, **k: (retry.copy(), "Yahoo"))
    v80._retry_incomplete_us_price_history(raw, {"SPY": "Yahoo"}, ["SPY"])
    v80._assert_us_internal_price_history(raw, ["SPY"])
    assert raw["SPY"].index.equals(dates)
    assert raw["SPY"]["open"].notna().all()


def test_retry_truncated_tail_remains_blocked_by_required_close_freshness(
        v80, monkeypatch):
    original, dates = retry_frames()
    original["open"] = [100.0, 100.0, np.nan, 100.0, 100.0, np.nan]
    retry = pd.DataFrame({"open": 100.0, "close": 100.0}, index=dates[:-1])
    raw = {"SPY": original.copy()}
    monkeypatch.setattr(v80, "fetch_yahoo", lambda *a, **k: (retry.copy(), "Yahoo"))
    with pytest.raises(v80.poe.BotError):
        v80._retry_incomplete_us_price_history(raw, {"SPY": "Yahoo"}, ["SPY"])
        v80._assert_columns_fresh(raw, ["SPY"], expected_date=dates[-1], max_lag_days=0)
        v80._assert_us_internal_price_history(raw, ["SPY"])


@pytest.mark.parametrize("column,position", [("open", 0), ("open", -1),
                                              ("close", 0), ("close", -1)])
def test_unrepaired_observed_endpoints_fail_us_ohlc_check(
        v80, column, position):
    dates = pd.to_datetime(["2026-09-21", "2026-09-22", "2026-09-23"])
    frame = pd.DataFrame({"open": 100.0, "close": 100.0}, index=dates)
    frame.iloc[position, frame.columns.get_loc(column)] = np.nan
    with pytest.raises(v80.poe.BotError):
        v80._assert_us_internal_price_history({"SPY": frame}, ["SPY"])


def independent_r2(values):
    values = np.asarray(values, dtype=float)
    y = values - values[0]
    y -= y.mean()
    if not np.any(y):
        return 0.0
    y /= np.max(np.abs(y))
    x = np.arange(len(y), dtype=float)
    x -= x.mean()
    return float((x @ y) ** 2 / ((x @ x) * (y @ y)))


@pytest.mark.parametrize("scale", [0.01, 1.0, 100.0])
def test_r2_ordinary_scale_matches_independent_normalized_correlation(v80, scale):
    values = scale * (1000.0 + np.cumsum(np.sin(np.arange(81)) + 0.12))
    actual = v80.calc_rolling_r2(pd.Series(values), window=20)
    expected = [independent_r2(values[i-19:i+1]) for i in range(19, len(values))]
    np.testing.assert_allclose(actual.iloc[19:], expected, rtol=0.0, atol=2e-14)


def test_cn_joint_gap_across_maintained_year_boundary_respects_holidays(v80):
    dates = pd.to_datetime(["2025-12-31", "2026-01-05"])
    frames = [pd.DataFrame({"a": [100.0, 101.0]}, index=dates)]
    actual = v80._merge_cn_price_frames(frames, ["a"], "synthetic")
    assert actual.index.equals(dates)


def test_cn_joint_two_missing_sessions_inside_maintained_year_rejects(v80):
    dates = pd.to_datetime(["2026-01-05", "2026-01-08"])
    frames = [pd.DataFrame({"a": [100.0, 101.0]}, index=dates)]
    with pytest.raises(v80.DataSchemaError, match="2026-01-06,2026-01-07"):
        v80._merge_cn_price_frames(frames, ["a"], "synthetic")


@pytest.mark.parametrize("bad", [-1.0, 0.0, np.nan, np.inf])
def test_h_proxy_invalid_same_day_anchor_fail_closed(v80, bad):
    date = pd.to_datetime(["2026-09-28"])
    base = pd.DataFrame({"close": [100.0]}, index=date)
    proxy = pd.DataFrame({"close": [bad]}, index=date)
    with pytest.raises(v80.DataSchemaError):
        v80._project_proxy_realtime_close(base, proxy, 202.0)


@pytest.fixture(scope="module")
def frozen_inputs():
    source = ROOT / "outputs/v80_recert_20260926/l1_final/formal_inputs.pkl"
    if not source.is_file():
        pytest.skip("optional real-input diagnostic requires the git-ignored local L1 freeze")
    with source.open("rb") as f:
        return pickle.load(f)


def test_frozen_current_adk_rank_score_and_direction_match_formal_pair_state(
        v80, frozen_inputs):
    # Directly run the current formal ADK path, not the earlier audit's output.
    cn, dk = frozen_inputs["frames"][:2]
    result = v80.run_v80_adk_new_only(cn, dk)
    for _label, _scope, _weight, leg, _new in v80._v80_adk_component_specs(result):
        scores = leg.attrs["signals_df"]
        shifted = scores.shift(1)
        pairs = leg.attrs["pair_data"]
        for pos, date in enumerate(leg.index):
            for use_shifted in (False, True):
                rows = v80._build_dk_rank_rows_at(leg, pos, use_shifted, top_n=1)
                if not rows:
                    continue
                row = rows[0]
                pair = row["pair"]
                frame = pairs[pair]
                if date not in frame.index:
                    continue
                expected_direction = frame.at[date, "position" if use_shifted else "signal"]
                expected_score = (shifted if use_shifted else scores).at[date, pair]
                assert row["direction"] == int(expected_direction)
                assert row["score_used"] == pytest.approx(expected_score, abs=1e-12)


def test_subc_flat_prices_scaling_transition_reconciles_fees_and_debt(v80):
    # Independent analytical oracle with no price movement and zero funding.
    dates = pd.to_datetime(["2026-09-21", "2026-09-22"])
    prices = pd.DataFrame({"VTI": 100.0, "BIL": 100.0}, index=dates)
    components = pd.DataFrame({"exposure::VTI": 0.6, "signal::VTI": 1.0,
                               "contribution::VTI": 0.0}, index=dates)
    opens = {name: prices[name] for name in prices}
    cost_rate = 0.0006
    observed_return, observed_cost = v80._subc_scale_transition_account(
        components, ["VTI"], 1, 1.0, 1.5, prices, opens, True, 0.0, cost_rate
    )
    # fee = c * (1.5 * (1-fee) - 1) => c * 0.5 / (1+1.5*c)
    sleeve_fee = cost_rate * 0.5 / (1.0 + 1.5 * cost_rate)
    assert observed_cost == pytest.approx(0.6 * sleeve_fee, abs=1e-14)
    assert observed_return == pytest.approx(-0.6 * sleeve_fee, abs=1e-14)


def test_subc_zero_risk_signal_transition_does_not_borrow(v80):
    # Boundary only: formal PROD_USE_TIMING=False makes these 0 signals inactive.
    dates = pd.to_datetime(["2026-09-21", "2026-09-22"])
    prices = pd.DataFrame({"VTI": 100.0, "BIL": 100.0}, index=dates)
    components = pd.DataFrame({"exposure::VTI": 0.6, "signal::VTI": 0.0,
                               "contribution::VTI": 0.0}, index=dates)
    opens = {name: prices[name] for name in prices}
    ret, cost = v80._subc_scale_transition_account(
        components, ["VTI"], 1, 1.0, 1.5, prices, opens, True, 0.01, 0.0006
    )
    assert ret == pytest.approx(0.0, abs=1e-14)
    assert cost == pytest.approx(0.0, abs=1e-14)

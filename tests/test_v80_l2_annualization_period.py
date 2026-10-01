"""The first dated return consumes a real market-close interval."""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    path = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_l2_periods", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_full_us_period_includes_friday_to_monday_first_return(v80):
    returns = pd.Series([0.001, 0.002], index=pd.to_datetime(["2024-01-08", "2024-01-09"]))
    expected = ((1.001 * 1.002) ** (365.25 / 4) - 1.0) * 100.0
    assert v80._performance_annualized_pct(returns, None, "B7.9", first_period_start=pd.Timestamp("2024-01-05")) == pytest.approx(expected)


def test_window_uses_previous_observed_close(v80):
    dates = pd.bdate_range("2024-01-02", periods=35)
    returns = pd.Series(0.001, index=dates)
    first_window_day = dates[10]
    window = returns.loc[first_window_day:]
    expected_days = (window.index[-1] - dates[9]).days
    expected = ((1.001 ** len(window)) ** (365.25 / expected_days) - 1.0) * 100.0
    actual = v80._performance_daily_window_metric(returns, first_window_day, dates[-1], name="B7.9")
    assert actual["reason"] is None
    assert actual["annual"] == pytest.approx(expected)


def test_first_period_without_source_anchor_is_rejected(v80):
    returns = pd.Series([0.01, 0.02], index=pd.to_datetime(["2024-01-08", "2024-01-09"]))
    with pytest.raises(ValueError, match="preceding source close"):
        v80._performance_annualized_pct(returns, None, "B7.9")


def test_combined_query_uses_previous_return_date_across_us_holiday(v80):
    dates = pd.to_datetime(["2024-07-03", "2024-07-04", "2024-07-05", "2024-07-08"])
    history = pd.Series([0.001, 0.002, 0.003, 0.004], index=dates)
    query = history.loc["2024-07-05":]
    expected = ((1.003 * 1.004) ** (365.25 / 4) - 1.0) * 100.0
    assert v80._performance_annualized_pct(query, history, "Combined") == pytest.approx(expected)


def test_legacy_metrics_include_first_return_period_and_window_anchor(v80):
    dates = pd.bdate_range("2024-01-08", periods=100)
    history = pd.Series(0.001, index=dates)
    full = v80.calc_daily_metrics(history, 0.0, 252, first_period_start="2024-01-05")
    full_days = (dates[-1] - pd.Timestamp("2024-01-05")).days
    assert full["years"] == pytest.approx(full_days / 365.25)
    assert full["annual"] == pytest.approx(((1.001 ** 100) ** (365.25 / full_days) - 1) * 100)

    window = history.iloc[20:]
    result = v80.calc_daily_metrics(window, 0.0, 252, history_returns=history)
    window_days = (dates[-1] - dates[19]).days
    assert result["years"] == pytest.approx(window_days / 365.25)
    assert result["annual"] == pytest.approx(((1.001 ** 80) ** (365.25 / window_days) - 1) * 100)


def test_legacy_metrics_reject_unanchored_first_return(v80):
    dates = pd.bdate_range("2024-01-08", periods=80)
    returns = pd.Series(0.001, index=dates)
    with pytest.raises(ValueError, match="preceding source close"):
        v80.calc_daily_metrics(returns, 0.0, 252)

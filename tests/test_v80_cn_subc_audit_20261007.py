"""Adversarial implementation cases; synthetic prices are not strategy metrics."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    path = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_cn_subc_audit_20261007", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.mark.parametrize("slope", [0.1, 0.0001])
def test_suba_rolling_r2_linear_price_is_one_after_long_history(v80, slope):
    # Translation must not change correlation. Large cumulative sums must not
    # turn an exactly linear 20-session window into a weak-quality signal.
    prices = pd.Series(1000.0 + slope * np.arange(6000))
    actual = v80.calc_rolling_r2(prices, window=20).iloc[19:]
    assert actual.between(0.0, 1.0).all()
    np.testing.assert_allclose(actual.to_numpy(), 1.0, atol=1e-8, rtol=0.0)


def test_suba_rolling_r2_recovers_only_after_missing_bar_leaves_window(v80):
    prices = pd.Series(1000.0 + np.arange(80, dtype=float))
    prices.iloc[30] = np.nan
    actual = v80.calc_rolling_r2(prices, window=20)
    assert actual.iloc[30:50].isna().all()
    assert actual.iloc[50] == pytest.approx(1.0, abs=1e-10)


@pytest.mark.parametrize("window", [1, 2, 20])
def test_suba_rolling_r2_constant_price_is_zero(v80, window):
    actual = v80.calc_rolling_r2(pd.Series([1e6] * 60), window=window)
    assert actual.iloc[window - 1:].eq(0.0).all()


def test_suba_rolling_r2_two_point_trend_is_one(v80):
    actual = v80.calc_rolling_r2(pd.Series([1e6, 1e6 + 0.001, 1e6 + 0.004]), window=2)
    np.testing.assert_allclose(actual.iloc[1:], 1.0, atol=1e-10, rtol=0.0)


@pytest.mark.parametrize("expected", [0.14999, 0.15001])
def test_suba_rolling_r2_preserves_gate_with_high_offset(v80, expected):
    x = np.arange(20, dtype=float)
    x -= x.mean()
    noise = np.cos(np.arange(20))
    noise -= noise.mean()
    noise -= x * (noise @ x) / (x @ x)
    amplitude = np.sqrt((1 - expected) / expected * (x @ x) / (noise @ noise))
    prices = pd.Series(1e6 + 0.001 * (x + amplitude * noise))
    actual = v80.calc_rolling_r2(prices, window=20).iloc[-1]
    assert actual == pytest.approx(expected, abs=1e-7)
    assert (actual >= v80.CN_R2_THRESHOLD) == (expected >= v80.CN_R2_THRESHOLD)


def test_suba_rolling_r2_is_prefix_invariant(v80):
    prices = pd.Series(1000.0 + np.cumsum(np.sin(np.arange(200)) * 0.0001))
    full = v80.calc_rolling_r2(prices, window=20)
    prefix = v80.calc_rolling_r2(prices.iloc[:137], window=20)
    pd.testing.assert_series_equal(prefix, full.iloc[:137])


@pytest.mark.parametrize("at", [False, True])
def test_adk_shifted_rank_uses_executed_direction_on_signal_flip(v80, at):
    dates = pd.to_datetime(["2026-09-21", "2026-09-22"])
    pair = "SZ50/ZZ500"
    result = pd.DataFrame({"top_pair": [pair, pair], "direction": [1, 1]}, index=dates)
    result.attrs["signals_df"] = pd.DataFrame({pair: [10.0, 20.0]}, index=dates)
    result.attrs["pair_data"] = {
        pair: pd.DataFrame({"signal": [1, -1], "position": [1, 1]}, index=dates)
    }
    function = v80._build_dk_rank_rows_at if at else v80._build_dk_rank_rows
    assert function(result, use_shifted=True)[0]["direction"] == 1
    assert function(result, use_shifted=False)[0]["direction"] == -1


def test_adk_effective_cost_charges_shared_leg_net_change(v80):
    dates = pd.to_datetime(["2026-09-21", "2026-09-22"])
    frame = pd.DataFrame(
        {"top_pair": ["SZ50/ZZ500", "SZ50/CYB"], "direction": [1, 1],
         "weight": [1.0, 1.0]}, index=dates
    )
    pairs = {
        label: pd.DataFrame({"position": [1, 1], "raw_ret": [0.0, 0.0]}, index=dates)
        for label in ["SZ50/ZZ500", "SZ50/CYB"]
    }
    result = v80._rebuild_dk_effective_execution_costs(frame, pairs, commission=0.001)
    assert result["dk_execution_turnover"].tolist() == [2.0, 2.0]
    assert result["dk_execution_cost"].tolist() == [0.002, 0.002]
    np.testing.assert_allclose(result["return"], [-0.002, -0.002], atol=1e-14)


def test_subc_annual_rebalance_uses_actual_last_us_session(v80):
    dates = pd.to_datetime(["2022-12-29", "2022-12-30", "2023-01-03"])
    prices = pd.DataFrame({"AAA": [100.0, 120.0, 120.0],
                           "BBB": [100.0, 100.0, 100.0],
                           "BIL": [100.0, 100.0, 100.0]}, index=dates)
    signals = pd.DataFrame(1.0, columns=["AAA", "BBB"],
                           index=pd.to_datetime(["2022-12-31", "2023-01-31"]))
    portfolio = {"AAA": {"w": 0.5, "proxy": "AAA"},
                 "BBB": {"w": 0.5, "proxy": "BBB"}}
    result = v80._compute_daily_subc_components(prices, signals, portfolio, "BIL")
    assert result.loc["2022-12-30", "annual_rebalanced"]
    assert not result.loc["2023-01-03", "annual_rebalanced"]
    assert result.loc["2022-12-30", "close_weight::AAA"] == pytest.approx(0.5)
    expected_turnover = abs(0.5 - 0.6 / 1.1) + abs(0.5 - 0.5 / 1.1)
    assert result.loc["2022-12-30", "asset_turnover"] == pytest.approx(expected_turnover)
    assert result.loc["2022-12-30", "base_return"] == pytest.approx(
        0.1 - 1.1 * expected_turnover * v80.PROD_COMMISSION
    )


def test_subc_scale_is_lagged_and_prefix_invariant(v80):
    dates = pd.bdate_range("2024-01-02", periods=45)
    raw = pd.Series(np.where(np.arange(45) < 25, 0.5, 1.5), index=dates)
    full = v80._subc_threshold_scale(raw, threshold=0.35)
    prefix = v80._subc_threshold_scale(raw.iloc[:26], threshold=0.35)
    pd.testing.assert_series_equal(prefix, full.iloc[:26])
    assert full.iloc[25] == 0.5
    assert full.iloc[26] == 1.5

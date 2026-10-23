"""Offline regression tests for cash financing and holiday query boundaries."""
import numpy as np
import pandas as pd
import pytest

from test_v80_adversarial_math_20261023 import v80, no_network, flat_case, holiday_query_inputs
from test_v80_reporting_repairs_20261015 import report_harness


def with_prior(inputs, date="2026-09-24", values=None):
    return {name: pd.concat([pd.Series([(values or {}).get(name, 0.0)], index=pd.to_datetime([date])), series])
            for name, series in inputs.items()}


@pytest.mark.parametrize("signal", [0.0, 0.25, 0.5, 0.75, 1.0])
@pytest.mark.parametrize("scale", [0.5, 1.0, 1.5])
def test_ordinary_day_charges_only_net_group_borrow(v80, monkeypatch, signal, scale):
    actual = flat_case(v80, monkeypatch, signal, scale)
    expected = -0.75 * max(scale * signal - 1.0, 0.0) * v80.PROD_VS_SPREAD_BPS / 10000 / v80.US_TRADING_DAYS
    assert actual.tolist() == pytest.approx([expected, expected], abs=1e-14)


@pytest.mark.parametrize("signal", [0.0, 0.5, 0.75, 1.0])
def test_allocation_and_vs_info_use_same_group_net_cash(v80, monkeypatch, signal):
    dates = pd.to_datetime(["2026-09-21", "2026-09-22", "2026-09-23"])
    columns = {cfg["proxy"] for cfg in v80.PROD_PORTFOLIO.values()} | {"BIL", "SPY"}
    prices = pd.DataFrame(100.0, index=dates, columns=sorted(columns))
    signals = pd.DataFrame(signal, index=pd.to_datetime(["2026-09-30"]), columns=prices.columns)
    components = v80._compute_daily_subc_components(prices, signals, v80.PROD_PORTFOLIO, "BIL")
    monkeypatch.setattr(v80, "_subc_relative_scale", lambda price, index, *a: pd.Series(1.5, index=index))
    scales = pd.Series(1.5, index=components.index)
    info = v80._build_subc_vs_info(prices, components, actual_scale=scales)
    base = {name: cfg["w"] for name, cfg in v80.PROD_PORTFOLIO.items()}
    risk, cash, borrow = v80._subc_scaled_allocation(base, dict.fromkeys(base, signal), 1.5, 1.5)
    assert info["current_asset_weights"] == pytest.approx(risk)
    assert info["current_cash_exposure"] == pytest.approx(cash)
    assert info["current_borrow_exposure"] == pytest.approx(borrow)
    assert sum(risk.values()) + cash - borrow == pytest.approx(1.0)
    assert borrow == pytest.approx(0.75 * max(1.5 * signal - 1.0, 0.0))


def test_zero_risk_scale_change_has_no_fee_with_or_without_open_path(v80, monkeypatch):
    dates = pd.to_datetime(["2026-09-21", "2026-09-22", "2026-09-23"])
    columns = {cfg["proxy"] for cfg in v80.PROD_PORTFOLIO.values()} | {"BIL", "SPY"}
    prices = pd.DataFrame(100.0, index=dates, columns=sorted(columns))
    signals = pd.DataFrame(0.0, index=pd.to_datetime(["2026-09-30"]), columns=prices.columns)
    components = v80._compute_daily_subc_components(prices, signals, v80.PROD_PORTFOLIO, "BIL")
    for function in ("_subc_absolute_scale", "_subc_relative_scale"):
        monkeypatch.setattr(v80, function, lambda price, index, *a: pd.Series([1.0, 1.5], index=index))
    for opens in (None, {name: prices[name] for name in prices}):
        ret, _, costs = v80._apply_subc_vol_scaling(components["base_return"], prices, components=components,
                                                   us_open=opens, strict_open_execution=opens is not None)
        np.testing.assert_allclose(ret, 0.0, atol=1e-14)
        np.testing.assert_allclose(costs, 0.0, atol=1e-14)


def test_independent_groups_do_not_net_gold_cash_against_equity_debt(v80):
    base = {name: cfg["w"] for name, cfg in v80.PROD_PORTFOLIO.items()}
    risk, cash, borrow = v80._subc_scaled_allocation(base, dict.fromkeys(base, 1.0), 1.5, 0.5)
    assert cash == pytest.approx(0.075)
    assert borrow == pytest.approx(0.30)
    assert sum(risk.values()) + cash - borrow == pytest.approx(1.0)


@pytest.mark.parametrize("signal", [0.0, 0.5])
def test_ordinary_day_retains_interest_on_effective_cash(v80, monkeypatch, signal):
    dates = pd.to_datetime(["2026-09-21", "2026-09-22", "2026-09-23"])
    columns = {cfg["proxy"] for cfg in v80.PROD_PORTFOLIO.values()} | {"BIL", "SPY"}
    prices = pd.DataFrame(100.0, index=dates, columns=sorted(columns))
    prices["BIL"] = [100.0, 100.1, 100.2001]
    signals = pd.DataFrame(signal, index=pd.to_datetime(["2026-09-30"]), columns=prices.columns)
    components = v80._compute_daily_subc_components(prices, signals, v80.PROD_PORTFOLIO, "BIL")
    for function in ("_subc_absolute_scale", "_subc_relative_scale"):
        monkeypatch.setattr(v80, function, lambda price, index, *a: pd.Series(1.5, index=index))
    actual, _, _ = v80._apply_subc_vol_scaling(components["base_return"], prices, components=components)
    expected_cash = 0.75 * (1.0 - 1.5 * signal) + 0.25 * (1.0 - signal)
    np.testing.assert_allclose(actual, expected_cash * 0.001, atol=1e-14)


def test_query_resets_weights_even_when_prior_history_has_drifted(v80):
    inputs = holiday_query_inputs(v80)
    history = with_prior(inputs, values={"Sub-A": 0.5})
    query = v80._performance_combined_daily_returns(inputs, history_returns=history, query_start="2026-09-25")
    full = v80._performance_combined_daily_returns(history).loc["2026-09-25":]
    assert query.iloc[0] == pytest.approx(0.07)
    assert full.iloc[0] != pytest.approx(query.iloc[0])


def test_unknown_empty_sleeve_is_not_blindly_filled(v80):
    inputs = holiday_query_inputs(v80, one_day=True)
    assert v80._performance_combined_daily_returns(inputs).empty
    assert v80._performance_combined_daily_returns(inputs, history_returns=inputs, query_start="2026-09-25").empty


def test_true_later_inception_preserves_later_common_start(v80):
    inputs = holiday_query_inputs(v80)
    actual = v80._performance_combined_daily_returns(inputs, history_returns=inputs, query_start="2026-09-25")
    assert actual.index.tolist() == pd.to_datetime(["2026-09-28"]).tolist()
    assert actual.tolist() == pytest.approx([0.0])


def test_query_missing_first_required_us_session_is_rejected(v80):
    inputs = holiday_query_inputs(v80)
    history = with_prior(inputs)
    inputs["B7.8"] = inputs["B7.8"].iloc[1:]
    with pytest.raises(ValueError, match="B7.8: missing market-session return at 2026-09-25"):
        v80._performance_combined_daily_returns(inputs, history_returns=history, query_start="2026-09-25")


def test_stale_prequery_state_does_not_prove_holiday_continuation(v80):
    inputs = holiday_query_inputs(v80, one_day=True)
    history = with_prior(inputs, date="2026-09-21")
    with pytest.raises(ValueError, match="missing pre-query market-session return"):
        v80._performance_combined_daily_returns(inputs, history_returns=history, query_start="2026-09-25")


def test_us_holiday_cn_open_is_symmetric(v80):
    day = pd.Timestamp("2026-07-03")
    assert v80._is_cn_required_close_day(day) and not v80._is_us_market_session(day)
    inputs = {name: pd.Series([0.1], index=[day]) if name in ("Sub-A", "Sub-A-DK")
              else pd.Series(dtype=float, index=pd.DatetimeIndex([])) for name in v80.PERFORMANCE_COMBO_ORDER}
    actual = v80._performance_combined_daily_returns(inputs, history_returns=with_prior(inputs, date="2026-07-02"), query_start=day)
    assert actual.tolist() == pytest.approx([0.03])


def test_chart_consumer_keeps_us_only_session_combined(v80, report_harness):
    result = report_harness.execute("净值曲线 2026-09-25")
    nav = result["charts"][0]["navs"]["Combined"]
    expected = sum(v80._performance_combo_weights()[name] * series.get(pd.Timestamp("2026-09-25"), 0.0)
                   for name, series in report_harness.returns.items())
    assert nav.index.tolist() == pd.to_datetime(["2026-09-25"]).tolist()
    assert nav.iloc[0] == pytest.approx(1.0 + expected)

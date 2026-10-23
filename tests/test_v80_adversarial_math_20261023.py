"""Offline synthetic adversarial probes, never market-performance evidence.

Retained regression cases after the October 23 repairs. Production timing is off.
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

from test_v80_reporting_repairs_20261015 import report_harness, workbook_sheets


@pytest.fixture(scope="module")
def v80():
    path = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("audit_v80_20261023_math", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def no_network(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline audit must not access network")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)


def flat_case(v80, monkeypatch, signal, scale):
    dates = pd.to_datetime(["2026-09-21", "2026-09-22", "2026-09-23"])
    columns = {cfg["proxy"] for cfg in v80.PROD_PORTFOLIO.values()} | {"BIL", "SPY"}
    prices = pd.DataFrame(100.0, index=dates, columns=sorted(columns))
    signals = pd.DataFrame(signal, index=pd.to_datetime(["2026-09-30"]), columns=prices.columns)
    components = v80._compute_daily_subc_components(prices, signals, v80.PROD_PORTFOLIO, "BIL")
    def forced_scale(price, index, *args):
        return pd.Series(scale, index=index)
    monkeypatch.setattr(v80, "_subc_absolute_scale", forced_scale)
    monkeypatch.setattr(v80, "_subc_relative_scale", forced_scale)
    return v80._apply_subc_vol_scaling(
        components["base_return"], prices, components=components,
        us_open={name: prices[name] for name in prices}, strict_open_execution=True,
    )[0]


def test_all_cash_momentum_sleeves_have_no_borrow_cost(v80, monkeypatch):
    observed = flat_case(v80, monkeypatch, signal=0.0, scale=1.5)
    assert observed.tolist() == pytest.approx([0.0, 0.0], abs=1e-14)


def test_flat_all_cash_at_unit_scale_control(v80, monkeypatch):
    observed = flat_case(v80, monkeypatch, signal=0.0, scale=1.0)
    assert observed.tolist() == pytest.approx([0.0, 0.0], abs=1e-14)


def test_flat_all_risk_leveraged_control(v80, monkeypatch):
    observed = flat_case(v80, monkeypatch, signal=1.0, scale=1.5)
    expected = -0.75 * 0.5 * v80.PROD_VS_SPREAD_BPS / 10000 / v80.US_TRADING_DAYS
    assert observed.tolist() == pytest.approx([expected, expected], abs=1e-14)


def holiday_query_inputs(v80, one_day=False):
    holiday = pd.Timestamp("2026-09-25")
    assert not v80._is_cn_required_close_day(holiday)
    assert v80._is_us_market_session(holiday)
    us_dates = pd.to_datetime(["2026-09-25"] if one_day else ["2026-09-25", "2026-09-28"])
    cn_dates = pd.DatetimeIndex([]) if one_day else pd.to_datetime(["2026-09-28"])
    return {name: (pd.Series(0.0, index=cn_dates) if name in ("Sub-A", "Sub-A-DK")
                   else pd.Series([0.10] if one_day else [0.10, 0.0], index=us_dates))
            for name in v80.PERFORMANCE_COMBO_ORDER}


def test_query_starting_on_cn_holiday_keeps_us_return(v80):
    inputs = holiday_query_inputs(v80)
    full_inputs = {name: pd.concat([pd.Series([0.0], index=pd.to_datetime(["2026-09-24"])), values])
                   for name, values in inputs.items()}
    full_then_clip = v80._performance_combined_daily_returns(full_inputs).loc["2026-09-25":]
    assert full_then_clip.tolist() == pytest.approx([0.07, 0.0], abs=1e-14)
    observed = v80._performance_combined_daily_returns(inputs, history_returns=full_inputs, query_start="2026-09-25")
    pd.testing.assert_series_equal(observed, full_then_clip)


def test_single_cn_holiday_query_has_combined_return(v80):
    inputs = holiday_query_inputs(v80, one_day=True)
    history = {name: pd.concat([pd.Series([0.0], index=pd.to_datetime(["2026-09-24"])), values]) for name, values in inputs.items()}
    observed = v80._performance_combined_daily_returns(inputs, history_returns=history, query_start="2026-09-25")
    assert observed.index.tolist() == pd.to_datetime(["2026-09-25"]).tolist()
    assert observed.tolist() == pytest.approx([0.07], abs=1e-14)


def test_real_report_holiday_only_combined_cell_is_numeric(v80, report_harness):
    result = report_harness.execute("表现 2026-09-25")
    book = next(item for item in result["attachments"] if item["name"].endswith(".xlsx"))
    cells = workbook_sheets(book["contents"])["绩效概览"]
    expected = sum(v80._performance_combo_weights()[name] * series.get(pd.Timestamp("2026-09-25"), 0.0)
                   for name, series in report_harness.returns.items())
    assert cells.get("G2") == pytest.approx(expected, abs=1e-14)

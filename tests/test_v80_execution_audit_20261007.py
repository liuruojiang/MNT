"""Adversarial execution probes for the production V8.0 entrypoint.

Small inputs are explicit counterexamples, not market backtests.
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    path = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_execution_audit_20261007", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.mark.parametrize("helper", ["_lookup_next_open", "_v80_b78_lookup_next_open"])
def test_historical_open_does_not_jump_to_future_live_listing(v80, helper):
    signal = pd.Timestamp("2019-10-03")
    proxy = pd.Series([190.0, 191.0], index=pd.to_datetime(["2019-10-04", "2019-10-07"]))
    live = pd.Series([120.0], index=pd.to_datetime(["2020-10-13"]))
    assert getattr(v80, helper)("QQQ", signal, {"QQQ": proxy, "QQQM": live}) == pytest.approx(190.0)


@pytest.mark.parametrize("helper", ["_lookup_next_open", "_v80_b78_lookup_next_open"])
def test_missing_next_session_open_is_not_replaced_by_later_session(v80, helper):
    signal = pd.Timestamp("2026-09-24")
    prices = pd.Series([190.0], index=pd.to_datetime(["2026-09-28"]))
    assert getattr(v80, helper)("SPY", signal, {"SPY": prices}) is None


@pytest.mark.parametrize("helper", ["_lookup_next_open", "_v80_b78_lookup_next_open"])
def test_next_open_ignores_weekend_rows(v80, helper):
    signal = pd.Timestamp("2024-01-05")
    prices = pd.Series([190.0, 191.0], index=pd.to_datetime(["2024-01-06", "2024-01-08"]))
    assert getattr(v80, helper)("SPY", signal, {"SPY": prices}) == pytest.approx(191.0)


def account_input(dates, qqq, bil, signal):
    return pd.DataFrame({"return": 0.0, "model_w_QQQ": qqq, "model_w_BIL": bil,
                         "model_target_w_QQQ": qqq, "model_target_w_BIL": bil,
                         "model_rebalanced": signal}, index=dates)


def rebuild(v80, model, close, opens, commission=0.0, covered_assets=(), defense_scale=1.0):
    return v80._v80_rebuild_subb_self_financing(
        model, close, opens, True, commission=commission, benchmark="BIL",
        spread_bps=0.0, trading_days=252, covered_assets=covered_assets,
        defense_scale=defense_scale, next_defense_func=lambda current, ratio: current)


def test_account_overnight_move_belongs_to_old_holdings(v80):
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    model = account_input(dates, [1.0, 0.0], [0.0, 1.0], [True, False])
    model.loc[dates[0], "model_target_w_QQQ"] = 0.0
    model.loc[dates[0], "model_target_w_BIL"] = 1.0
    close = pd.DataFrame({"QQQ": [100.0, 121.0], "BIL": [100.0, 100.0]}, index=dates)
    opens = {"QQQ": pd.Series([100.0, 110.0], index=dates), "BIL": close["BIL"]}
    out = rebuild(v80, model, close, opens)
    assert out.iloc[1]["return"] == pytest.approx(0.10)
    assert out.iloc[1]["actual_w_QQQ"] == 0.0
    assert out.iloc[1]["actual_w_BIL"] == pytest.approx(1.0)
    assert out.iloc[1]["subb_model_execution"]


def test_account_no_event_keeps_shares_and_debt_without_daily_rebalance(v80):
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    model = account_input(dates, [1.5] * 3, [0.0] * 3, [False] * 3)
    close = pd.DataFrame({"QQQ": [100.0, 110.0, 100.0], "BIL": [100.0] * 3}, index=dates)
    out = rebuild(v80, model, close, {})
    assert out.iloc[1]["subb_account_nav"] == pytest.approx(1.15)
    assert out.iloc[2]["subb_account_nav"] == pytest.approx(1.0)
    assert out.iloc[1]["actual_w_QQQ"] == pytest.approx(1.65 / 1.15)
    assert (out["subb_account_borrow_value"] == 0.5).all()
    assert not out["subb_model_execution"].any()
    assert (out["subb_effective_cost"] == 0.0).all()


def test_account_transition_fee_equals_executed_risk_notional(v80):
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    model = account_input(dates, [1.0] * 3, [0.0] * 3, [False] * 3)
    model["volreg_defense"] = [False, True, False]
    close = pd.DataFrame({"QQQ": [100.0] * 3, "BIL": [100.0] * 3}, index=dates)
    opens = {asset: close[asset] for asset in close.columns}
    out = rebuild(v80, model, close, opens, commission=0.001, covered_assets=("QQQ",), defense_scale=0.5)
    assert out.iloc[1]["subb_volreg_execution"]
    assert out.iloc[2]["subb_volreg_execution"]
    for _, row in out.iloc[1:].iterrows():
        traded = row["subb_effective_turnover"] * row["subb_account_open_nav"]
        assert row["subb_account_fee_value"] == pytest.approx(traded * 0.001)
        assert row["subb_account_nav"] == pytest.approx(row["subb_account_asset_value"] - row["subb_account_borrow_value"])

@pytest.mark.parametrize("helper", ["_us_signal_days", "_v80_b78_us_signal_days"])
@pytest.mark.parametrize("dates, expected", [
    (["2024-01-02"], set()),
    (["2024-01-02", "2024-01-03"], set()),
    (["2024-01-02", "2024-01-03", "2024-01-04"], {2}),
    (["2024-11-25", "2024-11-26", "2024-11-27"], {2}),
    (["2024-09-03", "2024-09-04"], set()),
])
def test_weekly_signal_uses_complete_exchange_schedule_not_input_tail(v80, helper, dates, expected):
    frame = pd.DataFrame({"SPY": 100.0}, index=pd.to_datetime(dates))
    assert getattr(v80, helper)(frame, 0) == expected


@pytest.mark.parametrize("helper", ["_us_signal_days", "_v80_b78_us_signal_days"])
def test_tuesday_volreg_target_cannot_include_unconfirmed_weekly_model(v80, helper):
    dates = pd.to_datetime(["2024-01-08", "2024-01-09"])
    close = pd.DataFrame({"QQQ": 100.0, "BIL": 100.0, "GLD": 100.0}, index=dates)
    signals = getattr(v80, helper)(close, 0)
    model = account_input(dates, [1.0, 1.0], [0.0, 0.0], [i in signals for i in range(2)])
    model["model_w_GLD"] = 0.0
    model["model_target_w_GLD"] = [0.0, 1.0]
    model.loc[dates[1], "model_target_w_QQQ"] = 0.0
    model["volreg_defense"] = False
    model["volreg_ratio"] = [0.5, 2.0]
    out = v80._v80_rebuild_subb_self_financing(
        model, close, {}, True, commission=0.0, benchmark="BIL", spread_bps=0.0,
        trading_days=252, covered_assets=("QQQ",), defense_scale=0.5,
        next_defense_func=lambda current, ratio: ratio > 1.0)
    last = out.iloc[-1]
    assert last["subb_pending_volreg_transition"]
    assert not last["subb_pending_model_rebalance"]
    assert last["execution_target_w_QQQ"] == pytest.approx(0.5)
    assert last["execution_target_w_BIL"] == pytest.approx(0.5)
    assert last["execution_target_w_GLD"] == pytest.approx(0.0)

@pytest.mark.parametrize("helper", ["_next_session_day", "_v80_b78_next_session_day"])
def test_execution_time_does_not_skip_missing_market_price_session(v80, helper):
    signal = pd.Timestamp("2026-09-24")
    schedule = {"SPY": pd.Series([190.0], index=pd.to_datetime(["2026-09-28"]))}
    assert getattr(v80, helper)(signal, schedule) == pd.Timestamp("2026-09-25")

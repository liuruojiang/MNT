"""Independent offline repair audit; no historical performance assertions."""
import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def v80():
    path = Path(os.environ.get("V80_REVIEW_SOURCE", ROOT / "mnt_bot V 8.0 plus.py"))
    spec = importlib.util.spec_from_file_location("review_v80_math_clock", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def offline(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No network or LLM in repair review")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.poe, "call", forbidden)


def components_case(v80, all_risk=False):
    dates = pd.to_datetime(["2026-09-21", "2026-09-22", "2026-09-23"])
    names = list(v80.PROD_PORTFOLIO)
    prices = pd.DataFrame(index=dates)
    mix = {}
    for i, name in enumerate(names):
        ticker = v80.PROD_PORTFOLIO[name]["proxy"]
        prices[ticker] = [100., 100., 100. * (1 + (i - 4) * .003)]
        mix[ticker] = 1. if all_risk else (i % 5) / 4
    prices["BIL"] = [100., 100., 100.1]
    if "SPY" not in prices:
        prices["SPY"] = [100., 100., 100.2]
    signals = pd.DataFrame(mix, index=pd.to_datetime(["2026-09-30"]))
    ledger = v80._compute_daily_subc_components(prices, signals, v80.PROD_PORTFOLIO, "BIL")
    return prices, ledger


@pytest.mark.parametrize("equity_scale,gold_scale", [(0., 0.), (.5, 1.8), (1., 1.), (1.8, .5), (1.8, 1.8)])
def test_fractional_signal_returns_equal_independent_cash_account(v80, monkeypatch, equity_scale, gold_scale):
    prices, ledger = components_case(v80)
    monkeypatch.setattr(v80, "_subc_absolute_scale", lambda price, index, *args: pd.Series(equity_scale, index=index))
    monkeypatch.setattr(v80, "_subc_relative_scale", lambda price, index, *args: pd.Series(gold_scale, index=index))
    actual, _, fee = v80._apply_subc_vol_scaling(ledger["base_return"], prices, components=ledger)
    row = ledger.iloc[-1]
    cash, debt, expected = {}, {}, 0.
    for name, cfg in v80.PROD_PORTFOLIO.items():
        group = "eq" if cfg["cls"] in v80.PROD_VS_SCALE_CLASSES else "au" if name == "GLDM" else "fixed"
        scale = equity_scale if group == "eq" else gold_scale if group == "au" else 1.
        base, signal = row[f"exposure::{name}"], row[f"signal::{name}"]
        risk = base * signal * scale
        cash[group] = cash.get(group, 0.) + base - risk
        expected += risk * (prices[cfg["proxy"]].iloc[-1] / prices[cfg["proxy"]].iloc[-2] - 1)
    cash_return = prices["BIL"].iloc[-1] / prices["BIL"].iloc[-2] - 1
    spread = v80.PROD_VS_SPREAD_BPS / 10000 / v80.US_TRADING_DAYS
    expected += sum(value * cash_return - max(-value, 0.) * spread for value in cash.values())
    assert actual.iloc[-1] == pytest.approx(expected, abs=1e-14)
    assert fee.eq(0).all()


@pytest.mark.parametrize("scale", [.5, 1., 1.8])
def test_unchanged_scale_transition_agrees_with_ordinary_account_when_no_gap(v80, monkeypatch, scale):
    prices, ledger = components_case(v80)
    opens = {ticker: prices[ticker].shift().fillna(prices[ticker].iloc[0]) for ticker in prices}
    # The last day's movement is entirely intraday. No prior gap/state drift
    # separates the two arithmetic paths, so they have the same exact oracle.
    monkeypatch.setattr(v80, "_subc_absolute_scale", lambda price, index, *args: pd.Series(scale, index=index))
    monkeypatch.setattr(v80, "_subc_relative_scale", lambda price, index, *args: pd.Series(scale, index=index))
    ordinary, _, _ = v80._apply_subc_vol_scaling(ledger["base_return"], prices, components=ledger, spread_bps=0.)
    groups = [[name for name, cfg in v80.PROD_PORTFOLIO.items() if cfg["cls"] in v80.PROD_VS_SCALE_CLASSES], ["GLDM"]]
    expected = 0.
    for group in groups:
        ret, fee = v80._subc_scale_transition_account(ledger, group, 1, scale, scale, prices, opens, True,
                                                     0., v80.PROD_VS_REBAL_COST_BPS / 10000)
        expected += ret
        assert fee == pytest.approx(0., abs=1e-14)
    for name in set(v80.PROD_PORTFOLIO) - set(sum(groups, [])):
        expected += ledger[f"contribution::{name}"].iloc[-1]
    assert ordinary.iloc[-1] == pytest.approx(expected, abs=1e-13)


@pytest.mark.parametrize("start,end", [("2026-09-25", "2026-09-30"), ("2026-07-03", "2026-07-07"), ("2026-10-01", "2026-10-09")])
def test_holiday_query_matches_separate_notional_accounts(v80, start, end):
    history, clipped = {}, {}
    for i, name in enumerate(v80.PERFORMANCE_COMBO_ORDER):
        dates = v80._performance_expected_sessions(name, pd.Timestamp(start) - pd.Timedelta(days=15), end)
        history[name] = pd.Series((i + 1) * .001 + np.arange(len(dates)) * .0001, index=dates)
        clipped[name] = history[name].loc[start:end]
    actual = v80._performance_combined_daily_returns(clipped, history_returns=history, query_start=start)
    union = pd.DatetimeIndex(sorted(set().union(*(part.index for part in clipped.values()))))
    combined_value = np.zeros(len(union))
    for name, series in clipped.items():
        notional = v80._performance_combo_weights()[name]
        values = []
        for day in union:
            notional *= 1 + series.get(day, 0.)
            values.append(notional)
        combined_value += np.array(values)
    expected = combined_value / np.r_[1., combined_value[:-1]] - 1
    assert actual.index.equals(union)
    np.testing.assert_allclose(actual, expected, atol=1e-14, rtol=0.)


def test_missing_tail_session_is_never_treated_as_closed(v80):
    history = {}
    for name in v80.PERFORMANCE_COMBO_ORDER:
        dates = v80._performance_expected_sessions(name, "2026-09-21", "2026-09-30")
        history[name] = pd.Series(.001, index=dates)
    clipped = {name: series.loc["2026-09-25":] for name, series in history.items()}
    clipped["Sub-C"] = clipped["Sub-C"].iloc[:-1]
    with pytest.raises(ValueError, match="Sub-C: missing market-session"):
        v80._performance_combined_daily_returns(clipped, history_returns=history, query_start="2026-09-25")


@pytest.mark.parametrize("clock,expected", [("2026-12-31 22:00", True), ("2027-01-01 05:00", False), ("2027-01-04 23:00", False)])
def test_native_annual_info_expires_at_close(v80, monkeypatch, clock, expected):
    monkeypatch.setattr(v80, "beijing_now", lambda: pd.Timestamp(clock))
    base = {name: cfg["w"] for name, cfg in v80.PROD_PORTFOLIO.items()}
    names = list(base)
    base[names[0]] += .01
    base[names[1]] -= .01
    row = {f"exposure::{name}": value for name, value in base.items()}
    row.update({f"close_weight::{name}": value for name, value in base.items()})
    ledger = pd.DataFrame([row], index=pd.to_datetime(["2026-12-30"]))
    info = dict(asset_momentum_signal=dict.fromkeys(base, 1.), current_scale=1., next_scale=1., gold_current_scale=1., gold_next_scale=1.)
    native = v80._subc_add_annual_action_info(info, ledger)
    assert native["annual_rebalance_due"] == expected


@pytest.mark.parametrize("now", ["2026-10-23 00:00", "2026-10-23 04:00", "2026-10-23 21:30"])
def test_clock_does_not_mutate_or_depend_on_unrelated_b_prices(v80, now):
    frame = pd.DataFrame({"SPY": [100.]}, index=pd.to_datetime(["2026-10-22"]))
    before = frame.copy(deep=True)
    clock = v80._subc_query_clock(frame, now=now)
    changed_price = frame * 1000
    assert clock == v80._subc_query_clock(changed_price, now=now)
    pd.testing.assert_frame_equal(frame, before)

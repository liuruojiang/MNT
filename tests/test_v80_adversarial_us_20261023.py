"""Offline adversarial contracts for Sub-B's strict public runner boundary.

Synthetic data tests calendar rejection only; this is not a performance backtest.
The default network loader already validates raw calendars. These probes cover
research/cache callers which invoke a strict runner directly.
"""
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    path = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_us_audit_20261023", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def offline(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Audit must not request network or LLM")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.poe, "call", forbidden)


@pytest.fixture
def prices(v80):
    dates = v80._expected_us_ohlc_index("2022-01-03", "2024-10-01")
    x = np.arange(len(dates))
    assets = sorted(set(v80.US_ROT_POOL + v80._v80_b78_US_ROT_POOL + ["BIL", "SPY", "TLT"]))
    return pd.DataFrame({asset: 100 * np.exp((0.0002 + i * 0.00002) * x
                       + 0.002 * np.sin(x / (3 + i)))
                         for i, asset in enumerate(assets)}, index=dates)


@pytest.mark.parametrize("runner", ["_run_v80_subb_v78", "_run_v80_subb_v79"])
def test_complete_calendar_positive_control(v80, prices, runner):
    result = getattr(v80, runner)(prices, us_open={a: prices[a] for a in prices},
                                  strict_open_execution=True)
    assert pd.Timestamp("2024-09-17") in result.index
    assert np.isfinite(result["return"]).all()


@pytest.mark.parametrize("runner", ["_run_v80_subb_v78", "_run_v80_subb_v79"])
def test_strict_runner_rejects_missing_nonexecution_session(v80, prices, runner):
    missing = pd.Timestamp("2024-09-17")
    assert v80._is_us_market_session(missing)
    incomplete = prices.drop(index=missing)
    with pytest.raises((ValueError, v80.poe.BotError), match="(?i)(session|calendar|gap|missing)"):
        getattr(v80, runner)(incomplete, us_open={a: incomplete[a] for a in incomplete},
                             strict_open_execution=True)


@pytest.mark.parametrize("rebuilder", ["_v80_b78_rebuild_subb_account_execution_costs",
                                        "_rebuild_subb_account_execution_costs"])
def test_nasdaq_repaired_open_preserves_known_same_day_adjustment(v80, rebuilder):
    """A 0.5% adjustment-factor step cannot create a profit on a flat entry day."""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04",
                            "2024-01-05", "2024-01-08"])
    primary = pd.DataFrame({"open": [99.5, 99.5, 99.5, np.nan, 100.],
                            "close": [99.5, 99.5, 99.5, 100., 100.]}, index=dates)
    fallback = pd.DataFrame({"open": 100., "close": 100.}, index=dates)
    execution_day = pd.Timestamp("2024-01-05")
    repaired, count = v80._merge_same_ticker_gap_prices(
        primary, fallback, [execution_day], "QQQ")
    assert count == 1
    v80._assert_us_internal_price_history({"QQQ": repaired}, ["QQQ"])
    known_adjustment = primary.loc[execution_day, "close"] / fallback.loc[execution_day, "close"]
    correct_open = fallback.loc[execution_day, "open"] * known_adjustment
    closes = pd.DataFrame({"QQQ": primary["close"], "BIL": 100.}, index=dates)
    model = pd.DataFrame({"return": 0., "model_w_QQQ": [0., 1.],
                          "model_w_BIL": [1., 0.], "model_target_w_QQQ": 1.,
                          "model_target_w_BIL": 0., "model_rebalanced": [True, False]},
                         index=dates[2:4])
    wrong_opens = {"QQQ": repaired["open"], "BIL": closes["BIL"]}
    correct_opens = {a: s.copy() for a, s in wrong_opens.items()}
    correct_opens["QQQ"].loc[execution_day] = correct_open
    wrong = getattr(v80, rebuilder)(model, closes, wrong_opens, strict_open_execution=True)
    correct = getattr(v80, rebuilder)(model, closes, correct_opens, strict_open_execution=True)
    observed_return = float(wrong.loc[execution_day, "return"])
    correct_return = float(correct.loc[execution_day, "return"])
    print({"runner": rebuilder, "repaired_open": float(repaired.loc[execution_day, "open"]),
           "correct_open": float(correct_open), "repaired_net_return": observed_return,
           "correct_net_return": correct_return,
           "net_return_error_bp": (observed_return - correct_return) * 10000})
    assert observed_return == pytest.approx(correct_return, abs=1e-13)

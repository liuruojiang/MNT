"""Native EMA state regression with synthetic adjusted prices and opens.

The source oracle is the production weekly model itself. No scores, weights,
EMA state or rebalance events are mocked; no performance claim is made.
"""
import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def v80(monkeypatch, tmp_path):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    source = Path(os.environ.get("V80_AUDIT_SOURCE", str(ROOT / "mnt_bot V 8.0 plus.py")))
    name = "v80_native_ema_state_20261022"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(name, None)


def thursday_prices(v80):
    dates = pd.DatetimeIndex([day for day in pd.date_range("2023-01-01", "2026-10-15", freq="B")
                              if v80._is_us_market_session(day)])[-540:]
    assets = sorted(set(v80.SUBB_REQUIRED_PRICE_TICKERS) | set(v80._v80_b78_SUBB_REQUIRED_PRICE_TICKERS))
    rng = np.random.default_rng(811)
    drifts = {asset: -0.08 for asset in assets}
    drifts.update({"QQQ": 0.45, "GLD": 0.35, "DBC": 0.22, "EMXC": 0.08,
                   "BIL": 0.025, "SPY": 0.12})
    returns = np.array([drifts[asset] / 252 for asset in assets])[None, :] + rng.normal(0, 0.001, (len(dates), len(assets)))
    returns[:, assets.index("BIL")] = 0.0001
    close = pd.DataFrame(100 * np.cumprod(1 + returns, axis=0), index=dates, columns=assets)
    quiet = np.random.default_rng(4481)
    for asset, drift in (("QQQ", 0.45), ("GLD", 0.35)):
        close[asset] = 100 * np.cumprod(1 + drift / 252 + quiet.normal(0, 0.00015, len(dates)))
    # Before this Thursday the EMA portfolio still holds DBC. Four daily
    # returns after the preceding signal now raise DBC's inverse-vol penalty.
    for pos, change in zip(range(len(dates) - 5, len(dates) - 1), (0.95, -0.95, 0.95, -0.95)):
        close.iloc[pos, close.columns.get_loc("DBC")] = close["DBC"].iloc[pos - 1] * (1 + change)
    # Solve actual final prices from the EMA recurrence. EMXC's score is only
    # 0.5% above DBC, within the native 5% challenger Buffer. These are prices,
    # not a mock or replacement of the production scoring function.
    alpha = 1 - np.exp(np.log(0.5) / 70)
    for asset, score in {"QQQ": 0.45, "GLD": 0.35, "DBC": 0.200, "EMXC": 0.201}.items():
        previous = close[asset].iloc[:-1].pct_change().ewm(halflife=70, min_periods=70, adjust=False).mean().iloc[-1]
        change = (score / 252 - (1 - alpha) * previous) / alpha
        assert change > -1
        close.loc[dates[-1], asset] = close[asset].iloc[-2] * (1 + change)
    adjusted_open = {asset: close[asset].shift(1).fillna(close[asset].iloc[0]) for asset in assets}
    return close, adjusted_open


def test_thursday_reference_uses_native_predecision_ema_state(v80):
    close, adjusted_open = thursday_prices(v80)
    assert close.index[-1].dayofweek == 3
    # This ordinary Thursday is already a real weekly event in the native
    # calendar. The full production model supplies the independent oracle.
    native = v80._run_v80_subb_v78(close, us_open=adjusted_open, strict_open_execution=True)
    last = native.iloc[-1]
    assert bool(last["subb_pending_model_rebalance"])
    assert last["ema_actual_w_DBC"] > 0.001
    assert 0 < last["ema_w_DBC"] < 0.001
    assert last["ema_w_EMXC"] == 0
    scores = v80._v80_b78_subb_v75_ema_score(close).iloc[-1]
    assert 1 < scores["EMXC"] / scores["DBC"] < 1.05
    original = native.copy(deep=True)
    reference = v80._v80_subb_model_reference_weights(close, native, "B7.8")
    expected = {column[len("target_w_"):]: float(last[column])
                for column in native if column.startswith("target_w_")}
    for asset in set(expected) | set(reference):
        assert reference.get(asset, 0.0) == pytest.approx(expected.get(asset, 0.0), abs=1e-12), asset
    pd.testing.assert_frame_equal(native, original)

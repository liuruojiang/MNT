"""Live B previews are diagnostic; executions remain on the production schedule.

All generated prices in this file are synthetic, including adjusted opens.
They test display and snapshot equivalence, never strategy performance.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def v80():
    spec = importlib.util.spec_from_file_location("v80_live_reference_20261021", ROOT / "mnt_bot V 8.0 plus.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(scope="module")
def market(v80):
    dates = pd.DatetimeIndex([d for d in pd.date_range("2024-01-01", "2026-10-21", freq="B")
                              if v80._is_us_market_session(d)])[-540:]
    assets = sorted(set(v80.SUBB_REQUIRED_PRICE_TICKERS) | set(v80._v80_b78_SUBB_REQUIRED_PRICE_TICKERS))
    rng = np.random.default_rng(8021)
    changes = rng.normal(0.0005, 0.009, (len(dates), len(assets)))
    close = pd.DataFrame(100 * np.exp(changes.cumsum(axis=0)), index=dates, columns=assets)
    close["BIL"] = 100 * np.exp(np.arange(len(dates)) * 0.0001)
    # A Wednesday snapshot changes ranks, while the execution schedule stays put.
    close.loc[dates[-1], "QQQ"] *= 1.28
    close.loc[dates[-1], "DBC"] *= 0.80
    close.loc[dates[-1], "GLD"] *= 1.22
    opens = {asset: close[asset].shift(1).fillna(close[asset].iloc[0]) for asset in assets}
    result = v80._run_v80_subb_variants(close, us_open=opens, strict_open_execution=True)
    return close, opens, result


@pytest.mark.parametrize("label", ["B7.8", "B7.9"])
def test_reference_matches_native_models_if_today_were_a_signal_day(v80, market, monkeypatch, label):
    close, opens, b79 = market
    result = b79.attrs["v80_b78"] if label == "B7.8" else b79
    original = result.copy(deep=True)
    actual = v80._v80_subb_model_reference_weights(close, result, label)
    signal_name = "_v80_b78_us_signal_days" if label == "B7.8" else "_us_signal_days"
    signal_days = getattr(v80, signal_name)
    monkeypatch.setattr(v80, signal_name,
                        lambda frame, start: signal_days(frame, start) | {len(frame) - 1})
    run = v80._run_v80_subb_v78 if label == "B7.8" else v80._run_v80_subb_v79
    forced = run(close, us_open=opens, strict_open_execution=True)
    expected = {col[len("target_w_"):]: float(forced.iloc[-1][col])
                for col in forced if col.startswith("target_w_")}
    for asset in set(actual) | set(expected):
        assert actual.get(asset, 0.0) == pytest.approx(expected.get(asset, 0.0), abs=1e-12)
    # Reading a preview must never alter account holdings, returns, or pending orders.
    pd.testing.assert_frame_equal(result, original)
    assert not bool(result.iloc[-1]["subb_pending_model_rebalance"])
    assert any(abs(row["delta"]) >= 0.0005
               for row in v80._v80_subb_variant_rows(result, label=label, target_weights=actual))


@pytest.mark.parametrize("kind", ["signal", "live_signal", "params", "live_params"])
def test_all_query_surfaces_separate_reference_changes_from_execution(v80, market, kind):
    close, _, result = market
    output = []
    original = result.copy(deep=True)
    info = v80._write_v80_subb_overview(output.append, result, query_kind=kind,
                                       us_intraday="live" in kind, us_rot_close=close, is_signal_day=False)
    text = "".join(output)
    assert text.count("假设今天是周度信号日") == 2
    assert text.count("| ETF | 当前已生效 | 今日模型参考 | 参考差额 |") == 2
    assert "仅供参考，不生成调仓指令" in text
    assert "模型参考不可用" not in text
    assert not info["B7.8"]["is_signal"] and not info["B7.9"]["is_signal"]
    for label, part in (("B7.8", result.attrs["v80_b78"]), ("B7.9", result)):
        rows = v80._v80_subb_variant_rows(part, label=label)
        assert all(abs(item["delta"]) < 1e-12 for item in rows)
    pd.testing.assert_frame_equal(result, original)


def test_preview_failure_is_visible_instead_of_copying_current_weights(v80, market, monkeypatch):
    close, _, result = market

    def unavailable(*args):
        raise ValueError("diagnostic missing input")

    monkeypatch.setattr(v80, "_v80_subb_model_reference_weights", unavailable)
    output = []
    info = v80._write_v80_subb_overview(output.append, result, query_kind="live_signal",
                                       us_rot_close=close, is_signal_day=False)
    assert "".join(output).count("今日模型参考不可用") == 2
    assert "diagnostic missing input" in "".join(output)
    assert all(not item["is_signal"] for item in info.values())


@pytest.mark.parametrize("label", ["B7.8", "B7.9"])
def test_reference_requires_matching_prices_and_component_dates(v80, market, label):
    close, _, b79 = market
    result = (b79.attrs["v80_b78"] if label == "B7.8" else b79).copy(deep=True)
    with pytest.raises(ValueError, match="date"):
        v80._v80_subb_model_reference_weights(close.iloc[:-1], result, label)
    result.attrs["v78_subb_bias"] = result.attrs["v78_subb_bias"].iloc[:-1]
    with pytest.raises(ValueError, match="date"):
        v80._v80_subb_model_reference_weights(close, result, label)


def test_volreg_order_remains_actionable_when_model_preview_is_present(v80, market):
    close, _, baseline = market
    result = baseline.copy(deep=True)
    for label, part in (("B7.9", result), ("B7.8", result.attrs["v80_b78"])):
        last = part.index[-1]
        part.loc[last, "volreg_defense"] = False
        part.loc[last, "volreg_ratio"] = 2.0
        part.loc[last, "subb_pending_volreg_transition"] = True
        covered = v80._v80_b78_US_ROT_VOLREG_SCALE_ASSETS if label == "B7.8" else v80.US_ROT_VOLREG_SCALE_ASSETS
        for asset in covered:
            current = float(part.loc[last, "effective_w_" + asset])
            part.loc[last, "execution_target_w_" + asset] = 0.0
            part.loc[last, "execution_target_w_BIL"] += current
    output = []
    info = v80._write_v80_subb_overview(output.append, result, query_kind="signal",
                                       us_rot_close=close, is_signal_day=False)
    assert "VolReg收盘确认调整" in "".join(output)
    assert "不等待下周周度信号" in "".join(output)
    assert info["B7.8"]["is_signal"] and info["B7.9"]["is_signal"]


@pytest.mark.parametrize("label", ["B7.8", "B7.9"])
def test_missing_leg_scale_is_not_silently_replaced_by_one(v80, market, label):
    close, _, b79 = market
    result = (b79.attrs["v80_b78"] if label == "B7.8" else b79).copy(deep=True)
    result.attrs["v78_subb_bias"].drop(columns="target_vol_scale", inplace=True)
    with pytest.raises(ValueError, match="target_vol_scale"):
        v80._v80_subb_model_reference_weights(close, result, label)


@pytest.mark.parametrize("label", ["B7.8", "B7.9"])
@pytest.mark.parametrize("weight", [0.0, 0.0005, 0.001, 0.001000001, 0.2])
def test_ema_buffer_reads_current_leg_and_native_holding_threshold(v80, market, monkeypatch, label, weight):
    """Native Buffer reads actual leg holdings at its 0.1% cutoff, before decisions."""
    close, _, b79 = market
    result = (b79.attrs["v80_b78"] if label == "B7.8" else b79).copy(deep=True)
    pool = v80._v80_b78_US_ROT_POOL if label == "B7.8" else v80.US_ROT_POOL
    for asset in pool:
        result.loc[result.index[-2:], "ema_actual_w_" + asset] = 0.0
        result.loc[result.index[-1], "ema_w_" + asset] = 0.0
    for asset in ("QQQ", "GLD"):
        result.loc[result.index[-2:], "ema_actual_w_" + asset] = 0.4
    result.loc[result.index[-2], "ema_actual_w_DBC"] = weight
    result.loc[result.index[-1], "ema_actual_w_EMXC"] = weight
    result.loc[result.index[-1], "ema_w_DBC"] = weight
    name = "_v80_b78_us_raw_weights" if label == "B7.8" else "_us_raw_weights"
    raw_weights = getattr(v80, name)
    observed = []

    def record_buffer_state(*args, **kwargs):
        threshold = kwargs.get("abs_threshold", args[4] if len(args) > 4 else None)
        if threshold == 0.15:
            observed.append(kwargs.get("prev_risky"))
        return raw_weights(*args, **kwargs)

    monkeypatch.setattr(v80, name, record_buffer_state)
    v80._v80_subb_model_reference_weights(close, result, label)
    expected = {"QQQ", "GLD"} | ({"EMXC"} if weight > 0.001 else set())
    assert observed == [expected]


@pytest.mark.parametrize("label", ["B7.8", "B7.9"])
@pytest.mark.parametrize("value", [None, np.nan, np.inf, -0.01])
def test_reference_rejects_unresolved_current_ema_leg(v80, market, label, value):
    close, _, b79 = market
    result = (b79.attrs["v80_b78"] if label == "B7.8" else b79).copy(deep=True)
    if value is None:
        result.drop(columns="ema_actual_w_EMXC", inplace=True)
    else:
        result.loc[result.index[-1], "ema_actual_w_EMXC"] = value
    with pytest.raises(ValueError, match="current EMA holding"):
        v80._v80_subb_model_reference_weights(close, result, label)

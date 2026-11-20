"""Offline V8.0 audit probes. Outputs are diagnostics, not portfolio performance."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("audited_v80", ROOT / "mnt_bot V 8.0 plus.py")
v80 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v80)


def short_window():
    # Use retained market observations. Prefer the local historical portfolio replay.
    path = ROOT / "outputs/v80_recert_20260926/l8/cross/formal_daily_returns.csv.gz"
    if path.exists():
        returns = pd.read_csv(path, index_col="date", parse_dates=True)["return_net"]
    else:
        path = ROOT / "tests/fixtures/v80_verified_data_20261025/kmlm_expected_adjusted.csv"
        returns = pd.read_csv(path, index_col="date", parse_dates=True)["adj_close"].pct_change()
    monthly = v80._monthly_returns_from_daily_window(returns, "2025-01-31", "2025-03-03")
    metrics = v80.calc_monthly_metrics(monthly)
    assert len(monthly) == 3 and np.isfinite(metrics["vol"]) and np.isfinite(metrics["sharpe"])
    return dict(source=path.relative_to(ROOT).as_posix(), days_elapsed=31, complete_months=1,
                reported_vol_pct=metrics["vol"], reported_sharpe=metrics["sharpe"])


def crossing_close():
    # Only supply the market quote. Production code appends and marks the live bar.
    prior = pd.Timestamp("2026-11-18")
    raw = {"SPY": pd.DataFrame({"open": [99.0], "close": [100.0]}, index=[prior])}
    with patch.object(v80, "_fetch_us_realtime_close", return_value=(101.0, "2026-11-19", 100.0)):
        v80._supplement_us_today_close(raw, ["SPY"])
    assert raw["SPY"].iloc[-1]["is_live_bar"]
    frame = pd.DataFrame({"SPY": raw["SPY"]["close"]})
    info = dict(current_scale=1.0, next_target_scale=1.5, next_scale=1.5,
                gold_current_scale=1.0, gold_target_scale=1.0, gold_next_scale=1.0)
    observed = []
    for when in ["2026-11-20 04:59:59", "2026-11-20 05:00:01"]:
        clock = v80._subc_query_clock(frame, now=when)
        out = v80._write_v80_subc_overview(lambda message: None, info, query_kind="live_signal", clock=clock)
        observed.append(dict(displayed_at_beijing=when, unconfirmed=clock["unconfirmed"],
                             is_signal=out["is_signal"]))
    assert [row["is_signal"] for row in observed] == [False, True]
    return observed


def quantities():
    # Diagnostic only. Timing off, constant scale, no fees/spread, two +10% equity days.
    dates = pd.to_datetime(["2026-11-16", "2026-11-17", "2026-11-18"])
    equities = [cfg["proxy"] for cfg in v80.PROD_PORTFOLIO.values() if cfg["cls"] == "equity"]
    names = {cfg["proxy"] for cfg in v80.PROD_PORTFOLIO.values()} | {"SPY", "BIL"}
    close = pd.DataFrame(100.0, index=dates, columns=sorted(names))
    for name in equities:
        close[name] = [100.0, 110.0, 121.0]
    signals = pd.DataFrame(1.0, index=[dates[-1]], columns=close.columns)
    components = v80._compute_daily_subc_components(close, signals, v80.PROD_PORTFOLIO, "BIL")
    equity_scale = pd.Series(1.5, index=components.index)
    gold_scale = pd.Series(1.0, index=components.index)
    with patch.object(v80, "_subc_absolute_scale", return_value=equity_scale), \
            patch.object(v80, "_subc_relative_scale", return_value=gold_scale):
        returns, _, costs = v80._apply_subc_vol_scaling(components["base_return"], close,
            components=components, spread_bps=0.0, strict_open_execution=True)
    equity_base = sum(cfg["w"] for cfg in v80.PROD_PORTFOLIO.values() if cfg["cls"] == "equity")
    hold_units = 1.0 + equity_base * 1.5 * (121.0 / 100.0 - 1.0)
    model = float((1 + returns).prod())
    assert not components["annual_rebalanced"].any() and costs.eq(0.0).all()
    assert np.isclose(1 + returns.iloc[0], 1 + equity_base * 1.5 * 0.1)
    assert abs(model - hold_units) > 0.001
    return dict(two_day_model_nav=model, two_day_constant_units_nav=hold_units,
                reported_scaling_cost=float(costs.sum()))


if __name__ == "__main__":
    print(json.dumps(dict(short_window=short_window(), crossing_close=crossing_close(),
                          subc_untraded_quantity_limit=quantities()), indent=2))

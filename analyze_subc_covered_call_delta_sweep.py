"""Approximate Sub-C covered-call overlay sweep.

This is a research helper, not production strategy logic. It reuses the
Sub-C functions and constants from ``mnt_bot V 7.0 plus.py`` and adds an
approximate covered-call overlay using Black-Scholes prices with historical
realized volatility as the IV proxy.
"""

from __future__ import annotations

import math
import sys
import types
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
STRATEGY_FILE = ROOT / "mnt_bot V 7.0 plus.py"
US_DATA_FILE = ROOT / "mnt_strategy_data_us.csv"
OUT_DIR = ROOT / "docs" / "subc_covered_call_roll_sweep_20260423"


DELTAS = (0.10, 0.15, 0.20)
ROLL_DAYS_BEFORE_EXPIRY = (0, 10, 20)
HV_LOOKBACK = 63
MIN_IV = 0.08
MAX_IV = 1.50
RISK_FREE = 0.0
TRADING_DAYS = 252


_N = NormalDist()


def _install_poe_stubs() -> None:
    """Allow executing the Poe bot file without the Poe runtime."""
    if "fastapi_poe" not in sys.modules:
        fastapi_poe = types.ModuleType("fastapi_poe")
        fastapi_poe_types = types.ModuleType("fastapi_poe.types")

        class SettingsResponse:  # noqa: D401 - tiny runtime stub
            """Stub matching the constructor behavior needed at import time."""

            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        fastapi_poe_types.SettingsResponse = SettingsResponse
        fastapi_poe.types = fastapi_poe_types
        sys.modules["fastapi_poe"] = fastapi_poe
        sys.modules["fastapi_poe.types"] = fastapi_poe_types


def load_strategy_namespace() -> dict:
    _install_poe_stubs()

    class BotError(Exception):
        pass

    class _NullMessage:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def write(self, *_args, **_kwargs):
            return None

        def attach_file(self, *_args, **_kwargs):
            return None

    poe_stub = types.SimpleNamespace(
        BotError=BotError,
        start_message=lambda: _NullMessage(),
        update_settings=lambda *_args, **_kwargs: None,
        default_chat="",
        query=types.SimpleNamespace(text="", attachments=[]),
        call=lambda *_args, **_kwargs: "",
    )
    ns = {"__name__": "mnt_bot_v70_loaded", "poe": poe_stub}
    code = STRATEGY_FILE.read_text(encoding="utf-8", errors="replace")
    exec(compile(code, str(STRATEGY_FILE), "exec"), ns)
    return ns


def build_us_prod_daily(ns: dict) -> pd.DataFrame:
    wide = pd.read_csv(US_DATA_FILE, parse_dates=["date"]).set_index("date")
    wide = wide.apply(pd.to_numeric, errors="coerce")

    prod_portfolio = ns["PROD_PORTFOLIO"]
    prod_cash = ns["PROD_CASH"]
    prod_proxies = list({cfg["proxy"] for cfg in prod_portfolio.values()} | {prod_cash})

    late_prod = {"BTC-USD", "DBMF"}
    core = [t for t in prod_proxies if t not in late_prod and t in wide.columns]
    us_prod_daily = pd.concat([wide[t].rename(t) for t in core], axis=1).ffill().dropna()
    for ticker in late_prod:
        if ticker in wide.columns:
            us_prod_daily = us_prod_daily.join(wide[ticker].rename(ticker), how="left")

    stock_prod = [t for t in prod_proxies if t in wide.columns and t != "BTC-USD"]
    if stock_prod:
        last_stock_date = max(wide[t].dropna().index[-1] for t in stock_prod if wide[t].notna().any())
        us_prod_daily = us_prod_daily.loc[:last_stock_date]

    for live_ticker in prod_portfolio.keys():
        if live_ticker in wide.columns and live_ticker not in us_prod_daily.columns:
            us_prod_daily[live_ticker] = wide[live_ticker].reindex(us_prod_daily.index)
    return us_prod_daily


def build_subc_returns(ns: dict, us_prod_daily: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.DataFrame]:
    prod_monthly = us_prod_daily.resample("M").last()
    last_daily = us_prod_daily.index[-1]
    today_period = pd.Timestamp("2026-04-22").to_period("M")
    if last_daily.to_period("M") == prod_monthly.index[-1].to_period("M") == today_period:
        prod_monthly = prod_monthly.iloc[:-1]

    prod_sig_a = ns["make_abs_mom_signals"](prod_monthly, ns["PROD_ABS_MOM_LB"])
    prod_sig_b = ns["make_sma_signals"](prod_monthly, ns["PROD_SMA_WINDOW"], ns["PROD_SMA_BAND"])
    if not ns["PROD_USE_TIMING"]:
        prod_sig_a = pd.DataFrame(1.0, index=prod_sig_a.index, columns=prod_sig_a.columns)
        prod_sig_b = prod_sig_a.copy()

    raw = ns["_compute_daily_subc_phased"](
        us_prod_daily,
        prod_sig_a,
        ns["PROD_CASH"],
        prod_sig_b=prod_sig_b,
        blend_a=ns["PROD_BLEND_A"],
    )
    scaled, actual_scale, costs = ns["_apply_subc_vol_scaling"](raw, us_prod_daily)
    baseline = ns["_get_subc_daily_ret"](us_prod_daily, prod_sig_a, prod_sig_b=prod_sig_b)
    max_abs_diff = (baseline - scaled).abs().max()
    if pd.isna(max_abs_diff) or max_abs_diff > 1e-12:
        raise RuntimeError(f"Sub-C parity failed: max_abs_diff={max_abs_diff}")
    return baseline, raw, actual_scale, prod_sig_a


def phase_portfolio(ns: dict, date: pd.Timestamp) -> dict:
    if date < ns["DBMF_BT_START"]:
        return ns["PROD_PORTFOLIO_PRE_DBMF"]
    if date < ns["BTC_BT_START"]:
        return ns["PROD_PORTFOLIO_BT"]
    return ns["PROD_PORTFOLIO"]


def bs_call_price(s: float, k: float, t: float, sigma: float, r: float = RISK_FREE) -> float:
    if s <= 0 or k <= 0 or t <= 0 or sigma <= 0:
        return 0.0
    sqrt_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return s * _N.cdf(d1) - k * math.exp(-r * t) * _N.cdf(d2)


def strike_for_call_delta(s: float, delta: float, t: float, sigma: float, r: float = RISK_FREE) -> float:
    d1 = _N.inv_cdf(delta)
    return s * math.exp((r + 0.5 * sigma * sigma) * t - d1 * sigma * math.sqrt(t))


def historical_vol(prices: pd.Series, entry: pd.Timestamp) -> float | None:
    ret = prices.loc[:entry].pct_change().dropna().tail(HV_LOOKBACK)
    if len(ret) < HV_LOOKBACK:
        return None
    vol = float(ret.std(ddof=1) * math.sqrt(TRADING_DAYS))
    return float(np.clip(vol, MIN_IV, MAX_IV)) if np.isfinite(vol) else None


def month_expiries(ret_index: pd.DatetimeIndex) -> dict[pd.Period, pd.Timestamp]:
    return {
        period: pd.Timestamp(dates.iloc[-1])
        for period, dates in pd.Series(ret_index, index=ret_index).groupby(ret_index.to_period("M"))
        if len(dates) > 0
    }


def next_expiry_after(expiries: dict[pd.Period, pd.Timestamp], expiry: pd.Timestamp) -> pd.Timestamp | None:
    future = [dt for dt in expiries.values() if dt > expiry]
    return min(future) if future else None


def first_roll_date(
    ret_index: pd.DatetimeIndex,
    entry: pd.Timestamp,
    expiry: pd.Timestamp,
    roll_days_before_expiry: int,
) -> pd.Timestamp:
    if roll_days_before_expiry <= 0:
        return expiry
    candidates = ret_index[
        (ret_index > entry)
        & (ret_index <= expiry)
        & ((expiry - ret_index).days <= roll_days_before_expiry)
    ]
    if len(candidates) == 0:
        return expiry
    return pd.Timestamp(candidates[0])


def covered_call_overlay(
    ns: dict,
    us_prod_daily: pd.DataFrame,
    ret_index: pd.DatetimeIndex,
    actual_scale: pd.Series,
    delta: float,
    roll_days_before_expiry: int = 0,
) -> tuple[pd.Series, pd.DataFrame]:
    overlay = pd.Series(0.0, index=ret_index)
    events = []
    expiries = month_expiries(ret_index)

    entry = pd.Timestamp(ret_index[0])
    expiry = expiries.get(entry.to_period("M"))
    if expiry is None or expiry <= entry:
        expiry = next_expiry_after(expiries, entry)

    while expiry is not None and entry < ret_index[-1]:
        if expiry <= entry:
            expiry = next_expiry_after(expiries, expiry)
            continue
        exit_date = first_roll_date(ret_index, entry, expiry, roll_days_before_expiry)
        t_years_entry = max((expiry - entry).days / 365.25, 1.0 / 365.25)
        t_years_exit = max((expiry - exit_date).days / 365.25, 0.0)
        scale = float(actual_scale.reindex(ret_index).ffill().loc[entry])
        portfolio = phase_portfolio(ns, entry)

        for name, cfg in portfolio.items():
            proxy = cfg["proxy"]
            if proxy not in us_prod_daily.columns:
                continue
            prices = us_prod_daily[proxy].dropna()
            if entry not in prices.index or exit_date not in prices.index:
                continue
            sigma = historical_vol(prices, entry)
            if sigma is None:
                continue
            s0 = float(prices.loc[entry])
            sx = float(prices.loc[exit_date])
            if s0 <= 0 or sx <= 0:
                continue
            strike = strike_for_call_delta(s0, delta, t_years_entry, sigma)
            premium = bs_call_price(s0, strike, t_years_entry, sigma)
            close_value = (
                max(sx - strike, 0.0)
                if exit_date == expiry or t_years_exit <= 0
                else bs_call_price(sx, strike, t_years_exit, sigma)
            )
            notional = float(cfg["w"]) * scale
            premium_ret = notional * premium / s0
            close_ret = notional * close_value / s0
            overlay.loc[entry] += premium_ret
            overlay.loc[exit_date] -= close_ret
            events.append(
                {
                    "period": str(entry.to_period("M")),
                    "entry": entry.date().isoformat(),
                    "expiry": expiry.date().isoformat(),
                    "exit": exit_date.date().isoformat(),
                    "roll_days_before_expiry": roll_days_before_expiry,
                    "days_to_expiry_at_entry": (expiry - entry).days,
                    "days_to_expiry_at_exit": (expiry - exit_date).days,
                    "name": name,
                    "proxy": proxy,
                    "weight": cfg["w"],
                    "scale": scale,
                    "delta": delta,
                    "iv_proxy": sigma,
                    "entry_price": s0,
                    "exit_price": sx,
                    "strike": strike,
                    "premium_pct_notional": premium / s0,
                    "close_cost_pct_notional": close_value / s0,
                    "portfolio_premium_ret": premium_ret,
                    "portfolio_close_ret": close_ret,
                    "portfolio_net_ret": premium_ret - close_ret,
                    "itm_at_exit": sx > strike,
                    "expired": exit_date == expiry,
                }
            )
        next_expiry = next_expiry_after(expiries, expiry)
        if next_expiry is None:
            break
        entry = exit_date if roll_days_before_expiry > 0 else min(
            ret_index[ret_index > expiry], default=ret_index[-1]
        )
        expiry = next_expiry
    return overlay, pd.DataFrame(events)


def metrics(ret: pd.Series) -> dict:
    ret = ret.dropna()
    nav = (1.0 + ret).cumprod()
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    peak = nav.cummax()
    dd = nav / peak - 1.0
    annual = nav.iloc[-1] ** (1.0 / years) - 1.0
    vol = ret.std(ddof=1) * math.sqrt(TRADING_DAYS)
    sharpe = ret.mean() / ret.std(ddof=1) * math.sqrt(TRADING_DAYS) if ret.std(ddof=1) > 0 else np.nan
    monthly = ret.groupby(ret.index.to_period("M")).apply(lambda x: (1.0 + x).prod() - 1.0)
    return {
        "start": ret.index[0].date().isoformat(),
        "end": ret.index[-1].date().isoformat(),
        "days": len(ret),
        "years": years,
        "total_return": nav.iloc[-1] - 1.0,
        "annual": annual,
        "vol": vol,
        "sharpe": sharpe,
        "max_dd": dd.min(),
        "calmar": annual / abs(dd.min()) if dd.min() < 0 else np.nan,
        "monthly_win_rate": float((monthly > 0).mean()),
    }


def windowed_metrics(ret_map: dict[str, pd.Series]) -> pd.DataFrame:
    common_end = min(s.dropna().index[-1] for s in ret_map.values())
    windows = {
        "full": None,
        "10Y": common_end - pd.DateOffset(years=10),
        "5Y": common_end - pd.DateOffset(years=5),
        "3Y": common_end - pd.DateOffset(years=3),
        "1Y": common_end - pd.DateOffset(years=1),
    }
    rows = []
    for window, start in windows.items():
        for name, ret in ret_map.items():
            cur = ret.loc[:common_end]
            if start is not None:
                cur = cur.loc[cur.index >= start]
            if len(cur) < 60:
                continue
            row = {"window": window, "strategy": name}
            row.update(metrics(cur))
            rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    ns = load_strategy_namespace()
    us_prod_daily = build_us_prod_daily(ns)
    baseline, raw, actual_scale, _prod_sig_a = build_subc_returns(ns, us_prod_daily)

    ret_map = {"baseline": baseline}
    event_frames = []
    daily = pd.DataFrame({"baseline": baseline, "raw_subc": raw, "actual_scale": actual_scale})

    for roll_days in ROLL_DAYS_BEFORE_EXPIRY:
        roll_label = "expiry" if roll_days == 0 else f"roll_{roll_days}d"
        for delta in DELTAS:
            overlay, events = covered_call_overlay(
                ns,
                us_prod_daily,
                baseline.index,
                actual_scale,
                delta,
                roll_days_before_expiry=roll_days,
            )
            label = f"cc_{roll_label}_delta_{delta:.2f}"
            ret_map[label] = baseline.add(overlay, fill_value=0.0)
            daily[f"{label}_overlay"] = overlay
            daily[label] = ret_map[label]
            events["strategy"] = label
            event_frames.append(events)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    metric_df = windowed_metrics(ret_map)
    event_df = pd.concat(event_frames, ignore_index=True) if event_frames else pd.DataFrame()

    metric_path = OUT_DIR / "metrics.csv"
    event_path = OUT_DIR / "option_events.csv"
    daily_path = OUT_DIR / "daily_returns.csv"
    metric_df.to_csv(metric_path, index=False, encoding="utf-8-sig")
    event_df.to_csv(event_path, index=False, encoding="utf-8-sig")
    daily.to_csv(daily_path, index_label="date", encoding="utf-8-sig")

    pd.set_option("display.width", 180)
    pd.set_option("display.max_columns", 20)
    print(f"data={US_DATA_FILE}")
    print(f"date_range={baseline.index[0].date()}..{baseline.index[-1].date()} rows={len(baseline)}")
    print(f"outputs={OUT_DIR}")
    print(metric_df[metric_df["window"].isin(["full", "5Y", "3Y", "1Y"])][
        ["window", "strategy", "annual", "vol", "sharpe", "max_dd", "total_return", "monthly_win_rate"]
    ].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    if not event_df.empty:
        summary = event_df.groupby("strategy").agg(
            events=("strategy", "size"),
            itm_exit_rate=("itm_at_exit", "mean"),
            avg_entry_dte=("days_to_expiry_at_entry", "mean"),
            avg_exit_dte=("days_to_expiry_at_exit", "mean"),
            avg_premium=("premium_pct_notional", "mean"),
            avg_net=("portfolio_net_ret", "mean"),
        )
        print("\noption_event_summary")
        print(summary.to_string(float_format=lambda x: f"{x:.4f}"))


if __name__ == "__main__":
    main()

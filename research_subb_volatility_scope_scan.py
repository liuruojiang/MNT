#!/usr/bin/env python3
"""Formal V7.8/V7.9 Sub-B volatility-scope research.

The production scripts are imported as the source of truth.  The four selection
legs, T-close -> T+1 adjusted-open execution, turnover costs, SPY VolReg and the
DBC profit guard are preserved.  Only the target-vol signal/scope is varied.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / "quant_param_scan_runs" / (
    "20260812_a_share_us_momentum_combo_v7_8_v7_9_sub_b_"
    "sub_b_volatility_sizing_scope_stock_signal_nonstock_delever_scope"
)
VERSION_FILES = {
    "V7.8": ROOT / "mnt_bot V 7.8 plus.py",
    "V7.9": ROOT / "mnt_bot V 7.9 plus.py",
}
WINDOWS = {"full": None, "10Y": 10, "5Y": 5, "3Y": 3, "1Y": 1}

ASSET_CLASS = {
    "QQQ": "stock",
    "EMXC": "stock",
    "EFA": "stock",
    "GLD": "gold",
    "AGG": "bond",
    "DBC": "commodity",
    "UUP": "currency",
    "DBMF": "cta",
    "KMLM": "cta",
    "BTC-USD": "bitcoin",
}
NONSTOCK_CLASSES = frozenset({"gold", "bond", "commodity", "currency", "cta", "bitcoin"})


@dataclass(frozen=True)
class Candidate:
    name: str
    stock_mode: str
    nonstock_mode: str = "fixed"
    groups: frozenset[str] = frozenset()
    short: int = 30
    long: int = 252
    floor: float = 0.50
    ceiling: float = 1.00
    stock_target: float | None = None
    description: str = ""


def candidate_grid() -> list[Candidate]:
    core = [
        Candidate("production_current", "current", description="four-leg self-vol scalar; production scope"),
        Candidate("no_target_vol", "none", description="all asset target-vol scaling disabled"),
        Candidate("spy_stock_nonstock_1x", "spy", description="SPY manages stocks; every non-stock stays at 1x"),
        Candidate("spy_stock_legself_down_all_nonstock", "spy", "leg_self", NONSTOCK_CLASSES,
                  description="SPY manages stocks; current leg self-vol scalar may only reduce non-stocks"),
    ]
    for group in ("gold", "bond", "commodity", "cta", "bitcoin", "currency"):
        core.append(Candidate(
            f"spy_stock_{group}_ownrel_s30_l252_f50",
            "spy", "own_relative", frozenset({group}),
            description=f"SPY manages stocks; only {group} may de-risk by own 30d/252d volatility",
        ))
    core.extend([
        Candidate("spy_stock_all_nonstock_ownrel_s30_l252_f50", "spy", "own_relative", NONSTOCK_CLASSES,
                  description="SPY manages stocks; all non-stocks independently de-risk, 30/252 floor 0.50"),
        Candidate("spy_stock_all_except_btc_ownrel_s30_l252_f50", "spy", "own_relative",
                  NONSTOCK_CLASSES - {"bitcoin"},
                  description="same as all non-stocks, but BTC is fixed at 1x"),
        Candidate("spy_stock_all_nonstock_ownrel_s20_l252_f50", "spy", "own_relative", NONSTOCK_CLASSES,
                  short=20, long=252, floor=0.50, description="short-window sensitivity"),
        Candidate("spy_stock_all_nonstock_ownrel_s40_l252_f50", "spy", "own_relative", NONSTOCK_CLASSES,
                  short=40, long=252, floor=0.50, description="short-window sensitivity"),
        Candidate("spy_stock_all_nonstock_ownrel_s30_l126_f50", "spy", "own_relative", NONSTOCK_CLASSES,
                  short=30, long=126, floor=0.50, description="long-window sensitivity"),
        Candidate("spy_stock_all_nonstock_ownrel_s30_l252_f25", "spy", "own_relative", NONSTOCK_CLASSES,
                  short=30, long=252, floor=0.25, description="lower-floor sensitivity"),
        Candidate("spy_stock_all_nonstock_ownrel_s30_l252_f75", "spy", "own_relative", NONSTOCK_CLASSES,
                  short=30, long=252, floor=0.75, description="higher-floor sensitivity"),
    ])
    return core


def load_module(label: str, path: Path):
    name = "subb_scope_" + label.lower().replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    # V7.8 keeps Top3 as function defaults; V7.9 promotes Top2 to a constant.
    if not hasattr(module, "US_ROT_TOP_N"):
        module.US_ROT_TOP_N = 3
    return module


def fetch_shared_raw(modules: dict[str, object]):
    tickers = {"IBIT", "EEM"}
    for m in modules.values():
        tickers.update(m.SUBB_REQUIRED_PRICE_TICKERS)
        tickers.add(m.US_ROT_EMXC_BT_PROXY)
    raw, sources = {}, {}
    for ticker in sorted(tickers):
        print(f"[data] {ticker}", flush=True)
        frame, source = modules["V7.8"].fetch_yahoo(ticker, start_date="2003-01-01")
        if frame is None or len(frame) <= 50:
            raise RuntimeError(f"missing usable formal price history: {ticker} ({source})")
        if "Yahoo" not in str(source):
            raise RuntimeError(f"formal run requires Yahoo adjusted OHLC, got {ticker}: {source}")
        raw[ticker] = frame.copy()
        sources[ticker] = str(source)
    return raw, sources


def build_version_data(m, raw: dict[str, pd.DataFrame]):
    rot_tickers = list(dict.fromkeys(m.US_ROT_POOL + ["BIL"] + list(m.SUBB_INFLATION_GATE_TICKERS)))
    late = m._us_rot_late_history_tickers()
    core = [ticker for ticker in rot_tickers if ticker not in late]
    if "EMXC" in m.US_ROT_POOL and m.US_ROT_EMXC_BT_PROXY not in core:
        core.append(m.US_ROT_EMXC_BT_PROXY)
    missing = [ticker for ticker in core if ticker not in raw]
    if missing:
        raise RuntimeError(f"missing core prices: {missing}")
    close = pd.concat(
        [raw[ticker][["close"]].rename(columns={"close": ticker}) for ticker in core],
        axis=1,
    ).ffill().dropna()
    if "EMXC" in m.US_ROT_POOL:
        proxy = close[m.US_ROT_EMXC_BT_PROXY].copy()
        hybrid = proxy.rename("EMXC")
        emxc = raw["EMXC"]["close"].reindex(hybrid.index)
        switch = hybrid.index >= m.US_ROT_EMXC_BT_START
        first = emxc.loc[switch].first_valid_index()
        if first is not None:
            factor = hybrid.loc[first] / emxc.loc[first]
            hybrid.loc[switch] = emxc.loc[switch] * factor
        close["EMXC"] = hybrid
        if m.US_ROT_EMXC_BT_PROXY not in m.US_ROT_POOL:
            close = close.drop(columns=[m.US_ROT_EMXC_BT_PROXY])
    for ticker in late:
        if ticker == "EMXC":
            continue
        if ticker in raw:
            close = close.join(raw[ticker][["close"]].rename(columns={"close": ticker}), how="left")
    if "BTC-USD" in close.columns:
        close["BTC-USD"] = m.build_ibit_spliced(pd.DataFrame({
            "BTC-USD": close["BTC-USD"],
            "IBIT": raw["IBIT"]["close"].reindex(close.index),
        }))
    close["SPY"] = raw["SPY"]["close"].reindex(close.index)
    latest = max(raw[ticker].index[-1] for ticker in rot_tickers if ticker in raw and ticker != "BTC-USD")
    close = close.loc[:latest]
    open_prices = m._build_us_open_execution_dict(raw)
    return close, open_prices


class ScaleContext:
    def __init__(self, m, close: pd.DataFrame, cfg: Candidate):
        self.m = m
        self.close = close
        self.cfg = cfg
        returns = close.pct_change(fill_method=None)
        spy_rv = returns["SPY"].rolling(m.US_ROT_VOL_WINDOW).std() * math.sqrt(m.US_TRADING_DAYS)
        self.spy_rv_lag = spy_rv.shift(1)
        self.relative: dict[str, pd.Series] = {}
        if cfg.nonstock_mode == "own_relative":
            for asset in m.US_ROT_POOL:
                if asset not in returns:
                    continue
                short_rv = returns[asset].rolling(cfg.short).std() * math.sqrt(m.US_TRADING_DAYS)
                long_rv = returns[asset].rolling(cfg.long).std() * math.sqrt(m.US_TRADING_DAYS)
                ratio = (long_rv / short_rv).replace([np.inf, -np.inf], np.nan).clip(cfg.floor, cfg.ceiling)
                self.relative[asset] = ratio.shift(1)

    @staticmethod
    def _value(series: pd.Series | None, dt, default=1.0) -> float:
        if series is None or dt not in series.index or pd.isna(series.loc[dt]):
            return float(default)
        return float(series.loc[dt])

    def stock_scale(self, dt, target_vol: float, max_leverage: float) -> float:
        if self.cfg.stock_mode != "spy":
            return 1.0
        rv = self._value(self.spy_rv_lag, dt, default=np.nan)
        if not np.isfinite(rv) or rv <= 0.001:
            return 1.0
        effective_target = target_vol if self.cfg.stock_target is None else float(self.cfg.stock_target)
        return float(np.clip(effective_target / rv, 0.05, max_leverage))

    def transform(self, raw_weights: dict[str, float], dt, target_vol: float,
                  max_leverage: float, leg_self_scale: float) -> tuple[dict[str, float], dict[str, float]]:
        stock_scale = self.stock_scale(dt, target_vol, max_leverage)
        out, scales = {}, {"stock": stock_scale}
        for asset, raw_weight in raw_weights.items():
            if asset == "BIL":
                continue
            cls = ASSET_CLASS.get(asset, "other")
            scale = stock_scale if cls == "stock" else 1.0
            if cls in self.cfg.groups:
                if self.cfg.nonstock_mode == "own_relative":
                    scale = self._value(self.relative.get(asset), dt, default=1.0)
                elif self.cfg.nonstock_mode == "leg_self":
                    scale = min(float(leg_self_scale), 1.0)
            out[asset] = float(raw_weight) * float(scale)
            scales[asset] = float(scale)
        out["BIL"] = max(1.0 - sum(out.values()), 0.0)
        out = self.m._apply_subb_btc_cap(out)
        return out, scales


def _target_from_raw(m, ctx: ScaleContext, raw: dict[str, float], dt,
                     target_vol: float, max_leverage: float, leg_self_scale: float):
    if ctx.cfg.stock_mode == "current":
        return m._apply_subb_btc_cap(m._us_model_b(raw, leg_self_scale)), {"stock": leg_self_scale}
    if ctx.cfg.stock_mode == "none":
        return ctx.transform(raw, dt, target_vol, max_leverage, 1.0)
    return ctx.transform(raw, dt, target_vol, max_leverage, leg_self_scale)


def run_official_candidate(m, close_df, us_open, ctx: ScaleContext):
    ranking_codes = list(m.US_ROT_BASE_POOL)
    close_df = m._apply_subb_btc_start_filter(close_df)
    momentum = {lb: close_df.div(close_df.shift(lb)).sub(1) for lb in m.US_ROT_LBS}
    vol_df = close_df.pct_change().rolling(m.US_ROT_VOL_LB).std() * np.sqrt(m.US_TRADING_DAYS)
    start = max(m.US_ROT_MAX_LB, m.US_ROT_VOL_LB, m.US_ROT_VOL_WINDOW) + 1
    signal_days = m._us_signal_days(close_df, start)
    assets = list(dict.fromkeys(m.US_ROT_POOL + ["BIL"]))
    act = holdings = {"BIL": 1.0}
    pending, pending_cost, self_scale = None, 0.0, 1.0
    prev_selected = {lb: None for lb in m.US_ROT_LBS}
    rows, hist = [], []
    for i in range(start, len(close_df)):
        dt = close_df.index[i]
        if len(hist) >= m.US_ROT_VOL_WINDOW:
            rv = np.std(hist[-m.US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(m.US_TRADING_DAYS)
            self_scale = float(np.clip(m.US_ROT_TARGET_VOL / rv, 0.05, m.US_ROT_MAX_LEV)) if rv > 0.001 else m.US_ROT_MAX_LEV
        if pending is not None:
            open_row = m._us_open_row(dt, m._active_weight_assets(holdings, pending), us_open, close_df,
                                      strict=True, context="Sub-B scope scan official")
            overnight = m._us_weighted_return(holdings, close_df.iloc[i - 1], open_row)
            intraday = m._us_weighted_return(pending, open_row, close_df.iloc[i])
            gross = (1 + overnight) * (1 + intraday) - 1
            cost = pending_cost
            ret = (1 + gross) * (1 - cost) - 1
            holdings, pending, pending_cost = dict(pending), None, 0.0
        else:
            gross = m._us_weighted_return(holdings, close_df.iloc[i - 1], close_df.iloc[i])
            cost, ret = 0.0, gross
        hist.append(float(ret))
        is_signal, rebalanced = i in signal_days, False
        active_codes = list(ranking_codes)
        row_selected = {lb: prev_selected.get(lb) for lb in m.US_ROT_LBS}
        scales = {"stock": 1.0}
        if is_signal:
            active_codes = list(m._subb_active_ranking_codes(close_df, i, ranking_codes))
            moms = {lb: momentum[lb].iloc[i] for lb in m.US_ROT_LBS}
            if ctx.cfg.stock_mode == "current":
                new_act, per_lb = m._us_mix_target_weights(
                    moms, vol_df.iloc[i], active_codes, self_scale, top_n=m.US_ROT_TOP_N,
                    abs_threshold=m.US_ROT_ABS_THRESHOLD, prev_risky_by_lb=prev_selected,
                    threshold=m.US_ROT_REBALANCE_THRESHOLD,
                )
                scales = {"stock": self_scale}
            else:
                raw_act, per_lb = m._us_mix_target_weights(
                    moms, vol_df.iloc[i], active_codes, 1.0, top_n=m.US_ROT_TOP_N,
                    abs_threshold=m.US_ROT_ABS_THRESHOLD, prev_risky_by_lb=prev_selected,
                    threshold=m.US_ROT_REBALANCE_THRESHOLD,
                )
                new_act, scales = _target_from_raw(
                    m, ctx, raw_act, dt, m.US_ROT_TARGET_VOL, m.US_ROT_MAX_LEV, self_scale,
                )
            next_selected = {lb: per_lb[lb]["selected"] or None for lb in m.US_ROT_LBS}
            turnover = sum(abs(new_act.get(a, 0.0) - act.get(a, 0.0)) for a in set(new_act) | set(act) if a != "BIL")
            if m._subb_should_rebalance(turnover, m.US_ROT_MIN_TURNOVER):
                pending, pending_cost, act = dict(new_act), turnover * m.US_ROT_COMMISSION, dict(new_act)
                prev_selected, row_selected, rebalanced = next_selected, next_selected, True
        row = {"date": dt, "return": ret, "return_before_execution_cost": gross,
               "execution_cost": cost, "is_signal": is_signal, "rebalanced": rebalanced,
               "inflation_pressure_on": m._inflation_pressure_on_from_prices(close_df, i),
               "ranking_codes": ",".join(active_codes), "target_vol_scale": self_scale,
               "candidate_stock_scale": scales.get("stock", 1.0)}
        for asset in assets:
            row[f"w_{asset}"] = holdings.get(asset, 0.0)
            row[f"actual_w_{asset}"] = holdings.get(asset, 0.0)
            row[f"target_w_{asset}"] = act.get(asset, 0.0)
            row[f"candidate_scale_{asset}"] = scales.get(asset, 1.0)
        for lb in m.US_ROT_LBS:
            row[f"sel_{lb}"] = m._serialize_us_mix_selected(row_selected.get(lb))
        rows.append(row)
    out = pd.DataFrame(rows).set_index("date")
    out["nav"] = (1 + out["return"]).cumprod()
    return out


def run_ema_candidate(m, close_df, us_open, ctx: ScaleContext):
    close_df = m._apply_subb_btc_start_filter(close_df)
    ranking = list(m.US_ROT_POOL)
    scores = m._subb_v75_ema_score(close_df, m.SUBB_V75_EMA_HALF_LIFE)
    vol_df = close_df.pct_change().rolling(m.US_ROT_VOL_LB).std() * np.sqrt(m.US_TRADING_DAYS)
    start = max(m.SUBB_V75_EMA_HALF_LIFE, m.US_ROT_VOL_LB, m.US_ROT_VOL_WINDOW) + 1
    signal_days = m._us_signal_days(close_df, start)
    assets = list(dict.fromkeys(ranking + ["BIL"]))
    act = holdings = {"BIL": 1.0}
    pending, pending_cost, rows, hist = None, 0.0, [], []
    for i in range(start, len(close_df)):
        dt = close_df.index[i]
        self_scale = m._subb_v75_ema_scale_from_hist(hist)
        if pending is not None:
            open_row = m._us_open_row(dt, m._active_weight_assets(holdings, pending), us_open, close_df,
                                      strict=True, context="Sub-B scope scan EMA")
            overnight = m._us_weighted_return(holdings, close_df.iloc[i - 1], open_row)
            intraday = m._us_weighted_return(pending, open_row, close_df.iloc[i])
            gross = (1 + overnight) * (1 + intraday) - 1
            cost = pending_cost
            ret = (1 + gross) * (1 - cost) - 1
            holdings, pending, pending_cost = dict(pending), None, 0.0
        else:
            gross = m._us_weighted_return(holdings, close_df.iloc[i - 1], close_df.iloc[i])
            cost, ret = 0.0, gross
        hist.append(float(ret))
        is_signal, rebalanced, turnover, selected = i in signal_days, False, 0.0, []
        scales = {"stock": 1.0}
        if is_signal:
            previous = {a for a in assets if a != "BIL" and act.get(a, 0.0) > 0.001}
            raw = m._us_raw_weights(scores.iloc[i], vol_df.iloc[i], ranking, m.US_ROT_TOP_N,
                                    m.SUBB_V75_EMA_ABS_THRESHOLD, prev_risky=previous or None,
                                    threshold=m.US_ROT_REBALANCE_THRESHOLD)
            new_act, scales = _target_from_raw(
                m, ctx, raw, dt, m.US_ROT_TARGET_VOL, m.US_ROT_MAX_LEV, self_scale,
            )
            turnover = sum(abs(new_act.get(a, 0.0) - act.get(a, 0.0)) for a in set(new_act) | set(act) if a != "BIL")
            if m._subb_should_rebalance(turnover, m.US_ROT_MIN_TURNOVER):
                pending, pending_cost, act, rebalanced = dict(new_act), turnover * m.US_ROT_COMMISSION, dict(new_act), True
            selected = sorted(a for a, w in raw.items() if a != "BIL" and w > 1e-12)
        row = {"date": dt, "return": ret, "return_before_execution_cost": gross,
               "execution_cost": cost, "is_signal": is_signal, "rebalanced": rebalanced,
               "turnover": turnover, "scale": self_scale, "target_vol_mode": m.SUBB_V75_EMA_VOL_MODE,
               "target_vol_halflife_days": m.SUBB_V75_EMA_VOL_HALFLIFE_DAYS,
               "ranking_codes": ",".join(ranking), "selected": ",".join(selected),
               "inflation_pressure_on": m._inflation_pressure_on_from_prices(close_df, i),
               "candidate_stock_scale": scales.get("stock", 1.0)}
        for asset in assets:
            row[f"w_{asset}"] = holdings.get(asset, 0.0)
            row[f"actual_w_{asset}"] = holdings.get(asset, 0.0)
            row[f"target_w_{asset}"] = act.get(asset, 0.0)
            row[f"candidate_scale_{asset}"] = scales.get(asset, 1.0)
        rows.append(row)
    out = pd.DataFrame(rows).set_index("date")
    out["nav"] = (1 + out["return"]).cumprod()
    return out


def run_new_line_candidate(m, close_df, us_open, ctx: ScaleContext, line: str):
    close_df = m._apply_subb_btc_start_filter(close_df)
    assets = list(dict.fromkeys(m.US_ROT_POOL + ["BIL"]))
    if line == "bias":
        scores, target_vol, window, max_lev, start = m._v78_score_bias_level(close_df), 0.25, 40, 1.5, 391
    elif line == "logvol":
        scores, target_vol, window, max_lev, start = m._v78_score_log_weighted(close_df), 0.30, 40, 1.25, 321
    else:
        raise ValueError(line)
    start = max(start - 1, m.US_ROT_VOL_LB, window) + 1
    vol_df = close_df.pct_change().rolling(m.US_ROT_VOL_LB).std() * np.sqrt(m.US_TRADING_DAYS)
    signal_days = m._us_signal_days(close_df, start)
    volume_gate, volume_source = m._v78_spy_volume_gate(close_df.index)
    volume_gate = volume_gate.reindex(close_df.index).fillna(False)
    holdings = target = {"BIL": 1.0}
    pending, pending_cost, hist, rows = None, 0.0, [], []
    for i in range(start, len(close_df)):
        dt = close_df.index[i]
        if len(hist) >= window:
            rv = np.std(hist[-window:], ddof=1) * np.sqrt(m.US_TRADING_DAYS)
            self_scale = float(np.clip(target_vol / rv, 0.05, max_lev)) if rv > 0.001 else max_lev
        else:
            rv, self_scale = np.nan, 1.0
        if pending is not None:
            open_row = m._us_open_row(dt, m._active_weight_assets(holdings, pending), us_open, close_df,
                                      strict=True, context=f"Sub-B scope scan {line}")
            overnight = m._us_weighted_return(holdings, close_df.iloc[i - 1], open_row)
            intraday = m._us_weighted_return(pending, open_row, close_df.iloc[i])
            gross = (1 + overnight) * (1 + intraday) - 1
            cost = pending_cost
            ret = (1 + gross) * (1 - cost) - 1
            holdings, pending, pending_cost = dict(pending), None, 0.0
        else:
            gross = m._us_weighted_return(holdings, close_df.iloc[i - 1], close_df.iloc[i])
            cost, ret = 0.0, gross
        hist.append(float(ret))
        is_signal, rebalanced, turnover = i in signal_days, False, 0.0
        volume_on = bool(volume_gate.iloc[i])
        volume_scale = 0.75 if volume_on else 1.0
        hot = bool(line == "logvol" and np.isfinite(rv) and rv >= 0.50)
        hot_scale = 0.75 if hot else 1.0
        scales = {"stock": 1.0}
        if is_signal:
            raw = m._us_raw_weights(scores.iloc[i], vol_df.iloc[i], m.US_ROT_POOL, m.US_ROT_TOP_N,
                                    0.0, prev_risky=None, threshold=1.0)
            base, scales = _target_from_raw(m, ctx, raw, dt, target_vol, max_lev, self_scale)
            target = m._v78_apply_equity_scale(base, volume_scale * hot_scale)
            turnover = sum(abs(target.get(a, 0.0) - holdings.get(a, 0.0)) for a in set(target) | set(holdings) if a != "BIL")
            pending, pending_cost, rebalanced = dict(target), turnover * m.US_ROT_COMMISSION, True
        row = {"date": dt, "return": ret, "return_before_execution_cost": gross,
               "execution_cost": cost, "is_signal": is_signal, "rebalanced": rebalanced,
               "turnover": turnover, "target_vol_scale": self_scale, "realized_vol": rv,
               "volume_gate_next": volume_on, "volume_scale_next": volume_scale,
               "logvol_high_vol_on": hot, "logvol_high_vol_scale": hot_scale,
               "volume_source": volume_source, "line": line,
               "candidate_stock_scale": scales.get("stock", 1.0)}
        for asset in assets:
            row[f"w_{asset}"] = holdings.get(asset, 0.0)
            row[f"actual_w_{asset}"] = holdings.get(asset, 0.0)
            row[f"target_w_{asset}"] = target.get(asset, 0.0)
            row[f"candidate_scale_{asset}"] = scales.get(asset, 1.0)
        rows.append(row)
    out = pd.DataFrame(rows).set_index("date")
    out["nav"] = (1 + out["return"].fillna(0.0)).cumprod()
    return out


def finish_bundle(m, close, us_open, official, ema, bias, logvol):
    v77 = m.blend_subb_v75_results(official, ema)
    final = m.blend_v78_subb_results(v77, bias, logvol)
    if m.US_ROT_VOLREG_ENABLED:
        final = m.apply_vol_regime_overlay(final, close["SPY"], close_df=close, us_open=us_open,
                                           strict_open_execution=True)
    if m.SUBB_DBC_PROFIT_GUARD_ENABLED:
        final = m.apply_subb_dbc_profit_guard_overlay(final, close, us_open=us_open,
                                                      strict_open_execution=True)
    return {"final": final, "official": official, "ema": ema, "bias": bias, "logvol": logvol, "v77": v77}


def run_production_bundle(m, close, us_open):
    official = m.run_us_rotation_mix(
        close, m.US_ROT_BASE_POOL, top_n=m.US_ROT_TOP_N, us_open=us_open,
        ranking_code_selector=m._subb_active_ranking_codes, weight_assets=m.US_ROT_POOL,
        strict_open_execution=True,
    )
    ema = m.run_subb_v75_ema_base7_rotation(
        close, base_codes=m.US_ROT_POOL, top_n=m.US_ROT_TOP_N, us_open=us_open,
        weight_assets=m.US_ROT_POOL, strict_open_execution=True,
    )
    bias = m.run_v78_subb_new_line(close, line="bias", us_open=us_open, strict_open_execution=True)
    logvol = m.run_v78_subb_new_line(close, line="logvol", us_open=us_open, strict_open_execution=True)
    return finish_bundle(m, close, us_open, official, ema, bias, logvol)


def run_candidate_bundle(m, close, us_open, cfg: Candidate):
    ctx = ScaleContext(m, close, cfg)
    official = run_official_candidate(m, close, us_open, ctx)
    ema = run_ema_candidate(m, close, us_open, ctx)
    bias = run_new_line_candidate(m, close, us_open, ctx, "bias")
    logvol = run_new_line_candidate(m, close, us_open, ctx, "logvol")
    return finish_bundle(m, close, us_open, official, ema, bias, logvol)


def metric_row(returns: pd.Series, start=None):
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if start is not None:
        values = values.loc[values.index >= start]
    if values.empty:
        return {"start": "", "end": "", "rows": 0, "cagr": np.nan, "ann_vol": np.nan,
                "sharpe": np.nan, "max_dd": np.nan}
    nav = (1 + values).cumprod()
    years = len(values) / 252.0
    cagr = nav.iloc[-1] ** (1 / years) - 1 if years > 0 and nav.iloc[-1] > 0 else np.nan
    ann_vol = values.std(ddof=1) * np.sqrt(252)
    sharpe = values.mean() / values.std(ddof=1) * np.sqrt(252) if values.std(ddof=1) > 0 else np.nan
    max_dd = (nav / nav.cummax() - 1).min()
    return {"start": values.index[0].date().isoformat(), "end": values.index[-1].date().isoformat(),
            "rows": len(values), "cagr": cagr, "ann_vol": ann_vol, "sharpe": sharpe, "max_dd": max_dd}


def total_embedded_cost(bundle, index):
    zero = pd.Series(0.0, index=index)
    def col(frame, name):
        return pd.to_numeric(frame.get(name, zero), errors="coerce").reindex(index).fillna(0.0)
    component = 0.25 * sum((col(bundle[name], "execution_cost") for name in ("official", "ema", "bias", "logvol")), zero)
    v77_outer = 0.5 * col(bundle["v77"], "subb_execution_cost")
    final_effective = col(bundle["final"], "subb_effective_cost")
    dbc = col(bundle["final"], "dbc_profit_guard_cost")
    return component + v77_outer + final_effective + dbc


def scale_diagnostics(bundle, m):
    frames = []
    for name in ("official", "ema", "bias", "logvol"):
        frame = bundle[name]
        frames.append(frame.loc[frame["is_signal"].astype(bool)])
    merged = pd.concat(frames, axis=0)
    out = {}
    for label, col in [("stock", "candidate_stock_scale")] + [
        (asset, f"candidate_scale_{asset}") for asset in m.US_ROT_POOL
    ]:
        if col not in merged:
            continue
        values = pd.to_numeric(merged[col], errors="coerce").dropna()
        if len(values):
            out[f"scale_mean_{label}"] = values.mean()
            out[f"scale_pct_lt1_{label}"] = (values < 1 - 1e-12).mean()
    return out


def git_output(args):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()


def write_artifacts(modules, closes, sources, results, configs, parity):
    rows, full_rows = [], []
    for version, by_candidate in results.items():
        baseline = by_candidate["production_current"]
        baseline_full = metric_row(baseline["final"]["return"])
        for cfg in configs:
            bundle = by_candidate[cfg.name]
            final = bundle["final"]
            end = final.index.max()
            for window, years in WINDOWS.items():
                start = None if years is None else end - pd.DateOffset(years=years)
                metrics = metric_row(final["return"], start)
                cost = total_embedded_cost(bundle, final.index)
                if start is not None:
                    cost = cost.loc[cost.index >= start]
                row = {"version": version, "candidate": cfg.name, "window": window,
                       "kind": "baseline" if cfg.name == "production_current" else "candidate",
                       "stock_mode": cfg.stock_mode, "nonstock_mode": cfg.nonstock_mode,
                       "groups": ",".join(sorted(cfg.groups)), "short": cfg.short, "long": cfg.long,
                       "floor": cfg.floor, **metrics,
                       "annualized_embedded_cost": cost.mean() * 252 if len(cost) else np.nan}
                rows.append(row)
            metrics = metric_row(final["return"])
            full = {"version": version, "candidate": cfg.name,
                    "kind": "baseline" if cfg.name == "production_current" else "candidate",
                    "stock_mode": cfg.stock_mode, "nonstock_mode": cfg.nonstock_mode,
                    "groups": ",".join(sorted(cfg.groups)), "short": cfg.short, "long": cfg.long,
                    "floor": cfg.floor, "description": cfg.description, **metrics,
                    "delta_cagr_pp": (metrics["cagr"] - baseline_full["cagr"]) * 100,
                    "delta_sharpe": metrics["sharpe"] - baseline_full["sharpe"],
                    "delta_mdd_improvement_pp": (metrics["max_dd"] - baseline_full["max_dd"]) * 100}
            full.update(scale_diagnostics(bundle, modules[version]))
            full_rows.append(full)
    window_df = pd.DataFrame(rows)
    summary_df = pd.DataFrame(full_rows)
    write_schema_csvs(window_df, summary_df, RUN_DIR)

    meta_path = RUN_DIR / "scan_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update({
        "phase": "executed",
        "scan_type": "research_only_no_source_change",
        "baseline": {
            "V7.8": "production four-leg self-vol target 25%, production asymmetric scope",
            "V7.9": "production four-leg self-vol target 30%, production asymmetric scope",
        },
        "candidate_grid": [cfg.__dict__ | {"groups": sorted(cfg.groups)} for cfg in configs],
        "data_snapshot": {
            "provider": "Yahoo adjusted OHLC via production fetch_yahoo",
            "source_labels": sources,
            "versions": {v: {"start": d.index.min().date().isoformat(),
                              "end": d.index.max().date().isoformat(), "rows": len(d),
                              "pool": list(modules[v].US_ROT_POOL)} for v, d in closes.items()},
            "formal_execution": "T close signal -> T+1 adjusted open -> T+1 close return",
            "late_assets": "actual pre-inception NaN; BTC eligible from 2022-01-01; EMXC uses production EEM/EMXC splice",
        },
        "cost_model": {
            "commission": 0.001,
            "turnover": "production one-way absolute risky-weight turnover at component, blend/VolReg, and DBC guard layers",
            "financing": "none, matching current Sub-B production implementation",
        },
        "parity": parity,
        "decision": "research_pending_review",
        "stability_label": "reported_not_promoted",
        "git_status_after": git_output(["git", "status", "--short"]),
    })
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def fmt(value, pct=False):
        return "N/A" if pd.isna(value) else (f"{value:.2%}" if pct else f"{value:.3f}")
    lines = [
        "# V7.8 / V7.9 Sub-B volatility sizing scope scan",
        "",
        "## Research question",
        "",
        "Test SPY absolute target volatility on stocks while non-stock assets never exceed 1x and may either stay at 1x or independently de-risk when their own short volatility exceeds long volatility.",
        "",
        "## Frozen implementation",
        "",
        "- Production four-leg selection, thresholds, inflation gate, BTC cap/start, SPY volume gate, LogVol vol-hot rule, SPY VolReg and DBC profit guard are unchanged.",
        "- Execution is T close signal -> T+1 adjusted open -> T+1 close with the production 10 bp turnover charge.",
        "- SPY stock scale uses each leg's existing target/max (V7.8 official/EMA 25%; V7.9 official/EMA 30%; Bias 25%; LogVol 30%).",
        "- Own-relative non-stock scale is clip(long-vol / short-vol, floor, 1.0), lagged one trading day; missing warm-up means 1.0.",
        "- V7.8 includes EFA/AGG/UUP; V7.9 does not, so bond/currency ablations are N/A/no-op in V7.9.",
        "- Research-only: neither production script is modified by this run.",
        "",
        "## Harness parity",
        "",
    ]
    for version, item in parity.items():
        lines.append(f"- {version}: max absolute return difference {item['max_abs_return_diff']:.3e}; PASS={item['pass']}")
    lines += ["", "## Full-sample results", ""]
    for version in VERSION_FILES:
        subset = summary_df[summary_df.version == version].copy()
        base = subset[subset.candidate == "production_current"].iloc[0]
        lines += [f"### {version}", "",
                  f"Production baseline: CAGR {fmt(base.cagr, True)}, Sharpe {fmt(base.sharpe)}, max drawdown {fmt(base.max_dd, True)}.", "",
                  "| Candidate | CAGR | ΔCAGR pp | Sharpe | ΔSharpe | MDD | ΔMDD improve pp |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        show = subset.sort_values(["delta_sharpe", "delta_cagr_pp"], ascending=False)
        for row in show.itertuples():
            lines.append(f"| {row.candidate} | {row.cagr:.2%} | {row.delta_cagr_pp:+.3f} | {row.sharpe:.3f} | {row.delta_sharpe:+.3f} | {row.max_dd:.2%} | {row.delta_mdd_improvement_pp:+.3f} |")
        lines.append("")
    lines += [
        "## Interpretation rule",
        "",
        "A non-stock de-risk rule is useful only if its group ablation improves drawdown/risk-adjusted return without relying on a single window. The 30/252/floor-0.50 all-group candidate is judged together with 20/252, 40/252, 30/126 and floor 0.25/0.75 sensitivities. No candidate is promoted automatically.",
        "",
        "## Required windows",
        "",
        "Full, 10Y, 5Y, 3Y and 1Y metrics are in `window_metrics.csv`; all metrics use each version's common four-leg result window.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_schema_csvs(long_metrics: pd.DataFrame, full_diagnostics: pd.DataFrame, run_dir: Path):
    """Write the skill-standard long summary and one-row-per-candidate window table."""
    segment_map = {"full": "full", "10Y": "last_10y", "5Y": "last_5y", "3Y": "last_3y", "1Y": "last_1y"}
    scan = long_metrics.copy()
    scan["segment"] = scan["window"].map(segment_map)
    scan = scan.rename(columns={"cagr": "ann_return", "sharpe": "sharpe_repo"})
    scan.to_csv(run_dir / "scan_summary.csv", index=False, encoding="utf-8-sig")

    identity = ["version", "candidate", "kind", "stock_mode", "nonstock_mode", "groups", "short", "long", "floor"]
    records = []
    for keys, group in long_metrics.groupby(identity, dropna=False, sort=False):
        row = dict(zip(identity, keys))
        for item in group.itertuples(index=False):
            suffix = segment_map[item.window]
            row[f"ann_return_{suffix}"] = item.cagr
            row[f"ann_vol_{suffix}"] = item.ann_vol
            row[f"sharpe_repo_{suffix}"] = item.sharpe
            row[f"max_dd_{suffix}"] = item.max_dd
            row[f"start_{suffix}"] = item.start
            row[f"end_{suffix}"] = item.end
            row[f"rows_{suffix}"] = item.rows
            row[f"annualized_embedded_cost_{suffix}"] = item.annualized_embedded_cost
        records.append(row)
    wide = pd.DataFrame(records)
    diagnostic_cols = [c for c in full_diagnostics.columns if c not in wide.columns or c in ("version", "candidate")]
    diagnostics = full_diagnostics[diagnostic_cols].copy()
    wide = wide.merge(diagnostics, on=["version", "candidate"], how="left", suffixes=("", "_diagnostic"))
    wide.to_csv(run_dir / "window_metrics.csv", index=False, encoding="utf-8-sig")


def normalize_existing_artifacts(run_dir: Path):
    """One-time migration for the first completed run, before the schema fix above."""
    old_full = pd.read_csv(run_dir / "scan_summary.csv")
    old_long = pd.read_csv(run_dir / "window_metrics.csv")
    if "window" not in old_long.columns or "delta_cagr_pp" not in old_full.columns:
        raise ValueError("existing artifacts are not the pre-normalization schema")
    write_schema_csvs(old_long, old_full, run_dir)


def main():
    global RUN_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--normalize-existing", action="store_true")
    args = parser.parse_args()
    RUN_DIR = args.run_dir.resolve()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    if args.normalize_existing:
        normalize_existing_artifacts(RUN_DIR)
        print(RUN_DIR)
        return
    modules = {label: load_module(label, path) for label, path in VERSION_FILES.items()}
    raw, sources = fetch_shared_raw(modules)
    closes, opens = {}, {}
    for version, module in modules.items():
        closes[version], opens[version] = build_version_data(module, raw)
    # Freeze one volume series per version so every candidate sees identical external data.
    for version, module in modules.items():
        print(f"[{version}] freeze SPY volume gate", flush=True)
        gate, source = module._v78_spy_volume_gate(closes[version].index)
        frozen = gate.copy()
        module._v78_spy_volume_gate = lambda index, g=frozen, s=source: (g.reindex(index).fillna(False), s)

    configs = candidate_grid()
    results, parity = {}, {}
    for version, module in modules.items():
        print(f"[{version}] production baseline", flush=True)
        production = run_production_bundle(module, closes[version], opens[version])
        rebuilt = run_candidate_bundle(module, closes[version], opens[version], configs[0])
        common = production["final"].index.intersection(rebuilt["final"].index)
        diff = (production["final"].loc[common, "return"] - rebuilt["final"].loc[common, "return"]).abs().max()
        parity[version] = {"max_abs_return_diff": float(diff), "pass": bool(diff <= 1e-12), "rows": len(common)}
        if not parity[version]["pass"]:
            raise AssertionError(f"{version} production parity failed: {diff}")
        by_candidate = {"production_current": production}
        for cfg in configs[1:]:
            print(f"[{version}] {cfg.name}", flush=True)
            by_candidate[cfg.name] = run_candidate_bundle(module, closes[version], opens[version], cfg)
        results[version] = by_candidate
    write_artifacts(modules, closes, sources, results, configs, parity)
    print(RUN_DIR)


if __name__ == "__main__":
    main()

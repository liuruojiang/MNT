#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "matplotlib",
#   "numpy",
#   "pandas",
#   "requests",
#   "xlsxwriter",
# ]
# ///
"""Reproducible V7.8/V7.9 formal and long-proxy comparison.

The production scripts are imported unchanged.  Formal runs preserve their
official sleeve call chains and Sub-B T close -> T+1 adjusted-open execution.
The proxy run is explicitly research-only: it uses reduced/pre-publication CN
proxies and long-history US mutual-fund/index/futures proxies.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
V78_PATH = ROOT / "mnt_bot V 7.8 plus.py"
V79_PATH = ROOT / "mnt_bot V 7.9 plus.py"
CN_CACHE_PATH = ROOT / "mnt_strategy_data_cn.csv"
DEFAULT_OUTPUT = ROOT / "outputs" / "v78_v79_proxy_compare_20260810"
FORMAL_START = pd.Timestamp("2014-10-17")
WINDOWS = {
    "Full": None,
    "10Y": pd.DateOffset(years=10),
    "5Y": pd.DateOffset(years=5),
    "3Y": pd.DateOffset(years=3),
    "1Y": pd.DateOffset(years=1),
}
CRISIS_WINDOWS = {
    "A-share 2007-08 peak-to-trough": ("2007-10-16", "2008-10-28"),
    "GFC Lehman-to-trough": ("2008-09-15", "2009-03-09"),
    "China 2015-16 crash": ("2015-06-12", "2016-02-29"),
    "2018 risk-off": ("2018-01-26", "2018-12-24"),
    "COVID crash": ("2020-02-19", "2020-03-23"),
    "2022 inflation bear": ("2022-01-03", "2022-12-30"),
    "China Jan-Feb 2024": ("2024-01-02", "2024-02-05"),
}
PROXY_MAP = {
    "QQQ": "^NDX",
    "EMXC": "VEIEX",
    "EFA": "VGTSX",
    "GLD": "GC=F",
    "AGG": "VUSTX",
    "DBC": "^SPGSCI",
    "BIL": "VFISX",
    "SPY": "SPY",
    "TLT": "VUSTX",
    "UUP": "DX-Y.NYB",
    "DBMF": "RYMFX",
    "KMLM": "AQMNX",
    "BTC-USD": "BTC-USD",
}


class QuietMsg:
    def write(self, _text: str) -> None:
        return None


@dataclass
class SleeveRun:
    returns: dict[str, pd.Series]
    results: dict[str, pd.DataFrame]
    notes: list[str]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def numeric_panel(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    return frame.apply(pd.to_numeric, errors="coerce")


def last_valid_date(frame: pd.DataFrame, columns: list[str]) -> pd.Timestamp:
    dates = [frame[col].dropna().index.max() for col in columns]
    return min(pd.Timestamp(value) for value in dates)


def write_panel(frame: pd.DataFrame, path: Path) -> None:
    out = frame.copy()
    out.index.name = "date"
    out.to_csv(path, encoding="utf-8-sig")


def load_or_fetch_formal_market(mod, out_dir: Path):
    cache_dir = out_dir / "market_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "cn": cache_dir / "formal_cn_close.csv",
        "dk": cache_dir / "formal_dk_close.csv",
        "us": cache_dir / "formal_us_rot_close.csv",
        "prod": cache_dir / "formal_us_prod_daily.csv",
        "open": cache_dir / "formal_us_adjusted_open.csv",
    }
    if all(path.exists() for path in paths.values()):
        panels = [numeric_panel(paths[key]) for key in ("cn", "dk", "us", "prod")]
        open_frame = numeric_panel(paths["open"])
        return (
            *panels,
            {col: open_frame[col].dropna() for col in open_frame.columns},
            "cache",
        )

    bot = mod.CombinedStrategyV78()
    cn, dk, us, prod = bot._fetch_data(
        QuietMsg(), include_cn_live_snapshot=True, include_us_live_snapshot=False
    )
    local_cn = numeric_panel(CN_CACHE_PATH)
    cn_required = list(mod.CN_STOCK_CODES) + [mod.CN_BOND_CODE]
    formal_end = last_valid_date(local_cn, cn_required)
    formal_end = min(formal_end, cn.index.max(), dk.index.max(), us.index.max())
    cn = cn.loc[FORMAL_START:formal_end].copy()
    dk = dk.loc[FORMAL_START:formal_end].copy()
    us = us.loc[:formal_end].copy()
    prod = prod.loc[:formal_end].copy()
    open_frame = pd.concat(
        {key: value.loc[:formal_end] for key, value in bot._us_open.items()}, axis=1
    ).sort_index()
    for key, panel in zip(("cn", "dk", "us", "prod"), (cn, dk, us, prod), strict=True):
        write_panel(panel, paths[key])
    write_panel(open_frame, paths["open"])
    return (
        cn,
        dk,
        us,
        prod,
        {col: open_frame[col].dropna() for col in open_frame},
        "network",
    )


def run_formal_sleeves(mod, open_dict, cn, dk, us, prod) -> SleeveRun:
    bot = mod.CombinedStrategyV78()
    bot._us_open = open_dict
    notes: list[str] = []
    start = time.perf_counter()
    outputs = bot._run_strategies(
        cn,
        dk,
        us,
        prod,
        allow_unresolved_suba_volume=False,
        strict_subb_open_execution=True,
    )
    notes.append(
        f"official _run_strategies completed in {time.perf_counter() - start:.1f}s"
    )
    results = {"Sub-A": outputs[0], "Sub-A-DK": outputs[1], "Sub-B": outputs[2]}
    returns = {
        name: frame["return"].dropna().astype(float) for name, frame in results.items()
    }
    returns["Combined"] = mod._performance_combined_daily_returns(returns)
    return SleeveRun(returns=returns, results=results, notes=notes)


@contextmanager
def patched(module, **updates: Any) -> Iterator[None]:
    old = {key: getattr(module, key) for key in updates}
    try:
        for key, value in updates.items():
            setattr(module, key, value)
        yield
    finally:
        for key, value in old.items():
            setattr(module, key, value)


def run_proxy_suba(mod, cn_raw: pd.DataFrame) -> pd.DataFrame:
    proxy_codes = ["1.930955", "1.000016", "1.000852", "1.000905"]
    proxy = (
        pd.DataFrame(
            {
                "1.930955": cn_raw["1.H20955"],
                "1.000016": cn_raw["1.H00016"],
                "1.000852": cn_raw["1.H00852"],
                "1.000905": cn_raw["1.H00905"],
                mod.CN_BOND_CODE: cn_raw[mod.CN_BOND_CODE],
            }
        )
        .ffill()
        .dropna()
    )
    with patched(mod, CN_EQUITY_CODES=proxy_codes, CN_STOCK_CODES=proxy_codes):
        gate = (
            mod._build_suba_single_strategy_gates(proxy)
            if mod.CN_SA_SINGLE_GATE_ENABLED
            else None
        )
        old = mod.run_cn_strategy(proxy, proxy_codes, single_asset_signal_gate=gate)
        if mod.CN_SA_CASH_OVERLAY_ENABLED:
            old = mod.apply_suba_cash_peak_decay_overlay(
                old,
                proxy,
                decay_ratio_threshold=mod.CN_SA_CASH_OVERLAY_DECAY_RATIO,
                recovery_ratio_threshold=mod.CN_SA_CASH_OVERLAY_RECOVERY_RATIO,
                commission=mod.CN_COMMISSION,
            )
        if mod.CN_SA_SAME_SIDE_OVERHEAT_ENABLED:
            old = mod.apply_suba_same_side_overheat_overlay(
                old,
                proxy,
                enter_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_ENTER,
                exit_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_EXIT,
                derisk_scale=mod.CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE,
            )
        new = mod.run_v78_suba_new_tv10(proxy, proxy_codes)
        return mod.blend_v78_suba_results(old, new)


def run_proxy_adk(mod, cn_raw: pd.DataFrame) -> pd.DataFrame:
    dk = (
        pd.DataFrame(
            {
                "DK_SZ50": cn_raw["1.000016"],
                "DK_HS300": cn_raw["1.000300"],
                "DK_ZZ500": cn_raw["1.000905"],
                "DK_ZZ1000": cn_raw["1.H00852"],
            }
        )
        .ffill()
        .dropna()
    )
    cn_dummy = pd.DataFrame(index=dk.index)
    reduced_indices = {
        key: value for key, value in mod.CN_DK_INDICES.items() if key != "CYB"
    }
    reduced_official = tuple(
        pair for pair in mod.ADK_OFFICIAL_PAIR_ORDER if "CYB" not in pair
    )
    with patched(
        mod,
        CN_DK_INDICES=reduced_indices,
        ADK_OFFICIAL_PAIR_ORDER=reduced_official,
        ADK_OFFICIAL_PAIRS=set(reduced_official),
    ):
        old = mod.run_dk_strategy(cn_dummy, dk, official_pair_order=reduced_official)
        if mod.CN_DK_PAIR_SCORE_DECAY_ENABLED:
            old = mod.apply_dk_pair_score_peak_decay_overlay(
                old,
                decay_ratio_threshold=mod.CN_DK_PAIR_SCORE_DECAY_RATIO,
                recovery_ratio_threshold=mod.CN_DK_PAIR_SCORE_RECOVERY_RATIO,
                derisk_scale=mod.CN_DK_PAIR_SCORE_DERISK_SCALE,
                commission=mod.CN_DK_COMMISSION,
            )
        if mod.CN_DK_SAME_SIDE_OVERHEAT_ENABLED:
            old = mod.apply_dk_same_side_overheat_overlay(
                old,
                enter_threshold=mod.CN_DK_SAME_SIDE_OVERHEAT_ENTER,
                exit_threshold=mod.CN_DK_SAME_SIDE_OVERHEAT_EXIT,
                derisk_scale=mod.CN_DK_SAME_SIDE_OVERHEAT_DERISK_SCALE,
                commission=mod.CN_DK_COMMISSION,
            )
        old = mod._rebuild_dk_effective_execution_costs(
            old, old.attrs.get("pair_data", {}), mod.CN_DK_COMMISSION
        )
        new = mod.run_v78_adk_new_primary(cn_dummy, dk)
        return mod.blend_v78_adk_results(old, new)


def load_or_fetch_proxy_raw(
    mod, out_dir: Path
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    cache_dir = out_dir / "market_cache" / "proxy_raw"
    cache_dir.mkdir(parents=True, exist_ok=True)
    raw: dict[str, pd.DataFrame] = {}
    meta: dict[str, Any] = {}
    for strategy_asset, source_ticker in PROXY_MAP.items():
        path = cache_dir / f"{strategy_asset.replace('^', '_').replace('/', '_')}.csv"
        if path.exists():
            frame = numeric_panel(path)
            source = "cache"
        else:
            frame, source = mod.fetch_yahoo(source_ticker, start_date="1995-01-01")
            if frame is None or len(frame) <= 50:
                raise RuntimeError(
                    f"proxy fetch failed: {strategy_asset} <- {source_ticker}"
                )
            write_panel(frame, path)
        raw[strategy_asset] = frame
        meta[strategy_asset] = {
            "proxy": source_ticker,
            "source": source,
            "start": frame.index.min().date().isoformat(),
            "end": frame.index.max().date().isoformat(),
            "rows": len(frame),
        }
    return raw, meta


def proxy_us_panel(mod, raw: dict[str, pd.DataFrame]):
    anchor = raw["SPY"].index
    close = pd.DataFrame(index=anchor)
    open_frame = pd.DataFrame(index=anchor)
    needed = list(dict.fromkeys(list(mod.US_ROT_POOL) + ["BIL", "SPY", "TLT"]))
    for asset in needed:
        source = raw[asset]
        close[asset] = source["close"].reindex(anchor).ffill()
        open_source = source["open"] if "open" in source else source["close"]
        open_frame[asset] = open_source.reindex(anchor).ffill()
    core = [
        asset for asset in needed if asset not in mod._us_rot_late_history_tickers()
    ]
    close = close.dropna(subset=core)
    open_frame = open_frame.reindex(close.index).ffill()
    return close, {col: open_frame[col] for col in open_frame}


def run_proxy_subb(mod, raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close, open_dict = proxy_us_panel(mod, raw)
    official = mod.run_us_rotation_mix(
        close,
        mod.US_ROT_BASE_POOL,
        top_n=getattr(mod, "US_ROT_TOP_N", 3),
        us_open=open_dict,
        ranking_code_selector=mod._subb_active_ranking_codes,
        weight_assets=mod.US_ROT_POOL,
        strict_open_execution=True,
    )
    ema = mod.run_subb_v75_ema_base7_rotation(
        close,
        base_codes=mod.US_ROT_POOL,
        top_n=getattr(mod, "US_ROT_TOP_N", 3),
        us_open=open_dict,
        weight_assets=mod.US_ROT_POOL,
        strict_open_execution=True,
    )
    v77 = mod.blend_subb_v75_results(official, ema)
    bias = mod.run_v78_subb_new_line(
        close, line="bias", us_open=open_dict, strict_open_execution=True
    )
    logvol = mod.run_v78_subb_new_line(
        close, line="logvol", us_open=open_dict, strict_open_execution=True
    )
    result = mod.blend_v78_subb_results(v77, bias, logvol)
    if mod.US_ROT_VOLREG_ENABLED:
        result = mod.apply_vol_regime_overlay(
            result,
            close["SPY"],
            close_df=close,
            us_open=open_dict,
            strict_open_execution=True,
        )
    if mod.SUBB_DBC_PROFIT_GUARD_ENABLED:
        result = mod.apply_subb_dbc_profit_guard_overlay(
            result, close, us_open=open_dict, strict_open_execution=True
        )
    return result


def run_proxy_sleeves(
    mod, cn_raw: pd.DataFrame, raw_us: dict[str, pd.DataFrame]
) -> SleeveRun:
    notes = [
        "research-only reduced CN pool; CYB excluded",
        "ZZ1000 uses H00852 total-return proxy before price-index publication",
        "Sub-A volume overlay excluded because a consistent pre-2005 amount history is unavailable",
        "US proxy adjusted opens are reindexed to SPY sessions and forward-filled when the proxy has no bar",
    ]
    results = {
        "Sub-A": run_proxy_suba(mod, cn_raw),
        "Sub-A-DK": run_proxy_adk(mod, cn_raw),
        "Sub-B": run_proxy_subb(mod, raw_us),
    }
    returns = {
        name: frame["return"].dropna().astype(float) for name, frame in results.items()
    }
    returns["Combined"] = mod._performance_combined_daily_returns(returns)
    return SleeveRun(returns=returns, results=results, notes=notes)


def slice_window(series: pd.Series, offset: pd.DateOffset | None) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    if clean.empty or offset is None:
        return clean
    return clean.loc[clean.index >= clean.index.max() - offset]


def metric_row(series: pd.Series, annual_days: int) -> dict[str, Any]:
    ret = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    if len(ret) < 2:
        return {"start": "", "end": "", "rows": len(ret)}
    nav = (1.0 + ret).cumprod()
    dd = nav / nav.cummax() - 1.0
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    cagr = nav.iloc[-1] ** (1.0 / years) - 1.0 if years > 0 else np.nan
    vol = ret.std(ddof=1) * math.sqrt(annual_days)
    sharpe = (
        ret.mean() / ret.std(ddof=1) * math.sqrt(annual_days)
        if ret.std(ddof=1) > 0
        else np.nan
    )
    downside = ret.clip(upper=0).std(ddof=1) * math.sqrt(annual_days)
    sortino = ret.mean() * annual_days / downside if downside > 0 else np.nan
    monthly = ret.groupby(ret.index.to_period("M")).apply(
        lambda x: (1.0 + x).prod() - 1.0
    )
    q05 = ret.quantile(0.05)
    cvar = ret[ret <= q05].mean()
    underwater = dd < -1e-12
    max_underwater = 0
    current = 0
    for value in underwater:
        current = current + 1 if value else 0
        max_underwater = max(max_underwater, current)
    return {
        "start": ret.index[0].date().isoformat(),
        "end": ret.index[-1].date().isoformat(),
        "rows": len(ret),
        "years": years,
        "total_return": nav.iloc[-1] - 1.0,
        "cagr": cagr,
        "annual_vol": vol,
        "sharpe_0rf": sharpe,
        "sortino_0rf": sortino,
        "max_drawdown": dd.min(),
        "calmar": cagr / abs(dd.min()) if dd.min() < 0 else np.nan,
        "ulcer_index": float(np.sqrt(np.mean(np.square(dd)))) if len(dd) else np.nan,
        "monthly_win_rate": float((monthly > 0).mean()) if len(monthly) else np.nan,
        "best_month": monthly.max() if len(monthly) else np.nan,
        "worst_month": monthly.min() if len(monthly) else np.nan,
        "daily_var_95": q05,
        "daily_cvar_95": cvar,
        "max_underwater_obs": int(max_underwater),
    }


def turnover_cost_metrics(frame: pd.DataFrame) -> dict[str, float]:
    turnover_cols = [
        col
        for col in (
            "effective_turnover",
            "dk_execution_turnover",
            "turnover",
            "execution_turnover",
        )
        if col in frame.columns
    ]
    cost_cols = [
        col
        for col in ("trade_cost", "dk_execution_cost", "execution_cost")
        if col in frame.columns
    ]
    out: dict[str, float] = {}
    if turnover_cols:
        out["turnover_sum"] = float(
            pd.to_numeric(frame[turnover_cols[0]], errors="coerce").fillna(0).sum()
        )
    if cost_cols:
        out["cost_sum"] = float(
            pd.to_numeric(frame[cost_cols[0]], errors="coerce").fillna(0).sum()
        )
    weight_candidates = [
        col for col in ("weight", "v78_adk_final_exposure") if col in frame.columns
    ]
    if weight_candidates:
        out["average_abs_exposure"] = float(
            pd.to_numeric(frame[weight_candidates[0]], errors="coerce").abs().mean()
        )
    return out


def collect_metrics(runs: dict[tuple[str, str], SleeveRun]) -> pd.DataFrame:
    rows = []
    for (classification, version), run in runs.items():
        for sleeve, series in run.returns.items():
            annual_days = 244 if sleeve in {"Sub-A", "Sub-A-DK"} else 252
            extras = (
                turnover_cost_metrics(run.results[sleeve])
                if sleeve in run.results
                else {}
            )
            for window, offset in WINDOWS.items():
                row = metric_row(slice_window(series, offset), annual_days)
                rows.append(
                    {
                        "classification": classification,
                        "version": version,
                        "sleeve": sleeve,
                        "window": window,
                        **row,
                        **(extras if window == "Full" else {}),
                    }
                )
    return pd.DataFrame(rows)


def collect_yearly(runs: dict[tuple[str, str], SleeveRun]) -> pd.DataFrame:
    rows = []
    for (classification, version), run in runs.items():
        for sleeve, series in run.returns.items():
            for year, group in series.groupby(series.index.year):
                if len(group) < 20:
                    continue
                rows.append(
                    {
                        "classification": classification,
                        "version": version,
                        "sleeve": sleeve,
                        "year": int(year),
                        "return": float((1.0 + group).prod() - 1.0),
                    }
                )
    return pd.DataFrame(rows)


def collect_crises(runs: dict[tuple[str, str], SleeveRun]) -> pd.DataFrame:
    rows = []
    for (classification, version), run in runs.items():
        for sleeve, series in run.returns.items():
            for name, (start, end) in CRISIS_WINDOWS.items():
                period = series.loc[pd.Timestamp(start) : pd.Timestamp(end)]
                if len(period) < 10:
                    continue
                metric = metric_row(
                    period, 244 if sleeve in {"Sub-A", "Sub-A-DK"} else 252
                )
                rows.append(
                    {
                        "classification": classification,
                        "version": version,
                        "sleeve": sleeve,
                        "crisis": name,
                        **metric,
                    }
                )
    return pd.DataFrame(rows)


def collect_rolling(runs: dict[tuple[str, str], SleeveRun]) -> pd.DataFrame:
    rows = []
    for classification in sorted({key[0] for key in runs}):
        for sleeve in ("Sub-A", "Sub-A-DK", "Sub-B", "Combined"):
            series = {}
            for version in ("V7.8", "V7.9"):
                run = runs.get((classification, version))
                if run and sleeve in run.returns:
                    series[version] = run.returns[sleeve]
            if len(series) != 2:
                continue
            month_ends = (
                series["V7.8"]
                .resample("ME")
                .last()
                .index.intersection(series["V7.9"].resample("ME").last().index)
            )
            for end in month_ends:
                start = end - pd.DateOffset(years=3)
                metrics = {
                    version: metric_row(
                        values.loc[start:end],
                        244 if sleeve in {"Sub-A", "Sub-A-DK"} else 252,
                    )
                    for version, values in series.items()
                }
                if min(metrics[v].get("rows", 0) for v in metrics) < 500:
                    continue
                rows.append(
                    {
                        "classification": classification,
                        "sleeve": sleeve,
                        "end": end.date().isoformat(),
                        "v78_cagr": metrics["V7.8"].get("cagr"),
                        "v79_cagr": metrics["V7.9"].get("cagr"),
                        "v78_max_drawdown": metrics["V7.8"].get("max_drawdown"),
                        "v79_max_drawdown": metrics["V7.9"].get("max_drawdown"),
                    }
                )
    return pd.DataFrame(rows)


def save_daily(runs: dict[tuple[str, str], SleeveRun], out_dir: Path) -> None:
    for classification in sorted({key[0] for key in runs}):
        frames = {}
        for version in ("V7.8", "V7.9"):
            run = runs.get((classification, version))
            if run is None:
                continue
            for sleeve, series in run.returns.items():
                frames[f"{version}_{sleeve}"] = series
        if frames:
            write_panel(
                pd.DataFrame(frames).sort_index(),
                out_dir / f"{classification}_daily_returns.csv",
            )


def load_saved_runs(out_dir: Path) -> dict[tuple[str, str], SleeveRun]:
    runs: dict[tuple[str, str], SleeveRun] = {}
    for classification in ("formal", "proxy"):
        path = out_dir / f"{classification}_daily_returns.csv"
        if not path.exists():
            raise FileNotFoundError(f"missing saved run: {path}")
        frame = numeric_panel(path)
        for version in ("V7.8", "V7.9"):
            returns = {}
            for sleeve in ("Sub-A", "Sub-A-DK", "Sub-B", "Combined"):
                column = f"{version}_{sleeve}"
                if column not in frame:
                    raise KeyError(f"missing {column} in {path}")
                returns[sleeve] = frame[column].dropna().astype(float)
            runs[(classification, version)] = SleeveRun(
                returns=returns,
                results={},
                notes=[f"aggregated from {path.name}"],
            )
    return runs


def plot_comparison(runs: dict[tuple[str, str], SleeveRun], out_dir: Path) -> None:
    for classification in sorted({key[0] for key in runs}):
        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        for version, color in (("V7.8", "#5875A4"), ("V7.9", "#D65F5F")):
            run = runs.get((classification, version))
            if run is None:
                continue
            ret = run.returns["Combined"].dropna()
            nav = (1.0 + ret).cumprod()
            nav = nav / nav.iloc[0]
            dd = nav / nav.cummax() - 1.0
            axes[0].plot(nav.index, nav, label=version, color=color)
            axes[1].plot(dd.index, dd, label=version, color=color)
        axes[0].set_yscale("log")
        axes[0].set_ylabel("Combined NAV (log)")
        axes[1].set_ylabel("Drawdown")
        axes[1].set_xlabel("Date")
        axes[0].legend()
        axes[1].legend()
        fig.suptitle(f"V7.8 vs V7.9 - {classification}")
        fig.tight_layout()
        fig.savefig(out_dir / f"{classification}_combined_nav_drawdown.png", dpi=160)
        plt.close(fig)


def fmt_pct(value: Any) -> str:
    return "N/A" if pd.isna(value) else f"{float(value):.2%}"


def build_report(
    metrics: pd.DataFrame,
    yearly: pd.DataFrame,
    crises: pd.DataFrame,
    rolling: pd.DataFrame,
    audit: dict[str, Any],
) -> str:
    lines = [
        "# V7.8 vs V7.9 回测与长代理压力测试",
        "",
        f"生成时间：{audit['created_at']}",
        "",
        "## 口径",
        "",
        "- 正式共同样本：原版生产代码、完整当前 A/ADK 池、费用与严格 Sub-B T+1 调整后开盘执行。",
        "- 长代理样本：仅作压力研究；Sub-A/ADK 去除 CYB，ZZ1000 使用 H00852 全收益代理，Sub-A 成交额覆盖层关闭；美国资产使用长历史代理。",
        "- 组合：按生产绩效页的 Sub-A/Sub-A-DK/Sub-B 权重 15/15/40 归一，即 21.43%/21.43%/57.14%，不含微盘与 Sub-D。",
        "",
        "## 标准窗口（CAGR / 最大回撤 / Sharpe）",
        "",
    ]
    for classification in ("formal", "proxy"):
        subset = metrics[
            (metrics["classification"] == classification)
            & (metrics["sleeve"] == "Combined")
        ]
        if subset.empty:
            continue
        lines.extend(
            [
                f"### {classification}",
                "",
                "| 窗口 | V7.8 | V7.9 | CAGR差 |",
                "|---|---:|---:|---:|",
            ]
        )
        for window in WINDOWS:
            left = subset[(subset["version"] == "V7.8") & (subset["window"] == window)]
            right = subset[(subset["version"] == "V7.9") & (subset["window"] == window)]
            if left.empty or right.empty:
                continue
            a, b = left.iloc[0], right.iloc[0]
            delta = b.get("cagr", np.nan) - a.get("cagr", np.nan)
            lines.append(
                f"| {window} | {fmt_pct(a.get('cagr'))} / {fmt_pct(a.get('max_drawdown'))} / {a.get('sharpe_0rf', np.nan):.2f} "
                f"| {fmt_pct(b.get('cagr'))} / {fmt_pct(b.get('max_drawdown'))} / {b.get('sharpe_0rf', np.nan):.2f} | {delta:+.2%} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 袖套归因（Full）",
            "",
            "| 样本 | 袖套 | V7.8 CAGR/MDD | V7.9 CAGR/MDD | CAGR差 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for classification in ("formal", "proxy"):
        for sleeve in ("Sub-A", "Sub-A-DK", "Sub-B", "Combined"):
            subset = metrics[
                (metrics["classification"] == classification)
                & (metrics["sleeve"] == sleeve)
                & (metrics["window"] == "Full")
            ]
            if len(subset) != 2:
                continue
            a = subset[subset["version"] == "V7.8"].iloc[0]
            b = subset[subset["version"] == "V7.9"].iloc[0]
            lines.append(
                f"| {classification} | {sleeve} | {fmt_pct(a.cagr)} / {fmt_pct(a.max_drawdown)} "
                f"| {fmt_pct(b.cagr)} / {fmt_pct(b.max_drawdown)} | {b.cagr - a.cagr:+.2%} |"
            )

    lines.extend(["", "## 滚动与年度稳健性", ""])
    for classification in ("formal", "proxy"):
        roll = rolling[
            (rolling["classification"] == classification)
            & (rolling["sleeve"] == "Combined")
        ]
        if len(roll):
            win = float((roll["v79_cagr"] > roll["v78_cagr"]).mean())
            dd_win = float((roll["v79_max_drawdown"] > roll["v78_max_drawdown"]).mean())
            lines.append(
                f"- {classification}：3年滚动 CAGR 中 V7.9 胜率 {win:.1%}；3年滚动最大回撤更浅的比例 {dd_win:.1%}（{len(roll)} 个重叠月末窗口）。"
            )
        yr = yearly[
            (yearly["classification"] == classification)
            & (yearly["sleeve"] == "Combined")
        ]
        if len(yr):
            piv = yr.pivot(index="year", columns="version", values="return").dropna()
            if len(piv):
                lines.append(
                    f"- {classification}：完整年度中 V7.9 收益更高 {int((piv['V7.9'] > piv['V7.8']).sum())}/{len(piv)} 年。"
                )

    lines.extend(
        [
            "",
            "## 压力窗口（三策略组合）",
            "",
            "| 样本 | 窗口 | V7.8 区间收益 / MDD | V7.9 区间收益 / MDD |",
            "|---|---|---:|---:|",
        ]
    )
    selected_crises = {
        "formal": ("China 2015-16 crash", "COVID crash", "2022 inflation bear"),
        "proxy": (
            "A-share 2007-08 peak-to-trough",
            "GFC Lehman-to-trough",
            "COVID crash",
            "2022 inflation bear",
        ),
    }
    for classification, crisis_names in selected_crises.items():
        for crisis_name in crisis_names:
            subset = crises[
                (crises["classification"] == classification)
                & (crises["sleeve"] == "Combined")
                & (crises["crisis"] == crisis_name)
            ]
            if len(subset) != 2:
                continue
            left = subset[subset["version"] == "V7.8"].iloc[0]
            right = subset[subset["version"] == "V7.9"].iloc[0]
            lines.append(
                f"| {classification} | {crisis_name} | {fmt_pct(left.total_return)} / {fmt_pct(left.max_drawdown)} "
                f"| {fmt_pct(right.total_return)} / {fmt_pct(right.max_drawdown)} |"
            )

    formal_full = metrics[
        (metrics["classification"] == "formal")
        & (metrics["sleeve"] == "Combined")
        & (metrics["window"] == "Full")
    ].set_index("version")
    proxy_full = metrics[
        (metrics["classification"] == "proxy")
        & (metrics["sleeve"] == "Combined")
        & (metrics["window"] == "Full")
    ].set_index("version")
    lines.extend(["", "## 结论", ""])
    if len(formal_full) == 2 and len(proxy_full) == 2:
        lines.extend(
            [
                (
                    f"- 正式样本：V7.9 CAGR 高 {(formal_full.loc['V7.9', 'cagr'] - formal_full.loc['V7.8', 'cagr']):.2%}，"
                    f"但最大回撤深 {abs(formal_full.loc['V7.9', 'max_drawdown']) - abs(formal_full.loc['V7.8', 'max_drawdown']):.2%}。"
                ),
                (
                    f"- 长代理样本：V7.9 CAGR 仅高 {(proxy_full.loc['V7.9', 'cagr'] - proxy_full.loc['V7.8', 'cagr']):.2%}，"
                    f"最大回撤深 {abs(proxy_full.loc['V7.9', 'max_drawdown']) - abs(proxy_full.loc['V7.8', 'max_drawdown']):.2%}；"
                    "收益优势明显收窄，说明正式样本中的大幅领先带有较强近年行情依赖。"
                ),
                "- 因而 V7.9 是更偏进攻的收益型版本，不是无条件风险占优：若优先 CAGR 可选 V7.9；若优先历史危机防守与回撤稳定性，V7.8 更稳。",
            ]
        )

    lines.extend(
        [
            "",
            "## 关键差异与限制",
            "",
            "- V7.9 Sub-B：Top3→Top2、目标波动 25%→30%、绝对动量门槛 4%→0、挑战者保护 1.05→1.00，并移除 EFA/AGG/UUP；这是两版收益差的主要来源。",
            "- V7.9 Sub-A/ADK 的 bias-momentum 有一日回看边界修正，因此两只 A 股袖套也可能出现小幅路径差。",
            "- 代理结果不能替代正式回测：H00852 是全收益代理，不是 ZZ1000 价格指数；美国互惠基金/指数/期货代理并非可交易 ETF，开盘价也只是近似执行输入。",
            "- 未纳入微盘与 Sub-D，因为它们属于独立官方输出，未在本次刷新；硬拼会违反仓库组合刷新规则。",
            "",
            "详细数据见 `window_metrics.csv`、`yearly_returns.csv`、`crisis_metrics.csv`、`rolling_3y_metrics.csv` 与 `audit.json`。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=("formal", "proxy", "all", "aggregate"), default="all"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    mod78 = load_module(V78_PATH, "v78_compare_module")
    mod79 = load_module(V79_PATH, "v79_compare_module")
    runs: dict[tuple[str, str], SleeveRun] = {}
    audit: dict[str, Any] = {
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
            timespec="seconds"
        ),
        "scripts": {"V7.8": str(V78_PATH), "V7.9": str(V79_PATH)},
        "formal_start_rule": "full current DK pool no earlier than ZZ1000 publication 2014-10-17",
        "formal_execution": "Sub-A/ADK close-to-close; Sub-B T close signal -> T+1 adjusted open -> T+1 close; strict missing-open failure",
        "combined_weights_normalized": {
            "Sub-A": 3 / 14,
            "Sub-A-DK": 3 / 14,
            "Sub-B": 8 / 14,
        },
        "proxy_classification": "research-only, not official production backtest",
        "proxy_map": PROXY_MAP,
        "versions": {},
    }

    if args.mode == "aggregate":
        runs = load_saved_runs(out_dir)
        formal_cache = out_dir / "market_cache"
        formal_cn = numeric_panel(formal_cache / "formal_cn_close.csv")
        formal_dk = numeric_panel(formal_cache / "formal_dk_close.csv")
        formal_us = numeric_panel(formal_cache / "formal_us_rot_close.csv")
        formal_open = numeric_panel(formal_cache / "formal_us_adjusted_open.csv")
        audit["formal_data"] = {
            "source": "saved market cache",
            "cn": [
                formal_cn.index.min().date().isoformat(),
                formal_cn.index.max().date().isoformat(),
                len(formal_cn),
            ],
            "dk": [
                formal_dk.index.min().date().isoformat(),
                formal_dk.index.max().date().isoformat(),
                len(formal_dk),
            ],
            "us": [
                formal_us.index.min().date().isoformat(),
                formal_us.index.max().date().isoformat(),
                len(formal_us),
            ],
            "open_assets": len(formal_open.columns),
        }
        proxy_meta = {}
        proxy_cache = formal_cache / "proxy_raw"
        for asset, ticker in PROXY_MAP.items():
            path = proxy_cache / f"{asset.replace('^', '_').replace('/', '_')}.csv"
            frame = numeric_panel(path)
            proxy_meta[asset] = {
                "proxy": ticker,
                "source": "saved market cache",
                "start": frame.index.min().date().isoformat(),
                "end": frame.index.max().date().isoformat(),
                "rows": len(frame),
            }
        audit["proxy_sources"] = proxy_meta
        audit["proxy_cn"] = {
            "source": str(CN_CACHE_PATH),
            "Sub-A": "H20955/H00016/H00852/H00905 + H11077; CYB excluded",
            "ADK": "SZ50/HS300/ZZ500 price + H00852 as ZZ1000 proxy; CYB excluded",
        }

    if args.mode in {"formal", "all"}:
        cn, dk, us, prod, open_dict, source = load_or_fetch_formal_market(
            mod78, out_dir
        )
        audit["formal_data"] = {
            "source": source,
            "cn": [
                cn.index.min().date().isoformat(),
                cn.index.max().date().isoformat(),
                len(cn),
            ],
            "dk": [
                dk.index.min().date().isoformat(),
                dk.index.max().date().isoformat(),
                len(dk),
            ],
            "us": [
                us.index.min().date().isoformat(),
                us.index.max().date().isoformat(),
                len(us),
            ],
            "open_assets": len(open_dict),
        }
        for version, mod in (("V7.8", mod78), ("V7.9", mod79)):
            print(f"running {version} formal", flush=True)
            run = run_formal_sleeves(mod, open_dict, cn, dk, us, prod)
            runs[("formal", version)] = run

    if args.mode in {"proxy", "all"}:
        cn_raw = numeric_panel(CN_CACHE_PATH)
        raw_us, proxy_meta = load_or_fetch_proxy_raw(mod79, out_dir)
        audit["proxy_sources"] = proxy_meta
        audit["proxy_cn"] = {
            "source": str(CN_CACHE_PATH),
            "start": cn_raw.index.min().date().isoformat(),
            "end": cn_raw.index.max().date().isoformat(),
            "Sub-A": "H20955/H00016/H00852/H00905 + H11077; CYB excluded",
            "ADK": "SZ50/HS300/ZZ500 price + H00852 as ZZ1000 proxy; CYB excluded",
        }
        for version, mod in (("V7.8", mod78), ("V7.9", mod79)):
            print(f"running {version} proxy", flush=True)
            runs[("proxy", version)] = run_proxy_sleeves(mod, cn_raw, raw_us)

    if not runs:
        raise RuntimeError("no run completed")
    for (classification, version), run in runs.items():
        audit["versions"][f"{classification}_{version}"] = {
            "ranges": {
                sleeve: [
                    series.index.min().date().isoformat(),
                    series.index.max().date().isoformat(),
                    len(series),
                ]
                for sleeve, series in run.returns.items()
            },
            "notes": run.notes,
        }
    audit["parameter_delta"] = {
        "V7.8": {
            "Sub-B pool": list(mod78.US_ROT_POOL),
            "top_n": 3,
            "target_vol": mod78.US_ROT_TARGET_VOL,
            "abs_threshold": mod78.US_ROT_ABS_THRESHOLD,
            "rebalance_threshold": mod78.US_ROT_REBALANCE_THRESHOLD,
        },
        "V7.9": {
            "Sub-B pool": list(mod79.US_ROT_POOL),
            "top_n": mod79.US_ROT_TOP_N,
            "target_vol": mod79.US_ROT_TARGET_VOL,
            "abs_threshold": mod79.US_ROT_ABS_THRESHOLD,
            "rebalance_threshold": mod79.US_ROT_REBALANCE_THRESHOLD,
        },
    }

    metrics = collect_metrics(runs)
    yearly = collect_yearly(runs)
    crises = collect_crises(runs)
    rolling = collect_rolling(runs)
    save_daily(runs, out_dir)
    metrics.to_csv(out_dir / "window_metrics.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(out_dir / "yearly_returns.csv", index=False, encoding="utf-8-sig")
    crises.to_csv(out_dir / "crisis_metrics.csv", index=False, encoding="utf-8-sig")
    rolling.to_csv(
        out_dir / "rolling_3y_metrics.csv", index=False, encoding="utf-8-sig"
    )
    plot_comparison(runs, out_dir)
    (out_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    report = build_report(metrics, yearly, crises, rolling, audit)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"OUTPUT {out_dir}")
    print(
        metrics[metrics["sleeve"].eq("Combined")][
            [
                "classification",
                "version",
                "window",
                "start",
                "end",
                "cagr",
                "max_drawdown",
                "sharpe_0rf",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()

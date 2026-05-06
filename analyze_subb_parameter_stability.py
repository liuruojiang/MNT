from __future__ import annotations

import argparse
import builtins
import importlib.util
import json
import math
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
WINDOWS = {
    "1Y": pd.DateOffset(years=1),
    "3Y": pd.DateOffset(years=3),
    "5Y": pd.DateOffset(years=5),
    "10Y": pd.DateOffset(years=10),
}
RECENT_WEIGHTS = {"1Y": 0.15, "3Y": 0.35, "5Y": 0.35, "10Y": 0.15}


class _PoeStub:
    query = None
    default_chat: list[Any] = []

    class BotError(Exception):
        pass

    def update_settings(self, settings):
        self.settings = settings


@dataclass(frozen=True)
class Candidate:
    name: str
    lbs: tuple[int, int, int]
    abs_threshold: float
    rebalance_threshold: float
    min_turnover: float
    commission: float
    official_weight: float
    ema_weight: float
    ema_half_life: int
    ema_abs_threshold: float
    target_vol: float
    vol_window: int
    vol_lb: int
    max_lev: float
    volreg_enabled: bool
    volreg_short_window: int
    volreg_long_window: int
    volreg_enter: float
    volreg_exit: float
    ema_vol_halflife_days: int


@dataclass
class MarketContext:
    mod: Any
    script: Path
    close_df: pd.DataFrame
    open_map: dict[str, pd.Series]
    audit: dict[str, Any]


def load_module(script: Path, module_name: str):
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = _PoeStub()
    spec = importlib.util.spec_from_file_location(module_name, str(script))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    if had_poe:
        builtins.poe = old_poe
    else:
        delattr(builtins, "poe")
    return mod


@contextmanager
def temp_globals(mod, updates: dict[str, Any]):
    sentinel = object()
    old = {key: getattr(mod, key, sentinel) for key in updates}
    try:
        for key, value in updates.items():
            setattr(mod, key, value)
        yield
    finally:
        for key, value in old.items():
            if value is sentinel:
                delattr(mod, key)
            else:
                setattr(mod, key, value)


def default_candidate(mod, name: str = "default") -> Candidate:
    return Candidate(
        name=name,
        lbs=tuple(int(x) for x in mod.US_ROT_LBS),
        abs_threshold=float(mod.US_ROT_ABS_THRESHOLD),
        rebalance_threshold=float(mod.US_ROT_REBALANCE_THRESHOLD),
        min_turnover=float(mod.US_ROT_MIN_TURNOVER),
        commission=float(mod.US_ROT_COMMISSION),
        official_weight=float(mod.SUBB_V75_OFFICIAL_WEIGHT),
        ema_weight=float(mod.SUBB_V75_EMA_WEIGHT),
        ema_half_life=int(mod.SUBB_V75_EMA_HALF_LIFE),
        ema_abs_threshold=float(mod.SUBB_V75_EMA_ABS_THRESHOLD),
        target_vol=float(mod.US_ROT_TARGET_VOL),
        vol_window=int(mod.US_ROT_VOL_WINDOW),
        vol_lb=int(mod.US_ROT_VOL_LB),
        max_lev=float(mod.US_ROT_MAX_LEV),
        volreg_enabled=bool(mod.US_ROT_VOLREG_ENABLED),
        volreg_short_window=int(mod.US_ROT_VOLREG_SHORT_W),
        volreg_long_window=int(mod.US_ROT_VOLREG_LONG_W),
        volreg_enter=float(mod.US_ROT_VOLREG_THRESHOLD),
        volreg_exit=float(mod.US_ROT_VOLREG_EXIT_THRESHOLD),
        ema_vol_halflife_days=int(mod.SUBB_V75_EMA_VOL_HALFLIFE_DAYS),
    )


def _fetch_one(mod, ticker: str) -> tuple[pd.DataFrame, str]:
    df, source = mod.fetch_yahoo(ticker, start_date="2003-01-01")
    if df is None or len(df) <= 50 or "close" not in df.columns:
        raise RuntimeError(f"failed to fetch usable data for {ticker}")
    return df, str(source)


def build_market_context(mod, script: Path) -> MarketContext:
    tickers = sorted(set(mod.US_ROT_POOL + ["BIL", "SPY", mod.US_ROT_EMXC_BT_PROXY, "IBIT"]))
    us_raw: dict[str, pd.DataFrame] = {}
    sources: dict[str, str] = {}
    raw_ranges: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        df, source = _fetch_one(mod, ticker)
        us_raw[ticker] = df
        sources[ticker] = source
        raw_ranges[ticker] = {
            "start": df.index[0].date().isoformat(),
            "end": df.index[-1].date().isoformat(),
            "rows": int(len(df)),
            "has_open": bool("open" in df.columns),
        }
        time.sleep(0.1)

    rot_tickers = list(mod.US_ROT_POOL) + ["BIL"]
    late_rot = mod._us_rot_late_history_tickers()
    rot_core = [ticker for ticker in rot_tickers if ticker not in late_rot]
    if "EMXC" in mod.US_ROT_POOL and mod.US_ROT_EMXC_BT_PROXY not in rot_core and mod.US_ROT_EMXC_BT_PROXY in us_raw:
        rot_core.append(mod.US_ROT_EMXC_BT_PROXY)

    close_df = pd.concat(
        [us_raw[ticker][["close"]].rename(columns={"close": ticker}) for ticker in rot_core if ticker in us_raw],
        axis=1,
    ).ffill().dropna()

    if "EMXC" in mod.US_ROT_POOL and mod.US_ROT_EMXC_BT_PROXY in us_raw:
        proxy_col = close_df[mod.US_ROT_EMXC_BT_PROXY].copy() if mod.US_ROT_EMXC_BT_PROXY in close_df.columns else None
        emxc_raw = us_raw.get("EMXC")
        if proxy_col is not None:
            hybrid = proxy_col.rename("EMXC")
            if emxc_raw is not None and len(emxc_raw) > 0:
                emxc_ser = emxc_raw["close"].reindex(hybrid.index)
                switch_idx = hybrid.index >= mod.US_ROT_EMXC_BT_START
                first_emxc_date = emxc_ser.loc[switch_idx].first_valid_index() if switch_idx.any() else None
                if first_emxc_date is not None:
                    scale_factor = hybrid.loc[first_emxc_date] / emxc_ser.loc[first_emxc_date]
                    hybrid.loc[switch_idx] = emxc_ser.loc[switch_idx] * scale_factor
            close_df["EMXC"] = hybrid
            if mod.US_ROT_EMXC_BT_PROXY in close_df.columns and mod.US_ROT_EMXC_BT_PROXY not in mod.US_ROT_POOL:
                close_df = close_df.drop(columns=[mod.US_ROT_EMXC_BT_PROXY])

    for ticker in late_rot:
        if ticker == "EMXC":
            continue
        if ticker in us_raw:
            close_df = close_df.join(us_raw[ticker][["close"]].rename(columns={"close": ticker}), how="left")

    if "BTC-USD" in close_df.columns and "IBIT" in us_raw and "close" in us_raw["IBIT"].columns:
        close_df["BTC-USD"] = mod.build_ibit_spliced(
            pd.DataFrame(
                {
                    "BTC-USD": close_df["BTC-USD"],
                    "IBIT": us_raw["IBIT"]["close"].reindex(close_df.index),
                }
            )
        )

    if "SPY" not in close_df.columns and "SPY" in us_raw:
        close_df["SPY"] = us_raw["SPY"]["close"].reindex(close_df.index)

    stock_rot = [ticker for ticker in rot_tickers if ticker in us_raw and ticker != "BTC-USD"]
    if stock_rot:
        close_df = close_df.loc[: max(us_raw[ticker].index[-1] for ticker in stock_rot)]
    weekend_rows = int((close_df.index.dayofweek >= 5).sum())
    if weekend_rows:
        raise RuntimeError(f"US rotation calendar contains {weekend_rows} weekend rows")

    open_map = {ticker: df["open"] for ticker, df in us_raw.items() if "open" in df.columns}
    missing_open = sorted(set(tickers) - set(open_map))
    audit = {
        "script": str(script),
        "entrypoint": (
            "Sub-B formal path: production US rotation data construction -> run_us_rotation_mix() "
            "official macro-gated leg -> run_subb_v75_ema_base7_rotation() EMA leg -> "
            "blend_subb_v75_results() -> optional apply_vol_regime_overlay()"
        ),
        "data_source": "fetch_yahoo() production path with Yahoo/Stooq fallback",
        "sources": sources,
        "raw_ranges": raw_ranges,
        "merged_start": close_df.index[0].date().isoformat(),
        "merged_end": close_df.index[-1].date().isoformat(),
        "merged_rows": int(len(close_df)),
        "duplicate_dates": int(close_df.index.duplicated().sum()),
        "weekend_rows": weekend_rows,
        "columns": list(close_df.columns),
        "open_map_count": int(len(open_map)),
        "missing_open": missing_open,
        "return_column": "return",
        "cost_model": "US_ROT_COMMISSION applied to leg execution, blend execution, and VolReg transition turnover",
        "timing": "T close signal, pending target executed at T+1 adjusted open when us_open is available",
        "emxc_splice": f"EEM proxy before scaled EMXC from {mod.US_ROT_EMXC_BT_START.date().isoformat()}",
        "btc_splice": "BTC-USD replaced by IBIT-spliced series where IBIT exists; BTC joined on US ETF calendar only",
    }
    return MarketContext(mod=mod, script=script, close_df=close_df, open_map=open_map, audit=audit)


def candidate_updates(candidate: Candidate) -> dict[str, Any]:
    return {
        "US_ROT_LBS": tuple(candidate.lbs),
        "US_ROT_LB": int(candidate.lbs[1]),
        "US_ROT_MAX_LB": int(max(candidate.lbs)),
        "US_ROT_ABS_THRESHOLD": float(candidate.abs_threshold),
        "US_ROT_REBALANCE_THRESHOLD": float(candidate.rebalance_threshold),
        "US_ROT_MIN_TURNOVER": float(candidate.min_turnover),
        "US_ROT_COMMISSION": float(candidate.commission),
        "US_ROT_TARGET_VOL": float(candidate.target_vol),
        "US_ROT_VOL_WINDOW": int(candidate.vol_window),
        "US_ROT_VOL_LB": int(candidate.vol_lb),
        "US_ROT_MAX_LEV": float(candidate.max_lev),
        "SUBB_V75_OFFICIAL_WEIGHT": float(candidate.official_weight),
        "SUBB_V75_EMA_WEIGHT": float(candidate.ema_weight),
        "SUBB_V75_EMA_HALF_LIFE": int(candidate.ema_half_life),
        "SUBB_V75_EMA_ABS_THRESHOLD": float(candidate.ema_abs_threshold),
        "SUBB_V75_EMA_VOL_HALFLIFE_DAYS": int(candidate.ema_vol_halflife_days),
        "US_ROT_VOLREG_ENABLED": bool(candidate.volreg_enabled),
        "US_ROT_VOLREG_SHORT_W": int(candidate.volreg_short_window),
        "US_ROT_VOLREG_LONG_W": int(candidate.volreg_long_window),
        "US_ROT_VOLREG_THRESHOLD": float(candidate.volreg_enter),
        "US_ROT_VOLREG_EXIT_THRESHOLD": float(candidate.volreg_exit),
    }


def run_ema_leg(ctx: MarketContext, candidate: Candidate) -> pd.DataFrame:
    mod = ctx.mod
    with temp_globals(mod, candidate_updates(candidate)):
        return mod.run_subb_v75_ema_base7_rotation(
            ctx.close_df,
            base_codes=list(mod.US_ROT_BASE_POOL),
            half_life=candidate.ema_half_life,
            abs_threshold=candidate.ema_abs_threshold,
            top_n=3,
            min_turnover=candidate.min_turnover,
            threshold=candidate.rebalance_threshold,
            us_open=ctx.open_map,
            weight_assets=list(mod.US_ROT_BASE_POOL),
        )


def run_official_leg(ctx: MarketContext, candidate: Candidate) -> pd.DataFrame:
    mod = ctx.mod
    with temp_globals(mod, candidate_updates(candidate)):
        return mod.run_us_rotation_mix(
            ctx.close_df,
            list(mod.US_ROT_BASE_POOL),
            top_n=3,
            abs_threshold=candidate.abs_threshold,
            min_turnover=candidate.min_turnover,
            threshold=candidate.rebalance_threshold,
            us_open=ctx.open_map,
            ranking_code_selector=mod._subb_active_ranking_codes,
            weight_assets=list(mod.US_ROT_POOL),
        )


def run_candidate(
    ctx: MarketContext,
    candidate: Candidate,
    cached_official: pd.DataFrame | None = None,
    cached_ema: pd.DataFrame | None = None,
    cached_base: pd.DataFrame | None = None,
) -> pd.DataFrame:
    mod = ctx.mod
    with temp_globals(mod, candidate_updates(candidate)):
        if cached_base is not None:
            out = cached_base.copy()
        else:
            official = cached_official if cached_official is not None else run_official_leg(ctx, candidate)
            ema = cached_ema if cached_ema is not None else run_ema_leg(ctx, candidate)
            out = mod.blend_subb_v75_results(
                official,
                ema,
                official_weight=candidate.official_weight,
                ema_weight=candidate.ema_weight,
            )
        if candidate.volreg_enabled and "SPY" in ctx.close_df.columns:
            out = mod.apply_vol_regime_overlay(out, ctx.close_df["SPY"])
    out = out.copy()
    out["return"] = pd.to_numeric(out["return"], errors="coerce").fillna(0.0)
    out["nav"] = (1.0 + out["return"]).cumprod()
    return out


def calc_metrics(ret: pd.Series) -> dict[str, float] | None:
    ret = pd.to_numeric(ret, errors="coerce").dropna()
    if len(ret) < 20:
        return None
    nav = (1.0 + ret).cumprod()
    years = len(ret) / 252.0
    if years <= 0 or nav.iloc[-1] <= 0:
        return None
    std = float(ret.std(ddof=1))
    maxdd = float((nav / nav.cummax() - 1.0).min())
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0)
    monthly = ret.groupby(ret.index.to_period("M")).apply(lambda values: (1.0 + values).prod() - 1.0)
    return {
        "days": int(len(ret)),
        "cagr": cagr,
        "vol": float(std * math.sqrt(252.0)),
        "sharpe": float(ret.mean() / std * math.sqrt(252.0)) if std > 0 else np.nan,
        "maxdd": maxdd,
        "calmar": float(cagr / abs(maxdd)) if maxdd < 0 else np.nan,
        "final_nav": float(nav.iloc[-1]),
        "monthly_win_rate": float((monthly > 0).mean()) if len(monthly) else np.nan,
    }


def exposure_turnover(result: pd.DataFrame) -> dict[str, float]:
    w_cols = [col for col in result.columns if col.startswith("w_")]
    risky_cols = [col for col in w_cols if col not in ("w_BIL", "w_CASH")]

    def numeric_col(name: str) -> pd.Series:
        if name in result.columns:
            return pd.to_numeric(result[name], errors="coerce").fillna(0.0)
        return pd.Series(0.0, index=result.index)

    out = {
        "avg_bil": float(numeric_col("w_BIL").mean()),
        "avg_cash": float(numeric_col("w_CASH").mean()),
        "avg_risky": float(result[risky_cols].sum(axis=1).mean()) if risky_cols else 0.0,
        "max_risky": float(result[risky_cols].sum(axis=1).max()) if risky_cols else 0.0,
    }
    for col in ("subb_effective_turnover", "subb_execution_turnover", "turnover"):
        if col in result.columns:
            turnover = pd.to_numeric(result[col], errors="coerce").fillna(0.0)
            out["annual_turnover"] = float(turnover.sum() / max(len(turnover) / 252.0, 1e-9))
            break
    else:
        out["annual_turnover"] = np.nan
    for col in ("subb_effective_cost", "subb_execution_cost", "execution_cost"):
        if col in result.columns:
            out["total_trade_cost"] = float(pd.to_numeric(result[col], errors="coerce").fillna(0.0).sum())
            break
    else:
        out["total_trade_cost"] = np.nan
    return out


def segment_rows(version: str, candidate: Candidate, result: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    ret = result["return"].astype(float)
    end = ret.index[-1]
    segments = {"full_common": (ret.index[0], end)}
    for name, offset in WINDOWS.items():
        segments[name] = (end - offset, end)
    for segment, (start, finish) in segments.items():
        seg_ret = ret.loc[start:finish]
        metrics = calc_metrics(seg_ret)
        if metrics is None:
            continue
        detail = result.loc[seg_ret.index]
        row = {
            "version": version,
            "candidate": candidate.name,
            "segment": segment,
            "start": seg_ret.index[0].date().isoformat(),
            "end": seg_ret.index[-1].date().isoformat(),
            **asdict(candidate),
            **metrics,
            **exposure_turnover(detail),
        }
        rows.append(row)
    return rows


def yearly_rows(version: str, candidate: Candidate, result: pd.DataFrame) -> list[dict[str, Any]]:
    ret = result["return"].astype(float).dropna()
    yearly = ret.groupby(ret.index.year).apply(lambda values: (1.0 + values).prod() - 1.0)
    return [
        {
            "version": version,
            "candidate": candidate.name,
            **asdict(candidate),
            "year": int(year),
            "return": float(value),
        }
        for year, value in yearly.items()
    ]


def add_recent_score(summary: pd.DataFrame, param_cols: list[str]) -> pd.DataFrame:
    rows = []
    group_cols = ["version", "candidate"] + param_cols
    for keys, sub in summary.groupby(group_cols, dropna=False):
        key_map = dict(zip(group_cols, keys))
        by_seg = sub.set_index("segment")
        score = 0.0
        complete = True
        for segment, weight in RECENT_WEIGHTS.items():
            if segment not in by_seg.index:
                complete = False
                break
            score += float(by_seg.loc[segment, "sharpe"]) * weight
        ten = by_seg.loc["10Y"] if "10Y" in by_seg.index else by_seg.iloc[-1]
        rows.append(
            {
                **key_map,
                "recent_weighted_sharpe": score if complete else np.nan,
                "mean_recent_cagr": float(by_seg.loc[list(RECENT_WEIGHTS), "cagr"].mean()) if complete else np.nan,
                "worst_recent_maxdd": float(by_seg.loc[list(RECENT_WEIGHTS), "maxdd"].min()) if complete else np.nan,
                "10y_cagr": float(ten["cagr"]),
                "10y_maxdd": float(ten["maxdd"]),
                "10y_sharpe": float(ten["sharpe"]),
                "10y_calmar": float(ten["calmar"]),
                "10y_annual_turnover": float(ten.get("annual_turnover", np.nan)),
                "10y_total_trade_cost": float(ten.get("total_trade_cost", np.nan)),
            }
        )
    rank = pd.DataFrame(rows)
    return rank.sort_values(["version", "recent_weighted_sharpe", "10y_cagr"], ascending=[True, False, False])


def compare_versions(rank: pd.DataFrame, param_cols: list[str]) -> pd.DataFrame:
    left = rank[rank["version"].eq("V7.5")].copy()
    right = rank[rank["version"].eq("V7.6")].copy()
    joined = left.merge(right, on=param_cols, suffixes=("_v75", "_v76"))
    for col in ["recent_weighted_sharpe", "mean_recent_cagr", "worst_recent_maxdd", "10y_cagr", "10y_maxdd", "10y_sharpe", "10y_annual_turnover"]:
        joined[f"delta_{col}"] = joined[f"{col}_v76"] - joined[f"{col}_v75"]
    return joined.sort_values(["recent_weighted_sharpe_v76", "recent_weighted_sharpe_v75"], ascending=False)


def load_partial_state(out_dir: Path, expected_segments: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, pd.Series], set[tuple[str, str]]]:
    summary_path = out_dir / "partial_summary.csv"
    yearly_path = out_dir / "partial_yearly_returns.csv"
    daily_path = out_dir / "partial_daily_returns.csv"
    if not summary_path.exists():
        return [], [], {}, set()

    summary = pd.read_csv(summary_path)
    yearly = pd.read_csv(yearly_path) if yearly_path.exists() else pd.DataFrame()
    daily = pd.read_csv(daily_path, index_col="date", parse_dates=True) if daily_path.exists() else pd.DataFrame()
    daily_returns = {col: daily[col].dropna() for col in daily.columns}

    completed: set[tuple[str, str]] = set()
    for (version, candidate), sub in summary.groupby(["version", "candidate"], dropna=False):
        daily_col = f"{version}_{candidate}"
        if len(sub) == expected_segments and daily_col in daily_returns:
            completed.add((str(version), str(candidate)))

    if not completed:
        return [], [], {}, set()

    keep_summary = summary[
        summary.apply(lambda row: (str(row["version"]), str(row["candidate"])) in completed, axis=1)
    ]
    if yearly.empty:
        keep_yearly = yearly
    else:
        keep_yearly = yearly[
            yearly.apply(lambda row: (str(row["version"]), str(row["candidate"])) in completed, axis=1)
        ]
    daily_returns = {
        col: series
        for col, series in daily_returns.items()
        if tuple(col.split("_", 1)) in completed
    }
    print(f"[resume] loaded {len(completed)} completed candidates from partial outputs", flush=True)
    return keep_summary.to_dict("records"), keep_yearly.to_dict("records"), daily_returns, completed


def candidate_group(default: Candidate, group: str) -> tuple[list[Candidate], list[str], dict[str, Any]]:
    if group == "lbs":
        lbs_grid = [
            (100, 200, 300),
            (120, 240, 360),
            (120, 260, 390),
            (130, 240, 390),
            (130, 260, 390),
            (130, 280, 390),
            (160, 260, 390),
            (160, 320, 480),
            (200, 300, 450),
        ]
        candidates = [
            replace(default, name=f"lbs_{'_'.join(map(str, lbs))}", lbs=lbs)
            for lbs in lbs_grid
        ]
        return candidates, ["lbs"], {"lbs_grid": lbs_grid}

    if group == "lbs_local":
        lbs_grid = [
            (short, mid, long)
            for short, mid, long in product([140, 160, 180], [240, 260, 280], [360, 390, 420])
        ]
        candidates = [
            replace(default, name=f"lbs_{'_'.join(map(str, lbs))}", lbs=lbs)
            for lbs in lbs_grid
        ]
        return candidates, ["lbs"], {
            "center": (160, 260, 390),
            "short_values": [140, 160, 180],
            "mid_values": [240, 260, 280],
            "long_values": [360, 390, 420],
            "lbs_grid": lbs_grid,
        }

    if group == "blend_ema":
        blend_grid = [(0.75, 0.25), (0.50, 0.50), (0.25, 0.75)]
        ema_grid = [(60, 0.16), (100, 0.08), (100, 0.16), (100, 0.24), (150, 0.16)]
        candidates = []
        for official_weight, ema_weight in blend_grid:
            for half_life, ema_abs in ema_grid:
                candidates.append(
                    replace(
                        default,
                        name=f"ow{official_weight:g}_ema{half_life}_{ema_abs:g}",
                        official_weight=official_weight,
                        ema_weight=ema_weight,
                        ema_half_life=half_life,
                        ema_abs_threshold=ema_abs,
                    )
                )
        return candidates, ["official_weight", "ema_weight", "ema_half_life", "ema_abs_threshold"], {"blend_grid": blend_grid, "ema_grid": ema_grid}

    if group == "thresholds":
        candidates = []
        for abs_threshold, rebalance_threshold in product([0.00, 0.04, 0.08], [1.00, 1.03, 1.05, 1.08, 1.10]):
            candidates.append(
                replace(
                    default,
                    name=f"abs{abs_threshold:g}_rb{rebalance_threshold:g}",
                    abs_threshold=abs_threshold,
                    rebalance_threshold=rebalance_threshold,
                )
            )
        return candidates, ["abs_threshold", "rebalance_threshold"], {"abs_thresholds": [0.00, 0.04, 0.08], "rebalance_thresholds": [1.00, 1.03, 1.05, 1.08, 1.10]}

    if group == "sizing_volreg":
        candidates = []
        volreg_grid = [(True, 2.0, 1.6), (True, 1.8, 1.4), (False, 2.0, 1.6)]
        for target_vol, vol_window, max_lev, volreg in product([0.20, 0.25, 0.30], [40, 80], [1.5, 2.0], volreg_grid):
            enabled, enter, exit_value = volreg
            candidates.append(
                replace(
                    default,
                    name=f"tv{target_vol:g}_vw{vol_window}_lev{max_lev:g}_vr{int(enabled)}_{enter:g}_{exit_value:g}",
                    target_vol=target_vol,
                    vol_window=vol_window,
                    max_lev=max_lev,
                    volreg_enabled=enabled,
                    volreg_enter=enter,
                    volreg_exit=exit_value,
                )
            )
        return candidates, ["target_vol", "vol_window", "max_lev", "volreg_enabled", "volreg_enter", "volreg_exit"], {
            "target_vols": [0.20, 0.25, 0.30],
            "vol_windows": [40, 80],
            "max_levs": [1.5, 2.0],
            "volreg_grid": volreg_grid,
        }

    if group == "turnover_cost":
        candidates = []
        min_turnover_grid = [0.00, 0.01, 0.03, 0.05, 0.08]
        commission_grid = [0.0005, 0.0010, 0.0020, 0.0030]
        for min_turnover, commission in product(min_turnover_grid, commission_grid):
            candidates.append(
                replace(
                    default,
                    name=f"mt{min_turnover:g}_fee{commission:g}",
                    min_turnover=min_turnover,
                    commission=commission,
                )
            )
        return candidates, ["min_turnover", "commission"], {
            "min_turnover_grid": min_turnover_grid,
            "commission_grid": commission_grid,
        }

    if group == "volreg_windows":
        candidates = []
        window_grid = [(15, 90), (20, 120), (20, 180), (30, 120), (30, 180), (40, 180), (40, 252)]
        for short_window, long_window in window_grid:
            candidates.append(
                replace(
                    default,
                    name=f"vrwin{short_window}_{long_window}",
                    volreg_enabled=True,
                    volreg_short_window=short_window,
                    volreg_long_window=long_window,
                )
            )
        return candidates, ["volreg_short_window", "volreg_long_window"], {"window_grid": window_grid}

    if group == "vol_weight":
        candidates = []
        for vol_lb in [10, 20, 40, 60]:
            candidates.append(replace(default, name=f"vollb{vol_lb}", vol_lb=vol_lb))
        return candidates, ["vol_lb"], {"vol_lb_grid": [10, 20, 40, 60]}

    if group == "ema_volscale":
        candidates = []
        halflife_grid = [63, 126, 189, 252]
        for halflife_days in halflife_grid:
            candidates.append(
                replace(
                    default,
                    name=f"emavolhl{halflife_days}",
                    ema_vol_halflife_days=halflife_days,
                )
            )
        return candidates, ["ema_vol_halflife_days"], {"ema_vol_halflife_days_grid": halflife_grid}

    raise ValueError(f"unknown group: {group}")


def version_constants(mod) -> dict[str, Any]:
    keys = [
        "US_ROT_POOL",
        "US_ROT_BASE_POOL",
        "US_ROT_LBS",
        "US_ROT_LB",
        "US_ROT_ABS_THRESHOLD",
        "US_ROT_REBALANCE_THRESHOLD",
        "US_ROT_MIN_TURNOVER",
        "SUBB_V75_OFFICIAL_WEIGHT",
        "SUBB_V75_EMA_WEIGHT",
        "SUBB_V75_EMA_HALF_LIFE",
        "SUBB_V75_EMA_ABS_THRESHOLD",
        "SUBB_V75_EMA_VOL_MODE",
        "SUBB_V75_EMA_VOL_HALFLIFE_DAYS",
        "US_ROT_TARGET_VOL",
        "US_ROT_VOL_WINDOW",
        "US_ROT_VOL_LB",
        "US_ROT_MAX_LEV",
        "US_ROT_VOLREG_ENABLED",
        "US_ROT_VOLREG_SHORT_W",
        "US_ROT_VOLREG_LONG_W",
        "US_ROT_VOLREG_THRESHOLD",
        "US_ROT_VOLREG_EXIT_THRESHOLD",
        "US_ROT_COMMISSION",
        "US_ROT_EMXC_BT_START",
        "US_ROT_EMXC_BT_PROXY",
    ]
    out = {}
    for key in keys:
        value = getattr(mod, key, None)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif isinstance(value, tuple):
            value = list(value)
        out[key] = value
    return out


def run_scan(group: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    expected_segments = len(WINDOWS) + 1
    all_summary, all_yearly, daily_returns, completed_candidates = load_partial_state(out_dir, expected_segments)
    audit: dict[str, Any] = {
        "group": group,
        "recent_weighted_sharpe": RECENT_WEIGHTS,
        "versions": {},
        "resumed_completed_candidates": len(completed_candidates),
    }

    for version, script_name in [("V7.5", "mnt_bot V 7.5 plus.py"), ("V7.6", "mnt_bot V 7.6 plus.py")]:
        script = ROOT / script_name
        print(f"[{version}] loading {script}", flush=True)
        mod = load_module(script, f"subb_stability_{version.replace('.', '_')}")
        default = default_candidate(mod)
        candidates, param_cols, grid_values = candidate_group(default, group)
        audit["param_cols"] = param_cols
        audit["grid_values"] = grid_values
        audit["variants_per_version"] = len(candidates)
        audit["versions"][version] = {"constants": version_constants(mod)}
        ctx = build_market_context(mod, script)
        audit["versions"][version].update(ctx.audit)
        cached_official = None
        cached_ema = None
        ema_cache: dict[tuple[int, float], pd.DataFrame] = {}
        base_cache: dict[tuple[float, int, float], pd.DataFrame] = {}
        if group in {"lbs", "lbs_local"}:
            print(f"[{version}] caching EMA leg once for {group} group", flush=True)
            cached_ema = run_ema_leg(ctx, candidates[0])
        if group == "blend_ema":
            print(f"[{version}] caching official leg once for blend_ema group", flush=True)
            cached_official = run_official_leg(ctx, candidates[0])

        for idx, candidate in enumerate(candidates, start=1):
            print(f"[{version}] {idx}/{len(candidates)} {candidate.name}", flush=True)
            if (version, candidate.name) in completed_candidates:
                print(f"[{version}] skipping completed {candidate.name}", flush=True)
                continue
            per_candidate_ema = cached_ema
            if group in {"blend_ema", "thresholds", "turnover_cost", "vol_weight", "ema_volscale"}:
                ema_key = (
                    candidate.ema_half_life,
                    candidate.ema_abs_threshold,
                    candidate.rebalance_threshold,
                    candidate.min_turnover,
                    candidate.commission,
                    candidate.target_vol,
                    candidate.vol_window,
                    candidate.vol_lb,
                    candidate.max_lev,
                    candidate.ema_vol_halflife_days,
                )
                if ema_key not in ema_cache:
                    print(f"[{version}] caching EMA leg {ema_key}", flush=True)
                    ema_cache[ema_key] = run_ema_leg(ctx, candidate)
                per_candidate_ema = ema_cache[ema_key]
            cached_base = None
            if group in {"sizing_volreg", "volreg_windows"}:
                base_key = (
                    candidate.lbs,
                    candidate.abs_threshold,
                    candidate.rebalance_threshold,
                    candidate.min_turnover,
                    candidate.commission,
                    candidate.official_weight,
                    candidate.ema_weight,
                    candidate.ema_half_life,
                    candidate.ema_abs_threshold,
                    candidate.target_vol,
                    candidate.vol_window,
                    candidate.vol_lb,
                    candidate.max_lev,
                    candidate.ema_vol_halflife_days,
                )
                if base_key not in base_cache:
                    print(f"[{version}] caching base stream {base_key}", flush=True)
                    base_candidate = replace(candidate, volreg_enabled=False)
                    base_cache[base_key] = run_candidate(ctx, base_candidate)
                cached_base = base_cache[base_key]
            result = run_candidate(
                ctx,
                candidate,
                cached_official=cached_official,
                cached_ema=per_candidate_ema,
                cached_base=cached_base,
            )
            all_summary.extend(segment_rows(version, candidate, result))
            all_yearly.extend(yearly_rows(version, candidate, result))
            daily_returns[f"{version}_{candidate.name}"] = result["return"]
            pd.DataFrame(all_summary).to_csv(out_dir / "partial_summary.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame(all_yearly).to_csv(out_dir / "partial_yearly_returns.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame(daily_returns).to_csv(out_dir / "partial_daily_returns.csv", index_label="date", encoding="utf-8-sig")

    summary = pd.DataFrame(all_summary)
    param_cols = audit["param_cols"]
    rank = add_recent_score(summary, param_cols)
    compare = compare_versions(rank, param_cols)
    pd.DataFrame(all_yearly).to_csv(out_dir / "yearly_returns.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(daily_returns).to_csv(out_dir / "daily_returns.csv", index_label="date", encoding="utf-8-sig")
    summary.to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig")
    rank.to_csv(out_dir / "rank.csv", index=False, encoding="utf-8-sig")
    compare.to_csv(out_dir / "v75_v76_compare.csv", index=False, encoding="utf-8-sig")
    (out_dir / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"done: {out_dir}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=[
        "lbs",
        "lbs_local",
        "blend_ema",
        "thresholds",
        "sizing_volreg",
        "turnover_cost",
        "volreg_windows",
        "vol_weight",
        "ema_volscale",
    ], required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    run_scan(args.group, Path(args.out_dir))


if __name__ == "__main__":
    main()

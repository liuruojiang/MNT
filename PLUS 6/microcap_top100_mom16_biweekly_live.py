from __future__ import annotations

import argparse
import json
import re
import time
import warnings
from pathlib import Path
from types import SimpleNamespace

import akshare as ak
import matplotlib
import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import analyze_microcap_zz1000_hedge as hedge_mod
import analyze_top100_rebalance_frequency as freq_mod
import fetch_wind_microcap_index as fetch_mod


ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / ".microcap_index_cache"
REALTIME_DIR = CACHE_DIR / "realtime"

TOP_N = 100
LOOKBACK = 16
REBALANCE_WEEKDAY = "Thursday"
HEDGE_COLUMN = hedge_mod.DEFAULT_HEDGE_COLUMN
FIXED_HEDGE_RATIO = 1.0
FUTURES_DRAG = hedge_mod.DEFAULT_FUTURES_DRAG
REQUIRE_POSITIVE_MICROCAP_MOM = False
TAIL_JITTER_WARNING_GAP = 0.001
TAIL_JITTER_CAUTION_GAP = 0.002

DEFAULT_INDEX_CSV = ROOT / "wind_microcap_top_100_biweekly_thursday_16y_cached.csv"
DEFAULT_OUTPUT_PREFIX = "microcap_top100_mom16_biweekly_live"
DEFAULT_COSTED_NAV_CSV = ROOT / "microcap_top100_mom16_hedge_zz1000_biweekly_thursday_16y_costed_nav.csv"
WEEK_FREQ_BY_START = {
    "Monday": "W-SUN",
    "Tuesday": "W-MON",
    "Wednesday": "W-TUE",
    "Thursday": "W-WED",
    "Friday": "W-THU",
}

warnings.filterwarnings("ignore", category=PerformanceWarning)

CN_NUM = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "半": 0.5,
}
DAY_SUFFIX = r"[日号]?"
PERFORMANCE_PATTERN = re.compile(r"表现|收益(?!曲线)|回撤|年化|夏普|回报|净值曲线")
NON_TRADABLE_NAME_PATTERN = re.compile(r"(退$|退市|摘牌)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Top100 microcap practical script. Fixed params: exclude current ST, Top100 "
            "smallest-cap A-shares, biweekly Thursday-signal rebalance, 16-day relative "
            "momentum versus CSI 1000. Supports both batch export and query commands."
        )
    )
    parser.add_argument("query_tokens", nargs="*", help="Optional query, such as 信号 / 实时信号 / 成分股 / 进出名单 / 表现 2024至今")
    parser.add_argument("--panel-path", type=Path, default=hedge_mod.DEFAULT_PANEL)
    parser.add_argument("--index-csv", type=Path, default=DEFAULT_INDEX_CSV)
    parser.add_argument("--costed-nav-csv", type=Path, default=DEFAULT_COSTED_NAV_CSV)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--capital", type=float, default=None, help="Optional gross stock capital used for per-stock target notional.")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument(
        "--realtime-cache-seconds",
        type=int,
        default=30,
        help="Only reuse realtime results within this many seconds. Default is 30s for same-decision-window sharing.",
    )
    parser.add_argument(
        "--rebuild-index-if-missing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If the cached Top100 biweekly proxy is missing, rebuild it from local/public cache.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Only used when rebuilding the proxy. Refresh AKShare cache before rebuilding.",
    )
    return parser.parse_args()


def is_tradable_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return True
    return NON_TRADABLE_NAME_PATTERN.search(text) is None


def build_output_paths(output_prefix: str) -> dict[str, Path]:
    return {
        "summary": ROOT / f"{output_prefix}_summary.json",
        "signal": ROOT / f"{output_prefix}_latest_signal.csv",
        "members": ROOT / f"{output_prefix}_target_members.csv",
        "changes": ROOT / f"{output_prefix}_rebalance_changes.csv",
        "nav": ROOT / f"{output_prefix}_nav.csv",
        "proxy_meta": ROOT / f"{output_prefix}_proxy_meta.json",
        "proxy_members": ROOT / f"{output_prefix}_proxy_members.csv",
        "realtime_signal": ROOT / f"{output_prefix}_realtime_signal.csv",
        "realtime_members": ROOT / f"{output_prefix}_realtime_target_members.csv",
        "realtime_changes": ROOT / f"{output_prefix}_realtime_rebalance_changes.csv",
        "performance_summary": ROOT / f"{output_prefix}_performance_summary.csv",
        "performance_yearly": ROOT / f"{output_prefix}_performance_yearly.csv",
        "performance_nav": ROOT / f"{output_prefix}_performance_nav.csv",
        "performance_chart": ROOT / f"{output_prefix}_performance_curve.png",
        "performance_json": ROOT / f"{output_prefix}_performance_summary.json",
        "cache_static_meta": REALTIME_DIR / f"{output_prefix}_static_meta.json",
        "cache_static_target": REALTIME_DIR / f"{output_prefix}_static_target_members.csv",
        "cache_static_effective": REALTIME_DIR / f"{output_prefix}_static_effective_members.csv",
        "cache_static_changes": REALTIME_DIR / f"{output_prefix}_static_rebalance_changes.csv",
        "cache_realtime_meta": REALTIME_DIR / f"{output_prefix}_realtime_meta.json",
        "cache_realtime_members": REALTIME_DIR / f"{output_prefix}_realtime_cached_members.csv",
        "cache_realtime_changes": REALTIME_DIR / f"{output_prefix}_realtime_cached_changes.csv",
        "cache_realtime_signal": REALTIME_DIR / f"{output_prefix}_realtime_cached_signal.csv",
    }


def build_biweekly_rebalance_dates(
    trading_dates: pd.DatetimeIndex,
    week_anchor: str = REBALANCE_WEEKDAY,
) -> pd.DatetimeIndex:
    freq = WEEK_FREQ_BY_START.get(week_anchor)
    if freq is None:
        raise ValueError(f"Unsupported rebalance weekday anchor: {week_anchor}")
    if len(trading_dates) == 0:
        return pd.DatetimeIndex([])
    week_periods = trading_dates.to_period(freq)
    unique_weeks = sorted(pd.Index(week_periods.unique()))
    week_keys = pd.Series([i // 2 for i, _ in enumerate(unique_weeks)], index=unique_weeks)
    aligned_keys = pd.Index(week_periods).map(lambda p: week_keys[p])
    grouped = trading_dates.to_series().groupby(aligned_keys)
    return pd.DatetimeIndex(grouped.min().tolist())


def build_local_proxy_bundle(
    args: argparse.Namespace,
    trading_dates: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    rebalance_dates = build_biweekly_rebalance_dates(trading_dates)
    symbols = freq_mod.load_universe()
    returns_df, caps_by_date = freq_mod.load_cache_panels(
        symbols=symbols,
        trading_dates=trading_dates,
        cap_dates=rebalance_dates,
        max_workers=args.max_workers,
    )
    name_map = load_name_map()

    rebalance_set = set(rebalance_dates)
    next_members_map: dict[pd.Timestamp, list[str]] = {}
    members_rows: list[dict[str, object]] = []
    turnover_rows: list[dict[str, object]] = []
    prev_members: list[str] | None = None

    for dt in rebalance_dates:
        cap_map = caps_by_date.get(pd.Timestamp(dt), {})
        ranked = [
            (symbol, market_cap)
            for symbol, market_cap in sorted(cap_map.items(), key=lambda x: x[1])
            if is_tradable_name(name_map.get(symbol.zfill(6), ""))
        ][:TOP_N]
        selected = [symbol for symbol, _ in ranked]
        next_members_map[pd.Timestamp(dt)] = selected
        for rank, (symbol, market_cap) in enumerate(ranked, start=1):
            members_rows.append(
                {
                    "rebalance_date": pd.Timestamp(dt),
                    "rank": rank,
                    "symbol": symbol,
                    "name": name_map.get(symbol.zfill(6), ""),
                    "market_cap": float(market_cap),
                }
            )
        if prev_members is not None:
            prev_set = set(prev_members)
            curr_set = set(selected)
            entry_count = len(curr_set - prev_set)
            exit_count = len(prev_set - curr_set)
            turnover_rows.append(
                {
                    "rebalance_date": pd.Timestamp(dt),
                    "entry_count": entry_count,
                    "exit_count": exit_count,
                    "turnover_frac_one_side": entry_count / TOP_N,
                    "two_side_cost_rate": 2 * 0.003 * (entry_count / TOP_N),
                }
            )
        prev_members = selected

    index_rows: list[dict[str, object]] = []
    current_members: list[str] = []
    current_level = 1000.0
    for i, dt in enumerate(trading_dates):
        if i == 0:
            index_rows.append(
                {
                    "date": dt,
                    "close": current_level,
                    "daily_return": np.nan,
                    "holding_count": 0,
                    "holding_effective": False,
                }
            )
            if dt in rebalance_set:
                current_members = next_members_map.get(pd.Timestamp(dt), [])
            continue

        if trading_dates[i - 1] in rebalance_set:
            current_members = next_members_map.get(pd.Timestamp(trading_dates[i - 1]), [])

        if current_members:
            day_ret = returns_df.loc[dt, current_members].dropna()
            portfolio_ret = float(day_ret.mean()) if len(day_ret) else 0.0
        else:
            portfolio_ret = 0.0
        current_level *= 1.0 + portfolio_ret
        index_rows.append(
            {
                "date": dt,
                "close": current_level,
                "daily_return": portfolio_ret,
                "holding_count": len(current_members),
                "holding_effective": bool(current_members),
            }
        )

    index_df = pd.DataFrame(index_rows)
    members_df = pd.DataFrame(members_rows)
    turnover_df = pd.DataFrame(turnover_rows)
    meta = {
        "index_code": "TOP100_BIWEEKLY_THURSDAY_PROXY",
        "source_used": "local_cache_proxy",
        "method_note": (
            "Local cache reconstruction using raw close data and share-change data. "
            "This practical version anchors biweekly rebalances to Thursday signal dates."
        ),
        "core_params": {
            "top_n": TOP_N,
            "exclude_current_st": True,
            "rebalance_frequency": "biweekly",
            "rebalance_weekday_anchor": REBALANCE_WEEKDAY,
            "lookback": LOOKBACK,
            "hedge_column": HEDGE_COLUMN,
        },
        "start_date": str(pd.Timestamp(trading_dates.min()).date()),
        "end_date": str(pd.Timestamp(trading_dates.max()).date()),
        "rebalance_dates_count": int(len(rebalance_dates)),
    }
    return index_df, members_df, turnover_df, meta


def ensure_strategy_files(args: argparse.Namespace, paths: dict[str, Path]) -> None:
    if args.index_csv.exists() and args.costed_nav_csv.exists():
        return
    if not args.rebuild_index_if_missing:
        missing = []
        if not args.index_csv.exists():
            missing.append(str(args.index_csv))
        if not args.costed_nav_csv.exists():
            missing.append(str(args.costed_nav_csv))
        raise FileNotFoundError("Missing required strategy files: " + ", ".join(missing))

    panel = pd.read_csv(args.panel_path, usecols=["date"])
    panel["date"] = pd.to_datetime(panel["date"])
    trading_dates = pd.DatetimeIndex(panel["date"].drop_duplicates().sort_values())

    index_df, members_df, turnover_df, meta = build_local_proxy_bundle(args, trading_dates)
    args.index_csv.parent.mkdir(parents=True, exist_ok=True)
    index_df.to_csv(args.index_csv, index=False, encoding="utf-8")
    members_df.to_csv(paths["proxy_members"], index=False, encoding="utf-8")
    paths["proxy_meta"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    close_df = load_close_df(args.panel_path, args.index_csv)
    gross = run_signal(close_df)
    turnover_df = turnover_df.copy()
    turnover_df["rebalance_date"] = pd.to_datetime(turnover_df["rebalance_date"])
    net = freq_mod.cost_mod.apply_cost_model(gross, turnover_df)
    net.to_csv(args.costed_nav_csv, index_label="date", encoding="utf-8")


def load_close_df(panel_path: Path, index_csv: Path) -> pd.DataFrame:
    panel = pd.read_csv(panel_path, usecols=["date", HEDGE_COLUMN])
    panel["date"] = pd.to_datetime(panel["date"])
    hedge = panel.set_index("date")[HEDGE_COLUMN].rename("hedge").astype(float)

    microcap = pd.read_csv(index_csv, usecols=["date", "close"])
    microcap["date"] = pd.to_datetime(microcap["date"])
    microcap = microcap.set_index("date")["close"].rename("microcap").astype(float)

    close_df = pd.concat([microcap, hedge], axis=1).sort_index().dropna()
    if len(close_df) < LOOKBACK + 3:
        raise ValueError(f"Not enough aligned rows for lookback={LOOKBACK}: got {len(close_df)}.")
    return close_df


def run_signal(close_df: pd.DataFrame) -> pd.DataFrame:
    result = hedge_mod.run_backtest(
        close_df=close_df,
        signal_model="momentum",
        lookback=LOOKBACK,
        bias_n=hedge_mod.DEFAULT_BIAS_N,
        bias_mom_day=hedge_mod.DEFAULT_BIAS_MOM_DAY,
        futures_drag=FUTURES_DRAG * FIXED_HEDGE_RATIO,
        require_positive_microcap_mom=REQUIRE_POSITIVE_MICROCAP_MOM,
        r2_window=hedge_mod.DEFAULT_R2_WINDOW,
        r2_threshold=0.0,
        vol_scale_enabled=False,
        target_vol=hedge_mod.DEFAULT_TARGET_VOL,
        vol_window=hedge_mod.DEFAULT_VOL_WINDOW,
        max_lev=hedge_mod.DEFAULT_MAX_LEV,
        min_lev=hedge_mod.DEFAULT_MIN_LEV,
        scale_threshold=hedge_mod.DEFAULT_SCALE_THRESHOLD,
    )
    result.index = pd.to_datetime(result.index)
    return result


def load_name_map() -> dict[str, str]:
    frame = pd.read_csv(freq_mod.ACTIVE_UNIVERSE, dtype=str)
    return dict(zip(frame["code"].str.zfill(6), frame["name"]))


def load_member_snapshot(
    snapshot_dates: list[pd.Timestamp],
    max_workers: int,
) -> dict[pd.Timestamp, pd.DataFrame]:
    if not snapshot_dates:
        return {}
    symbols = freq_mod.load_universe()
    snapshot_index = pd.DatetimeIndex(sorted(set(pd.Timestamp(dt) for dt in snapshot_dates)))
    _, caps_by_date = freq_mod.load_cache_panels(
        symbols=symbols,
        trading_dates=snapshot_index,
        cap_dates=snapshot_index,
        max_workers=max_workers,
    )
    name_map = load_name_map()

    snapshots: dict[pd.Timestamp, pd.DataFrame] = {}
    for dt in snapshot_index:
        cap_map = caps_by_date.get(pd.Timestamp(dt), {})
        ranked = [
            (symbol, market_cap)
            for symbol, market_cap in sorted(cap_map.items(), key=lambda x: x[1])
            if is_tradable_name(name_map.get(symbol.zfill(6), ""))
        ][:TOP_N]
        rows = []
        for rank, (symbol, market_cap) in enumerate(ranked, start=1):
            rows.append(
                {
                    "rebalance_date": pd.Timestamp(dt),
                    "rank": rank,
                    "symbol": symbol,
                    "name": name_map.get(symbol.zfill(6), ""),
                    "market_cap": float(market_cap),
                    "target_weight": 1.0 / TOP_N,
                }
            )
        snapshots[pd.Timestamp(dt)] = pd.DataFrame(rows)
    return snapshots


def build_change_table(prev_df: pd.DataFrame | None, curr_df: pd.DataFrame) -> pd.DataFrame:
    prev_df = prev_df.copy() if prev_df is not None else pd.DataFrame(columns=["symbol", "rank", "name"])
    curr_df = curr_df.copy()

    prev_rank = dict(zip(prev_df["symbol"], prev_df["rank"]))
    curr_rank = dict(zip(curr_df["symbol"], curr_df["rank"]))
    name_map = dict(zip(curr_df["symbol"], curr_df.get("name", "")))
    name_map.update(dict(zip(prev_df["symbol"], prev_df.get("name", ""))))

    rows: list[dict[str, object]] = []
    all_symbols = sorted(set(prev_rank) | set(curr_rank))
    for symbol in all_symbols:
        in_prev = symbol in prev_rank
        in_curr = symbol in curr_rank
        if in_prev and not in_curr:
            action = "exit"
        elif in_curr and not in_prev:
            action = "enter"
        else:
            continue
        rows.append(
            {
                "action": action,
                "symbol": symbol,
                "name": name_map.get(symbol, ""),
                "prev_rank": prev_rank.get(symbol),
                "new_rank": curr_rank.get(symbol),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["action", "symbol", "name", "prev_rank", "new_rank"])
    out = pd.DataFrame(rows)
    action_order = {"enter": 0, "exit": 1}
    out["action_order"] = out["action"].map(action_order)
    out = out.sort_values(["action_order", "new_rank", "prev_rank", "symbol"]).drop(columns="action_order")
    return out.reset_index(drop=True)


def locate_rebalance_dates(
    trading_dates: pd.DatetimeIndex,
) -> tuple[pd.Timestamp, pd.Timestamp | None, pd.Timestamp | None, pd.Timestamp | None]:
    rebalance_dates = build_biweekly_rebalance_dates(trading_dates)
    last_trade_date = pd.Timestamp(trading_dates[-1])
    available = [pd.Timestamp(dt) for dt in rebalance_dates if pd.Timestamp(dt) <= last_trade_date]
    if not available:
        raise ValueError("No rebalance date found up to the latest trade date.")
    latest_rebalance = available[-1]
    prev_rebalance = available[-2] if len(available) >= 2 else None

    if latest_rebalance == last_trade_date and prev_rebalance is not None:
        effective_rebalance = prev_rebalance
    else:
        effective_rebalance = latest_rebalance

    next_rebalance = None
    future = [pd.Timestamp(dt) for dt in rebalance_dates if pd.Timestamp(dt) > last_trade_date]
    if future:
        next_rebalance = future[0]
    return latest_rebalance, prev_rebalance, next_rebalance, effective_rebalance


def get_next_trade_date(trading_dates: pd.DatetimeIndex, current_date: pd.Timestamp) -> pd.Timestamp | None:
    future_dates = trading_dates[trading_dates > pd.Timestamp(current_date)]
    if len(future_dates) == 0:
        return None
    return pd.Timestamp(future_dates[0])


def add_capital_columns(members_df: pd.DataFrame, capital: float | None) -> pd.DataFrame:
    out = members_df.copy()
    if capital is not None and not out.empty:
        out["target_notional"] = capital * out["target_weight"]
    return out


def load_cached_static_context(
    paths: dict[str, Path],
    latest_rebalance: pd.Timestamp,
    prev_rebalance: pd.Timestamp | None,
    effective_rebalance: pd.Timestamp | None,
    rebalance_effective_date: pd.Timestamp | None,
    capital: float | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
    meta_path = paths["cache_static_meta"]
    target_path = paths["cache_static_target"]
    effective_path = paths["cache_static_effective"]
    changes_path = paths["cache_static_changes"]
    if not (meta_path.exists() and target_path.exists() and effective_path.exists() and changes_path.exists()):
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        expected = {
            "latest_rebalance": str(pd.Timestamp(latest_rebalance).date()),
            "prev_rebalance": None if prev_rebalance is None else str(pd.Timestamp(prev_rebalance).date()),
            "effective_rebalance": None if effective_rebalance is None else str(pd.Timestamp(effective_rebalance).date()),
            "rebalance_effective_date": None if rebalance_effective_date is None else str(pd.Timestamp(rebalance_effective_date).date()),
        }
        if any(meta.get(key) != value for key, value in expected.items()):
            return None
        target_members = pd.read_csv(target_path, dtype={"symbol": str})
        effective_members = pd.read_csv(effective_path, dtype={"symbol": str})
        changes_df = pd.read_csv(changes_path, dtype={"symbol": str})
        target_members = add_capital_columns(target_members, capital)
        return target_members, effective_members, changes_df
    except Exception:
        return None


def save_static_context_cache(
    paths: dict[str, Path],
    latest_rebalance: pd.Timestamp,
    prev_rebalance: pd.Timestamp | None,
    effective_rebalance: pd.Timestamp | None,
    rebalance_effective_date: pd.Timestamp | None,
    target_members: pd.DataFrame,
    effective_members: pd.DataFrame,
    changes_df: pd.DataFrame,
) -> None:
    REALTIME_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "latest_rebalance": str(pd.Timestamp(latest_rebalance).date()),
        "prev_rebalance": None if prev_rebalance is None else str(pd.Timestamp(prev_rebalance).date()),
        "effective_rebalance": None if effective_rebalance is None else str(pd.Timestamp(effective_rebalance).date()),
        "rebalance_effective_date": None if rebalance_effective_date is None else str(pd.Timestamp(rebalance_effective_date).date()),
    }
    paths["cache_static_meta"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    target_members.to_csv(paths["cache_static_target"], index=False, encoding="utf-8")
    effective_members.to_csv(paths["cache_static_effective"], index=False, encoding="utf-8")
    changes_df.to_csv(paths["cache_static_changes"], index=False, encoding="utf-8")


def compute_trade_state(current_holding: str, next_holding: str) -> str:
    if current_holding == next_holding:
        return "hold"
    if current_holding == "cash" and next_holding != "cash":
        return "open"
    if current_holding != "cash" and next_holding == "cash":
        return "close"
    return "switch"


def classify_tail_jitter_risk(momentum_gap: float) -> tuple[str, str]:
    abs_gap = abs(float(momentum_gap))
    if abs_gap < TAIL_JITTER_WARNING_GAP:
        return "warning", "gap very close to zero; confirm again near the close"
    if abs_gap < TAIL_JITTER_CAUTION_GAP:
        return "caution", "gap is narrow; close-time recheck is recommended"
    return "normal", ""


def enrich_signal_frame(signal_df: pd.DataFrame, result: pd.DataFrame) -> pd.DataFrame:
    out = signal_df.copy()
    last_row = result.iloc[-1]
    current_holding = str(last_row["holding"])
    next_holding = str(last_row["next_holding"])
    out["current_holding"] = current_holding
    out["trade_state"] = compute_trade_state(current_holding, next_holding)
    return out


def build_summary(
    result: pd.DataFrame,
    latest_signal: pd.DataFrame,
    latest_rebalance: pd.Timestamp,
    prev_rebalance: pd.Timestamp | None,
    next_rebalance: pd.Timestamp | None,
    members_df: pd.DataFrame,
    changes_df: pd.DataFrame,
    capital: float | None,
) -> dict[str, object]:
    latest_row = latest_signal.iloc[0]
    last_result_row = result.iloc[-1]
    current_holding = last_result_row["holding"]
    next_holding = last_result_row["next_holding"]
    active_next = next_holding != "cash"
    trade_state = compute_trade_state(str(current_holding), str(next_holding))
    hedge_notional = capital * FIXED_HEDGE_RATIO if (capital is not None and active_next) else 0.0
    return {
        "strategy": DEFAULT_OUTPUT_PREFIX,
        "core_params": {
            "top_n": TOP_N,
            "exclude_current_st": True,
            "rebalance_schedule": "biweekly",
            "rebalance_weekday_anchor": REBALANCE_WEEKDAY,
            "lookback": LOOKBACK,
            "signal_model": "relative_momentum",
            "hedge_column": HEDGE_COLUMN,
            "fixed_hedge_ratio": FIXED_HEDGE_RATIO,
            "futures_drag_per_day": FUTURES_DRAG,
        },
        "latest_trade_date": str(result.index[-1].date()),
        "latest_rebalance_date": str(latest_rebalance.date()),
        "previous_rebalance_date": None if prev_rebalance is None else str(prev_rebalance.date()),
        "next_rebalance_date": None if next_rebalance is None else str(next_rebalance.date()),
        "latest_signal": {
            "signal_label": latest_row["signal_label"],
            "current_holding": current_holding,
            "next_holding": next_holding,
            "trade_state": trade_state,
            "microcap_mom": float(latest_row["microcap_mom"]),
            "hedge_mom": float(latest_row["hedge_mom"]),
            "momentum_gap": float(latest_row["momentum_gap"]),
            "microcap_close": float(latest_row["microcap_close"]),
            "hedge_close": float(latest_row["hedge_close"]),
        },
        "target_members": {
            "count": int(len(members_df)),
            "enter_count": int((changes_df["action"] == "enter").sum()) if len(changes_df) else 0,
            "exit_count": int((changes_df["action"] == "exit").sum()) if len(changes_df) else 0,
            "equal_weight": 1.0 / TOP_N,
        },
        "capital_plan": {
            "gross_stock_capital": capital,
            "per_stock_target_notional": None if capital is None else capital / TOP_N,
            "hedge_notional": hedge_notional,
        },
    }


def build_base_context(args: argparse.Namespace, include_members: bool = True) -> dict[str, object]:
    paths = build_output_paths(args.output_prefix)
    ensure_strategy_files(args, paths)

    close_df = load_close_df(args.panel_path, args.index_csv)
    result = run_signal(close_df)
    latest_signal = enrich_signal_frame(hedge_mod.build_latest_signal(result), result)

    latest_rebalance, prev_rebalance, next_rebalance, effective_rebalance = locate_rebalance_dates(close_df.index)
    rebalance_effective_date = get_next_trade_date(close_df.index, latest_rebalance)
    target_members = pd.DataFrame()
    effective_members = pd.DataFrame()
    changes_df = pd.DataFrame(columns=["action", "symbol", "name", "prev_rank", "new_rank"])

    if include_members:
        cached_static = load_cached_static_context(
            paths=paths,
            latest_rebalance=latest_rebalance,
            prev_rebalance=prev_rebalance,
            effective_rebalance=effective_rebalance,
            rebalance_effective_date=rebalance_effective_date,
            capital=args.capital,
        )
        if cached_static is None:
            snapshot_dates = [dt for dt in [latest_rebalance, prev_rebalance, effective_rebalance] if dt is not None]
            snapshots = load_member_snapshot(snapshot_dates=snapshot_dates, max_workers=args.max_workers)
            target_members = snapshots[pd.Timestamp(latest_rebalance)].copy()
            prev_members = snapshots.get(pd.Timestamp(prev_rebalance)) if prev_rebalance is not None else None
            effective_members = snapshots.get(pd.Timestamp(effective_rebalance)) if effective_rebalance is not None else target_members.copy()
            target_members = add_capital_columns(target_members, capital=args.capital)
            if not target_members.empty:
                target_members["signal_date"] = pd.Timestamp(latest_rebalance).date()
                target_members["effective_date"] = None if rebalance_effective_date is None else pd.Timestamp(rebalance_effective_date).date()
            changes_df = build_change_table(prev_members, target_members)
            if not changes_df.empty:
                changes_df["signal_date"] = pd.Timestamp(latest_rebalance).date()
                changes_df["effective_date"] = None if rebalance_effective_date is None else pd.Timestamp(rebalance_effective_date).date()
            save_static_context_cache(
                paths=paths,
                latest_rebalance=latest_rebalance,
                prev_rebalance=prev_rebalance,
                effective_rebalance=effective_rebalance,
                rebalance_effective_date=rebalance_effective_date,
                target_members=target_members.drop(columns=["target_notional"], errors="ignore"),
                effective_members=effective_members,
                changes_df=changes_df,
            )
        else:
            target_members, effective_members, changes_df = cached_static

    summary = build_summary(
        result=result,
        latest_signal=latest_signal,
        latest_rebalance=latest_rebalance,
        prev_rebalance=prev_rebalance,
        next_rebalance=next_rebalance,
        members_df=target_members,
        changes_df=changes_df,
        capital=args.capital,
    )
    return {
        "include_members": include_members,
        "paths": paths,
        "close_df": close_df,
        "result": result,
        "latest_signal": latest_signal,
        "latest_rebalance": latest_rebalance,
        "rebalance_effective_date": rebalance_effective_date,
        "prev_rebalance": prev_rebalance,
        "next_rebalance": next_rebalance,
        "effective_rebalance": effective_rebalance,
        "target_members": target_members,
        "effective_members": effective_members,
        "changes_df": changes_df,
        "summary": summary,
    }


def save_base_outputs(context: dict[str, object]) -> None:
    paths = context["paths"]
    result = context["result"]
    latest_signal = context["latest_signal"]
    target_members = context["target_members"]
    changes_df = context["changes_df"]
    summary = context["summary"]
    include_members = bool(context.get("include_members", True))

    result.to_csv(paths["nav"], index_label="date", encoding="utf-8")
    latest_signal.to_csv(paths["signal"], index=False, encoding="utf-8")
    if include_members:
        target_members.to_csv(paths["members"], index=False, encoding="utf-8")
        changes_df.to_csv(paths["changes"], index=False, encoding="utf-8")
        paths["summary"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def print_console_summary(summary: dict[str, object]) -> None:
    latest_signal = summary["latest_signal"]
    capital_plan = summary["capital_plan"]
    target_members = summary["target_members"]
    print(f"最新交易日: {summary['latest_trade_date']}")
    print(f"最新调仓日: {summary['latest_rebalance_date']}")
    print(f"下一调仓日: {summary['next_rebalance_date']}")
    print(f"当前信号: {latest_signal['signal_label']} -> 下期持仓 {latest_signal['next_holding']}")
    print(f"交易动作: {latest_signal['trade_state']}")
    print(
        "16日动量: microcap={:.4%}, hedge={:.4%}, gap={:.4%}".format(
            latest_signal["microcap_mom"],
            latest_signal["hedge_mom"],
            latest_signal["momentum_gap"],
        )
    )
    print(
        f"目标成分股: {target_members['count']} 只, 本次进入 {target_members['enter_count']} 只, "
        f"剔除 {target_members['exit_count']} 只"
    )
    if capital_plan["gross_stock_capital"] is not None:
        print(
            f"股票资金: {capital_plan['gross_stock_capital']:.2f}, "
            f"单票目标资金: {capital_plan['per_stock_target_notional']:.2f}, "
            f"对冲名义: {capital_plan['hedge_notional']:.2f}"
        )


def _parse_cn_num(text: str) -> int | float | None:
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text in CN_NUM:
        return CN_NUM[text]
    if "十" in text:
        parts = text.split("十")
        tens = CN_NUM.get(parts[0], 1) if parts[0] else 1
        ones = CN_NUM.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    return None


def _strip_query_prefix(text: str) -> str:
    out = re.sub(r"^(查询|看看|看下|看一下|给我看一下|给我看看)", "", text.strip())
    out = re.sub(r"^(表现|净值曲线|收益|回撤|年化|夏普)", "", out)
    out = re.sub(r"^[:：\s]+", "", out)
    return out.strip()


def parse_date_range(text: str, now: pd.Timestamp | None = None) -> tuple[pd.Timestamp | None, pd.Timestamp | None, str]:
    now = (now or pd.Timestamp.now()).normalize()
    raw = text.strip()
    text = re.sub(r"\s+", "", raw)
    text = text.replace("从", "")
    text = _strip_query_prefix(text)
    if not text or text in {"全部", "全样本", "历史全部", "历史", "全周期"}:
        return None, None, "全样本"

    m = re.search(
        r"(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})" + DAY_SUFFIX +
        r"[到至—\-~]+" +
        r"(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})" + DAY_SUFFIX,
        text,
    )
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
        end = pd.Timestamp(f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}")
        return start, end, f"{start:%Y-%m-%d} to {end:%Y-%m-%d}"

    m = re.search(r"(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})" + DAY_SUFFIX + r"至今", text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
        return start, now, f"{start:%Y-%m-%d} to now"

    m = re.search(r"(\d{1,2})[-月/.](\d{1,2})" + DAY_SUFFIX + r"至今", text)
    if m:
        year = now.year
        start = pd.Timestamp(f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}")
        if start > now:
            start = start.replace(year=year - 1)
        return start, now, f"{start:%Y-%m-%d} to now"

    m = re.search(r"(\d{4})[-年/.]?(\d{1,2})[-月]?\s*至今", text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-01")
        return start, now, f"{start:%Y-%m} to now"

    m = re.search(r"(\d{4})\s*年?\s*至今", text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-01-01")
        return start, now, f"{start:%Y} to now"

    m = re.search(r"(\d{4})[-年/.](\d{1,2})[-月]?[到至—\-~]+(\d{4})[-年/.](\d{1,2})", text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-01")
        end = pd.Timestamp(f"{m.group(3)}-{int(m.group(4)):02d}-01") + pd.offsets.MonthEnd(0)
        return start, end, f"{start:%Y-%m} to {end:%Y-%m}"

    m = re.search(r"(\d{4})\s*年?\s*[到至—\-~]+\s*(\d{4})\s*年?", text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-01-01")
        end = pd.Timestamp(f"{m.group(2)}-12-31")
        return start, end, f"{m.group(1)} to {m.group(2)}"

    m = re.search(r"(?:最近|过去|近)\s*([一二两三四五六七八九十\d半]+)\s*个?\s*年", text)
    if m:
        n = _parse_cn_num(m.group(1))
        if n is not None:
            if isinstance(n, float):
                start = now - pd.DateOffset(months=int(n * 12))
            else:
                start = now - pd.DateOffset(years=int(n))
            return start, now, f"last_{m.group(1)}_years"

    m = re.search(r"(?:最近|过去|近)\s*([一二两三四五六七八九十\d半]+)\s*个?\s*月", text)
    if m:
        n = _parse_cn_num(m.group(1))
        if n is not None:
            months = int(n if n >= 1 else 1)
            start = now - pd.DateOffset(months=months)
            return start, now, f"last_{m.group(1)}_months"

    if "最近几年" in text or "近几年" in text or "过去几年" in text:
        start = now - pd.DateOffset(years=3)
        return start, now, "last_3_years_default"

    if "今年" in text:
        start = pd.Timestamp(f"{now.year}-01-01")
        return start, now, f"{now.year}"

    if "去年" in text:
        year = now.year - 1
        start = pd.Timestamp(f"{year}-01-01")
        end = pd.Timestamp(f"{year}-12-31")
        return start, end, f"{year}"

    if "前年" in text:
        year = now.year - 2
        start = pd.Timestamp(f"{year}-01-01")
        end = pd.Timestamp(f"{year}-12-31")
        return start, end, f"{year}"

    m = re.search(r"(\d{4})[-年/.](\d{1,2})\s*月?份?", text)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        if 1 <= month <= 12:
            start = pd.Timestamp(f"{year}-{month:02d}-01")
            end = start + pd.offsets.MonthEnd(0)
            return start, end, f"{year}-{month:02d}"

    m = re.search(r"(\d{4})\s*年?\s*全?年?", text)
    if m:
        year = int(m.group(1))
        if 2000 <= year <= 2099:
            start = pd.Timestamp(f"{year}-01-01")
            end = pd.Timestamp(f"{year}-12-31")
            return start, end, f"{year}"

    return None, None, "全样本"


def load_performance_source(costed_nav_csv: Path, fallback_result: pd.DataFrame) -> tuple[pd.DataFrame, str, str, str]:
    if costed_nav_csv.exists():
        perf = pd.read_csv(costed_nav_csv)
        perf["date"] = pd.to_datetime(perf["date"])
        perf = perf.set_index("date").sort_index()
        if "return_net" in perf.columns and "nav_net" in perf.columns:
            return perf, "return_net", "nav_net", "costed"
        return perf, "return", "nav", "gross"

    perf = fallback_result.copy()
    return perf, "return", "nav", "gross_fallback"


def calc_max_drawdown_from_returns(returns: pd.Series) -> float:
    nav = (1.0 + returns.fillna(0.0)).cumprod()
    drawdown = nav / nav.cummax() - 1.0
    return float(drawdown.min())


def build_performance_outputs(
    perf_df: pd.DataFrame,
    ret_col: str,
    nav_col: str,
    source_label: str,
    query_text: str,
    paths: dict[str, Path],
) -> dict[str, object]:
    start_date, end_date, period_label = parse_date_range(query_text)
    data = perf_df.copy()
    if start_date is None:
        start_date = pd.Timestamp(data.index.min())
    if end_date is None:
        end_date = pd.Timestamp(data.index.max())

    data = data.loc[(data.index >= start_date) & (data.index <= end_date)].copy()
    if data.empty:
        raise ValueError(f"在 {start_date:%Y-%m-%d} 到 {end_date:%Y-%m-%d} 之间没有表现数据。")

    returns = data[ret_col].fillna(0.0)
    metrics = hedge_mod.calc_metrics(returns)
    rebased_nav = (1.0 + returns).cumprod()
    data["nav_rebased"] = rebased_nav

    yearly_rows: list[dict[str, object]] = []
    for year, part in data.groupby(data.index.year):
        part_returns = part[ret_col].fillna(0.0)
        part_metrics = hedge_mod.calc_metrics(part_returns)
        yearly_rows.append(
            {
                "year": str(year),
                "start_date": str(part.index.min().date()),
                "end_date": str(part.index.max().date()),
                "days": int(len(part)),
                "return_pct": float((1.0 + part_returns).prod() - 1.0) * 100.0,
                "max_drawdown_pct": calc_max_drawdown_from_returns(part_returns) * 100.0,
                "sharpe": float(part_metrics.sharpe),
                "annual_pct": float(part_metrics.annual) * 100.0,
            }
        )
    yearly_df = pd.DataFrame(yearly_rows)

    summary_df = pd.DataFrame(
        [
            {
                "period_label": period_label,
                "source": source_label,
                "start_date": str(data.index.min().date()),
                "end_date": str(data.index.max().date()),
                "days": int(len(data)),
                "final_nav": float(rebased_nav.iloc[-1]),
                "total_return_pct": float(rebased_nav.iloc[-1] - 1.0) * 100.0,
                "annual_pct": float(metrics.annual) * 100.0,
                "max_drawdown_pct": float(metrics.max_dd) * 100.0,
                "sharpe": float(metrics.sharpe),
                "vol_pct": float(metrics.vol) * 100.0,
            }
        ]
    )

    data.reset_index().to_csv(paths["performance_nav"], index=False, encoding="utf-8")
    summary_df.to_csv(paths["performance_summary"], index=False, encoding="utf-8")
    yearly_df.to_csv(paths["performance_yearly"], index=False, encoding="utf-8")

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(data.index, data["nav_rebased"], linewidth=2.0, color="#1f4e79")
    title_label = period_label if str(period_label).isascii() else f"{data.index.min():%Y-%m-%d} to {data.index.max():%Y-%m-%d}"
    ax.set_title(f"Top100 Microcap Mom16 Biweekly ({title_label})")
    ax.set_ylabel("Rebased NAV")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(paths["performance_chart"], dpi=160)
    plt.close(fig)

    payload = {
        "period_label": period_label,
        "source": source_label,
        "query_text": query_text,
        "start_date": str(data.index.min().date()),
        "end_date": str(data.index.max().date()),
        "summary": summary_df.iloc[0].to_dict(),
        "yearly": yearly_rows,
        "files": {
            "summary_csv": str(paths["performance_summary"]),
            "yearly_csv": str(paths["performance_yearly"]),
            "nav_csv": str(paths["performance_nav"]),
            "chart_png": str(paths["performance_chart"]),
        },
    }
    paths["performance_json"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def normalize_symbol_code(series: pd.Series) -> pd.Series:
    return series.astype(str).str.extract(r"(\d{6})", expand=False).fillna("")


def get_realtime_cache_file(name: str) -> Path:
    REALTIME_DIR.mkdir(parents=True, exist_ok=True)
    return REALTIME_DIR / name


def load_or_refresh_stock_spot(cache_seconds: int) -> pd.DataFrame:
    cache_file = get_realtime_cache_file("stock_spot_latest.csv")
    now = time.time()
    if cache_file.exists() and now - cache_file.stat().st_mtime <= cache_seconds:
        return pd.read_csv(cache_file, dtype={"代码": str})

    last_error: Exception | None = None
    for fetcher in (ak.stock_zh_a_spot_em, ak.stock_zh_a_spot):
        try:
            spot = fetcher()
            spot.to_csv(cache_file, index=False, encoding="utf-8")
            return spot
        except Exception as exc:
            last_error = exc

    if cache_file.exists():
        return pd.read_csv(cache_file, dtype={"代码": str})
    raise RuntimeError(f"实时股票行情抓取失败: {last_error}") from last_error


def load_or_refresh_index_spot(cache_seconds: int) -> pd.DataFrame:
    cache_file = get_realtime_cache_file("index_spot_latest.csv")
    now = time.time()
    if cache_file.exists() and now - cache_file.stat().st_mtime <= cache_seconds:
        return pd.read_csv(cache_file, dtype={"代码": str})

    try:
        spot = ak.stock_zh_index_spot_em()
        spot.to_csv(cache_file, index=False, encoding="utf-8")
        return spot
    except Exception as exc:
        if cache_file.exists():
            return pd.read_csv(cache_file, dtype={"代码": str})
        raise RuntimeError(f"实时指数行情抓取失败: {exc}") from exc


def load_or_refresh_latest_shares(cache_seconds: int = 86400) -> pd.DataFrame:
    cache_file = get_realtime_cache_file("latest_total_shares.csv")
    now = time.time()
    if cache_file.exists() and now - cache_file.stat().st_mtime <= cache_seconds:
        return pd.read_csv(cache_file, dtype={"code": str, "symbol": str})

    universe = pd.read_csv(freq_mod.ACTIVE_UNIVERSE, dtype=str)
    st_codes = set(pd.read_csv(freq_mod.CURRENT_ST, dtype=str)["code"].dropna().astype(str))
    universe = universe[~universe["code"].isin(st_codes)].copy()
    universe = universe[universe["name"].map(is_tradable_name)].copy()

    rows: list[dict[str, object]] = []
    for row in universe.itertuples(index=False):
        code = str(row.code).zfill(6)
        share_path = freq_mod.SHARE_DIR / f"{code}.csv"
        if not share_path.exists():
            continue
        try:
            share_df = pd.read_csv(share_path, usecols=["change_date", "total_shares_10k"])
            share_df = share_df.dropna(subset=["total_shares_10k"])
            if share_df.empty:
                continue
            share_df["change_date"] = pd.to_datetime(share_df["change_date"])
            share_df["total_shares_10k"] = pd.to_numeric(share_df["total_shares_10k"], errors="coerce")
            share_df = share_df.dropna(subset=["total_shares_10k"]).sort_values("change_date")
            last_row = share_df.iloc[-1]
            rows.append(
                {
                    "symbol": str(row.symbol),
                    "code": code,
                    "name": str(row.name),
                    "change_date": str(pd.Timestamp(last_row["change_date"]).date()),
                    "total_shares": float(last_row["total_shares_10k"]) * 10000.0,
                }
            )
        except Exception:
            continue

    latest_shares = pd.DataFrame(rows)
    latest_shares.to_csv(cache_file, index=False, encoding="utf-8")
    return latest_shares


def build_realtime_quote_map(cache_seconds: int) -> tuple[pd.DataFrame, str]:
    stock_spot = load_or_refresh_stock_spot(cache_seconds)
    stock_spot["code"] = normalize_symbol_code(stock_spot["代码"])
    stock_spot = stock_spot[stock_spot["code"].ne("")].copy()
    for col in ["最新价", "昨收", "今开", "最高", "最低", "成交额"]:
        if col in stock_spot.columns:
            stock_spot[col] = pd.to_numeric(stock_spot[col], errors="coerce")
    stock_spot["rt_price"] = stock_spot["最新价"]
    stock_spot.loc[stock_spot["rt_price"].isna() | (stock_spot["rt_price"] <= 0), "rt_price"] = stock_spot["昨收"]
    source = "live_or_prev_close_fallback"
    return stock_spot, source


def load_latest_close_map(symbols: list[str], as_of_date: pd.Timestamp) -> dict[str, float]:
    out: dict[str, float] = {}
    for symbol in symbols:
        path = freq_mod.PRICE_DIR / f"{symbol}.csv"
        if not path.exists():
            continue
        try:
            price = pd.read_csv(path, usecols=["date", "close_raw"])
            price["date"] = pd.to_datetime(price["date"])
            price["close_raw"] = pd.to_numeric(price["close_raw"], errors="coerce")
            price = price.dropna(subset=["close_raw"])
            price = price.loc[price["date"] <= as_of_date].sort_values("date")
            if price.empty:
                continue
            out[symbol] = float(price.iloc[-1]["close_raw"])
        except Exception:
            continue
    return out


def build_realtime_target_members(context: dict[str, object], cache_seconds: int, capital: float | None) -> tuple[pd.DataFrame, str]:
    shares_df = load_or_refresh_latest_shares()
    quotes_df, quote_source = build_realtime_quote_map(cache_seconds)
    merged = shares_df.merge(quotes_df[["code", "名称", "rt_price", "昨收", "今开", "最高", "最低", "成交额"]], on="code", how="inner")
    merged = merged[merged["name"].map(is_tradable_name)].copy()
    merged["market_cap"] = merged["rt_price"] * merged["total_shares"]
    merged = merged.dropna(subset=["market_cap"]).sort_values("market_cap").head(TOP_N).copy()
    merged["rank"] = np.arange(1, len(merged) + 1)
    merged["target_weight"] = 1.0 / TOP_N
    merged["symbol"] = merged["code"]
    merged["name"] = merged["名称"].fillna(merged["name"])
    cols = ["rank", "symbol", "name", "rt_price", "market_cap", "target_weight", "change_date", "今开", "最高", "最低", "成交额"]
    out = merged[cols].reset_index(drop=True)
    if capital is not None and not out.empty:
        out["target_notional"] = capital * out["target_weight"]
    return out, quote_source


def build_realtime_signal(context: dict[str, object], cache_seconds: int) -> tuple[pd.DataFrame, dict[str, object]]:
    close_df = context["close_df"].copy()
    effective_members = context["effective_members"].copy()
    latest_trade_date = pd.Timestamp(close_df.index[-1])
    member_symbols = effective_members["symbol"].astype(str).tolist()
    last_close_map = load_latest_close_map(member_symbols, as_of_date=latest_trade_date)

    quotes_df, quote_source = build_realtime_quote_map(cache_seconds)
    quotes_df = quotes_df.set_index("code")

    member_returns: list[float] = []
    available_rows = 0
    for symbol in member_symbols:
        last_close = last_close_map.get(symbol)
        if last_close is None or last_close <= 0:
            continue
        if symbol not in quotes_df.index:
            continue
        rt_price = pd.to_numeric(quotes_df.at[symbol, "rt_price"], errors="coerce")
        if pd.isna(rt_price) or rt_price <= 0:
            continue
        member_returns.append(float(rt_price / last_close - 1.0))
        available_rows += 1

    if not member_returns:
        raise ValueError("无法计算实时信号: 当前成分股没有可用实时价格。")

    last_microcap_close = float(close_df["microcap"].iloc[-1])
    microcap_rt_close = last_microcap_close * (1.0 + float(np.mean(member_returns)))

    index_spot = load_or_refresh_index_spot(cache_seconds)
    index_spot["代码"] = index_spot["代码"].astype(str).str.zfill(6)
    hedge_row = index_spot.loc[index_spot["代码"] == "000852"]
    if hedge_row.empty:
        hedge_rt_close = float(close_df["hedge"].iloc[-1])
        hedge_source = "latest_cached_close_fallback"
    else:
        hedge_row = hedge_row.iloc[0]
        hedge_rt_close = pd.to_numeric(hedge_row.get("最新价"), errors="coerce")
        hedge_prev = pd.to_numeric(hedge_row.get("昨收"), errors="coerce")
        if pd.isna(hedge_rt_close) or hedge_rt_close <= 0:
            hedge_rt_close = hedge_prev if pd.notna(hedge_prev) and hedge_prev > 0 else float(close_df["hedge"].iloc[-1])
            hedge_source = "index_prev_close_fallback"
        else:
            hedge_source = "index_spot_latest"

    snapshot_ts = pd.Timestamp.now()
    if snapshot_ts <= latest_trade_date:
        snapshot_ts = latest_trade_date + pd.Timedelta(seconds=1)
    rt_close_df = close_df.copy()
    rt_close_df.loc[snapshot_ts, ["microcap", "hedge"]] = [microcap_rt_close, float(hedge_rt_close)]
    rt_close_df = rt_close_df.sort_index()
    rt_result = run_signal(rt_close_df)
    latest_rt_signal = enrich_signal_frame(hedge_mod.build_latest_signal(rt_result), rt_result)
    latest_rt_signal["date"] = snapshot_ts
    latest_rt_signal["quote_source"] = quote_source
    latest_rt_signal["hedge_quote_source"] = hedge_source
    latest_rt_signal["member_price_count"] = available_rows
    latest_rt_signal["member_count"] = len(member_symbols)
    latest_rt_signal["latest_anchor_trade_date"] = latest_trade_date

    meta = {
        "snapshot_time": str(snapshot_ts),
        "latest_anchor_trade_date": str(latest_trade_date.date()),
        "quote_source": quote_source,
        "hedge_quote_source": hedge_source,
        "member_price_count": available_rows,
        "member_count": len(member_symbols),
        "microcap_rt_close": float(microcap_rt_close),
        "hedge_rt_close": float(hedge_rt_close),
    }
    return latest_rt_signal, meta


def load_cached_realtime_state(
    paths: dict[str, Path],
    cache_seconds: int,
    latest_anchor_trade_date: pd.Timestamp,
    latest_rebalance: pd.Timestamp,
    effective_rebalance: pd.Timestamp | None,
    rebalance_effective_date: pd.Timestamp | None,
    capital: float | None,
) -> dict[str, object] | None:
    meta_path = paths["cache_realtime_meta"]
    signal_path = paths["cache_realtime_signal"]
    members_path = paths["cache_realtime_members"]
    changes_path = paths["cache_realtime_changes"]
    needed = [meta_path, signal_path, members_path, changes_path]
    if not all(path.exists() for path in needed):
        return None
    cache_age_seconds = time.time() - meta_path.stat().st_mtime
    if cache_age_seconds > cache_seconds:
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        expected = {
            "latest_anchor_trade_date": str(pd.Timestamp(latest_anchor_trade_date).date()),
            "latest_rebalance": str(pd.Timestamp(latest_rebalance).date()),
            "effective_rebalance": None if effective_rebalance is None else str(pd.Timestamp(effective_rebalance).date()),
            "rebalance_effective_date": None if rebalance_effective_date is None else str(pd.Timestamp(rebalance_effective_date).date()),
        }
        if any(meta.get(key) != value for key, value in expected.items()):
            return None
        signal_df = pd.read_csv(signal_path)
        members_df = pd.read_csv(members_path, dtype={"symbol": str})
        changes_df = pd.read_csv(changes_path, dtype={"symbol": str})
        members_df = add_capital_columns(members_df, capital)
        return {
            "meta": meta,
            "signal": signal_df,
            "members": members_df,
            "changes": changes_df,
            "from_cache": True,
            "cache_age_seconds": float(cache_age_seconds),
        }
    except Exception:
        return None


def save_realtime_state_cache(
    paths: dict[str, Path],
    meta: dict[str, object],
    signal_df: pd.DataFrame,
    members_df: pd.DataFrame,
    changes_df: pd.DataFrame,
) -> None:
    REALTIME_DIR.mkdir(parents=True, exist_ok=True)
    paths["cache_realtime_meta"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    signal_df.to_csv(paths["cache_realtime_signal"], index=False, encoding="utf-8")
    members_df.to_csv(paths["cache_realtime_members"], index=False, encoding="utf-8")
    changes_df.to_csv(paths["cache_realtime_changes"], index=False, encoding="utf-8")


def compute_realtime_state(
    context: dict[str, object],
    cache_seconds: int,
    capital: float | None,
) -> dict[str, object]:
    paths = context["paths"]
    latest_trade_date = pd.Timestamp(context["close_df"].index[-1])
    latest_rebalance = pd.Timestamp(context["latest_rebalance"])
    effective_rebalance = context.get("effective_rebalance")
    rebalance_effective_date = context.get("rebalance_effective_date")

    cached = load_cached_realtime_state(
        paths=paths,
        cache_seconds=cache_seconds,
        latest_anchor_trade_date=latest_trade_date,
        latest_rebalance=latest_rebalance,
        effective_rebalance=effective_rebalance,
        rebalance_effective_date=rebalance_effective_date,
        capital=capital,
    )
    if cached is not None:
        return cached

    shares_df = load_or_refresh_latest_shares()
    quotes_df, quote_source = build_realtime_quote_map(cache_seconds)
    quotes_small = quotes_df[["code", "名称", "rt_price", "昨收", "今开", "最高", "最低", "成交额"]].copy()

    realtime_members = shares_df.merge(quotes_small, on="code", how="inner")
    realtime_members = realtime_members[realtime_members["name"].map(is_tradable_name)].copy()
    realtime_members["market_cap"] = realtime_members["rt_price"] * realtime_members["total_shares"]
    realtime_members = realtime_members.dropna(subset=["market_cap"]).sort_values("market_cap").head(TOP_N).copy()
    realtime_members["rank"] = np.arange(1, len(realtime_members) + 1)
    realtime_members["target_weight"] = 1.0 / TOP_N
    realtime_members["symbol"] = realtime_members["code"]
    realtime_members["name"] = realtime_members["名称"].fillna(realtime_members["name"])
    realtime_members["signal_date"] = latest_rebalance.date()
    realtime_members["effective_date"] = None if rebalance_effective_date is None else pd.Timestamp(rebalance_effective_date).date()
    members_out = realtime_members[
        ["rank", "symbol", "name", "rt_price", "market_cap", "target_weight", "change_date", "今开", "最高", "最低", "成交额", "signal_date", "effective_date"]
    ].reset_index(drop=True)
    members_out = add_capital_columns(members_out, capital)

    current_members = context["effective_members"].copy()
    current_members["symbol"] = current_members["symbol"].astype(str)
    members_for_diff = members_out.copy()
    members_for_diff["symbol"] = members_for_diff["symbol"].astype(str)
    changes_df = build_change_table(current_members[["symbol", "rank", "name"]], members_for_diff[["symbol", "rank", "name"]])
    if not changes_df.empty:
        rt_cap_map = dict(zip(members_for_diff["symbol"], members_for_diff["market_cap"]))
        rt_price_map = dict(zip(members_for_diff["symbol"], members_for_diff["rt_price"]))
        changes_df["realtime_market_cap"] = changes_df["symbol"].map(rt_cap_map)
        changes_df["realtime_price"] = changes_df["symbol"].map(rt_price_map)
        changes_df["signal_date"] = latest_rebalance.date()
        changes_df["effective_date"] = None if rebalance_effective_date is None else pd.Timestamp(rebalance_effective_date).date()

    close_df = context["close_df"].copy()
    effective_members_df = context["effective_members"].copy()
    member_symbols = effective_members_df["symbol"].astype(str).tolist()
    last_close_map = load_latest_close_map(member_symbols, as_of_date=latest_trade_date)
    quotes_indexed = quotes_df.set_index("code")
    member_returns: list[float] = []
    available_rows = 0
    for symbol in member_symbols:
        last_close = last_close_map.get(symbol)
        if last_close is None or last_close <= 0 or symbol not in quotes_indexed.index:
            continue
        rt_price = pd.to_numeric(quotes_indexed.at[symbol, "rt_price"], errors="coerce")
        if pd.isna(rt_price) or rt_price <= 0:
            continue
        member_returns.append(float(rt_price / last_close - 1.0))
        available_rows += 1
    if not member_returns:
        raise ValueError("无法计算实时信号: 当前成分股没有可用实时价格。")

    last_microcap_close = float(close_df["microcap"].iloc[-1])
    microcap_rt_close = last_microcap_close * (1.0 + float(np.mean(member_returns)))

    index_spot = load_or_refresh_index_spot(cache_seconds)
    index_spot["代码"] = index_spot["代码"].astype(str).str.zfill(6)
    hedge_row = index_spot.loc[index_spot["代码"] == "000852"]
    if hedge_row.empty:
        hedge_rt_close = float(close_df["hedge"].iloc[-1])
        hedge_source = "latest_cached_close_fallback"
    else:
        hedge_row = hedge_row.iloc[0]
        hedge_rt_close = pd.to_numeric(hedge_row.get("最新价"), errors="coerce")
        hedge_prev = pd.to_numeric(hedge_row.get("昨收"), errors="coerce")
        if pd.isna(hedge_rt_close) or hedge_rt_close <= 0:
            hedge_rt_close = hedge_prev if pd.notna(hedge_prev) and hedge_prev > 0 else float(close_df["hedge"].iloc[-1])
            hedge_source = "index_prev_close_fallback"
        else:
            hedge_source = "index_spot_latest"

    snapshot_ts = pd.Timestamp.now()
    if snapshot_ts <= latest_trade_date:
        snapshot_ts = latest_trade_date + pd.Timedelta(seconds=1)
    rt_close_df = close_df.copy()
    rt_close_df.loc[snapshot_ts, ["microcap", "hedge"]] = [microcap_rt_close, float(hedge_rt_close)]
    rt_close_df = rt_close_df.sort_index()
    rt_result = run_signal(rt_close_df)
    signal_df = enrich_signal_frame(hedge_mod.build_latest_signal(rt_result), rt_result)
    jitter_level, jitter_note = classify_tail_jitter_risk(float(signal_df.iloc[0]["momentum_gap"]))
    signal_df["date"] = snapshot_ts
    signal_df["quote_source"] = quote_source
    signal_df["hedge_quote_source"] = hedge_source
    signal_df["member_price_count"] = available_rows
    signal_df["member_count"] = len(member_symbols)
    signal_df["latest_anchor_trade_date"] = latest_trade_date
    signal_df["tail_jitter_risk"] = jitter_level
    signal_df["tail_jitter_note"] = jitter_note

    meta = {
        "snapshot_time": str(snapshot_ts),
        "latest_anchor_trade_date": str(latest_trade_date.date()),
        "latest_rebalance": str(latest_rebalance.date()),
        "effective_rebalance": None if effective_rebalance is None else str(pd.Timestamp(effective_rebalance).date()),
        "rebalance_effective_date": None if rebalance_effective_date is None else str(pd.Timestamp(rebalance_effective_date).date()),
        "quote_source": quote_source,
        "hedge_quote_source": hedge_source,
        "member_price_count": available_rows,
        "member_count": len(member_symbols),
        "microcap_rt_close": float(microcap_rt_close),
        "hedge_rt_close": float(hedge_rt_close),
        "tail_jitter_risk": jitter_level,
        "tail_jitter_note": jitter_note,
    }
    save_realtime_state_cache(
        paths=paths,
        meta=meta,
        signal_df=signal_df,
        members_df=members_out.drop(columns=["target_notional"], errors="ignore"),
        changes_df=changes_df,
    )
    return {
        "meta": meta,
        "signal": signal_df,
        "members": members_out,
        "changes": changes_df,
        "from_cache": False,
        "cache_age_seconds": 0.0,
    }


def format_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df.empty:
        return "(empty)"
    return df.head(max_rows).to_string(index=False)


def handle_query(context: dict[str, object], args: argparse.Namespace, query: str) -> None:
    query = query.strip()
    paths = context["paths"]
    latest_rebalance = pd.Timestamp(context["latest_rebalance"])
    rebalance_effective_date = context.get("rebalance_effective_date")
    save_base_outputs(context)

    if query == "信号":
        latest_signal = context["latest_signal"]
        print("确认信号")
        print(format_table(latest_signal))
        print(f"已保存: {paths['signal'].name}")
        return

    if query == "实时信号":
        realtime_state = compute_realtime_state(context, args.realtime_cache_seconds, args.capital)
        rt_signal = realtime_state["signal"]
        meta = realtime_state["meta"]
        cache_age_seconds = float(realtime_state.get("cache_age_seconds", 0.0))
        rt_signal.to_csv(paths["realtime_signal"], index=False, encoding="utf-8")
        gap_value = float(rt_signal.iloc[0]["momentum_gap"])
        jitter_risk = str(rt_signal.iloc[0].get("tail_jitter_risk", "normal"))
        jitter_note = str(rt_signal.iloc[0].get("tail_jitter_note", "") or "")
        print("实时信号")
        print(format_table(rt_signal))
        print(f"实时快照时间: {meta['snapshot_time']}")
        print(f"锚定最新历史交易日: {meta['latest_anchor_trade_date']}")
        print(f"微盘实时价格来源: {meta['quote_source']}")
        print(f"对冲腿实时价格来源: {meta['hedge_quote_source']}")
        print(f"尾盘抖动风险: {jitter_risk} (|gap|={abs(gap_value):.4%})")
        if jitter_risk != "normal" and jitter_note:
            print(f"提示: {jitter_note}")
        print(f"结果来源: {'cache' if realtime_state['from_cache'] else 'fresh'}")
        print(f"实时结果年龄: {cache_age_seconds:.1f} 秒")
        print(f"已保存: {paths['realtime_signal'].name}")
        return

    if query == "成分股":
        members = context["target_members"]
        members.to_csv(paths["members"], index=False, encoding="utf-8")
        print("最新成分股")
        print(f"信号日: {latest_rebalance.date()}")
        print(
            "生效日: {}".format(
                "暂无下一交易日" if rebalance_effective_date is None else pd.Timestamp(rebalance_effective_date).date()
            )
        )
        print(format_table(members[["rank", "symbol", "name", "market_cap", "target_weight", "signal_date", "effective_date"]], max_rows=TOP_N))
        print(f"已保存: {paths['members'].name}")
        return

    if query == "进出名单":
        changes = context["changes_df"]
        changes.to_csv(paths["changes"], index=False, encoding="utf-8")
        print("最新进出名单")
        print(f"信号日: {latest_rebalance.date()}")
        print(
            "生效日: {}".format(
                "暂无下一交易日" if rebalance_effective_date is None else pd.Timestamp(rebalance_effective_date).date()
            )
        )
        print(format_table(changes))
        print(f"已保存: {paths['changes'].name}")
        return

    if query == "实时进出名单":
        realtime_state = compute_realtime_state(context, args.realtime_cache_seconds, args.capital)
        realtime_members = realtime_state["members"]
        changes = realtime_state["changes"]
        quote_source = realtime_state["meta"]["quote_source"]
        snapshot_time = realtime_state["meta"].get("snapshot_time")
        cache_age_seconds = float(realtime_state.get("cache_age_seconds", 0.0))
        realtime_members.to_csv(paths["realtime_members"], index=False, encoding="utf-8")
        changes.to_csv(paths["realtime_changes"], index=False, encoding="utf-8")
        print("实时进出名单")
        print(f"基准调仓信号日: {latest_rebalance.date()}")
        print(
            "静态名单生效日: {}".format(
                "暂无下一交易日" if rebalance_effective_date is None else pd.Timestamp(rebalance_effective_date).date()
            )
        )
        if snapshot_time:
            print(f"实时快照时间: {snapshot_time}")
        print(f"实时价格来源: {quote_source}")
        print(f"结果来源: {'cache' if realtime_state['from_cache'] else 'fresh'}")
        print(f"实时结果年龄: {cache_age_seconds:.1f} 秒")
        print(format_table(changes))
        print(f"已保存: {paths['realtime_changes'].name}")
        return

    if PERFORMANCE_PATTERN.search(query):
        perf_df, ret_col, nav_col, source_label = load_performance_source(args.costed_nav_csv, context["result"])
        build_performance_outputs(
            perf_df=perf_df,
            ret_col=ret_col,
            nav_col=nav_col,
            source_label=source_label,
            query_text=query,
            paths=paths,
        )
        summary = pd.read_csv(paths["performance_summary"])
        yearly = pd.read_csv(paths["performance_yearly"])
        print("表现汇总")
        print(format_table(summary))
        print("年度分解")
        print(format_table(yearly, max_rows=30))
        print(f"已保存: {paths['performance_chart'].name}")
        print(f"已保存: {paths['performance_summary'].name}")
        print(f"已保存: {paths['performance_yearly'].name}")
        print(f"已保存: {paths['performance_nav'].name}")
        print(f"已保存: {paths['performance_json'].name}")
        return

    raise ValueError(
        "不支持的查询命令。支持: 信号 / 实时信号 / 成分股 / 进出名单 / 实时进出名单 / 表现 <区间>"
    )


def main() -> None:
    args = parse_args()
    query = " ".join(args.query_tokens).strip()
    include_members = (not query) or query in {"成分股", "进出名单", "实时进出名单", "实时信号"}
    context = build_base_context(args, include_members=include_members)
    if query:
        handle_query(context, args, query)
        return

    save_base_outputs(context)
    print_console_summary(context["summary"])
    paths = context["paths"]
    print(f"saved {paths['summary'].name}")
    print(f"saved {paths['signal'].name}")
    print(f"saved {paths['members'].name}")
    print(f"saved {paths['changes'].name}")
    print(f"saved {paths['nav'].name}")


if __name__ == "__main__":
    main()

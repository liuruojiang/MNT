from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import analyze_microcap_zz1000_hedge as hedge_mod


ROOT = Path(__file__).resolve().parent
MEMBERS_CSV = ROOT / "wind_microcap_868008_monthly_16y_members.csv"
BASE_INDEX_CSV = ROOT / "wind_microcap_868008_monthly_16y.csv"
PRICE_CACHE_DIR = ROOT / ".microcap_index_cache" / "prices_raw"

COUNTS = [100, 200, 300, 400]
WINDOWS = {
    5: pd.Timestamp("2021-03-18"),
    10: pd.Timestamp("2016-03-18"),
    15: pd.Timestamp("2011-03-18"),
}
END_DATE = pd.Timestamp("2026-03-18")


def calc_turnover(member_map: dict[pd.Timestamp, list[str]], count: int) -> float:
    ordered_dates = sorted(member_map)
    turnovers: list[float] = []
    for prev_dt, curr_dt in zip(ordered_dates[:-1], ordered_dates[1:]):
        prev_set = set(member_map[prev_dt])
        curr_set = set(member_map[curr_dt])
        overlap = len(prev_set & curr_set)
        turnovers.append(1.0 - overlap / count)
    return float(pd.Series(turnovers).mean()) if turnovers else 0.0


def max_dd_window(nav: pd.Series) -> dict[str, object]:
    dd = nav / nav.cummax() - 1.0
    trough_date = dd.idxmin()
    peak_date = nav.loc[:trough_date].idxmax()
    post = nav.loc[trough_date:]
    recovery_candidates = post[post >= nav.loc[peak_date]]
    recovery_date = recovery_candidates.index[0] if len(recovery_candidates) else pd.NaT
    return {
        "peak_date": str(peak_date.date()),
        "trough_date": str(trough_date.date()),
        "recovery_date": None if pd.isna(recovery_date) else str(recovery_date.date()),
    }


def load_members() -> pd.DataFrame:
    members = pd.read_csv(MEMBERS_CSV, dtype={"symbol": str, "rank": int})
    members["symbol"] = members["symbol"].str.zfill(6)
    members["rebalance_date"] = pd.to_datetime(members["rebalance_date"])
    return members


def load_trading_dates() -> pd.DatetimeIndex:
    index_df = pd.read_csv(BASE_INDEX_CSV, usecols=["date"])
    index_df["date"] = pd.to_datetime(index_df["date"])
    return pd.DatetimeIndex(index_df["date"])


def load_returns(all_symbols: list[str], trading_dates: pd.DatetimeIndex) -> pd.DataFrame:
    ret_series: dict[str, pd.Series] = {}
    for symbol in all_symbols:
        path = PRICE_CACHE_DIR / f"{symbol}.csv"
        if not path.exists():
            continue
        px = pd.read_csv(path, usecols=["date", "close_raw"])
        px["date"] = pd.to_datetime(px["date"])
        px = px.sort_values("date").drop_duplicates("date")
        ret_series[symbol] = px.set_index("date")["close_raw"].pct_change(fill_method=None).reindex(trading_dates)
    return pd.DataFrame(ret_series, index=trading_dates)


def build_count_index(
    trading_dates: pd.DatetimeIndex,
    returns_df: pd.DataFrame,
    member_map: dict[pd.Timestamp, list[str]],
) -> pd.DataFrame:
    current_members: list[str] = []
    rebalance_set = set(member_map)
    current_level = 1000.0
    rows: list[dict[str, object]] = []
    for i, dt in enumerate(trading_dates):
        if i == 0:
            rows.append(
                {
                    "date": dt,
                    "close": current_level,
                    "daily_return": None,
                    "holding_count": 0,
                }
            )
            if dt in rebalance_set:
                current_members = member_map.get(pd.Timestamp(dt), [])
            continue

        if trading_dates[i - 1] in rebalance_set:
            current_members = member_map.get(pd.Timestamp(trading_dates[i - 1]), [])

        if current_members:
            available = [symbol for symbol in current_members if symbol in returns_df.columns]
            day_ret = returns_df.loc[dt, available].dropna()
            bucket_ret = float(day_ret.mean()) if len(day_ret) else 0.0
        else:
            bucket_ret = 0.0

        current_level *= 1.0 + bucket_ret
        rows.append(
            {
                "date": dt,
                "close": current_level,
                "daily_return": bucket_ret,
                "holding_count": len(current_members),
            }
        )
    return pd.DataFrame(rows)


def summarize_long_only(index_df: pd.DataFrame, label: str, avg_turnover: float) -> list[dict[str, object]]:
    index_df = index_df.copy()
    index_df["date"] = pd.to_datetime(index_df["date"])
    index_df = index_df.set_index("date")
    rows: list[dict[str, object]] = []
    for years, start_target in WINDOWS.items():
        part_nav = index_df.loc[(index_df.index >= start_target) & (index_df.index <= END_DATE), "close"].copy()
        part_ret = part_nav.pct_change(fill_method=None).dropna()
        if len(part_ret) < 30:
            continue
        metrics = hedge_mod.calc_metrics(part_ret)
        row = {
            "index_label": label,
            "window_years": years,
            "window_start_actual": str(part_nav.index[0].date()),
            "window_end": str(part_nav.index[-1].date()),
            "annual": float(metrics.annual),
            "max_dd": float(metrics.max_dd),
            "sharpe": float(metrics.sharpe),
            "vol": float(metrics.vol),
            "total_return": float(metrics.total_return),
            "win_rate": float(metrics.win_rate),
            "avg_monthly_member_turnover": avg_turnover,
        }
        row.update(max_dd_window(part_nav))
        rows.append(row)
    return rows


def summarize_strategy(index_path: Path, label: str) -> list[dict[str, object]]:
    class Args:
        pass

    args = Args()
    args.panel_path = hedge_mod.DEFAULT_PANEL
    args.microcap_column = hedge_mod.DEFAULT_MICROCAP_COLUMN
    args.hedge_column = hedge_mod.DEFAULT_HEDGE_COLUMN
    args.lookback = 5
    args.signal_model = "momentum"
    args.bias_n = hedge_mod.DEFAULT_BIAS_N
    args.bias_mom_day = hedge_mod.DEFAULT_BIAS_MOM_DAY
    args.futures_drag = hedge_mod.DEFAULT_FUTURES_DRAG
    args.r2_window = 5
    args.r2_threshold = 0.0
    args.vol_scale_enabled = False
    args.target_vol = hedge_mod.DEFAULT_TARGET_VOL
    args.vol_window = hedge_mod.DEFAULT_VOL_WINDOW
    args.max_lev = hedge_mod.DEFAULT_MAX_LEV
    args.min_lev = hedge_mod.DEFAULT_MIN_LEV
    args.scale_threshold = hedge_mod.DEFAULT_SCALE_THRESHOLD
    args.microcap_csv = index_path
    args.microcap_date_col = "date"
    args.microcap_close_col = "close"
    args.output_prefix = "tmp_unused"
    args.require_positive_microcap_mom = False

    close_df = hedge_mod.build_close_df(args)
    result = hedge_mod.run_backtest(
        close_df=close_df,
        signal_model="momentum",
        lookback=5,
        bias_n=hedge_mod.DEFAULT_BIAS_N,
        bias_mom_day=hedge_mod.DEFAULT_BIAS_MOM_DAY,
        futures_drag=hedge_mod.DEFAULT_FUTURES_DRAG,
        require_positive_microcap_mom=False,
        r2_window=5,
        r2_threshold=0.0,
        vol_scale_enabled=False,
        target_vol=hedge_mod.DEFAULT_TARGET_VOL,
        vol_window=hedge_mod.DEFAULT_VOL_WINDOW,
        max_lev=hedge_mod.DEFAULT_MAX_LEV,
        min_lev=hedge_mod.DEFAULT_MIN_LEV,
        scale_threshold=hedge_mod.DEFAULT_SCALE_THRESHOLD,
    )

    rows: list[dict[str, object]] = []
    for years, start_target in WINDOWS.items():
        part = result.loc[(result.index >= start_target) & (result.index <= END_DATE)].copy()
        if len(part) < 30:
            continue
        metrics = hedge_mod.calc_metrics(part["return"])
        active = part["holding"] != "cash"
        span_years = (part.index[-1] - part.index[0]).days / 365.25
        trades = int(active.ne(active.shift()).sum() - 1)
        row = {
            "index_label": label,
            "window_years": years,
            "window_start_actual": str(part.index[0].date()),
            "window_end": str(part.index[-1].date()),
            "annual": float(metrics.annual),
            "max_dd": float(metrics.max_dd),
            "sharpe": float(metrics.sharpe),
            "vol": float(metrics.vol),
            "total_return": float(metrics.total_return),
            "win_rate": float(metrics.win_rate),
            "active_days_pct": float(active.mean()),
            "trades_per_year": float(trades / span_years) if span_years > 0 else 0.0,
        }
        row.update(max_dd_window(part["nav"]))
        rows.append(row)
    return rows


def main() -> None:
    members = load_members()
    trading_dates = load_trading_dates()
    all_symbols = sorted(set(members["symbol"]))
    returns_df = load_returns(all_symbols=all_symbols, trading_dates=trading_dates)

    long_only_rows: list[dict[str, object]] = []
    strategy_rows: list[dict[str, object]] = []
    nav_cols: dict[str, pd.Series] = {}

    for count in COUNTS:
        label = f"top_{count}"
        sub = members[members["rank"] <= count].copy()
        member_map = {
            pd.Timestamp(dt): grp["symbol"].tolist()
            for dt, grp in sub.groupby("rebalance_date")
        }
        avg_turnover = calc_turnover(member_map=member_map, count=count)
        index_df = build_count_index(
            trading_dates=trading_dates,
            returns_df=returns_df,
            member_map=member_map,
        )
        out_path = ROOT / f"wind_microcap_top_{count}_monthly_16y.csv"
        index_df.to_csv(out_path, index=False, encoding="utf-8-sig")
        nav_cols[label] = index_df.set_index("date")["close"]

        long_only_rows.extend(summarize_long_only(index_df=index_df, label=label, avg_turnover=avg_turnover))
        strategy_rows.extend(summarize_strategy(index_path=out_path, label=label))

    pd.DataFrame(nav_cols).reset_index().to_csv(
        ROOT / "microcap_top_100_200_300_400_navs_16y.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(long_only_rows).to_csv(
        ROOT / "microcap_top_100_200_300_400_longonly_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(strategy_rows).to_csv(
        ROOT / "microcap_top_100_200_300_400_strategy_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    report = {
        "counts": COUNTS,
        "windows": list(WINDOWS),
        "long_only_output": "microcap_top_100_200_300_400_longonly_summary.csv",
        "strategy_output": "microcap_top_100_200_300_400_strategy_summary.csv",
    }
    with open(ROOT / "microcap_top_100_200_300_400_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

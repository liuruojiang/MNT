from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd

import fetch_wind_microcap_index as fetch_mod
import microcap_top100_mom16_biweekly_live as live_mod


ROOT = Path(__file__).resolve().parent
MINUTE_CACHE_DIR = ROOT / ".microcap_index_cache" / "realtime" / "minute5m_tail"
OUTPUT_CSV = ROOT / "microcap_top100_tail10m_jitter_recent_exact.csv"
OUTPUT_JSON = ROOT / "microcap_top100_tail10m_jitter_estimate.json"

LOOKBACK = live_mod.LOOKBACK
TOP_N = live_mod.TOP_N


def ensure_cache_dir() -> None:
    MINUTE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def code_to_symbol_map() -> dict[str, str]:
    df = pd.read_csv(live_mod.freq_mod.ACTIVE_UNIVERSE, dtype=str)
    return dict(zip(df["code"].str.zfill(6), df["symbol"]))


def load_recent_context() -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex, dict[pd.Timestamp, list[str]]]:
    close_df = live_mod.load_close_df(live_mod.hedge_mod.DEFAULT_PANEL, live_mod.DEFAULT_INDEX_CSV)
    result = live_mod.run_signal(close_df)
    trading_dates = close_df.index
    latest_trade_date = pd.Timestamp(trading_dates[-1])
    recent_days = trading_dates[trading_dates >= latest_trade_date - pd.DateOffset(days=60)]

    rebalance_dates = fetch_mod.build_rebalance_dates(
        trading_dates=trading_dates,
        switch_date=str(trading_dates[0].date()),
        pre_switch_schedule=live_mod.PRE_SWITCH_SCHEDULE,
        post_switch_schedule=live_mod.POST_SWITCH_SCHEDULE,
    )
    recent_rebalances = [pd.Timestamp(x) for x in rebalance_dates if pd.Timestamp(x) <= latest_trade_date and pd.Timestamp(x) >= recent_days[0] - pd.DateOffset(days=20)]
    snapshots = live_mod.load_member_snapshot(recent_rebalances, max_workers=8)

    effective_members_by_day: dict[pd.Timestamp, list[str]] = {}
    current_members: list[str] = []
    rebalance_set = {pd.Timestamp(x) for x in recent_rebalances}
    next_members_map = {pd.Timestamp(dt): df["symbol"].astype(str).tolist() for dt, df in snapshots.items()}
    for i, dt in enumerate(trading_dates):
        if i == 0:
            if dt in rebalance_set:
                current_members = next_members_map.get(pd.Timestamp(dt), [])
        else:
            if pd.Timestamp(trading_dates[i - 1]) in rebalance_set:
                current_members = next_members_map.get(pd.Timestamp(trading_dates[i - 1]), [])
        if dt in recent_days:
            effective_members_by_day[pd.Timestamp(dt)] = list(current_members)
    return close_df, result, recent_days, effective_members_by_day


def cache_file_for_symbol(symbol: str) -> Path:
    return MINUTE_CACHE_DIR / f"{symbol}.csv"


def cache_file_for_stock(symbol: str) -> Path:
    return MINUTE_CACHE_DIR / f"{symbol}_em.csv"


def cache_file_for_index() -> Path:
    return MINUTE_CACHE_DIR / "index_000852.csv"


def fetch_stock_5m(symbol: str) -> tuple[str, pd.DataFrame | None]:
    path = cache_file_for_stock(symbol)
    if path.exists():
        try:
            df = pd.read_csv(path)
            if "时间" in df.columns:
                df["时间"] = pd.to_datetime(df["时间"])
                return symbol, df
        except Exception:
            pass
    try:
        df = ak.stock_zh_a_hist_min_em(
            symbol=symbol[-6:],
            period="5",
            start_date="2026-02-01 09:30:00",
            end_date="2026-03-27 15:00:00",
            adjust="",
        )
        df.to_csv(path, index=False, encoding="utf-8")
        df["时间"] = pd.to_datetime(df["时间"])
        return symbol, df
    except Exception:
        return symbol, None


def fetch_index_5m() -> pd.DataFrame:
    path = cache_file_for_index()
    if path.exists():
        try:
            df = pd.read_csv(path)
            df["时间"] = pd.to_datetime(df["时间"])
            return df
        except Exception:
            pass
    df = ak.index_zh_a_hist_min_em(
        symbol="000852",
        period="5",
        start_date="2025-01-01 09:30:00",
        end_date="2030-01-01 15:00:00",
    )
    df.to_csv(path, index=False, encoding="utf-8")
    df["时间"] = pd.to_datetime(df["时间"])
    return df


def extract_tail_return_stock(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "ret_10m"])
    work = df.copy()
    work["date"] = work["时间"].dt.normalize()
    work["time_str"] = work["时间"].dt.strftime("%H:%M:%S")
    p1450 = work.loc[work["time_str"] == "14:50:00", ["date", "收盘"]].rename(columns={"收盘": "c1450"})
    p1500 = work.loc[work["time_str"] == "15:00:00", ["date", "收盘"]].rename(columns={"收盘": "c1500"})
    out = p1450.merge(p1500, on="date", how="inner")
    out["ret_10m"] = pd.to_numeric(out["c1500"], errors="coerce") / pd.to_numeric(out["c1450"], errors="coerce") - 1.0
    return out[["date", "ret_10m"]].dropna()


def extract_tail_return_index(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["date"] = work["时间"].dt.normalize()
    work["time_str"] = work["时间"].dt.strftime("%H:%M:%S")
    p1450 = work.loc[work["time_str"] == "14:50:00", ["date", "收盘"]].rename(columns={"收盘": "c1450"})
    p1500 = work.loc[work["time_str"] == "15:00:00", ["date", "收盘"]].rename(columns={"收盘": "c1500"})
    out = p1450.merge(p1500, on="date", how="inner")
    out["ret_10m"] = pd.to_numeric(out["c1500"], errors="coerce") / pd.to_numeric(out["c1450"], errors="coerce") - 1.0
    return out[["date", "ret_10m"]].dropna()


def compute_recent_exact(
    close_df: pd.DataFrame,
    result: pd.DataFrame,
    recent_days: pd.DatetimeIndex,
    effective_members_by_day: dict[pd.Timestamp, list[str]],
    stock_tail_by_code: dict[str, pd.DataFrame],
    index_tail: pd.DataFrame,
) -> pd.DataFrame:
    index_map = dict(zip(index_tail["date"], index_tail["ret_10m"]))
    rows: list[dict[str, object]] = []
    date_pos = {pd.Timestamp(dt): i for i, dt in enumerate(close_df.index)}

    for dt in recent_days:
        dt = pd.Timestamp(dt)
        if dt not in index_map or dt not in date_pos or date_pos[dt] < LOOKBACK:
            continue
        members = effective_members_by_day.get(dt, [])
        member_rets = []
        for code in members:
            tail_df = stock_tail_by_code.get(code)
            if tail_df is None or tail_df.empty:
                continue
            sub = tail_df.loc[tail_df["date"] == dt, "ret_10m"]
            if len(sub):
                member_rets.append(float(sub.iloc[0]))
        if len(member_rets) < 70:
            continue

        idx = date_pos[dt]
        ref_dt = pd.Timestamp(close_df.index[idx - LOOKBACK])
        micro_close = float(close_df.loc[dt, "microcap"])
        hedge_close = float(close_df.loc[dt, "hedge"])
        micro_ref = float(close_df.loc[ref_dt, "microcap"])
        hedge_ref = float(close_df.loc[ref_dt, "hedge"])

        r_micro_10m = float(np.mean(member_rets))
        r_hedge_10m = float(index_map[dt])
        micro_1450 = micro_close / (1.0 + r_micro_10m)
        hedge_1450 = hedge_close / (1.0 + r_hedge_10m)
        gap_close = float(result.loc[dt, "momentum_gap"])
        gap_1450 = (micro_1450 / micro_ref - 1.0) - (hedge_1450 / hedge_ref - 1.0)
        close_signal = gap_close > 0.0
        signal_1450 = gap_1450 > 0.0
        rows.append(
            {
                "date": str(dt.date()),
                "member_count_used": int(len(member_rets)),
                "micro_ret_10m": r_micro_10m,
                "hedge_ret_10m": r_hedge_10m,
                "gap_1450": gap_1450,
                "gap_close": gap_close,
                "signal_1450": bool(signal_1450),
                "signal_close": bool(close_signal),
                "jitter": bool(signal_1450 != close_signal),
            }
        )
    return pd.DataFrame(rows)


def estimate_last_year_probability(close_df: pd.DataFrame, result: pd.DataFrame, exact_df: pd.DataFrame) -> dict[str, object]:
    pairs = exact_df[["micro_ret_10m", "hedge_ret_10m"]].dropna().to_numpy()
    latest_trade_date = pd.Timestamp(close_df.index[-1])
    last_year_start = latest_trade_date - pd.DateOffset(years=1)
    window = result.loc[result.index >= last_year_start].copy()
    date_pos = {pd.Timestamp(dt): i for i, dt in enumerate(close_df.index)}
    daily_probs = []

    for dt, row in window.iterrows():
        dt = pd.Timestamp(dt)
        if dt not in date_pos or date_pos[dt] < LOOKBACK:
            continue
        idx = date_pos[dt]
        ref_dt = pd.Timestamp(close_df.index[idx - LOOKBACK])
        micro_close = float(close_df.loc[dt, "microcap"])
        hedge_close = float(close_df.loc[dt, "hedge"])
        micro_ref = float(close_df.loc[ref_dt, "microcap"])
        hedge_ref = float(close_df.loc[ref_dt, "hedge"])
        close_signal = float(row["momentum_gap"]) > 0.0

        flips = 0
        for r_micro_10m, r_hedge_10m in pairs:
            micro_1450 = micro_close / (1.0 + float(r_micro_10m))
            hedge_1450 = hedge_close / (1.0 + float(r_hedge_10m))
            gap_1450 = (micro_1450 / micro_ref - 1.0) - (hedge_1450 / hedge_ref - 1.0)
            signal_1450 = gap_1450 > 0.0
            flips += int(signal_1450 != close_signal)
        prob = flips / len(pairs) if len(pairs) else np.nan
        daily_probs.append({"date": str(dt.date()), "estimated_flip_prob": prob, "gap_close": float(row["momentum_gap"])})

    daily_prob_df = pd.DataFrame(daily_probs)
    return {
        "window_start": str(last_year_start.date()),
        "window_end": str(latest_trade_date.date()),
        "days": int(len(daily_prob_df)),
        "estimated_average_flip_prob": float(daily_prob_df["estimated_flip_prob"].mean()),
        "estimated_median_flip_prob": float(daily_prob_df["estimated_flip_prob"].median()),
        "estimated_p90_flip_prob": float(daily_prob_df["estimated_flip_prob"].quantile(0.9)),
        "high_risk_days_over_10pct": int((daily_prob_df["estimated_flip_prob"] > 0.10).sum()),
        "high_risk_days_over_25pct": int((daily_prob_df["estimated_flip_prob"] > 0.25).sum()),
    }, daily_prob_df


def main() -> None:
    ensure_cache_dir()
    close_df, result, recent_days, effective_members_by_day = load_recent_context()
    code_map = code_to_symbol_map()
    union_codes = sorted({code for members in effective_members_by_day.values() for code in members})
    union_symbols = [code_map[code] for code in union_codes if code in code_map]

    stock_tail_by_code: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(fetch_stock_5m, symbol): symbol for symbol in union_symbols}
        for fut in as_completed(futures):
            symbol, minute_df = fut.result()
            code = symbol[-6:]
            stock_tail_by_code[code] = extract_tail_return_stock(minute_df)

    index_tail = extract_tail_return_index(fetch_index_5m())
    index_tail = index_tail[index_tail["date"] <= pd.Timestamp(close_df.index[-1])]

    exact_df = compute_recent_exact(
        close_df=close_df,
        result=result,
        recent_days=recent_days[recent_days <= pd.Timestamp(close_df.index[-1])],
        effective_members_by_day=effective_members_by_day,
        stock_tail_by_code=stock_tail_by_code,
        index_tail=index_tail,
    )
    exact_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")

    summary, daily_prob_df = estimate_last_year_probability(close_df, result, exact_df)
    payload = {
        "method": {
            "exact_recent_window": "recent days where 5-minute tail data is available for both basket and CSI1000",
            "estimate_last_year": "project empirical recent tail 10-minute return pairs onto last year's daily signal boundaries",
            "tail_window": "14:50 to 15:00",
            "recent_exact_days": int(len(exact_df)),
        },
        "recent_exact": {
            "start_date": None if exact_df.empty else str(exact_df["date"].min()),
            "end_date": None if exact_df.empty else str(exact_df["date"].max()),
            "days": int(len(exact_df)),
            "jitter_days": int(exact_df["jitter"].sum()) if len(exact_df) else 0,
            "jitter_prob": float(exact_df["jitter"].mean()) if len(exact_df) else np.nan,
            "avg_member_count_used": float(exact_df["member_count_used"].mean()) if len(exact_df) else np.nan,
        },
        "last_year_estimate": summary,
        "files": {
            "recent_exact_csv": str(OUTPUT_CSV),
        },
    }
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

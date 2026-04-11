from __future__ import annotations

import json
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning

import analyze_microcap_zz1000_hedge as hedge_mod
import analyze_top100_rebalance_frequency as freq_mod
import fetch_wind_microcap_index as fetch_mod


warnings.filterwarnings("ignore", category=PerformanceWarning)

ROOT = Path(__file__).resolve().parent
OHLC_CACHE_DIR = ROOT / ".microcap_index_cache" / "prices_ohlc"
INDEX_CSV = ROOT / "wind_microcap_top_100_biweekly_16y_cached.csv"
OUTPUT_PREFIX = "microcap_top100_execution_stress_recent5y"

TOP_N = 100
LOOKBACK = 16
YEARS = 5
MAX_WORKERS = 8
HEDGE_AK_SYMBOL = "sh000852"


def load_dates_and_members() -> tuple[pd.DatetimeIndex, dict[pd.Timestamp, list[str]]]:
    trading_dates = freq_mod.load_trading_dates()
    end_date = pd.Timestamp(trading_dates[-1])
    start_date = end_date - pd.DateOffset(years=YEARS)
    trading_dates = trading_dates[trading_dates >= start_date]

    rebalance_dates = fetch_mod.build_rebalance_dates(
        trading_dates=trading_dates,
        switch_date=str(trading_dates[0].date()),
        pre_switch_schedule="biweek_start",
        post_switch_schedule="biweek_start",
    )

    symbols = freq_mod.load_universe()
    _, caps_by_date = freq_mod.load_cache_panels(
        symbols=symbols,
        trading_dates=rebalance_dates,
        cap_dates=rebalance_dates,
        max_workers=MAX_WORKERS,
    )

    member_map: dict[pd.Timestamp, list[str]] = {}
    for dt in rebalance_dates:
        cap_map = caps_by_date.get(pd.Timestamp(dt), {})
        ranked = sorted(cap_map.items(), key=lambda x: x[1])[:TOP_N]
        member_map[pd.Timestamp(dt)] = [symbol for symbol, _ in ranked]
    return trading_dates, member_map


def build_daily_members(
    trading_dates: pd.DatetimeIndex,
    member_map: dict[pd.Timestamp, list[str]],
) -> tuple[dict[pd.Timestamp, list[str]], set[str]]:
    rebalance_set = set(member_map)
    current_members: list[str] = []
    daily_members: dict[pd.Timestamp, list[str]] = {}
    unique_symbols: set[str] = set()

    for i, dt in enumerate(trading_dates):
        if i > 0 and trading_dates[i - 1] in rebalance_set:
            current_members = member_map.get(pd.Timestamp(trading_dates[i - 1]), [])
        daily_members[pd.Timestamp(dt)] = current_members.copy()
        unique_symbols.update(current_members)
    return daily_members, unique_symbols


def fetch_stock_ohlc(symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    OHLC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = OHLC_CACHE_DIR / f"{symbol}.csv"
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)

    if cache_path.exists():
        frame = pd.read_csv(cache_path)
        frame["date"] = pd.to_datetime(frame["date"])
        if not frame.empty and frame["date"].min() <= start_ts and frame["date"].max() >= end_ts:
            return frame[(frame["date"] >= start_ts) & (frame["date"] <= end_ts)].copy()

    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust="",
        )
    except Exception:
        return None
    if df.empty:
        return None

    df = df[["日期", "开盘", "收盘", "最高", "最低"]].copy()
    df.columns = ["date", "open", "close", "high", "low"]
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "close", "high", "low"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna().sort_values("date")
    df.to_csv(cache_path, index=False, encoding="utf-8")
    return df


def load_stock_ohlc_batch(symbols: set[str], start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(fetch_stock_ohlc, symbol, start_date, end_date): symbol for symbol in sorted(symbols)
        }
        for fut in as_completed(futures):
            symbol = futures[fut]
            df = fut.result()
            if df is not None and not df.empty:
                out[symbol] = df
    return out


def prepare_stock_ratio_cache(stock_data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for symbol, df in stock_data.items():
        work = df.copy().sort_values("date")
        work["prev_close"] = work["close"].shift(1)
        work["ret_cc"] = work["close"] / work["prev_close"] - 1.0
        work["ret_open_pc"] = work["open"] / work["prev_close"] - 1.0
        work["ret_high_pc"] = work["high"] / work["prev_close"] - 1.0
        work["ret_low_pc"] = work["low"] / work["prev_close"] - 1.0
        work["ret_entry_open"] = work["close"] / work["open"] - 1.0
        work["ret_entry_high"] = work["close"] / work["high"] - 1.0
        work["ret_exit_open"] = work["open"] / work["prev_close"] - 1.0
        work["ret_exit_low"] = work["low"] / work["prev_close"] - 1.0
        out[symbol] = work.set_index("date")
    return out


def fetch_hedge_ohlc(start_date: str, end_date: str) -> pd.DataFrame:
    df = ak.stock_zh_index_daily_em(symbol=HEDGE_AK_SYMBOL)
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= pd.Timestamp(start_date)) & (df["date"] <= pd.Timestamp(end_date))].copy()
    df = df[["date", "open", "close", "high", "low"]].copy().sort_values("date")
    for col in ["open", "close", "high", "low"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["prev_close"] = df["close"].shift(1)
    df["ret_cc"] = df["close"] / df["prev_close"] - 1.0
    df["ret_entry_open"] = df["close"] / df["open"] - 1.0
    df["ret_entry_low"] = df["close"] / df["low"] - 1.0
    df["ret_exit_open"] = df["open"] / df["prev_close"] - 1.0
    df["ret_exit_high"] = df["high"] / df["prev_close"] - 1.0
    return df.set_index("date")


def build_basket_return_table(
    trading_dates: pd.DatetimeIndex,
    daily_members: dict[pd.Timestamp, list[str]],
    stock_ratio_cache: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for dt in trading_dates:
        members = daily_members.get(pd.Timestamp(dt), [])
        if not members:
            rows.append(
                {
                    "date": dt,
                    "member_count": 0,
                    "ret_cc": np.nan,
                    "ret_entry_open": np.nan,
                    "ret_entry_high": np.nan,
                    "ret_exit_open": np.nan,
                    "ret_exit_low": np.nan,
                }
            )
            continue

        values: dict[str, list[float]] = {
            "ret_cc": [],
            "ret_entry_open": [],
            "ret_entry_high": [],
            "ret_exit_open": [],
            "ret_exit_low": [],
        }
        valid_count = 0
        for symbol in members:
            df = stock_ratio_cache.get(symbol)
            if df is None or pd.Timestamp(dt) not in df.index:
                continue
            row = df.loc[pd.Timestamp(dt)]
            if pd.isna(row["prev_close"]):
                continue
            valid_count += 1
            for key in values:
                val = row[key]
                if pd.notna(val):
                    values[key].append(float(val))

        rows.append(
            {
                "date": dt,
                "member_count": valid_count,
                "ret_cc": np.mean(values["ret_cc"]) if values["ret_cc"] else np.nan,
                "ret_entry_open": np.mean(values["ret_entry_open"]) if values["ret_entry_open"] else np.nan,
                "ret_entry_high": np.mean(values["ret_entry_high"]) if values["ret_entry_high"] else np.nan,
                "ret_exit_open": np.mean(values["ret_exit_open"]) if values["ret_exit_open"] else np.nan,
                "ret_exit_low": np.mean(values["ret_exit_low"]) if values["ret_exit_low"] else np.nan,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def build_signal_frame(trading_dates: pd.DatetimeIndex) -> pd.DataFrame:
    microcap = pd.read_csv(INDEX_CSV, usecols=["date", "close"])
    microcap["date"] = pd.to_datetime(microcap["date"])
    microcap = microcap.set_index("date")["close"].rename("microcap").astype(float)

    hedge = pd.read_csv(hedge_mod.DEFAULT_PANEL, usecols=["date", hedge_mod.DEFAULT_HEDGE_COLUMN])
    hedge["date"] = pd.to_datetime(hedge["date"])
    hedge = hedge.set_index("date")[hedge_mod.DEFAULT_HEDGE_COLUMN].rename("hedge").astype(float)

    close_df = pd.concat([microcap, hedge], axis=1).sort_index().dropna()
    close_df = close_df.loc[close_df.index.isin(trading_dates)].copy()
    close_df["microcap_mom"] = hedge_mod.calc_momentum(close_df["microcap"], LOOKBACK)
    close_df["hedge_mom"] = hedge_mod.calc_momentum(close_df["hedge"], LOOKBACK)
    close_df["signal"] = (close_df["microcap_mom"] > close_df["hedge_mom"]).astype(bool)
    valid = close_df[["microcap_mom", "hedge_mom"]].notna().all(axis=1)
    close_df = close_df.loc[valid[valid].index.min():].copy()
    close_df["target_today"] = close_df["signal"].shift(1, fill_value=False).astype(bool)
    close_df["target_prev"] = close_df["target_today"].shift(1, fill_value=False).astype(bool)
    return close_df


def run_scenarios(signal_df: pd.DataFrame, basket_df: pd.DataFrame, hedge_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    nav_df = pd.DataFrame(index=signal_df.index)

    for scenario in ["base_close_to_close", "t_plus_1_open", "worst_high_low"]:
        rets = []
        for dt, row in signal_df.iterrows():
            if dt not in basket_df.index or dt not in hedge_df.index:
                rets.append(np.nan)
                continue

            b = basket_df.loc[dt]
            h = hedge_df.loc[dt]
            target_prev = bool(row["target_prev"])
            target_today = bool(row["target_today"])

            if scenario == "base_close_to_close":
                ret = (b["ret_cc"] - h["ret_cc"] - hedge_mod.DEFAULT_FUTURES_DRAG) if target_today else 0.0
            elif scenario == "t_plus_1_open":
                if (not target_prev) and (not target_today):
                    ret = 0.0
                elif (not target_prev) and target_today:
                    ret = b["ret_entry_open"] - h["ret_entry_open"] - hedge_mod.DEFAULT_FUTURES_DRAG
                elif target_prev and target_today:
                    ret = b["ret_cc"] - h["ret_cc"] - hedge_mod.DEFAULT_FUTURES_DRAG
                else:
                    ret = b["ret_exit_open"] - h["ret_exit_open"]
            else:
                if (not target_prev) and (not target_today):
                    ret = 0.0
                elif (not target_prev) and target_today:
                    ret = b["ret_entry_high"] - h["ret_entry_low"] - hedge_mod.DEFAULT_FUTURES_DRAG
                elif target_prev and target_today:
                    ret = b["ret_cc"] - h["ret_cc"] - hedge_mod.DEFAULT_FUTURES_DRAG
                else:
                    ret = b["ret_exit_low"] - h["ret_exit_high"]

            rets.append(float(ret) if pd.notna(ret) else np.nan)

        ret_s = pd.Series(rets, index=signal_df.index, dtype=float).dropna()
        nav_s = (1.0 + ret_s).cumprod()
        nav_df[scenario] = nav_s
        metrics = hedge_mod.calc_metrics(ret_s)
        out = {
            "scenario": scenario,
            "annual": float(metrics.annual),
            "max_dd": float(metrics.max_dd),
            "sharpe": float(metrics.sharpe),
            "vol": float(metrics.vol),
            "total_return": float(metrics.total_return),
        }
        last_date = ret_s.index[-1]
        for yrs in [1, 3, 5]:
            part = ret_s.loc[ret_s.index >= last_date - pd.DateOffset(years=yrs)]
            m = hedge_mod.calc_metrics(part)
            out[f"annual_{yrs}y"] = float(m.annual)
            out[f"max_dd_{yrs}y"] = float(m.max_dd)
            out[f"sharpe_{yrs}y"] = float(m.sharpe)
        rows.append(out)
    return pd.DataFrame(rows), nav_df


def main() -> None:
    trading_dates, member_map = load_dates_and_members()
    daily_members, unique_symbols = build_daily_members(trading_dates, member_map)

    start_date = str(trading_dates[0].date())
    end_date = str(trading_dates[-1].date())
    stock_ohlc = load_stock_ohlc_batch(unique_symbols, start_date=start_date, end_date=end_date)
    stock_ratio_cache = prepare_stock_ratio_cache(stock_ohlc)
    basket_df = build_basket_return_table(trading_dates, daily_members, stock_ratio_cache)
    hedge_df = fetch_hedge_ohlc(start_date=start_date, end_date=end_date)
    signal_df = build_signal_frame(trading_dates)
    signal_df = signal_df.loc[signal_df.index.isin(basket_df.index) & signal_df.index.isin(hedge_df.index)].copy()

    summary_df, nav_df = run_scenarios(signal_df, basket_df, hedge_df)
    summary_df = summary_df.sort_values("sharpe", ascending=False).reset_index(drop=True)

    summary_path = ROOT / f"{OUTPUT_PREFIX}.csv"
    nav_path = ROOT / f"{OUTPUT_PREFIX}_nav.csv"
    meta_path = ROOT / f"{OUTPUT_PREFIX}.json"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8")
    nav_df.reset_index().rename(columns={"index": "date"}).to_csv(nav_path, index=False, encoding="utf-8")

    payload = {
        "strategy": "top100_biweekly_mom16_execution_stress_recent5y",
        "window_start": start_date,
        "window_end": end_date,
        "top_n": TOP_N,
        "lookback": LOOKBACK,
        "unique_symbols_with_ohlc": int(len(stock_ohlc)),
        "unique_symbols_needed": int(len(unique_symbols)),
        "scenarios": summary_df.to_dict(orient="records"),
        "notes": {
            "base_close_to_close": "Idealized close-to-close daily execution, same as standard close-bar backtest.",
            "t_plus_1_open": "Signal decided at T close, executed at T+1 open.",
            "worst_high_low": "Stress test: long leg enters at day high and exits at day low; hedge leg enters short at day low and exits cover at day high.",
            "scope": "Stress test focuses on signal execution timing. Constituent rotation is still approximated from the reconstructed Top100 basket.",
        },
    }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(summary_df.to_string(index=False))
    print(f"saved {summary_path.name}")
    print(f"saved {nav_path.name}")
    print(f"saved {meta_path.name}")


if __name__ == "__main__":
    main()

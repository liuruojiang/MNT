from __future__ import annotations

import argparse
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import akshare as ak
import numpy as np
import pandas as pd
import requests


END_DATE = pd.Timestamp("2026-05-08")
OUTPUT_DIR = Path("outputs")

ASSETS = {
    "159915.SZ": "CYB100_ETF",
    "159941.SZ": "NASDAQ_ETF",
    "513030.SH": "GERMANY_ETF",
    "513520.SH": "NIKKEI_ETF",
    "159985.SZ": "SOYMEAL_ETF",
    "518880.SH": "GOLD_ETF",
}

LOOKBACK = 25
TRADING_DAYS = 252
SCORE_MIN = 0.0
SCORE_MAX = 5.0
STOP_DD = 0.05
COOLDOWN_TRADING_DAYS = 5
DEFAULT_ONE_WAY_COST = 0.001
DEFAULT_VOL_WINDOW = 80
DEFAULT_MAX_LEV = 1.5


@dataclass(frozen=True)
class RunConfig:
    source: Literal["sina", "eastmoney"]
    one_way_cost: float
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    output_tag: str
    target_vols: tuple[float, ...]
    vol_window: int
    max_lev: float


def sina_symbol(code: str) -> str:
    ticker, suffix = code.split(".")
    if suffix == "SZ":
        return f"sz{ticker}"
    if suffix == "SH":
        return f"sh{ticker}"
    raise ValueError(f"Unsupported suffix: {code}")


def eastmoney_market_id(code: str) -> str:
    ticker, suffix = code.split(".")
    if suffix == "SZ":
        return f"0.{ticker}"
    if suffix == "SH":
        return f"1.{ticker}"
    raise ValueError(f"Unsupported suffix: {code}")


def normalize_code(raw: str) -> str:
    if "." in raw:
        ticker, suffix = raw.split(".", 1)
        suffix = suffix.upper()
        if suffix in {"SH", "SS"}:
            return f"{ticker}.SH"
        if suffix == "SZ":
            return f"{ticker}.SZ"
    if raw.startswith(("51", "58")):
        return f"{raw}.SH"
    return f"{raw}.SZ"


def load_sina_close(codes: list[str], end_date: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    series = []
    sources = []
    for code in codes:
        symbol = sina_symbol(code)
        df = ak.fund_etf_hist_sina(symbol=symbol)
        if df.empty:
            raise RuntimeError(f"Sina returned no rows for {code} / {symbol}")
        close = df[["date", "close"]].copy()
        close["date"] = pd.to_datetime(close["date"])
        close = close.set_index("date")["close"].astype(float).sort_index()
        close = close.loc[:end_date]
        close.name = code
        series.append(close)
        non_na = close.dropna()
        sources.append(
            {
                "code": code,
                "name": ASSETS[code],
                "source": "akshare.fund_etf_hist_sina raw close",
                "adjustment": "raw/unadjusted as served by Sina",
                "first": non_na.index.min().date().isoformat(),
                "last": non_na.index.max().date().isoformat(),
                "rows": int(non_na.shape[0]),
            }
        )
    return pd.concat(series, axis=1).sort_index(), pd.DataFrame(sources)


def load_eastmoney_close(codes: list[str], end_date: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    series = []
    sources = []
    for code in codes:
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": "101",
            "fqt": "1",
            "beg": "20100101",
            "end": end_date.strftime("%Y%m%d"),
            "secid": eastmoney_market_id(code),
        }
        last_error = None
        data = None
        for attempt in range(1, 4):
            try:
                response = requests.get(url, params=params, timeout=20)
                response.raise_for_status()
                payload = response.json()
                data = (payload.get("data") or {}).get("klines") or []
                if data:
                    break
            except Exception as exc:  # noqa: BLE001 - record provider failure details.
                last_error = exc
            time.sleep(1.5 * attempt)
        if not data:
            raise RuntimeError(f"Eastmoney returned no rows for {code}; last_error={last_error}")
        rows = [item.split(",") for item in data]
        df = pd.DataFrame(rows)
        df.columns = [
            "date",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "amount",
            "amplitude",
            "pct_change",
            "px_change",
            "turnover_rate",
        ]
        close = df[["date", "close"]].copy()
        close["date"] = pd.to_datetime(close["date"])
        close = close.set_index("date")["close"].astype(float).sort_index()
        close = close.loc[:end_date]
        close.name = code
        series.append(close)
        non_na = close.dropna()
        sources.append(
            {
                "code": code,
                "name": ASSETS[code],
                "source": "Eastmoney push2his kline",
                "adjustment": "qfq/front-adjusted",
                "first": non_na.index.min().date().isoformat(),
                "last": non_na.index.max().date().isoformat(),
                "rows": int(non_na.shape[0]),
            }
        )
    return pd.concat(series, axis=1).sort_index(), pd.DataFrame(sources)


def load_close(config: RunConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    codes = list(ASSETS)
    if config.source == "sina":
        return load_sina_close(codes, config.end_date)
    if config.source == "eastmoney":
        return load_eastmoney_close(codes, config.end_date)
    raise ValueError(f"Unsupported source: {config.source}")


def weighted_slope_score(window: pd.Series) -> float:
    score, _r2 = weighted_slope_score_and_r2(window)
    return score


def weighted_slope_score_and_r2(window: pd.Series) -> tuple[float, float]:
    values = window.dropna().astype(float)
    if len(values) != LOOKBACK or (values <= 0).any():
        return math.nan, math.nan
    y = np.log(values.to_numpy())
    x = np.arange(len(y), dtype=float)
    weights = np.arange(1, len(y) + 1, dtype=float)
    slope, intercept = np.polyfit(x, y, 1, w=np.sqrt(weights))
    fitted = slope * x + intercept
    y_bar = float(np.average(y, weights=weights))
    ss_tot = float(np.sum(weights * (y - y_bar) ** 2))
    if ss_tot <= 0:
        return math.nan, math.nan
    ss_res = float(np.sum(weights * (y - fitted) ** 2))
    r2 = max(0.0, 1.0 - ss_res / ss_tot)
    score = math.exp(float(slope) * TRADING_DAYS) - 1.0
    return score, r2


def calc_scores(
    prices: pd.DataFrame,
    idx: int,
    r2_threshold: float | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    scores = {}
    r2_values = {}
    for code in ASSETS:
        window = prices[code].iloc[idx - LOOKBACK + 1 : idx + 1]
        score, r2 = weighted_slope_score_and_r2(window)
        if not math.isnan(r2):
            r2_values[code] = r2
        passes_r2 = r2_threshold is None or (not math.isnan(r2) and r2 >= r2_threshold)
        if SCORE_MIN < score < SCORE_MAX and passes_r2:
            scores[code] = score
    return scores, r2_values


def run_subd(
    prices: pd.DataFrame,
    config: RunConfig,
    r2_threshold: float | None = None,
) -> pd.DataFrame:
    prices = prices.loc[: config.end_date].copy()
    dates = prices.index
    position = "CASH"
    nav = 1.0
    trade_count = 0
    stop_count = 0
    high_watermark: dict[str, float] = {}
    cooldown_until_idx: dict[str, int] = {}
    rows = []

    for idx, date in enumerate(dates):
        prev_position = position
        gross_return = 0.0
        if idx > 0 and prev_position != "CASH":
            prev_px = prices.iloc[idx - 1].get(prev_position, np.nan)
            cur_px = prices.iloc[idx].get(prev_position, np.nan)
            if pd.notna(prev_px) and pd.notna(cur_px) and prev_px > 0:
                gross_return = float(cur_px / prev_px - 1.0)
        nav *= 1.0 + gross_return

        stop_triggered = False
        target_position = prev_position
        if prev_position != "CASH":
            cur_px = prices.iloc[idx].get(prev_position, np.nan)
            if pd.notna(cur_px):
                prev_high = high_watermark.get(prev_position, float(cur_px))
                high = max(prev_high, float(cur_px))
                high_watermark[prev_position] = high
                if float(cur_px) <= high * (1.0 - STOP_DD):
                    stop_triggered = True
                    target_position = "CASH"
                    cooldown_until_idx[prev_position] = idx + COOLDOWN_TRADING_DAYS
                    stop_count += 1

        scores: dict[str, float] = {}
        r2_values: dict[str, float] = {}
        if not stop_triggered and idx >= LOOKBACK - 1:
            raw_scores, r2_values = calc_scores(prices, idx, r2_threshold=r2_threshold)
            scores = {
                code: score
                for code, score in raw_scores.items()
                if cooldown_until_idx.get(code, -1) < idx
            }
            target_position = max(scores, key=scores.get) if scores else "CASH"

        turnover = 0.0
        if target_position != prev_position:
            trade_count += 1
            if prev_position != "CASH":
                turnover += 1.0
            if target_position != "CASH":
                turnover += 1.0
                entry_px = prices.iloc[idx].get(target_position, np.nan)
                if pd.notna(entry_px):
                    high_watermark[target_position] = float(entry_px)
        cost = turnover * config.one_way_cost
        if cost:
            nav *= 1.0 - cost

        net_return = nav / rows[-1]["nav"] - 1.0 if rows else nav - 1.0
        score_row = {f"score_{code}": scores.get(code, math.nan) for code in ASSETS}
        r2_row = {f"r2_{code}": r2_values.get(code, math.nan) for code in ASSETS}
        rows.append(
            {
                "date": date,
                "r2_threshold": r2_threshold,
                "position_before": prev_position,
                "position": target_position,
                "gross_return": gross_return,
                "turnover": turnover,
                "cost": cost,
                "return": net_return,
                "nav": nav,
                "stop_triggered": stop_triggered,
                "trade_count": trade_count,
                "stop_count": stop_count,
                **score_row,
                **r2_row,
            }
        )
        position = target_position

    return pd.DataFrame(rows).set_index("date")


def max_drawdown(nav: pd.Series) -> float:
    return float((nav / nav.cummax() - 1.0).min())


def summarize_curve(curve: pd.DataFrame, start: pd.Timestamp, label: str) -> dict[str, object]:
    sub = curve.loc[curve.index >= start].copy()
    if sub.empty:
        raise RuntimeError(f"No data for window {label}")
    nav = sub["nav"] / float(sub["nav"].iloc[0])
    ret = nav.pct_change().fillna(0.0)
    years = len(sub) / TRADING_DAYS
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else math.nan
    vol = float(ret.std(ddof=0) * math.sqrt(TRADING_DAYS))
    sharpe = float(ret.mean() / ret.std(ddof=0) * math.sqrt(TRADING_DAYS)) if ret.std(ddof=0) > 0 else math.nan
    max_lev = float(sub["max_lev"].iloc[0]) if "max_lev" in sub else DEFAULT_MAX_LEV
    return {
        "window": label,
        "start": sub.index[0].date().isoformat(),
        "end": sub.index[-1].date().isoformat(),
        "days": int(len(sub)),
        "total": float(nav.iloc[-1] - 1.0),
        "cagr": cagr,
        "maxdd": max_drawdown(nav),
        "sharpe": sharpe,
        "vol": vol,
        "cash_days": int((sub["position"] == "CASH").sum()),
        "trades": int(sub["trade_count"].iloc[-1] - sub["trade_count"].iloc[0]),
        "stop_exits": int(sub["stop_count"].iloc[-1] - sub["stop_count"].iloc[0]),
        "cost_sum": float(sub["cost"].sum()),
        "turnover_sum": float(sub["turnover"].sum()),
        "avg_weight": float(sub["weight"].mean()) if "weight" in sub else 1.0,
        "max_weight": float(sub["weight"].max()) if "weight" in sub else 1.0,
        "pct_at_max_lev": float((sub["weight"] >= max_lev - 1e-12).mean()) if "weight" in sub else 0.0,
        "pct_below_1x": float((sub["weight"] < 1.0 - 1e-12).mean()) if "weight" in sub else 0.0,
    }


def apply_target_vol_overlay(
    base_curve: pd.DataFrame,
    target_vol: float,
    vol_window: int,
    max_lev: float,
) -> pd.DataFrame:
    result = base_curve.copy()
    base_ret = result["return"].astype(float).fillna(0.0)
    realized_vol = base_ret.rolling(vol_window, min_periods=vol_window).std(ddof=0) * math.sqrt(TRADING_DAYS)
    scale = (target_vol / realized_vol).replace([np.inf, -np.inf], np.nan)
    scale = scale.shift(1).clip(lower=0.0, upper=max_lev).fillna(1.0)
    result["base_return"] = base_ret
    result["base_nav"] = result["nav"]
    result["realized_vol"] = realized_vol
    result["weight"] = scale
    result["return"] = base_ret * scale
    result["gross_return"] = result["gross_return"].astype(float) * scale
    result["cost"] = result["cost"].astype(float) * scale
    result["nav"] = (1.0 + result["return"]).cumprod()
    result["target_vol"] = target_vol
    result["vol_window"] = vol_window
    result["max_lev"] = max_lev
    return result


def target_vol_label(target_vol: float) -> str:
    return f"tv{int(round(target_vol * 100)):02d}"


def r2_filter_label(r2_threshold: float | None) -> str:
    if r2_threshold is None:
        return "no_r2_filter"
    return f"r2_ge_{str(f'{r2_threshold:.2f}').replace('.', 'p')}"


def write_r2_filter_outputs(
    prices: pd.DataFrame,
    sources: pd.DataFrame,
    config: RunConfig,
    r2_thresholds: tuple[float, ...],
    target_vol: float,
) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    tv_label = target_vol_label(target_vol)
    prefix = f"subd_six_etf_weighted_slope_{config.source}_{config.output_tag}_{tv_label}_r2_filter"
    windows = {
        "10Y": config.end_date - pd.DateOffset(years=10),
        "max_all6": max(prices[code].dropna().index.min() for code in ASSETS),
        "article_2020": pd.Timestamp("2020-01-02"),
        "5Y": config.end_date - pd.DateOffset(years=5),
        "3Y": config.end_date - pd.DateOffset(years=3),
        "1Y": config.end_date - pd.DateOffset(years=1),
    }
    scan_thresholds: tuple[float | None, ...] = (None, *r2_thresholds)
    curves = []
    summary_rows = []
    yearly_rows = []
    holding_rows = []

    for threshold in scan_thresholds:
        label = r2_filter_label(threshold)
        base_curve = run_subd(prices, config, r2_threshold=threshold)
        tv_curve = apply_target_vol_overlay(base_curve, target_vol, config.vol_window, config.max_lev)
        tagged_curve = tv_curve.copy()
        tagged_curve.insert(0, "r2_filter_label", label)
        tagged_curve.insert(1, "r2_threshold_value", threshold)
        curves.append(tagged_curve)

        for window_label, start in windows.items():
            row = summarize_curve(tv_curve, start, window_label)
            summary_rows.append(
                {
                    "r2_filter_label": label,
                    "r2_threshold": threshold,
                    "target_vol_label": tv_label,
                    "target_vol": target_vol,
                    "vol_window": config.vol_window,
                    "max_lev": config.max_lev,
                    **row,
                }
            )

        yearly = yearly_returns(tv_curve, pd.Timestamp("2020-01-02"))
        yearly.insert(0, "r2_filter_label", label)
        yearly.insert(1, "r2_threshold", threshold)
        yearly.insert(2, "target_vol_label", tv_label)
        yearly.insert(3, "target_vol", target_vol)
        yearly_rows.extend(yearly.to_dict("records"))

        holding = holding_distribution(tv_curve, pd.Timestamp("2020-01-02"))
        holding.insert(0, "r2_filter_label", label)
        holding.insert(1, "r2_threshold", threshold)
        holding.insert(2, "target_vol_label", tv_label)
        holding.insert(3, "target_vol", target_vol)
        holding_rows.extend(holding.to_dict("records"))

    sources.to_csv(OUTPUT_DIR / f"{prefix}_sources.csv", index=False, encoding="utf-8-sig")
    data_quality(prices).to_csv(OUTPUT_DIR / f"{prefix}_data_quality.csv", index=False, encoding="utf-8-sig")
    pd.concat(curves).to_csv(OUTPUT_DIR / f"{prefix}_daily.csv", encoding="utf-8-sig")
    summary = pd.DataFrame(summary_rows)
    yearly = pd.DataFrame(yearly_rows)
    holding = pd.DataFrame(holding_rows)
    summary.to_csv(OUTPUT_DIR / f"{prefix}_summary.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(OUTPUT_DIR / f"{prefix}_yearly.csv", index=False, encoding="utf-8-sig")
    holding.to_csv(OUTPUT_DIR / f"{prefix}_holding.csv", index=False, encoding="utf-8-sig")

    print("\nR2 FILTER TARGET VOL SUMMARY")
    print(summary.to_string(index=False))
    print("\nR2 FILTER YEARLY FROM 2020")
    print(yearly.to_string(index=False))
    print(f"\nWROTE {OUTPUT_DIR / (prefix + '_summary.csv')}")


def yearly_returns(curve: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    sub = curve.loc[curve.index >= start].copy()
    ret = sub["nav"].pct_change().fillna(0.0)
    rows = []
    for year, part in ret.groupby(ret.index.year):
        rows.append({"year": int(year), "return": float((1.0 + part).prod() - 1.0)})
    return pd.DataFrame(rows)


def holding_distribution(curve: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    sub = curve.loc[curve.index >= start].copy()
    total = len(sub)
    invested = int((sub["position"] != "CASH").sum())
    rows = []
    for code, name in ASSETS.items():
        days = int((sub["position"] == code).sum())
        rows.append(
            {
                "position": code,
                "name": name,
                "days": days,
                "full_sample_pct": days / total if total else math.nan,
                "invested_days_pct": days / invested if invested else math.nan,
            }
        )
    cash_days = int((sub["position"] == "CASH").sum())
    rows.append(
        {
            "position": "CASH",
            "name": "CASH",
            "days": cash_days,
            "full_sample_pct": cash_days / total if total else math.nan,
            "invested_days_pct": math.nan,
        }
    )
    return pd.DataFrame(rows)


def data_quality(prices: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ret = prices.pct_change(fill_method=None)
    for code in prices.columns:
        series = prices[code].dropna()
        daily = ret[code].dropna()
        max_abs_date = daily.abs().idxmax() if not daily.empty else pd.NaT
        rows.append(
            {
                "code": code,
                "name": ASSETS[code],
                "first": series.index.min().date().isoformat(),
                "last": series.index.max().date().isoformat(),
                "rows": int(series.shape[0]),
                "missing_in_joined_calendar": int(prices[code].isna().sum()),
                "max_abs_daily_return": float(daily.abs().max()) if not daily.empty else math.nan,
                "max_abs_daily_return_date": max_abs_date.date().isoformat() if pd.notna(max_abs_date) else "",
                "large_move_gt_30pct_count": int((daily.abs() > 0.30).sum()),
            }
        )
    return pd.DataFrame(rows)


def write_outputs(prices: pd.DataFrame, sources: pd.DataFrame, curve: pd.DataFrame, config: RunConfig) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    prefix = f"subd_six_etf_weighted_slope_{config.source}_{config.output_tag}"
    windows = {
        "10Y": config.end_date - pd.DateOffset(years=10),
        "max_all6": max(prices[code].dropna().index.min() for code in ASSETS),
        "article_2020": pd.Timestamp("2020-01-02"),
        "5Y": config.end_date - pd.DateOffset(years=5),
        "3Y": config.end_date - pd.DateOffset(years=3),
        "1Y": config.end_date - pd.DateOffset(years=1),
    }
    summary = pd.DataFrame([summarize_curve(curve, start, label) for label, start in windows.items()])
    yearly = yearly_returns(curve, pd.Timestamp("2020-01-02"))
    holding = holding_distribution(curve, pd.Timestamp("2020-01-02"))
    quality = data_quality(prices)
    compare_curves = []
    compare_summary_rows = []
    compare_yearly_rows = []

    base_curve = curve.copy()
    base_curve["base_return"] = base_curve["return"]
    base_curve["base_nav"] = base_curve["nav"]
    base_curve["realized_vol"] = math.nan
    base_curve["weight"] = 1.0
    base_curve["target_vol"] = math.nan
    base_curve["vol_window"] = config.vol_window
    base_curve["max_lev"] = 1.0
    tagged_base_curve = base_curve.copy()
    tagged_base_curve.insert(0, "target_vol_label", "no_target_vol")
    compare_curves.append(tagged_base_curve)
    for window_label, start in windows.items():
        row = summarize_curve(base_curve, start, window_label)
        compare_summary_rows.append(
            {
                "target_vol_label": "no_target_vol",
                "target_vol": math.nan,
                "vol_window": config.vol_window,
                "max_lev": 1.0,
                **row,
            }
        )
    base_yearly = yearly_returns(base_curve, pd.Timestamp("2020-01-02"))
    base_yearly.insert(0, "target_vol_label", "no_target_vol")
    base_yearly.insert(1, "target_vol", math.nan)
    compare_yearly_rows.extend(base_yearly.to_dict("records"))

    for tv in config.target_vols:
        tv_curve = apply_target_vol_overlay(curve, tv, config.vol_window, config.max_lev)
        tv_label = target_vol_label(tv)
        tagged_curve = tv_curve.copy()
        tagged_curve.insert(0, "target_vol_label", tv_label)
        compare_curves.append(tagged_curve)
        for window_label, start in windows.items():
            row = summarize_curve(tv_curve, start, window_label)
            compare_summary_rows.append(
                {
                    "target_vol_label": tv_label,
                    "target_vol": tv,
                    "vol_window": config.vol_window,
                    "max_lev": config.max_lev,
                    **row,
                }
            )
        tv_yearly = yearly_returns(tv_curve, pd.Timestamp("2020-01-02"))
        tv_yearly.insert(0, "target_vol_label", tv_label)
        tv_yearly.insert(1, "target_vol", tv)
        compare_yearly_rows.extend(tv_yearly.to_dict("records"))
    compare_summary = pd.DataFrame(compare_summary_rows)
    compare_yearly = pd.DataFrame(compare_yearly_rows)

    sources.to_csv(OUTPUT_DIR / f"{prefix}_sources.csv", index=False, encoding="utf-8-sig")
    quality.to_csv(OUTPUT_DIR / f"{prefix}_data_quality.csv", index=False, encoding="utf-8-sig")
    curve.to_csv(OUTPUT_DIR / f"{prefix}_daily.csv", encoding="utf-8-sig")
    summary.to_csv(OUTPUT_DIR / f"{prefix}_summary.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(OUTPUT_DIR / f"{prefix}_yearly.csv", index=False, encoding="utf-8-sig")
    holding.to_csv(OUTPUT_DIR / f"{prefix}_holding.csv", index=False, encoding="utf-8-sig")
    if compare_curves:
        pd.concat(compare_curves).to_csv(OUTPUT_DIR / f"{prefix}_targetvol_daily.csv", encoding="utf-8-sig")
        compare_summary.to_csv(OUTPUT_DIR / f"{prefix}_targetvol_summary.csv", index=False, encoding="utf-8-sig")
        compare_yearly.to_csv(OUTPUT_DIR / f"{prefix}_targetvol_yearly.csv", index=False, encoding="utf-8-sig")

    print("SOURCES")
    print(sources.to_string(index=False))
    print("\nDATA QUALITY")
    print(quality.to_string(index=False))
    print("\nWINDOW SUMMARY")
    print(summary.to_string(index=False))
    print("\nYEARLY FROM 2020")
    print(yearly.to_string(index=False))
    print("\nHOLDING FROM 2020")
    print(holding.to_string(index=False))
    if not compare_summary.empty:
        print("\nTARGET VOL SUMMARY")
        print(compare_summary.to_string(index=False))
        print("\nTARGET VOL YEARLY FROM 2020")
        print(compare_yearly.to_string(index=False))
    print(f"\nWROTE {OUTPUT_DIR / (prefix + '_summary.csv')}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sub-D six ETF weighted slope baseline research.")
    parser.add_argument("--source", choices=["sina", "eastmoney"], default="sina")
    parser.add_argument("--one-way-cost", type=float, default=DEFAULT_ONE_WAY_COST)
    parser.add_argument("--start-date", default="20100101")
    parser.add_argument("--end-date", default=END_DATE.strftime("%Y%m%d"))
    parser.add_argument("--output-tag", default="baseline_20260509")
    parser.add_argument("--target-vols", default="")
    parser.add_argument("--vol-window", type=int, default=DEFAULT_VOL_WINDOW)
    parser.add_argument("--max-lev", type=float, default=DEFAULT_MAX_LEV)
    parser.add_argument("--r2-thresholds", default="")
    parser.add_argument("--r2-target-vol", type=float, default=0.30)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target_vols = tuple(
        float(item.strip())
        for item in args.target_vols.split(",")
        if item.strip()
    )
    r2_thresholds = tuple(
        float(item.strip())
        for item in args.r2_thresholds.split(",")
        if item.strip()
    )
    config = RunConfig(
        source=args.source,
        one_way_cost=float(args.one_way_cost),
        start_date=pd.Timestamp(args.start_date),
        end_date=pd.Timestamp(args.end_date),
        output_tag=args.output_tag,
        target_vols=target_vols,
        vol_window=int(args.vol_window),
        max_lev=float(args.max_lev),
    )
    prices, sources = load_close(config)
    prices = prices.loc[prices.index >= config.start_date]
    curve = run_subd(prices, config)
    write_outputs(prices, sources, curve, config)
    if r2_thresholds:
        write_r2_filter_outputs(
            prices,
            sources,
            config,
            r2_thresholds=r2_thresholds,
            target_vol=float(args.r2_target_vol),
        )


if __name__ == "__main__":
    main()

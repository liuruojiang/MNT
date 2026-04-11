from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd
import requests


ROOT = Path(r"C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略")
V61_DIR = ROOT / "A股美股动量组合策略"
OUT_DIR = Path(__file__).resolve().parent / "outputs_v61_rsrs_replacement"
OUT_DIR.mkdir(exist_ok=True)
V61_DIR = Path(__file__).resolve().parents[2]
if str(V61_DIR) not in sys.path:
    sys.path.insert(0, str(V61_DIR))
from local_data_refresh import refresh_cn_strategy_data, refresh_us_strategy_data


# Sub-A constants from V6.1
CN_COMMISSION = 0.001
CN_RF_ANNUAL = 0.03
CN_TRADING_DAYS = 244
CN_RF_DAILY = (1 + CN_RF_ANNUAL) ** (1 / CN_TRADING_DAYS) - 1
CN_BIAS_N = 60
CN_MOM_DAY = 20
CN_R2_WINDOW = 20
CN_R2_THRESHOLD = 0.3
CN_BOND_CODE = "1.H11077"
CN_TARGET_VOL = 0.20
CN_VOL_WINDOW = 60
CN_MAX_LEV = 1.5
CN_MIN_LEV = 0.1
CN_SCALE_THRESHOLD = 0.10
CN_EQUITY_CODES = ["1.H20955", "0.399606", "1.H00016", "1.H00852", "1.H00905"]
CN_ALL_CODES = CN_EQUITY_CODES + [CN_BOND_CODE]


# Sub-B constants from V6.1
US_ROT_COMMISSION = 0.001
US_TRADING_DAYS = 252
US_ROT_POOL = ["QQQ", "EMXC", "EFA", "GLD", "TLT", "DBC", "BTC-USD"]
US_ROT_FUTURES = {"QQQ", "GLD", "TLT"}
US_ROT_TARGET_VOL = 0.25
US_ROT_MAX_LEV = 2.0
US_ROT_VOL_WINDOW = 40
US_ROT_LB = 160
US_ROT_VOL_LB = 20
US_ROT_MIN_TURNOVER = 0.15
US_ROT_ABS_THRESHOLD = 0.0
US_ROT_REBALANCE_THRESHOLD = 1.0
US_ROT_BTC_TICKER = "BTC-USD"
US_ROT_BTC_START = pd.Timestamp("2022-01-01")
US_ROT_BTC_MAX_W = 0.30
US_ROT_EMXC_BT_START = pd.Timestamp("2017-08-01")
US_ROT_VOLREG_ENABLED = True
US_ROT_VOLREG_SHORT_W = 10
US_ROT_VOLREG_LONG_W = 250
US_ROT_VOLREG_THRESHOLD = 2.0


# Canonical RSRS parameters
RSRS_N = 18
RSRS_M = 600


CN_PROXY_MAP = {
    "1.H20955": "sh515100",  # dividend ETF as intraday-shape proxy, anchored to total-return close
    "0.399606": "sz399606",
    "1.H00016": "sh000016",
    "1.H00852": "sh000852",
    "1.H00905": "sh000905",
    "1.H11077": "sh511260",  # 10Y treasury ETF as intraday-shape proxy, anchored to total-return close
}


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Referer": "https://finance.sina.com.cn/",
        }
    )
    return s


def _fetch_sina_cn_ohlc(symbol: str, datalen: int = 10000) -> pd.DataFrame:
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
    )
    r = session().get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        raise ValueError(f"Sina returned no CN OHLC for {symbol}")
    rows = []
    for item in data:
        rows.append(
            {
                "date": pd.Timestamp(item["day"]),
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
            }
        )
    df = pd.DataFrame(rows).set_index("date").sort_index()
    return df[(df["close"] > 0) & (df["high"] >= df["low"])]


def _fetch_yahoo_us_ohlc(ticker: str, start_date: str = "2003-01-01") -> pd.DataFrame:
    start_ts = int(pd.Timestamp(start_date).timestamp())
    end_ts = int((datetime.now() + timedelta(days=30)).timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?period1={start_ts}&period2={end_ts}&interval=1d&includeAdjustedClose=true"
    )
    r = session().get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    result = data["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"]["quote"][0]
    adj = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
    rows = []
    for i, ts in enumerate(timestamps):
        raw_close = quote["close"][i]
        raw_open = quote["open"][i]
        raw_high = quote["high"][i]
        raw_low = quote["low"][i]
        adj_close = adj[i] if i < len(adj) else raw_close
        if raw_close is None or adj_close is None or raw_close == 0:
            continue
        factor = adj_close / raw_close
        row = {
            "date": pd.Timestamp.fromtimestamp(ts).normalize(),
            "open": raw_open * factor if raw_open is not None else np.nan,
            "high": raw_high * factor if raw_high is not None else np.nan,
            "low": raw_low * factor if raw_low is not None else np.nan,
            "close": adj_close,
        }
        rows.append(row)
    df = pd.DataFrame(rows).set_index("date").sort_index()
    df = df.dropna(subset=["close"])
    df = df[(df["high"] >= df["low"]) & (df["close"] > 0)]
    return df


def _load_cn_total_return_close(code: str) -> pd.Series:
    cache_path = V61_DIR / ".cn_official_cache" / f"{code.replace('.', '_')}.csv"
    df = pd.read_csv(cache_path, parse_dates=["date"])
    return df.set_index("date")["close"].astype(float).rename(code)


def _load_us_close_panel() -> pd.DataFrame:
    path = V61_DIR / "mnt_strategy_data_us.csv"
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    keep = ["QQQ", "EFA", "GLD", "TLT", "DBC", "BTC-USD", "BIL", "SPY", "EEM", "EMXC", "EMXC_spliced"]
    cols = [c for c in keep if c in df.columns]
    out = df[cols].astype(float)
    if "EMXC_spliced" in out.columns:
        out["EMXC"] = out["EMXC_spliced"]
    return out


def anchor_ohlc_to_target_close(proxy_ohlc: pd.DataFrame, target_close: pd.Series) -> pd.DataFrame:
    df = proxy_ohlc.join(target_close.rename("target_close"), how="inner")
    df = df.dropna(subset=["open", "high", "low", "close", "target_close"])
    factor = df["target_close"] / df["close"]
    anchored = df[["open", "high", "low", "close"]].mul(factor, axis=0)
    anchored["close"] = df["target_close"]
    anchored["high"] = anchored[["open", "high", "low", "close"]].max(axis=1)
    anchored["low"] = anchored[["open", "high", "low", "close"]].min(axis=1)
    return anchored


def build_cn_inputs() -> tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    refresh_cn_strategy_data(csv_path=V61_DIR / "mnt_strategy_data_cn.csv", verbose=False)
    close_map = {code: _load_cn_total_return_close(code) for code in CN_ALL_CODES}
    cn_close = pd.concat(close_map.values(), axis=1).ffill().dropna()
    proxy_raw = {code: _fetch_sina_cn_ohlc(symbol) for code, symbol in CN_PROXY_MAP.items()}
    cn_ohlc = {code: anchor_ohlc_to_target_close(proxy_raw[code], cn_close[code]) for code in CN_ALL_CODES}
    return cn_close, cn_ohlc


def build_us_inputs() -> tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    refresh_us_strategy_data(csv_path=V61_DIR / "mnt_strategy_data_us.csv", verbose=False)
    us_close = _load_us_close_panel()
    raw = {t: _fetch_yahoo_us_ohlc(t) for t in ["QQQ", "EFA", "GLD", "TLT", "DBC", "BTC-USD", "BIL", "SPY", "EEM", "EMXC"]}
    us_ohlc: Dict[str, pd.DataFrame] = {}
    for ticker in ["QQQ", "EFA", "GLD", "TLT", "DBC", "BTC-USD", "BIL", "SPY"]:
        us_ohlc[ticker] = anchor_ohlc_to_target_close(raw[ticker], us_close[ticker])
    emxc_target = us_close["EMXC"].dropna()
    eem_anchor = anchor_ohlc_to_target_close(raw["EEM"], emxc_target)
    emxc_anchor = anchor_ohlc_to_target_close(raw["EMXC"], emxc_target)
    emxc_combo = eem_anchor.copy()
    if not emxc_anchor.empty:
        switch_mask = emxc_combo.index >= US_ROT_EMXC_BT_START
        emxc_combo.loc[switch_mask] = emxc_anchor.reindex(emxc_combo.index).loc[switch_mask]
        emxc_combo = emxc_combo.combine_first(emxc_anchor)
    us_ohlc["EMXC"] = emxc_combo
    return us_close, us_ohlc


def calc_bias_momentum(close_series: pd.Series, bias_n: int = CN_BIAS_N, mom_day: int = CN_MOM_DAY) -> pd.Series:
    prices = close_series.values.astype(float)
    n = len(prices)
    result = np.full(n, np.nan)
    ma = close_series.rolling(bias_n).mean().values
    total_lookback = bias_n + mom_day - 1
    x = np.arange(mom_day, dtype=float)
    for i in range(total_lookback, n):
        bias_window = np.empty(mom_day)
        valid = True
        for j in range(mom_day):
            idx = i - mom_day + 1 + j
            if np.isnan(ma[idx]) or ma[idx] < 1e-10 or np.isnan(prices[idx]):
                valid = False
                break
            bias_window[j] = prices[idx] / ma[idx]
        if not valid or bias_window[0] < 1e-10:
            continue
        bias_norm = bias_window / bias_window[0]
        slope = np.polyfit(x, bias_norm, 1)[0]
        result[i] = slope * 10000
    return pd.Series(result, index=close_series.index)


def calc_rolling_r2(close_series: pd.Series, window: int = CN_R2_WINDOW) -> pd.Series:
    y = close_series.values.astype(float)
    n = len(y)
    r2 = np.full(n, np.nan)
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    ss_x = ((x - x_mean) ** 2).sum()
    for i in range(window - 1, n):
        y_win = y[i - window + 1 : i + 1]
        if np.any(np.isnan(y_win)):
            continue
        y_mean = y_win.mean()
        ss_y = ((y_win - y_mean) ** 2).sum()
        if ss_y < 1e-12:
            r2[i] = 0.0
            continue
        ss_xy = ((x - x_mean) * (y_win - y_mean)).sum()
        r2[i] = (ss_xy ** 2) / (ss_x * ss_y)
    return pd.Series(r2, index=close_series.index)


def compute_rsrs_score(ohlc: pd.DataFrame, n: int = RSRS_N, m: int = RSRS_M) -> pd.Series:
    highs = ohlc["high"].astype(float).values
    lows = ohlc["low"].astype(float).values
    size = len(ohlc)
    beta = np.full(size, np.nan)
    r2 = np.full(size, np.nan)
    for i in range(n - 1, size):
        y = highs[i - n + 1 : i + 1]
        x = lows[i - n + 1 : i + 1]
        if np.any(np.isnan(x)) or np.any(np.isnan(y)):
            continue
        x_mean = x.mean()
        y_mean = y.mean()
        ss_x = ((x - x_mean) ** 2).sum()
        ss_y = ((y - y_mean) ** 2).sum()
        if ss_x < 1e-12 or ss_y < 1e-12:
            continue
        ss_xy = ((x - x_mean) * (y - y_mean)).sum()
        beta[i] = ss_xy / ss_x
        r2[i] = (ss_xy ** 2) / (ss_x * ss_y)
    beta_s = pd.Series(beta, index=ohlc.index)
    r2_s = pd.Series(r2, index=ohlc.index)
    mean_s = beta_s.rolling(m).mean()
    std_s = beta_s.rolling(m).std(ddof=1).replace(0, np.nan)
    zscore = (beta_s - mean_s) / std_s
    right_skew = zscore * r2_s * beta_s
    return right_skew.rename("rsrs_score")


def run_cn_strategy_baseline(close_df: pd.DataFrame, equity_codes: Iterable[str]) -> pd.DataFrame:
    all_codes = list(equity_codes) + [CN_BOND_CODE]
    bias_dict = {code: calc_bias_momentum(close_df[code]) for code in all_codes}
    r2_dict = {code: calc_rolling_r2(close_df[code]) for code in all_codes}
    start_idx = CN_BIAS_N + CN_MOM_DAY
    holding = "cash"
    rows = []
    for i in range(start_idx, len(close_df)):
        date = close_df.index[i]
        scores = {code: bias_dict[code].iloc[i] for code in all_codes if not np.isnan(bias_dict[code].iloc[i])}
        ideal = "cash"
        if scores:
            best = max(scores, key=scores.get)
            if scores[best] > 0:
                r2_val = r2_dict[best].iloc[i]
                if not np.isnan(r2_val) and r2_val >= CN_R2_THRESHOLD:
                    ideal = best
        target = ideal if ideal != holding else None
        if target is not None:
            old_h = holding
            cost = (1 - CN_COMMISSION) if (old_h == "cash" or target == "cash") else (1 - CN_COMMISSION) ** 2
            if old_h == "cash":
                day_ret = (1 + CN_RF_DAILY) * cost - 1
            else:
                asset_ret = close_df.iloc[i][old_h] / close_df.iloc[i - 1][old_h] - 1
                day_ret = (1 + asset_ret) * cost - 1
            holding = target
        else:
            if holding == "cash":
                day_ret = CN_RF_DAILY
            else:
                day_ret = close_df.iloc[i][holding] / close_df.iloc[i - 1][holding] - 1
        rows.append({"date": date, "return": day_ret, "holding": holding, "is_signal": target is not None})
    df = pd.DataFrame(rows).set_index("date")
    return _apply_cn_vol_scaling(df)


def run_cn_strategy_rsrs(close_df: pd.DataFrame, ohlc_map: Dict[str, pd.DataFrame], equity_codes: Iterable[str]) -> pd.DataFrame:
    all_codes = list(equity_codes) + [CN_BOND_CODE]
    score_df = pd.concat([compute_rsrs_score(ohlc_map[code]).rename(code) for code in all_codes], axis=1).reindex(close_df.index)
    r2_dict = {code: calc_rolling_r2(close_df[code]) for code in all_codes}
    start_idx = CN_BIAS_N + CN_MOM_DAY
    holding = "cash"
    rows = []
    for i in range(start_idx, len(close_df)):
        date = close_df.index[i]
        row = score_df.iloc[i]
        scores = {code: row[code] for code in all_codes if code in row.index and not np.isnan(row[code])}
        ideal = "cash"
        if scores:
            best = max(scores, key=scores.get)
            if scores[best] > 0:
                r2_val = r2_dict[best].iloc[i]
                if not np.isnan(r2_val) and r2_val >= CN_R2_THRESHOLD:
                    ideal = best
        target = ideal if ideal != holding else None
        if target is not None:
            old_h = holding
            cost = (1 - CN_COMMISSION) if (old_h == "cash" or target == "cash") else (1 - CN_COMMISSION) ** 2
            if old_h == "cash":
                day_ret = (1 + CN_RF_DAILY) * cost - 1
            else:
                asset_ret = close_df.iloc[i][old_h] / close_df.iloc[i - 1][old_h] - 1
                day_ret = (1 + asset_ret) * cost - 1
            holding = target
        else:
            if holding == "cash":
                day_ret = CN_RF_DAILY
            else:
                day_ret = close_df.iloc[i][holding] / close_df.iloc[i - 1][holding] - 1
        rows.append({"date": date, "return": day_ret, "holding": holding, "is_signal": target is not None})
    df = pd.DataFrame(rows).set_index("date")
    return _apply_cn_vol_scaling(df)


def _apply_cn_vol_scaling(df: pd.DataFrame) -> pd.DataFrame:
    raw_ret = df["return"].values.copy()
    is_cash = (df["holding"] == "cash").values
    realized_vol = pd.Series(raw_ret, index=df.index).rolling(CN_VOL_WINDOW).std() * np.sqrt(CN_TRADING_DAYS)
    raw_scale = (CN_TARGET_VOL / realized_vol.replace(0, np.nan)).clip(CN_MIN_LEV, CN_MAX_LEV).shift(1)
    if CN_SCALE_THRESHOLD > 0:
        arr = raw_scale.values.copy()
        last = np.nan
        for i in range(len(arr)):
            if np.isnan(arr[i]):
                continue
            if np.isnan(last):
                last = arr[i]
            elif abs(arr[i] - last) >= CN_SCALE_THRESHOLD - 1e-9:
                last = arr[i]
            else:
                arr[i] = last
        raw_scale = pd.Series(arr, index=df.index)
    scale_arr = raw_scale.fillna(1.0).values
    scale_arr[is_cash] = 1.0
    prev_scale = np.concatenate([[scale_arr[0]], scale_arr[:-1]])
    delta_scale = np.abs(scale_arr - prev_scale)
    scale_tc = np.where((~df["is_signal"].values) & ~is_cash, CN_COMMISSION * delta_scale, 0.0)
    out = df.copy()
    out["weight"] = scale_arr
    out["scale_raw"] = raw_scale
    out["realized_vol"] = realized_vol
    out["scale_tc"] = scale_tc
    out["return"] = (1 + raw_ret * scale_arr) * (1 - scale_tc) - 1
    out["nav"] = (1 + out["return"]).cumprod()
    return out


def _us_signal_days(close_df: pd.DataFrame, start_idx: int) -> set[int]:
    week_best: Dict[tuple[int, int], tuple[int, int]] = {}
    for i in range(start_idx, len(close_df)):
        dt = close_df.index[i]
        dow = dt.dayofweek
        if dow > 3:
            continue
        yr, wk, _ = dt.isocalendar()
        key = (int(yr), int(wk))
        if key not in week_best or dow > week_best[key][1]:
            week_best[key] = (i, dow)
    return {v[0] for v in week_best.values()}


def _us_raw_weights(
    score_row: pd.Series,
    vol_row: pd.Series,
    ranking_codes: Iterable[str],
    top_n: int,
    abs_threshold: float,
    prev_risky: Optional[set[str]] = None,
    threshold: float = 1.0,
) -> Dict[str, float]:
    available = {}
    for a in ranking_codes:
        if a in score_row.index and a in vol_row.index and not np.isnan(score_row[a]) and not np.isnan(vol_row[a]) and vol_row[a] > 0.001:
            available[a] = score_row[a]
    if not available:
        return {"BIL": 1.0}
    sorted_avail = sorted(available.items(), key=lambda x: x[1], reverse=True)
    if threshold > 1.0 and prev_risky:
        selected = {a for a in prev_risky if a in available}
        for a, _ in sorted_avail:
            if len(selected) >= top_n:
                break
            selected.add(a)
        if len(selected) > top_n:
            selected = {
                a for a, _ in sorted([(a, available[a]) for a in selected], key=lambda x: x[1], reverse=True)[:top_n]
            }
        weakest = min(selected, key=lambda a: available.get(a, -999))
        weakest_score = available.get(weakest, 0)
        for a, sc in sorted_avail:
            if a in selected:
                continue
            if weakest_score > 0 and sc > weakest_score * threshold:
                selected.discard(weakest)
                selected.add(a)
                weakest = min(selected, key=lambda a2: available.get(a2, -999))
                weakest_score = available.get(weakest, 0)
        top = [(a, available[a]) for a in selected]
    else:
        top = sorted_avail[:top_n]
    passed = [a for a, _ in top if score_row[a] > abs_threshold]
    n_fail = len(top) - len(passed)
    if not top:
        return {"BIL": 1.0}
    bil_w = n_fail / len(top)
    raw: Dict[str, float] = {}
    if passed:
        iv = {a: 1.0 / vol_row[a] for a in passed if vol_row[a] > 0.001}
        total_iv = sum(iv.values()) if iv else 1.0
        share = 1.0 - bil_w
        raw = {a: (v / total_iv) * share for a, v in iv.items()}
    if bil_w > 0:
        raw["BIL"] = bil_w
    return raw


def _us_model_b(raw_w: Dict[str, float], scale: float) -> Dict[str, float]:
    act: Dict[str, float] = {}
    if scale <= 1.0:
        for a, w in raw_w.items():
            if a != "BIL":
                act[a] = w * scale
    else:
        fut_sum = sum(w for a, w in raw_w.items() if a != "BIL" and a in US_ROT_FUTURES)
        nf_sum = sum(w for a, w in raw_w.items() if a != "BIL" and a not in US_ROT_FUTURES)
        total = fut_sum + nf_sum
        if total > 0:
            target = total * scale
            fut_target = target - nf_sum
            fut_scale = fut_target / fut_sum if fut_sum > 0 and fut_target > 0 else 1.0
            for a, w in raw_w.items():
                if a == "BIL":
                    continue
                act[a] = w * fut_scale if a in US_ROT_FUTURES else w
    risky = sum(act.values())
    act["BIL"] = max(1.0 - risky, 0.0)
    return act


def _apply_btc_cap(act: Dict[str, float], btc_ticker: str, max_w: float) -> Dict[str, float]:
    if btc_ticker not in act or act[btc_ticker] <= max_w:
        return act
    out = dict(act)
    excess = out[btc_ticker] - max_w
    out[btc_ticker] = max_w
    out["BIL"] = out.get("BIL", 0.0) + excess
    return out


def run_us_rotation(close_df: pd.DataFrame, score_df: pd.DataFrame) -> pd.DataFrame:
    working = close_df.copy()
    if US_ROT_BTC_TICKER in working.columns:
        working.loc[working.index < US_ROT_BTC_START, US_ROT_BTC_TICKER] = np.nan
    vol_df = working.ffill().pct_change(fill_method=None).rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
    start_idx = max(US_ROT_LB, US_ROT_VOL_LB, US_ROT_VOL_WINDOW) + 1
    signal_days = _us_signal_days(working, start_idx)
    act = {"BIL": 1.0}
    scale = 1.0
    w_assets = list(US_ROT_POOL) + ["BIL"]
    rows = []
    hist = []
    for i in range(start_idx, len(working)):
        is_sig = i in signal_days
        comm = 0.0
        rebalanced = False
        if len(hist) >= US_ROT_VOL_WINDOW:
            rv = np.std(hist[-US_ROT_VOL_WINDOW :], ddof=1) * np.sqrt(US_TRADING_DAYS)
            scale = min(max(US_ROT_TARGET_VOL / rv, 0.05), US_ROT_MAX_LEV) if rv > 0.001 else US_ROT_MAX_LEV
        old_act = dict(act)
        if is_sig:
            prev_risky = {a for a in w_assets if a != "BIL" and rows and rows[-1].get(f"w_{a}", 0.0) > 0.001}
            raw_w = _us_raw_weights(
                score_df.iloc[i],
                vol_df.iloc[i],
                US_ROT_POOL,
                top_n=3,
                abs_threshold=US_ROT_ABS_THRESHOLD,
                prev_risky=prev_risky if prev_risky else None,
                threshold=US_ROT_REBALANCE_THRESHOLD,
            )
            new_act = _us_model_b(raw_w, scale)
            new_act = _apply_btc_cap(new_act, US_ROT_BTC_TICKER, US_ROT_BTC_MAX_W)
            prev_a = {a: rows[-1].get(f"w_{a}", 0.0) for a in w_assets} if rows else {"BIL": 1.0}
            all_a = set(new_act).union(prev_a)
            turnover = sum(abs(new_act.get(a, 0.0) - prev_a.get(a, 0.0)) for a in all_a if a != "BIL")
            if turnover >= US_ROT_MIN_TURNOVER:
                comm = turnover * US_ROT_COMMISSION if turnover > 0 else 0.0
                act = new_act
                rebalanced = True
        pr = 0.0
        for a, w in old_act.items():
            if a in working.columns and not np.isnan(working.iloc[i].get(a, np.nan)) and not np.isnan(working.iloc[i - 1].get(a, np.nan)):
                pr += w * (working.iloc[i][a] / working.iloc[i - 1][a] - 1)
        adj = (1 + pr) * (1 - comm) - 1
        hist.append(adj)
        row = {"date": working.index[i], "return": adj, "is_signal": is_sig, "rebalanced": rebalanced}
        for a in w_assets:
            row[f"w_{a}"] = act.get(a, 0.0)
        rows.append(row)
    df = pd.DataFrame(rows).set_index("date")
    df["nav"] = (1 + df["return"]).cumprod()
    if US_ROT_VOLREG_ENABLED and "SPY" in working.columns:
        df = apply_vol_regime_overlay(df, working["SPY"])
    return df


def apply_vol_regime_overlay(us_rot_result: pd.DataFrame, spy_close: pd.Series) -> pd.DataFrame:
    spy_ret = spy_close.ffill().pct_change(fill_method=None)
    short_vol = spy_ret.rolling(US_ROT_VOLREG_SHORT_W).std() * np.sqrt(US_TRADING_DAYS)
    long_vol = spy_ret.rolling(US_ROT_VOLREG_LONG_W).std() * np.sqrt(US_TRADING_DAYS)
    vol_ratio = (short_vol / long_vol.replace(0, np.nan)).reindex(us_rot_result.index).ffill()
    mask = vol_ratio.shift(1).gt(US_ROT_VOLREG_THRESHOLD).fillna(False)
    out = us_rot_result.copy()
    out.loc[mask, "return"] = 0.0
    out["nav"] = (1 + out["return"]).cumprod()
    out["volreg_ratio"] = vol_ratio
    out["volreg_cash"] = mask
    return out


def calc_metrics(ret: pd.Series, td: int, rf_daily: float = 0.0) -> dict:
    ret = ret.dropna()
    nav = (1 + ret).cumprod()
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    excess = ret - rf_daily
    sharpe = excess.mean() / excess.std() * np.sqrt(td) if excess.std() > 0 else 0.0
    peak = nav.cummax()
    return {
        "start": ret.index[0].strftime("%Y-%m-%d"),
        "end": ret.index[-1].strftime("%Y-%m-%d"),
        "days": int(len(ret)),
        "annual": float(nav.iloc[-1] ** (1 / years) - 1) if years > 0 else np.nan,
        "max_dd": float(((nav - peak) / peak).min()),
        "sharpe": float(sharpe),
        "total_return": float(nav.iloc[-1] - 1),
    }


def first_valid_score_date(score_df: pd.DataFrame) -> pd.Timestamp:
    mask = score_df.notna().any(axis=1)
    return score_df.index[mask.argmax()] if mask.any() else score_df.index[0]


def main() -> None:
    cn_close, cn_ohlc = build_cn_inputs()
    us_close_raw, us_ohlc = build_us_inputs()

    cn_base = run_cn_strategy_baseline(cn_close, CN_EQUITY_CODES)
    cn_rsrs = run_cn_strategy_rsrs(cn_close, cn_ohlc, CN_EQUITY_CODES)
    cn_rsrs_scores = pd.concat([compute_rsrs_score(cn_ohlc[c]).rename(c) for c in CN_ALL_CODES], axis=1).reindex(cn_close.index)
    cn_common_start = max(cn_base.index[0], cn_rsrs.index[0], first_valid_score_date(cn_rsrs_scores))

    us_close = us_close_raw[["QQQ", "EMXC", "EFA", "GLD", "TLT", "DBC", "BTC-USD", "BIL", "SPY"]].copy()
    us_mom_score = us_close.div(us_close.shift(US_ROT_LB)).sub(1)
    us_rsrs_score = pd.concat([compute_rsrs_score(us_ohlc[c]).rename(c) for c in US_ROT_POOL], axis=1).reindex(us_close.index)
    us_base = run_us_rotation(us_close, us_mom_score)
    us_rsrs = run_us_rotation(us_close, us_rsrs_score)
    us_common_start = max(us_base.index[0], us_rsrs.index[0], first_valid_score_date(us_rsrs_score))

    rows = []
    rows.append({"strategy": "Sub-A_baseline_full", **calc_metrics(cn_base["return"], CN_TRADING_DAYS, CN_RF_DAILY)})
    rows.append({"strategy": "Sub-A_RSRS_full", **calc_metrics(cn_rsrs["return"], CN_TRADING_DAYS, CN_RF_DAILY)})
    rows.append(
        {
            "strategy": "Sub-A_baseline_same_start",
            **calc_metrics(cn_base.loc[cn_base.index >= cn_common_start, "return"], CN_TRADING_DAYS, CN_RF_DAILY),
        }
    )
    rows.append(
        {
            "strategy": "Sub-A_RSRS_same_start",
            **calc_metrics(cn_rsrs.loc[cn_rsrs.index >= cn_common_start, "return"], CN_TRADING_DAYS, CN_RF_DAILY),
        }
    )
    rows.append({"strategy": "Sub-B_baseline_full", **calc_metrics(us_base["return"], US_TRADING_DAYS, 0.0)})
    rows.append({"strategy": "Sub-B_RSRS_full", **calc_metrics(us_rsrs["return"], US_TRADING_DAYS, 0.0)})
    rows.append(
        {
            "strategy": "Sub-B_baseline_same_start",
            **calc_metrics(us_base.loc[us_base.index >= us_common_start, "return"], US_TRADING_DAYS, 0.0),
        }
    )
    rows.append(
        {
            "strategy": "Sub-B_RSRS_same_start",
            **calc_metrics(us_rsrs.loc[us_rsrs.index >= us_common_start, "return"], US_TRADING_DAYS, 0.0),
        }
    )
    compare = pd.DataFrame(rows)

    compare_path = OUT_DIR / "v61_ab_rsrs_replacement_compare.csv"
    compare.to_csv(compare_path, index=False, encoding="utf-8-sig")

    cn_nav = pd.DataFrame({"baseline": cn_base["nav"], "rsrs": cn_rsrs["nav"]})
    us_nav = pd.DataFrame({"baseline": us_base["nav"], "rsrs": us_rsrs["nav"]})
    cn_nav.to_csv(OUT_DIR / "sub_a_nav_compare.csv", encoding="utf-8-sig")
    us_nav.to_csv(OUT_DIR / "sub_b_nav_compare.csv", encoding="utf-8-sig")

    summary = {
        "rsrs_params": {"n": RSRS_N, "m": RSRS_M, "signal": "right_skew", "threshold": 0.0},
        "sub_a_common_start": cn_common_start.strftime("%Y-%m-%d"),
        "sub_b_common_start": us_common_start.strftime("%Y-%m-%d"),
        "sub_a_proxy_map": CN_PROXY_MAP,
        "sub_b_emxc_ohlc_proxy": "EEM before 2017-08-01, EMXC afterwards, both anchored to local EMXC_spliced close",
        "results": compare.to_dict(orient="records"),
    }
    with open(OUT_DIR / "v61_ab_rsrs_replacement_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(compare.to_string(index=False))
    print()
    print(f"Saved compare -> {compare_path}")


if __name__ == "__main__":
    main()

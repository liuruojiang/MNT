# poe: name=Combined-Strategy-V3
# poe: privacy_shield=half
"""
Combined Portfolio V3: 3 Sub-Strategies with Signal & Performance Tracking
- Sub-A (CN): A-Share 4idx+SZQZ, LB=20, AM=10
- Sub-B (US-Rot): US 8ETF rotation, LB=120, Top3, TV=20%, ML=1.5, Model B
- Sub-C (US-Prod): 10ETF production portfolio, AbsMom-6m, annual Dec rebalance
- Combined: equal-weight (1/3 each) monthly-aligned returns
- Weekly win rate: weekdays only, >= 3 trading days per week
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import io
import re
import xlsxwriter
import time
from datetime import datetime, timedelta
from fastapi_poe.types import SettingsResponse

# ---- Settings ----
poe.update_settings(SettingsResponse(
    introduction_message=(
        "📊 **Combined Strategy V3 — 操作信号 & 绩效追踪**\n\n"
        "三策略组合信号输出：\n"
        "- **Sub-A**: A股轮动（515100+3指数+511260国债ETF，动量20日+绝对动量10日）\n"
        "- **Sub-B**: 美股8ETF轮动（IEMG/VEA/GLDM/PDBC替代低费率ETF，LB=120, Top3, TV=20%, ML=1.5）\n"
        "- **Sub-C**: 美股10ETF生产组合（AbsMom-6m, 年度12月再平衡）\n\n"
        "**用法：**\n"
        '- 发送 **"信号"** → 获取当前操作信号 + Excel调仓记录\n'
        '- 发送 **"表现 2024-01到2025-01"** → 查看该时段子策略&组合绩效\n'
        '- 发送 **"表现 最近6个月"** → 查看近期表现\n'
        '- 发送 **"表现 2024年"** → 查看全年表现\n\n'
        "信号日输出实际信号，非信号日输出假设信号并注明。"
    ),
))

# ---- HTTP session ----
def _get_session():
    s = requests.Session()
    retries = Retry(
        total=5, connect=3, read=3,
        backoff_factor=1.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
    })
    return s
_session = _get_session()

# ================================================================
# PARAMETERS
# ================================================================

# --- Sub-A: A-Share ---
CN_COMMISSION = 0.001
CN_RF_DAILY = (1.03 ** (1/244)) - 1
CN_LOOKBACK = 20
CN_ABS_MOM_LB = 10
CN_TRADING_DAYS = 244
CN_STOCK_CODES = ["1.515100", "0.399102", "1.000300", "1.000852"]
CN_BOND_CODE = "1.511260"
CN_ALL_CODES = CN_STOCK_CODES + [CN_BOND_CODE]
CN_NAMES = {"1.515100": "ZZHL-ETF", "0.399102": "CYBQZ", "1.000300": "HS300",
            "1.000852": "ZZ1000", "1.511260": "10Y国债ETF", "cash": "Cash"}

# --- Sub-B: US 8ETF Rotation ---
US_ROT_COMMISSION = 0.001
US_TRADING_DAYS = 252
US_ROT_ASSETS = {
    "SPY":  {"proxy": "SPY",  "label": "S&P 500"},
    "QQQ":  {"proxy": "QQQ",  "label": "Nasdaq 100"},
    "IEMG": {"proxy": "EEM",  "label": "新兴市场"},
    "VEA":  {"proxy": "EFA",  "label": "发达市场"},
    "GLDM": {"proxy": "GLD",  "label": "黄金"},
    "TLT":  {"proxy": "TLT",  "label": "长期国债"},
    "VNQ":  {"proxy": "VNQ",  "label": "REITs"},
    "PDBC": {"proxy": "DBC",  "label": "大宗商品"},
}
US_ROT_POOL = [cfg["proxy"] for cfg in US_ROT_ASSETS.values()]
US_ROT_FUTURES = {"SPY", "QQQ", "GLD", "TLT"}
_ROT_PROXY_TO_LIVE = {cfg["proxy"]: live for live, cfg in US_ROT_ASSETS.items()}
US_ROT_TARGET_VOL = 0.20
US_ROT_MAX_LEV = 1.5
US_ROT_VOL_WINDOW = 40
US_ROT_LB = 120
US_ROT_VOL_LB = 20
US_ROT_MIN_TURNOVER = 0.15

# --- Sub-C: US Production Portfolio ---
PROD_ABS_MOM_LB = 6
PROD_REBAL_MONTH = 12
PROD_CASH = "BIL"
PROD_PORTFOLIO = {
    "MTUM":  {"w": 0.10, "label": "US Momentum",      "proxy": "MTUM", "cls": "equity"},
    "RPV":   {"w": 0.10, "label": "US Deep Value",     "proxy": "RPV",  "cls": "equity"},
    "XSMO":  {"w": 0.10, "label": "US SC Momentum",    "proxy": "XSMO", "cls": "equity"},
    "AVUV":  {"w": 0.10, "label": "US SC Value",       "proxy": "IJS",  "cls": "equity"},
    "AVDV":  {"w": 0.10, "label": "Intl SC Value",     "proxy": "DLS",  "cls": "equity"},
    "EFV":   {"w": 0.10, "label": "Intl Large Value",  "proxy": "EFV",  "cls": "equity"},
    "VGIT":  {"w": 0.15, "label": "US Interm Treasury", "proxy": "VGIT", "cls": "bond"},
    "GLDM":  {"w": 0.15, "label": "Gold",              "proxy": "GLD",  "cls": "commodity"},
    "VNQ":   {"w": 0.05, "label": "US REITs",          "proxy": "VNQ",  "cls": "equity"},
    "IBIT":  {"w": 0.05, "label": "Bitcoin",           "proxy": "BTC-USD", "cls": "crypto"},
}

US_ALL_TICKERS = sorted(set(
    US_ROT_POOL + ["BIL"] +
    [c["proxy"] for c in PROD_PORTFOLIO.values()]
))

# --- Combined weights ---
COMBINED_WEIGHTS = {"Sub-A": 1/3, "Sub-B": 1/3, "Sub-C": 1/3}

# ================================================================
# DATA FETCHING (with fallback sources)
# ================================================================

def _secid_to_sina(secid):
    market, code = secid.split(".")
    return ("sh" if market == "1" else "sz") + code

def _fetch_cn_eastmoney(secid):
    end_date = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
           f"&klt=101&fqt=0&beg=20050101&end={end_date}&lmt=10000")
    resp = _session.get(url, timeout=30,
                        headers={"Referer": "https://quote.eastmoney.com/"})
    resp.raise_for_status()
    data = resp.json()
    klines = data["data"]["klines"]
    rows = [{"date": p[0], "close": float(p[2])} for line in klines for p in [line.split(",")]]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()

def _fetch_cn_sina(secid):
    symbol = _secid_to_sina(secid)
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
           f"/CN_MarketData.getKLineData"
           f"?symbol={symbol}&scale=240&ma=no&datalen=10000")
    resp = _session.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data or not isinstance(data, list) or len(data) == 0:
        raise ValueError(f"Sina returned empty data for {symbol}")
    rows = [{"date": item["day"], "close": float(item["close"])} for item in data]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()

def fetch_cn_kline(secid):
    sources = [
        ("EastMoney", lambda: _fetch_cn_eastmoney(secid)),
        ("Sina",      lambda: _fetch_cn_sina(secid)),
    ]
    last_err = None
    for name, fetcher in sources:
        try:
            df = fetcher()
            if df is not None and len(df) > 50:
                return df, name
        except Exception as e:
            last_err = e
            time.sleep(1)
    raise poe.BotError(f"获取A股数据失败 ({secid}): {last_err}")

def _ticker_to_stooq(ticker):
    special = {"BTC-USD": "btc.v"}
    return special.get(ticker, f"{ticker.lower()}.us")

def _fetch_us_yahoo(ticker, start_date="2003-01-01"):
    start_ts = int(pd.Timestamp(start_date).timestamp())
    end_ts = int((datetime.now() + timedelta(days=30)).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={start_ts}&period2={end_ts}&interval=1d&includeAdjustedClose=true")
    resp = _session.get(url, timeout=30)
    if resp.status_code != 200:
        raise ValueError(f"Yahoo returned status {resp.status_code}")
    data = resp.json()
    if "chart" not in data or not data["chart"].get("result"):
        raise ValueError("Yahoo returned empty result")
    result = data["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    if not timestamps:
        raise ValueError("No timestamps")
    quote = result["indicators"]["quote"][0]
    adj = result["indicators"].get("adjclose", [{}])[0]
    rows = []
    for i, ts in enumerate(timestamps):
        dt = pd.Timestamp.fromtimestamp(ts).strftime("%Y-%m-%d")
        c = quote["close"][i]
        ac = adj.get("adjclose", [None] * len(timestamps))[i] if adj else c
        if c is not None and ac is not None:
            rows.append({"date": dt, "close": ac})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.drop_duplicates(subset="date").set_index("date").sort_index()

def _fetch_us_stooq(ticker, start_date="2003-01-01"):
    stooq_sym = _ticker_to_stooq(ticker)
    d1 = pd.Timestamp(start_date).strftime("%Y%m%d")
    d2 = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
    url = f"https://stooq.com/q/d/l/?s={stooq_sym}&d1={d1}&d2={d2}&i=d"
    resp = _session.get(url, timeout=30)
    resp.raise_for_status()
    text = resp.text.strip()
    if not text or "No data" in text or len(text) < 50:
        raise ValueError(f"Stooq returned no data for {ticker}")
    df = pd.read_csv(io.StringIO(text))
    if df.empty or "Close" not in df.columns:
        raise ValueError(f"Stooq CSV invalid for {ticker}")
    df = df.rename(columns={"Date": "date", "Close": "close"})
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "close"]].dropna().set_index("date").sort_index()

def fetch_yahoo(ticker, start_date="2003-01-01"):
    sources = [
        ("Yahoo", lambda: _fetch_us_yahoo(ticker, start_date)),
        ("Stooq", lambda: _fetch_us_stooq(ticker, start_date)),
    ]
    last_err = None
    for name, fetcher in sources:
        try:
            df = fetcher()
            if df is not None and len(df) > 50:
                return df, name
        except Exception as e:
            last_err = e
            time.sleep(1)
    return None, "FAILED"


# ================================================================
# SUB-A: A-Share Strategy Engine
# ================================================================
def _cn_signal_days(close_df, start_idx):
    week_best = {}
    for i in range(start_idx, len(close_df)):
        dt = close_df.index[i]
        dow = dt.dayofweek
        if dow > 3:
            continue
        yr, wk, _ = dt.isocalendar()
        key = (yr, wk)
        if key not in week_best or dow > week_best[key][1]:
            week_best[key] = (i, dow)
    return {v[0] for v in week_best.values()}

def _cn_cost(old_h, new_h):
    if old_h == "cash":
        legs = 1 if new_h != "cash" else 0
    elif old_h != new_h:
        legs = (1 if old_h != "cash" else 0) + (1 if new_h != "cash" else 0)
    else:
        legs = 0
    return (1 - CN_COMMISSION) ** legs

def run_cn_strategy(close_df, ranking_codes):
    momentum = close_df.div(close_df.shift(CN_LOOKBACK)).sub(1)
    abs_momentum = close_df.div(close_df.shift(CN_ABS_MOM_LB)).sub(1)
    start_idx = max(CN_LOOKBACK, CN_ABS_MOM_LB)
    signal_days = _cn_signal_days(close_df, start_idx)
    holding = "cash"
    rows = []
    for i in range(start_idx, len(close_df)):
        date = close_df.index[i]
        target = None
        is_signal = i in signal_days
        if is_signal:
            mom_vals = momentum.iloc[i][ranking_codes].dropna()
            if len(mom_vals) > 0:
                best = mom_vals.idxmax()
                abs_val = abs_momentum.iloc[i].get(best, np.nan)
                target = best if (not np.isnan(abs_val) and abs_val > 0) else "cash"
        if target is not None:
            old_h = holding
            cf = _cn_cost(old_h, target)
            if old_h == "cash":
                day_ret = (1 + CN_RF_DAILY) * cf - 1
            else:
                prev = close_df.iloc[i-1][old_h]
                curr = close_df.iloc[i][old_h]
                day_ret = (1 + (curr/prev - 1)) * cf - 1 if prev != 0 else cf - 1
            holding = target
        else:
            if holding == "cash":
                day_ret = CN_RF_DAILY
            else:
                prev = close_df.iloc[i-1][holding]
                curr = close_df.iloc[i][holding]
                day_ret = (curr/prev - 1) if prev != 0 else 0.0
        rows.append({"date": date, "return": day_ret, "holding": holding,
                      "is_signal": is_signal, "target": target})
    df = pd.DataFrame(rows).set_index("date")
    df["nav"] = (1 + df["return"]).cumprod()
    return df


# ================================================================
# SUB-B: US 8ETF Rotation Engine
# ================================================================
def _us_signal_days(close_df, start_idx):
    week_best = {}
    for i in range(start_idx, len(close_df)):
        dt = close_df.index[i]
        dow = dt.dayofweek
        if dow > 3:
            continue
        yr, wk, _ = dt.isocalendar()
        key = (yr, wk)
        if key not in week_best or dow > week_best[key][1]:
            week_best[key] = (i, dow)
    return {v[0] for v in week_best.values()}

def _us_raw_weights(mom_row, vol_row, ranking_codes, top_n, abs_threshold):
    available = {}
    for a in ranking_codes:
        if (a in mom_row.index and not np.isnan(mom_row[a])
                and a in vol_row.index and not np.isnan(vol_row[a])
                and vol_row[a] > 0.001):
            available[a] = mom_row[a]
    top = sorted(available.items(), key=lambda x: x[1], reverse=True)[:top_n]
    passed, n_fail = [], 0
    for a, _ in top:
        if not np.isnan(mom_row.get(a, np.nan)) and mom_row[a] > abs_threshold:
            passed.append(a)
        else:
            n_fail += 1
    if not top:
        return {"BIL": 1.0}
    bil_w = n_fail / len(top)
    raw = {}
    if passed:
        iv = {a: 1.0 / vol_row[a] for a in passed}
        total_iv = sum(iv.values())
        share = 1.0 - bil_w
        raw = {a: (v / total_iv) * share for a, v in iv.items()}
    if bil_w > 0:
        raw["BIL"] = bil_w
    return raw

def _us_model_b(raw_w, scale):
    act = {}
    if scale <= 1.0:
        for a, w in raw_w.items():
            if a == "BIL":
                continue
            act[a] = w * scale
    else:
        fut_sum = sum(w for a, w in raw_w.items()
                      if a != "BIL" and a in US_ROT_FUTURES)
        nf_sum = sum(w for a, w in raw_w.items()
                     if a != "BIL" and a not in US_ROT_FUTURES)
        total = fut_sum + nf_sum
        if total > 0:
            target = total * scale
            fut_target = target - nf_sum
            fs = fut_target / fut_sum if (fut_sum > 0 and fut_target > 0) else 1.0
            for a, w in raw_w.items():
                if a == "BIL":
                    continue
                act[a] = w * fs if a in US_ROT_FUTURES else w
    risky = sum(act.values())
    act["BIL"] = max(1.0 - risky, 0.0)
    return act

def run_us_rotation(close_df, ranking_codes, top_n=3, abs_threshold=0.03,
                    min_turnover=US_ROT_MIN_TURNOVER):
    momentum = close_df.div(close_df.shift(US_ROT_LB)).sub(1)
    vol_df = close_df.pct_change().rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
    start_idx = max(US_ROT_LB, US_ROT_VOL_LB, US_ROT_VOL_WINDOW) + 1
    signal_days = _us_signal_days(close_df, start_idx)
    raw_w = {"BIL": 1.0}
    act = {"BIL": 1.0}
    scale = 1.0
    w_assets = list(ranking_codes) + (["BIL"] if "BIL" not in ranking_codes else [])
    rows, hist = [], []

    for i in range(start_idx, len(close_df)):
        is_sig = i in signal_days
        comm = 0.0
        rebalanced = False
        if len(hist) >= US_ROT_VOL_WINDOW:
            rv = np.std(hist[-US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
            scale = min(max(US_ROT_TARGET_VOL / rv, 0.05), US_ROT_MAX_LEV) if rv > 0.001 else US_ROT_MAX_LEV
        old_act = dict(act)
        if is_sig:
            raw_w = _us_raw_weights(
                momentum.iloc[i-1], vol_df.iloc[i-1], ranking_codes, top_n, abs_threshold)
            new_act = _us_model_b(raw_w, scale)
            prev_a = {}
            if rows:
                prev_a = {a: rows[-1].get(f"w_{a}", 0.0) for a in w_assets}
            else:
                prev_a = {"BIL": 1.0}
            all_a = set(list(new_act.keys()) + list(prev_a.keys()))
            to = sum(abs(new_act.get(a, 0) - prev_a.get(a, 0)) for a in all_a if a != "BIL")
            if to >= min_turnover:
                if to > 0:
                    comm = to * US_ROT_COMMISSION
                act = new_act
                rebalanced = True
        pr = 0.0
        for a, w in act.items():
            if a in close_df.columns:
                pr += w * (close_df.iloc[i][a] / close_df.iloc[i-1][a] - 1)
        adj = (1 + pr) * (1 - comm) - 1
        hist.append(adj)
        row = {"date": close_df.index[i], "return": adj, "is_signal": is_sig,
               "rebalanced": rebalanced}
        for a in w_assets:
            row[f"w_{a}"] = act.get(a, 0.0)
        rows.append(row)

    df = pd.DataFrame(rows).set_index("date")
    df["nav"] = (1 + df["return"]).cumprod()
    return df


# ================================================================
# SUB-C: US Production Portfolio Engine (AbsMom-6m)
# ================================================================
def make_abs_mom_signals(monthly_prices, lookback=6):
    ret_n = monthly_prices / monthly_prices.shift(lookback) - 1
    raw = (ret_n > 0).astype(float)
    return raw.shift(1)

def simulate_prod(portfolio, monthly_ret, signals, cash_ret, rebal_month=12):
    dates = monthly_ret.index
    current_val = 1.0
    pos = {t: current_val * c["w"] for t, c in portfolio.items()}
    vals, details = [], []
    for dt in dates:
        month_detail = {"date": dt}
        for t, c in portfolio.items():
            proxy = c["proxy"]
            s = signals.loc[dt, proxy] if proxy in signals.columns else 1.0
            if pd.isna(s):
                s = 0.0
            r_asset = monthly_ret.loc[dt, proxy] if proxy in monthly_ret.columns else 0.0
            r_cash = cash_ret.loc[dt] if dt in cash_ret.index else 0.0
            if pd.isna(r_asset):
                r_asset = 0.0
            if pd.isna(r_cash):
                r_cash = 0.0
            pos[t] *= (1 + (r_asset if s == 1.0 else r_cash))
            month_detail[f"sig_{t}"] = s
        current_val = sum(pos.values())
        vals.append(current_val)
        details.append(month_detail)
        if dt.month == rebal_month:
            pos = {t: current_val * c["w"] for t, c in portfolio.items()}
    nav = pd.Series(vals, index=dates)
    return nav, pd.DataFrame(details).set_index("date")


# ================================================================
# METRICS
# ================================================================
def calc_daily_metrics(ret_series, rf_daily, td):
    nav = (1 + ret_series).cumprod()
    years = (ret_series.index[-1] - ret_series.index[0]).days / 365.25
    if years < 0.25 or len(ret_series) < 20:
        return None
    annual = (nav.iloc[-1] ** (1/years) - 1) * 100
    excess = ret_series - rf_daily
    sharpe = excess.mean() / excess.std() * np.sqrt(td) if excess.std() > 0 else 0
    vol = ret_series.std() * np.sqrt(td) * 100
    peak = nav.cummax()
    dd = ((nav - peak) / peak).min() * 100
    calmar = annual / abs(dd) if dd != 0 else 0
    monthly = ret_series.groupby(ret_series.index.to_period("M")).apply(lambda x: (1+x).prod()-1)
    win_rate = (monthly > 0).mean() * 100
    yearly = {}
    for year in sorted(ret_series.index.year.unique()):
        yr_data = ret_series[ret_series.index.year == year]
        if len(yr_data) > 10:
            yearly[year] = ((1 + yr_data).prod() - 1) * 100
    return {"annual": annual, "vol": vol, "sharpe": sharpe, "max_dd": dd,
            "calmar": calmar, "win_rate": win_rate, "years": years,
            "total_return": (nav.iloc[-1] - 1) * 100, "yearly": yearly}

def calc_monthly_metrics(ret_series, rf_monthly=0.0):
    nav = (1 + ret_series).cumprod()
    n_months = len(ret_series)
    years = n_months / 12
    total_return = (nav.iloc[-1] - 1) * 100
    peak = nav.cummax()
    dd = ((nav - peak) / peak).min() * 100
    win_rate = (ret_series > 0).mean() * 100

    # For short periods (1-2 months), return basic metrics only
    if n_months < 3:
        return {"annual": None, "vol": None, "sharpe": None, "max_dd": dd,
                "calmar": None, "win_rate": win_rate, "years": years,
                "total_return": total_return, "yearly": {}}

    annual = (nav.iloc[-1] ** (1/years) - 1) * 100
    excess = ret_series - rf_monthly
    sharpe = excess.mean() / excess.std() * np.sqrt(12) if excess.std() > 0 else 0
    vol = ret_series.std() * np.sqrt(12) * 100
    calmar = annual / abs(dd) if dd != 0 else 0
    yearly = {}
    for year in sorted(ret_series.index.year.unique()):
        yr_data = ret_series[ret_series.index.year == year]
        if len(yr_data) >= 1:
            yearly[year] = ((1 + yr_data).prod() - 1) * 100
    return {"annual": annual, "vol": vol, "sharpe": sharpe, "max_dd": dd,
            "calmar": calmar, "win_rate": win_rate, "years": years,
            "total_return": total_return, "yearly": yearly}


# ================================================================
# HELPER UTILITIES
# ================================================================

def beijing_now():
    """Get current Beijing time (UTC+8)."""
    from datetime import timezone
    utc_now = datetime.now(timezone.utc)
    bj_now = utc_now + timedelta(hours=8)
    return bj_now.replace(tzinfo=None)

def is_cn_market_open():
    """Check if A-share market is currently in trading hours (9:30-15:00 Beijing time).
    Returns (is_open, bj_now) tuple."""
    bj = beijing_now()
    weekday = bj.weekday()
    if weekday >= 5:  # Weekend
        return False, bj
    market_open = bj.replace(hour=9, minute=30, second=0)
    market_close = bj.replace(hour=15, minute=0, second=0)
    return market_open <= bj <= market_close, bj

def is_us_market_open():
    """Check if US market is currently in trading hours (9:30-16:00 ET).
    Returns (is_open, bj_now) tuple."""
    bj = beijing_now()
    # US market in Beijing time:
    # EST (Nov-Mar): 22:30 - next day 05:00
    # EDT (Mar-Nov): 21:30 - next day 04:00
    month = bj.month
    if 3 <= month < 11:  # EDT
        open_h, open_m, close_h = 21, 30, 4
    else:  # EST
        open_h, open_m, close_h = 22, 30, 5
    hour = bj.hour
    # US trading spans midnight Beijing time
    if hour >= open_h or hour < close_h:
        return True, bj
    return False, bj

def beijing_time_str(date, market="CN"):
    """Convert trading date to Beijing time string."""
    if market == "CN":
        return f"{date.strftime('%Y-%m-%d')} 15:00 北京时间"
    else:
        month = date.month
        bj_hour = "04:00" if 3 <= month < 11 else "05:00"
        next_day = date + timedelta(days=1)
        return f"{next_day.strftime('%Y-%m-%d')} {bj_hour} 北京时间"

def parse_date_range(text):
    """Parse date range from Chinese text. Returns (start, end) or (None, None)."""
    # Pattern: 2024-01到2025-01 or 2024年1月到2025年6月
    m = re.search(r'(\d{4})[-年/.](\d{1,2})[-月]?\s*[到至—\-]+\s*(\d{4})[-年/.](\d{1,2})', text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-01")
        end = pd.Timestamp(f"{m.group(3)}-{int(m.group(4)):02d}-01") + pd.offsets.MonthEnd(0)
        return start, end
    # Same year: 2024年1月到6月 or 2024-01到06
    m = re.search(r'(\d{4})[-年/.](\d{1,2})[-月]?\s*[到至—\-]+\s*(\d{1,2})', text)
    if m:
        yr = int(m.group(1))
        start = pd.Timestamp(f"{yr}-{int(m.group(2)):02d}-01")
        end = pd.Timestamp(f"{yr}-{int(m.group(3)):02d}-01") + pd.offsets.MonthEnd(0)
        return start, end
    # 最近N个月
    m = re.search(r'最近(\d+)\s*个?月', text)
    if m:
        months = int(m.group(1))
        end = pd.Timestamp.now()
        start = end - pd.DateOffset(months=months)
        return start, end
    # Single month: 2026年2月份 or 2026年2月 or 2026-02 (MUST be before year-only pattern)
    m = re.search(r'(\d{4})[-年/.](\d{1,2})\s*月?份?', text)
    if m:
        yr = int(m.group(1))
        mon = int(m.group(2))
        if 1 <= mon <= 12:
            start = pd.Timestamp(f"{yr}-{mon:02d}-01")
            end = start + pd.offsets.MonthEnd(0)
            return start, end
    # 2024年 or 2024年全年 (year-only, no month specified)
    m = re.search(r'(\d{4})\s*年\s*全?年', text)
    if m:
        yr = int(m.group(1))
        return pd.Timestamp(f"{yr}-01-01"), pd.Timestamp(f"{yr}-12-31")
    # 今年
    if '今年' in text:
        now = pd.Timestamp.now()
        return pd.Timestamp(f"{now.year}-01-01"), now
    return None, None

def extract_cn_rebalances(cn_result, cn_close):
    """Extract Sub-A rebalancing records with Beijing time."""
    records = []
    prev_holding = None
    for i in range(len(cn_result)):
        holding = cn_result["holding"].iloc[i]
        date = cn_result.index[i]
        if prev_holding is not None and holding != prev_holding:
            price_sell = cn_close.loc[date, prev_holding] if prev_holding != "cash" and prev_holding in cn_close.columns else None
            price_buy = cn_close.loc[date, holding] if holding != "cash" and holding in cn_close.columns else None
            records.append({
                "日期": date.strftime("%Y-%m-%d"),
                "北京时间": beijing_time_str(date, "CN"),
                "策略": "Sub-A",
                "卖出": CN_NAMES.get(prev_holding, prev_holding),
                "卖出价格": price_sell,
                "买入": CN_NAMES.get(holding, holding),
                "买入价格": price_buy,
            })
        prev_holding = holding
    return records

def extract_us_rot_rebalances(us_rot_result):
    """Extract Sub-B rebalancing records with Beijing time."""
    records = []
    w_cols = [c for c in us_rot_result.columns if c.startswith("w_")]
    prev_weights = None
    for i in range(len(us_rot_result)):
        date = us_rot_result.index[i]
        rebalanced = us_rot_result["rebalanced"].iloc[i] if "rebalanced" in us_rot_result.columns else False
        if not rebalanced:
            weights = {c.replace("w_", ""): us_rot_result.iloc[i][c] for c in w_cols}
            prev_weights = weights
            continue
        weights = {c.replace("w_", ""): us_rot_result.iloc[i][c] for c in w_cols}
        if prev_weights is None:
            prev_weights = {"BIL": 1.0}
        sells, buys = [], []
        for a in sorted(set(list(weights.keys()) + list(prev_weights.keys()))):
            cur = weights.get(a, 0)
            prev = prev_weights.get(a, 0)
            diff = cur - prev
            if abs(diff) > 0.005:
                live = _ROT_PROXY_TO_LIVE.get(a, a)
                if diff < 0 and a != "BIL":
                    sells.append(f"{live} {prev:.1%}→{cur:.1%}")
                elif diff > 0 and a != "BIL":
                    buys.append(f"{live} {prev:.1%}→{cur:.1%}")
        if sells or buys:
            records.append({
                "日期": date.strftime("%Y-%m-%d"),
                "北京时间": beijing_time_str(date, "US"),
                "策略": "Sub-B",
                "卖出": "; ".join(sells) if sells else "—",
                "卖出价格": None,
                "买入": "; ".join(buys) if buys else "—",
                "买入价格": None,
            })
        prev_weights = weights
    return records

def extract_prod_rebalances(prod_details, prod_monthly, include_no_change=False):
    """Extract Sub-C signal change records.
    If include_no_change=True, also record months where signals were evaluated but unchanged."""
    records = []
    sig_cols = [c for c in prod_details.columns if c.startswith("sig_")]
    prev_sigs = None
    for i in range(len(prod_details)):
        dt = prod_details.index[i]
        sigs = {c.replace("sig_", ""): prod_details.iloc[i][c] for c in sig_cols}
        if prev_sigs is not None:
            changes = []
            for t, s in sigs.items():
                ps = prev_sigs.get(t, s)
                if not pd.isna(s) and not pd.isna(ps) and s != ps:
                    action = "持有" if s == 1.0 else "→BIL"
                    proxy = PROD_PORTFOLIO.get(t, {}).get("proxy", t)
                    price = prod_monthly.loc[dt, proxy] if proxy in prod_monthly.columns and dt in prod_monthly.index else None
                    changes.append(f"{t} {'风险资产' if s == 1.0 else '现金(BIL)'}")
            if changes:
                records.append({
                    "日期": dt.strftime("%Y-%m-%d"),
                    "北京时间": beijing_time_str(dt, "US"),
                    "策略": "Sub-C",
                    "卖出": "",
                    "卖出价格": None,
                    "买入": "; ".join(changes),
                    "买入价格": None,
                })
            elif include_no_change:
                risk_on = sum(1 for t, s in sigs.items() if not pd.isna(s) and s == 1.0)
                total = sum(1 for t, s in sigs.items() if not pd.isna(s))
                records.append({
                    "日期": dt.strftime("%Y-%m-%d"),
                    "北京时间": beijing_time_str(dt, "US"),
                    "策略": "Sub-C",
                    "卖出": "",
                    "卖出价格": None,
                    "买入": f"信号无变更 (风险资产{risk_on}/{total})",
                    "买入价格": None,
                })
        prev_sigs = sigs
    return records


def _compute_daily_subc(us_prod_daily, prod_signals, portfolio, cash_ticker):
    """Compute daily Sub-C returns from daily prices and monthly signals.
    Uses monthly AbsMom signals applied to daily price changes for accurate
    intra-month drawdown calculation."""
    daily_ret = us_prod_daily.pct_change().dropna(how="all")
    day_periods = daily_ret.index.to_period("M")

    # Build lookup: month_period -> signal row
    sig_lookup = {}
    for sig_dt in prod_signals.index:
        p = sig_dt.to_period("M")
        sig_lookup[p] = prod_signals.loc[sig_dt]

    # Precompute period masks to avoid redundant comparisons
    period_masks = {}
    for period in day_periods.unique():
        period_masks[period] = (day_periods == period)

    result = pd.Series(0.0, index=daily_ret.index)
    cash_daily = (daily_ret[cash_ticker].fillna(0)
                  if cash_ticker in daily_ret.columns
                  else pd.Series(0.0, index=daily_ret.index))

    for name, cfg in portfolio.items():
        proxy = cfg["proxy"]
        w = cfg["w"]
        if proxy not in daily_ret.columns:
            continue

        asset_daily = daily_ret[proxy].fillna(0)

        # Build daily signal for this asset
        daily_sig = pd.Series(np.nan, index=daily_ret.index)
        for period, mask in period_masks.items():
            if period in sig_lookup and proxy in sig_lookup[period].index:
                sig_val = sig_lookup[period][proxy]
                if pd.isna(sig_val):
                    sig_val = 0.0
                daily_sig[mask] = sig_val

        # Forward fill for months without explicit signal, default to 0 (cash)
        daily_sig = daily_sig.ffill().fillna(0)

        weighted = w * (daily_sig * asset_daily + (1 - daily_sig) * cash_daily)
        result += weighted

    return result


# ================================================================
# EXCEL GENERATION
# ================================================================

def generate_signal_excel(date_str, signal_info, rebalance_records):
    """Generate Excel file for signal output."""
    output = io.BytesIO()
    with xlsxwriter.Workbook(output, {"in_memory": True}) as wb:
        # Formats
        header_fmt = wb.add_format({"bold": True, "bg_color": "#4472C4",
                                     "font_color": "white", "border": 1})
        cell_fmt = wb.add_format({"border": 1})
        pct_fmt = wb.add_format({"border": 1, "num_format": "0.0%"})
        price_fmt = wb.add_format({"border": 1, "num_format": "0.000"})

        # Sheet 1: Signal Overview
        ws = wb.add_worksheet("信号概览")
        ws.set_column("A:A", 12)
        ws.set_column("B:B", 18)
        ws.set_column("C:C", 30)
        ws.set_column("D:D", 15)

        headers = ["策略", "信号日?", "当前信号", "备注"]
        for j, h in enumerate(headers):
            ws.write(0, j, h, header_fmt)

        for i, (strat, info) in enumerate(signal_info.items()):
            ws.write(i+1, 0, strat, cell_fmt)
            ws.write(i+1, 1, "是" if info.get("is_signal") else "否（假设信号）", cell_fmt)
            ws.write(i+1, 2, info.get("signal_text", ""), cell_fmt)
            ws.write(i+1, 3, info.get("note", ""), cell_fmt)

        # Sheet 2: Rebalance Records
        if rebalance_records:
            ws2 = wb.add_worksheet("调仓记录")
            ws2.set_column("A:A", 12)
            ws2.set_column("B:B", 25)
            ws2.set_column("C:C", 8)
            ws2.set_column("D:D", 15)
            ws2.set_column("E:E", 12)
            ws2.set_column("F:F", 30)
            ws2.set_column("G:G", 12)
            rh = ["日期", "北京时间", "策略", "卖出", "卖出价格", "买入", "买入价格"]
            for j, h in enumerate(rh):
                ws2.write(0, j, h, header_fmt)
            for i, rec in enumerate(rebalance_records):
                ws2.write(i+1, 0, rec.get("日期", ""), cell_fmt)
                ws2.write(i+1, 1, rec.get("北京时间", ""), cell_fmt)
                ws2.write(i+1, 2, rec.get("策略", ""), cell_fmt)
                ws2.write(i+1, 3, rec.get("卖出", ""), cell_fmt)
                p = rec.get("卖出价格")
                ws2.write(i+1, 4, p if p is not None else "", price_fmt if p else cell_fmt)
                ws2.write(i+1, 5, rec.get("买入", ""), cell_fmt)
                p2 = rec.get("买入价格")
                ws2.write(i+1, 6, p2 if p2 is not None else "", price_fmt if p2 else cell_fmt)

    output.seek(0)
    return output.getvalue()


def generate_performance_excel(date_str, metrics_dict, monthly_returns, rebalance_records, is_short_period=False):
    """Generate Excel file for performance output."""
    output = io.BytesIO()
    with xlsxwriter.Workbook(output, {"in_memory": True}) as wb:
        header_fmt = wb.add_format({"bold": True, "bg_color": "#4472C4",
                                     "font_color": "white", "border": 1})
        cell_fmt = wb.add_format({"border": 1})
        pct_fmt = wb.add_format({"border": 1, "num_format": "0.00%"})
        num_fmt = wb.add_format({"border": 1, "num_format": "0.00"})

        # Sheet 1: Metrics
        ws = wb.add_worksheet("绩效概览")
        ws.set_column("A:A", 14)
        ws.set_column("B:F", 12)
        metric_headers = ["指标", "Sub-A", "Sub-B", "Sub-C", "组合"]
        for j, h in enumerate(metric_headers):
            ws.write(0, j, h, header_fmt)
        pct2_fmt = wb.add_format({"border": 1, "num_format": "0.00%"})
        metric_names = [
            ("累计收益", "total_return", True),
            ("年化收益", "annual", True),
            ("波动率", "vol", True),
            ("夏普比率", "sharpe", False),
            ("最大回撤", "max_dd", True),
            ("卡尔玛比率", "calmar", False),
            ("月胜率", "win_rate", True),
        ]
        if is_short_period:
            metric_names.append(("周胜率", "weekly_win_rate", True))
        for i, (label, key, is_pct) in enumerate(metric_names):
            ws.write(i+1, 0, label, cell_fmt)
            for j, strat in enumerate(["Sub-A", "Sub-B", "Sub-C", "Combined"]):
                m = metrics_dict.get(strat)
                if m and key in m and m[key] is not None:
                    if is_pct:
                        ws.write(i+1, j+1, m[key] / 100, pct2_fmt)
                    else:
                        ws.write(i+1, j+1, round(m[key], 2), num_fmt)
                else:
                    ws.write(i+1, j+1, "N/A", cell_fmt)

        # Sheet 2: Monthly Returns
        if monthly_returns is not None and len(monthly_returns) > 0:
            ws2 = wb.add_worksheet("月度收益")
            ws2.set_column("A:A", 10)
            ws2.set_column("B:E", 12)
            mr_headers = ["月份", "Sub-A", "Sub-B", "Sub-C", "组合"]
            for j, h in enumerate(mr_headers):
                ws2.write(0, j, h, header_fmt)
            for i in range(len(monthly_returns)):
                idx = monthly_returns.index[i]
                ws2.write(i+1, 0, str(idx), cell_fmt)
                for j, col in enumerate(monthly_returns.columns):
                    val = monthly_returns.iloc[i][col]
                    if not pd.isna(val):
                        ws2.write(i+1, j+1, val, pct_fmt)
                    else:
                        ws2.write(i+1, j+1, "", cell_fmt)

        # Sheet 3: Rebalance Records
        if rebalance_records:
            ws3 = wb.add_worksheet("调仓记录")
            ws3.set_column("A:A", 12)
            ws3.set_column("B:B", 25)
            ws3.set_column("C:C", 8)
            ws3.set_column("D:D", 15)
            ws3.set_column("E:E", 12)
            ws3.set_column("F:F", 30)
            ws3.set_column("G:G", 12)
            rh = ["日期", "北京时间", "策略", "卖出", "卖出价格", "买入", "买入价格"]
            for j, h in enumerate(rh):
                ws3.write(0, j, h, header_fmt)
            price_fmt = wb.add_format({"border": 1, "num_format": "0.000"})
            for i, rec in enumerate(rebalance_records):
                ws3.write(i+1, 0, rec.get("日期", ""), cell_fmt)
                ws3.write(i+1, 1, rec.get("北京时间", ""), cell_fmt)
                ws3.write(i+1, 2, rec.get("策略", ""), cell_fmt)
                ws3.write(i+1, 3, rec.get("卖出", ""), cell_fmt)
                p = rec.get("卖出价格")
                ws3.write(i+1, 4, p if p is not None else "", price_fmt if p else cell_fmt)
                ws3.write(i+1, 5, rec.get("买入", ""), cell_fmt)
                p2 = rec.get("买入价格")
                ws3.write(i+1, 6, p2 if p2 is not None else "", price_fmt if p2 else cell_fmt)

    output.seek(0)
    return output.getvalue()


# ================================================================
# BOT CLASS
# ================================================================
class CombinedStrategyV3:

    def run(self):
        query = poe.query.text.strip()
        if "表现" in query:
            self._handle_performance(query)
        else:
            self._handle_signal()

    # ----------------------------------------------------------
    # Common: fetch all data
    # ----------------------------------------------------------
    def _fetch_data(self, msg):
        msg.write("⏳ 正在获取A股数据...\n")
        cn_raw, cn_sources = {}, {}
        for secid in CN_ALL_CODES:
            df, source = fetch_cn_kline(secid)
            cn_raw[secid] = df
            cn_sources[secid] = source
            time.sleep(0.5)
        cn_close = pd.concat([cn_raw[s].rename(columns={"close": s})
                              for s in CN_ALL_CODES], axis=1).ffill().dropna()

        if len(cn_close) < CN_LOOKBACK + 10:
            raise poe.BotError(f"A股数据不足: 仅{len(cn_close)}行")

        for secid in CN_ALL_CODES:
            name = CN_NAMES.get(secid, secid)
            msg.write(f"  {name}: {cn_raw[secid].index[-1].strftime('%Y-%m-%d')} [{cn_sources[secid]}]\n")
        msg.write(f"  合并截至: {cn_close.index[-1].strftime('%Y-%m-%d')}\n")

        msg.write("⏳ 正在获取美股数据...\n")
        us_raw, us_sources = {}, {}
        for ticker in US_ALL_TICKERS:
            df, source = fetch_yahoo(ticker)
            if df is not None and len(df) > 50:
                us_raw[ticker] = df
                us_sources[ticker] = source
            time.sleep(0.3)

        rot_tickers = US_ROT_POOL + ["BIL"]
        us_rot_close = pd.concat(
            [us_raw[t][["close"]].rename(columns={"close": t})
             for t in rot_tickers if t in us_raw],
            axis=1).ffill().dropna()

        prod_proxies = list(set(
            [c["proxy"] for c in PROD_PORTFOLIO.values()] + [PROD_CASH]))
        us_prod_daily = pd.concat(
            [us_raw[t][["close"]].rename(columns={"close": t})
             for t in prod_proxies if t in us_raw],
            axis=1).ffill().dropna()

        missing_us = set(rot_tickers + prod_proxies) - set(us_raw.keys())
        if missing_us:
            msg.write(f"  ⚠️ 缺失: {', '.join(sorted(missing_us))}\n")

        msg.write(f"  美股: {len(us_raw)}个ETF 截至{us_rot_close.index[-1].strftime('%Y-%m-%d')}\n")

        return cn_close, us_rot_close, us_prod_daily

    # ----------------------------------------------------------
    # Common: run all strategies
    # ----------------------------------------------------------
    def _run_strategies(self, cn_close, us_rot_close, us_prod_daily):
        cn_result = run_cn_strategy(cn_close, CN_ALL_CODES)
        us_rot_result = run_us_rotation(us_rot_close, US_ROT_POOL)

        prod_monthly = us_prod_daily.resample("M").last()
        _last_daily = us_prod_daily.index[-1]
        _last_monthly_period = prod_monthly.index[-1].to_period("M")
        if (_last_daily.to_period("M") == _last_monthly_period and _last_daily.day < 20):
            prod_monthly = prod_monthly.iloc[:-1]
        prod_signals = make_abs_mom_signals(prod_monthly, PROD_ABS_MOM_LB)

        prod_monthly_ret = prod_monthly.pct_change().dropna()
        cash_ret = prod_monthly_ret[PROD_CASH] if PROD_CASH in prod_monthly_ret.columns else pd.Series(0, index=prod_monthly_ret.index)
        prod_nav, prod_details = simulate_prod(PROD_PORTFOLIO, prod_monthly_ret, prod_signals, cash_ret, PROD_REBAL_MONTH)

        return cn_result, us_rot_result, prod_monthly, prod_signals, prod_nav, prod_details

    # ----------------------------------------------------------
    # Signal handler
    # ----------------------------------------------------------
    def _handle_signal(self):
        with poe.start_message() as msg:
            cn_close, us_rot_close, us_prod_daily = self._fetch_data(msg)
            msg.write("⏳ 正在计算信号...\n")

        cn_result, us_rot_result, prod_monthly, prod_signals, prod_nav, prod_details = \
            self._run_strategies(cn_close, us_rot_close, us_prod_daily)

        # --- Sub-A signal info ---
        cn_date = cn_close.index[-1]
        cn_start_idx = max(CN_LOOKBACK, CN_ABS_MOM_LB)
        cn_signal_set = _cn_signal_days(cn_close, cn_start_idx)
        is_cn_signal = (len(cn_close) - 1) in cn_signal_set
        # Fix: for the current (incomplete) week, Mon/Tue/Wed are NOT confirmed
        # signal days — the actual signal day is the last Mon-Thu trading day,
        # which we can't know until the week ends. Only Thu (dayofweek==3) is
        # confirmed as signal day within the current week.
        if is_cn_signal:
            last_dow = cn_date.dayofweek
            last_yr, last_wk, _ = cn_date.isocalendar()
            now_yr, now_wk, _ = datetime.now().isocalendar()
            if (last_yr, last_wk) == (now_yr, now_wk) and last_dow < 3:
                is_cn_signal = False
        cn_current = cn_result["holding"].iloc[-1]

        momentum_cn = cn_close.div(cn_close.shift(CN_LOOKBACK)).sub(1)
        abs_mom_cn = cn_close.div(cn_close.shift(CN_ABS_MOM_LB)).sub(1)

        hypo_data_idx = max(0, len(momentum_cn) - 2)
        mom_vals = momentum_cn.iloc[hypo_data_idx][CN_ALL_CODES].dropna()
        if len(mom_vals) > 0:
            best_cn = mom_vals.idxmax()
            abs_val = abs_mom_cn.iloc[hypo_data_idx].get(best_cn, np.nan)
            hypo_cn = best_cn if (not np.isnan(abs_val) and abs_val > 0) else "cash"
        else:
            hypo_cn = "cash"

        # --- Sub-B signal info ---
        us_date = us_rot_close.index[-1]
        us_start_idx = max(US_ROT_LB, US_ROT_VOL_LB, US_ROT_VOL_WINDOW) + 1
        us_signal_set = _us_signal_days(us_rot_close, us_start_idx)
        is_us_signal = (len(us_rot_close) - 1) in us_signal_set
        # Same fix as Sub-A: current incomplete week → only Thu is confirmed
        if is_us_signal:
            last_dow_us = us_date.dayofweek
            last_yr_us, last_wk_us, _ = us_date.isocalendar()
            now_yr_us, now_wk_us, _ = datetime.now().isocalendar()
            if (last_yr_us, last_wk_us) == (now_yr_us, now_wk_us) and last_dow_us < 3:
                is_us_signal = False

        rot_w_cols = [c for c in us_rot_result.columns if c.startswith("w_")]
        current_us_w = {c.replace("w_", ""): us_rot_result.iloc[-1][c] for c in rot_w_cols}

        hist = us_rot_result["return"].values
        if len(hist) >= US_ROT_VOL_WINDOW:
            rv = np.std(hist[-US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
            scale = min(max(US_ROT_TARGET_VOL / rv, 0.05), US_ROT_MAX_LEV) if rv > 0.001 else US_ROT_MAX_LEV
        else:
            scale = 1.0

        # Compute hypothetical/actual weights for Sub-B
        if is_us_signal:
            prev_us_w = {}
            for idx in range(len(us_rot_result) - 2, -1, -1):
                row = us_rot_result.iloc[idx]
                pw = {c.replace("w_", ""): row[c] for c in rot_w_cols}
                if pw != current_us_w:
                    prev_us_w = pw
                    break
            if not prev_us_w:
                prev_us_w = {"BIL": 1.0}
            hypo_us_w = current_us_w
            all_a = set(list(current_us_w.keys()) + list(prev_us_w.keys()))
            turnover = sum(abs(current_us_w.get(a, 0) - prev_us_w.get(a, 0)) for a in all_a if a != "BIL")
            rebalanced_b = turnover > 0.001
        else:
            momentum_us = us_rot_close.div(us_rot_close.shift(US_ROT_LB)).sub(1)
            vol_df = us_rot_close.pct_change().rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
            raw_w = _us_raw_weights(momentum_us.iloc[-1], vol_df.iloc[-1], US_ROT_POOL, 3, 0.03)
            hypo_us_w = _us_model_b(raw_w, scale)
            all_a = set(list(hypo_us_w.keys()) + list(current_us_w.keys()))
            turnover = sum(abs(hypo_us_w.get(a, 0) - current_us_w.get(a, 0)) for a in all_a if a != "BIL")
            would_rebalance = turnover >= US_ROT_MIN_TURNOVER

        # --- Sub-C signal info ---
        ret_n_prod = prod_monthly / prod_monthly.shift(PROD_ABS_MOM_LB) - 1
        current_prod_raw = (ret_n_prod > 0).astype(float)
        last_sig_month = current_prod_raw.index[-1]

        # ==============================================================
        # OUTPUT SIGNAL TEXT
        # ==============================================================
        now_str = datetime.now().strftime("%Y%m%d")
        signal_info = {}  # For Excel

        # Detect market hours
        cn_open, bj_now = is_cn_market_open()
        us_open, _ = is_us_market_open()
        cn_data_is_today = (cn_date.date() == bj_now.date())
        us_data_is_today = (us_date.date() == bj_now.date()) or \
            (us_date.date() == (bj_now - timedelta(days=1)).date() and bj_now.hour < 6)

        with poe.start_message() as msg:
            msg.write("## 📊 操作信号\n\n")

            # Market status banner
            bj_time_str = bj_now.strftime('%H:%M')
            if cn_open and cn_data_is_today:
                msg.write(f"⚠️ **A股盘中** (北京时间 {bj_time_str})，"
                         f"数据含今日实时价格（非收盘价），信号可能在收盘后变化\n\n")
            if us_open and us_data_is_today:
                msg.write(f"⚠️ **美股盘中** (北京时间 {bj_time_str})，"
                         f"数据含今日实时价格（非收盘价），信号可能在收盘后变化\n\n")

            # ---- Sub-A ----
            msg.write("### Sub-A: A股轮动\n")
            msg.write(f"数据来源: 东方财富日K线 | 截至: {cn_date.strftime('%Y-%m-%d')}")
            if cn_open and cn_data_is_today:
                msg.write(" ⚡实时")
            msg.write("\n")
            if is_cn_signal:
                msg.write(f"✅ {cn_date.strftime('%Y-%m-%d')} 是信号日\n")
                msg.write(f"**持仓信号: {CN_NAMES.get(cn_current, cn_current)}**\n")
                msg.write(f"⏰ {beijing_time_str(cn_date, 'CN')}\n\n")
                signal_info["Sub-A"] = {
                    "is_signal": True,
                    "signal_text": CN_NAMES.get(cn_current, cn_current),
                    "note": beijing_time_str(cn_date, "CN"),
                }
            else:
                sigs = sorted([i for i in cn_signal_set if i < len(cn_close)])
                last_cn_sig_date = cn_close.index[sigs[-1]] if sigs else cn_date
                msg.write(f"⏸️ {cn_date.strftime('%Y-%m-%d')} 非信号日"
                         f"（上次: {last_cn_sig_date.strftime('%m-%d')}）\n")
                msg.write(f"- 当前持仓: **{CN_NAMES.get(cn_current, cn_current)}**\n")
                hypo_name = CN_NAMES.get(hypo_cn, hypo_cn)
                if hypo_cn == cn_current:
                    msg.write(f"- 假设今天出信号: **{hypo_name}**（无变化）\n\n")
                else:
                    msg.write(f"- 假设今天出信号: **{hypo_name}** ⬅️ 需换仓\n\n")
                signal_info["Sub-A"] = {
                    "is_signal": False,
                    "signal_text": f"当前:{CN_NAMES.get(cn_current, cn_current)} / 假设:{hypo_name}",
                    "note": f"非信号日,上次{last_cn_sig_date.strftime('%m-%d')}",
                }

            # Momentum ranking
            msg.write("动量排名:\n")
            mom_rank = momentum_cn.iloc[-1][CN_ALL_CODES].dropna().sort_values(ascending=False)
            for rank, (code, val) in enumerate(mom_rank.items(), 1):
                name = CN_NAMES.get(code, code)
                av = abs_mom_cn.iloc[-1].get(code, np.nan)
                af = "✅" if (not np.isnan(av) and av > 0) else "❌"
                marker = " 👈" if code == cn_current else ""
                msg.write(f"  {rank}. {name} {val:+.2%} 绝对动量{af}{marker}\n")
            msg.write("\n---\n\n")

            # ---- Sub-B ----
            msg.write("### Sub-B: 美股8ETF轮动\n")
            msg.write(f"数据来源: Yahoo Finance日K线 | 截至: {us_date.strftime('%Y-%m-%d')}")
            if us_open and us_data_is_today:
                msg.write(" ⚡实时")
            msg.write("\n")
            msg.write(f"波动率缩放: {scale:.2f}x\n")
            changed = {l: c["proxy"] for l, c in US_ROT_ASSETS.items() if l != c["proxy"]}
            if changed:
                msg.write("实盘→proxy: " + ", ".join(f"{k}→{v}" for k, v in changed.items()) + "\n")
            msg.write("\n")

            if is_us_signal:
                msg.write(f"✅ {us_date.strftime('%Y-%m-%d')} 是信号日\n")
                msg.write(f"⏰ {beijing_time_str(us_date, 'US')}\n\n")
                if rebalanced_b:
                    msg.write("**已调仓**，当前持仓:\n\n")
                else:
                    msg.write("调仓幅度未达阈值，**维持原仓位**:\n\n")
                msg.write("| ETF | 权重 | 变动 |\n|:----|-----:|-----:|\n")
                for etf in sorted(all_a):
                    cur = current_us_w.get(etf, 0)
                    prev = prev_us_w.get(etf, 0)
                    if cur < 0.001 and prev < 0.001:
                        continue
                    diff = cur - prev
                    ds = f"{diff:+.1%}" if abs(diff) > 0.001 else "—"
                    live = _ROT_PROXY_TO_LIVE.get(etf, etf)
                    msg.write(f"| {live} | {cur:.1%} | {ds} |\n")
                us_sig_text = "; ".join(f"{_ROT_PROXY_TO_LIVE.get(e,e)} {current_us_w.get(e,0):.0%}" for e in sorted(all_a) if current_us_w.get(e, 0) > 0.005)
                signal_info["Sub-B"] = {
                    "is_signal": True,
                    "signal_text": us_sig_text,
                    "note": beijing_time_str(us_date, "US"),
                }
            else:
                sigs = sorted([i for i in us_signal_set if i < len(us_rot_close)])
                last_us_date = us_rot_close.index[sigs[-1]] if sigs else us_date
                msg.write(f"⏸️ {us_date.strftime('%Y-%m-%d')} 非信号日"
                         f"（上次: {last_us_date.strftime('%m-%d')}）\n\n")
                msg.write("| ETF | 当前持仓 | 假设信号 | 变动 |\n|:----|--------:|--------:|-----:|\n")
                for etf in sorted(all_a):
                    cur = current_us_w.get(etf, 0)
                    hypo = hypo_us_w.get(etf, 0)
                    if cur < 0.001 and hypo < 0.001:
                        continue
                    diff = hypo - cur
                    ds = f"{diff:+.1%}" if abs(diff) > 0.001 else "—"
                    live = _ROT_PROXY_TO_LIVE.get(etf, etf)
                    msg.write(f"| {live} | {cur:.1%} | {hypo:.1%} | {ds} |\n")
                msg.write(f"\n调仓幅度: **{turnover:.1%}**")
                if would_rebalance:
                    msg.write(f" ✅ 超{US_ROT_MIN_TURNOVER:.0%}阈值，**会调仓**\n")
                else:
                    msg.write(f" ❌ 低于{US_ROT_MIN_TURNOVER:.0%}阈值，**不调仓**\n")
                us_sig_text = "; ".join(f"{_ROT_PROXY_TO_LIVE.get(e,e)} {current_us_w.get(e,0):.0%}" for e in sorted(all_a) if current_us_w.get(e, 0) > 0.005)
                signal_info["Sub-B"] = {
                    "is_signal": False,
                    "signal_text": f"当前:{us_sig_text}",
                    "note": f"非信号日,上次{last_us_date.strftime('%m-%d')}",
                }
            msg.write("\n---\n\n")

            # ---- Sub-C ----
            msg.write("### Sub-C: 美股生产组合\n")
            msg.write("📅 **月度信号机制**（非周度）：每月月末最后一个交易日发出信号，"
                     "次月第一个交易日执行。12月年度重平衡权重。\n\n")

            # Find actual signal issue date (last trading day of signal month)
            # and execution date (first trading day of next month)
            sig_month_period = last_sig_month.to_period("M")
            sig_month_mask = us_prod_daily.index.to_period("M") == sig_month_period
            sig_month_trading = us_prod_daily.index[sig_month_mask]
            signal_issue_date = sig_month_trading[-1] if len(sig_month_trading) > 0 else last_sig_month

            next_month_period = sig_month_period + 1
            next_month_mask = us_prod_daily.index.to_period("M") == next_month_period
            next_month_trading = us_prod_daily.index[next_month_mask]
            exec_date = next_month_trading[0] if len(next_month_trading) > 0 else None

            msg.write(f"信号发出: **{signal_issue_date.strftime('%Y-%m-%d')}** "
                     f"({beijing_time_str(signal_issue_date, 'US')})\n")
            if exec_date is not None:
                msg.write(f"执行调仓: **{exec_date.strftime('%Y-%m-%d')}** "
                         f"({beijing_time_str(exec_date, 'US')})\n\n")
            else:
                msg.write(f"执行调仓: 次月第一个交易日（待定）\n\n")

            # Check for signal changes vs previous month
            prev_sig_month = None
            if len(current_prod_raw) >= 2:
                prev_sig_month = current_prod_raw.index[-2]

            msg.write("| 资产 | 标签 | 权重 | 信号 | 操作 | 变动 |\n|:-----|:-----|-----:|:----:|:----:|:----:|\n")
            risk_on, cash_on = 0, 0
            prod_signal_parts = []
            changes_count = 0
            for name, cfg in PROD_PORTFOLIO.items():
                proxy = cfg["proxy"]
                w = cfg["w"]
                sv = current_prod_raw.loc[last_sig_month, proxy] if proxy in current_prod_raw.columns else float("nan")
                # Previous month signal for comparison
                prev_sv = float("nan")
                if prev_sig_month is not None and proxy in current_prod_raw.columns:
                    prev_sv = current_prod_raw.loc[prev_sig_month, proxy]
                # Determine change
                change_str = "—"
                if not pd.isna(sv) and not pd.isna(prev_sv):
                    if sv != prev_sv:
                        change_str = "🔄 变更" if sv == 1.0 else "🔄 转现金"
                        changes_count += 1

                if pd.isna(sv):
                    ss, act = "—", "现金"
                    cash_on += w
                elif sv == 1.0:
                    ss, act = "✅", name
                    risk_on += w
                    prod_signal_parts.append(name)
                else:
                    ss, act = "❌", "BIL"
                    cash_on += w
                msg.write(f"| {name} | {cfg['label']} | {w:.0%} | {ss} | {act} | {change_str} |\n")
            msg.write(f"\n风险资产 {risk_on:.0%} | 现金 {cash_on:.0%}")
            if prev_sig_month is not None:
                msg.write(f" | 较上月({prev_sig_month.strftime('%Y-%m')})有 **{changes_count}** 项变更")
            msg.write("\n")

            signal_info["Sub-C"] = {
                "is_signal": False,  # Sub-C is monthly, not weekly signal
                "signal_text": f"风险{risk_on:.0%}/现金{cash_on:.0%} ({','.join(prod_signal_parts[:3])}...)" if prod_signal_parts else "全现金",
                "note": f"信号{signal_issue_date.strftime('%m-%d')}发出,"
                        f"{'执行' + exec_date.strftime('%m-%d') if exec_date else '待执行'}",
            }

        # ==============================================================
        # GENERATE EXCEL
        # ==============================================================
        # Get recent rebalances (last 60 days)
        cutoff = cn_date - timedelta(days=60)
        all_rebalances = []
        cn_rebs = extract_cn_rebalances(cn_result, cn_close)
        all_rebalances.extend([r for r in cn_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        us_rebs = extract_us_rot_rebalances(us_rot_result)
        all_rebalances.extend([r for r in us_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        prod_rebs = extract_prod_rebalances(prod_details, prod_monthly)
        all_rebalances.extend([r for r in prod_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        all_rebalances.sort(key=lambda x: x["日期"], reverse=True)

        excel_bytes = generate_signal_excel(now_str, signal_info, all_rebalances)
        filename = f"signal_{now_str}.xlsx"

        with poe.start_message() as msg:
            msg.attach_file(
                name=filename,
                contents=excel_bytes,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            msg.write(f"📎 Excel调仓记录: **{filename}**\n")
            if all_rebalances:
                msg.write(f"含最近60天 {len(all_rebalances)} 条调仓记录（北京时间）")
            else:
                msg.write("最近60天无调仓记录")

    # ----------------------------------------------------------
    # Performance handler
    # ----------------------------------------------------------
    def _handle_performance(self, query):
        start_date, end_date = parse_date_range(query)
        if start_date is None:
            raise poe.BotError(
                "无法解析日期范围。请使用以下格式：\n"
                "- 表现 2024-01到2025-01\n"
                "- 表现 最近6个月\n"
                "- 表现 2024年\n"
                "- 表现 今年"
            )

        with poe.start_message() as msg:
            cn_close, us_rot_close, us_prod_daily = self._fetch_data(msg)
            msg.write("⏳ 正在计算策略...\n")

        cn_result, us_rot_result, prod_monthly, prod_signals, prod_nav, prod_details = \
            self._run_strategies(cn_close, us_rot_close, us_prod_daily)

        # --- Convert to monthly returns and align ---
        # Sub-A: daily → monthly
        cn_monthly = cn_result["return"].groupby(cn_result.index.to_period("M")).apply(
            lambda x: (1+x).prod()-1)
        # Sub-B: daily → monthly
        us_rot_monthly = us_rot_result["return"].groupby(us_rot_result.index.to_period("M")).apply(
            lambda x: (1+x).prod()-1)
        # Sub-C: from NAV
        prod_monthly_ret = prod_nav.pct_change().dropna()
        prod_monthly_ret.index = prod_monthly_ret.index.to_period("M")

        # Align all three
        all_periods = cn_monthly.index.intersection(us_rot_monthly.index).intersection(prod_monthly_ret.index)
        if len(all_periods) == 0:
            raise poe.BotError("三个策略没有重叠的月度数据")

        aligned = pd.DataFrame({
            "Sub-A": cn_monthly.reindex(all_periods),
            "Sub-B": us_rot_monthly.reindex(all_periods),
            "Sub-C": prod_monthly_ret.reindex(all_periods),
        }).dropna()

        # Combined
        w = COMBINED_WEIGHTS
        aligned["Combined"] = (aligned["Sub-A"] * w["Sub-A"]
                               + aligned["Sub-B"] * w["Sub-B"]
                               + aligned["Sub-C"] * w["Sub-C"])

        # Filter to date range
        start_period = start_date.to_period("M")
        end_period = end_date.to_period("M")
        mask = (aligned.index >= start_period) & (aligned.index <= end_period)
        filtered = aligned[mask]

        if len(filtered) < 1:
            raise poe.BotError(f"在 {start_date.strftime('%Y-%m')} 到 {end_date.strftime('%Y-%m')} 期间没有数据")

        # Calculate metrics
        metrics = {}
        for col in ["Sub-A", "Sub-B", "Sub-C", "Combined"]:
            m = calc_monthly_metrics(filtered[col])
            if m:
                metrics[col] = m

        # --- Override max drawdown using daily data (intra-month precision) ---
        # Monthly aggregation loses intra-month drawdowns; use daily returns instead.

        # Sub-A: daily A-share returns
        cn_daily_period = cn_result["return"][
            (cn_result.index >= start_date) & (cn_result.index <= end_date)]
        if len(cn_daily_period) > 1 and "Sub-A" in metrics:
            nav_a = (1 + cn_daily_period).cumprod()
            metrics["Sub-A"]["max_dd"] = ((nav_a - nav_a.cummax()) / nav_a.cummax()).min() * 100

        # Sub-B: daily US rotation returns
        us_daily_period = us_rot_result["return"][
            (us_rot_result.index >= start_date) & (us_rot_result.index <= end_date)]
        if len(us_daily_period) > 1 and "Sub-B" in metrics:
            nav_b = (1 + us_daily_period).cumprod()
            metrics["Sub-B"]["max_dd"] = ((nav_b - nav_b.cummax()) / nav_b.cummax()).min() * 100

        # Sub-C: daily returns from production portfolio prices + monthly signals
        subc_daily = _compute_daily_subc(us_prod_daily, prod_signals, PROD_PORTFOLIO, PROD_CASH)
        subc_period = subc_daily[
            (subc_daily.index >= start_date) & (subc_daily.index <= end_date)]
        if len(subc_period) > 1 and "Sub-C" in metrics:
            nav_c = (1 + subc_period).cumprod()
            metrics["Sub-C"]["max_dd"] = ((nav_c - nav_c.cummax()) / nav_c.cummax()).min() * 100

        # Combined: equal-weight daily (aligned across CN and US trading dates)
        comb_daily = None
        if "Combined" in metrics:
            all_daily_dates = cn_daily_period.index.union(
                us_daily_period.index).union(subc_period.index).sort_values()
            if len(all_daily_dates) > 1:
                cw = COMBINED_WEIGHTS
                comb_daily = (
                    cn_daily_period.reindex(all_daily_dates).fillna(0) * cw["Sub-A"] +
                    us_daily_period.reindex(all_daily_dates).fillna(0) * cw["Sub-B"] +
                    subc_period.reindex(all_daily_dates).fillna(0) * cw["Sub-C"]
                )
                nav_comb = (1 + comb_daily).cumprod()
                metrics["Combined"]["max_dd"] = (
                    (nav_comb - nav_comb.cummax()) / nav_comb.cummax()).min() * 100

        # --- Weekly win rate for short periods (< 1 year) ---
        is_short_period = (end_date - start_date).days < 365
        if is_short_period:
            def _weekly_win_rate(daily_ret):
                """Compute weekly win rate using Mon-Fri trading days only.
                Only counts weeks with >= 3 trading days (drops partial weeks
                at month boundaries and holidays)."""
                if daily_ret is None or len(daily_ret) < 5:
                    return None, 0
                # Filter to weekdays only (Mon=0 .. Fri=4) to exclude
                # weekend entries (e.g. BTC-USD trades 24/7)
                weekday_mask = daily_ret.index.dayofweek < 5
                wd_ret = daily_ret[weekday_mask]
                if len(wd_ret) < 5:
                    return None, 0
                # Group by ISO week
                weekly_groups = wd_ret.groupby(wd_ret.index.to_period("W"))
                # Only keep weeks with >= 3 trading days (remove partial weeks)
                weekly = weekly_groups.apply(lambda x: (1 + x).prod() - 1)
                week_sizes = weekly_groups.size()
                full_weeks = week_sizes[week_sizes >= 3].index
                weekly = weekly.reindex(full_weeks)
                if len(weekly) < 1:
                    return None, 0
                return (weekly > 0).mean() * 100, len(weekly)

            for strat_name, daily_data in [
                ("Sub-A", cn_daily_period),
                ("Sub-B", us_daily_period),
                ("Sub-C", subc_period),
                ("Combined", comb_daily),
            ]:
                if strat_name in metrics and daily_data is not None and len(daily_data) > 4:
                    wwr, n_weeks = _weekly_win_rate(daily_data)
                    if wwr is not None:
                        metrics[strat_name]["weekly_win_rate"] = wwr
                        metrics[strat_name]["weekly_win_weeks"] = n_weeks

        # Rebalance records in period
        all_rebalances = []
        cn_rebs = extract_cn_rebalances(cn_result, cn_close)
        all_rebalances.extend([r for r in cn_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])
        us_rebs = extract_us_rot_rebalances(us_rot_result)
        all_rebalances.extend([r for r in us_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])
        prod_rebs = extract_prod_rebalances(prod_details, prod_monthly, include_no_change=True)
        all_rebalances.extend([r for r in prod_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])
        all_rebalances.sort(key=lambda x: x["日期"])

        # ==============================================================
        # OUTPUT PERFORMANCE TEXT
        # ==============================================================
        with poe.start_message() as msg:
            msg.write(f"## 📈 策略表现: {start_date.strftime('%Y-%m')} 至 {end_date.strftime('%Y-%m')}\n\n")

            msg.write("| 指标 | Sub-A | Sub-B | Sub-C | 组合(等权) |\n")
            msg.write("|:-----|------:|------:|------:|----------:|\n")
            metric_labels = [
                ("年化收益", "annual", "%"), ("波动率", "vol", "%"),
                ("夏普比率", "sharpe", ""), ("最大回撤", "max_dd", "%"),
                ("卡尔玛比率", "calmar", ""), ("月胜率", "win_rate", "%"),
            ]
            if is_short_period:
                metric_labels.append(("周胜率", "weekly_win_rate", "%"))
            metric_labels.append(("累计收益", "total_return", "%"))
            for label, key, suffix in metric_labels:
                row = f"| {label} |"
                for col in ["Sub-A", "Sub-B", "Sub-C", "Combined"]:
                    m = metrics.get(col)
                    if m and key in m and m[key] is not None:
                        val_str = f"{m[key]:.2f}{suffix}"
                        # Append week count for transparency
                        if key == "weekly_win_rate" and "weekly_win_weeks" in m:
                            val_str += f" ({m['weekly_win_weeks']}周)"
                        row += f" {val_str} |"
                    else:
                        row += " — |"
                msg.write(row + "\n")

            # Yearly breakdown
            years_available = set()
            for m in metrics.values():
                if "yearly" in m:
                    years_available.update(m["yearly"].keys())
            if years_available:
                msg.write(f"\n### 年度收益\n")
                msg.write("| 年份 | Sub-A | Sub-B | Sub-C | 组合 |\n")
                msg.write("|:-----|------:|------:|------:|-----:|\n")
                for yr in sorted(years_available):
                    row = f"| {yr} |"
                    for col in ["Sub-A", "Sub-B", "Sub-C", "Combined"]:
                        m = metrics.get(col)
                        if m and yr in m.get("yearly", {}):
                            row += f" {m['yearly'][yr]:.1f}% |"
                        else:
                            row += " — |"
                    msg.write(row + "\n")

            # Recent rebalances
            msg.write(f"\n### 调仓记录 ({len(all_rebalances)}条)\n")
            if all_rebalances:
                msg.write("| 日期 | 北京时间 | 策略 | 操作 |\n")
                msg.write("|:-----|:---------|:-----|:-----|\n")
                display_rebs = all_rebalances[-20:]  # Show last 20
                for rec in display_rebs:
                    buy_info = rec.get("买入", "")
                    sell_info = rec.get("卖出", "")
                    # Clean up "—" placeholders
                    if sell_info == "—":
                        sell_info = ""
                    if buy_info == "—":
                        buy_info = ""
                    parts = []
                    if sell_info:
                        parts.append(f"减: {sell_info}")
                    if buy_info:
                        parts.append(f"加: {buy_info}")
                    op = " / ".join(parts) if parts else "—"
                    msg.write(f"| {rec['日期']} | {rec['北京时间']} | {rec['策略']} | {op} |\n")
                if len(all_rebalances) > 20:
                    msg.write(f"\n（仅显示最近20条，完整记录见Excel）\n")
            else:
                msg.write("该时段无调仓记录\n")

        # Generate Excel
        now_str = datetime.now().strftime("%Y%m%d")
        excel_bytes = generate_performance_excel(now_str, metrics, filtered, all_rebalances, is_short_period)
        filename = f"performance_{now_str}.xlsx"

        with poe.start_message() as msg:
            msg.attach_file(
                name=filename,
                contents=excel_bytes,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            msg.write(f"📎 绩效报告: **{filename}**")


if __name__ == "__main__":
    bot = CombinedStrategyV3()
    bot.run()

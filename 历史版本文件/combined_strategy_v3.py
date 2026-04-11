# poe: name=Combined-Strategy-V3
# poe: privacy_shield=half
"""
Combined Portfolio V3: 3 Sub-Strategies
- Sub-A (CN): A-Share 4idx+SZQZ, LB=20, AM=10
- Sub-B (US-Rot): US 8ETF rotation, LB=120, Top3, TV=20%, ML=1.5, Model B
- Sub-C (US-Prod): 10ETF production portfolio, AbsMom-6m, annual Dec rebalance
- Monthly-aligned returns, grid search for optimal 3-way allocation
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import io
import xlsxwriter
import time
import itertools
from datetime import datetime, timedelta
from matplotlib.colors import TwoSlopeNorm
from fastapi_poe.types import SettingsResponse

# ---- Settings ----
poe.update_settings(SettingsResponse(
    introduction_message=(
        "Hi! I'm **Combined Strategy V3** - a 3-strategy portfolio backtesting bot.\n\n"
        "**Sub-Strategies:**\n"
        "- **Sub-A (CN)**: A-Share 4 indices + SZQZ, momentum LB=20, abs momentum LB=10\n"
        "- **Sub-B (US-Rot)**: US 8-ETF rotation, LB=120, Top3, target vol 20%, max leverage 1.5x\n"
        "- **Sub-C (US-Prod)**: 10-ETF production portfolio, absolute momentum 6m, annual Dec rebalance\n\n"
        "**Output includes:**\n"
        "- Sub-strategy standalone metrics\n"
        "- Grid search for optimal 3-way allocation (10% step)\n"
        "- Yearly returns, period stability analysis\n"
        "- NAV charts, drawdown, heatmaps\n"
        "- Full Excel report (4 sheets)\n\n"
        "Send any message to run the analysis."
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
CN_STOCK_CODES = ["1.000922", "0.399102", "1.000300", "1.000852"]
CN_BOND_CODE = "1.000013"
CN_ALL_CODES = CN_STOCK_CODES + [CN_BOND_CODE]
CN_NAMES = {"1.000922": "ZZHL", "0.399102": "CYBQZ", "1.000300": "HS300",
            "1.000852": "ZZ1000", "1.000013": "SZQZ", "cash": "Cash"}

# --- Sub-B: US 8ETF Rotation ---
US_ROT_COMMISSION = 0.001
US_TRADING_DAYS = 252
US_ROT_POOL = ["SPY", "QQQ", "EEM", "EFA", "GLD", "TLT", "VNQ", "DBC"]
US_ROT_FUTURES = {"SPY", "QQQ", "GLD", "TLT"}
US_ROT_TARGET_VOL = 0.20
US_ROT_MAX_LEV = 1.5
US_ROT_VOL_WINDOW = 40
US_ROT_LB = 120
US_ROT_VOL_LB = 20
US_ROT_MIN_TURNOVER = 0.15  # skip rebalance if total weight change < 15%

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

# All US tickers to fetch (union of rotation + production + BIL)
US_ALL_TICKERS = sorted(set(
    US_ROT_POOL + ["BIL"] +
    [c["proxy"] for c in PROD_PORTFOLIO.values()]
))

# ================================================================
# DATA FETCHING (with fallback sources)
# ================================================================

# ---------- A-Share helpers ----------
def _secid_to_sina(secid):
    """Convert EastMoney secid '1.000922' to Sina symbol 'sh000922'."""
    market, code = secid.split(".")
    return ("sh" if market == "1" else "sz") + code


# --- A-Share: EastMoney (primary) ---
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
    rows = []
    for line in klines:
        p = line.split(",")
        rows.append({"date": p[0], "close": float(p[2])})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


# --- A-Share: Sina Finance (backup) ---
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


# --- A-Share: wrapper with fallback ---
def fetch_cn_kline(secid):
    """Try EastMoney -> Sina.  Returns (DataFrame, source_name)."""
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
    raise poe.BotError(
        f"获取A股数据失败 ({secid}): 所有数据源均失败。最后错误: {last_err}")


# ---------- US Stock helpers ----------
def _ticker_to_stooq(ticker):
    """Convert Yahoo ticker to Stooq symbol."""
    special = {"BTC-USD": "btc.v"}
    return special.get(ticker, f"{ticker.lower()}.us")


# --- US Stock: Yahoo Finance (primary) ---
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
        raise ValueError("No timestamps in Yahoo response")
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


# --- US Stock: Stooq (backup) ---
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


# --- US Stock: wrapper with fallback ---
def fetch_yahoo(ticker, start_date="2003-01-01"):
    """Try Yahoo -> Stooq.  Returns (DataFrame, source_name) or (None, 'FAILED')."""
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
        rows.append({"date": date, "return": day_ret})
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
        if len(hist) >= US_ROT_VOL_WINDOW:
            rv = np.std(hist[-US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
            scale = min(max(US_ROT_TARGET_VOL / rv, 0.05), US_ROT_MAX_LEV) if rv > 0.001 else US_ROT_MAX_LEV
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
            # else: skip rebalance, keep old weights
        pr = 0.0
        for a, w in act.items():
            if a in close_df.columns:
                pr += w * (close_df.iloc[i][a] / close_df.iloc[i-1][a] - 1)
        adj = (1 + pr) * (1 - comm) - 1
        hist.append(adj)
        row = {"date": close_df.index[i], "return": adj}
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
    return raw.shift(1)  # delay 1 month

def simulate_prod(portfolio, monthly_ret, signals, cash_ret, rebal_month=12):
    dates = monthly_ret.index
    current_val = 1.0
    pos = {t: current_val * c["w"] for t, c in portfolio.items()}
    vals = []
    for dt in dates:
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
        current_val = sum(pos.values())
        vals.append(current_val)
        if dt.month == rebal_month:
            pos = {t: current_val * c["w"] for t, c in portfolio.items()}
    return pd.Series(vals, index=dates)


# ================================================================
# METRICS
# ================================================================
def calc_monthly_metrics(ret_series, rf_monthly=0.0):
    nav = (1 + ret_series).cumprod()
    n_months = len(ret_series)
    years = n_months / 12
    if years < 0.5 or n_months < 6:
        return None
    annual = (nav.iloc[-1] ** (1/years) - 1) * 100
    excess = ret_series - rf_monthly
    sharpe = excess.mean() / excess.std() * np.sqrt(12) if excess.std() > 0 else 0
    vol = ret_series.std() * np.sqrt(12) * 100
    peak = nav.cummax()
    dd_series = (nav - peak) / peak
    dd = dd_series.min() * 100
    calmar = annual / abs(dd) if dd != 0 else 0
    win_rate = (ret_series > 0).mean() * 100
    yearly = {}
    for year in sorted(ret_series.index.year.unique()):
        yr_data = ret_series[ret_series.index.year == year]
        if len(yr_data) >= 3:
            yearly[year] = ((1 + yr_data).prod() - 1) * 100
    return {
        "annual": annual, "vol": vol, "sharpe": sharpe, "max_dd": dd,
        "calmar": calmar, "win_rate": win_rate, "years": years,
        "total_return": (nav.iloc[-1] - 1) * 100, "yearly": yearly,
        "nav": nav, "dd_series": dd_series,
    }

def calc_daily_metrics(ret_series, rf_daily, td):
    nav = (1 + ret_series).cumprod()
    years = (ret_series.index[-1] - ret_series.index[0]).days / 365.25
    if years < 0.5 or len(ret_series) < 50:
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


# ================================================================
# BOT CLASS
# ================================================================
class CombinedStrategyV3:
    def run(self):
        today_str = datetime.now().strftime("%Y%m%d")

        # ==============================================================
        # 1. FETCH DATA
        # ==============================================================
        cn_raw = {}
        cn_sources = {}
        with poe.start_message() as msg:
            msg.write("## 1. Fetching Data\n\n**A-Share:**\n")
            for secid in CN_ALL_CODES:
                df, source = fetch_cn_kline(secid)
                cn_raw[secid] = df
                cn_sources[secid] = source
                name = CN_NAMES.get(secid, secid)
                msg.write(f"  > {name} [{source}]: {len(df)} days "
                         f"{df.index[0].strftime('%Y-%m-%d')}~"
                         f"{df.index[-1].strftime('%Y-%m-%d')}\n")
                time.sleep(0.5)
        cn_close = pd.concat([cn_raw[s].rename(columns={"close": s})
                              for s in CN_ALL_CODES], axis=1).dropna()

        us_raw = {}
        us_sources = {}
        with poe.start_message() as msg:
            msg.write("\n**US ETF:**\n")
            for ticker in US_ALL_TICKERS:
                df, source = fetch_yahoo(ticker)
                if df is not None and len(df) > 50:
                    us_raw[ticker] = df
                    us_sources[ticker] = source
                    msg.write(f"  > {ticker} [{source}]: {len(df)} days "
                             f"{df.index[0].strftime('%Y-%m-%d')}~"
                             f"{df.index[-1].strftime('%Y-%m-%d')}\n")
                else:
                    msg.write(f"  > {ticker}: FAILED (all sources)\n")
                time.sleep(0.3)

        # Show fallback summary if any source used backup
        cn_fallbacks = [f"{CN_NAMES.get(k,k)}={v}" for k, v in cn_sources.items() if v != "EastMoney"]
        us_fallbacks = [f"{k}={v}" for k, v in us_sources.items() if v != "Yahoo"]
        if cn_fallbacks or us_fallbacks:
            with poe.start_message() as msg:
                msg.write("**Fallback sources used:**\n")
                if cn_fallbacks:
                    msg.write(f"  A-Share: {', '.join(cn_fallbacks)}\n")
                if us_fallbacks:
                    msg.write(f"  US: {', '.join(us_fallbacks)}\n")

        # Build close DataFrames
        rot_tickers = US_ROT_POOL + ["BIL"]
        us_rot_close = pd.concat(
            [us_raw[t][["close"]].rename(columns={"close": t}) for t in rot_tickers if t in us_raw],
            axis=1).ffill().dropna()

        prod_proxies = list(set([c["proxy"] for c in PROD_PORTFOLIO.values()] + [PROD_CASH]))
        us_prod_daily = pd.concat(
            [us_raw[t][["close"]].rename(columns={"close": t}) for t in prod_proxies if t in us_raw],
            axis=1).ffill().dropna()

        bil_daily_ret = us_rot_close["BIL"].pct_change()

        # ==============================================================
        # 2. RUN SUB-STRATEGIES
        # ==============================================================
        with poe.start_message() as msg:
            msg.write("\n## 2. Running Sub-Strategies\n\n")
            msg.write("**Sub-A (CN)**: 4idx+SZQZ, LB=20, AM=10, Thu Close\n")
            msg.write("**Sub-B (US-Rot)**: 8ETF, LB=120, Top3, TV=20%, ML=1.5, Model B\n")
            msg.write("**Sub-C (US-Prod)**: 10ETF AbsMom-6m, annual Dec rebalance\n\n")

        cn_result = run_cn_strategy(cn_close, CN_ALL_CODES)
        us_rot_result = run_us_rotation(us_rot_close, US_ROT_POOL)

        prod_monthly = us_prod_daily.resample("M").last()
        prod_monthly_ret = prod_monthly.pct_change()
        prod_signals = make_abs_mom_signals(prod_monthly, PROD_ABS_MOM_LB)
        prod_proxy_list = [c["proxy"] for c in PROD_PORTFOLIO.values()]
        req_cols = [c for c in prod_proxy_list + [PROD_CASH]
                    if c in prod_signals.columns and c in prod_monthly_ret.columns]
        valid = prod_signals[req_cols].notna().all(axis=1) & prod_monthly_ret[req_cols].notna().all(axis=1)
        prod_start = valid[valid].index[0]
        prod_ret_trimmed = prod_monthly_ret.loc[prod_start:]
        prod_sig_trimmed = prod_signals.loc[prod_start:]
        prod_cash_ret = prod_ret_trimmed[PROD_CASH]

        prod_nav_series = simulate_prod(PROD_PORTFOLIO, prod_ret_trimmed, prod_sig_trimmed,
                                         prod_cash_ret, PROD_REBAL_MONTH)
        prod_ret_series = prod_nav_series.pct_change().dropna()

        cn_start, cn_end = cn_result.index[0], cn_result.index[-1]
        rot_start, rot_end = us_rot_result.index[0], us_rot_result.index[-1]
        prod_start_dt = prod_ret_series.index[0]
        prod_end_dt = prod_ret_series.index[-1]

        cn_m = calc_daily_metrics(cn_result["return"], CN_RF_DAILY, CN_TRADING_DAYS)
        us_rf = bil_daily_ret.reindex(us_rot_result.index).fillna(0)
        us_excess = us_rot_result["return"] - us_rf
        us_nav = us_rot_result["nav"]
        us_yrs = (us_rot_result.index[-1] - us_rot_result.index[0]).days / 365.25
        us_rot_m = {
            "annual": (us_nav.iloc[-1] ** (1/us_yrs) - 1) * 100,
            "sharpe": us_excess.mean() / us_excess.std() * np.sqrt(US_TRADING_DAYS) if us_excess.std() > 0 else 0,
            "vol": us_rot_result["return"].std() * np.sqrt(US_TRADING_DAYS) * 100,
            "max_dd": ((us_nav / us_nav.cummax()) - 1).min() * 100,
            "years": us_yrs,
        }
        us_rot_m["calmar"] = us_rot_m["annual"] / abs(us_rot_m["max_dd"]) if us_rot_m["max_dd"] != 0 else 0

        prod_rf_m = prod_cash_ret.mean()
        prod_m = calc_monthly_metrics(prod_ret_series, prod_rf_m)

        with poe.start_message() as msg:
            msg.write(f"**Sub-A (CN)**: {cn_start.strftime('%Y-%m-%d')} ~ {cn_end.strftime('%Y-%m-%d')} ({cn_m['years']:.1f}Y)\n")
            msg.write(f"**Sub-B (US-Rot)**: {rot_start.strftime('%Y-%m-%d')} ~ {rot_end.strftime('%Y-%m-%d')} ({us_rot_m['years']:.1f}Y)\n")
            msg.write(f"**Sub-C (US-Prod)**: {prod_start_dt.strftime('%Y-%m')} ~ {prod_end_dt.strftime('%Y-%m')} ({prod_m['years']:.1f}Y)\n\n")

            msg.write("**Sub-Strategy Standalone:**\n\n")
            msg.write("| Metric | CN | US-Rot | US-Prod |\n")
            msg.write("|:-------|---:|-------:|--------:|\n")
            msg.write(f"| Annual | {cn_m['annual']:.1f}% | {us_rot_m['annual']:.1f}% | {prod_m['annual']:.1f}% |\n")
            msg.write(f"| Sharpe | {cn_m['sharpe']:.3f} | {us_rot_m['sharpe']:.3f} | {prod_m['sharpe']:.3f} |\n")
            msg.write(f"| MaxDD | {cn_m['max_dd']:.1f}% | {us_rot_m['max_dd']:.1f}% | {prod_m['max_dd']:.1f}% |\n")
            msg.write(f"| Calmar | {cn_m['calmar']:.3f} | {us_rot_m['calmar']:.3f} | {prod_m['calmar']:.3f} |\n")
            msg.write(f"| Vol | {cn_m['vol']:.1f}% | {us_rot_m['vol']:.1f}% | {prod_m['vol']:.1f}% |\n")

        # ==============================================================
        # 3. MONTHLY ALIGNMENT
        # ==============================================================
        cn_monthly = cn_result["return"].groupby(cn_result.index.to_period("M")).apply(
            lambda x: (1+x).prod()-1)
        rot_monthly = us_rot_result["return"].groupby(us_rot_result.index.to_period("M")).apply(
            lambda x: (1+x).prod()-1)
        prod_monthly_aligned = prod_ret_series.copy()
        prod_monthly_aligned.index = prod_monthly_aligned.index.to_period("M")

        common_months = cn_monthly.index.intersection(rot_monthly.index).intersection(prod_monthly_aligned.index)
        cn_m_aligned = cn_monthly.loc[common_months]
        rot_m_aligned = rot_monthly.loc[common_months]
        prod_m_aligned = prod_monthly_aligned.loc[common_months]

        overlap_start = common_months[0]
        overlap_end = common_months[-1]

        with poe.start_message() as msg:
            msg.write(f"\n## 3. Combined Portfolio (Monthly Aligned)\n\n")
            msg.write(f"  Overlap: {overlap_start} ~ {overlap_end} ({len(common_months)} months)\n\n")

        corr_df = pd.DataFrame({"CN": cn_m_aligned.values,
                                 "US-Rot": rot_m_aligned.values,
                                 "US-Prod": prod_m_aligned.values})
        corr_matrix = corr_df.corr()

        with poe.start_message() as msg:
            msg.write("**Monthly Correlation Matrix:**\n\n")
            msg.write("| | CN | US-Rot | US-Prod |\n")
            msg.write("|:---|---:|------:|-------:|\n")
            for name in ["CN", "US-Rot", "US-Prod"]:
                msg.write(f"| {name} | {corr_matrix.loc[name,'CN']:.3f} | "
                         f"{corr_matrix.loc[name,'US-Rot']:.3f} | "
                         f"{corr_matrix.loc[name,'US-Prod']:.3f} |\n")

        # ==============================================================
        # 4. GRID SEARCH
        # ==============================================================
        STEP = 0.10
        bil_monthly_ret = bil_daily_ret.groupby(bil_daily_ret.index.to_period("M")).apply(
            lambda x: (1+x).prod()-1)
        rf_monthly = bil_monthly_ret.reindex(common_months).fillna(0).mean()

        grid_results = {}
        for w_cn_i in range(0, 11):
            for w_rot_i in range(0, 11 - w_cn_i):
                w_prod_i = 10 - w_cn_i - w_rot_i
                w_cn = w_cn_i * STEP
                w_rot = w_rot_i * STEP
                w_prod = w_prod_i * STEP
                port_ret = w_cn * cn_m_aligned + w_rot * rot_m_aligned + w_prod * prod_m_aligned
                port_ret.index = port_ret.index.to_timestamp(how="end")
                m = calc_monthly_metrics(port_ret, rf_monthly)
                if m:
                    label = f"CN{w_cn_i*10}-Rot{w_rot_i*10}-Prod{w_prod_i*10}"
                    grid_results[label] = {
                        "metrics": m, "w_cn": w_cn, "w_rot": w_rot, "w_prod": w_prod
                    }

        best_sha_label = max(grid_results, key=lambda k: grid_results[k]["metrics"]["sharpe"])
        best_sha = grid_results[best_sha_label]
        best_cal_label = max(grid_results, key=lambda k: grid_results[k]["metrics"]["calmar"])
        best_cal = grid_results[best_cal_label]

        key_labels = [
            "CN100-Rot0-Prod0", "CN0-Rot100-Prod0", "CN0-Rot0-Prod100",
            "CN0-Rot50-Prod50",
            "CN30-Rot70-Prod0",
            "CN30-Rot50-Prod20",
            "CN20-Rot50-Prod30",
            "CN20-Rot40-Prod40",
            "CN30-Rot40-Prod30",
            best_sha_label, best_cal_label,
        ]
        key_labels = list(dict.fromkeys([l for l in key_labels if l in grid_results]))

        top_by_sharpe = sorted(grid_results.items(), key=lambda x: x[1]["metrics"]["sharpe"], reverse=True)[:15]

        with poe.start_message() as msg:
            msg.write(f"**Top 15 Allocations by Sharpe (Grid 10% step):**\n\n")
            msg.write("| Rank | Allocation | Sharpe | Annual | MaxDD | Calmar | Vol | WR(M) |\n")
            msg.write("|:-----|:-----------|-------:|-------:|------:|-------:|----:|------:|\n")
            for i, (label, r) in enumerate(top_by_sharpe):
                m = r["metrics"]
                bold = "**" if label == best_sha_label else ""
                msg.write(f"| {i+1} | {bold}{label}{bold} | {bold}{m['sharpe']:.3f}{bold} | "
                         f"{m['annual']:.1f}% | {m['max_dd']:.1f}% | {m['calmar']:.3f} | "
                         f"{m['vol']:.1f}% | {m['win_rate']:.1f}% |\n")

        with poe.start_message() as msg:
            msg.write(f"\n**Best Sharpe: {best_sha_label}** -> Sharpe={best_sha['metrics']['sharpe']:.3f}, "
                     f"Ann={best_sha['metrics']['annual']:.1f}%, DD={best_sha['metrics']['max_dd']:.1f}%\n")
            if best_cal_label != best_sha_label:
                msg.write(f"**Best Calmar: {best_cal_label}** -> Calmar={best_cal['metrics']['calmar']:.3f}, "
                         f"Sharpe={best_cal['metrics']['sharpe']:.3f}, DD={best_cal['metrics']['max_dd']:.1f}%\n")

        # ==============================================================
        # 5. YEARLY RETURNS
        # ==============================================================
        all_years = sorted(set().union(*[
            r["metrics"]["yearly"].keys() for l, r in grid_results.items() if l in key_labels
        ]))

        with poe.start_message() as msg:
            msg.write(f"\n## 4. Yearly Returns\n\n")
            hdr = "| Year |"
            for l in key_labels:
                short = l.replace("CN", "C").replace("Rot", "R").replace("Prod", "P")
                hdr += f" {short} |"
            msg.write(hdr + "\n")
            msg.write("|:-----|" + "------:|" * len(key_labels) + "\n")
            for yr in all_years:
                line = f"| {yr} |"
                for l in key_labels:
                    v = grid_results[l]["metrics"]["yearly"].get(yr, 0)
                    line += f" {v:+.1f}% |"
                msg.write(line + "\n")

        # ==============================================================
        # 6. PERIOD STABILITY
        # ==============================================================
        periods = [
            ("Full", None, None),
            ("2015-2017", "2015-01-01", "2017-12-31"),
            ("2018-2019", "2018-01-01", "2019-12-31"),
            ("2020-2022", "2020-01-01", "2022-12-31"),
            ("2023-now", "2023-01-01", None),
        ]

        with poe.start_message() as msg:
            msg.write(f"\n## 5. Period Stability (Sharpe)\n\n")
            hdr = "| Period |"
            for l in key_labels[:6]:
                short = l.replace("CN", "C").replace("Rot", "R").replace("Prod", "P")
                hdr += f" {short} |"
            msg.write(hdr + "\n")
            msg.write("|:-------|" + "------:|" * min(6, len(key_labels)) + "\n")
            for pname, start, end in periods:
                line = f"| {pname} |"
                for l in key_labels[:6]:
                    nav = grid_results[l]["metrics"]["nav"]
                    sub_nav = nav.copy()
                    if start:
                        sub_nav = sub_nav[sub_nav.index >= pd.Timestamp(start)]
                    if end:
                        sub_nav = sub_nav[sub_nav.index <= pd.Timestamp(end)]
                    if len(sub_nav) < 6:
                        line += " N/A |"
                        continue
                    sub_ret = sub_nav.pct_change().dropna()
                    if len(sub_ret) < 6:
                        line += " N/A |"
                        continue
                    excess = sub_ret - rf_monthly
                    sha = excess.mean() / excess.std() * np.sqrt(12) if excess.std() > 0 else 0
                    line += f" {sha:.3f} |"
                msg.write(line + "\n")

        # ==============================================================
        # 7. CHARTS
        # ==============================================================
        with poe.start_message() as msg:
            msg.write(f"\n## 6. Generating Charts...\n")

        plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
        cmap = plt.cm.tab10
        fig = plt.figure(figsize=(24, 34))
        gs = gridspec.GridSpec(6, 2, height_ratios=[3, 2, 2.5, 2, 2, 2], hspace=0.38, wspace=0.3)

        colors = {}
        for i, l in enumerate(key_labels):
            colors[l] = cmap(i % 10)
        colors["CN100-Rot0-Prod0"] = "#e74c3c"
        colors["CN0-Rot100-Prod0"] = "#2c3e50"
        colors["CN0-Rot0-Prod100"] = "#8e44ad"
        if best_sha_label not in ("CN100-Rot0-Prod0", "CN0-Rot100-Prod0", "CN0-Rot0-Prod100"):
            colors[best_sha_label] = "#f39c12"

        ax1 = fig.add_subplot(gs[0, :])
        for l in key_labels:
            if l not in grid_results:
                continue
            m = grid_results[l]["metrics"]
            c = colors.get(l, cmap(key_labels.index(l) % 10))
            lw = 2.5 if l == best_sha_label else (2.0 if "100" in l else 1.3)
            ls = "-" if l == best_sha_label else ("--" if "100" in l.split("-")[0][2:] else "-.")
            short = l.replace("CN", "C").replace("Rot", "R").replace("Prod", "P")
            ax1.plot(m["nav"].index, m["nav"],
                     label=f"{short} (S={m['sharpe']:.2f} A={m['annual']:.1f}%)",
                     color=c, linewidth=lw, linestyle=ls)
        ax1.set_yscale("log")
        ax1.set_title(f"3-Strategy Combined NAV ({overlap_start}~{overlap_end})",
                      fontsize=14, fontweight="bold")
        ax1.legend(fontsize=8, ncol=2)
        ax1.grid(True, alpha=0.3)
        ax1.set_ylabel("NAV (log)")

        ax2 = fig.add_subplot(gs[1, :])
        for l in key_labels[:6]:
            if l not in grid_results:
                continue
            m = grid_results[l]["metrics"]
            c = colors.get(l, cmap(key_labels.index(l) % 10))
            short = l.replace("CN", "C").replace("Rot", "R").replace("Prod", "P")
            ax2.plot(m["dd_series"].index, m["dd_series"] * 100,
                     label=f"{short} ({m['max_dd']:.1f}%)", color=c, linewidth=1.5)
        ax2.set_title("Drawdown Comparison", fontsize=13, fontweight="bold")
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=0.3)
        ax2.set_ylabel("Drawdown %")

        ax3 = fig.add_subplot(gs[2, 0])
        steps = list(range(0, 110, 10))
        sha_grid = np.full((len(steps), len(steps)), np.nan)
        for i, w_cn_pct in enumerate(steps):
            for j, w_rot_pct in enumerate(steps):
                w_prod_pct = 100 - w_cn_pct - w_rot_pct
                if w_prod_pct < 0 or w_prod_pct > 100:
                    continue
                label = f"CN{w_cn_pct}-Rot{w_rot_pct}-Prod{w_prod_pct}"
                if label in grid_results:
                    sha_grid[i, j] = grid_results[label]["metrics"]["sharpe"]
        im = ax3.imshow(sha_grid, origin="lower", cmap="RdYlGn", aspect="auto",
                         extent=[-5, 105, -5, 105])
        ax3.set_xlabel("US-Rot %")
        ax3.set_ylabel("CN %")
        ax3.set_title("Sharpe Heatmap\n(Prod = 100% - CN% - Rot%)", fontsize=12, fontweight="bold")
        plt.colorbar(im, ax=ax3, shrink=0.8)
        best_cn_pct = int(best_sha["w_cn"] * 100)
        best_rot_pct = int(best_sha["w_rot"] * 100)
        ax3.plot(best_rot_pct, best_cn_pct, "r*", markersize=20)
        ax3.annotate(f"Best S={best_sha['metrics']['sharpe']:.3f}",
                     (best_rot_pct, best_cn_pct), fontsize=8, color="red",
                     xytext=(5, 5), textcoords="offset points", fontweight="bold")

        ax3b = fig.add_subplot(gs[2, 1])
        cal_grid = np.full((len(steps), len(steps)), np.nan)
        for i, w_cn_pct in enumerate(steps):
            for j, w_rot_pct in enumerate(steps):
                w_prod_pct = 100 - w_cn_pct - w_rot_pct
                if w_prod_pct < 0 or w_prod_pct > 100:
                    continue
                label = f"CN{w_cn_pct}-Rot{w_rot_pct}-Prod{w_prod_pct}"
                if label in grid_results:
                    cal_grid[i, j] = grid_results[label]["metrics"]["calmar"]
        im2 = ax3b.imshow(cal_grid, origin="lower", cmap="RdYlGn", aspect="auto",
                           extent=[-5, 105, -5, 105])
        ax3b.set_xlabel("US-Rot %")
        ax3b.set_ylabel("CN %")
        ax3b.set_title("Calmar Heatmap\n(Prod = 100% - CN% - Rot%)", fontsize=12, fontweight="bold")
        plt.colorbar(im2, ax=ax3b, shrink=0.8)
        best_cal_cn = int(best_cal["w_cn"] * 100)
        best_cal_rot = int(best_cal["w_rot"] * 100)
        ax3b.plot(best_cal_rot, best_cal_cn, "r*", markersize=20)
        ax3b.annotate(f"Best C={best_cal['metrics']['calmar']:.3f}",
                      (best_cal_rot, best_cal_cn), fontsize=8, color="red",
                      xytext=(5, 5), textcoords="offset points", fontweight="bold")

        ax4 = fig.add_subplot(gs[3, 0])
        ax4.plot(cn_result.index, cn_result["nav"], color="#e74c3c", linewidth=2,
                 label=f"CN (S={cn_m['sharpe']:.2f} A={cn_m['annual']:.1f}%)")
        ax4.plot(us_rot_result.index, us_rot_result["nav"], color="#2c3e50", linewidth=2,
                 label=f"US-Rot (S={us_rot_m['sharpe']:.2f} A={us_rot_m['annual']:.1f}%)")
        prod_nav_plot = prod_nav_series.copy()
        ax4.plot(prod_nav_plot.index, prod_nav_plot.values, color="#8e44ad", linewidth=2,
                 label=f"US-Prod (S={prod_m['sharpe']:.2f} A={prod_m['annual']:.1f}%)")
        ax4.set_yscale("log")
        ax4.set_title("Sub-Strategy NAV (standalone)", fontsize=12, fontweight="bold")
        ax4.legend(fontsize=8)
        ax4.grid(True, alpha=0.3)
        ax4.set_ylabel("NAV (log)")

        ax4b = fig.add_subplot(gs[3, 1])
        im3 = ax4b.imshow(corr_matrix.values, cmap="coolwarm", vmin=-0.5, vmax=1.0, aspect="auto")
        ax4b.set_xticks(range(3))
        ax4b.set_xticklabels(["CN", "US-Rot", "US-Prod"], fontsize=10)
        ax4b.set_yticks(range(3))
        ax4b.set_yticklabels(["CN", "US-Rot", "US-Prod"], fontsize=10)
        for i in range(3):
            for j in range(3):
                ax4b.text(j, i, f"{corr_matrix.values[i, j]:.3f}", ha="center", va="center",
                          fontsize=14, fontweight="bold",
                          color="white" if abs(corr_matrix.values[i, j]) > 0.5 else "black")
        ax4b.set_title("Monthly Correlation Matrix", fontsize=12, fontweight="bold")
        plt.colorbar(im3, ax=ax4b, shrink=0.8)

        ax5 = fig.add_subplot(gs[4, :])
        show_labels = key_labels[:5]
        n_alloc = len(show_labels)
        x = np.arange(len(all_years))
        w_bar = 0.8 / n_alloc
        for i, l in enumerate(show_labels):
            if l not in grid_results:
                continue
            vals = [grid_results[l]["metrics"]["yearly"].get(y, 0) for y in all_years]
            c = colors.get(l, cmap(i % 10))
            short = l.replace("CN", "C").replace("Rot", "R").replace("Prod", "P")
            ax5.bar(x + i * w_bar - 0.4 + w_bar/2, vals, w_bar, label=short, color=c, alpha=0.8)
        ax5.set_xticks(x)
        ax5.set_xticklabels([str(y) for y in all_years], fontsize=8, rotation=45)
        ax5.set_ylabel("Return %")
        ax5.set_title("Yearly Returns by Allocation", fontsize=13, fontweight="bold")
        ax5.legend(fontsize=7, ncol=5)
        ax5.grid(True, alpha=0.3, axis="y")
        ax5.axhline(0, color="black", linewidth=0.5)

        ax6 = fig.add_subplot(gs[5, 0])
        ax6.axis("off")
        summary = (
            f"3-Strategy Combined Portfolio\n"
            f"{'='*42}\n\n"
            f"Best Sharpe: {best_sha_label}\n"
            f"  CN={best_sha['w_cn']:.0%} Rot={best_sha['w_rot']:.0%} Prod={best_sha['w_prod']:.0%}\n\n"
            f"Sharpe:     {best_sha['metrics']['sharpe']:.3f}\n"
            f"Annual:     {best_sha['metrics']['annual']:.1f}%\n"
            f"MaxDD:      {best_sha['metrics']['max_dd']:.1f}%\n"
            f"Calmar:     {best_sha['metrics']['calmar']:.3f}\n"
            f"Total:      {best_sha['metrics']['total_return']:.1f}%\n"
            f"WinRate(M): {best_sha['metrics']['win_rate']:.1f}%\n"
            f"Period:     {best_sha['metrics']['years']:.1f}yr\n\n"
            f"Correlations:\n"
            f"  CN vs Rot:  {corr_matrix.loc['CN','US-Rot']:.3f}\n"
            f"  CN vs Prod: {corr_matrix.loc['CN','US-Prod']:.3f}\n"
            f"  Rot vs Prod:{corr_matrix.loc['US-Rot','US-Prod']:.3f}"
        )
        ax6.text(0.05, 0.95, summary, transform=ax6.transAxes, fontsize=11,
                 verticalalignment="top", fontfamily="monospace",
                 bbox=dict(boxstyle="round,pad=0.5", facecolor="#ecf0f1", alpha=0.8))

        ax6b = fig.add_subplot(gs[5, 1])
        ax6b.axis("off")
        v2_best = grid_results.get("CN30-Rot70-Prod0", {}).get("metrics", {})
        rot_prod = grid_results.get("CN0-Rot50-Prod50", {}).get("metrics", {})
        three_way = best_sha["metrics"]
        compare_text = (
            f"2-Way vs 3-Way Comparison\n"
            f"{'='*42}\n\n"
            f"{'Metric':<12s} {'CN30-R70':<12s} {'R50-P50':<12s} {'Best3':<12s}\n"
            f"{'-'*48}\n"
        )
        if v2_best:
            compare_text += f"{'Sharpe':<12s} {v2_best.get('sharpe',0):<12.3f} {rot_prod.get('sharpe',0):<12.3f} {three_way['sharpe']:<12.3f}\n"
            compare_text += f"{'Annual':<12s} {v2_best.get('annual',0):<11.1f}% {rot_prod.get('annual',0):<11.1f}% {three_way['annual']:<11.1f}%\n"
            compare_text += f"{'MaxDD':<12s} {v2_best.get('max_dd',0):<11.1f}% {rot_prod.get('max_dd',0):<11.1f}% {three_way['max_dd']:<11.1f}%\n"
            compare_text += f"{'Calmar':<12s} {v2_best.get('calmar',0):<12.3f} {rot_prod.get('calmar',0):<12.3f} {three_way['calmar']:<12.3f}\n"
            compare_text += f"{'Vol':<12s} {v2_best.get('vol',0):<11.1f}% {rot_prod.get('vol',0):<11.1f}% {three_way['vol']:<11.1f}%\n"
        ax6b.text(0.05, 0.95, compare_text, transform=ax6b.transAxes, fontsize=11,
                  verticalalignment="top", fontfamily="monospace",
                  bbox=dict(boxstyle="round,pad=0.5", facecolor="#E3F2FD", alpha=0.8))

        fig.suptitle(
            "3-Strategy Combined: CN(4idx+SZQZ) + US-Rot(8ETF LB120 TV20%) + US-Prod(10ETF AbsMom6m)",
            fontsize=14, fontweight="bold", y=1.01)
        plt.tight_layout(rect=[0, 0, 1, 0.97])

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        chart_bytes = buf.read()

        with poe.start_message() as msg:
            msg.write("## Charts\n\n")
            att = msg.attach_file(name="combined_v3.png", contents=chart_bytes,
                                  content_type="image/png", is_inline=True)
            msg.write(f"{att.inline_ref}\n")

        # ==============================================================
        # 8. EXCEL
        # ==============================================================
        excel_buf = io.BytesIO()
        wb = xlsxwriter.Workbook(excel_buf, {"in_memory": True})
        fh = wb.add_format({"bold": True, "bg_color": "#1a5276", "font_color": "white",
                             "border": 1, "align": "center", "text_wrap": True})
        fn = wb.add_format({"num_format": "0.000", "border": 1, "align": "center"})
        fn2 = wb.add_format({"num_format": "0.00", "border": 1, "align": "center"})
        fpct = wb.add_format({"num_format": "0.0%", "border": 1, "align": "center"})
        fstr = wb.add_format({"border": 1, "align": "center"})
        fgood = wb.add_format({"bg_color": "#27AE60", "font_color": "white", "border": 1,
                                "num_format": "0.0%", "align": "center"})
        fbad = wb.add_format({"bg_color": "#E74C3C", "font_color": "white", "border": 1,
                               "num_format": "0.0%", "align": "center"})
        fbest = wb.add_format({"bg_color": "#FFF9C4", "border": 1, "num_format": "0.000",
                                "align": "center"})

        ws1 = wb.add_worksheet("All Allocations")
        h1 = ["Allocation", "CN%", "Rot%", "Prod%", "Sharpe", "Annual", "MaxDD",
              "Calmar", "Vol", "WinRate", "Total Ret"]
        for j, h in enumerate(h1):
            ws1.write(0, j, h, fh)
            ws1.set_column(j, j, 16 if j == 0 else 12)
        sorted_all = sorted(grid_results.items(), key=lambda x: x[1]["metrics"]["sharpe"], reverse=True)
        for i, (label, r) in enumerate(sorted_all):
            m = r["metrics"]
            row = i + 1
            is_best = label == best_sha_label
            sf = fbest if is_best else fstr
            nf = fbest if is_best else fn
            pf = fbest if is_best else fpct
            ws1.write(row, 0, label, sf)
            ws1.write(row, 1, r["w_cn"], pf)
            ws1.write(row, 2, r["w_rot"], pf)
            ws1.write(row, 3, r["w_prod"], pf)
            ws1.write(row, 4, m["sharpe"], nf)
            ws1.write(row, 5, m["annual"]/100, pf)
            ws1.write(row, 6, m["max_dd"]/100, pf)
            ws1.write(row, 7, m["calmar"], nf)
            ws1.write(row, 8, m["vol"]/100, pf)
            ws1.write(row, 9, m["win_rate"]/100, pf)
            ws1.write(row, 10, m["total_return"]/100, pf)

        ws2 = wb.add_worksheet("Yearly Returns")
        ws2.write(0, 0, "Year", fh)
        for j, l in enumerate(key_labels):
            ws2.write(0, j+1, l, fh)
            ws2.set_column(j+1, j+1, 20)
        ws2.set_column(0, 0, 8)
        for i, yr in enumerate(all_years):
            ws2.write(i+1, 0, yr, fstr)
            for j, l in enumerate(key_labels):
                v = grid_results[l]["metrics"]["yearly"].get(yr, None)
                if v is not None:
                    ws2.write(i+1, j+1, v/100, fgood if v > 0 else fbad)

        ws3 = wb.add_worksheet(f"Monthly ({best_sha_label[:20].replace('/','-')})")
        best_port_ret = (best_sha["w_cn"] * cn_m_aligned +
                         best_sha["w_rot"] * rot_m_aligned +
                         best_sha["w_prod"] * prod_m_aligned)
        ws3.write(0, 0, "Month", fh)
        ws3.write(0, 1, "CN Ret", fh)
        ws3.write(0, 2, "US-Rot Ret", fh)
        ws3.write(0, 3, "US-Prod Ret", fh)
        ws3.write(0, 4, "Combined", fh)
        ws3.write(0, 5, "NAV", fh)
        ws3.set_column(0, 0, 12)
        for j in range(1, 6):
            ws3.set_column(j, j, 14)
        comb_nav = (1 + best_port_ret).cumprod()
        fpct2 = wb.add_format({"num_format": "0.00%", "border": 1, "align": "center"})
        for i, mo in enumerate(common_months):
            ws3.write(i+1, 0, str(mo), fstr)
            ws3.write(i+1, 1, cn_m_aligned.iloc[i], fpct2)
            ws3.write(i+1, 2, rot_m_aligned.iloc[i], fpct2)
            ws3.write(i+1, 3, prod_m_aligned.iloc[i], fpct2)
            ws3.write(i+1, 4, best_port_ret.iloc[i], fpct2)
            ws3.write(i+1, 5, comb_nav.iloc[i], fn)

        ws4 = wb.add_worksheet("Charts")
        ws4.insert_image("A1", "c.png", {"image_data": io.BytesIO(chart_bytes),
                                           "x_scale": 0.35, "y_scale": 0.35})

        wb.close()
        excel_buf.seek(0)
        excel_bytes = excel_buf.read()

        with poe.start_message() as msg:
            msg.write("## Excel Output\n\n")
            msg.attach_file(
                name=f"Combined_3Strategy_V3_{today_str}.xlsx",
                contents=excel_bytes,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            msg.write("\n**4 Sheets:**\n")
            msg.write("1. **All Allocations** - 66 combos sorted by Sharpe\n")
            msg.write("2. **Yearly Returns** - Key allocations year-by-year\n")
            msg.write(f"3. **Monthly** - Best allocation monthly CN/Rot/Prod/Combined\n")
            msg.write("4. **Charts** - Summary chart\n")

        # ==============================================================
        # 9. FINAL SUMMARY
        # ==============================================================
        cn100 = grid_results.get("CN100-Rot0-Prod0", {}).get("metrics", {})
        rot100 = grid_results.get("CN0-Rot100-Prod0", {}).get("metrics", {})
        prod100 = grid_results.get("CN0-Rot0-Prod100", {}).get("metrics", {})
        v2_best_m = grid_results.get("CN30-Rot70-Prod0", {}).get("metrics", {})

        with poe.start_message() as msg:
            msg.write(f"\n## Final Summary\n\n")
            msg.write(f"**Sub-Strategies:**\n")
            msg.write(f"- CN: 4idx+SZQZ, LB=20, AM=10\n")
            msg.write(f"- US-Rot: 8ETF, LB=120, Top3, TV=20%, ML=1.5, ModelB\n")
            msg.write(f"- US-Prod: 10ETF, AbsMom-6m, Dec rebalance\n\n")

            msg.write(f"| Metric | CN only | Rot only | Prod only | 2-way(CN30-R70) | **{best_sha_label}** |\n")
            msg.write(f"|:-------|--------:|---------:|----------:|:---------------:|:-------:|\n")
            for name, key, fmt, suffix in [
                ("Sharpe", "sharpe", ".3f", ""),
                ("Annual", "annual", ".1f", "%"),
                ("MaxDD", "max_dd", ".1f", "%"),
                ("Calmar", "calmar", ".3f", ""),
                ("Vol", "vol", ".1f", "%"),
                ("WinRate", "win_rate", ".1f", "%"),
            ]:
                vc = cn100.get(key, 0)
                vr = rot100.get(key, 0)
                vp = prod100.get(key, 0)
                v2 = v2_best_m.get(key, 0) if v2_best_m else 0
                vb = best_sha["metrics"][key]
                msg.write(f"| {name} | {vc:{fmt}}{suffix} | {vr:{fmt}}{suffix} | "
                         f"{vp:{fmt}}{suffix} | {v2:{fmt}}{suffix} | **{vb:{fmt}}{suffix}** |\n")

            msg.write(f"\n**Diversification:**\n")
            msg.write(f"- CN <-> US-Rot: {corr_matrix.loc['CN','US-Rot']:.3f}\n")
            msg.write(f"- CN <-> US-Prod: {corr_matrix.loc['CN','US-Prod']:.3f}\n")
            msg.write(f"- US-Rot <-> US-Prod: {corr_matrix.loc['US-Rot','US-Prod']:.3f}\n")

            if v2_best_m:
                sha_gain = best_sha["metrics"]["sharpe"] - v2_best_m.get("sharpe", 0)
                dd_gain = best_sha["metrics"]["max_dd"] - v2_best_m.get("max_dd", 0)
                msg.write(f"\n**3-Way vs 2-Way (CN30-R70):**\n")
                msg.write(f"- Sharpe: {sha_gain:+.3f}\n")
                msg.write(f"- MaxDD: {dd_gain:+.1f}%\n")


if __name__ == "__main__":
    bot = CombinedStrategyV3()
    bot.run()

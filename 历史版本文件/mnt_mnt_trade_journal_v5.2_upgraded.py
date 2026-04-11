# poe: name=Trade-Journal-V5
# poe: privacy_shield=half
"""V5"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import io
import re
import json
import xlsxwriter
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi_poe.types import SettingsResponse

# ─────────────────────────────────────────────
# A股 Sub-A 双动量策略
# ─────────────────────────────────────────────
CN_COMMISSION = 0.001
CN_RF_ANNUAL = 0.03
CN_TRADING_DAYS = 244
CN_RF_DAILY = (1 + CN_RF_ANNUAL) ** (1 / CN_TRADING_DAYS) - 1

CN_LOOKBACK = 20
CN_ABS_MOM_LB = 20
CN_VOL_RANK_LB = 10
CN_COOLDOWN_DAYS = 3
CN_MA_WINDOW = 20
CN_MA_FILTER_MODE = "turning"  # "turning" = MA拐头向下→cash, "level" = price<MA→cash

CN_STOCK_CODES = ["1.515100", "0.159915", "1.000300", "1.000852", "1.000905"]
CN_NAMES = {
    "1.515100": "ZZHL-ETF",
    "0.159915": "CYB-ETF",
    "1.000300": "HS300",
    "1.000852": "ZZ1000",
    "1.000905": "ZZ500",
    "cash": "Cash",
}
CN_HS300_SECID = "1.000300"  # 提取：MA过滤中使用的沪深300代码

# A股 ETF/指数 映射
CN_ZZHL_INDEX_SECID = "1.H30269"
CN_ZZHL_ETF_SECID = "1.515100"
CN_ZZHL_ETF_START = pd.Timestamp("2020-07-03")
CN_CYB_INDEX_SECID = "0.399006"
CN_CYB_ETF_SECID = "0.159915"
CN_CYB_ETF_START = pd.Timestamp("2011-12-09")

# ─────────────────────────────────────────────
# A股 Sub-A-DK 多空策略
# ─────────────────────────────────────────────
CN_DK_ZZ1000_CODE = "000852"
CN_DK_SZ50_CODE = "000016"
CN_DK_ZZ1000_SECID = "1.000852"
CN_DK_SZ50_SECID = "1.000016"
CN_DK_MOM_LB = 20
CN_DK_COLS = ["DK_ZZ1000", "DK_SZ50"]
CN_DK_NAMES = {"DK_ZZ1000": "中证1000", "DK_SZ50": "上证50"}
CN_DK_TARGET_VOL = 0.15
CN_DK_VOL_WINDOW = 30
CN_DK_MAX_LEV = 1.5
CN_DK_MIN_LEV = 0.1
CN_DK_TRADING_DAYS = 242
CN_DK_COOLDOWN_DAYS = 5
CN_DK_NAV_MA_FILTER = 300  # 净值曲线MA窗口(用于展示)
CN_DK_USE_NAV_FILTER = False  # False=仅展示,不参与交易; True=NAV<MA时强制空仓

# ─────────────────────────────────────────────
# 美股 Sub-B 轮动策略
# ─────────────────────────────────────────────
US_ROT_COMMISSION = 0.001
US_TRADING_DAYS = 252
US_ROT_ASSETS = {
    "VOO":  {"proxy": "SPY",     "label": "S&P 500"},
    "QQQM": {"proxy": "QQQ",     "label": "Nasdaq 100"},
    "EMXC": {"proxy": "EMXC",    "label": "新兴市场(除中国)"},
    "VEA":  {"proxy": "EFA",     "label": "发达市场"},
    "GLDM": {"proxy": "GLD",     "label": "黄金"},
    "VGLT": {"proxy": "TLT",     "label": "长期国债"},
    "SCHH": {"proxy": "VNQ",     "label": "REITs"},
    "PDBC": {"proxy": "DBC",     "label": "大宗商品"},
    "IBIT": {"proxy": "BTC-USD", "label": "比特币"},
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
US_ROT_ABS_THRESHOLD = 0.0
US_ROT_REBALANCE_THRESHOLD = 1.3  # 新资产需 > 最弱持仓 × 1.3x 才替换
US_ROT_BTC_TICKER = "BTC-USD"
US_ROT_BTC_START = pd.Timestamp("2022-01-01")
US_ROT_BTC_MAX_W = 0.30
US_ROT_EMXC_BT_START = pd.Timestamp("2017-08-01")
US_ROT_EMXC_BT_PROXY = "EEM"

# VolReg 风控: SPY短期/长期波动率比 > 阈值时次日转现金
US_ROT_VOLREG_ENABLED = True
US_ROT_VOLREG_SHORT_W = 10      # 短期波动率窗口(交易日)
US_ROT_VOLREG_LONG_W = 250      # 长期波动率窗口(交易日)
US_ROT_VOLREG_THRESHOLD = 2.0   # 短/长波动率比触发阈值

# ─────────────────────────────────────────────
# 美股 Sub-C 生产组合
# ─────────────────────────────────────────────
PROD_USE_TIMING = False
PROD_ABS_MOM_LB = 6
PROD_SMA_WINDOW = 12
PROD_SMA_BAND = 0.03
PROD_BLEND_A = 0.5
PROD_COMMISSION = 0.001
PROD_REBAL_MONTH = 12
PROD_CASH = "BIL"
PROD_PORTFOLIO = {
    "VTI":   {"w": 0.30, "label": "US Total Market",    "proxy": "VTI",     "cls": "equity"},
    "QQQM":  {"w": 0.10, "label": "US Nasdaq 100",      "proxy": "QQQ",     "cls": "equity"},
    "VEA":   {"w": 0.20, "label": "Intl Developed",     "proxy": "VEA",     "cls": "equity"},
    "VGIT":  {"w": 0.15, "label": "US Interm Treasury",  "proxy": "VGIT",    "cls": "bond"},
    "DBMF":  {"w": 0.05, "label": "Managed Futures",    "proxy": "DBMF",    "cls": "alt"},
    "GLDM":  {"w": 0.15, "label": "Gold",               "proxy": "GLD",     "cls": "commodity"},
    "IBIT":  {"w": 0.05, "label": "Bitcoin",            "proxy": "BTC-USD", "cls": "crypto"},
}

BTC_BT_START = pd.Timestamp("2022-01-01")
DBMF_BT_START = pd.Timestamp("2019-06-01")

# ─────────────────────────────────────────────
# 派生计算（自动从上方配置生成）
# ─────────────────────────────────────────────

# PROD_PORTFOLIO_BT: 排除 IBIT 后重新归一化权重
PROD_PORTFOLIO_BT = {}
_bt_remaining = sum(c["w"] for _n, c in PROD_PORTFOLIO.items() if _n != "IBIT")
for _n, _c in PROD_PORTFOLIO.items():
    if _n == "IBIT":
        continue
    PROD_PORTFOLIO_BT[_n] = {**_c, "w": _c["w"] / _bt_remaining}

# PROD_PORTFOLIO_PRE_DBMF: 排除 IBIT+DBMF，DBMF权重归入VGIT
PROD_PORTFOLIO_PRE_DBMF = {}
_dbmf_w = PROD_PORTFOLIO["DBMF"]["w"]
_pre_dbmf_rest = sum(c["w"] for _n, c in PROD_PORTFOLIO.items() if _n not in ("IBIT", "DBMF"))
for _n, _c in PROD_PORTFOLIO.items():
    if _n in ("IBIT", "DBMF"):
        continue
    _w = _c["w"] + (_dbmf_w if _n == "VGIT" else 0)
    PROD_PORTFOLIO_PRE_DBMF[_n] = {**_c, "w": _w / (_pre_dbmf_rest + _dbmf_w)}

# 全部美股Ticker合集
US_ALL_TICKERS = sorted(set(
    US_ROT_POOL + ["BIL", US_ROT_EMXC_BT_PROXY] +
    [c["proxy"] for c in PROD_PORTFOLIO.values()]
))

# ─────────────────────────────────────────────
# 组合权重
# ─────────────────────────────────────────────
COMBINED_WEIGHTS = {"Sub-A": 0.15, "Sub-A-DK": 0.15, "Sub-B": 0.40, "Sub-C": 0.30}

# trade_journal 中也引用为 STRATEGY_WEIGHTS
STRATEGY_WEIGHTS = COMBINED_WEIGHTS

# 清理临时变量
del _bt_remaining, _n, _c, _dbmf_w, _pre_dbmf_rest, _w
def _sm():
    return poe.start_message()

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


# 数据获取/解析相关的可恢复异常 — 真正的bug（AttributeError等）将正常传播
_DATA_FETCH_ERRORS = (
    requests.exceptions.RequestException,  # 网络: 连接、超时、HTTP错误
    json.JSONDecodeError,                  # API返回非JSON
    KeyError,                              # API JSON结构变化
    ValueError,                            # 数据校验失败（空数据等）
    TypeError,                             # 意外None/类型不匹配
    IndexError,                            # 空数据访问（.iloc[0]等）
)
# 包含 poe.BotError — 用于 fetch_cn_kline 失败后优雅降级的场景
# poe.BotError 仅在运行时可用（settings提取阶段不可用），因此用 try 保护
try:
    _FETCH_OR_BOT_ERRORS = _DATA_FETCH_ERRORS + (poe.BotError,)
except AttributeError:
    _FETCH_OR_BOT_ERRORS = _DATA_FETCH_ERRORS

def _secid_to_sina(secid):
    market, code = secid.split(".")
    return ("sh" if market == "1" else "sz") + code

def _fetch_cn_eastmoney(secid):
    end_date = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
           f"&klt=101&fqt=1&beg=20050101&end={end_date}&lmt=10000")
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

def _fetch_cn_csindex(index_code):
    url = (f"https://www.csindex.com.cn/csindex-home/perf/index-perf"
           f"?indexCode={index_code}&startDate=20050101"
           f"&endDate={(datetime.now() + timedelta(days=30)).strftime('%Y%m%d')}")
    resp = _session.get(url, timeout=30,
                        headers={"Referer": "https://www.csindex.com.cn/"})
    resp.raise_for_status()
    data = resp.json()
    if not data.get("data"):
        raise ValueError(f"csindex returned no data for {index_code}")
    rows = [{"date": item["tradeDate"], "close": float(item["close"])}
            for item in data["data"]]
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
        except _DATA_FETCH_ERRORS as e:
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
        if ac is None:
            ac = c
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
        except _DATA_FETCH_ERRORS as e:
            last_err = e
            time.sleep(1)
    return None, "FAILED"

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

def run_cn_strategy(close_df, ranking_codes, target_vol=None, vol_window=30, max_lev=1.0,
                    cooldown_days=CN_COOLDOWN_DAYS, ma_window=CN_MA_WINDOW,
                    ma_filter_mode=CN_MA_FILTER_MODE):
    """Sub-A V5: 双动量做多 + 每日检查 + 冷却期 + HS300 MA过滤.
    V5变更:
    - ma_filter_mode="turning": MA拐头向下→cash (MA_today < MA_yesterday)
    - ma_filter_mode="level":   price < MA→cash (原始MA120逻辑)
    - 用前一天的MA方向避免未来函数
    """
    momentum = close_df.div(close_df.shift(CN_LOOKBACK)).sub(1)
    abs_momentum = close_df.div(close_df.shift(CN_ABS_MOM_LB)).sub(1)
    vol_rank = close_df.pct_change().rolling(CN_VOL_RANK_LB).std() * np.sqrt(CN_TRADING_DAYS)
    daily_ret_df = close_df.pct_change() if target_vol is not None else None
    hs300_col = "1.000300"
    if ma_window is not None:
        hs300_ma = close_df[hs300_col].rolling(ma_window).mean()
        if ma_filter_mode == "turning":
            market_above_ma = (hs300_ma > hs300_ma.shift(1)).shift(1).fillna(True)
        else:
            market_above_ma = close_df[hs300_col] > hs300_ma
    else:
        market_above_ma = pd.Series(True, index=close_df.index)
    start_idx = max(CN_LOOKBACK, CN_ABS_MOM_LB, CN_VOL_RANK_LB, ma_window or 0)
    if target_vol is not None:
        start_idx = max(start_idx, vol_window)
    holding = "cash"
    rows = []
    last_trade_day = -999
    for i in range(start_idx, len(close_df)):
        date = close_df.index[i]
        mom_vals = momentum.iloc[i][ranking_codes].dropna()
        vol_vals = vol_rank.iloc[i][ranking_codes].dropna()
        common = mom_vals.index.intersection(vol_vals.index)
        mom_vals = mom_vals[common]
        vol_vals = vol_vals[common]
        ideal = "cash"
        if len(mom_vals) > 0:
            valid_vol = vol_vals[vol_vals > 0.001]
            common2 = mom_vals.index.intersection(valid_vol.index)
            if len(common2) > 0:
                score = mom_vals[common2] / vol_vals[common2]
                best = score.idxmax()
            else:
                best = mom_vals.idxmax()
            abs_val = abs_momentum.iloc[i].get(best, np.nan)
            if not np.isnan(abs_val) and abs_val > 0:
                ideal = best
        if ideal != "cash" and not market_above_ma.iloc[i]:
            ideal = "cash"
        target = None
        days_since_trade = i - last_trade_day
        if ideal != holding and days_since_trade >= cooldown_days:
            target = ideal
            last_trade_day = i
        weight = 1.0
        if target_vol is not None and holding != "cash":
            recent = daily_ret_df[holding].iloc[max(0, i - vol_window):i].dropna()
            if len(recent) >= 10:
                rv = recent.std() * np.sqrt(CN_TRADING_DAYS)
                weight = min(target_vol / rv, max_lev) if rv > 0.001 else max_lev
        elif holding == "cash":
            weight = 0.0
        if target is not None:
            old_h = holding
            cf = _cn_cost(old_h, target)
            if old_h == "cash":
                day_ret = (1 + CN_RF_DAILY) * cf - 1
            else:
                prev = close_df.iloc[i-1][old_h]
                curr = close_df.iloc[i][old_h]
                asset_ret = (curr/prev - 1) if prev != 0 else 0.0
                if target_vol is not None:
                    day_ret = (1 + weight * asset_ret + (1 - weight) * CN_RF_DAILY) * cf - 1
                else:
                    day_ret = (1 + asset_ret) * cf - 1
            holding = target
        else:
            if holding == "cash":
                day_ret = CN_RF_DAILY
            else:
                prev = close_df.iloc[i-1][holding]
                curr = close_df.iloc[i][holding]
                asset_ret = (curr/prev - 1) if prev != 0 else 0.0
                if target_vol is not None:
                    day_ret = weight * asset_ret + (1 - weight) * CN_RF_DAILY
                else:
                    day_ret = asset_ret
        rows.append({"date": date, "return": day_ret, "holding": holding,
                      "is_signal": target is not None, "target": target, "weight": weight})
    df = pd.DataFrame(rows).set_index("date")
    df["nav"] = (1 + df["return"]).cumprod()
    return df

def _dk_signal_days(close_df, start_idx):
    week_best = {}
    for i in range(start_idx, len(close_df)):
        dt = close_df.index[i]
        dow = dt.dayofweek
        yr, wk, _ = dt.isocalendar()
        key = (yr, wk)
        if key not in week_best or dow > week_best[key][1]:
            week_best[key] = (i, dow)
    return {v[0] for v in week_best.values()}

def run_dk_strategy(close_df, target_vol=CN_DK_TARGET_VOL, vol_window=CN_DK_VOL_WINDOW,
                    max_lev=CN_DK_MAX_LEV, min_lev=CN_DK_MIN_LEV,
                    commission=CN_COMMISSION, cooldown_days=CN_DK_COOLDOWN_DAYS,
                    nav_ma_filter=CN_DK_NAV_MA_FILTER):
    """Sub-A-DK V4: ZZ1000/SZ50 多空策略 + 每日检查 + 冷却期 + 净值曲线MA过滤.
    V4变更:
    - 每日检查方向信号(替代固定周五)
    - cooldown_days: 方向翻转后至少等N个交易日才能再次翻转
    - 杠杆缩放(risk scaling)保持日频, 不受冷却期约束(专家条件5)
    - nav_ma_filter: 净值曲线MA天数(如300), NAV<MA时次日强制平仓(空仓)
    比较20日绝对动量，做多动量高的，做空另一个。永远满仓(一多一空)。
    信号决策后，下一个交易日开始生效。
    波动率缩放: scale = target_vol/realized_vol, clip(min_lev, max_lev),
               scale.shift(1)延迟一天生效。
    """
    zz1000_col, sz50_col = CN_DK_COLS
    a_col, b_col = sz50_col, zz1000_col
    d = pd.DataFrame({'a': close_df[a_col], 'b': close_df[b_col]}).dropna()
    d['a_ret'] = d['a'].pct_change()
    d['b_ret'] = d['b'].pct_change()
    d['a_mom'] = d['a'].pct_change(CN_DK_MOM_LB)
    d['b_mom'] = d['b'].pct_change(CN_DK_MOM_LB)
    d['spread_ret'] = d['a_ret'] - d['b_ret']
    d = d.dropna(subset=['a_ret', 'b_ret'])
    n = len(d)
    start_idx = max(CN_DK_MOM_LB, vol_window) + 1
    d['daily_signal'] = np.nan
    both_valid = d['a_mom'].notna() & d['b_mom'].notna()
    d.loc[both_valid, 'daily_signal'] = np.where(
        d.loc[both_valid, 'a_mom'] > d.loc[both_valid, 'b_mom'], 1, -1
    )
    signal_list = [np.nan] * n
    is_signal_list = [False] * n
    current_signal = np.nan
    last_trade_idx = -999
    for i in range(n):
        ds = d['daily_signal'].iloc[i]
        if pd.isna(ds) or i < start_idx:
            signal_list[i] = current_signal
            continue
        if pd.isna(current_signal):
            current_signal = ds
            last_trade_idx = i
            is_signal_list[i] = True
        elif ds != current_signal and (i - last_trade_idx) >= cooldown_days:
            current_signal = ds
            last_trade_idx = i
            is_signal_list[i] = True
        signal_list[i] = current_signal
    d['signal'] = signal_list
    d['signal'] = d['signal'].astype(float)
    d['is_signal'] = is_signal_list
    d['position'] = d['signal'].shift(1)
    d['raw_ret'] = d['position'] * d['spread_ret']
    d = d.dropna(subset=['position', 'raw_ret'])
    if target_vol is not None:
        d['realized_vol'] = d['raw_ret'].rolling(vol_window).std() * np.sqrt(CN_DK_TRADING_DAYS)
        d['scale'] = (target_vol / d['realized_vol']).clip(min_lev, max_lev)
        d['scale'] = d['scale'].shift(1)
        d['strategy_ret'] = d['raw_ret'] * d['scale']
        d = d.dropna(subset=['strategy_ret'])
    else:
        d['strategy_ret'] = d['raw_ret']
        d['scale'] = 1.0
    pos_prev = d['position'].shift(1)
    is_flip = (d['position'] != pos_prev) & pos_prev.notna()
    is_initial = d['position'].notna() & pos_prev.isna()
    d['cost_factor'] = 1.0
    if commission > 0:
        scale_eff = d['scale'] if target_vol is not None else 1.0
        d['tc'] = 0.0
        d.loc[is_flip, 'tc'] = 4 * commission * scale_eff[is_flip] if target_vol is not None else 4 * commission
        d.loc[is_initial, 'tc'] = 2 * commission * scale_eff[is_initial] if target_vol is not None else 2 * commission
        d['cost_factor'] = 1 - d['tc']
    d['strategy_ret'] = (1 + d['strategy_ret']) * d['cost_factor'] - 1
    # ── Always compute unfiltered NAV via numpy loop (consistent regardless of filter) ──
    _ret_arr = d['strategy_ret'].values.copy()
    _n_ret = len(_ret_arr)
    _nav_unfiltered = np.ones(_n_ret)
    for _i in range(1, _n_ret):
        _nav_unfiltered[_i] = _nav_unfiltered[_i - 1] * (1 + _ret_arr[_i])
    d['_nav_unf'] = _nav_unfiltered
    # ── NAV MA filter: optionally zero returns when NAV < MA ──
    d['nav_filtered'] = False
    if nav_ma_filter and nav_ma_filter > 0:
        _flat_flags = np.zeros(_n_ret, dtype=bool)
        for _i in range(_n_ret):
            if _i >= nav_ma_filter - 1:
                _ma_val = np.mean(_nav_unfiltered[_i - nav_ma_filter + 1:_i + 1])
                if _nav_unfiltered[_i] < _ma_val:
                    if _i + 1 < _n_ret:
                        _flat_flags[_i + 1] = True
        _ret_arr[_flat_flags] = 0.0
        d['strategy_ret'] = _ret_arr
        d['nav_filtered'] = _flat_flags
    d['holding'] = np.where(d['signal'] == 1, a_col, b_col)
    d.loc[d['nav_filtered'] == True, 'holding'] = 'none'
    d['target'] = None
    sig_mask = d['is_signal'].reindex(d.index, fill_value=False)
    d.loc[sig_mask, 'target'] = np.where(
        d.loc[sig_mask, 'signal'] == 1, a_col, b_col
    )
    result = pd.DataFrame({
        'return': d['strategy_ret'],
        'holding': d['holding'],
        'is_signal': d['is_signal'].reindex(d.index, fill_value=False),
        'target': d['target'],
        'weight': d['scale'] if target_vol is not None else 1.0,
        'nav_filtered': d['nav_filtered'],
    }, index=d.index)
    result['nav'] = (1 + result['return']).cumprod()
    result['nav_unfiltered'] = d['_nav_unf'] if '_nav_unf' in d.columns else result['nav']
    return result

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

def _us_raw_weights(mom_row, vol_row, ranking_codes, top_n, abs_threshold,
                    prev_risky=None, threshold=1.0):
    """Top-N selection with optional threshold.
    When threshold > 1.0 and prev_risky is provided:
      new challenger must score > weakest current holding × threshold to replace.
    """
    available = {}
    for a in ranking_codes:
        if (a in mom_row.index and not np.isnan(mom_row[a])
                and a in vol_row.index and not np.isnan(vol_row[a])
                and vol_row[a] > 0.001):
            available[a] = mom_row[a]
    if not available:
        return {"BIL": 1.0}
    sorted_avail = sorted(available.items(), key=lambda x: x[1], reverse=True)
    if threshold > 1.0 and prev_risky:
        selected = set()
        for a in prev_risky:
            if a in available:
                selected.add(a)
        for a, _ in sorted_avail:
            if len(selected) >= top_n:
                break
            if a not in selected:
                selected.add(a)
        if len(selected) > top_n:
            sel_scored = sorted([(a, available[a]) for a in selected], key=lambda x: x[1])
            while len(selected) > top_n:
                selected.discard(sel_scored.pop(0)[0])
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
        iv = {a: 1.0 / vol_row[a] for a in passed if vol_row[a] > 0.001}
        total_iv = sum(iv.values()) if iv else 1
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

def _apply_btc_cap(act, btc_ticker, max_w):
    if btc_ticker not in act or act[btc_ticker] <= max_w:
        return act
    act = dict(act)
    excess = act[btc_ticker] - max_w
    act[btc_ticker] = max_w
    act["BIL"] = act.get("BIL", 0.0) + excess
    return act

def run_us_rotation(close_df, ranking_codes, top_n=3, abs_threshold=US_ROT_ABS_THRESHOLD,
                    min_turnover=US_ROT_MIN_TURNOVER,
                    threshold=US_ROT_REBALANCE_THRESHOLD,
                    btc_ticker=None, btc_start=None, btc_max_w=None):
    if btc_ticker and btc_start is not None and btc_ticker in close_df.columns:
        close_df = close_df.copy()
        close_df.loc[close_df.index < btc_start, btc_ticker] = np.nan
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
            prev_risky = set()
            if rows:
                for a in w_assets:
                    wv = rows[-1].get(f"w_{a}", 0.0)
                    if a != "BIL" and wv > 0.001:
                        prev_risky.add(a)
            raw_w = _us_raw_weights(
                momentum.iloc[i], vol_df.iloc[i], ranking_codes, top_n, abs_threshold,
                prev_risky=prev_risky if prev_risky else None,
                threshold=threshold)
            new_act = _us_model_b(raw_w, scale)
            if btc_max_w is not None and btc_ticker:
                new_act = _apply_btc_cap(new_act, btc_ticker, btc_max_w)
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
        for a, w in old_act.items():
            if a in close_df.columns and not np.isnan(close_df.iloc[i].get(a, np.nan)) and not np.isnan(close_df.iloc[i-1].get(a, np.nan)):
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

def apply_vol_regime_overlay(us_rot_result, spy_close):
    """VolReg风控: SPY 短期vol/长期vol > 阈值 → 次日return=0(转现金)。
    在us_rot_result上新增 volreg_ratio / volreg_cash 两列用于信号展示。"""
    spy_ret = spy_close.pct_change()
    short_vol = spy_ret.rolling(US_ROT_VOLREG_SHORT_W).std() * np.sqrt(US_TRADING_DAYS)
    long_vol  = spy_ret.rolling(US_ROT_VOLREG_LONG_W).std() * np.sqrt(US_TRADING_DAYS)
    vol_ratio = (short_vol / long_vol).reindex(us_rot_result.index).ffill()
    # shift(1): T日收盘计算信号 → T+1日执行
    ratio_shifted = vol_ratio.shift(1)
    mask = (ratio_shifted > US_ROT_VOLREG_THRESHOLD).fillna(False)
    result = us_rot_result.copy()
    result.loc[mask, "return"] = 0.0
    result["nav"] = (1 + result["return"]).cumprod()
    result["volreg_ratio"] = vol_ratio        # 当日收盘的ratio(未shift), 用于信号展示
    result["volreg_cash"]  = mask             # 当日是否因昨日信号已转现金
    return result

def make_abs_mom_signals(monthly_prices, lookback=6):
    ret_n = monthly_prices / monthly_prices.shift(lookback) - 1
    raw = (ret_n > 0).astype(float)
    return raw.shift(1)

def _sma_raw_signals(monthly_prices, window=12, band=0.0):
    sma = monthly_prices.rolling(window).mean()
    if band <= 0:
        return (monthly_prices > sma).astype(float)
    upper = sma * (1 + band)
    lower = sma * (1 - band)
    sig = pd.DataFrame(np.nan, index=monthly_prices.index, columns=monthly_prices.columns)
    for col in monthly_prices.columns:
        prev = 0.0
        for i in range(len(monthly_prices)):
            price = monthly_prices.iloc[i][col]
            u = upper.iloc[i][col] if col in upper.columns else np.nan
            l = lower.iloc[i][col] if col in lower.columns else np.nan
            if pd.isna(u) or pd.isna(l) or pd.isna(price):
                sig.iloc[i, sig.columns.get_loc(col)] = np.nan
                continue
            if price > u:
                prev = 1.0
            elif price < l:
                prev = 0.0
            sig.iloc[i, sig.columns.get_loc(col)] = prev
    return sig

def make_sma_signals(monthly_prices, window=12, band=0.0):
    return _sma_raw_signals(monthly_prices, window, band).shift(1)

def simulate_prod(portfolio, monthly_ret, sig_a, cash_ret, rebal_month=12,
                  sig_b=None, blend_a=0.5, commission=0.0):
    """50/50混合回测引擎 (当sig_b=None时退化为纯AbsMom)。
    每个资产仓位分成两半: blend_a跟sig_a(AbsMom), (1-blend_a)跟sig_b(SMA)。
    年度再平衡。commission=单边交易成本(如0.001=千分之一)。"""
    dates = monthly_ret.index
    current_val = 1.0
    blend_b = 1 - blend_a
    use_blend = sig_b is not None
    if use_blend:
        pos_a = {t: current_val * c["w"] * blend_a for t, c in portfolio.items()}
        pos_b = {t: current_val * c["w"] * blend_b for t, c in portfolio.items()}
    else:
        pos_a = {t: current_val * c["w"] for t, c in portfolio.items()}
    prev_sig_a = {}
    prev_sig_b = {}
    vals, details = [], []
    for dt in dates:
        month_detail = {"date": dt}
        month_cost = 0.0
        for t, c in portfolio.items():
            proxy = c["proxy"]
            sa = sig_a.loc[dt, proxy] if proxy in sig_a.columns else 1.0
            if pd.isna(sa):
                sa = 0.0
            r_asset = monthly_ret.loc[dt, proxy] if proxy in monthly_ret.columns else 0.0
            r_cash = cash_ret.loc[dt] if dt in cash_ret.index else 0.0
            if pd.isna(r_asset):
                r_asset = 0.0
            if pd.isna(r_cash):
                r_cash = 0.0
            if commission > 0 and t in prev_sig_a and sa != prev_sig_a[t]:
                cost = pos_a[t] * commission
                pos_a[t] -= cost
                month_cost += cost
            prev_sig_a[t] = sa
            pos_a[t] *= (1 + (r_asset if sa == 1.0 else r_cash))
            month_detail[f"sig_am_{t}"] = sa
            if use_blend:
                sb = sig_b.loc[dt, proxy] if proxy in sig_b.columns else 1.0
                if pd.isna(sb):
                    sb = 0.0
                if commission > 0 and t in prev_sig_b and sb != prev_sig_b[t]:
                    cost = pos_b[t] * commission
                    pos_b[t] -= cost
                    month_cost += cost
                prev_sig_b[t] = sb
                pos_b[t] *= (1 + (r_asset if sb == 1.0 else r_cash))
                month_detail[f"sig_sma_{t}"] = sb
                month_detail[f"sig_{t}"] = blend_a * sa + blend_b * sb
            else:
                month_detail[f"sig_{t}"] = sa
        current_val = sum(pos_a.values()) + (sum(pos_b.values()) if use_blend else 0)
        vals.append(current_val)
        month_detail["cost"] = month_cost
        details.append(month_detail)
        if dt.month == rebal_month:
            if commission > 0 and current_val > 0:
                rebal_to = 0.0
                for t, c in portfolio.items():
                    tgt_a = c["w"] * (blend_a if use_blend else 1.0)
                    act_a = pos_a[t] / current_val
                    rebal_to += abs(tgt_a - act_a)
                    if use_blend:
                        tgt_b = c["w"] * blend_b
                        act_b = pos_b[t] / current_val
                        rebal_to += abs(tgt_b - act_b)
                current_val *= (1 - rebal_to * commission)
            if use_blend:
                pos_a = {t: current_val * c["w"] * blend_a for t, c in portfolio.items()}
                pos_b = {t: current_val * c["w"] * blend_b for t, c in portfolio.items()}
            else:
                pos_a = {t: current_val * c["w"] for t, c in portfolio.items()}
    nav = pd.Series(vals, index=dates)
    return nav, pd.DataFrame(details).set_index("date")

def simulate_prod_btc_phased(monthly_ret, sig_a, cash_ret, rebal_month=12,
                              sig_b=None, blend_a=0.5, commission=0.0):
    """Three-phase Sub-C backtest:
    Phase 0: Before DBMF_BT_START — PROD_PORTFOLIO_PRE_DBMF (no BTC, no DBMF -> VGIT替代)
    Phase 1: DBMF_BT_START to BTC_BT_START — PROD_PORTFOLIO_BT (no BTC, has DBMF)
    Phase 2: From BTC_BT_START — PROD_PORTFOLIO (full)
    Chains NAVs at phase boundaries."""
    phases = [
        (monthly_ret[monthly_ret.index < DBMF_BT_START], PROD_PORTFOLIO_PRE_DBMF),
        (monthly_ret[(monthly_ret.index >= DBMF_BT_START) & (monthly_ret.index < BTC_BT_START)], PROD_PORTFOLIO_BT),
        (monthly_ret[monthly_ret.index >= BTC_BT_START], PROD_PORTFOLIO),
    ]
    navs, details_list = [], []
    end_val = 1.0
    for ret_phase, portfolio in phases:
        if len(ret_phase) > 0:
            nav_phase, det_phase = simulate_prod(
                portfolio, ret_phase, sig_a, cash_ret, rebal_month,
                sig_b=sig_b, blend_a=blend_a, commission=commission)
            nav_phase_scaled = nav_phase * end_val
            navs.append(nav_phase_scaled)
            details_list.append(det_phase)
            end_val = nav_phase_scaled.iloc[-1]
    if navs:
        return pd.concat(navs), pd.concat(details_list)
    return pd.Series(dtype=float), pd.DataFrame()

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

def beijing_now():
    from datetime import timezone
    utc_now = datetime.now(timezone.utc)
    bj_now = utc_now + timedelta(hours=8)
    return bj_now.replace(tzinfo=None)

def is_cn_market_open():
    bj = beijing_now()
    weekday = bj.weekday()
    if weekday >= 5:
        return False, bj
    market_open = bj.replace(hour=9, minute=30, second=0)
    market_close = bj.replace(hour=15, minute=0, second=0)
    return market_open <= bj <= market_close, bj

def _is_edt(d):
    if hasattr(d, 'date'):
        d = d.date()
    et = datetime(d.year, d.month, d.day, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    return et.utcoffset() == timedelta(hours=-4)

def is_us_market_open():
    bj = beijing_now()
    weekday = bj.weekday()
    if weekday == 5 and bj.hour >= 5:
        return False, bj
    if weekday == 6:
        return False, bj
    if weekday == 0 and bj.hour < 21:
        return False, bj
    edt = _is_edt(bj)
    if edt:
        open_h, open_m, close_h = 21, 30, 4
    else:
        open_h, open_m, close_h = 22, 30, 5
    hour = bj.hour
    if hour >= open_h or hour < close_h:
        return True, bj
    return False, bj

def beijing_time_str(date, market="CN", event="close"):
    if market == "CN":
        if event == "open":
            return f"{date.strftime('%Y-%m-%d')} 09:30 北京时间"
        return f"{date.strftime('%Y-%m-%d')} 15:00 北京时间"
    else:
        edt = _is_edt(date)
        if event == "open":
            bj_hour = "21:30" if edt else "22:30"
            return f"{date.strftime('%Y-%m-%d')} {bj_hour} 北京时间"
        else:
            bj_hour = "04:00" if edt else "05:00"
            next_day = date + timedelta(days=1)
            return f"{next_day.strftime('%Y-%m-%d')} {bj_hour} 北京时间"

def _next_biz_day(date):
    d = date + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d

def us_exec_time_str(signal_date):
    exec_day = _next_biz_day(signal_date)
    return beijing_time_str(exec_day, "US", "open")

def _has_execution_happened(signal_date, market, bj_now):
    exec_day = _next_biz_day(signal_date)
    exec_day_date = exec_day.date() if hasattr(exec_day, 'date') else exec_day
    today_date = bj_now.date()
    if today_date > exec_day_date:
        return True
    elif today_date == exec_day_date:
        if market == "CN":
            return bj_now.hour > 9 or (bj_now.hour == 9 and bj_now.minute >= 35)
        else:
            open_h = 21 if _is_edt(exec_day) else 22
            return bj_now.hour > open_h or (bj_now.hour == open_h and bj_now.minute >= 35)
    return False

def _mark_tentative_records(records):
    now_yr, now_wk, _ = beijing_now().isocalendar()
    for rec in records:
        rec_date = pd.Timestamp(rec["日期"])
        rec_yr, rec_wk, _ = rec_date.isocalendar()
        if (rec_yr, rec_wk) == (now_yr, now_wk) and rec_date.dayofweek < 3:
            if "假定" not in rec["策略"]:
                rec["策略"] = rec["策略"] + " ⚠假定"
    return records

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
           "半": 0.5}

def _parse_cn_num(s):
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    if '十' in s:
        parts = s.split('十')
        tens = _CN_NUM.get(parts[0], 1) if parts[0] else 1
        ones = _CN_NUM.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    return None

def parse_date_range(text):
    now = pd.Timestamp.now()
    # ---- 含「日」的完整日期: YYYY年M月D日 到 YYYY年M月D日 / YYYY-MM-DD到YYYY-MM-DD ----
    m = re.search(
        r'(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})\s*日?\s*[到至—\-~]+\s*(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})\s*日?',
        text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
        end = pd.Timestamp(f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}")
        return start, end
    # ---- YYYY年M月D日至今 ----
    m = re.search(r'(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})\s*日?\s*至今', text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
        return start, now
    # ---- 以下为原有的年月级别匹配 ----
    m = re.search(r'(\d{4})[-年/.]?(\d{1,2})[-月]?\s*至今', text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-01")
        return start, now
    m = re.search(r'(\d{4})\s*年?\s*至今', text)
    if m:
        return pd.Timestamp(f"{m.group(1)}-01-01"), now
    m = re.search(r'(\d{4})[-年/.](\d{1,2})[-月]?\s*[到至—\-~]+\s*(\d{4})[-年/.](\d{1,2})', text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-01")
        end = pd.Timestamp(f"{m.group(3)}-{int(m.group(4)):02d}-01") + pd.offsets.MonthEnd(0)
        return start, end
    m = re.search(r'(\d{4})[-年/.](\d{1,2})[-月]?\s*[到至—\-~]+\s*(\d{1,2})', text)
    if m:
        yr = int(m.group(1))
        start = pd.Timestamp(f"{yr}-{int(m.group(2)):02d}-01")
        end = pd.Timestamp(f"{yr}-{int(m.group(3)):02d}-01") + pd.offsets.MonthEnd(0)
        return start, end
    m = re.search(r'(\d{4})(\d{2})\s*[-到至~]+\s*(\d{4})(\d{2})', text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{m.group(2)}-01")
        end = pd.Timestamp(f"{m.group(3)}-{m.group(4)}-01") + pd.offsets.MonthEnd(0)
        return start, end
    m = re.search(r'(\d{4})\s*年?\s*[到至—\-~]+\s*(\d{4})\s*年?', text)
    if m:
        return pd.Timestamp(f"{m.group(1)}-01-01"), pd.Timestamp(f"{m.group(2)}-12-31")
    m = re.search(r'(?:最近|过去|近)\s*([一二两三四五六七八九十\d半]+)\s*个?\s*年', text)
    if m:
        n = _parse_cn_num(m.group(1))
        if n is not None:
            if isinstance(n, float):
                return now - pd.DateOffset(months=int(n * 12)), now
            return now - pd.DateOffset(years=int(n)), now
    m = re.search(r'(?:最近|过去|近)\s*([一二两三四五六七八九十\d半]+)\s*个?\s*月', text)
    if m:
        n = _parse_cn_num(m.group(1))
        if n is not None:
            return now - pd.DateOffset(months=int(n if n >= 1 else 1)), now
    if '今年' in text:
        return pd.Timestamp(f"{now.year}-01-01"), now
    if '去年' in text:
        yr = now.year - 1
        return pd.Timestamp(f"{yr}-01-01"), pd.Timestamp(f"{yr}-12-31")
    if '前年' in text:
        yr = now.year - 2
        return pd.Timestamp(f"{yr}-01-01"), pd.Timestamp(f"{yr}-12-31")
    m = re.search(r'(\d{4})[-年/.](\d{1,2})\s*月?份?', text)
    if m:
        yr = int(m.group(1))
        mon = int(m.group(2))
        if 1 <= mon <= 12:
            start = pd.Timestamp(f"{yr}-{mon:02d}-01")
            end = start + pd.offsets.MonthEnd(0)
            return start, end
    m = re.search(r'(\d{4})\s*年?\s*全?年?', text)
    if m:
        yr = int(m.group(1))
        if 2000 <= yr <= 2099:
            return pd.Timestamp(f"{yr}-01-01"), pd.Timestamp(f"{yr}-12-31")
    return None, None

def parse_all_date_ranges(text):
    parts = re.split(r'以及|、|；|;\s*', text)
    if len(parts) == 1:
        parts = re.split(r'(?<=[年月日\d])\s*和\s*(?=[近最过])', text)
    results = []
    seen = set()
    for part in parts:
        part = part.strip()
        if not part:
            continue
        start, end = parse_date_range(part)
        if start is not None:
            key = (start.date(), end.date())
            if key not in seen:
                results.append((start, end))
                seen.add(key)
    if not results:
        start, end = parse_date_range(text)
        if start is not None:
            results.append((start, end))
    results.sort(key=lambda x: (x[1] - x[0]).days)
    return results

CAPITAL_CONFIG_START = "<!--CAPITAL_CONFIG"
CAPITAL_CONFIG_END = "CAPITAL_CONFIG-->"
# STRATEGY_WEIGHTS 已从 strategy_config 导入

def _scan_capital_config(chat):
    config = None
    for m in chat:
        t = m.text
        while True:
            s = t.find(CAPITAL_CONFIG_START)
            if s < 0:
                break
            e = t.find(CAPITAL_CONFIG_END, s)
            if e < 0:
                break
            raw = t[s + len(CAPITAL_CONFIG_START):e].strip()
            try:
                config = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass
            t = t[e + len(CAPITAL_CONFIG_END):]
    return config

def _build_capital_marker(config):
    return f"\n{CAPITAL_CONFIG_START}\n{json.dumps(config, ensure_ascii=False)}\n{CAPITAL_CONFIG_END}\n"

POSITION_CONFIG_START = "<!--POSITION_CONFIG"
POSITION_CONFIG_END = "POSITION_CONFIG-->"

def _scan_position_config(chat):
    config = None
    for m in chat:
        t = m.text
        while True:
            s = t.find(POSITION_CONFIG_START)
            if s < 0:
                break
            e = t.find(POSITION_CONFIG_END, s)
            if e < 0:
                break
            raw = t[s + len(POSITION_CONFIG_START):e].strip()
            try:
                config = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass
            t = t[e + len(POSITION_CONFIG_END):]
    return config

def _build_position_marker(config):
    return f"\n{POSITION_CONFIG_START}\n{json.dumps(config, ensure_ascii=False)}\n{POSITION_CONFIG_END}\n"

def _pos_entry_value(val, price):
    """Get current market value of a position entry (amount-based or shares-based)."""
    if isinstance(val, dict) and 'amount' in val:
        return float(val['amount'])
    shares = int(float(val)) if isinstance(val, (int, float)) else 0
    return shares * price if price else 0

def _pos_entry_shares(val, price):
    """Get equivalent shares of a position entry (converts amount to shares if needed)."""
    if isinstance(val, dict) and 'amount' in val:
        return int(float(val['amount']) / price) if price and price > 0 else 0
    return int(float(val)) if isinstance(val, (int, float)) else 0

def _calc_quantities(capital, weights, prices):
    result = {}
    for etf, w in weights.items():
        if not isinstance(w, (int, float)) or w < 0.005:
            continue
        amount = capital * w
        price = prices.get(etf)
        if price and price > 0:
            qty = int(amount / price)
            result[etf] = {"weight": w, "amount": round(amount, 2),
                           "price": round(price, 2), "qty": qty}
        else:
            result[etf] = {"weight": w, "amount": round(amount, 2),
                           "price": None, "qty": None}
    return result

TRADE_LOG_START = "<!--TRADE_LOG"
TRADE_LOG_END = "TRADE_LOG-->"

_TRADE_RECORD_KEYWORDS = [
    "执行了", "买了", "买入了", "卖了", "卖出了", "换仓了", "换了",
    "翻转了", "做多了", "做空了", "再平衡了", "重平衡了", "没跟", "跳过了",
    "记录交易", "记录操作", "实盘操作", "已操作", "已执行",
    "刚买", "刚卖", "刚换", "成交", "下单",
    "买入价", "卖出价", "成交价",  # price reporting -> strong trade signal
    "手续费", "佣金",  # commission reporting -> strong trade signal
]

_KNOWN_ASSETS = [
    "红利低波", "中证红利", "中证500", "中证1000", "创业板", "沪深300", "上证50",
    "zzhl", "cyb", "hs300", "zz1000", "zz500",
    "voo", "qqqm", "emxc", "vea", "gldm", "vglt", "schh", "pdbc", "ibit",
    "spy", "qqq", "efa", "gld", "tlt", "vnq", "dbc",
    "vti", "vgit", "dbmf", "bil",
]

_ACTION_CN_MAP = {
    "buy": "买入", "sell": "卖出", "switch": "换仓",
    "flip": "翻转", "rebalance": "再平衡", "skip": "跳过信号",
    "hold": "继续持有",
}

_CN_HOLDING_NORM = {}
for _code, _name in CN_NAMES.items():
    _CN_HOLDING_NORM[_name.lower()] = _code
    _CN_HOLDING_NORM[_code.lower()] = _code
    _CN_HOLDING_NORM[_code.split(".")[-1]] = _code
_CN_HOLDING_NORM.update({
    "zzhl": "1.515100", "zzhl-etf": "1.515100", "红利低波": "1.515100",
    "中证红利低波": "1.515100",
    "cyb": "0.159915", "cyb-etf": "0.159915", "创业板": "0.159915",
    "创业板etf": "0.159915",
    "hs300": "1.000300", "沪深300": "1.000300", "300": "1.000300",
    "zz1000": "1.000852", "中证1000": "1.000852", "1000": "1.000852",
    "zz500": "1.000905", "中证500": "1.000905", "500": "1.000905",
    "cash": "cash", "现金": "cash",
})

def _is_trade_recording(query):
    q = query.lower()
    if any(kw in q for kw in _TRADE_RECORD_KEYWORDS):
        return True
    has_strat = any(s in q for s in [
        "sub-a", "sub-b", "sub-c", "a股", "美股轮动", "多空", "dk", "生产组合"])
    has_asset = any(a in q for a in _KNOWN_ASSETS)
    has_act = any(a in q for a in ["买", "卖", "换", "翻转", "做多", "做空", "平衡"])
    return (has_strat or has_asset) and has_act

def _parse_json_from_response(text, required_fields=None):
    m = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        js = m.group(1).strip()
    else:
        m = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if not m:
            raise ValueError("No JSON found")
        js = m.group(0).strip()
    parsed = json.loads(js)
    if required_fields:
        missing = set(required_fields) - set(parsed.keys())
        if missing:
            raise ValueError(f"Missing: {', '.join(missing)}")
    return parsed

def _scan_trade_logs(chat):
    all_recs = []
    for msg in chat:
        text = msg.text
        pos = 0
        while True:
            s = text.find(TRADE_LOG_START, pos)
            if s == -1:
                break
            e = text.find(TRADE_LOG_END, s)
            if e == -1:
                break
            try:
                all_recs.append(json.loads(text[s + len(TRADE_LOG_START):e].strip()))
            except json.JSONDecodeError:
                pass
            pos = e + len(TRADE_LOG_END)
    deleted = {r["id"] for r in all_recs if r.get("action") == "_deleted"}
    recs = [r for r in all_recs
            if r.get("action") != "_deleted" and r.get("id") not in deleted]
    recs.sort(key=lambda r: r.get("ts", ""))
    return recs

def _build_trade_marker(rec):
    return f"\n{TRADE_LOG_START}\n{json.dumps(rec, ensure_ascii=False)}\n{TRADE_LOG_END}\n"

def _gen_trade_id(existing):
    now_s = beijing_now().strftime("%Y%m%d")
    ids = [r["id"] for r in existing if r.get("id", "").startswith(f"T{now_s}")]
    seq = max((int(t.split("_")[-1]) for t in ids), default=0) + 1
    return f"T{now_s}_{seq:03d}"

def _get_latest_holdings(records):
    latest = {}
    for r in records:
        s = r.get("strategy")
        if s and r.get("action") != "skip":
            latest[s] = r
    return latest

def _normalize_cn_holding(name):
    if name is None:
        return None
    return _CN_HOLDING_NORM.get(name.lower().strip(), name)

def generate_trade_log_csv(records):
    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "交易日期", "记录时间", "策略", "操作", "原持仓",
                     "新持仓", "执行价格", "数量", "持仓市值", "权重",
                     "交易成本", "费率(‰)", "跟随信号", "备注"])
    for r in records:
        ep = r.get("exec_prices", {})
        qt = r.get("quantities", {})
        wt = r.get("weights", {})
        sig = r.get("signal_followed")
        comm = r.get("commission", {}) or {}
        pos_val = 0
        for k in qt:
            q = qt.get(k, 0)
            p = ep.get(k, 0)
            if isinstance(q, dict) and "amount" in q:
                pos_val += float(q["amount"])
            elif isinstance(q, (int, float)) and isinstance(p, (int, float)):
                pos_val += q * p
        comm_amt = comm.get("amount")
        comm_rate = comm.get("rate")
        writer.writerow([
            r.get("id", ""),
            r.get("trade_date", ""),
            r.get("ts", ""),
            r.get("strategy", ""),
            _ACTION_CN_MAP.get(r.get("action", ""), r.get("action", "")),
            r.get("from_holding", "") or "",
            r.get("to_holding", ""),
            json.dumps(ep, ensure_ascii=False) if ep else "",
            json.dumps(qt, ensure_ascii=False) if qt else "",
            f"{pos_val:,.2f}" if pos_val > 0 else "",
            ", ".join(f"{k}:{v:.0%}" for k, v in wt.items()
                      if isinstance(v, (int, float)) and v > 0.005) if wt else "",
            f"{comm_amt:,.2f}" if isinstance(comm_amt, (int, float)) else "",
            f"{comm_rate*1000:.2f}" if isinstance(comm_rate, (int, float)) else "",
            "是" if sig is True else ("否" if sig is False else "—"),
            r.get("notes", ""),
        ])
    return b'\xef\xbb\xbf' + buf.getvalue().encode("utf-8")

def extract_cn_rebalances(cn_result, cn_close, strategy_name="Sub-A", names=None):
    if names is None:
        names = CN_NAMES
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
                "策略": strategy_name,
                "卖出": names.get(prev_holding, prev_holding),
                "卖出价格": price_sell,
                "买入": names.get(holding, holding),
                "买入价格": price_buy,
            })
        prev_holding = holding
    return records

def extract_dk_rebalances(dk_result, strategy_name="Sub-A-DK"):
    records = []
    prev_holding = None
    for i in range(len(dk_result)):
        holding = dk_result["holding"].iloc[i]
        date = dk_result.index[i]
        if prev_holding is not None and holding != prev_holding and holding != "none":
            short_old = CN_DK_COLS[1] if prev_holding == CN_DK_COLS[0] else CN_DK_COLS[0]
            short_new = CN_DK_COLS[1] if holding == CN_DK_COLS[0] else CN_DK_COLS[0]
            records.append({
                "日期": date.strftime("%Y-%m-%d"),
                "北京时间": beijing_time_str(date, "CN"),
                "策略": strategy_name,
                "卖出": f"平多{CN_DK_NAMES.get(prev_holding, prev_holding)}/平空{CN_DK_NAMES.get(short_old, short_old)}",
                "卖出价格": None,
                "买入": f"做多{CN_DK_NAMES.get(holding, holding)}/做空{CN_DK_NAMES.get(short_new, short_new)}",
                "买入价格": None,
            })
        prev_holding = holding
    return records

def extract_us_rot_rebalances(us_rot_result):
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
                    sells.append(f"{live} {prev:.1%}->{cur:.1%}")
                elif diff > 0 and a != "BIL":
                    buys.append(f"{live} {prev:.1%}->{cur:.1%}")
        if sells or buys:
            records.append({
                "日期": date.strftime("%Y-%m-%d"),
                "北京时间": us_exec_time_str(date),
                "策略": "Sub-B",
                "卖出": "; ".join(sells) if sells else "—",
                "卖出价格": None,
                "买入": "; ".join(buys) if buys else "—",
                "买入价格": None,
            })
        prev_weights = weights
    return records

def extract_prod_rebalances(prod_details, prod_monthly, include_no_change=False):
    records = []
    sig_cols = [c for c in prod_details.columns if c.startswith("sig_") and not c.startswith("sig_am_") and not c.startswith("sig_sma_")]
    prev_sigs = None
    for i in range(len(prod_details)):
        dt = prod_details.index[i]
        sigs = {c.replace("sig_", ""): prod_details.iloc[i][c] for c in sig_cols}
        if prev_sigs is not None:
            changes = []
            for t, s in sigs.items():
                ps = prev_sigs.get(t, s)
                if not pd.isna(s) and not pd.isna(ps) and abs(s - ps) > 0.01:
                    if s >= 0.99:
                        desc = f"{t} 全部持有"
                    elif s <= 0.01:
                        desc = f"{t} 全部现金(BIL)"
                    else:
                        desc = f"{t} {s:.0%}持有"
                    changes.append(desc)
            if changes:
                records.append({
                    "日期": dt.strftime("%Y-%m-%d"),
                    "北京时间": us_exec_time_str(dt),
                    "策略": "Sub-C",
                    "卖出": "",
                    "卖出价格": None,
                    "买入": "; ".join(changes),
                    "买入价格": None,
                })
            elif include_no_change:
                risk_pct = np.mean([s for s in sigs.values() if not pd.isna(s)]) if sigs else 0
                records.append({
                    "日期": dt.strftime("%Y-%m-%d"),
                    "北京时间": us_exec_time_str(dt),
                    "策略": "Sub-C",
                    "卖出": "",
                    "卖出价格": None,
                    "买入": f"信号无变更 (平均持仓{risk_pct:.0%})",
                    "买入价格": None,
                })
        prev_sigs = sigs
    return records

def _compute_daily_subc(us_prod_daily, prod_sig_a, portfolio, cash_ticker,
                        prod_sig_b=None, blend_a=0.5):
    """Compute daily Sub-C returns from daily prices and monthly signals.
    Supports 50/50 blend when prod_sig_b is provided.
    Uses monthly signals applied to daily price changes for accurate
    intra-month drawdown calculation."""
    daily_ret = us_prod_daily.pct_change().dropna(how="all")
    day_periods = daily_ret.index.to_period("M")
    use_blend = prod_sig_b is not None
    blend_b = 1 - blend_a
    sig_a_lookup = {}
    for sig_dt in prod_sig_a.index:
        sig_a_lookup[sig_dt.to_period("M")] = prod_sig_a.loc[sig_dt]
    sig_b_lookup = {}
    if use_blend:
        for sig_dt in prod_sig_b.index:
            sig_b_lookup[sig_dt.to_period("M")] = prod_sig_b.loc[sig_dt]
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
        daily_sig_a = pd.Series(np.nan, index=daily_ret.index)
        for period, mask in period_masks.items():
            if period in sig_a_lookup and proxy in sig_a_lookup[period].index:
                sv = sig_a_lookup[period][proxy]
                daily_sig_a[mask] = 0.0 if pd.isna(sv) else sv
        daily_sig_a = daily_sig_a.ffill().fillna(0)
        if use_blend:
            daily_sig_b = pd.Series(np.nan, index=daily_ret.index)
            for period, mask in period_masks.items():
                if period in sig_b_lookup and proxy in sig_b_lookup[period].index:
                    sv = sig_b_lookup[period][proxy]
                    daily_sig_b[mask] = 0.0 if pd.isna(sv) else sv
            daily_sig_b = daily_sig_b.ffill().fillna(0)
            ret_a = daily_sig_a * asset_daily + (1 - daily_sig_a) * cash_daily
            ret_b = daily_sig_b * asset_daily + (1 - daily_sig_b) * cash_daily
            weighted = w * (blend_a * ret_a + blend_b * ret_b)
        else:
            weighted = w * (daily_sig_a * asset_daily + (1 - daily_sig_a) * cash_daily)
        result += weighted
    return result

def _compute_daily_subc_phased(us_prod_daily, prod_sig_a, cash_ticker,
                                prod_sig_b=None, blend_a=0.5):
    """Three-phase daily Sub-C matching simulate_prod_btc_phased phases.
    Used for accurate intra-month drawdown calculation."""
    phases = [
        (us_prod_daily[us_prod_daily.index < DBMF_BT_START], PROD_PORTFOLIO_PRE_DBMF),
        (us_prod_daily[(us_prod_daily.index >= DBMF_BT_START) & (us_prod_daily.index < BTC_BT_START)], PROD_PORTFOLIO_BT),
        (us_prod_daily[us_prod_daily.index >= BTC_BT_START], PROD_PORTFOLIO),
    ]
    parts = []
    for daily_phase, portfolio in phases:
        if len(daily_phase) > 1:
            parts.append(_compute_daily_subc(
                daily_phase, prod_sig_a, portfolio, cash_ticker,
                prod_sig_b=prod_sig_b, blend_a=blend_a))
    return pd.concat(parts) if parts else pd.Series(dtype=float)

def generate_signal_excel(date_str, signal_info, rebalance_records):
    output = io.BytesIO()
    with xlsxwriter.Workbook(output, {"in_memory": True}) as wb:
        header_fmt = wb.add_format({"bold": True, "bg_color": "#4472C4",
                                     "font_color": "white", "border": 1})
        cell_fmt = wb.add_format({"border": 1})
        pct_fmt = wb.add_format({"border": 1, "num_format": "0.0%"})
        price_fmt = wb.add_format({"border": 1, "num_format": "0.000"})
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
            ws.write(i+1, 1, "是" if info.get("is_signal") else "否（信号）", cell_fmt)
            ws.write(i+1, 2, info.get("signal_text", ""), cell_fmt)
            ws.write(i+1, 3, info.get("note", ""), cell_fmt)
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
    output = io.BytesIO()
    with xlsxwriter.Workbook(output, {"in_memory": True}) as wb:
        header_fmt = wb.add_format({"bold": True, "bg_color": "#4472C4",
                                     "font_color": "white", "border": 1})
        cell_fmt = wb.add_format({"border": 1})
        pct_fmt = wb.add_format({"border": 1, "num_format": "0.00%"})
        num_fmt = wb.add_format({"border": 1, "num_format": "0.00"})
        ws = wb.add_worksheet("绩效概览")
        ws.set_column("A:A", 14)
        ws.set_column("B:G", 12)
        metric_headers = ["指标", "Sub-A", "A-DK", "Sub-B", "Sub-C", "组合"]
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
            for j, strat in enumerate(["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C", "Combined"]):
                m = metrics_dict.get(strat)
                if m and key in m and m[key] is not None:
                    if is_pct:
                        ws.write(i+1, j+1, m[key] / 100, pct2_fmt)
                    else:
                        ws.write(i+1, j+1, round(m[key], 2), num_fmt)
                else:
                    ws.write(i+1, j+1, "N/A", cell_fmt)
        if monthly_returns is not None and len(monthly_returns) > 0:
            ws2 = wb.add_worksheet("月度收益")
            ws2.set_column("A:A", 10)
            ws2.set_column("B:G", 12)
            mr_headers = ["月份", "Sub-A", "A-DK", "Sub-B", "Sub-C", "组合"]
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

class CombinedStrategyBase:
    """共享基类: 数据获取、策略执行、信号计算、资金管理"""

    def _fetch_data(self, msg):
        msg.write("⏳ 正在获取A股数据...\n")
        cn_raw, cn_sources = {}, {}
        for secid in CN_STOCK_CODES:
            df, source = fetch_cn_kline(secid)
            cn_raw[secid] = df
            cn_sources[secid] = source
            time.sleep(0.5)
        try:
            zzhl_idx_df, zzhl_idx_src = None, None
            for src_name, fetcher in [
                ("EastMoney", lambda: _fetch_cn_eastmoney(CN_ZZHL_INDEX_SECID)),
                ("EastMoney-0", lambda: _fetch_cn_eastmoney("0.H30269")),
                ("Sina", lambda: _fetch_cn_sina(CN_ZZHL_INDEX_SECID)),
                ("csindex", lambda: _fetch_cn_csindex("H30269")),
            ]:
                try:
                    df = fetcher()
                    if df is not None and len(df) > 50:
                        zzhl_idx_df, zzhl_idx_src = df, src_name
                        break
                except _DATA_FETCH_ERRORS:
                    time.sleep(0.5)
            if zzhl_idx_df is None:
                raise ValueError("所有数据源均失败")
            zzhl_etf_df = cn_raw[CN_ZZHL_ETF_SECID]
            zzhl_before = zzhl_idx_df[zzhl_idx_df.index < CN_ZZHL_ETF_START]
            zzhl_after = zzhl_etf_df[zzhl_etf_df.index >= CN_ZZHL_ETF_START]
            if len(zzhl_before) > 0 and len(zzhl_after) > 0:
                idx_last = zzhl_before["close"].iloc[-1]
                etf_first = zzhl_after["close"].iloc[0]
                scale = etf_first / idx_last
                zzhl_before = zzhl_before.copy()
                zzhl_before["close"] = zzhl_before["close"] * scale
                cn_raw[CN_ZZHL_ETF_SECID] = pd.concat([zzhl_before, zzhl_after])
                msg.write(f"  ZZHL混合: 指数{zzhl_idx_df.index[0].strftime('%Y-%m-%d')}~{CN_ZZHL_ETF_START.strftime('%Y-%m-%d')}"
                         f" + ETF{CN_ZZHL_ETF_START.strftime('%Y-%m-%d')}~ [{zzhl_idx_src}+ETF]\n")
        except _DATA_FETCH_ERRORS as e:
            msg.write(f"  ⚠️ ZZHL指数获取失败({e})，仅用ETF数据\n")
        try:
            cyb_idx_df, cyb_idx_src = fetch_cn_kline(CN_CYB_INDEX_SECID)
            cyb_etf_df = cn_raw[CN_CYB_ETF_SECID]
            cyb_before = cyb_idx_df[cyb_idx_df.index < CN_CYB_ETF_START]
            cyb_after = cyb_etf_df[cyb_etf_df.index >= CN_CYB_ETF_START]
            if len(cyb_before) > 0 and len(cyb_after) > 0:
                cyb_idx_last = cyb_before["close"].iloc[-1]
                cyb_etf_first = cyb_after["close"].iloc[0]
                cyb_scale = cyb_etf_first / cyb_idx_last
                cyb_before = cyb_before.copy()
                cyb_before["close"] = cyb_before["close"] * cyb_scale
                cn_raw[CN_CYB_ETF_SECID] = pd.concat([cyb_before, cyb_after])
                msg.write(f"  CYB混合: 指数{cyb_idx_df.index[0].strftime('%Y-%m-%d')}~{CN_CYB_ETF_START.strftime('%Y-%m-%d')}"
                         f" + ETF{CN_CYB_ETF_START.strftime('%Y-%m-%d')}~ [{cyb_idx_src}+ETF]\n")
        except _FETCH_OR_BOT_ERRORS as e:
            msg.write(f"  ⚠️ CYB指数获取失败({e})，仅用ETF数据\n")
        cn_close = pd.concat([cn_raw[s].rename(columns={"close": s})
                              for s in CN_STOCK_CODES], axis=1).ffill().dropna()
        if len(cn_close) < CN_LOOKBACK + 10:
            raise poe.BotError(f"A股数据不足: 仅{len(cn_close)}行")
        for secid in CN_STOCK_CODES:
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
        _late_rot = {"BTC-USD", "EMXC"}
        rot_tickers_core = [t for t in rot_tickers if t not in _late_rot]
        if "EMXC" in US_ROT_POOL and US_ROT_EMXC_BT_PROXY not in rot_tickers_core:
            if US_ROT_EMXC_BT_PROXY in us_raw:
                rot_tickers_core.append(US_ROT_EMXC_BT_PROXY)
        us_rot_close = pd.concat(
            [us_raw[t][["close"]].rename(columns={"close": t})
             for t in rot_tickers_core if t in us_raw],
            axis=1).ffill().dropna()
        if "EMXC" in US_ROT_POOL and US_ROT_EMXC_BT_PROXY in us_raw:
            eem_col = us_rot_close[US_ROT_EMXC_BT_PROXY].copy() if US_ROT_EMXC_BT_PROXY in us_rot_close.columns else None
            emxc_raw = us_raw.get("EMXC")
            if eem_col is not None:
                hybrid = eem_col.rename("EMXC")
                if emxc_raw is not None and len(emxc_raw) > 0:
                    emxc_ser = emxc_raw["close"].reindex(hybrid.index)
                    switch_idx = hybrid.index >= US_ROT_EMXC_BT_START
                    if switch_idx.any() and emxc_ser.loc[switch_idx].first_valid_index() is not None:
                        first_emxc_date = emxc_ser.loc[switch_idx].first_valid_index()
                        scale_factor = hybrid.loc[first_emxc_date] / emxc_ser.loc[first_emxc_date]
                        hybrid.loc[switch_idx] = emxc_ser.loc[switch_idx] * scale_factor
                us_rot_close["EMXC"] = hybrid
                if US_ROT_EMXC_BT_PROXY in us_rot_close.columns and US_ROT_EMXC_BT_PROXY not in US_ROT_POOL:
                    us_rot_close = us_rot_close.drop(columns=[US_ROT_EMXC_BT_PROXY])
        for t in _late_rot:
            if t == "EMXC":
                continue
            if t in us_raw:
                us_rot_close = us_rot_close.join(
                    us_raw[t][["close"]].rename(columns={"close": t}), how="left")
        prod_proxies = list(set(
            [c["proxy"] for c in PROD_PORTFOLIO.values()] + [PROD_CASH]))
        _late_prod = {"BTC-USD", "DBMF"}
        prod_proxies_core = [t for t in prod_proxies if t not in _late_prod]
        us_prod_daily = pd.concat(
            [us_raw[t][["close"]].rename(columns={"close": t})
             for t in prod_proxies_core if t in us_raw],
            axis=1).ffill().dropna()
        for t in _late_prod:
            if t in us_raw:
                us_prod_daily = us_prod_daily.join(
                    us_raw[t][["close"]].rename(columns={"close": t}), how="left")
        _btc_like = {"BTC-USD"}
        _us_stock_rot = [t for t in rot_tickers if t in us_raw and t not in _btc_like]
        if _us_stock_rot:
            _last_stock_date = max(us_raw[t].index[-1] for t in _us_stock_rot)
            us_rot_close = us_rot_close.loc[:_last_stock_date]
        _us_stock_prod = [t for t in prod_proxies if t in us_raw and t not in _btc_like]
        if _us_stock_prod:
            _last_prod_date = max(us_raw[t].index[-1] for t in _us_stock_prod)
            us_prod_daily = us_prod_daily.loc[:_last_prod_date]
        missing_us = set(rot_tickers + prod_proxies) - set(us_raw.keys())
        if missing_us:
            msg.write(f"  ⚠️ 缺失: {', '.join(sorted(missing_us))}\n")
        us_date = us_rot_close.index[-1]
        us_close_bj = beijing_time_str(us_date, "US", "close")
        msg.write(f"  美股: {len(us_raw)}个ETF | 收盘: {us_close_bj}\n")
        msg.write("⏳ 正在获取A-DK多空数据(中证1000/上证50)...\n")
        try:
            dk_dfs = {}
            for idx_code, secid, col_name in [
                (CN_DK_ZZ1000_CODE, CN_DK_ZZ1000_SECID, CN_DK_COLS[0]),
                (CN_DK_SZ50_CODE, CN_DK_SZ50_SECID, CN_DK_COLS[1]),
            ]:
                idx_df, src = None, None
                for src_name, fetcher in [
                    ("csindex", lambda c=idx_code: _fetch_cn_csindex(c)),
                    ("EastMoney", lambda s=secid: _fetch_cn_eastmoney(s)),
                ]:
                    try:
                        df = fetcher()
                        if df is not None and len(df) > 50:
                            idx_df, src = df, src_name
                            break
                    except _DATA_FETCH_ERRORS:
                        time.sleep(0.5)
                if idx_df is None:
                    raise ValueError(f"A-DK {col_name} 数据源均失败")
                dk_dfs[col_name] = idx_df.rename(columns={"close": col_name})
                msg.write(f"  {CN_DK_NAMES[col_name]}: {idx_df.index[0].strftime('%Y-%m-%d')}~{idx_df.index[-1].strftime('%Y-%m-%d')} [{src}]\n")
                time.sleep(0.5)
            cn_dk_close = pd.concat([dk_dfs[c] for c in CN_DK_COLS], axis=1).ffill().dropna()
            msg.write(f"  A-DK合并截至: {cn_dk_close.index[-1].strftime('%Y-%m-%d')}\n")
        except _DATA_FETCH_ERRORS as e:
            raise poe.BotError(f"A-DK多空数据获取失败: {e}")
        return cn_close, cn_dk_close, us_rot_close, us_prod_daily
    def _run_strategies(self, cn_close, cn_dk_close, us_rot_close, us_prod_daily):
        cn_result = run_cn_strategy(cn_close, CN_STOCK_CODES)
        cn_dk_result = run_dk_strategy(cn_dk_close,
                                       target_vol=CN_DK_TARGET_VOL,
                                       vol_window=CN_DK_VOL_WINDOW,
                                       max_lev=CN_DK_MAX_LEV,
                                       min_lev=CN_DK_MIN_LEV,
                                       nav_ma_filter=CN_DK_NAV_MA_FILTER if CN_DK_USE_NAV_FILTER else 0)
        us_rot_result = run_us_rotation(
            us_rot_close, US_ROT_POOL,
            btc_ticker=US_ROT_BTC_TICKER, btc_start=US_ROT_BTC_START, btc_max_w=US_ROT_BTC_MAX_W)
        if US_ROT_VOLREG_ENABLED and "SPY" in us_rot_close.columns:
            us_rot_result = apply_vol_regime_overlay(us_rot_result, us_rot_close["SPY"])
        prod_monthly = us_prod_daily.resample("M").last()
        _last_daily = us_prod_daily.index[-1]
        _last_monthly_period = prod_monthly.index[-1].to_period("M")
        _today_period = pd.Timestamp(beijing_now().date()).to_period("M")
        if _last_daily.to_period("M") == _last_monthly_period == _today_period:
            prod_monthly = prod_monthly.iloc[:-1]
        prod_sig_a = make_abs_mom_signals(prod_monthly, PROD_ABS_MOM_LB)
        prod_sig_b = make_sma_signals(prod_monthly, PROD_SMA_WINDOW, PROD_SMA_BAND)
        if not PROD_USE_TIMING:
            prod_sig_a = pd.DataFrame(1.0, index=prod_sig_a.index, columns=prod_sig_a.columns)
            prod_sig_b = prod_sig_a.copy()
        prod_monthly_ret = prod_monthly.pct_change().dropna(how="all")
        cash_ret = prod_monthly_ret[PROD_CASH] if PROD_CASH in prod_monthly_ret.columns else pd.Series(0, index=prod_monthly_ret.index)
        prod_nav, prod_details = simulate_prod_btc_phased(
            prod_monthly_ret, prod_sig_a, cash_ret, PROD_REBAL_MONTH,
            sig_b=prod_sig_b, blend_a=PROD_BLEND_A, commission=PROD_COMMISSION)
        return cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details
    def _compute_signal_data(self, cn_close, cn_dk_close, us_rot_close, us_prod_daily):
        cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details = \
            self._run_strategies(cn_close, cn_dk_close, us_rot_close, us_prod_daily)
        cn_date = cn_close.index[-1]
        cn_current = cn_result["holding"].iloc[-1]
        cn_trade_days = cn_result[cn_result["is_signal"] == True]
        if len(cn_trade_days) > 0:
            last_cn_trade_date = cn_trade_days.index[-1]
            cn_days_since = len(cn_result.loc[last_cn_trade_date:]) - 1
            cn_cooldown_remaining = max(0, CN_COOLDOWN_DAYS - cn_days_since)
        else:
            cn_cooldown_remaining = 0
        hs300_col = "1.000300"
        hs300_ma_cn = cn_close[hs300_col].rolling(CN_MA_WINDOW).mean()
        if CN_MA_FILTER_MODE == "turning":
            cn_ma_above = bool(hs300_ma_cn.iloc[-2] > hs300_ma_cn.iloc[-3]) if len(hs300_ma_cn) >= 3 else True
        else:
            cn_ma_above = bool(cn_close[hs300_col].iloc[-1] > hs300_ma_cn.iloc[-1])
        is_cn_signal = bool(cn_result["is_signal"].iloc[-1]) if "is_signal" in cn_result.columns else False
        momentum_cn = cn_close.div(cn_close.shift(CN_LOOKBACK)).sub(1)
        abs_mom_cn = cn_close.div(cn_close.shift(CN_ABS_MOM_LB)).sub(1)
        vol_rank_cn = cn_close.pct_change().rolling(CN_VOL_RANK_LB).std() * np.sqrt(CN_TRADING_DAYS)
        hypo_data_idx = len(momentum_cn) - 1
        mom_vals = momentum_cn.iloc[hypo_data_idx][CN_STOCK_CODES].dropna()
        vol_vals = vol_rank_cn.iloc[hypo_data_idx][CN_STOCK_CODES].dropna()
        common_cn = mom_vals.index.intersection(vol_vals.index)
        mom_vals = mom_vals[common_cn]
        vol_vals = vol_vals[common_cn]
        if len(mom_vals) > 0:
            valid_vol = vol_vals[vol_vals > 0.001]
            common2_cn = mom_vals.index.intersection(valid_vol.index)
            if len(common2_cn) > 0:
                score_cn = mom_vals[common2_cn] / vol_vals[common2_cn]
                best_cn = score_cn.idxmax()
            else:
                best_cn = mom_vals.idxmax()
            abs_val = abs_mom_cn.iloc[hypo_data_idx].get(best_cn, np.nan)
            hypo_cn = best_cn if (not np.isnan(abs_val) and abs_val > 0) else "cash"
        else:
            hypo_cn = "cash"
        if hypo_cn != "cash" and not cn_ma_above:
            hypo_cn = "cash"
        us_date = us_rot_close.index[-1]
        us_start_idx = max(US_ROT_LB, US_ROT_VOL_LB, US_ROT_VOL_WINDOW) + 1
        us_signal_set = _us_signal_days(us_rot_close, us_start_idx)
        is_us_signal = (len(us_rot_close) - 1) in us_signal_set
        if is_us_signal:
            last_dow_us = us_date.dayofweek
            last_yr_us, last_wk_us, _ = us_date.isocalendar()
            now_yr_us, now_wk_us, _ = beijing_now().isocalendar()
            if (last_yr_us, last_wk_us) == (now_yr_us, now_wk_us) and last_dow_us < 3:
                is_us_signal = False
        rot_w_cols = [c for c in us_rot_result.columns if c.startswith("w_")]
        current_us_w = {c.replace("w_", ""): us_rot_result.iloc[-1][c] for c in rot_w_cols}
        if not is_us_signal:
            sigs_confirmed_us = sorted([i for i in us_signal_set if i < len(us_rot_close) - 1])
            if sigs_confirmed_us:
                last_conf_date_us = us_rot_close.index[sigs_confirmed_us[-1]]
                if last_conf_date_us in us_rot_result.index:
                    current_us_w = {c.replace("w_", ""): us_rot_result.loc[last_conf_date_us, c] for c in rot_w_cols}
        hist = us_rot_result["return"].values
        if len(hist) >= US_ROT_VOL_WINDOW:
            rv = np.std(hist[-US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
            us_scale = min(max(US_ROT_TARGET_VOL / rv, 0.05), US_ROT_MAX_LEV) if rv > 0.001 else US_ROT_MAX_LEV
        else:
            us_scale = 1.0
        prev_us_w = None
        rebalanced_b = None
        would_rebalance = None
        turnover_b = 0.0
        _mu = us_rot_close.div(us_rot_close.shift(US_ROT_LB)).sub(1)
        _vl = us_rot_close.pct_change().rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
        _prev_risky_us = {a for a, w in current_us_w.items() if a != "BIL" and w > 0.001}
        hypo_us_w = _us_model_b(_us_raw_weights(_mu.iloc[-1], _vl.iloc[-1], US_ROT_POOL, 3, US_ROT_ABS_THRESHOLD,
                                                 prev_risky=_prev_risky_us if _prev_risky_us else None,
                                                 threshold=US_ROT_REBALANCE_THRESHOLD), us_scale)
        if US_ROT_BTC_MAX_W is not None:
            hypo_us_w = _apply_btc_cap(hypo_us_w, US_ROT_BTC_TICKER, US_ROT_BTC_MAX_W)
        if is_us_signal:
            rebalanced_b = bool(us_rot_result.iloc[-1].get("rebalanced", False))
            rloc = len(us_rot_result) - 1
            prev_us_w = {}
            if rloc > 0:
                prev_us_w = {c.replace("w_", ""): us_rot_result.iloc[rloc - 1][c] for c in rot_w_cols}
            if not prev_us_w:
                prev_us_w = {"BIL": 1.0}
            all_a = set(list(hypo_us_w.keys()) + list(prev_us_w.keys()))
            turnover_b = sum(abs(hypo_us_w.get(a, 0) - prev_us_w.get(a, 0)) for a in all_a if a != "BIL")
        else:
            all_a = set(list(hypo_us_w.keys()) + list(current_us_w.keys()))
            turnover_b = sum(abs(hypo_us_w.get(a, 0) - current_us_w.get(a, 0)) for a in all_a if a != "BIL")
            would_rebalance = turnover_b >= US_ROT_MIN_TURNOVER
        dk_date = cn_dk_close.index[-1]
        dk_current = cn_dk_result["holding"].iloc[-1]
        dk_trade_days = cn_dk_result[cn_dk_result["is_signal"] == True]
        if len(dk_trade_days) > 0:
            last_dk_trade_date = dk_trade_days.index[-1]
            dk_days_since = len(cn_dk_result.loc[last_dk_trade_date:]) - 1
            dk_cooldown_remaining = max(0, CN_DK_COOLDOWN_DAYS - dk_days_since)
        else:
            dk_cooldown_remaining = 0
        is_dk_signal = bool(cn_dk_result["is_signal"].iloc[-1]) if "is_signal" in cn_dk_result.columns else False
        dk_mom = cn_dk_close.pct_change(CN_DK_MOM_LB)
        dk_mom_latest = dk_mom.iloc[-1]
        zz1000_col, sz50_col = CN_DK_COLS
        zz1000_mom_val = dk_mom_latest.get(zz1000_col, np.nan)
        sz50_mom_val = dk_mom_latest.get(sz50_col, np.nan)
        if not np.isnan(zz1000_mom_val) and not np.isnan(sz50_mom_val):
            hypo_dk = zz1000_col if zz1000_mom_val > sz50_mom_val else sz50_col
        else:
            hypo_dk = dk_current
        ret_n_prod = prod_monthly / prod_monthly.shift(PROD_ABS_MOM_LB) - 1
        current_am_raw = (ret_n_prod > 0).astype(float)
        current_sma_raw = _sma_raw_signals(prod_monthly, PROD_SMA_WINDOW, PROD_SMA_BAND)
        last_sig_month = current_am_raw.index[-1]
        return {
            "cn_result": cn_result, "cn_dk_result": cn_dk_result,
            "us_rot_result": us_rot_result,
            "prod_monthly": prod_monthly, "prod_details": prod_details,
            "cn_date": cn_date,
            "is_cn_signal": is_cn_signal, "cn_current": cn_current,
            "hypo_cn": hypo_cn,
            "cn_cooldown_remaining": cn_cooldown_remaining,
            "cn_ma_above": cn_ma_above,
            "momentum_cn": momentum_cn, "abs_mom_cn": abs_mom_cn,
            "vol_rank_cn": vol_rank_cn,
            "dk_date": dk_date,
            "is_dk_signal": is_dk_signal, "dk_current": dk_current,
            "hypo_dk": hypo_dk, "dk_mom": dk_mom,
            "dk_cooldown_remaining": dk_cooldown_remaining,
            "us_date": us_date, "us_signal_set": us_signal_set,
            "is_us_signal": is_us_signal, "current_us_w": current_us_w,
            "us_scale": us_scale,
            "prev_us_w": prev_us_w, "hypo_us_w": hypo_us_w,
            "rebalanced_b": rebalanced_b, "would_rebalance": would_rebalance,
            "turnover_b": turnover_b, "all_a": all_a,
            "rot_w_cols": rot_w_cols,
            "current_am_raw": current_am_raw, "current_sma_raw": current_sma_raw,
            "last_sig_month": last_sig_month,
            "volreg_ratio": float(us_rot_result["volreg_ratio"].iloc[-1]) if "volreg_ratio" in us_rot_result.columns else None,
            "volreg_cash_today": bool(us_rot_result["volreg_cash"].iloc[-1]) if "volreg_cash" in us_rot_result.columns else False,
        }

    def _handle_set_capital(self):
        existing = _scan_capital_config(poe.default_chat) or {}
        ctx_parts = []
        for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:
            v = existing.get(s)
            if v:
                ctx_parts.append(f"- {s}: {v:,.0f}")
            else:
                ctx_parts.append(f"- {s}: 未设置")
        prompt = f"""解析资金设置。

四个子策略: Sub-A, Sub-A-DK, Sub-B, Sub-C
默认权重: Sub-A 15%, Sub-A-DK 15%, Sub-B 40%, Sub-C 30%
注意: Sub-A和Sub-A-DK使用人民币, Sub-B和Sub-C使用美元

当前已设置:
{chr(10).join(ctx_parts)}

用户输入: {poe.query.text}

输出```json格式:
```json
{{
  "Sub-A": 数字或null,
  "Sub-A-DK": 数字或null,
  "Sub-B": 数字或null,
  "Sub-C": 数字或null
}}
```

规则:
1. 用户说"Sub-B 5万美元" -> Sub-B: 50000
2. 用户分别指定人民币和美元金额 -> 人民币金额按Sub-A:Sub-A-DK=15:15(各50%)拆分, 美元金额按Sub-B:Sub-C=40:30拆分
   例: "人民币300万, 美元100万" -> Sub-A: 1500000, Sub-A-DK: 1500000, Sub-B: 571429, Sub-C: 428571
3. 用户说"总共100万, 按默认比例" (未区分币种) -> Sub-A: 150000, Sub-A-DK: 150000, Sub-B: 400000, Sub-C: 300000
4. 用户只设置部分策略 -> 未提到的填null(保持之前的设置)
5. "万"=10000, "百万"=1000000, "千"=1000
6. 金额只填数字(不带货币符号), 单位统一为该策略的对应货币(A股=人民币, 美股=美元)
7. 用户说"总共10万美元给美股" -> 按Sub-B 40/(40+30), Sub-C 30/(40+30)比例拆分
8. 关键: 人民币/RMB/CNY -> 只分给Sub-A和Sub-A-DK; 美元/USD -> 只分给Sub-B和Sub-C"""

        with _sm() as msg:
            w = msg.write
            w("⏳ 正在解析资金设置...\n")
        response = poe.call("Grok-4.1-Fast-Non-Reasoning", prompt)
        try:
            parsed = _parse_json_from_response(response.text, [])
        except (json.JSONDecodeError, ValueError):
            raise poe.BotError(
                "无法解析资金设置，请用更明确的语言，例如:\n"
                "- 设置资金 Sub-B 5万美元 Sub-C 3万美元\n"
                "- 设置资金 A股共20万 美股共8万美元\n"
                "- 设置资金 总共100万人民币 按默认比例")
        config = dict(existing)
        for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:
            v = parsed.get(s)
            if v is not None and isinstance(v, (int, float)) and v > 0:
                config[s] = v
        currency = {"Sub-A": "¥", "Sub-A-DK": "¥", "Sub-B": "$", "Sub-C": "$"}
        with _sm() as msg:
            w = msg.write
            w("## 💰 资金配置已更新\n\n| 策略 | 资金 | 默认权重 |\n|:-|-----:|:-|\n")
            for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:
                v = config.get(s)
                c = currency[s]
                _sw = STRATEGY_WEIGHTS[s]
                if v:
                    w(f"| {s} | {c}{v:,.0f} | {_sw:.0%} |\n")
                else:
                    w(f"| {s} | 未设置 | {_sw:.0%} |\n")
            w("\n✅ 信号查询时将自动计算目标持仓数量\n")
            w(_build_capital_marker(config))

    def _handle_set_position(self):
        existing = _scan_position_config(poe.default_chat) or {}
        # Check for CSV attachment
        csv_data = None
        for att in poe.query.attachments:
            if att.name and att.name.lower().endswith('.csv'):
                csv_data = att.get_contents().decode('utf-8', errors='replace')
                break

        if csv_data:
            # Parse CSV directly
            try:
                df = pd.read_csv(io.StringIO(csv_data))
                df.columns = [c.strip() for c in df.columns]
                config = dict(existing)
                col_map = {}
                for c in df.columns:
                    cl = c.lower()
                    if cl in ('策略', 'strategy', 'sub', '子策略'):
                        col_map['strategy'] = c
                    elif cl in ('etf', 'ticker', '代码', '标的', 'code', 'symbol'):
                        col_map['etf'] = c
                    elif cl in ('数量', 'shares', 'qty', '股数', '持仓', 'quantity', 'amount'):
                        col_map['shares'] = c

                if 'etf' not in col_map or 'shares' not in col_map:
                    raise poe.BotError(
                        "CSV格式不正确。需要至少包含ETF和数量两列。\n"
                        "支持的列名:\n"
                        "- ETF列: ETF, ticker, 代码, 标的, code, symbol\n"
                        "- 数量列: 数量, shares, qty, 股数, 持仓, quantity\n"
                        "- 策略列(可选): 策略, strategy, sub")

                if 'strategy' in col_map:
                    for _, row in df.iterrows():
                        strat = str(row[col_map['strategy']]).strip()
                        etf = str(row[col_map['etf']]).strip()
                        shares = int(float(row[col_map['shares']]))
                        if strat not in config:
                            config[strat] = {}
                        config[strat][etf] = shares
                else:
                    query_text = poe.query.text.strip()
                    strategy = None
                    for s in ["Sub-A-DK", "Sub-A", "Sub-B", "Sub-C"]:
                        if s.lower() in query_text.lower() or s in query_text:
                            strategy = s
                            break
                    if not strategy:
                        us_rot_etfs = set(_ROT_PROXY_TO_LIVE.keys()) | set(_ROT_PROXY_TO_LIVE.values())
                        prod_etfs = set(PROD_PORTFOLIO.keys())
                        etfs = [str(r).strip().upper() for r in df[col_map['etf']]]
                        if any(e in us_rot_etfs for e in etfs):
                            strategy = "Sub-B"
                        elif any(e in prod_etfs for e in etfs):
                            strategy = "Sub-C"
                        else:
                            raise poe.BotError(
                                "无法判断仓位属于哪个策略。请在消息中指明策略，例如:\n"
                                "\"设置仓位 Sub-B\" 并附上CSV文件")
                    config[strategy] = {}
                    for _, row in df.iterrows():
                        etf = str(row[col_map['etf']]).strip()
                        shares = int(float(row[col_map['shares']]))
                        config[strategy][etf] = shares
            except poe.BotError:
                raise
            except Exception as e:
                raise poe.BotError(f"CSV解析失败: {e}")
        else:
            # Use LLM to parse text
            ctx_parts = []
            for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:
                v = existing.get(s)
                if v:
                    items_list = []
                    for k, v_ in v.items():
                        if isinstance(v_, dict) and 'amount' in v_:
                            items_list.append(f"{k}: {v_['amount']:,.0f}元")
                        else:
                            items_list.append(f"{k}: {v_}股")
                    ctx_parts.append(f"- {s}: {', '.join(items_list)}")
                else:
                    ctx_parts.append(f"- {s}: 未设置")

            prompt = f"""解析仓位设置。

四个子策略可设置仓位:
Sub-A: A股轮动 - ETF代码格式如 1.515100(中证红利低波), 0.159915(创业板)
Sub-A-DK: A股多空 - 用指数期货/ETF实现, 标的: 中证1000(000852), 上证50(000016), 可填合约张数或ETF股数
Sub-B: 美股9ETF轮动 - ETF代码如 VOO, QQQM, GLDM, VGLT, EMXC, VEA, SCHH, PDBC, IBIT, BIL
Sub-C: 美股7ETF组合 - ETF代码如 VTI, QQQM, VEA, VGIT, DBMF, GLDM, IBIT

当前已设置的仓位:
{chr(10).join(ctx_parts)}

用户输入: {poe.query.text}

输出```json格式:
```json
{{
  "Sub-A": {{"ETF代码": 股数或{{"amount": 金额数字}}}} 或 null,
  "Sub-A-DK": {{"标的代码": 数量或{{"amount": 金额数字}}}} 或 null,
  "Sub-B": {{"ETF代码": 股数或{{"amount": 金额数字}}}} 或 null,
  "Sub-C": {{"ETF代码": 股数或{{"amount": 金额数字}}}} 或 null
}}
```

规则:
1. 股数为整数
2. 用户只设置部分策略 -> 未提到的填null(保持之前的设置)
3. "股"=股数, "手"=100股(A股), "张"=合约张数
4. 如果用户说"清空"某策略的仓位 -> 填空字典 {{}}
5. ETF代码保持原样(区分大小写)
6. 如果用户指定某个标的的金额(万/百万/元/人民币/美元等), 对应标的输出 {{"amount": 金额数字(转为基本单位,元或美元)}}
   例: "中证1000持仓200万" -> "中证1000": {{"amount": 2000000}}
   如果用户说"100股", 直接输出整数 100
7. 关键: 如果用户只指定策略的总金额, 不列出具体标的(如"策略C持仓100万美元"、"Sub-B总共50万"), 输出 {{"_total_amount": 金额数字}}
   例: "策略C持仓100万美元" -> "Sub-C": {{"_total_amount": 1000000}}
   例: "Sub-B总共50万美元" -> "Sub-B": {{"_total_amount": 500000}}
   注意: _total_amount表示策略总金额, 和具体标的的amount不同"""

            with _sm() as msg:
                msg.write("⏳ 正在解析仓位设置...\n")
            response = poe.call("Grok-4.1-Fast-Non-Reasoning", prompt)
            try:
                parsed = _parse_json_from_response(response.text, [])
            except (json.JSONDecodeError, ValueError):
                raise poe.BotError(
                    "无法解析仓位设置，请用更明确的语言，例如:\n"
                    "- 设置仓位 Sub-B: VOO 100股 QQQM 50股 GLDM 200股\n"
                    "- 设置仓位 Sub-A-DK: 中证1000持仓200万人民币\n"
                    "- 设置仓位 Sub-C: VTI 300 QQQM 100 VEA 200\n"
                    "- 或上传CSV文件(列: ETF, 数量)")
            config = dict(existing)
            cap_config = _scan_capital_config(poe.default_chat) or {}
            cap_updated = False
            for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:
                v = parsed.get(s)
                if v is not None and isinstance(v, dict):
                    # Check for total amount (user specified strategy total, not per-ETF)
                    if '_total_amount' in v:
                        total = float(v['_total_amount'])
                        if total > 0:
                            if s == "Sub-C":
                                # Sub-C has fixed weights -> distribute to per-ETF amounts
                                new_pos = {}
                                for etf, cfg in PROD_PORTFOLIO.items():
                                    new_pos[etf] = {"amount": round(total * cfg['w'], 2)}
                                config[s] = new_pos
                            else:
                                # Sub-B/Sub-A/Sub-A-DK: weights are dynamic -> set as capital
                                cap_config[s] = total
                                cap_updated = True
                    else:
                        new_pos = {}
                        for k, v_ in v.items():
                            if isinstance(v_, dict) and 'amount' in v_:
                                amt = float(v_['amount'])
                                if amt > 0:
                                    new_pos[k] = {"amount": amt}
                            elif isinstance(v_, (int, float)) and v_ > 0:
                                new_pos[k] = int(float(v_))
                        config[s] = new_pos

        currency_label = {"Sub-A": "A股", "Sub-A-DK": "A股(多空)", "Sub-B": "美股", "Sub-C": "美股"}
        currency_symbol = {"Sub-A": "¥", "Sub-A-DK": "¥", "Sub-B": "$", "Sub-C": "$"}
        with _sm() as msg:
            w = msg.write
            w("## 📊 仓位配置已更新\n\n")
            for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:
                pos = config.get(s)
                if pos:
                    ccy = currency_symbol.get(s, "")
                    w(f"### {s} ({currency_label[s]})\n")
                    w("| 标的 | 持仓 |\n|:-|--------:|\n")
                    for etf, val in sorted(pos.items()):
                        if isinstance(val, dict) and 'amount' in val:
                            w(f"| {etf} | {ccy}{val['amount']:,.0f} |\n")
                        else:
                            w(f"| {etf} | {val:,}股 |\n")
                    w("\n")
            # Show capital updates from _total_amount conversion
            if cap_updated:
                w("### 💰 资金配置（按总额设置）\n")
                for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:
                    if s in cap_config and parsed.get(s) and '_total_amount' in parsed[s]:
                        ccy = currency_symbol.get(s, "")
                        w(f"- **{s}**: {ccy}{cap_config[s]:,.0f}")
                        if s == "Sub-B":
                            w("（持仓比例随信号变化，查询信号时自动计算各ETF目标数量）")
                        elif s in ("Sub-A", "Sub-A-DK"):
                            w("（持仓标的随信号变化，查询信号时自动计算目标数量）")
                        w("\n")
                w("\n")
            if not any(config.get(s) for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]) and not cap_updated:
                w("暂无仓位设置\n")
            w("\n✅ 信号查询时将自动显示仓位调整建议\n")
            w(_build_position_marker(config))
            if cap_updated:
                w(_build_capital_marker(cap_config))

poe.update_settings(SettingsResponse(
    introduction_message=(
        "📝 **Trade Journal V5 — 模拟实盘交易**\n\n"
        "四策略组合: Sub-A 15% + Sub-A-DK 15% + Sub-B 40% + Sub-C 30%\n\n"
        "**记录交易:**\n"
        '- 自然语言: "Sub-A换仓到ZZHL-ETF了 成交价1.234 买了5000股 手续费5块"\n'
        '- 发送 **"交易记录"** -> 查看所有记录\n'
        '- 发送 **"删除记录 xxx"** -> 删除指定记录\n\n'
        "**实盘分析:**\n"
        '- 发送 **"实盘持仓"** -> 实际 vs 理论持仓对比\n'
        '- 发送 **"实盘表现"** -> 实际 vs 理论表现对比\n'
        '- 发送 **"执行分析"** -> 执行质量分析\n\n'
        "**导入导出:**\n"
        '- 发送 **"导出日志"** -> JSON+CSV导出\n'
        "- 上传JSON文件 -> 导入交易记录\n\n"
        "**💰 资金管理:** \"设置资金 Sub-B 5万美元\"\n"
        "**📊 仓位管理:** \"设置仓位 Sub-B: VOO 100股 QQQM 50股\" 或 \"设置仓位 Sub-A-DK: 中证1000持仓200万\"\n"
    ),
))

class CombinedStrategyV4(CombinedStrategyBase):

    def run(self):
        query = poe.query.text.strip()
        if poe.query.attachments:
            for att in poe.query.attachments:
                if att.name and att.name.endswith('.json'):
                    self._handle_import_log()
                    return
        if "实盘表现" in query:
            self._handle_live_performance(query)
        elif "实盘持仓" in query:
            self._handle_live_portfolio()
        elif "交易记录" in query:
            self._handle_trade_history()
        elif "执行分析" in query:
            self._handle_execution_analysis()
        elif "导出日志" in query:
            self._handle_export_log()
        elif "删除记录" in query:
            self._handle_delete_record(query)
        elif ("设置" in query or "设定" in query or "配置" in query) and "资金" in query:
            self._handle_set_capital()
        elif ("设置" in query or "设定" in query or "配置" in query) and "仓位" in query:
            self._handle_set_position()
        elif _is_trade_recording(query):
            self._handle_record_trade()
        else:
            with _sm() as msg:
                msg.write("❓ 无法识别指令。可用指令:\n\n")
                msg.write("- 自然语言记录交易\n")
                msg.write("- **交易记录** / **删除记录 xxx**\n")
                msg.write("- **实盘持仓** / **实盘表现** / **执行分析**\n")
                msg.write("- **导出日志** / 上传JSON导入\n")
                msg.write("- **设置资金 Sub-B 5万美元**\n")
                msg.write("- **设置仓位 Sub-B: VOO 100股** 或 **设置仓位 Sub-A-DK: 中证1000持仓200万**\n")
    def _handle_record_trade(self):
        existing = _scan_trade_logs(poe.default_chat)
        latest = _get_latest_holdings(existing)
        ctx = []
        for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:
            r = latest.get(s)
            if r:
                w = r.get("weights", {})
                if w:
                    ctx.append(f"- {s}: " + ", ".join(
                        f"{k}:{v:.0%}" for k, v in w.items()
                        if isinstance(v, (int, float)) and v > 0.005))
                else:
                    ctx.append(f"- {s}: {r.get('to_holding', '?')}")
            else:
                ctx.append(f"- {s}: 尚未记录")
        today = beijing_now().strftime("%Y-%m-%d")
        prompt = f"""你是交易记录解析器。从用户自然语言中提取结构化交易信息。

策略和可选标的:
- Sub-A: A股做多轮动 (ZZHL-ETF, CYB-ETF, HS300, ZZ1000, ZZ500, Cash)
- Sub-A-DK: ZZ1000/SZ50多空 (做多中证1000/做空上证50, 或反过来)
- Sub-B: 美股9ETF (VOO, QQQM, EMXC, VEA, GLDM, VGLT, SCHH, PDBC, IBIT, BIL/现金)
- Sub-C: 美股7ETF组合 (VTI, QQQM, VEA, VGIT, DBMF, GLDM, IBIT)

用户当前已记录持仓:
{chr(10).join(ctx)}

今天: {today}

用户输入: {poe.query.text}

关键: 如果用户提到多个策略的操作, 必须输出JSON数组(每个策略一条记录)!

输出```json格式:
```json
[
  {{
    "strategy": "Sub-A",
    "action": "buy/sell/switch/flip/rebalance/skip/hold",
    "from_holding": "之前持仓或null",
    "to_holding": "新持仓描述",
    "exec_prices": {{"标的": 价格}},
    "quantities": {{"标的": 数量或{{"amount": 金额数字}}}},
    "weights": {{"标的": 0.xx}},
    "commission": {{"amount": 总手续费金额或null, "rate": 费率或null}},
    "notes": "补充说明",
    "signal_followed": true/false/null,
    "trade_date": "YYYY-MM-DD或null"
  }}
]
```

规则:
1. 每个策略必须单独一条记录! 涉及多个策略 -> 数组里多条记录, 单个策略 -> 数组里一条记录
2. skip=没跟信号 3. Sub-A标的:ZZHL-ETF/CYB-ETF/HS300/ZZ1000/ZZ500/Cash
4. Sub-B/C用大写ETF代码 5. Sub-A-DK: "做多中证1000"或"做多上证50"
6. exec_prices:价格,没有写{{}} 7. quantities:数量(整数),50手=5000,没有写{{}}
8. weights:仅多标的时填 9. commission:手续费5块->amount:5,千一->rate:0.001,没提->null
10. signal_followed:true/false/null 11. trade_date:今天={today},没说=null
12. from_holding:根据描述或记录推断,不确定=null
13. 如果用户指定金额(万/人民币/美元等), quantities里对应标的输出 {{"amount": 金额数字(基本单位)}}
    例: "中证一千50万人民币" -> quantities: {{"中证1000": {{"amount": 500000}}}}
    例: "C策略30万美元" -> quantities: {{"_total": {{"amount": 300000}}}} (策略总金额用"_total"作为key)
14. "红利低波"="ZZHL-ETF"=1.515100, "创业板"="CYB-ETF"=0.159915"""

        with _sm() as msg:
            w = msg.write
            w("⏳ 正在解析交易记录...\n")
        response = poe.call("Grok-4.1-Fast-Non-Reasoning", prompt)
        # --- Parse JSON array (one record per strategy) ---
        try:
            raw = response.text
            m_arr = re.search(r'```json\s*(\[.*?\])\s*```', raw, re.DOTALL)
            if m_arr:
                records_parsed = json.loads(m_arr.group(1).strip())
            else:
                m_arr = re.search(r'\[.*\]', raw, re.DOTALL)
                if m_arr:
                    try:
                        records_parsed = json.loads(m_arr.group(0).strip())
                    except json.JSONDecodeError:
                        records_parsed = None
                else:
                    records_parsed = None
            if records_parsed is None:
                parsed_single = _parse_json_from_response(
                    raw, ["strategy", "action", "to_holding"])
                records_parsed = [parsed_single]
            if isinstance(records_parsed, dict):
                records_parsed = [records_parsed]
            if not records_parsed:
                raise ValueError("Empty")
        except (json.JSONDecodeError, ValueError):
            raise poe.BotError(
                "无法解析交易描述，请用更明确的语言，例如:\n"
                "- Sub-A换仓到ZZHL-ETF了\n"
                "- Sub-B调仓 VOO 40% GLDM 30% IBIT 30%\n"
                "- Sub-A-DK翻转做多中证1000了\n"
                "- Sub-A没跟今天的信号")
        for _p in records_parsed:
            for _f in ("strategy", "action", "to_holding"):
                if _f not in _p:
                    raise poe.BotError(f"解析结果缺少字段 '{_f}'，请重试")
        now = beijing_now()
        all_new_recs = []
        for parsed in records_parsed:
            if not parsed.get("from_holding"):
                s = parsed["strategy"]
                if s in latest:
                    parsed["from_holding"] = latest[s].get("to_holding")
            raw_comm = parsed.get("commission") or {}
            comm_amount = raw_comm.get("amount") if isinstance(raw_comm, dict) else None
            comm_rate = raw_comm.get("rate") if isinstance(raw_comm, dict) else None
            trade_val = 0
            ep = parsed.get("exec_prices") or {}
            qt = parsed.get("quantities") or {}
            for k in set(list(ep.keys()) + list(qt.keys())):
                p = ep.get(k, 0)
                q = qt.get(k, 0)
                if k == "_total":
                    if isinstance(q, dict) and "amount" in q:
                        trade_val += float(q["amount"])
                elif isinstance(q, dict) and "amount" in q:
                    trade_val += float(q["amount"])
                elif isinstance(p, (int, float)) and isinstance(q, (int, float)) and p > 0 and q > 0:
                    trade_val += p * q
            if comm_rate and isinstance(comm_rate, (int, float)) and comm_rate > 0:
                if comm_amount is None and trade_val > 0:
                    comm_amount = round(trade_val * comm_rate, 2)
            elif comm_amount and isinstance(comm_amount, (int, float)) and comm_amount > 0:
                if comm_rate is None and trade_val > 0:
                    comm_rate = round(comm_amount / trade_val, 6)
            rec = {
                "v": 1, "id": _gen_trade_id(existing + all_new_recs),
                "ts": now.isoformat(),
                "trade_date": parsed.get("trade_date") or today,
                "strategy": parsed["strategy"], "action": parsed["action"],
                "from_holding": parsed.get("from_holding"),
                "to_holding": parsed["to_holding"],
                "exec_prices": ep,
                "quantities": qt,
                "weights": parsed.get("weights") or {},
                "commission": {"amount": comm_amount, "rate": comm_rate},
                "notes": parsed.get("notes") or "",
                "signal_followed": parsed.get("signal_followed"),
            }
            all_new_recs.append(rec)
        # --- Display each record and write trade markers ---
        for rec in all_new_recs:
            act = _ACTION_CN_MAP.get(rec["action"], rec["action"])
            _ccy = "¥" if rec["strategy"] in ("Sub-A", "Sub-A-DK") else "$"
            _theo_rate = CN_COMMISSION if rec["strategy"] in ("Sub-A", "Sub-A-DK") else US_ROT_COMMISSION
            qt = rec["quantities"]
            ep = rec["exec_prices"]
            trade_val = 0
            for k in set(list(ep.keys()) + list(qt.keys())):
                pv = ep.get(k, 0)
                qv = qt.get(k, 0)
                if k == "_total":
                    if isinstance(qv, dict) and "amount" in qv:
                        trade_val += float(qv["amount"])
                elif isinstance(qv, dict) and "amount" in qv:
                    trade_val += float(qv["amount"])
                elif isinstance(pv, (int, float)) and isinstance(qv, (int, float)) and pv > 0 and qv > 0:
                    trade_val += pv * qv
            with _sm() as msg:
                w = msg.write
                w("## ✅ 交易已记录\n\n| 项目 | 内容 |\n|:-|:-|\n")
                w(f"| ID | `{rec['id']}` |\n")
                w(f"| 交易日期 | {rec['trade_date']} |\n")
                w(f"| 策略 | **{rec['strategy']}** |\n")
                w(f"| 操作 | {act} |\n")
                if rec["from_holding"]:
                    w(f"| 原持仓 | {rec['from_holding']} |\n")
                w(f"| 新持仓 | **{rec['to_holding']}** |\n")
                if ep:
                    for k, v in ep.items():
                        w(f"| 执行价格 | {k}: {v} |\n")
                if qt:
                    for k, v in qt.items():
                        if k == "_total":
                            if isinstance(v, dict) and "amount" in v:
                                w(f"| 总金额 | {_ccy}{float(v['amount']):,.0f} |\n")
                        elif isinstance(v, dict) and "amount" in v:
                            w(f"| 金额 | {k}: {_ccy}{float(v['amount']):,.0f} |\n")
                        elif isinstance(v, (int, float)) and v > 0:
                            w(f"| 数量 | {k}: {v:,.0f} 股 |\n")
                if rec["weights"]:
                    ws = ", ".join(
                        f"{k}: {v:.0%}" for k, v in rec["weights"].items()
                        if isinstance(v, (int, float)) and v > 0.005)
                    if ws:
                        w(f"| 权重 | {ws} |\n")
                if trade_val > 0:
                    w(f"| 持仓市值 | {_ccy}{trade_val:,.2f} |\n")
                _comm = rec["commission"]
                if _comm.get("amount") or _comm.get("rate"):
                    comm_parts = []
                    if _comm.get("amount"):
                        comm_parts.append(f"{_ccy}{_comm['amount']:,.2f}")
                    if _comm.get("rate"):
                        r = _comm["rate"]
                        if r < 0.01:
                            comm_parts.append(f"{r*1000:.2f}‰")
                        else:
                            comm_parts.append(f"{r:.2%}")
                    comm_str = " / ".join(comm_parts)
                    if _comm.get("rate") and abs(_comm["rate"] - _theo_rate) > 0.00001:
                        diff = _comm["rate"] - _theo_rate
                        comm_str += f" (回测假设{_theo_rate*1000:.1f}‰, 差{diff*1000:+.2f}‰)"
                    w(f"| 交易成本 | {comm_str} |\n")
                sig = rec["signal_followed"]
                w(f"| 跟随信号 | "
                          f"{'✅ 是' if sig is True else ('❌ 否' if sig is False else '—')}"
                          f" |\n")
                if rec["notes"]:
                    w(f"| 备注 | {rec['notes']} |\n")
                w(f"\n💡 如需修改，发送 \"删除记录 {rec['id']}\"\n")
                w(_build_trade_marker(rec))
    def _handle_delete_record(self, query):
        m = re.search(r'T\d{8}_\d{3}', query)
        if not m:
            raise poe.BotError("请提供记录ID，例如: 删除记录 T20260312_001")
        tid = m.group(0)
        existing = _scan_trade_logs(poe.default_chat)
        found = next((r for r in existing if r.get("id") == tid), None)
        if not found:
            raise poe.BotError(f"未找到记录 `{tid}`")
        del_rec = {"v": 1, "id": tid, "action": "_deleted",
                   "ts": beijing_now().isoformat()}
        act = _ACTION_CN_MAP.get(found.get("action", ""), found.get("action", ""))
        with _sm() as msg:
            w = msg.write
            w(f"## 🗑️ 记录已删除\n\n")
            w(f"- ID: `{tid}`\n")
            w(f"- 策略: {found.get('strategy', '?')} | "
                      f"操作: {act} | 持仓: {found.get('to_holding', '?')}\n")
            w(_build_trade_marker(del_rec))
    def _handle_trade_history(self):
        records = _scan_trade_logs(poe.default_chat)
        if not records:
            raise poe.BotError(
                "无记录。\n\n用自然语言记录交易，例如:\n"
                "- Sub-A换仓到ZZHL-ETF了\n"
                "- Sub-B调仓 VOO 40% GLDM 30% IBIT 30%")
        with _sm() as msg:
            w = msg.write
            w(f"## 📋 交易记录 ({len(records)}条)\n\n")
            w("| # | 日期 | 策略 | 操作 | 详情 | 备注 |\n|:-|:-|:-|:-|:-|:-|\n")
            for i, r in enumerate(records, 1):
                act = _ACTION_CN_MAP.get(r.get("action", ""), r.get("action", ""))
                to_h = r.get("to_holding", "?")
                wts = r.get("weights", {})
                if wts:
                    parts = [f"{k}:{v:.0%}" for k, v in wts.items()
                             if isinstance(v, (int, float)) and v > 0.005]
                    if parts:
                        to_h = " ".join(parts)
                frm = r.get("from_holding", "")
                detail = f"{frm}->{to_h}" if frm and frm != to_h else to_h
                ep = r.get("exec_prices", {})
                if ep:
                    detail += " " + " ".join(f"@{v}" for v in ep.values())
                sig = r.get("signal_followed")
                sig_i = " ✅" if sig is True else (
                    " ❌" if sig is False else "")
                notes = (r.get("notes", "") or "")[:20]
                w(f"| {i} | {r.get('trade_date', '?')} | "
                          f"{r.get('strategy', '?')} | {act}{sig_i} | "
                          f"{detail} | {notes} |\n")
            w("\n### 各策略持仓\n\n")
            latest = _get_latest_holdings(records)
            for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:
                rec = latest.get(s)
                if rec:
                    h = rec.get("to_holding", "?")
                    wts = rec.get("weights", {})
                    if wts:
                        ws = ", ".join(
                            f"{k}:{v:.0%}" for k, v in wts.items()
                            if isinstance(v, (int, float)) and v > 0.005)
                        w(f"- **{s}**: {ws} "
                                  f"(记录于 {rec.get('trade_date', '?')})\n")
                    else:
                        w(f"- **{s}**: **{h}** "
                                  f"(记录于 {rec.get('trade_date', '?')})\n")
                else:
                    w(f"- **{s}**: _未记录_\n")
        cb = generate_trade_log_csv(records)
        fname = f"trade_log_{beijing_now().strftime('%Y%m%d')}.csv"
        with _sm() as msg:
            w = msg.write
            msg.attach_file(name=fname, contents=cb, content_type="text/csv")
            w(f"📎 **{fname}**")
    def _handle_live_portfolio(self):
        records = _scan_trade_logs(poe.default_chat)
        latest = _get_latest_holdings(records)
        if not records:
            raise poe.BotError(
                "无记录，无法显示实盘持仓。\n请先记录交易。")
        with _sm() as msg:
            w = msg.write
            cn_close, cn_dk_close, us_rot_close, us_prod_daily = \
                self._fetch_data(msg)
            w("⏳ 正在计算策略信号...\n")
        d = self._compute_signal_data(
            cn_close, cn_dk_close, us_rot_close, us_prod_daily)
        with _sm() as msg:
            w = msg.write
            w("## 📊 实盘持仓 vs 理论持仓\n\n| 策略 | 实际持仓 | 策略持仓 | 匹配 |\n|:-|:-|:-|:-|\n")
            a_rec = latest.get("Sub-A")
            actual_a = a_rec.get("to_holding", "—") if a_rec else "—"
            theo_a_code = d["cn_current"]
            theo_a = CN_NAMES.get(theo_a_code, theo_a_code)
            if a_rec:
                match_a = ("✅" if _normalize_cn_holding(actual_a) == theo_a_code
                           else "⚠️ 不一致")
            else:
                match_a = "未记录"
            w(f"| Sub-A | {actual_a} | {theo_a} | {match_a} |\n")
            dk_rec = latest.get("Sub-A-DK")
            actual_dk = dk_rec.get("to_holding", "—") if dk_rec else "—"
            dk_h = d["dk_current"]
            theo_dk = f"做多{CN_DK_NAMES.get(dk_h, dk_h)}"
            if dk_rec:
                match_dk = "✅" if actual_dk == theo_dk else "⚠️ 不一致"
            else:
                match_dk = "未记录"
            w(f"| Sub-A-DK | {actual_dk} | {theo_dk} | {match_dk} |\n")
            # VolReg风控状态
            _vr = d.get("volreg_ratio")
            _vr_cash = d.get("volreg_cash_today", False)
            if US_ROT_VOLREG_ENABLED and _vr is not None:
                if _vr > US_ROT_VOLREG_THRESHOLD:
                    w(f"\n🔴 **Sub-B VolReg风控:** SPY波动率比={_vr:.2f} > {US_ROT_VOLREG_THRESHOLD}，**明日转现金**\n\n")
                elif _vr_cash:
                    w(f"\n🟡 **Sub-B VolReg风控:** 今日已转现金(昨日触发) | SPY波动率比={_vr:.2f}\n\n")
                else:
                    w(f"\n🟢 **Sub-B VolReg风控:** SPY波动率比={_vr:.2f} < {US_ROT_VOLREG_THRESHOLD}，正常\n\n")
            b_rec = latest.get("Sub-B")
            b_w = b_rec.get("weights", {}) if b_rec else {}
            theo_b = d["current_us_w"]
            if b_w:
                ab_str = ", ".join(
                    f"{k}:{v:.0%}" for k, v in sorted(b_w.items())
                    if isinstance(v, (int, float)) and v > 0.005)
            else:
                ab_str = (b_rec.get("to_holding", "—") if b_rec else "—")
            tb_str = ", ".join(
                f"{_ROT_PROXY_TO_LIVE.get(k,k)}:{v:.0%}"
                for k, v in sorted(theo_b.items()) if v > 0.005)
            w(f"| Sub-B | {ab_str} | {tb_str} | "
                      f"{'📊' if b_rec else '未记录'} |\n")
            c_rec = latest.get("Sub-C")
            ac_str = (c_rec.get("to_holding", "—") if c_rec else "—")
            tc_parts = [f"{n}:{c['w']:.0%}" for n, c in PROD_PORTFOLIO.items()]
            w(f"| Sub-C | {ac_str} | {', '.join(tc_parts)} | "
                      f"{'📊' if c_rec else '未记录'} |\n")
            if b_w and theo_b:
                w("\n### Sub-B 权重对比\n\n")
                all_e = sorted(set(
                    list(b_w.keys()) + [k for k in theo_b.keys()]))
                w("| ETF | 实际 | 策略 | 差异 |\n"
                          "|:-|-----:|-----:|-----:|\n")
                for e in all_e:
                    aw = b_w.get(e, 0)
                    if not isinstance(aw, (int, float)):
                        aw = 0
                    tw = theo_b.get(e, 0)
                    if aw < 0.005 and tw < 0.005:
                        continue
                    live = _ROT_PROXY_TO_LIVE.get(e, e)
                    df = aw - tw
                    ds = f"{df:+.1%}" if abs(df) > 0.005 else "—"
                    w(f"| {live} | {aw:.1%} | {tw:.1%} | {ds} |\n")
            w(f"\n⏱ 数据: A股{d['cn_date'].strftime('%Y-%m-%d')} / "
                      f"美股{d['us_date'].strftime('%Y-%m-%d')}")
    def _handle_live_performance(self, query):
        records = _scan_trade_logs(poe.default_chat)
        if not records:
            raise poe.BotError("无记录，不能算实盘表现。")
        q2 = query.replace("实盘", "")
        start_date, end_date = parse_date_range(q2)
        if start_date is None:
            first_d = min(r.get("trade_date", "9999") for r in records)
            start_date = pd.Timestamp(first_d)
            end_date = pd.Timestamp(beijing_now().strftime("%Y-%m-%d"))
        with _sm() as msg:
            w = msg.write
            cn_close, cn_dk_close, us_rot_close, us_prod_daily = \
                self._fetch_data(msg)
            w("⏳ 正在计算...\n")
        cn_result, cn_dk_result, us_rot_result, *_ = \
            self._run_strategies(
                cn_close, cn_dk_close, us_rot_close, us_prod_daily)
        theo_cn_ret = cn_result["return"]
        cn_ret_df = cn_close.pct_change()
        sub_a_recs = sorted(
            [r for r in records
             if r.get("strategy") == "Sub-A" and r.get("action") != "skip"],
            key=lambda r: r.get("trade_date", ""))
        actual_cn_ret = None
        if sub_a_recs:
            changes = []
            for r in sub_a_recs:
                td = pd.Timestamp(r.get("trade_date"))
                code = _normalize_cn_holding(r.get("to_holding"))
                changes.append((td, code))
            actual_h = pd.Series("none", index=cn_result.index)
            first_from = _normalize_cn_holding(
                sub_a_recs[0].get("from_holding"))
            timeline = []
            if first_from:
                timeline.append((pd.Timestamp.min, first_from))
            for td, code in changes:
                timeline.append((td + pd.Timedelta(days=1), code))
            for start, code in timeline:
                actual_h[cn_result.index >= start] = code
            actual_cn_ret = pd.Series(0.0, index=cn_result.index)
            for code in actual_h.unique():
                mask = actual_h == code
                if code == "none":
                    continue
                elif code == "cash":
                    actual_cn_ret[mask] = CN_RF_DAILY
                elif code in cn_ret_df.columns:
                    actual_cn_ret[mask] = cn_ret_df[code].reindex(
                        cn_result.index).fillna(0)[mask]
        period = (f"{start_date.strftime('%Y-%m-%d')} ~ "
                  f"{end_date.strftime('%Y-%m-%d')}")
        with _sm() as msg:
            w = msg.write
            w(f"## 📊 实盘 vs 策略: {period}\n\n")
            if actual_cn_ret is not None:
                t_a = theo_cn_ret[
                    (theo_cn_ret.index >= start_date) &
                    (theo_cn_ret.index <= end_date)]
                a_a = actual_cn_ret[
                    (actual_cn_ret.index >= start_date) &
                    (actual_cn_ret.index <= end_date)]
                if len(t_a) > 5 and len(a_a) > 5:
                    t_cum = (1 + t_a).cumprod()
                    a_cum = (1 + a_a).cumprod()
                    t_tot = (t_cum.iloc[-1] - 1) * 100
                    a_tot = (a_cum.iloc[-1] - 1) * 100
                    t_dd = ((t_cum - t_cum.cummax()) /
                            t_cum.cummax()).min() * 100
                    a_dd = ((a_cum - a_cum.cummax()) /
                            a_cum.cummax()).min() * 100
                    w("### Sub-A 收益对比\n\n| 指标 | 你的实盘 | 理论 | 差异 |\n|:-|--------:|--------:|-----:|\n")
                    w(f"| 累计收益 | {a_tot:+.2f}% | "
                              f"{t_tot:+.2f}% | {a_tot-t_tot:+.2f}% |\n")
                    w(f"| 最大回撤 | {a_dd:.2f}% | "
                              f"{t_dd:.2f}% | {a_dd-t_dd:+.2f}% |\n")
                    days = len(t_a)
                    if days > 30:
                        t_ann = ((t_cum.iloc[-1]) ** (
                            CN_TRADING_DAYS / days) - 1) * 100
                        a_ann = ((a_cum.iloc[-1]) ** (
                            CN_TRADING_DAYS / days) - 1) * 100
                        w(f"| 年化收益 | {a_ann:+.2f}% | "
                                  f"{t_ann:+.2f}% | {a_ann-t_ann:+.2f}% |\n")
                    w("\n**持仓对比** (30日):\n\n| 日期 | 你的持仓 | 策略持仓 | 一致? |\n|:-|:-|:-|:-:|\n")
                    theo_h = cn_result["holding"]
                    recent = t_a.index[-30:] if len(t_a) >= 30 else t_a.index
                    for day in recent:
                        ah = actual_h.get(day, "none") if actual_cn_ret is not None else "?"
                        th = theo_h.get(day, "?") if day in theo_h.index else "?"
                        a_name = CN_NAMES.get(ah, ah)
                        t_name = CN_NAMES.get(th, th)
                        m_icon = "✅" if ah == th else "❌"
                        w(f"| {day.strftime('%m-%d')} | {a_name} | "
                                  f"{t_name} | {m_icon} |\n")
            w("\n### 执行纪律\n\n")
            total = len(records)
            fol = sum(1 for r in records
                      if r.get("signal_followed") is True)
            nfol = sum(1 for r in records
                       if r.get("signal_followed") is False)
            unclear = total - fol - nfol
            rate = fol / total * 100 if total > 0 else 0
            w(f"- 总交易记录: **{total}** 条\n")
            w(f"- 跟随信号: **{fol}** 条 ({rate:.0f}%)\n")
            w(f"- 未跟信号: **{nfol}** 条\n")
            if unclear:
                w(f"- 未标注: {unclear} 条\n")
            w("\n### 各策略统计\n\n| 策略 | 操作次数 | 跳过次数 | 跟随率 |\n|:-|--------:|--------:|-------:|\n")
            for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:
                sr = [r for r in records if r.get("strategy") == s]
                ops = [r for r in sr if r.get("action") != "skip"]
                skips = [r for r in sr if r.get("action") == "skip"]
                sf = sum(1 for r in sr
                         if r.get("signal_followed") is True)
                st = len(sr)
                r_pct = f"{sf/st*100:.0f}%" if st > 0 else "—"
                w(f"| {s} | {len(ops)} | {len(skips)} | "
                          f"{r_pct} |\n")
            recs_with_price = [r for r in records if r.get("exec_prices")]
            if recs_with_price:
                w(f"\n### 已记录执行价格 ({len(recs_with_price)}条)\n\n")
                w("| 日期 | 策略 | 标的 | 执行价格 |\n|:-|:-|:-|--------:|\n")
                for r in recs_with_price[-10:]:
                    for k, v in r.get("exec_prices", {}).items():
                        w(f"| {r.get('trade_date', '?')} | "
                                  f"{r.get('strategy', '?')} | {k} | {v} |\n")
    def _handle_execution_analysis(self):
        records = _scan_trade_logs(poe.default_chat)
        if not records:
            raise poe.BotError("无记录，无法分析。")
        with _sm() as msg:
            w = msg.write
            w("## 🔍 执行分析\n\n")
            total = len(records)
            fol = sum(1 for r in records
                      if r.get("signal_followed") is True)
            nfol = sum(1 for r in records
                       if r.get("signal_followed") is False)
            skips = sum(1 for r in records if r.get("action") == "skip")
            w("### 总览\n\n| 指标 | 值 |\n|:-|-----:|\n")
            w(f"| 总交易记录 | {total} |\n")
            w(f"| 执行操作 | {total - skips} |\n")
            w(f"| 跳过信号 | {skips} |\n")
            rate_str = f"{fol} ({fol/total*100:.0f}%)" if total > 0 else "—"
            w(f"| 跟随信号 | {rate_str} |\n")
            w(f"| 偏离信号 | {nfol} |\n")
            w("\n### 各策略明细\n\n")
            for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:
                sr = [r for r in records if r.get("strategy") == s]
                if not sr:
                    continue
                w(f"**{s}** ({len(sr)}条):\n")
                ops = [r for r in sr if r.get("action") != "skip"]
                actions = {}
                for r in ops:
                    a = _ACTION_CN_MAP.get(
                        r.get("action", ""), r.get("action", ""))
                    actions[a] = actions.get(a, 0) + 1
                for a, c in sorted(actions.items(), key=lambda x: -x[1]):
                    w(f"- {a}: {c}次\n")
                skips_s = [r for r in sr if r.get("action") == "skip"]
                if skips_s:
                    w(f"- 跳过: {len(skips_s)}次\n")
                dates = sorted(
                    r.get("trade_date", "") for r in sr
                    if r.get("trade_date"))
                if dates:
                    w(f"- 时间跨度: {dates[0]} ~ {dates[-1]}\n")
                if len(dates) >= 2:
                    d_list = [pd.Timestamp(d) for d in dates]
                    intervals = [(d_list[i+1] - d_list[i]).days
                                 for i in range(len(d_list)-1)]
                    avg = sum(intervals) / len(intervals)
                    w(f"- 平均操作间隔: {avg:.0f}天\n")
                w("\n")
            recs_with_price = [r for r in records if r.get("exec_prices")]
            if recs_with_price:
                w("### 已记录的执行价格\n\n")
                w("| 日期 | 策略 | 标的 | 价格 |\n"
                          "|:-|:-|:-|-----:|\n")
                for r in recs_with_price:
                    for k, v in r.get("exec_prices", {}).items():
                        w(f"| {r.get('trade_date', '?')} | "
                                  f"{r.get('strategy', '?')} | {k} | {v} |\n")
            recs_with_comm = [r for r in records
                              if r.get("commission") and (
                                  r["commission"].get("amount") or
                                  r["commission"].get("rate"))]
            if recs_with_comm:
                w("\n### 💰 交易成本分析\n\n")
                for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:
                    sr = [r for r in recs_with_comm if r.get("strategy") == s]
                    if not sr:
                        continue
                    _ccy = "¥" if s in ("Sub-A", "Sub-A-DK") else "$"
                    _theo = CN_COMMISSION if s in ("Sub-A", "Sub-A-DK") else US_ROT_COMMISSION
                    total_comm = sum(r["commission"].get("amount", 0) or 0 for r in sr)
                    rates = [r["commission"]["rate"] for r in sr
                             if r["commission"].get("rate") and
                             isinstance(r["commission"]["rate"], (int, float))]
                    avg_rate = sum(rates) / len(rates) if rates else None
                    w(f"**{s}** ({len(sr)}笔有成本记录):\n")
                    if total_comm > 0:
                        w(f"- 累计交易成本: {_ccy}{total_comm:,.2f}\n")
                    if avg_rate is not None:
                        w(f"- 平均费率: {avg_rate*1000:.2f}‰")
                        diff = avg_rate - _theo
                        if abs(diff) > 0.00001:
                            w(f" (回测假设 {_theo*1000:.1f}‰, "
                                      f"{'高' if diff > 0 else '低'}"
                                      f"{abs(diff)*1000:.2f}‰)")
                        else:
                            w(" (与回测一致)")
                        w("\n")
                    w("\n")
            else:
                w("\n### 💰 交易成本\n\n暂无成本记录。记录交易时可附带成本信息，例如:\n")
                w('- "Sub-A换仓到ZZHL-ETF 成交价1.234 **手续费5块**"\n')
                w('- "买入VOO 420 10股 **佣金万分之五**"\n\n')
            w("💡 持续记录交易后，统计分析将越来越有参考价值。\n")
    def _handle_export_log(self):
        records = _scan_trade_logs(poe.default_chat)
        if not records:
            raise poe.BotError("无记录可导出。")
        now_s = beijing_now().strftime('%Y%m%d')
        jb = json.dumps(
            {"v": 1, "exported": beijing_now().isoformat(),
             "records": records},
            ensure_ascii=False, indent=2).encode("utf-8")
        cb = generate_trade_log_csv(records)
        with _sm() as msg:
            w = msg.write
            msg.attach_file(
                name=f"trade_log_{now_s}.json", contents=jb,
                content_type="application/json")
            w(f"📎 JSON日志: **trade_log_{now_s}.json** "
                      f"({len(records)}条)\n")
            w("💡 将此JSON文件发给机器人即可在新会话中恢复记录\n")
        with _sm() as msg:
            w = msg.write
            msg.attach_file(
                name=f"trade_log_{now_s}.csv", contents=cb,
                content_type="text/csv")
            w(f"📎 CSV日志: **trade_log_{now_s}.csv**")
    def _handle_import_log(self):
        json_att = None
        for att in poe.query.attachments:
            if att.name and att.name.endswith('.json'):
                json_att = att
                break
        if not json_att:
            raise poe.BotError(
                "未检测到JSON文件。请附带trade_log_*.json文件发送。")
        try:
            raw = json_att.get_contents()
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            raise poe.BotError(f"JSON解析失败: {e}")
        imported = data.get("records", [])
        if not imported:
            raise poe.BotError("JSON文件中无交易记录。")
        valid = [r for r in imported
                 if r.get("strategy") and r.get("action")
                 and r.get("action") != "_deleted"]
        with _sm() as msg:
            w = msg.write
            w(f"## 📥 导入交易记录\n\n")
            w(f"成功导入 **{len(valid)}** 条记录\n\n")
            for r in valid:
                w(_build_trade_marker(r))
            w("\n发送 **\"交易记录\"** 查看所有记录")


if __name__ == "__main__":
    bot = CombinedStrategyV4()
    bot.run()
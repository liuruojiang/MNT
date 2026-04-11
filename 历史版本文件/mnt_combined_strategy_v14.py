# poe: name=Combined-Strategy-V4
# poe: privacy_shield=half
"""
Combined Portfolio V4: 4 Sub-Strategies with Signal & Performance Tracking
- Sub-A (CN Long): A-Share 5idx, LB=20, AM=10, RiskAdj=mom/vol(10d), 无波动率缩放
  混合数据源: ZZHL(指数H30269+ETF515100), CYB(指数399006+ETF159915)
  HS300/ZZ1000/ZZ500用指数(股指期货)
- Sub-A-DK (CN Long-Short): 中证1000/上证50多空策略, 20日绝对动量比较, 波动率缩放15%/30d
- Sub-B (US-Rot): US 9ETF rotation (EMXC ex-China EM, EEM proxy pre-2017-08), LB=120, Top3, TV=20%, ML=1.5, Model B
- Sub-C (US-Prod): 7ETF production portfolio, 无择时, annual Dec rebalance
- Combined: Sub-A 15% + Sub-A-DK 15% + Sub-B 40% + Sub-C 30%
V4 changes: Sub-A/Sub-A-DK改为日频检查+冷却期(A:3天,DK:5天), Sub-A新增HS300 MA120均线过滤
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
from zoneinfo import ZoneInfo
from fastapi_poe.types import SettingsResponse

# ---- Settings ----
poe.update_settings(SettingsResponse(
    introduction_message=(
        "📊 **Combined Strategy V4 — 操作信号 & 绩效追踪**\n\n"
        "四策略组合信号输出：\n"
        "- **Sub-A**: A股做多轮动（5只ETF/指数，风险调整排名mom/vol(10d)+绝对动量10日，无波动率缩放）\n"
        "- **Sub-A-DK**: 中证1000/上证50多空（20日绝对动量比较，做多动量高的做空另一个，波动率缩放15%/30d）\n"
        "- **Sub-B**: 美股9ETF轮动（EMXC除中国新兴, 含BTC 2022起参与, LB=120d, Top3, TV=20%, ML=1.5, BTC≤30%）\n"
        "- **Sub-C**: 美股7ETF生产组合（VTI/QQQM/VEA/VGIT/DBMF/GLDM/IBIT, 无择时·纯持有, 年度12月再平衡）\n"
        "- **组合**: Sub-A 15% + Sub-A-DK 15% + Sub-B 40% + Sub-C 30%\n\n"
        "**用法：**\n"
        '- 发送 **"信号"** → 收盘确认信号 + 执行指令 + Excel调仓记录（基于收盘数据，不含假设）\n'
        '- 发送 **"实时信号"** → 实时数据快照，假设现在收盘会产生什么信号、是否调仓\n'
        '- 发送 **"参数"** → 查看四策略核心参数及计算过程\n'
        '- 发送 **"实时参数"** → 查看当前实时计算值（动量/波动率/得分等）\n'
        '- 发送 **"表现 过去两年"** → 查看该时段子策略&组合绩效\n'
        '- 发送 **"表现 2024至今"** / **"表现 最近6个月"** / **"表现 2024年"**\n'
        '- 发送 **"净值曲线 过去两年"** → 绘制子策略和组合的净值走势图\n'
        '- 发送 **"净值曲线 今年"** / **"净值曲线 2024-01到2025-06"**\n'
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
CN_VOL_RANK_LB = 10           # V11: 排名用波动率窗口(交易日), mom/vol风险调整排名
CN_STOCK_CODES = ["1.515100", "0.159915", "1.000300", "1.000852", "1.000905"]
CN_NAMES = {"1.515100": "ZZHL-ETF", "0.159915": "CYB-ETF", "1.000300": "HS300",
            "1.000852": "ZZ1000", "1.000905": "ZZ500", "cash": "Cash"}

# 混合数据源: 回测用指数(更长历史), 实盘用ETF(实际交易标的)
# ZZHL: 2020-07前用红利低波全收益指数(H30269), 之后用ETF(515100)
CN_ZZHL_INDEX_SECID = "1.H30269"
CN_ZZHL_ETF_SECID = "1.515100"
CN_ZZHL_ETF_START = pd.Timestamp("2020-07-03")
# CYB: ETF上市前用创业板指数(399006), 之后用创业板ETF(159915)
CN_CYB_INDEX_SECID = "0.399006"
CN_CYB_ETF_SECID = "0.159915"
CN_CYB_ETF_START = pd.Timestamp("2011-12-09")  # 159915上市日

# --- Sub-A-DK: 中证1000/上证50 多空策略 + Vol Scaling ---
# 比较20日绝对动量，做多动量高的，做空另一个，永远满仓(一多一空)
CN_DK_ZZ1000_CODE = "000852"      # 中证1000指数 (csindex.com.cn)
CN_DK_SZ50_CODE = "000016"        # 上证50指数 (csindex.com.cn)
CN_DK_ZZ1000_SECID = "1.000852"   # EastMoney fallback
CN_DK_SZ50_SECID = "1.000016"     # EastMoney fallback
CN_DK_MOM_LB = 20                 # 20日绝对动量比较窗口
CN_DK_COLS = ["DK_ZZ1000", "DK_SZ50"]  # Column names in dk_close DataFrame
CN_DK_NAMES = {"DK_ZZ1000": "中证1000", "DK_SZ50": "上证50"}
CN_DK_TARGET_VOL = 0.15           # 目标年化波动率 15%
CN_DK_VOL_WINDOW = 30             # 波动率计算窗口 30交易日
CN_DK_MAX_LEV = 1.5               # 最大杠杆1.5x(低波动时可放大)
CN_DK_MIN_LEV = 0.1               # 最小杠杆0.1x(高波动时最低仓位)
CN_DK_TRADING_DAYS = 242          # A-DK年化交易日数(与原始脚本一致)

# --- Sub-B: US 9ETF Rotation ---
US_ROT_COMMISSION = 0.001
US_TRADING_DAYS = 252
US_ROT_ASSETS = {
    "VOO":  {"proxy": "SPY",  "label": "S&P 500"},
    "QQQM": {"proxy": "QQQ",  "label": "Nasdaq 100"},
    "EMXC": {"proxy": "EMXC", "label": "新兴市场(除中国)"},
    "VEA":  {"proxy": "EFA",  "label": "发达市场"},
    "GLDM": {"proxy": "GLD",  "label": "黄金"},
    "VGLT": {"proxy": "TLT",  "label": "长期国债"},
    "SCHH": {"proxy": "VNQ",  "label": "REITs"},
    "PDBC": {"proxy": "DBC",  "label": "大宗商品"},
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
US_ROT_ABS_THRESHOLD = 0.0   # 绝对动量阈值: >0即可(与Sub-A一致)
US_ROT_BTC_TICKER = "BTC-USD"
US_ROT_BTC_START = pd.Timestamp("2022-01-01")  # BTC参与轮动回测起始日
US_ROT_BTC_MAX_W = 0.30                         # BTC最大持仓占比(30%), 凌驾于其他条件
# EMXC (新兴市场除中国) launched 2017-07-26. Before that, use EEM (含中国) as backtest proxy.
US_ROT_EMXC_BT_START = pd.Timestamp("2017-08-01")  # 首个完整月份
US_ROT_EMXC_BT_PROXY = "EEM"                        # 2017-08前的回测proxy

# --- Sub-C: US Production Portfolio (7ETF, Buy & Hold + Annual Rebalance) ---
PROD_USE_TIMING = False     # V9: 关闭择时(AbsMom+SMA)，纯买入持有+年度再平衡
PROD_ABS_MOM_LB = 6         # (仅在 PROD_USE_TIMING=True 时生效)
PROD_SMA_WINDOW = 12        # (仅在 PROD_USE_TIMING=True 时生效)
PROD_SMA_BAND = 0.03        # (仅在 PROD_USE_TIMING=True 时生效)
PROD_BLEND_A = 0.5          # (仅在 PROD_USE_TIMING=True 时生效)
PROD_COMMISSION = 0.001     # 单边千分之一
PROD_REBAL_MONTH = 12
PROD_CASH = "BIL"
PROD_PORTFOLIO = {
    "VTI":   {"w": 0.30, "label": "US Total Market",     "proxy": "VTI",     "cls": "equity"},
    "QQQM":  {"w": 0.10, "label": "US Nasdaq 100",       "proxy": "QQQ",     "cls": "equity"},
    "VEA":   {"w": 0.20, "label": "Intl Developed",      "proxy": "VEA",     "cls": "equity"},
    "VGIT":  {"w": 0.15, "label": "US Interm Treasury",  "proxy": "VGIT",    "cls": "bond"},
    "DBMF":  {"w": 0.05, "label": "Managed Futures",     "proxy": "DBMF",    "cls": "alt"},
    "GLDM":  {"w": 0.15, "label": "Gold",                "proxy": "GLD",     "cls": "commodity"},
    "IBIT":  {"w": 0.05, "label": "Bitcoin",             "proxy": "BTC-USD", "cls": "crypto"},
}

# --- Sub-C: BTC phased backtest ---
# BTC only participates in backtest from 2022 onwards (avoid pre-2022 extreme returns inflating metrics).
# Live signals always include BTC.
BTC_BT_START = pd.Timestamp("2022-01-01")

# Pre-2022 backtest portfolio: no BTC, weights rescaled to sum to 100%
PROD_PORTFOLIO_BT = {}
_bt_remaining = sum(c["w"] for _n, c in PROD_PORTFOLIO.items() if _n != "IBIT")
for _n, _c in PROD_PORTFOLIO.items():
    if _n == "IBIT":
        continue
    PROD_PORTFOLIO_BT[_n] = {**_c, "w": _c["w"] / _bt_remaining}

# --- Sub-C: DBMF phased backtest ---
# DBMF (管理型期货) launched 2019-05-08. Before that, substitute with VGIT (国债).
DBMF_BT_START = pd.Timestamp("2019-06-01")  # 首个完整月份

# Pre-DBMF portfolio: no BTC, no DBMF; DBMF weight → VGIT (国债替代管理期货)
PROD_PORTFOLIO_PRE_DBMF = {}
_dbmf_w = PROD_PORTFOLIO["DBMF"]["w"]
_pre_dbmf_rest = sum(c["w"] for _n, c in PROD_PORTFOLIO.items() if _n not in ("IBIT", "DBMF"))
for _n, _c in PROD_PORTFOLIO.items():
    if _n in ("IBIT", "DBMF"):
        continue
    _w = _c["w"] + (_dbmf_w if _n == "VGIT" else 0)
    PROD_PORTFOLIO_PRE_DBMF[_n] = {**_c, "w": _w / (_pre_dbmf_rest + _dbmf_w)}

US_ALL_TICKERS = sorted(set(
    US_ROT_POOL + ["BIL", US_ROT_EMXC_BT_PROXY] +
    [c["proxy"] for c in PROD_PORTFOLIO.values()]
))

# --- Combined weights ---
COMBINED_WEIGHTS = {"Sub-A": 0.15, "Sub-A-DK": 0.15, "Sub-B": 0.40, "Sub-C": 0.30}

# --- V4 upgrade parameters ---
CN_COOLDOWN_DAYS = 3       # Sub-A: 冷却期(交易日)
CN_MA_WINDOW = 120         # Sub-A: HS300均线窗口
CN_DK_COOLDOWN_DAYS = 5    # Sub-A-DK: 冷却期(交易日)

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
           f"&klt=101&fqt=1&beg=20050101&end={end_date}&lmt=10000")  # fqt=1 前复权(避免ETF分红除息跳空影响动量)
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
    """Fetch from csindex.com.cn — works for CSI index codes like H30269."""
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
        if ac is None:
            ac = c  # 盘中adjclose可能为null，降级使用close
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
# 执行模型说明 (Execution Model):
# A股采用"收盘价决策+收盘价执行"模式，即：
#   1. 收盘前约1小时(14:00后)根据实时价格判断信号
#   2. 通过收盘集合竞价(14:57-15:00)以收盘价执行交易
# 因此信号使用当日收盘价 momentum.iloc[i] 是正确的，无需shift(1)。
# 这与Sub-B/C的"信号日次日执行"模式不同，是A股特有的可行执行方式。
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
                    cooldown_days=CN_COOLDOWN_DAYS, ma_window=CN_MA_WINDOW):
    """Sub-A V4: 双动量做多 + 每日检查 + 冷却期 + HS300 MA120过滤.

    V4变更:
    - 每个交易日检查信号(替代固定周四)
    - cooldown_days: 换仓后至少等N个交易日才能再次换仓
    - ma_window: HS300 < MA则强制现金(熊市保护)
    - target_vol: 可选波动率缩放(Sub-A不用, 保留接口兼容性)
    """
    momentum = close_df.div(close_df.shift(CN_LOOKBACK)).sub(1)
    abs_momentum = close_df.div(close_df.shift(CN_ABS_MOM_LB)).sub(1)
    vol_rank = close_df.pct_change().rolling(CN_VOL_RANK_LB).std() * np.sqrt(CN_TRADING_DAYS)
    daily_ret_df = close_df.pct_change() if target_vol is not None else None

    # MA过滤器: HS300低于均线时强制现金 (ma_window=None 表示不使用)
    hs300_col = "1.000300"
    if ma_window is not None:
        ma = close_df.rolling(ma_window).mean()
        market_above_ma = close_df[hs300_col] > ma[hs300_col]
    else:
        market_above_ma = pd.Series(True, index=close_df.index)  # 永远在均线上方 = 不过滤

    start_idx = max(CN_LOOKBACK, CN_ABS_MOM_LB, CN_VOL_RANK_LB, ma_window or 0)
    if target_vol is not None:
        start_idx = max(start_idx, vol_window)
    holding = "cash"
    rows = []
    last_trade_day = -999  # 冷却期追踪

    for i in range(start_idx, len(close_df)):
        date = close_df.index[i]

        # ---- 每日计算理想标的 ----
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

        # ---- MA120 过滤: 大盘低于均线 → 强制现金 ----
        if ideal != "cash" and not market_above_ma.iloc[i]:
            ideal = "cash"

        # ---- 冷却期判断: 只有理想标的≠当前持仓 且 冷却期已过 才换仓 ----
        target = None
        days_since_trade = i - last_trade_day
        if ideal != holding and days_since_trade >= cooldown_days:
            target = ideal
            last_trade_day = i

        # --- Vol scaling weight (for current holding, before any transition) ---
        weight = 1.0
        if target_vol is not None and holding != "cash":
            recent = daily_ret_df[holding].iloc[max(0, i - vol_window):i].dropna()
            if len(recent) >= 10:
                rv = recent.std() * np.sqrt(CN_TRADING_DAYS)
                weight = min(target_vol / rv, max_lev) if rv > 0.001 else max_lev
        elif holding == "cash":
            weight = 0.0

        # --- Return calculation ---
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
    """A-DK信号日: 每周五(dayofweek=4), 若周五非交易日则取该周最后一个交易日."""
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
                    commission=CN_COMMISSION, cooldown_days=CN_DK_COOLDOWN_DAYS):
    """Sub-A-DK V4: 中证1000/上证50 多空策略 + 每日检查 + 冷却期.

    V4变更:
    - 每日检查方向信号(替代固定周五)
    - cooldown_days: 方向翻转后至少等N个交易日才能再次翻转
    - 杠杆缩放(risk scaling)保持日频, 不受冷却期约束(专家条件5)

    比较20日绝对动量，做多动量高的，做空另一个。永远满仓(一多一空)。
    signal.shift(1): 信号决策后，下一个交易日开始生效。
    波动率缩放: scale = target_vol/realized_vol, clip(min_lev, max_lev),
               scale.shift(1)延迟一天生效。
    """
    zz1000_col, sz50_col = CN_DK_COLS
    # a=上证50, b=中证1000 (与原始脚本一致: spread_ret = a_ret - b_ret)
    a_col, b_col = sz50_col, zz1000_col

    # ---- 数据对齐 ----
    d = pd.DataFrame({'a': close_df[a_col], 'b': close_df[b_col]}).dropna()
    d['a_ret'] = d['a'].pct_change()
    d['b_ret'] = d['b'].pct_change()
    d['a_mom'] = d['a'].pct_change(CN_DK_MOM_LB)
    d['b_mom'] = d['b'].pct_change(CN_DK_MOM_LB)
    d['spread_ret'] = d['a_ret'] - d['b_ret']
    d = d.dropna(subset=['a_ret', 'b_ret'])

    # ---- V4: 每日理想信号 + 冷却期 ----
    n = len(d)
    start_idx = max(CN_DK_MOM_LB, vol_window) + 1

    # 每天计算理想方向
    d['daily_signal'] = np.nan
    both_valid = d['a_mom'].notna() & d['b_mom'].notna()
    d.loc[both_valid, 'daily_signal'] = np.where(
        d.loc[both_valid, 'a_mom'] > d.loc[both_valid, 'b_mom'], 1, -1
    )

    # 冷却期逻辑: 方向翻转需满足冷却期, 杠杆缩放不受限
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
            # 首次建仓
            current_signal = ds
            last_trade_idx = i
            is_signal_list[i] = True
        elif ds != current_signal and (i - last_trade_idx) >= cooldown_days:
            # 方向翻转 + 冷却期已满
            current_signal = ds
            last_trade_idx = i
            is_signal_list[i] = True

        signal_list[i] = current_signal

    d['signal'] = signal_list
    d['signal'] = d['signal'].astype(float)
    d['is_signal'] = is_signal_list

    # position = signal.shift(1) — 信号决策后, 下一日生效
    d['position'] = d['signal'].shift(1)
    d['raw_ret'] = d['position'] * d['spread_ret']
    d = d.dropna(subset=['position', 'raw_ret'])

    # ---- 波动率缩放: 日频, 不受冷却期约束 ----
    if target_vol is not None:
        d['realized_vol'] = d['raw_ret'].rolling(vol_window).std() * np.sqrt(CN_DK_TRADING_DAYS)
        d['scale'] = (target_vol / d['realized_vol']).clip(min_lev, max_lev)
        d['scale'] = d['scale'].shift(1)  # scale延迟一天生效
        d['strategy_ret'] = d['raw_ret'] * d['scale']
        d = d.dropna(subset=['strategy_ret'])
    else:
        d['strategy_ret'] = d['raw_ret']
        d['scale'] = 1.0

    # ---- 交易成本 — 基于 position 变化 ----
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

    # ---- 构造输出DataFrame ----
    d['holding'] = np.where(d['signal'] == 1, a_col, b_col)
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
    }, index=d.index)
    result['nav'] = (1 + result['return']).cumprod()
    return result


# ================================================================
# SUB-B: US 9ETF Rotation Engine
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

def _apply_btc_cap(act, btc_ticker, max_w):
    """BTC持仓上限: 超出部分归入BIL现金。凌驾于其他条件之上。"""
    if btc_ticker not in act or act[btc_ticker] <= max_w:
        return act
    act = dict(act)
    excess = act[btc_ticker] - max_w
    act[btc_ticker] = max_w
    act["BIL"] = act.get("BIL", 0.0) + excess
    return act

def run_us_rotation(close_df, ranking_codes, top_n=3, abs_threshold=US_ROT_ABS_THRESHOLD,
                    min_turnover=US_ROT_MIN_TURNOVER,
                    btc_ticker=None, btc_start=None, btc_max_w=None):
    # V10: BTC分阶段 — 2022前屏蔽BTC数据，自动排除出排名池
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
            raw_w = _us_raw_weights(
                momentum.iloc[i], vol_df.iloc[i], ranking_codes, top_n, abs_threshold)
            new_act = _us_model_b(raw_w, scale)
            # V10: BTC持仓上限
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
        # 当日收益使用旧权重 (old_act): 持有旧仓位一整天, 收盘后才换仓
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


# ================================================================
# SUB-C: US Production Portfolio Engine (AbsMom-6m + SMA-12m blend)
# ================================================================
def make_abs_mom_signals(monthly_prices, lookback=6):
    ret_n = monthly_prices / monthly_prices.shift(lookback) - 1
    raw = (ret_n > 0).astype(float)
    return raw.shift(1)

def _sma_raw_signals(monthly_prices, window=12, band=0.0):
    """Compute raw SMA signal with hysteresis band (before shift).
    band=0: 简单比较 price > SMA
    band>0: 上穿 SMA*(1+band) → 持有(1), 下穿 SMA*(1-band) → 现金(0), 带内维持"""
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
    """SMA信号+过滤带: 上穿SMA*(1+band)→持有, 下穿SMA*(1-band)→现金, 带内维持。shift(1)防前瞻"""
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

    # Track previous signals for cost calculation
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

            # Signal change cost for pool A
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

                # Signal change cost for pool B
                if commission > 0 and t in prev_sig_b and sb != prev_sig_b[t]:
                    cost = pos_b[t] * commission
                    pos_b[t] -= cost
                    month_cost += cost
                prev_sig_b[t] = sb

                pos_b[t] *= (1 + (r_asset if sb == 1.0 else r_cash))
                month_detail[f"sig_sma_{t}"] = sb
                month_detail[f"sig_{t}"] = blend_a * sa + blend_b * sb  # blended hold ratio
            else:
                month_detail[f"sig_{t}"] = sa

        current_val = sum(pos_a.values()) + (sum(pos_b.values()) if use_blend else 0)
        vals.append(current_val)
        month_detail["cost"] = month_cost
        details.append(month_detail)

        if dt.month == rebal_month:
            # Rebalance cost: turnover from drift back to target weights
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
    Phase 0: Before DBMF_BT_START — PROD_PORTFOLIO_PRE_DBMF (no BTC, no DBMF → VGIT替代)
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

def _is_edt(d):
    """Return True if date d is in US Eastern Daylight Time (EDT).
    Uses zoneinfo for accurate DST boundary (3月第二个周日, 11月第一个周日)."""
    if hasattr(d, 'date'):
        d = d.date()
    et = datetime(d.year, d.month, d.day, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    return et.utcoffset() == timedelta(hours=-4)

def is_us_market_open():
    """Check if US market is currently in trading hours (9:30-16:00 ET).
    Returns (is_open, bj_now) tuple."""
    bj = beijing_now()
    # Weekend check: US market closed Sat-Sun.
    # In Beijing time, US Mon-Fri sessions span midnight, so:
    # - Sat 05:00+ to Mon 21:30 Beijing time → closed
    weekday = bj.weekday()  # 0=Mon ... 6=Sun
    if weekday == 5 and bj.hour >= 5:   # Saturday after US close
        return False, bj
    if weekday == 6:                      # Sunday all day
        return False, bj
    if weekday == 0 and bj.hour < 21:    # Monday before US open
        return False, bj
    # US market in Beijing time:
    # EST (Nov-Mar): 22:30 - next day 05:00
    # EDT (Mar-Nov): 21:30 - next day 04:00
    edt = _is_edt(bj)
    if edt:
        open_h, open_m, close_h = 21, 30, 4
    else:  # EST
        open_h, open_m, close_h = 22, 30, 5
    hour = bj.hour
    # US trading spans midnight Beijing time
    if hour >= open_h or hour < close_h:
        return True, bj
    return False, bj

def beijing_time_str(date, market="CN", event="close"):
    """Convert trading date to Beijing time string.
    event='close' → market close time; event='open' → market open time."""
    if market == "CN":
        if event == "open":
            return f"{date.strftime('%Y-%m-%d')} 09:30 北京时间"
        return f"{date.strftime('%Y-%m-%d')} 15:00 北京时间"
    else:
        edt = _is_edt(date)
        if event == "open":
            # US open 9:30am ET → Beijing same day 21:30 (EDT) or 22:30 (EST)
            bj_hour = "21:30" if edt else "22:30"
            return f"{date.strftime('%Y-%m-%d')} {bj_hour} 北京时间"
        else:
            # US close 4pm ET → Beijing next day 04:00 (EDT) or 05:00 (EST)
            bj_hour = "04:00" if edt else "05:00"
            next_day = date + timedelta(days=1)
            return f"{next_day.strftime('%Y-%m-%d')} {bj_hour} 北京时间"

def _next_biz_day(date):
    """Next business day after date (skip weekends)."""
    d = date + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d

def us_exec_time_str(signal_date):
    """信号日 → 次日开盘的北京时间 (实际执行时间)"""
    exec_day = _next_biz_day(signal_date)
    return beijing_time_str(exec_day, "US", "open")

def _has_execution_happened(signal_date, market, bj_now):
    """Check if the execution (next biz day open) for a signal has happened.
    Returns True if the execution time has passed."""
    exec_day = _next_biz_day(signal_date)
    exec_day_date = exec_day.date() if hasattr(exec_day, 'date') else exec_day
    today_date = bj_now.date()
    if today_date > exec_day_date:
        return True
    elif today_date == exec_day_date:
        if market == "CN":
            # CN opens 09:30 Beijing time
            return bj_now.hour > 9 or (bj_now.hour == 9 and bj_now.minute >= 35)
        else:
            # US opens 21:30 (EDT) or 22:30 (EST) Beijing time
            open_h = 21 if _is_edt(exec_day) else 22
            return bj_now.hour > open_h or (bj_now.hour == open_h and bj_now.minute >= 35)
    return False

def _mark_tentative_records(records):
    """Mark rebalance records from current incomplete week as hypothetical (假定).
    Weekly strategies (Sub-A/Sub-B) fire on the last Mon-Thu of each week,
    but we can't confirm until Thu. Records on Mon-Wed of the current week are tentative."""
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
    """Parse Chinese or Arabic number string."""
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    # 十二 → 12, 二十 → 20, etc.
    if '十' in s:
        parts = s.split('十')
        tens = _CN_NUM.get(parts[0], 1) if parts[0] else 1
        ones = _CN_NUM.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    return None

def parse_date_range(text):
    """Parse date range from Chinese natural language text.
    Returns (start: Timestamp, end: Timestamp) or (None, None).

    Supported patterns:
      - 2024-01到2025-01 / 2024年1月到2025年6月 (full range)
      - 2024年1月到6月 / 2024-01到06 (same year)
      - 202401-202602 / 202401到202602 (compact YYYYMM)
      - 2024到2025 / 2024年到2025年 (year-to-year)
      - 2024至今 / 2024年至今 / 2024-01至今 (year/month to now)
      - 最近N个月 / 最近N年 / 过去N年 / 近N个月
      - 今年 / 去年 / 前年
      - 2024年 / 2024年全年 (single year)
      - 2026年2月 / 2026-02 (single month)
    """
    now = pd.Timestamp.now()

    # ---- "至今" patterns: YYYY至今 / YYYY年至今 / YYYY-MM至今 / YYYY年M月至今 ----
    m = re.search(r'(\d{4})[-年/.]?(\d{1,2})[-月]?\s*至今', text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-01")
        return start, now
    m = re.search(r'(\d{4})\s*年?\s*至今', text)
    if m:
        return pd.Timestamp(f"{m.group(1)}-01-01"), now

    # ---- Full range: YYYY-MM到YYYY-MM / 2024年1月到2025年6月 ----
    m = re.search(r'(\d{4})[-年/.](\d{1,2})[-月]?\s*[到至—\-~]+\s*(\d{4})[-年/.](\d{1,2})', text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-01")
        end = pd.Timestamp(f"{m.group(3)}-{int(m.group(4)):02d}-01") + pd.offsets.MonthEnd(0)
        return start, end

    # ---- Same year: 2024年1月到6月 / 2024-01到06 ----
    m = re.search(r'(\d{4})[-年/.](\d{1,2})[-月]?\s*[到至—\-~]+\s*(\d{1,2})', text)
    if m:
        yr = int(m.group(1))
        start = pd.Timestamp(f"{yr}-{int(m.group(2)):02d}-01")
        end = pd.Timestamp(f"{yr}-{int(m.group(3)):02d}-01") + pd.offsets.MonthEnd(0)
        return start, end

    # ---- Compact YYYYMM-YYYYMM / YYYYMM到YYYYMM ----
    m = re.search(r'(\d{4})(\d{2})\s*[-到至~]+\s*(\d{4})(\d{2})', text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{m.group(2)}-01")
        end = pd.Timestamp(f"{m.group(3)}-{m.group(4)}-01") + pd.offsets.MonthEnd(0)
        return start, end

    # ---- Year-to-year: 2024到2025 / 2024年到2025年 / 2024-2026 ----
    m = re.search(r'(\d{4})\s*年?\s*[到至—\-~]+\s*(\d{4})\s*年?', text)
    if m:
        return pd.Timestamp(f"{m.group(1)}-01-01"), pd.Timestamp(f"{m.group(2)}-12-31")

    # ---- 最近/过去/近 N 个?月/年 (Chinese or Arabic numbers) ----
    m = re.search(r'(?:最近|过去|近)\s*([一二两三四五六七八九十\d半]+)\s*个?\s*年', text)
    if m:
        n = _parse_cn_num(m.group(1))
        if n is not None:
            if isinstance(n, float):  # 半年
                return now - pd.DateOffset(months=int(n * 12)), now
            return now - pd.DateOffset(years=int(n)), now
    m = re.search(r'(?:最近|过去|近)\s*([一二两三四五六七八九十\d半]+)\s*个?\s*月', text)
    if m:
        n = _parse_cn_num(m.group(1))
        if n is not None:
            return now - pd.DateOffset(months=int(n if n >= 1 else 1)), now

    # ---- 今年 / 去年 / 前年 ----
    if '今年' in text:
        return pd.Timestamp(f"{now.year}-01-01"), now
    if '去年' in text:
        yr = now.year - 1
        return pd.Timestamp(f"{yr}-01-01"), pd.Timestamp(f"{yr}-12-31")
    if '前年' in text:
        yr = now.year - 2
        return pd.Timestamp(f"{yr}-01-01"), pd.Timestamp(f"{yr}-12-31")

    # ---- Single month: 2026年2月 / 2026-02 (before year-only) ----
    m = re.search(r'(\d{4})[-年/.](\d{1,2})\s*月?份?', text)
    if m:
        yr = int(m.group(1))
        mon = int(m.group(2))
        if 1 <= mon <= 12:
            start = pd.Timestamp(f"{yr}-{mon:02d}-01")
            end = start + pd.offsets.MonthEnd(0)
            return start, end

    # ---- Single year: 2024年 / 2024年全年 / bare 2024 ----
    m = re.search(r'(\d{4})\s*年?\s*全?年?', text)
    if m:
        yr = int(m.group(1))
        if 2000 <= yr <= 2099:
            return pd.Timestamp(f"{yr}-01-01"), pd.Timestamp(f"{yr}-12-31")

    return None, None


def parse_all_date_ranges(text):
    """Parse one or more date ranges from Chinese text.

    Handles queries like "近1年以及近4年的表现" by splitting on common
    conjunctions (以及 / 和 / 、 / ;) and parsing each part independently.
    Returns a list of (start, end) tuples sorted by period length (short first).
    """
    # Split on common Chinese conjunctions between date expressions
    parts = re.split(r'以及|、|；|;\s*', text)
    # Also try splitting on "和" only if it sits between two date-like segments
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

    # Fallback: if splitting produced nothing, try original text as single range
    if not results:
        start, end = parse_date_range(text)
        if start is not None:
            results.append((start, end))

    # Sort by period length (shorter first)
    results.sort(key=lambda x: (x[1] - x[0]).days)
    return results


def extract_cn_rebalances(cn_result, cn_close, strategy_name="Sub-A", names=None):
    """Extract CN rebalancing records with Beijing time. Works for Sub-A and Sub-A-DK."""
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
    """Extract A-DK (long-short) rebalancing records: direction flips."""
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
    """Extract Sub-C signal change records (supports blend: sig_am_X + sig_sma_X columns)."""
    records = []
    # Use blended sig_ columns for detecting overall changes
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
                    # Describe blend change
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

    # Build lookup: month_period -> signal row
    sig_a_lookup = {}
    for sig_dt in prod_sig_a.index:
        sig_a_lookup[sig_dt.to_period("M")] = prod_sig_a.loc[sig_dt]

    sig_b_lookup = {}
    if use_blend:
        for sig_dt in prod_sig_b.index:
            sig_b_lookup[sig_dt.to_period("M")] = prod_sig_b.loc[sig_dt]

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

        # Build daily AbsMom signal
        daily_sig_a = pd.Series(np.nan, index=daily_ret.index)
        for period, mask in period_masks.items():
            if period in sig_a_lookup and proxy in sig_a_lookup[period].index:
                sv = sig_a_lookup[period][proxy]
                daily_sig_a[mask] = 0.0 if pd.isna(sv) else sv
        daily_sig_a = daily_sig_a.ffill().fillna(0)

        if use_blend:
            # Build daily SMA signal
            daily_sig_b = pd.Series(np.nan, index=daily_ret.index)
            for period, mask in period_masks.items():
                if period in sig_b_lookup and proxy in sig_b_lookup[period].index:
                    sv = sig_b_lookup[period][proxy]
                    daily_sig_b[mask] = 0.0 if pd.isna(sv) else sv
            daily_sig_b = daily_sig_b.ffill().fillna(0)

            # Blend: each half independently
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

        # Sheet 2: Monthly Returns
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
class CombinedStrategyV4:

    def run(self):
        query = poe.query.text.strip()
        if "净值曲线" in query:
            self._handle_nav_chart(query)
        elif "表现" in query:
            ranges = parse_all_date_ranges(query)
            if len(ranges) <= 1:
                self._handle_performance(query)
            else:
                for r in ranges:
                    self._handle_performance(query, _forced_range=r)
        elif "实时信号" in query:
            self._handle_live_signal()
        elif "实时参数" in query:
            self._handle_live_params()
        elif "参数" in query:
            self._handle_params()
        elif "信号" in query:
            self._handle_signal()
        else:
            self._handle_signal()

    # ----------------------------------------------------------
    # Common: fetch all data
    # ----------------------------------------------------------
    def _fetch_data(self, msg):
        msg.write("⏳ 正在获取A股数据...\n")
        cn_raw, cn_sources = {}, {}
        for secid in CN_STOCK_CODES:
            df, source = fetch_cn_kline(secid)
            cn_raw[secid] = df
            cn_sources[secid] = source
            time.sleep(0.5)

        # Hybrid ZZHL: fetch index data for longer history, splice with ETF
        # EastMoney/Sina often fail for H30269, so try csindex.com.cn as fallback
        try:
            zzhl_idx_df, zzhl_idx_src = None, None
            # Try EastMoney + Sina first
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
                except Exception:
                    time.sleep(0.5)

            if zzhl_idx_df is None:
                raise ValueError("所有数据源均失败")

            # Use index data before ETF start, ETF data after
            zzhl_etf_df = cn_raw[CN_ZZHL_ETF_SECID]
            zzhl_before = zzhl_idx_df[zzhl_idx_df.index < CN_ZZHL_ETF_START]
            zzhl_after = zzhl_etf_df[zzhl_etf_df.index >= CN_ZZHL_ETF_START]
            # Splice: scale index to match ETF at transition point
            if len(zzhl_before) > 0 and len(zzhl_after) > 0:
                idx_last = zzhl_before["close"].iloc[-1]
                etf_first = zzhl_after["close"].iloc[0]
                scale = etf_first / idx_last
                zzhl_before = zzhl_before.copy()
                zzhl_before["close"] = zzhl_before["close"] * scale
                cn_raw[CN_ZZHL_ETF_SECID] = pd.concat([zzhl_before, zzhl_after])
                msg.write(f"  ZZHL混合: 指数{zzhl_idx_df.index[0].strftime('%Y-%m-%d')}~{CN_ZZHL_ETF_START.strftime('%Y-%m-%d')}"
                         f" + ETF{CN_ZZHL_ETF_START.strftime('%Y-%m-%d')}~ [{zzhl_idx_src}+ETF]\n")
        except Exception as e:
            msg.write(f"  ⚠️ ZZHL指数获取失败({e})，仅用ETF数据\n")

        # Hybrid CYB: fetch 创业板指数 for longer history, splice with ETF
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
        except Exception as e:
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

        # Sub-B rotation close: exclude late-launching tickers from initial concat
        # so their late start dates don't truncate the entire dataset via dropna().
        # BTC-USD (~2014 on Yahoo) would otherwise cut off 2007-2014 data.
        # EMXC (2017-07) uses EEM as backtest proxy before US_ROT_EMXC_BT_START.
        # The engine handles BTC NaN via btc_ticker/btc_start params.
        rot_tickers = US_ROT_POOL + ["BIL"]
        _late_rot = {"BTC-USD", "EMXC"}
        rot_tickers_core = [t for t in rot_tickers if t not in _late_rot]
        # If EMXC is in the pool, ensure EEM is in core for early backtest period
        if "EMXC" in US_ROT_POOL and US_ROT_EMXC_BT_PROXY not in rot_tickers_core:
            if US_ROT_EMXC_BT_PROXY in us_raw:
                rot_tickers_core.append(US_ROT_EMXC_BT_PROXY)
        us_rot_close = pd.concat(
            [us_raw[t][["close"]].rename(columns={"close": t})
             for t in rot_tickers_core if t in us_raw],
            axis=1).ffill().dropna()
        # Build hybrid EMXC column: EEM before EMXC_BT_START, EMXC after
        if "EMXC" in US_ROT_POOL and US_ROT_EMXC_BT_PROXY in us_raw:
            eem_col = us_rot_close[US_ROT_EMXC_BT_PROXY].copy() if US_ROT_EMXC_BT_PROXY in us_rot_close.columns else None
            emxc_raw = us_raw.get("EMXC")
            if eem_col is not None:
                hybrid = eem_col.rename("EMXC")
                if emxc_raw is not None and len(emxc_raw) > 0:
                    emxc_ser = emxc_raw["close"].reindex(hybrid.index)
                    # Splice: use EMXC from its BT start, scale to match EEM level at switchover
                    switch_idx = hybrid.index >= US_ROT_EMXC_BT_START
                    if switch_idx.any() and emxc_ser.loc[switch_idx].first_valid_index() is not None:
                        first_emxc_date = emxc_ser.loc[switch_idx].first_valid_index()
                        scale_factor = hybrid.loc[first_emxc_date] / emxc_ser.loc[first_emxc_date]
                        hybrid.loc[switch_idx] = emxc_ser.loc[switch_idx] * scale_factor
                us_rot_close["EMXC"] = hybrid
                # Remove EEM column (only needed to build hybrid EMXC)
                if US_ROT_EMXC_BT_PROXY in us_rot_close.columns and US_ROT_EMXC_BT_PROXY not in US_ROT_POOL:
                    us_rot_close = us_rot_close.drop(columns=[US_ROT_EMXC_BT_PROXY])
        for t in _late_rot:
            if t == "EMXC":
                continue  # Already handled above via hybrid
            if t in us_raw:
                us_rot_close = us_rot_close.join(
                    us_raw[t][["close"]].rename(columns={"close": t}), how="left")

        # Sub-C production daily: exclude late-launching tickers similarly.
        # DBMF (2019-05) and BTC-USD would otherwise truncate to 2019.
        # BTC is handled by simulate_prod_btc_phased; DBMF NaN → 0% return (5% weight, minor drag).
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

        # ---- Build A-DK close data: 中证1000 + 上证50 for long-short strategy ----
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
                    except Exception:
                        time.sleep(0.5)
                if idx_df is None:
                    raise ValueError(f"A-DK {col_name} 数据源均失败")
                dk_dfs[col_name] = idx_df.rename(columns={"close": col_name})
                msg.write(f"  {CN_DK_NAMES[col_name]}: {idx_df.index[0].strftime('%Y-%m-%d')}~{idx_df.index[-1].strftime('%Y-%m-%d')} [{src}]\n")
                time.sleep(0.5)

            cn_dk_close = pd.concat([dk_dfs[c] for c in CN_DK_COLS], axis=1).ffill().dropna()
            msg.write(f"  A-DK合并截至: {cn_dk_close.index[-1].strftime('%Y-%m-%d')}\n")
        except Exception as e:
            raise poe.BotError(f"A-DK多空数据获取失败: {e}")

        return cn_close, cn_dk_close, us_rot_close, us_prod_daily

    # ----------------------------------------------------------
    # Common: run all strategies
    # ----------------------------------------------------------
    def _run_strategies(self, cn_close, cn_dk_close, us_rot_close, us_prod_daily):
        cn_result = run_cn_strategy(cn_close, CN_STOCK_CODES)
        cn_dk_result = run_dk_strategy(cn_dk_close,
                                       target_vol=CN_DK_TARGET_VOL,
                                       vol_window=CN_DK_VOL_WINDOW,
                                       max_lev=CN_DK_MAX_LEV,
                                       min_lev=CN_DK_MIN_LEV)
        us_rot_result = run_us_rotation(
            us_rot_close, US_ROT_POOL,
            btc_ticker=US_ROT_BTC_TICKER, btc_start=US_ROT_BTC_START, btc_max_w=US_ROT_BTC_MAX_W)

        prod_monthly = us_prod_daily.resample("M").last()
        _last_daily = us_prod_daily.index[-1]
        _last_monthly_period = prod_monthly.index[-1].to_period("M")
        # 如果最后数据日在当前月(月未结束), 截掉不完整月
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

    # ----------------------------------------------------------
    # Signal computation (shared by 信号 and 实时信号)
    # ----------------------------------------------------------
    def _compute_signal_data(self, cn_close, cn_dk_close, us_rot_close, us_prod_daily):
        """Compute all signal data for Sub-A, Sub-A-DK, Sub-B, Sub-C. Returns a dict."""
        cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details = \
            self._run_strategies(cn_close, cn_dk_close, us_rot_close, us_prod_daily)

        # --- Sub-A signal info (V4: 日频检查 + 冷却期 + MA120) ---
        cn_date = cn_close.index[-1]
        cn_current = cn_result["holding"].iloc[-1]

        # V4: 找最后一次实际换仓日, 计算冷却期剩余天数
        cn_trade_days = cn_result[cn_result["is_signal"] == True]
        if len(cn_trade_days) > 0:
            last_cn_trade_date = cn_trade_days.index[-1]
            cn_days_since = len(cn_result.loc[last_cn_trade_date:]) - 1
            cn_cooldown_remaining = max(0, CN_COOLDOWN_DAYS - cn_days_since)
        else:
            cn_cooldown_remaining = 0

        # MA120 状态
        ma_cn = cn_close.rolling(CN_MA_WINDOW).mean()
        hs300_col = "1.000300"
        cn_ma_above = bool(cn_close[hs300_col].iloc[-1] > ma_cn[hs300_col].iloc[-1])

        # V4: 每日都检查信号, is_cn_signal 表示"今天是否触发了换仓"
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
        # MA120 过滤: 如果大盘低于均线, 理想标的强制为现金
        if hypo_cn != "cash" and not cn_ma_above:
            hypo_cn = "cash"

        # --- Sub-B signal info ---
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

        # Compute hypothetical/actual weights for Sub-B
        prev_us_w = None
        rebalanced_b = None
        hypo_us_w = None
        would_rebalance = None
        turnover_b = 0.0
        if is_us_signal:
            # 直接使用引擎的调仓判定(与回测一致, 阈值=US_ROT_MIN_TURNOVER)
            rebalanced_b = bool(us_rot_result.iloc[-1].get("rebalanced", False))
            # 前一交易日权重(用于展示变动)
            rloc = len(us_rot_result) - 1
            prev_us_w = {}
            if rloc > 0:
                prev_us_w = {c.replace("w_", ""): us_rot_result.iloc[rloc - 1][c] for c in rot_w_cols}
            if not prev_us_w:
                prev_us_w = {"BIL": 1.0}
            hypo_us_w = current_us_w
            all_a = set(list(current_us_w.keys()) + list(prev_us_w.keys()))
            turnover_b = sum(abs(current_us_w.get(a, 0) - prev_us_w.get(a, 0)) for a in all_a if a != "BIL")
        else:
            momentum_us = us_rot_close.div(us_rot_close.shift(US_ROT_LB)).sub(1)
            vol_df = us_rot_close.pct_change().rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
            raw_w = _us_raw_weights(momentum_us.iloc[-1], vol_df.iloc[-1], US_ROT_POOL, 3, US_ROT_ABS_THRESHOLD)
            hypo_us_w = _us_model_b(raw_w, us_scale)
            if US_ROT_BTC_MAX_W is not None:
                hypo_us_w = _apply_btc_cap(hypo_us_w, US_ROT_BTC_TICKER, US_ROT_BTC_MAX_W)
            all_a = set(list(hypo_us_w.keys()) + list(current_us_w.keys()))
            turnover_b = sum(abs(hypo_us_w.get(a, 0) - current_us_w.get(a, 0)) for a in all_a if a != "BIL")
            would_rebalance = turnover_b >= US_ROT_MIN_TURNOVER

        # --- Sub-A-DK signal info (V4: 日频检查 + 冷却期) ---
        dk_date = cn_dk_close.index[-1]
        dk_current = cn_dk_result["holding"].iloc[-1]

        # V4: 找最后一次方向翻转日, 计算冷却期剩余
        dk_trade_days = cn_dk_result[cn_dk_result["is_signal"] == True]
        if len(dk_trade_days) > 0:
            last_dk_trade_date = dk_trade_days.index[-1]
            dk_days_since = len(cn_dk_result.loc[last_dk_trade_date:]) - 1
            dk_cooldown_remaining = max(0, CN_DK_COOLDOWN_DAYS - dk_days_since)
        else:
            dk_cooldown_remaining = 0

        # V4: is_dk_signal = 今天是否触发了方向翻转
        is_dk_signal = bool(cn_dk_result["is_signal"].iloc[-1]) if "is_signal" in cn_dk_result.columns else False

        # Hypothetical A-DK signal: compare 20d momentum
        dk_mom = cn_dk_close.pct_change(CN_DK_MOM_LB)
        dk_mom_latest = dk_mom.iloc[-1]
        zz1000_col, sz50_col = CN_DK_COLS
        zz1000_mom_val = dk_mom_latest.get(zz1000_col, np.nan)
        sz50_mom_val = dk_mom_latest.get(sz50_col, np.nan)
        if not np.isnan(zz1000_mom_val) and not np.isnan(sz50_mom_val):
            hypo_dk = zz1000_col if zz1000_mom_val > sz50_mom_val else sz50_col
        else:
            hypo_dk = dk_current

        # --- Sub-C signal info ---
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
        }

    # ----------------------------------------------------------
    # Sub-C output (shared by 信号 and 实时信号)
    # ----------------------------------------------------------
    def _write_sub_c(self, msg, d, us_prod_daily):
        """Write Sub-C section. Returns signal_info dict for Sub-C."""
        current_am_raw = d["current_am_raw"]
        current_sma_raw = d["current_sma_raw"]
        last_sig_month = d["last_sig_month"]

        if PROD_USE_TIMING:
            msg.write("### Sub-C: 美股7ETF生产组合 (50/50混合择时)\n")
            msg.write(f"📅 **月度信号机制**（非周度）：每月月末发出信号，次月执行。"
                     f"每个资产仓位一分为二: 50%跟AbsMom-{PROD_ABS_MOM_LB}m, "
                     f"50%跟SMA-{PROD_SMA_WINDOW}m。12月年度重平衡。\n\n")
        else:
            msg.write("### Sub-C: 美股7ETF生产组合 (无择时·纯持有)\n")
            msg.write("📅 **买入持有 + 年度再平衡**（12月），无择时信号。\n\n")

        sig_month_period = last_sig_month.to_period("M")
        sig_month_mask = us_prod_daily.index.to_period("M") == sig_month_period
        sig_month_trading = us_prod_daily.index[sig_month_mask]
        signal_issue_date = sig_month_trading[-1] if len(sig_month_trading) > 0 else last_sig_month

        next_month_period = sig_month_period + 1
        next_month_mask = us_prod_daily.index.to_period("M") == next_month_period
        next_month_trading = us_prod_daily.index[next_month_mask]
        exec_date = next_month_trading[0] if len(next_month_trading) > 0 else None

        if not PROD_USE_TIMING:
            msg.write("| 资产 | 标签 | 目标权重 | 操作 |\n")
            msg.write("|:-----|:-----|--------:|:-----|\n")
            for name, cfg in PROD_PORTFOLIO.items():
                msg.write(f"| {name} | {cfg['label']} | {cfg['w']:.0%} | 始终持有 |\n")
            msg.write(f"\n风险资产 **100%** | 年度再平衡: 每年{PROD_REBAL_MONTH}月\n")
            return {
                "is_signal": True,
                "signal_text": "全部持有(无择时)，100%风险资产",
                "note": f"年度再平衡: 每年{PROD_REBAL_MONTH}月",
            }
        else:
            msg.write(f"信号发出: **{signal_issue_date.strftime('%Y-%m-%d')}** "
                     f"({beijing_time_str(signal_issue_date, 'US')})\n")
            if exec_date is not None:
                msg.write(f"执行调仓: **{exec_date.strftime('%Y-%m-%d')}** "
                         f"({beijing_time_str(exec_date, 'US', 'open')})\n\n")
            else:
                msg.write(f"执行调仓: 次月第一个交易日（待定）\n\n")

            prev_sig_month = None
            if len(current_am_raw) >= 2:
                prev_sig_month = current_am_raw.index[-2]

            msg.write(f"| 资产 | 标签 | 权重 | AbsMom | SMA | 混合操作 | 持仓% | 变动 |\n"
                     f"|:-----|:-----|-----:|:------:|:---:|:---------|------:|:----:|\n")
            total_hold, total_cash = 0, 0
            prod_signal_parts = []
            changes_count = 0
            for name, cfg in PROD_PORTFOLIO.items():
                proxy = cfg["proxy"]
                w = cfg["w"]
                am_sv = current_am_raw.loc[last_sig_month, proxy] if proxy in current_am_raw.columns else float("nan")
                sma_sv = current_sma_raw.loc[last_sig_month, proxy] if proxy in current_sma_raw.columns else float("nan")
                prev_hold = float("nan")
                curr_hold = float("nan")
                if not pd.isna(am_sv) and not pd.isna(sma_sv):
                    curr_hold = PROD_BLEND_A * am_sv + (1 - PROD_BLEND_A) * sma_sv
                if prev_sig_month is not None:
                    prev_am = current_am_raw.loc[prev_sig_month, proxy] if proxy in current_am_raw.columns else float("nan")
                    prev_sma = current_sma_raw.loc[prev_sig_month, proxy] if proxy in current_sma_raw.columns else float("nan")
                    if not pd.isna(prev_am) and not pd.isna(prev_sma):
                        prev_hold = PROD_BLEND_A * prev_am + (1 - PROD_BLEND_A) * prev_sma
                change_str = "—"
                if not pd.isna(curr_hold) and not pd.isna(prev_hold) and abs(curr_hold - prev_hold) > 0.01:
                    change_str = "🔄"
                    changes_count += 1
                am_icon = "🟢" if am_sv == 1.0 else ("🔴" if am_sv == 0.0 else "—")
                sma_icon = "🟢" if sma_sv == 1.0 else ("🔴" if sma_sv == 0.0 else "—")
                if pd.isna(curr_hold):
                    blend_act, hold_pct = "现金(BIL)", 0.0
                elif curr_hold >= 0.99:
                    blend_act, hold_pct = f"全部持有({name})", 1.0
                    prod_signal_parts.append(name)
                elif curr_hold <= 0.01:
                    blend_act, hold_pct = "全部现金(BIL)", 0.0
                else:
                    blend_act, hold_pct = f"50%{name}+50%BIL", curr_hold
                    prod_signal_parts.append(f"{name}½")
                total_hold += w * hold_pct
                total_cash += w * (1 - hold_pct)
                msg.write(f"| {name} | {cfg['label']} | {w:.0%} | {am_icon} | {sma_icon} "
                         f"| {blend_act} | {hold_pct:.0%} | {change_str} |\n")

            msg.write(f"\n风险资产 {total_hold:.0%} | 现金 {total_cash:.0%}")
            if prev_sig_month is not None:
                msg.write(f" | 较上月({prev_sig_month.strftime('%Y-%m')})有 **{changes_count}** 项变更")
            msg.write("\n")

            return {
                "is_signal": False,
                "signal_text": f"风险{total_hold:.0%}/现金{total_cash:.0%} ({','.join(prod_signal_parts[:3])}{'...' if len(prod_signal_parts) > 3 else ''})" if prod_signal_parts else "全现金",
                "note": f"信号{signal_issue_date.strftime('%m-%d')}发出,"
                        f"{'执行' + exec_date.strftime('%m-%d') if exec_date else '待执行'}",
            }

    # ----------------------------------------------------------
    # Signal handler (confirmed close-only — "信号")
    # ----------------------------------------------------------
    def _handle_signal(self):
        with poe.start_message() as msg:
            cn_close, cn_dk_close, us_rot_close, us_prod_daily = self._fetch_data(msg)
            msg.write("⏳ 正在计算信号...\n")

        d = self._compute_signal_data(cn_close, cn_dk_close, us_rot_close, us_prod_daily)
        cn_date = d["cn_date"]
        us_date = d["us_date"]
        cn_result = d["cn_result"]
        cn_dk_result = d["cn_dk_result"]
        is_cn_signal = d["is_cn_signal"]
        cn_current = d["cn_current"]
        is_us_signal = d["is_us_signal"]
        current_us_w = d["current_us_w"]
        us_scale = d["us_scale"]
        prev_us_w = d["prev_us_w"]
        rebalanced_b = d["rebalanced_b"]
        all_a = d["all_a"]
        momentum_cn = d["momentum_cn"]
        abs_mom_cn = d["abs_mom_cn"]
        us_signal_set = d["us_signal_set"]
        rot_w_cols = d["rot_w_cols"]
        us_rot_result = d["us_rot_result"]
        cn_cooldown_remaining = d.get("cn_cooldown_remaining", 0)
        cn_ma_above = d.get("cn_ma_above", True)
        # A-DK
        dk_date = d["dk_date"]
        is_dk_signal = d["is_dk_signal"]
        dk_current = d["dk_current"]
        dk_cooldown_remaining = d.get("dk_cooldown_remaining", 0)
        dk_mom = d["dk_mom"]

        now_str = datetime.now().strftime("%Y%m%d")
        signal_info = {}

        cn_open, bj_now = is_cn_market_open()
        us_open, _ = is_us_market_open()
        cn_data_is_today = (cn_date.date() == bj_now.date())
        us_data_is_today = (us_date.date() == bj_now.date()) or \
            (us_date.date() == (bj_now - timedelta(days=1)).date() and bj_now.hour < 6)
        bj_time_str_val = bj_now.strftime('%H:%M')
        bj_date_str = bj_now.strftime('%Y-%m-%d')

        # Determine confirmed vs live for each sub-strategy
        cn_signal_live = is_cn_signal and cn_open and cn_data_is_today
        cn_signal_confirmed = is_cn_signal and not cn_signal_live
        us_signal_live = is_us_signal and us_open and us_data_is_today
        us_signal_confirmed = is_us_signal and not us_signal_live

        with poe.start_message() as msg:
            msg.write("## 📊 操作信号（收盘确认）\n\n")
            msg.write(f"⏱ **北京时间 {bj_date_str} {bj_time_str_val}**\n\n")

            # ---- Sub-A ----
            msg.write("### Sub-A: A股轮动\n")
            cn_close_bj = beijing_time_str(cn_date, "CN", "close")
            msg.write(f"数据来源: 东方财富日K线 | 收盘: {cn_close_bj}\n")
            vol_rank_cn = d["vol_rank_cn"]

            # V4: Find last confirmed trade day
            if cn_signal_confirmed:
                _last_sig_date = cn_date
            else:
                _past_cn_trades = cn_result.iloc[:-1]
                _past_cn_trades = _past_cn_trades[_past_cn_trades["is_signal"] == True]
                _last_sig_date = _past_cn_trades.index[-1] if len(_past_cn_trades) > 0 else None

            # Get rebalancing info from last confirmed signal
            _sig_holding = cn_current
            _prev_holding = "cash"
            if _last_sig_date and _last_sig_date in cn_result.index:
                _result_loc = cn_result.index.get_loc(_last_sig_date)
                _sig_holding = cn_result.loc[_last_sig_date, "holding"]
                _prev_holding = cn_result.iloc[_result_loc - 1]["holding"] if _result_loc > 0 else "cash"

            if cn_signal_confirmed:
                # State 1: Signal day + market closed → confirmed & already executed at close
                msg.write(f"✅ 信号日 ({cn_date.strftime('%m-%d')}) — 信号已确认，收盘价执行\n")
                if _sig_holding != _prev_holding:
                    msg.write(f"📋 调仓: **{CN_NAMES.get(_prev_holding, _prev_holding)}** → **{CN_NAMES.get(_sig_holding, _sig_holding)}**\n\n")
                else:
                    msg.write(f"📋 维持持仓: **{CN_NAMES.get(_sig_holding, _sig_holding)}**（无调仓）\n\n")
                signal_info["Sub-A"] = {
                    "is_signal": True,
                    "signal_text": CN_NAMES.get(_sig_holding, _sig_holding),
                    "note": f"{cn_date.strftime('%m-%d')} 收盘执行",
                }
            elif cn_signal_live:
                # State 2: Signal day but market still open → not confirmed
                msg.write(f"⏳ 信号日 ({cn_date.strftime('%m-%d')})，A股未收盘，信号未确认\n")
                msg.write("💡 收盘前请参考「实时信号」查看盘中信号\n\n")
                if _last_sig_date:
                    msg.write(f"上次信号: {_last_sig_date.strftime('%Y-%m-%d')} ✅ 已执行\n")
                    if _sig_holding != _prev_holding:
                        msg.write(f"调仓: {CN_NAMES.get(_prev_holding, _prev_holding)} → **{CN_NAMES.get(_sig_holding, _sig_holding)}**\n")
                    else:
                        msg.write(f"维持持仓: **{CN_NAMES.get(_sig_holding, _sig_holding)}**（无调仓）\n")
                msg.write(f"当前持仓: **{CN_NAMES.get(_sig_holding, _sig_holding)}**\n\n")
                cn_current = _sig_holding  # Override for later use
                signal_info["Sub-A"] = {
                    "is_signal": False,
                    "signal_text": f"盘中未确认,当前:{CN_NAMES.get(_sig_holding, _sig_holding)}",
                    "note": f"上次信号{_last_sig_date.strftime('%m-%d')}" if _last_sig_date else "",
                }
            else:
                # State 3: No trade today → last trade already executed
                if _last_sig_date:
                    msg.write(f"上次换仓: {_last_sig_date.strftime('%Y-%m-%d')} ✅ 已执行\n")
                    if _sig_holding != _prev_holding:
                        msg.write(f"调仓: {CN_NAMES.get(_prev_holding, _prev_holding)} → **{CN_NAMES.get(_sig_holding, _sig_holding)}**\n")
                    else:
                        msg.write(f"维持持仓: **{CN_NAMES.get(_sig_holding, _sig_holding)}**（无调仓）\n")
                msg.write(f"当前持仓: **{CN_NAMES.get(cn_current, cn_current)}**\n")
                _cd_txt = f"冷却剩余{cn_cooldown_remaining}天" if cn_cooldown_remaining > 0 else "冷却已过"
                _ma_txt = "HS300在MA120上方" if cn_ma_above else "HS300在MA120下方→强制现金"
                msg.write(f"📊 V4: {_cd_txt} | {_ma_txt}\n\n")
                signal_info["Sub-A"] = {
                    "is_signal": False,
                    "signal_text": CN_NAMES.get(cn_current, cn_current),
                    "note": f"上次信号{_last_sig_date.strftime('%m-%d')}" if _last_sig_date else "",
                }

            # Show ranking from SIGNAL DAY data (explains the signal decision)
            if _last_sig_date and _last_sig_date in momentum_cn.index:
                _mom_vals = momentum_cn.loc[_last_sig_date][CN_STOCK_CODES].dropna()
                _vol_vals = vol_rank_cn.loc[_last_sig_date][CN_STOCK_CODES].dropna()
                _abs_vals = abs_mom_cn.loc[_last_sig_date][CN_STOCK_CODES].dropna()
                _common = _mom_vals.index.intersection(_vol_vals.index)
                _scores = {}
                for _c in _common:
                    _v = _vol_vals[_c]
                    _scores[_c] = _mom_vals[_c] / _v if _v > 0.001 else float("nan")
                _sorted = sorted(_common, key=lambda c: _scores.get(c, float("-inf")), reverse=True)

                msg.write(f"**信号日排名** ({_last_sig_date.strftime('%m-%d')} 数据, score = {CN_LOOKBACK}日动量 / {CN_VOL_RANK_LB}日波动率):\n\n")
                msg.write(f"| # | ETF | {CN_LOOKBACK}日动量 | {CN_VOL_RANK_LB}日波动率 | score | {CN_ABS_MOM_LB}日绝对动量 |\n")
                msg.write("|:--|:----|------:|------:|------:|------:|\n")
                for _rank, _c in enumerate(_sorted, 1):
                    _name = CN_NAMES.get(_c, _c)
                    _m = _mom_vals[_c]
                    _v = _vol_vals[_c]
                    _s = _scores[_c]
                    _a = _abs_vals.get(_c, float("nan"))
                    _af = "✅" if (not np.isnan(_a) and _a > 0) else "❌"
                    _hold = " 👈" if _c == _sig_holding else ""
                    _top = " 🎯" if _rank == 1 else ""
                    _s_str = f"{_s:.2f}" if not np.isnan(_s) else "N/A"
                    msg.write(f"| {_rank}{_top} | {_name}{_hold} | {_m:+.2%} | {_v:.1%} | {_s_str} | {_a:+.2%} {_af} |\n")

                if _sorted:
                    _best = _sorted[0]
                    _best_name = CN_NAMES.get(_best, _best)
                    _best_abs = _abs_vals.get(_best, float("nan"))
                    _passed = not np.isnan(_best_abs) and _best_abs > 0
                    msg.write(f"\n**选择:** score最高 → **{_best_name}** (score={_scores[_best]:.2f})\n")
                    msg.write(f"**绝对动量过滤:** {CN_ABS_MOM_LB}日动量 = {_best_abs:+.2%} → "
                              f"{'**通过** ✅ → 持有{}'.format(_best_name) if _passed else '**未通过** ❌ → 持有Cash'}\n")
                    _ma_status = "**通过** ✅" if cn_ma_above else "**未通过** ❌ → 强制持有Cash"
                    msg.write(f"**MA120过滤:** HS300{'>' if cn_ma_above else '<'}MA120 → {_ma_status}\n")
            msg.write("\n---\n\n")

            # ---- Sub-A-DK (Long-Short) ----
            msg.write("### Sub-A-DK: 中证1000/上证50多空\n")
            dk_close_bj = beijing_time_str(dk_date, "CN", "close")
            msg.write(f"数据来源: 中证指数官网(000852/000016) | 收盘: {dk_close_bj}\n")

            dk_signal_live = is_dk_signal and cn_open and cn_data_is_today
            dk_signal_confirmed = is_dk_signal and not dk_signal_live

            # V4: Find last confirmed A-DK direction flip
            if dk_signal_confirmed:
                _last_dk_sig_date = dk_date
            else:
                _past_dk_trades = cn_dk_result.iloc[:-1]
                _past_dk_trades = _past_dk_trades[_past_dk_trades["is_signal"] == True]
                _last_dk_sig_date = _past_dk_trades.index[-1] if len(_past_dk_trades) > 0 else None

            _dk_sig_holding = dk_current
            _dk_prev_holding = None
            if _last_dk_sig_date and _last_dk_sig_date in cn_dk_result.index:
                _dk_result_loc = cn_dk_result.index.get_loc(_last_dk_sig_date)
                _dk_sig_holding = cn_dk_result.loc[_last_dk_sig_date, "holding"]
                _dk_prev_holding = cn_dk_result.iloc[_dk_result_loc - 1]["holding"] if _dk_result_loc > 0 else None

            def _dk_pos_str(long_leg):
                if long_leg is None or long_leg == "none":
                    return "未建仓"
                short_leg = CN_DK_COLS[1] if long_leg == CN_DK_COLS[0] else CN_DK_COLS[0]
                return f"做多 {CN_DK_NAMES.get(long_leg, long_leg)} / 做空 {CN_DK_NAMES.get(short_leg, short_leg)}"

            if dk_signal_confirmed:
                msg.write(f"✅ 信号日 ({dk_date.strftime('%m-%d')}) — 信号已确认，收盘价执行\n")
                if _dk_sig_holding != _dk_prev_holding:
                    msg.write(f"📋 调仓: **{_dk_pos_str(_dk_prev_holding)}** → **{_dk_pos_str(_dk_sig_holding)}**\n")
                else:
                    msg.write(f"📋 维持方向: **{_dk_pos_str(_dk_sig_holding)}**（无调仓）\n")
                dk_mom_vals = dk_mom.loc[dk_date] if dk_date in dk_mom.index else dk_mom.iloc[-1]
                msg.write(f"中证1000 {CN_DK_MOM_LB}日动量: {dk_mom_vals.get(CN_DK_COLS[0], np.nan):+.2%} | 上证50: {dk_mom_vals.get(CN_DK_COLS[1], np.nan):+.2%}\n\n")
                signal_info["Sub-A-DK"] = {
                    "is_signal": True,
                    "signal_text": _dk_pos_str(_dk_sig_holding),
                    "note": f"{dk_date.strftime('%m-%d')} 收盘执行",
                }
            elif dk_signal_live:
                msg.write(f"⏳ 信号日 ({dk_date.strftime('%m-%d')})，A股未收盘，信号未确认\n")
                msg.write(f"当前方向: **{_dk_pos_str(_dk_sig_holding)}**\n\n")
                signal_info["Sub-A-DK"] = {
                    "is_signal": True,
                    "signal_text": f"盘中未确认,当前:{_dk_pos_str(_dk_sig_holding)}",
                    "note": f"上次信号{_last_dk_sig_date.strftime('%m-%d')}" if _last_dk_sig_date else "",
                }
            else:
                if _last_dk_sig_date:
                    msg.write(f"上次翻转: {_last_dk_sig_date.strftime('%Y-%m-%d')} ✅ 已执行\n")
                    if _dk_sig_holding != _dk_prev_holding:
                        msg.write(f"调仓: {_dk_pos_str(_dk_prev_holding)} → **{_dk_pos_str(_dk_sig_holding)}**\n")
                    else:
                        msg.write(f"维持方向: **{_dk_pos_str(_dk_sig_holding)}**（无调仓）\n")
                msg.write(f"当前方向: **{_dk_pos_str(dk_current)}**\n")
                _dk_cd_txt = f"冷却剩余{dk_cooldown_remaining}天" if dk_cooldown_remaining > 0 else "冷却已过"
                msg.write(f"📊 V4: {_dk_cd_txt}（杠杆日频调整不受冷却限制）\n\n")
                signal_info["Sub-A-DK"] = {
                    "is_signal": False,
                    "signal_text": _dk_pos_str(dk_current),
                    "note": f"上次翻转{_last_dk_sig_date.strftime('%m-%d')}" if _last_dk_sig_date else "",
                }

            msg.write("\n---\n\n")

            # ---- Sub-B ----
            us_close_bj = beijing_time_str(us_date, "US", "close")
            msg.write("### Sub-B: 美股9ETF轮动\n")
            msg.write(f"数据来源: Yahoo Finance日K线 | 收盘: {us_close_bj}\n")
            changed = {l: c["proxy"] for l, c in US_ROT_ASSETS.items() if l != c["proxy"]}
            if changed:
                msg.write("实盘→proxy: " + ", ".join(f"{k}→{v}" for k, v in changed.items()) + "\n")

            # Find last confirmed signal
            if us_signal_confirmed:
                _last_us_sig_date = us_date
            else:
                _prev_us_sigs = sorted([i for i in us_signal_set if i < len(us_rot_close) - 1])
                _last_us_sig_date = us_rot_close.index[_prev_us_sigs[-1]] if _prev_us_sigs else None

            # Get signal-day weights and rebalancing info
            _us_sig_w = dict(current_us_w)
            _us_prev_w = {"BIL": 1.0}
            _us_rebalanced = False
            _us_sig_scale = us_scale
            if _last_us_sig_date and _last_us_sig_date in us_rot_result.index:
                _us_rloc = us_rot_result.index.get_loc(_last_us_sig_date)
                _us_sig_w = {c.replace("w_", ""): us_rot_result.loc[_last_us_sig_date, c] for c in rot_w_cols}
                _us_rebalanced = bool(us_rot_result.loc[_last_us_sig_date, "rebalanced"])
                if _us_rloc > 0:
                    _us_prev_w = {c.replace("w_", ""): us_rot_result.iloc[_us_rloc - 1][c] for c in rot_w_cols}
                # Vol scaling at signal time (hist BEFORE signal day)
                _hist_before = us_rot_result["return"].iloc[:_us_rloc].values
                if len(_hist_before) >= US_ROT_VOL_WINDOW:
                    _us_rv_sig = np.std(_hist_before[-US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
                    _us_sig_scale = min(max(US_ROT_TARGET_VOL / _us_rv_sig, 0.05), US_ROT_MAX_LEV) if _us_rv_sig > 0.001 else US_ROT_MAX_LEV

            _us_all_etfs = set(list(_us_sig_w.keys()) + list(_us_prev_w.keys()))

            if us_signal_confirmed:
                # State 1: Signal day confirmed (market closed)
                us_exec_bj = us_exec_time_str(us_date)
                exec_happened_us = _has_execution_happened(us_date, "US", bj_now)
                msg.write(f"✅ 信号日 (美东 {us_date.strftime('%m-%d')}) — 信号已确认\n")
                if exec_happened_us:
                    msg.write(f"✅ 已执行 ({us_exec_bj})\n")
                else:
                    msg.write(f"⏳ 等待执行: {us_exec_bj}\n")
                if _us_rebalanced:
                    msg.write("📋 **调仓信号**\n\n")
                else:
                    msg.write("📋 调仓幅度未达阈值，**维持原仓位**\n\n")
                us_sig_text = "; ".join(f"{_ROT_PROXY_TO_LIVE.get(e,e)} {_us_sig_w.get(e,0):.0%}" for e in sorted(_us_all_etfs) if _us_sig_w.get(e, 0) > 0.005)
                signal_info["Sub-B"] = {"is_signal": True, "signal_text": us_sig_text, "note": us_exec_bj}
            elif us_signal_live:
                # State 2: Signal day but market still open
                msg.write(f"⏳ 信号日 (美东 {us_date.strftime('%m-%d')})，美股未收盘，信号未确认\n")
                msg.write("💡 美股收盘后再次查询获取确认信号\n\n")
                if _last_us_sig_date:
                    _prev_bj = beijing_time_str(_last_us_sig_date, "US", "close")
                    msg.write(f"上次信号: {_prev_bj} ✅\n")
                    if _us_rebalanced:
                        msg.write("📋 **调仓信号**\n\n")
                    else:
                        msg.write("📋 维持原仓位\n\n")
                us_sig_text = "; ".join(f"{_ROT_PROXY_TO_LIVE.get(e,e)} {_us_sig_w.get(e,0):.0%}" for e in sorted(_us_all_etfs) if _us_sig_w.get(e, 0) > 0.005)
                signal_info["Sub-B"] = {"is_signal": False, "signal_text": f"盘中未确认,当前:{us_sig_text}",
                                        "note": f"上次信号{beijing_time_str(_last_us_sig_date, 'US', 'close')}" if _last_us_sig_date else ""}
            else:
                # State 3: Not signal day
                if _last_us_sig_date:
                    _sig_bj = beijing_time_str(_last_us_sig_date, "US", "close")
                    exec_happened_us = _has_execution_happened(_last_us_sig_date, "US", bj_now)
                    msg.write(f"上次信号: {_sig_bj}")
                    if exec_happened_us:
                        msg.write(" ✅ 已执行\n")
                    else:
                        msg.write(f" ⏳ 等待执行: {us_exec_time_str(_last_us_sig_date)}\n")
                    if _us_rebalanced:
                        msg.write("📋 **调仓信号**\n\n")
                    else:
                        msg.write("📋 调仓幅度未达阈值，**维持原仓位**\n\n")
                us_sig_text = "; ".join(f"{_ROT_PROXY_TO_LIVE.get(e,e)} {_us_sig_w.get(e,0):.0%}" for e in sorted(_us_all_etfs) if _us_sig_w.get(e, 0) > 0.005)
                signal_info["Sub-B"] = {"is_signal": False, "signal_text": f"当前:{us_sig_text}",
                                        "note": f"上次信号{beijing_time_str(_last_us_sig_date, 'US', 'close')}" if _last_us_sig_date else ""}

            # Weight change table (always show signal-day weights)
            msg.write("| ETF | 目标权重 | 变动 |\n|:----|--------:|-----:|\n")
            for etf in sorted(_us_all_etfs):
                cur = _us_sig_w.get(etf, 0)
                prev = _us_prev_w.get(etf, 0)
                if cur < 0.001 and prev < 0.001:
                    continue
                diff = cur - prev
                ds = f"{diff:+.1%}" if abs(diff) > 0.001 else "—"
                live = _ROT_PROXY_TO_LIVE.get(etf, etf)
                msg.write(f"| {live} | {cur:.1%} | {ds} |\n")

            # Signal-day ranking details (engine uses iloc[i] — signal day's close data)
            if _last_us_sig_date:
                _sig_close_idx = us_rot_close.index.get_loc(_last_us_sig_date)
                if _sig_close_idx >= US_ROT_LB:
                    _momentum_us = us_rot_close.div(us_rot_close.shift(US_ROT_LB)).sub(1)
                    _vol_us = us_rot_close.pct_change().rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
                    _mom_row = _momentum_us.iloc[_sig_close_idx]
                    _vol_row = _vol_us.iloc[_sig_close_idx]

                    msg.write(f"\n**信号日排名** ({_last_us_sig_date.strftime('%m-%d')} 收盘数据):\n\n")
                    msg.write(f"| ETF | {US_ROT_LB}日动量 | {US_ROT_VOL_LB}日波动率 | Top3? | 绝对动量>0? |\n")
                    msg.write("|:----|------:|------:|:----:|:----:|\n")
                    _us_avail = {}
                    for a in US_ROT_POOL:
                        if (a in _mom_row.index and not np.isnan(_mom_row[a])
                                and a in _vol_row.index and not np.isnan(_vol_row[a]) and _vol_row[a] > 0.001):
                            _us_avail[a] = _mom_row[a]
                    _us_sorted = sorted(_us_avail.items(), key=lambda x: x[1], reverse=True)
                    _top3 = [a for a, _ in _us_sorted[:3]]
                    for _rank, (a, m) in enumerate(_us_sorted, 1):
                        _live = _ROT_PROXY_TO_LIVE.get(a, a)
                        _v = _vol_row[a]
                        _is_top3 = "✅" if a in _top3 else ""
                        _abs_pass = "✅" if m > US_ROT_ABS_THRESHOLD else "❌"
                        _marker = " 🏆" if _rank <= 3 else ""
                        msg.write(f"| {_rank}. {_live}{_marker} | {m:+.2%} | {_v:.1%} | {_is_top3} | {_abs_pass} |\n")

                    # Inverse-vol raw weights
                    _raw_w = _us_raw_weights(_mom_row, _vol_row, US_ROT_POOL, 3, US_ROT_ABS_THRESHOLD)
                    _passed = [a for a in _top3 if _us_avail.get(a, 0) > US_ROT_ABS_THRESHOLD]
                    _failed = [a for a in _top3 if _us_avail.get(a, 0) <= US_ROT_ABS_THRESHOLD]
                    _bil_share = len(_failed) / 3 if _top3 else 0
                    msg.write(f"\n**反波动率加权 (1/vol):**\n\n")
                    if _passed:
                        _iv = {a: 1.0 / _vol_row[a] for a in _passed}
                        _total_iv = sum(_iv.values())
                        _risky = 1.0 - _bil_share
                        msg.write("| ETF | 1/vol | 原始权重 |\n|:----|------:|------:|\n")
                        for a in _passed:
                            _live = _ROT_PROXY_TO_LIVE.get(a, a)
                            _w = (_iv[a] / _total_iv) * _risky
                            msg.write(f"| {_live} | {_iv[a]:.1f} | {_w:.1%} |\n")
                    if _failed:
                        msg.write(f"| BIL(未达标{len(_failed)}只) | — | {_bil_share:.1%} |\n")

                    msg.write(f"\n**波动率缩放:** {_us_sig_scale:.2f}x")
                    if _us_sig_scale > 1.0:
                        msg.write(f" (>1: 仅放大期货类ETF，上限{US_ROT_MAX_LEV:.1f}x)\n")
                    elif _us_sig_scale < 1.0:
                        msg.write(" (<1: 所有资产等比缩减)\n")
                    else:
                        msg.write("\n")

            msg.write("\n---\n\n")

            # ---- Sub-C ----
            signal_info["Sub-C"] = self._write_sub_c(msg, d, us_prod_daily)

        # ==============================================================
        # GENERATE EXCEL
        # ==============================================================
        cutoff = cn_date - timedelta(days=60)
        all_rebalances = []
        cn_rebs = extract_cn_rebalances(cn_result, cn_close)
        all_rebalances.extend([r for r in cn_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        dk_rebs = extract_dk_rebalances(cn_dk_result)
        all_rebalances.extend([r for r in dk_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        us_rebs = extract_us_rot_rebalances(d["us_rot_result"])
        all_rebalances.extend([r for r in us_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        prod_rebs = extract_prod_rebalances(d["prod_details"], d["prod_monthly"])
        all_rebalances.extend([r for r in prod_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        _mark_tentative_records(all_rebalances)
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
    # Live signal handler (real-time snapshot — "实时信号")
    # ----------------------------------------------------------
    def _handle_live_signal(self):
        with poe.start_message() as msg:
            cn_close, cn_dk_close, us_rot_close, us_prod_daily = self._fetch_data(msg)
            msg.write("⏳ 正在计算实时信号...\n")

        d = self._compute_signal_data(cn_close, cn_dk_close, us_rot_close, us_prod_daily)
        cn_date = d["cn_date"]
        us_date = d["us_date"]
        is_cn_signal = d["is_cn_signal"]
        cn_current = d["cn_current"]
        hypo_cn = d["hypo_cn"]
        is_us_signal = d["is_us_signal"]
        current_us_w = d["current_us_w"]
        us_scale = d["us_scale"]
        hypo_us_w = d["hypo_us_w"]
        rebalanced_b = d["rebalanced_b"]
        would_rebalance = d["would_rebalance"]
        turnover_b = d["turnover_b"]
        all_a = d["all_a"]
        momentum_cn = d["momentum_cn"]
        abs_mom_cn = d["abs_mom_cn"]
        cn_result = d["cn_result"]
        cn_cooldown_remaining = d.get("cn_cooldown_remaining", 0)
        cn_ma_above = d.get("cn_ma_above", True)
        us_signal_set = d["us_signal_set"]
        # A-DK
        dk_date = d["dk_date"]
        is_dk_signal = d["is_dk_signal"]
        dk_current = d["dk_current"]
        hypo_dk = d["hypo_dk"]
        dk_mom = d["dk_mom"]
        cn_dk_result = d["cn_dk_result"]
        dk_cooldown_remaining = d.get("dk_cooldown_remaining", 0)

        cn_open, bj_now = is_cn_market_open()
        us_open, _ = is_us_market_open()
        cn_data_is_today = (cn_date.date() == bj_now.date())
        us_data_is_today = (us_date.date() == bj_now.date()) or \
            (us_date.date() == (bj_now - timedelta(days=1)).date() and bj_now.hour < 6)
        any_market_live = (cn_open and cn_data_is_today) or (us_open and us_data_is_today)

        bj_time_str_val = bj_now.strftime('%H:%M')
        bj_date_str = bj_now.strftime('%Y-%m-%d')

        with poe.start_message() as msg:
            msg.write("## 📡 实时信号\n\n")

            # Timestamp + market status banner
            if any_market_live:
                live_markets = []
                if cn_open and cn_data_is_today:
                    live_markets.append("A股")
                if us_open and us_data_is_today:
                    live_markets.append("美股")
                msg.write(f"⏱ **北京时间 {bj_date_str} {bj_time_str_val}** 实时数据快照"
                         f"（{'、'.join(live_markets)}盘中，收盘前信号可能变化）\n\n")
            else:
                msg.write(f"⏱ **北京时间 {bj_date_str} {bj_time_str_val}** 基于收盘数据（非盘中）\n\n")

            # ---- Sub-A ----
            msg.write("### Sub-A: A股轮动\n")
            cn_close_bj = beijing_time_str(cn_date, "CN", "close")
            msg.write(f"数据来源: 东方财富日K线 | 收盘: {cn_close_bj}")
            if cn_open and cn_data_is_today:
                msg.write(" ⚡盘中实时")
            msg.write("\n")

            hypo_cn_name = CN_NAMES.get(hypo_cn, hypo_cn)
            cn_current_name = CN_NAMES.get(cn_current, cn_current)
            if is_cn_signal:
                msg.write(f"✅ 信号日 ({cn_date.strftime('%m-%d')})\n")
                msg.write(f"当前持仓: **{cn_current_name}**\n")
                msg.write(f"假设现在收盘，信号: **{hypo_cn_name}**")
                if hypo_cn != cn_current:
                    msg.write(" ⬅️ 需换仓")
                else:
                    msg.write("（无变化）")
                msg.write("\n\n")
            else:
                _past_cn_trades_live = cn_result.iloc[:-1]
                _past_cn_trades_live = _past_cn_trades_live[_past_cn_trades_live["is_signal"] == True]
                last_cn_sig_date = _past_cn_trades_live.index[-1] if len(_past_cn_trades_live) > 0 else cn_date
                _cd_txt = f"冷却剩余{cn_cooldown_remaining}天" if cn_cooldown_remaining > 0 else "冷却已过"
                _ma_txt = "MA120上方" if cn_ma_above else "MA120下方→现金"
                msg.write(f"⏸️ 今日无换仓（{_cd_txt} | {_ma_txt} | 上次换仓: {last_cn_sig_date.strftime('%Y-%m-%d')}）\n")
                msg.write(f"当前持仓: **{cn_current_name}**\n")
                if hypo_cn == cn_current:
                    msg.write(f"假设今天出信号: **{hypo_cn_name}**（无变化）\n\n")
                else:
                    msg.write(f"假设今天出信号: **{hypo_cn_name}** ⬅️ 需换仓\n\n")

            # Risk-adjusted ranking
            vol_rank_cn = d["vol_rank_cn"]
            _mom_vals2 = momentum_cn.iloc[-1][CN_STOCK_CODES].dropna()
            _vol_vals2 = vol_rank_cn.iloc[-1][CN_STOCK_CODES].dropna()
            _abs_vals2 = abs_mom_cn.iloc[-1][CN_STOCK_CODES].dropna()
            _common2 = _mom_vals2.index.intersection(_vol_vals2.index)
            _scores2 = {}
            for _c in _common2:
                _v = _vol_vals2[_c]
                _scores2[_c] = _mom_vals2[_c] / _v if _v > 0.001 else float("nan")
            _sorted2 = sorted(_common2, key=lambda c: _scores2.get(c, float("-inf")), reverse=True)

            msg.write(f"**风险调整排名** (score = {CN_LOOKBACK}日动量 / {CN_VOL_RANK_LB}日波动率):\n\n")
            msg.write(f"| # | ETF | {CN_LOOKBACK}日动量 | {CN_VOL_RANK_LB}日波动率 | score | {CN_ABS_MOM_LB}日绝对动量 |\n")
            msg.write("|:--|:----|------:|------:|------:|------:|\n")
            for _rank, _c in enumerate(_sorted2, 1):
                _name = CN_NAMES.get(_c, _c)
                _m = _mom_vals2[_c]
                _v = _vol_vals2[_c]
                _s = _scores2[_c]
                _a = _abs_vals2.get(_c, float("nan"))
                _af = "✅" if (not np.isnan(_a) and _a > 0) else "❌"
                _hold = " 👈" if _c == cn_current else ""
                _top = " 🎯" if _rank == 1 else ""
                _s_str = f"{_s:.2f}" if not np.isnan(_s) else "N/A"
                msg.write(f"| {_rank}{_top} | {_name}{_hold} | {_m:+.2%} | {_v:.1%} | {_s_str} | {_a:+.2%} {_af} |\n")

            if _sorted2:
                _best = _sorted2[0]
                _best_name = CN_NAMES.get(_best, _best)
                _best_abs = _abs_vals2.get(_best, float("nan"))
                _passed = not np.isnan(_best_abs) and _best_abs > 0
                _would_hold = _best_name if _passed else "Cash"
                _ma_status_live = "通过 ✅" if cn_ma_above else "未通过 ❌ → 强制Cash"
                if is_cn_signal:
                    msg.write(f"\n**选择:** score最高 → **{_best_name}** (score={_scores2[_best]:.2f})\n")
                    msg.write(f"**绝对动量过滤:** {CN_ABS_MOM_LB}日动量 = {_best_abs:+.2%} → "
                              f"{'**通过** ✅ → 持有{}'.format(_best_name) if _passed else '**未通过** ❌ → 持有Cash'}\n")
                    msg.write(f"**MA120过滤:** HS300{'>' if cn_ma_above else '<'}MA120 → {_ma_status_live}\n")
                else:
                    msg.write(f"\nscore最高 → **{_best_name}** (score={_scores2[_best]:.2f})\n")
                    msg.write(f"绝对动量过滤: {CN_ABS_MOM_LB}日动量 = {_best_abs:+.2%} → "
                              f"{'通过 ✅' if _passed else '未通过 ❌'}\n")
                    msg.write(f"MA120过滤: HS300{'>' if cn_ma_above else '<'}MA120 → {_ma_status_live}\n")
                    _final_hold = _would_hold if cn_ma_above else "Cash"
                    msg.write(f"→ 如出信号选择 **{_final_hold}**\n")
            msg.write("\n---\n\n")

            # ---- Sub-A-DK (Long-Short) ----
            msg.write("### Sub-A-DK: 中证1000/上证50多空\n")
            dk_close_bj = beijing_time_str(dk_date, "CN", "close")
            msg.write(f"数据来源: 中证指数官网(000852/000016) | 收盘: {dk_close_bj}")

            def _dk_pos_str_live(long_leg):
                if long_leg is None or long_leg == "none":
                    return "未建仓"
                short_leg = CN_DK_COLS[1] if long_leg == CN_DK_COLS[0] else CN_DK_COLS[0]
                return f"做多{CN_DK_NAMES.get(long_leg, long_leg)}/做空{CN_DK_NAMES.get(short_leg, short_leg)}"

            hypo_dk_name = _dk_pos_str_live(hypo_dk)
            dk_current_name = _dk_pos_str_live(dk_current)
            dk_mom_latest = dk_mom.iloc[-1]
            zz1000_mom_now = dk_mom_latest.get(CN_DK_COLS[0], np.nan)
            sz50_mom_now = dk_mom_latest.get(CN_DK_COLS[1], np.nan)

            if is_dk_signal:
                msg.write(f"\n✅ 信号日 ({dk_date.strftime('%m-%d')})\n")
                msg.write(f"当前方向: **{dk_current_name}**\n")
                msg.write(f"假设现在收盘，信号: **{hypo_dk_name}**")
                if hypo_dk != dk_current:
                    msg.write(f" ⬅️ 方向翻转\n")
                else:
                    msg.write(f"（无变化）\n")
            else:
                _past_dk_trades_live = cn_dk_result.iloc[:-1]
                _past_dk_trades_live = _past_dk_trades_live[_past_dk_trades_live["is_signal"] == True]
                last_dk_date = _past_dk_trades_live.index[-1] if len(_past_dk_trades_live) > 0 else dk_date
                _dk_cd_txt = f"冷却剩余{dk_cooldown_remaining}天" if dk_cooldown_remaining > 0 else "冷却已过"
                msg.write(f"\n⏸️ 今日无翻转（{_dk_cd_txt} | 上次翻转: {last_dk_date.strftime('%Y-%m-%d')}）\n")
                msg.write(f"当前方向: **{dk_current_name}**\n")
                if hypo_dk == dk_current:
                    msg.write(f"假设今天出信号: **{hypo_dk_name}**（无变化）\n")
                else:
                    msg.write(f"假设今天出信号: **{hypo_dk_name}** ⬅️ 需翻转\n")
            msg.write(f"中证1000 {CN_DK_MOM_LB}日动量: {zz1000_mom_now:+.2%} | 上证50: {sz50_mom_now:+.2%}\n")
            msg.write("\n---\n\n")

            # ---- Sub-B ----
            us_close_bj = beijing_time_str(us_date, "US", "close")
            msg.write("### Sub-B: 美股9ETF轮动\n")
            msg.write(f"数据来源: Yahoo Finance日K线 | 收盘: {us_close_bj}")
            if us_open and us_data_is_today:
                msg.write(" ⚡盘中实时")
            msg.write("\n")
            msg.write(f"波动率缩放: {us_scale:.2f}x\n")
            changed = {l: c["proxy"] for l, c in US_ROT_ASSETS.items() if l != c["proxy"]}
            if changed:
                msg.write("实盘→proxy: " + ", ".join(f"{k}→{v}" for k, v in changed.items()) + "\n")
            msg.write("\n")

            if is_us_signal:
                msg.write(f"✅ 信号日 (美东 {us_date.strftime('%m-%d')})\n")
                msg.write("假设现在收盘，信号权重:\n\n")
                msg.write("| ETF | 当前持仓 | 假设信号 | 变动 |\n|:----|--------:|--------:|-----:|\n")
                for etf in sorted(all_a):
                    cur = current_us_w.get(etf, 0)
                    prev = d["prev_us_w"].get(etf, 0) if d["prev_us_w"] else 0
                    if cur < 0.001 and prev < 0.001:
                        continue
                    diff = cur - prev
                    ds = f"{diff:+.1%}" if abs(diff) > 0.001 else "—"
                    live = _ROT_PROXY_TO_LIVE.get(etf, etf)
                    msg.write(f"| {live} | {prev:.1%} | {cur:.1%} | {ds} |\n")
                msg.write(f"\n调仓幅度: **{turnover_b:.1%}**")
                if rebalanced_b:
                    msg.write(f" ✅ 超{US_ROT_MIN_TURNOVER:.0%}阈值，**会调仓**\n")
                else:
                    msg.write(f" ❌ 低于{US_ROT_MIN_TURNOVER:.0%}阈值，**不调仓**\n")
            else:
                sigs = sorted([i for i in us_signal_set if i < len(us_rot_close) - 1])
                last_us_date = us_rot_close.index[sigs[-1]] if sigs else us_date
                last_us_close_bj = beijing_time_str(last_us_date, "US", "close")
                msg.write(f"⏸️ 非信号日（上次信号: {last_us_close_bj}）\n")
                msg.write("假设现在收盘出信号:\n\n")
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
                msg.write(f"\n调仓幅度: **{turnover_b:.1%}**")
                if would_rebalance:
                    msg.write(f" ✅ 超{US_ROT_MIN_TURNOVER:.0%}阈值，**会调仓**\n")
                else:
                    msg.write(f" ❌ 低于{US_ROT_MIN_TURNOVER:.0%}阈值，**不调仓**\n")
            msg.write("\n---\n\n")

            # ---- Sub-C ----
            self._write_sub_c(msg, d, us_prod_daily)

    # ----------------------------------------------------------
    # Parameters handler
    # ----------------------------------------------------------
    def _handle_params(self):
        with poe.start_message() as msg:
            msg.write("## ⚙️ 策略参数总览\n\n")

            # ---- Sub-A ----
            msg.write("### Sub-A: A股轮动\n\n")
            msg.write("| 参数 | 值 | 说明 |\n")
            msg.write("|:-----|:---|:-----|\n")
            msg.write(f"| 排名动量窗口 | **{CN_LOOKBACK}日** | 过去{CN_LOOKBACK}个交易日收益率，用于排名 |\n")
            msg.write(f"| 排名波动率窗口 | **{CN_VOL_RANK_LB}日** | 过去{CN_VOL_RANK_LB}个交易日年化波动率，用于排名 |\n")
            msg.write(f"| 绝对动量窗口 | **{CN_ABS_MOM_LB}日** | 过去{CN_ABS_MOM_LB}个交易日收益率，>0才持有 |\n")
            msg.write(f"| 波动率缩放 | **无** | V12去掉波动率缩放 |\n")
            msg.write(f"| 交易成本 | **{CN_COMMISSION:.1%}** | 单边手续费 |\n")
            msg.write(f"| 无风险利率 | **3%/年** | Cash日收益 = (1.03^(1/244))-1 |\n")
            stock_names = [CN_NAMES.get(c, c) for c in CN_STOCK_CODES]
            msg.write(f"| 资产池 | **{len(CN_STOCK_CODES)}只** | {', '.join(stock_names)} |\n")
            msg.write(f"| 信号频率 | **日频(V4)** | 每个交易日检查信号 |\n")
            msg.write(f"| 冷却期 | **{CN_COOLDOWN_DAYS}个交易日** | 换仓后至少等{CN_COOLDOWN_DAYS}个交易日才能再次换仓 |\n")
            msg.write(f"| HS300均线过滤 | **MA{CN_MA_WINDOW}** | HS300收盘 < MA{CN_MA_WINDOW}时强制持有Cash(熊市保护) |\n")
            msg.write("\n**计算过程:**\n")
            msg.write(f"1. 每个交易日，计算5只ETF/指数的{CN_LOOKBACK}日动量: `mom = price/price[{CN_LOOKBACK}日前] - 1`\n")
            msg.write(f"2. 计算{CN_VOL_RANK_LB}日年化波动率: `vol = std(日收益率, {CN_VOL_RANK_LB}日) × √244`\n")
            msg.write("3. 风险调整得分: `score = mom / vol`（类夏普比率），选得分最高者\n")
            msg.write(f"4. 绝对动量过滤: 检查该ETF的{CN_ABS_MOM_LB}日动量是否 > 0，不满足则持有Cash\n")
            msg.write(f"5. HS300均线过滤: HS300收盘价 < MA{CN_MA_WINDOW}时，强制持有Cash\n")
            msg.write(f"6. 冷却期控制: 距上次换仓不足{CN_COOLDOWN_DAYS}个交易日，跳过本次信号\n")

            msg.write("\n---\n\n")

            # ---- Sub-A-DK ----
            msg.write("### Sub-A-DK: 中证1000/上证50多空\n\n")
            msg.write("| 参数 | 值 | 说明 |\n")
            msg.write("|:-----|:---|:-----|\n")
            msg.write(f"| 做多标的 | **中证1000(000852)** | 中证1000指数 |\n")
            msg.write(f"| 做空标的 | **上证50(000016)** | 上证50指数 |\n")
            msg.write(f"| 动量比较窗口 | **{CN_DK_MOM_LB}日** | 比较两者的20日绝对动量 |\n")
            msg.write(f"| 波动率缩放目标 | **{CN_DK_TARGET_VOL:.0%}** | 目标年化波动率 |\n")
            msg.write(f"| 波动率计算窗口 | **{CN_DK_VOL_WINDOW}日** | 用spread收益率计算已实现波动率 |\n")
            msg.write(f"| 最大杠杆 | **{CN_DK_MAX_LEV:.1f}x** | 高杠杆上限 |\n")
            msg.write(f"| 最小杠杆 | **{CN_DK_MIN_LEV:.1f}x** | 高波动时最低仓位 |\n")
            msg.write(f"| 交易成本 | **{CN_COMMISSION:.1%}** | 单边手续费(翻转=4笔单边) |\n")
            msg.write(f"| 信号频率 | **日频(V4)** | 每个交易日检查方向信号 |\n")
            msg.write(f"| 冷却期 | **{CN_DK_COOLDOWN_DAYS}个交易日** | 方向翻转后至少等{CN_DK_COOLDOWN_DAYS}个交易日才能再次翻转 |\n")
            msg.write(f"| 年化交易日 | **{CN_DK_TRADING_DAYS}日** | 波动率年化基数 |\n")
            msg.write("\n**计算过程:**\n")
            msg.write(f"1. 每个交易日，计算中证1000和上证50的{CN_DK_MOM_LB}日绝对动量\n")
            msg.write("2. 做多动量较高的指数，做空动量较低的指数（永远满仓，一多一空）\n")
            msg.write(f"3. 冷却期控制: 距上次翻转不足{CN_DK_COOLDOWN_DAYS}个交易日，跳过本次信号\n")
            msg.write("4. signal.shift(1): 信号日决策，下一个交易日才生效（信号日收益归旧持仓）\n")
            msg.write(f"5. 波动率缩放(日频，不受冷却期约束): scale = clip({CN_DK_TARGET_VOL:.0%} / realized_vol, {CN_DK_MIN_LEV:.1f}, {CN_DK_MAX_LEV:.1f})，scale.shift(1)延迟一天\n")
            msg.write("6. 数据来源: 中证指数官网(csindex.com.cn)\n")

            msg.write("\n---\n\n")

            # ---- Sub-B ----
            msg.write("### Sub-B: 美股9ETF轮动\n\n")
            msg.write("| 参数 | 值 | 说明 |\n")
            msg.write("|:-----|:---|:-----|\n")
            msg.write(f"| 动量窗口 | **{US_ROT_LB}日** | 过去{US_ROT_LB}个交易日收益率，用于排名 |\n")
            msg.write(f"| 波动率窗口(权重) | **{US_ROT_VOL_LB}日** | 用于反波动率加权 |\n")
            msg.write(f"| Top N | **3** | 选动量最高的3只ETF |\n")
            msg.write(f"| 绝对动量阈值 | **{US_ROT_ABS_THRESHOLD:.0%}(动量为正)** | {US_ROT_LB}日动量 > 0 才持有，不达标部分转BIL |\n")
            msg.write(f"| 波动率缩放窗口 | **{US_ROT_VOL_WINDOW}日** | 计算近{US_ROT_VOL_WINDOW}日已实现波动率 |\n")
            msg.write(f"| 目标年化波动率 | **{US_ROT_TARGET_VOL:.0%}** | 波动率缩放目标 |\n")
            msg.write(f"| 最大杠杆 | **{US_ROT_MAX_LEV:.1f}x** | 仅限期货类ETF(VOO/QQQM/GLDM/VGLT) |\n")
            msg.write(f"| 最小调仓幅度 | **{US_ROT_MIN_TURNOVER:.0%}** | 总变动 < {US_ROT_MIN_TURNOVER:.0%} 则不调仓 |\n")
            msg.write(f"| BTC参与起始 | **{US_ROT_BTC_START.strftime('%Y-%m-%d')}** | 之前BTC不参与排名 |\n")
            msg.write(f"| BTC持仓上限 | **{US_ROT_BTC_MAX_W:.0%}** | 超出部分归入BIL |\n")
            msg.write(f"| 交易成本 | **{US_ROT_COMMISSION:.1%}** | 单边手续费 |\n")
            n_etfs = len(US_ROT_ASSETS)
            etf_labels = [f"{k}({v['label']})" for k, v in US_ROT_ASSETS.items()]
            msg.write(f"| 资产池 | **{n_etfs}只** | {', '.join(etf_labels)} |\n")
            msg.write(f"| 信号频率 | **周度** | 每周最后一个交易日(≤周四) |\n")
            msg.write("\n**计算过程:**\n")
            msg.write(f"1. 每个信号日，计算{n_etfs}只ETF的{US_ROT_LB}日动量（用信号日收盘数据）\n")
            msg.write("2. 按动量排名，选Top 3\n")
            msg.write("3. 绝对动量过滤: 动量 > 0 的留下，不达标的份额转为BIL(现金)\n")
            msg.write(f"4. 反波动率加权: 权重 ∝ 1/vol({US_ROT_VOL_LB}日)，波动越低权重越高\n")
            msg.write(f"5. 波动率缩放(Model B): scale = {US_ROT_TARGET_VOL:.0%}/已实现波动率，"
                      f"scale≤1时所有资产等比缩减；scale>1时仅放大期货类ETF，最高{US_ROT_MAX_LEV:.1f}x\n")
            msg.write(f"6. BTC上限: 若BTC权重 > {US_ROT_BTC_MAX_W:.0%}，超出部分归入BIL\n")

            msg.write("\n---\n\n")

            # ---- Sub-C ----
            msg.write("### Sub-C: 美股7ETF生产组合\n\n")
            msg.write("| 参数 | 值 | 说明 |\n")
            msg.write("|:-----|:---|:-----|\n")
            msg.write(f"| 择时 | **{'开启' if PROD_USE_TIMING else '关闭'}** | 纯买入持有，无择时信号 |\n")
            msg.write(f"| 再平衡月份 | **{PROD_REBAL_MONTH}月** | 每年12月恢复目标权重 |\n")
            msg.write(f"| 现金ETF | **{PROD_CASH}** | 未持有时的现金替代 |\n")
            msg.write(f"| 交易成本 | **{PROD_COMMISSION:.1%}** | 单边手续费 |\n")
            msg.write(f"| BTC参与起始 | **{BTC_BT_START.strftime('%Y-%m-%d')}** | 回测中BTC从此日起参与 |\n")
            msg.write("\n**目标权重:**\n\n")
            msg.write("| 资产 | 标签 | 权重 | 类别 |\n")
            msg.write("|:-----|:-----|-----:|:-----|\n")
            for name, cfg in PROD_PORTFOLIO.items():
                msg.write(f"| {name} | {cfg['label']} | {cfg['w']:.0%} | {cfg['cls']} |\n")
            msg.write("\n**计算过程:**\n")
            msg.write("1. 买入并持有全部7只ETF，按目标权重配置\n")
            msg.write("2. 日常无操作，持仓随市场波动自然漂移\n")
            msg.write("3. 每年12月再平衡: 卖出超配、买入低配，恢复目标权重\n")
            msg.write("4. 回测中BTC从2022年起参与（避免早期极端波动影响指标），实盘始终包含\n")

            msg.write("\n---\n\n")

            # ---- Combined ----
            msg.write("### 组合方式\n\n")
            msg.write("| 参数 | 值 |\n")
            msg.write("|:-----|:---|\n")
            for name, w in COMBINED_WEIGHTS.items():
                msg.write(f"| {name}权重 | **{w:.1%}** |\n")
            msg.write("| 合并方式 | 加权合并，月度对齐收益率 |\n")

    # ----------------------------------------------------------
    # Live parameters handler (fetches data, shows real-time computed values)
    # ----------------------------------------------------------
    def _handle_live_params(self):
        with poe.start_message() as msg:
            cn_close, cn_dk_close, us_rot_close, us_prod_daily = self._fetch_data(msg)
            msg.write("⏳ 正在计算实时参数...\n")

        cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details = \
            self._run_strategies(cn_close, cn_dk_close, us_rot_close, us_prod_daily)

        with poe.start_message() as msg:
            cn_date = cn_close.index[-1]
            us_date = us_rot_close.index[-1]
            cn_close_bj = beijing_time_str(cn_date, "CN", "close")
            us_close_bj = beijing_time_str(us_date, "US", "close")

            # Timestamp + market status
            cn_open, bj_now = is_cn_market_open()
            us_open, _ = is_us_market_open()
            cn_data_is_today = (cn_date.date() == bj_now.date())
            us_data_is_today = (us_date.date() == bj_now.date()) or \
                (us_date.date() == (bj_now - timedelta(days=1)).date() and bj_now.hour < 6)
            any_live = (cn_open and cn_data_is_today) or (us_open and us_data_is_today)

            bj_ts = bj_now.strftime('%Y-%m-%d %H:%M')
            msg.write(f"## 📐 实时参数值\n\n")
            if any_live:
                live_mkts = []
                if cn_open and cn_data_is_today:
                    live_mkts.append("A股")
                if us_open and us_data_is_today:
                    live_mkts.append("美股")
                msg.write(f"⏱ **北京时间 {bj_ts}** 实时数据快照"
                         f"（{'、'.join(live_mkts)}盘中，收盘前参数可能变化）\n\n")
            else:
                msg.write(f"⏱ **北京时间 {bj_ts}** 基于收盘数据\n\n")

            msg.write(f"A股收盘: {cn_close_bj} | "
                      f"美股收盘: {us_close_bj}\n\n")

            # ============ Sub-A ============
            msg.write("### Sub-A: A股轮动\n\n")

            # Step 1-2: momentum & vol for each ETF
            momentum_cn = cn_close.div(cn_close.shift(CN_LOOKBACK)).sub(1)
            abs_mom_cn = cn_close.div(cn_close.shift(CN_ABS_MOM_LB)).sub(1)
            vol_rank_cn = cn_close.pct_change().rolling(CN_VOL_RANK_LB).std() * np.sqrt(CN_TRADING_DAYS)

            mom_vals = momentum_cn.iloc[-1][CN_STOCK_CODES].dropna()
            vol_vals = vol_rank_cn.iloc[-1][CN_STOCK_CODES].dropna()
            abs_vals = abs_mom_cn.iloc[-1][CN_STOCK_CODES].dropna()
            common = mom_vals.index.intersection(vol_vals.index)

            msg.write("**① 动量 & 波动率 & 风险调整得分:**\n\n")
            msg.write(f"| ETF | {CN_LOOKBACK}日动量 | {CN_VOL_RANK_LB}日年化波动率 | "
                      f"score=mom/vol | {CN_ABS_MOM_LB}日绝对动量 |\n")
            msg.write("|:----|------:|------:|------:|------:|\n")

            # Compute scores
            scores = {}
            for code in common:
                m = mom_vals[code]
                v = vol_vals[code]
                s = m / v if v > 0.001 else float("nan")
                scores[code] = s

            # Sort by score descending
            sorted_codes = sorted(common, key=lambda c: scores.get(c, float("-inf")), reverse=True)
            for rank, code in enumerate(sorted_codes, 1):
                name = CN_NAMES.get(code, code)
                m = mom_vals[code]
                v = vol_vals[code]
                s = scores[code]
                a = abs_vals.get(code, float("nan"))
                af = "✅" if (not np.isnan(a) and a > 0) else "❌"
                rank_marker = " 🏆" if rank == 1 else ""
                s_str = f"{s:.2f}" if not np.isnan(s) else "N/A"
                msg.write(f"| {rank}. {name}{rank_marker} | {m:+.2%} | {v:.1%} | {s_str} | {a:+.2%} {af} |\n")

            # Step 3: Winner selection
            best_code = sorted_codes[0] if sorted_codes else None
            if best_code:
                best_name = CN_NAMES.get(best_code, best_code)
                best_abs = abs_vals.get(best_code, float("nan"))
                passed = not np.isnan(best_abs) and best_abs > 0
                msg.write(f"\n**② 选股结果:** score最高 → **{best_name}** (score={scores[best_code]:.2f})\n")
                msg.write(f"**③ 绝对动量过滤:** {CN_ABS_MOM_LB}日动量 = {best_abs:+.2%} → "
                          f"{'**通过** ✅ → 持有{}'.format(best_name) if passed else '**未通过** ❌ → 持有Cash'}\n")

            msg.write("\n---\n\n")

            # ============ Sub-A-DK ============
            msg.write("### Sub-A-DK: 中证1000/上证50多空\n\n")
            dk_mom_lb = cn_dk_close.pct_change(CN_DK_MOM_LB)
            dk_zz1000_mom = dk_mom_lb.iloc[-1].get(CN_DK_COLS[0], np.nan)
            dk_sz50_mom = dk_mom_lb.iloc[-1].get(CN_DK_COLS[1], np.nan)
            dk_holding = cn_dk_result["holding"].iloc[-1]
            dk_short = CN_DK_COLS[1] if dk_holding == CN_DK_COLS[0] else CN_DK_COLS[0]
            dk_holding_name = CN_DK_NAMES.get(dk_holding, dk_holding)
            dk_short_name = CN_DK_NAMES.get(dk_short, dk_short)

            msg.write("**多空动量比较:**\n\n")
            msg.write(f"| 指标 | 值 |\n")
            msg.write(f"|:-----|------:|\n")
            msg.write(f"| 中证1000 {CN_DK_MOM_LB}日动量 | {dk_zz1000_mom:+.2%} |\n")
            msg.write(f"| 上证50 {CN_DK_MOM_LB}日动量 | {dk_sz50_mom:+.2%} |\n")
            msg.write(f"| 当前做多 | **{dk_holding_name}** |\n")
            msg.write(f"| 当前做空 | **{dk_short_name}** |\n")
            winner = "中证1000" if dk_zz1000_mom > dk_sz50_mom else "上证50"
            msg.write(f"| 动量优胜 | **{winner}** (做多方) |\n")

            msg.write("\n---\n\n")

            # ============ Sub-B ============
            msg.write("### Sub-B: 美股9ETF轮动\n\n")

            momentum_us = us_rot_close.div(us_rot_close.shift(US_ROT_LB)).sub(1)
            vol_us = us_rot_close.pct_change().rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)

            # 与信号handler假设计算一致: 用当天数据 iloc[-1]
            mom_row = momentum_us.iloc[-1]
            vol_row = vol_us.iloc[-1]

            msg.write("**① 动量排名 & 波动率:**\n\n")
            msg.write(f"| ETF | {US_ROT_LB}日动量 | {US_ROT_VOL_LB}日年化波动率 | Top3? | 绝对动量>0? |\n")
            msg.write("|:----|------:|------:|:----:|:----:|\n")

            # Compute available & sort
            us_avail = {}
            for a in US_ROT_POOL:
                if a in mom_row.index and not np.isnan(mom_row[a]) and a in vol_row.index and not np.isnan(vol_row[a]) and vol_row[a] > 0.001:
                    us_avail[a] = mom_row[a]
            us_sorted = sorted(us_avail.items(), key=lambda x: x[1], reverse=True)
            top3_codes = [a for a, _ in us_sorted[:3]]
            for rank, (a, m) in enumerate(us_sorted, 1):
                live_name = _ROT_PROXY_TO_LIVE.get(a, a)
                v = vol_row[a]
                is_top3 = "✅" if a in top3_codes else ""
                abs_pass = "✅" if m > US_ROT_ABS_THRESHOLD else "❌"
                rank_marker = " 🏆" if rank <= 3 else ""
                msg.write(f"| {rank}. {live_name}{rank_marker} | {m:+.2%} | {v:.1%} | {is_top3} | {abs_pass} |\n")

            # Step 2: Inv-vol raw weights (use _us_raw_weights for consistency)
            raw_w = _us_raw_weights(mom_row, vol_row, US_ROT_POOL, 3, US_ROT_ABS_THRESHOLD)
            msg.write(f"\n**② Top3 反波动率加权 (1/vol):**\n\n")
            passed_top3 = [a for a in top3_codes if us_avail.get(a, 0) > US_ROT_ABS_THRESHOLD]
            failed_top3 = [a for a in top3_codes if us_avail.get(a, 0) <= US_ROT_ABS_THRESHOLD]
            bil_share = len(failed_top3) / 3 if top3_codes else 0

            if passed_top3:
                iv = {a: 1.0 / vol_row[a] for a in passed_top3}
                total_iv = sum(iv.values())
                risky_share = 1.0 - bil_share
                msg.write("| ETF | 1/vol | 原始权重 |\n")
                msg.write("|:----|------:|------:|\n")
                for a in passed_top3:
                    live_name = _ROT_PROXY_TO_LIVE.get(a, a)
                    w = (iv[a] / total_iv) * risky_share
                    msg.write(f"| {live_name} | {iv[a]:.1f} | {w:.1%} |\n")
            if failed_top3:
                msg.write(f"| BIL(未达标{len(failed_top3)}只) | — | {bil_share:.1%} |\n")

            # Step 3: Vol scaling
            hist_us = us_rot_result["return"].values
            if len(hist_us) >= US_ROT_VOL_WINDOW:
                us_rv = np.std(hist_us[-US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
                us_scale = min(max(US_ROT_TARGET_VOL / us_rv, 0.05), US_ROT_MAX_LEV) if us_rv > 0.001 else US_ROT_MAX_LEV
            else:
                us_rv = 0.0
                us_scale = 1.0

            msg.write(f"\n**③ 波动率缩放 (Model B):** 近{US_ROT_VOL_WINDOW}日已实现波动率 = {us_rv:.1%}，"
                      f"scale = {US_ROT_TARGET_VOL:.0%}/{us_rv:.1%} = **{us_scale:.2f}x**")
            if us_scale > 1.0:
                msg.write(f" (>1: 仅放大期货类ETF，上限{US_ROT_MAX_LEV:.1f}x)")
            elif us_scale < 1.0:
                msg.write(" (<1: 所有资产等比缩减)")
            msg.write("\n")

            # Step 4: Hypothetical final weights (same calc as signal handler)
            hypo_w = _us_model_b(raw_w, us_scale)
            if US_ROT_BTC_MAX_W is not None:
                hypo_w = _apply_btc_cap(hypo_w, US_ROT_BTC_TICKER, US_ROT_BTC_MAX_W)
            msg.write(f"\n**④ 假设信号权重 (缩放+BTC上限后):**\n\n")
            msg.write("| ETF | 权重 |\n|:----|------:|\n")
            for a in sorted(hypo_w.keys(), key=lambda x: hypo_w[x], reverse=True):
                if hypo_w[a] < 0.001:
                    continue
                live_name = _ROT_PROXY_TO_LIVE.get(a, a)
                msg.write(f"| {live_name} | {hypo_w[a]:.1%} |\n")

            msg.write("\n---\n\n")

            # ============ Sub-C ============
            msg.write("### Sub-C: 美股7ETF生产组合\n\n")
            msg.write("**纯买入持有 + 年度12月再平衡**，无实时计算参数。\n\n")
            msg.write("| 资产 | 目标权重 | 类别 |\n")
            msg.write("|:-----|------:|:-----|\n")
            for name, cfg in PROD_PORTFOLIO.items():
                msg.write(f"| {name} | {cfg['w']:.0%} | {cfg['cls']} |\n")
            msg.write(f"\n下次再平衡: **{datetime.now().year}年12月**"
                      f"（若已过则{datetime.now().year + 1}年12月）\n")

            msg.write("\n---\n\n")

            # ============ Combined ============
            msg.write("### 组合权重\n\n")
            msg.write("| 策略 | 权重 |\n|:-----|------:|\n")
            for name, w in COMBINED_WEIGHTS.items():
                msg.write(f"| {name} | {w:.0%} |\n")

    # ----------------------------------------------------------
    # NAV chart handler
    # ----------------------------------------------------------
    def _handle_nav_chart(self, query):
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        start_date, end_date = parse_date_range(query)
        if start_date is None:
            raise poe.BotError(
                "无法解析日期范围。支持的格式示例：\n"
                "- 净值曲线 今年 / 去年\n"
                "- 净值曲线 过去两年 / 最近6个月\n"
                "- 净值曲线 2024-01到2025-01\n"
                "- 净值曲线 2024至今\n"
                "- 净值曲线 2024年"
            )

        with poe.start_message() as msg:
            cn_close, cn_dk_close, us_rot_close, us_prod_daily = self._fetch_data(msg)
            msg.write("⏳ 正在计算策略净值...\n")

        cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details = \
            self._run_strategies(cn_close, cn_dk_close, us_rot_close, us_prod_daily)

        # --- Compute daily returns for each sub-strategy ---
        cn_daily_ret = cn_result["return"]
        dk_daily_ret = cn_dk_result["return"]
        us_daily_ret = us_rot_result["return"]
        subc_daily_ret = _compute_daily_subc_phased(
            us_prod_daily, prod_sig_a, PROD_CASH,
            prod_sig_b=prod_sig_b, blend_a=PROD_BLEND_A)

        # --- Filter to date range ---
        cn_period = cn_daily_ret[(cn_daily_ret.index >= start_date) & (cn_daily_ret.index <= end_date)]
        dk_period = dk_daily_ret[(dk_daily_ret.index >= start_date) & (dk_daily_ret.index <= end_date)]
        us_period = us_daily_ret[(us_daily_ret.index >= start_date) & (us_daily_ret.index <= end_date)]
        subc_period = subc_daily_ret[(subc_daily_ret.index >= start_date) & (subc_daily_ret.index <= end_date)]

        if len(cn_period) < 2 and len(us_period) < 2:
            raise poe.BotError(f"在 {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')} 期间数据不足")

        # --- Build daily NAV (normalized to 1.0 at start) ---
        nav_series = {}
        if len(cn_period) > 1:
            nav_a = (1 + cn_period).cumprod()
            nav_a = nav_a / nav_a.iloc[0]
            nav_series["Sub-A"] = nav_a
        if len(dk_period) > 1:
            nav_dk = (1 + dk_period).cumprod()
            nav_dk = nav_dk / nav_dk.iloc[0]
            nav_series["Sub-A-DK"] = nav_dk
        if len(us_period) > 1:
            nav_b = (1 + us_period).cumprod()
            nav_b = nav_b / nav_b.iloc[0]
            nav_series["Sub-B"] = nav_b
        if len(subc_period) > 1:
            nav_c = (1 + subc_period).cumprod()
            nav_c = nav_c / nav_c.iloc[0]
            nav_series["Sub-C"] = nav_c

        # Combined: NAV加权合成(买入持有, 非每日再平衡)
        # P0-4: 动态权重归一化 — 缺失策略的权重按比例分配给有数据的策略
        if len(nav_series) >= 2:
            cw = COMBINED_WEIGHTS
            all_nav_dates = sorted(set().union(*(s.index for s in nav_series.values())))
            nav_df = pd.DataFrame({
                name: s.reindex(pd.DatetimeIndex(all_nav_dates)).ffill()
                for name, s in nav_series.items()
            })
            # 动态权重: 每日按有数据的策略重新归一化权重
            weight_df = nav_df.notna().astype(float)
            for col in weight_df.columns:
                weight_df[col] *= cw.get(col, 0)
            weight_sum = weight_df.sum(axis=1).replace(0, np.nan)
            weight_df = weight_df.div(weight_sum, axis=0)
            nav_df = nav_df.fillna(0)  # NaN策略贡献0, 权重已归一化到其他策略
            nav_comb = (nav_df * weight_df).sum(axis=1)
            nav_comb = nav_comb / nav_comb.iloc[0]
            nav_series["Combined"] = nav_comb

        if not nav_series:
            raise poe.BotError("无法计算该时段的净值曲线")

        # --- Draw chart (English labels — no CJK fonts in execution env) ---
        colors = {
            "Sub-A": "#E74C3C",    # red
            "Sub-A-DK": "#9B59B6", # purple
            "Sub-B": "#2980B9",    # blue
            "Sub-C": "#27AE60",    # green
            "Combined": "#F39C12", # orange/gold
        }
        chart_labels = {
            "Sub-A": "Sub-A (CN Long)",
            "Sub-A-DK": "Sub-A-DK (CN Long-Short)",
            "Sub-B": "Sub-B (US Rotation)",
            "Sub-C": "Sub-C (US Production)",
            "Combined": f"Combined ({int(COMBINED_WEIGHTS['Sub-A']*100)}/{int(COMBINED_WEIGHTS['Sub-A-DK']*100)}/{int(COMBINED_WEIGHTS['Sub-B']*100)}/{int(COMBINED_WEIGHTS['Sub-C']*100)})",
        }
        labels = {
            "Sub-A": "Sub-A (A股做多)",
            "Sub-A-DK": "Sub-A-DK (多空)",
            "Sub-B": "Sub-B (美股轮动)",
            "Sub-C": "Sub-C (生产组合)",
            "Combined": f"组合 ({int(COMBINED_WEIGHTS['Sub-A']*100)}/{int(COMBINED_WEIGHTS['Sub-A-DK']*100)}/{int(COMBINED_WEIGHTS['Sub-B']*100)}/{int(COMBINED_WEIGHTS['Sub-C']*100)})",
        }

        fig, ax = plt.subplots(figsize=(12, 6))
        for name, nav in nav_series.items():
            ax.plot(nav.index, nav.values,
                    label=f"{chart_labels[name]}  ({(nav.iloc[-1]-1)*100:+.1f}%)",
                    color=colors[name], linewidth=1.8)

        ax.axhline(y=1.0, color='gray', linestyle='--', linewidth=0.8, alpha=0.5)
        ax.set_title(
            f"NAV Curve: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            fontsize=14, fontweight='bold')
        ax.set_ylabel("NAV (start=1.0)", fontsize=11)
        ax.legend(loc='best', fontsize=10, framealpha=0.9)
        ax.grid(True, alpha=0.3)

        # Format x-axis dates
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        fig.autofmt_xdate(rotation=30)
        fig.tight_layout()

        # --- Save to bytes ---
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        chart_bytes = buf.read()

        # --- Compute max drawdown for each series ---
        max_dd = {}
        for name, nav in nav_series.items():
            drawdown = (nav - nav.cummax()) / nav.cummax()
            max_dd[name] = drawdown.min() * 100  # as percentage

        # --- Output ---
        period_label = f"{start_date.strftime('%Y-%m-%d')}至{end_date.strftime('%Y-%m-%d')}"
        with poe.start_message() as msg:
            msg.write(f"## 📈 净值曲线: {period_label}\n\n")

            # Summary table
            msg.write("| 策略 | 期末净值 | 区间收益 | 最大回撤 |\n")
            msg.write("|:-----|--------:|---------:|---------:|\n")
            for name in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C", "Combined"]:
                if name in nav_series:
                    final_nav = nav_series[name].iloc[-1]
                    ret = (final_nav - 1) * 100
                    dd = max_dd[name]
                    display = labels[name]
                    msg.write(f"| {display} | {final_nav:.4f} | {ret:+.2f}% | {dd:.2f}% |\n")
            msg.write("\n")

            msg.attach_file(
                name=f"nav_chart_{datetime.now().strftime('%Y%m%d')}.png",
                contents=chart_bytes,
                content_type="image/png",
                is_inline=True,
            )

    # ----------------------------------------------------------
    # Performance handler
    # ----------------------------------------------------------
    def _handle_performance(self, query, _forced_range=None):
        if _forced_range:
            start_date, end_date = _forced_range
        else:
            start_date, end_date = parse_date_range(query)
        if start_date is None:
            raise poe.BotError(
                "无法解析日期范围。支持的格式示例：\n"
                "- 表现 今年 / 去年\n"
                "- 表现 过去两年 / 最近6个月\n"
                "- 表现 2024-01到2025-01\n"
                "- 表现 2024至今\n"
                "- 表现 2024年"
            )

        with poe.start_message() as msg:
            cn_close, cn_dk_close, us_rot_close, us_prod_daily = self._fetch_data(msg)
            msg.write("⏳ 正在计算策略...\n")

        cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details = \
            self._run_strategies(cn_close, cn_dk_close, us_rot_close, us_prod_daily)

        # --- Convert to monthly returns and align ---
        cn_monthly = cn_result["return"].groupby(cn_result.index.to_period("M")).apply(
            lambda x: (1+x).prod()-1)
        dk_monthly = cn_dk_result["return"].groupby(cn_dk_result.index.to_period("M")).apply(
            lambda x: (1+x).prod()-1)
        us_rot_monthly = us_rot_result["return"].groupby(us_rot_result.index.to_period("M")).apply(
            lambda x: (1+x).prod()-1)
        prod_monthly_ret = prod_nav.pct_change().dropna()
        prod_monthly_ret.index = prod_monthly_ret.index.to_period("M")

        # Align all four
        all_periods = cn_monthly.index.intersection(dk_monthly.index).intersection(
            us_rot_monthly.index).intersection(prod_monthly_ret.index)
        if len(all_periods) == 0:
            raise poe.BotError("四个策略没有重叠的月度数据")

        aligned = pd.DataFrame({
            "Sub-A": cn_monthly.reindex(all_periods),
            "Sub-A-DK": dk_monthly.reindex(all_periods),
            "Sub-B": us_rot_monthly.reindex(all_periods),
            "Sub-C": prod_monthly_ret.reindex(all_periods),
        }).dropna()

        # Combined: P0-4 — NAV加权合成(买入持有), 与日度/图表口径一致
        # 从月度收益构建各策略累计NAV, 再按初始权重加总(非每月再平衡)
        w = COMBINED_WEIGHTS
        _strat_cols = ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]
        _nav_monthly = (1 + aligned[_strat_cols]).cumprod()
        _nav_comb = sum(_nav_monthly[n] * w[n] for n in _strat_cols)
        _nav_comb = _nav_comb / _nav_comb.iloc[0]
        aligned["Combined"] = _nav_comb.pct_change()
        aligned.loc[aligned.index[0], "Combined"] = _nav_comb.iloc[0] - 1

        # Filter to date range
        start_period = start_date.to_period("M")
        end_period = end_date.to_period("M")
        mask = (aligned.index >= start_period) & (aligned.index <= end_period)
        filtered = aligned[mask]

        # --- Individual strategy monthly data (each uses its OWN full range) ---
        cn_monthly_period = cn_monthly[
            (cn_monthly.index >= start_period) & (cn_monthly.index <= end_period)]
        dk_monthly_period = dk_monthly[
            (dk_monthly.index >= start_period) & (dk_monthly.index <= end_period)]
        us_monthly_period = us_rot_monthly[
            (us_rot_monthly.index >= start_period) & (us_rot_monthly.index <= end_period)]
        prod_monthly_period = prod_monthly_ret[
            (prod_monthly_ret.index >= start_period) & (prod_monthly_ret.index <= end_period)]

        if len(cn_monthly_period) < 1 and len(us_monthly_period) < 1:
            raise poe.BotError(f"在 {start_date.strftime('%Y-%m')} 到 {end_date.strftime('%Y-%m')} 期间没有数据")

        # Calculate metrics — each strategy uses its OWN data range
        metrics = {}
        if len(cn_monthly_period) >= 1:
            metrics["Sub-A"] = calc_monthly_metrics(cn_monthly_period)
        if len(dk_monthly_period) >= 1:
            metrics["Sub-A-DK"] = calc_monthly_metrics(dk_monthly_period)
        if len(us_monthly_period) >= 1:
            metrics["Sub-B"] = calc_monthly_metrics(us_monthly_period)
        if len(prod_monthly_period) >= 1:
            metrics["Sub-C"] = calc_monthly_metrics(prod_monthly_period)
        # Combined: only meaningful over the intersection period
        if len(filtered) >= 1:
            metrics["Combined"] = calc_monthly_metrics(filtered["Combined"])

        # --- Override max drawdown using daily data (more precise than monthly) ---
        cn_daily_period = cn_result["return"][
            (cn_result.index >= start_date) & (cn_result.index <= end_date)]
        if len(cn_daily_period) > 1 and "Sub-A" in metrics:
            nav_a = (1 + cn_daily_period).cumprod()
            metrics["Sub-A"]["max_dd"] = ((nav_a - nav_a.cummax()) / nav_a.cummax()).min() * 100

        dk_daily_period = cn_dk_result["return"][
            (cn_dk_result.index >= start_date) & (cn_dk_result.index <= end_date)]
        if len(dk_daily_period) > 1 and "Sub-A-DK" in metrics:
            nav_dk = (1 + dk_daily_period).cumprod()
            metrics["Sub-A-DK"]["max_dd"] = ((nav_dk - nav_dk.cummax()) / nav_dk.cummax()).min() * 100

        us_daily_period = us_rot_result["return"][
            (us_rot_result.index >= start_date) & (us_rot_result.index <= end_date)]
        if len(us_daily_period) > 1 and "Sub-B" in metrics:
            nav_b = (1 + us_daily_period).cumprod()
            metrics["Sub-B"]["max_dd"] = ((nav_b - nav_b.cummax()) / nav_b.cummax()).min() * 100

        subc_daily = _compute_daily_subc_phased(us_prod_daily, prod_sig_a, PROD_CASH,
                                                prod_sig_b=prod_sig_b, blend_a=PROD_BLEND_A)
        subc_period = subc_daily[
            (subc_daily.index >= start_date) & (subc_daily.index <= end_date)]
        if len(subc_period) > 1 and "Sub-C" in metrics:
            nav_c = (1 + subc_period).cumprod()
            metrics["Sub-C"]["max_dd"] = ((nav_c - nav_c.cummax()) / nav_c.cummax()).min() * 100

        # Combined daily — only from when ALL strategies have data
        comb_daily = None
        common_start = start_date
        if len(cn_daily_period) > 0:
            common_start = max(common_start, cn_daily_period.index[0])
        if len(dk_daily_period) > 0:
            common_start = max(common_start, dk_daily_period.index[0])
        if len(us_daily_period) > 0:
            common_start = max(common_start, us_daily_period.index[0])
        if len(subc_period) > 0:
            common_start = max(common_start, subc_period.index[0])
        if "Combined" in metrics:
            # NAV加权合成(买入持有, 非每日再平衡) — 与 nav_chart 一致
            nav_parts = {}
            for sname, dret in [("Sub-A", cn_daily_period), ("Sub-A-DK", dk_daily_period), ("Sub-B", us_daily_period), ("Sub-C", subc_period)]:
                if len(dret) > 1:
                    nv = (1 + dret).cumprod()
                    nav_parts[sname] = nv / nv.iloc[0]
            if len(nav_parts) >= 2:
                cw = COMBINED_WEIGHTS
                all_daily_dates = sorted(set().union(*(s.index for s in nav_parts.values())))
                all_daily_dates = [d for d in all_daily_dates if d >= common_start]
                if len(all_daily_dates) > 1:
                    nav_df = pd.DataFrame({
                        n: s.reindex(pd.DatetimeIndex(all_daily_dates)).ffill()
                        for n, s in nav_parts.items()
                    })
                    # P0-4: 动态权重归一化 — 与 nav_chart 一致
                    _wdf = nav_df.notna().astype(float)
                    for _c in _wdf.columns:
                        _wdf[_c] *= cw.get(_c, 0)
                    _ws = _wdf.sum(axis=1).replace(0, np.nan)
                    _wdf = _wdf.div(_ws, axis=0)
                    nav_df_filled = nav_df.fillna(0)
                    nav_comb = (nav_df_filled * _wdf).sum(axis=1)
                    nav_comb = nav_comb / nav_comb.iloc[0]
                    metrics["Combined"]["max_dd"] = (
                        (nav_comb - nav_comb.cummax()) / nav_comb.cummax()).min() * 100
                    # 从NAV反推日收益率, 供周胜率计算
                    comb_daily = nav_comb.pct_change().dropna()

        # --- Override total_return / annual / calmar from daily data (match chart) ---
        # Monthly metrics cover full calendar months, but daily data starts from
        # the exact start_date (possibly mid-month).  The chart legend shows
        # cumulative return from daily NAV, so we align the table to match.
        for _sname, _dret in [
            ("Sub-A", cn_daily_period), ("Sub-A-DK", dk_daily_period),
            ("Sub-B", us_daily_period), ("Sub-C", subc_period),
        ]:
            if _sname in metrics and len(_dret) > 1:
                _nav_d = (1 + _dret).cumprod()
                _total = (_nav_d.iloc[-1] / _nav_d.iloc[0] - 1) * 100
                metrics[_sname]["total_return"] = _total
                _ndays = (_dret.index[-1] - _dret.index[0]).days
                if _ndays > 0:
                    _ann = ((_nav_d.iloc[-1] / _nav_d.iloc[0]) ** (365.25 / _ndays) - 1) * 100
                    metrics[_sname]["annual"] = _ann
                    _mdd = metrics[_sname]["max_dd"]
                    metrics[_sname]["calmar"] = _ann / abs(_mdd) if _mdd != 0 else 0
        if "Combined" in metrics and comb_daily is not None and len(comb_daily) > 1:
            _nav_d = (1 + comb_daily).cumprod()
            _total = (_nav_d.iloc[-1] / _nav_d.iloc[0] - 1) * 100
            metrics["Combined"]["total_return"] = _total
            _ndays = (comb_daily.index[-1] - comb_daily.index[0]).days
            if _ndays > 0:
                _ann = ((_nav_d.iloc[-1] / _nav_d.iloc[0]) ** (365.25 / _ndays) - 1) * 100
                metrics["Combined"]["annual"] = _ann
                _mdd = metrics["Combined"]["max_dd"]
                metrics["Combined"]["calmar"] = _ann / abs(_mdd) if _mdd != 0 else 0

        # Build Excel monthly data from individual strategies (not just intersection)
        excel_monthly = pd.DataFrame({
            "Sub-A": cn_monthly_period,
            "Sub-A-DK": dk_monthly_period,
            "Sub-B": us_monthly_period,
            "Sub-C": prod_monthly_period,
        }).sort_index()
        if len(filtered) > 0:
            excel_monthly["Combined"] = filtered["Combined"].reindex(excel_monthly.index)
        else:
            excel_monthly["Combined"] = np.nan

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
                ("Sub-A-DK", dk_daily_period),
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
        dk_rebs = extract_dk_rebalances(cn_dk_result)
        all_rebalances.extend([r for r in dk_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])
        us_rebs = extract_us_rot_rebalances(us_rot_result)
        all_rebalances.extend([r for r in us_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])
        prod_rebs = extract_prod_rebalances(prod_details, prod_monthly, include_no_change=True)
        all_rebalances.extend([r for r in prod_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])
        _mark_tentative_records(all_rebalances)
        all_rebalances.sort(key=lambda x: x["日期"])

        # ==============================================================
        # GENERATE NAV CHART
        # ==============================================================
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        nav_series = {}
        if len(cn_daily_period) > 1:
            _nav_a = (1 + cn_daily_period).cumprod()
            nav_series["Sub-A"] = _nav_a / _nav_a.iloc[0]
        if len(dk_daily_period) > 1:
            _nav_dk = (1 + dk_daily_period).cumprod()
            nav_series["Sub-A-DK"] = _nav_dk / _nav_dk.iloc[0]
        if len(us_daily_period) > 1:
            _nav_b = (1 + us_daily_period).cumprod()
            nav_series["Sub-B"] = _nav_b / _nav_b.iloc[0]
        if len(subc_period) > 1:
            _nav_c = (1 + subc_period).cumprod()
            nav_series["Sub-C"] = _nav_c / _nav_c.iloc[0]
        if comb_daily is not None and len(comb_daily) > 1:
            _nav_comb = (1 + comb_daily).cumprod()
            nav_series["Combined"] = _nav_comb / _nav_comb.iloc[0]

        chart_bytes = None
        if nav_series:
            colors = {
                "Sub-A": "#E74C3C", "Sub-A-DK": "#9B59B6",
                "Sub-B": "#2980B9", "Sub-C": "#27AE60", "Combined": "#F39C12",
            }
            chart_labels = {
                "Sub-A": "Sub-A (CN Long)",
                "Sub-A-DK": "Sub-A-DK (CN Long-Short)",
                "Sub-B": "Sub-B (US Rotation)",
                "Sub-C": "Sub-C (US Production)",
                "Combined": f"Combined ({int(COMBINED_WEIGHTS['Sub-A']*100)}/{int(COMBINED_WEIGHTS['Sub-A-DK']*100)}/{int(COMBINED_WEIGHTS['Sub-B']*100)}/{int(COMBINED_WEIGHTS['Sub-C']*100)})",
            }
            fig, ax = plt.subplots(figsize=(12, 6))
            for name, nav in nav_series.items():
                ax.plot(nav.index, nav.values,
                        label=f"{chart_labels[name]}  ({(nav.iloc[-1]-1)*100:+.1f}%)",
                        color=colors[name], linewidth=1.8)
            ax.axhline(y=1.0, color='gray', linestyle='--', linewidth=0.8, alpha=0.5)
            ax.set_title(
                f"NAV Curve: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
                fontsize=14, fontweight='bold')
            ax.set_ylabel("NAV (start=1.0)", fontsize=11)
            ax.legend(loc='best', fontsize=10, framealpha=0.9)
            ax.grid(True, alpha=0.3)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            fig.autofmt_xdate(rotation=30)
            fig.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            chart_bytes = buf.read()

        # ==============================================================
        # OUTPUT PERFORMANCE TEXT
        # ==============================================================
        with poe.start_message() as msg:
            msg.write(f"## 📈 策略表现: {start_date.strftime('%Y-%m')} 至 {end_date.strftime('%Y-%m')}\n\n")

            # Inline NAV chart at top
            if chart_bytes:
                msg.attach_file(
                    name=f"perf_nav_{datetime.now().strftime('%Y%m%d')}.png",
                    contents=chart_bytes,
                    content_type="image/png",
                    is_inline=True,
                )
                msg.write("\n\n")

            # Show actual data ranges if they differ
            range_info = {}
            if len(cn_monthly_period) >= 1:
                range_info["Sub-A"] = (cn_monthly_period.index[0], cn_monthly_period.index[-1])
            if len(dk_monthly_period) >= 1:
                range_info["Sub-A-DK"] = (dk_monthly_period.index[0], dk_monthly_period.index[-1])
            if len(us_monthly_period) >= 1:
                range_info["Sub-B"] = (us_monthly_period.index[0], us_monthly_period.index[-1])
            if len(prod_monthly_period) >= 1:
                range_info["Sub-C"] = (prod_monthly_period.index[0], prod_monthly_period.index[-1])
            if len(filtered) >= 1:
                range_info["Combined"] = (filtered.index[0], filtered.index[-1])
            # Check if ranges differ
            starts = set(v[0] for v in range_info.values())
            if len(starts) > 1:
                msg.write("⚠️ **各策略数据起始日不同:**\n")
                for name in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C", "Combined"]:
                    if name in range_info:
                        s, e = range_info[name]
                        msg.write(f"- {name}: {s} ~ {e}\n")
                msg.write("\n")

            msg.write("| 指标 | Sub-A | A-DK | Sub-B | Sub-C | 组合 |\n")
            msg.write("|:-----|------:|------:|------:|------:|-----:|\n")
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
                for col in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C", "Combined"]:
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
                msg.write("| 年份 | Sub-A | A-DK | Sub-B | Sub-C | 组合 |\n")
                msg.write("|:-----|------:|------:|------:|------:|-----:|\n")
                for yr in sorted(years_available):
                    row = f"| {yr} |"
                    for col in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C", "Combined"]:
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
        excel_bytes = generate_performance_excel(now_str, metrics, excel_monthly, all_rebalances, is_short_period)
        filename = f"performance_{now_str}.xlsx"

        with poe.start_message() as msg:
            msg.attach_file(
                name=filename,
                contents=excel_bytes,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            msg.write(f"📎 绩效报告: **{filename}**")


if __name__ == "__main__":
    bot = CombinedStrategyV4()
    bot.run()

# poe: privacy_shield=half
"""
Combined Portfolio: A-Share + US ETF Momentum Rotation (V2 - Correct US Strategy)
- Sub-strategy A: A-Share 4idx(ZZHL+CYBQZ+HS300+ZZ1000) + SZQZ, LB=20, AM=10
- Sub-strategy B: US 8ETF, LB=120, Top3, VolTarget=20%, MaxLev=1.5, Model B
- Weekly-aligned returns, test various CN/US allocation weights
- A-share from EastMoney, US from Yahoo Finance
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
from datetime import datetime
from matplotlib.colors import TwoSlopeNorm

# Robust HTTP session with retries
def _get_session():
    s = requests.Session()
    retries = Retry(total=5, backoff_factor=1.0,
                    status_forcelist=[500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    return s

_session = _get_session()

# ============================================================
# A-Share Parameters
# ============================================================
CN_COMMISSION = 0.001          # 0.1% per leg
CN_RF_DAILY = (1.03 ** (1/244)) - 1
CN_RF_ANNUAL = 3.0
CN_LOOKBACK = 20
CN_ABS_MOM_LB = 10
CN_TRADING_DAYS = 244

CN_STOCK_CODES = ["1.000922", "0.399102", "1.000300", "1.000852"]
CN_BOND_CODE = "1.000013"  # SZQZ
CN_ALL_CODES = CN_STOCK_CODES + [CN_BOND_CODE]

CN_NAMES = {
    "1.000922": "ZZHL", "0.399102": "CYBQZ",
    "1.000300": "HS300", "1.000852": "ZZ1000",
    "1.000013": "SZQZ", "cash": "Cash",
}

# ============================================================
# US 8ETF Parameters (from user's final_backtest.py)
# ============================================================
US_COMMISSION = 0.001          # 0.1% per unit turnover
US_TRADING_DAYS = 252
US_POOL_8 = ["SPY", "QQQ", "EEM", "EFA", "GLD", "TLT", "VNQ", "DBC"]
US_FUTURES_ELIGIBLE = {"SPY", "QQQ", "GLD", "TLT"}
US_ALL_FETCH = sorted(set(US_POOL_8 + ["BIL"]))
US_TARGET_VOL = 0.20
US_MAX_LEVERAGE = 1.5
US_VOL_WINDOW = 40
US_LOOKBACK = 120
US_VOL_LB = 20

# ============================================================
# Data Fetching
# ============================================================
def fetch_cn_kline(secid):
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
           f"&klt=101&fqt=0&beg=20050101&end=20260301&lmt=10000")
    resp = _session.get(url, timeout=30)
    data = resp.json()
    klines = data["data"]["klines"]
    rows = []
    for line in klines:
        p = line.split(",")
        rows.append({"date": p[0], "close": float(p[2])})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def fetch_yahoo(ticker, start_date="2003-01-01"):
    start_ts = int(pd.Timestamp(start_date).timestamp())
    end_ts = int(pd.Timestamp("2026-03-01").timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={start_ts}&period2={end_ts}&interval=1d&includeAdjustedClose=true")
    resp = _session.get(url, timeout=30)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if "chart" not in data or not data["chart"].get("result"):
        return None
    result = data["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    if not timestamps:
        return None
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


# ============================================================
# A-Share Strategy Engine (LB=20, AM=10, Top1, Thu Close)
# ============================================================
def _cn_get_signal_days(close_df, start_idx):
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


def _cn_cost_factor(old_h, new_h):
    if old_h == "cash":
        legs = 1 if new_h != "cash" else 0
    elif old_h != new_h:
        legs = (1 if old_h != "cash" else 0) + (1 if new_h != "cash" else 0)
    else:
        legs = 0
    return (1 - CN_COMMISSION) ** legs


def run_cn_strategy(close_df, ranking_codes):
    """A-share: 4idx+SZQZ, LB=20, AM=10, Thu close signal"""
    momentum = close_df.div(close_df.shift(CN_LOOKBACK)).sub(1)
    abs_momentum = close_df.div(close_df.shift(CN_ABS_MOM_LB)).sub(1)
    start_idx = max(CN_LOOKBACK, CN_ABS_MOM_LB)
    signal_days = _cn_get_signal_days(close_df, start_idx)
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
            cf = _cn_cost_factor(old_h, target)
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
                     "is_signal": is_signal})

    df = pd.DataFrame(rows).set_index("date")
    df["nav"] = (1 + df["return"]).cumprod()
    df["peak"] = df["nav"].cummax()
    df["drawdown"] = (df["nav"] - df["peak"]) / df["peak"]
    return df


# ============================================================
# US 8ETF Strategy Engine (LB=120, Top3, VolTarget, Model B)
# ============================================================
def _us_get_signal_days(close_df, start_idx):
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


def _us_compute_raw_weights(mom_row, vol_row, ranking_codes, top_n, abs_threshold):
    available = {}
    for asset in ranking_codes:
        if (asset in mom_row.index and not np.isnan(mom_row[asset])
                and asset in vol_row.index and not np.isnan(vol_row[asset])
                and vol_row[asset] > 0.001):
            available[asset] = mom_row[asset]
    top_ranked = sorted(available.items(), key=lambda x: x[1], reverse=True)[:top_n]
    passed, n_failed = [], 0
    for asset, _ in top_ranked:
        if not np.isnan(mom_row.get(asset, np.nan)) and mom_row[asset] > abs_threshold:
            passed.append(asset)
        else:
            n_failed += 1
    if not top_ranked:
        return {"BIL": 1.0}
    bil_w = n_failed / len(top_ranked)
    raw = {}
    if passed:
        iv = {a: 1.0 / vol_row[a] for a in passed}
        total_iv = sum(iv.values())
        share = 1.0 - bil_w
        raw = {a: (v / total_iv) * share for a, v in iv.items()}
    if bil_w > 0:
        raw["BIL"] = bil_w
    return raw


def _us_apply_model_b(raw_weights, scale):
    actual = {}
    if scale <= 1.0:
        for a, w in raw_weights.items():
            if a == "BIL":
                continue
            actual[a] = w * scale
    else:
        fut_sum = sum(w for a, w in raw_weights.items()
                      if a != "BIL" and a in US_FUTURES_ELIGIBLE)
        nf_sum = sum(w for a, w in raw_weights.items()
                     if a != "BIL" and a not in US_FUTURES_ELIGIBLE)
        total_risky = fut_sum + nf_sum
        if total_risky > 0:
            target = total_risky * scale
            fut_target = target - nf_sum
            fs = fut_target / fut_sum if (fut_sum > 0 and fut_target > 0) else 1.0
            for a, w in raw_weights.items():
                if a == "BIL":
                    continue
                actual[a] = w * fs if a in US_FUTURES_ELIGIBLE else w
    risky = sum(actual.values())
    actual["BIL"] = max(1.0 - risky, 0.0)
    return actual


def run_us_strategy(close_df, ranking_codes, top_n=3, abs_threshold=0.03):
    """US 8ETF: LB=120, Top3, VolTarget=20%, ML=1.5, Model B, Comm=0.1%"""
    momentum = close_df.div(close_df.shift(US_LOOKBACK)).sub(1)
    vol_df = close_df.pct_change().rolling(US_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
    start_idx = max(US_LOOKBACK, US_VOL_LB, US_VOL_WINDOW) + 1
    signal_days = _us_get_signal_days(close_df, start_idx)
    raw_w = {"BIL": 1.0}
    act = {"BIL": 1.0}
    scale = 1.0
    w_assets = list(ranking_codes) + (["BIL"] if "BIL" not in ranking_codes else [])
    rows, hist = [], []

    for i in range(start_idx, len(close_df)):
        is_sig = i in signal_days
        comm = 0.0
        to = 0.0
        switched = False
        if len(hist) >= US_VOL_WINDOW:
            rv = np.std(hist[-US_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
            scale = min(max(US_TARGET_VOL / rv, 0.05), US_MAX_LEVERAGE) if rv > 0.001 else US_MAX_LEVERAGE
        if is_sig:
            raw_w = _us_compute_raw_weights(
                momentum.iloc[i-1], vol_df.iloc[i-1], ranking_codes, top_n, abs_threshold)
            new_act = _us_apply_model_b(raw_w, scale)
            prev_a = {a: rows[-1].get(f"w_{a}", 0.0) for a in w_assets} if rows else {"BIL": 1.0}
            all_a = set(list(new_act.keys()) + list(prev_a.keys()))
            to = sum(abs(new_act.get(a, 0) - prev_a.get(a, 0)) for a in all_a if a != "BIL")
            if to > 0:
                comm = to * US_COMMISSION
                switched = True
            act = new_act
        pr = 0.0
        for a, w in act.items():
            if a in close_df.columns:
                pr += w * (close_df.iloc[i][a] / close_df.iloc[i-1][a] - 1)
        adj = (1 + pr) * (1 - comm) - 1
        hist.append(adj)
        risky = sum(w for a, w in act.items() if a != "BIL")
        row = {"date": close_df.index[i], "return": adj, "is_signal": is_sig,
               "switched": switched, "scale": scale, "risky_pct": risky,
               "turnover": to, "comm": comm}
        for a in w_assets:
            row[f"w_{a}"] = act.get(a, 0.0)
        rows.append(row)

    df = pd.DataFrame(rows).set_index("date")
    df["nav"] = (1 + df["return"]).cumprod()
    df["peak"] = df["nav"].cummax()
    df["drawdown"] = (df["nav"] - df["peak"]) / df["peak"]
    return df


# ============================================================
# Portfolio Metrics
# ============================================================
def calc_metrics_daily(ret_series, rf_daily, td):
    """Compute metrics for daily return series."""
    nav = (1 + ret_series).cumprod()
    years = (ret_series.index[-1] - ret_series.index[0]).days / 365.25
    if years < 0.5 or len(ret_series) < 50:
        return None
    annual = (nav.iloc[-1] ** (1/years) - 1) * 100
    excess = ret_series - rf_daily
    sharpe = excess.mean() / excess.std() * np.sqrt(td) if excess.std() > 0 else 0
    vol = ret_series.std() * np.sqrt(td) * 100
    peak = nav.cummax()
    dd_series = (nav - peak) / peak
    dd = dd_series.min() * 100
    calmar = annual / abs(dd) if dd != 0 else 0
    monthly = ret_series.groupby(ret_series.index.to_period("M")).apply(lambda x: (1+x).prod()-1)
    win_rate = (monthly > 0).mean() * 100

    yearly = {}
    for year in sorted(ret_series.index.year.unique()):
        yr_data = ret_series[ret_series.index.year == year]
        if len(yr_data) > 10:
            yearly[year] = ((1 + yr_data).prod() - 1) * 100

    return {
        "annual": annual, "vol": vol, "sharpe": sharpe, "max_dd": dd,
        "calmar": calmar, "win_rate": win_rate, "years": years,
        "total_return": (nav.iloc[-1] - 1) * 100, "yearly": yearly,
        "nav": nav, "dd_series": dd_series,
    }


def calc_metrics_weekly(ret_series, rf_weekly):
    """Compute metrics for weekly return series."""
    nav = (1 + ret_series).cumprod()
    years = (ret_series.index[-1] - ret_series.index[0]).days / 365.25
    if years < 0.5 or len(ret_series) < 20:
        return None
    annual = (nav.iloc[-1] ** (1/years) - 1) * 100
    excess = ret_series - rf_weekly
    sharpe = excess.mean() / excess.std() * np.sqrt(52) if excess.std() > 0 else 0
    vol = ret_series.std() * np.sqrt(52) * 100
    peak = nav.cummax()
    dd_series = (nav - peak) / peak
    dd = dd_series.min() * 100
    calmar = annual / abs(dd) if dd != 0 else 0
    monthly = ret_series.groupby(ret_series.index.to_period("M")).apply(lambda x: (1+x).prod()-1)
    win_rate = (monthly > 0).mean() * 100

    yearly = {}
    for year in sorted(ret_series.index.year.unique()):
        yr_data = ret_series[ret_series.index.year == year]
        if len(yr_data) > 3:
            yearly[year] = ((1 + yr_data).prod() - 1) * 100

    return {
        "annual": annual, "vol": vol, "sharpe": sharpe, "max_dd": dd,
        "calmar": calmar, "win_rate": win_rate, "years": years,
        "total_return": (nav.iloc[-1] - 1) * 100, "yearly": yearly,
        "nav": nav, "dd_series": dd_series,
    }


# ============================================================
# Main
# ============================================================
def main():
    today_str = datetime.now().strftime("%Y%m%d")

    # ==========================================================
    # 1. Fetch Data
    # ==========================================================
    cn_raw = {}
    with poe.start_message() as msg:
        msg.write("## 1. Fetching Data\n\n")
        msg.write("**A-Share (EastMoney):**\n")
        for secid in CN_ALL_CODES:
            df = fetch_cn_kline(secid)
            cn_raw[secid] = df
            name = CN_NAMES.get(secid, secid)
            msg.write(f"  > {name}: {len(df)} days "
                     f"{df.index[0].strftime('%Y-%m-%d')}~{df.index[-1].strftime('%Y-%m-%d')}\n")
            time.sleep(0.5)

    cn_close = pd.concat([cn_raw[s].rename(columns={"close": s})
                          for s in CN_ALL_CODES], axis=1).dropna()

    us_raw = {}
    with poe.start_message() as msg:
        msg.write("\n**US ETF (Yahoo Finance):**\n")
        for ticker in US_ALL_FETCH:
            df = fetch_yahoo(ticker)
            if df is not None and len(df) > 100:
                us_raw[ticker] = df
                msg.write(f"  > {ticker}: {len(df)} days "
                         f"{df.index[0].strftime('%Y-%m-%d')}~{df.index[-1].strftime('%Y-%m-%d')}\n")
            else:
                msg.write(f"  > {ticker}: FAILED\n")
            time.sleep(0.5)

    us_close = pd.concat(
        [us_raw[t][["close"]].rename(columns={"close": t}) for t in US_ALL_FETCH if t in us_raw],
        axis=1).ffill().dropna()

    # BIL daily returns for US Sharpe calculation
    bil_daily_ret = us_close["BIL"].pct_change()

    # ==========================================================
    # 2. Run Sub-Strategies
    # ==========================================================
    with poe.start_message() as msg:
        msg.write("\n## 2. Running Sub-Strategies\n\n")
        msg.write("**A-Share**: 4idx(ZZHL+CYBQZ+HS300+ZZ1000)+SZQZ, LB=20, AM=10, Thu Close\n")
        msg.write("**US 8ETF**: SPY+QQQ+EEM+EFA+GLD+TLT+VNQ+DBC, LB=120, Top3, TV=20%, ML=1.5, Model B\n\n")

    cn_result = run_cn_strategy(cn_close, CN_ALL_CODES)
    us_result = run_us_strategy(us_close, US_POOL_8)

    cn_start = cn_result.index[0]
    cn_end = cn_result.index[-1]
    us_start = us_result.index[0]
    us_end = us_result.index[-1]

    # Sub-strategy standalone metrics
    cn_m = calc_metrics_daily(cn_result["return"], CN_RF_DAILY, CN_TRADING_DAYS)

    # US: use BIL daily returns as Rf
    us_rf_aligned = bil_daily_ret.reindex(us_result.index).fillna(0)
    us_excess = us_result["return"] - us_rf_aligned
    us_nav = us_result["nav"]
    us_years = (us_result.index[-1] - us_result.index[0]).days / 365.25
    us_annual = (us_nav.iloc[-1] ** (1/us_years) - 1) * 100
    us_sharpe = us_excess.mean() / us_excess.std() * np.sqrt(US_TRADING_DAYS) if us_excess.std() > 0 else 0
    us_vol = us_result["return"].std() * np.sqrt(US_TRADING_DAYS) * 100
    us_dd = us_result["drawdown"].min() * 100
    us_calmar = us_annual / abs(us_dd) if us_dd != 0 else 0
    us_monthly = us_result["return"].groupby(us_result.index.to_period("M")).apply(lambda x: (1+x).prod()-1)
    us_win_rate = (us_monthly > 0).mean() * 100
    us_yearly = {}
    for year in sorted(us_result.index.year.unique()):
        yr_data = us_result[us_result.index.year == year]["return"]
        if len(yr_data) > 10:
            us_yearly[year] = ((1 + yr_data).prod() - 1) * 100

    us_m = {
        "annual": us_annual, "vol": us_vol, "sharpe": us_sharpe, "max_dd": us_dd,
        "calmar": us_calmar, "win_rate": us_win_rate, "years": us_years,
        "total_return": (us_nav.iloc[-1] - 1) * 100, "yearly": us_yearly,
    }

    # SPY benchmark
    us_bt_start_idx = max(US_LOOKBACK, US_VOL_LB, US_VOL_WINDOW) + 1
    spy_ret = us_close["SPY"].pct_change().iloc[us_bt_start_idx:]
    spy_nav_full = (1 + spy_ret).cumprod()

    with poe.start_message() as msg:
        msg.write(f"**A-Share period**: {cn_start.strftime('%Y-%m-%d')} ~ {cn_end.strftime('%Y-%m-%d')} "
                 f"({len(cn_result)} days)\n")
        msg.write(f"**US 8ETF period**: {us_start.strftime('%Y-%m-%d')} ~ {us_end.strftime('%Y-%m-%d')} "
                 f"({len(us_result)} days)\n\n")

        msg.write(f"**Sub-Strategy Standalone Results:**\n\n")
        msg.write(f"| Metric | A-Share | US 8ETF | SPY |\n")
        msg.write(f"|:-------|--------:|--------:|----:|\n")

        # SPY metrics
        spy_rf = bil_daily_ret.reindex(spy_ret.index).fillna(0)
        spy_excess = spy_ret - spy_rf
        spy_sharpe = spy_excess.mean() / spy_excess.std() * np.sqrt(US_TRADING_DAYS)
        spy_yrs = (spy_nav_full.index[-1] - spy_nav_full.index[0]).days / 365.25
        spy_annual = (spy_nav_full.iloc[-1] ** (1/spy_yrs) - 1) * 100
        spy_dd = ((spy_nav_full / spy_nav_full.cummax()) - 1).min() * 100
        spy_vol = spy_ret.std() * np.sqrt(US_TRADING_DAYS) * 100
        spy_calmar = spy_annual / abs(spy_dd) if spy_dd != 0 else 0

        msg.write(f"| Annual | {cn_m['annual']:.1f}% | {us_m['annual']:.1f}% | {spy_annual:.1f}% |\n")
        msg.write(f"| Sharpe | {cn_m['sharpe']:.3f} | {us_m['sharpe']:.3f} | {spy_sharpe:.3f} |\n")
        msg.write(f"| MaxDD | {cn_m['max_dd']:.1f}% | {us_m['max_dd']:.1f}% | {spy_dd:.1f}% |\n")
        msg.write(f"| Calmar | {cn_m['calmar']:.3f} | {us_m['calmar']:.3f} | {spy_calmar:.3f} |\n")
        msg.write(f"| Vol | {cn_m['vol']:.1f}% | {us_m['vol']:.1f}% | {spy_vol:.1f}% |\n")
        msg.write(f"| WinRate(M) | {cn_m['win_rate']:.1f}% | {us_m['win_rate']:.1f}% | - |\n")
        msg.write(f"| Period | {cn_m['years']:.1f}Y | {us_m['years']:.1f}Y | {spy_yrs:.1f}Y |\n")

    # ==========================================================
    # 3. Build Combined Portfolios (Weekly Aligned)
    # ==========================================================
    cn_weekly = cn_result["return"].groupby(cn_result.index.to_period("W")).apply(
        lambda x: (1+x).prod()-1)
    us_weekly = us_result["return"].groupby(us_result.index.to_period("W")).apply(
        lambda x: (1+x).prod()-1)

    common_weeks = cn_weekly.index.intersection(us_weekly.index)
    cn_w = cn_weekly.loc[common_weeks]
    us_w = us_weekly.loc[common_weeks]

    combined_start = common_weeks[0]
    combined_end = common_weeks[-1]

    with poe.start_message() as msg:
        msg.write(f"\n## 3. Combined Portfolio (Weekly Aligned)\n\n")
        msg.write(f"  Overlap period: {combined_start} ~ {combined_end} ({len(common_weeks)} weeks)\n\n")

    # Correlation
    corr = cn_w.corr(us_w)
    rolling_corr = cn_w.rolling(26).corr(us_w).dropna()

    # Test allocations
    weights = [
        (0.0, 1.0, "US 100%"),
        (0.1, 0.9, "CN10/US90"),
        (0.2, 0.8, "CN20/US80"),
        (0.3, 0.7, "CN30/US70"),
        (0.4, 0.6, "CN40/US60"),
        (0.5, 0.5, "CN50/US50"),
        (0.6, 0.4, "CN60/US40"),
        (0.7, 0.3, "CN70/US30"),
        (0.8, 0.2, "CN80/US20"),
        (0.9, 0.1, "CN90/US10"),
        (1.0, 0.0, "CN 100%"),
    ]

    # Blended weekly Rf (~3.5% annual, using US BIL as proxy)
    bil_weekly = bil_daily_ret.groupby(bil_daily_ret.index.to_period("W")).apply(
        lambda x: (1+x).prod()-1)
    bil_weekly_aligned = bil_weekly.reindex(common_weeks).fillna(0)
    combined_rf_weekly = bil_weekly_aligned.mean()  # Average weekly BIL return

    portfolio_results = {}
    for w_cn, w_us, label in weights:
        port_ret = w_cn * cn_w + w_us * us_w
        port_ret.index = port_ret.index.to_timestamp(how="end")
        m = calc_metrics_weekly(port_ret, combined_rf_weekly)
        if m:
            portfolio_results[label] = {"metrics": m, "w_cn": w_cn, "w_us": w_us}

    # Results table
    with poe.start_message() as msg:
        msg.write("**Allocation Comparison (Overlap Period):**\n\n")
        msg.write(f"| Allocation | Sharpe | Annual | MaxDD | Calmar | Vol | WinRate(M) | Total |\n")
        msg.write(f"|:-----------|-------:|-------:|------:|-------:|----:|-----------:|------:|\n")
        for label, r in portfolio_results.items():
            m = r["metrics"]
            best_sha = max(portfolio_results.values(), key=lambda x: x["metrics"]["sharpe"])["metrics"]["sharpe"]
            bold = "**" if m["sharpe"] == best_sha else ""
            msg.write(f"| {bold}{label}{bold} | {bold}{m['sharpe']:.3f}{bold} | "
                     f"{m['annual']:.1f}% | {m['max_dd']:.1f}% | {m['calmar']:.3f} | "
                     f"{m['vol']:.1f}% | {m['win_rate']:.1f}% | {m['total_return']:.1f}% |\n")

    # Find optimal
    best_label = max(portfolio_results, key=lambda k: portfolio_results[k]["metrics"]["sharpe"])
    best_r = portfolio_results[best_label]
    best_m = best_r["metrics"]

    # Also find best Calmar
    best_calmar_label = max(portfolio_results, key=lambda k: portfolio_results[k]["metrics"]["calmar"])
    best_calmar_m = portfolio_results[best_calmar_label]["metrics"]

    with poe.start_message() as msg:
        msg.write(f"\n**Best Sharpe: {best_label}** → Sharpe={best_m['sharpe']:.3f}, "
                 f"Ann={best_m['annual']:.1f}%, DD={best_m['max_dd']:.1f}%, Calmar={best_m['calmar']:.3f}\n")
        if best_calmar_label != best_label:
            msg.write(f"**Best Calmar: {best_calmar_label}** → Calmar={best_calmar_m['calmar']:.3f}, "
                     f"Sharpe={best_calmar_m['sharpe']:.3f}, Ann={best_calmar_m['annual']:.1f}%, DD={best_calmar_m['max_dd']:.1f}%\n")
        msg.write(f"\n**Correlation (CN vs US weekly): {corr:.3f}**\n")
        msg.write(f"  Rolling 26-week range: [{rolling_corr.min():.3f}, {rolling_corr.max():.3f}], "
                 f"mean={rolling_corr.mean():.3f}\n")

    # ==========================================================
    # 4. Yearly Comparison
    # ==========================================================
    key_labels = ["CN 100%", "CN50/US50", best_label, "US 100%"]
    if best_label in ("CN 100%", "US 100%", "CN50/US50"):
        key_labels = list(dict.fromkeys(key_labels))
    if best_calmar_label not in key_labels and best_calmar_label != best_label:
        key_labels.insert(-1, best_calmar_label)
    key_labels = list(dict.fromkeys(key_labels))

    all_years = sorted(set().union(*[
        portfolio_results[l]["metrics"]["yearly"].keys()
        for l in key_labels if l in portfolio_results
    ]))

    with poe.start_message() as msg:
        msg.write(f"\n## 4. Yearly Returns\n\n")
        header = "| Year |"
        for l in key_labels:
            header += f" {l} |"
        msg.write(header + "\n")
        msg.write("|:-----|" + "-------:|" * len(key_labels) + "\n")
        for yr in all_years:
            line = f"| {yr} |"
            for l in key_labels:
                v = portfolio_results[l]["metrics"]["yearly"].get(yr, 0)
                line += f" {v:+.1f}% |"
            msg.write(line + "\n")

    # ==========================================================
    # 5. Period Stability
    # ==========================================================
    periods = [
        ("Full", None, None),
        ("2008-2009", "2008-01-01", "2009-12-31"),
        ("2010-2012", "2010-01-01", "2012-12-31"),
        ("2013-2015", "2013-01-01", "2015-12-31"),
        ("2016-2019", "2016-01-01", "2019-12-31"),
        ("2020-2022", "2020-01-01", "2022-12-31"),
        ("2023-now", "2023-01-01", None),
    ]

    with poe.start_message() as msg:
        msg.write(f"\n## 5. Period Stability (Sharpe)\n\n")
        header = "| Period |"
        for l in key_labels:
            header += f" {l} |"
        msg.write(header + "\n")
        msg.write("|:-------|" + "-------:|" * len(key_labels) + "\n")

        for pname, start, end in periods:
            line = f"| {pname} |"
            for l in key_labels:
                nav = portfolio_results[l]["metrics"]["nav"]
                sub_nav = nav.copy()
                if start:
                    sub_nav = sub_nav[sub_nav.index >= pd.Timestamp(start)]
                if end:
                    sub_nav = sub_nav[sub_nav.index <= pd.Timestamp(end)]
                if len(sub_nav) < 20:
                    line += f" N/A |"
                    continue
                sub_ret = sub_nav.pct_change().dropna()
                if len(sub_ret) < 20:
                    line += f" N/A |"
                    continue
                excess = sub_ret - combined_rf_weekly
                sha = excess.mean() / excess.std() * np.sqrt(52) if excess.std() > 0 else 0
                line += f" {sha:.3f} |"
            msg.write(line + "\n")

    # ==========================================================
    # 6. Extended timeline: US-only before A-share starts
    # ==========================================================
    us_before = us_result[us_result.index < cn_start]
    if len(us_before) > 50:
        us_before_rf = bil_daily_ret.reindex(us_before.index).fillna(0)
        us_before_excess = us_before["return"] - us_before_rf
        us_before_sharpe = us_before_excess.mean() / us_before_excess.std() * np.sqrt(US_TRADING_DAYS) if us_before_excess.std() > 0 else 0
        us_before_nav = us_before["nav"]
        us_before_years = (us_before.index[-1] - us_before.index[0]).days / 365.25
        us_before_annual = (us_before_nav.iloc[-1] ** (1/us_before_years) - 1) * 100
        us_before_dd = us_before["drawdown"].min() * 100

        with poe.start_message() as msg:
            msg.write(f"\n## 6. Extended Timeline\n\n")
            msg.write(f"**Phase 1 (US Only):** {us_before.index[0].strftime('%Y-%m-%d')} ~ "
                     f"{us_before.index[-1].strftime('%Y-%m-%d')}\n")
            msg.write(f"  Sharpe={us_before_sharpe:.3f}, Ann={us_before_annual:.1f}%, "
                     f"DD={us_before_dd:.1f}%\n\n")
            msg.write(f"**Phase 2 (Combined {best_label}):** "
                     f"{combined_start} ~ {combined_end}\n")
            msg.write(f"  Sharpe={best_m['sharpe']:.3f}, Ann={best_m['annual']:.1f}%, "
                     f"DD={best_m['max_dd']:.1f}%\n")

    # ==========================================================
    # 7. Charts
    # ==========================================================
    with poe.start_message() as msg:
        msg.write(f"\n## 7. Generating Charts...\n")

    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    cmap = plt.cm.tab10
    fig = plt.figure(figsize=(24, 32))
    gs = gridspec.GridSpec(6, 2, height_ratios=[3, 2, 2, 2, 2, 2], hspace=0.38, wspace=0.3)

    colors_alloc = {
        "CN 100%": "#e74c3c", "US 100%": "#2c3e50",
        "CN50/US50": "#27ae60", "CN30/US70": "#8e44ad",
        "CN40/US60": "#f39c12", "CN60/US40": "#3498db",
        "CN70/US30": "#1abc9c", "CN20/US80": "#d35400",
        "CN80/US20": "#c0392b", "CN10/US90": "#7f8c8d",
        "CN90/US10": "#16a085",
    }

    # Panel 1: NAV comparison (key allocations)
    ax1 = fig.add_subplot(gs[0, :])
    for label in key_labels:
        if label not in portfolio_results:
            continue
        m = portfolio_results[label]["metrics"]
        c = colors_alloc.get(label, cmap(key_labels.index(label) % 10))
        lw = 2.5 if label == best_label else 1.5
        ls = "-" if label == best_label else ("--" if "100%" in label else "-.")
        ax1.plot(m["nav"].index, m["nav"],
                 label=f"{label} (S={m['sharpe']:.2f} A={m['annual']:.1f}% DD={m['max_dd']:.1f}%)",
                 color=c, linewidth=lw, linestyle=ls)
    ax1.set_yscale("log")
    ax1.set_title(f"Combined Portfolio NAV ({combined_start} ~ {combined_end})",
                  fontsize=14, fontweight="bold")
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.set_ylabel("NAV (log)")

    # Panel 2: Drawdown
    ax2 = fig.add_subplot(gs[1, :])
    for label in key_labels:
        if label not in portfolio_results:
            continue
        m = portfolio_results[label]["metrics"]
        c = colors_alloc.get(label, cmap(key_labels.index(label) % 10))
        lw = 2.0 if label == best_label else 1.2
        ax2.plot(m["dd_series"].index, m["dd_series"] * 100,
                 label=f"{label} ({m['max_dd']:.1f}%)",
                 color=c, linewidth=lw)
    ax2.set_title("Drawdown Comparison", fontsize=13, fontweight="bold")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.set_ylabel("Drawdown %")

    # Panel 3a: Sharpe vs CN allocation (efficient frontier)
    ax3 = fig.add_subplot(gs[2, 0])
    alloc_pcts, sharpes, annuals_arr, dds_arr = [], [], [], []
    for label, r in portfolio_results.items():
        alloc_pcts.append(r["w_cn"] * 100)
        sharpes.append(r["metrics"]["sharpe"])
        annuals_arr.append(r["metrics"]["annual"])
        dds_arr.append(abs(r["metrics"]["max_dd"]))
    ax3.plot(alloc_pcts, sharpes, "o-", color="#2c3e50", linewidth=2, markersize=8)
    best_idx = sharpes.index(max(sharpes))
    ax3.plot(alloc_pcts[best_idx], sharpes[best_idx], "o", color="#e74c3c",
             markersize=14, zorder=5)
    ax3.annotate(f"Best: {alloc_pcts[best_idx]:.0f}% CN\nSharpe={sharpes[best_idx]:.3f}",
                 (alloc_pcts[best_idx], sharpes[best_idx]),
                 fontsize=9, xytext=(10, -15), textcoords="offset points",
                 fontweight="bold", color="#e74c3c")
    ax3.set_xlabel("A-Share Allocation %")
    ax3.set_ylabel("Sharpe Ratio")
    ax3.set_title("Sharpe vs A-Share Allocation", fontsize=12, fontweight="bold")
    ax3.grid(True, alpha=0.3)

    # Panel 3b: Risk-Return scatter
    ax4 = fig.add_subplot(gs[2, 1])
    for i, (label, r) in enumerate(portfolio_results.items()):
        m = r["metrics"]
        is_best = label == best_label
        size = 150 if is_best else 60
        ax4.scatter(m["max_dd"], m["annual"], s=size,
                    c=[colors_alloc.get(label, cmap(i % 10))],
                    edgecolors="red" if is_best else "white",
                    linewidths=2 if is_best else 1, alpha=0.8, zorder=5 if is_best else 3)
        ax4.annotate(label, (m["max_dd"], m["annual"]),
                     fontsize=7, xytext=(5, 5), textcoords="offset points")
    ax4.set_xlabel("Max Drawdown %")
    ax4.set_ylabel("Annual Return %")
    ax4.set_title("Risk-Return Frontier", fontsize=12, fontweight="bold")
    ax4.grid(True, alpha=0.3)

    # Panel 4: Yearly returns bar chart
    ax5 = fig.add_subplot(gs[3, :])
    n_alloc = len(key_labels)
    x = np.arange(len(all_years))
    w = 0.8 / n_alloc
    for i, label in enumerate(key_labels):
        if label not in portfolio_results:
            continue
        vals = [portfolio_results[label]["metrics"]["yearly"].get(y, 0) for y in all_years]
        c = colors_alloc.get(label, cmap(i % 10))
        ax5.bar(x + i * w - 0.4 + w/2, vals, w, label=label, color=c, alpha=0.8)
    ax5.set_xticks(x)
    ax5.set_xticklabels([str(y) for y in all_years], fontsize=8, rotation=45)
    ax5.set_ylabel("Return %")
    ax5.set_title("Yearly Returns by Allocation", fontsize=13, fontweight="bold")
    ax5.legend(fontsize=8, ncol=4)
    ax5.grid(True, alpha=0.3, axis="y")
    ax5.axhline(0, color="black", linewidth=0.5)

    # Panel 5a: Rolling correlation
    ax6 = fig.add_subplot(gs[4, 0])
    rolling_corr_ts = rolling_corr.copy()
    rolling_corr_ts.index = rolling_corr_ts.index.to_timestamp(how="end")
    ax6.plot(rolling_corr_ts.index, rolling_corr_ts, color="#8e44ad", linewidth=1.2)
    ax6.axhline(corr, color="red", linewidth=1.5, linestyle="--",
                label=f"Full period: {corr:.3f}")
    ax6.axhline(0, color="gray", linewidth=0.5)
    ax6.set_title("Rolling 26-Week Correlation (CN vs US)", fontsize=12, fontweight="bold")
    ax6.set_ylabel("Correlation")
    ax6.legend(fontsize=9)
    ax6.grid(True, alpha=0.3)
    ax6.set_ylim(-0.6, 0.8)

    # Panel 5b: Sub-strategy NAV comparison (standalone, full period each)
    ax7 = fig.add_subplot(gs[4, 1])
    ax7.plot(cn_result.index, cn_result["nav"], color="#e74c3c", linewidth=2,
             label=f"A-Share (S={cn_m['sharpe']:.2f} A={cn_m['annual']:.1f}%)")
    ax7.plot(us_result.index, us_result["nav"], color="#2c3e50", linewidth=2,
             label=f"US 8ETF (S={us_m['sharpe']:.2f} A={us_m['annual']:.1f}%)")
    # SPY benchmark on same axes
    spy_nav_aligned = spy_nav_full.reindex(us_result.index).ffill().dropna()
    if len(spy_nav_aligned) > 0:
        ax7.plot(spy_nav_aligned.index, spy_nav_aligned / spy_nav_aligned.iloc[0],
                 color="gray", linewidth=1.2, linestyle="--", alpha=0.6,
                 label=f"SPY (S={spy_sharpe:.2f} A={spy_annual:.1f}%)")
    ax7.set_yscale("log")
    ax7.set_title("Sub-Strategy NAV (standalone)", fontsize=12, fontweight="bold")
    ax7.legend(fontsize=8)
    ax7.grid(True, alpha=0.3)
    ax7.set_ylabel("NAV (log)")

    # Panel 6a: Monthly heatmap for best combined portfolio
    ax8 = fig.add_subplot(gs[5, 0])
    best_nav = best_m["nav"]
    best_ret = best_nav.pct_change().dropna()
    monthly_rets = best_ret.groupby([best_ret.index.year, best_ret.index.month]).apply(
        lambda x: (1+x).prod()-1) * 100
    monthly_df = monthly_rets.unstack(level=1)
    month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    # Ensure all 12 columns
    for mi in range(1, 13):
        if mi not in monthly_df.columns:
            monthly_df[mi] = np.nan
    monthly_df = monthly_df[list(range(1, 13))]
    monthly_df.columns = month_labels

    valid_vals = monthly_df.values[~np.isnan(monthly_df.values)]
    if len(valid_vals) > 0:
        vabs = max(abs(valid_vals.min()), abs(valid_vals.max()))
        norm = TwoSlopeNorm(vmin=-vabs, vcenter=0, vmax=vabs)
        im = ax8.imshow(monthly_df.values, cmap="RdYlGn", aspect="auto", norm=norm)
        ax8.set_xticks(range(12))
        ax8.set_xticklabels(month_labels, fontsize=7, rotation=45)
        ax8.set_yticks(range(len(monthly_df.index)))
        ax8.set_yticklabels([str(y) for y in monthly_df.index], fontsize=7)
        for yi in range(len(monthly_df.index)):
            for xi in range(12):
                v = monthly_df.values[yi, xi]
                if not np.isnan(v):
                    ax8.text(xi, yi, f"{v:.1f}", ha="center", va="center",
                             fontsize=5.5, color="white" if abs(v) > vabs*0.6 else "black")
        ax8.set_title(f"Monthly Returns (%): {best_label}", fontsize=11, fontweight="bold")
        plt.colorbar(im, ax=ax8, shrink=0.8, label="%")

    # Panel 6b: Summary text box
    ax9 = fig.add_subplot(gs[5, 1])
    ax9.axis("off")
    cn100 = portfolio_results.get("CN 100%", {}).get("metrics", {})
    us100 = portfolio_results.get("US 100%", {}).get("metrics", {})
    summary_text = (
        f"Combined Portfolio Summary\n"
        f"{'='*45}\n\n"
        f"Best Sharpe: {best_label}\n"
        f"  (A-Share {best_r['w_cn']*100:.0f}% + US {best_r['w_us']*100:.0f}%)\n\n"
        f"Sharpe:       {best_m['sharpe']:.3f}\n"
        f"Annual Ret:   {best_m['annual']:.1f}%\n"
        f"Max Drawdown: {best_m['max_dd']:.1f}%\n"
        f"Calmar:       {best_m['calmar']:.3f}\n"
        f"Total Return: {best_m['total_return']:.1f}%\n"
        f"Win Rate(M):  {best_m['win_rate']:.1f}%\n"
        f"Period:       {best_m['years']:.1f} years\n\n"
        f"Correlation:  {corr:.3f}\n\n"
        f"Sub-Strategies:\n"
        f"  CN: S={cn_m['sharpe']:.3f} A={cn_m['annual']:.1f}% DD={cn_m['max_dd']:.1f}%\n"
        f"  US: S={us_m['sharpe']:.3f} A={us_m['annual']:.1f}% DD={us_m['max_dd']:.1f}%\n"
        f"  SPY: S={spy_sharpe:.3f} A={spy_annual:.1f}% DD={spy_dd:.1f}%"
    )
    ax9.text(0.05, 0.95, summary_text, transform=ax9.transAxes,
             fontsize=11, verticalalignment="top", fontfamily="monospace",
             bbox=dict(boxstyle="round,pad=0.5", facecolor="#ecf0f1", alpha=0.8))

    fig.suptitle(
        f"A-Share + US 8ETF Combined Momentum Rotation\n"
        f"CN: 4idx+SZQZ LB=20 AM=10 | US: 8ETF LB=120 Top3 TV=20% ML=1.5 ModelB",
        fontsize=15, fontweight="bold", y=1.01)
    plt.tight_layout(rect=[0, 0, 1, 0.97])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    chart_bytes = buf.read()

    with poe.start_message() as msg:
        msg.write("## Charts\n\n")
        att = msg.attach_file(name="combined_strategy_v2.png", contents=chart_bytes,
                              content_type="image/png", is_inline=True)
        msg.write(f"{att.inline_ref}\n")

    # ==========================================================
    # 8. Excel Output
    # ==========================================================
    excel_buf = io.BytesIO()
    wb = xlsxwriter.Workbook(excel_buf, {"in_memory": True})

    fh = wb.add_format({"bold": True, "bg_color": "#1a5276", "font_color": "white",
                         "border": 1, "align": "center", "text_wrap": True})
    fd = wb.add_format({"num_format": "yyyy-mm-dd", "border": 1})
    fn = wb.add_format({"num_format": "0.000", "border": 1, "align": "center"})
    fn2 = wb.add_format({"num_format": "0.00", "border": 1, "align": "center"})
    fpct = wb.add_format({"num_format": "0.0%", "border": 1, "align": "center"})
    fpct2 = wb.add_format({"num_format": "0.00%", "border": 1, "align": "center"})
    fstr = wb.add_format({"border": 1, "align": "center"})
    fgood = wb.add_format({"bg_color": "#27AE60", "font_color": "white", "border": 1,
                            "num_format": "0.0%", "align": "center"})
    fbad = wb.add_format({"bg_color": "#E74C3C", "font_color": "white", "border": 1,
                           "num_format": "0.0%", "align": "center"})
    fbest = wb.add_format({"bg_color": "#FFF9C4", "border": 1, "num_format": "0.000",
                            "align": "center"})

    # Sheet 1: Allocation Comparison
    ws1 = wb.add_worksheet("Allocation Comparison")
    headers1 = ["Allocation", "CN%", "US%", "Sharpe", "Annual", "MaxDD",
                "Calmar", "Vol", "WinRate(M)", "Total Ret", "Years"]
    for j, h in enumerate(headers1):
        ws1.write(0, j, h, fh)
        ws1.set_column(j, j, 14 if j == 0 else 12)
    for i, (label, r) in enumerate(portfolio_results.items()):
        m = r["metrics"]
        row = i + 1
        is_best = label == best_label
        sf = fbest if is_best else fstr
        nf = fbest if is_best else fn
        pf = fbest if is_best else fpct
        ws1.write(row, 0, label, sf)
        ws1.write(row, 1, r["w_cn"], pf)
        ws1.write(row, 2, r["w_us"], pf)
        ws1.write(row, 3, m["sharpe"], nf)
        ws1.write(row, 4, m["annual"]/100, pf)
        ws1.write(row, 5, m["max_dd"]/100, pf)
        ws1.write(row, 6, m["calmar"], nf)
        ws1.write(row, 7, m["vol"]/100, pf)
        ws1.write(row, 8, m["win_rate"]/100, pf)
        ws1.write(row, 9, m["total_return"]/100, pf)
        ws1.write(row, 10, m["years"], fn2)

    # Sheet 2: Yearly Returns
    ws2 = wb.add_worksheet("Yearly Returns")
    all_labels = list(portfolio_results.keys())
    ws2.write(0, 0, "Year", fh)
    for j, label in enumerate(all_labels):
        ws2.write(0, j+1, label, fh)
        ws2.set_column(j+1, j+1, 14)
    ws2.set_column(0, 0, 8)

    all_years_full = sorted(set().union(*[
        r["metrics"]["yearly"].keys() for r in portfolio_results.values()
    ]))
    for i, yr in enumerate(all_years_full):
        ws2.write(i+1, 0, yr, fstr)
        for j, label in enumerate(all_labels):
            v = portfolio_results[label]["metrics"]["yearly"].get(yr, None)
            if v is not None:
                cell_fmt = fgood if v > 0 else fbad
                ws2.write(i+1, j+1, v/100, cell_fmt)

    # Sheet 3: Weekly Returns (best allocation)
    ws3 = wb.add_worksheet(f"Weekly Ret ({best_label[:12].replace('/', '-')})")
    best_port_ret = best_r["w_cn"] * cn_w + best_r["w_us"] * us_w
    ws3.write(0, 0, "Week End", fh)
    ws3.write(0, 1, "CN Ret", fh)
    ws3.write(0, 2, "US Ret", fh)
    ws3.write(0, 3, "Combined Ret", fh)
    ws3.write(0, 4, "Combined NAV", fh)
    ws3.set_column(0, 0, 14)
    for j in range(1, 5):
        ws3.set_column(j, j, 14)

    comb_nav_weekly = (1 + best_port_ret).cumprod()
    for i, wk in enumerate(common_weeks):
        ws3.write(i+1, 0, str(wk), fstr)
        ws3.write(i+1, 1, cn_w.iloc[i], fpct2)
        ws3.write(i+1, 2, us_w.iloc[i], fpct2)
        ws3.write(i+1, 3, best_port_ret.iloc[i], fpct2)
        ws3.write(i+1, 4, comb_nav_weekly.iloc[i], fn)

    # Sheet 4: Sub-strategy daily (CN)
    ws4 = wb.add_worksheet("CN Daily")
    cn_headers = ["Date", "Holding", "Return", "NAV", "Drawdown"]
    for j, h in enumerate(cn_headers):
        ws4.write(0, j, h, fh)
        ws4.set_column(j, j, 14)
    for i, (dt, row) in enumerate(cn_result.iterrows()):
        r = i + 1
        if r > 65000:
            break
        ws4.write_datetime(r, 0, dt.to_pydatetime(), fd)
        ws4.write(r, 1, CN_NAMES.get(row["holding"], row["holding"]), fstr)
        ws4.write(r, 2, row["return"], fpct2)
        ws4.write(r, 3, row["nav"], fn)
        ws4.write(r, 4, row["drawdown"], fpct2)

    # Sheet 5: Sub-strategy daily (US)
    ws5 = wb.add_worksheet("US Daily")
    us_w_cols = [f"w_{a}" for a in US_POOL_8 + ["BIL"]]
    us_headers = ["Date", "Return", "NAV", "Drawdown", "Scale"] + US_POOL_8 + ["BIL"]
    for j, h in enumerate(us_headers):
        ws5.write(0, j, h, fh)
        ws5.set_column(j, j, 12)
    ws5.set_column(0, 0, 14)
    for i, (dt, row) in enumerate(us_result.iterrows()):
        r = i + 1
        if r > 65000:
            break
        ws5.write_datetime(r, 0, dt.to_pydatetime(), fd)
        ws5.write(r, 1, row["return"], fpct2)
        ws5.write(r, 2, row["nav"], fn)
        ws5.write(r, 3, row["drawdown"], fpct2)
        ws5.write(r, 4, row.get("scale", 1.0), fn2)
        for ai, a in enumerate(US_POOL_8 + ["BIL"]):
            col_name = f"w_{a}"
            ws5.write(r, 5 + ai, row.get(col_name, 0.0), fn)

    # Sheet 6: Charts
    ws6 = wb.add_worksheet("Charts")
    ws6.insert_image("A1", "c.png", {"image_data": io.BytesIO(chart_bytes),
                                       "x_scale": 0.35, "y_scale": 0.35})

    wb.close()
    excel_buf.seek(0)
    excel_bytes = excel_buf.read()

    with poe.start_message() as msg:
        msg.write("## Excel Output\n\n")
        msg.attach_file(
            name=f"Combined_Portfolio_V2_{today_str}.xlsx",
            contents=excel_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        msg.write(f"\n**6 Sheets:**\n")
        msg.write(f"1. **Allocation Comparison** - All CN/US weight combos\n")
        msg.write(f"2. **Yearly Returns** - Year-by-year for all allocations\n")
        msg.write(f"3. **Weekly Ret ({best_label[:12]})** - Weekly CN/US/Combined returns\n")
        msg.write(f"4. **CN Daily** - A-share sub-strategy daily records\n")
        msg.write(f"5. **US Daily** - US 8ETF sub-strategy daily records + weights\n")
        msg.write(f"6. **Charts** - Strategy summary chart\n")

    # ==========================================================
    # 9. Final Summary
    # ==========================================================
    with poe.start_message() as msg:
        msg.write(f"\n## Final Summary\n\n")
        msg.write(f"**Sub-Strategies:**\n")
        msg.write(f"- A-Share: 4idx+SZQZ, LB=20, AM=10, Comm=0.1%/leg\n")
        msg.write(f"- US: 8ETF, LB=120, Top3, TV=20%, ML=1.5, ModelB, Comm=0.1%\n\n")

        cn100_m = portfolio_results.get("CN 100%", {}).get("metrics", {})
        us100_m = portfolio_results.get("US 100%", {}).get("metrics", {})

        msg.write(f"| Metric | CN 100% | {best_label} | US 100% |\n")
        msg.write(f"|:-------|--------:|:-------:|--------:|\n")
        for name, key, fmt, suffix in [
            ("Sharpe", "sharpe", ".3f", ""),
            ("Annual", "annual", ".1f", "%"),
            ("MaxDD", "max_dd", ".1f", "%"),
            ("Calmar", "calmar", ".3f", ""),
            ("Vol", "vol", ".1f", "%"),
            ("Total Ret", "total_return", ".1f", "%"),
            ("WinRate(M)", "win_rate", ".1f", "%"),
        ]:
            v_cn = cn100_m.get(key, 0)
            v_best = best_m.get(key, 0)
            v_us = us100_m.get(key, 0)
            msg.write(f"| {name} | {v_cn:{fmt}}{suffix} | **{v_best:{fmt}}{suffix}** | {v_us:{fmt}}{suffix} |\n")

        msg.write(f"\n**Diversification Benefit:**\n")
        msg.write(f"- Weekly correlation: {corr:.3f}\n")
        sha_gain = best_m["sharpe"] - max(cn100_m.get("sharpe", 0), us100_m.get("sharpe", 0))
        dd_improve = best_m["max_dd"] - min(cn100_m.get("max_dd", 0), us100_m.get("max_dd", 0))
        msg.write(f"- Sharpe improvement vs best single: {sha_gain:+.3f}\n")
        msg.write(f"- MaxDD improvement vs worst single: {dd_improve:+.1f}%\n")


main()

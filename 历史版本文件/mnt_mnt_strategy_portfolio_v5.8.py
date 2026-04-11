# privacy_shield=half (需要网络访问东方财富API获取股票数据)
"""
策略组合 v5.8 — 移除Sub-A/Sub-A-DK冷却期
===============================================================
变更:
  v5.7 → v5.8:
    移除 Sub-A 和 Sub-A-DK 的冷却期(COOLDOWN_DAYS):
      - Sub-A:    COOLDOWN_DAYS=3 → 移除 (乖离动量信号平滑, CD=0~3交易频率几乎无差异)
      - Sub-A-DK: COOLDOWN_DAYS=5 → 移除 (年均33次交易中30次是配对切换,
        冷却期仅影响方向翻转3次/年, 实际无效果)
      - 依据: T+1制度已天然保证最少1天间隔, 乖离动量+R²信号足够平滑无需额外冷却

  v5.6 → v5.7:
    Sub-B 参数优化 (基于纵向+横向过拟合审查):
      - US_ROT_LB: 120 → 160 (120在80%平台边缘, 160更稳健)
      - US_ROT_REBALANCE_THRESHOLD: 1.3 → 1.0 (移除, 全时段贡献为负)
      - 其余参数不变: MIN_TURNOVER=0.15, VolReg=2.0(10/250), TOP_N=3

  v5.5 → v5.6:
    Sub-A-DK 从 v5.4 单配对(SZ50/ZZ1000) 改为 多配对Top-1:
      - 5指数(SZ50, HS300, ZZ500, ZZ1000, CYB) → C(5,2)=10配对
      - 每对独立运行乖离动量策略(含波动率缩放+交易成本)
      - 每天按 |bias_mom| 信号强度选Top-1配对
      - 二值R²过滤: R²(20)<0.3 → 次日收益置零

  v5.4 → v5.5:
    Sub-A 从 v5.4 的 MA-Turning 轮动 改为 乖离动量+R²过滤+国债ETF

子策略组成:
  - Sub-A (15%):   乖离动量 + R²过滤 + 国债ETF    [v5.5, v5.8移除冷却期]
  - Sub-A-DK (15%): 多配对Top-1 + 二值R²           [v5.6, v5.8移除冷却期]
  - Sub-B (40%):   美股9ETF轮动 + VolReg           [v5.7优化]
  - Sub-C (30%):   美股生产组合 + Vol-Scaling       [v5.4不变]

运行方式: 直接执行本文件, 从API获取数据, 对比新旧组合表现
依赖: 同目录下需有 v5.4 脚本文件
===============================================================
"""

import sys
import importlib.util
import pandas as pd
import numpy as np
import time
from itertools import combinations

# ─────────────────────────────────────────────
# 全局配置
# ─────────────────────────────────────────────
V54_PATH = "1_mnt_mnt_strategy_signal_v5.4_aggressive.py"   # v5.4 脚本路径
BOND_SECID = "1.511010"                                      # 国债ETF代码


###############################################################################
#  Part 1 — 新 Sub-A 策略: 乖离动量 + R² 过滤 + 国债ETF  (自v5.5)
###############################################################################

class BiasMotionConfig:
    """乖离动量策略参数"""
    EQUITY_CODES = ["1.515100", "0.159915", "1.000300", "1.000852", "1.000905"]
    BOND_CODE = "1.511010"
    ALL_CODES = EQUITY_CODES + [BOND_CODE]

    BIAS_N = 60          # 均线周期 (price / MA60)
    MOM_DAY = 20         # 斜率拟合窗口
    R2_WINDOW = 20       # R²滚动窗口
    R2_THRESHOLD = 0.3   # R²最低门槛
    COMMISSION = 0.001   # 单边佣金 0.1%

    RF_ANNUAL = 0.03
    TRADING_DAYS = 244
    RF_DAILY = (1 + RF_ANNUAL) ** (1 / TRADING_DAYS) - 1

    CN_NAMES = {
        "1.515100": "中证红利", "0.159915": "创业板", "1.000300": "沪深300",
        "1.000852": "中证1000", "1.000905": "中证500", "1.511010": "国债ETF",
        "cash": "现金",
    }


class BiasMotionStrategy:
    """
    乖离动量 + R²过滤 + 国债ETF轮动策略
    替代 v5.4 的 run_cn_strategy
    """

    def __init__(self, config=None):
        self.cfg = config or BiasMotionConfig()

    def calc_bias_momentum(self, close_series):
        """
        乖离动量:
        1) bias = price / MA(BIAS_N)
        2) 取最近 MOM_DAY 天的 bias, 归一化 (/ bias[0])
        3) 线性拟合斜率 × 10000
        """
        cfg = self.cfg
        prices = close_series.values.astype(float)
        n = len(prices)
        result = np.full(n, np.nan)
        ma = close_series.rolling(cfg.BIAS_N).mean().values
        total_lookback = cfg.BIAS_N + cfg.MOM_DAY - 1
        x = np.arange(cfg.MOM_DAY, dtype=float)

        for i in range(total_lookback, n):
            bias_window = np.empty(cfg.MOM_DAY)
            valid = True
            for j in range(cfg.MOM_DAY):
                idx = i - cfg.MOM_DAY + 1 + j
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

    def calc_rolling_r2(self, close_series):
        """滚动R²: 价格对时间的线性回归拟合优度 (0~1)"""
        cfg = self.cfg
        y = close_series.values.astype(float)
        n = len(y)
        r2 = np.full(n, np.nan)
        window = cfg.R2_WINDOW
        x = np.arange(window, dtype=float)
        x_mean = x.mean()
        ss_x = ((x - x_mean) ** 2).sum()

        for i in range(window - 1, n):
            y_win = y[i - window + 1:i + 1]
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

    def run(self, close_df, codes=None):
        """
        运行回测
        返回: DataFrame(index=date, columns=[return, holding, nav])
        """
        cfg = self.cfg
        if codes is None:
            codes = cfg.ALL_CODES

        has_bond = cfg.BOND_CODE in codes
        bias_dict, r2_dict = {}, {}
        for code in codes:
            bias_dict[code] = self.calc_bias_momentum(close_df[code])
            if code != cfg.BOND_CODE:
                r2_dict[code] = self.calc_rolling_r2(close_df[code])

        start_idx = cfg.BIAS_N + cfg.MOM_DAY
        holding = "cash"
        rows = []

        for i in range(start_idx, len(close_df)):
            date = close_df.index[i]

            scores = {}
            for code in codes:
                val = bias_dict[code].iloc[i]
                if not np.isnan(val):
                    scores[code] = val

            ideal = "cash"
            if scores:
                best = max(scores, key=scores.get)
                if has_bond and best == cfg.BOND_CODE:
                    ideal = best
                else:
                    r2_val = r2_dict.get(best, pd.Series(dtype=float)).iloc[i] \
                        if best in r2_dict and i < len(r2_dict[best]) else np.nan
                    if not np.isnan(r2_val) and r2_val >= cfg.R2_THRESHOLD:
                        ideal = best

            target = ideal if ideal != holding else None

            if target is not None:
                old_h = holding
                cost = (1 - cfg.COMMISSION) if (old_h == "cash" or target == "cash") \
                    else (1 - cfg.COMMISSION) ** 2
                if old_h == "cash":
                    day_ret = (1 + cfg.RF_DAILY) * cost - 1
                else:
                    asset_ret = close_df.iloc[i][old_h] / close_df.iloc[i-1][old_h] - 1
                    day_ret = (1 + asset_ret) * cost - 1
                holding = target
            else:
                if holding == "cash":
                    day_ret = cfg.RF_DAILY
                else:
                    day_ret = close_df.iloc[i][holding] / close_df.iloc[i-1][holding] - 1

            rows.append({"date": date, "return": day_ret, "holding": holding})

        result = pd.DataFrame(rows).set_index("date")
        result["nav"] = (1 + result["return"]).cumprod()
        return result


###############################################################################
#  Part 2 — 新 Sub-A-DK: 多配对 Top-1 + 二值R²  (v5.6新增)
###############################################################################

class MultiPairDKConfig:
    """多配对DK策略参数"""
    BIAS_N = 60              # 乖离动量均线周期
    MOM_DAY = 20             # 斜率拟合窗口
    R2_MODE = 'binary'       # R²模式: 'binary'=二值过滤
    R2_WINDOW = 20           # R²滚动窗口
    R2_THRESHOLD = 0.3       # R²阈值(二值过滤)
    TARGET_VOL = 0.15        # 目标波动率
    VOL_WINDOW = 30          # 波动率计算窗口
    MAX_LEV = 1.5            # 最大杠杆
    MIN_LEV = 0.1            # 最小杠杆
    SCALE_THRESHOLD = 0.10   # scale变动阈值
    COMMISSION = 0.001       # 单边佣金
    TRADING_DAYS = 242       # 年交易日(用于波动率年化)
    TOP_N = 1                # 每天选Top-N配对

    INDEX_NAMES = {
        'SZ50': '上证50', 'HS300': '沪深300', 'ZZ500': '中证500',
        'ZZ1000': '中证1000', 'CYB': '创业板',
    }


def _calc_bias_momentum(series, bias_n, mom_day):
    """乖离动量: slope(price/MA(bias_n) 归一化后最近mom_day日) × 10000"""
    prices = series.values.astype(float)
    n = len(prices)
    result = np.full(n, np.nan)
    ma = series.rolling(bias_n).mean().values
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

    return pd.Series(result, index=series.index)


def _rolling_r2_fast(series, window):
    """滚动R²"""
    y = series.values.astype(float)
    n = len(y)
    r2 = np.full(n, np.nan)
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    ss_x = ((x - x_mean) ** 2).sum()
    for i in range(window - 1, n):
        yi = y[i - window + 1:i + 1]
        if np.any(np.isnan(yi)):
            continue
        y_mean = yi.mean()
        ss_y = ((yi - y_mean) ** 2).sum()
        if ss_y < 1e-15:
            r2[i] = 0.0
            continue
        ss_xy = ((x - x_mean) * (yi - y_mean)).sum()
        r2[i] = max(0.0, (ss_xy ** 2) / (ss_x * ss_y))
    return pd.Series(r2, index=series.index)


def _run_single_pair(a_prices, b_prices, cfg=None):
    """
    对单个配对运行乖离动量策略
    返回: (strategy_ret: pd.Series, abs_bias_mom: pd.Series) 或 (None, None)
    """
    if cfg is None:
        cfg = MultiPairDKConfig()

    d = pd.DataFrame({'a': a_prices, 'b': b_prices}).dropna()
    if len(d) < cfg.BIAS_N + cfg.MOM_DAY + cfg.VOL_WINDOW + 50:
        return None, None

    d['a_ret'] = d['a'].pct_change()
    d['b_ret'] = d['b'].pct_change()
    d['spread_ret'] = d['a_ret'] - d['b_ret']
    d = d.dropna(subset=['a_ret', 'b_ret'])

    # 乖离动量 (对价格比)
    d['ratio'] = d['a'] / d['b']
    d['bias_mom'] = _calc_bias_momentum(d['ratio'], cfg.BIAS_N, cfg.MOM_DAY)

    # R² (对价差累计曲线)
    d['spread_cum'] = d['spread_ret'].cumsum()
    d['r2'] = _rolling_r2_fast(d['spread_cum'], cfg.R2_WINDOW)

    n = len(d)
    start_idx = max(cfg.BIAS_N + cfg.MOM_DAY, cfg.VOL_WINDOW, cfg.R2_WINDOW) + 1

    # 方向信号: bias_mom > 0 → +1, 否则 -1 (无冷却期, T+1已天然保证)
    d['signal'] = np.nan
    valid = d['bias_mom'].notna() & (np.arange(n) >= start_idx)
    d.loc[valid, 'signal'] = np.where(d.loc[valid, 'bias_mom'] > 0, 1, -1)
    d['signal'] = d['signal'].ffill()   # 保持上一信号 (处理bias_mom偶发NaN)
    d['signal'] = d['signal'].astype(float)
    d['position'] = d['signal'].shift(1)
    d['raw_ret'] = d['position'] * d['spread_ret']
    d = d.dropna(subset=['position', 'raw_ret'])

    # 波动率缩放
    d['realized_vol'] = d['raw_ret'].rolling(cfg.VOL_WINDOW).std() * np.sqrt(cfg.TRADING_DAYS)
    d['scale'] = (cfg.TARGET_VOL / d['realized_vol']).clip(cfg.MIN_LEV, cfg.MAX_LEV)
    d['scale'] = d['scale'].shift(1)
    if cfg.SCALE_THRESHOLD > 0:
        _sa = d['scale'].values.copy()
        _last = np.nan
        for _i in range(len(_sa)):
            if np.isnan(_sa[_i]):
                continue
            if np.isnan(_last):
                _last = _sa[_i]
            elif abs(_sa[_i] - _last) >= cfg.SCALE_THRESHOLD:
                _last = _sa[_i]
            else:
                _sa[_i] = _last
        d['scale'] = _sa
    d['strategy_ret'] = d['raw_ret'] * d['scale']
    d = d.dropna(subset=['strategy_ret'])

    # 交易成本
    pos_prev = d['position'].shift(1)
    is_flip = (d['position'] != pos_prev) & pos_prev.notna()
    is_initial = d['position'].notna() & pos_prev.isna()
    if cfg.COMMISSION > 0:
        d['tc'] = 0.0
        d.loc[is_flip, 'tc'] = 4 * cfg.COMMISSION * d['scale'][is_flip]
        d.loc[is_initial, 'tc'] = 2 * cfg.COMMISSION * d['scale'][is_initial]
        _chg = d['scale'].diff().abs().fillna(0)
        _only = ~is_flip & ~is_initial & d['position'].notna()
        d.loc[_only, 'tc'] += 2 * cfg.COMMISSION * _chg[_only]
        d['strategy_ret'] = (1 + d['strategy_ret']) * (1 - d['tc']) - 1

    # 二值R²过滤: R²<阈值 → 次日收益置零
    if cfg.R2_MODE == 'binary':
        _r2v = d['r2'].values
        _flags = np.zeros(len(d), dtype=bool)
        for _i in range(len(d)):
            if not np.isnan(_r2v[_i]) and _r2v[_i] < cfg.R2_THRESHOLD:
                if _i + 1 < len(d):
                    _flags[_i + 1] = True
        _ret = d['strategy_ret'].values.copy()
        _ret[_flags] = 0.0
        d['strategy_ret'] = _ret

    return d['strategy_ret'], d['bias_mom'].abs()


def _build_top_n(rets_df, signals_df, n):
    """每天选 |bias_mom| 最大的N对, 等权. 信号用前一天的(避免前瞻)"""
    sig_shifted = signals_df.shift(1)
    portfolio_ret = pd.Series(0.0, index=rets_df.index)

    for date in rets_df.index:
        available_rets = rets_df.loc[date].dropna()
        if date in sig_shifted.index:
            available_sigs = sig_shifted.loc[date].dropna()
        else:
            continue
        common = available_rets.index.intersection(available_sigs.index)
        if len(common) == 0:
            continue
        top_pairs = available_sigs[common].nlargest(min(n, len(common)))
        selected = top_pairs.index
        portfolio_ret[date] = available_rets[selected].mean()

    return portfolio_ret


class MultiPairDKStrategy:
    """
    多配对 Top-1 DK 策略
    5指数(SZ50, HS300, ZZ500, ZZ1000, CYB) → C(5,2)=10配对
    每对独立运行乖离动量策略, 每天选信号最强的1对
    """

    def __init__(self, config=None):
        self.cfg = config or MultiPairDKConfig()

    def run(self, cn_close, cn_dk_close):
        """
        运行多配对Top-1策略
        参数:
            cn_close: 包含 '1.000300', '1.000905', '0.159915' 等列的DataFrame
            cn_dk_close: 包含 'DK_SZ50', 'DK_ZZ1000' 等列的DataFrame
        返回:
            pd.DataFrame(index=date, columns=['return', 'nav'])
        """
        cfg = self.cfg

        indices = {
            'SZ50':   cn_dk_close['DK_SZ50'],
            'HS300':  cn_close['1.000300'],
            'ZZ500':  cn_close['1.000905'],
            'ZZ1000': cn_dk_close['DK_ZZ1000'],
            'CYB':    cn_close['0.159915'],
        }

        idx_all = list(indices.keys())
        pairs_all = list(combinations(idx_all, 2))

        pair_rets = {}
        pair_sigs = {}
        for a_name, b_name in pairs_all:
            label = f"{a_name}/{b_name}"
            ret, sig = _run_single_pair(indices[a_name], indices[b_name], cfg)
            if ret is not None and len(ret) > 100:
                pair_rets[label] = ret
                pair_sigs[label] = sig

        if not pair_rets:
            raise RuntimeError("多配对策略无法生成任何有效配对")

        rets_df = pd.DataFrame(pair_rets)
        sigs_df = pd.DataFrame(pair_sigs)

        t_ret = _build_top_n(rets_df, sigs_df, cfg.TOP_N)

        result = pd.DataFrame({'return': t_ret})
        result['nav'] = (1 + result['return']).cumprod()
        return result


###############################################################################
#  Part 3 — v5.4 模块加载 + 指标计算
###############################################################################

def load_v54(path):
    """导入 v5.4 模块 (mock poe 以便脱离 Poe 环境运行)"""
    class _FakePoe:
        class BotError(Exception): pass
        class Message:
            def __init__(self, **kw):
                self.text = kw.get("text", "")
                self.sender = kw.get("sender", "user")
                self.attachments = kw.get("attachments", [])
                self.parameters = kw.get("parameters", {})
        def start_message(self): return self
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def write(self, *a): pass
        def update_settings(self, *a): pass

    _fake = _FakePoe()
    sys.modules['poe'] = _fake
    class _FT:
        SettingsResponse = type('SR', (), {'__init__': lambda self, **kw: None})
    sys.modules.setdefault('fastapi_poe', type(sys)('fastapi_poe'))
    sys.modules.setdefault('fastapi_poe.types', _FT())

    spec = importlib.util.spec_from_file_location("v54", path)
    mod = importlib.util.module_from_spec(spec)
    mod.poe = _fake
    spec.loader.exec_module(mod)
    return mod


class ProgressMsg:
    """_fetch_data 的进度输出"""
    def write(self, text): print(text, end="")
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def add_attachment(self, *a, **kw): pass
    def attach_file(self, *a, **kw): pass


def compute_metrics(cn_result, cn_dk_result, us_rot_result,
                    us_prod_daily, prod_sig_a, prod_sig_b, prod_nav,
                    start_date, end_date, v54):
    """
    完整指标计算:
      月度收益 → 对齐 → 组合NAV → calc_monthly_metrics → 日度覆盖 MaxDD/Annual
    """
    cn_m = cn_result["return"].groupby(cn_result.index.to_period("M")).apply(
        lambda x: (1 + x).prod() - 1)
    dk_m = cn_dk_result["return"].groupby(cn_dk_result.index.to_period("M")).apply(
        lambda x: (1 + x).prod() - 1)
    us_m = us_rot_result["return"].groupby(us_rot_result.index.to_period("M")).apply(
        lambda x: (1 + x).prod() - 1)

    if v54.PROD_VS_ENABLED:
        subc_daily = v54._get_subc_daily_ret(us_prod_daily, prod_sig_a, prod_sig_b=prod_sig_b)
        prod_m = subc_daily.groupby(subc_daily.index.to_period("M")).apply(
            lambda x: (1 + x).prod() - 1)
    else:
        prod_m = prod_nav.pct_change().dropna()
        prod_m.index = prod_m.index.to_period("M")

    common = cn_m.index.intersection(dk_m.index).intersection(us_m.index).intersection(prod_m.index)
    aligned = pd.DataFrame({
        "Sub-A": cn_m.reindex(common), "Sub-A-DK": dk_m.reindex(common),
        "Sub-B": us_m.reindex(common), "Sub-C": prod_m.reindex(common),
    }).dropna()

    w = v54.COMBINED_WEIGHTS
    cols = ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]
    nav_m = (1 + aligned[cols]).cumprod()
    nav_comb = sum(nav_m[n] * w[n] for n in cols)
    nav_comb = nav_comb / nav_comb.iloc[0]
    aligned["Combined"] = nav_comb.pct_change()
    aligned.loc[aligned.index[0], "Combined"] = nav_comb.iloc[0] - 1

    sp, ep = start_date.to_period("M"), end_date.to_period("M")
    mask = (aligned.index >= sp) & (aligned.index <= ep)
    filt = aligned[mask]

    metrics = {}
    for name, series in [("Sub-A", cn_m), ("Sub-A-DK", dk_m), ("Sub-B", us_m), ("Sub-C", prod_m)]:
        s = series[(series.index >= sp) & (series.index <= ep)]
        if len(s) >= 1:
            metrics[name] = v54.calc_monthly_metrics(s)
    if len(filt) >= 1:
        metrics["Combined"] = v54.calc_monthly_metrics(filt["Combined"])

    # 日度覆盖: MaxDD / Annual / Calmar
    cn_d = cn_result["return"][(cn_result.index >= start_date) & (cn_result.index <= end_date)]
    dk_d = cn_dk_result["return"][(cn_dk_result.index >= start_date) & (cn_dk_result.index <= end_date)]
    us_d = us_rot_result["return"][(us_rot_result.index >= start_date) & (us_rot_result.index <= end_date)]
    if v54.PROD_VS_ENABLED:
        subc_d = v54._get_subc_daily_ret(us_prod_daily, prod_sig_a, prod_sig_b=prod_sig_b)
    else:
        subc_d = prod_nav.pct_change().dropna()
    subc_d = subc_d[(subc_d.index >= start_date) & (subc_d.index <= end_date)]

    for sname, dret in [("Sub-A", cn_d), ("Sub-A-DK", dk_d), ("Sub-B", us_d), ("Sub-C", subc_d)]:
        if sname in metrics and len(dret) > 1:
            nv = (1 + dret).cumprod()
            metrics[sname]["max_dd"] = ((nv - nv.cummax()) / nv.cummax()).min() * 100
            total = (nv.iloc[-1] / nv.iloc[0] - 1) * 100
            metrics[sname]["total_return"] = total
            ndays = (dret.index[-1] - dret.index[0]).days
            if ndays > 0:
                ann = ((nv.iloc[-1] / nv.iloc[0]) ** (365.25 / ndays) - 1) * 100
                metrics[sname]["annual"] = ann
                metrics[sname]["calmar"] = ann / abs(metrics[sname]["max_dd"]) \
                    if metrics[sname]["max_dd"] != 0 else 0

    # Combined 日度覆盖
    if "Combined" in metrics:
        daily_parts = [cn_d, dk_d, us_d, subc_d]
        non_empty = [d for d in daily_parts if len(d) > 0]
        if len(non_empty) >= 2:
            cstart = max(d.index[0] for d in non_empty)
            nav_parts = {}
            for sname, dret in [("Sub-A", cn_d), ("Sub-A-DK", dk_d), ("Sub-B", us_d), ("Sub-C", subc_d)]:
                if len(dret) > 1:
                    nv = (1 + dret).cumprod()
                    nav_parts[sname] = nv / nv.iloc[0]
            if len(nav_parts) >= 2:
                dates = sorted(set().union(*(s.index for s in nav_parts.values())))
                dates = [d for d in dates if d >= cstart]
                if len(dates) > 1:
                    ndf = pd.DataFrame({n: s.reindex(pd.DatetimeIndex(dates)).ffill()
                                         for n, s in nav_parts.items()})
                    wdf = ndf.notna().astype(float)
                    for c in wdf.columns:
                        wdf[c] *= w.get(c, 0)
                    ws = wdf.sum(axis=1).replace(0, np.nan)
                    wdf = wdf.div(ws, axis=0)
                    nc = (ndf.fillna(0) * wdf).sum(axis=1)
                    nc = nc / nc.iloc[0]
                    metrics["Combined"]["max_dd"] = ((nc - nc.cummax()) / nc.cummax()).min() * 100
                    cret = nc.pct_change().dropna()
                    if len(cret) > 1:
                        nv = (1 + cret).cumprod()
                        metrics["Combined"]["total_return"] = (nv.iloc[-1] / nv.iloc[0] - 1) * 100
                        nd = (cret.index[-1] - cret.index[0]).days
                        if nd > 0:
                            ann = ((nv.iloc[-1] / nv.iloc[0]) ** (365.25 / nd) - 1) * 100
                            metrics["Combined"]["annual"] = ann
                            metrics["Combined"]["calmar"] = ann / abs(metrics["Combined"]["max_dd"]) \
                                if metrics["Combined"]["max_dd"] != 0 else 0

    return metrics


###############################################################################
#  Part 4 — 输出格式
###############################################################################

def fmt_table(metrics, title=""):
    lines = []
    if title:
        lines.append(f"\n{'=' * 90}")
        lines.append(f"  {title}")
        lines.append(f"{'=' * 90}")
    cs = [k for k in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C", "Combined"] if k in metrics]
    lines.append(f"  {'指标':>12}" + "".join(f"  {c:>12}" for c in cs))
    lines.append("  " + "-" * (14 + 14 * len(cs)))
    for label, key, fmt, suf in [("年化收益", "annual", ".2f", "%"), ("波动率", "vol", ".2f", "%"),
                                   ("夏普比率", "sharpe", ".2f", ""), ("最大回撤", "max_dd", ".2f", "%"),
                                   ("卡尔玛比率", "calmar", ".2f", ""), ("月胜率", "win_rate", ".1f", "%"),
                                   ("累计收益", "total_return", ".2f", "%")]:
        row = f"  {label:>12}"
        for c in cs:
            v = metrics.get(c, {}).get(key)
            row += f"  {v:>11{fmt}}{suf}" if v is not None else f"  {'N/A':>12}"
        lines.append(row)
    return "\n".join(lines)


def fmt_comparison(old_m, new_m, title=""):
    lines = []
    if title:
        lines.append(f"\n{'=' * 90}")
        lines.append(f"  {title}")
        lines.append(f"{'=' * 90}")
    lines.append(f"  {'指标':>12}  {'旧组合':>12}  {'新组合':>12}  {'差值':>12}")
    lines.append("  " + "-" * 56)
    for label, key, fmt, suf in [("年化收益", "annual", ".2f", "%"), ("波动率", "vol", ".2f", "%"),
                                   ("夏普比率", "sharpe", ".2f", ""), ("最大回撤", "max_dd", ".2f", "%"),
                                   ("卡尔玛比率", "calmar", ".2f", ""), ("月胜率", "win_rate", ".1f", "%"),
                                   ("累计收益", "total_return", ".2f", "%")]:
        oc = old_m.get("Combined", {}).get(key)
        nc = new_m.get("Combined", {}).get(key)
        dc = (nc - oc) if (nc is not None and oc is not None) else None
        row = f"  {label:>12}"
        for v in [oc, nc]:
            row += f"  {v:>11{fmt}}{suf}" if v is not None else f"  {'N/A':>12}"
        row += f"  {dc:>+11{fmt}}{suf}" if dc is not None else f"  {'N/A':>12}"
        lines.append(row)
    return "\n".join(lines)


###############################################################################
#  Part 5 — 主程序
###############################################################################

###############################################################################
#  Sub-B v5.7 参数配置
###############################################################################
SUBB_NEW_LB = 160                   # v5.4=120 → v5.7=160
SUBB_NEW_REBALANCE_THRESHOLD = 1.0  # v5.4=1.3 → v5.7=1.0 (移除替换阈值)


if __name__ == "__main__":
    print("=" * 100)
    print("  策略组合 v5.8 — Sub-A(乖离动量) + Sub-A-DK(多配对Top-1) + Sub-B(参数优化) + 移除冷却期")
    print("=" * 100)

    v54 = load_v54(V54_PATH)
    bot = v54.CombinedStrategyV4()
    msg = ProgressMsg()

    print("\n📡 从API获取数据...\n")
    cn_close, cn_dk_close, us_rot_close, us_prod_daily = bot._fetch_data(msg)

    print("\n📡 获取国债ETF...\n")
    try:
        bond_df, bond_src = v54.fetch_cn_kline(BOND_SECID)
        print(f"  国债ETF: {bond_df.index[0].strftime('%Y-%m-%d')} ~ "
              f"{bond_df.index[-1].strftime('%Y-%m-%d')} [{bond_src}]")
    except Exception as e:
        raise RuntimeError(f"国债ETF数据获取失败: {e}")

    cn_close_new = cn_close.copy()
    cn_close_new[BOND_SECID] = bond_df["close"].reindex(cn_close_new.index)
    cn_close_new = cn_close_new.ffill().dropna()
    print(f"\n  新Sub-A数据: {cn_close_new.index[0].strftime('%Y-%m-%d')} ~ "
          f"{cn_close_new.index[-1].strftime('%Y-%m-%d')}, {len(cn_close_new)}行")

    # ── 基线: v5.4 原版全部策略 ──
    print("\n⏳ 运行v5.4原版策略 (基线)...\n")
    (cn_result_old, cn_dk_result_old, us_rot_result_old,
     prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details) = \
        bot._run_strategies(cn_close, cn_dk_close, us_rot_close, us_prod_daily)

    # ── 新 Sub-A (v5.5) ──
    print("⏳ 运行新Sub-A (乖离动量)...\n")
    new_suba = BiasMotionStrategy()
    cn_result_new = new_suba.run(cn_close_new)

    # ── 新 Sub-A-DK (v5.6) ──
    print("⏳ 运行新Sub-A-DK (多配对Top-1 + 二值R²)...\n")
    new_dk = MultiPairDKStrategy()
    cn_dk_result_new = new_dk.run(cn_close, cn_dk_close)
    print(f"  新DK数据: {cn_dk_result_new.index[0].strftime('%Y-%m-%d')} ~ "
          f"{cn_dk_result_new.index[-1].strftime('%Y-%m-%d')}, {len(cn_dk_result_new)}行")

    # ── 新 Sub-B (v5.7): LB=160, threshold=1.0 ──
    print("⏳ 运行新Sub-B (LB=160, 无替换阈值)...\n")
    ORIG_LB = v54.US_ROT_LB
    v54.US_ROT_LB = SUBB_NEW_LB
    us_rot_result_new = v54.run_us_rotation(
        us_rot_close, v54.US_ROT_POOL,
        top_n=3,
        threshold=SUBB_NEW_REBALANCE_THRESHOLD,
        min_turnover=v54.US_ROT_MIN_TURNOVER,
        btc_ticker=v54.US_ROT_BTC_TICKER,
        btc_start=v54.US_ROT_BTC_START,
        btc_max_w=v54.US_ROT_BTC_MAX_W)
    # VolReg overlay (同v5.4参数: SHORT=10, LONG=250, THRESHOLD=2.0)
    v54.US_ROT_VOLREG_SHORT_W = 10
    v54.US_ROT_VOLREG_LONG_W = 250
    v54.US_ROT_VOLREG_THRESHOLD = 2.0
    us_rot_result_new = v54.apply_vol_regime_overlay(us_rot_result_new, us_rot_close["SPY"])
    v54.US_ROT_LB = ORIG_LB
    print(f"  新Sub-B数据: {us_rot_result_new.index[0].strftime('%Y-%m-%d')} ~ "
          f"{us_rot_result_new.index[-1].strftime('%Y-%m-%d')}, {len(us_rot_result_new)}行")

    end_date = min(cn_result_old.index[-1], cn_result_new.index[-1],
                   cn_dk_result_old.index[-1], cn_dk_result_new.index[-1],
                   us_rot_result_old.index[-1], us_rot_result_new.index[-1])

    periods = [
        ("近4年",  end_date - pd.DateOffset(years=4)),
        ("近8年",  end_date - pd.DateOffset(years=8)),
        ("近12年", end_date - pd.DateOffset(years=12)),
    ]

    print(f"\n  回测截止: {end_date.strftime('%Y-%m-%d')}")
    print(f"  权重: Sub-A 15%, Sub-A-DK 15%, Sub-B 40%, Sub-C 30%")
    print(f"\n  Sub-B 变更: LB 120→{SUBB_NEW_LB}, REBALANCE_THRESHOLD 1.3→{SUBB_NEW_REBALANCE_THRESHOLD}")
    print(f"  Sub-A/DK 变更: 冷却期(COOLDOWN_DAYS)已移除")

    for period_name, start_date in periods:
        print(f"\n\n{'='*100}")
        print(f"  {period_name}  ({start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')})")
        print(f"{'='*100}")

        # 旧: v5.4 全部
        old_m = compute_metrics(
            cn_result_old, cn_dk_result_old, us_rot_result_old,
            us_prod_daily, prod_sig_a, prod_sig_b, prod_nav,
            start_date, end_date, v54)

        # 新: v5.8 (新Sub-A + 新DK 无冷却期 + 新Sub-B)
        new_m = compute_metrics(
            cn_result_new, cn_dk_result_new, us_rot_result_new,
            us_prod_daily, prod_sig_a, prod_sig_b, prod_nav,
            start_date, end_date, v54)

        print(fmt_table(old_m, f"v5.4 基线 — {period_name}"))
        print(fmt_table(new_m, f"v5.8 (全部优化) — {period_name}"))
        print(fmt_comparison(old_m, new_m, f"v5.4 → v5.8 总对比 — {period_name}"))

    print("\n\n✅ 完成")

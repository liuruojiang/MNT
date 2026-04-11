# poe: privacy_shield=half
"""
策略组合 v5.5 — 子策略A改造版
===============================================================
变更: Sub-A 从 v5.4 的 MA-Turning 轮动 改为 乖离动量+R²过滤+国债

v5.4 Sub-A: run_cn_strategy(cn_close, CN_STOCK_CODES)
  - 基于 MA20 turning point 信号选股
  - 仅在5只权益ETF中轮动
  - 过拟合测试未通过 (前后半段收益差异大)

v5.5 Sub-A: BiasMotionStrategy.run(cn_close_with_bond)
  - 乖离动量 = slope( price/MA60 归一化后最近20日 ) × 10000
  - R²(20) >= 0.3 过滤: 趋势不明确→Cash
  - 国债ETF(511010)加入轮动池, 不受R²过滤
  - 冷却期3天, 佣金0.1%

其他子策略不变:
  - Sub-A-DK: 中证1000/上证50 多空 (v5.4 run_dk_strategy)
  - Sub-B: 美股9ETF轮动 + VolReg (v5.4 run_us_rotation)
  - Sub-C: 美股生产组合 + Vol-Scaling (v5.4 simulate_prod_btc_phased)
  - 权重: Sub-A 15%, Sub-A-DK 15%, Sub-B 40%, Sub-C 30%

运行方式: 直接执行本文件, 从API获取数据, 对比新旧Sub-A组合表现
依赖: 同目录下需有 v5.4 脚本文件
===============================================================
"""

import sys
import importlib.util
import pandas as pd
import numpy as np
import time

# ─────────────────────────────────────────────
# 全局配置
# ─────────────────────────────────────────────
V54_PATH = "1_mnt_mnt_strategy_signal_v5.4_aggressive.py"   # v5.4 脚本路径
BOND_SECID = "1.511010"                                      # 国债ETF代码


###############################################################################
#  Part 1 — 新 Sub-A 策略: 乖离动量 + R² 过滤 + 国债ETF
###############################################################################

class BiasMotionConfig:
    """乖离动量策略参数"""
    # 标的池
    EQUITY_CODES = ["1.515100", "0.159915", "1.000300", "1.000852", "1.000905"]
    BOND_CODE = "1.511010"
    ALL_CODES = EQUITY_CODES + [BOND_CODE]

    # 乖离动量参数
    BIAS_N = 60          # 均线周期 (price / MA60)
    MOM_DAY = 20         # 斜率拟合窗口

    # R² 过滤
    R2_WINDOW = 20       # R²滚动窗口
    R2_THRESHOLD = 0.3   # R²最低门槛

    # 交易参数
    COOLDOWN_DAYS = 3    # 换仓冷却期
    COMMISSION = 0.001   # 单边佣金 0.1%

    # 现金收益
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
        与 v5.4 的 run_cn_strategy 返回格式兼容
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
        last_trade_day = -999

        for i in range(start_idx, len(close_df)):
            date = close_df.index[i]

            # 1. 乖离动量排名
            scores = {}
            for code in codes:
                val = bias_dict[code].iloc[i]
                if not np.isnan(val):
                    scores[code] = val

            # 2. 选最优 + R²过滤
            ideal = "cash"
            if scores:
                best = max(scores, key=scores.get)
                if has_bond and best == cfg.BOND_CODE:
                    ideal = best                    # 国债不过滤
                else:
                    r2_val = r2_dict.get(best, pd.Series(dtype=float)).iloc[i] \
                        if best in r2_dict and i < len(r2_dict[best]) else np.nan
                    if not np.isnan(r2_val) and r2_val >= cfg.R2_THRESHOLD:
                        ideal = best

            # 3. 冷却期
            target = None
            if ideal != holding and (i - last_trade_day) >= cfg.COOLDOWN_DAYS:
                target = ideal
                last_trade_day = i

            # 4. 日收益
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
#  Part 2 — v5.4 模块加载 + 指标计算
###############################################################################

def load_v54(path):
    """导入 v5.4 模块 (mock poe 以便脱离 Poe 环境运行)"""
    class _FakePoe:
        class BotError(Exception):
            pass
        class Message:
            def __init__(self, **kw):
                self.text = kw.get("text", "")
                self.sender = kw.get("sender", "user")
                self.attachments = kw.get("attachments", [])
                self.parameters = kw.get("parameters", {})
        def start_message(self):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def write(self, *a):
            pass
        def update_settings(self, *a):
            pass

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
    def write(self, text):
        print(text, end="")
    def __enter__(self):
        return self
    def __exit__(self, *a):
        pass
    def add_attachment(self, *a, **kw):
        pass
    def attach_file(self, *a, **kw):
        pass


def compute_metrics(cn_result, cn_dk_result, us_rot_result,
                    us_prod_daily, prod_sig_a, prod_sig_b, prod_nav,
                    start_date, end_date, v54):
    """
    照搬 v5.4 _handle_performance 的完整指标计算:
      月度收益 → 对齐 → 组合NAV → calc_monthly_metrics → 日度覆盖 MaxDD/Annual
    """
    # ── 月度收益 ──
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

    # ── 对齐 + 组合NAV ──
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

    # ── 期间过滤 ──
    sp, ep = start_date.to_period("M"), end_date.to_period("M")
    mask = (aligned.index >= sp) & (aligned.index <= ep)
    filt = aligned[mask]

    # ── 月度基础指标 ──
    metrics = {}
    for name, series in [("Sub-A", cn_m), ("Sub-A-DK", dk_m), ("Sub-B", us_m), ("Sub-C", prod_m)]:
        s = series[(series.index >= sp) & (series.index <= ep)]
        if len(s) >= 1:
            metrics[name] = v54.calc_monthly_metrics(s)
    if len(filt) >= 1:
        metrics["Combined"] = v54.calc_monthly_metrics(filt["Combined"])

    # ── 日度覆盖 ──
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

    # ── Combined 日度覆盖 ──
    if "Combined" in metrics:
        cstart = max(d.index[0] for d in [cn_d, dk_d, us_d, subc_d] if len(d) > 0)
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
#  Part 3 — 输出格式
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
    lines.append(f"  {'指标':>12}  {'旧Sub-A':>12}  {'新Sub-A':>12}  {'旧组合':>12}  {'新组合':>12}  {'组合差值':>12}")
    lines.append("  " + "-" * 86)
    for label, key, fmt, suf in [("年化收益", "annual", ".2f", "%"), ("波动率", "vol", ".2f", "%"),
                                   ("夏普比率", "sharpe", ".2f", ""), ("最大回撤", "max_dd", ".2f", "%"),
                                   ("卡尔玛比率", "calmar", ".2f", ""), ("月胜率", "win_rate", ".1f", "%"),
                                   ("累计收益", "total_return", ".2f", "%")]:
        oa = old_m.get("Sub-A", {}).get(key)
        na = new_m.get("Sub-A", {}).get(key)
        oc = old_m.get("Combined", {}).get(key)
        nc = new_m.get("Combined", {}).get(key)
        dc = (nc - oc) if (nc is not None and oc is not None) else None
        row = f"  {label:>12}"
        for v in [oa, na, oc, nc]:
            row += f"  {v:>11{fmt}}{suf}" if v is not None else f"  {'N/A':>12}"
        row += f"  {dc:>+11{fmt}}{suf}" if dc is not None else f"  {'N/A':>12}"
        lines.append(row)
    return "\n".join(lines)


###############################################################################
#  Part 4 — 主程序
###############################################################################

if __name__ == "__main__":
    print("=" * 90)
    print("  策略组合 v5.5 — 新Sub-A(乖离动量) + v5.4基础设施")
    print("=" * 90)

    # ── 加载 v5.4 ──
    v54 = load_v54(V54_PATH)
    bot = v54.CombinedStrategyV4()
    msg = ProgressMsg()

    # ── 从API取数据 ──
    print("\n📡 从API获取数据...\n")
    cn_close, cn_dk_close, us_rot_close, us_prod_daily = bot._fetch_data(msg)

    # ── 额外获取国债ETF ──
    print("\n📡 获取国债ETF...\n")
    try:
        bond_df, bond_src = v54.fetch_cn_kline(BOND_SECID)
        print(f"  国债ETF: {bond_df.index[0].strftime('%Y-%m-%d')} ~ "
              f"{bond_df.index[-1].strftime('%Y-%m-%d')} [{bond_src}]")
    except Exception as e:
        raise RuntimeError(f"国债ETF数据获取失败: {e}")

    # ── 构建新Sub-A数据 ──
    cn_close_new = cn_close.copy()
    cn_close_new[BOND_SECID] = bond_df["close"].reindex(cn_close_new.index)
    cn_close_new = cn_close_new.ffill().dropna()
    print(f"\n  新Sub-A数据: {cn_close_new.index[0].strftime('%Y-%m-%d')} ~ "
          f"{cn_close_new.index[-1].strftime('%Y-%m-%d')}, {len(cn_close_new)}行")

    # ── 运行v5.4原版策略 ──
    print("\n⏳ 运行v5.4原版策略...\n")
    (cn_result_old, cn_dk_result, us_rot_result,
     prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details) = \
        bot._run_strategies(cn_close, cn_dk_close, us_rot_close, us_prod_daily)

    # ── 运行新Sub-A ──
    print("⏳ 运行新Sub-A (乖离动量)...\n")
    new_suba = BiasMotionStrategy()
    cn_result_new = new_suba.run(cn_close_new)

    # ── 计算指标: 多时段 ──
    end_date = min(cn_result_old.index[-1], cn_result_new.index[-1],
                   cn_dk_result.index[-1], us_rot_result.index[-1])
    start_2012 = pd.Timestamp("2012-01-01")

    periods = [
        ("2012年起至今", start_2012),
        ("近8年", end_date - pd.DateOffset(years=8)),
        ("近4年", end_date - pd.DateOffset(years=4)),
    ]

    for period_name, start_date in periods:
        old_m = compute_metrics(cn_result_old, cn_dk_result, us_rot_result,
                                us_prod_daily, prod_sig_a, prod_sig_b, prod_nav,
                                start_date, end_date, v54)
        new_m = compute_metrics(cn_result_new, cn_dk_result, us_rot_result,
                                us_prod_daily, prod_sig_a, prod_sig_b, prod_nav,
                                start_date, end_date, v54)

        print(fmt_table(old_m, f"旧Sub-A 组合 — {period_name}"))
        print(fmt_table(new_m, f"新Sub-A(乖离动量) 组合 — {period_name}"))
        print(fmt_comparison(old_m, new_m, f"新旧对比 — {period_name}"))

    print("\n\n✅ 完成")

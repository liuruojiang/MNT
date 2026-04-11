"""
最终策略: 乖离动量(60,20) + R²(20,0.3) + 国债ETF轮动
============================================================
选股: 乖离动量 = slope( price/MA60 归一化后最近20日 ) × 10000
      选乖离动量最高的ETF
过滤: 权益ETF的R²(20) >= 0.3 才持有, 否则→Cash
      国债ETF不受R²过滤
调仓: 每日检查, 3日冷却期
费用: 单边0.1%佣金
现金: 年化3%无风险收益

标的池:
  权益: 1.515100(中证红利), 0.159915(创业板), 1.000300(沪深300),
        1.000852(中证1000), 1.000905(中证500)
  债券: 1.511010(国债ETF) — 不受R²过滤
"""
import pandas as pd
import numpy as np


# ── 策略参数 ──
class StrategyConfig:
    # 标的
    EQUITY_CODES = ["1.515100", "0.159915", "1.000300", "1.000852", "1.000905"]
    BOND_CODE = "1.511010"
    ALL_CODES = EQUITY_CODES + [BOND_CODE]

    # 乖离动量参数
    BIAS_N = 60        # 均线周期 (计算偏离度: price / MA60)
    MOM_DAY = 20       # 拟合斜率窗口 (最近20日偏离度的线性回归)

    # R²过滤参数
    R2_WINDOW = 20     # R²滚动窗口
    R2_THRESHOLD = 0.3 # R²最低门槛 (趋势不明确→Cash)

    # 交易参数
    COOLDOWN_DAYS = 3  # 换仓冷却期 (防止频繁交易)
    COMMISSION = 0.001 # 单边佣金 0.1%

    # 无风险收益
    RF_ANNUAL = 0.03
    TRADING_DAYS = 244
    RF_DAILY = (1 + RF_ANNUAL) ** (1 / TRADING_DAYS) - 1

    # 数据
    CN_DATA_PATH = "mnt/mnt_strategy_data_cn.csv"
    BOND_DATA_PATH = "mnt/bond_511010.csv"

    CN_NAMES = {
        "1.515100": "中证红利", "0.159915": "创业板", "1.000300": "沪深300",
        "1.000852": "中证1000", "1.000905": "中证500", "1.511010": "国债ETF",
        "cash": "现金",
    }


class Strategy:
    """乖离动量 + R²过滤 + 国债ETF轮动策略"""

    def __init__(self, config=None):
        self.cfg = config or StrategyConfig()

    # ── 指标计算 ──

    def calc_bias_momentum(self, close_series):
        """
        乖离动量:
        1) bias = price / MA(BIAS_N) — 价格偏离均线的程度
        2) 取最近 MOM_DAY 天的 bias
        3) 归一化: bias / bias[0] — 消除绝对水平差异
        4) 线性拟合斜率 × 10000 — 衡量偏离度的变化速度(加速度)
        """
        cfg = self.cfg
        prices = close_series.values.astype(float)
        n = len(prices)
        result = np.full(n, np.nan)

        ma = close_series.rolling(cfg.BIAS_N).mean().values
        total_lookback = cfg.BIAS_N + cfg.MOM_DAY - 1

        x = np.arange(cfg.MOM_DAY, dtype=float)

        for i in range(total_lookback, n):
            # 取最近 MOM_DAY 天的偏离度
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

            # 归一化 + 线性拟合
            bias_norm = bias_window / bias_window[0]
            slope = np.polyfit(x, bias_norm, 1)[0]
            result[i] = slope * 10000

        return pd.Series(result, index=close_series.index)

    def calc_rolling_r2(self, close_series):
        """
        滚动R²: 价格对时间的线性回归拟合优度 (0~1)
        R²高 = 趋势平滑可信; R²低 = 震荡无方向
        """
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

    # ── 交易成本 ──

    def _calc_cost(self, old_holding, new_holding):
        """计算换仓成本"""
        if old_holding == new_holding:
            return 1.0
        elif old_holding == "cash" or new_holding == "cash":
            # 现金↔资产: 单边佣金
            return 1 - self.cfg.COMMISSION
        else:
            # 资产↔资产: 双边佣金 (卖出旧 + 买入新)
            return (1 - self.cfg.COMMISSION) ** 2

    # ── 回测引擎 ──

    def run(self, close_df, codes=None):
        """
        运行回测
        参数:
            close_df: 收盘价DataFrame (index=date, columns=codes)
            codes: 参与轮动的标的列表, 默认ALL_CODES
        返回:
            DataFrame: date, return, holding, nav
        """
        cfg = self.cfg
        if codes is None:
            codes = cfg.ALL_CODES

        has_bond = cfg.BOND_CODE in codes
        equity_codes = [c for c in codes if c != cfg.BOND_CODE]

        # 预计算指标
        bias_dict = {}
        r2_dict = {}
        for code in codes:
            bias_dict[code] = self.calc_bias_momentum(close_df[code])
            if code != cfg.BOND_CODE:
                r2_dict[code] = self.calc_rolling_r2(close_df[code])

        # 国债也需要乖离动量用于排名 (已包含在循环中)

        start_idx = cfg.BIAS_N + cfg.MOM_DAY  # 确保所有指标有效
        holding = "cash"
        rows = []
        last_trade_day = -999

        for i in range(start_idx, len(close_df)):
            date = close_df.index[i]

            # Step 1: 计算所有标的的乖离动量得分
            scores = {}
            for code in codes:
                val = bias_dict[code].iloc[i]
                if not np.isnan(val):
                    scores[code] = val

            # Step 2: 选得分最高的标的
            ideal = "cash"
            if len(scores) > 0:
                best = max(scores, key=scores.get)

                if has_bond and best == cfg.BOND_CODE:
                    # 国债ETF不受R²过滤, 直接持有
                    ideal = best
                else:
                    # 权益ETF需通过R²过滤
                    r2_val = r2_dict[best].iloc[i] if best in r2_dict else np.nan
                    if not np.isnan(r2_val) and r2_val >= cfg.R2_THRESHOLD:
                        ideal = best
                    # else: R²不达标 → Cash

            # Step 3: 冷却期判断 + 执行换仓
            target = None
            days_since_trade = i - last_trade_day
            if ideal != holding and days_since_trade >= cfg.COOLDOWN_DAYS:
                target = ideal
                last_trade_day = i

            # Step 4: 计算日收益
            if target is not None:
                # 发生换仓
                old_h = holding
                cost_factor = self._calc_cost(old_h, target)

                if old_h == "cash":
                    day_ret = (1 + cfg.RF_DAILY) * cost_factor - 1
                else:
                    prev = close_df.iloc[i - 1][old_h]
                    curr = close_df.iloc[i][old_h]
                    asset_ret = (curr / prev - 1) if prev != 0 else 0.0
                    day_ret = (1 + asset_ret) * cost_factor - 1
                holding = target
            else:
                # 维持仓位
                if holding == "cash":
                    day_ret = cfg.RF_DAILY
                else:
                    prev = close_df.iloc[i - 1][holding]
                    curr = close_df.iloc[i][holding]
                    asset_ret = (curr / prev - 1) if prev != 0 else 0.0
                    day_ret = asset_ret

            rows.append({"date": date, "return": day_ret, "holding": holding})

        result = pd.DataFrame(rows).set_index("date")
        result["nav"] = (1 + result["return"]).cumprod()
        return result

    # ── 业绩指标 ──

    @staticmethod
    def calc_metrics(nav_series):
        """计算完整业绩指标"""
        if len(nav_series) < 2:
            return {}

        total_days = (nav_series.index[-1] - nav_series.index[0]).days
        if total_days <= 0:
            return {}

        # 年化收益
        total_return = nav_series.iloc[-1] / nav_series.iloc[0]
        ann_ret = total_return ** (365.0 / total_days) - 1

        # 最大回撤
        running_max = nav_series.cummax()
        drawdown = nav_series / running_max - 1
        max_dd = drawdown.min()

        # 波动率 & Sharpe
        daily_rets = nav_series.pct_change().dropna()
        ann_vol = daily_rets.std() * np.sqrt(244)
        sharpe = (ann_ret - 0.03) / ann_vol if ann_vol > 0 else 0

        # Calmar
        calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

        # 最大回撤持续期
        dd_start = None
        max_dd_duration = 0
        for i in range(1, len(nav_series)):
            if nav_series.iloc[i] >= running_max.iloc[i]:
                if dd_start is not None:
                    duration = (nav_series.index[i] - dd_start).days
                    if duration > max_dd_duration:
                        max_dd_duration = duration
                dd_start = None
            else:
                if dd_start is None:
                    dd_start = nav_series.index[i - 1]

        return {
            "total_return": total_return - 1,
            "ann_ret": ann_ret,
            "max_dd": max_dd,
            "ann_vol": ann_vol,
            "sharpe": sharpe,
            "calmar": calmar,
            "max_dd_duration_days": max_dd_duration,
            "total_days": total_days,
        }

    # ── 数据加载 ──

    @staticmethod
    def load_data(cn_path, bond_path, equity_codes, bond_code):
        """加载并合并数据"""
        df = pd.read_csv(cn_path, parse_dates=["date"]).set_index("date")

        # 拼接数据 (使用更长的_spliced序列)
        for col in ["1.515100", "0.159915"]:
            spliced_col = f"{col}_spliced"
            if spliced_col in df.columns:
                df[col] = df[spliced_col].combine_first(df[col])

        # 加载国债ETF
        bond_df = pd.read_csv(bond_path, parse_dates=["date"]).set_index("date")
        bond_df = bond_df.rename(columns={"close": bond_code})
        df = df.join(bond_df, how="outer")

        all_codes = equity_codes + [bond_code]
        close_df = df[all_codes].copy().ffill().dropna()
        return close_df


def generate_full_report(strategy, bt_result, close_df, label=""):
    """生成完整业绩报告"""
    cfg = strategy.cfg
    nav = bt_result["nav"]
    holdings = bt_result["holding"]
    daily_rets = bt_result["return"]

    metrics = strategy.calc_metrics(nav)
    if not metrics:
        print("数据不足, 无法生成报告")
        return

    # 前后半段
    mid = len(nav) // 2
    m_front = strategy.calc_metrics(nav.iloc[:mid])
    m_back = strategy.calc_metrics(nav.iloc[mid:])

    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"  数据: {nav.index[0].strftime('%Y-%m-%d')} ~ {nav.index[-1].strftime('%Y-%m-%d')}")
    print(f"{'='*80}")

    print(f"\n📊 核心指标:")
    print(f"  累计收益      {metrics['total_return']:.2%}")
    print(f"  年化收益      {metrics['ann_ret']:.2%}")
    print(f"  最大回撤      {metrics['max_dd']:.2%}")
    print(f"  年化波动率    {metrics['ann_vol']:.2%}")
    print(f"  Sharpe        {metrics['sharpe']:.2f}")
    print(f"  Calmar        {metrics['calmar']:.2f}")
    print(f"  终值/初值     {nav.iloc[-1] / nav.iloc[0]:.2f}x")
    print(f"  最大回撤持续  {metrics['max_dd_duration_days']}天")

    print(f"\n📊 前后半段对比:")
    if m_front and m_back:
        print(f"  前半段 年化 {m_front['ann_ret']:.2%}, MaxDD {m_front['max_dd']:.2%}")
        print(f"  后半段 年化 {m_back['ann_ret']:.2%}, MaxDD {m_back['max_dd']:.2%}")
        print(f"  前后差 {abs(m_front['ann_ret'] - m_back['ann_ret']):.2%}")

    # ── 年度收益 ──
    print(f"\n📅 年度收益:")
    bt_result_with_year = bt_result.copy()
    bt_result_with_year["year"] = bt_result_with_year.index.year
    for year, group in bt_result_with_year.groupby("year"):
        year_nav = (1 + group["return"]).cumprod()
        year_ret = year_nav.iloc[-1] / year_nav.iloc[0] - 1
        year_dd = (year_nav / year_nav.cummax() - 1).min()
        print(f"  {year}: {year_ret:>+7.2%}  MaxDD {year_dd:>7.2%}")

    # ── 月度热力图 ──
    print(f"\n📅 月度收益:")
    bt_result_with_ym = bt_result.copy()
    bt_result_with_ym["year"] = bt_result_with_ym.index.year
    bt_result_with_ym["month"] = bt_result_with_ym.index.month
    monthly = bt_result_with_ym.groupby(["year", "month"])["return"].apply(
        lambda x: (1 + x).prod() - 1
    ).unstack(level=1)

    header = "      " + "".join(f"{m:>7}" for m in range(1, 13))
    print(header)
    for year in monthly.index:
        row = f"  {year}"
        for m in range(1, 13):
            val = monthly.loc[year, m] if m in monthly.columns and not pd.isna(monthly.loc[year].get(m, np.nan)) else np.nan
            if np.isnan(val):
                row += "      -"
            else:
                row += f" {val:>+6.1%}"

        print(row)

    # ── 持仓分布 ──
    print(f"\n📦 持仓分布:")
    total = len(holdings)
    for code in cfg.ALL_CODES + ["cash"]:
        count = (holdings == code).sum()
        pct = count / total * 100
        name = cfg.CN_NAMES.get(code, code)
        if pct > 0:
            print(f"  {name:>8}: {pct:>5.1f}%  ({count}天)")

    # ── 换手统计 ──
    trades = (holdings != holdings.shift(1)).sum() - 1  # 排除第一天
    years = metrics['total_days'] / 365
    print(f"\n🔄 换手统计:")
    print(f"  总换仓次数    {trades}次")
    print(f"  年均换仓      {trades / years:.1f}次")
    print(f"  平均持仓天数  {total / max(trades, 1):.1f}天")

    # ── 最大回撤详情 ──
    running_max = nav.cummax()
    drawdown = nav / running_max - 1
    dd_min_idx = drawdown.idxmin()
    peak_before = nav.loc[:dd_min_idx].idxmax()
    # 恢复日期
    recovery_slice = nav.loc[dd_min_idx:]
    recovery_mask = recovery_slice >= running_max.loc[dd_min_idx]
    if recovery_mask.any():
        recovery_date = recovery_mask.idxmax()
        recovery_days = (recovery_date - dd_min_idx).days
    else:
        recovery_date = None
        recovery_days = None

    print(f"\n📉 最大回撤详情:")
    print(f"  峰值日期  {peak_before.strftime('%Y-%m-%d')}")
    print(f"  谷底日期  {dd_min_idx.strftime('%Y-%m-%d')}")
    print(f"  回撤幅度  {drawdown.loc[dd_min_idx]:.2%}")
    if recovery_date:
        print(f"  恢复日期  {recovery_date.strftime('%Y-%m-%d')} ({recovery_days}天)")
    else:
        print(f"  恢复日期  尚未恢复")

    return metrics


# ── 主程序 ──
if __name__ == "__main__":
    cfg = StrategyConfig()
    strategy = Strategy(cfg)

    # 加载数据
    close_df = strategy.load_data(
        cfg.CN_DATA_PATH, cfg.BOND_DATA_PATH,
        cfg.EQUITY_CODES, cfg.BOND_CODE
    )
    print(f"数据加载: {close_df.index[0].strftime('%Y-%m-%d')} ~ "
          f"{close_df.index[-1].strftime('%Y-%m-%d')}, {len(close_df)}行")

    # 含国债回测
    bt_new = strategy.run(close_df, cfg.ALL_CODES)
    m_new = generate_full_report(
        strategy, bt_new, close_df,
        label="乖离动量(60,20) + R²(20,0.3) + 国债ETF"
    )

    # 无国债回测 (对照)
    close_old = close_df[cfg.EQUITY_CODES].copy()
    bt_old = strategy.run(close_old, cfg.EQUITY_CODES)
    m_old = generate_full_report(
        strategy, bt_old, close_old,
        label="乖离动量(60,20) + R²(20,0.3) 无国债 (对照)"
    )

    # 国债贡献
    if m_new and m_old:
        print(f"\n{'='*80}")
        print(f"  国债ETF贡献")
        print(f"{'='*80}")
        print(f"  Δ年化收益  {m_new['ann_ret'] - m_old['ann_ret']:>+.2%}")
        print(f"  ΔMaxDD     {m_new['max_dd'] - m_old['max_dd']:>+.2%}")
        print(f"  ΔSharpe    {m_new['sharpe'] - m_old['sharpe']:>+.2f}")
        print(f"  ΔCalmar    {m_new['calmar'] - m_old['calmar']:>+.2f}")

import builtins
import importlib.util
import json
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "mnt_bot V 7.0 plus.py"
OUT_DIR = ROOT / "docs" / "subb_mix_robustness_20260424"
_STRATEGY_MOD = None

BASELINE_LB = 160
MIX_LBS = [130, 260, 390]
NEIGHBOR_SHORT = [120, 130, 140]
NEIGHBOR_MID = [240, 260, 280]
NEIGHBOR_LONG = [360, 390, 420]
ROLLING_WINDOWS = [("roll_3y", 756), ("roll_5y", 1260)]
ROLLING_STEP = 63
REGIMES = [
    ("post_gfc_rebound", "2008-12-15", "2009-12-31", "金融危机后反弹"),
    ("qe_bull", "2010-01-01", "2014-12-31", "QE牛市"),
    ("sideways_2015_2016", "2015-01-01", "2016-12-31", "震荡/加息切换"),
    ("late_cycle_2017_2019", "2017-01-01", "2019-12-31", "低波牛市+2018回撤"),
    ("covid_2020", "2020-01-01", "2020-12-31", "疫情冲击与反弹"),
    ("inflation_bear_2021_2022", "2021-01-01", "2022-12-31", "通胀加息/熊市"),
    ("ai_rebound_2023_now", "2023-01-01", "2026-04-23", "AI/高集中反弹"),
    ("last_10y", "2016-04-25", "2026-04-23", "最近10年"),
    ("last_5y", "2021-04-23", "2026-04-23", "最近5年"),
    ("full_common", "2008-12-15", "2026-04-23", "全样本公共区间"),
]
COMMISSION_SCENARIOS = [
    ("0bps", 0.0),
    ("10bps", 0.001),
    ("20bps", 0.002),
]


class _PoeStub:
    query = None
    default_chat = []

    class BotError(Exception):
        pass

    def update_settings(self, settings):
        self.settings = settings

    def start_message(self):
        raise RuntimeError("poe unavailable")

    def call(self, *args, **kwargs):
        raise RuntimeError("poe unavailable")


@dataclass
class MarketContext:
    mod: object
    close_df: pd.DataFrame
    open_map: dict
    ranking_codes: list[str]


def load_strategy_module():
    global _STRATEGY_MOD
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = _PoeStub()
    spec = importlib.util.spec_from_file_location("mnt_bot_v70_robustness", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if had_poe:
        builtins.poe = old_poe
    else:
        delattr(builtins, "poe")
    _STRATEGY_MOD = mod
    return mod


def build_market_context(mod, exclude_btc=True):
    ranking_codes = [a for a in mod.US_ROT_POOL if (a != "BTC-USD" or not exclude_btc)]
    needed = sorted(set(ranking_codes + ["BIL", "SPY", mod.US_ROT_EMXC_BT_PROXY]))
    us_raw = {}
    for ticker in needed:
        df, _source = mod.fetch_yahoo(ticker, start_date="2003-01-01")
        if df is None or len(df) == 0 or "close" not in df.columns:
            raise RuntimeError(f"empty data for {ticker}")
        us_raw[ticker] = df

    rot_tickers = ranking_codes + ["BIL"]
    rot_tickers_core = [t for t in rot_tickers if t != "EMXC"]
    if mod.US_ROT_EMXC_BT_PROXY not in rot_tickers_core and mod.US_ROT_EMXC_BT_PROXY in us_raw:
        rot_tickers_core.append(mod.US_ROT_EMXC_BT_PROXY)
    close_df = pd.concat(
        [us_raw[t][["close"]].rename(columns={"close": t}) for t in rot_tickers_core if t in us_raw],
        axis=1,
    ).ffill().dropna()

    if "EMXC" in ranking_codes:
        hybrid = close_df[mod.US_ROT_EMXC_BT_PROXY].copy().rename("EMXC")
        emxc_ser = us_raw["EMXC"]["close"].reindex(hybrid.index)
        switch_idx = hybrid.index >= mod.US_ROT_EMXC_BT_START
        first_emxc_date = emxc_ser.loc[switch_idx].first_valid_index()
        if first_emxc_date is not None:
            scale_factor = hybrid.loc[first_emxc_date] / emxc_ser.loc[first_emxc_date]
            hybrid.loc[switch_idx] = emxc_ser.loc[switch_idx] * scale_factor
        close_df["EMXC"] = hybrid
        if mod.US_ROT_EMXC_BT_PROXY in close_df.columns and mod.US_ROT_EMXC_BT_PROXY not in ranking_codes:
            close_df = close_df.drop(columns=[mod.US_ROT_EMXC_BT_PROXY])

    if "SPY" in us_raw:
        close_df["SPY"] = us_raw["SPY"]["close"].reindex(close_df.index)

    last_stock_date = max(us_raw[t].index[-1] for t in rot_tickers if t in us_raw)
    close_df = close_df.loc[:last_stock_date]
    open_map = {t: df["open"] for t, df in us_raw.items() if "open" in df.columns}
    return MarketContext(mod=mod, close_df=close_df, open_map=open_map, ranking_codes=ranking_codes)


def apply_volreg(ctx: MarketContext, result: pd.DataFrame) -> pd.DataFrame:
    if ctx.mod.US_ROT_VOLREG_ENABLED and "SPY" in ctx.close_df.columns:
        return ctx.mod.apply_vol_regime_overlay(result, ctx.close_df["SPY"])
    return result


def run_single(ctx: MarketContext, lb: int, commission: float | None = None) -> pd.DataFrame:
    mod = ctx.mod
    old_lb = mod.US_ROT_LB
    old_commission = mod.US_ROT_COMMISSION
    mod.US_ROT_LB = lb
    if commission is not None:
        mod.US_ROT_COMMISSION = commission
    try:
        result = mod.run_us_rotation(
            ctx.close_df,
            ctx.ranking_codes,
            btc_ticker=None,
            btc_start=None,
            btc_max_w=None,
            us_open=ctx.open_map,
        )
        return apply_volreg(ctx, result)
    finally:
        mod.US_ROT_LB = old_lb
        mod.US_ROT_COMMISSION = old_commission


def run_target_average(
    ctx: MarketContext,
    lbs: list[int],
    ranking_codes: list[str] | None = None,
    commission: float | None = None,
) -> pd.DataFrame:
    mod = ctx.mod
    ranking_codes = ranking_codes or ctx.ranking_codes
    old_commission = mod.US_ROT_COMMISSION
    if commission is not None:
        mod.US_ROT_COMMISSION = commission

    momentum_by_lb = {lb: ctx.close_df.div(ctx.close_df.shift(lb)).sub(1) for lb in lbs}
    vol_df = ctx.close_df.pct_change().rolling(mod.US_ROT_VOL_LB).std() * np.sqrt(mod.US_TRADING_DAYS)
    start_idx = max(max(lbs), mod.US_ROT_VOL_LB, mod.US_ROT_VOL_WINDOW) + 1
    signal_days = mod._us_signal_days(ctx.close_df, start_idx)
    w_assets = list(ranking_codes) + ["BIL"]

    act = {"BIL": 1.0}
    holdings = {"BIL": 1.0}
    pending_act = None
    pending_comm = 0.0
    scale = 1.0
    hist = []
    rows = []

    try:
        for i in range(start_idx, len(ctx.close_df)):
            if len(hist) >= mod.US_ROT_VOL_WINDOW:
                rv = np.std(hist[-mod.US_ROT_VOL_WINDOW :], ddof=1) * np.sqrt(mod.US_TRADING_DAYS)
                scale = min(max(mod.US_ROT_TARGET_VOL / rv, 0.05), mod.US_ROT_MAX_LEV) if rv > 0.001 else mod.US_ROT_MAX_LEV

            if pending_act is not None:
                open_row = mod._us_open_row(ctx.close_df.index[i], w_assets, ctx.open_map, ctx.close_df)
                overnight = mod._us_weighted_return(holdings, ctx.close_df.iloc[i - 1], open_row)
                intraday = mod._us_weighted_return(pending_act, open_row, ctx.close_df.iloc[i])
                adj = (1 + overnight) * (1 + intraday) * (1 - pending_comm) - 1
                holdings = dict(pending_act)
                pending_act = None
                pending_comm = 0.0
            else:
                adj = mod._us_weighted_return(holdings, ctx.close_df.iloc[i - 1], ctx.close_df.iloc[i])

            hist.append(adj)
            is_sig = i in signal_days
            rebalanced = False
            new_act = dict(act)

            if is_sig:
                acts = []
                for lb in lbs:
                    raw = mod._us_raw_weights(
                        momentum_by_lb[lb].iloc[i],
                        vol_df.iloc[i],
                        ranking_codes,
                        3,
                        mod.US_ROT_ABS_THRESHOLD,
                    )
                    acts.append(mod._us_model_b(raw, scale))
                keys = set().union(*[a.keys() for a in acts]) if acts else {"BIL"}
                new_act = {k: sum(a.get(k, 0.0) for a in acts) / len(acts) for k in keys}
                prev_act = {a: act.get(a, 0.0) for a in w_assets} if rows else {"BIL": 1.0}
                turnover = sum(abs(new_act.get(a, 0.0) - prev_act.get(a, 0.0)) for a in set(new_act) | set(prev_act) if a != "BIL")
                if turnover >= mod.US_ROT_MIN_TURNOVER:
                    pending_act = dict(new_act)
                    pending_comm = turnover * mod.US_ROT_COMMISSION if turnover > 0 else 0.0
                    act = new_act
                    rebalanced = True

            row = {"date": ctx.close_df.index[i], "return": adj, "is_signal": is_sig, "rebalanced": rebalanced}
            for asset in w_assets:
                row[f"w_{asset}"] = act.get(asset, 0.0)
            rows.append(row)

        df = pd.DataFrame(rows).set_index("date")
        df["nav"] = (1 + df["return"]).cumprod()
        return apply_volreg(ctx, df)
    finally:
        mod.US_ROT_COMMISSION = old_commission


def mix_signal_then_top_weights(
    momentum_rows: dict[int, pd.Series],
    vol_row: pd.Series,
    ranking_codes: list[str],
    scale: float,
    top_n: int = 3,
    abs_threshold: float = 0.0,
):
    global _STRATEGY_MOD
    if _STRATEGY_MOD is None:
        load_strategy_module()
    avg_signal = pd.concat(momentum_rows, axis=1).mean(axis=1)
    raw = _STRATEGY_MOD._us_raw_weights(
        avg_signal,
        vol_row,
        ranking_codes,
        top_n,
        abs_threshold,
    )
    act = _STRATEGY_MOD._us_model_b(raw, scale)
    return act, avg_signal


def run_signal_average_top3(
    ctx: MarketContext,
    lbs: list[int],
    ranking_codes: list[str] | None = None,
    commission: float | None = None,
) -> pd.DataFrame:
    mod = ctx.mod
    ranking_codes = ranking_codes or ctx.ranking_codes
    old_commission = mod.US_ROT_COMMISSION
    if commission is not None:
        mod.US_ROT_COMMISSION = commission

    momentum_by_lb = {lb: ctx.close_df.div(ctx.close_df.shift(lb)).sub(1) for lb in lbs}
    vol_df = ctx.close_df.pct_change().rolling(mod.US_ROT_VOL_LB).std() * np.sqrt(mod.US_TRADING_DAYS)
    start_idx = max(max(lbs), mod.US_ROT_VOL_LB, mod.US_ROT_VOL_WINDOW) + 1
    signal_days = mod._us_signal_days(ctx.close_df, start_idx)
    w_assets = list(ranking_codes) + ["BIL"]

    act = {"BIL": 1.0}
    holdings = {"BIL": 1.0}
    pending_act = None
    pending_comm = 0.0
    scale = 1.0
    hist = []
    rows = []

    try:
        for i in range(start_idx, len(ctx.close_df)):
            if len(hist) >= mod.US_ROT_VOL_WINDOW:
                rv = np.std(hist[-mod.US_ROT_VOL_WINDOW :], ddof=1) * np.sqrt(mod.US_TRADING_DAYS)
                scale = min(max(mod.US_ROT_TARGET_VOL / rv, 0.05), mod.US_ROT_MAX_LEV) if rv > 0.001 else mod.US_ROT_MAX_LEV

            if pending_act is not None:
                open_row = mod._us_open_row(ctx.close_df.index[i], w_assets, ctx.open_map, ctx.close_df)
                overnight = mod._us_weighted_return(holdings, ctx.close_df.iloc[i - 1], open_row)
                intraday = mod._us_weighted_return(pending_act, open_row, ctx.close_df.iloc[i])
                adj = (1 + overnight) * (1 + intraday) * (1 - pending_comm) - 1
                holdings = dict(pending_act)
                pending_act = None
                pending_comm = 0.0
            else:
                adj = mod._us_weighted_return(holdings, ctx.close_df.iloc[i - 1], ctx.close_df.iloc[i])

            hist.append(adj)
            is_sig = i in signal_days
            rebalanced = False

            if is_sig:
                momentum_rows = {lb: momentum_by_lb[lb].iloc[i] for lb in lbs}
                new_act, avg_signal = mix_signal_then_top_weights(
                    momentum_rows,
                    vol_df.iloc[i],
                    ranking_codes,
                    scale,
                    top_n=3,
                    abs_threshold=mod.US_ROT_ABS_THRESHOLD,
                )
                prev_act = {a: act.get(a, 0.0) for a in w_assets} if rows else {"BIL": 1.0}
                turnover = sum(abs(new_act.get(a, 0.0) - prev_act.get(a, 0.0)) for a in set(new_act) | set(prev_act) if a != "BIL")
                if turnover >= mod.US_ROT_MIN_TURNOVER:
                    pending_act = dict(new_act)
                    pending_comm = turnover * mod.US_ROT_COMMISSION if turnover > 0 else 0.0
                    act = new_act
                    rebalanced = True
            else:
                avg_signal = pd.Series(dtype=float)

            row = {"date": ctx.close_df.index[i], "return": adj, "is_signal": is_sig, "rebalanced": rebalanced}
            for asset in w_assets:
                row[f"w_{asset}"] = act.get(asset, 0.0)
            for asset in ranking_codes:
                row[f"sig_{asset}"] = float(avg_signal.get(asset, np.nan)) if not avg_signal.empty else np.nan
            rows.append(row)

        df = pd.DataFrame(rows).set_index("date")
        df["nav"] = (1 + df["return"]).cumprod()
        return apply_volreg(ctx, df)
    finally:
        mod.US_ROT_COMMISSION = old_commission


def calc_metrics(ret: pd.Series):
    ret = ret.dropna()
    if len(ret) < 20:
        return None
    nav = (1 + ret).cumprod()
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    if years <= 0:
        return None
    cagr = nav.iloc[-1] ** (1 / years) - 1
    vol = ret.std() * np.sqrt(252)
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else np.nan
    maxdd = (nav / nav.cummax() - 1).min()
    calmar = cagr / abs(maxdd) if maxdd < 0 else np.nan
    monthly = ret.groupby(ret.index.to_period("M")).apply(lambda x: (1 + x).prod() - 1)
    win_rate = (monthly > 0).mean()
    return {
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "maxdd": maxdd,
        "calmar": calmar,
        "final_nav": nav.iloc[-1],
        "monthly_win_rate": win_rate,
    }


def summarize_segments(name: str, df: pd.DataFrame):
    rows = []
    for seg_key, start, end, label in REGIMES:
        seg = df.loc[start:end]
        metrics = calc_metrics(seg["return"])
        if metrics is None:
            continue
        row = {
            "strategy": name,
            "segment": seg_key,
            "label": label,
            "start": seg.index[0].date().isoformat(),
            "end": seg.index[-1].date().isoformat(),
        }
        row.update(metrics)
        if "rebalanced" in seg.columns:
            row["rebalances"] = int(seg["rebalanced"].sum())
        wc = [c for c in seg.columns if c.startswith("w_")]
        if wc:
            weights = seg[wc].fillna(0).rename(columns=lambda c: c[2:])
            bil = weights["BIL"] if "BIL" in weights.columns else pd.Series(0.0, index=weights.index)
            risky = weights[[c for c in weights.columns if c != "BIL"]].sum(axis=1)
            row["avg_bil"] = bil.mean()
            row["avg_risky"] = risky.mean()
        rows.append(row)
    return rows


def rolling_windows(name: str, df: pd.DataFrame):
    rows = []
    for window_name, window_len in ROLLING_WINDOWS:
        idx = df.index
        for start_i in range(0, len(idx) - window_len + 1, ROLLING_STEP):
            seg = df.iloc[start_i : start_i + window_len]
            metrics = calc_metrics(seg["return"])
            if metrics is None:
                continue
            row = {
                "strategy": name,
                "window": window_name,
                "start": seg.index[0].date().isoformat(),
                "end": seg.index[-1].date().isoformat(),
            }
            row.update(metrics)
            rows.append(row)
    return rows


def dd_details(df: pd.DataFrame):
    nav = (1 + df["return"]).cumprod()
    running_peak = nav.cummax()
    dd = nav / running_peak - 1
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    recovery = nav.loc[trough:]
    recovery_date = recovery[recovery >= nav.loc[peak]].index.min() if (recovery >= nav.loc[peak]).any() else pd.NaT
    return {
        "peak_date": peak.date().isoformat(),
        "trough_date": trough.date().isoformat(),
        "recovery_date": None if pd.isna(recovery_date) else recovery_date.date().isoformat(),
        "maxdd": float(dd.loc[trough]),
        "peak_to_trough_days": int((trough - peak).days),
        "underwater_days": None if pd.isna(recovery_date) else int((recovery_date - peak).days),
    }


def top_drawdown_episodes(df: pd.DataFrame, n=5):
    nav = (1 + df["return"]).cumprod()
    peak = nav.cummax()
    dd = nav / peak - 1
    mins = []
    vals = dd.values
    idx = dd.index
    for i in range(1, len(dd) - 1):
        if vals[i] <= vals[i - 1] and vals[i] <= vals[i + 1] and vals[i] < -0.05:
            trough = idx[i]
            peak_idx = nav.loc[:trough].idxmax()
            mins.append((vals[i], peak_idx, trough))
    mins = sorted(mins, key=lambda x: x[0])
    out = []
    seen = set()
    for val, peak_idx, trough in mins:
        key = (peak_idx, trough)
        if key in seen:
            continue
        seen.add(key)
        out.append({"peak": peak_idx.date().isoformat(), "trough": trough.date().isoformat(), "dd": float(val)})
        if len(out) >= n:
            break
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    mod = load_strategy_module()
    ctx = build_market_context(mod, exclude_btc=True)

    baseline = run_single(ctx, BASELINE_LB)
    mix = run_target_average(ctx, MIX_LBS)
    mix_signal_top3 = run_signal_average_top3(ctx, MIX_LBS)

    segment_rows = (
        summarize_segments("baseline_160", baseline)
        + summarize_segments("mix_130_260_390", mix)
        + summarize_segments("mix_signal_top3_130_260_390", mix_signal_top3)
    )
    rolling_rows = (
        rolling_windows("baseline_160", baseline)
        + rolling_windows("mix_130_260_390", mix)
        + rolling_windows("mix_signal_top3_130_260_390", mix_signal_top3)
    )

    neighborhood_rows = []
    for short_lb in NEIGHBOR_SHORT:
        for mid_lb in NEIGHBOR_MID:
            for long_lb in NEIGHBOR_LONG:
                name = f"{short_lb}+{mid_lb}+{long_lb}"
                result = run_target_average(ctx, [short_lb, mid_lb, long_lb])
                for seg_key, start, end, label in [r for r in REGIMES if r[0] in {"last_5y", "last_10y", "full_common"}]:
                    seg = result.loc[start:end]
                    metrics = calc_metrics(seg["return"])
                    if metrics is None:
                        continue
                    row = {"combo": name, "segment": seg_key, "label": label}
                    row.update(metrics)
                    neighborhood_rows.append(row)

    leave_one_param_rows = []
    leave_one_param_sets = [
        ("drop_130", [260, 390]),
        ("drop_260", [130, 390]),
        ("drop_390", [130, 260]),
    ]
    for name, lbs in leave_one_param_sets:
        result = run_target_average(ctx, lbs)
        for seg_key, start, end, label in [r for r in REGIMES if r[0] in {"last_5y", "last_10y", "full_common"}]:
            seg = result.loc[start:end]
            metrics = calc_metrics(seg["return"])
            if metrics is None:
                continue
            row = {"variant": name, "segment": seg_key, "label": label}
            row.update(metrics)
            leave_one_param_rows.append(row)

    leave_one_asset_rows = []
    for asset in ctx.ranking_codes:
        reduced_codes = [a for a in ctx.ranking_codes if a != asset]
        result = run_target_average(ctx, MIX_LBS, ranking_codes=reduced_codes)
        for seg_key, start, end, label in [r for r in REGIMES if r[0] in {"last_5y", "last_10y", "full_common"}]:
            seg = result.loc[start:end]
            metrics = calc_metrics(seg["return"])
            if metrics is None:
                continue
            row = {"dropped_asset": asset, "segment": seg_key, "label": label}
            row.update(metrics)
            leave_one_asset_rows.append(row)

    cost_rows = []
    for scenario, commission in COMMISSION_SCENARIOS:
        result = run_target_average(ctx, MIX_LBS, commission=commission)
        for seg_key, start, end, label in [r for r in REGIMES if r[0] in {"last_5y", "last_10y", "full_common"}]:
            seg = result.loc[start:end]
            metrics = calc_metrics(seg["return"])
            if metrics is None:
                continue
            row = {"commission_scenario": scenario, "commission": commission, "segment": seg_key, "label": label}
            row.update(metrics)
            cost_rows.append(row)

    dd_rows = pd.DataFrame(
        [
            {
                "strategy": "baseline_160",
                **dd_details(baseline.loc["2016-04-25":"2026-04-23"]),
                "episodes": json.dumps(top_drawdown_episodes(baseline.loc["2016-04-25":"2026-04-23"]), ensure_ascii=False),
            },
            {
                "strategy": "mix_130_260_390",
                **dd_details(mix.loc["2016-04-25":"2026-04-23"]),
                "episodes": json.dumps(top_drawdown_episodes(mix.loc["2016-04-25":"2026-04-23"]), ensure_ascii=False),
            },
            {
                "strategy": "mix_signal_top3_130_260_390",
                **dd_details(mix_signal_top3.loc["2016-04-25":"2026-04-23"]),
                "episodes": json.dumps(top_drawdown_episodes(mix_signal_top3.loc["2016-04-25":"2026-04-23"]), ensure_ascii=False),
            },
        ]
    )

    segment_df = pd.DataFrame(segment_rows)
    rolling_df = pd.DataFrame(rolling_rows)
    neighborhood_df = pd.DataFrame(neighborhood_rows)
    leave_one_param_df = pd.DataFrame(leave_one_param_rows)
    leave_one_asset_df = pd.DataFrame(leave_one_asset_rows)
    cost_df = pd.DataFrame(cost_rows)

    rolling_summary_rows = []
    pivot_roll = rolling_df.pivot_table(index=["window", "start", "end"], columns="strategy", values="sharpe").reset_index()
    for window_name, group in rolling_df.groupby(["strategy", "window"]):
        strategy, window = window_name
        rolling_summary_rows.append(
            {
                "strategy": strategy,
                "window": window,
                "median_sharpe": group["sharpe"].median(),
                "p25_sharpe": group["sharpe"].quantile(0.25),
                "p75_sharpe": group["sharpe"].quantile(0.75),
                "worst_cagr": group["cagr"].min(),
                "best_cagr": group["cagr"].max(),
                "worst_maxdd": group["maxdd"].min(),
                "best_maxdd": group["maxdd"].max(),
                "positive_window_rate": (group["cagr"] > 0).mean(),
            }
        )
    rolling_summary_df = pd.DataFrame(rolling_summary_rows)

    if not pivot_roll.empty:
        rolling_outperf_rows = []
        for strategy_name in ["mix_130_260_390", "mix_signal_top3_130_260_390"]:
            delta_col = f"{strategy_name}_minus_base_sharpe"
            pivot_roll[delta_col] = pivot_roll.get(strategy_name, np.nan) - pivot_roll.get("baseline_160", np.nan)
            outperf = pivot_roll.groupby("window")[delta_col].agg(
                outperf_rate=lambda s: (s > 0).mean(),
                median_delta="median",
                p25_delta=lambda s: s.quantile(0.25),
                p75_delta=lambda s: s.quantile(0.75),
            ).reset_index()
            outperf["strategy"] = strategy_name
            rolling_outperf_rows.append(outperf)
        rolling_outperf = pd.concat(rolling_outperf_rows, ignore_index=True)
    else:
        rolling_outperf = pd.DataFrame()

    robust_rank = (
        neighborhood_df.groupby("segment")["sharpe"]
        .rank(pct=True)
        .rename("rank_pct")
    )
    neighborhood_rank_df = neighborhood_df.join(robust_rank)
    robust_combo = (
        neighborhood_rank_df.groupby("combo")["rank_pct"]
        .mean()
        .sort_values(ascending=False)
        .reset_index(name="avg_sharpe_rank_pct")
    )

    files = {
        "segment": OUT_DIR / "segment_metrics.csv",
        "rolling": OUT_DIR / "rolling_metrics.csv",
        "rolling_summary": OUT_DIR / "rolling_summary.csv",
        "rolling_outperf": OUT_DIR / "rolling_mix_vs_base.csv",
        "neighborhood": OUT_DIR / "neighbor_combo_metrics.csv",
        "neighbor_rank": OUT_DIR / "neighbor_combo_rank.csv",
        "drop_param": OUT_DIR / "leave_one_param.csv",
        "drop_asset": OUT_DIR / "leave_one_asset.csv",
        "cost": OUT_DIR / "commission_sensitivity.csv",
        "dd": OUT_DIR / "drawdown_diagnostics.csv",
        "core_compare": OUT_DIR / "core_compare_with_signal_top3.csv",
    }
    segment_df.to_csv(files["segment"], index=False)
    rolling_df.to_csv(files["rolling"], index=False)
    rolling_summary_df.to_csv(files["rolling_summary"], index=False)
    rolling_outperf.to_csv(files["rolling_outperf"], index=False)
    neighborhood_df.to_csv(files["neighborhood"], index=False)
    robust_combo.to_csv(files["neighbor_rank"], index=False)
    leave_one_param_df.to_csv(files["drop_param"], index=False)
    leave_one_asset_df.to_csv(files["drop_asset"], index=False)
    cost_df.to_csv(files["cost"], index=False)
    dd_rows.to_csv(files["dd"], index=False)
    segment_df[segment_df["segment"].isin(["last_5y", "last_10y", "full_common"])].to_csv(files["core_compare"], index=False)

    report_lines = []
    report_lines.append("# Sub-B Mix 130/260/390 Robustness")
    report_lines.append("")
    report_lines.append(f"- Data source: production `fetch_yahoo()` path from `{SCRIPT.name}`")
    report_lines.append("- Ranking pool: QQQ, EMXC, EFA, GLD, TLT, DBC")
    report_lines.append("- BTC excluded from backtest")
    report_lines.append("- `mix_130_260_390`: each window selects its own Top3, then average target weights")
    report_lines.append("- `mix_signal_top3_130_260_390`: first average 130/260/390 momentum signal, then select one global Top3")
    report_lines.append("- Execution: T close signal -> T+1 open execution")
    report_lines.append(f"- Costs: default `{mod.US_ROT_COMMISSION:.4f}` unless stated otherwise")
    report_lines.append("")

    seg_last10 = segment_df[segment_df["segment"] == "last_10y"].copy()
    seg_last5 = segment_df[segment_df["segment"] == "last_5y"].copy()
    report_lines.append("## Core Comparison")
    report_lines.append("")
    report_lines.append("### Last 10Y")
    report_lines.append(seg_last10[["strategy", "cagr", "sharpe", "maxdd", "calmar", "avg_bil", "avg_risky"]].to_markdown(index=False, floatfmt=".4f"))
    report_lines.append("")
    report_lines.append("### Last 5Y")
    report_lines.append(seg_last5[["strategy", "cagr", "sharpe", "maxdd", "calmar", "avg_bil", "avg_risky"]].to_markdown(index=False, floatfmt=".4f"))
    report_lines.append("")

    report_lines.append("## Rolling Robustness")
    report_lines.append("")
    if not rolling_outperf.empty:
        report_lines.append(rolling_outperf.to_markdown(index=False, floatfmt=".4f"))
        report_lines.append("")
    report_lines.append(rolling_summary_df.to_markdown(index=False, floatfmt=".4f"))
    report_lines.append("")

    report_lines.append("## Neighbor Combo Robustness")
    report_lines.append("")
    report_lines.append(robust_combo.head(15).to_markdown(index=False, floatfmt=".4f"))
    report_lines.append("")

    report_lines.append("## Leave-One Tests")
    report_lines.append("")
    report_lines.append("### Drop One Parameter")
    report_lines.append(leave_one_param_df.to_markdown(index=False, floatfmt=".4f"))
    report_lines.append("")
    report_lines.append("### Drop One Asset")
    report_lines.append(leave_one_asset_df.to_markdown(index=False, floatfmt=".4f"))
    report_lines.append("")

    report_lines.append("## Cost Sensitivity")
    report_lines.append("")
    report_lines.append(cost_df.to_markdown(index=False, floatfmt=".4f"))
    report_lines.append("")

    report_lines.append("## Drawdown Diagnostics")
    report_lines.append("")
    report_lines.append(dd_rows.drop(columns=["episodes"]).to_markdown(index=False))
    report_lines.append("")

    report_path = OUT_DIR / "summary.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print("WROTE", OUT_DIR)
    for label, path in files.items():
        print(label.upper(), path)
    print("REPORT", report_path)


if __name__ == "__main__":
    main()

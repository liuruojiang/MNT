import builtins
import importlib.util
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "mnt_bot V 7.1 plus.py"
OUT_DIR = ROOT / "docs" / "subb_v71_buffer_20260425"

BUFFER_THRESHOLDS = [
    ("legacy_no_buffer_1p00x", 1.00),
    ("candidate_1p02x", 1.02),
    ("candidate_1p10x", 1.10),
]

SEGMENTS = [
    ("last_1y", "2025-04-25", "2026-04-24"),
    ("last_3y", "2023-04-25", "2026-04-24"),
    ("last_5y", "2021-04-23", "2026-04-24"),
    ("last_10y", "2016-04-25", "2026-04-24"),
    ("full_common", None, None),
]


class _PoeStub:
    query = None
    default_chat = []

    class BotError(Exception):
        pass

    def update_settings(self, settings):
        self.settings = settings


@dataclass
class MarketContext:
    mod: object
    close_df: pd.DataFrame
    open_map: dict
    ranking_codes: list[str]


def load_strategy_module():
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = _PoeStub()
    spec = importlib.util.spec_from_file_location("mnt_bot_v71_buffer", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if had_poe:
        builtins.poe = old_poe
    else:
        delattr(builtins, "poe")
    return mod


def build_market_context(mod):
    ranking_codes = list(mod.US_ROT_POOL)
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


def run_current_mix(ctx: MarketContext) -> pd.DataFrame:
    result = ctx.mod.run_us_rotation_mix(
        ctx.close_df,
        ctx.ranking_codes,
        us_open=ctx.open_map,
    )
    return apply_volreg(ctx, result)


def _average_weight_dicts(weight_dicts):
    if not weight_dicts:
        return {"BIL": 1.0}
    keys = set().union(*[wd.keys() for wd in weight_dicts])
    return {k: sum(wd.get(k, 0.0) for wd in weight_dicts) / len(weight_dicts) for k in keys}


def run_mix_with_buffer(ctx: MarketContext, threshold: float) -> pd.DataFrame:
    mod = ctx.mod
    close_df = ctx.close_df
    ranking_codes = ctx.ranking_codes
    top_n = 3
    abs_threshold = mod.US_ROT_ABS_THRESHOLD
    min_turnover = mod.US_ROT_MIN_TURNOVER
    momentum_by_lb = {lb: close_df.div(close_df.shift(lb)).sub(1) for lb in mod.US_ROT_LBS}
    vol_df = close_df.pct_change().rolling(mod.US_ROT_VOL_LB).std() * np.sqrt(mod.US_TRADING_DAYS)
    start_idx = max(mod.US_ROT_MAX_LB, mod.US_ROT_VOL_LB, mod.US_ROT_VOL_WINDOW) + 1
    signal_days = mod._us_signal_days(close_df, start_idx)

    act = {"BIL": 1.0}
    holdings = {"BIL": 1.0}
    pending_act = None
    pending_comm = 0.0
    scale = 1.0
    w_assets = list(ranking_codes) + (["BIL"] if "BIL" not in ranking_codes else [])
    prev_risky_by_lb = {lb: None for lb in mod.US_ROT_LBS}
    rows = []
    hist = []

    for i in range(start_idx, len(close_df)):
        if len(hist) >= mod.US_ROT_VOL_WINDOW:
            rv = np.std(hist[-mod.US_ROT_VOL_WINDOW :], ddof=1) * np.sqrt(mod.US_TRADING_DAYS)
            scale = min(max(mod.US_ROT_TARGET_VOL / rv, 0.05), mod.US_ROT_MAX_LEV) if rv > 0.001 else mod.US_ROT_MAX_LEV

        if pending_act is not None:
            open_row = mod._us_open_row(close_df.index[i], w_assets, ctx.open_map, close_df)
            overnight = mod._us_weighted_return(holdings, close_df.iloc[i - 1], open_row)
            intraday = mod._us_weighted_return(pending_act, open_row, close_df.iloc[i])
            adj = (1 + overnight) * (1 + intraday) * (1 - pending_comm) - 1
            holdings = dict(pending_act)
            pending_act = None
            pending_comm = 0.0
        else:
            adj = mod._us_weighted_return(holdings, close_df.iloc[i - 1], close_df.iloc[i])

        hist.append(adj)
        is_sig = i in signal_days
        rebalanced = False
        new_act = dict(act)
        per_lb_selected = {lb: [] for lb in mod.US_ROT_LBS}

        if is_sig:
            acts = []
            next_prev_risky_by_lb = {}
            for lb in mod.US_ROT_LBS:
                raw = mod._us_raw_weights(
                    momentum_by_lb[lb].iloc[i],
                    vol_df.iloc[i],
                    ranking_codes,
                    top_n,
                    abs_threshold,
                    prev_risky=prev_risky_by_lb.get(lb),
                    threshold=threshold,
                )
                per_lb_selected[lb] = sorted([a for a, w in raw.items() if a != "BIL" and w > 1e-12])
                acts.append(mod._us_model_b(raw, scale))
                next_prev_risky_by_lb[lb] = set(per_lb_selected[lb]) or None
            new_act = _average_weight_dicts(acts)
            prev_a = {a: act.get(a, 0.0) for a in w_assets} if rows else {"BIL": 1.0}
            all_a = set(list(new_act.keys()) + list(prev_a.keys()))
            turnover = sum(abs(new_act.get(a, 0.0) - prev_a.get(a, 0.0)) for a in all_a if a != "BIL")
            if turnover >= min_turnover:
                pending_act = dict(new_act)
                pending_comm = turnover * mod.US_ROT_COMMISSION if turnover > 0 else 0.0
                act = new_act
                prev_risky_by_lb = next_prev_risky_by_lb
                rebalanced = True
        else:
            turnover = 0.0

        row = {
            "date": close_df.index[i],
            "return": adj,
            "is_signal": is_sig,
            "rebalanced": rebalanced,
            "turnover": turnover,
        }
        for a in w_assets:
            row[f"w_{a}"] = act.get(a, 0.0)
        for lb in mod.US_ROT_LBS:
            row[f"sel_{lb}"] = ",".join(per_lb_selected[lb]) if per_lb_selected[lb] else ""
        rows.append(row)

    df = pd.DataFrame(rows).set_index("date")
    df["nav"] = (1 + df["return"]).cumprod()
    return apply_volreg(ctx, df)


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
    return {
        "cagr": float(cagr),
        "vol": float(vol),
        "sharpe": float(sharpe),
        "max_dd": float(maxdd),
        "calmar": float(cagr / abs(maxdd)) if maxdd < 0 else np.nan,
        "final_nav": float(nav.iloc[-1]),
    }


def qqq_churn_stats(df: pd.DataFrame, ticker="QQQ"):
    col = f"w_{ticker}"
    if col not in df.columns:
        return {
            "ticker": ticker,
            "entries": 0,
            "exits": 0,
            "state_changes": 0,
            "changes_within_7d": 0,
            "avg_weight": np.nan,
            "hold_ratio": np.nan,
        }
    on = df[col].fillna(0.0) > 1e-6
    prev = on.shift(1).fillna(False)
    entries = int(((~prev) & on).sum())
    exits = int((prev & (~on)).sum())
    change_dates = df.index[on != prev]
    if len(change_dates) > 0:
        change_dates = change_dates[1:]
    gaps = np.diff(change_dates.values).astype("timedelta64[D]").astype(int) if len(change_dates) >= 2 else np.array([], dtype=int)
    return {
        "ticker": ticker,
        "entries": entries,
        "exits": exits,
        "state_changes": int(entries + exits),
        "changes_within_7d": int((gaps <= 7).sum()) if len(gaps) else 0,
        "avg_weight": float(df[col].fillna(0.0).mean()),
        "hold_ratio": float(on.mean()),
    }


def summarize_strategy(name: str, threshold: float, df: pd.DataFrame):
    rows = []
    churn = qqq_churn_stats(df, ticker="QQQ")
    for seg_name, start, end in SEGMENTS:
        seg = df if start is None else df.loc[start:end]
        metrics = calc_metrics(seg["return"])
        if metrics is None:
            continue
        local_churn = qqq_churn_stats(seg, ticker="QQQ")
        rows.append(
            {
                "strategy": name,
                "buffer_threshold": threshold,
                "segment": seg_name,
                "start": seg.index[0].date().isoformat(),
                "end": seg.index[-1].date().isoformat(),
                "rebalances": int(seg["rebalanced"].sum()) if "rebalanced" in seg else 0,
                "avg_turnover": float(seg["turnover"].mean()) if "turnover" in seg else np.nan,
                "qqq_entries": local_churn["entries"],
                "qqq_exits": local_churn["exits"],
                "qqq_state_changes": local_churn["state_changes"],
                "qqq_changes_within_7d": local_churn["changes_within_7d"],
                "qqq_avg_weight": local_churn["avg_weight"],
                "qqq_hold_ratio": local_churn["hold_ratio"],
                **metrics,
            }
        )
    return rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mod = load_strategy_module()
    ctx = build_market_context(mod)

    strategy_results = {}
    strategy_results["formal_v71_1p05x"] = run_current_mix(ctx)
    for name, threshold in BUFFER_THRESHOLDS:
        strategy_results[name] = run_mix_with_buffer(ctx, threshold)

    parity_custom_1p05 = run_mix_with_buffer(ctx, mod.US_ROT_REBALANCE_THRESHOLD)
    joined = strategy_results["formal_v71_1p05x"][["nav"]].join(
        parity_custom_1p05[["nav"]].rename(columns={"nav": "custom_nav"}),
        how="inner",
    )
    parity_info = {
        "formal_threshold": float(mod.US_ROT_REBALANCE_THRESHOLD),
        "parity_rows": int(len(joined)),
        "parity_max_abs_nav_diff": float((joined["nav"] - joined["custom_nav"]).abs().max()) if len(joined) else np.nan,
    }

    summary_rows = []
    summary_rows.extend(summarize_strategy("formal_v71_1p05x", mod.US_ROT_REBALANCE_THRESHOLD, strategy_results["formal_v71_1p05x"]))
    for name, threshold in BUFFER_THRESHOLDS:
        summary_rows.extend(summarize_strategy(name, threshold, strategy_results[name]))

    summary_df = pd.DataFrame(summary_rows)
    core_df = summary_df[summary_df["segment"].isin(["last_1y", "last_3y", "last_5y", "last_10y", "full_common"])].copy()

    robustness_rows = []
    for seg_name, seg_df in core_df.groupby("segment"):
        if seg_df.empty:
            continue
        for metric in ["cagr", "sharpe", "calmar"]:
            best = seg_df.sort_values(metric, ascending=False).iloc[0]
            robustness_rows.append(
                {
                    "segment": seg_name,
                    "metric": metric,
                    "winner": best["strategy"],
                    "winner_value": float(best[metric]),
                }
            )
        best_dd = seg_df.sort_values("max_dd", ascending=False).iloc[0]
        robustness_rows.append(
            {
                "segment": seg_name,
                "metric": "max_dd",
                "winner": best_dd["strategy"],
                "winner_value": float(best_dd["max_dd"]),
            }
        )
    robustness_df = pd.DataFrame(robustness_rows)

    summary_df.to_csv(OUT_DIR / "summary.csv", index=False)
    core_df.to_csv(OUT_DIR / "core_compare.csv", index=False)
    robustness_df.to_csv(OUT_DIR / "robustness_summary.csv", index=False)
    pd.DataFrame([parity_info]).to_csv(OUT_DIR / "formal_vs_custom_parity.csv", index=False)

    recent_df = core_df[core_df["segment"].isin(["last_1y", "last_3y", "last_5y"])].copy()
    recent_df.to_csv(OUT_DIR / "recent_1y_3y_5y_compare.csv", index=False)

    lines = [
        "# Sub-B V7.1 Buffer Study",
        "",
        "- Data source: production `fetch_yahoo()` path from `mnt_bot V 7.1 plus.py`",
        f"- Strategy: current `run_us_rotation_mix()` logic with `130/260/390` windows; current formal production threshold = `{mod.US_ROT_REBALANCE_THRESHOLD:.2f}x`",
        "- Pool: `QQQ, EMXC, EFA, GLD, TLT, DBC, BTC-USD`",
        "- Execution: T close signal -> T+1 open execution",
        "- Costs: `US_ROT_COMMISSION = 0.001`",
        "- Buffer rule: each window remembers its prior Top3; challenger must beat the weakest incumbent by `threshold` before replacing it",
        f"- Production parity check: custom `{mod.US_ROT_REBALANCE_THRESHOLD:.2f}x` harness vs `run_us_rotation_mix()` max abs NAV diff = `{parity_info['parity_max_abs_nav_diff']:.6g}`",
        "",
    ]
    for seg in ["last_1y", "last_3y", "last_5y", "last_10y", "full_common"]:
        lines.append(f"## {seg}")
        sub = core_df[core_df["segment"] == seg].copy().sort_values("sharpe", ascending=False)
        for _, row in sub.iterrows():
            lines.append(
                f"- {row['strategy']}: CAGR {row['cagr']:.2%}, Sharpe {row['sharpe']:.3f}, "
                f"MaxDD {row['max_dd']:.2%}, Rebalances {int(row['rebalances'])}, "
                f"QQQ changes<=7d {int(row['qqq_changes_within_7d'])}"
            )
        winners = robustness_df[robustness_df["segment"] == seg]
        if not winners.empty:
            winner_text = "; ".join(
                f"{row['metric']} -> {row['winner']}"
                for _, row in winners.iterrows()
            )
            lines.append(f"- Winners: {winner_text}")
        lines.append("")
    (OUT_DIR / "summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()

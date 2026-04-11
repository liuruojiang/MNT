from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import analyze_microcap_zz1000_hedge as hedge_mod
import scan_top100_momentum_costs as cost_mod


ROOT = Path(__file__).resolve().parent
MICROCAP_CSV = ROOT / "wind_microcap_top_100_biweekly_16y_cached.csv"
TURNOVER_CSV = ROOT / "microcap_top100_biweekly_turnover_stats.csv"
OUTPUT_PREFIX = "microcap_top100_mom16_biweekly_hedge_ratio"

LOOKBACK = 16
ENTRY_GAP = 0.005
EXIT_GAP = 0.0
FIXED_RATIO_GRID = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
BETA_WINDOWS = [20, 40, 60, 90, 120]
BETA_MIN_OBS_RATIO = 0.5
BETA_CLIP_MIN = 0.7
BETA_CLIP_MAX = 1.3


def build_close_df() -> pd.DataFrame:
    microcap = pd.read_csv(MICROCAP_CSV, usecols=["date", "close"])
    microcap["date"] = pd.to_datetime(microcap["date"])
    microcap = microcap.set_index("date")["close"].rename("microcap").astype(float)

    panel = pd.read_csv(hedge_mod.DEFAULT_PANEL, usecols=["date", hedge_mod.DEFAULT_HEDGE_COLUMN])
    panel["date"] = pd.to_datetime(panel["date"])
    hedge = panel.set_index("date")[hedge_mod.DEFAULT_HEDGE_COLUMN].rename("hedge").astype(float)

    return pd.concat([microcap, hedge], axis=1).sort_index().dropna()


def build_signal_frame(close_df: pd.DataFrame) -> pd.DataFrame:
    work = close_df.copy()
    work["microcap_ret"] = work["microcap"].pct_change(fill_method=None)
    work["hedge_ret"] = work["hedge"].pct_change(fill_method=None)
    work["microcap_mom"] = hedge_mod.calc_momentum(work["microcap"], LOOKBACK)
    work["hedge_mom"] = hedge_mod.calc_momentum(work["hedge"], LOOKBACK)
    work["momentum_gap"] = work["microcap_mom"] - work["hedge_mom"]

    valid_mask = work[["microcap_mom", "hedge_mom"]].notna().all(axis=1)
    valid_start = valid_mask[valid_mask].index.min()
    if pd.isna(valid_start):
        raise ValueError("No valid momentum history.")
    return work.loc[valid_start:].copy()


def rolling_beta(asset_ret: pd.Series, hedge_ret: pd.Series, window: int) -> pd.Series:
    out = np.full(len(asset_ret), np.nan)
    a = asset_ret.values.astype(float)
    h = hedge_ret.values.astype(float)
    min_obs = max(10, int(window * BETA_MIN_OBS_RATIO))
    for i in range(len(asset_ret)):
        start = max(0, i - window)
        pair = pd.DataFrame({"a": a[start:i], "h": h[start:i]}).dropna()
        if len(pair) < min_obs:
            continue
        h_var = pair["h"].var(ddof=1)
        if not np.isfinite(h_var) or h_var < 1e-12:
            continue
        beta = pair["a"].cov(pair["h"]) / h_var
        out[i] = float(np.clip(beta, BETA_CLIP_MIN, BETA_CLIP_MAX))
    return pd.Series(out, index=asset_ret.index)


def run_with_hedge_ratio(
    work: pd.DataFrame,
    hedge_ratio_series: pd.Series,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    holding = False
    for i in range(1, len(work)):
        date = work.index[i]
        gap = work["momentum_gap"].iloc[i]
        if holding:
            signal_on = bool(pd.notna(gap) and gap >= EXIT_GAP)
        else:
            signal_on = bool(pd.notna(gap) and gap > ENTRY_GAP)

        hedge_ratio = float(hedge_ratio_series.iloc[i]) if pd.notna(hedge_ratio_series.iloc[i]) else 1.0
        if not holding:
            hedge_ratio = 0.0

        active_ret = 0.0
        drag = hedge_mod.DEFAULT_FUTURES_DRAG * hedge_ratio if holding else 0.0
        if holding:
            microcap_ret = work["microcap_ret"].iloc[i]
            hedge_ret = work["hedge_ret"].iloc[i]
            if pd.notna(microcap_ret) and pd.notna(hedge_ret):
                active_ret = float(microcap_ret - hedge_ratio * hedge_ret)

        day_ret = active_ret - drag
        rows.append(
            {
                "date": date,
                "return_raw": day_ret,
                "holding": "long_microcap_short_zz1000" if holding else "cash",
                "next_holding": "long_microcap_short_zz1000" if signal_on else "cash",
                "signal_on": signal_on,
                "microcap_close": float(work["microcap"].iloc[i]),
                "hedge_close": float(work["hedge"].iloc[i]),
                "microcap_ret": float(work["microcap_ret"].iloc[i]) if pd.notna(work["microcap_ret"].iloc[i]) else np.nan,
                "hedge_ret": float(work["hedge_ret"].iloc[i]) if pd.notna(work["hedge_ret"].iloc[i]) else np.nan,
                "microcap_mom": float(work["microcap_mom"].iloc[i]),
                "hedge_mom": float(work["hedge_mom"].iloc[i]),
                "momentum_gap": float(gap),
                "hedge_ratio": hedge_ratio,
                "futures_drag": drag,
                "active_spread_ret": active_ret,
            }
        )
        holding = signal_on

    result = pd.DataFrame(rows).set_index("date")
    result["weight"] = 1.0
    result["realized_vol"] = np.nan
    result["scale_raw"] = np.nan
    result["return"] = result["return_raw"]
    result["nav"] = (1.0 + result["return"]).cumprod()
    return result


def calc_drawdown_dates(ret: pd.Series) -> dict[str, str | None]:
    nav = (1.0 + ret).cumprod()
    dd = nav.div(nav.cummax()).sub(1.0)
    trough_date = dd.idxmin()
    peak_date = nav.loc[:trough_date].idxmax()
    recovery = nav.loc[trough_date:]
    recovery = recovery[recovery >= nav.loc[peak_date]]
    recovery_date = recovery.index[0] if len(recovery) else pd.NaT
    return {
        "peak_date": str(peak_date.date()),
        "trough_date": str(trough_date.date()),
        "recovery_date": None if pd.isna(recovery_date) else str(recovery_date.date()),
    }


def summarize_variant(
    variant: str,
    param: str,
    gross: pd.DataFrame,
    net: pd.DataFrame,
) -> dict[str, object]:
    metrics = hedge_mod.calc_metrics(net["return_net"])
    active = net["holding"].ne("cash")
    active_prev = active.shift(1, fill_value=False)
    hedge_live = net.loc[active, "hedge_ratio"].replace(0.0, np.nan).dropna()
    dd = calc_drawdown_dates(net["return_net"])
    return {
        "variant": variant,
        "param": param,
        "annual": metrics.annual,
        "max_dd": metrics.max_dd,
        "sharpe": metrics.sharpe,
        "vol": metrics.vol,
        "total_return": metrics.total_return,
        "entry_days": int((active & ~active_prev).sum()),
        "exit_days": int((~active & active_prev).sum()),
        "signal_changes": int(gross["signal_on"].ne(gross["signal_on"].shift()).sum() - 1),
        "entry_exit_cost_sum": float(net["entry_exit_cost"].sum()),
        "rebalance_cost_sum": float(net["rebalance_cost"].sum()),
        "total_cost_sum": float(net["total_cost"].sum()),
        "active_days_pct": float(active.mean()),
        "hedge_ratio_mean_live": float(hedge_live.mean()) if len(hedge_live) else np.nan,
        "hedge_ratio_median_live": float(hedge_live.median()) if len(hedge_live) else np.nan,
        "peak_date": dd["peak_date"],
        "trough_date": dd["trough_date"],
        "recovery_date": dd["recovery_date"],
    }


def plot_recent5y_compare(
    baseline: pd.DataFrame,
    best_fixed: pd.DataFrame,
    best_dynamic: pd.DataFrame,
    best_fixed_label: str,
    best_dynamic_label: str,
    output_path: Path,
) -> None:
    last_date = baseline.index[-1]
    start = last_date - pd.DateOffset(years=5)
    frames = [
        ("Baseline 1.0x", baseline.loc[baseline.index >= start, "nav_net"]),
        (best_fixed_label, best_fixed.loc[best_fixed.index >= start, "nav_net"]),
        (best_dynamic_label, best_dynamic.loc[best_dynamic.index >= start, "nav_net"]),
    ]

    plt.figure(figsize=(12, 6))
    colors = ["#2f3e46", "#0b6e4f", "#bc4749"]
    for (label, series), color in zip(frames, colors):
        s = series / series.iloc[0]
        plt.plot(s.index, s.values, linewidth=1.9, label=label, color=color)
    plt.title("Top 100 + 16d Momentum + Biweekly Rebalance\nDynamic Hedge Ratio Compare (Recent 5 Years, Net)")
    plt.grid(alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def main() -> None:
    close_df = build_close_df()
    work = build_signal_frame(close_df)
    turnover = cost_mod.load_turnover_table(TURNOVER_CSV)

    rows: list[dict[str, object]] = []
    baseline_net: pd.DataFrame | None = None
    best_fixed_net: pd.DataFrame | None = None
    best_dynamic_net: pd.DataFrame | None = None

    # Fixed hedge ratio scan
    for ratio in FIXED_RATIO_GRID:
        hedge_ratio_series = pd.Series(ratio, index=work.index, dtype=float)
        gross = run_with_hedge_ratio(work, hedge_ratio_series)
        net = cost_mod.apply_cost_model(gross, turnover)
        rows.append(summarize_variant("fixed", f"{ratio:.2f}", gross, net))
        if ratio == 1.0:
            baseline_net = net.copy()

    # Rolling beta scan
    for window in BETA_WINDOWS:
        beta_series = rolling_beta(work["microcap_ret"], work["hedge_ret"], window=window).fillna(1.0)
        gross = run_with_hedge_ratio(work, beta_series)
        net = cost_mod.apply_cost_model(gross, turnover)
        rows.append(summarize_variant("rolling_beta", f"window_{window}", gross, net))

    scan_df = pd.DataFrame(rows).sort_values(["sharpe", "annual"], ascending=[False, False]).reset_index(drop=True)
    scan_df["rank"] = np.arange(1, len(scan_df) + 1)
    scan_df = scan_df[
        [
            "rank",
            "variant",
            "param",
            "annual",
            "max_dd",
            "sharpe",
            "entry_exit_cost_sum",
            "rebalance_cost_sum",
            "total_cost_sum",
            "hedge_ratio_mean_live",
            "hedge_ratio_median_live",
            "entry_days",
            "signal_changes",
            "active_days_pct",
            "peak_date",
            "trough_date",
            "recovery_date",
        ]
    ]

    best_fixed = scan_df[scan_df["variant"] == "fixed"].sort_values(["sharpe", "annual"], ascending=[False, False]).iloc[0]
    best_dynamic = scan_df[scan_df["variant"] == "rolling_beta"].sort_values(["sharpe", "annual"], ascending=[False, False]).iloc[0]

    best_fixed_ratio = float(best_fixed["param"])
    best_fixed_net = cost_mod.apply_cost_model(
        run_with_hedge_ratio(work, pd.Series(best_fixed_ratio, index=work.index, dtype=float)),
        turnover,
    )
    best_dynamic_window = int(str(best_dynamic["param"]).split("_")[-1])
    best_dynamic_series = rolling_beta(work["microcap_ret"], work["hedge_ret"], best_dynamic_window).fillna(1.0)
    best_dynamic_net = cost_mod.apply_cost_model(run_with_hedge_ratio(work, best_dynamic_series), turnover)

    grid_path = ROOT / f"{OUTPUT_PREFIX}_scan.csv"
    summary_path = ROOT / f"{OUTPUT_PREFIX}_summary.json"
    plot_path = ROOT / f"{OUTPUT_PREFIX}_recent5y_compare.png"
    scan_df.to_csv(grid_path, index=False, encoding="utf-8")

    recent_rows: list[dict[str, object]] = []
    compare_map = {
        "baseline_fixed_1.0": baseline_net,
        f"best_fixed_{best_fixed_ratio:.2f}": best_fixed_net,
        f"best_dynamic_window_{best_dynamic_window}": best_dynamic_net,
    }
    for label, nav_df in compare_map.items():
        if nav_df is None:
            continue
        last_date = nav_df.index[-1]
        for yrs in [1, 2, 3, 4, 5]:
            part = nav_df.loc[nav_df.index >= last_date - pd.DateOffset(years=yrs), "return_net"]
            if len(part) > 30:
                m = hedge_mod.calc_metrics(part)
                recent_rows.append(
                    {
                        "variant": label,
                        "window_years": yrs,
                        "annual": m.annual,
                        "max_dd": m.max_dd,
                        "sharpe": m.sharpe,
                    }
                )

    summary = {
        "strategy": "top100_mom16_biweekly_dynamic_hedge_ratio",
        "signal_rule": {
            "entry_gap": ENTRY_GAP,
            "exit_gap": EXIT_GAP,
        },
        "beta_clip": [BETA_CLIP_MIN, BETA_CLIP_MAX],
        "fixed_ratio_grid": FIXED_RATIO_GRID,
        "beta_windows": BETA_WINDOWS,
        "best_fixed": best_fixed.to_dict(),
        "best_dynamic": best_dynamic.to_dict(),
        "top10": scan_df.head(10).to_dict(orient="records"),
        "recent_windows": recent_rows,
        "notes": {
            "futures_drag": "Scaled by hedge ratio each active day.",
            "futures_rehedge_fee": "Not added. This scan only keeps the existing futures drag, same as prior tests.",
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if baseline_net is not None and best_fixed_net is not None and best_dynamic_net is not None:
        plot_recent5y_compare(
            baseline_net,
            best_fixed_net,
            best_dynamic_net,
            best_fixed_label=f"Best fixed {best_fixed_ratio:.2f}x",
            best_dynamic_label=f"Best rolling beta w{best_dynamic_window}",
            output_path=plot_path,
        )

    print(scan_df.to_string(index=False))
    print(f"saved {grid_path.name}")
    print(f"saved {summary_path.name}")
    print(f"saved {plot_path.name}")


if __name__ == "__main__":
    main()

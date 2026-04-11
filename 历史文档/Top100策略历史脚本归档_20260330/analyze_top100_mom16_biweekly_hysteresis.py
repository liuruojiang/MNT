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
OUTPUT_PREFIX = "microcap_top100_mom16_biweekly_hysteresis"
LOOKBACK = 16
ENTRY_GRID = [0.0, 0.005, 0.01, 0.015, 0.02, 0.03]
EXIT_GRID = [0.0, -0.005, -0.01, -0.015, -0.02]


def build_close_df() -> pd.DataFrame:
    microcap = pd.read_csv(MICROCAP_CSV, usecols=["date", "close"])
    microcap["date"] = pd.to_datetime(microcap["date"])
    microcap = microcap.set_index("date")["close"].rename("microcap").astype(float)

    panel = pd.read_csv(hedge_mod.DEFAULT_PANEL, usecols=["date", hedge_mod.DEFAULT_HEDGE_COLUMN])
    panel["date"] = pd.to_datetime(panel["date"])
    hedge = panel.set_index("date")[hedge_mod.DEFAULT_HEDGE_COLUMN].rename("hedge").astype(float)

    close_df = pd.concat([microcap, hedge], axis=1).sort_index().dropna()
    return close_df


def run_hysteresis_backtest(
    close_df: pd.DataFrame,
    entry_gap: float,
    exit_gap: float,
) -> pd.DataFrame:
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
    work = work.loc[valid_start:].copy()

    rows: list[dict[str, object]] = []
    holding = False
    for i in range(1, len(work)):
        date = work.index[i]
        active_ret = 0.0
        drag = hedge_mod.DEFAULT_FUTURES_DRAG if holding else 0.0
        if holding:
            microcap_ret = work["microcap_ret"].iloc[i]
            hedge_ret = work["hedge_ret"].iloc[i]
            if pd.notna(microcap_ret) and pd.notna(hedge_ret):
                active_ret = float(microcap_ret - hedge_ret)

        gap = work["momentum_gap"].iloc[i]
        if holding:
            signal_on = bool(pd.notna(gap) and gap >= exit_gap)
        else:
            signal_on = bool(pd.notna(gap) and gap > entry_gap)

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
                "futures_drag": drag,
                "active_spread_ret": active_ret,
                "entry_gap": entry_gap,
                "exit_gap": exit_gap,
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


def calc_spell_stats(net: pd.DataFrame) -> dict[str, float]:
    active = net["holding"].ne("cash")
    spell = active.ne(active.shift()).cumsum()
    spells = net.loc[active].groupby(spell).size()
    return {
        "median_holding_days": float(spells.median()) if len(spells) else 0.0,
        "mean_holding_days": float(spells.mean()) if len(spells) else 0.0,
    }


def drawdown_dates(ret: pd.Series) -> dict[str, str | None]:
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


def summarize_row(entry_gap: float, exit_gap: float, gross: pd.DataFrame, net: pd.DataFrame) -> dict[str, object]:
    metrics = hedge_mod.calc_metrics(net["return_net"])
    active = net["holding"].ne("cash")
    active_prev = active.shift(1, fill_value=False)
    spells = calc_spell_stats(net)
    dd = drawdown_dates(net["return_net"])
    return {
        "entry_gap": entry_gap,
        "exit_gap": exit_gap,
        "annual": metrics.annual,
        "max_dd": metrics.max_dd,
        "sharpe": metrics.sharpe,
        "vol": metrics.vol,
        "total_return": metrics.total_return,
        "active_days_pct": float(active.mean()),
        "entry_days": int((active & ~active_prev).sum()),
        "exit_days": int((~active & active_prev).sum()),
        "signal_cost_days": int(net["entry_exit_cost"].gt(0).sum()),
        "rebalance_cost_days": int(net["rebalance_cost"].gt(0).sum()),
        "entry_exit_cost_sum": float(net["entry_exit_cost"].sum()),
        "rebalance_cost_sum": float(net["rebalance_cost"].sum()),
        "total_cost_sum": float(net["total_cost"].sum()),
        "signal_changes": int(gross["signal_on"].ne(gross["signal_on"].shift()).sum() - 1),
        "median_holding_days": spells["median_holding_days"],
        "mean_holding_days": spells["mean_holding_days"],
        "peak_date": dd["peak_date"],
        "trough_date": dd["trough_date"],
        "recovery_date": dd["recovery_date"],
    }


def plot_compare_recent5y(
    baseline: pd.DataFrame,
    best: pd.DataFrame,
    best_label: str,
    output_path: Path,
) -> None:
    last_date = baseline.index[-1]
    start = last_date - pd.DateOffset(years=5)
    base = baseline.loc[baseline.index >= start, "nav_net"]
    cand = best.loc[best.index >= start, "nav_net"]
    base = base / base.iloc[0]
    cand = cand / cand.iloc[0]

    plt.figure(figsize=(12, 6))
    plt.plot(base.index, base.values, linewidth=1.9, label="Baseline (gap > 0 / exit < 0)")
    plt.plot(cand.index, cand.values, linewidth=1.9, label=best_label)
    plt.title("Top 100 + 16d Momentum + CSI1000 Hedge + Biweekly Rebalance\nRecent 5 Years (Net of Trading Costs)")
    plt.grid(alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def main() -> None:
    close_df = build_close_df()
    turnover = cost_mod.load_turnover_table(TURNOVER_CSV)

    rows: list[dict[str, object]] = []
    best_net: pd.DataFrame | None = None
    baseline_net: pd.DataFrame | None = None
    best_label = ""

    for entry_gap in ENTRY_GRID:
        for exit_gap in EXIT_GRID:
            if exit_gap > entry_gap:
                continue
            gross = run_hysteresis_backtest(close_df, entry_gap=entry_gap, exit_gap=exit_gap)
            net = cost_mod.apply_cost_model(gross, turnover)
            row = summarize_row(entry_gap, exit_gap, gross, net)
            rows.append(row)
            if entry_gap == 0.0 and exit_gap == 0.0:
                baseline_net = net.copy()

    scan_df = pd.DataFrame(rows).sort_values(["sharpe", "annual"], ascending=[False, False]).reset_index(drop=True)
    scan_df["rank"] = np.arange(1, len(scan_df) + 1)
    scan_df = scan_df[
        [
            "rank",
            "entry_gap",
            "exit_gap",
            "annual",
            "max_dd",
            "sharpe",
            "entry_days",
            "exit_days",
            "signal_cost_days",
            "entry_exit_cost_sum",
            "rebalance_cost_sum",
            "total_cost_sum",
            "signal_changes",
            "median_holding_days",
            "mean_holding_days",
            "active_days_pct",
            "peak_date",
            "trough_date",
            "recovery_date",
        ]
    ]

    best_row = scan_df.iloc[0].to_dict()
    best_entry = float(best_row["entry_gap"])
    best_exit = float(best_row["exit_gap"])
    best_gross = run_hysteresis_backtest(close_df, entry_gap=best_entry, exit_gap=best_exit)
    best_net = cost_mod.apply_cost_model(best_gross, turnover)
    best_label = f"Best (enter > {best_entry:.3f}, hold until < {best_exit:.3f})"

    grid_path = ROOT / f"{OUTPUT_PREFIX}_scan.csv"
    summary_path = ROOT / f"{OUTPUT_PREFIX}_summary.json"
    plot_path = ROOT / f"{OUTPUT_PREFIX}_recent5y_compare.png"
    scan_df.to_csv(grid_path, index=False, encoding="utf-8")

    recent_rows: list[dict[str, object]] = []
    for label, nav_df in [("baseline", baseline_net), ("best", best_net)]:
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
        "strategy": "top100_mom16_biweekly_hysteresis_scan",
        "baseline_rule": "enter when momentum_gap > 0; exit when momentum_gap < 0",
        "entry_grid": ENTRY_GRID,
        "exit_grid": EXIT_GRID,
        "best_rule": best_row,
        "top10": scan_df.head(10).to_dict(orient="records"),
        "recent_windows": recent_rows,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if baseline_net is not None and best_net is not None:
        plot_compare_recent5y(baseline_net, best_net, best_label, plot_path)

    print(scan_df.head(15).to_string(index=False))
    print(f"saved {grid_path.name}")
    print(f"saved {summary_path.name}")
    print(f"saved {plot_path.name}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import analyze_microcap_zz1000_hedge as hedge_mod
import scan_top100_momentum_costs as cost_mod


ROOT = Path(__file__).resolve().parent
TOP_N_LIST = [20, 30, 100]
HEDGE_RATIOS = [1.0, 0.9]
LOOKBACK = 16
ENTRY_GAP = 0.005
EXIT_GAP = 0.0
WINDOWS = [1, 2, 3, 4, 5]
OUTPUT_PREFIX = "microcap_top20_30_100_practical_compare"


def load_close_df(top_n: int) -> pd.DataFrame:
    microcap_path = ROOT / f"wind_microcap_top_{top_n}_biweekly_16y_cached.csv"
    microcap = pd.read_csv(microcap_path, usecols=["date", "close"])
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


def run_strategy(work: pd.DataFrame, hedge_ratio: float) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    holding = False
    for i in range(1, len(work)):
        date = work.index[i]
        gap = work["momentum_gap"].iloc[i]
        if holding:
            signal_on = bool(pd.notna(gap) and gap >= EXIT_GAP)
        else:
            signal_on = bool(pd.notna(gap) and gap > ENTRY_GAP)

        active_ret = 0.0
        drag = hedge_mod.DEFAULT_FUTURES_DRAG * hedge_ratio if holding else 0.0
        if holding:
            microcap_ret = work["microcap_ret"].iloc[i]
            hedge_ret = work["hedge_ret"].iloc[i]
            if pd.notna(microcap_ret) and pd.notna(hedge_ret):
                active_ret = float(microcap_ret - hedge_ratio * hedge_ret)

        rows.append(
            {
                "date": date,
                "return_raw": active_ret - drag,
                "holding": "long_microcap_short_zz1000" if holding else "cash",
                "next_holding": "long_microcap_short_zz1000" if signal_on else "cash",
                "signal_on": signal_on,
                "microcap_ret": float(work["microcap_ret"].iloc[i]) if pd.notna(work["microcap_ret"].iloc[i]) else np.nan,
                "hedge_ret": float(work["hedge_ret"].iloc[i]) if pd.notna(work["hedge_ret"].iloc[i]) else np.nan,
                "microcap_mom": float(work["microcap_mom"].iloc[i]),
                "hedge_mom": float(work["hedge_mom"].iloc[i]),
                "momentum_gap": float(gap),
                "hedge_ratio": hedge_ratio if holding else 0.0,
                "futures_drag": drag,
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


def summarize_variant(top_n: int, hedge_ratio: float, net: pd.DataFrame, turnover_df: pd.DataFrame) -> tuple[dict[str, object], list[dict[str, object]]]:
    metrics = hedge_mod.calc_metrics(net["return_net"])
    active = net["holding"].ne("cash")
    active_prev = active.shift(1, fill_value=False)
    summary = {
        "top_n": top_n,
        "hedge_ratio": hedge_ratio,
        "annual": float(metrics.annual),
        "max_dd": float(metrics.max_dd),
        "sharpe": float(metrics.sharpe),
        "vol": float(metrics.vol),
        "total_return": float(metrics.total_return),
        "entry_days": int((active & ~active_prev).sum()),
        "exit_days": int((~active & active_prev).sum()),
        "entry_exit_cost_sum": float(net["entry_exit_cost"].sum()),
        "rebalance_cost_sum": float(net["rebalance_cost"].sum()),
        "total_cost_sum": float(net["total_cost"].sum()),
        "active_days_pct": float(active.mean()),
        "avg_turnover_frac_one_side": float(turnover_df["turnover_frac_one_side"].mean()) if len(turnover_df) else 0.0,
    }

    recent_rows: list[dict[str, object]] = []
    last_date = net.index[-1]
    for years in WINDOWS:
        part = net.loc[net.index >= last_date - pd.DateOffset(years=years), "return_net"]
        if len(part) < 30:
            continue
        m = hedge_mod.calc_metrics(part)
        recent_rows.append(
            {
                "top_n": top_n,
                "hedge_ratio": hedge_ratio,
                "window_years": years,
                "annual": float(m.annual),
                "max_dd": float(m.max_dd),
                "sharpe": float(m.sharpe),
            }
        )
    return summary, recent_rows


def main() -> None:
    summary_rows: list[dict[str, object]] = []
    recent_rows: list[dict[str, object]] = []

    for top_n in TOP_N_LIST:
        close_df = load_close_df(top_n)
        work = build_signal_frame(close_df)
        turnover_path = ROOT / f"microcap_top{top_n}_biweekly_turnover_stats.csv"
        turnover_df = cost_mod.load_turnover_table(turnover_path)

        for hedge_ratio in HEDGE_RATIOS:
            gross = run_strategy(work, hedge_ratio=hedge_ratio)
            net = cost_mod.apply_cost_model(gross, turnover_df)
            net.to_csv(
                ROOT / f"microcap_top{top_n}_mom16_gap005_hedge_{hedge_ratio:.1f}x_biweekly_16y_costed_nav.csv",
                index_label="date",
                encoding="utf-8",
            )
            summary, recent = summarize_variant(top_n=top_n, hedge_ratio=hedge_ratio, net=net, turnover_df=turnover_df)
            summary_rows.append(summary)
            recent_rows.extend(recent)

    summary_df = pd.DataFrame(summary_rows).sort_values(["sharpe", "annual"], ascending=[False, False]).reset_index(drop=True)
    recent_df = pd.DataFrame(recent_rows).sort_values(["window_years", "sharpe", "annual"], ascending=[True, False, False]).reset_index(drop=True)

    summary_df.to_csv(ROOT / f"{OUTPUT_PREFIX}.csv", index=False, encoding="utf-8")
    recent_df.to_csv(ROOT / f"{OUTPUT_PREFIX}_recent_windows.csv", index=False, encoding="utf-8")

    payload = {
        "strategy": "top20_30_100_practical_compare",
        "config": {
            "rebalance": "biweekly",
            "lookback": LOOKBACK,
            "entry_gap": ENTRY_GAP,
            "exit_gap": EXIT_GAP,
            "hedge_ratios": HEDGE_RATIOS,
            "top_n_list": TOP_N_LIST,
            "stock_cost_one_side": cost_mod.ENTRY_COST,
        },
        "summary": summary_df.to_dict(orient="records"),
        "recent_windows": recent_df.to_dict(orient="records"),
    }
    (ROOT / f"{OUTPUT_PREFIX}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(summary_df.to_string(index=False))
    print(f"saved {OUTPUT_PREFIX}.csv")
    print(f"saved {OUTPUT_PREFIX}_recent_windows.csv")


if __name__ == "__main__":
    main()

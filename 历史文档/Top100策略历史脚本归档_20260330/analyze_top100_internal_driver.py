from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import analyze_microcap_zz1000_hedge as hedge_mod
import analyze_top100_rebalance_frequency as freq_mod
import scan_top100_momentum_costs as cost_mod


ROOT = Path(__file__).resolve().parent
COUNTS = [10, 20, 30, 50, 100]
LOOKBACK = 16
REBALANCE_LABEL = "biweekly"
WINDOWS = [1, 2, 3, 4, 5]


def build_index_and_turnover(
    trading_dates: pd.DatetimeIndex,
    returns_df: pd.DataFrame,
    caps_by_date: dict[pd.Timestamp, dict[str, float]],
    rebalance_dates: pd.DatetimeIndex,
    top_n: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rebalance_set = set(rebalance_dates)
    next_members_map: dict[pd.Timestamp, list[str]] = {}
    turnover_rows: list[dict[str, object]] = []
    prev_members: list[str] | None = None

    for dt in rebalance_dates:
        cap_map = caps_by_date.get(pd.Timestamp(dt), {})
        ranked = sorted(cap_map.items(), key=lambda x: x[1])
        selected = [symbol for symbol, _ in ranked[:top_n]]
        next_members_map[pd.Timestamp(dt)] = selected
        if prev_members is not None:
            prev_set = set(prev_members)
            curr_set = set(selected)
            entry_count = len(curr_set - prev_set)
            exit_count = len(prev_set - curr_set)
            turnover_frac = entry_count / top_n if top_n > 0 else 0.0
            turnover_rows.append(
                {
                    "rebalance_date": pd.Timestamp(dt),
                    "entry_count": entry_count,
                    "exit_count": exit_count,
                    "turnover_frac_one_side": turnover_frac,
                    "two_side_cost_rate": 2 * cost_mod.MONTHLY_REBALANCE_ONE_SIDE * turnover_frac,
                }
            )
        prev_members = selected

    current_members: list[str] = []
    current_level = 1000.0
    index_rows: list[dict[str, object]] = []
    for i, dt in enumerate(trading_dates):
        if i == 0:
            index_rows.append(
                {
                    "date": dt,
                    "close": current_level,
                    "daily_return": None,
                    "holding_count": 0,
                }
            )
            if dt in rebalance_set:
                current_members = next_members_map.get(pd.Timestamp(dt), [])
            continue

        if trading_dates[i - 1] in rebalance_set:
            current_members = next_members_map.get(pd.Timestamp(trading_dates[i - 1]), [])

        if current_members:
            day_ret = returns_df.loc[dt, current_members].dropna()
            bucket_ret = float(day_ret.mean()) if len(day_ret) else 0.0
        else:
            bucket_ret = 0.0

        current_level *= 1.0 + bucket_ret
        index_rows.append(
            {
                "date": dt,
                "close": current_level,
                "daily_return": bucket_ret,
                "holding_count": len(current_members),
            }
        )

    return pd.DataFrame(index_rows), pd.DataFrame(turnover_rows)


def summarize_long_only(index_df: pd.DataFrame, top_n: int) -> tuple[dict[str, object], list[dict[str, object]]]:
    nav = index_df.copy()
    nav["date"] = pd.to_datetime(nav["date"])
    nav = nav.set_index("date")
    ret = nav["close"].pct_change(fill_method=None).dropna()
    metrics = hedge_mod.calc_metrics(ret)
    summary = {
        "top_n": top_n,
        "annual": float(metrics.annual),
        "max_dd": float(metrics.max_dd),
        "sharpe": float(metrics.sharpe),
        "vol": float(metrics.vol),
        "total_return": float(metrics.total_return),
    }

    recent_rows: list[dict[str, object]] = []
    last_date = nav.index[-1]
    for years in WINDOWS:
        part_nav = nav.loc[nav.index >= last_date - pd.DateOffset(years=years), "close"]
        part_ret = part_nav.pct_change(fill_method=None).dropna()
        if len(part_ret) < 30:
            continue
        part_metrics = hedge_mod.calc_metrics(part_ret)
        recent_rows.append(
            {
                "top_n": top_n,
                "window_years": years,
                "annual": float(part_metrics.annual),
                "max_dd": float(part_metrics.max_dd),
                "sharpe": float(part_metrics.sharpe),
            }
        )
    return summary, recent_rows


def summarize_strategy(
    net: pd.DataFrame,
    turnover_df: pd.DataFrame,
    top_n: int,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    metrics = hedge_mod.calc_metrics(net["return_net"])
    summary = {
        "top_n": top_n,
        "net_annual": float(metrics.annual),
        "net_max_dd": float(metrics.max_dd),
        "net_sharpe": float(metrics.sharpe),
        "net_vol": float(metrics.vol),
        "net_total_return": float(metrics.total_return),
        "entry_exit_cost_sum": float(net["entry_exit_cost"].sum()),
        "rebalance_cost_sum": float(net["rebalance_cost"].sum()),
        "total_cost_sum": float(net["total_cost"].sum()),
        "entry_days": int(net["entry_exit_cost"].gt(0).sum()),
        "rebalance_events": int(len(turnover_df)),
        "avg_turnover_frac_one_side": float(turnover_df["turnover_frac_one_side"].mean()) if len(turnover_df) else 0.0,
    }

    recent_rows: list[dict[str, object]] = []
    last_date = net.index[-1]
    for years in WINDOWS:
        part = net.loc[net.index >= last_date - pd.DateOffset(years=years), "return_net"]
        if len(part) < 30:
            continue
        part_metrics = hedge_mod.calc_metrics(part)
        recent_rows.append(
            {
                "top_n": top_n,
                "window_years": years,
                "annual": float(part_metrics.annual),
                "max_dd": float(part_metrics.max_dd),
                "sharpe": float(part_metrics.sharpe),
            }
        )
    return summary, recent_rows


def main() -> None:
    trading_dates = freq_mod.load_trading_dates()
    rebalance_map = freq_mod.build_all_rebalance_dates(trading_dates)
    rebalance_dates = rebalance_map[REBALANCE_LABEL]
    symbols = freq_mod.load_universe()
    returns_df, caps_by_date = freq_mod.load_cache_panels(
        symbols=symbols,
        trading_dates=trading_dates,
        cap_dates=rebalance_dates,
        max_workers=8,
    )

    longonly_rows: list[dict[str, object]] = []
    longonly_recent_rows: list[dict[str, object]] = []
    strategy_rows: list[dict[str, object]] = []
    strategy_recent_rows: list[dict[str, object]] = []
    nav_cols: dict[str, pd.Series] = {}

    for top_n in COUNTS:
        index_df, turnover_df = build_index_and_turnover(
            trading_dates=trading_dates,
            returns_df=returns_df,
            caps_by_date=caps_by_date,
            rebalance_dates=rebalance_dates,
            top_n=top_n,
        )
        net = freq_mod.run_strategy(index_df=index_df, turnover_df=turnover_df)

        label = f"top_{top_n}"
        nav_cols[label] = index_df.set_index("date")["close"]
        index_df.to_csv(
            ROOT / f"wind_microcap_top_{top_n}_{REBALANCE_LABEL}_16y_cached.csv",
            index=False,
            encoding="utf-8",
        )
        turnover_df.to_csv(
            ROOT / f"microcap_top{top_n}_{REBALANCE_LABEL}_turnover_stats.csv",
            index=False,
            encoding="utf-8",
        )
        net.to_csv(
            ROOT / f"microcap_top{top_n}_mom{LOOKBACK}_hedge_zz1000_{REBALANCE_LABEL}_16y_costed_nav.csv",
            index_label="date",
            encoding="utf-8",
        )

        longonly_summary, longonly_recent = summarize_long_only(index_df=index_df, top_n=top_n)
        strategy_summary, strategy_recent = summarize_strategy(net=net, turnover_df=turnover_df, top_n=top_n)
        longonly_rows.append(longonly_summary)
        longonly_recent_rows.extend(longonly_recent)
        strategy_rows.append(strategy_summary)
        strategy_recent_rows.extend(strategy_recent)

    nav_df = pd.DataFrame(nav_cols).reset_index()
    longonly_df = pd.DataFrame(longonly_rows).sort_values("sharpe", ascending=False)
    longonly_recent_df = pd.DataFrame(longonly_recent_rows).sort_values(
        ["window_years", "sharpe"],
        ascending=[True, False],
    )
    strategy_df = pd.DataFrame(strategy_rows).sort_values("net_sharpe", ascending=False)
    strategy_recent_df = pd.DataFrame(strategy_recent_rows).sort_values(
        ["window_years", "sharpe"],
        ascending=[True, False],
    )

    nav_df.to_csv(ROOT / "microcap_top10_20_30_50_100_biweekly_navs_16y.csv", index=False, encoding="utf-8")
    longonly_df.to_csv(ROOT / "microcap_top10_20_30_50_100_biweekly_longonly_summary.csv", index=False, encoding="utf-8")
    longonly_recent_df.to_csv(
        ROOT / "microcap_top10_20_30_50_100_biweekly_longonly_recent_windows.csv",
        index=False,
        encoding="utf-8",
    )
    strategy_df.to_csv(ROOT / "microcap_top10_20_30_50_100_biweekly_strategy_summary.csv", index=False, encoding="utf-8")
    strategy_recent_df.to_csv(
        ROOT / "microcap_top10_20_30_50_100_biweekly_strategy_recent_windows.csv",
        index=False,
        encoding="utf-8",
    )

    payload = {
        "strategy": "top10_20_30_50_100_biweekly_driver_compare",
        "core_config": {
            "rebalance": REBALANCE_LABEL,
            "lookback": LOOKBACK,
            "hedge": "zz1000",
            "stock_cost_one_side": cost_mod.ENTRY_COST,
            "signal_rule": "baseline relative momentum, gap > 0 in, gap < 0 out",
        },
        "longonly_summary": longonly_df.to_dict(orient="records"),
        "longonly_recent_windows": longonly_recent_df.to_dict(orient="records"),
        "strategy_summary": strategy_df.to_dict(orient="records"),
        "strategy_recent_windows": strategy_recent_df.to_dict(orient="records"),
    }
    (ROOT / "microcap_top10_20_30_50_100_biweekly_driver_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=== strategy summary ===")
    print(strategy_df.to_string(index=False))
    print("=== long only summary ===")
    print(longonly_df.to_string(index=False))
    print("saved microcap_top10_20_30_50_100_biweekly_strategy_summary.csv")


if __name__ == "__main__":
    main()

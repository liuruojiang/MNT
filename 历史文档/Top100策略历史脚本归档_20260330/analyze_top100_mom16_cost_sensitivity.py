from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import analyze_microcap_zz1000_hedge as hedge_mod
import scan_top100_momentum_costs as cost_mod


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_PREFIX = "microcap_top100_mom16_cost_sensitivity"
LOOKBACK = 16


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run cost sensitivity analysis for Top 100 + 16d momentum + CSI1000 hedge."
    )
    parser.add_argument("--panel-path", type=Path, default=hedge_mod.DEFAULT_PANEL)
    parser.add_argument("--microcap-csv", type=Path, default=cost_mod.DEFAULT_MICROCAP_CSV)
    parser.add_argument("--turnover-csv", type=Path, default=cost_mod.DEFAULT_TURNOVER_CSV)
    parser.add_argument("--hedge-column", default=hedge_mod.DEFAULT_HEDGE_COLUMN)
    parser.add_argument("--futures-drag", type=float, default=hedge_mod.DEFAULT_FUTURES_DRAG)
    parser.add_argument(
        "--cost-grid",
        default="0,0.001,0.002,0.003,0.004,0.005",
        help="Comma-separated one-side cost grid. Example: 0,0.001,0.002,0.003",
    )
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    return parser.parse_args()


def parse_cost_grid(raw: str) -> list[float]:
    values = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        values.append(float(part))
    if not values:
        raise ValueError("Cost grid is empty.")
    return sorted(set(values))


def apply_cost_model(
    result: pd.DataFrame,
    turnover: pd.DataFrame,
    entry_cost_one_side: float,
    exit_cost_one_side: float,
    monthly_rebalance_one_side: float,
) -> pd.DataFrame:
    out = result.copy()
    active = out["holding"].ne("cash")
    prev_active = active.shift(1, fill_value=False)

    entry_cost = pd.Series(0.0, index=out.index, dtype=float)
    entry_cost.loc[active & ~prev_active] = entry_cost_one_side

    exit_cost = pd.Series(0.0, index=out.index, dtype=float)
    exit_cost.loc[~active & prev_active] = exit_cost_one_side

    if cost_mod.MONTHLY_REBALANCE_ONE_SIDE <= 0:
        raise ValueError("Base monthly rebalance cost constant must be positive.")
    scale = monthly_rebalance_one_side / cost_mod.MONTHLY_REBALANCE_ONE_SIDE
    rebalance_base = cost_mod.map_rebalance_apply_costs(out.index, turnover) * scale
    rebalance_cost = rebalance_base.where(active & prev_active, 0.0)

    out["entry_exit_cost"] = entry_cost + exit_cost
    out["rebalance_cost"] = rebalance_cost
    out["total_cost"] = out["entry_exit_cost"] + out["rebalance_cost"]
    out["return_net"] = (1.0 + out["return"]) * (1.0 - out["total_cost"]) - 1.0
    out["nav_net"] = (1.0 + out["return_net"]).cumprod()
    return out


def run_base_backtest(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    scan_args = argparse.Namespace(
        panel_path=args.panel_path,
        microcap_csv=args.microcap_csv,
        turnover_csv=args.turnover_csv,
        hedge_column=args.hedge_column,
        lookback_start=LOOKBACK,
        lookback_end=LOOKBACK,
        futures_drag=args.futures_drag,
        output_prefix="unused",
    )
    close_df = cost_mod.build_close_df(scan_args)
    turnover = cost_mod.load_turnover_table(args.turnover_csv)
    gross = hedge_mod.run_backtest(
        close_df=close_df,
        signal_model="momentum",
        lookback=LOOKBACK,
        bias_n=hedge_mod.DEFAULT_BIAS_N,
        bias_mom_day=hedge_mod.DEFAULT_BIAS_MOM_DAY,
        futures_drag=args.futures_drag,
        require_positive_microcap_mom=False,
        r2_window=hedge_mod.DEFAULT_R2_WINDOW,
        r2_threshold=0.0,
        vol_scale_enabled=False,
        target_vol=hedge_mod.DEFAULT_TARGET_VOL,
        vol_window=hedge_mod.DEFAULT_VOL_WINDOW,
        max_lev=hedge_mod.DEFAULT_MAX_LEV,
        min_lev=hedge_mod.DEFAULT_MIN_LEV,
        scale_threshold=hedge_mod.DEFAULT_SCALE_THRESHOLD,
    )
    return gross, turnover


def main() -> None:
    args = parse_args()
    cost_grid = parse_cost_grid(args.cost_grid)
    gross, turnover = run_base_backtest(args)
    gross_metrics = hedge_mod.calc_metrics(gross["return"])

    active = gross["holding"].ne("cash")
    prev_active = active.shift(1, fill_value=False)
    structural = {
        "lookback": LOOKBACK,
        "gross_annual": gross_metrics.annual,
        "gross_max_dd": gross_metrics.max_dd,
        "gross_sharpe": gross_metrics.sharpe,
        "gross_vol": gross_metrics.vol,
        "gross_total_return": gross_metrics.total_return,
        "entry_days": int((active & ~prev_active).sum()),
        "exit_days": int((~active & prev_active).sum()),
        "holding_days_pct": float(active.mean()),
        "rebalance_cost_days": int(cost_mod.map_rebalance_apply_costs(gross.index, turnover).gt(0).sum()),
    }

    rows: list[dict[str, float | int]] = []
    for signal_cost in cost_grid:
        for monthly_cost in cost_grid:
            net = apply_cost_model(
                result=gross,
                turnover=turnover,
                entry_cost_one_side=signal_cost,
                exit_cost_one_side=signal_cost,
                monthly_rebalance_one_side=monthly_cost,
            )
            metrics = hedge_mod.calc_metrics(net["return_net"])
            rows.append(
                {
                    "signal_one_side_cost": signal_cost,
                    "monthly_rebalance_one_side_cost": monthly_cost,
                    "net_annual": metrics.annual,
                    "net_max_dd": metrics.max_dd,
                    "net_sharpe": metrics.sharpe,
                    "net_vol": metrics.vol,
                    "net_total_return": metrics.total_return,
                    "entry_exit_cost_sum": float(net["entry_exit_cost"].sum()),
                    "rebalance_cost_sum": float(net["rebalance_cost"].sum()),
                    "total_cost_sum": float(net["total_cost"].sum()),
                }
            )

    grid_df = pd.DataFrame(rows).sort_values(
        ["signal_one_side_cost", "monthly_rebalance_one_side_cost"]
    ).reset_index(drop=True)

    output_prefix = args.output_prefix
    grid_path = ROOT / f"{output_prefix}_grid.csv"
    annual_wide_path = ROOT / f"{output_prefix}_annual_wide.csv"
    sharpe_wide_path = ROOT / f"{output_prefix}_sharpe_wide.csv"
    dd_wide_path = ROOT / f"{output_prefix}_maxdd_wide.csv"
    summary_path = ROOT / f"{output_prefix}_summary.json"

    grid_df.to_csv(grid_path, index=False, encoding="utf-8")
    grid_df.pivot(
        index="signal_one_side_cost",
        columns="monthly_rebalance_one_side_cost",
        values="net_annual",
    ).to_csv(annual_wide_path, encoding="utf-8")
    grid_df.pivot(
        index="signal_one_side_cost",
        columns="monthly_rebalance_one_side_cost",
        values="net_sharpe",
    ).to_csv(sharpe_wide_path, encoding="utf-8")
    grid_df.pivot(
        index="signal_one_side_cost",
        columns="monthly_rebalance_one_side_cost",
        values="net_max_dd",
    ).to_csv(dd_wide_path, encoding="utf-8")

    baseline = grid_df.loc[
        (grid_df["signal_one_side_cost"] == 0.003)
        & (grid_df["monthly_rebalance_one_side_cost"] == 0.003)
    ]
    summary = {
        "strategy": "top100_mom16_hedge_zz1000_cost_sensitivity",
        "lookback": LOOKBACK,
        "gross_metrics": structural,
        "cost_grid": cost_grid,
        "baseline_3permil_each": baseline.iloc[0].to_dict() if not baseline.empty else None,
        "best_by_net_sharpe": grid_df.sort_values(
            ["net_sharpe", "net_annual"], ascending=[False, False]
        ).iloc[0].to_dict(),
        "worst_by_net_sharpe": grid_df.sort_values(
            ["net_sharpe", "net_annual"], ascending=[True, True]
        ).iloc[0].to_dict(),
        "notes": {
            "signal_cost_definition": "Entry and exit each charged at signal_one_side_cost on the microcap stock basket.",
            "monthly_rebalance_definition": "Monthly stock-basket reshuffle charged at 2 * monthly_rebalance_one_side_cost * replaced_fraction.",
            "futures_leg": "No extra transaction cost added; futures drag stays at 3/10000 per active day.",
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(grid_df.to_string(index=False))
    print(f"saved {grid_path.name}")
    print(f"saved {annual_wide_path.name}")
    print(f"saved {sharpe_wide_path.name}")
    print(f"saved {dd_wide_path.name}")
    print(f"saved {summary_path.name}")


if __name__ == "__main__":
    main()

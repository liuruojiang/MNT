"""Test whether Strategy C still needs a dedicated 15% bond sleeve."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import research_subc_bond_sleeve_backtest as base


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "outputs" / "subc_bond_necessity_20260811"

COMMON = dict(base.COMMON_WEIGHTS)
NO_BOND_SCALE = 1.0 / sum(COMMON.values())

VARIANTS = {
    "VGIT 15%": {**COMMON, "VGIT": 0.15},
    "VGIT 7.5% + BIL 7.5%": {**COMMON, "VGIT": 0.075, "BIL": 0.075},
    "BIL 15%": {**COMMON, "BIL": 0.15},
    "No bond, pro-rata risk assets": {
        ticker: weight * NO_BOND_SCALE for ticker, weight in COMMON.items()
    },
}


def plot_results(returns: pd.DataFrame, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    nav = returns.apply(base.nav_from_returns)
    nav = nav.div(nav.iloc[0])
    drawdown = nav.div(nav.cummax()).sub(1.0)

    fig, axes = plt.subplots(2, 1, figsize=(13.5, 8.8), sharex=True)
    fig.subplots_adjust(left=0.08, right=0.985, top=0.90, bottom=0.09, hspace=0.10)
    for name in nav.columns:
        axes[0].plot(nav.index, nav[name], linewidth=2.0, label=name)
        axes[1].plot(drawdown.index, drawdown[name] * 100, linewidth=1.55, label=name)
    axes[0].set_title("完整新策略 C：债券必要性测试（均含15%目标波动率）", fontsize=14, fontweight="bold")
    axes[0].set_ylabel("归一化净值")
    axes[0].grid(True, alpha=0.24)
    axes[0].legend(frameon=False, ncol=2)
    axes[1].axhline(0, color="#6B7280", linewidth=0.8)
    axes[1].set_ylabel("回撤（%）")
    axes[1].set_xlabel("日期")
    axes[1].grid(True, alpha=0.24)
    axes[1].xaxis.set_major_locator(mdates.YearLocator())
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle("策略 C：15%债券仓是否值得保留？", fontsize=17, fontweight="bold", y=0.975)
    fig.text(
        0.01,
        0.018,
        "Yahoo复权收盘；美股交易日；年度再平衡10bps；V7.7目标波动率15日/15%、0.5-1.5x、阈值0.10、融资利差100bps、调仓6bps。",
        fontsize=8.5,
        color="#4B5563",
    )
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    v77 = base.load_module(base.V77_PATH, "v77_bond_necessity")
    v79 = base.load_module(base.V79_PATH, "v79_bond_necessity_loader")
    all_prices, sources, excluded_date = base.fetch_adjusted_close(v79)

    required = sorted(set().union(*(weights.keys() for weights in VARIANTS.values())))
    prices = base.common_price_frame(all_prices, required + ["SPY"])

    scaled_returns = {}
    raw_returns = {}
    scales = {}
    scale_costs = {}
    asset_costs = {}
    turnovers = {}
    for name, weights in VARIANTS.items():
        raw, turnover, asset_cost = base.annual_rebalanced_returns(prices, weights)
        scaled, scale, scale_cost = v77._apply_subc_vol_scaling(raw, prices)
        raw_returns[name] = raw
        scaled_returns[name] = scaled
        scales[name] = scale
        scale_costs[name] = scale_cost
        asset_costs[name] = asset_cost
        turnovers[name] = turnover

    returns = pd.DataFrame(scaled_returns).dropna(how="any")
    raw_frame = pd.DataFrame(raw_returns).reindex(returns.index)
    scale_frame = pd.DataFrame(scales).reindex(returns.index)
    metrics = base.window_metrics(returns)

    delta_rows = []
    for candidate in list(VARIANTS)[1:]:
        delta_rows.append(base.delta_metrics(metrics, "VGIT 15%", candidate))
    deltas = pd.concat(delta_rows, ignore_index=True)

    spy_ret = prices["SPY"].pct_change().reindex(returns.index)
    defense_rows = []
    for name in VARIANTS:
        common = pd.concat([returns[name], spy_ret.rename("SPY")], axis=1).dropna()
        worst_decile = common["SPY"] <= common["SPY"].quantile(0.10)
        y2022 = common.loc["2022-01-01":"2022-12-31", name]
        defense_rows.append(
            {
                "series": name,
                "correlation_to_spy": common[name].corr(common["SPY"]),
                "average_return_on_worst_10pct_spy_days": common.loc[worst_decile, name].mean(),
                "calendar_2022_return": (1.0 + y2022).prod() - 1.0,
            }
        )
    defense = pd.DataFrame(defense_rows)

    overlay_rows = []
    for name in VARIANTS:
        scale = scale_frame[name]
        overlay_rows.append(
            {
                "series": name,
                "average_scale": scale.mean(),
                "median_scale": scale.median(),
                "pct_days_at_min_0_5": (scale <= 0.5000001).mean(),
                "pct_days_at_max_1_5": (scale >= 1.4999999).mean(),
                "scale_adjustment_days": int((scale.diff().abs() > 1e-12).sum()),
                "scale_cost_sum": scale_costs[name].reindex(returns.index).sum(),
                "asset_rebalance_cost_sum": asset_costs[name].reindex(returns.index).sum(),
                "annual_rebalance_turnover_sum": turnovers[name].reindex(returns.index).sum(),
            }
        )
    overlay = pd.DataFrame(overlay_rows)

    prior_path = ROOT / "outputs" / "subc_bond_sleeve_20260811" / "full_strategy_metrics.csv"
    prior = pd.read_csv(prior_path)
    prior = prior[prior["series"] == "New C + VGIT 15%"].set_index("window")
    current = metrics[metrics["series"] == "VGIT 15%"].set_index("window")
    parity_windows = [window for window in current.index if window in prior.index]
    parity_max_metric_diff = float(
        max(
            (current.loc[parity_windows, "cagr"] - prior.loc[parity_windows, "cagr"]).abs().max(),
            (
                current.loc[parity_windows, "max_drawdown"]
                - prior.loc[parity_windows, "max_drawdown"]
            ).abs().max(),
        )
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_results(returns, OUT_DIR / "subc_bond_necessity_backtest.png")
    daily = pd.concat(
        {
            "raw_return": raw_frame,
            "scaled_return": returns,
            "scaled_nav": returns.apply(base.nav_from_returns),
            "scale": scale_frame,
        },
        axis=1,
    )
    daily.to_csv(OUT_DIR / "daily_nav_and_returns.csv", encoding="utf-8-sig")
    metrics.to_csv(OUT_DIR / "metrics.csv", index=False, encoding="utf-8-sig")
    deltas.to_csv(OUT_DIR / "candidate_deltas.csv", index=False, encoding="utf-8-sig")
    defense.to_csv(OUT_DIR / "defense_metrics.csv", index=False, encoding="utf-8-sig")
    overlay.to_csv(OUT_DIR / "vol_scale_audit.csv", index=False, encoding="utf-8-sig")
    sources.to_csv(OUT_DIR / "sources.csv", index=False, encoding="utf-8-sig")

    audit = {
        "status": "observed_real_data_research_backtest",
        "created_at_shanghai": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "data_source": "Yahoo adjusted close via mnt_bot V 7.9 plus.py",
        "sample_start": returns.index.min().date().isoformat(),
        "sample_end": returns.index.max().date().isoformat(),
        "excluded_unconfirmed_date": excluded_date,
        "calendar": "common US ETF sessions; BTC weekend return enters next ETF session",
        "asset_rebalance": "before first US ETF session of each calendar year",
        "asset_rebalance_cost_rate": base.ASSET_REBAL_COST,
        "target_vol_source": "mnt_bot V 7.7 plus.py::_apply_subc_vol_scaling",
        "baseline_parity_to_prior_bond_test_max_metric_difference": parity_max_metric_diff,
        "production_code_changed": False,
        "live_orders": False,
        "limitations": [
            "No valid 10Y ETF-only result because KMLM began in December 2020",
            "No taxes or investor-specific withholding modeled",
            "No intraday bid/ask slippage beyond configured rebalance costs",
        ],
    }
    (OUT_DIR / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    full = metrics[metrics["window"] == "Full"].set_index("series")
    defense_idx = defense.set_index("series")
    overlay_idx = overlay.set_index("series")
    record_lines = [
        "# Strategy C Bond Necessity Test",
        "",
        "## Scope",
        "",
        "Test whether the dedicated 15% VGIT sleeve earns its place after gold, managed futures, bitcoin, and the official target-volatility overlay are already present.",
        "",
        "## Full-sample results",
        "",
        "| Variant | CAGR | Max drawdown | Annual vol | Sharpe | 2022 return | Avg scale |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in VARIANTS:
        row = full.loc[name]
        record_lines.append(
            f"| {name} | {row['cagr']:.2%} | {row['max_drawdown']:.2%} | "
            f"{row['annual_vol']:.2%} | {row['sharpe_0rf']:.2f} | "
            f"{defense_idx.loc[name, 'calendar_2022_return']:.2%} | "
            f"{overlay_idx.loc[name, 'average_scale']:.2f}x |"
        )
    record_lines.extend(
        [
            "",
            "## Integrity and limitations",
            "",
            f"- Sample: {returns.index.min().date()} to {returns.index.max().date()}.",
            "- Yahoo adjusted close; common US ETF calendar; current unconfirmed bar excluded.",
            "- Annual rebalance cost 10 bps plus official V7.7 target-vol financing and scale costs.",
            f"- Baseline parity to the prior bond test: max CAGR/MDD difference {parity_max_metric_diff:.3g}.",
            "- Ten-year result is N/A because KMLM lacks sufficient live ETF history.",
            "- Research-only; no production change or live order.",
        ]
    )
    (OUT_DIR / "record.md").write_text("\n".join(record_lines) + "\n", encoding="utf-8")

    print("METRICS")
    print(metrics.to_string(index=False))
    print("\nDELTAS")
    print(deltas.to_string(index=False))
    print("\nDEFENSE")
    print(defense.to_string(index=False))
    print("\nOVERLAY")
    print(overlay.to_string(index=False))
    print("\nPARITY_MAX_METRIC_DIFF", parity_max_metric_diff)
    print("OUTPUT", OUT_DIR)


if __name__ == "__main__":
    main()

"""Test independent target-vol control for the proposed Strategy C pool.

Research-only first pass.  Equities share a SPY volatility signal; treasury,
gold, each managed-futures ETF, and bitcoin use their own return volatility.
The official V7.7 target-vol parameters, lag, threshold, financing spread, and
scale-adjustment cost are preserved.  Production strategy files are untouched.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import research_subc_bond_sleeve_backtest as base
import research_subc_target_vol_scope_backtest as scope_base


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "outputs" / "subc_independent_vol_20260812"
FORMAL_START = scope_base.FORMAL_START
AFTER_WEIGHTS = scope_base.AFTER_WEIGHTS
EQUITY_ASSETS = scope_base.EQUITY_ASSETS

CURRENT = "Portfolio vol -> all assets (current)"
SPY_EQUITY = "SPY vol -> equities only"
INDEPENDENT = "Independent sleeve vol"
NO_SCALE = "No target-vol scaling"
VARIANT_ORDER = [CURRENT, SPY_EQUITY, INDEPENDENT, NO_SCALE]

SLEEVE_SIGNALS = {
    "Equities (SPY)": (sorted(EQUITY_ASSETS), "SPY"),
    "Treasury": (["TREASURY"], "TREASURY"),
    "Managed futures DBMF": (["MF_1"], "MF_1"),
    "Managed futures KMLM": (["MF_2"], "MF_2"),
    "Gold": (["GOLD"], "GOLD"),
    "Bitcoin": (["BTC"], "BTC"),
}


def simulate_asset_components(
    prices: pd.DataFrame,
    after_weights: dict[str, float],
    before_weights: dict[str, float] | None = None,
    btc_start: pd.Timestamp | None = None,
    cost_rate: float = base.ASSET_REBAL_COST,
) -> pd.DataFrame:
    """Annual-rebalanced portfolio decomposed into per-asset P&L/exposure."""
    before = dict(before_weights or after_weights)
    assets = sorted(set(after_weights) | set(before))
    required = sorted(set(assets) | {"BIL"})
    asset_ret = prices[required].pct_change(fill_method=None)
    # Match the official overlay warmup: BIL must be available before the
    # strategy can model released cash or financing.
    start_candidates = [
        asset_ret[name].first_valid_index() for name in sorted(set(before) | {"BIL"})
    ]
    start = max(date for date in start_candidates if date is not None)
    asset_ret = asset_ret.loc[start:]

    initial = after_weights if btc_start is None or start >= btc_start else before
    holdings = pd.Series(initial, dtype=float)
    prev_value = float(holdings.sum())
    prev_year = asset_ret.index[0].year
    in_after_phase = btc_start is None or asset_ret.index[0] >= btc_start
    rows: list[dict[str, float | pd.Timestamp]] = []

    for date, returns_row in asset_ret.iterrows():
        target = after_weights if btc_start is None or date >= btc_start else before
        phase_changed = btc_start is not None and date >= btc_start and not in_after_phase
        annual_rebalance = date.year != prev_year
        turnover = 0.0
        asset_cost = 0.0
        if phase_changed or annual_rebalance:
            actual = holdings / holdings.sum()
            union = actual.index.union(pd.Index(target))
            actual = actual.reindex(union, fill_value=0.0)
            target_series = pd.Series(target, dtype=float).reindex(union, fill_value=0.0)
            turnover = float((target_series - actual).abs().sum())
            asset_cost = float(holdings.sum() * turnover * cost_rate)
            holdings = target_series * float(holdings.sum() - asset_cost)
        if phase_changed:
            in_after_phase = True
        if annual_rebalance:
            prev_year = date.year

        pre_return_value = float(holdings.sum())
        output: dict[str, float | pd.Timestamp] = {
            "date": date,
            "asset_cost_return": (pre_return_value - prev_value) / prev_value,
            "asset_turnover": turnover,
            "asset_cost_fraction": asset_cost / prev_value,
        }
        pnl_total = 0.0
        for asset in assets:
            holding = float(holdings.get(asset, 0.0))
            asset_return = float(returns_row.get(asset, 0.0))
            if not np.isfinite(asset_return):
                asset_return = 0.0
            contribution = holding * asset_return / prev_value
            output[f"contribution::{asset}"] = contribution
            output[f"exposure::{asset}"] = holding / prev_value
            pnl_total += contribution

        output["base_return"] = float(output["asset_cost_return"]) + pnl_total
        holdings = holdings * (1.0 + returns_row.reindex(holdings.index).fillna(0.0))
        value = float(holdings.sum())
        direct_return = value / prev_value - 1.0
        if not math.isclose(float(output["base_return"]), direct_return, abs_tol=2e-14):
            raise RuntimeError(f"Asset component reconciliation failed on {date}")
        rows.append(output)
        prev_value = value
    return pd.DataFrame(rows).set_index("date")


def aggregate_for_existing_overlays(asset_components: pd.DataFrame) -> pd.DataFrame:
    result = asset_components[
        ["base_return", "asset_cost_return", "asset_turnover", "asset_cost_fraction"]
    ].copy()
    equity_contribution = sum(
        (asset_components[f"contribution::{asset}"] for asset in EQUITY_ASSETS),
        start=pd.Series(0.0, index=asset_components.index),
    )
    equity_exposure = sum(
        (asset_components[f"exposure::{asset}"] for asset in EQUITY_ASSETS),
        start=pd.Series(0.0, index=asset_components.index),
    )
    total_exposure = sum(
        (
            asset_components[column]
            for column in asset_components
            if column.startswith("exposure::")
        ),
        start=pd.Series(0.0, index=asset_components.index),
    )
    result["equity_contribution"] = equity_contribution
    result["non_equity_contribution"] = (
        result["base_return"] - result["asset_cost_return"] - equity_contribution
    )
    result["equity_exposure"] = equity_exposure
    result["non_equity_exposure"] = total_exposure - equity_exposure
    return result


def independent_overlay(
    components: pd.DataFrame,
    prices: pd.DataFrame,
    v77,
    active_sleeves: list[str] | None = None,
) -> tuple[pd.Series, pd.DataFrame, pd.Series, pd.Series]:
    index = components.index
    rf = prices["BIL"].pct_change(fill_method=None).reindex(index).fillna(0.0)
    daily_spread = v77.PROD_VS_SPREAD_BPS / 10000 / v77.US_TRADING_DAYS
    output = components["asset_cost_return"].copy()
    total_cost = pd.Series(0.0, index=index)
    gross = pd.Series(0.0, index=index)
    scales: dict[str, pd.Series] = {}

    covered_assets: set[str] = set()
    selected = set(active_sleeves or SLEEVE_SIGNALS)
    for sleeve, (assets, signal_asset) in SLEEVE_SIGNALS.items():
        if sleeve not in selected:
            continue
        covered_assets.update(assets)
        signal_return = (
            prices[signal_asset].pct_change(fill_method=None).reindex(index).fillna(0.0)
        )
        scale = scope_base.thresholded_scale(signal_return, v77)
        scales[sleeve] = scale
        exposure = sum(
            (components[f"exposure::{asset}"] for asset in assets),
            start=pd.Series(0.0, index=index),
        )
        contribution = sum(
            (components[f"contribution::{asset}"] for asset in assets),
            start=pd.Series(0.0, index=index),
        )
        output += scale * contribution
        delta_exposure = (scale - 1.0) * exposure
        reduced = delta_exposure <= 0.0
        output.loc[reduced] += (-delta_exposure.loc[reduced]) * rf.loc[reduced]
        output.loc[~reduced] -= delta_exposure.loc[~reduced] * (
            rf.loc[~reduced] + daily_spread
        )
        scale_cost = (
            exposure
            * scale.diff().abs().fillna(0.0)
            * v77.PROD_VS_REBAL_COST_BPS
            / 10000
        )
        output -= scale_cost
        total_cost += scale_cost
        gross += scale * exposure

    all_assets = {
        column.split("::", 1)[1]
        for column in components
        if column.startswith("exposure::")
    }
    uncovered = sorted(all_assets - covered_assets)
    for asset in uncovered:
        output += components[f"contribution::{asset}"]
        gross += components[f"exposure::{asset}"]
    return output, pd.DataFrame(scales), total_cost, gross


def run_ablations(
    prices: pd.DataFrame,
    after_weights: dict[str, float],
    v77,
    before_weights: dict[str, float] | None = None,
    btc_start: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Add one self-vol sleeve at a time on top of SPY-controlled equities."""
    components = simulate_asset_components(
        prices, after_weights, before_weights, btc_start
    )
    equity = "Equities (SPY)"
    configurations = {
        "SPY equities only": [equity],
        "+ Treasury self vol": [equity, "Treasury"],
        "+ DBMF self vol": [equity, "Managed futures DBMF"],
        "+ KMLM self vol": [equity, "Managed futures KMLM"],
        "+ Gold self vol": [equity, "Gold"],
        "+ Bitcoin self vol": [equity, "Bitcoin"],
        "All non-equity self vol": list(SLEEVE_SIGNALS),
    }
    returns = {}
    for name, sleeves in configurations.items():
        returns[name] = independent_overlay(
            components, prices, v77, active_sleeves=sleeves
        )[0]
    return pd.DataFrame(returns).dropna(how="any")


def run_sample(
    prices: pd.DataFrame,
    after_weights: dict[str, float],
    v77,
    before_weights: dict[str, float] | None = None,
    btc_start: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, float]:
    asset_components = simulate_asset_components(
        prices, after_weights, before_weights, btc_start
    )
    aggregate = aggregate_for_existing_overlays(asset_components)
    reference = scope_base.simulate_components(
        prices, after_weights, before_weights, btc_start
    )
    component_parity = float(
        (aggregate["base_return"] - reference["base_return"]).abs().max()
    )

    current_ret, current_scale, current_cost, current_gross = scope_base.apply_overlay(
        aggregate, prices, "portfolio", "all", v77
    )
    spy_ret, spy_scale, spy_cost, spy_gross = scope_base.apply_overlay(
        aggregate, prices, "spy", "equity", v77
    )
    independent_ret, independent_scales, independent_cost, independent_gross = (
        independent_overlay(asset_components, prices, v77)
    )
    no_ret, no_scale, no_cost, no_gross = scope_base.apply_overlay(
        aggregate, prices, "none", "none", v77
    )
    returns = pd.DataFrame(
        {
            CURRENT: current_ret,
            SPY_EQUITY: spy_ret,
            INDEPENDENT: independent_ret,
            NO_SCALE: no_ret,
        }
    ).dropna(how="any")
    variant_scales = pd.DataFrame(
        {CURRENT: current_scale, SPY_EQUITY: spy_scale, NO_SCALE: no_scale}
    ).reindex(returns.index)
    costs = pd.DataFrame(
        {
            CURRENT: current_cost,
            SPY_EQUITY: spy_cost,
            INDEPENDENT: independent_cost,
            NO_SCALE: no_cost,
        }
    ).reindex(returns.index)
    gross = pd.DataFrame(
        {
            CURRENT: current_gross,
            SPY_EQUITY: spy_gross,
            INDEPENDENT: independent_gross,
            NO_SCALE: no_gross,
        }
    ).reindex(returns.index)
    scales = pd.concat(
        {
            "variant": variant_scales,
            "independent_sleeve": independent_scales.reindex(returns.index),
        },
        axis=1,
    )
    return returns, scales, costs, gross, component_parity


def overlay_audit(
    scales: pd.DataFrame, costs: pd.DataFrame, gross: pd.DataFrame, sample: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    variant_rows = []
    for name in VARIANT_ORDER:
        scale = (
            scales[("variant", name)]
            if ("variant", name) in scales
            else pd.Series(np.nan, index=scales.index)
        )
        variant_rows.append(
            {
                "sample": sample,
                "series": name,
                "average_scale": scale.mean(),
                "adjustment_days": int((scale.diff().abs() > 1e-12).sum()),
                "total_scale_cost_fraction": costs[name].sum(),
                "average_gross_exposure": gross[name].mean(),
                "maximum_gross_exposure": gross[name].max(),
            }
        )
    sleeve_rows = []
    for sleeve in SLEEVE_SIGNALS:
        scale = scales[("independent_sleeve", sleeve)]
        sleeve_rows.append(
            {
                "sample": sample,
                "sleeve": sleeve,
                "average_scale": scale.mean(),
                "median_scale": scale.median(),
                "pct_days_at_min_0_5": (scale <= 0.5000001).mean(),
                "pct_days_at_max_1_5": (scale >= 1.4999999).mean(),
                "adjustment_days": int((scale.diff().abs() > 1e-12).sum()),
            }
        )
    return pd.DataFrame(variant_rows), pd.DataFrame(sleeve_rows)


def plot_results(frame: pd.DataFrame, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    nav = frame.apply(base.nav_from_returns).div(
        frame.apply(base.nav_from_returns).iloc[0]
    )
    drawdown = nav.div(nav.cummax()).sub(1.0)
    fig, axes = plt.subplots(2, 1, figsize=(14.0, 9.2), sharex=True)
    fig.subplots_adjust(left=0.08, right=0.985, top=0.90, bottom=0.09, hspace=0.10)
    for name in VARIANT_ORDER:
        axes[0].plot(nav.index, nav[name], linewidth=1.8, label=name)
        axes[1].plot(drawdown.index, drawdown[name] * 100, linewidth=1.35, label=name)
    axes[0].set_title("策略 C：独立波动率管理长周期代理", fontsize=14, fontweight="bold")
    axes[0].set_ylabel("归一化净值")
    axes[0].grid(True, alpha=0.24)
    axes[0].legend(frameon=False, fontsize=9, ncol=2)
    axes[1].axhline(0, color="#6B7280", linewidth=0.8)
    axes[1].set_ylabel("回撤（%）")
    axes[1].set_xlabel("日期")
    axes[1].grid(True, alpha=0.24)
    axes[1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle("统一缩放 vs 分资产独立缩放", fontsize=17, fontweight="bold", y=0.975)
    fig.text(
        0.01,
        0.018,
        "15日/15%目标波动率、0.5-1.5x、0.10阈值、融资BIL+100bps、缩放成本6bps；年度资产再平衡10bps。",
        fontsize=8.2,
        color="#4B5563",
    )
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def markdown_metrics(metrics: pd.DataFrame) -> list[str]:
    lines = [
        "| Variant | Window | CAGR | Max drawdown | Annual vol | Sharpe |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for name in VARIANT_ORDER:
        for _, row in metrics[metrics["series"] == name].iterrows():
            if pd.isna(row["cagr"]):
                lines.append(f"| {name} | {row['window']} | N/A | N/A | N/A | N/A |")
            else:
                lines.append(
                    f"| {name} | {row['window']} | {row['cagr']:.2%} | "
                    f"{row['max_drawdown']:.2%} | {row['annual_vol']:.2%} | "
                    f"{row['sharpe_0rf']:.2f} |"
                )
    return lines


def main() -> None:
    v77 = base.load_module(base.V77_PATH, "v77_independent_vol")
    v79 = base.load_module(base.V79_PATH, "v79_independent_vol_loader")
    raw, sources, excluded_date = scope_base.long_base.fetch_raw(v79)
    calendar = raw["SPY"].index

    long_prices, proxy_map = scope_base.build_stitched_prices(raw, calendar)
    before_weights = scope_base.long_base.pre_btc_weights(AFTER_WEIGHTS, "renormalize")
    btc_start = long_prices["BTC"].first_valid_index()
    long_returns, long_scales, long_costs, long_gross, long_component_parity = run_sample(
        long_prices, AFTER_WEIGHTS, v77, before_weights, btc_start
    )
    long_ablations = run_ablations(
        long_prices, AFTER_WEIGHTS, v77, before_weights, btc_start
    )

    formal_prices = scope_base.build_formal_prices(raw, calendar)
    formal_returns, formal_scales, formal_costs, formal_gross, formal_component_parity = (
        run_sample(formal_prices, AFTER_WEIGHTS, v77)
    )
    formal_ablations = run_ablations(formal_prices, AFTER_WEIGHTS, v77)
    formal_returns = formal_returns.loc[formal_returns.index >= FORMAL_START]
    formal_ablations = formal_ablations.loc[formal_ablations.index >= FORMAL_START]
    formal_scales = formal_scales.reindex(formal_returns.index)
    formal_costs = formal_costs.reindex(formal_returns.index)
    formal_gross = formal_gross.reindex(formal_returns.index)

    long_metrics = base.window_metrics(long_returns)
    formal_metrics = base.window_metrics(formal_returns)
    long_deltas = pd.concat(
        [
            base.delta_metrics(long_metrics, CURRENT, candidate)
            for candidate in VARIANT_ORDER[1:]
        ],
        ignore_index=True,
    )
    formal_deltas = pd.concat(
        [
            base.delta_metrics(formal_metrics, CURRENT, candidate)
            for candidate in VARIANT_ORDER[1:]
        ],
        ignore_index=True,
    )
    long_ablation_metrics = base.window_metrics(long_ablations)
    formal_ablation_metrics = base.window_metrics(formal_ablations)
    ablation_baseline = "SPY equities only"
    long_ablation_deltas = pd.concat(
        [
            base.delta_metrics(long_ablation_metrics, ablation_baseline, candidate)
            for candidate in long_ablations.columns[1:]
        ],
        ignore_index=True,
    )
    formal_ablation_deltas = pd.concat(
        [
            base.delta_metrics(formal_ablation_metrics, ablation_baseline, candidate)
            for candidate in formal_ablations.columns[1:]
        ],
        ignore_index=True,
    )
    stress = pd.concat(
        [
            scope_base.stress_metrics(long_returns, "long_proxy"),
            scope_base.stress_metrics(formal_returns, "formal_overlap"),
        ],
        ignore_index=True,
    )
    long_overlay, long_sleeves = overlay_audit(
        long_scales, long_costs, long_gross, "long_proxy"
    )
    formal_overlay, formal_sleeves = overlay_audit(
        formal_scales, formal_costs, formal_gross, "formal_overlap"
    )
    overlay = pd.concat([long_overlay, formal_overlay], ignore_index=True)
    sleeve_scales = pd.concat([long_sleeves, formal_sleeves], ignore_index=True)

    prior_metrics = pd.read_csv(
        ROOT / "outputs" / "subc_target_vol_scope_20260812" / "long_proxy_metrics.csv"
    )
    prior_daily = pd.read_csv(
        ROOT
        / "outputs"
        / "subc_target_vol_scope_20260812"
        / "daily_nav_and_audit.csv",
        header=[0, 1],
        index_col=0,
        parse_dates=True,
    )[("return", CURRENT)].dropna()
    common_parity_index = long_returns.index.intersection(prior_daily.index)
    daily_baseline_parity = float(
        (
            long_returns.loc[common_parity_index, CURRENT]
            - prior_daily.loc[common_parity_index]
        )
        .abs()
        .max()
    )
    prior_current = prior_metrics[prior_metrics["series"] == CURRENT].set_index("window")
    matched_current_metrics = base.window_metrics(
        long_returns.loc[: prior_daily.index.max(), [CURRENT]]
    )
    measured_current = matched_current_metrics.set_index("window")
    baseline_parity = pd.DataFrame(
        {
            "window": ["Full", "10Y", "5Y", "3Y", "1Y"],
            "cagr_difference": [
                measured_current.loc[w, "cagr"] - prior_current.loc[w, "cagr"]
                for w in ["Full", "10Y", "5Y", "3Y", "1Y"]
            ],
            "max_drawdown_difference": [
                measured_current.loc[w, "max_drawdown"]
                - prior_current.loc[w, "max_drawdown"]
                for w in ["Full", "10Y", "5Y", "3Y", "1Y"]
            ],
        }
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_results(long_returns, OUT_DIR / "subc_independent_vol.png")
    pd.concat(
        {
            "return": long_returns,
            "nav": long_returns.apply(base.nav_from_returns),
            "cost": long_costs,
            "gross_exposure": long_gross,
        },
        axis=1,
    ).to_csv(OUT_DIR / "long_daily_nav_and_audit.csv", encoding="utf-8-sig")
    long_scales.to_csv(OUT_DIR / "long_daily_scales.csv", encoding="utf-8-sig")
    long_metrics.to_csv(OUT_DIR / "long_proxy_metrics.csv", index=False, encoding="utf-8-sig")
    formal_metrics.to_csv(OUT_DIR / "formal_overlap_metrics.csv", index=False, encoding="utf-8-sig")
    long_deltas.to_csv(OUT_DIR / "long_proxy_deltas.csv", index=False, encoding="utf-8-sig")
    formal_deltas.to_csv(OUT_DIR / "formal_overlap_deltas.csv", index=False, encoding="utf-8-sig")
    long_ablation_metrics.to_csv(
        OUT_DIR / "long_ablation_metrics.csv", index=False, encoding="utf-8-sig"
    )
    formal_ablation_metrics.to_csv(
        OUT_DIR / "formal_ablation_metrics.csv", index=False, encoding="utf-8-sig"
    )
    long_ablation_deltas.to_csv(
        OUT_DIR / "long_ablation_deltas.csv", index=False, encoding="utf-8-sig"
    )
    formal_ablation_deltas.to_csv(
        OUT_DIR / "formal_ablation_deltas.csv", index=False, encoding="utf-8-sig"
    )
    stress.to_csv(OUT_DIR / "stress_periods.csv", index=False, encoding="utf-8-sig")
    overlay.to_csv(OUT_DIR / "overlay_audit.csv", index=False, encoding="utf-8-sig")
    sleeve_scales.to_csv(OUT_DIR / "independent_sleeve_scale_audit.csv", index=False, encoding="utf-8-sig")
    baseline_parity.to_csv(OUT_DIR / "baseline_parity.csv", index=False, encoding="utf-8-sig")
    proxy_map.to_csv(OUT_DIR / "proxy_map.csv", index=False, encoding="utf-8-sig")
    sources.to_csv(OUT_DIR / "sources.csv", index=False, encoding="utf-8-sig")

    audit = {
        "status": "research_only_independent_sleeve_vol_first_pass",
        "created_at_shanghai": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "long_sample": [
            long_returns.index.min().date().isoformat(),
            long_returns.index.max().date().isoformat(),
        ],
        "formal_overlap": [
            formal_returns.index.min().date().isoformat(),
            formal_returns.index.max().date().isoformat(),
        ],
        "excluded_unconfirmed_date": excluded_date,
        "portfolio": AFTER_WEIGHTS,
        "sleeve_signals": SLEEVE_SIGNALS,
        "data_source": "Yahoo adjusted close via mnt_bot V 7.9 plus.py",
        "calendar": "SPY US sessions; BTC weekend return accumulates to next US session",
        "parameters": {
            "target_vol": v77.PROD_VS_TARGET_VOL,
            "window": v77.PROD_VS_VOL_WINDOW,
            "min_scale": v77.PROD_VS_MIN_LEV,
            "max_scale": v77.PROD_VS_MAX_LEV,
            "threshold": v77.PROD_VS_THRESHOLD,
            "financing_spread_bps": v77.PROD_VS_SPREAD_BPS,
            "scale_cost_bps": v77.PROD_VS_REBAL_COST_BPS,
            "asset_rebalance_cost_rate": base.ASSET_REBAL_COST,
            "aggregate_gross_cap": None,
        },
        "component_parity": {
            "long": long_component_parity,
            "formal": formal_component_parity,
        },
        "prior_current_baseline_max_abs_difference": {
            "daily_return": daily_baseline_parity,
            "cagr": float(baseline_parity["cagr_difference"].abs().max()),
            "max_drawdown": float(
                baseline_parity["max_drawdown_difference"].abs().max()
            ),
        },
        "production_code_changed": False,
        "live_orders": False,
    }
    (OUT_DIR / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    record = [
        "# Strategy C Independent Sleeve Volatility Test",
        "",
        "## Classification",
        "",
        "- First-pass research only; no parameter scan and no production change.",
        "- Long sample is diagnostic proxy research; formal overlap starts with live KMLM availability.",
        "- All sleeves use the unchanged V7.7 15-day/15% target-vol parameter set.",
        "- Equities share SPY volatility; treasury, gold, DBMF, KMLM, and bitcoin use their own volatility.",
        "- Each sleeve has a 0.5-1.5x cap; no additional aggregate gross-exposure cap is applied.",
        "- One-at-a-time ablations use SPY-controlled equities as their baseline and add one non-equity self-vol sleeve.",
        "",
        "## Long Proxy — Mandatory Windows",
        "",
        *markdown_metrics(long_metrics),
        "",
        "## Formal Overlap — Mandatory Windows",
        "",
        *markdown_metrics(formal_metrics),
    ]
    (OUT_DIR / "record.md").write_text("\n".join(record) + "\n", encoding="utf-8")

    print("LONG_METRICS")
    print(long_metrics.to_string(index=False))
    print("\nFORMAL_METRICS")
    print(formal_metrics.to_string(index=False))
    print("\nLONG_ABLATION_DELTAS")
    print(long_ablation_deltas.to_string(index=False))
    print("\nFORMAL_ABLATION_DELTAS")
    print(formal_ablation_deltas.to_string(index=False))
    print("\nSTRESS")
    print(stress.to_string(index=False))
    print("\nOVERLAY")
    print(overlay.to_string(index=False))
    print("\nSLEEVE_SCALES")
    print(sleeve_scales.to_string(index=False))
    print("\nBASELINE_PARITY")
    print(baseline_parity.to_string(index=False))
    print("\nOUTPUT", OUT_DIR)


if __name__ == "__main__":
    main()

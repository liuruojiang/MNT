"""Compare Strategy C target-vol signal sources and scaling scopes.

The current V7.7 implementation uses whole-portfolio realized volatility and
applies one scale to the whole Strategy C sleeve.  This research harness adds
equity-only scope and SPY-signal alternatives while preserving the official
threshold, lag, financing spread, and scale-adjustment cost.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import research_subc_bond_necessity_long_proxy as long_base
import research_subc_bond_sleeve_backtest as base


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "outputs" / "subc_target_vol_scope_20260812"
FORMAL_START = pd.Timestamp("2020-12-03")

EQUITY_ASSETS = {
    "VTI",
    "QQQ",
    "US_SMALL_VALUE",
    "DEVELOPED",
    "INTL_SMALL_VALUE",
}

AFTER_WEIGHTS = {
    **long_base.COMMON_AFTER_BTC,
    "TREASURY": 0.15,
}

VARIANTS = {
    "Portfolio vol -> all assets (current)": ("portfolio", "all"),
    "Portfolio vol -> equities only": ("portfolio", "equity"),
    "SPY vol -> all assets": ("spy", "all"),
    "SPY vol -> equities only": ("spy", "equity"),
    "No target-vol scaling": ("none", "none"),
}

LIVE_MAP = {
    "VTI": "VTI",
    "QQQ": "QQQ",
    "US_SMALL_VALUE": "AVUV",
    "DEVELOPED": "VEA",
    "INTL_SMALL_VALUE": "AVDV",
    "MF_1": "DBMF",
    "MF_2": "KMLM",
    "GOLD": "GLD",
    "BTC": "BTC-USD",
    "TREASURY": "VGIT",
    "BIL": "BIL",
    "SPY": "SPY",
}


def build_stitched_prices(
    raw: dict[str, pd.Series], calendar: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame]:
    stitched = {}
    rows = []
    for synthetic, (proxy, live, description) in long_base.PROXY_MAP.items():
        nav, switch = long_base.stitched_nav(calendar, raw, proxy, live)
        stitched[synthetic] = nav.rename(synthetic)
        rows.append(
            {
                "synthetic": synthetic,
                "proxy": proxy,
                "live": live,
                "description": description,
                "proxy_start": raw[proxy].index.min().date().isoformat(),
                "live_return_switch": (
                    switch.date().isoformat() if switch is not None else None
                ),
                "classification": (
                    "proxy research before live switch"
                    if live is not None
                    else "actual/designated proxy"
                ),
            }
        )
    return pd.concat(stitched.values(), axis=1).sort_index(), pd.DataFrame(rows)


def build_formal_prices(
    raw: dict[str, pd.Series], calendar: pd.DatetimeIndex
) -> pd.DataFrame:
    prices = pd.concat(
        {
            synthetic: raw[ticker].reindex(calendar)
            for synthetic, ticker in LIVE_MAP.items()
        },
        axis=1,
    )
    required = sorted(set(AFTER_WEIGHTS) | {"BIL", "SPY"})
    prices = prices.loc[:, required].dropna(how="any")
    return prices.loc[prices.index >= FORMAL_START - pd.offsets.BDay(2)]


def simulate_components(
    prices: pd.DataFrame,
    after_weights: dict[str, float],
    before_weights: dict[str, float] | None = None,
    btc_start: pd.Timestamp | None = None,
    cost_rate: float = base.ASSET_REBAL_COST,
) -> pd.DataFrame:
    """Annual-rebalanced portfolio split into equity/non-equity contributions."""
    before = dict(before_weights or after_weights)
    required = sorted(set(after_weights) | set(before) | {"BIL"})
    asset_ret = prices[required].pct_change(fill_method=None)
    start_required = sorted(set(before) | {"BIL"})
    start_candidates = [
        asset_ret[ticker].first_valid_index() for ticker in start_required
    ]
    start = max(date for date in start_candidates if date is not None)
    asset_ret = asset_ret.loc[start:]

    initial = after_weights if btc_start is None or start >= btc_start else before
    holdings = pd.Series(initial, dtype=float)
    prev_value = float(holdings.sum())
    prev_year = asset_ret.index[0].year
    in_after_phase = btc_start is None or asset_ret.index[0] >= btc_start
    rows = []

    for date, row in asset_ret.iterrows():
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
        eq_names = [name for name in holdings.index if name in EQUITY_ASSETS]
        non_eq_names = [name for name in holdings.index if name not in EQUITY_ASSETS]
        eq_pnl = float(
            (holdings.reindex(eq_names) * row.reindex(eq_names).fillna(0.0)).sum()
        )
        non_eq_pnl = float(
            (
                holdings.reindex(non_eq_names)
                * row.reindex(non_eq_names).fillna(0.0)
            ).sum()
        )
        cost_return = (pre_return_value - prev_value) / prev_value
        eq_contribution = eq_pnl / prev_value
        non_eq_contribution = non_eq_pnl / prev_value
        base_return = cost_return + eq_contribution + non_eq_contribution
        eq_exposure = float(holdings.reindex(eq_names).sum() / prev_value)
        non_eq_exposure = float(holdings.reindex(non_eq_names).sum() / prev_value)

        holdings = holdings * (1.0 + row.reindex(holdings.index).fillna(0.0))
        value = float(holdings.sum())
        direct_return = value / prev_value - 1.0
        if not math.isclose(base_return, direct_return, abs_tol=2e-14):
            raise RuntimeError(f"Component reconciliation failed on {date}")
        rows.append(
            {
                "date": date,
                "base_return": base_return,
                "equity_contribution": eq_contribution,
                "non_equity_contribution": non_eq_contribution,
                "asset_cost_return": cost_return,
                "equity_exposure": eq_exposure,
                "non_equity_exposure": non_eq_exposure,
                "asset_turnover": turnover,
                "asset_cost_fraction": asset_cost / prev_value,
            }
        )
        prev_value = value
    return pd.DataFrame(rows).set_index("date")


def thresholded_scale(signal_returns: pd.Series, v77) -> pd.Series:
    realized = signal_returns.rolling(v77.PROD_VS_VOL_WINDOW).std() * np.sqrt(
        v77.US_TRADING_DAYS
    )
    target = (
        (v77.PROD_VS_TARGET_VOL / realized)
        .clip(v77.PROD_VS_MIN_LEV, v77.PROD_VS_MAX_LEV)
        .shift(1)
        .fillna(1.0)
    )
    actual = pd.Series(1.0, index=signal_returns.index)
    current = 1.0
    for date, value in target.items():
        if pd.notna(value) and abs(float(value) - current) >= v77.PROD_VS_THRESHOLD - 1e-9:
            current = float(value)
        actual.loc[date] = current
    return actual


def apply_overlay(
    components: pd.DataFrame,
    prices: pd.DataFrame,
    signal_source: str,
    scope: str,
    v77,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    index = components.index
    base_return = components["base_return"]
    rf = prices["BIL"].pct_change(fill_method=None).reindex(index).fillna(0.0)
    if signal_source == "none":
        scale = pd.Series(1.0, index=index)
    else:
        if signal_source == "portfolio":
            signal_return = base_return
        elif signal_source == "spy":
            signal_return = (
                prices["SPY"].pct_change(fill_method=None).reindex(index).fillna(0.0)
            )
        else:
            raise ValueError(signal_source)
        scale = thresholded_scale(signal_return, v77)

    scale_change = scale.diff().abs().fillna(0.0)
    daily_spread = v77.PROD_VS_SPREAD_BPS / 10000 / v77.US_TRADING_DAYS
    if scope == "none":
        output = base_return.copy()
        scale_cost = pd.Series(0.0, index=index)
        gross_exposure = (
            components["equity_exposure"] + components["non_equity_exposure"]
        )
    elif scope == "all":
        output = pd.Series(index=index, dtype=float)
        below = scale <= 1.0
        output.loc[below] = (
            scale.loc[below] * base_return.loc[below]
            + (1.0 - scale.loc[below]) * rf.loc[below]
        )
        above = ~below
        output.loc[above] = (
            scale.loc[above] * base_return.loc[above]
            - (scale.loc[above] - 1.0) * (rf.loc[above] + daily_spread)
        )
        scale_cost = scale_change * v77.PROD_VS_REBAL_COST_BPS / 10000
        output = output - scale_cost
        gross_exposure = scale * (
            components["equity_exposure"] + components["non_equity_exposure"]
        )
    elif scope == "equity":
        equity_exposure = components["equity_exposure"]
        delta_exposure = (scale - 1.0) * equity_exposure
        output = (
            components["asset_cost_return"]
            + components["non_equity_contribution"]
            + scale * components["equity_contribution"]
        )
        reduced = delta_exposure <= 0.0
        output.loc[reduced] += (-delta_exposure.loc[reduced]) * rf.loc[reduced]
        levered = ~reduced
        output.loc[levered] -= delta_exposure.loc[levered] * (
            rf.loc[levered] + daily_spread
        )
        scale_cost = (
            equity_exposure
            * scale_change
            * v77.PROD_VS_REBAL_COST_BPS
            / 10000
        )
        output = output - scale_cost
        gross_exposure = components["non_equity_exposure"] + scale * equity_exposure
    else:
        raise ValueError(scope)
    return output, scale, scale_cost, gross_exposure


def run_variants(
    components: pd.DataFrame, prices: pd.DataFrame, v77
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    returns = {}
    scales = {}
    costs = {}
    gross = {}
    for name, (signal, scope) in VARIANTS.items():
        result, scale, scale_cost, gross_exposure = apply_overlay(
            components, prices, signal, scope, v77
        )
        returns[name] = result
        scales[name] = scale
        costs[name] = scale_cost
        gross[name] = gross_exposure
    common = pd.DataFrame(returns).dropna(how="any")
    return (
        common,
        pd.DataFrame(scales).reindex(common.index),
        pd.DataFrame(costs).reindex(common.index),
        pd.DataFrame(gross).reindex(common.index),
    )


def stress_metrics(frame: pd.DataFrame, sample: str) -> pd.DataFrame:
    windows = {
        "GFC": ("2007-10-09", "2009-03-09"),
        "COVID": ("2020-02-19", "2020-03-23"),
        "2022": ("2022-01-01", "2022-12-31"),
    }
    rows = []
    for period, (start, end) in windows.items():
        for name in frame:
            selected = frame[name].loc[start:end]
            if selected.empty:
                continue
            nav = base.nav_from_returns(selected)
            rows.append(
                {
                    "sample": sample,
                    "period": period,
                    "series": name,
                    "return": (1.0 + selected).prod() - 1.0,
                    "max_drawdown": (nav / nav.cummax() - 1.0).min(),
                }
            )
    return pd.DataFrame(rows)


def overlay_audit(
    scales: pd.DataFrame, costs: pd.DataFrame, gross: pd.DataFrame, sample: str
) -> pd.DataFrame:
    rows = []
    for name in scales:
        scale = scales[name]
        rows.append(
            {
                "sample": sample,
                "series": name,
                "average_scale": scale.mean(),
                "median_scale": scale.median(),
                "pct_days_at_min_0_5": (scale <= 0.5000001).mean(),
                "pct_days_at_max_1_5": (scale >= 1.4999999).mean(),
                "scale_adjustment_days": int((scale.diff().abs() > 1e-12).sum()),
                "total_scale_cost_fraction": costs[name].sum(),
                "average_gross_exposure": gross[name].mean(),
                "maximum_gross_exposure": gross[name].max(),
            }
        )
    return pd.DataFrame(rows)


def plot_results(frame: pd.DataFrame, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    nav = frame.apply(base.nav_from_returns)
    nav = nav.div(nav.iloc[0])
    drawdown = nav.div(nav.cummax()).sub(1.0)
    fig, axes = plt.subplots(2, 1, figsize=(14.0, 9.2), sharex=True)
    fig.subplots_adjust(left=0.08, right=0.985, top=0.90, bottom=0.09, hspace=0.10)
    for name in nav:
        axes[0].plot(nav.index, nav[name], linewidth=1.8, label=name)
        axes[1].plot(drawdown.index, drawdown[name] * 100, linewidth=1.35, label=name)
    axes[0].set_title("策略 C 长周期代理净值", fontsize=14, fontweight="bold")
    axes[0].set_ylabel("归一化净值")
    axes[0].grid(True, alpha=0.24)
    axes[0].legend(frameon=False, fontsize=8.5, ncol=2)
    axes[1].axhline(0, color="#6B7280", linewidth=0.8)
    axes[1].set_ylabel("回撤（%）")
    axes[1].set_xlabel("日期")
    axes[1].grid(True, alpha=0.24)
    axes[1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle("目标波动率：信号来源 × 缩放范围", fontsize=17, fontweight="bold", y=0.975)
    fig.text(
        0.01,
        0.018,
        "同一策略C资产池；15日/15%目标波动率、0.5-1.5x、0.10调仓阈值、融资100bps、缩放成本6bps；年度资产再平衡10bps。",
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
    for name in VARIANTS:
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
    v77 = base.load_module(base.V77_PATH, "v77_target_vol_scope")
    v79 = base.load_module(base.V79_PATH, "v79_target_vol_scope_loader")
    raw, sources, excluded_date = long_base.fetch_raw(v79)
    calendar = raw["SPY"].index

    long_prices, proxy_map = build_stitched_prices(raw, calendar)
    before_weights = long_base.pre_btc_weights(AFTER_WEIGHTS, "renormalize")
    btc_start = long_prices["BTC"].first_valid_index()
    long_components = simulate_components(
        long_prices, AFTER_WEIGHTS, before_weights, btc_start
    )
    long_returns, long_scales, long_costs, long_gross = run_variants(
        long_components, long_prices, v77
    )

    formal_prices = build_formal_prices(raw, calendar)
    formal_components = simulate_components(formal_prices, AFTER_WEIGHTS)
    formal_returns, formal_scales, formal_costs, formal_gross = run_variants(
        formal_components, formal_prices, v77
    )
    formal_returns = formal_returns.loc[formal_returns.index >= FORMAL_START]
    formal_scales = formal_scales.reindex(formal_returns.index)
    formal_costs = formal_costs.reindex(formal_returns.index)
    formal_gross = formal_gross.reindex(formal_returns.index)

    long_metrics = base.window_metrics(long_returns)
    formal_metrics = base.window_metrics(formal_returns)
    baseline = "Portfolio vol -> all assets (current)"
    long_deltas = pd.concat(
        [
            base.delta_metrics(long_metrics, baseline, candidate)
            for candidate in list(VARIANTS)[1:]
        ],
        ignore_index=True,
    )
    formal_deltas = pd.concat(
        [
            base.delta_metrics(formal_metrics, baseline, candidate)
            for candidate in list(VARIANTS)[1:]
        ],
        ignore_index=True,
    )
    saved_formal = pd.read_csv(
        ROOT / "outputs" / "subc_bond_sleeve_20260811" / "full_strategy_metrics.csv"
    )
    saved_formal = saved_formal[
        saved_formal["series"] == "New C + VGIT 15%"
    ].set_index("window")
    measured_formal = formal_metrics[
        formal_metrics["series"] == baseline
    ].set_index("window")
    saved_parity_rows = []
    for window in ("Full", "5Y", "3Y", "1Y"):
        saved_parity_rows.append(
            {
                "window": window,
                "cagr_difference": (
                    measured_formal.loc[window, "cagr"]
                    - saved_formal.loc[window, "cagr"]
                ),
                "max_drawdown_difference": (
                    measured_formal.loc[window, "max_drawdown"]
                    - saved_formal.loc[window, "max_drawdown"]
                ),
            }
        )
    saved_formal_parity = pd.DataFrame(saved_parity_rows)
    stress = pd.concat(
        [
            stress_metrics(long_returns, "long_proxy"),
            stress_metrics(formal_returns, "formal_overlap"),
        ],
        ignore_index=True,
    )
    overlay = pd.concat(
        [
            overlay_audit(long_scales, long_costs, long_gross, "long_proxy"),
            overlay_audit(
                formal_scales, formal_costs, formal_gross, "formal_overlap"
            ),
        ],
        ignore_index=True,
    )

    official_ret, official_scale, official_cost = v77._apply_subc_vol_scaling(
        long_components["base_return"], long_prices
    )
    parity = {
        "max_return_difference": float(
            (long_returns[baseline] - official_ret.reindex(long_returns.index)).abs().max()
        ),
        "max_scale_difference": float(
            (long_scales[baseline] - official_scale.reindex(long_returns.index)).abs().max()
        ),
        "max_scale_cost_difference": float(
            (long_costs[baseline] - official_cost.reindex(long_returns.index)).abs().max()
        ),
    }
    component_start_loc = long_prices.index.get_loc(long_components.index.min())
    reference_anchor = long_prices.index[max(0, component_start_loc - 1)]
    raw_reference, _, _ = long_base.phased_annual_returns(
        long_prices.loc[reference_anchor:],
        AFTER_WEIGHTS,
        before_weights,
        btc_start,
    )
    component_parity = float(
        (
            long_components["base_return"]
            - raw_reference.reindex(long_components.index)
        ).abs().max()
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_results(long_returns, OUT_DIR / "subc_target_vol_scope.png")
    daily = pd.concat(
        {
            "return": long_returns,
            "nav": long_returns.apply(base.nav_from_returns),
            "scale": long_scales,
            "scale_cost": long_costs,
            "gross_exposure": long_gross,
            "component": long_components,
        },
        axis=1,
    )
    daily.to_csv(OUT_DIR / "daily_nav_and_audit.csv", encoding="utf-8-sig")
    long_metrics.to_csv(OUT_DIR / "long_proxy_metrics.csv", index=False, encoding="utf-8-sig")
    formal_metrics.to_csv(OUT_DIR / "formal_overlap_metrics.csv", index=False, encoding="utf-8-sig")
    long_deltas.to_csv(OUT_DIR / "long_proxy_deltas.csv", index=False, encoding="utf-8-sig")
    formal_deltas.to_csv(OUT_DIR / "formal_overlap_deltas.csv", index=False, encoding="utf-8-sig")
    stress.to_csv(OUT_DIR / "stress_periods.csv", index=False, encoding="utf-8-sig")
    overlay.to_csv(OUT_DIR / "overlay_audit.csv", index=False, encoding="utf-8-sig")
    saved_formal_parity.to_csv(
        OUT_DIR / "saved_formal_baseline_parity.csv", index=False, encoding="utf-8-sig"
    )
    proxy_map.to_csv(OUT_DIR / "proxy_map.csv", index=False, encoding="utf-8-sig")
    sources.to_csv(OUT_DIR / "sources.csv", index=False, encoding="utf-8-sig")

    audit = {
        "status": "diagnostic_scope_comparison_plus_formal_overlap",
        "created_at_shanghai": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "long_sample_start": long_returns.index.min().date().isoformat(),
        "formal_overlap_start": formal_returns.index.min().date().isoformat(),
        "sample_end": long_returns.index.max().date().isoformat(),
        "excluded_unconfirmed_date": excluded_date,
        "portfolio": AFTER_WEIGHTS,
        "equity_assets": sorted(EQUITY_ASSETS),
        "data_source": "Yahoo adjusted close via mnt_bot V 7.9 plus.py",
        "calendar": "SPY US sessions; BTC weekend return accumulates to next US session",
        "current_implementation": "portfolio return volatility signal; all-assets scope",
        "parameters": {
            "target_vol": v77.PROD_VS_TARGET_VOL,
            "window": v77.PROD_VS_VOL_WINDOW,
            "min_scale": v77.PROD_VS_MIN_LEV,
            "max_scale": v77.PROD_VS_MAX_LEV,
            "threshold": v77.PROD_VS_THRESHOLD,
            "financing_spread_bps": v77.PROD_VS_SPREAD_BPS,
            "scale_cost_bps": v77.PROD_VS_REBAL_COST_BPS,
            "asset_rebalance_cost_rate": base.ASSET_REBAL_COST,
        },
        "official_overlay_parity": parity,
        "component_raw_return_parity": component_parity,
        "saved_formal_baseline_max_abs_difference": {
            "cagr": float(saved_formal_parity["cagr_difference"].abs().max()),
            "max_drawdown": float(
                saved_formal_parity["max_drawdown_difference"].abs().max()
            ),
        },
        "production_code_changed": False,
        "live_orders": False,
    }
    (OUT_DIR / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    record = [
        "# Strategy C Target-Vol Signal and Scope Comparison",
        "",
        "## Classification",
        "",
        "- Long sample is diagnostic proxy research.",
        "- Formal overlap starts with live KMLM return availability.",
        "- Formal 10Y is N/A because live overlap begins in December 2020.",
        "- Current V7.7 behavior is portfolio-vol signal applied to all assets.",
        "",
        "## Long Proxy — Mandatory Windows",
        "",
        *markdown_metrics(long_metrics),
        "",
        "## Formal Overlap — Mandatory Windows",
        "",
        *markdown_metrics(formal_metrics),
        "",
        "## Deferred Follow-up (Not Run)",
        "",
        "- Test independent volatility control by sleeve instead of one shared portfolio scale.",
        "- SPY realized volatility controls the equity sleeve only.",
        "- Gold, bonds, managed futures, and bitcoin are each controlled by their own realized volatility.",
        "- Pre-declare each sleeve's volatility target, floor/cap, financing treatment, and any final portfolio gross-exposure cap before testing.",
        "- Status: deferred at the user's request on 2026-08-12; no parameter scan and no production change.",
    ]
    (OUT_DIR / "record.md").write_text("\n".join(record) + "\n", encoding="utf-8")

    print("LONG_METRICS")
    print(long_metrics.to_string(index=False))
    print("\nFORMAL_METRICS")
    print(formal_metrics.to_string(index=False))
    print("\nSTRESS")
    print(stress.to_string(index=False))
    print("\nOVERLAY")
    print(overlay.to_string(index=False))
    print("\nPARITY", parity)
    print("COMPONENT_PARITY", component_parity)
    print("\nOUTPUT", OUT_DIR)


if __name__ == "__main__":
    main()

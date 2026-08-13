"""Two-stage Strategy C volatility research.

Stage 1 scans the absolute target volatility used by SPY to control equities.
Stage 2 carries an explicit equity target and scans non-equity short/long
relative-volatility overlays.  This is a research harness; production files are
never mutated.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import research_subc_bond_sleeve_backtest as base
import research_subc_independent_vol_backtest as independent
import research_subc_target_vol_scope_backtest as scope_base


ROOT = Path(__file__).resolve().parent
EQUITY_RUN = ROOT / "quant_param_scan_runs" / "20260812_subc_equity_target_vol"
RELATIVE_RUN = (
    ROOT / "quant_param_scan_runs" / "20260812_subc_non_equity_relative_vol"
)
FORMAL_START = scope_base.FORMAL_START
AFTER_WEIGHTS = scope_base.AFTER_WEIGHTS
EQUITY_TARGETS = [0.08, 0.10, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18, 0.20, 0.22, 0.25]
SHORT_WINDOWS = [10, 15, 20, 30]
LONG_WINDOWS = [63, 126, 252]
NON_EQUITY_SCOPES = {
    "treasury": ["Treasury"],
    "dbmf": ["Managed futures DBMF"],
    "kmlm": ["Managed futures KMLM"],
    "gold": ["Gold"],
    "bitcoin": ["Bitcoin"],
    "all_non_equity": [
        "Treasury",
        "Managed futures DBMF",
        "Managed futures KMLM",
        "Gold",
        "Bitcoin",
    ],
}
WINDOW_TO_SEGMENT = {
    "Full": "full",
    "10Y": "last_10y",
    "5Y": "last_5y",
    "3Y": "last_3y",
    "1Y": "last_1y",
}


def git_status() -> str:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def threshold_actual(raw_target: pd.Series, threshold: float) -> pd.Series:
    target = raw_target.shift(1).fillna(1.0)
    actual = pd.Series(1.0, index=target.index)
    current = 1.0
    for date, value in target.items():
        if pd.notna(value) and abs(float(value) - current) >= threshold - 1e-9:
            current = float(value)
        actual.loc[date] = current
    return actual


def absolute_scale(signal_return: pd.Series, target_vol: float, v77) -> pd.Series:
    realized = signal_return.rolling(v77.PROD_VS_VOL_WINDOW).std() * np.sqrt(
        v77.US_TRADING_DAYS
    )
    raw = (target_vol / realized).clip(v77.PROD_VS_MIN_LEV, v77.PROD_VS_MAX_LEV)
    return threshold_actual(raw, v77.PROD_VS_THRESHOLD)


def relative_scale(
    signal_return: pd.Series, short_window: int, long_window: int, v77
) -> pd.Series:
    short_vol = signal_return.rolling(short_window).std()
    long_vol = signal_return.rolling(long_window).std()
    raw = (long_vol / short_vol).clip(v77.PROD_VS_MIN_LEV, v77.PROD_VS_MAX_LEV)
    return threshold_actual(raw, v77.PROD_VS_THRESHOLD)


def apply_sleeve_scales(
    components: pd.DataFrame,
    prices: pd.DataFrame,
    sleeve_scales: dict[str, pd.Series],
    v77,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    index = components.index
    rf = prices["BIL"].pct_change(fill_method=None).reindex(index).fillna(0.0)
    daily_spread = v77.PROD_VS_SPREAD_BPS / 10000 / v77.US_TRADING_DAYS
    output = components["asset_cost_return"].copy()
    total_cost = pd.Series(0.0, index=index)
    gross = pd.Series(0.0, index=index)
    covered: set[str] = set()

    for sleeve, scale in sleeve_scales.items():
        assets = independent.SLEEVE_SIGNALS[sleeve][0]
        covered.update(assets)
        scale = scale.reindex(index).fillna(1.0)
        exposure = sum(
            (components[f"exposure::{asset}"] for asset in assets),
            start=pd.Series(0.0, index=index),
        )
        contribution = sum(
            (components[f"contribution::{asset}"] for asset in assets),
            start=pd.Series(0.0, index=index),
        )
        output += scale * contribution
        delta = (scale - 1.0) * exposure
        reduced = delta <= 0.0
        output.loc[reduced] += (-delta.loc[reduced]) * rf.loc[reduced]
        output.loc[~reduced] -= delta.loc[~reduced] * (
            rf.loc[~reduced] + daily_spread
        )
        cost = (
            exposure
            * scale.diff().abs().fillna(0.0)
            * v77.PROD_VS_REBAL_COST_BPS
            / 10000
        )
        output -= cost
        total_cost += cost
        gross += scale * exposure

    all_assets = {
        name.split("::", 1)[1]
        for name in components
        if name.startswith("exposure::")
    }
    for asset in sorted(all_assets - covered):
        output += components[f"contribution::{asset}"]
        gross += components[f"exposure::{asset}"]
    return output, total_cost, gross


def prepare_data(v79):
    raw, sources, excluded_date = scope_base.long_base.fetch_raw(v79)
    calendar = raw["SPY"].index
    long_prices, proxy_map = scope_base.build_stitched_prices(raw, calendar)
    before_weights = scope_base.long_base.pre_btc_weights(AFTER_WEIGHTS, "renormalize")
    btc_start = long_prices["BTC"].first_valid_index()
    long_components = independent.simulate_asset_components(
        long_prices, AFTER_WEIGHTS, before_weights, btc_start
    )
    formal_prices = scope_base.build_formal_prices(raw, calendar)
    formal_components = independent.simulate_asset_components(
        formal_prices, AFTER_WEIGHTS
    )
    return {
        "long_prices": long_prices,
        "long_components": long_components,
        "formal_prices": formal_prices,
        "formal_components": formal_components,
        "sources": sources,
        "proxy_map": proxy_map,
        "excluded_date": excluded_date,
    }


def equity_candidates(prices, components, v77):
    spy_return = prices["SPY"].pct_change(fill_method=None).reindex(components.index)
    returns, costs, gross, params, scales = {}, {}, {}, {}, {}
    for target in EQUITY_TARGETS:
        name = f"equity_target_{target:.0%}"
        scale = absolute_scale(spy_return, target, v77)
        result, cost, exposure = apply_sleeve_scales(
            components, prices, {"Equities (SPY)": scale}, v77
        )
        returns[name], costs[name], gross[name], scales[name] = (
            result,
            cost,
            exposure,
            scale,
        )
        params[name] = {"target_vol": target, "scope": "equity"}
    frame = pd.DataFrame(returns).dropna(how="any")
    return (
        frame,
        pd.DataFrame(costs).reindex(frame.index),
        pd.DataFrame(gross).reindex(frame.index),
        pd.DataFrame(scales).reindex(frame.index),
        params,
    )


def relative_candidates(prices, components, v77, equity_target: float):
    index = components.index
    asset_return = {
        sleeve: prices[signal].pct_change(fill_method=None).reindex(index)
        for sleeve, (_, signal) in independent.SLEEVE_SIGNALS.items()
    }
    equity_scale = absolute_scale(asset_return["Equities (SPY)"], equity_target, v77)
    returns, costs, gross, params = {}, {}, {}, {}
    baseline = "baseline_no_relative_vol"
    result, cost, exposure = apply_sleeve_scales(
        components, prices, {"Equities (SPY)": equity_scale}, v77
    )
    returns[baseline], costs[baseline], gross[baseline] = result, cost, exposure
    params[baseline] = {
        "equity_target_vol": equity_target,
        "scope": "none",
        "short_window": 0,
        "long_window": 0,
    }

    for short in SHORT_WINDOWS:
        for long in LONG_WINDOWS:
            if long < 3 * short:
                continue
            relative_scales = {
                sleeve: relative_scale(asset_return[sleeve], short, long, v77)
                for sleeve in independent.SLEEVE_SIGNALS
                if sleeve != "Equities (SPY)"
            }
            for scope, active in NON_EQUITY_SCOPES.items():
                name = f"{scope}_s{short}_l{long}"
                scales = {"Equities (SPY)": equity_scale}
                scales.update({sleeve: relative_scales[sleeve] for sleeve in active})
                result, cost, exposure = apply_sleeve_scales(
                    components, prices, scales, v77
                )
                returns[name], costs[name], gross[name] = result, cost, exposure
                params[name] = {
                    "equity_target_vol": equity_target,
                    "scope": scope,
                    "short_window": short,
                    "long_window": long,
                }
    frame = pd.DataFrame(returns).dropna(how="any")
    return (
        frame,
        pd.DataFrame(costs).reindex(frame.index),
        pd.DataFrame(gross).reindex(frame.index),
        params,
    )


def post_selection_bundles(prices, components, v77, equity_target: float):
    """Clearly labeled diagnostics selected after the primary grid was observed."""
    index = components.index
    signals = {
        sleeve: prices[signal].pct_change(fill_method=None).reindex(index)
        for sleeve, (_, signal) in independent.SLEEVE_SIGNALS.items()
    }
    equity = absolute_scale(signals["Equities (SPY)"], equity_target, v77)
    definitions = {
        "baseline": {},
        "btc_10_63": {"Bitcoin": (10, 63)},
        "gold_30_252": {"Gold": (30, 252)},
        "gold30_252_btc10_63": {"Gold": (30, 252), "Bitcoin": (10, 63)},
        "gold30_252_btc10_126": {"Gold": (30, 252), "Bitcoin": (10, 126)},
        "gold30_126_btc10_63": {"Gold": (30, 126), "Bitcoin": (10, 63)},
    }
    returns = {}
    scale_audit = []
    for name, rules in definitions.items():
        scales = {"Equities (SPY)": equity}
        for sleeve, (short, long) in rules.items():
            scale = relative_scale(signals[sleeve], short, long, v77)
            scales[sleeve] = scale
            scale_audit.append(
                {
                    "bundle": name,
                    "sleeve": sleeve,
                    "short_window": short,
                    "long_window": long,
                    "average_scale": scale.mean(),
                    "median_scale": scale.median(),
                    "pct_at_min_0_5": (scale <= 0.5000001).mean(),
                    "pct_at_max_1_5": (scale >= 1.4999999).mean(),
                    "adjustment_days": int((scale.diff().abs() > 1e-12).sum()),
                }
            )
        returns[name] = apply_sleeve_scales(components, prices, scales, v77)[0]
    return pd.DataFrame(returns).dropna(how="any"), pd.DataFrame(scale_audit)


def build_outputs(returns, costs, gross, params):
    metrics = base.window_metrics(returns)
    metric_rows = []
    for _, row in metrics.iterrows():
        p = params[row["series"]]
        metric_rows.append(
            {
                "candidate": row["series"],
                "segment": WINDOW_TO_SEGMENT[row["window"]],
                "start": row["start"],
                "end": row["end"],
                "rows": row["rows"],
                "ann_return": row["cagr"],
                "ann_vol": row["annual_vol"],
                "sharpe_repo": row["sharpe_0rf"],
                "max_dd": row["max_drawdown"],
                "avg_gross": gross[row["series"]].loc[row["start"] : row["end"]].mean()
                if row["start"] is not None
                else np.nan,
                "cost_total": costs[row["series"]].loc[row["start"] : row["end"]].sum()
                if row["start"] is not None
                else np.nan,
                **p,
            }
        )
    summary = pd.DataFrame(metric_rows)
    wide_rows = []
    for candidate, group in summary.groupby("candidate", sort=False):
        p = params[candidate]
        output = {"candidate": candidate, **p}
        for _, row in group.iterrows():
            suffix = row["segment"]
            output[f"ann_return_{suffix}"] = row["ann_return"]
            output[f"max_dd_{suffix}"] = row["max_dd"]
            output[f"sharpe_repo_{suffix}"] = row["sharpe_repo"]
            output[f"avg_gross_{suffix}"] = row["avg_gross"]
        wide_rows.append(output)
    return summary, pd.DataFrame(wide_rows), metrics


def save_chart_equity(wide: pd.DataFrame, path: Path) -> None:
    frame = wide.sort_values("target_vol")
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 8.0), sharex=True)
    sharpe_axis = axes[0].twinx()
    cagr_line = axes[0].plot(
        frame["target_vol"] * 100,
        frame["ann_return_full"] * 100,
        marker="o",
        label="CAGR",
    )
    sharpe_line = sharpe_axis.plot(
        frame["target_vol"] * 100,
        frame["sharpe_repo_full"],
        marker="s",
        color="#F97316",
        label="Sharpe",
    )
    axes[0].axvline(15, color="#6B7280", linestyle="--", linewidth=1)
    axes[0].set_ylabel("CAGR (%)")
    sharpe_axis.set_ylabel("Sharpe")
    axes[0].legend(cagr_line + sharpe_line, ["CAGR", "Sharpe"], frameon=False)
    axes[0].grid(alpha=0.25)
    axes[1].plot(frame["target_vol"] * 100, frame["max_dd_full"] * 100, marker="o", color="#DC2626")
    axes[1].axvline(15, color="#6B7280", linestyle="--", linewidth=1)
    axes[1].set_xlabel("Equity target volatility (%)")
    axes[1].set_ylabel("Max drawdown (%)")
    axes[1].grid(alpha=0.25)
    fig.suptitle("Strategy C SPY-controlled equity target-vol scan")
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def save_chart_relative(wide: pd.DataFrame, path: Path) -> None:
    baseline = wide[wide["candidate"] == "baseline_no_relative_vol"].iloc[0]
    frame = wide[wide["scope"] != "none"].copy()
    scopes = list(NON_EQUITY_SCOPES)
    fig, axes = plt.subplots(2, 1, figsize=(12.0, 9.0), sharex=True)
    for scope in scopes:
        group = frame[frame["scope"] == scope].sort_values(["long_window", "short_window"])
        x = np.arange(len(group))
        labels = [f"{int(s)}/{int(l)}" for s, l in zip(group.short_window, group.long_window)]
        axes[0].plot(x, (group.ann_return_full - baseline.ann_return_full) * 100, marker="o", label=scope)
        axes[1].plot(x, (group.max_dd_full - baseline.max_dd_full) * 100, marker="o", label=scope)
    axes[0].axhline(0, color="#6B7280", linewidth=0.8)
    axes[1].axhline(0, color="#6B7280", linewidth=0.8)
    axes[0].set_ylabel("Full CAGR delta (pp)")
    axes[1].set_ylabel("Full DD improvement (pp)")
    axes[1].set_xticks(x, labels, rotation=45)
    axes[1].set_xlabel("Short/long windows")
    axes[0].legend(frameon=False, ncol=3, fontsize=8)
    for axis in axes:
        axis.grid(alpha=0.22)
    fig.suptitle("Non-equity relative-vol scan vs carried equity baseline")
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def update_meta(run_dir: Path, **updates) -> None:
    path = run_dir / "scan_meta.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta.update(updates)
    meta["repo_root"] = str(ROOT)
    meta["git_status_after"] = git_status()
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def append_log(run_dir: Path, command: str, elapsed: float) -> None:
    with (run_dir / "command_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"\nworking_directory={ROOT}\ncommand={command}\nelapsed_sec={elapsed:.3f}\n")


def save_common_artifacts(run_dir, data, long_pack, formal_pack, command, elapsed):
    long_returns, long_costs, long_gross, params = long_pack
    formal_returns, formal_costs, formal_gross, _ = formal_pack
    long_summary, long_wide, _ = build_outputs(long_returns, long_costs, long_gross, params)
    formal_summary, formal_wide, _ = build_outputs(
        formal_returns.loc[formal_returns.index >= FORMAL_START],
        formal_costs.loc[formal_costs.index >= FORMAL_START],
        formal_gross.loc[formal_gross.index >= FORMAL_START],
        params,
    )
    long_summary.to_csv(run_dir / "scan_summary.csv", index=False, encoding="utf-8-sig")
    long_wide.to_csv(run_dir / "window_metrics.csv", index=False, encoding="utf-8-sig")
    formal_summary.to_csv(run_dir / "formal_scan_summary.csv", index=False, encoding="utf-8-sig")
    formal_wide.to_csv(run_dir / "formal_window_metrics.csv", index=False, encoding="utf-8-sig")
    long_returns.to_csv(run_dir / "daily_returns.csv", encoding="utf-8-sig")
    data["sources"].to_csv(run_dir / "sources.csv", index=False, encoding="utf-8-sig")
    data["proxy_map"].to_csv(run_dir / "proxy_map.csv", index=False, encoding="utf-8-sig")
    append_log(run_dir, command, elapsed)
    return long_summary, long_wide, formal_summary, formal_wide


def run_equity(data, v77, command: str, elapsed_start: float) -> None:
    long = equity_candidates(data["long_prices"], data["long_components"], v77)
    formal = equity_candidates(data["formal_prices"], data["formal_components"], v77)
    long_pack = (*long[:3], long[4])
    formal_pack = (*formal[:3], formal[4])
    elapsed = time.perf_counter() - elapsed_start
    summary, wide, formal_summary, formal_wide = save_common_artifacts(
        EQUITY_RUN, data, long_pack, formal_pack, command, elapsed
    )
    long[3].to_csv(EQUITY_RUN / "daily_scales.csv", encoding="utf-8-sig")
    save_chart_equity(wide, EQUITY_RUN / "equity_target_scan.png")

    prior = pd.read_csv(
        ROOT / "outputs" / "subc_independent_vol_20260812" / "long_daily_nav_and_audit.csv",
        header=[0, 1],
        index_col=0,
        parse_dates=True,
    )[("return", "SPY vol -> equities only")].dropna()
    baseline = long[0]["equity_target_15%"]
    common = baseline.index.intersection(prior.index)
    parity = float((baseline.loc[common] - prior.loc[common]).abs().max())
    update_meta(
        EQUITY_RUN,
        scan_type="single_parameter",
        baseline={"candidate": "equity_target_15%", "target_vol": 0.15},
        candidate_grid=EQUITY_TARGETS,
        data_snapshot={
            "long_proxy_start": long[0].index.min().date().isoformat(),
            "formal_start": FORMAL_START.date().isoformat(),
            "end": long[0].index.max().date().isoformat(),
            "source": "Yahoo adjusted close via mnt_bot V7.9 loader",
            "calendar": "SPY US sessions; BTC weekends accumulated to next US session",
            "classification": "long proxy research plus formal live-ETF overlap",
        },
        cost_model={
            "annual_asset_rebalance_two_way": base.ASSET_REBAL_COST,
            "scale_adjustment_bps": v77.PROD_VS_REBAL_COST_BPS,
            "financing_spread_bps": v77.PROD_VS_SPREAD_BPS,
        },
        parity_check={"max_daily_return_difference": parity, "tolerance": 2e-6},
        excluded_unconfirmed_date=data["excluded_date"],
        warnings=["Long sample uses documented stitched proxies before live ETF switches."],
        elapsed_sec=elapsed,
    )
    print("EQUITY_FULL")
    print(
        wide[
            ["candidate", "target_vol", "ann_return_full", "max_dd_full", "sharpe_repo_full"]
        ].to_string(index=False)
    )
    print("\nEQUITY_FORMAL_FULL")
    print(
        formal_wide[
            ["candidate", "target_vol", "ann_return_full", "max_dd_full", "sharpe_repo_full"]
        ].to_string(index=False)
    )
    print("\nPARITY", parity)


def run_relative(data, v77, equity_target: float, command: str, elapsed_start: float) -> None:
    long = relative_candidates(
        data["long_prices"], data["long_components"], v77, equity_target
    )
    formal = relative_candidates(
        data["formal_prices"], data["formal_components"], v77, equity_target
    )
    long_bundles, long_bundle_scales = post_selection_bundles(
        data["long_prices"], data["long_components"], v77, equity_target
    )
    formal_bundles, formal_bundle_scales = post_selection_bundles(
        data["formal_prices"], data["formal_components"], v77, equity_target
    )
    elapsed = time.perf_counter() - elapsed_start
    summary, wide, formal_summary, formal_wide = save_common_artifacts(
        RELATIVE_RUN, data, long, formal, command, elapsed
    )
    save_chart_relative(wide, RELATIVE_RUN / "relative_vol_scan.png")
    base.window_metrics(long_bundles).to_csv(
        RELATIVE_RUN / "post_selection_bundle_long_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    base.window_metrics(formal_bundles.loc[formal_bundles.index >= FORMAL_START]).to_csv(
        RELATIVE_RUN / "post_selection_bundle_formal_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    long_bundles.to_csv(
        RELATIVE_RUN / "post_selection_bundle_daily_returns.csv",
        encoding="utf-8-sig",
    )
    formal_bundles.loc[formal_bundles.index >= FORMAL_START].to_csv(
        RELATIVE_RUN / "post_selection_bundle_formal_daily_returns.csv",
        encoding="utf-8-sig",
    )
    pd.concat(
        {
            "long_proxy": long_bundle_scales,
            "formal_overlap": formal_bundle_scales,
        },
        names=["sample"],
    ).reset_index(level=0).to_csv(
        RELATIVE_RUN / "post_selection_scale_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    baseline_name = "baseline_no_relative_vol"
    baseline = long[0][baseline_name]
    equity_target_name = f"equity_target_{equity_target:.0%}"
    equity_daily = pd.read_csv(
        EQUITY_RUN / "daily_returns.csv", index_col=0, parse_dates=True
    )[equity_target_name].dropna()
    common = baseline.index.intersection(equity_daily.index)
    parity = float((baseline.loc[common] - equity_daily.loc[common]).abs().max())
    candidate_grid = [
        {"short_window": short, "long_window": long}
        for short in SHORT_WINDOWS
        for long in LONG_WINDOWS
        if long >= 3 * short
    ]
    update_meta(
        RELATIVE_RUN,
        scan_type="two_parameter_grid",
        baseline={
            "candidate": baseline_name,
            "equity_target_vol": equity_target,
            "non_equity_relative_vol": False,
        },
        candidate_grid=candidate_grid,
        scopes=list(NON_EQUITY_SCOPES),
        relative_scale_formula="clip(long realized vol / short realized vol, 0.5, 1.5), lag 1, threshold 0.10",
        data_snapshot={
            "long_proxy_start": long[0].index.min().date().isoformat(),
            "formal_start": FORMAL_START.date().isoformat(),
            "end": long[0].index.max().date().isoformat(),
            "source": "Yahoo adjusted close via mnt_bot V7.9 loader",
            "calendar": "SPY US sessions; BTC weekends accumulated to next US session",
            "classification": "long proxy research plus formal live-ETF overlap",
        },
        cost_model={
            "annual_asset_rebalance_two_way": base.ASSET_REBAL_COST,
            "scale_adjustment_bps": v77.PROD_VS_REBAL_COST_BPS,
            "financing_spread_bps": v77.PROD_VS_SPREAD_BPS,
        },
        parity_check={"max_daily_return_difference": parity, "tolerance": 2e-6},
        excluded_unconfirmed_date=data["excluded_date"],
        warnings=[
            "Long sample uses documented stitched proxies before live ETF switches.",
            "DBMF and KMLM share RYMFX proxy returns before their live switches.",
        ],
        elapsed_sec=elapsed,
    )
    baseline_row = wide[wide.candidate == baseline_name].iloc[0]
    ranked = wide[wide.candidate != baseline_name].copy()
    ranked["sharpe_delta"] = ranked.sharpe_repo_full - baseline_row.sharpe_repo_full
    ranked["cagr_delta_pp"] = (ranked.ann_return_full - baseline_row.ann_return_full) * 100
    ranked["dd_improvement_pp"] = (ranked.max_dd_full - baseline_row.max_dd_full) * 100
    print("RELATIVE_BASELINE")
    print(baseline_row[["ann_return_full", "max_dd_full", "sharpe_repo_full"]].to_string())
    print("\nTOP_RELATIVE_BY_FULL_SHARPE")
    print(
        ranked.sort_values("sharpe_repo_full", ascending=False)[
            [
                "candidate",
                "scope",
                "short_window",
                "long_window",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "cagr_delta_pp",
                "dd_improvement_pp",
            ]
        ]
        .head(20)
        .to_string(index=False)
    )
    print("\nPARITY", parity)
    print("\nPOST_SELECTION_LONG")
    print(base.window_metrics(long_bundles).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["equity", "relative"])
    parser.add_argument("--equity-target", type=float, default=0.15)
    args = parser.parse_args()
    start = time.perf_counter()
    v77 = base.load_module(base.V77_PATH, f"v77_relative_scan_{args.phase}")
    v79 = base.load_module(base.V79_PATH, f"v79_relative_scan_{args.phase}")
    data = prepare_data(v79)
    command = f'python "{Path(__file__).name}" {args.phase}'
    if args.phase == "relative":
        command += f" --equity-target {args.equity_target}"
        run_relative(data, v77, args.equity_target, command, start)
    else:
        run_equity(data, v77, command, start)


if __name__ == "__main__":
    main()

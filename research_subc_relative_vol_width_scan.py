"""SPY relative-vol scan and Gold/Bitcoin width audit for Strategy C.

Research-only.  Reuses the reconciled Strategy C component/cost harness and
keeps production V7.7/V7.8/V7.9 files untouched.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import deque
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import research_subc_bond_sleeve_backtest as base
import research_subc_independent_vol_backtest as independent
import research_subc_relative_vol_param_scan as prior
import research_subc_target_vol_scope_backtest as scope_base


ROOT = Path(__file__).resolve().parent
SPY_RUN = ROOT / "quant_param_scan_runs" / "20260812_subc_spy_relative_vol"
WIDTH_RUN = ROOT / "quant_param_scan_runs" / "20260812_subc_gold_btc_width"
FORMAL_START = scope_base.FORMAL_START
AFTER_WEIGHTS = scope_base.AFTER_WEIGHTS

SPY_SHORTS = [5, 7, 10, 15, 20, 30, 40, 60]
SPY_LONGS = [42, 63, 84, 126, 189, 252, 378, 504]
GOLD_SHORTS = [15, 20, 25, 30, 35, 40, 50, 60]
GOLD_LONGS = [126, 189, 252, 315, 378, 504, 756]
BTC_SHORTS = [3, 5, 7, 10, 12, 15, 20, 30]
BTC_LONGS = [21, 42, 63, 84, 126, 189, 252, 378]
LOCAL_GOLD_SHORTS = [20, 30, 40]
LOCAL_GOLD_LONGS = [189, 252, 378]
LOCAL_BTC_SHORTS = [7, 10, 15]
LOCAL_BTC_LONGS = [42, 63, 84]

CENTER = (30, 252, 10, 63)
AXIS_NEIGHBORS = {
    "gold_short": [(20, 252, 10, 63), (40, 252, 10, 63)],
    "gold_long": [(30, 189, 10, 63), (30, 378, 10, 63)],
    "bitcoin_short": [(30, 252, 7, 63), (30, 252, 15, 63)],
    "bitcoin_long": [(30, 252, 10, 42), (30, 252, 10, 84)],
}


def git_status() -> str:
    return subprocess.run(
        ["git", "status", "--short"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


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
    formal_components = independent.simulate_asset_components(formal_prices, AFTER_WEIGHTS)

    # Volatility signals keep their full pre-formal history.  Portfolio returns
    # still begin at the live-ETF common start.  This avoids a 252/504-day
    # artificial scale=1 warmup in the formal comparison.
    formal_signals = pd.concat(
        {
            "SPY": raw["SPY"].reindex(calendar),
            "GOLD": raw["GLD"].reindex(calendar),
            "BTC": raw["BTC-USD"].reindex(calendar),
        },
        axis=1,
    )
    return {
        "long_prices": long_prices,
        "long_components": long_components,
        "long_signals": long_prices[["SPY", "GOLD", "BTC"]],
        "formal_prices": formal_prices,
        "formal_components": formal_components,
        "formal_signals": formal_signals,
        "sources": sources,
        "proxy_map": proxy_map,
        "excluded_date": excluded_date,
    }


def signal_return(signal_prices: pd.DataFrame, name: str) -> pd.Series:
    return signal_prices[name].pct_change(fill_method=None)


def apply_candidate(components, prices, scales, v77):
    return prior.apply_sleeve_scales(components, prices, scales, v77)


def spy_candidates(prices, components, signals, v77):
    spy_ret = signal_return(signals, "SPY")
    prior_warmup_spy_ret = spy_ret.reindex(components.index)
    returns, costs, gross, params = {}, {}, {}, {}

    definitions = {
        "baseline_absolute_15": prior.absolute_scale(spy_ret, 0.15, v77),
        "parity_prior_absolute_15": prior.absolute_scale(
            prior_warmup_spy_ret, 0.15, v77
        ),
        "comparison_absolute_16": prior.absolute_scale(spy_ret, 0.16, v77),
        "comparison_no_equity_scale": pd.Series(1.0, index=spy_ret.index),
    }
    for name, scale in definitions.items():
        result, cost, exposure = apply_candidate(
            components, prices, {"Equities (SPY)": scale}, v77
        )
        returns[name], costs[name], gross[name] = result, cost, exposure
        params[name] = {
            "mode": name,
            "short_window": 0,
            "long_window": 0,
            "target_vol": 0.15 if name.endswith("15") else (0.16 if name.endswith("16") else 0.0),
        }

    for short in SPY_SHORTS:
        for long in SPY_LONGS:
            if long < 3 * short:
                continue
            name = f"spy_relative_s{short}_l{long}"
            scale = prior.relative_scale(spy_ret, short, long, v77)
            result, cost, exposure = apply_candidate(
                components, prices, {"Equities (SPY)": scale}, v77
            )
            returns[name], costs[name], gross[name] = result, cost, exposure
            params[name] = {
                "mode": "relative",
                "short_window": short,
                "long_window": long,
                "target_vol": 0.0,
            }
    frame = pd.DataFrame(returns).dropna(how="any")
    return (
        frame,
        pd.DataFrame(costs).reindex(frame.index),
        pd.DataFrame(gross).reindex(frame.index),
        params,
    )


def bundle_name(gs: int, gl: int, bs: int, bl: int) -> str:
    return f"bundle_gs{gs}_gl{gl}_bs{bs}_bl{bl}"


def width_candidates(prices, components, signals, v77):
    spy_ret = signal_return(signals, "SPY")
    gold_ret = signal_return(signals, "GOLD")
    btc_ret = signal_return(signals, "BTC")
    equity_scale = prior.absolute_scale(spy_ret, 0.15, v77)
    returns, costs, gross, params = {}, {}, {}, {}

    def add(name: str, gold_rule=None, btc_rule=None, kind=""):
        scales = {"Equities (SPY)": equity_scale}
        gs = gl = bs = bl = 0
        if gold_rule is not None:
            gs, gl = gold_rule
            scales["Gold"] = prior.relative_scale(gold_ret, gs, gl, v77)
        if btc_rule is not None:
            bs, bl = btc_rule
            scales["Bitcoin"] = prior.relative_scale(btc_ret, bs, bl, v77)
        result, cost, exposure = apply_candidate(components, prices, scales, v77)
        returns[name], costs[name], gross[name] = result, cost, exposure
        params[name] = {
            "kind": kind,
            "gold_short": gs,
            "gold_long": gl,
            "bitcoin_short": bs,
            "bitcoin_long": bl,
        }

    add("baseline_no_gold_btc_relative", kind="baseline")
    for short in GOLD_SHORTS:
        for long in GOLD_LONGS:
            if long >= 3 * short:
                add(
                    f"gold_s{short}_l{long}",
                    gold_rule=(short, long),
                    kind="gold_surface",
                )
    for short in BTC_SHORTS:
        for long in BTC_LONGS:
            if long >= 3 * short:
                add(
                    f"bitcoin_s{short}_l{long}",
                    btc_rule=(short, long),
                    kind="bitcoin_surface",
                )
    for gs in LOCAL_GOLD_SHORTS:
        for gl in LOCAL_GOLD_LONGS:
            for bs in LOCAL_BTC_SHORTS:
                for bl in LOCAL_BTC_LONGS:
                    add(
                        bundle_name(gs, gl, bs, bl),
                        gold_rule=(gs, gl),
                        btc_rule=(bs, bl),
                        kind="local_bundle_cube",
                    )
    frame = pd.DataFrame(returns).dropna(how="any")
    return (
        frame,
        pd.DataFrame(costs).reindex(frame.index),
        pd.DataFrame(gross).reindex(frame.index),
        params,
    )


def build_outputs(pack):
    returns, costs, gross, params = pack
    return prior.build_outputs(returns, costs, gross, params)


def save_standard(run_dir, data, long_pack, formal_pack, command, elapsed):
    long_summary, long_wide, long_metrics = build_outputs(long_pack)
    formal_returns, formal_costs, formal_gross, params = formal_pack
    mask = formal_returns.index >= FORMAL_START
    formal_pack_cut = (
        formal_returns.loc[mask],
        formal_costs.loc[mask],
        formal_gross.loc[mask],
        params,
    )
    formal_summary, formal_wide, formal_metrics = build_outputs(formal_pack_cut)
    long_summary.to_csv(run_dir / "scan_summary.csv", index=False, encoding="utf-8-sig")
    long_wide.to_csv(run_dir / "window_metrics.csv", index=False, encoding="utf-8-sig")
    formal_summary.to_csv(run_dir / "formal_scan_summary.csv", index=False, encoding="utf-8-sig")
    formal_wide.to_csv(run_dir / "formal_window_metrics.csv", index=False, encoding="utf-8-sig")
    long_pack[0].to_csv(run_dir / "daily_returns.csv", encoding="utf-8-sig")
    data["sources"].to_csv(run_dir / "sources.csv", index=False, encoding="utf-8-sig")
    data["proxy_map"].to_csv(run_dir / "proxy_map.csv", index=False, encoding="utf-8-sig")
    with (run_dir / "command_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(
            f"\nworking_directory={ROOT}\ncommand={command}\nelapsed_sec={elapsed:.3f}\n"
        )
    return long_summary, long_wide, formal_summary, formal_wide, long_metrics, formal_metrics


def update_meta(run_dir: Path, **updates):
    path = run_dir / "scan_meta.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta.update(updates)
    meta["repo_root"] = str(ROOT)
    meta["git_status_after"] = git_status()
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def valid_return_tolerance(wide_row, baseline_row) -> bool:
    limits = {
        "full": 1.0,
        "last_10y": 1.0,
        "last_5y": 1.0,
        "last_3y": 3.0,
        "last_1y": 3.0,
    }
    for segment, limit_pp in limits.items():
        candidate = wide_row[f"ann_return_{segment}"]
        baseline = baseline_row[f"ann_return_{segment}"]
        if pd.isna(candidate) or pd.isna(baseline):
            continue
        if (candidate - baseline) * 100 < -limit_pp - 1e-12:
            return False
    return True


def width_audit(wide: pd.DataFrame):
    indexed = wide.set_index("candidate")
    baseline = indexed.loc["baseline_no_gold_btc_relative"]
    center_name = bundle_name(*CENTER)
    center = indexed.loc[center_name]
    baseline_sharpe = baseline["sharpe_repo_full"]
    center_gain = center["sharpe_repo_full"] - baseline_sharpe
    rows = []
    axis_passes = {}
    for axis, neighbors in AXIS_NEIGHBORS.items():
        side_rows = []
        for side, params in zip(["left", "right"], neighbors):
            name = bundle_name(*params)
            row = indexed.loc[name]
            gain = row["sharpe_repo_full"] - baseline_sharpe
            retention = gain / center_gain if center_gain > 0 else np.nan
            item = {
                "axis": axis,
                "side": side,
                "candidate": name,
                "gold_short": params[0],
                "gold_long": params[1],
                "bitcoin_short": params[2],
                "bitcoin_long": params[3],
                "full_cagr": row["ann_return_full"],
                "full_max_dd": row["max_dd_full"],
                "full_sharpe": row["sharpe_repo_full"],
                "sharpe_gain_vs_baseline": gain,
                "gain_retention_vs_center": retention,
                "return_tolerance_pass": valid_return_tolerance(row, baseline),
                "side_pass_80pct": bool(
                    retention >= 0.8 and valid_return_tolerance(row, baseline)
                ),
            }
            rows.append(item)
            side_rows.append(item)
        axis_passes[axis] = all(item["side_pass_80pct"] for item in side_rows)
    return pd.DataFrame(rows), axis_passes, center_name, baseline_sharpe, center_gain


def cube_audit(wide, baseline_sharpe, center_gain):
    frame = wide[wide["kind"] == "local_bundle_cube"].copy()
    baseline = wide[wide.candidate == "baseline_no_gold_btc_relative"].iloc[0]
    frame["sharpe_gain_vs_baseline"] = frame.sharpe_repo_full - baseline_sharpe
    frame["gain_retention_vs_center"] = frame.sharpe_gain_vs_baseline / center_gain
    frame["return_tolerance_pass"] = frame.apply(
        lambda row: valid_return_tolerance(row, baseline), axis=1
    )
    frame["width_supported"] = (
        (frame.gain_retention_vs_center >= 0.8) & frame.return_tolerance_pass
    )

    dimensions = [
        LOCAL_GOLD_SHORTS,
        LOCAL_GOLD_LONGS,
        LOCAL_BTC_SHORTS,
        LOCAL_BTC_LONGS,
    ]
    supported = {
        (int(r.gold_short), int(r.gold_long), int(r.bitcoin_short), int(r.bitcoin_long))
        for _, r in frame[frame.width_supported].iterrows()
    }
    visited = set()
    components = []
    for point in supported:
        if point in visited:
            continue
        queue = deque([point])
        visited.add(point)
        component = []
        while queue:
            current = queue.popleft()
            component.append(current)
            for axis, values in enumerate(dimensions):
                position = values.index(current[axis])
                for offset in (-1, 1):
                    neighbor_pos = position + offset
                    if 0 <= neighbor_pos < len(values):
                        neighbor = list(current)
                        neighbor[axis] = values[neighbor_pos]
                        neighbor = tuple(neighbor)
                        if neighbor in supported and neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)
        components.append(component)
    largest = max((len(component) for component in components), default=0)
    center_supported = CENTER in supported
    return frame, {
        "supported_points": len(supported),
        "total_points": len(frame),
        "supported_fraction": len(supported) / len(frame),
        "connected_components": len(components),
        "largest_component": largest,
        "center_supported": center_supported,
    }


def heatmap(frame, value, short_col, long_col, title, output):
    pivot = frame.pivot(index=short_col, columns=long_col, values=value).sort_index(ascending=False)
    fig, axis = plt.subplots(figsize=(10.5, 6.5))
    image = axis.imshow(pivot, aspect="auto", cmap="RdYlGn")
    axis.set_xticks(range(len(pivot.columns)), [str(int(x)) for x in pivot.columns])
    axis.set_yticks(range(len(pivot.index)), [str(int(x)) for x in pivot.index])
    axis.set_xlabel("Long window")
    axis.set_ylabel("Short window")
    axis.set_title(title)
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            value_item = pivot.iloc[i, j]
            if pd.notna(value_item):
                axis.text(j, i, f"{value_item:.3f}", ha="center", va="center", fontsize=7)
    fig.colorbar(image, ax=axis)
    fig.tight_layout()
    fig.savefig(output, dpi=170)
    plt.close(fig)


def run_spy(data, v77, command, started):
    long_pack = spy_candidates(
        data["long_prices"], data["long_components"], data["long_signals"], v77
    )
    formal_pack = spy_candidates(
        data["formal_prices"], data["formal_components"], data["formal_signals"], v77
    )
    elapsed = time.perf_counter() - started
    _, wide, _, formal_wide, _, _ = save_standard(
        SPY_RUN, data, long_pack, formal_pack, command, elapsed
    )
    baseline = wide[wide.candidate == "baseline_absolute_15"].iloc[0]
    relative = wide[wide["mode"] == "relative"].copy()
    relative["sharpe_delta"] = relative.sharpe_repo_full - baseline.sharpe_repo_full
    relative["cagr_delta_pp"] = (relative.ann_return_full - baseline.ann_return_full) * 100
    relative["dd_improvement_pp"] = (relative.max_dd_full - baseline.max_dd_full) * 100
    relative.to_csv(SPY_RUN / "relative_grid_deltas.csv", index=False, encoding="utf-8-sig")
    heatmap(
        relative,
        "sharpe_delta",
        "short_window",
        "long_window",
        "SPY equity relative-vol: full Sharpe delta vs absolute 15%",
        SPY_RUN / "spy_relative_sharpe_heatmap.png",
    )
    prior_daily = pd.read_csv(
        ROOT / "quant_param_scan_runs" / "20260812_subc_equity_target_vol" / "daily_returns.csv",
        index_col=0,
        parse_dates=True,
    )["equity_target_15%"].dropna()
    measured = long_pack[0]["parity_prior_absolute_15"]
    common = measured.index.intersection(prior_daily.index)
    parity = float((measured.loc[common] - prior_daily.loc[common]).abs().max())
    update_meta(
        SPY_RUN,
        scan_type="two_parameter_grid",
        baseline={"candidate": "baseline_absolute_15", "target_vol": 0.15},
        candidate_grid=[
            {"short_window": s, "long_window": l}
            for s in SPY_SHORTS
            for l in SPY_LONGS
            if l >= 3 * s
        ],
        data_snapshot={
            "long_proxy_start": long_pack[0].index.min().date().isoformat(),
            "formal_start": FORMAL_START.date().isoformat(),
            "end": long_pack[0].index.max().date().isoformat(),
            "source": "Yahoo adjusted close via V7.9 loader",
            "formal_signal_warmup": "full pre-formal SPY history",
        },
        cost_model={
            "annual_asset_rebalance_two_way": base.ASSET_REBAL_COST,
            "scale_adjustment_bps": v77.PROD_VS_REBAL_COST_BPS,
            "financing_spread_bps": v77.PROD_VS_SPREAD_BPS,
        },
        parity_check={
            "candidate": "parity_prior_absolute_15",
            "max_daily_return_difference": parity,
            "tolerance": 2e-6,
            "fair_comparison_baseline": "baseline_absolute_15 with full pre-sample SPY warmup",
        },
        elapsed_sec=elapsed,
        excluded_unconfirmed_date=data["excluded_date"],
        production_code_changed=False,
    )
    print("TOP SPY RELATIVE BY SHARPE")
    print(
        relative.sort_values("sharpe_repo_full", ascending=False)[
            [
                "candidate",
                "short_window",
                "long_window",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "sharpe_delta",
                "cagr_delta_pp",
                "dd_improvement_pp",
            ]
        ].head(20).to_string(index=False)
    )
    print("\nFORMAL TOP")
    top_names = relative.sort_values("sharpe_repo_full", ascending=False).head(8).candidate
    print(
        formal_wide[formal_wide.candidate.isin(top_names)][
            ["candidate", "ann_return_full", "max_dd_full", "sharpe_repo_full"]
        ].sort_values("sharpe_repo_full", ascending=False).to_string(index=False)
    )
    print("\nPARITY", parity)


def run_width(data, v77, command, started):
    long_pack = width_candidates(
        data["long_prices"], data["long_components"], data["long_signals"], v77
    )
    formal_pack = width_candidates(
        data["formal_prices"], data["formal_components"], data["formal_signals"], v77
    )
    gold_ready = (
        signal_return(data["long_signals"], "GOLD")
        .rolling(max(GOLD_LONGS))
        .std()
        .first_valid_index()
    )
    btc_ready = (
        signal_return(data["long_signals"], "BTC")
        .rolling(max(BTC_LONGS))
        .std()
        .first_valid_index()
    )
    common_warm_start = max(gold_ready, btc_ready, long_pack[0].index.min())
    long_pack = (
        long_pack[0].loc[common_warm_start:],
        long_pack[1].loc[common_warm_start:],
        long_pack[2].loc[common_warm_start:],
        long_pack[3],
    )
    elapsed = time.perf_counter() - started
    _, wide, _, formal_wide, _, _ = save_standard(
        WIDTH_RUN, data, long_pack, formal_pack, command, elapsed
    )
    axis, axis_passes, center_name, baseline_sharpe, center_gain = width_audit(wide)
    cube, cube_summary = cube_audit(wide, baseline_sharpe, center_gain)
    axis.to_csv(WIDTH_RUN / "axis_width_audit.csv", index=False, encoding="utf-8-sig")
    cube.to_csv(WIDTH_RUN / "local_cube_width_audit.csv", index=False, encoding="utf-8-sig")
    (WIDTH_RUN / "width_summary.json").write_text(
        json.dumps(
            {
                "center": center_name,
                "baseline_full_sharpe": baseline_sharpe,
                "center_sharpe_gain": center_gain,
                "axis_passes": axis_passes,
                "all_four_axes_pass": all(axis_passes.values()),
                "cube": cube_summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    gold = wide[wide.kind == "gold_surface"].copy()
    btc = wide[wide.kind == "bitcoin_surface"].copy()
    gold["sharpe_delta"] = gold.sharpe_repo_full - baseline_sharpe
    btc["sharpe_delta"] = btc.sharpe_repo_full - baseline_sharpe
    heatmap(
        gold,
        "sharpe_delta",
        "gold_short",
        "gold_long",
        "Gold relative-vol extended width: full Sharpe delta",
        WIDTH_RUN / "gold_width_heatmap.png",
    )
    heatmap(
        btc,
        "sharpe_delta",
        "bitcoin_short",
        "bitcoin_long",
        "Bitcoin relative-vol extended width: full Sharpe delta",
        WIDTH_RUN / "bitcoin_width_heatmap.png",
    )

    prior_daily = pd.read_csv(
        ROOT
        / "quant_param_scan_runs"
        / "20260812_subc_non_equity_relative_vol"
        / "post_selection_bundle_daily_returns.csv",
        index_col=0,
        parse_dates=True,
    )
    baseline_prior = prior_daily["baseline"].dropna()
    center_prior = prior_daily["gold30_252_btc10_63"].dropna()
    measured_baseline = long_pack[0]["baseline_no_gold_btc_relative"]
    measured_center = long_pack[0][center_name]
    common_base = measured_baseline.index.intersection(baseline_prior.index)
    common_center = measured_center.index.intersection(center_prior.index)
    parity = {
        "baseline": float(
            (measured_baseline.loc[common_base] - baseline_prior.loc[common_base]).abs().max()
        ),
        "center": float(
            (measured_center.loc[common_center] - center_prior.loc[common_center]).abs().max()
        ),
    }
    update_meta(
        WIDTH_RUN,
        scan_type="two_parameter_grid_plus_local_four_parameter_width_cube",
        baseline={"candidate": "baseline_no_gold_btc_relative", "equity_target": 0.15},
        center={
            "candidate": center_name,
            "gold_short": 30,
            "gold_long": 252,
            "bitcoin_short": 10,
            "bitcoin_long": 63,
        },
        width_rule="both immediate sides on every axis retain >=80% of center positive full-Sharpe gain vs baseline and pass return tolerance",
        candidate_grid={
            "gold_short": GOLD_SHORTS,
            "gold_long": GOLD_LONGS,
            "bitcoin_short": BTC_SHORTS,
            "bitcoin_long": BTC_LONGS,
            "local_cube": {
                "gold_short": LOCAL_GOLD_SHORTS,
                "gold_long": LOCAL_GOLD_LONGS,
                "bitcoin_short": LOCAL_BTC_SHORTS,
                "bitcoin_long": LOCAL_BTC_LONGS,
            },
        },
        data_snapshot={
            "long_proxy_start": long_pack[0].index.min().date().isoformat(),
            "common_longest_window_warmup_start": common_warm_start.date().isoformat(),
            "formal_start": FORMAL_START.date().isoformat(),
            "end": long_pack[0].index.max().date().isoformat(),
            "source": "Yahoo adjusted close via V7.9 loader",
            "formal_signal_warmup": "full pre-formal SPY/GLD/BTC history",
        },
        cost_model={
            "annual_asset_rebalance_two_way": base.ASSET_REBAL_COST,
            "scale_adjustment_bps": v77.PROD_VS_REBAL_COST_BPS,
            "financing_spread_bps": v77.PROD_VS_SPREAD_BPS,
        },
        parity_check={"max_daily_return_difference": parity, "tolerance": 2e-6},
        width_audit={"axis_passes": axis_passes, "cube": cube_summary},
        elapsed_sec=elapsed,
        excluded_unconfirmed_date=data["excluded_date"],
        production_code_changed=False,
    )
    print("AXIS WIDTH")
    print(axis.to_string(index=False))
    print("\nAXIS PASSES", axis_passes)
    print("\nCUBE", cube_summary)
    print("\nTOP LOCAL CUBE")
    print(
        cube.sort_values("sharpe_repo_full", ascending=False)[
            [
                "candidate",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "gain_retention_vs_center",
                "width_supported",
            ]
        ].head(15).to_string(index=False)
    )
    print("\nFORMAL CENTER")
    print(
        formal_wide[
            formal_wide.candidate.isin(
                ["baseline_no_gold_btc_relative", center_name]
            )
        ][
            [
                "candidate",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "ann_return_last_5y",
                "max_dd_last_5y",
                "ann_return_last_3y",
                "max_dd_last_3y",
                "ann_return_last_1y",
                "max_dd_last_1y",
            ]
        ].to_string(index=False)
    )
    print("\nPARITY", parity)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["spy", "width"])
    args = parser.parse_args()
    started = time.perf_counter()
    v77 = base.load_module(base.V77_PATH, f"v77_relative_width_{args.phase}")
    v79 = base.load_module(base.V79_PATH, f"v79_relative_width_{args.phase}")
    data = prepare_data(v79)
    command = f'python "{Path(__file__).name}" {args.phase}'
    if args.phase == "spy":
        run_spy(data, v77, command, started)
    else:
        run_width(data, v77, command, started)


if __name__ == "__main__":
    main()

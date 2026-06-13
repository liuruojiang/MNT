"""Layer 3 target-vol scan for long ZZ500 / short CYB spread.

Inputs are selected Layer 2 score/absolute-bias carry candidates. This layer
adds only target-vol exposure scaling and a scale-change deadband. NAV defense,
overheat, amount/volume, and momentum decay remain off.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_cyb_spread_layer2_score_abs_filter as l2
import scan_adk_zz500_cyb_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_cyb_spread_long_only_v77_adk_spread_layer3_target_vol_l2_bias_carry"

L2_INPUTS = [
    {
        "layer2_anchor": "bias_primary_abs60_m2p5",
        "candidate": "l2_bias_10_29_we3_score0_abs60_gt_m2p5pct",
        "anchor": "bias_10_29_we3",
        "family": "bias_momentum",
        "bias_ma": 10,
        "mom_day": 29,
        "weight_end": 3.0,
        "layer1_candidate": "bias_ma010_mom029_we3p0_gt0",
        "score_threshold": 0.0,
        "abs_ma": 60,
        "abs_threshold": -0.025,
        "abs_filter": "ratio_bias",
        "role": "primary_bias",
    },
    {
        "layer2_anchor": "bias_confirm_abs65_m3",
        "candidate": "l2_bias_10_29_we3_score0_abs65_gt_m3pct",
        "anchor": "bias_10_29_we3",
        "family": "bias_momentum",
        "bias_ma": 10,
        "mom_day": 29,
        "weight_end": 3.0,
        "layer1_candidate": "bias_ma010_mom029_we3p0_gt0",
        "score_threshold": 0.0,
        "abs_ma": 65,
        "abs_threshold": -0.030,
        "abs_filter": "ratio_bias",
        "role": "nearby_confirmation",
    },
    {
        "layer2_anchor": "bias_dd_tight_score1_abs35_p3p5",
        "candidate": "l2_bias_10_29_we3_score1_abs35_gt_3p5pct",
        "anchor": "bias_10_29_we3",
        "family": "bias_momentum",
        "bias_ma": 10,
        "mom_day": 29,
        "weight_end": 3.0,
        "layer1_candidate": "bias_ma010_mom029_we3p0_gt0",
        "score_threshold": 1.0,
        "abs_ma": 35,
        "abs_threshold": 0.035,
        "abs_filter": "ratio_bias",
        "role": "dd_tight_watchlist",
    },
    {
        "layer2_anchor": "log_reference_score5_abs55_m0p5",
        "candidate": "l2_log_11_we2_score5_abs55_gt_m0p5pct",
        "anchor": "log_11_we2",
        "family": "log_wls_momentum",
        "bias_ma": 0,
        "mom_day": 11,
        "weight_end": 2.0,
        "layer1_candidate": "dense_log_wls_mom011_we2p0_gt0",
        "score_threshold": 5.0,
        "abs_ma": 55,
        "abs_threshold": -0.005,
        "abs_filter": "ratio_bias",
        "role": "log_reference",
    },
]

TARGET_VOLS = [0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20]
VOL_WINDOWS = [20, 40, 60, 80, 120]
MAX_LEVERAGES = [1.0, 1.25, 1.5, 2.0]
MIN_SCALES = [0.0, 0.25, 0.5]
DEADBANDS = [
    ("none", 0.0),
    ("abs", 0.025),
    ("abs", 0.05),
    ("abs", 0.10),
    ("abs", 0.15),
    ("abs", 0.20),
    ("rel", 0.05),
    ("rel", 0.10),
    ("rel", 0.15),
    ("rel", 0.20),
]
LOSS_TIERS = [1.0, 2.0, 3.0]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def apply_deadband(desired: pd.Series, mode: str, value: float) -> pd.Series:
    arr = desired.fillna(0.0).to_numpy(dtype=float)
    out = np.zeros(len(arr), dtype=float)
    prev = 0.0
    for i, target in enumerate(arr):
        target = float(target)
        if target <= 0.0:
            selected = 0.0
        elif prev <= 0.0:
            selected = target
        elif mode == "none" or value <= 0.0:
            selected = target
        else:
            delta = abs(target - prev)
            if mode == "abs":
                selected = target if delta >= value else prev
            elif mode == "rel":
                selected = target if delta / max(abs(prev), 1e-12) >= value else prev
            else:
                raise ValueError(f"unsupported deadband mode: {mode}")
        out[i] = selected
        prev = selected
    return pd.Series(out, index=desired.index)


def build_l2_signal_frame(
    panel: pd.DataFrame,
    candidate: dict[str, object],
    scores: dict[str, pd.Series],
    r2s: dict[str, pd.Series],
    abs_bias: dict[int, pd.Series],
) -> pd.DataFrame:
    score = scores[str(candidate["anchor"])]
    r2 = r2s[str(candidate["anchor"])]
    raw_signal = (score > float(candidate["score_threshold"])) & (r2 >= 0.05)
    abs_ma = int(candidate["abs_ma"])
    if abs_ma > 0:
        raw_signal = raw_signal & (abs_bias[abs_ma] > float(candidate["abs_threshold"]))
    warmup = max(int(candidate["bias_ma"]), int(candidate["mom_day"]), abs_ma) + 2
    spread_return = panel["spread_return"]
    base_exec_weight = raw_signal.astype(float).shift(1).fillna(0.0)
    base_turnover = base_exec_weight.diff().abs().fillna(base_exec_weight.abs())
    base_cost = base_turnover * (2.0 * base.COMMISSION_ONE_WAY)
    out = pd.DataFrame(
        {
            "spread_return": spread_return,
            "raw_signal": raw_signal.astype(float),
            "base_weight": base_exec_weight,
            "score": score,
            "r2": r2,
            "realized_source_return": spread_return,
            "return": base_exec_weight * spread_return - base_cost,
            "gross_return": base_exec_weight * spread_return,
            "cost": base_cost,
            "turnover": base_turnover,
            "weight": base_exec_weight,
            "raw_scale": raw_signal.astype(float),
            "selected_scale": raw_signal.astype(float),
        },
        index=panel.index,
    )
    return out.iloc[warmup:].copy()


def realized_vol(source_return: pd.Series, window: int) -> pd.Series:
    return source_return.rolling(window).std(ddof=0) * math.sqrt(base.ANNUALIZATION_DAYS)


def apply_target_vol(base_frame: pd.DataFrame, grid: dict[str, object]) -> pd.DataFrame:
    tv = float(grid["target_vol"])
    vol_window = int(grid["vol_window"])
    max_lev = float(grid["max_leverage"])
    min_scale = float(grid["min_scale"])
    deadband_mode = str(grid["deadband_mode"])
    deadband_value = float(grid["deadband_value"])

    vol = realized_vol(base_frame["realized_source_return"], vol_window)
    raw_scale = (tv / vol.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)
    raw_scale = raw_scale.clip(lower=min_scale, upper=max_lev)
    desired = base_frame["raw_signal"] * raw_scale.fillna(0.0)
    selected = apply_deadband(desired, deadband_mode, deadband_value)
    exec_weight = selected.shift(1).fillna(0.0)

    turnover = exec_weight.diff().abs().fillna(exec_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = exec_weight * base_frame["spread_return"]
    ret = gross_return - cost
    scale_change = selected.diff().abs().fillna(selected.abs())
    small_change = (scale_change > 1e-12) & (scale_change < 0.05)
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": exec_weight,
            "raw_scale": raw_scale,
            "selected_scale": selected,
            "raw_signal": base_frame["raw_signal"],
            "realized_vol": vol,
            "scale_change": scale_change,
            "small_scale_change": small_change.astype(float),
        },
        index=base_frame.index,
    ).iloc[vol_window + 1 :].copy()


def candidate_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for l2_input in L2_INPUTS:
        short = str(l2_input["layer2_anchor"])
        grid.append(
            {
                **l2_input,
                "candidate": f"l3_{short}_tv_off",
                "layer2_candidate": l2_input["candidate"],
                "target_vol": 0.0,
                "vol_window": 0,
                "max_leverage": 1.0,
                "min_scale": 0.0,
                "deadband_mode": "off",
                "deadband_value": 0.0,
                "target_vol_enabled": False,
            }
        )
        for tv in TARGET_VOLS:
            for vol_window in VOL_WINDOWS:
                for max_lev in MAX_LEVERAGES:
                    for min_scale in MIN_SCALES:
                        if min_scale > max_lev:
                            continue
                        for deadband_mode, deadband_value in DEADBANDS:
                            grid.append(
                                {
                                    **l2_input,
                                    "candidate": (
                                        f"l3_{short}_tv{fmt_num(tv, pct=True)}"
                                        f"_rv{vol_window}_max{fmt_num(max_lev)}"
                                        f"_floor{fmt_num(min_scale)}"
                                        f"_db{deadband_mode}{fmt_num(deadband_value, pct=(deadband_mode == 'rel'))}"
                                    ),
                                    "layer2_candidate": l2_input["candidate"],
                                    "target_vol": tv,
                                    "vol_window": vol_window,
                                    "max_leverage": max_lev,
                                    "min_scale": min_scale,
                                    "deadband_mode": deadband_mode,
                                    "deadband_value": deadband_value,
                                    "target_vol_enabled": True,
                                }
                            )
    return grid


def extra_metrics(result: pd.DataFrame) -> dict[str, float]:
    active = result["weight"].abs() > 1e-12
    scale_change = result["selected_scale"].diff().abs().fillna(result["selected_scale"].abs())
    change_days = scale_change > 1e-12
    return {
        "avg_scale_full": float(result["weight"].mean()),
        "avg_abs_scale_full": float(result["weight"].abs().mean()),
        "avg_scale_when_active_full": float(result.loc[active, "weight"].mean()) if active.any() else 0.0,
        "avg_raw_scale_when_signal_full": float(result.loc[result["raw_signal"] > 0, "raw_scale"].mean())
        if (result["raw_signal"] > 0).any()
        else 0.0,
        "scale_change_frequency_full": float(change_days.mean()),
        "small_scale_change_frequency_full": float(result["small_scale_change"].mean()),
        "avg_scale_change_when_changed_full": float(scale_change.loc[change_days].mean()) if change_days.any() else 0.0,
    }


def add_baselines_and_flags(window_metrics: pd.DataFrame) -> pd.DataFrame:
    out = window_metrics.copy()
    for segment in ["full", "last_10y", "last_5y", "last_3y", "last_1y"]:
        out[f"{segment}_ann_loss_pp"] = (out[f"base_ann_return_{segment}"] - out[f"ann_return_{segment}"]) * 100.0
        out[f"{segment}_dd_improve_pp"] = (out[f"max_dd_{segment}"] - out[f"base_max_dd_{segment}"]) * 100.0
    out["turnover_delta_full"] = out["avg_turnover_full"] - out["base_avg_turnover_full"]
    out["cost_delta_full"] = out["cost_total_full"] - out["base_cost_total_full"]
    out["pass_full_ann_dd"] = (
        (out["ann_return_full"] >= out["base_ann_return_full"] - 1e-12)
        & (out["max_dd_full"] >= out["base_max_dd_full"] - 1e-12)
    )
    out["pass_full_5y_ann_dd"] = (
        out["pass_full_ann_dd"]
        & (out["ann_return_last_5y"] >= out["base_ann_return_last_5y"] - 1e-12)
        & (out["max_dd_last_5y"] >= out["base_max_dd_last_5y"] - 1e-12)
    )
    out["practical_scale_path"] = (
        (out["scale_change_frequency_full"] <= 0.18)
        & (out["small_scale_change_frequency_full"] <= 0.06)
        & (out["avg_scale_change_when_changed_full"] >= 0.04)
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            out["target_vol_enabled"]
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["last_5y_dd_improve_pp"] >= -1e-12)
            & out["practical_scale_path"]
        )
    return out


def width_summary(window_metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    source = window_metrics[window_metrics["target_vol_enabled"]].copy()
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for layer2_anchor, group in source.groupby("layer2_anchor"):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "loss_tier_pp": tier,
                        "layer2_anchor": layer2_anchor,
                        "pass_count": 0,
                        "target_vol_count": 0,
                        "vol_window_count": 0,
                        "max_leverage_count": 0,
                        "deadband_variant_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_scale_change_frequency": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(
                ["full_dd_improve_pp", "ann_return_full", "scale_change_frequency_full"],
                ascending=[False, False, True],
            ).iloc[0]
            deadband_count = passed[["deadband_mode", "deadband_value"]].drop_duplicates().shape[0]
            patch_like = bool(
                len(passed) >= 8
                and passed["target_vol"].nunique() >= 2
                and passed["vol_window"].nunique() >= 2
                and passed["max_leverage"].nunique() >= 2
                and deadband_count >= 2
            )
            rows.append(
                {
                    "loss_tier_pp": tier,
                    "layer2_anchor": layer2_anchor,
                    "pass_count": int(len(passed)),
                    "target_vol_count": int(passed["target_vol"].nunique()),
                    "vol_window_count": int(passed["vol_window"].nunique()),
                    "max_leverage_count": int(passed["max_leverage"].nunique()),
                    "deadband_variant_count": int(deadband_count),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "best_full_ann_loss_pp": float(best["full_ann_loss_pp"]),
                    "best_full_dd_improve_pp": float(best["full_dd_improve_pp"]),
                    "best_scale_change_frequency": float(best["scale_change_frequency_full"]),
                    "patch_like": patch_like,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def select_carry(window_metrics: pd.DataFrame, ridge: pd.DataFrame) -> pd.DataFrame:
    strict = window_metrics[
        window_metrics["target_vol_enabled"]
        & window_metrics["pass_full_5y_ann_dd"]
        & window_metrics["practical_scale_path"]
    ].copy()
    if not strict.empty:
        strict["carry_score"] = (
            strict["ann_return_full"] * 20.0
            + strict["full_dd_improve_pp"].clip(lower=0, upper=20) * 0.5
            + strict["last_5y_dd_improve_pp"].clip(lower=0, upper=20) * 0.5
            - strict["scale_change_frequency_full"] * 5.0
            - strict["small_scale_change_frequency_full"] * 10.0
        )
        return strict.sort_values(
            ["carry_score", "ann_return_full", "full_dd_improve_pp"],
            ascending=[False, False, False],
        ).groupby("layer2_anchor").head(2).head(10)

    pool = window_metrics[
        window_metrics["target_vol_enabled"]
        & window_metrics["practical_scale_path"]
        & (window_metrics["full_dd_improve_pp"] > 0)
        & (window_metrics["last_5y_dd_improve_pp"] >= -1e-12)
    ].copy()
    if pool.empty:
        return pool
    pool["carry_score"] = (
        pool["full_dd_improve_pp"].clip(lower=0, upper=30)
        + pool["last_5y_dd_improve_pp"].clip(lower=-5, upper=20) * 0.6
        - pool["full_ann_loss_pp"].clip(lower=-5, upper=10) * 0.8
        - pool["scale_change_frequency_full"] * 5.0
        - pool["small_scale_change_frequency_full"] * 10.0
        + pool["ann_return_full"] * 10.0
    )
    return pool.sort_values(["carry_score", "ann_return_full"], ascending=[False, False]).groupby("layer2_anchor").head(2).head(10)


def window_table(df: pd.DataFrame, n: int = 10) -> str:
    cols = [
        "candidate",
        "layer2_anchor",
        "role",
        "target_vol",
        "vol_window",
        "max_leverage",
        "min_scale",
        "deadband_mode",
        "deadband_value",
    ]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_") or col in {"target_vol", "deadband_value"}:
            display[col] = display[col].map(lambda x: pct(float(x)) if pd.notna(x) else "")
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, zz500, cyb, panel = l2.load_panel()
    scores, r2s, abs_bias = l2.precompute(panel)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    l2_frames = {
        str(item["layer2_anchor"]): build_l2_signal_frame(panel, item, scores, r2s, abs_bias)
        for item in L2_INPUTS
    }
    grid = candidate_grid()
    long_rows = []
    wide_rows = []
    result_cache: dict[str, pd.DataFrame] = {}
    baseline_metric_cache: dict[tuple[str, str, str], dict[str, dict[str, object]]] = {}

    for candidate in grid:
        layer2_anchor = str(candidate["layer2_anchor"])
        base_frame = l2_frames[layer2_anchor]
        if candidate["target_vol_enabled"]:
            result = apply_target_vol(base_frame, candidate)
        else:
            result = base_frame.copy()
            result["small_scale_change"] = 0.0
            result["scale_change"] = result["selected_scale"].diff().abs().fillna(result["selected_scale"].abs())
            result["realized_vol"] = np.nan

        extra = extra_metrics(result)
        wide = {**candidate, **extra}
        baseline_slice = base_frame.loc[result.index].copy()
        baseline_key = (layer2_anchor, str(result.index.min().date()), str(result.index.max().date()))
        if baseline_key not in baseline_metric_cache:
            baseline_metric_cache[baseline_key] = {
                segment: base.metrics_for_segment(baseline_slice, segment, years)
                for segment, years in base.SEGMENTS
            }
        for segment, years in base.SEGMENTS:
            metrics = base.metrics_for_segment(result, segment, years)
            baseline_metrics = baseline_metric_cache[baseline_key][segment]
            long_rows.append({**candidate, **extra, **metrics})
            for key in [
                "ann_return",
                "max_dd",
                "sharpe_repo",
                "avg_weight",
                "avg_turnover",
                "holding_day_ratio",
                "cost_total",
            ]:
                wide[f"{key}_{segment}"] = metrics[key]
                wide[f"base_{key}_{segment}"] = baseline_metrics[key]
        wide_rows.append(wide)
        if not candidate["target_vol_enabled"]:
            result_cache[str(candidate["candidate"])] = result

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = width_summary(window_metrics)

    strict_full = window_metrics[
        window_metrics["target_vol_enabled"] & window_metrics["pass_full_ann_dd"] & window_metrics["practical_scale_path"]
    ].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
    strict_full_5y = window_metrics[
        window_metrics["target_vol_enabled"] & window_metrics["pass_full_5y_ann_dd"] & window_metrics["practical_scale_path"]
    ].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
    top_tier: dict[float, pd.DataFrame] = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        passed = window_metrics[window_metrics[pass_col]].sort_values(
            ["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]
        )
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_tier[tier] = passed

    carry = select_carry(window_metrics, ridge)
    selected_names = set(window_metrics[~window_metrics["target_vol_enabled"]]["candidate"].astype(str).tolist())
    for df in [strict_full, strict_full_5y, carry, *top_tier.values()]:
        if not df.empty:
            selected_names.update(df.head(8)["candidate"].astype(str).tolist())
    selected_lookup = {str(row["candidate"]): row.to_dict() for _, row in window_metrics.iterrows() if str(row["candidate"]) in selected_names}
    for name, candidate in selected_lookup.items():
        if name in result_cache:
            continue
        result_cache[name] = apply_target_vol(l2_frames[str(candidate["layer2_anchor"])], candidate)

    daily_rows = []
    for name, result in result_cache.items():
        out = result.copy()
        out["nav"] = (1.0 + out["return"]).cumprod()
        out["candidate"] = name
        daily_rows.append(out.reset_index(names="date"))
    daily = pd.concat(daily_rows, ignore_index=True) if daily_rows else pd.DataFrame()

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    strict_full.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_full_5y.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# ZZ500/CYB Layer 3 Target-Vol Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer3_target_vol_complete_not_promoted`",
        "- stability: `target_vol_width_and_deadband_pending_user_confirmation`",
        "",
        "## Research Question",
        "Scan target-vol exposure scaling after selected Layer 2 score/absolute-bias filters.",
        "",
        "## Layer Inputs",
        "- Layer 2 inputs:",
        *[
            f"  - `{item['layer2_anchor']}` from `{item['candidate']}`: role={item['role']}, score>{item['score_threshold']}, abs_ma={item['abs_ma']}, abs_threshold={item['abs_threshold']:.2%}"
            for item in L2_INPUTS
        ],
        f"- Target vols: `{', '.join(f'{x:.0%}' for x in TARGET_VOLS)}`.",
        f"- Realized-vol windows: `{', '.join(str(x) for x in VOL_WINDOWS)}`.",
        f"- Max leverage grid: `{', '.join(str(x) for x in MAX_LEVERAGES)}`.",
        f"- Min active scale/floor grid: `{', '.join(str(x) for x in MIN_SCALES)}`.",
        "- Deadband grid: none; absolute 0.025/0.05/0.10/0.15/0.20 scale; relative 5%/10%/15%/20%.",
        "",
        "## Implementation Anchor",
        "- Imports data loader, metrics, and Layer 2 signal construction from prior research scripts.",
        "- Target-vol scale is computed at T close from rolling spread-return volatility and shifted to T+1 execution.",
        "- Costs are recomputed after final target-vol exposure changes.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research with two-leg commissions, excluding futures basis, financing, borrow, and short locate costs.",
        "- Source-change rule: `research_only_new_scan_script`.",
        "",
        "## Data Snapshot",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- CYB publication date: {base.CYB_PUBLICATION_DATE}; local rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start rule: latest actual index publication date among the two legs.",
        "- Adjustment mode: price index close from local official cache, no total-return substitution.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal and target-vol scale -> T+1 close-to-close spread return.",
        "- Return stream: final scale times ZZ500 close-to-close return minus CYB close-to-close return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- No NAV defense, overheat, amount, volume, or momentum-decay overlay is applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 3 scan.",
        "",
        "## Commands",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"ZZ500/CYB spread Layer 3 target-vol\" --parameter-group \"target_vol_window_leverage_deadband\" --repo . --entrypoint \"scan_adk_zz500_cyb_spread_layer3_target_vol.py\" --date 2026-06-12 --slug \"adk_zz500_cyb_spread_long_only_v77_adk_spread_layer3_target_vol_l2_bias_carry\"`",
        "- `python -m py_compile \"scan_adk_zz500_cyb_spread_layer3_target_vol.py\"`",
        "- `python \"scan_adk_zz500_cyb_spread_layer3_target_vol.py\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py <run_folder> --decision \"layer3_target_vol_complete_not_promoted\" --stability-label \"target_vol_width_and_deadband_pending_user_confirmation\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>`",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `full_baseline_pass_candidates.csv`",
        "- `full_and_5y_pass_candidates.csv`",
        "- `dd_first_pass_loss_le_1p0pp.csv`",
        "- `dd_first_pass_loss_le_2p0pp.csv`",
        "- `dd_first_pass_loss_le_3p0pp.csv`",
        "- `carry_candidates.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        window_table(strict_full, 12) if not strict_full.empty else "No target-vol candidates passed full-sample annual-return and drawdown non-underperformance with practical scale path.",
        "",
        "## Window Results",
        window_table(strict_full_5y, 12) if not strict_full_5y.empty else "No target-vol candidates passed strict full+5Y annual-return and drawdown non-underperformance with practical scale path.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Operational Path Summary",
        "- `scale_change_frequency_full` measures selected-scale changes before the T+1 shift.",
        "- `small_scale_change_frequency_full` measures selected-scale changes below 0.05 after deadband.",
        "- `practical_scale_path` requires change frequency <=18%, small-change frequency <=6%, and average changed scale >=0.04.",
        "",
        "## Decision",
        "Layer 3 target-vol scan completed but not promoted. Stop for user review before Layer 4 NAV defense.",
        "",
        "## User-Facing Summary",
        f"- strict full pass count: {len(strict_full)}",
        f"- strict full+5Y pass count: {len(strict_full_5y)}",
        f"- loss<=1pp pass count: {len(top_tier[1.0])}",
        f"- loss<=2pp pass count: {len(top_tier[2.0])}",
        f"- loss<=3pp pass count: {len(top_tier[3.0])}",
        "",
        "## Next-Layer Carry Candidates",
        window_table(carry, 10) if not carry.empty else "No carry candidate selected.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "ZZ500/CYB spread Layer 3 target-vol",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz500_cyb_spread_layer2_score_abs_filter.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "layer3_target_vol",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "target_vol_window_leverage_deadband",
        "baseline": {"layer2_inputs": L2_INPUTS, "loss_tiers_pp": LOSS_TIERS},
        "candidate_grid_size": len(grid),
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal and target-vol scale -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "target_vol_model": {
            "realized_vol_source": "daily spread_return rolling std annualized by 242",
            "scale": "target_vol / realized_vol clipped to [min_scale, max_leverage] when Layer 2 signal is active",
            "deadband": "selected scale changes only when absolute or relative threshold is met; off signal resets scale to zero",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "zz500": {
                "secid": str(mod.CN_DK_ZZ500_SECID),
                "publication_date": base.ZZ500_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_ZZ500_SECID))),
                "rows": int(len(zz500)),
                "start": str(zz500.index.min().date()),
                "end": str(zz500.index.max().date()),
            },
            "cyb": {
                "secid": str(mod.CN_DK_CYB_SECID),
                "publication_date": base.CYB_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_CYB_SECID))),
                "rows": int(len(cyb)),
                "start": str(cyb.index.min().date()),
                "end": str(cyb.index.max().date()),
            },
            "formal": {
                "rows": int(len(panel)),
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
                "start_rule": "latest actual publication/listing date among participants",
                "ratio": "ZZ500 / CYB",
                "return_stream": "ZZ500 pct_change - CYB pct_change",
            },
        },
        "decision": "layer3_target_vol_complete_not_promoted",
        "stability_label": "target_vol_width_and_deadband_pending_user_confirmation",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "full_baseline_pass_candidates": str(RUN_DIR / "full_baseline_pass_candidates.csv"),
            "full_and_5y_pass_candidates": str(RUN_DIR / "full_and_5y_pass_candidates.csv"),
            "carry_candidates": str(RUN_DIR / "carry_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"ZZ500/CYB spread Layer 3 target-vol\" --parameter-group \"target_vol_window_leverage_deadband\" --repo . --entrypoint \"scan_adk_zz500_cyb_spread_layer3_target_vol.py\" --date 2026-06-12 --slug \"adk_zz500_cyb_spread_long_only_v77_adk_spread_layer3_target_vol_l2_bias_carry\"\n"
        "python -m py_compile \"scan_adk_zz500_cyb_spread_layer3_target_vol.py\"\n"
        "python \"scan_adk_zz500_cyb_spread_layer3_target_vol.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"layer3_target_vol_complete_not_promoted\" --stability-label \"target_vol_width_and_deadband_pending_user_confirmation\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict \"{RUN_DIR}\"\n",
        encoding="utf-8",
    )

    cols = [
        "candidate",
        "layer2_anchor",
        "role",
        "target_vol",
        "vol_window",
        "max_leverage",
        "min_scale",
        "deadband_mode",
        "deadband_value",
        "ann_return_full",
        "max_dd_full",
        "full_ann_loss_pp",
        "full_dd_improve_pp",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "last_5y_ann_loss_pp",
        "last_5y_dd_improve_pp",
        "ann_return_last_1y",
        "max_dd_last_1y",
        "scale_change_frequency_full",
        "small_scale_change_frequency_full",
    ]
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_tier[tier])}")
        print(top_tier[tier][cols].head(12).to_string(index=False) if not top_tier[tier].empty else "NONE")
    print(f"STRICT_FULL_PASS_COUNT={len(strict_full)}")
    print(strict_full[cols].head(12).to_string(index=False) if not strict_full.empty else "NONE")
    print(f"STRICT_FULL_5Y_PASS_COUNT={len(strict_full_5y)}")
    print(strict_full_5y[cols].head(12).to_string(index=False) if not strict_full_5y.empty else "NONE")
    print("CARRY")
    print(carry[cols].head(12).to_string(index=False) if not carry.empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

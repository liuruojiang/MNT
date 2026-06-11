"""Layer 3 target-vol + scale-deadband scan for long SZ50 / short ZZ500.

Inputs are the width-supported Layer 2 carry lines. This layer scans target-vol
sizing only: target volatility, realized-vol window, max leverage, and the
minimum scale-change deadband required before changing live exposure.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_sz50_zz500_spread_layer1_dense_patch as l1dense
import scan_adk_sz50_zz500_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_sz50_zz500_spread_long_only_v77_adk_spread_layer3_target_vol_deadband_after_l2"

LINES = [
    {
        "line": "primary_65_16_s1_abs45_m1p5",
        "line_role": "primary_l2_carry",
        "bias_ma": 65,
        "mom_day": 16,
        "weight_end": 2.75,
        "score_threshold": 1.0,
        "abs_ma": 45,
        "abs_threshold": -0.015,
        "layer2_candidate": "l2_bias_65_16_we2p75_score1_abs45_gt_m1p5pct",
    },
    {
        "line": "confirm_65_16_s1_abs40_0",
        "line_role": "nearby_confirmation",
        "bias_ma": 65,
        "mom_day": 16,
        "weight_end": 2.75,
        "score_threshold": 1.0,
        "abs_ma": 40,
        "abs_threshold": 0.0,
        "layer2_candidate": "l2_bias_65_16_we2p75_score1_abs40_gt_0pct",
    },
    {
        "line": "confirm_60_16_s1_abs55_m2p5",
        "line_role": "width_confirmation",
        "bias_ma": 60,
        "mom_day": 16,
        "weight_end": 2.75,
        "score_threshold": 1.0,
        "abs_ma": 55,
        "abs_threshold": -0.025,
        "layer2_candidate": "l2_bias_60_16_we2p75_score1_abs55_gt_m2p5pct",
    },
    {
        "line": "return_60_18_sm1_abs30_0p5",
        "line_role": "return_heavy_watch",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.75,
        "score_threshold": -1.0,
        "abs_ma": 30,
        "abs_threshold": 0.005,
        "layer2_candidate": "l2_bias_60_18_we2p75_return_heavy_scorem1_abs30_gt_0p5pct",
    },
    {
        "line": "return_60_18_s0_abs80_m5",
        "line_role": "return_confirmation",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.75,
        "score_threshold": 0.0,
        "abs_ma": 80,
        "abs_threshold": -0.050,
        "layer2_candidate": "l2_bias_60_18_we2p75_return_heavy_score0_abs80_gt_m5pct",
    },
    {
        "line": "balanced_65_18_s0p5_abs55_m2p5",
        "line_role": "balanced_watch",
        "bias_ma": 65,
        "mom_day": 18,
        "weight_end": 2.75,
        "score_threshold": 0.5,
        "abs_ma": 55,
        "abs_threshold": -0.025,
        "layer2_candidate": "l2_bias_65_18_we2p75_score0p5_abs55_gt_m2p5pct",
    },
]

TARGET_VOLS = [0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18]
VOL_WINDOWS = [20, 30, 40, 60, 90]
MAX_LEVERAGES = [1.0, 1.25, 1.5]
SCALE_DEADBANDS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
MIN_LEVERAGE = 0.10
PRACTICAL_MAX_SCALE_ADJUST_DAYS_PER_YEAR = 20.0
PRACTICAL_MIN_SCALE_ADJUST_REDUCTION = 0.40
PRACTICAL_MAX_FULL_ANN_LOSS_PP = 2.0
LOSS_TIERS = [1.0, 2.0, 3.0]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def load_panel() -> tuple[object, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    mod = base.load_v77()
    sz50 = mod._load_cn_official_cache(mod.CN_DK_SZ50_SECID).rename(columns={"close": "SZ50"})
    zz500 = mod._load_cn_official_cache(mod.CN_DK_ZZ500_SECID).rename(columns={"close": "ZZ500"})
    panel = pd.concat([sz50["SZ50"], zz500["ZZ500"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["SZ50"] / panel["ZZ500"]
    panel["spread_return"] = panel["SZ50"].pct_change().fillna(0.0) - panel["ZZ500"].pct_change().fillna(0.0)
    return mod, sz50, zz500, panel


def line_signal(panel: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    ratio = panel["ratio"]
    feature = ratio / ratio.rolling(int(line["bias_ma"])).mean() - 1.0
    score, r2 = l1dense.fast_weighted_slope_and_r2(
        feature,
        int(line["mom_day"]),
        float(line["weight_end"]),
    )
    abs_bias = ratio / ratio.rolling(int(line["abs_ma"])).mean() - 1.0
    raw_signal = (
        (score > float(line["score_threshold"]))
        & (r2 >= 0.05)
        & (abs_bias > float(line["abs_threshold"]))
    ).astype(float)
    exec_signal = raw_signal.shift(1).fillna(0.0)
    warmup = max(int(line["bias_ma"]), int(line["mom_day"]), int(line["abs_ma"])) + 2
    return pd.DataFrame(
        {
            "signal": exec_signal,
            "score": score,
            "r2": r2,
            "abs_bias": abs_bias,
            "raw_signal": raw_signal,
        },
        index=panel.index,
    ).iloc[warmup:].copy()


def apply_scale_deadband(raw_scale: pd.Series, signal: pd.Series, threshold: float) -> pd.Series:
    applied: list[float] = []
    last_scale = 0.0
    for desired_raw, sig in zip(raw_scale.fillna(0.0).astype(float), signal.fillna(0.0).astype(float)):
        if sig <= 0:
            current = 0.0
        elif last_scale <= 0:
            current = float(desired_raw)
        elif abs(float(desired_raw) - last_scale) >= threshold - 1e-12:
            current = float(desired_raw)
        else:
            current = last_scale
        applied.append(current)
        last_scale = current
    return pd.Series(applied, index=raw_scale.index)


def returns_for(panel: pd.DataFrame, sig: pd.DataFrame, cand: dict[str, object]) -> pd.DataFrame:
    d = pd.concat([sig, panel[["spread_return", "ratio"]]], axis=1).dropna().copy()
    if not bool(cand["tv_enabled"]):
        raw_scale = pd.Series(1.0, index=d.index)
        applied_scale = d["signal"].copy()
        realized_vol = d["spread_return"].rolling(40).std() * np.sqrt(base.ANNUALIZATION_DAYS)
        raw_weight = d["signal"]
    else:
        realized_vol = d["spread_return"].rolling(int(cand["vol_window"])).std() * np.sqrt(base.ANNUALIZATION_DAYS)
        raw_scale = (
            (float(cand["target_vol"]) / realized_vol)
            .clip(MIN_LEVERAGE, float(cand["max_leverage"]))
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
        )
        applied_scale = apply_scale_deadband(raw_scale, d["signal"], float(cand["scale_deadband"]))
        raw_weight = d["signal"] * raw_scale

    weight = d["signal"] * applied_scale
    turnover = weight.diff().abs().fillna(weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = weight * d["spread_return"]
    ret = gross_return - cost

    holding = d["signal"] > 0
    scale_diff = applied_scale.diff().abs().fillna(applied_scale.abs())
    raw_scale_diff = raw_scale.diff().abs().fillna(raw_scale.abs())
    scale_adjust_day = holding & (scale_diff > 1e-12)
    raw_scale_adjust_day = holding & (raw_scale_diff > 1e-12)
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": weight,
            "base_signal": d["signal"],
            "raw_weight": raw_weight,
            "raw_scale": raw_scale,
            "applied_scale": applied_scale,
            "realized_vol": realized_vol,
            "score": d["score"],
            "r2": d["r2"],
            "abs_bias": d["abs_bias"],
            "ratio": d["ratio"],
            "spread_return": d["spread_return"],
            "scale_adjust_day": scale_adjust_day.astype(int),
            "raw_scale_adjust_day": raw_scale_adjust_day.astype(int),
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for line in LINES:
        grid.append(
            {
                **line,
                "candidate": f"l3_{line['line']}_tv_off",
                "target_vol": 0.0,
                "vol_window": 0,
                "max_leverage": 1.0,
                "scale_deadband": 0.0,
                "tv_enabled": False,
            }
        )
        for target_vol in TARGET_VOLS:
            for vol_window in VOL_WINDOWS:
                for max_leverage in MAX_LEVERAGES:
                    for deadband in SCALE_DEADBANDS:
                        grid.append(
                            {
                                **line,
                                "candidate": (
                                    f"l3_{line['line']}_tv{fmt_num(target_vol, True)}"
                                    f"_vw{vol_window}_max{fmt_num(max_leverage)}_db{fmt_num(deadband)}"
                                ),
                                "target_vol": target_vol,
                                "vol_window": vol_window,
                                "max_leverage": max_leverage,
                                "scale_deadband": deadband,
                                "tv_enabled": True,
                            }
                        )
    return grid


def extra_metrics_for_segment(result: pd.DataFrame, years: int | None) -> dict[str, float]:
    if years is None:
        d = result.copy()
    else:
        cutoff = result.index.max() - pd.DateOffset(years=years)
        d = result.loc[result.index >= cutoff].copy()
    if d.empty:
        return {
            "avg_scale": 0.0,
            "avg_active_scale": 0.0,
            "scale_adjust_days": 0.0,
            "raw_scale_adjust_days": 0.0,
            "scale_adjust_days_per_year": 0.0,
            "raw_scale_adjust_days_per_year": 0.0,
            "scale_adjust_reduction_pct_segment": 0.0,
            "avg_cost_per_year": 0.0,
        }
    years_len = len(d) / base.ANNUALIZATION_DAYS
    holding = d["base_signal"] > 0
    active_scale = d.loc[holding, "applied_scale"]
    scale_adjust_days = float(d["scale_adjust_day"].sum())
    raw_scale_adjust_days = float(d["raw_scale_adjust_day"].sum())
    return {
        "avg_scale": float(d["applied_scale"].mean()),
        "avg_active_scale": float(active_scale.mean()) if not active_scale.empty else 0.0,
        "scale_adjust_days": scale_adjust_days,
        "raw_scale_adjust_days": raw_scale_adjust_days,
        "scale_adjust_days_per_year": scale_adjust_days / years_len if years_len > 0 else 0.0,
        "raw_scale_adjust_days_per_year": raw_scale_adjust_days / years_len if years_len > 0 else 0.0,
        "scale_adjust_reduction_pct_segment": 1.0 - scale_adjust_days / raw_scale_adjust_days if raw_scale_adjust_days > 0 else 0.0,
        "avg_cost_per_year": float(d["cost"].sum() / years_len) if years_len > 0 else 0.0,
    }


def add_baselines_and_flags(window_metrics: pd.DataFrame) -> pd.DataFrame:
    out = window_metrics.copy()
    baselines = out[out["tv_enabled"] == False].set_index("line")
    for col in [
        "ann_return_full",
        "max_dd_full",
        "ann_return_last_10y",
        "max_dd_last_10y",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "ann_return_last_3y",
        "max_dd_last_3y",
        "ann_return_last_1y",
        "max_dd_last_1y",
        "sharpe_repo_full",
        "cost_total_full",
        "avg_turnover_full",
        "scale_adjust_days_full",
        "raw_scale_adjust_days_full",
    ]:
        out[f"base_{col}"] = out["line"].map(baselines[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100.0
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100.0
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100.0
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100.0
    out["scale_adjust_reduction_pct"] = np.where(
        out["raw_scale_adjust_days_full"] > 0,
        1.0 - out["scale_adjust_days_full"] / out["raw_scale_adjust_days_full"],
        0.0,
    )
    out["cost_delta_pct"] = np.where(
        out["base_cost_total_full"] > 0,
        out["cost_total_full"] / out["base_cost_total_full"] - 1.0,
        0.0,
    )
    out["pass_full_ann_dd"] = (
        (out["tv_enabled"] == True)
        & (out["ann_return_full"] >= out["base_ann_return_full"] - 1e-12)
        & (out["max_dd_full"] >= out["base_max_dd_full"] - 1e-12)
    )
    out["pass_full_and_5y"] = (
        out["pass_full_ann_dd"]
        & (out["ann_return_last_5y"] >= out["base_ann_return_last_5y"] - 1e-12)
        & (out["max_dd_last_5y"] >= out["base_max_dd_last_5y"] - 1e-12)
    )
    out["practical_pass"] = (
        (out["tv_enabled"] == True)
        & (out["scale_deadband"] > 0)
        & (out["full_ann_loss_pp"] <= PRACTICAL_MAX_FULL_ANN_LOSS_PP + 1e-12)
        & (out["full_dd_improve_pp"] > 0)
        & (out["fivey_dd_improve_pp"] >= -1e-12)
        & (out["scale_adjust_days_per_year_full"] <= PRACTICAL_MAX_SCALE_ADJUST_DAYS_PER_YEAR)
        & (out["scale_adjust_reduction_pct"] >= PRACTICAL_MIN_SCALE_ADJUST_REDUCTION)
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            (out["tv_enabled"] == True)
            & (out["scale_deadband"] > 0)
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["fivey_dd_improve_pp"] >= -1e-12)
            & (out["scale_adjust_reduction_pct"] >= PRACTICAL_MIN_SCALE_ADJUST_REDUCTION)
        )
    return out


def patch_summary(window_metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    source = window_metrics[window_metrics["tv_enabled"] == True].copy()
    rules = ["pass_full_ann_dd", "pass_full_and_5y", "practical_pass", "pass_loss_le_1p0pp", "pass_loss_le_2p0pp", "pass_loss_le_3p0pp"]
    for pass_col in rules:
        for line, group in source.groupby("line"):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": pass_col,
                        "line": line,
                        "pass_count": 0,
                        "target_vol_count": 0,
                        "vol_window_count": 0,
                        "max_leverage_count": 0,
                        "deadband_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "best_scale_adjust_days_per_year": np.nan,
                        "best_scale_adjust_reduction_pct": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(
                ["full_dd_improve_pp", "ann_return_full", "scale_adjust_days_per_year_full"],
                ascending=[False, False, True],
            ).iloc[0]
            patch_like = bool(
                len(passed) >= 4
                and passed["target_vol"].nunique() >= 2
                and passed["vol_window"].nunique() >= 2
                and passed["scale_deadband"].nunique() >= 2
            )
            rows.append(
                {
                    "pass_rule": pass_col,
                    "line": line,
                    "pass_count": int(len(passed)),
                    "target_vol_count": int(passed["target_vol"].nunique()),
                    "vol_window_count": int(passed["vol_window"].nunique()),
                    "max_leverage_count": int(passed["max_leverage"].nunique()),
                    "deadband_count": int(passed["scale_deadband"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                    "best_full_dd_improve_pp": best["full_dd_improve_pp"],
                    "best_5y_ann_return": best["ann_return_last_5y"],
                    "best_5y_max_dd": best["max_dd_last_5y"],
                    "best_scale_adjust_days_per_year": best["scale_adjust_days_per_year_full"],
                    "best_scale_adjust_reduction_pct": best["scale_adjust_reduction_pct"],
                    "patch_like": patch_like,
                }
            )
    return pd.DataFrame(rows).sort_values(["pass_rule", "patch_like", "pass_count"], ascending=[True, False, False])


def compact_daily(curves: dict[str, pd.DataFrame], selected_names: set[str]) -> pd.DataFrame:
    rows = []
    for name in sorted(selected_names):
        curve = curves.get(name)
        if curve is None:
            continue
        out = curve.copy()
        out["nav"] = (1.0 + out["return"]).cumprod()
        out["candidate"] = name
        rows.append(out.reset_index(names="date"))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, sz50, zz500, panel = load_panel()
    signals = {str(line["line"]): line_signal(panel, line) for line in LINES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    grid = make_grid()
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    curves: dict[str, pd.DataFrame] = {}

    for cand in grid:
        result = returns_for(panel, signals[str(cand["line"])], cand)
        wide = {**cand}
        for segment, years in base.SEGMENTS:
            metrics = base.metrics_for_segment(result, segment, years)
            extras = extra_metrics_for_segment(result, years)
            long_rows.append({**cand, **metrics, **extras})
            for key in [
                "ann_return",
                "ann_vol",
                "max_dd",
                "sharpe_repo",
                "avg_weight",
                "avg_turnover",
                "holding_day_ratio",
                "cost_total",
                "avg_scale",
                "avg_active_scale",
                "scale_adjust_days",
                "raw_scale_adjust_days",
                "scale_adjust_days_per_year",
                "raw_scale_adjust_days_per_year",
                "avg_cost_per_year",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
            wide[f"scale_adjust_reduction_pct_{segment}"] = extras["scale_adjust_reduction_pct_segment"]
        wide_rows.append(wide)
        if not bool(cand["tv_enabled"]):
            curves[str(cand["candidate"])] = result

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    full_pass = window_metrics[(window_metrics["tv_enabled"] == True) & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[(window_metrics["tv_enabled"] == True) & window_metrics["pass_full_and_5y"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    practical = window_metrics[(window_metrics["tv_enabled"] == True) & window_metrics["practical_pass"]].sort_values(
        ["full_dd_improve_pp", "ann_return_full", "scale_adjust_days_per_year_full"],
        ascending=[False, False, True],
    )

    selected_names = set(window_metrics[window_metrics["tv_enabled"] == False]["candidate"].astype(str).tolist())
    for df in [full_pass, strict_pass, practical]:
        selected_names.update(df.head(20)["candidate"].astype(str).tolist())
    selected_grid = {str(cand["candidate"]): cand for cand in grid if str(cand["candidate"]) in selected_names}
    for name, cand in selected_grid.items():
        if name not in curves:
            curves[name] = returns_for(panel, signals[str(cand["line"])], cand)
    daily = compact_daily(curves, selected_names)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")
    practical.to_csv(RUN_DIR / "practical_candidates.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")

    cols = [
        "candidate",
        "line",
        "target_vol",
        "vol_window",
        "max_leverage",
        "scale_deadband",
        "ann_return_full",
        "max_dd_full",
        "ann_return_last_10y",
        "max_dd_last_10y",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "ann_return_last_3y",
        "max_dd_last_3y",
        "ann_return_last_1y",
        "max_dd_last_1y",
        "avg_active_scale_full",
        "scale_adjust_days_per_year_full",
        "scale_adjust_reduction_pct",
        "cost_total_full",
        "full_ann_loss_pp",
        "full_dd_improve_pp",
        "practical_pass",
    ]
    display_cols = [c for c in cols if c in window_metrics.columns]
    baseline = window_metrics[window_metrics["tv_enabled"] == False][display_cols]
    record_lines = [
        "# SZ50/ZZ500 Layer 3 Target-Vol + Deadband Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer3_target_vol_deadband_complete_pending_user_review`",
        "- stability: `target_vol_deadband_practicality_review`",
        "",
        "## Research Question",
        "Scan target-vol sizing after Layer 2 score and absolute-bias filters for long SZ50 / short ZZ500.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
        "",
        "## Implementation Anchor",
        "- Imports data loader and metrics from `scan_adk_sz50_zz500_spread_long_only.py`.",
        "- Uses vectorized weighted-slope/R2 from `scan_adk_sz50_zz500_spread_layer1_dense_patch.py`.",
        "- Source-change rule: `research_only_no_source_change`.",
        "",
        "## Data Snapshot",
        f"- SZ50 publication date: {base.SZ50_PUBLICATION_DATE}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        f"- SZ50 rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- ZZ500 rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long SZ50 / short ZZ500; ratio is SZ50/ZZ500; spread return is SZ50 pct_change minus ZZ500 pct_change.",
        "- T close signal -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on exposure changes, including scale changes.",
        "- No NAV defense, overheat, amount/volume, or momentum-decay overlay is applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 3 target-vol scan.",
        "",
        "## Commands",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"SZ50/ZZ500 spread Layer 3 target vol\" --parameter-group \"target_vol_window_max_leverage_scale_deadband\" --repo . --entrypoint \"scan_adk_sz50_zz500_spread_layer3_target_vol.py\" --date 2026-06-12 --slug \"adk_sz50_zz500_spread_long_only_v77_adk_spread_layer3_target_vol_deadband_after_l2\"`",
        "- `python -m py_compile \"scan_adk_sz50_zz500_spread_layer3_target_vol.py\"`",
        "- `python \"scan_adk_sz50_zz500_spread_layer3_target_vol.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `full_baseline_pass_candidates.csv`",
        "- `full_and_5y_pass_candidates.csv`",
        "- `practical_candidates.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        baseline.to_markdown(index=False),
        "",
        "## Window Results",
        strict_pass[display_cols].head(20).to_markdown(index=False) if not strict_pass.empty else "No target-vol candidate passed full+5Y baseline comparison.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 3 completed and stopped for user review before NAV-defense testing.",
        "",
        "## User-Facing Summary",
        f"- candidates_scanned: {len(grid)}",
        f"- full_baseline_pass_count: {len(full_pass)}",
        f"- full_and_5y_pass_count: {len(strict_pass)}",
        f"- practical_pass_count: {len(practical)}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    git_status_after = base.git_text(["status", "--short"])
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "SZ50/ZZ500 spread Layer 3 target vol",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_sz50_zz500_spread_long_only.py + scan_adk_sz50_zz500_spread_layer1_dense_patch.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": git_status_after,
        "scan_type": "fresh_layer3_target_vol_deadband",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "target_vol_window_max_leverage_scale_deadband",
        "baseline": {"lines": LINES, "pass_rule": "compare every target-vol candidate with its own tv_off line"},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "publication_dates": {"SZ50": base.SZ50_PUBLICATION_DATE, "ZZ500": base.ZZ500_PUBLICATION_DATE},
        },
        "practical_rule": {
            "scale_deadband_gt": 0,
            "max_full_ann_loss_pp": PRACTICAL_MAX_FULL_ANN_LOSS_PP,
            "full_dd_improve_gt_pp": 0,
            "fivey_dd_not_worse": True,
            "max_scale_adjust_days_per_year": PRACTICAL_MAX_SCALE_ADJUST_DAYS_PER_YEAR,
            "min_scale_adjust_reduction_pct": PRACTICAL_MIN_SCALE_ADJUST_REDUCTION,
        },
        "decision": "layer3_target_vol_deadband_complete_pending_user_review",
        "stability_label": "target_vol_deadband_practicality_review",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "practical_candidates": str(RUN_DIR / "practical_candidates.csv"),
            "full_baseline_pass_candidates": str(RUN_DIR / "full_baseline_pass_candidates.csv"),
            "full_and_5y_pass_candidates": str(RUN_DIR / "full_and_5y_pass_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "\n".join(
            [
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "SZ50/ZZ500 spread Layer 3 target vol" --parameter-group "target_vol_window_max_leverage_scale_deadband" --repo . --entrypoint "scan_adk_sz50_zz500_spread_layer3_target_vol.py" --date 2026-06-12 --slug "adk_sz50_zz500_spread_long_only_v77_adk_spread_layer3_target_vol_deadband_after_l2"',
                'python -m py_compile "scan_adk_sz50_zz500_spread_layer3_target_vol.py"',
                'python "scan_adk_sz50_zz500_spread_layer3_target_vol.py"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "{RUN_DIR}" --decision "layer3_target_vol_deadband_complete_pending_user_review" --stability-label "target_vol_deadband_practicality_review"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict "{RUN_DIR}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(f"FULL_PASS_COUNT={len(full_pass)} STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)} PRACTICAL_PASS_COUNT={len(practical)}")
    print("BASELINES")
    print(baseline.to_string(index=False))
    print("PRACTICAL_TOP")
    print(practical[display_cols].head(20).to_string(index=False) if not practical.empty else "NONE")
    print("STRICT_PASS_TOP")
    print(strict_pass[display_cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

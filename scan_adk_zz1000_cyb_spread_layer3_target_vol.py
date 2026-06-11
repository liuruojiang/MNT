"""Layer 3 target-vol + leverage-deadband scan for long ZZ1000 / short CYB.

This layer follows the updated workflow requirement: when target-vol leverage is
used, scan the scale-change deadband in the same layer so candidates are judged
on an executable exposure path.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_zz1000_spread_long_only as metric_base
import scan_adk_zz1000_cyb_spread_layer1_dense_patch as l1dense
import scan_adk_zz1000_cyb_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260611_adk_zz1000_cyb_spread_long_only_v77_adk_spread_layer3_target_vol_deadband_after_l2_score_abs"

LINES = [
    {
        "line": "primary_s2_abs70_m7",
        "line_role": "primary_l2_carry",
        "bias_ma": 60,
        "mom_day": 12,
        "weight_end": 2.0,
        "score_threshold": 2.0,
        "abs_ma": 70,
        "abs_threshold": -0.070,
    },
    {
        "line": "confirm_s2_abs65_m6p5",
        "line_role": "width_confirmation",
        "bias_ma": 60,
        "mom_day": 12,
        "weight_end": 2.0,
        "score_threshold": 2.0,
        "abs_ma": 65,
        "abs_threshold": -0.065,
    },
    {
        "line": "confirm_s2_abs75_m7p5",
        "line_role": "width_confirmation",
        "bias_ma": 60,
        "mom_day": 12,
        "weight_end": 2.0,
        "score_threshold": 2.0,
        "abs_ma": 75,
        "abs_threshold": -0.075,
    },
    {
        "line": "watch35_s0_abs65_m1p5",
        "line_role": "original_width_watchlist",
        "bias_ma": 35,
        "mom_day": 21,
        "weight_end": 3.0,
        "score_threshold": 0.0,
        "abs_ma": 65,
        "abs_threshold": -0.015,
    },
]

TARGET_VOLS = [0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18]
VOL_WINDOWS = [20, 30, 40, 60, 90]
MAX_LEVERAGES = [1.0, 1.25, 1.5]
SCALE_DEADBANDS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
MIN_LEVERAGE = 0.10
LOSS_TIERS = [1.0, 2.0, 3.0]


def fmt(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def load_panel() -> tuple[object, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    mod = base.load_v77()
    zz1000 = mod._load_cn_official_cache(mod.CN_DK_ZZ1000_SECID).rename(columns={"close": "ZZ1000"})
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    panel = pd.concat([zz1000["ZZ1000"], cyb["CYB"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["ZZ1000"] / panel["CYB"]
    panel["spread_return"] = panel["ZZ1000"].pct_change().fillna(0.0) - panel["CYB"].pct_change().fillna(0.0)
    return mod, zz1000, cyb, panel


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
    d = pd.concat([sig, panel[["spread_return"]]], axis=1).dropna().copy()
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

    scale_diff = applied_scale.diff().abs().fillna(applied_scale.abs())
    raw_scale_diff = raw_scale.diff().abs().fillna(raw_scale.abs())
    holding = d["signal"] > 0
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
        for tv in TARGET_VOLS:
            for vw in VOL_WINDOWS:
                for max_lev in MAX_LEVERAGES:
                    for deadband in SCALE_DEADBANDS:
                        grid.append(
                            {
                                **line,
                                "candidate": (
                                    f"l3_{line['line']}_tv{fmt(tv, True)}"
                                    f"_vw{vw}_max{fmt(max_lev)}_db{fmt(deadband)}"
                                ),
                                "target_vol": tv,
                                "vol_window": vw,
                                "max_leverage": max_lev,
                                "scale_deadband": deadband,
                                "tv_enabled": True,
                            }
                        )
    return grid


def segment_stats(result: pd.DataFrame, years: int | None) -> pd.DataFrame:
    if years is None:
        return result
    cutoff = result.index.max() - pd.DateOffset(years=years)
    return result.loc[result.index >= cutoff]


def add_baselines_and_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    baselines = out[out["tv_enabled"] == False].set_index("line")
    for col in [
        "ann_return_full",
        "max_dd_full",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "sharpe_repo_full",
        "scale_adjust_days_full",
        "cost_total_full",
        "avg_turnover_full",
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
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            (out["tv_enabled"] == True)
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["fivey_dd_improve_pp"] >= -1e-12)
        )
    out["pass_practical"] = (
        (out["tv_enabled"] == True)
        & (out["scale_deadband"] > 0)
        & (out["pass_loss_le_2p0pp"])
        & (out["scale_adjust_days_per_year_full"] <= 20.0)
        & (out["scale_adjust_reduction_pct"] >= 0.40)
    )
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    tv_rows = wm[wm["tv_enabled"] == True]
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for line, group in tv_rows.groupby("line"):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "loss_tier_pp": tier,
                        "line": line,
                        "pass_count": 0,
                        "target_vol_count": 0,
                        "window_count": 0,
                        "maxlev_count": 0,
                        "deadband_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_scale_adjust_days_per_year": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(
                ["full_dd_improve_pp", "ann_return_full", "scale_adjust_reduction_pct"],
                ascending=[False, False, False],
            ).iloc[0]
            patch_like = bool(
                len(passed) >= 8
                and passed["target_vol"].nunique() >= 2
                and passed["vol_window"].nunique() >= 2
                and passed["scale_deadband"].nunique() >= 2
            )
            rows.append(
                {
                    "loss_tier_pp": tier,
                    "line": line,
                    "pass_count": int(len(passed)),
                    "target_vol_count": int(passed["target_vol"].nunique()),
                    "window_count": int(passed["vol_window"].nunique()),
                    "maxlev_count": int(passed["max_leverage"].nunique()),
                    "deadband_count": int(passed["scale_deadband"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                    "best_full_dd_improve_pp": best["full_dd_improve_pp"],
                    "best_scale_adjust_days_per_year": best["scale_adjust_days_per_year_full"],
                    "patch_like": patch_like,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def window_table(df: pd.DataFrame, n: int = 12) -> str:
    cols = ["candidate", "line", "target_vol", "vol_window", "max_leverage", "scale_deadband"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    mod, zz1000, cyb, panel = load_panel()
    signals = {line["line"]: line_signal(panel, line) for line in LINES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = make_grid()
    long_rows = []
    wide_rows = []
    curves: dict[str, pd.DataFrame] = {}

    for cand in grid:
        result = returns_for(panel, signals[str(cand["line"])], cand)
        wide = {**cand}
        for segment, years in base.SEGMENTS:
            metrics = metric_base.metrics_for_segment(result, segment, years)
            seg_df = segment_stats(result, years)
            metrics["scale_adjust_days"] = int(seg_df["scale_adjust_day"].sum())
            metrics["raw_scale_adjust_days"] = int(seg_df["raw_scale_adjust_day"].sum())
            metrics["scale_adjust_days_per_year"] = float(
                seg_df["scale_adjust_day"].sum() / max(len(seg_df), 1) * base.ANNUALIZATION_DAYS
            )
            metrics["raw_scale_adjust_days_per_year"] = float(
                seg_df["raw_scale_adjust_day"].sum() / max(len(seg_df), 1) * base.ANNUALIZATION_DAYS
            )
            metrics["avg_applied_scale_when_holding"] = (
                float(seg_df.loc[seg_df["base_signal"] > 0, "applied_scale"].mean())
                if (seg_df["base_signal"] > 0).any()
                else 0.0
            )
            metrics["avg_raw_scale_when_holding"] = (
                float(seg_df.loc[seg_df["base_signal"] > 0, "raw_scale"].mean())
                if (seg_df["base_signal"] > 0).any()
                else 0.0
            )
            long_rows.append({**cand, **metrics})
            for key in [
                "ann_return",
                "max_dd",
                "sharpe_repo",
                "avg_weight",
                "avg_turnover",
                "holding_day_ratio",
                "cost_total",
                "scale_adjust_days",
                "raw_scale_adjust_days",
                "scale_adjust_days_per_year",
                "raw_scale_adjust_days_per_year",
                "avg_applied_scale_when_holding",
                "avg_raw_scale_when_holding",
            ]:
                wide[f"{key}_{segment}"] = metrics[key]
        wide_rows.append(wide)
        if (not bool(cand["tv_enabled"])) or bool(cand.get("scale_deadband", 0.0) in (0.0, 0.15, 0.25)):
            curves[str(cand["candidate"])] = result

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    practical = window_metrics[window_metrics["pass_practical"]].sort_values(
        ["full_dd_improve_pp", "ann_return_full", "scale_adjust_days_per_year_full"],
        ascending=[False, False, True],
    )
    full_pass = window_metrics[window_metrics["pass_full_ann_dd"]].sort_values(
        ["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[window_metrics["pass_full_and_5y"]].sort_values(
        ["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]
    )
    top_tier: dict[float, pd.DataFrame] = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(
            ["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]
        )
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_tier[tier] = passed

    selected_names = set()
    for df in [practical, strict_pass, *top_tier.values()]:
        selected_names.update(df.head(12)["candidate"].astype(str).tolist())
    selected_lookup = {cand["candidate"]: cand for cand in grid if str(cand["candidate"]) in selected_names}
    for name, cand in selected_lookup.items():
        if name not in curves:
            curves[name] = returns_for(panel, signals[str(cand["line"])], cand)
    daily_parts = []
    for name, curve in curves.items():
        daily = curve.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = name
        daily_parts.append(daily.reset_index(names="date"))
    daily_curves = pd.concat(daily_parts, ignore_index=True)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    practical.to_csv(RUN_DIR / "practical_candidates.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")
    daily_curves.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")

    cols = [
        "candidate",
        "line",
        "line_role",
        "target_vol",
        "vol_window",
        "max_leverage",
        "scale_deadband",
        "ann_return_full",
        "max_dd_full",
        "full_ann_loss_pp",
        "full_dd_improve_pp",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "fivey_ann_loss_pp",
        "fivey_dd_improve_pp",
        "scale_adjust_days_per_year_full",
        "raw_scale_adjust_days_per_year_full",
        "scale_adjust_reduction_pct",
        "cost_total_full",
        "avg_applied_scale_when_holding_full",
    ]
    record_lines = [
        "# ZZ1000/CYB Layer 3 Target-Vol And Deadband Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer3_target_vol_deadband_complete_not_promoted`",
        "- stability: `target_vol_deadband_practicality_review`",
        "",
        "## Research Question",
        "Scan target-vol sizing and scale-change deadband after Layer 2 score/absolute-bias filters.",
        "",
        "## Implementation Anchor",
        "- Data loader and formal sample from `scan_adk_zz1000_cyb_spread_long_only.py`.",
        "- Vectorized weighted-slope/r2 from `scan_adk_zz1000_cyb_spread_layer1_dense_patch.py`.",
        "- Layer 2 lines from `scan_adk_zz1000_cyb_spread_layer2_score_abs_filter.py`.",
        "",
        "## Data Snapshot",
        f"- ZZ1000 rows: {len(zz1000)}, start {zz1000.index.min().date()}, end {zz1000.index.max().date()}.",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start: `2014-10-17`, constrained by CSI 1000 publication date.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal -> T+1 close-to-close spread return.",
        "- Return stream: ZZ1000 close-to-close return minus CYB close-to-close return.",
        "- Two-leg transaction cost with one-way commission 0.0005 on scaled exposure changes.",
        "- Deadband semantics: during active holding, keep last target-vol scale unless absolute raw-scale change reaches the threshold; entries and exits still execute.",
        "- No NAV defense, overheat, amount, volume, or momentum-decay overlay is applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 3 scan.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_zz1000_cyb_spread_layer3_target_vol.py\"`",
        "- `python \"scan_adk_zz1000_cyb_spread_layer3_target_vol.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `practical_candidates.csv`",
        "- `full_baseline_pass_candidates.csv`",
        "- `full_and_5y_pass_candidates.csv`",
        "- `dd_first_pass_loss_le_1p0pp.csv`",
        "- `dd_first_pass_loss_le_2p0pp.csv`",
        "- `dd_first_pass_loss_le_3p0pp.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        practical[cols].head(20).to_markdown(index=False)
        if not practical.empty
        else "No practical candidates passed the current screen.",
        "",
        "## Window Results",
        window_table(practical, 12) if not practical.empty else "No practical candidates passed the current screen.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 3 completed but not promoted. Stop for user review before NAV-defense layer.",
        "",
        "## User-Facing Summary",
        f"- strict full+5Y pass count: {len(strict_pass)}",
        f"- practical pass count: {len(practical)}",
        f"- loss<=1pp pass count: {len(top_tier[1.0])}",
        f"- loss<=2pp pass count: {len(top_tier[2.0])}",
        f"- loss<=3pp pass count: {len(top_tier[3.0])}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz1000_cyb_spread_long_only.py",
        "git_branch": "dirty_worktree_not_cleaned",
        "git_commit": "not_recorded",
        "git_status_before": "dirty_worktree_with_prior_research_artifacts",
        "git_status_after": "dirty_worktree_with_prior_research_artifacts",
        "scan_type": "layer3_target_vol_with_scale_deadband",
        "parameter_group": "target_vol_window_max_leverage_scale_deadband",
        "baseline": {"lines": LINES, "loss_tiers_pp": LOSS_TIERS},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal -> T+1 close-to-close return",
            "deadband_semantics": "absolute scale change threshold during active holdings",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "zz1000": {
                "secid": str(mod.CN_DK_ZZ1000_SECID),
                "rows": int(len(zz1000)),
                "start": str(zz1000.index.min().date()),
                "end": str(zz1000.index.max().date()),
                "publication_date": "2014-10-17",
            },
            "cyb": {
                "secid": str(mod.CN_DK_CYB_SECID),
                "rows": int(len(cyb)),
                "start": str(cyb.index.min().date()),
                "end": str(cyb.index.max().date()),
            },
            "formal": {
                "rows": int(len(panel)),
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
                "start_rule": "latest actual publication/listing date; ZZ1000 publication 2014-10-17",
            },
        },
        "decision": "layer3_target_vol_deadband_complete_not_promoted",
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
        "python -m py_compile \"scan_adk_zz1000_cyb_spread_layer3_target_vol.py\"\n"
        "python \"scan_adk_zz1000_cyb_spread_layer3_target_vol.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("PRACTICAL")
    print(practical[cols].head(30).to_string(index=False) if not practical.empty else "NONE")
    print("STRICT_FULL_5Y")
    print(strict_pass[cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

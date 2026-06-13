"""Layer 4 NAV drawdown defense after Layer 3 target-vol for HS300/ZZ500.

Uses prior-row pre-overlay candidate NAV drawdown. If prior drawdown is below
the threshold, next execution exposure is multiplied by defense_scale and costs
are recalculated on final exposure changes.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_hs300_zz500_spread_layer2_score_abs_filter as l2
import scan_adk_hs300_zz500_spread_layer3_target_vol as l3
import scan_adk_hs300_zz500_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_hs300_zz500_spread_long_only_v77_adk_spread_layer4_nav_defense_after_l3_target_vol"

LINES = [
    {
        "line": "primary_tv12_rv20_max2_floor0_dbrel15",
        "line_role": "primary_strict_full_5y",
        "layer2_anchor": "primary_60_18_we2p5_s0_abs30_m0p5",
        "layer2_candidate": "l2_bias_60_18_we2p5_score0_abs30_gt_m0p5pct",
        "anchor": "bias_60_18_we2p5",
        "family": "bias_momentum",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.5,
        "layer1_candidate": "dense_bias_ma060_mom018_we2p5_gt0",
        "score_threshold": 0.0,
        "abs_ma": 30,
        "abs_threshold": -0.005,
        "abs_filter": "ratio_bias",
        "target_vol": 0.12,
        "vol_window": 20,
        "max_leverage": 2.0,
        "min_scale": 0.0,
        "deadband_mode": "rel",
        "deadband_value": 0.15,
        "target_vol_enabled": True,
        "layer3_candidate": "l3_primary_60_18_we2p5_s0_abs30_m0p5_tv12_rv20_max2_floor0_dbrel15",
    },
    {
        "line": "confirm_tv12_rv20_max2_floor0_dbrel20",
        "line_role": "same_anchor_confirmation",
        "layer2_anchor": "confirm_60_18_we2p5_s0_abs50_m1p5",
        "layer2_candidate": "l2_bias_60_18_we2p5_score0_abs50_gt_m1p5pct",
        "anchor": "bias_60_18_we2p5",
        "family": "bias_momentum",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.5,
        "layer1_candidate": "dense_bias_ma060_mom018_we2p5_gt0",
        "score_threshold": 0.0,
        "abs_ma": 50,
        "abs_threshold": -0.015,
        "abs_filter": "ratio_bias",
        "target_vol": 0.12,
        "vol_window": 20,
        "max_leverage": 2.0,
        "min_scale": 0.0,
        "deadband_mode": "rel",
        "deadband_value": 0.20,
        "target_vol_enabled": True,
        "layer3_candidate": "l3_confirm_60_18_we2p5_s0_abs50_m1p5_tv12_rv20_max2_floor0_dbrel20",
    },
    {
        "line": "nearby_tv12_rv20_max2_floor0_dbrel20",
        "line_role": "nearby_width_confirmation",
        "layer2_anchor": "confirm_60_17_we2p5_s0_abs70_m5",
        "layer2_candidate": "l2_bias_60_17_we2p5_score0_abs70_gt_m5pct",
        "anchor": "bias_60_17_we2p5",
        "family": "bias_momentum",
        "bias_ma": 60,
        "mom_day": 17,
        "weight_end": 2.5,
        "layer1_candidate": "dense_bias_ma060_mom017_we2p5_gt0",
        "score_threshold": 0.0,
        "abs_ma": 70,
        "abs_threshold": -0.050,
        "abs_filter": "ratio_bias",
        "target_vol": 0.12,
        "vol_window": 20,
        "max_leverage": 2.0,
        "min_scale": 0.0,
        "deadband_mode": "rel",
        "deadband_value": 0.20,
        "target_vol_enabled": True,
        "layer3_candidate": "l3_confirm_60_17_we2p5_s0_abs70_m5_tv12_rv20_max2_floor0_dbrel20",
    },
    {
        "line": "watch_tv12_rv20_max2_floor0_dbrel20",
        "line_role": "higher_weight_watchlist",
        "layer2_anchor": "watch_60_18_we2p75_s0_abs75_m5p5",
        "layer2_candidate": "l2_bias_60_18_we2p75_score0_abs75_gt_m5p5pct",
        "anchor": "bias_60_18_we2p75",
        "family": "bias_momentum",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.75,
        "layer1_candidate": "dense_bias_ma060_mom018_we2p75_gt0",
        "score_threshold": 0.0,
        "abs_ma": 75,
        "abs_threshold": -0.055,
        "abs_filter": "ratio_bias",
        "target_vol": 0.12,
        "vol_window": 20,
        "max_leverage": 2.0,
        "min_scale": 0.0,
        "deadband_mode": "rel",
        "deadband_value": 0.20,
        "target_vol_enabled": True,
        "layer3_candidate": "l3_watch_60_18_we2p75_s0_abs75_m5p5_tv12_rv20_max2_floor0_dbrel20",
    },
    {
        "line": "primary_defensive_tv6_rv40_max1p5_floor0p25_dbabs15",
        "line_role": "defensive_primary_watch",
        "layer2_anchor": "primary_60_18_we2p5_s0_abs30_m0p5",
        "layer2_candidate": "l2_bias_60_18_we2p5_score0_abs30_gt_m0p5pct",
        "anchor": "bias_60_18_we2p5",
        "family": "bias_momentum",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.5,
        "layer1_candidate": "dense_bias_ma060_mom018_we2p5_gt0",
        "score_threshold": 0.0,
        "abs_ma": 30,
        "abs_threshold": -0.005,
        "abs_filter": "ratio_bias",
        "target_vol": 0.06,
        "vol_window": 40,
        "max_leverage": 1.5,
        "min_scale": 0.25,
        "deadband_mode": "abs",
        "deadband_value": 0.15,
        "target_vol_enabled": True,
        "layer3_candidate": "l3_primary_60_18_we2p5_s0_abs30_m0p5_tv6_rv40_max1p5_floor0p25_dbabs0p15",
    },
]

NAV_THRESHOLDS = [0.02, 0.03, 0.04, 0.05, 0.06, 0.075, 0.0875, 0.10, 0.12, 0.15]
DEFENSE_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0]
WINDOW_SEGMENTS = ["full", "last_10y", "last_5y", "last_3y", "last_1y"]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def l3_base_returns(
    panel: pd.DataFrame,
    line: dict[str, object],
    scores: dict[str, pd.Series],
    r2s: dict[str, pd.Series],
    abs_bias: dict[int, pd.Series],
) -> pd.DataFrame:
    l2_frame = l3.build_l2_signal_frame(panel, line, scores, r2s, abs_bias)
    d = l3.apply_target_vol(l2_frame, line).copy()
    aligned = l2_frame.loc[d.index]
    d["spread_return"] = aligned["spread_return"]
    d["score"] = aligned["score"]
    d["r2"] = aligned["r2"]
    d["pre_nav"] = (1.0 + d["return"]).cumprod()
    d["pre_nav_dd"] = d["pre_nav"] / d["pre_nav"].cummax() - 1.0
    d["base_signal"] = d["raw_signal"]
    d["applied_scale"] = d["selected_scale"]
    return d


def apply_nav_defense(base_df: pd.DataFrame, threshold: float | None, scale: float | None) -> pd.DataFrame:
    d = base_df.copy()
    if threshold is None:
        final_weight = d["weight"]
        defense_on = pd.Series(False, index=d.index)
        mult = pd.Series(1.0, index=d.index)
    else:
        defense_on = d["pre_nav_dd"].shift(1).fillna(0.0) <= -float(threshold)
        mult = pd.Series(1.0, index=d.index)
        mult.loc[defense_on] = float(scale)
        final_weight = d["weight"] * mult

    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = final_weight * d["spread_return"].fillna(0.0)
    ret = gross_return - cost
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "base_weight": d["weight"],
            "base_signal": d["base_signal"],
            "spread_return": d["spread_return"],
            "pre_nav": d["pre_nav"],
            "pre_nav_dd": d["pre_nav_dd"],
            "nav_defense_on": defense_on.astype(int),
            "nav_defense_mult": mult,
            "raw_scale": d["raw_scale"],
            "applied_scale": d["applied_scale"],
            "realized_vol": d["realized_vol"],
            "score": d["score"],
            "r2": d["r2"],
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for line in LINES:
        grid.append(
            {
                **line,
                "candidate": f"l4_{line['line']}_nav_off",
                "nav_threshold": 0.0,
                "defense_scale": 1.0,
                "nav_enabled": False,
            }
        )
        for threshold in NAV_THRESHOLDS:
            for scale in DEFENSE_SCALES:
                grid.append(
                    {
                        **line,
                        "candidate": f"l4_{line['line']}_nav{fmt_num(threshold, True)}_scale{fmt_num(scale)}",
                        "nav_threshold": threshold,
                        "defense_scale": scale,
                        "nav_enabled": True,
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
            "nav_defense_days": 0.0,
            "nav_defense_day_ratio": 0.0,
            "avg_defense_mult": 1.0,
            "avg_active_defense_mult": 1.0,
        }
    active = d["base_weight"].abs() > 1e-12
    active_mult = d.loc[active, "nav_defense_mult"]
    return {
        "nav_defense_days": float(d["nav_defense_on"].sum()),
        "nav_defense_day_ratio": float(d["nav_defense_on"].mean()),
        "avg_defense_mult": float(d["nav_defense_mult"].mean()),
        "avg_active_defense_mult": float(active_mult.mean()) if not active_mult.empty else 1.0,
    }


def add_baselines_and_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["nav_enabled"] == False].set_index("line")
    baseline_cols = [
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
    ]
    for col in baseline_cols:
        out[f"base_{col}"] = out["line"].map(base_rows[col])
    for segment in WINDOW_SEGMENTS:
        out[f"{segment}_ann_loss_pp"] = (out[f"base_ann_return_{segment}"] - out[f"ann_return_{segment}"]) * 100.0
        out[f"{segment}_dd_improve_pp"] = (out[f"max_dd_{segment}"] - out[f"base_max_dd_{segment}"]) * 100.0
    out["cost_delta_full"] = out["cost_total_full"] - out["base_cost_total_full"]
    out["turnover_delta_full"] = out["avg_turnover_full"] - out["base_avg_turnover_full"]
    active_nav = out["nav_defense_days_full"] > 0
    out["pass_full_ann_dd"] = (
        (out["nav_enabled"] == True)
        & active_nav
        & (out["ann_return_full"] >= out["base_ann_return_full"] - 1e-12)
        & (out["max_dd_full"] >= out["base_max_dd_full"] - 1e-12)
    )
    out["pass_full_5y_ann_dd"] = (
        out["pass_full_ann_dd"]
        & (out["ann_return_last_5y"] >= out["base_ann_return_last_5y"] - 1e-12)
        & (out["max_dd_last_5y"] >= out["base_max_dd_last_5y"] - 1e-12)
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            (out["nav_enabled"] == True)
            & active_nav
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["last_5y_dd_improve_pp"] >= -1e-12)
        )
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    pass_cols = ["pass_full_ann_dd", "pass_full_5y_ann_dd"] + [
        f"pass_loss_le_{str(tier).replace('.', 'p')}pp" for tier in LOSS_TIERS
    ]
    source = wm[wm["nav_enabled"] == True]
    for pass_col in pass_cols:
        for line, group in source.groupby("line"):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": pass_col,
                        "line": line,
                        "pass_count": 0,
                        "threshold_count": 0,
                        "scale_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "best_nav_defense_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            thresholds = sorted(passed["nav_threshold"].unique())
            adjacent = any(round(thresholds[i + 1] - thresholds[i], 4) <= 0.0251 for i in range(len(thresholds) - 1))
            rows.append(
                {
                    "pass_rule": pass_col,
                    "line": line,
                    "pass_count": int(len(passed)),
                    "threshold_count": int(passed["nav_threshold"].nunique()),
                    "scale_count": int(passed["defense_scale"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "best_full_ann_loss_pp": float(best["full_ann_loss_pp"]),
                    "best_full_dd_improve_pp": float(best["full_dd_improve_pp"]),
                    "best_5y_ann_return": float(best["ann_return_last_5y"]),
                    "best_5y_max_dd": float(best["max_dd_last_5y"]),
                    "best_nav_defense_days": float(best["nav_defense_days_full"]),
                    "patch_like": bool(len(passed) >= 3 and passed["nav_threshold"].nunique() >= 2 and adjacent),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["pass_rule", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def comparison_table(df: pd.DataFrame, n: int = 12) -> str:
    cols = [
        "candidate",
        "line",
        "line_role",
        "nav_threshold",
        "defense_scale",
        "nav_defense_days_full",
    ]
    for segment in WINDOW_SEGMENTS:
        cols.extend(
            [
                f"base_ann_return_{segment}",
                f"base_max_dd_{segment}",
                f"ann_return_{segment}",
                f"max_dd_{segment}",
                f"{segment}_ann_loss_pp",
                f"{segment}_dd_improve_pp",
            ]
        )
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_") or col.startswith("base_ann_return_") or col.startswith("base_max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
        elif col.endswith("_ann_loss_pp"):
            display[col] = display[col].map(lambda x: f"{-float(x):+.2f}pp")
        elif col.endswith("_dd_improve_pp"):
            display[col] = display[col].map(lambda x: f"{float(x):+.2f}pp")
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, hs300, zz500, panel = l2.load_panel()
    scores, r2s, abs_bias = l2.precompute(panel)
    base_by_line = {str(line["line"]): l3_base_returns(panel, line, scores, r2s, abs_bias) for line in LINES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    grid = make_grid()
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    daily_parts: list[pd.DataFrame] = []

    for cand in grid:
        result = apply_nav_defense(
            base_by_line[str(cand["line"])],
            None if not bool(cand["nav_enabled"]) else float(cand["nav_threshold"]),
            None if not bool(cand["nav_enabled"]) else float(cand["defense_scale"]),
        )
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["line"] = cand["line"]
        daily_parts.append(daily.reset_index(names="date"))

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
                "nav_defense_days",
                "nav_defense_day_ratio",
                "avg_defense_mult",
                "avg_active_defense_mult",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    full_pass = window_metrics[window_metrics["nav_enabled"] & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[window_metrics["nav_enabled"] & window_metrics["pass_full_5y_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    loss_passes: dict[float, pd.DataFrame] = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(
            ["line", "full_dd_improve_pp", "ann_return_full"], ascending=[True, False, False]
        )
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        loss_passes[tier] = passed

    daily_all = pd.concat(daily_parts, ignore_index=True)
    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")

    carry_pool = strict_pass if not strict_pass.empty else loss_passes[1.0]
    carry = carry_pool.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).groupby("line").head(1)
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# HS300/ZZ500 Layer 4 NAV Defense After Target-Vol",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer4_nav_defense_complete_pending_user_review`",
        "- stability: `nav_defense_after_target_vol_patch_review`",
        "",
        "## Research Question",
        "Test prior-row NAV drawdown defense after Layer 3 target-vol and scale-deadband candidates.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
        "",
        "## Implementation Anchor",
        "- Imports Layer 2 data/signal functions and Layer 3 target-vol functions.",
        "- NAV defense uses prior-row pre-overlay NAV drawdown, then scales next execution exposure only.",
        "- Source-change rule: `research_only_new_scan_script`.",
        "",
        "## Data Snapshot",
        f"- HS300 publication date: {base.HS300_PUBLICATION_DATE}; local rows: {len(hs300)}, start {hs300.index.min().date()}, end {hs300.index.max().date()}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start rule: latest actual index publication date among the two legs.",
        "- Adjustment mode: price index close from local official cache, no total-return substitution.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long HS300 / short ZZ500; ratio is HS300/ZZ500; spread return is HS300 pct_change minus ZZ500 pct_change.",
        "- T close signal/target-vol/NAV state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- No overheat, amount/volume, or momentum-decay overlay is applied.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research, excluding futures basis, financing, borrow, short locate, and slippage.",
        "",
        "## NAV Grid",
        f"- nav_threshold: {NAV_THRESHOLDS}",
        f"- defense_scale: {DEFENSE_SCALES}",
        "",
        "## Baselines",
        comparison_table(window_metrics[~window_metrics["nav_enabled"]], len(LINES)),
        "",
        "## Full+5Y Non-Underperformance Candidates",
        comparison_table(strict_pass, 16) if not strict_pass.empty else "No NAV candidate passed full+5Y non-underperformance.",
        "",
        "## DD-First Candidates Loss <= 1pp",
        comparison_table(loss_passes[1.0], 16) if not loss_passes[1.0].empty else "No NAV candidate passed loss<=1pp with DD improvement.",
        "",
        "## Width Summary",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 4 completed and stopped for user review before formal Layer 5 momentum-decay testing.",
        "",
        "## User-Facing Summary",
        f"- candidates_scanned: {len(grid)}",
        f"- full_baseline_pass_count: {len(full_pass)}",
        f"- full_and_5y_pass_count: {len(strict_pass)}",
        f"- loss_le_0p5pp_pass_count: {len(loss_passes[0.5])}",
        f"- loss_le_1pp_pass_count: {len(loss_passes[1.0])}",
        f"- loss_le_2pp_pass_count: {len(loss_passes[2.0])}",
        "",
        "## Next-Layer Carry Candidates",
        comparison_table(carry, 10) if not carry.empty else "No carry candidate selected.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    git_status_after = base.git_text(["status", "--short"])
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "HS300/ZZ500 spread Layer 4 NAV defense",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_hs300_zz500_spread_layer3_target_vol.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": git_status_after,
        "scan_type": "fresh_layer4_nav_defense",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "nav_drawdown_threshold_defense_scale",
        "baseline": {"lines": LINES, "pass_rule": "compare every NAV candidate with same-line nav_off"},
        "candidate_grid": make_grid(),
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/target-vol/NAV state -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "publication_dates": {"HS300": base.HS300_PUBLICATION_DATE, "ZZ500": base.ZZ500_PUBLICATION_DATE},
            "ratio": "HS300 / ZZ500",
            "return_stream": "HS300 pct_change - ZZ500 pct_change",
        },
        "nav_implementation": "prior-row pre-overlay candidate NAV drawdown, shifted one row to next execution, final turnover/cost recomputed",
        "decision": "layer4_nav_defense_complete_pending_user_review",
        "stability_label": "nav_defense_after_target_vol_patch_review",
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
            "dd_first_pass_loss_le_0p5pp": str(RUN_DIR / "dd_first_pass_loss_le_0p5pp.csv"),
            "dd_first_pass_loss_le_1p0pp": str(RUN_DIR / "dd_first_pass_loss_le_1p0pp.csv"),
            "dd_first_pass_loss_le_2p0pp": str(RUN_DIR / "dd_first_pass_loss_le_2p0pp.csv"),
            "carry_candidates": str(RUN_DIR / "carry_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "\n".join(
            [
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "HS300/ZZ500 spread Layer 4 NAV defense" --parameter-group "nav_drawdown_threshold_defense_scale" --repo . --entrypoint "scan_adk_hs300_zz500_spread_layer4_nav_defense.py" --date 2026-06-12 --slug "adk_hs300_zz500_spread_long_only_v77_adk_spread_layer4_nav_defense_after_l3_target_vol"',
                'python -m py_compile "scan_adk_hs300_zz500_spread_layer4_nav_defense.py"',
                'python "scan_adk_hs300_zz500_spread_layer4_nav_defense.py"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "{RUN_DIR}" --decision "layer4_nav_defense_complete_pending_user_review" --stability-label "nav_defense_after_target_vol_patch_review"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict "{RUN_DIR}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(
        "FULL_PASS_COUNT="
        f"{len(full_pass)} STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)} "
        f"LOSS0P5_COUNT={len(loss_passes[0.5])} LOSS1_COUNT={len(loss_passes[1.0])} LOSS2_COUNT={len(loss_passes[2.0])}"
    )
    print("BASELINES")
    print(window_metrics[~window_metrics.nav_enabled][["line", "ann_return_full", "max_dd_full", "ann_return_last_10y", "max_dd_last_10y", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_3y", "max_dd_last_3y", "ann_return_last_1y", "max_dd_last_1y"]].to_string(index=False))
    print("STRICT_PASS_TOP")
    print(strict_pass[["candidate", "line", "nav_threshold", "defense_scale", "nav_defense_days_full", "ann_return_full", "max_dd_full", "ann_return_last_10y", "max_dd_last_10y", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_3y", "max_dd_last_3y", "ann_return_last_1y", "max_dd_last_1y", "full_ann_loss_pp", "full_dd_improve_pp"]].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

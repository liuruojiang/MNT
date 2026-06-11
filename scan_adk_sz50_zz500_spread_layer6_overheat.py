"""Layer 6 score/realized-vol overheat after Layer 5 decay for SZ50/ZZ500.

NAV defense was rejected, so this layer carries Layer 5 decay branches and tests
only overheat overlays. The overheat state is evaluated at T close via prior-row
score or realized volatility and applied to the next execution row.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_sz50_zz500_spread_layer3_target_vol as l3
import scan_adk_sz50_zz500_spread_layer5_momentum_decay as l5
import scan_adk_sz50_zz500_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_sz50_zz500_spread_long_only_v77_adk_spread_layer6_overheat_after_l5_decay"

LINES = [
    {
        "line": "return_s0_decay030_rec080_w3_s025",
        "line_role": "primary_l5_carry",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.75,
        "score_threshold": 0.0,
        "abs_ma": 80,
        "abs_threshold": -0.050,
        "target_vol": 0.16,
        "vol_window": 20,
        "max_leverage": 1.5,
        "scale_deadband": 0.30,
        "tv_enabled": True,
        "decay_threshold": 0.30,
        "recovery_threshold": 0.80,
        "warmup_days": 3,
        "derisk_scale": 0.25,
        "layer5_candidate": "l5_return_s0_tv16_vw20_max1p5_db0p30_decay0p3_rec0p8_warm3_scale0p25",
    },
    {
        "line": "return_s0_decay030_rec060_w3_s025",
        "line_role": "nearby_confirmation",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.75,
        "score_threshold": 0.0,
        "abs_ma": 80,
        "abs_threshold": -0.050,
        "target_vol": 0.16,
        "vol_window": 20,
        "max_leverage": 1.5,
        "scale_deadband": 0.30,
        "tv_enabled": True,
        "decay_threshold": 0.30,
        "recovery_threshold": 0.60,
        "warmup_days": 3,
        "derisk_scale": 0.25,
        "layer5_candidate": "l5_return_s0_tv16_vw20_max1p5_db0p30_decay0p3_rec0p6_warm3_scale0p25",
    },
    {
        "line": "return_sm1_decay045_rec090_w10_s025",
        "line_role": "return_heavy_watch",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.75,
        "score_threshold": -1.0,
        "abs_ma": 30,
        "abs_threshold": 0.005,
        "target_vol": 0.16,
        "vol_window": 30,
        "max_leverage": 1.5,
        "scale_deadband": 0.20,
        "tv_enabled": True,
        "decay_threshold": 0.45,
        "recovery_threshold": 0.90,
        "warmup_days": 10,
        "derisk_scale": 0.25,
        "layer5_candidate": "l5_return_sm1_tv16_vw30_max1p5_db0p20_decay0p45_rec0p9_warm10_scale0p25",
    },
]

SCORE_HOT_THRESHOLDS = [8, 10, 12, 15, 18, 22, 26, 30]
SCORE_HOT_SCALES = [0.0, 0.25, 0.5, 0.75]
VOL_HOT_WINDOWS = [20, 30, 40, 60, 90]
VOL_HOT_THRESHOLDS = [0.18, 0.22, 0.26, 0.30, 0.35, 0.40]
VOL_HOT_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def layer5_base_returns(panel: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    d0 = l5.l3_base_returns(panel, line)
    d = l5.apply_decay(
        d0,
        float(line["decay_threshold"]),
        float(line["recovery_threshold"]),
        int(line["warmup_days"]),
        float(line["derisk_scale"]),
    )
    d["layer5_weight"] = d["weight"]
    return d


def apply_overlay(base_df: pd.DataFrame, kind: str, params: dict[str, float]) -> pd.DataFrame:
    d = base_df.copy()
    mult = pd.Series(1.0, index=d.index)
    trigger = pd.Series(False, index=d.index)
    aux_value = pd.Series(np.nan, index=d.index)
    if kind == "off":
        pass
    elif kind == "scorehot":
        aux_value = d["score"].shift(1)
        trigger = aux_value.fillna(0.0) >= float(params["score_threshold"])
        mult.loc[trigger] = float(params["scale"])
    elif kind == "volhot":
        rv = d["spread_return"].rolling(int(params["window"])).std() * np.sqrt(base.ANNUALIZATION_DAYS)
        aux_value = rv.shift(1)
        trigger = aux_value.fillna(0.0) >= float(params["threshold"])
        mult.loc[trigger] = float(params["scale"])
    else:
        raise ValueError(kind)

    final_weight = d["layer5_weight"] * mult
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
            "layer5_weight": d["layer5_weight"],
            "overlay_mult": mult,
            "overlay_on": trigger.astype(int),
            "overlay_aux": aux_value,
            "decay_on": d["decay_on"],
            "decay_mult": d["decay_mult"],
            "score": d["score"],
            "score_strength": d["score_strength"],
            "spread_return": d["spread_return"],
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in LINES:
        rows.append(
            {
                **line,
                "candidate": f"l6_{line['line']}_overheat_off",
                "overlay_kind": "off",
                "param_a": 0.0,
                "param_b": 0.0,
                "param_c": 1.0,
            }
        )
        for threshold in SCORE_HOT_THRESHOLDS:
            for scale in SCORE_HOT_SCALES:
                rows.append(
                    {
                        **line,
                        "candidate": f"l6_{line['line']}_scorehot{threshold}_scale{fmt_num(scale)}",
                        "overlay_kind": "scorehot",
                        "param_a": float(threshold),
                        "param_b": 0.0,
                        "param_c": scale,
                    }
                )
        for window in VOL_HOT_WINDOWS:
            for threshold in VOL_HOT_THRESHOLDS:
                for scale in VOL_HOT_SCALES:
                    rows.append(
                        {
                            **line,
                            "candidate": f"l6_{line['line']}_volhot_w{window}_thr{fmt_num(threshold, True)}_scale{fmt_num(scale)}",
                            "overlay_kind": "volhot",
                            "param_a": float(window),
                            "param_b": threshold,
                            "param_c": scale,
                        }
                    )
    return rows


def params_for(cand: dict[str, object]) -> dict[str, float]:
    if cand["overlay_kind"] == "scorehot":
        return {"score_threshold": float(cand["param_a"]), "scale": float(cand["param_c"])}
    if cand["overlay_kind"] == "volhot":
        return {"window": float(cand["param_a"]), "threshold": float(cand["param_b"]), "scale": float(cand["param_c"])}
    return {}


def extra_metrics_for_segment(result: pd.DataFrame, years: int | None) -> dict[str, float]:
    if years is None:
        d = result.copy()
    else:
        cutoff = result.index.max() - pd.DateOffset(years=years)
        d = result.loc[result.index >= cutoff].copy()
    if d.empty:
        return {
            "overlay_days": 0.0,
            "overlay_day_ratio": 0.0,
            "decay_days": 0.0,
            "decay_overlay_overlap_days": 0.0,
        }
    return {
        "overlay_days": float(d["overlay_on"].sum()),
        "overlay_day_ratio": float(d["overlay_on"].mean()),
        "decay_days": float(d["decay_on"].sum()),
        "decay_overlay_overlap_days": float(((d["decay_on"] > 0) & (d["overlay_on"] > 0)).sum()),
    }


def add_baselines_and_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["overlay_kind"] == "off"].set_index("line")
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
        "cost_total_full",
    ]:
        out[f"base_{col}"] = out["line"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100.0
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100.0
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100.0
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100.0
    out["cost_delta"] = out["cost_total_full"] - out["base_cost_total_full"]
    out["pass_full_ann_dd"] = (
        (out["overlay_kind"] != "off")
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
            (out["overlay_kind"] != "off")
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["fivey_dd_improve_pp"] >= -1e-12)
        )
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    pass_cols = ["pass_full_ann_dd", "pass_full_and_5y"] + [f"pass_loss_le_{str(t).replace('.', 'p')}pp" for t in LOSS_TIERS]
    source = wm[wm["overlay_kind"] != "off"]
    for pass_col in pass_cols:
        for (line, kind), group in source.groupby(["line", "overlay_kind"]):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": pass_col,
                        "line": line,
                        "overlay_kind": kind,
                        "pass_count": 0,
                        "param_a_count": 0,
                        "param_b_count": 0,
                        "param_c_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "best_overlay_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(len(passed) >= 3 and passed["param_a"].nunique() >= 2)
            rows.append(
                {
                    "pass_rule": pass_col,
                    "line": line,
                    "overlay_kind": kind,
                    "pass_count": int(len(passed)),
                    "param_a_count": int(passed["param_a"].nunique()),
                    "param_b_count": int(passed["param_b"].nunique()),
                    "param_c_count": int(passed["param_c"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                    "best_full_dd_improve_pp": best["full_dd_improve_pp"],
                    "best_5y_ann_return": best["ann_return_last_5y"],
                    "best_5y_max_dd": best["max_dd_last_5y"],
                    "best_overlay_days": best["overlay_days_full"],
                    "patch_like": patch_like,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["pass_rule", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def state_overlap_summary(daily_all: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for candidate, d in daily_all.groupby("candidate"):
        decay_on = d["decay_on"].astype(float) > 0
        overlay_on = d["overlay_on"].astype(float) > 0
        masks = {
            "decay0_overheat0": ~decay_on & ~overlay_on,
            "decay1_overheat0": decay_on & ~overlay_on,
            "decay0_overheat1": ~decay_on & overlay_on,
            "decay1_overheat1": decay_on & overlay_on,
        }
        for state, mask in masks.items():
            part = d.loc[mask]
            rows.append(
                {
                    "candidate": candidate,
                    "state": state,
                    "days": int(mask.sum()),
                    "avg_weight": float(part["weight"].mean()) if not part.empty else np.nan,
                    "net_return_sum": float(part["return"].sum()) if not part.empty else 0.0,
                    "cost_sum": float(part["cost"].sum()) if not part.empty else 0.0,
                }
            )
    return pd.DataFrame(rows)


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def window_table(df: pd.DataFrame, n: int = 16) -> str:
    cols = ["candidate", "line", "overlay_kind", "param_a", "param_b", "param_c", "overlay_days_full"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, sz50, zz500, panel = l3.load_panel()
    base_by_line = {str(line["line"]): layer5_base_returns(panel, line) for line in LINES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = make_grid()
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    daily_parts: list[pd.DataFrame] = []

    for cand in grid:
        result = apply_overlay(base_by_line[str(cand["line"])], str(cand["overlay_kind"]), params_for(cand))
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["line"] = cand["line"]
        daily["overlay_kind"] = cand["overlay_kind"]
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
                "overlay_days",
                "overlay_day_ratio",
                "decay_days",
                "decay_overlay_overlap_days",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)
    overlap = state_overlap_summary(daily_all)

    full_pass = window_metrics[(window_metrics["overlay_kind"] != "off") & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[(window_metrics["overlay_kind"] != "off") & window_metrics["pass_full_and_5y"]].sort_values(
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

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    overlap.to_csv(RUN_DIR / "state_overlap_summary.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")

    cols = [
        "candidate",
        "line",
        "line_role",
        "overlay_kind",
        "param_a",
        "param_b",
        "param_c",
        "overlay_days_full",
        "decay_days_full",
        "decay_overlay_overlap_days_full",
        "ann_return_full",
        "max_dd_full",
        "full_ann_loss_pp",
        "full_dd_improve_pp",
        "ann_return_last_10y",
        "max_dd_last_10y",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "fivey_ann_loss_pp",
        "fivey_dd_improve_pp",
        "ann_return_last_3y",
        "max_dd_last_3y",
        "ann_return_last_1y",
        "max_dd_last_1y",
        "cost_total_full",
    ]
    display_cols = [c for c in cols if c in window_metrics.columns]
    baseline = window_metrics[window_metrics["overlay_kind"] == "off"][display_cols]
    record_lines = [
        "# SZ50/ZZ500 Layer 6 Overheat After Momentum Decay",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer6_overheat_complete_pending_user_review`",
        "- stability: `score_and_realized_vol_overheat_after_decay_review`",
        "",
        "## Research Question",
        "Test score and realized-vol overheat after Layer 5 momentum decay; NAV defense remains rejected/off.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
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
        "- T close signal/state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Scorehot uses prior-row score; volhot uses prior-row realized spread volatility.",
        "- NAV defense, entry staging, amount, and volume filters are off.",
        "",
        "## Overheat Grid",
        f"- scorehot thresholds: {SCORE_HOT_THRESHOLDS}, scales: {SCORE_HOT_SCALES}",
        f"- volhot windows: {VOL_HOT_WINDOWS}, thresholds: {VOL_HOT_THRESHOLDS}, scales: {VOL_HOT_SCALES}",
        "",
        "## Baselines",
        baseline.to_markdown(index=False),
        "",
        "## Full+5Y Non-Underperformance Candidates",
        window_table(strict_pass, 20) if not strict_pass.empty else "No overheat candidate passed full+5Y non-underperformance.",
        "",
        "## DD-First Candidates Loss <= 1pp",
        window_table(loss_passes[1.0], 20) if not loss_passes[1.0].empty else "No overheat candidate passed loss<=1pp with DD improvement.",
        "",
        "## DD-First Candidates Loss <= 2pp",
        window_table(loss_passes[2.0], 20) if not loss_passes[2.0].empty else "No overheat candidate passed loss<=2pp with DD improvement.",
        "",
        "## Width Summary",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 6 completed and stopped for user review before entry staging or amount/volume filters.",
        "",
        "## User-Facing Summary",
        f"- candidates_scanned: {len(grid)}",
        f"- full_baseline_pass_count: {len(full_pass)}",
        f"- full_and_5y_pass_count: {len(strict_pass)}",
        f"- loss_le_1pp_pass_count: {len(loss_passes[1.0])}",
        f"- loss_le_2pp_pass_count: {len(loss_passes[2.0])}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    git_status_after = base.git_text(["status", "--short"])
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "SZ50/ZZ500 spread Layer 6 overheat",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_sz50_zz500_spread_layer5_momentum_decay.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": git_status_after,
        "scan_type": "fresh_layer6_overheat_after_l5_decay",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "scorehot_realized_volhot_after_momentum_decay",
        "baseline": {
            "lines": LINES,
            "pass_rule": "compare every overheat candidate with same-line overheat_off",
            "layer4_nav_defense": "rejected_by_user_review_as_too_weak",
        },
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "publication_dates": {"SZ50": base.SZ50_PUBLICATION_DATE, "ZZ500": base.ZZ500_PUBLICATION_DATE},
        },
        "overheat_implementation": "prior-row score or prior-row realized spread volatility, final turnover/cost recomputed",
        "decision": "layer6_overheat_complete_pending_user_review",
        "stability_label": "score_and_realized_vol_overheat_after_decay_review",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "state_overlap_summary": str(RUN_DIR / "state_overlap_summary.csv"),
            "full_baseline_pass_candidates": str(RUN_DIR / "full_baseline_pass_candidates.csv"),
            "full_and_5y_pass_candidates": str(RUN_DIR / "full_and_5y_pass_candidates.csv"),
            "dd_first_pass_loss_le_0p5pp": str(RUN_DIR / "dd_first_pass_loss_le_0p5pp.csv"),
            "dd_first_pass_loss_le_1p0pp": str(RUN_DIR / "dd_first_pass_loss_le_1p0pp.csv"),
            "dd_first_pass_loss_le_2p0pp": str(RUN_DIR / "dd_first_pass_loss_le_2p0pp.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "\n".join(
            [
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "SZ50/ZZ500 spread Layer 6 overheat" --parameter-group "scorehot_realized_volhot_after_momentum_decay" --repo . --entrypoint "scan_adk_sz50_zz500_spread_layer6_overheat.py" --date 2026-06-12 --slug "adk_sz50_zz500_spread_long_only_v77_adk_spread_layer6_overheat_after_l5_decay"',
                'python -m py_compile "scan_adk_sz50_zz500_spread_layer6_overheat.py"',
                'python "scan_adk_sz50_zz500_spread_layer6_overheat.py"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "{RUN_DIR}" --decision "layer6_overheat_complete_pending_user_review" --stability-label "score_and_realized_vol_overheat_after_decay_review"',
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
        f"LOSS1_COUNT={len(loss_passes[1.0])} LOSS2_COUNT={len(loss_passes[2.0])}"
    )
    print("BASELINES")
    print(baseline.to_string(index=False))
    print("STRICT_PASS_TOP")
    print(strict_pass[display_cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    print("LOSS_1_TOP")
    print(loss_passes[1.0][display_cols].head(20).to_string(index=False) if not loss_passes[1.0].empty else "NONE")
    print("LOSS_2_TOP")
    print(loss_passes[2.0][display_cols].head(20).to_string(index=False) if not loss_passes[2.0].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

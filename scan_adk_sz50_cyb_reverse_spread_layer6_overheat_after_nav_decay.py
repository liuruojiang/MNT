"""Layer 6 overheat scan after NAV defense and momentum decay for SZ50/CYB.

Formal sequence: Layer 4 NAV defense -> Layer 5 momentum decay -> Layer 6
overheat. This scan carries three Layer 5 branches and tests three overheat
families on the already NAV/decay-adjusted exposure.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_sz50_cyb_reverse_spread_layer5_momentum_decay_after_nav as l5
import scan_adk_sz50_cyb_reverse_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260609_adk_sz50_cyb_reverse_spread_long_only_v77_adk_reverse_spread_layer6_overheat_after_nav_decay_three_lines"

BRANCHES = [
    {
        "branch": "neighbor_nav10_s025_decay030_rec080_w3_s0",
        "branch_role": "formal_carry",
        "anchor": "neighbor_tv16_nav10_s025",
        "bias_ma": 30,
        "mom_day": 32,
        "weight_end": 3.5,
        "score_threshold": 1.0,
        "abs_ma": 15,
        "abs_threshold": -0.070,
        "target_vol": 0.16,
        "vol_window": 20,
        "max_leverage": 1.25,
        "nav_threshold": 0.10,
        "nav_scale": 0.25,
        "decay_threshold": 0.30,
        "recovery_threshold": 0.80,
        "warmup_days": 3,
        "derisk_scale": 0.0,
    },
    {
        "branch": "main_nav10_s0_decay030_rec080_w3_s025",
        "branch_role": "main_comparison",
        "anchor": "main_tv16_nav10_s0",
        "bias_ma": 25,
        "mom_day": 36,
        "weight_end": 4.0,
        "score_threshold": 0.0,
        "abs_ma": 15,
        "abs_threshold": -0.070,
        "target_vol": 0.16,
        "vol_window": 20,
        "max_leverage": 1.5,
        "nav_threshold": 0.10,
        "nav_scale": 0.0,
        "decay_threshold": 0.30,
        "recovery_threshold": 0.80,
        "warmup_days": 3,
        "derisk_scale": 0.25,
    },
    {
        "branch": "return_tv20_nav12_s0_decay030_rec080_w3_s05",
        "branch_role": "return_comparison",
        "anchor": "return_tv20_nav12_s0",
        "bias_ma": 25,
        "mom_day": 36,
        "weight_end": 4.0,
        "score_threshold": 0.0,
        "abs_ma": 15,
        "abs_threshold": -0.070,
        "target_vol": 0.20,
        "vol_window": 20,
        "max_leverage": 1.5,
        "nav_threshold": 0.12,
        "nav_scale": 0.0,
        "decay_threshold": 0.30,
        "recovery_threshold": 0.80,
        "warmup_days": 3,
        "derisk_scale": 0.5,
    },
]

SCORE_HOT_THRESHOLDS = [20, 30, 40, 50, 60, 80, 100]
SCORE_HOT_SCALES = [0.0, 0.25, 0.5, 0.75]
VOL_HOT_WINDOWS = [20, 30, 40, 60, 90]
VOL_HOT_THRESHOLDS = [0.18, 0.22, 0.26, 0.30, 0.35, 0.40]
VOL_HOT_SCALES = [0.0, 0.25, 0.5, 0.75]
DOWNONLY_TVS = [0.10, 0.12, 0.14, 0.16, 0.18, 0.20]
DOWNONLY_WINDOWS = [20, 30, 40, 60, 90]
DOWNONLY_MIN_SCALES = [0.0, 0.25, 0.5]
LOSS_TIERS = [1.0, 2.0, 3.0]


def fmt(value: float, pct: bool = False) -> str:
    x = value * 100.0 if pct else value
    sign = "m" if x < 0 else ""
    return sign + f"{abs(x):g}".replace(".", "p")


def layer5_base(panel: pd.DataFrame, branch: dict[str, object]) -> pd.DataFrame:
    l4_base = l5.l4_nav_base(panel, branch)
    d = l5.apply_decay(
        l4_base,
        float(branch["decay_threshold"]),
        float(branch["recovery_threshold"]),
        int(branch["warmup_days"]),
        float(branch["derisk_scale"]),
    )
    d["spread_return"] = l4_base["spread_return"]
    d["layer5_weight"] = d["weight"]
    d["layer5_return"] = d["return"]
    return d


def apply_overlay(base_df: pd.DataFrame, kind: str, params: dict[str, float]) -> pd.DataFrame:
    d = base_df.copy()
    mult = pd.Series(1.0, index=d.index)
    trigger = pd.Series(False, index=d.index)

    if kind == "off":
        pass
    elif kind == "scorehot":
        trigger = d["score"].shift(1).fillna(0.0) >= float(params["score_threshold"])
        mult.loc[trigger] = float(params["scale"])
    elif kind == "volhot":
        rv = d["spread_return"].rolling(int(params["window"])).std() * np.sqrt(base.base_scan.ANNUALIZATION_DAYS)
        trigger = rv.shift(1).fillna(0.0) >= float(params["threshold"])
        mult.loc[trigger] = float(params["scale"])
    elif kind == "downonly_tv":
        rv = d["spread_return"].rolling(int(params["window"])).std() * np.sqrt(base.base_scan.ANNUALIZATION_DAYS)
        cap = (float(params["target_vol"]) / rv).clip(float(params["min_scale"]), 1.0).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        tv_gate = float(params.get("target_vol_gate", 0.0))
        if tv_gate > 0.0:
            cap = cap.where(cap <= (1.0 - tv_gate), 1.0)
        mult = cap.shift(1).fillna(1.0)
        trigger = mult < 0.999
    else:
        raise ValueError(kind)

    final_weight = d["layer5_weight"] * mult
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.base_scan.COMMISSION_ONE_WAY)
    gross_return = final_weight * d["spread_return"]
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
            "overlay_on": trigger.astype(float),
            "nav_on": d["nav_on"],
            "decay_on": d["decay_on"],
            "decay_mult": d["decay_mult"],
            "score": d["score"],
            "spread_return": d["spread_return"],
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for branch in BRANCHES:
        rows.append({**branch, "candidate": f"l6oh_{branch['branch']}_overlay_off", "overlay_kind": "off", "param_a": 0.0, "param_b": 0.0, "param_c": 1.0})
        for thr in SCORE_HOT_THRESHOLDS:
            for scale in SCORE_HOT_SCALES:
                rows.append({**branch, "candidate": f"l6oh_{branch['branch']}_scorehot{thr}_scale{fmt(scale)}", "overlay_kind": "scorehot", "param_a": float(thr), "param_b": 0.0, "param_c": scale})
        for window in VOL_HOT_WINDOWS:
            for thr in VOL_HOT_THRESHOLDS:
                for scale in VOL_HOT_SCALES:
                    rows.append({**branch, "candidate": f"l6oh_{branch['branch']}_volhot_w{window}_thr{fmt(thr, True)}_scale{fmt(scale)}", "overlay_kind": "volhot", "param_a": float(window), "param_b": thr, "param_c": scale})
        for tv in DOWNONLY_TVS:
            for window in DOWNONLY_WINDOWS:
                for min_scale in DOWNONLY_MIN_SCALES:
                    rows.append({**branch, "candidate": f"l6oh_{branch['branch']}_downonly_tv{fmt(tv, True)}_w{window}_min{fmt(min_scale)}", "overlay_kind": "downonly_tv", "param_a": tv, "param_b": float(window), "param_c": min_scale})
    return rows


def params_for(cand: dict[str, object]) -> dict[str, float]:
    kind = cand["overlay_kind"]
    if kind == "scorehot":
        return {"score_threshold": float(cand["param_a"]), "scale": float(cand["param_c"])}
    if kind == "volhot":
        return {"window": float(cand["param_a"]), "threshold": float(cand["param_b"]), "scale": float(cand["param_c"])}
    if kind == "downonly_tv":
        return {
            "target_vol": float(cand["param_a"]),
            "window": float(cand["param_b"]),
            "min_scale": float(cand["param_c"]),
            "target_vol_gate": float(cand.get("param_d", 0.0)),
        }
    return {}


def add_tiers(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["overlay_kind"] == "off"].set_index("branch")
    for col in ["ann_return_full", "max_dd_full", "ann_return_last_5y", "max_dd_last_5y", "sharpe_repo_full"]:
        out[f"base_{col}"] = out["branch"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100
    out["strict_full5y_pass"] = (
        (out["overlay_kind"] != "off")
        & (out["full_ann_loss_pp"] <= 1.0 + 1e-12)
        & (out["full_dd_improve_pp"] > 0)
        & (out["fivey_ann_loss_pp"] <= 1.0 + 1e-12)
        & (out["fivey_dd_improve_pp"] >= -1e-12)
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (out["overlay_kind"] != "off") & (out["full_ann_loss_pp"] <= tier + 1e-12) & (out["full_dd_improve_pp"] > 0)
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for (branch, kind), d in wm[wm["overlay_kind"] != "off"].groupby(["branch", "overlay_kind"]):
            p = d[d[pass_col]].copy()
            if p.empty:
                rows.append({"loss_tier_pp": tier, "branch": branch, "overlay_kind": kind, "pass_count": 0, "param_a_count": 0, "param_b_count": 0, "param_c_count": 0, "strict_full5y_count": 0, "best_candidate": "", "best_full_ann_return": np.nan, "best_full_max_dd": np.nan, "best_full_ann_loss_pp": np.nan, "best_full_dd_improve_pp": np.nan, "best_5y_ann_return": np.nan, "best_5y_max_dd": np.nan, "patch_like": False})
                continue
            best = p.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(len(p) >= 3 and p["param_a"].nunique() >= 2)
            rows.append({"loss_tier_pp": tier, "branch": branch, "overlay_kind": kind, "pass_count": int(len(p)), "param_a_count": int(p["param_a"].nunique()), "param_b_count": int(p["param_b"].nunique()), "param_c_count": int(p["param_c"].nunique()), "strict_full5y_count": int(p["strict_full5y_pass"].sum()), "best_candidate": best["candidate"], "best_full_ann_return": best["ann_return_full"], "best_full_max_dd": best["max_dd_full"], "best_full_ann_loss_pp": best["full_ann_loss_pp"], "best_full_dd_improve_pp": best["full_dd_improve_pp"], "best_5y_ann_return": best["ann_return_last_5y"], "best_5y_max_dd": best["max_dd_last_5y"], "patch_like": patch_like})
    return pd.DataFrame(rows).sort_values(["loss_tier_pp", "patch_like", "strict_full5y_count", "pass_count", "best_full_dd_improve_pp"], ascending=[True, False, False, False, False])


def state_overlap_summary(daily_all: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for candidate, d in daily_all.groupby("candidate"):
        nav_on = d["nav_on"].astype(float) > 0
        decay_on = d["decay_on"].astype(float) > 0
        overlay_on = d["overlay_on"].astype(float) > 0
        masks = {
            "nav0_decay0_overheat0": ~nav_on & ~decay_on & ~overlay_on,
            "nav1_decay0_overheat0": nav_on & ~decay_on & ~overlay_on,
            "nav0_decay1_overheat0": ~nav_on & decay_on & ~overlay_on,
            "nav0_decay0_overheat1": ~nav_on & ~decay_on & overlay_on,
            "nav1_decay1_overheat0": nav_on & decay_on & ~overlay_on,
            "nav1_decay0_overheat1": nav_on & ~decay_on & overlay_on,
            "nav0_decay1_overheat1": ~nav_on & decay_on & overlay_on,
            "nav1_decay1_overheat1": nav_on & decay_on & overlay_on,
        }
        for label, mask in masks.items():
            part = d.loc[mask]
            rows.append(
                {
                    "candidate": candidate,
                    "state": label,
                    "days": int(mask.sum()),
                    "avg_weight": float(part["weight"].mean()) if not part.empty else np.nan,
                    "net_return_sum": float(part["return"].sum()) if not part.empty else 0.0,
                    "cost_sum": float(part["cost"].sum()) if not part.empty else 0.0,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    _mod, cyb, sz50, panel = l5.load_panel()
    base_by_branch = {b["branch"]: layer5_base(panel, b) for b in BRANCHES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    grid = make_grid()
    long_rows = []
    wide_rows = []
    daily_parts = []
    for cand in grid:
        result = apply_overlay(base_by_branch[cand["branch"]], str(cand["overlay_kind"]), params_for(cand))
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["branch"] = cand["branch"]
        daily["overlay_kind"] = cand["overlay_kind"]
        daily_parts.append(daily.reset_index(names="date"))
        wide = {**cand}
        wide["overlay_days_full"] = int(result["overlay_on"].sum())
        wide["nav_days_full"] = int(result["nav_on"].sum())
        wide["decay_days_full"] = int(result["decay_on"].sum())
        wide["nav_decay_overlay_overlap_days_full"] = int(((result["nav_on"] > 0) & (result["decay_on"] > 0) & (result["overlay_on"] > 0)).sum())
        for segment, years in base.base_scan.SEGMENTS:
            m = base.base_scan.metrics_for_segment(result, segment, years)
            long_rows.append({**cand, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_tiers(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)
    overlap = state_overlap_summary(daily_all)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    overlap.to_csv(RUN_DIR / "state_overlap_summary.csv", index=False, encoding="utf-8-sig")

    top_by_tier = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(["strict_full5y_pass", "full_dd_improve_pp", "ann_return_full"], ascending=[False, False, False])
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_by_tier[tier] = passed
    strict = window_metrics[window_metrics["strict_full5y_pass"]].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
    strict.to_csv(RUN_DIR / "strict_full5y_pass.csv", index=False, encoding="utf-8-sig")

    cols = [
        "candidate",
        "branch",
        "branch_role",
        "overlay_kind",
        "param_a",
        "param_b",
        "param_c",
        "overlay_days_full",
        "nav_days_full",
        "decay_days_full",
        "nav_decay_overlay_overlap_days_full",
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
        "sharpe_repo_full",
    ]
    record_lines = [
        "# SZ50/CYB Layer 6 Overheat After NAV And Momentum Decay",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer6_overheat_after_nav_decay_complete_not_promoted`",
        "- stability: `overheat_after_nav_decay_patch_review`",
        "",
        "## Research Question",
        "Test overheat overlays after the formal Layer 5 NAV-defense plus momentum-decay branches.",
        "",
        "## Implementation Anchor",
        "- Three Layer 5 branches are carried: formal carry, main comparison, and return comparison.",
        "- Baseline exposure already includes Layer 4 NAV defense and Layer 5 score-peak momentum decay.",
        "- Overheat multiplier is applied to the Layer 5 final exposure, then turnover, cost, return, NAV, and drawdown are recalculated.",
        "- Tested overheat families: scorehot, volhot, and downonly_tv.",
        "",
        "## Data Snapshot",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- SZ50 rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long SZ50 / short CYB.",
        "- T close signal and state -> T+1 close-to-close spread return.",
        "- Two-leg transaction cost with one-way commission 0.0005 on final exposure changes.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_sz50_cyb_reverse_spread_layer6_overheat_after_nav_decay.py\"`",
        "- `python \"scan_adk_sz50_cyb_reverse_spread_layer6_overheat_after_nav_decay.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `state_overlap_summary.csv`",
        "- `ridge_width.csv`",
        "- `strict_full5y_pass.csv`",
        "- `dd_first_pass_loss_le_1p0pp.csv`",
        "- `dd_first_pass_loss_le_2p0pp.csv`",
        "- `dd_first_pass_loss_le_3p0pp.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Baselines",
        window_metrics[window_metrics["overlay_kind"] == "off"][cols].to_markdown(index=False),
        "",
        "## Strict Full Plus 5Y Results",
        strict[cols].head(25).to_markdown(index=False) if not strict.empty else "No candidates passed strict Full + 5Y screen.",
        "",
        "## Full-Sample Results",
        top_by_tier[1.0][cols].head(25).to_markdown(index=False) if not top_by_tier[1.0].empty else "No candidates passed loss<=1pp with DD improvement.",
        "",
        "## Window Results",
        top_by_tier[2.0][cols].head(25).to_markdown(index=False) if not top_by_tier[2.0].empty else "No candidates passed loss<=2pp with DD improvement.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 6 overheat after NAV+decay completed but not promoted. Stop for review before any amount or final-composition layer.",
        "",
        "## User-Facing Summary",
        f"- loss<=1pp pass count: {len(top_by_tier[1.0])}",
        f"- loss<=2pp pass count: {len(top_by_tier[2.0])}",
        f"- loss<=3pp pass count: {len(top_by_tier[3.0])}",
        f"- strict Full+5Y pass count: {len(strict)}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK reverse spread research",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_sz50_cyb_reverse_spread_layer5_momentum_decay_after_nav.py",
        "git_branch": "not_checked_agent_policy",
        "git_commit": "not_checked_agent_policy",
        "git_status_before": "dirty_research_workspace",
        "git_status_after": "dirty_research_workspace",
        "scan_type": "fresh_layer6_overheat_after_nav_decay_three_lines",
        "parameter_group": "scorehot_volhot_downonlytv_after_nav_decay",
        "baseline": {"branches": BRANCHES, "loss_tiers_pp": LOSS_TIERS},
        "candidate_grid": grid,
        "cost_model": {"one_way_commission": base.base_scan.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return", "direction": "long SZ50 / short CYB"},
        "data_snapshot": {"source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via reverse layer harness", "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())}},
        "decision": "layer6_overheat_after_nav_decay_complete_not_promoted",
        "stability_label": "overheat_after_nav_decay_patch_review",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "state_overlap_summary": str(RUN_DIR / "state_overlap_summary.csv"),
            "strict_full5y_pass": str(RUN_DIR / "strict_full5y_pass.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_sz50_cyb_reverse_spread_layer6_overheat_after_nav_decay.py\"\n"
        "python \"scan_adk_sz50_cyb_reverse_spread_layer6_overheat_after_nav_decay.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("BASELINES")
    print(window_metrics[window_metrics.overlay_kind == "off"][cols].to_string(index=False))
    print(f"STRICT_FULL5Y_COUNT={len(strict)}")
    print(strict[cols].head(15).to_string(index=False) if not strict.empty else "NONE")
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_by_tier[tier])}")
        print(top_by_tier[tier][cols].head(12).to_string(index=False) if not top_by_tier[tier].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

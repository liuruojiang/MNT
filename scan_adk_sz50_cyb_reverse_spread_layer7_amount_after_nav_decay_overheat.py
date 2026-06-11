"""Layer 7 amount defense after NAV, momentum decay, and overheat for SZ50/CYB.

This is a quasi-formal layer because the available CYB/SZ50 amount panel is
composed from two existing local sources with different raw units. The scan
uses only own-MA relative amount features and unitless relative ratios.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_sz50_cyb_reverse_spread_layer6_overheat_after_nav_decay as l6
import scan_adk_sz50_cyb_reverse_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260609_adk_sz50_cyb_reverse_spread_long_only_v77_adk_reverse_spread_layer7_amount_after_nav_decay_overheat"
AMOUNT_CSV = base.ROOT / "outputs" / "adk_cyb_sz50_amount_composed.csv"
AMOUNT_META = base.ROOT / "outputs" / "adk_cyb_sz50_amount_composed_meta.json"

INPUTS = [
    {
        "line": "neighbor_volhot_w30_thr22_s05",
        "line_role": "formal_carry",
        "branch": "neighbor_nav10_s025_decay030_rec080_w3_s0",
        "overlay_kind": "volhot",
        "param_a": 30.0,
        "param_b": 0.22,
        "param_c": 0.5,
    },
    {
        "line": "neighbor_downonly_tv16_w30_min0",
        "line_role": "defensive_neighbor",
        "branch": "neighbor_nav10_s025_decay030_rec080_w3_s0",
        "overlay_kind": "downonly_tv",
        "param_a": 0.16,
        "param_b": 30.0,
        "param_c": 0.0,
    },
    {
        "line": "main_downonly_tv14_w30_min0",
        "line_role": "main_comparison",
        "branch": "main_nav10_s0_decay030_rec080_w3_s025",
        "overlay_kind": "downonly_tv",
        "param_a": 0.14,
        "param_b": 30.0,
        "param_c": 0.0,
    },
    {
        "line": "return_downonly_tv16_w30_min05",
        "line_role": "return_comparison",
        "branch": "return_tv20_nav12_s0_decay030_rec080_w3_s05",
        "overlay_kind": "downonly_tv",
        "param_a": 0.16,
        "param_b": 30.0,
        "param_c": 0.5,
    },
]

AMOUNT_WINDOWS = [20, 40, 60, 80, 120]
HIGH_THRESHOLDS = [1.25, 1.50, 1.75, 2.00]
LOW_THRESHOLDS = [0.75, 0.85, 1.00]
CONFIRM_DAYS = [1, 3, 5]
AMOUNT_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [1.0, 2.0, 3.0]


def fmt(value: float) -> str:
    return f"{value:g}".replace(".", "p")


def load_amount_panel() -> tuple[pd.DataFrame, dict[str, object]]:
    if not AMOUNT_CSV.exists():
        raise FileNotFoundError(f"missing amount panel: {AMOUNT_CSV}")
    amount = pd.read_csv(AMOUNT_CSV, encoding="utf-8-sig")
    amount["date"] = pd.to_datetime(amount["date"])
    amount = amount.set_index("date").sort_index()
    meta = json.loads(AMOUNT_META.read_text(encoding="utf-8")) if AMOUNT_META.exists() else {}
    return amount, meta


def branch_config(branch_name: str) -> dict[str, object]:
    matches = [b for b in l6.BRANCHES if b["branch"] == branch_name]
    if len(matches) != 1:
        raise ValueError(branch_name)
    return matches[0]


def params_for_overlay(line: dict[str, object]) -> dict[str, float]:
    if line["overlay_kind"] == "volhot":
        return {"window": float(line["param_a"]), "threshold": float(line["param_b"]), "scale": float(line["param_c"])}
    if line["overlay_kind"] == "downonly_tv":
        return {"target_vol": float(line["param_a"]), "window": float(line["param_b"]), "min_scale": float(line["param_c"])}
    raise ValueError(str(line["overlay_kind"]))


def line_base(panel: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    b = branch_config(str(line["branch"]))
    l5_base = l6.layer5_base(panel, b)
    return l6.apply_overlay(l5_base, str(line["overlay_kind"]), params_for_overlay(line))


def amount_feature(amount_panel: pd.DataFrame, feature: str, window: int) -> pd.Series:
    cyb_rel = amount_panel["cyb_amount"] / amount_panel["cyb_amount"].rolling(window).mean()
    sz50_rel = amount_panel["sz50_amount"] / amount_panel["sz50_amount"].rolling(window).mean()
    pair_rel = sz50_rel / cyb_rel
    if feature in {"cyb_high", "cyb_low"}:
        return cyb_rel
    if feature in {"sz50_high", "sz50_low"}:
        return sz50_rel
    if feature in {"pair_high", "pair_low"}:
        return pair_rel
    raise ValueError(feature)


def confirmed_trigger(cond: pd.Series, days: int) -> pd.Series:
    if days <= 1:
        return cond.fillna(False)
    return cond.astype(float).rolling(days).sum().fillna(0) >= days


def apply_amount_overlay(
    base_df: pd.DataFrame,
    amount_panel: pd.DataFrame,
    feature: str | None,
    window: int | None,
    threshold: float | None,
    confirm_days: int | None,
    scale: float | None,
) -> pd.DataFrame:
    d = base_df.copy()
    if feature is None:
        mult = pd.Series(1.0, index=d.index)
        on = pd.Series(False, index=d.index)
        indicator = pd.Series(np.nan, index=d.index)
    else:
        indicator = amount_feature(amount_panel, feature, int(window)).reindex(d.index)
        raw = indicator >= float(threshold) if feature.endswith("high") else indicator <= float(threshold)
        on = confirmed_trigger(raw, int(confirm_days)).shift(1).fillna(False)
        mult = pd.Series(1.0, index=d.index)
        mult.loc[on] = float(scale)

    final_weight = d["weight"] * mult
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
            "pre_amount_weight": d["weight"],
            "amount_mult": mult,
            "amount_on": on.astype(float),
            "amount_indicator": indicator,
            "spread_return": d["spread_return"],
            "nav_on": d["nav_on"],
            "decay_on": d["decay_on"],
            "overheat_on": d["overlay_on"],
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    features = ["cyb_high", "cyb_low", "sz50_high", "sz50_low", "pair_high", "pair_low"]
    for line in INPUTS:
        rows.append({**line, "candidate": f"l7amt_{line['line']}_amount_off", "amount_feature": "off", "amount_window": 0, "amount_threshold": 0.0, "confirm_days": 0, "amount_scale": 1.0, "amount_enabled": False})
        for feature in features:
            thresholds = HIGH_THRESHOLDS if feature.endswith("high") else LOW_THRESHOLDS
            for window in AMOUNT_WINDOWS:
                for threshold in thresholds:
                    for days in CONFIRM_DAYS:
                        for scale in AMOUNT_SCALES:
                            rows.append({**line, "candidate": f"l7amt_{line['line']}_{feature}_w{window}_thr{fmt(threshold)}_d{days}_scale{fmt(scale)}", "amount_feature": feature, "amount_window": window, "amount_threshold": threshold, "confirm_days": days, "amount_scale": scale, "amount_enabled": True})
    return rows


def run_candidate(cand: dict[str, object], base_by_line: dict[str, pd.DataFrame], amount_panel: pd.DataFrame) -> pd.DataFrame:
    return apply_amount_overlay(
        base_by_line[cand["line"]],
        amount_panel,
        None if not cand["amount_enabled"] else str(cand["amount_feature"]),
        None if not cand["amount_enabled"] else int(cand["amount_window"]),
        None if not cand["amount_enabled"] else float(cand["amount_threshold"]),
        None if not cand["amount_enabled"] else int(cand["confirm_days"]),
        None if not cand["amount_enabled"] else float(cand["amount_scale"]),
    )


def add_tiers(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["amount_enabled"] == False].set_index("line")
    for col in ["ann_return_full", "max_dd_full", "ann_return_last_5y", "max_dd_last_5y", "sharpe_repo_full"]:
        out[f"base_{col}"] = out["line"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100
    out["strict_full5y_pass"] = (
        (out["amount_enabled"] == True)
        & (out["full_ann_loss_pp"] <= 1.0 + 1e-12)
        & (out["full_dd_improve_pp"] > 0)
        & (out["fivey_ann_loss_pp"] <= 1.0 + 1e-12)
        & (out["fivey_dd_improve_pp"] >= -1e-12)
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (out["amount_enabled"] == True) & (out["full_ann_loss_pp"] <= tier + 1e-12) & (out["full_dd_improve_pp"] > 0)
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for (line, feature), d in wm[wm["amount_enabled"] == True].groupby(["line", "amount_feature"]):
            p = d[d[pass_col]].copy()
            if p.empty:
                rows.append({"loss_tier_pp": tier, "line": line, "amount_feature": feature, "pass_count": 0, "window_count": 0, "threshold_count": 0, "day_count": 0, "scale_count": 0, "strict_full5y_count": 0, "best_candidate": "", "best_full_ann_return": np.nan, "best_full_max_dd": np.nan, "best_full_ann_loss_pp": np.nan, "best_full_dd_improve_pp": np.nan, "best_5y_ann_return": np.nan, "best_5y_max_dd": np.nan, "patch_like": False})
                continue
            best = p.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(len(p) >= 4 and p["amount_window"].nunique() >= 2 and p["amount_threshold"].nunique() >= 2)
            rows.append({"loss_tier_pp": tier, "line": line, "amount_feature": feature, "pass_count": int(len(p)), "window_count": int(p["amount_window"].nunique()), "threshold_count": int(p["amount_threshold"].nunique()), "day_count": int(p["confirm_days"].nunique()), "scale_count": int(p["amount_scale"].nunique()), "strict_full5y_count": int(p["strict_full5y_pass"].sum()), "best_candidate": best["candidate"], "best_full_ann_return": best["ann_return_full"], "best_full_max_dd": best["max_dd_full"], "best_full_ann_loss_pp": best["full_ann_loss_pp"], "best_full_dd_improve_pp": best["full_dd_improve_pp"], "best_5y_ann_return": best["ann_return_last_5y"], "best_5y_max_dd": best["max_dd_last_5y"], "patch_like": patch_like})
    return pd.DataFrame(rows).sort_values(["loss_tier_pp", "patch_like", "strict_full5y_count", "pass_count", "best_full_dd_improve_pp"], ascending=[True, False, False, False, False])


def main() -> None:
    _mod, cyb, sz50, panel = l6.l5.load_panel()
    amount_panel, amount_meta = load_amount_panel()
    amount_panel = amount_panel.reindex(panel.index)
    complete_amount_rows = amount_panel[["cyb_amount", "sz50_amount"]].dropna()
    base_by_line = {line["line"]: line_base(panel, line) for line in INPUTS}
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    grid = make_grid()
    grid_by_candidate = {str(c["candidate"]): c for c in grid}
    long_rows = []
    wide_rows = []
    for cand in grid:
        result = run_candidate(cand, base_by_line, amount_panel)
        wide = {**cand}
        wide["amount_days_full"] = int(result["amount_on"].sum())
        wide["amount_complete_rows_full"] = int(len(complete_amount_rows))
        for segment, years in base.base_scan.SEGMENTS:
            m = base.base_scan.metrics_for_segment(result, segment, years)
            long_rows.append({**cand, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_tiers(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    strict = window_metrics[window_metrics["strict_full5y_pass"]].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    strict.to_csv(RUN_DIR / "strict_full5y_pass.csv", index=False, encoding="utf-8-sig")

    top_by_tier = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(["strict_full5y_pass", "full_dd_improve_pp", "ann_return_full"], ascending=[False, False, False])
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_by_tier[tier] = passed

    keep_candidates = set(window_metrics.loc[window_metrics["amount_enabled"] == False, "candidate"].astype(str))
    keep_candidates.update(strict.head(80)["candidate"].astype(str).tolist())
    for passed in top_by_tier.values():
        keep_candidates.update(passed.head(40)["candidate"].astype(str).tolist())
    daily_parts = []
    for candidate in sorted(keep_candidates):
        cand = grid_by_candidate[candidate]
        result = run_candidate(cand, base_by_line, amount_panel)
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["line"] = cand["line"]
        daily["amount_feature"] = cand["amount_feature"]
        daily_parts.append(daily.reset_index(names="date"))
    daily_all = pd.concat(daily_parts, ignore_index=True)
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")

    cols = [
        "candidate", "line", "line_role", "amount_feature", "amount_window", "amount_threshold", "confirm_days", "amount_scale", "amount_days_full",
        "ann_return_full", "max_dd_full", "full_ann_loss_pp", "full_dd_improve_pp",
        "ann_return_last_10y", "max_dd_last_10y", "ann_return_last_5y", "max_dd_last_5y",
        "fivey_ann_loss_pp", "fivey_dd_improve_pp", "ann_return_last_3y", "max_dd_last_3y",
        "ann_return_last_1y", "max_dd_last_1y", "sharpe_repo_full",
    ]
    record_lines = [
        "# SZ50/CYB Layer 7 Amount Defense After NAV + Decay + Overheat",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer7_amount_after_nav_decay_overheat_complete_not_promoted`",
        "- stability: `quasi_formal_amount_patch_review`",
        "",
        "## Research Question",
        "Test amount/volume defense after the formal NAV, momentum-decay, and overheat lines.",
        "",
        "## Implementation Anchor",
        "- Input lines already include Layer 4 NAV defense, Layer 5 momentum decay, and Layer 6 overheat.",
        "- Amount multiplier is applied to the Layer 6 final exposure, then turnover, cost, return, NAV, and drawdown are recalculated.",
        "- This layer is quasi-formal because the CYB/SZ50 amount panel is composed from sources with different raw units.",
        "- Only own-MA relative features and unitless SZ50_rel/CYB_rel pair features are used.",
        "",
        "## Data Snapshot",
        f"- CYB price rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- SZ50 price rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- Formal aligned price rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        f"- Amount panel rows with both amount series on formal dates: {len(complete_amount_rows)}, start {complete_amount_rows.index.min().date()}, end {complete_amount_rows.index.max().date()}.",
        f"- Amount panel: `{AMOUNT_CSV}`.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long SZ50 / short CYB.",
        "- Amount trigger is T-close state shifted to T+1 execution.",
        "- Two-leg transaction cost with one-way commission 0.0005 on final exposure changes.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_sz50_cyb_reverse_spread_layer7_amount_after_nav_decay_overheat.py\"`",
        "- `python \"scan_adk_sz50_cyb_reverse_spread_layer7_amount_after_nav_decay_overheat.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `strict_full5y_pass.csv`",
        "- `dd_first_pass_loss_le_1p0pp.csv`",
        "- `dd_first_pass_loss_le_2p0pp.csv`",
        "- `dd_first_pass_loss_le_3p0pp.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Baselines",
        window_metrics[window_metrics["amount_enabled"] == False][cols].to_markdown(index=False),
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
        "Layer 7 amount scan completed but not promoted. Stop for review before final ridge or fixed-script landing.",
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
        "implementation_anchor": "scan_adk_sz50_cyb_reverse_spread_layer6_overheat_after_nav_decay.py",
        "git_branch": "not_checked_agent_policy",
        "git_commit": "not_checked_agent_policy",
        "git_status_before": "dirty_research_workspace",
        "git_status_after": "dirty_research_workspace",
        "scan_type": "fresh_layer7_amount_after_nav_decay_overheat",
        "formal_status": "quasi_formal_due_to_composed_amount_panel",
        "parameter_group": "amount_relative_ma_defense_after_nav_decay_overheat",
        "baseline": {"inputs": INPUTS, "loss_tiers_pp": LOSS_TIERS, "amount_unit_warning": amount_meta.get("unit_warning", "raw units not treated as comparable")},
        "candidate_grid": grid,
        "cost_model": {"one_way_commission": base.base_scan.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return", "direction": "long SZ50 / short CYB"},
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via reverse layer harness",
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "amount": {"csv": str(AMOUNT_CSV), "meta": str(AMOUNT_META), "complete_rows_on_formal_dates": int(len(complete_amount_rows)), "start": str(complete_amount_rows.index.min().date()), "end": str(complete_amount_rows.index.max().date())},
        },
        "decision": "layer7_amount_after_nav_decay_overheat_complete_not_promoted",
        "stability_label": "quasi_formal_amount_patch_review",
        "daily_curve_scope": "baselines plus top strict/full-loss candidates, not all grid candidates",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "strict_full5y_pass": str(RUN_DIR / "strict_full5y_pass.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_sz50_cyb_reverse_spread_layer7_amount_after_nav_decay_overheat.py\"\n"
        "python \"scan_adk_sz50_cyb_reverse_spread_layer7_amount_after_nav_decay_overheat.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(f"AMOUNT_COMPLETE={complete_amount_rows.index.min().date()}->{complete_amount_rows.index.max().date()} rows={len(complete_amount_rows)}")
    print("BASELINES")
    print(window_metrics[window_metrics.amount_enabled == False][cols].to_string(index=False))
    print(f"STRICT_FULL5Y_COUNT={len(strict)}")
    print(strict[cols].head(15).to_string(index=False) if not strict.empty else "NONE")
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_by_tier[tier])}")
        print(top_by_tier[tier][cols].head(12).to_string(index=False) if not top_by_tier[tier].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

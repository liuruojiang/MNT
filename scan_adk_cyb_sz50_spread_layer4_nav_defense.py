"""Layer 4 NAV drawdown defense after Layer 3 target-vol for CYB/SZ50.

Uses prior-row pre-overlay candidate NAV drawdown. If prior DD <= -threshold,
next execution exposure is multiplied by defense_scale. Costs are recalculated
on final exposure changes.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_sz50_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260609_adk_cyb_sz50_spread_long_only_v77_adk_spread_layer4_nav_defense_after_l3_tv"

ANCHORS = [
    {"anchor": "main_l3", "bias_ma": 80, "mom_day": 28, "weight_end": 2.5, "score_threshold": 5.0, "abs_ma": 25, "abs_threshold": 0.010, "target_vol": 0.24, "vol_window": 30, "max_leverage": 1.5},
    {"anchor": "neighbor_abs30_l3", "bias_ma": 80, "mom_day": 28, "weight_end": 2.5, "score_threshold": 5.0, "abs_ma": 30, "abs_threshold": 0.015, "target_vol": 0.24, "vol_window": 30, "max_leverage": 1.5},
]
NAV_THRESHOLDS = [0.04, 0.05, 0.06, 0.075, 0.0875, 0.10, 0.12]
DEFENSE_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [1.0, 2.0, 3.0]
MIN_LEVERAGE = 0.1


def fmt(value: float, pct: bool = False) -> str:
    x = value * 100.0 if pct else value
    sign = "m" if x < 0 else ""
    return sign + f"{abs(x):g}".replace(".", "p")


def load_panel():
    mod = base.load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    sz50 = mod._load_cn_official_cache(mod.CN_DK_SZ50_SECID).rename(columns={"close": "SZ50"})
    panel = pd.concat([cyb["CYB"], sz50["SZ50"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["CYB"] / panel["SZ50"]
    panel["spread_return"] = panel["CYB"].pct_change().fillna(0.0) - panel["SZ50"].pct_change().fillna(0.0)
    return mod, cyb, sz50, panel


def l3_base_returns(panel: pd.DataFrame, anchor: dict[str, object]) -> pd.DataFrame:
    ratio = panel["ratio"]
    feature = ratio / ratio.rolling(int(anchor["bias_ma"])).mean() - 1.0
    score = base.weighted_slope_score(feature, int(anchor["mom_day"]), float(anchor["weight_end"]))
    r2 = base.weighted_slope_r2(feature, int(anchor["mom_day"]), float(anchor["weight_end"]))
    abs_bias = ratio / ratio.rolling(int(anchor["abs_ma"])).mean() - 1.0
    raw_signal = ((score > float(anchor["score_threshold"])) & (r2 >= 0.05) & (abs_bias > float(anchor["abs_threshold"]))).astype(float)
    signal = raw_signal.shift(1).fillna(0.0)
    realized_vol = panel["spread_return"].rolling(int(anchor["vol_window"])).std() * np.sqrt(base.ANNUALIZATION_DAYS)
    raw_scale = (float(anchor["target_vol"]) / realized_vol).clip(MIN_LEVERAGE, float(anchor["max_leverage"])).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    weight = signal * raw_scale
    warmup = max(int(anchor["bias_ma"]), int(anchor["mom_day"]), int(anchor["abs_ma"]), int(anchor["vol_window"])) + 2
    d = pd.DataFrame({"weight": weight, "score": score, "r2": r2, "abs_bias": abs_bias, "raw_scale": raw_scale, "spread_return": panel["spread_return"]}, index=panel.index).iloc[warmup:].dropna().copy()
    turnover = d["weight"].diff().abs().fillna(d["weight"].abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = d["weight"] * d["spread_return"]
    ret = gross_return - cost
    nav = (1.0 + ret).cumprod()
    dd = nav / nav.cummax() - 1.0
    d["return"] = ret
    d["gross_return"] = gross_return
    d["cost"] = cost
    d["turnover"] = turnover
    d["pre_nav"] = nav
    d["pre_nav_dd"] = dd
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
    gross_return = final_weight * d["spread_return"]
    ret = gross_return - cost
    out = pd.DataFrame({"return": ret, "gross_return": gross_return, "cost": cost, "turnover": turnover, "weight": final_weight, "base_weight": d["weight"], "pre_nav": d["pre_nav"], "pre_nav_dd": d["pre_nav_dd"], "nav_defense_on": defense_on.astype(float), "nav_defense_mult": mult}, index=d.index)
    return out


def make_grid():
    for anchor in ANCHORS:
        yield {**anchor, "candidate": f"l4_{anchor['anchor']}_nav_off", "nav_threshold": 0.0, "defense_scale": 1.0, "nav_enabled": False}
        for threshold in NAV_THRESHOLDS:
            for scale in DEFENSE_SCALES:
                yield {**anchor, "candidate": f"l4_{anchor['anchor']}_nav{fmt(threshold, True)}_scale{fmt(scale)}", "nav_threshold": threshold, "defense_scale": scale, "nav_enabled": True}


def add_tiers(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["nav_enabled"] == False].set_index("anchor")
    for col in ["ann_return_full", "max_dd_full", "ann_return_last_5y", "max_dd_last_5y", "sharpe_repo_full"]:
        out[f"base_{col}"] = out["anchor"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (out["nav_enabled"] == True) & (out["full_ann_loss_pp"] <= tier + 1e-12) & (out["full_dd_improve_pp"] > 0)
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for anchor, d in wm[wm["nav_enabled"] == True].groupby("anchor"):
            p = d[d[pass_col]].copy()
            if p.empty:
                rows.append({"loss_tier_pp": tier, "anchor": anchor, "pass_count": 0, "threshold_count": 0, "scale_count": 0, "best_candidate": "", "best_full_ann_return": np.nan, "best_full_max_dd": np.nan, "best_full_ann_loss_pp": np.nan, "best_full_dd_improve_pp": np.nan, "best_5y_ann_return": np.nan, "best_5y_max_dd": np.nan, "patch_like": False})
                continue
            best = p.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(len(p) >= 3 and p["nav_threshold"].nunique() >= 2)
            rows.append({"loss_tier_pp": tier, "anchor": anchor, "pass_count": int(len(p)), "threshold_count": int(p["nav_threshold"].nunique()), "scale_count": int(p["defense_scale"].nunique()), "best_candidate": best["candidate"], "best_full_ann_return": best["ann_return_full"], "best_full_max_dd": best["max_dd_full"], "best_full_ann_loss_pp": best["full_ann_loss_pp"], "best_full_dd_improve_pp": best["full_dd_improve_pp"], "best_5y_ann_return": best["ann_return_last_5y"], "best_5y_max_dd": best["max_dd_last_5y"], "patch_like": patch_like})
    return pd.DataFrame(rows).sort_values(["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"], ascending=[True, False, False, False])


def main() -> None:
    mod, cyb, sz50, panel = load_panel()
    base_by_anchor = {a["anchor"]: l3_base_returns(panel, a) for a in ANCHORS}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = list(make_grid())
    long_rows = []
    wide_rows = []
    daily_parts = []
    for cand in grid:
        result = apply_nav_defense(base_by_anchor[cand["anchor"]], None if not cand["nav_enabled"] else float(cand["nav_threshold"]), None if not cand["nav_enabled"] else float(cand["defense_scale"]))
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily_parts.append(daily.reset_index(names="date"))
        wide = {**cand}
        wide["nav_defense_days_full"] = int(result["nav_defense_on"].sum()) if "nav_defense_on" in result else 0
        for segment, years in base.SEGMENTS:
            m = base.metrics_for_segment(result, segment, years)
            long_rows.append({**cand, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)
    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_tiers(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)
    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    top_by_tier = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_by_tier[tier] = passed
    cols = ["candidate", "anchor", "nav_threshold", "defense_scale", "nav_defense_days_full", "ann_return_full", "max_dd_full", "full_ann_loss_pp", "full_dd_improve_pp", "ann_return_last_5y", "max_dd_last_5y", "fivey_ann_loss_pp", "fivey_dd_improve_pp", "sharpe_repo_full"]
    record_lines = [
        "# CYB/SZ50 Layer 4 NAV Defense After L3 Target-Vol",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer4_nav_defense_complete_not_promoted`",
        "- stability: `nav_defense_dd_first_patch_review`",
        "",
        "## Research Question",
        "Test prior-row NAV drawdown defense after the L3 target-vol anchors.",
        "",
        "## Implementation Anchor",
        "- Uses prior-row pre-overlay NAV drawdown from the L3 candidate.",
        "- Recalculates costs after final exposure changes.",
        "",
        "## Data Snapshot",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- SZ50 rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal -> T+1 close-to-close spread return.",
        "- NAV defense uses prior-row pre-overlay NAV drawdown, then scales next exposure.",
        "- Two-leg transaction cost with one-way commission 0.0005 on final exposure changes.",
        "- No overheat, amount, or momentum-decay overlay is applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_cyb_sz50_spread_layer4_nav_defense.py\"`",
        "- `python \"scan_adk_cyb_sz50_spread_layer4_nav_defense.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `dd_first_pass_loss_le_1p0pp.csv`",
        "- `dd_first_pass_loss_le_2p0pp.csv`",
        "- `dd_first_pass_loss_le_3p0pp.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        top_by_tier[1.0][cols].head(20).to_markdown(index=False) if not top_by_tier[1.0].empty else "No candidates passed loss<=1pp with DD improvement.",
        "",
        "## Window Results",
        top_by_tier[2.0][cols].head(20).to_markdown(index=False) if not top_by_tier[2.0].empty else "No candidates passed loss<=2pp with DD improvement.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 4 completed but not promoted. Stop for review before further overheat/decay layers.",
        "",
        "## User-Facing Summary",
        f"- loss<=1pp pass count: {len(top_by_tier[1.0])}",
        f"- loss<=2pp pass count: {len(top_by_tier[2.0])}",
        f"- loss<=3pp pass count: {len(top_by_tier[3.0])}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")
    meta = {"run_id": RUN_DIR.name, "created_at": datetime.now().isoformat(timespec="seconds"), "project": "A-share / US momentum combo", "strategy": "V7.7 ADK spread research", "repo_root": str(base.ROOT), "entrypoint": str(Path(__file__).name), "implementation_anchor": "scan_adk_cyb_sz50_spread_long_only.py", "git_branch": "not_checked_agent_policy", "git_commit": "not_checked_agent_policy", "git_status_before": "not_checked_agent_policy", "git_status_after": "not_checked_agent_policy", "scan_type": "fresh_layer4_nav_defense_after_l3_tv", "parameter_group": "nav_dd_threshold_defense_scale", "baseline": {"anchors": ANCHORS, "loss_tiers_pp": LOSS_TIERS}, "candidate_grid": grid, "cost_model": {"one_way_commission": base.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return"}, "data_snapshot": {"source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via layer1 harness", "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())}}, "decision": "layer4_nav_defense_complete_not_promoted", "stability_label": "nav_defense_dd_first_patch_review", "outputs": {"record": str(RUN_DIR / "record.md"), "scan_summary": str(RUN_DIR / "scan_summary.csv"), "window_metrics": str(RUN_DIR / "window_metrics.csv"), "scan_meta": str(RUN_DIR / "scan_meta.json"), "command_log": str(RUN_DIR / "command_log.txt"), "daily_curves": str(RUN_DIR / "daily_curves.csv"), "ridge_width": str(RUN_DIR / "ridge_width.csv")}}
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text("python -m py_compile \"scan_adk_cyb_sz50_spread_layer4_nav_defense.py\"\npython \"scan_adk_cyb_sz50_spread_layer4_nav_defense.py\"\npython C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n", encoding="utf-8")
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("BASELINES")
    print(window_metrics[window_metrics.nav_enabled == False][cols].to_string(index=False))
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_by_tier[tier])}")
        print(top_by_tier[tier][cols].head(12).to_string(index=False) if not top_by_tier[tier].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

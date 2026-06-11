"""Layer 5 three-overheat scan after NAV defense for CYB/SZ50.

Tests three overheat families on NAV-defense baselines:
- score overheat: high holding score reduces exposure
- realized-vol overheat: high spread realized vol reduces exposure
- down-only target-vol cap: risk cap on final exposure

Amount/volume is intentionally not included here because no CYB/SZ50 amount panel
has been built for this fresh branch in the current session.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_sz50_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260609_adk_cyb_sz50_spread_long_only_v77_adk_spread_layer5_overheat_after_nav"

ANCHORS = [
    {"anchor": "nav6", "bias_ma": 80, "mom_day": 28, "weight_end": 2.5, "score_threshold": 5.0, "abs_ma": 30, "abs_threshold": 0.015, "target_vol": 0.24, "vol_window": 30, "max_leverage": 1.5, "nav_threshold": 0.06, "nav_scale": 0.75},
    {"anchor": "nav4", "bias_ma": 80, "mom_day": 28, "weight_end": 2.5, "score_threshold": 5.0, "abs_ma": 30, "abs_threshold": 0.015, "target_vol": 0.24, "vol_window": 30, "max_leverage": 1.5, "nav_threshold": 0.04, "nav_scale": 0.75},
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


def nav_base(panel: pd.DataFrame, anchor: dict[str, object]) -> pd.DataFrame:
    ratio = panel["ratio"]
    feature = ratio / ratio.rolling(int(anchor["bias_ma"])).mean() - 1.0
    score = base.weighted_slope_score(feature, int(anchor["mom_day"]), float(anchor["weight_end"]))
    r2 = base.weighted_slope_r2(feature, int(anchor["mom_day"]), float(anchor["weight_end"]))
    abs_bias = ratio / ratio.rolling(int(anchor["abs_ma"])).mean() - 1.0
    raw_signal = ((score > float(anchor["score_threshold"])) & (r2 >= 0.05) & (abs_bias > float(anchor["abs_threshold"]))).astype(float)
    exec_signal = raw_signal.shift(1).fillna(0.0)
    realized_vol = panel["spread_return"].rolling(int(anchor["vol_window"])).std() * np.sqrt(base.ANNUALIZATION_DAYS)
    raw_scale = (float(anchor["target_vol"]) / realized_vol).clip(MIN_LEVERAGE, float(anchor["max_leverage"])).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    l3_weight = exec_signal * raw_scale
    warmup = max(int(anchor["bias_ma"]), int(anchor["mom_day"]), int(anchor["abs_ma"]), int(anchor["vol_window"])) + 2
    d = pd.DataFrame({"l3_weight": l3_weight, "score": score, "spread_return": panel["spread_return"]}, index=panel.index).iloc[warmup:].dropna().copy()
    l3_turnover = d["l3_weight"].diff().abs().fillna(d["l3_weight"].abs())
    l3_cost = l3_turnover * (2.0 * base.COMMISSION_ONE_WAY)
    l3_ret = d["l3_weight"] * d["spread_return"] - l3_cost
    pre_nav = (1.0 + l3_ret).cumprod()
    pre_dd = pre_nav / pre_nav.cummax() - 1.0
    nav_on = pre_dd.shift(1).fillna(0.0) <= -float(anchor["nav_threshold"])
    nav_mult = pd.Series(1.0, index=d.index)
    nav_mult.loc[nav_on] = float(anchor["nav_scale"])
    weight = d["l3_weight"] * nav_mult
    turnover = weight.diff().abs().fillna(weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = weight * d["spread_return"]
    ret = gross_return - cost
    out = pd.DataFrame({"weight": weight, "base_weight": weight, "score": d["score"], "spread_return": d["spread_return"], "return": ret, "gross_return": gross_return, "cost": cost, "turnover": turnover, "pre_nav": pre_nav, "pre_nav_dd": pre_dd, "nav_on": nav_on.astype(float)}, index=d.index)
    return out


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
        rv = d["spread_return"].rolling(int(params["window"])).std() * np.sqrt(base.ANNUALIZATION_DAYS)
        trigger = rv.shift(1).fillna(0.0) >= float(params["threshold"])
        mult.loc[trigger] = float(params["scale"])
    elif kind == "downonly_tv":
        rv = d["spread_return"].rolling(int(params["window"])).std() * np.sqrt(base.ANNUALIZATION_DAYS)
        cap = (float(params["target_vol"]) / rv).clip(float(params["min_scale"]), 1.0).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        mult = cap.shift(1).fillna(1.0)
        trigger = mult < 0.999
    else:
        raise ValueError(kind)
    weight = d["base_weight"] * mult
    turnover = weight.diff().abs().fillna(weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = weight * d["spread_return"]
    ret = gross_return - cost
    return pd.DataFrame({"return": ret, "gross_return": gross_return, "cost": cost, "turnover": turnover, "weight": weight, "base_weight": d["base_weight"], "overlay_mult": mult, "overlay_on": trigger.astype(float), "score": d["score"]}, index=d.index)


def make_grid():
    for anchor in ANCHORS:
        yield {**anchor, "candidate": f"l5_{anchor['anchor']}_overlay_off", "overlay_kind": "off", "param_a": 0.0, "param_b": 0.0, "param_c": 1.0}
        for thr in SCORE_HOT_THRESHOLDS:
            for scale in SCORE_HOT_SCALES:
                yield {**anchor, "candidate": f"l5_{anchor['anchor']}_scorehot{thr}_scale{fmt(scale)}", "overlay_kind": "scorehot", "param_a": float(thr), "param_b": 0.0, "param_c": scale}
        for window in VOL_HOT_WINDOWS:
            for thr in VOL_HOT_THRESHOLDS:
                for scale in VOL_HOT_SCALES:
                    yield {**anchor, "candidate": f"l5_{anchor['anchor']}_volhot_w{window}_thr{fmt(thr, True)}_scale{fmt(scale)}", "overlay_kind": "volhot", "param_a": float(window), "param_b": thr, "param_c": scale}
        for tv in DOWNONLY_TVS:
            for window in DOWNONLY_WINDOWS:
                for min_scale in DOWNONLY_MIN_SCALES:
                    yield {**anchor, "candidate": f"l5_{anchor['anchor']}_downonly_tv{fmt(tv, True)}_w{window}_min{fmt(min_scale)}", "overlay_kind": "downonly_tv", "param_a": tv, "param_b": float(window), "param_c": min_scale}


def params_for(cand: dict[str, object]) -> dict[str, float]:
    kind = cand["overlay_kind"]
    if kind == "scorehot":
        return {"score_threshold": float(cand["param_a"]), "scale": float(cand["param_c"])}
    if kind == "volhot":
        return {"window": float(cand["param_a"]), "threshold": float(cand["param_b"]), "scale": float(cand["param_c"])}
    if kind == "downonly_tv":
        return {"target_vol": float(cand["param_a"]), "window": float(cand["param_b"]), "min_scale": float(cand["param_c"])}
    return {}


def add_tiers(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["overlay_kind"] == "off"].set_index("anchor")
    for col in ["ann_return_full", "max_dd_full", "ann_return_last_5y", "max_dd_last_5y", "sharpe_repo_full"]:
        out[f"base_{col}"] = out["anchor"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (out["overlay_kind"] != "off") & (out["full_ann_loss_pp"] <= tier + 1e-12) & (out["full_dd_improve_pp"] > 0)
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for (anchor, kind), d in wm[wm["overlay_kind"] != "off"].groupby(["anchor", "overlay_kind"]):
            p = d[d[pass_col]].copy()
            if p.empty:
                rows.append({"loss_tier_pp": tier, "anchor": anchor, "overlay_kind": kind, "pass_count": 0, "param_a_count": 0, "param_b_count": 0, "param_c_count": 0, "best_candidate": "", "best_full_ann_return": np.nan, "best_full_max_dd": np.nan, "best_full_ann_loss_pp": np.nan, "best_full_dd_improve_pp": np.nan, "best_5y_ann_return": np.nan, "best_5y_max_dd": np.nan, "patch_like": False})
                continue
            best = p.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(len(p) >= 3 and p["param_a"].nunique() >= 2)
            rows.append({"loss_tier_pp": tier, "anchor": anchor, "overlay_kind": kind, "pass_count": int(len(p)), "param_a_count": int(p["param_a"].nunique()), "param_b_count": int(p["param_b"].nunique()), "param_c_count": int(p["param_c"].nunique()), "best_candidate": best["candidate"], "best_full_ann_return": best["ann_return_full"], "best_full_max_dd": best["max_dd_full"], "best_full_ann_loss_pp": best["full_ann_loss_pp"], "best_full_dd_improve_pp": best["full_dd_improve_pp"], "best_5y_ann_return": best["ann_return_last_5y"], "best_5y_max_dd": best["max_dd_last_5y"], "patch_like": patch_like})
    return pd.DataFrame(rows).sort_values(["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"], ascending=[True, False, False, False])


def main() -> None:
    mod, cyb, sz50, panel = load_panel()
    base_by_anchor = {a["anchor"]: nav_base(panel, a) for a in ANCHORS}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = list(make_grid())
    long_rows = []
    wide_rows = []
    daily_parts = []
    for cand in grid:
        result = apply_overlay(base_by_anchor[cand["anchor"]], str(cand["overlay_kind"]), params_for(cand))
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily_parts.append(daily.reset_index(names="date"))
        wide = {**cand}
        wide["overlay_days_full"] = int(result["overlay_on"].sum())
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
    cols = ["candidate", "anchor", "overlay_kind", "param_a", "param_b", "param_c", "overlay_days_full", "ann_return_full", "max_dd_full", "full_ann_loss_pp", "full_dd_improve_pp", "ann_return_last_5y", "max_dd_last_5y", "fivey_ann_loss_pp", "fivey_dd_improve_pp", "sharpe_repo_full"]
    record_lines = [
        "# CYB/SZ50 Layer 5 Overheat After NAV",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer5_overheat_complete_not_promoted`",
        "- stability: `overheat_dd_first_patch_review`",
        "",
        "## Research Question",
        "Test score overheat, realized-vol overheat, and down-only TV caps after NAV defense.",
        "",
        "## Implementation Anchor",
        "- Amount/volume overheat excluded because no fresh CYB/SZ50 amount panel was built in this run.",
        "- Overlay states are shifted to avoid same-row lookahead where applicable.",
        "",
        "## Data Snapshot",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- SZ50 rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal -> T+1 close-to-close spread return.",
        "- Two-leg transaction cost with one-way commission 0.0005 on final exposure changes.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_cyb_sz50_spread_layer5_overheat_after_nav.py\"`",
        "- `python \"scan_adk_cyb_sz50_spread_layer5_overheat_after_nav.py\"`",
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
        "Layer 5 completed but not promoted. Stop for review before amount/volume work or final ridge.",
        "",
        "## User-Facing Summary",
        f"- loss<=1pp pass count: {len(top_by_tier[1.0])}",
        f"- loss<=2pp pass count: {len(top_by_tier[2.0])}",
        f"- loss<=3pp pass count: {len(top_by_tier[3.0])}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")
    meta = {"run_id": RUN_DIR.name, "created_at": datetime.now().isoformat(timespec="seconds"), "project": "A-share / US momentum combo", "strategy": "V7.7 ADK spread research", "repo_root": str(base.ROOT), "entrypoint": str(Path(__file__).name), "implementation_anchor": "scan_adk_cyb_sz50_spread_long_only.py", "git_branch": "not_checked_agent_policy", "git_commit": "not_checked_agent_policy", "git_status_before": "not_checked_agent_policy", "git_status_after": "not_checked_agent_policy", "scan_type": "fresh_layer5_overheat_after_nav", "parameter_group": "scorehot_volhot_downonlytv", "baseline": {"anchors": ANCHORS, "loss_tiers_pp": LOSS_TIERS}, "candidate_grid": grid, "cost_model": {"one_way_commission": base.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return"}, "data_snapshot": {"source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via layer1 harness", "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())}}, "decision": "layer5_overheat_complete_not_promoted", "stability_label": "overheat_dd_first_patch_review", "outputs": {"record": str(RUN_DIR / "record.md"), "scan_summary": str(RUN_DIR / "scan_summary.csv"), "window_metrics": str(RUN_DIR / "window_metrics.csv"), "scan_meta": str(RUN_DIR / "scan_meta.json"), "command_log": str(RUN_DIR / "command_log.txt"), "daily_curves": str(RUN_DIR / "daily_curves.csv"), "ridge_width": str(RUN_DIR / "ridge_width.csv")}}
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text("python -m py_compile \"scan_adk_cyb_sz50_spread_layer5_overheat_after_nav.py\"\npython \"scan_adk_cyb_sz50_spread_layer5_overheat_after_nav.py\"\npython C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n", encoding="utf-8")
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("BASELINES")
    print(window_metrics[window_metrics.overlay_kind == 'off'][cols].to_string(index=False))
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_by_tier[tier])}")
        print(top_by_tier[tier][cols].head(12).to_string(index=False) if not top_by_tier[tier].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

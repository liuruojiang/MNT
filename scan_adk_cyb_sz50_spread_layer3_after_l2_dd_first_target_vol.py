"""Layer 3 target-vol scan after Layer 2 DD-first anchors for CYB/SZ50.

Inputs:
- main: lowdd80 score5 abs25>1%
- neighbors: lowdd80 score5 abs25>0.5%, lowdd80 score5 abs30>1.5%

This layer uses DD-first pass tiers: annual return loss <=2/3/5pp plus max-drawdown improvement.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_sz50_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260609_adk_cyb_sz50_spread_long_only_v77_adk_spread_layer3_target_vol_after_l2_dd_first"

ANCHORS = [
    {"anchor": "main_lowdd80_s5_abs25_p1", "bias_ma": 80, "mom_day": 28, "weight_end": 2.5, "score_threshold": 5.0, "abs_ma": 25, "abs_threshold": 0.010},
    {"anchor": "neighbor_lowdd80_s5_abs25_p0p5", "bias_ma": 80, "mom_day": 28, "weight_end": 2.5, "score_threshold": 5.0, "abs_ma": 25, "abs_threshold": 0.005},
    {"anchor": "neighbor_lowdd80_s5_abs30_p1p5", "bias_ma": 80, "mom_day": 28, "weight_end": 2.5, "score_threshold": 5.0, "abs_ma": 30, "abs_threshold": 0.015},
]
TARGET_VOLS = [0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.24, 0.28]
VOL_WINDOWS = [20, 30, 40, 60, 90, 120]
MAX_LEVERAGES = [1.0, 1.25, 1.5]
MIN_LEVERAGE = 0.1
LOSS_TIERS = [2.0, 3.0, 5.0]


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


def anchor_signal(panel: pd.DataFrame, anchor: dict[str, object]) -> pd.DataFrame:
    ratio = panel["ratio"]
    feature = ratio / ratio.rolling(int(anchor["bias_ma"])).mean() - 1.0
    score = base.weighted_slope_score(feature, int(anchor["mom_day"]), float(anchor["weight_end"]))
    r2 = base.weighted_slope_r2(feature, int(anchor["mom_day"]), float(anchor["weight_end"]))
    abs_bias = ratio / ratio.rolling(int(anchor["abs_ma"])).mean() - 1.0
    raw_signal = ((score > float(anchor["score_threshold"])) & (r2 >= 0.05) & (abs_bias > float(anchor["abs_threshold"]))).astype(float)
    exec_signal = raw_signal.shift(1).fillna(0.0)
    warmup = max(int(anchor["bias_ma"]), int(anchor["mom_day"]), int(anchor["abs_ma"])) + 2
    return pd.DataFrame({"signal": exec_signal, "score": score, "r2": r2, "abs_bias": abs_bias}, index=panel.index).iloc[warmup:].copy()


def returns_for(panel: pd.DataFrame, sig: pd.DataFrame, tv: float | None, vw: int | None, max_lev: float | None) -> pd.DataFrame:
    d = pd.concat([sig, panel[["spread_return"]]], axis=1).dropna().copy()
    if tv is None:
        scale = d["signal"]
        raw_scale = pd.Series(1.0, index=d.index)
        realized_vol = d["spread_return"].rolling(40).std() * np.sqrt(base.ANNUALIZATION_DAYS)
    else:
        realized_vol = d["spread_return"].rolling(int(vw)).std() * np.sqrt(base.ANNUALIZATION_DAYS)
        raw_scale = (float(tv) / realized_vol).clip(MIN_LEVERAGE, float(max_lev)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        scale = d["signal"] * raw_scale
    turnover = scale.diff().abs().fillna(scale.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = scale * d["spread_return"]
    ret = gross_return - cost
    return pd.DataFrame({"return": ret, "gross_return": gross_return, "cost": cost, "turnover": turnover, "weight": scale, "raw_scale": raw_scale, "realized_vol": realized_vol}, index=d.index)


def make_grid():
    for anchor in ANCHORS:
        yield {**anchor, "candidate": f"l3dd_{anchor['anchor']}_tv_off", "target_vol": 0.0, "vol_window": 0, "max_leverage": 1.0, "tv_enabled": False}
        for tv in TARGET_VOLS:
            for vw in VOL_WINDOWS:
                for max_lev in MAX_LEVERAGES:
                    yield {**anchor, "candidate": f"l3dd_{anchor['anchor']}_tv{fmt(tv, True)}_vw{vw}_max{fmt(max_lev)}", "target_vol": tv, "vol_window": vw, "max_leverage": max_lev, "tv_enabled": True}


def add_tiers(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["tv_enabled"] == False].set_index("anchor")
    for col in ["ann_return_full", "max_dd_full", "ann_return_last_5y", "max_dd_last_5y", "sharpe_repo_full"]:
        out[f"base_{col}"] = out["anchor"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (out["tv_enabled"] == True) & (out["full_ann_loss_pp"] <= tier + 1e-12) & (out["full_dd_improve_pp"] > 0)
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for anchor, d in wm[wm["tv_enabled"] == True].groupby("anchor"):
            p = d[d[pass_col]].copy()
            if p.empty:
                rows.append({"loss_tier_pp": tier, "anchor": anchor, "pass_count": 0, "target_vol_count": 0, "window_count": 0, "maxlev_count": 0, "best_candidate": "", "best_full_ann_return": np.nan, "best_full_max_dd": np.nan, "best_full_ann_loss_pp": np.nan, "best_full_dd_improve_pp": np.nan, "best_5y_ann_return": np.nan, "best_5y_max_dd": np.nan, "patch_like": False})
                continue
            best = p.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(len(p) >= 4 and p["target_vol"].nunique() >= 2 and p["vol_window"].nunique() >= 2)
            rows.append({"loss_tier_pp": tier, "anchor": anchor, "pass_count": int(len(p)), "target_vol_count": int(p["target_vol"].nunique()), "window_count": int(p["vol_window"].nunique()), "maxlev_count": int(p["max_leverage"].nunique()), "best_candidate": best["candidate"], "best_full_ann_return": best["ann_return_full"], "best_full_max_dd": best["max_dd_full"], "best_full_ann_loss_pp": best["full_ann_loss_pp"], "best_full_dd_improve_pp": best["full_dd_improve_pp"], "best_5y_ann_return": best["ann_return_last_5y"], "best_5y_max_dd": best["max_dd_last_5y"], "patch_like": patch_like})
    return pd.DataFrame(rows).sort_values(["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"], ascending=[True, False, False, False])


def main() -> None:
    mod, cyb, sz50, panel = load_panel()
    signals = {a["anchor"]: anchor_signal(panel, a) for a in ANCHORS}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = list(make_grid())
    long_rows = []
    wide_rows = []
    daily_parts = []
    for cand in grid:
        result = returns_for(panel, signals[cand["anchor"]], None if not cand["tv_enabled"] else float(cand["target_vol"]), None if not cand["tv_enabled"] else int(cand["vol_window"]), None if not cand["tv_enabled"] else float(cand["max_leverage"]))
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily_parts.append(daily.reset_index(names="date"))
        wide = {**cand}
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
    cols = ["candidate", "anchor", "target_vol", "vol_window", "max_leverage", "ann_return_full", "max_dd_full", "full_ann_loss_pp", "full_dd_improve_pp", "ann_return_last_5y", "max_dd_last_5y", "fivey_ann_loss_pp", "fivey_dd_improve_pp", "sharpe_repo_full"]
    record_lines = [
        "# CYB/SZ50 Layer 3 Target-Vol After DD-First Layer 2",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer3_after_l2_dd_first_complete_not_promoted`",
        "- stability: `target_vol_dd_first_patch_review`",
        "",
        "## Research Question",
        "Test target-vol sizing after the Layer 2 DD-first anchors, allowing annual return loss tiers in exchange for drawdown reduction.",
        "",
        "## Implementation Anchor",
        "- Imports metric and signal helpers from `scan_adk_cyb_sz50_spread_long_only.py`.",
        "- Anchors are `lowdd80 score5` abs-filter candidates from the Layer 2 DD-first rescan.",
        "",
        "## Data Snapshot",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- SZ50 rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal -> T+1 close-to-close spread return.",
        "- Two-leg transaction cost with one-way commission 0.0005 on exposure and scale changes.",
        "- No NAV defense, overheat, amount, or momentum-decay overlay is applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_cyb_sz50_spread_layer3_after_l2_dd_first_target_vol.py\"`",
        "- `python \"scan_adk_cyb_sz50_spread_layer3_after_l2_dd_first_target_vol.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `dd_first_pass_loss_le_2p0pp.csv`",
        "- `dd_first_pass_loss_le_3p0pp.csv`",
        "- `dd_first_pass_loss_le_5p0pp.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        top_by_tier[2.0][cols].head(20).to_markdown(index=False) if not top_by_tier[2.0].empty else "No candidates passed loss<=2pp with DD improvement.",
        "",
        "## Window Results",
        top_by_tier[3.0][cols].head(20).to_markdown(index=False) if not top_by_tier[3.0].empty else "No candidates passed loss<=3pp with DD improvement.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 3 completed but not promoted. Stop for user review before NAV/state-defense layer.",
        "",
        "## User-Facing Summary",
        f"- loss<=2pp pass count: {len(top_by_tier[2.0])}",
        f"- loss<=3pp pass count: {len(top_by_tier[3.0])}",
        f"- loss<=5pp pass count: {len(top_by_tier[5.0])}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")
    meta = {"run_id": RUN_DIR.name, "created_at": datetime.now().isoformat(timespec="seconds"), "project": "A-share / US momentum combo", "strategy": "V7.7 ADK spread research", "repo_root": str(base.ROOT), "entrypoint": str(Path(__file__).name), "implementation_anchor": "scan_adk_cyb_sz50_spread_long_only.py", "git_branch": "not_checked_agent_policy", "git_commit": "not_checked_agent_policy", "git_status_before": "not_checked_agent_policy", "git_status_after": "not_checked_agent_policy", "scan_type": "fresh_layer3_target_vol_after_l2_dd_first", "parameter_group": "target_vol_window_max_leverage", "baseline": {"anchors": ANCHORS, "loss_tiers_pp": LOSS_TIERS}, "candidate_grid": grid, "cost_model": {"one_way_commission": base.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return"}, "data_snapshot": {"source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via layer1 harness", "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())}}, "decision": "layer3_after_l2_dd_first_complete_not_promoted", "stability_label": "target_vol_dd_first_patch_review", "outputs": {"record": str(RUN_DIR / "record.md"), "scan_summary": str(RUN_DIR / "scan_summary.csv"), "window_metrics": str(RUN_DIR / "window_metrics.csv"), "scan_meta": str(RUN_DIR / "scan_meta.json"), "command_log": str(RUN_DIR / "command_log.txt"), "daily_curves": str(RUN_DIR / "daily_curves.csv"), "ridge_width": str(RUN_DIR / "ridge_width.csv")}}
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text("python -m py_compile \"scan_adk_cyb_sz50_spread_layer3_after_l2_dd_first_target_vol.py\"\npython \"scan_adk_cyb_sz50_spread_layer3_after_l2_dd_first_target_vol.py\"\npython C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n", encoding="utf-8")
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("BASELINES")
    print(window_metrics[window_metrics.tv_enabled == False][cols].to_string(index=False))
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_by_tier[tier])}")
        print(top_by_tier[tier][cols].head(12).to_string(index=False) if not top_by_tier[tier].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

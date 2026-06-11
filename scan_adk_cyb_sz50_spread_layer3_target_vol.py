"""Layer 3 target-vol scan for CYB/SZ50 after strict Layer 2 anchors.

Pass rule: each target-vol candidate is compared against its own tv_off anchor.
A useful target-vol layer must not reduce full-sample annual return or worsen
full-sample max drawdown versus the pre-condition anchor, and should form a
neighboring patch. Strict mode also checks 5Y parity.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_sz50_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260609_adk_cyb_sz50_spread_long_only_v77_adk_spread_layer3_target_vol_strict_l2_anchors"

ANCHORS = [
    {"anchor": "main_abs35_m3p5", "bias_ma": 75, "mom_day": 28, "weight_end": 2.5, "score_threshold": 0.0, "abs_ma": 35, "abs_threshold": -0.035},
    {"anchor": "neighbor_abs30_m4", "bias_ma": 75, "mom_day": 28, "weight_end": 2.5, "score_threshold": 0.0, "abs_ma": 30, "abs_threshold": -0.040},
    {"anchor": "lowdd_abs70_m5p5", "bias_ma": 75, "mom_day": 28, "weight_end": 2.5, "score_threshold": 0.0, "abs_ma": 70, "abs_threshold": -0.055},
]
TARGET_VOLS = [0.08, 0.10, 0.12, 0.14, 0.16, 0.20]
VOL_WINDOWS = [20, 30, 40, 60, 90, 120]
MAX_LEVERAGES = [1.0, 1.25, 1.5]
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
        raw_scale = pd.Series(1.0, index=d.index)
        scale = d["signal"]
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
        yield {**anchor, "candidate": f"l3_{anchor['anchor']}_tv_off", "target_vol": 0.0, "vol_window": 0, "max_leverage": 1.0, "tv_enabled": False}
        for tv in TARGET_VOLS:
            for vw in VOL_WINDOWS:
                for max_lev in MAX_LEVERAGES:
                    yield {**anchor, "candidate": f"l3_{anchor['anchor']}_tv{fmt(tv, True)}_vw{vw}_max{fmt(max_lev)}", "target_vol": tv, "vol_window": vw, "max_leverage": max_lev, "tv_enabled": True}


def add_pass_columns(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    baselines = out[out["tv_enabled"] == False].set_index("anchor")
    for col in ["ann_return_full", "max_dd_full", "ann_return_last_5y", "max_dd_last_5y"]:
        out[f"base_{col}"] = out["anchor"].map(baselines[col])
    out["pass_full_ann_dd"] = (out["ann_return_full"] >= out["base_ann_return_full"] - 1e-12) & (out["max_dd_full"] >= out["base_max_dd_full"] - 1e-12)
    out["pass_5y_ann_dd"] = (out["ann_return_last_5y"] >= out["base_ann_return_last_5y"] - 1e-12) & (out["max_dd_last_5y"] >= out["base_max_dd_last_5y"] - 1e-12)
    out["pass_full_and_5y"] = out["pass_full_ann_dd"] & out["pass_5y_ann_dd"]
    return out


def patch_summary(wm: pd.DataFrame, pass_col: str) -> pd.DataFrame:
    rows = []
    cand = wm[wm["tv_enabled"] == True].copy()
    for anchor, d in cand.groupby("anchor"):
        p = d[d[pass_col]].copy()
        if p.empty:
            rows.append({"anchor": anchor, "pass_rule": pass_col, "pass_count": 0, "target_vol_count": 0, "window_count": 0, "maxlev_count": 0, "best_candidate": "", "best_full_ann_return": np.nan, "best_full_max_dd": np.nan, "best_5y_ann_return": np.nan, "best_5y_max_dd": np.nan, "patch_like": False})
            continue
        best = p.sort_values(["ann_return_full", "max_dd_full"], ascending=[False, False]).iloc[0]
        tv_count = p["target_vol"].nunique()
        window_count = p["vol_window"].nunique()
        maxlev_count = p["max_leverage"].nunique()
        patch_like = bool(len(p) >= 4 and tv_count >= 2 and window_count >= 2)
        rows.append({"anchor": anchor, "pass_rule": pass_col, "pass_count": int(len(p)), "target_vol_count": int(tv_count), "window_count": int(window_count), "maxlev_count": int(maxlev_count), "best_candidate": best["candidate"], "best_full_ann_return": best["ann_return_full"], "best_full_max_dd": best["max_dd_full"], "best_5y_ann_return": best["ann_return_last_5y"], "best_5y_max_dd": best["max_dd_last_5y"], "patch_like": patch_like})
    return pd.DataFrame(rows).sort_values(["pass_rule", "patch_like", "pass_count"], ascending=[True, False, False])


def main() -> None:
    mod, cyb, sz50, panel = load_panel()
    signals = {a["anchor"]: anchor_signal(panel, a) for a in ANCHORS}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    long_rows = []
    wide_rows = []
    daily_parts = []
    grid = list(make_grid())
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
    window_metrics = add_pass_columns(pd.DataFrame(wide_rows))
    ridge = pd.concat([patch_summary(window_metrics, "pass_full_ann_dd"), patch_summary(window_metrics, "pass_full_and_5y")], ignore_index=True)
    full_pass = window_metrics[(window_metrics["tv_enabled"] == True) & window_metrics["pass_full_ann_dd"]].sort_values(["ann_return_full", "max_dd_full"], ascending=[False, False])
    strict_pass = window_metrics[(window_metrics["tv_enabled"] == True) & window_metrics["pass_full_and_5y"]].sort_values(["ann_return_full", "max_dd_full"], ascending=[False, False])
    daily_all = pd.concat(daily_parts, ignore_index=True)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")

    cols = ["candidate", "anchor", "target_vol", "vol_window", "max_leverage", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "pass_full_ann_dd", "pass_full_and_5y"]
    record_lines = [
        "# CYB/SZ50 Layer 3 Target-Vol Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer3_target_vol_complete_not_promoted`",
        "- stability: `target_vol_width_pending_review`",
        "",
        "## Research Question",
        "Test target-vol sizing on the strict Layer 2 anchors, comparing every candidate to its own tv-off baseline.",
        "",
        "## Implementation Anchor",
        "- Imports metric and signal helpers from `scan_adk_cyb_sz50_spread_long_only.py`.",
        "- Target-vol is based on rolling realized volatility of CYB-SZ50 close-to-close spread returns.",
        "",
        "## Data Snapshot",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- SZ50 rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal -> T+1 close-to-close spread return.",
        "- Two-leg transaction cost with one-way commission 0.0005 on exposure changes, including scale changes.",
        "- No NAV defense, overheat, amount, or momentum-decay overlay is applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_cyb_sz50_spread_layer3_target_vol.py\"`",
        "- `python \"scan_adk_cyb_sz50_spread_layer3_target_vol.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `full_baseline_pass_candidates.csv`",
        "- `full_and_5y_pass_candidates.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        full_pass[cols].head(20).to_markdown(index=False) if not full_pass.empty else "No target-vol candidate passed full baseline comparison.",
        "",
        "## Window Results",
        strict_pass[cols].head(20).to_markdown(index=False) if not strict_pass.empty else "No target-vol candidate passed full+5Y baseline comparison.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 3 completed but not promoted. Stop for review before NAV/state-defense layers.",
        "",
        "## User-Facing Summary",
        f"- full_baseline_pass_count: {len(full_pass)}",
        f"- full_and_5y_pass_count: {len(strict_pass)}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_cyb_sz50_spread_long_only.py",
        "git_branch": "not_checked_agent_policy",
        "git_commit": "not_checked_agent_policy",
        "git_status_before": "not_checked_agent_policy",
        "git_status_after": "not_checked_agent_policy",
        "scan_type": "fresh_layer3_target_vol",
        "parameter_group": "target_vol_window_max_leverage",
        "baseline": {"anchors": ANCHORS, "pass_rule": "target-vol candidate must not underperform same-anchor tv-off baseline"},
        "candidate_grid": grid,
        "cost_model": {"one_way_commission": base.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return"},
        "data_snapshot": {"source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via layer1 harness", "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())}},
        "decision": "layer3_target_vol_complete_not_promoted",
        "stability_label": "target_vol_width_pending_review",
        "outputs": {"record": str(RUN_DIR / "record.md"), "scan_summary": str(RUN_DIR / "scan_summary.csv"), "window_metrics": str(RUN_DIR / "window_metrics.csv"), "scan_meta": str(RUN_DIR / "scan_meta.json"), "command_log": str(RUN_DIR / "command_log.txt"), "daily_curves": str(RUN_DIR / "daily_curves.csv"), "ridge_width": str(RUN_DIR / "ridge_width.csv")},
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_cyb_sz50_spread_layer3_target_vol.py\"\n"
        "python \"scan_adk_cyb_sz50_spread_layer3_target_vol.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(f"FULL_PASS_COUNT={len(full_pass)} STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)}")
    print("BASELINES")
    print(window_metrics[window_metrics.tv_enabled == False][cols].to_string(index=False))
    print("FULL_PASS_TOP")
    print(full_pass[cols].head(20).to_string(index=False) if not full_pass.empty else "NONE")
    print("STRICT_PASS_TOP")
    print(strict_pass[cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

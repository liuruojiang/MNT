"""Layer 2 DD-first rescan for CYB/ZZ1000 score/absolute-bias filters.

This rescans Layer 2 using the user's revised standard: this layer is mainly
allowed to reduce drawdown, with modest annual-return sacrifice accepted. The
script reports loss tiers (<=2pp, <=3pp, <=5pp) and patch width around pass cells.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_zz1000_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260611_adk_cyb_zz1000_spread_long_only_v77_adk_spread_layer2_score_abs_filter_three_layer1_anchors"

ANCHORS = [
    {"anchor": "main_50_20_we4", "bias_ma": 50, "mom_day": 20, "weight_end": 4.0},
    {"anchor": "neighbor_45_20_we4", "bias_ma": 45, "mom_day": 20, "weight_end": 4.0},
    {"anchor": "conservative_55_20_we1", "bias_ma": 55, "mom_day": 20, "weight_end": 1.0},
]
SCORE_THRESHOLDS = [-2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.5, 10.0]
ABS_MAS = list(range(20, 81, 5))
ABS_THRESHOLDS = [round(x, 3) for x in np.arange(-0.08, 0.0801, 0.005)]
LOSS_TIERS = [1.0, 2.0, 3.0]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def load_panel():
    mod = base.load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    zz1000 = mod._load_cn_official_cache(mod.CN_DK_ZZ1000_SECID).rename(columns={"close": "ZZ1000"})
    panel = pd.concat([cyb["CYB"], zz1000["ZZ1000"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["CYB"] / panel["ZZ1000"]
    panel["spread_return"] = panel["CYB"].pct_change().fillna(0.0) - panel["ZZ1000"].pct_change().fillna(0.0)
    return mod, cyb, zz1000, panel


def precompute(panel: pd.DataFrame):
    ratio = panel["ratio"]
    scores = {}
    r2s = {}
    for anchor in ANCHORS:
        feature = ratio / ratio.rolling(int(anchor["bias_ma"])).mean() - 1.0
        scores[anchor["anchor"]] = base.weighted_slope_score(feature, int(anchor["mom_day"]), float(anchor["weight_end"]))
        r2s[anchor["anchor"]] = base.weighted_slope_r2(feature, int(anchor["mom_day"]), float(anchor["weight_end"]))
    abs_bias = {ma: ratio / ratio.rolling(ma).mean() - 1.0 for ma in ABS_MAS}
    return scores, r2s, abs_bias


def candidate_returns(panel: pd.DataFrame, score: pd.Series, r2: pd.Series, abs_series: pd.Series | None, score_thr: float, abs_thr: float | None, warmup: int) -> pd.DataFrame:
    signal = (score > score_thr) & (r2 >= 0.05)
    if abs_series is not None and abs_thr is not None:
        signal = signal & (abs_series > abs_thr)
    weight = signal.astype(float).shift(1).fillna(0.0)
    turnover = weight.diff().abs().fillna(weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = weight * panel["spread_return"]
    ret = gross_return - cost
    return pd.DataFrame({"return": ret, "gross_return": gross_return, "cost": cost, "turnover": turnover, "weight": weight}, index=panel.index).iloc[warmup:].copy()


def make_grid():
    for anchor in ANCHORS:
        for score_thr in SCORE_THRESHOLDS:
            yield {**anchor, "candidate": f"l2dd_{anchor['anchor']}_score{fmt_num(score_thr)}_abs_off", "score_threshold": score_thr, "abs_ma": 0, "abs_threshold": -999.0, "abs_filter": "off"}
            for abs_ma in ABS_MAS:
                for abs_thr in ABS_THRESHOLDS:
                    yield {**anchor, "candidate": f"l2dd_{anchor['anchor']}_score{fmt_num(score_thr)}_abs{abs_ma}_gt_{fmt_num(abs_thr, True)}pct", "score_threshold": score_thr, "abs_ma": abs_ma, "abs_threshold": abs_thr, "abs_filter": "ratio_bias"}


def add_baseline_and_tiers(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    baselines = out[(out["score_threshold"] == 0.0) & (out["abs_filter"] == "off")].set_index("anchor")
    for col in ["ann_return_full", "max_dd_full", "ann_return_last_5y", "max_dd_last_5y", "sharpe_repo_full"]:
        out[f"base_{col}"] = out["anchor"].map(baselines[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100.0
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100.0
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100.0
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100.0
    out["pass_full_ann_dd"] = (out["ann_return_full"] >= out["base_ann_return_full"] - 1e-12) & (out["max_dd_full"] >= out["base_max_dd_full"] - 1e-12)
    out["pass_full_and_5y"] = out["pass_full_ann_dd"] & (out["ann_return_last_5y"] >= out["base_ann_return_last_5y"] - 1e-12) & (out["max_dd_last_5y"] >= out["base_max_dd_last_5y"] - 1e-12)
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (out["full_ann_loss_pp"] <= tier + 1e-12) & (out["full_dd_improve_pp"] > 0) & (out["fivey_dd_improve_pp"] >= -1e-12)
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        cand = wm[(wm["abs_filter"] == "ratio_bias") & wm[pass_col]].copy()
        for (anchor, score_thr), d in wm[wm["abs_filter"] == "ratio_bias"].groupby(["anchor", "score_threshold"]):
            p = d[d[pass_col]].copy()
            if p.empty:
                rows.append({"loss_tier_pp": tier, "anchor": anchor, "score_threshold": score_thr, "pass_count": 0, "ma_count": 0, "threshold_count": 0, "best_candidate": "", "best_full_ann_return": np.nan, "best_full_max_dd": np.nan, "best_full_ann_loss_pp": np.nan, "best_full_dd_improve_pp": np.nan, "best_5y_ann_return": np.nan, "best_5y_max_dd": np.nan, "patch_like": False})
                continue
            best = p.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            thrs = sorted(p["abs_threshold"].unique())
            adjacent_thr = any(round(thrs[i + 1] - thrs[i], 3) <= 0.006 for i in range(len(thrs) - 1))
            patch_like = bool(len(p) >= 4 and p["abs_ma"].nunique() >= 2 and p["abs_threshold"].nunique() >= 2 and adjacent_thr)
            rows.append({
                "loss_tier_pp": tier,
                "anchor": anchor,
                "score_threshold": score_thr,
                "pass_count": int(len(p)),
                "ma_count": int(p["abs_ma"].nunique()),
                "threshold_count": int(p["abs_threshold"].nunique()),
                "best_candidate": best["candidate"],
                "best_full_ann_return": best["ann_return_full"],
                "best_full_max_dd": best["max_dd_full"],
                "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                "best_full_dd_improve_pp": best["full_dd_improve_pp"],
                "best_5y_ann_return": best["ann_return_last_5y"],
                "best_5y_max_dd": best["max_dd_last_5y"],
                "patch_like": patch_like,
            })
    return pd.DataFrame(rows).sort_values(["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"], ascending=[True, False, False, False])


def main() -> None:
    mod, cyb, zz1000, panel = load_panel()
    scores, r2s, abs_bias = precompute(panel)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = list(make_grid())
    long_rows = []
    wide_rows = []
    for cand in grid:
        abs_ma = int(cand["abs_ma"])
        result = candidate_returns(
            panel,
            scores[cand["anchor"]],
            r2s[cand["anchor"]],
            None if abs_ma == 0 else abs_bias[abs_ma],
            float(cand["score_threshold"]),
            None if abs_ma == 0 else float(cand["abs_threshold"]),
            max(int(cand["bias_ma"]), int(cand["mom_day"]), abs_ma) + 2,
        )
        wide = {**cand}
        for segment, years in base.SEGMENTS:
            m = base.metrics_for_segment(result, segment, years)
            long_rows.append({**cand, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)
    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baseline_and_tiers(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    cols = ["candidate", "anchor", "score_threshold", "abs_ma", "abs_threshold", "ann_return_full", "max_dd_full", "full_ann_loss_pp", "full_dd_improve_pp", "ann_return_last_5y", "max_dd_last_5y", "fivey_ann_loss_pp", "fivey_dd_improve_pp", "sharpe_repo_full"]
    full_pass = window_metrics[(window_metrics["pass_full_ann_dd"]) & (window_metrics["abs_filter"] == "ratio_bias")].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
    strict_pass = window_metrics[(window_metrics["pass_full_and_5y"]) & (window_metrics["abs_filter"] == "ratio_bias")].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
    top_by_tier = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        passed = window_metrics[(window_metrics[pass_col]) & (window_metrics["abs_filter"] == "ratio_bias")].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_by_tier[tier] = passed

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# CYB/ZZ1000 Layer 2 Score And Absolute-Bias Filter Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer2_score_abs_complete_not_promoted`",
        "- stability: `strict_and_dd_first_patch_review`",
        "",
        "## Research Question",
        "Scan Layer 2 score thresholds and absolute ratio-bias filters against the exact Layer 1 anchors, with strict full+5Y non-underperformance and DD-first patch checks.",
        "",
        "## Implementation Anchor",
        "- Imports metric and signal helpers from `scan_adk_cyb_zz1000_spread_long_only.py`.",
        "- Baselines are the three Layer 1 anchors with score0 and abs filter off.",
        "",
        "## Data Snapshot",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- ZZ1000 rows: {len(zz1000)}, start {zz1000.index.min().date()}, end {zz1000.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal -> T+1 close-to-close spread return.",
        "- Two-leg transaction cost with one-way commission 0.0005 on exposure changes.",
        "- No target-vol, NAV defense, overheat, amount, or momentum-decay overlay is applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_cyb_zz1000_spread_layer2_score_abs_filter.py\"`",
        "- `python \"scan_adk_cyb_zz1000_spread_layer2_score_abs_filter.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `ridge_width.csv`",
        "- `full_baseline_pass_candidates.csv`",
        "- `full_and_5y_pass_candidates.csv`",
        "- `dd_first_pass_loss_le_1p0pp.csv`",
        "- `dd_first_pass_loss_le_2p0pp.csv`",
        "- `dd_first_pass_loss_le_3p0pp.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        full_pass[cols].head(20).to_markdown(index=False) if not full_pass.empty else "No candidates passed strict full-sample annual-return and drawdown non-underperformance.",
        "",
        "## Window Results",
        strict_pass[cols].head(20).to_markdown(index=False) if not strict_pass.empty else "No candidates passed strict full+5Y annual-return and drawdown non-underperformance.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 2 score/absolute-bias scan completed but not promoted. Stop for user review before choosing Layer 3 inputs.",
        "",
        "## User-Facing Summary",
        f"- strict full pass count: {len(full_pass)}",
        f"- strict full+5Y pass count: {len(strict_pass)}",
        f"- loss<=2pp pass count: {len(top_by_tier[2.0])}",
        f"- loss<=3pp pass count: {len(top_by_tier[3.0])}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_cyb_zz1000_spread_long_only.py",
        "git_branch": "not_checked_agent_policy",
        "git_commit": "not_checked_agent_policy",
        "git_status_before": "not_checked_agent_policy",
        "git_status_after": "not_checked_agent_policy",
        "scan_type": "fresh_layer2_score_abs_filter",
        "parameter_group": "score_threshold_abs_bias_filter",
        "baseline": {"anchors": ANCHORS, "loss_tiers_pp": LOSS_TIERS},
        "candidate_grid": grid,
        "cost_model": {"one_way_commission": base.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return"},
        "data_snapshot": {"source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via layer1 harness", "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())}},
        "decision": "layer2_score_abs_complete_not_promoted",
        "stability_label": "strict_and_dd_first_patch_review",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "full_baseline_pass_candidates": str(RUN_DIR / "full_baseline_pass_candidates.csv"),
            "full_and_5y_pass_candidates": str(RUN_DIR / "full_and_5y_pass_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_cyb_zz1000_spread_layer2_score_abs_filter.py\"\n"
        "python \"scan_adk_cyb_zz1000_spread_layer2_score_abs_filter.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_by_tier[tier])}")
        print(top_by_tier[tier][cols].head(12).to_string(index=False) if not top_by_tier[tier].empty else "NONE")
    print(f"STRICT_FULL_PASS_COUNT={len(full_pass)}")
    print(full_pass[cols].head(12).to_string(index=False) if not full_pass.empty else "NONE")
    print(f"STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)}")
    print(strict_pass[cols].head(12).to_string(index=False) if not strict_pass.empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()


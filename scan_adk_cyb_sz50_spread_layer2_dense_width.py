"""Layer 2 dense width scan for CYB/SZ50 score/absolute-bias filters.

Pass rule follows the user's process rule: compare each filtered candidate against
its own unfiltered Layer 1 anchor before adding the condition. A useful patch
must not be worse than the pre-condition anchor and must have neighboring points.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_sz50_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260609_adk_cyb_sz50_spread_long_only_v77_adk_spread_layer2_dense_width_score_abs_filter"

ANCHORS = [
    {"anchor": "return_75_28_we2p5", "bias_ma": 75, "mom_day": 28, "weight_end": 2.5, "base_ann": 0.156831, "base_dd": -0.259992, "base_ann5": 0.168521, "base_dd5": -0.155751},
    {"anchor": "lowdd_80_28_we2p5", "bias_ma": 80, "mom_day": 28, "weight_end": 2.5, "base_ann": 0.144277, "base_dd": -0.239022, "base_ann5": 0.138733, "base_dd5": -0.216000},
]
SCORE_THRESHOLDS = [-2.0, -1.0, 0.0, 1.0, 2.0]
ABS_MAS = list(range(20, 81, 5))
ABS_THRESHOLDS = [round(x, 3) for x in np.arange(-0.10, 0.0251, 0.005)]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    text = f"{abs(scaled):g}".replace(".", "p")
    return f"{sign}{text}"


def load_panel():
    mod = base.load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    sz50 = mod._load_cn_official_cache(mod.CN_DK_SZ50_SECID).rename(columns={"close": "SZ50"})
    panel = pd.concat([cyb["CYB"], sz50["SZ50"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["CYB"] / panel["SZ50"]
    return mod, cyb, sz50, panel


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


def candidate_returns(panel: pd.DataFrame, score: pd.Series, r2: pd.Series, abs_series: pd.Series, score_thr: float, abs_thr: float, warmup: int) -> pd.DataFrame:
    signal = ((score > score_thr) & (r2 >= 0.05) & (abs_series > abs_thr)).astype(float)
    weight = signal.shift(1).fillna(0.0)
    spread_return = panel["CYB"].pct_change().fillna(0.0) - panel["SZ50"].pct_change().fillna(0.0)
    turnover = weight.diff().abs().fillna(weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    ret = weight * spread_return - cost
    return pd.DataFrame({"return": ret, "weight": weight, "turnover": turnover, "cost": cost}, index=panel.index).iloc[warmup:].copy()


def make_grid():
    for anchor in ANCHORS:
        for score_thr in SCORE_THRESHOLDS:
            for abs_ma in ABS_MAS:
                for abs_thr in ABS_THRESHOLDS:
                    yield {
                        **anchor,
                        "candidate": f"l2dense_{anchor['anchor']}_score{fmt_num(score_thr)}_abs{abs_ma}_gt_{fmt_num(abs_thr, pct=True)}pct",
                        "score_threshold": score_thr,
                        "abs_ma": abs_ma,
                        "abs_threshold": abs_thr,
                    }


def add_pass_columns(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    out["pass_full_ann_dd"] = (out["ann_return_full"] >= out["base_ann"] - 1e-12) & (out["max_dd_full"] >= out["base_dd"] - 1e-12)
    out["pass_full_sharpe_dd"] = (out["sharpe_repo_full"] >= out.groupby("anchor")["sharpe_repo_full"].transform(lambda s: np.nan))
    out["pass_5y_ann_dd"] = (out["ann_return_last_5y"] >= out["base_ann5"] - 1e-12) & (out["max_dd_last_5y"] >= out["base_dd5"] - 1e-12)
    out["pass_full_and_5y"] = out["pass_full_ann_dd"] & out["pass_5y_ann_dd"]
    return out


def patch_summary(wm: pd.DataFrame, pass_col: str) -> pd.DataFrame:
    rows = []
    for (anchor, score_thr), d in wm.groupby(["anchor", "score_threshold"]):
        p = d[d[pass_col]].copy()
        if p.empty:
            rows.append({"anchor": anchor, "score_threshold": score_thr, "pass_rule": pass_col, "pass_count": 0, "ma_count": 0, "threshold_count": 0, "best_candidate": "", "best_full_ann_return": np.nan, "best_full_max_dd": np.nan, "patch_like": False})
            continue
        best = p.sort_values(["ann_return_full", "max_dd_full"], ascending=[False, False]).iloc[0]
        ma_count = p["abs_ma"].nunique()
        thr_count = p["abs_threshold"].nunique()
        # Simple patch criterion: at least 4 passing cells spanning at least 2 MAs and 2 adjacent thresholds.
        thr_values = sorted(p["abs_threshold"].unique())
        adjacent_thr = any(round(thr_values[i+1] - thr_values[i], 3) <= 0.006 for i in range(len(thr_values)-1))
        patch_like = bool(len(p) >= 4 and ma_count >= 2 and thr_count >= 2 and adjacent_thr)
        rows.append({
            "anchor": anchor,
            "score_threshold": score_thr,
            "pass_rule": pass_col,
            "pass_count": int(len(p)),
            "ma_count": int(ma_count),
            "threshold_count": int(thr_count),
            "best_candidate": best["candidate"],
            "best_full_ann_return": best["ann_return_full"],
            "best_full_max_dd": best["max_dd_full"],
            "best_5y_ann_return": best["ann_return_last_5y"],
            "best_5y_max_dd": best["max_dd_last_5y"],
            "patch_like": patch_like,
        })
    return pd.DataFrame(rows).sort_values(["pass_rule", "patch_like", "pass_count"], ascending=[True, False, False])


def main() -> None:
    mod, cyb, sz50, panel = load_panel()
    scores, r2s, abs_bias = precompute(panel)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    long_rows = []
    wide_rows = []
    grid = list(make_grid())
    for cand in grid:
        result = candidate_returns(
            panel,
            scores[cand["anchor"]],
            r2s[cand["anchor"]],
            abs_bias[int(cand["abs_ma"])],
            float(cand["score_threshold"]),
            float(cand["abs_threshold"]),
            max(int(cand["bias_ma"]), int(cand["mom_day"]), int(cand["abs_ma"])) + 2,
        )
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
    full_pass = window_metrics[window_metrics["pass_full_ann_dd"]].sort_values(["ann_return_full", "max_dd_full"], ascending=[False, False])
    strict_pass = window_metrics[window_metrics["pass_full_and_5y"]].sort_values(["ann_return_full", "max_dd_full"], ascending=[False, False])

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")

    cols = ["candidate", "anchor", "score_threshold", "abs_ma", "abs_threshold", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "pass_full_ann_dd", "pass_full_and_5y"]
    record_lines = [
        "# CYB/SZ50 Layer 2 Dense Width Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer2_dense_width_complete_not_promoted`",
        "- stability: `strict_width_requires_review`",
        "",
        "## Research Question",
        "Re-test Layer 2 filters using the user's width rule: filtered candidates must not underperform the pre-condition anchor, and passing cells should form a patch.",
        "",
        "## Implementation Anchor",
        "- Imports metric and signal helpers from `scan_adk_cyb_sz50_spread_long_only.py`.",
        "- Anchors are the same two Layer 1 dense anchors.",
        "",
        "## Data Snapshot",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- SZ50 rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- Same as prior layers: T close signal -> T+1 close-to-close spread return.",
        "- Two-leg transaction cost with one-way commission 0.0005 on exposure changes.",
        "- No target-vol, NAV defense, overheat, amount, or momentum-decay overlay is applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_cyb_sz50_spread_layer2_dense_width.py\"`",
        "- `python \"scan_adk_cyb_sz50_spread_layer2_dense_width.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `ridge_width.csv`",
        "- `full_baseline_pass_candidates.csv`",
        "- `full_and_5y_pass_candidates.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        full_pass[cols].head(20).to_markdown(index=False),
        "",
        "## Window Results",
        "Strict full+5Y pass candidates:",
        strict_pass[cols].head(20).to_markdown(index=False) if not strict_pass.empty else "No candidates passed both full-sample and 5Y anchor comparison.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 2 dense width completed but not promoted. Use `ridge_width.csv` to decide whether a full-only patch is acceptable or whether Layer 2 should be rejected under strict full+5Y parity.",
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
        "scan_type": "fresh_layer2_dense_width_score_abs_filter",
        "parameter_group": "score_threshold_abs_bias_filter_width",
        "baseline": {"anchors": ANCHORS, "pass_rule": "candidate metrics must not underperform same-anchor pre-condition baseline"},
        "candidate_grid": grid,
        "cost_model": {"one_way_commission": base.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return"},
        "data_snapshot": {"source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via layer1 harness", "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())}},
        "decision": "layer2_dense_width_complete_not_promoted",
        "stability_label": "strict_width_requires_review",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_cyb_sz50_spread_layer2_dense_width.py\"\n"
        "python \"scan_adk_cyb_sz50_spread_layer2_dense_width.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(f"FULL_PASS_COUNT={len(full_pass)} STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)}")
    print("FULL_PASS_TOP")
    print(full_pass[cols].head(20).to_string(index=False))
    print("STRICT_PASS_TOP")
    print((strict_pass[cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE"))
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

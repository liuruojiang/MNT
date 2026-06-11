"""Layer 2 filter scan for fresh ADK-style long CYB / short SZ50 spread.

Inputs are two Layer 1 dense anchors:
- return-led: bias_ma=75, mom_day=28, weight_end=2.5
- lower-DD: bias_ma=80, mom_day=28, weight_end=2.5

Layer 2 scans score entry thresholds and an absolute ratio-bias filter only.
No target-vol, NAV defense, overheat, amount, or momentum-decay overlay is applied.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_sz50_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260609_adk_cyb_sz50_spread_long_only_v77_adk_spread_layer2_score_abs_filter_anchor75_80"

ANCHORS = [
    {"anchor": "return_75_28_we2p5", "bias_ma": 75, "mom_day": 28, "weight_end": 2.5},
    {"anchor": "lowdd_80_28_we2p5", "bias_ma": 80, "mom_day": 28, "weight_end": 2.5},
]
SCORE_THRESHOLDS = [-10.0, -7.5, -5.0, -2.5, 0.0, 2.5, 5.0, 7.5, 10.0]
ABS_MAS = [20, 40, 60, 75, 80]
ABS_THRESHOLDS = [-0.10, -0.075, -0.05, -0.025, 0.0, 0.025, 0.05]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    text = f"{abs(scaled):g}".replace(".", "p")
    return f"{sign}{text}"


def candidate_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for anchor in ANCHORS:
        for score_thr in SCORE_THRESHOLDS:
            grid.append(
                {
                    **anchor,
                    "candidate": f"l2_{anchor['anchor']}_score{fmt_num(score_thr)}_abs_off",
                    "score_threshold": score_thr,
                    "abs_ma": 0,
                    "abs_threshold": -999.0,
                    "abs_filter": "off",
                }
            )
            for abs_ma in ABS_MAS:
                for abs_thr in ABS_THRESHOLDS:
                    grid.append(
                        {
                            **anchor,
                            "candidate": f"l2_{anchor['anchor']}_score{fmt_num(score_thr)}_abs{abs_ma}_gt_{fmt_num(abs_thr, pct=True)}pct",
                            "score_threshold": score_thr,
                            "abs_ma": abs_ma,
                            "abs_threshold": abs_thr,
                            "abs_filter": "ratio_bias",
                        }
                    )
    return grid


def build_panel(mod) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    sz50 = mod._load_cn_official_cache(mod.CN_DK_SZ50_SECID).rename(columns={"close": "SZ50"})
    panel = pd.concat([cyb["CYB"], sz50["SZ50"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["CYB"] / panel["SZ50"]
    return panel, cyb, sz50


def precompute_features(panel: pd.DataFrame) -> tuple[dict[str, pd.Series], dict[str, pd.Series], dict[int, pd.Series]]:
    ratio = panel["ratio"]
    score_by_anchor: dict[str, pd.Series] = {}
    r2_by_anchor: dict[str, pd.Series] = {}
    for anchor in ANCHORS:
        feature = ratio / ratio.rolling(int(anchor["bias_ma"])).mean() - 1.0
        score_by_anchor[str(anchor["anchor"])] = base.weighted_slope_score(
            feature,
            int(anchor["mom_day"]),
            float(anchor["weight_end"]),
        )
        r2_by_anchor[str(anchor["anchor"])] = base.weighted_slope_r2(
            feature,
            int(anchor["mom_day"]),
            float(anchor["weight_end"]),
        )
    abs_bias_by_ma = {ma: ratio / ratio.rolling(ma).mean() - 1.0 for ma in ABS_MAS}
    return score_by_anchor, r2_by_anchor, abs_bias_by_ma


def build_candidate_returns(
    panel: pd.DataFrame,
    candidate: dict[str, object],
    score_by_anchor: dict[str, pd.Series],
    r2_by_anchor: dict[str, pd.Series],
    abs_bias_by_ma: dict[int, pd.Series],
) -> pd.DataFrame:
    anchor_name = str(candidate["anchor"])
    score = score_by_anchor[anchor_name]
    r2 = r2_by_anchor[anchor_name]
    signal = (score > float(candidate["score_threshold"])) & (r2 >= 0.05)
    abs_ma = int(candidate["abs_ma"])
    if abs_ma > 0:
        abs_bias = abs_bias_by_ma[abs_ma]
        signal = signal & (abs_bias > float(candidate["abs_threshold"]))
    else:
        abs_bias = pd.Series(np.nan, index=panel.index)
    raw_signal = signal.astype(float)
    exec_weight = raw_signal.shift(1).fillna(0.0)
    spread_return = panel["CYB"].pct_change().fillna(0.0) - panel["SZ50"].pct_change().fillna(0.0)
    turnover = exec_weight.diff().abs().fillna(exec_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    ret = exec_weight * spread_return - cost
    warmup = max(int(candidate["bias_ma"]), int(candidate["mom_day"]), abs_ma) + 2
    out = pd.DataFrame(
        {
            "return": ret,
            "gross_return": exec_weight * spread_return,
            "cost": cost,
            "turnover": turnover,
            "weight": exec_weight,
            "raw_signal": raw_signal,
            "score": score,
            "r2": r2,
            "abs_bias": abs_bias,
            "ratio": panel["ratio"],
            "spread_return": spread_return,
        },
        index=panel.index,
    )
    return out.iloc[warmup:].copy()


def build_ridge(window_metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, df in window_metrics.groupby(["anchor", "abs_filter", "abs_ma"]):
        best = df.sort_values("sharpe_repo_full", ascending=False).iloc[0]
        rows.append(
            {
                "anchor": keys[0],
                "abs_filter": keys[1],
                "abs_ma": keys[2],
                "best_candidate": best["candidate"],
                "best_score_threshold": best["score_threshold"],
                "best_abs_threshold": best["abs_threshold"],
                "best_full_ann_return": best["ann_return_full"],
                "best_full_max_dd": best["max_dd_full"],
                "best_full_sharpe": best["sharpe_repo_full"],
                "best_5y_ann_return": best["ann_return_last_5y"],
                "best_5y_max_dd": best["max_dd_last_5y"],
                "candidate_count": int(len(df)),
            }
        )
    return pd.DataFrame(rows).sort_values("best_full_sharpe", ascending=False)


def main() -> None:
    mod = base.load_v77()
    panel, cyb, sz50 = build_panel(mod)
    score_by_anchor, r2_by_anchor, abs_bias_by_ma = precompute_features(panel)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    grid = candidate_grid()
    long_rows = []
    wide_rows = []
    daily_curves = []

    for candidate in grid:
        result = build_candidate_returns(panel, candidate, score_by_anchor, r2_by_anchor, abs_bias_by_ma)
        nav = (1.0 + result["return"]).cumprod()
        out = result.copy()
        out["nav"] = nav
        out["candidate"] = candidate["candidate"]
        daily_curves.append(out.reset_index(names="date"))

        wide = {**candidate}
        for segment, years in base.SEGMENTS:
            m = base.metrics_for_segment(result, segment, years)
            long_rows.append({**candidate, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = pd.DataFrame(wide_rows)
    daily = pd.concat(daily_curves, ignore_index=True)
    ridge = build_ridge(window_metrics)
    top = window_metrics.sort_values("sharpe_repo_full", ascending=False).head(20)
    practical = window_metrics[
        (window_metrics["ann_return_full"] >= 0.11)
        & (window_metrics["max_dd_full"] >= -0.22)
        & (window_metrics["ann_return_last_5y"] >= 0.08)
    ].sort_values(["max_dd_full", "sharpe_repo_full"], ascending=[False, False]).head(20)
    if practical.empty:
        practical = window_metrics.sort_values(["max_dd_full", "sharpe_repo_full"], ascending=[False, False]).head(20)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    practical.to_csv(RUN_DIR / "practical_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# CYB/SZ50 Fresh ADK Spread Layer 2 Score / Abs Filter Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer2_complete_not_promoted`",
        "- stability: `score_abs_filter_patch_pending_review`",
        "",
        "## Research Question",
        "Test score threshold and absolute ratio-bias filters on the two Layer 1 dense anchors.",
        "",
        "## Implementation Anchor",
        "- Imports metric and signal helpers from `scan_adk_cyb_sz50_spread_long_only.py`.",
        "- Anchors: `75/28/we2.5` and `80/28/we2.5`.",
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
        "- `python -m py_compile \"scan_adk_cyb_sz50_spread_layer2_score_abs_filter.py\"`",
        "- `python \"scan_adk_cyb_sz50_spread_layer2_score_abs_filter.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `practical_candidates.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        top[["candidate", "anchor", "score_threshold", "abs_ma", "abs_threshold", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]].to_markdown(index=False),
        "",
        "## Window Results",
        "See `window_metrics.csv` and `practical_candidates.csv`.",
        "",
        "## Stability Classification",
        ridge.head(30).to_markdown(index=False),
        "",
        "## Decision",
        "Layer 2 completed but not promoted. Stop for user confirmation before selecting anchors for target-vol/state-defense layers.",
        "",
        "## User-Facing Summary",
        practical[["candidate", "anchor", "score_threshold", "abs_ma", "abs_threshold", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]].head(12).to_markdown(index=False),
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
        "scan_type": "fresh_layer2_score_abs_filter",
        "parameter_group": "score_threshold_abs_bias_filter",
        "baseline": {"anchors": ANCHORS},
        "candidate_grid": grid,
        "cost_model": {"one_way_commission": base.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return"},
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via layer1 harness",
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
        },
        "decision": "layer2_complete_not_promoted",
        "stability_label": "score_abs_filter_patch_pending_review",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "practical_candidates": str(RUN_DIR / "practical_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_cyb_sz50_spread_layer2_score_abs_filter.py\"\n"
        "python \"scan_adk_cyb_sz50_spread_layer2_score_abs_filter.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )

    cols = ["candidate", "anchor", "score_threshold", "abs_ma", "abs_threshold", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("TOP_SHARPE")
    print(top[cols].head(12).to_string(index=False))
    print("PRACTICAL")
    print(practical[cols].head(12).to_string(index=False))
    print("RIDGE")
    print(ridge.head(30).to_string(index=False))


if __name__ == "__main__":
    main()

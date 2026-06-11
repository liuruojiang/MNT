"""Dense Layer 1 patch scan for fresh ADK-style long CYB / short ZZ1000 spread.

This keeps the Layer 1 scope: bias-momentum signal window and recency weight only.
No target-vol, NAV defense, overheat, amount, or momentum-decay overlay is applied.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import scan_adk_cyb_zz1000_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260611_adk_cyb_zz1000_spread_long_only_v77_adk_spread_layer1_dense_patch_bias_momentum_window_weight"
WEIGHT_GRID = [0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 3.5]
WEIGHT_EXTENSION_GRID = [4.0, 4.5, 5.0]


def dense_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for bias_ma in range(10, 71, 5):
        for mom_day in range(14, 37, 2):
            for weight_end in WEIGHT_GRID:
                grid.append(
                    {
                        "candidate": f"dense_bias_ma{bias_ma:03d}_mom{mom_day:03d}_we{str(weight_end).replace('.', 'p')}_gt0",
                        "family": "bias_momentum",
                        "bias_ma": bias_ma,
                        "mom_day": mom_day,
                        "weight_end": weight_end,
                        "threshold": 0.0,
                    }
                )
    for bias_ma in range(40, 61, 5):
        for mom_day in range(18, 23, 2):
            for weight_end in WEIGHT_EXTENSION_GRID:
                grid.append(
                    {
                        "candidate": f"dense_bias_ma{bias_ma:03d}_mom{mom_day:03d}_we{str(weight_end).replace('.', 'p')}_gt0",
                        "family": "bias_momentum",
                        "bias_ma": bias_ma,
                        "mom_day": mom_day,
                        "weight_end": weight_end,
                        "threshold": 0.0,
                    }
                )
    return grid


def main() -> None:
    mod = base.load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    zz1000 = mod._load_cn_official_cache(mod.CN_DK_ZZ1000_SECID).rename(columns={"close": "ZZ1000"})
    panel = pd.concat([cyb["CYB"], zz1000["ZZ1000"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["CYB"] / panel["ZZ1000"]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = dense_grid()
    long_rows = []
    wide_rows = []
    daily_curves = []

    for candidate in grid:
        result = base.build_candidate_returns(panel, candidate)
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

    top_sharpe = window_metrics.sort_values("sharpe_repo_full", ascending=False).head(20)
    practical = window_metrics[
        (window_metrics["ann_return_full"] >= 0.06)
        & (window_metrics["max_dd_full"] >= -0.18)
        & (window_metrics["ann_return_last_5y"] >= 0.03)
    ].sort_values(["max_dd_full", "sharpe_repo_full"], ascending=[False, False]).head(20)
    if practical.empty:
        practical = window_metrics.sort_values(["max_dd_full", "sharpe_repo_full"], ascending=[False, False]).head(20)

    width_rows = []
    best_sharpe = float(window_metrics["sharpe_repo_full"].max())
    for bias_ma, df1 in window_metrics.groupby("bias_ma"):
        best = df1.sort_values("sharpe_repo_full", ascending=False).iloc[0]
        width_rows.append(
            {
                "axis": "bias_ma",
                "value": bias_ma,
                "best_candidate": best["candidate"],
                "best_full_ann_return": best["ann_return_full"],
                "best_full_max_dd": best["max_dd_full"],
                "best_full_sharpe": best["sharpe_repo_full"],
                "pass_80pct_global_best": bool(best["sharpe_repo_full"] >= best_sharpe * 0.8),
            }
        )
    for mom_day, df1 in window_metrics.groupby("mom_day"):
        best = df1.sort_values("sharpe_repo_full", ascending=False).iloc[0]
        width_rows.append(
            {
                "axis": "mom_day",
                "value": mom_day,
                "best_candidate": best["candidate"],
                "best_full_ann_return": best["ann_return_full"],
                "best_full_max_dd": best["max_dd_full"],
                "best_full_sharpe": best["sharpe_repo_full"],
                "pass_80pct_global_best": bool(best["sharpe_repo_full"] >= best_sharpe * 0.8),
            }
        )
    for weight_end, df1 in window_metrics.groupby("weight_end"):
        best = df1.sort_values("sharpe_repo_full", ascending=False).iloc[0]
        width_rows.append(
            {
                "axis": "weight_end",
                "value": weight_end,
                "best_candidate": best["candidate"],
                "best_full_ann_return": best["ann_return_full"],
                "best_full_max_dd": best["max_dd_full"],
                "best_full_sharpe": best["sharpe_repo_full"],
                "pass_80pct_global_best": bool(best["sharpe_repo_full"] >= best_sharpe * 0.8),
            }
        )
    ridge = pd.DataFrame(width_rows)

    pass_cut = best_sharpe * 0.8
    pass_df = window_metrics[window_metrics["sharpe_repo_full"] >= pass_cut].copy()
    local_rows = []
    min_bias, max_bias = int(window_metrics["bias_ma"].min()), int(window_metrics["bias_ma"].max())
    min_mom, max_mom = int(window_metrics["mom_day"].min()), int(window_metrics["mom_day"].max())
    min_weight, max_weight = float(window_metrics["weight_end"].min()), float(window_metrics["weight_end"].max())
    for _, row in top_sharpe.head(30).iterrows():
        nearby = pass_df[
            (pass_df["bias_ma"].sub(row["bias_ma"]).abs() <= 5)
            & (pass_df["mom_day"].sub(row["mom_day"]).abs() <= 2)
            & (pass_df["weight_end"].sub(row["weight_end"]).abs() <= 0.5)
        ]
        local_rows.append(
            {
                "candidate": row["candidate"],
                "bias_ma": int(row["bias_ma"]),
                "mom_day": int(row["mom_day"]),
                "weight_end": float(row["weight_end"]),
                "ann_return_full": float(row["ann_return_full"]),
                "max_dd_full": float(row["max_dd_full"]),
                "sharpe_repo_full": float(row["sharpe_repo_full"]),
                "ann_return_last_5y": float(row["ann_return_last_5y"]),
                "max_dd_last_5y": float(row["max_dd_last_5y"]),
                "ann_return_last_1y": float(row["ann_return_last_1y"]),
                "max_dd_last_1y": float(row["max_dd_last_1y"]),
                "nearby_pass_count": int(len(nearby)),
                "nearby_bias_count": int(nearby["bias_ma"].nunique()),
                "nearby_mom_count": int(nearby["mom_day"].nunique()),
                "nearby_weight_count": int(nearby["weight_end"].nunique()),
                "edge_flag": bool(
                    row["bias_ma"] in (min_bias, max_bias)
                    or row["mom_day"] in (min_mom, max_mom)
                    or float(row["weight_end"]) in (min_weight, max_weight)
                ),
                "local_patch": bool(
                    len(nearby) >= 4
                    and nearby["bias_ma"].nunique() >= 2
                    and nearby["mom_day"].nunique() >= 2
                    and nearby["weight_end"].nunique() >= 2
                ),
            }
        )
    local_width = pd.DataFrame(local_rows)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    local_width.to_csv(RUN_DIR / "local_width.csv", index=False, encoding="utf-8-sig")
    practical.to_csv(RUN_DIR / "practical_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# CYB/ZZ1000 Fresh ADK Spread Layer 1 Dense Patch",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer1_dense_complete_not_promoted`",
        "- stability: `dense_bias_momentum_patch_found_but_dd_tradeoff_remains`",
        "",
        "## Research Question",
        "Dense scan around the Layer 1 leading bias-momentum family for long CYB / short ZZ1000.",
        "",
        "## Implementation Anchor",
        "- Imports Layer 0/1 harness from `scan_adk_cyb_zz1000_spread_long_only.py`.",
        "- Only `bias_ma`, `mom_day`, and `weight_end` are scanned.",
        "- Dense grid covers both Layer 0/1 leading neighborhoods: `20/30/we2` and `40/20/we1`.",
        "- Because the first dense pass hit the `weight_end=3.5` upper edge near `45-50/20`, this run includes a targeted `weight_end=4.0/4.5/5.0` extension for `bias_ma=40..60`, `mom_day=18..22`.",
        "",
        "## Data Snapshot",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- Same as Layer 0/1: T close signal -> T+1 close-to-close spread return.",
        "- Two-leg transaction cost with one-way commission 0.0005 on exposure changes.",
        "- No overlays or defensive layers are applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_cyb_zz1000_spread_layer1_dense_patch.py\"`",
        "- `python \"scan_adk_cyb_zz1000_spread_layer1_dense_patch.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `local_width.csv`",
        "- `practical_candidates.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        top_sharpe[["candidate", "bias_ma", "mom_day", "weight_end", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]].to_markdown(index=False),
        "",
        "## Window Results",
        "See `window_metrics.csv` and `practical_candidates.csv`.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Local Width Check",
        local_width.head(12).to_markdown(index=False),
        "",
        "## Decision",
        "Layer 1 dense patch completed but not promoted. Stop for user confirmation before Layer 2 filters.",
        "",
        "## User-Facing Summary",
        practical[["candidate", "bias_ma", "mom_day", "weight_end", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]].head(12).to_markdown(index=False),
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
        "scan_type": "fresh_layer1_dense_bias_momentum_patch",
        "parameter_group": "bias_ma_mom_day_weight_end",
        "baseline": {
            "previous_layer_best": "bias_ma020_mom030_we2p0_gt0",
            "previous_layer_neighbor": "bias_ma040_mom020_we1p0_gt0",
            "threshold": 0.0,
        },
        "candidate_grid": dense_grid(),
        "cost_model": {"one_way_commission": base.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return"},
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via layer1 harness",
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
        },
        "decision": "layer1_dense_complete_not_promoted",
        "stability_label": "dense_bias_momentum_patch_found_but_dd_tradeoff_remains",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "local_width": str(RUN_DIR / "local_width.csv"),
            "practical_candidates": str(RUN_DIR / "practical_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_cyb_zz1000_spread_layer1_dense_patch.py\"\n"
        "python \"scan_adk_cyb_zz1000_spread_layer1_dense_patch.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("TOP_SHARPE")
    print(top_sharpe[["candidate", "bias_ma", "mom_day", "weight_end", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]].head(12).to_string(index=False))
    print("PRACTICAL")
    print(practical[["candidate", "bias_ma", "mom_day", "weight_end", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]].head(12).to_string(index=False))
    print("RIDGE")
    print(ridge.to_string(index=False))
    print("LOCAL_WIDTH")
    print(local_width.head(12).to_string(index=False))


if __name__ == "__main__":
    main()


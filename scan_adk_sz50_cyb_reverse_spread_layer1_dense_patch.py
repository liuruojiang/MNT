"""Dense Layer 1 patch scan for ADK-style long SZ50 / short CYB spread.

This keeps Layer 1 scope: bias-momentum signal window and recency weight only.
The grid deliberately expands beyond the Layer 0/1 best point so edge picks are
visible instead of accidentally treated as stable.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import scan_adk_sz50_cyb_reverse_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260609_adk_sz50_cyb_reverse_spread_long_only_v77_adk_reverse_spread_layer1_dense_patch_bias_momentum_window_weight"
WEIGHT_GRID = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]


def dense_grid() -> list[dict[str, object]]:
    grid: dict[tuple[int, int, float], dict[str, object]] = {}
    # Primary cluster: Layer 0/1 best was bias_ma=20, mom_day=40, weight_end=3.0.
    for bias_ma in range(10, 61, 5):
        for mom_day in range(30, 53, 2):
            for weight_end in WEIGHT_GRID:
                grid[(bias_ma, mom_day, weight_end)] = make_candidate(bias_ma, mom_day, weight_end)
    # Secondary cluster: several Layer 0/1 runners-up sat around long MA and mom20.
    for bias_ma in range(70, 131, 10):
        for mom_day in range(16, 29, 2):
            for weight_end in WEIGHT_GRID:
                grid[(bias_ma, mom_day, weight_end)] = make_candidate(bias_ma, mom_day, weight_end)
    return list(grid.values())


def make_candidate(bias_ma: int, mom_day: int, weight_end: float) -> dict[str, object]:
    return {
        "candidate": f"dense_rev_bias_ma{bias_ma:03d}_mom{mom_day:03d}_we{str(weight_end).replace('.', 'p')}_gt0",
        "family": "bias_momentum",
        "bias_ma": bias_ma,
        "mom_day": mom_day,
        "weight_end": weight_end,
        "threshold": 0.0,
    }


def axis_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    best_sharpe = float(window_metrics["sharpe_repo_full"].max())
    pass_cut = best_sharpe * 0.8
    for axis in ["bias_ma", "mom_day", "weight_end"]:
        for value, df in window_metrics.groupby(axis):
            best = df.sort_values("sharpe_repo_full", ascending=False).iloc[0]
            passed = df[df["sharpe_repo_full"] >= pass_cut]
            rows.append(
                {
                    "axis": axis,
                    "value": value,
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_sharpe": best["sharpe_repo_full"],
                    "pass_count_at_value": int(len(passed)),
                    "pass_80pct_global_best": bool(best["sharpe_repo_full"] >= pass_cut),
                }
            )
    return pd.DataFrame(rows)


def local_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    best_sharpe = float(window_metrics["sharpe_repo_full"].max())
    pass_cut = best_sharpe * 0.8
    passed = window_metrics[window_metrics["sharpe_repo_full"] >= pass_cut].copy()
    for _, row in window_metrics.sort_values("sharpe_repo_full", ascending=False).head(20).iterrows():
        b = int(row["bias_ma"])
        m = int(row["mom_day"])
        w = float(row["weight_end"])
        neighbors = passed[
            (passed["bias_ma"].between(b - 5, b + 5))
            & (passed["mom_day"].between(m - 2, m + 2))
            & (passed["weight_end"].between(w - 0.5, w + 0.5))
        ]
        same_core = window_metrics[(window_metrics["bias_ma"] == b) & (window_metrics["mom_day"] == m)]
        weight_pass = same_core[same_core["sharpe_repo_full"] >= pass_cut]
        rows.append(
            {
                "candidate": row["candidate"],
                "bias_ma": b,
                "mom_day": m,
                "weight_end": w,
                "ann_return_full": row["ann_return_full"],
                "max_dd_full": row["max_dd_full"],
                "sharpe_repo_full": row["sharpe_repo_full"],
                "nearby_pass_count": int(len(neighbors)),
                "nearby_bias_count": int(neighbors["bias_ma"].nunique()),
                "nearby_mom_count": int(neighbors["mom_day"].nunique()),
                "nearby_weight_count": int(neighbors["weight_end"].nunique()),
                "same_core_weight_pass_count": int(len(weight_pass)),
                "is_grid_edge": bool(
                    b in {int(window_metrics["bias_ma"].min()), int(window_metrics["bias_ma"].max())}
                    or m in {int(window_metrics["mom_day"].min()), int(window_metrics["mom_day"].max())}
                    or w in {float(window_metrics["weight_end"].min()), float(window_metrics["weight_end"].max())}
                ),
                "local_patch": bool(
                    len(neighbors) >= 6
                    and neighbors["bias_ma"].nunique() >= 2
                    and neighbors["mom_day"].nunique() >= 2
                    and neighbors["weight_end"].nunique() >= 2
                ),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    mod = base.base_scan.load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    sz50 = mod._load_cn_official_cache(mod.CN_DK_SZ50_SECID).rename(columns={"close": "SZ50"})
    panel = pd.concat([cyb["CYB"], sz50["SZ50"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.base_scan.FORMAL_START].copy()
    panel["ratio"] = panel["SZ50"] / panel["CYB"]

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
        for segment, years in base.base_scan.SEGMENTS:
            m = base.base_scan.metrics_for_segment(result, segment, years)
            long_rows.append({**candidate, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = pd.DataFrame(wide_rows)
    daily = pd.concat(daily_curves, ignore_index=True)
    ridge = axis_width(window_metrics)
    local = local_width(window_metrics)

    top_sharpe = window_metrics.sort_values("sharpe_repo_full", ascending=False).head(20)
    practical = window_metrics[
        (window_metrics["ann_return_full"] > 0.0)
        & (window_metrics["ann_return_last_5y"] > 0.0)
        & (window_metrics["ann_return_last_1y"] > -0.08)
    ].sort_values(["max_dd_full", "sharpe_repo_full"], ascending=[False, False]).head(20)
    if practical.empty:
        practical = window_metrics.sort_values(["max_dd_full", "sharpe_repo_full"], ascending=[False, False]).head(20)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    local.to_csv(RUN_DIR / "local_width.csv", index=False, encoding="utf-8-sig")
    practical.to_csv(RUN_DIR / "practical_candidates.csv", index=False, encoding="utf-8-sig")

    best = top_sharpe.iloc[0]
    best_local = local[local["candidate"] == best["candidate"]].iloc[0]
    stability = "dense_patch_found" if bool(best_local["local_patch"]) and not bool(best_local["is_grid_edge"]) else "edge_or_thin_width_warning"
    record_lines = [
        "# SZ50/CYB Reverse ADK Spread Layer 1 Dense Patch",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer1_dense_complete_not_promoted`",
        f"- stability: `{stability}`",
        "",
        "## Research Question",
        "Dense scan around the Layer 0/1 leading bias-momentum family for long SZ50 / short CYB, with explicit edge and local-width checks.",
        "",
        "## Implementation Anchor",
        "- Imports Layer 0/1 reverse harness from `scan_adk_sz50_cyb_reverse_spread_long_only.py`.",
        "- Only `bias_ma`, `mom_day`, and `weight_end` are scanned.",
        "- Primary grid expands around `bias_ma20/mom40/weight_end3.0`; secondary grid keeps the long-MA/mom20 runner-up area.",
        "",
        "## Data Snapshot",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- Same as Layer 0/1: T close signal -> T+1 close-to-close spread return.",
        "- Return stream: SZ50 close-to-close return minus CYB close-to-close return.",
        f"- Two-leg transaction cost with one-way commission {base.base_scan.COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- No target-vol, NAV defense, overheat, amount, or momentum-decay overlay is applied.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_sz50_cyb_reverse_spread_layer1_dense_patch.py\"`",
        "- `python \"scan_adk_sz50_cyb_reverse_spread_layer1_dense_patch.py\"`",
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
        "## Local Width",
        local.head(20).to_markdown(index=False),
        "",
        "## Axis Width",
        ridge.to_markdown(index=False),
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
        "implementation_anchor": "scan_adk_sz50_cyb_reverse_spread_long_only.py",
        "git_branch": "not_checked_agent_policy",
        "git_commit": "not_checked_agent_policy",
        "git_status_before": "not_checked_agent_policy",
        "git_status_after": "not_checked_agent_policy",
        "scan_type": "reverse_layer1_dense_bias_momentum_patch",
        "parameter_group": "bias_ma_mom_day_weight_end",
        "baseline": {"previous_layer_best": "bias_ma020_mom040_we3p0_gt0", "threshold": 0.0, "direction": "long_SZ50_short_CYB"},
        "candidate_grid": grid,
        "cost_model": {"one_way_commission": base.base_scan.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return"},
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via reverse layer1 harness",
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
        },
        "decision": "layer1_dense_complete_not_promoted",
        "stability_label": stability,
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
        "python -m py_compile \"scan_adk_sz50_cyb_reverse_spread_layer1_dense_patch.py\"\n"
        "python \"scan_adk_sz50_cyb_reverse_spread_layer1_dense_patch.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(f"STABILITY={stability}")
    print("TOP_SHARPE")
    print(top_sharpe[["candidate", "bias_ma", "mom_day", "weight_end", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]].head(12).to_string(index=False))
    print("LOCAL_WIDTH")
    print(local.head(12).to_string(index=False))
    print("PRACTICAL")
    print(practical[["candidate", "bias_ma", "mom_day", "weight_end", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]].head(12).to_string(index=False))


if __name__ == "__main__":
    main()

"""Dense Layer 1 patch scan for long ZZ1000 / short CYB spread.

This keeps the Layer 1 scope: bias-momentum signal parameters only.
No target-vol, NAV defense, overheat, amount, volume, or momentum-decay overlay
is applied.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np

import scan_adk_zz1000_cyb_spread_long_only as base
import scan_adk_cyb_zz1000_spread_long_only as metric_base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260611_adk_zz1000_cyb_spread_long_only_v77_adk_spread_layer1_dense_patch_bias_momentum_width"
WEIGHT_GRID = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0, 3.5]


def dense_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for bias_ma in range(30, 71, 5):
        for mom_day in range(8, 23):
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
    return grid


def fast_weighted_slope_and_r2(
    series: pd.Series,
    window: int,
    weight_end: float,
) -> tuple[pd.Series, pd.Series]:
    arr = series.astype(float).to_numpy()
    valid = np.isfinite(arr).astype(float)
    arr0 = np.where(np.isfinite(arr), arr, 0.0)

    x = np.arange(window, dtype=float)
    weights = np.linspace(1.0, float(weight_end), window)
    weights = weights / weights.sum()
    sx = float(np.sum(weights * x))
    sxx = float(np.sum(weights * x * x))
    var_x = sxx - sx * sx

    counts = np.convolve(valid, np.ones(window), mode="valid")
    sy = np.convolve(arr0, weights[::-1], mode="valid")
    syy = np.convolve(arr0 * arr0, weights[::-1], mode="valid")
    sxy = np.convolve(arr0, (weights * x)[::-1], mode="valid")

    cov = sxy - sx * sy
    var_y = syy - sy * sy
    slope_values = cov / var_x * window * 100.0
    r2_values = np.full_like(cov, np.nan, dtype=float)
    np.divide(cov * cov, var_x * var_y, out=r2_values, where=var_y > 0)
    r2_values = np.clip(r2_values, 0.0, 1.0)

    bad = counts < window
    slope_values[bad] = np.nan
    r2_values[bad] = np.nan

    slope = np.full(len(arr), np.nan)
    r2 = np.full(len(arr), np.nan)
    slope[window - 1 :] = slope_values
    r2[window - 1 :] = r2_values
    return pd.Series(slope, index=series.index), pd.Series(r2, index=series.index)


def build_candidate_returns(panel: pd.DataFrame, candidate: dict[str, object]) -> pd.DataFrame:
    ratio = panel["ratio"]
    family = str(candidate["family"])
    threshold = float(candidate.get("threshold", 0.0))
    weight_end = float(candidate.get("weight_end", 1.0))

    if family != "bias_momentum":
        raise ValueError(f"unsupported dense family: {family}")

    bias_ma = int(candidate["bias_ma"])
    mom_day = int(candidate["mom_day"])
    feature = ratio / ratio.rolling(bias_ma).mean() - 1.0
    score, r2 = fast_weighted_slope_and_r2(feature, mom_day, weight_end)

    raw_signal = ((score > threshold) & (r2 >= 0.05)).astype(float)
    exec_weight = raw_signal.shift(1).fillna(0.0)
    spread_return = panel["ZZ1000"].pct_change().fillna(0.0) - panel["CYB"].pct_change().fillna(0.0)
    turnover = exec_weight.diff().abs().fillna(exec_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    ret = exec_weight * spread_return - cost
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
            "ratio": ratio,
            "spread_return": spread_return,
        },
        index=panel.index,
    )
    warmup = int(max(bias_ma, mom_day) + 2)
    return out.iloc[warmup:].copy()


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def add_pass_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    best_sharpe = float(out["sharpe_repo_full"].max())
    out["global80_pass"] = out["sharpe_repo_full"] >= best_sharpe * 0.8
    out["core_pass"] = (
        (out["ann_return_full"] >= 0.005)
        & (out["max_dd_full"] >= -0.22)
        & (out["ann_return_last_5y"] >= 0.0)
        & (out["ann_return_last_3y"] >= -0.05)
        & (out["ann_return_last_1y"] >= -0.11)
    )
    out["defensive_pass"] = (
        (out["ann_return_full"] >= 0.0)
        & (out["max_dd_full"] >= -0.19)
        & (out["ann_return_last_5y"] >= 0.0)
        & (out["ann_return_last_1y"] >= -0.08)
    )
    out["recent5_pass"] = (
        (out["ann_return_full"] >= 0.0)
        & (out["ann_return_last_5y"] >= 0.02)
        & (out["max_dd_full"] >= -0.23)
    )
    out["width_score"] = (
        out["sharpe_repo_full"]
        + out["ann_return_last_5y"].clip(lower=-0.10, upper=0.10)
        + out["ann_return_last_1y"].clip(lower=-0.15, upper=0.05) * 0.5
        + out["max_dd_full"].clip(lower=-0.40, upper=0.0) * 0.25
    )
    return out


def build_local_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = add_pass_flags(window_metrics)
    min_bias, max_bias = int(df["bias_ma"].min()), int(df["bias_ma"].max())
    min_mom, max_mom = int(df["mom_day"].min()), int(df["mom_day"].max())
    min_weight, max_weight = float(df["weight_end"].min()), float(df["weight_end"].max())

    seed_pool = pd.concat(
        [
            df.sort_values("sharpe_repo_full", ascending=False).head(60),
            df.sort_values("width_score", ascending=False).head(60),
            df[df["core_pass"]].sort_values("width_score", ascending=False).head(60),
            df[df["defensive_pass"]].sort_values("width_score", ascending=False).head(60),
            df[df["recent5_pass"]].sort_values("ann_return_last_5y", ascending=False).head(60),
        ],
        ignore_index=True,
    ).drop_duplicates("candidate")

    rows = []
    for _, row in seed_pool.iterrows():
        nearby = df[
            (df["bias_ma"].sub(row["bias_ma"]).abs() <= 5)
            & (df["mom_day"].sub(row["mom_day"]).abs() <= 2)
            & (df["weight_end"].sub(row["weight_end"]).abs() <= 0.5)
        ]
        core = nearby[nearby["core_pass"]]
        defensive = nearby[nearby["defensive_pass"]]
        recent5 = nearby[nearby["recent5_pass"]]
        global80 = nearby[nearby["global80_pass"]]
        rows.append(
            {
                "candidate": row["candidate"],
                "bias_ma": int(row["bias_ma"]),
                "mom_day": int(row["mom_day"]),
                "weight_end": float(row["weight_end"]),
                "ann_return_full": float(row["ann_return_full"]),
                "max_dd_full": float(row["max_dd_full"]),
                "sharpe_repo_full": float(row["sharpe_repo_full"]),
                "ann_return_last_10y": float(row["ann_return_last_10y"]),
                "max_dd_last_10y": float(row["max_dd_last_10y"]),
                "ann_return_last_5y": float(row["ann_return_last_5y"]),
                "max_dd_last_5y": float(row["max_dd_last_5y"]),
                "ann_return_last_3y": float(row["ann_return_last_3y"]),
                "max_dd_last_3y": float(row["max_dd_last_3y"]),
                "ann_return_last_1y": float(row["ann_return_last_1y"]),
                "max_dd_last_1y": float(row["max_dd_last_1y"]),
                "width_score": float(row["width_score"]),
                "nearby_count": int(len(nearby)),
                "nearby_global80_count": int(len(global80)),
                "nearby_core_pass_count": int(len(core)),
                "nearby_defensive_pass_count": int(len(defensive)),
                "nearby_recent5_pass_count": int(len(recent5)),
                "core_bias_count": int(core["bias_ma"].nunique()),
                "core_mom_count": int(core["mom_day"].nunique()),
                "core_weight_count": int(core["weight_end"].nunique()),
                "defensive_bias_count": int(defensive["bias_ma"].nunique()),
                "defensive_mom_count": int(defensive["mom_day"].nunique()),
                "defensive_weight_count": int(defensive["weight_end"].nunique()),
                "recent5_bias_count": int(recent5["bias_ma"].nunique()),
                "recent5_mom_count": int(recent5["mom_day"].nunique()),
                "recent5_weight_count": int(recent5["weight_end"].nunique()),
                "edge_flag": bool(
                    row["bias_ma"] in (min_bias, max_bias)
                    or row["mom_day"] in (min_mom, max_mom)
                    or float(row["weight_end"]) in (min_weight, max_weight)
                ),
                "core_local_patch": bool(
                    len(core) >= 8
                    and core["bias_ma"].nunique() >= 2
                    and core["mom_day"].nunique() >= 3
                    and core["weight_end"].nunique() >= 2
                ),
                "defensive_local_patch": bool(
                    len(defensive) >= 6
                    and defensive["bias_ma"].nunique() >= 2
                    and defensive["mom_day"].nunique() >= 2
                    and defensive["weight_end"].nunique() >= 2
                ),
                "recent5_local_patch": bool(
                    len(recent5) >= 8
                    and recent5["bias_ma"].nunique() >= 2
                    and recent5["mom_day"].nunique() >= 3
                    and recent5["weight_end"].nunique() >= 2
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(
        [
            "core_local_patch",
            "defensive_local_patch",
            "recent5_local_patch",
            "nearby_core_pass_count",
            "nearby_defensive_pass_count",
            "nearby_recent5_pass_count",
            "width_score",
        ],
        ascending=[False, False, False, False, False, False, False],
    )


def build_axis_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = add_pass_flags(window_metrics)
    rows = []
    for axis in ["bias_ma", "mom_day", "weight_end"]:
        for value, group in df.groupby(axis):
            best = group.sort_values("width_score", ascending=False).iloc[0]
            rows.append(
                {
                    "axis": axis,
                    "value": value,
                    "best_candidate": best["candidate"],
                    "best_width_score": float(best["width_score"]),
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "best_5y_ann_return": float(best["ann_return_last_5y"]),
                    "best_1y_ann_return": float(best["ann_return_last_1y"]),
                    "core_pass_count": int(group["core_pass"].sum()),
                    "defensive_pass_count": int(group["defensive_pass"].sum()),
                    "recent5_pass_count": int(group["recent5_pass"].sum()),
                }
            )
    return pd.DataFrame(rows)


def window_table(df: pd.DataFrame, n: int = 10) -> str:
    cols = ["candidate", "bias_ma", "mom_day", "weight_end"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    mod = base.load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    zz1000 = mod._load_cn_official_cache(mod.CN_DK_ZZ1000_SECID).rename(columns={"close": "ZZ1000"})
    panel = pd.concat([zz1000["ZZ1000"], cyb["CYB"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["ZZ1000"] / panel["CYB"]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = dense_grid()
    long_rows = []
    wide_rows = []
    daily_curves = []

    for candidate in grid:
        result = build_candidate_returns(panel, candidate)
        nav = (1.0 + result["return"]).cumprod()
        out = result.copy()
        out["nav"] = nav
        out["candidate"] = candidate["candidate"]
        daily_curves.append(out.reset_index(names="date"))

        wide = {**candidate}
        for segment, years in base.SEGMENTS:
            m = metric_base.metrics_for_segment(result, segment, years)
            long_rows.append({**candidate, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_pass_flags(pd.DataFrame(wide_rows))
    daily = pd.concat(daily_curves, ignore_index=True)
    local_width = build_local_width(window_metrics)
    ridge = build_axis_width(window_metrics)

    top_sharpe = window_metrics.sort_values("sharpe_repo_full", ascending=False).head(20)
    width_candidates = local_width[
        (local_width["core_local_patch"] | local_width["defensive_local_patch"] | local_width["recent5_local_patch"])
        & (~local_width["edge_flag"])
    ].head(20)
    if width_candidates.empty:
        width_candidates = local_width[~local_width["edge_flag"]].head(20)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    local_width.to_csv(RUN_DIR / "local_width.csv", index=False, encoding="utf-8-sig")
    width_candidates.to_csv(RUN_DIR / "width_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# ZZ1000/CYB Fresh ADK Spread Layer 1 Dense Patch",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer1_dense_complete_not_promoted`",
        "- stability: `dense_width_search_complete`",
        "",
        "## Research Question",
        "Dense scan for a suboptimal but wider Layer 1 point in long ZZ1000 / short CYB.",
        "",
        "## Implementation Anchor",
        "- Imports the reverse Layer 0/1 harness from `scan_adk_zz1000_cyb_spread_long_only.py`.",
        "- Only `bias_ma`, `mom_day`, and `weight_end` are scanned.",
        "- Dense grid: `bias_ma=30..70 step5`, `mom_day=8..22 step1`, `weight_end=0.75..3.5`.",
        "",
        "## Data Snapshot",
        f"- ZZ1000 rows: {len(zz1000)}, start {zz1000.index.min().date()}, end {zz1000.index.max().date()}.",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start: `2014-10-17`, constrained by CSI 1000 publication date.",
        "",
        "## Cost and Execution Assumptions",
        "- Timing: T close signal -> T+1 close-to-close spread return.",
        "- Return stream: ZZ1000 close-to-close return minus CYB close-to-close return.",
        f"- Transaction cost: two legs times one-way commission {base.COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- No overlays or defensive layers are applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 1 dense scan.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_zz1000_cyb_spread_layer1_dense_patch.py\"`",
        "- `python \"scan_adk_zz1000_cyb_spread_layer1_dense_patch.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `local_width.csv`",
        "- `width_candidates.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Top Full-Sample Results",
        window_table(top_sharpe, 12),
        "",
        "## Width Candidates",
        window_table(width_candidates, 12),
        "",
        "## Stability Classification",
        local_width.head(20).to_markdown(index=False),
        "",
        "## Decision",
        "Layer 1 dense patch completed but not promoted. Stop for user confirmation before Layer 2 filters.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz1000_cyb_spread_long_only.py",
        "git_branch": "dirty_worktree_not_cleaned",
        "git_commit": "not_recorded",
        "git_status_before": "dirty_worktree_with_prior_research_artifacts",
        "git_status_after": "dirty_worktree_with_prior_research_artifacts",
        "scan_type": "layer1_dense_patch_width_search",
        "parameter_group": "bias_momentum_window_weight_width",
        "baseline": {"direction": "long_ZZ1000_short_CYB", "threshold": 0.0},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal -> T+1 close-to-close return",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "zz1000": {
                "secid": str(mod.CN_DK_ZZ1000_SECID),
                "rows": int(len(zz1000)),
                "start": str(zz1000.index.min().date()),
                "end": str(zz1000.index.max().date()),
                "publication_date": "2014-10-17",
            },
            "cyb": {
                "secid": str(mod.CN_DK_CYB_SECID),
                "rows": int(len(cyb)),
                "start": str(cyb.index.min().date()),
                "end": str(cyb.index.max().date()),
            },
            "formal": {
                "rows": int(len(panel)),
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
                "start_rule": "latest actual publication/listing date; ZZ1000 publication 2014-10-17",
            },
        },
        "decision": "layer1_dense_complete_not_promoted",
        "stability_label": "dense_width_search_complete",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "local_width": str(RUN_DIR / "local_width.csv"),
            "width_candidates": str(RUN_DIR / "width_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_zz1000_cyb_spread_layer1_dense_patch.py\"\n"
        "python \"scan_adk_zz1000_cyb_spread_layer1_dense_patch.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)}")
    print("TOP_SHARPE")
    print(top_sharpe[["candidate", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]].to_string(index=False))
    print("WIDTH_CANDIDATES")
    print(width_candidates[["candidate", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y", "nearby_core_pass_count", "nearby_defensive_pass_count", "nearby_recent5_pass_count", "core_local_patch", "defensive_local_patch", "recent5_local_patch", "edge_flag"]].head(20).to_string(index=False))


if __name__ == "__main__":
    main()

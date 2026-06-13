"""Layer 1 dense patch for ADK-style long ZZ500 / short CYB spread.

This layer follows the width-first rule from the Layer 0/1 result:
- primary line: log_wls_mom010_we2p0_gt0.
- confirmation lines: log_wls_mom015_we2p0_gt0 and log_wls_mom010_we1p0_gt0.

Target-vol, NAV defense, overheat, amount/volume, and momentum decay are off.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_cyb_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_cyb_spread_long_only_v77_adk_spread_layer1_dense_patch_log_wls_width"
WEIGHT_GRID = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 4.0]
PREVIOUS_PRIMARY = {"mom_day": 10, "weight_end": 2.0, "candidate": "log_wls_mom010_we2p0_gt0"}
PREVIOUS_CONFIRMATION = [
    {"mom_day": 15, "weight_end": 2.0, "candidate": "log_wls_mom015_we2p0_gt0"},
    {"mom_day": 10, "weight_end": 1.0, "candidate": "log_wls_mom010_we1p0_gt0"},
]


def dense_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for mom_day in range(5, 26):
        for weight_end in WEIGHT_GRID:
            grid.append(
                {
                    "candidate": f"dense_log_wls_mom{mom_day:03d}_we{str(weight_end).replace('.', 'p')}_gt0",
                    "family": "log_wls_momentum",
                    "branch": "width_supported_log_wls",
                    "bias_ma": 0,
                    "mom_day": mom_day,
                    "weight_end": weight_end,
                    "threshold": 0.0,
                }
            )
    return grid


def fast_weighted_slope_and_r2(series: pd.Series, window: int, weight_end: float) -> tuple[pd.Series, pd.Series]:
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
    threshold = float(candidate.get("threshold", 0.0))
    weight_end = float(candidate["weight_end"])
    mom_day = int(candidate["mom_day"])
    feature = np.log(ratio)
    score, r2 = fast_weighted_slope_and_r2(feature, mom_day, weight_end)
    raw_signal = ((score > threshold) & (r2 >= 0.05)).astype(float)
    exec_weight = raw_signal.shift(1).fillna(0.0)
    spread_return = panel["ZZ500"].pct_change().fillna(0.0) - panel["CYB"].pct_change().fillna(0.0)
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
            "score": score,
            "r2": r2,
        },
        index=panel.index,
    )
    return out.iloc[int(mom_day + 2) :].copy()


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def add_baseline_deltas(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = window_metrics.copy()
    baseline_name = f"dense_log_wls_mom{PREVIOUS_PRIMARY['mom_day']:03d}_we2p0_gt0"
    baseline = df[df["candidate"] == baseline_name]
    if baseline.empty:
        return df
    base_row = baseline.iloc[0]
    for segment, _years in base.SEGMENTS:
        df[f"ann_delta_pp_{segment}"] = (df[f"ann_return_{segment}"] - float(base_row[f"ann_return_{segment}"])) * 100.0
        df[f"dd_improve_pp_{segment}"] = (df[f"max_dd_{segment}"] - float(base_row[f"max_dd_{segment}"])) * 100.0
    return df


def add_pass_flags(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = add_baseline_deltas(window_metrics)
    best_sharpe = float(df["sharpe_repo_full"].max())
    df["family80_pass"] = df["sharpe_repo_full"] >= best_sharpe * 0.8
    df["not_worse_full_vs_anchor"] = (df["ann_delta_pp_full"] >= -0.25) & (df["dd_improve_pp_full"] >= -2.0)
    df["not_worse_5y_vs_anchor"] = (df["ann_delta_pp_last_5y"] >= -0.50) & (df["dd_improve_pp_last_5y"] >= -2.0)
    df["recent_watch_pass"] = (df["ann_delta_pp_last_3y"] >= 0.0) | (df["dd_improve_pp_last_3y"] >= 2.0)
    df["anchor_compatible"] = df["not_worse_full_vs_anchor"] & df["not_worse_5y_vs_anchor"]
    df["width_score"] = (
        df["sharpe_repo_full"]
        + df["ann_return_full"].clip(lower=-0.05, upper=0.03)
        + df["ann_return_last_5y"].clip(lower=-0.05, upper=0.03) * 0.5
        + df["ann_return_last_1y"].clip(lower=-0.15, upper=0.05) * 0.2
        + df["max_dd_full"].clip(lower=-0.4, upper=0.0) * 0.08
        + df["anchor_compatible"].astype(float) * 0.03
        + df["recent_watch_pass"].astype(float) * 0.01
    )
    return df


def build_local_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = add_pass_flags(window_metrics)
    rows = []
    min_mom, max_mom = int(df["mom_day"].min()), int(df["mom_day"].max())
    min_weight, max_weight = float(df["weight_end"].min()), float(df["weight_end"].max())
    seeds = pd.concat(
        [
            df.sort_values("sharpe_repo_full", ascending=False).head(80),
            df.sort_values("width_score", ascending=False).head(80),
            df[df["anchor_compatible"]].sort_values("width_score", ascending=False).head(80),
        ],
        ignore_index=True,
    ).drop_duplicates("candidate")
    for _, row in seeds.iterrows():
        nearby = df[
            (df["mom_day"].sub(row["mom_day"]).abs() <= 2)
            & (df["weight_end"].sub(row["weight_end"]).abs() <= 0.5)
        ]
        family80 = nearby[nearby["family80_pass"]]
        compatible = nearby[nearby["anchor_compatible"]]
        recent = nearby[nearby["recent_watch_pass"]]
        is_edge = bool(row["mom_day"] in (min_mom, max_mom) or float(row["weight_end"]) in (min_weight, max_weight))
        family80_patch = bool(
            len(family80) >= 4
            and family80["mom_day"].nunique() >= 2
            and family80["weight_end"].nunique() >= 2
        )
        compatible_patch = bool(
            len(compatible) >= 4
            and compatible["mom_day"].nunique() >= 2
            and compatible["weight_end"].nunique() >= 2
        )
        rows.append(
            {
                "candidate": row["candidate"],
                "family": row["family"],
                "branch": row["branch"],
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
                "ann_delta_pp_full": float(row["ann_delta_pp_full"]),
                "dd_improve_pp_full": float(row["dd_improve_pp_full"]),
                "ann_delta_pp_last_5y": float(row["ann_delta_pp_last_5y"]),
                "dd_improve_pp_last_5y": float(row["dd_improve_pp_last_5y"]),
                "width_score": float(row["width_score"]),
                "nearby_count": int(len(nearby)),
                "nearby_family80_count": int(len(family80)),
                "nearby_anchor_compatible_count": int(len(compatible)),
                "nearby_recent_watch_count": int(len(recent)),
                "edge_flag": is_edge,
                "family80_local_patch": family80_patch,
                "anchor_compatible_patch": compatible_patch,
                "width_supported": bool((family80_patch or compatible_patch) and not is_edge),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["width_supported", "family80_local_patch", "anchor_compatible_patch", "nearby_family80_count", "width_score"],
        ascending=[False, False, False, False, False],
    )


def build_axis_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = add_pass_flags(window_metrics)
    rows = []
    for axis in ["mom_day", "weight_end"]:
        for value, group in df.groupby(axis):
            best = group.sort_values("width_score", ascending=False).iloc[0]
            rows.append(
                {
                    "family": "log_wls_momentum",
                    "axis": axis,
                    "value": value,
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "family80_count": int(group["family80_pass"].sum()),
                    "anchor_compatible_count": int(group["anchor_compatible"].sum()),
                    "recent_watch_count": int(group["recent_watch_pass"].sum()),
                }
            )
    return pd.DataFrame(rows)


def window_table(df: pd.DataFrame, n: int = 12) -> str:
    cols = ["candidate", "family", "branch", "mom_day", "weight_end"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def delta_table(df: pd.DataFrame, n: int = 8) -> str:
    cols = [
        "candidate",
        "ann_return_full",
        "max_dd_full",
        "ann_delta_pp_full",
        "dd_improve_pp_full",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "ann_delta_pp_last_5y",
        "dd_improve_pp_last_5y",
    ]
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
        elif col.endswith("_pp_full") or col.endswith("_pp_last_5y"):
            display[col] = display[col].map(lambda x: f"{float(x):+.2f}pp")
    return display.to_markdown(index=False)


def select_carry_candidates(local_width: pd.DataFrame) -> pd.DataFrame:
    supported = local_width[local_width["width_supported"]].copy()
    if supported.empty:
        return local_width[~local_width["edge_flag"]].sort_values("width_score", ascending=False).head(6)
    primary = supported.sort_values(["family80_local_patch", "width_score"], ascending=[False, False]).head(4)
    confirmations = local_width[
        (~local_width["edge_flag"])
        & (local_width["mom_day"].isin([10, 15]))
        & (local_width["weight_end"].isin([1.0, 2.0]))
    ].sort_values("width_score", ascending=False)
    return pd.concat([primary, confirmations], ignore_index=True).drop_duplicates("candidate").head(8)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod = base.load_v77()
    zz500 = mod._load_cn_official_cache(mod.CN_DK_ZZ500_SECID).rename(columns={"close": "ZZ500"})
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    panel = pd.concat([zz500["ZZ500"], cyb["CYB"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["ZZ500"] / panel["CYB"]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = dense_grid()
    long_rows = []
    wide_rows = []
    daily_rows = []

    for candidate in grid:
        result = build_candidate_returns(panel, candidate)
        nav = (1.0 + result["return"]).cumprod()
        daily_rows.append(
            pd.DataFrame(
                {
                    "date": result.index,
                    "candidate": candidate["candidate"],
                    "return": result["return"].to_numpy(),
                    "nav": nav.to_numpy(),
                    "weight": result["weight"].to_numpy(),
                    "cost": result["cost"].to_numpy(),
                }
            )
        )
        wide = {**candidate}
        for segment, years in base.SEGMENTS:
            m = base.metrics_for_segment(result, segment, years)
            long_rows.append({**candidate, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_pass_flags(pd.DataFrame(wide_rows))
    daily = pd.concat(daily_rows, ignore_index=True)
    local_width = build_local_width(window_metrics)
    ridge = build_axis_width(window_metrics)
    top_sharpe = window_metrics.sort_values("sharpe_repo_full", ascending=False).head(30)
    width_candidates = local_width[local_width["width_supported"]].head(40)
    carry = select_carry_candidates(local_width)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    local_width.to_csv(RUN_DIR / "local_width.csv", index=False, encoding="utf-8-sig")
    width_candidates.to_csv(RUN_DIR / "width_candidates.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# ZZ500/CYB ADK Spread Layer 1 Dense Patch",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer1_dense_complete_not_promoted`",
        "- stability: `log_wls_width_supported_pending_user_confirmation`",
        "",
        "## Research Question",
        "Dense Layer 1 width scan for long ZZ500 / short CYB after Layer 0/1 found a width-supported log-WLS ridge.",
        "",
        "## Layer Inputs",
        f"- Primary from Layer 0/1: `{PREVIOUS_PRIMARY['candidate']}`.",
        f"- Confirmation from Layer 0/1: `{PREVIOUS_CONFIRMATION[0]['candidate']}`, `{PREVIOUS_CONFIRMATION[1]['candidate']}`.",
        "- Dense grid: `mom_day=5..25 step1`, `weight_end=0.50..4.00`.",
        "- Threshold: `score > 0`, R2 filter `>= 0.05`.",
        "",
        "## Implementation Anchor",
        "- Imports V7.7 local cache loader and metrics from `scan_adk_zz500_cyb_spread_long_only.py`.",
        "- Uses vectorized weighted-slope/R2 calculation matching the Layer 0/1 log-WLS formula.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research with two-leg commissions, excluding futures basis, financing, borrow, and short locate costs.",
        "- Source-change rule: `research_only_new_scan_script`.",
        "",
        "## Data Snapshot",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- CYB publication date: {base.CYB_PUBLICATION_DATE}; local rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start rule: latest actual index publication date among the two legs.",
        "- Adjustment mode: price index close from local official cache, no total-return substitution.",
        "",
        "## Cost and Execution Assumptions",
        "- Market: A-share index spread research using daily close data.",
        "- Trading calendar: aligned index dates from the two local cache series.",
        "- Timing: T close signal -> T+1 close-to-close spread return.",
        "- Return stream: ZZ500 close-to-close return minus CYB close-to-close return.",
        f"- Transaction cost: two legs times one-way commission {base.COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- Target-vol, NAV defense, overheat, amount/volume gates, and momentum decay are off.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 1 dense scan artifact.",
        "",
        "## Commands",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"ZZ500/CYB spread Layer 1 dense\" --parameter-group \"log_wls_signal_width_dense_patch\" --repo . --entrypoint \"scan_adk_zz500_cyb_spread_layer1_dense_patch.py\" --date 2026-06-12 --slug \"adk_zz500_cyb_spread_long_only_v77_adk_spread_layer1_dense_patch_log_wls_width\"`",
        "- `python -m py_compile \"scan_adk_zz500_cyb_spread_layer1_dense_patch.py\"`",
        "- `python \"scan_adk_zz500_cyb_spread_layer1_dense_patch.py\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py <run_folder> --decision \"layer1_dense_complete_not_promoted\" --stability-label \"log_wls_width_supported_pending_user_confirmation\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>`",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `local_width.csv`",
        "- `width_candidates.csv`",
        "- `carry_candidates.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Top Full-Sample Results",
        window_table(top_sharpe, 12),
        "",
        "## Baseline Delta Check",
        delta_table(carry, 8),
        "",
        "## Width Candidates",
        window_table(width_candidates, 12) if not width_candidates.empty else "No non-edge width-supported candidates under local width rules.",
        "",
        "## Next-Layer Carry Candidates",
        window_table(carry, 8),
        "",
        "## Stability Classification",
        local_width.head(30).to_markdown(index=False),
        "",
        "## Decision",
        "Layer 1 dense patch completed but not promoted. Stop for user confirmation before Layer 2 score and absolute-bias filters.",
        "",
        "## User-Facing Summary",
        window_table(carry, 8),
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "ZZ500/CYB spread Layer 1 dense",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz500_cyb_spread_long_only.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "layer1_dense_patch_log_wls_width",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "log_wls_signal_width_dense_patch",
        "baseline": {
            "direction": "long_ZZ500_short_CYB",
            "previous_primary": PREVIOUS_PRIMARY,
            "previous_confirmation": PREVIOUS_CONFIRMATION,
            "threshold": 0.0,
        },
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "zz500": {
                "secid": str(mod.CN_DK_ZZ500_SECID),
                "publication_date": base.ZZ500_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_ZZ500_SECID))),
                "rows": int(len(zz500)),
                "start": str(zz500.index.min().date()),
                "end": str(zz500.index.max().date()),
            },
            "cyb": {
                "secid": str(mod.CN_DK_CYB_SECID),
                "publication_date": base.CYB_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_CYB_SECID))),
                "rows": int(len(cyb)),
                "start": str(cyb.index.min().date()),
                "end": str(cyb.index.max().date()),
            },
            "formal": {
                "rows": int(len(panel)),
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
                "start_rule": "latest actual publication/listing date among participants",
                "ratio": "ZZ500 / CYB",
                "return_stream": "ZZ500 pct_change - CYB pct_change",
            },
        },
        "decision": "layer1_dense_complete_not_promoted",
        "stability_label": "log_wls_width_supported_pending_user_confirmation",
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
            "carry_candidates": str(RUN_DIR / "carry_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"ZZ500/CYB spread Layer 1 dense\" --parameter-group \"log_wls_signal_width_dense_patch\" --repo . --entrypoint \"scan_adk_zz500_cyb_spread_layer1_dense_patch.py\" --date 2026-06-12 --slug \"adk_zz500_cyb_spread_long_only_v77_adk_spread_layer1_dense_patch_log_wls_width\"\n"
        "python -m py_compile \"scan_adk_zz500_cyb_spread_layer1_dense_patch.py\"\n"
        "python \"scan_adk_zz500_cyb_spread_layer1_dense_patch.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"layer1_dense_complete_not_promoted\" --stability-label \"log_wls_width_supported_pending_user_confirmation\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict \"{RUN_DIR}\"\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("TOP_SHARPE")
    print(
        top_sharpe[
            [
                "candidate",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "ann_return_last_5y",
                "max_dd_last_5y",
                "ann_return_last_1y",
                "max_dd_last_1y",
            ]
        ]
        .head(12)
        .to_string(index=False)
    )
    print("WIDTH_CANDIDATES")
    if width_candidates.empty:
        print("NONE")
    else:
        print(
            width_candidates[
                [
                    "candidate",
                    "ann_return_full",
                    "max_dd_full",
                    "sharpe_repo_full",
                    "nearby_family80_count",
                    "nearby_anchor_compatible_count",
                    "ann_delta_pp_full",
                    "dd_improve_pp_full",
                ]
            ]
            .head(12)
            .to_string(index=False)
        )
    print("CARRY")
    print(
        carry[
            [
                "candidate",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "ann_return_last_5y",
                "max_dd_last_5y",
                "ann_return_last_1y",
                "max_dd_last_1y",
                "ann_delta_pp_full",
                "dd_improve_pp_full",
                "nearby_family80_count",
                "nearby_anchor_compatible_count",
            ]
        ]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()

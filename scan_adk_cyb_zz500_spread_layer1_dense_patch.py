"""Dense Layer 1 patch for ADK-style long CYB / short ZZ500 spread.

Layer 0/1 found a width-supported bias-momentum family led by 20/30/we2.0,
with 20/30/we1.0 as a lower-drawdown confirmation. This scan stays within
Layer 1: signal window and recency weight only.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_zz500_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_cyb_zz500_spread_long_only_v77_adk_spread_layer1_dense_patch_bias_momentum_width"
BASELINE_CANDIDATE = {
    "candidate": "baseline_l0_bias_ma020_mom030_we2p0_gt0",
    "family": "bias_momentum",
    "bias_ma": 20,
    "mom_day": 30,
    "weight_end": 2.0,
    "threshold": 0.0,
}
CONFIRMATION_CANDIDATE = {
    "candidate": "confirm_l0_bias_ma020_mom030_we1p0_gt0",
    "family": "bias_momentum",
    "bias_ma": 20,
    "mom_day": 30,
    "weight_end": 1.0,
    "threshold": 0.0,
}
WEIGHTS = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 4.0]


def dense_grid() -> list[dict[str, object]]:
    grid: dict[str, dict[str, object]] = {}

    def add_region(bias_values, mom_values, weight_values) -> None:
        for bias_ma in bias_values:
            for mom_day in mom_values:
                for weight_end in weight_values:
                    key = (int(bias_ma), int(mom_day), float(weight_end))
                    grid[str(key)] = {
                        "candidate": f"dense_bias_ma{bias_ma:03d}_mom{mom_day:03d}_we{str(weight_end).replace('.', 'p')}_gt0",
                        "family": "bias_momentum",
                        "bias_ma": int(bias_ma),
                        "mom_day": int(mom_day),
                        "weight_end": float(weight_end),
                        "threshold": 0.0,
                    }

    add_region(range(10, 51, 5), range(20, 46, 1), WEIGHTS)
    add_region(range(30, 61, 5), range(14, 31, 1), WEIGHTS[:11])
    add_region(range(55, 86, 5), range(24, 41, 2), WEIGHTS[2:])
    return list(grid.values())


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
    bias_ma = int(candidate["bias_ma"])
    mom_day = int(candidate["mom_day"])
    weight_end = float(candidate["weight_end"])
    threshold = float(candidate.get("threshold", 0.0))

    feature = ratio / ratio.rolling(bias_ma).mean() - 1.0
    score, r2 = fast_weighted_slope_and_r2(feature, mom_day, weight_end)
    raw_signal = ((score > threshold) & (r2 >= 0.05)).astype(float)
    exec_weight = raw_signal.shift(1).fillna(0.0)
    spread_return = panel["CYB"].pct_change().fillna(0.0) - panel["ZZ500"].pct_change().fillna(0.0)
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
    return out.iloc[max(bias_ma, mom_day) + 2 :].copy()


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def pp(value: float) -> str:
    return f"{value * 100:+.2f}pp"


def add_baseline_deltas(window_metrics: pd.DataFrame, baseline_metrics: dict[str, dict[str, object]]) -> pd.DataFrame:
    out = window_metrics.copy()
    for segment, _years in base.SEGMENTS:
        out[f"ann_delta_vs_l0_{segment}"] = out[f"ann_return_{segment}"] - float(baseline_metrics[segment]["ann_return"])
        out[f"dd_improve_vs_l0_{segment}"] = out[f"max_dd_{segment}"] - float(baseline_metrics[segment]["max_dd"])
    return out


def add_pass_flags(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = window_metrics.copy()
    best_sharpe = float(df["sharpe_repo_full"].max())
    best_return = float(df["ann_return_full"].max())
    df["near_peak_pass"] = (
        (df["sharpe_repo_full"] >= best_sharpe * 0.80)
        & (df["ann_return_full"] >= best_return * 0.80)
        & (df["max_dd_full"] >= -0.28)
    )
    df["practical_pass"] = (
        (df["ann_return_full"] >= 0.060)
        & (df["max_dd_full"] >= -0.20)
        & (df["ann_return_last_5y"] >= 0.030)
        & (df["ann_return_last_1y"] >= 0.12)
    )
    df["dd_first_pass"] = (
        (df["ann_return_full"] >= 0.055)
        & (df["max_dd_full"] >= -0.16)
        & (df["ann_return_last_5y"] >= 0.030)
        & (df["ann_return_last_3y"] >= 0.040)
        & (df["ann_return_last_1y"] >= 0.12)
    )
    df["width_score"] = (
        df["sharpe_repo_full"]
        + df["ann_return_full"].clip(lower=0.0, upper=0.08) * 1.5
        + df["ann_return_last_5y"].clip(lower=-0.02, upper=0.05)
        + df["ann_return_last_1y"].clip(lower=0.0, upper=0.25) * 0.2
        + df["max_dd_full"].clip(lower=-0.35, upper=0.0) * 0.10
    )
    return df


def build_local_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = add_pass_flags(window_metrics)
    rows = []
    seed_pool = pd.concat(
        [
            df.sort_values("sharpe_repo_full", ascending=False).head(120),
            df.sort_values("width_score", ascending=False).head(120),
            df[df["practical_pass"]].sort_values("width_score", ascending=False).head(120),
            df[df["dd_first_pass"]].sort_values("width_score", ascending=False).head(120),
        ],
        ignore_index=True,
    ).drop_duplicates("candidate")

    min_bias, max_bias = int(df["bias_ma"].min()), int(df["bias_ma"].max())
    min_mom, max_mom = int(df["mom_day"].min()), int(df["mom_day"].max())
    min_weight, max_weight = float(df["weight_end"].min()), float(df["weight_end"].max())

    for _, row in seed_pool.iterrows():
        nearby = df[
            (df["bias_ma"].sub(row["bias_ma"]).abs() <= 10)
            & (df["mom_day"].sub(row["mom_day"]).abs() <= 3)
            & (df["weight_end"].sub(row["weight_end"]).abs() <= 0.5)
        ]
        near_peak = nearby[nearby["near_peak_pass"]]
        practical = nearby[nearby["practical_pass"]]
        dd_first = nearby[nearby["dd_first_pass"]]
        edge_flag = bool(
            row["bias_ma"] in (min_bias, max_bias)
            or row["mom_day"] in (min_mom, max_mom)
            or float(row["weight_end"]) in (min_weight, max_weight)
        )
        practical_patch = (
            len(practical) >= 8
            and practical["bias_ma"].nunique() >= 2
            and practical["mom_day"].nunique() >= 2
            and practical["weight_end"].nunique() >= 2
        )
        dd_patch = (
            len(dd_first) >= 5
            and dd_first["bias_ma"].nunique() >= 2
            and dd_first["mom_day"].nunique() >= 2
            and dd_first["weight_end"].nunique() >= 2
        )
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
                "ann_delta_vs_l0_full": float(row["ann_delta_vs_l0_full"]),
                "dd_improve_vs_l0_full": float(row["dd_improve_vs_l0_full"]),
                "ann_delta_vs_l0_last_5y": float(row["ann_delta_vs_l0_last_5y"]),
                "dd_improve_vs_l0_last_5y": float(row["dd_improve_vs_l0_last_5y"]),
                "width_score": float(row["width_score"]),
                "nearby_count": int(len(nearby)),
                "nearby_near_peak_count": int(len(near_peak)),
                "nearby_practical_count": int(len(practical)),
                "nearby_dd_first_count": int(len(dd_first)),
                "practical_bias_count": int(practical["bias_ma"].nunique()),
                "practical_mom_count": int(practical["mom_day"].nunique()),
                "practical_weight_count": int(practical["weight_end"].nunique()),
                "dd_bias_count": int(dd_first["bias_ma"].nunique()),
                "dd_mom_count": int(dd_first["mom_day"].nunique()),
                "dd_weight_count": int(dd_first["weight_end"].nunique()),
                "edge_flag": edge_flag,
                "practical_local_patch": bool(practical_patch),
                "dd_first_local_patch": bool(dd_patch),
                "width_supported": bool((practical_patch or dd_patch) and not edge_flag),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["width_supported", "practical_local_patch", "dd_first_local_patch", "nearby_practical_count", "width_score"],
        ascending=[False, False, False, False, False],
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
                    "near_peak_pass_count": int(group["near_peak_pass"].sum()),
                    "practical_pass_count": int(group["practical_pass"].sum()),
                    "dd_first_pass_count": int(group["dd_first_pass"].sum()),
                }
            )
    return pd.DataFrame(rows)


def window_table(df: pd.DataFrame, n: int = 12) -> str:
    cols = ["candidate", "bias_ma", "mom_day", "weight_end"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def build_selected_daily_curves(panel: pd.DataFrame, candidates: list[dict[str, object]]) -> pd.DataFrame:
    daily_curves = []
    seen = set()
    for candidate in candidates:
        name = str(candidate["candidate"])
        if name in seen:
            continue
        seen.add(name)
        result = build_candidate_returns(panel, candidate)
        nav = (1.0 + result["return"]).cumprod()
        daily_curves.append(
            pd.DataFrame(
                {
                    "date": result.index,
                    "candidate": name,
                    "return": result["return"].to_numpy(),
                    "nav": nav.to_numpy(),
                    "weight": result["weight"].to_numpy(),
                    "turnover": result["turnover"].to_numpy(),
                    "cost": result["cost"].to_numpy(),
                }
            )
        )
    return pd.concat(daily_curves, ignore_index=True)


def rows_to_candidates(df: pd.DataFrame) -> list[dict[str, object]]:
    candidates = []
    for _, row in df.iterrows():
        candidates.append(
            {
                "candidate": str(row["candidate"]),
                "family": "bias_momentum",
                "bias_ma": int(row["bias_ma"]),
                "mom_day": int(row["mom_day"]),
                "weight_end": float(row["weight_end"]),
                "threshold": 0.0,
            }
        )
    return candidates


def baseline_table(df: pd.DataFrame, n: int = 12) -> str:
    display = df.head(n)[["candidate", "bias_ma", "mom_day", "weight_end"]].copy()
    for segment, _years in base.SEGMENTS:
        display[segment] = df.head(n).apply(
            lambda r: (
                f"{pct(float(r[f'ann_return_{segment}']))}/{pct(float(r[f'max_dd_{segment}']))} "
                f"({pp(float(r[f'ann_delta_vs_l0_{segment}']))}, "
                f"{pp(float(r[f'dd_improve_vs_l0_{segment}']))})"
            ),
            axis=1,
        )
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod = base.load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    zz500 = mod._load_cn_official_cache(mod.CN_DK_ZZ500_SECID).rename(columns={"close": "ZZ500"})
    panel = pd.concat([cyb["CYB"], zz500["ZZ500"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["CYB"] / panel["ZZ500"]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = dense_grid()
    long_rows = []
    wide_rows = []
    baseline_result = build_candidate_returns(panel, BASELINE_CANDIDATE)
    confirmation_result = build_candidate_returns(panel, CONFIRMATION_CANDIDATE)
    baseline_metrics = {segment: base.metrics_for_segment(baseline_result, segment, years) for segment, years in base.SEGMENTS}
    confirmation_metrics = {segment: base.metrics_for_segment(confirmation_result, segment, years) for segment, years in base.SEGMENTS}

    for candidate in grid:
        result = build_candidate_returns(panel, candidate)
        wide = {**candidate}
        for segment, years in base.SEGMENTS:
            m = base.metrics_for_segment(result, segment, years)
            long_rows.append({**candidate, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baseline_deltas(pd.DataFrame(wide_rows), baseline_metrics)
    window_metrics = add_pass_flags(window_metrics)
    local_width = build_local_width(window_metrics)
    ridge = build_axis_width(window_metrics)
    top_sharpe = window_metrics.sort_values("sharpe_repo_full", ascending=False).head(30)
    width_candidates = local_width[local_width["width_supported"]].head(40)
    practical_candidates = window_metrics[window_metrics["practical_pass"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    dd_candidates = window_metrics[window_metrics["dd_first_pass"]].sort_values(
        ["max_dd_full", "ann_return_full"], ascending=[False, False]
    )
    carry = pd.concat(
        [
            width_candidates.head(8),
            local_width[local_width["dd_first_local_patch"] & ~local_width["edge_flag"]].head(6),
            local_width[~local_width["edge_flag"]].head(6),
        ],
        ignore_index=True,
    ).drop_duplicates("candidate").head(12)
    selected_daily_candidates = (
        [BASELINE_CANDIDATE, CONFIRMATION_CANDIDATE]
        + rows_to_candidates(top_sharpe.head(20))
        + rows_to_candidates(carry)
        + rows_to_candidates(practical_candidates.head(20))
        + rows_to_candidates(dd_candidates.head(20))
    )
    daily = build_selected_daily_curves(panel, selected_daily_candidates)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    local_width.to_csv(RUN_DIR / "local_width.csv", index=False, encoding="utf-8-sig")
    width_candidates.to_csv(RUN_DIR / "width_candidates.csv", index=False, encoding="utf-8-sig")
    practical_candidates.to_csv(RUN_DIR / "practical_candidates.csv", index=False, encoding="utf-8-sig")
    dd_candidates.to_csv(RUN_DIR / "dd_first_candidates.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    decision = "layer1_dense_complete_not_promoted"
    stability = "width_supported_dense_patch_pending_user_confirmation" if not width_candidates.empty else "dense_patch_requires_review"
    record_lines = [
        "# CYB/ZZ500 ADK Spread Layer 1 Dense Patch",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        f"- decision: `{decision}`",
        f"- stability: `{stability}`",
        "",
        "## Research Question",
        "Dense scan around the Layer 0/1 width-supported bias-momentum family for long CYB / short ZZ500.",
        "",
        "## Layer Inputs",
        "- Previous-layer primary baseline: `bias_ma020_mom030_we2p0_gt0`.",
        "- Previous-layer lower-DD confirmation: `bias_ma020_mom030_we1p0_gt0`.",
        "- Dense grid covers `bias_ma=10..60`, `mom_day=14..45`, `weight_end=0.75..4.0`, plus an 80/30 watch region observed in Layer 0/1.",
        "",
        "## Implementation Anchor",
        "- Imports V7.7 local cache loader and metrics from `scan_adk_cyb_zz500_spread_long_only.py`.",
        "- Uses vectorized weighted-slope/R2 calculation matching the Layer 0/1 formula.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research with two-leg commissions, excluding futures basis, financing, borrow, and short locate costs.",
        "- Source-change rule: `research_only_new_scan_script`.",
        "",
        "## Data Snapshot",
        f"- CYB publication date: {base.CYB_PUBLICATION_DATE}; local rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start rule: latest actual index publication/listing date among the two legs.",
        "- Adjustment mode: price index close from local official cache, no total-return substitution.",
        "",
        "## Cost and Execution Assumptions",
        "- Market: A-share index spread research using daily close data.",
        "- Trading calendar: aligned index dates from the two local cache series.",
        "- Timing: T close signal -> T+1 close-to-close spread return.",
        "- Return stream: CYB close-to-close return minus ZZ500 close-to-close return.",
        f"- Transaction cost: two legs times one-way commission {base.COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- Target-vol, NAV defense, overheat, amount/volume gates, and momentum decay are off.",
        "- Practical local patch: nearby +/-10 bias, +/-3 mom, +/-0.5 weight contains at least 8 practical-pass points across at least 2 values on every axis.",
        "",
        "## Same-Line Baselines",
        f"- Primary baseline Full: {pct(float(baseline_metrics['full']['ann_return']))}/{pct(float(baseline_metrics['full']['max_dd']))}; 5Y: {pct(float(baseline_metrics['last_5y']['ann_return']))}/{pct(float(baseline_metrics['last_5y']['max_dd']))}; 1Y: {pct(float(baseline_metrics['last_1y']['ann_return']))}/{pct(float(baseline_metrics['last_1y']['max_dd']))}.",
        f"- Lower-DD confirmation Full: {pct(float(confirmation_metrics['full']['ann_return']))}/{pct(float(confirmation_metrics['full']['max_dd']))}; 5Y: {pct(float(confirmation_metrics['last_5y']['ann_return']))}/{pct(float(confirmation_metrics['last_5y']['max_dd']))}; 1Y: {pct(float(confirmation_metrics['last_1y']['ann_return']))}/{pct(float(confirmation_metrics['last_1y']['max_dd']))}.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 1 dense scan artifact.",
        "",
        "## Commands",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"CYB/ZZ500 spread Layer 1 dense patch\" --parameter-group \"bias_ma_mom_day_weight_end\" --repo . --entrypoint \"scan_adk_cyb_zz500_spread_layer1_dense_patch.py\" --date 2026-06-12 --slug \"adk_cyb_zz500_spread_long_only_v77_adk_spread_layer1_dense_patch_bias_momentum_width\"`",
        "- `python -m py_compile \"scan_adk_cyb_zz500_spread_layer1_dense_patch.py\"`",
        "- `python \"scan_adk_cyb_zz500_spread_layer1_dense_patch.py\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py <run_folder> --decision \"layer1_dense_complete_not_promoted\" --stability-label \"<stability>\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>`",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv` (selected representative candidates: Layer 0/1 baselines, top Sharpe, carry, practical, and DD-first rows)",
        "- `ridge_width.csv`",
        "- `local_width.csv`",
        "- `width_candidates.csv`",
        "- `practical_candidates.csv`",
        "- `dd_first_candidates.csv`",
        "- `carry_candidates.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        window_table(top_sharpe, 12),
        "",
        "## Same-Line Baseline Comparison",
        "Baseline is Layer 0/1 primary `20/30/we2.0`. Cell format: `candidate ann/DD (delta ann, delta DD improvement)`.",
        "",
        baseline_table(top_sharpe, 12),
        "",
        "## Width Candidates",
        window_table(width_candidates, 12) if not width_candidates.empty else "No width-supported dense candidate passed the local patch rule.",
        "",
        "## Next-Layer Carry Candidates",
        window_table(carry, 8),
        "",
        "## Window Results",
        "The tables above include full, last_10y, last_5y, last_3y, and last_1y annualized return and max drawdown. See `window_metrics.csv` for the complete dense grid.",
        "",
        "## Stability Classification",
        local_width.head(30).to_markdown(index=False),
        "",
        "## Decision",
        "Layer 1 dense patch completed but not promoted. Stop for user confirmation before any Layer 2 filters.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "CYB/ZZ500 spread Layer 1 dense patch",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_cyb_zz500_spread_long_only.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "layer1_dense_patch_bias_momentum_width",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "bias_ma_mom_day_weight_end",
        "baseline": {
            "direction": "long_CYB_short_ZZ500",
            "previous_primary": BASELINE_CANDIDATE,
            "previous_lower_dd_confirmation": CONFIRMATION_CANDIDATE,
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
        "width_rules": {
            "near_peak_pass": "full Sharpe >= 80% dense best; full return >= 80% dense best; full maxDD >= -28%",
            "practical_pass": "full return >= 6%; full maxDD >= -20%; 5Y return >= 3%; 1Y return >= 12%",
            "dd_first_pass": "full return >= 5.5%; full maxDD >= -16%; 5Y return >= 3%; 3Y return >= 4%; 1Y return >= 12%",
            "local_patch": "within +/-10 bias, +/-3 mom, +/-0.5 weight; practical >=8 points or dd-first >=5 points across at least 2 values per axis; edge candidates not promoted",
        },
        "daily_curves_scope": "selected representative candidates only; full candidate metrics are in scan_summary.csv and window_metrics.csv",
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "cyb": {
                "secid": str(mod.CN_DK_CYB_SECID),
                "publication_date": base.CYB_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_CYB_SECID))),
                "rows": int(len(cyb)),
                "start": str(cyb.index.min().date()),
                "end": str(cyb.index.max().date()),
            },
            "zz500": {
                "secid": str(mod.CN_DK_ZZ500_SECID),
                "publication_date": base.ZZ500_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_ZZ500_SECID))),
                "rows": int(len(zz500)),
                "start": str(zz500.index.min().date()),
                "end": str(zz500.index.max().date()),
            },
            "formal": {
                "rows": int(len(panel)),
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
                "start_rule": "latest actual publication/listing date among participants",
                "ratio": "CYB / ZZ500",
                "return_stream": "CYB pct_change - ZZ500 pct_change",
            },
        },
        "decision": decision,
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
            "width_candidates": str(RUN_DIR / "width_candidates.csv"),
            "practical_candidates": str(RUN_DIR / "practical_candidates.csv"),
            "dd_first_candidates": str(RUN_DIR / "dd_first_candidates.csv"),
            "carry_candidates": str(RUN_DIR / "carry_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"CYB/ZZ500 spread Layer 1 dense patch\" --parameter-group \"bias_ma_mom_day_weight_end\" --repo . --entrypoint \"scan_adk_cyb_zz500_spread_layer1_dense_patch.py\" --date 2026-06-12 --slug \"adk_cyb_zz500_spread_long_only_v77_adk_spread_layer1_dense_patch_bias_momentum_width\"\n"
        "python -m py_compile \"scan_adk_cyb_zz500_spread_layer1_dense_patch.py\"\n"
        "python \"scan_adk_cyb_zz500_spread_layer1_dense_patch.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"{decision}\" --stability-label \"{stability}\"\n"
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
                "bias_ma",
                "mom_day",
                "weight_end",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "ann_return_last_5y",
                "max_dd_last_5y",
                "ann_return_last_1y",
                "max_dd_last_1y",
                "ann_delta_vs_l0_full",
                "dd_improve_vs_l0_full",
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
                    "ann_return_last_5y",
                    "ann_return_last_1y",
                    "nearby_practical_count",
                    "nearby_dd_first_count",
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
                "nearby_practical_count",
                "nearby_dd_first_count",
                "width_supported",
            ]
        ]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()

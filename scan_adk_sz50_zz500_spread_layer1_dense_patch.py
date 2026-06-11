"""Dense Layer 1 patch for long SZ50 / short ZZ500 spread.

The Layer 0/1 winner did not pass width checks. This run searches for a
secondary, width-supported signal area in the same direction without adding
target-vol, NAV defense, overheat, amount/volume, or momentum-decay overlays.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_sz50_zz500_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_sz50_zz500_spread_long_only_v77_adk_spread_layer1_dense_patch_secondary_width"
WEIGHT_GRID = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25]
PREVIOUS_TOP = "bias_ma080_mom020_we3p0_gt0"
PREVIOUS_CARRY = [
    "bias_ma080_mom020_we3p0_gt0",
    "bias_ma060_mom015_we1p0_gt0",
    "bias_ma080_mom015_we1p0_gt0",
    "bias_ma120_mom015_we3p0_gt0",
    "bias_ma060_mom030_we3p0_gt0",
]


def dense_grid() -> list[dict[str, object]]:
    grid: dict[str, dict[str, object]] = {}

    def add_bias_region(bias_values, mom_values, weight_values) -> None:
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

    add_bias_region(range(50, 96, 5), range(12, 25, 2), WEIGHT_GRID)
    add_bias_region(range(50, 76, 5), range(24, 35, 2), [1.0, 1.5, 2.0, 2.5, 3.0, 3.25])
    add_bias_region(range(95, 126, 5), range(12, 25, 2), [1.0, 1.5, 2.0, 2.5, 3.0, 3.25])
    add_bias_region(range(20, 46, 5), range(24, 35, 2), [1.0, 1.5, 2.0, 2.5, 3.0, 3.25])
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
    weight_end = float(candidate.get("weight_end", 1.0))
    threshold = float(candidate.get("threshold", 0.0))

    feature = ratio / ratio.rolling(bias_ma).mean() - 1.0
    score, r2 = fast_weighted_slope_and_r2(feature, mom_day, weight_end)
    raw_signal = ((score > threshold) & (r2 >= 0.05)).astype(float)
    exec_weight = raw_signal.shift(1).fillna(0.0)
    spread_return = panel["SZ50"].pct_change().fillna(0.0) - panel["ZZ500"].pct_change().fillna(0.0)
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


def add_pass_flags(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = window_metrics.copy()
    best_sharpe = float(df["sharpe_repo_full"].max())
    best_return = float(df["ann_return_full"].max())
    df["near_peak_pass"] = (
        (df["sharpe_repo_full"] >= best_sharpe * 0.80)
        & (df["ann_return_full"] >= best_return * 0.80)
        & (df["max_dd_full"] >= -0.42)
    )
    df["secondary_pass"] = (
        (df["sharpe_repo_full"] >= best_sharpe * 0.60)
        & (df["ann_return_full"] >= best_return * 0.60)
        & (df["max_dd_full"] >= -0.42)
        & (df["ann_return_last_5y"] >= -0.005)
        & (df["ann_return_last_1y"] >= -0.12)
    )
    df["recent_resilient_pass"] = (
        (df["ann_return_full"] >= 0.005)
        & (df["ann_return_last_5y"] >= 0.005)
        & (df["ann_return_last_3y"] >= -0.005)
        & (df["ann_return_last_1y"] >= -0.08)
    )
    df["width_score"] = (
        df["sharpe_repo_full"]
        + df["ann_return_full"].clip(lower=-0.02, upper=0.04) * 1.5
        + df["ann_return_last_5y"].clip(lower=-0.02, upper=0.04)
        + df["ann_return_last_1y"].clip(lower=-0.15, upper=0.02) * 0.30
        + df["max_dd_full"].clip(lower=-0.50, upper=0.0) * 0.15
    )
    return df


def build_local_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = add_pass_flags(window_metrics)
    rows = []
    min_bias, max_bias = int(df["bias_ma"].min()), int(df["bias_ma"].max())
    min_mom, max_mom = int(df["mom_day"].min()), int(df["mom_day"].max())
    min_weight, max_weight = float(df["weight_end"].min()), float(df["weight_end"].max())

    seed_pool = pd.concat(
        [
            df.sort_values("sharpe_repo_full", ascending=False).head(120),
            df.sort_values("width_score", ascending=False).head(120),
            df[df["secondary_pass"]].sort_values("width_score", ascending=False).head(120),
            df[df["recent_resilient_pass"]].sort_values("width_score", ascending=False).head(120),
        ],
        ignore_index=True,
    ).drop_duplicates("candidate")

    for _, row in seed_pool.iterrows():
        nearby = df[
            (df["bias_ma"].sub(row["bias_ma"]).abs() <= 10)
            & (df["mom_day"].sub(row["mom_day"]).abs() <= 2)
            & (df["weight_end"].sub(row["weight_end"]).abs() <= 0.5)
        ]
        near_peak = nearby[nearby["near_peak_pass"]]
        secondary = nearby[nearby["secondary_pass"]]
        recent = nearby[nearby["recent_resilient_pass"]]
        rows.append(
            {
                "candidate": row["candidate"],
                "family": row["family"],
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
                "nearby_near_peak_count": int(len(near_peak)),
                "nearby_secondary_count": int(len(secondary)),
                "nearby_recent_resilient_count": int(len(recent)),
                "secondary_bias_count": int(secondary["bias_ma"].nunique()),
                "secondary_mom_count": int(secondary["mom_day"].nunique()),
                "secondary_weight_count": int(secondary["weight_end"].nunique()),
                "recent_bias_count": int(recent["bias_ma"].nunique()),
                "recent_mom_count": int(recent["mom_day"].nunique()),
                "recent_weight_count": int(recent["weight_end"].nunique()),
                "edge_flag": bool(
                    row["bias_ma"] in (min_bias, max_bias)
                    or row["mom_day"] in (min_mom, max_mom)
                    or float(row["weight_end"]) in (min_weight, max_weight)
                ),
                "secondary_local_patch": bool(
                    len(secondary) >= 10
                    and secondary["bias_ma"].nunique() >= 2
                    and secondary["mom_day"].nunique() >= 2
                    and secondary["weight_end"].nunique() >= 2
                ),
                "recent_local_patch": bool(
                    len(recent) >= 8
                    and recent["bias_ma"].nunique() >= 2
                    and recent["mom_day"].nunique() >= 2
                    and recent["weight_end"].nunique() >= 2
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(
        [
            "secondary_local_patch",
            "recent_local_patch",
            "nearby_secondary_count",
            "nearby_recent_resilient_count",
            "width_score",
        ],
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
                    "family": "bias_momentum",
                    "axis": axis,
                    "value": value,
                    "best_candidate": best["candidate"],
                    "best_width_score": float(best["width_score"]),
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "best_5y_ann_return": float(best["ann_return_last_5y"]),
                    "best_1y_ann_return": float(best["ann_return_last_1y"]),
                    "near_peak_pass_count": int(group["near_peak_pass"].sum()),
                    "secondary_pass_count": int(group["secondary_pass"].sum()),
                    "recent_resilient_pass_count": int(group["recent_resilient_pass"].sum()),
                }
            )
    return pd.DataFrame(rows)


def select_carry_candidates(local_width: pd.DataFrame, window_metrics: pd.DataFrame) -> pd.DataFrame:
    lw = local_width[~local_width["edge_flag"]].copy()
    secondary = lw[lw["secondary_local_patch"]].sort_values(
        ["nearby_secondary_count", "nearby_recent_resilient_count", "width_score"],
        ascending=[False, False, False],
    )
    recent = lw[lw["recent_local_patch"]].sort_values(
        ["nearby_recent_resilient_count", "nearby_secondary_count", "width_score"],
        ascending=[False, False, False],
    )
    carry = pd.concat([secondary.head(4), recent.head(4)], ignore_index=True).drop_duplicates("candidate")
    if carry.empty:
        carry = lw.sort_values(["nearby_secondary_count", "nearby_recent_resilient_count", "width_score"], ascending=False).head(8)
    metric_cols = [
        "candidate",
        "family",
        "bias_ma",
        "mom_day",
        "weight_end",
        "ann_return_full",
        "max_dd_full",
        "sharpe_repo_full",
        "ann_return_last_10y",
        "max_dd_last_10y",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "ann_return_last_3y",
        "max_dd_last_3y",
        "ann_return_last_1y",
        "max_dd_last_1y",
    ]
    return carry.merge(window_metrics[metric_cols], on=["candidate", "family", "bias_ma", "mom_day", "weight_end"], suffixes=("", "_metric"))


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def window_table(df: pd.DataFrame, n: int = 12) -> str:
    cols = ["candidate", "bias_ma", "mom_day", "weight_end"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod = base.load_v77()
    sz50 = mod._load_cn_official_cache(mod.CN_DK_SZ50_SECID).rename(columns={"close": "SZ50"})
    zz500 = mod._load_cn_official_cache(mod.CN_DK_ZZ500_SECID).rename(columns={"close": "ZZ500"})
    panel = pd.concat([sz50["SZ50"], zz500["ZZ500"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["SZ50"] / panel["ZZ500"]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = dense_grid()
    long_rows = []
    wide_rows = []
    daily_curves = []

    for candidate in grid:
        result = build_candidate_returns(panel, candidate)
        nav = (1.0 + result["return"]).cumprod()
        daily_curves.append(
            pd.DataFrame(
                {
                    "date": result.index,
                    "candidate": candidate["candidate"],
                    "return": result["return"].to_numpy(),
                    "nav": nav.to_numpy(),
                    "weight": result["weight"].to_numpy(),
                    "turnover": result["turnover"].to_numpy(),
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
    daily = pd.concat(daily_curves, ignore_index=True)
    local_width = build_local_width(window_metrics)
    ridge = build_axis_width(window_metrics)
    top_sharpe = window_metrics.sort_values("sharpe_repo_full", ascending=False).head(30)
    width_candidates = local_width[
        (~local_width["edge_flag"]) & (local_width["secondary_local_patch"] | local_width["recent_local_patch"])
    ].head(40)
    carry = select_carry_candidates(local_width, window_metrics)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    local_width.to_csv(RUN_DIR / "local_width.csv", index=False, encoding="utf-8-sig")
    width_candidates.to_csv(RUN_DIR / "width_candidates.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# SZ50/ZZ500 ADK Spread Layer 1 Dense Patch",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer1_dense_secondary_width_complete_not_promoted`",
        "- stability: `secondary_width_supported_pending_user_confirmation`",
        "",
        "## Research Question",
        "Layer 0/1 width failed, so this scan searches for a secondary point with enough local width for long SZ50 / short ZZ500.",
        "",
        "## Layer Inputs",
        "- Previous-layer top candidate:",
        f"  - `{PREVIOUS_TOP}`",
        "- Previous-layer carry/watch list:",
        *[f"  - `{item}`" for item in PREVIOUS_CARRY],
        "- Dense grid covers the top region, the 60/15 secondary region, the 60/30 recent-resilient region, and the 120/15 region.",
        "",
        "## Implementation Anchor",
        "- Imports V7.7 local cache loader and metrics from `scan_adk_sz50_zz500_spread_long_only.py`.",
        "- Uses vectorized weighted-slope/R2 calculation matching the Layer 0/1 formula.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research with two-leg commissions, excluding futures basis, financing, borrow, and short locate costs.",
        "- Source-change rule: `research_only_no_source_change`.",
        "",
        "## Data Snapshot",
        f"- SZ50 publication date: {base.SZ50_PUBLICATION_DATE}; local rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start rule: latest actual index publication date among the two legs.",
        "- Adjustment mode: price index close from local official cache, no total-return substitution.",
        "",
        "## Cost and Execution Assumptions",
        "- Market: A-share index spread research using daily close data.",
        "- Trading calendar: aligned index dates from the two local cache series.",
        "- Timing: T close signal -> T+1 close-to-close spread return.",
        "- Return stream: SZ50 close-to-close return minus ZZ500 close-to-close return.",
        f"- Transaction cost: two legs times one-way commission {base.COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- Target-vol, NAV defense, overheat, amount/volume gates, and momentum decay are off.",
        "- Secondary width gate: local neighborhood within +/-10 bias, +/-2 mom, +/-0.5 weight must contain at least 10 secondary-pass points across at least 2 values on every axis.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 1 dense scan artifact.",
        "",
        "## Commands",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"SZ50/ZZ500 spread Layer 1 dense width-first\" --parameter-group \"secondary_width_supported_signal_patch\" --repo . --entrypoint \"scan_adk_sz50_zz500_spread_layer1_dense_patch.py\" --date 2026-06-12 --slug \"adk_sz50_zz500_spread_long_only_v77_adk_spread_layer1_dense_patch_secondary_width\"`",
        "- `python -m py_compile \"scan_adk_sz50_zz500_spread_layer1_dense_patch.py\"`",
        "- `python \"scan_adk_sz50_zz500_spread_layer1_dense_patch.py\"`",
        "- strict artifact checker after run.",
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
        "## Full-Sample Results",
        window_table(top_sharpe, 12),
        "",
        "## Window Results",
        "The top table includes full, last_10y, last_5y, last_3y, and last_1y annualized return and max drawdown. See `window_metrics.csv` for the complete dense grid.",
        "",
        "## Stability Classification",
        width_candidates.head(20).to_markdown(index=False),
        "",
        "## Decision",
        "Layer 1 dense secondary-width scan completed but not promoted. Stop for user confirmation before Layer 2 score and absolute-bias filters.",
        "",
        "## User-Facing Summary",
        "The carry list intentionally favors local width over the single highest full-sample Sharpe.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "SZ50/ZZ500 spread Layer 1 dense width-first",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_sz50_zz500_spread_long_only.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "layer1_dense_patch_secondary_width",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "secondary_width_supported_signal_patch",
        "baseline": {
            "direction": "long_SZ50_short_ZZ500",
            "previous_top": PREVIOUS_TOP,
            "previous_carry": PREVIOUS_CARRY,
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
            "near_peak_pass": "full Sharpe >= 80% of dense best; full return >= 80% of dense best; full maxDD >= -42%",
            "secondary_pass": "full Sharpe >= 60% of dense best; full return >= 60% of dense best; full maxDD >= -42%; 5Y return >= -0.5%; 1Y return >= -12%",
            "recent_resilient_pass": "full return >= 0.5%; 5Y return >= 0.5%; 3Y return >= -0.5%; 1Y return >= -8%",
            "secondary_local_patch": "within +/-10 bias, +/-2 mom, +/-0.5 weight: >=10 secondary-pass points, >=2 unique values on every axis",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "sz50": {
                "secid": str(mod.CN_DK_SZ50_SECID),
                "publication_date": base.SZ50_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_SZ50_SECID))),
                "rows": int(len(sz50)),
                "start": str(sz50.index.min().date()),
                "end": str(sz50.index.max().date()),
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
                "ratio": "SZ50 / ZZ500",
                "return_stream": "SZ50 pct_change - ZZ500 pct_change",
            },
        },
        "decision": "layer1_dense_secondary_width_complete_not_promoted",
        "stability_label": "secondary_width_supported_pending_user_confirmation",
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
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"SZ50/ZZ500 spread Layer 1 dense width-first\" --parameter-group \"secondary_width_supported_signal_patch\" --repo . --entrypoint \"scan_adk_sz50_zz500_spread_layer1_dense_patch.py\" --date 2026-06-12 --slug \"adk_sz50_zz500_spread_long_only_v77_adk_spread_layer1_dense_patch_secondary_width\"\n"
        "python -m py_compile \"scan_adk_sz50_zz500_spread_layer1_dense_patch.py\"\n"
        "python \"scan_adk_sz50_zz500_spread_layer1_dense_patch.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"layer1_dense_secondary_width_complete_not_promoted\" --stability-label \"secondary_width_supported_pending_user_confirmation\"\n"
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
    print(
        width_candidates[
            [
                "candidate",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "ann_return_last_5y",
                "ann_return_last_1y",
                "nearby_secondary_count",
                "nearby_recent_resilient_count",
                "secondary_local_patch",
                "recent_local_patch",
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
                "nearby_secondary_count",
                "nearby_recent_resilient_count",
            ]
        ]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()

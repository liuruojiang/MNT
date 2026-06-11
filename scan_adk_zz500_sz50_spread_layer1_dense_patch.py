"""Dense Layer 1 patch for long ZZ500 / short SZ50 spread.

This layer widens the confirmed Layer 0/1 candidates:
- bias-momentum around the width-first secondary ridge near bias_ma=100, mom=20.
- log weighted-slope momentum around the width-supported mom=15, weight=1..2 area.

No target-vol, NAV defense, overheat, amount/volume, or momentum-decay overlay is
applied in this layer.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_sz50_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_sz50_spread_long_only_v77_adk_spread_layer1_dense_patch_width_first"
WEIGHT_GRID = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25]
PREVIOUS_CARRY = [
    "bias_ma100_mom020_we2p0_gt0",
    "bias_ma100_mom020_we1p0_gt0",
    "log_wls_mom015_we2p0_gt0",
    "log_wls_mom015_we1p0_gt0",
]


def dense_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for bias_ma in range(75, 126, 5):
        for mom_day in range(12, 29, 2):
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
    for mom_day in range(10, 26):
        for weight_end in WEIGHT_GRID:
            grid.append(
                {
                    "candidate": f"dense_log_wls_mom{mom_day:03d}_we{str(weight_end).replace('.', 'p')}_gt0",
                    "family": "log_wls_momentum",
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
    family = str(candidate["family"])
    threshold = float(candidate.get("threshold", 0.0))
    weight_end = float(candidate.get("weight_end", 1.0))
    mom_day = int(candidate["mom_day"])

    if family == "bias_momentum":
        bias_ma = int(candidate["bias_ma"])
        feature = ratio / ratio.rolling(bias_ma).mean() - 1.0
        warmup = max(bias_ma, mom_day) + 2
    elif family == "log_wls_momentum":
        feature = np.log(ratio)
        warmup = mom_day + 2
    else:
        raise ValueError(f"unsupported dense family: {family}")

    score, r2 = fast_weighted_slope_and_r2(feature, mom_day, weight_end)
    raw_signal = ((score > threshold) & (r2 >= 0.05)).astype(float)
    exec_weight = raw_signal.shift(1).fillna(0.0)
    spread_return = panel["ZZ500"].pct_change().fillna(0.0) - panel["SZ50"].pct_change().fillna(0.0)
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
    return out.iloc[int(warmup) :].copy()


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def add_pass_flags(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = window_metrics.copy()
    best_by_family = df.groupby("family")["sharpe_repo_full"].transform("max")
    df["family80_pass"] = df["sharpe_repo_full"] >= best_by_family * 0.8
    df["core_pass"] = (
        (df["ann_return_full"] >= 0.055)
        & (df["max_dd_full"] >= -0.38)
        & (df["ann_return_last_5y"] >= 0.07)
        & (df["ann_return_last_1y"] >= 0.10)
    )
    df["defensive_pass"] = (
        (df["ann_return_full"] >= 0.055)
        & (df["max_dd_full"] >= -0.30)
        & (df["ann_return_last_5y"] >= 0.05)
        & (df["ann_return_last_1y"] >= 0.10)
    )
    df["recent_pass"] = (
        (df["ann_return_full"] >= 0.045)
        & (df["ann_return_last_5y"] >= 0.08)
        & (df["ann_return_last_3y"] >= 0.02)
        & (df["ann_return_last_1y"] >= 0.15)
    )
    df["width_score"] = (
        df["sharpe_repo_full"]
        + df["ann_return_last_5y"].clip(lower=-0.05, upper=0.10)
        + df["ann_return_last_1y"].clip(lower=0.0, upper=0.25) * 0.25
        + df["max_dd_full"].clip(lower=-0.45, upper=0.0) * 0.20
        + df["core_pass"].astype(float) * 0.05
        + df["defensive_pass"].astype(float) * 0.05
    )
    return df


def build_local_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = add_pass_flags(window_metrics)
    rows = []
    for family, fam_df in df.groupby("family"):
        min_mom, max_mom = int(fam_df["mom_day"].min()), int(fam_df["mom_day"].max())
        min_weight, max_weight = float(fam_df["weight_end"].min()), float(fam_df["weight_end"].max())
        if family == "bias_momentum":
            min_bias, max_bias = int(fam_df["bias_ma"].min()), int(fam_df["bias_ma"].max())
            seed_pool = pd.concat(
                [
                    fam_df.sort_values("sharpe_repo_full", ascending=False).head(80),
                    fam_df.sort_values("width_score", ascending=False).head(80),
                    fam_df[fam_df["core_pass"]].sort_values("width_score", ascending=False).head(80),
                    fam_df[fam_df["defensive_pass"]].sort_values("width_score", ascending=False).head(80),
                    fam_df[fam_df["recent_pass"]].sort_values("width_score", ascending=False).head(80),
                ],
                ignore_index=True,
            ).drop_duplicates("candidate")
        else:
            min_bias = max_bias = 0
            seed_pool = fam_df.copy()

        for _, row in seed_pool.iterrows():
            nearby = fam_df[
                (fam_df["mom_day"].sub(row["mom_day"]).abs() <= 2)
                & (fam_df["weight_end"].sub(row["weight_end"]).abs() <= 0.5)
            ]
            if family == "bias_momentum":
                nearby = nearby[nearby["bias_ma"].sub(row["bias_ma"]).abs() <= 10]
            core = nearby[nearby["core_pass"]]
            defensive = nearby[nearby["defensive_pass"]]
            recent = nearby[nearby["recent_pass"]]
            family80 = nearby[nearby["family80_pass"]]
            rows.append(
                {
                    "candidate": row["candidate"],
                    "family": family,
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
                    "nearby_family80_count": int(len(family80)),
                    "nearby_core_pass_count": int(len(core)),
                    "nearby_defensive_pass_count": int(len(defensive)),
                    "nearby_recent_pass_count": int(len(recent)),
                    "core_bias_count": int(core["bias_ma"].nunique()) if family == "bias_momentum" else 0,
                    "core_mom_count": int(core["mom_day"].nunique()),
                    "core_weight_count": int(core["weight_end"].nunique()),
                    "defensive_bias_count": int(defensive["bias_ma"].nunique()) if family == "bias_momentum" else 0,
                    "defensive_mom_count": int(defensive["mom_day"].nunique()),
                    "defensive_weight_count": int(defensive["weight_end"].nunique()),
                    "recent_bias_count": int(recent["bias_ma"].nunique()) if family == "bias_momentum" else 0,
                    "recent_mom_count": int(recent["mom_day"].nunique()),
                    "recent_weight_count": int(recent["weight_end"].nunique()),
                    "edge_flag": bool(
                        row["mom_day"] in (min_mom, max_mom)
                        or float(row["weight_end"]) in (min_weight, max_weight)
                        or (family == "bias_momentum" and row["bias_ma"] in (min_bias, max_bias))
                    ),
                    "core_local_patch": bool(
                        len(core) >= (12 if family == "bias_momentum" else 4)
                        and core["mom_day"].nunique() >= 2
                        and core["weight_end"].nunique() >= 2
                        and (family != "bias_momentum" or core["bias_ma"].nunique() >= 2)
                    ),
                    "defensive_local_patch": bool(
                        len(defensive) >= (8 if family == "bias_momentum" else 3)
                        and defensive["mom_day"].nunique() >= 2
                        and defensive["weight_end"].nunique() >= 2
                        and (family != "bias_momentum" or defensive["bias_ma"].nunique() >= 2)
                    ),
                    "recent_local_patch": bool(
                        len(recent) >= (10 if family == "bias_momentum" else 3)
                        and recent["mom_day"].nunique() >= 2
                        and recent["weight_end"].nunique() >= 2
                        and (family != "bias_momentum" or recent["bias_ma"].nunique() >= 2)
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        [
            "core_local_patch",
            "defensive_local_patch",
            "recent_local_patch",
            "nearby_core_pass_count",
            "nearby_defensive_pass_count",
            "nearby_recent_pass_count",
            "width_score",
        ],
        ascending=[False, False, False, False, False, False, False],
    )


def build_axis_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = add_pass_flags(window_metrics)
    rows = []
    for family, fam_df in df.groupby("family"):
        axes = ["mom_day", "weight_end"] if family == "log_wls_momentum" else ["bias_ma", "mom_day", "weight_end"]
        for axis in axes:
            for value, group in fam_df.groupby(axis):
                best = group.sort_values("width_score", ascending=False).iloc[0]
                rows.append(
                    {
                        "family": family,
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
                        "recent_pass_count": int(group["recent_pass"].sum()),
                        "family80_count": int(group["family80_pass"].sum()),
                    }
                )
    return pd.DataFrame(rows)


def window_table(df: pd.DataFrame, n: int = 12) -> str:
    cols = ["candidate", "family", "bias_ma", "mom_day", "weight_end"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def select_carry_candidates(local_width: pd.DataFrame, window_metrics: pd.DataFrame) -> pd.DataFrame:
    lw = local_width[~local_width["edge_flag"]].copy()
    bias = lw[
        (lw["family"] == "bias_momentum")
        & (lw["core_local_patch"] | lw["defensive_local_patch"] | lw["recent_local_patch"])
    ].sort_values(
        ["nearby_core_pass_count", "nearby_defensive_pass_count", "width_score"],
        ascending=[False, False, False],
    )
    log = lw[
        (lw["family"] == "log_wls_momentum")
        & (lw["core_local_patch"] | lw["defensive_local_patch"] | lw["recent_local_patch"])
    ].sort_values(
        ["nearby_core_pass_count", "nearby_defensive_pass_count", "width_score"],
        ascending=[False, False, False],
    )
    carry = pd.concat([bias.head(4), log.head(4)], ignore_index=True).drop_duplicates("candidate")
    if carry.empty:
        carry = lw.sort_values("width_score", ascending=False).head(8)
    metrics_cols = [
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
    return carry.merge(
        window_metrics[metrics_cols],
        on=["candidate", "family", "bias_ma", "mom_day", "weight_end"],
        suffixes=("", "_metric"),
    )


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod = base.load_v77()
    zz500 = mod._load_cn_official_cache(mod.CN_DK_ZZ500_SECID).rename(columns={"close": "ZZ500"})
    sz50 = mod._load_cn_official_cache(mod.CN_DK_SZ50_SECID).rename(columns={"close": "SZ50"})
    panel = pd.concat([zz500["ZZ500"], sz50["SZ50"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["ZZ500"] / panel["SZ50"]

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
        out["family"] = candidate["family"]
        daily_curves.append(out.reset_index(names="date"))

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
        (~local_width["edge_flag"])
        & (local_width["core_local_patch"] | local_width["defensive_local_patch"] | local_width["recent_local_patch"])
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
        "# ZZ500/SZ50 ADK Spread Layer 1 Dense Patch",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer1_dense_complete_not_promoted`",
        "- stability: `width_first_dense_patch_pending_user_confirmation`",
        "",
        "## Research Question",
        "Dense width-first scan around the Layer 0/1 carry list for long ZZ500 / short SZ50.",
        "",
        "## Layer Inputs",
        "- Previous-layer carry list:",
        *[f"  - `{item}`" for item in PREVIOUS_CARRY],
        "- Bias-momentum dense grid: `bias_ma=75..125 step5`, `mom_day=12..28 step2`, `weight_end=0.75..3.25`.",
        "- Log-WLS dense grid: `mom_day=10..25 step1`, `weight_end=0.75..3.25`.",
        "",
        "## Implementation Anchor",
        "- Imports V7.7 local cache loader and metrics from `scan_adk_zz500_sz50_spread_long_only.py`.",
        "- Uses vectorized weighted-slope/R2 calculation matching the Layer 0/1 formula.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research with two-leg commissions, excluding futures basis, financing, borrow, and short locate costs.",
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
        "- Return stream: ZZ500 close-to-close return minus SZ50 close-to-close return.",
        f"- Transaction cost: two legs times one-way commission {base.COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- Target-vol, NAV defense, overheat, amount/volume gates, and momentum decay are off.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 1 dense scan artifact.",
        "",
        "## Commands",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"ZZ500/SZ50 spread Layer 1 dense\" --parameter-group \"bias_log_signal_width_dense_patch\" --repo . --entrypoint \"scan_adk_zz500_sz50_spread_layer1_dense_patch.py\" --date 2026-06-12 --slug \"adk_zz500_sz50_spread_long_only_v77_adk_spread_layer1_dense_patch_width_first\"`",
        "- `python -m py_compile \"scan_adk_zz500_sz50_spread_layer1_dense_patch.py\"`",
        "- `python \"scan_adk_zz500_sz50_spread_layer1_dense_patch.py\"`",
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
        "## Top Full-Sample Results",
        window_table(top_sharpe, 12),
        "",
        "## Width Candidates",
        window_table(width_candidates, 12),
        "",
        "## Next-Layer Carry Candidates",
        window_table(carry, 8),
        "",
        "## Stability Classification",
        local_width.head(30).to_markdown(index=False),
        "",
        "## Decision",
        "Layer 1 dense patch completed but not promoted. Stop for user confirmation before Layer 2 score and absolute-bias filters.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz500_sz50_spread_long_only.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "layer1_dense_patch_width_first",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "bias_log_signal_width_dense_patch",
        "baseline": {
            "direction": "long_ZZ500_short_SZ50",
            "previous_layer_carry": PREVIOUS_CARRY,
            "threshold": 0.0,
        },
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
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
                "ratio": "ZZ500 / SZ50",
                "return_stream": "ZZ500 pct_change - SZ50 pct_change",
            },
        },
        "decision": "layer1_dense_complete_not_promoted",
        "stability_label": "width_first_dense_patch_pending_user_confirmation",
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
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"ZZ500/SZ50 spread Layer 1 dense\" --parameter-group \"bias_log_signal_width_dense_patch\" --repo . --entrypoint \"scan_adk_zz500_sz50_spread_layer1_dense_patch.py\" --date 2026-06-12 --slug \"adk_zz500_sz50_spread_long_only_v77_adk_spread_layer1_dense_patch_width_first\"\n"
        "python -m py_compile \"scan_adk_zz500_sz50_spread_layer1_dense_patch.py\"\n"
        "python \"scan_adk_zz500_sz50_spread_layer1_dense_patch.py\"\n"
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
                "family",
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
                "family",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "nearby_core_pass_count",
                "nearby_defensive_pass_count",
                "nearby_recent_pass_count",
                "core_local_patch",
                "defensive_local_patch",
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
                "family",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "ann_return_last_5y",
                "max_dd_last_5y",
                "ann_return_last_1y",
                "max_dd_last_1y",
                "nearby_core_pass_count",
                "nearby_defensive_pass_count",
            ]
        ]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()

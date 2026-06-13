"""Layer 1 dense patch for ADK-style long ZZ500 / short HS300 spread.

This layer follows the width-first rule from the Layer 0/1 result:
- primary dense branch around the width-supported log-WLS mom20/we2 ridge.
- watchlist dense branch around the thinner headline bias_ma120/mom20/we3 point.

Target-vol, NAV defense, overheat, amount/volume, and momentum decay are off.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_hs300_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_hs300_spread_long_only_v77_adk_spread_layer1_dense_patch_width_supported_secondary"
WEIGHT_GRID = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 4.0]
PREVIOUS_HEADLINE_MAX = "bias_ma120_mom020_we3p0_gt0"
PREVIOUS_WIDTH_SUPPORTED = "log_wls_mom020_we2p0_gt0"


def dense_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for mom_day in range(12, 29):
        for weight_end in WEIGHT_GRID:
            grid.append(
                {
                    "candidate": f"dense_log_wls_mom{mom_day:03d}_we{str(weight_end).replace('.', 'p')}_gt0",
                    "family": "log_wls_momentum",
                    "branch": "width_supported_primary",
                    "bias_ma": 0,
                    "mom_day": mom_day,
                    "weight_end": weight_end,
                    "threshold": 0.0,
                }
            )
    for bias_ma in range(90, 151, 10):
        for mom_day in range(14, 27, 2):
            for weight_end in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
                grid.append(
                    {
                        "candidate": f"dense_bias_ma{bias_ma:03d}_mom{mom_day:03d}_we{str(weight_end).replace('.', 'p')}_gt0",
                        "family": "bias_momentum",
                        "branch": "headline_max_watchlist",
                        "bias_ma": bias_ma,
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
    weight_end = float(candidate["weight_end"])
    mom_day = int(candidate["mom_day"])

    if family == "bias_momentum":
        bias_ma = int(candidate["bias_ma"])
        feature = ratio / ratio.rolling(bias_ma).mean() - 1.0
        warmup = max(bias_ma, mom_day) + 2
    elif family == "log_wls_momentum":
        feature = np.log(ratio)
        warmup = mom_day + 2
    else:
        raise ValueError(f"unsupported family: {family}")

    score, r2 = fast_weighted_slope_and_r2(feature, mom_day, weight_end)
    raw_signal = ((score > threshold) & (r2 >= 0.05)).astype(float)
    exec_weight = raw_signal.shift(1).fillna(0.0)
    spread_return = panel["ZZ500"].pct_change().fillna(0.0) - panel["HS300"].pct_change().fillna(0.0)
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
    return out.iloc[int(warmup) :].copy()


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def add_pass_flags(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = window_metrics.copy()
    best_by_family = df.groupby("family")["sharpe_repo_full"].transform("max")
    df["family80_pass"] = df["sharpe_repo_full"] >= best_by_family * 0.8
    df["core_pass"] = (
        (df["ann_return_full"] >= 0.05)
        & (df["max_dd_full"] >= -0.22)
        & (df["ann_return_last_5y"] >= 0.035)
        & (df["ann_return_last_1y"] >= 0.075)
    )
    df["recent_pass"] = (
        (df["ann_return_full"] >= 0.04)
        & (df["max_dd_full"] >= -0.25)
        & (df["ann_return_last_5y"] >= 0.05)
        & (df["ann_return_last_1y"] >= 0.10)
    )
    df["defensive_pass"] = (
        (df["ann_return_full"] >= 0.04)
        & (df["max_dd_full"] >= -0.18)
        & (df["ann_return_last_5y"] >= 0.03)
    )
    df["width_score"] = (
        df["sharpe_repo_full"]
        + df["ann_return_last_5y"].clip(lower=-0.05, upper=0.08)
        + df["ann_return_last_1y"].clip(lower=0.0, upper=0.18) * 0.25
        + df["max_dd_full"].clip(lower=-0.35, upper=0.0) * 0.15
        + df["core_pass"].astype(float) * 0.05
        + df["recent_pass"].astype(float) * 0.04
        + df["defensive_pass"].astype(float) * 0.03
    )
    return df


def build_local_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = add_pass_flags(window_metrics)
    rows = []
    for family, fam_df in df.groupby("family"):
        min_mom, max_mom = int(fam_df["mom_day"].min()), int(fam_df["mom_day"].max())
        min_weight, max_weight = float(fam_df["weight_end"].min()), float(fam_df["weight_end"].max())
        min_bias = int(fam_df["bias_ma"].min()) if family == "bias_momentum" else 0
        max_bias = int(fam_df["bias_ma"].max()) if family == "bias_momentum" else 0
        seeds = pd.concat(
            [
                fam_df.sort_values("sharpe_repo_full", ascending=False).head(60),
                fam_df.sort_values("width_score", ascending=False).head(60),
                fam_df[fam_df["core_pass"]].sort_values("width_score", ascending=False).head(60),
                fam_df[fam_df["recent_pass"]].sort_values("width_score", ascending=False).head(60),
                fam_df[fam_df["defensive_pass"]].sort_values("width_score", ascending=False).head(60),
            ],
            ignore_index=True,
        ).drop_duplicates("candidate")
        for _, row in seeds.iterrows():
            nearby = fam_df[
                (fam_df["mom_day"].sub(row["mom_day"]).abs() <= 2)
                & (fam_df["weight_end"].sub(row["weight_end"]).abs() <= 0.5)
            ]
            if family == "bias_momentum":
                nearby = nearby[nearby["bias_ma"].sub(row["bias_ma"]).abs() <= 10]
            family80 = nearby[nearby["family80_pass"]]
            core = nearby[nearby["core_pass"]]
            recent = nearby[nearby["recent_pass"]]
            defensive = nearby[nearby["defensive_pass"]]
            is_edge = bool(
                row["mom_day"] in (min_mom, max_mom)
                or float(row["weight_end"]) in (min_weight, max_weight)
                or (family == "bias_momentum" and row["bias_ma"] in (min_bias, max_bias))
            )
            family80_patch = bool(
                len(family80) >= (4 if family == "log_wls_momentum" else 8)
                and family80["mom_day"].nunique() >= 2
                and family80["weight_end"].nunique() >= 2
                and (family != "bias_momentum" or family80["bias_ma"].nunique() >= 2)
            )
            practical_patch = bool(
                (len(core) + len(recent) + len(defensive)) >= (6 if family == "log_wls_momentum" else 10)
                and pd.concat([core, recent, defensive])["mom_day"].nunique() >= 2
                and pd.concat([core, recent, defensive])["weight_end"].nunique() >= 2
                and (family != "bias_momentum" or pd.concat([core, recent, defensive])["bias_ma"].nunique() >= 2)
            )
            rows.append(
                {
                    "candidate": row["candidate"],
                    "family": family,
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
                    "width_score": float(row["width_score"]),
                    "nearby_count": int(len(nearby)),
                    "nearby_family80_count": int(len(family80)),
                    "nearby_core_pass_count": int(len(core)),
                    "nearby_recent_pass_count": int(len(recent)),
                    "nearby_defensive_pass_count": int(len(defensive)),
                    "edge_flag": is_edge,
                    "family80_local_patch": family80_patch,
                    "practical_local_patch": practical_patch,
                    "width_supported": bool((family80_patch or practical_patch) and not is_edge),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["width_supported", "family80_local_patch", "practical_local_patch", "nearby_family80_count", "width_score"],
        ascending=[False, False, False, False, False],
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
                        "best_full_ann_return": float(best["ann_return_full"]),
                        "best_full_max_dd": float(best["max_dd_full"]),
                        "family80_count": int(group["family80_pass"].sum()),
                        "core_pass_count": int(group["core_pass"].sum()),
                        "recent_pass_count": int(group["recent_pass"].sum()),
                        "defensive_pass_count": int(group["defensive_pass"].sum()),
                    }
                )
    return pd.DataFrame(rows)


def window_table(df: pd.DataFrame, n: int = 12) -> str:
    cols = ["candidate", "family", "branch", "bias_ma", "mom_day", "weight_end"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def select_carry_candidates(local_width: pd.DataFrame, window_metrics: pd.DataFrame) -> pd.DataFrame:
    supported = local_width[local_width["width_supported"]].copy()
    primary = supported[supported["branch"] == "width_supported_primary"].head(4)
    watch = local_width[
        (local_width["branch"] == "headline_max_watchlist")
        & (~local_width["edge_flag"])
    ].sort_values(["width_supported", "sharpe_repo_full", "width_score"], ascending=[False, False, False]).head(4)
    carry = pd.concat([primary, watch], ignore_index=True).drop_duplicates("candidate")
    if carry.empty:
        carry = local_width.sort_values("width_score", ascending=False).head(8)
    metrics_cols = [
        "candidate",
        "family",
        "branch",
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
        on=["candidate", "family", "branch", "bias_ma", "mom_day", "weight_end"],
        suffixes=("", "_metric"),
    )


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod = base.load_v77()
    zz500 = mod._load_cn_official_cache(mod.CN_DK_ZZ500_SECID).rename(columns={"close": "ZZ500"})
    hs300 = mod._load_cn_official_cache(mod.CN_DK_HS300_SECID).rename(columns={"close": "HS300"})
    panel = pd.concat([zz500["ZZ500"], hs300["HS300"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["ZZ500"] / panel["HS300"]

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
    carry = select_carry_candidates(local_width, window_metrics)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    local_width.to_csv(RUN_DIR / "local_width.csv", index=False, encoding="utf-8-sig")
    width_candidates.to_csv(RUN_DIR / "width_candidates.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# ZZ500/HS300 ADK Spread Layer 1 Dense Patch",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer1_dense_complete_not_promoted`",
        "- stability: `width_supported_secondary_found_pending_user_confirmation`",
        "",
        "## Research Question",
        "Dense Layer 1 width scan for long ZZ500 / short HS300 after Layer 0/1 found a thin headline maximum and a width-supported log-WLS secondary ridge.",
        "",
        "## Layer Inputs",
        f"- Headline maximum watchlist from Layer 0/1: `{PREVIOUS_HEADLINE_MAX}`.",
        f"- Width-supported primary from Layer 0/1: `{PREVIOUS_WIDTH_SUPPORTED}`.",
        "- Log-WLS dense grid: `mom_day=12..28 step1`, `weight_end=0.75..4.0`.",
        "- Bias-momentum watchlist grid: `bias_ma=90..150 step10`, `mom_day=14..26 step2`, `weight_end=1.0..4.0`.",
        "",
        "## Implementation Anchor",
        "- Imports V7.7 local cache loader and metrics from `scan_adk_zz500_hs300_spread_long_only.py`.",
        "- Uses vectorized weighted-slope/R2 calculation matching the Layer 0/1 formula.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research with two-leg commissions, excluding futures basis, financing, borrow, and short locate costs.",
        "- Source-change rule: `research_only_new_scan_script`.",
        "",
        "## Data Snapshot",
        f"- HS300 publication date: {base.HS300_PUBLICATION_DATE}; local rows: {len(hs300)}, start {hs300.index.min().date()}, end {hs300.index.max().date()}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start rule: latest actual index publication date among the two legs.",
        "- Adjustment mode: price index close from local official cache, no total-return substitution.",
        "",
        "## Cost and Execution Assumptions",
        "- Market: A-share index spread research using daily close data.",
        "- Trading calendar: aligned index dates from the two local cache series.",
        "- Timing: T close signal -> T+1 close-to-close spread return.",
        "- Return stream: ZZ500 close-to-close return minus HS300 close-to-close return.",
        f"- Transaction cost: two legs times one-way commission {base.COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- Target-vol, NAV defense, overheat, amount/volume gates, and momentum decay are off.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 1 dense scan artifact.",
        "",
        "## Commands",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"ZZ500/HS300 spread Layer 1 dense\" --parameter-group \"width_supported_secondary_dense_patch\" --repo . --entrypoint \"scan_adk_zz500_hs300_spread_layer1_dense_patch.py\" --date 2026-06-12 --slug \"adk_zz500_hs300_spread_long_only_v77_adk_spread_layer1_dense_patch_width_supported_secondary\"`",
        "- `python -m py_compile \"scan_adk_zz500_hs300_spread_layer1_dense_patch.py\"`",
        "- `python \"scan_adk_zz500_hs300_spread_layer1_dense_patch.py\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py <run_folder> --decision \"layer1_dense_complete_not_promoted\" --stability-label \"width_supported_secondary_found_pending_user_confirmation\"`",
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
        "subsystem": "ZZ500/HS300 spread Layer 1 dense",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz500_hs300_spread_long_only.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "layer1_dense_patch_width_supported_secondary",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "width_supported_secondary_dense_patch",
        "baseline": {
            "direction": "long_ZZ500_short_HS300",
            "previous_headline_max": PREVIOUS_HEADLINE_MAX,
            "previous_width_supported": PREVIOUS_WIDTH_SUPPORTED,
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
            "hs300": {
                "secid": str(mod.CN_DK_HS300_SECID),
                "publication_date": base.HS300_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_HS300_SECID))),
                "rows": int(len(hs300)),
                "start": str(hs300.index.min().date()),
                "end": str(hs300.index.max().date()),
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
                "ratio": "ZZ500 / HS300",
                "return_stream": "ZZ500 pct_change - HS300 pct_change",
            },
        },
        "decision": "layer1_dense_complete_not_promoted",
        "stability_label": "width_supported_secondary_found_pending_user_confirmation",
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
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"ZZ500/HS300 spread Layer 1 dense\" --parameter-group \"width_supported_secondary_dense_patch\" --repo . --entrypoint \"scan_adk_zz500_hs300_spread_layer1_dense_patch.py\" --date 2026-06-12 --slug \"adk_zz500_hs300_spread_long_only_v77_adk_spread_layer1_dense_patch_width_supported_secondary\"\n"
        "python -m py_compile \"scan_adk_zz500_hs300_spread_layer1_dense_patch.py\"\n"
        "python \"scan_adk_zz500_hs300_spread_layer1_dense_patch.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"layer1_dense_complete_not_promoted\" --stability-label \"width_supported_secondary_found_pending_user_confirmation\"\n"
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
                "branch",
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
                "branch",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "nearby_family80_count",
                "nearby_core_pass_count",
                "nearby_recent_pass_count",
                "nearby_defensive_pass_count",
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
                "branch",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "ann_return_last_5y",
                "max_dd_last_5y",
                "ann_return_last_1y",
                "max_dd_last_1y",
                "nearby_family80_count",
                "nearby_core_pass_count",
            ]
        ]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()

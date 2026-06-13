"""Layer 10 volume filter for long ZZ500 / short HS300.

Layer 9 promoted width-supported amount filters, so this layer uses those
Layer 9 carry lines as the baseline and tests volume filters as an incremental
overlay. Prices remain local official close cache; volume uses the V7.7
EastMoney fallback and is therefore quasi-formal.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_hs300_spread_layer9_amount as l9


RUN_DIR = l9.base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_hs300_spread_long_only_v77_adk_spread_layer10_volume_after_l9_amount"

LINES = [
    {
        **l9.LINES[0],
        "layer9_candidate": "l9amt_main_confirm_zz500_amount_low_w120_thr0p75_d1_scale0p25",
        "amount_feature": "zz500_amount_low",
        "amount_window": 120,
        "amount_threshold": 0.75,
        "amount_confirm_days": 1,
        "amount_scale": 0.25,
    },
    {
        **l9.LINES[1],
        "layer9_candidate": "l9amt_return_preserve_zz500_amount_low_w20_thr1_d3_scale0p25",
        "amount_feature": "zz500_amount_low",
        "amount_window": 20,
        "amount_threshold": 1.00,
        "amount_confirm_days": 3,
        "amount_scale": 0.25,
    },
    {
        **l9.LINES[2],
        "layer9_candidate": "l9amt_primary_dd_zz500_amount_low_w120_thr0p75_d1_scale0",
        "amount_feature": "zz500_amount_low",
        "amount_window": 120,
        "amount_threshold": 0.75,
        "amount_confirm_days": 1,
        "amount_scale": 0.00,
    },
    {
        **l9.LINES[3],
        "layer9_candidate": "l9amt_ultra_def_zz500_amount_low_w40_thr0p85_d1_scale0p25",
        "amount_feature": "zz500_amount_low",
        "amount_window": 40,
        "amount_threshold": 0.85,
        "amount_confirm_days": 1,
        "amount_scale": 0.25,
    },
]

VOLUME_WINDOWS = [20, 40, 60, 80, 120]
HIGH_THRESHOLDS = [1.25, 1.50, 1.75, 2.00]
LOW_THRESHOLDS = [0.75, 0.85, 1.00]
CONFIRM_DAYS = [1, 3, 5]
VOLUME_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0, 3.0]
WINDOW_SEGMENTS = ["full", "last_10y", "last_5y", "last_3y", "last_1y"]


def volume_feature(source_panel: pd.DataFrame, feature: str, window: int) -> pd.Series:
    hs300_rel = source_panel["HS300_volume"] / source_panel["HS300_volume"].rolling(window).mean()
    zz500_rel = source_panel["ZZ500_volume"] / source_panel["ZZ500_volume"].rolling(window).mean()
    pair_rel = zz500_rel / hs300_rel
    if feature in {"hs300_volume_high", "hs300_volume_low"}:
        return hs300_rel
    if feature in {"zz500_volume_high", "zz500_volume_low"}:
        return zz500_rel
    if feature in {"pair_volume_high", "pair_volume_low"}:
        return pair_rel
    raise ValueError(feature)


def layer9_base_returns(
    panel: pd.DataFrame,
    source_panel: pd.DataFrame,
    line: dict[str, object],
    scores: dict[str, pd.Series],
    r2s: dict[str, pd.Series],
    abs_bias: dict[int, pd.Series],
) -> pd.DataFrame:
    layer7 = l9.layer7_base_returns(panel, line, scores, r2s, abs_bias)
    d = l9.apply_amount_overlay(
        layer7,
        source_panel,
        str(line["amount_feature"]),
        int(line["amount_window"]),
        float(line["amount_threshold"]),
        int(line["amount_confirm_days"]),
        float(line["amount_scale"]),
    )
    d["layer9_weight"] = d["weight"]
    return d


def apply_volume_overlay(
    base_df: pd.DataFrame,
    source_panel: pd.DataFrame,
    feature: str | None,
    window: int | None,
    threshold: float | None,
    confirm_days: int | None,
    scale: float | None,
) -> pd.DataFrame:
    d = base_df.copy()
    if feature is None:
        indicator = pd.Series(np.nan, index=d.index)
        on = pd.Series(False, index=d.index)
        mult = pd.Series(1.0, index=d.index)
    else:
        indicator = volume_feature(source_panel, str(feature), int(window)).reindex(d.index)
        raw = indicator >= float(threshold) if str(feature).endswith("high") else indicator <= float(threshold)
        on = l9.confirmed_trigger(raw, int(confirm_days)).shift(1, fill_value=False).astype(bool)
        mult = pd.Series(1.0, index=d.index)
        mult.loc[on] = float(scale)

    final_weight = d["layer9_weight"] * mult
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * l9.base.COMMISSION_ONE_WAY)
    gross_return = final_weight * d["spread_return"].fillna(0.0)
    ret = gross_return - cost
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "layer9_weight": d["layer9_weight"],
            "volume_mult": mult,
            "volume_on": on.astype(int),
            "volume_indicator": indicator,
            "amount_on": d["amount_on"],
            "amount_mult": d["amount_mult"],
            "overlay_on": d["overlay_on"],
            "overlay_mult": d["overlay_mult"],
            "score": d["score"],
            "spread_return": d["spread_return"],
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    features = [
        "hs300_volume_high",
        "hs300_volume_low",
        "zz500_volume_high",
        "zz500_volume_low",
        "pair_volume_high",
        "pair_volume_low",
    ]
    for line in LINES:
        rows.append(
            {
                **line,
                "candidate": f"l10vol_{line['line']}_volume_off",
                "volume_feature": "off",
                "volume_window": 0,
                "volume_threshold": 0.0,
                "volume_confirm_days": 0,
                "volume_scale": 1.0,
                "volume_enabled": False,
            }
        )
        for feature in features:
            thresholds = HIGH_THRESHOLDS if feature.endswith("high") else LOW_THRESHOLDS
            for window in VOLUME_WINDOWS:
                for threshold in thresholds:
                    for days in CONFIRM_DAYS:
                        for scale in VOLUME_SCALES:
                            rows.append(
                                {
                                    **line,
                                    "candidate": (
                                        f"l10vol_{line['line']}_{feature}"
                                        f"_w{window}_thr{l9.fmt_num(threshold)}_d{days}_scale{l9.fmt_num(scale)}"
                                    ),
                                    "volume_feature": feature,
                                    "volume_window": window,
                                    "volume_threshold": threshold,
                                    "volume_confirm_days": days,
                                    "volume_scale": scale,
                                    "volume_enabled": True,
                                }
                            )
    return rows


def run_candidate(cand: dict[str, object], base_by_line: dict[str, pd.DataFrame], source_panel: pd.DataFrame) -> pd.DataFrame:
    return apply_volume_overlay(
        base_by_line[str(cand["line"])],
        source_panel,
        None if not cand["volume_enabled"] else str(cand["volume_feature"]),
        None if not cand["volume_enabled"] else int(cand["volume_window"]),
        None if not cand["volume_enabled"] else float(cand["volume_threshold"]),
        None if not cand["volume_enabled"] else int(cand["volume_confirm_days"]),
        None if not cand["volume_enabled"] else float(cand["volume_scale"]),
    )


def extra_metrics_for_segment(result: pd.DataFrame, years: int | None) -> dict[str, float]:
    if years is None:
        d = result.copy()
    else:
        cutoff = result.index.max() - pd.DateOffset(years=years)
        d = result.loc[result.index >= cutoff].copy()
    if d.empty:
        return {"volume_days": 0.0, "volume_day_ratio": 0.0, "amount_volume_overlap_days": 0.0}
    return {
        "volume_days": float(d["volume_on"].sum()),
        "volume_day_ratio": float(d["volume_on"].mean()),
        "amount_volume_overlap_days": float(((d["amount_on"] > 0) & (d["volume_on"] > 0)).sum()),
    }


def add_baselines_and_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["volume_enabled"] == False].set_index("line")
    for col in [
        "ann_return_full",
        "max_dd_full",
        "ann_return_last_10y",
        "max_dd_last_10y",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "ann_return_last_3y",
        "max_dd_last_3y",
        "ann_return_last_1y",
        "max_dd_last_1y",
        "cost_total_full",
        "avg_turnover_full",
    ]:
        out[f"base_{col}"] = out["line"].map(base_rows[col])
    for segment in WINDOW_SEGMENTS:
        out[f"{segment}_ann_loss_pp"] = (out[f"base_ann_return_{segment}"] - out[f"ann_return_{segment}"]) * 100.0
        out[f"{segment}_dd_improve_pp"] = (out[f"max_dd_{segment}"] - out[f"base_max_dd_{segment}"]) * 100.0
    out["cost_delta_full"] = out["cost_total_full"] - out["base_cost_total_full"]
    out["turnover_delta_full"] = out["avg_turnover_full"] - out["base_avg_turnover_full"]
    active_volume = out["volume_days_full"] > 0
    out["pass_full_ann_dd"] = (
        (out["volume_enabled"] == True)
        & active_volume
        & (out["ann_return_full"] >= out["base_ann_return_full"] - 1e-12)
        & (out["max_dd_full"] >= out["base_max_dd_full"] - 1e-12)
    )
    out["pass_full_5y_ann_dd"] = (
        out["pass_full_ann_dd"]
        & (out["ann_return_last_5y"] >= out["base_ann_return_last_5y"] - 1e-12)
        & (out["max_dd_last_5y"] >= out["base_max_dd_last_5y"] - 1e-12)
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            (out["volume_enabled"] == True)
            & active_volume
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["last_5y_dd_improve_pp"] >= -1e-12)
        )
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    pass_cols = ["pass_full_ann_dd", "pass_full_5y_ann_dd"] + [
        f"pass_loss_le_{str(tier).replace('.', 'p')}pp" for tier in LOSS_TIERS
    ]
    source = wm[wm["volume_enabled"] == True]
    for pass_col in pass_cols:
        for (line, feature), group in source.groupby(["line", "volume_feature"]):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": pass_col,
                        "line": line,
                        "volume_feature": feature,
                        "pass_count": 0,
                        "window_count": 0,
                        "threshold_count": 0,
                        "day_count": 0,
                        "scale_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "best_volume_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(
                len(passed) >= 4
                and passed["volume_window"].nunique() >= 2
                and passed["volume_threshold"].nunique() >= 2
            )
            rows.append(
                {
                    "pass_rule": pass_col,
                    "line": line,
                    "volume_feature": feature,
                    "pass_count": int(len(passed)),
                    "window_count": int(passed["volume_window"].nunique()),
                    "threshold_count": int(passed["volume_threshold"].nunique()),
                    "day_count": int(passed["volume_confirm_days"].nunique()),
                    "scale_count": int(passed["volume_scale"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "best_full_ann_loss_pp": float(best["full_ann_loss_pp"]),
                    "best_full_dd_improve_pp": float(best["full_dd_improve_pp"]),
                    "best_5y_ann_return": float(best["ann_return_last_5y"]),
                    "best_5y_max_dd": float(best["max_dd_last_5y"]),
                    "best_volume_days": float(best["volume_days_full"]),
                    "patch_like": patch_like,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["pass_rule", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def state_overlap_summary(daily_all: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for candidate, d in daily_all.groupby("candidate"):
        amount_on = d["amount_on"].astype(float) > 0
        volume_on = d["volume_on"].astype(float) > 0
        masks = {
            "amount0_volume0": ~amount_on & ~volume_on,
            "amount1_volume0": amount_on & ~volume_on,
            "amount0_volume1": ~amount_on & volume_on,
            "amount1_volume1": amount_on & volume_on,
        }
        for label, mask in masks.items():
            part = d.loc[mask]
            rows.append(
                {
                    "candidate": candidate,
                    "state": label,
                    "days": int(mask.sum()),
                    "avg_weight": float(part["weight"].mean()) if not part.empty else np.nan,
                    "net_return_sum": float(part["return"].sum()) if not part.empty else 0.0,
                    "cost_sum": float(part["cost"].sum()) if not part.empty else 0.0,
                }
            )
    return pd.DataFrame(rows)


def comparison_table(df: pd.DataFrame, n: int = 12) -> str:
    cols = [
        "candidate",
        "line",
        "volume_feature",
        "volume_window",
        "volume_threshold",
        "volume_confirm_days",
        "volume_scale",
        "volume_days_full",
    ]
    for segment in WINDOW_SEGMENTS:
        cols.extend(
            [
                f"base_ann_return_{segment}",
                f"base_max_dd_{segment}",
                f"ann_return_{segment}",
                f"max_dd_{segment}",
                f"{segment}_ann_loss_pp",
                f"{segment}_dd_improve_pp",
            ]
        )
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith(("ann_return_", "max_dd_", "base_ann_return_", "base_max_dd_")):
            display[col] = display[col].map(lambda x: l9.pct(float(x)))
        elif col.endswith("_ann_loss_pp"):
            display[col] = display[col].map(lambda x: f"{-float(x):+.2f}pp")
        elif col.endswith("_dd_improve_pp"):
            display[col] = display[col].map(lambda x: f"{float(x):+.2f}pp")
    return display.to_markdown(index=False)


def select_carry(window_metrics: pd.DataFrame, strict_pass: pd.DataFrame, ridge: pd.DataFrame) -> tuple[pd.DataFrame, str, str]:
    width_supported = ridge[
        (ridge["pass_rule"] == "pass_full_5y_ann_dd")
        & (ridge["patch_like"] == True)
        & (ridge["pass_count"] > 0)
    ]
    if not strict_pass.empty and not width_supported.empty:
        carry = (
            strict_pass.sort_values(
                ["line", "full_dd_improve_pp", "last_5y_dd_improve_pp", "ann_return_full"],
                ascending=[True, False, False, False],
            )
            .groupby("line")
            .head(1)
        )
        return carry, "layer10_volume_complete_promoted_width_supported_volume", "volume_width_supported_full_5y_nonunderperformance"
    carry = window_metrics[window_metrics["volume_enabled"] == False].copy()
    return carry, "layer10_volume_complete_not_promoted_carry_layer9_amount", "volume_filter_rejected_carry_layer9_amount"


def main() -> None:
    git_status_before = l9.base.git_text(["status", "--short"])
    mod, zz500, hs300, panel = l9.l2.load_panel()
    scores, r2s, abs_bias = l9.l2.precompute(panel)
    source_panel, source_meta = l9.fetch_amount_panel(mod)
    source_panel = source_panel.reindex(panel.index)
    complete_volume_rows = source_panel[["HS300_volume", "ZZ500_volume"]].apply(pd.to_numeric, errors="coerce").dropna()
    base_by_line = {
        str(line["line"]): layer9_base_returns(panel, source_panel, line, scores, r2s, abs_bias)
        for line in LINES
    }
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    grid = make_grid()
    grid_by_candidate = {str(c["candidate"]): c for c in grid}
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []

    for cand in grid:
        result = run_candidate(cand, base_by_line, source_panel)
        wide = {**cand}
        wide["volume_complete_rows_full"] = int(len(complete_volume_rows))
        for segment, years in l9.base.SEGMENTS:
            metrics = l9.base.metrics_for_segment(result, segment, years)
            extras = extra_metrics_for_segment(result, years)
            long_rows.append({**cand, **metrics, **extras})
            for key in [
                "ann_return",
                "ann_vol",
                "max_dd",
                "sharpe_repo",
                "avg_weight",
                "avg_turnover",
                "holding_day_ratio",
                "cost_total",
                "volume_days",
                "volume_day_ratio",
                "amount_volume_overlap_days",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    full_pass = window_metrics[(window_metrics["volume_enabled"] == True) & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[(window_metrics["volume_enabled"] == True) & window_metrics["pass_full_5y_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    loss_passes: dict[float, pd.DataFrame] = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(
            ["line", "full_dd_improve_pp", "ann_return_full"], ascending=[True, False, False]
        )
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        loss_passes[tier] = passed

    carry, decision, stability_label = select_carry(window_metrics, strict_pass, ridge)
    diagnostic = loss_passes[1.0].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).groupby("line").head(1)

    keep_candidates = set(window_metrics.loc[window_metrics["volume_enabled"] == False, "candidate"].astype(str))
    keep_candidates.update(carry["candidate"].astype(str).tolist())
    keep_candidates.update(diagnostic["candidate"].astype(str).tolist())
    keep_candidates.update(strict_pass.head(80)["candidate"].astype(str).tolist())
    keep_candidates.update(full_pass.head(80)["candidate"].astype(str).tolist())
    for passed in loss_passes.values():
        keep_candidates.update(passed.head(40)["candidate"].astype(str).tolist())
    daily_parts = []
    for candidate in sorted(keep_candidates):
        cand = grid_by_candidate[candidate]
        result = run_candidate(cand, base_by_line, source_panel)
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["line"] = cand["line"]
        daily["volume_feature"] = cand["volume_feature"]
        daily_parts.append(daily.reset_index(names="date"))
    daily_all = pd.concat(daily_parts, ignore_index=True)
    overlap = state_overlap_summary(daily_all)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    overlap.to_csv(RUN_DIR / "state_overlap_summary.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# ZZ500/HS300 Layer 10 Volume Filter",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        f"- decision: `{decision}`",
        f"- stability: `{stability_label}`",
        "",
        "## Research Question",
        "Test volume relative-MA filters after promoted Layer 9 amount filters, using Layer 9 carry lines as baseline.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
        "",
        "## Data Snapshot",
        f"- HS300 publication date: {l9.base.HS300_PUBLICATION_DATE}; local rows: {len(hs300)}, start {hs300.index.min().date()}, end {hs300.index.max().date()}.",
        f"- ZZ500 publication date: {l9.base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Formal aligned price rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        f"- Volume source HS300: {source_meta['HS300_source']}; rows {source_meta['HS300_rows']}, {source_meta['HS300_start']} -> {source_meta['HS300_end']}.",
        f"- Volume source ZZ500: {source_meta['ZZ500_source']}; rows {source_meta['ZZ500_rows']}, {source_meta['ZZ500_start']} -> {source_meta['ZZ500_end']}.",
        f"- Complete volume rows on formal price dates: {len(complete_volume_rows)}, start {complete_volume_rows.index.min().date()}, end {complete_volume_rows.index.max().date()}.",
        f"- Unit normalization: {source_meta['unit_note']}",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long ZZ500 / short HS300; ratio is ZZ500/HS300; spread return is ZZ500 pct_change minus HS300 pct_change.",
        "- T close volume state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {l9.base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Volume features use own-MA relative values or pair-relative ratios; pair volume is ZZ500 relative volume / HS300 relative volume.",
        "- Layer 7 volhot and Layer 9 amount remain active as the baseline.",
        "- Result status: quasi-formal, because volume data comes from V7.7 external fallback while prices use close-only official cache.",
        "",
        "## Volume Grid",
        f"- windows: {VOLUME_WINDOWS}",
        f"- high thresholds: {HIGH_THRESHOLDS}",
        f"- low thresholds: {LOW_THRESHOLDS}",
        f"- confirm days: {CONFIRM_DAYS}",
        f"- scales: {VOLUME_SCALES}",
        "",
        "## Baselines",
        comparison_table(window_metrics[window_metrics["volume_enabled"] == False], len(LINES)),
        "",
        "## Full+5Y Non-Underperformance Candidates",
        comparison_table(strict_pass, 20) if not strict_pass.empty else "No volume candidate passed full+5Y non-underperformance.",
        "",
        "## DD-First Candidates Loss <= 1pp",
        comparison_table(loss_passes[1.0], 20) if not loss_passes[1.0].empty else "No volume candidate passed loss<=1pp with DD improvement.",
        "",
        "## Width Summary",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        f"Layer 10 completed with decision `{decision}`. If not promoted, next layer continues from Layer 9 amount carry lines.",
        "",
        "## User-Facing Summary",
        f"- candidates_scanned: {len(grid)}",
        f"- full_baseline_pass_count: {len(full_pass)}",
        f"- full_and_5y_pass_count: {len(strict_pass)}",
        f"- loss_le_0p5pp_pass_count: {len(loss_passes[0.5])}",
        f"- loss_le_1pp_pass_count: {len(loss_passes[1.0])}",
        f"- loss_le_2pp_pass_count: {len(loss_passes[2.0])}",
        f"- loss_le_3pp_pass_count: {len(loss_passes[3.0])}",
        "",
        "## Next-Layer Carry Candidates",
        comparison_table(carry, 10) if not carry.empty else "No carry candidate selected.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    git_status_after = l9.base.git_text(["status", "--short"])
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "ZZ500/HS300 spread Layer 10 volume",
        "repo_root": str(l9.base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz500_hs300_spread_layer9_amount.py",
        "git_branch": l9.base.git_text(["branch", "--show-current"]),
        "git_commit": l9.base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": git_status_after,
        "scan_type": "fresh_layer10_volume_after_l9_amount",
        "formal_status": "quasi_formal_price_index_close_to_close_with_eastmoney_volume",
        "parameter_group": "volume_relative_ma_filter_after_layer9_amount",
        "baseline": {"inputs": LINES, "pass_rule": "compare every volume candidate with same-line volume_off Layer 9 amount baseline"},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": l9.base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close volume state -> T+1 close-to-close return",
            "direction": "long ZZ500 / short HS300",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "data_snapshot": {
            "price_source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "volume_source": source_meta,
            "formal_price": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "aligned_volume": {
                "rows": int(len(complete_volume_rows)),
                "start": str(complete_volume_rows.index.min().date()),
                "end": str(complete_volume_rows.index.max().date()),
            },
            "publication_dates": {"HS300": l9.base.HS300_PUBLICATION_DATE, "ZZ500": l9.base.ZZ500_PUBLICATION_DATE},
            "ratio": "ZZ500 / HS300",
            "return_stream": "ZZ500 pct_change - HS300 pct_change",
            "pair_volume_feature": "ZZ500 volume relative-to-MA / HS300 volume relative-to-MA",
        },
        "volume_implementation": "prior-row volume feature trigger; final exposure multiplier and turnover/cost recomputed",
        "decision": decision,
        "stability_label": stability_label,
        "daily_curve_scope": "baselines plus carry/top strict/full/loss candidates, not all grid candidates",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "state_overlap_summary": str(RUN_DIR / "state_overlap_summary.csv"),
            "full_baseline_pass_candidates": str(RUN_DIR / "full_baseline_pass_candidates.csv"),
            "full_and_5y_pass_candidates": str(RUN_DIR / "full_and_5y_pass_candidates.csv"),
            "dd_first_pass_loss_le_0p5pp": str(RUN_DIR / "dd_first_pass_loss_le_0p5pp.csv"),
            "dd_first_pass_loss_le_1p0pp": str(RUN_DIR / "dd_first_pass_loss_le_1p0pp.csv"),
            "dd_first_pass_loss_le_2p0pp": str(RUN_DIR / "dd_first_pass_loss_le_2p0pp.csv"),
            "dd_first_pass_loss_le_3p0pp": str(RUN_DIR / "dd_first_pass_loss_le_3p0pp.csv"),
            "carry_candidates": str(RUN_DIR / "carry_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "\n".join(
            [
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "ZZ500/HS300 spread Layer 10 volume" --parameter-group "volume_relative_ma_filter_after_layer9_amount" --repo . --entrypoint "scan_adk_zz500_hs300_spread_layer10_volume.py" --date 2026-06-12 --slug "adk_zz500_hs300_spread_long_only_v77_adk_spread_layer10_volume_after_l9_amount"',
                'python -m py_compile "scan_adk_zz500_hs300_spread_layer10_volume.py"',
                'git diff --check -- "scan_adk_zz500_hs300_spread_layer10_volume.py"',
                'python "scan_adk_zz500_hs300_spread_layer10_volume.py"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "{RUN_DIR}" --decision "{decision}" --stability-label "{stability_label}"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict "{RUN_DIR}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    display_cols = [
        "candidate",
        "line",
        "volume_feature",
        "volume_window",
        "volume_threshold",
        "volume_confirm_days",
        "volume_scale",
        "volume_days_full",
        "ann_return_full",
        "max_dd_full",
        "ann_return_last_10y",
        "max_dd_last_10y",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "ann_return_last_3y",
        "max_dd_last_3y",
        "ann_return_last_1y",
        "max_dd_last_1y",
        "full_ann_loss_pp",
        "full_dd_improve_pp",
        "last_5y_ann_loss_pp",
        "last_5y_dd_improve_pp",
    ]
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(f"VOLUME_SOURCE={source_meta}")
    print(f"DECISION={decision} STABILITY={stability_label}")
    print(
        "FULL_PASS_COUNT="
        f"{len(full_pass)} STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)} "
        f"LOSS0P5_COUNT={len(loss_passes[0.5])} LOSS1_COUNT={len(loss_passes[1.0])} "
        f"LOSS2_COUNT={len(loss_passes[2.0])} LOSS3_COUNT={len(loss_passes[3.0])}"
    )
    print("BASELINES")
    print(window_metrics[window_metrics.volume_enabled == False][display_cols].to_string(index=False))
    print("STRICT_PASS_TOP")
    print(strict_pass[display_cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    print("LOSS_1_TOP")
    print(loss_passes[1.0][display_cols].head(20).to_string(index=False) if not loss_passes[1.0].empty else "NONE")
    print("CARRY")
    print(carry[display_cols].to_string(index=False) if not carry.empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

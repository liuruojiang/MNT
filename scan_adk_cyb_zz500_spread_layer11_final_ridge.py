"""Layer 11 final ridge for long CYB / short ZZ500.

Layer 10 promoted width-supported volume filters with small edge. This final
ridge keeps the Layer 7 volhot and Layer 9 amount settings fixed, applies the
accepted Layer 10 volume line as the baseline, and locally scans only that
same volume family around the accepted ridge.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_zz500_spread_layer10_volume as l10


RUN_DIR = l10.l9.base.ROOT / "quant_param_scan_runs" / "20260612_adk_cyb_zz500_spread_long_only_v77_adk_spread_layer11_final_ridge_after_l10_volume"

LINES = [
    {
        **l10.LINES[0],
        "layer10_candidate": "l10vol_confirm_nav3_pair_volume_high_w80_thr2_d3_scale0",
        "volume_feature": "pair_volume_high",
        "volume_window": 80,
        "volume_threshold": 2.00,
        "volume_confirm_days": 3,
        "volume_scale": 0.00,
        "ridge_windows": [40, 60, 80, 100, 120],
        "ridge_thresholds": [1.50, 1.75, 2.00, 2.25],
        "ridge_days": [1, 3, 5],
        "ridge_scales": [0.0, 0.10, 0.25, 0.50],
    },
    {
        **l10.LINES[1],
        "layer10_candidate": "l10vol_primary_nav3_cyb_volume_high_w60_thr1p75_d3_scale0p75",
        "volume_feature": "cyb_volume_high",
        "volume_window": 60,
        "volume_threshold": 1.75,
        "volume_confirm_days": 3,
        "volume_scale": 0.75,
        "ridge_windows": [20, 40, 60, 80, 100],
        "ridge_thresholds": [1.50, 1.75, 2.00, 2.25],
        "ridge_days": [1, 3, 5],
        "ridge_scales": [0.0, 0.25, 0.50, 0.75],
    },
    {
        **l10.LINES[2],
        "layer10_candidate": "l10vol_defensive_nav3_cyb_volume_high_w20_thr2_d3_scale0",
        "volume_feature": "cyb_volume_high",
        "volume_window": 20,
        "volume_threshold": 2.00,
        "volume_confirm_days": 3,
        "volume_scale": 0.00,
        "ridge_windows": [20, 40, 60, 80],
        "ridge_thresholds": [1.50, 1.75, 2.00, 2.25],
        "ridge_days": [1, 3, 5],
        "ridge_scales": [0.0, 0.10, 0.25, 0.50],
    },
    {
        **l10.LINES[3],
        "layer10_candidate": "l10vol_return_nav3_zz500_volume_high_w60_thr2_d5_scale0p25",
        "volume_feature": "zz500_volume_high",
        "volume_window": 60,
        "volume_threshold": 2.00,
        "volume_confirm_days": 5,
        "volume_scale": 0.25,
        "ridge_windows": [40, 60, 80, 100, 120],
        "ridge_thresholds": [1.50, 1.75, 2.00, 2.25],
        "ridge_days": [1, 3, 5],
        "ridge_scales": [0.0, 0.10, 0.25, 0.50],
    },
    {
        **l10.LINES[4],
        "layer10_candidate": "l10vol_defensive_nav4_pair_volume_high_w80_thr2_d3_scale0",
        "volume_feature": "pair_volume_high",
        "volume_window": 80,
        "volume_threshold": 2.00,
        "volume_confirm_days": 3,
        "volume_scale": 0.00,
        "ridge_windows": [40, 60, 80, 100, 120],
        "ridge_thresholds": [1.50, 1.75, 2.00, 2.25],
        "ridge_days": [1, 3, 5],
        "ridge_scales": [0.0, 0.10, 0.25, 0.50],
    },
]

LOSS_TIERS = [0.5, 1.0, 2.0, 3.0]
WINDOW_SEGMENTS = ["full", "last_10y", "last_5y", "last_3y", "last_1y"]
LAYER10_RUN_DIR = l10.RUN_DIR


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in LINES:
        rows.append(
            {
                **line,
                "candidate": f"l11ridge_{line['line']}_volume_off",
                "ridge_enabled": False,
                "volume_feature": "off",
                "volume_window": 0,
                "volume_threshold": 0.0,
                "volume_confirm_days": 0,
                "volume_scale": 1.0,
            }
        )
        for window in line["ridge_windows"]:
            for threshold in line["ridge_thresholds"]:
                for days in line["ridge_days"]:
                    for scale in line["ridge_scales"]:
                        rows.append(
                            {
                                **line,
                                "candidate": (
                                    f"l11ridge_{line['line']}_{line['volume_feature']}"
                                    f"_w{window}_thr{l10.l9.fmt_num(float(threshold))}_d{days}_scale{l10.l9.fmt_num(float(scale))}"
                                ),
                                "ridge_enabled": True,
                                "volume_feature": line["volume_feature"],
                                "volume_window": int(window),
                                "volume_threshold": float(threshold),
                                "volume_confirm_days": int(days),
                                "volume_scale": float(scale),
                            }
                        )
    return rows


def layer10_base_returns(
    panel: pd.DataFrame,
    source_panel: pd.DataFrame,
    line: dict[str, object],
    scores: dict[str, pd.Series],
    r2s: dict[str, pd.Series],
    abs_bias: dict[int, pd.Series],
) -> pd.DataFrame:
    layer9 = l10.layer9_base_returns(panel, source_panel, line, scores, r2s, abs_bias)
    d = l10.apply_volume_overlay(
        layer9,
        source_panel,
        str(line["volume_feature"]),
        int(line["volume_window"]),
        float(line["volume_threshold"]),
        int(line["volume_confirm_days"]),
        float(line["volume_scale"]),
    )
    d["layer10_weight"] = d["weight"]
    return d


def run_candidate(cand: dict[str, object], base_by_line: dict[str, pd.DataFrame], source_panel: pd.DataFrame) -> pd.DataFrame:
    base_df = base_by_line[str(cand["line"])]
    if not cand["ridge_enabled"]:
        return base_df.rename(columns={"layer10_weight": "pre_ridge_weight"}).assign(ridge_on=0, ridge_mult=1.0)
    ridge_input = base_df.copy()
    ridge_input["layer9_weight"] = ridge_input["layer10_weight"]
    return l10.apply_volume_overlay(
        ridge_input,
        source_panel,
        str(cand["volume_feature"]),
        int(cand["volume_window"]),
        float(cand["volume_threshold"]),
        int(cand["volume_confirm_days"]),
        float(cand["volume_scale"]),
    ).rename(columns={"volume_on": "ridge_on", "volume_mult": "ridge_mult", "layer9_weight": "pre_ridge_weight"})


def extra_metrics_for_segment(result: pd.DataFrame, years: int | None) -> dict[str, float]:
    d = result.copy() if years is None else result.loc[result.index >= result.index.max() - pd.DateOffset(years=years)].copy()
    if d.empty:
        return {"ridge_days": 0.0, "ridge_day_ratio": 0.0}
    return {"ridge_days": float(d["ridge_on"].sum()), "ridge_day_ratio": float(d["ridge_on"].mean())}


def add_baselines_and_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["ridge_enabled"] == False].set_index("line")
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
    active = out["ridge_days_full"] > 0
    out["pass_full_ann_dd"] = (
        (out["ridge_enabled"] == True)
        & active
        & (out["ann_return_full"] >= out["base_ann_return_full"] - 1e-12)
        & (out["max_dd_full"] >= out["base_max_dd_full"] - 1e-12)
    )
    out["pass_full_5y_ann_dd"] = (
        out["pass_full_ann_dd"]
        & (out["ann_return_last_5y"] >= out["base_ann_return_last_5y"] - 1e-12)
        & (out["max_dd_last_5y"] >= out["base_max_dd_last_5y"] - 1e-12)
    )
    out["pass_final_guardrail"] = (
        out["pass_full_5y_ann_dd"]
        & (out["last_10y_dd_improve_pp"] >= -0.10 - 1e-12)
        & (out["last_1y_ann_loss_pp"] <= 0.50 + 1e-12)
        & (out["last_1y_dd_improve_pp"] >= -0.25 - 1e-12)
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            (out["ridge_enabled"] == True)
            & active
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["last_5y_dd_improve_pp"] >= -1e-12)
        )
    return out


def ridge_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    pass_cols = ["pass_full_ann_dd", "pass_full_5y_ann_dd", "pass_final_guardrail"] + [
        f"pass_loss_le_{str(tier).replace('.', 'p')}pp" for tier in LOSS_TIERS
    ]
    source = wm[wm["ridge_enabled"] == True]
    for pass_col in pass_cols:
        for line, group in source.groupby("line"):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": pass_col,
                        "line": line,
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
                        "best_1y_ann_loss_pp": np.nan,
                        "best_ridge_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(
                ["ann_return_full", "full_dd_improve_pp", "ann_return_last_5y"],
                ascending=[False, False, False],
            ).iloc[0]
            rows.append(
                {
                    "pass_rule": pass_col,
                    "line": line,
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
                    "best_1y_ann_loss_pp": float(best["last_1y_ann_loss_pp"]),
                    "best_ridge_days": float(best["ridge_days_full"]),
                    "patch_like": bool(
                        len(passed) >= 4
                        and passed["volume_window"].nunique() >= 2
                        and passed["volume_threshold"].nunique() >= 2
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["pass_rule", "patch_like", "pass_count", "best_full_ann_return"],
        ascending=[True, False, False, False],
    )


def comparison_table(df: pd.DataFrame, n: int = 12) -> str:
    cols = [
        "candidate",
        "line",
        "volume_feature",
        "volume_window",
        "volume_threshold",
        "volume_confirm_days",
        "volume_scale",
        "ridge_days_full",
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
            display[col] = display[col].map(lambda x: l10.l9.pct(float(x)))
        elif col.endswith("_ann_loss_pp"):
            display[col] = display[col].map(lambda x: f"{-float(x):+.2f}pp")
        elif col.endswith("_dd_improve_pp"):
            display[col] = display[col].map(lambda x: f"{float(x):+.2f}pp")
    return display.to_markdown(index=False)


def select_final(window_metrics: pd.DataFrame, ridge: pd.DataFrame) -> tuple[pd.DataFrame, str, str]:
    guarded_width = ridge[
        (ridge["pass_rule"] == "pass_final_guardrail")
        & (ridge["patch_like"] == True)
        & (ridge["pass_count"] > 0)
    ]
    if guarded_width.empty:
        carry = window_metrics[window_metrics["ridge_enabled"] == False].copy()
        return carry, "layer11_final_ridge_complete_no_better_guardrailed_candidate_carry_layer10", "final_ridge_guardrail_rejected_carry_layer10"
    passed = window_metrics[window_metrics["pass_final_guardrail"]].copy()
    carry = (
        passed.sort_values(
            ["line", "ann_return_full", "full_dd_improve_pp", "ann_return_last_5y"],
            ascending=[True, False, False, False],
        )
        .groupby("line")
        .head(1)
    )
    return carry, "layer11_final_ridge_complete_selected_guardrailed_width_supported_candidates", "final_ridge_width_supported_guardrailed"


def validate_source_and_layer10_baselines(
    source_meta: dict[str, object],
    base_by_line: dict[str, pd.DataFrame],
    lines: list[dict[str, object]] | None = None,
) -> None:
    meta_path = LAYER10_RUN_DIR / "scan_meta.json"
    carry_path = LAYER10_RUN_DIR / "carry_candidates.csv"
    daily_path = LAYER10_RUN_DIR / "daily_curves.csv"
    if not meta_path.exists() or not carry_path.exists() or not daily_path.exists():
        raise FileNotFoundError(f"Layer 10 artifacts are required: {LAYER10_RUN_DIR}")

    layer10_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    expected_source = layer10_meta["data_snapshot"]["volume_source"]
    for key in ["CYB_source", "ZZ500_source", "CYB_start", "CYB_end", "ZZ500_start", "ZZ500_end"]:
        if str(source_meta.get(key)) != str(expected_source.get(key)):
            raise RuntimeError(
                f"Layer 11 source drift: {key} current={source_meta.get(key)!r} "
                f"layer10={expected_source.get(key)!r}"
            )

    carry = pd.read_csv(carry_path).set_index("line")
    snapshot_dates = pd.read_csv(daily_path, usecols=["date"], parse_dates=["date"])["date"].dropna()
    if snapshot_dates.empty:
        raise RuntimeError(f"Layer 10 daily snapshot has no dates: {daily_path}")
    snapshot_end = pd.Timestamp(snapshot_dates.max())
    for line in lines or LINES:
        line_name = str(line["line"])
        row = carry.loc[line_name]
        if str(row["candidate"]) != str(line["layer10_candidate"]):
            raise RuntimeError(f"Layer 10 carry mismatch for {line_name}: {row['candidate']} != {line['layer10_candidate']}")
        base_df = base_by_line[line_name].loc[:snapshot_end]
        for segment, years in l10.l9.base.SEGMENTS:
            metrics = l10.l9.base.metrics_for_segment(base_df, segment, years)
            for key in ["ann_return", "max_dd"]:
                current = float(metrics[key])
                expected = float(row[f"{key}_{segment}"])
                if abs(current - expected) > 1e-10:
                    raise RuntimeError(
                        f"Layer 10 baseline drift for {line_name} {segment} {key}: "
                        f"current={current:.12g} layer10={expected:.12g}"
                    )


def main() -> None:
    git_status_before = l10.l9.base.git_text(["status", "--short"])
    mod, cyb, zz500, panel = l10.l9.l2.load_panel()
    scores, r2s, abs_bias = l10.l9.l2.precompute(panel)
    source_panel, source_meta = l10.l9.fetch_amount_panel(mod)
    source_panel = source_panel.reindex(panel.index)
    complete_rows = source_panel[["CYB_volume", "ZZ500_volume", "CYB_amount", "ZZ500_amount"]].apply(pd.to_numeric, errors="coerce").dropna()
    base_by_line = {
        str(line["line"]): layer10_base_returns(panel, source_panel, line, scores, r2s, abs_bias)
        for line in LINES
    }
    validate_source_and_layer10_baselines(source_meta, base_by_line)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    grid = make_grid()
    grid_by_candidate = {str(c["candidate"]): c for c in grid}
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []

    for cand in grid:
        result = run_candidate(cand, base_by_line, source_panel)
        wide = {**cand, "source_complete_rows_full": int(len(complete_rows))}
        for segment, years in l10.l9.base.SEGMENTS:
            metrics = l10.l9.base.metrics_for_segment(result, segment, years)
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
                "ridge_days",
                "ridge_day_ratio",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = ridge_summary(window_metrics)
    full_pass = window_metrics[(window_metrics["ridge_enabled"] == True) & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[(window_metrics["ridge_enabled"] == True) & window_metrics["pass_full_5y_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    guardrail_pass = window_metrics[(window_metrics["ridge_enabled"] == True) & window_metrics["pass_final_guardrail"]].sort_values(
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

    final, decision, stability_label = select_final(window_metrics, ridge)
    diagnostic = guardrail_pass.sort_values(["ann_return_full", "full_dd_improve_pp"], ascending=[False, False]).groupby("line").head(1)

    keep_candidates = set(window_metrics.loc[window_metrics["ridge_enabled"] == False, "candidate"].astype(str))
    keep_candidates.update(final["candidate"].astype(str).tolist())
    keep_candidates.update(diagnostic["candidate"].astype(str).tolist())
    keep_candidates.update(guardrail_pass.head(80)["candidate"].astype(str).tolist())
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

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")
    guardrail_pass.to_csv(RUN_DIR / "final_guardrail_pass_candidates.csv", index=False, encoding="utf-8-sig")
    final.to_csv(RUN_DIR / "final_candidates.csv", index=False, encoding="utf-8-sig")
    final.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# CYB/ZZ500 Layer 11 Final Ridge",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        f"- decision: `{decision}`",
        f"- stability: `{stability_label}`",
        "",
        "## Research Question",
        "Run a local final ridge around accepted Layer 10 volume families while keeping Layer 7 volhot and Layer 9 amount fixed.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).drop(columns=["ridge_windows", "ridge_thresholds", "ridge_days", "ridge_scales"]).to_markdown(index=False),
        "",
        "## Data Snapshot",
        f"- CYB publication date: {l10.l9.base.CYB_PUBLICATION_DATE}; local rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- ZZ500 publication date: {l10.l9.base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Formal aligned price rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        f"- External source CYB: {source_meta['CYB_source']}; rows {source_meta['CYB_rows']}, {source_meta['CYB_start']} -> {source_meta['CYB_end']}.",
        f"- External source ZZ500: {source_meta['ZZ500_source']}; rows {source_meta['ZZ500_rows']}, {source_meta['ZZ500_start']} -> {source_meta['ZZ500_end']}.",
        f"- Complete amount/volume rows on formal price dates: {len(complete_rows)}, start {complete_rows.index.min().date()}, end {complete_rows.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long CYB / short ZZ500; ratio is CYB/ZZ500; spread return is CYB pct_change minus ZZ500 pct_change.",
        "- T close final-ridge volume state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {l10.l9.base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Layer 7 volhot, Layer 9 amount, and Layer 10 volume are the baseline; final ridge only retunes local volume family parameters.",
        "- Guardrail requires full+5Y non-underperformance, 10Y drawdown improvement not below -0.10pp, 1Y annualized-return loss <=0.50pp, and 1Y drawdown improvement >=-0.25pp.",
        "- Result status: quasi-formal, because amount/volume data comes from V7.7 external fallback while prices use close-only official cache.",
        "",
        "## Baselines",
        comparison_table(window_metrics[window_metrics["ridge_enabled"] == False], len(LINES)),
        "",
        "## Final Guardrail Pass Candidates",
        comparison_table(guardrail_pass, 20) if not guardrail_pass.empty else "No final-ridge candidate passed guardrails.",
        "",
        "## Width Summary",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        f"Layer 11 completed with decision `{decision}`.",
        "",
        "## User-Facing Summary",
        f"- candidates_scanned: {len(grid)}",
        f"- full_baseline_pass_count: {len(full_pass)}",
        f"- full_and_5y_pass_count: {len(strict_pass)}",
        f"- final_guardrail_pass_count: {len(guardrail_pass)}",
        f"- loss_le_0p5pp_pass_count: {len(loss_passes[0.5])}",
        f"- loss_le_1pp_pass_count: {len(loss_passes[1.0])}",
        f"- loss_le_2pp_pass_count: {len(loss_passes[2.0])}",
        f"- loss_le_3pp_pass_count: {len(loss_passes[3.0])}",
        "",
        "## Final Candidates",
        comparison_table(final, 10) if not final.empty else "No final candidate selected.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    git_status_after = l10.l9.base.git_text(["status", "--short"])
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "CYB/ZZ500 spread Layer 11 final ridge",
        "repo_root": str(l10.l9.base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_cyb_zz500_spread_layer10_volume.py",
        "git_branch": l10.l9.base.git_text(["branch", "--show-current"]),
        "git_commit": l10.l9.base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": git_status_after,
        "scan_type": "fresh_layer11_final_ridge_after_l10_volume",
        "formal_status": "quasi_formal_price_index_close_to_close_with_v77_amount_volume_fallback",
        "parameter_group": "local_final_ridge_after_layer10_volume",
        "baseline": {"inputs": LINES, "pass_rule": "compare every final-ridge candidate with same-line Layer 10 carry baseline"},
        "candidate_grid": grid,
        "guardrail": {
            "full_5y_nonunderperformance": True,
            "last_10y_dd_improve_min_pp": -0.10,
            "last_1y_ann_loss_max_pp": 0.50,
            "last_1y_dd_improve_min_pp": -0.25,
        },
        "cost_model": {
            "one_way_commission": l10.l9.base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close final-ridge volume state -> T+1 close-to-close return",
            "direction": "long CYB / short ZZ500",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "data_snapshot": {
            "price_source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "external_source": source_meta,
            "formal_price": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "aligned_amount_volume": {
                "rows": int(len(complete_rows)),
                "start": str(complete_rows.index.min().date()),
                "end": str(complete_rows.index.max().date()),
            },
            "publication_dates": {"CYB": l10.l9.base.CYB_PUBLICATION_DATE, "ZZ500": l10.l9.base.ZZ500_PUBLICATION_DATE},
            "ratio": "CYB / ZZ500",
            "return_stream": "CYB pct_change - ZZ500 pct_change",
        },
        "decision": decision,
        "stability_label": stability_label,
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "full_baseline_pass_candidates": str(RUN_DIR / "full_baseline_pass_candidates.csv"),
            "full_and_5y_pass_candidates": str(RUN_DIR / "full_and_5y_pass_candidates.csv"),
            "final_guardrail_pass_candidates": str(RUN_DIR / "final_guardrail_pass_candidates.csv"),
            "final_candidates": str(RUN_DIR / "final_candidates.csv"),
            "carry_candidates": str(RUN_DIR / "carry_candidates.csv"),
            "dd_first_pass_loss_le_0p5pp": str(RUN_DIR / "dd_first_pass_loss_le_0p5pp.csv"),
            "dd_first_pass_loss_le_1p0pp": str(RUN_DIR / "dd_first_pass_loss_le_1p0pp.csv"),
            "dd_first_pass_loss_le_2p0pp": str(RUN_DIR / "dd_first_pass_loss_le_2p0pp.csv"),
            "dd_first_pass_loss_le_3p0pp": str(RUN_DIR / "dd_first_pass_loss_le_3p0pp.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "\n".join(
            [
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "CYB/ZZ500 spread Layer 11 final ridge" --parameter-group "local_final_ridge_after_layer10_volume" --repo . --entrypoint "scan_adk_cyb_zz500_spread_layer11_final_ridge.py" --date 2026-06-12 --slug "adk_cyb_zz500_spread_long_only_v77_adk_spread_layer11_final_ridge_after_l10_volume"',
                'python -m py_compile "scan_adk_cyb_zz500_spread_layer11_final_ridge.py"',
                'git diff --check -- "scan_adk_cyb_zz500_spread_layer11_final_ridge.py"',
                'python "scan_adk_cyb_zz500_spread_layer11_final_ridge.py"',
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
        "ridge_days_full",
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
        "last_10y_dd_improve_pp",
        "last_5y_ann_loss_pp",
        "last_5y_dd_improve_pp",
        "last_1y_ann_loss_pp",
        "last_1y_dd_improve_pp",
    ]
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(f"SOURCE={source_meta}")
    print(f"DECISION={decision} STABILITY={stability_label}")
    print(
        "FULL_PASS_COUNT="
        f"{len(full_pass)} STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)} "
        f"FINAL_GUARDRAIL_COUNT={len(guardrail_pass)} "
        f"LOSS0P5_COUNT={len(loss_passes[0.5])} LOSS1_COUNT={len(loss_passes[1.0])} "
        f"LOSS2_COUNT={len(loss_passes[2.0])} LOSS3_COUNT={len(loss_passes[3.0])}"
    )
    print("BASELINES")
    print(window_metrics[window_metrics.ridge_enabled == False][display_cols].to_string(index=False))
    print("GUARDRAIL_PASS_TOP")
    print(guardrail_pass[display_cols].head(20).to_string(index=False) if not guardrail_pass.empty else "NONE")
    print("FINAL")
    print(final[display_cols].to_string(index=False) if not final.empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

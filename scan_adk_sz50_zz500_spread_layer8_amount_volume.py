"""Layer 8 amount/volume overlay after rejected entry staging for SZ50/ZZ500.

Layer 7 entry staging was rejected, so this layer carries the Layer 6 scorehot
branches. It uses the V7.7 amount-data fallback to fetch index amount/volume,
then tests prior-row amount states as final exposure multipliers.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_sz50_zz500_spread_layer3_target_vol as l3
import scan_adk_sz50_zz500_spread_layer6_overheat as l6
import scan_adk_sz50_zz500_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_sz50_zz500_spread_long_only_v77_adk_spread_layer8_amount_volume_after_l7_rejected"

LINES = [
    {
        "line": "primary_scorehot18_s025",
        "line_role": "primary_l6_carry",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.75,
        "score_threshold": 0.0,
        "abs_ma": 80,
        "abs_threshold": -0.050,
        "target_vol": 0.16,
        "vol_window": 20,
        "max_leverage": 1.5,
        "scale_deadband": 0.30,
        "tv_enabled": True,
        "decay_threshold": 0.30,
        "recovery_threshold": 0.80,
        "warmup_days": 3,
        "derisk_scale": 0.25,
        "overheat_kind": "scorehot",
        "overheat_param_a": 18.0,
        "overheat_param_b": 0.0,
        "overheat_param_c": 0.25,
        "layer6_candidate": "l6_return_s0_decay030_rec080_w3_s025_scorehot18_scale0p25",
    },
    {
        "line": "primary_scorehot18_s05",
        "line_role": "nearby_confirmation",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.75,
        "score_threshold": 0.0,
        "abs_ma": 80,
        "abs_threshold": -0.050,
        "target_vol": 0.16,
        "vol_window": 20,
        "max_leverage": 1.5,
        "scale_deadband": 0.30,
        "tv_enabled": True,
        "decay_threshold": 0.30,
        "recovery_threshold": 0.80,
        "warmup_days": 3,
        "derisk_scale": 0.25,
        "overheat_kind": "scorehot",
        "overheat_param_a": 18.0,
        "overheat_param_b": 0.0,
        "overheat_param_c": 0.50,
        "layer6_candidate": "l6_return_s0_decay030_rec080_w3_s025_scorehot18_scale0p5",
    },
    {
        "line": "return_watch_scorehot18_s0",
        "line_role": "return_heavy_watch",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.75,
        "score_threshold": -1.0,
        "abs_ma": 30,
        "abs_threshold": 0.005,
        "target_vol": 0.16,
        "vol_window": 30,
        "max_leverage": 1.5,
        "scale_deadband": 0.20,
        "tv_enabled": True,
        "decay_threshold": 0.45,
        "recovery_threshold": 0.90,
        "warmup_days": 10,
        "derisk_scale": 0.25,
        "overheat_kind": "scorehot",
        "overheat_param_a": 18.0,
        "overheat_param_b": 0.0,
        "overheat_param_c": 0.0,
        "layer6_candidate": "l6_return_sm1_decay045_rec090_w10_s025_scorehot18_scale0",
    },
]

AMOUNT_WINDOWS = [20, 40, 60, 120]
LOW_AMOUNT_THRESHOLDS = [0.60, 0.70, 0.80, 0.90, 1.00]
REL_LOW_THRESHOLDS = [0.70, 0.80, 0.90, 1.00]
ZZ500_HOT_THRESHOLDS = [1.20, 1.40, 1.60, 1.80, 2.00]
OVERLAY_SCALES = [0.0, 0.25, 0.50, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0]


def fmt_num(value: float) -> str:
    sign = "m" if value < 0 else ""
    return sign + f"{abs(value):g}".replace(".", "p")


def fetch_amount_panel(mod: object) -> tuple[pd.DataFrame, dict[str, object]]:
    sz50_amt, sz50_source = mod._fetch_cn_amount_with_fallback(mod.CN_DK_SZ50_SECID, "SZ50", beg="20070101", lmt=10000)
    zz500_amt, zz500_source = mod._fetch_cn_amount_with_fallback(mod.CN_DK_ZZ500_SECID, "ZZ500", beg="20070101", lmt=10000)
    out = pd.concat(
        [
            sz50_amt[["amount", "volume"]].rename(columns={"amount": "SZ50_amount", "volume": "SZ50_volume"}),
            zz500_amt[["amount", "volume"]].rename(columns={"amount": "ZZ500_amount", "volume": "ZZ500_volume"}),
        ],
        axis=1,
    ).dropna()
    meta = {
        "SZ50_source": sz50_source,
        "ZZ500_source": zz500_source,
        "SZ50_rows": int(len(sz50_amt)),
        "ZZ500_rows": int(len(zz500_amt)),
        "SZ50_start": str(sz50_amt.index.min().date()),
        "SZ50_end": str(sz50_amt.index.max().date()),
        "ZZ500_start": str(zz500_amt.index.min().date()),
        "ZZ500_end": str(zz500_amt.index.max().date()),
        "aligned_rows": int(len(out)),
        "aligned_start": str(out.index.min().date()),
        "aligned_end": str(out.index.max().date()),
    }
    return out, meta


def layer6_base_returns(panel: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    l5_base = l6.layer5_base_returns(panel, line)
    params = {
        "score_threshold": float(line["overheat_param_a"]),
        "window": float(line["overheat_param_a"]),
        "threshold": float(line["overheat_param_b"]),
        "scale": float(line["overheat_param_c"]),
    }
    d = l6.apply_overlay(l5_base, str(line["overheat_kind"]), params).copy()
    d["layer6_weight"] = d["weight"]
    return d


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in LINES:
        rows.append(
            {
                **line,
                "candidate": f"l8_{line['line']}_amount_off",
                "amount_kind": "off",
                "amount_window": 0,
                "amount_threshold": 0.0,
                "amount_scale": 1.0,
            }
        )
        for window in AMOUNT_WINDOWS:
            for threshold in LOW_AMOUNT_THRESHOLDS:
                for scale in OVERLAY_SCALES:
                    rows.append(
                        {
                            **line,
                            "candidate": f"l8_{line['line']}_sz50_amtcold_w{window}_thr{fmt_num(threshold)}_scale{fmt_num(scale)}",
                            "amount_kind": "sz50_amt_cold",
                            "amount_window": window,
                            "amount_threshold": threshold,
                            "amount_scale": scale,
                        }
                    )
            for threshold in REL_LOW_THRESHOLDS:
                for scale in OVERLAY_SCALES:
                    rows.append(
                        {
                            **line,
                            "candidate": f"l8_{line['line']}_rel_amtcold_w{window}_thr{fmt_num(threshold)}_scale{fmt_num(scale)}",
                            "amount_kind": "relative_sz50_zz500_cold",
                            "amount_window": window,
                            "amount_threshold": threshold,
                            "amount_scale": scale,
                        }
                    )
            for threshold in ZZ500_HOT_THRESHOLDS:
                for scale in OVERLAY_SCALES:
                    rows.append(
                        {
                            **line,
                            "candidate": f"l8_{line['line']}_zz500_amthot_w{window}_thr{fmt_num(threshold)}_scale{fmt_num(scale)}",
                            "amount_kind": "zz500_amt_hot",
                            "amount_window": window,
                            "amount_threshold": threshold,
                            "amount_scale": scale,
                        }
                    )
    return rows


def amount_trigger(amount_panel: pd.DataFrame, kind: str, window: int, threshold: float) -> tuple[pd.Series, pd.Series]:
    if kind == "sz50_amt_cold":
        feature = amount_panel["SZ50_amount"] / amount_panel["SZ50_amount"].rolling(window).mean()
        trigger = feature < threshold
    elif kind == "relative_sz50_zz500_cold":
        rel = amount_panel["SZ50_amount"] / amount_panel["ZZ500_amount"]
        feature = rel / rel.rolling(window).mean()
        trigger = feature < threshold
    elif kind == "zz500_amt_hot":
        feature = amount_panel["ZZ500_amount"] / amount_panel["ZZ500_amount"].rolling(window).mean()
        trigger = feature > threshold
    else:
        raise ValueError(kind)
    return trigger.shift(1, fill_value=False).astype(bool), feature.shift(1)


def apply_amount_overlay(
    base_df: pd.DataFrame,
    amount_panel: pd.DataFrame,
    kind: str,
    window: int,
    threshold: float,
    scale: float,
) -> pd.DataFrame:
    d = base_df.copy()
    if kind == "off":
        trigger = pd.Series(False, index=d.index)
        aux = pd.Series(np.nan, index=d.index)
        mult = pd.Series(1.0, index=d.index)
    else:
        trigger_raw, aux_raw = amount_trigger(amount_panel, kind, int(window), float(threshold))
        trigger = trigger_raw.reindex(d.index).fillna(False).astype(bool)
        aux = aux_raw.reindex(d.index)
        mult = pd.Series(1.0, index=d.index)
        mult.loc[trigger] = float(scale)
    final_weight = d["layer6_weight"] * mult
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = final_weight * d["spread_return"].fillna(0.0)
    ret = gross_return - cost
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "layer6_weight": d["layer6_weight"],
            "amount_mult": mult,
            "amount_on": trigger.astype(int),
            "amount_aux": aux,
            "score": d["score"],
            "decay_on": d["decay_on"],
            "overheat_on": d["overlay_on"],
            "spread_return": d["spread_return"],
        },
        index=d.index,
    )


def extra_metrics_for_segment(result: pd.DataFrame, years: int | None) -> dict[str, float]:
    if years is None:
        d = result.copy()
    else:
        cutoff = result.index.max() - pd.DateOffset(years=years)
        d = result.loc[result.index >= cutoff].copy()
    if d.empty:
        return {
            "amount_days": 0.0,
            "amount_day_ratio": 0.0,
            "avg_amount_mult_active": 1.0,
            "overheat_amount_overlap_days": 0.0,
        }
    active = d["layer6_weight"].abs() > 1e-12
    return {
        "amount_days": float(d["amount_on"].sum()),
        "amount_day_ratio": float(d["amount_on"].mean()),
        "avg_amount_mult_active": float(d.loc[active, "amount_mult"].mean()) if active.any() else 1.0,
        "overheat_amount_overlap_days": float(((d["overheat_on"] > 0) & (d["amount_on"] > 0)).sum()),
    }


def add_baselines_and_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["amount_kind"] == "off"].set_index("line")
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
    ]:
        out[f"base_{col}"] = out["line"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100.0
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100.0
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100.0
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100.0
    out["cost_delta"] = out["cost_total_full"] - out["base_cost_total_full"]
    out["pass_full_ann_dd"] = (
        (out["amount_kind"] != "off")
        & (out["ann_return_full"] >= out["base_ann_return_full"] - 1e-12)
        & (out["max_dd_full"] >= out["base_max_dd_full"] - 1e-12)
    )
    out["pass_full_and_5y"] = (
        out["pass_full_ann_dd"]
        & (out["ann_return_last_5y"] >= out["base_ann_return_last_5y"] - 1e-12)
        & (out["max_dd_last_5y"] >= out["base_max_dd_last_5y"] - 1e-12)
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            (out["amount_kind"] != "off")
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["fivey_dd_improve_pp"] >= -1e-12)
        )
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    pass_cols = ["pass_full_ann_dd", "pass_full_and_5y"] + [f"pass_loss_le_{str(t).replace('.', 'p')}pp" for t in LOSS_TIERS]
    source = wm[wm["amount_kind"] != "off"]
    for pass_col in pass_cols:
        for (line, kind), group in source.groupby(["line", "amount_kind"]):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": pass_col,
                        "line": line,
                        "amount_kind": kind,
                        "pass_count": 0,
                        "window_count": 0,
                        "threshold_count": 0,
                        "scale_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "best_amount_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            rows.append(
                {
                    "pass_rule": pass_col,
                    "line": line,
                    "amount_kind": kind,
                    "pass_count": int(len(passed)),
                    "window_count": int(passed["amount_window"].nunique()),
                    "threshold_count": int(passed["amount_threshold"].nunique()),
                    "scale_count": int(passed["amount_scale"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                    "best_full_dd_improve_pp": best["full_dd_improve_pp"],
                    "best_5y_ann_return": best["ann_return_last_5y"],
                    "best_5y_max_dd": best["max_dd_last_5y"],
                    "best_amount_days": best["amount_days_full"],
                    "patch_like": bool(
                        len(passed) >= 4
                        and passed["amount_window"].nunique() >= 2
                        and passed["amount_scale"].nunique() >= 2
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["pass_rule", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def window_table(df: pd.DataFrame, n: int = 16) -> str:
    cols = ["candidate", "line", "amount_kind", "amount_window", "amount_threshold", "amount_scale", "amount_days_full"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, sz50, zz500, panel = l3.load_panel()
    amount_panel, amount_meta = fetch_amount_panel(mod)
    amount_panel = amount_panel.reindex(panel.index).dropna()
    base_by_line = {str(line["line"]): layer6_base_returns(panel, line) for line in LINES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = make_grid()
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    daily_parts: list[pd.DataFrame] = []

    for cand in grid:
        result = apply_amount_overlay(
            base_by_line[str(cand["line"])],
            amount_panel,
            str(cand["amount_kind"]),
            int(cand["amount_window"]),
            float(cand["amount_threshold"]),
            float(cand["amount_scale"]),
        )
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["line"] = cand["line"]
        daily["amount_kind"] = cand["amount_kind"]
        daily_parts.append(daily.reset_index(names="date"))

        wide = {**cand}
        for segment, years in base.SEGMENTS:
            metrics = base.metrics_for_segment(result, segment, years)
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
                "amount_days",
                "amount_day_ratio",
                "avg_amount_mult_active",
                "overheat_amount_overlap_days",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)

    full_pass = window_metrics[(window_metrics["amount_kind"] != "off") & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[(window_metrics["amount_kind"] != "off") & window_metrics["pass_full_and_5y"]].sort_values(
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

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")

    cols = [
        "candidate",
        "line",
        "line_role",
        "amount_kind",
        "amount_window",
        "amount_threshold",
        "amount_scale",
        "amount_days_full",
        "avg_amount_mult_active_full",
        "ann_return_full",
        "max_dd_full",
        "full_ann_loss_pp",
        "full_dd_improve_pp",
        "ann_return_last_10y",
        "max_dd_last_10y",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "fivey_ann_loss_pp",
        "fivey_dd_improve_pp",
        "ann_return_last_3y",
        "max_dd_last_3y",
        "ann_return_last_1y",
        "max_dd_last_1y",
        "cost_total_full",
    ]
    display_cols = [c for c in cols if c in window_metrics.columns]
    baseline = window_metrics[window_metrics["amount_kind"] == "off"][display_cols]
    record_lines = [
        "# SZ50/ZZ500 Layer 8 Amount/Volume Overlay",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer8_amount_volume_complete_pending_user_review`",
        "- stability: `amount_volume_after_l7_rejected_review`",
        "",
        "## Research Question",
        "Test amount/volume overlays after Layer 7 entry staging was rejected; baseline is Layer 6 scorehot carry.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
        "",
        "## Data Snapshot",
        f"- SZ50 publication date: {base.SZ50_PUBLICATION_DATE}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}.",
        f"- Formal price rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        f"- Amount source SZ50: {amount_meta['SZ50_source']}; rows {amount_meta['SZ50_rows']}, {amount_meta['SZ50_start']} -> {amount_meta['SZ50_end']}.",
        f"- Amount source ZZ500: {amount_meta['ZZ500_source']}; rows {amount_meta['ZZ500_rows']}, {amount_meta['ZZ500_start']} -> {amount_meta['ZZ500_end']}.",
        f"- Amount rows aligned to price panel: {len(amount_panel)}, {amount_panel.index.min().date()} -> {amount_panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long SZ50 / short ZZ500; ratio is SZ50/ZZ500; spread return is SZ50 pct_change minus ZZ500 pct_change.",
        "- T close signal/state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Amount states use prior-row amount ratios/features; final turnover and costs are recomputed.",
        "- Result status: quasi-formal, because amount data is fetched via V7.7 external fallback rather than the close-only official cache.",
        "",
        "## Amount Grid",
        f"- amount_window: {AMOUNT_WINDOWS}",
        f"- sz50 low amount thresholds: {LOW_AMOUNT_THRESHOLDS}",
        f"- relative SZ50/ZZ500 low thresholds: {REL_LOW_THRESHOLDS}",
        f"- zz500 hot amount thresholds: {ZZ500_HOT_THRESHOLDS}",
        f"- overlay scales: {OVERLAY_SCALES}",
        "",
        "## Baselines",
        baseline.to_markdown(index=False),
        "",
        "## Full+5Y Non-Underperformance Candidates",
        window_table(strict_pass, 20) if not strict_pass.empty else "No amount candidate passed full+5Y non-underperformance.",
        "",
        "## DD-First Candidates Loss <= 1pp",
        window_table(loss_passes[1.0], 20) if not loss_passes[1.0].empty else "No amount candidate passed loss<=1pp with DD improvement.",
        "",
        "## DD-First Candidates Loss <= 2pp",
        window_table(loss_passes[2.0], 20) if not loss_passes[2.0].empty else "No amount candidate passed loss<=2pp with DD improvement.",
        "",
        "## Width Summary",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 8 completed and stopped for user review before final ridge or landing script.",
        "",
        "## User-Facing Summary",
        f"- candidates_scanned: {len(grid)}",
        f"- full_baseline_pass_count: {len(full_pass)}",
        f"- full_and_5y_pass_count: {len(strict_pass)}",
        f"- loss_le_1pp_pass_count: {len(loss_passes[1.0])}",
        f"- loss_le_2pp_pass_count: {len(loss_passes[2.0])}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    git_status_after = base.git_text(["status", "--short"])
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "SZ50/ZZ500 spread Layer 8 amount/volume",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_sz50_zz500_spread_layer6_overheat.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": git_status_after,
        "scan_type": "fresh_layer8_amount_volume_after_l7_rejected",
        "result_status": "quasi-formal_external_amount_fallback_price_index_research",
        "parameter_group": "amount_window_threshold_scale_after_l6_scorehot",
        "baseline": {
            "lines": LINES,
            "pass_rule": "compare every amount candidate with same-line amount_off",
            "layer7_entry_staging": "rejected",
        },
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "data_snapshot": {
            "price_source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "amount_source": amount_meta,
            "formal_price": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "aligned_amount": {"rows": int(len(amount_panel)), "start": str(amount_panel.index.min().date()), "end": str(amount_panel.index.max().date())},
            "publication_dates": {"SZ50": base.SZ50_PUBLICATION_DATE, "ZZ500": base.ZZ500_PUBLICATION_DATE},
        },
        "amount_implementation": "prior-row amount feature trigger; final exposure multiplier and turnover/cost recomputed",
        "decision": "layer8_amount_volume_complete_pending_user_review",
        "stability_label": "amount_volume_after_l7_rejected_review",
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
            "dd_first_pass_loss_le_0p5pp": str(RUN_DIR / "dd_first_pass_loss_le_0p5pp.csv"),
            "dd_first_pass_loss_le_1p0pp": str(RUN_DIR / "dd_first_pass_loss_le_1p0pp.csv"),
            "dd_first_pass_loss_le_2p0pp": str(RUN_DIR / "dd_first_pass_loss_le_2p0pp.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "\n".join(
            [
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "SZ50/ZZ500 spread Layer 8 amount/volume" --parameter-group "amount_window_threshold_scale_after_l6_scorehot" --repo . --entrypoint "scan_adk_sz50_zz500_spread_layer8_amount_volume.py" --date 2026-06-12 --slug "adk_sz50_zz500_spread_long_only_v77_adk_spread_layer8_amount_volume_after_l7_rejected"',
                'python -m py_compile "scan_adk_sz50_zz500_spread_layer8_amount_volume.py"',
                'python "scan_adk_sz50_zz500_spread_layer8_amount_volume.py"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "{RUN_DIR}" --decision "layer8_amount_volume_complete_pending_user_review" --stability-label "amount_volume_after_l7_rejected_review"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict "{RUN_DIR}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(f"AMOUNT={amount_meta}")
    print(
        "FULL_PASS_COUNT="
        f"{len(full_pass)} STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)} "
        f"LOSS1_COUNT={len(loss_passes[1.0])} LOSS2_COUNT={len(loss_passes[2.0])}"
    )
    print("BASELINES")
    print(baseline.to_string(index=False))
    print("STRICT_PASS_TOP")
    print(strict_pass[display_cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    print("LOSS_1_TOP")
    print(loss_passes[1.0][display_cols].head(20).to_string(index=False) if not loss_passes[1.0].empty else "NONE")
    print("LOSS_2_TOP")
    print(loss_passes[2.0][display_cols].head(20).to_string(index=False) if not loss_passes[2.0].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

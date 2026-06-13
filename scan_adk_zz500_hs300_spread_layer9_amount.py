"""Layer 9 amount filter for long ZZ500 / short HS300.

Layer 8 entry staging was rejected, so this layer uses the promoted Layer 7
volhot carry lines as the baseline. Amount states are evaluated at T close and
shifted to T+1 execution. Prices remain local official close cache; amount uses
the V7.7 EastMoney fallback and is therefore quasi-formal.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_hs300_spread_layer2_score_abs_filter as l2
import scan_adk_zz500_hs300_spread_layer5_momentum_decay as l5
import scan_adk_zz500_hs300_spread_layer7_overheat as l7
import scan_adk_zz500_hs300_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_hs300_spread_long_only_v77_adk_spread_layer9_amount_after_l7_volhot"

LINES = [
    {
        **l7.LINES[0],
        "line": "main_confirm",
        "line_role": "main_strict_full_5y",
        "layer7_candidate": "l7_main_confirm_volhot_w40_thr22_scale0p5",
        "overlay_kind": "volhot",
        "param_a": 40.0,
        "param_b": 0.22,
        "param_c": 0.50,
    },
    {
        **l7.LINES[1],
        "line": "return_preserve",
        "line_role": "return_preserve_watchlist",
        "layer7_candidate": "l7_return_preserve_volhot_w40_thr22_scale0",
        "overlay_kind": "volhot",
        "param_a": 40.0,
        "param_b": 0.22,
        "param_c": 0.00,
    },
    {
        **l7.LINES[2],
        "line": "primary_dd",
        "line_role": "primary_dd_first",
        "layer7_candidate": "l7_primary_dd_volhot_w20_thr35_scale0",
        "overlay_kind": "volhot",
        "param_a": 20.0,
        "param_b": 0.35,
        "param_c": 0.00,
    },
    {
        **l7.LINES[3],
        "line": "ultra_def",
        "line_role": "ultra_defensive_watchlist",
        "layer7_candidate": "l7_ultra_def_volhot_w40_thr22_scale0p5",
        "overlay_kind": "volhot",
        "param_a": 40.0,
        "param_b": 0.22,
        "param_c": 0.50,
    },
]

AMOUNT_WINDOWS = [20, 40, 60, 80, 120]
HIGH_THRESHOLDS = [1.25, 1.50, 1.75, 2.00]
LOW_THRESHOLDS = [0.75, 0.85, 1.00]
CONFIRM_DAYS = [1, 3, 5]
AMOUNT_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0, 3.0]
WINDOW_SEGMENTS = ["full", "last_10y", "last_5y", "last_3y", "last_1y"]


def fmt_num(value: float) -> str:
    sign = "m" if value < 0 else ""
    return sign + f"{abs(value):g}".replace(".", "p")


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def fetch_amount_panel(mod: object) -> tuple[pd.DataFrame, dict[str, object]]:
    hs300_amt, hs300_source = mod._fetch_cn_amount_with_fallback(mod.CN_DK_HS300_SECID, "HS300", beg="20070101", lmt=10000)
    zz500_amt, zz500_source = mod._fetch_cn_amount_with_fallback(mod.CN_DK_ZZ500_SECID, "ZZ500", beg="20070101", lmt=10000)
    out = pd.concat(
        [
            hs300_amt[["amount", "volume"]].rename(columns={"amount": "HS300_amount", "volume": "HS300_volume"}),
            zz500_amt[["amount", "volume"]].rename(columns={"amount": "ZZ500_amount", "volume": "ZZ500_volume"}),
        ],
        axis=1,
    ).dropna()
    meta = {
        "HS300_source": hs300_source,
        "ZZ500_source": zz500_source,
        "HS300_rows": int(len(hs300_amt)),
        "ZZ500_rows": int(len(zz500_amt)),
        "HS300_start": str(hs300_amt.index.min().date()),
        "HS300_end": str(hs300_amt.index.max().date()),
        "ZZ500_start": str(zz500_amt.index.min().date()),
        "ZZ500_end": str(zz500_amt.index.max().date()),
        "aligned_rows": int(len(out)),
        "aligned_start": str(out.index.min().date()),
        "aligned_end": str(out.index.max().date()),
        "unit_note": "EastMoney amount numeric field as returned by V7.7 fallback; volume is raw index volume field.",
    }
    return out, meta


def layer7_base_returns(
    panel: pd.DataFrame,
    line: dict[str, object],
    scores: dict[str, pd.Series],
    r2s: dict[str, pd.Series],
    abs_bias: dict[int, pd.Series],
) -> pd.DataFrame:
    l4_frame = l5.l4_nav_off_frame(panel, line, scores, r2s, abs_bias)
    d = l7.apply_overlay(l4_frame, str(line["overlay_kind"]), l7.params_for(line))
    d["layer7_weight"] = d["weight"]
    return d


def amount_feature(amount_panel: pd.DataFrame, feature: str, window: int) -> pd.Series:
    hs300_rel = amount_panel["HS300_amount"] / amount_panel["HS300_amount"].rolling(window).mean()
    zz500_rel = amount_panel["ZZ500_amount"] / amount_panel["ZZ500_amount"].rolling(window).mean()
    pair_rel = zz500_rel / hs300_rel
    if feature in {"hs300_amount_high", "hs300_amount_low"}:
        return hs300_rel
    if feature in {"zz500_amount_high", "zz500_amount_low"}:
        return zz500_rel
    if feature in {"pair_amount_high", "pair_amount_low"}:
        return pair_rel
    raise ValueError(feature)


def confirmed_trigger(cond: pd.Series, days: int) -> pd.Series:
    if days <= 1:
        return cond.fillna(False).astype(bool)
    return (cond.astype(float).rolling(days).sum().fillna(0) >= days).astype(bool)


def apply_amount_overlay(
    base_df: pd.DataFrame,
    amount_panel: pd.DataFrame,
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
        indicator = amount_feature(amount_panel, str(feature), int(window)).reindex(d.index)
        raw = indicator >= float(threshold) if str(feature).endswith("high") else indicator <= float(threshold)
        on = confirmed_trigger(raw, int(confirm_days)).shift(1, fill_value=False).astype(bool)
        mult = pd.Series(1.0, index=d.index)
        mult.loc[on] = float(scale)

    final_weight = d["layer7_weight"] * mult
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
            "layer7_weight": d["layer7_weight"],
            "amount_mult": mult,
            "amount_on": on.astype(int),
            "amount_indicator": indicator,
            "overlay_on": d["overlay_on"],
            "overlay_mult": d["overlay_mult"],
            "score": d["score"],
            "selected_scale": d["selected_scale"],
            "spread_return": d["spread_return"],
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    features = [
        "hs300_amount_high",
        "hs300_amount_low",
        "zz500_amount_high",
        "zz500_amount_low",
        "pair_amount_high",
        "pair_amount_low",
    ]
    for line in LINES:
        rows.append(
            {
                **line,
                "candidate": f"l9amt_{line['line']}_amount_off",
                "amount_feature": "off",
                "amount_window": 0,
                "amount_threshold": 0.0,
                "confirm_days": 0,
                "amount_scale": 1.0,
                "amount_enabled": False,
            }
        )
        for feature in features:
            thresholds = HIGH_THRESHOLDS if feature.endswith("high") else LOW_THRESHOLDS
            for window in AMOUNT_WINDOWS:
                for threshold in thresholds:
                    for days in CONFIRM_DAYS:
                        for scale in AMOUNT_SCALES:
                            rows.append(
                                {
                                    **line,
                                    "candidate": (
                                        f"l9amt_{line['line']}_{feature}"
                                        f"_w{window}_thr{fmt_num(threshold)}_d{days}_scale{fmt_num(scale)}"
                                    ),
                                    "amount_feature": feature,
                                    "amount_window": window,
                                    "amount_threshold": threshold,
                                    "confirm_days": days,
                                    "amount_scale": scale,
                                    "amount_enabled": True,
                                }
                            )
    return rows


def run_candidate(cand: dict[str, object], base_by_line: dict[str, pd.DataFrame], amount_panel: pd.DataFrame) -> pd.DataFrame:
    return apply_amount_overlay(
        base_by_line[str(cand["line"])],
        amount_panel,
        None if not cand["amount_enabled"] else str(cand["amount_feature"]),
        None if not cand["amount_enabled"] else int(cand["amount_window"]),
        None if not cand["amount_enabled"] else float(cand["amount_threshold"]),
        None if not cand["amount_enabled"] else int(cand["confirm_days"]),
        None if not cand["amount_enabled"] else float(cand["amount_scale"]),
    )


def extra_metrics_for_segment(result: pd.DataFrame, years: int | None) -> dict[str, float]:
    if years is None:
        d = result.copy()
    else:
        cutoff = result.index.max() - pd.DateOffset(years=years)
        d = result.loc[result.index >= cutoff].copy()
    if d.empty:
        return {"amount_days": 0.0, "amount_day_ratio": 0.0, "volhot_amount_overlap_days": 0.0}
    return {
        "amount_days": float(d["amount_on"].sum()),
        "amount_day_ratio": float(d["amount_on"].mean()),
        "volhot_amount_overlap_days": float(((d["overlay_on"] > 0) & (d["amount_on"] > 0)).sum()),
    }


def add_baselines_and_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["amount_enabled"] == False].set_index("line")
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
    active_amount = out["amount_days_full"] > 0
    out["pass_full_ann_dd"] = (
        (out["amount_enabled"] == True)
        & active_amount
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
            (out["amount_enabled"] == True)
            & active_amount
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
    source = wm[wm["amount_enabled"] == True]
    for pass_col in pass_cols:
        for (line, feature), group in source.groupby(["line", "amount_feature"]):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": pass_col,
                        "line": line,
                        "amount_feature": feature,
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
                        "best_amount_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(
                len(passed) >= 4
                and passed["amount_window"].nunique() >= 2
                and passed["amount_threshold"].nunique() >= 2
            )
            rows.append(
                {
                    "pass_rule": pass_col,
                    "line": line,
                    "amount_feature": feature,
                    "pass_count": int(len(passed)),
                    "window_count": int(passed["amount_window"].nunique()),
                    "threshold_count": int(passed["amount_threshold"].nunique()),
                    "day_count": int(passed["confirm_days"].nunique()),
                    "scale_count": int(passed["amount_scale"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "best_full_ann_loss_pp": float(best["full_ann_loss_pp"]),
                    "best_full_dd_improve_pp": float(best["full_dd_improve_pp"]),
                    "best_5y_ann_return": float(best["ann_return_last_5y"]),
                    "best_5y_max_dd": float(best["max_dd_last_5y"]),
                    "best_amount_days": float(best["amount_days_full"]),
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
        volhot_on = d["overlay_on"].astype(float) > 0
        amount_on = d["amount_on"].astype(float) > 0
        masks = {
            "volhot0_amount0": ~volhot_on & ~amount_on,
            "volhot1_amount0": volhot_on & ~amount_on,
            "volhot0_amount1": ~volhot_on & amount_on,
            "volhot1_amount1": volhot_on & amount_on,
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
        "amount_feature",
        "amount_window",
        "amount_threshold",
        "confirm_days",
        "amount_scale",
        "amount_days_full",
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
            display[col] = display[col].map(lambda x: pct(float(x)))
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
        return carry, "layer9_amount_complete_promoted_width_supported_amount", "amount_width_supported_full_5y_nonunderperformance"
    carry = window_metrics[window_metrics["amount_enabled"] == False].copy()
    return carry, "layer9_amount_complete_not_promoted_carry_layer7_volhot", "amount_filter_rejected_carry_layer7_volhot"


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, zz500, hs300, panel = l2.load_panel()
    scores, r2s, abs_bias = l2.precompute(panel)
    amount_panel, amount_meta = fetch_amount_panel(mod)
    amount_panel = amount_panel.reindex(panel.index)
    complete_amount_rows = amount_panel[["HS300_amount", "ZZ500_amount"]].apply(pd.to_numeric, errors="coerce").dropna()
    base_by_line = {str(line["line"]): layer7_base_returns(panel, line, scores, r2s, abs_bias) for line in LINES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    grid = make_grid()
    grid_by_candidate = {str(c["candidate"]): c for c in grid}
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []

    for cand in grid:
        result = run_candidate(cand, base_by_line, amount_panel)
        wide = {**cand}
        wide["amount_complete_rows_full"] = int(len(complete_amount_rows))
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
                "volhot_amount_overlap_days",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    full_pass = window_metrics[(window_metrics["amount_enabled"] == True) & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[(window_metrics["amount_enabled"] == True) & window_metrics["pass_full_5y_ann_dd"]].sort_values(
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

    keep_candidates = set(window_metrics.loc[window_metrics["amount_enabled"] == False, "candidate"].astype(str))
    keep_candidates.update(carry["candidate"].astype(str).tolist())
    keep_candidates.update(diagnostic["candidate"].astype(str).tolist())
    keep_candidates.update(strict_pass.head(80)["candidate"].astype(str).tolist())
    keep_candidates.update(full_pass.head(80)["candidate"].astype(str).tolist())
    for passed in loss_passes.values():
        keep_candidates.update(passed.head(40)["candidate"].astype(str).tolist())
    daily_parts = []
    for candidate in sorted(keep_candidates):
        cand = grid_by_candidate[candidate]
        result = run_candidate(cand, base_by_line, amount_panel)
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["line"] = cand["line"]
        daily["amount_feature"] = cand["amount_feature"]
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
        "# ZZ500/HS300 Layer 9 Amount Filter",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        f"- decision: `{decision}`",
        f"- stability: `{stability_label}`",
        "",
        "## Research Question",
        "Test amount relative-MA filters after Layer 8 rejected entry staging, using promoted Layer 7 volhot carry lines as baseline.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
        "",
        "## Data Snapshot",
        f"- HS300 publication date: {base.HS300_PUBLICATION_DATE}; local rows: {len(hs300)}, start {hs300.index.min().date()}, end {hs300.index.max().date()}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Formal aligned price rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        f"- Amount source HS300: {amount_meta['HS300_source']}; rows {amount_meta['HS300_rows']}, {amount_meta['HS300_start']} -> {amount_meta['HS300_end']}.",
        f"- Amount source ZZ500: {amount_meta['ZZ500_source']}; rows {amount_meta['ZZ500_rows']}, {amount_meta['ZZ500_start']} -> {amount_meta['ZZ500_end']}.",
        f"- Complete amount rows on formal price dates: {len(complete_amount_rows)}, start {complete_amount_rows.index.min().date()}, end {complete_amount_rows.index.max().date()}.",
        f"- Unit normalization: {amount_meta['unit_note']}",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long ZZ500 / short HS300; ratio is ZZ500/HS300; spread return is ZZ500 pct_change minus HS300 pct_change.",
        "- T close amount state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Amount features use own-MA relative values or pair-relative ratios; pair amount is ZZ500 relative amount / HS300 relative amount.",
        "- Entry staging and momentum decay are off; Layer 7 volhot remains active as the baseline.",
        "- Result status: quasi-formal, because amount data comes from V7.7 external fallback while prices use close-only official cache.",
        "",
        "## Amount Grid",
        f"- windows: {AMOUNT_WINDOWS}",
        f"- high thresholds: {HIGH_THRESHOLDS}",
        f"- low thresholds: {LOW_THRESHOLDS}",
        f"- confirm days: {CONFIRM_DAYS}",
        f"- scales: {AMOUNT_SCALES}",
        "",
        "## Baselines",
        comparison_table(window_metrics[window_metrics["amount_enabled"] == False], len(LINES)),
        "",
        "## Full+5Y Non-Underperformance Candidates",
        comparison_table(strict_pass, 20) if not strict_pass.empty else "No amount candidate passed full+5Y non-underperformance.",
        "",
        "## DD-First Candidates Loss <= 1pp",
        comparison_table(loss_passes[1.0], 20) if not loss_passes[1.0].empty else "No amount candidate passed loss<=1pp with DD improvement.",
        "",
        "## Width Summary",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        f"Layer 9 completed with decision `{decision}`. If not promoted, next layer continues from Layer 7 volhot carry lines.",
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

    git_status_after = base.git_text(["status", "--short"])
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "ZZ500/HS300 spread Layer 9 amount",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz500_hs300_spread_layer7_overheat.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": git_status_after,
        "scan_type": "fresh_layer9_amount_after_l7_volhot",
        "formal_status": "quasi_formal_price_index_close_to_close_with_eastmoney_amount",
        "parameter_group": "amount_relative_ma_filter_after_layer7_volhot",
        "baseline": {"inputs": LINES, "pass_rule": "compare every amount candidate with same-line amount_off Layer 7 volhot baseline"},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close amount state -> T+1 close-to-close return",
            "direction": "long ZZ500 / short HS300",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "data_snapshot": {
            "price_source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "amount_source": amount_meta,
            "formal_price": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "aligned_amount": {
                "rows": int(len(complete_amount_rows)),
                "start": str(complete_amount_rows.index.min().date()),
                "end": str(complete_amount_rows.index.max().date()),
            },
            "publication_dates": {"HS300": base.HS300_PUBLICATION_DATE, "ZZ500": base.ZZ500_PUBLICATION_DATE},
            "ratio": "ZZ500 / HS300",
            "return_stream": "ZZ500 pct_change - HS300 pct_change",
            "pair_amount_feature": "ZZ500 amount relative-to-MA / HS300 amount relative-to-MA",
        },
        "amount_implementation": "prior-row amount feature trigger; final exposure multiplier and turnover/cost recomputed",
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
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "ZZ500/HS300 spread Layer 9 amount" --parameter-group "amount_relative_ma_filter_after_layer7_volhot" --repo . --entrypoint "scan_adk_zz500_hs300_spread_layer9_amount.py" --date 2026-06-12 --slug "adk_zz500_hs300_spread_long_only_v77_adk_spread_layer9_amount_after_l7_volhot"',
                'python -m py_compile "scan_adk_zz500_hs300_spread_layer9_amount.py"',
                'git diff --check -- "scan_adk_zz500_hs300_spread_layer9_amount.py"',
                'python "scan_adk_zz500_hs300_spread_layer9_amount.py"',
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
        "amount_feature",
        "amount_window",
        "amount_threshold",
        "confirm_days",
        "amount_scale",
        "amount_days_full",
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
    print(f"AMOUNT={amount_meta}")
    print(f"DECISION={decision} STABILITY={stability_label}")
    print(
        "FULL_PASS_COUNT="
        f"{len(full_pass)} STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)} "
        f"LOSS0P5_COUNT={len(loss_passes[0.5])} LOSS1_COUNT={len(loss_passes[1.0])} "
        f"LOSS2_COUNT={len(loss_passes[2.0])} LOSS3_COUNT={len(loss_passes[3.0])}"
    )
    print("BASELINES")
    print(window_metrics[window_metrics.amount_enabled == False][display_cols].to_string(index=False))
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

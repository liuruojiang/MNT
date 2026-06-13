"""Layer 8 first-entry staging diagnostic for long CYB / short ZZ500.

Layer 7 promoted width-supported volhot candidates, so this layer uses those
Layer 7 carry lines as the baseline. The local official cache has close prices
only, so the add-on trigger is a close-to-close pullback proxy, not a formal
bearish-candle test.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_zz500_spread_layer2_score_abs_filter as l2
import scan_adk_cyb_zz500_spread_layer5_momentum_decay as l5
import scan_adk_cyb_zz500_spread_layer7_overheat as l7
import scan_adk_cyb_zz500_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_cyb_zz500_spread_long_only_v77_adk_spread_layer8_entry_staging_close_proxy_after_l7_volhot"

LINES = [
    {
        **l7.LINES[0],
        "line": "return_nav3",
        "line_role": "main_return_watchlist",
        "layer7_candidate": "l7_return_nav3_volhot_w20_thr26_scale0p75",
        "overlay_kind": "volhot",
        "param_a": 20.0,
        "param_b": 0.26,
        "param_c": 0.75,
    },
    {
        **l7.LINES[4],
        "line": "defensive_nav3",
        "line_role": "defensive_preferred",
        "layer7_candidate": "l7_defensive_nav3_volhot_w40_thr26_scale0",
        "overlay_kind": "volhot",
        "param_a": 40.0,
        "param_b": 0.26,
        "param_c": 0.00,
    },
    {
        **l7.LINES[3],
        "line": "defensive_nav4",
        "line_role": "defensive_confirmation",
        "layer7_candidate": "l7_defensive_nav4_volhot_w20_thr26_scale0p5",
        "overlay_kind": "volhot",
        "param_a": 20.0,
        "param_b": 0.26,
        "param_c": 0.50,
    },
    {
        **l7.LINES[1],
        "line": "primary_nav3",
        "line_role": "primary_width_watchlist",
        "layer7_candidate": "l7_primary_nav3_volhot_w40_thr26_scale0p5",
        "overlay_kind": "volhot",
        "param_a": 40.0,
        "param_b": 0.26,
        "param_c": 0.50,
    },
    {
        **l7.LINES[2],
        "line": "confirm_nav3",
        "line_role": "same_patch_confirmation",
        "layer7_candidate": "l7_confirm_nav3_volhot_w30_thr26_scale0p25",
        "overlay_kind": "volhot",
        "param_a": 30.0,
        "param_b": 0.26,
        "param_c": 0.25,
    },
]

ENTRY_INITIAL_FRACTIONS = [0.25, 0.50, 0.75]
ENTRY_PULLBACK_SOURCES = ["cyb_down_close", "ratio_down_close", "spread_return_negative"]
ENTRY_MAX_WAITS = [0, 3, 5, 10]
LOSS_TIERS = [0.5, 1.0, 2.0, 3.0]
WINDOW_SEGMENTS = ["full", "last_10y", "last_5y", "last_3y", "last_1y"]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def raw_cache_snapshot(mod: object) -> dict[str, object]:
    raw_cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID)
    raw_zz500 = mod._load_cn_official_cache(mod.CN_DK_ZZ500_SECID)
    required_ohlc = ["open", "high", "low", "close"]
    return {
        "cyb_columns": list(raw_cyb.columns),
        "zz500_columns": list(raw_zz500.columns),
        "has_true_ohlc": bool(
            all(col in raw_cyb.columns for col in required_ohlc)
            and all(col in raw_zz500.columns for col in required_ohlc)
        ),
        "cyb_rows": int(len(raw_cyb)),
        "cyb_start": str(raw_cyb.index.min().date()),
        "cyb_end": str(raw_cyb.index.max().date()),
        "zz500_rows": int(len(raw_zz500)),
        "zz500_start": str(raw_zz500.index.min().date()),
        "zz500_end": str(raw_zz500.index.max().date()),
    }


def pullback_exec_signal(panel: pd.DataFrame, source: str) -> pd.Series:
    if source == "cyb_down_close":
        raw = panel["CYB"].diff() < 0
    elif source == "ratio_down_close":
        raw = panel["ratio"].diff() < 0
    elif source == "spread_return_negative":
        raw = panel["spread_return"] < 0
    else:
        raise ValueError(f"unknown pullback source: {source}")
    return raw.shift(1, fill_value=False).astype(bool)


def layer7_base_returns(
    panel: pd.DataFrame,
    line: dict[str, object],
    scores: dict[str, pd.Series],
    r2s: dict[str, pd.Series],
    abs_bias: dict[int, pd.Series],
) -> pd.DataFrame:
    l4_frame = l5.l4_base_frame(panel, line, scores, r2s, abs_bias)
    d = l7.apply_overlay(l4_frame, str(line["overlay_kind"]), l7.params_for(line))
    d["layer7_weight"] = d["weight"]
    return d


def apply_entry_staging(
    base_df: pd.DataFrame,
    panel: pd.DataFrame,
    enabled: bool,
    pullback_source: str,
    initial_fraction: float,
    max_wait_days: int,
) -> pd.DataFrame:
    d = base_df.copy()
    d = d.join(panel[["CYB", "ZZ500", "ratio"]], how="left")
    pullback = pullback_exec_signal(panel.reindex(d.index), pullback_source)
    base_weight = d["layer7_weight"].astype(float)
    active = base_weight.abs() > 1e-12

    if not enabled:
        stage_mult = pd.Series(1.0, index=d.index)
        stage_on = pd.Series(False, index=d.index)
        pending_on = pd.Series(False, index=d.index)
        add_on_day = pd.Series(False, index=d.index)
        entry_day = active & ~active.shift(1, fill_value=False)
    else:
        mult_values: list[float] = []
        stage_values: list[bool] = []
        pending_values: list[bool] = []
        add_values: list[bool] = []
        pending = False
        wait_days = 0
        prev_active = False
        for is_active, did_pullback in zip(active.astype(bool), pullback.astype(bool)):
            if not is_active:
                pending = False
                wait_days = 0
                mult = 1.0
                staged = False
                add_now = False
            elif not prev_active:
                pending = True
                wait_days = 0
                mult = float(initial_fraction)
                staged = initial_fraction < 1.0
                add_now = False
            elif pending:
                wait_days += 1
                force_add = max_wait_days > 0 and wait_days >= max_wait_days
                if bool(did_pullback) or force_add:
                    pending = False
                    mult = 1.0
                    staged = False
                    add_now = True
                else:
                    mult = float(initial_fraction)
                    staged = initial_fraction < 1.0
                    add_now = False
            else:
                mult = 1.0
                staged = False
                add_now = False
            mult_values.append(mult)
            stage_values.append(staged and is_active)
            pending_values.append(pending and is_active)
            add_values.append(add_now and is_active)
            prev_active = bool(is_active)

        stage_mult = pd.Series(mult_values, index=d.index)
        stage_on = pd.Series(stage_values, index=d.index)
        pending_on = pd.Series(pending_values, index=d.index)
        add_on_day = pd.Series(add_values, index=d.index)
        entry_day = active & ~active.shift(1, fill_value=False)

    final_weight = base_weight * stage_mult
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
            "layer7_weight": base_weight,
            "stage_mult": stage_mult,
            "stage_on": stage_on.astype(int),
            "pending_on": pending_on.astype(int),
            "add_on_day": add_on_day.astype(int),
            "entry_day": entry_day.astype(int),
            "pullback_exec": pullback.astype(int),
            "overlay_on": d["overlay_on"],
            "nav_on": d["nav_on"],
            "score": d["score"],
            "spread_return": d["spread_return"],
            "ratio": d["ratio"],
            "CYB": d["CYB"],
            "ZZ500": d["ZZ500"],
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in LINES:
        rows.append(
            {
                **line,
                "candidate": f"l8_{line['line']}_entry_off",
                "entry_enabled": False,
                "pullback_source": "off",
                "initial_fraction": 1.0,
                "max_wait_days": 0,
            }
        )
        for source in ENTRY_PULLBACK_SOURCES:
            for fraction in ENTRY_INITIAL_FRACTIONS:
                for max_wait in ENTRY_MAX_WAITS:
                    rows.append(
                        {
                            **line,
                            "candidate": (
                                f"l8_{line['line']}_{source}"
                                f"_init{fmt_num(fraction)}_wait{max_wait}"
                            ),
                            "entry_enabled": True,
                            "pullback_source": source,
                            "initial_fraction": fraction,
                            "max_wait_days": max_wait,
                        }
                    )
    return rows


def extra_metrics_for_segment(result: pd.DataFrame, years: int | None) -> dict[str, float]:
    if years is None:
        d = result.copy()
    else:
        cutoff = result.index.max() - pd.DateOffset(years=years)
        d = result.loc[result.index >= cutoff].copy()
    if d.empty:
        return {
            "entry_days": 0.0,
            "stage_days": 0.0,
            "pending_days": 0.0,
            "add_days": 0.0,
            "pullback_exec_days": 0.0,
            "avg_active_stage_mult": 0.0,
            "overlay_days": 0.0,
            "nav_days": 0.0,
        }
    active = d["layer7_weight"].abs() > 1e-12
    return {
        "entry_days": float(d["entry_day"].sum()),
        "stage_days": float(d["stage_on"].sum()),
        "pending_days": float(d["pending_on"].sum()),
        "add_days": float(d["add_on_day"].sum()),
        "pullback_exec_days": float(((d["pullback_exec"] > 0) & active).sum()),
        "avg_active_stage_mult": float(d.loc[active, "stage_mult"].mean()) if bool(active.any()) else 0.0,
        "overlay_days": float(d["overlay_on"].sum()),
        "nav_days": float(d["nav_on"].sum()),
    }


def add_baselines_and_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["entry_enabled"] == False].set_index("line")
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
    out["pass_full_ann_dd"] = (
        (out["entry_enabled"] == True)
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
            (out["entry_enabled"] == True)
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
    source = wm[wm["entry_enabled"] == True]
    for pass_col in pass_cols:
        for (line, pullback_source), group in source.groupby(["line", "pullback_source"]):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": pass_col,
                        "line": line,
                        "pullback_source": pullback_source,
                        "pass_count": 0,
                        "initial_fraction_count": 0,
                        "max_wait_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "best_stage_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(len(passed) >= 3 and passed["initial_fraction"].nunique() >= 2)
            rows.append(
                {
                    "pass_rule": pass_col,
                    "line": line,
                    "pullback_source": pullback_source,
                    "pass_count": int(len(passed)),
                    "initial_fraction_count": int(passed["initial_fraction"].nunique()),
                    "max_wait_count": int(passed["max_wait_days"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "best_full_ann_loss_pp": float(best["full_ann_loss_pp"]),
                    "best_full_dd_improve_pp": float(best["full_dd_improve_pp"]),
                    "best_5y_ann_return": float(best["ann_return_last_5y"]),
                    "best_5y_max_dd": float(best["max_dd_last_5y"]),
                    "best_stage_days": float(best["stage_days_full"]),
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
        overlay_on = d["overlay_on"].astype(float) > 0
        stage_on = d["stage_on"].astype(float) > 0
        nav_on = d["nav_on"].astype(float) > 0
        masks = {
            "nav0_volhot0_stage0": ~nav_on & ~overlay_on & ~stage_on,
            "nav1_volhot0_stage0": nav_on & ~overlay_on & ~stage_on,
            "nav0_volhot1_stage0": ~nav_on & overlay_on & ~stage_on,
            "nav1_volhot1_stage0": nav_on & overlay_on & ~stage_on,
            "nav0_volhot0_stage1": ~nav_on & ~overlay_on & stage_on,
            "nav1_volhot0_stage1": nav_on & ~overlay_on & stage_on,
            "nav0_volhot1_stage1": ~nav_on & overlay_on & stage_on,
            "nav1_volhot1_stage1": nav_on & overlay_on & stage_on,
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
    cols = ["candidate", "line", "pullback_source", "initial_fraction", "max_wait_days", "stage_days_full"]
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
        if (
            col.startswith("ann_return_")
            or col.startswith("max_dd_")
            or col.startswith("base_ann_return_")
            or col.startswith("base_max_dd_")
        ):
            display[col] = display[col].map(lambda x: pct(float(x)))
        elif col.endswith("_ann_loss_pp"):
            display[col] = display[col].map(lambda x: f"{-float(x):+.2f}pp")
        elif col.endswith("_dd_improve_pp"):
            display[col] = display[col].map(lambda x: f"{float(x):+.2f}pp")
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, cyb, zz500, panel = l2.load_panel()
    cache_snapshot = raw_cache_snapshot(mod)
    scores, r2s, abs_bias = l2.precompute(panel)
    base_by_line = {str(line["line"]): layer7_base_returns(panel, line, scores, r2s, abs_bias) for line in LINES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    grid = make_grid()
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    daily_parts: list[pd.DataFrame] = []

    for cand in grid:
        result = apply_entry_staging(
            base_by_line[str(cand["line"])],
            panel,
            bool(cand["entry_enabled"]),
            str(cand["pullback_source"]) if bool(cand["entry_enabled"]) else "cyb_down_close",
            float(cand["initial_fraction"]),
            int(cand["max_wait_days"]),
        )
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["line"] = cand["line"]
        daily["pullback_source"] = cand["pullback_source"]
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
                "entry_days",
                "stage_days",
                "pending_days",
                "add_days",
                "pullback_exec_days",
                "avg_active_stage_mult",
                "overlay_days",
                "nav_days",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)
    overlap = state_overlap_summary(daily_all)

    full_pass = window_metrics[(window_metrics["entry_enabled"] == True) & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[(window_metrics["entry_enabled"] == True) & window_metrics["pass_full_5y_ann_dd"]].sort_values(
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

    if strict_pass.empty:
        carry = window_metrics[window_metrics["entry_enabled"] == False].copy()
        diagnostic = loss_passes[1.0].sort_values(
            ["full_dd_improve_pp", "ann_return_full"],
            ascending=[False, False],
        ).groupby("line").head(1)
        carry = pd.concat([carry, diagnostic], ignore_index=True).drop_duplicates("candidate")
        decision = "layer8_entry_staging_close_proxy_complete_not_promoted"
        stability = "entry_staging_close_proxy_rejected_carry_layer7_volhot"
    else:
        carry = strict_pass.sort_values(
            ["line", "full_dd_improve_pp", "last_5y_dd_improve_pp", "ann_return_full"],
            ascending=[True, False, False, False],
        ).groupby("line").head(1)
        decision = "layer8_entry_staging_close_proxy_complete_promoted"
        stability = "entry_staging_close_proxy_width_supported_full_5y_nonunderperformance"

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    overlap.to_csv(RUN_DIR / "state_overlap_summary.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# CYB/ZZ500 Layer 8 First-Entry Staging Close Proxy",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        f"- decision: `{decision}`",
        f"- stability: `{stability}`",
        "",
        "## Research Question",
        "Test first-entry staged exposure after promoted Layer 7 volhot, using Layer 7 carry lines as the baseline.",
        "",
        "## Result Status",
        "- `diagnostic_close_proxy`: true OHLC candles are unavailable in the local official cache, so this is not a formal bearish-candle conclusion.",
        f"- raw CYB columns: {cache_snapshot['cyb_columns']}",
        f"- raw ZZ500 columns: {cache_snapshot['zz500_columns']}",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
        "",
        "## Data Snapshot",
        f"- CYB publication date: {base.CYB_PUBLICATION_DATE}; local rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start rule: latest actual index publication date among the two legs.",
        "- Adjustment mode: price index close from local official cache, no total-return substitution.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long CYB / short ZZ500; ratio is CYB/ZZ500; spread return is CYB pct_change minus ZZ500 pct_change.",
        "- T close signal/state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Entry staging applies only on a fresh active entry. Pullback proxy is observed at T close and shifted to next execution row.",
        "- Amount and volume filters remain off. Volhot remains on from the Layer 7 decision.",
        "",
        "## Entry Staging Grid",
        f"- initial fractions: {ENTRY_INITIAL_FRACTIONS}",
        f"- close-only pullback proxies: {ENTRY_PULLBACK_SOURCES}",
        f"- max wait days: {ENTRY_MAX_WAITS}; `0` means wait indefinitely until the selected pullback proxy.",
        "",
        "## Baselines",
        comparison_table(window_metrics[window_metrics["entry_enabled"] == False], len(LINES)),
        "",
        "## Full+5Y Non-Underperformance Candidates",
        comparison_table(strict_pass, 20) if not strict_pass.empty else "No entry-staging candidate passed full+5Y non-underperformance.",
        "",
        "## DD-First Candidates Loss <= 1pp",
        comparison_table(loss_passes[1.0], 20) if not loss_passes[1.0].empty else "No entry-staging candidate passed loss<=1pp with DD improvement.",
        "",
        "## Width Summary",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        f"Layer 8 completed with decision `{decision}`. Stop for user review before amount/volume or final ridge layers.",
        "",
        "## Next-Layer Carry Candidates",
        comparison_table(carry, 10) if not carry.empty else "No carry candidate selected.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "CYB/ZZ500 spread Layer 8 entry staging",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_cyb_zz500_spread_layer7_overheat.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "fresh_layer8_entry_staging_close_proxy_after_l7_volhot",
        "result_status": "diagnostic_close_proxy_no_true_ohlc",
        "parameter_group": "first_entry_staging_close_proxy_after_l7_volhot",
        "baseline": {"lines": LINES, "pass_rule": "compare every staging candidate with same-line entry_off"},
        "candidate_grid": make_grid(),
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "raw_cache": cache_snapshot,
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
        "entry_staging_implementation": "fresh active entry starts at initial_fraction; add to full after prior-row close-proxy pullback or max_wait; final turnover/cost recomputed",
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
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "CYB/ZZ500 spread Layer 8 entry staging" --parameter-group "first_entry_staging_close_proxy_after_l7_volhot" --repo . --entrypoint "scan_adk_cyb_zz500_spread_layer8_entry_staging.py" --date 2026-06-12 --slug "adk_cyb_zz500_spread_long_only_v77_adk_spread_layer8_entry_staging_close_proxy_after_l7_volhot"',
                'python -m py_compile "scan_adk_cyb_zz500_spread_layer8_entry_staging.py"',
                'git diff --check -- "scan_adk_cyb_zz500_spread_layer8_entry_staging.py"',
                'python "scan_adk_cyb_zz500_spread_layer8_entry_staging.py"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "{RUN_DIR}" --decision "{decision}" --stability-label "{stability}"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict "{RUN_DIR}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(f"RAW_COLS CYB={cache_snapshot['cyb_columns']} ZZ500={cache_snapshot['zz500_columns']} HAS_TRUE_OHLC={cache_snapshot['has_true_ohlc']}")
    print(
        "FULL_PASS_COUNT="
        f"{len(full_pass)} STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)} "
        f"LOSS0P5_COUNT={len(loss_passes[0.5])} LOSS1_COUNT={len(loss_passes[1.0])} "
        f"LOSS2_COUNT={len(loss_passes[2.0])} LOSS3_COUNT={len(loss_passes[3.0])}"
    )
    base_cols = [
        "line",
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
    ]
    result_cols = [
        "candidate",
        "line",
        "pullback_source",
        "initial_fraction",
        "max_wait_days",
        "stage_days_full",
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
    ]
    print("BASELINES")
    print(window_metrics[window_metrics.entry_enabled == False][base_cols].to_string(index=False))
    print("STRICT_PASS_TOP")
    print(strict_pass[result_cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    print("LOSS1_TOP")
    print(loss_passes[1.0][result_cols].head(20).to_string(index=False) if not loss_passes[1.0].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

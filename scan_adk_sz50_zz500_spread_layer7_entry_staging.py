"""Layer 7 close-proxy first-entry staging after Layer 6 overheat for SZ50/ZZ500.

The local official index cache only has close prices, so this layer is
quasi-formal. It tests first-entry staging with close-to-close pullback proxies:
enter a fraction of the final Layer 6 exposure on a fresh entry, then add the
rest after a shifted pullback proxy or a maximum wait.
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


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_sz50_zz500_spread_long_only_v77_adk_spread_layer7_entry_staging_after_l6_overheat"

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

ENTRY_INITIAL_FRACTIONS = [0.25, 0.50, 0.75]
ENTRY_PULLBACK_SOURCES = ["sz50_down_close", "ratio_down_close", "spread_return_negative"]
ENTRY_MAX_WAITS = [0, 3, 5, 10]
LOSS_TIERS = [0.5, 1.0, 2.0]


def fmt_num(value: float) -> str:
    sign = "m" if value < 0 else ""
    return sign + f"{abs(value):g}".replace(".", "p")


def layer6_base_returns(panel: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    l5_base = l6.layer5_base_returns(panel, line)
    overheat_params = {
        "score_threshold": float(line["overheat_param_a"]),
        "window": float(line["overheat_param_a"]),
        "threshold": float(line["overheat_param_b"]),
        "scale": float(line["overheat_param_c"]),
    }
    d = l6.apply_overlay(l5_base, str(line["overheat_kind"]), overheat_params).copy()
    extras = panel[["SZ50", "ZZ500", "ratio"]].reindex(d.index)
    d = pd.concat([d, extras], axis=1)
    d["layer6_weight"] = d["weight"]
    return d


def entry_multiplier(d: pd.DataFrame, source: str, initial_fraction: float, max_wait: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    if source == "sz50_down_close":
        pullback = d["SZ50"].diff() < 0
    elif source == "ratio_down_close":
        pullback = d["ratio"].diff() < 0
    elif source == "spread_return_negative":
        pullback = d["spread_return"] < 0
    else:
        raise ValueError(source)
    pullback_exec = pullback.shift(1, fill_value=False).astype(bool)
    mult: list[float] = []
    pending_flags: list[bool] = []
    add_flags: list[bool] = []
    pending = False
    wait_days = 0
    prev_active = False
    for active, did_pullback in zip(d["layer6_weight"].abs() > 1e-12, pullback_exec):
        if not active:
            pending = False
            wait_days = 0
            prev_active = False
            mult.append(0.0)
            pending_flags.append(False)
            add_flags.append(False)
            continue
        fresh_entry = not prev_active
        if fresh_entry:
            pending = True
            wait_days = 0
            mult.append(float(initial_fraction))
            pending_flags.append(True)
            add_flags.append(False)
        elif pending:
            wait_days += 1
            force_add = max_wait > 0 and wait_days >= max_wait
            if bool(did_pullback) or force_add:
                pending = False
                mult.append(1.0)
                pending_flags.append(False)
                add_flags.append(True)
            else:
                mult.append(float(initial_fraction))
                pending_flags.append(True)
                add_flags.append(False)
        else:
            mult.append(1.0)
            pending_flags.append(False)
            add_flags.append(False)
        prev_active = True
    return (
        pd.Series(mult, index=d.index),
        pd.Series(pending_flags, index=d.index),
        pd.Series(add_flags, index=d.index),
    )


def apply_entry_staging(
    base_df: pd.DataFrame,
    source: str | None,
    initial_fraction: float | None,
    max_wait: int | None,
) -> pd.DataFrame:
    d = base_df.copy()
    if source is None:
        mult = pd.Series(1.0, index=d.index)
        pending = pd.Series(False, index=d.index)
        add_day = pd.Series(False, index=d.index)
    else:
        mult, pending, add_day = entry_multiplier(d, source, float(initial_fraction), int(max_wait))
    final_weight = d["layer6_weight"] * mult
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = final_weight * d["spread_return"].fillna(0.0)
    ret = gross_return - cost
    staged = (d["layer6_weight"].abs() > 1e-12) & (mult < 1.0 - 1e-12)
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "layer6_weight": d["layer6_weight"],
            "entry_mult": mult,
            "entry_staged": staged.astype(int),
            "entry_pending": pending.astype(int),
            "entry_add_day": add_day.astype(int),
            "score": d["score"],
            "decay_on": d["decay_on"],
            "overlay_on": d["overlay_on"],
            "spread_return": d["spread_return"],
            "ratio": d["ratio"],
            "SZ50": d["SZ50"],
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
                "candidate": f"l7_{line['line']}_entry_off",
                "entry_enabled": False,
                "initial_fraction": 1.0,
                "pullback_source": "",
                "max_wait": 0,
            }
        )
        for initial_fraction in ENTRY_INITIAL_FRACTIONS:
            for source in ENTRY_PULLBACK_SOURCES:
                for max_wait in ENTRY_MAX_WAITS:
                    wait_tag = "no_force" if max_wait == 0 else f"maxwait{max_wait}"
                    rows.append(
                        {
                            **line,
                            "candidate": f"l7_{line['line']}_entry{fmt_num(initial_fraction)}_{source}_{wait_tag}",
                            "entry_enabled": True,
                            "initial_fraction": initial_fraction,
                            "pullback_source": source,
                            "max_wait": max_wait,
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
            "entry_staged_days": 0.0,
            "entry_add_days": 0.0,
            "avg_entry_mult_active": 1.0,
        }
    active = d["layer6_weight"].abs() > 1e-12
    return {
        "entry_staged_days": float(d["entry_staged"].sum()),
        "entry_add_days": float(d["entry_add_day"].sum()),
        "avg_entry_mult_active": float(d.loc[active, "entry_mult"].mean()) if active.any() else 1.0,
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
    ]:
        out[f"base_{col}"] = out["line"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100.0
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100.0
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100.0
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100.0
    out["cost_delta"] = out["cost_total_full"] - out["base_cost_total_full"]
    out["pass_full_ann_dd"] = (
        (out["entry_enabled"] == True)
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
            (out["entry_enabled"] == True)
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["fivey_dd_improve_pp"] >= -1e-12)
        )
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    pass_cols = ["pass_full_ann_dd", "pass_full_and_5y"] + [f"pass_loss_le_{str(t).replace('.', 'p')}pp" for t in LOSS_TIERS]
    source = wm[wm["entry_enabled"] == True]
    for pass_col in pass_cols:
        for line, group in source.groupby("line"):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": pass_col,
                        "line": line,
                        "pass_count": 0,
                        "initial_fraction_count": 0,
                        "pullback_source_count": 0,
                        "max_wait_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "best_entry_staged_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            rows.append(
                {
                    "pass_rule": pass_col,
                    "line": line,
                    "pass_count": int(len(passed)),
                    "initial_fraction_count": int(passed["initial_fraction"].nunique()),
                    "pullback_source_count": int(passed["pullback_source"].nunique()),
                    "max_wait_count": int(passed["max_wait"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                    "best_full_dd_improve_pp": best["full_dd_improve_pp"],
                    "best_5y_ann_return": best["ann_return_last_5y"],
                    "best_5y_max_dd": best["max_dd_last_5y"],
                    "best_entry_staged_days": best["entry_staged_days_full"],
                    "patch_like": bool(
                        len(passed) >= 3
                        and passed["initial_fraction"].nunique() >= 2
                        and passed["pullback_source"].nunique() >= 1
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
    cols = ["candidate", "line", "initial_fraction", "pullback_source", "max_wait", "entry_staged_days_full"]
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
    base_by_line = {str(line["line"]): layer6_base_returns(panel, line) for line in LINES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = make_grid()
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    daily_parts: list[pd.DataFrame] = []

    for cand in grid:
        result = apply_entry_staging(
            base_by_line[str(cand["line"])],
            None if not bool(cand["entry_enabled"]) else str(cand["pullback_source"]),
            None if not bool(cand["entry_enabled"]) else float(cand["initial_fraction"]),
            None if not bool(cand["entry_enabled"]) else int(cand["max_wait"]),
        )
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["line"] = cand["line"]
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
                "entry_staged_days",
                "entry_add_days",
                "avg_entry_mult_active",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)

    full_pass = window_metrics[(window_metrics["entry_enabled"] == True) & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[(window_metrics["entry_enabled"] == True) & window_metrics["pass_full_and_5y"]].sort_values(
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
        "entry_enabled",
        "initial_fraction",
        "pullback_source",
        "max_wait",
        "entry_staged_days_full",
        "entry_add_days_full",
        "avg_entry_mult_active_full",
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
    baseline = window_metrics[window_metrics["entry_enabled"] == False][display_cols]
    record_lines = [
        "# SZ50/ZZ500 Layer 7 First-Entry Staging",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer7_entry_staging_complete_pending_user_review`",
        "- stability: `close_proxy_entry_staging_review`",
        "",
        "## Research Question",
        "Test first-entry staging after Layer 6 scorehot. Because local index caches only include close prices, this is a close-to-close pullback proxy and not a formal bearish-candle test.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
        "",
        "## Data Snapshot",
        f"- SZ50 publication date: {base.SZ50_PUBLICATION_DATE}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        f"- SZ50 rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}; columns available after loader: {list(sz50.columns)}.",
        f"- ZZ500 rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}; columns available after loader: {list(zz500.columns)}.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long SZ50 / short ZZ500; ratio is SZ50/ZZ500; spread return is SZ50 pct_change minus ZZ500 pct_change.",
        "- T close signal/state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Entry staging: fresh entry uses initial fraction, then adds remaining exposure after shifted close-proxy pullback or max wait.",
        "- OHLC open/high/low candles are unavailable in the loader output, so the result status is quasi-formal close-proxy research.",
        "",
        "## Entry Grid",
        f"- initial_fraction: {ENTRY_INITIAL_FRACTIONS}",
        f"- pullback_source: {ENTRY_PULLBACK_SOURCES}",
        f"- max_wait: {ENTRY_MAX_WAITS}; 0 means no forced add.",
        "",
        "## Baselines",
        baseline.to_markdown(index=False),
        "",
        "## Full+5Y Non-Underperformance Candidates",
        window_table(strict_pass, 20) if not strict_pass.empty else "No entry candidate passed full+5Y non-underperformance.",
        "",
        "## DD-First Candidates Loss <= 1pp",
        window_table(loss_passes[1.0], 20) if not loss_passes[1.0].empty else "No entry candidate passed loss<=1pp with DD improvement.",
        "",
        "## DD-First Candidates Loss <= 2pp",
        window_table(loss_passes[2.0], 20) if not loss_passes[2.0].empty else "No entry candidate passed loss<=2pp with DD improvement.",
        "",
        "## Width Summary",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 7 completed and stopped for user review before amount/volume filters.",
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
        "subsystem": "SZ50/ZZ500 spread Layer 7 entry staging",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_sz50_zz500_spread_layer6_overheat.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": git_status_after,
        "scan_type": "fresh_layer7_close_proxy_entry_staging",
        "result_status": "quasi-formal_close_proxy_price_index_research",
        "parameter_group": "first_entry_initial_fraction_pullback_proxy_max_wait",
        "baseline": {
            "lines": LINES,
            "pass_rule": "compare every entry candidate with same-line entry_off",
            "ohlc_available": False,
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
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "publication_dates": {"SZ50": base.SZ50_PUBLICATION_DATE, "ZZ500": base.ZZ500_PUBLICATION_DATE},
            "available_price_fields": {"SZ50": list(sz50.columns), "ZZ500": list(zz500.columns)},
        },
        "entry_implementation": "fresh entry initial fraction, add after shifted close-proxy pullback or max wait; final turnover/cost recomputed",
        "decision": "layer7_entry_staging_complete_pending_user_review",
        "stability_label": "close_proxy_entry_staging_review",
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
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "SZ50/ZZ500 spread Layer 7 entry staging" --parameter-group "first_entry_initial_fraction_pullback_proxy_max_wait" --repo . --entrypoint "scan_adk_sz50_zz500_spread_layer7_entry_staging.py" --date 2026-06-12 --slug "adk_sz50_zz500_spread_long_only_v77_adk_spread_layer7_entry_staging_after_l6_overheat"',
                'python -m py_compile "scan_adk_sz50_zz500_spread_layer7_entry_staging.py"',
                'python "scan_adk_sz50_zz500_spread_layer7_entry_staging.py"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "{RUN_DIR}" --decision "layer7_entry_staging_complete_pending_user_review" --stability-label "close_proxy_entry_staging_review"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict "{RUN_DIR}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
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

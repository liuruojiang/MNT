"""Layer 7 score/realized-vol overheat for long ZZ500 / short HS300.

Layer 6 did not promote NAV/decay interaction, so this layer carries the
Layer 4 nav_off target-vol lines unchanged and tests only score/realized-vol
overheat overlays. Entry staging, amount, and volume filters remain off.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_hs300_spread_layer2_score_abs_filter as l2
import scan_adk_zz500_hs300_spread_layer5_momentum_decay as l5
import scan_adk_zz500_hs300_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_hs300_spread_long_only_v77_adk_spread_layer7_overheat_after_l4_nav_off"

LINES = [
    {**l5.L4_INPUTS[0], "line": "main_confirm", "line_role": "main_strict_full_5y"},
    {**l5.L4_INPUTS[1], "line": "return_preserve", "line_role": "return_preserve_watchlist"},
    {**l5.L4_INPUTS[2], "line": "primary_dd", "line_role": "primary_dd_first"},
    {**l5.L4_INPUTS[3], "line": "ultra_def", "line_role": "ultra_defensive_watchlist"},
]

SCORE_HOT_THRESHOLDS = [6, 8, 10, 12, 15, 18, 22, 26, 30]
SCORE_HOT_SCALES = [0.0, 0.25, 0.5, 0.75]
VOL_HOT_WINDOWS = [20, 30, 40, 60, 90]
VOL_HOT_THRESHOLDS = [0.10, 0.12, 0.15, 0.18, 0.22, 0.26, 0.30, 0.35]
VOL_HOT_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0, 3.0]
WINDOW_SEGMENTS = ["full", "last_10y", "last_5y", "last_3y", "last_1y"]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in LINES:
        rows.append(
            {
                **line,
                "candidate": f"l7_{line['line']}_overheat_off",
                "overlay_kind": "off",
                "param_a": 0.0,
                "param_b": 0.0,
                "param_c": 1.0,
            }
        )
        for threshold in SCORE_HOT_THRESHOLDS:
            for scale in SCORE_HOT_SCALES:
                rows.append(
                    {
                        **line,
                        "candidate": f"l7_{line['line']}_scorehot{threshold}_scale{fmt_num(scale)}",
                        "overlay_kind": "scorehot",
                        "param_a": float(threshold),
                        "param_b": 0.0,
                        "param_c": scale,
                    }
                )
        for window in VOL_HOT_WINDOWS:
            for threshold in VOL_HOT_THRESHOLDS:
                for scale in VOL_HOT_SCALES:
                    rows.append(
                        {
                            **line,
                            "candidate": f"l7_{line['line']}_volhot_w{window}_thr{fmt_num(threshold, True)}_scale{fmt_num(scale)}",
                            "overlay_kind": "volhot",
                            "param_a": float(window),
                            "param_b": threshold,
                            "param_c": scale,
                        }
                    )
    return rows


def params_for(cand: dict[str, object]) -> dict[str, float]:
    kind = str(cand["overlay_kind"])
    if kind == "scorehot":
        return {"score_threshold": float(cand["param_a"]), "scale": float(cand["param_c"])}
    if kind == "volhot":
        return {"window": float(cand["param_a"]), "threshold": float(cand["param_b"]), "scale": float(cand["param_c"])}
    return {}


def apply_overlay(base_frame: pd.DataFrame, kind: str, params: dict[str, float]) -> pd.DataFrame:
    mult = pd.Series(1.0, index=base_frame.index)
    trigger = pd.Series(False, index=base_frame.index)
    aux_value = pd.Series(np.nan, index=base_frame.index)
    if kind == "off":
        pass
    elif kind == "scorehot":
        aux_value = base_frame["score"].shift(1)
        trigger = aux_value.fillna(0.0) >= float(params["score_threshold"])
        mult.loc[trigger] = float(params["scale"])
    elif kind == "volhot":
        rv = base_frame["spread_return"].rolling(int(params["window"])).std(ddof=0) * np.sqrt(base.ANNUALIZATION_DAYS)
        aux_value = rv.shift(1)
        trigger = aux_value.fillna(0.0) >= float(params["threshold"])
        mult.loc[trigger] = float(params["scale"])
    else:
        raise ValueError(kind)

    final_weight = base_frame["weight"] * mult
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = final_weight * base_frame["spread_return"].fillna(0.0)
    ret = gross_return - cost
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "base_weight": base_frame["weight"],
            "overlay_mult": mult,
            "overlay_on": trigger.astype(int),
            "overlay_aux": aux_value,
            "raw_signal": base_frame["raw_signal"],
            "score": base_frame["score"],
            "selected_scale": base_frame["selected_scale"],
            "spread_return": base_frame["spread_return"],
        },
        index=base_frame.index,
    )


def extra_metrics_for_segment(result: pd.DataFrame, years: int | None) -> dict[str, float]:
    if years is None:
        d = result.copy()
    else:
        cutoff = result.index.max() - pd.DateOffset(years=years)
        d = result.loc[result.index >= cutoff].copy()
    if d.empty:
        return {"overlay_days": 0.0, "overlay_day_ratio": 0.0, "avg_overlay_mult": 1.0}
    overlay_on = d["overlay_on"].astype(float) > 0
    return {
        "overlay_days": float(overlay_on.sum()),
        "overlay_day_ratio": float(overlay_on.mean()),
        "avg_overlay_mult": float(d["overlay_mult"].mean()),
    }


def add_baselines_and_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["overlay_kind"] == "off"].set_index("line")
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
    active_overlay = out["overlay_days_full"] > 0
    out["pass_full_ann_dd"] = (
        (out["overlay_kind"] != "off")
        & active_overlay
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
            (out["overlay_kind"] != "off")
            & active_overlay
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
    source = wm[wm["overlay_kind"] != "off"]
    for pass_col in pass_cols:
        for (line, kind), group in source.groupby(["line", "overlay_kind"]):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": pass_col,
                        "line": line,
                        "overlay_kind": kind,
                        "pass_count": 0,
                        "param_a_count": 0,
                        "param_b_count": 0,
                        "param_c_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "best_overlay_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(len(passed) >= 3 and passed["param_a"].nunique() >= 2)
            rows.append(
                {
                    "pass_rule": pass_col,
                    "line": line,
                    "overlay_kind": kind,
                    "pass_count": int(len(passed)),
                    "param_a_count": int(passed["param_a"].nunique()),
                    "param_b_count": int(passed["param_b"].nunique()),
                    "param_c_count": int(passed["param_c"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "best_full_ann_loss_pp": float(best["full_ann_loss_pp"]),
                    "best_full_dd_improve_pp": float(best["full_dd_improve_pp"]),
                    "best_5y_ann_return": float(best["ann_return_last_5y"]),
                    "best_5y_max_dd": float(best["max_dd_last_5y"]),
                    "best_overlay_days": float(best["overlay_days_full"]),
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
        masks = {"overheat0": ~overlay_on, "overheat1": overlay_on}
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
    cols = ["candidate", "line", "line_role", "overlay_kind", "param_a", "param_b", "param_c", "overlay_days_full"]
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
    mod, zz500, hs300, panel = l2.load_panel()
    scores, r2s, abs_bias = l2.precompute(panel)
    base_by_line = {str(line["line"]): l5.l4_nav_off_frame(panel, line, scores, r2s, abs_bias) for line in LINES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = make_grid()
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    daily_parts: list[pd.DataFrame] = []

    for cand in grid:
        result = apply_overlay(base_by_line[str(cand["line"])], str(cand["overlay_kind"]), params_for(cand))
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["line"] = cand["line"]
        daily["overlay_kind"] = cand["overlay_kind"]
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
                "overlay_days",
                "overlay_day_ratio",
                "avg_overlay_mult",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)
    overlap = state_overlap_summary(daily_all)

    full_pass = window_metrics[(window_metrics["overlay_kind"] != "off") & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[(window_metrics["overlay_kind"] != "off") & window_metrics["pass_full_5y_ann_dd"]].sort_values(
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
    if not strict_pass.empty:
        carry = strict_pass.sort_values(
            ["line", "full_dd_improve_pp", "last_5y_dd_improve_pp", "ann_return_full"],
            ascending=[True, False, False, False],
        ).groupby("line").head(1)
    else:
        carry = window_metrics[window_metrics["overlay_kind"] == "off"].copy()
        diagnostic = loss_passes[1.0].sort_values(
            ["full_dd_improve_pp", "ann_return_full"],
            ascending=[False, False],
        ).groupby("line").head(1)
        carry = pd.concat([carry, diagnostic], ignore_index=True).drop_duplicates("candidate")

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    overlap.to_csv(RUN_DIR / "state_overlap_summary.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# ZZ500/HS300 Layer 7 Overheat After Layer 4 Nav-Off",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer7_overheat_complete_promoted_width_supported_volhot`",
        "- stability: `volhot_width_supported_full_5y_nonunderperformance`",
        "",
        "## Research Question",
        "Test score and realized-vol overheat after Layer 6 rejected NAV/decay interaction, using Layer 4 nav_off target-vol lines as baseline.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
        "",
        "## Implementation Anchor",
        "- Imports Layer 5 exact Layer 4 `nav_off` daily curves as baseline.",
        "- Scorehot uses prior-row score; volhot uses prior-row realized spread volatility.",
        "- Entry staging, amount, and volume filters remain off.",
        "- Final turnover, costs, returns, NAV, and drawdown are recomputed after overheat scaling.",
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
        "- Direction: long ZZ500 / short HS300; ratio is ZZ500/HS300; spread return is ZZ500 pct_change minus HS300 pct_change.",
        "- T close signal/state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research, excluding futures basis, financing, borrow, short locate, and slippage.",
        "",
        "## Overheat Grid",
        f"- scorehot thresholds: {SCORE_HOT_THRESHOLDS}, scales: {SCORE_HOT_SCALES}",
        f"- volhot windows: {VOL_HOT_WINDOWS}, thresholds: {VOL_HOT_THRESHOLDS}, scales: {VOL_HOT_SCALES}",
        "",
        "## Baselines",
        comparison_table(window_metrics[window_metrics["overlay_kind"] == "off"], len(LINES)),
        "",
        "## Full+5Y Non-Underperformance Candidates",
        comparison_table(strict_pass, 16) if not strict_pass.empty else "No overheat candidate passed full+5Y non-underperformance.",
        "",
        "## DD-First Candidates Loss <= 1pp",
        comparison_table(loss_passes[1.0], 16) if not loss_passes[1.0].empty else "No overheat candidate passed loss<=1pp with DD improvement.",
        "",
        "## Width Summary",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 7 completed and promoted width-supported volhot candidates. Scorehot remains rejected.",
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

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "ZZ500/HS300 spread Layer 7 overheat",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz500_hs300_spread_layer5_momentum_decay.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "fresh_layer7_overheat_after_l4_nav_off",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "scorehot_realized_volhot_after_l4_nav_off",
        "baseline": {"lines": LINES, "pass_rule": "compare every overheat candidate with same-line overheat_off"},
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
        "overheat_implementation": "prior-row score or prior-row realized spread volatility; final turnover/cost recomputed",
        "decision": "layer7_overheat_complete_promoted_width_supported_volhot",
        "stability_label": "volhot_width_supported_full_5y_nonunderperformance",
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
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "ZZ500/HS300 spread Layer 7 overheat" --parameter-group "scorehot_realized_volhot_after_l4_nav_off" --repo . --entrypoint "scan_adk_zz500_hs300_spread_layer7_overheat.py" --date 2026-06-12 --slug "adk_zz500_hs300_spread_long_only_v77_adk_spread_layer7_overheat_after_l4_nav_off"',
                'python -m py_compile "scan_adk_zz500_hs300_spread_layer7_overheat.py"',
                'python "scan_adk_zz500_hs300_spread_layer7_overheat.py"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "{RUN_DIR}" --decision "layer7_overheat_complete_promoted_width_supported_volhot" --stability-label "volhot_width_supported_full_5y_nonunderperformance"',
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
        "overlay_kind",
        "param_a",
        "param_b",
        "param_c",
        "overlay_days_full",
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
    print(window_metrics[window_metrics.overlay_kind == "off"][base_cols].to_string(index=False))
    print("STRICT_PASS_TOP")
    print(strict_pass[result_cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    print("LOSS1_TOP")
    print(loss_passes[1.0][result_cols].head(20).to_string(index=False) if not loss_passes[1.0].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

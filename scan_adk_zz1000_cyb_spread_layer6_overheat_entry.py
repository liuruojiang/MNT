"""Layer 6 overheat and first-entry staging scan for ZZ1000/CYB.

Layer 4 NAV defense and Layer 5 momentum decay were not promoted, so this scan
uses the unchanged Layer 3 target-vol carry lines. It tests three
overheat families plus a close-only first-entry staging diagnostic.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_zz1000_spread_long_only as metric_base
import scan_adk_zz1000_cyb_spread_layer3_target_vol as l3
import scan_adk_zz1000_cyb_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260611_adk_zz1000_cyb_spread_long_only_v77_adk_spread_layer6_overheat_entry_after_l3_target_vol"

LINES = [
    {
        "line": "primary_tv14_vw60_max1p25_db0p05",
        "line_role": "formal_carry",
        "source_line": "primary_s2_abs70_m7",
        "bias_ma": 60,
        "mom_day": 12,
        "weight_end": 2.0,
        "score_threshold": 2.0,
        "abs_ma": 70,
        "abs_threshold": -0.070,
        "target_vol": 0.14,
        "vol_window": 60,
        "max_leverage": 1.25,
        "scale_deadband": 0.05,
        "tv_enabled": True,
    },
    {
        "line": "primary_tv14_vw60_max1p25_db0p10",
        "line_role": "deadband_confirmation",
        "source_line": "primary_s2_abs70_m7",
        "bias_ma": 60,
        "mom_day": 12,
        "weight_end": 2.0,
        "score_threshold": 2.0,
        "abs_ma": 70,
        "abs_threshold": -0.070,
        "target_vol": 0.14,
        "vol_window": 60,
        "max_leverage": 1.25,
        "scale_deadband": 0.10,
        "tv_enabled": True,
    },
    {
        "line": "confirm75_tv14_vw60_max1p25_db0p05",
        "line_role": "width_confirmation",
        "source_line": "confirm_s2_abs75_m7p5",
        "bias_ma": 60,
        "mom_day": 12,
        "weight_end": 2.0,
        "score_threshold": 2.0,
        "abs_ma": 75,
        "abs_threshold": -0.075,
        "target_vol": 0.14,
        "vol_window": 60,
        "max_leverage": 1.25,
        "scale_deadband": 0.05,
        "tv_enabled": True,
    },
    {
        "line": "return_tv16_vw60_max1p25_db0p05",
        "line_role": "return_watchlist",
        "source_line": "primary_s2_abs70_m7",
        "bias_ma": 60,
        "mom_day": 12,
        "weight_end": 2.0,
        "score_threshold": 2.0,
        "abs_ma": 70,
        "abs_threshold": -0.070,
        "target_vol": 0.16,
        "vol_window": 60,
        "max_leverage": 1.25,
        "scale_deadband": 0.05,
        "tv_enabled": True,
    },
]

SCORE_HOT_THRESHOLDS = [20, 30, 40, 50, 60, 80, 100]
SCORE_HOT_SCALES = [0.0, 0.25, 0.5, 0.75]
VOL_HOT_WINDOWS = [20, 30, 40, 60, 90]
VOL_HOT_THRESHOLDS = [0.18, 0.22, 0.26, 0.30, 0.35, 0.40]
VOL_HOT_SCALES = [0.0, 0.25, 0.5, 0.75]
DOWNONLY_TVS = [0.08, 0.10, 0.12, 0.14, 0.16, 0.18]
DOWNONLY_WINDOWS = [20, 30, 40, 60, 90]
DOWNONLY_MIN_SCALES = [0.0, 0.25, 0.5]
ENTRY_PULLBACK_SOURCES = ["zz1000_down_close", "ratio_down_close", "spread_return_negative"]
ENTRY_MAX_WAITS = [0, 3, 5, 10]
ENTRY_INITIAL_FRACTION = 0.5
LOSS_TIERS = [0.5, 1.0, 2.0]


def fmt(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def l3_base_returns(panel: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    sig = l3.line_signal(panel, line)
    d = l3.returns_for(panel, sig, line).copy()
    extra = sig[["score"]].reindex(d.index)
    d = pd.concat([d, extra, panel[["ZZ1000", "CYB", "ratio", "spread_return"]].reindex(d.index)], axis=1).copy()
    d["raw_signal"] = sig["signal"].reindex(d.index).fillna(0.0)
    d["base_weight"] = d["weight"]
    return d


def apply_entry_staging(d: pd.DataFrame, pullback_source: str, max_wait: int) -> pd.Series:
    if pullback_source == "zz1000_down_close":
        pullback = d["ZZ1000"].diff() < 0
    elif pullback_source == "ratio_down_close":
        pullback = d["ratio"].diff() < 0
    elif pullback_source == "spread_return_negative":
        pullback = d["spread_return"] < 0
    else:
        raise ValueError(pullback_source)
    pullback_exec = pullback.shift(1, fill_value=False).astype(bool)
    mult = []
    pending = False
    wait_days = 0
    prev_active = False
    for active, did_pullback in zip(d["base_weight"].abs() > 1e-12, pullback_exec):
        if not active:
            pending = False
            wait_days = 0
            prev_active = False
            mult.append(0.0)
            continue
        fresh_entry = not prev_active
        if fresh_entry:
            pending = True
            wait_days = 0
            mult.append(ENTRY_INITIAL_FRACTION)
        elif pending:
            wait_days += 1
            force_add = max_wait > 0 and wait_days >= max_wait
            if bool(did_pullback) or force_add:
                pending = False
                mult.append(1.0)
            else:
                mult.append(ENTRY_INITIAL_FRACTION)
        else:
            mult.append(1.0)
        prev_active = True
    return pd.Series(mult, index=d.index)


def apply_overlay(base_df: pd.DataFrame, kind: str, params: dict[str, float | str]) -> pd.DataFrame:
    d = base_df.copy()
    mult = pd.Series(1.0, index=d.index)
    trigger = pd.Series(False, index=d.index)
    aux_value = pd.Series(np.nan, index=d.index)
    if kind == "off":
        pass
    elif kind == "scorehot":
        aux_value = d["score"].shift(1)
        trigger = aux_value.fillna(0.0) >= float(params["score_threshold"])
        mult.loc[trigger] = float(params["scale"])
    elif kind == "volhot":
        rv = d["spread_return"].rolling(int(params["window"])).std() * np.sqrt(base.ANNUALIZATION_DAYS)
        aux_value = rv.shift(1)
        trigger = aux_value.fillna(0.0) >= float(params["threshold"])
        mult.loc[trigger] = float(params["scale"])
    elif kind == "downonly_tv":
        rv = d["spread_return"].rolling(int(params["window"])).std() * np.sqrt(base.ANNUALIZATION_DAYS)
        cap = (float(params["target_vol"]) / rv).clip(float(params["min_scale"]), 1.0).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        mult = cap.shift(1).fillna(1.0)
        aux_value = mult
        trigger = mult < 0.999
    elif kind == "entry_stage_proxy":
        mult = apply_entry_staging(d, str(params["pullback_source"]), int(params["max_wait"]))
        aux_value = mult
        trigger = (d["base_weight"].abs() > 1e-12) & (mult < 0.999)
    else:
        raise ValueError(kind)
    final_weight = d["base_weight"] * mult
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = final_weight * d["spread_return"]
    ret = gross_return - cost
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "base_weight": d["base_weight"],
            "overlay_mult": mult,
            "overlay_on": trigger.astype(float),
            "overlay_aux": aux_value,
            "score": d["score"],
            "spread_return": d["spread_return"],
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in LINES:
        rows.append({**line, "candidate": f"l6_{line['line']}_overlay_off", "overlay_kind": "off", "param_a": 0.0, "param_b": 0.0, "param_c": 1.0, "param_s": ""})
        for thr in SCORE_HOT_THRESHOLDS:
            for scale in SCORE_HOT_SCALES:
                rows.append({**line, "candidate": f"l6_{line['line']}_scorehot{thr}_scale{fmt(scale)}", "overlay_kind": "scorehot", "param_a": float(thr), "param_b": 0.0, "param_c": scale, "param_s": ""})
        for window in VOL_HOT_WINDOWS:
            for thr in VOL_HOT_THRESHOLDS:
                for scale in VOL_HOT_SCALES:
                    rows.append({**line, "candidate": f"l6_{line['line']}_volhot_w{window}_thr{fmt(thr, True)}_scale{fmt(scale)}", "overlay_kind": "volhot", "param_a": float(window), "param_b": thr, "param_c": scale, "param_s": ""})
        for tv in DOWNONLY_TVS:
            for window in DOWNONLY_WINDOWS:
                for min_scale in DOWNONLY_MIN_SCALES:
                    rows.append({**line, "candidate": f"l6_{line['line']}_downonly_tv{fmt(tv, True)}_w{window}_min{fmt(min_scale)}", "overlay_kind": "downonly_tv", "param_a": tv, "param_b": float(window), "param_c": min_scale, "param_s": ""})
        for source in ENTRY_PULLBACK_SOURCES:
            for max_wait in ENTRY_MAX_WAITS:
                wait_tag = "no_force" if max_wait == 0 else f"maxwait{max_wait}"
                rows.append({**line, "candidate": f"l6_{line['line']}_entryhalf_{source}_{wait_tag}", "overlay_kind": "entry_stage_proxy", "param_a": ENTRY_INITIAL_FRACTION, "param_b": float(max_wait), "param_c": 1.0, "param_s": source})
    return rows


def params_for(cand: dict[str, object]) -> dict[str, float | str]:
    kind = str(cand["overlay_kind"])
    if kind == "scorehot":
        return {"score_threshold": float(cand["param_a"]), "scale": float(cand["param_c"])}
    if kind == "volhot":
        return {"window": float(cand["param_a"]), "threshold": float(cand["param_b"]), "scale": float(cand["param_c"])}
    if kind == "downonly_tv":
        return {"target_vol": float(cand["param_a"]), "window": float(cand["param_b"]), "min_scale": float(cand["param_c"])}
    if kind == "entry_stage_proxy":
        return {"initial_fraction": float(cand["param_a"]), "max_wait": float(cand["param_b"]), "pullback_source": str(cand["param_s"])}
    return {}


def add_tiers(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["overlay_kind"] == "off"].set_index("line")
    for col in [
        "ann_return_full",
        "max_dd_full",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "sharpe_repo_full",
        "cost_total_full",
    ]:
        out[f"base_{col}"] = out["line"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100.0
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100.0
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100.0
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100.0
    out["cost_delta"] = out["cost_total_full"] - out["base_cost_total_full"]
    out["strict_full5y_pass"] = (
        (out["overlay_kind"] != "off")
        & (out["full_ann_loss_pp"] <= 1.0 + 1e-12)
        & (out["full_dd_improve_pp"] > 0)
        & (out["fivey_dd_improve_pp"] >= -1e-12)
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            (out["overlay_kind"] != "off")
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["fivey_dd_improve_pp"] >= -1e-12)
        )
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    test_rows = wm[wm["overlay_kind"] != "off"]
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for (line, kind), d in test_rows.groupby(["line", "overlay_kind"]):
            p = d[d[pass_col]].copy()
            if p.empty:
                rows.append(
                    {
                        "loss_tier_pp": tier,
                        "line": line,
                        "overlay_kind": kind,
                        "pass_count": 0,
                        "param_a_count": 0,
                        "param_b_count": 0,
                        "param_c_count": 0,
                        "param_s_count": 0,
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
            best = p.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            if kind == "entry_stage_proxy":
                patch_like = bool(len(p) >= 2 and p["param_s"].nunique() >= 1 and p["param_b"].nunique() >= 2)
            else:
                patch_like = bool(len(p) >= 3 and p["param_a"].nunique() >= 2)
            rows.append(
                {
                    "loss_tier_pp": tier,
                    "line": line,
                    "overlay_kind": kind,
                    "pass_count": int(len(p)),
                    "param_a_count": int(p["param_a"].nunique()),
                    "param_b_count": int(p["param_b"].nunique()),
                    "param_c_count": int(p["param_c"].nunique()),
                    "param_s_count": int(p["param_s"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                    "best_full_dd_improve_pp": best["full_dd_improve_pp"],
                    "best_5y_ann_return": best["ann_return_last_5y"],
                    "best_5y_max_dd": best["max_dd_last_5y"],
                    "best_overlay_days": best["overlay_days_full"],
                    "patch_like": patch_like,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def main() -> None:
    mod, zz1000, cyb, panel = l3.load_panel()
    base_by_line = {line["line"]: l3_base_returns(panel, line) for line in LINES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = make_grid()
    long_rows = []
    wide_rows = []
    daily_parts = []
    for cand in grid:
        result = apply_overlay(base_by_line[str(cand["line"])], str(cand["overlay_kind"]), params_for(cand))
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily_parts.append(daily.reset_index(names="date"))
        wide = {**cand}
        for segment, years in base.SEGMENTS:
            m = metric_base.metrics_for_segment(result, segment, years)
            seg_df = result if years is None else result.loc[result.index >= result.index.max() - pd.DateOffset(years=years)]
            m["overlay_days"] = int(seg_df["overlay_on"].sum())
            long_rows.append({**cand, **m})
            for key in [
                "ann_return",
                "max_dd",
                "sharpe_repo",
                "avg_weight",
                "avg_turnover",
                "holding_day_ratio",
                "cost_total",
                "overlay_days",
            ]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_tiers(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)
    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")

    top_by_tier = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(
            ["line", "full_dd_improve_pp", "ann_return_full"],
            ascending=[True, False, False],
        )
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_by_tier[tier] = passed

    decision = (
        "layer6_overheat_entry_candidate_found_not_promoted"
        if bool(ridge[(ridge["loss_tier_pp"] <= 1.0) & (ridge["patch_like"]) & (ridge["pass_count"] > 0)].shape[0])
        else "layer6_overheat_entry_complete_not_promoted"
    )
    cols = [
        "candidate",
        "line",
        "overlay_kind",
        "param_a",
        "param_b",
        "param_c",
        "param_s",
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
        "fivey_ann_loss_pp",
        "fivey_dd_improve_pp",
        "sharpe_repo_full",
    ]
    record_lines = [
        "# ZZ1000/CYB Layer 6 Overheat And First-Entry Staging After L3 Target-Vol",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        f"- decision: `{decision}`",
        "- stability: `overheat_entry_after_deadband_patch_review`",
        "",
        "## Research Question",
        "Test score overheat, realized-vol overheat, down-only target-vol caps, and first-entry half-position staging after Layer 3 target-vol. NAV defense and momentum decay are off because neither was promoted.",
        "",
        "## Implementation Anchor",
        "- Base exposure is the Layer 3 target-vol path from `scan_adk_zz1000_cyb_spread_layer3_target_vol.py`.",
        "- Overheat states use prior-row T-close state where applicable and recalculate costs on final exposure changes.",
        "- First-entry staging enters half exposure first and adds the remaining half after a close-to-close pullback proxy or max-wait timeout.",
        "",
        "## Data Snapshot",
        f"- ZZ1000 rows: {len(zz1000)}, start {zz1000.index.min().date()}, end {zz1000.index.max().date()}, columns {list(zz1000.columns)}.",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}, columns {list(cyb.columns)}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start: `2014-10-17`, constrained by CSI 1000 publication date.",
        "- True bearish-candle staging is not formal in this run because local official caches have close only, not open. Entry-staging results use close-down proxies and are diagnostic/quasi-formal.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal/state -> T+1 close-to-close spread return.",
        "- Return stream: ZZ1000 close-to-close return minus CYB close-to-close return.",
        "- Two-leg transaction cost with one-way commission 0.0005 on final exposure changes.",
        "- NAV defense, momentum decay, amount, and volume overlays are off.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_zz1000_cyb_spread_layer6_overheat_entry.py\"`",
        "- `python \"scan_adk_zz1000_cyb_spread_layer6_overheat_entry.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `dd_first_pass_loss_le_0p5pp.csv`",
        "- `dd_first_pass_loss_le_1p0pp.csv`",
        "- `dd_first_pass_loss_le_2p0pp.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        top_by_tier[0.5][cols].head(30).to_markdown(index=False) if not top_by_tier[0.5].empty else "No candidates passed loss<=0.5pp with Full DD improvement and 5Y DD non-worse.",
        "",
        "## Window Results",
        top_by_tier[1.0][cols].head(30).to_markdown(index=False) if not top_by_tier[1.0].empty else "No candidates passed loss<=1pp with Full DD improvement and 5Y DD non-worse.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 6 completed. Stop for user review before amount/volume or final ridge layers.",
        "",
        "## User-Facing Summary",
        f"- loss<=0.5pp pass count: {len(top_by_tier[0.5])}",
        f"- loss<=1.0pp pass count: {len(top_by_tier[1.0])}",
        f"- loss<=2.0pp pass count: {len(top_by_tier[2.0])}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz1000_cyb_spread_layer3_target_vol.py",
        "git_branch": "dirty_worktree_not_cleaned",
        "git_commit": "not_recorded",
        "git_status_before": "dirty_worktree_with_prior_research_artifacts",
        "git_status_after": "dirty_worktree_with_prior_research_artifacts",
        "scan_type": "layer6_overheat_entry_after_l3_target_vol",
        "parameter_group": "scorehot_volhot_downonlytv_entryhalf_closepullback",
        "baseline": {"lines": LINES, "loss_tiers_pp": LOSS_TIERS},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
            "entry_staging": "half exposure first; close-down proxy shifted to next execution; true bearish candle unavailable without open",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "zz1000": {
                "secid": str(mod.CN_DK_ZZ1000_SECID),
                "rows": int(len(zz1000)),
                "start": str(zz1000.index.min().date()),
                "end": str(zz1000.index.max().date()),
                "publication_date": "2014-10-17",
            },
            "cyb": {
                "secid": str(mod.CN_DK_CYB_SECID),
                "rows": int(len(cyb)),
                "start": str(cyb.index.min().date()),
                "end": str(cyb.index.max().date()),
            },
            "formal": {
                "rows": int(len(panel)),
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
                "start_rule": "latest actual publication/listing date; ZZ1000 publication 2014-10-17",
            },
            "ohlc_availability": {
                "cyb_columns": list(cyb.columns),
                "zz1000_columns": list(zz1000.columns),
                "true_bearish_candle_available": False,
            },
        },
        "decision": decision,
        "stability_label": "overheat_entry_after_deadband_patch_review",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_zz1000_cyb_spread_layer6_overheat_entry.py\"\n"
        "python \"scan_adk_zz1000_cyb_spread_layer6_overheat_entry.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("BASELINES")
    print(window_metrics[window_metrics.overlay_kind == "off"][cols].to_string(index=False))
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_by_tier[tier])}")
        print(top_by_tier[tier][cols].head(12).to_string(index=False) if not top_by_tier[tier].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

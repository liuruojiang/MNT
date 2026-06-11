"""Layer 5 momentum-decay scan after Layer 3 target-vol for ZZ1000/CYB.

Layer 4 NAV defense was not promoted, so this layer compares momentum decay
against the unchanged Layer 3 target-vol lines. NAV defense, overheat, amount, and
volume overlays are intentionally off.
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

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260611_adk_zz1000_cyb_spread_long_only_v77_adk_spread_layer5_momentum_decay_after_l3_target_vol_nav_off"

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

DECAY_THRESHOLDS = [0.35, 0.45, 0.55, 0.65, 0.70, 0.75]
RECOVERY_THRESHOLDS = [0.70, 0.80, 0.90]
WARMUP_DAYS = [3, 5, 10]
DERISK_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0]


def fmt(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def l3_base_returns(panel: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    sig = l3.line_signal(panel, line)
    d = l3.returns_for(panel, sig, line).copy()
    extra = sig[["score"]].reindex(d.index)
    d = pd.concat([d, extra], axis=1).copy()
    d["raw_signal"] = sig["signal"].reindex(d.index).fillna(0.0)
    d["spread_return"] = panel["spread_return"].reindex(d.index).fillna(0.0)
    d["base_weight"] = d["weight"]
    return d


def score_decay_multiplier(
    d: pd.DataFrame,
    decay: float | None,
    recovery: float | None,
    warmup: int | None,
    derisk_scale: float | None,
) -> pd.Series:
    if decay is None:
        return pd.Series(1.0, index=d.index)
    raw_signal = d["raw_signal"].astype(float).to_numpy()
    score = d["score"].astype(float).to_numpy()
    state = np.ones(len(d), dtype=float)
    peak = np.nan
    active_days = 0
    in_decay = False
    for i in range(len(d)):
        if raw_signal[i] <= 0 or not np.isfinite(score[i]):
            peak = np.nan
            active_days = 0
            in_decay = False
            state[i] = 1.0
            continue
        active_days += 1
        peak = score[i] if not np.isfinite(peak) else max(peak, score[i])
        ratio = score[i] / peak if peak > 0 else 1.0
        if active_days >= int(warmup):
            if in_decay:
                if ratio >= float(recovery):
                    in_decay = False
            elif ratio <= float(decay):
                in_decay = True
        state[i] = float(derisk_scale) if in_decay else 1.0
    # T-close decay state controls the next execution row.
    return pd.Series(state, index=d.index).shift(1).fillna(1.0)


def apply_decay(
    base_df: pd.DataFrame,
    decay: float | None,
    recovery: float | None,
    warmup: int | None,
    derisk_scale: float | None,
) -> pd.DataFrame:
    d = base_df.copy()
    mult = score_decay_multiplier(d, decay, recovery, warmup, derisk_scale)
    final_weight = d["base_weight"] * mult
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = final_weight * d["gross_return"].div(d["base_weight"].replace(0.0, np.nan)).fillna(0.0)
    ret = gross_return - cost
    decay_active = (final_weight.abs() < d["base_weight"].abs() - 1e-12) & (d["base_weight"].abs() > 1e-12)
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "base_weight": d["base_weight"],
            "decay_mult": mult,
            "decay_active": decay_active.astype(float),
            "score": d["score"],
            "raw_signal": d["raw_signal"],
            "applied_scale": d["applied_scale"],
            "realized_vol": d["realized_vol"],
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    grid = []
    for line in LINES:
        grid.append(
            {
                **line,
                "candidate": f"l5_{line['line']}_decay_off",
                "decay_threshold": 0.0,
                "recovery_threshold": 0.0,
                "warmup_days": 0,
                "derisk_scale": 1.0,
                "decay_enabled": False,
            }
        )
        for decay in DECAY_THRESHOLDS:
            for recovery in RECOVERY_THRESHOLDS:
                for warmup in WARMUP_DAYS:
                    for scale in DERISK_SCALES:
                        grid.append(
                            {
                                **line,
                                "candidate": f"l5_{line['line']}_decay{fmt(decay)}_rec{fmt(recovery)}_warm{warmup}_scale{fmt(scale)}",
                                "decay_threshold": decay,
                                "recovery_threshold": recovery,
                                "warmup_days": warmup,
                                "derisk_scale": scale,
                                "decay_enabled": True,
                            }
                        )
    return grid


def add_tiers(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["decay_enabled"] == False].set_index("line")
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
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            (out["decay_enabled"] == True)
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["fivey_dd_improve_pp"] >= -1e-12)
        )
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    decay_rows = wm[wm["decay_enabled"] == True]
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for line, d in decay_rows.groupby("line"):
            p = d[d[pass_col]].copy()
            if p.empty:
                rows.append(
                    {
                        "loss_tier_pp": tier,
                        "line": line,
                        "pass_count": 0,
                        "decay_count": 0,
                        "recovery_count": 0,
                        "warmup_count": 0,
                        "scale_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "best_decay_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = p.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(
                len(p) >= 4
                and p["decay_threshold"].nunique() >= 2
                and p["derisk_scale"].nunique() >= 2
            )
            rows.append(
                {
                    "loss_tier_pp": tier,
                    "line": line,
                    "pass_count": int(len(p)),
                    "decay_count": int(p["decay_threshold"].nunique()),
                    "recovery_count": int(p["recovery_threshold"].nunique()),
                    "warmup_count": int(p["warmup_days"].nunique()),
                    "scale_count": int(p["derisk_scale"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                    "best_full_dd_improve_pp": best["full_dd_improve_pp"],
                    "best_5y_ann_return": best["ann_return_last_5y"],
                    "best_5y_max_dd": best["max_dd_last_5y"],
                    "best_decay_days": best["decay_days_full"],
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
        result = apply_decay(
            base_by_line[str(cand["line"])],
            None if not cand["decay_enabled"] else float(cand["decay_threshold"]),
            None if not cand["decay_enabled"] else float(cand["recovery_threshold"]),
            None if not cand["decay_enabled"] else int(cand["warmup_days"]),
            None if not cand["decay_enabled"] else float(cand["derisk_scale"]),
        )
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily_parts.append(daily.reset_index(names="date"))
        wide = {**cand}
        for segment, years in base.SEGMENTS:
            m = metric_base.metrics_for_segment(result, segment, years)
            seg_df = result if years is None else result.loc[result.index >= result.index.max() - pd.DateOffset(years=years)]
            m["decay_days"] = int(seg_df["decay_active"].sum())
            long_rows.append({**cand, **m})
            for key in [
                "ann_return",
                "max_dd",
                "sharpe_repo",
                "avg_weight",
                "avg_turnover",
                "holding_day_ratio",
                "cost_total",
                "decay_days",
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
        "layer5_momentum_decay_candidate_found_not_promoted"
        if bool(ridge[(ridge["loss_tier_pp"] <= 1.0) & (ridge["patch_like"]) & (ridge["pass_count"] > 0)].shape[0])
        else "layer5_momentum_decay_complete_not_promoted"
    )
    cols = [
        "candidate",
        "line",
        "line_role",
        "decay_threshold",
        "recovery_threshold",
        "warmup_days",
        "derisk_scale",
        "decay_days_full",
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
    formal_preserve = window_metrics[
        (window_metrics["line"] == "primary_tv14_vw60_max1p25_db0p05")
        & (window_metrics["decay_enabled"] == True)
        & (window_metrics["full_ann_loss_pp"] <= 0.5 + 1e-12)
        & (window_metrics["full_dd_improve_pp"] > 0)
        & (window_metrics["fivey_ann_loss_pp"] <= 0.5 + 1e-12)
        & (window_metrics["fivey_dd_improve_pp"] >= -1e-12)
    ].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
    record_lines = [
        "# ZZ1000/CYB Layer 5 Momentum Decay After L3 Target-Vol",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        f"- decision: `{decision}`",
        "- stability: `momentum_decay_after_deadband_patch_review`",
        "",
        "## Research Question",
        "Test score-peak momentum decay after target-vol and scale-change deadband, with NAV defense explicitly off because Layer 4 was not promoted.",
        "",
        "## Implementation Anchor",
        "- Base exposure is the Layer 3 target-vol path from `scan_adk_zz1000_cyb_spread_layer3_target_vol.py`.",
        "- Momentum-decay state is computed from T-close score/current-trade peak and shifted to T+1 execution.",
        "- Costs are recalculated after final exposure changes.",
        "",
        "## Data Snapshot",
        f"- ZZ1000 rows: {len(zz1000)}, start {zz1000.index.min().date()}, end {zz1000.index.max().date()}.",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start: `2014-10-17`, constrained by CSI 1000 publication date.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal/state -> T+1 close-to-close spread return.",
        "- Return stream: ZZ1000 close-to-close return minus CYB close-to-close return.",
        "- Momentum decay uses T-close score ratio to current trade peak, shifted to next execution row.",
        "- NAV defense, overheat, amount, and volume overlays are off.",
        "- Two-leg transaction cost with one-way commission 0.0005 on final exposure changes.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_zz1000_cyb_spread_layer5_momentum_decay.py\"`",
        "- `python \"scan_adk_zz1000_cyb_spread_layer5_momentum_decay.py\"`",
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
        "## Formal 5Y Annualized Preservation Check",
        formal_preserve[cols].head(12).to_markdown(index=False) if not formal_preserve.empty else "No formal-carry candidates preserved 5Y annualized return within 0.5pp while improving Full and 5Y DD.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 5 completed. Stop for user review before any overheat, volhot, amount, or volume layer.",
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
        "scan_type": "layer5_momentum_decay_after_l3_target_vol_nav_off",
        "parameter_group": "score_peak_decay_recovery_warmup_scale",
        "baseline": {"lines": LINES, "loss_tiers_pp": LOSS_TIERS},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
            "momentum_decay_timing": "T-close score/peak state shifted to next execution row",
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
        },
        "decision": decision,
        "stability_label": "momentum_decay_after_deadband_patch_review",
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
        "python -m py_compile \"scan_adk_zz1000_cyb_spread_layer5_momentum_decay.py\"\n"
        "python \"scan_adk_zz1000_cyb_spread_layer5_momentum_decay.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("BASELINES")
    print(window_metrics[window_metrics.decay_enabled == False][cols].to_string(index=False))
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_by_tier[tier])}")
        print(top_by_tier[tier][cols].head(12).to_string(index=False) if not top_by_tier[tier].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

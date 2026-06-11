"""Layer 4 NAV drawdown defense after Layer 3 target-vol for ZZ1000/CYB.

Uses prior-row pre-overlay candidate NAV drawdown. If prior drawdown is below
the threshold, next execution exposure is multiplied by defense_scale and costs
are recalculated on final exposure changes.
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


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260611_adk_zz1000_cyb_spread_long_only_v77_adk_spread_layer4_nav_defense_after_l3_target_vol_deadband"

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

NAV_THRESHOLDS = [0.03, 0.04, 0.05, 0.06, 0.075, 0.0875, 0.10, 0.12]
DEFENSE_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0]


def fmt(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def l3_base_returns(panel: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    sig = l3.line_signal(panel, line)
    d = l3.returns_for(panel, sig, line).copy()
    d["spread_return"] = panel["spread_return"].reindex(d.index)
    pre_nav = (1.0 + d["return"]).cumprod()
    d["pre_nav"] = pre_nav
    d["pre_nav_dd"] = pre_nav / pre_nav.cummax() - 1.0
    return d


def apply_nav_defense(base_df: pd.DataFrame, threshold: float | None, scale: float | None) -> pd.DataFrame:
    d = base_df.copy()
    if threshold is None:
        final_weight = d["weight"]
        defense_on = pd.Series(False, index=d.index)
        mult = pd.Series(1.0, index=d.index)
    else:
        defense_on = d["pre_nav_dd"].shift(1).fillna(0.0) <= -float(threshold)
        mult = pd.Series(1.0, index=d.index)
        mult.loc[defense_on] = float(scale)
        final_weight = d["weight"] * mult

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
            "base_weight": d["weight"],
            "spread_return": d["spread_return"],
            "pre_nav": d["pre_nav"],
            "pre_nav_dd": d["pre_nav_dd"],
            "nav_defense_on": defense_on.astype(float),
            "nav_defense_mult": mult,
            "raw_scale": d["raw_scale"],
            "applied_scale": d["applied_scale"],
            "realized_vol": d["realized_vol"],
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for line in LINES:
        grid.append(
            {
                **line,
                "candidate": f"l4_{line['line']}_nav_off",
                "nav_threshold": 0.0,
                "defense_scale": 1.0,
                "nav_enabled": False,
            }
        )
        for threshold in NAV_THRESHOLDS:
            for scale in DEFENSE_SCALES:
                grid.append(
                    {
                        **line,
                        "candidate": f"l4_{line['line']}_nav{fmt(threshold, True)}_scale{fmt(scale)}",
                        "nav_threshold": threshold,
                        "defense_scale": scale,
                        "nav_enabled": True,
                    }
                )
    return grid


def add_baselines_and_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["nav_enabled"] == False].set_index("line")
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
    out["pass_full_ann_dd"] = (
        (out["nav_enabled"] == True)
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
            (out["nav_enabled"] == True)
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["fivey_dd_improve_pp"] >= -1e-12)
        )
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for line, group in wm[wm["nav_enabled"] == True].groupby("line"):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "loss_tier_pp": tier,
                        "line": line,
                        "pass_count": 0,
                        "threshold_count": 0,
                        "scale_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "best_nav_defense_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            thresholds = sorted(passed["nav_threshold"].unique())
            adjacent = any(round(thresholds[i + 1] - thresholds[i], 4) <= 0.0251 for i in range(len(thresholds) - 1))
            rows.append(
                {
                    "loss_tier_pp": tier,
                    "line": line,
                    "pass_count": int(len(passed)),
                    "threshold_count": int(passed["nav_threshold"].nunique()),
                    "scale_count": int(passed["defense_scale"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                    "best_full_dd_improve_pp": best["full_dd_improve_pp"],
                    "best_5y_ann_return": best["ann_return_last_5y"],
                    "best_5y_max_dd": best["max_dd_last_5y"],
                    "best_nav_defense_days": best["nav_defense_days_full"],
                    "patch_like": bool(len(passed) >= 3 and adjacent),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def window_table(df: pd.DataFrame, n: int = 12) -> str:
    cols = ["candidate", "line", "nav_threshold", "defense_scale"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    mod, zz1000, cyb, panel = l3.load_panel()
    base_by_line = {line["line"]: l3_base_returns(panel, line) for line in LINES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = make_grid()
    long_rows = []
    wide_rows = []
    daily_parts = []

    for cand in grid:
        result = apply_nav_defense(
            base_by_line[str(cand["line"])],
            None if not bool(cand["nav_enabled"]) else float(cand["nav_threshold"]),
            None if not bool(cand["nav_enabled"]) else float(cand["defense_scale"]),
        )
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily_parts.append(daily.reset_index(names="date"))

        wide = {**cand}
        for segment, years in base.SEGMENTS:
            metrics = metric_base.metrics_for_segment(result, segment, years)
            seg_df = result if years is None else result.loc[result.index >= result.index.max() - pd.DateOffset(years=years)]
            metrics["nav_defense_days"] = int(seg_df["nav_defense_on"].sum())
            long_rows.append({**cand, **metrics})
            for key in [
                "ann_return",
                "max_dd",
                "sharpe_repo",
                "avg_weight",
                "avg_turnover",
                "holding_day_ratio",
                "cost_total",
                "nav_defense_days",
            ]:
                wide[f"{key}_{segment}"] = metrics[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_curves = pd.concat(daily_parts, ignore_index=True)

    full_pass = window_metrics[window_metrics["pass_full_ann_dd"]].sort_values(
        ["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[window_metrics["pass_full_and_5y"]].sort_values(
        ["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]
    )
    top_tier: dict[float, pd.DataFrame] = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(
            ["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]
        )
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_tier[tier] = passed

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily_curves.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")

    cols = [
        "candidate",
        "line",
        "line_role",
        "nav_threshold",
        "defense_scale",
        "nav_defense_days_full",
        "ann_return_full",
        "max_dd_full",
        "full_ann_loss_pp",
        "full_dd_improve_pp",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "fivey_ann_loss_pp",
        "fivey_dd_improve_pp",
        "sharpe_repo_full",
    ]
    record_lines = [
        "# ZZ1000/CYB Layer 4 NAV Defense After Target-Vol",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer4_nav_defense_complete_not_promoted`",
        "- stability: `nav_defense_after_target_vol_patch_review`",
        "",
        "## Research Question",
        "Test prior-row NAV drawdown defense after target-vol and scale-change deadband.",
        "",
        "## Implementation Anchor",
        "- Base exposure is the Layer 3 target-vol path from `scan_adk_zz1000_cyb_spread_layer3_target_vol.py`.",
        "- NAV defense uses prior-row pre-overlay NAV drawdown, scales the next execution exposure, and recalculates transaction costs.",
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
        "- Two-leg transaction cost with one-way commission 0.0005 on final exposure changes.",
        "- No momentum-decay, overheat, amount, or volume overlay is applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 4 scan.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_zz1000_cyb_spread_layer4_nav_defense.py\"`",
        "- `python \"scan_adk_zz1000_cyb_spread_layer4_nav_defense.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `full_baseline_pass_candidates.csv`",
        "- `full_and_5y_pass_candidates.csv`",
        "- `dd_first_pass_loss_le_0p5pp.csv`",
        "- `dd_first_pass_loss_le_1p0pp.csv`",
        "- `dd_first_pass_loss_le_2p0pp.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        window_table(top_tier[0.5], 12) if not top_tier[0.5].empty else "No candidates passed loss<=0.5pp with Full DD improvement and 5Y DD non-worse.",
        "",
        "## Window Results",
        window_table(top_tier[1.0], 12) if not top_tier[1.0].empty else "No candidates passed loss<=1pp with Full DD improvement and 5Y DD non-worse.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 4 completed but not promoted. Stop for user review before Layer 5 momentum decay.",
        "",
        "## User-Facing Summary",
        f"- strict full+5Y pass count: {len(strict_pass)}",
        f"- loss<=0.5pp pass count: {len(top_tier[0.5])}",
        f"- loss<=1.0pp pass count: {len(top_tier[1.0])}",
        f"- loss<=2.0pp pass count: {len(top_tier[2.0])}",
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
        "scan_type": "layer4_nav_defense_after_target_vol_deadband",
        "parameter_group": "nav_dd_threshold_defense_scale",
        "baseline": {"lines": LINES, "loss_tiers_pp": LOSS_TIERS},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
            "nav_defense_timing": "prior-row pre-overlay NAV drawdown controls next execution exposure",
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
        "decision": "layer4_nav_defense_complete_not_promoted",
        "stability_label": "nav_defense_after_target_vol_patch_review",
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
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_zz1000_cyb_spread_layer4_nav_defense.py\"\n"
        "python \"scan_adk_zz1000_cyb_spread_layer4_nav_defense.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("BASELINES")
    print(window_metrics[window_metrics.nav_enabled == False][cols].to_string(index=False))
    print("STRICT_FULL_5Y")
    print(strict_pass[cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_tier[tier])}")
        print(top_tier[tier][cols].head(12).to_string(index=False) if not top_tier[tier].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

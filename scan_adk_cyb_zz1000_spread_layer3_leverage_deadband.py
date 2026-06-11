"""Layer 3B leverage deadband scan for CYB/ZZ1000 target-vol candidates.

This is a required continuation of the target-vol layer. It scans the minimum
absolute scale change required before updating live leverage, so target-vol
candidates are judged on executable exposure paths, not only raw daily scaling.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_zz1000_spread_long_only as base
import scan_adk_cyb_zz1000_spread_layer3_target_vol as l3tv

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260611_adk_cyb_zz1000_spread_long_only_v77_adk_spread_layer3b_leverage_deadband_after_target_vol"

LINES = [
    {
        "line": "formal_s1_abs35_tv10_vw20_max1p25",
        "line_role": "formal_default",
        "anchor": "main_s1_abs35_m3",
        "target_vol": 0.10,
        "vol_window": 20,
        "max_leverage": 1.25,
    },
    {
        "line": "alt_s0_abs60_tv10_vw20_max1p5",
        "line_role": "target_vol_alternative",
        "anchor": "main_s0_abs60_p1",
        "target_vol": 0.10,
        "vol_window": 20,
        "max_leverage": 1.50,
    },
    {
        "line": "def_s0_abs60_tv8_vw20_max1p5",
        "line_role": "defensive_watchlist",
        "anchor": "main_s0_abs60_p1",
        "target_vol": 0.08,
        "vol_window": 20,
        "max_leverage": 1.50,
    },
]

DEADBANDS = [0.0, 0.025, 0.05, 0.075, 0.10, 0.125, 0.15, 0.20, 0.25, 0.30]
LOSS_TIERS = [0.25, 0.50, 1.00]


def fmt(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def selected_anchors() -> list[dict[str, object]]:
    by_name = {str(a["anchor"]): a for a in l3tv.ANCHORS}
    anchors: list[dict[str, object]] = []
    for line in LINES:
        anchor = dict(by_name[str(line["anchor"])])
        anchors.append(anchor)
    seen = set()
    unique = []
    for anchor in anchors:
        if anchor["anchor"] in seen:
            continue
        seen.add(anchor["anchor"])
        unique.append(anchor)
    return unique


def apply_scale_deadband(raw_scale: pd.Series, signal: pd.Series, threshold: float) -> pd.Series:
    applied = []
    last_scale = 0.0
    for desired_raw, sig in zip(raw_scale.fillna(0.0).astype(float), signal.fillna(0.0).astype(float)):
        if sig <= 0:
            current = 0.0
        elif last_scale <= 0:
            current = desired_raw
        elif abs(desired_raw - last_scale) >= threshold - 1e-12:
            current = desired_raw
        else:
            current = last_scale
        applied.append(current)
        last_scale = current
    return pd.Series(applied, index=raw_scale.index)


def returns_for_deadband(panel: pd.DataFrame, sig: pd.DataFrame, line: dict[str, object], deadband: float) -> pd.DataFrame:
    d = pd.concat([sig, panel[["spread_return"]]], axis=1).dropna().copy()
    realized_vol = d["spread_return"].rolling(int(line["vol_window"])).std() * np.sqrt(base.ANNUALIZATION_DAYS)
    raw_scale = (
        (float(line["target_vol"]) / realized_vol)
        .clip(l3tv.MIN_LEVERAGE, float(line["max_leverage"]))
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
    )
    applied_scale = apply_scale_deadband(raw_scale, d["signal"], float(deadband))
    weight = d["signal"] * applied_scale
    turnover = weight.diff().abs().fillna(weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = weight * d["spread_return"]
    ret = gross_return - cost
    raw_weight = d["signal"] * raw_scale
    scale_diff = applied_scale.diff().abs().fillna(applied_scale.abs())
    raw_scale_diff = raw_scale.diff().abs().fillna(raw_scale.abs())
    holding = d["signal"] > 0
    scale_adjust_day = holding & (scale_diff > 1e-12)
    raw_scale_adjust_day = holding & (raw_scale_diff > 1e-12)
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": weight,
            "raw_weight": raw_weight,
            "raw_scale": raw_scale,
            "applied_scale": applied_scale,
            "realized_vol": realized_vol,
            "scale_adjust_day": scale_adjust_day.astype(int),
            "raw_scale_adjust_day": raw_scale_adjust_day.astype(int),
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    grid = []
    for line in LINES:
        for deadband in DEADBANDS:
            grid.append(
                {
                    **line,
                    "candidate": f"l3b_{line['line']}_db{fmt(deadband)}",
                    "scale_deadband": deadband,
                }
            )
    return grid


def add_baseline_and_tiers(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["scale_deadband"] == 0.0].set_index("line")
    for col in [
        "ann_return_full",
        "max_dd_full",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "sharpe_repo_full",
        "scale_adjust_days_full",
        "cost_total_full",
        "avg_turnover_full",
    ]:
        out[f"base_{col}"] = out["line"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100.0
    out["full_dd_delta_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100.0
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100.0
    out["fivey_dd_delta_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100.0
    out["scale_adjust_reduction_pct"] = np.where(
        out["base_scale_adjust_days_full"] > 0,
        1.0 - out["scale_adjust_days_full"] / out["base_scale_adjust_days_full"],
        0.0,
    )
    out["cost_reduction_pct"] = np.where(
        out["base_cost_total_full"] > 0,
        1.0 - out["cost_total_full"] / out["base_cost_total_full"],
        0.0,
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            (out["scale_deadband"] > 0)
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["max_dd_full"] >= out["base_max_dd_full"] - 0.005)
            & (out["scale_adjust_reduction_pct"] >= 0.25)
        )
    out["pass_practical"] = (
        (out["scale_deadband"] > 0)
        & (out["full_ann_loss_pp"] <= 0.50 + 1e-12)
        & (out["max_dd_full"] >= out["base_max_dd_full"] - 0.005)
        & (out["scale_adjust_reduction_pct"] >= 0.40)
    )
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for line, d in wm[wm["scale_deadband"] > 0].groupby("line"):
            p = d[d[pass_col]].copy()
            if p.empty:
                rows.append(
                    {
                        "loss_tier_pp": tier,
                        "line": line,
                        "pass_count": 0,
                        "deadband_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_scale_adjust_reduction_pct": np.nan,
                        "best_cost_reduction_pct": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = p.sort_values(
                ["scale_adjust_reduction_pct", "ann_return_full", "max_dd_full"],
                ascending=[False, False, False],
            ).iloc[0]
            deadbands = sorted(p["scale_deadband"].unique())
            adjacent = any(round(deadbands[i + 1] - deadbands[i], 3) <= 0.051 for i in range(len(deadbands) - 1))
            rows.append(
                {
                    "loss_tier_pp": tier,
                    "line": line,
                    "pass_count": int(len(p)),
                    "deadband_count": int(p["scale_deadband"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                    "best_scale_adjust_reduction_pct": best["scale_adjust_reduction_pct"],
                    "best_cost_reduction_pct": best["cost_reduction_pct"],
                    "patch_like": bool(len(p) >= 2 and adjacent),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["loss_tier_pp", "patch_like", "pass_count", "best_scale_adjust_reduction_pct"],
        ascending=[True, False, False, False],
    )


def main() -> None:
    mod, cyb, zz1000, panel = l3tv.load_panel()
    signals = {a["anchor"]: l3tv.anchor_signal(panel, a) for a in selected_anchors()}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = make_grid()
    long_rows = []
    wide_rows = []
    daily_parts = []
    for cand in grid:
        result = returns_for_deadband(panel, signals[str(cand["anchor"])], cand, float(cand["scale_deadband"]))
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily_parts.append(daily.reset_index(names="date"))
        wide = {**cand}
        for segment, years in base.SEGMENTS:
            m = base.metrics_for_segment(result, segment, years)
            if years is None:
                seg_df = result
            else:
                cutoff = result.index.max() - pd.DateOffset(years=years)
                seg_df = result.loc[result.index >= cutoff]
            m["scale_adjust_days"] = int(seg_df["scale_adjust_day"].sum())
            m["raw_scale_adjust_days"] = int(seg_df["raw_scale_adjust_day"].sum())
            m["scale_adjust_days_per_year"] = float(seg_df["scale_adjust_day"].sum() / max(len(seg_df), 1) * base.ANNUALIZATION_DAYS)
            m["raw_scale_adjust_days_per_year"] = float(seg_df["raw_scale_adjust_day"].sum() / max(len(seg_df), 1) * base.ANNUALIZATION_DAYS)
            m["avg_applied_scale_when_holding"] = float(seg_df.loc[seg_df["weight"] > 0, "applied_scale"].mean()) if (seg_df["weight"] > 0).any() else 0.0
            m["avg_raw_scale_when_holding"] = float(seg_df.loc[seg_df["raw_weight"] > 0, "raw_scale"].mean()) if (seg_df["raw_weight"] > 0).any() else 0.0
            long_rows.append({**cand, **m})
            for key in [
                "ann_return",
                "max_dd",
                "sharpe_repo",
                "avg_weight",
                "avg_turnover",
                "holding_day_ratio",
                "cost_total",
                "scale_adjust_days",
                "raw_scale_adjust_days",
                "scale_adjust_days_per_year",
                "raw_scale_adjust_days_per_year",
                "avg_applied_scale_when_holding",
                "avg_raw_scale_when_holding",
            ]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baseline_and_tiers(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)
    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")

    practical = window_metrics[window_metrics["pass_practical"]].sort_values(
        ["line", "scale_adjust_reduction_pct", "ann_return_full"], ascending=[True, False, False]
    )
    practical.to_csv(RUN_DIR / "practical_deadband_candidates.csv", index=False, encoding="utf-8-sig")
    top_by_tier = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(
            ["line", "scale_adjust_reduction_pct", "ann_return_full"], ascending=[True, False, False]
        )
        passed.to_csv(RUN_DIR / f"deadband_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_by_tier[tier] = passed

    cols = [
        "candidate",
        "line",
        "line_role",
        "scale_deadband",
        "ann_return_full",
        "max_dd_full",
        "full_ann_loss_pp",
        "full_dd_delta_pp",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "fivey_ann_loss_pp",
        "fivey_dd_delta_pp",
        "scale_adjust_days_full",
        "scale_adjust_days_per_year_full",
        "scale_adjust_reduction_pct",
        "cost_total_full",
        "cost_reduction_pct",
        "avg_applied_scale_when_holding_full",
        "sharpe_repo_full",
    ]
    record_lines = [
        "# CYB/ZZ1000 Layer 3B Leverage Deadband Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer3b_leverage_deadband_complete_not_promoted`",
        "- stability: `scale_deadband_practicality_review`",
        "",
        "## Research Question",
        "Scan the target-vol leverage adjustment threshold so live exposure does not require frequent small day-to-day scale changes.",
        "",
        "## Implementation Anchor",
        "- Uses Layer 3 target-vol candidates from `scan_adk_cyb_zz1000_spread_layer3_target_vol.py`.",
        "- Deadband semantics follow V7-style absolute scale threshold: during an active holding, keep the last applied scale unless `abs(raw_scale - last_applied_scale) >= threshold`; entries and exits still execute.",
        "",
        "## Data Snapshot",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- ZZ1000 rows: {len(zz1000)}, start {zz1000.index.min().date()}, end {zz1000.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal -> T+1 close-to-close spread return.",
        "- Two-leg transaction cost with one-way commission 0.0005 on exposure changes after deadband.",
        "- No NAV defense, overheat, amount, or momentum-decay overlay is applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_cyb_zz1000_spread_layer3_leverage_deadband.py\"`",
        "- `python \"scan_adk_cyb_zz1000_spread_layer3_leverage_deadband.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `practical_deadband_candidates.csv`",
        "- `deadband_pass_loss_le_0p25pp.csv`",
        "- `deadband_pass_loss_le_0p5pp.csv`",
        "- `deadband_pass_loss_le_1p0pp.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Practical Candidates",
        practical[cols].head(30).to_markdown(index=False) if not practical.empty else "No practical candidates passed the current screen.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 3B completed but not promoted. Stop for user review before NAV-defense layer.",
        "",
        "## User-Facing Summary",
        f"- practical pass count: {len(practical)}",
        f"- loss<=0.25pp pass count: {len(top_by_tier[0.25])}",
        f"- loss<=0.50pp pass count: {len(top_by_tier[0.50])}",
        f"- loss<=1.00pp pass count: {len(top_by_tier[1.00])}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_cyb_zz1000_spread_layer3_target_vol.py",
        "git_branch": "not_checked_agent_policy",
        "git_commit": "not_checked_agent_policy",
        "git_status_before": "not_checked_agent_policy",
        "git_status_after": "not_checked_agent_policy",
        "scan_type": "layer3b_leverage_deadband_after_target_vol",
        "parameter_group": "target_vol_scale_deadband",
        "baseline": {"lines": LINES, "loss_tiers_pp": LOSS_TIERS, "deadband_zero_is_raw_target_vol": True},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal -> T+1 close-to-close return",
            "deadband_semantics": "absolute scale change threshold during active holdings",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via layer3 target-vol harness",
            "formal": {
                "rows": int(len(panel)),
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
            },
        },
        "decision": "layer3b_leverage_deadband_complete_not_promoted",
        "stability_label": "scale_deadband_practicality_review",
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
        "python -m py_compile \"scan_adk_cyb_zz1000_spread_layer3_leverage_deadband.py\"\n"
        "python \"scan_adk_cyb_zz1000_spread_layer3_leverage_deadband.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("BASELINES")
    print(window_metrics[window_metrics.scale_deadband == 0.0][cols].to_string(index=False))
    print("PRACTICAL")
    print(practical[cols].head(30).to_string(index=False) if not practical.empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

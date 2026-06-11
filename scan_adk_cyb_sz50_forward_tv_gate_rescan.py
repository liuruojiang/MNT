#!/usr/bin/env python
"""Rescan final CYB/SZ50 forward strategy target-vol gate."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import final_adk_cyb_sz50_spread as fwd


ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / "quant_param_scan_runs" / "20260610_adk_cyb_sz50_forward_tv_gate_rescan"
SEGMENTS = [("full", None), ("last_10y", 10), ("last_5y", 5), ("last_3y", 3), ("last_1y", 1)]


def gate_grid() -> list[float]:
    coarse = [x / 100.0 for x in range(0, 16)]
    fine = [x / 1000.0 for x in range(80, 106)]
    return sorted(set(round(x, 3) for x in coarse + fine))


def pct_label(value: float) -> str:
    return f"gate_{int(round(value * 1000)):03d}bp"


def git_text(args: list[str]) -> str:
    try:
        out = subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT)
        return out.strip()
    except Exception as exc:  # pragma: no cover - audit helper only
        return f"unavailable: {exc}"


def subset(curve: pd.DataFrame, years: int | None) -> pd.DataFrame:
    if years is None or curve.empty:
        return curve
    return curve.loc[curve.index >= curve.index.max() - pd.DateOffset(years=int(years))]


def build_candidate(gate: float) -> tuple[pd.DataFrame, dict[str, object], list[dict[str, object]]]:
    original_gate = fwd.TV_GATE
    try:
        fwd.TV_GATE = float(gate)
        curve, meta = fwd.build_curve()
        metrics = fwd.build_metrics(curve)
    finally:
        fwd.TV_GATE = original_gate
    return curve, meta, metrics


def metric_row(candidate: str, gate: float, metric: dict[str, object], curve: pd.DataFrame, years: int | None) -> dict[str, object]:
    d = subset(curve, years)
    raw = pd.to_numeric(d.get("raw_target_vol_scale", pd.Series(dtype=float)), errors="coerce")
    scale = pd.to_numeric(d.get("target_vol_scale", pd.Series(dtype=float)), errors="coerce")
    active = pd.to_numeric(d.get("exec_signal", pd.Series(dtype=float)), errors="coerce").fillna(0.0) > 0.0
    active_scale_delta = (raw[active] - scale[active]).abs() if len(raw) else pd.Series(dtype=float)
    return {
        "candidate": candidate,
        "tv_gate": gate,
        "segment": metric["segment"],
        "start": metric["start"],
        "end": metric["end"],
        "rows": metric["rows"],
        "ann_return": metric["ann_return"],
        "ann_vol": metric["ann_vol"],
        "sharpe_repo": metric["sharpe_repo"],
        "max_dd": metric["max_dd"],
        "avg_weight": metric["avg_weight"],
        "avg_exposure": metric.get("avg_exposure", metric["avg_weight"]),
        "avg_turnover": metric["avg_turnover"],
        "holding_days": metric["holding_days"],
        "holding_day_ratio": metric["holding_day_ratio"],
        "final_nav": metric.get("final_nav"),
        "suppressed_active_days": int((active_scale_delta > 1e-12).sum()),
        "avg_active_raw_scale": float(raw[active].mean()) if active.any() else 0.0,
        "avg_active_final_scale": float(scale[active].mean()) if active.any() else 0.0,
    }


def main() -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    status_before = git_text(["status", "--short"])
    commit = git_text(["rev-parse", "HEAD"])
    branch = git_text(["branch", "--show-current"])

    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    daily_parts: list[pd.DataFrame] = []
    meta_sample: dict[str, object] | None = None
    baseline_curves: dict[float, pd.DataFrame] = {}
    grid = gate_grid()

    for gate in grid:
        candidate = pct_label(gate)
        curve, meta, metrics = build_candidate(gate)
        if meta_sample is None:
            meta_sample = meta
        if gate in (0.0, 0.08, 0.09, 0.10):
            baseline_curves[gate] = curve.copy()
        daily = curve[
            [
                "return",
                "nav",
                "gross_exposure",
                "raw_target_vol_scale",
                "target_vol_scale",
                "exec_signal",
                "nav_scale",
                "volhot_scale",
                "amount_scale",
            ]
        ].copy()
        daily["candidate"] = candidate
        daily["tv_gate"] = gate
        daily_parts.append(daily.reset_index(names="date"))

        wide = {"candidate": candidate, "tv_gate": gate}
        for metric in metrics:
            segment = str(metric["segment"])
            years = next(y for s, y in SEGMENTS if s == segment)
            long_rows.append(metric_row(candidate, gate, metric, curve, years))
            for key in [
                "ann_return",
                "ann_vol",
                "sharpe_repo",
                "max_dd",
                "avg_weight",
                "avg_turnover",
                "holding_day_ratio",
                "final_nav",
            ]:
                if key in metric:
                    wide[f"{key}_{segment}"] = metric[key]
        full = subset(curve, None)
        raw = pd.to_numeric(full["raw_target_vol_scale"], errors="coerce")
        scale = pd.to_numeric(full["target_vol_scale"], errors="coerce")
        active = pd.to_numeric(full["exec_signal"], errors="coerce").fillna(0.0) > 0.0
        wide["suppressed_active_days_full"] = int(((raw[active] - scale[active]).abs() > 1e-12).sum())
        wide["avg_active_raw_scale_full"] = float(raw[active].mean()) if active.any() else 0.0
        wide["avg_active_final_scale_full"] = float(scale[active].mean()) if active.any() else 0.0
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = pd.DataFrame(wide_rows).sort_values("tv_gate").reset_index(drop=True)

    no_gate = window_metrics.loc[window_metrics["tv_gate"] == 0.0].iloc[0]
    current = window_metrics.loc[window_metrics["tv_gate"] == 0.10].iloc[0]
    for prefix, base_row in [("vs_no_gate", no_gate), ("vs_current_10pct", current)]:
        for window in ["full", "last_10y", "last_5y", "last_3y", "last_1y"]:
            window_metrics[f"ann_delta_pp_{prefix}_{window}"] = (
                window_metrics[f"ann_return_{window}"] - float(base_row[f"ann_return_{window}"])
            ) * 100.0
            window_metrics[f"dd_delta_pp_{prefix}_{window}"] = (
                window_metrics[f"max_dd_{window}"] - float(base_row[f"max_dd_{window}"])
            ) * 100.0

    window_metrics["same_as_no_gate"] = (
        (window_metrics["ann_return_full"] - float(no_gate["ann_return_full"])).abs() < 1e-12
    ) & ((window_metrics["max_dd_full"] - float(no_gate["max_dd_full"])).abs() < 1e-12)
    window_metrics["return_loss_vs_no_gate_pp"] = -window_metrics["ann_delta_pp_vs_no_gate_full"]
    window_metrics["current_return_recovered_pp"] = window_metrics["ann_delta_pp_vs_current_10pct_full"]
    window_metrics["decision_hint"] = np.where(
        window_metrics["same_as_no_gate"],
        "equivalent_to_no_gate",
        np.where(window_metrics["return_loss_vs_no_gate_pp"] <= 0.25, "minor_loss", "material_loss"),
    )
    current_with_deltas = window_metrics.loc[window_metrics["tv_gate"] == 0.10].iloc[0]

    daily_curves = pd.concat(daily_parts, ignore_index=True)
    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily_curves.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")

    neighbor_cols = [
        "candidate",
        "tv_gate",
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
        "suppressed_active_days_full",
        "return_loss_vs_no_gate_pp",
        "current_return_recovered_pp",
        "decision_hint",
    ]
    focus = window_metrics[(window_metrics["tv_gate"] >= 0.075) & (window_metrics["tv_gate"] <= 0.105)].copy()
    focus[neighbor_cols].to_csv(RUN_DIR / "neighbor_focus.csv", index=False, encoding="utf-8-sig")

    best_recovery = window_metrics.sort_values(
        ["ann_return_full", "max_dd_full", "ann_return_last_5y"], ascending=[False, False, False]
    ).head(10)
    best_recovery[neighbor_cols].to_csv(RUN_DIR / "top_by_full_return.csv", index=False, encoding="utf-8-sig")

    data_meta = meta_sample or {}
    record_lines = [
        "# CYB/SZ50 Forward TV_GATE Rescan",
        "",
        "## Run Metadata",
        f"- created_at: {created_at}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `research_only_recommend_lower_gate_not_promoted`",
        "- stability_label: `wide_equivalent_region_below_8pct`",
        "",
        "## Research Question",
        "Rescan the final forward long-CYB/short-SZ50 target-vol gate because the current 10% gate reduces return too much.",
        "",
        "## Implementation Anchor",
        "- `final_adk_cyb_sz50_spread.py` is imported directly.",
        "- Only module global `TV_GATE` is overridden per candidate; all final overlays and costs stay unchanged.",
        "",
        "## Data Snapshot",
        f"- sample: {data_meta.get('common_start')} to {data_meta.get('common_end')}, rows {data_meta.get('common_rows')}.",
        f"- source_csv: `{data_meta.get('source_csv')}`",
        "",
        "## Cost and Execution Assumptions",
        "- Same as final forward script: T close signal -> T+1 close-to-close spread return.",
        "- Two-leg transaction cost on exposure changes.",
        "- NAV defense, volatility overheat, and CYB low-amount overlay remain enabled.",
        "",
        "## Runtime Override Plan",
        "- Research-only monkeypatch of `final_adk_cyb_sz50_spread.TV_GATE` inside this scan script.",
        "- No production script or Poe bot parameter was changed.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_cyb_sz50_forward_tv_gate_rescan.py\"`",
        "- `python \"scan_adk_cyb_sz50_forward_tv_gate_rescan.py\"`",
        "- `python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\finalize_quant_param_scan_run.py quant_param_scan_runs\\20260610_adk_cyb_sz50_forward_tv_gate_rescan --decision \"research_only_recommend_lower_gate_not_promoted\" --stability-label \"wide_equivalent_region_below_8pct\"`",
        "- `python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict quant_param_scan_runs\\20260610_adk_cyb_sz50_forward_tv_gate_rescan`",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `neighbor_focus.csv`",
        "- `top_by_full_return.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        best_recovery[neighbor_cols].to_markdown(index=False),
        "",
        "## Window Results",
        focus[neighbor_cols].to_markdown(index=False),
        "",
        "## Stability Classification",
        "- `0%` to `8%` is checked as the no-impact/equivalent region if `same_as_no_gate=True` in `window_metrics.csv`.",
        "- Dense neighbor checks from `8.0%` to `10.5%` show where the gate starts changing realized performance.",
        "",
        "## Decision",
        "Research-only recommendation: lower the forward TV_GATE away from 10%; do not promote until user approves.",
        "",
        "## User-Facing Summary",
        f"- candidates: {len(grid)}",
        f"- no_gate_full_ann: {float(no_gate['ann_return_full']):.8f}",
        f"- current_10pct_full_ann: {float(current['ann_return_full']):.8f}",
        f"- current_10pct_return_loss_pp: {float(current_with_deltas['return_loss_vs_no_gate_pp']):.4f}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": created_at,
        "project": "A-share ADK CYB/SZ50",
        "strategy": "forward_cyb_sz50_final",
        "repo_root": str(ROOT),
        "entrypoint": "final_adk_cyb_sz50_spread.py",
        "scan_script": str(ROOT / Path(__file__).name),
        "git_branch": branch,
        "git_commit": commit,
        "git_status_before": status_before,
        "git_status_after": git_text(["status", "--short"]),
        "scan_type": "fresh_final_forward_tv_gate_rescan",
        "parameter_group": "TV_GATE",
        "baseline": {
            "no_gate": 0.0,
            "current_gate": 0.10,
            "production_strategy_id": fwd.STRATEGY_ID,
        },
        "candidate_grid": grid,
        "source_change_rule": "research-only monkeypatch; no production default changed",
        "cost_model": data_meta.get("cost_model", {}),
        "data_snapshot": {
            "source_csv": data_meta.get("source_csv"),
            "common_start": data_meta.get("common_start"),
            "common_end": data_meta.get("common_end"),
            "common_rows": data_meta.get("common_rows"),
            "formal_start": data_meta.get("formal_start"),
        },
        "decision": "research_only_recommend_lower_gate_not_promoted",
        "stability_label": "wide_equivalent_region_below_8pct",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "neighbor_focus": str(RUN_DIR / "neighbor_focus.csv"),
            "top_by_full_return": str(RUN_DIR / "top_by_full_return.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "\n".join(
            [
                'python -m py_compile "scan_adk_cyb_sz50_forward_tv_gate_rescan.py"',
                'python "scan_adk_cyb_sz50_forward_tv_gate_rescan.py"',
                'python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\finalize_quant_param_scan_run.py quant_param_scan_runs\\20260610_adk_cyb_sz50_forward_tv_gate_rescan --decision "research_only_recommend_lower_gate_not_promoted" --stability-label "wide_equivalent_region_below_8pct"',
                'python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict quant_param_scan_runs\\20260610_adk_cyb_sz50_forward_tv_gate_rescan',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={data_meta.get('common_start')}->{data_meta.get('common_end')} rows={data_meta.get('common_rows')}")
    print(f"CANDIDATES={len(grid)}")
    print("TOP_BY_FULL_RETURN")
    print(best_recovery[neighbor_cols].to_string(index=False))
    print("NEIGHBOR_FOCUS")
    print(focus[neighbor_cols].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

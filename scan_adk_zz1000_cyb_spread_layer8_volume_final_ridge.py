"""Layer 8 final ridge around CYB low-volume defense for long ZZ1000 / short CYB."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import scan_adk_zz1000_cyb_spread_layer7_volume_after_l3_target_vol as l7

RUN_DIR = l7.base.ROOT / "quant_param_scan_runs" / "20260611_adk_zz1000_cyb_spread_long_only_v77_adk_spread_layer8_volume_final_ridge_cyb_low_after_l7"

VOLUME_WINDOWS = [40, 50, 60, 70, 80, 100, 120, 140]
LOW_THRESHOLDS = [0.85, 0.90, 0.95, 1.00, 1.05, 1.10]
CONFIRM_DAYS = [3, 4, 5, 6, 7]
VOLUME_SCALES = [0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in l7.INPUTS:
        rows.append(
            {
                **line,
                "candidate": f"l8ridge_{line['line']}_volume_off",
                "volume_feature": "off",
                "volume_window": 0,
                "volume_threshold": 0.0,
                "confirm_days": 0,
                "volume_scale": 1.0,
                "volume_enabled": False,
            }
        )
        for window in VOLUME_WINDOWS:
            for threshold in LOW_THRESHOLDS:
                for days in CONFIRM_DAYS:
                    for scale in VOLUME_SCALES:
                        rows.append(
                            {
                                **line,
                                "candidate": (
                                    f"l8ridge_{line['line']}_cyb_vol_low"
                                    f"_w{window}_thr{l7.fmt(threshold)}_d{days}_scale{l7.fmt(scale)}"
                                ),
                                "volume_feature": "cyb_vol_low",
                                "volume_window": window,
                                "volume_threshold": threshold,
                                "confirm_days": days,
                                "volume_scale": scale,
                                "volume_enabled": True,
                            }
                        )
    return rows


def write_layer8_record() -> None:
    wm = pd.read_csv(RUN_DIR / "window_metrics.csv")
    strict = pd.read_csv(RUN_DIR / "strict_full5y_pass.csv")
    ridge = pd.read_csv(RUN_DIR / "ridge_width.csv")
    cols = [
        "candidate",
        "line",
        "line_role",
        "volume_window",
        "volume_threshold",
        "confirm_days",
        "volume_scale",
        "volume_days_full",
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
    ]
    baselines = wm[wm["volume_enabled"] == False][cols]
    formal = wm[(wm["line"] == "primary_tv14_vw60_max1p25_db0p05") & (wm["volume_enabled"] == True)]
    formal_strict = formal[formal["strict_full5y_pass"]].sort_values(
        ["ann_return_full", "full_dd_improve_pp"], ascending=[False, False]
    )
    formal_dd = formal[formal["pass_loss_le_1p0pp"]].sort_values(
        ["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]
    )

    record_lines = [
        "# ZZ1000/CYB Layer 8 CYB Low-Volume Final Ridge",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer8_volume_final_ridge_complete_waiting_user_review`",
        "- stability: `cyb_low_volume_final_ridge`",
        "",
        "## Research Question",
        "Fine-scan the CYB low-volume defense around the accepted Layer 7 candidate `w60/thr1/d5/scale0.25`.",
        "",
        "## Implementation Anchor",
        "- Reuses Layer 7 real-data implementation and Sina same-source volume proxy panel.",
        "- Scans only `cyb_vol_low`; no new amount, NAV, decay, overheat, or entry-staging layer is added.",
        "- Volume trigger is shifted from T close to T+1 execution, then final exposure, turnover, cost, return, and NAV are recomputed.",
        "",
        "## Grid",
        f"- windows: `{VOLUME_WINDOWS}`",
        f"- low thresholds: `{LOW_THRESHOLDS}`",
        f"- confirm days: `{CONFIRM_DAYS}`",
        f"- scales: `{VOLUME_SCALES}`",
        "",
        "## Baselines",
        baselines.to_markdown(index=False),
        "",
        "## Formal Return-Led Strict Candidates",
        formal_strict[cols].head(25).to_markdown(index=False) if not formal_strict.empty else "No formal strict candidates.",
        "",
        "## Formal Drawdown-Led Candidates",
        formal_dd[cols].head(25).to_markdown(index=False) if not formal_dd.empty else "No formal DD candidates.",
        "",
        "## All-Line Strict Candidates",
        strict[cols].head(25).to_markdown(index=False) if not strict.empty else "No strict candidates.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 8 final ridge completed. Stop for user review before fixed-script landing.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta_path = RUN_DIR / "scan_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "entrypoint": str(Path(__file__).name),
            "scan_type": "layer8_volume_final_ridge_cyb_low_after_l7",
            "parameter_group": "cyb_low_volume_final_ridge_after_layer7",
            "candidate_grid": make_grid(),
            "decision": "layer8_volume_final_ridge_complete_waiting_user_review",
            "stability_label": "cyb_low_volume_final_ridge",
            "daily_curve_scope": "baselines plus top strict/full-loss candidates, not all ridge candidates",
        }
    )
    meta["outputs"]["record"] = str(RUN_DIR / "record.md")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_zz1000_cyb_spread_layer8_volume_final_ridge.py\"\n"
        "python \"scan_adk_zz1000_cyb_spread_layer8_volume_final_ridge.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )


def main() -> None:
    l7.RUN_DIR = RUN_DIR
    l7.VOLUME_WINDOWS = VOLUME_WINDOWS
    l7.LOW_THRESHOLDS = LOW_THRESHOLDS
    l7.CONFIRM_DAYS = CONFIRM_DAYS
    l7.VOLUME_SCALES = VOLUME_SCALES
    l7.make_grid = make_grid
    l7.main()
    write_layer8_record()


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


RUN_DIR = Path(__file__).resolve().parent
SUMMARY_CSV = RUN_DIR / "scan_summary.csv"
OUT_CSV = RUN_DIR / "ridge_width_analysis.csv"
OUT_MD = RUN_DIR / "ridge_width_analysis.md"

WINDOWS = ["full", "last_10y", "last_5y", "last_3y", "last_1y"]
TARGETS = [
    {
        "label": "formal_defensive_ridge",
        "candidate": "v25_lb22_hl8_th0p4_cost_only",
        "lookback": 22.0,
        "halflife": 8.0,
        "threshold": 0.4,
    },
    {
        "label": "recent_fast_ridge",
        "candidate": "v25_lb38_hl10_th0p0_cost_only",
        "lookback": 38.0,
        "halflife": 10.0,
        "threshold": 0.0,
    },
]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _contiguous_values(values: list[float], center: float, good: set[float]) -> list[float]:
    vals = sorted(float(v) for v in values)
    if center not in vals or center not in good:
        return []
    pos = vals.index(center)
    lo = pos
    hi = pos
    while lo - 1 >= 0 and vals[lo - 1] in good:
        lo -= 1
    while hi + 1 < len(vals) and vals[hi + 1] in good:
        hi += 1
    return vals[lo : hi + 1]


def _span(vals: list[float]) -> str:
    if not vals:
        return ""
    if len(vals) == 1:
        return f"{vals[0]:g}"
    return f"{min(vals):g}..{max(vals):g}"


def _summarize_axis(
    surface: pd.DataFrame,
    target: dict[str, Any],
    window: str,
    axis: str,
    tolerance: float = 0.95,
) -> dict[str, Any]:
    center_lb = float(target["lookback"])
    center_hl = float(target["halflife"])
    center = surface[(surface["lookback"].eq(center_lb)) & (surface["halflife"].eq(center_hl))]
    if center.empty:
        raise RuntimeError(f"missing center row: {target['candidate']} {window}")
    center_row = center.iloc[0]
    center_sharpe = float(center_row["sharpe_repo"])
    cutoff = center_sharpe * tolerance
    if axis == "lookback":
        axis_rows = surface[surface["halflife"].eq(center_hl)].copy()
        values = axis_rows["lookback"].astype(float).tolist()
        good = set(axis_rows[axis_rows["sharpe_repo"].astype(float).ge(cutoff)]["lookback"].astype(float).tolist())
        contiguous = _contiguous_values(values, center_lb, good)
    elif axis == "halflife":
        axis_rows = surface[surface["lookback"].eq(center_lb)].copy()
        values = axis_rows["halflife"].astype(float).tolist()
        good = set(axis_rows[axis_rows["sharpe_repo"].astype(float).ge(cutoff)]["halflife"].astype(float).tolist())
        contiguous = _contiguous_values(values, center_hl, good)
    else:
        raise ValueError(axis)
    return {
        "axis": axis,
        "center_sharpe": center_sharpe,
        "axis_cutoff_95pct_center_sharpe": cutoff,
        "axis_span_95pct_center_sharpe": _span(contiguous),
        "axis_count_95pct_center_sharpe": len(contiguous),
        "axis_left_width": float(center_lb - min(contiguous)) if axis == "lookback" and contiguous else np.nan,
        "axis_right_width": float(max(contiguous) - center_lb) if axis == "lookback" and contiguous else np.nan,
        "axis_low_width": float(center_hl - min(contiguous)) if axis == "halflife" and contiguous else np.nan,
        "axis_high_width": float(max(contiguous) - center_hl) if axis == "halflife" and contiguous else np.nan,
    }


def _surface_plateau(surface: pd.DataFrame, tolerance: float = 0.95) -> dict[str, Any]:
    peak = surface.sort_values(["sharpe_repo", "ann_return"], ascending=False).iloc[0]
    peak_sharpe = float(peak["sharpe_repo"])
    good = surface[surface["sharpe_repo"].astype(float).ge(peak_sharpe * tolerance)].copy()
    return {
        "surface_peak_candidate": peak["candidate"],
        "surface_peak_lb": float(peak["lookback"]),
        "surface_peak_hl": float(peak["halflife"]),
        "surface_peak_threshold": float(peak["threshold"]),
        "surface_peak_ann_return": float(peak["ann_return"]),
        "surface_peak_max_dd": float(peak["max_dd"]),
        "surface_peak_sharpe": peak_sharpe,
        "surface_95pct_peak_count": int(len(good)),
        "surface_95pct_peak_lb_span": _span(good["lookback"].astype(float).tolist()),
        "surface_95pct_peak_hl_span": _span(good["halflife"].astype(float).tolist()),
        "surface_95pct_peak_ann_min": float(good["ann_return"].min()),
        "surface_95pct_peak_ann_max": float(good["ann_return"].max()),
        "surface_95pct_peak_maxdd_min": float(good["max_dd"].min()),
        "surface_95pct_peak_maxdd_max": float(good["max_dd"].max()),
    }


def main() -> None:
    df = pd.read_csv(SUMMARY_CSV)
    rows: list[dict[str, Any]] = []
    lines = [
        "# Ridge Width Analysis",
        "",
        "Definitions:",
        "",
        "- Axis width: contiguous lookback or halflife values through the target point with Sharpe >= 95% of that target point in the same window.",
        "- Surface plateau: all points in the same threshold surface with Sharpe >= 95% of that window's peak Sharpe.",
        "",
    ]
    for target in TARGETS:
        lines.append(f"## {target['label']} `{target['candidate']}`")
        lines.append("")
        for window in WINDOWS:
            surface = df[
                df["segment"].eq(window)
                & df["candidate"].str.startswith("v25_lb")
                & df["threshold"].astype(float).eq(float(target["threshold"]))
            ].copy()
            center = surface[
                surface["lookback"].astype(float).eq(float(target["lookback"]))
                & surface["halflife"].astype(float).eq(float(target["halflife"]))
            ].iloc[0]
            plateau = _surface_plateau(surface)
            lb_axis = _summarize_axis(surface, target, window, "lookback")
            hl_axis = _summarize_axis(surface, target, window, "halflife")
            row = {
                "ridge_label": target["label"],
                "target_candidate": target["candidate"],
                "window": window,
                "target_lb": float(target["lookback"]),
                "target_hl": float(target["halflife"]),
                "target_threshold": float(target["threshold"]),
                "target_ann_return": float(center["ann_return"]),
                "target_max_dd": float(center["max_dd"]),
                "target_sharpe": float(center["sharpe_repo"]),
                **{f"lb_{k}": v for k, v in lb_axis.items() if k != "axis"},
                **{f"hl_{k}": v for k, v in hl_axis.items() if k != "axis"},
                **plateau,
            }
            rows.append(row)
            lines.append(
                f"- `{window}` target {float(center['ann_return']):.2%} / "
                f"{float(center['max_dd']):.2%} / Sharpe {float(center['sharpe_repo']):.2f}; "
                f"LB axis `{row['lb_axis_span_95pct_center_sharpe']}` "
                f"(left {row['lb_axis_left_width']:.0f}, right {row['lb_axis_right_width']:.0f}); "
                f"HL axis `{row['hl_axis_span_95pct_center_sharpe']}`; "
                f"surface 95% peak LB `{row['surface_95pct_peak_lb_span']}`, "
                f"HL `{row['surface_95pct_peak_hl_span']}`, count {row['surface_95pct_peak_count']}."
            )
        lines.append("")
    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RUN_DIR / "ridge_width_analysis.json").write_text(
        json.dumps(_json_safe({"rows": rows}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

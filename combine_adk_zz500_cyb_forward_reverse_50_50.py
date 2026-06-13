#!/usr/bin/env python
"""Combine ADK ZZ500/CYB forward and reverse spread sleeves at 50/50."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

import scan_adk_zz500_cyb_spread_long_only as base_scan


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

FORWARD_ID = "substrategy_zz500_cyb_confirm_strict_decay_volhot_amtlow"
REVERSE_ID = "substrategy_cyb_zz500_primary_nav3_volridge"
COMBO_ID = "combo_zz500_cyb_forward50_reverse50"


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _load_daily(output_dir: Path, strategy_id: str) -> pd.DataFrame:
    path = output_dir / f"{strategy_id}_daily.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing daily file: {path}")
    return pd.read_csv(path, parse_dates=["date"], encoding="utf-8-sig").set_index("date").sort_index()


def _load_metrics(output_dir: Path, strategy_id: str) -> dict[str, Any]:
    path = output_dir / f"{strategy_id}_metrics.json"
    if not path.exists():
        raise FileNotFoundError(f"missing metrics file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df[column], errors="coerce").fillna(0.0)


def build_combo(output_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    forward = _load_daily(output_dir, FORWARD_ID)
    reverse = _load_daily(output_dir, REVERSE_ID)
    forward_payload = _load_metrics(output_dir, FORWARD_ID)
    reverse_payload = _load_metrics(output_dir, REVERSE_ID)

    common_index = forward.index.intersection(reverse.index)
    if common_index.empty:
        raise ValueError("forward/reverse daily files have no common dates")
    forward = forward.reindex(common_index)
    reverse = reverse.reindex(common_index)

    combo = pd.DataFrame(index=common_index)
    combo["forward_return"] = _series(forward, "return")
    combo["reverse_return"] = _series(reverse, "return")
    combo["forward_cost"] = _series(forward, "cost")
    combo["reverse_cost"] = _series(reverse, "cost")
    combo["forward_turnover"] = _series(forward, "turnover")
    combo["reverse_turnover"] = _series(reverse, "turnover")
    combo["return"] = 0.5 * combo["forward_return"] + 0.5 * combo["reverse_return"]
    combo["gross_return"] = 0.5 * _series(forward, "gross_return") + 0.5 * _series(reverse, "gross_return")
    combo["cost"] = 0.5 * combo["forward_cost"] + 0.5 * combo["reverse_cost"]
    combo["turnover"] = 0.5 * combo["forward_turnover"] + 0.5 * combo["reverse_turnover"]
    combo["forward_weight"] = _series(forward, "weight")
    combo["reverse_weight"] = _series(reverse, "weight")
    combo["gross_exposure"] = 0.5 * combo["forward_weight"].abs() + 0.5 * combo["reverse_weight"].abs()
    combo["weight"] = combo["gross_exposure"]
    combo["net_zz500_exposure"] = 0.5 * combo["forward_weight"] - 0.5 * combo["reverse_weight"]
    combo["net_cyb_exposure"] = -combo["net_zz500_exposure"]
    combo["forward_nav"] = _series(forward, "nav")
    combo["reverse_nav"] = _series(reverse, "nav")
    combo["nav"] = (1.0 + combo["return"]).cumprod()

    both_active = (combo["forward_weight"].abs() > 1e-12) & (combo["reverse_weight"].abs() > 1e-12)
    meta = {
        "strategy_id": COMBO_ID,
        "components": {
            FORWARD_ID: {"weight": 0.5, "direction": "long ZZ500 / short CYB"},
            REVERSE_ID: {"weight": 0.5, "direction": "long CYB / short ZZ500"},
        },
        "combination_rule": "daily 50/50 blend of already-costed component net returns; no extra combo-level rebalance cost or netting cost credit",
        "common_start": common_index.min().date().isoformat(),
        "common_end": common_index.max().date().isoformat(),
        "common_rows": int(len(common_index)),
        "both_active_days": int(both_active.sum()),
        "forward_meta": forward_payload.get("meta", {}),
        "reverse_meta": reverse_payload.get("meta", {}),
        "annualization_days": base_scan.ANNUALIZATION_DAYS,
    }
    return combo, meta


def build_metrics(curve: pd.DataFrame, strategy_id: str = COMBO_ID) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment, years in base_scan.SEGMENTS:
        metrics = base_scan.metrics_for_segment(curve, segment, years)
        subset = curve if years is None else curve.loc[curve.index >= curve.index.max() - pd.DateOffset(years=int(years))]
        both_active = (subset["forward_weight"].abs() > 1e-12) & (subset["reverse_weight"].abs() > 1e-12)
        metrics["strategy_id"] = strategy_id
        metrics["both_active_days"] = int(both_active.sum())
        rows.append(metrics)
    return rows


def _component_metrics(combo: pd.DataFrame, label: str, prefix: str) -> list[dict[str, Any]]:
    rows = []
    component = pd.DataFrame(index=combo.index)
    component["return"] = combo[f"{prefix}_return"]
    component["weight"] = combo[f"{prefix}_weight"].abs()
    component["turnover"] = combo[f"{prefix}_turnover"]
    component["cost"] = combo[f"{prefix}_cost"]
    for segment, years in base_scan.SEGMENTS:
        metrics = base_scan.metrics_for_segment(component, segment, years)
        rows.append(
            {
                "strategy": label,
                "segment": metrics["segment"],
                "start": metrics["start"],
                "end": metrics["end"],
                "ann_return": float(metrics["ann_return"]),
                "max_dd": float(metrics["max_dd"]),
                "rows": int(metrics["rows"]),
            }
        )
    return rows


def build_comparison(combo: pd.DataFrame, combo_metrics: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    rows.extend(_component_metrics(combo, "long_ZZ500_short_CYB", "forward"))
    rows.extend(_component_metrics(combo, "long_CYB_short_ZZ500", "reverse"))
    rows.extend(
        {
            "strategy": "combo_50_50",
            "segment": row["segment"],
            "start": row["start"],
            "end": row["end"],
            "ann_return": float(row["ann_return"]),
            "max_dd": float(row["max_dd"]),
            "rows": int(row["rows"]),
        }
        for row in combo_metrics
    )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    combo, meta = build_combo(args.output_dir)
    metrics = build_metrics(combo)
    comparison = build_comparison(combo, metrics)

    daily_path = args.output_dir / f"{COMBO_ID}_daily.csv"
    metrics_path = args.output_dir / f"{COMBO_ID}_metrics.json"
    comparison_path = args.output_dir / f"{COMBO_ID}_comparison.csv"
    combo.to_csv(daily_path, index_label="date", encoding="utf-8-sig")
    comparison.to_csv(comparison_path, index=False, encoding="utf-8-sig")
    payload = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "meta": meta,
        "metrics": metrics,
        "comparison": comparison.to_dict(orient="records"),
        "outputs": {
            "daily": str(daily_path),
            "metrics": str(metrics_path),
            "comparison": str(comparison_path),
        },
    }
    metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"{COMBO_ID}")
    for item in metrics:
        print(
            f"{item['segment']}: Ann {pct(float(item['ann_return']))}, "
            f"MaxDD {pct(float(item['max_dd']))}, rows {int(item['rows'])}"
        )
    print(f"daily: {daily_path}")
    print(f"metrics: {metrics_path}")
    print(f"comparison: {comparison_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

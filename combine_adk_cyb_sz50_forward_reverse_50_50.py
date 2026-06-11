#!/usr/bin/env python
"""Combine ADK CYB/SZ50 forward and reverse spread sleeves at 50/50."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import scan_adk_cyb_sz50_spread_long_only as base_scan


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

FORWARD_ID = "final_cyb_sz50_return_nav6_volhot_w40_thr0p18_scale0p75_cyb_low_w20_thr1_d5_scale0p25"
REVERSE_ID = "final_reverse_sz50_cyb_neighbor_downonly_tv16_nav10_decay_volhigh_w60_thr1p25_d3_scale0"
COMBO_ID = "combo_cyb_sz50_forward50_reverse50"


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _load_forward(output_dir: Path) -> pd.DataFrame:
    path = output_dir / f"{FORWARD_ID}_daily.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing forward daily file: {path}")
    return pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()


def _load_forward_metrics(output_dir: Path) -> dict[str, object]:
    path = output_dir / f"{FORWARD_ID}_metrics.json"
    if not path.exists():
        raise FileNotFoundError(f"missing forward metrics file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_reverse(output_dir: Path) -> pd.DataFrame:
    path = output_dir / f"{REVERSE_ID}_daily.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing reverse daily file: {path}")
    return pd.read_csv(path, parse_dates=["date"], encoding="utf-8-sig").set_index("date").sort_index()


def _load_reverse_metrics(output_dir: Path) -> dict[str, object]:
    path = output_dir / f"{REVERSE_ID}_metrics.json"
    if not path.exists():
        raise FileNotFoundError(f"missing reverse metrics file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df[column], errors="coerce").fillna(0.0)


def build_combo(output_dir: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    forward = _load_forward(output_dir)
    forward_payload = _load_forward_metrics(output_dir)
    reverse = _load_reverse(output_dir)
    reverse_payload = _load_reverse_metrics(output_dir)

    common_index = forward.index.intersection(reverse.index)
    if common_index.empty:
        raise ValueError("forward/reverse daily files have no common dates")
    forward = forward.reindex(common_index)
    reverse = reverse.reindex(common_index)

    combo = pd.DataFrame(index=common_index)
    combo["forward_return"] = _series(forward, "return")
    combo["reverse_return"] = _series(reverse, "return")
    combo["return"] = 0.5 * combo["forward_return"] + 0.5 * combo["reverse_return"]
    combo["gross_return"] = 0.5 * _series(forward, "gross_return") + 0.5 * _series(reverse, "gross_return")
    combo["cost"] = 0.5 * _series(forward, "cost") + 0.5 * _series(reverse, "cost")
    combo["turnover"] = 0.5 * _series(forward, "turnover") + 0.5 * _series(reverse, "turnover")
    combo["forward_gross_exposure"] = _series(forward, "gross_exposure") if "gross_exposure" in forward else _series(forward, "weight")
    combo["reverse_gross_exposure"] = _series(reverse, "weight")
    combo["gross_exposure"] = 0.5 * combo["forward_gross_exposure"] + 0.5 * combo["reverse_gross_exposure"]
    combo["weight"] = combo["gross_exposure"]
    combo["forward_nav"] = _series(forward, "nav")
    combo["reverse_nav"] = _series(reverse, "nav")
    combo["nav"] = (1.0 + combo["return"]).cumprod()

    both_active = (combo["forward_gross_exposure"].abs() > 1e-12) & (combo["reverse_gross_exposure"].abs() > 1e-12)
    meta = {
        "strategy_id": COMBO_ID,
        "weights": {
            FORWARD_ID: 0.5,
            REVERSE_ID: 0.5,
        },
        "combination_rule": "daily blend of already-costed component net returns; no extra combo-level rebalance cost",
        "common_start": common_index.min().date().isoformat(),
        "common_end": common_index.max().date().isoformat(),
        "common_rows": int(len(common_index)),
        "both_active_days": int(both_active.sum()),
        "both_active_dates_head": [idx.date().isoformat() for idx in combo.index[both_active][:20]],
        "forward_meta": forward_payload.get("meta", {}),
        "reverse_meta": reverse_payload.get("meta", {}),
        "annualization_days": base_scan.ANNUALIZATION_DAYS,
    }
    return combo, meta


def build_metrics(combo: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for segment, years in base_scan.SEGMENTS:
        metrics = base_scan.metrics_for_segment(combo, segment, years)
        for key in ["sharpe_repo", "calmar"]:
            if key in metrics and pd.isna(metrics[key]):
                metrics[key] = 0.0
        subset = combo if years is None else combo.loc[combo.index >= combo.index.max() - pd.DateOffset(years=int(years))]
        both_active = (subset["forward_gross_exposure"].abs() > 1e-12) & (subset["reverse_gross_exposure"].abs() > 1e-12)
        metrics["both_active_days"] = int(both_active.sum())
        rows.append({"strategy_id": COMBO_ID, **metrics})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    combo, meta = build_combo(args.output_dir)
    metrics = build_metrics(combo)

    daily_path = args.output_dir / f"{COMBO_ID}_daily.csv"
    metrics_path = args.output_dir / f"{COMBO_ID}_metrics.json"
    combo.to_csv(daily_path, index_label="date")
    payload = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "meta": meta,
        "metrics": metrics,
        "outputs": {"daily": str(daily_path), "metrics": str(metrics_path)},
    }
    metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    full = next(item for item in metrics if item["segment"] == "full")
    print(f"{COMBO_ID}: Full Ann {pct(float(full['ann_return']))}, MaxDD {pct(float(full['max_dd']))}")
    print(f"daily: {daily_path}")
    print(f"metrics: {metrics_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Combine fixed ADK ZZ1000/SZ50 forward and reverse spread sleeves at 50/50."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import scan_adk_zz1000_hs300_spread_long_only as layer1


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

FORWARD_ID = "final_forward_zz1000_sz50_main_q0_tvdb0p075_low_abs_w40_thr1_days3_scale0p75"
REVERSE_ID = "final_reverse_sz50_zz1000_return_nav_score_q1_volhot_w20_thr0p18_scale0"
COMBO_ID = "combo_forward_zz1000_sz50_tvdb0p075_reverse_sz50_zz1000_50_50"


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _load_daily(output_dir: Path, strategy_id: str) -> pd.DataFrame:
    path = output_dir / f"{strategy_id}_daily.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing daily file: {path}")
    return pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()


def _load_metrics(output_dir: Path, strategy_id: str) -> dict[str, object]:
    path = output_dir / f"{strategy_id}_metrics.json"
    if not path.exists():
        raise FileNotFoundError(f"missing metrics file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_combo(output_dir: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    forward = _load_daily(output_dir, FORWARD_ID)
    reverse = _load_daily(output_dir, REVERSE_ID)
    forward_payload = _load_metrics(output_dir, FORWARD_ID)
    reverse_payload = _load_metrics(output_dir, REVERSE_ID)

    common_index = forward.index.intersection(reverse.index)
    if common_index.empty:
        raise ValueError("forward/reverse daily files have no common dates")
    forward = forward.reindex(common_index)
    reverse = reverse.reindex(common_index)

    combo_return = 0.5 * pd.to_numeric(forward["return"], errors="coerce").fillna(0.0) + 0.5 * pd.to_numeric(
        reverse["return"], errors="coerce"
    ).fillna(0.0)
    combo = pd.DataFrame(index=common_index)
    combo["forward_return"] = forward["return"]
    combo["reverse_return"] = reverse["return"]
    combo["return"] = combo_return
    combo["gross_return"] = 0.5 * pd.to_numeric(forward["gross_return"], errors="coerce").fillna(0.0) + 0.5 * pd.to_numeric(
        reverse["gross_return"], errors="coerce"
    ).fillna(0.0)
    combo["cost"] = 0.5 * pd.to_numeric(forward["cost"], errors="coerce").fillna(0.0) + 0.5 * pd.to_numeric(
        reverse["cost"], errors="coerce"
    ).fillna(0.0)
    combo["turnover"] = 0.5 * pd.to_numeric(forward["turnover"], errors="coerce").fillna(0.0) + 0.5 * pd.to_numeric(
        reverse["turnover"], errors="coerce"
    ).fillna(0.0)
    combo["forward_gross_exposure"] = pd.to_numeric(forward["gross_exposure"], errors="coerce").fillna(0.0)
    combo["reverse_gross_exposure"] = pd.to_numeric(reverse["gross_exposure"], errors="coerce").fillna(0.0)
    combo["gross_exposure"] = 0.5 * combo["forward_gross_exposure"] + 0.5 * combo["reverse_gross_exposure"]
    combo["forward_nav"] = forward["nav"]
    combo["reverse_nav"] = reverse["nav"]
    combo["nav"] = (1.0 + combo["return"]).cumprod()

    both_active = (combo["forward_gross_exposure"].abs() > 1e-12) & (combo["reverse_gross_exposure"].abs() > 1e-12)
    meta = {
        "strategy_id": COMBO_ID,
        "weights": {FORWARD_ID: 0.5, REVERSE_ID: 0.5},
        "combination_rule": "daily blend of already-costed component net returns; no extra combo-level rebalance cost",
        "common_start": common_index.min().date().isoformat(),
        "common_end": common_index.max().date().isoformat(),
        "common_rows": int(len(common_index)),
        "both_active_days": int(both_active.sum()),
        "both_active_dates": [idx.date().isoformat() for idx in combo.index[both_active]],
        "forward_meta": forward_payload.get("meta", {}),
        "reverse_meta": reverse_payload.get("meta", {}),
        "annualization_days": layer1.ANNUALIZATION_DAYS,
    }
    return combo, meta


def build_metrics(combo: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for segment, years in layer1.SEGMENTS:
        metrics = layer1.metrics_for_segment(combo, segment, years)
        for key in ["sharpe_repo", "calmar"]:
            if pd.isna(metrics[key]):
                metrics[key] = 0.0
        subset = combo if years is None else combo.loc[combo.index >= combo.index.max() - pd.DateOffset(years=int(years))]
        both_active = (subset["forward_gross_exposure"].abs() > 1e-12) & (subset["reverse_gross_exposure"].abs() > 1e-12)
        metrics["both_active_days"] = int(both_active.sum())
        rows.append({"strategy_id": COMBO_ID, "segment": segment, **metrics})
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

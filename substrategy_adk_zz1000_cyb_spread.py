#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Standalone ZZ1000/CYB ADK spread substrategy.

Finalized candidate:
long ZZ1000 / short CYB, Layer 3 target-vol baseline plus Layer 8
CYB low-volume defense `w60/thr1.05/d6/scale0.25`.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

import scan_adk_zz1000_cyb_spread_layer7_volume_after_l3_target_vol as layer7


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

SUBSTRATEGY_ID = "substrategy_zz1000_cyb_tv14_db5_cybvol_w60_thr1p05_d6_scale0p25"
STRATEGY_ID = SUBSTRATEGY_ID

DIRECTION = "long ZZ1000 / short CYB"
LONG_LEG = "ZZ1000"
SHORT_LEG = "CYB"
FORMAL_START = "2014-10-17"

LINE_NAME = "primary_tv14_vw60_max1p25_db0p05"
VOLUME_FEATURE = "cyb_vol_low"
VOLUME_WINDOW = 60
VOLUME_THRESHOLD = 1.05
VOLUME_CONFIRM_DAYS = 6
VOLUME_SCALE = 0.25


def _line() -> dict[str, Any]:
    for line in layer7.INPUTS:
        if line["line"] == LINE_NAME:
            return dict(line)
    raise KeyError(f"missing line: {LINE_NAME}")


def _subset(curve: pd.DataFrame, years: int | None) -> pd.DataFrame:
    if years is None or curve.empty:
        return curve
    return curve.loc[curve.index >= curve.index.max() - pd.DateOffset(years=int(years))]


def _volume_switch_counts(curve: pd.DataFrame, years: int | None) -> dict[str, Any]:
    subset = _subset(curve, years)
    if subset.empty:
        return {
            "volume_active_days": 0,
            "volume_entries": 0,
            "volume_recoveries": 0,
            "volume_switch_actions": 0,
            "volume_entries_per_year": 0.0,
            "volume_switch_actions_per_year": 0.0,
        }
    on = pd.to_numeric(subset["volume_on"], errors="coerce").fillna(0).gt(0)
    prev = on.shift(1, fill_value=False)
    entries = int((on & ~prev).sum())
    recoveries = int((~on & prev).sum())
    years_rows = len(subset) / layer7.base.ANNUALIZATION_DAYS
    return {
        "volume_active_days": int(on.sum()),
        "volume_entries": entries,
        "volume_recoveries": recoveries,
        "volume_switch_actions": entries + recoveries,
        "volume_entries_per_year": float(entries / years_rows) if years_rows > 0 else 0.0,
        "volume_switch_actions_per_year": float((entries + recoveries) / years_rows) if years_rows > 0 else 0.0,
    }


def build_curve() -> tuple[pd.DataFrame, dict[str, Any]]:
    line = _line()
    mod, zz1000_raw, cyb_raw, panel = layer7.l3.load_panel()
    volume_panel, volume_meta = layer7.load_volume_panel()
    volume_panel = volume_panel.reindex(panel.index)

    signal = layer7.l3.line_signal(panel, line)
    base_curve = layer7.l3.returns_for(panel, signal, line).copy()
    base_curve["spread_return"] = panel["spread_return"].reindex(base_curve.index).fillna(0.0)

    curve = layer7.apply_volume_overlay(
        base_curve,
        volume_panel,
        VOLUME_FEATURE,
        VOLUME_WINDOW,
        VOLUME_THRESHOLD,
        VOLUME_CONFIRM_DAYS,
        VOLUME_SCALE,
    )

    out = curve.copy()
    out["zz1000"] = panel["ZZ1000"].reindex(out.index)
    out["cyb"] = panel["CYB"].reindex(out.index)
    out["spread_close"] = panel["ratio"].reindex(out.index)
    out["signal_score"] = signal["score"].reindex(out.index)
    out["signal_r2"] = signal["r2"].reindex(out.index)
    out["abs_bias"] = signal["abs_bias"].reindex(out.index)
    out["execution_signal"] = base_curve["base_signal"].reindex(out.index)
    out["target_vol_raw_weight"] = base_curve["raw_weight"].reindex(out.index)
    out["target_vol_raw_scale"] = base_curve["raw_scale"].reindex(out.index)
    out["target_vol_applied_scale"] = base_curve["applied_scale"].reindex(out.index)
    out["target_vol_realized_vol"] = base_curve["realized_vol"].reindex(out.index)
    out["gross_exposure"] = out["weight"]
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["strategy_id"] = STRATEGY_ID
    out["candidate"] = (
        f"l8ridge_{LINE_NAME}_{VOLUME_FEATURE}"
        f"_w{VOLUME_WINDOW}_thr1p05_d{VOLUME_CONFIRM_DAYS}_scale0p25"
    )

    complete_volume = volume_panel[["zz1000_volume", "cyb_volume"]].apply(pd.to_numeric, errors="coerce").dropna()
    meta = {
        "strategy_id": STRATEGY_ID,
        "substrategy_id": SUBSTRATEGY_ID,
        "script_role": "standalone_substrategy",
        "direction": DIRECTION,
        "long_leg": LONG_LEG,
        "short_leg": SHORT_LEG,
        "formal_start": FORMAL_START,
        "common_start": str(panel.index.min().date()),
        "common_end": str(panel.index.max().date()),
        "common_rows": int(len(panel)),
        "zz1000_first_valid": str(zz1000_raw.index.min().date()),
        "zz1000_last_valid": str(zz1000_raw.index.max().date()),
        "cyb_first_valid": str(cyb_raw.index.min().date()),
        "cyb_last_valid": str(cyb_raw.index.max().date()),
        "price_source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
        "volume_source": "Sina same-source volume proxy; Sohu ZZ1000 history too short for full-sample formal use",
        "volume_meta": volume_meta,
        "volume_complete_rows": int(len(complete_volume)),
        "line": line,
        "target_vol": {
            "enabled": True,
            "target_vol": float(line["target_vol"]),
            "vol_window": int(line["vol_window"]),
            "max_leverage": float(line["max_leverage"]),
            "min_leverage": float(layer7.l3.MIN_LEVERAGE),
            "scale_deadband": float(line["scale_deadband"]),
        },
        "volume_filter": {
            "enabled": True,
            "feature": VOLUME_FEATURE,
            "window": VOLUME_WINDOW,
            "threshold": VOLUME_THRESHOLD,
            "confirm_days": VOLUME_CONFIRM_DAYS,
            "scale": VOLUME_SCALE,
            "timing": "T-close volume state shifted to T+1 execution exposure",
        },
        "disabled_overlays": {
            "nav_defense": "tested and not promoted",
            "momentum_decay": "tested and not promoted",
            "overheat_entry": "tested and not promoted",
            "amount": "not included; full-history formal source not promoted in this branch",
        },
        "cost_model": {
            "one_way_commission": layer7.base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close spread return",
        },
        "annualization_days": layer7.base.ANNUALIZATION_DAYS,
    }
    return out, meta


def build_metrics(curve: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment, years in layer7.base.SEGMENTS:
        metrics = layer7.metric_base.metrics_for_segment(curve, segment, years)
        subset = _subset(curve, years)
        subset_nav = (1.0 + subset["return"].astype(float)).cumprod()
        metrics["strategy_id"] = STRATEGY_ID
        metrics["substrategy_id"] = SUBSTRATEGY_ID
        metrics["avg_exposure"] = metrics["avg_weight"]
        metrics["final_nav"] = float(subset_nav.iloc[-1]) if not subset_nav.empty else 0.0
        metrics.update(_volume_switch_counts(curve, years))
        rows.append(metrics)
    return rows


def run(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    curve, meta = build_curve()
    metrics = build_metrics(curve)

    daily_path = output_dir / f"{SUBSTRATEGY_ID}_daily.csv"
    metrics_path = output_dir / f"{SUBSTRATEGY_ID}_metrics.json"

    curve.to_csv(daily_path, index_label="date", encoding="utf-8-sig")
    payload = {
        "strategy_id": STRATEGY_ID,
        "substrategy_id": SUBSTRATEGY_ID,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        "metrics": metrics,
        "outputs": {
            "daily_csv": str(daily_path),
            "metrics_json": str(metrics_path),
        },
    }
    metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run finalized standalone ZZ1000/CYB ADK spread substrategy.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = run(args.output_dir)
    full_row = next(row for row in payload["metrics"] if row["segment"] == "full")
    print(f"strategy_id: {payload['strategy_id']}")
    print(f"daily_csv: {payload['outputs']['daily_csv']}")
    print(f"metrics_json: {payload['outputs']['metrics_json']}")
    print(f"Full AnnRet: {full_row['ann_return']:.2%}")
    print(f"Full MaxDD: {full_row['max_dd']:.2%}")
    print(f"Volume entries/year: {full_row['volume_entries_per_year']:.2f}")


if __name__ == "__main__":
    main()

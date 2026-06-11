#!/usr/bin/env python
"""Fixed final ADK spread script: long CYB / short ZZ1000."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import scan_adk_cyb_zz1000_spread_layer6_overheat_entry as layer6
import scan_adk_cyb_zz1000_spread_long_only as base


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

STRATEGY_ID = "final_cyb_zz1000_tv14_max1p5_db0p375_volhot_w20_thr0p26_scale0"

LINE_NAME = "formal_s1_abs35_tv14_vw20_max1p5_db0p375"
VOLHOT_WINDOW = 20
VOLHOT_THRESHOLD = 0.26
VOLHOT_SCALE = 0.0


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _line() -> dict[str, object]:
    return {
        "line": LINE_NAME,
        "line_role": "formal_default",
        "anchor": "main_s1_abs35_m3",
        "target_vol": 0.14,
        "vol_window": 20,
        "max_leverage": 1.50,
        "scale_deadband": 0.375,
    }


def _anchor(line: dict[str, object]) -> dict[str, object]:
    for anchor in layer6.l3b.l3tv.ANCHORS:
        if anchor["anchor"] == line["anchor"]:
            return dict(anchor)
    raise KeyError(f"missing anchor: {line['anchor']}")


def build_curve() -> tuple[pd.DataFrame, dict[str, object]]:
    line = _line()
    anchor = _anchor(line)
    mod, cyb_raw, zz1000_raw, panel = layer6.l3b.l3tv.load_panel()

    signal = layer6.add_signal_fields(layer6.l3b.l3tv.anchor_signal(panel, anchor), anchor)
    base_curve = layer6.l3b_base_returns(panel, signal, line)
    curve = layer6.apply_overlay(
        base_curve,
        "volhot",
        {"window": VOLHOT_WINDOW, "threshold": VOLHOT_THRESHOLD, "scale": VOLHOT_SCALE},
    )

    out = curve.copy()
    out["cyb"] = base_curve["CYB"].reindex(out.index)
    out["zz1000"] = base_curve["ZZ1000"].reindex(out.index)
    out["spread_close"] = base_curve["ratio"].reindex(out.index)
    out["signal_score"] = base_curve["score"].reindex(out.index)
    out["raw_signal"] = base_curve["raw_signal"].reindex(out.index)
    out["target_vol_realized_vol"] = base_curve["realized_vol"].reindex(out.index)
    out["target_vol_raw_scale"] = base_curve["raw_scale"].reindex(out.index)
    out["target_vol_applied_scale"] = base_curve["applied_scale"].reindex(out.index)
    out["target_vol_base_weight"] = base_curve["base_weight"].reindex(out.index)
    out["volhot_realized_vol"] = out["overlay_aux"]
    out["volhot_gate"] = out["overlay_on"]
    out["volhot_scale"] = out["overlay_mult"]
    out["gross_exposure"] = out["weight"]
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["candidate"] = "stage2_tv14_max1p5_db0p375_volhot_w20_thr0p26_scale0p0"
    out["strategy_id"] = STRATEGY_ID

    meta = {
        "source_csv": str(base.ENTRYPOINT),
        "cyb_column": getattr(mod, "CN_DK_CYB_SECID", "0.399006"),
        "zz1000_column": getattr(mod, "CN_DK_ZZ1000_SECID", "1.000852"),
        "cyb_first_valid": str(cyb_raw.index.min().date()),
        "cyb_last_valid": str(cyb_raw.index.max().date()),
        "zz1000_first_valid": str(zz1000_raw.index.min().date()),
        "zz1000_last_valid": str(zz1000_raw.index.max().date()),
        "formal_start": str(base.FORMAL_START.date()),
        "common_start": str(panel.index.min().date()),
        "common_end": str(panel.index.max().date()),
        "common_rows": int(len(panel)),
        "strategy_id": STRATEGY_ID,
        "candidate": str(out["candidate"].iloc[0]),
        "direction": "long CYB / short ZZ1000",
        "asset_curve": "ChiNext price index / CSI 1000 price index",
        "signal": {
            "bias_ma": int(anchor["bias_ma"]),
            "mom_day": int(anchor["mom_day"]),
            "weight_end": float(anchor["weight_end"]),
            "score_threshold": float(anchor["score_threshold"]),
            "abs_mom_day": int(anchor["abs_ma"]),
            "abs_threshold": float(anchor["abs_threshold"]),
            "r2_threshold": 0.05,
        },
        "target_vol": {
            "enabled": True,
            "target_vol": float(line["target_vol"]),
            "target_vol_window": int(line["vol_window"]),
            "max_leverage": float(line["max_leverage"]),
            "min_leverage": float(layer6.l3b.l3tv.MIN_LEVERAGE),
            "scale_deadband": float(line["scale_deadband"]),
            "deadband_timing": "during active holding, keep last scale unless absolute raw-scale change exceeds deadband",
        },
        "vol_overheat": {
            "enabled": True,
            "window": VOLHOT_WINDOW,
            "threshold": VOLHOT_THRESHOLD,
            "scale": VOLHOT_SCALE,
            "timing": "prior-row spread realized volatility controls next execution exposure",
            "active_days_full": int(pd.to_numeric(out["volhot_gate"], errors="coerce").fillna(0).sum()),
            "rescan_note": "Downstream rescan selected w20/thr0.26/scale0.0; trigger days are cut to zero exposure.",
        },
        "disabled_overlays": {
            "nav_defense": "tested and not promoted",
            "momentum_decay": "tested and not promoted by user review",
            "entry_staging": "tested as close-only proxy and not promoted",
            "amount_volume": "not included in this fixed script",
        },
        "combination_rule": "final exposure = target-vol deadbanded exposure * volhot multiplier",
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close spread return",
        },
        "annualization_days": base.ANNUALIZATION_DAYS,
    }
    return out, meta


def _subset(curve: pd.DataFrame, years: int | None) -> pd.DataFrame:
    if years is None or curve.empty:
        return curve
    return curve.loc[curve.index >= curve.index.max() - pd.DateOffset(years=int(years))]


def _switch_counts(curve: pd.DataFrame, years: int | None) -> dict[str, object]:
    subset = _subset(curve, years)
    if subset.empty:
        return {
            "volhot_active_days": 0,
            "volhot_episodes": 0,
            "volhot_recoveries": 0,
            "volhot_switch_actions": 0,
            "volhot_switch_actions_per_year": 0.0,
        }
    active = subset["base_weight"].abs() > 1e-12
    on = pd.to_numeric(subset["volhot_gate"], errors="coerce").fillna(0).gt(0) & active
    prev = on.shift(1, fill_value=False)
    episodes = int((on & ~prev).sum())
    recoveries = int((~on & prev).sum())
    switch_actions = episodes + recoveries
    years_rows = len(subset) / base.ANNUALIZATION_DAYS
    return {
        "volhot_active_days": int(on.sum()),
        "volhot_episodes": episodes,
        "volhot_recoveries": recoveries,
        "volhot_switch_actions": switch_actions,
        "volhot_switch_actions_per_year": float(switch_actions / years_rows) if years_rows > 0 else 0.0,
    }


def build_metrics(curve: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for segment, years in base.SEGMENTS:
        metrics = base.metrics_for_segment(curve, segment, years)
        subset = _subset(curve, years)
        subset_nav = (1.0 + subset["return"].astype(float)).cumprod()
        metrics["strategy_id"] = STRATEGY_ID
        metrics["avg_exposure"] = metrics["avg_weight"]
        metrics["final_nav"] = float(subset_nav.iloc[-1]) if not subset_nav.empty else 0.0
        metrics.update(_switch_counts(curve, years))
        rows.append(metrics)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    curve, meta = build_curve()
    metrics = build_metrics(curve)

    daily_path = args.output_dir / f"{STRATEGY_ID}_daily.csv"
    metrics_path = args.output_dir / f"{STRATEGY_ID}_metrics.json"
    curve.to_csv(daily_path, index_label="date", encoding="utf-8-sig")
    payload = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "meta": meta,
        "metrics": metrics,
        "outputs": {"daily": str(daily_path), "metrics": str(metrics_path)},
    }
    metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    full = next(item for item in metrics if item["segment"] == "full")
    print(f"{STRATEGY_ID}: Full Ann {pct(float(full['ann_return']))}, MaxDD {pct(float(full['max_dd']))}")
    print(f"daily: {daily_path}")
    print(f"metrics: {metrics_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Fixed final ADK reverse spread script: long SZ50 / short CYB."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import scan_adk_cyb_sz50_spread_long_only as base_scan
import scan_adk_sz50_cyb_reverse_spread_layer7_volume_after_nav_decay_overheat as layer7


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

STRATEGY_ID = "final_reverse_sz50_cyb_neighbor_downonly_tv16_nav10_decay_volhigh_w60_thr1p25_d3_scale0"

LINE = {
    "line": "neighbor_downonly_tv16_w30_min0",
    "line_role": "defensive_neighbor",
    "branch": "neighbor_nav10_s025_decay030_rec080_w3_s0",
    "overlay_kind": "downonly_tv",
    "param_a": 0.16,
    "param_b": 30.0,
    "param_c": 0.0,
    "param_d": 0.09,
}
TV_GATE = 0.09

VOLUME_FEATURE = "sz50_vol_high"
VOLUME_WINDOW = 60
VOLUME_THRESHOLD = 1.25
VOLUME_CONFIRM_DAYS = 3
VOLUME_SCALE = 0.0


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _branch() -> dict[str, object]:
    return layer7.branch_config(str(LINE["branch"]))


def build_curve() -> tuple[pd.DataFrame, dict[str, object]]:
    mod, cyb_raw, sz50_raw, panel = layer7.l6.l5.load_panel()
    volume_panel, volume_meta = layer7.load_volume_panel()
    volume_panel = volume_panel.reindex(panel.index)

    base = layer7.line_base(panel, LINE)
    curve = layer7.apply_volume_overlay(
        base,
        volume_panel,
        VOLUME_FEATURE,
        VOLUME_WINDOW,
        VOLUME_THRESHOLD,
        VOLUME_CONFIRM_DAYS,
        VOLUME_SCALE,
    )

    out = curve.copy()
    out["cyb"] = panel["CYB"].reindex(out.index)
    out["sz50"] = panel["SZ50"].reindex(out.index)
    out["spread_close"] = panel["ratio"].reindex(out.index)
    out["gross_exposure"] = out["weight"]
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["candidate"] = "l7vol_neighbor_downonly_tv16_w30_min0_sz50_vol_high_w60_thr1p25_d3_scale0"
    out["line"] = str(LINE["line"])
    out["volume_feature"] = VOLUME_FEATURE

    branch = _branch()
    complete_volume_rows = volume_panel[["cyb_volume", "sz50_volume"]].apply(pd.to_numeric, errors="coerce").dropna()
    meta = {
        "source_csv": str(base_scan.ENTRYPOINT),
        "cyb_column": getattr(mod, "CN_DK_CYB_SECID", "0.399006"),
        "sz50_column": getattr(mod, "CN_DK_SZ50_SECID", "1.000016"),
        "cyb_first_valid": str(cyb_raw.index.min().date()),
        "cyb_last_valid": str(cyb_raw.index.max().date()),
        "sz50_first_valid": str(sz50_raw.index.min().date()),
        "sz50_last_valid": str(sz50_raw.index.max().date()),
        "formal_start": str(base_scan.FORMAL_START.date()),
        "common_start": str(panel.index.min().date()),
        "common_end": str(panel.index.max().date()),
        "common_rows": int(len(panel)),
        "strategy_id": STRATEGY_ID,
        "candidate": str(out["candidate"].iloc[0]),
        "direction": "long SZ50 / short CYB",
        "asset_curve": "SSE50 price index / ChiNext price index",
        "baseline": {
            "line": str(LINE["line"]),
            "branch": str(LINE["branch"]),
            "role": str(LINE["line_role"]),
            "label": "neighbor signal, TV16%, NAV10% scale25%, momentum decay to cash, down-only TV cap, SZ50 high-volume cash gate",
        },
        "signal": {
            "bias_ma": int(branch["bias_ma"]),
            "mom_day": int(branch["mom_day"]),
            "weight_end": float(branch["weight_end"]),
            "score_threshold": float(branch["score_threshold"]),
            "abs_mom_day": int(branch["abs_ma"]),
            "abs_threshold": float(branch["abs_threshold"]),
            "r2_threshold": 0.05,
        },
        "target_vol": {
            "enabled": True,
            "target_vol": float(branch["target_vol"]),
            "target_vol_window": int(branch["vol_window"]),
            "max_leverage": float(branch["max_leverage"]),
            "min_leverage": float(layer7.l6.l5.MIN_LEVERAGE),
        },
        "nav_defense": {
            "enabled": True,
            "threshold": float(branch["nav_threshold"]),
            "scale": float(branch["nav_scale"]),
            "timing": "prior-row pre-overlay candidate NAV drawdown",
        },
        "momentum_decay": {
            "enabled": True,
            "decay_threshold": float(branch["decay_threshold"]),
            "recovery_threshold": float(branch["recovery_threshold"]),
            "warmup_days": int(branch["warmup_days"]),
            "scale": float(branch["derisk_scale"]),
            "timing": "score peak decay shifted to next execution row",
        },
        "overheat": {
            "enabled": True,
            "kind": str(LINE["overlay_kind"]),
            "gate": float(LINE.get("param_d", TV_GATE)),
            "target_vol": float(LINE["param_a"]),
            "window": int(LINE["param_b"]),
            "min_scale": float(LINE["param_c"]),
            "timing": "prior-row realized volatility cap",
        },
        "volume_overlay": {
            "enabled": True,
            "family": VOLUME_FEATURE,
            "series": "sz50_volume / sz50_volume_rolling_mean",
            "window": VOLUME_WINDOW,
            "threshold": VOLUME_THRESHOLD,
            "confirm_days": VOLUME_CONFIRM_DAYS,
            "scale": VOLUME_SCALE,
            "timing": "T close volume condition shifted to T+1 execution",
        },
        "combination_rule": "final exposure = target-vol baseline exposure * NAV multiplier * score-decay multiplier * down-only-TV multiplier * SZ50-high-volume multiplier",
        "volume_data": {
            "volume_csv": str(layer7.VOLUME_CSV),
            "volume_meta": str(layer7.VOLUME_META),
            "source": "Sohu real volume panel",
            "complete_rows": int(len(complete_volume_rows)),
            "metadata": volume_meta,
        },
        "cost_model": {
            "one_way_commission": base_scan.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal -> T+1 close-to-close return",
        },
        "annualization_days": base_scan.ANNUALIZATION_DAYS,
    }
    return out, meta


def _subset(curve: pd.DataFrame, years: int | None) -> pd.DataFrame:
    if years is None or curve.empty:
        return curve
    return curve.loc[curve.index >= curve.index.max() - pd.DateOffset(years=int(years))]


def build_metrics(curve: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for segment, years in base_scan.SEGMENTS:
        metrics = base_scan.metrics_for_segment(curve, segment, years)
        subset = _subset(curve, years)
        subset_nav = (1.0 + subset["return"].astype(float)).cumprod()
        metrics["strategy_id"] = STRATEGY_ID
        metrics["avg_exposure"] = metrics["avg_weight"]
        metrics["final_nav"] = float(subset_nav.iloc[-1]) if not subset_nav.empty else 0.0
        metrics["nav_defense_days"] = int(pd.to_numeric(subset["nav_on"], errors="coerce").fillna(0).sum())
        metrics["momentum_decay_days"] = int(pd.to_numeric(subset["decay_on"], errors="coerce").fillna(0).sum())
        metrics["overheat_days"] = int(pd.to_numeric(subset["overheat_on"], errors="coerce").fillna(0).sum())
        metrics["volume_gate_days"] = int(pd.to_numeric(subset["volume_on"], errors="coerce").fillna(0).sum())
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

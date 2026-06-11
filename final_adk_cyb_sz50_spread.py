#!/usr/bin/env python
"""Fixed final ADK spread script: long CYB / short SZ50."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_sz50_spread_layer6_amount_after_nav_volhot as layer6
import scan_adk_cyb_sz50_spread_long_only as base


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

STRATEGY_ID = "final_cyb_sz50_return_nav6_volhot_w40_thr0p18_scale0p75_cyb_low_w20_thr1_d5_scale0p25"

ANCHOR_NAME = "main_nav6_volhot_w40"
AMOUNT_FEATURE = "cyb_low"
AMOUNT_WINDOW = 20
AMOUNT_THRESHOLD = 1.0
AMOUNT_CONFIRM_DAYS = 5
AMOUNT_SCALE = 0.25
TV_GATE = 0.10


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _anchor() -> dict[str, object]:
    for anchor in layer6.ANCHORS:
        if anchor["anchor"] == ANCHOR_NAME:
            return anchor
    raise KeyError(f"missing anchor: {ANCHOR_NAME}")


def build_curve() -> tuple[pd.DataFrame, dict[str, object]]:
    anchor = _anchor()
    p = layer6.BASE_PARAMS
    amount_panel = layer6.compose_amount_panel()
    mod, cyb_raw, sz50_raw, panel = layer6.load_price_panel()
    amount_panel = amount_panel.reindex(panel.index)

    ratio = panel["ratio"]
    feature = ratio / ratio.rolling(int(p["bias_ma"])).mean() - 1.0
    score = base.weighted_slope_score(feature, int(p["mom_day"]), float(p["weight_end"]))
    r2 = base.weighted_slope_r2(feature, int(p["mom_day"]), float(p["weight_end"]))
    abs_bias = ratio / ratio.rolling(int(p["abs_ma"])).mean() - 1.0
    raw_signal = ((score > float(p["score_threshold"])) & (r2 >= 0.05) & (abs_bias > float(p["abs_threshold"]))).astype(float)
    exec_signal = raw_signal.shift(1).fillna(0.0)

    target_vol_indicator = panel["spread_return"].rolling(int(p["vol_window"])).std() * np.sqrt(base.ANNUALIZATION_DAYS)
    raw_target_vol_scale = (
        (float(p["target_vol"]) / target_vol_indicator)
        .clip(layer6.MIN_LEVERAGE, float(p["max_leverage"]))
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
    )
    if TV_GATE > 0.0:
        target_vol_scale = raw_target_vol_scale.where(raw_target_vol_scale <= (1.0 - TV_GATE), 1.0)
    else:
        target_vol_scale = raw_target_vol_scale

    l3_weight = exec_signal * target_vol_scale

    warmup = max(
        int(p["bias_ma"]),
        int(p["mom_day"]),
        int(p["abs_ma"]),
        int(p["vol_window"]),
        int(anchor["volhot_window"]),
    ) + 2
    d = pd.DataFrame(
        {
            "cyb": panel["CYB"],
            "sz50": panel["SZ50"],
            "spread_close": ratio,
            "spread_return": panel["spread_return"],
            "signal_feature": feature,
            "score": score,
            "r2": r2,
            "abs_bias": abs_bias,
            "raw_signal": raw_signal,
            "exec_signal": exec_signal,
            "target_vol_indicator": target_vol_indicator,
            "raw_target_vol_scale": raw_target_vol_scale,
            "target_vol_scale": target_vol_scale,
            "l3_weight": l3_weight,
            "cyb_amount": amount_panel["cyb_amount"],
            "sz50_amount": amount_panel["sz50_amount"],
        },
        index=panel.index,
    ).iloc[warmup:].dropna(subset=["spread_return", "score", "target_vol_scale", "l3_weight"])

    l3_turnover = d["l3_weight"].diff().abs().fillna(d["l3_weight"].abs())
    l3_return = d["l3_weight"] * d["spread_return"] - l3_turnover * (2.0 * base.COMMISSION_ONE_WAY)
    pre_nav = (1.0 + l3_return).cumprod()
    pre_dd = pre_nav / pre_nav.cummax() - 1.0
    nav_gate = pre_dd.shift(1).fillna(0.0) <= -float(p["nav_threshold"])
    nav_scale = pd.Series(1.0, index=d.index)
    nav_scale.loc[nav_gate] = float(p["nav_scale"])
    nav_weight = d["l3_weight"] * nav_scale

    volhot_indicator = d["spread_return"].rolling(int(anchor["volhot_window"])).std() * np.sqrt(base.ANNUALIZATION_DAYS)
    volhot_gate = volhot_indicator.shift(1).fillna(0.0) >= float(anchor["volhot_threshold"])
    volhot_scale = pd.Series(1.0, index=d.index)
    volhot_scale.loc[volhot_gate] = float(anchor["volhot_scale"])
    base_weight = nav_weight * volhot_scale

    amount_indicator = layer6.amount_feature(amount_panel, AMOUNT_FEATURE, AMOUNT_WINDOW).reindex(d.index)
    amount_raw = amount_indicator <= AMOUNT_THRESHOLD
    amount_gate = layer6.confirmed_trigger(amount_raw, AMOUNT_CONFIRM_DAYS).shift(1, fill_value=False).astype(bool)
    amount_scale = pd.Series(1.0, index=d.index)
    amount_scale.loc[amount_gate] = AMOUNT_SCALE

    weight = base_weight * amount_scale
    turnover = weight.diff().abs().fillna(weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = weight * d["spread_return"]
    ret = gross_return - cost
    nav = (1.0 + ret).cumprod()

    out = d.copy()
    out["pre_overlay_nav"] = pre_nav
    out["base_nav"] = pre_nav
    out["pre_overlay_drawdown"] = pre_dd
    out["nav_defense_gate"] = nav_gate.astype(float)
    out["nav_scale"] = nav_scale
    out["volhot_indicator"] = volhot_indicator
    out["volhot_gate"] = volhot_gate.astype(float)
    out["volhot_scale"] = volhot_scale
    out["base_gross_exposure"] = base_weight
    out["amount_indicator"] = amount_indicator
    out["amount_ma_ratio"] = amount_indicator
    out["amount_gate"] = amount_gate.astype(float)
    out["amount_scale"] = amount_scale
    out["gross_exposure"] = weight
    out["weight"] = weight
    out["gross_return"] = gross_return
    out["cost"] = cost
    out["turnover"] = turnover
    out["return"] = ret
    out["nav"] = nav

    meta = {
        "source_csv": str(base.ENTRYPOINT),
        "cyb_column": getattr(mod, "CN_DK_CYB_SECID", "0.399006"),
        "sz50_column": getattr(mod, "CN_DK_SZ50_SECID", "1.000016"),
        "cyb_first_valid": str(cyb_raw.index.min().date()),
        "cyb_last_valid": str(cyb_raw.index.max().date()),
        "sz50_first_valid": str(sz50_raw.index.min().date()),
        "sz50_last_valid": str(sz50_raw.index.max().date()),
        "formal_start": str(base.FORMAL_START.date()),
        "common_start": str(panel.index.min().date()),
        "common_end": str(panel.index.max().date()),
        "common_rows": int(len(panel)),
        "strategy_id": STRATEGY_ID,
        "direction": "long CYB / short SZ50",
        "asset_curve": "ChiNext price index / SSE50 price index",
        "baseline": {
            "line": ANCHOR_NAME,
            "label": "score>5, abs30>1.5%, TV24%, NAV6% scale75%, volhot40>18% scale75%",
        },
        "signal": {
            "bias_ma": int(p["bias_ma"]),
            "mom_day": int(p["mom_day"]),
            "weight_end": float(p["weight_end"]),
            "score_threshold": float(p["score_threshold"]),
            "abs_mom_day": int(p["abs_ma"]),
            "abs_threshold": float(p["abs_threshold"]),
            "r2_threshold": 0.05,
        },
        "target_vol": {
            "enabled": True,
            "gate": float(TV_GATE),
            "target_vol": float(p["target_vol"]),
            "target_vol_window": int(p["vol_window"]),
            "max_leverage": float(p["max_leverage"]),
            "min_leverage": float(layer6.MIN_LEVERAGE),
        },
        "nav_defense": {
            "enabled": True,
            "threshold": float(p["nav_threshold"]),
            "scale": float(p["nav_scale"]),
            "timing": "prior-row pre-overlay candidate NAV drawdown",
        },
        "vol_overheat": {
            "enabled": True,
            "window": int(anchor["volhot_window"]),
            "threshold": float(anchor["volhot_threshold"]),
            "scale": float(anchor["volhot_scale"]),
            "timing": "prior-row realized volatility",
        },
        "amount_overlay": {
            "enabled": True,
            "family": AMOUNT_FEATURE,
            "series": "cyb_amount / cyb_amount_rolling_mean",
            "window": AMOUNT_WINDOW,
            "threshold": AMOUNT_THRESHOLD,
            "confirm_days": AMOUNT_CONFIRM_DAYS,
            "scale": AMOUNT_SCALE,
            "timing": "T close amount condition shifted to T+1 execution",
            "unit_warning": "raw CYB and SZ50 amount units differ; this rule uses CYB own-MA relative amount only",
        },
        "combination_rule": "final exposure = target-vol baseline exposure * NAV multiplier * volhot multiplier * CYB-low-amount multiplier",
        "amount_data": {
            "amount_csv": str(layer6.OUTPUT_AMOUNT),
            "amount_meta": str(layer6.OUTPUT_AMOUNT_META),
            "source": "composed local amount panel",
            "unit_warning": "raw CYB and SZ50 amount units differ; no raw CYB/SZ50 amount ratio is used",
        },
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal -> T+1 close-to-close return",
        },
        "annualization_days": base.ANNUALIZATION_DAYS,
    }
    return out, meta


def _subset(curve: pd.DataFrame, years: int | None) -> pd.DataFrame:
    if years is None or curve.empty:
        return curve
    return curve.loc[curve.index >= curve.index.max() - pd.DateOffset(years=int(years))]


def build_metrics(curve: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for segment, years in base.SEGMENTS:
        metrics = base.metrics_for_segment(curve, segment, years)
        subset = _subset(curve, years)
        subset_nav = (1.0 + subset["return"].astype(float)).cumprod()
        metrics["strategy_id"] = STRATEGY_ID
        metrics["avg_exposure"] = metrics["avg_weight"]
        metrics["final_nav"] = float(subset_nav.iloc[-1]) if not subset_nav.empty else 0.0
        metrics["nav_defense_days"] = int(pd.to_numeric(subset["nav_defense_gate"], errors="coerce").fillna(0).sum())
        metrics["volhot_days"] = int(pd.to_numeric(subset["volhot_gate"], errors="coerce").fillna(0).sum())
        metrics["amount_gate_days"] = int(pd.to_numeric(subset["amount_gate"], errors="coerce").fillna(0).sum())
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

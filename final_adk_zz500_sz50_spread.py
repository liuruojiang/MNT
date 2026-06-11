#!/usr/bin/env python
"""Fixed final ADK spread script: long ZZ500 / short SZ50."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import scan_adk_zz500_sz50_spread_layer9_amount as layer9
import scan_adk_zz500_sz50_spread_long_only as base


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

STRATEGY_ID = "final_zz500_sz50_width_confirm_decay045_zz500amtlow_w60_thr0p85_d3_scale0p25"

LINE_NAME = "width_confirm_decay_only"
AMOUNT_FEATURE = "zz500_amount_low"
AMOUNT_WINDOW = 60
AMOUNT_THRESHOLD = 0.85
AMOUNT_CONFIRM_DAYS = 3
AMOUNT_SCALE = 0.25


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _line() -> dict[str, object]:
    for line in layer9.INPUTS:
        if line["line"] == LINE_NAME:
            return dict(line)
    raise KeyError(f"missing final line: {LINE_NAME}")


def build_curve() -> tuple[pd.DataFrame, dict[str, object]]:
    line = _line()
    mod, zz500_raw, sz50_raw, panel = layer9.l3.load_panel()
    amount_panel, amount_meta = layer9.load_amount_panel()
    amount_panel = amount_panel.reindex(panel.index)

    layer6_curve = layer9.l7.layer6_base_returns(panel, line)
    curve = layer9.apply_amount_overlay(
        layer6_curve,
        amount_panel,
        AMOUNT_FEATURE,
        AMOUNT_WINDOW,
        AMOUNT_THRESHOLD,
        AMOUNT_CONFIRM_DAYS,
        AMOUNT_SCALE,
    )

    out = curve.copy()
    out["zz500"] = panel["ZZ500"].reindex(out.index)
    out["sz50"] = panel["SZ50"].reindex(out.index)
    out["spread_close"] = panel["ratio"].reindex(out.index)
    out["gross_exposure"] = out["weight"]
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["candidate"] = "l9amt_width_confirm_decay_only_zz500_amount_low_w60_thr0p85_d3_scale0p25"
    out["line"] = LINE_NAME
    out["amount_feature"] = AMOUNT_FEATURE
    out["amount_window"] = AMOUNT_WINDOW
    out["amount_threshold"] = AMOUNT_THRESHOLD
    out["amount_confirm_days"] = AMOUNT_CONFIRM_DAYS
    out["amount_scale_param"] = AMOUNT_SCALE

    for col in [
        "base_weight",
        "layer6_weight",
        "raw_signal",
        "nav_on",
        "nav_mult",
        "decay_on",
        "decay_mult",
        "score",
    ]:
        if col in layer6_curve.columns:
            out[col] = layer6_curve[col].reindex(out.index)

    complete_amount_rows = amount_panel[["zz500_amount", "sz50_amount"]].apply(pd.to_numeric, errors="coerce").dropna()
    meta = {
        "source_csv": str(base.ENTRYPOINT),
        "zz500_column": getattr(mod, "CN_DK_ZZ500_SECID", "1.000905"),
        "sz50_column": getattr(mod, "CN_DK_SZ50_SECID", "1.000016"),
        "zz500_publication_date": base.ZZ500_PUBLICATION_DATE,
        "sz50_publication_date": base.SZ50_PUBLICATION_DATE,
        "zz500_first_valid": str(zz500_raw.index.min().date()),
        "zz500_last_valid": str(zz500_raw.index.max().date()),
        "sz50_first_valid": str(sz50_raw.index.min().date()),
        "sz50_last_valid": str(sz50_raw.index.max().date()),
        "formal_start": str(base.FORMAL_START.date()),
        "common_start": str(panel.index.min().date()),
        "common_end": str(panel.index.max().date()),
        "common_rows": int(len(panel)),
        "strategy_id": STRATEGY_ID,
        "candidate": str(out["candidate"].iloc[0]),
        "direction": "long ZZ500 / short SZ50",
        "asset_curve": "CSI500 price index / SSE50 price index",
        "result_status": "quasi-formal fixed research script; close-to-close index spread with CSIndex official amount overlay and commission costs",
        "baseline": {
            "line": LINE_NAME,
            "source_candidate": str(line["source_candidate"]),
            "label": "width-confirm Layer 6 decay-only line plus Layer 9 CSIndex ZZ500 low-amount filter",
        },
        "signal": {
            "family": str(line["family"]),
            "bias_ma": int(line["bias_ma"]),
            "mom_day": int(line["mom_day"]),
            "weight_end": float(line["weight_end"]),
            "score_threshold": float(line["score_threshold"]),
            "abs_ma": int(line["abs_ma"]),
            "abs_threshold": float(line["abs_threshold"]),
            "r2_threshold": 0.05,
        },
        "target_vol": {
            "enabled": bool(line["tv_enabled"]),
            "target_vol": float(line["target_vol"]),
            "target_vol_window": int(line["vol_window"]),
            "max_leverage": float(line["max_leverage"]),
            "min_leverage": float(layer9.l3.MIN_LEVERAGE),
            "scale_deadband": float(line["scale_deadband"]),
        },
        "momentum_decay": {
            "enabled": True,
            "decay_threshold": float(line["decay_threshold"]),
            "recovery_threshold": float(line["recovery_threshold"]),
            "warmup_days": int(line["warmup_days"]),
            "scale": float(line["derisk_scale"]),
            "timing": "T close score-peak decay state shifted to T+1 execution",
        },
        "amount_overlay": {
            "enabled": True,
            "feature": AMOUNT_FEATURE,
            "series": "zz500_amount / zz500_amount_rolling_mean",
            "window": AMOUNT_WINDOW,
            "threshold": AMOUNT_THRESHOLD,
            "confirm_days": AMOUNT_CONFIRM_DAYS,
            "scale": AMOUNT_SCALE,
            "timing": "T close amount condition shifted to T+1 execution",
            "source": "CSIndex official tradingValue/amount",
        },
        "rejected_layers": {
            "nav_defense": "Layer 4 reviewed as weak; disabled",
            "overheat": "Layer 7 reviewed as return-costly or no-op; disabled",
            "entry_staging": "Layer 8 close-only diagnostic was not promoted; disabled",
        },
        "combination_rule": "final exposure = target-vol signal exposure * momentum-decay multiplier * ZZ500-low-amount multiplier",
        "amount_data": {
            "amount_csv": str(layer9.AMOUNT_CSV),
            "amount_meta": str(layer9.AMOUNT_META),
            "complete_rows_on_price_calendar": int(len(complete_amount_rows)),
            "metadata": amount_meta,
        },
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
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
        active = subset["pre_amount_weight"].abs() > 1e-12 if "pre_amount_weight" in subset else pd.Series(False, index=subset.index)
        metrics["strategy_id"] = STRATEGY_ID
        metrics["avg_exposure"] = metrics["avg_weight"]
        metrics["final_nav"] = float(subset_nav.iloc[-1]) if not subset_nav.empty else 0.0
        metrics["momentum_decay_days"] = int(pd.to_numeric(subset["decay_on"], errors="coerce").fillna(0).sum())
        metrics["amount_gate_days"] = int(pd.to_numeric(subset["amount_on"], errors="coerce").fillna(0).sum())
        metrics["decay_amount_overlap_days"] = int(((subset["decay_on"] > 0) & (subset["amount_on"] > 0)).sum())
        metrics["avg_amount_mult_active"] = (
            float(subset.loc[active, "amount_mult"].mean()) if active.any() else 1.0
        )
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

    print(STRATEGY_ID)
    for item in metrics:
        print(
            f"{item['segment']}: Ann {pct(float(item['ann_return']))}, "
            f"MaxDD {pct(float(item['max_dd']))}, "
            f"rows {int(item['rows'])}"
        )
    print(f"daily: {daily_path}")
    print(f"metrics: {metrics_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

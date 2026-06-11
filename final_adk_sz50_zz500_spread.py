#!/usr/bin/env python
"""Fixed final ADK spread script: long SZ50 / short ZZ500."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import scan_adk_sz50_zz500_spread_layer8_amount_volume as layer8
import scan_adk_sz50_zz500_spread_long_only as base


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

STRATEGY_ID = "final_sz50_zz500_score0_abs80_tv16_decay030_scorehot18_zz500amthot_w60_thr1p2_scale0p25"
LINE_NAME = "primary_scorehot18_s025"
AMOUNT_KIND = "zz500_amt_hot"
AMOUNT_WINDOW = 60
AMOUNT_THRESHOLD = 1.20
AMOUNT_SCALE = 0.25


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _line() -> dict[str, object]:
    for line in layer8.LINES:
        if line["line"] == LINE_NAME:
            return dict(line)
    raise KeyError(f"missing line: {LINE_NAME}")


def build_curve() -> tuple[pd.DataFrame, dict[str, object]]:
    line = _line()
    mod, sz50_raw, zz500_raw, panel = layer8.l3.load_panel()
    amount_panel, amount_meta = layer8.fetch_amount_panel(mod)
    amount_panel = amount_panel.reindex(panel.index)

    layer6_curve = layer8.layer6_base_returns(panel, line)
    curve = layer8.apply_amount_overlay(
        layer6_curve,
        amount_panel,
        AMOUNT_KIND,
        AMOUNT_WINDOW,
        AMOUNT_THRESHOLD,
        AMOUNT_SCALE,
    )

    out = curve.copy()
    out["sz50"] = panel["SZ50"].reindex(out.index)
    out["zz500"] = panel["ZZ500"].reindex(out.index)
    out["spread_close"] = panel["ratio"].reindex(out.index)
    out["gross_exposure"] = out["weight"]
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["candidate"] = (
        "l8_primary_scorehot18_s025_zz500_amthot_w60_thr1p2_scale0p25"
    )
    out["line"] = LINE_NAME
    out["amount_kind"] = AMOUNT_KIND
    out["amount_window"] = AMOUNT_WINDOW
    out["amount_threshold"] = AMOUNT_THRESHOLD
    out["amount_scale"] = AMOUNT_SCALE

    for col in ["layer5_weight", "overlay_mult", "overlay_aux", "decay_mult", "score_strength"]:
        if col in layer6_curve.columns:
            out[col] = layer6_curve[col].reindex(out.index)
    out["scorehot_mult"] = out.get("overlay_mult", pd.Series(index=out.index, dtype=float))
    out["scorehot_aux"] = out.get("overlay_aux", pd.Series(index=out.index, dtype=float))

    complete_amount_rows = amount_panel[["SZ50_amount", "ZZ500_amount"]].apply(pd.to_numeric, errors="coerce").dropna()
    meta = {
        "source_csv": str(base.ENTRYPOINT),
        "sz50_column": getattr(mod, "CN_DK_SZ50_SECID", "1.000016"),
        "zz500_column": getattr(mod, "CN_DK_ZZ500_SECID", "1.000905"),
        "sz50_publication_date": base.SZ50_PUBLICATION_DATE,
        "zz500_publication_date": base.ZZ500_PUBLICATION_DATE,
        "sz50_first_valid": str(sz50_raw.index.min().date()),
        "sz50_last_valid": str(sz50_raw.index.max().date()),
        "zz500_first_valid": str(zz500_raw.index.min().date()),
        "zz500_last_valid": str(zz500_raw.index.max().date()),
        "formal_start": str(base.FORMAL_START.date()),
        "common_start": str(panel.index.min().date()),
        "common_end": str(panel.index.max().date()),
        "common_rows": int(len(panel)),
        "strategy_id": STRATEGY_ID,
        "candidate": str(out["candidate"].iloc[0]),
        "direction": "long SZ50 / short ZZ500",
        "asset_curve": "SSE50 price index / CSI500 price index",
        "result_status": "quasi-formal research fixed script; close-to-close index spread with amount overlay and commission costs",
        "baseline": {
            "line": LINE_NAME,
            "layer6_candidate": str(line["layer6_candidate"]),
            "label": "Layer 6 primary after rejected NAV and rejected entry staging",
        },
        "signal": {
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
            "min_leverage": float(layer8.l3.MIN_LEVERAGE),
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
        "score_overheat": {
            "enabled": True,
            "kind": str(line["overheat_kind"]),
            "score_threshold": float(line["overheat_param_a"]),
            "scale": float(line["overheat_param_c"]),
            "timing": "prior-row score state",
        },
        "amount_overlay": {
            "enabled": True,
            "kind": AMOUNT_KIND,
            "series": "ZZ500_amount / ZZ500_amount_rolling_mean",
            "window": AMOUNT_WINDOW,
            "threshold": AMOUNT_THRESHOLD,
            "scale": AMOUNT_SCALE,
            "timing": "T close amount condition shifted to T+1 execution",
        },
        "rejected_layers": {
            "nav_defense": "Layer 4 reviewed as too small an improvement; disabled",
            "entry_staging": "Layer 7 close-to-close proxy worsened the main chain; disabled",
            "sz50_amount_cold": "Layer 8 width insufficient; disabled",
            "relative_sz50_zz500_amount_cold": "Layer 8 not promoted; disabled",
        },
        "combination_rule": "final exposure = target-vol signal exposure * momentum-decay multiplier * scorehot multiplier * ZZ500-amount-hot multiplier",
        "amount_data": {
            "metadata": amount_meta,
            "complete_rows_on_price_calendar": int(len(complete_amount_rows)),
            "source_note": "uses V7.7 _fetch_cn_amount_with_fallback for both indices",
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
        active = subset["layer6_weight"].abs() > 1e-12 if "layer6_weight" in subset else pd.Series(False, index=subset.index)
        metrics["strategy_id"] = STRATEGY_ID
        metrics["avg_exposure"] = metrics["avg_weight"]
        metrics["final_nav"] = float(subset_nav.iloc[-1]) if not subset_nav.empty else 0.0
        metrics["momentum_decay_days"] = int(pd.to_numeric(subset["decay_on"], errors="coerce").fillna(0).sum())
        metrics["scorehot_days"] = int(pd.to_numeric(subset["overheat_on"], errors="coerce").fillna(0).sum())
        metrics["amount_gate_days"] = int(pd.to_numeric(subset["amount_on"], errors="coerce").fillna(0).sum())
        metrics["overheat_amount_overlap_days"] = int(((subset["overheat_on"] > 0) & (subset["amount_on"] > 0)).sum())
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

#!/usr/bin/env python
"""Fixed final ADK spread script: long HS300 / short ZZ500."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import scan_adk_hs300_zz500_spread_layer9_amount as layer9
import scan_adk_hs300_zz500_spread_long_only as base


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

STRATEGY_ID = "final_hs300_zz500_primary_nav_zz500amthigh_w120_thr1p25_d1_scale0p25"

LINE_NAME = "primary_nav_only"
AMOUNT_FEATURE = "zz500_amount_high"
AMOUNT_WINDOW = 120
AMOUNT_THRESHOLD = 1.25
AMOUNT_CONFIRM_DAYS = 1
AMOUNT_SCALE = 0.25


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _line() -> dict[str, object]:
    for line in layer9.LINES:
        if line["line"] == LINE_NAME:
            return dict(line)
    raise KeyError(f"missing final line: {LINE_NAME}")


def build_curve() -> tuple[pd.DataFrame, dict[str, object]]:
    line = _line()
    mod, hs300_raw, zz500_raw, panel = layer9.l2.load_panel()
    scores, r2s, abs_bias = layer9.l2.precompute(panel)
    amount_panel, amount_meta = layer9.fetch_amount_panel(mod)
    amount_panel = amount_panel.reindex(panel.index)

    nav_curve = layer9.nav_base_returns(panel, line, scores, r2s, abs_bias)
    curve = layer9.apply_amount_overlay(
        nav_curve,
        amount_panel,
        AMOUNT_FEATURE,
        AMOUNT_WINDOW,
        AMOUNT_THRESHOLD,
        AMOUNT_CONFIRM_DAYS,
        AMOUNT_SCALE,
    )

    out = curve.copy()
    out["hs300"] = panel["HS300"].reindex(out.index)
    out["zz500"] = panel["ZZ500"].reindex(out.index)
    out["spread_close"] = panel["ratio"].reindex(out.index)
    out["gross_exposure"] = out["weight"]
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["candidate"] = "l10ridge_primary_nav_only_zz500_amount_high_w120_thr1p25_d1_scale0p25"
    out["line"] = LINE_NAME
    out["amount_feature"] = AMOUNT_FEATURE
    out["amount_window"] = AMOUNT_WINDOW
    out["amount_threshold"] = AMOUNT_THRESHOLD
    out["amount_confirm_days"] = AMOUNT_CONFIRM_DAYS
    out["amount_scale_param"] = AMOUNT_SCALE

    for col in [
        "base_weight",
        "nav_weight",
        "nav_on",
        "nav_defense_mult",
        "score",
        "r2",
        "realized_vol",
        "applied_scale",
        "raw_scale",
    ]:
        if col in nav_curve.columns:
            out[col] = nav_curve[col].reindex(out.index)

    complete_amount_rows = amount_panel[["HS300_amount", "ZZ500_amount"]].apply(pd.to_numeric, errors="coerce").dropna()
    meta = {
        "source_entrypoint": str(base.ENTRYPOINT),
        "hs300_column": getattr(mod, "CN_DK_HS300_SECID", "1.000300"),
        "zz500_column": getattr(mod, "CN_DK_ZZ500_SECID", "1.000905"),
        "hs300_publication_date": base.HS300_PUBLICATION_DATE,
        "zz500_publication_date": base.ZZ500_PUBLICATION_DATE,
        "hs300_first_valid": str(hs300_raw.index.min().date()),
        "hs300_last_valid": str(hs300_raw.index.max().date()),
        "zz500_first_valid": str(zz500_raw.index.min().date()),
        "zz500_last_valid": str(zz500_raw.index.max().date()),
        "formal_start": str(base.FORMAL_START.date()),
        "common_start": str(panel.index.min().date()),
        "common_end": str(panel.index.max().date()),
        "common_rows": int(len(panel)),
        "strategy_id": STRATEGY_ID,
        "candidate": str(out["candidate"].iloc[0]),
        "direction": "long HS300 / short ZZ500",
        "asset_curve": "CSI300 price index / CSI500 price index",
        "result_status": "quasi-formal fixed research script; close-to-close index spread with EastMoney amount overlay and commission costs",
        "baseline": {
            "line": LINE_NAME,
            "source_candidate": str(line["source_candidate"]),
            "label": "Layer 6 NAV-only primary line plus Layer 10 ZZ500 high-amount final ridge",
        },
        "signal": {
            "anchor": str(line["anchor"]),
            "bias_ma": int(line["bias_ma"]),
            "mom_day": int(line["mom_day"]),
            "weight_end": float(line["weight_end"]),
            "score_threshold": float(line["score_threshold"]),
            "abs_ma": int(line["abs_ma"]),
            "abs_threshold": float(line["abs_threshold"]),
            "r2_threshold": 0.05,
        },
        "target_vol": {
            "enabled": True,
            "target_vol": float(line["target_vol"]),
            "target_vol_window": int(line["vol_window"]),
            "max_leverage": float(line["max_leverage"]),
            "min_scale": float(line["min_scale"]),
            "deadband_mode": str(line["deadband_mode"]),
            "deadband_value": float(line["deadband_value"]),
        },
        "nav_defense": {
            "enabled": True,
            "nav_threshold": float(line["nav_threshold"]),
            "defense_scale": float(line["defense_scale"]),
            "timing": "prior-row pre-overlay NAV drawdown shifted to next execution row",
        },
        "amount_overlay": {
            "enabled": True,
            "feature": AMOUNT_FEATURE,
            "series": "ZZ500_amount / ZZ500_amount_rolling_mean",
            "window": AMOUNT_WINDOW,
            "threshold": AMOUNT_THRESHOLD,
            "confirm_days": AMOUNT_CONFIRM_DAYS,
            "scale": AMOUNT_SCALE,
            "timing": "T close amount condition shifted to T+1 execution",
            "source": amount_meta.get("ZZ500_source", "EastMoney amount"),
        },
        "rejected_layers": {
            "momentum_decay": "Layer 5 reviewed as return-costly; disabled",
            "overheat": "Layer 7 reviewed as not promoted; disabled",
            "entry_staging": "Layer 8 close-only diagnostic not promoted; disabled",
            "other_amount_features": "Layer 10 final ridge selected only ZZ500 high-amount family",
        },
        "combination_rule": "final exposure = NAV-only target-vol signal exposure * ZZ500-high-amount multiplier",
        "amount_data": {
            "metadata": amount_meta,
            "complete_rows_on_price_calendar": int(len(complete_amount_rows)),
            "source_note": "uses V7.7 _fetch_cn_amount_with_fallback for both indices",
        },
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
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
        metrics["nav_defense_days"] = int(pd.to_numeric(subset["nav_on"], errors="coerce").fillna(0).sum())
        metrics["amount_gate_days"] = int(pd.to_numeric(subset["amount_on"], errors="coerce").fillna(0).sum())
        metrics["nav_amount_overlap_days"] = int(((subset["nav_on"] > 0) & (subset["amount_on"] > 0)).sum())
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
            f"MaxDD {pct(float(item['max_dd']))}, rows {int(item['rows'])}"
        )
    print(f"daily: {daily_path}")
    print(f"metrics: {metrics_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

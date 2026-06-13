#!/usr/bin/env python
"""Fixed final ADK spread script: long ZZ500 / short CYB.

This landing script freezes the promoted Layer 9 amount-gate line. It keeps the
scan implementation as the source of truth and only exposes a stable runner for
portfolio/substrategy integration.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

import scan_adk_zz500_cyb_spread_layer9_amount as layer9


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

STRATEGY_ID = "final_zz500_cyb_confirm_strict_decay_volhot_amtlow"
DEFAULT_PROFILE = "main_confirm"

PROFILES: dict[str, dict[str, Any]] = {
    "main_confirm": {
        "strategy_id": "final_zz500_cyb_confirm_strict_decay_volhot_amtlow",
        "candidate": "l9amt_confirm_strict_small_decay_zz500_amount_low_w40_thr1_d3_scale0",
        "line": "confirm_strict_small_decay",
        "label": "main_strict_full_5y_width_supported",
        "amount_feature": "zz500_amount_low",
        "amount_window": 40,
        "amount_threshold": 1.00,
        "amount_confirm_days": 3,
        "amount_scale": 0.0,
    },
    "strict_defensive": {
        "strategy_id": "final_zz500_cyb_confirm_defensive_decay_volhot_amtlow",
        "candidate": "l9amt_confirm_strict_defensive_decay_zz500_amount_low_w40_thr1_d5_scale0",
        "line": "confirm_strict_defensive_decay",
        "label": "strict_5y_defensive_watch",
        "amount_feature": "zz500_amount_low",
        "amount_window": 40,
        "amount_threshold": 1.00,
        "amount_confirm_days": 5,
        "amount_scale": 0.0,
    },
    "carry_dd": {
        "strategy_id": "final_zz500_cyb_confirm_carry_decay_volhot_amtlow",
        "candidate": "l9amt_confirm_carry_dd_decay_zz500_amount_low_w40_thr1_d3_scale0",
        "line": "confirm_carry_dd_decay",
        "label": "best_layer3_carry_dd_watch",
        "amount_feature": "zz500_amount_low",
        "amount_window": 40,
        "amount_threshold": 1.00,
        "amount_confirm_days": 3,
        "amount_scale": 0.0,
    },
    "primary_bias": {
        "strategy_id": "final_zz500_cyb_primary_bias_decay_volhot_amtlow",
        "candidate": "l9amt_primary_bias_dd_decay_cyb_amount_low_w60_thr1_d5_scale0",
        "line": "primary_bias_dd_decay",
        "label": "primary_bias_dd_watch",
        "amount_feature": "cyb_amount_low",
        "amount_window": 60,
        "amount_threshold": 1.00,
        "amount_confirm_days": 5,
        "amount_scale": 0.0,
    },
}


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _line(line_name: str) -> dict[str, object]:
    for line in layer9.LINES:
        if line["line"] == line_name:
            return dict(line)
    raise KeyError(f"missing Layer 9 line: {line_name}")


def _candidate(profile: dict[str, Any], line: dict[str, object]) -> dict[str, object]:
    return {
        **line,
        "candidate": profile["candidate"],
        "amount_enabled": True,
        "amount_feature": profile["amount_feature"],
        "amount_window": int(profile["amount_window"]),
        "amount_threshold": float(profile["amount_threshold"]),
        "confirm_days": int(profile["amount_confirm_days"]),
        "amount_scale": float(profile["amount_scale"]),
    }


def _subset(curve: pd.DataFrame, years: int | None) -> pd.DataFrame:
    if years is None or curve.empty:
        return curve
    return curve.loc[curve.index >= curve.index.max() - pd.DateOffset(years=int(years))]


def _sum_flag(frame: pd.DataFrame, column: str) -> int:
    if column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def build_curve(profile_name: str = DEFAULT_PROFILE) -> tuple[pd.DataFrame, dict[str, object]]:
    profile = dict(PROFILES[profile_name])
    line = _line(str(profile["line"]))

    mod, zz500_raw, cyb_raw, panel = layer9.l2.load_panel()
    scores, r2s, abs_bias = layer9.l2.precompute(panel)
    amount_panel, amount_meta = layer9.fetch_amount_panel(mod)
    amount_panel = amount_panel.reindex(panel.index)

    layer7_curve = layer9.layer7_base_returns(panel, line, scores, r2s, abs_bias)
    curve = layer9.run_candidate(
        _candidate(profile, line),
        {str(line["line"]): layer7_curve},
        amount_panel,
    )

    out = curve.copy()
    out["zz500"] = panel["ZZ500"].reindex(out.index)
    out["cyb"] = panel["CYB"].reindex(out.index)
    out["spread_close"] = panel["ratio"].reindex(out.index)
    out["gross_exposure"] = out["weight"]
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["strategy_id"] = profile["strategy_id"]
    out["profile"] = profile_name
    out["candidate"] = profile["candidate"]
    out["line"] = line["line"]
    out["amount_feature"] = profile["amount_feature"]
    out["amount_window"] = int(profile["amount_window"])
    out["amount_threshold"] = float(profile["amount_threshold"])
    out["amount_confirm_days"] = int(profile["amount_confirm_days"])
    out["amount_scale_param"] = float(profile["amount_scale"])

    passthrough_cols = {
        "base_weight": "target_vol_weight",
        "raw_signal": "raw_signal",
        "overlay_aux": "volhot_realized_vol",
    }
    for source_col, output_col in passthrough_cols.items():
        if source_col in layer7_curve.columns:
            out[output_col] = layer7_curve[source_col].reindex(out.index)

    complete_rows = amount_panel[["CYB_amount", "ZZ500_amount", "CYB_volume", "ZZ500_volume"]].apply(
        pd.to_numeric,
        errors="coerce",
    ).dropna()
    meta = {
        "source_entrypoint": str(layer9.base.ENTRYPOINT),
        "zz500_column": getattr(mod, "CN_DK_ZZ500_SECID", "1.000905"),
        "cyb_column": getattr(mod, "CN_DK_CYB_SECID", "0.399006"),
        "zz500_publication_date": layer9.base.ZZ500_PUBLICATION_DATE,
        "cyb_publication_date": layer9.base.CYB_PUBLICATION_DATE,
        "zz500_first_valid": str(zz500_raw.index.min().date()),
        "zz500_last_valid": str(zz500_raw.index.max().date()),
        "cyb_first_valid": str(cyb_raw.index.min().date()),
        "cyb_last_valid": str(cyb_raw.index.max().date()),
        "formal_start": str(layer9.base.FORMAL_START.date()),
        "common_start": str(panel.index.min().date()),
        "common_end": str(panel.index.max().date()),
        "common_rows": int(len(panel)),
        "strategy_id": profile["strategy_id"],
        "default_strategy_id": STRATEGY_ID,
        "profile": profile_name,
        "candidate": profile["candidate"],
        "direction": "long ZZ500 / short CYB",
        "asset_curve": "CSI500 price index / ChiNext price index",
        "result_status": "quasi-formal fixed research script; close-to-close index spread with V7.7 amount fallback and commission costs",
        "baseline": {
            "line": str(line["line"]),
            "line_role": str(line["line_role"]),
            "source_candidate": str(line["source_candidate"]),
            "layer7_candidate": str(line["layer7_candidate"]),
            "layer9_candidate": profile["candidate"],
        },
        "signal": {
            "anchor": str(line["anchor"]),
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
            "enabled": True,
            "target_vol": float(line["target_vol"]),
            "target_vol_window": int(line["vol_window"]),
            "max_leverage": float(line["max_leverage"]),
            "min_scale": float(line["min_scale"]),
            "deadband_mode": str(line["deadband_mode"]),
            "deadband_value": float(line["deadband_value"]),
        },
        "momentum_decay": {
            "enabled": True,
            "decay_ratio": float(line["decay_ratio"]),
            "recovery_ratio": float(line["recovery_ratio"]),
            "confirm_days": int(line["confirm_days"]),
            "derisk_scale": float(line["derisk_scale"]),
        },
        "volhot_overlay": {
            "enabled": True,
            "window": float(line["param_a"]),
            "threshold": float(line["param_b"]),
            "scale": float(line["param_c"]),
            "timing": "prior-row realized spread volatility shifted to next execution row",
        },
        "amount_overlay": {
            "enabled": True,
            "feature": str(profile["amount_feature"]),
            "window": int(profile["amount_window"]),
            "threshold": float(profile["amount_threshold"]),
            "confirm_days": int(profile["amount_confirm_days"]),
            "scale": float(profile["amount_scale"]),
            "timing": "T close amount condition shifted to T+1 execution",
            "source": amount_meta.get("ZZ500_source", "V7.7 amount fallback"),
        },
        "combination_rule": "final exposure = target-vol signal * momentum decay * volhot * amount gate",
        "external_data": {
            "metadata": amount_meta,
            "complete_amount_volume_rows_on_price_calendar": int(len(complete_rows)),
            "source_note": "uses V7.7 _fetch_cn_amount_with_fallback for amount and volume fields; only amount gate is active",
        },
        "cost_model": {
            "one_way_commission": layer9.base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "annualization_days": layer9.base.ANNUALIZATION_DAYS,
    }
    return out, meta


def build_metrics(curve: pd.DataFrame, strategy_id: str | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    sid = strategy_id or str(curve["strategy_id"].iloc[0])
    for segment, years in layer9.base.SEGMENTS:
        metrics = layer9.base.metrics_for_segment(curve, segment, years)
        subset = _subset(curve, years)
        subset_nav = (1.0 + subset["return"].astype(float)).cumprod()
        metrics["strategy_id"] = sid
        metrics["avg_exposure"] = metrics["avg_weight"]
        metrics["final_nav"] = float(subset_nav.iloc[-1]) if not subset_nav.empty else 0.0
        metrics["volhot_days"] = _sum_flag(subset, "overlay_on")
        metrics["amount_gate_days"] = _sum_flag(subset, "amount_on")
        rows.append(metrics)
    return rows


def run_profile(profile_name: str, output_dir: Path) -> dict[str, Any]:
    curve, meta = build_curve(profile_name)
    strategy_id = str(meta["strategy_id"])
    metrics = build_metrics(curve, strategy_id)
    daily_path = output_dir / f"{strategy_id}_daily.csv"
    metrics_path = output_dir / f"{strategy_id}_metrics.json"
    curve.to_csv(daily_path, index_label="date", encoding="utf-8-sig")
    payload = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "meta": meta,
        "metrics": metrics,
        "outputs": {"daily": str(daily_path), "metrics": str(metrics_path)},
    }
    metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=sorted(PROFILES), default=DEFAULT_PROFILE)
    parser.add_argument("--all-profiles", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    profile_names = sorted(PROFILES) if args.all_profiles else [args.profile]
    for profile_name in profile_names:
        payload = run_profile(profile_name, args.output_dir)
        print(payload["meta"]["strategy_id"])
        for item in payload["metrics"]:
            print(
                f"{item['segment']}: Ann {pct(float(item['ann_return']))}, "
                f"MaxDD {pct(float(item['max_dd']))}, rows {int(item['rows'])}"
            )
        print(f"daily: {payload['outputs']['daily']}")
        print(f"metrics: {payload['outputs']['metrics']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Fixed final ADK spread script: long ZZ500 / short HS300.

Default profile is the purple-column main-confirm line. Other final-ridge
profiles are kept selectable for review and portfolio-combination experiments.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

import scan_adk_zz500_hs300_spread_layer11_final_ridge as layer11


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

STRATEGY_ID = "final_zz500_hs300_purple_mainconfirm_amtlow_volridge"
DEFAULT_PROFILE = "main_confirm"

PROFILES: dict[str, dict[str, Any]] = {
    "main_confirm": {
        "strategy_id": "final_zz500_hs300_purple_mainconfirm_amtlow_volridge",
        "candidate": "l11ridge_main_confirm_pair_volume_high_w50_thr1p25_d5_scale0",
        "line": "main_confirm",
        "label": "purple_column_main_confirm",
        "volume_feature": "pair_volume_high",
        "volume_window": 50,
        "volume_threshold": 1.25,
        "volume_confirm_days": 5,
        "volume_scale": 0.0,
    },
    "return_preserve": {
        "strategy_id": "final_zz500_hs300_return_preserve_amtlow_volridge",
        "candidate": "l11ridge_return_preserve_hs300_volume_low_w60_thr0p7_d5_scale0",
        "line": "return_preserve",
        "label": "return_preserve_watchlist",
        "volume_feature": "hs300_volume_low",
        "volume_window": 60,
        "volume_threshold": 0.70,
        "volume_confirm_days": 5,
        "volume_scale": 0.0,
    },
    "primary_dd": {
        "strategy_id": "final_zz500_hs300_primary_dd_amtlow_volridge",
        "candidate": "l11ridge_primary_dd_pair_volume_low_w30_thr1_d7_scale0",
        "line": "primary_dd",
        "label": "primary_dd_first",
        "volume_feature": "pair_volume_low",
        "volume_window": 30,
        "volume_threshold": 1.00,
        "volume_confirm_days": 7,
        "volume_scale": 0.0,
    },
    "ultra_def": {
        "strategy_id": "final_zz500_hs300_ultra_def_amtlow_volridge",
        "candidate": "l11ridge_ultra_def_pair_volume_low_w30_thr1_d7_scale0",
        "line": "ultra_def",
        "label": "ultra_defensive_watchlist",
        "volume_feature": "pair_volume_low",
        "volume_window": 30,
        "volume_threshold": 1.00,
        "volume_confirm_days": 7,
        "volume_scale": 0.0,
    },
}


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _line(line_name: str) -> dict[str, object]:
    for line in layer11.LINES:
        if line["line"] == line_name:
            return dict(line)
    raise KeyError(f"missing final line: {line_name}")


def _candidate(profile: dict[str, Any], line: dict[str, object]) -> dict[str, object]:
    return {
        **line,
        "candidate": profile["candidate"],
        "ridge_enabled": True,
        "volume_feature": profile["volume_feature"],
        "volume_window": int(profile["volume_window"]),
        "volume_threshold": float(profile["volume_threshold"]),
        "volume_confirm_days": int(profile["volume_confirm_days"]),
        "volume_scale": float(profile["volume_scale"]),
    }


def build_curve(profile_name: str = DEFAULT_PROFILE) -> tuple[pd.DataFrame, dict[str, object]]:
    profile = dict(PROFILES[profile_name])
    line = _line(str(profile["line"]))

    mod, zz500_raw, hs300_raw, panel = layer11.l10.l9.l2.load_panel()
    scores, r2s, abs_bias = layer11.l10.l9.l2.precompute(panel)
    source_panel, source_meta = layer11.l10.l9.fetch_amount_panel(mod)
    source_panel = source_panel.reindex(panel.index)

    layer10_curve = layer11.layer10_base_returns(panel, source_panel, line, scores, r2s, abs_bias)
    curve = layer11.run_candidate(
        _candidate(profile, line),
        {str(line["line"]): layer10_curve},
        source_panel,
    )

    out = curve.copy()
    out["zz500"] = panel["ZZ500"].reindex(out.index)
    out["hs300"] = panel["HS300"].reindex(out.index)
    out["spread_close"] = panel["ratio"].reindex(out.index)
    out["gross_exposure"] = out["weight"]
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["strategy_id"] = profile["strategy_id"]
    out["profile"] = profile_name
    out["candidate"] = profile["candidate"]
    out["line"] = line["line"]
    out["amount_feature"] = line["amount_feature"]
    out["amount_window"] = int(line["amount_window"])
    out["amount_threshold"] = float(line["amount_threshold"])
    out["amount_confirm_days"] = int(line["amount_confirm_days"])
    out["amount_scale_param"] = float(line["amount_scale"])
    out["layer10_volume_feature"] = line["volume_feature"]
    out["layer10_volume_window"] = int(line["volume_window"])
    out["layer10_volume_threshold"] = float(line["volume_threshold"])
    out["layer10_volume_confirm_days"] = int(line["volume_confirm_days"])
    out["layer10_volume_scale_param"] = float(line["volume_scale"])
    out["final_volume_feature"] = profile["volume_feature"]
    out["final_volume_window"] = int(profile["volume_window"])
    out["final_volume_threshold"] = float(profile["volume_threshold"])
    out["final_volume_confirm_days"] = int(profile["volume_confirm_days"])
    out["final_volume_scale_param"] = float(profile["volume_scale"])

    passthrough_cols = {
        "layer10_weight": "layer10_weight",
        "volume_on": "layer10_volume_on",
        "volume_mult": "layer10_volume_mult",
        "volume_indicator": "layer10_volume_indicator",
    }
    for source_col, output_col in passthrough_cols.items():
        if source_col in layer10_curve.columns:
            out[output_col] = layer10_curve[source_col].reindex(out.index)

    complete_rows = source_panel[["HS300_amount", "ZZ500_amount", "HS300_volume", "ZZ500_volume"]].apply(
        pd.to_numeric,
        errors="coerce",
    ).dropna()
    meta = {
        "source_entrypoint": str(layer11.l10.l9.base.ENTRYPOINT),
        "hs300_column": getattr(mod, "CN_DK_HS300_SECID", "1.000300"),
        "zz500_column": getattr(mod, "CN_DK_ZZ500_SECID", "1.000905"),
        "hs300_publication_date": layer11.l10.l9.base.HS300_PUBLICATION_DATE,
        "zz500_publication_date": layer11.l10.l9.base.ZZ500_PUBLICATION_DATE,
        "hs300_first_valid": str(hs300_raw.index.min().date()),
        "hs300_last_valid": str(hs300_raw.index.max().date()),
        "zz500_first_valid": str(zz500_raw.index.min().date()),
        "zz500_last_valid": str(zz500_raw.index.max().date()),
        "formal_start": str(layer11.l10.l9.base.FORMAL_START.date()),
        "common_start": str(panel.index.min().date()),
        "common_end": str(panel.index.max().date()),
        "common_rows": int(len(panel)),
        "strategy_id": profile["strategy_id"],
        "default_strategy_id": STRATEGY_ID,
        "profile": profile_name,
        "candidate": profile["candidate"],
        "direction": "long ZZ500 / short HS300",
        "asset_curve": "CSI500 price index / CSI300 price index",
        "result_status": "quasi-formal fixed research script; close-to-close index spread with EastMoney amount/volume overlays and commission costs",
        "baseline": {
            "line": str(line["line"]),
            "line_role": str(line["line_role"]),
            "source_candidate": str(line["source_candidate"]),
            "layer7_candidate": str(line["layer7_candidate"]),
            "layer9_candidate": str(line["layer9_candidate"]),
            "layer10_candidate": str(line["layer10_candidate"]),
            "final_candidate": profile["candidate"],
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
        "volhot_overlay": {
            "enabled": True,
            "window": float(line["param_a"]),
            "threshold": float(line["param_b"]),
            "scale": float(line["param_c"]),
            "timing": "prior-row realized spread volatility shifted to next execution row",
        },
        "amount_overlay": {
            "enabled": True,
            "feature": str(line["amount_feature"]),
            "window": int(line["amount_window"]),
            "threshold": float(line["amount_threshold"]),
            "confirm_days": int(line["amount_confirm_days"]),
            "scale": float(line["amount_scale"]),
            "timing": "T close amount condition shifted to T+1 execution",
            "source": source_meta.get("ZZ500_source", "EastMoney amount"),
        },
        "layer10_volume_overlay": {
            "enabled": True,
            "feature": str(line["volume_feature"]),
            "window": int(line["volume_window"]),
            "threshold": float(line["volume_threshold"]),
            "confirm_days": int(line["volume_confirm_days"]),
            "scale": float(line["volume_scale"]),
        },
        "final_ridge_overlay": {
            "enabled": True,
            "feature": str(profile["volume_feature"]),
            "window": int(profile["volume_window"]),
            "threshold": float(profile["volume_threshold"]),
            "confirm_days": int(profile["volume_confirm_days"]),
            "scale": float(profile["volume_scale"]),
            "timing": "T close final-ridge volume condition shifted to T+1 execution",
        },
        "combination_rule": "final exposure = target-vol signal * volhot * amount gate * Layer10 volume gate * final-ridge volume gate",
        "external_data": {
            "metadata": source_meta,
            "complete_amount_volume_rows_on_price_calendar": int(len(complete_rows)),
            "source_note": "uses V7.7 _fetch_cn_amount_with_fallback for both amount and volume fields",
        },
        "cost_model": {
            "one_way_commission": layer11.l10.l9.base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "annualization_days": layer11.l10.l9.base.ANNUALIZATION_DAYS,
    }
    return out, meta


def _subset(curve: pd.DataFrame, years: int | None) -> pd.DataFrame:
    if years is None or curve.empty:
        return curve
    return curve.loc[curve.index >= curve.index.max() - pd.DateOffset(years=int(years))]


def build_metrics(curve: pd.DataFrame, strategy_id: str | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    sid = strategy_id or str(curve["strategy_id"].iloc[0])
    for segment, years in layer11.l10.l9.base.SEGMENTS:
        metrics = layer11.l10.l9.base.metrics_for_segment(curve, segment, years)
        subset = _subset(curve, years)
        subset_nav = (1.0 + subset["return"].astype(float)).cumprod()
        active = subset["pre_ridge_weight"].abs() > 1e-12 if "pre_ridge_weight" in subset else pd.Series(False, index=subset.index)
        metrics["strategy_id"] = sid
        metrics["avg_exposure"] = metrics["avg_weight"]
        metrics["final_nav"] = float(subset_nav.iloc[-1]) if not subset_nav.empty else 0.0
        metrics["volhot_days"] = int(pd.to_numeric(subset["overlay_on"], errors="coerce").fillna(0).sum())
        metrics["amount_gate_days"] = int(pd.to_numeric(subset["amount_on"], errors="coerce").fillna(0).sum())
        metrics["layer10_volume_days"] = int(pd.to_numeric(subset.get("layer10_volume_on", 0), errors="coerce").fillna(0).sum())
        metrics["final_ridge_days"] = int(pd.to_numeric(subset["ridge_on"], errors="coerce").fillna(0).sum())
        metrics["avg_final_ridge_mult_active"] = (
            float(subset.loc[active, "ridge_mult"].mean()) if active.any() else 1.0
        )
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

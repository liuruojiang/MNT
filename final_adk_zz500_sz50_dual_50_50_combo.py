#!/usr/bin/env python
"""Fixed 50/50 combo of long ZZ500/SZ50 and long SZ50/ZZ500 ADK spread sleeves."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import final_adk_sz50_zz500_spread as sz50_zz500
import final_adk_zz500_sz50_spread as zz500_sz50
import scan_adk_zz500_sz50_spread_long_only as base


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

STRATEGY_ID = "combo_zz500_sz50_forward50_reverse50"
ZZ500_SZ50_WEIGHT = 0.50
SZ50_ZZ500_WEIGHT = 0.50


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def build_curve() -> tuple[pd.DataFrame, dict[str, object]]:
    zz_curve, zz_meta = zz500_sz50.build_curve()
    sz_curve, sz_meta = sz50_zz500.build_curve()

    left = zz_curve.add_prefix("zz500_sz50_")
    right = sz_curve.add_prefix("sz50_zz500_")
    joined = pd.concat([left, right], axis=1, join="inner").copy()

    combo_return = (
        ZZ500_SZ50_WEIGHT * joined["zz500_sz50_return"]
        + SZ50_ZZ500_WEIGHT * joined["sz50_zz500_return"]
    )
    combo_gross_return = (
        ZZ500_SZ50_WEIGHT * joined["zz500_sz50_gross_return"]
        + SZ50_ZZ500_WEIGHT * joined["sz50_zz500_gross_return"]
    )
    combo_cost = (
        ZZ500_SZ50_WEIGHT * joined["zz500_sz50_cost"]
        + SZ50_ZZ500_WEIGHT * joined["sz50_zz500_cost"]
    )
    combo_turnover = (
        ZZ500_SZ50_WEIGHT * joined["zz500_sz50_turnover"]
        + SZ50_ZZ500_WEIGHT * joined["sz50_zz500_turnover"]
    )

    zz_weight = joined["zz500_sz50_weight"].astype(float)
    sz_weight = joined["sz50_zz500_weight"].astype(float)
    zz500_leg = ZZ500_SZ50_WEIGHT * zz_weight - SZ50_ZZ500_WEIGHT * sz_weight
    sz50_leg = -zz500_leg
    gross_pair_exposure = ZZ500_SZ50_WEIGHT * zz_weight.abs() + SZ50_ZZ500_WEIGHT * sz_weight.abs()

    out = pd.DataFrame(index=joined.index)
    out["return"] = combo_return
    out["gross_return"] = combo_gross_return
    out["cost"] = combo_cost
    out["turnover"] = combo_turnover
    out["weight"] = gross_pair_exposure
    out["gross_exposure"] = gross_pair_exposure
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["zz500_sz50_return"] = joined["zz500_sz50_return"]
    out["sz50_zz500_return"] = joined["sz50_zz500_return"]
    out["zz500_sz50_weight"] = zz_weight
    out["sz50_zz500_weight"] = sz_weight
    out["zz500_leg_exposure"] = zz500_leg
    out["sz50_leg_exposure"] = sz50_leg
    out["net_spread_exposure_zz500_minus_sz50"] = zz500_leg
    out["both_sleeves_active"] = ((zz_weight.abs() > 1e-12) & (sz_weight.abs() > 1e-12)).astype(int)
    out["zz500_sz50_active"] = (zz_weight.abs() > 1e-12).astype(int)
    out["sz50_zz500_active"] = (sz_weight.abs() > 1e-12).astype(int)
    out["candidate"] = STRATEGY_ID

    meta = {
        "strategy_id": STRATEGY_ID,
        "direction": "50/50 combo of long ZZ500 / short SZ50 and long SZ50 / short ZZ500",
        "result_status": "quasi-formal fixed research combo; daily fixed 50/50 sleeve weights, no extra portfolio-level rebalance friction",
        "formal_start": str(max(pd.Timestamp(zz_meta["formal_start"]), pd.Timestamp(sz_meta["formal_start"])).date()),
        "common_start": str(out.index.min().date()),
        "common_end": str(out.index.max().date()),
        "common_rows": int(len(out)),
        "sleeves": {
            "zz500_sz50": {
                "weight": ZZ500_SZ50_WEIGHT,
                "strategy_id": zz_meta["strategy_id"],
                "direction": zz_meta["direction"],
                "candidate": zz_meta["candidate"],
                "common_start": zz_meta["common_start"],
                "common_end": zz_meta["common_end"],
                "common_rows": zz_meta["common_rows"],
                "result_status": zz_meta["result_status"],
            },
            "sz50_zz500": {
                "weight": SZ50_ZZ500_WEIGHT,
                "strategy_id": sz_meta["strategy_id"],
                "direction": sz_meta["direction"],
                "candidate": sz_meta["candidate"],
                "common_start": sz_meta["common_start"],
                "common_end": sz_meta["common_end"],
                "common_rows": sz_meta["common_rows"],
                "result_status": sz_meta["result_status"],
            },
        },
        "combination_rule": "combo daily return = 0.5 * ZZ500/SZ50 sleeve return + 0.5 * SZ50/ZZ500 sleeve return",
        "leg_exposure_rule": "ZZ500 leg = 0.5 * ZZ500/SZ50 weight - 0.5 * SZ50/ZZ500 weight; SZ50 leg is the opposite",
        "cost_model": {
            "sleeve_costs": "each final sleeve already includes two-leg one-way commission on turnover",
            "portfolio_rebalance_cost": "excluded",
            "execution": "same common close-to-close daily return calendar as both sleeves",
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
        metrics["strategy_id"] = STRATEGY_ID
        metrics["avg_exposure"] = metrics["avg_weight"]
        metrics["final_nav"] = float(subset_nav.iloc[-1]) if not subset_nav.empty else 0.0
        metrics["zz500_sz50_active_days"] = int(subset["zz500_sz50_active"].sum())
        metrics["sz50_zz500_active_days"] = int(subset["sz50_zz500_active"].sum())
        metrics["both_sleeves_active_days"] = int(subset["both_sleeves_active"].sum())
        metrics["avg_net_spread_exposure_zz500_minus_sz50"] = float(
            subset["net_spread_exposure_zz500_minus_sz50"].mean()
        )
        metrics["avg_abs_net_spread_exposure"] = float(
            subset["net_spread_exposure_zz500_minus_sz50"].abs().mean()
        )
        metrics["sleeve_return_corr"] = float(
            subset[["zz500_sz50_return", "sz50_zz500_return"]].corr().iloc[0, 1]
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

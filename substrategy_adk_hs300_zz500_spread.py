#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Standalone HS300/ZZ500 ADK spread substrategy.

This file exposes the finalized HS300/ZZ500 sleeve as an importable
sub-strategy module for portfolio-combination scripts while keeping exact
parity with the verified final runner.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

import final_adk_hs300_zz500_spread as final_strategy


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

SUBSTRATEGY_ID = "substrategy_hs300_zz500_primary_nav_zz500amthigh_w120_thr1p25_d1_scale0p25"
STRATEGY_ID = SUBSTRATEGY_ID
SOURCE_STRATEGY_ID = final_strategy.STRATEGY_ID

DIRECTION = "long HS300 / short ZZ500"
LONG_LEG = "HS300"
SHORT_LEG = "ZZ500"
FORMAL_START = "2007-01-15"
LINE_NAME = final_strategy.LINE_NAME

AMOUNT_FEATURE = final_strategy.AMOUNT_FEATURE
AMOUNT_WINDOW = final_strategy.AMOUNT_WINDOW
AMOUNT_THRESHOLD = final_strategy.AMOUNT_THRESHOLD
AMOUNT_CONFIRM_DAYS = final_strategy.AMOUNT_CONFIRM_DAYS
AMOUNT_SCALE = final_strategy.AMOUNT_SCALE


def build_substrategy_curve() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build the finalized daily substrategy curve and metadata."""

    curve, meta = final_strategy.build_curve()
    curve = curve.copy()
    curve["substrategy_id"] = SUBSTRATEGY_ID
    curve["strategy_id"] = SUBSTRATEGY_ID
    curve["source_strategy_id"] = SOURCE_STRATEGY_ID

    meta = dict(meta)
    meta.update(
        {
            "strategy_id": SUBSTRATEGY_ID,
            "substrategy_id": SUBSTRATEGY_ID,
            "source_strategy_id": SOURCE_STRATEGY_ID,
            "script_role": "standalone_substrategy",
            "direction": DIRECTION,
            "long_leg": LONG_LEG,
            "short_leg": SHORT_LEG,
            "formal_start": FORMAL_START,
        }
    )
    return curve, meta


def build_curve() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Alias used by combination runners that expect build_curve()."""

    return build_substrategy_curve()


def build_metrics(curve: pd.DataFrame) -> list[dict[str, Any]]:
    """Build standard metrics for the standalone substrategy output."""

    metrics = final_strategy.build_metrics(curve)
    for row in metrics:
        row["strategy_id"] = SUBSTRATEGY_ID
        row["substrategy_id"] = SUBSTRATEGY_ID
        row["source_strategy_id"] = SOURCE_STRATEGY_ID
    return metrics


def run(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    """Write the standalone substrategy daily curve and metrics."""

    output_dir.mkdir(parents=True, exist_ok=True)
    curve, meta = build_substrategy_curve()
    metrics = build_metrics(curve)

    daily_path = output_dir / f"{SUBSTRATEGY_ID}_daily.csv"
    metrics_path = output_dir / f"{SUBSTRATEGY_ID}_metrics.json"

    daily = curve.reset_index()
    if daily.columns[0] != "date":
        daily = daily.rename(columns={daily.columns[0]: "date"})
    daily.to_csv(daily_path, index=False, encoding="utf-8-sig")
    payload = {
        "strategy_id": SUBSTRATEGY_ID,
        "substrategy_id": SUBSTRATEGY_ID,
        "source_strategy_id": SOURCE_STRATEGY_ID,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        "metrics": metrics,
        "outputs": {
            "daily_csv": str(daily_path),
            "metrics_json": str(metrics_path),
        },
    }
    metrics_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run finalized standalone HS300/ZZ500 ADK spread substrategy.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for daily CSV and metrics JSON outputs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = run(args.output_dir)
    full_row = next(
        row
        for row in payload["metrics"]
        if row.get("window") == "Full" or row.get("segment") == "full"
    )
    max_drawdown = full_row.get("max_drawdown", full_row.get("max_dd"))
    print(f"strategy_id: {payload['strategy_id']}")
    print(f"source_strategy_id: {payload['source_strategy_id']}")
    print(f"daily_csv: {payload['outputs']['daily_csv']}")
    print(f"metrics_json: {payload['outputs']['metrics_json']}")
    print(f"Full AnnRet: {full_row['ann_return']:.2%}")
    print(f"Full MaxDD: {max_drawdown:.2%}")


if __name__ == "__main__":
    main()

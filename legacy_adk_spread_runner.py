#!/usr/bin/env python
"""Legacy ADK spread runner for fixed artifact-seeded legs.

This runner is intentionally conservative: it treats the existing formal daily
artifact as the audited historical seed, then optionally applies the POE online
incremental extension path. It does not claim to reconstruct the original scan
from primitive parameters.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

import poe_adk_16_spread_v1_0_bot as poe16
import restored_adk_spread_runner as restored


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"

LEGACY_KEYS = {
    "forward_zz1000_hs300",
    "reverse_hs300_zz1000",
    "forward_cyb_hs300",
    "reverse_hs300_cyb",
    "forward_zz1000_sz50",
    "reverse_sz50_zz1000",
}


def _config_by_key() -> dict[str, poe16.StrategyConfig]:
    return {config.key: config for config in poe16.STRATEGIES}


def _load_meta(config: poe16.StrategyConfig) -> dict[str, Any]:
    metrics_path = poe16.OUTPUT_DIR / config.metrics_file
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    return payload.get("meta", payload)


def build_curve(key: str, *, extend_online: bool = True) -> tuple[pd.DataFrame, dict[str, Any]]:
    if key not in LEGACY_KEYS:
        raise KeyError(f"{key!r} is not a legacy artifact-seeded key")

    config = _config_by_key()[key]
    if key in restored.SUPPORTED_KEYS:
        curve, meta = restored.build_curve(key)
        online = {"ok": False, "data_mode": "local_source_recompute_only", "error": None}
        if extend_online:
            curves, online = poe16.load_performance_curves()
            if online.get("data_mode") != "local_artifacts_plus_online":
                raise RuntimeError(f"unexpected POE data_mode={online.get('data_mode')!r}")
            extension = curves[key].loc[curves[key].index > curve.index.max()].copy()
            if not extension.empty:
                curve = pd.concat([curve, extension], axis=0).sort_index()
                meta["recompute_status"] = "source_reconstructed_exact_plus_online"
            else:
                meta["recompute_status"] = "source_reconstructed_exact"
        meta.update(
            {
                "display_name": config.display_name,
                "history_seed_file": config.daily_file,
                "history_seed_metrics_file": config.metrics_file,
                "history_seed_source_dir": str(poe16.OUTPUT_DIR),
                "online_extension": online,
                "runner_note": (
                    "Historical rows are recomputed from local source data by "
                    "restored_adk_spread_runner; newer rows, when present, are "
                    "appended only through POE local_artifacts_plus_online."
                ),
            }
        )
        return curve, meta

    if extend_online:
        curves, online = poe16.load_performance_curves()
        if online.get("data_mode") != "local_artifacts_plus_online":
            raise RuntimeError(f"unexpected POE data_mode={online.get('data_mode')!r}")
    else:
        curves = poe16.load_strategy_curves()
        online = {"ok": False, "data_mode": "local_artifacts_only", "error": None}

    curve = curves[key].copy()
    meta = _load_meta(config)
    meta.update(
        {
            "strategy_id": key,
            "poe_strategy_key": key,
            "display_name": config.display_name,
            "recompute_status": "legacy_seed_extension",
            "history_seed_file": config.daily_file,
            "history_seed_metrics_file": config.metrics_file,
            "history_seed_source_dir": str(poe16.OUTPUT_DIR),
            "online_extension": online,
            "runner_note": (
                "Formal historical scan runner was not found in the current workspace. "
                "This entrypoint fixes the production path by replaying the audited daily "
                "artifact as historical seed and, when enabled, extending only newer rows "
                "through POE local_artifacts_plus_online."
            ),
        }
    )
    return curve, meta


def write_outputs(key: str, output_dir: Path, *, extend_online: bool = True) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    config = _config_by_key()[key]
    curve, meta = build_curve(key, extend_online=extend_online)
    daily_path = output_dir / config.daily_file
    metrics_path = output_dir / config.metrics_file
    curve.to_csv(daily_path, index_label="date", encoding="utf-8-sig")
    payload = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "meta": meta,
        "outputs": {"daily": str(daily_path), "metrics": str(metrics_path)},
    }
    metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return daily_path, metrics_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run legacy artifact-seeded ADK spread leg.")
    parser.add_argument("key", choices=sorted(LEGACY_KEYS))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-online", action="store_true", help="Replay only the local formal artifact seed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    daily_path, metrics_path = write_outputs(args.key, args.output_dir, extend_online=not args.no_online)
    print(args.key)
    print(f"daily: {daily_path}")
    print(f"metrics: {metrics_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

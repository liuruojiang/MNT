#!/usr/bin/env python
"""Source-reconstructed ADK spread runners recovered from artifacts and notes.

Only keys that have been re-derived and reconciled against the official daily
artifact belong here. Other legacy legs stay in ``legacy_adk_spread_runner``.
"""

from __future__ import annotations

import argparse
import builtins
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = ROOT / "mnt_bot V 7.7 plus.py"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"
ANNUALIZATION_DAYS = 242.0
ONE_WAY_COST = 0.0005

SUPPORTED_KEYS = {"forward_zz1000_hs300", "reverse_sz50_zz1000"}


class _PoeStub:
    query = None
    default_chat = []

    class BotError(Exception):
        pass

    @staticmethod
    def update_settings(_settings):
        return None


def _load_v77():
    import importlib.util

    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = _PoeStub()
    try:
        spec = importlib.util.spec_from_file_location("mnt_v77_restored_adk", str(ENTRYPOINT))
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if had_poe:
            builtins.poe = old_poe
        else:
            delattr(builtins, "poe")


def _bias_momentum_score(close: pd.Series, bias_ma: int, mom_day: int, weight_end: float) -> pd.Series:
    feature = close.astype(float) / close.astype(float).rolling(int(bias_ma)).mean()
    x = np.arange(int(mom_day), dtype=float)
    weights = np.linspace(1.0, float(weight_end), int(mom_day))
    weights = weights / weights.sum()
    x_bar = float((weights * x).sum())
    denom = float((weights * (x - x_bar) ** 2).sum())

    def calc(arr: np.ndarray) -> float:
        if not np.isfinite(arr).all() or abs(float(arr[0])) <= 1e-12:
            return np.nan
        y_bar = float((weights * arr).sum())
        slope = float((weights * (x - x_bar) * (arr - y_bar)).sum() / denom)
        return slope / float(arr[0]) * 10000.0

    return feature.rolling(int(mom_day)).apply(calc, raw=True)


def _metrics_for_segment(df: pd.DataFrame, segment: str, years: int | None) -> dict[str, object]:
    if years is None:
        d = df.copy()
    else:
        d = df.loc[df.index >= df.index.max() - pd.DateOffset(years=int(years))].copy()
    if d.empty:
        return {
            "segment": segment,
            "start": "",
            "end": "",
            "rows": 0,
            "ann_return": 0.0,
            "ann_vol": 0.0,
            "sharpe_repo": 0.0,
            "max_dd": 0.0,
            "avg_turnover": 0.0,
            "cost_total": 0.0,
            "avg_exposure": 0.0,
            "final_nav": 0.0,
        }
    ret = pd.to_numeric(d["return"], errors="coerce").fillna(0.0)
    nav = (1.0 + ret).cumprod()
    ann_return = float(nav.iloc[-1] ** (ANNUALIZATION_DAYS / len(d)) - 1.0)
    ann_vol = float(ret.std(ddof=0) * np.sqrt(ANNUALIZATION_DAYS))
    return {
        "segment": segment,
        "start": d.index.min().strftime("%Y-%m-%d"),
        "end": d.index.max().strftime("%Y-%m-%d"),
        "rows": int(len(d)),
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "sharpe_repo": float(ann_return / ann_vol) if ann_vol > 0 else 0.0,
        "max_dd": float((nav / nav.cummax() - 1.0).min()),
        "avg_turnover": float(pd.to_numeric(d["turnover"], errors="coerce").fillna(0.0).mean()),
        "cost_total": float(pd.to_numeric(d["cost"], errors="coerce").fillna(0.0).sum()),
        "avg_exposure": float(pd.to_numeric(d["gross_exposure"], errors="coerce").fillna(0.0).mean()),
        "final_nav": float(nav.iloc[-1]),
    }


def _forward_zz1000_hs300() -> tuple[pd.DataFrame, dict[str, Any]]:
    mod = _load_v77()
    zz1000 = mod._load_cn_official_cache(mod.CN_DK_ZZ1000_SECID).rename(columns={"close": "zz1000"})
    hs300 = mod._load_cn_official_cache(mod.CN_DK_HS300_SECID).rename(columns={"close": "hs300"})
    panel = pd.concat([zz1000["zz1000"], hs300["hs300"]], axis=1).dropna()
    panel = panel.loc[panel.index >= pd.Timestamp("2014-10-17")].copy()

    raw_ratio = panel["zz1000"] / panel["hs300"]
    spread_close = raw_ratio / raw_ratio.iloc[0]
    spread_return = spread_close.pct_change().fillna(0.0)
    score = _bias_momentum_score(spread_close, bias_ma=60, mom_day=20, weight_end=1.0)
    abs_mom = spread_close.pct_change(50)
    raw_signal = ((score > 0.0) & (abs_mom > -0.05)).astype(float)

    base_weight = raw_signal.shift(1).fillna(0.0)
    base_turnover = base_weight.diff().abs().fillna(base_weight.abs())
    base_return = base_weight * spread_return - base_turnover * ONE_WAY_COST
    base_nav = (1.0 + base_return).cumprod()
    base_dd = base_nav / base_nav.cummax() - 1.0
    nav_defense_gate = (base_dd.shift(1).fillna(0.0) <= -0.0875)
    nav_multiplier = pd.Series(np.where(nav_defense_gate, 0.0, 1.0), index=panel.index)

    amount_path = ROOT / "outputs" / "adk_zz1000_hs300_amount_csindex.csv"
    amount_panel = pd.read_csv(amount_path, parse_dates=["date"]).set_index("date").sort_index()
    amount_ma_ratio = amount_panel["zz1000_amount"] / amount_panel["zz1000_amount"].rolling(40).mean()
    amount_condition = amount_ma_ratio.lt(1.0).reindex(panel.index, fill_value=False).astype(bool)
    amount_gate = (amount_condition.shift(1, fill_value=False) & base_weight.gt(0) & ~nav_defense_gate).astype(int)
    amount_multiplier = pd.Series(np.where(amount_gate.astype(bool), 0.5, 1.0), index=panel.index)

    gross_exposure = base_weight * nav_multiplier * amount_multiplier
    turnover = gross_exposure.diff().abs().fillna(gross_exposure.abs())
    cost = turnover * ONE_WAY_COST
    gross_return = gross_exposure * spread_return
    ret = gross_return - cost
    out = pd.DataFrame(
        {
            "zz1000": panel["zz1000"],
            "hs300": panel["hs300"],
            "spread_close": spread_close,
            "score": score,
            "zz1000_amount": amount_panel["zz1000_amount"].reindex(panel.index),
            "hs300_amount": amount_panel["hs300_amount"].reindex(panel.index),
            "amount_ratio_zz1000_hs300": amount_panel["amount_ratio_zz1000_hs300"].reindex(panel.index),
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "gross_exposure": gross_exposure,
            "nav": (1.0 + ret).cumprod(),
            "nav_defense_gate": nav_defense_gate.astype(int),
            "amount_gate": amount_gate,
            "amount_ma_ratio": amount_ma_ratio.reindex(panel.index),
        },
        index=panel.index,
    )
    meta = {
        "strategy_id": "final_forward_zz1000_hs300_nav_low_abs_w40_thr1_days1_scale0p5",
        "poe_strategy_key": "forward_zz1000_hs300",
        "recompute_status": "source_reconstructed_exact",
        "source_reconstruction": {
            "evidence": [
                "outputs/final_adk_spread/final_forward_zz1000_hs300_nav_low_abs_w40_thr1_days1_scale0p5_metrics.json",
                "TASK_STATE.md",
                "docs/cleanup_record_20260609_031249.md",
            ],
            "note": "Original final script was cleaned on 2026-06-09; this runner was re-derived from artifact metadata and reconciled to the official daily artifact.",
        },
        "direction": "long ZZ1000 / short HS300",
        "asset_curve": "CSI1000 price index / CSI300 price index",
        "formal_start": "2014-10-17",
        "common_start": str(panel.index.min().date()),
        "common_end": str(out.dropna(how="all").index.max().date()),
        "common_rows": int(len(out)),
        "signal": {
            "bias_ma": 60,
            "mom_day": 20,
            "weight_end": 1.0,
            "score_threshold": 0.0,
            "abs_mom_day": 50,
            "abs_threshold": -0.05,
            "r2_filter": False,
        },
        "target_vol": {"enabled": False, "max_leverage": 1.0},
        "nav_defense": {
            "enabled": True,
            "threshold": 0.0875,
            "scale": 0.0,
            "timing": "prior-row pre-overlay candidate NAV drawdown",
        },
        "amount_overlay": {
            "enabled": True,
            "family": "low_abs",
            "series": "zz1000_amount",
            "window": 40,
            "threshold": 1.0,
            "confirm_days": 1,
            "scale": 0.5,
            "timing": "T close amount condition shifted to T+1 execution",
            "source": str(amount_path),
        },
        "cost_model": {"one_way_cost_bps": 5.0, "cost": "turnover * 5bp"},
        "annualization_days": ANNUALIZATION_DAYS,
    }
    return out, meta


def _reverse_sz50_zz1000() -> tuple[pd.DataFrame, dict[str, Any]]:
    mod = _load_v77()
    sz50 = mod._load_cn_official_cache(mod.CN_DK_SZ50_SECID).rename(columns={"close": "sz50"})
    zz1000 = mod._load_cn_official_cache(mod.CN_DK_ZZ1000_SECID).rename(columns={"close": "zz1000"})
    panel = pd.concat([sz50["sz50"], zz1000["zz1000"]], axis=1).dropna()
    panel = panel.loc[panel.index >= pd.Timestamp("2014-10-17")].copy()

    raw_ratio = panel["sz50"] / panel["zz1000"]
    spread_close = raw_ratio / raw_ratio.iloc[0]
    spread_return = spread_close.pct_change().fillna(0.0)
    score = _bias_momentum_score(spread_close, bias_ma=60, mom_day=20, weight_end=3.5)
    abs_mom = spread_close.pct_change(10)
    raw_signal = ((score > 0.0) & (abs_mom > -0.075)).astype(float)

    base_weight = raw_signal.shift(1).fillna(0.0)
    base_turnover = base_weight.diff().abs().fillna(base_weight.abs())
    base_return = base_weight * spread_return - base_turnover * ONE_WAY_COST
    base_nav = (1.0 + base_return).cumprod()
    base_dd = base_nav / base_nav.cummax() - 1.0
    nav_defense_gate = (base_dd.shift(1).fillna(0.0) <= -0.04)
    nav_multiplier = pd.Series(np.where(nav_defense_gate, 0.75, 1.0), index=panel.index)

    overheat_indicator = spread_return.rolling(20).std(ddof=0) * np.sqrt(ANNUALIZATION_DAYS)
    overheat_gate = overheat_indicator.shift(1).fillna(0.0).ge(0.18)
    overheat_scale = pd.Series(np.where(overheat_gate, 0.0, 1.0), index=panel.index)

    gross_exposure = base_weight * nav_multiplier * overheat_scale
    turnover = gross_exposure.diff().abs().fillna(gross_exposure.abs())
    cost = turnover * ONE_WAY_COST
    gross_return = gross_exposure * spread_return
    ret = gross_return - cost
    out = pd.DataFrame(
        {
            "zz1000": panel["zz1000"],
            "sz50": panel["sz50"],
            "spread_close": spread_close,
            "score": score,
            "base_gross_exposure": base_weight,
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "gross_exposure": gross_exposure,
            "nav": (1.0 + ret).cumprod(),
            "nav_defense_gate": nav_defense_gate.astype(int),
            "overheat_gate": overheat_gate.astype(int),
            "overheat_indicator": overheat_indicator,
            "overheat_scale": overheat_scale,
        },
        index=panel.index,
    )
    meta = {
        "strategy_id": "final_reverse_sz50_zz1000_return_nav_score_q1_volhot_w20_thr0p18_scale0",
        "poe_strategy_key": "reverse_sz50_zz1000",
        "recompute_status": "source_reconstructed_exact",
        "source_reconstruction": {
            "evidence": [
                "outputs/final_adk_spread/final_reverse_sz50_zz1000_return_nav_score_q1_volhot_w20_thr0p18_scale0_metrics.json",
                "TASK_STATE.md",
                "docs/cleanup_record_20260609_031249.md",
            ],
            "note": "Original final script was cleaned on 2026-06-09; this runner was re-derived from artifact metadata and reconciled to the official daily artifact.",
        },
        "direction": "long SZ50 / short ZZ1000",
        "asset_curve": "SSE50 price index / CSI1000 price index",
        "formal_start": "2014-10-17",
        "common_start": str(panel.index.min().date()),
        "common_end": str(out.dropna(how="all").index.max().date()),
        "common_rows": int(len(out)),
        "signal": {
            "bias_ma": 60,
            "mom_day": 20,
            "weight_end": 3.5,
            "score_threshold": 0.0,
            "abs_mom_day": 10,
            "abs_threshold": -0.075,
            "r2_filter": False,
        },
        "target_vol": {"enabled": False, "target_vol": None, "target_vol_window": None, "max_leverage": 1.0},
        "nav_defense": {
            "enabled": True,
            "threshold": 0.04,
            "scale": 0.75,
            "timing": "prior-row pre-overlay candidate NAV drawdown",
        },
        "vol_overheat": {
            "enabled": True,
            "window": 20,
            "threshold": 0.18,
            "scale": 0.0,
            "timing": "spread close realized volatility shifted to T+1 execution",
        },
        "amount_overlay": {
            "enabled": False,
            "reason": "Layer 10 high_abs remains watchlist evidence; not promoted into the fixed final runner.",
        },
        "cost_model": {"one_way_cost_bps": 5.0, "cost": "turnover * 5bp"},
        "annualization_days": ANNUALIZATION_DAYS,
    }
    return out, meta


def build_curve(key: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    if key == "forward_zz1000_hs300":
        return _forward_zz1000_hs300()
    if key == "reverse_sz50_zz1000":
        return _reverse_sz50_zz1000()
    raise KeyError(f"{key!r} is not a source-reconstructed ADK spread key")


def build_metrics(curve: pd.DataFrame, strategy_id: str) -> list[dict[str, object]]:
    rows = []
    for segment, years in [("full", None), ("last_10y", 10), ("last_5y", 5), ("last_3y", 3), ("last_1y", 1)]:
        rows.append({"strategy_id": strategy_id, **_metrics_for_segment(curve, segment, years)})
    return rows


def write_outputs(key: str, output_dir: Path) -> tuple[Path, Path]:
    curve, meta = build_curve(key)
    output_dir.mkdir(parents=True, exist_ok=True)
    strategy_id = str(meta["strategy_id"])
    daily_path = output_dir / f"{strategy_id}_daily.csv"
    metrics_path = output_dir / f"{strategy_id}_metrics.json"
    curve.to_csv(daily_path, index_label="date", encoding="utf-8-sig")
    payload = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "meta": meta,
        "metrics": build_metrics(curve, strategy_id),
        "outputs": {"daily": str(daily_path), "metrics": str(metrics_path)},
    }
    metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return daily_path, metrics_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a source-reconstructed ADK spread leg.")
    parser.add_argument("key", choices=sorted(SUPPORTED_KEYS))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    daily_path, metrics_path = write_outputs(args.key, args.output_dir)
    print(args.key)
    print(f"daily: {daily_path}")
    print(f"metrics: {metrics_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

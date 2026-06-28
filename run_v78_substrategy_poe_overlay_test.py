from __future__ import annotations

import importlib.util
import json
import math
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
V78_PATH = ROOT / "mnt_bot V 7.8 plus.py"
CN_LONG_PATH = Path(r"D:\动量策略\A 股股指多头策略\poe_cn_four_index_initial_equal_capital_combo_v1_2_bot.py")
US_LONG_PATH = Path(r"D:\动量策略\美股多头策略\poe_us_etf_five_long_momentum_v1_0_bot.py")
ADK_ALLOWED_DIR = ROOT / "outputs" / "adk_v77_16_overlay_poe_online5000_20260614"
DEFAULT_OUT_PREFIX = "v78_substrategy_poe_overlay"

WINDOWS = {
    "Full": None,
    "10Y": pd.DateOffset(years=10),
    "5Y": pd.DateOffset(years=5),
    "3Y": pd.DateOffset(years=3),
    "1Y": pd.DateOffset(years=1),
}

SUBA_GATE_MAP = {
    "1.000852": "zz1000",
    "1.000905": "zz500",
    "0.399006": "cyb",
}

SUBB_GATE_MAP = {
    "QQQ": "qqq",
    "QQQM": "qqq",
    "GLD": "gld",
    "GLDM": "gld",
    "AGG": "agg",
    "TLT": "agg",
    "IEF": "agg",
    "VGIT": "agg",
    "VGLT": "agg",
    "DBC": "dbc",
    "PDBC": "dbc",
    "BTC-USD": "btc",
    "IBIT": "btc",
    "EMXC": "vt",
    "EEM": "vt",
    "EFA": "vt",
    "VEA": "vt",
}


class QuietMsg:
    def write(self, _text: str) -> None:
        return None


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def slice_window(ret: pd.Series, offset: pd.DateOffset | None) -> pd.Series:
    ret = pd.to_numeric(ret, errors="coerce").dropna()
    if offset is not None and len(ret):
        ret = ret.loc[ret.index >= ret.index.max() - offset]
    return ret


def perf(ret: pd.Series, offset: pd.DateOffset | None, annual_days: float) -> dict[str, object]:
    x = slice_window(ret, offset)
    if x.empty:
        return {"start": "", "end": "", "rows": 0, "ann": np.nan, "max_dd": np.nan, "final_nav": np.nan}
    nav = (1.0 + x).cumprod()
    dd = nav / nav.cummax() - 1.0
    return {
        "start": x.index.min().date().isoformat(),
        "end": x.index.max().date().isoformat(),
        "rows": int(len(x)),
        "ann": float(nav.iloc[-1] ** (annual_days / len(x)) - 1.0) if len(x) > 1 else 0.0,
        "max_dd": float(dd.min()),
        "final_nav": float(nav.iloc[-1]),
    }


def write_window_metrics(path: Path, rows: list[dict[str, object]]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df


def shift_bool_frame(frame: pd.DataFrame, periods: int) -> pd.DataFrame:
    if periods <= 0:
        return frame.astype(bool)
    return frame.shift(periods).fillna(False).astype(bool)


def _date_label(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _align_external_bool_gate(frame: pd.DataFrame, index: pd.Index, label: str) -> pd.DataFrame:
    target = pd.DatetimeIndex(index)
    if target.empty:
        return frame.reindex(index).ffill().fillna(False).astype(bool)
    if frame.empty:
        raise ValueError(f"{label} source is empty; target index ends at {_date_label(target.max())}")
    source_end = pd.Timestamp(frame.index.max())
    target_end = pd.Timestamp(target.max())
    if source_end < target_end:
        raise ValueError(
            f"{label} source ends at {_date_label(source_end)} before target index ends at "
            f"{_date_label(target_end)}; refusing to forward-fill stale external gate"
        )
    return frame.reindex(index).ffill().fillna(False).astype(bool)


def suba_active_frame(cn_long, index: pd.Index, signal_shift_days: int = 0) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    curves, _combo, source_map, _errors = cn_long.load_all_curves(progress=None, include_realtime=False)
    active = pd.DataFrame(index=index)
    audit_rows = []
    for code, key in SUBA_GATE_MAP.items():
        curve = curves[key].copy()
        curve.index = pd.to_datetime(curve.index).normalize()
        if "final_weight" in curve.columns:
            signal = pd.to_numeric(curve["final_weight"], errors="coerce").fillna(0.0) > 1e-12
            col_used = "final_weight"
        else:
            signal = pd.to_numeric(curve["strategy_ret"], errors="coerce").fillna(0.0).abs() > 1e-12
            col_used = "strategy_ret_abs"
        active[code] = signal.reindex(index).ffill().fillna(False).astype(bool)
    active = shift_bool_frame(active, signal_shift_days)
    for code, key in SUBA_GATE_MAP.items():
        curve = curves[key].copy()
        curve.index = pd.to_datetime(curve.index).normalize()
        col_used = "final_weight" if "final_weight" in curve.columns else "strategy_ret_abs"
        audit_rows.append(
            {
                "code": code,
                "poe_key": key,
                "source": source_map.get(key, ""),
                "curve_start": curve.index.min().date().isoformat(),
                "curve_end": curve.index.max().date().isoformat(),
                "rows": int(len(curve)),
                "column_used": col_used,
                "active_days_aligned": int(active[code].sum()),
                "signal_shift_days": int(signal_shift_days),
            }
        )
    return active, pd.DataFrame(audit_rows), source_map


def run_v78_suba_new_tv10_gated(v78, close_df: pd.DataFrame, equity_codes: list[str], gates: pd.DataFrame) -> pd.DataFrame:
    codes = [c for c in equity_codes + [v78.CN_BOND_CODE] if c in close_df.columns]
    close = close_df[codes].copy()
    score = v78._v78_suba_bias_slope_score(close, ma=40, mom=20, weight_end=3.0)
    abs_mom = close.pct_change(20)
    score = score.where(score > 10.0 / 10000.0)
    score = score.where(abs_mom > 0.02)
    for code in codes:
        if code in gates.columns:
            score.loc[~gates[code].reindex(score.index).ffill().fillna(False).astype(bool), code] = np.nan
    score_arr = score.replace([np.inf, -np.inf], np.nan).to_numpy(dtype=float)
    filled = np.where(np.isfinite(score_arr), score_arr, -np.inf)
    max_idx = np.argmax(filled, axis=1)
    max_val = filled[np.arange(len(filled)), max_idx]
    target_code = np.where(np.isfinite(max_val) & (max_val > 0), max_idx, -1).astype(int)

    raw = np.zeros(len(close), dtype=float)
    price = close.to_numpy(dtype=float)
    asset_ret = np.zeros_like(price, dtype=float)
    asset_ret[1:] = price[1:] / price[:-1] - 1.0
    holding_code = np.empty_like(target_code)
    holding_code[0] = -1
    holding_code[1:] = target_code[:-1]
    invested = holding_code >= 0
    raw[invested] = asset_ret[np.arange(len(close))[invested], holding_code[invested]]

    realized = pd.Series(raw, index=close.index).rolling(80).std() * np.sqrt(v78.CN_TRADING_DAYS)
    scale = (0.30 / realized.replace(0.0, np.nan)).clip(lower=0.0, upper=1.0)
    target_weight = scale.fillna(1.0).where(pd.Series(target_code, index=close.index) >= 0, 0.0)
    holding_weight = target_weight.shift(1).fillna(0.0)
    gross = holding_weight.to_numpy(dtype=float) * pd.Series(raw, index=close.index).to_numpy(dtype=float)
    same_asset = target_code == holding_code
    turnover = np.where(
        same_asset,
        np.abs(target_weight.to_numpy(dtype=float) - holding_weight.to_numpy(dtype=float)),
        np.abs(target_weight.to_numpy(dtype=float)) + np.abs(holding_weight.to_numpy(dtype=float)),
    )
    trade_cost = v78.CN_COMMISSION * turnover
    ret = (1.0 + gross) * (1.0 - trade_cost) - 1.0
    labels = np.array(codes + ["cash"], dtype=object)
    out = pd.DataFrame(
        {
            "holding": labels[np.where(holding_code >= 0, holding_code, len(codes))],
            "target": labels[np.where(target_code >= 0, target_code, len(codes))],
            "holding_fraction": holding_weight,
            "base_weight": holding_weight,
            "weight": holding_weight,
            "target_weight": target_weight,
            "scale_raw": scale,
            "realized_vol": realized,
            "return": ret,
            "trade_cost": trade_cost,
            "turnover": turnover,
            "is_signal": pd.Series(target_code, index=close.index).ne(pd.Series(target_code, index=close.index).shift(1)).fillna(False),
        },
        index=close.index,
    )
    out["nav"] = (1.0 + out["return"].fillna(0.0)).cumprod()
    return out


def apply_suba_overlays(v78, result: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
    out = result.copy()
    if v78.CN_SA_CASH_OVERLAY_ENABLED:
        out = v78.apply_suba_cash_peak_decay_overlay(
            out,
            close_df,
            decay_ratio_threshold=v78.CN_SA_CASH_OVERLAY_DECAY_RATIO,
            recovery_ratio_threshold=v78.CN_SA_CASH_OVERLAY_RECOVERY_RATIO,
            commission=v78.CN_COMMISSION,
        )
    if v78.CN_SA_SAME_SIDE_OVERHEAT_ENABLED:
        out = v78.apply_suba_same_side_overheat_overlay(
            out,
            close_df,
            enter_threshold=v78.CN_SA_SAME_SIDE_OVERHEAT_ENTER,
            exit_threshold=v78.CN_SA_SAME_SIDE_OVERHEAT_EXIT,
            derisk_scale=v78.CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE,
        )
    if v78.CN_SA_VOLUME_OVERLAY_ENABLED:
        try:
            volume_signal, volume_feature = v78._load_suba_volume_signal()
            volume_feature = v78._annotate_rule_freshness(
                volume_feature,
                expected_date=close_df.index.max(),
                rule_key="suba_volume",
            )
            out = v78._apply_suba_volume_overlay_policy(
                out,
                close_df,
                volume_signal,
                volume_feature,
                allow_unresolved_suba_volume=True,
            )
        except Exception as exc:
            out = v78._mark_suba_volume_unavailable(out, exc)
    return out


def run_suba_overlay(v78, cn_long, cn_close: pd.DataFrame, baseline: pd.DataFrame, out_dir: Path, signal_shift_days: int) -> pd.DataFrame:
    close = v78._add_cn_bond_column(cn_close, context="V7.8 Sub-A Poe overlay research")
    gates, gate_audit, source_map = suba_active_frame(cn_long, close.index, signal_shift_days=signal_shift_days)
    v77_gated = v78.run_cn_strategy(close, v78.CN_EQUITY_CODES, single_asset_signal_gate={c: gates[c] for c in gates.columns})
    v77_gated = apply_suba_overlays(v78, v77_gated, close)
    new_gated = run_v78_suba_new_tv10_gated(v78, close, v78.CN_EQUITY_CODES, gates)
    gated = v78.blend_v78_suba_results(v77_gated, new_gated)
    common = baseline.index.intersection(gated.index)
    baseline = baseline.reindex(common)
    gated = gated.reindex(common)
    baseline.to_csv(out_dir / "suba_v78_before_poe_cn_gate_daily.csv", index_label="date", encoding="utf-8-sig")
    gated.to_csv(out_dir / "suba_v78_after_poe_cn_gate_daily.csv", index_label="date", encoding="utf-8-sig")
    gates.reindex(common).to_csv(out_dir / "suba_poe_cn_active_by_code.csv", index_label="date", encoding="utf-8-sig")
    gate_audit.to_csv(out_dir / "suba_poe_cn_gate_audit.csv", index=False, encoding="utf-8-sig")
    rows = []
    for label, offset in WINDOWS.items():
        before = perf(baseline["return"], offset, v78.CN_TRADING_DAYS)
        after = perf(gated["return"], offset, v78.CN_TRADING_DAYS)
        rows.append({"strategy": "Sub-A", "variant": "before", "window": label, **before})
        rows.append({"strategy": "Sub-A", "variant": "after_poe_cn_gate", "window": label, **after})
    metrics = write_window_metrics(out_dir / "suba_window_metrics.csv", rows)
    meta = {
        "rule": "External CN four-index Poe active gates mapped Sub-A assets; unmapped Sub-A assets unchanged.",
        "mapped_assets": SUBA_GATE_MAP,
        "source_map": source_map,
        "baseline_start": str(common.min().date()),
        "baseline_end": str(common.max().date()),
        "rows": int(len(common)),
        "signal_shift_days": int(signal_shift_days),
    }
    (out_dir / "suba_summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


def subb_weight_assets(result: pd.DataFrame) -> list[str]:
    return sorted({col[2:] for col in result.columns if col.startswith("w_")})


def subb_open_row(date: pd.Timestamp, assets: list[str], us_open: dict[str, pd.Series] | None, close: pd.DataFrame) -> pd.Series:
    prices = {}
    for asset in assets:
        value = np.nan
        if us_open is not None and asset in us_open and date in us_open[asset].index:
            value = us_open[asset].loc[date]
        if pd.isna(value) and asset in close.columns:
            value = close.loc[date, asset]
        prices[asset] = value
    return pd.Series(prices)


def returns_from_weights(weights: pd.DataFrame, close: pd.DataFrame, us_open: dict[str, pd.Series] | None, commission: float) -> pd.DataFrame:
    assets = list(weights.columns)
    prev_weights = weights.shift(1).fillna(0.0)
    if not prev_weights.empty and "BIL" in prev_weights.columns:
        prev_weights.iloc[0] = 0.0
        prev_weights.iloc[0, prev_weights.columns.get_loc("BIL")] = 1.0
    rows = []
    for dt in weights.index:
        idx = close.index.get_loc(dt)
        prev_close = close.iloc[idx - 1] if idx > 0 else close.loc[dt]
        curr_open = subb_open_row(dt, assets, us_open, close)
        curr_close = close.loc[dt].reindex(assets)
        prev_w = prev_weights.loc[dt].reindex(assets).fillna(0.0)
        curr_w = weights.loc[dt].reindex(assets).fillna(0.0)
        overnight = 0.0
        intraday = 0.0
        for asset in assets:
            if asset == "CASH":
                continue
            pc = prev_close.get(asset, np.nan)
            op = curr_open.get(asset, np.nan)
            cc = curr_close.get(asset, np.nan)
            if pd.notna(pc) and pd.notna(op) and pc:
                overnight += float(prev_w.get(asset, 0.0)) * (float(op) / float(pc) - 1.0)
            if pd.notna(op) and pd.notna(cc) and op:
                intraday += float(curr_w.get(asset, 0.0)) * (float(cc) / float(op) - 1.0)
        gross = (1.0 + overnight) * (1.0 + intraday) - 1.0
        cost_assets = [asset for asset in assets if asset not in ("BIL", "CASH")]
        turnover_value = float((curr_w - prev_w).abs().reindex(cost_assets).fillna(0.0).sum())
        cost = turnover_value * commission
        rows.append(
            {
                "return_before_execution_cost": gross,
                "execution_turnover": turnover_value,
                "execution_cost": cost,
                "return": (1.0 + gross) * (1.0 - cost) - 1.0,
            }
        )
    out = pd.DataFrame(rows, index=weights.index)
    out["nav"] = (1.0 + out["return"]).cumprod()
    return out


def apply_subb_gate(result: pd.DataFrame, close: pd.DataFrame, active: pd.DataFrame, us_open: dict[str, pd.Series] | None, commission: float) -> pd.DataFrame:
    common = result.index.intersection(close.index)
    result = result.reindex(common).copy()
    close = close.reindex(common)
    assets = subb_weight_assets(result)
    if "BIL" not in assets:
        assets.append("BIL")
    original_w = pd.DataFrame(index=common)
    gated_w = pd.DataFrame(index=common)
    for asset in assets:
        original_w[asset] = pd.to_numeric(result.get(f"w_{asset}", 0.0), errors="coerce").fillna(0.0)
        gated_w[asset] = original_w[asset]
        gate_key = SUBB_GATE_MAP.get(asset)
        if gate_key and gate_key in active.columns:
            allowed = active[gate_key].reindex(common).ffill().fillna(False)
            gated_w.loc[~allowed, asset] = 0.0
    risky_cols = [a for a in assets if a not in ("BIL", "CASH")]
    gated_w["BIL"] = gated_w.get("BIL", 0.0) + (original_w[risky_cols].sum(axis=1) - gated_w[risky_cols].sum(axis=1)).clip(lower=0.0)
    calc = returns_from_weights(gated_w.fillna(0.0), close, us_open, commission)
    out = result.copy()
    for asset in gated_w.columns:
        out[f"gated_w_{asset}"] = gated_w[asset]
    out["return_original_reference"] = pd.to_numeric(result["return"], errors="coerce")
    out["return_before_gate_cost"] = calc["return_before_execution_cost"]
    out["gate_turnover"] = calc["execution_turnover"]
    out["gate_execution_cost"] = calc["execution_cost"]
    out["return"] = calc["return"]
    out["nav"] = (1.0 + out["return"]).cumprod()
    return out


def recalc_subb_same_engine(result: pd.DataFrame, close: pd.DataFrame, us_open: dict[str, pd.Series] | None, commission: float) -> pd.DataFrame:
    common = result.index.intersection(close.index)
    result = result.reindex(common).copy()
    close = close.reindex(common)
    assets = subb_weight_assets(result)
    if "BIL" not in assets:
        assets.append("BIL")
    weights = pd.DataFrame(index=common)
    for asset in assets:
        weights[asset] = pd.to_numeric(result.get(f"w_{asset}", 0.0), errors="coerce").fillna(0.0)
    calc = returns_from_weights(weights.fillna(0.0), close, us_open, commission)
    out = result.copy()
    out["same_engine_return_before_execution_cost"] = calc["return_before_execution_cost"]
    out["same_engine_execution_turnover"] = calc["execution_turnover"]
    out["same_engine_execution_cost"] = calc["execution_cost"]
    out["return"] = calc["return"]
    out["nav"] = (1.0 + out["return"]).cumprod()
    return out


def subb_active_frame(index: pd.Index) -> pd.DataFrame:
    active_path = ROOT / "outputs" / "subb_v77_us_long_poe_gate_20260612" / "poe_us_long_active_by_sleeve.csv"
    active = pd.read_csv(active_path, parse_dates=["date"]).set_index("date").sort_index()
    return _align_external_bool_gate(active, index, "Sub-B active")


def run_subb_overlay(v78, us_close: pd.DataFrame, baseline: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    active = subb_active_frame(baseline.index)
    v77 = baseline.attrs["v78_subb_v77"]
    bias = baseline.attrs["v78_subb_bias"]
    logvol = baseline.attrs["v78_subb_logvol"]
    v77_g = apply_subb_gate(v77, us_close, active, getattr(v78.CombinedStrategyV78(), "_us_open", None), v78.US_ROT_COMMISSION)
    # The real open lookup is attached to the bot instance, so recompute the three components below with that lookup in main.
    raise RuntimeError("run_subb_overlay requires bot._us_open; call run_subb_overlay_with_open")


def run_subb_overlay_with_open(v78, us_close: pd.DataFrame, baseline: pd.DataFrame, us_open: dict[str, pd.Series], out_dir: Path) -> pd.DataFrame:
    active = subb_active_frame(baseline.index)
    components = {
        "v77": baseline.attrs["v78_subb_v77"],
        "bias": baseline.attrs["v78_subb_bias"],
        "logvol": baseline.attrs["v78_subb_logvol"],
    }
    same_engine_components = {
        name: recalc_subb_same_engine(df, us_close, us_open, v78.US_ROT_COMMISSION)
        for name, df in components.items()
    }
    gated_components = {
        name: apply_subb_gate(df, us_close, active, us_open, v78.US_ROT_COMMISSION)
        for name, df in components.items()
    }
    common = baseline.index
    for df in list(same_engine_components.values()) + list(gated_components.values()):
        common = common.intersection(df.index)
    same_engine = baseline.reindex(common).copy()
    same_engine["v78_subb_v77_return"] = same_engine_components["v77"].reindex(common)["return"]
    same_engine["v78_subb_bias_return"] = same_engine_components["bias"].reindex(common)["return"]
    same_engine["v78_subb_logvol_return"] = same_engine_components["logvol"].reindex(common)["return"]
    same_engine["return"] = (
        v78.V78_SUBB_V77_WEIGHT * same_engine["v78_subb_v77_return"]
        + v78.V78_SUBB_NEW_BIAS_WEIGHT * same_engine["v78_subb_bias_return"]
        + v78.V78_SUBB_NEW_LOGVOL_WEIGHT * same_engine["v78_subb_logvol_return"]
    )
    same_engine["nav"] = (1.0 + same_engine["return"].fillna(0.0)).cumprod()
    gated = baseline.reindex(common).copy()
    gated["v78_subb_v77_return"] = gated_components["v77"].reindex(common)["return"]
    gated["v78_subb_bias_return"] = gated_components["bias"].reindex(common)["return"]
    gated["v78_subb_logvol_return"] = gated_components["logvol"].reindex(common)["return"]
    gated["return"] = (
        v78.V78_SUBB_V77_WEIGHT * gated["v78_subb_v77_return"]
        + v78.V78_SUBB_NEW_BIAS_WEIGHT * gated["v78_subb_bias_return"]
        + v78.V78_SUBB_NEW_LOGVOL_WEIGHT * gated["v78_subb_logvol_return"]
    )
    gated["nav"] = (1.0 + gated["return"].fillna(0.0)).cumprod()
    baseline = baseline.reindex(common)
    baseline.to_csv(out_dir / "subb_v78_before_us_long_gate_daily.csv", index_label="date", encoding="utf-8-sig")
    same_engine.to_csv(out_dir / "subb_v78_before_same_engine_daily.csv", index_label="date", encoding="utf-8-sig")
    gated.to_csv(out_dir / "subb_v78_after_us_long_gate_daily.csv", index_label="date", encoding="utf-8-sig")
    active.reindex(common).to_csv(out_dir / "subb_poe_us_long_active_by_sleeve.csv", index_label="date", encoding="utf-8-sig")
    for name, df in same_engine_components.items():
        df.reindex(common).to_csv(out_dir / f"subb_v78_component_{name}_same_engine_daily.csv", index_label="date", encoding="utf-8-sig")
    for name, df in gated_components.items():
        df.reindex(common).to_csv(out_dir / f"subb_v78_component_{name}_after_gate_daily.csv", index_label="date", encoding="utf-8-sig")
    rows = []
    for label, offset in WINDOWS.items():
        official = perf(baseline["return"], offset, v78.US_TRADING_DAYS)
        before = perf(same_engine["return"], offset, v78.US_TRADING_DAYS)
        after = perf(gated["return"], offset, v78.US_TRADING_DAYS)
        rows.append({"strategy": "Sub-B", "variant": "before_official", "window": label, **official})
        rows.append({"strategy": "Sub-B", "variant": "before_same_engine", "window": label, **before})
        rows.append({"strategy": "Sub-B", "variant": "after_us_long_gate", "window": label, **after})
    metrics = write_window_metrics(out_dir / "subb_window_metrics.csv", rows)
    return metrics


def adk_direction_leg(row: pd.Series) -> str | None:
    pair = str(row.get("top_pair", "none"))
    direction = int(row.get("direction", 0) or 0)
    if pair == "none" or direction == 0 or "/" not in pair:
        return None
    a, b = pair.split("/")
    return f"{a}/{b}" if direction > 0 else f"{b}/{a}"


def recompute_adk_allowed(v78, before: pd.DataFrame, allowed: pd.DataFrame, mode: str) -> pd.DataFrame:
    out = before.copy()
    new_weight = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0).copy()
    covered = []
    is_allowed = []
    blocked = []
    legs_col = []
    for dt, row in out.iterrows():
        leg = adk_direction_leg(row)
        legs_col.append(leg or "")
        is_covered = isinstance(leg, str) and leg in allowed.columns
        allow = bool(allowed.at[dt, leg]) if is_covered and dt in allowed.index else True
        block = bool(is_covered and not allow and float(new_weight.loc[dt]) > 1e-12)
        if block:
            new_weight.loc[dt] = 0.0
        covered.append(is_covered)
        is_allowed.append(allow)
        blocked.append(block)
    out["direction_leg"] = pd.Series(legs_col, index=out.index)
    out["overlay_mode"] = mode
    out["covered_by_substrategy"] = pd.Series(covered, index=out.index, dtype=bool)
    out["substrategy_active"] = pd.Series(is_allowed, index=out.index, dtype=bool)
    out["blocked_by_substrategy"] = pd.Series(blocked, index=out.index, dtype=bool)
    out["weight"] = new_weight

    returns, gross_returns, costs, turnovers, actual_positions, actual_directions = [], [], [], [], [], []
    prev_legs: dict[str, float] = {}
    for dt, row in out.iterrows():
        pair = str(row.get("top_pair", "none"))
        direction = int(row.get("direction", 0) or 0)
        scale = float(row.get("weight", 0.0) or 0.0)
        old_weight = float(before.at[dt, "weight"] or 0.0)
        old_gross = float(before.at[dt, "return_before_dk_execution_cost"] or 0.0)
        raw_pair_ret = old_gross / old_weight if abs(old_weight) > 1e-12 else 0.0
        gross = raw_pair_ret * scale if scale > 1e-12 else 0.0
        legs = v78._dk_position_legs(pair, direction, scale) if pair != "none" and direction != 0 and scale > 1e-12 else {}
        turnover = v78._dict_weight_turnover(prev_legs, legs)
        cost = turnover * v78.CN_DK_COMMISSION
        returns.append((1.0 + gross) * (1.0 - cost) - 1.0)
        gross_returns.append(gross)
        turnovers.append(turnover)
        costs.append(cost)
        actual_positions.append(f"{pair}_{direction}" if legs else "none")
        actual_directions.append(direction if legs else 0)
        prev_legs = legs
    out["return_before_dk_execution_cost"] = pd.Series(gross_returns, index=out.index)
    out["dk_execution_turnover"] = pd.Series(turnovers, index=out.index)
    out["dk_execution_cost"] = pd.Series(costs, index=out.index)
    out["actual_position"] = pd.Series(actual_positions, index=out.index)
    out["actual_direction"] = pd.Series(actual_directions, index=out.index)
    out["return"] = pd.Series(returns, index=out.index)
    out["nav"] = (1.0 + out["return"]).cumprod()
    return out


def run_adk_overlay(v78, baseline: pd.DataFrame, out_dir: Path, signal_shift_days: int) -> pd.DataFrame:
    allowed_files = {
        "direct16": "direct16_allowed_daily.csv",
        "transitive16": "transitive16_allowed_daily.csv",
        "consensus16": "consensus16_allowed_daily.csv",
        "tc_direct_veto": "transitive_consensus_direct_veto_allowed_daily.csv",
    }
    components = {
        "v77": baseline.attrs["v78_adk_v77"],
        "new": baseline.attrs["v78_adk_new"],
    }
    common = baseline.index
    outputs = {}
    for mode, filename in allowed_files.items():
        allowed = pd.read_csv(ADK_ALLOWED_DIR / filename, parse_dates=["date"]).set_index("date").sort_index()
        allowed = _align_external_bool_gate(allowed, common, f"ADK {mode} allowed")
        allowed = shift_bool_frame(allowed, signal_shift_days)
        comp_after = {name: recompute_adk_allowed(v78, df.reindex(common), allowed, mode) for name, df in components.items()}
        after = baseline.reindex(common).copy()
        after["v78_adk_v77_return"] = comp_after["v77"]["return"]
        after["v78_adk_new_return"] = comp_after["new"]["return"]
        after["return"] = v78.V78_ADK_V77_WEIGHT * after["v78_adk_v77_return"] + v78.V78_ADK_NEW_PRIMARY_WEIGHT * after["v78_adk_new_return"]
        after["nav"] = (1.0 + after["return"].fillna(0.0)).cumprod()
        outputs[mode] = after
        after.to_csv(out_dir / f"adk_v78_after_{mode}_daily.csv", index_label="date", encoding="utf-8-sig")
        for name, df in comp_after.items():
            df.to_csv(out_dir / f"adk_v78_component_{name}_after_{mode}_daily.csv", index_label="date", encoding="utf-8-sig")
    baseline.reindex(common).to_csv(out_dir / "adk_v78_before_daily.csv", index_label="date", encoding="utf-8-sig")
    rows = []
    for label, offset in WINDOWS.items():
        before = perf(baseline.reindex(common)["return"], offset, v78.CN_TRADING_DAYS)
        rows.append({"strategy": "Sub-A-DK", "variant": "before", "window": label, **before})
        for mode, after in outputs.items():
            p = perf(after["return"], offset, v78.CN_TRADING_DAYS)
            rows.append({"strategy": "Sub-A-DK", "variant": mode, "window": label, **p})
    metrics = write_window_metrics(out_dir / "adk_window_metrics.csv", rows)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Run V7.8 Sub-A/ADK/Sub-B external Poe overlay tests.")
    parser.add_argument("--signal-shift-days", type=int, default=0, help="Shift external A/ADK daily signals by N rows before applying.")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    suffix = f"_shift{args.signal_shift_days}" if args.signal_shift_days else ""
    out_dir = args.output_dir or ROOT / "outputs" / f"{DEFAULT_OUT_PREFIX}{suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    v78 = load_module(V78_PATH, "mnt_bot_v78_overlay")
    cn_long = load_module(CN_LONG_PATH, "cn_long_poe_v12")

    bot = v78.CombinedStrategyV78()
    cn_close, cn_dk_close, us_rot_close, us_prod_daily = bot._cached_fetch_data(
        QuietMsg(),
        include_cn_live_snapshot=True,
        include_us_live_snapshot=False,
    )
    cn_result, adk_result, subb_result, *_ = bot._cached_run_strategies(
        cn_close,
        cn_dk_close,
        us_rot_close,
        us_prod_daily,
        allow_unresolved_suba_volume=True,
    )

    suba_metrics = run_suba_overlay(v78, cn_long, cn_close, cn_result, out_dir, signal_shift_days=args.signal_shift_days)
    adk_metrics = run_adk_overlay(v78, adk_result, out_dir, signal_shift_days=args.signal_shift_days)
    subb_metrics = run_subb_overlay_with_open(v78, us_rot_close, subb_result, getattr(bot, "_us_open", {}), out_dir)
    all_metrics = pd.concat([suba_metrics, adk_metrics, subb_metrics], ignore_index=True)
    all_metrics.to_csv(out_dir / "window_metrics_all.csv", index=False, encoding="utf-8-sig")

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "script": str(Path(__file__).resolve()),
        "v78_script": str(V78_PATH),
        "output_dir": str(out_dir),
        "signal_shift_days": int(args.signal_shift_days),
        "data_ranges": {
            "cn_close": [str(cn_close.index.min().date()), str(cn_close.index.max().date()), int(len(cn_close))],
            "cn_dk_close": [str(cn_dk_close.index.min().date()), str(cn_dk_close.index.max().date()), int(len(cn_dk_close))],
            "us_rot_close": [str(us_rot_close.index.min().date()), str(us_rot_close.index.max().date()), int(len(us_rot_close))],
        },
        "assumptions": {
            "Sub-A": "External CN long Poe active gates mapped assets zz1000/zz500/cyb; unmapped REDLOW100/SZ50/bond unchanged; V7.8 components gated then blended 50/50.",
            "Sub-A-DK": "Reuse saved Poe ADK16 allowed tables from online5000 run; gross return zeroed when held directed leg is blocked, execution cost recomputed, V7.8 components gated then blended 50/50.",
            "Sub-B": "Reuse saved US long active-by-sleeve table; component weights filtered by active sleeve, blocked risky weight goes to BIL; T close to T+1 adjusted open path recomputed, then V7.8 50/25/25 blend.",
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("OUTPUT", out_dir)
    print(all_metrics.to_string(index=False, formatters={"ann": "{:.2%}".format, "max_dd": "{:.2%}".format, "final_nav": "{:.4f}".format}))


if __name__ == "__main__":
    main()

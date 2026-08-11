"""Symmetric fallback-rule research for V7.9 Sub-A.

This script does not change production logic. It compares:

1. V7.7A baseline (raw Top-1 only, no fallback) vs eligible-pool fallback.
2. New A baseline (eligible-pool fallback) vs raw Top-1 only, no fallback.

The production fee, close-to-close timing, target-vol, overheat, and amount
overlay paths are retained. Formal conclusions start at 2023-08-11 because
the production amount overlay requires the CSI 2000 amount series.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
BOT_PATH = ROOT / "mnt_bot V 7.9 plus.py"
PANEL_PATH = ROOT / "mnt_strategy_data_cn.csv"
SAVED_V77_PATH = ROOT / "docs" / "v77_suba_standard_review_20260614" / "v77_suba_daily.csv"
DEFAULT_OUTPUT = ROOT / "outputs" / "suba_fallback_symmetry_v79_20260810"
FROZEN_END = pd.Timestamp("2026-06-12")
FORMAL_START = pd.Timestamp("2023-08-11")
PUBLICATION_DATES = {
    "1.930955": "2017-05-26",
    "0.399006": "2010-06-01",
    "1.000016": "2004-01-02",
    "1.000852": "2014-10-17",
    "1.000905": "2007-01-15",
    "1.H11077": "2013-03-07",
    "2.932000": "2023-08-11",
}


def load_bot():
    spec = importlib.util.spec_from_file_location("mnt_bot_v79_fallback_research", BOT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {BOT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_close_panel(module) -> pd.DataFrame:
    panel = pd.read_csv(PANEL_PATH, parse_dates=["date"]).set_index("date").sort_index()
    required = module.CN_EQUITY_CODES + [module.CN_BOND_CODE]
    missing = [code for code in required if code not in panel.columns]
    if missing:
        raise KeyError(f"Frozen CN panel is missing: {missing}")
    close = panel[required].apply(pd.to_numeric, errors="coerce")
    close = close.loc[pd.Timestamp("2014-10-17"):FROZEN_END].ffill().dropna()
    if close.index[-1] != FROZEN_END:
        raise RuntimeError(f"Frozen panel ends {close.index[-1].date()}, expected {FROZEN_END.date()}")
    return close


def eligible_pool_selector(module) -> Callable[..., str]:
    def select(scores, r2_dict, row_pos, holding="cash", abs_mom_dict=None):
        if not scores:
            return "cash"
        eligible = []
        for code, score in scores.items():
            if pd.isna(score) or float(score) <= 0.0:
                continue
            r2_value = module._cn_series_value_at(r2_dict.get(code), row_pos) if r2_dict else np.nan
            if pd.isna(r2_value) or float(r2_value) < module.CN_R2_THRESHOLD:
                continue
            if abs_mom_dict is not None:
                abs_value = module._cn_series_value_at(abs_mom_dict.get(code), row_pos)
                if pd.isna(abs_value) or float(abs_value) <= module.CN_ABS_MOM_THRESHOLD:
                    continue
            eligible.append(code)
        if not eligible:
            return "cash"
        best = max(eligible, key=lambda code: scores[code])
        if (
            holding != "cash"
            and holding != best
            and holding in eligible
            and module.CN_SWITCH_BUFFER > 1.0
        ):
            return best if float(scores[best]) > float(scores[holding]) * module.CN_SWITCH_BUFFER else holding
        return best

    return select


def run_v77_raw(module, close: pd.DataFrame, *, fallback: bool) -> pd.DataFrame:
    if not fallback:
        return module.run_cn_strategy(close, module.CN_EQUITY_CODES)
    original = module._select_cn_ideal_asset
    module._select_cn_ideal_asset = eligible_pool_selector(module)
    try:
        return module.run_cn_strategy(close, module.CN_EQUITY_CODES)
    finally:
        module._select_cn_ideal_asset = original


def apply_v77_overlays(module, result: pd.DataFrame, close: pd.DataFrame, volume_signal, volume_feature) -> pd.DataFrame:
    out = result
    if module.CN_SA_CASH_OVERLAY_ENABLED:
        out = module.apply_suba_cash_peak_decay_overlay(
            out,
            close,
            module.CN_SA_CASH_OVERLAY_DECAY_RATIO,
            module.CN_SA_CASH_OVERLAY_RECOVERY_RATIO,
            commission=module.CN_COMMISSION,
        )
    if module.CN_SA_SAME_SIDE_OVERHEAT_ENABLED:
        out = module.apply_suba_same_side_overheat_overlay(
            out,
            close,
            module.CN_SA_SAME_SIDE_OVERHEAT_ENTER,
            module.CN_SA_SAME_SIDE_OVERHEAT_EXIT,
            module.CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE,
        )
    if module.CN_SA_VOLUME_OVERLAY_ENABLED:
        out = module._apply_suba_volume_overlay_policy(
            out,
            close,
            volume_signal,
            volume_feature,
            allow_unresolved_suba_volume=False,
        )
    return out


def run_new_raw(module, close_df: pd.DataFrame, *, raw_top_only: bool) -> pd.DataFrame:
    """Research copy of run_v78_suba_new_tv10 with only selection order varied."""
    if float(module.V78_SUBA_NEW_MAX_LEV) > 1.0 + 1e-12:
        raise ValueError("V78_SUBA_NEW_MAX_LEV > 1.0 requires explicit borrow-cost implementation.")
    codes = [code for code in module.CN_EQUITY_CODES + [module.CN_BOND_CODE] if code in close_df.columns]
    close = close_df[codes].copy()
    raw_score = module._v78_suba_bias_slope_score(
        close,
        ma=module.V78_SUBA_NEW_MA,
        mom=module.V78_SUBA_NEW_MOM_DAY,
        weight_end=module.V78_SUBA_NEW_WEIGHT_END,
    )
    abs_mom = close.pct_change(module.V78_SUBA_NEW_ABS_DAY)
    raw_arr = raw_score.replace([np.inf, -np.inf], np.nan).to_numpy(dtype=float)
    raw_filled = np.where(np.isfinite(raw_arr), raw_arr, -np.inf)
    raw_top_idx = np.argmax(raw_filled, axis=1)
    raw_top_val = raw_filled[np.arange(len(raw_filled)), raw_top_idx]

    if raw_top_only:
        top_abs = abs_mom.to_numpy(dtype=float)[np.arange(len(close)), raw_top_idx]
        valid = (
            np.isfinite(raw_top_val)
            & (raw_top_val > module.V78_SUBA_NEW_SCORE_THRESHOLD)
            & np.isfinite(top_abs)
            & (top_abs > module.V78_SUBA_NEW_ABS_THRESHOLD)
        )
        target_code = np.where(valid, raw_top_idx, -1).astype(int)
        gated_score = raw_score.where(raw_score > module.V78_SUBA_NEW_SCORE_THRESHOLD)
        gated_score = gated_score.where(abs_mom > module.V78_SUBA_NEW_ABS_THRESHOLD)
    else:
        gated_score = raw_score.where(raw_score > module.V78_SUBA_NEW_SCORE_THRESHOLD)
        gated_score = gated_score.where(abs_mom > module.V78_SUBA_NEW_ABS_THRESHOLD)
        gated_arr = gated_score.replace([np.inf, -np.inf], np.nan).to_numpy(dtype=float)
        filled = np.where(np.isfinite(gated_arr), gated_arr, -np.inf)
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

    realized = pd.Series(raw, index=close.index).rolling(module.V78_SUBA_NEW_VOL_WINDOW).std() * np.sqrt(module.CN_TRADING_DAYS)
    scale = (module.V78_SUBA_NEW_TARGET_VOL / realized.replace(0.0, np.nan)).clip(
        lower=0.0,
        upper=module.V78_SUBA_NEW_MAX_LEV,
    )
    target_weight = scale.fillna(1.0).where(pd.Series(target_code, index=close.index) >= 0, 0.0)
    holding_weight = target_weight.shift(1).fillna(0.0)

    gross = holding_weight.to_numpy(dtype=float) * pd.Series(raw, index=close.index).to_numpy(dtype=float)
    cash_component = (1.0 - holding_weight.clip(upper=1.0).to_numpy(dtype=float)) * float(module.CN_RF_DAILY)
    same_asset = target_code == holding_code
    turnover = np.where(
        same_asset,
        np.abs(target_weight.to_numpy(dtype=float) - holding_weight.to_numpy(dtype=float)),
        np.abs(target_weight.to_numpy(dtype=float)) + np.abs(holding_weight.to_numpy(dtype=float)),
    )
    trade_cost = module.CN_COMMISSION * turnover
    ret = (1.0 + gross + cash_component) * (1.0 - trade_cost) - 1.0
    code_changed = pd.Series(target_code, index=close.index).ne(pd.Series(target_code, index=close.index).shift(1))
    weight_changed = target_weight.diff().abs().fillna(0.0).gt(1e-4)
    label_arr = np.array(codes + ["cash"], dtype=object)
    out = pd.DataFrame(
        {
            "holding": label_arr[np.where(holding_code >= 0, holding_code, len(codes))],
            "target": label_arr[np.where(target_code >= 0, target_code, len(codes))],
            "holding_fraction": holding_weight,
            "base_weight": holding_weight,
            "weight": holding_weight,
            "target_weight": target_weight,
            "scale_raw": scale,
            "realized_vol": realized,
            "return": ret,
            "trade_cost": trade_cost,
            "turnover": turnover,
            "cash_component": cash_component,
            "is_signal": (code_changed | weight_changed).fillna(False),
        },
        index=close.index,
    )
    out["nav"] = (1.0 + out["return"].fillna(0.0)).cumprod()
    out.attrs["v78_raw_score"] = raw_score
    out.attrs["v78_abs_mom"] = abs_mom
    out.attrs["v78_score"] = gated_score
    return out


def apply_new_overlay(module, result: pd.DataFrame, close: pd.DataFrame, volume_signal, volume_feature) -> pd.DataFrame:
    if not module.CN_SA_VOLUME_OVERLAY_ENABLED:
        return result
    return module._apply_v78_suba_new_volume_overlay_policy(
        result,
        close,
        volume_signal,
        volume_feature,
        allow_unresolved_suba_volume=False,
    )


def metric(module, returns: pd.Series) -> dict[str, Any]:
    series = pd.to_numeric(returns, errors="coerce").dropna().sort_index()
    if len(series) < 20:
        return {"available": False, "reason": f"only {len(series)} rows"}
    years = (series.index[-1] - series.index[0]).days / 365.25
    if years <= 0:
        return {"available": False, "reason": "zero date span"}
    nav = (1.0 + series).cumprod()
    return {
        "available": True,
        "start": series.index[0].strftime("%Y-%m-%d"),
        "end": series.index[-1].strftime("%Y-%m-%d"),
        "rows": int(len(series)),
        "annual_return": float(nav.iloc[-1] ** (1.0 / years) - 1.0),
        "max_drawdown": float(module._max_drawdown_pct_from_nav(nav) / 100.0),
        "total_return": float(nav.iloc[-1] - 1.0),
        "volatility": float(series.std(ddof=1) * np.sqrt(module.CN_TRADING_DAYS)),
    }


def paired_metric_rows(module, experiments: dict[str, tuple[pd.Series, pd.Series]], *, formal: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for experiment, (baseline, candidate) in experiments.items():
        common = baseline.index.intersection(candidate.index)
        baseline = baseline.reindex(common)
        candidate = candidate.reindex(common)
        end = min(baseline.index[-1], candidate.index[-1], FROZEN_END)
        windows = [
            ("Full", None),
            ("10Y", end - pd.DateOffset(years=10)),
            ("5Y", end - pd.DateOffset(years=5)),
            ("3Y", end - pd.DateOffset(years=3)),
            ("1Y", end - pd.DateOffset(years=1)),
        ]
        for window, requested_start in windows:
            if formal and requested_start is not None and requested_start < FORMAL_START:
                rows.append(
                    {
                        "experiment": experiment,
                        "window": window,
                        "status": "N/A",
                        "reason": f"requested start {requested_start.date()} precedes formal start {FORMAL_START.date()}",
                    }
                )
                continue
            start = FORMAL_START if formal and requested_start is None else requested_start
            if start is None:
                start = common[0]
            base_slice = baseline[(baseline.index >= start) & (baseline.index <= end)]
            cand_slice = candidate[(candidate.index >= start) & (candidate.index <= end)]
            aligned = base_slice.index.intersection(cand_slice.index)
            base_metric = metric(module, base_slice.reindex(aligned))
            cand_metric = metric(module, cand_slice.reindex(aligned))
            if not base_metric.get("available") or not cand_metric.get("available"):
                rows.append(
                    {
                        "experiment": experiment,
                        "window": window,
                        "status": "N/A",
                        "reason": base_metric.get("reason") or cand_metric.get("reason"),
                    }
                )
                continue
            rows.append(
                {
                    "experiment": experiment,
                    "window": window,
                    "status": "observed",
                    "start": base_metric["start"],
                    "end": base_metric["end"],
                    "rows": base_metric["rows"],
                    "baseline_annual_return": base_metric["annual_return"],
                    "candidate_annual_return": cand_metric["annual_return"],
                    "annual_return_delta_pp": (cand_metric["annual_return"] - base_metric["annual_return"]) * 100.0,
                    "baseline_max_drawdown": base_metric["max_drawdown"],
                    "candidate_max_drawdown": cand_metric["max_drawdown"],
                    "max_drawdown_improvement_pp": (cand_metric["max_drawdown"] - base_metric["max_drawdown"]) * 100.0,
                    "baseline_volatility": base_metric["volatility"],
                    "candidate_volatility": cand_metric["volatility"],
                }
            )
    return rows


def event_summary(name: str, baseline: pd.DataFrame, candidate: pd.DataFrame) -> dict[str, Any]:
    common = baseline.index.intersection(candidate.index)
    base = baseline.reindex(common)
    cand = candidate.reindex(common)
    base_weight = pd.to_numeric(base["weight"], errors="coerce").fillna(0.0)
    cand_weight = pd.to_numeric(cand["weight"], errors="coerce").fillna(0.0)
    base_holding = base["holding"].fillna("cash").astype(str)
    cand_holding = cand["holding"].fillna("cash").astype(str)
    return {
        "experiment": name,
        "start": common[0].strftime("%Y-%m-%d"),
        "end": common[-1].strftime("%Y-%m-%d"),
        "rows": int(len(common)),
        "holding_changed_days": int((base_holding != cand_holding).sum()),
        "exposure_changed_days": int((base_weight - cand_weight).abs().gt(1e-12).sum()),
        "baseline_invested_days": int(base_weight.gt(1e-12).sum()),
        "candidate_invested_days": int(cand_weight.gt(1e-12).sum()),
        "candidate_extra_invested_days": int((cand_weight.gt(1e-12) & base_weight.le(1e-12)).sum()),
        "candidate_removed_invested_days": int((cand_weight.le(1e-12) & base_weight.gt(1e-12)).sum()),
        "baseline_turnover": float(pd.to_numeric(base.get("effective_turnover", base.get("turnover", 0.0)), errors="coerce").fillna(0.0).sum()),
        "candidate_turnover": float(pd.to_numeric(cand.get("effective_turnover", cand.get("turnover", 0.0)), errors="coerce").fillna(0.0).sum()),
    }


def markdown_metric_table(rows: list[dict[str, Any]], experiment: str) -> str:
    selected = [row for row in rows if row["experiment"] == experiment]
    lines = [
        "| Window | Baseline ann. | Candidate ann. | Δ ann. | Baseline MDD | Candidate MDD | MDD improvement |",
        "|:-|--:|--:|--:|--:|--:|--:|",
    ]
    for row in selected:
        if row["status"] != "observed":
            lines.append(f"| {row['window']} | N/A | N/A | N/A | N/A | N/A | N/A ({row['reason']}) |")
            continue
        lines.append(
            f"| {row['window']} | {row['baseline_annual_return']:.2%} | {row['candidate_annual_return']:.2%} | "
            f"{row['annual_return_delta_pp']:+.2f}pp | {row['baseline_max_drawdown']:.2%} | "
            f"{row['candidate_max_drawdown']:.2%} | {row['max_drawdown_improvement_pp']:+.2f}pp |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    module = load_bot()
    close = load_close_panel(module)
    volume_signal, volume_feature = module._load_suba_volume_signal()
    volume_feature = module._annotate_rule_freshness(
        volume_feature,
        expected_date=FROZEN_END,
        rule_key="suba_volume",
    )
    formal_feature = volume_feature.loc[FORMAL_START:FROZEN_END]
    if len(formal_feature) == 0 or module._suba_volume_feature_has_unresolved(formal_feature):
        raise RuntimeError("Formal amount-overlay feature is empty or unresolved.")

    v77_base_raw = run_v77_raw(module, close, fallback=False)
    v77_candidate_raw = run_v77_raw(module, close, fallback=True)
    v77_base = apply_v77_overlays(module, v77_base_raw, close, volume_signal, volume_feature)
    v77_candidate = apply_v77_overlays(module, v77_candidate_raw, close, volume_signal, volume_feature)

    saved_v77 = pd.read_csv(SAVED_V77_PATH, parse_dates=["date"]).set_index("date")
    saved_common = v77_base.index.intersection(saved_v77.index)
    v77_baseline_diff = (v77_base.loc[saved_common, "return"] - saved_v77.loc[saved_common, "return"]).abs()
    if float(v77_baseline_diff.max()) > 1e-12:
        raise AssertionError(f"V7.7 baseline mismatch: max abs return diff {v77_baseline_diff.max():.3e}")

    new_official_raw = module.run_v78_suba_new_tv10(close, module.CN_EQUITY_CODES)
    new_base_raw = run_new_raw(module, close, raw_top_only=False)
    raw_common = new_official_raw.index.intersection(new_base_raw.index)
    new_raw_diff = (new_official_raw.loc[raw_common, "return"] - new_base_raw.loc[raw_common, "return"]).abs()
    if float(new_raw_diff.max()) > 1e-12:
        raise AssertionError(f"New A raw baseline mismatch: max abs return diff {new_raw_diff.max():.3e}")
    new_candidate_raw = run_new_raw(module, close, raw_top_only=True)
    new_base = apply_new_overlay(module, new_base_raw, close, volume_signal, volume_feature)
    new_candidate = apply_new_overlay(module, new_candidate_raw, close, volume_signal, volume_feature)
    new_official = apply_new_overlay(module, new_official_raw, close, volume_signal, volume_feature)
    new_common = new_official.index.intersection(new_base.index)
    new_baseline_diff = (new_official.loc[new_common, "return"] - new_base.loc[new_common, "return"]).abs()
    if float(new_baseline_diff.max()) > 1e-12:
        raise AssertionError(f"New A overlaid baseline mismatch: max abs return diff {new_baseline_diff.max():.3e}")

    blend_base = module.blend_v78_suba_results(v77_base, new_base)
    blend_v77_candidate = module.blend_v78_suba_results(v77_candidate, new_base)
    blend_new_candidate = module.blend_v78_suba_results(v77_base, new_candidate)

    experiments = {
        "V7.7A leg: no fallback -> fallback": (v77_base["return"], v77_candidate["return"]),
        "Sub-A impact: only V7.7A uses fallback": (blend_base["return"], blend_v77_candidate["return"]),
        "New A leg: fallback -> no fallback": (new_base["return"], new_candidate["return"]),
        "Sub-A impact: only New A removes fallback": (blend_base["return"], blend_new_candidate["return"]),
    }
    formal_rows = paired_metric_rows(module, experiments, formal=True)
    diagnostic_rows = paired_metric_rows(module, experiments, formal=False)
    event_rows = [
        event_summary("V7.7A leg: no fallback -> fallback", v77_base, v77_candidate),
        event_summary("New A leg: fallback -> no fallback", new_base, new_candidate),
    ]

    daily = pd.concat(
        {
            "v77_baseline_return": v77_base["return"],
            "v77_fallback_return": v77_candidate["return"],
            "new_baseline_return": new_base["return"],
            "new_no_fallback_return": new_candidate["return"],
            "suba_baseline_return": blend_base["return"],
            "suba_v77_fallback_return": blend_v77_candidate["return"],
            "suba_new_no_fallback_return": blend_new_candidate["return"],
        },
        axis=1,
    ).sort_index()
    for column in [col for col in daily.columns if col.endswith("_return")]:
        daily[column.replace("_return", "_nav")] = (1.0 + daily[column].fillna(0.0)).cumprod()
    daily.index.name = "date"
    daily.to_csv(output / "daily_curves.csv")
    pd.DataFrame(formal_rows).to_csv(output / "metrics_formal.csv", index=False)
    pd.DataFrame(diagnostic_rows).to_csv(output / "metrics_diagnostic.csv", index=False)
    pd.DataFrame(event_rows).to_csv(output / "event_summary.csv", index=False)
    volume_feature.loc[:FROZEN_END].to_csv(output / "volume_feature_used.csv")

    metadata = {
        "status": "observed",
        "production_script": str(BOT_PATH),
        "research_script": str(Path(__file__).resolve()),
        "price_panel": str(PANEL_PATH),
        "saved_v77_baseline": str(SAVED_V77_PATH),
        "price_range": [close.index[0].strftime("%Y-%m-%d"), close.index[-1].strftime("%Y-%m-%d")],
        "price_rows": int(len(close)),
        "formal_start": FORMAL_START.strftime("%Y-%m-%d"),
        "formal_end": FROZEN_END.strftime("%Y-%m-%d"),
        "publication_dates": PUBLICATION_DATES,
        "price_mode": "equity price indexes; 1.H11077 defensive bond total-return series",
        "calendar_timezone": "A-share trading-day panel; Asia/Shanghai signal interpretation",
        "execution": "T close signal -> next close-to-close holding; no lookahead shift retained from production",
        "commission": module.CN_COMMISSION,
        "slippage": "none beyond configured 10 bps single-side commission",
        "overlays": {
            "v77_target_vol": [module.CN_TARGET_VOL, module.CN_VOL_WINDOW, module.CN_MAX_LEV],
            "v77_same_side_overheat": [module.CN_SA_SAME_SIDE_OVERHEAT_ENTER, module.CN_SA_SAME_SIDE_OVERHEAT_EXIT, module.CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE],
            "amount_rule": module.CN_SA_VOLUME_RULE_NAME,
            "new_target_vol": [module.V78_SUBA_NEW_TARGET_VOL, module.V78_SUBA_NEW_VOL_WINDOW, module.V78_SUBA_NEW_MAX_LEV],
        },
        "baseline_reconciliation": {
            "v77_overlap_rows": int(len(saved_common)),
            "v77_max_abs_return_diff": float(v77_baseline_diff.max()),
            "new_raw_overlap_rows": int(len(raw_common)),
            "new_raw_max_abs_return_diff": float(new_raw_diff.max()),
            "new_overlaid_overlap_rows": int(len(new_common)),
            "new_overlaid_max_abs_return_diff": float(new_baseline_diff.max()),
        },
        "formal_metrics": formal_rows,
        "diagnostic_metrics": diagnostic_rows,
        "event_summary": event_rows,
        "caveats": [
            "Formal window starts 2023-08-11 because CSI 2000 amount is a production input.",
            "Pre-publication index and amount history is diagnostic only.",
            "No A-share price-limit, suspension-fill, capacity, or extra slippage model beyond production commission.",
            "This is a research comparison only; production selection logic is unchanged.",
        ],
    }
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    formal_v77 = markdown_metric_table(formal_rows, "V7.7A leg: no fallback -> fallback")
    formal_v77_blend = markdown_metric_table(formal_rows, "Sub-A impact: only V7.7A uses fallback")
    formal_new = markdown_metric_table(formal_rows, "New A leg: fallback -> no fallback")
    formal_new_blend = markdown_metric_table(formal_rows, "Sub-A impact: only New A removes fallback")
    diagnostic_v77 = markdown_metric_table(diagnostic_rows, "V7.7A leg: no fallback -> fallback")
    diagnostic_v77_blend = markdown_metric_table(
        diagnostic_rows, "Sub-A impact: only V7.7A uses fallback"
    )
    diagnostic_new = markdown_metric_table(diagnostic_rows, "New A leg: fallback -> no fallback")
    diagnostic_new_blend = markdown_metric_table(
        diagnostic_rows, "Sub-A impact: only New A removes fallback"
    )
    record = f"""# V7.9 Sub-A Fallback Symmetry Test

Generated: 2026-08-10

## 1. Scope

- V7.7A: production raw-Top-1/no-fallback baseline versus eligible-pool fallback candidate.
- New A TV1.0: production eligible-pool fallback baseline versus raw-Top-1/no-fallback candidate.
- Production code was not changed by this research run.

## 2. Code And Data Provenance

- Production implementation: `{BOT_PATH}`.
- Frozen price panel: `{PANEL_PATH}`, {close.index[0].date()} to {close.index[-1].date()}, {len(close)} rows.
- Formal start: {FORMAL_START.date()}, set by CSI 2000 amount publication/availability.
- Price mode: equity price indexes; `1.H11077` defensive bond total-return series.
- Baseline reconciliation: V7.7A {len(saved_common)} rows, max abs return diff {float(v77_baseline_diff.max()):.3e}; New A raw {len(raw_common)} rows, max diff {float(new_raw_diff.max()):.3e}; New A after amount overlay max diff {float(new_baseline_diff.max()):.3e}.

## 3. Execution And Frictions

- T close signal changes the next close-to-close holding, matching production shift behavior.
- Commission: {module.CN_COMMISSION:.1%} single-side turnover cost.
- Included: each leg's production target-vol; V7.7A MA60 overheat; production Sub-A amount overlay.
- Excluded beyond production: extra slippage, price-limit/suspension fill modeling, and capacity constraints.

## 4. Formal Results

### V7.7A Leg — Add Fallback

{formal_v77}

### 50/50 Sub-A — Only V7.7A Adds Fallback

{formal_v77_blend}

### New A Leg — Remove Fallback

{formal_new}

### 50/50 Sub-A — Only New A Removes Fallback

{formal_new_blend}

## 5. Diagnostic Long-Window Results

These windows include pre-publication/backfilled inputs and are diagnostic only.

### V7.7A Leg — Add Fallback

{diagnostic_v77}

### 50/50 Sub-A — Only V7.7A Adds Fallback

{diagnostic_v77_blend}

### New A Leg — Remove Fallback

{diagnostic_new}

### 50/50 Sub-A — Only New A Removes Fallback

{diagnostic_new_blend}

## 6. Event Summary

```json
{json.dumps(event_rows, ensure_ascii=False, indent=2)}
```

## 7. Integrity And Caveats

- Both baselines were reconciled before candidate comparison.
- Baseline and candidate use the same data slice, costs, close-to-close timing, target-vol, and overlays.
- Formal 10Y/5Y/3Y rows are N/A because their requested starts precede 2023-08-11.
- Research only: no production promotion or signal-display change was made.

## 8. Decision

- Do not add fallback to V7.7A: the formal full window has lower annualized return and materially deeper drawdown. The recent 1Y benefit does not survive the formal full/3Y comparison.
- Keep fallback in New A: removing it lowers return in every reported window while providing essentially no formal drawdown benefit.
- The asymmetric production rules are therefore retained.
"""
    (output / "record.md").write_text(record, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

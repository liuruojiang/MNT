from __future__ import annotations

import builtins
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = Path(__file__).resolve().parent
ENTRYPOINT = ROOT / "mnt_bot V 7.7 plus.py"
CN_DATA = ROOT / "mnt_strategy_data_cn.csv"
FORMAL_START = pd.Timestamp("2014-10-17")
SCALE_WHEN_TRUE = 0.50
COST_BPS = 10.0
TRADING_DAYS = 242

MA_VALUES = list(range(10, 81))
DAYS_VALUES = list(range(2, 21))
WINDOWS = {
    "full": None,
    "last_10y": pd.DateOffset(years=10),
    "last_5y": pd.DateOffset(years=5),
    "last_3y": pd.DateOffset(years=3),
    "last_1y": pd.DateOffset(years=1),
}


class _PoeStub:
    query = None
    default_chat = []

    class BotError(Exception):
        pass

    def update_settings(self, settings):
        self.settings = settings


def load_module():
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = _PoeStub()
    spec = importlib.util.spec_from_file_location("mnt_bot_v77_multi_amount_scan", str(ENTRYPOINT))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    if had_poe:
        builtins.poe = old_poe
    else:
        delattr(builtins, "poe")
    return mod


def load_dk_close(mod) -> pd.DataFrame:
    raw = pd.read_csv(CN_DATA, parse_dates=["date"]).set_index("date").sort_index()
    mapping = {
        mod.CN_DK_ZZ1000_SECID: mod.CN_DK_COLS[0],
        mod.CN_DK_SZ50_SECID: mod.CN_DK_COLS[1],
        mod.CN_DK_HS300_SECID: mod.CN_DK_COLS[2],
        mod.CN_DK_ZZ500_SECID: mod.CN_DK_COLS[3],
        mod.CN_DK_CYB_SECID: mod.CN_DK_COLS[4],
    }
    missing = [src for src in mapping if src not in raw.columns]
    if missing:
        raise KeyError(f"Missing DK columns in {CN_DATA}: {missing}")
    return raw[list(mapping)].rename(columns=mapping).ffill().dropna(how="any")


def run_current_v77_adk(mod, dk_close: pd.DataFrame) -> pd.DataFrame:
    result = mod.run_dk_strategy(dk_close, dk_close)
    if mod.CN_DK_PAIR_SCORE_DECAY_ENABLED:
        result = mod.apply_dk_pair_score_peak_decay_overlay(
            result,
            decay_ratio_threshold=mod.CN_DK_PAIR_SCORE_DECAY_RATIO,
            recovery_ratio_threshold=mod.CN_DK_PAIR_SCORE_RECOVERY_RATIO,
            derisk_scale=mod.CN_DK_PAIR_SCORE_DERISK_SCALE,
            commission=mod.CN_DK_COMMISSION,
        )
    if mod.CN_DK_SAME_SIDE_OVERHEAT_ENABLED:
        result = mod.apply_dk_same_side_overheat_overlay(
            result,
            enter_threshold=mod.CN_DK_SAME_SIDE_OVERHEAT_ENTER,
            exit_threshold=mod.CN_DK_SAME_SIDE_OVERHEAT_EXIT,
            derisk_scale=mod.CN_DK_SAME_SIDE_OVERHEAT_DERISK_SCALE,
            commission=mod.CN_DK_COMMISSION,
        )
    if mod.CN_DK_RISK_GATE_ENABLED:
        result = mod.apply_dk_drawdown_risk_gate(
            result,
            enter=mod.CN_DK_RISK_GATE_ENTER,
            scale_defense=mod.CN_DK_RISK_GATE_DEFENSE_SCALE,
            exit_value=mod.CN_DK_RISK_GATE_EXIT,
            cooldown_days=mod.CN_DK_RISK_GATE_COOLDOWN_DAYS,
        )
    return mod._rebuild_dk_effective_execution_costs(
        result,
        result.attrs.get("pair_data", {}),
        mod.CN_DK_COMMISSION,
    )


def consecutive_below(amount: pd.Series, ma: int, days: int) -> pd.Series:
    amount = pd.Series(amount, dtype=float).sort_index()
    ratio = amount / amount.rolling(int(ma), min_periods=int(ma)).mean()
    below = ratio < 1.0
    streak = []
    cur = 0
    for value in below.fillna(False):
        cur = cur + 1 if bool(value) else 0
        streak.append(cur)
    return pd.Series(streak, index=amount.index, dtype=int) >= int(days)


def calc_metrics(ret: pd.Series) -> dict[str, float]:
    ret = pd.Series(ret, dtype=float).dropna().sort_index()
    if ret.empty:
        return {
            "annual_pct": np.nan,
            "vol_pct": np.nan,
            "sharpe": np.nan,
            "max_dd_pct": np.nan,
            "calmar": np.nan,
            "total_return_pct": np.nan,
        }
    nav = (1.0 + ret).cumprod()
    years = len(ret) / TRADING_DAYS
    annual = nav.iloc[-1] ** (1.0 / years) - 1.0 if years > 0 else np.nan
    vol = ret.std() * np.sqrt(TRADING_DAYS)
    max_dd = (nav / nav.cummax() - 1.0).min()
    return {
        "annual_pct": float(annual * 100.0),
        "vol_pct": float(vol * 100.0),
        "sharpe": float(annual / vol) if vol and not np.isnan(vol) else np.nan,
        "max_dd_pct": float(max_dd * 100.0),
        "calmar": float(annual / abs(max_dd)) if max_dd and not np.isnan(max_dd) else np.nan,
        "total_return_pct": float((nav.iloc[-1] - 1.0) * 100.0),
    }


def window_slice(ret: pd.Series, window: str) -> pd.Series:
    ret = ret.dropna().sort_index()
    offset = WINDOWS[window]
    if offset is None or ret.empty:
        return ret
    return ret.loc[ret.index >= ret.index.max() - offset]


def max_dd_span(ret: pd.Series) -> dict[str, str | float]:
    ret = ret.dropna().sort_index()
    nav = (1.0 + ret).cumprod()
    dd = nav / nav.cummax() - 1.0
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    return {
        "max_dd_pct": float(dd.loc[trough] * 100.0),
        "peak": str(peak.date()),
        "trough": str(trough.date()),
    }


def apply_amount_filter(base_ret: pd.Series, raw_signal: pd.Series) -> tuple[pd.Series, pd.Series]:
    ret = base_ret.dropna().sort_index()
    signal = raw_signal.reindex(raw_signal.index.union(ret.index)).sort_index().ffill().reindex(ret.index)
    signal = signal.fillna(False).astype(bool)
    scale = pd.Series(np.where(signal.shift(1).fillna(False), SCALE_WHEN_TRUE, 1.0), index=ret.index)
    extra_cost = scale.diff().abs().fillna(0.0) * (COST_BPS / 10000.0)
    scenario = ret * scale - extra_cost
    return scenario, scale


def scan_one_amount_series(source_key: str, label: str, amount: pd.Series, base_ret: pd.Series) -> tuple[list[dict], list[dict]]:
    baseline = {window: calc_metrics(window_slice(base_ret, window)) for window in WINDOWS}
    summary_rows: list[dict] = []
    window_rows: list[dict] = []
    signal_cache: dict[tuple[int, int], pd.Series] = {}
    for ma in MA_VALUES:
        for days in DAYS_VALUES:
            raw_signal = signal_cache.setdefault((ma, days), consecutive_below(amount, ma, days))
            scenario_ret, scale = apply_amount_filter(base_ret, raw_signal)
            candidate = f"{source_key}_ma{ma}_d{days}_s050"
            summary = {
                "candidate": candidate,
                "source_key": source_key,
                "source_label": label,
                "ma": ma,
                "days": days,
                "scale_when_true": SCALE_WHEN_TRUE,
            }
            for window in WINDOWS:
                part = window_slice(scenario_ret, window)
                metrics = calc_metrics(part)
                base = baseline[window]
                part_scale = scale.reindex(part.index)
                signal_part = raw_signal.reindex(part.index).ffill().fillna(False).astype(bool)
                dd_span = max_dd_span(part) if len(part) else {"peak": "", "trough": ""}
                annual_delta = metrics["annual_pct"] - base["annual_pct"]
                sharpe_delta = metrics["sharpe"] - base["sharpe"]
                max_dd_delta = metrics["max_dd_pct"] - base["max_dd_pct"]
                row = {
                    "candidate": candidate,
                    "source_key": source_key,
                    "source_label": label,
                    "window": window,
                    "ma": ma,
                    "days": days,
                    "scale_when_true": SCALE_WHEN_TRUE,
                    "start": str(part.index.min().date()) if len(part) else "",
                    "end": str(part.index.max().date()) if len(part) else "",
                    "n_days": int(len(part)),
                    **metrics,
                    "baseline_annual_pct": base["annual_pct"],
                    "baseline_sharpe": base["sharpe"],
                    "baseline_max_dd_pct": base["max_dd_pct"],
                    "annual_delta_pp": annual_delta,
                    "sharpe_delta": sharpe_delta,
                    "max_dd_delta_pp": max_dd_delta,
                    "signal_days_pct": float(signal_part.mean() * 100.0) if len(part) else np.nan,
                    "defense_days_pct": float((part_scale < 0.999).mean() * 100.0) if len(part) else np.nan,
                    "switch_count": int(part_scale.diff().abs().fillna(0.0).gt(0.0).sum()) if len(part) else 0,
                    "max_dd_peak": dd_span.get("peak", ""),
                    "max_dd_trough": dd_span.get("trough", ""),
                }
                window_rows.append(row)
                for key in [
                    "annual_pct",
                    "sharpe",
                    "max_dd_pct",
                    "annual_delta_pp",
                    "sharpe_delta",
                    "max_dd_delta_pp",
                    "signal_days_pct",
                    "defense_days_pct",
                    "switch_count",
                ]:
                    summary[f"{window}_{key}"] = row[key]
            summary["robust_pass"] = bool(
                summary["last_10y_max_dd_delta_pp"] >= 2.0
                and summary["last_5y_max_dd_delta_pp"] >= 1.0
                and summary["last_3y_max_dd_delta_pp"] >= 1.0
                and summary["last_10y_annual_delta_pp"] >= -1.5
                and summary["last_5y_annual_delta_pp"] >= -1.0
                and summary["last_3y_annual_delta_pp"] >= -1.0
            )
            summary["defense_score"] = (
                summary["last_10y_max_dd_delta_pp"]
                + summary["last_5y_max_dd_delta_pp"]
                + summary["last_3y_max_dd_delta_pp"]
                + 0.25 * summary["full_max_dd_delta_pp"]
                + 0.5 * min(summary["last_10y_annual_delta_pp"], 2.0)
                + 0.5 * min(summary["last_5y_annual_delta_pp"], 2.0)
                + 0.5 * min(summary["last_3y_annual_delta_pp"], 2.0)
            )
            summary_rows.append(summary)
    return summary_rows, window_rows


def main() -> None:
    mod = load_module()
    dk_close = load_dk_close(mod)
    raw_adk = run_current_v77_adk(mod, dk_close)
    base_ret = pd.to_numeric(raw_adk["return"], errors="coerce").dropna().sort_index()
    base_ret = base_ret.loc[base_ret.index >= FORMAL_START]

    amount_specs = [
        ("sz50", "SZ50", mod.CN_DK_SZ50_SECID, mod.CN_DK_COLS[1]),
        ("hs300", "HS300", mod.CN_DK_HS300_SECID, mod.CN_DK_COLS[2]),
        ("zz500", "ZZ500", mod.CN_DK_ZZ500_SECID, mod.CN_DK_COLS[3]),
        ("zz1000", "ZZ1000", mod.CN_DK_ZZ1000_SECID, mod.CN_DK_COLS[0]),
        ("cyb", "CYB", mod.CN_DK_CYB_SECID, mod.CN_DK_COLS[4]),
    ]

    summary_rows: list[dict] = []
    window_rows: list[dict] = []
    availability_rows: list[dict] = []
    amount_sources: dict[str, str] = {}
    for source_key, label, secid, price_col in amount_specs:
        price = dk_close[price_col].dropna()
        amount_df, amount_source = mod._fetch_cn_amount_with_fallback(
            secid,
            label,
            beg=mod.CN_SA_VOLUME_HISTORY_BEG,
            lmt=10000,
        )
        amount = pd.to_numeric(amount_df["amount"], errors="coerce").dropna().sort_index()
        amount_sources[source_key] = amount_source
        availability_rows.append(
            {
                "source_key": source_key,
                "source_label": label,
                "secid": secid,
                "price_start": str(price.index.min().date()),
                "price_end": str(price.index.max().date()),
                "price_rows": int(len(price)),
                "amount_source": amount_source,
                "amount_start": str(amount.index.min().date()),
                "amount_end": str(amount.index.max().date()),
                "amount_rows": int(len(amount)),
                "formal_eval_start": str(FORMAL_START.date()),
            }
        )
        s_rows, w_rows = scan_one_amount_series(source_key, label, amount, base_ret)
        summary_rows.extend(s_rows)
        window_rows.extend(w_rows)

    summary = pd.DataFrame(summary_rows)
    window_metrics = pd.DataFrame(window_rows)
    availability = pd.DataFrame(availability_rows)

    sort_cols = ["robust_pass", "defense_score", "last_10y_max_dd_delta_pp", "last_5y_max_dd_delta_pp"]
    top_candidates = summary.sort_values(sort_cols, ascending=[False, False, False, False]).head(50)
    best_by_source = (
        summary.sort_values(sort_cols, ascending=[False, False, False, False])
        .groupby("source_key", as_index=False)
        .head(1)
        .sort_values(sort_cols, ascending=[False, False, False, False])
    )
    source_summary_rows = []
    for source_key, group in summary.groupby("source_key"):
        best = group.sort_values(sort_cols, ascending=[False, False, False, False]).iloc[0]
        source_summary_rows.append(
            {
                "source_key": source_key,
                "source_label": str(best["source_label"]),
                "amount_source": amount_sources[source_key],
                "candidate_count": int(len(group)),
                "robust_pass_count": int(group["robust_pass"].sum()),
                "best_candidate": str(best["candidate"]),
                "best_ma": int(best["ma"]),
                "best_days": int(best["days"]),
                "best_defense_score": float(best["defense_score"]),
                "best_10y_ann_delta_pp": float(best["last_10y_annual_delta_pp"]),
                "best_10y_maxdd_delta_pp": float(best["last_10y_max_dd_delta_pp"]),
                "best_5y_ann_delta_pp": float(best["last_5y_annual_delta_pp"]),
                "best_5y_maxdd_delta_pp": float(best["last_5y_max_dd_delta_pp"]),
                "best_3y_ann_delta_pp": float(best["last_3y_annual_delta_pp"]),
                "best_3y_maxdd_delta_pp": float(best["last_3y_max_dd_delta_pp"]),
                "best_full_ann_delta_pp": float(best["full_annual_delta_pp"]),
                "best_full_maxdd_delta_pp": float(best["full_max_dd_delta_pp"]),
            }
        )
    source_summary = pd.DataFrame(source_summary_rows).sort_values(
        ["robust_pass_count", "best_defense_score"],
        ascending=[False, False],
    )

    baseline_rows = []
    for window in WINDOWS:
        part = window_slice(base_ret, window)
        baseline_rows.append(
            {
                "window": window,
                "start": str(part.index.min().date()) if len(part) else "",
                "end": str(part.index.max().date()) if len(part) else "",
                "n_days": int(len(part)),
                **calc_metrics(part),
                **{f"dd_{k}": v for k, v in max_dd_span(part).items() if k != "max_dd_pct"},
            }
        )
    baseline_metrics = pd.DataFrame(baseline_rows)

    summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    top_candidates.to_csv(RUN_DIR / "top_candidates.csv", index=False, encoding="utf-8-sig")
    best_by_source.to_csv(RUN_DIR / "best_by_source.csv", index=False, encoding="utf-8-sig")
    source_summary.to_csv(RUN_DIR / "source_summary.csv", index=False, encoding="utf-8-sig")
    availability.to_csv(RUN_DIR / "amount_availability.csv", index=False, encoding="utf-8-sig")
    baseline_metrics.to_csv(RUN_DIR / "baseline_metrics.csv", index=False, encoding="utf-8-sig")

    meta_path = RUN_DIR / "scan_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "phase": "ran",
            "scan_type": "multi_index_amount_filter_grid",
            "baseline": {
                "entrypoint": str(ENTRYPOINT),
                "formal_eval_start": str(FORMAL_START.date()),
                "adk_pair_pool": list(mod.ADK_OFFICIAL_PAIR_ORDER),
                "target_vol": mod.CN_DK_TARGET_VOL,
                "vol_window": mod.CN_DK_VOL_WINDOW,
                "same_side_overheat_enabled": mod.CN_DK_SAME_SIDE_OVERHEAT_ENABLED,
                "same_side_overheat_enter": mod.CN_DK_SAME_SIDE_OVERHEAT_ENTER,
                "same_side_overheat_exit": mod.CN_DK_SAME_SIDE_OVERHEAT_EXIT,
                "risk_gate_enabled": mod.CN_DK_RISK_GATE_ENABLED,
                "pair_score_decay_enabled": mod.CN_DK_PAIR_SCORE_DECAY_ENABLED,
            },
            "candidate_grid": {
                "sources": [row[0] for row in amount_specs],
                "ma_values": MA_VALUES,
                "days_values": DAYS_VALUES,
                "scale_when_true": SCALE_WHEN_TRUE,
                "extra_cost_bps_per_abs_scale_change": COST_BPS,
                "signal_timing": "T close amount signal shifts to T+1 ADK total exposure",
            },
            "data_snapshot": {
                "cn_data": str(CN_DATA),
                "dk_close_start": str(dk_close.index.min().date()),
                "dk_close_end": str(dk_close.index.max().date()),
                "baseline_return_start": str(base_ret.index.min().date()),
                "baseline_return_end": str(base_ret.index.max().date()),
                "amount_sources": amount_sources,
                "availability_csv": str(RUN_DIR / "amount_availability.csv"),
            },
            "cost_model": {
                "base_adk_commission": mod.CN_DK_COMMISSION,
                "extra_volume_overlay_cost": f"{COST_BPS}bp * abs(scale change)",
                "slippage": "not separately modeled beyond configured ADK commission and overlay scale-change cost",
                "open_impact": "not modeled",
            },
            "outputs": {
                **meta.get("outputs", {}),
                "top_candidates": str(RUN_DIR / "top_candidates.csv"),
                "best_by_source": str(RUN_DIR / "best_by_source.csv"),
                "source_summary": str(RUN_DIR / "source_summary.csv"),
                "amount_availability": str(RUN_DIR / "amount_availability.csv"),
                "baseline_metrics": str(RUN_DIR / "baseline_metrics.csv"),
            },
        }
    )
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    record = f"""# V7.7 ADK Multi-Index Amount Filter Scan

## Question

Check whether the prior HS300 amount rule remains the only useful DK/ADK volume source after V7.7 8-pair formalization, using the other ADK-involved indices on the same rule family.

## Baseline

- Entry point: `{ENTRYPOINT.name}`
- ADK production path: formal 8-pair V7.7 Sub-A-DK.
- Formal evaluation start: `{FORMAL_START.date()}` because the current full ADK pool includes ZZ1000.
- Baseline data: `{CN_DATA.name}`.
- Baseline return end: `{base_ret.index.max().date()}`.

## Candidate Grid

- Sources: SZ50, HS300, ZZ500, ZZ1000, CYB.
- Rule: index amount below its own MA for N consecutive days.
- Grid: MA `{MA_VALUES[0]}..{MA_VALUES[-1]}` step 1, days `{DAYS_VALUES[0]}..{DAYS_VALUES[-1]}` step 1.
- Execution: T close volume state affects T+1 ADK total exposure.
- Defense action: scale ADK exposure to `{SCALE_WHEN_TRUE:.0%}`.
- Extra cost: `{COST_BPS:.1f}bp * abs(scale change)`.

## Outputs

- `scan_summary.csv`: one row per source/MA/days candidate with full and recent windows.
- `window_metrics.csv`: long-form window metrics.
- `source_summary.csv`: best candidate and robust-pass count by source.
- `best_by_source.csv`: top candidate per source.
- `top_candidates.csv`: global top candidates.
- `amount_availability.csv`: price/amount availability and source checks.
- `baseline_metrics.csv`: V7.7 ADK baseline by window.

## Decision

Pending final interpretation after strict artifact check.
"""
    (RUN_DIR / "record.md").write_text(record, encoding="utf-8")

    print(f"Wrote {RUN_DIR}")
    print(source_summary.to_string(index=False))


if __name__ == "__main__":
    main()

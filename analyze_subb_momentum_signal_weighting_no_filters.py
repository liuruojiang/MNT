from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import analyze_subb_parameter_stability as subb


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "mnt_bot V 7.7 plus.py"
LBS = (160, 260, 390)
WINDOWS = {
    "full": None,
    "last_10y": pd.DateOffset(years=10),
    "last_5y": pd.DateOffset(years=5),
    "last_3y": pd.DateOffset(years=3),
    "last_1y": pd.DateOffset(years=1),
}


def normalize_weights(raw: dict[int, float]) -> dict[int, float]:
    total = float(sum(raw.values()))
    if total <= 0:
        raise ValueError(f"invalid weights: {raw}")
    return {int(k): float(v) / total for k, v in raw.items()}


def weight_sets() -> dict[str, dict[int, float]]:
    exp_hl260 = {lb: math.exp(-(lb - min(LBS)) / 260.0) for lb in LBS}
    return {
        "equal_1_1_1": normalize_weights({160: 1.0, 260: 1.0, 390: 1.0}),
        "recent_3_2_1": normalize_weights({160: 3.0, 260: 2.0, 390: 1.0}),
        "recent_50_30_20": normalize_weights({160: 0.50, 260: 0.30, 390: 0.20}),
        "recent_60_30_10": normalize_weights({160: 0.60, 260: 0.30, 390: 0.10}),
        "inverse_lookback": normalize_weights({lb: 1.0 / lb for lb in LBS}),
        "sqrt_inverse_lookback": normalize_weights({lb: 1.0 / math.sqrt(lb) for lb in LBS}),
        "exp_halflife_260": normalize_weights(exp_hl260),
    }


def weighted_average_dicts(items: list[tuple[dict[str, float], float]]) -> dict[str, float]:
    keys: set[str] = set()
    for weights, _weight in items:
        keys.update(weights)
    return {key: sum(weights.get(key, 0.0) * weight for weights, weight in items) for key in keys}


def weighted_signal(momentum_rows: dict[int, pd.Series], weights: dict[int, float]) -> pd.Series:
    out = None
    for lb, weight in weights.items():
        row = momentum_rows[lb].astype(float) * float(weight)
        out = row if out is None else out.add(row, fill_value=0.0)
    return out if out is not None else pd.Series(dtype=float)


def run_raw_momentum(
    ctx: subb.MarketContext,
    weights: dict[int, float],
    combine_mode: str,
) -> pd.DataFrame:
    mod = ctx.mod
    ranking_codes = list(mod.US_ROT_POOL)
    w_assets = list(dict.fromkeys(ranking_codes + ["BIL"]))
    momentum_by_lb = {lb: ctx.close_df.div(ctx.close_df.shift(lb)).sub(1) for lb in LBS}
    vol_df = ctx.close_df.pct_change().rolling(mod.US_ROT_VOL_LB).std() * np.sqrt(mod.US_TRADING_DAYS)
    start_idx = max(max(LBS), mod.US_ROT_VOL_LB, mod.US_ROT_VOL_WINDOW) + 1
    signal_days = mod._us_signal_days(ctx.close_df, start_idx)

    act: dict[str, float] = {"BIL": 1.0}
    holdings: dict[str, float] = {"BIL": 1.0}
    pending_act: dict[str, float] | None = None
    pending_comm = 0.0
    hist: list[float] = []
    rows: list[dict[str, Any]] = []
    scale = 1.0

    for i in range(start_idx, len(ctx.close_df)):
        if len(hist) >= mod.US_ROT_VOL_WINDOW:
            rv = np.std(hist[-mod.US_ROT_VOL_WINDOW :], ddof=1) * np.sqrt(mod.US_TRADING_DAYS)
            scale = min(max(mod.US_ROT_TARGET_VOL / rv, 0.05), mod.US_ROT_MAX_LEV) if rv > 0.001 else mod.US_ROT_MAX_LEV

        if pending_act is not None:
            open_row = mod._us_open_row(ctx.close_df.index[i], w_assets, ctx.open_map, ctx.close_df)
            overnight = mod._us_weighted_return(holdings, ctx.close_df.iloc[i - 1], open_row)
            intraday = mod._us_weighted_return(pending_act, open_row, ctx.close_df.iloc[i])
            gross = (1.0 + overnight) * (1.0 + intraday) - 1.0
            execution_cost = float(pending_comm)
            ret = (1.0 + gross) * (1.0 - execution_cost) - 1.0
            holdings = dict(pending_act)
            pending_act = None
            pending_comm = 0.0
        else:
            gross = mod._us_weighted_return(holdings, ctx.close_df.iloc[i - 1], ctx.close_df.iloc[i])
            execution_cost = 0.0
            ret = gross

        hist.append(float(ret))
        is_signal = i in signal_days
        rebalanced = False
        turnover = 0.0
        active_signal = pd.Series(dtype=float)

        if is_signal:
            momentum_rows = {lb: momentum_by_lb[lb].iloc[i] for lb in LBS}
            if combine_mode == "window_target":
                acts = []
                for lb in LBS:
                    raw = mod._us_raw_weights(
                        momentum_rows[lb],
                        vol_df.iloc[i],
                        ranking_codes,
                        3,
                        -999.0,
                        prev_risky=None,
                        threshold=1.0,
                    )
                    acts.append((mod._us_model_b(raw, scale), weights[lb]))
                new_act = weighted_average_dicts(acts)
                active_signal = weighted_signal(momentum_rows, weights)
            elif combine_mode == "weighted_signal":
                active_signal = weighted_signal(momentum_rows, weights)
                raw = mod._us_raw_weights(
                    active_signal,
                    vol_df.iloc[i],
                    ranking_codes,
                    3,
                    -999.0,
                    prev_risky=None,
                    threshold=1.0,
                )
                new_act = mod._us_model_b(raw, scale)
            else:
                raise ValueError(f"unknown combine_mode: {combine_mode}")

            prev_act = {asset: act.get(asset, 0.0) for asset in w_assets} if rows else {"BIL": 1.0}
            all_assets = set(prev_act) | set(new_act)
            turnover = sum(abs(new_act.get(asset, 0.0) - prev_act.get(asset, 0.0)) for asset in all_assets if asset != "BIL")
            pending_act = dict(new_act)
            pending_comm = turnover * mod.US_ROT_COMMISSION if turnover > 0 else 0.0
            act = dict(new_act)
            rebalanced = True

        row: dict[str, Any] = {
            "date": ctx.close_df.index[i],
            "return": float(ret),
            "return_before_execution_cost": float(gross),
            "execution_cost": float(execution_cost),
            "is_signal": bool(is_signal),
            "rebalanced": bool(rebalanced),
            "turnover": float(turnover),
            "scale": float(scale),
        }
        for asset in w_assets:
            row[f"w_{asset}"] = holdings.get(asset, 0.0)
            row[f"target_w_{asset}"] = act.get(asset, 0.0)
            if is_signal and asset in ranking_codes:
                row[f"sig_{asset}"] = float(active_signal.get(asset, np.nan))
        rows.append(row)

    result = pd.DataFrame(rows).set_index("date")
    result["nav"] = (1.0 + result["return"]).cumprod()
    return result


def calc_metrics(ret: pd.Series) -> dict[str, float] | None:
    ret = pd.to_numeric(ret, errors="coerce").dropna()
    if len(ret) < 20:
        return None
    nav = (1.0 + ret).cumprod()
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    if years <= 0 or nav.iloc[-1] <= 0:
        return None
    std = float(ret.std(ddof=1))
    maxdd = float((nav / nav.cummax() - 1.0).min())
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0)
    monthly = ret.groupby(ret.index.to_period("M")).apply(lambda values: (1.0 + values).prod() - 1.0)
    return {
        "days": float(len(ret)),
        "cagr": cagr,
        "vol": float(std * math.sqrt(252.0)),
        "sharpe": float(ret.mean() / std * math.sqrt(252.0)) if std > 0 else np.nan,
        "maxdd": maxdd,
        "calmar": float(cagr / abs(maxdd)) if maxdd < 0 else np.nan,
        "final_nav": float(nav.iloc[-1]),
        "monthly_win_rate": float((monthly > 0).mean()) if len(monthly) else np.nan,
    }


def exposure_metrics(result: pd.DataFrame) -> dict[str, float]:
    w_cols = [col for col in result.columns if col.startswith("w_")]
    risky_cols = [col for col in w_cols if col != "w_BIL"]
    risky = result[risky_cols].sum(axis=1) if risky_cols else pd.Series(0.0, index=result.index)
    bil = result["w_BIL"] if "w_BIL" in result.columns else pd.Series(0.0, index=result.index)
    signal = result["is_signal"].astype(bool) if "is_signal" in result.columns else pd.Series(False, index=result.index)
    return {
        "avg_risky": float(risky.mean()),
        "avg_bil": float(bil.mean()),
        "rebalance_days": float(result["rebalanced"].astype(bool).sum()) if "rebalanced" in result.columns else np.nan,
        "signal_days": float(signal.sum()),
        "avg_turnover_on_signal": float(result.loc[signal, "turnover"].mean()) if signal.any() else np.nan,
    }


def window_rows(candidate: str, combine_mode: str, weights: dict[int, float], result: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    end = result.index.max()
    for window, offset in WINDOWS.items():
        part = result if offset is None else result.loc[result.index >= end - offset]
        metrics = calc_metrics(part["return"])
        if metrics is None:
            continue
        row: dict[str, Any] = {
            "candidate": candidate,
            "combine_mode": combine_mode,
            "window": window,
            "start": part.index.min().date().isoformat(),
            "end": part.index.max().date().isoformat(),
            "w_160": weights[160],
            "w_260": weights[260],
            "w_390": weights[390],
        }
        row.update(metrics)
        row.update(exposure_metrics(part))
        rows.append(row)
    return rows


def add_deltas(metrics_df: pd.DataFrame) -> pd.DataFrame:
    out = metrics_df.copy()
    keys = ["combine_mode", "window"]
    baseline = out[out["candidate"] == "equal_1_1_1"][
        keys + ["cagr", "sharpe", "maxdd", "calmar", "final_nav"]
    ].rename(
        columns={
            "cagr": "base_cagr",
            "sharpe": "base_sharpe",
            "maxdd": "base_maxdd",
            "calmar": "base_calmar",
            "final_nav": "base_final_nav",
        }
    )
    out = out.merge(baseline, on=keys, how="left")
    out["delta_cagr"] = out["cagr"] - out["base_cagr"]
    out["delta_sharpe"] = out["sharpe"] - out["base_sharpe"]
    out["delta_maxdd"] = out["maxdd"] - out["base_maxdd"]
    out["delta_calmar"] = out["calmar"] - out["base_calmar"]
    out["delta_final_nav"] = out["final_nav"] - out["base_final_nav"]
    return out


def write_record(out_dir: Path, metrics: pd.DataFrame, meta: dict[str, Any]) -> None:
    primary = metrics[(metrics["combine_mode"] == "window_target") & (metrics["window"].isin(["last_10y", "last_5y", "last_3y", "last_1y"]))]
    primary_rank = primary.copy()
    primary_rank["recent_score"] = (
        primary_rank["sharpe"].fillna(-999.0) * 0.45
        + primary_rank["calmar"].fillna(-999.0) * 0.35
        + primary_rank["cagr"].fillna(-999.0) * 0.20
    )
    table = primary_rank[primary_rank["window"].isin(["last_10y", "last_5y"])][
        ["candidate", "window", "cagr", "sharpe", "maxdd", "calmar", "delta_cagr", "delta_sharpe", "delta_maxdd"]
    ]
    lines = [
        "# V7.7 Sub-B 160/260/390 Momentum Weighting Without Filters",
        "",
        "Scope: raw Sub-B three-window momentum isolation.",
        "",
        "Removed filters: absolute momentum gate, inflation macro gate, EMA leg, VolReg overlay, switch buffer, min-turnover gate.",
        "Retained: US_ROT_POOL, Top3 selection, inverse-vol position sizing, target-vol scale, T close signal -> T+1 adjusted open execution, default commission.",
        "",
        f"Data: {meta['data_source']}; merged {meta['merged_start']}~{meta['merged_end']}, rows={meta['merged_rows']}.",
        "",
        "## Primary Window-Target Comparison",
        "",
        table.to_markdown(index=False, floatfmt=".4f"),
        "",
        "Full outputs: `scan_summary.csv`, `window_metrics.csv`, `daily_returns.csv`, `scan_meta.json`.",
        "",
    ]
    (out_dir / "record.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    command = "python analyze_subb_momentum_signal_weighting_no_filters.py --out-dir " + str(out_dir)
    (out_dir / "command_log.txt").write_text(command + "\n", encoding="utf-8")

    mod = subb.load_module(SCRIPT, "mnt_bot_v77_subb_weighting_no_filters")
    ctx = subb.build_market_context(mod, SCRIPT)

    all_rows: list[dict[str, Any]] = []
    daily_returns: dict[str, pd.Series] = {}
    result_paths: dict[str, str] = {}
    weights_by_name = weight_sets()
    for combine_mode in ("window_target", "weighted_signal"):
        for name, weights in weights_by_name.items():
            result = run_raw_momentum(ctx, weights, combine_mode)
            key = f"{combine_mode}__{name}"
            daily_returns[key] = result["return"]
            all_rows.extend(window_rows(name, combine_mode, weights, result))
            result_path = out_dir / f"{key}_daily.csv"
            result.to_csv(result_path, index_label="date", encoding="utf-8-sig")
            result_paths[key] = str(result_path)

    metrics = add_deltas(pd.DataFrame(all_rows))
    metrics.to_csv(out_dir / "window_metrics.csv", index=False, encoding="utf-8-sig")
    metrics.to_csv(out_dir / "scan_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(daily_returns).to_csv(out_dir / "daily_returns.csv", index_label="date", encoding="utf-8-sig")

    meta = {
        **ctx.audit,
        "strategy_script": str(SCRIPT),
        "parameter_group": "momentum_window_signal_weighting_no_filters",
        "weight_sets": {name: {str(k): v for k, v in weights.items()} for name, weights in weights_by_name.items()},
        "combine_modes": {
            "window_target": "each lookback builds Top3 target weights, then target weights are window-weighted",
            "weighted_signal": "lookback returns are weighted first, then a single Top3 is selected",
        },
        "removed_filters": [
            "US_ROT_ABS_THRESHOLD",
            "_subb_active_ranking_codes inflation macro gate",
            "run_subb_v75_ema_base7_rotation EMA leg",
            "apply_vol_regime_overlay VolReg overlay",
            "US_ROT_REBALANCE_THRESHOLD switch buffer",
            "US_ROT_MIN_TURNOVER rebalance gate",
        ],
        "retained_assumptions": [
            "US_ROT_POOL ranking universe",
            "Top3 selection",
            "inverse-vol raw weights",
            "US_ROT_TARGET_VOL scale and US_ROT_MAX_LEV cap",
            "T close signal -> T+1 adjusted open execution when open data exists",
            "US_ROT_COMMISSION transaction cost",
        ],
        "outputs": {
            "scan_summary": str(out_dir / "scan_summary.csv"),
            "window_metrics": str(out_dir / "window_metrics.csv"),
            "daily_returns": str(out_dir / "daily_returns.csv"),
            "result_paths": result_paths,
        },
    }
    (out_dir / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    write_record(out_dir, metrics, meta)
    print(f"done: {out_dir}")


if __name__ == "__main__":
    main()

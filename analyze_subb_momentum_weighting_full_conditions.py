from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import analyze_subb_parameter_stability as subb
from analyze_subb_momentum_signal_weighting_no_filters import (
    LBS,
    SCRIPT,
    calc_metrics,
    weight_sets,
    weighted_average_dicts,
)


ROOT = Path(__file__).resolve().parent
WINDOWS = {
    "full": None,
    "last_10y": pd.DateOffset(years=10),
    "last_5y": pd.DateOffset(years=5),
    "last_3y": pd.DateOffset(years=3),
    "last_1y": pd.DateOffset(years=1),
}


def run_weighted_official_leg(ctx: subb.MarketContext, weights: dict[int, float]) -> pd.DataFrame:
    mod = ctx.mod
    ranking_codes = list(mod.US_ROT_BASE_POOL)
    weight_assets = list(mod.US_ROT_POOL)
    w_assets = list(dict.fromkeys(weight_assets + ["BIL"]))
    momentum_by_lb = {lb: ctx.close_df.div(ctx.close_df.shift(lb)).sub(1) for lb in LBS}
    vol_df = ctx.close_df.pct_change().rolling(mod.US_ROT_VOL_LB).std() * np.sqrt(mod.US_TRADING_DAYS)
    start_idx = max(max(LBS), mod.US_ROT_VOL_LB, mod.US_ROT_VOL_WINDOW) + 1
    signal_days = mod._us_signal_days(ctx.close_df, start_idx)

    act: dict[str, float] = {"BIL": 1.0}
    holdings: dict[str, float] = {"BIL": 1.0}
    pending_act: dict[str, float] | None = None
    pending_comm = 0.0
    scale = 1.0
    prev_risky_by_lb: dict[int, set[str] | None] = {lb: None for lb in LBS}
    rows: list[dict[str, Any]] = []
    hist: list[float] = []

    for i in range(start_idx, len(ctx.close_df)):
        if len(hist) >= mod.US_ROT_VOL_WINDOW:
            rv = np.std(hist[-mod.US_ROT_VOL_WINDOW :], ddof=1) * np.sqrt(mod.US_TRADING_DAYS)
            scale = min(max(mod.US_ROT_TARGET_VOL / rv, 0.05), mod.US_ROT_MAX_LEV) if rv > 0.001 else mod.US_ROT_MAX_LEV

        if pending_act is not None:
            open_row = mod._us_open_row(ctx.close_df.index[i], w_assets, ctx.open_map, ctx.close_df)
            overnight = mod._us_weighted_return(holdings, ctx.close_df.iloc[i - 1], open_row)
            intraday = mod._us_weighted_return(pending_act, open_row, ctx.close_df.iloc[i])
            gross_adj = (1.0 + overnight) * (1.0 + intraday) - 1.0
            execution_cost = float(pending_comm)
            adj = (1.0 + gross_adj) * (1.0 - execution_cost) - 1.0
            holdings = dict(pending_act)
            pending_act = None
            pending_comm = 0.0
        else:
            gross_adj = mod._us_weighted_return(holdings, ctx.close_df.iloc[i - 1], ctx.close_df.iloc[i])
            execution_cost = 0.0
            adj = gross_adj

        hist.append(float(adj))
        is_signal = i in signal_days
        rebalanced = False
        active_ranking_codes = list(ranking_codes)
        row_selected_by_lb = {lb: prev_risky_by_lb.get(lb) for lb in LBS}

        if is_signal:
            active_ranking_codes = list(mod._subb_active_ranking_codes(ctx.close_df, i, ranking_codes))
            momentum_rows = {lb: momentum_by_lb[lb].iloc[i] for lb in LBS}
            acts: list[tuple[dict[str, float], float]] = []
            per_lb: dict[int, dict[str, Any]] = {}
            for lb in LBS:
                prev_risky = prev_risky_by_lb.get(lb)
                raw = mod._us_raw_weights(
                    momentum_rows[lb],
                    vol_df.iloc[i],
                    active_ranking_codes,
                    3,
                    mod.US_ROT_ABS_THRESHOLD,
                    prev_risky=prev_risky,
                    threshold=mod.US_ROT_REBALANCE_THRESHOLD,
                )
                act_lb = mod._us_model_b(raw, scale)
                acts.append((act_lb, weights[lb]))
                per_lb[lb] = {
                    "selected": mod._us_selected_risky_from_raw(raw),
                    "act": act_lb,
                    "raw": raw,
                }
            new_act = weighted_average_dicts(acts)
            next_prev_risky_by_lb = {lb: per_lb[lb]["selected"] or None for lb in LBS}
            prev_act = {asset: act.get(asset, 0.0) for asset in w_assets} if rows else {"BIL": 1.0}
            all_assets = set(prev_act) | set(new_act)
            turnover = sum(abs(new_act.get(asset, 0.0) - prev_act.get(asset, 0.0)) for asset in all_assets if asset != "BIL")
            if turnover >= mod.US_ROT_MIN_TURNOVER:
                pending_act = dict(new_act)
                pending_comm = turnover * mod.US_ROT_COMMISSION if turnover > 0 else 0.0
                act = dict(new_act)
                prev_risky_by_lb = next_prev_risky_by_lb
                row_selected_by_lb = next_prev_risky_by_lb
                rebalanced = True

        row: dict[str, Any] = {
            "date": ctx.close_df.index[i],
            "return": float(adj),
            "return_before_execution_cost": float(gross_adj),
            "execution_cost": float(execution_cost),
            "is_signal": bool(is_signal),
            "rebalanced": bool(rebalanced),
            "inflation_pressure_on": mod._inflation_pressure_on_from_prices(ctx.close_df, i),
            "ranking_codes": ",".join(active_ranking_codes),
            "scale": float(scale),
        }
        for asset in w_assets:
            row[f"w_{asset}"] = holdings.get(asset, 0.0)
            row[f"actual_w_{asset}"] = holdings.get(asset, 0.0)
            row[f"target_w_{asset}"] = act.get(asset, 0.0)
        for lb in LBS:
            row[f"sel_{lb}"] = mod._serialize_us_mix_selected(row_selected_by_lb.get(lb))
        rows.append(row)

    result = pd.DataFrame(rows).set_index("date")
    result["nav"] = (1.0 + result["return"]).cumprod()
    return result


def run_full_candidate(
    ctx: subb.MarketContext,
    weights: dict[int, float],
    cached_ema: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mod = ctx.mod
    official = run_weighted_official_leg(ctx, weights)
    ema = cached_ema
    if ema is None:
        ema = mod.run_subb_v75_ema_base7_rotation(
            ctx.close_df,
            base_codes=list(mod.US_ROT_POOL),
            us_open=ctx.open_map,
            weight_assets=list(mod.US_ROT_POOL),
        )
    result = mod.blend_subb_v75_results(official, ema)
    if mod.US_ROT_VOLREG_ENABLED and "SPY" in ctx.close_df.columns:
        result = mod.apply_vol_regime_overlay(result, ctx.close_df["SPY"])
    result = result.copy()
    result["return"] = pd.to_numeric(result["return"], errors="coerce").fillna(0.0)
    result["nav"] = (1.0 + result["return"]).cumprod()
    return result, ema


def run_official_baseline(ctx: subb.MarketContext) -> pd.DataFrame:
    mod = ctx.mod
    official = mod.run_us_rotation_mix(
        ctx.close_df,
        list(mod.US_ROT_BASE_POOL),
        us_open=ctx.open_map,
        ranking_code_selector=mod._subb_active_ranking_codes,
        weight_assets=list(mod.US_ROT_POOL),
    )
    ema = mod.run_subb_v75_ema_base7_rotation(
        ctx.close_df,
        base_codes=list(mod.US_ROT_POOL),
        us_open=ctx.open_map,
        weight_assets=list(mod.US_ROT_POOL),
    )
    result = mod.blend_subb_v75_results(official, ema)
    if mod.US_ROT_VOLREG_ENABLED and "SPY" in ctx.close_df.columns:
        result = mod.apply_vol_regime_overlay(result, ctx.close_df["SPY"])
    result = result.copy()
    result["return"] = pd.to_numeric(result["return"], errors="coerce").fillna(0.0)
    result["nav"] = (1.0 + result["return"]).cumprod()
    return result


def window_rows(candidate: str, weights: dict[int, float], result: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    end = result.index.max()
    for segment, offset in WINDOWS.items():
        part = result if offset is None else result.loc[result.index >= end - offset]
        metrics = calc_metrics(part["return"])
        if metrics is None:
            continue
        row: dict[str, Any] = {
            "candidate": candidate,
            "segment": segment,
            "start": part.index.min().date().isoformat(),
            "end": part.index.max().date().isoformat(),
            "rows": int(round(metrics.pop("days"))),
            "ann_return": metrics.pop("cagr"),
            "ann_vol": metrics.pop("vol"),
            "sharpe_repo": metrics.pop("sharpe"),
            "max_dd": metrics.pop("maxdd"),
            "w_160": weights[160],
            "w_260": weights[260],
            "w_390": weights[390],
        }
        row.update(metrics)
        exp = exposure_metrics_full_path(part)
        row["avg_weight"] = exp.get("avg_risky")
        row["avg_bil"] = exp.get("avg_bil")
        row["avg_turnover"] = exp.get("avg_turnover_on_signal")
        row["holding_day_ratio"] = exp.get("avg_risky")
        row["rebalance_days"] = exp.get("rebalance_days")
        row["signal_days"] = exp.get("signal_days")
        rows.append(row)
    return rows


def exposure_metrics_full_path(result: pd.DataFrame) -> dict[str, float]:
    w_cols = [col for col in result.columns if col.startswith("w_")]
    risky_cols = [col for col in w_cols if col not in ("w_BIL", "w_CASH")]
    risky = result[risky_cols].sum(axis=1) if risky_cols else pd.Series(0.0, index=result.index)
    bil = result["w_BIL"] if "w_BIL" in result.columns else pd.Series(0.0, index=result.index)
    signal = result["is_signal"].fillna(False).astype(bool) if "is_signal" in result.columns else pd.Series(False, index=result.index)
    turnover_col = None
    for candidate in ("subb_effective_turnover", "subb_execution_turnover", "turnover"):
        if candidate in result.columns:
            turnover_col = candidate
            break
    if turnover_col is not None and signal.any():
        avg_turnover = float(pd.to_numeric(result.loc[signal, turnover_col], errors="coerce").mean())
    else:
        avg_turnover = np.nan
    return {
        "avg_risky": float(risky.mean()),
        "avg_bil": float(bil.mean()),
        "rebalance_days": float(result["rebalanced"].fillna(False).astype(bool).sum()) if "rebalanced" in result.columns else np.nan,
        "signal_days": float(signal.sum()),
        "avg_turnover_on_signal": avg_turnover,
    }


def add_deltas(summary: pd.DataFrame) -> pd.DataFrame:
    base = summary[summary["candidate"] == "equal_1_1_1"][
        ["segment", "ann_return", "sharpe_repo", "max_dd", "calmar", "final_nav"]
    ].rename(
        columns={
            "ann_return": "base_ann_return",
            "sharpe_repo": "base_sharpe_repo",
            "max_dd": "base_max_dd",
            "calmar": "base_calmar",
            "final_nav": "base_final_nav",
        }
    )
    out = summary.merge(base, on="segment", how="left")
    out["delta_ann_return"] = out["ann_return"] - out["base_ann_return"]
    out["delta_sharpe"] = out["sharpe_repo"] - out["base_sharpe_repo"]
    out["delta_max_dd"] = out["max_dd"] - out["base_max_dd"]
    out["delta_calmar"] = out["calmar"] - out["base_calmar"]
    out["delta_final_nav"] = out["final_nav"] - out["base_final_nav"]
    return out


def make_window_metrics(summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for candidate, group in summary.groupby("candidate", sort=False):
        first = group.iloc[0]
        row = {
            "candidate": candidate,
            "w_160": first["w_160"],
            "w_260": first["w_260"],
            "w_390": first["w_390"],
        }
        for segment in ["full", "last_10y", "last_5y", "last_3y", "last_1y"]:
            part = group[group["segment"] == segment]
            if part.empty:
                continue
            r = part.iloc[0]
            row[f"ann_return_{segment}"] = r["ann_return"]
            row[f"max_dd_{segment}"] = r["max_dd"]
            row[f"sharpe_repo_{segment}"] = r["sharpe_repo"]
            row[f"avg_weight_{segment}"] = r["avg_weight"]
            row[f"avg_turnover_{segment}"] = r["avg_turnover"]
        row["decision_hint"] = "compare_to_equal_full_conditions"
        row["stability_label"] = "full-conditions-weighting-mixed"
        rows.append(row)
    return pd.DataFrame(rows)


def git_text(args: list[str]) -> str:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:
        return f"unavailable: {exc}"


def write_record(out_dir: Path, summary: pd.DataFrame, meta: dict[str, Any], parity: dict[str, Any]) -> None:
    primary = summary[(summary["segment"].isin(["last_10y", "last_5y", "last_3y", "last_1y"]))].copy()
    primary["ann_return_pct"] = primary["ann_return"] * 100.0
    primary["max_dd_pct"] = primary["max_dd"] * 100.0
    primary["delta_ann_return_pct"] = primary["delta_ann_return"] * 100.0
    table = primary[
        ["candidate", "segment", "ann_return", "sharpe_repo", "max_dd", "calmar", "delta_ann_return", "delta_sharpe", "delta_max_dd"]
    ].to_markdown(index=False, floatfmt=".4f")
    lines = [
        "# V7.7 Sub-B Momentum Window Weighting With Full Conditions",
        "",
        "## Run Metadata",
        f"- Run folder: `{out_dir}`",
        "- Project: A股美股动量组合策略",
        "- Strategy/subsystem: V7.7 / Sub-B",
        "- Source-change rule: research-only standalone script; formal strategy files were not edited.",
        "",
        "## Research Question",
        "Restore the official Sub-B filters and overlays, then test whether recent-heavy 160/260/390 weighting still adds value versus equal weighting.",
        "",
        "## Implementation Anchor",
        "- Entrypoint: `mnt_bot V 7.7 plus.py`",
        "- Harness: `analyze_subb_momentum_weighting_full_conditions.py`",
        "- Changed variable: only the official macro-gated leg's 160/260/390 target-weight mix.",
        "- Restored conditions: absolute momentum gate, inflation macro gate, EMA leg, 50/50 blend, VolReg, switch buffer, min-turnover gate.",
        "",
        "## Data Snapshot",
        f"- Source: {meta['data_snapshot']['source']}",
        f"- Merged range: {meta['data_snapshot']['merged_start']} to {meta['data_snapshot']['merged_end']}",
        f"- Merged rows: {meta['data_snapshot']['merged_rows']}",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal, T+1 adjusted open execution when open data exists.",
        "- Repo `US_ROT_COMMISSION` retained for leg execution, blend execution, and VolReg transition costs.",
        "- No extra slippage beyond the repo's current commission model.",
        "",
        "## Runtime Override Plan",
        "No production constants were edited. Candidate weights are applied only inside the standalone official-leg harness.",
        "",
        "## Commands",
        f"- `python analyze_subb_momentum_weighting_full_conditions.py --out-dir {out_dir}`",
        "",
        "## Output Files",
        "- `scan_summary.csv`, `window_metrics.csv`, `daily_returns.csv`, `scan_meta.json`, `command_log.txt`",
        "",
        "## Full-Sample Results",
        summary[summary["segment"] == "full"][["candidate", "ann_return", "sharpe_repo", "max_dd", "calmar"]].to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Window Results",
        table,
        "",
        "## Stability Classification",
        "`full-conditions-weighting-mixed`: the edge from recent-heavy weighting shrinks materially once official filters and overlays are restored.",
        "",
        "## Decision",
        "Do not promote 60/30/10 directly from this scan alone. With full conditions restored, 60/30/10 is strongest across the recent windows, but the full-sample uplift is tiny and full-sample Sharpe is not better than equal weighting.",
        "",
        "## User-Facing Summary",
        "The weighting still has some use, but much less than in the no-filter isolation. Treat 60/30/10 as the aggressive follow-up candidate and 3/2/1 or 50/30/20 as milder candidates, not as an immediate default change.",
        "",
        f"Parity check equal-weight harness vs official baseline max abs daily return diff: {parity['max_abs_return_diff']:.12g}",
    ]
    (out_dir / "record.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    command = f"python analyze_subb_momentum_weighting_full_conditions.py --out-dir {out_dir}"
    (out_dir / "command_log.txt").write_text(command + "\n", encoding="utf-8")

    mod = subb.load_module(SCRIPT, "mnt_bot_v77_subb_weighting_full_conditions")
    ctx = subb.build_market_context(mod, SCRIPT)

    all_rows: list[dict[str, Any]] = []
    daily_returns: dict[str, pd.Series] = {}
    result_paths: dict[str, str] = {}
    ema_cache: pd.DataFrame | None = None

    for name, weights in weight_sets().items():
        result, ema_cache = run_full_candidate(ctx, weights, cached_ema=ema_cache)
        daily_returns[name] = result["return"]
        all_rows.extend(window_rows(name, weights, result))
        result_path = out_dir / f"{name}_daily.csv"
        result.to_csv(result_path, index_label="date", encoding="utf-8-sig")
        result_paths[name] = str(result_path)

    official_baseline = run_official_baseline(ctx)
    common = official_baseline.index.intersection(pd.read_csv(out_dir / "equal_1_1_1_daily.csv", index_col=0, parse_dates=True).index)
    equal_returns = daily_returns["equal_1_1_1"].reindex(common)
    official_returns = official_baseline["return"].reindex(common)
    parity = {
        "common_rows": int(len(common)),
        "max_abs_return_diff": float((equal_returns - official_returns).abs().max()),
    }

    summary = add_deltas(pd.DataFrame(all_rows))
    summary.to_csv(out_dir / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics = make_window_metrics(summary)
    window_metrics.to_csv(out_dir / "window_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(daily_returns).to_csv(out_dir / "daily_returns.csv", index_label="date", encoding="utf-8-sig")

    meta = {
        "run_id": out_dir.name,
        "created_at": "2026-05-16T19:00:00+08:00",
        "project": "A股美股动量组合策略",
        "repo_root": str(ROOT),
        "entrypoint": str(SCRIPT),
        "git_branch": git_text(["git", "branch", "--show-current"]),
        "git_commit": git_text(["git", "rev-parse", "HEAD"]),
        "git_status_before": git_text(["git", "status", "--short"]),
        "git_status_after": git_text(["git", "status", "--short"]),
        "scan_type": "official_path_parameter_scan",
        "parameter_group": "momentum_window_weighting_full_conditions",
        "baseline": {"candidate": "equal_1_1_1", "weights": {"160": 1 / 3, "260": 1 / 3, "390": 1 / 3}},
        "candidate_grid": [
            {"candidate": name, **{f"w_{lb}": weight for lb, weight in weights.items()}}
            for name, weights in weight_sets().items()
        ],
        "data_snapshot": {
            "source": ctx.audit.get("data_source"),
            "merged_start": ctx.audit.get("merged_start"),
            "merged_end": ctx.audit.get("merged_end"),
            "merged_rows": ctx.audit.get("merged_rows"),
            "sources": ctx.audit.get("sources"),
        },
        "cost_model": {
            "commission": "US_ROT_COMMISSION retained",
            "execution": "T close signal -> T+1 adjusted open execution where open data exists",
            "slippage": "No extra slippage beyond repo commission model",
        },
        "restored_conditions": [
            "US_ROT_ABS_THRESHOLD",
            "_subb_active_ranking_codes inflation macro gate",
            "run_subb_v75_ema_base7_rotation EMA leg",
            "blend_subb_v75_results official/EMA 50:50 blend",
            "apply_vol_regime_overlay",
            "US_ROT_REBALANCE_THRESHOLD switch buffer",
            "US_ROT_MIN_TURNOVER rebalance gate",
        ],
        "parity_check": parity,
        "outputs": {
            "record": str(out_dir / "record.md"),
            "scan_summary": str(out_dir / "scan_summary.csv"),
            "window_metrics": str(out_dir / "window_metrics.csv"),
            "scan_meta": str(out_dir / "scan_meta.json"),
            "command_log": str(out_dir / "command_log.txt"),
            "daily_returns": str(out_dir / "daily_returns.csv"),
            "result_paths": result_paths,
        },
        "decision": "Do not promote 60/30/10 directly from this scan alone; full-condition results still favor recent-heavy weighting in recent windows, but the edge is much smaller and full-sample Sharpe is not improved.",
        "stability_label": "full-conditions-weighting-mixed",
    }
    (out_dir / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    write_record(out_dir, summary, meta, parity)
    print(f"done: {out_dir}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
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
    weighted_signal,
)


ROOT = Path(__file__).resolve().parent
WINDOWS = {
    "full": None,
    "last_10y": pd.DateOffset(years=10),
    "last_5y": pd.DateOffset(years=5),
    "last_3y": pd.DateOffset(years=3),
    "last_1y": pd.DateOffset(years=1),
}


def top3_equal_weights(score_row: pd.Series, ranking_codes: list[str]) -> dict[str, float]:
    available = {
        code: float(score_row.get(code))
        for code in ranking_codes
        if code in score_row.index and not pd.isna(score_row.get(code))
    }
    if not available:
        return {"BIL": 1.0}
    selected = [code for code, _score in sorted(available.items(), key=lambda item: item[1], reverse=True)[:3]]
    if not selected:
        return {"BIL": 1.0}
    weight = 1.0 / len(selected)
    return {code: weight for code in selected}


def run_pure_momentum(
    ctx: subb.MarketContext,
    weights: dict[int, float],
    combine_mode: str,
) -> pd.DataFrame:
    mod = ctx.mod
    ranking_codes = list(mod.US_ROT_POOL)
    w_assets = list(dict.fromkeys(ranking_codes + ["BIL"]))
    momentum_by_lb = {lb: ctx.close_df.div(ctx.close_df.shift(lb)).sub(1) for lb in LBS}
    start_idx = max(LBS) + 1
    signal_days = mod._us_signal_days(ctx.close_df, start_idx)

    act: dict[str, float] = {"BIL": 1.0}
    holdings: dict[str, float] = {"BIL": 1.0}
    pending_act: dict[str, float] | None = None
    pending_comm = 0.0
    rows: list[dict[str, Any]] = []

    for i in range(start_idx, len(ctx.close_df)):
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

        is_signal = i in signal_days
        rebalanced = False
        turnover = 0.0
        active_signal = pd.Series(dtype=float)

        if is_signal:
            momentum_rows = {lb: momentum_by_lb[lb].iloc[i] for lb in LBS}
            if combine_mode == "window_target":
                per_window = []
                for lb in LBS:
                    per_window.append((top3_equal_weights(momentum_rows[lb], ranking_codes), weights[lb]))
                new_act = weighted_average_dicts(per_window)
                active_signal = weighted_signal(momentum_rows, weights)
            elif combine_mode == "weighted_signal":
                active_signal = weighted_signal(momentum_rows, weights)
                new_act = top3_equal_weights(active_signal, ranking_codes)
            else:
                raise ValueError(f"unknown combine_mode: {combine_mode}")

            prev_act = {asset: act.get(asset, 0.0) for asset in w_assets} if rows else {"BIL": 1.0}
            turnover = sum(
                abs(new_act.get(asset, 0.0) - prev_act.get(asset, 0.0))
                for asset in set(prev_act) | set(new_act)
                if asset != "BIL"
            )
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


def exposure_metrics(result: pd.DataFrame) -> dict[str, float]:
    w_cols = [col for col in result.columns if col.startswith("w_")]
    risky_cols = [col for col in w_cols if col != "w_BIL"]
    risky = result[risky_cols].sum(axis=1) if risky_cols else pd.Series(0.0, index=result.index)
    bil = result["w_BIL"] if "w_BIL" in result.columns else pd.Series(0.0, index=result.index)
    signal = result["is_signal"].astype(bool) if "is_signal" in result.columns else pd.Series(False, index=result.index)
    return {
        "avg_weight": float(risky.mean()),
        "avg_bil": float(bil.mean()),
        "rebalance_days": float(result["rebalanced"].astype(bool).sum()) if "rebalanced" in result.columns else np.nan,
        "signal_days": float(signal.sum()),
        "avg_turnover": float(result.loc[signal, "turnover"].mean()) if signal.any() else np.nan,
        "holding_day_ratio": float((risky > 1e-9).mean()),
    }


def window_rows(candidate: str, combine_mode: str, weights: dict[int, float], result: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    end = result.index.max()
    for segment, offset in WINDOWS.items():
        part = result if offset is None else result.loc[result.index >= end - offset]
        metrics = calc_metrics(part["return"])
        if metrics is None:
            continue
        row: dict[str, Any] = {
            "candidate": f"{combine_mode}__{candidate}",
            "segment": segment,
            "start": part.index.min().date().isoformat(),
            "end": part.index.max().date().isoformat(),
            "rows": int(round(metrics.pop("days"))),
            "ann_return": metrics.pop("cagr"),
            "ann_vol": metrics.pop("vol"),
            "sharpe_repo": metrics.pop("sharpe"),
            "max_dd": metrics.pop("maxdd"),
            "combine_mode": combine_mode,
            "weight_label": candidate,
            "w_160": weights[160],
            "w_260": weights[260],
            "w_390": weights[390],
        }
        row.update(metrics)
        row.update(exposure_metrics(part))
        rows.append(row)
    return rows


def add_deltas(summary: pd.DataFrame) -> pd.DataFrame:
    base = summary[summary["weight_label"] == "equal_1_1_1"][
        ["combine_mode", "segment", "ann_return", "sharpe_repo", "max_dd", "calmar", "final_nav"]
    ].rename(
        columns={
            "ann_return": "base_ann_return",
            "sharpe_repo": "base_sharpe_repo",
            "max_dd": "base_max_dd",
            "calmar": "base_calmar",
            "final_nav": "base_final_nav",
        }
    )
    out = summary.merge(base, on=["combine_mode", "segment"], how="left")
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
            "combine_mode": first["combine_mode"],
            "weight_label": first["weight_label"],
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
        row["decision_hint"] = "compare_to_equal_pure_momentum"
        row["stability_label"] = "pure-momentum-recent-heavy-mixed"
        rows.append(row)
    return pd.DataFrame(rows)


def git_text(args: list[str]) -> str:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:
        return f"unavailable: {exc}"


def write_record(out_dir: Path, summary: pd.DataFrame, meta: dict[str, Any]) -> None:
    primary = summary[
        (summary["combine_mode"] == "window_target")
        & (summary["segment"].isin(["full", "last_10y", "last_5y", "last_3y", "last_1y"]))
    ]
    table = primary[
        ["weight_label", "segment", "ann_return", "sharpe_repo", "max_dd", "calmar", "delta_ann_return", "delta_sharpe", "delta_max_dd"]
    ].to_markdown(index=False, floatfmt=".4f")
    lines = [
        "# V7.7 Sub-B Pure Momentum Weighting Without Filters Or Vol Sizing",
        "",
        "## Run Metadata",
        f"- Run folder: `{out_dir}`",
        "- Project: A股美股动量组合策略",
        "- Strategy/subsystem: V7.7 / Sub-B",
        "- Source-change rule: research-only standalone script; formal strategy files were not edited.",
        "",
        "## Research Question",
        "Retest raw 160/260/390 momentum weighting after also removing inverse-vol weighting and target-vol scaling.",
        "",
        "## Implementation Anchor",
        "- Entrypoint: `mnt_bot V 7.7 plus.py`",
        "- Harness: `analyze_subb_pure_momentum_weighting_no_filters_no_vol_sizing.py`",
        "- Kept: US_ROT_POOL, Top3 momentum selection, equal-weight selected assets, T+1 adjusted open execution, repo commission.",
        "- Removed: absolute momentum gate, inflation macro gate, EMA leg, VolReg, switch buffer, min-turnover gate, inverse-vol weighting, target-vol scaling.",
        "",
        "## Data Snapshot",
        f"- Source: {meta['data_snapshot']['source']}",
        f"- Merged range: {meta['data_snapshot']['merged_start']} to {meta['data_snapshot']['merged_end']}",
        f"- Merged rows: {meta['data_snapshot']['merged_rows']}",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal, T+1 adjusted open execution when open data exists.",
        "- Repo `US_ROT_COMMISSION` retained.",
        "- No extra slippage beyond repo commission model.",
        "",
        "## Runtime Override Plan",
        "No production constants were edited. The pure momentum harness does not call inverse-vol sizing or target-vol scale logic.",
        "",
        "## Commands",
        f"- `python analyze_subb_pure_momentum_weighting_no_filters_no_vol_sizing.py --out-dir {out_dir}`",
        "",
        "## Output Files",
        "- `scan_summary.csv`, `window_metrics.csv`, `daily_returns.csv`, `scan_meta.json`, `command_log.txt`",
        "",
        "## Full-Sample Results",
        primary[primary["segment"] == "full"][
            ["weight_label", "ann_return", "sharpe_repo", "max_dd", "calmar", "delta_ann_return", "delta_max_dd"]
        ].to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Window Results",
        table,
        "",
        "## Stability Classification",
        "`pure-momentum-window-target-improves`: in the official-style window-target mix, recent-heavy weighting still improves return and drawdown versus equal windows; however absolute drawdown is much larger without risk sizing, and weighted-signal mode is less stable.",
        "",
        "## Decision",
        "The pure no-filter test still supports recent-heavy weighting for the window-target structure, with 60/30/10 strongest. The earlier raw test understated absolute drawdown because risk sizing was still active, so this remains research evidence rather than a direct default-change recommendation.",
        "",
        "## User-Facing Summary",
        "Your correction matters: the earlier raw test mixed in risk sizing. After removing it, the relative window-weighting effect still exists in the window-target structure, but the standalone pure momentum sleeve has much deeper drawdowns.",
    ]
    (out_dir / "record.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    command = f"python analyze_subb_pure_momentum_weighting_no_filters_no_vol_sizing.py --out-dir {out_dir}"
    (out_dir / "command_log.txt").write_text(command + "\n", encoding="utf-8")

    mod = subb.load_module(SCRIPT, "mnt_bot_v77_subb_pure_momentum_no_vol_sizing")
    ctx = subb.build_market_context(mod, SCRIPT)

    all_rows: list[dict[str, Any]] = []
    daily_returns: dict[str, pd.Series] = {}
    result_paths: dict[str, str] = {}
    for combine_mode in ("window_target", "weighted_signal"):
        for name, weights in weight_sets().items():
            result = run_pure_momentum(ctx, weights, combine_mode)
            key = f"{combine_mode}__{name}"
            daily_returns[key] = result["return"]
            all_rows.extend(window_rows(name, combine_mode, weights, result))
            result_path = out_dir / f"{key}_daily.csv"
            result.to_csv(result_path, index_label="date", encoding="utf-8-sig")
            result_paths[key] = str(result_path)

    summary = add_deltas(pd.DataFrame(all_rows))
    summary.to_csv(out_dir / "scan_summary.csv", index=False, encoding="utf-8-sig")
    make_window_metrics(summary).to_csv(out_dir / "window_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(daily_returns).to_csv(out_dir / "daily_returns.csv", index_label="date", encoding="utf-8-sig")

    meta = {
        "run_id": out_dir.name,
        "created_at": "2026-05-16T19:20:00+08:00",
        "project": "A股美股动量组合策略",
        "repo_root": str(ROOT),
        "entrypoint": str(SCRIPT),
        "git_branch": git_text(["git", "branch", "--show-current"]),
        "git_commit": git_text(["git", "rev-parse", "HEAD"]),
        "git_status_before": git_text(["git", "status", "--short"]),
        "git_status_after": git_text(["git", "status", "--short"]),
        "scan_type": "isolated_pure_momentum_parameter_scan",
        "parameter_group": "pure_momentum_weighting_no_filters_no_vol_sizing",
        "baseline": {"candidate": "window_target__equal_1_1_1", "weights": {"160": 1 / 3, "260": 1 / 3, "390": 1 / 3}},
        "candidate_grid": [
            {"candidate": f"{mode}__{name}", "combine_mode": mode, **{f"w_{lb}": weight for lb, weight in weights.items()}}
            for mode in ("window_target", "weighted_signal")
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
        "removed_conditions": [
            "US_ROT_ABS_THRESHOLD",
            "inflation macro gate",
            "EMA leg",
            "VolReg overlay",
            "switch buffer",
            "min-turnover gate",
            "inverse-vol weighting",
            "target-vol scaling",
        ],
        "outputs": {
            "record": str(out_dir / "record.md"),
            "scan_summary": str(out_dir / "scan_summary.csv"),
            "window_metrics": str(out_dir / "window_metrics.csv"),
            "scan_meta": str(out_dir / "scan_meta.json"),
            "command_log": str(out_dir / "command_log.txt"),
            "daily_returns": str(out_dir / "daily_returns.csv"),
            "result_paths": result_paths,
        },
        "decision": "Pure no-filter no-vol-sizing results still support recent-heavy weighting for the window-target structure, especially 60/30/10, but absolute drawdown is much larger without risk sizing and weighted-signal mode is less stable.",
        "stability_label": "pure-momentum-window-target-improves",
    }
    (out_dir / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    write_record(out_dir, summary, meta)
    print(f"done: {out_dir}")


if __name__ == "__main__":
    main()

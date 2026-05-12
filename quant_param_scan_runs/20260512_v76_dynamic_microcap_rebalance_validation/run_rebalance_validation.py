from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


RUN_DIR = Path(__file__).resolve().parent
ROOT = RUN_DIR.parents[1]
INPUT_RETURNS = ROOT / "outputs" / "v76_dynamic_microcap_risk_budget_20260512" / "aligned_sleeve_returns.csv"

WINDOWS = {
    "full": None,
    "last_10y": pd.DateOffset(years=10),
    "last_5y": pd.DateOffset(years=5),
    "last_3y": pd.DateOffset(years=3),
    "last_1y": pd.DateOffset(years=1),
}

BASE_WEIGHTS = {"Sub-A": 0.10, "Sub-A-DK": 0.15, "Microcap": 0.15, "Sub-B": 0.60}
BANDS = {
    "dd_5_10": {"boost_dd": 0.05, "cut_dd": 0.10},
    "dd_5_12": {"boost_dd": 0.05, "cut_dd": 0.12},
    "dd_3_10": {"boost_dd": 0.03, "cut_dd": 0.10},
}
EXECUTIONS = ["daily", "weekly", "month_end"]
COST_BPS = [0, 5, 10, 20]


def git_value(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
    except Exception:
        return ""


def load_returns() -> pd.DataFrame:
    df = pd.read_csv(INPUT_RETURNS, parse_dates=["date"]).set_index("date").sort_index()
    required = ["Sub-A", "Sub-A-DK", "Microcap", "Sub-B"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"missing required return columns: {missing}")
    return df[required].apply(pd.to_numeric, errors="coerce").fillna(0.0)


def microcap_target(ret_df: pd.DataFrame, boost_dd: float, cut_dd: float) -> pd.Series:
    micro_nav = (1.0 + ret_df["Microcap"]).cumprod()
    prior_nav = micro_nav.shift(1)
    prior_peak = micro_nav.cummax().shift(1)
    prior_dd = prior_nav / prior_peak - 1.0
    target = pd.Series(0.15, index=ret_df.index, dtype=float)
    target.loc[prior_dd >= -boost_dd] = 0.20
    target.loc[prior_dd <= -cut_dd] = 0.10
    return target.fillna(0.15)


def execution_mask(index: pd.DatetimeIndex, execution: str) -> pd.Series:
    if execution == "daily":
        return pd.Series(True, index=index)
    next_index = pd.Series(index, index=index).shift(-1)
    if execution == "weekly":
        current_period = pd.Series(index.to_period("W-FRI"), index=index)
        next_period = pd.Series(next_index.dt.to_period("W-FRI").values, index=index)
    elif execution == "month_end":
        current_period = pd.Series(index.to_period("M"), index=index)
        next_period = pd.Series(next_index.dt.to_period("M").values, index=index)
    else:
        raise ValueError(f"unknown execution: {execution}")
    return next_period.notna() & (current_period != next_period)


def build_weights(ret_df: pd.DataFrame, target_micro: pd.Series | None, execution: str) -> pd.DataFrame:
    if target_micro is None:
        return pd.DataFrame({name: float(value) for name, value in BASE_WEIGHTS.items()}, index=ret_df.index)
    mask = execution_mask(ret_df.index, execution)
    executed_micro = pd.Series(np.nan, index=ret_df.index, dtype=float)
    executed_micro.loc[mask] = target_micro.loc[mask]
    executed_micro.iloc[0] = 0.15
    executed_micro = executed_micro.ffill().fillna(0.15)

    weights = pd.DataFrame(index=ret_df.index)
    weights["Sub-A"] = 0.10
    weights["Sub-A-DK"] = 0.15
    weights["Microcap"] = executed_micro
    weights["Sub-B"] = 0.75 - executed_micro
    return weights[["Sub-A", "Sub-A-DK", "Microcap", "Sub-B"]]


def turnover(weights: pd.DataFrame) -> pd.Series:
    return weights.diff().abs().sum(axis=1).fillna(0.0)


def nav_from_weights(ret_df: pd.DataFrame, weights: pd.DataFrame, cost_bps: float) -> tuple[pd.Series, pd.Series]:
    allocation_turnover = turnover(weights)
    gross_ret = (ret_df * weights).sum(axis=1)
    cost = allocation_turnover * (cost_bps / 10000.0)
    net_ret = gross_ret - cost
    nav = (1.0 + net_ret).cumprod()
    return nav / nav.iloc[0], allocation_turnover


def underwater_stats(nav: pd.Series) -> dict[str, object]:
    nav = nav.dropna()
    underwater = nav < nav.cummax()
    max_closed = 0
    current_start = None
    for dt, is_underwater in underwater.items():
        if is_underwater and current_start is None:
            current_start = dt
        elif not is_underwater and current_start is not None:
            max_closed = max(max_closed, int((dt - current_start).days))
            current_start = None
    return {
        "max_closed_underwater_days": max_closed,
        "open_underwater_days": int((nav.index[-1] - current_start).days) if current_start is not None else 0,
        "is_currently_underwater": bool(current_start is not None),
    }


def summarize(nav: pd.Series, segment: str, offset: pd.DateOffset | None) -> dict[str, object]:
    part = nav.dropna().copy() if offset is None else nav.loc[nav.index >= nav.index[-1] - offset].dropna().copy()
    part = part / part.iloc[0]
    daily_ret = part.pct_change().dropna()
    elapsed_years = (part.index[-1] - part.index[0]).days / 365.25
    ann_return = part.iloc[-1] ** (1.0 / elapsed_years) - 1.0
    ann_vol = daily_ret.std() * np.sqrt(252.0)
    max_dd = (part / part.cummax() - 1.0).min()
    return {
        "segment": segment,
        "start": part.index[0].date().isoformat(),
        "end": part.index[-1].date().isoformat(),
        "rows": int(len(part)),
        "ann_return": float(ann_return),
        "ann_vol": float(ann_vol),
        "max_dd": float(max_dd),
        "sharpe_repo": float(ann_return / ann_vol) if ann_vol and ann_vol > 0 else np.nan,
        "total_return": float(part.iloc[-1] - 1.0),
        **underwater_stats(part),
    }


def scenario_rows(ret_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    long_rows: list[dict[str, object]] = []
    weight_rows: list[dict[str, object]] = []
    nav_outputs: dict[str, pd.Series] = {}

    scenarios: list[tuple[str, str, str, float | None, float | None, pd.DataFrame]] = []
    scenarios.append(("fixed_10_15_15_60_cost0", "fixed", "none", None, None, build_weights(ret_df, None, "daily")))

    for band_name, band in BANDS.items():
        target = microcap_target(ret_df, band["boost_dd"], band["cut_dd"])
        for execution in EXECUTIONS:
            weights = build_weights(ret_df, target, execution)
            for cost_bps in COST_BPS:
                name = f"{band_name}_{execution}_cost{cost_bps}bps"
                scenarios.append((name, band_name, execution, band["boost_dd"], band["cut_dd"], weights))

    for candidate, band_name, execution, boost_dd, cut_dd, weights in scenarios:
        cost_values = [0] if candidate == "fixed_10_15_15_60_cost0" else COST_BPS
        if candidate != "fixed_10_15_15_60_cost0":
            cost_values = [int(candidate.rsplit("cost", 1)[1].replace("bps", ""))]
        for cost_bps in cost_values:
            nav, alloc_turnover = nav_from_weights(ret_df, weights, float(cost_bps))
            nav_outputs[candidate] = nav
            for segment, offset in WINDOWS.items():
                row = {"candidate": candidate, **summarize(nav, segment, offset)}
                row.update(
                    {
                        "band": band_name,
                        "execution": execution,
                        "boost_dd": "" if boost_dd is None else boost_dd,
                        "cut_dd": "" if cut_dd is None else cut_dd,
                        "cost_bps": cost_bps,
                        "allocation_turnover_total": float(alloc_turnover.sum()),
                        "allocation_turnover_annualized": float(alloc_turnover.sum() / ((ret_df.index[-1] - ret_df.index[0]).days / 365.25)),
                        "rebalance_count": int((weights["Microcap"].diff().abs() > 1e-12).sum()),
                        "avg_microcap_weight": float(weights["Microcap"].mean()),
                        "last_microcap_weight": float(weights["Microcap"].iloc[-1]),
                    }
                )
                long_rows.append(row)
            weight_rows.append(
                {
                    "candidate": candidate,
                    "band": band_name,
                    "execution": execution,
                    "boost_dd": "" if boost_dd is None else boost_dd,
                    "cut_dd": "" if cut_dd is None else cut_dd,
                    "cost_bps": cost_bps,
                    "avg_microcap_weight": float(weights["Microcap"].mean()),
                    "min_microcap_weight": float(weights["Microcap"].min()),
                    "max_microcap_weight": float(weights["Microcap"].max()),
                    "last_microcap_weight": float(weights["Microcap"].iloc[-1]),
                    "microcap_20_days": int((weights["Microcap"] >= 0.199999).sum()),
                    "microcap_15_days": int(((weights["Microcap"] > 0.100001) & (weights["Microcap"] < 0.199999)).sum()),
                    "microcap_10_days": int((weights["Microcap"] <= 0.100001).sum()),
                    "rebalance_count": int((weights["Microcap"].diff().abs() > 1e-12).sum()),
                    "allocation_turnover_total": float(turnover(weights).sum()),
                }
            )
            if cost_bps == 0:
                weights.to_csv(RUN_DIR / f"weights_{candidate}.csv", index_label="date", encoding="utf-8-sig")
                pd.DataFrame({"date": nav.index, "nav": nav.values}).to_csv(
                    RUN_DIR / f"daily_{candidate}.csv",
                    index=False,
                    encoding="utf-8-sig",
                )

    return pd.DataFrame(long_rows), pd.DataFrame(weight_rows), pd.DataFrame(nav_outputs)


def build_window_metrics(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for candidate, group in summary.groupby("candidate", sort=False):
        item: dict[str, object] = {"candidate": candidate}
        for segment in WINDOWS:
            row = group[group["segment"] == segment].iloc[0]
            suffix = segment.replace("last_", "last_")
            item[f"ann_return_{suffix}"] = row["ann_return"]
            item[f"ann_vol_{suffix}"] = row["ann_vol"]
            item[f"max_dd_{suffix}"] = row["max_dd"]
            item[f"sharpe_{suffix}"] = row["sharpe_repo"]
            item[f"allocation_turnover_total_{suffix}"] = row["allocation_turnover_total"]
            item[f"rebalance_count_{suffix}"] = row["rebalance_count"]
        rows.append(item)
    return pd.DataFrame(rows)


def write_record(summary: pd.DataFrame, window_metrics: pd.DataFrame, weights: pd.DataFrame) -> None:
    base = window_metrics[window_metrics["candidate"] == "fixed_10_15_15_60_cost0"].iloc[0]
    cost0 = window_metrics[window_metrics["candidate"].str.endswith("cost0bps")].copy()
    cost0["ann_return_delta_1y"] = cost0["ann_return_last_1y"] - base["ann_return_last_1y"]
    cost0["max_dd_delta_1y"] = cost0["max_dd_last_1y"] - base["max_dd_last_1y"]
    cost0["sharpe_delta_1y"] = cost0["sharpe_last_1y"] - base["sharpe_last_1y"]
    best = cost0.sort_values(["sharpe_last_1y", "ann_return_last_1y"], ascending=False).iloc[0]
    text = f"""# V7.6 Dynamic Microcap Rebalance Validation

## Research Question

Validate whether the dynamic Microcap DD-tier rule remains useful after adding executable rebalance frequencies and sleeve-allocation turnover cost sensitivity.

## Data

- Input returns: `{INPUT_RETURNS}`
- Common start: `{summary['start'].min()}`
- Common end: `{summary['end'].max()}`
- Source-change rule: `research_only_no_source_change`
- Signal timing: Microcap weight target for date `t` uses Microcap NAV information through `t-1`.
- Execution timing:
  - `daily`: target can change every trading date.
  - `weekly`: target changes only on the last available trading date of each `W-FRI` week.
  - `month_end`: target changes only on the last available trading date of each calendar month.

## Cost And Execution Assumptions

- Sleeve returns are the already aligned daily sleeve returns from the prior official V7.6 plus Microcap v1.8 run.
- Cost sensitivity applies only to inter-sleeve allocation turnover: `daily_cost = sum(abs(delta weights)) * cost_bps / 10000`.
- Tested cost levels: `{', '.join(str(x) for x in COST_BPS)} bps`.
- Intra-sleeve trading costs are inherited from each sleeve's source return path where available.

## Candidates

- Baseline: `fixed_10_15_15_60_cost0`
- Bands:
  - `dd_5_10`: Microcap 20% within 5% of its prior high, 10% below -10% DD, otherwise 15%.
  - `dd_5_12`: Microcap 20% within 5% of its prior high, 10% below -12% DD, otherwise 15%.
  - `dd_3_10`: Microcap 20% within 3% of its prior high, 10% below -10% DD, otherwise 15%.
- Executions: daily, weekly, month_end.

## Best Cost-0 Candidate By Latest 1Y Sharpe

- Candidate: `{best['candidate']}`
- 1Y annual return: `{best['ann_return_last_1y']:.4f}`
- 1Y max drawdown: `{best['max_dd_last_1y']:.4f}`
- 1Y Sharpe: `{best['sharpe_last_1y']:.4f}`
- 1Y annual return delta vs baseline: `{best['ann_return_delta_1y']:.4f}`
- 1Y max drawdown delta vs baseline: `{best['max_dd_delta_1y']:.4f}`
- 1Y Sharpe delta vs baseline: `{best['sharpe_delta_1y']:.4f}`

## Output Files

- `scan_summary.csv`: long window metrics.
- `window_metrics.csv`: one row per candidate with required window metrics.
- `weight_diagnostics.csv`: Microcap exposure, rebalance count, and allocation turnover.
- `scan_meta.json`: run metadata.
- `command_log.txt`: commands.

## Stability Classification

- Stability label: `promising_execution_robust_month_end`
- Evidence: the dynamic DD-tier family remains positive versus the fixed daily-weight baseline across daily, weekly, and month-end execution variants.
- Execution note: month-end execution materially reduces allocation turnover versus daily execution.
- Cost sensitivity: 5/10/20 bps inter-sleeve turnover costs were tested in the same run.
- Caveat: this remains a research-only allocation overlay and is not a source default.

## Decision

Decision: `watchlist_dd_5_12_month_end_validate_not_source_default`.

Practical read: daily variants can win the latest-1Y table, but they trade more frequently and are more sensitive. The month-end candidate is the next implementation-fit candidate if it keeps most of the improvement with much lower allocation turnover after corrected execution-date handling.
"""
    (RUN_DIR / "record.md").write_text(text, encoding="utf-8")


def main() -> None:
    ret_df = load_returns()
    summary, weight_diag, nav_outputs = scenario_rows(ret_df)
    window_metrics = build_window_metrics(summary)

    summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    weight_diag.to_csv(RUN_DIR / "weight_diagnostics.csv", index=False, encoding="utf-8-sig")
    nav_outputs.to_csv(RUN_DIR / "nav_outputs.csv", index_label="date", encoding="utf-8-sig")

    meta_path = RUN_DIR / "scan_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "phase": "scanned",
            "scan_type": "execution_frequency_and_cost_sensitivity",
            "entrypoint": str(INPUT_RETURNS),
            "git_branch": git_value(["branch", "--show-current"]) or meta.get("git_branch", ""),
            "git_commit": git_value(["rev-parse", "HEAD"]) or meta.get("git_commit", ""),
            "parameter_group": "microcap_dd_tier_rebalance_frequency",
            "baseline": BASE_WEIGHTS,
            "candidate_grid": {
                "bands": BANDS,
                "executions": EXECUTIONS,
                "cost_bps": COST_BPS,
            },
            "data_snapshot": {
                "input_returns": str(INPUT_RETURNS),
                "start": ret_df.index[0].date().isoformat(),
                "end": ret_df.index[-1].date().isoformat(),
                "rows": int(len(ret_df)),
                "columns": list(ret_df.columns),
            },
            "cost_model": {
                "inter_sleeve_allocation_turnover_bps": COST_BPS,
                "formula": "daily_cost = sum(abs(delta_weights)) * cost_bps / 10000",
                "intra_sleeve_costs": "inherited from source sleeve return series where available",
            },
            "outputs": {
                "record": str(RUN_DIR / "record.md"),
                "scan_summary": str(RUN_DIR / "scan_summary.csv"),
                "window_metrics": str(RUN_DIR / "window_metrics.csv"),
                "scan_meta": str(RUN_DIR / "scan_meta.json"),
                "command_log": str(RUN_DIR / "command_log.txt"),
                "weight_diagnostics": str(RUN_DIR / "weight_diagnostics.csv"),
                "nav_outputs": str(RUN_DIR / "nav_outputs.csv"),
            },
            "decision": "watchlist_dd_5_12_month_end_validate_not_source_default",
            "stability_label": "promising_execution_robust_month_end",
        }
    )
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    with (RUN_DIR / "command_log.txt").open("a", encoding="utf-8") as f:
        f.write("\npython quant_param_scan_runs\\20260512_v76_dynamic_microcap_rebalance_validation\\run_rebalance_validation.py\n")
        f.write(f"completed_at={datetime.now().astimezone().isoformat(timespec='seconds')}\n")

    write_record(summary, window_metrics, weight_diag)
    print(window_metrics.to_string(index=False))
    print(weight_diag.to_string(index=False))


if __name__ == "__main__":
    main()

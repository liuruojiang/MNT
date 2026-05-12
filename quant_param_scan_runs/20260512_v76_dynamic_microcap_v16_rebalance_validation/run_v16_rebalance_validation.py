from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


RUN_DIR = Path(__file__).resolve().parent
ROOT = RUN_DIR.parents[1]
BASE_ALIGNED = ROOT / "outputs" / "v76_dynamic_microcap_risk_budget_20260512" / "aligned_sleeve_returns.csv"
MICROCAP_V16 = (
    ROOT.parent
    / "微盘股对冲策略"
    / "outputs"
    / "microcap_top100_mom16_targetvol25_max1p5_v1_6_costed_nav.csv"
)

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
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def load_returns() -> pd.DataFrame:
    base = pd.read_csv(BASE_ALIGNED, parse_dates=["date"]).set_index("date").sort_index()
    v16 = pd.read_csv(MICROCAP_V16, parse_dates=["date"]).set_index("date").sort_index()
    micro = pd.to_numeric(v16["return_net"], errors="coerce").dropna().rename("Microcap")
    ret = base[["Sub-A", "Sub-A-DK", "Sub-B"]].join(micro, how="inner")
    ret = ret[["Sub-A", "Sub-A-DK", "Microcap", "Sub-B"]].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return ret


def microcap_target(ret_df: pd.DataFrame, boost_dd: float, cut_dd: float) -> pd.Series:
    micro_nav = (1.0 + ret_df["Microcap"]).cumprod()
    prior_dd = micro_nav.shift(1) / micro_nav.cummax().shift(1) - 1.0
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
    executed = pd.Series(np.nan, index=ret_df.index, dtype=float)
    executed.loc[mask] = target_micro.loc[mask]
    executed.iloc[0] = 0.15
    executed = executed.ffill().fillna(0.15)
    weights = pd.DataFrame(index=ret_df.index)
    weights["Sub-A"] = 0.10
    weights["Sub-A-DK"] = 0.15
    weights["Microcap"] = executed
    weights["Sub-B"] = 0.75 - executed
    return weights[["Sub-A", "Sub-A-DK", "Microcap", "Sub-B"]]


def turnover(weights: pd.DataFrame) -> pd.Series:
    return weights.diff().abs().sum(axis=1).fillna(0.0)


def nav_from_weights(ret_df: pd.DataFrame, weights: pd.DataFrame, cost_bps: float) -> tuple[pd.Series, pd.Series]:
    alloc_turnover = turnover(weights)
    net_ret = (ret_df * weights).sum(axis=1) - alloc_turnover * (cost_bps / 10000.0)
    nav = (1.0 + net_ret).cumprod()
    return nav / nav.iloc[0], alloc_turnover


def underwater_stats(nav: pd.Series) -> dict[str, object]:
    underwater = nav < nav.cummax()
    max_closed = 0
    current_start = None
    for dt, value in underwater.items():
        if value and current_start is None:
            current_start = dt
        elif not value and current_start is not None:
            max_closed = max(max_closed, int((dt - current_start).days))
            current_start = None
    return {
        "max_closed_underwater_days": max_closed,
        "open_underwater_days": int((nav.index[-1] - current_start).days) if current_start is not None else 0,
        "is_currently_underwater": bool(current_start is not None),
    }


def summarize(nav: pd.Series, segment: str, offset: pd.DateOffset | None) -> dict[str, object]:
    part = nav.copy() if offset is None else nav.loc[nav.index >= nav.index[-1] - offset].copy()
    part = part / part.iloc[0]
    daily_ret = part.pct_change().dropna()
    years = (part.index[-1] - part.index[0]).days / 365.25
    ann_return = part.iloc[-1] ** (1.0 / years) - 1.0
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


def build_outputs(ret_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    weight_rows: list[dict[str, object]] = []
    nav_outputs: dict[str, pd.Series] = {}
    scenarios: list[tuple[str, str, str, float | str, float | str, int, pd.DataFrame]] = [
        ("fixed_10_15_15_60_cost0", "fixed", "none", "", "", 0, build_weights(ret_df, None, "daily"))
    ]
    for band_name, band in BANDS.items():
        target = microcap_target(ret_df, band["boost_dd"], band["cut_dd"])
        for execution in EXECUTIONS:
            weights = build_weights(ret_df, target, execution)
            for cost_bps in COST_BPS:
                scenarios.append((f"{band_name}_{execution}_cost{cost_bps}bps", band_name, execution, band["boost_dd"], band["cut_dd"], cost_bps, weights))
    for candidate, band, execution, boost_dd, cut_dd, cost_bps, weights in scenarios:
        nav, alloc_turnover = nav_from_weights(ret_df, weights, float(cost_bps))
        nav_outputs[candidate] = nav
        for segment, offset in WINDOWS.items():
            rows.append(
                {
                    "candidate": candidate,
                    **summarize(nav, segment, offset),
                    "band": band,
                    "execution": execution,
                    "boost_dd": boost_dd,
                    "cut_dd": cut_dd,
                    "cost_bps": cost_bps,
                    "allocation_turnover_total": float(alloc_turnover.sum()),
                    "allocation_turnover_annualized": float(alloc_turnover.sum() / ((ret_df.index[-1] - ret_df.index[0]).days / 365.25)),
                    "rebalance_count": int((weights["Microcap"].diff().abs() > 1e-12).sum()),
                    "avg_microcap_weight": float(weights["Microcap"].mean()),
                    "last_microcap_weight": float(weights["Microcap"].iloc[-1]),
                }
            )
        weight_rows.append(
            {
                "candidate": candidate,
                "band": band,
                "execution": execution,
                "boost_dd": boost_dd,
                "cut_dd": cut_dd,
                "cost_bps": cost_bps,
                "avg_microcap_weight": float(weights["Microcap"].mean()),
                "last_microcap_weight": float(weights["Microcap"].iloc[-1]),
                "microcap_20_days": int((weights["Microcap"] >= 0.199999).sum()),
                "microcap_15_days": int(((weights["Microcap"] > 0.100001) & (weights["Microcap"] < 0.199999)).sum()),
                "microcap_10_days": int((weights["Microcap"] <= 0.100001).sum()),
                "rebalance_count": int((weights["Microcap"].diff().abs() > 1e-12).sum()),
                "allocation_turnover_total": float(alloc_turnover.sum()),
            }
        )
        if cost_bps == 0:
            weights.to_csv(RUN_DIR / f"weights_{candidate}.csv", index_label="date", encoding="utf-8-sig")
            pd.DataFrame({"date": nav.index, "nav": nav.values}).to_csv(RUN_DIR / f"daily_{candidate}.csv", index=False, encoding="utf-8-sig")
    return pd.DataFrame(rows), pd.DataFrame(weight_rows), pd.DataFrame(nav_outputs)


def window_metrics(summary: pd.DataFrame) -> pd.DataFrame:
    out = []
    for candidate, group in summary.groupby("candidate", sort=False):
        row: dict[str, object] = {"candidate": candidate}
        for segment in WINDOWS:
            s = group[group["segment"] == segment].iloc[0]
            row[f"ann_return_{segment}"] = s["ann_return"]
            row[f"ann_vol_{segment}"] = s["ann_vol"]
            row[f"max_dd_{segment}"] = s["max_dd"]
            row[f"sharpe_{segment}"] = s["sharpe_repo"]
            row[f"allocation_turnover_total_{segment}"] = s["allocation_turnover_total"]
            row[f"rebalance_count_{segment}"] = s["rebalance_count"]
        out.append(row)
    return pd.DataFrame(out)


def write_record(summary: pd.DataFrame, wm: pd.DataFrame) -> None:
    base = wm[wm["candidate"] == "fixed_10_15_15_60_cost0"].iloc[0]
    cost0 = wm[wm["candidate"].str.endswith("cost0bps")].copy()
    cost0["delta_1y_sharpe"] = cost0["sharpe_last_1y"] - base["sharpe_last_1y"]
    best = cost0.sort_values(["sharpe_last_1y", "ann_return_last_1y"], ascending=False).iloc[0]
    text = f"""# V7.6 Dynamic Microcap V1.6 Rebalance Validation

## Research Question

Correct the Microcap sleeve source from v1.8 to the current mainline v1.6 and retest DD-tier rebalance frequency and allocation-turnover cost sensitivity.

## Data

- Microcap source: `{MICROCAP_V16}`
- Microcap return column: `return_net`
- Non-Microcap sleeve source: `{BASE_ALIGNED}` columns `Sub-A`, `Sub-A-DK`, `Sub-B`
- Common start: `{summary['start'].min()}`
- Common end: `{summary['end'].max()}`
- Source-change rule: `research_only_no_source_change`
- Signal timing: Microcap weight target for date `t` uses Microcap NAV information through `t-1`.

## Cost And Execution Assumptions

- Inter-sleeve allocation turnover cost: `daily_cost = sum(abs(delta weights)) * cost_bps / 10000`.
- Tested cost levels: `{', '.join(str(x) for x in COST_BPS)} bps`.
- Intra-sleeve costs are inherited from the v1.6 `return_net` and the existing sleeve return sources.

## Candidates

- Baseline: `fixed_10_15_15_60_cost0`
- Bands: `dd_5_10`, `dd_5_12`, `dd_3_10`
- Executions: daily, weekly, month_end

## Best Cost-0 Candidate By Latest 1Y Sharpe

- Candidate: `{best['candidate']}`
- 1Y annual return: `{best['ann_return_last_1y']:.4f}`
- 1Y max drawdown: `{best['max_dd_last_1y']:.4f}`
- 1Y Sharpe: `{best['sharpe_last_1y']:.4f}`
- 1Y Sharpe delta vs baseline: `{best['delta_1y_sharpe']:.4f}`

## Stability Classification

- Stability label: `v1_6_corrected_watchlist`
- Evidence: corrected to current Microcap v1.6 costed return source.
- Caveat: this remains research-only and does not change production `COMBINED_WEIGHTS`.

## Output Files

- `scan_summary.csv`
- `window_metrics.csv`
- `weight_diagnostics.csv`
- `scan_meta.json`
- `command_log.txt`

## Decision

Decision: `corrected_to_v1_6_watchlist_not_source_default`.
"""
    (RUN_DIR / "record.md").write_text(text, encoding="utf-8")


def main() -> None:
    ret_df = load_returns()
    summary, weights, navs = build_outputs(ret_df)
    wm = window_metrics(summary)
    summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    wm.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    weights.to_csv(RUN_DIR / "weight_diagnostics.csv", index=False, encoding="utf-8-sig")
    navs.to_csv(RUN_DIR / "nav_outputs.csv", index_label="date", encoding="utf-8-sig")
    meta_path = RUN_DIR / "scan_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "phase": "scanned",
            "scan_type": "v1_6_execution_frequency_and_cost_sensitivity",
            "entrypoint": str(MICROCAP_V16),
            "git_branch": git_value(["branch", "--show-current"]) or meta.get("git_branch", ""),
            "git_commit": git_value(["rev-parse", "HEAD"]) or meta.get("git_commit", ""),
            "parameter_group": "microcap_v1_6_dd_tier_rebalance_frequency",
            "baseline": BASE_WEIGHTS,
            "candidate_grid": {"bands": BANDS, "executions": EXECUTIONS, "cost_bps": COST_BPS},
            "data_snapshot": {
                "microcap_source": str(MICROCAP_V16),
                "base_aligned_source": str(BASE_ALIGNED),
                "start": ret_df.index[0].date().isoformat(),
                "end": ret_df.index[-1].date().isoformat(),
                "rows": int(len(ret_df)),
            },
            "cost_model": {
                "inter_sleeve_allocation_turnover_bps": COST_BPS,
                "formula": "daily_cost = sum(abs(delta_weights)) * cost_bps / 10000",
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
            "decision": "corrected_to_v1_6_watchlist_not_source_default",
            "stability_label": "v1_6_corrected_watchlist",
        }
    )
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    with (RUN_DIR / "command_log.txt").open("a", encoding="utf-8") as f:
        f.write("\npython quant_param_scan_runs\\20260512_v76_dynamic_microcap_v16_rebalance_validation\\run_v16_rebalance_validation.py\n")
        f.write(f"completed_at={datetime.now().astimezone().isoformat(timespec='seconds')}\n")
    write_record(summary, wm)
    print(wm.to_string(index=False))
    print(weights.to_string(index=False))


if __name__ == "__main__":
    main()

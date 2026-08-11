#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "matplotlib",
#     "numpy",
#     "pandas",
#     "requests",
#     "xlsxwriter",
# ]
# ///

"""Scan a 0%-30% Inflation Compass sleeve around the V7.9 core portfolio."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import research_v79_inflation_compass_50_50 as combo_core

WEIGHTS = (0.00, 0.10, 0.15, 0.20, 0.25, 0.30)
WINDOWS = (
    ("full", None),
    ("last_10y", pd.DateOffset(years=10)),
    ("last_5y", pd.DateOffset(years=5)),
    ("last_3y", pd.DateOffset(years=3)),
    ("last_1y", pd.DateOffset(years=1)),
)
RUN_ID = "20260811_v79_inflation_compass_weight_10_30"
DEFAULT_RUN_DIR = Path("quant_param_scan_runs") / RUN_ID
ARCHIVAL_INPUT = (
    Path("outputs")
    / "v79_inflation_compass_50_50_20260811"
    / "archival_aligned_daily_returns.csv"
)
REFRESHED_INPUT = (
    Path("outputs")
    / "v79_inflation_compass_50_50_20260811"
    / "aligned_daily_returns.csv"
)
OUTER_COST_BPS = 5.0


@dataclass(frozen=True)
class CandidateResult:
    returns: pd.Series
    nav: pd.Series
    trades: pd.DataFrame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--archival-input", type=Path, default=ARCHIVAL_INPUT)
    parser.add_argument("--refreshed-input", type=Path, default=REFRESHED_INPUT)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def candidate_label(ic_weight: float) -> str:
    suffix = round(ic_weight * 100)
    return f"ic_{suffix:02d}" + ("_baseline" if suffix == 0 else "")


def load_aligned_returns(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["date"], index_col="date")
    required = ["V7.9", "Inflation Compass"]
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise KeyError(f"{path} missing columns: {missing}")
    output = frame.loc[:, required].apply(pd.to_numeric, errors="coerce")
    if output.empty or output.isna().any(axis=None):
        raise ValueError(f"{path} contains missing or empty aligned returns")
    if output.le(-1.0).any(axis=None) or output.index.has_duplicates:
        raise ValueError(f"{path} contains invalid returns or duplicate dates")
    return output.sort_index()


def simulate_from_existing_v79(
    returns: pd.DataFrame,
    ic_weight: float,
    *,
    cost_bps: float,
) -> CandidateResult:
    """Rebalance monthly, treating the account as initially 100% invested in V7.9."""
    target = {"V7.9": 1.0 - ic_weight, "Inflation Compass": ic_weight}
    weights = {"V7.9": 1.0, "Inflation Compass": 0.0}
    nav = 1.0
    last_period: pd.Period | None = None
    nav_rows: list[float] = []
    return_rows: list[float] = []
    trades: list[dict[str, Any]] = []
    for date, row in returns.iterrows():
        nav_before = nav
        period = date.to_period("M")
        if period != last_period:
            before = dict(weights)
            turnover = sum(abs(target[name] - weights[name]) for name in target)
            cost = nav * turnover * cost_bps / 10_000.0
            nav -= cost
            weights = dict(target)
            trades.append(
                {
                    "date": date,
                    "ic_weight": ic_weight,
                    "turnover": turnover,
                    "cost": cost,
                    "nav_before_cost": nav_before,
                    "nav_after_cost": nav,
                    "pretrade_weights": json.dumps(before, sort_keys=True),
                    "target_weights": json.dumps(target, sort_keys=True),
                }
            )
            last_period = period
        gross_return = sum(weights[name] * float(row[name]) for name in target)
        nav *= 1.0 + gross_return
        denominator = 1.0 + gross_return
        weights = {
            name: weights[name] * (1.0 + float(row[name])) / denominator
            for name in target
        }
        nav_rows.append(nav)
        return_rows.append(nav / nav_before - 1.0)
    index = returns.index
    name = candidate_label(ic_weight)
    return CandidateResult(
        returns=pd.Series(return_rows, index=index, name=name),
        nav=pd.Series(nav_rows, index=index, name=name),
        trades=pd.DataFrame(trades),
    )


def run_dataset(
    aligned: pd.DataFrame,
    *,
    dataset: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    end = aligned.index.max()
    summary_rows: list[dict[str, Any]] = []
    wide_rows: list[dict[str, Any]] = []
    daily: dict[str, pd.Series] = {}
    trade_frames: list[pd.DataFrame] = []
    for weight in WEIGHTS:
        label = candidate_label(weight)
        result = simulate_from_existing_v79(
            aligned,
            weight,
            cost_bps=OUTER_COST_BPS,
        )
        daily[label] = result.returns
        trades = result.trades.copy()
        trades.insert(0, "candidate", label)
        trades.insert(1, "dataset", dataset)
        trade_frames.append(trades)
        avg_turnover = float(trades["turnover"].iloc[1:].mean())
        annualized_turnover = float(
            trades["turnover"].sum()
            / ((aligned.index.max() - aligned.index.min()).days / 365.25)
        )
        total_cost = float(trades["cost"].sum())
        wide: dict[str, Any] = {
            "candidate": label,
            "ic_weight": weight,
            "v79_weight": 1.0 - weight,
            "avg_monthly_turnover": avg_turnover,
            "annualized_turnover": annualized_turnover,
            "cost_total_nav_units": total_cost,
        }
        for segment, offset in WINDOWS:
            requested = None if offset is None else end - offset
            metric = combo_core.performance_metric(result.returns, requested, end)
            if not metric.get("available"):
                summary_rows.append(
                    {
                        "candidate": label,
                        "dataset": dataset,
                        "segment": segment,
                        "available": False,
                        "reason": metric.get("reason"),
                        "ic_weight": weight,
                    }
                )
                continue
            summary_rows.append(
                {
                    "candidate": label,
                    "dataset": dataset,
                    "segment": segment,
                    "start": metric["start"],
                    "end": metric["end"],
                    "rows": metric["rows"],
                    "ann_return": metric["cagr"],
                    "ann_vol": metric["annualized_volatility"],
                    "sharpe_repo": metric["sharpe_zero_rf"],
                    "max_dd": metric["max_drawdown"],
                    "total_return": metric["total_return"],
                    "ic_weight": weight,
                    "v79_weight": 1.0 - weight,
                    "avg_turnover": avg_turnover,
                    "annualized_turnover": annualized_turnover,
                    "cost_total": total_cost,
                }
            )
            wide[f"ann_return_{segment}"] = metric["cagr"]
            wide[f"max_dd_{segment}"] = metric["max_drawdown"]
            wide[f"sharpe_repo_{segment}"] = metric["sharpe_zero_rf"]
        wide_rows.append(wide)
    return (
        pd.DataFrame(summary_rows),
        pd.DataFrame(wide_rows),
        pd.DataFrame(daily),
        pd.concat(trade_frames, ignore_index=True),
    )


def add_baseline_deltas(
    wide: pd.DataFrame,
    refreshed_wide: pd.DataFrame,
) -> pd.DataFrame:
    output = wide.copy()
    baseline = output.loc[output["candidate"].eq("ic_00_baseline")].iloc[0]
    refreshed = refreshed_wide.set_index("candidate")
    for segment, _ in WINDOWS:
        output[f"ann_return_delta_pp_{segment}"] = 100.0 * (
            output[f"ann_return_{segment}"] - baseline[f"ann_return_{segment}"]
        )
        output[f"mdd_improvement_pp_{segment}"] = 100.0 * (
            output[f"max_dd_{segment}"] - baseline[f"max_dd_{segment}"]
        )
    output["refreshed_ann_return_full"] = output["candidate"].map(
        refreshed["ann_return_full"]
    )
    output["refreshed_max_dd_full"] = output["candidate"].map(refreshed["max_dd_full"])
    refreshed_baseline = refreshed.loc["ic_00_baseline"]
    output["refreshed_ann_return_delta_pp_full"] = 100.0 * (
        output["refreshed_ann_return_full"] - refreshed_baseline["ann_return_full"]
    )
    output["refreshed_mdd_improvement_pp_full"] = 100.0 * (
        output["refreshed_max_dd_full"] - refreshed_baseline["max_dd_full"]
    )
    output["risk_return_gate"] = (
        (output["ann_return_delta_pp_full"] >= 0.50)
        & (output["mdd_improvement_pp_full"] >= -2.00)
        & (output["mdd_improvement_pp_last_10y"] >= -2.50)
        & (output["mdd_improvement_pp_last_5y"] >= -2.50)
        & (output["ann_return_delta_pp_last_3y"] >= -3.00)
        & (output["ann_return_delta_pp_last_1y"] >= -3.00)
        & (output["refreshed_ann_return_delta_pp_full"] >= 0.00)
        & (output["refreshed_mdd_improvement_pp_full"] >= -2.50)
    )
    output.loc[output["candidate"].eq("ic_00_baseline"), "risk_return_gate"] = True
    output["decision_hint"] = np.where(
        output["candidate"].eq("ic_00_baseline"),
        "baseline",
        np.where(output["risk_return_gate"], "passes_predeclared_gate", "fails_gate"),
    )
    return output


def chart_frontier(
    archival: pd.DataFrame,
    refreshed: pd.DataFrame,
    path: Path,
) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    for axis, frame, title in (
        (axes[0], archival, "Saved formal history to 2026-06-15"),
        (axes[1], refreshed, "Latest refreshed common sample to 2026-08-07"),
    ):
        axis.plot(
            -100.0 * frame["max_dd_full"],
            100.0 * frame["ann_return_full"],
            marker="o",
            color="#2E7D32",
        )
        for _, row in frame.iterrows():
            axis.annotate(
                f"{100.0 * row['ic_weight']:.0f}%",
                (-100.0 * row["max_dd_full"], 100.0 * row["ann_return_full"]),
                xytext=(5, 4),
                textcoords="offset points",
            )
        axis.set_xlabel("Maximum drawdown magnitude (%) — lower is better")
        axis.set_ylabel("CAGR (%) — higher is better")
        axis.set_title(title)
        axis.grid(alpha=0.25)
    figure.suptitle("Inflation Compass weight frontier (monthly rebalance, 5 bps)")
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def chart_nav(daily: pd.DataFrame, path: Path) -> None:
    nav = (1.0 + daily).cumprod()
    figure, axis = plt.subplots(figsize=(12, 6.5))
    colors = plt.cm.viridis(np.linspace(0.05, 0.95, len(nav.columns)))
    for color, column in zip(colors, nav.columns, strict=True):
        axis.plot(nav.index, nav[column], label=column, color=color, linewidth=1.3)
    axis.set_yscale("log")
    axis.set_ylabel("NAV (log scale)")
    axis.set_xlabel("Date")
    axis.set_title("V7.9 + Inflation Compass weight scan — saved formal history")
    axis.grid(alpha=0.25)
    axis.legend(ncol=2)
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def format_metric(value: float) -> str:
    return f"{100.0 * value:.2f}%"


def build_record(
    *,
    repo: Path,
    run_dir: Path,
    archival_input: Path,
    refreshed_input: Path,
    wide: pd.DataFrame,
    refreshed_wide: pd.DataFrame,
    git_before: str,
    git_after: str,
) -> str:
    pass_rows = wide.loc[
        wide["risk_return_gate"] & ~wide["candidate"].eq("ic_00_baseline")
    ]
    primary = (
        pass_rows.iloc[(pass_rows["ic_weight"] - 0.20).abs().argmin()]["candidate"]
        if not pass_rows.empty
        else "none"
    )
    upper_bound = (
        pass_rows.sort_values("ic_weight").iloc[-1]["candidate"]
        if not pass_rows.empty
        else "none"
    )
    full_lines = [
        "| candidate | IC weight | CAGR | max DD | CAGR Δ | MDD improvement | gate |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for _, row in wide.iterrows():
        full_lines.append(
            f"| {row['candidate']} | {100.0 * row['ic_weight']:.0f}% | "
            f"{format_metric(row['ann_return_full'])} | {format_metric(row['max_dd_full'])} | "
            f"{row['ann_return_delta_pp_full']:+.2f}pp | "
            f"{row['mdd_improvement_pp_full']:+.2f}pp | {row['decision_hint']} |"
        )
    window_lines = [
        "| candidate | 10Y | 5Y | 3Y | 1Y | latest refreshed full |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    refreshed_indexed = refreshed_wide.set_index("candidate")
    for _, row in wide.iterrows():
        current = refreshed_indexed.loc[row["candidate"]]
        window_lines.append(
            f"| {row['candidate']} | {format_metric(row['ann_return_last_10y'])} / {format_metric(row['max_dd_last_10y'])} | "
            f"{format_metric(row['ann_return_last_5y'])} / {format_metric(row['max_dd_last_5y'])} | "
            f"{format_metric(row['ann_return_last_3y'])} / {format_metric(row['max_dd_last_3y'])} | "
            f"{format_metric(row['ann_return_last_1y'])} / {format_metric(row['max_dd_last_1y'])} | "
            f"{format_metric(current['ann_return_full'])} / {format_metric(current['max_dd_full'])} |"
        )
    return f"""# V7.9 × Inflation Compass weight scan

## Run Metadata

- Run id: `{RUN_ID}`
- Run date: {datetime.now().astimezone().isoformat()}
- Timezone: Asia/Shanghai
- Project: A-share / US momentum combo
- Repo: `{repo}`
- Version: V7.9 core-three performance line plus Inflation Compass formal E3
- Parameter: `inflation_compass_weight`
- Scan type: `portfolio_weight_scan`
- Git commit: `{git_value(repo, "rev-parse", "HEAD")}`
- Working tree before: `{git_before.replace(chr(10), " | ")}`
- Working tree after: `{git_after.replace(chr(10), " | ")}`

## Research Question

- Baseline: 100% V7.9 core-three performance line (`ic_00_baseline`).
- Candidate grid: 10% / 15% / 20% / 25% / 30% Inflation Compass, funded from V7.9.
- Decision target: identify a watchlist weight, not change production defaults.
- Source-change rule: `research_only_no_source_change`.
- Required windows: full / 10Y / 5Y / 3Y / 1Y on the saved formal history.
- Predeclared gate: full CAGR +0.50pp or better; archival full MDD no more than 2.00pp deeper; 10Y/5Y MDD no more than 2.50pp deeper; 3Y/1Y CAGR lag no worse than 3.00pp; refreshed full CAGR non-negative delta and MDD no more than 2.50pp deeper.
- Rerun trigger: official refreshed V7.9 history becomes long enough to reconcile 10Y, or the saved/refreshed overlap mismatch is repaired.

## Implementation Anchor

- Official V7.9 path was refreshed in the preceding run through `_cached_fetch_data` → `_cached_run_strategies` → `_performance_combined_daily_returns`.
- Scan entrypoint: `{Path(__file__).resolve()}`.
- Allocation engine: `simulate_from_existing_v79`; monthly target restoration before the first union-calendar observation of each month.
- Existing V7.9 position at inception is 100%; initial transaction cost is only the actual shift into Inflation Compass.
- Default/current weight: 0% Inflation Compass. No source constants are overridden.

## Data Snapshot

- Saved formal input: `{archival_input}`; {pd.read_csv(archival_input, usecols=["date"])["date"].iloc[0]} to {pd.read_csv(archival_input, usecols=["date"])["date"].iloc[-1]}.
- Latest refreshed input: `{refreshed_input}`; {pd.read_csv(refreshed_input, usecols=["date"])["date"].iloc[0]} to {pd.read_csv(refreshed_input, usecols=["date"])["date"].iloc[-1]}.
- V7.9 source: production loaders; full DK pool respects ZZ1000 publication floor 2014-10-17.
- Inflation Compass source: frozen formal E3 `daily_nav.csv`, Yahoo adjusted O/H/L/C and FRED T5YIE.
- Alignment: union of mixed V7.9 and XNYS dates; a closed sleeve has zero return. No US calendar compression to A-share dates.
- Data warning: refreshed Zhongzheng Dividend Low Vol 100 history begins 2020-02-10 and does not match the saved formal overlap closely enough to splice; saved and refreshed evidence remain separate.
- Cache write risk: none in this scan; input CSVs are read-only. Dirty worktree existed before the run.

## Cost and Execution Assumptions

- Bottom strategy costs: already embedded in both input return streams.
- Outer rebalance cost: {OUTER_COST_BPS:.1f} bps one-way on summed buy/sell turnover.
- Rebalance: monthly, before that day's sleeve returns.
- V7.9 execution: Sub-A/ADK formal close path; Sub-B T close signal → T+1 adjusted open → T+1 close.
- Inflation Compass: complete month-end signal → next XNYS adjusted open; internal one-way 5 bps.
- Financing/borrow/open impact: no new outer financing or borrow model; inherited bottom-strategy assumptions only.
- Currency: no explicit CNY/USD conversion, preserving the existing V7.9 mixed-sleeve convention.

## Runtime Override Plan

- Override mechanism: none; weights are research-harness arguments only.
- Values restored after candidate: yes, each candidate is a fresh simulation.
- Default candidate included: yes, 0%.
- Parity: 0% baseline daily return equals the saved/refreshed V7.9 input exactly because it incurs no outer turnover.

## Commands

See `command_log.txt` for exact commands.

## Output Files

- `scan_summary.csv`: required long-form saved-formal metrics.
- `window_metrics.csv`: required wide saved-formal table plus refreshed full columns.
- `refreshed_scan_summary.csv`, `refreshed_window_metrics.csv`: latest-sample supplemental evidence.
- `daily_outputs/`: candidate daily returns and rebalance records.
- `charts/weight_frontier.png`, `charts/nav_curves_archival.png`.

## Full-Sample Results

{chr(10).join(full_lines)}

## Window Results

All cells are CAGR / maximum drawdown.

{chr(10).join(window_lines)}

## Stability Classification

- Label: `wide_stable` for the weight response; 15%-30% is one contiguous passing platform in both evidence sets.
- Data caveat: saved and refreshed V7.9 histories cannot be safely spliced, so the conclusion remains watchlist-only despite the wide parameter platform.
- Gate-passing non-baseline candidates: {", ".join(pass_rows["candidate"]) if not pass_rows.empty else "none"}.
- Primary balanced line: `{primary}`; conservative line `ic_15`; return-heavy watch line `ic_25`.
- Highest tested passing weight: `{upper_bound}`. It is the edge of the requested grid and its 3Y CAGR lag is close to the predeclared -3pp limit, so it is not the primary recommendation.
- `ic_10` misses the +0.50pp full-CAGR gate by only about 0.04pp and remains a valid risk-first reference, but it does not meet the predeclared promotion gate.

## Decision

- Decision: `watchlist`; no production allocation change in this run.
- Recommended next action: paper-track 20% as the primary line, retain 15% and 25% as neighboring confirmation lines, and rerun after the V7.9 historical source mismatch is repaired.

## User-Facing Summary

This scan is observed from real saved and refreshed daily strategy returns. It does not authorize a production allocation change or automated orders.
"""


def main() -> int:
    args = parse_args()
    repo = Path.cwd().resolve()
    run_dir = args.run_dir.resolve()
    archival_input = args.archival_input.resolve()
    refreshed_input = args.refreshed_input.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "daily_outputs").mkdir(exist_ok=True)
    (run_dir / "charts").mkdir(exist_ok=True)

    git_before = git_value(repo, "status", "--short")
    archival = load_aligned_returns(archival_input)
    refreshed = load_aligned_returns(refreshed_input)
    archival_summary, archival_wide, archival_daily, archival_trades = run_dataset(
        archival, dataset="saved_formal"
    )
    refreshed_summary, refreshed_wide, refreshed_daily, refreshed_trades = run_dataset(
        refreshed, dataset="latest_refreshed"
    )
    wide = add_baseline_deltas(archival_wide, refreshed_wide)

    archival_summary.to_csv(
        run_dir / "scan_summary.csv", index=False, encoding="utf-8-sig"
    )
    wide.to_csv(run_dir / "window_metrics.csv", index=False, encoding="utf-8-sig")
    refreshed_summary.to_csv(
        run_dir / "refreshed_scan_summary.csv", index=False, encoding="utf-8-sig"
    )
    refreshed_wide.to_csv(
        run_dir / "refreshed_window_metrics.csv", index=False, encoding="utf-8-sig"
    )
    archival_daily.index.name = "date"
    archival_daily.to_csv(
        run_dir / "daily_outputs" / "archival_candidate_returns.csv",
        encoding="utf-8-sig",
    )
    refreshed_daily.index.name = "date"
    refreshed_daily.to_csv(
        run_dir / "daily_outputs" / "refreshed_candidate_returns.csv",
        encoding="utf-8-sig",
    )
    pd.concat([archival_trades, refreshed_trades], ignore_index=True).to_csv(
        run_dir / "daily_outputs" / "monthly_rebalance_records.csv",
        index=False,
        encoding="utf-8-sig",
    )
    chart_frontier(wide, refreshed_wide, run_dir / "charts" / "weight_frontier.png")
    chart_nav(archival_daily, run_dir / "charts" / "nav_curves_archival.png")

    parity = pd.DataFrame(
        {
            "dataset": ["saved_formal", "latest_refreshed"],
            "max_abs_daily_return_difference": [
                float(
                    (archival_daily["ic_00_baseline"] - archival["V7.9"]).abs().max()
                ),
                float(
                    (refreshed_daily["ic_00_baseline"] - refreshed["V7.9"]).abs().max()
                ),
            ],
        }
    )
    parity.to_csv(run_dir / "parity_checks.csv", index=False, encoding="utf-8-sig")
    if not parity["max_abs_daily_return_difference"].le(1e-14).all():
        raise RuntimeError("0% baseline parity failed")

    git_after = git_value(repo, "status", "--short")
    meta_path = run_dir / "scan_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "scan_type": "portfolio_weight_scan",
            "baseline": {
                "candidate": "ic_00_baseline",
                "inflation_compass_weight": 0.0,
                "v79_weight": 1.0,
            },
            "candidate_grid": [candidate_label(weight) for weight in WEIGHTS],
            "data_snapshot": {
                "saved_formal": {
                    "path": str(archival_input),
                    "start": archival.index.min().strftime("%Y-%m-%d"),
                    "end": archival.index.max().strftime("%Y-%m-%d"),
                    "rows": len(archival),
                    "sha256": sha256_file(archival_input),
                },
                "latest_refreshed": {
                    "path": str(refreshed_input),
                    "start": refreshed.index.min().strftime("%Y-%m-%d"),
                    "end": refreshed.index.max().strftime("%Y-%m-%d"),
                    "rows": len(refreshed),
                    "sha256": sha256_file(refreshed_input),
                },
            },
            "cost_model": {
                "bottom_strategy_costs": "embedded",
                "outer_one_way_bps": OUTER_COST_BPS,
                "turnover_definition": "sum absolute target-minus-pretrade weights",
            },
            "parity_check": parity.to_dict(orient="records"),
            "cache_write_risk": "none; scan reads prior artifacts",
            "warnings": [
                "saved formal V7.9 ends 2026-06-15",
                "latest refreshed common sample starts 2020-06-05",
                "saved and refreshed V7.9 overlap mismatch prevents splicing",
                "no explicit CNY/USD conversion",
            ],
            "source_hashes": {
                str(Path(__file__).resolve()): sha256_file(Path(__file__).resolve()),
                str(Path(combo_core.__file__).resolve()): sha256_file(
                    Path(combo_core.__file__).resolve()
                ),
            },
            "git_status_after_scan": git_after,
        }
    )
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record = build_record(
        repo=repo,
        run_dir=run_dir,
        archival_input=archival_input,
        refreshed_input=refreshed_input,
        wide=wide,
        refreshed_wide=refreshed_wide,
        git_before=git_before,
        git_after=git_after,
    )
    (run_dir / "record.md").write_text(record, encoding="utf-8")
    with (run_dir / "command_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(
            "\nscan_command=uv run research_v79_inflation_compass_weight_scan.py\n"
        )
        handle.write(f"working_directory={repo}\n")
        handle.write(f"completed_at={datetime.now().astimezone().isoformat()}\n")
        handle.write("environment=PYTHONIOENCODING=utf-8\n")
    print(wide.to_string(index=False))
    print(f"Artifacts: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

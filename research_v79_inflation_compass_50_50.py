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

"""Combine the formal V7.9 core-three-sleeve line with Inflation Compass 50/50.

The script refreshes V7.9 through its production fetch/run path, reconciles the
refreshed overlap to the saved formal V7.9 artifact, and only extends that saved
history when the recent overlap matches.  Inflation Compass is read from its
frozen formal E3 daily NAV.  The outer allocation is restored to 50/50 monthly.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

WINDOWS: tuple[tuple[str, pd.DateOffset | None], ...] = (
    ("Full", None),
    ("10Y", pd.DateOffset(years=10)),
    ("5Y", pd.DateOffset(years=5)),
    ("3Y", pd.DateOffset(years=3)),
    ("1Y", pd.DateOffset(years=1)),
)
TARGET_WEIGHTS = {"V7.9": 0.50, "Inflation Compass": 0.50}
V79_COMPONENT_WEIGHTS = {
    "Sub-A": 0.15 / 0.70,
    "Sub-A-DK": 0.15 / 0.70,
    "Sub-B": 0.40 / 0.70,
}
FORMAL_DK_PUBLICATION_DATE = pd.Timestamp("2014-10-17")
SPLICE_TAIL_ROWS = 252
SPLICE_ABS_TOL = 1e-10


@dataclass(frozen=True)
class SimulationResult:
    daily_returns: pd.Series
    nav: pd.Series
    trades: pd.DataFrame


class ProgressMessage:
    """Minimal Poe-compatible progress sink used by the production runner."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, value: object) -> None:
        text = str(value)
        self.lines.append(text)
        print(text, end="", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--v79-script",
        type=Path,
        default=Path("mnt_bot V 7.9 plus.py"),
    )
    parser.add_argument(
        "--saved-formal",
        type=Path,
        default=Path("outputs/v78_v79_proxy_compare_20260810/formal_daily_returns.csv"),
    )
    parser.add_argument(
        "--inflation-root",
        type=Path,
        default=Path(
            r"C:\Users\Administrator.DESKTOP-95I7VVU\Documents\ChatGPT\通胀指南针"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/v79_inflation_compass_50_50_20260811"),
    )
    parser.add_argument("--outer-cost-bps", type=float, default=5.0)
    parser.add_argument(
        "--reuse-refreshed",
        action="store_true",
        help="Reuse v79_refreshed_daily_returns.csv in the output directory.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def load_module(path: Path) -> Any:
    resolved = path.resolve()
    spec = importlib.util.spec_from_file_location("v79_combo_research", resolved)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load V7.9 module: {resolved}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def clean_return_series(values: pd.Series, name: str) -> pd.Series:
    series = pd.to_numeric(values, errors="coerce").dropna().sort_index()
    series.index = pd.DatetimeIndex(series.index).tz_localize(None)
    if series.index.has_duplicates:
        raise ValueError(f"{name} return index contains duplicates")
    if series.empty or series.le(-1.0).any():
        raise ValueError(f"{name} returns are empty or contain loss <= -100%")
    return series.rename(name)


def refresh_v79(module: Any) -> tuple[dict[str, pd.Series], dict[str, Any], list[str]]:
    message = ProgressMessage()
    bot = module.CombinedStrategyV78()
    cn_close, dk_close, us_close, prod_daily = bot._cached_fetch_data(
        message,
        include_cn_live_snapshot=False,
        include_us_live_snapshot=False,
    )
    results = bot._cached_run_strategies(cn_close, dk_close, us_close, prod_daily)
    suba, adk, subb = results[0], results[1], results[2]
    component = {
        "Sub-A": clean_return_series(suba["return"], "Sub-A"),
        "Sub-A-DK": clean_return_series(adk["return"], "Sub-A-DK"),
        "Sub-B": clean_return_series(subb["return"], "Sub-B"),
    }
    combined = clean_return_series(
        module._performance_combined_daily_returns(component),
        "V7.9",
    )
    series = {**component, "V7.9": combined}
    frames = {
        "cn_input": cn_close,
        "dk_input": dk_close,
        "us_input": us_close,
        "prod_input": prod_daily,
    }
    ranges: dict[str, Any] = {}
    for name, frame in frames.items():
        ranges[name] = {
            "start": frame.index.min().strftime("%Y-%m-%d"),
            "end": frame.index.max().strftime("%Y-%m-%d"),
            "rows": len(frame),
        }
    for name, values in series.items():
        ranges[name] = {
            "start": values.index.min().strftime("%Y-%m-%d"),
            "end": values.index.max().strftime("%Y-%m-%d"),
            "rows": len(values),
        }
    return series, ranges, message.lines


def reconcile_and_splice(
    refreshed: pd.Series,
    saved_formal_path: Path,
) -> tuple[pd.Series, dict[str, Any], pd.DataFrame]:
    saved_frame = pd.read_csv(saved_formal_path, parse_dates=["date"], index_col="date")
    saved = clean_return_series(saved_frame["V7.9_Combined"], "V7.9 saved formal")
    overlap = saved.index.intersection(refreshed.index)
    if overlap.empty:
        raise RuntimeError("Saved and refreshed V7.9 series have no overlap")
    comparison = pd.DataFrame(
        {
            "saved_formal": saved.reindex(overlap),
            "refreshed": refreshed.reindex(overlap),
        }
    ).dropna()
    comparison["difference"] = comparison["refreshed"] - comparison["saved_formal"]
    tail = comparison.tail(min(SPLICE_TAIL_ROWS, len(comparison)))
    tail_max_abs = float(tail["difference"].abs().max())
    tail_rmse = float(np.sqrt(np.mean(np.square(tail["difference"]))))
    tail_corr = float(tail[["saved_formal", "refreshed"]].corr().iloc[0, 1])
    accepted = len(tail) >= 63 and tail_max_abs <= SPLICE_ABS_TOL
    saved_end = saved.index.max()
    if accepted:
        extension = refreshed.loc[refreshed.index > saved_end]
        formal = pd.concat([saved, extension]).sort_index()
        source = "saved formal history plus overlap-verified refreshed extension"
    else:
        formal = refreshed.copy()
        source = (
            "refreshed path only; saved history rejected because overlap did not match"
        )
    audit = {
        "accepted": bool(accepted),
        "source": source,
        "saved_start": saved.index.min().strftime("%Y-%m-%d"),
        "saved_end": saved_end.strftime("%Y-%m-%d"),
        "refreshed_start": refreshed.index.min().strftime("%Y-%m-%d"),
        "refreshed_end": refreshed.index.max().strftime("%Y-%m-%d"),
        "overlap_rows": len(comparison),
        "tail_rows_tested": len(tail),
        "tail_max_absolute_return_difference": tail_max_abs,
        "tail_rmse": tail_rmse,
        "tail_correlation": tail_corr,
        "acceptance_tolerance": SPLICE_ABS_TOL,
        "formal_start": formal.index.min().strftime("%Y-%m-%d"),
        "formal_end": formal.index.max().strftime("%Y-%m-%d"),
        "formal_rows": len(formal),
    }
    return clean_return_series(formal, "V7.9"), audit, comparison


def load_saved_v79(saved_formal_path: Path) -> pd.Series:
    frame = pd.read_csv(saved_formal_path, parse_dates=["date"], index_col="date")
    return clean_return_series(frame["V7.9_Combined"], "V7.9")


def load_refreshed_output(path: Path) -> dict[str, pd.Series]:
    frame = pd.read_csv(path, parse_dates=["date"], index_col="date")
    required = ("Sub-A", "Sub-A-DK", "Sub-B", "V7.9")
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise KeyError(f"Refreshed artifact is missing columns: {missing}")
    return {name: clean_return_series(frame[name], name) for name in required}


def load_inflation_compass(root: Path) -> tuple[pd.Series, dict[str, Any]]:
    nav_path = root / "outputs" / "formal_e3_backtest" / "daily_nav.csv"
    config_path = root / "outputs" / "formal_e3_backtest" / "config.json"
    nav = pd.read_csv(nav_path, parse_dates=["date"], index_col="date")
    returns = clean_return_series(nav["daily_return"], "Inflation Compass")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    metadata = {
        "nav_path": str(nav_path.resolve()),
        "config_path": str(config_path.resolve()),
        "start": returns.index.min().strftime("%Y-%m-%d"),
        "end": returns.index.max().strftime("%Y-%m-%d"),
        "rows": len(returns),
        "config": config,
    }
    return returns, metadata


def align_on_union_calendar(series: dict[str, pd.Series]) -> pd.DataFrame:
    common_start = max(values.index.min() for values in series.values())
    common_end = min(values.index.max() for values in series.values())
    if common_end <= common_start:
        raise RuntimeError("No usable common V7.9 / Inflation Compass interval")
    union = pd.DatetimeIndex(
        sorted(
            set().union(
                *(
                    set(values.loc[common_start:common_end].index)
                    for values in series.values()
                )
            )
        )
    )
    aligned = pd.DataFrame(
        {name: values.reindex(union).fillna(0.0) for name, values in series.items()}
    )
    if aligned.isna().any(axis=None):
        raise RuntimeError("Calendar alignment left missing returns")
    return aligned


def simulate_monthly_target(
    returns: pd.DataFrame,
    target_weights: dict[str, float],
    cost_bps: float,
) -> SimulationResult:
    if not np.isclose(sum(target_weights.values()), 1.0):
        raise ValueError("Target weights must sum to one")
    if cost_bps < 0.0:
        raise ValueError("Cost cannot be negative")
    values = returns.loc[:, list(target_weights)].copy().sort_index()
    nav = 1.0
    weights: dict[str, float] = {}
    last_period: pd.Period | None = None
    nav_rows: list[float] = []
    return_rows: list[float] = []
    trade_rows: list[dict[str, Any]] = []
    for date, row in values.iterrows():
        period = date.to_period("M")
        nav_before = nav
        if period != last_period:
            before = dict(weights)
            turnover = sum(
                abs(target_weights.get(name, 0.0) - weights.get(name, 0.0))
                for name in set(target_weights) | set(weights)
            )
            cost = nav * turnover * cost_bps / 10_000.0
            nav -= cost
            weights = dict(target_weights)
            trade_rows.append(
                {
                    "date": date,
                    "pretrade_weights": json.dumps(before, sort_keys=True),
                    "target_weights": json.dumps(target_weights, sort_keys=True),
                    "turnover": turnover,
                    "cost": cost,
                    "nav_before_cost": nav_before,
                    "nav_after_cost": nav,
                }
            )
            last_period = period
        gross_return = sum(weights[name] * float(row[name]) for name in target_weights)
        nav *= 1.0 + gross_return
        denominator = 1.0 + gross_return
        weights = {
            name: weights[name] * (1.0 + float(row[name])) / denominator
            for name in target_weights
        }
        nav_rows.append(nav)
        return_rows.append(nav / nav_before - 1.0)
    index = values.index
    return SimulationResult(
        daily_returns=pd.Series(return_rows, index=index, name="50/50 + 5bps"),
        nav=pd.Series(nav_rows, index=index, name="50/50 + 5bps"),
        trades=pd.DataFrame(trade_rows),
    )


def max_drawdown(nav: pd.Series) -> float:
    values = pd.to_numeric(nav, errors="coerce").dropna()
    peaks = values.cummax().clip(lower=1.0)
    return float((values / peaks - 1.0).min())


def performance_metric(
    returns: pd.Series,
    requested_start: pd.Timestamp | None,
    end: pd.Timestamp,
) -> dict[str, Any]:
    values = clean_return_series(returns.loc[:end], str(returns.name))
    if requested_start is not None:
        if values.index.min() > requested_start + pd.Timedelta(days=7):
            return {
                "available": False,
                "reason": (
                    f"series starts {values.index.min():%Y-%m-%d} after required "
                    f"{requested_start:%Y-%m-%d}"
                ),
            }
        values = values.loc[requested_start:]
    if len(values) < 20:
        return {"available": False, "reason": f"only {len(values)} daily rows"}
    years = (values.index.max() - values.index.min()).days / 365.25
    nav = (1.0 + values).cumprod()
    if years <= 0.0 or nav.iloc[-1] <= 0.0:
        return {"available": False, "reason": "non-positive span or NAV"}
    observations_per_year = len(values) / years
    volatility = float(values.std(ddof=1) * np.sqrt(observations_per_year))
    sharpe = (
        float(values.mean() / values.std(ddof=1) * np.sqrt(observations_per_year))
        if values.std(ddof=1) > 0.0
        else np.nan
    )
    return {
        "available": True,
        "reason": None,
        "start": values.index.min().strftime("%Y-%m-%d"),
        "end": values.index.max().strftime("%Y-%m-%d"),
        "rows": len(values),
        "cagr": float(nav.iloc[-1] ** (1.0 / years) - 1.0),
        "max_drawdown": max_drawdown(nav),
        "annualized_volatility": volatility,
        "sharpe_zero_rf": sharpe,
        "total_return": float(nav.iloc[-1] - 1.0),
    }


def metrics_by_window(returns: pd.DataFrame) -> pd.DataFrame:
    end = returns.index.max()
    rows: list[dict[str, Any]] = []
    for label, offset in WINDOWS:
        requested = None if offset is None else end - offset
        metrics = {
            name: performance_metric(returns[name], requested, end)
            for name in returns.columns
        }
        for name, metric in metrics.items():
            row = {"window": label, "strategy": name, **metric}
            combo = metrics.get("50/50 + 5bps", {})
            if (
                name != "50/50 + 5bps"
                and metric.get("available")
                and combo.get("available")
            ):
                row["combo_cagr_delta_pp"] = 100.0 * (combo["cagr"] - metric["cagr"])
                row["combo_mdd_improvement_pp"] = 100.0 * (
                    combo["max_drawdown"] - metric["max_drawdown"]
                )
            rows.append(row)
    return pd.DataFrame(rows)


def render_chart(returns: pd.DataFrame, path: Path) -> None:
    nav = (1.0 + returns).cumprod()
    drawdown = nav.div(nav.cummax().clip(lower=1.0)).sub(1.0)
    colors = {
        "V7.9": "#1976D2",
        "Inflation Compass": "#E65100",
        "50/50 + 5bps": "#2E7D32",
    }
    figure, (axis_nav, axis_dd) = plt.subplots(
        2,
        1,
        figsize=(12, 8),
        sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1.0]},
    )
    for column in returns.columns:
        axis_nav.plot(
            nav.index, nav[column], label=column, color=colors[column], linewidth=1.6
        )
        axis_dd.fill_between(
            drawdown.index,
            drawdown[column] * 100.0,
            0.0,
            color=colors[column],
            alpha=0.12,
        )
        axis_dd.plot(
            drawdown.index,
            drawdown[column] * 100.0,
            color=colors[column],
            linewidth=1.0,
        )
    axis_nav.set_yscale("log")
    axis_nav.set_ylabel("NAV (log scale)")
    axis_nav.grid(alpha=0.25)
    axis_nav.legend(loc="upper left")
    axis_nav.set_title("V7.9 + Inflation Compass: 50/50 monthly rebalance")
    axis_dd.set_ylabel("Drawdown (%)")
    axis_dd.grid(alpha=0.25)
    axis_dd.set_xlabel("Date")
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def markdown_window_table(metrics: pd.DataFrame) -> str:
    lines = [
        "| Window | V7.9 | Inflation Compass | 50/50（外层5bps） |",
        "|:-|--:|--:|--:|",
    ]
    for label, _ in WINDOWS:
        cells: list[str] = []
        for strategy in ("V7.9", "Inflation Compass", "50/50 + 5bps"):
            row = metrics.loc[
                metrics["window"].eq(label) & metrics["strategy"].eq(strategy)
            ].iloc[0]
            if not bool(row["available"]):
                cells.append(f"N/A（{row['reason']}）")
            else:
                cells.append(
                    f"{100.0 * float(row['cagr']):.2f}% / "
                    f"{100.0 * float(row['max_drawdown']):.2f}%"
                )
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    repo = Path.cwd().resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    v79_path = args.v79_script.resolve()
    saved_path = args.saved_formal.resolve()
    inflation_root = args.inflation_root.resolve()
    inflation_nav_path = (
        inflation_root / "outputs" / "formal_e3_backtest" / "daily_nav.csv"
    )

    refreshed_output_path = output_dir / "v79_refreshed_daily_returns.csv"
    previous_metadata_path = output_dir / "metadata.json"
    if args.reuse_refreshed:
        refreshed_series = load_refreshed_output(refreshed_output_path)
        refreshed_ranges = {
            name: {
                "start": values.index.min().strftime("%Y-%m-%d"),
                "end": values.index.max().strftime("%Y-%m-%d"),
                "rows": len(values),
            }
            for name, values in refreshed_series.items()
        }
        if previous_metadata_path.exists():
            previous_metadata = json.loads(
                previous_metadata_path.read_text(encoding="utf-8")
            )
            refreshed_ranges = previous_metadata.get("v79_definition", {}).get(
                "refreshed_ranges", refreshed_ranges
            )
        fetch_log_path = output_dir / "fetch_log.txt"
        fetch_log = (
            [fetch_log_path.read_text(encoding="utf-8")]
            if fetch_log_path.exists()
            else ["Reused prior refreshed return artifact.\n"]
        )
    else:
        module = load_module(v79_path)
        refreshed_series, refreshed_ranges, fetch_log = refresh_v79(module)
    v79, splice_audit, overlap = reconcile_and_splice(
        refreshed_series["V7.9"], saved_path
    )
    inflation, inflation_metadata = load_inflation_compass(inflation_root)
    if v79.index.min() < FORMAL_DK_PUBLICATION_DATE:
        raise RuntimeError("V7.9 formal series begins before ZZ1000 publication")

    aligned = align_on_union_calendar({"V7.9": v79, "Inflation Compass": inflation})
    gross = simulate_monthly_target(aligned, TARGET_WEIGHTS, cost_bps=0.0)
    net = simulate_monthly_target(
        aligned,
        TARGET_WEIGHTS,
        cost_bps=float(args.outer_cost_bps),
    )
    comparison_returns = aligned.copy()
    comparison_returns["50/50 + 5bps"] = net.daily_returns
    metrics = metrics_by_window(comparison_returns)

    saved_v79 = load_saved_v79(saved_path)
    archival_aligned = align_on_union_calendar(
        {"V7.9": saved_v79, "Inflation Compass": inflation}
    )
    archival_gross = simulate_monthly_target(
        archival_aligned, TARGET_WEIGHTS, cost_bps=0.0
    )
    archival_net = simulate_monthly_target(
        archival_aligned,
        TARGET_WEIGHTS,
        cost_bps=float(args.outer_cost_bps),
    )
    archival_returns = archival_aligned.copy()
    archival_returns["50/50 + 5bps"] = archival_net.daily_returns
    archival_metrics = metrics_by_window(archival_returns)

    refreshed_frame = pd.concat(refreshed_series, axis=1, sort=False).sort_index()
    refreshed_frame.index.name = "date"
    refreshed_frame.to_csv(
        output_dir / "v79_refreshed_daily_returns.csv", encoding="utf-8-sig"
    )
    overlap.index.name = "date"
    overlap.to_csv(output_dir / "v79_splice_overlap.csv", encoding="utf-8-sig")
    aligned_output = comparison_returns.copy()
    aligned_output["50/50 no outer cost"] = gross.daily_returns
    aligned_output.index.name = "date"
    aligned_output.to_csv(
        output_dir / "aligned_daily_returns.csv", encoding="utf-8-sig"
    )
    metrics.to_csv(output_dir / "window_metrics.csv", index=False, encoding="utf-8-sig")
    net.trades.to_csv(
        output_dir / "monthly_rebalance_trades.csv", index=False, encoding="utf-8-sig"
    )
    render_chart(comparison_returns, output_dir / "nav_drawdown.png")
    archival_output = archival_returns.copy()
    archival_output["50/50 no outer cost"] = archival_gross.daily_returns
    archival_output.index.name = "date"
    archival_output.to_csv(
        output_dir / "archival_aligned_daily_returns.csv", encoding="utf-8-sig"
    )
    archival_metrics.to_csv(
        output_dir / "archival_window_metrics.csv", index=False, encoding="utf-8-sig"
    )
    archival_net.trades.to_csv(
        output_dir / "archival_monthly_rebalance_trades.csv",
        index=False,
        encoding="utf-8-sig",
    )
    render_chart(archival_returns, output_dir / "archival_nav_drawdown.png")

    monthly = comparison_returns.groupby(comparison_returns.index.to_period("M")).apply(
        lambda frame: (1.0 + frame).prod() - 1.0
    )
    monthly.index = monthly.index.to_timestamp("M")
    correlations = {
        "daily_union_calendar": float(
            comparison_returns[["V7.9", "Inflation Compass"]].corr().iloc[0, 1]
        ),
        "monthly": float(monthly[["V7.9", "Inflation Compass"]].corr().iloc[0, 1]),
    }
    archival_monthly = archival_returns.groupby(
        archival_returns.index.to_period("M")
    ).apply(lambda frame: (1.0 + frame).prod() - 1.0)
    archival_correlations = {
        "daily_union_calendar": float(
            archival_returns[["V7.9", "Inflation Compass"]].corr().iloc[0, 1]
        ),
        "monthly": float(
            archival_monthly[["V7.9", "Inflation Compass"]].corr().iloc[0, 1]
        ),
    }
    gross_vs_net = float(gross.nav.iloc[-1] - net.nav.iloc[-1])
    total_outer_cost = float(net.trades["cost"].sum())

    fund_metadata_path = (
        inflation_root
        / "reports"
        / "artifacts"
        / "inflation_compass_20260809"
        / "fund_metadata.csv"
    )
    required_ic_symbols = [
        "SPY",
        "XLE",
        "XLI",
        "XLF",
        "XLB",
        "XLU",
        "XLV",
        "XLP",
        "XLK",
        "IEF",
    ]
    fund_metadata = pd.read_csv(fund_metadata_path)
    required_funds = fund_metadata.loc[
        fund_metadata["symbol"].isin(required_ic_symbols)
    ].copy()
    required_funds.to_csv(
        output_dir / "inflation_compass_required_fund_inceptions.csv",
        index=False,
        encoding="utf-8-sig",
    )

    git_head = git_value(repo, "rev-parse", "HEAD")
    git_status = git_value(repo, "status", "--short")
    metadata = {
        "created_at": datetime.now().astimezone().isoformat(),
        "observed_not_inferred": True,
        "v79_definition": {
            "line": "official performance-page core three sleeves; excludes Microcap and Sub-D",
            "weights": V79_COMPONENT_WEIGHTS,
            "working_tree_script": str(v79_path),
            "git_head": git_head,
            "git_status": git_status.splitlines(),
            "refreshed_ranges": refreshed_ranges,
            "splice_audit": splice_audit,
        },
        "inflation_compass": inflation_metadata,
        "outer_portfolio": {
            "weights": TARGET_WEIGHTS,
            "rebalance": "first union-calendar observation of each month, before that day's returns",
            "cost_bps_one_way": float(args.outer_cost_bps),
            "calendar": "union of V7.9 mixed-market dates and Inflation Compass XNYS dates; closed sleeve return=0",
            "start": comparison_returns.index.min().strftime("%Y-%m-%d"),
            "end": comparison_returns.index.max().strftime("%Y-%m-%d"),
            "rows": len(comparison_returns),
            "total_outer_cost_nav_units": total_outer_cost,
            "terminal_nav_drag_vs_zero_outer_cost": gross_vs_net,
        },
        "correlations": correlations,
        "archival_saved_formal_evidence": {
            "classification": "saved audited formal V7.9 history; stale after 2026-06-15 and not spliced to refresh",
            "start": archival_returns.index.min().strftime("%Y-%m-%d"),
            "end": archival_returns.index.max().strftime("%Y-%m-%d"),
            "rows": len(archival_returns),
            "correlations": archival_correlations,
            "total_outer_cost_nav_units": float(archival_net.trades["cost"].sum()),
            "terminal_nav_drag_vs_zero_outer_cost": float(
                archival_gross.nav.iloc[-1] - archival_net.nav.iloc[-1]
            ),
        },
        "source_hashes": {
            str(v79_path): sha256_file(v79_path),
            str(saved_path): sha256_file(saved_path),
            str(inflation_nav_path): sha256_file(inflation_nav_path),
            str(fund_metadata_path): sha256_file(fund_metadata_path),
        },
        "integrity": {
            "zz1000_publication_floor": FORMAL_DK_PUBLICATION_DATE.strftime("%Y-%m-%d"),
            "v79_starts_after_floor": bool(
                v79.index.min() >= FORMAL_DK_PUBLICATION_DATE
            ),
            "ic_required_latest_inception": str(
                required_funds["first_price_date"].max()
            ),
            "outer_common_start_after_all_ic_inceptions": bool(
                comparison_returns.index.min()
                >= pd.Timestamp(required_funds["first_price_date"].max())
            ),
            "lookahead": "V7.9 official execution path; IC complete month-end signal -> next XNYS adjusted open",
            "currency": "No explicit CNY/USD FX conversion; preserves V7.9 existing mixed-sleeve convention",
        },
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "fetch_log.txt").write_text("".join(fetch_log), encoding="utf-8")

    full = metrics.loc[metrics["window"].eq("Full")].set_index("strategy")
    combo = full.loc["50/50 + 5bps"]
    v79_full = full.loc["V7.9"]
    ic_full = full.loc["Inflation Compass"]
    archival_full = archival_metrics.loc[
        archival_metrics["window"].eq("Full")
    ].set_index("strategy")
    archival_combo = archival_full.loc["50/50 + 5bps"]
    report = f"""# V7.9 × 通胀指南针 50/50 组合研究

生成时间：{metadata["created_at"]}

## 结论

- **保存正式历史（2015-04-20 至 2026-06-15）**：50/50（月度恢复、外层单边 {args.outer_cost_bps:.1f} bps）CAGR **{100.0 * archival_combo["cagr"]:.2f}%**，最大回撤 **{100.0 * archival_combo["max_drawdown"]:.2f}%**。
- **最新刷新共同样本（{comparison_returns.index.min():%Y-%m-%d} 至 {comparison_returns.index.max():%Y-%m-%d}）**：50/50 CAGR **{100.0 * combo["cagr"]:.2f}%**，最大回撤 **{100.0 * combo["max_drawdown"]:.2f}%**。
- 最新样本相对 V7.9：CAGR {100.0 * (combo["cagr"] - v79_full["cagr"]):+.2f} 个百分点，最大回撤变化 {100.0 * (combo["max_drawdown"] - v79_full["max_drawdown"]):+.2f} 个百分点（负数表示更深）。
- 最新样本相对通胀指南针：CAGR {100.0 * (combo["cagr"] - ic_full["cagr"]):+.2f} 个百分点，最大回撤改善 {100.0 * (combo["max_drawdown"] - ic_full["max_drawdown"]):+.2f} 个百分点。
- 两策略相关性：保存正式历史日/月 **{archival_correlations["daily_union_calendar"]:.3f} / {archival_correlations["monthly"]:.3f}**；最新刷新日/月 **{correlations["daily_union_calendar"]:.3f} / {correlations["monthly"]:.3f}**。

## 保存正式历史标准窗口（CAGR / 最大回撤）

截至 2026-06-15；用于完整 10Y 审视，但不是最新行情刷新。

{markdown_window_table(archival_metrics)}

## 最新刷新标准窗口（CAGR / 最大回撤）

截至 2026-08-07；因远端中证红利低波100历史缩短，10Y 必须标 N/A。

{markdown_window_table(metrics)}

## 口径与数据

- V7.9：`mnt_bot V 7.9 plus.py` 的正式取数与 `_cached_run_strategies` 路径；绩效页核心三袖 Sub-A/Sub-A-DK/Sub-B 按 15/15/40 归一，不含未刷新的微盘与 Sub-D。
- V7.9 历史拼接：{splice_audit["source"]}；最近 {splice_audit["tail_rows_tested"]} 个重叠观测最大日收益差 `{splice_audit["tail_max_absolute_return_difference"]:.3e}`，所以保存历史与最新刷新严格分开显示。
- 通胀指南针：冻结 E3 正式 `daily_nav.csv`；完整月末信号，下一 XNYS 调整后开盘执行，内部单边 5 bps。
- 外层组合：每月并集日历首个观测日前恢复 50/50；外层单边 {args.outer_cost_bps:.1f} bps。两个底层策略自身收益已扣各自正式成本。
- 日历：V7.9 的中美交易日与通胀指南针 XNYS 日历取并集；某袖套闭市日收益记 0，不把美国数据压到 A 股日历。
- 调整：通胀指南针使用 Yahoo 复权价；Sub-B 使用调整后开盘/收盘，Sub-A/ADK 沿用 7.9 正式字段与成本口径。

## 最新刷新完整样本补充指标

| 指标 | V7.9 | 通胀指南针 | 50/50 |
|:-|--:|--:|--:|
| 年化波动率 | {100.0 * v79_full["annualized_volatility"]:.2f}% | {100.0 * ic_full["annualized_volatility"]:.2f}% | {100.0 * combo["annualized_volatility"]:.2f}% |
| Sharpe（0% RF） | {v79_full["sharpe_zero_rf"]:.2f} | {ic_full["sharpe_zero_rf"]:.2f} | {combo["sharpe_zero_rf"]:.2f} |
| 累计收益 | {100.0 * v79_full["total_return"]:.2f}% | {100.0 * ic_full["total_return"]:.2f}% | {100.0 * combo["total_return"]:.2f}% |

## 完整性与限制

- 完整 DK 池正式下限为 2014-10-17；组合实际从 {comparison_returns.index.min():%Y-%m-%d} 开始，未使用 ZZ1000 发布前回填。
- 通胀指南针所需 ETF 的最晚上市日为 {required_funds["first_price_date"].max()}（IEF），早于共同样本。
- 7.9 刷新时中证红利低波100远端接口只返回到 2020-02-10；仅在最近重叠路径通过逐日容差后，才用已审计保存产物补回更早历史。
- 保存正式历史截止 2026-06-15，不能代表其后的当前表现；最新刷新则无法安全补回 2020 年前历史。两条证据不做净值拼接。
- 通胀指南针真正发布后 OOS 仅自 2026-07-28；其历史强度仍可能包含规则发现期偏差。
- 未显式换算 CNY/USD，沿用 7.9 现有跨市场袖套组合习惯；这是账户级结果的主要未验证假设。
- 外层按月调仓是假设口径，不代表已获准自动交易；两套脚本均不自动下单。
"""
    (output_dir / "record.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Artifacts: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

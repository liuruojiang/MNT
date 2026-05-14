from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "portfolio_v76_current"
DEFAULT_DASHBOARD = DEFAULT_OUTPUT_DIR / "level8_decision_dashboard.csv"
DEFAULT_CURVE = DEFAULT_OUTPUT_DIR / "scenario_economic_curve.csv"
DEFAULT_SOURCE_RETURNS = (
    ROOT
    / "quant_param_scan_runs"
    / "20260512_v76_five_sleeve_real_subd_v20_rebalance_validation"
    / "aligned_five_sleeve_real_subd_returns.csv"
)

ACTIVE_SCENARIO = "advisory_suba_microcap_subd_dd_7_10_month_end"
FIXED_SCENARIO = "fixed_10_15_15_20_40"

MAX_EXCESS_DD_REVIEW = -0.05
MAX_EXCESS_DD_ROLLBACK = -0.10
MAX_ALLOCATION_TURNOVER_REVIEW = 25.0
MAX_REBALANCE_COUNT_REVIEW = 180


def _pct(value: float) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.2%}"


def _num(value: object, default: float = float("nan")) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _latest_date(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    try:
        dates = pd.read_csv(path, usecols=["date"], parse_dates=["date"])["date"]
    except Exception:
        return None
    dates = pd.to_datetime(dates, errors="coerce").dropna()
    if dates.empty:
        return None
    return pd.Timestamp(dates.max()).normalize()


def _status_priority(status: str) -> int:
    return {
        "ROLLBACK_FIXED": 0,
        "REVIEW": 1,
        "ACTIVE_OK": 2,
        "INFO": 3,
    }.get(status, 9)


def _rule(rule: str, status: str, value: str, threshold: str, note: str) -> dict[str, str]:
    return {
        "rule": rule,
        "status": status,
        "value": value,
        "threshold": threshold,
        "note": note,
    }


def _active_row(dashboard: pd.DataFrame) -> pd.Series | None:
    rows = dashboard[
        (dashboard["scenario"] == ACTIVE_SCENARIO)
        & (dashboard["candidate_status"] == "ACTIVE_DEFAULT")
    ]
    if rows.empty:
        return None
    return rows.iloc[0]


def _relative_nav_stats(curve: pd.DataFrame) -> dict[str, float]:
    if curve.empty or "fixed_nav" not in curve or "stacked_advisory_nav" not in curve:
        return {
            "latest_excess_nav": float("nan"),
            "peak_excess_nav": float("nan"),
            "current_excess_drawdown": float("nan"),
            "worst_excess_drawdown": float("nan"),
        }
    fixed = pd.to_numeric(curve["fixed_nav"], errors="coerce")
    active = pd.to_numeric(curve["stacked_advisory_nav"], errors="coerce")
    rel = active / fixed - 1.0
    rel = rel.replace([float("inf"), float("-inf")], pd.NA).dropna()
    if rel.empty:
        return {
            "latest_excess_nav": float("nan"),
            "peak_excess_nav": float("nan"),
            "current_excess_drawdown": float("nan"),
            "worst_excess_drawdown": float("nan"),
        }
    peak = rel.cummax()
    dd = rel - peak
    return {
        "latest_excess_nav": float(rel.iloc[-1]),
        "peak_excess_nav": float(peak.iloc[-1]),
        "current_excess_drawdown": float(dd.iloc[-1]),
        "worst_excess_drawdown": float(dd.min()),
    }


def build_governance(
    dashboard_path: Path,
    curve_path: Path,
    source_returns_path: Path,
) -> tuple[pd.DataFrame, dict[str, object]]:
    dashboard = pd.read_csv(dashboard_path)
    curve = pd.read_csv(curve_path, parse_dates=["date"]).sort_values("date")
    active = _active_row(dashboard)
    curve_latest = _latest_date(curve_path)
    source_latest = _latest_date(source_returns_path)
    nav_stats = _relative_nav_stats(curve)

    rows: list[dict[str, str]] = []

    if curve_latest is None:
        rows.append(
            _rule(
                "data_freshness",
                "ROLLBACK_FIXED",
                "missing",
                "curve latest >= source latest",
                "No scenario curve date is available.",
            )
        )
    elif source_latest is not None and curve_latest < source_latest:
        rows.append(
            _rule(
                "data_freshness",
                "ROLLBACK_FIXED",
                curve_latest.date().isoformat(),
                f">= {source_latest.date().isoformat()}",
                "Portfolio report is stale versus the aligned source returns.",
            )
        )
    else:
        rows.append(
            _rule(
                "data_freshness",
                "ACTIVE_OK",
                curve_latest.date().isoformat(),
                "fresh",
                "Scenario curve is current relative to the aligned source returns.",
            )
        )

    if active is None:
        rows.append(
            _rule(
                "active_row",
                "ROLLBACK_FIXED",
                "missing",
                ACTIVE_SCENARIO,
                "Dashboard does not mark the stacked scenario as ACTIVE_DEFAULT.",
            )
        )
    else:
        rows.append(
            _rule(
                "active_row",
                "ACTIVE_OK",
                str(active["scenario"]),
                ACTIVE_SCENARIO,
                "Dashboard marks the Sub-A + Microcap + Sub-D scenario as ACTIVE_DEFAULT; Sub-A-DK stays fixed because its internal DD RiskGate remains active.",
            )
        )

    if active is not None:
        since_2020_annual = _num(active.get("since_2020_annual_delta"))
        since_2020_dd = _num(active.get("since_2020_max_dd_delta"))
        since_2020_sharpe = _num(active.get("since_2020_sharpe_delta"))
        since_2020_ok = since_2020_annual > 0 and since_2020_dd >= 0 and since_2020_sharpe > 0
        rows.append(
            _rule(
                "since_2020_window_evidence",
                "ACTIVE_OK" if since_2020_ok else "ROLLBACK_FIXED",
                f"annual {_pct(since_2020_annual)}, maxDD {_pct(since_2020_dd)}, sharpe {since_2020_sharpe:.2f}",
                "all >= 0, annual/sharpe strictly > 0",
                "Since-2020 evidence must remain positive versus fixed.",
            )
        )

        one_y_annual = _num(active.get("last_1y_annual_delta"))
        one_y_dd = _num(active.get("last_1y_max_dd_delta"))
        one_y_sharpe = _num(active.get("last_1y_sharpe_delta"))
        one_y_ok = one_y_annual > 0 and one_y_dd >= 0 and one_y_sharpe > 0
        rows.append(
            _rule(
                "latest_1y_evidence",
                "ACTIVE_OK" if one_y_ok else "REVIEW",
                f"annual {_pct(one_y_annual)}, maxDD {_pct(one_y_dd)}, sharpe {one_y_sharpe:.2f}",
                "all >= 0, annual/sharpe strictly > 0",
                "Recent-window evidence should remain positive; failure starts review before hard rollback.",
            )
        )

        turnover = _num(active.get("allocation_turnover"))
        switches = _num(active.get("rebalance_count"))
        turnover_ok = turnover <= MAX_ALLOCATION_TURNOVER_REVIEW and switches <= MAX_REBALANCE_COUNT_REVIEW
        rows.append(
            _rule(
                "execution_load",
                "ACTIVE_OK" if turnover_ok else "REVIEW",
                f"switches {switches:.0f}, turnover {turnover:.1f}",
                f"switches <= {MAX_REBALANCE_COUNT_REVIEW}, turnover <= {MAX_ALLOCATION_TURNOVER_REVIEW:.1f}",
                "Execution load should stay near the accepted stacked-budget level.",
            )
        )

        weights = {
            "Sub-A": _num(active.get("latest_suba")),
            "Sub-A-DK": _num(active.get("latest_subadk")),
            "Microcap": _num(active.get("latest_microcap")),
            "Sub-D": _num(active.get("latest_subd")),
            "Sub-B": _num(active.get("latest_subb")),
        }
        total_weight = sum(weights.values())
        weight_ok = abs(total_weight - 1.0) < 1e-6 and all(0.0 <= value <= 1.0 for value in weights.values())
        rows.append(
            _rule(
                "weight_sanity",
                "ACTIVE_OK" if weight_ok else "ROLLBACK_FIXED",
                ", ".join(f"{name} {_pct(value)}" for name, value in weights.items()),
                "sum = 100%, each sleeve in [0%, 100%]",
                "Active budget must remain a valid five-sleeve allocation.",
            )
        )

    current_excess_dd = nav_stats["current_excess_drawdown"]
    worst_excess_dd = nav_stats["worst_excess_drawdown"]
    if pd.isna(current_excess_dd):
        rows.append(
            _rule(
                "relative_nav_drawdown",
                "REVIEW",
                "n/a",
                f"review <= {_pct(MAX_EXCESS_DD_REVIEW)}, rollback <= {_pct(MAX_EXCESS_DD_ROLLBACK)}",
                "Could not compute active-vs-fixed relative NAV drawdown.",
            )
        )
    elif current_excess_dd <= MAX_EXCESS_DD_ROLLBACK:
        rows.append(
            _rule(
                "relative_nav_drawdown",
                "ROLLBACK_FIXED",
                _pct(current_excess_dd),
                _pct(MAX_EXCESS_DD_ROLLBACK),
                "Active budget has given back too much relative NAV versus fixed.",
            )
        )
    elif current_excess_dd <= MAX_EXCESS_DD_REVIEW:
        rows.append(
            _rule(
                "relative_nav_drawdown",
                "REVIEW",
                _pct(current_excess_dd),
                _pct(MAX_EXCESS_DD_REVIEW),
                "Active budget is in relative drawdown; review before new promotion work.",
            )
        )
    else:
        rows.append(
            _rule(
                "relative_nav_drawdown",
                "ACTIVE_OK",
                f"current {_pct(current_excess_dd)}, worst {_pct(worst_excess_dd)}",
                f"> {_pct(MAX_EXCESS_DD_REVIEW)}",
                "Active budget has not breached the relative drawdown review threshold.",
            )
        )

    governance = pd.DataFrame(rows)
    worst_status = sorted(governance["status"].tolist(), key=_status_priority)[0]
    action = {
        "ROLLBACK_FIXED": "Use fixed 10/15/15/20/40 until the failed rule is repaired and rerun.",
        "REVIEW": "Keep active budget only with manual review; do not promote new Level-8 candidates.",
        "ACTIVE_OK": "Continue using stacked active dynamic budget.",
        "INFO": "No active decision.",
    }[worst_status]
    summary = {
        "decision_status": worst_status,
        "action": action,
        "curve_latest": curve_latest.date().isoformat() if curve_latest is not None else "",
        "source_latest": source_latest.date().isoformat() if source_latest is not None else "",
        **nav_stats,
    }
    return governance, summary


def render_markdown(governance: pd.DataFrame, summary: dict[str, object]) -> str:
    lines = [
        "# V7.6 Level-8 Risk Governance",
        "",
        "## Decision",
        "",
        f"- Status: **{summary['decision_status']}**",
        f"- Action: {summary['action']}",
        f"- Curve latest: `{summary.get('curve_latest', '')}`",
        f"- Source latest: `{summary.get('source_latest', '')}`",
        f"- Latest active excess NAV vs fixed: {_pct(float(summary['latest_excess_nav']))}",
        f"- Active relative NAV drawdown from its own peak: {_pct(float(summary['current_excess_drawdown']))}",
        "",
        "## Rules",
        "",
        "| Rule | Status | Value | Threshold | Note |",
        "|---|---|---:|---:|---|",
    ]
    for row in governance.to_dict("records"):
        lines.append(
            f"| {row['rule']} | {row['status']} | {row['value']} | {row['threshold']} | {row['note']} |"
        )
    lines.extend(
        [
            "",
            "## Read",
            "",
            "This is a governance layer, not a new optimizer. It decides whether the current stacked active budget can remain active, should move to manual review, or should roll back to fixed `10/15/15/20/40`.",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dashboard", default=str(DEFAULT_DASHBOARD))
    parser.add_argument("--curve", default=str(DEFAULT_CURVE))
    parser.add_argument("--source-returns", default=str(DEFAULT_SOURCE_RETURNS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    governance, summary = build_governance(
        Path(args.dashboard),
        Path(args.curve),
        Path(args.source_returns),
    )
    governance_path = out / "level8_risk_governance.csv"
    markdown_path = out / "level8_risk_governance.md"
    governance.to_csv(governance_path, index=False, encoding="utf-8-sig")
    markdown_path.write_text(render_markdown(governance, summary), encoding="utf-8")

    print(render_markdown(governance, summary))
    print(f"WROTE {governance_path}")
    print(f"WROTE {markdown_path}")


if __name__ == "__main__":
    main()

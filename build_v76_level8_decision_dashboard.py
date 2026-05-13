from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "portfolio_v76_current"
DEFAULT_METRICS = DEFAULT_OUTPUT_DIR / "scenario_window_metrics.csv"
DEFAULT_CURVE = DEFAULT_OUTPUT_DIR / "scenario_economic_curve.csv"
DEFAULT_MANIFEST = ROOT / "portfolio_manifests" / "v76_current.json"
DEFAULT_SOURCE_RETURNS = (
    ROOT
    / "quant_param_scan_runs"
    / "20260512_v76_five_sleeve_real_subd_v20_rebalance_validation"
    / "aligned_five_sleeve_real_subd_returns.csv"
)
DEFAULT_A_ADK_B_SUBD_SCAN = (
    ROOT
    / "quant_param_scan_runs"
    / "20260512_v76_level8_v7_6_five_sleeve_a_adk_b_subd_dynamic_budget_prior_nav_dd_threshold_execution_step"
    / "window_metrics.csv"
)

FIXED_SCENARIO = "fixed_10_15_15_20_40"
MICROCAP_ADVISORY_SCENARIO = "advisory_dd_3_10_month_end"
SUBA_ADVISORY_SCENARIO = "advisory_suba_dd_5_8_weekly"
STACKED_ADVISORY_SCENARIO = "advisory_suba_microcap_dd_3_10_month_end"
SCENARIO_ORDER = [
    FIXED_SCENARIO,
    MICROCAP_ADVISORY_SCENARIO,
    SUBA_ADVISORY_SCENARIO,
    STACKED_ADVISORY_SCENARIO,
]
WINDOW_WEIGHTS = {
    "full": 0.10,
    "last_10y": 0.15,
    "last_5y": 0.25,
    "last_3y": 0.30,
    "last_1y": 0.20,
}
EXTERNAL_SCAN_SLEEVES = ["Sub-A-DK", "Sub-B", "Sub-D"]
BASE_WEIGHTS = {
    "Sub-A": 0.10,
    "Sub-A-DK": 0.15,
    "Microcap": 0.15,
    "Sub-D": 0.20,
    "Sub-B": 0.40,
}
DYNAMIC_SLEEVES = {
    FIXED_SCENARIO: "none",
    MICROCAP_ADVISORY_SCENARIO: "Microcap",
    SUBA_ADVISORY_SCENARIO: "Sub-A",
    STACKED_ADVISORY_SCENARIO: "Sub-A,Microcap",
}
HISTORY_COLUMNS = [
    "observed_at",
    "latest_date",
    "decision_status",
    "data_freshness",
    "watch_scenario",
    "primary_action",
    "scenario",
    "latest_suba",
    "latest_subadk",
    "latest_microcap",
    "latest_subd",
    "latest_subb",
    "dynamic_sleeves",
    "full_annual_delta",
    "full_max_dd_delta",
    "full_sharpe_delta",
    "last_1y_annual_delta",
    "last_1y_max_dd_delta",
    "last_1y_sharpe_delta",
    "latest_excess_nav_vs_fixed",
    "candidate_status",
    "evidence_note",
]


def _latest_date_from_csv(path: str | Path) -> pd.Timestamp | None:
    candidate = Path(path)
    if not candidate.exists():
        return None
    try:
        dates = pd.read_csv(candidate, usecols=["date"], parse_dates=["date"])["date"]
    except Exception:
        return None
    dates = pd.to_datetime(dates, errors="coerce").dropna()
    if dates.empty:
        return None
    return pd.Timestamp(dates.max()).normalize()


def _read_metrics(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def _read_curve(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()


def _read_base_weights(path: str | Path) -> dict[str, float]:
    candidate = Path(path)
    if not candidate.exists():
        return dict(BASE_WEIGHTS)
    try:
        manifest = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return dict(BASE_WEIGHTS)
    weights = dict(BASE_WEIGHTS)
    for sleeve in manifest.get("sleeves", []):
        name = sleeve.get("name")
        if name:
            weights[name] = float(sleeve["weight"])
    return weights


def _metric_row(metrics: pd.DataFrame, scenario: str, segment: str) -> pd.Series | None:
    rows = metrics[(metrics["scenario"] == scenario) & (metrics["segment"] == segment)]
    if rows.empty:
        return None
    return rows.iloc[0]


def _float_value(row: pd.Series | None, name: str) -> float:
    if row is None or name not in row or pd.isna(row[name]):
        return np.nan
    return float(row[name])


def _latest_or_base(row: pd.Series | None, name: str, base_weights: dict[str, float], sleeve: str) -> float:
    latest = _float_value(row, name)
    if pd.isna(latest):
        return base_weights[sleeve]
    return latest


def _pct(value: float) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.2%}"


def _weight(value: float) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.0%}"


def _weight_delta(value: float, base: float) -> str:
    if pd.isna(value) or pd.isna(base):
        return "n/a"
    delta_pp = int(round((float(value) - float(base)) * 100))
    if delta_pp > 0:
        return f"+{delta_pp}pp"
    if delta_pp < 0:
        return f"{delta_pp}pp"
    return "0pp"


def _scenario_label(scenario: str) -> str:
    return {
        FIXED_SCENARIO: "Fixed default",
        MICROCAP_ADVISORY_SCENARIO: "Microcap advisory",
        SUBA_ADVISORY_SCENARIO: "Sub-A 5/8 weekly advisory",
        STACKED_ADVISORY_SCENARIO: "Stacked Sub-A 5/8 weekly + Microcap 3/10 month-end",
    }.get(scenario, scenario)


def _freshness_state(curve: pd.DataFrame, source_latest_date: pd.Timestamp | None) -> tuple[str, str]:
    latest = pd.Timestamp(curve.index[-1]).normalize() if len(curve.index) else None
    if latest is None:
        return "missing", "scenario curve is empty"
    if source_latest_date is not None and latest < pd.Timestamp(source_latest_date).normalize():
        return (
            "stale",
            f"scenario curve latest {latest.date().isoformat()} < source latest {source_latest_date.date().isoformat()}",
        )
    return "fresh", f"scenario curve latest {latest.date().isoformat()}"


def _scenario_excess_nav(scenario: str, curve: pd.DataFrame) -> float:
    columns = {
        MICROCAP_ADVISORY_SCENARIO: "advisory_excess_nav",
        SUBA_ADVISORY_SCENARIO: "suba_advisory_excess_nav",
        STACKED_ADVISORY_SCENARIO: "stacked_advisory_excess_nav",
    }
    column = columns.get(scenario)
    if column and column in curve.columns and not curve.empty:
        return float(curve[column].iloc[-1])
    return np.nan


def _all_window_deltas_positive(row: dict[str, object]) -> bool:
    annual_keys = [
        "full_annual_delta",
        "last_10y_annual_delta",
        "last_5y_annual_delta",
        "last_3y_annual_delta",
        "last_1y_annual_delta",
    ]
    sharpe_keys = [
        "full_sharpe_delta",
        "last_10y_sharpe_delta",
        "last_5y_sharpe_delta",
        "last_3y_sharpe_delta",
        "last_1y_sharpe_delta",
    ]
    return all(float(row.get(key, np.nan)) > 0 for key in annual_keys + sharpe_keys)


def _classify_candidate(row: dict[str, object]) -> tuple[str, str]:
    scenario = str(row.get("scenario", ""))
    if scenario == FIXED_SCENARIO:
        return "BASELINE", "Executable default benchmark."
    if scenario == STACKED_ADVISORY_SCENARIO:
        full_return_ok = float(row.get("full_annual_delta", np.nan)) > 0
        full_sharpe_ok = float(row.get("full_sharpe_delta", np.nan)) > 0
        full_dd_ok = float(row.get("full_max_dd_delta", np.nan)) >= 0
        one_y_return_ok = float(row.get("last_1y_annual_delta", np.nan)) > 0
        one_y_sharpe_ok = float(row.get("last_1y_sharpe_delta", np.nan)) > 0
        one_y_dd_ok = float(row.get("last_1y_max_dd_delta", np.nan)) >= 0
        if (
            full_return_ok
            and full_sharpe_ok
            and full_dd_ok
            and one_y_return_ok
            and one_y_sharpe_ok
            and one_y_dd_ok
        ):
            return (
                "ACTIVE_DEFAULT",
                "Active stacked portfolio-level dynamic budget; fixed weights remain the benchmark and rollback line.",
            )
        return (
            "REPORT_WATCH_ONLY",
            "Stacked rule is adopted only when return, Sharpe, and drawdown all improve versus fixed.",
        )
    if scenario == SUBA_ADVISORY_SCENARIO and _all_window_deltas_positive(row):
        full_dd_ok = float(row.get("full_max_dd_delta", np.nan)) >= 0
        one_y_dd_ok = float(row.get("last_1y_max_dd_delta", np.nan)) >= 0
        turnover_ok = float(row.get("allocation_turnover", np.nan)) <= 10.0
        if full_dd_ok and one_y_dd_ok and turnover_ok:
            return "REPORT_WATCH_ONLY", "Former active component; superseded by the adopted stacked dynamic budget."
    if str(row.get("dynamic_sleeves")) == "Sub-B":
        return "DEFER", "Sub-B dynamic budget is weak under the proportional absorber design."
    if str(row.get("dynamic_sleeves")) == "Sub-D" and float(row.get("last_1y_annual_delta", np.nan)) > 0:
        return "REPORT_WATCH_ONLY", "Strong recent-window evidence, but full-sample Sharpe is not robust enough for default promotion."
    if float(row.get("full_annual_delta", np.nan)) <= 0 or float(row.get("full_sharpe_delta", np.nan)) <= 0:
        return "DEFER", "No robust full-sample improvement versus fixed default."
    if float(row.get("full_max_dd_delta", np.nan)) < 0:
        return "REPORT_WATCH_ONLY", "Positive return evidence but max drawdown worsens versus fixed default."
    return "REPORT_WATCH_ONLY", "Positive evidence, but not broad enough to become the first executable default candidate."


def _build_base_scenario_rows(
    metrics: pd.DataFrame,
    curve: pd.DataFrame,
    latest_date: str,
    fixed_full: pd.Series | None,
    fixed_1y: pd.Series | None,
    base_weights: dict[str, float],
) -> list[dict[str, object]]:
    rows = []
    for scenario in [name for name in SCENARIO_ORDER if name in set(metrics["scenario"])]:
        full = _metric_row(metrics, scenario, "full")
        one_y = _metric_row(metrics, scenario, "last_1y")
        row = {
            "scenario": scenario,
            "label": _scenario_label(scenario),
            "latest_date": latest_date,
            "latest_suba": _latest_or_base(full, "latest_suba", base_weights, "Sub-A"),
            "latest_subadk": _latest_or_base(full, "latest_subadk", base_weights, "Sub-A-DK"),
            "latest_microcap": _latest_or_base(full, "latest_microcap", base_weights, "Microcap"),
            "latest_subd": _latest_or_base(full, "latest_subd", base_weights, "Sub-D"),
            "latest_subb": _latest_or_base(full, "latest_subb", base_weights, "Sub-B"),
            "dynamic_sleeves": DYNAMIC_SLEEVES.get(scenario, ""),
            "rebalance_count": _float_value(full, "rebalance_count"),
            "allocation_turnover": _float_value(full, "allocation_turnover"),
            "full_annual_return": _float_value(full, "annual_return"),
            "full_max_dd": _float_value(full, "max_dd"),
            "full_sharpe": _float_value(full, "sharpe"),
            "last_1y_annual_return": _float_value(one_y, "annual_return"),
            "last_1y_max_dd": _float_value(one_y, "max_dd"),
            "last_1y_sharpe": _float_value(one_y, "sharpe"),
        }
        for segment in ["last_10y", "last_5y", "last_3y"]:
            segment_row = _metric_row(metrics, scenario, segment)
            fixed_segment = _metric_row(metrics, FIXED_SCENARIO, segment)
            row[f"{segment}_annual_delta"] = _float_value(segment_row, "annual_return") - _float_value(
                fixed_segment, "annual_return"
            )
            row[f"{segment}_max_dd_delta"] = _float_value(segment_row, "max_dd") - _float_value(
                fixed_segment, "max_dd"
            )
            row[f"{segment}_sharpe_delta"] = _float_value(segment_row, "sharpe") - _float_value(
                fixed_segment, "sharpe"
            )
        row["full_annual_delta"] = row["full_annual_return"] - _float_value(fixed_full, "annual_return")
        row["full_max_dd_delta"] = row["full_max_dd"] - _float_value(fixed_full, "max_dd")
        row["full_sharpe_delta"] = row["full_sharpe"] - _float_value(fixed_full, "sharpe")
        row["last_1y_annual_delta"] = row["last_1y_annual_return"] - _float_value(fixed_1y, "annual_return")
        row["last_1y_max_dd_delta"] = row["last_1y_max_dd"] - _float_value(fixed_1y, "max_dd")
        row["last_1y_sharpe_delta"] = row["last_1y_sharpe"] - _float_value(fixed_1y, "sharpe")
        row["latest_excess_nav_vs_fixed"] = _scenario_excess_nav(scenario, curve)
        row["candidate_status"], row["evidence_note"] = _classify_candidate(row)
        rows.append(row)
    return rows


def _score_external_candidate(row: pd.Series, fixed: pd.Series) -> float:
    score = 0.0
    for segment, weight in WINDOW_WEIGHTS.items():
        ann_delta = float(row[f"ann_return_{segment}"] - fixed[f"ann_return_{segment}"])
        sharpe_delta = float(row[f"sharpe_repo_{segment}"] - fixed[f"sharpe_repo_{segment}"])
        maxdd_delta = float(row[f"max_dd_{segment}"] - fixed[f"max_dd_{segment}"])
        score += weight * (ann_delta * 4.0 + sharpe_delta * 0.3 + maxdd_delta * 2.0)
    return score


def _external_candidate_weights(
    dynamic_sleeve: str,
    latest_dynamic_weight: float,
    base_weights: dict[str, float],
) -> dict[str, float]:
    weights = dict(base_weights)
    if pd.isna(latest_dynamic_weight):
        return weights
    if dynamic_sleeve == "Sub-B":
        base_subb = base_weights["Sub-B"]
        delta = float(latest_dynamic_weight) - base_subb
        absorber_total = sum(v for k, v in base_weights.items() if k != "Sub-B")
        for sleeve, base_weight in base_weights.items():
            if sleeve == "Sub-B":
                weights[sleeve] = float(latest_dynamic_weight)
            else:
                weights[sleeve] = base_weight - delta * (base_weight / absorber_total)
        return weights
    if dynamic_sleeve in weights:
        delta = float(latest_dynamic_weight) - base_weights[dynamic_sleeve]
        weights[dynamic_sleeve] = float(latest_dynamic_weight)
        weights["Sub-B"] = base_weights["Sub-B"] - delta
    return weights


def _external_scan_rows(
    scan_path: str | Path | None,
    latest_date: str,
    base_weights: dict[str, float],
) -> list[dict[str, object]]:
    if scan_path is None or not Path(scan_path).exists():
        return []
    scan = pd.read_csv(scan_path)
    if scan.empty or "dynamic_sleeve" not in scan.columns:
        return []
    fixed = scan[scan["candidate"] == FIXED_SCENARIO].iloc[0]
    candidate_rows = []
    for sleeve in EXTERNAL_SCAN_SLEEVES:
        sleeve_rows = scan[scan["dynamic_sleeve"] == sleeve].copy()
        if sleeve_rows.empty:
            continue
        sleeve_rows["recent_weighted_score"] = sleeve_rows.apply(
            lambda row: _score_external_candidate(row, fixed), axis=1
        )
        best = sleeve_rows.sort_values(
            ["recent_weighted_score", "sharpe_repo_full"], ascending=[False, False]
        ).iloc[0]
        weights = _external_candidate_weights(sleeve, float(best["latest_dynamic_sleeve"]), base_weights)
        row = {
            "scenario": str(best["candidate"]),
            "label": f"{sleeve} best own-DD advisory",
            "latest_date": latest_date,
            "latest_suba": weights["Sub-A"],
            "latest_subadk": weights["Sub-A-DK"],
            "latest_microcap": weights["Microcap"],
            "latest_subd": weights["Sub-D"],
            "latest_subb": weights["Sub-B"],
            "dynamic_sleeves": sleeve,
            "rebalance_count": float(best["rebalance_count"]),
            "allocation_turnover": float(best["allocation_turnover"]),
            "full_annual_return": float(best["ann_return_full"]),
            "full_max_dd": float(best["max_dd_full"]),
            "full_sharpe": float(best["sharpe_repo_full"]),
            "last_1y_annual_return": float(best["ann_return_last_1y"]),
            "last_1y_max_dd": float(best["max_dd_last_1y"]),
            "last_1y_sharpe": float(best["sharpe_repo_last_1y"]),
            "latest_excess_nav_vs_fixed": np.nan,
        }
        for segment in WINDOW_WEIGHTS:
            row[f"{segment}_annual_delta"] = float(best[f"ann_return_{segment}"] - fixed[f"ann_return_{segment}"])
            row[f"{segment}_max_dd_delta"] = float(best[f"max_dd_{segment}"] - fixed[f"max_dd_{segment}"])
            row[f"{segment}_sharpe_delta"] = float(best[f"sharpe_repo_{segment}"] - fixed[f"sharpe_repo_{segment}"])
        row["candidate_status"], row["evidence_note"] = _classify_candidate(row)
        candidate_rows.append(row)
    return candidate_rows


def build_level8_dashboard(
    metrics: pd.DataFrame,
    curve: pd.DataFrame,
    source_latest_date: pd.Timestamp | None = None,
    base_weights: dict[str, float] | None = None,
    external_scan_path: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    base_weights = dict(BASE_WEIGHTS if base_weights is None else base_weights)
    freshness, freshness_note = _freshness_state(curve, source_latest_date)
    latest_date = pd.Timestamp(curve.index[-1]).date().isoformat() if not curve.empty else ""
    if freshness == "stale":
        return pd.DataFrame(), {
            "decision_status": "REFRESH_REQUIRED",
            "data_freshness": freshness,
            "freshness_note": freshness_note,
            "latest_date": latest_date,
            "watch_scenario": "",
            "primary_action": "Refresh portfolio report before using advisory weights.",
        }

    fixed_full = _metric_row(metrics, FIXED_SCENARIO, "full")
    fixed_1y = _metric_row(metrics, FIXED_SCENARIO, "last_1y")
    rows = _build_base_scenario_rows(metrics, curve, latest_date, fixed_full, fixed_1y, base_weights)
    rows.extend(_external_scan_rows(external_scan_path, latest_date, base_weights))

    summary = pd.DataFrame(rows)
    status_order = {
        "BASELINE": 0,
        "ACTIVE_DEFAULT": 1,
        "LANDING_CANDIDATE": 2,
        "REPORT_WATCH_ONLY": 3,
        "DEFER": 4,
    }
    summary["_status_order"] = summary["candidate_status"].map(status_order).fillna(9)
    summary = summary.sort_values(
        ["_status_order", "full_annual_delta", "last_1y_annual_delta"],
        ascending=[True, False, False],
    ).drop(columns=["_status_order"]).reset_index(drop=True)
    decision = {
        "decision_status": "HOLD",
        "data_freshness": freshness,
        "freshness_note": freshness_note,
        "latest_date": latest_date,
        "watch_scenario": "",
        "primary_action": "Keep fixed default weights.",
    }
    active_rows = summary[summary["candidate_status"] == "ACTIVE_DEFAULT"]
    landing_rows = summary[summary["candidate_status"] == "LANDING_CANDIDATE"]
    if not active_rows.empty:
        active = active_rows.iloc[0]
        decision.update(
            {
                "decision_status": "ACTIVE_DEFAULT",
                "watch_scenario": str(active["scenario"]),
                "primary_action": (
                    "Use stacked Sub-A 5/8 weekly + Microcap 3/10 month-end as the active portfolio-level dynamic budget; keep fixed weights as benchmark and rollback."
                ),
            }
        )
    elif not landing_rows.empty:
        landing = landing_rows.iloc[0]
        decision.update(
            {
                "decision_status": "LANDING_CANDIDATE",
                "watch_scenario": str(landing["scenario"]),
                "primary_action": (
                    "Keep fixed default execution for now; use the best advisory row as the next promotion candidate."
                ),
            }
        )
    elif (summary["candidate_status"] == "REPORT_WATCH_ONLY").any():
        watch = summary[summary["candidate_status"] == "REPORT_WATCH_ONLY"].iloc[0]
        decision.update(
            {
                "decision_status": "WATCH",
                "watch_scenario": str(watch["scenario"]),
                "primary_action": "Keep fixed default execution; continue observing report-layer candidates.",
            }
        )
    summary["decision_status"] = decision["decision_status"]
    return summary, decision


def render_markdown(summary: pd.DataFrame, decision: dict[str, object]) -> str:
    lines = [
        "# V7.6 Level-8 Decision Dashboard",
        "",
        "## Decision Status",
        "",
        f"- Status: **{decision['decision_status']}**",
        f"- Data freshness: **{decision['data_freshness']}** ({decision['freshness_note']})",
        f"- Latest date: `{decision.get('latest_date', '')}`",
        f"- Primary action: {decision['primary_action']}",
    ]
    if decision.get("watch_scenario"):
        scenario_label = (
            "Active scenario"
            if decision.get("decision_status") == "ACTIVE_DEFAULT"
            else "Watch scenario"
        )
        lines.append(f"- {scenario_label}: `{decision['watch_scenario']}`")
    if summary.empty:
        lines.extend(["", "No scenario metrics are shown until the portfolio report is refreshed."])
        return "\n".join(lines)

    lines.extend(
        [
            "",
            "## Scenario Snapshot",
            "",
            "| Scenario | Status | Sub-A | Sub-A-DK | Microcap | Sub-D | Sub-B | Dynamic sleeves | Full annual / MaxDD / Sharpe | 1Y annual / MaxDD / Sharpe | Excess NAV | Switches | Turnover | Note |",
            "|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for _, row in summary.iterrows():
        lines.append(
            "| "
            f"{row['label']} | "
            f"{row['candidate_status']} | "
            f"{_weight(row['latest_suba'])} | "
            f"{_weight(row['latest_subadk'])} | "
            f"{_weight(row['latest_microcap'])} | "
            f"{_weight(row['latest_subd'])} | "
            f"{_weight(row['latest_subb'])} | "
            f"{row['dynamic_sleeves']} | "
            f"{_pct(row['full_annual_return'])} / {_pct(row['full_max_dd'])} / {row['full_sharpe']:.2f} | "
            f"{_pct(row['last_1y_annual_return'])} / {_pct(row['last_1y_max_dd'])} / {row['last_1y_sharpe']:.2f} | "
            f"{_pct(row['latest_excess_nav_vs_fixed'])} | "
            f"{int(row['rebalance_count']) if pd.notna(row['rebalance_count']) else 'n/a'} | "
            f"{row['allocation_turnover']:.1f} | "
            f"{row['evidence_note']} |"
        )

    lines.extend(
        [
            "",
            "## Read",
            "",
            "This dashboard is the portfolio-level budget decision surface. The stacked Sub-A 5/8 weekly + Microcap 3/10 month-end rule is the active dynamic budget; fixed weights remain the benchmark and rollback line.",
            "",
            "Status labels: ACTIVE_DEFAULT means the current portfolio-level dynamic budget; LANDING_CANDIDATE means next implementation candidate; REPORT_WATCH_ONLY means useful evidence but not a default; DEFER means not suitable under the current test design.",
        ]
    )
    return "\n".join(lines)


def _action_row(summary: pd.DataFrame, decision: dict[str, object]) -> pd.Series | None:
    scenario = str(decision.get("watch_scenario", ""))
    if scenario and scenario in set(summary["scenario"]):
        return summary[summary["scenario"] == scenario].iloc[0]
    active = summary[summary["candidate_status"] == "ACTIVE_DEFAULT"]
    if not active.empty:
        return active.iloc[0]
    fixed = summary[summary["scenario"] == FIXED_SCENARIO]
    if not fixed.empty:
        return fixed.iloc[0]
    if not summary.empty:
        return summary.iloc[0]
    return None


def render_action_summary(summary: pd.DataFrame, decision: dict[str, object]) -> str:
    row = _action_row(summary, decision)
    if row is None:
        return "\n".join(
            [
                "## 今日执行仓位",
                "",
                "- 状态: 无可用输出",
                "- 操作: 不调仓，先刷新 Level-8 Advisory 输出。",
            ]
        )

    stale = decision.get("data_freshness") != "fresh"
    status = str(decision.get("decision_status", ""))
    latest_date = str(row.get("latest_date", decision.get("latest_date", "")))
    action = (
        "不调仓，先刷新数据。"
        if stale
        else "按下表配置仓位；若账户已是这些权重，则持有不动。"
    )
    sleeves = [
        ("Sub-A", "latest_suba"),
        ("Sub-A-DK", "latest_subadk"),
        ("Microcap", "latest_microcap"),
        ("Sub-D", "latest_subd"),
        ("Sub-B", "latest_subb"),
    ]
    lines = [
        "## 今日执行仓位",
        "",
        f"- 数据日期: `{latest_date}`",
        f"- 状态: **{status}**",
        f"- 操作: {action}",
        "- 固定回滚线: `10% / 15% / 15% / 20% / 40%`",
        "",
        "| 袖珍组合 | 目标仓位 | 相对固定变化 | 说明 |",
        "|---|---:|---:|---|",
    ]
    dynamic = {item.strip() for item in str(row.get("dynamic_sleeves", "")).split(",") if item.strip()}
    for sleeve, column in sleeves:
        target = float(row.get(column, np.nan))
        base = BASE_WEIGHTS[sleeve]
        if sleeve in dynamic:
            note = "动态调整"
        elif sleeve == "Sub-B":
            note = "吸收权重差"
        else:
            note = "固定"
        lines.append(f"| {sleeve} | {_weight(target)} | {_weight_delta(target, base)} | {note} |")

    lines.extend(
        [
            "",
            "## 触发规则",
            "",
            "- Sub-A: 5/8 weekly 动态预算。",
            "- Microcap: 3/10 month-end 动态预算。",
            "- Sub-B: 自动吸收 Sub-A 和 Microcap 的仓位差。",
            "- 复核线: 相对固定组合的超额 NAV 回撤到 -5% 进入复核；到 -10% 回滚固定仓位。",
            "",
            "## 证据摘要",
            "",
            f"- 相对固定超额 NAV: {_pct(float(row.get('latest_excess_nav_vs_fixed', np.nan)))}",
            f"- 全样本相对固定: 年化 {_pct(float(row.get('full_annual_delta', np.nan)))} / 最大回撤改善 {_pct(float(row.get('full_max_dd_delta', np.nan)))} / Sharpe +{float(row.get('full_sharpe_delta', np.nan)):.2f}",
            f"- 近 1 年相对固定: 年化 {_pct(float(row.get('last_1y_annual_delta', np.nan)))} / 最大回撤改善 {_pct(float(row.get('last_1y_max_dd_delta', np.nan)))} / Sharpe +{float(row.get('last_1y_sharpe_delta', np.nan)):.2f}",
        ]
    )
    return "\n".join(lines)


def _history_scenario_name(decision: dict[str, object]) -> str:
    watch = str(decision.get("watch_scenario", ""))
    if watch.startswith("stacked_"):
        return watch[len("stacked_") :]
    return watch


def _history_row(
    summary: pd.DataFrame,
    decision: dict[str, object],
    run_timestamp: str | None = None,
) -> dict[str, object]:
    observed_at = run_timestamp or datetime.now().isoformat(timespec="seconds")
    scenario = _history_scenario_name(decision)
    if summary.empty:
        row = pd.Series(dtype=object)
    elif scenario and scenario in set(summary["scenario"]):
        row = summary[summary["scenario"] == scenario].iloc[0]
    elif FIXED_SCENARIO in set(summary["scenario"]):
        row = summary[summary["scenario"] == FIXED_SCENARIO].iloc[0]
        scenario = FIXED_SCENARIO
    else:
        row = summary.iloc[0]
        scenario = str(row.get("scenario", ""))

    history = {
        "observed_at": observed_at,
        "latest_date": str(row.get("latest_date", decision.get("latest_date", ""))),
        "decision_status": decision.get("decision_status", ""),
        "data_freshness": decision.get("data_freshness", ""),
        "watch_scenario": decision.get("watch_scenario", ""),
        "primary_action": decision.get("primary_action", ""),
        "scenario": scenario,
    }
    for name in HISTORY_COLUMNS:
        if name in history:
            continue
        history[name] = row.get(name, np.nan)
    return history


def append_decision_history(
    summary: pd.DataFrame,
    decision: dict[str, object],
    output_dir: str | Path,
    run_timestamp: str | None = None,
) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    history_path = out / "level8_decision_history.csv"
    new_row = pd.DataFrame([_history_row(summary, decision, run_timestamp)])
    if history_path.exists():
        existing = pd.read_csv(history_path)
        history = pd.concat([existing, new_row], ignore_index=True)
    else:
        history = new_row
    history = history[HISTORY_COLUMNS]
    history = history.drop_duplicates(
        subset=["latest_date", "decision_status", "watch_scenario"],
        keep="last",
    )
    history.to_csv(history_path, index=False, encoding="utf-8-sig")
    return history_path


def write_dashboard_outputs(summary: pd.DataFrame, decision: dict[str, object], output_dir: str | Path) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out / "level8_decision_dashboard.csv", index=False, encoding="utf-8-sig")
    (out / "level8_action_summary.md").write_text(
        render_action_summary(summary, decision), encoding="utf-8"
    )
    (out / "level8_decision_dashboard.md").write_text(
        render_markdown(summary, decision), encoding="utf-8"
    )
    append_decision_history(summary, decision, out)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build V7.6 Level-8 portfolio decision dashboard.")
    parser.add_argument("--metrics", default=str(DEFAULT_METRICS))
    parser.add_argument("--curve", default=str(DEFAULT_CURVE))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--source-returns", default=str(DEFAULT_SOURCE_RETURNS))
    parser.add_argument("--external-scan", default=str(DEFAULT_A_ADK_B_SUBD_SCAN))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    metrics = _read_metrics(args.metrics)
    curve = _read_curve(args.curve)
    base_weights = _read_base_weights(args.manifest)
    source_latest = _latest_date_from_csv(args.source_returns)
    summary, decision = build_level8_dashboard(
        metrics, curve, source_latest, base_weights, args.external_scan
    )
    write_dashboard_outputs(summary, decision, args.output_dir)
    print(render_action_summary(summary, decision))
    print()
    print(render_markdown(summary, decision))
    print(f"WROTE {Path(args.output_dir) / 'level8_decision_dashboard.csv'}")
    print(f"WROTE {Path(args.output_dir) / 'level8_action_summary.md'}")
    print(f"WROTE {Path(args.output_dir) / 'level8_decision_dashboard.md'}")
    print(f"WROTE {Path(args.output_dir) / 'level8_decision_history.csv'}")


if __name__ == "__main__":
    main()

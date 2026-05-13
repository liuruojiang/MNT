from __future__ import annotations

import argparse
from html import escape
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "portfolio_manifests" / "v76_current.json"
DEFAULT_RETURNS = (
    ROOT
    / "quant_param_scan_runs"
    / "20260512_v76_five_sleeve_real_subd_v20_rebalance_validation"
    / "aligned_five_sleeve_real_subd_returns.csv"
)
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "portfolio_v76_current"
FIXED_SCENARIO = "fixed_10_15_15_20_40"
ADVISORY_SCENARIO = "advisory_dd_3_10_month_end"
SUBA_ADVISORY_SCENARIO = "advisory_suba_dd_5_8_weekly"
STACKED_ADVISORY_SCENARIO = "advisory_suba_microcap_dd_3_10_month_end"
ACTIVE_DYNAMIC_BUDGET_SCENARIO = STACKED_ADVISORY_SCENARIO
WINDOWS = {
    "full": None,
    "last_10y": pd.DateOffset(years=10),
    "last_5y": pd.DateOffset(years=5),
    "last_3y": pd.DateOffset(years=3),
    "last_1y": pd.DateOffset(years=1),
}
DYNAMIC_BUDGET_SLEEVES = ["Sub-A", "Sub-A-DK", "Microcap", "Sub-D"]


@dataclass(frozen=True)
class PortfolioManifest:
    path: Path
    portfolio_id: str
    weights: dict[str, float]
    external_sleeves: list[str]
    internal_sleeves: list[str]


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> PortfolioManifest:
    manifest_path = Path(path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    sleeves = data.get("sleeves") or []
    weights = {str(item["name"]): float(item["weight"]) for item in sleeves}
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-10:
        raise ValueError(f"Portfolio weights must sum to 1.0, got {total:.12f}")
    source_types = {str(item["name"]): str(item.get("source_type", "")) for item in sleeves}
    return PortfolioManifest(
        path=manifest_path,
        portfolio_id=str(data.get("portfolio_id", manifest_path.stem)),
        weights=weights,
        external_sleeves=[name for name, kind in source_types.items() if kind == "external_script"],
        internal_sleeves=[name for name, kind in source_types.items() if kind == "v76_internal"],
    )


def load_aligned_returns(path: str | Path) -> pd.DataFrame:
    ret = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    ret.index.name = "date"
    return ret.apply(pd.to_numeric, errors="coerce")


def build_portfolio_nav(ret_df: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    missing = [name for name in weights if name not in ret_df.columns]
    if missing:
        raise ValueError(f"Return file is missing sleeve columns: {', '.join(missing)}")
    sleeve_returns = ret_df[list(weights)].fillna(0.0)
    weight_series = pd.Series(weights, dtype=float)
    portfolio_return = sleeve_returns.mul(weight_series, axis=1).sum(axis=1)
    nav = (1.0 + portfolio_return).cumprod()
    return pd.DataFrame(
        {
            "portfolio_return": portfolio_return,
            "portfolio_nav": nav,
        },
        index=ret_df.index,
    )


def build_portfolio_nav_from_weight_frame(
    ret_df: pd.DataFrame, weights_df: pd.DataFrame
) -> pd.DataFrame:
    missing = [name for name in weights_df.columns if name not in ret_df.columns]
    if missing:
        raise ValueError(f"Return file is missing sleeve columns: {', '.join(missing)}")
    sleeve_returns = ret_df[list(weights_df.columns)].fillna(0.0)
    aligned_weights = weights_df.reindex(sleeve_returns.index).ffill()
    if aligned_weights.isna().any().any():
        raise ValueError("Weight frame has missing weights after alignment")
    portfolio_return = sleeve_returns.mul(aligned_weights, axis=0).sum(axis=1)
    nav = (1.0 + portfolio_return).cumprod()
    return pd.DataFrame(
        {
            "portfolio_return": portfolio_return,
            "portfolio_nav": nav,
        },
        index=ret_df.index,
    )


def execution_mask(index: pd.DatetimeIndex, execution: str) -> pd.Series:
    if execution == "daily":
        return pd.Series(True, index=index)
    if execution == "weekly":
        periods = index.to_period("W-FRI")
    elif execution == "month_end":
        periods = index.to_period("M")
    else:
        raise ValueError(f"Unsupported execution: {execution}")

    current = pd.Series(periods, index=index)
    next_period = current.shift(-1)
    mask = current.ne(next_period)
    mask.iloc[-1] = False
    return mask


def sleeve_target_by_prior_dd(
    ret_df: pd.DataFrame,
    sleeve: str,
    boost_dd: float = 0.03,
    cut_dd: float = 0.10,
    base: float = 0.15,
    boost: float = 0.20,
    cut: float = 0.10,
) -> pd.Series:
    if sleeve not in ret_df.columns:
        raise ValueError(f"Return file is missing {sleeve} column")
    sleeve_nav = (1.0 + ret_df[sleeve].fillna(0.0)).cumprod()
    prior_peak = sleeve_nav.cummax().shift(1)
    prior_dd = sleeve_nav.shift(1) / prior_peak - 1.0
    target = pd.Series(base, index=ret_df.index, dtype=float)
    target.loc[prior_dd >= -boost_dd] = boost
    target.loc[prior_dd <= -cut_dd] = cut
    return target.fillna(base)


def microcap_target_by_prior_dd(
    ret_df: pd.DataFrame,
    boost_dd: float = 0.03,
    cut_dd: float = 0.10,
    base: float = 0.15,
    boost: float = 0.20,
    cut: float = 0.10,
) -> pd.Series:
    return sleeve_target_by_prior_dd(
        ret_df,
        "Microcap",
        boost_dd=boost_dd,
        cut_dd=cut_dd,
        base=base,
        boost=boost,
        cut=cut,
    )


def build_dynamic_sleeve_weights(
    ret_df: pd.DataFrame,
    weights: dict[str, float],
    sleeve: str,
    absorber: str = "Sub-B",
    execution: str = "month_end",
    boost_dd: float = 0.03,
    cut_dd: float = 0.10,
    step: float = 0.05,
) -> pd.DataFrame:
    if sleeve == absorber:
        raise ValueError("Dynamic sleeve and absorber must be different")
    missing_weights = [name for name in [sleeve, absorber] if name not in weights]
    if missing_weights:
        raise ValueError(f"Manifest is missing sleeve weights: {', '.join(missing_weights)}")
    base = weights[sleeve]
    boost = base + step
    cut = max(base - step, 0.0)
    target = sleeve_target_by_prior_dd(
        ret_df,
        sleeve,
        boost_dd=boost_dd,
        cut_dd=cut_dd,
        base=base,
        boost=boost,
        cut=cut,
    )
    mask = execution_mask(ret_df.index, execution)
    executed = pd.Series(np.nan, index=ret_df.index, dtype=float)
    executed.iloc[0] = base
    executed.loc[mask] = target.loc[mask]
    executed = executed.ffill()

    dynamic = pd.DataFrame(weights, index=ret_df.index, dtype=float)
    delta = executed - base
    dynamic[sleeve] = executed
    dynamic[absorber] = weights[absorber] - delta
    dynamic = dynamic[list(weights)]
    if (dynamic < -1e-12).any().any():
        raise ValueError("Dynamic weights produced a negative sleeve weight")
    if not np.allclose(dynamic.sum(axis=1).to_numpy(), 1.0):
        raise ValueError("Dynamic weights must sum to 1.0 on every date")
    return dynamic


def build_dynamic_microcap_weights(
    ret_df: pd.DataFrame,
    weights: dict[str, float],
    execution: str = "month_end",
    boost_dd: float = 0.03,
    cut_dd: float = 0.10,
) -> pd.DataFrame:
    required = ["Sub-A", "Sub-A-DK", "Microcap", "Sub-D", "Sub-B"]
    missing = [name for name in required if name not in weights]
    if missing:
        raise ValueError(f"Manifest is missing sleeve weights: {', '.join(missing)}")

    return build_dynamic_sleeve_weights(
        ret_df,
        weights,
        sleeve="Microcap",
        absorber="Sub-B",
        execution=execution,
        boost_dd=boost_dd,
        cut_dd=cut_dd,
        step=0.05,
    )


def build_multi_dynamic_sleeve_weights(
    ret_df: pd.DataFrame,
    weights: dict[str, float],
    sleeves: list[str],
    absorber: str = "Sub-B",
    execution: str = "month_end",
    boost_dd: float = 0.03,
    cut_dd: float = 0.10,
    step: float = 0.05,
) -> pd.DataFrame:
    if absorber not in weights:
        raise ValueError(f"Manifest is missing absorber weight: {absorber}")
    if len(set(sleeves)) != len(sleeves):
        raise ValueError("Dynamic sleeves must be unique")
    if absorber in sleeves:
        raise ValueError("Dynamic sleeve and absorber must be different")
    missing = [name for name in sleeves if name not in weights]
    if missing:
        raise ValueError(f"Manifest is missing sleeve weights: {', '.join(missing)}")

    dynamic = pd.DataFrame(weights, index=ret_df.index, dtype=float)
    total_delta = pd.Series(0.0, index=ret_df.index, dtype=float)
    for sleeve in sleeves:
        base = weights[sleeve]
        target = sleeve_target_by_prior_dd(
            ret_df,
            sleeve,
            boost_dd=boost_dd,
            cut_dd=cut_dd,
            base=base,
            boost=base + step,
            cut=max(base - step, 0.0),
        )
        mask = execution_mask(ret_df.index, execution)
        executed = pd.Series(np.nan, index=ret_df.index, dtype=float)
        executed.iloc[0] = base
        executed.loc[mask] = target.loc[mask]
        executed = executed.ffill()
        dynamic[sleeve] = executed
        total_delta = total_delta + (executed - base)

    dynamic[absorber] = weights[absorber] - total_delta
    dynamic = dynamic[list(weights)]
    if (dynamic < -1e-12).any().any():
        raise ValueError("Dynamic weights produced a negative sleeve weight")
    if not np.allclose(dynamic.sum(axis=1).to_numpy(), 1.0):
        raise ValueError("Dynamic weights must sum to 1.0 on every date")
    return dynamic


def build_stacked_suba_microcap_weights(
    ret_df: pd.DataFrame,
    weights: dict[str, float],
) -> pd.DataFrame:
    required = ["Sub-A", "Microcap", "Sub-B"]
    missing = [name for name in required if name not in weights]
    if missing:
        raise ValueError(f"Manifest is missing sleeve weights: {', '.join(missing)}")

    suba_base = weights["Sub-A"]
    microcap_base = weights["Microcap"]
    suba_target = sleeve_target_by_prior_dd(
        ret_df,
        "Sub-A",
        boost_dd=0.05,
        cut_dd=0.08,
        base=suba_base,
        boost=suba_base + 0.05,
        cut=max(suba_base - 0.05, 0.0),
    )
    microcap_target = sleeve_target_by_prior_dd(
        ret_df,
        "Microcap",
        boost_dd=0.03,
        cut_dd=0.10,
        base=microcap_base,
        boost=microcap_base + 0.05,
        cut=max(microcap_base - 0.05, 0.0),
    )

    suba_executed = pd.Series(np.nan, index=ret_df.index, dtype=float)
    suba_executed.iloc[0] = suba_base
    suba_mask = execution_mask(ret_df.index, "weekly")
    suba_executed.loc[suba_mask] = suba_target.loc[suba_mask]
    suba_executed = suba_executed.ffill()

    microcap_executed = pd.Series(np.nan, index=ret_df.index, dtype=float)
    microcap_executed.iloc[0] = microcap_base
    microcap_mask = execution_mask(ret_df.index, "month_end")
    microcap_executed.loc[microcap_mask] = microcap_target.loc[microcap_mask]
    microcap_executed = microcap_executed.ffill()

    dynamic = pd.DataFrame(weights, index=ret_df.index, dtype=float)
    total_delta = (suba_executed - suba_base) + (microcap_executed - microcap_base)
    dynamic["Sub-A"] = suba_executed
    dynamic["Microcap"] = microcap_executed
    dynamic["Sub-B"] = weights["Sub-B"] - total_delta
    dynamic = dynamic[list(weights)]
    if (dynamic < -1e-12).any().any():
        raise ValueError("Dynamic weights produced a negative sleeve weight")
    if not np.allclose(dynamic.sum(axis=1).to_numpy(), 1.0):
        raise ValueError("Dynamic weights must sum to 1.0 on every date")
    return dynamic


def build_suba_5_8_weekly_weights(
    ret_df: pd.DataFrame,
    weights: dict[str, float],
) -> pd.DataFrame:
    return build_dynamic_sleeve_weights(
        ret_df,
        weights,
        sleeve="Sub-A",
        absorber="Sub-B",
        execution="weekly",
        boost_dd=0.05,
        cut_dd=0.08,
        step=0.05,
    )


def allocation_turnover(weights_df: pd.DataFrame) -> float:
    return float(weights_df.diff().abs().sum(axis=1).sum())


def rebalance_count(weights_df: pd.DataFrame) -> int:
    changes = weights_df.diff().abs().sum(axis=1)
    return int((changes > 1e-12).sum())


def summarize_nav(nav_df: pd.DataFrame, segment: str, offset: pd.DateOffset | None) -> dict[str, object]:
    part = nav_df.copy() if offset is None else nav_df.loc[nav_df.index >= nav_df.index[-1] - offset].copy()
    if len(part) < 2:
        raise ValueError(f"Not enough rows for {segment}")
    nav = part["portfolio_nav"] / part["portfolio_nav"].iloc[0]
    ret = nav.pct_change().dropna()
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    annual_return = nav.iloc[-1] ** (1.0 / years) - 1.0
    annual_vol = ret.std(ddof=1) * np.sqrt(252.0)
    max_dd = (nav / nav.cummax() - 1.0).min()
    return {
        "segment": segment,
        "start": nav.index[0].date().isoformat(),
        "end": nav.index[-1].date().isoformat(),
        "rows": int(len(nav)),
        "annual_return": float(annual_return),
        "annual_vol": float(annual_vol),
        "sharpe": float(annual_return / annual_vol) if annual_vol and annual_vol > 0 else np.nan,
        "max_dd": float(max_dd),
        "total_return": float(nav.iloc[-1] - 1.0),
    }


def build_window_metrics(nav_df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [summarize_nav(nav_df, segment, offset) for segment, offset in WINDOWS.items()]
    )


def build_scenario_outputs(
    ret_df: pd.DataFrame, weights: dict[str, float]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    fixed_nav = build_portfolio_nav(ret_df, weights)
    advisory_weights = build_dynamic_microcap_weights(ret_df, weights, execution="month_end")
    advisory_nav = build_portfolio_nav_from_weight_frame(ret_df, advisory_weights)
    suba_advisory_weights = build_suba_5_8_weekly_weights(ret_df, weights)
    suba_advisory_nav = build_portfolio_nav_from_weight_frame(ret_df, suba_advisory_weights)
    stacked_weights = build_stacked_suba_microcap_weights(ret_df, weights)
    stacked_nav = build_portfolio_nav_from_weight_frame(ret_df, stacked_weights)
    scenario_weights = {
        ADVISORY_SCENARIO: advisory_weights,
        SUBA_ADVISORY_SCENARIO: suba_advisory_weights,
        STACKED_ADVISORY_SCENARIO: stacked_weights,
    }

    scenario_nav = pd.DataFrame(index=ret_df.index)
    for scenario, nav in {
        FIXED_SCENARIO: fixed_nav,
        ADVISORY_SCENARIO: advisory_nav,
        SUBA_ADVISORY_SCENARIO: suba_advisory_nav,
        STACKED_ADVISORY_SCENARIO: stacked_nav,
    }.items():
        scenario_nav[f"{scenario}_return"] = nav["portfolio_return"]
        scenario_nav[f"{scenario}_nav"] = nav["portfolio_nav"]

    fixed_weights = pd.DataFrame(weights, index=ret_df.index)
    metrics = []
    for scenario, nav, weight_frame in [
        (FIXED_SCENARIO, fixed_nav, fixed_weights),
        (ADVISORY_SCENARIO, advisory_nav, advisory_weights),
        (SUBA_ADVISORY_SCENARIO, suba_advisory_nav, suba_advisory_weights),
        (STACKED_ADVISORY_SCENARIO, stacked_nav, stacked_weights),
    ]:
        scenario_metrics = build_window_metrics(nav)
        scenario_metrics.insert(0, "scenario", scenario)
        scenario_metrics["avg_suba"] = float(weight_frame["Sub-A"].mean())
        scenario_metrics["avg_microcap"] = float(weight_frame["Microcap"].mean())
        scenario_metrics["latest_suba"] = float(weight_frame["Sub-A"].iloc[-1])
        scenario_metrics["latest_microcap"] = float(weight_frame["Microcap"].iloc[-1])
        scenario_metrics["latest_subb"] = float(weight_frame["Sub-B"].iloc[-1])
        scenario_metrics["rebalance_count"] = rebalance_count(weight_frame)
        scenario_metrics["allocation_turnover"] = allocation_turnover(weight_frame)
        metrics.append(scenario_metrics)

    return scenario_nav, pd.concat(metrics, ignore_index=True), scenario_weights


def scenario_name_for_sleeve(sleeve: str) -> str:
    clean = sleeve.lower().replace("-", "")
    return f"advisory_{clean}_dd_3_10_month_end"


def build_dynamic_sleeve_budget_scan(
    ret_df: pd.DataFrame,
    weights: dict[str, float],
    sleeves: list[str] | None = None,
    absorber: str = "Sub-B",
) -> pd.DataFrame:
    sleeve_list = list(sleeves or DYNAMIC_BUDGET_SLEEVES)
    rows = []
    fixed_weights = pd.DataFrame(weights, index=ret_df.index)
    fixed_nav = build_portfolio_nav(ret_df, weights)
    fixed_metrics = build_window_metrics(fixed_nav)
    fixed_metrics.insert(0, "scenario", FIXED_SCENARIO)
    fixed_metrics["dynamic_sleeve"] = ""
    fixed_metrics["absorber"] = ""
    fixed_metrics["avg_dynamic_sleeve"] = np.nan
    fixed_metrics["latest_dynamic_sleeve"] = np.nan
    fixed_metrics["latest_absorber"] = float(fixed_weights[absorber].iloc[-1])
    fixed_metrics["rebalance_count"] = 0
    fixed_metrics["allocation_turnover"] = 0.0
    rows.append(fixed_metrics)

    for sleeve in sleeve_list:
        if sleeve == absorber:
            continue
        dynamic_weights = build_dynamic_sleeve_weights(
            ret_df, weights, sleeve=sleeve, absorber=absorber, execution="month_end"
        )
        nav = build_portfolio_nav_from_weight_frame(ret_df, dynamic_weights)
        metrics = build_window_metrics(nav)
        metrics.insert(0, "scenario", scenario_name_for_sleeve(sleeve))
        metrics["dynamic_sleeve"] = sleeve
        metrics["absorber"] = absorber
        metrics["avg_dynamic_sleeve"] = float(dynamic_weights[sleeve].mean())
        metrics["latest_dynamic_sleeve"] = float(dynamic_weights[sleeve].iloc[-1])
        metrics["latest_absorber"] = float(dynamic_weights[absorber].iloc[-1])
        metrics["rebalance_count"] = rebalance_count(dynamic_weights)
        metrics["allocation_turnover"] = allocation_turnover(dynamic_weights)
        rows.append(metrics)
    return pd.concat(rows, ignore_index=True)


def format_dynamic_sleeve_budget_summary(scan_metrics: pd.DataFrame) -> str:
    fixed_full = _metric_row(scan_metrics, FIXED_SCENARIO, "full")
    fixed_1y = _metric_row(scan_metrics, FIXED_SCENARIO, "last_1y")
    candidate_names = [name for name in scan_metrics["scenario"].unique() if name != FIXED_SCENARIO]
    lines = [
        "# V7.6 Dynamic Sleeve Budget Scan",
        "",
        "## Scope",
        "",
        "Each candidate applies the same prior-NAV-drawdown rule to one sleeve only. Sub-B absorbs the weight delta. This is research output only and does not change executable defaults.",
        "",
        "Rule: month-end execution, +5pp when prior sleeve drawdown is within 3%, -5pp when prior drawdown is at or below -10%, otherwise base weight.",
        "",
        "## Candidate Summary",
        "",
        "| Candidate | Sleeve | Full Ann. Delta | Full MaxDD Delta | Full Sharpe Delta | 1Y Ann. Delta | 1Y Sharpe Delta | Latest sleeve | Latest Sub-B | Switches | Turnover |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in candidate_names:
        full = _metric_row(scan_metrics, name, "full")
        one_y = _metric_row(scan_metrics, name, "last_1y")
        lines.append(
            "| "
            f"`{name}` | {full['dynamic_sleeve']} | "
            f"{_pct(float(full['annual_return'] - fixed_full['annual_return']))} | "
            f"{_pct(float(full['max_dd'] - fixed_full['max_dd']))} | "
            f"{float(full['sharpe'] - fixed_full['sharpe']):+.2f} | "
            f"{_pct(float(one_y['annual_return'] - fixed_1y['annual_return']))} | "
            f"{float(one_y['sharpe'] - fixed_1y['sharpe']):+.2f} | "
            f"{_pct(float(full['latest_dynamic_sleeve']))} | "
            f"{_pct(float(full['latest_absorber']))} | "
            f"{int(full['rebalance_count'])} | "
            f"{float(full['allocation_turnover']):.1f} |"
        )
    return "\n".join(lines)


def build_scenario_economic_curve(
    scenario_nav: pd.DataFrame, scenario_weights: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    fixed_return_col = f"{FIXED_SCENARIO}_return"
    fixed_nav_col = f"{FIXED_SCENARIO}_nav"
    scenario_prefixes = {
        ADVISORY_SCENARIO: "advisory",
        SUBA_ADVISORY_SCENARIO: "suba_advisory",
        STACKED_ADVISORY_SCENARIO: "stacked_advisory",
    }
    required = [fixed_return_col, fixed_nav_col]
    for scenario in scenario_prefixes:
        required.extend([f"{scenario}_return", f"{scenario}_nav"])
    missing = [col for col in required if col not in scenario_nav.columns]
    if missing:
        raise ValueError(f"Scenario NAV is missing columns: {', '.join(missing)}")
    missing_scenarios = [scenario for scenario in scenario_prefixes if scenario not in scenario_weights]
    if missing_scenarios:
        raise ValueError(f"Scenario weights are missing scenarios: {', '.join(missing_scenarios)}")

    fixed_nav = scenario_nav[fixed_nav_col]
    curve = pd.DataFrame(index=scenario_nav.index)
    curve["fixed_return"] = scenario_nav[fixed_return_col]
    curve["fixed_nav"] = fixed_nav
    curve["fixed_drawdown"] = fixed_nav / fixed_nav.cummax() - 1.0

    for scenario, prefix in scenario_prefixes.items():
        weights_df = scenario_weights[scenario]
        required_weight_cols = ["Sub-A", "Microcap", "Sub-B"]
        missing_weights = [col for col in required_weight_cols if col not in weights_df.columns]
        if missing_weights:
            raise ValueError(f"{scenario} weights are missing columns: {', '.join(missing_weights)}")
        scenario_return = scenario_nav[f"{scenario}_return"]
        scenario_nav_series = scenario_nav[f"{scenario}_nav"]
        curve[f"{prefix}_return"] = scenario_return
        curve[f"{prefix}_nav"] = scenario_nav_series
        curve[f"{prefix}_drawdown"] = scenario_nav_series / scenario_nav_series.cummax() - 1.0
        curve[f"{prefix}_excess_return"] = scenario_return - curve["fixed_return"]
        curve[f"{prefix}_excess_nav"] = scenario_nav_series / fixed_nav - 1.0
        curve[f"{prefix}_suba_weight"] = weights_df["Sub-A"].reindex(curve.index).ffill()
        curve[f"{prefix}_microcap_weight"] = weights_df["Microcap"].reindex(curve.index).ffill()
        curve[f"{prefix}_subb_weight"] = weights_df["Sub-B"].reindex(curve.index).ffill()
    return curve


def _pct(value: float) -> str:
    return f"{value:.2%}"


def _multiple(value: float) -> str:
    return f"{value:.2f}x"


def _metric_row(metrics: pd.DataFrame, scenario: str, segment: str) -> pd.Series:
    rows = metrics[(metrics["scenario"] == scenario) & (metrics["segment"] == segment)]
    if rows.empty:
        raise ValueError(f"Missing metrics for {scenario} / {segment}")
    return rows.iloc[0]


def format_scenario_decision_summary(
    scenario_metrics: pd.DataFrame, economic_curve: pd.DataFrame
) -> str:
    latest = economic_curve.iloc[-1]
    fixed_full = _metric_row(scenario_metrics, FIXED_SCENARIO, "full")
    advisory_full = _metric_row(scenario_metrics, ADVISORY_SCENARIO, "full")
    suba_full = _metric_row(scenario_metrics, SUBA_ADVISORY_SCENARIO, "full")
    stacked_full = _metric_row(scenario_metrics, STACKED_ADVISORY_SCENARIO, "full")
    fixed_1y = _metric_row(scenario_metrics, FIXED_SCENARIO, "last_1y")
    advisory_1y = _metric_row(scenario_metrics, ADVISORY_SCENARIO, "last_1y")
    suba_1y = _metric_row(scenario_metrics, SUBA_ADVISORY_SCENARIO, "last_1y")
    stacked_1y = _metric_row(scenario_metrics, STACKED_ADVISORY_SCENARIO, "last_1y")
    return "\n".join(
        [
            "# V7.6 Portfolio Scenario Decision Summary",
            "",
            "## Scope",
            "",
            "This report compares the fixed five-sleeve benchmark with portfolio-layer dynamic-budget scenarios.",
            f"Active dynamic budget default: `{ACTIVE_DYNAMIC_BUDGET_SCENARIO}`.",
            "Fixed 10/15/15/20/40 remains the benchmark for attribution and rollback.",
            "",
            "## Latest Advisory State",
            "",
            f"- Scenario: `{ADVISORY_SCENARIO}`",
            f"- Latest date: `{economic_curve.index[-1].date().isoformat()}`",
            f"- Latest Microcap advisory weight: {_pct(float(latest['advisory_microcap_weight']))}",
            f"- Latest Sub-B absorbing weight: {_pct(float(latest['advisory_subb_weight']))}",
            f"- Advisory excess NAV versus fixed: {_pct(float(latest['advisory_excess_nav']))}",
            "",
            f"- Scenario: `{SUBA_ADVISORY_SCENARIO}`",
            f"- Latest Sub-A advisory weight: {_pct(float(latest['suba_advisory_suba_weight']))}",
            f"- Latest Microcap fixed weight: {_pct(float(latest['suba_advisory_microcap_weight']))}",
            f"- Latest Sub-B absorbing weight: {_pct(float(latest['suba_advisory_subb_weight']))}",
            f"- Sub-A advisory excess NAV versus fixed: {_pct(float(latest['suba_advisory_excess_nav']))}",
            "",
            f"- Scenario: `{STACKED_ADVISORY_SCENARIO}`",
            f"- Latest Sub-A advisory weight: {_pct(float(latest['stacked_advisory_suba_weight']))}",
            f"- Latest Microcap advisory weight: {_pct(float(latest['stacked_advisory_microcap_weight']))}",
            f"- Latest Sub-B absorbing weight: {_pct(float(latest['stacked_advisory_subb_weight']))}",
            f"- Stacked advisory excess NAV versus fixed: {_pct(float(latest['stacked_advisory_excess_nav']))}",
            "",
            "## Metric Comparison",
            "",
            "| Window | Fixed annual / MaxDD / Sharpe | Microcap advisory annual / MaxDD / Sharpe | Sub-A advisory annual / MaxDD / Sharpe | Stacked advisory annual / MaxDD / Sharpe |",
            "|---|---:|---:|---:|---:|",
            (
                f"| Full | {_pct(float(fixed_full['annual_return']))} / {_pct(float(fixed_full['max_dd']))} / "
                f"{float(fixed_full['sharpe']):.2f} | {_pct(float(advisory_full['annual_return']))} / "
                f"{_pct(float(advisory_full['max_dd']))} / {float(advisory_full['sharpe']):.2f} | "
                f"{_pct(float(suba_full['annual_return']))} / {_pct(float(suba_full['max_dd']))} / "
                f"{float(suba_full['sharpe']):.2f} | "
                f"{_pct(float(stacked_full['annual_return']))} / {_pct(float(stacked_full['max_dd']))} / "
                f"{float(stacked_full['sharpe']):.2f} |"
            ),
            (
                f"| 1Y | {_pct(float(fixed_1y['annual_return']))} / {_pct(float(fixed_1y['max_dd']))} / "
                f"{float(fixed_1y['sharpe']):.2f} | {_pct(float(advisory_1y['annual_return']))} / "
                f"{_pct(float(advisory_1y['max_dd']))} / {float(advisory_1y['sharpe']):.2f} | "
                f"{_pct(float(suba_1y['annual_return']))} / {_pct(float(suba_1y['max_dd']))} / "
                f"{float(suba_1y['sharpe']):.2f} | "
                f"{_pct(float(stacked_1y['annual_return']))} / {_pct(float(stacked_1y['max_dd']))} / "
                f"{float(stacked_1y['sharpe']):.2f} |"
            ),
            "",
            "## Decision",
            "",
            f"Use `{ACTIVE_DYNAMIC_BUDGET_SCENARIO}` as the active portfolio-level dynamic budget. Keep Sub-A-only and Microcap-only rules as report-layer comparisons.",
        ]
    )


def output_path_metadata(path: str | Path) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(ROOT)
        except ValueError:
            pass
    return candidate.as_posix()


def _downsample_for_svg(df: pd.DataFrame, max_points: int = 700) -> pd.DataFrame:
    if len(df) <= max_points:
        return df
    step = int(np.ceil(len(df) / max_points))
    sampled = df.iloc[::step].copy()
    if sampled.index[-1] != df.index[-1]:
        sampled = pd.concat([sampled, df.iloc[[-1]]])
    return sampled


def _svg_line_chart(
    chart_id: str,
    title: str,
    series: dict[str, pd.Series],
    colors: dict[str, str],
    value_format,
    height: int = 280,
    width: int = 960,
) -> str:
    valid_series = {
        name: pd.to_numeric(values, errors="coerce").dropna()
        for name, values in series.items()
        if not values.dropna().empty
    }
    if not valid_series:
        return f'<section class="chart-panel"><h2>{escape(title)}</h2><p>No data.</p></section>'

    left, right, top, bottom = 64, 24, 26, 42
    plot_w = width - left - right
    plot_h = height - top - bottom
    all_values = pd.concat(valid_series.values())
    y_min = float(all_values.min())
    y_max = float(all_values.max())
    if np.isclose(y_min, y_max):
        pad = max(abs(y_min) * 0.05, 0.01)
        y_min -= pad
        y_max += pad
    else:
        pad = (y_max - y_min) * 0.08
        y_min -= pad
        y_max += pad

    all_index = pd.Index(sorted(set().union(*[set(s.index) for s in valid_series.values()])))
    x_lookup = {idx: i for i, idx in enumerate(all_index)}
    x_den = max(len(all_index) - 1, 1)

    def x_pos(idx) -> float:
        return left + plot_w * x_lookup[idx] / x_den

    def y_pos(value: float) -> float:
        return top + plot_h * (y_max - value) / (y_max - y_min)

    y_ticks = [y_min, (y_min + y_max) / 2.0, y_max]
    grid = []
    for tick in y_ticks:
        y = y_pos(tick)
        grid.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" class="grid" />'
        )
        grid.append(
            f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" class="axis-label">{escape(value_format(tick))}</text>'
        )

    paths = []
    legend = []
    for offset, (name, values) in enumerate(valid_series.items()):
        points = " ".join(f"{x_pos(idx):.2f},{y_pos(float(value)):.2f}" for idx, value in values.items())
        color = colors.get(name, "#4b5563")
        paths.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.6" />')
        legend_x = left + offset * 220
        legend.append(
            f'<g><line x1="{legend_x}" y1="{height - 18}" x2="{legend_x + 28}" y2="{height - 18}" stroke="{color}" stroke-width="3" />'
            f'<text x="{legend_x + 36}" y="{height - 14}" class="legend">{escape(name)}</text></g>'
        )

    start_label = all_index[0].date().isoformat() if hasattr(all_index[0], "date") else str(all_index[0])
    end_label = all_index[-1].date().isoformat() if hasattr(all_index[-1], "date") else str(all_index[-1])
    return "\n".join(
        [
            f'<section class="chart-panel" id="{escape(chart_id)}">',
            f"<h2>{escape(title)}</h2>",
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
            f'<rect x="0" y="0" width="{width}" height="{height}" class="svg-bg" />',
            *grid,
            f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" class="axis" />',
            f'<text x="{left}" y="{height - 24}" class="axis-label">{escape(start_label)}</text>',
            f'<text x="{width - right}" y="{height - 24}" text-anchor="end" class="axis-label">{escape(end_label)}</text>',
            *paths,
            *legend,
            "</svg>",
            "</section>",
        ]
    )


def _metric_table_html(scenario_metrics: pd.DataFrame) -> str:
    rows = []
    for segment, label in [("full", "Full"), ("last_10y", "10Y"), ("last_5y", "5Y"), ("last_3y", "3Y"), ("last_1y", "1Y")]:
        has_fixed = ((scenario_metrics["scenario"] == FIXED_SCENARIO) & (scenario_metrics["segment"] == segment)).any()
        has_advisory = (
            (scenario_metrics["scenario"] == ADVISORY_SCENARIO)
            & (scenario_metrics["segment"] == segment)
        ).any()
        has_suba = (
            (scenario_metrics["scenario"] == SUBA_ADVISORY_SCENARIO)
            & (scenario_metrics["segment"] == segment)
        ).any()
        has_stacked = (
            (scenario_metrics["scenario"] == STACKED_ADVISORY_SCENARIO)
            & (scenario_metrics["segment"] == segment)
        ).any()
        if not (has_fixed and has_advisory and has_suba and has_stacked):
            continue
        fixed = _metric_row(scenario_metrics, FIXED_SCENARIO, segment)
        advisory = _metric_row(scenario_metrics, ADVISORY_SCENARIO, segment)
        suba = _metric_row(scenario_metrics, SUBA_ADVISORY_SCENARIO, segment)
        stacked = _metric_row(scenario_metrics, STACKED_ADVISORY_SCENARIO, segment)
        rows.append(
            "<tr>"
            f"<td>{label}</td>"
            f"<td>{_pct(float(fixed['annual_return']))}</td>"
            f"<td>{_pct(float(fixed['max_dd']))}</td>"
            f"<td>{float(fixed['sharpe']):.2f}</td>"
            f"<td>{_pct(float(advisory['annual_return']))}</td>"
            f"<td>{_pct(float(advisory['max_dd']))}</td>"
            f"<td>{float(advisory['sharpe']):.2f}</td>"
            f"<td>{_pct(float(suba['annual_return']))}</td>"
            f"<td>{_pct(float(suba['max_dd']))}</td>"
            f"<td>{float(suba['sharpe']):.2f}</td>"
            f"<td>{_pct(float(stacked['annual_return']))}</td>"
            f"<td>{_pct(float(stacked['max_dd']))}</td>"
            f"<td>{float(stacked['sharpe']):.2f}</td>"
            "</tr>"
        )
    return "\n".join(
        [
            '<table class="metrics-table">',
            "<thead><tr><th>Window</th><th>Fixed Ann.</th><th>Fixed MaxDD</th><th>Fixed Sharpe</th><th>Microcap Ann.</th><th>Microcap MaxDD</th><th>Microcap Sharpe</th><th>Sub-A Ann.</th><th>Sub-A MaxDD</th><th>Sub-A Sharpe</th><th>Stacked Ann.</th><th>Stacked MaxDD</th><th>Stacked Sharpe</th></tr></thead>",
            "<tbody>",
            *rows,
            "</tbody></table>",
        ]
    )


def render_scenario_visual_report(scenario_metrics: pd.DataFrame, economic_curve: pd.DataFrame) -> str:
    curve = _downsample_for_svg(economic_curve)
    latest = economic_curve.iloc[-1]
    fixed_full = _metric_row(scenario_metrics, FIXED_SCENARIO, "full")
    advisory_full = _metric_row(scenario_metrics, ADVISORY_SCENARIO, "full")
    suba_full = _metric_row(scenario_metrics, SUBA_ADVISORY_SCENARIO, "full")
    stacked_full = _metric_row(scenario_metrics, STACKED_ADVISORY_SCENARIO, "full")
    advisory_1y = _metric_row(scenario_metrics, ADVISORY_SCENARIO, "last_1y")
    suba_1y = _metric_row(scenario_metrics, SUBA_ADVISORY_SCENARIO, "last_1y")
    stacked_1y = _metric_row(scenario_metrics, STACKED_ADVISORY_SCENARIO, "last_1y")
    colors = {
        "Fixed NAV": "#2563eb",
        "Microcap advisory NAV": "#0f766e",
        "Sub-A advisory NAV": "#9333ea",
        "Stacked advisory NAV": "#b45309",
        "Fixed DD": "#3b82f6",
        "Microcap advisory DD": "#14b8a6",
        "Sub-A advisory DD": "#a855f7",
        "Stacked advisory DD": "#f59e0b",
        "Microcap excess": "#7c3aed",
        "Sub-A excess": "#6d28d9",
        "Stacked excess": "#b91c1c",
        "Sub-A advisory weight": "#9333ea",
        "Sub-A stacked weight": "#b45309",
        "Microcap weight": "#dc2626",
        "Sub-B Sub-A advisory weight": "#64748b",
        "Microcap stacked weight": "#f97316",
        "Sub-B weight": "#475569",
        "Sub-B stacked weight": "#111827",
    }
    nav_chart = _svg_line_chart(
        "nav-chart",
        "NAV: Fixed vs Advisory",
        {
            "Fixed NAV": curve["fixed_nav"],
            "Microcap advisory NAV": curve["advisory_nav"],
            "Sub-A advisory NAV": curve["suba_advisory_nav"],
            "Stacked advisory NAV": curve["stacked_advisory_nav"],
        },
        colors,
        _multiple,
    )
    dd_chart = _svg_line_chart(
        "drawdown-chart",
        "Daily Drawdown",
        {
            "Fixed DD": curve["fixed_drawdown"],
            "Microcap advisory DD": curve["advisory_drawdown"],
            "Sub-A advisory DD": curve["suba_advisory_drawdown"],
            "Stacked advisory DD": curve["stacked_advisory_drawdown"],
        },
        colors,
        _pct,
    )
    excess_chart = _svg_line_chart(
        "excess-chart",
        "Advisory Excess NAV",
        {
            "Microcap excess": curve["advisory_excess_nav"],
            "Sub-A excess": curve["suba_advisory_excess_nav"],
            "Stacked excess": curve["stacked_advisory_excess_nav"],
        },
        colors,
        _pct,
    )
    weight_chart = _svg_line_chart(
        "weight-chart",
        "Advisory Weights",
        {
            "Microcap weight": curve["advisory_microcap_weight"],
            "Sub-B weight": curve["advisory_subb_weight"],
            "Sub-A advisory weight": curve["suba_advisory_suba_weight"],
            "Sub-B Sub-A advisory weight": curve["suba_advisory_subb_weight"],
            "Sub-A stacked weight": curve["stacked_advisory_suba_weight"],
            "Microcap stacked weight": curve["stacked_advisory_microcap_weight"],
            "Sub-B stacked weight": curve["stacked_advisory_subb_weight"],
        },
        colors,
        _pct,
    )
    latest_date = economic_curve.index[-1].date().isoformat()
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8" />',
            '<meta name="viewport" content="width=device-width, initial-scale=1" />',
            "<title>V7.6 Portfolio Scenario Visual Report</title>",
            "<style>",
            "body{margin:0;background:#f8fafc;color:#0f172a;font-family:Arial,'Microsoft YaHei',sans-serif;}",
            "main{max-width:1120px;margin:0 auto;padding:28px 20px 44px;}",
            "header{margin-bottom:18px;} h1{font-size:28px;margin:0 0 8px;} h2{font-size:18px;margin:0 0 12px;}",
            ".muted{color:#64748b;} .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0;}",
            ".card,.chart-panel,.table-panel{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:16px;box-shadow:0 1px 2px rgba(15,23,42,.04);}",
            ".card .label{font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.04em}.card .value{font-size:24px;font-weight:700;margin-top:6px;}",
            ".chart-grid{display:grid;grid-template-columns:1fr;gap:14px}.svg-bg{fill:#fff}.grid{stroke:#e2e8f0;stroke-width:1}.axis{stroke:#94a3b8;stroke-width:1}.axis-label,.legend{fill:#475569;font-size:12px}",
            "table{width:100%;border-collapse:collapse;font-size:14px}th,td{border-bottom:1px solid #e2e8f0;padding:8px 10px;text-align:right}th:first-child,td:first-child{text-align:left}th{color:#475569;background:#f8fafc}",
            ".note{font-size:13px;line-height:1.55;color:#475569;margin-top:14px}",
            "</style>",
            "</head>",
            "<body><main>",
            "<header>",
            "<h1>V7.6 Portfolio Scenario Visual Report</h1>",
            f'<div class="muted">Active dynamic budget default: <code>{ACTIVE_DYNAMIC_BUDGET_SCENARIO}</code>. Comparison scenarios: <code>{ADVISORY_SCENARIO}</code> and <code>{STACKED_ADVISORY_SCENARIO}</code>. Fixed 10/15/15/20/40 remains the benchmark. Data through {latest_date}.</div>',
            "</header>",
            '<section class="cards">',
            f'<div class="card"><div class="label">Full Annual Delta</div><div class="value">{_pct(float(advisory_full["annual_return"] - fixed_full["annual_return"]))}</div></div>',
            f'<div class="card"><div class="label">Sub-A Annual Delta</div><div class="value">{_pct(float(suba_full["annual_return"] - fixed_full["annual_return"]))}</div></div>',
            f'<div class="card"><div class="label">Stacked Annual Delta</div><div class="value">{_pct(float(stacked_full["annual_return"] - fixed_full["annual_return"]))}</div></div>',
            f'<div class="card"><div class="label">Sub-A Full Sharpe</div><div class="value">{float(suba_full["sharpe"]):.2f}</div></div>',
            f'<div class="card"><div class="label">Stacked Full Sharpe</div><div class="value">{float(stacked_full["sharpe"]):.2f}</div></div>',
            f'<div class="card"><div class="label">Sub-A 1Y Annual</div><div class="value">{_pct(float(suba_1y["annual_return"]))}</div></div>',
            f'<div class="card"><div class="label">Stacked 1Y Annual</div><div class="value">{_pct(float(stacked_1y["annual_return"]))}</div></div>',
            f'<div class="card"><div class="label">Sub-A Excess NAV</div><div class="value">{_pct(float(latest["suba_advisory_excess_nav"]))}</div></div>',
            f'<div class="card"><div class="label">Stacked Excess NAV</div><div class="value">{_pct(float(latest["stacked_advisory_excess_nav"]))}</div></div>',
            f'<div class="card"><div class="label">Sub-A Advisory</div><div class="value">{_pct(float(latest["suba_advisory_suba_weight"]))}</div></div>',
            f'<div class="card"><div class="label">Stacked Sub-A</div><div class="value">{_pct(float(latest["stacked_advisory_suba_weight"]))}</div></div>',
            f'<div class="card"><div class="label">Stacked Microcap</div><div class="value">{_pct(float(latest["stacked_advisory_microcap_weight"]))}</div></div>',
            f'<div class="card"><div class="label">Stacked Sub-B</div><div class="value">{_pct(float(latest["stacked_advisory_subb_weight"]))}</div></div>',
            "</section>",
            '<section class="chart-grid">',
            nav_chart,
            dd_chart,
            excess_chart,
            weight_chart,
            "</section>",
            '<section class="table-panel">',
            "<h2>Window Metrics</h2>",
            _metric_table_html(scenario_metrics),
            '<p class="note">The active portfolio-level dynamic budget is stacked Sub-A 5/8 weekly + Microcap 3/10 month-end with Sub-B absorbing both deltas. Sub-A-only and Microcap-only remain comparison scenarios. Fixed 10/15/15/20/40 is retained as the benchmark and rollback line.</p>',
            "</section>",
            "</main></body></html>",
        ]
    )


def write_outputs(
    manifest: PortfolioManifest,
    ret_df: pd.DataFrame,
    nav_df: pd.DataFrame,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    returns_source: str | Path = DEFAULT_RETURNS,
) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    metrics = build_window_metrics(nav_df)
    scenario_nav, scenario_metrics, scenario_weights = build_scenario_outputs(ret_df, manifest.weights)
    advisory_weights = scenario_weights[ADVISORY_SCENARIO]
    suba_advisory_weights = scenario_weights[SUBA_ADVISORY_SCENARIO]
    stacked_weights = scenario_weights[STACKED_ADVISORY_SCENARIO]
    economic_curve = build_scenario_economic_curve(scenario_nav, scenario_weights)
    decision_summary = format_scenario_decision_summary(scenario_metrics, economic_curve)
    visual_report = render_scenario_visual_report(scenario_metrics, economic_curve)
    dynamic_budget_scan = build_dynamic_sleeve_budget_scan(ret_df, manifest.weights)
    dynamic_budget_summary = format_dynamic_sleeve_budget_summary(dynamic_budget_scan)
    ret_df.to_csv(out / "aligned_sleeve_returns.csv", index_label="date", encoding="utf-8-sig")
    nav_df.to_csv(out / "portfolio_nav.csv", index_label="date", encoding="utf-8-sig")
    metrics.to_csv(out / "window_metrics.csv", index=False, encoding="utf-8-sig")
    scenario_nav.to_csv(out / "scenario_nav.csv", index_label="date", encoding="utf-8-sig")
    scenario_metrics.to_csv(out / "scenario_window_metrics.csv", index=False, encoding="utf-8-sig")
    economic_curve.to_csv(out / "scenario_economic_curve.csv", index_label="date", encoding="utf-8-sig")
    (out / "scenario_decision_summary.md").write_text(decision_summary, encoding="utf-8")
    (out / "scenario_visual_report.html").write_text(visual_report, encoding="utf-8")
    dynamic_budget_scan.to_csv(out / "dynamic_sleeve_budget_scan.csv", index=False, encoding="utf-8-sig")
    (out / "dynamic_sleeve_budget_summary.md").write_text(dynamic_budget_summary, encoding="utf-8")
    advisory_weights.to_csv(
        out / "weights_advisory_dd_3_10_month_end.csv", index_label="date", encoding="utf-8-sig"
    )
    suba_advisory_weights.to_csv(
        out / "weights_advisory_suba_dd_5_8_weekly.csv",
        index_label="date",
        encoding="utf-8-sig",
    )
    stacked_weights.to_csv(
        out / "weights_active_dynamic_budget.csv",
        index_label="date",
        encoding="utf-8-sig",
    )
    stacked_weights.to_csv(
        out / "weights_advisory_suba_microcap_dd_3_10_month_end.csv",
        index_label="date",
        encoding="utf-8-sig",
    )
    meta = {
        "portfolio_id": manifest.portfolio_id,
        "manifest": output_path_metadata(manifest.path),
        "returns_source": output_path_metadata(returns_source),
        "start": nav_df.index[0].date().isoformat(),
        "end": nav_df.index[-1].date().isoformat(),
        "rows": int(len(nav_df)),
        "weights": manifest.weights,
        "active_dynamic_budget_scenario": ACTIVE_DYNAMIC_BUDGET_SCENARIO,
        "internal_sleeves": manifest.internal_sleeves,
        "external_sleeves": manifest.external_sleeves,
        "scenarios": {
            FIXED_SCENARIO: {
                "description": "Static five-sleeve baseline from manifest weights.",
            },
            ADVISORY_SCENARIO: {
                "description": "Microcap advisory risk budget: 20% when prior Microcap NAV DD is within 3%, 10% when prior DD is at or below -10%, otherwise 15%; month-end execution; Sub-B absorbs the delta.",
                "microcap_source": "Microcap v2.0 return_net from aligned returns",
                "execution": "month_end",
                "boost_dd": 0.03,
                "cut_dd": 0.10,
            },
            SUBA_ADVISORY_SCENARIO: {
                "description": "Sub-A advisory risk budget: 15% when prior Sub-A NAV DD is within 5%, 5% when prior DD is at or below -8%, otherwise 10%; weekly execution; Sub-B absorbs the delta.",
                "suba_source": "Sub-A return from aligned returns",
                "execution": "weekly",
                "boost_dd": 0.05,
                "cut_dd": 0.08,
                "active_dynamic_budget_default": False,
            },
            STACKED_ADVISORY_SCENARIO: {
                "description": "Stacked Sub-A + Microcap advisory risk budget: Sub-A uses 5/8 weekly, Microcap uses 3/10 month-end; each sleeve moves +/-5pp from base; Sub-B absorbs both deltas.",
                "suba_source": "Sub-A return from aligned returns",
                "microcap_source": "Microcap v2.0 return_net from aligned returns",
                "suba_execution": "weekly",
                "suba_boost_dd": 0.05,
                "suba_cut_dd": 0.08,
                "microcap_execution": "month_end",
                "microcap_boost_dd": 0.03,
                "microcap_cut_dd": 0.10,
                "active_dynamic_budget_default": True,
            },
        },
        "outputs": {
            "aligned_sleeve_returns": output_path_metadata(out / "aligned_sleeve_returns.csv"),
            "portfolio_nav": output_path_metadata(out / "portfolio_nav.csv"),
            "window_metrics": output_path_metadata(out / "window_metrics.csv"),
            "scenario_nav": output_path_metadata(out / "scenario_nav.csv"),
            "scenario_window_metrics": output_path_metadata(out / "scenario_window_metrics.csv"),
            "scenario_economic_curve": output_path_metadata(out / "scenario_economic_curve.csv"),
            "scenario_decision_summary": output_path_metadata(out / "scenario_decision_summary.md"),
            "scenario_visual_report": output_path_metadata(out / "scenario_visual_report.html"),
            "dynamic_sleeve_budget_scan": output_path_metadata(out / "dynamic_sleeve_budget_scan.csv"),
            "dynamic_sleeve_budget_summary": output_path_metadata(out / "dynamic_sleeve_budget_summary.md"),
            "advisory_weights": output_path_metadata(out / "weights_advisory_dd_3_10_month_end.csv"),
            "suba_advisory_weights": output_path_metadata(
                out / "weights_advisory_suba_dd_5_8_weekly.csv"
            ),
            "active_dynamic_budget_weights": output_path_metadata(
                out / "weights_active_dynamic_budget.csv"
            ),
            "stacked_advisory_weights": output_path_metadata(
                out / "weights_advisory_suba_microcap_dd_3_10_month_end.csv"
            ),
            "meta": output_path_metadata(out / "meta.json"),
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build V7.6 current five-sleeve portfolio NAV.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--returns", default=str(DEFAULT_RETURNS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = load_manifest(args.manifest)
    returns = load_aligned_returns(args.returns)
    nav = build_portfolio_nav(returns, manifest.weights)
    write_outputs(manifest, returns, nav, args.output_dir, args.returns)
    metrics = build_window_metrics(nav)
    _, scenario_metrics, _ = build_scenario_outputs(returns, manifest.weights)
    print(metrics.to_string(index=False))
    print()
    print(scenario_metrics.to_string(index=False))
    print(f"WROTE {Path(args.output_dir) / 'portfolio_nav.csv'}")
    print(f"WROTE {Path(args.output_dir) / 'window_metrics.csv'}")
    print(f"WROTE {Path(args.output_dir) / 'scenario_nav.csv'}")
    print(f"WROTE {Path(args.output_dir) / 'scenario_window_metrics.csv'}")
    print(f"WROTE {Path(args.output_dir) / 'scenario_economic_curve.csv'}")
    print(f"WROTE {Path(args.output_dir) / 'scenario_decision_summary.md'}")
    print(f"WROTE {Path(args.output_dir) / 'scenario_visual_report.html'}")
    print(f"WROTE {Path(args.output_dir) / 'dynamic_sleeve_budget_scan.csv'}")
    print(f"WROTE {Path(args.output_dir) / 'dynamic_sleeve_budget_summary.md'}")
    print(f"WROTE {Path(args.output_dir) / 'weights_advisory_dd_3_10_month_end.csv'}")
    print(f"WROTE {Path(args.output_dir) / 'weights_advisory_suba_dd_5_8_weekly.csv'}")
    print(f"WROTE {Path(args.output_dir) / 'weights_active_dynamic_budget.csv'}")
    print(f"WROTE {Path(args.output_dir) / 'weights_advisory_suba_microcap_dd_3_10_month_end.csv'}")


if __name__ == "__main__":
    main()

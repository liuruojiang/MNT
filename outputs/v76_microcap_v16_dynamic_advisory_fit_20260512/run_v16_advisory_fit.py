from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MICROCAP_V16 = (
    ROOT.parent
    / "微盘股对冲策略"
    / "outputs"
    / "microcap_top100_mom16_targetvol25_max1p5_v1_6_costed_nav.csv"
)
OUT_DIR = Path(__file__).resolve().parent

BOOST_DD = 0.03
CUT_DD = 0.10
BASE_WEIGHTS = {"Sub-A": 0.10, "Sub-A-DK": 0.15, "Microcap": 0.15, "Sub-B": 0.60}


def dd_target(prior_dd: float) -> float:
    if prior_dd >= -BOOST_DD:
        return 0.20
    if prior_dd <= -CUT_DD:
        return 0.10
    return 0.15


def month_end_execution_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    current_period = pd.Series(index.to_period("M"), index=index)
    next_index = pd.Series(index, index=index).shift(-1)
    next_period = pd.Series(next_index.dt.to_period("M").values, index=index)
    return pd.DatetimeIndex(index[next_period.notna() & (current_period != next_period)])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(MICROCAP_V16, parse_dates=["date"]).sort_values("date").set_index("date")
    ret = pd.to_numeric(df["return_net"], errors="coerce").dropna()
    nav = (1.0 + ret).cumprod()
    peak = nav.cummax()
    drawdown = nav / peak - 1.0
    prior_dd = nav.shift(1) / peak.shift(1) - 1.0
    daily_target = prior_dd.apply(lambda x: 0.15 if pd.isna(x) else dd_target(float(x)))

    exec_dates = month_end_execution_dates(ret.index)
    executed = pd.Series(index=ret.index, dtype=float)
    executed.loc[exec_dates] = daily_target.loc[exec_dates]
    executed.iloc[0] = 0.15
    executed = executed.ffill().fillna(0.15)

    latest_date = ret.index[-1]
    last_exec = exec_dates[exec_dates <= latest_date][-1]
    current_micro = float(executed.loc[latest_date])
    advisory = BASE_WEIGHTS.copy()
    advisory["Microcap"] = current_micro
    advisory["Sub-B"] = 0.75 - current_micro

    daily_weights = BASE_WEIGHTS.copy()
    daily_weights["Microcap"] = float(daily_target.loc[latest_date])
    daily_weights["Sub-B"] = 0.75 - daily_weights["Microcap"]

    history = pd.DataFrame(
        {
            "return_net": ret,
            "microcap_nav": nav,
            "microcap_peak": peak,
            "microcap_drawdown": drawdown,
            "prior_drawdown_for_signal": prior_dd,
            "daily_signal_microcap_weight": daily_target,
            "month_end_executed_microcap_weight": executed,
        }
    )
    summary = {
        "rule": "dd_3_10_month_end",
        "microcap_version": "v1.6",
        "source": str(MICROCAP_V16),
        "return_column": "return_net",
        "latest_date": latest_date.date().isoformat(),
        "latest_microcap_nav": float(nav.iloc[-1]),
        "latest_microcap_peak": float(peak.iloc[-1]),
        "latest_microcap_drawdown": float(drawdown.iloc[-1]),
        "latest_prior_drawdown_for_signal": float(prior_dd.loc[latest_date]),
        "latest_daily_signal_microcap_weight": float(daily_target.loc[latest_date]),
        "last_month_end_execution_date": last_exec.date().isoformat(),
        "last_month_end_signal_microcap_weight": float(daily_target.loc[last_exec]),
        "current_executed_month_end_microcap_weight": current_micro,
        "current_advisory_combo_weights": advisory,
        "latest_daily_recommendation_combo_weights": daily_weights,
        "implementation_fit": {
            "existing_v76_loader_corrected_to_v1_6": True,
            "should_use_v1_6_for_current_mainline": True,
            "requires_microcap_internal_change": False,
            "recommended_integration": "advisory display only; production COMBINED_WEIGHTS remains unchanged",
        },
    }
    history.to_csv(OUT_DIR / "microcap_v16_advisory_history.csv", index_label="date", encoding="utf-8-sig")
    (OUT_DIR / "advisory_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# V7.6 Microcap V1.6 Dynamic Advisory Fit Check",
        "",
        f"- Rule: `{summary['rule']}`",
        "- Microcap source version: `v1.6`",
        f"- Latest date: `{summary['latest_date']}`",
        f"- Latest Microcap drawdown: `{summary['latest_microcap_drawdown']:.2%}`",
        f"- Prior drawdown used for latest daily signal: `{summary['latest_prior_drawdown_for_signal']:.2%}`",
        f"- Latest daily signal Microcap weight: `{summary['latest_daily_signal_microcap_weight']:.0%}`",
        f"- Last month-end execution date: `{summary['last_month_end_execution_date']}`",
        f"- Current executed month-end Microcap weight: `{summary['current_executed_month_end_microcap_weight']:.0%}`",
        "",
        "## Current Advisory Combo Weights",
        "",
        "| Sleeve | Advisory weight |",
        "|---|---:|",
    ]
    for name, weight in advisory.items():
        lines.append(f"| {name} | {weight:.0%} |")
    lines.extend(
        [
            "",
            "## Implementation Fit",
            "",
            "- Use v1.6 as the current mainline Microcap source.",
            "- V7.6 loader has been corrected to v1.6 for the current mainline source.",
            "- No Microcap v1.6 internal change is required.",
            "- Do not change production `COMBINED_WEIGHTS` yet.",
        ]
    )
    (OUT_DIR / "advisory_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

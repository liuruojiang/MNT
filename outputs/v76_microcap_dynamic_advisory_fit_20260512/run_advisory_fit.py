from __future__ import annotations

import builtins
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "mnt_bot V 7.6 plus.py"
OUT_DIR = Path(__file__).resolve().parent

BOOST_DD = 0.05
CUT_DD = 0.12
BASE_WEIGHTS = {"Sub-A": 0.10, "Sub-A-DK": 0.15, "Microcap": 0.15, "Sub-B": 0.60}


class NullMessage:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, value) -> None:
        self.lines.append(str(value))


class PoeStub:
    class BotError(RuntimeError):
        pass

    query = SimpleNamespace(text="", attachments=[])
    default_chat = []

    @staticmethod
    def update_settings(_settings):
        return None


def load_module():
    builtins.poe = PoeStub()
    spec = importlib.util.spec_from_file_location("mnt_bot_v76_microcap_advisory_fit", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    module.poe = PoeStub()
    spec.loader.exec_module(module)
    return module


def dd_target(prior_dd: float) -> float:
    if prior_dd >= -BOOST_DD:
        return 0.20
    if prior_dd <= -CUT_DD:
        return 0.10
    return 0.15


def execution_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    periods = pd.Series(index.to_period("M"), index=index)
    next_periods = pd.Series(pd.Series(index, index=index).shift(-1).dt.to_period("M").values, index=index)
    return pd.DatetimeIndex(index[next_periods.notna() & (periods != next_periods)])


def build_advisory(ret: pd.Series) -> tuple[dict[str, object], pd.DataFrame]:
    ret = pd.to_numeric(ret, errors="coerce").dropna().sort_index()
    nav = (1.0 + ret).cumprod()
    peak = nav.cummax()
    prior_nav = nav.shift(1)
    prior_peak = peak.shift(1)
    prior_dd = prior_nav / prior_peak - 1.0
    daily_target = prior_dd.apply(lambda x: 0.15 if pd.isna(x) else dd_target(float(x)))

    exec_dates = execution_dates(ret.index)
    executed = pd.Series(index=ret.index, dtype=float)
    executed.loc[exec_dates] = daily_target.loc[exec_dates]
    executed.iloc[0] = 0.15
    executed = executed.ffill().fillna(0.15)

    latest_date = ret.index[-1]
    latest_dd = float(nav.iloc[-1] / peak.iloc[-1] - 1.0)
    latest_prior_dd = float(prior_dd.loc[latest_date])
    latest_daily_target = float(daily_target.loc[latest_date])
    current_month_end_target = float(executed.loc[latest_date])
    last_execution_date = exec_dates[exec_dates <= latest_date][-1]
    last_execution_target = float(daily_target.loc[last_execution_date])

    target_weights = BASE_WEIGHTS.copy()
    target_weights["Microcap"] = current_month_end_target
    target_weights["Sub-B"] = 0.75 - current_month_end_target

    daily_recommendation_weights = BASE_WEIGHTS.copy()
    daily_recommendation_weights["Microcap"] = latest_daily_target
    daily_recommendation_weights["Sub-B"] = 0.75 - latest_daily_target

    history = pd.DataFrame(
        {
            "return_net": ret,
            "microcap_nav": nav,
            "microcap_peak": peak,
            "microcap_drawdown": nav / peak - 1.0,
            "prior_drawdown_for_signal": prior_dd,
            "daily_signal_microcap_weight": daily_target,
            "month_end_executed_microcap_weight": executed,
        }
    )
    summary = {
        "rule": "dd_5_12_month_end",
        "source": "official V7.6 _load_microcap_daily_ret() reading Microcap v1.8 costed return_net",
        "boost_rule": f"20% Microcap if prior Microcap NAV drawdown is within {BOOST_DD:.0%}",
        "cut_rule": f"10% Microcap if prior Microcap NAV drawdown is worse than {CUT_DD:.0%}",
        "neutral_rule": "15% Microcap otherwise",
        "execution_rule": "month-end only; Sub-B absorbs the difference",
        "latest_date": latest_date.date().isoformat(),
        "latest_microcap_nav": float(nav.iloc[-1]),
        "latest_microcap_peak": float(peak.iloc[-1]),
        "latest_microcap_drawdown": latest_dd,
        "latest_prior_drawdown_for_signal": latest_prior_dd,
        "latest_daily_signal_microcap_weight": latest_daily_target,
        "last_month_end_execution_date": last_execution_date.date().isoformat(),
        "last_month_end_signal_microcap_weight": last_execution_target,
        "current_executed_month_end_microcap_weight": current_month_end_target,
        "current_advisory_combo_weights": target_weights,
        "latest_daily_recommendation_combo_weights": daily_recommendation_weights,
        "implementation_fit": {
            "can_compute_from_existing_v76_loader": True,
            "requires_microcap_internal_change": False,
            "recommended_integration": "advisory display only before production default",
            "display_locations": [
                "parameters/combo weight section",
                "live parameters combo weight section",
            ],
            "do_not_change": [
                "COMBINED_WEIGHTS production default",
                "PERFORMANCE_COMBO_ORDER no-microcap performance query",
                "Microcap v1.8 standalone strategy internals",
            ],
        },
    }
    return summary, history


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    module = load_module()
    msg = NullMessage()
    ret = module._load_microcap_daily_ret(msg=msg)
    summary, history = build_advisory(ret)
    history.to_csv(OUT_DIR / "microcap_advisory_history.csv", index_label="date", encoding="utf-8-sig")
    (OUT_DIR / "advisory_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# V7.6 Microcap Dynamic Advisory Fit Check",
        "",
        f"- Rule: `{summary['rule']}`",
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
    for name, weight in summary["current_advisory_combo_weights"].items():
        lines.append(f"| {name} | {weight:.0%} |")
    lines.extend(
        [
            "",
            "## Implementation Fit",
            "",
            "- Existing V7.6 Microcap loader is enough to compute the rule.",
            "- No Microcap v1.8 internal source change is required.",
            "- Treat this as advisory display first; do not change production `COMBINED_WEIGHTS` yet.",
            "- Keep the no-microcap performance query unchanged unless a separate full-combo PV query is built.",
        ]
    )
    (OUT_DIR / "advisory_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

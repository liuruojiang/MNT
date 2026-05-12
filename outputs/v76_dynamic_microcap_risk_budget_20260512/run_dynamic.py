from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
FOUR_SLEEVE_RUN = ROOT / "outputs" / "v76_four_sleeve_weight_check_20260512" / "run_compare.py"
OUT_DIR = Path(__file__).resolve().parent

WINDOWS = {
    "full": None,
    "10Y": pd.DateOffset(years=10),
    "5Y": pd.DateOffset(years=5),
    "3Y": pd.DateOffset(years=3),
    "1Y": pd.DateOffset(years=1),
}

FIXED_CURRENT = {"Sub-A": 0.10, "Sub-A-DK": 0.15, "Microcap": 0.15, "Sub-B": 0.60}
FIXED_HIGHER_MICROCAP = {"Sub-A": 0.10, "Sub-A-DK": 0.15, "Microcap": 0.20, "Sub-B": 0.55}


def load_four_sleeve_module():
    spec = importlib.util.spec_from_file_location("v76_four_sleeve_run_compare", FOUR_SLEEVE_RUN)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {FOUR_SLEEVE_RUN}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def align_returns(daily_returns: dict[str, pd.Series]) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    common_start = max(series.index[0] for series in daily_returns.values())
    common_end = min(series.index[-1] for series in daily_returns.values())
    all_dates = pd.DatetimeIndex(sorted(set().union(*(s.loc[(s.index >= common_start) & (s.index <= common_end)].index for s in daily_returns.values()))))
    ret_df = pd.DataFrame(
        {
            name: pd.to_numeric(series, errors="coerce").reindex(all_dates).fillna(0.0)
            for name, series in daily_returns.items()
        }
    )
    return ret_df, common_start, common_end


def fixed_weights(index: pd.DatetimeIndex, weights: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame({name: float(value) for name, value in weights.items()}, index=index)


def dynamic_weights(ret_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    micro_nav = (1.0 + ret_df["Microcap"]).cumprod()
    prev_nav = micro_nav.shift(1)
    prev_peak = micro_nav.cummax().shift(1)
    prev_dd = prev_nav / prev_peak - 1.0
    prev_ma126 = micro_nav.rolling(126, min_periods=60).mean().shift(1)

    near_high_5 = (prev_dd >= -0.05).fillna(False)
    near_high_10 = (prev_dd >= -0.10).fillna(False)
    above_ma126 = (prev_nav > prev_ma126).fillna(False)

    scenarios: dict[str, pd.Series] = {
        "dyn_microcap_20_if_dd_le_5": pd.Series(np.where(near_high_5, 0.20, 0.15), index=ret_df.index),
        "dyn_microcap_20_if_above_ma126": pd.Series(np.where(above_ma126, 0.20, 0.15), index=ret_df.index),
        "dyn_microcap_20_if_above_ma126_and_dd_le_10": pd.Series(
            np.where(above_ma126 & near_high_10, 0.20, 0.15),
            index=ret_df.index,
        ),
        "dyn_microcap_10_15_20_by_dd_5_10": pd.Series(
            np.select([near_high_5, prev_dd <= -0.10], [0.20, 0.10], default=0.15),
            index=ret_df.index,
        ),
    }

    out: dict[str, pd.DataFrame] = {}
    for name, micro_weight in scenarios.items():
        w = fixed_weights(ret_df.index, FIXED_CURRENT)
        w["Microcap"] = micro_weight.astype(float)
        w["Sub-B"] = 0.75 - w["Microcap"]
        out[name] = w
    return out


def nav_from_weights(ret_df: pd.DataFrame, weights: pd.DataFrame) -> pd.Series:
    weights = weights.reindex(ret_df.index).ffill()
    daily = (ret_df * weights[ret_df.columns]).sum(axis=1)
    nav = (1.0 + daily).cumprod()
    return nav / nav.iloc[0]


def underwater_stats(nav: pd.Series) -> dict[str, object]:
    nav = nav.dropna()
    in_dd = nav < nav.cummax()
    max_closed_days = 0
    current_start = None
    for dt, underwater in in_dd.items():
        if underwater and current_start is None:
            current_start = dt
        elif not underwater and current_start is not None:
            max_closed_days = max(max_closed_days, int((dt - current_start).days))
            current_start = None
    return {
        "max_closed_underwater_days": max_closed_days,
        "open_underwater_days": int((nav.index[-1] - current_start).days) if current_start is not None else 0,
        "is_currently_underwater": bool(current_start is not None),
    }


def summarize(nav: pd.Series, window_name: str, offset: pd.DateOffset | None) -> dict[str, object]:
    nav = nav.dropna()
    part = nav.copy() if offset is None else nav.loc[nav.index >= nav.index[-1] - offset].copy()
    part = part / part.iloc[0]
    daily_ret = part.pct_change().dropna()
    years = (part.index[-1] - part.index[0]).days / 365.25
    annual_return = part.iloc[-1] ** (1.0 / years) - 1.0
    max_dd = (part / part.cummax() - 1.0).min()
    vol = daily_ret.std() * np.sqrt(252.0)
    return {
        "window": window_name,
        "start": part.index[0].date().isoformat(),
        "end": part.index[-1].date().isoformat(),
        "rows": int(len(part)),
        "annual_return": float(annual_return),
        "max_drawdown": float(max_dd),
        "sharpe": float(annual_return / vol) if vol and vol > 0 else np.nan,
        "total_return": float(part.iloc[-1] - 1.0),
        **underwater_stats(part),
    }


def weight_stats(weights: pd.DataFrame) -> dict[str, object]:
    micro = weights["Microcap"]
    return {
        "avg_microcap_weight": float(micro.mean()),
        "min_microcap_weight": float(micro.min()),
        "max_microcap_weight": float(micro.max()),
        "days_microcap_20": int((micro >= 0.199999).sum()),
        "days_microcap_15": int(((micro > 0.100001) & (micro < 0.199999)).sum()),
        "days_microcap_10": int((micro <= 0.100001).sum()),
        "last_microcap_weight": float(micro.iloc[-1]),
        "weight_change_count": int((micro.diff().abs() > 1e-12).sum()),
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    four = load_four_sleeve_module()
    mod = four.load_module()
    daily_returns, audit = four.run_v76_sleeves(mod)
    ret_df, common_start, common_end = align_returns(daily_returns)

    weights_by_name = {
        "fixed_rebalanced_10_15_15_60": fixed_weights(ret_df.index, FIXED_CURRENT),
        "fixed_rebalanced_10_15_20_55": fixed_weights(ret_df.index, FIXED_HIGHER_MICROCAP),
        **dynamic_weights(ret_df),
    }

    rows = []
    weight_rows = []
    for name, weights in weights_by_name.items():
        nav = nav_from_weights(ret_df, weights)
        pd.DataFrame({"date": nav.index, "nav": nav.values}).to_csv(
            OUT_DIR / f"daily_{name}.csv",
            index=False,
            encoding="utf-8-sig",
        )
        weights.to_csv(OUT_DIR / f"weights_{name}.csv", index_label="date", encoding="utf-8-sig")
        weight_rows.append({"scenario": name, **weight_stats(weights)})
        for window_name, offset in WINDOWS.items():
            rows.append({"scenario": name, **summarize(nav, window_name, offset)})

    summary = pd.DataFrame(rows)
    base = summary[summary["scenario"] == "fixed_rebalanced_10_15_15_60"].set_index("window")
    for idx, row in summary.iterrows():
        b = base.loc[row["window"]]
        summary.loc[idx, "annual_return_delta_vs_current_rebalanced"] = row["annual_return"] - b["annual_return"]
        summary.loc[idx, "max_drawdown_delta_vs_current_rebalanced"] = row["max_drawdown"] - b["max_drawdown"]
        summary.loc[idx, "sharpe_delta_vs_current_rebalanced"] = row["sharpe"] - b["sharpe"]
    summary.to_csv(OUT_DIR / "summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(weight_rows).to_csv(OUT_DIR / "weight_stats.csv", index=False, encoding="utf-8-sig")
    ret_df.to_csv(OUT_DIR / "aligned_sleeve_returns.csv", index_label="date", encoding="utf-8-sig")

    audit.update(
        {
            "classification": "V7.6 dynamic microcap risk-budget check",
            "common_start": common_start.date().isoformat(),
            "common_end": common_end.date().isoformat(),
            "weight_semantics": "daily sleeve returns; weights for date t are determined by information through t-1 for dynamic rules",
            "cost_note": "sleeve returns are net/costed where the source sleeve provides net returns; inter-sleeve allocation turnover cost is not modeled",
            "baseline": "fixed_rebalanced_10_15_15_60",
            "fixed_current": FIXED_CURRENT,
            "fixed_higher_microcap": FIXED_HIGHER_MICROCAP,
            "rules": {
                "dyn_microcap_20_if_dd_le_5": "Microcap 20% if prior Microcap NAV drawdown is within 5%; otherwise 15%; Sub-B absorbs the difference.",
                "dyn_microcap_20_if_above_ma126": "Microcap 20% if prior Microcap NAV is above prior 126-day moving average; otherwise 15%; Sub-B absorbs the difference.",
                "dyn_microcap_20_if_above_ma126_and_dd_le_10": "Microcap 20% only if prior NAV is above prior 126-day MA and within 10% drawdown; otherwise 15%; Sub-B absorbs the difference.",
                "dyn_microcap_10_15_20_by_dd_5_10": "Microcap 20% if prior drawdown is within 5%, 10% if prior drawdown is worse than 10%, otherwise 15%; Sub-B absorbs the difference.",
            },
            "source_four_sleeve_script": str(FOUR_SLEEVE_RUN),
        }
    )
    (OUT_DIR / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary.to_string(index=False))
    print(pd.DataFrame(weight_rows).to_string(index=False))


if __name__ == "__main__":
    main()

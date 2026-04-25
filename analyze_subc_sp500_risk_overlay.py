"""Sub-C S&P 500 risk-regime overlay research.

This standalone helper reuses the real Sub-C production functions from
``mnt_bot V 7.0 plus.py`` and tests how the S&P 500 risk-regime budget would
have changed Sub-C performance. It does not modify production strategy logic.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
STRATEGY_FILE = ROOT / "mnt_bot V 7.0 plus.py"
US_DATA_FILE = ROOT / "mnt_strategy_data_us.csv"
RISK_FILE = ROOT.parent / "新策略学习" / "sp500_risk_regime_video_aligned_baa10y_output.csv"
OUT_DIR = ROOT / "docs" / "subc_sp500_risk_overlay_20260423"
GROWTH_ASSETS = {"VTI", "QQQ", "VEA", "BTC-USD"}
PRESSURE_WINDOWS = {
    "2020_crash": ("2020-02-19", "2020-03-23"),
    "2022_bear": ("2022-01-03", "2022-10-14"),
    "2025_tariff": ("2025-02-14", "2025-04-17"),
    "since_2021": ("2021-01-01", "2026-04-17"),
}


def _install_poe_stubs() -> None:
    if "fastapi_poe" not in sys.modules:
        fastapi_poe = types.ModuleType("fastapi_poe")
        fastapi_poe_types = types.ModuleType("fastapi_poe.types")

        class SettingsResponse:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        fastapi_poe_types.SettingsResponse = SettingsResponse
        fastapi_poe.types = fastapi_poe_types
        sys.modules["fastapi_poe"] = fastapi_poe
        sys.modules["fastapi_poe.types"] = fastapi_poe_types


def load_strategy_namespace() -> dict:
    _install_poe_stubs()

    class BotError(Exception):
        pass

    class _NullMessage:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def write(self, *_args, **_kwargs):
            return None

        def attach_file(self, *_args, **_kwargs):
            return None

    poe_stub = types.SimpleNamespace(
        BotError=BotError,
        start_message=lambda: _NullMessage(),
        update_settings=lambda *_args, **_kwargs: None,
        default_chat="",
        query=types.SimpleNamespace(text="", attachments=[]),
        call=lambda *_args, **_kwargs: "",
    )
    ns = {"__name__": "mnt_bot_v70_subc_overlay_loaded", "poe": poe_stub}
    exec(compile(STRATEGY_FILE.read_text(encoding="utf-8", errors="replace"), str(STRATEGY_FILE), "exec"), ns)
    return ns


def build_us_prod_daily(ns: dict) -> pd.DataFrame:
    wide = pd.read_csv(US_DATA_FILE, parse_dates=["date"]).set_index("date")
    wide = wide.apply(pd.to_numeric, errors="coerce")
    prod_portfolio = ns["PROD_PORTFOLIO"]
    prod_cash = ns["PROD_CASH"]
    prod_proxies = list({cfg["proxy"] for cfg in prod_portfolio.values()} | {prod_cash})
    late_prod = {"BTC-USD", "DBMF"}
    core = [t for t in prod_proxies if t not in late_prod and t in wide.columns]
    us_prod_daily = pd.concat([wide[t].rename(t) for t in core], axis=1).ffill().dropna()
    for ticker in late_prod:
        if ticker in wide.columns:
            us_prod_daily = us_prod_daily.join(wide[ticker].rename(ticker), how="left")
    stock_prod = [t for t in prod_proxies if t in wide.columns and t != "BTC-USD"]
    if stock_prod:
        last_stock_date = max(wide[t].dropna().index[-1] for t in stock_prod if wide[t].notna().any())
        us_prod_daily = us_prod_daily.loc[:last_stock_date]
    for live_ticker in prod_portfolio.keys():
        if live_ticker in wide.columns and live_ticker not in us_prod_daily.columns:
            us_prod_daily[live_ticker] = wide[live_ticker].reindex(us_prod_daily.index)
    return us_prod_daily


def build_subc_signals(ns: dict, us_prod_daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    prod_monthly = us_prod_daily.resample("M").last()
    last_daily = us_prod_daily.index[-1]
    today_period = pd.Timestamp("2026-04-23").to_period("M")
    if last_daily.to_period("M") == prod_monthly.index[-1].to_period("M") == today_period:
        prod_monthly = prod_monthly.iloc[:-1]
    prod_sig_a = ns["make_abs_mom_signals"](prod_monthly, ns["PROD_ABS_MOM_LB"])
    prod_sig_b = ns["make_sma_signals"](prod_monthly, ns["PROD_SMA_WINDOW"], ns["PROD_SMA_BAND"])
    if not ns["PROD_USE_TIMING"]:
        prod_sig_a = pd.DataFrame(1.0, index=prod_sig_a.index, columns=prod_sig_a.columns)
        prod_sig_b = prod_sig_a.copy()
    return prod_sig_a, prod_sig_b


def phase_portfolio(ns: dict, date: pd.Timestamp) -> dict:
    if date < ns["DBMF_BT_START"]:
        return ns["PROD_PORTFOLIO_PRE_DBMF"]
    if date < ns["BTC_BT_START"]:
        return ns["PROD_PORTFOLIO_BT"]
    return ns["PROD_PORTFOLIO"]


def read_risk_signal_frame() -> pd.DataFrame:
    return pd.read_csv(RISK_FILE, index_col=0, parse_dates=True, encoding="utf-8-sig").sort_index()


def read_risk_signal_budget(floor: float | None = None) -> pd.Series:
    risk = read_risk_signal_frame()
    budget = risk["suggested_equity_budget"].astype(str).str.rstrip("%").astype(float).div(100.0)
    if floor is not None:
        budget = budget.clip(lower=floor)
    return budget.sort_index()


def next_trading_day_after(daily_index: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | None:
    candidates = daily_index[daily_index > date]
    if len(candidates) == 0:
        return None
    return candidates[0]


def load_risk_budget(daily_index: pd.DatetimeIndex, floor: float | None = None, delay_days: int = 0) -> pd.Series:
    budget = read_risk_signal_budget(floor=floor)
    shifted = pd.Series(index=daily_index, dtype=float)
    for signal_date, value in budget.items():
        # Weekly Friday close signal becomes executable after the requested delay,
        # then on the next Sub-C trading day.
        execution_date = next_trading_day_after(daily_index, signal_date + pd.Timedelta(days=delay_days))
        if execution_date is not None:
            shifted.loc[execution_date] = value
    return shifted.ffill().reindex(daily_index).ffill().fillna(1.0)


def load_staged_down_budget(
    daily_index: pd.DatetimeIndex,
    floor: float | None = None,
    cumulative_cut_fractions: tuple[tuple[int, float], ...] = ((0, 0.20), (7, 0.50), (14, 1.0)),
) -> pd.Series:
    signal_budget = read_risk_signal_budget(floor=floor)
    signal_events: dict[pd.Timestamp, float] = {}
    for signal_date, value in signal_budget.items():
        execution_date = next_trading_day_after(daily_index, signal_date)
        if execution_date is not None:
            signal_events[execution_date] = float(value)

    current = 1.0
    pending: list[tuple[pd.Timestamp, float]] = []
    out = pd.Series(index=daily_index, dtype=float)
    for date in daily_index:
        if pending:
            due = [event for event in pending if event[0] <= date]
            pending = [event for event in pending if event[0] > date]
            if due:
                current = due[-1][1]

        if date in signal_events:
            target = signal_events[date]
            pending = []
            if target < current:
                start = current
                cut = start - target
                staged_values = []
                for delay_days, fraction in cumulative_cut_fractions:
                    stage_date = next_trading_day_after(daily_index, date + pd.Timedelta(days=delay_days))
                    if stage_date is not None:
                        staged_values.append((stage_date, start - cut * fraction))
                immediate = [event for event in staged_values if event[0] <= date]
                future = [event for event in staged_values if event[0] > date]
                if immediate:
                    current = immediate[-1][1]
                pending = future
            else:
                current = target

        out.loc[date] = current
    return out.ffill().fillna(1.0)


def load_regime_gate_budget(
    daily_index: pd.DatetimeIndex,
    active_regimes: set[str],
    delay_days: int = 0,
) -> pd.Series:
    risk = read_risk_signal_frame()
    base_budget = risk["suggested_equity_budget"].astype(str).str.rstrip("%").astype(float).div(100.0)
    regime = risk["regime"].astype(str)
    gated_budget = pd.Series(1.0, index=risk.index, dtype=float)
    gated_budget.loc[regime.isin(active_regimes)] = base_budget.loc[regime.isin(active_regimes)]
    shifted = pd.Series(index=daily_index, dtype=float)
    for signal_date, value in gated_budget.items():
        execution_date = next_trading_day_after(daily_index, signal_date + pd.Timedelta(days=delay_days))
        if execution_date is not None:
            shifted.loc[execution_date] = float(value)
    return shifted.ffill().reindex(daily_index).ffill().fillna(1.0)


def load_regime_fixed_budget(
    daily_index: pd.DatetimeIndex,
    active_regimes: set[str],
    active_budget: float,
    delay_days: int = 0,
) -> pd.Series:
    risk = read_risk_signal_frame()
    regime = risk["regime"].astype(str)
    gated_budget = pd.Series(1.0, index=risk.index, dtype=float)
    gated_budget.loc[regime.isin(active_regimes)] = float(active_budget)
    shifted = pd.Series(index=daily_index, dtype=float)
    for signal_date, value in gated_budget.items():
        execution_date = next_trading_day_after(daily_index, signal_date + pd.Timedelta(days=delay_days))
        if execution_date is not None:
            shifted.loc[execution_date] = float(value)
    return shifted.ffill().reindex(daily_index).ffill().fillna(1.0)


def load_regime_prefix_fixed_budget(
    daily_index: pd.DatetimeIndex,
    active_prefixes: set[str],
    active_budget: float,
    delay_days: int = 0,
) -> pd.Series:
    risk = read_risk_signal_frame()
    regime = risk["regime"].astype(str)
    active = pd.Series(False, index=risk.index)
    for prefix in active_prefixes:
        active = active | regime.str.startswith(f"{prefix}-")
    gated_budget = pd.Series(1.0, index=risk.index, dtype=float)
    gated_budget.loc[active] = float(active_budget)
    shifted = pd.Series(index=daily_index, dtype=float)
    for signal_date, value in gated_budget.items():
        execution_date = next_trading_day_after(daily_index, signal_date + pd.Timedelta(days=delay_days))
        if execution_date is not None:
            shifted.loc[execution_date] = float(value)
    return shifted.ffill().reindex(daily_index).ffill().fillna(1.0)


def load_regime_prefix_fixed_staged_budget(
    daily_index: pd.DatetimeIndex,
    active_prefixes: set[str],
    active_budget: float,
    cumulative_cut_fractions: tuple[tuple[int, float], ...] = ((0, 0.20), (7, 0.50), (14, 1.0)),
) -> pd.Series:
    risk = read_risk_signal_frame()
    regime = risk["regime"].astype(str)
    active = pd.Series(False, index=risk.index)
    for prefix in active_prefixes:
        active = active | regime.str.startswith(f"{prefix}-")
    signal_budget = pd.Series(1.0, index=risk.index, dtype=float)
    signal_budget.loc[active] = float(active_budget)

    signal_events: dict[pd.Timestamp, float] = {}
    for signal_date, value in signal_budget.items():
        execution_date = next_trading_day_after(daily_index, signal_date)
        if execution_date is not None:
            signal_events[execution_date] = float(value)

    current = 1.0
    pending: list[tuple[pd.Timestamp, float]] = []
    out = pd.Series(index=daily_index, dtype=float)
    for date in daily_index:
        if pending:
            due = [event for event in pending if event[0] <= date]
            pending = [event for event in pending if event[0] > date]
            if due:
                current = due[-1][1]

        if date in signal_events:
            target = signal_events[date]
            pending = []
            if target < current:
                start = current
                cut = start - target
                staged_values = []
                for delay_days, fraction in cumulative_cut_fractions:
                    stage_date = next_trading_day_after(daily_index, date + pd.Timedelta(days=delay_days))
                    if stage_date is not None:
                        staged_values.append((stage_date, start - cut * fraction))
                immediate = [event for event in staged_values if event[0] <= date]
                future = [event for event in staged_values if event[0] > date]
                if immediate:
                    current = immediate[-1][1]
                pending = future
            else:
                current = target

        out.loc[date] = current
    return out.ffill().fillna(1.0)


def daily_raw_overlay_return(
    ns: dict,
    us_prod_daily: pd.DataFrame,
    prod_sig_a: pd.DataFrame,
    prod_sig_b: pd.DataFrame,
    budget: pd.Series,
    capped_assets: set[str],
) -> pd.Series:
    daily_ret = us_prod_daily.pct_change().dropna(how="all")
    cash_daily = daily_ret[ns["PROD_CASH"]].fillna(0.0)
    out = pd.Series(0.0, index=daily_ret.index)
    prod_sig_a = prod_sig_a.copy()
    prod_sig_b = prod_sig_b.copy()
    sig_a_lookup = {idx.to_period("M"): row for idx, row in prod_sig_a.iterrows()}
    sig_b_lookup = {idx.to_period("M"): row for idx, row in prod_sig_b.iterrows()}
    budget = budget.reindex(daily_ret.index).ffill().fillna(1.0)
    for date in daily_ret.index:
        portfolio = phase_portfolio(ns, date)
        b = float(budget.loc[date])
        cash_weight = 0.0
        period = date.to_period("M")
        sig_a_row = sig_a_lookup.get(period)
        sig_b_row = sig_b_lookup.get(period)
        for name, cfg in portfolio.items():
            proxy = cfg["proxy"]
            if proxy not in daily_ret.columns:
                continue
            base_w = float(cfg["w"])
            cap_this = proxy in capped_assets or name in capped_assets
            eff_w = base_w * b if cap_this else base_w
            cash_weight += base_w - eff_w
            sig_a = 1.0
            sig_b = 1.0
            if sig_a_row is not None and proxy in sig_a_row.index and pd.notna(sig_a_row[proxy]):
                sig_a = float(sig_a_row[proxy])
            if sig_b_row is not None and proxy in sig_b_row.index and pd.notna(sig_b_row[proxy]):
                sig_b = float(sig_b_row[proxy])
            asset_daily = float(daily_ret.loc[date, proxy]) if pd.notna(daily_ret.loc[date, proxy]) else 0.0
            r_a = sig_a * asset_daily + (1.0 - sig_a) * float(cash_daily.loc[date])
            r_b = sig_b * asset_daily + (1.0 - sig_b) * float(cash_daily.loc[date])
            out.loc[date] += eff_w * (ns["PROD_BLEND_A"] * r_a + (1.0 - ns["PROD_BLEND_A"]) * r_b)
        out.loc[date] += cash_weight * float(cash_daily.loc[date])
    return out


def metrics(ret: pd.Series) -> dict[str, float]:
    ret = ret.dropna()
    nav = (1 + ret).cumprod()
    years = max((ret.index[-1] - ret.index[0]).days / 365.25, 1e-9)
    periods_per_year = len(ret) / years
    annual = nav.iloc[-1] ** (1 / years) - 1
    vol = ret.std(ddof=1) * np.sqrt(periods_per_year)
    sharpe = annual / vol if vol > 0 else np.nan
    dd = (nav / nav.cummax() - 1).min()
    return {
        "start": ret.index[0].strftime("%Y-%m-%d"),
        "end": ret.index[-1].strftime("%Y-%m-%d"),
        "years": years,
        "ann_return": annual,
        "ann_vol": vol,
        "sharpe": sharpe,
        "max_dd": dd,
        "final_nav": nav.iloc[-1],
        "calmar": annual / abs(dd) if dd < 0 else np.nan,
    }


def window_metrics(ret: pd.Series, start: str, end: str) -> dict[str, float]:
    r = ret.loc[start:end].dropna()
    if r.empty:
        return {"total_return": np.nan, "max_dd": np.nan}
    nav = (1 + r).cumprod()
    return {
        "total_return": nav.iloc[-1] - 1,
        "max_dd": (nav / nav.cummax() - 1).min(),
    }


def budget_metrics(budget: pd.Series) -> dict[str, float]:
    changes = budget.diff().abs().fillna(0.0)
    return {
        "min_budget": float(budget.min()),
        "avg_budget": float(budget.mean()),
        "days_below_70pct": float((budget < 0.70).mean()),
        "days_below_100pct": float((budget < 1.0).mean()),
        "budget_abs_change_sum": float(changes.sum()),
        "budget_change_days": float((changes > 1e-12).sum()),
    }


def main() -> int:
    ns = load_strategy_namespace()
    us_prod_daily = build_us_prod_daily(ns)
    prod_sig_a, prod_sig_b = build_subc_signals(ns, us_prod_daily)
    baseline = ns["_get_subc_daily_ret"](us_prod_daily, prod_sig_a, prod_sig_b=prod_sig_b)
    raw = ns["_compute_daily_subc_phased"](
        us_prod_daily,
        prod_sig_a,
        ns["PROD_CASH"],
        prod_sig_b=prod_sig_b,
        blend_a=ns["PROD_BLEND_A"],
    )
    scaled, _, _ = ns["_apply_subc_vol_scaling"](raw, us_prod_daily)
    parity = float((baseline - scaled).abs().max())
    if not np.isfinite(parity) or parity > 1e-12:
        raise RuntimeError(f"Sub-C parity failed: max_abs_diff={parity}")

    final_variants = {"baseline_subc": baseline}
    budget_summaries = []
    for floor in [None, 0.50, 0.60, 0.70, 0.80]:
        budget = load_risk_budget(baseline.index, floor=floor)
        name = "growth_original_map" if floor is None else f"growth_floor_{int(floor * 100)}"
        raw_ret = daily_raw_overlay_return(ns, us_prod_daily, prod_sig_a, prod_sig_b, budget, GROWTH_ASSETS)
        final_variants[name], _, _ = ns["_apply_subc_vol_scaling"](raw_ret, us_prod_daily)
        row = {"variant": name, "execution": "next_trading_day_after_signal"}
        row.update(budget_metrics(budget))
        budget_summaries.append(row)

    timing_variants = {
        "growth_floor_70_delay_1w": load_risk_budget(baseline.index, floor=0.70, delay_days=7),
        "growth_floor_70_delay_2w": load_risk_budget(baseline.index, floor=0.70, delay_days=14),
        "growth_floor_70_staged_20_30_50": load_staged_down_budget(baseline.index, floor=0.70),
        "growth_only_regime_3": load_regime_gate_budget(baseline.index, active_regimes={"3-困难模式"}),
        "growth_only_regime_4": load_regime_gate_budget(baseline.index, active_regimes={"4-噩梦模式"}),
        "growth_only_regime_6": load_regime_gate_budget(baseline.index, active_regimes={"6-炼狱模式"}),
        "growth_only_regime_5_6": load_regime_gate_budget(baseline.index, active_regimes={"5-地狱模式", "6-炼狱模式"}),
    }
    timing_variants.update(
        {
            "growth_regime_3_budget_90": load_regime_prefix_fixed_budget(
                baseline.index, active_prefixes={"3"}, active_budget=0.90
            ),
            "growth_regime_3_budget_80": load_regime_prefix_fixed_budget(
                baseline.index, active_prefixes={"3"}, active_budget=0.80
            ),
            "growth_regime_3_budget_70": load_regime_prefix_fixed_budget(
                baseline.index, active_prefixes={"3"}, active_budget=0.70
            ),
            "growth_regime_3_budget_60": load_regime_prefix_fixed_budget(
                baseline.index, active_prefixes={"3"}, active_budget=0.60
            ),
            "growth_regime_4_budget_80": load_regime_prefix_fixed_budget(
                baseline.index, active_prefixes={"4"}, active_budget=0.80
            ),
            "growth_regime_4_budget_70": load_regime_prefix_fixed_budget(
                baseline.index, active_prefixes={"4"}, active_budget=0.70
            ),
            "growth_regime_4_budget_60": load_regime_prefix_fixed_budget(
                baseline.index, active_prefixes={"4"}, active_budget=0.60
            ),
            "growth_regime_4_budget_50": load_regime_prefix_fixed_budget(
                baseline.index, active_prefixes={"4"}, active_budget=0.50
            ),
            "growth_regime_3_budget_90_staged": load_regime_prefix_fixed_staged_budget(
                baseline.index, active_prefixes={"3"}, active_budget=0.90
            ),
            "growth_regime_3_budget_80_staged": load_regime_prefix_fixed_staged_budget(
                baseline.index, active_prefixes={"3"}, active_budget=0.80
            ),
            "growth_regime_3_budget_70_staged": load_regime_prefix_fixed_staged_budget(
                baseline.index, active_prefixes={"3"}, active_budget=0.70
            ),
            "growth_regime_3_budget_60_staged": load_regime_prefix_fixed_staged_budget(
                baseline.index, active_prefixes={"3"}, active_budget=0.60
            ),
        }
    )
    timing_final_variants = {"baseline_subc": baseline, "growth_floor_70": final_variants["growth_floor_70"]}
    timing_budget_summaries = [
        {
            "variant": "growth_floor_70",
            "execution": "next_trading_day_after_signal",
            **budget_metrics(load_risk_budget(baseline.index, floor=0.70)),
        }
    ]
    for name, budget in timing_variants.items():
        raw_ret = daily_raw_overlay_return(ns, us_prod_daily, prod_sig_a, prod_sig_b, budget, GROWTH_ASSETS)
        final_variants[name], _, _ = ns["_apply_subc_vol_scaling"](raw_ret, us_prod_daily)
        timing_final_variants[name] = final_variants[name]
        if name.endswith("delay_1w"):
            execution = "full_budget_after_1_week"
        elif name.endswith("delay_2w"):
            execution = "full_budget_after_2_weeks"
        elif name.endswith("only_regime_3"):
            execution = "cut_only_when_regime_is_3"
        elif name.endswith("only_regime_4"):
            execution = "cut_only_when_regime_is_4"
        elif name.endswith("only_regime_6"):
            execution = "cut_only_when_regime_is_6"
        elif name.endswith("only_regime_5_6"):
            execution = "cut_only_when_regime_is_5_or_6"
        elif name.endswith("_staged"):
            execution = "staged_fixed_budget_only_when_regime_is_3"
        elif "regime_3_budget_" in name:
            execution = "fixed_budget_only_when_regime_is_3"
        elif "regime_4_budget_" in name:
            execution = "fixed_budget_only_when_regime_is_4"
        else:
            execution = "downside_only_staged_20_30_50pct_of_cut_over_0_1_2_weeks"
        row = {"variant": name, "execution": execution}
        row.update(budget_metrics(budget))
        timing_budget_summaries.append(row)

    rows = []
    for name, ret in final_variants.items():
        m = metrics(ret)
        m["variant"] = name
        rows.append(m)
    result = pd.DataFrame(rows).set_index("variant")
    for col in ["ann_return", "ann_vol", "sharpe", "max_dd", "final_nav", "calmar"]:
        result[col] = result[col].astype(float)
    budget_summary = pd.DataFrame(budget_summaries).set_index("variant")
    window_rows = []
    for name, ret in final_variants.items():
        row = {"variant": name}
        for win_name, (start, end) in PRESSURE_WINDOWS.items():
            wm = window_metrics(ret, start, end)
            row[f"{win_name}_total"] = wm["total_return"]
            row[f"{win_name}_max_dd"] = wm["max_dd"]
        window_rows.append(row)
    window_result = pd.DataFrame(window_rows).set_index("variant")

    timing_rows = []
    for name, ret in timing_final_variants.items():
        m = metrics(ret)
        m["variant"] = name
        timing_rows.append(m)
    timing_result = pd.DataFrame(timing_rows).set_index("variant")
    for col in ["ann_return", "ann_vol", "sharpe", "max_dd", "final_nav", "calmar"]:
        timing_result[col] = timing_result[col].astype(float)
    timing_budget_summary = pd.DataFrame(timing_budget_summaries).set_index("variant")
    timing_window_rows = []
    for name, ret in timing_final_variants.items():
        row = {"variant": name}
        for win_name, (start, end) in PRESSURE_WINDOWS.items():
            wm = window_metrics(ret, start, end)
            row[f"{win_name}_total"] = wm["total_return"]
            row[f"{win_name}_max_dd"] = wm["max_dd"]
        timing_window_rows.append(row)
    timing_window_result = pd.DataFrame(timing_window_rows).set_index("variant")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_DIR / "growth_floor_sweep_summary.csv", encoding="utf-8-sig")
    budget_summary.to_csv(OUT_DIR / "growth_floor_sweep_budget.csv", encoding="utf-8-sig")
    window_result.to_csv(OUT_DIR / "growth_floor_sweep_windows.csv", encoding="utf-8-sig")
    timing_result.to_csv(OUT_DIR / "growth_floor_70_execution_timing_summary.csv", encoding="utf-8-sig")
    timing_budget_summary.to_csv(OUT_DIR / "growth_floor_70_execution_timing_budget.csv", encoding="utf-8-sig")
    timing_window_result.to_csv(OUT_DIR / "growth_floor_70_execution_timing_windows.csv", encoding="utf-8-sig")
    print(f"Sub-C parity max_abs_diff={parity:.3g}")
    print(f"Data: {US_DATA_FILE.name}, risk: {RISK_FILE}")
    print(result[["start", "end", "years", "ann_return", "ann_vol", "sharpe", "max_dd", "final_nav", "calmar"]].to_string(float_format=lambda x: f"{x:.4f}"))
    print("\nBudget summary:")
    print(budget_summary.to_string(float_format=lambda x: f"{x:.4f}"))
    print("\nPressure windows:")
    print(window_result.to_string(float_format=lambda x: f"{x:.4f}"))
    print("\nFloor 70 execution timing:")
    print(timing_result[["start", "end", "years", "ann_return", "ann_vol", "sharpe", "max_dd", "final_nav", "calmar"]].to_string(float_format=lambda x: f"{x:.4f}"))
    print("\nFloor 70 execution budget summary:")
    print(timing_budget_summary.to_string(float_format=lambda x: f"{x:.4f}"))
    print("\nFloor 70 execution pressure windows:")
    print(timing_window_result.to_string(float_format=lambda x: f"{x:.4f}"))
    print(f"Saved: {OUT_DIR / 'growth_floor_sweep_summary.csv'}")
    print(f"Saved: {OUT_DIR / 'growth_floor_70_execution_timing_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

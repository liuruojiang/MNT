import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

import research_subd_six_etf_weighted_slope as subd


VERSION = "1.1"
START_DATE = pd.Timestamp("2010-01-01")
EVAL_START = pd.Timestamp("2020-01-02")
END_DATE = pd.Timestamp("2026-05-08")
R2_THRESHOLD = 0.20
TARGET_VOL = 0.25
SWITCH_BUFFER = 1.00
INITIAL_ENTRY_FRACTION = 0.50
OVERHEAT_ENTER = 0.20
OVERHEAT_EXIT = 0.18
OVERHEAT_DERISK_SCALE = 0.0
ONE_WAY_COST = 0.001
CN_BIAS_N = 60
CN_MOM_DAY = 20


@dataclass(frozen=True)
class EntryCase:
    label: str
    mode: Literal["full_entry", "all_new_asset_50_wait_down"]
    initial_fraction: float = 1.0


@dataclass(frozen=True)
class OverheatCase:
    label: str
    enter: float
    exit: float
    derisk_scale: float


def _target_from_scores(
    scores: dict[str, float],
    prev_holding: str,
    switch_buffer: float,
) -> tuple[str, str, float, float, bool]:
    if not scores:
        return "CASH", "CASH", math.nan, math.nan, False
    best = max(scores, key=scores.get)
    best_score = float(scores[best])
    current_score = float(scores[prev_holding]) if prev_holding in scores else math.nan
    blocked = False
    target = best
    if (
        prev_holding in scores
        and prev_holding != best
        and switch_buffer > 1.0
        and best_score <= current_score * switch_buffer
    ):
        target = prev_holding
        blocked = True
    return target, best, best_score, current_score, blocked


def run_staged_entry(
    prices: pd.DataFrame,
    config: subd.RunConfig,
    case: EntryCase,
    r2_threshold: float,
    switch_buffer: float,
) -> pd.DataFrame:
    prices = prices.loc[: config.end_date].copy()
    holding = "CASH"
    holding_fraction = 0.0
    pending_entry_target: str | None = None
    pending_entry_since: pd.Timestamp | None = None
    pending_entry_days = 0
    nav = 1.0
    trade_count = 0
    staged_initial_count = 0
    staged_fill_count = 0
    buffer_blocked_count = 0
    rows = []

    for idx, date in enumerate(prices.index):
        old_holding = holding
        old_fraction = holding_fraction

        scores: dict[str, float] = {}
        r2_values: dict[str, float] = {}
        if idx >= subd.LOOKBACK - 1:
            scores, r2_values = subd.calc_scores(prices, idx, r2_threshold=r2_threshold)
        ideal, best_candidate, best_score, current_score, buffer_blocked = _target_from_scores(
            scores, old_holding, switch_buffer
        )
        if buffer_blocked:
            buffer_blocked_count += 1

        signal_target = ideal if ideal != old_holding else None
        trade_target: str | None = None
        trade_fraction = old_fraction
        fill_on_down_day = False
        staged_initial = False

        if case.mode == "full_entry":
            if signal_target is not None:
                trade_target = signal_target
                trade_fraction = 0.0 if signal_target == "CASH" else 1.0
                pending_entry_target = None
                pending_entry_since = None
                pending_entry_days = 0
        elif old_holding == "CASH":
            if ideal != "CASH":
                initial = float(np.clip(case.initial_fraction, 0.0, 1.0))
                trade_target = ideal
                trade_fraction = initial
                staged_initial = initial < 1.0 - 1e-12
                if staged_initial:
                    pending_entry_target = ideal
                    pending_entry_since = date
                    pending_entry_days = 0
                    staged_initial_count += 1
                else:
                    pending_entry_target = None
                    pending_entry_since = None
                    pending_entry_days = 0
        else:
            is_partial_pending = (
                pending_entry_target is not None
                and old_holding == pending_entry_target
                and old_fraction < 1.0 - 1e-12
            )
            if is_partial_pending:
                if signal_target is not None:
                    if signal_target != "CASH":
                        initial = float(np.clip(case.initial_fraction, 0.0, 1.0))
                        trade_target = signal_target
                        trade_fraction = initial
                        pending_entry_target = signal_target if initial < 1.0 - 1e-12 else None
                        pending_entry_since = date if pending_entry_target is not None else None
                        pending_entry_days = 0
                        staged_initial = pending_entry_target is not None
                        if staged_initial:
                            staged_initial_count += 1
                    else:
                        trade_target = signal_target
                        trade_fraction = 0.0
                        pending_entry_target = None
                        pending_entry_since = None
                        pending_entry_days = 0
                else:
                    prev_close = prices.iloc[idx - 1][pending_entry_target] if idx > 0 else np.nan
                    curr_close = prices.iloc[idx][pending_entry_target]
                    is_down_day = (
                        pd.notna(prev_close)
                        and pd.notna(curr_close)
                        and float(curr_close) < float(prev_close)
                    )
                    if is_down_day:
                        trade_target = pending_entry_target
                        trade_fraction = 1.0
                        pending_entry_target = None
                        pending_entry_since = None
                        pending_entry_days = 0
                        fill_on_down_day = True
                        staged_fill_count += 1
                    else:
                        pending_entry_days += 1
            elif signal_target is not None:
                if signal_target != "CASH":
                    initial = float(np.clip(case.initial_fraction, 0.0, 1.0))
                    trade_target = signal_target
                    trade_fraction = initial
                    staged_initial = initial < 1.0 - 1e-12
                    if staged_initial:
                        pending_entry_target = signal_target
                        pending_entry_since = date
                        pending_entry_days = 0
                        staged_initial_count += 1
                    else:
                        pending_entry_target = None
                        pending_entry_since = None
                        pending_entry_days = 0
                else:
                    trade_target = signal_target
                    trade_fraction = 0.0
                    pending_entry_target = None
                    pending_entry_since = None
                    pending_entry_days = 0

        if old_holding == "CASH" or old_fraction <= 1e-12 or idx == 0:
            gross_return = 0.0
            asset_component = 0.0
        else:
            prev_px = prices.iloc[idx - 1].get(old_holding, np.nan)
            cur_px = prices.iloc[idx].get(old_holding, np.nan)
            asset_ret = float(cur_px / prev_px - 1.0) if pd.notna(prev_px) and pd.notna(cur_px) and prev_px > 0 else 0.0
            asset_component = old_fraction * asset_ret
            gross_return = asset_component

        turnover = 0.0
        cost = 0.0
        if trade_target is not None:
            if old_holding == trade_target:
                turnover = abs(float(trade_fraction) - old_fraction)
            else:
                turnover = (old_fraction if old_holding != "CASH" else 0.0) + (
                    float(trade_fraction) if trade_target != "CASH" else 0.0
                )
            cost = turnover * config.one_way_cost
            holding = trade_target if float(trade_fraction) > 1e-12 else "CASH"
            holding_fraction = float(trade_fraction) if holding != "CASH" else 0.0
            if turnover > 1e-12:
                trade_count += 1
        else:
            holding_fraction = old_fraction

        nav *= (1.0 + gross_return) * (1.0 - cost)
        net_return = nav / rows[-1]["nav"] - 1.0 if rows else nav - 1.0
        score_row = {f"score_{code}": scores.get(code, math.nan) for code in subd.ASSETS}
        r2_row = {f"r2_{code}": r2_values.get(code, math.nan) for code in subd.ASSETS}
        rows.append(
            {
                "date": date,
                "entry_case": case.label,
                "position_before": old_holding,
                "fraction_before": old_fraction,
                "position": holding,
                "holding_fraction": holding_fraction,
                "pending_entry_target": pending_entry_target,
                "pending_entry_since": pending_entry_since,
                "pending_entry_days": pending_entry_days,
                "trade_target": trade_target,
                "trade_fraction": trade_fraction if trade_target is not None else math.nan,
                "staged_initial": staged_initial,
                "fill_on_down_day": fill_on_down_day,
                "best_candidate": best_candidate,
                "best_candidate_score": best_score,
                "current_score": current_score,
                "buffer_blocked": buffer_blocked,
                "gross_return": gross_return,
                "asset_component": asset_component,
                "turnover": turnover,
                "cost": cost,
                "return": net_return,
                "nav": nav,
                "trade_count": trade_count,
                "stop_count": 0,
                "stop_triggered": False,
                "staged_initial_count": staged_initial_count,
                "staged_fill_count": staged_fill_count,
                **score_row,
                **r2_row,
                "buffer_blocked_count": buffer_blocked_count,
            }
        )

    return pd.DataFrame(rows).set_index("date")


def apply_target_vol_overlay(curve: pd.DataFrame, target_vol: float, vol_window: int, max_lev: float) -> pd.DataFrame:
    result = curve.copy()
    base_ret = result["return"].astype(float).fillna(0.0)
    realized_vol = base_ret.rolling(vol_window, min_periods=vol_window).std(ddof=0) * math.sqrt(subd.TRADING_DAYS)
    scale = (target_vol / realized_vol).replace([np.inf, -np.inf], np.nan)
    scale = scale.shift(1).clip(lower=0.0, upper=max_lev).fillna(1.0)
    result["base_return"] = base_ret
    result["base_nav"] = result["nav"]
    result["realized_vol"] = realized_vol
    result["weight"] = scale
    result["final_exposure"] = result["holding_fraction"].astype(float).fillna(0.0) * scale
    result["return"] = base_ret * scale
    result["gross_return"] = result["gross_return"].astype(float) * scale
    result["cost"] = result["cost"].astype(float) * scale
    result["nav"] = (1.0 + result["return"]).cumprod()
    result["target_vol"] = target_vol
    result["vol_window"] = vol_window
    result["max_lev"] = max_lev
    return result


def calc_bias_momentum(close_series: pd.Series) -> pd.Series:
    prices = close_series.values.astype(float)
    n = len(prices)
    result = np.full(n, np.nan)
    ma = close_series.rolling(CN_BIAS_N).mean().values
    total_lookback = CN_BIAS_N + CN_MOM_DAY - 1
    x = np.arange(CN_MOM_DAY, dtype=float)
    for i in range(total_lookback, n):
        bias_window = np.empty(CN_MOM_DAY)
        valid = True
        for j in range(CN_MOM_DAY):
            idx = i - CN_MOM_DAY + 1 + j
            if np.isnan(ma[idx]) or ma[idx] < 1e-10 or np.isnan(prices[idx]):
                valid = False
                break
            bias_window[j] = prices[idx] / ma[idx]
        if not valid or bias_window[0] < 1e-10:
            continue
        bias_norm = bias_window / bias_window[0]
        slope = np.polyfit(x, bias_norm, 1)[0]
        result[i] = slope * 10000
    return pd.Series(result, index=close_series.index)


def build_overheat_features(prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    features: dict[str, pd.DataFrame] = {}
    for code in subd.ASSETS:
        price = prices[code].astype(float)
        ma = price.rolling(CN_BIAS_N).mean()
        bias = price / ma - 1.0
        bias_mom = calc_bias_momentum(price)
        same_side = (bias > 0) & (bias_mom > 0) & bias.notna() & bias_mom.notna()
        features[code] = pd.DataFrame(
            {"bias": bias, "bias_mom": bias_mom, "same_side": same_side},
            index=prices.index,
        )
    return features


def apply_overheat_overlay(
    curve: pd.DataFrame,
    features: dict[str, pd.DataFrame],
    case: OverheatCase,
    one_way_cost: float,
) -> pd.DataFrame:
    if not 0 < case.exit < case.enter:
        raise ValueError(f"Bad overheat thresholds: {case}")
    if not 0 <= case.derisk_scale <= 1:
        raise ValueError(f"Bad derisk scale: {case}")

    out = curve.copy()
    defense_on = False
    prev_scale = 1.0
    prev_holding = None
    returns = []
    scales = []
    on_vals = []
    trigger_vals = []
    recover_vals = []
    bias_vals = []
    mom_vals = []
    same_side_vals = []
    tc_vals = []

    for dt, row in out.iterrows():
        holding = str(row["position_before"])
        if prev_holding is not None and holding != prev_holding:
            defense_on = False
            prev_scale = 1.0
        prev_holding = holding
        eligible = holding in subd.ASSETS

        bias = math.nan
        mom = math.nan
        same_side = False
        if eligible and dt in features[holding].index:
            frow = features[holding].loc[dt]
            bias = float(frow["bias"]) if pd.notna(frow["bias"]) else math.nan
            mom = float(frow["bias_mom"]) if pd.notna(frow["bias_mom"]) else math.nan
            same_side = bool(frow["same_side"]) if pd.notna(frow["same_side"]) else False

        current_scale = float(case.derisk_scale) if defense_on and eligible else 1.0
        tc = abs(current_scale - prev_scale) * one_way_cost if eligible else 0.0
        ret_before = float(row["return"])
        realized = (1.0 + ret_before * current_scale) * (1.0 - tc) - 1.0
        returns.append(realized)
        scales.append(current_scale)
        on_vals.append(bool(current_scale < 0.999999 and eligible))
        tc_vals.append(float(tc))

        triggered = False
        recovered = False
        next_state = defense_on
        if eligible and pd.notna(bias) and same_side:
            if next_state:
                if bias <= case.exit:
                    next_state = False
                    recovered = True
            elif bias >= case.enter:
                next_state = True
                triggered = True
        elif next_state:
            next_state = False
            recovered = True

        trigger_vals.append(triggered)
        recover_vals.append(recovered)
        bias_vals.append(bias)
        mom_vals.append(mom)
        same_side_vals.append(same_side)
        defense_on = next_state
        prev_scale = current_scale

    out.insert(0, "scenario", case.label)
    out["overheat_enter"] = case.enter
    out["overheat_exit"] = case.exit
    out["overheat_derisk_scale"] = case.derisk_scale
    out["return_before_overheat"] = out["return"]
    out["overheat_scale"] = pd.Series(scales, index=out.index, dtype=float)
    out["overheat_on"] = pd.Series(on_vals, index=out.index, dtype=bool)
    out["overheat_triggered"] = pd.Series(trigger_vals, index=out.index, dtype=bool)
    out["overheat_recovered"] = pd.Series(recover_vals, index=out.index, dtype=bool)
    out["overheat_bias"] = pd.Series(bias_vals, index=out.index, dtype=float)
    out["overheat_bias_mom"] = pd.Series(mom_vals, index=out.index, dtype=float)
    out["overheat_same_side"] = pd.Series(same_side_vals, index=out.index, dtype=bool)
    out["overheat_tc"] = pd.Series(tc_vals, index=out.index, dtype=float)
    out["return"] = pd.Series(returns, index=out.index, dtype=float)
    out["nav"] = (1.0 + out["return"]).cumprod()
    return out


def summarize(curve: pd.DataFrame, start: pd.Timestamp, label: str) -> dict[str, object]:
    sub = curve.loc[curve.index >= start].copy()
    nav = sub["nav"] / float(sub["nav"].iloc[0])
    ret = nav.pct_change().fillna(0.0)
    years = len(sub) / subd.TRADING_DAYS
    std = ret.std(ddof=0)
    final_exposure = sub["final_exposure"].astype(float).fillna(0.0)
    if "overheat_scale" in sub.columns:
        final_exposure = final_exposure * sub["overheat_scale"].astype(float).fillna(1.0)
    return {
        "version": curve["version"].iloc[0],
        "scenario": curve["scenario"].iloc[0],
        "window": label,
        "start": sub.index[0].date().isoformat(),
        "end": sub.index[-1].date().isoformat(),
        "days": len(sub),
        "total": float(nav.iloc[-1] - 1.0),
        "cagr": float(nav.iloc[-1] ** (1.0 / years) - 1.0),
        "maxdd": subd.max_drawdown(nav),
        "sharpe": float(ret.mean() / std * math.sqrt(subd.TRADING_DAYS)) if std > 0 else math.nan,
        "vol": float(std * math.sqrt(subd.TRADING_DAYS)),
        "cash_days": int((sub["position"] == "CASH").sum()),
        "half_position_days": int(((sub["holding_fraction"] > 1e-12) & (sub["holding_fraction"] < 1.0 - 1e-12)).sum()),
        "pending_days": int(sub["pending_entry_target"].notna().sum()),
        "staged_initials": int(sub["staged_initial"].astype(bool).sum()),
        "staged_fills": int(sub["fill_on_down_day"].astype(bool).sum()),
        "overheat_days": int(sub["overheat_on"].astype(bool).sum()) if "overheat_on" in sub.columns else 0,
        "overheat_triggers": int(sub["overheat_triggered"].astype(bool).sum()) if "overheat_triggered" in sub.columns else 0,
        "overheat_recoveries": int(sub["overheat_recovered"].astype(bool).sum()) if "overheat_recovered" in sub.columns else 0,
        "trades": int(sub["trade_count"].iloc[-1] - sub["trade_count"].iloc[0]),
        "cost_sum": float(sub["cost"].sum() + (sub["overheat_tc"].sum() if "overheat_tc" in sub.columns else 0.0)),
        "turnover_sum": float(sub["turnover"].sum()),
        "avg_scale": float(sub["weight"].mean()),
        "avg_final_exposure": float(final_exposure.mean()),
        "max_final_exposure": float(final_exposure.max()),
    }


def tag_original(curve: pd.DataFrame) -> pd.DataFrame:
    out = curve.copy()
    out.insert(0, "scenario", "v1_0_original_full_entry")
    out.insert(0, "version", "1.0")
    out["overheat_enter"] = np.nan
    out["overheat_exit"] = np.nan
    out["overheat_derisk_scale"] = 1.0
    out["overheat_scale"] = 1.0
    out["overheat_on"] = False
    out["overheat_triggered"] = False
    out["overheat_recovered"] = False
    out["overheat_tc"] = 0.0
    out["final_exposure_after_overheat"] = out["final_exposure"]
    return out


def build_curves(prices: pd.DataFrame, config: subd.RunConfig) -> list[pd.DataFrame]:
    original = apply_target_vol_overlay(
        run_staged_entry(
            prices,
            config,
            EntryCase("full_entry_baseline", "full_entry", 1.0),
            R2_THRESHOLD,
            SWITCH_BUFFER,
        ),
        TARGET_VOL,
        config.vol_window,
        config.max_lev,
    )
    staged = apply_target_vol_overlay(
        run_staged_entry(
            prices,
            config,
            EntryCase("all_new_asset_50_wait_down_no_timeout", "all_new_asset_50_wait_down", INITIAL_ENTRY_FRACTION),
            R2_THRESHOLD,
            SWITCH_BUFFER,
        ),
        TARGET_VOL,
        config.vol_window,
        config.max_lev,
    )
    v11 = apply_overheat_overlay(
        staged,
        build_overheat_features(prices),
        OverheatCase("v1_1_staged_50_plus_ma60_overheat", OVERHEAT_ENTER, OVERHEAT_EXIT, OVERHEAT_DERISK_SCALE),
        config.one_way_cost,
    )
    v11.insert(0, "version", VERSION)
    v11["scenario"] = "v1_1_staged_50_plus_ma60_overheat"
    v11["final_exposure_after_overheat"] = v11["final_exposure"] * v11["overheat_scale"]
    return [tag_original(original), v11]


def main() -> None:
    config = subd.RunConfig(
        source="sina",
        one_way_cost=ONE_WAY_COST,
        start_date=START_DATE,
        end_date=END_DATE,
        output_tag="v1_1_20260509",
        target_vols=(),
        vol_window=subd.DEFAULT_VOL_WINDOW,
        max_lev=subd.DEFAULT_MAX_LEV,
    )
    prices, sources = subd.load_close(config)
    prices = prices.loc[prices.index >= config.start_date]
    curves = build_curves(prices, config)
    windows = {
        "from_2020": EVAL_START,
        "5Y": config.end_date - pd.DateOffset(years=5),
        "3Y": config.end_date - pd.DateOffset(years=3),
        "1Y": config.end_date - pd.DateOffset(years=1),
    }
    summary = pd.DataFrame([summarize(curve, start, label) for curve in curves for label, start in windows.items()])

    prefix = "subd_six_etf_v1_1_20260509"
    subd.OUTPUT_DIR.mkdir(exist_ok=True)
    pd.concat(curves).to_csv(subd.OUTPUT_DIR / f"{prefix}_daily.csv", encoding="utf-8-sig")
    summary.to_csv(subd.OUTPUT_DIR / f"{prefix}_summary.csv", index=False, encoding="utf-8-sig")
    sources.to_csv(subd.OUTPUT_DIR / f"{prefix}_sources.csv", index=False, encoding="utf-8-sig")
    subd.data_quality(prices).to_csv(subd.OUTPUT_DIR / f"{prefix}_data_quality.csv", index=False, encoding="utf-8-sig")

    print("SUBD SIX ETF V1.1 SUMMARY")
    print(summary.to_string(index=False))
    print(f"\nWROTE {subd.OUTPUT_DIR / (prefix + '_summary.csv')}")
    print(f"WROTE {subd.OUTPUT_DIR / (prefix + '_daily.csv')}")


if __name__ == "__main__":
    main()

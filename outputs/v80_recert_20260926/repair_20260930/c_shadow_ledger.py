"""Diagnostic continuous-quantity Sub-C account on frozen L1/L2 inputs.

This model uses adjusted ETF/proxy opens/closes as tradable *index units*. In
particular QQQ, GLD and BTC-USD stand in for QQQM, GLDM and IBIT before their
full live history. It is a research account, not executable performance.
"""

from __future__ import annotations

import hashlib
import json
import math
import pickle
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
BASE = OUT.parent
INPUTS = BASE / "l1_final" / "formal_inputs.pkl"
SNAPSHOT = BASE / "l2" / "formal_subc_snapshot.pkl"
ASSETS = {
    "VTI": ("VTI", 0.20, "equity"),
    "QQQM": ("QQQ", 0.10, "equity"),
    "AVUV": ("AVUV", 0.10, "equity"),
    "VEA": ("VEA", 0.10, "equity"),
    "AVDV": ("AVDV", 0.10, "equity"),
    "VGIT": ("VGIT", 0.15, "fixed"),
    "DBMF": ("DBMF", 0.025, "fixed"),
    "KMLM": ("KMLM", 0.025, "fixed"),
    "GLDM": ("GLD", 0.15, "gold"),
    "IBIT": ("BTC-USD", 0.05, "fixed"),
}
CASH_TICKER = "BIL"
EQUITY = tuple(name for name, (_, _, group) in ASSETS.items() if group == "equity")
GOLD = ("GLDM",)
SPREAD_DAILY = 0.01 / 252.0
SCALE_FEE = 0.0006
ANNUAL_FEE = 0.001
EXPECTED_INPUTS = "182a5c54d5c81699d8e93038695a76febd15312aa48b5864e47a46318eeba00f"
EXPECTED_SNAPSHOT = "d0754188ef71f8ee938298398a994c3fe78782257df92fd544e7b1c53ed0fb9a"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def early_close(date: pd.Timestamp) -> bool:
    date = pd.Timestamp(date).normalize()
    thanksgiving = pd.Timestamp(date.year, 11, 1)
    thanksgiving += pd.Timedelta(days=(3 - thanksgiving.weekday()) % 7 + 21)
    if date == thanksgiving + pd.Timedelta(days=1):
        return True
    if (date.month, date.day) == (12, 24):
        return True
    fourth = pd.Timestamp(date.year, 7, 4)
    return date == fourth - pd.Timedelta(days=1) and date.weekday() < 5


def day_fractions(previous: pd.Timestamp, date: pd.Timestamp) -> tuple[float, float]:
    et = ZoneInfo("America/New_York")
    previous_hour = 13 if early_close(previous) else 16
    close_hour = 13 if early_close(date) else 16
    previous_close = datetime(previous.year, previous.month, previous.day, previous_hour, tzinfo=et).astimezone(timezone.utc)
    current_open = datetime(date.year, date.month, date.day, 9, 30, tzinfo=et).astimezone(timezone.utc)
    current_close = datetime(date.year, date.month, date.day, close_hour, tzinfo=et).astimezone(timezone.utc)
    gap = (current_open - previous_close).total_seconds() / (current_close - previous_close).total_seconds()
    assert 0 < gap < 1, (previous, date, gap)
    return gap, 1 - gap


def accrue_cash(cash: float, bil_return: float, spread_fraction: float, floor: bool) -> tuple[float, float]:
    if cash >= 0:
        return cash * (1 + bil_return), 0.0
    charge_rate = bil_return + SPREAD_DAILY * spread_fraction
    if floor:
        charge_rate = max(charge_rate, 0.0)
    charge = -cash * charge_rate
    return cash - charge, charge


def solve_trade(
    pre_nav: float,
    old: dict[str, float],
    target_weights: dict[str, float],
    rate: float,
) -> tuple[float, dict[str, float], float, float]:
    """Trade selected legs to target weights of NAV after actual turnover fee."""
    if pre_nav <= 0:
        raise ValueError(f"Non-positive pretrade NAV: {pre_nav}")
    lo, hi = 0.0, pre_nav
    for _ in range(70):
        mid = (lo + hi) / 2
        turnover = sum(abs(w * mid - old[name]) for name, w in target_weights.items())
        if mid + rate * turnover > pre_nav:
            hi = mid
        else:
            lo = mid
    post_nav = (lo + hi) / 2
    new = {name: w * post_nav for name, w in target_weights.items()}
    turnover = sum(abs(new[name] - old[name]) for name in target_weights)
    fee = rate * turnover
    if abs((post_nav + fee) - pre_nav) > 2e-13:
        raise AssertionError((post_nav, fee, pre_nav))
    return post_nav, new, turnover, fee


def window_metrics(daily: pd.DataFrame, formal: pd.Series) -> list[dict]:
    last = daily.index[-1]
    previous = {date: daily.index[pos - 1] if pos else pd.Timestamp("2020-12-02")
                for pos, date in enumerate(daily.index)}
    out = []
    for label, years in (("Full", None), ("10Y", 10), ("5Y", 5), ("3Y", 3), ("1Y", 1)):
        cutoff = daily.index[0] if years is None else last - pd.DateOffset(years=years)
        if years is not None and daily.index[0] > cutoff:
            out.append({"window": label, "status": "N/A", "reason": "valid C history shorter than window"})
            continue
        frame = daily.loc[daily.index >= cutoff]
        anchor = previous[frame.index[0]]
        elapsed = (frame.index[-1] - anchor).days / 365.25
        row = {"window": label, "status": "diagnostic", "start": str(frame.index[0].date()),
               "first_period_anchor": str(anchor.date()), "end": str(frame.index[-1].date()),
               "sessions": len(frame)}
        for key, returns in (("original_proxy", frame["return_original_proxy"]),
                             ("zero_floor", frame["return_zero_floor"]),
                             ("frozen_paper", formal.reindex(frame.index))):
            growth = (1 + returns).cumprod()
            peak = np.maximum.accumulate(np.r_[1.0, growth.to_numpy()])
            drawdown = np.r_[1.0, growth.to_numpy()] / peak - 1
            row[f"{key}_annual_pct"] = 100 * (float(growth.iloc[-1]) ** (1 / elapsed) - 1)
            row[f"{key}_max_dd_pct"] = 100 * float(drawdown.min())
        out.append(row)
    return out


def run_path(
    components: pd.DataFrame,
    equity_scale: pd.Series,
    gold_scale: pd.Series,
    close: pd.DataFrame,
    opens: dict,
    *,
    floor: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    days = components.index
    previous = close.index[close.index.get_loc(days[0]) - 1]
    initial = components.iloc[0]
    initial_weights = {
        name: float(initial[f"exposure::{name}"]) * float(initial[f"signal::{name}"])
        * (float(equity_scale.iloc[0]) if group == "equity" else float(gold_scale.iloc[0]) if group == "gold" else 1.0)
        for name, (_, _, group) in ASSETS.items()
    }
    units = {name: weight / float(close.at[previous, proxy]) for name, weight in initial_weights.items()
             for proxy in [ASSETS[name][0]]}
    cash = 1.0 - sum(initial_weights.values())
    prior_nav = 1.0
    records = []
    events = []
    previous_signals = {name: float(initial[f"signal::{name}"]) for name in ASSETS}

    for pos, date in enumerate(days):
        gap_fraction, day_fraction = day_fractions(previous, date)
        bil_previous = float(close.at[previous, CASH_TICKER])
        bil_open = float(opens[CASH_TICKER].at[date])
        bil_close = float(close.at[date, CASH_TICKER])
        prices_open = {name: float(opens[proxy].at[date]) for name, (proxy, _, _) in ASSETS.items()}
        prices_close = {name: float(close.at[date, proxy]) for name, (proxy, _, _) in ASSETS.items()}
        if any(not math.isfinite(v) or v <= 0 for v in (*prices_open.values(), *prices_close.values(), bil_open, bil_close)):
            raise ValueError(f"invalid adjusted proxy price on {date}")

        cash, financing_gap = accrue_cash(cash, bil_open / bil_previous - 1, gap_fraction, floor)
        open_values = {name: units[name] * price for name, price in prices_open.items()}
        nav_open = cash + sum(open_values.values())
        if nav_open <= 0:
            raise ValueError(f"nonpositive open equity on {date}")
        open_turnover = open_fee = 0.0
        today = components.loc[date]
        changed = []
        if pos:
            if abs(float(equity_scale.iloc[pos]) - float(equity_scale.iloc[pos - 1])) > 1e-12:
                changed.extend(EQUITY)
            if abs(float(gold_scale.iloc[pos]) - float(gold_scale.iloc[pos - 1])) > 1e-12:
                changed.extend(GOLD)
            for name in ASSETS:
                if abs(float(today[f"signal::{name}"]) - previous_signals[name]) > 1e-12 and name not in changed:
                    changed.append(name)
        if changed:
            targets = {
                name: float(today[f"exposure::{name}"]) * float(today[f"signal::{name}"])
                * (float(equity_scale.at[date]) if ASSETS[name][2] == "equity" else
                   float(gold_scale.at[date]) if ASSETS[name][2] == "gold" else 1.0)
                for name in changed
            }
            # The source has a 6bp scale fee and no separate signal-change fee.
            # Apply 6bp to all open trades as a stated diagnostic assumption.
            post_nav, target_values, open_turnover, open_fee = solve_trade(nav_open, open_values, targets, SCALE_FEE)
            event_kind = "scale_open" if all(abs(float(today[f"signal::{n}"]) - previous_signals[n]) <= 1e-12 for n in changed) else "signal_or_scale_open"
            for name in changed:
                old_units = units[name]
                units[name] = target_values[name] / prices_open[name]
                delta_value = target_values[name] - open_values[name]
                events.append({"date": date, "phase": "open", "kind": event_kind, "asset": name,
                               "proxy": ASSETS[name][0], "price": prices_open[name],
                               "units_before": old_units, "units_after": units[name],
                               "delta_units": units[name] - old_units,
                               "trade_notional_abs": abs(delta_value),
                               "allocated_fee": SCALE_FEE * abs(delta_value), "account_variant": "zero_floor" if floor else "original_proxy"})
            cash = post_nav - sum(units[name] * prices_open[name] for name in ASSETS)
        else:
            post_nav = nav_open
        assert abs(cash + sum(units[name] * prices_open[name] for name in ASSETS) - post_nav) < 2e-12

        cash, financing_day = accrue_cash(cash, bil_close / bil_open - 1, day_fraction, floor)
        close_values = {name: units[name] * price for name, price in prices_close.items()}
        nav_close_before_annual = cash + sum(close_values.values())
        annual_turnover = annual_fee = 0.0
        if bool(today["annual_rebalanced"]):
            targets = {
                name: base_weight * float(today[f"signal::{name}"])
                * (float(equity_scale.at[date]) if group == "equity" else
                   float(gold_scale.at[date]) if group == "gold" else 1.0)
                for name, (_, base_weight, group) in ASSETS.items()
            }
            nav_close, target_values, annual_turnover, annual_fee = solve_trade(
                nav_close_before_annual, close_values, targets, ANNUAL_FEE)
            for name in ASSETS:
                old_units = units[name]
                units[name] = target_values[name] / prices_close[name]
                delta_value = target_values[name] - close_values[name]
                events.append({"date": date, "phase": "close", "kind": "annual_rebalance", "asset": name,
                               "proxy": ASSETS[name][0], "price": prices_close[name],
                               "units_before": old_units, "units_after": units[name],
                               "delta_units": units[name] - old_units,
                               "trade_notional_abs": abs(delta_value),
                               "allocated_fee": ANNUAL_FEE * abs(delta_value), "account_variant": "zero_floor" if floor else "original_proxy"})
            cash = nav_close - sum(units[name] * prices_close[name] for name in ASSETS)
        else:
            nav_close = nav_close_before_annual
        final_values = {name: units[name] * prices_close[name] for name in ASSETS}
        identity = cash + sum(final_values.values()) - nav_close
        if abs(identity) > 2e-11 or nav_close <= 0:
            raise AssertionError((date, identity, nav_close))
        record = {"date": date, "prior_date": previous, "return": nav_close / prior_nav - 1,
                  "nav": nav_close, "nav_open_pretrade": nav_open, "nav_close_pre_annual": nav_close_before_annual,
                  "cash_signed": cash, "cash_positive": max(cash, 0), "debt": max(-cash, 0),
                  "bil_price_close": bil_close, "bil_cash_units": max(cash, 0) / bil_close,
                  "bil_debt_equivalent_units": max(-cash, 0) / bil_close,
                  "risky_notional": sum(final_values.values()), "gross_risky_exposure": sum(final_values.values()) / nav_close,
                  "open_turnover_value": open_turnover, "open_fee_value": open_fee,
                  "annual_turnover_value": annual_turnover, "annual_fee_value": annual_fee,
                  "financing_gap_signed_charge": financing_gap, "financing_day_signed_charge": financing_day,
                  "equity_scale": float(equity_scale.at[date]), "gold_scale": float(gold_scale.at[date]),
                  "account_identity_error": identity, "open_event": bool(changed),
                  "annual_event": bool(today["annual_rebalanced"])}
        for name in ASSETS:
            record[f"units::{name}"] = units[name]
            record[f"value::{name}"] = final_values[name]
            record[f"weight::{name}"] = final_values[name] / nav_close
        records.append(record)
        prior_nav = nav_close
        previous = date
        previous_signals = {name: float(today[f"signal::{name}"]) for name in ASSETS}
    return pd.DataFrame(records).set_index("date"), pd.DataFrame(events)


def main() -> None:
    if sha256(INPUTS) != EXPECTED_INPUTS:
        raise RuntimeError("Frozen L1 input SHA mismatch")
    if sha256(SNAPSHOT) != EXPECTED_SNAPSHOT:
        raise RuntimeError("Frozen L2 Sub-C snapshot SHA mismatch")
    with INPUTS.open("rb") as file:
        frozen = pickle.load(file)
    with SNAPSHOT.open("rb") as file:
        snapshot = pickle.load(file)
    components = snapshot["components"]
    close = frozen["frames"][3]
    opens = frozen["us_open"]
    for name, (proxy, _, _) in ASSETS.items():
        if proxy not in close or proxy not in opens:
            raise ValueError(f"missing price or open: {name}/{proxy}")
    for path_name, floor in (("original_proxy", False), ("zero_floor", True)):
        daily, events = run_path(components, snapshot["equity_scale"], snapshot["gold_scale"], close, opens, floor=floor)
        daily.to_csv(OUT / f"c_shadow_daily_{path_name}.csv", encoding="utf-8-sig")
        events.to_csv(OUT / f"c_shadow_events_{path_name}.csv", index=False, encoding="utf-8-sig")
        if path_name == "original_proxy":
            original, original_events = daily, events
        else:
            floored, floored_events = daily, events
    if not original.index.equals(floored.index):
        raise AssertionError("Variant calendars differ")
    combined = pd.DataFrame({"return_original_proxy": original["return"],
                             "return_zero_floor": floored["return"],
                             "return_frozen_paper": snapshot["scaled_return"]})
    windows = window_metrics(combined, snapshot["scaled_return"])
    pd.DataFrame(windows).to_csv(OUT / "c_shadow_window_metrics.csv", index=False, encoding="utf-8-sig")
    difference = original["return"] - snapshot["scaled_return"]
    gap = (original["return"] - floored["return"]).abs()
    summary = {
        "status": "DIAGNOSTIC_ONLY",
        "source_inputs": {"formal_inputs": str(INPUTS), "sha256": sha256(INPUTS),
                          "formal_subc_snapshot": str(SNAPSHOT), "snapshot_sha256": sha256(SNAPSHOT)},
        "date_start": str(original.index[0].date()), "date_end": str(original.index[-1].date()),
        "sessions": len(original), "first_period_anchor": "2020-12-02",
        "events": {"original_rows": len(original_events), "floor_rows": len(floored_events),
                   "open_event_days": int(original.open_event.sum()),
                   "annual_event_days": int(original.annual_event.sum()),
                   "open_turnover_total_initial_units": float(original.open_turnover_value.sum()),
                   "annual_turnover_total_initial_units": float(original.annual_turnover_value.sum()),
                   "open_fee_total_initial_units": float(original.open_fee_value.sum()),
                   "annual_fee_total_initial_units": float(original.annual_fee_value.sum())},
        "account_checks": {"max_identity_error_original": float(original.account_identity_error.abs().max()),
                           "max_identity_error_floor": float(floored.account_identity_error.abs().max()),
                           "all_nav_positive_original": bool((original.nav > 0).all()),
                           "all_nav_positive_floor": bool((floored.nav > 0).all())},
        "paper_comparison": {"daily_return_max_abs_diff": float(difference.abs().max()),
                             "days_abs_diff_gt_1e-8": int((difference.abs() > 1e-8).sum()),
                             "first_day_diff": float(difference.iloc[0]),
                             "max_diff_day": str(difference.abs().idxmax().date())},
        "funding_sensitivity": {"daily_return_max_abs_diff": float(gap.max()),
                                "days_abs_diff_gt_1e-12": int((gap > 1e-12).sum())},
        "windows": windows,
        "assumptions": [
            "The opening position on 2020-12-02 is the frozen 2020-12-03 target with no initial fee; this is a diagnostic initialization.",
            "Proxy adjusted prices are treated as continuously tradable units; QQQ/GLD/BTC-USD proxy substitution and BTC UTC clock prevent executable certification.",
            "Only scale/signal changes trade at next US session open; annual base rebalance trades at that session close. Otherwise quantities drift naturally.",
            "On an open event, only changed group legs target frozen base exposure times current scale; unchanged legs retain quantities. Actual traded notional is charged 6bp. Annual full reset charges 10bp.",
            "Any future signal change is charged 6bp as a diagnostic assumption because the frozen source has no separate signal-change fee; no signal changes occur in this snapshot.",
            "Positive cash receives BIL adjusted price return. Negative cash uses BIL adjusted price return plus 100bp/252, split over overnight and intraday elapsed-time fractions. The zero-floor variant clamps each borrowing segment to at least zero.",
            "No broker financing quote, short constraints, slippage, market impact, margin, or FX is represented. This account must not replace formal paper or production results.",
        ],
    }
    (OUT / "c_shadow_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("status", "date_start", "date_end", "sessions", "events", "account_checks", "paper_comparison", "funding_sensitivity")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

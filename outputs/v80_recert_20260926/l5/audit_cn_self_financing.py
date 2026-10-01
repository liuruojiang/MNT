"""Independent index-unit shadow ledger for L5 A/ADK resource audit.

Inputs are frozen L1 prices and L2 formal daily target/cost rows. This is a
diagnostic capital accounting reconstruction, not an executable index trade.
No production account or L2 audit helper is imported.
"""

from __future__ import annotations

import json
import math
import pickle
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "outputs" / "v80_recert_20260926"
OUT = BASE / "l5"
FEE_A = 0.001
FEE_ADK = 0.0005
RF = (1.03 ** (1 / 244)) - 1
DK_COL = {
    "SZ50": "DK_SZ50", "HS300": "DK_HS300", "ZZ500": "DK_ZZ500",
    "ZZ1000": "DK_ZZ1000", "CYB": "DK_CYB",
}


def solve_post_trade(pre_equity: float, old_notional: dict[str, float], targets: dict[str, float], fee: float) -> tuple[float, float, float]:
    """Solve equity after a fee charged on actual securities notional exchanged."""
    lo, hi = 0.0, pre_equity
    for _ in range(60):
        mid = (lo + hi) / 2
        turnover = sum(abs(targets.get(c, 0) * mid - old_notional.get(c, 0)) for c in set(targets) | set(old_notional))
        if mid + fee * turnover > pre_equity:
            hi = mid
        else:
            lo = mid
    end_equity = (lo + hi) / 2
    turnover = sum(abs(targets.get(c, 0) * end_equity - old_notional.get(c, 0)) for c in set(targets) | set(old_notional))
    return end_equity, turnover, fee * turnover


def targets_a(row: pd.Series) -> dict[str, float]:
    code, w = str(row.holding), float(row.weight)
    return {code: w} if code != "cash" and w > 1e-12 else {}


def targets_adk(row: pd.Series) -> dict[str, float]:
    w = float(row.weight)
    if w <= 1e-12 or not isinstance(row.long_leg, str) or not isinstance(row.short_leg, str):
        return {}
    return {row.long_leg: w, row.short_leg: -w}


def run_ledger(frame: pd.DataFrame, prices: pd.DataFrame, target_fn, fee: float, kind: str, always_rebalance: bool) -> pd.DataFrame:
    units: dict[str, float] = {}
    cash = 1.0
    records = []
    prev_equity = 1.0
    for date, row in frame.iterrows():
        price = {code: float(prices.at[date, code]) for code in units}
        assert all(math.isfinite(v) and v > 0 for v in price.values()), (date, price)
        old_notional = {code: units[code] * price[code] for code in units}
        if kind == "A":
            cash = cash * (1 + RF) if cash >= 0 else cash * (1 + RF)
        # ADK cash represents segregated net collateral; no short proceeds carry.
        pre_equity = cash + sum(old_notional.values())
        if pre_equity <= 0:
            raise ValueError(f"Nonpositive equity on {date}: {pre_equity}")
        targets = target_fn(row)
        should_trade = always_rebalance or float(row["trade_cost" if kind == "A" else "dk_execution_cost"]) > 1e-13
        if should_trade:
            end_equity, turnover, cost = solve_post_trade(pre_equity, old_notional, targets, fee)
            new_notional = {code: wt * end_equity for code, wt in targets.items()}
            units = {code: notional / float(prices.at[date, code]) for code, notional in new_notional.items() if abs(notional) > 1e-15}
            cash = end_equity - sum(new_notional.values())
        else:
            end_equity, turnover, cost = pre_equity, 0.0, 0.0
            new_notional = old_notional
        long_value = sum(max(v, 0.0) for v in new_notional.values())
        short_value = sum(max(-v, 0.0) for v in new_notional.values())
        check = cash + long_value - short_value
        assert abs(check - end_equity) < 1e-9, (date, check, end_equity)
        records.append({
            "date": date, "model_return": float(row["return"]), "shadow_return": end_equity / prev_equity - 1,
            "model_nav": float(row.nav), "shadow_equity": end_equity,
            "model_cost_rate": float(row["trade_cost" if kind == "A" else "dk_execution_cost"]),
            "actual_fee": cost, "actual_turnover": turnover, "trade_event": bool(should_trade),
            "cash": cash, "long_notional": long_value, "short_notional": short_value,
            "debt_cash": max(-cash, 0.0), "borrowed_stock": short_value,
            "gross_exposure": (long_value + short_value) / end_equity,
            "target": json.dumps(targets, ensure_ascii=False),
            "units": json.dumps(units, ensure_ascii=False),
        })
        prev_equity = end_equity
    return pd.DataFrame(records).set_index("date")


def run_adk_prior_close(frame: pd.DataFrame, prices: pd.DataFrame, always_rebalance: bool) -> pd.DataFrame:
    """Shift row-t target to prior close, solely to separate ADK clock from accounting."""
    units: dict[str, float] = {}
    cash = 1.0
    records = []
    prev_equity = 1.0
    prev_date = None
    for date, row in frame.iterrows():
        targets = targets_adk(row)
        should_trade = always_rebalance or float(row.dk_execution_cost) > 1e-13
        if prev_date is not None and should_trade:
            old_notional = {code: qty * float(prices.at[prev_date, code]) for code, qty in units.items()}
            pre_equity = cash + sum(old_notional.values())
            post_equity, turnover, cost = solve_post_trade(pre_equity, old_notional, targets, FEE_ADK)
            new_notional = {code: wt * post_equity for code, wt in targets.items()}
            units = {code: notional / float(prices.at[prev_date, code]) for code, notional in new_notional.items() if abs(notional) > 1e-15}
            cash = post_equity - sum(new_notional.values())
        else:
            turnover = cost = 0.0
        current = {code: qty * float(prices.at[date, code]) for code, qty in units.items()}
        equity = cash + sum(current.values())
        if equity <= 0:
            raise ValueError(f"Nonpositive prior-close ADK equity on {date}: {equity}")
        long_value = sum(max(v, 0.0) for v in current.values())
        short_value = sum(max(-v, 0.0) for v in current.values())
        records.append({
            "date": date, "model_return": float(row["return"]), "shadow_return": equity / prev_equity - 1,
            "model_nav": float(row.nav), "shadow_equity": equity,
            "model_cost_rate": float(row.dk_execution_cost), "actual_fee": cost,
            "actual_turnover": turnover, "trade_event": bool(should_trade),
            "cash": cash, "long_notional": long_value, "short_notional": short_value,
            "debt_cash": max(-cash, 0.0), "borrowed_stock": short_value,
            "gross_exposure": (long_value + short_value) / equity,
            "target": json.dumps(targets, ensure_ascii=False), "units": json.dumps(units, ensure_ascii=False),
        })
        prev_equity = equity
        prev_date = date
    return pd.DataFrame(records).set_index("date")


def window_metrics(ledger: pd.DataFrame, years: int | None, first_anchor: pd.Timestamp) -> dict:
    end = ledger.index.max()
    if years is None:
        sl = ledger.copy()
        label = "Full"
    else:
        start_cut = end - pd.DateOffset(years=years)
        sl = ledger.loc[ledger.index > start_cut].copy()
        label = f"{years}Y"
        if ledger.index.min() > start_cut:
            return {"window": label, "status": "N/A", "reason": "可用收益起点晚于窗口要求", "rows": len(sl)}
    if len(sl) < 2:
        return {"window": label, "status": "N/A", "reason": "不足两个收益日", "rows": len(sl)}
    # Every return row contributes one valuation interval; first opening NAV is 1.
    anchor = ledger.index[ledger.index.get_loc(sl.index[0]) - 1] if sl.index[0] != ledger.index[0] else first_anchor
    duration = (sl.index[-1] - anchor).days / 365.25
    if duration <= 0:
        return {"window": label, "status": "N/A", "reason": "窗口年化锚无效", "rows": len(sl)}
    out = {"window": label, "status": "diagnostic", "rows": len(sl), "start": str(sl.index[0].date()), "end": str(end.date())}
    for col, name in [("model_return", "model"), ("shadow_return", "shadow")]:
        curve = (1 + sl[col]).cumprod()
        peak = np.maximum.accumulate(np.r_[1.0, curve.to_numpy()])[1:]
        out[name + "_cagr"] = float(curve.iloc[-1] ** (1 / duration) - 1)
        out[name + "_mdd"] = float(np.min(curve.to_numpy() / peak - 1))
        out[name + "_terminal"] = float(curve.iloc[-1])
    out["cagr_gap_pp"] = 100 * (out["shadow_cagr"] - out["model_cagr"])
    return out


def summary(ledger: pd.DataFrame, first_anchor: pd.Timestamp) -> dict:
    diff = ledger.shadow_return - ledger.model_return
    substantial = diff.abs() > 1e-6
    first = diff[diff.abs() > 1e-10]
    uncharged = ledger.model_cost_rate.abs() < 1e-13
    nofee_gap = diff[uncharged & (diff.abs() > 1e-6)]
    hidden_fees = ledger.loc[uncharged & ledger.actual_fee.gt(1e-12), "actual_fee"]
    example = None
    if len(nofee_gap):
        dt = nofee_gap.index[0]
        row = ledger.loc[dt]
        example = {"date": str(dt.date()), "model_return": float(row.model_return),
                   "shadow_return": float(row.shadow_return), "gap_bp": float(nofee_gap.iloc[0] * 10000),
                   "model_cost_rate": float(row.model_cost_rate), "actual_fee": float(row.actual_fee),
                   "target": json.loads(row.target)}
    return {
        "rows": len(ledger), "start": str(ledger.index.min().date()), "end": str(ledger.index.max().date()),
        "first_numeric_difference": str(first.index[0].date()) if len(first) else None,
        "first_numeric_gap_bp": float(first.iloc[0] * 10000) if len(first) else None,
        "first_ge_0_01bp": str(diff[diff.abs() >= 1e-6].index[0].date()) if substantial.any() else None,
        "days_over_0_01bp": int(substantial.sum()), "max_daily_abs_gap_bp": float(diff.abs().max() * 10000),
        "first_no_model_fee_gap": str(nofee_gap.index[0].date()) if len(nofee_gap) else None,
        "first_no_model_fee_counterexample": example,
        "no_model_fee_gap_days": len(nofee_gap),
        "daily_rebalance_without_model_fee_days": len(hidden_fees),
        "daily_rebalance_without_model_fee_absolute_cost": float(hidden_fees.sum()),
        "max_gross_exposure": float(ledger.gross_exposure.max()), "max_cash_debt": float(ledger.debt_cash.max()),
        "max_stock_borrow": float(ledger.borrowed_stock.max()), "trade_days": int(ledger.trade_event.sum()),
        "fee_sum": float(ledger.actual_fee.sum()),
        "windows": [window_metrics(ledger, years, first_anchor) for years in (None, 10, 5, 3, 1)],
    }


def interaction_evidence(a: pd.DataFrame, adk: pd.DataFrame) -> dict:
    masks = {
        "A_R2_positive_score_rejected": a.suba_top_score_pass.astype(bool) & ~a.suba_top_r2_pass.astype(bool),
        "A_volume_blocks_equity": a.suba_volume_rule_scale.fillna(1).astype(float).lt(1 - 1e-12) & a.pre_suba_volume_holding.notna() & a.pre_suba_volume_holding.ne("cash") & a.pre_suba_volume_holding.ne("1.H11077"),
        "A_target_vol_live": a.weight.astype(float).gt(0) & a.scale_raw.fillna(1).astype(float).sub(1).abs().gt(1e-9),
        "ADK_scorehot_zero_exposure": adk.v78_score_overheat_on.astype(bool) & adk.base_weight_before_v78_score_hot.fillna(0).astype(float).gt(0),
        "ADK_target_vol_live": adk.weight.astype(float).gt(0) & adk.scale_raw.fillna(1).astype(float).sub(1).abs().gt(1e-9),
    }
    masks["A_volume_and_target_vol"] = masks["A_volume_blocks_equity"] & a.scale_raw.fillna(1).astype(float).sub(1).abs().gt(1e-9)
    masks["ADK_scorehot_and_nonunit_vol_scale"] = masks["ADK_scorehot_zero_exposure"] & adk.scale_raw.fillna(1).astype(float).sub(1).abs().gt(1e-9)
    out = {}
    for key, mask in masks.items():
        chosen = mask[mask]
        out[key] = {"days": int(mask.sum()), "first": str(chosen.index[0].date()) if len(chosen) else None}
    return out


def leg_evidence(a: pd.DataFrame, adk: pd.DataFrame) -> dict:
    active_pairs = adk.loc[adk.weight.astype(float).gt(0) & adk.top_pair.ne("none"), "top_pair"]
    return {
        "A_holding_days": {str(k): int(v) for k, v in a.holding.value_counts().items()},
        "ADK_active_pair_days": {str(k): int(v) for k, v in active_pairs.value_counts().items()},
        "ADK_active_pair_count": int(active_pairs.nunique()),
        "ADK_max_gross_target_exposure": float(2 * adk.loc[adk.top_pair.ne("none"), "weight"].max()),
    }


def frozen_price_replay(a: pd.DataFrame, adk: pd.DataFrame, a_prices: pd.DataFrame, dk_prices: pd.DataFrame) -> dict:
    """Independently bridge formal gross returns to frozen index close ratios."""
    a_errors, d_errors = [], []
    prev_date = None
    prev_a = None
    for date, row in a.iterrows():
        if prev_a is None:
            gross = RF
        else:
            w = float(prev_a.weight)
            code = str(prev_a.holding)
            asset_ret = float(a_prices.at[date, code]) / float(a_prices.at[prev_date, code]) - 1 if code != "cash" and w > 0 else 0.0
            gross = w * asset_ret + (1 - w) * RF
        expected = (1 + gross) * (1 - float(row.trade_cost)) - 1
        a_errors.append(abs(expected - float(row["return"])))
        prev_date, prev_a = date, row
    prev_date = None
    for date, row in adk.iterrows():
        if prev_date is None or not isinstance(row.long_leg, str):
            gross = 0.0
        else:
            rlong = float(dk_prices.at[date, row.long_leg]) / float(dk_prices.at[prev_date, row.long_leg]) - 1
            rshort = float(dk_prices.at[date, row.short_leg]) / float(dk_prices.at[prev_date, row.short_leg]) - 1
            gross = float(row.weight) * (rlong - rshort)
        expected = (1 + gross) * (1 - float(row.dk_execution_cost)) - 1
        d_errors.append(abs(expected - float(row["return"])))
        prev_date = date
    return {"A_max_abs_daily_residual": max(a_errors), "ADK_max_abs_daily_residual": max(d_errors)}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = pickle.loads((BASE / "l1_final" / "formal_inputs.pkl").read_bytes())
    a_prices, dk_prices = frozen["frames"][:2]
    a, adk = pickle.loads((BASE / "l2" / "formal_results.pkl").read_bytes())[:2]
    status = json.loads((BASE / "l2" / "formal_status.json").read_text(encoding="utf-8"))
    first_anchor = {"A": pd.Timestamp(status["first_period_starts"]["Sub-A"]),
                    "ADK": pd.Timestamp(status["first_period_starts"]["Sub-A-DK"])}
    # Formal ADK leg names use the same DK universe labels as frozen close fields.
    named_dk = dk_prices.rename(columns={v: k for k, v in DK_COL.items()})
    paths = {}
    for kind, frame, prices, target_fn, fee in [
        ("A", a, a_prices, targets_a, FEE_A),
        ("ADK", adk, named_dk, targets_adk, FEE_ADK),
    ]:
        for cadence in ("model_events", "daily_rebalance"):
            ledger = run_ledger(frame, prices, target_fn, fee, kind, cadence == "daily_rebalance")
            name = f"cn_{kind.lower()}_{cadence}"
            ledger.to_csv(OUT / f"{name}.csv", float_format="%.14g")
            paths[name] = summary(ledger, first_anchor[kind])
    for cadence in ("model_events", "daily_rebalance"):
        ledger = run_adk_prior_close(adk, named_dk, cadence == "daily_rebalance")
        name = f"cn_adk_prior_close_{cadence}"
        ledger.to_csv(OUT / f"{name}.csv", float_format="%.14g")
        paths[name] = summary(ledger, first_anchor["ADK"])
    paths["interaction_evidence"] = interaction_evidence(a, adk)
    paths["leg_evidence"] = leg_evidence(a, adk)
    paths["frozen_price_replay"] = frozen_price_replay(a, adk, a_prices, named_dk)
    (OUT / "cn_account_summary.json").write_text(json.dumps(paths, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: {field: v[field] for field in ("first_numeric_difference", "first_ge_0_01bp", "days_over_0_01bp", "max_daily_abs_gap_bp", "max_gross_exposure", "max_cash_debt", "max_stock_borrow")} for k, v in paths.items() if "windows" in v}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Read-only L5 audit of five-sleeve capital and shared-resource accounting."""

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "outputs" / "v80_recert_20260926"
L2 = BASE / "l2"
OUT = BASE / "l5"
SOURCE = ROOT / "mnt_bot V 8.0 plus.py"
WEIGHTS = {"Sub-A": 0.15, "Sub-A-DK": 0.15, "B7.8": 0.20, "B7.9": 0.20, "Sub-C": 0.30}
ORDER = list(WEIGHTS)
EQUITY_C = {"VTI", "QQQM", "AVUV", "VEA", "AVDV"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value):
    return float(value)


def main():
    status = json.loads((L2 / "formal_status.json").read_text(encoding="utf-8"))
    paths = {"daily": L2 / "formal_daily_returns.pkl", "results": L2 / "formal_results.pkl",
             "subc": L2 / "formal_subc_snapshot.pkl"}
    for name, key in (("daily", "daily_sha256"), ("results", "result_sha256"), ("subc", "subc_sha256")):
        if sha(paths[name]) != status[key]:
            raise RuntimeError(f"L2 {name} frozen hash mismatch")
    with paths["daily"].open("rb") as f:
        daily = pickle.load(f)
    with paths["results"].open("rb") as f:
        formal = pickle.load(f)
    with paths["subc"].open("rb") as f:
        subc = pickle.load(f)
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index("def _performance_combined_daily_returns(")
    stop = source.index("\ndef _performance_daily_window_metric(", start)
    function = source[start:stop]
    assert "series.reindex(union_dates).fillna(0.0)" in function
    assert "combined_nav = sum((nav_df[name] * weights[name]" in function
    assert all(token not in function for token in ("margin", "fx_rate", "cash_ledger", "borrow_value"))

    common_start = max(pd.Timestamp(daily[name].index[0]) for name in ORDER)
    common_end = max(pd.Timestamp(daily[name].index[-1]) for name in ORDER)
    dates = pd.DatetimeIndex(sorted(set().union(*(daily[name].loc[common_start:common_end].index for name in ORDER))))
    aligned = {name: daily[name].reindex(dates).fillna(0.0).astype(float) for name in ORDER}
    nav = {name: (1.0 + aligned[name]).cumprod() for name in ORDER}
    reconstructed_nav = sum(WEIGHTS[name] * nav[name] for name in ORDER)
    reconstructed_ret = reconstructed_nav.pct_change()
    reconstructed_ret.iloc[0] = reconstructed_nav.iloc[0] - 1.0
    actual = daily["Combined"].reindex(dates)
    maximum_error = float((actual - reconstructed_ret).abs().max())
    if maximum_error > 1e-12:
        raise RuntimeError(f"PV not exactly independent sleeve NAV sum: {maximum_error}")
    capital_prior = {name: WEIGHTS[name] * nav[name].shift(1).fillna(1.0) for name in ORDER}
    b_frames = {"B7.8": formal[2].attrs["v80_b78"], "B7.9": formal[2]}
    t = None
    for candidate in dates[dates >= pd.Timestamp("2024-01-01")]:
        if not all(candidate in daily[name].index for name in ORDER):
            continue
        a_candidate = formal[0].loc[candidate]
        adk_candidate = formal[1].loc[candidate]
        if (float(a_candidate["weight"]) > 1.0 and adk_candidate["top_pair"] != "none"
                and float(adk_candidate["final_exposure"]) > 0.0
                and all(float(frame.loc[candidate, "subb_account_borrow_value"]) > 0.0 for frame in b_frames.values())
                and float(subc["equity_scale"].loc[candidate]) > 1.0):
            t = candidate
            break
    if t is None:
        raise RuntimeError("No common active resource counterexample")
    a = formal[0].loc[t]
    adk = formal[1].loc[t]
    c_components = subc["components"].loc[t]
    c_scale_equity = float(subc["equity_scale"].loc[t])
    c_scale_gold = float(subc["gold_scale"].loc[t])
    capital = {name: number(capital_prior[name].loc[t]) for name in ORDER}
    a_weight = float(a["weight"])
    adk_weight = float(adk["final_exposure"])
    adk_active = bool(adk["top_pair"] != "none" and adk["direction"] != 0 and
                      pd.notna(adk["long_leg"]) and pd.notna(adk["short_leg"]))
    b = {}
    for label, frame in b_frames.items():
        row = frame.loc[t]
        b[label] = {
            "local_nav": number(row["subb_account_nav"]),
            "asset_over_nav": number(row["subb_account_asset_value"] / row["subb_account_nav"]),
            "borrow_over_nav": number(row["subb_account_borrow_value"] / row["subb_account_nav"]),
            "reported_gross_exposure": number(row["subb_gross_exposure"]),
            "scaled_borrow_in_initial_PV_units": number(capital[label] * row["subb_account_borrow_value"] / row["subb_account_nav"]),
        }
    c_risky = {}
    for name in ("VTI", "QQQM", "AVUV", "VEA", "AVDV", "VGIT", "DBMF", "KMLM", "GLDM", "IBIT"):
        exposure = float(c_components[f"exposure::{name}"])
        signal = float(c_components[f"signal::{name}"])
        scale = c_scale_equity if name in EQUITY_C else c_scale_gold if name == "GLDM" else 1.0
        c_risky[name] = exposure * signal * scale
    c_risky_total = sum(c_risky.values())
    # Gross long plus borrowed short; excludes C and any non-risky B cash, so conservative.
    gross_from_a_adk_b = (
        capital["Sub-A"] * max(a_weight, 0.0)
        + (2.0 * capital["Sub-A-DK"] * adk_weight if adk_active else 0.0)
        + sum(capital[label] * max(b[label]["reported_gross_exposure"], 0.0) for label in b)
    )
    a_indicated_debt = capital["Sub-A"] * max(a_weight - 1.0, 0.0)
    b_reported_debt = sum(b[label]["scaled_borrow_in_initial_PV_units"] for label in b)
    example = {
        "date": str(t.date()), "portfolio_nav_before": number(sum(capital.values())),
        "sleeve_capital_before_in_initial_PV_units": capital,
        "A": {"holding": str(a["holding"]), "model_weight": a_weight,
              "indicated_local_leverage_need_in_initial_PV_units": a_indicated_debt},
        "ADK": {"pair": str(adk["top_pair"]), "long_leg": str(adk["long_leg"]),
                "short_leg": str(adk["short_leg"]), "model_per_leg_weight": adk_weight,
                "gross_long_plus_short_in_initial_PV_units": 2 * capital["Sub-A-DK"] * adk_weight if adk_active else 0.0,
                "short_instrument_borrow_in_initial_PV_units": capital["Sub-A-DK"] * adk_weight if adk_active else 0.0,
                "collateral_or_margin_recorded": False},
        "B": b,
        "C": {"equity_scale": c_scale_equity, "gold_scale": c_scale_gold,
              "model_risky_asset_weight_sum": c_risky_total,
              "scaled_risky_exposure_in_initial_PV_units": capital["Sub-C"] * c_risky_total,
              "physical_quantity_cash_currency_ledger": False},
        "conservative_A_ADK_B_gross_exposure_in_initial_PV_units": gross_from_a_adk_b,
        "A_model_indicated_plus_B_reported_debt_in_initial_PV_units": a_indicated_debt + b_reported_debt,
        "ADK_short_instrument_borrow_excluded_from_debt_sum": True,
    }
    end_extensions = {
        name: {"last_return_date": str(pd.Timestamp(daily[name].index[-1]).date()),
               "aligned_last_date_return": number(aligned[name].loc[dates[-1]])} for name in ORDER
    }
    result = {
        "status": "FAIL_strict_unified_resource_certification",
        "source_sha256": sha(SOURCE), "l2_hashes": {name: sha(path) for name, path in paths.items()},
        "source_function": "_performance_combined_daily_returns",
        "code_facts": ["Per-sleeve returns reindexed on union calendar; missing return filled 0",
                       "Each sleeve NAV compounded independently", "PV NAV equals fixed initial weight times sleeve NAV summed",
                       "No common cash, financing, margin, FX conversion, inter-sleeve transfer or execution ledger in function"],
        "pv_rows": len(dates), "start": str(dates[0].date()), "end": str(dates[-1].date()),
        "pv_reconstruction_max_abs_daily_error": maximum_error,
        "calendar_end_extension": end_extensions,
        "single_day_counterexample": example,
        "certification_boundary": "Paper buy-and-hold sum of five independent NAV series only. B7.8 and B7.9 have independent USD-like self-financing ledgers; A/ADK target-weight returns lack strict quantity/cash/debt and ADK collateral. C component weights and scaling account are local, not global. Shared capital, cross-currency funding and margin cannot be inferred from PV NAV arithmetic.",
        "minimum_rules_needed": [
            "Define initial and ongoing capital per sleeve, the base currency and dated FX conversion source/clock",
            "Define timestamped cash transfer and borrowing between sleeves; no implicit use of another sleeve's idle cash",
            "Build A and ADK actual quantities, trade cash, fees, debt, short borrow and collateral/margin accounts with execution prices and clocks",
            "Link B7.8, B7.9 and C local account values to the shared cash book without double-counting BIL or financed exposures",
            "On CN/US holiday mismatch and sequential closes, apply explicit mark and transfer timing, then reconcile global assets minus liabilities to NAV every timestamp",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "audit_unified_resource.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "pv_rows": len(dates),
                      "max_error": maximum_error, "counterexample": example}, ensure_ascii=False))


if __name__ == "__main__":
    main()

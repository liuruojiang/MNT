"""Frozen, diagnostic-only B/C borrowing-rate floor; never writes production state."""
from __future__ import annotations

import hashlib
import json
import pickle
import sys
import types
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import requests


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / "mnt_bot V 8.0 plus.py"
BASE = ROOT / "outputs/v80_recert_20260926"
REPLACEMENTS = {
    "financing = debt * (cash_return + daily_spread * spread_fraction)":
        "financing = debt * max(cash_return + daily_spread * spread_fraction, 0.0)",
    "open_cash = old_cash * (1.0 + cash_gap) - max(-old_cash, 0.0) * daily_spread * gap_spread":
        "open_cash = max(old_cash, 0.0) * (1.0 + cash_gap) - max(-old_cash, 0.0) * (1.0 + max(cash_gap + daily_spread * gap_spread, 0.0))",
    "close_nav = sum((value * (1.0 + risk_day[name]) for name, value in target_values.items())) + cash_value * (1.0 + cash_day)":
        "close_nav = sum((value * (1.0 + risk_day[name]) for name, value in target_values.items())) + max(cash_value, 0.0) * (1.0 + cash_day) - max(-cash_value, 0.0) * (1.0 + max(cash_day + daily_spread * day_spread, 0.0))",
    "close_nav -= max(-cash_value, 0.0) * daily_spread * day_spread":
        "close_nav -= 0.0  # spread included in floored borrowing leg above",
    "financing_return.loc[~reduced] = -delta_exposure.loc[~reduced] * (bil.loc[~reduced] + daily_spread)":
        "financing_return.loc[~reduced] = -delta_exposure.loc[~reduced] * np.maximum(bil.loc[~reduced] + daily_spread, 0.0)",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(text, name):
    module = types.ModuleType(name)
    module.__file__ = str(SOURCE)
    sys.modules[name] = module
    exec(compile(text, str(SOURCE), "exec"), module.__dict__)
    return module


def metrics(module, series, label, first):
    rows = module._performance_standard_window_rows(
        {label: series}, end_date=pd.Timestamp("2026-09-25"),
        columns=[label], first_period_starts={label: pd.Timestamp(first)})
    return {row["window"]: row["metrics"][label] for row in rows}


def main():
    original = SOURCE.read_text(encoding="utf-8")
    altered = original
    for old, new in REPLACEMENTS.items():
        if altered.count(old) != 1:
            raise RuntimeError(f"expected one financing expression: {old}")
        altered = altered.replace(old, new)
    base = load_module(original, "v80_bc_floor_baseline")
    floor = load_module(altered, "v80_bc_floor_diagnostic")
    with (BASE / "l1_final/formal_inputs.pkl").open("rb") as handle:
        inputs = pickle.load(handle)
    with (BASE / "l2/formal_results.pkl").open("rb") as handle:
        saved_result = pickle.load(handle)
    with (BASE / "l2/formal_daily_returns.pkl").open("rb") as handle:
        frozen = pickle.load(handle)
    status = json.loads((BASE / "l2/formal_status.json").read_text(encoding="utf-8"))
    cn, dk, us, c_prices = inputs["frames"]
    opens = inputs["us_open"]
    changed = {}
    audit = {}

    def no_network(*args, **kwargs):
        raise RuntimeError("network disabled for frozen funding diagnostic")

    with patch.object(requests.sessions.Session, "request", side_effect=no_network):
        for label, fn in (("B7.8", floor._run_v80_subb_v78), ("B7.9", floor._run_v80_subb_v79)):
            candidate = fn(us, us_open=opens, strict_open_execution=True)
            old = saved_result[2].attrs["v80_b78"] if label == "B7.8" else saved_result[2]
            pd.testing.assert_index_equal(candidate.index, old.index)
            for flag in ("subb_model_execution", "subb_volreg_execution"):
                pd.testing.assert_series_equal(candidate[flag], old[flag], check_names=False)
            for col in [x for x in old if x.startswith("target_w_") and x in candidate]:
                if not np.allclose(candidate[col], old[col], atol=1e-12, rtol=0):
                    raise AssertionError(f"{label} target changed: {col}")
            if (candidate["subb_account_financing_value"] < -1e-12).any():
                raise AssertionError(f"{label} retains negative borrowing cost")
            changed[label] = candidate["return"]
            audit[label] = {
                "rows": len(candidate),
                "negative_borrow_days_before": int((old["subb_account_financing_value"] < -1e-12).sum()),
                "negative_borrow_days_after": int((candidate["subb_account_financing_value"] < -1e-12).sum()),
                "changed_return_days": int(((candidate["return"] - frozen[label]).abs() > 1e-12).sum()),
                "old_metrics": metrics(base, frozen[label], label, status["first_period_starts"][label]),
                "floor_metrics": metrics(floor, candidate["return"], label, status["first_period_starts"][label]),
            }

        old_components = base._compute_daily_subc_components_phased(
            c_prices, saved_result[4], base.PROD_CASH,
            prod_sig_b=saved_result[5], blend_a=base.PROD_BLEND_A)
        old_c, old_scale, old_fee = base._apply_subc_vol_scaling(
            old_components.base_return, c_prices, components=old_components,
            us_open=opens, strict_open_execution=True)
        pd.testing.assert_series_equal(old_c, frozen["Sub-C"], check_names=False, atol=1e-12, rtol=0)
        components = floor._compute_daily_subc_components_phased(
            c_prices, saved_result[4], floor.PROD_CASH,
            prod_sig_b=saved_result[5], blend_a=floor.PROD_BLEND_A)
        new_c, new_scale, new_fee = floor._apply_subc_vol_scaling(
            components.base_return, c_prices, components=components,
            us_open=opens, strict_open_execution=True)
        pd.testing.assert_series_equal(new_scale, old_scale)
        pd.testing.assert_series_equal(new_fee, old_fee)
        delta = new_c - old_c
        if (delta > 1e-10).any():
            worst = delta.idxmax()
            raise AssertionError(f"C borrowing floor unexpectedly improved {worst.date()}: {delta.loc[worst]:.12g}")
        changed["Sub-C"] = new_c
        audit["Sub-C"] = {
            "rows": len(new_c),
            "baseline_parity_max_abs": float((old_c - frozen["Sub-C"]).abs().max()),
            "changed_return_days": int((delta.abs() > 1e-12).sum()),
            "max_daily_return_decrease": float(-delta.min()),
            "sum_daily_return_changes": float(delta.sum()),
            "max_abs_fee_change_from_equity_path": float((new_fee - old_fee).abs().max()),
            "old_metrics": metrics(base, frozen["Sub-C"], "Sub-C", status["first_period_starts"]["Sub-C"]),
            "floor_metrics": metrics(floor, new_c, "Sub-C", status["first_period_starts"]["Sub-C"]),
        }

    combo = floor._performance_combined_daily_returns({**frozen, **changed})
    pd.testing.assert_index_equal(combo.index, frozen["Combined"].index)
    audit["Combined"] = {
        "rows": len(combo),
        "changed_return_days": int(((combo - frozen["Combined"]).abs() > 1e-12).sum()),
        "old_metrics": metrics(base, frozen["Combined"], "Combined", status["first_period_starts"]["Combined"]),
        "floor_metrics": metrics(floor, combo, "Combined", status["first_period_starts"]["Combined"]),
    }
    columns = {f"formal_{key}": frozen[key] for key in changed}
    columns.update({f"floor_{key}": value for key, value in changed.items()})
    columns["formal_Combined"] = frozen["Combined"]
    columns["floor_Combined"] = combo
    daily = pd.concat([series.rename(name) for name, series in columns.items()], axis=1).sort_index()
    if daily["floor_Combined"].notna().sum() != len(combo):
        raise AssertionError("combined-only trading dates were lost from daily export")
    daily.to_csv(HERE / "bc_floor_daily.csv.gz", index_label="date", compression="gzip")
    result = {
        "status": "diagnostic_only", "floor_rule": "max(BIL adjusted-price period return + 100bp prorated spread, 0) on borrow debt only",
        "source_sha256": sha(SOURCE), "input_sha256": sha(BASE / "l1_final/formal_inputs.pkl"),
        "daily_sha256": sha(HERE / "bc_floor_daily.csv.gz"), "replacements": REPLACEMENTS,
        "audit": audit,
    }
    (HERE / "bc_floor_status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": result["status"], "source_sha256": result["source_sha256"],
                      "summary": {key: {"changed_return_days": value["changed_return_days"],
                                         "old_full": value["old_metrics"]["Full"],
                                         "floor_full": value["floor_metrics"]["Full"]}
                                  for key, value in audit.items()}}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

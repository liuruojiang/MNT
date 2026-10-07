"""Independent second-pass execution attacks against the V8.0 entrypoint.

The tiny account paths are named counterexamples, never market performance.
The prefix probes use the existing real L1 Yahoo freeze, with network disabled.
"""
import hashlib
import importlib.util
import json
import pickle
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "outputs/v80_script_doublecheck_20261007/execution_notes.json"
BASELINE_SHA256 = "776cbc35d82f7ed18719a0de62decb32e9dac65dfc5e45b4e9b6f06f52dc3395"
REPORT = {"basis": "independent code/fixture counterexamples and real frozen-input prefix diagnostics",
          "network_allowed": False, "production_edited": False, "findings": []}


@pytest.fixture(scope="module")
def v80():
    path = ROOT / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_second_execution_20261007", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    with patch.object(requests.sessions.Session, "request", side_effect=AssertionError("network forbidden")):
        spec.loader.exec_module(module)
        REPORT["source"] = str(path)
        REPORT["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        yield module
    REPORT["source_sha256_after"] = hashlib.sha256(path.read_bytes()).hexdigest()
    notes_path = NOTES if REPORT["source_sha256"] == BASELINE_SHA256 else NOTES.with_name("execution_notes_after.json")
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    if notes_path != NOTES and notes_path.exists():
        existing = json.loads(notes_path.read_text(encoding="utf-8"))
        existing.setdefault("additional_verification_runs", []).append(REPORT)
        notes_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    elif not notes_path.exists():
        notes_path.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.modules.pop(spec.name, None)


@pytest.mark.parametrize("helper", ["_us_signal_days", "_v80_b78_us_signal_days"])
@pytest.mark.parametrize("days, signal_date", [
    (["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-10"], "2025-01-08"),
    (["2024-11-25", "2024-11-26", "2024-11-27", "2024-11-29"], "2024-11-27"),
    (["2025-12-29", "2025-12-30", "2025-12-31", "2026-01-02"], "2025-12-31"),
])
def test_calendar_prefixes_do_not_confirm_before_real_weekly_date(v80, helper, days, signal_date):
    frame = pd.DataFrame({"SPY": 100.0}, index=pd.to_datetime(days))
    expected_position = frame.index.get_loc(pd.Timestamp(signal_date))
    for count in range(1, len(frame) + 1):
        expected = {expected_position} if count > expected_position else set()
        assert getattr(v80, helper)(frame.iloc[:count], 0) == expected


@pytest.mark.parametrize("helper", ["_lookup_next_open", "_v80_b78_lookup_next_open"])
@pytest.mark.parametrize("live_value", [None, np.nan, 0.0, -1.0, np.inf])
def test_exact_date_invalid_live_price_uses_same_day_valid_proxy_only(v80, helper, live_value):
    signal = pd.Timestamp("2026-09-24")
    dates = pd.to_datetime(["2026-09-25", "2026-09-28"])
    opens = {"QQQ": pd.Series([190.0, 191.0], index=dates),
             "QQQM": pd.Series([live_value, 199.0], index=dates)}
    assert getattr(v80, helper)("QQQ", signal, opens) == pytest.approx(190.0)
    opens["QQQ"] = pd.Series([191.0], index=dates[1:])
    assert getattr(v80, helper)("QQQ", signal, opens) is None


def account_model(dates, weights, flags=None):
    model = pd.DataFrame({"return": 0.0, "model_rebalanced": flags or [False] * len(dates)}, index=dates)
    for asset, values in weights.items():
        model["model_w_" + asset] = values
        model["model_target_w_" + asset] = values
    return model


def account(v80, model, close, opens, *, commission=0.001, covered_assets=("QQQ",), defense_scale=0.0):
    return v80._v80_rebuild_subb_self_financing(
        model, close, opens, True, commission=commission, benchmark="BIL", spread_bps=0.0,
        trading_days=252, covered_assets=covered_assets, defense_scale=defense_scale,
        next_defense_func=v80._volreg_next_cash_state)


def test_weekly_model_plus_risk_transition_is_one_open_net_trade(v80):
    dates = pd.to_datetime(["2024-01-04", "2024-01-05"])
    model = account_model(dates, {"QQQ": [0.6, 0.0], "GLD": [0.4, 1.0], "BIL": [0.0, 0.0]}, [True, False])
    model.loc[dates[0], ["model_target_w_QQQ", "model_target_w_GLD"]] = [0.0, 1.0]
    model["volreg_defense"] = [False, True]
    model["volreg_ratio"] = 2.0
    close = pd.DataFrame({"QQQ": [100.0, 121.0], "GLD": [100.0, 108.0], "BIL": 100.0}, index=dates)
    opens = {"QQQ": pd.Series([100.0, 110.0], index=dates),
             "GLD": pd.Series([100.0, 90.0], index=dates), "BIL": close["BIL"]}
    out = account(v80, model, close, opens)
    last = out.iloc[-1]
    expected_fee = 0.001 * 1.32 / 1.001
    assert last["subb_model_execution"] and last["subb_volreg_execution"]
    assert last["subb_account_open_nav"] == pytest.approx(1.02)
    assert last["subb_account_fee_value"] == pytest.approx(expected_fee)
    assert last["subb_account_nav"] == pytest.approx((1.02 - expected_fee) * 1.2)
    assert last["effective_w_GLD"] == pytest.approx(1.0)
    assert last["effective_w_QQQ"] == 0.0
    assert not last["subb_pending_execution"]
    REPORT["simultaneous_event"] = {"open_nav": float(last["subb_account_open_nav"]),
        "fee": float(last["subb_account_fee_value"]), "nav": float(last["subb_account_nav"])}


def test_risk_only_return_and_fees_do_not_trade_uncovered_gold(v80):
    dates = pd.to_datetime(["2024-01-08", "2024-01-09", "2024-01-10"])
    model = account_model(dates, {"QQQ": [0.5] * 3, "GLD": [0.5] * 3, "BIL": [0.0] * 3})
    model["volreg_defense"] = [False, True, False]
    model["volreg_ratio"] = [2.0, 1.0, 1.0]
    close = pd.DataFrame({"QQQ": [100.0, 115.0, 125.0], "GLD": [100.0, 120.0, 108.0], "BIL": 100.0}, index=dates)
    opens = {"QQQ": pd.Series([100.0, 110.0, 120.0], index=dates),
             "GLD": pd.Series([100.0, 105.0, 110.0], index=dates), "BIL": close["BIL"]}
    out = account(v80, model, close, opens)
    gold_shares = out["effective_w_GLD"] * out["subb_account_nav"] / close["GLD"]
    np.testing.assert_allclose(gold_shares, 0.005, rtol=0, atol=1e-15)
    assert not out["subb_model_execution"].any()
    np.testing.assert_allclose(out["subb_account_fee_value"],
                               0.001 * out["subb_effective_turnover"] * out["subb_account_open_nav"], atol=1e-15)
    np.testing.assert_allclose(out["subb_account_nav"],
                               out["subb_account_asset_value"] - out["subb_account_borrow_value"], atol=1e-15)


@pytest.mark.parametrize("label, rebuilder, extractor", [
    ("B7.8", "_v80_b78_rebuild_subb_account_execution_costs", "_v80_b78_extract_subb_volreg_rebalances"),
    ("B7.9", "_rebuild_subb_account_execution_costs", "extract_subb_volreg_rebalances"),
])
def test_no_covered_equity_means_volreg_does_not_log_gold_drift_as_trade(v80, label, rebuilder, extractor):
    dates = pd.to_datetime(["2024-01-08", "2024-01-09"])
    model = account_model(dates, {"QQQ": [0.0, 0.0], "GLD": [0.5, 0.5], "BIL": [0.5, 0.5]})
    model["volreg_defense"] = [False, True]
    model["volreg_ratio"] = 2.0
    model["volreg_transition"] = [False, True]
    model["volreg_action"] = ["", "enter_defense"]
    close = pd.DataFrame({"QQQ": 100.0, "GLD": [100.0, 120.0], "BIL": 100.0}, index=dates)
    opens = {asset: pd.Series(100.0, index=dates) for asset in close}
    out = getattr(v80, rebuilder)(model, close, opens, strict_open_execution=True)
    assert out["subb_effective_turnover"].eq(0.0).all()
    assert out["subb_account_fee_value"].eq(0.0).all()
    gold_shares = out["effective_w_GLD"] * out["subb_account_nav"] / close["GLD"]
    np.testing.assert_allclose(gold_shares, 0.005, atol=1e-15)
    records = getattr(v80, extractor)(out, us_rot_close=close, us_open=opens)
    REPORT["findings"].append({"id": "volreg_record_weight_drift_" + label,
        "classification": "confirmed bug if assertion fails", "priority": "P2",
        "function": extractor, "dates": [str(day.date()) for day in dates],
        "turnover": out["subb_effective_turnover"].tolist(),
        "fee": out["subb_account_fee_value"].tolist(),
        "gold_shares": gold_shares.tolist(), "reported_records": records})
    assert records == [], "Zero traded notional must not become a GLDM buy/BIL sell in the VolReg trade log"


@pytest.mark.parametrize("rebuilder, extractor", [
    ("_v80_b78_rebuild_subb_account_execution_costs", "_v80_b78_extract_subb_volreg_rebalances"),
    ("_rebuild_subb_account_execution_costs", "extract_subb_volreg_rebalances"),
])
def test_covered_risk_conversion_logs_qqq_bil_but_not_untraded_gold(v80, rebuilder, extractor):
    dates = pd.to_datetime(["2024-01-08", "2024-01-09"])
    model = account_model(dates, {"QQQ": [0.5, 0.5], "GLD": [0.5, 0.5], "BIL": [0.0, 0.0]})
    model["volreg_defense"] = [False, True]
    model["volreg_ratio"] = 2.0
    model["volreg_transition"] = [False, True]
    model["volreg_action"] = ["", "enter_defense"]
    close = pd.DataFrame({"QQQ": [100.0, 121.0], "GLD": [100.0, 120.0], "BIL": 100.0}, index=dates)
    opens = {"QQQ": pd.Series([100.0, 110.0], index=dates),
             "GLD": pd.Series([100.0, 105.0], index=dates), "BIL": close["BIL"]}
    out = getattr(v80, rebuilder)(model, close, opens, strict_open_execution=True)
    records = getattr(v80, extractor)(out, us_rot_close=close, us_open=opens)
    assert len(records) == 1
    assert "QQQM" in records[0]["卖出"]
    assert "BIL" in records[0]["买入"]
    assert "GLDM" not in records[0]["卖出"] + records[0]["买入"]
    assert out.iloc[-1]["subb_account_fee_value"] == pytest.approx(0.00055)


def test_b78_actual_trade_record_uses_b78_live_price_mapping(v80):
    dates = pd.to_datetime(["2024-01-08", "2024-01-09"])
    model = account_model(dates, {"EFA": [0.5, 0.5], "GLD": [0.5, 0.5], "BIL": [0.0, 0.0]})
    model["volreg_defense"] = [False, True]
    model["volreg_ratio"] = 2.0
    model["volreg_transition"] = [False, True]
    model["volreg_action"] = ["", "enter_defense"]
    close = pd.DataFrame({"EFA": 100.0, "GLD": 100.0, "BIL": 100.0}, index=dates)
    opens = {asset: close[asset] for asset in close}
    opens["VEA"] = pd.Series(50.0, index=dates)
    out = v80._v80_b78_rebuild_subb_account_execution_costs(model, close, opens, strict_open_execution=True)
    records = v80._v80_b78_extract_subb_volreg_rebalances(out, us_rot_close=close, us_open=opens)
    assert len(records) == 1
    assert records[0]["卖出价格"] == "VEA $50.00开", "A B7.8-specific live ticker must use its own same-day live price"
    REPORT["b78_label_price_positive_control"] = {"result": "PASS", "proxy_open_EFA": 100.0,
        "live_open_VEA": 50.0, "record": records[0]}
    REPORT["test_scope"] = "EFA/VEA new price regression only when run with its focused selector"


@pytest.mark.parametrize("rebuilder", ["_v80_b78_rebuild_subb_account_execution_costs", "_rebuild_subb_account_execution_costs"])
def test_simultaneous_model_risk_record_uses_actual_open_net_trade_once(v80, rebuilder):
    dates = pd.to_datetime(["2024-01-04", "2024-01-05"])
    model = account_model(dates, {"QQQ": [0.6, 0.0], "GLD": [0.4, 1.0], "BIL": [0.0, 0.0]}, [True, False])
    model.loc[dates[0], ["model_target_w_QQQ", "model_target_w_GLD"]] = [0.0, 1.0]
    model["volreg_defense"] = [False, True]
    model["volreg_ratio"] = 2.0
    model["volreg_transition"] = [False, True]
    model["volreg_action"] = ["", "enter_defense"]
    close = pd.DataFrame({"QQQ": [100.0, 121.0], "GLD": [100.0, 108.0], "BIL": 100.0}, index=dates)
    opens = {"QQQ": pd.Series([100.0, 110.0], index=dates),
             "GLD": pd.Series([100.0, 90.0], index=dates), "BIL": close["BIL"]}
    out = getattr(v80, rebuilder)(model, close, opens, strict_open_execution=True)
    combined = out.copy()
    combined.attrs["v80_b78"] = out.copy()
    records = v80._v80_extract_subb_rebalances(combined, us_rot_close=close, us_open=opens)
    assert len(records) == 2, "One executed net event for each independent account, never two cause records"
    assert {record["variant"] for record in records} == {"B7.8", "B7.9"}
    for record in records:
        assert record["record_kind"] == "model"
        assert "QQQM 64.7%->0.0%" in record["卖出"]
        assert "GLDM 35.3%->99.9%" in record["买入"]
    assert out.iloc[-1]["subb_model_execution"] and out.iloc[-1]["subb_volreg_execution"]
    assert out.iloc[-1]["subb_account_fee_value"] == pytest.approx(0.0013186813186813182)


@pytest.mark.parametrize("rebuilder", ["_v80_b78_rebuild_subb_account_execution_costs", "_rebuild_subb_account_execution_costs"])
@pytest.mark.parametrize("pending_kind", ["model", "risk"])
def test_last_pending_target_is_not_an_executed_historical_record(v80, rebuilder, pending_kind):
    dates = pd.to_datetime(["2024-01-04"])
    model = account_model(dates, {"QQQ": [1.0], "GLD": [0.0], "BIL": [0.0]}, [pending_kind == "model"])
    if pending_kind == "model":
        model.loc[dates[0], ["model_target_w_QQQ", "model_target_w_GLD"]] = [0.0, 1.0]
    model["volreg_defense"] = False
    model["volreg_ratio"] = 2.0 if pending_kind == "risk" else 1.0
    model["volreg_transition"] = False
    model["volreg_action"] = ""
    close = pd.DataFrame({"QQQ": 100.0, "GLD": 100.0, "BIL": 100.0}, index=dates)
    opens = {asset: close[asset] for asset in close}
    out = getattr(v80, rebuilder)(model, close, opens, strict_open_execution=True)
    assert out.iloc[-1]["subb_pending_execution"]
    assert not out.iloc[-1]["subb_model_execution"]
    assert not out.iloc[-1]["subb_volreg_execution"]
    combined = out.copy()
    combined.attrs["v80_b78"] = out.copy()
    assert v80._v80_extract_subb_rebalances(combined, us_rot_close=close, us_open=opens) == []


@pytest.fixture(scope="module")
def frozen_subb(v80):
    source = ROOT / "outputs/v80_recert_20260926/l1_final/formal_inputs.pkl"
    if not source.is_file():
        pytest.skip("optional real-input execution diagnostic requires the git-ignored local L1 freeze")
    data = pickle.loads(source.read_bytes())
    close = data["frames"][2].iloc[-1200:].copy()
    opens = {asset: series.loc[close.index[0]:].copy() for asset, series in data["us_open"].items()}
    full = v80._run_v80_subb_variants(close, us_open=opens, strict_open_execution=True)
    REPORT["real_input"] = {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "usable_close_start": str(close.index[0].date()), "usable_close_end": str(close.index[-1].date()),
        "close_rows": len(close), "entrypoint": "_run_v80_subb_variants -> both formal B wrappers",
        "current_data": False, "adjustment_basis": "existing Yahoo adjusted OHLC/proxy splice freeze",
        "scope": "prefix/account diagnostic, not production performance certification"}
    return close, opens, full


@pytest.mark.parametrize("cutoff", ["2025-01-08", "2026-09-22", "2026-09-23", "2026-09-24"])
def test_real_formal_subb_prefix_history_is_not_rewritten_by_future_tail(v80, frozen_subb, cutoff):
    close, opens, full = frozen_subb
    prefix_close = close.loc[:cutoff]
    prefix_open = {asset: series.loc[:cutoff] for asset, series in opens.items()}
    prefix = v80._run_v80_subb_variants(prefix_close, us_open=prefix_open, strict_open_execution=True)
    outcomes = {}
    for label, short, long in (("B7.8", prefix.attrs["v80_b78"], full.attrs["v80_b78"]),
                                ("B7.9", prefix, full)):
        columns = [col for col in short if col == "return" or col.startswith(("subb_account_", "execution_target_w_", "actual_w_", "subb_pending_"))]
        left = short[columns].copy()
        right = long.loc[short.index, columns].copy()
        left.attrs, right.attrs = {}, {}
        pd.testing.assert_frame_equal(left, right, check_exact=False, rtol=0, atol=1e-13)
        outcomes[label] = {"return_max_abs_delta": float((left["return"] - right["return"]).abs().max()),
                           "prefix_last_pending_model": bool(short.iloc[-1]["subb_pending_model_rebalance"]),
                           "prefix_last_pending_risk": bool(short.iloc[-1]["subb_pending_volreg_transition"]),
                           "rows": len(short)}
    REPORT.setdefault("real_prefix_comparisons", {})[cutoff] = outcomes


def test_real_volreg_records_against_actual_gold_share_continuity(v80, frozen_subb):
    close, opens, result = frozen_subb
    findings = []
    for label, frame, extractor, live in (("B7.8", result.attrs["v80_b78"], v80._v80_b78_extract_subb_volreg_rebalances, "GLDM"),
                                          ("B7.9", result, v80.extract_subb_volreg_rebalances, "GLDM")):
        records = extractor(frame, us_rot_close=close, us_open=opens)
        shares = frame["effective_w_GLD"] * frame["subb_account_nav"] / close["GLD"].reindex(frame.index)
        for record in records:
            day = pd.Timestamp(record["日期"])
            row = frame.loc[day]
            if row["subb_model_execution"] or live not in record["卖出"] + record["买入"]:
                continue
            position = frame.index.get_loc(day)
            if position == 0:
                continue
            before, after = float(shares.iloc[position - 1]), float(shares.iloc[position])
            if abs(after - before) <= 1e-12:
                findings.append({"label": label, "date": str(day.date()), "gold_shares_before": before,
                                 "gold_shares_after": after, "reported": record})
    REPORT["real_gold_drift_records"] = findings
    assert findings == [], "Observed formal-path VolReg gold records do not correspond to any change in gold shares"


@pytest.mark.parametrize("query_kind", ["signal", "live_signal", "params", "live_params"])
@pytest.mark.parametrize("intraday", [False, True])
def test_real_daily_risk_event_confirmation_in_all_four_query_consumers(v80, frozen_subb, query_kind, intraday):
    close, _, full = frozen_subb
    b78 = full.attrs["v80_b78"]
    candidates = full.index[(full["subb_pending_volreg_transition"] & b78["subb_pending_volreg_transition"]
                             & ~full["subb_pending_model_rebalance"]
                             & ~b78["subb_pending_model_rebalance"]).to_numpy()]
    selected = None
    for day in candidates:
        candidate = full.loc[:day].copy()
        candidate.attrs["v80_b78"] = b78.loc[:day].copy()
        states = []
        for label, result in (("B7.8", candidate.attrs["v80_b78"]), ("B7.9", candidate)):
            rows = v80._v80_subb_variant_rows(result, label=label)
            states.append(v80._v80_subb_execution_state(result, rows, label, is_signal_day=False))
        if all(item["risk_action"] and not item["model_action"] for item in states):
            selected = (day, candidate)
            break
    assert selected is not None, "The real diagnostic sample must contain a shared daily risk event"
    day, candidate = selected
    text = []
    signal_info = v80._write_v80_subb_overview(text.append, candidate, query_kind=query_kind,
        us_intraday=intraday, us_rot_close=close.loc[:day],
        is_signal_day=False if query_kind in {"signal", "live_signal"} else None)
    for label in ("B7.8", "B7.9"):
        assert signal_info[label]["is_signal"] is (not intraday)
        expected_note = "VolReg盘中假设，等待收盘确认" if intraday else "VolReg收盘确认，下一美股交易日开盘执行"
        assert expected_note in signal_info[label]["note"]
    if query_kind in {"signal", "live_signal"}:
        expected_action = "现在不执行，等待收盘确认" if intraday else "不等待下周周度信号"
        assert expected_action in "".join(text)
    REPORT.setdefault("four_query_confirmation", {})[query_kind + ("_intraday" if intraday else "_closed")] = {
        "sample_date": str(day.date()), "result": "PASS", "information_is_confirmed": not intraday,
        "scope": "actual shared display consumer called by all four handlers; no network or real order acceptance"}

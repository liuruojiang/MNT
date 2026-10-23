"""Independent post-repair CN review; synthetic data, offline only."""
import importlib.util
import io
import itertools
import os
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    root = Path(__file__).resolve().parents[1]
    source = Path(os.environ.get("V80_REVIEW_SOURCE", str(root / "mnt_bot V 8.0 plus.py")))
    spec = importlib.util.spec_from_file_location("v80_cn_independent_review_20261023", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def offline(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline post-repair review prohibits network/LLM")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.poe, "call", forbidden)
    monkeypatch.setattr(v80.time, "sleep", lambda *a, **k: None)


@pytest.mark.parametrize("mode,left,right", list(itertools.product(["or", "and"], [True, False, None], [True, False, None])))
def test_three_state_truth_table_independent_oracle(v80, mode, left, right):
    dates = v80._expected_cn_sessions("2026-07-01", "2026-07-31")
    def amount(state):
        x = pd.Series(np.linspace(200., 100., len(dates)) if state is True else np.linspace(100., 200., len(dates)), index=dates)
        if state is None:
            x.iloc[-2] = np.nan
        return x
    signal, feature = v80._build_consecutive_below_amount_signal({
        "left": {"amount": amount(left), "ma": 3, "days": 2},
        "right": {"amount": amount(right), "ma": 3, "days": 2},
    }, mode=mode)
    possibilities = [((bool(a) or bool(b)) if mode == "or" else (bool(a) and bool(b)))
                     for a in ([False, True] if left is None else [left])
                     for b in ([False, True] if right is None else [right])]
    unknown = len(set(possibilities)) > 1
    assert bool(feature["combined_unresolved"].iloc[-1]) == unknown
    if not unknown:
        assert bool(signal.iloc[-1]) == possibilities[0]


def source_with_old_gap(v80, monkeypatch, gap):
    dates = v80._expected_cn_sessions("2016-01-04", "2018-03-30")
    raw = pd.DataFrame({"amount": np.linspace(100., 200., len(dates))}, index=dates)
    if gap is not None:
        raw.loc[pd.Timestamp(gap), "amount"] = np.nan
    def vendor(secid, *a, **k):
        assert secid == v80.CN_SA_VOLUME_CYB_SECID
        return raw.copy(), "synthetic"
    monkeypatch.setattr(v80, "_fetch_cn_amount_with_fallback", vendor)
    signal, feature = v80._load_suba_volume_signal(expected_date=dates[-1])
    price_dates = dates[dates >= v80.CN_STOCK_FORMAL_START]
    t = np.arange(len(price_dates), dtype=float)
    prices = pd.DataFrame({code: 100. * np.exp(.0001 * t*t) for code in v80.CN_EQUITY_CODES}, index=price_dates)
    prices[v80.CN_BOND_CODE] = 100.
    result = v80.run_cn_strategy(prices, list(v80.CN_EQUITY_CODES))
    return prices, result, signal, feature


def test_ancient_gap_before_strategy_start_cannot_block_formal_output(v80, monkeypatch):
    prices, result, signal, feature = source_with_old_gap(v80, monkeypatch, "2016-06-01")
    assert feature.loc[feature.index < pd.Timestamp("2017-01-01"), "combined_unresolved"].any()
    assert not feature.reindex(result.index)["combined_unresolved"].any()
    repaired = v80._apply_suba_volume_overlay_policy(result, prices, signal, feature)
    assert not repaired["suba_volume_unresolved"].any()


def test_gap_in_prestart_dependency_still_blocks(v80, monkeypatch):
    prices, result, signal, feature = source_with_old_gap(v80, monkeypatch, "2017-05-25")
    # Strategy native warmup starts later. Put the unknown in a consumed row
    # using a preceding MA dependency immediately before that first row.
    first = result.index[0]
    earlier = prices.index[prices.index < first][-1]
    # Rebuild source with precisely that previous trading day's gap.
    prices, result, signal, feature = source_with_old_gap(v80, monkeypatch, str(earlier.date()))
    assert bool(feature.loc[result.index[0], "combined_unresolved"])
    with pytest.raises(v80.poe.BotError):
        v80._apply_suba_volume_overlay_policy(result, prices, signal, feature)


def test_amount_source_starts_later_than_strategy_must_not_fill_false(v80, monkeypatch):
    real_fetch = v80._fetch_cn_amount_with_fallback
    prices, result, signal, feature = source_with_old_gap(v80, monkeypatch, None)
    later = result.index[30]
    # Preserve the real source fallback/row-count checks; only the provider
    # returns a truncated but >50-row history. ZZ2000 is not yet published.
    partial_raw = feature.loc[later:, ["cyb_amount"]].rename(columns={"cyb_amount": "amount"})
    partial_raw.index = pd.DatetimeIndex(partial_raw.index)
    assert len(partial_raw) > 50
    monkeypatch.setattr(v80, "_fetch_cn_amount_with_fallback", real_fetch)
    monkeypatch.setattr(v80, "_fetch_cn_sohu_amount", lambda *a, **k: partial_raw.copy())
    narrow_signal, narrow_feature = v80._load_suba_volume_signal(expected_date=prices.index[-1])
    try:
        output = v80._apply_suba_volume_overlay_policy(result, prices, narrow_signal, narrow_feature)
    except (v80.poe.BotError, v80.DataSchemaError):
        return
    assert output.loc[output.index < later, "suba_volume_unresolved"].all(), "Missing post-publication history cannot become a known no-trigger"


@pytest.mark.parametrize("leading_days", [0, 1])
def test_truncated_source_warmup_must_not_erase_dependency_unknown(v80, monkeypatch, leading_days):
    real_fetch = v80._fetch_cn_amount_with_fallback
    prices, result, signal, feature = source_with_old_gap(v80, monkeypatch, None)
    first = result.index[0]
    source_start = first if leading_days == 0 else prices.index[prices.index < first][-1]
    partial_raw = feature.loc[source_start:, ["cyb_amount"]].rename(columns={"cyb_amount": "amount"})
    partial_raw.index = pd.DatetimeIndex(partial_raw.index)
    assert len(partial_raw) > 50
    monkeypatch.setattr(v80, "_fetch_cn_amount_with_fallback", real_fetch)
    monkeypatch.setattr(v80, "_fetch_cn_sohu_amount", lambda *a, **k: partial_raw.copy())
    narrow_signal, narrow_feature = v80._load_suba_volume_signal(expected_date=prices.index[-1])
    # CYB was published in 2010: a 2017 vendor cutoff is not its inception.
    assert bool(narrow_feature.loc[first, "combined_unresolved"]), "First consumed day lacks the preceding MA/streak dependency"
    with pytest.raises(v80.poe.BotError):
        v80._apply_suba_volume_overlay_policy(result, prices, narrow_signal, narrow_feature)


def test_prefix_invariance_including_unknown_mask(v80):
    dates = v80._expected_cn_sessions("2026-04-01", "2026-09-30")
    amounts = pd.Series(np.linspace(100., 200., len(dates)), index=dates)
    amounts.iloc[50] = np.nan
    full = v80._suba_amount_rule_frame(amounts, 20, 4)
    prefix = v80._suba_amount_rule_frame(amounts.iloc[:70], 20, 4)
    pd.testing.assert_frame_equal(prefix, full.iloc[:70])


def test_real_publication_warmup_remains_known(v80):
    publication = pd.Timestamp("2010-06-01")
    dates = v80._expected_cn_sessions(publication, "2010-08-31")
    raw = pd.Series(np.linspace(200., 100., len(dates)), index=dates)
    frame = v80._suba_amount_rule_frame(raw, 20, 4, publication_date=publication)
    assert frame["known"].all()
    assert not frame["signal"].iloc[:22].any()
    assert frame["signal"].iloc[22:].all()


def test_truncated_warmup_recovers_after_full_dependency(v80):
    dates = v80._expected_cn_sessions("2017-09-19", "2017-12-31")
    raw = pd.Series(np.linspace(200., 100., len(dates)), index=dates)
    frame = v80._suba_amount_rule_frame(raw, 20, 4, publication_date="2010-06-01")
    assert not frame["known"].iloc[:22].any()
    assert frame["known"].iloc[22:].all()
    assert frame["signal"].iloc[22:].all()


@pytest.mark.parametrize("query_kind", ["signal", "live_signal", "params", "live_params"])
def test_unknown_advisory_cannot_emit_confirmed_adjustment(v80, query_kind):
    dates = pd.to_datetime(["2026-09-28", "2026-09-29"])
    code = v80.CN_EQUITY_CODES[0]
    base = pd.DataFrame({"holding": ["cash", code], "target": ["cash", code],
                         "weight": [0., 1.], "is_signal": [False, True], "return": 0.}, index=dates)
    feature = pd.DataFrame({"combined_unresolved": [False, True]}, index=dates)
    advisory = v80._apply_suba_volume_overlay_policy(base, None, pd.Series(False, index=dates), feature, True)
    output = []
    result = v80._write_a_adk_query_overview(output.append, advisory, None, query_kind=query_kind)
    assert not result["Sub-A"]["is_signal"], "UNKNOWN risk state must not produce an exportable confirmed order signal"
    assert "收盘目标已确认：若尚未执行，按目标调整" not in "".join(output)


@pytest.mark.parametrize("query_kind", ["signal", "live_signal", "params", "live_params"])
def test_known_confirmed_adjustment_still_emits_signal(v80, query_kind):
    dates = pd.to_datetime(["2026-09-28", "2026-09-29"])
    code = v80.CN_EQUITY_CODES[0]
    base = pd.DataFrame({"holding": ["cash", code], "target": ["cash", code],
                         "weight": [0., 1.], "is_signal": [False, True], "return": 0.,
                         "suba_volume_unresolved": False, "suba_volume_unavailable": False}, index=dates)
    output = []
    result = v80._write_a_adk_query_overview(output.append, base, None, query_kind=query_kind)
    assert result["Sub-A"]["is_signal"], "Known confirmed adjustment must remain executable"
    if query_kind in {"signal", "live_signal"}:
        assert "收盘目标已确认：若尚未执行，按目标调整" in "".join(output)


def test_unknown_advisory_real_excel_is_nonexecuting(v80):
    dates = pd.to_datetime(["2026-09-28", "2026-09-29"])
    code = v80.CN_EQUITY_CODES[0]
    base = pd.DataFrame({"holding": ["cash", code], "target": ["cash", code],
                         "weight": [0., 1.], "is_signal": [False, True], "return": 0.}, index=dates)
    feature = pd.DataFrame({"combined_unresolved": [False, True]}, index=dates)
    advisory = v80._apply_suba_volume_overlay_policy(base, None, pd.Series(False, index=dates), feature, True)
    result = v80._write_a_adk_query_overview(lambda *a: None, advisory, None, query_kind="signal")
    data = v80.generate_signal_excel("2026-09-29", result, [])
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as workbook:
        strings = ["".join(node.itertext()) for node in ET.fromstring(workbook.read("xl/sharedStrings.xml"))]
        sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        values = {cell.attrib["r"]: strings[int(cell.find("s:v", ns).text)]
                  for cell in sheet.findall(".//s:c", ns) if cell.attrib.get("t") == "s"}
    assert values["A2"] == "Sub-A"
    assert values["B2"] == "否"
    assert "不可" in values["C2"] and "不可" in values["D2"]


@pytest.mark.parametrize("policy_name", ["_apply_suba_volume_overlay_policy", "_apply_v78_suba_new_volume_overlay_policy"])
@pytest.mark.parametrize("clock,should_block", [("14:59:59", False), ("15:00:00", True), ("15:00:01", True)])
def test_current_close_risk_boundary(v80, monkeypatch, policy_name, clock, should_block):
    prices, result, signal, feature = source_with_old_gap(v80, monkeypatch, None)
    today = result.index[-1]
    monkeypatch.setattr(v80, "beijing_now", lambda: pd.Timestamp(f"{today.date()} {clock}").to_pydatetime())
    # Latest confirmed row is an active risk reduction. Today has no amount row.
    prior_signal = pd.Series(True, index=result.index[:-1])
    prior_feature = pd.DataFrame({"combined_unresolved": False,
                                  "combined_scale": v80.CN_SA_VOLUME_SCALE}, index=result.index[:-1])
    policy = getattr(v80, policy_name)
    if should_block:
        with pytest.raises(v80.poe.BotError):
            policy(result, prices, prior_signal, prior_feature)
    else:
        output = policy(result, prices, prior_signal, prior_feature)
        assert bool(output["suba_volume_rule_on"].iloc[-1])
        assert output["suba_volume_rule_scale"].iloc[-1] == v80.CN_SA_VOLUME_SCALE
        assert not output["suba_volume_combined_unresolved"].any()


@pytest.mark.parametrize("policy_name", ["_apply_suba_volume_overlay_policy", "_apply_v78_suba_new_volume_overlay_policy"])
def test_intraday_cannot_hide_missing_prior_confirmed_risk(v80, monkeypatch, policy_name):
    prices, result, signal, feature = source_with_old_gap(v80, monkeypatch, None)
    today = result.index[-1]
    monkeypatch.setattr(v80, "beijing_now", lambda: pd.Timestamp(f"{today.date()} 11:00:00").to_pydatetime())
    missing_prior = feature.drop(index=result.index[-2])
    with pytest.raises(v80.poe.BotError):
        getattr(v80, policy_name)(result, prices, signal, missing_prior)

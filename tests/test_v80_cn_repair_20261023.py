"""Missing amount observations must not silently disable Sub-A risk control."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    source = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_cn_repair_20261023", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def offline(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network/LLM disabled for offline regression")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.poe, "call", forbidden)


def rule_inputs(v80):
    dates = v80._expected_cn_sessions("2026-06-01", "2026-09-30")
    clear = pd.Series(100., index=dates)
    clear.iloc[-3:] = [80., 70., 60.]
    stay = pd.Series(np.linspace(100., 200., len(dates)), index=dates)
    return clear, stay


@pytest.mark.parametrize("fault", ["nan", "inf", "negative", "zero", "missing"])
def test_rule_marks_window_unknown_and_recovers_only_after_dependency(v80, fault):
    clear, _ = rule_inputs(v80)
    hit = clear.index[-15]
    if fault == "missing":
        clear = clear.drop(hit)
    else:
        clear.loc[hit] = {"nan": np.nan, "inf": np.inf, "negative": -1., "zero": 0.}[fault]
    result = v80._suba_amount_rule_frame(clear, 5, 3)
    offset = result.index.get_loc(hit)
    assert not result["known"].iloc[offset:offset+7].any()
    assert result["known"].iloc[offset+7:].all()
    assert result["streak"].iloc[offset:offset+7].isna().all()


@pytest.mark.parametrize("kind", ["duplicate", "timezone", "intraday", "unordered", "holiday"])
def test_bad_daily_index_rejected(v80, kind):
    clear, _ = rule_inputs(v80)
    if kind == "duplicate":
        clear = pd.concat([clear.iloc[:2], clear.iloc[1:]])
    elif kind == "timezone":
        clear.index = clear.index.tz_localize("Asia/Shanghai")
    elif kind == "intraday":
        clear.index = clear.index + pd.Timedelta(hours=15)
    elif kind == "unordered":
        clear = clear.iloc[::-1]
    else:
        clear.loc[pd.Timestamp("2026-09-25")] = 100.
        clear = clear.sort_index()
    with pytest.raises(v80.DataSchemaError):
        v80._suba_amount_rule_frame(clear, 5, 3)


@pytest.mark.parametrize("mode,other_clear,expected_known,expected_on", [
    ("or", True, True, True), ("or", False, False, False),
    ("and", True, False, False), ("and", False, True, False),
])
def test_three_state_combination(v80, mode, other_clear, expected_known, expected_on):
    clear, stay = rule_inputs(v80)
    bad = clear.copy()
    bad.iloc[-2] = np.nan
    signal, feature = v80._build_consecutive_below_amount_signal({
        "bad": {"amount": bad, "ma": 20, "days": 3},
        "other": {"amount": clear if other_clear else stay, "ma": 20, "days": 3},
    }, mode=mode)
    assert bool(signal.iloc[-1]) == expected_on
    assert bool(feature["combined_unresolved"].iloc[-1]) == (not expected_known)


def test_publication_boundary_is_inactive_not_unknown(v80):
    dates = v80._expected_cn_sessions("2023-06-01", "2023-10-31")
    signal, feature = v80._build_consecutive_below_amount_signal({
        "cyb": {"amount": pd.Series(np.linspace(100., 200., len(dates)), index=dates), "ma": 20, "days": 4},
        "zz": {"amount": pd.Series(np.linspace(200., 100., len(dates)), index=dates), "ma": 20, "days": 3,
               "publication_date": v80.CN_SA_VOLUME_ZZ2000_PUBLICATION_DATE},
    })
    before = feature.loc[:"2023-08-10"]
    assert not before["combined_unresolved"].any()
    assert before["zz_amount"].isna().all()
    assert not signal.loc[:"2023-08-10"].any()


def test_missing_last_session_is_unknown_even_without_nan_row(v80):
    clear, _ = rule_inputs(v80)
    result = v80._suba_amount_rule_frame(clear.iloc[:-1], 20, 3, expected_date=clear.index[-1])
    assert result.index[-1] == clear.index[-1]
    assert not result["known"].iloc[-1]


def test_leg_known_to_clear_can_resolve_other_missing_values(v80, monkeypatch):
    clear, stay = rule_inputs(v80)
    bad = stay.copy()
    bad.iloc[-2] = np.nan
    # CYB needs four below-MA observations; ZZ2000 needs three.
    clear.iloc[-4:] = [85., 80., 70., 60.]
    monkeypatch.setattr(v80, "_fetch_cn_csindex_amount", lambda *a, **k: bad.to_frame("amount"))
    monkeypatch.setattr(v80, "_fetch_cn_sohu_amount", lambda *a, **k: clear.to_frame("amount"))
    signal, feature = v80._load_suba_volume_signal(expected_date=clear.index[-1])
    assert signal.iloc[-1]
    assert not feature["combined_unresolved"].iloc[-1]
    assert feature["combined_scale"].iloc[-1] == 0.


def test_unknown_policy_rejects_formal_and_labels_advisory(v80):
    dates = pd.to_datetime(["2026-09-28", "2026-09-29"])
    base = pd.DataFrame({"holding": "X", "weight": 1., "return": 0.}, index=dates)
    feature = pd.DataFrame({"combined_unresolved": [False, True]}, index=dates)
    with pytest.raises(v80.poe.BotError):
        v80._apply_suba_volume_overlay_policy(base, None, pd.Series(False, index=dates), feature)
    advisory = v80._apply_suba_volume_overlay_policy(base, None, pd.Series(False, index=dates), feature, True)
    assert advisory["suba_volume_unresolved"].all()
    class Message:
        def write(self, text):
            self.text = getattr(self, "text", "") + text
    msg = Message()
    v80._write_suba_volume_query_warning(msg, advisory)
    assert "不应按正常仓位执行" in msg.text


def test_prepublication_request_does_not_require_unpublished_leg(v80, monkeypatch):
    dates = v80._expected_cn_sessions("2023-01-03", "2023-06-30")
    def fetch(secid, *a, **k):
        assert secid == v80.CN_SA_VOLUME_CYB_SECID
        return pd.DataFrame({"amount": np.linspace(100., 200., len(dates))}, index=dates), "synthetic"
    monkeypatch.setattr(v80, "_fetch_cn_amount_with_fallback", fetch)
    signal, feature = v80._load_suba_volume_signal(expected_date=dates[-1])
    assert not signal.any()
    # CYB is a vendor-truncated history, while ZZ2000 has not been published.
    width = v80.CN_SA_VOLUME_CYB_MA + v80.CN_SA_VOLUME_CYB_DAYS - 1
    assert feature["combined_unresolved"].iloc[:width - 1].all()
    assert not feature["combined_unresolved"].iloc[width - 1:].any()
    assert feature["zz2000_source"].eq("not-yet-published").all()


def test_confirmed_gate_ignores_only_current_unconfirmed_price_bar(v80, monkeypatch):
    consumer = pd.to_datetime(["2026-09-28", "2026-09-29"])
    feature = pd.DataFrame({"combined_unresolved": [False]}, index=consumer[:1])
    monkeypatch.setattr(v80, "beijing_now", lambda: pd.Timestamp("2026-09-29 14:00").to_pydatetime())
    assert not v80._suba_volume_feature_has_unresolved(feature, consumer)
    monkeypatch.setattr(v80, "beijing_now", lambda: pd.Timestamp("2026-09-29 15:01").to_pydatetime())
    assert v80._suba_volume_feature_has_unresolved(feature, consumer)


def test_gate_preserves_missing_leading_and_internal_sessions(v80):
    dates = pd.to_datetime(["2026-09-28", "2026-09-29", "2026-09-30"])
    for available in (dates[1:], dates[[0, 2]]):
        feature = pd.DataFrame({"combined_unresolved": False}, index=available)
        assert v80._suba_volume_feature_has_unresolved(feature, dates)

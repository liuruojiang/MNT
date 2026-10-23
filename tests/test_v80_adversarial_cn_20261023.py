"""Offline adversarial CN input cases; synthetic values are not performance data.

These required-contract tests failed against the original audited production file.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    path = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("audit_v80_cn_20261023", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def local_only(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline CN audit forbids network and LLM")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.poe, "call", forbidden)


def load_amount_case(v80, monkeypatch, fault=None):
    dates = pd.bdate_range("2026-06-01", "2026-09-24")
    dates = dates[~dates.isin(pd.to_datetime(sorted(v80.CN_MARKET_HOLIDAYS)))]
    zz = pd.DataFrame({"amount": np.full(len(dates), 100.)}, index=dates)
    zz.iloc[-3:, 0] = [80., 70., 60.]
    if fault == "nan":
        zz.iloc[-2, 0] = np.nan
    elif fault == "missing":
        zz = zz.drop(dates[-2])
    cyb = pd.DataFrame({"amount": np.linspace(100., 200., len(dates))}, index=dates)
    monkeypatch.setattr(v80, "_fetch_cn_csindex_amount", lambda *a, **kw: zz.copy())
    monkeypatch.setattr(v80, "_fetch_cn_sohu_amount", lambda *a, **kw: cyb.copy())
    signal, feature = v80._load_suba_volume_signal(expected_date=dates[-1])
    feature = v80._annotate_rule_freshness(feature, dates[-1], "suba_volume")
    return signal, feature


def test_complete_amount_history_triggers_cash(v80, monkeypatch):
    signal, feature = load_amount_case(v80, monkeypatch)
    assert bool(signal.iloc[-1])
    assert feature["combined_scale"].iloc[-1] == 0.
    # This assertion concerns the final decision, after the source warmup.
    assert not v80._suba_volume_feature_has_unresolved(feature, feature.index[-1:])


@pytest.mark.parametrize("fault", [None, "nan", "missing"])
def test_amount_gap_reaches_native_suba_execution_weight(v80, monkeypatch, fault):
    signal, feature = load_amount_case(v80, monkeypatch, fault)
    t = np.arange(len(feature), dtype=float)
    cn = pd.DataFrame({code: 100. * np.exp(.0001 * t * t)
                       for code in v80.CN_EQUITY_CODES}, index=feature.index)
    cn[v80.CN_BOND_CODE] = 100.
    base = v80.run_cn_strategy(cn, list(v80.CN_EQUITY_CODES))
    assert base["weight"].iloc[-1] > 0.
    try:
        actual = v80._apply_suba_volume_overlay_policy(
            base, cn, signal, feature, allow_unresolved_suba_volume=False)
    except v80.poe.BotError:
        assert fault is not None
        return
    assert actual["weight"].iloc[-1] == 0., (
        f"fault={fault}: formal policy accepted incomplete source; "
        f"holding={actual['holding'].iloc[-1]}, weight={actual['weight'].iloc[-1]}, "
        f"overlay={actual['suba_volume_rule_scale'].iloc[-1]}"
    )


@pytest.mark.parametrize("fault", ["nan", "missing"])
def test_internal_amount_gap_must_not_silently_restore_risk(v80, monkeypatch, fault):
    try:
        signal, feature = load_amount_case(v80, monkeypatch, fault)
    except (v80.DataSchemaError, v80.DataUnavailableError, v80.poe.BotError):
        return  # Explicit rejection is also a safe valid outcome.
    assert v80._suba_volume_feature_has_unresolved(feature, feature.index[-1:]), (
        f"{fault} accepted: latest signal={bool(signal.iloc[-1])}, "
        f"scale={feature['combined_scale'].iloc[-1]}, "
        f"freshness_ok={feature['freshness_ok'].iloc[-1]}, "
        f"unresolved={feature['combined_unresolved'].iloc[-1]}"
    )


@pytest.mark.parametrize("sleeve", ["suba", "adk"])
def test_production_cn_calculation_is_prefix_invariant(v80, sleeve):
    dates = pd.bdate_range("2024-01-02", periods=430)
    t = np.arange(len(dates), dtype=float)
    codes = list(v80.CN_EQUITY_CODES) + [v80.CN_BOND_CODE]
    cn = pd.DataFrame({code: 100. * np.exp(np.cumsum(
        .001 + .012 * np.sin(t / (7. + j) + j)))
        for j, code in enumerate(codes)}, index=dates)
    dk = pd.DataFrame({code: 100. * np.exp(np.cumsum(
        .001 + .012 * np.sin(t / (6. + j) + j)))
        for j, code in enumerate(v80.CN_DK_COLS)}, index=dates)
    if sleeve == "suba":
        full = v80.run_cn_strategy(cn, list(v80.CN_EQUITY_CODES))
        prefix = v80.run_cn_strategy(cn.iloc[:370], list(v80.CN_EQUITY_CODES))
    else:
        full = v80.run_v80_adk_new_only(cn, dk)
        prefix = v80.run_v80_adk_new_only(cn.iloc[:370], dk.iloc[:370])
    for column in ["return", "nav", "weight", "holding"]:
        actual = prefix[column].copy()
        expected = full.loc[prefix.index, column].copy()
        actual.attrs = {}
        expected.attrs = {}
        pd.testing.assert_series_equal(actual, expected)

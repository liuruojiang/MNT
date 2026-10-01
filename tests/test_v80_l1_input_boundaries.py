"""Adversarial L1 checks for publication and input-clock boundaries."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    path = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_l1_boundaries", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_cn_stock_frame_starts_on_latest_component_publication(v80):
    dates = pd.to_datetime(["2017-05-24", "2017-05-25", "2017-05-26", "2017-05-29"])
    raw = {code: pd.DataFrame({"close": [100.0, 101.0, 102.0, 103.0]}, index=dates)
           for code in v80.CN_STOCK_CODES}
    frame = v80._build_cn_stock_close_frame(raw)
    assert frame.index[0] == pd.Timestamp("2017-05-26")
    assert len(frame) == 2


def test_zz2000_amount_cannot_signal_before_publication(v80, monkeypatch):
    dates = pd.bdate_range("2023-06-01", "2023-10-13")
    zz2000 = pd.DataFrame({"amount": np.linspace(200.0, 20.0, len(dates))}, index=dates)
    cyb = pd.DataFrame({"amount": np.linspace(20.0, 200.0, len(dates))}, index=dates)

    def fake_fetch(secid, label, **kwargs):
        frame = zz2000 if secid == v80.CN_SA_VOLUME_ZZ2000_SECID else cyb
        return frame, "test"

    monkeypatch.setattr(v80, "_fetch_cn_amount_with_fallback", fake_fetch)
    _signal, feature = v80._load_suba_volume_signal(expected_date=dates[-1])
    pre = feature.loc[feature.index < v80.CN_SA_VOLUME_ZZ2000_PUBLICATION_DATE]
    assert pre["zz2000_amount"].isna().all()
    assert not pre["zz2000_signal"].fillna(False).any()
    assert feature.loc[feature.index >= v80.CN_SA_VOLUME_ZZ2000_PUBLICATION_DATE, "zz2000_amount"].notna().any()


def test_etf_listing_close_cannot_change_same_day_model_open(v80):
    dates = pd.to_datetime(["2024-01-10", "2024-01-11", "2024-01-12"])
    proxy_open = pd.Series([98.0, 99.0, 101.0], index=dates)
    proxy_close = pd.Series([99.0, 100.0, 102.0], index=dates)
    live_open = pd.Series([np.nan, 9.0, 11.0], index=dates)
    first = v80._build_proxy_live_open_spliced_series(
        proxy_open, proxy_close, live_open, pd.Series([np.nan, 10.0, 12.0], index=dates))
    changed_close = v80._build_proxy_live_open_spliced_series(
        proxy_open, proxy_close, live_open, pd.Series([np.nan, 20.0, 12.0], index=dates))
    assert first.loc["2024-01-11"] == changed_close.loc["2024-01-11"] == 99.0
    assert first.loc["2024-01-12"] != changed_close.loc["2024-01-12"]


def test_cn_asof_cap_discards_future_row(v80):
    dates = pd.to_datetime(["2026-09-24", "2026-09-28"])
    raw = pd.DataFrame({"close": [100.0, 200.0]}, index=dates)
    capped = v80._drop_cn_rows_after(raw, pd.Timestamp("2026-09-24"))
    assert capped.index.tolist() == [pd.Timestamp("2026-09-24")]


def test_amount_loader_caps_future_rows(v80, monkeypatch):
    dates = pd.bdate_range("2026-07-01", "2026-09-28")
    frame = pd.DataFrame({"amount": np.linspace(100.0, 200.0, len(dates))}, index=dates)

    def fake_fetch(secid, label, **kwargs):
        return frame.copy(), "test"

    monkeypatch.setattr(v80, "_fetch_cn_amount_with_fallback", fake_fetch)
    signal, feature = v80._load_suba_volume_signal(expected_date=pd.Timestamp("2026-09-24"))
    assert signal.index.max() == feature.index.max() == pd.Timestamp("2026-09-24")

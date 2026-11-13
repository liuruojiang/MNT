"""Real 2026-11-13 response subsets; fault injections are explicit counterexamples.

The clear CYB leg used in loader tests is synthetic, not a current trading signal.
No network, model calls or performance conclusions are allowed in this suite.
"""
import copy
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = pd.read_csv(ROOT / 'tests/fixtures/v80_zz2000_fallback_20261113.csv')


@pytest.fixture(scope='module')
def v80():
    spec = importlib.util.spec_from_file_location('v80_zz2000_backup_tests', ROOT / 'mnt_bot V 8.0 plus.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def feeds(v80, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError('No network or model calls in frozen-source tests')
    monkeypatch.setattr(v80.requests.sessions.Session, 'request', forbidden)
    monkeypatch.setattr(v80.poe, 'call', forbidden)
    monkeypatch.setattr(v80.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(v80, 'beijing_now', lambda: v80.datetime(2026, 11, 13, 18, 30))
    rows = SAMPLE.dropna(subset=['csi_amount']).copy()
    official = pd.DataFrame({'close': rows.csi_close.to_numpy(), 'amount': rows.csi_amount.to_numpy()}, index=pd.to_datetime(rows.date))
    payload = {'rc': 0, 'data': {'code': '932000', 'market': 2, 'name': '中证2000', 'klines': [
        ','.join(str(row[k]) for k in ['date', 'open', 'close', 'high', 'low', 'volume', 'amount'])
        for row in SAMPLE.to_dict('records')]}}
    calls = []
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return copy.deepcopy(payload)
    def get(url, **kwargs):
        calls.append(url)
        assert 'secid=2.932000&' in url
        return Response()
    monkeypatch.setattr(v80._session, 'get', get)
    monkeypatch.setattr(v80, '_fetch_cn_csindex_amount', lambda *a, **k: official.copy())
    return official, payload, calls


def load(v80, expected='2026-11-13'):
    return v80._fetch_cn_amount_with_fallback(v80.CN_SA_VOLUME_ZZ2000_SECID, 'ZZ2000', expected_date=pd.Timestamp(expected))


def load_rules(v80, monkeypatch, expected='2026-11-13'):
    dates = pd.to_datetime(SAMPLE.date)
    # Deliberately synthetic non-triggering CYB leg to isolate ZZ2000's rule.
    clear = pd.DataFrame({'amount': np.arange(len(dates), dtype=float) + 100}, index=dates)
    monkeypatch.setattr(v80, '_fetch_cn_sohu_amount', lambda *a, **k: clear.copy())
    return v80._load_suba_volume_signal(expected_date=pd.Timestamp(expected))


def test_fresh_primary_does_not_request_backup(v80, feeds):
    official, _, calls = feeds
    result, source = load(v80, '2026-11-11')
    pd.testing.assert_series_equal(result.amount, official.amount)
    assert source == 'CSIndex official amount'
    assert not calls


@pytest.mark.parametrize('expected', ['2026-11-12', '2026-11-13'])
def test_real_stale_primary_uses_normalized_backup_and_preserves_prefix(v80, feeds, expected):
    official, _, calls = feeds
    result, source = load(v80, expected)
    assert len(calls) == 1
    assert 'EastMoney' in source
    pd.testing.assert_series_equal(result.loc[official.index, 'amount'], official.amount, check_freq=False)
    assert result.loc['2026-11-12', 'amount'] == pytest.approx(4071.42699488)
    assert result.loc['2026-11-13', 'amount'] == pytest.approx(3422.01381977)


def test_primary_transport_outage_uses_verified_backup(v80, feeds, monkeypatch):
    def outage(*a, **k):
        raise v80.requests.ConnectionError('explicit primary outage')
    monkeypatch.setattr(v80, '_fetch_cn_csindex_amount', outage)
    result, source = load(v80)
    assert source.startswith('EastMoney')
    assert result.amount.iloc[-1] == pytest.approx(3422.01381977)


@pytest.mark.parametrize('field,value', [('code', '932001'), ('market', 1)])
def test_wrong_index_or_market_is_refused(v80, feeds, field, value):
    _, payload, _ = feeds
    payload['data'][field] = value
    with pytest.raises(v80.DataUnavailableError, match='identity mismatch'):
        load(v80)


def test_conflicting_same_index_amount_is_not_silently_accepted(v80, feeds):
    _, payload, _ = feeds
    fields = payload['data']['klines'][-3].split(',')
    fields[6] = str(float(fields[6]) * 1.05)
    payload['data']['klines'][-3] = ','.join(fields)
    with pytest.raises(v80.VerifiedDataRepairConflict, match='2026-11-11'):
        load(v80)


@pytest.mark.parametrize('fault', ['stale', 'zero'])
def test_backup_must_have_current_positive_amount(v80, feeds, fault):
    _, payload, _ = feeds
    if fault == 'stale':
        payload['data']['klines'] = payload['data']['klines'][:-2]
    else:
        for i in (-1, -2):
            fields = payload['data']['klines'][i].split(',')
            fields[6] = '0'
            payload['data']['klines'][i] = ','.join(fields)
    with pytest.raises(v80.DataUnavailableError, match='latest valid amount 2026-11-11 < expected 2026-11-13'):
        load(v80)


@pytest.mark.parametrize('expected', ['2026-11-12', '2026-11-13'])
def test_real_backup_reaches_native_rule_without_future_bars(v80, feeds, monkeypatch, expected):
    _, feature = load_rules(v80, monkeypatch, expected)
    assert feature.index[-1] == pd.Timestamp(expected)
    assert not bool(feature.combined_unresolved.iloc[-1])
    assert 'EastMoney' in feature.zz2000_source.iloc[-1]


def test_missing_dependency_session_still_makes_latest_rule_unknown(v80, feeds, monkeypatch):
    _, payload, _ = feeds
    del payload['data']['klines'][-2]  # Missing 11/12 cannot be filled by stale CSI.
    _, feature = load_rules(v80, monkeypatch)
    assert bool(feature.combined_unresolved.iloc[-1])


@pytest.mark.parametrize('kind', ['signal', 'live_signal', 'params', 'live_params'])
def test_all_query_surfaces_show_fallback_source(v80, feeds, monkeypatch, kind):
    _, source = load(v80)
    dates = pd.to_datetime(['2026-11-12', '2026-11-13'])
    cn = pd.DataFrame({'holding': '1.000016', 'weight': [1.2052, 1.2046],
                       'suba_volume_zz2000_source': source,
                       'suba_volume_unresolved': False}, index=dates)
    output = []
    v80._write_a_adk_query_overview(output.append, cn, None, query_kind=kind)
    assert source in ''.join(output)
    assert '诊断目标（不可执行）' not in ''.join(output)

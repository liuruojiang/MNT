"""Independent data-contract adversaries for ZZ2000 amount failover.

Base observations come from the captured 2026-11-13 CSV. Malformed responses,
business errors and the clear CYB leg are explicit synthetic fault injections.
This suite makes no network calls and makes no performance claims.
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
def model():
    spec = importlib.util.spec_from_file_location('v80_zz2000_integrity_adversary', ROOT / 'mnt_bot V 8.0 plus.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def feeds(model, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError('Independent adversary forbids network and model calls')
    monkeypatch.setattr(model.requests.sessions.Session, 'request', forbidden)
    monkeypatch.setattr(model.poe, 'call', forbidden)
    monkeypatch.setattr(model.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(model, 'beijing_now', lambda: model.datetime(2026, 11, 13, 19, 0))
    observed = SAMPLE.dropna(subset=['csi_amount'])
    official = pd.DataFrame({'close': observed.csi_close.to_numpy(), 'amount': observed.csi_amount.to_numpy()}, index=pd.to_datetime(observed.date))
    payload = {'rc': 0, 'data': {'code': '932000', 'market': 2, 'name': '中证2000', 'klines': [
        ','.join(str(row[k]) for k in ['date', 'open', 'close', 'high', 'low', 'volume', 'amount'])
        for row in SAMPLE.to_dict('records')]}}
    state = {'official': official, 'payload': payload, 'primary_down': False, 'backup_down': False, 'calls': []}
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return copy.deepcopy(state['payload'])
    def get(url, **kw):
        assert 'secid=2.932000&' in url
        state['calls'].append(url)
        if state['backup_down']:
            raise model.requests.ConnectionError('injected backup outage')
        return Response()
    def primary(*a, **kw):
        if state['primary_down']:
            raise model.requests.ConnectionError('injected primary outage')
        return state['official'].copy()
    monkeypatch.setattr(model._session, 'get', get)
    monkeypatch.setattr(model, '_fetch_cn_csindex_amount', primary)
    dates = pd.to_datetime(SAMPLE.date)
    clear_cyb = pd.DataFrame({'amount': 100.0 + np.arange(len(dates))}, index=dates)
    monkeypatch.setattr(model, '_fetch_cn_sohu_amount', lambda *a, **kw: clear_cyb.copy())
    return state


def get_amount(model):
    return model._fetch_cn_amount_with_fallback(model.CN_SA_VOLUME_ZZ2000_SECID, 'ZZ2000', expected_date=pd.Timestamp('2026-11-13'))


def get_rule(model):
    return model._load_suba_volume_signal(expected_date=pd.Timestamp('2026-11-13'))[1]


@pytest.mark.parametrize('business_error', [1, -1, 105])
def test_business_failure_must_not_become_authoritative_amount(model, feeds, business_error):
    feeds['primary_down'] = True
    feeds['payload']['rc'] = business_error
    # Complete-looking stale/cached data cannot override the provider's failure flag.
    with pytest.raises(model.DataUnavailableError):
        get_amount(model)


@pytest.mark.parametrize('malformation', ['non_object_data', 'text_klines', 'short_row', 'non_text_row'])
def test_malformed_backup_is_classified_data_failure(model, feeds, malformation):
    feeds['primary_down'] = True
    if malformation == 'non_object_data':
        feeds['payload']['data'] = ['unexpected object type']
    elif malformation == 'text_klines':
        feeds['payload']['data']['klines'] = 'not a row collection'
    elif malformation == 'short_row':
        feeds['payload']['data']['klines'][-1] = '2026-11-13,1,2,3,4,5'
    else:
        feeds['payload']['data']['klines'][-1] = ['2026-11-13', 'not CSV text']
    with pytest.raises(model.DataUnavailableError):
        get_amount(model)


@pytest.mark.parametrize('bad_amount', ['nan', 'inf', '-inf', '-1', '0', 'True'])
def test_nonfinite_or_nonpositive_latest_amount_remains_unavailable(model, feeds, bad_amount):
    feeds['primary_down'] = True
    fields = feeds['payload']['data']['klines'][-1].split(',')
    fields[6] = bad_amount
    feeds['payload']['data']['klines'][-1] = ','.join(fields)
    with pytest.raises(model.DataUnavailableError):
        get_amount(model)


def test_duplicate_backup_day_cannot_generate_known_native_rule(model, feeds):
    feeds['primary_down'] = True
    feeds['payload']['data']['klines'].append(feeds['payload']['data']['klines'][-1])
    result = get_rule(model)
    assert bool(result.combined_unresolved.iloc[-1])


def test_reversed_vendor_rows_preserve_values_after_daily_sort(model, feeds):
    feeds['primary_down'] = True
    feeds['payload']['data']['klines'].reverse()
    result, _ = get_amount(model)
    assert result.index.is_monotonic_increasing
    assert result.loc['2026-11-13', 'amount'] == pytest.approx(3422.01381977)


def test_current_primary_with_dependency_hole_tries_complete_backup(model, feeds):
    # Extend the injected primary with observed same-index tail values, then
    # remove an interior required date. This tests selection, not source claims.
    tail = SAMPLE.tail(2)
    extension = pd.DataFrame({'close': tail.close.to_numpy(), 'amount': tail.amount.to_numpy() / 1e8}, index=pd.to_datetime(tail.date))
    complete = pd.concat([feeds['official'], extension]).sort_index()
    feeds['official'] = complete.drop(pd.Timestamp('2026-11-12'))
    result = get_rule(model)
    assert feeds['calls'], 'Fresh end date alone must not bypass fallback for a dependency hole'
    assert not bool(result.combined_unresolved.iloc[-1])


def test_units_changed_in_overlap_are_integrity_conflict(model, feeds):
    for i, line in enumerate(feeds['payload']['data']['klines']):
        fields = line.split(',')
        fields[6] = str(float(fields[6]) / 1e8)  # Explicitly wrong provider unit.
        feeds['payload']['data']['klines'][i] = ','.join(fields)
    with pytest.raises(model.VerifiedDataRepairConflict):
        get_amount(model)


def test_both_sources_unavailable_leave_native_rule_unknown(model, feeds):
    feeds['primary_down'] = feeds['backup_down'] = True
    result = get_rule(model)
    assert bool(result.combined_unresolved.iloc[-1])


def test_backup_weekend_in_required_interval_is_not_a_valid_rule(model, feeds):
    feeds['primary_down'] = True
    fields = feeds['payload']['data']['klines'][-5].split(',')
    fields[0] = '2026-11-07'  # Saturday; explicit corrupt extra observation.
    feeds['payload']['data']['klines'].append(','.join(fields))
    result = get_rule(model)
    assert bool(result.combined_unresolved.iloc[-1])


@pytest.mark.parametrize('bad_rc', [False, 0.0, '0', None])
def test_business_success_flag_has_explicit_integer_type(model, feeds, bad_rc):
    feeds['primary_down'] = True
    feeds['payload']['rc'] = bad_rc
    with pytest.raises(model.DataUnavailableError):
        get_amount(model)


def complete_injected_primary(feeds):
    """Observed same-index values; the primary's newly added tail is injected."""
    tail = SAMPLE.tail(2)
    extension = pd.DataFrame({'close': tail.close.to_numpy(), 'amount': tail.amount.to_numpy() / 1e8}, index=pd.to_datetime(tail.date))
    feeds['official'] = pd.concat([feeds['official'], extension]).sort_index()


@pytest.mark.parametrize('bad_primary', [float('nan'), float('inf'), -1.0])
def test_invalid_primary_amount_is_repaired_without_overwriting_good_prefix(model, feeds, bad_primary):
    complete_injected_primary(feeds)
    original = feeds['official'].copy()
    feeds['official'].loc[pd.Timestamp('2026-11-12'), 'amount'] = bad_primary
    result, _ = get_amount(model)
    good = original.index.difference(pd.to_datetime(['2026-11-12']))
    pd.testing.assert_series_equal(result.loc[good, 'amount'], original.loc[good, 'amount'], check_freq=False)
    assert result.loc['2026-11-12', 'amount'] == pytest.approx(4071.42699488)


@pytest.mark.parametrize('bad_backup', ['nan', 'inf', '-1'])
def test_both_sources_invalid_at_same_dependency_session_stay_unknown(model, feeds, bad_backup):
    complete_injected_primary(feeds)
    feeds['official'].loc[pd.Timestamp('2026-11-12'), 'amount'] = float('nan')
    fields = feeds['payload']['data']['klines'][-2].split(',')
    fields[6] = bad_backup
    feeds['payload']['data']['klines'][-2] = ','.join(fields)
    result = get_rule(model)
    assert bool(result.combined_unresolved.iloc[-1])


def test_primary_old_historical_hole_also_triggers_validated_repair(model, feeds):
    complete_injected_primary(feeds)
    feeds['official'] = feeds['official'].drop(pd.Timestamp('2026-09-01'))
    result, _ = get_amount(model)
    assert feeds['calls']
    assert result.loc['2026-09-01', 'amount'] == pytest.approx(4211.01468546)


def test_fresh_primary_hole_and_failed_backup_remain_unknown(model, feeds):
    complete_injected_primary(feeds)
    feeds['official'] = feeds['official'].drop(pd.Timestamp('2026-11-12'))
    feeds['payload']['rc'] = 1
    result = get_rule(model)
    assert bool(result.combined_unresolved.iloc[-1])


def test_future_backup_observation_does_not_fill_missing_required_close(model, feeds):
    feeds['primary_down'] = True
    fields = feeds['payload']['data']['klines'].pop().split(',')
    fields[0] = '2026-11-16'  # Explicit future observation replacing required 11/13.
    feeds['payload']['data']['klines'].append(','.join(fields))
    result = get_rule(model)
    assert result.index[-1] == pd.Timestamp('2026-11-13')
    assert bool(result.combined_unresolved.iloc[-1])


def test_extra_future_backup_bar_is_excluded_from_native_rule(model, feeds):
    fields = feeds['payload']['data']['klines'][-1].split(',')
    fields[0], fields[6] = '2026-11-16', '99999999999999'
    feeds['payload']['data']['klines'].append(','.join(fields))
    result = get_rule(model)
    assert result.index[-1] == pd.Timestamp('2026-11-13')
    assert not bool(result.combined_unresolved.iloc[-1])

"""Real archived prices; explicit corruption/scheduling controls, not simulated returns."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(os.environ.get('V80_REPAIR_REPO', Path(__file__).resolve().parents[1]))
SOURCE = Path(os.environ.get('V80_REPAIR_SOURCE', ROOT / 'mnt_bot V 8.0 plus.py'))
spec = importlib.util.spec_from_file_location('v80_integrity_review_tests', SOURCE)
M = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = M
spec.loader.exec_module(M)
PAYLOAD = json.loads((ROOT / 'tests/fixtures/v80_verified_data_20261025/yahoo_kmlm.json').read_text(encoding='utf-8'))
R = PAYLOAD['chart']['result'][0]
DATES = pd.to_datetime(R['timestamp'], unit='s', utc=True).tz_localize(None).normalize()
IP = DATES.get_loc(pd.Timestamp('2022-12-27'))


class Response:
    status_code = 200
    def __init__(self, value): self.value = value
    def json(self): return copy.deepcopy(self.value)
    def raise_for_status(self): pass


def prices(r): return r['indicators']['adjclose'][0]['adjclose']


@pytest.fixture(autouse=True)
def isolation(monkeypatch):
    M._V80_INTEGRITY_CONFLICTS.clear()
    M._V80_INTEGRITY_COVERAGE.clear()
    monkeypatch.setattr(M, '_V80_INTEGRITY_GENERATION', 0)
    monkeypatch.setattr(M, '_latest_us_required_close_date', lambda *a, **k: pd.Timestamp('2026-10-23'))
    monkeypatch.setattr(M.time, 'sleep', lambda *_: None)
    def forbidden(*a, **k): raise AssertionError('Unarchived network/fallback forbidden')
    monkeypatch.setattr(M._session, 'get', forbidden)
    monkeypatch.setattr(M, '_fetch_us_stooq', forbidden)
    yield
    M._V80_INTEGRITY_CONFLICTS.clear()
    M._V80_INTEGRITY_COVERAGE.clear()


def good(monkeypatch, payload=None):
    monkeypatch.setattr(M._session, 'get', lambda *a, **k: Response(PAYLOAD if payload is None else payload))
    return M.fetch_yahoo('KMLM')[0]


def poison(monkeypatch):
    bad = copy.deepcopy(PAYLOAD)
    bad['chart']['result'][0]['indicators'].pop('adjclose')
    monkeypatch.setattr(M._session, 'get', lambda *a, **k: Response(bad))
    with pytest.raises(M.VerifiedDataRepairConflict): M.fetch_yahoo('KMLM')


def sliced(payload, mask):
    p = copy.deepcopy(payload); r = p['chart']['result'][0]
    keep = np.flatnonzero(mask)
    r['timestamp'] = [r['timestamp'][i] for i in keep]
    for block in r['indicators']['quote'] + r['indicators']['adjclose']:
        for key, values in block.items(): block[key] = [values[i] for i in keep]
    return p


@pytest.mark.parametrize('seam', ['2022-12-28', '2023-01-31', '2023-06-01', '2024-12-16', '2024-12-17', '2025-12-22', '2026-10-21'])
@pytest.mark.parametrize('gap', [False, True])
def test_partial_suffix_cannot_hide_behind_event_or_missing_pair(monkeypatch, seam, gap):
    corrected, _ = M._repair_verified_kmlm_distribution('KMLM', R['timestamp'], R['indicators']['quote'][0], prices(R))
    scale = corrected[IP] / prices(R)[IP]
    p = copy.deepcopy(PAYLOAD); r = p['chart']['result'][0]
    through = np.flatnonzero(DATES <= pd.Timestamp(seam))
    for i in through: prices(r)[i] *= scale
    if gap:
        i = through[-1] + 1
        r['indicators']['quote'][0]['close'][i] = None; prices(r)[i] = None
    monkeypatch.setattr(M._session, 'get', lambda *a, **k: Response(p))
    with pytest.raises(M.VerifiedDataRepairConflict): M.fetch_yahoo('KMLM')
    assert M._v80_integrity_pending('KMLM')


@pytest.mark.parametrize('malformed', [False, True])
def test_postevent_only_slice_is_unchanged_or_rejected(monkeypatch, malformed):
    p = sliced(PAYLOAD, DATES >= pd.Timestamp('2023-01-03'))
    r = p['chart']['result'][0]
    if malformed:
        days = pd.to_datetime(r['timestamp'], unit='s', utc=True).tz_localize(None).normalize()
        for i in np.flatnonzero(days <= pd.Timestamp('2023-06-01')): prices(r)[i] *= .9512297157967274
    monkeypatch.setattr(M._session, 'get', lambda *a, **k: Response(p))
    if malformed:
        with pytest.raises(M.VerifiedDataRepairConflict): M.fetch_yahoo('KMLM', start_date='2023-01-03')
    else:
        f, source = M.fetch_yahoo('KMLM', start_date='2023-01-03')
        np.testing.assert_array_equal(f.close, prices(r)); assert source == 'Yahoo'


@pytest.mark.parametrize('defect', ['missing', 'short', 'scalar', 'boolean-time', 'duplicate-time', 'suffix-nan'])
def test_corporate_input_schema_cannot_escape_to_stooq(monkeypatch, defect):
    p = copy.deepcopy(PAYLOAD); r = p['chart']['result'][0]
    if defect == 'missing': r['indicators'].pop('adjclose')
    elif defect == 'short': prices(r).pop()
    elif defect == 'scalar': r['indicators']['adjclose'] = [42]
    elif defect == 'boolean-time': r['timestamp'][0] = True
    elif defect == 'duplicate-time': r['timestamp'][1] = r['timestamp'][0]
    else: prices(r)[-2] = None
    monkeypatch.setattr(M._session, 'get', lambda *a, **k: Response(p))
    with pytest.raises(M.VerifiedDataRepairConflict): M.fetch_yahoo('KMLM')


@pytest.mark.parametrize('previous_coverage', [False, True])
def test_next_network_failure_cannot_reenable_fallback(monkeypatch, previous_coverage):
    if previous_coverage: good(monkeypatch)
    poison(monkeypatch)
    def offline(*a, **k): raise M.requests.ConnectionError('explicit later outage')
    monkeypatch.setattr(M._session, 'get', offline)
    with pytest.raises(M.VerifiedDataRepairConflict): M.fetch_yahoo('KMLM')


@pytest.mark.parametrize('upstream_complete', [False, True])
def test_fresh_complete_yahoo_can_restore_trust(monkeypatch, upstream_complete):
    expected = good(monkeypatch)
    poison(monkeypatch)
    p = copy.deepcopy(PAYLOAD)
    if upstream_complete:
        r = p['chart']['result'][0]
        r['indicators']['adjclose'][0]['adjclose'], _ = M._repair_verified_kmlm_distribution('KMLM', r['timestamp'], r['indicators']['quote'][0], prices(r))
    restored = good(monkeypatch, p)
    pd.testing.assert_frame_equal(expected, restored)
    assert not M._v80_integrity_pending()


@pytest.mark.parametrize('prior,kind,start', [(False,'late','2021-01-04'), (True,'late','2021-01-04'), (False,'stale','2003-01-01'), (True,'stale','2003-01-01')])
def test_recovery_cannot_truncate_history_or_confirmation(prior, kind, start, monkeypatch):
    if prior: good(monkeypatch)
    poison(monkeypatch)
    mask = DATES >= pd.Timestamp(start) if kind == 'late' else DATES < pd.Timestamp('2026-10-23')
    p = sliced(PAYLOAD, mask)
    monkeypatch.setattr(M._session, 'get', lambda *a, **k: Response(p))
    with pytest.raises(M.VerifiedDataRepairConflict): M.fetch_yahoo('KMLM', start_date=start)
    assert M._v80_integrity_pending()


def test_paired_gap_keeps_existing_same_ticker_repair(monkeypatch):
    p = copy.deepcopy(PAYLOAD); r = p['chart']['result'][0]
    i = DATES.get_loc(pd.Timestamp('2023-06-01'))
    r['indicators']['quote'][0]['close'][i] = None; prices(r)[i] = None
    raw = pd.DataFrame({key:R['indicators']['quote'][0][key] for key in ['open','close']}, index=DATES)
    monkeypatch.setattr(M._session, 'get', lambda *a, **k: Response(p))
    # Real daily raw observations stand in for a Nasdaq transport control only.
    monkeypatch.setattr(M, '_fetch_us_nasdaq_history', lambda *a, **k: raw.copy())
    f, source = M.fetch_yahoo('KMLM')
    assert len(f) == 1480 and source.startswith('Yahoo+Nasdaq-gap')


def control_frames(monkeypatch):
    f = good(monkeypatch)
    # These are cache-wrapper controls; they are never interpreted as a backtest.
    return tuple(f.copy(deep=True) for _ in range(4))


def test_request_cache_and_old_input_references_cannot_revive(monkeypatch):
    data = control_frames(monkeypatch); bot = M.CombinedStrategyV80()
    monkeypatch.setattr(bot, '_fetch_data', lambda *a, **k: tuple(f.copy(deep=True) for f in data))
    old = bot._cached_fetch_data(None)
    bot._request_strategy_cache = {'old': 'must not survive'}
    poison(monkeypatch)
    with pytest.raises(M.VerifiedDataRepairConflict): bot._cached_fetch_data(None)
    assert not bot._request_data_cache and not bot._request_strategy_cache
    good(monkeypatch)
    with pytest.raises(M.VerifiedDataRepairConflict): bot._cached_run_strategies(*old)
    fresh = bot._cached_fetch_data(None)
    monkeypatch.setattr(bot, '_run_strategies', lambda *a, **k: ('fresh valid wrapper control',))
    assert bot._cached_run_strategies(*fresh) == ('fresh valid wrapper control',)


@pytest.mark.parametrize('stage', ['fetch', 'strategy'])
def test_inflight_computation_cannot_publish_after_conflict_and_recovery(monkeypatch, stage):
    data = control_frames(monkeypatch); bot = M.CombinedStrategyV80()
    def interrupted(*a, **k):
        poison(monkeypatch); good(monkeypatch)
        return data if stage == 'fetch' else ('must never publish',)
    if stage == 'fetch':
        monkeypatch.setattr(bot, '_fetch_data', interrupted)
        with pytest.raises(M.VerifiedDataRepairConflict): bot._cached_fetch_data(None)
        assert not bot._request_data_cache
    else:
        monkeypatch.setattr(bot, '_run_strategies', interrupted)
        with pytest.raises(M.VerifiedDataRepairConflict): bot._cached_run_strategies(*data)
        assert not bot._request_strategy_cache


def test_final_message_and_attachment_are_guarded_after_calculation(monkeypatch):
    good(monkeypatch)
    emitted = []
    class Sink:
        def write(self, value): emitted.append(('text',value))
        def attach_file(self, **kwargs): emitted.append(('file',kwargs))
    proxy = M._V80VerifiedMessage(Sink(), M._v80_integrity_generation())
    proxy.write('valid before any conflict')
    poison(monkeypatch)
    for action in [lambda:proxy.write('old normal signal'), lambda:proxy.attach_file(name='old.xlsx', contents=b'control')]:
        with pytest.raises(M.VerifiedDataRepairConflict): action()
    good(monkeypatch)
    with pytest.raises(M.VerifiedDataRepairConflict): proxy.write('old computation after recovery')
    assert emitted == [('text','valid before any conflict')]

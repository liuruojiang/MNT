"""Offline replays of the 2026-11-16..19 nine-ETF Yahoo/Tiingo/Nasdaq tail."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest


# For each ETF, these are the Tiingo and Nasdaq independently matching native
# (open, close) pairs. Yahoo's three actual overlap pairs were the same values
# rounded to binary32. No source showed a distribution or split in this window.
QUOTES = {
    'AVDV': [(103.715, 102.84), (102.21, 101.71), (101.01, 100.45), (100.14, 98.50)],
    'AVUV': [(122.05, 120.77), (120.13, 119.00), (118.65, 119.38), (119.54, 116.52)],
    'DBMF': [(32.27, 32.14), (32.28, 32.06), (32.12, 31.89), (32.04, 31.80)],
    'EMXC': [(86.525, 85.86), (85.36, 84.98), (85.16, 84.51), (85.11, 82.87)],
    'GLDM': [(76.45, 76.16), (76.38, 76.10), (74.75, 73.66), (73.36, 72.34)],
    'IBIT': [(36.47, 36.79), (36.695, 36.14), (36.13, 35.36), (36.13, 35.08)],
    'KMLM': [(29.76, 29.65), (29.80, 29.54), (29.50, 29.30), (29.34, 29.27)],
    'PDBC': [(18.15, 18.02), (18.115, 17.98), (17.79, 17.58), (17.73, 17.65)],
    'QQQM': [(276.291, 272.49), (273.079, 270.42), (272.249, 271.58), (276.359, 265.64)],
}
DAYS = pd.bdate_range('2026-11-16', '2026-11-19')


@pytest.fixture(scope='module')
def bot():
    path = Path(__file__).resolve().parents[1] / 'mnt_bot V 8.0 plus.py'
    spec = importlib.util.spec_from_file_location('v80_tiingo_tail', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def feed(symbol):
    prices = QUOTES[symbol]
    primary = pd.DataFrame(np.asarray(prices[:3], dtype='float32').astype(float), index=DAYS[:3], columns=['open', 'close'])
    primary.attrs['provider_first_trade_date'] = 'sentinel'
    tiingo = [{'date': d.strftime('%Y-%m-%dT00:00:00.000Z'), 'open': o, 'close': c,
               'adjOpen': o, 'adjClose': c, 'divCash': 0., 'splitFactor': 1.}
              for d, (o, c) in zip(DAYS, prices)]
    nasdaq = {'symbol': symbol, 'tradesTable': {'rows': [
        {'date': d.strftime('%m/%d/%Y'), 'open': str(o), 'close': str(c)} for d, (o, c) in reversed(list(zip(DAYS, prices)))]}}
    return primary, tiingo, nasdaq


@pytest.mark.parametrize('symbol', QUOTES)
def test_real_nine_etfs(bot, monkeypatch, symbol):
    primary, tiingo, nasdaq = feed(symbol)
    monkeypatch.setattr(bot, '_us_verified_tail_sources', lambda ticker, dates: (tiingo, nasdaq))
    out = bot._repair_us_verified_tiingo_tail(symbol, primary, DAYS[-1])
    assert len(primary) == 3
    assert out.loc[DAYS[-1]].tolist() == list(QUOTES[symbol][-1])
    pd.testing.assert_frame_equal(out.loc[DAYS[:3]], primary, check_freq=False)
    assert out.attrs['provider_first_trade_date'] == 'sentinel'
    assert out.attrs['tiingo_tail_evidence']['filled_fields'] == {'2026-11-19': ['open', 'close']}


@pytest.mark.parametrize('field', ['open', 'close'])
def test_partial_rows_preserve_observed_fields_and_validate_raw_scale(bot, monkeypatch, field):
    primary, tiingo, nasdaq = feed('AVUV')
    for row in tiingo:
        row['adjOpen'] *= .8
        row['adjClose'] *= .8
    primary *= .8
    i = ('open', 'close').index(field)
    preserved = QUOTES['AVUV'][-1][i] * .8 + 1e-8
    primary.loc[DAYS[-1], field] = preserved
    primary.attrs['yahoo_partial_raw'] = {'2026-11-19': {'open': QUOTES['AVUV'][-1][0]}}
    monkeypatch.setattr(bot, '_us_verified_tail_sources', lambda *_: (tiingo, nasdaq))
    repaired = bot._repair_us_verified_tiingo_tail('AVUV', primary, DAYS[-1])
    assert repaired.at[DAYS[-1], field] == preserved
    other = 'close' if field == 'open' else 'open'
    assert repaired.at[DAYS[-1], other] == QUOTES['AVUV'][-1][1-i] * .8
    primary.attrs['yahoo_partial_raw']['2026-11-19']['open'] *= .8
    replaced = bot._repair_us_verified_tiingo_tail('AVUV', primary, DAYS[-1])
    assert replaced.loc[DAYS[-1]].tolist() == [price * .8 for price in QUOTES['AVUV'][-1]]
    evidence = replaced.attrs['tiingo_tail_evidence']
    assert evidence['filled_fields']['2026-11-19'] == ['open', 'close']
    assert evidence['partial_conflicts']['2026-11-19']['raw_open'] == {
        'yahoo': QUOTES['AVUV'][-1][0] * .8, 'verified': QUOTES['AVUV'][-1][0]}


def test_contiguous_tail_multiple_days_and_non_session_cutoff(bot, monkeypatch):
    primary, tiingo, nasdaq = feed('GLDM')
    friday = pd.Timestamp('2026-11-20')
    tiingo.append({**tiingo[-1], 'date': '2026-11-20T00:00:00Z'})
    nasdaq['tradesTable']['rows'].insert(0, {**nasdaq['tradesTable']['rows'][0], 'date': '11/20/2026'})
    primary.loc[friday, 'open'] = QUOTES['GLDM'][-1][0]
    monkeypatch.setattr(bot, '_us_verified_tail_sources', lambda *_: (tiingo, nasdaq))
    out = bot._repair_us_verified_tiingo_tail('GLDM', primary, friday)
    assert out.attrs['tiingo_tail_evidence']['filled_fields'] == {
        '2026-11-19': ['open', 'close'], '2026-11-20': ['close']}
    with pytest.raises(bot.DataSchemaError):
        bot._repair_us_verified_tiingo_tail('GLDM', primary, '2026-11-21')


@pytest.mark.parametrize('fault', [
    'nasdaq_symbol', 'nasdaq_missing', 'nasdaq_duplicate', 'nasdaq_raw', 'tiingo_identity',
    'tiingo_duplicate', 'tiingo_missing', 'naive_date', 'cash', 'split', 'missing_action',
    'adjusted_jump', 'raw_adjusted_ratio', 'bad_close', 'bool_price', 'yahoo_overlap', 'yahoo_gap',
    'yahoo_raw_overlap', 'invalid_primary', 'unconfirmed_primary',
])
def test_conflicts_fail_closed(bot, monkeypatch, fault):
    primary, tiingo, nasdaq = feed('KMLM')
    nr = nasdaq['tradesTable']['rows']
    if fault == 'nasdaq_symbol': nasdaq['symbol'] = 'DBMF'
    elif fault == 'nasdaq_missing': nr.pop()
    elif fault == 'nasdaq_duplicate': nr[1] = nr[0]
    elif fault == 'nasdaq_raw': nr[0]['open'] = '30.5'
    elif fault == 'tiingo_identity': tiingo[-1]['ticker'] = 'DBMF'
    elif fault == 'tiingo_duplicate': tiingo[1] = tiingo[0]
    elif fault == 'tiingo_missing': tiingo.pop()
    elif fault == 'naive_date': tiingo[0]['date'] = '2026-11-16'
    elif fault == 'cash': tiingo[0]['divCash'] = .1
    elif fault == 'split': tiingo[-1]['splitFactor'] = 2.
    elif fault == 'missing_action': del tiingo[-1]['splitFactor']
    elif fault == 'adjusted_jump':
        tiingo[-1]['adjOpen'] *= .9
        tiingo[-1]['adjClose'] *= .9
    elif fault == 'raw_adjusted_ratio': tiingo[-1]['adjOpen'] *= .9
    elif fault == 'bad_close': tiingo[-1]['close'] = np.inf
    elif fault == 'bool_price': tiingo[-1]['open'] = True
    elif fault == 'yahoo_overlap': primary.iloc[-2, 0] *= .95
    elif fault == 'yahoo_gap': primary.index = [pd.Timestamp('2026-11-13'), DAYS[1], DAYS[2]]
    elif fault == 'yahoo_raw_overlap': primary.attrs['yahoo_partial_raw'] = {'2026-11-18': {'close': 28.4}}
    elif fault == 'invalid_primary': primary.loc[DAYS[-1], 'open'] = 0.
    elif fault == 'unconfirmed_primary': primary['is_live_bar'] = [False, True, False]
    monkeypatch.setattr(bot, '_us_verified_tail_sources', lambda *_: (tiingo, nasdaq))
    with pytest.raises(bot.DataSchemaError):
        bot._repair_us_verified_tiingo_tail('KMLM', primary, DAYS[-1])


def test_credential_failures_do_not_contact_sources(bot, monkeypatch):
    primary, _, _ = feed('DBMF')
    def denied():
        raise bot.DataSchemaError('Tiingo credential unavailable')
    monkeypatch.setattr(bot, '_tiingo_tail_credential', denied)
    monkeypatch.setattr(bot.requests, 'get', lambda *a, **k: pytest.fail('unexpected network call'))
    with pytest.raises(bot.DataSchemaError, match='credential unavailable'):
        bot._repair_us_verified_tiingo_tail('DBMF', primary, DAYS[-1])


def test_authenticated_request_refuses_redirect_and_redacts_exception(bot, monkeypatch):
    monkeypatch.setattr(bot, '_tiingo_tail_credential', lambda: 'test-only')
    calls = []
    def denied(url, **kwargs):
        calls.append((url, kwargs))
        return Mock(status_code=302, headers={'Location': 'https://example.invalid/'})
    monkeypatch.setattr(bot.requests, 'get', denied)
    with pytest.raises(bot.DataSchemaError) as error:
        bot._us_verified_tail_sources('AVUV', DAYS)
    assert len(calls) == 1 and calls[0][1]['allow_redirects'] is False
    assert 'test-only' not in calls[0][0] and 'test-only' not in str(error.value)


@pytest.mark.parametrize('failure', [401, 403, 429, 'timeout', 'no_credential'])
def test_transport_failures_use_verified_historical_prefix(bot, monkeypatch, failure):
    # The adapter receives a genuine requests.PreparedRequest. Simulate HTTP
    # responses at the transport boundary, leaving parsing and fallback intact.
    primary, _, _ = feed('EMXC')
    calls = []
    def send(adapter, prepared, **kwargs):
        calls.append(prepared)
        assert prepared.url.startswith('https://api.tiingo.com/tiingo/daily/EMXC/prices?')
        assert prepared.headers['Authorization'] == 'Token test-only'
        if failure == 'timeout':
            raise bot.requests.Timeout('test-only upstream echo')
        response = bot.requests.Response()
        response.status_code = failure
        response._content = b'{"detail":"test-only upstream echo"}'
        response.request = prepared
        response.url = prepared.url
        return response
    monkeypatch.setattr(bot.requests.adapters.HTTPAdapter, 'send', send)
    env = {} if failure == 'no_credential' else {'TIINGO_API_TOKEN': 'test-only'}
    monkeypatch.setattr(bot, 'os', SimpleNamespace(name='posix', environ=env))
    monkeypatch.setattr(bot, '_TIINGO_TAIL_REQUEST_TIMES', [])
    monkeypatch.setattr(bot, '_us_history_expected_start', lambda *_: DAYS[0])
    primary_output, status = bot._v80_us_confirmed_prefix(
        {'EMXC': primary}, {'EMXC': 'Yahoo'}, DAYS[-1], ['EMXC'], Mock())
    assert len(calls) == (0 if failure == 'no_credential' else 1)
    assert status['status'] == 'historical' and status['asof'] == DAYS[-2]
    assert status['repaired'] == () and 'test-only' not in status['reason']
    pd.testing.assert_frame_equal(primary, primary_output['EMXC'])


@pytest.mark.parametrize(('symbol', 'reported'), [
    ('IBIT', 36.13999938964844), ('PDBC', 17.719999313354492), ('QQQM', 276.3800048828125)])
def test_real_disputed_yahoo_half_bars_replaced_as_whole_pairs(bot, monkeypatch, symbol, reported):
    primary, tiingo, nasdaq = feed(symbol)
    primary.attrs['yahoo_partial_raw'] = {'2026-11-19': {'open': reported}}
    monkeypatch.setattr(bot, '_us_verified_tail_sources', lambda *_: (tiingo, nasdaq))
    out = bot._repair_us_verified_tiingo_tail(symbol, primary, DAYS[-1])
    assert out.loc[DAYS[-1]].tolist() == list(QUOTES[symbol][-1])
    evidence = out.attrs['tiingo_tail_evidence']
    assert evidence['ticker'] == symbol
    assert evidence['partial_conflicts'] == {'2026-11-19': {
        'raw_open': {'yahoo': reported, 'verified': QUOTES[symbol][-1][0]}}}
    assert out.attrs['yahoo_partial_raw'] == primary.attrs['yahoo_partial_raw']


def test_partial_adjusted_field_conflict_is_recorded_and_replaced_as_pair(bot, monkeypatch):
    primary, tiingo, nasdaq = feed('EMXC')
    primary.loc[DAYS[-1], 'close'] = 82.0
    monkeypatch.setattr(bot, '_us_verified_tail_sources', lambda *_: (tiingo, nasdaq))
    out = bot._repair_us_verified_tiingo_tail('EMXC', primary, DAYS[-1])
    assert out.loc[DAYS[-1]].tolist() == list(QUOTES['EMXC'][-1])
    assert out.attrs['tiingo_tail_evidence']['partial_conflicts']['2026-11-19'] == {
        'adjusted_close': {'yahoo': 82., 'verified': 82.87}}


@pytest.mark.parametrize(('day', 'quote_clock', 'temporary'), [
    ('2026-11-19', '13:00', True), ('2026-11-19', '15:59', True), ('2026-11-19', '16:00', False),
    ('2026-11-27', '12:59', True), ('2026-11-27', '13:00', False)])
def test_yahoo_last_bar_market_time_controls_formal_admission(bot, monkeypatch, day, quote_clock, temporary):
    day = pd.Timestamp(day)
    dates = bot._expected_us_ohlc_index(day - pd.Timedelta(days=12), day)[-4:]
    quote_time = pd.Timestamp(f'{day.date()} {quote_clock}', tz='America/New_York')
    stamps = [int(pd.Timestamp(f'{date.date()} 09:30', tz='America/New_York').timestamp()) for date in dates]
    rows = {'timestamp': stamps, 'meta': {'symbol': 'EMXC', 'regularMarketTime': int(quote_time.timestamp())},
            'indicators': {'quote': [{'open': [86.525, 85.36, 85.16, 85.11], 'close': [85.86, 84.98, 84.51, 84.7]}],
                           'adjclose': [{'adjclose': [85.86, 84.98, 84.51, 84.7]}]}}
    monkeypatch.setattr(bot._session, 'get', lambda *_a, **_kw: Mock(
        status_code=200, json=lambda: {'chart': {'result': [rows]}}))
    frame = bot._fetch_us_yahoo('EMXC')
    assert frame.loc[day, 'close'] == 84.7
    if temporary:
        assert frame['is_live_bar'].tolist() == [False, False, False, True]
        assert frame.attrs['yahoo_provisional_market_time'] == quote_time.isoformat()
        assert frame.attrs['yahoo_partial_raw'][str(day.date())] == {'open': 85.11, 'close': 84.7}
    monkeypatch.setattr(bot, '_us_history_expected_start', lambda *_: dates[0])
    monkeypatch.setattr(bot, 'os', SimpleNamespace(name='posix', environ={}))
    confirmed, status = bot._v80_us_confirmed_prefix({'EMXC': frame}, {'EMXC': 'Yahoo'}, day, ['EMXC'], Mock())
    assert status['status'] == ('historical' if temporary else 'current')
    assert confirmed['EMXC'].index[-1] == (dates[-2] if temporary else day)

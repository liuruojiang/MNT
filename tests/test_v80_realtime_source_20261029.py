"""Frozen real EastMoney receipts plus explicitly mutated rejection cases."""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests/fixtures/v80_realtime_20261029'
QUOTE = json.loads((FIX / 'quote.json').read_text(encoding='utf-8'))
TRENDS = json.loads((FIX / 'trends.json').read_text(encoding='utf-8'))


@pytest.fixture
def bot(monkeypatch):
    spec = importlib.util.spec_from_file_location('v80_realtime_source', ROOT / 'mnt_bot V 8.0 plus.py')
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, 'beijing_now', lambda: pd.Timestamp(TRENDS['received_at']).to_pydatetime())
    monkeypatch.setattr(m, '_fetch_cn_realtime_close_quote_fallback', lambda *a, **kw: None)
    def forbidden(*a, **kw):
        raise AssertionError('Unexpected network request')
    monkeypatch.setattr(m.requests.sessions.Session, 'request', forbidden)
    return m


def install(bot, monkeypatch, quote=None, trends=None):
    q = copy.deepcopy(QUOTE['payload'] if quote is None else quote)
    t = copy.deepcopy(TRENDS['payload'] if trends is None else trends)
    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): pass
        def json(self): return self.payload
    def get(url, **kw):
        if 'secid=1.930955' in url: return Response({'data': None})
        return Response(t if 'trends2' in url else q)
    monkeypatch.setattr(bot.requests, 'get', get)


def test_real_zero_timestamp_falls_back_to_dated_index(bot, monkeypatch):
    install(bot, monkeypatch)
    assert QUOTE['payload']['data']['f124'] == 0
    assert bot._fetch_cn_realtime_close('1.930955') == 11496.27
    # The 14:29 in-progress label was received at 14:28; never use its value.
    assert bot._fetch_cn_realtime_close('1.930955') != 11494.77


def test_real_supplement_merges_without_yesterday_fallback(bot, monkeypatch):
    install(bot, monkeypatch)
    base = pd.DataFrame({'close': [11433.78]}, index=pd.to_datetime(['2026-10-28']))
    frame = bot._supplement_today_close(base, '1.930955', pd.Timestamp('2026-10-29').date())
    assert frame.index[-1] == pd.Timestamp('2026-10-29')
    assert frame.iloc[-1]['close'] == 11496.27 and frame.iloc[-1]['is_live_bar']
    raw = {code: frame.copy() for code in bot.CN_STOCK_CODES}
    assert bot._build_cn_stock_close_frame(raw).index[-1] == pd.Timestamp('2026-10-29')
    assert base.index[-1] == pd.Timestamp('2026-10-28')


@pytest.mark.parametrize('fault', ['wrong_code', 'wrong_market', 'yesterday', 'tomorrow', 'far_future', 'duplicate', 'unordered', 'nan', 'zero', 'negative', 'empty', 'malformed'])
def test_bad_trends_rejected(bot, monkeypatch, fault):
    t = copy.deepcopy(TRENDS['payload']); d = t['data']
    if fault == 'wrong_code': d['code'] = '000905'
    elif fault == 'wrong_market': d['market'] = 1
    elif fault in ('yesterday', 'tomorrow'):
        d['trends'] = [s.replace('2026-10-29', '2026-10-28' if fault == 'yesterday' else '2026-10-30') for s in d['trends']]
    elif fault == 'far_future': d['trends'][-1] = d['trends'][-1].replace('14:29', '14:40')
    elif fault == 'duplicate': d['trends'].append(d['trends'][-1])
    elif fault == 'unordered': d['trends'].reverse()
    elif fault in ('nan', 'zero', 'negative'):
        s = d['trends'][-2].split(','); s[2] = {'nan':'NaN', 'zero':'0', 'negative':'-1'}[fault]; d['trends'][-2] = ','.join(s)
    elif fault == 'empty': d['trends'] = []
    elif fault == 'malformed': d['trends'] = ['broken']
    install(bot, monkeypatch, trends=t)
    assert bot._fetch_cn_realtime_close('1.930955') is None


def test_valid_primary_quote_retains_priority_and_decimal_scale(bot, monkeypatch):
    q = copy.deepcopy(QUOTE['payload'])
    q['data'].update(f124=int(pd.Timestamp('2026-10-29 14:28', tz='Asia/Shanghai').timestamp()), f43=1149627, f59=2)
    install(bot, monkeypatch, quote=q, trends={'data': None})
    assert bot._fetch_cn_realtime_close('1.930955') == 11496.27


@pytest.mark.parametrize('fault', ['wrong_code', 'future', 'yesterday', 'invalid_scale', 'invalid_type', 'nan'])
def test_primary_quote_validation(bot, monkeypatch, fault):
    q = copy.deepcopy(QUOTE['payload']); d = q['data']
    d['f124'] = int(pd.Timestamp('2026-10-29 14:28', tz='Asia/Shanghai').timestamp())
    if fault == 'wrong_code': d['f57'] = '000905'
    elif fault == 'future': d['f124'] += 3600
    elif fault == 'yesterday': d['f124'] -= 86400
    elif fault == 'invalid_scale': d['f59'] = 20
    elif fault == 'invalid_type': d['f43'] = {}
    else: d['f43'] = float('nan')
    install(bot, monkeypatch, quote=q, trends={'data': None})
    assert bot._fetch_cn_realtime_close('1.930955') is None

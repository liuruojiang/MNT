"""Adversarial controls for the current-day CN price/amount confirmation gates."""
import importlib.util
import io
import sys
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope='module')
def bot():
    spec = importlib.util.spec_from_file_location('v80_cn_finality', Path(__file__).resolve().parents[1] / 'mnt_bot V 8.0 plus.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DAY = pd.Timestamp('2026-11-18')
PREV = pd.Timestamp('2026-11-17')


@pytest.mark.parametrize('fault', [None, 'early_stamp', 'future_stamp', 'last_missing', 'midday_hole', 'wrong_market', 'business_error'])
def test_final_session_requires_complete_minutes_and_postclose_timestamp(bot, monkeypatch, fault):
    clock = pd.Timestamp('2026-11-18 15:35').to_pydatetime()
    monkeypatch.setattr(bot, 'beijing_now', lambda: clock)
    dates = pd.date_range('2026-11-18 09:30', '2026-11-18 11:30', freq='min').append(
        pd.date_range('2026-11-18 13:01', '2026-11-18 15:00', freq='min'))
    if fault == 'last_missing':
        dates = dates[:-1]
    if fault == 'midday_hole':
        dates = dates.delete(145)
    stamp = {'early_stamp': '14:59:59', 'future_stamp': '15:36:00'}.get(fault, '15:00:01')
    data = {'code': '399006', 'market': 1 if fault == 'wrong_market' else 0,
            'time': int(pd.Timestamp(f'2026-11-18 {stamp}', tz='Asia/Shanghai').timestamp()),
            'trends': [f'{date:%Y-%m-%d %H:%M},100,105,105,100,1000,10000.00,101' for date in dates]}

    class QuoteResponse:
        def raise_for_status(self): pass
        def json(self): return {'rc': 42 if fault == 'business_error' else 0, 'data': data}

    monkeypatch.setattr(bot.requests, 'get', lambda *a, **k: QuoteResponse())
    proof = bot._fetch_cn_final_sessions('0.399006', [DAY], clock)
    assert proof == ({DAY: {'close': 105.0, 'amount_cny': 2410000.0}} if fault is None else {})


def test_alternate_host_can_complete_amount_only_against_matching_close(bot, monkeypatch):
    clock = pd.Timestamp('2026-11-18 15:35').to_pydatetime()
    monkeypatch.setattr(bot, 'beijing_now', lambda: clock)
    dates = pd.date_range('2026-11-18 09:30', '2026-11-18 11:30', freq='min').append(
        pd.date_range('2026-11-18 13:01', '2026-11-18 15:00', freq='min'))
    data = {'time': int(pd.Timestamp('2026-11-18 15:00:01', tz='Asia/Shanghai').timestamp())}

    def feed(secid, host, ndays):
        amount = 'bad' if host == 'push2his.eastmoney.com' else '10000'
        return data, [[f'{day:%Y-%m-%d %H:%M}', '101', '105', '105', '101', '100', amount] for day in dates]

    monkeypatch.setattr(bot, '_fetch_cn_trend_rows', feed)
    assert bot._fetch_cn_final_sessions('0.399006', [DAY], clock) == {
        DAY: {'close': 105.0, 'amount_cny': 2410000.0}
    }


@pytest.mark.parametrize('close', [None, 102.0, 105.0])
def test_waiting_for_final_price_never_emits_same_day_trading_target(bot, monkeypatch, close):
    clock = pd.Timestamp('2026-11-18 15:35').to_pydatetime()
    monkeypatch.setattr(bot, 'beijing_now', lambda: clock)
    code = bot.CN_ZZHL_INDEX_SECID
    raw = {code: pd.DataFrame({'close': [99., 100., 105.]}, index=[pd.Timestamp('2026-11-16'), PREV, DAY])}
    proof = {code: {'close': close}} if close is not None else {}
    panel, diagnostics = bot._prepare_cn_live_panel(raw, {code: code}, clock, DAY, PREV, io.StringIO(), 'Sub-A', final_sessions=proof)
    result = pd.DataFrame({'holding': ['cash', code], 'weight': [0.0, 1.25]}, index=panel[code].index[-2:])
    frame = panel[code]
    frame.attrs.update(diagnostics)
    for kind in ('signal', 'live_signal', 'params', 'live_params'):
        out = io.StringIO()
        status = bot._write_a_adk_query_overview(out.write, result, None, query_kind=kind, cn_price_frame=frame)
        assert status['Sub-A']['is_signal'] == (close == 105.0)
        assert ('历史收盘目标（非今日实时）' in out.getvalue()) == (close != 105.0)


def test_stale_primary_continues_to_fresh_exact_sources_and_never_uses_etf(bot, monkeypatch):
    dates = bot._expected_cn_sessions('2026-01-05', DAY)
    latest = pd.DataFrame({'close': 105.0}, index=dates)
    stale = latest.loc[:PREV]
    monkeypatch.setattr(bot, 'time', type('Clock', (), {'sleep': staticmethod(lambda *a: None)}))
    monkeypatch.setattr(bot, '_fetch_cn_sina', lambda *a: stale)
    monkeypatch.setattr(bot, '_fetch_cn_eastmoney', lambda *a: latest)
    assert bot.fetch_cn_kline('0.399006', required_date=DAY)[1] == 'EastMoney'
    assert bot._fetch_cn_dk_price_index('399006', '0.399006', required_date=DAY)[1] == 'EastMoney'
    partial = latest.copy()
    partial.at[DAY, 'close'] = 103.0
    monkeypatch.setattr(bot, '_fetch_cn_sina', lambda *a: partial)
    assert bot.fetch_cn_kline('0.399006', required_date=DAY, verified_close=105.0)[1] == 'EastMoney'
    assert bot._fetch_cn_dk_price_index('399006', '0.399006', required_date=DAY, verified_close=105.0)[1] == 'EastMoney'
    monkeypatch.setattr(bot, '_fetch_cn_sina', lambda *a: latest.tail(55))
    assert bot.fetch_cn_kline('0.399006', required_date=DAY)[1] == 'EastMoney'
    assert bot._fetch_cn_dk_price_index('399006', '0.399006', required_date=DAY)[1] == 'EastMoney'
    monkeypatch.setattr(bot, '_fetch_cn_sina', lambda *a: latest.drop(index=PREV))
    assert bot.fetch_cn_kline('0.399006', required_date=DAY)[1] == 'EastMoney'
    assert bot._fetch_cn_dk_price_index('399006', '0.399006', required_date=DAY)[1] == 'EastMoney'
    monkeypatch.setattr(bot, '_fetch_cn_sina', lambda *a: stale)
    monkeypatch.setattr(bot, '_fetch_cn_eastmoney', lambda *a: stale)
    monkeypatch.setattr(bot, '_load_cn_official_base_with_embedded', lambda *a: (stale, 'cache'))
    monkeypatch.setattr(bot, '_fetch_cn_csindex', lambda *a: latest)
    monkeypatch.setattr(bot, '_save_cn_official_cache', lambda *a: None)

    def forbidden(*args):
        raise AssertionError('ETF proxy must be excluded from formal index history')

    monkeypatch.setattr(bot, '_fetch_cn_price_index_proxy', forbidden)
    assert bot.fetch_cn_kline(bot.CN_ZZHL_INDEX_SECID, required_date=DAY)[1] == 'csindex:930955'


def test_hole_in_verified_historical_calendar_tries_complete_alternate(bot, monkeypatch):
    dates = bot._expected_cn_sessions('2024-01-01', DAY)
    complete = pd.DataFrame({'close': 105.0}, index=dates)
    incomplete = complete.drop(index=pd.Timestamp('2024-11-12'))
    monkeypatch.setattr(bot, '_fetch_cn_sina', lambda *args: incomplete)
    monkeypatch.setattr(bot, '_fetch_cn_eastmoney', lambda *args: complete)
    assert bot.fetch_cn_kline('0.399006', required_date=DAY)[1] == 'EastMoney'
    assert bot._fetch_cn_dk_price_index('399006', '0.399006', required_date=DAY)[1] == 'EastMoney'


def test_daily_amount_requires_same_session_total_and_can_try_other_vendor(bot, monkeypatch):
    days = bot._expected_cn_sessions('2026-05-01', DAY)
    sohu = pd.DataFrame({'amount': 15_000_000.}, index=days)  # CNY 10,000
    eastmoney = pd.DataFrame({'amount': 341_433_093_442.59}, index=days)
    monkeypatch.setattr(bot, '_fetch_cn_sohu_amount', lambda *a, **k: sohu)
    monkeypatch.setattr(bot, '_fetch_cn_eastmoney_amount', lambda *a, **k: eastmoney)
    proof = {'0.399006': 341_433_093_587.0}
    frame, source = bot._fetch_cn_amount_with_fallback('0.399006', 'CYB', expected_date=DAY, final_amounts=proof)
    assert source == 'EastMoney amount' and frame.at[DAY, 'amount'] == eastmoney.at[DAY, 'amount']
    with pytest.raises(bot.DataUnavailableError):
        bot._fetch_cn_amount_with_fallback('0.399006', 'CYB', expected_date=DAY, final_amounts={})


def test_daily_amount_skips_future_dated_source_missing_target_session(bot, monkeypatch):
    days = bot._expected_cn_sessions('2026-05-01', DAY)
    sohu_days = days[:-1].append(pd.DatetimeIndex([DAY + pd.Timedelta(days=1)]))
    sohu = pd.DataFrame({'amount': 34_143_309.3443}, index=sohu_days)
    eastmoney = pd.DataFrame({'amount': 341_433_093_442.59}, index=days)
    monkeypatch.setattr(bot, '_fetch_cn_sohu_amount', lambda *a, **k: sohu)
    monkeypatch.setattr(bot, '_fetch_cn_eastmoney_amount', lambda *a, **k: eastmoney)
    frame, source = bot._fetch_cn_amount_with_fallback('0.399006', 'CYB', expected_date=DAY,
                                                      final_amounts={'0.399006': 341_433_093_443.0})
    assert source == 'EastMoney amount' and frame.index[-1] == DAY


def test_panel_does_not_merge_morning_snapshot_after_afternoon_reopens(bot, monkeypatch):
    clock = pd.Timestamp('2026-11-18 12:59:59').to_pydatetime()
    monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-11-18 13:01:01').to_pydatetime())
    raw = {code: pd.DataFrame({'close': [100.0]}, index=[PREV]) for code in ('0.399006', '1.000016')}

    def quote(frame, secid, day, msg, receipt):
        stamp = pd.Timestamp('2026-11-18 11:30' if secid == '0.399006' else '2026-11-18 13:01')
        receipt.update(time=stamp, source='fixture')
        return pd.DataFrame({'close': [100., 101.], 'is_live_bar': [False, True]}, index=[PREV, DAY])

    monkeypatch.setattr(bot, '_supplement_today_close', quote)
    panel, proof = bot._prepare_cn_live_panel(raw, {code: code for code in raw}, clock, PREV, PREV, io.StringIO(), 'Sub-A')
    assert all(frame.index[-1] == PREV for frame in panel.values())
    assert proof['cn_missing_live_inputs'] == (('创业板', '2026-11-17'),)


def test_rollover_cannot_bypass_latest_completed_price_proof(bot, monkeypatch):
    clock = pd.Timestamp('2026-11-19 00:10').to_pydatetime()
    monkeypatch.setattr(bot, 'beijing_now', lambda: clock)
    code = '0.399006'
    raw = {code: pd.DataFrame({'close': [100., 105.]}, index=[PREV, DAY])}
    for proof in ({}, {code: {'close': 100.0}}):
        with pytest.raises(bot.DataUnavailableError, match='2026-11-18'):
            bot._prepare_cn_live_panel(raw, {code: code}, clock, DAY, DAY, io.StringIO(), 'Sub-A', previous_sessions=proof)
    result, _ = bot._prepare_cn_live_panel(raw, {code: code}, clock, DAY, DAY, io.StringIO(), 'Sub-A',
                                           previous_sessions={code: {'close': 105.0}})
    assert result[code].at[DAY, 'close'] == 105.0


@pytest.mark.parametrize('fault', [None, 'preclose_clock', 'early_stamp', 'future_stamp', 'live', 'previous_date',
                                  'snapshot_price', 'missing_minute', 'invalid_price', 'wrong_symbol',
                                  'snapshot_amount', 'bool_snapshot_amount'])
def test_cnfin_primary_outage_keeps_same_day_close_and_amount_gates(bot, monkeypatch, fault):
    clock = pd.Timestamp('2026-11-18 14:59:59' if fault == 'preclose_clock' else '2026-11-18 18:41')
    monkeypatch.setattr(bot, 'beijing_now', lambda: clock)
    symbol = '932000.CSI'
    code = '2.932000'
    dates = pd.date_range('2026-11-18 09:31', '2026-11-18 11:30', freq='min').append(
        pd.date_range('2026-11-18 13:01', '2026-11-18 15:00', freq='min'))
    if fault == 'missing_minute':
        dates = dates.delete(20)
    rows = [[int(day.strftime('%Y%m%d%H%M')), 2562.74, 2000] for day in dates]
    if fault == 'invalid_price':
        rows[20][1] = True
    if fault == 'bool_snapshot_amount':
        for row in rows:
            row[2] = 0
        rows[-1][2] = 1
    candle = {'fields': ['min_time', 'close_px', 'business_balance'],
              '515100.SH' if fault == 'wrong_symbol' else symbol:
                  rows}
    snapshot = {'fields': ['data_timestamp', 'shares_per_hand', 'market_date', 'last_px', 'business_balance', 'trade_status'],
                symbol: [{'early_stamp': 145959999, 'future_stamp': 184100001}.get(fault, 150403000), 1,
                         20261117 if fault == 'previous_date' else 20261118,
                         2562.73 if fault == 'snapshot_price' else 2562.74,
                         {'snapshot_amount': 479999, 'bool_snapshot_amount': True}.get(fault, 480000),
                         'TRADE' if fault == 'live' else 'ENDTR']}

    class Response:
        def __init__(self, data):
            self.data = data
        def raise_for_status(self): pass
        def json(self): return {'data': self.data}

    def get(url, **kwargs):
        if 'eastmoney.com' in url:
            raise bot.requests.ConnectionError('primary minute feeds unavailable')
        if url.endswith('/kline'):
            assert kwargs['params']['prod_code'] == symbol
            assert kwargs['params']['start_date'] == kwargs['params']['end_date'] == '20261118'
            return Response({'candle': candle})
        assert url.endswith('/real')
        assert kwargs['params']['en_prod_code'] == symbol
        return Response({'snapshot': snapshot})

    monkeypatch.setattr(bot.requests, 'get', get)
    expected = ({DAY: {'close': 2562.74, 'amount_cny': 4_800_000_000.0}} if fault is None
                else {DAY: {'close': 2562.74}} if fault in {'snapshot_amount', 'bool_snapshot_amount'} else {})
    assert bot._fetch_cn_final_sessions(code, [DAY], clock) == expected


def test_cnfin_old_session_uses_exact_bond_minutes_and_requires_matching_daily_row(bot, monkeypatch):
    clock = pd.Timestamp('2026-11-18 15:20')
    monkeypatch.setattr(bot, 'beijing_now', lambda: clock)
    code = bot.CN_BOND_CODE
    calls = []

    def down(*args):
        raise bot.requests.ConnectionError('primary minute feeds unavailable')

    def candles(symbol, date, fields):
        assert symbol == '000012.SH' and fields == ['close_px']
        calls.append(date)
        dates = pd.date_range(date + pd.Timedelta('9h31m'), date + pd.Timedelta('11h30m'), freq='min').append(
            pd.date_range(date + pd.Timedelta('13h1m'), date + pd.Timedelta('15h30m'), freq='min'))
        return dates, [[int(day.strftime('%Y%m%d%H%M')), 232.19] for day in dates]

    monkeypatch.setattr(bot, '_fetch_cn_trend_rows', down)
    monkeypatch.setattr(bot, '_fetch_cnfin_candles', candles)
    monkeypatch.setattr(bot, '_fetch_cnfin_close_snapshot', lambda *a: pytest.fail('snapshot cannot prove a prior date'))
    proof = bot._fetch_cn_final_sessions(code, [PREV, DAY], clock)
    assert calls == [PREV] and proof == {PREV: {'close': 232.19}}
    raw = {code: pd.DataFrame({'close': [232.16, 232.30]}, index=[PREV, DAY])}
    with pytest.raises(bot.DataUnavailableError, match='日线缺失或与收盘凭据不一致'):
        bot._prepare_cn_live_panel(raw, {code: code}, clock, DAY, PREV, io.StringIO(), 'Sub-A',
                                   previous_sessions={code: proof[PREV]})

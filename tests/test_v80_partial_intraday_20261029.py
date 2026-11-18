"""Synthetic quotes exercise missing-live contracts, not market performance."""
import importlib.util
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope='module')
def bot():
    spec = importlib.util.spec_from_file_location('v80_partial_live', Path(__file__).resolve().parents[1] / 'mnt_bot V 8.0 plus.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def frames(bot, complete=False):
    return {code: pd.DataFrame({'close': [100., 101., 102.] if complete or code != '1.930955' else [100., 101.]},
                              index=pd.to_datetime(['2026-10-27', '2026-10-28', '2026-10-29'] if complete or code != '1.930955' else ['2026-10-27', '2026-10-28']))
            for code in bot.CN_STOCK_CODES}


def align(bot, raw, clock='2026-10-29 14:15', required='2026-10-28'):
    msg = io.StringIO()
    result = bot._align_partial_cn_intraday(raw, bot.CN_STOCK_CODES, pd.Timestamp(clock).to_pydatetime(), pd.Timestamp(required), msg)
    return result, msg.getvalue()


def test_partial_quotes_use_common_confirmed_date(bot):
    raw = frames(bot)
    with pytest.raises(bot.DataSchemaError, match='missing sessions'):
        bot._build_cn_stock_close_frame(raw)
    result, message = align(bot, raw)
    merged = bot._build_cn_stock_close_frame(result)
    assert merged.index[-1] == pd.Timestamp('2026-10-28')
    assert merged.iloc[-1].eq(101.).all()
    assert '中证红利低波100' in message and '不代表今日实时信号' in message
    assert any(frame.index[-1] == pd.Timestamp('2026-10-29') for frame in raw.values())


def test_complete_quotes_unchanged(bot):
    raw = frames(bot, complete=True)
    result, message = align(bot, raw)
    assert result is raw and message == ''
    assert bot._build_cn_stock_close_frame(result).index[-1] == pd.Timestamp('2026-10-29')


@pytest.mark.parametrize('clock,required', [('2026-10-29 15:15', '2026-10-29'), ('2026-10-29 09:00', '2026-10-28')])
def test_outside_intraday_does_not_relax_validation(bot, clock, required):
    raw = frames(bot)
    result, message = align(bot, raw, clock, required)
    assert result is raw and not message
    with pytest.raises(bot.DataSchemaError):
        bot._build_cn_stock_close_frame(result)


def test_stale_required_history_not_hidden(bot):
    raw = frames(bot)
    raw['1.930955'] = raw['1.930955'].iloc[:1]
    result, message = align(bot, raw)
    assert result is raw and not message
    with pytest.raises(bot.DataSchemaError):
        bot._build_cn_stock_close_frame(result)


def test_internal_hole_not_hidden(bot):
    raw = frames(bot)
    raw[bot.CN_STOCK_CODES[1]] = raw[bot.CN_STOCK_CODES[1]].drop(pd.Timestamp('2026-10-27'))
    # Include a common earlier session so the missing date is an internal hole.
    for code in raw:
        raw[code].loc[pd.Timestamp('2026-10-26'), 'close'] = 99.
        raw[code] = raw[code].sort_index()
    result, _ = align(bot, raw)
    with pytest.raises(bot.DataSchemaError, match='2026-10-27'):
        bot._build_cn_stock_close_frame(result)


@pytest.mark.parametrize('live,expected', [(True, '2026-10-28'), (False, '2026-10-28')])
def test_official_fetch_routes_partial_live_before_merge(bot, monkeypatch, live, expected):
    raw = frames(bot)
    raw[bot.CN_BOND_CODE] = raw[bot.CN_STOCK_CODES[1]].copy()
    monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-10-29 14:15').to_pydatetime())
    monkeypatch.setattr(bot, 'fetch_cn_kline', lambda code, **kw: (raw[code].copy(), 'TEST_ONLY'))
    monkeypatch.setattr(bot, '_fetch_cn_dk_price_index', lambda code, **kw: (raw[code].copy(), 'TEST_ONLY'))
    monkeypatch.setattr(bot, '_ensure_cn_history_frame', lambda code, frame, source, **kw: (frame, source))
    monkeypatch.setattr(bot, '_fetch_cn_final_sessions',
                        lambda code, dates, clock: {date: {'close': 101.0} for date in dates})
    def refresh(frame, code, *args):
        original = raw[code]
        if len(args) == 3 and original.index[-1] == pd.Timestamp('2026-10-29'):
            args[-1].update(time=pd.Timestamp('2026-10-29 14:14'), source='fixture')
        return original.assign(is_live_bar=original.index > pd.Timestamp(expected))
    monkeypatch.setattr(bot, '_supplement_today_close', refresh)
    monkeypatch.setattr(bot.time, 'sleep', lambda *a: None)
    def no_network(*a, **kw):
        raise AssertionError('Network forbidden')
    monkeypatch.setattr(bot.requests.sessions.Session, 'request', no_network)
    original = bot._build_cn_stock_close_frame
    class ReachedMerge(Exception):
        pass
    def capture(frames):
        result = original(frames)
        assert result.index[-1] == pd.Timestamp(expected)
        raise ReachedMerge
    monkeypatch.setattr(bot, '_build_cn_stock_close_frame', capture)
    msg = io.StringIO()
    with pytest.raises(ReachedMerge):
        bot.CombinedStrategyV80()._fetch_data(msg, include_cn_live_snapshot=live)
    assert ('不代表今日实时信号' in msg.getvalue()) == live


@pytest.mark.parametrize('kind', ['live_signal', 'live_params', 'signal', 'params'])
def test_display_keeps_missing_live_warning_even_on_cache_hit(bot, monkeypatch, kind):
    monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-10-29 14:15').to_pydatetime())
    cn = pd.DataFrame({'holding': ['cash'], 'scale': [1.]}, index=pd.to_datetime(['2026-10-28']))
    msg = io.StringIO()
    bot._write_a_adk_query_overview(msg.write, cn, None, query_kind=kind)
    assert ('今日Sub-A实时数据不完整' in msg.getvalue()) == kind.startswith('live_')


@pytest.mark.parametrize('missing, a_date, dk_date', [
    ('1.000012', '2026-10-08', '2026-10-09'),
    ('1.000300', '2026-10-09', '2026-10-08'),
    ('all', '2026-10-08', '2026-10-08'),
    (None, '2026-10-09', '2026-10-09'),
])
def test_native_live_query_isolates_missing_legs(bot, monkeypatch, missing, a_date, dk_date):
    from test_v80_doublecheck_data_math_20261007 import synthetic_vendor_fetch

    def quote(secid, expected_date=None, receipt=None):
        if missing in {secid, 'all'}:
            return None
        receipt.update(time=pd.Timestamp('2026-10-09 14:29'), source='test source')
        return 102.

    monkeypatch.setattr(bot, '_fetch_cn_realtime_close', quote)
    monkeypatch.setattr(bot.time, 'sleep', lambda *args: None)
    cn, dk, *_ = synthetic_vendor_fetch(bot, monkeypatch, '2026-10-09 14:30', False,
                                        include_cn_live=True, us_end='2026-10-08')
    prev, today = pd.Timestamp('2026-10-08'), pd.Timestamp('2026-10-09')
    for frame, expected in ((cn, a_date), (dk, dk_date)):
        assert frame.index[-1] == pd.Timestamp(expected)
        assert frame.attrs['cn_confirmed_close'] == prev
        assert frame.attrs['cn_unconfirmed_snapshot'] == (frame.index[-1] == today)
        if frame.index[-1] == today:
            assert frame.attrs['cn_quote_end'] == pd.Timestamp('2026-10-09 14:29')
    assert bot.CN_BOND_CODE in cn
    if missing == bot.CN_BOND_CODE:
        assert cn.attrs['cn_missing_live_inputs'] == ((bot.CN_BOND_NAME, a_date),)
    if missing == '1.000300':
        assert dk.attrs['cn_missing_live_inputs'] == (('沪深300', dk_date),)
    if missing == 'all':
        assert len(cn.attrs['cn_missing_live_inputs']) == 6
        assert len(dk.attrs['cn_missing_live_inputs']) == 5


def test_native_preclose_daily_bars_cannot_be_relabelled_after_close(bot, monkeypatch):
    from test_v80_doublecheck_data_math_20261007 import synthetic_vendor_fetch

    start, before = '2026-10-09 14:59:59', pd.Timestamp('2026-10-08')
    ensure = bot._ensure_cn_history_frame

    def after_fetch(code, *args, **kwargs):
        result = ensure(code, *args, **kwargs)
        if code == bot.CN_STOCK_CODES[-1]:
            monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-10-09 15:00:01').to_pydatetime())
        return result

    def forbidden(*args, **kwargs):
        raise AssertionError('no live quote may be fetched after 15:00')

    monkeypatch.setattr(bot, '_ensure_cn_history_frame', after_fetch)
    monkeypatch.setattr(bot, '_fetch_cn_realtime_close', forbidden)
    monkeypatch.setattr(bot.time, 'sleep', lambda *args: None)
    cn, dk, *_ = synthetic_vendor_fetch(bot, monkeypatch, start, False,
                                        include_cn_live=True, us_end='2026-10-08')
    for frame in (cn, dk):
        assert frame.index[-1] == before == frame.attrs['cn_confirmed_close']
        assert not frame.attrs['cn_unconfirmed_snapshot']


def test_after_close_live_query_can_show_pending_close_without_mixing_dates(bot):
    clock = pd.Timestamp('2026-10-29 15:02').to_pydatetime()
    before, today = pd.Timestamp('2026-10-28'), pd.Timestamp('2026-10-29')
    raw = frames(bot)
    symbols = {code: code for code in raw}
    resolved, diagnostics = bot._prepare_cn_live_panel(raw, symbols, clock, today, before, io.StringIO(), 'Sub-A')
    assert diagnostics['cn_missing_live_field'] == '当日确认收盘'
    assert diagnostics['cn_confirmed_close'] == before
    assert bot._build_cn_stock_close_frame(resolved).index[-1] == before
    assert all(frame.index[-1] == before for frame in resolved.values())


@pytest.fixture(scope='module')
def adk_history(bot):
    dates = bot._expected_cn_sessions('2026-01-05', '2026-10-28')
    days = np.arange(len(dates))
    prices = pd.DataFrame({
        code: 100 * (1 + .08 * np.sin(days / (9 + 3 * i) + i) + .0001 * i * days)
        for i, code in enumerate(bot.CN_DK_COLS)
    }, index=dates)
    return bot.run_v80_adk_new_only(pd.DataFrame(index=dates), prices)


@pytest.mark.parametrize('kind', ['live_signal', 'live_params'])
def test_adk_history_cannot_display_final_target_during_live_query(bot, monkeypatch, kind, adk_history):
    monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-10-29 14:15').to_pydatetime())
    frame = adk_history.copy()
    frame.attrs.update(cn_missing_live_inputs=(('沪深300', '2026-10-28'),), cn_missing_live_field='今日快照')
    out = io.StringIO()
    info = bot._write_a_adk_query_overview(out.write, None, frame, query_kind=kind, dk_price_frame=frame)
    panel = out.getvalue().split('### ADK策略')[1]
    assert '状态不可判定' in panel and '沪深300（最近有效数据 2026-10-28）' in panel
    assert '历史收盘目标（非今日实时）' in panel and '收盘最终目标' not in panel
    assert not info['Sub-A-DK']['is_signal']


def test_volume_gate_uses_captured_confirmed_cutoff_across_close(bot, monkeypatch):
    prev, today = pd.Timestamp('2026-10-28'), pd.Timestamp('2026-10-29')
    monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-10-29 15:01').to_pydatetime())
    feature = pd.DataFrame({'combined_unresolved': [False]}, index=[prev])
    assert not bot._suba_volume_feature_has_unresolved(feature, [prev, today], confirmed_date=prev)
    assert bot._suba_volume_feature_has_unresolved(feature, [prev, today])


def test_2027_calendar_covers_cross_year_and_published_holidays(bot):
    assert bot._latest_cn_data_required_date('2027-01-04 14:00') == pd.Timestamp('2026-12-31')
    assert bot._latest_cn_data_required_date('2027-01-15 14:00') == pd.Timestamp('2027-01-14')
    pd.testing.assert_index_equal(
        bot._expected_cn_sessions('2027-02-04', '2027-02-15'),
        pd.DatetimeIndex(['2027-02-04', '2027-02-15']),
    )
    with pytest.raises(bot.poe.BotError, match='未配置 2028'):
        bot._latest_cn_data_required_date('2028-01-04 14:00')

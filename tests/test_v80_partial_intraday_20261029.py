"""Synthetic quotes exercise missing-live contracts, not market performance."""
import importlib.util
import io
import sys
from pathlib import Path

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
    monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-10-29 14:15').to_pydatetime())
    monkeypatch.setattr(bot, 'fetch_cn_kline', lambda code, **kw: (raw[code].copy(), 'TEST_ONLY'))
    monkeypatch.setattr(bot, '_fetch_cn_dk_price_index', lambda code, **kw: (raw[code].copy(), 'TEST_ONLY'))
    monkeypatch.setattr(bot, '_ensure_cn_history_frame', lambda code, frame, source, **kw: (frame, source))
    monkeypatch.setattr(bot, '_supplement_today_close', lambda frame, *a: frame)
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

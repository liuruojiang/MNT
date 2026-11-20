"""Native Sub-A source selection, warmup and close-model clock regressions."""
import io
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from test_v80_reporting_repairs_20261015 import v80


ARCHIVE = Path(__file__).resolve().parents[1] / 'research/data_quality/20261106_bond_intraday_acceptance/a_chain/end'


@pytest.fixture
def prices():
    return pd.read_csv(ARCHIVE / 'native_prices.csv', index_col=0, parse_dates=True).loc[:'2026-11-05']


def test_short_preferred_source_uses_full_backup_for_native_signal_and_workbook(v80, prices, monkeypatch):
    bot = v80.CombinedStrategyV80()
    clock = pd.Timestamp('2026-11-06 08:30').to_pydatetime()
    end = prices.index[-1]
    evidence = {end: {c: {'close': float(prices[c].iloc[-1])} for c in prices}}
    monkeypatch.setattr(v80, 'beijing_now', lambda: clock)
    code = v80.CN_EQUITY_CODES[1]
    fetch = v80.fetch_cn_kline
    history = prices[[code]].rename(columns={code: 'close'})
    monkeypatch.setattr(v80, '_fetch_cn_sina', lambda *a: history.tail(90))
    monkeypatch.setattr(v80, '_fetch_cn_eastmoney', lambda *a: history)

    def vendor(symbol, **kwargs):
        if symbol == code:
            frame, name = fetch(symbol, **kwargs)
            assert name == 'EastMoney'
            return frame, name
        return prices[[symbol]].rename(columns={symbol: 'close'}), 'archived'

    monkeypatch.setattr(v80, 'fetch_cn_kline', vendor)
    panel = bot._fetch_cn_price_panel(io.StringIO(), [(c, c, None) for c in v80.CN_ALL_CODES], clock, end, end, evidence)
    feature = pd.read_pickle(ARCHIVE / 'native_result.pkl').filter(regex='^suba_volume_')
    feature.columns = feature.columns.str.removeprefix('suba_volume_')
    monkeypatch.setattr(v80, '_load_suba_volume_signal', lambda **kw: (feature['rule_on'], feature))
    prices.attrs['cn_confirmed_close'] = end
    expected = bot._run_suba(prices, False)
    model = bot._run_suba(panel, False)
    assert panel.index.equals(prices.index)
    pd.testing.assert_frame_equal(model[['weight', 'scale_raw', 'realized_vol']], expected[['weight', 'scale_raw', 'realized_vol']])
    assert model['weight'].iloc[-1] == pytest.approx(1.25)
    day = pd.Timestamp('2026-10-09')
    records = v80.extract_v78_suba_rebalances(model, panel)
    row = next(r for r in records if r['日期'] == '2026-10-09')
    assert row['买入'] == v80.CN_BOND_NAME and row['买入价格'] == pytest.approx(231.096)
    assert '收盘纸面计价' in row['北京时间'] and '15:00' not in row['北京时间']
    assert v80._filter_confirmed_records([row], bj_now=day + pd.Timedelta('15:29:59')) == []
    assert v80._filter_confirmed_records([row], bj_now=day + pd.Timedelta('15:30:00')) == [row]
    assert all(r['confirmation_not_before'].strftime('%H:%M') == '15:30' for r in records)
    xlsx = v80.generate_signal_excel('20261105', {}, [row])
    with io.BytesIO(xlsx) as source:
        book = openpyxl.load_workbook(source, read_only=True)
        headers, values = list(book['调仓记录'].values)
        fields = dict(zip(headers, values))
        assert fields['买入价格'] == row['买入价格']
        assert '15:30' in fields['信号观察'] and '15:30' in fields['价格确认']
        assert '实际成交时刻未核验' in fields['模型计价']
        book.close()


def test_warmup_uses_actual_confirmed_sessions_and_report_selects_longer_history(v80, monkeypatch, prices):
    code = v80.CN_EQUITY_CODES[1]
    h = prices[[code]].rename(columns={code: 'close'})
    n = v80.CN_MIN_HISTORY_ROWS
    assert n == 163
    with pytest.raises(v80.SubaInsufficientHistoryError, match='90'):
        v80.CombinedStrategyV80()._run_suba(prices.tail(90), True)
    opts = {'required_date': h.index[-1], 'verified_close': h['close'].iloc[-1]}
    monkeypatch.setattr(v80, '_fetch_cn_sina', lambda *a: h.tail(n))
    monkeypatch.setattr(v80, '_fetch_cn_eastmoney', lambda *a: h.tail(n - 1))
    assert v80.fetch_cn_kline(code, **opts)[1] == 'Sina'
    with pytest.raises(v80.DataUnavailableError, match='163'):
        v80.fetch_cn_kline(code, confirmed_through=h.index[-2], **opts)
    monkeypatch.setattr(v80, '_fetch_cn_sina', lambda *a: h.tail(90))
    with pytest.raises(v80.SubaInsufficientHistoryError, match='163'):
        v80.fetch_cn_kline(code, **opts)
    conflict = h.tail(90).copy()
    conflict.iloc[-1, 0] *= 1.01
    monkeypatch.setattr(v80, '_fetch_cn_sina', lambda *a: conflict)
    with pytest.raises(v80.DataUnavailableError) as err:
        v80.fetch_cn_kline(code, **opts)
    assert not isinstance(err.value, v80.SubaInsufficientHistoryError)
    monkeypatch.setattr(v80, '_fetch_cn_sina', lambda *a: h.tail(n))
    monkeypatch.setattr(v80, '_fetch_cn_eastmoney', lambda *a: h)
    assert v80.fetch_cn_kline(code, prefer_full_history=True, **opts)[1] == 'EastMoney'
    bad_latest = h.copy()
    bad_latest.iloc[-1, 0] *= 1.01
    monkeypatch.setattr(v80, '_fetch_cn_sina', lambda *a: bad_latest.tail(n))
    monkeypatch.setattr(v80, '_fetch_cn_eastmoney', lambda *a: h.iloc[:-1])
    assert v80.fetch_cn_kline(code, **opts)[1] == 'EastMoney'


def test_reports_keep_adk_if_suba_prices_lack_warmup(v80, monkeypatch):
    bot = v80.CombinedStrategyV80()
    end = pd.Timestamp('2026-11-18')
    monkeypatch.setattr(v80, 'beijing_now', lambda: pd.Timestamp('2026-11-18 16:05').to_pydatetime())
    monkeypatch.setattr(v80, '_fetch_cn_final_sessions', lambda *args: {})
    monkeypatch.setattr(v80, 'US_ALL_TICKERS', ())
    monkeypatch.setattr(v80, '_retry_incomplete_us_price_history', lambda *a, **k: None)
    monkeypatch.setattr(v80, '_v80_us_confirmed_prefix', lambda *a: ({}, {'status': 'unavailable', 'reason': 'offline'}))
    sample = pd.DataFrame({'DK_HS300': [4000.]}, index=[end])
    sample.attrs['cn_confirmed_close'] = end
    def panel(*args, adk, **kwargs):
        if adk:
            return sample
        raise v80.SubaInsufficientHistoryError('Sub-A 仅有90日，需163日')
    monkeypatch.setattr(bot, '_fetch_cn_price_panel', panel)
    cn, dk, *_ = bot._fetch_data(io.StringIO(), allow_last_confirmed_cn_close=True)
    assert cn.empty and '90' in cn.attrs['cn_panel_error']
    assert dk.index.equals(sample.index) and dk.attrs['cn_confirmed_close'] == end
    with pytest.raises(v80.SubaInsufficientHistoryError):
        bot._fetch_data(io.StringIO())
    def conflict(*args, **kwargs):
        raise v80.DataUnavailableError('completed session price conflict')
    monkeypatch.setattr(bot, '_fetch_cn_price_panel', conflict)
    with pytest.raises(v80.DataUnavailableError, match='conflict'):
        bot._fetch_data(io.StringIO(), allow_last_confirmed_cn_close=True)

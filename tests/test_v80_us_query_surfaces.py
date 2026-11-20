"""V8.0 consumer contracts for explicitly degraded US inputs; no provider calls."""
import pandas as pd
import pytest
from pathlib import Path

from test_v80_reporting_repairs_20261015 import report_harness, v80, workbook_sheets


def apply_status(harness, monkeypatch, state):
    cn, dk, us, prod = harness.frames
    if state == 'unavailable':
        us, prod = us.iloc[:0].copy(), prod.iloc[:0].copy()
    for frame in (us, prod):
        frame.attrs['us_data_status'] = dict(status=state, asof=frame.index.max() if len(frame) else None,
                                             required=pd.Timestamp('2026-09-28'), reason='诊断来源覆盖不足')
    monkeypatch.setattr(harness.bot, '_cached_fetch_data', lambda *a, **k: (cn, dk, us, prod))
    result_a, result_dk, result_b, *rest = harness.bot._cached_run_strategies()
    result_a['holding'] = 'cash'
    result_a['is_signal'] = False
    result_dk['holding'] = 'none_0'
    result_dk['weight'] = 0.0
    result_a['weight'] = 0.0
    if state == 'unavailable':
        result_b = None
    elif result_b is not None:
        for frame in [result_b, result_b.attrs['v80_b78']]:
            frame['w_QQQ'] = 1.0
            frame['target_w_QQQ'] = 0.4
    monkeypatch.setattr(harness.bot, '_cached_run_strategies', lambda *a, **k: (result_a, result_dk, result_b, *rest))


@pytest.mark.parametrize('query_kind', ['signal', 'live_signal', 'params', 'live_params'])
@pytest.mark.parametrize('state', ['historical', 'unavailable', 'partial_intraday'])
def test_limited_current_views_keep_cn_and_suppress_us_actions(report_harness, monkeypatch, query_kind, state):
    h = report_harness
    apply_status(h, monkeypatch, state)
    getattr(h.bot, '_handle_' + query_kind)()
    assert 'A / ADK总览' in h.capture.text
    assert '本次无可执行信号' in h.capture.text and '2026-09-28' in h.capture.text
    assert '下一美股开盘执行' not in h.capture.text
    if state == 'historical':
        assert '2026-09-25 历史持仓' in h.capture.text
    if query_kind == 'signal':
        sheet = workbook_sheets(h.capture.attachments[-1]['contents'])['信号概览']
        for row in (4, 5, 6):
            assert sheet[f'B{row}'] == '否'
            assert '2026-09-28' in sheet[f'D{row}']


@pytest.mark.parametrize('method', ['_handle_nav_chart', '_handle_performance', '_handle_signal_history'])
@pytest.mark.parametrize('state', ['historical', 'unavailable'])
def test_historical_queries_keep_actual_dates_and_independent_cn(report_harness, monkeypatch, method, state):
    h = report_harness
    apply_status(h, monkeypatch, state)
    bounds = tuple(pd.Timestamp(day) for day in ['2026-09-01', '2026-09-28'])
    monkeypatch.setattr(h.bot, '_parse_date_with_llm_fallback', lambda query: bounds)
    getattr(h.bot, method)('日期查询')
    assert '2026-09-28' in h.capture.text and '2026-09-01' in h.capture.text
    assert '诊断来源覆盖不足' in h.capture.text
    if method == '_handle_signal_history':
        assert 'Sub-A: A股轮动' in h.capture.text
    else:
        assert 'Sub-A' in h.charts[0]['navs']
        assert ('Combined' in h.charts[0]['navs']) == (state == 'historical')
    if method == '_handle_performance':
        sheets = workbook_sheets(h.capture.attachments[-1]['contents'])
        assert '美股数据覆盖' in sheets['报告元数据'].values()
        assert (sheets['绩效概览']['G2'] == 'N/A') == (state == 'unavailable')


def test_us_snapshot_keeps_original_finality_after_close(v80):
    frame = pd.DataFrame({'SPY': [101.]}, index=pd.to_datetime(['2026-11-19']))
    frame.attrs['us_data_status'] = {'status': 'current', 'intraday_snapshot': True}
    assert v80._subc_query_clock(frame, '2026-11-20 05:00:01')['unconfirmed']


@pytest.mark.parametrize('flag', ['suba_volume_unresolved', 'suba_volume_unavailable'])
def test_confirmed_suba_records_require_both_sides_of_a_known_transition(v80, flag):
    dates = pd.bdate_range('2026-09-14', periods=5)
    result = pd.DataFrame({'holding': ['cash', 'x', 'cash', 'x', 'cash'],
                           'weight': [0., 1., 0., 1., 0.], flag: [False, False, True, False, False]}, index=dates)
    result.attrs['suba_production_mode'] = 'old_a_only_simplified'
    prices = pd.DataFrame({'x': 100.}, index=dates)
    records = v80.extract_v78_suba_rebalances(result, prices)
    assert [rec['日期'] for rec in records] == [dates[1].strftime('%Y-%m-%d'), dates[4].strftime('%Y-%m-%d')]
    result[flag] = True
    assert v80.extract_v78_suba_rebalances(result, prices) == []


def test_original_volume_outage_replay_does_not_export_diagnostic_trades(v80, monkeypatch):
    root = Path(__file__).resolve().parents[1] / 'research/data_quality/20261106_bond_intraday_acceptance/a_chain/end'
    prices = pd.read_csv(root / 'native_prices.csv', index_col=0, parse_dates=True).loc[:'2026-11-05']
    archived = pd.read_pickle(root / 'native_result.pkl').loc[:prices.index[-1]]
    features = archived.filter(regex='^suba_volume_').copy()
    features.columns = features.columns.str.removeprefix('suba_volume_')
    prices.attrs['cn_confirmed_close'] = prices.index[-1]
    monkeypatch.setattr(v80, 'beijing_now', lambda: pd.Timestamp('2026-11-06 08:30').to_pydatetime())
    bot = v80.CombinedStrategyV80()
    monkeypatch.setattr(v80, '_load_suba_volume_signal', lambda **kw: (features['rule_on'], features))
    dates_from = prices.index[-1] - pd.Timedelta(days=60)
    control = bot._run_suba(prices, False)
    assert len(v80.extract_v78_suba_rebalances(control, prices, since_date=dates_from)) == 5

    def unavailable(**kwargs):
        raise v80.DataUnavailableError('controlled amount-feed outage')
    monkeypatch.setattr(v80, '_load_suba_volume_signal', unavailable)
    limited = bot._run_suba(prices, True)
    assert limited['suba_volume_unresolved'].all()
    assert v80.extract_v78_suba_rebalances(limited, prices, since_date=dates_from) == []


@pytest.mark.parametrize('quote, expected, reason', [
    ((84.70, '2026-11-19', None), (85.11000061, 84.70), None),
    ((84.70, '2026-11-19', 85.11), (85.11000061, 84.70), None),
    ((84.70, '2026-11-19', 86.0), None, '冲突'),
    ((84.70, '2026-11-20', None), None, '同一交易日'),
    ((84.70, '2026-11-18', None), None, '同一交易日'),
])
def test_intraday_quote_uses_same_day_raw_open_and_preserves_confirmed(v80, monkeypatch, quote, expected, reason):
    day = pd.Timestamp('2026-11-19')
    prior = pd.DataFrame({'open': [85.], 'close': [85.5]}, index=pd.to_datetime(['2026-11-18']))
    prior.attrs['history_expected_start'] = '2026-11-18'
    source = prior.copy()
    source.attrs['yahoo_partial_raw'] = {'2026-11-18': {'open': 9.}, '2026-11-19': {'open': 85.11000061}}
    source.attrs['yahoo_provisional_market_time'] = '2026-11-19T12:00:00-05:00'
    monkeypatch.setattr(v80, '_fetch_us_realtime_close', lambda ticker: quote)
    monkeypatch.setattr(v80.time, 'sleep', lambda *args: None)
    status = {'status': 'current', 'asof': prior.index[-1], 'intraday_snapshot': False}
    confirmed = {'EMXC': prior}
    result = v80._v80_us_live_panel(confirmed, {'EMXC': source}, ['EMXC'], day, status, None)
    assert prior.index.tolist() == [pd.Timestamp('2026-11-18')] and 'is_live_bar' not in prior
    assert result['EMXC'].attrs['history_expected_start'] == '2026-11-18'
    assert status['asof'] == prior.index[-1]
    if expected:
        assert status['intraday_snapshot'] and result['EMXC'].loc[day, 'is_live_bar']
        assert tuple(result['EMXC'].loc[day, ['open', 'close']]) == pytest.approx(expected)
    else:
        assert result is confirmed and status['status'] == 'partial_intraday'
        assert reason in status['reason'] and not status['intraday_snapshot']


def test_intraday_partial_adjusted_close_is_never_paired_with_unadjusted_open(v80, monkeypatch):
    day = pd.Timestamp('2026-11-19')
    hist = pd.DataFrame({'open': [40.], 'close': [41.]}, index=pd.to_datetime(['2026-11-18']))
    partial = pd.concat([hist, pd.DataFrame({'close': [42.]}, index=[day])])
    partial.attrs['yahoo_partial_raw'] = {'2026-11-19': {'close': 84.}}
    monkeypatch.setattr(v80, '_fetch_us_realtime_close', lambda ticker: (84.0, '2026-11-19', 80.0))
    monkeypatch.setattr(v80.time, 'sleep', lambda *args: None)
    status = {'status': 'current', 'asof': hist.index[-1]}
    panel = v80._v80_us_live_panel({'EMXC': hist}, {'EMXC': partial}, ['EMXC'], day, status, None)
    assert tuple(panel['EMXC'].loc[day, ['open', 'close']]) == pytest.approx((40.0, 42.0))
    assert status['intraday_snapshot'] and panel['EMXC'].loc[day, 'is_live_bar']

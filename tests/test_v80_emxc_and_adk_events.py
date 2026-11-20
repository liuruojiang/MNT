"""Native EMXC quotes and point-in-time ADK close targets share no execution state."""
import importlib.util
from io import BytesIO
from pathlib import Path
import sys

import pandas as pd
import pytest
from openpyxl import load_workbook
from test_v80_reporting_repairs_20261015 import report_harness, v80


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def bot():
    spec = importlib.util.spec_from_file_location('v80_event_review', ROOT / 'mnt_bot V 8.0 plus.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('label', ['B7.8', 'B7.9'])
def test_emxc_records_use_native_quote_and_preserve_model_open(bot, label):
    days = pd.to_datetime([bot.US_ROT_EMXC_BT_START, '2026-09-25'])
    raws = {
        'EMXC': pd.DataFrame({'open': [20., 100.], 'close': [20., 99.], 'raw_open': [21., 101.01]}, index=days),
        'EEM': pd.DataFrame({'open': [40., 74.], 'close': [40., 72.]}, index=days),
    }
    opens = bot._build_us_open_execution_dict(raws)
    assert opens['EMXC'].loc[days[-1]] == 200.
    ledger = pd.DataFrame({'subb_model_execution': [True], 'subb_execution_before_w_EMXC': [.47],
                           'subb_execution_after_w_EMXC': [.435]}, index=days[-1:])
    def report():
        return bot._v80_subb_account_rebalance_records(ledger, raws['EMXC'], opens, label=label)[0]
    assert report()['卖出价格'] == 'EMXC $101.01开'
    del opens['EMXC_raw_open']
    assert 'EMXC $100.00（ETF复权开）' == report()['卖出价格']
    del opens['EMXC_native_open']
    assert report()['卖出价格'] is None


def test_end_date_adk_event_is_stable_and_excel_identifies_target(bot, monkeypatch):
    days = pd.to_datetime(['2026-09-16', '2026-09-17'])
    frame = pd.DataFrame({'v78_adk_final_exposure': [.62, .54]}, index=days)
    frame.attrs['v80_adk_production_mode'] = bot.V80_ADK_PRODUCTION_MODE
    def leg(result, date):
        assert date in result.index
        return [{'leg': 'ADK策略', 'changed': True,
                 'current_pair': '中证1000/上证50' if date == days[0] else 'none',
                 'target_pair': '创业板/上证50' if date == days[0] else 'none',
                 'current_final_text': '多中证1000/空上证50 / 0.62x',
                 'target_final_text': '多创业板/空上证50 / 0.54x'}]
    monkeypatch.setattr(bot, '_v79_adk_leg_execution_rows', leg)
    day_only = bot.extract_v78_adk_rebalances(frame.iloc[:1], since_date=days[0])
    assert day_only == bot.extract_v78_adk_rebalances(frame, since_date=days[0])
    event, = day_only
    assert event['日期'] == '2026-09-16' and event['日期口径'] == 'signal_day'
    assert event['record_kind'] == 'close_target' and event['买入'].startswith('收盘目标')
    assert event['买入价格'] is event['卖出价格'] is None
    intraday = frame.iloc[:1].copy()
    intraday.attrs['cn_unconfirmed_snapshot'] = True
    assert not bot.extract_v78_adk_rebalances(intraday, cn_dk_close=intraday)
    assert not bot.extract_v78_adk_rebalances(frame, since_date=days[-1])
    workbook = load_workbook(BytesIO(bot.generate_signal_excel('20260916', {}, day_only)), read_only=True)
    row = list(workbook['调仓记录'].values)[1]
    assert row[2] == event['策略'] and '收盘目标' in row[5] and row[6] is None


def test_one_return_has_the_same_point_in_both_chart_commands(report_harness):
    day = pd.Timestamp('2026-09-24')
    observed = []
    for command in ('表现', '净值曲线'):
        captured = report_harness.execute(f'{command} {day:%Y-%m-%d}')
        graph, = captured['charts']
        observed.append(graph['navs'])
        assert set(graph['navs']) == {*report_harness.returns.keys(), 'Combined'}
        assert all(series.index.tolist() == [day] for series in graph['navs'].values())
        assert any(file['name'].endswith('.png') for file in captured['attachments'])
    for name in observed[0]:
        pd.testing.assert_series_equal(observed[0][name], observed[1][name])


def test_single_point_markers_use_only_the_observed_day(bot, monkeypatch):
    from matplotlib.axes import Axes
    day = pd.Timestamp('2026-09-24')
    plotted = []
    previous = Axes.plot
    def observe(axes, x, y, **style):
        plotted.append((list(x), style.get('marker')))
        return previous(axes, x, y, **style)
    monkeypatch.setattr(Axes, 'plot', observe)
    png = bot._render_nav_drawdown_chart({'Combined': pd.Series([1.01], index=[day])},
                                         {'Combined': 'PV'}, {'Combined': 'blue'}, day, day)
    assert png.startswith(b'\x89PNG') and plotted == [([day], 'o'), ([day], 'o')]

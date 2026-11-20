"""Consumer regressions for sleeve inception, warmup and full-month samples."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from test_v80_reporting_repairs_20261015 import report_harness, v80, workbook_sheets


@pytest.mark.parametrize('name', ['Sub-A', 'Sub-A-DK', 'B7.8', 'B7.9', 'Sub-C', 'Combined'])
def test_full_month_respects_sleeve_calendar(v80, name):
    cn = v80._expected_cn_sessions('2025-01-01', '2025-01-31')
    us = v80._expected_us_ohlc_index('2025-01-01', '2025-01-31')
    sessions = cn if name in ('Sub-A', 'Sub-A-DK') else cn.union(us) if name == 'Combined' else us
    assert v80._complete_performance_months(sessions, name).tolist() == [pd.Period('2025-01', freq='M')]
    assert list(v80._complete_performance_months(sessions.delete(len(sessions) // 2), name)) == []


def test_original_two_function_path_keeps_month_completeness(v80):
    dates = v80._expected_cn_sessions('2025-01-31', '2025-03-03').union(v80._expected_us_ohlc_index('2025-01-31', '2025-03-03'))
    daily = pd.Series(np.arange(len(dates)) * .0001, index=dates)
    monthly = v80._monthly_returns_from_daily_window(daily, dates[0], dates[-1])
    assert len(monthly) == 3 and monthly.attrs['complete_months'] == (pd.Period('2025-02', 'M'),)
    result = v80.calc_monthly_metrics(monthly)
    assert result['vol'] is result['sharpe'] is None
    assert result['total_return'] == pytest.approx(((1 + daily).prod() - 1) * 100)
    native_monthly = pd.Series([.02, -.01, .012], index=pd.period_range('2025-01', periods=3, freq='M'))
    assert v80.calc_monthly_metrics(native_monthly)['vol'] == pytest.approx(native_monthly.std() * np.sqrt(12) * 100)


@pytest.mark.parametrize('report_harness', [dict(start='2024-12-24', cn_end='2025-04-02', us_end='2025-04-02')], indirect=True)
@pytest.mark.parametrize('start,end,complete', [('2025-01-31', '2025-03-03', 1), ('2025-01-01', '2025-03-31', 3)])
def test_partial_months_excluded_from_risk_metrics_but_kept_in_total(report_harness, start, end, complete):
    out = report_harness.execute(f'表现 {start}到{end}')
    sheets = workbook_sheets(next(a['contents'] for a in out['attachments'] if a['name'].endswith('.xlsx')))
    summary = sheets['绩效概览']
    for column, name in [('B', 'Sub-A'), ('C', 'Sub-A-DK'), ('D', 'B7.8'), ('E', 'B7.9'), ('F', 'Sub-C')]:
        daily = report_harness.returns[name].loc[start:end]
        assert summary[f'{column}2'] == pytest.approx((1 + daily).prod() - 1)
        if complete == 1:
            assert summary[f'{column}4'] == summary[f'{column}5'] == 'N/A'
        else:
            monthly = daily.groupby(daily.index.to_period('M')).apply(lambda x: (1 + x).prod() - 1)
            assert summary[f'{column}4'] == pytest.approx(monthly.std() * np.sqrt(12))
    assert (summary['G4'] == 'N/A') == (complete < 3)
    assert (summary['G5'] == 'N/A') == (complete < 3)


def test_native_suba_first_mature_return_and_bond_receipt_boundary(v80, monkeypatch):
    root = Path(__file__).resolve().parents[1] / 'research/data_quality/20261106_bond_intraday_acceptance/a_chain/end'
    prices = pd.read_csv(root / 'native_prices.csv', index_col=0, parse_dates=True)
    feature = pd.read_pickle(root / 'native_result.pkl').filter(regex='^suba_volume_')
    feature.columns = feature.columns.str.removeprefix('suba_volume_')
    monkeypatch.setattr(v80, '_load_suba_volume_signal', lambda **kw: (feature['rule_on'], feature))
    prices.attrs.update(cn_confirmed_close=prices.index[-1], cn_final_amounts={'x': 1})
    bot = v80.CombinedStrategyV80()
    for n in [0, 90, v80.CN_MIN_HISTORY_ROWS - 1, v80.CN_MIN_HISTORY_ROWS, v80.CN_MIN_HISTORY_ROWS + 1]:
        end = prices.index[n - 1] if n else prices.index.min() - pd.Timedelta(days=1)
        frame = v80._cn_report_price_window(prices, end)
        if n:
            assert frame.attrs['cn_confirmed_close'] == end and 'cn_final_amounts' not in frame.attrs
        result = bot._run_suba(frame, False)
        assert result.index.tolist() == prices.index[v80.CN_MIN_HISTORY_ROWS - 1:n].tolist()
        assert 'return' in result and isinstance(result.index, pd.DatetimeIndex)


def test_native_short_source_reason_reaches_reports_and_workbook(v80, report_harness, monkeypatch):
    reason = 'Sub-A 各源确认行情仅有 162 日，当前及前一日仓位需 163 日预热'
    stock = pd.DataFrame(index=pd.DatetimeIndex([], name='date'))
    stock.attrs['cn_panel_error'] = reason
    frames = (stock, *report_harness.frames[1:])
    bot = report_harness.bot
    results = bot._cached_run_strategies(*frames)
    historical = bot._run_suba(v80._cn_report_price_window(stock, frames[1].index[-1]), False)
    assert historical.attrs['report_unavailable_reason'] == reason
    monkeypatch.setattr(bot, '_cached_fetch_data', lambda *a, **k: frames)
    monkeypatch.setattr(bot, '_cached_run_strategies', lambda *a, **k: (historical, *results[1:]))
    for query in ('表现', '净值曲线'):
        result = report_harness.execute(f'{query} 2026-07-01 到 2026-09-24')
        assert reason in result['text'] and 'Combined：N/A' in result['text']
        if query == '表现':
            book = workbook_sheets(next(a['contents'] for a in result['attachments'] if a['name'].endswith('.xlsx')))
            assert any(reason in str(value) for sheet in book.values() for value in sheet.values())

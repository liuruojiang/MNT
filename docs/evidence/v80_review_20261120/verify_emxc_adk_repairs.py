"""Replay frozen model inputs through the V8.0 quote, account and target-record paths."""
import importlib.util
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

from openpyxl import load_workbook
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
FROZEN = ROOT / 'outputs' / 'v80_recert_20260926'
BOT = 'mnt_bot V 8.0 plus.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_accounts(before, after, close):
    payload = pd.read_pickle(FROZEN / 'l1_final' / 'us_raw_ohlc.pkl')
    raw = {ticker: item['frame'] for ticker, item in payload.items()}
    old_open = before._build_us_open_execution_dict(raw)
    new_open = after._build_us_open_execution_dict(raw)
    for asset in old_open:
        pd.testing.assert_series_equal(old_open[asset], new_open[asset])
    results = {}
    for label, fn in [('B7.8', '_v80_b78_rebuild_subb_account_execution_costs'),
                      ('B7.9', '_rebuild_subb_account_execution_costs')]:
        model = pd.read_pickle(FROZEN / 'l4' / f'b_{label.replace(".", "")}_formal.pkl')
        previous = getattr(before, fn)(model, close, us_open=old_open, strict_open_execution=True)
        updated = getattr(after, fn)(model, close, us_open=new_open, strict_open_execution=True)
        for field in ['return', 'nav', 'subb_execution_cost', 'subb_account_borrow_value']:
            pd.testing.assert_series_equal(previous[field], updated[field], check_exact=True)
        event = after._v80_subb_account_rebalance_records(updated, close, new_open, since_date='2026-09-25', label=label)
        results[label] = {'start': str(updated.index[0].date()), 'end': str(updated.index[-1].date()),
                          'rows': len(updated), 'max_return_difference': (previous['return'] - updated['return']).abs().max()}
        if label == 'B7.9':
            record = next(row for row in event if 'EMXC' in row['卖出'])
            assert '$101.01' in record['卖出价格'] and '$88.42' not in record['卖出价格']
            results[label].update(sale=record['卖出'], report_price=record['卖出价格'])
    return results


def verify_adk(module, stock, prices):
    day = pd.Timestamp('2026-09-16')
    results = []
    for end in [day, pd.Timestamp('2026-09-17')]:
        result = module.run_v80_adk_new_only(stock.loc[:end], prices.loc[:end])
        records = module.extract_v78_adk_rebalances(result, cn_dk_close=prices.loc[:end], since_date=day)
        row, = [item for item in records if item['日期'] == str(day.date())]
        assert row['买入价格'] is row['卖出价格'] is None and row['日期口径'] == 'signal_day'
        assert '0.62x' in row['卖出'] and '创业板' in row['买入'] and '0.54x' in row['买入']
        workbook = module.generate_performance_excel('20260916', {}, {}, [row], True)
        cells = list(load_workbook(io.BytesIO(workbook), read_only=True)['调仓记录'].values)[1]
        assert cells[3] == row['卖出'] and cells[5] == row['买入'] and cells[4] is cells[6] is None
        results.append(row)
    assert results[0] == results[1]
    return results[0]


def verify_first_common_charts(module, pairs, us, prod):
    end = pd.Timestamp('2020-12-03')
    path = ROOT / 'research/data_quality/20261106_bond_intraday_acceptance/a_chain/end'
    cn = pd.read_csv(path / 'native_prices.csv', index_col=0, parse_dates=True)
    features = pd.read_pickle(path / 'native_result.pkl').filter(regex='^suba_volume_')
    features.columns = features.columns.str.removeprefix('suba_volume_')
    prices = tuple(frame.loc[:end] for frame in (cn, pairs, us, prod))
    archived = pd.read_pickle(FROZEN / 'l1_final/formal_inputs.pkl')['us_open']
    bot = module.CombinedStrategyV80()
    bot._us_open = {ticker: series.loc[:end] for ticker, series in archived.items()}
    frozen_b = pd.read_pickle(FROZEN / 'l2/formal_results.pkl')[2]
    class Output(io.StringIO):
        def __init__(self):
            super().__init__()
            self.files = []
        def __exit__(self, *_):
            return False
        def attach_file(self, **kw):
            self.files.append(kw)
    result = {}
    with patch.object(bot, '_cached_fetch_data', return_value=prices), patch.object(
            module, '_load_suba_volume_signal', return_value=(features['rule_on'], features)), patch.object(
            module, '_run_v80_subb_variants', return_value=frozen_b), patch.object(
            module.requests.sessions.Session, 'request', side_effect=AssertionError('offline')):
        for period in ('2020-12-02 至 2020-12-03', '2020-12-03'):
            reference = None
            for cmd in ('表现', '净值曲线'):
                sink = Output()
                query = f'{cmd} {period}'
                with patch.object(module, '_sm', return_value=sink), patch.object(module.poe.query, 'text', query), patch.object(
                        module, '_render_nav_drawdown_chart', wraps=module._render_nav_drawdown_chart) as render:
                    bot._run_impl()
                (call,) = render.call_args_list
                series = call.args[0]
                assert set(series) == set(module.PERFORMANCE_COLUMNS)
                assert series['Combined'].index.tolist() == [end] and series['Sub-C'].index.tolist() == [end]
                assert any(f['name'].endswith('.png') and f['contents'].startswith(b'\x89PNG') for f in sink.files)
                if reference is None:
                    reference = series
                    blob = next(f['contents'] for f in sink.files if f['name'].endswith('.xlsx'))
                    cells = list(load_workbook(io.BytesIO(blob), read_only=True)['绩效概览'].values)[1]
                    for col, name in enumerate(module.PERFORMANCE_COLUMNS, 1):
                        assert abs(cells[col] - (series[name].iloc[-1] - 1)) < 1e-12
                else:
                    for name in reference:
                        pd.testing.assert_series_equal(reference[name], series[name])
                result[query] = {name: len(line) for name, line in series.items()}
    return result


if __name__ == '__main__':
    current = load('event_review_current', ROOT / BOT)
    original = load('event_review_baseline', ROOT / '.codex_backups' / '20261120_113055' / BOT)
    stock, pairs, us, prod = pd.read_pickle(FROZEN / 'l1_final' / 'formal_inputs.pkl')['frames']
    if '--adk' in sys.argv:
        print(json.dumps(verify_adk(current, stock, pairs), ensure_ascii=False))
    elif '--charts' in sys.argv:
        print(json.dumps(verify_first_common_charts(current, pairs, us, prod), ensure_ascii=False))
    else:
        print(json.dumps(verify_accounts(original, current, us), ensure_ascii=False))

"""Offline replay of the pre-inception queries and complete-month report statistics."""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

import openpyxl
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'outputs/v80_recert_20260926'
spec = importlib.util.spec_from_file_location('report_repair', ROOT / 'mnt_bot V 8.0 plus.py')
v = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v
spec.loader.exec_module(v)


class Capture(io.StringIO):
    def __init__(self):
        super().__init__()
        self.files = []

    def __exit__(self, *_):
        return False

    def attach_file(self, *, name, contents, **kwargs):
        self.files.append((name, contents))


def verify():
    path = ARCHIVE / 'l1_final/formal_inputs.pkl'
    archive = pd.read_pickle(path)
    stock, dk, us, prod = archive['frames']
    bond = pd.read_csv(ROOT / 'research/data_quality/20261105_bond_replacement/native_bond_history.csv',
                       index_col='date', parse_dates=True)['close']
    stock = stock[v.CN_STOCK_CODES].copy()
    stock[v.CN_BOND_CODE] = bond.reindex(stock.index)
    end = pd.Timestamp('2017-06-30')
    frames = stock.loc[:end], dk.loc[:end], us.loc[:end], prod.loc[:end]
    bot = v.CombinedStrategyV80()
    bot._us_open = {ticker: value.loc[:end] for ticker, value in archive['us_open'].items()}
    native_b = v._run_v80_subb_variants(frames[2], us_open=bot._us_open, strict_open_execution=True)
    checks = []
    with patch.object(bot, '_cached_fetch_data', return_value=frames), patch.object(v, '_run_v80_subb_variants', return_value=native_b):
        for start, finish in [('2016-01-01', '2016-12-30'), ('2017-01-01', '2017-06-30')]:
            for prefix in ('表现', '净值曲线'):
                query = f'{prefix} {start} 至 {finish}'
                sink = Capture()
                with patch.object(v, '_sm', return_value=sink), patch.object(v.poe.query, 'text', query):
                    bot._run_impl()
                text = sink.getvalue()
                assert 'Sub-A：N/A' in text and 'Combined：N/A' in text
                assert 'Sub-C：N/A' in text and 'B7.8' in text and 'B7.9' in text
                png = next(blob for name, blob in sink.files if name.endswith('.png'))
                assert png.startswith(b'\x89PNG')
                item = dict(query=query, png_bytes=len(png), omitted=['Sub-A', 'Sub-C', 'Combined'])
                if prefix == '表现':
                    blob = next(blob for name, blob in sink.files if name.endswith('.xlsx'))
                    book = openpyxl.load_workbook(io.BytesIO(blob), read_only=True)
                    cells = list(next(book['绩效概览'].iter_rows(min_row=2, max_row=2, values_only=True)))[1:]
                    assert [i for i, value in enumerate(cells) if isinstance(value, float)] == [1, 2, 3]
                    assert [cells[i] for i in (0, 4, 5)] == ['N/A'] * 3
                    item['workbook_available'] = ['Sub-A-DK', 'B7.8', 'B7.9']
                checks.append(item)
    data = pd.read_csv(ARCHIVE / 'l8/cross/formal_daily_returns.csv.gz', parse_dates=['date']).set_index('date').return_net
    for start, finish in [('2025-01-31', '2025-03-03'), ('2025-01-01', '2025-03-31')]:
        daily = data.loc[start:finish]
        monthly = v._monthly_returns_from_daily_window(daily, start, finish)
        full = v._complete_performance_months(daily.index, 'Combined')
        assert tuple(full) == monthly.attrs['complete_months']
        metric = v.calc_monthly_metrics(monthly)
        assert (metric['vol'] is None) == (len(full) < 3)
        checks.append(dict(range=[start, finish], complete_months=list(map(str, full)),
                           vol=metric['vol'], sharpe=metric['sharpe'], all_days_total_pct=metric['total_return']))
    return dict(frozen_input_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                inputs='Local frozen prices, adjusted opens and confirmed native bond. US variants computed once for the shared prefix.',
                checks=checks)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    def no_network(*a, **kw):
        raise AssertionError('Offline evidence only')
    with patch.object(v.requests.sessions.Session, 'request', no_network):
        report = json.dumps(verify(), ensure_ascii=False, indent=2)
    print(report)
    if args.out:
        args.out.write_text(report + '\n', encoding='utf-8')

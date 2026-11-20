"""Independent offline checks of Sub-A source selection, warmup and paper-close receipts."""
import argparse
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pandas as pd

from verify_report_repairs import Capture, ROOT, v


def verify():
    native = ROOT / 'research/data_quality/20261106_bond_intraday_acceptance/a_chain/end'
    prices = pd.read_csv(native / 'native_prices.csv', index_col=0, parse_dates=True)
    n = v.CN_MIN_HISTORY_ROWS
    cutoff, prior = prices.index[-1], prices.index[-2]
    asset = v.CN_STOCK_CODES[0]
    source = prices[asset].rename('close').to_frame()
    def select(inputs, **kw):
        return v._fetch_cn_index_history(asset, [(name, lambda item=frame: item) for name, frame in inputs],
                                         required_date=cutoff, formal_start=v.CN_STOCK_FORMAL_START,
                                         min_rows=n, verified_close=source.at[cutoff, 'close'], **kw)[1]
    assert select([('short', source.tail(n - 1)), ('full', source)]) == 'full'
    assert select([('short', source.tail(n)), ('full', source)]) == 'short'
    assert select([('short', source.tail(n)), ('full', source)], prefer_full_history=True) == 'full'
    assert select([('provisional', source.tail(n)), ('full', source)], confirmed_through=prior) == 'full'
    assert select([('gapped', source.tail(n + 3).drop(source.index[-20])), ('full', source)]) == 'full'

    archive = pd.read_pickle(ROOT / 'outputs/v80_recert_20260926/l1_final/formal_inputs.pkl')
    historical = archive['frames'][1]['DK_SZ50'].rename('close').to_frame().loc[:'2017-06-30']
    try:
        v._fetch_cn_index_history('1.000016', [('prepublication', lambda: historical)],
                                  required_date=historical.index[-1], formal_start=v.CN_STOCK_FORMAL_START, min_rows=n)
    except v.SubaInsufficientHistoryError:
        pass
    else:
        raise AssertionError('Pre-publication rows entered formal warmup')

    receipts = {day: {code: {'close': prices.at[day, code]} for code in v.CN_ALL_CODES}
                for day in (prior, cutoff)}
    del receipts[cutoff][v.CN_BOND_CODE]
    bot = v.CombinedStrategyV80()
    def panel(window):
        def supply(code, **kw):
            return prices[code].tail(window).rename('close').to_frame(), 'native-archive'
        with patch.object(v, 'fetch_cn_kline', side_effect=supply):
            return bot._fetch_cn_price_panel(io.StringIO(), [(code, code, None) for code in v.CN_ALL_CODES],
                                             cutoff + pd.Timedelta(hours=15, minutes=5), cutoff, prior, receipts)
    try:
        panel(n)
    except v.SubaInsufficientHistoryError as exc:
        assert str(n - 1) in str(exc)
    else:
        raise AssertionError('Incomplete bond receipt advanced the common confirmed-day count')
    accepted = panel(n + 1)
    assert len(accepted) == n and accepted.index[-1] == accepted.attrs['cn_confirmed_close'] == prior

    # Check the public history/report handlers request the longest verified source.
    class StopAfterFetch(Exception):
        pass
    fetch_flags = {}
    for label, handler in [('history', bot._handle_signal_history), ('performance', bot._handle_performance),
                           ('chart', bot._handle_nav_chart)]:
        with patch.object(bot, '_cached_fetch_data', side_effect=StopAfterFetch) as spy, patch.object(v, '_sm', return_value=Capture()):
            try:
                handler('2025-01-01 到 2025-03-31', _forced_range=(pd.Timestamp('2025-01-01'), pd.Timestamp('2025-03-31')))
            except StopAfterFetch:
                pass
            fetch_flags[label] = spy.call_args.kwargs.get('allow_last_confirmed_cn_close', False)
            assert fetch_flags[label]

    held = pd.read_pickle(native / 'native_result.pkl')
    records = v.extract_v78_suba_rebalances(held, prices, since_date=pd.Timestamp('2026-01-01'))
    rec = next(row for row in reversed(records) if row.get('record_kind') == 'position'
               and any('国债' in row.get(column, '') for column in ('买入', '卖出')))
    at = pd.Timestamp(rec['日期']) + pd.Timedelta(hours=15, minutes=30)
    assert not v._filter_confirmed_records([rec], bj_now=at - pd.Timedelta(seconds=1))
    assert v._filter_confirmed_records([rec], bj_now=at) == [rec]
    with patch.object(v, '_fetch_cn_trend_rows', side_effect=AssertionError('premature receipt')):
        assert not v._fetch_cn_final_sessions(v.CN_BOND_CODE, [at.normalize()], at - pd.Timedelta(seconds=1))
    workbooks = {'signal': v.generate_signal_excel(rec['日期'], {}, [rec]),
                 'performance': v.generate_performance_excel(rec['日期'], {}, {}, [rec])}
    for blob in workbooks.values():
        book = openpyxl.load_workbook(io.BytesIO(blob), read_only=True)
        head, values = list(book['调仓记录'].values)[:2]
        persisted = dict(zip(head, values))
        for key in ('北京时间', '模型计价', '价格确认', '信号观察'):
            assert persisted[key] == rec[key]
        assert '实际成交时刻未核验' in persisted['模型计价'] and '15:30' in persisted['价格确认']

    return dict(input_sha256={name: hashlib.sha256((native / name).read_bytes()).hexdigest()
                              for name in ('native_prices.csv', 'native_result.pkl')},
                first_source_rows=n, longest_source_rows=len(source), formal_start=str(v.CN_STOCK_FORMAL_START.date()),
                prepublication_input_rows=len(historical), admitted_rows_since_publication=len(historical.loc[v.CN_STOCK_FORMAL_START:]),
                confirmed_day_gate=dict(minimum=n, partial_final_session=str(cutoff.date()), accepted_through=str(prior.date())),
                long_history_source_requested=fetch_flags,
                archived_trade=dict(date=rec['日期'], sold=rec['卖出'], bought=rec['买入'], time=rec['北京时间'],
                                    one_second_before='excluded', at_1530_with_verified_inputs='included',
                                    price_confirmation=rec['价格确认'], paper_price=rec['模型计价']),
                workbook_roundtrips=list(workbooks))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    with patch.object(v.requests.sessions.Session, 'request', side_effect=AssertionError('offline probe')):
        report = json.dumps(verify(), ensure_ascii=False, indent=2)
    print(report)
    if args.out:
        args.out.write_text(report + '\n', encoding='utf-8')

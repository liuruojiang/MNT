"""Offline extraction of actual archived issuer workbooks. Never fetches or repairs prices."""
import argparse
import base64
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import zipfile

import xlrd  # Legacy XLS capability; read only.
import openpyxl


def amount(value):
    return Decimal(str(value or 0))


def read(path, digest):
    raw = path.read_bytes()
    assert base64.b32encode(hashlib.sha1(raw).digest()).decode().rstrip('=') == digest
    result = []
    # Some real legacy OLE workbooks contain an embedded ZIP; inspect the
    # outer signature rather than mistaking the embedded stream for OOXML.
    if raw.startswith(b'PK\x03\x04'):
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = book['Primary Layout']
        for i, row in enumerate(sheet.iter_rows(values_only=True), 1):
            result.append((i, [x.date().isoformat() if isinstance(x, datetime) else x for x in row]))
        book.close()
    else:
        assert raw.startswith(bytes.fromhex('d0cf11e0a1b11ae1'))
        book = xlrd.open_workbook(path)
        sheet = book.sheet_by_name('Primary Layout')
        for i in range(sheet.nrows):
            row = [xlrd.xldate_as_datetime(c.value, book.datemode).date().isoformat()
                   if c.ctype == xlrd.XL_CELL_DATE else c.value for c in sheet.row(i)]
            for j in (6, 7, 8):
                if isinstance(row[j], str) and '/' in row[j]:
                    row[j] = datetime.strptime(row[j], '%m/%d/%Y').date().isoformat()
            result.append((i+1, row))
    return result, {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
                    'CDX_sha1_base32': digest, 'CDX_digest_matches': True, 'sheet': 'Primary Layout'}


def verify(vanguard, qqq):
    records = []
    for year, extension, digest, day, total, income, short, long, record, pay in [
        (2013, 'xls', 'RB6XQBLKTJCN3RRMCUEFFBIRTPC5OABF', '2013-12-24', '.263', '.074', '.015', '.174', '2013-12-27', '2013-12-31'),
        (2015, 'xlsx', 'BLGGDB6FQL5IJU35XWWNHCLAEFHZVPPF', '2015-11-02', '.085', '.085', '0', '0', '2015-11-04', '2015-11-06'),
    ]:
        rows, provenance = read(vanguard/f'{year}_Primary_Layout_archived.{extension}', digest)
        selected = [(i, r) for i, r in rows if r[1] == '92206C706' and r[7] == day]
        assert len(selected) == 1
        i, r = selected[0]
        assert r[2] == 'VGIT' and r[6] == record and r[8] == pay
        assert all(not r[j] for j in (3, 4, 5))  # E/R/C markers retained, never assumed away.
        assert [amount(r[j]) for j in (9, 13, 14, 21)] == list(map(Decimal, (total, income, short, long)))
        assert amount(r[9]) == sum(amount(r[j]) for j in (13, 14, 21, 25, 27, 29))
        assert amount(r[16]) == sum(amount(r[j]) for j in (13, 14, 15))
        records.append({'id': f'VGIT_{day}', 'status': 'CONFIRMED_CASH_EVENT',
            'cash_usd_per_share': str(Decimal(total)), 'ex_date': day, 'record_date': record, 'pay_date': pay,
            'income': str(Decimal(income)), 'short_term_gain': str(Decimal(short)), 'long_term_gain': str(Decimal(long)),
            'return_of_capital': str(amount(r[25])), 'estimated_flag': r[3], 'reclass_flag': r[4], 'corrected_flag': r[5],
            'ordinary_1099_includes_short_term': True, 'source': {**provenance, 'row_1based': i},
            'inference': False, 'production_approved': False})
    for year, digest, disputed, total in [
        (2010, 'BEIUQUTG7AJSJ3HR5VJC32SKMSIFD7TI', '2010-06-25', '.36063'),
        (2011, 'MUGL3S6RSZLDHVVOOMH6TNTBJE4UDK5J', '2011-12-27', '.46252'),
    ]:
        rows, provenance = read(qqq/f'workbook_{year}.bin', digest)
        selected = [(i, r) for i, r in rows if r[1] == '73935A104']
        assert len(selected) == 4 and all(r[2] in ('QQQ', 'QQQQ') and not r[3] for _, r in selected)
        assert all(r[7].startswith(str(year)) for _, r in selected)
        assert disputed not in [r[7] for _, r in selected]
        total_row_index = selected[-1][0]+1
        _, annual_total = next((i, r) for i, r in rows if i == total_row_index)
        assert annual_total[0] == 'Total'
        assert sum(amount(r[9]) for _, r in selected) == amount(annual_total[9]) == Decimal(total)
        assert all(amount(r[9]) == sum(amount(r[j]) for j in (13, 14, 21, 25, 27, 29)) for _, r in selected)
        records.append({'id': f'QQQ_{disputed}', 'status': 'CONFIRMED_NO_CASH_EVENT', 'cash_usd_per_share': '0',
            'ex_date': disputed, 'source': {**provenance, 'event_rows_1based': [i for i, _ in selected], 'total_row_1based': total_row_index},
            'actual_distribution_dates': [r[7] for _, r in selected], 'annual_total_usd': str(Decimal(total)),
            'estimated_flags': [r[3] for _, r in selected], 'reclass_flags': [r[4] for _, r in selected],
            'inference': True, 'basis': 'Retrospective inference from complete final annual tax statement and explicit reconciled Total; not an explicit zero row, not PIT certification',
            'production_approved': False})
    return {'status': 'PASS', 'network_requests': 0, 'records': records, 'strategy_backtests_run': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--vanguard-dir', type=Path, required=True)
    parser.add_argument('--qqq-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.vanguard_dir, args.qqq_dir)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: 2 exact VGIT cash records, 2 QQQ complete-annual-statement no-event inferences; zero requests')

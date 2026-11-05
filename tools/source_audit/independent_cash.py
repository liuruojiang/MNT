"""Read exact issuer records; a cash finding never qualifies a price series."""
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from bs4 import BeautifulSoup

from .transport import sha256


def cash(value):
    amount = Decimal(str(value).replace('$', '').replace(',', '').strip())
    if not amount.is_finite() or amount <= 0:
        raise ValueError('No positive final issuer cash amount')
    return str(amount)


def iso(value, fmt='%m/%d/%Y'):
    return datetime.strptime(value, fmt).date().isoformat()


@lru_cache(maxsize=16)
def extract(kind, body, symbol, ex_date):
    if kind == 'ishares':
        identities = {'AGG': '464287226', 'TLT': '464287432'}
        soup = BeautifulSoup(body, 'html.parser')
        if identities.get(symbol) not in soup.get_text(' ', strip=True):
            raise ValueError('Issuer CUSIP identity mismatch')
        tables = [t for t in soup.find_all('table') if [h.get_text(' ', strip=True) for h in t.find_all('th')] ==
                  ['Record Date', 'Ex-Date', 'Payable Date', 'Total Distribution', 'Income', 'ST Cap Gains', 'LT Cap Gains', 'Return of Capital']]
        rows = []
        for table in tables:
            for tr in table.find_all('tr'):
                cells = [c.get_text(' ', strip=True) for c in tr.find_all('td')]
                if len(cells) == 8 and iso(cells[1], '%b %d, %Y') == ex_date:
                    if Decimal(cells[3].replace('$', '')) != sum(Decimal(x.replace('$', '')) for x in cells[4:]):
                        raise ValueError('Issuer distribution categories do not sum')
                    rows.append({'cash_usd_per_share': cash(cells[3]), 'ex_date': ex_date,
                                 'record_date': iso(cells[0], '%b %d, %Y'), 'pay_date': iso(cells[2], '%b %d, %Y')})
    elif kind == 'ssga':
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            strings = [''.join(si.itertext()) for si in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('s:si', ns)]
            root = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        rows = []
        for tr in root.findall('.//s:row', ns):
            values = {}
            for c in tr.findall('s:c', ns):
                v = c.find('s:v', ns)
                if v is not None:
                    values[''.join(x for x in c.attrib['r'] if x.isalpha())] = strings[int(v.text)] if c.get('t') == 's' else v.text
            if values.get('B') == symbol and iso(values['D']) == ex_date:
                if symbol != 'BIL' or values.get('C') != '78468R663':
                    raise ValueError('State Street CUSIP mismatch')
                total = sum(Decimal(values.get(k, '').strip() or '0') for k in ('G', 'H', 'I'))
                rows.append({'cash_usd_per_share': cash(total), 'ex_date': ex_date,
                             'record_date': iso(values['E']), 'pay_date': iso(values['F'])})
    elif kind == 'vanguard':
        soup = BeautifulSoup(body, 'html.parser')
        nodes = soup.find_all(attrs={'data-vgn-funds-profile': True})
        if len(nodes) != 1:
            raise ValueError('Ambiguous Vanguard profile')
        data = json.loads(nodes[0]['data-vgn-funds-profile'])
        if symbol != 'VGIT' or data['overview'].get('cusip') != '92206C706' or data['overview'].get('fundId') != '3143':
            raise ValueError('Vanguard identity mismatch')
        # The reinvest date is not independently assumed to be the ex-date;
        # load_cases also requires the dated official schedule evidence.
        rows = [{'cash_usd_per_share': cash(r['share']), 'ex_date': ex_date,
                 'record_date': iso(r['recordDate']), 'pay_date': iso(r['payableDate'])}
                for r in data['distributions']['incomeCapitalGains']
                if r.get('type') == 'Dividend' and iso(r['reInvestDate']) == ex_date]
    else:
        raise ValueError('Unreviewed issuer parser')
    if len(rows) != 1:
        raise ValueError('Missing or duplicate exact issuer event')
    return rows[0]


def load_cases(repo):
    repo = Path(repo).resolve()
    path = repo / 'research/data_quality/independent_cash_references.json'
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('purpose') != 'research_only' or data.get('production_approved') is not False:
        raise ValueError('Independent cash registry is outside research scope')
    for case in data['cases']:
        bodies = []
        for item in case['evidence']:
            source = (repo / item['artifact']).resolve()
            if not source.is_relative_to(repo):
                raise ValueError('Issuer evidence path outside repository')
            body = source.read_bytes()
            if sha256(body) != item['sha256']:
                raise ValueError('Issuer evidence hash mismatch')
            bodies.append(body)
        actual = extract(case['issuer_parser'], bodies[0], case['symbol'], case['ex_date'])
        if any(str(actual[k]) != str(case['resolution'][k]) for k in actual):
            raise ValueError('Cash registry differs from actual issuer row')
        if case['issuer_parser'] == 'vanguard':
            schedule = bodies[-1].decode('utf-8')
            if not all(s in schedule for s in ['92206C706 VGIT', '11/02/26 11/02/26 11/04/26', 'EX-DIVIDEND']):
                raise ValueError('Exact Vanguard ex-date schedule missing')
    return data['cases']

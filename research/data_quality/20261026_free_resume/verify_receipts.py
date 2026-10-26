"""Offline receipt verification; never reads credentials or makes API requests."""
import hashlib
import json
from pathlib import Path


def verify(evidence):
    evidence = Path(evidence)
    receipts = sorted(evidence.rglob('*_receipt.json'))
    checked = []
    for path in receipts:
        receipt = json.loads(path.read_text(encoding='utf-8'))
        if receipt.get('provider') != 'wind':
            continue
        raw = path.parent / receipt['raw_file']
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == receipt['sha256'], path
        assert receipt['status'] == 200, path
        body = raw.read_text(encoding='utf-8')
        try:
            value = json.loads(body)
        except json.JSONDecodeError:
            events = [line[5:].strip() for line in body.splitlines() if line.startswith('data:')]
            assert len(events) == 1, path
            value = json.loads(events[0])
        assert value['result'].get('isError') is False, path
        parsed = path.parent / receipt['parsed_file']
        assert json.loads(parsed.read_text(encoding='utf-8')) == value, path
        payload = json.loads(value['result']['content'][0]['text'])
        assert payload.get('error') is None and payload['data']['rows'], path
        checked.append({'receipt': str(path), 'sha256': receipt['sha256'],
                        'request_id': receipt['request_id'],
                        'arguments': receipt['arguments'],
                        'rows': len(payload['data']['rows'])})
    assert len(checked) == 7, len(checked)
    assert len({x['request_id'] for x in checked}) == 7
    independent = []
    dates = ['2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23', '2026-10-26']
    fields = {'open': 'OPEN', 'high': 'HIGH', 'low': 'LOW', 'close': 'MATCH', 'volume': 'VOLUME'}
    for code, stem in [('000300', '002_000300_SH_short'), ('000852', '004_000852_SH_short')]:
        value = json.loads((evidence/'range_probes'/f'{stem}_parsed.json').read_text(encoding='utf-8'))
        data = json.loads(value['result']['content'][0]['text'])['data']
        columns = [column['name'] for column in data['columns']]
        wind = {row[columns.index('TIME')][:10]: dict(zip(columns, row)) for row in data['rows']}
        raw = evidence/'independent'/f'{code}_sina_raw.json'
        receipt = json.loads(raw.with_name(f'{code}_sina_receipt.json').read_text(encoding='utf-8'))
        assert receipt['status'] == 200
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == receipt['sha256']
        sina = {row['day']: row for row in json.loads(raw.read_text(encoding='utf-8'))}
        differences = {field: max(abs(float(wind[day][target])-float(sina[day][field]))
                                 for day in dates) for field, target in fields.items()}
        assert all(value <= (100 if field == 'volume' else .011) for field, value in differences.items())
        independent.append({'code': code, 'provider': 'Sina third-party, not CSI official',
                            'dates': dates, 'max_abs_differences': differences,
                            'sha256': receipt['sha256'], 'turnover_certified': False})
    return {'status': 'PASS', 'scope': 'Seven actual successful Wind receipts; not full data approval',
            'network_requests': 0, 'checked': checked, 'independent_recomputed': independent}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = verify(args.evidence)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: 7 Wind receipts, original bytes and parsed payloads verified; 0 requests')

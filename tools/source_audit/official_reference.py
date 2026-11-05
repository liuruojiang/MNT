"""Immutable, dated public CSI bond-close references; no production writes."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import requests


def refresh_bond_reference(directory, output, cutoff):
    source = Path(directory) / 'H11077.json'
    old = json.loads(source.read_text(encoding='utf-8')) if source.exists() else {'code': '200', 'data': []}
    end = cutoff.replace('-', '')
    existing = {r['tradeDate']: r for r in old['data']}
    if end in existing:
        return Path(directory), {'status': 'EXACT_CUTOFF_REFERENCE_REUSED', 'cutoff': cutoff, 'requests': 0}
    target = Path(output) / 'official_reference'
    target.mkdir(parents=True)
    for path in Path(directory).glob('*.json'):
        shutil.copyfile(path, target / path.name)
    begin = max(existing) if existing else '20260101'
    url = ('https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=H11077'
           '&startDate=' + begin + '&endDate=' + end)
    receipt = {'provider': 'CSI official', 'url': url, 'cutoff': cutoff, 'requests': 1,
               'retrieved_at_utc': datetime.now(timezone.utc).isoformat(), 'production_approved': False}
    try:
        response = requests.get(url, timeout=25, headers={'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.csindex.com.cn/zh-CN/indices/index-detail/931077'})
        body = response.content
        (target / 'H11077_fresh_raw.json').write_bytes(body)
        receipt.update(status=response.status_code, sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
        response.raise_for_status()
        value = json.loads(body)
        if str(value.get('code')) != '200' or not isinstance(value.get('data'), list) or not value['data']:
            raise ValueError('Official reference schema or empty response')
        seen = set()
        for row in value['data']:
            day = row['tradeDate']
            if row.get('indexCode') != 'H11077' or day in seen or not begin <= day <= end:
                raise ValueError('Official reference identity or date mismatch')
            seen.add(day)
            if day in existing and row['close'] != existing[day]['close']:
                raise ValueError('Official historical close revised; independent review required')
            existing[day] = row
        merged = {'code': '200', 'data': [existing[d] for d in sorted(existing)]}
        # Full numerical/date/independent-close qualification remains in the
        # bond auditor; a successful download never grants research acceptance.
        (target / 'H11077.json').write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')
        receipt['assessment'] = 'DOWNLOADED_NOT_QUALIFIED'
        receipt['last_returned_date'] = max(seen)
    except Exception as exc:
        # Preserve the raw failed response and stop this refresh, never retry or
        # substitute an earlier reference after conflicting fresh evidence.
        (target / 'H11077.json').write_text('{"code":"REFERENCE_REFRESH_FAILED","data":[]}', encoding='utf-8')
        receipt.update(assessment='BLOCKED', error_type=type(exc).__name__)
    (target / 'reference_receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return target, receipt

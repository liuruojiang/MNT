"""One-off read-only intraday acceptance; raw response timestamps are authoritative."""
import concurrent.futures
import hashlib
import importlib.util
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BJ = ZoneInfo('Asia/Shanghai')
SPEC = importlib.util.spec_from_file_location('bond_acceptance_v80', ROOT / 'mnt_bot V 8.0 plus.py')
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)
SOURCES = {
    'tencent': ('https://qt.gtimg.cn/q=sh000012', 'https://gu.qq.com/'),
    'sina': ('https://hq.sinajs.cn/list=sh000012', 'https://finance.sina.com.cn/'),
}


def collect(provider, round_number):
    url, referer = SOURCES[provider]
    base = OUT / f'round_{round_number:02d}_{provider}'
    receipt = {'round': round_number, 'provider': provider, 'symbol': '000012.SH', 'request_url': url,
               'request_started_utc': datetime.now(timezone.utc).isoformat()}
    try:
        response = requests.get(url, timeout=15, headers={'Referer': referer})
        receipt.update(retrieved_at_utc=datetime.now(timezone.utc).isoformat(), url=response.url,
                       http_status=response.status_code, bytes=len(response.content),
                       sha256=hashlib.sha256(response.content).hexdigest())
        base.with_suffix('.raw').write_bytes(response.content)
        response.raise_for_status()
        text = response.content.decode('gb18030')
        payload = text.split('"')[1]
        if provider == 'tencent':
            fields = payload.split('~')
            assert text.startswith('v_sh000012="') and fields[2] == '000012', 'wrong symbol'
            stamp = datetime.strptime(fields[30], '%Y%m%d%H%M%S').replace(tzinfo=BJ)
        else:
            fields = payload.split(',')
            assert text.startswith('var hq_str_sh000012="'), 'wrong symbol'
            stamp = datetime.fromisoformat(fields[30] + 'T' + fields[31]).replace(tzinfo=BJ)
        price = float(fields[3])
        receipt.update(quote_time=stamp.isoformat(), price=price,
                       lag_seconds=(datetime.fromisoformat(receipt['retrieved_at_utc'])-stamp).total_seconds(),
                       native_time_gate=bool(M._cn_quote_time_valid(pd.Timestamp(stamp), datetime.now(BJ).date())))
        assert math.isfinite(price) and price > 0, 'invalid price'
        assert stamp.date().isoformat() == '2026-11-06', 'wrong quote date'
        assert receipt['native_time_gate'], 'native 5-minute/session/date freshness gate rejected'
        receipt['status'] = 'PASS'
    except Exception as exc:
        receipt['status'] = 'FAIL'
        receipt['error'] = f'{type(exc).__name__}: {exc}'
    base.with_suffix('.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return receipt


def main():
    now = datetime.now(BJ)
    assert now.date().isoformat() == '2026-11-06' and (now.hour, now.minute) < (11, 0), 'outside target window'
    start = time.monotonic()
    manifest = {'started_at': now.isoformat(), 'source_sha256': hashlib.sha256((ROOT / 'mnt_bot V 8.0 plus.py').read_bytes()).hexdigest(),
                'round_interval_seconds': 300, 'planned_rounds': 7, 'rounds': []}
    for number in range(1, 8):
        target = start + (number - 1) * 300
        while time.monotonic() < target:
            time.sleep(min(30, target - time.monotonic()))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            receipts = list(executor.map(lambda provider: collect(provider, number), SOURCES))
        item = {'round': number, 'receipts': receipts}
        if all('price' in rec for rec in receipts):
            item['absolute_difference'] = abs(receipts[0]['price'] - receipts[1]['price'])
            item['within_0_011'] = item['absolute_difference'] <= 0.011
        manifest['rounds'].append(item)
        (OUT / 'quote_progress.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        pd.DataFrame([rec for item in manifest['rounds'] for rec in item['receipts']]).to_csv(OUT / 'quote_rounds.csv', index=False, encoding='utf-8-sig')
        print(json.dumps(item, ensure_ascii=False), flush=True)
    manifest['completed_at'] = datetime.now(BJ).isoformat()
    manifest['summary'] = {}
    for provider in SOURCES:
        rows = [rec for item in manifest['rounds'] for rec in item['receipts'] if rec['provider'] == provider]
        stamps = [rec['quote_time'] for rec in rows if 'quote_time' in rec]
        manifest['summary'][provider] = {'passed': sum(rec['status'] == 'PASS' for rec in rows),
                                        'failed': sum(rec['status'] != 'PASS' for rec in rows),
                                        'max_lag_seconds': max((rec.get('lag_seconds', float('-inf')) for rec in rows)),
                                        'unique_quote_times': len(set(stamps)),
                                        'strictly_advancing': len(stamps) == 7 and all(b > a for a, b in zip(stamps, stamps[1:]))}
    manifest['pass'] = all(s['passed'] == 7 and s['strictly_advancing'] for s in manifest['summary'].values()) and all(item.get('within_0_011', False) for item in manifest['rounds'])
    (OUT / 'quote_final.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest['summary'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

"""Explicit public research alternatives; original provider failures stay visible."""
from datetime import datetime, timezone
import json
from pathlib import Path

import requests

from .calendar import sessions
from .compare import finite, validate_bar
from .transport import sha256


SYMBOL = '518880.SH'
PROVIDERS = ('tencent', 'eastmoney', 'sina')
CONTRACTS = {
    '000012.SH': {'code': '000012', 'name': '国债', 'tencent_key': 'day', 'fqt': 0, 'tolerance': .011,
                  'providers': ('tencent', 'sina'), 'fields': ['close'],
                  'adjustment': 'Published broad government bond index points; no equity adjustment; distinct from H11077'},
    '518880.SH': {'code': '518880', 'name': '黄金', 'tencent_key': 'qfqday', 'fqt': 1, 'tolerance': .0011,
                  'adjustment': 'provider_native_qfq; matches Sina unadjusted OHLC only in the stated window'},
    '000905.SH': {'code': '000905', 'name': '中证500', 'tencent_key': 'day', 'fqt': 0, 'tolerance': .011,
                  'adjustment': 'unadjusted price index; Tencent returns day rather than qfqday'},
}


def source_urls(cutoff, symbol=SYMBOL):
    end = cutoff.replace('-', '')
    contract = CONTRACTS[symbol]
    code = contract['code']
    urls = {
        'tencent': 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh' + code + ',day,2026-01-01,' + cutoff + ',320,qfq',
        'eastmoney': 'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.' + code + '&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=' + str(contract['fqt']) + '&beg=20260101&end=' + end + '&lmt=320',
        'sina': 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh' + code + '&scale=240&ma=no&datalen=320',
    }
    return {p: urls[p] for p in contract.get('providers', PROVIDERS)}


def parse_prices(provider, payload, cutoff, symbol=SYMBOL):
    """Only OHLC; volume/amount units and total returns are not inferred."""
    contract = CONTRACTS[symbol]
    code = contract['code']
    close_only = contract.get('fields') == ['close']
    if provider == 'tencent':
        if payload.get('code') != 0 or 'sh' + code not in payload.get('data', {}):
            raise ValueError('Tencent identity/business error')
        rows = payload['data']['sh' + code][contract['tencent_key']]
    elif provider == 'eastmoney':
        body = payload.get('data') or {}
        if payload.get('rc') != 0 or body.get('code') != code or body.get('market') != 1 or contract['name'] not in body.get('name', ''):
            raise ValueError('Eastmoney identity/business error')
        rows = [row.split(',') for row in body['klines']]
    elif provider == 'sina':
        if not isinstance(payload, list):
            raise ValueError('Sina daily schema error')
        rows = [[r['day'], r.get('open'), r['close'], r.get('high'), r.get('low')] for r in payload]
    else:
        raise ValueError('Undeclared provider')
    if not rows:
        raise ValueError('Empty alternative response')
    result, previous = {}, ''
    for row in rows:
        day = row[0]
        if not isinstance(day, str) or len(day) != 10 or datetime.strptime(day, '%Y-%m-%d').date().isoformat() != day or day <= previous:
            raise ValueError('Duplicate/unsorted/non-session date representation')
        previous = day
        if not '2026-01-01' <= day <= cutoff:
            continue
        if close_only:
            bar = {'close': finite(row[2], True)}
        else:
            bar = dict(zip(('open', 'close', 'high', 'low'), (finite(v, True) for v in row[1:5])))
            if len(bar) != 4:
                raise ValueError('Missing OHLC fields')
            validate_bar({**bar, 'volume': 0})
        result[day] = bar
    expected = [str(d.date()) for d in sessions('XSHG', '2026-01-01', cutoff)]
    if list(result) != expected:
        raise ValueError('Alternative date coverage/freshness differs from exchange calendar')
    return result


def assess_prices(payloads, cutoff, symbol=SYMBOL):
    contract = CONTRACTS[symbol]
    providers = contract.get('providers', PROVIDERS)
    fields = contract.get('fields', ['open', 'high', 'low', 'close'])
    frames = {p: parse_prices(p, payloads[p], cutoff, symbol) for p in providers}
    delta = {p: max(abs(frames['tencent'][d][field] - frames[p][d][field])
                    for d in frames['tencent'] for field in fields)
             for p in providers if p != 'tencent'}
    if any(v > contract['tolerance'] for v in delta.values()):
        raise ValueError('Independent alternative OHLC conflict')
    return {d: {k: row[k] for k in fields} for d, row in frames['tencent'].items()}, {'status': 'QUALIFIED_FOR_RESEARCH_PRICE_ONLY', 'symbol': symbol,
        'start': '2026-01-01', 'last': cutoff, 'rows': len(frames['tencent']),
        'fields_qualified': fields, 'tolerance': contract['tolerance'],
        'max_abs_difference_from_tencent': delta, 'providers': list(providers),
        'adjustment': contract['adjustment'],
        'volume_gate': 'NOT_QUALIFIED', 'amount_gate': 'NOT_QUALIFIED',
        'pre_2026_history_certified': False, 'production_approved': False}


def _valid_head(head, provider, symbol, cutoff, url, config):
    if not head or head['cutoff'] != cutoff:
        return False
    receipt = head['receipt']
    if any(receipt.get(key) != expected for key, expected in
           [('provider', provider), ('symbol', symbol), ('url', url)]):
        return False
    try:
        last = datetime.fromisoformat(receipt['retrieved_at_utc'])
        if last.tzinfo is None:
            return False
        age = (datetime.now(timezone.utc) - last).total_seconds()
        return 0 <= age < config['same_cutoff_remote_refresh_hours'] * 3600
    except (KeyError, TypeError, ValueError):
        return False


def _run_asset(store, config, output, cutoff, run_id, symbol, *, allow_network):
    output = Path(output) / 'alternatives' / symbol.replace('.', '_')
    output.mkdir(parents=True, exist_ok=True)
    requests_made, evidence, payloads, stops = [], {}, {}, {}
    # A fresh attempt starts by revoking previous alternative acceptance.
    store.gate('tencent', symbol, 'BLOCKED', ['CURRENT_ALTERNATIVE_ASSESSMENT_PENDING'], run_id)
    try:
        for provider, url in source_urls(cutoff, symbol).items():
            head = store.head(provider, symbol)
            issue_id = 'ALTERNATIVE_SOURCE:' + provider + ':' + symbol
            prior_failure = store.db.execute('SELECT status FROM known_issues WHERE issue_id=?', (issue_id,)).fetchone()
            fresh = bool(_valid_head(head, provider, symbol, cutoff, url, config) and
                         (not prior_failure or prior_failure[0] != 'FRESH_COLLECTION_FAILED'))
            if not fresh:
                if not allow_network:
                    raise ValueError('No fresh alternative evidence; offline reuse cannot refresh a source')
                receipt = {'url': url, 'retrieved_at_utc': datetime.now(timezone.utc).isoformat(), 'provider': provider, 'symbol': symbol}
                try:
                    store.reserve_request(provider, config['local_hourly_budgets'].get(provider, 10))
                    response = requests.get(url, timeout=25, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'})
                    body = response.content
                    path = output / (provider + '.raw')
                    with path.open('xb') as handle:
                        handle.write(body)
                    receipt.update(status=response.status_code, sha256=sha256(body), bytes=len(body))
                    response.raise_for_status()
                    payload = json.loads(body)
                    # Parse before observing, so a structurally invalid success
                    # cannot become a reusable fresh head.
                    parse_prices(provider, payload, cutoff, symbol)
                    store.observe(provider, symbol, 'prices', cutoff, body, receipt)
                    store.issue(issue_id, 'FRESH_COLLECTION_SUCCEEDED', {'provider': provider, 'symbol': symbol})
                except Exception as exc:
                    receipt['error_type'] = type(exc).__name__
                    stops[provider] = {'error_type': type(exc).__name__}
                    store.issue(issue_id, 'FRESH_COLLECTION_FAILED', {'provider': provider, 'symbol': symbol, 'error_type': type(exc).__name__})
                    raise
                finally:
                    requests_made.append(receipt)
                    (output / (provider + '_receipt.json')).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
                head = store.head(provider, symbol)
            if not _valid_head(head, provider, symbol, cutoff, url, config):
                raise ValueError('Alternative receipt identity or retrieval time mismatch')
            payloads[provider] = head['payload']
            evidence[provider] = {'sha256': head['sha256'], 'cutoff': head['cutoff'], 'receipt': head['receipt']}
        records, asset = assess_prices(payloads, cutoff, symbol)
        asset['evidence'] = evidence
        store.gate('tencent', symbol, 'QUALIFIED_FOR_RESEARCH', [], run_id)
        store.publish('tencent', symbol, cutoff, [{'date': d, **row} for d, row in records.items()],
                      {**{k: asset[k] for k in ['adjustment', 'fields_qualified']}, 'currency': 'CNY',
                       'calendar': 'XSHG', 'source_evidence': evidence, 'start': '2026-01-01'}, run_id)
    except Exception as exc:
        asset = {'status': 'BLOCKED', 'symbol': symbol, 'reason': type(exc).__name__,
                 'fields_qualified': [], 'production_approved': False}
        store.gate('tencent', symbol, 'BLOCKED', ['ALTERNATIVE_VALIDATION_FAILED'], run_id)
    issue = {'symbol': symbol, 'status': asset['status'], 'fields_qualified': asset['fields_qualified']}
    changed = store.issue('ALTERNATIVE:' + symbol, asset['status'], issue)
    report = {'status': asset['status'], 'requests': requests_made, 'provider_stops': stops,
              'assets': [asset], 'original_provider_gate_unchanged': True,
              'new_or_changed_issues': [{'issue_id': 'ALTERNATIVE:' + symbol, 'evidence': issue}] if changed else []}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def validate_configuration(config):
    enabled = config.get('enabled_alternative_sources', [])
    if not enabled:
        if config.get('suba_bond_symbol') == '000012.SH':
            raise ValueError('Replacement bond sources must be enabled')
        return []
    symbols = config.get('alternative_cn_symbols', [SYMBOL])
    if (len(enabled) != len(set(enabled)) or not set(enabled).issubset(PROVIDERS)
            or not symbols or len(symbols) != len(set(symbols)) or not set(symbols).issubset(CONTRACTS)):
        raise ValueError('Alternative sources or assets are outside the reviewed contract')
    required = {p for symbol in symbols for p in CONTRACTS[symbol].get('providers', PROVIDERS)}
    if not required.issubset(enabled):
        raise ValueError('Missing sources required by the asset contract')
    if config.get('suba_bond_symbol') == '000012.SH' and '000012.SH' not in symbols:
        raise ValueError('Replacement bond is absent from the alternative configuration')
    return symbols


def run(store, config, output, cutoff, run_id, *, allow_network):
    symbols = validate_configuration(config)
    if not symbols:
        return {'status': 'NOT_ENABLED', 'requests': [], 'assets': [], 'new_or_changed_issues': []}
    reports = [_run_asset(store, config, output, cutoff, run_id, symbol, allow_network=allow_network) for symbol in symbols]
    statuses = [r['status'] for r in reports]
    return {'status': 'QUALIFIED_FOR_RESEARCH_PRICE_ONLY' if all(s == 'QUALIFIED_FOR_RESEARCH_PRICE_ONLY' for s in statuses)
            else ('PARTIAL_RESEARCH_ALTERNATIVES' if 'QUALIFIED_FOR_RESEARCH_PRICE_ONLY' in statuses else 'BLOCKED'),
            'requests': [q for r in reports for q in r['requests']],
            'assets': [a for r in reports for a in r['assets']],
            'provider_stops': {a['assets'][0]['symbol']: a['provider_stops'] for a in reports if a['provider_stops']},
            'original_provider_gate_unchanged': True,
            'new_or_changed_issues': [q for r in reports for q in r['new_or_changed_issues']]}

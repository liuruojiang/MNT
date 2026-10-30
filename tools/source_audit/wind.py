"""Wind Alice read-only collection and hard interval gates, separate from bots."""
from datetime import datetime, timezone
import copy
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import time

import numpy as np
import pandas as pd

from .transport import decrypt_dpapi
from wind_interval_guard import (WindIntervalConflict, parse_index_kline,
                                parse_csindex_reference, validate_long_short)

SERVERS = {name: 'https://mcp.wind.com.cn/vserver_' + name + '/mcp/' for name in
           ('index_data', 'fund_data', 'stock_data', 'economic_data', 'analytics_data', 'bond_data', 'financial_docs')}
KNOWN_READ_ONLY = {'index_data': {'get_index_kline'}, 'fund_data': {'get_fund_kline'}}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


class WindClient:
    """No secret in argv/URL/receipts; bounded calls, no redirects or stale fallback."""
    def __init__(self, credential_path, run_dir, max_requests=30, dns_override=None, budget_store=None):
        if isinstance(max_requests, bool) or not isinstance(max_requests, int) or max_requests < 1:
            raise ValueError('Invalid request budget')
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.max_requests = max_requests
        self.count = 0
        self.stopped = {}
        self.receipts = []
        self.catalogs = {}
        self.key = decrypt_dpapi(Path(credential_path))
        self.dns_override = str(ipaddress.ip_address(dns_override)) if dns_override else None
        self.budget_store = Path(budget_store) if budget_store else None
        self.global_stopped = False

    def rpc(self, server, method, params=None, label=None):
        if server not in SERVERS or method not in {'initialize', 'tools/list', 'tools/call'}:
            raise ValueError('Only known read-only Wind RPC destinations are allowed')
        if method == 'tools/call':
            name = (params or {}).get('name')
            catalog = self.catalogs.get(server, {})
            allowed = name in KNOWN_READ_ONLY.get(server, set()) or catalog.get(name, {}).get('annotations', {}).get('readOnlyHint') is True
            if not allowed:
                raise ValueError('Tool was not discovered as read-only')
        if self.global_stopped or server in self.stopped:
            raise RuntimeError('Wind server stopped after transport/auth/quota failure')
        if self.count >= self.max_requests:
            raise RuntimeError('Wind request budget exhausted')
        if self.budget_store is not None:
            from .store import Store
            budget = Store(self.budget_store)
            try: budget.reserve_request('wind',self.max_requests)
            finally: budget.close()
        self.count += 1
        request_id = int(time.time() * 1000) * 100 + self.count
        label = re.sub(r'[^a-zA-Z0-9_-]', '_', label or method)
        stem = f'{self.count:03}_{label}'
        payload = {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params or {}}
        receipt = {'provider': 'wind', 'server': server, 'url': SERVERS[server], 'method': method,
                   'request_id': request_id, 'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                   'authenticated': True, 'attempt': self.count, 'transport': 'curl/Windows HTTPS',
                   'dns_override_used': bool(self.dns_override), 'source_mode': 'LIVE_FRESH'}
        if method == 'tools/call':
            receipt['tool'] = params['name']
            receipt['arguments'] = params.get('arguments', {})
        config = [f'url = {json.dumps(SERVERS[server])}', 'request = "POST"',
                  'header = ' + json.dumps('Authorization: Bearer ' + self.key),
                  'header = "Content-Type: application/json"',
                  'header = "Accept: application/json, text/event-stream"',
                  'header = "User-Agent: ReadOnlyDataSourceService/1.0"',
                  # curl's config parser does not decode JSON \uXXXX escapes.
                  # Keep non-ASCII text UTF-8 in the outer config string too.
                  'data = ' + json.dumps(json.dumps(payload, ensure_ascii=False), ensure_ascii=False)]
        timeout_seconds = 90 if method == 'tools/call' and isinstance(params.get('arguments', {}).get('question'), str) else 45
        command = ['curl.exe', '--silent', '--show-error', '--connect-timeout', '10', '--max-time', str(timeout_seconds),
                   '--max-filesize', '20000000', '--config', '-', '--write-out', '\n__HTTP_STATUS__%{http_code}']
        if self.dns_override:
            command += ['--resolve', 'mcp.wind.com.cn:443:' + self.dns_override]
        value = None
        try:
            process = subprocess.run(command, input=('\n'.join(config) + '\n').encode('utf-8'), capture_output=True, timeout=timeout_seconds + 5)
            if process.returncode:
                raise RuntimeError('HTTPS transport failed')
            content, status = process.stdout.rsplit(b'\n__HTTP_STATUS__', 1)
            if len(content) > 20_000_000:
                raise ValueError('Response size limit')
            safe = content.decode('utf-8', errors='replace').replace(self.key, '[REDACTED]').encode('utf-8')
            with (self.run_dir / (stem + '_response.txt')).open('xb') as handle:
                handle.write(safe)
            receipt.update(status=int(status), bytes=len(safe), sha256=hashlib.sha256(safe).hexdigest(), raw_file=stem + '_response.txt')
            if receipt['status'] in {401,403,429}:
                self.global_stopped = True
                self.stopped[server] = {'status': receipt['status']}
            try:
                value = json.loads(safe)
            except json.JSONDecodeError:
                lines = [line[5:].strip() for line in safe.decode().splitlines() if line.startswith('data:')]
                if not lines:
                    raise ValueError('Neither JSON nor JSON-SSE')
                value = json.loads(lines[-1])
            if receipt['status'] != 200:
                self.stopped[server] = {'status': receipt['status']}
                if receipt['status'] in {401,403,429}: self.global_stopped = True
                value = None
            elif value.get('id') != request_id:
                raise ValueError('RPC response ID mismatch')
            if value is not None:
                write_json(self.run_dir / (stem + '_parsed.json'), value)
                receipt['parsed_file'] = stem + '_parsed.json'
                if method == 'tools/list':
                    self.catalogs[server] = {t['name']: t for t in value.get('result', {}).get('tools', [])}
                result=value.get('result',{})
                if result.get('isError') is True:
                    receipt['business_error']=True
                    message=' '.join(str(b.get('text','')) for b in result.get('content',[]) if b.get('type')=='text')
                    quota=result.get('structuredContent',{}).get('code') in {402,'402'} or any(s in message for s in ['积分余额不足','额度不足','insufficient credits'])
                    receipt['failure_class']='ACCOUNT_CREDITS_EXHAUSTED' if quota else 'WIND_BUSINESS_ERROR'
                    self.stopped[server]={'failure_class':receipt['failure_class']}
                    if quota:
                        self.global_stopped=True
                        if self.budget_store is not None:
                            hold=self.budget_store/'provider_holds'/'wind.json'
                            hold.parent.mkdir(parents=True,exist_ok=True)
                            state={'status':'OPEN','provider':'wind','reason':'ACCOUNT_CREDITS_EXHAUSTED',
                                   'observed_at_utc':receipt['retrieved_at_utc'],'evidence_sha256':receipt['sha256'],
                                   'evidence_receipt':str(self.run_dir/(stem+'_receipt.json')),
                                   'recovery':'User restores credits, then explicitly resume and validate fresh data; no automatic paid action'}
                            temp=hold.with_suffix('.tmp')
                            temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
                            temp.replace(hold)
                    value=None
        except Exception as exc:
            receipt['error_type'] = type(exc).__name__
            self.stopped[server] = {'error_type': type(exc).__name__}
            value = None
        self.receipts.append(receipt)
        write_json(self.run_dir / (stem + '_receipt.json'), receipt)
        if value is None:
            raise RuntimeError('Wind request failed; inspect sanitized receipt')
        return value

    def kline(self, code, kind, start, end, aftype='0', label=None):
        if not isinstance(code, str) or not re.fullmatch(r'(?:\d{6}\.(?:SH|SZ|CSI)|H\d{5}\.(?:SH|CSI))', code):
            raise ValueError('Explicit verified-format Wind code required')
        if kind not in {'index', 'fund'} or (kind == 'fund' and aftype not in {'0', '1', '2'}):
            raise ValueError('Unknown asset kind or adjustment basis')
        args = {'windcode': code, 'begin_date': start, 'end_date': end, 'period': '10', 'count': 0}
        if kind == 'fund':
            args['aftype'] = aftype
        return self.rpc(kind + '_data', 'tools/call', {'name': 'get_' + kind + '_kline', 'arguments': args}, label)


def nested_data(payload):
    if payload.get('error') or payload.get('result', {}).get('isError'):
        raise WindIntervalConflict('Wind business error')
    blocks = [b['text'] for b in payload['result']['content'] if b.get('type') == 'text']
    if len(blocks) != 1:
        raise WindIntervalConflict('Ambiguous Wind content')
    value = json.loads(blocks[0])
    if value.get('error') or not isinstance(value.get('data'), dict):
        raise WindIntervalConflict('Missing Wind data')
    return value['data']


def amount_frame(payload, *, kind, start=None, end=None):
    """TURNOVER is money, never a conversion from share volume."""
    data = nested_data(payload)
    names = [c['name'] for c in data['columns']]
    if 'TURNOVER' not in names:
        return None, 'MISSING_AMOUNT_FIELD'
    units = data.get('unit', {})
    declared = [v for k, v in units.items() if 'TURNOVER' in k.upper() or '成交额' in k]
    declared += [c['unit'] for c in data['columns'] if c['name'] == 'TURNOVER' and c.get('unit')]
    if not declared or any(v != '元' for v in declared):
        return None, 'UNCONFIRMED_AMOUNT_CURRENCY_UNIT'
    f = pd.DataFrame(data['rows'], columns=names)
    if start is not None:
        f = f.loc[f['TIME'].str[:10] >= str(pd.Timestamp(start).date())]
    if end is not None:
        f = f.loc[f['TIME'].str[:10] <= str(pd.Timestamp(end).date())]
    if f['TURNOVER'].map(lambda v: isinstance(v, (bool, np.bool_))).any():
        raise WindIntervalConflict('Boolean turnover')
    values = pd.to_numeric(f['TURNOVER'], errors='raise')
    if not np.isfinite(values).all() or (values < 0).any():
        raise WindIntervalConflict('Invalid turnover')
    s = pd.Series(values.to_numpy(), index=pd.to_datetime(f['TIME'].str[:10]), name='amount_yuan')
    if s.index.has_duplicates or not s.index.is_monotonic_increasing:
        raise WindIntervalConflict('Invalid turnover dates')
    return s, 'UNVERIFIED_CONSTITUENT_AGGREGATION' if kind == 'index' else 'DECLARED_CNY_PER_FUND_NOT_INDEPENDENTLY_VALIDATED'


def parse_index_close(payload):
    """Bond leg needs TIME/MATCH only; never invent equity volume or OHLC."""
    data = nested_data(payload)
    names = [c['name'] for c in data['columns']]
    if len(names) != len(set(names)) or not {'TIME', 'MATCH'} <= set(names):
        raise WindIntervalConflict('Missing/duplicate bond close columns')
    frame = pd.DataFrame(data['rows'], columns=names)
    if frame.empty or frame['MATCH'].map(lambda x: isinstance(x, (bool, np.bool_))).any():
        raise WindIntervalConflict('Empty/boolean bond close')
    dates = frame['TIME']
    if not dates.map(lambda x: isinstance(x, str) and re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T00:00:00(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', x) is not None).all():
        raise WindIntervalConflict('Invalid daily bond labels')
    pd.to_datetime(dates, utc=True, errors='raise')
    values = pd.to_numeric(frame['MATCH'], errors='raise')
    out = pd.DataFrame({'close': values.to_numpy()}, index=pd.to_datetime(dates.str[:10], format='%Y-%m-%d'))
    if out.index.has_duplicates or not out.index.is_monotonic_increasing or not np.isfinite(out.close).all() or (out.close <= 0).any():
        raise WindIntervalConflict('Invalid bond close dates/values')
    out.attrs['_response_request_id'] = payload.get('result', {}).get('_meta', {}).get('requestId')
    return out


def audit_bond_close(code, long_payload, short_payload, *, sessions, start, end, calendar_source,
                     independent_calendar=False, reference_payload=None, tail_sessions=5):
    """Return no consumable candidate until every recent independent close exists."""
    report = {'code': code, 'kind': 'index', 'gate': 'BLOCKED', 'required_fields': ['TIME', 'MATCH(close)'],
              'production_approved': False, 'amount_gate': 'NOT_REQUIRED_BY_FORMAL_BOND_LEG', 'field_gaps': [],
              'calendar_source': calendar_source, 'independent_calendar': bool(independent_calendar),
              'requested_start': start, 'required_end': end, 'history_before_start_certified': False,
              'identity': 'Wind H11077.SH / CSI market-data indexCode H11077; 931077 is the detail-page/Referer code only'}
    try:
        if code != 'H11077.SH':
            raise WindIntervalConflict('Close-only path restricted to verified H11077 bond leg')
        s = pd.DatetimeIndex(pd.to_datetime(sessions))
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        if not independent_calendar or s.empty or s.tz is not None or s.hasnans or s.has_duplicates or not s.is_monotonic_increasing or not s.equals(s.normalize()) or s.max() != hi or s.min() < lo:
            raise WindIntervalConflict('Invalid/missing independent bond calendar or cutoff')
        if isinstance(tail_sessions, bool) or not isinstance(tail_sessions, int) or tail_sessions < 1:
            raise WindIntervalConflict('Invalid close-only tail window')
        if long_payload is short_payload or (long_payload.get('id') is not None and long_payload.get('id') == short_payload.get('id')):
            raise WindIntervalConflict('Bond long/short reused the same response identity')
        long, short = parse_index_close(long_payload), parse_index_close(short_payload)
        if long.attrs.get('_response_request_id') and long.attrs.get('_response_request_id') == short.attrs.get('_response_request_id'):
            raise WindIntervalConflict('Bond long/short reused the same response receipt')
        long = long.loc[(long.index >= lo) & (long.index <= hi)]
        recent = s[-tail_sessions:]
        if not long.index.equals(s) or not short.index.equals(recent):
            raise WindIntervalConflict('Bond close dates incomplete or contain extra sessions')
        delta = (long.loc[recent, 'close'] - short.close).abs()
        if (delta > .011).any():
            raise WindIntervalConflict('Bond long/short close conflict')
        report.update(rows=len(long), first=str(s.min().date()), last=str(s.max().date()),
                      close_only_candidate=True, long_short_close_checked=True, long_short_max_abs_difference=float(delta.max()))
        ref = pd.Series(dtype=float)
        if reference_payload is not None:
            if str(reference_payload.get('code')) != '200' or not isinstance(reference_payload.get('data'), list):
                raise WindIntervalConflict('Official bond reference error/schema')
            rows = reference_payload['data']
            if any(r.get('indexCode') != 'H11077' or isinstance(r.get('close'), (bool, np.bool_)) for r in rows):
                raise WindIntervalConflict('Official bond reference identity/boolean close')
            ref = pd.Series([pd.to_numeric(r['close'], errors='raise') for r in rows],
                            index=pd.to_datetime([r['tradeDate'] for r in rows], format='%Y%m%d', errors='raise'), dtype=float)
            if ref.index.has_duplicates or not ref.index.is_monotonic_increasing or not np.isfinite(ref).all() or (ref <= 0).any():
                raise WindIntervalConflict('Invalid official bond reference dates/close')
            ref = ref.loc[(ref.index >= lo) & (ref.index <= hi)]
            if len(ref.index.difference(s)):
                raise WindIntervalConflict('Official bond reference contains unexpected sessions')
        common = long.index.intersection(ref.index)
        ref_delta = (long.loc[common, 'close'] - ref.loc[common]).abs()
        if (ref_delta > .011).any():
            raise WindIntervalConflict('Bond independent close conflict')
        missing = recent.difference(ref.index).strftime('%Y-%m-%d').tolist()
        report['independent_close_validation'] = {'provider': 'csindex', 'market_data_indexCode': 'H11077',
            'available_checked_sessions': len(common), 'max_abs_difference': float(ref_delta.max()) if len(common) else None,
            'required_recent_dates': recent.strftime('%Y-%m-%d').tolist(), 'missing_recent_dates': missing,
            'current_day_present': hi in ref.index, 'tolerance': .011, 'authentication': 'caller responsibility'}
        if missing:
            report.update(gate='PARTIAL_INDEPENDENT_REFERENCE', reason='Official close missing required recent sessions',
                          field_gaps=['INDEPENDENT_CLOSE_MISSING:' + ','.join(missing)])
            return report, None
        report.update(gate='INDEPENDENT_CLOSE_OVERLAP_CHECKED', acceptance_scope='Full requested date coverage and available official closes; recent independent closes complete; research only')
        return report, long.copy(deep=True)
    except Exception as exc:
        report.update(gate='BLOCKED', reason=str(exc)[:400], error_type=type(exc).__name__)
        return report, None


def check_sina_attestation(code, long_payload, short_payload, long_source, short_source, *,
                           attestation_path, sessions, cutoff):
    """Bind current immutable archives and recompute; never masquerade as CSI."""
    result = {'status': 'NOT_APPLICABLE', 'applicable': False, 'provider': 'sina', 'official_CSI': False, 'production_approved': False}
    try:
        attestation = json.loads(Path(attestation_path).read_text(encoding='utf-8'))
        if attestation.get('cutoff') != cutoff:
            result['reason'] = 'Attestation cutoff differs; no independent acceptance for this cutoff'
            return result
        entry = attestation.get('entries', {}).get(code)
        if entry is None:
            return result
        result['applicable'] = True
        for label, source, payload in [('long', long_source, long_payload), ('short', short_source, short_payload)]:
            path = Path(source['parsed_path'])
            if source.get('raw_sha256') != entry[label + '_raw_sha256'] or hashlib.sha256(path.read_bytes()).hexdigest() != entry[label + '_parsed_sha256'] or json.loads(path.read_text(encoding='utf-8')) != payload:
                raise ValueError('Attestation Wind archive binding differs')
        from urllib.parse import urlsplit, parse_qs
        url = urlsplit(entry['reference_url'])
        if url.scheme != 'https' or url.hostname != 'money.finance.sina.com.cn' or url.path != '/quotes_service/api/json_v2.php/CN_MarketData.getKLineData' or parse_qs(url.query).get('symbol') != ['sh' + code.split('.')[0]] or parse_qs(url.query).get('scale') != ['240']:
            raise ValueError('Attestation independent provider/identity differs')
        raw_path = Path(entry['reference_raw_path'])
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != entry['reference_raw_sha256']:
            raise ValueError('Attestation independent raw hash differs')
        raw = pd.DataFrame(json.loads(raw_path.read_text(encoding='utf-8')))
        fields = ['open', 'high', 'low', 'close', 'volume']
        if raw[fields].map(lambda x: isinstance(x, (bool, np.bool_))).any().any():
            raise ValueError('Boolean independent OHLCV')
        raw.index = pd.to_datetime(raw['day'], format='%Y-%m-%d', errors='raise')
        if raw.index.has_duplicates or not raw.index.is_monotonic_increasing:
            raise ValueError('Duplicate/unsorted independent sessions')
        recent = pd.DatetimeIndex(sessions)[-5:]
        ref = raw[fields].apply(pd.to_numeric, errors='raise').loc[recent]
        from wind_interval_guard import _validate
        _validate(ref, recent[0], pd.Timestamp(cutoff), recent, 'Sina independent reference')
        comparisons = {}
        for label, payload in [('long', long_payload), ('short', short_payload)]:
            frame = parse_index_kline(payload)
            values = {}
            for field in fields:
                delta = (frame.loc[recent, field] - ref[field]).abs()
                tolerance = 100 if field == 'volume' else .011
                if not np.isfinite(delta).all() or (delta > tolerance).any():
                    raise ValueError('Sina ' + label + '/' + field + ' conflict')
                values[field] = {'max_abs_difference': float(delta.max()), 'tolerance': tolerance}
            comparisons[label] = values
        result.update(status='THIRD_PARTY_INDEPENDENT_OVERLAP_CHECKED', cutoff=cutoff,
            dates=recent.strftime('%Y-%m-%d').tolist(), comparisons=comparisons,
            bindings=entry, attestation_sha256=hashlib.sha256(Path(attestation_path).read_bytes()).hexdigest(),
            scope='Exact bound raw/parsed responses and cutoff only; original numeric volume retained, no amount certification')
    except Exception as exc:
        result.update(status='FAILED', applicable=True, reason=str(exc)[:400])
    return result


def audit_asset(code, kind, long_payload, short_payload, *, sessions, start, end, calendar_source,
                independent_calendar=False, reference_payload=None, tail_sessions=5, aftype='0'):
    """Return a report and a checked OHLCV copy, or report+None on any failure.

    No partial/failed data are returned for downstream use. A successful
    interval check remains research-only and does not approve an amount field.
    """
    report = {'code': code, 'kind': kind, 'gate': 'BLOCKED', 'production_approved': False,
              'requested_start': start, 'required_end': end, 'adjustment_basis': 'price_index' if kind == 'index' else {'0': 'forward', '1': 'backward', '2': 'unadjusted'}[aftype],
              'calendar_source': calendar_source, 'independent_calendar': bool(independent_calendar),
              'amount_gate': 'BLOCKED', 'field_gaps': [], 'history_before_start_certified': False}
    try:
        s = pd.DatetimeIndex(pd.to_datetime(sessions)).normalize()
        if long_payload is short_payload or (long_payload.get('id') is not None and long_payload.get('id') == short_payload.get('id')):
            raise WindIntervalConflict('Long and short reused the same response identity')
        if not independent_calendar:
            raise WindIntervalConflict('Independent exchange sessions not supplied')
        if len(s) == 0 or s.max() != pd.Timestamp(end):
            raise WindIntervalConflict('Confirmed sessions do not reach requested cutoff')
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        l, r = parse_index_kline(long_payload), parse_index_kline(short_payload)
        l = l.loc[(l.index >= lo) & (l.index <= hi)].copy()
        recent = s[-tail_sessions:]
        r = r.loc[r.index.isin(recent)].copy()
        l.attrs['_requested_windcode'] = r.attrs['_requested_windcode'] = code
        lid = l.attrs.get('_response_request_id')
        if lid and lid == r.attrs.get('_response_request_id') and len(s) > tail_sessions:
            raise WindIntervalConflict('Long/short ranges reused the same Wind response')
        ref = None
        if reference_payload is not None:
            ref = parse_csindex_reference(reference_payload)
            ref = ref.loc[ref.index.isin(recent)].copy()
        accepted = validate_long_short(l, r, start=start, end=end, confirmed_sessions=s,
                                       tail_sessions=tail_sessions, reference=ref)
        report.update(gate='INDEPENDENT_OVERLAP_CHECKED' if ref is not None else 'INTERVAL_COHERENT_ONLY',
                      rows=len(accepted), first=str(accepted.index.min().date()), last=str(accepted.index.max().date()),
                      validation=accepted.attrs['wind_interval_validation'])
        long_amount, amount_note = amount_frame(long_payload, kind=kind, start=start, end=end)
        short_amount, _ = amount_frame(short_payload, kind=kind, start=str(recent[0].date()), end=end)
        report['amount_basis'] = amount_note
        if long_amount is None or short_amount is None:
            report['field_gaps'].append(amount_note)
        else:
            common = recent.intersection(long_amount.index).intersection(short_amount.index)
            if len(common) != len(recent) or not np.isclose(long_amount.loc[common], short_amount.loc[common], atol=1.0, rtol=0).all():
                raise WindIntervalConflict('Long/short turnover conflict or missing amount days')
            report['amount_range_consistent'] = True
            report['field_gaps'].append(amount_note)
        # The observed Wind schema does not declare VOLUME units explicitly.
        data = nested_data(long_payload)
        declared_volume = any('VOLUME' in str(k).upper() for k in data.get('unit', {})) or any(c['name'] == 'VOLUME' and c.get('unit') for c in data['columns'])
        if not declared_volume:
            report['field_gaps'].append('VOLUME_UNIT_NOT_EXPLICITLY_DECLARED')
        return report, accepted
    except Exception as exc:
        report.update(gate='BLOCKED', error_type=type(exc).__name__, reason=str(exc)[:400])
        return report, None


def archive_payload(path):
    """Require its original successful receipt and original raw-response hash."""
    path = Path(path)
    if not path.name.endswith('_parsed.json'):
        raise ValueError('Expected parsed Wind archive')
    prefix = path.name[:-len('_parsed.json')]
    receipt_path = path.with_name(prefix + '_receipt.json')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('status') != 200 or receipt.get('error_type'):
        raise WindIntervalConflict('Archived request failed')
    raw_path = path.with_name(prefix + '_response.txt')
    raw = raw_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt.get('sha256'):
        raise WindIntervalConflict('Archived raw-response hash mismatch')
    parsed = json.loads(path.read_text(encoding='utf-8'))
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        data_lines = [line[5:].strip() for line in raw.decode('utf-8').splitlines() if line.startswith('data:')]
        if not data_lines: raise WindIntervalConflict('Archived raw response cannot be decoded')
        decoded = json.loads(data_lines[-1])
    if parsed != decoded:
        raise WindIntervalConflict('Parsed archive differs from hashed original response')
    return parsed, {'source_mode': 'ARCHIVE_REUSED', 'parsed_path': str(path),
               'receipt_path': str(receipt_path), 'raw_sha256': receipt['sha256'], 'retrieved_at_utc': receipt.get('retrieved_at_utc')}


def validate_option_chain_result(payload, *, product, underlying_code, date, expiry_month):
    """Reject a structured but wrong product/date, instead of trusting HTTP 200.

    Schema is the actually observed analytics_data table, not an invented
    futures/options endpoint. No usable rows are exposed on a mismatch.
    """
    result = {'status': 'BLOCKED', 'requested_product': product, 'requested_underlying': underlying_code,
              'requested_date': date, 'requested_expiry_month': expiry_month, 'production_approved': False}
    try:
        if payload.get('error') or payload.get('result', {}).get('isError'):
            raise WindIntervalConflict('Wind RPC/business error')
        blocks = [b['text'] for b in payload['result']['content'] if b.get('type') == 'text']
        if len(blocks) != 1: raise WindIntervalConflict('Ambiguous structured response')
        data = json.loads(blocks[0])
        if data.get('error'): raise WindIntervalConflict('Wind data error')
        tables = data['data']['data']
        if len(tables) != 1: raise WindIntervalConflict('Ambiguous option table')
        table = tables[0]
        names = [c['name'] for c in table['columns']]
        if len(names) != len(set(names)): raise WindIntervalConflict('Duplicate option columns')
        frame = pd.DataFrame(table['rows'], columns=names)
        if frame.empty: raise WindIntervalConflict('Empty option table')
        issues = []
        for required in ['Wind代码', '标的WIND代码', '日期', '最后交易日期', '行权价格', '收盘价']:
            if required not in frame: issues.append('MISSING_FIELD:' + required)
        if issues: raise WindIntervalConflict('; '.join(issues))
        codes = frame['Wind代码'].astype(str)
        if not codes.str.startswith(product).all(): issues.append('CONTRACT_PRODUCT_MISMATCH')
        if not frame['标的WIND代码'].astype(str).eq(underlying_code).all(): issues.append('UNDERLYING_MISMATCH')
        if not frame['日期'].astype(str).str.replace('-', '').eq(date.replace('-', '')).all(): issues.append('REQUIRED_DATE_MISMATCH')
        if not frame['最后交易日期'].astype(str).str.startswith(expiry_month).all(): issues.append('EXPIRY_MONTH_MISMATCH')
        if not any('乘数' in col or '合约单位' in col for col in names): issues.append('MISSING_CONTRACT_MULTIPLIER')
        if not any('买一' in col or 'bid' in col.lower() for col in names): issues.append('MISSING_BID')
        if not any('卖一' in col or 'ask' in col.lower() for col in names): issues.append('MISSING_ASK')
        result.update(issues=issues, observed_rows=len(frame), observed_codes=codes.head(3).tolist(),
                      observed_dates=sorted(frame['日期'].astype(str).unique().tolist()), observed_fields=names)
        if issues:
            return result, None
        return {**result, 'status': 'SCHEMA_IDENTITY_DATE_CHECKED_NOT_MARKET_CERTIFIED'}, frame
    except Exception as exc:
        result.update(error_type=type(exc).__name__, reason=str(exc)[:300])
        return result, None


def merge_incremental(long_payload, short_payload, *, code, kind, sessions, start, end, parent_hashes):
    """Derive an appended research dataset only after unchanged overlap.

    Provider responses are untouched. New rows have only the short-response
    origin; this is not an independent second quote for the new trading day.
    Any revised overlap/schema/unit mismatch requires full refresh instead.
    """
    old_data, new_data = nested_data(long_payload), nested_data(short_payload)
    old_names = [c['name'] for c in old_data['columns']]
    new_names = [c['name'] for c in new_data['columns']]
    if old_names != new_names or old_data.get('unit') != new_data.get('unit'):
        raise WindIntervalConflict('needs_full_refresh: schema or units changed')
    old = {str(row[old_names.index('TIME')])[:10]: row for row in old_data['rows']}
    new = {str(row[new_names.index('TIME')])[:10]: row for row in new_data['rows']}
    if not old or not new:
        raise WindIntervalConflict('needs_full_refresh: no usable rows')
    if len(old) != len(old_data['rows']) or len(new) != len(new_data['rows']):
        raise WindIntervalConflict('needs_full_refresh: duplicate source dates')
    if max(old) >= end:
        return long_payload, None
    overlap = sorted(old.keys() & new.keys())
    if len(overlap) < 2 or max(old) not in overlap:
        raise WindIntervalConflict('needs_full_refresh: insufficient connected overlap')
    expected = pd.DatetimeIndex(sessions)
    missing_new = {str(day.date()) for day in expected if str(day.date()) > max(old)} - new.keys()
    if missing_new:
        raise WindIntervalConflict('needs_full_refresh: missing incremental sessions')
    for day in overlap:
        for field in ['OPEN', 'HIGH', 'LOW', 'MATCH', 'VOLUME', 'TURNOVER']:
            if field not in old_names:
                continue
            j = old_names.index(field)
            try:
                a, b = float(old[day][j]), float(new[day][j])
            except (TypeError, ValueError) as exc:
                raise WindIntervalConflict('needs_full_refresh: invalid overlap values') from exc
            tolerance = 100.0 if field == 'VOLUME' else (1.0 if field == 'TURNOVER' else (0.0011 if kind == 'fund' else 0.011))
            if not np.isfinite([a, b]).all() or abs(a - b) > tolerance:
                raise WindIntervalConflict('needs_full_refresh: revised overlap ' + day + ' ' + field)
    out = copy.deepcopy(long_payload)
    combined = {**old, **{day: row for day, row in new.items() if day > max(old)}}
    body = nested_data(out)
    body['rows'] = [combined[day] for day in sorted(combined)]
    # nested_data decodes a copy, so explicitly write the derived content.
    nested = json.loads(out['result']['content'][0]['text'])
    nested['data'] = body
    out['result']['content'][0]['text'] = json.dumps(nested, ensure_ascii=False)
    lineage = {'mode': 'DERIVED_ARCHIVE_PLUS_FRESH_TAIL', 'code': code, 'requested_end': end,
               'parent_hashes': parent_hashes, 'overlap_dates_checked': overlap,
               'added_dates': sorted(day for day in new if day > max(old)),
               'new_rows_second_independent_quote': False, 'production_approved': False}
    out['_derived_dataset'] = lineage
    return out, lineage

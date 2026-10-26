"""Read-only Wind Alice audit; reuses archives and never registers a production feed."""
import argparse
from datetime import datetime, timezone
import html
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import uuid4

import pandas as pd

from source_audit.wind import WindClient, audit_asset, archive_payload, write_json, merge_incremental, nested_data

REPO = Path(__file__).resolve().parents[1]
ASSETS = [
    {'code': '000852.SH', 'kind': 'index', 'archive': 'zz1000_full_kline', 'short': 'zz1000_recent_conflict_check', 'requires_amount': False},
    {'code': '000905.SH', 'kind': 'index', 'archive': 'zz500_full_kline', 'requires_amount': False},
    {'code': '399006.SZ', 'kind': 'index', 'archive': 'cyb_code_full', 'requires_amount': True,
     'known_amount_conflict': 'Archived 2018-12-10..20 TURNOVER conflicts with independent CNI; statistical scope unresolved'},
    {'code': '000688.SH', 'kind': 'index', 'archive': 'kcb50_full_kline', 'requires_amount': False},
    {'code': '000300.SH', 'kind': 'index', 'archive': 'hs300_full_kline', 'requires_amount': False},
    {'code': '000016.SH', 'kind': 'index', 'archive': 'sse50_chunk_b', 'requires_amount': True},
    {'code': '932000.CSI', 'kind': 'index', 'archive': 'zz2000_amount_recent', 'requires_amount': True},
    {'code': '930955.CSI', 'kind': 'index', 'archive': 'lowvol_dividend_recent', 'requires_amount': False,
     'known_interval_quarantine': 'Known 2026-10-23 range-dependent OHLC/amount conflict: a new agreeing Wind probe alone cannot certify correction; independent resolution required'},
    {'code': 'H11077.SH', 'kind': 'index', 'archive': 'bond_H11077_SH_verified_code', 'requires_amount': False,
     'unsupported_reason': 'Required recent close is available; earlier coverage and H11077/931077 formal identity equivalence remain uncertified. Equity volume is not required by this bond leg.'},
    {'code': '159915.SZ', 'kind': 'fund', 'archive': '159915_SZ_aftype0'},
    {'code': '159941.SZ', 'kind': 'fund', 'archive': '159941_SZ_aftype0'},
    {'code': '513030.SH', 'kind': 'fund', 'archive': 'germany_chunk_b'},
    {'code': '513520.SH', 'kind': 'fund', 'archive': '513520_SH_aftype0'},
    {'code': '159985.SZ', 'kind': 'fund', 'archive': '159985_SZ_aftype0'},
    {'code': '518880.SH', 'kind': 'fund', 'archive': '518880_SH_aftype0'},
]


def load_calendar(path, start, end):
    if path is None:
        return [], 'NOT_SUPPLIED', False
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    dates = value.get('sessions') or value.get('dates') or []
    ix = pd.DatetimeIndex(pd.to_datetime(dates))
    if ix.hasnans or ix.has_duplicates or not ix.is_monotonic_increasing or ix.tz is not None:
        raise ValueError('Invalid exchange calendar')
    candidates = [value.get(k) for k in ['source_url', 'source', 'sources', 'official_source']]
    def strings(x):
        if isinstance(x, str): yield x
        elif isinstance(x, dict):
            for item in x.values(): yield from strings(item)
        elif isinstance(x, list):
            for item in x: yield from strings(item)
    urls = [s for x in candidates for s in strings(x) if s.startswith('https://')]
    authoritative = any(urlsplit(u).hostname == 'www.sse.com.cn' for u in urls)
    if not authoritative:
        raise ValueError('Calendar must cite the official SSE exchange source')
    # Do not claim that the 2026 SSE holiday page certifies earlier history.
    if pd.Timestamp(start).year != 2026 or pd.Timestamp(end).year != 2026:
        raise ValueError('This verified CN calendar scope is limited to 2026')
    ix = ix[(ix >= pd.Timestamp(start)) & (ix <= pd.Timestamp(end))]
    return ix, '; '.join(urls), True


def reference_for(directory, code):
    if not directory:
        return None
    for name in [code.split('.')[0] + '.json', 'csi_' + code.split('.')[0] + '_full.json']:
        p = directory / name
        if p.exists(): return json.loads(p.read_text(encoding='utf-8'))
    return None


def reused_short(directory, cfg, end, begin):
    candidates = []
    for path in directory.glob('*_receipt.json'):
        value = json.loads(path.read_text(encoding='utf-8'))
        args = value.get('arguments', {})
        if args.get('windcode') == cfg['code'] and args.get('begin_date') == begin and args.get('end_date') == end:
            candidates.append((value.get('retrieved_at_utc', ''), path))
    if not candidates:
        raise ValueError('No independent short-window attempt matches the requested code/dates')
    receipt = max(candidates, key=lambda r: r[0])[1]
    # Selecting the latest attempt includes failed attempts; never silently
    # pick an earlier successful response after a newer failure.
    parsed = receipt.with_name(receipt.name[:-len('_receipt.json')] + '_parsed.json')
    return archive_payload(parsed)


def load_index(path, kind):
    if path is None or not path.exists(): return {'schema': 1, 'kind': kind, 'entries': {}}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 1 or data.get('kind') != kind or not isinstance(data.get('entries'), dict):
        raise ValueError('Unsupported Wind archive index')
    return data


def persist_index(path, data):
    if path is None: return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    write_json(temporary, data)
    temporary.replace(path)


def live_provenance(client):
    receipt = client.receipts[-1]
    return {'source_mode': 'LIVE_FRESH', 'parsed_path': str(client.run_dir / receipt['parsed_file']),
            'receipt_path': str(client.run_dir / receipt['parsed_file'].replace('_parsed.json', '_receipt.json')),
            'raw_sha256': receipt['sha256'], 'retrieved_at_utc': receipt['retrieved_at_utc']}


def pin_response(provenance, state_root, code):
    if state_root is None: return provenance
    parsed = Path(provenance['parsed_path']).resolve()
    state_root = state_root.resolve()
    if parsed.is_relative_to(state_root): return provenance
    destination = state_root / 'wind_response_archive' / code.replace('.', '_') / provenance['raw_sha256'][:20]
    destination.mkdir(parents=True, exist_ok=True)
    prefix = parsed.name[:-len('_parsed.json')]
    for suffix in ['_parsed.json', '_receipt.json', '_response.txt']:
        source = parsed.with_name(prefix + suffix)
        target = destination / source.name
        content = source.read_bytes()
        if target.exists():
            if target.read_bytes() != content: raise ValueError('Immutable response archive collision')
        else:
            with target.open('xb') as handle: handle.write(content)
    return {**provenance, 'parsed_path': str(destination / parsed.name),
            'receipt_path': str(destination / (prefix + '_receipt.json')), 'original_archive_path': str(parsed)}


def load_long_record(record):
    if record.get('derived_path'):
        path = Path(record['derived_path'])
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != record.get('derived_sha256'):
            raise ValueError('Derived long dataset hash mismatch')
        value = json.loads(body)
        if not value.get('_derived_dataset'):
            raise ValueError('Derived lineage missing')
        return value, {'source_mode': 'DERIVED_REUSED', 'derived_path': str(path),
                       'derived_sha256': record['derived_sha256'], 'lineage': value['_derived_dataset']}
    return archive_payload(Path(record['parsed_path']))


def discover(client):
    result = {}
    for server in ['index_data', 'fund_data', 'stock_data', 'analytics_data']:
        try:
            payload = client.rpc(server, 'tools/list', {}, server + '_tools')
            tools = payload.get('result', {}).get('tools', [])
            result[server] = {'status': 'CATALOG_DISCOVERED_NOT_ENTITLEMENT_CERTIFIED',
                              'tools': [{'name': t.get('name'), 'description': t.get('description'),
                                         'inputSchema': t.get('inputSchema'), 'annotations': t.get('annotations')} for t in tools]}
        except Exception as exc:
            result[server] = {'status': 'BLOCKED', 'error_type': type(exc).__name__}
    result['scope_limitations'] = {
        'PIT_security_master_ST_delisting_float_shares': 'NOT_DATA_ENTITLEMENT_CERTIFIED',
        'futures_contract_settlement_OI_expiry': 'NO_VERIFIED_FUTURES_API_PATH',
        'options_chain_strike_expiry_multiplier': 'NO_VERIFIED_OPTIONS_API_PATH',
        'note': 'Public marketing/skill catalog and tools/list visibility do not prove historical point-in-time field access.'}
    return result


def run(args):
    output = args.output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8])
    output.mkdir(parents=True)
    sessions, source, independent = load_calendar(args.sessions, args.start, args.cutoff)
    selected = {c for c in args.symbols.split(',') if c} if args.symbols else None
    assets = [a for a in ASSETS if selected is None or a['code'] in selected]
    if selected and selected - {a['code'] for a in assets}:
        raise ValueError('Unrecognized asset; extend explicit requirements before collecting')
    client = None
    def get_client():
        nonlocal client
        if args.credential is None:
            raise ValueError('Live requests require an encrypted credential path')
        if client is None:
            client = WindClient(args.credential, output / 'responses', args.max_requests, args.dns_override,
                                budget_store=getattr(args,'budget_store',None))
        return client
    short_index = load_index(args.short_index, 'short')
    long_index = load_index(args.long_index, 'long')
    if args.mode == 'discover':
        catalog = discover(get_client())
        write_json(output / 'capabilities.json', catalog)
        write_json(output / 'manifest.json', {'mode': args.mode, 'receipts': client.receipts, 'production_changed': False})
        print(json.dumps({'output': str(output), 'mode': args.mode, 'requests': client.count, 'production_changed': False}, ensure_ascii=False))
        return 2 if any(v.get('status') == 'BLOCKED' for v in catalog.values() if isinstance(v, dict)) else 0
    results, provenance = [], []
    for cfg in assets:
        code = cfg['code']
        try:
            if cfg.get('unsupported_reason'):
                raise ValueError(cfg['unsupported_reason'])
            if args.mode == 'live':
                long = get_client().kline(code, cfg['kind'], args.start, args.cutoff, label=code + '_long')
                long_source = live_provenance(client)
            elif code in long_index['entries']:
                long, long_source = load_long_record(long_index['entries'][code])
            else:
                if not args.offline_archive:
                    raise ValueError('An explicit archive is required')
                long, long_source = archive_payload(args.offline_archive / (cfg['archive'] + '_parsed.json'))
            if args.long_index and long_source.get('parsed_path'):
                long_source = pin_response(long_source, args.long_index.parent, code)
            if not len(sessions): raise ValueError('Independent exchange sessions required before short-window collection')
            short_start = str(sessions[-args.tail_sessions:].min().date())
            record = short_index['entries'].get(code)
            reused = False
            if args.mode != 'live' and record and record.get('cutoff') == args.cutoff and record.get('short_start') == short_start and record.get('kind') == cfg['kind']:
                short, short_source = archive_payload(Path(record['parsed_path']))
                reused = True
            elif args.mode != 'live' and args.short_archive:
                short, short_source = reused_short(args.short_archive, cfg, args.cutoff, short_start)
                reused = True
            elif args.mode != 'live' and cfg.get('short') and args.offline_archive:
                short, short_source = archive_payload(args.offline_archive / (cfg['short'] + '_parsed.json'))
                rows = nested_data(short)['rows']
                if min(r[0][:10] for r in rows) != short_start or max(r[0][:10] for r in rows) != args.cutoff:
                    if args.mode != 'tail': raise ValueError('Archived short window does not match requested cutoff')
                    short = get_client().kline(code, cfg['kind'], short_start, args.cutoff, label=code + '_short')
                    short_source = live_provenance(client)
                else: reused = True
            elif args.mode in {'live', 'tail'}:
                short = get_client().kline(code, cfg['kind'], short_start, args.cutoff, label=code + '_short')
                short_source = live_provenance(client)
            else:
                raise ValueError('Independent short-window response not yet collected; long response cannot verify itself')
            if args.short_index:
                short_source = pin_response(short_source, args.short_index.parent, code)
            short_index['entries'][code] = {'code': code, 'kind': cfg['kind'], 'cutoff': args.cutoff,
                                            'short_start': short_start, 'parsed_path': short_source['parsed_path'],
                                            'raw_sha256': short_source['raw_sha256'], 'retrieved_at_utc': short_source.get('retrieved_at_utc')}
            persist_index(args.short_index, short_index)
            parent_hashes = {'long': long_source.get('raw_sha256') or long_source.get('derived_sha256'), 'short': short_source['raw_sha256']}
            long, lineage = merge_incremental(long, short, code=code, kind=cfg['kind'], sessions=sessions,
                                              start=args.start, end=args.cutoff, parent_hashes=parent_hashes)
            derived_path = None
            if lineage:
                derived_path = output / (code.replace('.', '_') + '_derived_long.json')
                write_json(derived_path, long)
            result, checked = audit_asset(code, cfg['kind'], long, short, sessions=sessions, start=args.start, end=args.cutoff,
                                           calendar_source=source, independent_calendar=independent,
                                           reference_payload=reference_for(args.reference_dir, code), tail_sessions=args.tail_sessions)
            result.update(long_source=long_source, short_source=short_source, reused_completed_short=reused,
                          derivation=lineage, needs_full_refresh=checked is None)
            if (lineage or long_source.get('derived_path')) and checked is not None:
                result['gate'] = 'INCREMENTAL_OVERLAP_CHECKED'
                result['new_rows_second_independent_quote'] = False
            if cfg.get('known_amount_conflict'):
                result['amount_gate']='BLOCKED'
                result['known_independent_amount_conflict']=cfg['known_amount_conflict']
                result.setdefault('field_gaps',[]).append('KNOWN_OFFICIAL_AMOUNT_CONFLICT')
            if cfg.get('known_interval_quarantine') and checked is not None:
                result['observed_interval_gate']=result['gate']
                result.update(gate='BLOCKED',reason=cfg['known_interval_quarantine'],known_quarantine=True)
                checked=None
            if args.mode == 'tail':
                result['acceptance_scope'] = 'Archived long range versus fresh short probe; not a newly downloaded full history'
            if checked is not None:
                # Named as research data to prevent accidental production promotion.
                checked.to_csv(output / (code.replace('.', '_') + '_research_only_ohlcv.csv'), index_label='date', encoding='utf-8-sig')
                if derived_path:
                    if args.long_index:
                        stable = args.long_index.parent / 'wind_derived' / code.replace('.', '_') / (hashlib.sha256(derived_path.read_bytes()).hexdigest() + '.json')
                        stable.parent.mkdir(parents=True, exist_ok=True)
                        if not stable.exists():
                            with stable.open('xb') as handle: handle.write(derived_path.read_bytes())
                        elif stable.read_bytes() != derived_path.read_bytes():
                            raise ValueError('Immutable derived dataset collision')
                        derived_path = stable
                    long_index['entries'][code] = {'code': code, 'kind': cfg['kind'], 'cutoff': args.cutoff,
                        'derived_path': str(derived_path), 'derived_sha256': hashlib.sha256(derived_path.read_bytes()).hexdigest(), 'parents': parent_hashes}
                elif long_source.get('derived_path'):
                    pass  # Retain the existing verified derived record.
                else:
                    long_index['entries'][code] = {'code': code, 'kind': cfg['kind'], 'cutoff': args.cutoff, 'parsed_path': long_source['parsed_path']}
                persist_index(args.long_index, long_index)
        except Exception as exc:
            result = {'code': code, 'kind': cfg['kind'], 'gate': 'BLOCKED', 'reason': str(exc)[:400],
                      'error_type': type(exc).__name__, 'production_approved': False, 'amount_gate': 'BLOCKED',
                      'needs_full_refresh': 'needs_full_refresh:' in str(exc)}
        results.append(result)
        print(json.dumps({'code': code, 'gate': result['gate'], 'amount_gate': result['amount_gate']}, ensure_ascii=False), flush=True)
    report = {'mode': args.mode, 'status': 'REVIEW_REQUIRED', 'cutoff': args.cutoff, 'start': args.start,
              'assets': results, 'production_approved': False, 'production_changed': False,
              'calendar': {'source': source, 'independent': independent, 'sessions': len(sessions)},
              'unvalidated_requirements': ['Historical pre-2026 date/value certification', 'Index constituent turnover definition',
                                           'PIT/ST/delisting/share capital historical rights', 'Futures/options contract field rights'],
              'requests': client.count if client else 0}
    report['provider_stops']=client.stopped if client else {}
    write_json(output / 'report.json', report)
    write_json(output / 'manifest.json', {'mode': args.mode, 'receipts': client.receipts if client else [],
                                         'archives_reused_explicitly': args.mode != 'live', 'production_changed': False})
    rows = ''.join('<tr>' + ''.join('<td>' + html.escape(str(v)) + '</td>' for v in [r['code'], r['kind'], r['gate'], r['amount_gate'], r.get('reason') or ', '.join(r.get('field_gaps', []))]) + '</tr>' for r in results)
    (output / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>万得 A 股只读核验</title><style>body{font:16px system-ui;margin:30px}td,th{border:1px solid #ccd;padding:8px}table{border-collapse:collapse}</style><h1>万得 A 股只读核验</h1><p>不改生产；未验证的成交额和历史字段保持阻断。长短一致仅是区间一致性，不是全历史正确性证明。</p><table><tr><th>代码</th><th>类型</th><th>价格区间检查</th><th>成交额检查</th><th>说明</th></tr>' + rows + '</table>', encoding='utf-8')
    print(json.dumps({'output': str(output), 'status': report['status'], 'assets': len(results), 'blocked': sum(r['gate'] == 'BLOCKED' for r in results), 'production_changed': False}, ensure_ascii=False))
    return 2 if any(r['gate'] == 'BLOCKED' or r.get('field_gaps') for r in results) else 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--credential', type=Path)
    p.add_argument('--output', type=Path, default=REPO / 'data/cn_source_audit')
    p.add_argument('--offline-archive', type=Path)
    p.add_argument('--short-archive', type=Path, help='Explicit earlier short-probe response directory; original retrieval dates retained')
    p.add_argument('--short-index', type=Path, help='Persistent code/cutoff index; reuses completed probes without another request')
    p.add_argument('--long-index', type=Path, help='Persistent original/derived long datasets, each with source lineage')
    p.add_argument('--cutoff', required=True)
    p.add_argument('--start', default='2026-01-01')
    p.add_argument('--symbols', default='')
    p.add_argument('--sessions', type=Path)
    p.add_argument('--reference-dir', type=Path)
    p.add_argument('--max-requests', type=int, default=30)
    p.add_argument('--budget-store', type=Path, help='Optional persistent shared hourly request budget')
    p.add_argument('--tail-sessions', type=int, default=5)
    p.add_argument('--mode', choices=['archive', 'live', 'tail', 'discover'], default='archive')
    p.add_argument('--dns-override', help='Explicit diagnostic address only; default uses normal DNS and TLS verification')
    args = p.parse_args()
    try:
        return run(args)
    except Exception as exc:
        print(json.dumps({'status': 'FAILED', 'error_type': type(exc).__name__, 'reason': str(exc)[:250], 'production_changed': False}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

"""Frozen real responses and explicit mutations, never a live-source certificate."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from source_audit import alternative_sources as alt
from source_audit.independent_cash import load_cases
from source_audit.store import Store, DataNotAccepted
from source_audit.transport import sha256

FROZEN = ROOT / 'research/data_quality/20261103_alternative_sources'
CUTOFF = '2026-11-02'


def payloads():
    return {p: json.loads((FROZEN / ('gold_' + p + '.raw')).read_bytes()) for p in alt.PROVIDERS}


def seeded_store(tmp_path, *, hours_old=0):
    store = Store(tmp_path / 'store')
    for provider, payload in payloads().items():
        body = json.dumps(payload).encode()
        store.observe(provider, alt.SYMBOL, 'prices', CUTOFF, body, {
            'status': 200, 'sha256': sha256(body),
            'provider': provider, 'symbol': alt.SYMBOL,
            'url': alt.source_urls(CUTOFF, alt.SYMBOL)[provider],
            'retrieved_at_utc': (datetime.now(timezone.utc) - timedelta(hours=hours_old)).isoformat()})
    return store


CONFIG = {'enabled_alternative_sources': list(alt.PROVIDERS),
          'same_cutoff_remote_refresh_hours': 24, 'local_hourly_budgets': {p: 10 for p in alt.PROVIDERS}}


def test_real_three_source_prices_have_full_session_coverage_and_no_volume_acceptance():
    records, result = alt.assess_prices(payloads(), CUTOFF)
    assert len(records) == 199 and result['last'] == CUTOFF
    assert result['max_abs_difference_from_tencent'] == {'eastmoney': 0, 'sina': 0}
    assert result['fields_qualified'] == ['open', 'high', 'low', 'close']
    assert result['volume_gate'] == result['amount_gate'] == 'NOT_QUALIFIED'
    assert result['production_approved'] is False


def test_index_contract_uses_unadjusted_day_and_existing_rounding_tolerance():
    stems = {'tencent': 'zz500_tencent_qfq', 'eastmoney': 'zz500_eastmoney', 'sina': 'zz500_sina'}
    values = {p: json.loads((FROZEN / (s + '.raw')).read_bytes()) for p, s in stems.items()}
    rows, report = alt.assess_prices(values, CUTOFF, '000905.SH')
    assert len(rows) == 199 and report['tolerance'] == .011
    assert report['max_abs_difference_from_tencent']['eastmoney'] <= .011
    assert 'unadjusted price index' in report['adjustment']
    assert 'fqt=0' in alt.source_urls(CUTOFF, '000905.SH')['eastmoney']


def test_multiple_assets_publish_with_explicit_declared_aliases_and_isolate_failure(tmp_path, monkeypatch):
    from source_audit import adapters
    from source_audit.adapters import read_asset
    # Freeze the declared field contract locally. A unit test must exercise
    # hash checking without depending on another active strategy workspace.
    contract = copy.deepcopy(next(p for p in adapters.requirements()['projects']
                                  if p['project_id'] == 'cn_six_indices_v13'))
    entry = tmp_path / 'frozen_entrypoint.py'
    body = b'# explicit isolated source-contract fixture\n'
    entry.write_bytes(body)
    contract['entrypoints'] = [{'path': str(entry), 'sha256_lf': sha256(body)}]
    contract['runtime_dependencies'] = []
    monkeypatch.setattr(adapters, 'requirements', lambda: {'projects': [contract]})
    store = seeded_store(tmp_path)
    try:
        stems = {'tencent': 'zz500_tencent_qfq', 'eastmoney': 'zz500_eastmoney', 'sina': 'zz500_sina'}
        for provider, stem in stems.items():
            body = (FROZEN / (stem + '.raw')).read_bytes()
            store.observe(provider, '000905.SH', 'prices', CUTOFF, body, {'status': 200, 'sha256': sha256(body),
                'provider': provider, 'symbol': '000905.SH',
                'url': alt.source_urls(CUTOFF, '000905.SH')[provider],
                'retrieved_at_utc': datetime.now(timezone.utc).isoformat()})
        cfg = {**CONFIG, 'alternative_cn_symbols': ['518880.SH', '000905.SH']}
        report = alt.run(store, cfg, tmp_path / 'both', CUTOFF, 'both', allow_network=False)
        assert report['status'] == 'QUALIFIED_FOR_RESEARCH_PRICE_ONLY' and len(report['assets']) == 2
        assert len(read_asset(store, 'cn_six_indices_v13', 'tencent', '000905.SH', CUTOFF, fields=['close'])['records']) == 199
        entry.write_bytes(body + b'# changed after review\n')
        with pytest.raises(DataNotAccepted, match='entrypoint changed'):
            read_asset(store, 'cn_six_indices_v13', 'tencent', '000905.SH', CUTOFF, fields=['close'])
        entry.write_bytes(body)
        old = store.head('eastmoney', '000905.SH'); wrong = copy.deepcopy(old['payload']); wrong['data']['code'] = '000906'
        body = json.dumps(wrong).encode()
        store.observe('eastmoney', '000905.SH', 'prices', CUTOFF, body, {
            'provider': 'eastmoney', 'symbol': '000905.SH',
            'url': alt.source_urls(CUTOFF, '000905.SH')['eastmoney'],
            'status': 200, 'sha256': sha256(body), 'retrieved_at_utc': datetime.now(timezone.utc).isoformat()})
        again = alt.run(store, cfg, tmp_path / 'partial', CUTOFF, 'partial', allow_network=False)
        assert again['status'] == 'PARTIAL_RESEARCH_ALTERNATIVES'
        assert store.accepted('tencent', '518880.SH', CUTOFF)['run_id'] == 'partial'
        with pytest.raises(DataNotAccepted):
            store.accepted('tencent', '000905.SH', CUTOFF)
    finally:
        store.close()


@pytest.mark.parametrize('corruption', ['wrong_symbol', 'missing_day', 'duplicate', 'price_conflict', 'boolean'])
def test_mutated_third_party_success_does_not_qualify(corruption):
    values = copy.deepcopy(payloads())
    data = values['eastmoney']['data']
    if corruption == 'wrong_symbol':
        data['code'] = '518881'
    elif corruption == 'missing_day':
        data['klines'].pop()
    elif corruption == 'duplicate':
        data['klines'].append(data['klines'][-1])
    elif corruption == 'price_conflict':
        row = data['klines'][-1].split(','); row[2] = '7.944'; data['klines'][-1] = ','.join(row)
    else:
        values['tencent']['data']['sh518880']['qfqday'][-1][1] = True
    with pytest.raises(ValueError):
        alt.assess_prices(values, CUTOFF)


def test_exact_cutoff_reuse_publishes_explicit_provider_and_only_price_fields(tmp_path):
    store = seeded_store(tmp_path)
    try:
        report = alt.run(store, CONFIG, tmp_path / 'run', CUTOFF, 'new', allow_network=False)
        assert report['status'] == 'QUALIFIED_FOR_RESEARCH_PRICE_ONLY' and report['requests'] == []
        snapshot = store.accepted('tencent', alt.SYMBOL, CUTOFF)
        assert snapshot['run_id'] == 'new' and len(snapshot['records']) == 199
        assert set(snapshot['records'][-1]) == {'date', 'open', 'close', 'high', 'low'}
        with pytest.raises(DataNotAccepted):
            store.accepted('tencent', alt.SYMBOL, '2026-11-03')
    finally:
        store.close()


def test_failed_fresh_request_revokes_acceptance_and_cannot_fall_back_offline(tmp_path, monkeypatch):
    store = seeded_store(tmp_path, hours_old=25)
    calls = []

    def failing_get(*a, **kw):
        calls.append(a[0])
        return SimpleNamespace(status_code=503, content=b'{"error":"unavailable"}',
                               raise_for_status=lambda: (_ for _ in ()).throw(requests.HTTPError()))

    monkeypatch.setattr(alt.requests, 'get', failing_get)
    try:
        report = alt.run(store, CONFIG, tmp_path / 'failed', CUTOFF, 'failed', allow_network=True)
        assert report['status'] == 'BLOCKED' and len(calls) == 1
        with pytest.raises(DataNotAccepted):
            store.accepted('tencent', alt.SYMBOL, CUTOFF)
        # Even a nominally young head cannot override a recorded later failure.
        for provider in alt.PROVIDERS:
            old = store.head(provider, alt.SYMBOL)
            body = store.read_object(old['sha256'])
            receipt = {**old['receipt'], 'retrieved_at_utc': datetime.now(timezone.utc).isoformat()}
            store.observe(provider, alt.SYMBOL, 'prices', CUTOFF, body, receipt)
        again = alt.run(store, CONFIG, tmp_path / 'offline', CUTOFF, 'offline', allow_network=False)
        assert again['status'] == 'BLOCKED' and len(calls) == 1
    finally:
        store.close()


def test_four_issuer_originals_and_exact_vanguard_schedule():
    cases = load_cases(ROOT)
    assert {r['symbol']: float(r['resolution']['cash_usd_per_share']) for r in cases} == {
        'AGG': .342379, 'TLT': .343177, 'BIL': .308493, 'VGIT': .199}
    assert all(r['ex_date'] == CUTOFF and r['status'] == 'CONFIRMED_CASH_EVENT' for r in cases)


def test_cash_reference_change_cannot_override_issuer_original(tmp_path):
    data = json.loads((ROOT / 'research/data_quality/independent_cash_references.json').read_text(encoding='utf-8'))
    data['cases'] = [data['cases'][0]]
    case = data['cases'][0]
    for evidence in case['evidence']:
        path = tmp_path / evidence['artifact']; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / evidence['artifact']).read_bytes())
    case['resolution']['cash_usd_per_share'] = '99.0'
    registry = tmp_path / 'research/data_quality/independent_cash_references.json'
    registry.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='differs from actual issuer row'):
        load_cases(tmp_path)


def test_archive_mode_uses_exact_current_bond_index_instead_of_expired_candidate(tmp_path, monkeypatch):
    import audit_cn_sources as cli
    fix = ROOT / 'tests/fixtures/cn_source_audit'
    paths = {}
    for label in ['long', 'short']:
        body = (fix / ('h11077_' + label + '_20261026.json')).read_bytes()
        prefix = tmp_path / label
        Path(str(prefix) + '_parsed.json').write_bytes(body)
        Path(str(prefix) + '_response.txt').write_bytes(body)
        Path(str(prefix) + '_receipt.json').write_text(json.dumps({'status': 200, 'sha256': sha256(body)}))
        paths[label] = str(prefix) + '_parsed.json'
    long_index = tmp_path / 'long.json'; short_index = tmp_path / 'short.json'
    long_index.write_text(json.dumps({'schema': 1, 'kind': 'long', 'entries': {'H11077.SH': {
        'parsed_path': paths['long'], 'cutoff': '2026-10-26'}}}))
    short_index.write_text(json.dumps({'schema': 1, 'kind': 'short', 'entries': {'H11077.SH': {
        'parsed_path': paths['short'], 'cutoff': '2026-10-26', 'short_start': '2026-10-20', 'kind': 'index'}}}))
    expired = tmp_path / 'expired'; expired.mkdir()
    refs = tmp_path / 'refs'; refs.mkdir()
    (refs / 'H11077.json').write_bytes((fix / 'h11077_official_193days_20261023.json').read_bytes())
    monkeypatch.setattr(cli, 'WindClient', lambda *a, **kw: pytest.fail('Archive must not request Wind'))
    args = SimpleNamespace(output=tmp_path / 'out', sessions=fix / 'sessions_through_20261026.json',
        start='2026-01-01', cutoff='2026-10-26', symbols='H11077.SH', mode='archive', credential=None,
        candidate_archive=expired, max_requests=1, dns_override=None, offline_archive=tmp_path,
        short_archive=None, short_index=short_index, long_index=long_index, reference_dir=refs, tail_sessions=5)
    cli.run(args)
    report = json.loads(next((tmp_path / 'out').glob('*/report.json')).read_text(encoding='utf-8'))
    assert report['requests'] == 0 and report['assets'][0]['gate'] == 'PARTIAL_INDEPENDENT_REFERENCE'

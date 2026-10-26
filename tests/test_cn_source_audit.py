"""Wind service rejects real bad ranges and explicitly mutated counterexamples."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from source_audit.wind import (WindClient, WindIntervalConflict, archive_payload,
                               audit_asset, amount_frame, validate_option_chain_result, merge_incremental)

FIX = ROOT / 'tests/fixtures/v80_verified_data_20261025'
LONG = json.loads((FIX / 'wind_bad_long_tail.json').read_text(encoding='utf-8'))
SHORT = json.loads((FIX / 'wind_short.json').read_text(encoding='utf-8'))
REFERENCE = json.loads((FIX / 'csi_zz1000_reference.json').read_text(encoding='utf-8'))
SESSION = pd.date_range('2026-10-19', '2026-10-23', freq='B')


def audit(long=LONG, short=SHORT, **kwargs):
    return audit_asset('000852.SH', 'index', long, short, sessions=SESSION,
                       start='2026-10-19', end='2026-10-23', calendar_source='https://www.sse.com.cn/disclosure/dealinstruc/closed/',
                       independent_calendar=kwargs.pop('independent_calendar', True), reference_payload=REFERENCE,
                       **kwargs)


def good_long():
    # Explicit range-fixture mutation; not a repaired production data export.
    value = copy.deepcopy(SHORT)
    value['id'] = 'TEST_DISTINCT_LONG'
    value['result'].setdefault('_meta', {})['requestId'] = 'TEST_DISTINCT_LONG'
    return value


def test_real_corrupt_long_interval_returns_no_accepted_data():
    report, data = audit()
    assert report['gate'] == 'BLOCKED'
    assert data is None
    assert report['production_approved'] is False


def test_independent_overlap_check_never_approves_index_turnover():
    report, data = audit(good_long())
    assert report['gate'] == 'INDEPENDENT_OVERLAP_CHECKED'
    assert data is not None
    assert report['amount_gate'] == 'BLOCKED'
    assert report['amount_basis'] == 'UNVERIFIED_CONSTITUENT_AGGREGATION'
    assert report['production_approved'] is False


def test_missing_independent_calendar_is_blocked():
    report, data = audit(good_long(), independent_calendar=False)
    assert report['gate'] == 'BLOCKED' and data is None


def test_same_long_short_receipt_cannot_verify_itself():
    report, data = audit(SHORT, SHORT)
    assert report['gate'] == 'BLOCKED' and data is None


def test_boolean_turnover_is_not_money():
    p = copy.deepcopy(SHORT)
    decoded = json.loads(p['result']['content'][0]['text'])
    index = [c['name'] for c in decoded['data']['columns']].index('TURNOVER')
    decoded['data']['rows'][0][index] = True
    p['result']['content'][0]['text'] = json.dumps(decoded)
    with pytest.raises(WindIntervalConflict): amount_frame(p, kind='index')


def test_absent_turnover_does_not_convert_share_volume_to_money():
    p = copy.deepcopy(SHORT)
    decoded = json.loads(p['result']['content'][0]['text'])
    index = [c['name'] for c in decoded['data']['columns']].index('TURNOVER')
    decoded['data']['columns'].pop(index)
    for row in decoded['data']['rows']: row.pop(index)
    p['result']['content'][0]['text'] = json.dumps(decoded)
    value, status = amount_frame(p, kind='fund')
    assert value is None and status == 'MISSING_AMOUNT_FIELD'


def test_amount_difference_blocks_entire_candidate_return():
    p = good_long()
    decoded = json.loads(p['result']['content'][0]['text'])
    index = [c['name'] for c in decoded['data']['columns']].index('TURNOVER')
    decoded['data']['rows'][-1][index] = str(float(decoded['data']['rows'][-1][index]) * 2)
    p['result']['content'][0]['text'] = json.dumps(decoded)
    report, data = audit(p)
    assert data is None and report['gate'] == 'BLOCKED'
    assert 'turnover conflict' in report['reason']


def create_archive(tmp_path, payload=SHORT, status=200):
    raw = json.dumps(payload).encode()
    (tmp_path / 'test_response.txt').write_bytes(raw)
    (tmp_path / 'test_receipt.json').write_text(json.dumps({'status': status, 'sha256': hashlib.sha256(raw).hexdigest()}))
    p = tmp_path / 'test_parsed.json'
    p.write_text(json.dumps(payload))
    return p


def test_failed_archive_receipt_cannot_become_success(tmp_path):
    path = create_archive(tmp_path, status=429)
    with pytest.raises(WindIntervalConflict): archive_payload(path)


def test_archive_parsed_file_must_match_original_hash_verified_response(tmp_path):
    path = create_archive(tmp_path)
    p = copy.deepcopy(SHORT)
    p['result']['isError'] = True
    path.write_text(json.dumps(p))
    with pytest.raises(WindIntervalConflict): archive_payload(path)


def test_archive_never_claims_fresh_live_data(tmp_path):
    path = create_archive(tmp_path)
    payload, provenance = archive_payload(path)
    assert payload == SHORT and provenance['source_mode'] == 'ARCHIVE_REUSED'


def test_client_does_not_send_secret_in_argv_or_logs(tmp_path, monkeypatch):
    import source_audit.wind as wind
    monkeypatch.setattr(wind, 'decrypt_dpapi', lambda p: 'TEST_SECRET_SENTINEL')
    calls = []
    def run(command, input, **kwargs):
        calls.append(command)
        assert all('TEST_SECRET_SENTINEL' not in arg for arg in command)
        assert b'TEST_SECRET_SENTINEL' in input
        request = json.loads(json.loads(input.decode().split('data = ', 1)[1]))
        payload = {'jsonrpc': '2.0', 'id': request['id'], 'result': {'tools': [], 'echo': 'TEST_SECRET_SENTINEL'}}
        return type('Result', (), {'returncode': 0, 'stdout': json.dumps(payload).encode() + b'\n__HTTP_STATUS__200'})()
    monkeypatch.setattr(wind.subprocess, 'run', run)
    client = WindClient(tmp_path / 'unused', tmp_path / 'run', max_requests=1)
    client.rpc('stock_data', 'tools/list')
    assert len(calls) == 1
    assert 'TEST_SECRET_SENTINEL' not in ''.join(p.read_text(encoding='utf-8') for p in (tmp_path / 'run').iterdir())
    with pytest.raises(RuntimeError): client.rpc('stock_data', 'tools/list')


def test_client_rejects_unverified_side_effect_tool(tmp_path, monkeypatch):
    import source_audit.wind as wind
    monkeypatch.setattr(wind, 'decrypt_dpapi', lambda p: 'TEST_SECRET_SENTINEL')
    client = WindClient(tmp_path / 'unused', tmp_path / 'run')
    with pytest.raises(ValueError):
        client.rpc('stock_data', 'tools/call', {'name': 'submit_order', 'arguments': {}})
    assert client.count == 0


def test_non_json_auth_failure_stops_every_wind_server(tmp_path,monkeypatch):
    import source_audit.wind as wind
    monkeypatch.setattr(wind,'decrypt_dpapi',lambda p:'TEST_SECRET_SENTINEL')
    calls=[]
    def failed(*a,**k):
        calls.append(1)
        return type('Response',(),{'returncode':0,'stdout':b'Unauthorized\n__HTTP_STATUS__401'})()
    monkeypatch.setattr(wind.subprocess,'run',failed)
    client=WindClient(tmp_path/'unused',tmp_path/'run')
    with pytest.raises(RuntimeError): client.rpc('index_data','tools/list')
    with pytest.raises(RuntimeError): client.rpc('fund_data','tools/list')
    assert len(calls)==1 and client.global_stopped


def test_actual_wrong_option_product_and_intraday_date_are_hard_rejected():
    payload = json.loads((ROOT / 'tests/fixtures/cn_source_audit/wind_wrong_option_chain.json').read_text(encoding='utf-8'))
    result, rows = validate_option_chain_result(payload, product='MO', underlying_code='000852.SH', date='2026-10-23', expiry_month='2026-12')
    assert rows is None and result['status'] == 'BLOCKED'
    assert {'CONTRACT_PRODUCT_MISMATCH', 'UNDERLYING_MISMATCH', 'REQUIRED_DATE_MISMATCH', 'MISSING_CONTRACT_MULTIPLIER'} <= set(result['issues'])


def truncated_payload(rows):
    value = copy.deepcopy(SHORT)
    value['id'] = 'EXPLICIT_TEST_MUTATION_LONG'
    body = json.loads(value['result']['content'][0]['text'])
    body['data']['rows'] = body['data']['rows'][rows]
    value['result']['content'][0]['text'] = json.dumps(body)
    return value


def test_incremental_append_has_lineage_and_never_modifies_raw_payloads():
    old = truncated_payload(slice(0, 3))
    before = copy.deepcopy((old, SHORT))
    derived, lineage = merge_incremental(old, SHORT, code='000852.SH', kind='index', sessions=SESSION,
                                         start='2026-10-19', end='2026-10-23', parent_hashes={'long': 'a' * 64, 'short': 'b' * 64})
    assert (old, SHORT) == before
    assert lineage['added_dates'] == ['2026-10-22', '2026-10-23']
    assert lineage['parent_hashes']['long'] == 'a' * 64
    assert lineage['new_rows_second_independent_quote'] is False
    assert derived['_derived_dataset']['mode'] == 'DERIVED_ARCHIVE_PLUS_FRESH_TAIL'


def test_incremental_revised_overlap_requires_full_refresh():
    old = truncated_payload(slice(0, 3))
    new = copy.deepcopy(SHORT)
    body = json.loads(new['result']['content'][0]['text'])
    col = [c['name'] for c in body['data']['columns']].index('OPEN')
    body['data']['rows'][1][col] = str(float(body['data']['rows'][1][col]) * 1.1)
    new['result']['content'][0]['text'] = json.dumps(body)
    with pytest.raises(WindIntervalConflict, match='needs_full_refresh: revised overlap'):
        merge_incremental(old, new, code='000852.SH', kind='index', sessions=SESSION,
                          start='2026-10-19', end='2026-10-23', parent_hashes={})


def test_disconnected_incremental_dates_are_not_concatenated():
    old, new = truncated_payload(slice(0, 2)), truncated_payload(slice(2, None))
    with pytest.raises(WindIntervalConflict, match='insufficient connected overlap'):
        merge_incremental(old, new, code='000852.SH', kind='index', sessions=SESSION,
                          start='2026-10-19', end='2026-10-23', parent_hashes={})


def test_completed_same_cutoff_short_index_avoids_even_credential_loading(tmp_path, monkeypatch):
    import audit_cn_sources as cli
    long_dir, short_dir = tmp_path / 'originals', tmp_path / 'short'
    long_dir.mkdir(); short_dir.mkdir()
    p = create_archive(long_dir, LONG)
    for suffix in ['parsed.json', 'receipt.json', 'response.txt']:
        (long_dir / ('test_' + suffix)).rename(long_dir / ('zz1000_full_kline_' + suffix))
    sp = create_archive(short_dir, SHORT)
    calendar = tmp_path / 'calendar.json'
    calendar.write_text(json.dumps({'source': 'https://www.sse.com.cn/disclosure/dealinstruc/closed/', 'sessions': SESSION.strftime('%Y-%m-%d').tolist()}))
    index = tmp_path / 'short_index.json'
    index.write_text(json.dumps({'schema': 1, 'kind': 'short', 'entries': {'000852.SH': {'kind': 'index', 'cutoff': '2026-10-23', 'short_start': '2026-10-19', 'parsed_path': str(sp)}}}))
    monkeypatch.setattr(cli, 'WindClient', lambda *a, **k: pytest.fail('Completed cutoff must not instantiate a live client'))
    args = type('Args', (), {'output': tmp_path / 'outputs', 'sessions': calendar, 'start': '2026-10-19', 'cutoff': '2026-10-23',
        'symbols': '000852.SH', 'mode': 'tail', 'credential': None, 'max_requests': 1, 'dns_override': None,
        'offline_archive': long_dir, 'short_archive': None, 'short_index': index, 'long_index': None,
        'reference_dir': None, 'tail_sessions': 5})()
    assert cli.run(args) == 2  # The known real long-range conflict remains blocked.
    report = json.loads(next((tmp_path / 'outputs').glob('*/report.json')).read_text(encoding='utf-8'))
    assert report['requests'] == 0
    assert report['assets'][0]['gate'] == 'BLOCKED'


def test_reusing_incremental_long_does_not_promote_single_origin_rows_or_change_gate(tmp_path,monkeypatch):
    import audit_cn_sources as cli
    old_dir,new_dir=tmp_path/'old',tmp_path/'new'
    old_dir.mkdir(); new_dir.mkdir()
    old_payload=truncated_payload(slice(0,3))
    old_payload['result'].setdefault('_meta',{})['requestId']='TEST_OLDER_DISTINCT_RESPONSE'
    body=json.loads(old_payload['result']['content'][0]['text'])
    extra=copy.deepcopy(body['data']['rows'][0])
    extra[0]=extra[0].replace('2026-10-19','2026-10-16')  # Explicit synthetic prefix row for range topology.
    body['data']['rows'].insert(0,extra)
    old_payload['result']['content'][0]['text']=json.dumps(body)
    old=create_archive(old_dir,old_payload)
    short=create_archive(new_dir,SHORT)
    calendar=tmp_path/'calendar.json'
    calendar.write_text(json.dumps({'source':'https://www.sse.com.cn/disclosure/dealinstruc/closed/','sessions':['2026-10-16']+SESSION.strftime('%Y-%m-%d').tolist()}))
    short_index=tmp_path/'short_index.json'
    short_index.write_text(json.dumps({'schema':1,'kind':'short','entries':{'000852.SH':{'kind':'index','cutoff':'2026-10-23','short_start':'2026-10-19','parsed_path':str(short)}}}))
    long_index=tmp_path/'long_index.json'
    long_index.write_text(json.dumps({'schema':1,'kind':'long','entries':{'000852.SH':{'kind':'index','parsed_path':str(old)}}}))
    monkeypatch.setattr(cli,'WindClient',lambda *a,**k:pytest.fail('No repeat network request'))
    args=type('Args',(),{'output':tmp_path/'outputs','sessions':calendar,'start':'2026-10-16','cutoff':'2026-10-23','symbols':'000852.SH','mode':'tail','credential':None,'max_requests':1,'dns_override':None,'offline_archive':None,'short_archive':None,'short_index':short_index,'long_index':long_index,'reference_dir':None,'tail_sessions':5})()
    for _ in range(2):
        assert cli.run(args)==2
    reports=[json.loads(p.read_text(encoding='utf-8')) for p in (tmp_path/'outputs').glob('*/report.json')]
    assert len(reports)==2
    assert all(p['requests']==0 and p['assets'][0]['gate']=='INCREMENTAL_OVERLAP_CHECKED' and p['assets'][0]['new_rows_second_independent_quote'] is False for p in reports)


def test_known_interval_conflict_cannot_clear_on_a_new_same_provider_agreement(tmp_path,monkeypatch):
    import audit_cn_sources as cli
    old_dir,new_dir=tmp_path/'old',tmp_path/'new'
    old_dir.mkdir(); new_dir.mkdir()
    old=create_archive(old_dir,good_long()); short=create_archive(new_dir,SHORT)
    calendar=tmp_path/'calendar.json'
    calendar.write_text(json.dumps({'source':'https://www.sse.com.cn/disclosure/dealinstruc/closed/','sessions':SESSION.strftime('%Y-%m-%d').tolist()}))
    idx=tmp_path/'short_index.json'
    idx.write_text(json.dumps({'schema':1,'kind':'short','entries':{'930955.CSI':{'kind':'index','cutoff':'2026-10-23','short_start':'2026-10-19','parsed_path':str(short)}}}))
    long_idx=tmp_path/'long_index.json'
    long_idx.write_text(json.dumps({'schema':1,'kind':'long','entries':{'930955.CSI':{'parsed_path':str(old)}}}))
    # Isolate the quarantine decision from the separately tested field validator.
    monkeypatch.setattr(cli,'audit_asset',lambda *a,**k:({'code':'930955.CSI','kind':'index','gate':'INTERVAL_COHERENT_ONLY','amount_gate':'BLOCKED','field_gaps':[]},pd.DataFrame({'close':[1]})))
    monkeypatch.setattr(cli,'WindClient',lambda *a,**k:pytest.fail('No new requests'))
    args=type('Args',(),{'output':tmp_path/'outputs','sessions':calendar,'start':'2026-10-19','cutoff':'2026-10-23','symbols':'930955.CSI','mode':'tail','credential':None,'max_requests':1,'dns_override':None,'offline_archive':None,'short_archive':None,'short_index':idx,'long_index':long_idx,'reference_dir':None,'tail_sessions':5})()
    assert cli.run(args)==2
    report=json.loads(next((tmp_path/'outputs').glob('*/report.json')).read_text(encoding='utf-8'))
    assert report['assets'][0]['gate']=='BLOCKED' and report['assets'][0]['known_quarantine']
    assert not list((tmp_path/'outputs').glob('*/*research_only_ohlcv.csv'))

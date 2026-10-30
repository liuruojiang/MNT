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
                               audit_asset, audit_bond_close, check_sina_attestation,
                               amount_frame, validate_option_chain_result, merge_incremental)

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


def test_curl_preserves_chinese_request_body(tmp_path, monkeypatch):
    """Exercise curl's real config parser against a loopback-only HTTP server."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import shutil
    import threading
    import source_audit.wind as wind

    if shutil.which('curl.exe') is None:
        pytest.skip('Windows curl.exe is required for the production transport')
    observed = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.headers.get('Content-Length') is not None, str(self.headers)
            body = self.rfile.read(int(self.headers['Content-Length']))
            request = json.loads(body.decode('utf-8'))
            observed.append(request['params']['arguments']['question'])
            response = json.dumps({'jsonrpc': '2.0', 'id': request['id'],
                                   'result': {'ok': True}}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(wind, 'decrypt_dpapi', lambda p: 'TEST_SECRET_SENTINEL')
    monkeypatch.setitem(wind.SERVERS, 'index_data', f'http://127.0.0.1:{server.server_port}/')
    question = '查询中证红利低波100；保留 "引号"、反斜杠\\和换行\n第二行'
    try:
        client = WindClient(tmp_path / 'unused', tmp_path / 'run', max_requests=1)
        result = client.rpc('index_data', 'tools/call', {
            'name': 'get_index_kline', 'arguments': {'question': question}})
        assert result['result']['ok'] is True
        assert observed == [question]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


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


def test_http200_credit_business_error_stops_batch_and_persists_hold(tmp_path,monkeypatch):
    import source_audit.wind as wind
    monkeypatch.setattr(wind,'decrypt_dpapi',lambda p:'TEST_SECRET_SENTINEL')
    calls=[]
    def depleted(command,input,**kwargs):
        calls.append(1)
        request=json.loads(json.loads(input.decode().split('data = ',1)[1]))
        result={'id':request['id'],'jsonrpc':'2.0','result':{'isError':True,'structuredContent':{'code':402,'message':'账户积分余额不足'},'content':[{'type':'text','text':'账户积分余额不足'}]}}
        return type('Response',(),{'returncode':0,'stdout':json.dumps(result,ensure_ascii=False).encode()+b'\n__HTTP_STATUS__200'})()
    monkeypatch.setattr(wind.subprocess,'run',depleted)
    client=WindClient(tmp_path/'unused',tmp_path/'run',budget_store=tmp_path/'store')
    with pytest.raises(RuntimeError):client.kline('000852.SH','index','2026-01-01','2026-10-26')
    with pytest.raises(RuntimeError):client.kline('000300.SH','index','2026-01-01','2026-10-26')
    assert len(calls)==1 and client.global_stopped
    hold=json.loads((tmp_path/'store/provider_holds/wind.json').read_text(encoding='utf-8'))
    assert hold['status']=='OPEN' and hold['reason']=='ACCOUNT_CREDITS_EXHAUSTED'
    receipt=json.loads(next((tmp_path/'run').glob('*_receipt.json')).read_text(encoding='utf-8'))
    assert receipt['status']==200 and receipt['business_error'] is True


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


CLOSE_FIX = ROOT / 'tests/fixtures/cn_source_audit'
BOND_LONG = json.loads((CLOSE_FIX / 'h11077_long_20261026.json').read_text(encoding='utf-8'))
BOND_SHORT = json.loads((CLOSE_FIX / 'h11077_short_20261026.json').read_text(encoding='utf-8'))
BOND_REF = json.loads((CLOSE_FIX / 'h11077_official_193days_20261023.json').read_text(encoding='utf-8'))
BOND_SESSIONS = pd.to_datetime(json.loads((CLOSE_FIX / 'sessions_through_20261026.json').read_text(encoding='utf-8'))['sessions'])


def bond_audit(long=None, short=None, reference=None, **kwargs):
    return audit_bond_close('H11077.SH', BOND_LONG if long is None else long,
        BOND_SHORT if short is None else short, sessions=kwargs.pop('sessions', BOND_SESSIONS),
        start='2026-01-01', end=kwargs.pop('end', '2026-10-26'),
        calendar_source='https://www.sse.com.cn/disclosure/dealinstruc/closed/',
        independent_calendar=kwargs.pop('independent_calendar', True),
        reference_payload=BOND_REF if reference is None else reference, **kwargs)


def test_real_bond_close_without_equity_volume_is_partial_not_unsupported():
    result, data = bond_audit()
    assert data is None and result['gate'] == 'PARTIAL_INDEPENDENT_REFERENCE'
    assert result['rows'] == 194 and result['last'] == '2026-10-26'
    assert result['independent_close_validation']['available_checked_sessions'] == 193
    assert result['independent_close_validation']['missing_recent_dates'] == ['2026-10-26']
    assert result['amount_gate'] == 'NOT_REQUIRED_BY_FORMAL_BOND_LEG'
    assert result['production_approved'] is False


def mutate_bond(payload, mutate):
    value = copy.deepcopy(payload)
    body = json.loads(value['result']['content'][0]['text'])
    mutate(body['data'])
    value['result']['content'][0]['text'] = json.dumps(body)
    return value


@pytest.mark.parametrize('case', ['boolean', 'zero', 'nan', 'duplicate', 'missing_day', 'conflict'])
def test_close_only_rejects_invalid_or_conflicting_real_candidate_mutations(case):
    def mutate(data):
        col = [c['name'] for c in data['columns']].index('MATCH')
        if case == 'duplicate': data['rows'].append(copy.deepcopy(data['rows'][-1]))
        elif case == 'missing_day': data['rows'].pop()
        else: data['rows'][-1][col] = {'boolean': True, 'zero': '0', 'nan': 'NaN', 'conflict': '999'}[case]
    result, data = bond_audit(short=mutate_bond(BOND_SHORT, mutate))
    assert result['gate'] == 'BLOCKED' and data is None


def test_close_only_rejects_same_receipt_and_missing_calendar():
    short = copy.deepcopy(BOND_SHORT)
    short['result']['_meta']['requestId'] = BOND_LONG['result']['_meta']['requestId']
    assert bond_audit(short=short)[0]['gate'] == 'BLOCKED'
    assert bond_audit(independent_calendar=False)[0]['gate'] == 'BLOCKED'


def test_close_only_rejects_wrong_reference_identity_and_old_value_revision():
    ref = copy.deepcopy(BOND_REF)
    ref['data'][0]['indexCode'] = '931077'  # Detail-page code cannot become market-data identity.
    assert bond_audit(reference=ref)[0]['gate'] == 'BLOCKED'
    ref = copy.deepcopy(BOND_REF)
    ref['data'][0]['close'] += 1
    assert bond_audit(reference=ref)[0]['gate'] == 'BLOCKED'


def test_close_only_never_reuses_oct26_candidate_for_future_cutoff():
    sessions = BOND_SESSIONS.append(pd.DatetimeIndex(['2026-10-27']))
    result, data = bond_audit(sessions=sessions, end='2026-10-27')
    assert result['gate'] == 'BLOCKED' and data is None


def test_complete_real_previous_cutoff_close_reference_can_return_research_candidate():
    long = mutate_bond(BOND_LONG, lambda d: d['rows'].pop())
    short = mutate_bond(BOND_SHORT, lambda d: d['rows'].pop())
    result, data = bond_audit(long=long, short=short, sessions=BOND_SESSIONS[:-1], end='2026-10-23', tail_sessions=4)
    assert result['gate'] == 'INDEPENDENT_CLOSE_OVERLAP_CHECKED'
    assert data is not None and list(data.columns) == ['close']
    assert result['production_approved'] is False


def test_partial_bond_candidate_does_not_leak_into_later_asset_index_persistence(tmp_path, monkeypatch):
    import audit_cn_sources as cli
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    for name, payload, begin in [('long', BOND_LONG, '2026-01-01'), ('short', BOND_SHORT, '2026-10-20')]:
        folder = tmp_path / name; folder.mkdir(); path = create_archive(folder, payload)
        for suffix in ['parsed.json', 'response.txt', 'receipt.json']:
            (candidate / (name + '_' + suffix)).write_bytes((folder / ('test_' + suffix)).read_bytes())
        receipt = candidate / (name + '_receipt.json')
        value = json.loads(receipt.read_text()); value['arguments'] = {'windcode': 'H11077.SH', 'begin_date': begin, 'end_date': '2026-10-26'}
        receipt.write_text(json.dumps(value))
    long_index, short_index = tmp_path / 'long_index.json', tmp_path / 'short_index.json'
    long_index.write_text(json.dumps({'schema': 1, 'kind': 'long', 'entries': {}}))
    short_index.write_text(json.dumps({'schema': 1, 'kind': 'short', 'entries': {}}))
    refdir = tmp_path / 'ref'; refdir.mkdir(); (refdir / 'H11077.json').write_text(json.dumps(BOND_REF))
    monkeypatch.setattr(cli, 'ASSETS', [a for a in cli.ASSETS if a['code'] == 'H11077.SH'] + [{'code': '000300.SH', 'kind': 'index', 'archive': 'missing_after_partial'}])
    monkeypatch.setattr(cli, 'WindClient', lambda *a, **k: pytest.fail('No new network calls'))
    args = type('Args', (), {'output': tmp_path / 'outputs', 'sessions': CLOSE_FIX / 'sessions_through_20261026.json',
        'start': '2026-01-01', 'cutoff': '2026-10-26', 'symbols': '', 'mode': 'archive', 'credential': None,
        'candidate_archive': candidate, 'max_requests': 1, 'dns_override': None, 'offline_archive': tmp_path,
        'short_archive': None, 'short_index': short_index, 'long_index': long_index, 'reference_dir': refdir, 'tail_sessions': 5})()
    assert cli.run(args) == 2
    assert json.loads(short_index.read_text())['entries'] == {}
    assert json.loads(long_index.read_text())['entries'] == {}
    report = json.loads(next((tmp_path / 'outputs').glob('*/report.json')).read_text(encoding='utf-8'))
    assert report['requests'] == 0 and report['assets'][0]['gate'] == 'PARTIAL_INDEPENDENT_REFERENCE'
    assert not list((tmp_path / 'outputs').glob('*/*research_only_close.csv'))


def sina_case(tmp_path):
    paths, payloads, sources = {}, {}, {}
    attestation = {'cutoff': '2026-10-26', 'entries': {'000300.SH': {}}}
    entry = attestation['entries']['000300.SH']
    for label in ['long', 'short']:
        directory = tmp_path / label; directory.mkdir()
        payload = json.loads((CLOSE_FIX / ('hs300_' + label + '_20261026.json')).read_text(encoding='utf-8'))
        paths[label] = create_archive(directory, payload)
        payloads[label], sources[label] = archive_payload(paths[label])
        entry[label + '_raw_sha256'] = sources[label]['raw_sha256']
        entry[label + '_parsed_sha256'] = hashlib.sha256(paths[label].read_bytes()).hexdigest()
    raw = tmp_path / 'sina.json'; raw.write_bytes((CLOSE_FIX / 'hs300_sina_20261026.json').read_bytes())
    entry.update(reference_url='https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh000300&scale=240&datalen=10',
        reference_raw_path=str(raw), reference_raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest())
    path = tmp_path / 'attestation.json'; path.write_text(json.dumps(attestation))
    return path, paths, payloads, sources, raw


def test_real_sina_attestation_recomputes_five_days_and_preserves_provider(tmp_path):
    path, _, payloads, sources, _ = sina_case(tmp_path)
    result = check_sina_attestation('000300.SH', payloads['long'], payloads['short'], sources['long'], sources['short'],
        attestation_path=path, sessions=BOND_SESSIONS, cutoff='2026-10-26')
    assert result['status'] == 'THIRD_PARTY_INDEPENDENT_OVERLAP_CHECKED'
    assert result['provider'] == 'sina' and result['official_CSI'] is False
    assert len(result['dates']) == 5 and result['comparisons']['long']['volume']['max_abs_difference'] == 0


@pytest.mark.parametrize('change', ['cutoff', 'independent_raw', 'wind_parsed', 'provider_url', 'value_conflict'])
def test_sina_attestation_cannot_follow_changed_responses_or_future_cutoff(tmp_path, change):
    path, paths, payloads, sources, raw = sina_case(tmp_path)
    cutoff = '2026-10-26'
    if change == 'cutoff': cutoff = '2026-10-27'
    elif change == 'independent_raw': raw.write_text('[]')
    elif change == 'wind_parsed': paths['long'].write_text('{}')
    elif change == 'provider_url':
        data = json.loads(path.read_text()); data['entries']['000300.SH']['reference_url'] = 'https://www.csindex.com.cn/fake'
        path.write_text(json.dumps(data))
    else:
        rows = json.loads(raw.read_text()); rows[-1]['close'] = str(float(rows[-1]['close']) + 1)
        raw.write_text(json.dumps(rows))
        data = json.loads(path.read_text()); data['entries']['000300.SH']['reference_raw_sha256'] = hashlib.sha256(raw.read_bytes()).hexdigest()
        path.write_text(json.dumps(data))
    result = check_sina_attestation('000300.SH', payloads['long'], payloads['short'], sources['long'], sources['short'],
        attestation_path=path, sessions=BOND_SESSIONS, cutoff=cutoff)
    assert result['status'] == ('NOT_APPLICABLE' if change == 'cutoff' else 'FAILED')


@pytest.mark.parametrize('corruption', ['hash_mismatch', 'self_consistent_close_conflict'])
def test_applicable_independent_failure_blocks_cli_csv_and_both_index_promotions(tmp_path, monkeypatch, corruption):
    import audit_cn_sources as cli
    path, paths, _, _, raw = sina_case(tmp_path)
    rows = json.loads(raw.read_text()); rows[-1]['close'] = str(float(rows[-1]['close']) + 1)
    raw.write_text(json.dumps(rows))
    if corruption == 'self_consistent_close_conflict':
        value = json.loads(path.read_text()); value['entries']['000300.SH']['reference_raw_sha256'] = hashlib.sha256(raw.read_bytes()).hexdigest()
        path.write_text(json.dumps(value))
    long_index, short_index = tmp_path / 'long_index.json', tmp_path / 'short_index.json'
    long_index.write_text(json.dumps({'schema': 1, 'kind': 'long', 'entries': {'000300.SH': {'kind': 'index', 'parsed_path': str(paths['long']), 'marker': 'DO_NOT_REPLACE_ON_FAILED_ACCEPTANCE'}}}))
    short_index.write_text(json.dumps({'schema': 1, 'kind': 'short', 'entries': {'000300.SH': {'kind': 'index', 'cutoff': '2026-10-26', 'short_start': '2026-10-20', 'parsed_path': str(paths['short']), 'marker': 'DO_NOT_REPLACE_ON_FAILED_ACCEPTANCE'}}}))
    before = long_index.read_bytes(), short_index.read_bytes()
    monkeypatch.setattr(cli, 'WindClient', lambda *a, **k: pytest.fail('No new network requests'))
    args = type('Args', (), {'output': tmp_path / 'outputs', 'sessions': CLOSE_FIX / 'sessions_through_20261026.json',
        'start': '2026-01-01', 'cutoff': '2026-10-26', 'symbols': '000300.SH', 'mode': 'archive', 'credential': None,
        'max_requests': 1, 'dns_override': None, 'offline_archive': None, 'short_archive': None,
        'short_index': short_index, 'long_index': long_index, 'reference_dir': None, 'tail_sessions': 5,
        'independent_attestation': path})()
    assert cli.run(args) == 2
    report = json.loads(next((tmp_path / 'outputs').glob('*/report.json')).read_text(encoding='utf-8'))
    assert report['assets'][0]['gate'] == 'BLOCKED'
    assert report['assets'][0]['independent_followup']['status'] == 'FAILED'
    assert not list((tmp_path / 'outputs').glob('*/*research_only_ohlcv.csv'))
    assert (long_index.read_bytes(), short_index.read_bytes()) == before

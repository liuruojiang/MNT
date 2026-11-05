"""Regression guards for calendar isolation and dated bond collection.

Provider responses in these software tests are frozen fixtures or explicit
mutations, never evidence of a current live response.
"""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))


def test_calendar_ignores_unrelated_bot_code_but_rejects_policy_change(tmp_path, monkeypatch):
    from source_audit import calendar
    name = 'mnt_bot V 8.0 plus.py'
    body = (ROOT / name).read_text(encoding='utf-8')
    path = tmp_path / name
    path.write_text(body + '\nraise RuntimeError("bot must never execute")\n', encoding='utf-8')
    monkeypatch.setattr(calendar, 'REPO', tmp_path)
    assert not len(calendar.sessions('XNYS', '2025-01-09', '2025-01-09'))
    path.write_text(body.replace('def _us_observed_holiday(', 'def _unreviewed_observed_holiday(', 1), encoding='utf-8')
    with pytest.raises(calendar.CalendarCoverageError):
        calendar.sessions('XNYS', '2026-11-02', '2026-11-02')


def test_calendar_rejects_modified_constant_value(tmp_path, monkeypatch):
    from source_audit import calendar
    name = 'mnt_bot V 8.0 plus.py'
    body = (ROOT / name).read_text(encoding='utf-8')
    body = body.replace("'2025-01-09']).normalize()", "'2025-01-10']).normalize()", 1)
    assert body != (ROOT / name).read_text(encoding='utf-8')
    (tmp_path / name).write_text(body, encoding='utf-8')
    monkeypatch.setattr(calendar, 'REPO', tmp_path)
    with pytest.raises(calendar.CalendarCoverageError, match='policy changed'):
        calendar.sessions('XNYS', '2026-11-02', '2026-11-02')


def test_stale_bond_candidate_reaches_fresh_long_and_short_requests(tmp_path, monkeypatch):
    import audit_cn_sources as cli
    fixture = ROOT / 'tests/fixtures/cn_source_audit'
    candidate = tmp_path / 'expired'; candidate.mkdir()
    (candidate / 'old_receipt.json').write_text(json.dumps({'arguments': {
        'windcode': 'H11077.SH', 'begin_date': '2026-01-01', 'end_date': '2026-10-23'}}))
    calls = []

    class Client:
        def __init__(self, *a, **kw):
            self.count = 0; self.receipts = []; self.stopped = {}

        def kline(self, code, kind, begin, end, label):
            calls.append((code, begin, end)); self.count += 1
            name = 'h11077_long_20261026.json' if begin == '2026-01-01' else 'h11077_short_20261026.json'
            return json.loads((fixture / name).read_text(encoding='utf-8'))

    monkeypatch.setattr(cli, 'WindClient', Client)
    monkeypatch.setattr(cli, 'live_provenance', lambda c: {
        'parsed_path': str(tmp_path / 'unused.json'), 'raw_sha256': str(c.count) * 64})
    refs = tmp_path / 'refs'; refs.mkdir()
    (refs / 'H11077.json').write_bytes((fixture / 'h11077_official_193days_20261023.json').read_bytes())
    args = SimpleNamespace(output=tmp_path / 'out', sessions=fixture / 'sessions_through_20261026.json',
        start='2026-01-01', cutoff='2026-10-26', symbols='H11077.SH', mode='tail', credential=tmp_path / 'unused',
        candidate_archive=candidate, max_requests=2, dns_override=None, offline_archive=tmp_path,
        short_archive=None, short_index=None, long_index=None, reference_dir=refs, tail_sessions=5)
    cli.run(args)
    assert calls == [('H11077.SH', '2026-01-01', '2026-10-26'), ('H11077.SH', '2026-10-20', '2026-10-26')]
    report = json.loads(next((tmp_path / 'out').glob('*/report.json')).read_text(encoding='utf-8'))
    assert report['assets'][0]['gate'] == 'PARTIAL_INDEPENDENT_REFERENCE'
    assert not list((tmp_path / 'out').glob('*/*research_only_close.csv'))


def test_official_reference_revision_blocks_instead_of_reusing_old_close(tmp_path, monkeypatch):
    from source_audit import official_reference as ref
    base = tmp_path / 'base'; base.mkdir()
    original = {'code': '200', 'data': [{'tradeDate': '20261026', 'indexCode': 'H11077', 'close': 192.94}]}
    (base / 'H11077.json').write_text(json.dumps(original))
    response = SimpleNamespace(status_code=200, content=json.dumps({'code': '200', 'data': [
        {'tradeDate': '20261026', 'indexCode': 'H11077', 'close': 199.0}]}).encode(), raise_for_status=lambda: None)
    monkeypatch.setattr(ref.requests, 'get', lambda *a, **k: response)
    out, receipt = ref.refresh_bond_reference(base, tmp_path / 'run', '2026-11-02')
    assert receipt['assessment'] == 'BLOCKED'
    assert json.loads((out / 'H11077.json').read_text())['code'] == 'REFERENCE_REFRESH_FAILED'
    assert json.loads((base / 'H11077.json').read_text()) == original


def test_runtime_dependency_changes_revoke_project_scope(tmp_path, monkeypatch):
    from source_audit import adapters
    path = tmp_path / 'dependency.py'; path.write_bytes(b'old')
    project = {'project_id': 'example', 'entrypoints': [], 'runtime_dependencies': [{
        'path': str(path), 'sha256_lf': hashlib.sha256(b'old').hexdigest()}]}
    monkeypatch.setattr(adapters, 'requirements', lambda: {'projects': [project]})
    assert adapters.project_scope('example') is project
    path.write_bytes(b'new')
    with pytest.raises(adapters.DataNotAccepted, match='runtime dependency changed'):
        adapters.project_scope('example')

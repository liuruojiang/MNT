"""Independent bond-service adversarial checks against preserved real responses."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from source_audit import alternative_sources as alt
from source_audit.store import DataNotAccepted, Store
from source_audit.transport import sha256

FIX = ROOT / 'research/data_quality/20261105_bond_replacement'
SYMBOL = '000012.SH'
CUTOFF = '2026-11-05'
CONFIG = {'enabled_alternative_sources': list(alt.PROVIDERS),
          'alternative_cn_symbols': [SYMBOL], 'same_cutoff_remote_refresh_hours': 24,
          'local_hourly_budgets': {p: 10 for p in alt.PROVIDERS}}


def prices():
    return {p: json.loads((FIX / (p + '.raw')).read_bytes()) for p in ('tencent', 'sina')}


def seeded_store(tmp_path, mutation=None):
    store = Store(tmp_path / 'store')
    for provider, payload in prices().items():
        body = json.dumps(payload).encode()
        receipt = {'status': 200, 'sha256': sha256(body), 'provider': provider, 'symbol': SYMBOL,
                   'url': alt.source_urls(CUTOFF, SYMBOL)[provider],
                   'retrieved_at_utc': datetime.now(timezone.utc).isoformat()}
        if mutation:
            mutation(provider, receipt)
        store.observe(provider, SYMBOL, 'prices', CUTOFF, body, receipt)
    return store


def test_close_only_contract_does_not_require_equity_ohlc():
    values = copy.deepcopy(prices())
    for row in values['sina']:
        for field in ('open', 'high', 'low'):
            row[field] = None
    for row in values['tencent']['data']['sh000012']['day']:
        for index in (1, 3, 4):
            row[index] = None
    records, report = alt.assess_prices(values, CUTOFF, SYMBOL)
    assert len(records) == 202 and report['fields_qualified'] == ['close']


@pytest.mark.parametrize('fault', ['future', 'wrong_url', 'wrong_provider', 'wrong_symbol'])
def test_invalid_receipt_cannot_qualify_real_prices(tmp_path, fault):
    def mutate(provider, receipt):
        if provider != 'sina':
            return
        if fault == 'future': receipt['retrieved_at_utc'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        elif fault == 'wrong_url': receipt['url'] = receipt['url'].replace('sh000012', 'sh000905')
        elif fault == 'wrong_provider': receipt['provider'] = 'tencent'
        else: receipt['symbol'] = '000905.SH'
    store = seeded_store(tmp_path, mutate)
    try:
        result = alt.run(store, CONFIG, tmp_path / 'result', CUTOFF, fault, allow_network=False)
        assert result['status'] == 'BLOCKED'
        with pytest.raises(DataNotAccepted):
            store.accepted('tencent', SYMBOL, CUTOFF)
    finally:
        store.close()


def test_qualified_bond_snapshot_revoked_after_missing_source(tmp_path):
    store = seeded_store(tmp_path)
    try:
        assert alt.run(store, CONFIG, tmp_path / 'ok', CUTOFF, 'ok', allow_network=False)['status'] == 'QUALIFIED_FOR_RESEARCH_PRICE_ONLY'
        old = store.head('sina', SYMBOL)
        payload = old['payload'][:-1]
        body = json.dumps(payload).encode()
        receipt = {**old['receipt'], 'sha256': sha256(body), 'retrieved_at_utc': datetime.now(timezone.utc).isoformat()}
        store.observe('sina', SYMBOL, 'prices', CUTOFF, body, receipt)
        assert alt.run(store, CONFIG, tmp_path / 'bad', CUTOFF, 'bad', allow_network=False)['status'] == 'BLOCKED'
        with pytest.raises(DataNotAccepted): store.accepted('tencent', SYMBOL, CUTOFF)
    finally:
        store.close()


def test_bond_only_configuration_needs_only_its_two_reviewed_sources(tmp_path):
    store = seeded_store(tmp_path)
    try:
        cfg = {**CONFIG, 'enabled_alternative_sources': ['tencent', 'sina']}
        result = alt.run(store, cfg, tmp_path / 'bond_only', CUTOFF, 'bond_only', allow_network=False)
        assert result['status'] == 'QUALIFIED_FOR_RESEARCH_PRICE_ONLY'
    finally:
        store.close()


@pytest.mark.parametrize('enabled', [[], ['tencent']])
def test_retirement_requires_both_replacement_sources(tmp_path, monkeypatch, enabled):
    import run_data_source_service as service
    monkeypatch.setattr(service, 'wind_archive', lambda *a: tmp_path / 'archive')
    monkeypatch.setattr(service.adapters, 'project_scope', lambda _: {'requirements': [
        {'requirement_id': 'cn_bond_close', 'instruments': [SYMBOL]}]})
    def fake_run(command, **kw):
        output = Path(command[command.index('--output') + 1]) / 'fixture'
        output.mkdir(parents=True)
        (output / 'report.json').write_text(json.dumps({'assets': [], 'requests': 0}))
        return SimpleNamespace(stdout='', stderr='', returncode=0)
    monkeypatch.setattr(service.subprocess, 'run', fake_run)
    output = tmp_path / 'out'; output.mkdir()
    cfg = {**CONFIG, 'store_root': str(tmp_path), 'legacy_wind_archive': 'unused',
           'credentials': {'wind': 'unused'}, 'local_hourly_budgets': {'wind': 30},
           'suba_bond_symbol': SYMBOL, 'enabled_alternative_sources': enabled}
    with pytest.raises(ValueError, match='[Ss]ource|contract|[Cc]onfiguration|provider'):
        service.cn_run(cfg, output, 'archive', CUTOFF)


@pytest.mark.parametrize('legacy_symbol', [None, 'H11077.SH'])
def test_stale_machine_configuration_cannot_skip_current_bond_contract(tmp_path, monkeypatch, legacy_symbol):
    import run_data_source_service as service
    monkeypatch.setattr(service, 'wind_archive', lambda *a: tmp_path / 'archive')
    monkeypatch.setattr(service.adapters, 'project_scope', lambda _: {'requirements': [
        {'requirement_id': 'cn_bond_close', 'instruments': [SYMBOL]}]})
    def fake_run(command, **kw):
        output = Path(command[command.index('--output') + 1]) / 'fixture'
        output.mkdir(parents=True)
        (output / 'report.json').write_text(json.dumps({'assets': [], 'requests': 0}))
        return SimpleNamespace(stdout='', stderr='', returncode=0)
    monkeypatch.setattr(service.subprocess, 'run', fake_run)
    output = tmp_path / 'out'; output.mkdir()
    cfg = {'store_root': str(tmp_path), 'legacy_wind_archive': 'unused',
           'credentials': {'wind': 'unused'}, 'local_hourly_budgets': {'wind': 30},
           'enabled_alternative_sources': list(alt.PROVIDERS),
           'alternative_cn_symbols': ['518880.SH', '000905.SH']}
    if legacy_symbol is not None:
        cfg['suba_bond_symbol'] = legacy_symbol
    with pytest.raises(ValueError, match='[Cc]onfiguration|contract|[Bb]ond'):
        service.cn_run(cfg, output, 'archive', CUTOFF)

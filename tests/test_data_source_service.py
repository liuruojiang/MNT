"""Shared service invariants; adversarial inputs here are explicitly synthetic."""
from datetime import datetime, timezone, timedelta
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from source_audit.calendar import sessions,confirmed_cutoff,CalendarCoverageError
from source_audit.store import Store,DataNotAccepted
from source_audit.config import initialize
from source_audit.registry import annotate_us
from source_audit.us_service import needs_full_history,merge_tiingo
from source_audit.adapters import read_asset
from source_audit.store import service_lock,ServiceAlreadyRunning


@pytest.fixture
def store(tmp_path):
    s=Store(tmp_path/'store')
    yield s
    s.close()


def test_exchange_calendar_catches_common_missing_day_and_adhoc_closures():
    ix=sessions('XNYS','2026-09-28','2026-09-30')
    assert [str(d.date()) for d in ix]==['2026-09-28','2026-09-29','2026-09-30']
    assert not len(sessions('XNYS','2025-01-09','2025-01-09'))
    assert not len(sessions('XNYS','2012-10-29','2012-10-30'))
    assert not len(sessions('XNYS','2026-06-19','2026-06-19'))


def test_china_exchange_does_not_treat_makeup_weekend_as_trading():
    ix=sessions('XSHG','2026-10-01','2026-10-12')
    assert '2026-10-08' in [str(d.date()) for d in ix]
    assert '2026-10-10' not in [str(d.date()) for d in ix]
    assert not len(sessions('XSHG','2026-09-25','2026-09-27'))
    with pytest.raises(CalendarCoverageError): sessions('XSHG','2025-12-31','2026-01-05')


def test_confirmed_cutoff_is_not_inferred_from_spy_or_weekdays():
    now=datetime(2026,10,26,6,30,tzinfo=timezone.utc)  # China Monday, still intraday.
    assert confirmed_cutoff('XSHG',now)=='2026-10-23'
    assert confirmed_cutoff('XNYS',now)=='2026-10-23'
    assert confirmed_cutoff('XSHG',datetime(2026,10,26,9,tzinfo=timezone.utc))=='2026-10-26'
    assert confirmed_cutoff('XNYS',datetime(2026,10,27,2,tzinfo=timezone.utc))=='2026-10-26'


def publish(store,provider='tiingo',symbol='SPY',run='a',cutoff='2026-10-23'):
    store.gate(provider,symbol,'QUALIFIED_FOR_RESEARCH',[],run)
    store.publish(provider,symbol,cutoff,[{'date':cutoff,'close':100}],{'fields_qualified':['close']},run)


def test_quarantine_revokes_previously_qualified_snapshot_without_stale_fallback(store):
    publish(store)
    assert store.accepted('tiingo','SPY','2026-10-23')['production_approved'] is False
    store.gate('tiingo','SPY','BLOCKED',['known upstream conflict'],'b')
    with pytest.raises(DataNotAccepted): store.accepted('tiingo','SPY','2026-10-23')


def test_new_assessment_does_not_publish_previous_run_healthy_while_verifying(store):
    publish(store)
    store.begin_run()
    with pytest.raises(DataNotAccepted): store.accepted('tiingo','SPY','2026-10-23')
    store.gate('tiingo','SPY','QUALIFIED_FOR_RESEARCH',[],'c')
    with pytest.raises(DataNotAccepted): store.accepted('tiingo','SPY','2026-10-23')


def test_network_failure_quarantines_entire_provider_not_only_one_asset(store):
    publish(store,symbol='SPY')
    publish(store,symbol='QQQ')
    publish(store,provider='yahoo',symbol='SPY')
    store.quarantine_provider('tiingo','HTTP429','new_run')
    for symbol in ['SPY','QQQ']:
        with pytest.raises(DataNotAccepted): store.accepted('tiingo',symbol,'2026-10-23')
    assert store.accepted('yahoo','SPY','2026-10-23')


def test_snapshot_cannot_be_used_for_production_or_another_cutoff(store):
    publish(store)
    with pytest.raises(DataNotAccepted): store.accepted('tiingo','SPY','2026-10-23',purpose='production')
    with pytest.raises(DataNotAccepted): store.accepted('tiingo','SPY','2026-10-26')


def test_object_dedup_and_hash_validation(store):
    sha=store.put_object(b'{"test":1}')
    assert store.put_object(b'{"test":1}')==sha
    assert store.db.execute('SELECT COUNT(*) FROM objects').fetchone()[0]==1
    store.object_path(sha).write_bytes(b'{"test":2}')
    with pytest.raises(DataNotAccepted): store.read_object(sha)


def test_receipt_failure_and_replayed_old_import_cannot_promote_or_roll_back(store):
    body=b'[]'
    import hashlib
    sha=hashlib.sha256(body).hexdigest()
    with pytest.raises(DataNotAccepted): store.observe('tiingo','SPY','prices','2026-10-23',body,{'status':429,'sha256':sha})
    store.observe('tiingo','SPY','prices','2026-10-26',body,{'status':200,'sha256':sha,'retrieved_at_utc':'2026-10-26T10:00:00+00:00'})
    store.observe('tiingo','SPY','prices','2026-10-23',body,{'status':200,'sha256':sha,'retrieved_at_utc':'2026-10-25T10:00:00+00:00'})
    assert store.head('tiingo','SPY')['cutoff']=='2026-10-26'


def test_hourly_budget_survives_reopening_the_catalog(store):
    now=datetime(2026,10,26,8,tzinfo=timezone.utc)
    store.reserve_request('tiingo',1,now)
    other=Store(store.root)
    try:
        with pytest.raises(DataNotAccepted): other.reserve_request('tiingo',1,now)
    finally: other.close()


def test_concurrent_manual_and_daily_collectors_cannot_double_fetch(store):
    with service_lock(store.root):
        with pytest.raises(ServiceAlreadyRunning):
            with service_lock(store.root): pytest.fail('Concurrent acquisition was allowed')
    with service_lock(store.root): pass


def bar(day,close=100,cash=0,split=1):
    return {'date':day+'T00:00:00.000Z','open':close,'close':close,'adjOpen':close,'adjClose':close,'divCash':cash,'splitFactor':split}


@pytest.mark.parametrize('new',[bar('2026-10-26',cash=1),bar('2026-10-26',split=2),bar('2026-10-23',close=99)])
def test_new_action_or_revised_prefix_requires_full_refresh(new):
    old=[bar('2026-10-23')]
    assert needs_full_history(old,[new])
    with pytest.raises(DataNotAccepted): merge_tiingo(old,[new],'2026-10-26')


def test_non_action_increment_preserves_history_and_does_not_mutate_parents():
    old=[bar('2026-10-22'),bar('2026-10-23')]
    delta=[bar('2026-10-23'),bar('2026-10-26',close=101)]
    frozen=copy.deepcopy((old,delta))
    result=merge_tiingo(old,delta,'2026-10-26')
    assert len(result)==3 and result[0]==old[0] and (old,delta)==frozen
    with pytest.raises(DataNotAccepted): merge_tiingo(old,delta*2,'2026-10-26')


def test_encrypted_credential_transfer_is_idempotent_and_never_overwrites(tmp_path):
    source=tmp_path/'old'
    source.mkdir()
    for provider in ['tiingo','wind']: (source/('.'+provider+'-token.dpapi')).write_text('cafe',encoding='ascii')
    target=tmp_path/'new'
    config=initialize(target,source,tmp_path/'legacy',tmp_path/'wind')
    assert source.joinpath('.tiingo-token.dpapi').read_text()=='cafe'
    assert Path(config['credentials']['tiingo']).read_text()=='cafe'
    initialize(target,source,tmp_path/'legacy',tmp_path/'wind')
    source.joinpath('.wind-token.dpapi').write_text('beef',encoding='ascii')
    with pytest.raises(RuntimeError): initialize(target,source,tmp_path/'legacy',tmp_path/'wind')
    assert Path(config['credentials']['wind']).read_text()=='cafe'


def test_completed_dbmf_is_not_created_as_a_new_task_and_alerts_deduplicate(store):
    def event(symbol,date,t,y):
        return {'symbol':symbol,'details':[{'date':date,'flags':['cash'],'tiingo_cash':t,'yahoo_cash':y,'tiingo_split':1,'yahoo_split':1}]}
    report={'assets':[event('DBMF','2026-09-29',0.1456,0),event('QQQ','2020-09-21',0.38824,0)]}
    first=annotate_us(copy.deepcopy(report),store,ROOT)
    assert len(first['new_or_changed_issues'])==1
    assert first['assets'][0]['details'][0]['work_status']=='COMPLETED_DO_NOT_REPEAT'
    assert not annotate_us(copy.deepcopy(report),store,ROOT)['new_or_changed_issues']
    assert first['no_strategy_backtests_repeated']


def test_adapter_rejects_unqualified_volume_and_substring_symbol(store,monkeypatch):
    import source_audit.adapters as adapter
    monkeypatch.setattr(adapter,'project_scope',lambda project:{'requirements':[{'instruments':['SPY']}]})
    publish(store)
    result=read_asset(store,'us_long_v16','tiingo','SPY','2026-10-23',fields=['close'])
    assert result['records']==[{'date':'2026-10-23','close':100}]
    with pytest.raises(DataNotAccepted): read_asset(store,'us_long_v16','tiingo','SPY','2026-10-23',fields=['volume'])
    with pytest.raises(DataNotAccepted): read_asset(store,'us_long_v16','tiingo','SP','2026-10-23')


def test_changed_entrypoint_cannot_consume_old_project_contract(store,tmp_path,monkeypatch):
    import hashlib
    import source_audit.adapters as adapter
    entry=tmp_path/'explicit_test_entry.py'; entry.write_bytes(b'old reviewed test entry')
    contract={'project_id':'test_project','entrypoints':[{'path':str(entry),'sha256_lf':hashlib.sha256(entry.read_bytes()).hexdigest()}],'requirements':[{'instruments':['SPY']}]}
    monkeypatch.setattr(adapter,'requirements',lambda:{'projects':[contract]})
    publish(store)
    assert adapter.read_asset(store,'test_project','tiingo','SPY','2026-10-23',fields=['close'])
    entry.write_bytes(b'changed unreviewed test entry')
    with pytest.raises(DataNotAccepted,match='entrypoint changed'):
        adapter.read_asset(store,'test_project','tiingo','SPY','2026-10-23',fields=['close'])


def test_failed_service_run_revokes_prior_provider_snapshot_and_updates_latest(store,tmp_path,monkeypatch):
    import run_data_source_service as service
    publish(store)
    monkeypatch.setattr(service,'load',lambda p:{'store_root':str(store.root),'legacy_us_run':'unused'})
    monkeypatch.setattr(service,'Store',lambda root:Store(root))
    monkeypatch.setattr(service,'assess',lambda *a,**k:(_ for _ in ()).throw(ValueError('Adversarial parser failure')))
    monkeypatch.setattr(service,'import_legacy',lambda *a:{'new_api_requests':0})
    args=type('Args',(),{'config':tmp_path/'unused','mode':'reuse','cn_mode':'skip','field_probes':None,'export':None})()
    assert service.run(args)==2
    latest=json.loads((store.root/'latest.json').read_text())
    assert latest['status']=='FAILED'
    with pytest.raises(DataNotAccepted): store.accepted('tiingo','SPY','2026-10-23')


def test_weekly_full_check_does_not_spend_an_extra_delta_request_per_asset(store,tmp_path,monkeypatch):
    import hashlib
    import source_audit.us_service as service
    profiles=json.loads((ROOT/'tools/source_audit/projects.json').read_text())
    symbols=sorted(set().union(*(p['symbols'] for p in profiles['projects'].values()))-{'BTC-USD'})
    now=datetime.now(timezone.utc)
    body=json.dumps([bar('2026-10-22')]).encode()
    digest=hashlib.sha256(body).hexdigest()
    for symbol in symbols:
        store.observe('tiingo',symbol,'prices','2026-10-22',body,{'status':200,'sha256':digest,'retrieved_at_utc':now.isoformat(),'last_full_retrieved_at_utc':(now-timedelta(days=8)).isoformat()})
        store.observe('yahoo',symbol,'prices','2026-10-23',body,{'status':200,'sha256':digest,'retrieved_at_utc':now.isoformat()})
    calls=[]
    def fetch(url,path,token):
        calls.append(url)
        path.write_bytes(body)
        return {'status':200,'sha256':digest,'retrieved_at_utc':now.isoformat()},json.loads(body)
    monkeypatch.setattr(service,'fetch',fetch)
    monkeypatch.setattr(service,'decrypt_dpapi',lambda p:'TEST_ONLY')
    config={'credentials':{'tiingo':'unused'},'local_hourly_budgets':{'tiingo':30,'yahoo':30},'same_cutoff_remote_refresh_hours':24,'incremental_overlap_calendar_days':10,'full_revision_check_days':7}
    result=service.refresh(store,config,tmp_path,'2026-10-23')
    assert len(calls)==len(symbols)==22 and not result['provider_stops']
    assert all('startDate=2003-01-01' in u for u in calls)


def test_pinned_wind_bootstrap_survives_original_chat_directory_unavailable(tmp_path):
    import run_data_source_service as service
    old=tmp_path/'old_chat'
    old.mkdir()
    (old/'receipt.json').write_text('{"test_only":true}')
    root=tmp_path/'stable_store'
    root.mkdir()
    pinned=service.wind_archive(root,old)
    assert service.wind_archive(root,tmp_path/'nonexistent_old_chat')==pinned
    (pinned/'receipt.json').write_text('{"tampered":true}')
    with pytest.raises(ValueError,match='archive changed'):
        service.wind_archive(root,tmp_path/'nonexistent_old_chat')


def test_persistent_credit_hold_prevents_daily_live_collection(store,tmp_path,monkeypatch):
    import run_data_source_service as service
    hold=store.root/'provider_holds/wind.json';hold.parent.mkdir()
    hold.write_text(json.dumps({'status':'OPEN','reason':'ACCOUNT_CREDITS_EXHAUSTED'}))
    monkeypatch.setattr(service,'wind_archive',lambda root,legacy:root/'archive')
    calls=[]
    def archived(command,**kw):
        calls.append(command)
        assert command[command.index('--mode')+1]=='archive'
        destination=Path(command[command.index('--output')+1])/'test_run';destination.mkdir(parents=True)
        (destination/'report.json').write_text(json.dumps({'mode':'archive','requests':0,'assets':[]}))
        return type('Proc',(),{'stdout':'','stderr':'','returncode':2})()
    monkeypatch.setattr(service.subprocess,'run',archived)
    output=tmp_path/'assessment';output.mkdir()
    result=service.cn_run({'store_root':str(store.root),'legacy_wind_archive':'unused','credentials':{'wind':'unused'},'local_hourly_budgets':{'wind':30}},output,'tail','2026-10-27')
    assert len(calls)==1 and result['status']=='BLOCKED_PROVIDER_QUOTA' and result['requested_mode']=='tail'
    assert result['requests']==0 and result['provider_stops']['wind']['failure_class']=='ACCOUNT_CREDITS_EXHAUSTED'


def no_cash_oracle(monkeypatch, mutate_tiingo=False):
    import source_audit.us_service as service
    fixture=json.loads((ROOT/'tests/fixtures/us_source_audit/qqq_verified_no_cash_seams.json').read_text(encoding='utf-8'))
    if mutate_tiingo:
        # Adversarial mutation of actual archived quotes: both caches now
        # repeat Yahoo's spurious event. Agreement must not defeat the oracle.
        for row in fixture['tiingo']:
            if row['date'][:10]=='2011-12-27': row['divCash']=0.049
    class FrozenHeads:
        def head(self,provider,symbol,kind='prices'):
            assert symbol=='QQQ'
            return {'payload':fixture['metadata'] if kind=='metadata' else fixture[provider]}
    monkeypatch.setattr(service,'completed_work',lambda _:[])
    monkeypatch.setattr(service,'load_additional',lambda _:fixture['references'])
    return service.known_action_checks(FrozenHeads(),ROOT,'QQQ','2011-12-27')


def test_verified_zero_cash_is_not_skipped_in_real_cached_qqq_seams(monkeypatch):
    result=no_cash_oracle(monkeypatch)
    assert result['tiingo']==[]
    for day in ['2010-06-25','2011-12-27']:
        assert 'KNOWN_ACTION_CASH_CONFLICT:'+day in result['yahoo']
        assert 'KNOWN_ACTION_FACTOR_CONFLICT:'+day in result['yahoo']


def test_two_wrong_caches_cannot_hide_a_confirmed_no_cash_event(monkeypatch):
    result=no_cash_oracle(monkeypatch,mutate_tiingo=True)
    for provider in ['tiingo','yahoo']:
        assert 'KNOWN_ACTION_CASH_CONFLICT:2011-12-27' in result[provider]


def test_no_cash_adjudication_is_completed_but_does_not_accept_prices(store):
    report={'assets':[{'symbol':'QQQ','details':[{'date':'2010-06-25','flags':['cash'],
        'tiingo_cash':0,'yahoo_cash':0.089,'tiingo_split':1,'yahoo_split':1}]}]}
    result=annotate_us(copy.deepcopy(report),store,ROOT)
    assert result['assets'][0]['details'][0]['work_status']=='CASH_ADJUDICATION_COMPLETED'
    assert result['new_or_changed_issues'][0]['status']=='CASH_REFERENCE_CONFIRMED_PRICE_GATE_REMAINS'
    with pytest.raises(DataNotAccepted): store.accepted('yahoo','QQQ','2026-10-23')
    assert not annotate_us(copy.deepcopy(report),store,ROOT)['new_or_changed_issues']

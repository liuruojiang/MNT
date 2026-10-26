"""Explicit synthetic scheduler-evidence counterexamples; no market requests."""
import copy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from verify_data_source_daily import verify

START=datetime(2026,10,26,9,40,tzinfo=timezone.utc)


def reports():
    first={'run_id':'first','status':'REVIEW_REQUIRED','purpose':'research_only','cutoffs':{'US':'2026-10-23','CN':'2026-10-26'},'US':{'assets':[{}]*22,'collection':{'requests':[],'provider_stops':{}}},'CN':{'assets':[{}]*15,'requests':15},'projects':[{'entrypoint_scope':'MATCHES_REVIEWED_ENTRYPOINTS'}]*6,'new_or_changed_issues':[],'production_changed':False,'poe_deployed':False,'strategy_backtests_run':0}
    second=copy.deepcopy(first)
    second['run_id']='second'; second['CN']['requests']=0
    return first,second


def run(first,second,**kw):
    return verify(first,second,not_before=START,first_started=START,repeat_started=START+timedelta(minutes=1),receipts=[{'status':200}]*15,live_snapshots=[],**kw)


def test_runtime_success_does_not_claim_a_real_scheduler_trigger():
    result=run(*reports())
    assert result['status']=='RUNTIME_CHECKS_PASS'
    assert result['scheduler_execution_verified_by_this_script'] is False
    assert result['data_quality_status']=='REVIEW_REQUIRED' and not result['production_approved']


def test_same_run_or_old_cutoff_cannot_be_accepted():
    first,second=reports(); second['run_id']=first['run_id']
    assert run(first,second)['status']=='FAILED'
    first,second=reports(); second['cutoffs']['CN']='2026-10-23'
    assert run(first,second)['status']=='FAILED'


def test_repeat_requests_alerts_or_transport_failure_reject_operational_acceptance():
    for key in ['network','alert','failure']:
        first,second=reports()
        if key=='network': second['CN']['requests']=1
        if key=='alert': second['new_or_changed_issues']=[{'known_issue_repeated':True}]
        if key=='failure': first['US']['collection']['provider_stops']={'tiingo':{'status':429}}
        assert run(first,second)['status']=='FAILED'


def test_wrong_gate_or_old_snapshot_is_rejected():
    first,second=reports()
    bad={'cutoff':'2026-10-23','run_id':'first','gate_run':'second','gate_status':'BLOCKED'}
    result=verify(first,second,not_before=START,first_started=START,repeat_started=START+timedelta(minutes=1),receipts=[],live_snapshots=[bad])
    assert result['status']=='FAILED'


def test_project_version_change_must_remain_explicitly_blocked():
    first,second=reports()
    for r in [first,second]:r['projects'][0]={'project_id':'changed','entrypoint_scope':'BLOCKED_SOURCE_SCOPE','status':'BLOCKED_SOURCE_SCOPE'}
    result=run(first,second)
    assert result['status']=='RUNTIME_CHECKS_PASS' and result['blocked_project_contracts']==['changed']
    second['projects'][0]['status']='REVIEW_REQUIRED'
    assert run(first,second)['status']=='FAILED'

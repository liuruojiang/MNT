"""Verify runner evidence; scheduler origin must be established by the app run."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3

from source_audit.calendar import confirmed_cutoff
from source_audit.config import DEFAULT_ROOT,load


def verify(first,repeat,*,not_before,first_started,repeat_started,receipts,live_snapshots):
    expected={k:confirmed_cutoff(m,first_started) for k,m in [('US','XNYS'),('CN','XSHG')]}
    def complete(r):
        return (r.get('status')=='REVIEW_REQUIRED' and r.get('purpose')=='research_only'
                and len(r.get('US',{}).get('assets',[]))==22 and len((r.get('CN') or {}).get('assets',[]))==15
                and len(r.get('projects',[]))==6 and all(p.get('entrypoint_scope') in {'MATCHES_REVIEWED_ENTRYPOINTS','BLOCKED_SOURCE_SCOPE'} and (p.get('entrypoint_scope')!='BLOCKED_SOURCE_SCOPE' or p.get('status')=='BLOCKED_SOURCE_SCOPE') for p in r['projects']))
    checks={
        'distinct_completed_runs':complete(first) and complete(repeat) and first['run_id']!=repeat['run_id'],
        'execution_after_checkpoint':first_started>=not_before and repeat_started>=first_started,
        'independent_market_cutoffs':first.get('cutoffs')==expected and repeat.get('cutoffs')==expected,
        'provider_transport_not_failed':not first.get('US',{}).get('collection',{}).get('provider_stops') and not repeat.get('US',{}).get('collection',{}).get('provider_stops') and all(r.get('status')==200 and not r.get('error_type') for r in receipts),
        'request_receipts_complete':len(receipts)==sum(len(r.get('US',{}).get('collection',{}).get('requests',[]))+(r.get('CN') or {}).get('requests',0) for r in [first,repeat]),
        'same_cutoff_repeat_no_network':not repeat.get('US',{}).get('collection',{}).get('requests') and (repeat.get('CN') or {}).get('requests')==0,
        'unchanged_problems_no_repeat_alert':repeat.get('new_or_changed_issues')==[],
        'CN_gates_stable_on_same_cutoff_repeat':[{k:a.get(k) for k in ['code','gate','amount_gate']} for a in (first.get('CN') or {}).get('assets',[])]==[{k:a.get(k) for k in ['code','gate','amount_gate']} for a in (repeat.get('CN') or {}).get('assets',[])],
        'production_and_parameters_unchanged':all(r.get('production_changed') is False and r.get('poe_deployed') is False and r.get('strategy_backtests_run')==0 for r in [first,repeat]),
        'no_stale_or_quarantined_snapshot':all(s['cutoff']==expected['US'] and s['run_id']==repeat['run_id'] and s['gate_run']==repeat['run_id'] and s['gate_status']=='QUALIFIED_FOR_RESEARCH' for s in live_snapshots),
    }
    return {'status':'RUNTIME_CHECKS_PASS' if all(checks.values()) else 'FAILED','checks':checks,
            'first_run_id':first.get('run_id'),'repeat_run_id':repeat.get('run_id'),'cutoffs':expected,
            'scheduler_execution_verified_by_this_script':False,
            'scheduler_evidence_required':'An actual app-scheduled thread execution; CLI/manual execution cannot certify a clock trigger',
            'blocked_project_contracts':[p.get('project_id') for p in repeat.get('projects',[]) if p.get('entrypoint_scope')=='BLOCKED_SOURCE_SCOPE'],
            'data_quality_status':'REVIEW_REQUIRED','production_approved':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=DEFAULT_ROOT/'config.json')
    p.add_argument('--first-report',type=Path,required=True)
    p.add_argument('--repeat-report',type=Path,required=True)
    p.add_argument('--not-before',required=True,help='Timezone-aware ISO timestamp captured before the first run')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    before=datetime.fromisoformat(a.not_before)
    if before.tzinfo is None: raise ValueError('Timezone-aware checkpoint required')
    root=Path(load(a.config)['store_root'])
    db=sqlite3.connect((root/'catalog.sqlite').as_uri()+'?mode=ro',uri=True)
    def read(path):return json.loads(path.read_text(encoding='utf-8'))
    try:
        first,repeat=read(a.first_report),read(a.repeat_report)
        def started(report):
            row=db.execute('SELECT started,finished FROM runs WHERE id=?',(report['run_id'],)).fetchone()
            if not row or not row[1]: raise ValueError('Run is not completed in the catalog')
            return datetime.fromisoformat(row[0])
        snapshots=[dict(zip(['cutoff','run_id','gate_status','gate_run'],row)) for row in db.execute('SELECT s.cutoff,s.run_id,g.status,g.run_id FROM snapshots s JOIN gates g ON s.provider=g.provider AND s.symbol=g.symbol')]
        receipts=[]
        for report in [first,repeat]:
            receipts+=report.get('US',{}).get('collection',{}).get('requests',[])
            cn=report.get('CN') or {}
            manifest=Path(cn['artifact_path']).with_name('manifest.json')
            receipts+=read(manifest)['receipts']
        result=verify(first,repeat,not_before=before,first_started=started(first),repeat_started=started(repeat),receipts=receipts,live_snapshots=snapshots)
        result['checked_at_utc']=datetime.now(timezone.utc).isoformat()
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status']=='RUNTIME_CHECKS_PASS' else 2
    finally:db.close()


if __name__=='__main__':raise SystemExit(main())

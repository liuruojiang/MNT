"""Completed work is evidence, not a new daily task or automatic data approval."""
import json
from pathlib import Path


def completed_work(repo):
    repo = Path(repo)
    return [
        {'work_id':'KMLM_20221228','status':'COMPLETED_DO_NOT_REPEAT','symbol':'KMLM','date':'2022-12-28',
         'verified_cash':4.0377,'vendor_wrong':'yahoo','evidence':str(repo/'docs/v80_independent_review_20261025.md'),
         'scope':'Independent adjudication, idempotent/cache repair and original full replays already completed; no new strategy run'},
        {'work_id':'DBMF_20260929','status':'COMPLETED_DO_NOT_REPEAT','symbol':'DBMF','date':'2026-09-29',
         'verified_cash':0.1456,'vendor_wrong':'yahoo','evidence':str(repo/'research/data_quality/20261025_dbmf/独立来源裁定.json'),
         'scope':'Independent adjudication, isolated repair and full V1.6/V8.0 replays completed; candidate remains unapplied'},
        {'work_id':'SUBA_CYB_AMOUNT_20181214','status':'COMPLETED_DO_NOT_REPEAT','symbol':'399006','date':'2018-12-14',
         'evidence':str(repo/'docs/v80_independent_review_20261025.md'),
         'scope':'CNI constituent-aggregate turnover gap already adjudicated and repaired; do not substitute whole-market Wind amount'},
    ]


def load_additional(repo):
    path = Path(repo)/'research/data_quality/20261026_source_service/us_adjudications.json'
    if not path.exists(): return []
    data = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(data,list): return data
    return data.get('cases',data.get('adjudications',data.get('events',data.get('items',[]))))


def annotate_us(report, store, repo):
    completed = completed_work(repo)
    by_key = {(r['symbol'],r['date']):r for r in completed if 'verified_cash' in r}
    additional = load_additional(repo)
    additional_by_key = {(r['symbol'],r.get('ex_date',r.get('date'))):r for r in additional}
    alerts = []
    for item in report['assets']:
        for event in item.get('details',[]):
            if not any(f in event['flags'] for f in ['cash','split','unexplained_adjustment','capital_gains_review']): continue
            key = (item['symbol'],event['date'])
            known = by_key.get(key)
            adjudication = additional_by_key.get(key)
            evidence = {'symbol':key[0],'date':key[1], 'flags':sorted(set(event['flags']) & {'cash','split','unexplained_adjustment','capital_gains_review'}),
                        'tiingo_cash':event['tiingo_cash'],'yahoo_cash':event['yahoo_cash'],
                        'tiingo_split':event['tiingo_split'],'yahoo_split':event['yahoo_split']}
            issue_id = 'US:' + key[0] + ':' + key[1]
            state = 'KNOWN_ADJUDICATED_UPSTREAM_CONFLICT' if known else ('CASH_REFERENCE_CONFIRMED_PRICE_GATE_REMAINS' if adjudication and adjudication.get('status')=='CONFIRMED_CASH_EVENT' else 'UNRESOLVED_DATA_CONFLICT')
            changed = store.issue(issue_id,state,evidence)
            event['work_status'] = 'COMPLETED_DO_NOT_REPEAT' if known else ('CASH_ADJUDICATION_COMPLETED' if adjudication and adjudication.get('status')=='CONFIRMED_CASH_EVENT' else 'UNRESOLVED_EVIDENCE_BLOCKED')
            if adjudication: event['adjudication_id']=adjudication['id']
            if known:
                event['existing_evidence'] = known['evidence']
            if changed and not known:
                alerts.append({'issue_id':issue_id,'status':state,'evidence':evidence})
    report['completed_work_reused'] = completed
    report['additional_adjudications'] = additional
    report['new_or_changed_issues'] = alerts
    report['no_strategy_backtests_repeated'] = True
    return report

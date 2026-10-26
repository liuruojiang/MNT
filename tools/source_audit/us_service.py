"""Incremental research collection over immutable observations; no strategy execution."""
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from urllib.parse import urlencode
import os

from .calendar import confirmed_cutoff, sessions
from .registry import annotate_us, completed_work, load_additional, CASH_REFERENCE_STATUSES
from .store import DataNotAccepted
from .transport import decrypt_dpapi, fetch, sha256
from .compare import tiingo_rows, yahoo_rows, split_comparison_basis


def import_legacy(store, path):
    path = Path(path)
    snapshot = json.loads((path/'snapshot.json').read_text(encoding='utf-8'))
    imported = 0
    for name, receipt in snapshot['receipts'].items():
        provider = 'tiingo' if name.startswith('tiingo_') else 'yahoo'
        symbol = name[len(provider)+1:]
        kind = 'metadata' if symbol.endswith('_metadata') else 'prices'
        if kind == 'metadata': symbol = symbol[:-9]
        body = (path/'raw'/(name+'.json')).read_bytes()
        store.observe(provider,symbol,kind,snapshot['cutoff'],body,receipt,imported_from=path)
        imported += 1
    return {'observations_imported_or_already_present':imported,'cutoff':snapshot['cutoff'],
            'new_api_requests':0,'strategy_replays':0}


def needs_full_history(old, delta):
    """Detect a new action or repriced overlap before any incremental merge."""
    indexed = {row['date'][:10]:row for row in old}
    for row in delta:
        prev = indexed.get(row['date'][:10])
        if prev is None:
            if row.get('divCash',0) or row.get('splitFactor',1) != 1: return True
        else:
            if row.get('divCash') != prev.get('divCash') or row.get('splitFactor') != prev.get('splitFactor'): return True
            for key in ('adjOpen','adjClose'):
                a,b = row.get(key),prev.get(key)
                if a is None or b is None or not math.isfinite(float(a)) or not math.isfinite(float(b)): return True
                if abs(float(a)-float(b)) > max(1e-9,abs(float(b))*1e-7): return True
    return False


def merge_tiingo(old, delta, cutoff):
    if not isinstance(delta,list) or not delta: raise DataNotAccepted('Empty increment')
    dates = [r['date'][:10] for r in delta]
    if dates != sorted(set(dates)) or any(d > cutoff for d in dates):
        raise DataNotAccepted('Invalid incremental date sequence')
    if needs_full_history(old,delta): raise DataNotAccepted('Action/revision requires full history before merging')
    merged = {r['date'][:10]:r for r in old}
    merged.update({r['date'][:10]:r for r in delta})
    return [merged[d] for d in sorted(merged) if d <= cutoff]


def refresh(store,config,output,cutoff,*,probe_only=False):
    """One bounded network cycle; failures quarantine reads, never reuse an old PASS."""
    profiles = json.loads((Path(__file__).parent/'projects.json').read_text())
    symbols = sorted(set().union(*(p['symbols'] for p in profiles['projects'].values()))-{'BTC-USD'})
    requests, stopped, derivations = [],{},[]
    now = datetime.now(timezone.utc)
    token = None
    try: token = decrypt_dpapi(config['credentials']['tiingo'])
    except Exception as exc: stopped['tiingo']={'error_type':type(exc).__name__,'reason':'Existing encrypted credential cannot be read'}

    def request(provider,symbol,kind,url):
        if provider in stopped: return None,None
        try:
            store.reserve_request(provider,config['local_hourly_budgets'][provider])
        except DataNotAccepted:
            stopped[provider]={'error_type':'LocalBudgetExhausted'}
            store.quarantine_provider(provider,'Local budget exhausted during fresh validation',output.name)
            return None,None
        file = output/(provider+'_'+symbol+'_'+kind+'_'+str(len(requests))+'.json')
        receipt,payload = fetch(url,file,token if provider=='tiingo' else None)
        requests.append({'provider':provider,'symbol':symbol,'kind':kind,**receipt})
        if payload is None:
            stopped[provider]={'status':receipt.get('status'),'error_type':receipt.get('error_type','HTTPFailure')}
            store.quarantine_provider(provider,'Fresh request failed; old snapshots quarantined',output.name)
            return receipt,None
        store.observe(provider,symbol,kind,cutoff,file.read_bytes(),receipt)
        return receipt,payload

    if probe_only:
        # Probe is separately catalogued, so a one-row response cannot replace
        # the full-history head or clear an existing quality quarantine.
        request('tiingo','SPY','auth_probe','https://api.tiingo.com/tiingo/daily/SPY/prices?'+urlencode({'startDate':cutoff,'endDate':cutoff}))
        return {'requests':requests,'provider_stops':stopped,'derivations':[],'mode':'AUTH_PROBE_ONLY'}

    start = profiles['history_start']
    for symbol in symbols:
        current = store.head('tiingo',symbol)
        last = datetime.fromisoformat(current['receipt']['retrieved_at_utc']) if current and current['receipt'].get('retrieved_at_utc') else None
        due = not current or current['cutoff'] != cutoff or not last or (now-last).total_seconds() >= config['same_cutoff_remote_refresh_hours']*3600
        if due and 'tiingo' not in stopped:
            old = current['payload'] if current else []
            since = start if not current else (datetime.fromisoformat(current['cutoff'])-timedelta(days=config['incremental_overlap_calendar_days'])).date().isoformat()
            base = 'https://api.tiingo.com/tiingo/daily/'+symbol+'/prices?'
            full_at = current['receipt'].get('last_full_retrieved_at_utc',current['receipt'].get('retrieved_at_utc')) if current else None
            periodic = bool(full_at and (now-datetime.fromisoformat(full_at)).days >= config['full_revision_check_days'])
            full_first = not current or periodic
            receipt,delta = request('tiingo',symbol,'full_refresh' if full_first else 'delta',base+urlencode({'startDate':start if full_first else since,'endDate':cutoff,'resampleFreq':'daily'}))
            if delta is not None:
                # Archive freshness is measured by the last actual FULL request,
                # not by the date of a locally derived merged observation.
                if full_first or needs_full_history(old,delta):
                    full_receipt,full = (receipt,delta) if full_first else request('tiingo',symbol,'full_refresh',base+urlencode({'startDate':start,'endDate':cutoff,'resampleFreq':'daily'}))
                    if full is not None:
                        body = json.dumps(full,separators=(',',':')).encode()
                        proof = {**full_receipt,'sha256':sha256(body),'derivation':'lossless JSON serialization of full response','parent_response_sha256':full_receipt['sha256'],
                                 'last_full_retrieved_at_utc':full_receipt['retrieved_at_utc']}
                        store.observe('tiingo',symbol,'prices',cutoff,body,proof)
                else:
                    merged = merge_tiingo(old,delta,cutoff)
                    body = json.dumps(merged,separators=(',',':')).encode()
                    proof = {**receipt,'sha256':sha256(body),'derivation':'unchanged historical prefix + validated non-action overlap/delta',
                             'parent_response_sha256':receipt['sha256'],'prior_full_sha256':current['sha256'],'last_full_retrieved_at_utc':full_at}
                    store.observe('tiingo',symbol,'prices',cutoff,body,proof)
                    derivations.append({'symbol':symbol,'kind':'incremental_merge','rows':len(merged)})
        current_y = store.head('yahoo',symbol)
        last_y = datetime.fromisoformat(current_y['receipt']['retrieved_at_utc']) if current_y and current_y['receipt'].get('retrieved_at_utc') else None
        due_y = not current_y or current_y['cutoff'] != cutoff or not last_y or (now-last_y).total_seconds() >= config['same_cutoff_remote_refresh_hours']*3600
        if due_y and 'yahoo' not in stopped:
            # One native Yahoo request per ticker refreshes its full adjustment
            # basis, including upstream retrospective fixes outside the overlap.
            url = 'https://query1.finance.yahoo.com/v8/finance/chart/'+symbol+'?'+urlencode({
                'period1':int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp()),
                'period2':int((datetime.fromisoformat(cutoff).replace(tzinfo=timezone.utc)+timedelta(days=1)).timestamp()),
                'interval':'1d','includeAdjustedClose':'true','events':'div,splits,capitalGains'})
            request('yahoo',symbol,'prices',url)
    token = None
    return {'requests':requests,'provider_stops':stopped,'derivations':derivations,'mode':'INCREMENTAL'}


def known_action_checks(store, repo, symbol, cutoff):
    references = [r for r in completed_work(repo) if r.get('symbol')==symbol and 'verified_cash' in r]
    references += [{'symbol':r['symbol'],'date':r['ex_date'],'verified_cash':float(r['resolution']['cash_usd_per_share'])}
                   for r in load_additional(repo) if r.get('symbol')==symbol and r.get('status') in CASH_REFERENCE_STATUSES]
    if not references: return {'tiingo':[],'yahoo':[]}
    th,yh,mh = store.head('tiingo',symbol),store.head('yahoo',symbol),store.head('tiingo',symbol,'metadata')
    if not all([th,yh,mh]): return {'tiingo':['KNOWN_ACTION_ANCHORS_UNAVAILABLE'],'yahoo':['KNOWN_ACTION_ANCHORS_UNAVAILABLE']}
    raw_t = tiingo_rows(th['payload'],symbol,'2003-01-01',cutoff,mh['payload'])
    t = split_comparison_basis(raw_t)
    y = yahoo_rows(yh['payload'],symbol,'2003-01-01',cutoff)
    result = {'tiingo':[],'yahoo':[]}
    for ref in references:
        day = ref['date']
        if day > cutoff: continue
        for provider,rows in [('tiingo',t),('yahoo',y)]:
            prior = sessions('XNYS',datetime.fromisoformat(day)-timedelta(days=15),day)
            prev = str(prior[-2].date()) if len(prior)>1 else None
            if day not in rows or prev not in rows or day not in raw_t:
                result[provider].append('KNOWN_ACTION_MISSING:'+day)
                continue
            # Reference is per ex-date share. Convert only for subsequent
            # verified splits so future splits cannot falsify an old cash oracle.
            basis_scale = t[day]['close']/raw_t[day]['close']
            expected = [ref['verified_cash']*basis_scale]
            if symbol=='KMLM' and day=='2022-12-28': expected.append(4.038*basis_scale)
            a,b = rows[prev],rows[day]
            if provider=='tiingo':
                implied = a['close']*b['adjClose']/a['adjClose']-b['close']
            else:
                implied = a['close']*(1-(a['adjClose']/a['close'])/(b['adjClose']/b['close']))
            if min(abs(implied-value) for value in expected)>max(5e-5*basis_scale,1e-7):
                result[provider].append('KNOWN_ACTION_FACTOR_CONFLICT:'+day)
            if min(abs(b['divCash']-value) for value in expected)>max(0.001*basis_scale,abs(expected[0])*0.001):
                result[provider].append('KNOWN_ACTION_CASH_CONFLICT:'+day)
    return result


def materialize(store,output,cutoff):
    profiles = json.loads((Path(__file__).parent/'projects.json').read_text())
    symbols = sorted(set().union(*(p['symbols'] for p in profiles['projects'].values()))-{'BTC-USD'})
    receipts = {}
    raw = output/'raw'
    raw.mkdir(exist_ok=True)
    for provider in ('tiingo','yahoo'):
        for symbol in symbols:
            for kind in (['metadata','prices'] if provider=='tiingo' else ['prices']):
                head = store.head(provider,symbol,kind)
                name = provider+'_'+symbol+('_metadata' if kind=='metadata' else '')
                if not head:
                    receipts[name]={'error_type':'NoArchivedObservation'}
                    continue
                receipts[name]=head['receipt']
                source = store.object_path(head['sha256'])
                target = raw/(name+'.json')
                try: os.link(source,target)
                except OSError:
                    with target.open('xb') as handle: handle.write(store.read_object(head['sha256']))
    return profiles,{'mode':'ARCHIVE_REUSE_NO_BACKTEST','cutoff':cutoff,'receipts':receipts}


def assess(store,output,cutoff,scope,repo,run_id,network=None):
    from audit_us_sources import build_report
    profiles,snapshot = materialize(store,output,cutoff)
    calendar = [str(d.date()) for d in sessions('XNYS',profiles['history_start'],cutoff)]
    report = build_report(profiles,snapshot,output,scope,calendar_override=calendar)
    report['calendar']={'market':'XNYS','basis':'exchange_rules_independent_of_both_price_sources','required_end':cutoff}
    report['collection'] = network or {'mode':'ARCHIVE_REUSE','requests':[],'provider_stops':{}}
    failed_providers = set(report['collection'].get('provider_stops',{}))
    annotate_us(report,store,repo)
    qualified = []
    for item in report['assets']:
        symbol = item['symbol']
        bad_adjusted = any('adjusted_return' in d['flags'] and 'action_basis' not in d['flags'] for d in item.get('details',[]))
        price_errors = set(item.get('issues',[]))-{'VOLUME_REVIEW','ADJUSTED_RETURN_DIFFERENCE'}
        allowed = not price_errors and not bad_adjusted
        try: oracle = known_action_checks(store,repo,symbol,cutoff)
        except Exception: oracle = {'tiingo':['KNOWN_ACTION_VALIDATION_FAILED'],'yahoo':['KNOWN_ACTION_VALIDATION_FAILED']}
        item['independent_known_action_checks']=oracle
        # Baseline once, then alert on changed price/action gates (including an
        # upstream correction of a previously completed case). No replay follows.
        issue_id='US_GATE:'+symbol
        prior=store.db.execute('SELECT 1 FROM known_issues WHERE issue_id=?',(issue_id,)).fetchone()
        evidence={'symbol':symbol,'price_errors':sorted(price_errors),'unexplained_return':bad_adjusted,
                  'known_action_checks':oracle,'provider_failures':sorted(failed_providers),
                  'action_conflicts':[{'date':d['date'],'flags':sorted(set(d['flags']) & {'cash','split','unexplained_adjustment','capital_gains_review'}),
                      'tiingo_cash':d.get('tiingo_cash'),'yahoo_cash':d.get('yahoo_cash')} for d in item.get('details',[])
                      if set(d['flags']) & {'cash','split','unexplained_adjustment','capital_gains_review'}]}
        changed=store.issue(issue_id,'OBSERVED_GATE',evidence)
        if prior and changed:
            report['new_or_changed_issues'].append({'issue_id':issue_id,'status':'PRICE_OR_ACTION_GATE_CHANGED','evidence':evidence,
                                                   'strategy_replay_requested':False})
        for provider in ('tiingo','yahoo'):
            head = store.head(provider,symbol)
            ok = allowed and not oracle[provider] and provider not in failed_providers and head is not None and head['cutoff']==cutoff
            status = 'QUALIFIED_FOR_RESEARCH' if ok else 'BLOCKED'
            store.gate(provider,symbol,status,list(price_errors)+oracle[provider]+(['UNEXPLAINED_RETURN_BASIS'] if bad_adjusted else [])+(['FRESH_PROVIDER_FAILURE'] if provider in failed_providers else []),run_id)
            if ok:
                meta=store.head('tiingo',symbol,'metadata')['payload']
                parsed=tiingo_rows(head['payload'],symbol,profiles['history_start'],cutoff,meta) if provider=='tiingo' else yahoo_rows(head['payload'],symbol,profiles['history_start'],cutoff)
                fields=['open','high','low','close','adjOpen','adjClose','divCash','splitFactor']
                volume_accepted=item.get('counts',{}).get('volume',0)==0
                if volume_accepted: fields.append('volume')
                payload=[{'date':d,**{k:row[k] for k in fields}} for d,row in parsed.items()]
                store.publish(provider,symbol,cutoff,payload,{'adjustment':'provider_native_total_return','volume_cross_source_accepted':volume_accepted,
                    'fields_qualified':fields,'raw_ohlc_basis':'exdate_share' if provider=='tiingo' else 'latest_share_split_adjusted',
                    'calendar':'XNYS','currency':'USD','raw_response_sha256':head['sha256'],'retrieved_at_utc':head['receipt'].get('retrieved_at_utc')},run_id)
                qualified.append({'provider':provider,'symbol':symbol,'purpose':'research_only'})
    report['qualified_research_snapshots'] = qualified
    report['production_approved']=False
    return report

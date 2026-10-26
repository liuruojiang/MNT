"""Explicit research-only consumer API; formal strategies remain unchanged."""
import hashlib
import json
from pathlib import Path

from .store import DataNotAccepted


def requirements():
    return json.loads((Path(__file__).parent/'project_requirements.json').read_text(encoding='utf-8'))


def project_scope(project_id):
    project = next((p for p in requirements()['projects'] if p['project_id']==project_id),None)
    if project is None: raise DataNotAccepted('Unknown project')
    for entry in project['entrypoints']:
        path = Path(entry['path'])
        if not path.is_file() or hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=entry['sha256_lf']:
            raise DataNotAccepted('Project entrypoint changed; refresh the reviewed field contract')
    return project


def read_asset(store, project_id, provider, symbol, cutoff, *, purpose='research_only', fields=None):
    project = project_scope(project_id)
    # Only a symbol declared by the reviewed project may be requested. Conceptual
    # index names and API identifiers are not guessed or automatically converted.
    declared = set()
    for requirement in project['requirements']:
        for value in requirement.get('instruments',[]):
            if isinstance(value,str): declared.add(value)
            elif isinstance(value,dict):
                declared.update(v for k,v in value.items() if k in {'symbol','code','ticker'} and isinstance(v,str))
    if symbol not in declared:
        raise DataNotAccepted('Symbol is outside this project field contract')
    snapshot=store.accepted(provider,symbol,cutoff,purpose=purpose)
    allowed=set(snapshot['metadata'].get('fields_qualified',[]))
    requested=set(fields) if fields is not None else allowed
    if not requested or not requested.issubset(allowed):
        raise DataNotAccepted('Requested fields were not qualified; volume/amount cannot be inferred from price acceptance')
    snapshot['records']=[{k:v for k,v in row.items() if k=='date' or k in requested} for row in snapshot['records']]
    return snapshot


def readiness(us_report, cn_report=None, field_probes=None):
    results=[]
    profiles = json.loads((Path(__file__).parent/'projects.json').read_text())['projects']
    for project in requirements()['projects']:
        try:
            project_scope(project['project_id'])
            scope='MATCHES_REVIEWED_ENTRYPOINTS'
        except DataNotAccepted:
            scope='BLOCKED_SOURCE_SCOPE'
        name = project.get('name',project.get('display_name',project['project_id']))
        symbols = next((p['symbols'] for key,p in profiles.items() if key in name),[])
        observed = [a for a in us_report.get('assets',[]) if a['symbol'] in symbols]
        results.append({'project_id':project['project_id'],'name':name,'entrypoint_scope':scope,
                        'status':'REVIEW_REQUIRED' if scope=='MATCHES_REVIEWED_ENTRYPOINTS' else scope,
                        'requirements':project['requirements'],'known_gaps':project.get('gaps',[]),
                        'US_ETF_observations':len(observed),'CN_report_available':bool(cn_report),
                        'field_probe_evidence_available':bool(field_probes),
                        'actual_field_probe_results':[{k:p.get(k) for k in ['probe','status','fields_verified','permission_denied_observed','validation']} for p in (field_probes or {}).get('probes',[])],
                        'production_approved':False})
    return results

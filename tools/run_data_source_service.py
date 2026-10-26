"""Shared Tiingo/Wind shadow service. No strategy invocation or production writes."""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys

import audit_us_sources as legacy
from source_audit import adapters
from source_audit.calendar import confirmed_cutoff, document, sessions
from source_audit.config import DEFAULT_ROOT, load
from source_audit.registry import completed_work
from source_audit.store import Store,service_lock,ServiceAlreadyRunning
from source_audit.us_service import import_legacy, refresh, assess

REPO = Path(__file__).resolve().parents[1]


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str),encoding='utf-8')


def wind_archive(root, legacy_path):
    destination = root/'wind_archive'
    destination.mkdir(exist_ok=True)
    marker=destination/'_bootstrap_manifest.json'
    if marker.exists():
        manifest=json.loads(marker.read_text(encoding='utf-8'))
        for name,digest in manifest['files'].items():
            if Path(name).name!=name or hashlib.sha256((destination/name).read_bytes()).hexdigest()!=digest:
                raise ValueError('Pinned Wind bootstrap archive changed')
        return destination
    # Pin the original successful parsed response, receipt, and response text.
    # A copied filename is never silently overwritten by a new source response.
    for source in Path(legacy_path).iterdir():
        if source.is_file() and source.suffix in {'.json','.txt'}:
            target=destination/source.name
            if not target.exists(): shutil.copyfile(source,target)
            elif target.read_bytes()!=source.read_bytes(): raise ValueError('Existing Wind archive differs from bootstrap source')
    write(marker,{'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.iterdir() if p.is_file()}})
    return destination


def cn_run(config, output, mode, cutoff):
    if mode=='skip': return None
    root=Path(config['store_root'])
    archive=wind_archive(root,config['legacy_wind_archive'])
    calendar=root/'calendars'/'xshg_2026_sessions.json'
    command=[sys.executable,'-B',str(REPO/'tools/audit_cn_sources.py'),'--credential',config['credentials']['wind'],
             '--output',str(output/'cn'),'--offline-archive',str(archive),'--mode',mode,'--cutoff',cutoff,
             '--start','2026-01-01','--sessions',str(calendar),'--max-requests',str(config['local_hourly_budgets']['wind'])]
    command += ['--short-index',str(root/'wind_short_index.json'),'--long-index',str(root/'wind_long_index.json')]
    command += ['--budget-store',str(root)]
    proc=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1500)
    (output/'cn_runner.log').write_text(proc.stdout+'\n'+proc.stderr,encoding='utf-8')
    runs=sorted((output/'cn').glob('*/report.json'))
    if not runs: return {'status':'FAILED','error':'CN runner produced no report','exit_code':proc.returncode}
    report=json.loads(runs[-1].read_text(encoding='utf-8'))
    report['artifact_path']=str(runs[-1])
    report['exit_code']=proc.returncode
    return report


def crypto_boundary(config):
    # Use already verified measurements, never fetch or splice a second crypto
    # feed into production because it shares an ETF-style daily field name.
    return {'status':'RESEARCH_ONLY_NOT_INTERCHANGEABLE','market_calendar':'UTC 24/7',
        'volume_unit':'Provider-specific aggregation; not assumed interchangeable with Yahoo',
        'existing_work_reused':'2026-10-25 authenticated crypto comparison',
        'action':'Keep existing formal BTC provider; unsupported fields stay unavailable',
        'production_approved':False}


def render(report, output):
    counts={p:sum(x['provider']==p for x in report['US'].get('qualified_research_snapshots',[])) for p in ('tiingo','yahoo')}
    rows=''
    for p in report['projects']:
        rows+='<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in [p['name'],p['status'],p['entrypoint_scope'],len(p['requirements'])])+'</tr>'
    complete=''.join('<li>'+html.escape(w['work_id'])+'：已完成，复用证据，不重复取数或回测。</li>' for w in report['completed_work_reused'])
    cn=report.get('CN') or {}
    cgates={v:sum(a.get('gate')==v for a in cn.get('assets',[])) for v in ('BLOCKED','INTERVAL_COHERENT_ONLY','INDEPENDENT_OVERLAP_CHECKED')}
    probes=report.get('field_probes') or {}
    probe_text='；'.join(str(p.get('probe'))+'：'+str(p.get('status')) for p in probes.get('probes',[]))
    text=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>策略共享数据源服务</title>
<style>body{{font:16px/1.7 system-ui;max-width:1200px;margin:32px auto;padding:0 20px;color:#1a3441;background:#f5f8fa}}table{{border-collapse:collapse;background:white;width:100%}}td,th{{padding:10px;border:1px solid #cbd8df}}aside{{padding:18px;background:#fff0ca}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}a{{color:#08788e}}</style>
<h1>共享数据源服务 · 本轮只读核验</h1>
<aside>生产、策略参数与 Poe 未改。该服务提供归档、质量校验和研究快照；未通过的数据不会进入研究快照接口，更不会自动替换正式数据源。</aside>
<p>本轮：{report['run_id']}；美国已确认交易日：{report['cutoffs']['US']}；中国已确认交易日：{report['cutoffs']['CN']}。美股日历独立于两家行情源；中国独立日历目前覆盖 2026 年。</p>
<h2>已完成事项直接复用</h2><ul>{complete}</ul>
<p>本轮新增网络请求：美股 {len(report['US']['collection'].get('requests',[]))}；万得 {cn.get('requests',0)}。完整历史按内容哈希保存，重复运行不复制同一份原始数据；有公司行动或历史复权变化时要求全历史刷新，不能拼接新旧复权。</p>
<h2>研究快照与项目覆盖</h2><p>通过价格字段核验的研究快照：Tiingo {counts['tiingo']}，Yahoo {counts['yahoo']}。这是逐资产研究资格，成交量、整套策略和生产资格单列，不能据此全源晋级。</p>
<table><tr><th>项目</th><th>完整项目状态</th><th>入口版本</th><th>字段组数</th></tr>{rows}</table>
<p>万得区间结果：{html.escape(str(cgates))}。历史成交额统计口径、PIT-ST/股本/退市与期货期权字段按实际返回判定；HTTP 200 或能发现工具都不等于字段可用。BTC 保留 UTC 日历和独立成交量口径。</p>
<p>实际字段探针：{html.escape(probe_text)}。两次缩小到单字段的追问仍未取得合格结果；没有观察到权限拒绝，不能据此断定需要升级账号。MO 请求返回了 IO 合约及另一数据日，已阻断。基金接口声明 aftype=0 为前复权，但尚未完成历史序列的独立口径核对。</p>
<h2>新增裁定与需要处理的差异</h2><p>其余 ETF 公司行动已完成现金参考裁定 {sum(x.get('status')=='CONFIRMED_CASH_EVENT' for x in report['US'].get('additional_adjudications',[]))} 条；没有合格证据的条目保留阻断。新事件的因子/影响报告在交付目录独立提供；DBMF 不再重新分析。</p>
<p>新增或改变的问题 {len(report['new_or_changed_issues'])} 项；已知问题不变时每日任务保持静默。</p><details><summary>查看本轮变化</summary><pre>{html.escape(json.dumps(report['new_or_changed_issues'],ensure_ascii=False,indent=2))}</pre></details>
<p><a href="report.json">完整机器报告</a> · <a href="US_report.json">美股逐日检查</a> · <a href="project_readiness.json">逐项目字段要求</a></p>
<p>所有冻结证据保留原采集时间。接口失败或额度不足将隔离该源并拒绝旧快照；不会将旧缓存包装成正常信号。未开展参数扫描或已有策略回测。</p></html>'''
    (output/'report.html').write_text(text,encoding='utf-8')


def _run_locked(args):
    config=load(args.config)
    root=Path(config['store_root'])
    store=Store(root)
    run_id=store.begin_run()
    output=root/'runs'/run_id
    output.mkdir(parents=True)
    scope_before=legacy.source_scope(json.loads(legacy.PROFILE.read_text()),REPO.parent)
    try:
        if store.head('tiingo','SPY') is None:
            bootstrap=import_legacy(store,config['legacy_us_run'])
        else: bootstrap={'status':'ALREADY_IMPORTED','new_api_requests':0,'strategy_replays':0}
        cutoff_us=confirmed_cutoff('XNYS')
        cutoff_cn=confirmed_cutoff('XSHG')
        network={'mode':'ARCHIVE_REUSE','requests':[],'provider_stops':{}}
        if args.mode=='incremental': network=refresh(store,config,output,cutoff_us)
        elif args.mode=='probe': network=refresh(store,config,output,cutoff_us,probe_only=True)
        scope_after=legacy.source_scope(json.loads(legacy.PROFILE.read_text()),REPO.parent)
        scope={k:{**v,'unchanged_during_audit':v==scope_before[k]} for k,v in scope_after.items()}
        us=assess(store,output,cutoff_us,scope,REPO,run_id,network)
        cn=cn_run(config,output,args.cn_mode,cutoff_cn)
        probe_path=args.field_probes or root/'evidence/wind_field_probe_results.json'
        probes=json.loads(probe_path.read_text(encoding='utf-8')) if probe_path.exists() else None
        followup=root/'wind_capability_evidence/narrow_single_field_followup_20261026/followup.json'
        if probes is not None and followup.exists():
            probes['narrow_single_field_followup']=json.loads(followup.read_text(encoding='utf-8'))
        changes=list(us.get('new_or_changed_issues',[]))
        if cn:
            for asset in cn.get('assets',[]):
                issue_id='CN:'+asset['code']
                evidence={k:asset.get(k) for k in ['code','gate','amount_gate','reason','field_gaps']}
                prior=store.db.execute('SELECT 1 FROM known_issues WHERE issue_id=?',(issue_id,)).fetchone()
                changed=store.issue(issue_id,asset.get('gate','BLOCKED'),evidence)
                if changed and (prior or asset['code']!='000852.SH'): changes.append({'issue_id':issue_id,'evidence':evidence})
        report={'schema_version':1,'run_id':run_id,'status':'REVIEW_REQUIRED','purpose':'research_only',
                'cutoffs':{'US':cutoff_us,'CN':cutoff_cn},'bootstrap':bootstrap,
                'US':us,'CN':cn,'crypto':crypto_boundary(config),'field_probes':probes,
                'projects':adapters.readiness(us,cn,probes),'completed_work_reused':completed_work(REPO),
                'new_or_changed_issues':changes,'production_changed':False,'poe_deployed':False,'strategy_backtests_run':0}
        write(output/'US_report.json',us)
        write(output/'project_readiness.json',report['projects'])
        write(output/'report.json',report)
        render(report,output)
        store.finish_run(run_id,report['status'],output/'report.json')
        # The latest marker references an assessment, never a PASS/cache fallback.
        marker=root/'latest.tmp'
        write(marker,{'run_id':run_id,'report':str(output/'report.json'),'status':report['status']})
        marker.replace(root/'latest.json')
        if args.export:
            args.export.mkdir(parents=True,exist_ok=True)
            for name in ['report.html','report.json','US_report.json','project_readiness.json']:
                shutil.copyfile(output/name,args.export/name)
        print(json.dumps({'report':str(output/'report.html'),'cutoffs':report['cutoffs'],'new_or_changed_issues':len(changes),
                          'reused_completed_work':3,'US_requests':len(network.get('requests',[])),'CN_requests':cn.get('requests',0) if cn else 0,
                          'production_changed':False},ensure_ascii=False))
        return 0  # Process completion; report status remains REVIEW_REQUIRED.
    except Exception as exc:
        for provider in ['tiingo','yahoo','wind']: store.quarantine_provider(provider,'Incomplete service assessment',run_id)
        failure={'run_id':run_id,'status':'FAILED','error_type':type(exc).__name__,'production_changed':False}
        write(output/'report.json',failure)
        store.finish_run(run_id,'FAILED',output/'report.json')
        write(root/'latest.json',{'run_id':run_id,'report':str(output/'report.json'),'status':'FAILED'})
        print(json.dumps(failure),file=sys.stderr)
        return 2
    finally: store.close()


def run(args):
    config=load(args.config)
    try:
        with service_lock(config['store_root']): return _run_locked(args)
    except ServiceAlreadyRunning:
        print(json.dumps({'status':'ALREADY_RUNNING','production_changed':False}))
        return 3


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=DEFAULT_ROOT/'config.json')
    parser.add_argument('--mode',choices=['reuse','probe','incremental'],default='incremental')
    parser.add_argument('--cn-mode',choices=['skip','archive','tail','live'],default='archive')
    parser.add_argument('--field-probes',type=Path)
    parser.add_argument('--export',type=Path)
    args=parser.parse_args()
    return run(args)


if __name__=='__main__': sys.exit(main())

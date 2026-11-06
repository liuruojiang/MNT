"""Recheck recorded real observations, without making fresh market requests."""
import ast
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = ROOT / 'mnt_bot V 8.0 plus.py'


def read(path):
    return json.loads(path.read_text('utf-8'))


def main():
    source = SOURCE.read_text('utf-8-sig')
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    tree = ast.parse(source)
    klass = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'CombinedStrategyBase')
    native = {}
    for name, stop_text in [('_fetch_data', "msg.write('⏳ 正在获取美股数据"), ('_run_strategies', 'cn_dk_result = run_v80_adk_new_only')]:
        fn = next(x for x in klass.body if isinstance(x, ast.FunctionDef) and x.name == name)
        stop = next(i for i, node in enumerate(fn.body) if stop_text in ast.get_source_segment(source, node))
        native[name] = '\n\n'.join(ast.get_source_segment(source, node) for node in fn.body[:stop])
    runs = []
    for label in ('start', 'middle', 'end'):
        path = HERE / label
        if not (path / 'summary.json').exists():
            continue
        summary = read(path / 'summary.json')
        check = {'label': label, 'summary': summary, 'source_hash_match': summary['source_sha256'] == source_hash,
                 'native_prefix_exact': all((path / (name + '_native_prefix.txt')).read_text('utf-8') == value for name, value in native.items())}
        check['integrity_guard_observed'] = (summary.get('integrity_pending_before') is False
                                            and summary.get('integrity_pending_after') is False
                                            and summary.get('integrity_generation_before') == summary.get('integrity_generation_after'))
        check['integrity_scope_note'] = 'First round core A slice; no US quarantine path invoked' if label == 'start' else 'Original assertions and VerifiedMessage wrapper executed'
        receipts = []
        for f in sorted((path / 'http').glob('*.json')):
            receipt = read(f)
            if 'raw_file' in receipt:
                body = (f.parent / receipt['raw_file']).read_bytes()
                assert hashlib.sha256(body).hexdigest() == receipt['sha256'], str(f)
            receipts.append((f, receipt))
        check['http_receipts_hash_valid'] = True
        if (path / 'native_prices.pkl').exists():
            prices = pd.read_pickle(path / 'native_prices.pkl')
            check['columns'] = list(prices.columns)
            check['complete_six_columns'] = set(prices.columns) == {'1.930955','0.399006','1.000016','1.000852','1.000905','1.000012'}
            check['all_finite_positive'] = bool(np.isfinite(prices.to_numpy()).all() and (prices > 0).all().all())
            check['today_index'] = str(prices.index[-1].date()) == '2026-11-06'
            check['quote_matches'] = []
            aliases = read(path / 'native_defaults.json')['CN_VENDOR_SECID_ALIASES']
            for code in prices.columns:
                adopted = float(prices[code].iloc[-1])
                matches = []
                for f, receipt in receipts:
                    endpoint = urlparse(receipt['request_url'])
                    if endpoint.hostname != 'push2his.eastmoney.com' or endpoint.path != '/api/qt/stock/trends2/get' or not receipt.get('raw_file'):
                        continue
                    payload = read(f.parent / receipt['raw_file'])
                    data = payload.get('data') or {}
                    requested = parse_qs(urlparse(receipt['request_url']).query).get('secid', [])
                    permitted = aliases.get(code, [code])
                    if len(requested) != 1 or requested[0] not in permitted:
                        continue
                    request_market, request_code = requested[0].split('.')
                    identity_matches = str(data.get('code')) == request_code and str(data.get('market')) == request_market
                    if not identity_matches or str(data.get('code')) != code.split('.')[1]:
                        continue
                    observed = pd.Timestamp(receipt['completed_at_utc']).tz_convert('Asia/Shanghai').tz_localize(None)
                    rows = [x.split(',') for x in data.get('trends', [])]
                    eligible = [x for x in rows if pd.Timestamp(x[0]) <= observed]
                    if not eligible:
                        continue
                    selected = eligible[-1]
                    stamp = pd.Timestamp(selected[0])
                    lag = (observed-stamp).total_seconds()
                    same_value = abs(float(selected[2])-adopted) < 1e-10
                    matches.append({'receipt':str(f.relative_to(HERE)), 'request_url':receipt['request_url'], 'source':'EastMoney same-index minute trend',
                                    'code':data['code'], 'market':data.get('market'), 'adopted_value':adopted,'source_value':float(selected[2]),
                                    'requested_secid':requested[0], 'allowed_native_aliases':permitted, 'identity_matches_request':identity_matches,
                                    'quote_time':str(stamp), 'collected_time':str(observed), 'lag_seconds':lag,
                                    'same_value':same_value,'fresh':0 <= lag <= 300 and str(stamp.date())=='2026-11-06'})
                check['quote_matches'].append({'column':code,'matched':any(x['same_value'] and x['fresh'] for x in matches),'observations':matches})
            check['all_today_prices_traceable'] = all(x['matched'] for x in check['quote_matches'])
        if (path / 'native_result.pkl').exists():
            r = pd.read_pickle(path / 'native_result.pkl')
            row = r.iloc[-1]
            check['volume_known'] = all(bool(row.get(x, False)) for x in ('suba_volume_zz2000_known','suba_volume_cyb_known','suba_volume_freshness_ok'))
            check['volume_unresolved_false'] = not any(bool(row.get(x, True)) for x in ('suba_volume_combined_unresolved','suba_volume_unresolved'))
            check['volume_expected_date'] = str(row['suba_volume_freshness_expected_date'])
            check['volume_latest_date'] = str(row['suba_volume_freshness_latest_date'])
            check['volume_sources'] = {key:str(row[key]) for key in ('suba_volume_zz2000_source','suba_volume_cyb_source')}
            for kind in ('live_signal','live_params'):
                text = (path / (kind + '.md')).read_text('utf-8')
                check[kind+'_current_date'] = '**2026-11-06**（盘中快照，尚未确认）' in text
                info = read(path / (kind + '.json'))['Sub-A']
                check[kind+'_no_formal_instruction'] = info['is_signal'] is False
            check['signal_observation_only'] = '盘中仅观察：现在不操作' in (path / 'live_signal.md').read_text('utf-8')
            check['defaults_unchanged'] = all(read(path / 'native_defaults.json')[k] == v for k,v in {'CN_BIAS_N':60,'CN_MOM_DAY':20,'CN_R2_THRESHOLD':0.15,'CN_TARGET_VOL':0.2,'CN_VOL_WINDOW':80,'CN_MAX_LEV':1.25,'CN_COMMISSION':0.001,'CN_SA_VOLUME_OVERLAY_ENABLED':True}.items())
        mandatory = ['source_hash_match','native_prefix_exact','http_receipts_hash_valid','complete_six_columns','all_finite_positive','today_index','all_today_prices_traceable','volume_known','volume_unresolved_false','live_signal_current_date','live_params_current_date','live_signal_no_formal_instruction','live_params_no_formal_instruction','signal_observation_only','defaults_unchanged']
        if label != 'start':
            mandatory.append('integrity_guard_observed')
        check['verified'] = all(check.get(key,False) for key in mandatory)
        runs.append(check)
    result = {'scope':'A native fetch/run prefixes and shared native live renderers; no full multi-sleeve handler or Poe certification',
              'source_sha256':source_hash,'runs':runs,'status':'PASS_A_SCOPED' if len(runs)==3 and all(x['verified'] for x in runs) else 'PARTIAL_OR_BLOCKED'}
    observed_lags = [q['lag_seconds'] for run in runs for item in run.get('quote_matches',[]) for q in item['observations'] if q['same_value'] and q['fresh']]
    result['maximum_adopted_quote_lag_seconds'] = max(observed_lags) if observed_lags else None
    result['observed_rounds'] = len(runs)
    (HERE / 'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    lines = ['# 2026-11-06 A策略盘中专项验收', '', '状态：' + result['status'], '',
             '本报告只认证本地 V8.0 的 A 袖原生获取、计算与实时展示专项；不是完整多袖机器人或 Poe 线上验收。无下单、邮件或部署。', '',
             '## 同源链与边界', '',
             '- 原样执行 CombinedStrategyBase._fetch_data 中进入美股获取之前的全部 A 段，保留历史最小长度、已确认截止日、盘中报价校验、原始价格完整性和必需国债。',
             '- 原样执行 _run_strategies 中 ADK 调用之前的全部 A 段：run_cn_strategy、成交额获取/新鲜度/不可判定处理、成交额覆盖。两个原生 live handler 均使用 allow_unresolved_suba_volume=True；专项保持此值，并另外核验不可判定为 False，未将未知风控当正常。',
             '- 实时信号和参数共用原生 _write_a_adk_query_overview，分别使用 live_signal/live_params，真实当日价格帧及盘中标记。输出中的 ADK 不可用是本专项主动不加载 ADK 的边界，不是 A 的失败。',
             '- 中段/末段额外保留原生 integrity generation 前后断言、pending 记录、价格帧标签及 _V80VerifiedMessage；首轮未运行这些包装。源码唯一 quarantine 触发调用位于美股 fetch_yahoo，本次首轮为无美股请求的独立新进程；不能据此认证跨袖运行或既有长驻机器人缓存。',
             '- 缓存写调用仅重定向到本轮证据目录，原有缓存读取/网络响应和所有默认参数未改。没有修改生产源码。', '',
             '## 实际轮次', '', '| 轮次 | UTC开始 | UTC结束 | 日期 | 六列可追溯 | 成交额可判定 | 复核 |', '|---|---|---|---|---|---|---|']
    for run in runs:
        s = run['summary']
        lines.append('| ' + ' | '.join(str(x) for x in [run['label'],s['started_at_utc'],s['finished_at_utc'],s.get('result_end','未生成'),run.get('all_today_prices_traceable',False),run.get('volume_unresolved_false',False),run['verified']]) + ' |')
    lines += ['', '审计 JSON 保存每列真实行情时刻、采集时刻、滞后、代码/市场/请求 URL 身份匹配、响应 SHA256 与采用值的精确相等检查。930955 使用原生允许的 2.930955 供应商映射；000012 没有任何 H11077 锚点缩放。', '',
              '首轮独立国债链 start_bond 保留新浪发布后完整日线、11月5日确认收盘和11月6日直接实时采用值。中段/末段 fetch_*.csv 是透明旁录的原生返回帧。', '',
              '默认规则保持 MA60/动量20、R²20日≥0.15且Top-1失败不递补；目标波动20%/80日，上限1.25x；ZZ2000成交额MA20连续3日或CYB连续4日触发股票降至0%；成本单边0.10%。全部 CN 默认常量另存 native_defaults.json。', '',
              '本次是实时数据与信号功能验收，没有运行收益比较。Full / 10Y / 5Y / 3Y / 1Y 年化收益及最大回撤均 N/A，不是收益优选或历史可执行收益认证。', '',
              '所有实时目标均为盘中参考、尚未收盘确认；验收成功不等于发出了正式交易指令。']
    (HERE / 'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],'runs':[{k:x[k] for k in ('label','verified')} for x in runs]},ensure_ascii=False))
    if '--require-complete' in sys.argv and result['status'] != 'PASS_A_SCOPED':
        raise SystemExit(1)


if __name__ == '__main__':
    main()

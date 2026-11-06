"""Independent offline audit: reparse immutable raw quotes, not collector verdicts."""
import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
BJ = ZoneInfo('Asia/Shanghai')
EXPECTED_SOURCE_SHA = '606fd98bc0a7fde17a337fed0c67bd1179e1b03e1f6eecb78d643ff82198ba23'
URLS = {'tencent': 'https://qt.gtimg.cn/q=sh000012', 'sina': 'https://hq.sinajs.cn/list=sh000012'}


def main():
    final_path = OUT / 'quote_final.json'
    if not final_path.exists():
        raise SystemExit('WAITING: full seven-round collector evidence is not complete')
    manifest = json.loads(final_path.read_text('utf-8'))
    problems = []
    checks = []
    source_sha = hashlib.sha256((ROOT / 'mnt_bot V 8.0 plus.py').read_bytes()).hexdigest()
    if source_sha != EXPECTED_SOURCE_SHA or manifest['source_sha256'] != EXPECTED_SOURCE_SHA:
        problems.append('Production code identity differs from independently observed initial baseline')
    if len(manifest['rounds']) != 7:
        problems.append('Final manifest does not contain exactly seven rounds')
    for number in range(1, 8):
        for provider, expected_url in URLS.items():
            stem = OUT / f'round_{number:02d}_{provider}'
            try:
                receipt = json.loads(stem.with_suffix('.json').read_text('utf-8'))
                raw = stem.with_suffix('.raw').read_bytes()
                raw_sha = hashlib.sha256(raw).hexdigest()
                text = raw.decode('gb18030')
                fields = text.split('"')[1].split('~' if provider == 'tencent' else ',')
                if provider == 'tencent':
                    symbol_valid = text.startswith('v_sh000012="') and fields[2] == '000012'
                    stamp = datetime.strptime(fields[30], '%Y%m%d%H%M%S').replace(tzinfo=BJ)
                else:
                    symbol_valid = text.startswith('var hq_str_sh000012="')
                    stamp = datetime.fromisoformat(fields[30] + 'T' + fields[31]).replace(tzinfo=BJ)
                price = float(fields[3])
                started = datetime.fromisoformat(receipt['request_started_utc'])
                received = datetime.fromisoformat(receipt['retrieved_at_utc'])
                lag = (received - stamp).total_seconds()
                minute = (stamp.hour, stamp.minute, stamp.second)
                row_checks = {
                    'raw_sha256_matches_receipt': raw_sha == receipt['sha256'],
                    'raw_size_matches_receipt': len(raw) == receipt['bytes'],
                    'raw_symbol_exact': symbol_valid,
                    'provider_symbol_round_binding': receipt['provider'] == provider and receipt['symbol'] == '000012.SH' and receipt['round'] == number,
                    'url_binding': receipt['request_url'] == expected_url and receipt['url'] == expected_url,
                    'http_ok': receipt['http_status'] == 200,
                    'date_is_target_trading_friday': stamp.date().isoformat() == '2026-11-06' and stamp.weekday() == 4,
                    'morning_continuous_session': (9, 30, 0) <= minute <= (11, 30, 0),
                    'received_in_target_morning': received.astimezone(BJ).date() == stamp.date() and (9, 30, 0) <= (received.astimezone(BJ).hour, received.astimezone(BJ).minute, received.astimezone(BJ).second) <= (11, 30, 0),
                    'request_timestamps_aware_and_ordered': started.tzinfo is not None and received.tzinfo is not None and started <= received,
                    'real_quote_not_future_or_stale': 0 <= lag <= 300,
                    'finite_positive_price': math.isfinite(price) and price > 0,
                    'receipt_quote_fields_match_raw': datetime.fromisoformat(receipt['quote_time']) == stamp and receipt['price'] == price and abs(receipt['lag_seconds'] - lag) < 1e-6,
                    'collector_pass_consistent': receipt['status'] == 'PASS' and receipt['native_time_gate'] is True,
                    'manifest_receipt_matches_file': receipt == next(r for r in manifest['rounds'][number-1]['receipts'] if r['provider'] == provider),
                }
                for name, ok in row_checks.items():
                    if not ok:
                        problems.append(f'round {number} {provider}: {name}')
                checks.append({'round': number, 'provider': provider, 'price': price, 'quote_time': stamp.isoformat(),
                               'received_at': received.isoformat(), 'requested_at': started.isoformat(),
                               'lag_seconds': lag, 'raw_sha256': raw_sha, 'checks': row_checks})
            except Exception as exc:
                problems.append(f'round {number} {provider}: {type(exc).__name__}: {exc}')
    summary = {}
    for provider in URLS:
        rows = [row for row in checks if row['provider'] == provider]
        stamps = [datetime.fromisoformat(row['quote_time']) for row in rows]
        request_times = [datetime.fromisoformat(row['requested_at']) for row in rows]
        intervals = [(b - a).total_seconds() for a, b in zip(request_times, request_times[1:])]
        advancing = len(stamps) == 7 and all(b > a for a, b in zip(stamps, stamps[1:]))
        regular = len(intervals) == 6 and all(240 <= value <= 360 for value in intervals)
        span = (request_times[-1]-request_times[0]).total_seconds() if request_times else 0
        if not advancing:
            problems.append(provider + ': seven genuine quote timestamps do not strictly advance')
        if not regular:
            problems.append(provider + ': request cadence does not match approximately five minutes')
        if span < 1795:
            problems.append(provider + ': observation span is shorter than approximately thirty minutes')
        summary[provider] = {'rounds': len(rows), 'all_row_checks_pass': all(all(row['checks'].values()) for row in rows),
                             'quote_times_strictly_advance': advancing, 'request_intervals_seconds': intervals,
                             'request_span_seconds': span,
                             'first_quote_time': rows[0]['quote_time'] if rows else None, 'last_quote_time': rows[-1]['quote_time'] if rows else None,
                             'max_lag_seconds': max((row['lag_seconds'] for row in rows), default=None)}
    differences = []
    for number in range(1, 8):
        rows = [row for row in checks if row['round'] == number]
        if len(rows) == 2:
            difference = abs(rows[0]['price']-rows[1]['price'])
            differences.append(difference)
            if difference > 0.011:
                problems.append(f'round {number}: cross-source price difference {difference} exceeds 0.011')
    with (OUT / 'quote_rounds.csv').open(encoding='utf-8-sig', newline='') as stream:
        csv_rows = list(csv.DictReader(stream))
    if len(csv_rows) != 14:
        problems.append('round CSV is not 14 rows')
    for row in csv_rows:
        matches = [r for r in checks if r['round'] == int(row['round']) and r['provider'] == row['provider']]
        if len(matches) != 1 or matches[0]['raw_sha256'] != row['sha256'] or matches[0]['quote_time'] != row['quote_time'] or matches[0]['price'] != float(row['price']):
            problems.append(f'round CSV content mismatch: round {row["round"]} {row["provider"]}')
    report = {'status': 'PASS' if not problems else 'FAIL', 'audited_at': datetime.now(BJ).isoformat(),
              'scope': 'Independent raw-quote continuity audit only; does not certify full A strategy or Poe deployment',
              'baseline_commit': 'bd639c6fa244244f781685e440966c2314cd7ca3', 'source_sha256': source_sha,
              'collector_sha256': hashlib.sha256((OUT / 'collect_quotes.py').read_bytes()).hexdigest(),
              'summary': summary, 'max_cross_source_absolute_difference': max(differences, default=None),
              'checks': checks, 'problems': problems,
              'software_fault_tests': {'status': 'PASS', 'passed': 18, 'failed': 0,
                  'scope': 'Frozen November 5 receipts plus injected missing/history-gap/stale/identity/direct-price faults; not live market evidence',
                  'record': 'D:/Codex/test-lifecycle/records/ffeb456850c347f397eb3df1ff89e7f1',
                  'initial_command_error_record': 'D:/Codex/test-lifecycle/records/ecb3f4aba1e74a8f871c87f072e086d8',
                  'initial_command_error': 'Extra inner -B was interpreted as pytest argument, exited before tests; corrected rerun passed'}}
    (OUT / 'quote_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 国债盘中报价独立审计', '', f'结论：**{report["status"]}**。仅认证七轮真实报价连续性，不代替 A 策略链验收或 Poe 线上部署。', '',
             '| 来源 | 轮数 | 首轮报价时刻 | 末轮报价时刻 | 最大滞后秒 | 时间持续推进 |', '|---|---:|---|---|---:|---|']
    for provider, value in summary.items():
        lines.append(f'| {provider} | {value["rounds"]} | {value["first_quote_time"]} | {value["last_quote_time"]} | {value["max_lag_seconds"]} | {value["quote_times_strictly_advance"]} |')
    lines.extend(['', f'双源最大差：{report["max_cross_source_absolute_difference"]} 点；容差 0.011 点。', '',
                  '独立从十四份原始字节重新解析代码、价格与行情时间，复核 SHA256、字节数、URL/来源绑定、回执与 manifest 一致、请求/返回时序、交易日期与时段及 5 分钟时效。价格无需变化；全部行情时间必须真实推进。', '',
                  '18 项软件反例测试通过；它们使用冻结数据/故障注入，明确与本次盘中采集分开。初次命令因 pytest 参数误传退出，修正后重跑通过。详见 JSON 记录。', '',
                  '本审计子 Agent 未修改正式策略、collector、参数或生产门禁，未下单或部署。证据提交与推送由主 Agent 按既有授权另行处理。'])
    if problems:
        lines.extend(['', '问题：'] + ['- '+problem for problem in problems])
    (OUT / 'quote_audit.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({key:report[key] for key in ['status','summary','max_cross_source_absolute_difference','problems']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

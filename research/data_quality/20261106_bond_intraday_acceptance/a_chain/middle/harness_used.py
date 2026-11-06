"""Read-only live A-sleeve acceptance using exact native method prefixes."""
import ast
import copy
import hashlib
import importlib.util
import io
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = ROOT / 'mnt_bot V 8.0 plus.py'


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def native_prefix(module, name, stop_text, result_name, output):
    source = SOURCE.read_text('utf-8-sig')
    tree = ast.parse(source)
    klass = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'CombinedStrategyBase')
    fn = copy.deepcopy(next(x for x in klass.body if isinstance(x, ast.FunctionDef) and x.name == name))
    stop = next(i for i, node in enumerate(fn.body) if stop_text in ast.get_source_segment(source, node))
    selected = fn.body[:stop]
    fragment = '\n\n'.join(ast.get_source_segment(source, node) for node in selected)
    (output / (name + '_native_prefix.txt')).write_text(fragment, encoding='utf-8')
    fn.name = name + '_a_only'
    fn.body = selected + [ast.Return(value=ast.Name(id=result_name, ctx=ast.Load()))]
    extracted = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    exec(compile(extracted, str(SOURCE) + ':' + name + ':A-prefix', 'exec'), module.__dict__)
    return getattr(module, fn.name)


def main():
    label = sys.argv[1]
    out = HERE / label
    out.mkdir(parents=True, exist_ok=False)
    raw = out / 'http'
    raw.mkdir()
    summary = {'started_at_utc': now(), 'label': label, 'scope': 'Native A-only method prefixes; not full multi-sleeve bot or Poe deployment', 'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest()}
    (out / 'harness_used.py').write_bytes(Path(__file__).read_bytes())
    summary['harness_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location('v80_a_acceptance_' + label, SOURCE)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    fetch = native_prefix(m, '_fetch_data', "msg.write('⏳ 正在获取美股数据", 'cn_close', out)
    run = native_prefix(m, '_run_strategies', 'cn_dk_result = run_v80_adk_new_only', 'cn_result', out)
    log = io.StringIO()
    log_path = out / 'native_log.txt'
    class LiveLog:
        def write(self, text):
            log.write(text)
            log_path.write_text(log.getvalue(), encoding='utf-8')
            print(text, end='', flush=True)
    msg = LiveLog()
    original_send = requests.sessions.Session.send
    count = 0
    def recorded_send(session, request, **kwargs):
        nonlocal count
        count += 1
        number = count
        receipt = {'request_url': request.url, 'method': request.method, 'started_at_utc': now()}
        try:
            response = original_send(session, request, **kwargs)
            body = response.content
            name = f'{number:04d}.raw'
            (raw / name).write_bytes(body)
            receipt.update(status=response.status_code, final_url=response.url, raw_file=name, sha256=hashlib.sha256(body).hexdigest(), bytes=len(body), encoding=response.encoding)
            return response
        except Exception as exc:
            receipt['error'] = repr(exc)
            raise
        finally:
            receipt['completed_at_utc'] = now()
            dump(raw / f'{number:04d}.json', receipt)
    # Cache write calls are evidence copies only; existing cache reads and HTTP responses are unchanged.
    def evidence_cache(secid, frame):
        frame.to_csv(out / ('cache_write_' + secid.replace('.', '_') + '.csv'))
    defaults = {k: v for k, v in vars(m).items() if k.startswith(('CN_', 'V80_SUBA_')) and isinstance(v, (str, int, float, bool, list, tuple, dict, type(None)))}
    dump(out / 'native_defaults.json', defaults)
    summary['bond_code'] = m.CN_BOND_CODE
    summary['bond_name'] = m.CN_BOND_NAME
    generation = m._v80_integrity_generation()
    summary['integrity_generation_before'] = generation
    summary['integrity_pending_before'] = m._v80_integrity_pending()
    original_fetch = m.fetch_cn_kline
    fetch_count = 0
    def recorded_fetch(secid, *args, **kwargs):
        nonlocal fetch_count
        fetch_count += 1
        frame, source = original_fetch(secid, *args, **kwargs)
        name = f'fetch_{fetch_count:02d}_{secid.replace(".", "_")}'
        frame.to_csv(out / (name + '.csv'))
        dump(out / (name + '.json'), {'source': source, 'secid': secid, 'args': args, 'kwargs': kwargs, 'captured_at_utc': now(), 'attrs': frame.attrs})
        return frame, source
    try:
        with patch.object(requests.sessions.Session, 'send', recorded_send), patch.object(m, '_save_cn_official_cache', evidence_cache), patch.object(m, 'fetch_cn_kline', recorded_fetch):
            m._v80_assert_integrity(generation)
            if '--bond-only' in sys.argv:
                previous = m._latest_cn_data_required_date()
                bond, source = m.fetch_cn_kline(m.CN_BOND_CODE, required_date=previous)
                bond = m._drop_cn_unconfirmed_today(bond)
                summary['last_confirmed_close'] = str(bond.index[-1])
                summary['last_confirmed_value'] = float(bond['close'].iloc[-1])
                summary['required_close'] = str(previous)
                summary['history_source'] = source
                live = m._supplement_today_close(bond, m.CN_BOND_CODE, m.beijing_now().date(), msg)
                live.to_csv(out / 'bond_live.csv')
                dump(out / 'bond_live_attrs.json', live.attrs)
                summary['adopted_date'] = str(live.index[-1])
                summary['adopted_value'] = float(live['close'].iloc[-1])
                summary['status'] = 'PASS_NATIVE_BOND' if pd.Timestamp(live.index[-1]).date() == m.beijing_now().date() else 'BLOCKED'
                return
            prices = fetch(object(), msg, include_cn_live_snapshot=True, include_us_live_snapshot=True)
            m._v80_assert_integrity(generation)
            prices.attrs['verified_integrity_generation'] = generation
            prices.to_pickle(out / 'native_prices.pkl')
            prices.to_csv(out / 'native_prices.csv')
            dump(out / 'price_attrs.json', prices.attrs)
            summary['input_end'] = str(prices.index[-1])
            summary['input_start'] = str(prices.index[0])
            summary['input_rows'] = len(prices)
            summary['input_columns'] = list(prices.columns)
            summary['bond_adopted'] = float(prices[m.CN_BOND_CODE].iloc[-1])
            result = run(object(), prices, None, None, None, allow_unresolved_suba_volume=True)
            m._v80_assert_integrity(generation)
            result.to_pickle(out / 'native_result.pkl')
            result.tail(20).to_csv(out / 'native_result_last20.csv')
            summary['result_end'] = str(result.index[-1])
            summary['volume_unresolved'] = bool(result.iloc[-1].get('suba_volume_unresolved', result.iloc[-1].get('suba_volume_unavailable', False)))
            for kind in ('live_signal', 'live_params'):
                display = io.StringIO()
                verified_display = m._V80VerifiedMessage(display, m._v80_frames_generation(prices))
                info = m._write_a_adk_query_overview(verified_display.write, result, None, cn_intraday=True, dk_intraday=False, query_kind=kind, cn_price_frame=prices)
                (out / f'{kind}.md').write_text(display.getvalue(), encoding='utf-8')
                dump(out / f'{kind}.json', info)
            summary['today'] = str(m.beijing_now().date())
            summary['current_date_signal'] = pd.Timestamp(result.index[-1]).date() == m.beijing_now().date()
            summary['status'] = 'PASS_A_NATIVE_SLICE' if summary['current_date_signal'] and not summary['volume_unresolved'] else 'BLOCKED'
            m._v80_assert_integrity(generation)
            summary['integrity_generation_after'] = m._v80_integrity_generation()
            summary['integrity_pending_after'] = m._v80_integrity_pending()
    except Exception as exc:
        summary['status'] = 'BLOCKED'
        summary['error'] = repr(exc)
        (out / 'traceback.txt').write_text(traceback.format_exc(), encoding='utf-8')
        print(traceback.format_exc(), flush=True)
    finally:
        summary['finished_at_utc'] = now()
        summary['http_requests'] = count
        log_path.write_text(log.getvalue(), encoding='utf-8')
        dump(out / 'summary.json', summary)
        print(json.dumps(summary, ensure_ascii=False, default=str), flush=True)


if __name__ == '__main__':
    main()

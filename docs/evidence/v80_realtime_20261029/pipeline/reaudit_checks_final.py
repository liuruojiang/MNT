"""Independent offline second-pass pipeline checks; no market-performance claim."""
import hashlib
import importlib.util
import io
import json
import sys
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import pandas as pd

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'mnt_bot V 8.0 plus.py').is_file())
SOURCE = ROOT / 'mnt_bot V 8.0 plus.py'
initial_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
spec = importlib.util.spec_from_file_location('pipeline_reaudit', SOURCE)
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
results = {}
dates = pd.to_datetime(['2026-10-28', '2026-10-29'])
raw = {code: pd.DataFrame({'close': [100., 101.], 'is_live_bar': [False, True]}, index=dates) for code in m.CN_STOCK_CODES}
cn = m._build_cn_stock_close_frame(raw)
dk_raw = {code: pd.DataFrame({code: [100., 101.], 'is_live_bar': [False, True]}, index=dates) for code in m.CN_DK_COLS}
dk = m._build_cn_dk_close_frame(dk_raw)
assert cn.attrs['cn_unconfirmed_snapshot'] and dk.attrs['cn_unconfirmed_snapshot']
cn_result = pd.DataFrame({'holding': ['cash', '1.930955'], 'weight': [0., 1.]}, index=dates)
dk_result = pd.DataFrame({'top_pair': ['none', 'none'], 'direction': [0, 0], 'weight': [0., 0.]}, index=dates)

for kind in ['live_signal', 'live_params']:
    clock = [pd.Timestamp('2026-10-29 14:59').to_pydatetime()]
    lines = []; fetches = []
    class Message:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def write(self, text): lines.append(text)
    bot = m.CombinedStrategyV80()
    def fetch(msg, **kw):
        fetches.append(1)
        return cn, dk, cn, cn
    def compute(*args):
        clock[0] = pd.Timestamp('2026-10-29 15:01').to_pydatetime()
        return defaultdict(lambda: None, cn_date=dates[-1], dk_date=dates[-1], us_date=dates[-1], cn_result=cn_result, cn_dk_result=dk_result, us_rot_result=cn, subc_vs_info={})
    def run(*args, **kw):
        clock[0] = pd.Timestamp('2026-10-29 15:01').to_pydatetime()
        return cn_result, dk_result, cn, None, None, None, None, None
    with ExitStack() as stack:
        stack.enter_context(patch.object(m, 'beijing_now', lambda: clock[0]))
        stack.enter_context(patch.object(m, '_sm', Message))
        stack.enter_context(patch.object(bot, '_fetch_data', fetch))
        stack.enter_context(patch.object(bot, '_compute_signal_data', compute))
        stack.enter_context(patch.object(bot, '_cached_run_strategies', run))
        for name in ['_write_v80_subb_overview','_write_v80_subc_overview','_write_v80_a_adk_score_details','_write_volume_warning_panel','_write_suba_volume_query_warning']:
            stack.enter_context(patch.object(m, name, lambda *a, **k: None))
        # Exercise real request cache; then handler consumes the cached frames.
        bot._cached_fetch_data(Message(), include_cn_live_snapshot=True, include_us_live_snapshot=True)
        getattr(bot, '_handle_' + kind)()
    text = ''.join(lines)
    assert len(fetches) == 1
    assert text.count('盘中快照，尚未确认') == 2, text
    assert '收盘目标已确认' not in text
    assert '基于收盘数据' not in text
    assert '未确认行情快照' in text
    assert '盘中参考目标（待收盘确认）' in text
    results[kind + '_snapshot_cross_close_cached'] = {'pass': True, 'fetch_count': len(fetches), 'transcript': text}

with patch.object(m, 'beijing_now', lambda: pd.Timestamp('2026-10-01 14:00').to_pydatetime()):
    holiday_result = cn_result.set_axis(pd.to_datetime(['2026-09-29', '2026-09-30']))
    msg = io.StringIO(); m._write_a_adk_query_overview(msg.write, holiday_result, None, query_kind='live_signal')
    assert '今日Sub-A实时数据不完整' not in msg.getvalue()
    results['holiday_valid_last_close'] = {'pass': True}

base = pd.DataFrame({'close': [100., 101.]}, index=dates)
with patch.object(m, 'beijing_now', lambda: pd.Timestamp('2026-10-29 14:00').to_pydatetime()), patch.object(m, '_fetch_cn_realtime_close', return_value=105.) as get:
    refreshed = m._supplement_today_close(base, '1.930955', dates[-1].date())
    assert get.call_count == 1 and refreshed.iloc[-1]['close'] == 105. and refreshed.iloc[-1]['is_live_bar']
    assert base.iloc[-1]['close'] == 101.
    results['refresh_existing_today'] = {'pass': True}
with patch.object(m, 'beijing_now', lambda: pd.Timestamp('2026-10-29 14:00').to_pydatetime()), patch.object(m, '_fetch_cn_realtime_close', return_value=None):
    refreshed = m._supplement_today_close(base, '1.930955', dates[-1].date())
    assert refreshed.index[-1] == dates[0]
    results['failed_refresh_removes_today'] = {'pass': True}
with patch.object(m, 'beijing_now', lambda: pd.Timestamp('2026-10-29 15:01').to_pydatetime()), patch.object(m, '_fetch_cn_realtime_close', return_value=105.) as get:
    refreshed = m._supplement_today_close(base.iloc[:1], '1.930955', dates[-1].date())
    assert get.call_count == 0 and refreshed.index[-1] == dates[0]
    results['no_afterclose_snapshot_injection'] = {'pass': True}
    try:
        m._assert_cn_raw_prices_fresh(raw, m.CN_STOCK_CODES, dates[-1], 'reaudit')
    except Exception as exc:
        results['formal_rejects_marked_snapshot'] = {'pass': True, 'error': str(exc)}
    else:
        raise AssertionError('Marked snapshot admitted as confirmed close')
    assert m._latest_confirmed_cn_rule_date(dates[:1]) == dates[0]
    results['fallback_volume_date_stays_previous'] = {'pass': True}

final_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
assert initial_hash == final_hash
report = {'source_sha256': final_hash, 'production_unchanged_during_probe': True, 'checks': results}
Path(__file__).with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'source_sha256': final_hash, 'passed': len(results), 'checks': list(results)}, ensure_ascii=True))

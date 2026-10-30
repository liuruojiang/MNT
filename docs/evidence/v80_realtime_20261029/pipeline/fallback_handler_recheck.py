"""Offline clock-crossing counterexample; source responses/strategy are fixtures."""
import importlib.util
import io
import json
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'mnt_bot V 8.0 plus.py').is_file())
spec = importlib.util.spec_from_file_location('pipeline_handler_audit', ROOT / 'mnt_bot V 8.0 plus.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
clock = [pd.Timestamp('2026-10-29 14:59:00').to_pydatetime()]
cn_result = pd.DataFrame({'holding': ['cash', '1.930955'], 'weight': [0., 1.]}, index=pd.to_datetime(['2026-10-27', '2026-10-28']))
raw = {code: pd.DataFrame({'close': [100., 101., 102.]}, index=pd.to_datetime(['2026-10-27', '2026-10-28', '2026-10-29'])) for code in m.CN_STOCK_CODES}
raw['1.930955'] = raw['1.930955'].iloc[:-1]
lines = []
class Message:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def write(self, text): lines.append(text)

bot = m.CombinedStrategyV80()
observed = {}
def fetch(msg, **kwargs):
    # Keep actual new fallback and actual merge, emulate already fetched vendors.
    required = m._latest_cn_data_required_date(clock[0])
    aligned = m._align_partial_cn_intraday(raw, m.CN_STOCK_CODES, clock[0], required, msg)
    cn = m._build_cn_stock_close_frame(aligned)
    observed['fetched_at'] = str(clock[0])
    observed['cn_asof'] = str(cn.index[-1])
    return cn, cn, cn, cn

def compute(cn, dk, us, prod):
    # Model downstream US data/strategy work finishing after market close.
    clock[0] = pd.Timestamp('2026-10-29 15:01:00').to_pydatetime()
    return defaultdict(lambda: None, cn_date=cn.index[-1], dk_date=dk.index[-1],
                       us_date=us.index[-1], cn_result=cn_result, cn_dk_result=None,
                       us_rot_result=us, subc_vs_info={})

with patch.object(m, 'beijing_now', lambda: clock[0]), patch.object(m, '_sm', Message), patch.object(bot, '_fetch_data', fetch), patch.object(bot, '_compute_signal_data', compute), patch.object(m, '_write_v80_subb_overview', lambda *a, **k: None), patch.object(m, '_write_v80_subc_overview', lambda *a, **k: None), patch.object(m, '_write_v80_a_adk_score_details', lambda *a, **k: None), patch.object(m, '_write_volume_warning_panel', lambda *a, **k: None):
    bot._handle_live_signal()  # Real request cache, real handler, real A display.

text = ''.join(lines)
panel = text.split('### A策略')[1].split('### ADK')[0]
observed.update(displayed_at=str(clock[0]), warning_in_A_panel='今日Sub-A实时数据不完整' in panel,
                execute_yesterday='收盘目标已确认' in panel, transcript=text)
(Path(__file__).with_suffix('.json')).write_text(json.dumps(observed, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: v for k, v in observed.items() if k != 'transcript'}, ensure_ascii=True))

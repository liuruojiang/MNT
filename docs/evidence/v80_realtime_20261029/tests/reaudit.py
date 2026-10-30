"""Independent offline reaudit: real params handler and both request caches."""
import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

root = next(parent for parent in Path(__file__).resolve().parents if (parent / 'mnt_bot V 8.0 plus.py').is_file())
spec = importlib.util.spec_from_file_location('reaudit_v80_tests', root / 'mnt_bot V 8.0 plus.py')
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
clock = [pd.Timestamp('2026-10-29 14:59').to_pydatetime()]
lines = []; fetch_calls = []; run_calls = []
class Msg:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def write(self, text): lines.append(text)
bot = m.CombinedStrategyV80()
dates = pd.to_datetime(['2026-10-27','2026-10-28','2026-10-29'])
raw = {code: pd.DataFrame({'close':[100.,101.,102.], 'is_live_bar':[False,False,True]}, index=dates) for code in m.CN_STOCK_CODES}
def fetch(msg, **kw):
    fetch_calls.append(1)
    cn = m._build_cn_stock_close_frame(raw)
    return cn, cn.copy(), cn.copy(), cn.copy()
def run(cn, dk, us, prod, **kw):
    run_calls.append(1)
    clock[0] = pd.Timestamp('2026-10-29 15:01').to_pydatetime()
    result = pd.DataFrame({'holding':['cash','1.930955'],'weight':[0.,1.]},index=cn.index[-2:])
    return result, None, us, None, None, None, None, None
def forbidden(*a, **k): raise AssertionError('Network forbidden')
with patch.object(m,'beijing_now',lambda:clock[0]), patch.object(m,'_sm',Msg), patch.object(bot,'_fetch_data',fetch), patch.object(bot,'_run_strategies',run), patch.object(m.requests.sessions.Session,'request',forbidden):
    with patch.object(m,'_write_v80_subb_overview',lambda *a,**k:None), patch.object(m,'_write_v80_subc_overview',lambda *a,**k:None), patch.object(m,'_write_v80_a_adk_score_details',lambda *a,**k:None):
        bot._handle_live_params()
        bot._handle_live_params()
text = ''.join(lines)
(Path(__file__).parent/'params_panel.txt').write_text(text,encoding='utf-8')
result = {'fetch_calls':len(fetch_calls),'strategy_calls':len(run_calls),
          'still_unconfirmed':'盘中快照，尚未确认' in text,
          'reference_target':'盘中参考目标（待收盘确认）' in text,
          'contradictory_header':'基于收盘数据' in text}
assert len(fetch_calls)==1 and len(run_calls)==1
assert result['still_unconfirmed'] and result['reference_target']
assert not result['contradictory_header']
assert '未确认行情快照' in text
assert 'A股收盘:' not in text
# Separate boundary probes avoid simply rerunning the supplied closure test cases.
checks=[]
for now,tick,expected in [('11:30:30','11:30:00',True),('12:59:59','11:30:00',True),('13:00:01','11:30:00',False),('14:30:00','14:24:59',False),('14:30:00','14:25:00',True),('09:29:59','09:30:00',False)]:
    with patch.object(m,'beijing_now',lambda:pd.Timestamp('2026-10-29 '+now).to_pydatetime()):
        observed=m._cn_quote_time_valid('2026-10-29 '+tick,pd.Timestamp('2026-10-29').date())
    checks.append({'now':now,'tick':tick,'expected':expected,'observed':observed})
    assert observed==expected
result['boundary_checks']=checks
(Path(__file__).parent/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))

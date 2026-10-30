"""Offline counterexamples from the independent audit, now rejection contracts."""
import importlib.util
import io
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import pytest

@pytest.fixture(scope='module')
def m():
    p = Path(__file__).resolve().parents[1] / 'mnt_bot V 8.0 plus.py'
    spec = importlib.util.spec_from_file_location('v80_closure', p)
    mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

@pytest.fixture(autouse=True)
def offline(m, monkeypatch):
    def forbidden(*a, **k): raise AssertionError('Network forbidden')
    monkeypatch.setattr(m.requests.sessions.Session, 'request', forbidden)

@pytest.mark.parametrize('now,tick,valid', [
    ('14:30', '09:30', False), ('14:30', '12:30', False),
    ('15:10', '14:59', False), ('15:10', '15:00', False),
    ('14:30', '14:59', False), ('14:30', '14:29', True),
    ('12:30', '11:30', True), ('12:30', '11:20', False),
    ('13:01', '11:30', False), ('13:01', '13:00', True),
])
def test_time_contract(m, monkeypatch, now, tick, valid):
    monkeypatch.setattr(m, 'beijing_now', lambda: pd.Timestamp('2026-10-29 ' + now).to_pydatetime())
    assert m._cn_quote_time_valid('2026-10-29 ' + tick, pd.Timestamp('2026-10-29').date()) == valid

@pytest.mark.parametrize('provider', ['tencent', 'sina'])
@pytest.mark.parametrize('tick,code,expected', [('14:29:00','930955',123.), ('14:59:00','930955',None), ('09:30:00','930955',None), ('12:30:00','930955',None), ('14:29:00','000905',None)])
def test_fallbacks_share_timestamp_and_identity_gate(m, monkeypatch, provider, tick, code, expected):
    monkeypatch.setattr(m, 'beijing_now', lambda: pd.Timestamp('2026-10-29 14:30').to_pydatetime())
    if provider == 'tencent':
        fields = [''] * 32; fields[2]=code; fields[3]='123'; fields[30]='20261029'+tick.replace(':','')
        body = f'v_sh{code}="' + '~'.join(fields) + '";'
    else:
        fields = [''] * 33; fields[3]='123'; fields[30]='2026-10-29'; fields[31]=tick
        body = f'var hq_str_sh{code}="' + ','.join(fields) + '";'
    class R:
        def __init__(self, content): self.content=content
        def raise_for_status(self): pass
        def json(self): return {'data':None}
    def get(url, **k):
        matches = ('qt.gtimg' in url) if provider == 'tencent' else ('hq.sinajs' in url)
        return R(body.encode('gb18030') if matches else b'')
    monkeypatch.setattr(m.requests, 'get', get)
    assert m._fetch_cn_realtime_close('1.930955') == expected

def test_existing_today_is_refreshed_or_removed(m, monkeypatch):
    monkeypatch.setattr(m, 'beijing_now', lambda: pd.Timestamp('2026-10-29 14:30').to_pydatetime())
    frame=pd.DataFrame({'close':[100.,101.]}, index=pd.to_datetime(['2026-10-28','2026-10-29']))
    monkeypatch.setattr(m, '_fetch_cn_realtime_close', lambda *a: 102.)
    result=m._supplement_today_close(frame,'1.930955',pd.Timestamp('2026-10-29').date())
    assert result.iloc[-1]['close']==102. and result.iloc[-1]['is_live_bar']
    monkeypatch.setattr(m, '_fetch_cn_realtime_close', lambda *a: None)
    result=m._supplement_today_close(frame,'1.930955',pd.Timestamp('2026-10-29').date())
    assert result.index[-1]==pd.Timestamp('2026-10-28')

def test_after_close_does_not_supplement(m, monkeypatch):
    monkeypatch.setattr(m, 'beijing_now', lambda: pd.Timestamp('2026-10-29 15:10').to_pydatetime())
    def forbidden(*a): raise AssertionError('No realtime supplementation after close')
    monkeypatch.setattr(m, '_fetch_cn_realtime_close', forbidden)
    frame=pd.DataFrame({'close':[100.]}, index=pd.to_datetime(['2026-10-28']))
    assert m._supplement_today_close(frame,'1.930955',pd.Timestamp('2026-10-29').date()) is frame

def test_holiday_not_reported_as_missing_today(m, monkeypatch):
    monkeypatch.setattr(m, 'beijing_now', lambda: pd.Timestamp('2026-10-01 14:00').to_pydatetime())
    frame=pd.DataFrame({'holding':['cash'],'weight':[0.]},index=pd.to_datetime(['2026-09-30']))
    out=io.StringIO();m._write_a_adk_query_overview(out.write,frame,None,query_kind='live_signal')
    assert '今日Sub-A实时数据不完整' not in out.getvalue()

def test_required_close_rejects_retained_live_flag(m, monkeypatch):
    monkeypatch.setattr(m, 'beijing_now', lambda: pd.Timestamp('2026-10-29 15:10').to_pydatetime())
    frame=pd.DataFrame({'close':[101.], 'is_live_bar':[True]},index=pd.to_datetime(['2026-10-29']))
    with pytest.raises(m.DataSchemaError, match='unconfirmed snapshot'):
        m._assert_cn_raw_prices_fresh({'x':frame},['x'],pd.Timestamp('2026-10-29'),'test')
    frame['is_live_bar']=False
    m._assert_cn_raw_prices_fresh({'x':frame},['x'],pd.Timestamp('2026-10-29'),'test')

@pytest.mark.parametrize('snapshot', [False, True])
def test_real_handler_clock_crossing_and_request_cache(m, monkeypatch, snapshot):
    clock=[pd.Timestamp('2026-10-29 14:59').to_pydatetime()]; lines=[]; calls=[]
    dates=pd.to_datetime(['2026-10-27','2026-10-28','2026-10-29'])
    raw={code:pd.DataFrame({'close':[100.,101.,102.],'is_live_bar':[False,False,True]},index=dates) for code in m.CN_STOCK_CODES}
    if not snapshot: raw['1.930955']=raw['1.930955'].iloc[:-1]
    class Msg:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def write(self,text): lines.append(text)
    bot=m.CombinedStrategyV80()
    def fetch(msg,**kw):
        calls.append(1)
        cn=m._build_cn_stock_close_frame(m._align_partial_cn_intraday(raw,m.CN_STOCK_CODES,clock[0],pd.Timestamp('2026-10-28'),msg))
        return cn,cn,cn,cn
    def compute(cn,dk,us,prod):
        clock[0]=pd.Timestamp('2026-10-29 15:01').to_pydatetime()
        result=pd.DataFrame({'holding':['cash','1.930955'],'weight':[0.,1.]},index=cn.index[-2:])
        return defaultdict(lambda:None,cn_date=cn.index[-1],dk_date=dk.index[-1],us_date=us.index[-1],cn_result=result,cn_dk_result=None,us_rot_result=us,subc_vs_info={})
    monkeypatch.setattr(m,'beijing_now',lambda:clock[0]);monkeypatch.setattr(m,'_sm',Msg)
    monkeypatch.setattr(bot,'_fetch_data',fetch);monkeypatch.setattr(bot,'_compute_signal_data',compute)
    for name in ['_write_v80_subb_overview','_write_v80_subc_overview','_write_v80_a_adk_score_details','_write_volume_warning_panel']:
        monkeypatch.setattr(m,name,lambda *a,**k:None)
    bot._handle_live_signal()
    bot._cached_fetch_data(Msg(),include_cn_live_snapshot=True,include_us_live_snapshot=True)
    assert len(calls)==1
    panel=''.join(lines).split('### A策略')[1].split('### ADK')[0]
    assert '收盘目标已确认' not in panel
    assert ('盘中快照，尚未确认' if snapshot else '今日Sub-A实时数据不完整') in panel

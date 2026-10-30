import importlib.util, sys, json, copy,hashlib
from pathlib import Path
from unittest.mock import patch
import pandas as pd
ROOT=next(parent for parent in Path(__file__).resolve().parents if (parent / 'mnt_bot V 8.0 plus.py').is_file());out=Path(__file__).parent
source=ROOT/'mnt_bot V 8.0 plus.py'
spec=importlib.util.spec_from_file_location('v80_source_reaudit',source);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
T=json.loads((ROOT/'tests/fixtures/v80_realtime_20261029/trends.json').read_text(encoding='utf-8'))['payload']
class Response:
 def __init__(self,p=None,content=b''):self.p=p or {'data':None};self.content=content
 def raise_for_status(self):pass
 def json(self):return self.p
results=[]
def check(name,actual,expected):
 results.append({'case':name,'actual':actual,'expected':expected,'passed':actual==expected})
for now,stamp,expected in [
 ('14:30:00','09:30:00',False),('14:30:00','12:30:00',False),('15:10:00','14:59:00',False),
 ('15:00:00','15:00:00',False),('14:59:59','14:59:00',True),('14:30:00','14:25:00',True),('14:30:00','14:24:59',False),
 ('14:30:00','14:30:01',False),('12:30:00','11:30:00',True),('12:30:00','11:25:00',True),('12:30:00','11:24:59',False),
 ('12:30:00','11:30:01',False),('12:59:59','11:30:00',True),('13:00:00','11:30:00',False),('13:00:00','13:00:00',True),
 ('09:29:59','09:29:59',False),('09:30:00','09:30:00',True)]:
 with patch.object(m,'beijing_now',lambda:pd.Timestamp('2026-10-29 '+now).to_pydatetime()):check('clock_'+now+'_'+stamp,m._cn_quote_time_valid(pd.Timestamp('2026-10-29 '+stamp),pd.Timestamp('2026-10-29').date()),expected)
# Exercise actual primary/trends/fallback routing for prior counterexamples.
for label,now,stamp in [('stale','14:30','09:30'),('lunch','14:30','12:30'),('afterclose','15:10','14:59')]:
 t=copy.deepcopy(T);t['data']['trends']=[f'2026-10-29 {stamp},100,123.45,124,99,1000,10000,123']
 def get(url,**kw):return Response(t if 'trends2' in url and 'secid=2.930955' in url else None)
 with patch.object(m,'beijing_now',lambda:pd.Timestamp('2026-10-29 '+now).to_pydatetime()),patch.object(m.requests,'get',get):
  check(label+'_route',m._fetch_cn_realtime_close('1.930955'),None)
  b=pd.DataFrame({'close':[100.]},index=pd.to_datetime(['2026-10-28']))
  check(label+'_supplement',str(m._supplement_today_close(b,'1.930955',pd.Timestamp('2026-10-29').date()).index[-1]),'2026-10-28 00:00:00')
for provider in ['tencent','sina']:
 for stamp,code,expected in [('14:29:00','930955',321.),('14:59:00','930955',None),('09:30:00','930955',None),('12:30:00','930955',None),('14:29:00','000905',None)]:
  if provider=='tencent':
   f=['']*32;f[2]=code;f[3]='321.0';f[30]='20261029'+stamp.replace(':','');body=('v_sh'+code+'="'+'~'.join(f)+'";').encode('gbk')
  else:
   f=['']*33;f[3]='321.0';f[30]='2026-10-29';f[31]=stamp;body=('var hq_str_sh'+code+'="'+','.join(f)+'";').encode('gb18030')
  def get(url,**kw):return Response(content=body if (provider=='tencent' and 'qt.gtimg' in url) or (provider=='sina' and 'hq.sinajs' in url) else b'')
  with patch.object(m,'beijing_now',lambda:pd.Timestamp('2026-10-29 14:30').to_pydatetime()),patch.object(m.requests,'get',get):check(provider+'_'+stamp+'_'+code,m._fetch_cn_realtime_close('1.930955'),expected)
report={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'results':results,'passed':sum(r['passed'] for r in results),'total':len(results)}
(out/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2));assert report['passed']==report['total']

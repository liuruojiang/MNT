"""Regression cases use actual frozen responses; corruptions are explicit adversarial cases."""
import pathlib,sys,json,copy,unittest,ast,importlib.util
from unittest.mock import patch
import pytest
import numpy as np
import pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1]
FIX=ROOT/'tests/fixtures/v80_verified_data_20261025'
spec=importlib.util.spec_from_file_location('v80_wind_data_guard_tests',ROOT/'tools/wind_interval_guard.py')
guard=importlib.util.module_from_spec(spec);sys.modules[spec.name]=guard;spec.loader.exec_module(guard)
parse_index_kline=guard.parse_index_kline
parse_csindex_reference=guard.parse_csindex_reference
validate_long_short=guard.validate_long_short
fetch_checked_index=guard.fetch_checked_index
WindIntervalConflict=guard.WindIntervalConflict

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def load():
 p=ROOT/'mnt_bot V 8.0 plus.py';spec=importlib.util.spec_from_file_location('candidate_v80',p);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m
M=load()
Y=read(FIX/'yahoo_kmlm.json')['chart']['result'][0]
def fix(y=None,ticker='KMLM'):
 r=Y if y is None else y
 return M._repair_verified_kmlm_distribution(ticker,r['timestamp'],r['indicators']['quote'][0],r['indicators']['adjclose'][0]['adjclose'])
def sohu():
 data=read(FIX/'sohu_cyb_gap.json')[0]['hq']
 f=pd.DataFrame([{'date':r[0],'close':float(r[2]),'volume':float(r[7]),'amount':float(r[8]),'source':'Sohu amount'} for r in data]);f.index=pd.to_datetime(f.pop('date'));return f.sort_index()
LONG=parse_index_kline(read(FIX/'wind_bad_long_tail.json'))
SHORT_PAYLOAD=read(FIX/'wind_short.json')
SHORT=parse_index_kline(SHORT_PAYLOAD)
SESSIONS=SHORT.index
official=pd.DataFrame(read(FIX/'csi_zz1000_reference.json')['data']);official.index=pd.to_datetime(official.tradeDate)
REFERENCE=parse_csindex_reference(read(FIX/'csi_zz1000_reference.json'))

@pytest.fixture(autouse=True)
def offline(monkeypatch):
 M._V80_INTEGRITY_CONFLICTS.clear()
 M._V80_INTEGRITY_COVERAGE.clear()
 monkeypatch.setattr(M,'_V80_INTEGRITY_GENERATION',0)
 monkeypatch.setattr(M,'_latest_us_required_close_date',lambda *a,**k:pd.Timestamp('2026-10-23'))
 def forbidden(*args,**kwargs):raise AssertionError('Network/LLM is forbidden in data repair regressions')
 monkeypatch.setattr(M.requests.sessions.Session,'request',forbidden)
 if hasattr(M.poe,'call'):monkeypatch.setattr(M.poe,'call',forbidden)
 monkeypatch.setattr(M.time,'sleep',lambda *_:None)

class CorporateActionTests(unittest.TestCase):
 def test_real_event_matches_verified_math(self):
  a,note=fix();ix=pd.to_datetime(Y['timestamp'],unit='s',utc=True).normalize();ip=ix.get_loc(pd.Timestamp('2022-12-27',tz='UTC'));ie=ix.get_loc(pd.Timestamp('2022-12-28',tz='UTC'))
  close=Y['indicators']['quote'][0]['close'];self.assertAlmostEqual(a[ie]/a[ip],close[ie]/(close[ip]-4.0377),places=12);self.assertIn('verified',note)
 def test_repair_matches_prior_full_replay_candidate(self):
  expected=pd.read_csv(FIX/'kmlm_expected_adjusted.csv',index_col=0,parse_dates=True)
  np.testing.assert_allclose(fix()[0],expected.adj_close,rtol=1e-13,atol=1e-13)
 def test_input_not_mutated(self):
  before=copy.deepcopy(Y);fix();self.assertEqual(Y,before)
 def test_other_asset_unchanged(self):
  a,n=fix(ticker='DBMF');self.assertIs(a,Y['indicators']['adjclose'][0]['adjclose']);self.assertEqual(n,'')
 def test_double_application_no_change(self):
  a,_=fix();y=copy.deepcopy(Y);y['indicators']['adjclose'][0]['adjclose']=a;b,n=fix(y);self.assertEqual(a,b);self.assertIn('upstream-complete',n)
 def test_unknown_implied_distribution_refused(self):
  y=copy.deepcopy(Y);y['indicators']['adjclose'][0]['adjclose']=list(y['indicators']['quote'][0]['close'])
  with self.assertRaises(M.VerifiedDataRepairConflict):fix(y)
 def test_anchor_missing_refused(self):
  y=copy.deepcopy(Y);i=pd.to_datetime(y['timestamp'],unit='s',utc=True).get_loc(pd.Timestamp('2022-12-28 14:30:00',tz='UTC'));y['timestamp'][i]+=86400
  with self.assertRaises(M.VerifiedDataRepairConflict):fix(y)
 def test_nan_anchor_refused(self):
  y=copy.deepcopy(Y);ix=pd.to_datetime(y['timestamp'],unit='s',utc=True).normalize();i=ix.get_loc(pd.Timestamp('2022-12-27',tz='UTC'));y['indicators']['adjclose'][0]['adjclose'][i]=float('nan')
  with self.assertRaises(M.VerifiedDataRepairConflict):fix(y)
 def test_after_event_slice_no_repair(self):
  r={'timestamp':[pd.Timestamp('2023-01-03',tz='UTC').timestamp()], 'indicators':{'quote':[{'close':[30.]}],'adjclose':[{'adjclose':[29.]}]}}
  self.assertEqual(fix(r),([29.],''))
 def test_before_event_slice_no_return_change(self):
  r={'timestamp':[pd.Timestamp('2021-01-04',tz='UTC').timestamp()], 'indicators':{'quote':[{'close':[30.]}],'adjclose':[{'adjclose':[29.]}]}}
  self.assertEqual(fix(r),([29.],''))
 def test_conflict_does_not_fall_back_to_stooq(self):
  with patch.object(M,'_fetch_us_yahoo',side_effect=M.VerifiedDataRepairConflict('counterexample')),patch.object(M,'_fetch_us_stooq') as fallback:
   with self.assertRaises(M.VerifiedDataRepairConflict):M.fetch_yahoo('KMLM')
   fallback.assert_not_called()
 def test_no_change_on_or_after_event(self):
  a,_=fix();ix=pd.to_datetime(Y['timestamp'],unit='s',utc=True).normalize();raw=Y['indicators']['adjclose'][0]['adjclose']
  for i in np.flatnonzero(ix>=pd.Timestamp('2022-12-28',tz='UTC')):self.assertEqual(a[i],raw[i])
 def test_pre_event_returns_unchanged(self):
  a,_=fix();ix=pd.to_datetime(Y['timestamp'],unit='s',utc=True).normalize();before=ix<pd.Timestamp('2022-12-28',tz='UTC')
  raw=pd.Series(Y['indicators']['adjclose'][0]['adjclose'])[before].pct_change()
  repaired=pd.Series(a)[before].pct_change();np.testing.assert_allclose(raw,repaired,atol=1e-12,rtol=1e-12,equal_nan=True)

class AmountTests(unittest.TestCase):
 def test_only_one_actual_gap_is_filled(self):
  f=sohu();g=M._repair_verified_suba_amount_gap(M.CN_SA_VOLUME_CYB_SECID,f)
  self.assertEqual(len(g),len(f)+1);pd.testing.assert_frame_equal(g.drop(pd.Timestamp('2018-12-14')),f,check_flags=False,check_names=True)
  self.assertEqual(g.loc['2018-12-14','amount'],1691008.799204)
 def test_input_not_mutated(self):
  f=sohu();before=f.copy(deep=True);M._repair_verified_suba_amount_gap(M.CN_SA_VOLUME_CYB_SECID,f);pd.testing.assert_frame_equal(f,before)
 def test_idempotent(self):
  g=M._repair_verified_suba_amount_gap(M.CN_SA_VOLUME_CYB_SECID,sohu());h=M._repair_verified_suba_amount_gap(M.CN_SA_VOLUME_CYB_SECID,g);pd.testing.assert_frame_equal(g,h)
 def test_upstream_correct_value_preserved(self):
  f=sohu();f.loc[pd.Timestamp('2018-12-14'),['amount']]=1691008.80;f=f.sort_index();g=M._repair_verified_suba_amount_gap(M.CN_SA_VOLUME_CYB_SECID,f);self.assertIs(g,f)
 def test_existing_wider_market_amount_refused(self):
  f=sohu();f.loc[pd.Timestamp('2018-12-14'),'amount']=5141963.26;f=f.sort_index()
  with self.assertRaises(M.VerifiedDataRepairConflict):M._repair_verified_suba_amount_gap(M.CN_SA_VOLUME_CYB_SECID,f)
 def test_unit_mismatch_refused(self):
  f=sohu();f['amount']*=10000
  with self.assertRaises(M.VerifiedDataRepairConflict):M._repair_verified_suba_amount_gap(M.CN_SA_VOLUME_CYB_SECID,f)
 def test_missing_neighbor_refused(self):
  f=sohu().drop(pd.Timestamp('2018-12-13'))
  with self.assertRaises(M.VerifiedDataRepairConflict):M._repair_verified_suba_amount_gap(M.CN_SA_VOLUME_CYB_SECID,f)
 def test_post_gap_range_and_other_index_untouched(self):
  for secid,f in [(M.CN_SA_VOLUME_CYB_SECID,sohu().loc['2019':]),('1.000016',sohu())]:self.assertIs(M._repair_verified_suba_amount_gap(secid,f),f)
 def test_conflict_does_not_use_wider_fallback(self):
  with patch.object(M,'_fetch_cn_sohu_amount',side_effect=M.VerifiedDataRepairConflict('wrong basis')),patch.object(M,'_fetch_cn_eastmoney_amount') as fallback:
   with self.assertRaises(M.VerifiedDataRepairConflict):M._fetch_cn_amount_with_fallback(M.CN_SA_VOLUME_CYB_SECID,'CYB')
   fallback.assert_not_called()
 def test_public_source_provenance_propagates(self):
  g=M._repair_verified_suba_amount_gap(M.CN_SA_VOLUME_CYB_SECID,sohu())
  with patch.object(M,'_fetch_cn_sohu_amount',return_value=g):
   f,source=M._fetch_cn_amount_with_fallback(M.CN_SA_VOLUME_CYB_SECID,'CYB');self.assertIn('CNI-399006-20181214',source)
 def test_existing_zero_can_be_repaired_only_with_valid_neighbors(self):
  f=sohu();f.loc[pd.Timestamp('2018-12-14'),'amount']=0.;f=f.sort_index()
  g=M._repair_verified_suba_amount_gap(M.CN_SA_VOLUME_CYB_SECID,f);self.assertEqual(g.loc['2018-12-14','amount'],1691008.799204)

class WindTests(unittest.TestCase):
 def test_invalid_offset_minutes_rejected(self):
  for offset in ['+02:99','-02:60']:
   with self.subTest(offset=offset):
    value=copy.deepcopy(SHORT_PAYLOAD);decoded=json.loads(value['result']['content'][0]['text'])
    for row in decoded['data']['rows']:row[0]=row[0][:-6]+offset
    value['result']['content'][0]['text']=json.dumps(decoded)
    with self.assertRaises(WindIntervalConflict):parse_index_kline(value)
 def check(self,a=None,b=None,**kw):
  kw.setdefault('reference',REFERENCE)
  return validate_long_short(SHORT if a is None else a,SHORT if b is None else b,start='2026-10-19',end='2026-10-23',confirmed_sessions=SESSIONS,**kw)
 def test_verified_same_window_passes_reference(self):
  g=self.check(reference=REFERENCE);pd.testing.assert_frame_equal(g,SHORT);self.assertTrue(g.attrs['wind_interval_validation']['independent_reference'])
 def test_observed_bad_long_response_rejected(self):
  with self.assertRaisesRegex(WindIntervalConflict,'missing|conflict'):
   validate_long_short(LONG,SHORT,start='2026-10-12',end='2026-10-23',confirmed_sessions=LONG.index.union(SESSIONS),reference=REFERENCE)
 def test_bad_close_detected_with_complete_tail(self):
  bad=SHORT.copy();bad.loc['2026-10-21','close']=6820.63
  with self.assertRaisesRegex(WindIntervalConflict,'close'):self.check(bad)
 def test_bad_volume_detected(self):
  bad=SHORT.copy();bad.loc['2026-10-21','volume']=11393373900
  with self.assertRaisesRegex(WindIntervalConflict,'volume'):self.check(bad)
 def test_missing_tail_rejected(self):
  with self.assertRaisesRegex(WindIntervalConflict,'missing'):self.check(SHORT.iloc[:-1])
 def test_interior_omission_rejected(self):
  with self.assertRaisesRegex(WindIntervalConflict,'missing'):self.check(SHORT.drop(pd.Timestamp('2026-10-20')))
 def test_same_wrong_data_needs_reference(self):
  bad=SHORT.copy();bad.loc['2026-10-21','close']=6820.63
  with self.assertRaisesRegex(WindIntervalConflict,'reference'):self.check(bad,bad,reference=REFERENCE)
 def test_duplicate_rejected(self):
  with self.assertRaises(WindIntervalConflict):self.check(pd.concat([SHORT,SHORT.iloc[-1:]]))
 def test_nan_rejected(self):
  bad=SHORT.copy();bad.iloc[-1,0]=np.nan
  with self.assertRaises(WindIntervalConflict):self.check(bad)
 def test_impossible_range_rejected(self):
  bad=SHORT.copy();bad.loc['2026-10-21','close']=8000
  with self.assertRaises(WindIntervalConflict):self.check(bad)
 def test_volume_hands_vs_shares_rejected(self):
  bad=SHORT.copy();bad.volume/=100
  with self.assertRaisesRegex(WindIntervalConflict,'volume'):self.check(bad)
 def test_non_session_rejected(self):
  bad=SHORT.copy();bad.loc[pd.Timestamp('2026-10-24')]=bad.iloc[-1];bad=bad.sort_index()
  with self.assertRaises(WindIntervalConflict):self.check(bad)
 def test_missing_reference_day_rejected(self):
  with self.assertRaisesRegex(WindIntervalConflict,'reference'):self.check(reference=REFERENCE.iloc[:-1])
 def test_bad_schema_rejected(self):
  with self.assertRaises(WindIntervalConflict):parse_index_kline({'error':{'message':'fixture error'}})
 def test_boolean_price_fields_refused(self):
  with self.assertRaises(WindIntervalConflict):self.check(SHORT.astype(bool),SHORT.astype(bool))
 def test_ambiguous_symbol_rejected_without_fetch(self):
  calls=[]
  with self.assertRaises(WindIntervalConflict):fetch_checked_index(lambda *a:calls.append(a),windcode='中证1000',start='2026-10-19',end='2026-10-23',confirmed_sessions=SESSIONS)
  self.assertEqual(calls,[])
 def test_transport_failure_never_returns_long_alone(self):
  calls=[]
  def fetch(*args):
   calls.append(args)
   if len(calls)==2:raise TimeoutError('explicit counterexample')
   return SHORT_PAYLOAD
  with self.assertRaisesRegex(WindIntervalConflict,'transport'):fetch_checked_index(fetch,windcode='000852.SH',start='2026-10-19',end='2026-10-23',confirmed_sessions=SESSIONS,tail_sessions=2)
  self.assertEqual(len(calls),2)
 def test_successful_fetch_calls_both_ranges(self):
  calls=[]
  def fetch(*args):calls.append(args);return SHORT_PAYLOAD
  g=fetch_checked_index(fetch,windcode='000852.SH',start='2026-10-19',end='2026-10-23',confirmed_sessions=SESSIONS,reference=REFERENCE)
  self.assertEqual(len(calls),2);self.assertEqual(len(g),5)
 def test_short_query_uses_requested_exchange_sessions(self):
  calls=[]
  def fetch(code,start,end):
   calls.append((code,start,end));v=copy.deepcopy(SHORT_PAYLOAD);v['result'].setdefault('_meta',{})['requestId']='explicit-unit-fixture-'+str(len(calls));data=json.loads(v['result']['content'][0]['text']);data['data']['rows']=[r for r in data['data']['rows'] if start<=r[0][:10]<=end];v['result']['content'][0]['text']=json.dumps(data);return v
  fetch_checked_index(fetch,windcode='000852.SH',start='2026-10-19',end='2026-10-23',confirmed_sessions=SESSIONS,tail_sessions=2,reference=REFERENCE.loc['2026-10-22':])
  self.assertEqual(calls[1],('000852.SH','2026-10-22','2026-10-23'))
 def test_success_does_not_mutate_input_frame(self):
  x=SHORT.copy(deep=True);self.check();pd.testing.assert_frame_equal(x,SHORT)
 def test_duplicate_required_sessions_refused(self):
  with self.assertRaises(WindIntervalConflict):validate_long_short(SHORT,SHORT,start='2026-10-19',end='2026-10-23',confirmed_sessions=SESSIONS.append(SESSIONS[-1:]))

class IndependentReviewRegressions(unittest.TestCase):
 def corrected(self):return fix()[0]
 def test_partially_repaired_prefix_rejected_at_several_seams(self):
  corrected=self.corrected();days=pd.to_datetime(Y['timestamp'],unit='s',utc=True).tz_localize(None).normalize()
  for seam in ['2020-12-31','2021-12-28','2021-12-29','2022-06-01','2022-12-23']:
   with self.subTest(seam=seam):
    value=copy.deepcopy(Y);a=value['indicators']['adjclose'][0]['adjclose']
    for i in np.flatnonzero(days<=pd.Timestamp(seam)):a[i]=corrected[i]
    with self.assertRaises(M.VerifiedDataRepairConflict):fix(value)
 def test_upstream_complete_branch_still_checks_prefix(self):
  value=copy.deepcopy(Y);a=self.corrected();value['indicators']['adjclose'][0]['adjclose']=a
  days=pd.to_datetime(Y['timestamp'],unit='s',utc=True).tz_localize(None).normalize()
  for i in np.flatnonzero(days<=pd.Timestamp('2022-12-23')):a[i]=Y['indicators']['adjclose'][0]['adjclose'][i]
  with self.assertRaises(M.VerifiedDataRepairConflict):fix(value)
 def test_complete_upstream_three_decimal_rounding_is_preserved(self):
  value=copy.deepcopy(Y);a=self.corrected();days=pd.to_datetime(Y['timestamp'],unit='s',utc=True).tz_localize(None).normalize();ip=days.get_loc(pd.Timestamp('2022-12-27'));p=Y['indicators']['quote'][0]['close'][ip]
  scale=(1-4.038/p)/(1-4.0377/p)
  for i in np.flatnonzero(days<pd.Timestamp('2022-12-28')):a[i]*=scale
  value['indicators']['adjclose'][0]['adjclose']=a;b,note=fix(value);self.assertIs(b,a);self.assertIn('upstream-complete',note)
 def test_cash_total_return_convention_is_not_misidentified_as_missing_cash(self):
  value=copy.deepcopy(Y);a=value['indicators']['adjclose'][0]['adjclose'];days=pd.to_datetime(Y['timestamp'],unit='s',utc=True).tz_localize(None).normalize();ip=days.get_loc(pd.Timestamp('2022-12-27'));ie=days.get_loc(pd.Timestamp('2022-12-28'));q=value['indicators']['quote'][0]['close'];old=(a[ip]/q[ip])/(a[ie]/q[ie]);scale=(q[ie]/(q[ie]+4.0377))/old
  for i in np.flatnonzero(days<pd.Timestamp('2022-12-28')):a[i]*=scale
  with self.assertRaises(M.VerifiedDataRepairConflict):fix(value)
 def test_upstream_correct_suba_target_cannot_skip_wrong_units(self):
  f=sohu();f.loc[pd.Timestamp('2018-12-14'),'amount']=1691008.799204;f=f.sort_index();f.loc[pd.to_datetime(['2018-12-13','2018-12-17']),'amount']*=10000
  with self.assertRaises(M.VerifiedDataRepairConflict):M._repair_verified_suba_amount_gap(M.CN_SA_VOLUME_CYB_SECID,f)
 def test_integrity_conflict_is_not_a_transient_fetch_error(self):
  e=M.VerifiedDataRepairConflict('deliberate integrity counterexample');self.assertFalse(isinstance(e,M._DATA_FETCH_ERRORS))
 def test_actual_suba_loader_does_not_swallow_deterministic_conflict(self):
  d=read(FIX/'csi_zz2000_amount.json')['data'];z=pd.DataFrame(d);z.index=pd.to_datetime(z.tradeDate);z=z[['tradingValue']].rename(columns={'tradingValue':'amount'})
  def amount(secid,*args,**kwargs):
   if secid==M.CN_SA_VOLUME_CYB_SECID:raise M.VerifiedDataRepairConflict('explicit amount integrity conflict')
   return z.copy(),'frozen actual CSI amount'
  with patch.object(M,'_fetch_cn_amount_with_fallback',side_effect=amount):
   with self.assertRaises(M.VerifiedDataRepairConflict):M._load_suba_volume_signal(expected_date=pd.Timestamp('2026-10-23'))
 def test_allow_unresolved_signal_path_still_rejects_integrity_conflict(self):
  cn=pd.read_csv(FIX/'cn_close_control.csv',index_col=0,parse_dates=True);cr=pd.read_csv(FIX/'cn_result_control.csv',index_col=0,parse_dates=True)
  for allow in [False,True]:
   with self.subTest(allow_unresolved=allow),patch.object(M,'_add_cn_bond_column',return_value=cn),patch.object(M,'run_cn_strategy',return_value=cr.copy()),patch.object(M,'_load_suba_volume_signal',side_effect=M.VerifiedDataRepairConflict('explicit deterministic conflict')):
    with self.assertRaises(M.VerifiedDataRepairConflict):M.CombinedStrategyV80()._run_strategies(cn,cn,cn,cn,allow_unresolved_suba_volume=allow)
 def test_mixed_prefix_refused_by_real_fetch_yahoo_without_stooq(self):
  payload=copy.deepcopy(Y);corrected=self.corrected();days=pd.to_datetime(Y['timestamp'],unit='s',utc=True).tz_localize(None).normalize()
  for i in np.flatnonzero(days<=pd.Timestamp('2022-12-23')):payload['indicators']['adjclose'][0]['adjclose'][i]=corrected[i]
  class Response:
   status_code=200
   def json(self):return {'chart':{'result':[payload]}}
  with patch.object(M._session,'get',return_value=Response()),patch.object(M,'_fetch_us_stooq') as fallback:
   with self.assertRaises(M.VerifiedDataRepairConflict):M.fetch_yahoo('KMLM')
   fallback.assert_not_called()
 def test_mixed_json_boolean_rejected_before_numeric_coercion(self):
  v=copy.deepcopy(SHORT_PAYLOAD);d=json.loads(v['result']['content'][0]['text']);col=[c['name'] for c in d['data']['columns']].index('VOLUME');d['data']['rows'][0][col]=True;v['result']['content'][0]['text']=json.dumps(d)
  with self.assertRaises(WindIntervalConflict):parse_index_kline(v)
 def test_impossible_timezone_and_wrong_declared_volume_unit_rejected(self):
  for offset in ['+99:99','+02:99','-02:60']:
   v=copy.deepcopy(SHORT_PAYLOAD);d=json.loads(v['result']['content'][0]['text'])
   for row in d['data']['rows']:row[0]=row[0][:-6]+offset
   v['result']['content'][0]['text']=json.dumps(d)
   with self.subTest(offset=offset),self.assertRaises(WindIntervalConflict):parse_index_kline(v)
  v=copy.deepcopy(SHORT_PAYLOAD);d=json.loads(v['result']['content'][0]['text']);d['data'].setdefault('unit',{})['VOLUME 单位：']='手';v['result']['content'][0]['text']=json.dumps(d)
  with self.assertRaises(WindIntervalConflict):parse_index_kline(v)
 def test_coincident_queries_require_external_reference_before_fetch(self):
  calls=[]
  with self.assertRaises(WindIntervalConflict):fetch_checked_index(lambda *a:calls.append(a),windcode='000852.SH',start='2026-10-19',end='2026-10-23',confirmed_sessions=SESSIONS)
  self.assertEqual(calls,[])
 def test_vendor_frame_or_copy_cannot_self_certify(self):
  for reference in [SHORT,SHORT.copy()]:
   with self.assertRaises(WindIntervalConflict):validate_long_short(SHORT,SHORT,start='2026-10-19',end='2026-10-23',confirmed_sessions=SESSIONS,reference=reference)
 def test_wrong_reference_index_rejected(self):
  v=read(FIX/'csi_zz1000_reference.json')
  for row in v['data']:row['indexCode']='000905'
  ref=parse_csindex_reference(v)
  with self.assertRaises(WindIntervalConflict):fetch_checked_index(lambda *a:SHORT_PAYLOAD,windcode='000852.SH',start='2026-10-19',end='2026-10-23',confirmed_sessions=SESSIONS,reference=ref)
 def test_distinct_ranges_cannot_reuse_same_receipt(self):
  def fetch(code,start,end):
   v=copy.deepcopy(SHORT_PAYLOAD);d=json.loads(v['result']['content'][0]['text']);d['data']['rows']=[r for r in d['data']['rows'] if start<=r[0][:10]<=end];v['result']['content'][0]['text']=json.dumps(d);return v
  with self.assertRaisesRegex(WindIntervalConflict,'receipt'):fetch_checked_index(fetch,windcode='000852.SH',start='2026-10-19',end='2026-10-23',confirmed_sessions=SESSIONS,tail_sessions=2,reference=REFERENCE.loc['2026-10-22':])
 def test_legal_offset_preserves_daily_label_and_declared_shares(self):
  v=copy.deepcopy(SHORT_PAYLOAD);d=json.loads(v['result']['content'][0]['text']);d['data'].setdefault('unit',{})['VOLUME 单位：']='股';v['result']['content'][0]['text']=json.dumps(d)
  g=parse_index_kline(v);self.assertEqual(g.index.strftime('%Y-%m-%d').tolist(),SESSIONS.strftime('%Y-%m-%d').tolist())
 def test_fixture_hashes_are_checkout_portable(self):
  import hashlib
  manifest=read(FIX/'manifest.json')
  for row in manifest['files']:
   data=(FIX/row['file']).read_bytes().replace(b'\r\n',b'\n');self.assertEqual(hashlib.sha256(data).hexdigest(),row['sha256_lf'])

if __name__=='__main__':unittest.main(verbosity=2)

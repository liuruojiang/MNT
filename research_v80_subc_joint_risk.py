"""Joint C risk sizing through the unchanged production contribution/execution ledger."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
from unittest.mock import patch
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'quant_param_scan_runs/20260910_momentum_v80_subc_joint_risk'
SOURCE=ROOT/'mnt_bot V 8.0 plus.py'
FROZEN=ROOT/'outputs/v80_external_review_20260907'
spec=importlib.util.spec_from_file_location('v80_c_joint',SOURCE)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
sha=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
inputs=pd.read_pickle(FROZEN/'new_replay_inputs.pkl')
saved=pd.read_pickle(FROZEN/'new_replay_results.pkl')
expected=pd.read_pickle(FROZEN/'new_daily_returns.pkl')['Sub-C']
prices=inputs['frames'][3];opens=inputs['us_open']
components=m._compute_daily_subc_components_phased(prices,saved[4],m.PROD_CASH,prod_sig_b=saved[5],blend_a=m.PROD_BLEND_A)
index=components.index;raw=components.base_return
base,base_eq,base_cost=m._apply_subc_vol_scaling(raw,prices,components=components,us_open=opens,strict_open_execution=True)
base_gold=m._subc_relative_scale(prices[m.PROD_GOLD_VS_SIGNAL_TICKER],index,m.PROD_GOLD_VS_SHORT_WINDOW,m.PROD_GOLD_VS_LONG_WINDOW,m.PROD_VS_MIN_LEV,m.PROD_VS_MAX_LEV,m.PROD_VS_THRESHOLD)
pd.testing.assert_series_equal(base,expected,check_names=False,check_exact=False,atol=1e-12,rtol=0)
parity=float((base-expected).abs().max())
print('BASELINE PARITY',parity,flush=True)
assets=list(m.PROD_PORTFOLIO)
scaled=np.array([m.PROD_PORTFOLIO[a]['cls']=='equity' or a=='GLDM' for a in assets])
assert components[[f'signal::{a}' for a in assets]].eq(1).all().all()
asset_rets=pd.DataFrame({a:prices[cfg['proxy']].pct_change(fill_method=None) for a,cfg in m.PROD_PORTFOLIO.items()})
CASES=[('current_sleeves',None,None),('joint_diag10',.10,1.),('joint_corr10',.10,.5),('joint_corr08',.08,.5),('joint_corr12',.12,.5)]
WINDOW=63
covariances={}
for dt in index:
    history=asset_rets.loc[:dt].tail(WINDOW)
    if len(history)<WINDOW or history.isna().any().any():continue
    covariances[dt]=history.cov().to_numpy()*m.US_TRADING_DAYS
first_signal=min(covariances)
first_pos=index.get_loc(first_signal)+1
assert first_pos<len(index)
common_start=index[first_pos]
print('COMMON SAMPLE',common_start,index[-1],flush=True)
all_returns={'current_sleeves':base};scales={'current_equity':base_eq,'current_gold':base_gold}
details=[];diagnostics=[];costs={'current_sleeves':base_cost}
for name,target,shrink in CASES[1:]:
    raw_target=pd.Series(np.nan,index=index)
    state=[]
    for dt,full_cov in covariances.items():
        cov=(1-shrink)*full_cov+shrink*np.diag(np.diag(full_cov))
        weights=components.loc[dt,[f'close_weight::{a}' for a in assets]].to_numpy(float)
        e=weights*scaled;u=weights*(~scaled)
        aa=float(e@cov@e);bb=float(e@cov@u);cc=float(u@cov@u)
        low,high=m.PROD_VS_MIN_LEV,m.PROD_VS_MAX_LEV
        minimum=float(np.clip(-bb/aa,low,high))
        minrisk=aa*minimum**2+2*bb*minimum+cc
        feasible=minrisk<=target**2+1e-12
        if feasible:
            if aa*high**2+2*bb*high+cc<=target**2:
                value=high
            else:
                value=float(np.clip((-bb+np.sqrt(max(0,bb*bb-aa*(cc-target**2))))/aa,low,high))
        else:value=minimum
        assert low-1e-10<=value<=high+1e-10
        raw_target.loc[dt]=value
        state.append({'date':dt,'candidate':name,'raw_scale':value,'target':target,
                      'feasible_under_bounds':feasible,'minimum_predicted_vol':np.sqrt(minrisk),
                      'raw_predicted_vol':np.sqrt(aa*value**2+2*bb*value+cc),
                      'aa':aa,'bb':bb,'cc':cc})
    actual=m._subc_threshold_scale(raw_target,m.PROD_VS_THRESHOLD)
    # Identical production lag/deadband semantics and independent sleeve accounting.
    with patch.object(m,'_subc_absolute_scale',return_value=actual),patch.object(m,'_subc_relative_scale',return_value=actual):
        candidate,returned_scale,fee=m._apply_subc_vol_scaling(raw,prices,components=components,us_open=opens,strict_open_execution=True)
    pd.testing.assert_series_equal(actual,returned_scale)
    assert candidate.index.equals(base.index) and np.isfinite(candidate).all()
    all_returns[name]=candidate;scales[name]=actual;costs[name]=fee
    for row in state:
        # Signal-date implied carried next-day scale; price gaps remain unknowable.
        pos=index.get_loc(row['date'])
        next_scale=actual.iloc[pos+1] if pos+1<len(index) else np.nan
        row['next_actual_scale']=next_scale
        row['next_scale_predicted_vol']=np.sqrt(row['aa']*next_scale**2+2*row['bb']*next_scale+row['cc']) if pd.notna(next_scale) else np.nan
    frame=pd.DataFrame(state);details.extend(state)
    valid=frame[frame.date>=common_start]
    diagnostics.append({'candidate':name,'infeasible_signal_days':int((~valid.feasible_under_bounds).sum()),
                        'forecast_over_target_after_deadband_days':int((valid.next_scale_predicted_vol>target+1e-8).sum()),
                        'mean_scale':float(actual.loc[common_start:].mean()),
                        'scale_changes':int((actual.loc[common_start:].diff().abs()>1e-10).sum())})
    print('DONE',name,diagnostics[-1],flush=True)

daily=pd.DataFrame(all_returns).loc[common_start:]
scale_frame=pd.DataFrame(scales)
daily.to_csv(OUT/'daily_returns.csv');scale_frame.to_csv(OUT/'scales.csv')
pd.DataFrame(costs).to_csv(OUT/'scale_execution_costs.csv')
pd.DataFrame(details).to_csv(OUT/'risk_forecasts.csv',index=False)
pd.DataFrame(diagnostics).to_csv(OUT/'risk_diagnostics.csv',index=False)
components.to_pickle(OUT/'base_components.pkl')
rows=[];unavailable={}
for case in daily:
    unavailable[case]={}
    for segment,years in [('full',None),('last_10y',10),('last_5y',5),('last_3y',3),('last_1y',1)]:
        start=common_start if years is None else daily.index[-1]-pd.DateOffset(years=years)
        if years and start<common_start:
            reason=f'Common history after 63-session risk warmup starts {common_start.date()}; insufficient {years} years.'
            unavailable[case][segment]=reason
            rows.append(dict(candidate=case,segment=segment,start=str(common_start.date()),end=str(index[-1].date()),rows=0,ann_return='N/A',ann_vol='N/A',sharpe_repo='N/A',max_dd='N/A',na_reason=reason))
            continue
        r=daily.loc[start:,case]
        earlier=prices.index[prices.index<daily.index[0]]
        if len(earlier)==0:raise ValueError('Sub-C first return lacks preceding source close')
        metric=m.calc_daily_metrics(r,0,m.US_TRADING_DAYS,history_returns=daily[case],first_period_start=earlier[-1])
        rows.append(dict(candidate=case,segment=segment,start=str(r.index[0].date()),end=str(r.index[-1].date()),rows=len(r),ann_return=metric['annual']/100,ann_vol=metric['vol']/100,sharpe_repo=metric['sharpe'],max_dd=metric['max_dd']/100,na_reason=''))
summary=pd.DataFrame(rows);baseline=summary[summary.candidate=='current_sleeves'].set_index('segment')
summary['return_delta_pp']=[100*(x.ann_return-baseline.loc[x.segment,'ann_return']) if x.rows else 'N/A' for x in summary.itertuples()]
summary['drawdown_improvement_pp']=[100*(x.max_dd-baseline.loc[x.segment,'max_dd']) if x.rows else 'N/A' for x in summary.itertuples()]
summary.to_csv(OUT/'scan_summary.csv',index=False)
wide=[]
for case,group in summary.groupby('candidate',sort=False):
    row={'candidate':case}
    for x in group.itertuples():row['ann_return_'+x.segment]=x.ann_return;row['max_dd_'+x.segment]=x.max_dd
    wide.append(row)
pd.DataFrame(wide).to_csv(OUT/'window_metrics.csv',index=False)
years=(daily.index[-1]-daily.index[0]).days/365.25
pd.DataFrame([{'candidate':k,'annual_scale_cost_sum':v.loc[common_start:].sum()/years} for k,v in costs.items()]).to_csv(OUT/'cost_summary.csv',index=False)
meta=json.loads((OUT/'scan_meta.json').read_text())
meta.update(source_hashes={str(SOURCE):sha},data_snapshot={'path':str(FROZEN/'new_replay_inputs.pkl'),'sha256':hashlib.sha256((FROZEN/'new_replay_inputs.pkl').read_bytes()).hexdigest(),'start':str(common_start),'end':str(index[-1]),'basis':'Frozen production C including designated proxy/live splices; not all-live ETF or fresh market validation'},unavailable_segments=unavailable,parity_check={'max_daily_return_error':parity},cost_model={'execution':'Production next adjusted open scale transitions; annual base MOC unchanged','scale_fee_bps':m.PROD_VS_REBAL_COST_BPS,'financing_spread_bps':m.PROD_VS_SPREAD_BPS},warnings=['Joint replaces separate stock/gold scaling, never stacks on it','No change to base assets/weights or unscaled bond/CTA/BTC','Risk floor/deadband can leave estimated risk above nominal target','No independent latest-data or all-live ETF acceptance','Compare C alone, not a refreshed full V8 portfolio'],cache_write_risk='Research artifacts only',joint_spec={'window':WINDOW,'shrinkage':.5,'primary_target':.10,'target_neighbors':[.08,.12],'scale_bounds':[.5,1.5],'deadband':.35,'lag':1})
(OUT/'scan_meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
(OUT/'verification.json').write_text(json.dumps({'baseline_parity':parity,'finite_daily_returns':True,'production_source_unchanged':hashlib.sha256(SOURCE.read_bytes()).hexdigest()==sha,'same_base_components':True,'unchanged_bond_cta_btc_scaling':True,'common_start':str(common_start)},indent=2))
plt.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
fig,axes=plt.subplots(2,1,figsize=(10,10))
labels={'current_sleeves':'现有分袖','joint_diag10':'联合10%：忽略相关性','joint_corr10':'联合10%：收缩协方差','joint_corr08':'联合8%','joint_corr12':'联合12%'}
for ax,y in zip(axes,[None,3]):
    d=daily if y is None else daily.loc[daily.index[-1]-pd.DateOffset(years=y):]
    nav=(1+d).cumprod()
    for c in daily:ax.plot(nav.index,nav[c],label=labels[c],lw=2 if c in ['current_sleeves','joint_corr10'] else 1.2)
    ax.set_title('共同样本' if y is None else '近3年');ax.set_ylabel('累计净值');ax.grid(alpha=.2);ax.legend(fontsize=9)
fig.suptitle('V8.0 Sub-C：现有分袖与联合风险控制\n冻结数据截至2026-09-04；保留原代理拼接与执行成本',fontsize=13)
fig.tight_layout(rect=[0,0,1,.94]);fig.savefig(OUT/'nav_comparison.png',dpi=150)
print(summary.to_string(index=False),flush=True)

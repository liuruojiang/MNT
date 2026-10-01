"""Frozen, selection-preserving Sub-B allocation experiment; no production edits."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
from collections import Counter
import numpy as np
import pandas as pd
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'quant_param_scan_runs/20260910_momentum_v80_subb_correlation_allocation'
SOURCE = ROOT / 'mnt_bot V 8.0 plus.py'
FROZEN = ROOT / 'outputs/v80_external_review_20260907'
spec = importlib.util.spec_from_file_location('v80_corr_research', SOURCE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
inputs = pd.read_pickle(FROZEN / 'new_replay_inputs.pkl')
saved = pd.read_pickle(FROZEN / 'new_replay_results.pkl')[2]
close, opens = inputs['frames'][2], inputs['us_open']
returns = close.pct_change(fill_method=None)
source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
CASES = [('inverse_vol', 63, None), ('diagonal_minvar', 63, 1.0),
         ('corr63', 63, 0.5), ('corr42', 42, 0.5), ('corr126', 126, 0.5)]
originals = {name: getattr(m, name) for name in ['_us_raw_weights', '_v80_b78_us_raw_weights']}
baseline_calls = {}
audit = []
weight_rows = []

def make_wrapper(fname, case, window, shrink, stats):
    counts = Counter()
    def wrapped(mom_row, vol_row, *args, **kwargs):
        raw = originals[fname](mom_row, vol_row, *args, **kwargs)
        dt = pd.Timestamp(vol_row.name)
        assert dt in returns.index, ('missing signal timestamp', vol_row.name)
        counts[dt] += 1
        key = (fname, dt.isoformat(), counts[dt])
        selected = tuple(sorted(a for a, w in raw.items() if a != 'BIL' and w > 0))
        signature = (selected, round(raw.get('BIL', 0.0), 12))
        if case == 'inverse_vol':
            baseline_calls[key] = signature
        else:
            assert baseline_calls.get(key) == signature, ('selection/cash changed', key, signature, baseline_calls.get(key))
        stats['calls'] += 1
        if shrink is None or len(selected) < 2:
            return raw
        stats['multi_asset_calls'] += 1
        assets = list(selected)
        total = sum(raw[a] for a in assets)
        base = np.array([raw[a] / total for a in assets])
        sigma = vol_row.loc[assets].to_numpy(float)
        if shrink == 1:
            corr = np.eye(len(assets))
        else:
            history = returns.loc[:dt, assets].tail(window).dropna()
            if len(history) < window:
                stats['insufficient_history_fallback'] += 1
                return raw
            corr = history.corr().to_numpy()
            if not np.isfinite(corr).all():
                stats['invalid_corr_fallback'] += 1
                return raw
            corr = (1-shrink)*corr + shrink*np.eye(len(assets))
        cov = corr * np.outer(sigma, sigma)
        objective_cov = cov / max(float(np.trace(cov)), 1e-12)
        fit = minimize(lambda x: float(x @ objective_cov @ x), base,
                       jac=lambda x: 2*objective_cov@x, method='SLSQP',
                       bounds=list(zip(0.5*base, np.minimum(1.5*base, 1))),
                       constraints={'type':'eq', 'fun':lambda x:x.sum()-1,
                                    'jac':lambda x:np.ones(len(x))},
                       options={'ftol':1e-12, 'maxiter':100})
        assert fit.success, (key, fit.message)
        x = fit.x
        assert abs(x.sum()-1) < 1e-8
        assert np.all(x >= 0.5*base-1e-8) and np.all(x <= 1.5*base+1e-8)
        assert x@cov@x <= base@cov@base+1e-9
        result = dict(raw)
        for a, b, w in zip(assets, base, x):
            result[a] = float(w*total)
            weight_rows.append({'candidate':case,'family':fname,'date':dt,'call':counts[dt],
                                'asset':a,'original_weight':b*total,'new_weight':w*total})
        assert set(result) == set(raw) and abs(sum(result.values())-sum(raw.values())) < 1e-8
        stats['optimized_calls'] += 1
        stats['allocation_l1_sum'] += float(np.abs(x-base).sum())
        return result
    return wrapped

def stream(result, name):
    frame = result.attrs['v80_b78'] if name == 'B78' else result
    return pd.Series(frame['return'].to_numpy(copy=True), index=frame.index.copy())

all_returns, account_stats, parity = {}, [], {}
baseline_result = None
for case, window, shrink in CASES:
    print('START', case, flush=True)
    stats = Counter()
    for fname in originals:
        setattr(m, fname, make_wrapper(fname, case, window, shrink, stats))
    result = m._run_v80_subb_variants(close, us_open=opens, strict_open_execution=True)
    if baseline_result is None:
        baseline_result = result
        for name in ['B78', 'B79']:
            a, b = stream(result,name), stream(saved,name)
            pd.testing.assert_series_equal(a,b,check_exact=False,atol=1e-12,rtol=0)
            parity[name] = float((a-b).abs().max())
        (OUT/'parity.json').write_text(json.dumps(parity,indent=2))
        print('PARITY',parity,flush=True)
    for name in ['B78','B79']:
        frame = result.attrs['v80_b78'] if name=='B78' else result
        baseframe = baseline_result.attrs['v80_b78'] if name=='B78' else baseline_result
        pd.testing.assert_series_equal(frame['is_signal'],baseframe['is_signal'])
        for col in frame.columns:
            if 'selected' in col or 'inflation_pressure_on' in col:
                pd.testing.assert_series_equal(frame[col],baseframe[col])
        r = stream(result,name)
        all_returns[(case,name)] = r
        years=(r.index[-1]-r.index[0]).days/365.25
        account_stats.append({'candidate':case,'sleeve':name,
                              'turnover_per_year':float(frame['subb_effective_turnover'].sum()/years),
                              'execution_cost_per_year':float(frame['subb_effective_cost'].sum()/years)})
    r78,r79 = stream(result,'B78'),stream(result,'B79')
    nav=0.5*(1+r78).cumprod()+0.5*(1+r79).cumprod()
    r=nav.pct_change();r.iloc[0]=nav.iloc[0]-1
    all_returns[(case,'B_combined')]=r
    result.to_pickle(OUT/f'{case}_accounts.pkl')
    audit.append({'candidate':case,**dict(stats),'selection_cash_and_signal_parity':'passed'})
    pd.DataFrame(audit).to_csv(OUT/'allocation_audit.csv',index=False)
    pd.DataFrame(weight_rows).to_csv(OUT/'allocation_changes.csv',index=False)
    pd.DataFrame(all_returns).to_csv(OUT/'daily_returns.csv')
    print('DONE',case,dict(stats),flush=True)
for name, function in originals.items():
    setattr(m,name,function)

rows=[]
for (case,sleeve),ret in all_returns.items():
    for segment,years in [('full',None),('last_10y',10),('last_5y',5),('last_3y',3),('last_1y',1)]:
        r=ret if years is None else ret.loc[ret.index[-1]-pd.DateOffset(years=years):]
        earlier=close.index[close.index<ret.index[0]]
        if len(earlier)==0:raise ValueError('Sub-B first return lacks preceding source close')
        metric=m.calc_daily_metrics(r,0.0,m.US_TRADING_DAYS,history_returns=ret,first_period_start=earlier[-1])
        rows.append(dict(candidate=case,sleeve=sleeve,segment=segment,start=str(r.index[0].date()),end=str(r.index[-1].date()),rows=len(r),ann_return=metric['annual']/100,ann_vol=metric['vol']/100,sharpe_repo=metric['sharpe'],max_dd=metric['max_dd']/100))
df=pd.DataFrame(rows)
base=df[df.candidate=='inverse_vol'].set_index(['sleeve','segment'])
df['return_delta_pp']=[100*(x.ann_return-base.loc[(x.sleeve,x.segment),'ann_return']) for x in df.itertuples()]
df['drawdown_improvement_pp']=[100*(x.max_dd-base.loc[(x.sleeve,x.segment),'max_dd']) for x in df.itertuples()]
df.to_csv(OUT/'all_sleeve_metrics.csv',index=False)
summary=df[df.sleeve=='B_combined'].copy()
summary.to_csv(OUT/'scan_summary.csv',index=False)
wide=[]
for case,group in summary.groupby('candidate',sort=False):
    row={'candidate':case}
    for x in group.itertuples():
        row['ann_return_'+x.segment]=x.ann_return
        row['max_dd_'+x.segment]=x.max_dd
    wide.append(row)
pd.DataFrame(wide).to_csv(OUT/'window_metrics.csv',index=False)
pd.DataFrame(account_stats).to_csv(OUT/'turnover.csv',index=False)
meta=json.loads((OUT/'scan_meta.json').read_text())
meta.update(data_snapshot={'path':str(FROZEN/'new_replay_inputs.pkl'),'sha256':hashlib.sha256((FROZEN/'new_replay_inputs.pkl').read_bytes()).hexdigest(),'start':str(close.index[0]),'end':str(close.index[-1]),'rows':len(close),'basis':'Frozen accepted production phased/proxy history; not all-live-ETF history'},source_hashes={str(SOURCE):source_sha},parity_check=parity,candidates=CASES,cost_model={'execution':'T close -> T+1 adjusted open; production net account, financing and daily VolReg retained','commission':m.US_ROT_COMMISSION},warnings=['Frozen through 2026-09-04; not latest market performance','Long history retains original proxy/phased availability','Vol scaling rules unchanged but endogenous scales may change with candidate return history','Initial equal B account capital, drift thereafter; no daily cross-account rebalance'],cache_write_risk='Research artifacts only',source_change_rule='Never modify production source')
(OUT/'scan_meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==source_sha
print(summary.to_string(index=False),flush=True)

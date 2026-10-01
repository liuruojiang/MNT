"""Frozen production-path Sub-B cadence comparison; no production edits."""
import hashlib
import importlib.util
import json
import pickle
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'quant_param_scan_runs/20260910_momentum_v80_subb_rebalance_period'
SOURCE = ROOT / 'mnt_bot V 8.0 plus.py'
FROZEN = ROOT / 'outputs/v80_adversarial_fixes_20260907'
spec = importlib.util.spec_from_file_location('v80_cadence', SOURCE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
inputs = pickle.loads((FROZEN / 'new_replay_inputs.pkl').read_bytes())
saved = pickle.loads((FROZEN / 'new_replay_results.pkl').read_bytes())[2]
close, opens = inputs['frames'][2], inputs['us_open']
original = m._us_signal_days
original78 = m._v80_b78_us_signal_days
anchor = pd.Timestamp('2008-12-15')

def schedule(period, phase=0):
    def select(frame, start):
        if period == 'monthly':
            # Only completed calendar months; signal on last actual US session.
            groups = {}
            for i in range(start, len(frame)):
                dt = frame.index[i]
                if dt.to_period('M') < frame.index[-1].to_period('M'):
                    groups[dt.to_period('M')] = i
            return set(groups.values())
        weekly = original(frame, start)
        return {i for i in weekly if ((frame.index[i].normalize() - pd.Timedelta(days=frame.index[i].dayofweek) - anchor).days // 7) % period == phase}
    return select

def run():
    return m._run_v80_subb_variants(close, us_open=opens, strict_open_execution=True)

baseline_path = OUT / 'weekly_accounts.pkl'
baseline = pd.read_pickle(baseline_path) if baseline_path.exists() else run()
parity = {}
for name, a, b in [('B79', baseline, saved), ('B78', baseline.attrs['v80_b78'], saved.attrs['v80_b78'])]:
    pd.testing.assert_index_equal(a.index, b.index)
    error = float((a['return'] - b['return']).abs().max())
    parity[name] = error
    assert error <= 1e-12, parity
(OUT / 'parity.json').write_text(json.dumps(parity, indent=2))
print('BASELINE PARITY', parity, flush=True)
cases = [('weekly', 1, 0), ('biweekly', 2, 0), ('three_weekly', 3, 0), ('monthly', 'monthly', 0), ('biweekly_phase1', 2, 1), ('three_weekly_phase1', 3, 1), ('three_weekly_phase2', 3, 2)]
daily, summaries = {}, []
for name, period, phase in cases:
    print('RUN', name, flush=True)
    m._us_signal_days = m._v80_b78_us_signal_days = schedule(period, phase)
    cached = OUT / (name + '_accounts.pkl')
    result = baseline if name == 'weekly' else (pd.read_pickle(cached) if cached.exists() else run())
    b78 = result.attrs['v80_b78']
    r79 = pd.Series(result['return'].to_numpy(copy=True), index=result.index.copy())
    r78 = pd.Series(b78['return'].to_numpy(copy=True), index=b78.index.copy())
    # Match the official performance portfolio: initially equal account NAVs,
    # without inventing daily cross-account rebalancing.
    nav = 0.5 * (1+r79).cumprod() + 0.5 * (1+r78).cumprod()
    ret = nav.pct_change()
    ret.iloc[0] = nav.iloc[0] - 1.0
    assert ret.notna().all() and np.isfinite(ret).all()
    daily[name] = ret
    result.to_pickle(OUT / (name + '_accounts.pkl'))
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    summaries.append({'candidate':name, 'signal_days_per_year':float(result['is_signal'].sum()/years), 'turnover_per_year':float((result['subb_effective_turnover'].sum()+b78['subb_effective_turnover'].sum())/2/years), 'execution_cost_per_year':float((result['subb_effective_cost'].sum()+b78['subb_effective_cost'].sum())/2/years)})
    pd.DataFrame(daily).to_csv(OUT / 'daily_returns.csv')
    print('DONE', name, flush=True)
m._us_signal_days, m._v80_b78_us_signal_days = original, original78
rows, wide = [], []
for name, ret in daily.items():
    wr = {'candidate':name}
    for seg, years in [('full',None),('last_10y',10),('last_5y',5),('last_3y',3),('last_1y',1)]:
        start = None if years is None else ret.index[-1]-pd.DateOffset(years=years)
        r = ret if start is None else ret.loc[start:]
        earlier = close.index[close.index < ret.index[0]]
        if len(earlier) == 0:
            raise ValueError('Sub-B first return lacks preceding source close')
        metric = m.calc_daily_metrics(r, 0.0, m.US_TRADING_DAYS, history_returns=ret, first_period_start=earlier[-1])
        row = dict(candidate=name,segment=seg,start=str(r.index[0].date()),end=str(r.index[-1].date()),rows=len(r),ann_return=metric['annual']/100,ann_vol=metric['vol']/100,sharpe_repo=metric['sharpe'],max_dd=metric['max_dd']/100)
        rows.append(row)
        wr['ann_return_'+seg], wr['max_dd_'+seg] = row['ann_return'],row['max_dd']
    wide.append(wr)
df=pd.DataFrame(rows)
base=df[df.candidate=='weekly'].set_index('segment')
df['return_delta_pp']=[100*(r.ann_return-base.loc[r.segment,'ann_return']) for r in df.itertuples()]
df['drawdown_improvement_pp']=[100*(r.max_dd-base.loc[r.segment,'max_dd']) for r in df.itertuples()]
df.to_csv(OUT/'scan_summary.csv',index=False)
pd.DataFrame(wide).to_csv(OUT/'window_metrics.csv',index=False)
pd.DataFrame(summaries).to_csv(OUT/'turnover.csv',index=False)
meta=json.loads((OUT/'scan_meta.json').read_text(encoding='utf-8'))
meta.update(data_snapshot={'path':str(FROZEN/'new_replay_inputs.pkl'),'sha256':hashlib.sha256((FROZEN/'new_replay_inputs.pkl').read_bytes()).hexdigest(),'start':str(close.index[0]),'end':str(close.index[-1]),'rows':len(close),'basis':'Frozen production phased/proxy history; not all-live-ETF inception history'},parity_check=parity,source_hashes={str(SOURCE):hashlib.sha256(SOURCE.read_bytes()).hexdigest()},cost_model={'execution':'T close -> T+1 adjusted open -> T+1 close; original independent accounts, daily VolReg and financing retained','commission':m.US_ROT_COMMISSION},baseline={'candidate':'weekly'},warnings=['Frozen through 2026-09-04; no live refresh','Long history uses original proxy and phased availability; no all-live-ETF formal claim'],cache_write_risk='None: frozen pickle read, research artifacts only')
(OUT/'scan_meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
print(df.to_string(index=False),flush=True)

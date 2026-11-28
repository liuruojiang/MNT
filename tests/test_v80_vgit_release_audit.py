"""V8.0 VGIT release-specific source, inception and execution regressions."""
from pathlib import Path
import importlib.util
import sys
import numpy as np
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def b():
    path=ROOT/'mnt_bot V 8.0 plus.py'
    if not path.exists(): path=ROOT/'tools/v80_vgit_release_candidate.py'
    spec=importlib.util.spec_from_file_location('v80_vgit_release_audit',path)
    module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module)
    return module


def test_inception_and_shared_panel_contract(b):
    assert 'VGIT' in b._us_rot_late_history_tickers()
    assert 'VGIT' in b._v80_b78_US_ROT_POOL and 'AGG' not in b._v80_b78_US_ROT_POOL
    assert not {'VGIT','AGG'}.intersection(b.US_ROT_POOL)
    fake=pd.DataFrame({'open':[1.],'close':[1.]},index=pd.to_datetime(['2009-11-20']))
    fake.attrs['provider_first_trade_date']='2009-11-20'
    assert b._us_history_expected_start('VGIT','2003-01-01',fake)==pd.Timestamp('2009-11-23')
    with pytest.raises((ValueError,b.poe.BotError),match='VGIT'):
        b._assert_us_internal_price_history({'VGIT':fake},['VGIT'])
    with pytest.raises(ValueError,match='native'):
        b._run_v80_subb_v78(fake.rename(columns={'close':'VGIT'}),strict_open_execution=True)


@pytest.mark.parametrize('fault',[0,None,np.nan,-1,True,0.5])
def test_zero_and_unverified_native_open_mask(b,fault):
    dates=pd.to_datetime(['2026-11-25','2026-11-27'])
    frame=pd.DataFrame({'open':[57.,58.],'close':[57.,58.],'volume':pd.Series([1200,fault],index=dates,dtype=object)},index=dates)
    opens=b._build_us_open_execution_dict({'VGIT':frame});close=frame[['close']].rename(columns={'close':'VGIT'})
    assert opens['VGIT'].iloc[0]==57 and pd.isna(opens['VGIT'].iloc[-1])
    assert dates[-1] in b._valid_us_ohlc_index(frame)
    with pytest.raises(ValueError,match='VGIT'):
        b._v80_b78_us_open_row(dates[-1],['VGIT'],opens,close,strict=True)


def test_missing_internal_native_close_refused(b):
    dates=b._expected_us_ohlc_index('2020-01-02','2020-04-01')
    frame=pd.DataFrame({'VGIT':100.,'SPY':100.},index=dates); frame.iloc[10,0]=np.nan
    with pytest.raises(ValueError,match='native close history'):
        b._run_v80_subb_v78(frame,strict_open_execution=True)


def test_yahoo_native_volume_and_identity(b,monkeypatch):
    dates=pd.to_datetime(['2026-11-25','2026-11-27'])
    stamps=[int((x+pd.Timedelta(hours=15)).tz_localize('UTC').timestamp()) for x in dates]
    result={'meta':{'symbol':'VGIT'},'timestamp':stamps,'indicators':{'quote':[{'open':[57.,58.],'close':[57.,58.],'volume':[12345,0]}],'adjclose':[{'adjclose':[57.,58.]}]}}
    class Response:
        status_code=200
        def json(self): return {'chart':{'result':[result]}}
    monkeypatch.setattr(b._session,'get',lambda *args,**kwargs:Response())
    got=b._fetch_us_yahoo('VGIT'); assert list(got.volume)==[12345,0]
    result['meta']['symbol']='AGG'
    with pytest.raises((ValueError,b.DataSchemaError),match='identity'):
        b._fetch_us_yahoo('VGIT')


def test_nasdaq_gap_volume_conflict_preserves_price_but_not_executability(b):
    dates=pd.to_datetime(['2026-11-25','2026-11-27'])
    primary=pd.DataFrame({'open':[57.,np.nan],'close':[57.,58.],'volume':[10,0]},index=dates)
    fallback=pd.DataFrame({'open':[57.,58.],'close':[57.,58.],'volume':[10,100]},index=dates)
    got,n=b._merge_same_ticker_gap_prices(primary,fallback,dates[-1:],'VGIT')
    assert got.at[dates[-1],'open']==58 and pd.isna(got.at[dates[-1],'volume'])
    assert pd.isna(b._build_us_open_execution_dict({'VGIT':got})['VGIT'].loc[dates[-1]])


@pytest.mark.parametrize('volume',[0,None,np.nan,-1,True])
def test_live_vgit_without_native_liquidity_keeps_confirmed_prefix(b,volume):
    prior=pd.Timestamp('2026-11-25'); live=pd.Timestamp('2026-11-27')
    frame=pd.DataFrame({'open':[57.,58.],'close':[57.,58.],'volume':pd.Series([1000,volume],index=[prior,live],dtype=object)},index=[prior,live])
    status={'status':'current','asof':prior,'reason':'','intraday_snapshot':False}
    class Msg:
        def write(self,*a): pass
    got=b._v80_us_live_panel({'VGIT':frame.loc[:prior]}, {'VGIT':frame}, ['VGIT'],live,status,Msg())
    assert status['status']=='partial_intraday' and got['VGIT'].index[-1]==prior

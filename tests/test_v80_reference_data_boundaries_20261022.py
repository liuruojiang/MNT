"""Retain IPO warmup, BTC cutoff, data integrity and explicit VolReg contracts.

Synthetic inputs below are diagnostic; no strategy performance is reported.
"""
import copy
import importlib.util
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('V80_AUDIT_SOURCE', str(ROOT / 'mnt_bot V 8.0 plus.py')))


@pytest.fixture(scope='module')
def boundary_v80():
    spec = importlib.util.spec_from_file_location('v80_retained_data_boundaries', SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(scope='module')
def boundary_market(boundary_v80):
    file = ROOT / 'tests/test_v80_live_model_reference_20261021.py'
    spec = importlib.util.spec_from_file_location('v80_retained_fixture_donor', file)
    donor = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = donor
    spec.loader.exec_module(donor)
    market = donor.market.__wrapped__(boundary_v80)
    sys.modules.pop(spec.name, None)
    return market


def sample(module, market, label):
    close, opens, b79 = market
    result = b79.attrs['v80_b78'] if label == 'B7.8' else b79
    pool = module._v80_b78_US_ROT_POOL if label == 'B7.8' else module.US_ROT_POOL
    return close.copy(deep=True), copy.deepcopy(result), list(pool)


def reference(module, close, result, label):
    return module._v80_subb_model_reference_weights(close, result, label)


@pytest.mark.parametrize('label', ['B7.8', 'B7.9'])
def test_leading_nan_in_optional_etf_is_allowed(boundary_v80, boundary_market, label):
    close, result, pool = sample(boundary_v80, boundary_market, label)
    asset = 'DBMF' if 'DBMF' in pool else pool[-1]
    close.loc[close.index[:100], asset] = np.nan
    weights = reference(boundary_v80, close, result, label)
    assert weights and all(np.isfinite(float(w)) for w in weights.values())


@pytest.mark.parametrize('label', ['B7.8', 'B7.9'])
def test_pre_start_btc_values_are_filtered_before_validation(boundary_v80, boundary_market, label):
    close, result, pool = sample(boundary_v80, boundary_market, label)
    start = boundary_v80._v80_b78_US_ROT_BTC_START if label == 'B7.8' else boundary_v80.US_ROT_BTC_START
    old = pd.DataFrame([close.iloc[0].to_dict()], index=[pd.Timestamp(start) - pd.Timedelta(days=1)])
    old['BTC-USD'] = 'ignored-before-BTC-participation'
    close = pd.concat([old, close])
    weights = reference(boundary_v80, close, result, label)
    assert weights and all(np.isfinite(float(w)) for w in weights.values())


@pytest.mark.parametrize('label', ['B7.8', 'B7.9'])
def test_numeric_conversion_uses_private_copy(boundary_v80, boundary_market, label):
    close, result, pool = sample(boundary_v80, boundary_market, label)
    close['QQQ'] = close['QQQ'].map(lambda value: format(float(value), '.17g'))
    before = pickle.dumps((close, result), protocol=5)
    weights = reference(boundary_v80, close, result, label)
    assert weights and all(np.isfinite(float(w)) for w in weights.values())
    assert pickle.dumps((close, result), protocol=5) == before


@pytest.mark.parametrize('label', ['B7.8', 'B7.9'])
@pytest.mark.parametrize('held_prefix', ['model_w_', 'ema_actual_w_', 'official_actual_w_'])
def test_empty_price_for_asset_held_behind_volreg_is_rejected(boundary_v80, boundary_market, label, held_prefix):
    close, result, pool = sample(boundary_v80, boundary_market, label)
    date = result.index[-1]
    asset = 'QQQ'
    close[asset] = np.nan
    # Isolate a hidden model holding so a second checked field cannot mask a
    # missing guard while the account is in defensive cash.
    for prefix in ('w_', 'actual_w_', 'effective_w_', 'model_w_', 'ema_actual_w_',
                   'official_actual_w_', 'official_w_'):
        result.loc[date, prefix + asset] = 0.0
    result.loc[date, held_prefix + asset] = 0.4
    result.loc[date, 'volreg_defense'] = True
    result.loc[date, 'volreg_ratio'] = 1.2
    with pytest.raises((ValueError, TypeError)):
        reference(boundary_v80, close, result, label)


@pytest.mark.parametrize('label', ['B7.8', 'B7.9'])
@pytest.mark.parametrize('state', [False, True])
def test_explicit_nan_ratio_preserves_known_volreg_state(boundary_v80, boundary_market, label, state):
    close, result, pool = sample(boundary_v80, boundary_market, label)
    date = result.index[-1]
    result.loc[date, 'volreg_defense'] = np.bool_(state)
    result.loc[date, 'volreg_ratio'] = 1.6
    control = reference(boundary_v80, close, result, label)
    result.loc[date, 'volreg_ratio'] = np.nan
    inherited = reference(boundary_v80, close, result, label)
    assert inherited == control


@pytest.mark.parametrize('label', ['B7.8', 'B7.9'])
@pytest.mark.parametrize('fault', ['missing', 'nan', 'string_false', 'integer_one'])
def test_broken_volreg_state_is_not_bool_coerced(boundary_v80, boundary_market, label, fault):
    close, result, pool = sample(boundary_v80, boundary_market, label)
    date = result.index[-1]
    if fault == 'missing':
        result.drop(columns='volreg_defense', inplace=True)
    else:
        result['volreg_defense'] = result['volreg_defense'].astype(object)
        result.loc[date, 'volreg_defense'] = {'nan': np.nan, 'string_false': 'False',
                                             'integer_one': 1}[fault]
    text = []
    boundary_v80._write_v80_subb_model_reference(text.append, result, close, label)
    assert '今日模型参考不可用' in ''.join(text)
    assert '| ETF |' not in ''.join(text)


@pytest.mark.parametrize('label', ['B7.8', 'B7.9'])
@pytest.mark.parametrize('fault', ['missing', 'inf', 'negative'])
def test_broken_volreg_ratio_is_unavailable(boundary_v80, boundary_market, label, fault):
    close, result, pool = sample(boundary_v80, boundary_market, label)
    if fault == 'missing':
        result.drop(columns='volreg_ratio', inplace=True)
    else:
        result.loc[result.index[-1], 'volreg_ratio'] = np.inf if fault == 'inf' else -1.0
    text = []
    boundary_v80._write_v80_subb_model_reference(text.append, result, close, label)
    assert '今日模型参考不可用' in ''.join(text)
    assert '| ETF |' not in ''.join(text)


@pytest.mark.parametrize('label', ['B7.8', 'B7.9'])
@pytest.mark.parametrize('fault', ['nan_latest', 'inf_latest', 'zero_latest', 'negative_latest',
                                   'nan_recent', 'inf_recent'])
def test_invalid_available_asset_prices_are_unavailable(boundary_v80, boundary_market, label, fault):
    close, result, pool = sample(boundary_v80, boundary_market, label)
    asset = max(pool, key=lambda code: float(result.iloc[-1].get('effective_w_' + code, 0.0)))
    row = -2 if fault.endswith('recent') else -1
    value = {'nan': np.nan, 'inf': np.inf, 'zero': 0.0, 'negative': -1.0}[fault.split('_')[0]]
    close.loc[close.index[row], asset] = value
    with pytest.raises(ValueError, match='price'):
        reference(boundary_v80, close, result, label)
    text = []
    boundary_v80._write_v80_subb_model_reference(text.append, result, close, label)
    assert '今日模型参考不可用' in ''.join(text)
    assert '| ETF |' not in ''.join(text)


@pytest.mark.parametrize('label', ['B7.8', 'B7.9'])
def test_empty_unheld_optional_asset_remains_unavailable_to_native_ranking(boundary_v80, boundary_market, label):
    close, result, pool = sample(boundary_v80, boundary_market, label)
    asset = 'DBMF'
    assert asset in pool
    close[asset] = np.nan
    for prefix in ('w_', 'actual_w_', 'effective_w_', 'model_w_', 'ema_actual_w_',
                   'official_actual_w_', 'official_w_'):
        result.loc[result.index[-1], prefix + asset] = 0.0
    weights = reference(boundary_v80, close, result, label)
    assert weights and weights.get(asset, 0.0) == 0.0
    assert all(np.isfinite(float(weight)) for weight in weights.values())

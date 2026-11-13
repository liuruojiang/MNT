"""Independent native-A adversarial replay of the ZZ2000 backup path.

The final 60 ZZ2000 observations come from the real 2026-11-13 fixture.
Earlier amount warmup, all security prices and CYB amounts are synthetic
counterexample/control inputs. These tests do not certify current signals,
returns, complete provider history or deployment. Network/LLM are forbidden.
"""
import ast
import copy
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'mnt_bot V 8.0 plus.py'
SAMPLE = pd.read_csv(ROOT / 'tests/fixtures/v80_zz2000_fallback_20261113.csv')


@pytest.fixture(scope='module')
def bot():
    spec = importlib.util.spec_from_file_location('v80_adversarial_native_zz2000', SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CombinedStrategyBase')
    method = copy.deepcopy(next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == '_run_strategies'))
    stop = next(i for i, n in enumerate(method.body) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'cn_dk_result' for t in n.targets))
    # Exact native A prefix, excluding only unrelated ADK/US/C consumers.
    method.name = '_audit_run_native_a'
    method.body = method.body[:stop] + [ast.Return(value=ast.Name(id='cn_result', ctx=ast.Load()))]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(SOURCE), 'exec'), module.__dict__)
    return module


@pytest.fixture
def native(bot, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Native replay must never call network or LLM')
    monkeypatch.setattr(bot.requests.sessions.Session, 'request', forbidden)
    monkeypatch.setattr(bot.poe, 'call', forbidden)
    monkeypatch.setattr(bot.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(bot, 'beijing_now', lambda: bot.datetime(2026, 11, 13, 18, 30))
    dates = bot._expected_cn_sessions(pd.Timestamp('2025-10-08'), pd.Timestamp('2026-11-13'))
    t = np.arange(len(dates), dtype=float)
    prices = pd.DataFrame({code: 100 * np.exp(.0001*t) for code in bot.CN_EQUITY_CODES}, index=dates)
    prices['1.000016'] = 100 * np.exp(.000006*t*t + .003*np.sin(t/7))
    prices[bot.CN_BOND_CODE] = 100.0
    canonical = pd.DataFrame({'amount': 3000.0 + t, 'close': 3000.0}, index=dates)
    actual_dates = pd.to_datetime(SAMPLE.date)
    canonical.loc[actual_dates, 'amount'] = SAMPLE.csi_amount.fillna(SAMPLE.amount / 1e8).to_numpy()
    official = canonical.loc[:'2026-11-11'].copy()
    backup = canonical.copy()
    backup.loc[actual_dates, 'amount'] = SAMPLE.amount.to_numpy()/1e8
    backup['amount'] *= 1e8  # Native EastMoney amount frame uses CNY.
    clear_cyb = pd.DataFrame({'amount': 100.0+t}, index=dates)
    monkeypatch.setattr(bot, '_fetch_cn_csindex_amount', lambda *a, **k: official.copy())
    monkeypatch.setattr(bot, '_fetch_cn_eastmoney_amount', lambda *a, **k: backup.copy())
    monkeypatch.setattr(bot, '_fetch_cn_sohu_amount', lambda *a, **k: clear_cyb.copy())
    return prices, canonical, official, backup


def run(bot, prices, advisory=False):
    return bot._audit_run_native_a(object(), prices, None, None, None,
                                  allow_unresolved_suba_volume=advisory)


def test_backup_native_a_matches_complete_canonical_history(bot, native, monkeypatch):
    prices, canonical, _, _ = native
    actual = run(bot, prices)
    assert not bool(actual.suba_volume_unresolved.iloc[-1])
    assert 'EastMoney' in actual.suba_volume_zz2000_source.iloc[-1]
    monkeypatch.setattr(bot, '_fetch_cn_csindex_amount', lambda *a, **k: canonical.copy())
    complete = run(bot, prices)
    for field in ['holding', 'holding_fraction', 'weight', 'return', 'nav',
                  'trade_cost', 'effective_turnover', 'suba_top_code',
                  'suba_top_score', 'suba_top_r2', 'scale_raw', 'realized_vol',
                  'suba_volume_rule_on', 'suba_volume_rule_scale']:
        pd.testing.assert_series_equal(actual[field], complete[field], check_flags=False)
    raw = bot.run_cn_strategy(prices, bot.CN_EQUITY_CODES)
    # Overlay returns legitimately change the reported realized volatility;
    # its correct parity oracle is the complete-source run above, not raw NAV.
    for field in ['suba_top_code', 'suba_top_score', 'suba_top_r2', 'scale_raw']:
        pd.testing.assert_series_equal(actual[field], raw[field], check_flags=False)


@pytest.mark.parametrize('fault_date,fault', [
    ('2026-11-12', 'missing'), ('2026-07-01', 'missing'),
    ('2026-11-12', 'nan'), ('2026-11-12', 'zero'), ('2026-11-12', 'inf'),
])
def test_current_primary_with_internal_hole_is_repaired_before_native_execution(bot, native, monkeypatch, fault_date, fault):
    prices, canonical, _, _ = native
    monkeypatch.setattr(bot, '_fetch_cn_csindex_amount', lambda *a, **k: canonical.copy())
    complete = run(bot, prices)
    broken = canonical.copy()
    day = pd.Timestamp(fault_date)
    if fault == 'missing':
        broken.drop(index=day, inplace=True)
    else:
        broken.loc[day, 'amount'] = {'nan': np.nan, 'zero': 0.0, 'inf': np.inf}[fault]
    # Fresh final date alone cannot hide an internal history gap.
    assert broken.index[-1] == pd.Timestamp('2026-11-13')
    monkeypatch.setattr(bot, '_fetch_cn_csindex_amount', lambda *a, **k: broken.copy())
    repaired = run(bot, prices)
    assert not repaired.suba_volume_unresolved.any()
    assert 'EastMoney' in repaired.suba_volume_zz2000_source.iloc[-1]
    for field in ['holding', 'weight', 'return', 'nav', 'trade_cost',
                  'suba_top_r2', 'scale_raw', 'suba_volume_rule_on']:
        pd.testing.assert_series_equal(complete[field], repaired[field], check_flags=False)


@pytest.mark.parametrize('fault_date', ['2026-11-12', '2026-07-01'])
def test_current_or_consumed_history_gap_cannot_become_executable(bot, native, monkeypatch, fault_date):
    prices, _, official, backup = native
    # The July gap is outside today's MA dependency, but inside consumed NAV history.
    day = pd.Timestamp(fault_date)
    official.drop(index=day, errors='ignore', inplace=True)
    backup.drop(index=day, inplace=True)
    with pytest.raises(bot.SubaVolumeDataError, match='不可判定'):
        run(bot, prices)
    advisory = run(bot, prices, advisory=True)
    assert advisory.suba_volume_unresolved.all()
    assert advisory.suba_volume_unavailable.all()
    for kind in ['signal', 'live_signal', 'params', 'live_params']:
        output = []
        info = bot._write_a_adk_query_overview(output.append, advisory, None, query_kind=kind)
        text = ''.join(output)
        assert '诊断目标（不可执行）' in text
        assert '状态不可判定' in text
        assert not info['Sub-A']['is_signal']


@pytest.mark.parametrize('kind', ['signal', 'live_signal', 'params', 'live_params'])
def test_four_surfaces_receive_actual_native_backup_result(bot, native, kind):
    prices, _, _, _ = native
    actual = run(bot, prices)
    output = []
    info = bot._write_a_adk_query_overview(output.append, actual, None, query_kind=kind)
    text = ''.join(output).split('### ADK策略')[0]
    assert 'EastMoney' in text
    assert '诊断目标（不可执行）' not in text
    assert '状态不可判定' not in text
    assert '2026-11-13' in info['Sub-A']['note']


def test_future_backup_rows_do_not_change_native_prefix(bot, native, monkeypatch):
    prices, _, _, backup = native
    cutoff = pd.Timestamp('2026-11-12')
    original = run(bot, prices.loc[:cutoff])
    # A very large future amount must not affect T's MA/streak or execution.
    backup.loc[pd.Timestamp('2026-11-13'), 'amount'] = 9e20
    altered = run(bot, prices.loc[:cutoff])
    for field in ['holding', 'weight', 'return', 'nav', 'trade_cost',
                  'suba_volume_zz2000_streak', 'suba_volume_rule_scale']:
        pd.testing.assert_series_equal(original[field], altered[field], check_flags=False)
    assert altered.index[-1] == cutoff


def test_explicit_cyb_true_resolves_zz_unknown_only_for_known_dates(bot, native, monkeypatch):
    prices, _, _, backup = native
    del_day = pd.Timestamp('2026-11-12')
    backup.drop(index=del_day, inplace=True)
    dates = prices.index
    cyb = pd.DataFrame({'amount': 100.0+np.arange(len(dates), dtype=float)}, index=dates)
    cyb.iloc[-4:, 0] = [80.0, 70.0, 60.0, 50.0]
    monkeypatch.setattr(bot, '_fetch_cn_sohu_amount', lambda *a, **k: cyb.copy())
    signal, feature = bot._load_suba_volume_signal(expected_date=dates[-1])
    assert bool(signal.iloc[-1])
    assert bool(feature.cyb_signal.iloc[-1])
    assert not bool(feature.zz2000_known.iloc[-1])
    assert not bool(feature.combined_unresolved.iloc[-1])
    # A formal NAV still cannot consume preceding unknown dates in this history.
    with pytest.raises(bot.SubaVolumeDataError):
        run(bot, prices)


@pytest.mark.parametrize('kind', ['live_signal', 'live_params'])
def test_preclose_uses_confirmed_amount_and_never_emits_formal_action(bot, native, monkeypatch, kind):
    prices, _, _, backup = native
    monkeypatch.setattr(bot, 'beijing_now', lambda: bot.datetime(2026, 11, 13, 14, 0))
    before = run(bot, prices)
    assert before.suba_volume_freshness_latest_date.iloc[-1] == '2026-11-12'
    backup.loc[pd.Timestamp('2026-11-13'), 'amount'] = 9e20
    after = run(bot, prices)
    for field in ['weight', 'trade_cost', 'suba_volume_rule_on',
                  'suba_volume_rule_scale', 'suba_volume_zz2000_streak']:
        pd.testing.assert_series_equal(before[field], after[field], check_flags=False)
    output = []
    info = bot._write_a_adk_query_overview(output.append, after, None,
                                         cn_intraday=True, query_kind=kind)
    assert '盘中参考目标（待收盘确认）' in ''.join(output)
    assert not info['Sub-A']['is_signal']


def test_four_real_handlers_route_through_shared_native_path():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    methods = {n.name: n for c in tree.body if isinstance(c, ast.ClassDef)
               for n in c.body if isinstance(n, ast.FunctionDef)}
    for name in ['_handle_signal', '_handle_live_signal', '_handle_params', '_handle_live_params']:
        calls = [n for n in ast.walk(methods[name]) if isinstance(n, ast.Call)]
        targets = [n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id if isinstance(n.func, ast.Name) else '' for n in calls]
        assert '_write_a_adk_query_overview' in targets
        assert '_cached_run_strategies' in targets or '_compute_signal_data' in targets
    compute_calls = [n for n in ast.walk(methods['_compute_signal_data']) if isinstance(n, ast.Call)]
    assert any(isinstance(n.func, ast.Attribute) and n.func.attr == '_cached_run_strategies'
               and any(k.arg == 'allow_unresolved_suba_volume' and isinstance(k.value, ast.Constant)
                       and k.value.value is True for k in n.keywords) for n in compute_calls)

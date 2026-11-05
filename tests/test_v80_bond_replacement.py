"""Direct broad-bond replacement: real receipts and stale/conflicting failures."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'research/data_quality/20261105_bond_replacement'
sys.path.insert(0, str(ROOT / 'tools'))
from source_audit import alternative_sources as alt
from source_audit.adapters import project_scope


@pytest.fixture
def bot(monkeypatch):
    spec = importlib.util.spec_from_file_location('v80_bond_replacement', ROOT / 'mnt_bot V 8.0 plus.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected network request')
    monkeypatch.setattr(module.requests.sessions.Session, 'request', forbidden)
    return module


def payloads():
    return {p: json.loads((FIX / (p + '.raw')).read_bytes()) for p in ('tencent', 'sina')}


def test_real_bond_close_crosscheck_and_declared_contract():
    rows, report = alt.assess_prices(payloads(), '2026-11-05', '000012.SH')
    assert len(rows) == 202 and list(rows)[-1] == '2026-11-05'
    assert report['max_abs_difference_from_tencent']['sina'] <= .005000001
    assert report['fields_qualified'] == ['close']
    assert set(rows['2026-11-05']) == {'close'}
    assert set(alt.source_urls('2026-11-05', '000012.SH')) == {'tencent', 'sina'}
    contract = project_scope('combo_v80')
    assert next(r for r in contract['requirements'] if r['requirement_id'] == 'cn_bond_close')['instruments'] == ['000012.SH']


@pytest.mark.parametrize('fault', ['missing', 'conflict', 'wrong_code', 'boolean', 'duplicate'])
def test_bad_bond_evidence_rejected(fault):
    values = copy.deepcopy(payloads())
    if fault == 'missing': values['sina'].pop()
    elif fault == 'conflict': values['sina'][-1].update(close='232.280')
    elif fault == 'wrong_code': values['tencent']['data']['sh000013'] = values['tencent']['data'].pop('sh000012')
    elif fault == 'boolean': values['sina'][-1]['close'] = True
    else: values['sina'].append(values['sina'][-1])
    with pytest.raises(ValueError):
        alt.assess_prices(values, '2026-11-05', '000012.SH')


def test_stale_primary_uses_same_index_backup_and_all_stale_fails(bot, monkeypatch):
    frame = pd.read_csv(FIX / 'native_bond_history.csv', index_col=0, parse_dates=True)
    monkeypatch.setattr(bot, '_fetch_cn_sina', lambda code: frame.iloc[:-1])
    monkeypatch.setattr(bot, '_fetch_cn_qq_kline', lambda code, **kw: frame.copy())
    result, source = bot.fetch_cn_kline(bot.CN_BOND_CODE, required_date='2026-11-05')
    assert source == 'QQ:000012 direct bond index' and result.iloc[-1]['close'] == 232.258
    monkeypatch.setattr(bot, '_fetch_cn_qq_kline', lambda code, **kw: frame.iloc[:-1])
    with pytest.raises(bot.DataUnavailableError):
        bot.fetch_cn_kline(bot.CN_BOND_CODE, required_date='2026-11-05')


def test_direct_live_quote_is_never_h11077_scaled(bot, monkeypatch):
    monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-11-05 10:00').to_pydatetime())
    monkeypatch.setattr(bot, '_fetch_cn_realtime_close', lambda code: 232.25)
    def no_proxy(*a, **kw):
        raise AssertionError('Replacement must never use H11077 proxy scaling')
    monkeypatch.setattr(bot, '_fetch_cn_h_proxy', no_proxy)
    base = pd.DataFrame({'close': [232.209]}, index=pd.to_datetime(['2026-11-04']))
    result = bot._supplement_today_close(base, bot.CN_BOND_CODE, pd.Timestamp('2026-11-05').date())
    assert result.iloc[-1]['close'] == 232.25 and result.iloc[-1]['is_live_bar']
    assert bot.CN_BOND_CODE not in bot.CN_H_PROXY_SECIDS


def test_real_after_close_quotes_do_not_masquerade_as_intraday(bot, monkeypatch):
    monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-11-05 18:13').to_pydatetime())
    day = pd.Timestamp('2026-11-05').date()
    for stamp in ['2026-11-05 16:14', '2026-11-05 15:35:30']:
        assert not bot._cn_quote_time_valid(pd.Timestamp(stamp), day)
    monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-11-05 10:00').to_pydatetime())
    assert bot._cn_quote_time_valid(pd.Timestamp('2026-11-05 09:59'), day)
    assert not bot._cn_quote_time_valid(pd.Timestamp('2026-11-05 09:50'), day)
    assert not bot._cn_quote_time_valid(pd.Timestamp('2026-11-04 10:00'), day)


def test_service_retires_old_bond_without_hiding_other_asset_checks(tmp_path, monkeypatch):
    import run_data_source_service as service
    from audit_cn_sources import ASSETS
    monkeypatch.setattr(service, 'wind_archive', lambda *a: tmp_path / 'archive')
    def forbidden(*a, **kw):
        raise AssertionError('Retired H11077 must not request another official reference')
    monkeypatch.setattr(service, 'refresh_bond_reference', forbidden)
    def run(command, **kw):
        symbols = command[command.index('--symbols') + 1].split(',')
        assert set(symbols) == {a['code'] for a in ASSETS if a['code'] != 'H11077.SH'}
        output = Path(command[command.index('--output') + 1]) / 'fixture'
        output.mkdir(parents=True)
        (output / 'report.json').write_text(json.dumps({'assets': [], 'requests': 0}))
        return type('Result', (), {'stdout': '', 'stderr': '', 'returncode': 0})()
    monkeypatch.setattr(service.subprocess, 'run', run)
    output = tmp_path / 'output'; output.mkdir()
    result = service.cn_run({'store_root': str(tmp_path), 'legacy_wind_archive': 'unused',
        'credentials': {'wind': 'unused'}, 'local_hourly_budgets': {'wind': 30},
        'suba_bond_symbol': '000012.SH', 'alternative_cn_symbols': ['000012.SH'],
        'enabled_alternative_sources': ['tencent', 'sina']},
        output, 'tail', '2026-11-05')
    assert result['retired_suba_bond']['status'] == 'REPLACED_NOT_REPAIRED'
    assert result['official_reference_refresh'] is None

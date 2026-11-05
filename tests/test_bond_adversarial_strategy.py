"""Independent bond audit: real frozen prices, adversarial coverage boundaries."""
import importlib.util
from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'research/data_quality/20261105_bond_replacement/native_bond_history.csv'


@pytest.fixture
def audited_bot(monkeypatch):
    spec = importlib.util.spec_from_file_location('independent_bond_audit', ROOT / 'mnt_bot V 8.0 plus.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'beijing_now', lambda: pd.Timestamp('2026-11-05 18:30').to_pydatetime())
    def forbidden(*args, **kwargs):
        raise AssertionError('Independent audit must not access the network')
    monkeypatch.setattr(module.requests.sessions.Session, 'request', forbidden)
    return module


def history():
    return pd.read_csv(FIX, index_col=0, parse_dates=True)


def install_sources(bot, monkeypatch, frame):
    monkeypatch.setattr(bot, '_fetch_cn_sina', lambda code: frame.copy())
    monkeypatch.setattr(bot, '_fetch_cn_qq_kline', lambda code, **kwargs: frame.copy())


def test_confirmed_previous_cutoff_is_accepted_for_explicit_history_query(audited_bot, monkeypatch):
    """The caller already selected Nov 4 as the common confirmed cutoff."""
    bot = audited_bot
    frame = history().loc[:'2026-11-04']
    install_sources(bot, monkeypatch, frame)
    dates = frame.loc['2026-01-01':].index
    result = bot._add_cn_bond_column(pd.DataFrame(index=dates), strict=True)
    assert result.index[-1] == pd.Timestamp('2026-11-04')
    assert result[bot.CN_BOND_CODE].notna().all()


def test_short_bond_history_cannot_silently_drop_defensive_leg_prefix(audited_bot, monkeypatch):
    bot = audited_bot
    frame = history()
    install_sources(bot, monkeypatch, frame.tail(60))
    dates = frame.loc['2026-01-01':].index
    with pytest.raises((bot.DataSchemaError, bot.DataUnavailableError, bot.poe.BotError)):
        bot._add_cn_bond_column(pd.DataFrame(index=dates), strict=True)


def test_interior_missing_session_is_rejected(audited_bot, monkeypatch):
    bot = audited_bot
    frame = history()
    dates = frame.loc['2026-01-01':].index
    install_sources(bot, monkeypatch, frame.drop(pd.Timestamp('2026-11-03')))
    with pytest.raises((bot.DataSchemaError, bot.DataUnavailableError, bot.poe.BotError)):
        bot._add_cn_bond_column(pd.DataFrame(index=dates), strict=True)


def test_direct_bond_signal_and_parameter_name_share_same_mapping(audited_bot):
    bot = audited_bot
    assert bot.CN_BOND_CODE == '1.000012'
    assert bot.CN_ALL_CODES[-1] == bot.CN_BOND_CODE
    assert bot.CN_NAMES[bot.CN_BOND_CODE] == bot.CN_BOND_NAME
    assert '全期限' in bot.CN_BOND_NAME
    assert '000012' in bot._performance_basis_notes()['国债口径']


def test_missing_intraday_bond_quote_never_changes_the_asset_universe(audited_bot, monkeypatch):
    bot = audited_bot
    monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-11-05 10:00').to_pydatetime())
    frame = history().loc[:'2026-11-04']
    install_sources(bot, monkeypatch, frame)
    monkeypatch.setattr(bot, '_fetch_cn_realtime_close', lambda *a, **kw: None)
    dates = history().loc['2026-01-01':].index
    try:
        result = bot._add_cn_bond_column(pd.DataFrame(index=dates), strict=False, include_live_snapshot=True)
    except (bot.DataSchemaError, bot.DataUnavailableError, bot.poe.BotError):
        return  # Fail-closed is acceptable; silently dropping an asset is not.
    assert bot.CN_BOND_CODE in result, 'Missing live bond must not silently become equity-only strategy'
    assert result[bot.CN_BOND_CODE].notna().all()
    assert result.index[-1] == pd.Timestamp('2026-11-04')


def test_valid_live_quote_with_previous_confirmed_history_is_accepted(audited_bot, monkeypatch):
    bot = audited_bot
    monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-11-05 10:00').to_pydatetime())
    frame = history().loc[:'2026-11-04']
    install_sources(bot, monkeypatch, frame)
    monkeypatch.setattr(bot, '_fetch_cn_realtime_close', lambda *a, **kw: 232.25)
    dates = history().loc['2026-01-01':].index
    result = bot._add_cn_bond_column(pd.DataFrame(index=dates), strict=False, include_live_snapshot=True)
    assert result.iloc[-1][bot.CN_BOND_CODE] == 232.25
    assert result[bot.CN_BOND_CODE].notna().all()


def test_non_live_query_cannot_accept_unconfirmed_today_daily_bar(audited_bot, monkeypatch):
    bot = audited_bot
    monkeypatch.setattr(bot, 'beijing_now', lambda: pd.Timestamp('2026-11-05 10:00').to_pydatetime())
    frame = history()
    install_sources(bot, monkeypatch, frame)
    with pytest.raises((bot.DataSchemaError, bot.DataUnavailableError, bot.poe.BotError)):
        bot._add_cn_bond_column(pd.DataFrame(index=frame.loc['2026-01-01':].index), strict=False)
    previous = frame.loc['2026-01-01':'2026-11-04'].index
    accepted = bot._add_cn_bond_column(pd.DataFrame(index=previous), strict=True)
    assert accepted.index[-1] == pd.Timestamp('2026-11-04')


def test_preexisting_bond_column_prefix_gap_is_rejected(audited_bot):
    bot = audited_bot
    frame = history().loc['2026-01-01':].rename(columns={'close': bot.CN_BOND_CODE})
    frame.iloc[0, frame.columns.get_loc(bot.CN_BOND_CODE)] = float('nan')
    with pytest.raises(bot.DataSchemaError):
        bot._add_cn_bond_column(frame, strict=False)

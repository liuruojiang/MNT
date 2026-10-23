"""Independent offline review of immutable V8 repair candidates.

Synthetic values exercise data contracts, never historical performance.
"""
import copy
import importlib.util
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def v80():
    source = Path(os.environ.get("V80_REVIEW_SOURCE", ROOT / "mnt_bot V 8.0 plus.py"))
    spec = importlib.util.spec_from_file_location("v80_us_independent_review", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def offline(v80, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("Review cannot access network or LLM")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.poe, "call", forbidden)


def fixtures():
    dates = pd.to_datetime(["2024-03-25", "2024-03-26", "2024-03-27", "2024-03-28", "2024-04-01"])
    raw = pd.DataFrame({"open": [100., 102., 99., 103., 104.], "close": [101., 103., 101., 104., 105.]}, index=dates)
    return dates, raw


@pytest.mark.parametrize("missing_column", ["open", "close"])
@pytest.mark.parametrize("factor", [.001, .994, 1., 4.])
def test_session_factor_is_not_reestimated_from_later_prices(v80, missing_column, factor):
    dates, raw = fixtures()
    original = raw * factor
    gap = dates[2]
    original.loc[gap, missing_column] = np.nan
    original.attrs["audit"] = {"unchanged": [1, 2]}
    frozen = copy.deepcopy(original)
    repaired, count = v80._merge_same_ticker_gap_prices(original, raw, [gap], "SPY")
    assert count == 1
    assert repaired.loc[gap, missing_column] == pytest.approx(raw.loc[gap, missing_column] * factor)
    altered = original.copy()
    altered.loc[dates[3]:, ["open", "close"]] *= 13.
    changed, _ = v80._merge_same_ticker_gap_prices(altered, raw, [gap], "SPY")
    assert changed.loc[gap, missing_column] == repaired.loc[gap, missing_column]
    pd.testing.assert_frame_equal(original, frozen)
    assert original.attrs == frozen.attrs


def test_whole_gap_across_good_friday_uses_exchange_neighbors(v80):
    dates, raw = fixtures()
    # Thursday's immediate next session is Monday, not Good Friday.
    adjusted = raw * .73
    gap = dates[3]
    actual, count = v80._merge_same_ticker_gap_prices(adjusted.drop(gap), raw, [gap], "SPY")
    assert count == 1
    assert actual.loc[gap].tolist() == pytest.approx(adjusted.loc[gap].tolist())
    assert actual.attrs["nasdaq_gap_repair_evidence"][-1]["anchors"][1]["date"] == "2024-04-01"


@pytest.mark.parametrize("right_factor", [.99999, .99, .5, 2.])
def test_whole_gap_cannot_cross_even_small_action_factor(v80, right_factor):
    dates, raw = fixtures()
    gap = dates[2]
    adjusted = raw.copy()
    adjusted.loc[dates[3]:, ["open", "close"]] *= right_factor
    actual, count = v80._merge_same_ticker_gap_prices(adjusted.drop(gap), raw, [gap], "SPY")
    assert count == 0
    assert gap not in v80._valid_us_ohlc_index(actual)
    with pytest.raises(v80.poe.BotError):
        v80._assert_us_internal_price_history({"SPY": actual}, ["SPY"])


def test_requested_repairs_do_not_chain_or_mutate_existing_evidence(v80):
    dates, raw = fixtures()
    original = raw * .8
    original = original.drop(dates[1:3])
    prior = {"status": "previous", "filled_columns": ["open"]}
    original.attrs["nasdaq_gap_repair_evidence"] = [prior]
    actual, count = v80._merge_same_ticker_gap_prices(original, raw, dates[1:3], "SPY")
    assert count == 0
    assert original.attrs["nasdaq_gap_repair_evidence"] == [prior]
    assert len(actual.attrs["nasdaq_gap_repair_evidence"]) == 3


RUNNERS = ["run_us_rotation_mix", "run_subb_v75_ema_base7_rotation", "run_v78_subb_new_line",
           "_v80_b78_run_us_rotation_mix", "_v80_b78_run_subb_v75_ema_base7_rotation",
           "_v80_b78_run_v78_subb_new_line", "run_us_rotation"]


@pytest.fixture
def close(v80):
    dates = v80._expected_us_ohlc_index("2022-01-03", "2024-10-01")
    assets = sorted(set(v80.US_ROT_POOL + v80._v80_b78_US_ROT_POOL + ["BIL", "SPY", "TLT"]))
    return pd.DataFrame(100., index=dates, columns=assets)


def run(v80, name, close, strict):
    kwargs = {"us_open": {a: close[a] for a in close}, "strict_open_execution": strict}
    if name in ("run_us_rotation_mix", "_v80_b78_run_us_rotation_mix", "run_us_rotation"):
        kwargs["ranking_codes"] = v80.US_ROT_POOL
    return getattr(v80, name)(close, **kwargs)


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize("gap_location", [1, -11])
def test_every_production_component_rejects_missing_session(v80, close, runner, gap_location):
    damaged = close.drop(close.index[gap_location])
    with pytest.raises(ValueError, match="(?i)(session|calendar)"):
        run(v80, runner, damaged, True)


@pytest.mark.parametrize("runner", RUNNERS)
def test_each_runner_preserves_explicit_nonstrict_diagnostic_switch(v80, close, monkeypatch, runner):
    class ReachedValidator(Exception):
        pass
    def check(*a, **k):
        assert k["strict_calendar"] is False
        raise ReachedValidator()
    validator = "_v80_b78_validate_subb_price_input" if runner.startswith("_v80_b78") else "_validate_subb_price_input"
    monkeypatch.setattr(v80, validator, check)
    with pytest.raises(ReachedValidator):
        run(v80, runner, close.drop(close.index[1]), False)

"""C display clocks use C bars and XNYS sessions, independent of B snapshots."""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    source = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_c_clock_repair_20261023", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def local_only(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("C clock tests forbid network and LLM")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.poe, "call", forbidden)


@pytest.mark.parametrize("asof,now,unconfirmed,execution,elapsed", [
    ("2026-10-22", "2026-10-23 00:00", True, "2026-10-23 21:30", False),
    ("2026-10-22", "2026-10-23 04:00", False, "2026-10-23 21:30", False),
    ("2026-10-22", "2026-10-23 21:30", False, "2026-10-23 21:30", True),
    ("2026-10-21", "2026-10-23 00:00", False, "2026-10-22 21:30", True),
    ("2026-11-25", "2026-11-26 05:00", False, "2026-11-27 22:30", False),
    ("2026-11-27", "2026-11-28 01:59", True, "2026-11-30 22:30", False),
    ("2026-11-27", "2026-11-28 02:00", False, "2026-11-30 22:30", False),
    ("2026-03-06", "2026-03-07 05:00", False, "2026-03-09 21:30", False),
])
def test_c_clock_session_confirmation_and_execution(v80, asof, now, unconfirmed, execution, elapsed):
    frame = pd.DataFrame({"SPY": [100.]}, index=pd.to_datetime([asof]))
    clock = v80._subc_query_clock(frame, now=now)
    assert clock["asof"] == pd.Timestamp(asof)
    assert clock["unconfirmed"] == unconfirmed
    assert clock["execution_at"] == pd.Timestamp(execution, tz="Asia/Shanghai")
    assert clock["execution_elapsed"] == elapsed


def pending_info():
    return dict(current_scale=1., next_target_scale=.7, next_scale=.7,
                gold_current_scale=1., gold_target_scale=1., gold_next_scale=1.,
                pending_adjustment=True, gold_pending_adjustment=False)


@pytest.mark.parametrize("kind", ["signal", "live_signal", "params", "live_params"])
@pytest.mark.parametrize("now,status,actionable", [
    ("2026-10-23 00:00", "未收盘确认", False),
    ("2026-10-23 05:00", "已收盘确认", True),
    ("2026-10-23 22:00", "计划时点已过", False),
])
def test_four_surfaces_use_same_c_clock_and_do_not_reissue_expired_targets(v80, kind, now, status, actionable):
    frame = pd.DataFrame({"SPY": [100.]}, index=pd.to_datetime(["2026-10-22"]))
    clock = v80._subc_query_clock(frame, now=now)
    output = []
    # A contradictory B flag must not override C's explicit clock.
    state = v80._write_v80_subc_overview(output.append, pending_info(), query_kind=kind,
                                       us_intraday=not clock["unconfirmed"], clock=clock)
    rendered = "".join(output)
    assert status in rendered
    assert "2026-10-22" in rendered and "2026-10-23 21:30" in rendered
    assert state["is_signal"] == actionable
    if clock["execution_elapsed"]:
        assert "先核对账户是否已执行" in rendered
        assert "不应据此重复下单或直接补单" in rendered
        assert "计划时点已过" in state["note"]


def test_early_close_state_is_independent_of_market_open_boolean(v80):
    frame = pd.DataFrame({"SPY": [100.]}, index=pd.to_datetime(["2026-11-27"]))
    clock = v80._subc_query_clock(frame, now=pd.Timestamp("2026-11-27 18:00", tz="UTC"))
    assert not clock["unconfirmed"]
    assert clock["close_at"] == pd.Timestamp("2026-11-28 02:00", tz="Asia/Shanghai")
    output = []
    result = v80._write_v80_subc_overview(output.append, pending_info(), clock=clock)
    assert result["is_signal"]
    assert "2026-11-30 22:30" in "".join(output)


@pytest.mark.parametrize("kind", ["signal", "params"])
def test_confirmed_query_handlers_also_pass_c_own_clock(v80, monkeypatch, kind):
    # Reuse the handler harness from the original adversarial reproducer;
    # its live_signal/live_params cases are run alongside this file.
    from test_v80_adversarial_display_20261023 import test_c_confirmation_uses_its_own_data_date
    test_c_confirmation_uses_its_own_data_date(v80, monkeypatch, "2026-10-21", kind)


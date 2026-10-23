"""Offline display adversarial regressions; synthetic data, no performance claim."""
import importlib.util
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    source = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_display_adversarial_20261023", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def local_only(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline display audit forbids network and LLM")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.poe, "call", forbidden)
    monkeypatch.setattr(v80.time, "sleep", lambda *args, **kwargs: None)


def test_real_fetch_allows_c_previous_close_while_b_is_intraday(v80, monkeypatch):
    """Fault only upstream AVUV current-day bars and quotes; use real validation."""
    helper_path = Path(__file__).with_name("test_v80_doublecheck_data_math_20261007.py")
    spec = importlib.util.spec_from_file_location("v80_display_fetch_helper", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    assert "AVUV" not in v80.SUBB_REQUIRED_PRICE_TICKERS
    assert "AVUV" not in v80.SUBB_REQUIRED_LIVE_PRICE_TICKERS

    class FaultedVendorPatches:
        def setattr(self, obj, name, value):
            if name == "fetch_yahoo":
                original = value

                def value(ticker, *args, **kwargs):
                    frame, source = original(ticker, *args, **kwargs)
                    if ticker == "AVUV":
                        frame = frame.loc[:"2026-09-28"]
                    return frame, source
            elif name == "_fetch_us_realtime_close":
                original = value

                def value(ticker, *args, **kwargs):
                    return (None, None, None) if ticker == "AVUV" else original(ticker, *args, **kwargs)
            monkeypatch.setattr(obj, name, value)

    frames = helper.synthetic_vendor_fetch(v80, FaultedVendorPatches(),
                                            "2026-09-30 00:00", True,
                                            us_end="2026-09-29")
    assert frames[2].index[-1] == pd.Timestamp("2026-09-29")
    assert frames[3].index[-1] == pd.Timestamp("2026-09-28")


@pytest.mark.parametrize("c_date", ["2026-10-21", "2026-10-22"])
@pytest.mark.parametrize("query_kind", ["live_signal", "live_params"])
def test_c_confirmation_uses_its_own_data_date(v80, monkeypatch, c_date, query_kind):
    """B has Thursday live bars, while C can fall back to Wednesday close.

    Production _fetch_data truncates C to the oldest available asset date.
    Stub only fetching/strategy work; execute the actual query handler and
    inspect the confirmation state it passes to the actual C display.
    """
    now = datetime(2026, 10, 23, 0, 0)  # Thursday 12:00 New York
    b_date = pd.Timestamp("2026-10-22")
    cn = pd.DataFrame({"close": [100.0, 101.0]}, index=pd.to_datetime(["2026-10-21", "2026-10-22"]))
    b = pd.DataFrame({"close": [100.0]}, index=[b_date])
    c = pd.DataFrame({"close": [100.0]}, index=[pd.Timestamp(c_date)])
    info = dict(current_scale=1.0, next_target_scale=0.7, next_scale=0.7,
                gold_current_scale=1.0, gold_target_scale=1.0, gold_next_scale=1.0,
                pending_adjustment=True, gold_pending_adjustment=False)
    bot = v80.CombinedStrategyV80()
    monkeypatch.setattr(bot, "_cached_fetch_data", lambda *args, **kwargs: (cn, cn, b, c))
    monkeypatch.setattr(bot, "_cached_run_strategies", lambda *args, **kwargs: (cn, cn, b, None, c, None, None, None))
    data = defaultdict(lambda: None, cn_date=cn.index[-1], dk_date=cn.index[-1], us_date=b_date,
                       cn_result=cn, cn_dk_result=cn, us_rot_result=b, subc_vs_info=info,
                       is_us_signal=True)
    monkeypatch.setattr(bot, "_compute_signal_data", lambda *args: data)
    monkeypatch.setattr(v80, "_compute_subc_production_snapshot", lambda *args, **kwargs: {"info": info})
    monkeypatch.setattr(v80, "is_cn_unconfirmed_intraday_snapshot", lambda: (False, now))
    monkeypatch.setattr(v80, "is_us_market_open", lambda: (True, now))
    monkeypatch.setattr(v80, "beijing_now", lambda: now)
    monkeypatch.setattr(v80, "_write_a_adk_query_overview", lambda *args, **kwargs: {})
    monkeypatch.setattr(v80, "_write_v80_subb_overview", lambda *args, **kwargs: {})
    monkeypatch.setattr(v80, "_write_v80_a_adk_score_details", lambda *args, **kwargs: None)
    monkeypatch.setattr(v80, "_write_volume_warning_panel", lambda *args, **kwargs: None)
    monkeypatch.setattr(v80, "_write_suba_volume_query_warning", lambda *args, **kwargs: None)
    for name in ("extract_v78_suba_rebalances", "extract_v78_adk_rebalances",
                 "_v80_extract_subb_rebalances", "extract_prod_rebalances", "extract_subc_vs_rebalances"):
        monkeypatch.setattr(v80, name, lambda *args, **kwargs: [])
    monkeypatch.setattr(v80, "generate_signal_excel", lambda *args, **kwargs: b"offline-test")
    output, observed = [], []

    class Message:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def write(self, text):
            output.append(text)

        def attach_file(self, **kwargs):
            pass

    monkeypatch.setattr(v80, "_sm", Message)
    actual_writer = v80._write_v80_subc_overview

    def capture(*args, **kwargs):
        observed.append(kwargs["us_intraday"])
        return actual_writer(*args, **kwargs)

    monkeypatch.setattr(v80, "_write_v80_subc_overview", capture)
    getattr(bot, "_handle_" + query_kind)()
    expected_intraday = pd.Timestamp(c_date) == b_date
    assert observed == [expected_intraday], "C confirmation must use C's latest bar, not B's latest bar"
    if query_kind == "live_signal" and not expected_intraday:
        assert "收盘目标已确认" in "".join(output)


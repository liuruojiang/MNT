"""R1-R4 report contracts through real V8.0 report consumers.

The small, explicitly synthetic report fixture is a control/fault-injection
input, never presented as market history or strategy performance. It replaces
fetch/strategy/transaction extraction and image rendering only. Date parsing,
date coverage, portfolio combination, metrics, report handlers, and XLSX export
are the actual production functions. Expensive frozen-data replay belongs to
the lead auditor's final integration verification.
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import runpy
import sys
import types
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
NAMES = ("Sub-A", "Sub-A-DK", "B7.8", "B7.9", "Sub-C")
WEIGHTS = (0.15, 0.15, 0.20, 0.20, 0.30)
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


@pytest.fixture(scope="module")
def v80():
    spec = importlib.util.spec_from_file_location("v80_reporting_repairs_20261015", ROOT / "mnt_bot V 8.0 plus.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


class Capture:
    def __init__(self):
        self.messages = []
        self.attachments = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def write(self, value):
        self.messages.append(str(value))

    def attach_file(self, **kwargs):
        self.attachments.append(kwargs)

    @property
    def text(self):
        return "".join(self.messages)


def workbook_sheets(blob):
    """Read actual XLSX cells, avoiding incidental shared-string matches."""
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(node.text or "" for node in item.iter(NS + "t")) for item in shared.findall(NS + "si")]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
        sheets = {}
        for sheet in workbook.find(NS + "sheets"):
            target = targets[sheet.attrib[RELNS + "id"]]
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            root = ET.fromstring(archive.read(path))
            cells = {}
            for cell in root.iter(NS + "c"):
                value = cell.find(NS + "v")
                if value is None:
                    continue
                raw = value.text
                cells[cell.attrib["r"]] = strings[int(raw)] if cell.attrib.get("t") == "s" else float(raw)
            sheets[sheet.attrib["name"]] = cells
        return sheets


@pytest.fixture
def report_harness(v80, monkeypatch, request):
    bounds = getattr(request, "param", {})
    cn_end = pd.Timestamp(bounds.get("cn_end", "2026-09-25"))
    us_end = pd.Timestamp(bounds.get("us_end", "2026-09-25"))
    monkeypatch.setattr(v80, "beijing_now", lambda: pd.Timestamp(bounds.get("now", "2026-09-26 19:40:51")).to_pydatetime())
    calendar = pd.date_range(bounds.get("start", "2026-06-30"), max(cn_end, us_end), freq="D")
    cn_dates = v80._expected_cn_sessions(calendar[0], cn_end)
    us_dates = pd.DatetimeIndex([day for day in calendar if day <= us_end and v80._is_us_market_session(day)])
    # These are diagnostic report inputs. The production strategy is not run
    # against these placeholder prices; only source date coverage is consumed.
    cn_source = pd.DataFrame({"diagnostic_source": np.arange(len(cn_dates)) + 100.0}, index=cn_dates)
    us_source = pd.DataFrame({"diagnostic_source": np.arange(len(us_dates)) + 100.0}, index=us_dates)
    frames = (cn_source, cn_source.copy(), us_source, us_source.copy())
    returns = {}
    for number, name in enumerate(NAMES):
        dates = cn_dates[1:] if number < 2 else us_dates[1:]
        values = (np.arange(len(dates)) % 5 - 2) * 0.0004 + (number + 1) * 0.0001
        returns[name] = pd.Series(values, index=dates, name="return")
    cn_result = returns["Sub-A"].to_frame()
    dk_result = returns["Sub-A-DK"].to_frame()
    b78 = returns["B7.8"].to_frame()
    b79 = returns["B7.9"].to_frame()
    b79.attrs["v80_b78"] = b78
    results = (cn_result, dk_result, b79, None, None, None, None, None)
    bot = v80.CombinedStrategyV80()
    bot._us_open = {}
    capture = Capture()
    chart_calls = []

    def chart(nav_series, chart_labels, colors, start_date, end_date):
        item = {"start": pd.Timestamp(start_date), "end": pd.Timestamp(end_date),
                "navs": {name: series.copy() for name, series in nav_series.items()}}
        chart_calls.append(item)
        # Test-only opaque attachment bytes, never saved or claimed as a PNG.
        return json.dumps({"diagnostic_chart": True, "start": str(start_date), "end": str(end_date),
                           "last": {name: float(series.iloc[-1]) for name, series in nav_series.items()}}, sort_keys=True).encode()

    monkeypatch.setattr(v80, "_sm", lambda: capture)
    monkeypatch.setattr(bot, "_cached_fetch_data", lambda *args, **kwargs: frames)
    monkeypatch.setattr(bot, "_cached_run_strategies", lambda *args, **kwargs: results)
    monkeypatch.setattr(v80, "_get_subc_daily_ret", lambda *args, **kwargs: returns["Sub-C"])
    monkeypatch.setattr(v80, "_render_nav_drawdown_chart", chart)
    for name in ("extract_v78_suba_rebalances", "extract_v78_adk_rebalances", "_v80_extract_subb_rebalances",
                 "extract_prod_rebalances", "extract_subc_vs_rebalances"):
        monkeypatch.setattr(v80, name, lambda *args, **kwargs: [])
    monkeypatch.setattr(v80.requests.sessions.Session, "request", lambda *args, **kwargs: pytest.fail("report unit tests must not access network"))

    def execute(command):
        capture.messages.clear()
        capture.attachments.clear()
        chart_calls.clear()
        monkeypatch.setattr(v80.poe, "query", types.SimpleNamespace(text=command))
        bot._run_impl()
        return {"text": capture.text, "attachments": list(capture.attachments), "charts": list(chart_calls)}

    return types.SimpleNamespace(bot=bot, frames=frames, returns=returns, execute=execute, capture=capture, charts=chart_calls)


def test_calendar_control_midautumn_is_not_missing_cn_data(v80):
    assert v80._is_cn_required_close_day(pd.Timestamp("2026-09-24"))
    assert not v80._is_cn_required_close_day(pd.Timestamp("2026-09-25"))
    assert v80._is_us_market_session(pd.Timestamp("2026-09-25"))


@pytest.mark.parametrize("prefix", ["表现", "净值曲线"])
def test_holiday_asof_keeps_us_session_and_discloses_actual_end(report_harness, prefix):
    captured = report_harness.execute(prefix + " 2026-09-01到2026-09-26")
    assert len(captured["charts"]) == 1
    chart = captured["charts"][0]
    assert chart["end"] == pd.Timestamp("2026-09-25"), "actual report as-of must preserve the completed US session"
    assert chart["navs"]["Combined"].index[-1] == pd.Timestamp("2026-09-25")
    assert chart["navs"]["Sub-A"].index[-1] == pd.Timestamp("2026-09-24")
    assert "2026-09-25" in captured["text"]
    assert "2026-09-26" in captured["text"], "requested boundary should remain auditable"


def test_nav_and_performance_equal_cutoff_normal_control(report_harness):
    performance = report_harness.execute("表现 2026-09-01到2026-09-24")
    nav = report_harness.execute("净值曲线 2026-09-01到2026-09-24")
    for name in NAMES + ("Combined",):
        pd.testing.assert_series_equal(performance["charts"][0]["navs"][name], nav["charts"][0]["navs"][name])


@pytest.mark.parametrize("report_harness", [{
    "start": "2024-06-28",
    "cn_end": "2026-10-20", "us_end": "2026-10-19", "now": "2026-10-20 17:12:00",
}], indirect=True)
def test_cn_close_ahead_of_us_uses_confirmed_cutoff_for_all_report_consumers(v80, report_harness, monkeypatch):
    observed = []
    original = v80._v80_performance_daily_returns

    def standard_returns(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.append(result)
        return result

    monkeypatch.setattr(v80, "_v80_performance_daily_returns", standard_returns)
    # Reproduce the actual command and the explicit historical-range variant.
    for query in ("最近一年表现", "表现 2026-09-01到2026-10-20"):
        performance = report_harness.execute(query)
        assert len(performance["attachments"]) == 2
        assert performance["charts"][0]["end"] == pd.Timestamp("2026-10-19")
        for series in observed[-1].values():
            assert series.index[-1] == pd.Timestamp("2026-10-19")
            assert series.index[0] == pd.Timestamp("2024-07-01"), "standard windows must retain earlier history"
        book = next(item for item in performance["attachments"] if item["name"].endswith(".xlsx"))
        sheets = workbook_sheets(book["contents"])
        assert "标准窗口指标" in sheets
        standard = sheets["标准窗口指标"]
        row = next(cell[1:] for cell, value in standard.items() if cell.startswith("A") and value == "1Y")
        one_year_cells = [standard[column + row] for column in "BCDEFG"]
        assert all("N/A" not in value for value in one_year_cells), "exercise numeric 1Y metrics for every sleeve and Combined"
        assert "| 1Y | " + " | ".join(one_year_cells) + " |" in performance["text"]
        metadata = "\n".join(str(value) for value in sheets["报告元数据"].values())
        assert "2026-10-19" in metadata and "2026-10-20" in metadata
    nav = report_harness.execute("净值曲线 2026-09-01到2026-10-20")
    for name in NAMES + ("Combined",):
        pd.testing.assert_series_equal(performance["charts"][0]["navs"][name], nav["charts"][0]["navs"][name])
    assert report_harness.frames[0].index[-1] == pd.Timestamp("2026-10-20"), "source/signal data must remain intact"


@pytest.mark.parametrize("report_harness", [{
    "cn_end": "2026-10-20", "us_end": "2026-10-19", "now": "2026-10-20 17:12:00",
}], indirect=True)
@pytest.mark.parametrize("missing", ["2026-10-15", "2026-10-19"])
def test_confirmed_cutoff_still_rejects_missing_completed_us_returns(v80, report_harness, missing):
    results = report_harness.bot._cached_run_strategies(*report_harness.frames)
    results[2].attrs["v80_b78"].drop(pd.Timestamp(missing), inplace=True)
    with pytest.raises(ValueError, match=f"B7.8: missing market-session return at {missing}; refusing zero fill"):
        report_harness.execute("最近一年表现")


@pytest.mark.parametrize("report_harness", [{
    "start": "2024-06-28", "cn_end": "2026-10-26", "us_end": "2026-10-23",
    "now": "2026-10-26 16:30:00",
}], indirect=True)
@pytest.mark.parametrize("prefix", ["表现", "净值曲线"])
@pytest.mark.parametrize("period,cutoff", [
    ("最近一年", "2026-10-23"), ("2026-09-01到2026-10-19", "2026-10-19"),
])
def test_report_does_not_require_amount_after_report_end(v80, report_harness, monkeypatch, prefix, period, cutoff):
    original = report_harness.bot._cached_run_strategies
    calls = []
    snapshots = [frame.copy(deep=True) for frame in report_harness.frames]
    generation = v80._v80_integrity_generation()
    for frame in report_harness.frames:
        frame.attrs["verified_integrity_generation"] = generation

    def require_report_amount(cn, dk, us, prod, **kwargs):
        # Simulate a source published through the report's required close only.
        # The real handlers must stop demanding the newer CN day before calling
        # the strategies, rather than swallowing a validation error afterwards.
        assert cn.index[-1] == dk.index[-1] == pd.Timestamp(cutoff)
        assert cn.index[0] == dk.index[0] == snapshots[0].index[0]
        assert cn.attrs["verified_integrity_generation"] == generation
        assert us is report_harness.frames[2] and prod is report_harness.frames[3]
        calls.append(cn.index[-1])
        return original(cn, dk, us, prod, **kwargs)

    monkeypatch.setattr(report_harness.bot, "_cached_run_strategies", require_report_amount)
    captured = report_harness.execute(prefix + " " + period)
    assert calls == [pd.Timestamp(cutoff)]
    assert captured["attachments"]
    assert captured["charts"][0]["end"] == pd.Timestamp(cutoff)
    for frame, snapshot in zip(report_harness.frames, snapshots):
        pd.testing.assert_frame_equal(frame, snapshot)


@pytest.mark.parametrize("failure", ["unavailable", "unresolved", "empty"])
def test_formal_amount_failure_keeps_provider_evidence_in_user_message(v80, monkeypatch, failure):
    bot = v80.CombinedStrategyV80()
    capture = Capture()
    dates = pd.to_datetime(["2026-10-22", "2026-10-23"])
    prices = pd.DataFrame({"diagnostic": [100., 101.]}, index=dates)
    result = pd.DataFrame({"return": 0.}, index=dates)
    reason = "ZZ2000: CSIndex official amount: latest valid amount 2026-10-22 < expected 2026-10-23"
    monkeypatch.setattr(v80, "DEBUG_MODE", False)
    monkeypatch.setattr(v80.poe, "query", types.SimpleNamespace(text="最近一年表现"))
    monkeypatch.setattr(v80, "_sm", lambda: capture)
    monkeypatch.setattr(v80, "_add_cn_bond_column", lambda *a, **k: prices)
    monkeypatch.setattr(v80, "run_cn_strategy", lambda *a, **k: result)
    monkeypatch.setattr(v80, "beijing_now", lambda: pd.Timestamp("2026-10-26 16:30").to_pydatetime())

    def amount(**kwargs):
        assert kwargs["expected_date"] == dates[-1]
        if failure == "unavailable":
            raise v80.DataUnavailableError(reason)
        if failure == "empty":
            return pd.Series(dtype=bool), pd.DataFrame()
        return pd.Series(False, index=dates), pd.DataFrame({
            "combined_unresolved": [False, True], "zz2000_error": reason,
        }, index=dates)

    monkeypatch.setattr(v80, "_load_suba_volume_signal", amount)
    monkeypatch.setattr(bot, "_run_impl", lambda: bot._run_strategies(prices, prices, prices, prices))
    monkeypatch.setattr(v80.requests.sessions.Session, "request", lambda *a, **k: pytest.fail("unexpected network"))
    bot.run()
    assert "所需截至 2026-10-23" in capture.text
    if failure != "empty":
        assert "latest valid amount 2026-10-22" in capture.text
        assert "CSIndex official amount" in capture.text
    assert "本次未生成绩效报告" in capture.text
    assert "进入策略前" not in capture.text
    assert not capture.attachments
    if failure == "unresolved":
        assert "不可判定 1 日（2026-10-23 至 2026-10-23）" in capture.text


@pytest.mark.parametrize("native_api_complete", [False, True])
def test_poe_bootstrap_does_not_access_runtime_only_boterror(monkeypatch, native_api_complete):
    """Reproduce Poe's load phase, where BotError deliberately raises AttributeError."""
    denied = []
    settings = []

    class SandboxPoe:
        def __getattr__(self, name):
            if name == "BotError":
                denied.append(name)
                raise AttributeError("'poe' module attribute 'BotError' is not available in this context. "
                                     "Wrap your code in if __name__ == \"__main__\": block")
            raise AttributeError(name)

        def update_settings(self, value):
            settings.append(value)

    sandbox = SandboxPoe()
    if native_api_complete:
        sandbox.query = types.SimpleNamespace(text="最近一年表现", attachments=[])
        sandbox.default_chat = []
        sandbox.start_message = lambda: Capture()
        sandbox.call = lambda *a, **k: pytest.fail("bootstrap must not call LLM")
    monkeypatch.setattr("requests.sessions.Session.request", lambda *a, **k: pytest.fail("bootstrap must not fetch data"))
    loaded = runpy.run_path(str(ROOT / "mnt_bot V 8.0 plus.py"),
                           init_globals={"poe": sandbox}, run_name="v80_poe_bootstrap_regression")
    assert denied == [], "Poe runtime-only exceptions must not be resolved while loading class bases"
    assert settings
    assert issubclass(loaded["SubaVolumeDataError"], RuntimeError)

    # The local exception must still reach the user even while BotError is
    # unavailable; handling this error must not dereference the native API.
    capture = Capture()
    bot = loaded["CombinedStrategyV80"]()
    bot.run.__globals__["_sm"] = lambda: capture
    bot.run.__globals__["DEBUG_MODE"] = False

    def fail_amount():
        raise loaded["SubaVolumeDataError"]("Sub-A成交额风控数据不可用；ZZ2000 所需截至 2026-10-23")

    bot._run_impl = fail_amount
    bot.run()
    assert "ZZ2000 所需截至 2026-10-23" in capture.text
    assert "本次未生成绩效报告" in capture.text
    assert denied == []


def subb_display_result():
    dates = pd.to_datetime(["2026-09-22", "2026-09-23", "2026-09-24"])
    result = pd.DataFrame({"return": [0.001, -0.002, 0.003], "w_QQQ": 1.0,
                           "target_w_QQQ": 1.0, "volreg_ratio": 1.2,
                           "volreg_defense": False}, index=dates)
    result.attrs["v78_subb_bias"] = pd.DataFrame({"realized_vol": 0.2, "target_vol_scale": 1.25}, index=dates)
    result.attrs["v78_subb_logvol"] = pd.DataFrame({"realized_vol": 0.24, "target_vol_scale": 1.25}, index=dates)
    return result


@pytest.mark.parametrize("query_kind", ["params", "live_params"])
@pytest.mark.parametrize("label, official_target", [("B7.8", 25), ("B7.9", 30)])
def test_parameter_consumers_disclose_each_leg_target_window_cap(v80, query_kind, label, official_target):
    b79 = subb_display_result()
    b79.attrs["v80_b78"] = subb_display_result()
    output = []
    v80._write_v80_subb_overview(output.append, b79, query_kind=query_kind)
    text = "".join(output)
    section = text.split("### " + label, 1)[1].split("### ", 1)[0]
    expected = {"官方": (official_target, 40, 1.5), "EMA": (official_target, 126, 1.5),
                "Bias": (25, 40, 1.5), "LogVol": (30, 40, 1.25)}
    for leg, (target, window, cap) in expected.items():
        matching = [line for line in section.splitlines() if re.search(r"\|\s*" + re.escape(leg) + r"(?:腿)?\s*\|", line)]
        assert len(matching) == 1, f"{label} {query_kind} requires a distinct {leg} parameter row"
        row = matching[0]
        assert re.search(rf"(?<!\d){target}(?:\.0+)?%", row), (leg, row)
        assert re.search(rf"(?<!\d){window}(?!\d)", row), (leg, row)
        assert any(value in row for value in (f"{cap:g}x", f"{cap:.2f}x", f"{cap:g}倍", f"{cap:.2f}倍")), (leg, row)


def test_multi_window_names_are_unique_and_encode_requested_and_actual_dates(report_harness):
    result = report_harness.execute("表现 2026-09-01到2026-09-15；2026-09-16到2026-09-26")
    attachments = result["attachments"]
    assert len(attachments) == 4
    names = [item["name"] for item in attachments]
    assert len(names) == len(set(names)), "distinct query windows must not reuse attachment identities"
    required_groups = {("20260901", "20260915"), ("20260916", "20260926", "20260925")}
    observed_groups = set()
    # The existing parser intentionally sorts ranges by duration; do not make
    # artifact identity tests depend on the user's textual range ordering.
    for pair in (attachments[:2], attachments[2:]):
        names_compact = [re.sub(r"[^0-9]", "", item["name"]) for item in pair]
        matches = [required for required in required_groups if all(all(date in name for date in required) for name in names_compact)]
        assert len(matches) == 1, pair
        observed_groups.add(matches[0])
    assert observed_groups == required_groups


def test_workbook_metadata_contains_exact_request_actual_and_sleeve_boundaries(report_harness):
    result = report_harness.execute("表现 2026-09-01到2026-09-26")
    book = next(item for item in result["attachments"] if item["name"].endswith(".xlsx"))
    sheets = workbook_sheets(book["contents"])
    assert "报告元数据" in sheets
    metadata = "\n".join(str(value) for value in sheets["报告元数据"].values())
    for expected in ("2026-09-01", "2026-09-26", "2026-09-25", "2026-09-24", *NAMES):
        assert expected in metadata, f"explicit report metadata missing {expected}"


def test_report_actual_start_uses_returns_not_raw_price_inception(report_harness):
    result = report_harness.execute("表现 2026-06-01到2026-09-26")
    book = next(item for item in result["attachments"] if item["name"].endswith(".xlsx"))
    metadata = workbook_sheets(book["contents"])["报告元数据"]
    text = "\n".join(str(value) for value in metadata.values())
    assert "2026-06-01" in text and "2026-07-01" in text
    for attachment in result["attachments"]:
        compact = re.sub(r"[^0-9]", "", attachment["name"])
        assert "20260601" in compact, "the original requested start must be preserved"
        assert "20260701" in compact, "actual coverage begins with strategy returns, not the source-price warmup row"


def test_excel_optional_context_preserves_old_call_contract(v80):
    blob = v80.generate_performance_excel("20261015", {}, pd.DataFrame(), [])
    sheets = workbook_sheets(blob)
    assert "绩效概览" in sheets and "标准窗口指标" in sheets
    assert any("N/A" in str(value) for value in sheets["标准窗口指标"].values())


def test_single_period_combination_has_the_five_sleeve_weighted_return(v80):
    date = pd.to_datetime(["2026-09-24"])
    values = (-0.02, 0.01, 0.03, -0.01, 0.005)
    inputs = {name: pd.Series([value], index=date) for name, value in zip(NAMES, values)}
    actual = v80._performance_combined_daily_returns(inputs)
    assert isinstance(actual.index, pd.DatetimeIndex)
    assert len(actual) == 1
    assert actual.iloc[0] == pytest.approx(sum(w * r for w, r in zip(WEIGHTS, values)), abs=1e-15)


def test_two_period_combination_normal_control_uses_drifting_capital(v80):
    dates = pd.to_datetime(["2026-09-23", "2026-09-24"])
    first = (-0.02, 0.01, 0.03, -0.01, 0.005)
    second = (0.01, -0.02, 0.005, 0.015, 0.002)
    inputs = {name: pd.Series([a, b], index=dates) for name, a, b in zip(NAMES, first, second)}
    actual = v80._performance_combined_daily_returns(inputs)
    nav1 = sum(w * (1 + a) for w, a in zip(WEIGHTS, first))
    nav2 = sum(w * (1 + a) * (1 + b) for w, a, b in zip(WEIGHTS, first, second))
    np.testing.assert_allclose(actual.to_numpy(), [nav1 - 1, nav2 / nav1 - 1], rtol=0, atol=1e-15)


def test_empty_combination_preserves_datetime_index(v80):
    inputs = {name: pd.Series(dtype=float, index=pd.DatetimeIndex([])) for name in NAMES}
    actual = v80._performance_combined_daily_returns(inputs)
    assert actual.empty and isinstance(actual.index, pd.DatetimeIndex)


def test_empty_monthly_aggregation_is_explicitly_empty(v80):
    actual = v80._monthly_returns_from_daily_window(pd.Series(dtype=float), pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-24"))
    assert actual.empty


def test_single_day_performance_handler_produces_combined_cumulative_return(report_harness):
    result = report_harness.execute("表现 2026-09-24")
    book = next(item for item in result["attachments"] if item["name"].endswith(".xlsx"))
    sheets = workbook_sheets(book["contents"])
    expected = sum(w * report_harness.returns[name].loc["2026-09-24"] for name, w in zip(NAMES, WEIGHTS))
    assert sheets["绩效概览"]["G2"] == pytest.approx(expected, abs=1e-15)
    assert sheets["绩效概览"]["G3"] == "N/A", "one daily observation does not justify annualized performance"


@pytest.mark.parametrize("prefix", ["表现", "净值曲线"])
def test_empty_query_range_reports_data_unavailable_instead_of_type_error(v80, report_harness, prefix):
    with pytest.raises((ValueError, v80.poe.BotError), match="不足|没有数据|无数据|有效|可用|区间|范围|覆盖"):
        report_harness.execute(prefix + " 2025-01-01到2025-01-02")

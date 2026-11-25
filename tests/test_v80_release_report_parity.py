"""Release checks at the report boundary, using tracked V8.0 daily return archives."""
import re
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from matplotlib.backends.backend_agg import RendererAgg
from matplotlib.figure import Figure
from openpyxl import load_workbook
from PIL import Image

from test_v80_reporting_repairs_20261015 import Capture, v80, workbook_sheets


ROOT = Path(__file__).resolve().parents[1]
RECERT = ROOT / "outputs/v80_recert_20260926"
NAMES = ("Sub-A", "Sub-A-DK", "B7.8", "B7.9", "Sub-C", "Combined")
START = pd.Timestamp("2025-03-04")


def check_attachment_names(sink, command, requested_start, requested_end, actual_start, actual_end):
    run_ids = re.findall(r"报告编号：([0-9a-f]{12})。", sink.text)
    assert len(run_ids) == 1, "report text must identify this query"
    run_id = run_ids[0]
    stem = (f"req_{requested_start:%Y%m%d}_{requested_end:%Y%m%d}"
            f"_actual_{actual_start:%Y%m%d}_{actual_end:%Y%m%d}_{run_id}")
    names = [item["name"] for item in sink.attachments]
    if command == "表现":
        workbook_name = f"performance_{stem}.xlsx"
        expected = [f"perf_nav_{stem}.png", workbook_name]
    else:
        expected = [f"nav_chart_{stem}.png"]
    assert sorted(names) == sorted(expected), "attachment identity does not match query dates and report ID"
    if command == "表现":
        assert f"**{workbook_name}**" in sink.text
    return run_id


def archived_inputs(end, adk_only):
    def read(path, columns):
        return pd.read_csv(path, index_col="date", parse_dates=["date"], usecols=["date", *columns])

    # Use actual source closes, including the preceding close needed by annualization.
    cn = read(ROOT / "mnt_strategy_data_cn.csv", ["0.399006"]).loc["2025-03-03":end]
    us = read(ROOT / "mnt_strategy_data_us.csv", ["BIL"]).loc["2025-03-03":end]
    adk = read(RECERT / "l5/cn_adk_daily_rebalance.csv", ["model_return"]).loc[START:end, "model_return"]
    daily = {"Sub-A-DK": adk}
    stock = cn.copy()
    if adk_only:
        stock = stock.iloc[:0].copy()
        stock.attrs["cn_panel_error"] = "Sub-A 可核验历史不足"
        us = us.iloc[:0].copy()
        us.attrs["us_data_status"] = {"status": "unavailable"}
    else:
        daily["Sub-A"] = read(RECERT / "l5/cn_a_daily_rebalance.csv", ["model_return"]).loc[START:end, "model_return"]
        columns = {name: "formal_" + name for name in ("B7.8", "B7.9", "Sub-C")}
        us_returns = read(RECERT / "repair_20260930/bc_floor_daily.csv.gz", columns.values())
        daily.update({name: us_returns.loc[START:end, column] for name, column in columns.items()})
    return (stock, cn, us, us), daily


def check_saved_chart(figure, expected, start, end):
    figure.canvas.draw()
    width, height = figure.canvas.get_width_height()
    series_renderer = RendererAgg(width, height, figure.dpi)
    nav_axis, dd_axis = figure.axes
    assert nav_axis.get_title() == f"NAV Curve: {start:%Y-%m-%d} to {end:%Y-%m-%d}"
    nav_lines = [line for line in nav_axis.lines if not line.get_label().startswith("_")]
    dd_lines = [line for line in dd_axis.lines if line.get_transform() == dd_axis.transData]
    assert len(nav_lines) == len(dd_lines) == len(expected)
    legend = nav_axis.get_legend()
    assert legend is not None and legend.get_visible(), "missing visible NAV legend"
    labels = {line.get_label(): line for line in nav_lines}
    texts = legend.get_texts()
    assert {text.get_text() for text in texts} == set(labels), "visible legend text differs from plotted series"
    assert len(texts) == len(labels) == len(nav_lines)
    for text, handle in zip(texts, legend.get_lines(), strict=True):
        assert text.get_visible() and text.get_alpha() != 0
        assert handle.get_visible() and handle.get_alpha() != 0
        assert handle.get_color() == labels[text.get_text()].get_color(), "legend key has the wrong series color"
    observed = set()
    for line, drawdown in zip(nav_lines, dd_lines, strict=True):
        name = line.get_label().split()[0]
        name = "Combined" if name == "PV" else name
        assert name in expected and name not in observed
        observed.add(name)
        nav = expected[name]
        assert line.get_label().endswith(f"({(nav.iloc[-1] - 1) * 100:+.1f}%)")
        assert line.get_color() == drawdown.get_color()
        peaks = np.maximum.accumulate(np.r_[1., nav.values])[1:]
        for artist, values in ((line, nav.values), (drawdown, nav.values / peaks - 1)):
            assert artist.get_visible() and artist.get_alpha() != 0
            assert pd.DatetimeIndex(artist.get_xdata()).equals(nav.index)
            np.testing.assert_allclose(artist.get_ydata(), values, rtol=0, atol=1e-12)
            axis = artist.axes
            assert axis.get_visible() and artist.get_transform() == axis.transData
            pixels = artist.get_transform().transform(artist.get_xydata())
            assert all(axis.bbox.contains(x, y) for x, y in pixels), f"{name}: observation outside visible axes"
            if len(values) == 1:
                assert artist.get_marker() not in (None, "", "None", " ") and artist.get_markersize() > 0
            # A single point needs painted fill or stroke. For longer samples
            # either the line or its markers may carry the data. Draw the
            # actual artist in isolation so grid and axis pixels cannot count.
            series_renderer.clear()
            artist.draw(series_renderer)
            assert np.asarray(series_renderer.buffer_rgba())[:, :, 3].any(), f"{name}: series paints no visible pixels"
    assert observed == set(expected)


@pytest.mark.parametrize("adk_only,end", [
    pytest.param(False, START, id="one-return-day-all-sleeves"),
    pytest.param(False, pd.Timestamp("2025-03-10"), id="five-return-days-all-sleeves-weight-drift"),
    pytest.param(True, pd.Timestamp("2025-03-10"), id="only-adk-five-return-days"),
])
def test_release_report_text_workbook_and_nav(v80, monkeypatch, adk_only, end):
    frames, daily = archived_inputs(end, adk_only)
    expected = {name: (1 + returns).cumprod() for name, returns in daily.items()}
    assert all(nav.size == len(pd.bdate_range(START, end)) and np.isfinite(nav).all() for nav in expected.values())
    if not adk_only:
        expected["Combined"] = sum(expected[name] * weight for name, weight in
                                   zip(NAMES[:5], (.15, .15, .20, .20, .30), strict=True))
    empty = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    b79 = None
    if not adk_only:
        b79 = daily["B7.9"].to_frame("return")
        b79.attrs["v80_b78"] = daily["B7.8"].to_frame("return")
    results = (daily.get("Sub-A", empty).to_frame("return"), daily["Sub-A-DK"].to_frame("return"),
               b79, None, None, None, None, None)
    bot = v80.CombinedStrategyV80()
    monkeypatch.setattr(bot, "_cached_fetch_data", lambda *a, **kw: frames)
    monkeypatch.setattr(bot, "_cached_run_strategies", lambda *a, **kw: results)
    monkeypatch.setattr(v80, "_get_subc_daily_ret", lambda *a, **kw: daily["Sub-C"])
    monkeypatch.setattr(v80.requests.sessions.Session, "request", lambda *a, **kw: pytest.fail("offline report"))
    # This fixture contains archived returns only. Trade rows have a separate release check.
    for extractor in ("extract_v78_suba_rebalances", "extract_v78_adk_rebalances", "_v80_extract_subb_rebalances",
                      "extract_prod_rebalances", "extract_subc_vs_rebalances"):
        monkeypatch.setattr(v80, extractor, lambda *a, **kw: [])

    encoded = []
    savefig = Figure.savefig

    def check_and_save(figure, buffer, **kwargs):
        check_saved_chart(figure, expected, START, end)
        savefig(figure, buffer, **kwargs)
        encoded.append(buffer.getvalue())

    monkeypatch.setattr(Figure, "savefig", check_and_save)
    date_range = f"{START:%Y-%m-%d} 至 {end:%Y-%m-%d}"
    # The ADK archive has five returns; request dates on either side to distinguish
    # requested bounds from actual coverage in every public attachment.
    requested_start, requested_end = START, end
    if adk_only:
        requested_start -= pd.Timedelta(days=1)
        requested_end += pd.Timedelta(days=1)
    query_range = f"{requested_start:%Y-%m-%d} 至 {requested_end:%Y-%m-%d}"
    seen_ids = set()
    totals = [None if name not in expected else expected[name].iloc[-1] - 1 for name in NAMES]
    drawdowns = {}
    for name, nav in expected.items():
        values = np.r_[1., nav.values]
        drawdowns[name] = float(np.min(values / np.maximum.accumulate(values) - 1))
    metrics = {"累计收益": totals, "最大回撤": [drawdowns.get(name) for name in NAMES]}
    reasons = {}
    headings = ("Sub-A", "A-DK", "B7.8", "B7.9", "Sub-C", "PV组合")
    for command in ("表现", "净值曲线"):
        sink = Capture()
        monkeypatch.setattr(v80, "_sm", lambda: sink)
        monkeypatch.setattr(v80.poe, "query", SimpleNamespace(text=f"{command} {query_range}"))
        bot._run_impl()
        assert f"请求区间：{query_range}" in sink.text
        assert f"实际收益覆盖：{date_range}" in sink.text
        run_id = check_attachment_names(sink, command, requested_start, requested_end, START, end)
        assert run_id not in seen_ids, "a new query reused a previous report ID"
        seen_ids.add(run_id)
        for name in NAMES:
            assert (f"{name}：N/A（" in sink.text) == (name not in expected)
        png, = (a["contents"] for a in sink.attachments if a["name"].endswith(".png"))
        assert encoded == [png], "attachment must be the chart whose plotted data was checked"
        encoded.clear()
        with Image.open(BytesIO(png)) as image:
            assert image.format == "PNG"
            image.verify()
        if command == "表现":
            table = sink.text.split("### 查询区间指标", 1)[1]
            header, = (line for line in table.splitlines() if line.startswith("| 指标 |"))
            assert [c.strip().split("(")[0] for c in header.strip("|").split("|")][1:] == list(headings)
            for metric, values in metrics.items():
                row, = (line for line in table.splitlines() if line.startswith(f"| {metric} |"))
                cells = [cell.strip() for cell in row.strip("|").split("|")][1:]
                expected_cells = ["—" if value is None else f"{value:.2%}" for value in values]
                assert cells == expected_cells, f"表现文字 {metric}"
            xlsx, = (a["contents"] for a in sink.attachments if a["name"].endswith(".xlsx"))
            book = workbook_sheets(xlsx)
            check_excel_percentage_metrics(xlsx, metrics)
            summary = book["绩效概览"]
            assert summary["A2"] == "累计收益"
            meta = book["报告元数据"]
            fields = {key: meta["B" + cell[1:]] for cell, key in meta.items() if cell.startswith("A")}
            assert fields["run_id"] == run_id
            assert fields["requested_start"] == f"{requested_start:%Y-%m-%d}"
            assert fields["requested_end"] == f"{requested_end:%Y-%m-%d}"
            assert fields["actual_start"] == f"{START:%Y-%m-%d}" and fields["actual_end"] == f"{end:%Y-%m-%d}"
            for col, name, header, value in zip("BCDEFG", NAMES, headings, totals, strict=True):
                assert summary[col + "1"].split("(")[0] == header
                coverage = fields[name + " 收益覆盖"]
                if value is None:
                    assert summary[col + "2"] == "N/A" and coverage.startswith("N/A（")
                    assert f"{name}：{coverage}" in sink.text
                    reasons[name] = coverage
                else:
                    assert summary[col + "2"] == pytest.approx(value, rel=0, abs=1e-12)
                    assert coverage == date_range
        else:
            # Read the displayed values by named row, preserving policy for omitted sleeves.
            for name, reason in reasons.items():
                assert f"{name}：{reason}" in sink.text
            table = sink.text.split("| 策略 | 期末净值 | 区间收益 | 最大回撤 |", 1)[1]
            rows = [line.strip("|").split("|") for line in table.splitlines() if line.startswith("| ")]
            assert len(rows) == len(expected)
            for cells, name in zip(rows, (n for n in NAMES if n in expected), strict=True):
                display = cells[0].strip()
                prefix = "PV组合" if name == "Combined" else name
                assert display.split(" (")[0].split("（")[0] == prefix
                nav = expected[name].iloc[-1]
                assert cells[1].strip() == f"{nav:.4f}" and cells[2].strip() == f"{100 * (nav - 1):+.2f}%"
                assert cells[3].strip() == f"{drawdowns[name]:.2%}", f"净值文字 {name} 最大回撤"


def check_excel_percentage_metrics(blob, metrics):
    workbook = load_workbook(BytesIO(blob), read_only=True, data_only=True)
    try:
        rows = {row[0].value: row[1:] for row in workbook["绩效概览"].iter_rows()}
        for metric, expected_values in metrics.items():
            for cell, value in zip(rows[metric], expected_values, strict=True):
                if value is None:
                    assert cell.value == "N/A", (metric, cell.coordinate)
                    continue
                assert cell.value == pytest.approx(value, rel=0, abs=1e-12), (metric, cell.coordinate)
                # Excel applies one, two, or three numeric sections to positive/negative/zero.
                sections = cell.number_format.split(";")
                index = 1 if value < 0 and len(sections) >= 2 else 0
                if value == 0 and len(sections) >= 3:
                    index = 2
                section = re.sub(r"^\[(?:Black|Blue|Cyan|Green|Magenta|Red|White|Yellow|Color\d+)\]",
                                 "", sections[index].strip(), flags=re.IGNORECASE)
                number = r"(?:#,##)?0\.00%"
                if index == 1:
                    pattern = rf"(?:-{number}|\({number}\))"
                else:
                    pattern = rf"\+?{number}" if value >= 0 else number
                assert re.fullmatch(pattern, section), (metric, cell.coordinate, "Excel 百分比格式", cell.number_format)
    finally:
        workbook.close()

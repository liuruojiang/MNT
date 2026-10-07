"""Input contract and exported report parity at the real V8.0 helpers."""
import importlib.util
import io
import sys
import types
import zipfile
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def v80():
    path = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
    spec = importlib.util.spec_from_file_location("v80_report_audit_20261007", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.mark.parametrize("start", [1, True, "2026-01-01T12:00:00", "2026-01-01+08:00"])
def test_llm_date_fields_follow_declared_daily_string_contract(v80, monkeypatch, start):
    import json
    monkeypatch.setattr(v80.poe, "call", lambda *args, **kwargs: types.SimpleNamespace(
        text=json.dumps({"start": start, "end": "2026-10-07"})))
    with pytest.raises(ValueError, match="日期"):
        v80.CombinedStrategyV80()._parse_date_with_llm_fallback("表现 夏季以来")


def test_excel_has_same_five_window_metrics_and_na_reasons(v80):
    windows = []
    for label, _ in v80.PERFORMANCE_STANDARD_WINDOWS:
        windows.append({"window": label, "metrics": {
            name: {"annual": 1.25, "max_dd": -2.5} if label == "Full" else
            {"annual": None, "max_dd": None, "reason": "insufficient history"}
            for name in v80.PERFORMANCE_COLUMNS}})
    result = v80.generate_performance_excel("20261007", {}, pd.DataFrame(), [], standard_windows=windows)
    with zipfile.ZipFile(io.BytesIO(result)) as workbook:
        workbook_xml = workbook.read("xl/workbook.xml").decode()
        strings = workbook.read("xl/sharedStrings.xml").decode()
    assert "标准窗口指标" in workbook_xml
    for label, _ in v80.PERFORMANCE_STANDARD_WINDOWS:
        assert ">" + label + "<" in strings
    assert "1.25% / -2.50%" in strings
    assert "N/A (insufficient history)" in strings


def test_excel_without_window_input_explicitly_marks_all_windows_unavailable(v80):
    result = v80.generate_performance_excel("20261007", {}, pd.DataFrame(), [])
    with zipfile.ZipFile(io.BytesIO(result)) as workbook:
        strings = workbook.read("xl/sharedStrings.xml").decode()
    for label, _ in v80.PERFORMANCE_STANDARD_WINDOWS:
        assert ">" + label + "<" in strings
    assert "N/A (standard window inputs unavailable)" in strings

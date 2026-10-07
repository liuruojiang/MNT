"""Independent checks of retained audit evidence and real date-query dispatch.

Reads the existing frozen artifacts without regenerating them. The numeric
oracle below does not call production performance or combination helpers.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import pickle
import subprocess
import sys
import types
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
PRIOR = ROOT / "outputs/v80_script_audit_20261007"
HERE = ROOT / "outputs/v80_script_doublecheck_20261007"
L1 = ROOT / "outputs/v80_recert_20260926/l1_final"
SOURCE = ROOT / "mnt_bot V 8.0 plus.py"
BEFORE = ROOT / ".codex_backups/20261007_141858/mnt_bot V 8.0 plus.py"
PRIOR_AFTER = ROOT / ".codex_backups/20261007_143341/mnt_bot V 8.0 plus.py"
SOURCE_BEFORE_SHA = "cef733f30a48f2123725f5f213e483ee5112910462dea7b7f4bb47f41205414e"
SOURCE_AFTER_SHA = "776cbc35d82f7ed18719a0de62decb32e9dac65dfc5e45b4e9b6f06f52dc3395"
INPUT_SHA = "182a5c54d5c81699d8e93038695a76febd15312aa48b5864e47a46318eeba00f"
AMOUNT_SHA = "d1cb114b0f08c3f67b2f392831caddd9df7d974af0eaa10dc02d9283937c42c6"
COLUMNS = ["Sub-A", "Sub-A-DK", "B7.8", "B7.9", "Sub-C", "Combined"]
WINDOWS = ["Full", "10Y", "5Y", "3Y", "1Y"]
ORIGINAL_TEST_FILES = [
    "test_poe_adk_16_spread_decay.py", "test_v77_adk_drawdown_warning_panel.py",
    "test_suba_delayed_entry_copy.py",
    "test_v78_adk_subb_blend_display.py", "test_v78_cn_live_freshness.py",
    "test_v78_overlay_freshness_and_volreg.py", "test_v78_suba_new_signal_display.py",
    "test_v78_v79_adversarial_repairs.py", "test_v78_v79_subc_sleeve_vol.py",
    "test_v79_external_audit_repairs.py", "test_v80_cn_subc_audit_20261007.py",
    "test_v80_data_display_audit_20261007.py", "test_v80_execution_audit_20261007.py",
    "test_v80_l1_input_boundaries.py", "test_v80_l2_annualization_period.py",
    "test_v80_report_audit_20261007.py",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_prior_daily(label):
    return pd.read_csv(PRIOR / (label + "_daily.csv.gz"), index_col="date", parse_dates=True)


def reconcile_daily(before, after):
    """Reject shape/index/mask mismatches before checking numeric differences."""
    assert list(before.columns) == list(after.columns) == COLUMNS, "column contract differs"
    assert before.index.equals(after.index), "daily indices differ"
    assert isinstance(before.index, pd.DatetimeIndex)
    assert not before.index.hasnans and not before.index.has_duplicates
    assert before.index.is_monotonic_increasing
    assert before.isna().equals(after.isna()), "missing-return masks differ"
    result = {}
    for name in COLUMNS:
        left = before[name].dropna()
        right = after[name].dropna()
        assert np.isfinite(left).all() and np.isfinite(right).all()
        assert (left > -1.0).all() and (right > -1.0).all()
        delta = (right - left).abs()
        result[name] = {
            "first": str(right.index[0].date()), "last": str(right.index[-1].date()),
            "nonmissing_rows": len(right), "max_abs_daily_delta": float(delta.max()),
            "changed_days_over_1e12": int((delta > 1e-12).sum()),
        }
    return result


def initial_anchors(daily, frames):
    source = dict(zip(COLUMNS[:5], [frames[0], frames[1], frames[2], frames[2], frames[3]]))
    result = {}
    for name, frame in source.items():
        first_return = daily[name].first_valid_index()
        result[name] = max(day for day in frame.index if day < first_return)
    first_combined = daily["Combined"].first_valid_index()
    result["Combined"] = max(
        max(day for day in frame.index if day < first_combined) for frame in source.values()
    )
    return result


def independently_reconstruct_combo(daily):
    individual = {name: daily[name].dropna() for name in COLUMNS[:5]}
    start = max(series.index[0] for series in individual.values())
    end = max(series.index[-1] for series in individual.values())
    dates = pd.DatetimeIndex(sorted(set().union(*(
        set(series.loc[start:end].index) for series in individual.values()
    ))))
    capital = np.zeros(len(dates), dtype=float)
    for name, weight in zip(COLUMNS[:5], [0.15, 0.15, 0.20, 0.20, 0.30]):
        returns = individual[name].reindex(dates).fillna(0.0).to_numpy()
        capital += weight * np.cumprod(1.0 + returns)
    combined = pd.Series(capital / np.r_[1.0, capital[:-1]] - 1.0, index=dates)
    saved = daily["Combined"].dropna()
    assert combined.index.equals(saved.index)
    error = float((combined - saved).abs().max())
    assert error < 1e-12
    return {"max_abs_daily_delta": error, "rows": len(combined),
            "first": str(dates[0].date()), "last": str(dates[-1].date())}


def independently_compute_metrics(daily, frames, end="2026-09-25"):
    """Compound returns and initial-capital-inclusive MDD with separate code."""
    end = pd.Timestamp(end)
    anchors = initial_anchors(daily, frames)
    metrics = []
    for window in WINDOWS:
        start = None if window == "Full" else end.replace(year=end.year - int(window[:-1]))
        for name in COLUMNS:
            history = daily[name].dropna()
            assert np.isfinite(history).all() and (history > -1.0).all()
            row = {"window": window, "sleeve": name}
            if start is not None and history.index[0] > start + pd.Timedelta(days=7):
                row.update(annual=None, max_dd=None, reason="insufficient history")
                metrics.append(row)
                continue
            period = history.loc[:end] if start is None else history.loc[start:end]
            assert len(period) >= 20
            prior_dates = history.index[history.index < period.index[0]]
            anchor = prior_dates[-1] if len(prior_dates) else anchors[name]
            span_days = (period.index[-1] - anchor).days
            final_log_nav = math.fsum(math.log1p(float(value)) for value in period)
            annual = math.expm1(final_log_nav * 365.25 / span_days) * 100.0
            nav = np.cumprod(1.0 + period.to_numpy())
            peak = np.maximum.accumulate(np.r_[1.0, nav])[1:]
            mdd = float(np.min(nav / peak - 1.0) * 100.0)
            row.update(annual=annual, max_dd=mdd, reason=None,
                       start=str(period.index[0].date()), end=str(period.index[-1].date()),
                       period_start=str(anchor.date()), span_days=span_days, rows=len(period))
            metrics.append(row)
    return metrics


def check_metric_table(saved, recomputed):
    expected_keys = {(window, name) for window in WINDOWS for name in COLUMNS}
    assert len(saved) == 30
    assert not saved.duplicated(["window", "sleeve"]).any(), "duplicate metric keys"
    assert set(zip(saved["window"], saved["sleeve"])) == expected_keys
    oracle = {(row["window"], row["sleeve"]): row for row in recomputed}
    max_delta = {"annual": 0.0, "max_dd": 0.0}
    for _, actual in saved.iterrows():
        expected = oracle[(actual["window"], actual["sleeve"])]
        for field in max_delta:
            if expected[field] is None:
                assert pd.isna(actual[field]) and pd.notna(actual["reason"])
            else:
                assert pd.notna(actual[field]) and pd.isna(actual["reason"])
                delta = abs(float(actual[field]) - expected[field])
                max_delta[field] = max(max_delta[field], delta)
                assert delta < 1e-9, (actual["window"], actual["sleeve"], field, delta)
        if expected["annual"] is not None:
            assert actual["start"] == expected["start"] and actual["end"] == expected["end"]
    return max_delta


def read_inputs():
    assert sha(L1 / "formal_inputs.pkl") == INPUT_SHA
    assert sha(L1 / "suba_amount.pkl") == AMOUNT_SHA
    with (L1 / "formal_inputs.pkl").open("rb") as handle:
        return pickle.load(handle)


def captured_chat_excel_reconciliation():
    """Check actual handler artifacts cell by cell, not global XML substrings."""
    text_path = HERE / "query_4.txt"
    book_path = HERE / "query_4_performance_20260926.xlsx"
    chat = text_path.read_text(encoding="utf-8")
    chat_rows = {}
    for line in chat.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if cells[0] in WINDOWS:
            assert cells[0] not in chat_rows
            assert len(cells) == 7
            chat_rows[cells[0]] = cells[1:]
    assert set(chat_rows) == set(WINDOWS)
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    relns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    with zipfile.ZipFile(book_path) as archive:
        strings_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(part.text or "" for part in item.iter(ns + "t"))
                   for item in strings_root.findall(ns + "si")]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet_id = next(item.attrib[relns + "id"] for item in workbook.iter(ns + "sheet")
                        if item.attrib["name"] == "标准窗口指标")
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(item.attrib["Target"] for item in relations if item.attrib["Id"] == sheet_id)
        sheet = ET.fromstring(archive.read("xl/" + target))
        values = {}
        for cell in sheet.iter(ns + "c"):
            value = cell.find(ns + "v")
            if value is None:
                continue
            values[cell.attrib["r"]] = strings[int(value.text)] if cell.attrib.get("t") == "s" else value.text
    inputs = read_inputs()
    end = min(pd.Timestamp(frame.index[-1]) for frame in inputs["frames"])
    oracle_rows = independently_compute_metrics(read_prior_daily("after"), inputs["frames"], end=end)
    oracle = {(item["window"], item["sleeve"]): item for item in oracle_rows}
    checked_cells = 0
    checked_numeric_cells = 0
    for row_number, label in enumerate(WINDOWS, 2):
        assert values["A" + str(row_number)] == label
        for column_letter, name, chat_cell in zip("BCDEFG", COLUMNS, chat_rows[label]):
            book_cell = values[column_letter + str(row_number)]
            assert book_cell == chat_cell, (label, name, book_cell, chat_cell)
            expected = oracle[(label, name)]
            if expected["annual"] is not None:
                expected_cell = f'{expected["annual"]:.2f}% / {expected["max_dd"]:.2f}%'
                assert book_cell == expected_cell, (label, name, book_cell, expected_cell)
                checked_numeric_cells += 1
            else:
                assert book_cell.startswith("N/A (insufficient post-start history:")
                required = end.replace(year=end.year - int(label[:-1]))
                assert str(required.date()) in book_cell
            checked_cells += 1
    return {"chat": text_path.name, "workbook": book_path.name,
            "chat_sha256": sha(text_path), "workbook_sha256": sha(book_path),
            "same_standard_window_cells": checked_cells,
            "independent_numeric_cell_matches": checked_numeric_cells,
            "same_na_reason_cells": checked_cells - checked_numeric_cells,
            "cutoff": str(end.date())}


@pytest.fixture(scope="module")
def v80():
    spec = importlib.util.spec_from_file_location("v80_doublecheck_evidence", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(scope="module")
def retained_evidence():
    required = [BEFORE, PRIOR_AFTER, L1 / "formal_inputs.pkl", L1 / "suba_amount.pkl",
                HERE / "query_4.txt", HERE / "query_4_performance_20260926.xlsx"]
    required.extend(PRIOR / (label + suffix) for label in ("before", "after")
                    for suffix in ("_status.json", "_daily.csv.gz", "_window_metrics.csv"))
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        pytest.skip("optional retained-evidence audit requires git-ignored local artifacts: " + ", ".join(missing))


def test_retained_status_identifies_real_frozen_objects(retained_evidence):
    assert sha(BEFORE) == SOURCE_BEFORE_SHA
    assert sha(PRIOR_AFTER) == SOURCE_AFTER_SHA
    for label, source_hash in (("before", SOURCE_BEFORE_SHA), ("after", SOURCE_AFTER_SHA)):
        status = json.loads((PRIOR / (label + "_status.json")).read_text(encoding="utf-8"))
        assert status["source_sha256"] == source_hash
        assert status["input_sha256"] == INPUT_SHA
        assert status["amount_sha256"] == AMOUNT_SHA
        assert not status["network_allowed"] and not status["data_is_current"]
    read_inputs()


def test_retained_daily_returns_have_identical_shape_masks_and_values(retained_evidence):
    reconciled = reconcile_daily(read_prior_daily("before"), read_prior_daily("after"))
    status = json.loads((PRIOR / "after_status.json").read_text(encoding="utf-8"))
    for name, item in reconciled.items():
        dates = status["dates"][name]
        assert [item["first"], item["last"], item["nonmissing_rows"]] == [
            str(pd.Timestamp(dates[0]).date()), str(pd.Timestamp(dates[1]).date()), dates[2]
        ]
        assert item["max_abs_daily_delta"] < 1e-12 and item["changed_days_over_1e12"] == 0


def test_retained_combo_reconstructs_from_independent_sleeve_capital(retained_evidence):
    independently_reconstruct_combo(read_prior_daily("after"))


@pytest.mark.parametrize("label", ["before", "after"])
def test_retained_five_window_numbers_recompute_independently(label, retained_evidence):
    inputs = read_inputs()
    oracle = independently_compute_metrics(read_prior_daily(label), inputs["frames"])
    saved = pd.read_csv(PRIOR / (label + "_window_metrics.csv"))
    check_metric_table(saved, oracle)


def test_reconciliation_rejects_nan_that_previous_subtraction_can_miss(retained_evidence):
    before = read_prior_daily("before")
    altered = before.copy()
    day = altered["Combined"].first_valid_index()
    altered.loc[day, "Combined"] = np.nan
    naive_delta = altered - before
    assert naive_delta["Combined"].abs().max() == 0.0
    assert int((naive_delta["Combined"].abs() > 1e-12).sum()) == 0
    with pytest.raises(AssertionError, match="missing-return masks"):
        reconcile_daily(before, altered)


def test_window_reconciliation_rejects_dropped_or_duplicated_key(retained_evidence):
    inputs = read_inputs()
    daily = read_prior_daily("after")
    oracle = independently_compute_metrics(daily, inputs["frames"])
    saved = pd.read_csv(PRIOR / "after_window_metrics.csv")
    corrupted = saved.copy()
    corrupted.loc[0, ["window", "sleeve"]] = corrupted.loc[1, ["window", "sleeve"]].to_numpy()
    with pytest.raises(AssertionError, match="duplicate metric keys"):
        check_metric_table(corrupted, oracle)


def test_real_handler_chat_and_workbook_standard_windows_match_every_cell(retained_evidence):
    captured_chat_excel_reconciliation()


class _Capture:
    def __init__(self):
        self.text = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def write(self, value):
        self.text.append(str(value))


class _ReachedDataBoundary(Exception):
    pass


def probe_llm_single_range_dispatch(module):
    """Execute actual dispatch and handler date parsing, stopping before fetch."""
    bot = module.CombinedStrategyV80()
    captured = _Capture()
    calls = []
    parsed_ranges = []
    responses = [
        {"start": "2026-06-01", "end": "2026-09-24"},
        {"start": "2025-06-01", "end": "2026-09-24"},
    ]
    original_parse = bot._parse_date_with_llm_fallback

    def llm(*args, **kwargs):
        calls.append(args)
        return types.SimpleNamespace(text=json.dumps(responses[min(len(calls) - 1, 1)]))

    def parser(query):
        result = original_parse(query)
        parsed_ranges.append([str(value.date()) if value is not None else None for value in result])
        return result

    with patch.object(module, "_sm", return_value=captured), \
            patch.object(module, "beijing_now", return_value=pd.Timestamp("2026-09-26 08:00:00").to_pydatetime()), \
            patch.object(module.poe, "query", types.SimpleNamespace(text="表现 夏季以来")), \
            patch.object(module.poe, "call", side_effect=llm), \
            patch.object(bot, "_parse_date_with_llm_fallback", side_effect=parser), \
            patch.object(bot, "_cached_fetch_data", side_effect=_ReachedDataBoundary):
        with pytest.raises(_ReachedDataBoundary):
            bot._run_impl()
    return {"llm_calls": len(calls), "parsed_ranges": parsed_ranges,
            "reached_actual_performance_data_boundary": True}


def test_single_llm_range_is_preserved_by_real_performance_dispatch(v80):
    observed = probe_llm_single_range_dispatch(v80)
    assert observed["llm_calls"] == 1, observed
    assert observed["parsed_ranges"] == [["2026-06-01", "2026-09-24"]], observed


def build_notes():
    inputs = read_inputs()
    before = read_prior_daily("before")
    after = read_prior_daily("after")
    reconciliation = reconcile_daily(before, after)
    combo_reconciliation = independently_reconstruct_combo(after)
    after_oracle = independently_compute_metrics(after, inputs["frames"])
    after_metric_delta = check_metric_table(pd.read_csv(PRIOR / "after_window_metrics.csv"), after_oracle)
    common_cutoff = min(pd.Timestamp(frame.index[-1]) for frame in inputs["frames"])
    cutoff_oracle = independently_compute_metrics(after, inputs["frames"], end=common_cutoff)
    query_excel_reconciliation = captured_chat_excel_reconciliation()
    collect = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]
        + [str(ROOT / "tests" / name) for name in ORIGINAL_TEST_FILES],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    counts = Counter(line.split("::", 1)[0].split("/")[-1] for line in collect.stdout.splitlines() if "::" in line)
    current_count = sum(count for name, count in counts.items() if name.startswith("test_v80_"))
    source_hash = sha(SOURCE)
    spec = importlib.util.spec_from_file_location("v80_doublecheck_evidence_notes", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    llm_probe = probe_llm_single_range_dispatch(module)
    sys.modules.pop(spec.name, None)
    assert sha(SOURCE) == source_hash, "source changed during evidence checks"
    notes = {
        "source_sha256_at_check": source_hash,
        "retained_audit_source_sha256": SOURCE_AFTER_SHA,
        "input_sha256": INPUT_SHA, "amount_sha256": AMOUNT_SHA,
        "scope": "independent retained-evidence reconciliation; no strategy replay or network refresh",
        "original_suite_counts_by_file": dict(counts),
        "original_suite_total": sum(counts.values()),
        "v80_direct_source_tests": current_count,
        "other_source_tests": sum(counts.values()) - current_count,
        "daily_reconciliation": reconciliation,
        "independent_combo_reconciliation": combo_reconciliation,
        "independent_metric_max_error_pp": after_metric_delta,
        "independent_metrics_20260925": after_oracle,
        "normal_handler_cutoff_from_min_input_tail": str(common_cutoff.date()),
        "independent_metrics_at_normal_handler_cutoff": cutoff_oracle,
        "captured_query_excel_reconciliation": query_excel_reconciliation,
        "single_llm_range_dispatch_probe": llm_probe,
        "prior_replay_evidence_gaps": [
            "Source SHA is recorded and checked for in-run change, but not pinned to a declared before/after object.",
            "Input hashes are checked against colocated manifests; no literal expected freeze hashes in the runner.",
            "Daily comparison checks index equality but not columns, nonmissing masks, or finite values before subtraction.",
            "Metric comparison subtracts rows positionally without checking window/sleeve keys, masks, and reasons.",
            "beijing_now is frozen from the manifest, but the frozen clock is not written into before/after status.",
            "Network blocker patches requests.Session.request rather than all possible transports; traced current replay is requests-based.",
            "Prior date helper and XML string-presence tests do not establish whole-query handler or per-cell Excel parity.",
        ],
        "certification_boundary": "Matched frozen paper arithmetic is not executable/account/self-financing or latest online-data certification.",
    }
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / "evidence_notes.json").write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: notes[key] for key in (
        "source_sha256_at_check", "original_suite_total", "v80_direct_source_tests", "other_source_tests",
        "daily_reconciliation", "independent_metric_max_error_pp", "normal_handler_cutoff_from_min_input_tail",
        "single_llm_range_dispatch_probe")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build_notes()

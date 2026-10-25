"""Real KMLM seam plus explicit adversarial mutations; no network or credentials."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from source_audit.compare import compare, tiingo_rows, yahoo_rows
from source_audit.compare import split_comparison_basis
from source_audit.transport import fetch

spec = importlib.util.spec_from_file_location("source_audit_cli", ROOT / "tools/audit_us_sources.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
PROFILE = json.loads(cli.PROFILE.read_text(encoding="utf-8"))
FIXTURE = json.loads((ROOT / "tests/fixtures/us_source_audit/kmlm_real_seam.json").read_text())
START, END = "2022-12-27", "2022-12-29"


def frames():
    data = copy.deepcopy(FIXTURE)
    return (tiingo_rows(data["tiingo"], "KMLM", START, END, data["metadata"]),
            yahoo_rows(data["yahoo"], "KMLM", START, END))


def result(t, y):
    return compare("KMLM", t, y, FIXTURE["metadata"], ["2022-12-27", "2022-12-28", "2022-12-29"], START, END, PROFILE["audit_thresholds_not_strategy_parameters"])


def corrected_yahoo(y):
    y = copy.deepcopy(y)
    day, prev = "2022-12-28", "2022-12-27"
    y[day]["divCash"] = 4.0377
    # Change exactly the pre-exdate factor; preserve Yahoo's adjustment basis.
    scale = (1 - 4.0377 / y[prev]["close"]) / (1 - 2.481 / y[prev]["close"])
    y[prev]["adjClose"] *= scale
    y[prev]["adjOpen"] *= scale
    return y


def test_real_missing_ordinary_distribution_is_blocked():
    t, y = frames()
    r = result(t, y)
    assert r["status"] == "BLOCKED"
    assert r["counts"]["cash"] == 1
    assert r["details"][0]["date"] == "2022-12-28"
    assert r["details"][0]["tiingo_cash"] == 4.0377
    assert r["production_approved"] is False


def test_upstream_corrected_cash_and_factor_are_not_repaired_again():
    t, y = frames()
    y = corrected_yahoo(y)
    frozen = copy.deepcopy((t, y))
    r = result(t, y)
    assert r["counts"]["cash"] == 0
    assert r["counts"]["unexplained_adjustment"] == 0
    assert r["counts"]["action_basis"] == 1
    assert r["status"] == "REVIEW"  # Different documented return bases still review.
    assert (t, y) == frozen


def test_double_adjustment_despite_corrected_cash_is_blocked():
    t, y = frames()
    y = corrected_yahoo(y)
    y[START]["adjClose"] *= 0.9512297157967274
    r = result(t, y)
    assert r["status"] == "BLOCKED"
    assert r["counts"]["unexplained_adjustment"] > 0


def test_common_normalization_is_not_mistaken_for_a_return_error():
    t, y = frames()
    y = corrected_yahoo(y)
    a = result(t, y)
    for row in y.values():
        row["adjClose"] *= 0.3
        row["adjOpen"] *= 0.3
    b = result(t, y)
    assert a["counts"] == b["counts"]


@pytest.mark.parametrize("provider", ["tiingo", "yahoo", "both"])
def test_missing_session_is_not_hidden_by_intersection(provider):
    t, y = frames()
    if provider in {"tiingo", "both"}:
        t.pop("2022-12-28")
    if provider in {"yahoo", "both"}:
        y.pop("2022-12-28")
    r = result(t, y)
    assert "COVERAGE_OR_FRESHNESS" in r["issues"]
    assert r["status"] == "BLOCKED"


def test_non_action_factor_error_is_blocked():
    t, y = frames()
    y[END]["adjClose"] *= 1.02
    assert result(t, y)["counts"]["unexplained_adjustment"] == 1


def test_volume_units_are_separate_from_price_acceptance():
    t, y = frames()
    y = corrected_yahoo(y)
    for row in y.values():
        row["volume"] *= 100
    r = result(t, y)
    assert r["counts"]["volume"] == 3
    assert "VOLUME_REVIEW" in r["issues"]


def test_duplicate_dates_and_adjusted_open_corruption_rejected():
    data = copy.deepcopy(FIXTURE)
    with pytest.raises(ValueError):
        tiingo_rows(data["tiingo"] * 2, "KMLM", START, END, data["metadata"])
    data["tiingo"][0]["adjOpen"] *= 1.1
    with pytest.raises(ValueError):
        tiingo_rows(data["tiingo"], "KMLM", START, END, data["metadata"])


def test_yahoo_symbol_currency_timezone_contract():
    for field, value in (("symbol", "QQQ"), ("currency", "CNY"), ("exchangeTimezoneName", "UTC")):
        data = copy.deepcopy(FIXTURE["yahoo"])
        data["chart"]["result"][0]["meta"][field] = value
        with pytest.raises(ValueError):
            yahoo_rows(data, "KMLM", START, END)


def test_ny_day_boundary_handles_both_dst_seasons():
    assert cli.latest_eligible_day(datetime(2026, 7, 2, 0, 30, tzinfo=timezone.utc)) == "2026-06-30"
    assert cli.latest_eligible_day(datetime(2026, 7, 2, 1, 0, tzinfo=timezone.utc)) == "2026-07-01"
    assert cli.latest_eligible_day(datetime(2026, 1, 6, 1, 30, tzinfo=timezone.utc)) == "2026-01-04"
    assert cli.latest_eligible_day(datetime(2026, 1, 6, 2, 0, tzinfo=timezone.utc)) == "2026-01-05"


def test_credentials_cannot_be_sent_to_other_hosts(tmp_path):
    with pytest.raises(ValueError):
        fetch("https://example.com/", tmp_path / "x.json", "FAKE_TEST_SENTINEL")


def test_failed_live_receipt_cannot_reuse_a_good_file(tmp_path):
    # Even an available good JSON is rejected when that run's receipt failed.
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw/yahoo_SPY.json").write_text(json.dumps(FIXTURE["yahoo"]))
    snapshot = {"receipts": {"yahoo_SPY": {"status": 429}}, "cutoff": END, "mode": "LIVE_FRESH"}
    report = cli.build_report(PROFILE, snapshot, tmp_path, {name: {} for name in PROFILE["projects"]})
    assert all(item["status"] == "BLOCKED" for item in report["assets"])
    assert all(not item["production_approved"] for item in report["projects"].values())


def test_tampered_snapshot_cannot_be_accepted(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw/yahoo_SPY.json").write_text(json.dumps(FIXTURE["yahoo"]))
    snapshot = {"receipts": {"yahoo_SPY": {"status": 200, "sha256": "0" * 64}}, "cutoff": END, "mode": "OFFLINE_REPLAY"}
    report = cli.build_report(PROFILE, snapshot, tmp_path, {name: {} for name in PROFILE["projects"]})
    assert all(item["status"] == "BLOCKED" for item in report["assets"])


@pytest.mark.parametrize("symbol", ["GLDM", "EEM"])
def test_real_forward_and_reverse_splits_use_same_share_basis(symbol):
    fixture = json.loads((ROOT / "tests/fixtures/us_source_audit/split_real_seams.json").read_text())[symbol]
    start, end, meta = fixture["start"], fixture["end"], fixture["metadata"]
    t = tiingo_rows(fixture["tiingo"], symbol, start, end, meta)
    y = yahoo_rows(fixture["yahoo"], symbol, start, end)
    before = copy.deepcopy(t)
    normalized = split_comparison_basis(t)
    assert t == before
    # Actual split flags agree, including Tiingo's 3.000003 representation.
    r = compare(symbol, t, y, meta, sorted(y), start, end, PROFILE["audit_thresholds_not_strategy_parameters"])
    assert r["counts"]["split"] == 0
    assert r["counts"]["unexplained_adjustment"] == 0
    if symbol == "GLDM":
        assert abs(normalized[start]["close"] / y[start]["close"] - 1) < 0.0001
        assert normalized[start]["volume"] == t[start]["volume"] * 0.5
        assert normalized[end]["close"] == t[end]["close"]
        assert r["counts"]["raw_price"] == 0


def test_provider_quota_failure_stops_remaining_requests_without_old_cache(tmp_path, monkeypatch):
    calls = []
    fixture = copy.deepcopy(FIXTURE["yahoo"])
    fixture["chart"]["result"][0]["meta"]["symbol"] = "SPY"
    def fake_fetch(url, path, token=None):
        calls.append(url)
        if "tiingo.com" in url:
            return {"status": 429}, None
        body = json.dumps(fixture).encode()
        path.write_bytes(body)
        return {"status": 200, "sha256": cli.sha256(body)}, fixture
    monkeypatch.setattr(cli, "fetch", fake_fetch)
    monkeypatch.setattr(cli, "decrypt_dpapi", lambda p: "FAKE_TEST_SENTINEL")
    monkeypatch.setattr(cli, "latest_eligible_day", lambda: END)
    args = type("Args", (), {"workspace": ROOT.parent, "output": tmp_path, "offline_snapshot": None,
                            "cutoff": END, "tiingo_credential": tmp_path / "unused.dpapi"})()
    assert cli.run(args) == 2
    assert len([url for url in calls if "tiingo.com" in url]) == 1
    report = json.loads(next(tmp_path.glob("*/report.json")).read_text())
    assert all(row["status"] == "BLOCKED" for row in report["assets"])
    assert "FAKE_TEST_SENTINEL" not in "".join(p.read_text() for p in tmp_path.rglob("*.json"))


def test_authenticated_response_echo_is_redacted_before_archiving(tmp_path, monkeypatch):
    import urllib.request
    class Response:
        code = 403
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, size):
            return b'{"error":"FAKE_TEST_SENTINEL"}'
    class Opener:
        def open(self, request, timeout):
            assert "FAKE_TEST_SENTINEL" not in request.full_url
            return Response()
    monkeypatch.setattr(urllib.request, "build_opener", lambda handler: Opener())
    path = tmp_path / "response.json"
    receipt, value = fetch("https://api.tiingo.com/tiingo/daily/SPY", path, "FAKE_TEST_SENTINEL")
    assert value is None and receipt["status"] == 403
    assert "FAKE_TEST_SENTINEL" not in path.read_text() + json.dumps(receipt)


def test_credential_redirect_to_other_host_is_rejected(tmp_path, monkeypatch):
    import urllib.request
    def opener(handler):
        class Opener:
            def open(self, request, timeout):
                return handler.redirect_request(request, None, 302, "", {}, "https://example.com/")
        return Opener()
    monkeypatch.setattr(urllib.request, "build_opener", opener)
    receipt, value = fetch("https://api.tiingo.com/tiingo/daily/SPY", tmp_path / "x.json", "FAKE_TEST_SENTINEL")
    assert receipt["error_type"] == "ValueError" and value is None
    assert not (tmp_path / "x.json").exists()


@pytest.mark.parametrize("field,value", [("close", float("nan")), ("volume", float("inf")), ("divCash", -1), ("splitFactor", 0)])
def test_invalid_tiingo_numbers_fail_before_any_acceptance(field, value):
    data = copy.deepcopy(FIXTURE)
    data["tiingo"][0][field] = value
    with pytest.raises(ValueError):
        tiingo_rows(data["tiingo"], "KMLM", START, END, data["metadata"])


def test_changed_formal_source_blocks_project_scope(tmp_path):
    report = cli.build_report(PROFILE, {"receipts": {}, "cutoff": END, "mode": "OFFLINE_REPLAY"}, tmp_path,
                             {name: {"matches_profile": False, "unchanged_during_audit": True} for name in PROFILE["projects"]})
    assert all(p["status"] == "BLOCKED_SOURCE_SCOPE" for p in report["projects"].values())

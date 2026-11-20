"""V8.0 release gate: confirmed events must survive one additional market session."""
from collections import Counter
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from openpyxl import load_workbook
import pandas as pd
import pytest

from test_v80_reporting_repairs_20261015 import Capture, ROOT, v80


CN = ROOT / "research/data_quality/20261106_bond_intraday_acceptance/a_chain/end"
BASE_COLUMNS = ["日期", "北京时间", "策略", "卖出", "卖出价格", "买入", "买入价格"]
CLOCK_COLUMNS = ["信号观察", "价格确认", "模型计价"]


def read_prices(path):
    return pd.read_csv(path, index_col="date", parse_dates=True, float_precision="round_trip")


def price_prefix(frame, day, end):
    # All inputs are cut before model execution, including the amount-overlay features.
    prefix = frame.loc[:end]
    expected = [day] if end == day else [day, end]
    assert prefix.loc[day:].index.tolist() == expected
    return prefix


def dk_prices():
    labels = {"1.000852": "DK_ZZ1000", "1.000016": "DK_SZ50", "1.000300": "DK_HS300",
              "1.000905": "DK_ZZ500", "0.399006": "DK_CYB"}
    frame = read_prices(ROOT / "mnt_strategy_data_cn.csv")
    return frame[list(labels)].rename(columns=labels).dropna().loc["2014-10-17":]


def workbook_rows(blob, records, day):
    book = load_workbook(BytesIO(blob), read_only=True)
    try:
        head, *data = book["调仓记录"].values
        required = BASE_COLUMNS + (CLOCK_COLUMNS if any("模型计价" in item for item in records) else [])
        assert list(head) == required
        expected = [tuple(row.get(field) if row.get(field) != "" else None for field in head)
                    for row in records]
        assert len(data) == len(expected)
        for actual, source in zip(data, expected, strict=True):
            for value, reference in zip(actual, source, strict=True):
                if isinstance(reference, float):
                    assert value == pytest.approx(reference, rel=1e-14, abs=1e-14)
                else:
                    assert value == reference
        # Another date may add clock columns to the sheet. Compare their values
        # on the observed date, treating absent optional columns as blank.
        rows = [dict(zip(head, row, strict=True)) for row in data if row[0] == str(day.date())]
        return [tuple(row.get(field) for field in BASE_COLUMNS + CLOCK_COLUMNS) for row in rows]
    finally:
        book.close()


def query_snapshot(v, frames, feature, day, end, confirmed_at, us_open=None):
    snapshots = []
    for query, writer, record_arg in [
        (f"表现 {day:%Y-%m-%d} 至 {end:%Y-%m-%d}", "generate_performance_excel", 3),
        ("信号", "generate_signal_excel", 2),
    ]:
        bot = v.CombinedStrategyV80()
        bot._us_open = us_open or {}
        sink = Capture()
        with patch.object(v, "beijing_now", return_value=confirmed_at), \
             patch.object(v.poe, "query", SimpleNamespace(text=query)), \
             patch.object(bot, "_cached_fetch_data", return_value=frames), \
             patch.object(v, "_load_suba_volume_signal", return_value=(feature.rule_on, feature)), \
             patch.object(v, "_sm", return_value=sink), \
             patch.object(v, writer, wraps=getattr(v, writer)) as exporter:
            if confirmed_at.year == 2025 and query == "信号":
                # The auxiliary turnover warning panel has no 2025 live calendar.
                # Real close targets, trade collection and signal attachments run as usual.
                with patch.object(v, "_write_volume_warning_panel"):
                    bot.run()
            else:
                bot.run()
        assert exporter.call_count == 1, f"{query}: expected one workbook. {sink.text[-1500:]}"
        records = exporter.call_args.args[record_arg]
        blob, = [file["contents"] for file in sink.attachments if file["name"].endswith(".xlsx")]
        rows = [row for row in records if row["日期"] == str(day.date())]
        assert rows, f"{query}: expected a confirmed rebalance on {day.date()}"
        snapshots.append((rows, Counter(workbook_rows(blob, records, day))))
    performance, signal = snapshots
    assert signal[1] == performance[1], f"Signal and performance attachments disagree on {day.date()} as of {end.date()}"
    return performance, signal


@pytest.fixture
def amount_feature(v80, monkeypatch):
    def offline(*args, **kwargs):
        pytest.fail("Release replay attempted a network request")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", offline)
    feature = pd.read_pickle(CN / "native_result.pkl").filter(regex="^suba_volume_")
    return feature.rename(columns=lambda name: name.removeprefix("suba_volume_"))


@pytest.mark.parametrize("sleeve,day,next_session", [
    ("Sub-A", "2026-10-09", "2026-10-12"),
    ("ADK", "2026-06-11", "2026-06-12"),
])
def test_confirmed_cn_events_survive_next_session(v80, amount_feature, sleeve, day, next_session):
    day, next_session = pd.Timestamp(day), pd.Timestamp(next_session)
    stock = read_prices(CN / "native_prices.csv")
    pairs = dk_prices()
    unavailable_us = pd.DataFrame(index=pd.DatetimeIndex([]))
    unavailable_us.attrs["us_data_status"] = {"status": "unavailable"}
    snapshots = []
    for end in (day, next_session):
        cn = price_prefix(stock, day, end)
        feature = price_prefix(amount_feature, day, end)
        if sleeve == "ADK":
            dk = price_prefix(pairs, day, end)
        else:
            # This frozen five-index panel ends before the October bond event.
            dk = pairs.iloc[:0].copy()
            dk.attrs["cn_panel_error"] = "冻结 ADK 行情未覆盖本日"
        snapshots.append(query_snapshot(v80, (cn, dk, unavailable_us, unavailable_us), feature,
                                        day, end, end + pd.Timedelta(hours=16)))
    assert snapshots[0] == snapshots[1]
    (rows, _), _ = snapshots[0]
    if sleeve == "Sub-A":
        bond, = [row for row in rows if row["买入"] == v80.CN_BOND_NAME]
        assert bond["买入价格"] == pytest.approx(231.096)
        assert "15:30" in bond["价格确认"] and "实际成交时刻未核验" in bond["模型计价"]
    else:
        change, = [row for row in rows if row.get("record_kind") == "close_target"]
        current = "".join(change["卖出"].split())
        target = "".join(change["买入"].split())
        assert "做多上证50/做空中证1000/0.88x" in current
        assert "做多上证50/做空创业板/0.54x" in target
        assert change["日期口径"] == "signal_day" and change["买入价格"] is change["卖出价格"] is None


def test_confirmed_us_events_survive_next_session_in_report(v80, amount_feature):
    # Frozen 2026-09-26 recertification inputs, subset 2023-01-03..2025-11-17.
    # l1_final/formal_inputs.pkl SHA256 182a5c54d5c81699d8e93038695a76febd15312aa48b5864e47a46318eeba00f
    # close_* = frames[2], open_* = us_open, subc_EMXC = frames[3].EMXC.
    # open_EMXC_native_open = Yahoo EMXC adjusted open from l1_final/us_raw_ohlc.pkl
    # SHA256 01ba842c1d8ef688be14c5894a77a11e80f03224f20a6d1fe7c3df2b2bf67f50.
    prices = read_prices(ROOT / "tests/fixtures/v80_release_us_20251117.csv.gz")
    stock, pairs = read_prices(CN / "native_prices.csv"), dk_prices()
    day, next_session = pd.to_datetime(["2025-11-14", "2025-11-17"])
    prod_columns = "VTI QQQ AVUV VEA AVDV VGIT DBMF KMLM GLD BTC-USD BIL SPY QQQM GLDM IBIT PDBC EMXC AGG UUP".split()
    snapshots = []
    for end in (day, next_session):
        panel = price_prefix(prices, day, end)
        close = panel.filter(regex="^close_").rename(columns=lambda c: c.removeprefix("close_"))
        prod = close[prod_columns].copy()
        prod["EMXC"] = panel["subc_EMXC"]
        us_open = {key.removeprefix("open_"): panel[key].dropna() for key in panel if key.startswith("open_")}
        cn, dk, feature = (price_prefix(frame, day, end) for frame in (stock, pairs, amount_feature))
        # US close is already confirmed by 07:00 Beijing the following morning.
        snapshots.append(query_snapshot(v80, (cn, dk, close, prod), feature, day, end,
                                        end + pd.Timedelta(days=1, hours=7), us_open))
    assert snapshots[0] == snapshots[1]
    (rows, _), _ = snapshots[0]
    for label in ("B7.8", "B7.9", "Sub-C"):
        entries = [row for row in rows if row["策略"] == label]
        assert entries, f"{label}: missing {day.date()} execution"
        assert all(row["日期口径"] == "execution_day" for row in entries)
        assert any("开" in str(row.get(field)) for row in entries for field in ("卖出价格", "买入价格"))
    assert any(row.get("execution_at") == "2025-11-14T22:30:00+08:00" for row in rows if row["策略"] == "Sub-C")

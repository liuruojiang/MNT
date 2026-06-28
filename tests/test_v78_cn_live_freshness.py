import importlib.util
import inspect
from pathlib import Path

import pandas as pd
def load_v78_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "mnt_bot V 7.8 plus.py"
    spec = importlib.util.spec_from_file_location("mnt_bot_v78_plus", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fetch_us_yahoo_daily_dates_are_parsed_in_utc():
    module = load_v78_module()
    source = inspect.getsource(module._fetch_us_yahoo)

    assert 'pd.Timestamp.fromtimestamp(ts, tz="UTC")' in source
    assert "pd.Timestamp.fromtimestamp(ts).strftime" not in source


def test_sp500_risk_regime_has_no_embedded_numeric_fallback(monkeypatch):
    module = load_v78_module()

    monkeypatch.setattr(
        module,
        "_fetch_sp500_risk_regime_live_snapshot",
        lambda: (_ for _ in ()).throw(RuntimeError("live unavailable")),
    )

    try:
        module._load_sp500_risk_regime_snapshot(
            search_paths=[],
            live_fetch=True,
            allow_embedded=True,
        )
    except RuntimeError as exc:
        text = str(exc)
    else:
        raise AssertionError("embedded S&P risk snapshot should not provide stale numeric fallback")

    assert "live unavailable" in text


def test_realtime_cn_snapshot_stale_uses_v77_warning_instead_of_raising():
    module = load_v78_module()
    stale = pd.DataFrame({"close": [100.0]}, index=pd.to_datetime(["2026-06-12"]))
    fresh = pd.DataFrame({"close": [101.0]}, index=pd.to_datetime(["2026-06-15"]))
    cn_raw = {secid: fresh.copy() for secid in module.CN_STOCK_CODES}
    cn_raw[module.CN_ZZHL_INDEX_SECID] = stale
    chunks = []

    module._write_cn_after_close_stale_warning_or_raise(
        chunks.append,
        cn_raw,
        pd.Timestamp("2026-06-15").date(),
        include_cn_live_snapshot=True,
    )

    text = "".join(chunks)
    assert "数据延迟" in text
    assert "中证红利低波100" in text
    assert "信号可能不准确" in text


def test_cn_latest_data_source_label_prefers_live_snapshot_source():
    module = load_v78_module()
    df = pd.DataFrame(
        {
            "close": [100.0, 101.0],
            "source": ["csindex:930955", "EastMoney realtime snapshot"],
            "is_live_bar": [False, True],
        },
        index=pd.to_datetime(["2026-06-12", "2026-06-15"]),
    )

    label = module._cn_latest_data_source_label(df, "csindex:930955")

    assert label == "EastMoney realtime snapshot"


def test_cn_realtime_close_uses_vendor_alias_for_price_index(monkeypatch):
    module = load_v78_module()
    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"f43": 123456, "f46": 123000}}

    def fake_get(url, *args, **kwargs):
        calls.append(url)
        if "secid=2.930955" not in url:
            raise AssertionError("realtime should use the vendor alias before raw 1.930955")
        return Response()

    monkeypatch.setattr(module.requests, "get", fake_get)

    price = module._fetch_cn_realtime_close(module.CN_ZZHL_INDEX_SECID)

    assert price == 1234.56
    assert len(calls) == 1


def test_zzhl_price_index_prefers_vendor_kline_before_csindex(monkeypatch):
    module = load_v78_module()
    calls = []
    df = pd.DataFrame({"close": [100.0] * 60}, index=pd.date_range("2026-01-01", periods=60))

    def fake_eastmoney(secid):
        calls.append(("eastmoney", secid))
        return df

    def fail_csindex(index_code):
        raise AssertionError("csindex should not be the first source for 930955")

    monkeypatch.setattr(module, "_fetch_cn_eastmoney", fake_eastmoney)
    monkeypatch.setattr(module, "_fetch_cn_sina", lambda secid: (_ for _ in ()).throw(ValueError("no sina")))
    monkeypatch.setattr(module, "_load_cn_official_cache", lambda secid: (_ for _ in ()).throw(FileNotFoundError("no cache")))
    monkeypatch.setattr(module, "_fetch_cn_csindex", fail_csindex)

    result, source = module.fetch_cn_kline(module.CN_ZZHL_INDEX_SECID)

    assert result is df
    assert calls == [("eastmoney", "2.930955")]
    assert source == "EastMoney:2.930955"


def test_price_index_recent_official_cache_short_circuits_slow_vendors(monkeypatch):
    module = load_v78_module()
    cache = pd.DataFrame(
        {"close": [100.0] * 60},
        index=pd.date_range("2026-03-23", periods=60, freq="B"),
    )
    calls = []

    def fail_eastmoney(secid):
        calls.append(("eastmoney", secid))
        raise ValueError("vendor timeout")

    def fail_sina(secid):
        calls.append(("sina", secid))
        raise ValueError("sina timeout")

    def fail_csindex(index_code):
        calls.append(("csindex", index_code))
        raise AssertionError("csindex should not block when cache is available")

    monkeypatch.setattr(module, "_fetch_cn_eastmoney", fail_eastmoney)
    monkeypatch.setattr(module, "_fetch_cn_sina", fail_sina)
    monkeypatch.setattr(module, "_load_cn_official_cache", lambda secid: cache)
    monkeypatch.setattr(module, "_fetch_cn_csindex", fail_csindex)
    monkeypatch.setattr(module, "_latest_cn_required_close_date", lambda asof_date=None: cache.index[-1])

    result, source = module.fetch_cn_kline(module.CN_ZZHL_INDEX_SECID)

    assert result is cache
    assert source == f"csindex-cache:{cache.index[-1].strftime('%Y-%m-%d')}"
    assert calls == []


def test_short_cn_online_history_uses_local_strategy_csv_fallback(monkeypatch):
    module = load_v78_module()
    short = pd.DataFrame({"close": [100.0]}, index=pd.to_datetime(["2026-06-16"]))
    fallback = pd.DataFrame({"close": range(120)}, index=pd.date_range("2026-01-01", periods=120))
    chunks = []

    monkeypatch.setattr(module, "_load_cn_strategy_data_cache", lambda secid: fallback)

    result, source = module._ensure_cn_history_frame(
        module.CN_ZZHL_INDEX_SECID,
        short,
        "EastMoney:2.930955",
        min_rows=90,
        write=chunks.append,
    )

    assert result is fallback
    assert "local-cache:mnt_strategy_data_cn.csv" in source
    assert "历史兜底" in "".join(chunks)


def test_short_cn_online_history_error_names_bad_asset_when_no_fallback(monkeypatch):
    module = load_v78_module()
    short = pd.DataFrame({"close": [100.0]}, index=pd.to_datetime(["2026-06-16"]))

    def fail_cache(secid):
        raise FileNotFoundError("no local csv")

    monkeypatch.setattr(module, "_load_cn_strategy_data_cache", fail_cache)

    try:
        module._ensure_cn_history_frame(
            module.CN_ZZHL_INDEX_SECID,
            short,
            "EastMoney:2.930955",
            min_rows=90,
        )
    except module.poe.BotError as exc:
        text = str(exc)
    else:
        raise AssertionError("expected BotError")

    assert "中证红利低波100" in text
    assert "仅1行" in text
    assert "EastMoney:2.930955" in text
    assert "实时快照当历史K线" in text


def test_cn_dk_close_builder_ignores_live_snapshot_metadata_columns():
    module = load_v78_module()
    dates = pd.bdate_range("2025-01-02", periods=220)
    live_date = pd.Timestamp("2026-06-16")
    dk_dfs = {}

    for i, col in enumerate(module.CN_DK_COLS):
        frame = pd.DataFrame(
            {col: [100.0 + i + j * 0.1 for j in range(len(dates))]},
            index=dates,
        )
        live_row = pd.DataFrame(
            {
                col: [frame[col].iloc[-1] + 1.0],
                "is_live_bar": [True],
                "source": ["EastMoney realtime snapshot"],
            },
            index=pd.DatetimeIndex([live_date]),
        )
        frame = pd.concat([frame, live_row])
        frame["is_live_bar"] = frame["is_live_bar"].where(frame["is_live_bar"].notna(), False).astype(bool)
        dk_dfs[col] = frame

    cn_dk_close = module._build_cn_dk_close_frame(dk_dfs)

    assert list(cn_dk_close.columns) == module.CN_DK_COLS
    assert len(cn_dk_close) == len(dates) + 1
    assert cn_dk_close.index[-1] == live_date


def test_cn_dk_price_source_prefers_sina_before_eastmoney_and_csindex(monkeypatch):
    module = load_v78_module()
    sina = pd.DataFrame({"close": [100.0] * 60}, index=pd.date_range("2026-01-01", periods=60))
    csindex = pd.DataFrame({"close": [101.0] * 61}, index=pd.date_range("2026-01-01", periods=61))
    calls = []

    def fake_eastmoney(secid):
        calls.append(("eastmoney", secid))
        raise AssertionError("EastMoney should be fallback for DK price indices")

    def fake_sina(secid):
        calls.append(("sina", secid))
        return sina

    def fake_csindex(index_code):
        calls.append(("csindex", index_code))
        return csindex

    monkeypatch.setattr(module, "_fetch_cn_eastmoney", fake_eastmoney)
    monkeypatch.setattr(module, "_fetch_cn_sina", fake_sina)
    monkeypatch.setattr(module, "_fetch_cn_csindex", fake_csindex)

    result, source = module._fetch_cn_dk_price_index("000852", "1.000852")

    assert result is sina
    assert source == "Sina"
    assert calls == [("sina", "1.000852")]


def test_standard_cn_index_prefers_sina_before_eastmoney(monkeypatch):
    module = load_v78_module()
    sina = pd.DataFrame({"close": [100.0] * 60}, index=pd.date_range("2026-01-01", periods=60))
    calls = []

    def fake_sina(secid):
        calls.append(("sina", secid))
        return sina

    def fail_eastmoney(secid):
        calls.append(("eastmoney", secid))
        raise AssertionError("EastMoney should be fallback for standard CN indices")

    monkeypatch.setattr(module, "_fetch_cn_sina", fake_sina)
    monkeypatch.setattr(module, "_fetch_cn_eastmoney", fail_eastmoney)

    result, source = module.fetch_cn_kline("0.399006")

    assert result is sina
    assert source == "Sina"
    assert calls == [("sina", "0.399006")]


def test_suba_amount_zz2000_prefers_csindex_before_slow_eastmoney(monkeypatch):
    module = load_v78_module()
    amount = pd.DataFrame(
        {"close": [100.0] * 60, "amount": [1_000.0] * 60},
        index=pd.date_range("2026-01-01", periods=60),
    )
    calls = []

    def fake_csindex(secid, beg=module.CN_SA_VOLUME_HISTORY_BEG, lmt=10000):
        calls.append(("csindex", secid))
        return amount

    def fail_eastmoney(secid, beg=module.CN_SA_VOLUME_HISTORY_BEG, lmt=10000):
        calls.append(("eastmoney", secid))
        raise AssertionError("EastMoney amount should be fallback for ZZ2000")

    monkeypatch.setattr(module, "_fetch_cn_csindex_amount", fake_csindex)
    monkeypatch.setattr(module, "_fetch_cn_eastmoney_amount", fail_eastmoney)

    result, source = module._fetch_cn_amount_with_fallback(module.CN_SA_VOLUME_ZZ2000_SECID, "ZZ2000")

    assert result["source"].iloc[-1] == "CSIndex official amount"
    assert source == "CSIndex official amount"
    assert calls == [("csindex", module.CN_SA_VOLUME_ZZ2000_SECID)]


def test_suba_amount_cyb_prefers_qq_before_slow_eastmoney(monkeypatch):
    module = load_v78_module()
    amount = pd.DataFrame(
        {"close": [100.0] * 60, "amount": [1_000.0] * 60},
        index=pd.date_range("2026-01-01", periods=60),
    )
    calls = []

    def fake_qq(secid, datalen=10000):
        calls.append(("qq", secid))
        return amount

    def fail_eastmoney(secid, beg=module.CN_SA_VOLUME_HISTORY_BEG, lmt=10000):
        calls.append(("eastmoney", secid))
        raise AssertionError("EastMoney amount should be fallback for CYB")

    monkeypatch.setattr(module, "_fetch_cn_qq_amount_proxy", fake_qq)
    monkeypatch.setattr(module, "_fetch_cn_eastmoney_amount", fail_eastmoney)

    result, source = module._fetch_cn_amount_with_fallback(module.CN_SA_VOLUME_CYB_SECID, "CYB")

    assert result["source"].iloc[-1] == "QQ volume proxy"
    assert source == "QQ volume proxy"
    assert calls == [("qq", module.CN_SA_VOLUME_CYB_SECID)]


def test_h_index_fetch_uses_proxy_and_cached_base_before_csindex(monkeypatch):
    module = load_v78_module()
    base_dates = pd.bdate_range("2026-03-23", periods=61)
    proxy_dates = pd.bdate_range("2026-03-23", periods=62)
    base = pd.DataFrame(
        {"close": [100.0 + i * 0.1 for i in range(len(base_dates))]},
        index=base_dates,
    )
    proxy = pd.DataFrame(
        {"close": [200.0 + i * 0.2 for i in range(len(proxy_dates))]},
        index=proxy_dates,
    )
    calls = []

    def fail_csindex(index_code):
        calls.append(("csindex", index_code))
        raise AssertionError("official csindex should not block proxy/cache H-index path")

    monkeypatch.setattr(module, "_fetch_cn_h_proxy", lambda secid: (proxy, "Sina-proxy:1.000012"))
    monkeypatch.setattr(module, "_load_cn_official_cache", lambda secid: base)
    monkeypatch.setattr(module, "_fetch_cn_csindex_with_candidates", fail_csindex)
    monkeypatch.setattr(module, "_save_cn_official_cache", lambda secid, df: None)

    result, source = module.fetch_cn_kline(module.CN_BOND_CODE)

    assert calls == []
    assert source == f"csindex-cache:{base_dates[-1].strftime('%Y-%m-%d')}+Sina-proxy:1.000012"
    assert result.index[-1] == proxy_dates[-1]
    expected = float(base["close"].iloc[-1]) * float(proxy["close"].iloc[-1]) / float(proxy["close"].iloc[-2])
    assert round(float(result["close"].iloc[-1]), 10) == round(expected, 10)


def test_signal_handler_reports_compute_errors_instead_of_bubbling(monkeypatch, capfd):
    module = load_v78_module()
    bot = module.CombinedStrategyV78()

    monkeypatch.setattr(
        bot,
        "_cached_fetch_data",
        lambda msg, include_cn_live_snapshot=False, include_us_live_snapshot=False: (
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
        ),
    )

    def fail_compute(*_args, **_kwargs):
        raise RuntimeError("Sub-B display boom")

    monkeypatch.setattr(bot, "_compute_signal_data", fail_compute)

    bot._handle_signal()
    out = capfd.readouterr().out

    assert "信号计算/展示失败" in out
    assert "Sub-B display boom" in out


def test_live_signal_handler_prints_traceback_in_debug_mode(monkeypatch, capfd):
    module = load_v78_module()
    bot = module.CombinedStrategyV78()
    monkeypatch.setattr(module, "DEBUG_MODE", True)
    monkeypatch.setattr(
        bot,
        "_cached_fetch_data",
        lambda msg, include_cn_live_snapshot=False, include_us_live_snapshot=False: (
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
        ),
    )

    def fail_compute(*_args, **_kwargs):
        raise RuntimeError("Sub-B display boom")

    monkeypatch.setattr(bot, "_compute_signal_data", fail_compute)

    bot._handle_live_signal()
    out = capfd.readouterr().out

    assert "Traceback" in out
    assert "Sub-B display boom" in out


def test_us_live_supplement_updates_individual_stale_tickers_when_probe_is_not_newer(monkeypatch):
    module = load_v78_module()
    fresh = pd.DataFrame(
        {"close": [100.0, 101.0]},
        index=pd.to_datetime(["2026-06-12", "2026-06-15"]),
    )
    stale = pd.DataFrame(
        {"close": [200.0]},
        index=pd.to_datetime(["2026-06-12"]),
    )
    us_raw = {
        "SPY": fresh.copy(),
        "QQQ": fresh.copy(),
        "GLD": stale.copy(),
        "AGG": stale.copy(),
    }

    def fake_realtime(ticker):
        return {"SPY": (101.0, "2026-06-15", 100.5), "GLD": (205.0, "2026-06-15", 203.0), "AGG": (200.0, "2026-06-15", 199.0)}.get(
            ticker,
            (None, None, None),
        )

    monkeypatch.setattr(module, "_fetch_us_realtime_close", fake_realtime)

    module._supplement_us_today_close(us_raw, ["SPY", "QQQ", "GLD", "AGG"])

    assert us_raw["GLD"].index[-1] == pd.Timestamp("2026-06-15")
    assert float(us_raw["GLD"]["close"].iloc[-1]) == 205.0
    assert float(us_raw["GLD"]["open"].iloc[-1]) == 203.0
    assert bool(us_raw["GLD"]["is_live_bar"].iloc[-1]) is True
    assert us_raw["AGG"].index[-1] == pd.Timestamp("2026-06-15")
    assert float(us_raw["AGG"]["close"].iloc[-1]) == 200.0
    assert float(us_raw["AGG"]["open"].iloc[-1]) == 199.0


def test_us_realtime_close_reads_open_from_chart_quote(monkeypatch):
    module = load_v78_module()
    market_time = int(pd.Timestamp("2026-06-15 20:00:00", tz="UTC").timestamp())

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": 205.0,
                                "regularMarketTime": market_time,
                            },
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [203.0],
                                        "close": [205.0],
                                    }
                                ]
                            },
                        }
                    ]
                }
            }

    monkeypatch.setattr(module._session, "get", lambda *_args, **_kwargs: FakeResponse())

    price, trade_date, open_price = module._fetch_us_realtime_close("GLD")

    assert price == 205.0
    assert trade_date == "2026-06-15"
    assert open_price == 203.0

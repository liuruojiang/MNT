import importlib.util
import inspect
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATHS = {
    "v78": ROOT / "mnt_bot V 7.8 plus.py",
    "v79": ROOT / "mnt_bot V 7.9 plus.py",
}


class _Sink:
    def __init__(self):
        self.parts = []

    def write(self, value):
        self.parts.append(str(value))

    @property
    def text(self):
        return "".join(self.parts)


def _load_version(name, path):
    module_name = f"adversarial_repairs_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module_name, module


@pytest.fixture(scope="module")
def versions():
    loaded = {
        name: _load_version(name, path)
        for name, path in VERSION_PATHS.items()
    }
    try:
        yield {name: pair[1] for name, pair in loaded.items()}
    finally:
        for module_name, _module in loaded.values():
            sys.modules.pop(module_name, None)


def _subc_component_ledger(module, index, contribution=None):
    contribution = pd.Series(0.0, index=index) if contribution is None else contribution
    ledger = pd.DataFrame(index=index)
    ledger["asset_cost_return"] = 0.0
    ledger["asset_turnover"] = 0.0
    ledger["asset_cost_fraction"] = 0.0
    for name in module.PROD_PORTFOLIO:
        ledger[f"exposure::{name}"] = 1.0 if name == "VTI" else 0.0
        ledger[f"contribution::{name}"] = contribution if name == "VTI" else 0.0
    ledger["base_return"] = contribution
    return ledger


def _subc_open_dict(module, index, vti_open):
    result = {}
    default = pd.Series(100.0, index=index)
    for name, cfg in module.PROD_PORTFOLIO.items():
        result[name] = default.copy()
        result[cfg["proxy"]] = default.copy()
    result[module.PROD_CASH] = default.copy()
    result["VTI"] = pd.Series(vti_open, index=index, dtype=float)
    return result


def _call_subc_scaling(module, subc_ret, prices, components, us_open, **kwargs):
    call_kwargs = {
        "components": components,
        "us_open": us_open,
        **kwargs,
    }
    if "strict_open_execution" in inspect.signature(
        module._apply_subc_vol_scaling
    ).parameters:
        call_kwargs["strict_open_execution"] = True
    return module._apply_subc_vol_scaling(subc_ret, prices, **call_kwargs)


@pytest.mark.parametrize("move", [-0.20, -0.05, 0.05, 0.20])
@pytest.mark.parametrize("move_kind", ["gap_only", "intraday_only"])
def test_subc_scale_changes_execute_at_t_plus_one_open(
    versions, monkeypatch, move, move_kind
):
    """Old scale owns the gap; the new scale owns only the execution-day intraday leg."""
    index = pd.to_datetime(["2026-06-11", "2026-06-12"])
    previous_scale = 1.0
    new_scale = 1.5
    close_on_execution = 100.0 * (1.0 + move)
    open_on_execution = close_on_execution if move_kind == "gap_only" else 100.0
    expected = (previous_scale if move_kind == "gap_only" else new_scale) * move

    for module in versions.values():
        equity_scale = pd.Series([previous_scale, new_scale], index=index)
        monkeypatch.setattr(
            module,
            "_subc_absolute_scale",
            lambda *_args, _scale=equity_scale, **_kwargs: _scale.copy(),
        )
        monkeypatch.setattr(
            module,
            "_subc_relative_scale",
            lambda *_args, **_kwargs: pd.Series(1.0, index=index),
        )
        contribution = pd.Series([0.0, move], index=index)
        components = _subc_component_ledger(module, index, contribution)
        prices = pd.DataFrame(
            {
                "VTI": [100.0, close_on_execution],
                "SPY": [100.0, close_on_execution],
                "GLD": [100.0, 100.0],
                "BIL": [100.0, 100.0],
            },
            index=index,
        )
        us_open = _subc_open_dict(
            module, index, [100.0, open_on_execution]
        )

        scaled, actual_scale, costs = _call_subc_scaling(
            module,
            components["base_return"],
            prices,
            components,
            us_open,
            spread_bps=0.0,
            rebal_cost_bps=0.0,
        )

        assert actual_scale.loc[index[-1]] == pytest.approx(new_scale)
        assert costs.loc[index[-1]] == pytest.approx(0.0, abs=1e-14)
        assert scaled.loc[index[-1]] == pytest.approx(expected, abs=1e-12)


def test_subc_strict_execution_rejects_missing_active_open(versions, monkeypatch):
    index = pd.to_datetime(["2026-06-11", "2026-06-12"])
    for module in versions.values():
        scale = pd.Series([1.0, 1.5], index=index)
        monkeypatch.setattr(
            module,
            "_subc_absolute_scale",
            lambda *_args, _scale=scale, **_kwargs: _scale.copy(),
        )
        monkeypatch.setattr(
            module,
            "_subc_relative_scale",
            lambda *_args, **_kwargs: pd.Series(1.0, index=index),
        )
        components = _subc_component_ledger(
            module, index, pd.Series([0.0, 0.10], index=index)
        )
        prices = pd.DataFrame(
            {
                "VTI": [100.0, 110.0],
                "SPY": [100.0, 110.0],
                "GLD": [100.0, 100.0],
                "BIL": [100.0, 100.0],
            },
            index=index,
        )
        us_open = _subc_open_dict(module, index, [100.0, np.nan])

        with pytest.raises(ValueError, match=r"VTI|open|开盘"):
            _call_subc_scaling(
                module,
                components["base_return"],
                prices,
                components,
                us_open,
                spread_bps=0.0,
                rebal_cost_bps=0.0,
            )


def test_subc_rebalance_display_uses_execution_day_open(versions, monkeypatch):
    dates = pd.to_datetime(["2026-06-11", "2026-06-12", "2026-06-15"])
    for module in versions.values():
        equity_scale = pd.Series([1.0, 1.5, 1.5], index=dates)
        gold_scale = pd.Series(1.0, index=dates)
        monkeypatch.setattr(
            module,
            "_compute_subc_production_snapshot",
            lambda *_args, _eq=equity_scale, _gold=gold_scale, **_kwargs: {
                "equity_scale": _eq,
                "gold_scale": _gold,
            },
        )
        prices = pd.DataFrame(
            {
                cfg["proxy"]: 100.0
                for cfg in module.PROD_PORTFOLIO.values()
            },
            index=dates,
        )
        prices[module.PROD_CASH] = 100.0
        us_open = {
            name: pd.Series([100.0, 111.0, 222.0], index=dates)
            for name in module.PROD_PORTFOLIO
        }
        signals = pd.DataFrame(index=dates)

        records = module.extract_subc_vs_rebalances(
            prices, signals, signals, us_open=us_open
        )

        assert len(records) == 1
        assert records[0]["日期"] == "2026-06-12"
        price_text = f"{records[0].get('买入价格')} {records[0].get('卖出价格')}"
        assert "$111.00" in price_text
        assert "$222.00" not in price_text


@pytest.mark.parametrize(
    ("previous", "current"),
    [
        (100.0, np.nan),
        (np.nan, 100.0),
        (0.0, 100.0),
        (np.inf, 100.0),
        (100.0, np.inf),
    ],
)
def test_active_us_asset_invalid_price_fails_closed(versions, previous, current):
    for module in versions.values():
        with pytest.raises(ValueError, match="QQQ"):
            module._us_weighted_return(
                {"QQQ": 1.0},
                pd.Series({"QQQ": previous}),
                pd.Series({"QQQ": current}),
            )


def _finalize_subb_account_costs(module, result, close_df, us_open):
    rebuild = getattr(module, "_rebuild_subb_account_execution_costs", None)
    if rebuild is None:
        return result
    params = inspect.signature(rebuild).parameters
    kwargs = {}
    if "close_df" in params:
        kwargs["close_df"] = close_df
    if "us_open" in params:
        kwargs["us_open"] = us_open
    if "strict" in params:
        kwargs["strict"] = True
    if "strict_open_execution" in params:
        kwargs["strict_open_execution"] = True
    return rebuild(result, **kwargs)


def test_volreg_final_account_target_unchanged_means_no_trade_and_no_fee(
    versions, monkeypatch
):
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    for module in versions.values():
        states = iter([False, True])
        monkeypatch.setattr(
            module,
            "_volreg_next_cash_state",
            lambda _state, _ratio, _states=states: next(_states),
        )
        result = pd.DataFrame(
            {
                "return": [0.0, 0.0],
                "return_before_subb_execution_cost": [0.0, 0.0],
                "actual_w_QQQ": [0.0, 0.5],
                "actual_w_BIL": [1.0, 0.5],
                "w_QQQ": [0.0, 0.5],
                "w_BIL": [1.0, 0.5],
                "target_w_QQQ": [0.0, 0.5],
                "target_w_BIL": [1.0, 0.5],
                "rebalanced": [False, True],
            },
            index=dates,
        )
        close_df = pd.DataFrame(
            {"QQQ": [100.0, 100.0], "BIL": [100.0, 100.0]}, index=dates
        )
        us_open = {
            "QQQ": pd.Series(100.0, index=dates),
            "BIL": pd.Series(100.0, index=dates),
        }
        spy = pd.Series(100.0, index=dates)

        overlaid = module.apply_vol_regime_overlay(
            result,
            spy,
            close_df=close_df,
            us_open=us_open,
            strict_open_execution=True,
        )
        finalized = _finalize_subb_account_costs(
            module, overlaid, close_df, us_open
        )

        assert finalized.loc[dates[-1], "effective_w_QQQ"] == pytest.approx(0.0)
        assert finalized.loc[dates[-1], "effective_w_BIL"] == pytest.approx(1.0)
        assert finalized.loc[dates[-1], "subb_effective_turnover"] == pytest.approx(0.0)
        assert finalized.loc[dates[-1], "subb_effective_cost"] == pytest.approx(0.0)
        assert finalized.loc[dates[-1], "return"] == pytest.approx(0.0)


def _market_frame(end, periods=500, start_value=100.0):
    index = pd.bdate_range(end=pd.Timestamp(end), periods=periods)
    values = start_value * np.exp(np.linspace(0.0, 0.05, periods))
    return pd.DataFrame({"open": values, "close": values}, index=index)


def _patch_fetch_data_sources(
    monkeypatch,
    module,
    *,
    us_end="2026-08-11",
    us_end_by_ticker=None,
    dk_end="2026-08-12",
):
    us_end_by_ticker = dict(us_end_by_ticker or {})
    now = datetime(2026, 8, 12, 16, 30)
    cn_frame = _market_frame("2026-08-12")
    monkeypatch.setattr(module, "beijing_now", lambda: now)
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "fetch_cn_kline",
        lambda _secid: (cn_frame.copy(), "fixture-cn"),
    )
    monkeypatch.setattr(
        module,
        "_ensure_cn_history_frame",
        lambda _secid, frame, source, **_kwargs: (frame, source),
    )
    monkeypatch.setattr(
        module, "_supplement_today_close", lambda frame, *_args, **_kwargs: frame
    )
    monkeypatch.setattr(module, "is_cn_market_open", lambda: (False, now))
    monkeypatch.setattr(
        module,
        "_add_cn_bond_column",
        lambda frame, *_args, **_kwargs: frame,
    )
    monkeypatch.setattr(
        module,
        "_supplement_us_today_close",
        lambda *_args, **_kwargs: None,
    )

    def fetch_yahoo(ticker):
        end = us_end_by_ticker.get(ticker, us_end)
        return _market_frame(end), f"fixture-us:{ticker}"

    monkeypatch.setattr(module, "fetch_yahoo", fetch_yahoo)
    monkeypatch.setattr(
        module,
        "_fetch_cn_dk_price_index",
        lambda _idx, _secid: (_market_frame(dk_end), "fixture-dk"),
    )


def test_us_freshness_is_anchored_to_latest_completed_market_session(
    versions, monkeypatch
):
    for module in versions.values():
        _patch_fetch_data_sources(
            monkeypatch, module, us_end="2025-01-02", dk_end="2026-08-12"
        )
        bot = module.CombinedStrategyV78()
        with pytest.raises(module.poe.BotError, match=r"过期|stale|Sub-B|US"):
            bot._fetch_data(
                _Sink(),
                include_cn_live_snapshot=True,
                include_us_live_snapshot=True,
            )


def test_subc_raw_staleness_cannot_be_hidden_by_reindex_ffill(
    versions, monkeypatch
):
    for module in versions.values():
        _patch_fetch_data_sources(
            monkeypatch,
            module,
            us_end="2026-08-11",
            us_end_by_ticker={"VTI": "2026-08-03"},
            dk_end="2026-08-12",
        )
        bot = module.CombinedStrategyV78()
        with pytest.raises(module.poe.BotError, match=r"VTI|Sub-C|过期|stale"):
            bot._fetch_data(
                _Sink(),
                include_cn_live_snapshot=True,
                include_us_live_snapshot=True,
            )


def test_realtime_dk_stale_data_fails_closed(versions, monkeypatch):
    for module in versions.values():
        _patch_fetch_data_sources(
            monkeypatch,
            module,
            us_end="2026-08-11",
            dk_end="2026-08-03",
        )
        bot = module.CombinedStrategyV78()
        with pytest.raises(module.poe.BotError, match=r"A-DK|DK|过期|stale"):
            bot._fetch_data(
                _Sink(),
                include_cn_live_snapshot=True,
                include_us_live_snapshot=True,
            )


def test_subc_share_count_never_falls_back_to_proxy_price(
    versions, monkeypatch
):
    date = pd.Timestamp("2026-06-12")
    for module in versions.values():
        monkeypatch.setattr(
            module, "_scan_capital_config", lambda _chat: {"Sub-C": 10_000.0}
        )
        monkeypatch.setattr(module, "_scan_position_config", lambda _chat: {})
        columns = {
            cfg["proxy"]: [25.0]
            for cfg in module.PROD_PORTFOLIO.values()
        }
        for name in module.PROD_PORTFOLIO:
            if name != "QQQM":
                columns[name] = [50.0]
        columns[module.PROD_CASH] = [100.0]
        prices = pd.DataFrame(columns, index=[date])
        d = {
            "current_am_raw": pd.DataFrame(index=[date]),
            "current_sma_raw": pd.DataFrame(index=[date]),
            "last_sig_month": date,
            "subc_vs_info": {
                "current_scale": 1.0,
                "next_scale": 1.0,
                "gold_current_scale": 1.0,
                "gold_next_scale": 1.0,
                "next_gross_exposure": 1.0,
                "next_cash_exposure": 0.0,
                "next_borrow_exposure": 0.0,
                "pending_adjustment": False,
                "gold_pending_adjustment": False,
            },
        }
        sink = _Sink()

        try:
            module.CombinedStrategyV78()._write_sub_c(sink, d, prices)
        except (module.poe.BotError, ValueError) as exc:
            assert "QQQM" in str(exc)
        else:
            qqqm_rows = [line for line in sink.text.splitlines() if "| QQQM |" in line]
            assert len(qqqm_rows) == 1
            # Proxy QQQ is $25, which would fabricate exactly 40 shares here.
            assert "| 40 |" not in qqqm_rows[0]
            assert "价格" in qqqm_rows[0] or "—" in qqqm_rows[0]


@pytest.mark.parametrize(
    ("proxy", "live"),
    [("QQQ", "QQQM"), ("GLD", "GLDM"), ("DBC", "PDBC")],
)
def test_subb_open_execution_uses_live_etf_gap_mapped_to_proxy(
    versions, proxy, live
):
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    for module in versions.values():
        raw = {
            proxy: pd.DataFrame(
                {"open": [100.0, 100.0], "close": [100.0, 110.0]},
                index=dates,
            ),
            live: pd.DataFrame(
                {"open": [50.0, 55.0], "close": [50.0, 55.0]},
                index=dates,
            ),
        }

        execution_open = module._build_us_open_execution_dict(raw)

        assert proxy in execution_open
        mapped_gap = execution_open[proxy].loc[dates[-1]] / 100.0 - 1.0
        live_gap = raw[live].loc[dates[-1], "open"] / raw[live].loc[dates[0], "close"] - 1.0
        assert mapped_gap == pytest.approx(live_gap)


def test_proxy_live_close_splice_preserves_prelisting_proxy_history(versions):
    dates = pd.to_datetime(["2014-11-05", "2014-11-06", "2014-11-07", "2014-11-10"])
    proxy = pd.Series([20.0, 21.0, 22.0, 23.0], index=dates)
    live = pd.Series([np.nan, np.nan, 10.0, 11.0], index=dates)

    for module in versions.values():
        spliced = module._build_proxy_live_spliced_series(
            proxy,
            live,
            name="DBC",
        )

        pd.testing.assert_series_equal(
            spliced.loc[: "2014-11-06"],
            proxy.rename("DBC").loc[: "2014-11-06"],
        )
        assert spliced.loc["2014-11-07"] == pytest.approx(22.0)
        assert spliced.loc["2014-11-10"] == pytest.approx(24.2)


def test_pdbc_is_a_required_live_subb_price_series(versions):
    for module in versions.values():
        assert "DBC" in module.SUBB_REQUIRED_PRICE_TICKERS
        assert "PDBC" in module.SUBB_REQUIRED_LIVE_PRICE_TICKERS


def test_v79_proxy_live_splice_rejects_a_post_listing_live_gap(versions):
    module = versions["v79"]
    dates = pd.to_datetime(["2026-08-10", "2026-08-11", "2026-08-12"])
    proxy = pd.Series([100.0, 101.0, 102.0], index=dates, name="DBC")
    live = pd.Series([50.0, np.nan, 51.0], index=dates, name="PDBC")

    with pytest.raises(ValueError, match=r"DBC/PDBC.*2026-08-11"):
        module._build_proxy_live_spliced_series(
            proxy,
            live,
            name="DBC",
            live_name="PDBC",
        )


def test_proxy_live_splice_preserves_complete_live_returns(versions):
    dates = pd.to_datetime(["2026-08-10", "2026-08-11", "2026-08-12"])
    proxy = pd.Series([100.0, 101.0, 102.0], index=dates, name="DBC")
    live = pd.Series([50.0, 50.5, 51.0], index=dates, name="PDBC")

    for module in versions.values():
        kwargs = {"name": "DBC"}
        if "live_name" in inspect.signature(
            module._build_proxy_live_spliced_series
        ).parameters:
            kwargs["live_name"] = "PDBC"
        result = module._build_proxy_live_spliced_series(proxy, live, **kwargs)
        pd.testing.assert_series_equal(result, proxy)


def test_us_execution_schedule_ignores_crypto_only_holiday_rows(versions):
    schedule = {
        "SPY": pd.Series([100.0, 101.0], index=pd.to_datetime(["2026-11-25", "2026-11-27"])),
        "BTC-USD": pd.Series([1.0, 1.0, 1.0], index=pd.to_datetime(["2026-11-25", "2026-11-26", "2026-11-27"])),
    }

    for module in versions.values():
        assert module._next_session_day(pd.Timestamp("2026-11-25"), schedule) == pd.Timestamp("2026-11-27")
        assert not module._has_execution_happened(
            pd.Timestamp("2026-11-25"),
            "US",
            pd.Timestamp("2026-11-26 23:00"),
            schedule,
        )


@pytest.mark.parametrize("bad_price", [0.0, -1.0, np.inf, -np.inf])
def test_live_etf_price_rejects_nonpositive_or_nonfinite_values(versions, bad_price):
    date = pd.Timestamp("2026-06-12")
    prices = pd.DataFrame({"QQQM": [bad_price]}, index=[date])

    for module in versions.values():
        assert module._latest_live_etf_price(
            prices,
            "QQQ",
            "QQQM",
            expected_date=date,
        ) is None


def test_subb_financing_gross_exposure_includes_invested_bil(versions):
    for module in versions.values():
        weights = {"QQQ": 0.75, "BIL": 0.50, "CASH": 0.25}
        assert module._subb_account_gross_exposure(weights) == pytest.approx(1.25)


def test_fetch_data_splices_subc_proxy_close_to_live_etf(versions, monkeypatch):
    for module in versions.values():
        _patch_fetch_data_sources(monkeypatch, module)

        def fetch_yahoo(ticker):
            frame = _market_frame("2026-08-11", start_value=50.0 if ticker == "QQQM" else 100.0)
            if ticker == "QQQM":
                frame.loc[frame.index[-1], ["open", "close"]] *= 1.20
            return frame, f"fixture-us:{ticker}"

        monkeypatch.setattr(module, "fetch_yahoo", fetch_yahoo)
        _cn, _dk, _rot, prod = module.CombinedStrategyV78()._fetch_data(
            _Sink(),
            include_cn_live_snapshot=True,
            include_us_live_snapshot=True,
        )

        # The first overlap normalizes QQQM to QQQ.  Its distinct final-day
        # +20% move must therefore appear in the configured QQQ proxy column.
        qqq_raw = _market_frame("2026-08-11")["close"]
        assert prod["QQQ"].iloc[-1] == pytest.approx(qqq_raw.iloc[-1] * 1.20)


def test_fetch_data_does_not_ffill_missing_live_etf_snapshot(versions, monkeypatch):
    for module in versions.values():
        _patch_fetch_data_sources(monkeypatch, module)

        def supplement_today(raw, _tickers, _msg=None):
            today = pd.Timestamp("2026-08-12")
            for ticker, frame in raw.items():
                if ticker == "QQQM":
                    continue
                last = frame.iloc[-1].copy()
                frame.loc[today] = last

        monkeypatch.setattr(module, "_supplement_us_today_close", supplement_today)
        _cn, _dk, _rot, prod = module.CombinedStrategyV78()._fetch_data(
            _Sink(),
            include_cn_live_snapshot=True,
            include_us_live_snapshot=True,
        )

        assert prod.index[-1] == pd.Timestamp("2026-08-12")
        assert pd.isna(prod.loc[pd.Timestamp("2026-08-12"), "QQQM"])


def test_fetch_data_retries_transient_yahoo_internal_gap(versions, monkeypatch):
    for module in versions.values():
        _patch_fetch_data_sources(monkeypatch, module)
        calls = {"EMXC": 0}
        missing_date = pd.Timestamp("2026-07-22")

        def fetch_yahoo(ticker, start_date=None):
            frame = _market_frame("2026-08-11", periods=500)
            if ticker == "EMXC":
                calls["EMXC"] += 1
                if calls["EMXC"] == 1:
                    frame = frame.drop(index=missing_date)
            return frame, "Yahoo"

        monkeypatch.setattr(module, "fetch_yahoo", fetch_yahoo)
        _cn, _dk, rot, _prod = module.CombinedStrategyV78()._fetch_data(
            _Sink(),
            include_cn_live_snapshot=True,
            include_us_live_snapshot=True,
        )

        assert calls["EMXC"] == 2
        assert pd.notna(rot.loc[missing_date, "EMXC"])


def test_fetch_data_uses_ibit_after_listing_when_btc_proxy_has_gap(
    versions, monkeypatch
):
    """A retired BTC proxy hole must not block current IBIT-backed production."""
    missing_date = pd.Timestamp("2026-07-22")
    for module in versions.values():
        _patch_fetch_data_sources(monkeypatch, module)

        def fetch_yahoo(ticker, start_date=None):
            frame = _market_frame("2026-08-11", periods=500)
            if ticker == "BTC-USD":
                frame = frame.drop(index=missing_date)
            return frame, f"fixture-us:{ticker}"

        monkeypatch.setattr(module, "fetch_yahoo", fetch_yahoo)
        _cn, _dk, rot, prod = module.CombinedStrategyV78()._fetch_data(
            _Sink(),
            include_cn_live_snapshot=True,
            include_us_live_snapshot=True,
        )

        assert pd.notna(rot.loc[missing_date, "BTC-USD"])
        assert pd.notna(prod.loc[missing_date, "BTC-USD"])


def test_fetch_data_still_fails_when_post_listing_ibit_has_gap(
    versions, monkeypatch
):
    missing_date = pd.Timestamp("2026-07-22")
    for module in versions.values():
        _patch_fetch_data_sources(monkeypatch, module)

        def fetch_yahoo(ticker, start_date=None):
            frame = _market_frame("2026-08-11", periods=500)
            if ticker == "IBIT":
                frame = frame.drop(index=missing_date)
            return frame, f"fixture-us:{ticker}"

        monkeypatch.setattr(module, "fetch_yahoo", fetch_yahoo)
        with pytest.raises(
            module.poe.BotError,
            match=r"IBIT|BTC/IBIT|2026-07-22|OHLC gap",
        ):
            module.CombinedStrategyV78()._fetch_data(
                _Sink(),
                include_cn_live_snapshot=True,
                include_us_live_snapshot=True,
            )


def test_yahoo_gap_retry_never_fills_persistent_missing_prices(versions, monkeypatch):
    missing_date = pd.Timestamp("2026-07-22")
    for module in versions.values():
        complete = _market_frame("2026-08-11", periods=500)
        incomplete = complete.drop(index=missing_date)
        raw = {"SPY": complete.copy(), "EMXC": incomplete.copy()}
        sources = {"SPY": "Yahoo", "EMXC": "Yahoo"}
        calls = {"count": 0}

        def still_incomplete(_ticker, start_date=None):
            calls["count"] += 1
            return incomplete.copy(), "Yahoo"

        monkeypatch.setattr(module, "fetch_yahoo", still_incomplete)
        module._retry_incomplete_us_price_history(
            raw,
            sources,
            ["EMXC"],
            max_attempts=2,
        )

        assert calls["count"] == 2
        assert missing_date not in raw["EMXC"].index


def test_yahoo_gap_retry_merges_same_ticker_rows_without_losing_old_rows(versions, monkeypatch):
    for module in versions.values():
        complete = _market_frame("2026-08-11", periods=500)
        dates = complete.index[-6:-2]
        original = complete.drop(index=[dates[2], dates[3]])
        retry = complete.drop(index=[dates[1]])
        raw = {"SPY": complete.copy(), "EMXC": original.copy()}
        sources = {"SPY": "Yahoo", "EMXC": "Yahoo"}

        monkeypatch.setattr(
            module,
            "fetch_yahoo",
            lambda _ticker: (retry.copy(), "Yahoo"),
        )
        module._retry_incomplete_us_price_history(
            raw,
            sources,
            ["EMXC"],
            max_attempts=1,
        )

        assert dates[1] in raw["EMXC"].index
        assert dates[2] in raw["EMXC"].index
        assert dates[3] in raw["EMXC"].index
        module._assert_us_internal_price_history(raw, ["SPY", "EMXC"], label="fixture")


def test_fetch_yahoo_repairs_same_ticker_gap_from_nasdaq(versions, monkeypatch):
    dates = pd.bdate_range("2026-05-20", periods=60)
    missing_date = dates[-2]
    values = pd.Series(np.linspace(100.0, 102.0, len(dates)), index=dates)
    yahoo = pd.DataFrame({"open": values, "close": values}).drop(index=missing_date)
    nasdaq = pd.DataFrame(
        {
            "open": values.loc[dates[-3:]] / 2.0,
            "close": values.loc[dates[-3:]] / 2.0,
        },
        index=dates[-3:],
    )
    for module in versions.values():
        monkeypatch.setattr(module, "_fetch_us_yahoo", lambda *_a, **_k: yahoo.copy())
        monkeypatch.setattr(
            module, "_fetch_us_nasdaq_history", lambda *_a, **_k: nasdaq.copy()
        )
        repaired, source = module.fetch_yahoo("AVDV")

        assert source == "Yahoo+Nasdaq-gap"
        assert repaired.loc[missing_date, "open"] == pytest.approx(values.loc[missing_date])
        assert repaired.loc[missing_date, "close"] == pytest.approx(values.loc[missing_date])


def test_nasdaq_gap_repair_rejects_a_mismatched_price_scale(versions):
    dates = pd.to_datetime(["2026-08-10", "2026-08-11", "2026-08-12"])
    primary = pd.DataFrame(
        {"open": [10.0, 10.2], "close": [10.0, 10.2]},
        index=dates[[0, 2]],
    )
    fallback = pd.DataFrame(
        {"open": [10.0, 10.1, 20.4], "close": [10.0, 10.1, 20.4]},
        index=dates,
    )

    for module in versions.values():
        with pytest.raises(ValueError, match="scale mismatch"):
            module._merge_same_ticker_gap_prices(
                primary,
                fallback,
                [dates[1]],
                "PDBC",
            )


def test_btc_ibit_formal_frame_uses_ibit_after_listing(versions):
    dates = pd.to_datetime(["2024-01-10", "2024-01-11", "2024-01-12"])
    btc = pd.DataFrame(
        {"open": [100.0, 101.0], "close": [100.0, 101.0]},
        index=dates[[0, 2]],
    )
    ibit = pd.DataFrame(
        {"open": [50.0, 51.0], "close": [50.0, 51.0]},
        index=dates[[1, 2]],
    )

    for module in versions.values():
        formal = module._build_btc_ibit_formal_ohlc(
            {"BTC-USD": btc, "IBIT": ibit}
        )
        assert formal.loc[dates[0], "close"] == pytest.approx(100.0)
        assert formal.loc[dates[1], "close"] == pytest.approx(50.0)
        assert formal.loc[dates[2], "close"] == pytest.approx(51.0)


def test_btc_ibit_formal_frame_keeps_prelisting_btc_gap_visible(versions):
    dates = pd.to_datetime(
        ["2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"]
    )
    btc = pd.DataFrame(
        {"open": [100.0, 102.0], "close": [100.0, 102.0]},
        index=dates[[0, 2]],
    )
    ibit = pd.DataFrame(
        {"open": [50.0], "close": [50.0]},
        index=dates[[3]],
    )
    reference = pd.DataFrame(
        {"open": [1.0] * len(dates), "close": [1.0] * len(dates)},
        index=dates,
    )

    for module in versions.values():
        formal = module._build_btc_ibit_formal_ohlc(
            {"BTC-USD": btc, "IBIT": ibit}
        )
        with pytest.raises(module.poe.BotError, match="2024-01-09"):
            module._assert_us_internal_price_history(
                {"SPY": reference, "BTC/IBIT": formal},
                ["SPY", "BTC/IBIT"],
                label="fixture",
            )


def test_yahoo_gap_retry_uses_shorter_window_on_second_attempt(versions, monkeypatch):
    for module in versions.values():
        complete = _market_frame("2026-08-11", periods=500)
        dates = complete.index[-6:-2]
        original = complete.drop(index=[dates[2], dates[3]])
        first_retry = complete.drop(index=[dates[3]])
        second_retry = complete.loc[dates[0]:].copy()
        raw = {"SPY": complete.copy(), "EMXC": original.copy()}
        sources = {"SPY": "Yahoo", "EMXC": "Yahoo"}
        starts = []

        def fetch_yahoo(_ticker, start_date=None):
            starts.append(start_date)
            return (first_retry if len(starts) == 1 else second_retry).copy(), "Yahoo"

        monkeypatch.setattr(module, "fetch_yahoo", fetch_yahoo)
        module._retry_incomplete_us_price_history(
            raw,
            sources,
            ["EMXC"],
            max_attempts=2,
        )

        assert starts[0] is None
        assert pd.Timestamp(starts[1]) < dates[3]
        assert dates[2] in raw["EMXC"].index
        assert dates[3] in raw["EMXC"].index


def test_yahoo_gap_retry_has_global_request_budget(versions, monkeypatch):
    for module in versions.values():
        complete = _market_frame("2026-08-11", periods=500)
        missing_date = complete.index[-2]
        incomplete = complete.drop(index=missing_date)
        tickers = ["EMXC", "QQQM", "GLDM", "PDBC"]
        raw = {"SPY": complete.copy()}
        raw.update({ticker: incomplete.copy() for ticker in tickers})
        sources = {ticker: "Yahoo" for ticker in raw}
        calls = {"count": 0}

        def still_incomplete(_ticker, start_date=None):
            calls["count"] += 1
            return incomplete.copy(), "Yahoo"

        monkeypatch.setattr(module, "fetch_yahoo", still_incomplete)
        module._retry_incomplete_us_price_history(
            raw,
            sources,
            tickers,
            max_attempts=2,
            max_total_attempts=3,
        )

        assert calls["count"] == 3


@pytest.mark.parametrize("ticker", ["SPY", "TLT", "BIL"])
def test_fetch_data_never_hides_persistent_formal_us_gap(
    versions, monkeypatch, ticker
):
    missing_date = pd.Timestamp("2026-07-22")
    for module in versions.values():
        _patch_fetch_data_sources(monkeypatch, module)
        calls = {"target": 0}

        def fetch_yahoo(current, start_date=None):
            frame = _market_frame("2026-08-11", periods=500)
            if current == ticker:
                calls["target"] += 1
                frame = frame.drop(index=missing_date)
            return frame, "Yahoo"

        monkeypatch.setattr(module, "fetch_yahoo", fetch_yahoo)
        with pytest.raises(
            module.poe.BotError,
            match=rf"{ticker}.*2026-07-22|2026-07-22.*{ticker}|OHLC gap",
        ):
            module.CombinedStrategyV78()._fetch_data(
                _Sink(),
                include_cn_live_snapshot=True,
                include_us_live_snapshot=True,
            )

        assert calls["target"] == 3


def test_shared_us_sessions_do_not_treat_marketwide_closure_as_gap(versions):
    closure = pd.Timestamp("2025-01-09")
    complete = _market_frame("2026-08-11", periods=500)
    closed = complete.drop(index=closure)
    for module in versions.values():
        raw = {
            "SPY": closed.copy(),
            "TLT": closed.copy(),
            "BIL": closed.copy(),
        }
        module._assert_us_internal_price_history(
            raw,
            ["SPY", "TLT", "BIL"],
            label="fixture",
        )


def test_fetch_data_detects_marketwide_common_mode_session_gap(versions, monkeypatch):
    missing_date = pd.Timestamp("2026-07-22")
    for module in versions.values():
        _patch_fetch_data_sources(monkeypatch, module)

        def fetch_yahoo(_ticker):
            return _market_frame("2026-08-11", periods=500).drop(index=missing_date), "Yahoo"

        monkeypatch.setattr(module, "fetch_yahoo", fetch_yahoo)
        with pytest.raises(
            module.poe.BotError,
            match=r"2026-07-22|OHLC gap",
        ):
            module.CombinedStrategyV78()._fetch_data(
                _Sink(),
                include_cn_live_snapshot=True,
                include_us_live_snapshot=True,
            )


@pytest.mark.parametrize(
    "closure",
    [
        "2004-06-11",
        "2007-01-02",
        "2012-10-29",
        "2012-10-30",
        "2018-12-05",
        "2025-01-09",
    ],
)
def test_us_ad_hoc_market_closures_are_not_sessions(versions, closure):
    for module in versions.values():
        sessions = module._expected_us_ohlc_index(closure, closure)
        assert len(sessions) == 0


@pytest.mark.parametrize(
    "closure",
    [
        "2022-06-20",
        "2023-06-19",
        "2024-06-19",
    ],
)
def test_us_juneteenth_closures_are_not_internal_ohlc_gaps(versions, closure):
    for module in versions.values():
        sessions = module._expected_us_ohlc_index(closure, closure)
        assert len(sessions) == 0


def test_v78_stale_optional_calendar_cannot_restore_juneteenth(versions, monkeypatch):
    module = versions["v78"]
    index = pd.date_range("2022-06-17", "2022-06-21", freq="B")
    stale_schedule = pd.DataFrame(
        {
            "open": pd.to_datetime(index.strftime("%Y-%m-%d") + " 13:30", utc=True),
            "close": pd.to_datetime(index.strftime("%Y-%m-%d") + " 20:00", utc=True),
        },
        index=index,
    )

    class _StaleCalendar:
        schedule = stale_schedule

    stale_package = type(
        "StaleExchangeCalendars",
        (),
        {"get_calendar": staticmethod(lambda _name: _StaleCalendar())},
    )()
    monkeypatch.setitem(sys.modules, "exchange_calendars", stale_package)

    sessions = module._xnys_schedule("2022-06-17", "2022-06-21")
    assert pd.Timestamp("2022-06-20") not in sessions.index
    assert list(sessions.index) == [
        pd.Timestamp("2022-06-17"),
        pd.Timestamp("2022-06-21"),
    ]


@pytest.mark.parametrize(
    ("signal_date", "expected"),
    [
        ("2025-07-03", "2025-07-07"),
        ("2025-12-24", "2025-12-26"),
    ],
)
def test_us_next_session_skips_exchange_holidays(versions, signal_date, expected):
    for module in versions.values():
        assert module._next_session_day(pd.Timestamp(signal_date)) == pd.Timestamp(expected)


@pytest.mark.parametrize(
    ("session", "expected_text"),
    [
        ("2025-07-03", "2025-07-04 01:00"),
        ("2025-11-28", "2025-11-29 02:00"),
    ],
)
def test_us_early_close_display_uses_one_pm_eastern(
    versions, session, expected_text
):
    for module in versions.values():
        assert expected_text in module.beijing_time_str(
            pd.Timestamp(session), "US", "close"
        )


def test_latest_required_us_close_skips_independence_day(versions):
    for module in versions.values():
        resolver = getattr(
            module, "_latest_us_required_close_date", module._latest_required_close_date
        )
        assert resolver(pd.Timestamp("2025-07-05")) == pd.Timestamp("2025-07-03")


def test_first_trade_is_preserved_in_nav_and_drawdown(versions):
    dates = pd.to_datetime(["2026-01-05", "2026-01-06"])
    for module in versions.values():
        nav = module._nav_from_period_returns(
            pd.Series([0.10, 0.0], index=dates)
        )
        assert nav.tolist() == pytest.approx([1.10, 1.10])

        assert module._max_drawdown_pct_from_nav(
            pd.Series([0.90, 0.99], index=dates)
        ) == pytest.approx(-10.0)

        daily = {
            name: pd.Series([0.10, 0.0], index=dates)
            for name in module.PERFORMANCE_COMBO_ORDER
        }
        combined = module._performance_combined_daily_returns(daily)
        assert combined.iloc[0] == pytest.approx(0.10)
        assert (1.0 + combined).prod() == pytest.approx(1.10)


@pytest.mark.parametrize("engine", ["mix", "legacy", "bias"])
def test_subb_engines_reject_short_input_with_clear_value_error(versions, engine):
    dates = pd.bdate_range("2026-01-05", periods=10)
    for module in versions.values():
        columns = sorted(
            set(module.US_ROT_POOL)
            | {"BIL", "SPY", "DBC", "TLT", "UUP"}
        )
        close = pd.DataFrame(100.0, index=dates, columns=columns)
        calls = {
            "mix": lambda: module.run_us_rotation_mix(
                close, module.US_ROT_BASE_POOL
            ),
            "legacy": lambda: module.run_us_rotation(
                close, module.US_ROT_BASE_POOL
            ),
            "bias": lambda: module.run_v78_subb_new_line(close, line="bias"),
        }
        with pytest.raises(
            ValueError, match=r"history|rows|short|insufficient|数据不足"
        ):
            calls[engine]()


def _financing_component_ledger(module, index):
    ledger = pd.DataFrame(index=index)
    ledger["asset_cost_return"] = 0.0
    ledger["asset_turnover"] = 0.0
    ledger["asset_cost_fraction"] = 0.0
    for name, cfg in module.PROD_PORTFOLIO.items():
        ledger[f"exposure::{name}"] = float(cfg["w"])
        ledger[f"contribution::{name}"] = 0.0
    ledger["base_return"] = 0.0
    return ledger


def test_subc_financing_cost_conserves_borrow_exposure_with_seeded_cases(
    versions, monkeypatch
):
    rng = np.random.default_rng(20260812)
    index = pd.bdate_range("2026-01-05", periods=6)
    for module in versions.values():
        for _ in range(6):
            equity_scale_value = float(rng.uniform(1.05, 1.50))
            spread_bps = float(rng.uniform(25.0, 175.0))
            cash_return = float(rng.uniform(0.0, 0.0002))
            equity_scale = pd.Series(equity_scale_value, index=index)
            monkeypatch.setattr(
                module,
                "_subc_absolute_scale",
                lambda *_args, _scale=equity_scale, **_kwargs: _scale.copy(),
            )
            monkeypatch.setattr(
                module,
                "_subc_relative_scale",
                lambda *_args, **_kwargs: pd.Series(1.0, index=index),
            )
            bil = 100.0 * np.cumprod(np.full(len(index), 1.0 + cash_return))
            prices = pd.DataFrame(
                {
                    "SPY": 100.0,
                    "GLD": 100.0,
                    "BIL": bil,
                    "VTI": 100.0,
                },
                index=index,
            )
            components = _financing_component_ledger(module, index)
            opens = _subc_open_dict(module, index, np.full(len(index), 100.0))

            scaled, _, costs = _call_subc_scaling(
                module,
                components["base_return"],
                prices,
                components,
                opens,
                spread_bps=spread_bps,
                rebal_cost_bps=0.0,
            )

            equity_exposure = sum(
                cfg["w"]
                for cfg in module.PROD_PORTFOLIO.values()
                if cfg["cls"] in module.PROD_VS_SCALE_CLASSES
            )
            borrow = (equity_scale_value - 1.0) * equity_exposure
            bil_ret = prices["BIL"].pct_change(fill_method=None).fillna(0.0)
            expected = -borrow * (
                bil_ret + spread_bps / 10_000.0 / module.US_TRADING_DAYS
            )
            pd.testing.assert_series_equal(
                scaled, expected, check_names=False, atol=2e-14, rtol=0.0
            )
            assert np.allclose(costs.to_numpy(), 0.0, atol=1e-14, rtol=0.0)


def test_v79_deployment_identity_is_consistent(versions):
    module = versions["v79"]
    first_line = VERSION_PATHS["v79"].read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "# poe: name=Strategy-Signal-V79"
    assert module.__doc__ == "V7.9"
    assert module.V78_LABEL == "V7.9"


def test_v79_uup_is_optional_observation_not_required_trade_data(versions):
    module = versions["v79"]
    assert "UUP" not in module.US_ROT_POOL
    assert "UUP" not in module.SUBB_REQUIRED_PRICE_TICKERS
    assert "UUP" in module.SUBB_OPTIONAL_MACRO_TICKERS
    date = pd.Timestamp("2026-06-12")
    raw = {
        ticker: pd.DataFrame(
            {"close": [100.0]}, index=pd.DatetimeIndex([date])
        )
        for ticker in module.SUBB_REQUIRED_PRICE_TICKERS
    }
    module._assert_columns_fresh(
        raw,
        module.SUBB_REQUIRED_PRICE_TICKERS,
        expected_date=date,
        max_lag_days=0,
        label="Sub-B core",
    )
    gate_prices = pd.DataFrame(
        {
            "DBC": np.linspace(100.0, 120.0, 160),
            "TLT": np.linspace(100.0, 90.0, 160),
        },
        index=pd.bdate_range(end=date, periods=160),
    )
    assert isinstance(
        module._inflation_pressure_state_from_prices(gate_prices, -1), bool
    )


def test_v79_parameter_pool_text_is_derived_from_actual_pool(versions):
    module = versions["v79"]
    chunks = []
    module._write_v78_subb_param_tables(chunks.append)
    text = "".join(chunks)
    expected_pool_label = (
        f"{len(module.US_ROT_BASE_ASSETS)}ETF+"
        f"通胀宏观{len(module.US_ROT_MACRO_ASSETS)}ETF"
    )
    assert expected_pool_label in text
    assert "7ETF+通胀宏观3ETF" not in text

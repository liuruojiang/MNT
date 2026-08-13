import importlib.util
import inspect
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATHS = {
    "v78": ROOT / "mnt_bot V 7.8 plus.py",
    "v79": ROOT / "mnt_bot V 7.9 plus.py",
}

EXPECTED_POOL = {
    "VTI": (0.20, "VTI", "equity"),
    "QQQM": (0.10, "QQQ", "equity"),
    "AVUV": (0.10, "AVUV", "equity"),
    "VEA": (0.10, "VEA", "equity"),
    "AVDV": (0.10, "AVDV", "equity"),
    "VGIT": (0.15, "VGIT", "bond"),
    "DBMF": (0.025, "DBMF", "alt"),
    "KMLM": (0.025, "KMLM", "alt"),
    "GLDM": (0.15, "GLD", "commodity"),
    "IBIT": (0.05, "BTC-USD", "crypto"),
}


def _load_version(name, path):
    module_name = f"subc_sleeve_vol_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def versions():
    return {
        name: _load_version(name, path)
        for name, path in VERSION_PATHS.items()
    }


def _price_from_returns(index, returns, start=100.0):
    return pd.Series(start * np.exp(np.cumsum(returns)), index=index)


def _overlay_prices():
    index = pd.bdate_range("2018-01-02", periods=650)
    n = np.arange(len(index))

    spy_sigma = np.select(
        [n < 210, n < 430],
        [0.0020, 0.0300],
        default=0.0030,
    )
    spy_returns = 0.00015 + spy_sigma * np.where(n % 2 == 0, 1.0, -1.0)

    gold_sigma = np.select(
        [n < 300, n < 465],
        [0.0200, 0.0020],
        default=0.0300,
    )
    gold_returns = 0.00010 + gold_sigma * np.where(n % 2 == 0, 1.0, -1.0)

    return pd.DataFrame(
        {
            "SPY": _price_from_returns(index, spy_returns),
            "GLD": _price_from_returns(index, gold_returns),
            "BIL": 100.0 * np.cumprod(np.full(len(index), 1.00005)),
        },
        index=index,
    )


def _flat_component_ledger(module, index):
    ledger = pd.DataFrame(index=index)
    ledger["asset_cost_return"] = 0.0
    ledger["asset_turnover"] = 0.0
    ledger["asset_cost_fraction"] = 0.0
    for name, cfg in module.PROD_PORTFOLIO.items():
        ledger[f"exposure::{name}"] = float(cfg["w"])
        ledger[f"contribution::{name}"] = 0.0
    ledger["base_return"] = 0.0
    return ledger


def _overlay_run(module):
    prices = _overlay_prices()
    index = prices.index[260:]
    components = _flat_component_ledger(module, index)
    scaled, equity_scale, costs = module._apply_subc_vol_scaling(
        components["base_return"], prices, components=components
    )
    gold_scale = module._subc_relative_scale(
        prices[module.PROD_GOLD_VS_SIGNAL_TICKER],
        index,
        module.PROD_GOLD_VS_SHORT_WINDOW,
        module.PROD_GOLD_VS_LONG_WINDOW,
        module.PROD_VS_MIN_LEV,
        module.PROD_VS_MAX_LEV,
        module.PROD_VS_THRESHOLD,
    )
    return prices, components, scaled, equity_scale, gold_scale, costs


def test_v78_v79_use_the_same_promoted_pool_and_rules(versions):
    for module in versions.values():
        actual = {
            name: (cfg["w"], cfg["proxy"], cfg["cls"])
            for name, cfg in module.PROD_PORTFOLIO.items()
        }
        assert actual == EXPECTED_POOL
        assert sum(cfg["w"] for cfg in module.PROD_PORTFOLIO.values()) == pytest.approx(1.0)
        assert module.SUBC_FORMAL_START == pd.Timestamp("2020-12-03")

        assert module.PROD_VS_ENABLED is True
        assert module.PROD_VS_SIGNAL_TICKER == "SPY"
        assert module.PROD_VS_SCALE_CLASSES == frozenset({"equity"})
        assert module.PROD_VS_TARGET_VOL == pytest.approx(0.15)
        assert module.PROD_VS_VOL_WINDOW == 15
        assert module.PROD_VS_MIN_LEV == pytest.approx(0.5)
        assert module.PROD_VS_MAX_LEV == pytest.approx(1.5)
        assert module.PROD_VS_THRESHOLD == pytest.approx(0.35)

        assert module.PROD_GOLD_VS_ENABLED is True
        assert module.PROD_GOLD_VS_SIGNAL_TICKER == "GLD"
        assert module.PROD_GOLD_VS_SHORT_WINDOW == 30
        assert module.PROD_GOLD_VS_LONG_WINDOW == 252
        assert module.ACTIVE_COMBINED_WEIGHTS == pytest.approx({
            "Sub-A": 0.15,
            "Sub-A-DK": 0.15,
            "Sub-B": 0.40,
            "Sub-C": 0.30,
        })
        assert sum(module.ACTIVE_COMBINED_WEIGHTS.values()) == pytest.approx(1.0)


def test_strategy_c_is_restored_across_allocation_and_performance_surfaces(versions):
    expected_order = ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]
    expected_weights = {
        "Sub-A": 0.15,
        "Sub-A-DK": 0.15,
        "Sub-B": 0.40,
        "Sub-C": 0.30,
    }
    index = pd.bdate_range("2026-01-05", periods=5)
    complete = {
        name: pd.Series(0.01, index=index)
        for name in expected_order
    }
    incomplete = {name: series for name, series in complete.items() if name != "Sub-C"}

    for module in versions.values():
        assert module.COMBINED_DISPLAY_ORDER[-1] == "Sub-C"
        assert module.PERFORMANCE_COMBO_ORDER == expected_order
        assert module.PERFORMANCE_COLUMNS == expected_order + ["Combined"]
        assert module.COMBINED_DISPLAY_ORDER == expected_order
        assert module._performance_combo_weights() == pytest.approx(expected_weights)

        combined = module._performance_combined_daily_returns(complete)
        assert len(combined) == len(index)
        assert np.allclose(combined.to_numpy(), 0.01, atol=1e-12, rtol=0.0)
        assert module._performance_combined_daily_returns(incomplete).empty

        assert module._parse_simple_capital_config("总共7万美元给美股") == pytest.approx({
            "Sub-B": 40_000.0,
            "Sub-C": 30_000.0,
        })
        assert module._parse_simple_position_config(
            "Sub-C VTI 10股 GLDM 20股"
        ) == {"Sub-C": {"VTI": 10, "GLDM": 20}}

        rendered = []
        module._write_subc_param_summary(rendered.append)
        text = "".join(rendered)
        assert "主组合权重30%" in text
        assert "调整死区|Δscale|≥0.35" in text
        assert "VTI" in text and "IBIT" in text

        bot_class = next(
            value
            for name, value in vars(module).items()
            if name.startswith("CombinedStrategyV") and inspect.isclass(value)
        )
        assert 'signal_info["Sub-C"] = self._write_sub_c' in inspect.getsource(
            bot_class._handle_signal
        )
        assert "self._write_sub_c" in inspect.getsource(bot_class._handle_live_signal)
        assert "_write_subc_param_summary" in inspect.getsource(bot_class._handle_params)
        assert "_write_subc_param_summary" in inspect.getsource(bot_class._handle_live_params)


def test_external_sleeves_are_absent_from_both_bot_scripts():
    for path in VERSION_PATHS.values():
        source = path.read_text(encoding="utf-8")
        for external_name in ("Microcap", "微盘", "Sub-D", "策略D"):
            assert external_name not in source


def test_threshold_state_machine_is_lagged_one_session_and_uses_deadband(versions):
    index = pd.bdate_range("2026-01-05", periods=8)
    raw_target = pd.Series(
        [1.00, 1.05, 1.09, 1.11, 1.15, 1.21, 0.95, 0.90],
        index=index,
    )
    expected = pd.Series(
        [1.00, 1.00, 1.00, 1.00, 1.11, 1.11, 1.21, 0.95],
        index=index,
    )
    for module in versions.values():
        actual = module._subc_threshold_scale(raw_target, 0.10)
        pd.testing.assert_series_equal(actual, expected)


def test_spy_absolute_and_gold_relative_scales_match_their_own_signals(versions):
    prices = _overlay_prices()
    index = prices.index[260:]
    for module in versions.values():
        equity_scale = module._subc_absolute_scale(
            prices["SPY"], index, 0.15, 15, 0.5, 1.5, 0.10
        )
        spy_vol = prices["SPY"].pct_change(fill_method=None).rolling(15).std()
        spy_raw = (0.15 / (spy_vol * np.sqrt(module.US_TRADING_DAYS))).clip(0.5, 1.5)
        expected_equity = module._subc_threshold_scale(spy_raw, 0.10).reindex(index).fillna(1.0)
        pd.testing.assert_series_equal(equity_scale, expected_equity)

        gold_scale = module._subc_relative_scale(
            prices["GLD"], index, 30, 252, 0.5, 1.5, 0.10
        )
        gold_ret = prices["GLD"].pct_change(fill_method=None)
        gold_raw = (
            gold_ret.rolling(252).std() / gold_ret.rolling(30).std()
        ).clip(0.5, 1.5)
        expected_gold = module._subc_threshold_scale(gold_raw, 0.10).reindex(index).fillna(1.0)
        pd.testing.assert_series_equal(gold_scale, expected_gold)

        assert equity_scale.between(0.5, 1.5).all()
        assert gold_scale.between(0.5, 1.5).all()
        assert equity_scale.nunique() > 1
        assert gold_scale.nunique() > 1

        # A last-close shock can change the raw target, but lag=1 means it cannot
        # change the scale already executed on that same session.
        shocked_spy = prices["SPY"].copy()
        shocked_spy.iloc[-1] *= 5.0
        shocked_equity = module._subc_absolute_scale(
            shocked_spy, index, 0.15, 15, 0.5, 1.5, 0.10
        )
        assert shocked_equity.iloc[-1] == pytest.approx(equity_scale.iloc[-1])

        shocked_gold = prices["GLD"].copy()
        shocked_gold.iloc[-1] *= 5.0
        shocked_gold_scale = module._subc_relative_scale(
            shocked_gold, index, 30, 252, 0.5, 1.5, 0.10
        )
        assert shocked_gold_scale.iloc[-1] == pytest.approx(gold_scale.iloc[-1])


def test_component_ledger_reconstructs_base_return_exactly(versions):
    index = pd.bdate_range("2020-01-02", periods=430)
    n = np.arange(len(index))
    for module in versions.values():
        proxies = list(dict.fromkeys(
            cfg["proxy"] for cfg in module.PROD_PORTFOLIO.values()
        ))
        prices = {}
        for offset, proxy in enumerate(proxies):
            returns = (
                0.00015
                + (0.0015 + offset * 0.00007)
                * np.sin(n * (0.071 + offset * 0.003))
            )
            prices[proxy] = _price_from_returns(index, returns, 100.0 + offset)
        prices[module.PROD_CASH] = 100.0 * np.cumprod(np.full(len(index), 1.00004))
        prices = pd.DataFrame(prices, index=index)

        signal_dates = pd.DatetimeIndex(
            pd.Series(index, index=index.to_period("M")).groupby(level=0).last().to_numpy()
        )
        signals = pd.DataFrame(1.0, index=signal_dates, columns=proxies)
        ledger = module._compute_daily_subc_components(
            prices,
            signals,
            module.PROD_PORTFOLIO,
            module.PROD_CASH,
        )

        assert not ledger.empty
        reconstructed = ledger["asset_cost_return"].copy()
        for name in module.PROD_PORTFOLIO:
            reconstructed += ledger[f"contribution::{name}"]
        pd.testing.assert_series_equal(
            reconstructed,
            ledger["base_return"],
            check_names=False,
            atol=2e-14,
            rtol=0.0,
        )
        assert (ledger["asset_cost_fraction"] >= 0.0).all()


def test_overlay_financing_cash_and_costs_are_group_specific(versions):
    for module in versions.values():
        prices, components, scaled, equity_scale, gold_scale, costs = _overlay_run(module)
        index = components.index
        bil = prices["BIL"].pct_change(fill_method=None).reindex(index).fillna(0.0)
        spread = module.PROD_VS_SPREAD_BPS / 10000 / module.US_TRADING_DAYS

        equity_assets = [
            name for name, cfg in module.PROD_PORTFOLIO.items()
            if cfg["cls"] in module.PROD_VS_SCALE_CLASSES
        ]
        equity_exposure = sum(module.PROD_PORTFOLIO[name]["w"] for name in equity_assets)
        gold_exposure = module.PROD_PORTFOLIO["GLDM"]["w"]

        expected_costs = (
            equity_exposure * equity_scale.diff().abs().fillna(0.0)
            + gold_exposure * gold_scale.diff().abs().fillna(0.0)
        ) * module.PROD_VS_REBAL_COST_BPS / 10000
        pd.testing.assert_series_equal(costs, expected_costs, check_names=False)

        expected = -expected_costs
        for scale, exposure in (
            (equity_scale, equity_exposure),
            (gold_scale, gold_exposure),
        ):
            delta = (scale - 1.0) * exposure
            expected += (-delta).where(delta <= 0.0, 0.0) * bil
            expected -= delta.where(delta > 0.0, 0.0) * (bil + spread)
        pd.testing.assert_series_equal(scaled, expected, check_names=False)


def test_only_equities_and_gold_are_scaled_while_btc_bonds_and_ctas_stay_one_x(versions):
    shock = None
    for module in versions.values():
        prices, components, base_scaled, equity_scale, gold_scale, _ = _overlay_run(module)
        if shock is None:
            shock = pd.Series(
                np.where(np.arange(len(components)) % 11 == 0, 0.001, -0.0002),
                index=components.index,
            )

        for name in ("VTI", "QQQM", "AVUV", "VEA", "AVDV"):
            changed = components.copy()
            changed[f"contribution::{name}"] = shock
            changed["base_return"] = shock
            result, _, _ = module._apply_subc_vol_scaling(
                changed["base_return"], prices, components=changed
            )
            pd.testing.assert_series_equal(
                result - base_scaled, equity_scale * shock, check_names=False
            )

        changed = components.copy()
        changed["contribution::GLDM"] = shock
        changed["base_return"] = shock
        result, _, _ = module._apply_subc_vol_scaling(
            changed["base_return"], prices, components=changed
        )
        pd.testing.assert_series_equal(
            result - base_scaled, gold_scale * shock, check_names=False
        )

        for name in ("IBIT", "VGIT", "DBMF", "KMLM"):
            changed = components.copy()
            changed[f"contribution::{name}"] = shock
            changed["base_return"] = shock
            result, _, _ = module._apply_subc_vol_scaling(
                changed["base_return"], prices, components=changed
            )
            pd.testing.assert_series_equal(
                result - base_scaled, shock, check_names=False
            )


def test_v78_and_v79_produce_identical_subc_overlay_outputs(versions):
    outputs = {}
    for name, module in versions.items():
        _, _, scaled, equity_scale, gold_scale, costs = _overlay_run(module)
        outputs[name] = (scaled, equity_scale, gold_scale, costs)
    for left, right in zip(outputs["v78"], outputs["v79"]):
        pd.testing.assert_series_equal(left, right)

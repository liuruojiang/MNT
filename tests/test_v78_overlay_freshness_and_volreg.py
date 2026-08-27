import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def load_v78_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "mnt_bot V 7.8 plus.py"
    spec = importlib.util.spec_from_file_location("mnt_bot_v78_plus", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_overlay_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "run_v78_substrategy_poe_overlay_test.py"
    spec = importlib.util.spec_from_file_location("run_v78_substrategy_poe_overlay_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_subb_external_gate_rejects_source_ending_before_target_index(tmp_path, monkeypatch):
    overlay = load_overlay_module()
    gate_dir = tmp_path / "outputs" / "subb_v77_us_long_poe_gate_20260612"
    gate_dir.mkdir(parents=True)
    pd.DataFrame(
        {"date": [pd.Timestamp("2026-05-01")], "qqq": [True]}
    ).to_csv(gate_dir / "poe_us_long_active_by_sleeve.csv", index=False)
    monkeypatch.setattr(overlay, "ROOT", tmp_path)

    target_index = pd.to_datetime(["2026-05-01", "2026-06-12"])

    with pytest.raises(ValueError, match="Sub-B active.*2026-05-01.*2026-06-12"):
        overlay.subb_active_frame(target_index)


def test_adk_external_allowed_rejects_source_ending_before_target_index(tmp_path, monkeypatch):
    overlay = load_overlay_module()
    for filename in (
        "direct16_allowed_daily.csv",
        "transitive16_allowed_daily.csv",
        "consensus16_allowed_daily.csv",
        "transitive_consensus_direct_veto_allowed_daily.csv",
    ):
        pd.DataFrame(
            {"date": [pd.Timestamp("2026-06-11")], "SZ50/ZZ1000": [True]}
        ).to_csv(tmp_path / filename, index=False)
    monkeypatch.setattr(overlay, "ADK_ALLOWED_DIR", tmp_path)
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    baseline = pd.DataFrame({"return": [0.0, 0.0]}, index=dates)
    component = pd.DataFrame(
        {
            "return": [0.0, 0.0],
            "return_before_dk_execution_cost": [0.0, 0.0],
            "top_pair": ["none", "none"],
            "direction": [0, 0],
            "weight": [0.0, 0.0],
        },
        index=dates,
    )
    baseline.attrs["v78_adk_v77"] = component
    baseline.attrs["v78_adk_new"] = component.copy()

    class FakeV78:
        CN_DK_COMMISSION = 0.0005
        CN_TRADING_DAYS = 242
        V78_ADK_V77_WEIGHT = 0.5
        V78_ADK_NEW_PRIMARY_WEIGHT = 0.5

        @staticmethod
        def _dict_weight_turnover(_old_weights, _new_weights):
            return 0.0

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with pytest.raises(ValueError, match="ADK direct16.*2026-06-11.*2026-06-12"):
        overlay.run_adk_overlay(FakeV78(), baseline, out_dir, signal_shift_days=0)


def test_subb_volreg_clears_equity_assets_only_and_uses_open_execution(monkeypatch):
    module = load_v78_module()
    dates = pd.to_datetime(
        ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]
    )
    result = pd.DataFrame(
        {
            "return": [0.0, 0.0, -0.01, 0.02, 0.01],
            "actual_w_QQQ": [0.4] * len(dates),
            "actual_w_EFA": [0.2] * len(dates),
            "actual_w_GLD": [0.3] * len(dates),
            "actual_w_BIL": [0.1] * len(dates),
            "w_QQQ": [0.4] * len(dates),
            "w_EFA": [0.2] * len(dates),
            "w_GLD": [0.3] * len(dates),
            "w_BIL": [0.1] * len(dates),
            "rebalanced": [False] * len(dates),
        },
        index=dates,
    )
    close_df = pd.DataFrame(
        {
            "BIL": [100.0] * len(dates),
            "QQQ": [100.0, 101.0, 99.0, 100.0, 101.0],
            "EFA": [50.0, 51.0, 49.0, 50.0, 51.0],
            "GLD": [200.0, 201.0, 202.0, 203.0, 204.0],
        },
        index=dates,
    )
    us_open = {
        "BIL": pd.Series([100.0] * len(dates), index=dates),
        "QQQ": pd.Series([100.0, 101.0, 98.0, 100.5, 100.0], index=dates),
        "EFA": pd.Series([50.0, 51.0, 48.0, 50.5, 50.0], index=dates),
    }
    states = iter([False, False, True, True, False])

    monkeypatch.setattr(module, "US_ROT_COMMISSION", 0.0)
    monkeypatch.setattr(module, "_volreg_next_cash_state", lambda _current_cash, _ratio: next(states))

    out = module.apply_vol_regime_overlay(
        result,
        pd.Series([100.0] * len(dates), index=dates),
        close_df=close_df,
        us_open=us_open,
    )

    assert out.loc[dates[2], "volreg_action"] == "enter_defense"
    assert out.loc[dates[4], "volreg_action"] == "exit_defense"
    assert bool(out.loc[dates[2], "volreg_defense"])
    assert not bool(out.loc[dates[2], "volreg_cash"])
    assert np.isclose(module.US_ROT_VOLREG_DEFENSE_SCALE, 0.0)
    assert np.isclose(out.loc[dates[2], "w_QQQ"], 0.0)
    assert np.isclose(out.loc[dates[2], "w_EFA"], 0.0)
    assert np.isclose(out.loc[dates[2], "w_GLD"], 0.3)
    assert np.isclose(out.loc[dates[2], "w_BIL"], 0.1 + 0.4 + 0.2)
    assert np.isclose(out.loc[dates[2], "w_CASH"], 0.0)


def test_subb_volreg_syncs_target_weights_for_signal_display(monkeypatch):
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11"])
    result = pd.DataFrame(
        {
            "return": [0.0] * len(dates),
            "actual_w_QQQ": [0.4] * len(dates),
            "actual_w_EFA": [0.2] * len(dates),
            "actual_w_GLD": [0.3] * len(dates),
            "actual_w_BIL": [0.1] * len(dates),
            "w_QQQ": [0.4] * len(dates),
            "w_EFA": [0.2] * len(dates),
            "w_GLD": [0.3] * len(dates),
            "w_BIL": [0.1] * len(dates),
            "target_w_QQQ": [0.4] * len(dates),
            "target_w_EFA": [0.2] * len(dates),
            "target_w_GLD": [0.3] * len(dates),
            "target_w_BIL": [0.1] * len(dates),
            "rebalanced": [False, False, True, False],
        },
        index=dates,
    )
    close_df = pd.DataFrame(
        {
            "BIL": [100.0] * len(dates),
            "QQQ": [100.0] * len(dates),
            "EFA": [50.0] * len(dates),
            "GLD": [200.0] * len(dates),
        },
        index=dates,
    )
    us_open = {
        "BIL": pd.Series([100.0] * len(dates), index=dates),
        "QQQ": pd.Series([100.0] * len(dates), index=dates),
        "EFA": pd.Series([50.0] * len(dates), index=dates),
    }
    states = iter([False, False, True, True])

    monkeypatch.setattr(module, "US_ROT_COMMISSION", 0.0)
    monkeypatch.setattr(module, "_volreg_next_cash_state", lambda _current_cash, _ratio: next(states))

    out = module.apply_vol_regime_overlay(
        result,
        pd.Series([100.0] * len(dates), index=dates),
        close_df=close_df,
        us_open=us_open,
    )
    display = module._subb_signal_display_source_weights(
        out,
        dates[2],
        ["w_QQQ", "w_EFA", "w_GLD", "w_BIL"],
    )

    assert np.isclose(out.loc[dates[2], "target_w_QQQ"], 0.0)
    assert np.isclose(out.loc[dates[2], "target_w_EFA"], 0.0)
    assert np.isclose(out.loc[dates[2], "target_w_BIL"], 0.7)
    assert np.isclose(display["QQQ"], 0.0)
    assert np.isclose(display["EFA"], 0.0)
    assert np.isclose(display["BIL"], 0.7)


def test_subb_volreg_falls_back_per_asset_when_actual_weight_is_partial(monkeypatch):
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-08", "2026-06-09", "2026-06-10"])
    result = pd.DataFrame(
        {
            "return": [0.0] * len(dates),
            "actual_w_BIL": [0.6] * len(dates),
            "w_QQQ": [0.4] * len(dates),
            "w_BIL": [0.6] * len(dates),
            "rebalanced": [False] * len(dates),
        },
        index=dates,
    )
    close_df = pd.DataFrame(
        {
            "BIL": [100.0] * len(dates),
            "QQQ": [100.0] * len(dates),
        },
        index=dates,
    )
    us_open = {
        "BIL": pd.Series([100.0] * len(dates), index=dates),
        "QQQ": pd.Series([100.0] * len(dates), index=dates),
    }
    states = iter([False, True, True])

    monkeypatch.setattr(module, "US_ROT_COMMISSION", 0.0)
    monkeypatch.setattr(module, "_volreg_next_cash_state", lambda _current_cash, _ratio: next(states))

    out = module.apply_vol_regime_overlay(
        result,
        pd.Series([100.0] * len(dates), index=dates),
        close_df=close_df,
        us_open=us_open,
    )

    assert np.isclose(out.loc[dates[1], "model_w_QQQ"], 0.4)
    assert np.isclose(out.loc[dates[1], "volreg_moved_to_bil"], 0.4)
    assert np.isclose(out.loc[dates[1], "w_QQQ"], 0.0)
    assert np.isclose(out.loc[dates[1], "w_BIL"], 1.0)


def test_subb_volreg_rule_text_shows_proxy_scope_and_clear_scale():
    module = load_v78_module()

    text = module._subb_volreg_rule_text()

    assert "QQQ/EMXC/EFA" in text
    assert "x0.00" in text
    assert "BIL" in text
    assert "1.8" in text
    assert "1.4" in text


def test_subb_strict_open_row_rejects_close_fallback():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-12"])
    close_df = pd.DataFrame({"QQQ": [101.0]}, index=dates)

    with pytest.raises(ValueError, match=r"Sub-B official.*2026-06-12.*QQQ.*T\+1 adjusted open"):
        module._us_open_row(
            dates[0],
            ["QQQ"],
            {},
            close_df,
            strict=True,
            context="Sub-B official",
        )


def test_subb_emxc_strict_open_uses_eem_proxy_before_emxc_live_history():
    module = load_v78_module()
    pre_live = pd.Timestamp("2009-05-29")
    switch = module.US_ROT_EMXC_BT_START
    post_live = switch + pd.Timedelta(days=1)
    dates = pd.to_datetime([pre_live, switch, post_live])
    us_raw = {
        "EEM": pd.DataFrame(
            {"open": [20.0, 25.0, 27.5], "close": [21.0, 26.0, 28.0]},
            index=dates,
        ),
        "EMXC": pd.DataFrame(
            {"open": [np.nan, 10.0, 12.0], "close": [np.nan, 11.0, 13.0]},
            index=dates,
        ),
    }
    us_open = module._build_us_open_execution_dict(us_raw)
    close_df = pd.DataFrame({"EMXC": [21.0, 26.0, 31.2]}, index=dates)

    pre_row = module._us_open_row(
        pre_live,
        ["EMXC"],
        us_open,
        close_df,
        strict=True,
        context="Sub-B official rotation",
    )

    assert pre_row["EMXC"] == 20.0
    assert us_open["EMXC"].loc[post_live] == pytest.approx(12.0 * 26.0 / 11.0)


def test_subb_btc_ibit_strict_open_uses_spliced_ibit_open_after_listing():
    module = load_v78_module()
    dates = pd.to_datetime(["2024-01-10", "2024-01-11", "2024-01-12"])
    us_raw = {
        "BTC-USD": pd.DataFrame(
            {"close": [50000.0, 51000.0, 52000.0], "open": [49900.0, 50900.0, 51900.0]},
            index=dates,
        ),
        "IBIT": pd.DataFrame(
            {"close": [50.0, 51.0, 52.0], "open": [49.5, 50.5, 51.5]},
            index=dates,
        ),
    }
    us_open = module._build_us_open_execution_dict(us_raw)
    close_spliced = module.build_ibit_spliced(
        pd.DataFrame(
            {
                "BTC-USD": us_raw["BTC-USD"]["close"],
                "IBIT": us_raw["IBIT"]["close"],
            }
        )
    )
    close_df = pd.DataFrame({"BTC-USD": close_spliced}, index=dates)

    row = module._us_open_row(
        dates[1],
        ["BTC-USD"],
        us_open,
        close_df,
        strict=True,
        context="Sub-B official rotation",
    )

    scale = us_raw["BTC-USD"].loc[dates[0], "close"] / us_raw["IBIT"].loc[dates[0], "close"]
    assert row["BTC-USD"] == us_raw["IBIT"].loc[dates[1], "open"] * scale
    assert row["BTC-USD"] != us_raw["BTC-USD"].loc[dates[1], "open"]


def test_subb_rotation_mix_strict_open_execution_rejects_missing_open(monkeypatch):
    module = load_v78_module()
    dates = pd.bdate_range("2026-06-01", periods=6)
    close_df = pd.DataFrame(
        {
            "QQQ": [100.0, 101.0, 103.0, 104.0, 105.0, 106.0],
            "BIL": [100.0] * len(dates),
        },
        index=dates,
    )
    us_open = {
        "BIL": pd.Series([100.0] * len(dates), index=dates),
        "QQQ": pd.Series([100.0, 101.0, 103.0, 104.0, np.nan, 106.0], index=dates),
    }

    monkeypatch.setattr(module, "US_ROT_LBS", (1,))
    monkeypatch.setattr(module, "US_ROT_MAX_LB", 1)
    monkeypatch.setattr(module, "US_ROT_VOL_LB", 1)
    monkeypatch.setattr(module, "US_ROT_VOL_WINDOW", 2)
    monkeypatch.setattr(module, "US_ROT_TARGET_VOL", 1.0)
    monkeypatch.setattr(module, "US_ROT_MAX_LEV", 1.0)
    monkeypatch.setattr(module, "US_ROT_COMMISSION", 0.0)
    monkeypatch.setattr(module, "_us_signal_days", lambda _close_df, start_idx: {start_idx})
    monkeypatch.setattr(
        module,
        "_us_mix_target_weights",
        lambda *args, **kwargs: ({"QQQ": 1.0}, {1: {"selected": {"QQQ"}}}),
    )

    with pytest.raises(ValueError, match=r"Sub-B official rotation.*QQQ.*T\+1 adjusted open"):
        module.run_us_rotation_mix(
            close_df,
            ["QQQ"],
            us_open=us_open,
            weight_assets=["QQQ", "BIL"],
            strict_open_execution=True,
        )


def test_v78_run_strategies_passes_strict_subb_open_execution_to_all_subb_legs():
    module = load_v78_module()
    source = inspect.getsource(module.CombinedStrategyBase._run_strategies)

    assert source.count("strict_open_execution=strict_subb_open_execution") >= 5


def test_v78_subb_params_display_describes_strict_open_execution_not_close_close_proxy():
    module = load_v78_module()
    source = inspect.getsource(module.CombinedStrategyV78._handle_params)
    subb_section = source.split("### Sub-B", 1)[1].split("### 组合", 1)[0]

    assert "回测用收盘价对收盘价" not in subb_section
    assert "shift(1)近似" not in subb_section
    assert "T+1 adjusted open" in subb_section


def test_v78_production_spec_includes_manual_run_checklist():
    root = Path(__file__).resolve().parents[1]
    spec_text = (root / "docs" / "V7.8_PRODUCTION_SPEC.md").read_text(encoding="utf-8")

    assert "## Manual Run Checklist" in spec_text
    for required_text in (
        "CN close latest date",
        "US close latest date",
        "US adjusted open coverage",
        "Sub-A volume overlay",
        "External gates",
        "Sub-C data and scale state",
    ):
        assert required_text in spec_text

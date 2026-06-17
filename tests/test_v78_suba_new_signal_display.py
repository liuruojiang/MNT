import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd


def load_v78_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "mnt_bot V 7.8 plus.py"
    spec = importlib.util.spec_from_file_location("mnt_bot_v78_plus", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v78_suba_new_rows_show_score_and_abs_gate_status():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-12"])
    raw_score = pd.DataFrame({"AAA": [0.0020], "BBB": [0.0005]}, index=dates)
    abs_mom = pd.DataFrame({"AAA": [0.0100], "BBB": [0.0300]}, index=dates)
    gated_score = raw_score.where(raw_score > module.V78_SUBA_NEW_SCORE_THRESHOLD).where(
        abs_mom > module.V78_SUBA_NEW_ABS_THRESHOLD
    )
    new_result = pd.DataFrame(
        {"holding": ["cash"], "weight": [0.0]},
        index=dates,
    )
    new_result.attrs["v78_raw_score"] = raw_score
    new_result.attrs["v78_abs_mom"] = abs_mom
    new_result.attrs["v78_score"] = gated_score
    cn_result = pd.DataFrame({"v78_suba_new_holding": ["cash"]}, index=dates)
    cn_result.attrs["v78_suba_new"] = new_result

    rows = module._v78_suba_new_signal_rows(cn_result, 0)

    assert rows[0]["code"] == "AAA"
    assert rows[0]["score_pass"] is True
    assert rows[0]["abs_pass"] is False
    assert rows[0]["selected"] is False
    assert rows[1]["code"] == "BBB"
    assert rows[1]["score_pass"] is False
    assert rows[1]["abs_pass"] is True
    assert rows[1]["selected"] is False


def test_v78_suba_blend_exposes_final_components_and_signal_flags():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    v77 = pd.DataFrame(
        {
            "return": [0.0, 0.0],
            "holding": ["AAA", "AAA"],
            "weight": [1.0, 1.0],
            "holding_fraction": [1.0, 1.0],
            "scale_raw": [1.2, 1.2],
            "base_weight": [1.0, 1.0],
            "is_signal": [False, False],
        },
        index=dates,
    )
    new = pd.DataFrame(
        {
            "return": [0.0, 0.0],
            "holding": ["BBB", "BBB"],
            "weight": [0.2, 0.6],
            "holding_fraction": [0.2, 0.6],
            "is_signal": [False, False],
        },
        index=dates,
    )

    out = module.blend_v78_suba_results(v77, new)

    assert np.allclose(out["final_exposure"], [0.6, 0.8])
    assert np.allclose(out["weight"], out["final_exposure"])
    assert out.loc[dates[0], "holding"] == "V7.7A:AAA|NewA:BBB"
    assert out.loc[dates[0], "final_components"]["v77"]["holding"] == "AAA"
    assert out.loc[dates[0], "final_components"]["new"]["weight"] == 0.1
    assert np.isnan(float(out.loc[dates[0], "scale_raw"]))
    assert np.allclose(out["base_weight"], out["final_exposure"])
    assert np.allclose(out["v78_suba_v77_scale_raw"], [1.2, 1.2])
    assert bool(out.loc[dates[1], "is_signal"]) is True


def test_v78_suba_blend_preserves_component_targets_for_signal_display():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    v77 = pd.DataFrame(
        {
            "return": [0.0, 0.0],
            "holding": ["AAA", "AAA"],
            "target": [None, None],
            "weight": [1.0, 1.0],
            "target_weight": [1.0, 1.0],
            "is_signal": [False, False],
        },
        index=dates,
    )
    new = pd.DataFrame(
        {
            "return": [0.0, 0.0],
            "holding": ["OLD", "OLD"],
            "target": [None, "NEW"],
            "weight": [0.2, 0.4],
            "target_weight": [0.4, 0.8],
            "is_signal": [False, True],
        },
        index=dates,
    )

    out = module.blend_v78_suba_results(v77, new)
    state = module._suba_signal_display_state(out, -1)

    assert out.loc[dates[1], "v78_suba_new_holding"] == "OLD"
    assert out.loc[dates[1], "v78_suba_new_target"] == "NEW"
    assert out.loc[dates[1], "target"] == "V7.7A:AAA|NewA:NEW"
    assert abs(float(out.loc[dates[1], "v78_suba_target_exposure"]) - 0.9) < 1e-12
    assert "NewA: OLD 0.20x" in state["current_display"]
    assert "NewA: OLD 0.10x" not in state["current_display"]
    assert "NewA: NEW 0.40x" in state["target_display"]
    assert state["post_display"] == state["target_display"]


def test_v78_suba_signal_display_pre_trade_uses_previous_v77_and_current_newa():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    v77 = pd.DataFrame(
        {
            "return": [0.0, 0.0],
            "holding": ["OLDV77", "NEWV77"],
            "target": [None, None],
            "weight": [1.0, 1.0],
            "target_weight": [1.0, 1.0],
            "is_signal": [False, True],
        },
        index=dates,
    )
    new = pd.DataFrame(
        {
            "return": [0.0, 0.0],
            "holding": ["OLDNEW", "OLDNEW"],
            "target": [None, "NEWNEW"],
            "weight": [0.2, 0.4],
            "target_weight": [0.2, 0.8],
            "is_signal": [False, True],
        },
        index=dates,
    )

    out = module.blend_v78_suba_results(v77, new)
    state = module._suba_signal_display_state(out, -1)

    assert "V7.7A: OLDV77 0.50x" in state["current_display"]
    assert "V7.7A: NEWV77 0.50x" not in state["current_display"]
    assert "NewA: OLDNEW 0.20x" in state["current_display"]
    assert "V7.7A: NEWV77 0.50x" in state["target_display"]
    assert "NewA: NEWNEW 0.40x" in state["target_display"]


def test_v78_suba_signal_info_does_not_suppress_weight_only_signals():
    module = load_v78_module()
    source = inspect.getsource(module.CombinedStrategyV78._handle_signal)
    suba_info_block = source.split('signal_info["Sub-A"] = {', 1)[1].split("# ── Sub-A vol-scaling", 1)[0]

    assert "_cn_target_holding != _cn_display_holding" not in suba_info_block
    assert "执行前:" in suba_info_block
    assert "目标:" in suba_info_block


def test_v78_live_signal_uses_suba_display_fields_not_single_leg_hypo():
    module = load_v78_module()
    compute_source = inspect.getsource(module.CombinedStrategyV78._compute_signal_data)
    live_source = inspect.getsource(module.CombinedStrategyV78._handle_live_signal)
    suba_block = live_source.split('w("### Sub-A: A股轮动', 1)[1].split("# ── Sub-A vol-scaling", 1)[0]

    assert '"cn_current_display": cn_display_state.get("current_display")' in compute_source
    assert '"cn_target_display": cn_display_state.get("target_display")' in compute_source
    assert '"cn_post_display": cn_display_state.get("post_display")' in compute_source
    assert 'd.get("cn_current_display")' in live_source
    assert 'd.get("cn_target_display")' in live_source
    assert 'd.get("cn_post_display")' in live_source
    assert "hypo_cn_name" not in suba_block
    assert "假设现在收盘，信号" not in suba_block
    assert "假设今天出信号" not in suba_block
    assert "needs_cn_trade" in suba_block
    assert "v78_suba_target_exposure" in suba_block
    assert "cn_target != cn_current" not in suba_block
    assert "假设现在收盘目标" in suba_block
    assert "V7.8双腿状态表" in suba_block


def test_v78_suba_legacy_single_leg_hypo_cn_is_not_exposed_to_display_layer():
    module = load_v78_module()
    compute_source = inspect.getsource(module.CombinedStrategyV78._compute_signal_data)
    signal_source = inspect.getsource(module.CombinedStrategyV78._handle_signal)
    live_source = inspect.getsource(module.CombinedStrategyV78._handle_live_signal)

    assert '"hypo_cn":' not in compute_source
    assert 'd.get("hypo_cn"' not in signal_source
    assert 'd.get("hypo_cn"' not in live_source
    assert 'd["hypo_cn"]' not in signal_source
    assert 'd["hypo_cn"]' not in live_source


def test_v78_suba_rebalances_use_newa_target_on_signal_day():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-12"])
    blended = pd.DataFrame({"holding": ["V7.7A:AAA|NewA:OLD"], "weight": [0.7]}, index=dates)
    v77 = pd.DataFrame(
        {
            "return": [0.0],
            "holding": ["AAA"],
            "target": [None],
            "weight": [1.0],
            "target_weight": [1.0],
            "is_signal": [False],
        },
        index=dates,
    )
    new = pd.DataFrame(
        {
            "return": [0.0],
            "holding": ["OLD"],
            "target": ["NEW"],
            "weight": [0.4],
            "target_weight": [0.8],
            "is_signal": [True],
        },
        index=dates,
    )
    blended.attrs["v78_suba_v77"] = v77
    blended.attrs["v78_suba_new"] = new

    records = module.extract_v78_suba_rebalances(blended)

    assert len(records) == 1
    assert records[0]["日期"] == "2026-06-12"
    assert records[0]["策略"] == f"{module.V78_SUBA_NEW_LABEL} ({module.V78_SUBA_NEW_TV10_WEIGHT:.0%})"
    assert records[0]["卖出"] == "OLD 0.40x"
    assert records[0]["买入"] == "NEW 0.80x"


def test_v78_suba_new_tv10_cash_slice_earns_rf_and_weight_changes_signal(monkeypatch):
    module = load_v78_module()
    dates = pd.date_range("2026-06-01", periods=6, freq="B")
    close = pd.DataFrame(
        {
            "AAA": [100.0, 150.0, 75.0, 150.0, 75.0, 150.0],
            module.CN_BOND_CODE: [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        },
        index=dates,
    )
    raw_score = pd.DataFrame({"AAA": [1.0] * len(dates), module.CN_BOND_CODE: [0.0] * len(dates)}, index=dates)
    monkeypatch.setattr(module, "_v78_suba_bias_slope_score", lambda close_df, ma, mom, weight_end: raw_score)
    monkeypatch.setattr(module, "V78_SUBA_NEW_ABS_THRESHOLD", -2.0)
    monkeypatch.setattr(module, "V78_SUBA_NEW_ABS_DAY", 1)
    monkeypatch.setattr(module, "V78_SUBA_NEW_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr(module, "V78_SUBA_NEW_VOL_WINDOW", 2)
    monkeypatch.setattr(module, "V78_SUBA_NEW_TARGET_VOL", 0.05)
    monkeypatch.setattr(module, "V78_SUBA_NEW_MAX_LEV", 1.0)
    monkeypatch.setattr(module, "CN_RF_DAILY", 0.01)
    monkeypatch.setattr(module, "CN_COMMISSION", 0.0)

    out = module.run_v78_suba_new_tv10(close, ["AAA"])
    invested_partial = out[(out["holding"] == "AAA") & (out["weight"] > 0.0) & (out["weight"] < 1.0)]

    assert not invested_partial.empty
    dt = invested_partial.index[0]
    prev_dt = out.index[out.index.get_loc(dt) - 1]
    raw_ret = close.loc[dt, "AAA"] / close.loc[prev_dt, "AAA"] - 1.0
    expected = float(out.loc[dt, "weight"]) * raw_ret + (1.0 - float(out.loc[dt, "weight"])) * module.CN_RF_DAILY
    assert abs(float(out.loc[dt, "return"]) - expected) < 1e-12
    assert bool(out.loc[dt, "is_signal"]) is True


def test_v78_suba_new_tv10_rejects_leverage_without_borrow_cost(monkeypatch):
    module = load_v78_module()
    dates = pd.date_range("2026-06-01", periods=4, freq="B")
    close = pd.DataFrame(
        {
            "AAA": [100.0, 101.0, 102.0, 103.0],
            module.CN_BOND_CODE: [100.0, 100.0, 100.0, 100.0],
        },
        index=dates,
    )
    monkeypatch.setattr(module, "V78_SUBA_NEW_MAX_LEV", 1.1)

    try:
        module.run_v78_suba_new_tv10(close, ["AAA"])
    except ValueError as exc:
        assert "V78_SUBA_NEW_MAX_LEV" in str(exc)
    else:
        raise AssertionError("NewA leverage above 1.0 should require explicit borrow-cost implementation")


def test_v78_suba_volume_overlay_is_applied_to_new_tv10_leg():
    module = load_v78_module()
    source = inspect.getsource(module.CombinedStrategyBase._run_strategies)

    new_leg_pos = source.index("cn_new_result = run_v78_suba_new_tv10")
    new_overlay_pos = source.index("cn_new_result = apply_v78_suba_new_volume_overlay")
    blend_pos = source.index("cn_result = blend_v78_suba_results")

    assert new_leg_pos < new_overlay_pos < blend_pos


def test_v78_suba_new_volume_overlay_no_double_volscale(monkeypatch):
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    close = pd.DataFrame({"AAA": [100.0, 110.0], module.CN_BOND_CODE: [100.0, 100.0]}, index=dates)
    new_result = pd.DataFrame(
        {
            "holding": ["AAA", "AAA"],
            "target": ["AAA", "AAA"],
            "holding_fraction": [0.8, 0.8],
            "base_weight": [0.8, 0.8],
            "weight": [0.8, 0.8],
            "target_weight": [0.8, 0.8],
            "return": [0.0, 0.08],
            "trade_cost": [0.0, 0.0],
            "turnover": [0.0, 0.0],
            "is_signal": [False, False],
        },
        index=dates,
    )
    volume_signal = pd.Series([True, True], index=dates)
    volume_feature = pd.DataFrame({"combined_scale": [0.5, 0.5]}, index=dates)
    monkeypatch.setattr(module, "CN_TARGET_VOL", 99.0)
    monkeypatch.setattr(module, "CN_MAX_LEV", 1.5)
    monkeypatch.setattr(module, "CN_COMMISSION", 0.0)
    monkeypatch.setattr(module, "CN_RF_DAILY", 0.01)

    out = module.apply_v78_suba_new_volume_overlay(new_result, close, volume_signal, volume_feature)

    assert np.allclose(out["weight"], [0.0, 0.4])
    assert np.allclose(out["target_weight"], [0.4, 0.4])
    assert list(out["holding"]) == ["cash", "AAA"]
    assert list(out["target"]) == ["AAA", None]
    assert out["weight"].max() <= module.V78_SUBA_NEW_MAX_LEV
    expected = 0.4 * 0.10 + 0.6 * module.CN_RF_DAILY
    assert abs(float(out.loc[dates[1], "return"]) - expected) < 1e-12


def test_v78_suba_new_volume_overlay_uses_previous_actual_holding_when_scale_drops(monkeypatch):
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    close = pd.DataFrame({"AAA": [100.0, 90.0], module.CN_BOND_CODE: [100.0, 100.0]}, index=dates)
    new_result = pd.DataFrame(
        {
            "holding": ["cash", "AAA"],
            "target": ["AAA", "AAA"],
            "holding_fraction": [0.0, 1.0],
            "base_weight": [0.0, 1.0],
            "weight": [0.0, 1.0],
            "target_weight": [1.0, 1.0],
            "return": [0.0, -0.10],
            "trade_cost": [0.0, 0.0],
            "turnover": [1.0, 0.0],
            "is_signal": [True, True],
        },
        index=dates,
    )
    volume_signal = pd.Series([False, True], index=dates)
    volume_feature = pd.DataFrame({"combined_scale": [1.0, 0.0]}, index=dates)
    monkeypatch.setattr(module, "CN_COMMISSION", 0.01)
    monkeypatch.setattr(module, "CN_RF_DAILY", 0.0)

    out = module.apply_v78_suba_new_volume_overlay(new_result, close, volume_signal, volume_feature)

    assert out.loc[dates[0], "holding"] == "cash"
    assert out.loc[dates[0], "target"] == "AAA"
    assert float(out.loc[dates[0], "turnover"]) == 1.0
    assert out.loc[dates[1], "holding"] == "AAA"
    assert out.loc[dates[1], "target"] == "cash"
    assert float(out.loc[dates[1], "weight"]) == 1.0
    assert float(out.loc[dates[1], "target_weight"]) == 0.0
    assert abs(float(out.loc[dates[1], "trade_cost"]) - 0.01) < 1e-12
    assert abs(float(out.loc[dates[1], "return"]) - ((1.0 - 0.10) * (1.0 - 0.01) - 1.0)) < 1e-12


def test_v78_suba_new_volume_overlay_zero_scale_sets_cash(monkeypatch):
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    close = pd.DataFrame({"AAA": [100.0, 110.0], module.CN_BOND_CODE: [100.0, 100.0]}, index=dates)
    new_result = pd.DataFrame(
        {
            "holding": ["AAA", "AAA"],
            "target": ["AAA", "AAA"],
            "holding_fraction": [0.8, 0.8],
            "base_weight": [0.8, 0.8],
            "weight": [0.8, 0.8],
            "target_weight": [0.8, 0.8],
            "return": [0.0, 0.08],
            "trade_cost": [0.0, 0.0],
            "turnover": [0.0, 0.0],
            "is_signal": [True, True],
        },
        index=dates,
    )
    volume_signal = pd.Series([True, True], index=dates)
    volume_feature = pd.DataFrame({"combined_scale": [0.0, 0.0]}, index=dates)
    monkeypatch.setattr(module, "CN_COMMISSION", 0.0)

    out = module.apply_v78_suba_new_volume_overlay(new_result, close, volume_signal, volume_feature)

    assert list(out["holding"]) == ["cash", "cash"]
    assert list(out["target"]) == ["cash", "cash"]
    assert np.allclose(out["weight"], [0.0, 0.0])
    assert np.allclose(out["target_weight"], [0.0, 0.0])


def test_v78_suba_rebalances_use_component_legs_not_composite_asset():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    close = pd.DataFrame({"AAA": [100.0, 101.0], "BBB": [200.0, 202.0], "CCC": [300.0, 303.0]}, index=dates)
    blended = pd.DataFrame(
        {
            "holding": ["V7.7A:AAA|NewA:BBB", "V7.7A:CCC|NewA:BBB"],
            "weight": [1.0, 1.0],
        },
        index=dates,
    )
    v77 = pd.DataFrame({"holding": ["AAA", "CCC"], "weight": [1.0, 1.0]}, index=dates)
    new = pd.DataFrame({"holding": ["BBB", "BBB"], "weight": [1.0, 1.0]}, index=dates)
    blended.attrs["v78_suba_v77"] = v77
    blended.attrs["v78_suba_new"] = new

    legacy_records = module.extract_cn_rebalances(blended, close)
    v78_records = module.extract_v78_suba_rebalances(blended, close)

    assert legacy_records[0]["卖出价格"] is None
    assert len(v78_records) == 1
    assert "V7.7A" in v78_records[0]["策略"]
    assert v78_records[0]["卖出价格"] == 101.0


def test_v78_suba_position_text_hides_composite_holding():
    module = load_v78_module()
    row = pd.Series(
        {
            "holding": "V7.7A:AAA|NewA:BBB",
            "v78_suba_v77_holding": "AAA",
            "v78_suba_new_holding": "BBB",
            "v78_suba_v77_weight": 1.0,
            "v78_suba_new_weight": 0.5,
        }
    )

    text = module._v78_suba_position_text(row)

    assert "V7.7A:" in text
    assert "NewA:" in text
    assert "V7.7A:AAA|NewA:BBB" not in text


def test_v78_rebalance_extractors_are_wired_into_signal_and_performance_pages():
    module = load_v78_module()
    signal_source = inspect.getsource(module.CombinedStrategyV78._handle_signal)
    performance_source = inspect.getsource(module.CombinedStrategyV78._handle_performance)

    assert "extract_v78_suba_rebalances(cn_result" in signal_source
    assert "extract_v78_adk_rebalances(cn_dk_result" in signal_source
    assert "extract_v78_suba_rebalances(cn_result" in performance_source
    assert "extract_v78_adk_rebalances(cn_dk_result" in performance_source


def test_v78_suba_v77_leg_tables_use_v77_holding_not_composite_holding():
    module = load_v78_module()
    combined_source = "\n".join(
        [
            inspect.getsource(module.CombinedStrategyV78._handle_signal),
            inspect.getsource(module.CombinedStrategyV78._handle_live_signal),
            inspect.getsource(module.CombinedStrategyV78._handle_live_params),
        ]
    )

    assert "current_holding=_cn_display_holding" not in combined_source
    assert "current_holding=cn_current" not in combined_source
    assert "v78_suba_v77_holding" in combined_source


def test_v78_suba_display_branches_before_single_leg_volscale_projection():
    module = load_v78_module()
    for method in (module.CombinedStrategyV78._handle_signal, module.CombinedStrategyV78._handle_live_signal):
        source = inspect.getsource(method)
        suba_block = source.split('if "weight" in cn_result.columns', 1)[1].split("_write_v78_suba_blend_table", 1)[0]

        assert suba_block.index('"v78_suba_final_exposure" in cn_result.columns') < suba_block.index("_compute_next_vol_scale")
        assert "VolScale调仓" not in suba_block.split('"v78_suba_final_exposure" in cn_result.columns', 1)[0]


def test_v78_signal_history_routes_suba_to_component_rebalance_extractor():
    module = load_v78_module()
    source = inspect.getsource(module.CombinedStrategyV78._handle_signal_history)
    suba_block = source.split("# ===== Sub-A =====", 1)[1].split("# ── Sub-A 杠杆缩放调仓", 1)[0]

    assert 'if "v78_suba_final_exposure" in cn_result.columns' in suba_block
    assert "extract_v78_suba_rebalances" in suba_block
    assert 'cn_period["holding"]' not in suba_block


def test_v78_suba_live_params_component_exposure_uses_multiply_sign():
    module = load_v78_module()
    source = inspect.getsource(module.CombinedStrategyV78._handle_live_params)
    component_block = source.split("V7.8 Sub-A component exposure", 1)[1].split("Execution basis", 1)[0]

    assert "x ?" not in component_block
    assert "×" in component_block


def test_v78_suba_leg_tables_use_unified_columns_for_v77_and_new():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-12"])
    cn_result = pd.DataFrame({"holding": ["cash"]}, index=dates)
    raw_score = pd.DataFrame({"AAA": [0.0020]}, index=dates)
    abs_mom = pd.DataFrame({"AAA": [0.0300]}, index=dates)
    new_result = pd.DataFrame({"holding": ["AAA"], "weight": [1.0]}, index=dates)
    new_result.attrs["v78_raw_score"] = raw_score
    new_result.attrs["v78_abs_mom"] = abs_mom
    new_result.attrs["v78_score"] = raw_score
    cn_result.attrs["v78_suba_new"] = new_result
    bias_mom = {"AAA": pd.Series([1.2], index=dates)}
    r2 = {"AAA": pd.Series([0.3], index=dates)}
    abs_mom_v77 = {"AAA": pd.Series([0.03], index=dates)}
    chunks = []

    module._write_v78_suba_leg_signal_tables(
        chunks.append,
        cn_result,
        0,
        bias_mom,
        r2,
        abs_mom_v77,
        ["AAA"],
        current_holding="cash",
    )
    text = "".join(chunks)

    assert "**V7.7A原版 子策略状态**" in text
    assert "**New A TV1.0 子策略状态**" in text
    assert "| # | 资产 | 排名分数 | 质量过滤 | 动量过滤 | 状态 |" in text
    assert "乖离动量排名" not in text
    assert "信号过滤" not in text


def test_v78_suba_leg_status_tables_do_not_mix_signal_icons():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-12"])
    cn_result = pd.DataFrame({"holding": ["cash"]}, index=dates)
    raw_score = pd.DataFrame({"AAA": [-0.0020]}, index=dates)
    abs_mom = pd.DataFrame({"AAA": [-0.0100]}, index=dates)
    new_result = pd.DataFrame({"holding": ["cash"], "weight": [0.0]}, index=dates)
    new_result.attrs["v78_raw_score"] = raw_score
    new_result.attrs["v78_abs_mom"] = abs_mom
    new_result.attrs["v78_score"] = raw_score.where(raw_score > module.V78_SUBA_NEW_SCORE_THRESHOLD)
    cn_result.attrs["v78_suba_new"] = new_result
    bias_mom = {"AAA": pd.Series([-1.2], index=dates)}
    r2 = {"AAA": pd.Series([0.3], index=dates)}
    abs_mom_v77 = {"AAA": pd.Series([-0.01], index=dates)}
    chunks = []

    module._write_v78_suba_leg_signal_tables(
        chunks.append,
        cn_result,
        0,
        bias_mom,
        r2,
        abs_mom_v77,
        ["AAA"],
        current_holding="cash",
    )
    text = "".join(chunks)

    assert "动量≤0" in text
    assert "排除" in text
    for marker in ("⛔", "✅", "❌", "🟢", "🔴"):
        assert marker not in text

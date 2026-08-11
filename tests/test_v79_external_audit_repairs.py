import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def load_v79_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "mnt_bot V 7.9 plus.py"
    spec = importlib.util.spec_from_file_location("mnt_bot_v79_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_newa_volume_policy_skips_overlay_when_feature_is_unresolved():
    module = load_v79_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    close = pd.DataFrame({"A": [100.0, 101.0]}, index=dates)
    base = pd.DataFrame(
        {
            "return": [0.0, 0.0],
            "holding": ["cash", "A"],
            "target": ["A", "A"],
            "weight": [0.0, 1.0],
            "target_weight": [1.0, 1.0],
            "is_signal": [True, False],
        },
        index=dates,
    )
    feature = pd.DataFrame(
        {"combined_unresolved": [True, True], "combined_scale": [0.0, 0.0]},
        index=dates,
    )

    result = module._apply_v78_suba_new_volume_overlay_policy(
        base,
        close,
        pd.Series(True, index=dates),
        feature,
        allow_unresolved_suba_volume=True,
    )

    pd.testing.assert_series_equal(result["target_weight"], base["target_weight"])
    assert result["suba_volume_unresolved"].all()
    assert result["suba_volume_unavailable"].all()


def test_suba_blend_separates_during_day_and_close_target_exposure():
    module = load_v79_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    v77 = pd.DataFrame(
        {
            "return": [0.0, 0.0],
            "holding": ["A", "B"],
            "weight": [0.8, 1.2],
            "is_signal": [False, True],
        },
        index=dates,
    )
    new = pd.DataFrame(
        {
            "return": [0.0, 0.0],
            "holding": ["A", "A"],
            "target": [None, "B"],
            "weight": [0.4, 0.4],
            "target_weight": [0.4, 1.0],
            "is_signal": [False, True],
        },
        index=dates,
    )

    blend = module.blend_v78_suba_results(v77, new)

    assert blend.loc[dates[1], "final_exposure"] == pytest.approx(0.6)
    assert blend.loc[dates[1], "weight"] == pytest.approx(0.6)
    assert blend.loc[dates[1], "target_exposure"] == pytest.approx(1.1)
    assert bool(blend.loc[dates[1], "is_signal"])


def test_suba_execution_chain_explains_zero_current_weight_as_timing_only():
    module = load_v79_module()
    date = pd.Timestamp("2026-08-10")
    blend = pd.DataFrame(
        {
            "v78_suba_v77_holding": ["cash"],
            "v78_suba_v77_weight": [0.0],
            "v78_suba_new_holding": ["cash"],
            "v78_suba_new_weight": [0.0],
        },
        index=[date],
    )
    blend.attrs["v78_suba_v77"] = pd.DataFrame(
        {"holding": ["cash"], "weight": [0.0]}, index=[date]
    )
    blend.attrs["v78_suba_new"] = pd.DataFrame(
        {
            "holding": ["cash"],
            "weight": [0.0],
            "target": ["AAA"],
            "target_weight": [0.8],
            "base_target_holding_before_suba_volume": ["AAA"],
            "base_target_weight_before_suba_volume": [0.8],
            "suba_volume_rule_on": [False],
            "suba_volume_rule_scale": [1.0],
        },
        index=[date],
    )

    rows = module._v79_suba_leg_execution_rows(blend, -1)
    new_row = next(row for row in rows if row["leg"] == module.V78_SUBA_NEW_LABEL)

    assert new_row["current"] == "Cash / 0.00x"
    assert "AAA / 0.80x" in new_row["final_target"]
    assert "当前0仅因时点" in new_row["reason"]
    assert "收盘执行后" in new_row["reason"]


def test_suba_execution_chain_names_the_overlay_that_forces_zero_target():
    module = load_v79_module()
    date = pd.Timestamp("2026-08-10")
    blend = pd.DataFrame(
        {
            "v78_suba_v77_holding": ["cash"],
            "v78_suba_v77_weight": [0.0],
            "v78_suba_new_holding": ["cash"],
            "v78_suba_new_weight": [0.0],
        },
        index=[date],
    )
    blend.attrs["v78_suba_v77"] = pd.DataFrame(
        {"holding": ["cash"], "weight": [0.0]}, index=[date]
    )
    blend.attrs["v78_suba_new"] = pd.DataFrame(
        {
            "holding": ["cash"],
            "weight": [0.0],
            "target": ["cash"],
            "target_weight": [0.0],
            "base_target_holding_before_suba_volume": ["AAA"],
            "base_target_weight_before_suba_volume": [0.8],
            "suba_volume_rule_on": [True],
            "suba_volume_rule_scale": [0.0],
        },
        index=[date],
    )

    rows = module._v79_suba_leg_execution_rows(blend, -1)
    new_row = next(row for row in rows if row["leg"] == module.V78_SUBA_NEW_LABEL)

    assert new_row["raw_target"] == "AAA / 0.80x"
    assert new_row["final_target"] == "Cash / 0.00x"
    assert "成交额风控 ×0.00" in new_row["reason"]


def test_suba_execution_chain_names_v77_overheat_clear():
    module = load_v79_module()
    date = pd.Timestamp("2026-08-10")
    blend = pd.DataFrame(
        {
            "v78_suba_v77_holding": ["cash"],
            "v78_suba_v77_weight": [0.0],
            "v78_suba_new_holding": ["cash"],
            "v78_suba_new_weight": [0.0],
        },
        index=[date],
    )
    blend.attrs["v78_suba_v77"] = pd.DataFrame(
        {
            "holding": ["cash"],
            "weight": [0.0],
            "pre_suba_overheat_holding": ["AAA"],
            "pre_suba_overheat_weight": [1.2],
            "pre_suba_volume_weight": [0.0],
            "suba_same_side_overheat_on": [True],
            "suba_same_side_overheat_bias": [0.30],
            "suba_volume_rule_on": [False],
            "suba_volume_rule_scale": [1.0],
        },
        index=[date],
    )
    blend.attrs["v78_suba_new"] = pd.DataFrame(
        {"holding": ["cash"], "weight": [0.0], "target_weight": [0.0]}, index=[date]
    )

    rows = module._v79_suba_leg_execution_rows(blend, -1)
    v77_row = next(row for row in rows if row["leg"] == "V7.7A原版")

    assert v77_row["raw_target"] == "AAA / 1.20x"
    assert "MA60过热止盈 ×0.00" in v77_row["reason"]
    assert "当前乖离30.0%" in v77_row["reason"]


def test_suba_execution_chain_explains_v77_top1_failure_and_no_fallback():
    module = load_v79_module()
    date = pd.Timestamp("2026-08-10")
    blend = pd.DataFrame(
        {
            "v78_suba_v77_holding": ["cash"],
            "v78_suba_v77_weight": [0.0],
            "v78_suba_new_holding": ["cash"],
            "v78_suba_new_weight": [0.0],
        },
        index=[date],
    )
    blend.attrs["v78_suba_v77"] = pd.DataFrame(
        {
            "holding": ["cash"],
            "weight": [0.0],
            "suba_top_code": ["AAA"],
            "suba_top_score": [12.0],
            "suba_top_r2": [0.10],
            "suba_top_abs_mom": [0.04],
            "suba_top_score_pass": [True],
            "suba_top_r2_pass": [False],
            "suba_top_abs_pass": [True],
        },
        index=[date],
    )
    blend.attrs["v78_suba_new"] = pd.DataFrame(
        {"holding": ["cash"], "weight": [0.0], "target_weight": [0.0]}, index=[date]
    )

    rows = module._v79_suba_leg_execution_rows(blend, -1)
    v77_row = next(row for row in rows if row["leg"] == "V7.7A原版")

    assert "Top-1=AAA未通过：R² 0.1000<0.15" in v77_row["reason"]
    assert "只检查Top-1，不递补第2名" in v77_row["reason"]


def test_suba_execution_chain_is_wired_to_all_query_surfaces():
    module = load_v79_module()
    for handler in (
        module.CombinedStrategyV78._handle_signal,
        module.CombinedStrategyV78._handle_live_signal,
        module.CombinedStrategyV78._handle_params,
        module.CombinedStrategyV78._handle_live_params,
    ):
        assert "_write_v79_suba_execution_chain" in inspect.getsource(handler)


def test_suba_displays_state_the_two_different_fallback_rules_explicitly():
    module = load_v79_module()
    param_chunks = []
    module._write_v78_suba_param_tables(param_chunks.append)
    params_text = "".join(param_chunks)
    execution_source = inspect.getsource(module._write_v79_suba_execution_chain)
    v77_source = inspect.getsource(module._write_v78_suba_v77_leg_signal_table)
    new_source = inspect.getsource(module._write_v78_suba_new_leg_signal_table)

    assert "不递补第2名" in v77_source
    assert "首名失败可递补" in new_source
    assert "V7.7A首名失败不递补" in execution_source
    assert "New A会从其余合格资产中递补" in execution_source
    assert "先定原始Top-1，再验门槛；不递补" in params_text
    assert "全池先过滤，再在合格池择优；允许递补" in params_text


def test_subb_bias_and_logvol_scores_require_every_configured_window():
    module = load_v79_module()
    dates = pd.bdate_range("2024-01-02", periods=420)
    close = pd.DataFrame(100.0, index=dates, columns=module.US_ROT_POOL)

    bias = module._v78_score_bias_level(close)
    logvol = module._v78_score_log_weighted(close)

    assert bias.iloc[300].isna().all()
    assert bias.iloc[389].notna().all()
    assert logvol.iloc[250].isna().all()
    assert logvol.iloc[320].notna().all()


def test_spy_volume_failure_uses_cached_history_and_fails_closed_only_for_missing_tail(monkeypatch):
    module = load_v79_module()
    dates = pd.bdate_range("2026-01-02", periods=70)
    cached = pd.Series(100.0, index=dates[:-2], dtype=float)
    cached.iloc[-5:] = 200.0
    unavailable = lambda index: (pd.Series(False, index=index, dtype=bool), "unavailable: network")
    monkeypatch.setattr(module, "_v78_fetch_spy_volume", unavailable)
    monkeypatch.setattr(module, "_v78_fetch_spy_volume_stooq", unavailable)
    monkeypatch.setattr(module, "_load_v78_spy_volume_cache", lambda: cached)
    monkeypatch.setattr(module, "V78_SUBB_SPY_VOLUME_FAIL_MODE", "fail_closed")

    gate, source = module._v78_spy_volume_gate(dates)

    assert not bool(gate.iloc[0])
    assert bool(gate.iloc[-3])
    assert gate.iloc[-2:].all()
    assert "local-cache" in source
    assert "fail_closed" in source


def test_subb_volume_warning_reports_partially_unresolved_spy_tail():
    module = load_v79_module()
    date = pd.Timestamp("2026-06-12")
    component = pd.DataFrame(
        {
            "volume_source": [
                "local-cache SPY volume | unresolved SPY volume 2026-06-12..2026-06-12 (1 dates); fail_closed"
            ]
        },
        index=[date],
    )
    result = pd.DataFrame(index=[date])
    result.attrs["v78_subb_bias"] = component

    warning = module._v78_subb_volume_warning(result)

    assert "Bias" in warning
    assert "fail-closed" in warning


def test_subb_model_rebalance_is_kept_when_volreg_transitions_same_day():
    module = load_v79_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    result = pd.DataFrame(
        {
            "model_rebalanced": [False, True],
            "volreg_transition": [False, True],
            "volreg_action": ["", "enter_defense"],
            "model_target_w_QQQ": [0.50, 0.70],
            "model_target_w_GLD": [0.50, 0.30],
            "target_w_QQQ": [0.50, 0.00],
            "target_w_GLD": [0.50, 0.30],
            "target_w_BIL": [0.00, 0.70],
            "effective_w_QQQ": [0.50, 0.00],
            "effective_w_GLD": [0.50, 0.30],
            "effective_w_BIL": [0.00, 0.70],
        },
        index=dates,
    )

    model_records = module.extract_us_rot_rebalances(
        result, since_date=pd.Timestamp("2026-06-12")
    )
    volreg_records = module.extract_subb_volreg_rebalances(
        result, since_date=pd.Timestamp("2026-06-12")
    )

    assert len(model_records) == 1
    assert "QQQM 50.0%->70.0%" in model_records[0]["买入"]
    assert len(volreg_records) == 1


def test_cn_proxy_stitch_keeps_official_rows_newer_than_proxy():
    module = load_v79_module()
    base_dates = pd.to_datetime(["2026-06-10", "2026-06-11", "2026-06-12"])
    proxy_dates = pd.to_datetime(["2026-06-10", "2026-06-11"])
    base = pd.DataFrame({"close": [100.0, 101.0, 102.0]}, index=base_dates)
    proxy = pd.DataFrame({"close": [200.0, 202.0]}, index=proxy_dates)

    stitched = module._stitch_cn_proxy_returns(base, proxy)

    pd.testing.assert_frame_equal(stitched, base)


def test_cn_today_supplement_keeps_a_valid_flat_close(monkeypatch):
    module = load_v79_module()
    previous = pd.Timestamp("2026-06-11")
    today = pd.Timestamp("2026-06-12")
    frame = pd.DataFrame({"close": [100.0]}, index=pd.DatetimeIndex([previous]))
    monkeypatch.setattr(module, "beijing_now", lambda: today.replace(hour=16).to_pydatetime())
    monkeypatch.setattr(module, "_can_use_cn_realtime_snapshot_at", lambda now: True)
    monkeypatch.setattr(module, "_is_cn_required_close_day", lambda date: True)
    monkeypatch.setattr(module, "_fetch_cn_realtime_close", lambda secid: 100.0)

    supplemented = module._supplement_today_close(frame, "1.000300", today.date())

    assert supplemented.index[-1] == today
    assert float(supplemented.iloc[-1]["close"]) == 100.0


def test_cyb_amount_prefers_true_amount_before_volume_proxy(monkeypatch):
    module = load_v79_module()
    dates = pd.bdate_range("2026-01-02", periods=60)
    amount = pd.DataFrame({"amount": np.arange(60, dtype=float) + 1.0}, index=dates)
    calls = []

    def sohu(*args, **kwargs):
        calls.append("Sohu amount")
        return amount

    def proxy(*args, **kwargs):
        calls.append("volume proxy")
        return amount

    monkeypatch.setattr(module, "_fetch_cn_sohu_amount", sohu)
    monkeypatch.setattr(module, "_fetch_cn_qq_amount_proxy", proxy)
    monkeypatch.setattr(module, "_fetch_cn_sina_amount_proxy", proxy)

    _, source = module._fetch_cn_amount_with_fallback(
        module.CN_SA_VOLUME_CYB_SECID, "CYB"
    )

    assert source == "Sohu amount"
    assert calls == ["Sohu amount"]


def test_bias_momentum_calculators_emit_the_first_mathematically_valid_row():
    module = load_v79_module()
    series = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    first_valid = 3 + 2 - 2

    generic = module.calc_bias_momentum(series, bias_n=3, mom_day=2)
    single = module._suba_single_calc_bias_momentum(series, 3, 2, 10.0)
    dk = module._dk_calc_bias_momentum(series, 3, 2)

    assert pd.isna(generic.iloc[first_valid - 1])
    assert pd.notna(generic.iloc[first_valid])
    assert pd.notna(single.iloc[first_valid])
    assert pd.notna(dk.iloc[first_valid])


def test_parse_date_range_maps_no_year_cross_year_interval_correctly(monkeypatch):
    module = load_v79_module()
    now = pd.Timestamp("2026-08-07 12:00:00")
    monkeypatch.setattr(module, "beijing_now", lambda: now.to_pydatetime())

    start, end = module.parse_date_range("12月20日到1月10日")

    assert start == pd.Timestamp("2025-12-20")
    assert end == pd.Timestamp("2026-01-10")
    assert start <= end


@pytest.mark.parametrize(
    "text",
    ["12月31日到1月1日", "11月15日到2月20日", "8月8日到8月9日"],
)
def test_parse_date_range_no_year_invariants(monkeypatch, text):
    module = load_v79_module()
    monkeypatch.setattr(
        module,
        "beijing_now",
        lambda: pd.Timestamp("2026-08-07 12:00:00").to_pydatetime(),
    )

    start, end = module.parse_date_range(text)

    assert start <= end
    assert (end - start).days < 370


def test_cn_leverage_rebalance_record_uses_close_time():
    module = load_v79_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    result = pd.DataFrame(
        {"holding": ["000300", "000300"], "weight": [0.8, 1.2]},
        index=dates,
    )
    close = pd.DataFrame({"000300": [100.0, 101.0]}, index=dates)

    records = module.extract_cn_rebalances(result, close)

    assert len(records) == 1
    assert records[0]["北京时间"] == module.beijing_time_str(
        dates[1], "CN", "close"
    )


def test_csindex_fetchers_close_retry_sessions():
    module = load_v79_module()

    price_source = inspect.getsource(module._fetch_cn_csindex)
    amount_source = inspect.getsource(module._fetch_cn_csindex_amount)

    assert "with requests.Session() as sess:" in price_source
    assert "with requests.Session() as sess:" in amount_source


def test_signal_handlers_initialize_pending_flags_before_optional_branches():
    module = load_v79_module()
    signal_source = inspect.getsource(module.CombinedStrategyV78._handle_signal)
    live_source = inspect.getsource(module.CombinedStrategyV78._handle_live_signal)

    assert "_cn_pending = False" in signal_source
    assert "_cn_pending3 = False" in live_source
    assert "_dk_pending3 = False" in live_source


def test_params_no_longer_advertise_unused_microcap_direct_volume_rule():
    module = load_v79_module()
    params_source = inspect.getsource(module.CombinedStrategyV78._handle_params)

    assert "MICROCAP_DIRECT_VOLUME_CODE" not in params_source
    assert "直接口径参考" not in params_source


def test_adk_score_overheat_cost_is_explicitly_indicative():
    module = load_v79_module()
    dates = pd.bdate_range("2026-01-02", periods=5)
    result = pd.DataFrame(
        {
            "return": [0.0] * 5,
            "holding": ["A_1"] * 5,
            "top_pair": ["A"] * 5,
            "direction": [1] * 5,
            "weight": [1.0] * 5,
            "is_signal": [False] * 5,
        },
        index=dates,
    )
    result.attrs["signals_df"] = pd.DataFrame({"A": [0.0] * 5}, index=dates)

    adjusted = module.apply_v78_adk_score_overheat(result)

    assert "v78_score_overheat_cost" not in adjusted.columns
    assert "v78_score_overheat_cost_indicative" in adjusted.columns


def test_adk_blend_reports_volatility_scaling_per_leg():
    module = load_v79_module()
    date = pd.Timestamp("2026-06-12")
    v77 = pd.DataFrame(
        {
            "top_pair": ["HS300/ZZ500"],
            "direction": [1],
            "weight": [0.96],
            "base_weight": [1.20],
            "scale_raw": [1.25],
            "realized_vol": [0.12],
            "overlay_scale": [0.80],
            "risk_gate_scale": [1.0],
        },
        index=[date],
    )
    new = pd.DataFrame(
        {
            "top_pair": ["CYB/ZZ1000"],
            "direction": [-1],
            "weight": [0.0],
            "base_weight": [1.10],
            "scale_raw": [1.15],
            "realized_vol": [0.14],
            "v78_score_overheat_scale": [0.0],
        },
        index=[date],
    )
    blend = pd.DataFrame(
        {"v78_adk_final_exposure": [0.48], "weight": [0.48]}, index=[date]
    )
    blend.attrs["v78_adk_v77"] = v77
    blend.attrs["v78_adk_new"] = new

    rows = module._v78_adk_leg_status_rows(blend, -1)

    assert rows[0]["realized_vol"] == pytest.approx(0.12)
    assert rows[0]["vol_scale_raw"] == pytest.approx(1.25)
    assert rows[0]["vol_scale"] == pytest.approx(1.5)
    assert rows[0]["overlay_multiplier"] == pytest.approx(0.64)
    assert rows[1]["vol_scale_raw"] == pytest.approx(1.15)
    assert rows[1]["overlay_multiplier"] == pytest.approx(0.0)


def test_live_params_does_not_compute_a_composite_adk_volscale():
    module = load_v79_module()
    source = inspect.getsource(module.CombinedStrategyV78._handle_live_params)

    assert "ADK双腿分别执行波动率缩放；综合结果不存在单一VolScale" in source


def test_adk_close_target_ignores_the_last_executed_signal_row():
    module = load_v79_module()
    date = pd.Timestamp("2026-06-12")

    def component(current_pair, target_pair):
        frame = pd.DataFrame(
            {"top_pair": [current_pair], "direction": [1], "weight": [1.0]},
            index=[date],
        )
        frame.attrs["signals_df"] = pd.DataFrame(
            {current_pair: [2.0], target_pair: [3.0 if target_pair != current_pair else 2.0]},
            index=[date],
        )
        frame.attrs["pair_data"] = {
            current_pair: pd.DataFrame({"signal": [1]}, index=[date]),
            target_pair: pd.DataFrame({"signal": [1]}, index=[date]),
        }
        return frame

    unchanged = pd.DataFrame(
        {"is_signal": [True], "holding": ["executed-yesterday"]}, index=[date]
    )
    unchanged.attrs["v78_adk_v77"] = component("A/B", "A/B")
    unchanged.attrs["v78_adk_new"] = component("C/D", "C/D")

    changed = unchanged.copy()
    changed.attrs["v78_adk_v77"] = component("A/B", "A/C")
    changed.attrs["v78_adk_new"] = unchanged.attrs["v78_adk_new"]

    unchanged_rows = module._v78_adk_close_target_change_rows(unchanged, -1)
    changed_rows = module._v78_adk_close_target_change_rows(changed, -1)

    assert not any(row["changed"] for row in unchanged_rows)
    assert any(row["changed"] for row in changed_rows)


def test_signal_handler_uses_unshifted_adk_close_targets():
    module = load_v79_module()
    source = inspect.getsource(module.CombinedStrategyV78._handle_signal)
    live_source = inspect.getsource(module.CombinedStrategyV78._handle_live_signal)

    assert "_v78_adk_close_target_change_rows" in source
    assert "_v78_adk_close_target_change_rows" in live_source


def test_suba_pre_trade_text_reads_the_current_during_day_row():
    module = load_v79_module()
    dates = pd.to_datetime(["2026-06-10", "2026-06-11", "2026-06-12"])
    result = pd.DataFrame(
        {
            "v78_suba_v77_holding": ["A", "B", "C"],
            "v78_suba_v77_weight": [0.4, 0.8, 1.2],
            "v78_suba_new_holding": ["X", "Y", "Z"],
            "v78_suba_new_weight": [0.2, 0.4, 0.6],
            "is_signal": [False, False, True],
        },
        index=dates,
    )

    text = module._v78_suba_pre_trade_position_text(result, 2)

    assert "C" in text
    assert "Z" in text
    assert "V7.7A: B" not in text


def test_suba_blend_shifts_v77_scale_raw_with_during_day_weight():
    module = load_v79_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    v77 = pd.DataFrame(
        {
            "return": [0.0, 0.0],
            "holding": ["A", "B"],
            "weight": [0.8, 1.2],
            "scale_raw": [0.9, 1.3],
            "is_signal": [False, True],
        },
        index=dates,
    )
    new = pd.DataFrame(
        {
            "return": [0.0, 0.0],
            "holding": ["A", "A"],
            "target": ["A", "A"],
            "weight": [0.4, 0.4],
            "target_weight": [0.4, 0.4],
            "scale_raw": [0.5, 0.6],
            "is_signal": [False, False],
        },
        index=dates,
    )

    blend = module.blend_v78_suba_results(v77, new)

    assert blend.loc[dates[1], "v78_suba_v77_scale_raw"] == pytest.approx(0.9)
    assert blend.loc[dates[1], "v78_suba_new_scale_raw"] == pytest.approx(0.6)


def test_intraday_current_state_always_uses_latest_during_day_row():
    module = load_v79_module()
    signal_source = inspect.getsource(module.CombinedStrategyV78._handle_signal)
    live_source = inspect.getsource(module.CombinedStrategyV78._handle_live_signal)
    params_source = inspect.getsource(module.CombinedStrategyV78._handle_live_params)

    assert "_cn_display_idx = -1" in signal_source
    assert "_dk_signal_current_idx = -1" in signal_source
    assert "_dk_effective_idx3 = -1" in live_source
    assert "_cn_display_idx_lp = -1" in params_source
    assert "_dk_display_idx_lp = -1" in params_source


def test_live_signal_renders_current_adk_net_exposure_before_close_target():
    module = load_v79_module()
    source = inspect.getsource(module.CombinedStrategyV78._handle_live_signal)
    block = source.split("# ── DK vol-scaling 杠杆显示 (实时) ──", 1)[1].split(
        'w("\\n---\\n\\n")', 1
    )[0]
    blend_branch = block.index('if "v78_adk_final_exposure" in cn_dk_result.columns:')
    net_table = block.index(
        "_write_v78_adk_net_exposure_table(w, cn_dk_result, _dk_effective_idx3)"
    )
    scale_heading = block.index('w("\\n**③ ADK双腿波动率缩放:**')

    assert blend_branch < net_table < scale_heading
    assert block.count('"v78_adk_final_exposure" in cn_dk_result.columns') == 1


def test_signal_history_end_position_uses_post_close_target_semantics():
    module = load_v79_module()
    source = inspect.getsource(module.CombinedStrategyV78._handle_signal_history)

    assert source.count(
        "_v78_suba_position_text(cn_period.iloc[-1], mode='target')"
    ) == 2


def test_adk_execution_chain_explains_zero_new_leg_and_final_change_state():
    module = load_v79_module()
    dates = pd.to_datetime(["2026-06-11", "2026-06-12"])
    pair = "HS300/ZZ500"

    def component(*, new_leg=False, live_score=90.0):
        frame = pd.DataFrame(
            {
                "top_pair": [pair, pair],
                "direction": [1, 0 if new_leg else 1],
                "weight": [1.0, 0.0 if new_leg else 1.0],
                "scale_raw": [1.0, 1.0],
                "realized_vol": [0.14, 0.14],
            },
            index=dates,
        )
        if new_leg:
            frame["base_weight_before_v78_score_hot"] = 1.0
            frame["v78_score_overheat_scale"] = [1.0, 0.0]
            frame["v78_score_overheat_on"] = [False, True]
            frame["v78_score_overheat_score"] = [90.0, live_score]
        else:
            frame["pre_overheat_weight"] = 1.0
            frame["same_side_overheat_scale"] = 1.0
            frame["same_side_overheat_on"] = False
        frame.attrs["signals_df"] = pd.DataFrame({pair: [90.0, 90.0]}, index=dates)
        frame.attrs["pair_data"] = {
            pair: pd.DataFrame(
                {
                    "position": [1, 1],
                    "signal": [1, 1],
                    "scale": [1.0, 1.0],
                    "realized_vol": [0.14, 0.14],
                },
                index=dates,
            )
        }
        return frame

    blend = pd.DataFrame(
        {
            "v78_adk_final_exposure": [1.0, 0.5],
            "adk_net_asset_exposure": [{}, {"HS300": 0.5, "ZZ500": -0.5}],
        },
        index=dates,
    )
    blend.attrs["v78_adk_v77"] = component()
    blend.attrs["v78_adk_new"] = component(new_leg=True, live_score=90.0)

    summary = module._v79_adk_execution_summary(blend, -1)
    new_row = summary["rows"][1]
    chunks = []
    module._write_v79_adk_execution_chain(chunks.append, blend, -1)
    text = "".join(chunks)

    assert new_row["current_base_pair"] == pair
    assert new_row["current_base_direction"] == 1
    assert new_row["current_final_text"] == "空仓 / 0.00x"
    assert "基础信号并未空仓" in new_row["current_overlay_text"]
    assert "score-hot已触发" in new_row["current_overlay_text"]
    assert summary["changed"] is False
    assert "最终执行仓位不变化" in text

    rank_chunks = []
    module._write_v78_adk_leg_rank_tables(rank_chunks.append, blend, -1, use_shifted=False)
    rank_text = "".join(rank_chunks)
    new_rank_block = rank_text.split(module.V78_ADK_NEW_LABEL, 1)[1]

    assert "实时基础Top-3" in rank_text
    assert "这里只展示若现在收盘的基础排名，不等于最终执行" in rank_text
    assert "score-hot开启" in new_rank_block
    assert "过滤后最终为空仓" in new_rank_block
    assert "不会执行该配对" in new_rank_block
    assert "← 若现在收盘将执行" not in rank_text

    blend.attrs["v78_adk_new"] = component(new_leg=True, live_score=10.0)
    recovered = module._v79_adk_execution_summary(blend, -1)

    assert recovered["rows"][1]["target_weight"] == pytest.approx(1.0)
    assert recovered["rows"][1]["changed"] is True
    assert recovered["changed"] is True


def test_adk_query_surfaces_use_final_execution_change_chain():
    module = load_v79_module()
    signal_source = inspect.getsource(module.CombinedStrategyV78._handle_signal)
    live_source = inspect.getsource(module.CombinedStrategyV78._handle_live_signal)
    params_source = inspect.getsource(module.CombinedStrategyV78._handle_params)
    live_params_source = inspect.getsource(module.CombinedStrategyV78._handle_live_params)

    assert "_write_v79_adk_execution_chain" in signal_source
    assert "_write_v79_adk_execution_chain" in live_source
    assert "_write_v79_adk_execution_chain" in params_source
    assert "_write_v79_adk_execution_chain" in live_params_source
    assert "变化判断同时比较配对、方向、VolScale和覆盖层后的最终腿内敞口" in signal_source

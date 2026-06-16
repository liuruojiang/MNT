import importlib.util
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


def test_v78_adk_status_rows_include_v77_and_new_adk_legs():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-12"])
    v77 = pd.DataFrame(
        {"top_pair": ["ZZ1000/SZ50"], "direction": [1], "weight": [0.8]},
        index=dates,
    )
    v77.attrs["signals_df"] = pd.DataFrame({"ZZ1000/SZ50": [55.0]}, index=dates)
    new = pd.DataFrame(
        {
            "top_pair": ["ZZ500/CYB"],
            "direction": [-1],
            "weight": [0.0],
            "v78_score_overheat_score": [92.0],
            "v78_score_overheat_scale": [0.0],
            "v78_score_overheat_on": [True],
        },
        index=dates,
    )
    new.attrs["signals_df"] = pd.DataFrame({"ZZ500/CYB": [92.0]}, index=dates)
    blended = pd.DataFrame({"v78_adk_v77_holding": ["ZZ1000/SZ50_1"]}, index=dates)
    blended.attrs["v78_adk_v77"] = v77
    blended.attrs["v78_adk_new"] = new

    rows = module._v78_adk_leg_status_rows(blended, 0)

    assert [row["leg"] for row in rows] == ["V7.7 ADK", module.V78_ADK_NEW_LABEL]
    assert rows[0]["pair"] == "ZZ1000/SZ50"
    assert rows[0]["score"] == 55.0
    assert rows[1]["pair"] == "ZZ500/CYB"
    assert rows[1]["score"] == 92.0
    assert rows[1]["score_hot_on"] is True
    assert rows[1]["leg_contribution"] == 0.0


def test_v78_subb_four_leg_rows_expand_nested_v77_components():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-12"])
    v77 = pd.DataFrame(
        {
            "official_w_QQQ": [0.60],
            "official_contrib_w_QQQ": [0.30],
            "ema_w_QQQ": [0.40],
            "ema_contrib_w_QQQ": [0.20],
            "w_QQQ": [0.50],
        },
        index=dates,
    )
    bias = pd.DataFrame({"w_QQQ": [0.20]}, index=dates)
    logvol = pd.DataFrame({"w_QQQ": [0.10]}, index=dates)
    blended = pd.DataFrame({"w_QQQ": [0.30]}, index=dates)
    blended.attrs["v78_subb_v77"] = v77
    blended.attrs["v78_subb_bias"] = bias
    blended.attrs["v78_subb_logvol"] = logvol

    rows = module._v78_subb_four_leg_weight_rows(blended, 0)

    assert rows == [
        {
            "asset": "QQQ",
            "live_name": "QQQM",
            "official_contrib": 0.15,
            "ema_contrib": 0.10,
            "bias_contrib": 0.05,
            "logvol_contrib": 0.025,
            "final_weight": 0.325,
        }
    ]


def test_v78_subb_blend_targets_use_leg_targets_not_current_holdings():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-12"])
    v77 = pd.DataFrame(
        {
            "return": [0.0],
            "w_QQQ": [0.10],
            "actual_w_QQQ": [0.10],
            "target_w_QQQ": [0.50],
            "official_w_QQQ": [0.60],
            "official_contrib_w_QQQ": [0.30],
            "ema_w_QQQ": [0.40],
            "ema_contrib_w_QQQ": [0.20],
            "is_signal": [True],
            "rebalanced": [False],
        },
        index=dates,
    )
    bias = pd.DataFrame(
        {
            "return": [0.0],
            "w_QQQ": [0.00],
            "actual_w_QQQ": [0.00],
            "target_w_QQQ": [0.40],
            "is_signal": [True],
            "rebalanced": [True],
        },
        index=dates,
    )
    logvol = pd.DataFrame(
        {
            "return": [0.0],
            "w_QQQ": [0.00],
            "actual_w_QQQ": [0.00],
            "target_w_QQQ": [0.20],
            "is_signal": [True],
            "rebalanced": [True],
        },
        index=dates,
    )

    blended = module.blend_v78_subb_results(v77, bias, logvol)
    rows = module._v78_subb_four_leg_weight_rows(blended, dates[0])
    signal_weights = module._subb_signal_display_source_weights(blended, dates[0], ["w_QQQ"])

    assert round(float(blended.loc[dates[0], "actual_w_QQQ"]), 10) == 0.05
    assert round(float(blended.loc[dates[0], "target_w_QQQ"]), 10) == 0.40
    assert bool(blended.loc[dates[0], "rebalanced"]) is True
    assert round(signal_weights["QQQ"], 10) == 0.40
    assert round(rows[0]["official_contrib"], 10) == 0.15
    assert round(rows[0]["ema_contrib"], 10) == 0.10
    assert round(rows[0]["bias_contrib"], 10) == 0.10
    assert round(rows[0]["logvol_contrib"], 10) == 0.05
    assert round(rows[0]["final_weight"], 10) == 0.40


def test_v78_subb_hypothetical_weights_blend_all_four_legs():
    module = load_v78_module()

    weights = module._blend_v78_subb_weight_dicts(
        {"QQQ": 0.50},
        {"PDBC": 0.40},
        {"GLD": 0.20},
    )

    assert weights == {"GLD": 0.05, "PDBC": 0.10, "QQQ": 0.25}


def test_subb_rebalance_extract_since_date_uses_previous_row_as_baseline():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-05-01", "2026-06-12"])
    result = pd.DataFrame(
        {
            "rebalanced": [False, True],
            "target_w_QQQ": [0.25, 0.40],
            "target_w_GLD": [0.75, 0.60],
            "actual_w_QQQ": [0.25, 0.25],
            "actual_w_GLD": [0.75, 0.75],
        },
        index=dates,
    )

    records = module.extract_us_rot_rebalances(result, since_date=pd.Timestamp("2026-06-01"))

    assert len(records) == 1
    assert records[0]["日期"] == "2026-06-12"
    assert "QQQM 25.0%->40.0%" in records[0]["买入"]
    assert "GLDM 75.0%->60.0%" in records[0]["卖出"]


def test_subb_volreg_extract_since_date_uses_previous_row_as_baseline():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-05-01", "2026-06-12"])
    result = pd.DataFrame(
        {
            "volreg_transition": [False, True],
            "effective_w_QQQ": [0.50, 0.0],
            "effective_w_GLD": [0.50, 0.0],
            "effective_w_BIL": [0.0, 1.0],
            "w_QQQ": [0.50, 0.50],
            "w_GLD": [0.50, 0.50],
            "w_BIL": [0.0, 0.0],
        },
        index=dates,
    )

    records = module.extract_subb_volreg_rebalances(result, since_date=pd.Timestamp("2026-06-01"))

    assert len(records) == 1
    assert records[0]["日期"] == "2026-06-12"
    assert "QQQM 50.0%->0.0%" in records[0]["卖出"]
    assert "GLDM 50.0%->0.0%" in records[0]["卖出"]


def test_v78_subb_component_leg_tables_show_each_leg_without_legacy_hypothetical_block():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-12"])
    v77 = pd.DataFrame(
        {
            "official_w_QQQ": [0.60],
            "official_contrib_w_QQQ": [0.30],
            "ema_w_QQQ": [0.40],
            "ema_contrib_w_QQQ": [0.20],
            "w_QQQ": [0.50],
        },
        index=dates,
    )
    bias = pd.DataFrame({"w_PDBC": [0.44]}, index=dates)
    logvol = pd.DataFrame({"w_GLDM": [0.30]}, index=dates)
    blended = pd.DataFrame({"w_QQQ": [0.25], "w_PDBC": [0.11], "w_GLDM": [0.075]}, index=dates)
    blended.attrs["v78_subb_v77"] = v77
    blended.attrs["v78_subb_bias"] = bias
    blended.attrs["v78_subb_logvol"] = logvol
    chunks = []

    module._write_v78_subb_component_leg_tables(chunks.append, blended, 0)
    text = "".join(chunks)

    assert "**EMA腿（25%）**" in text
    assert "**Bias腿（25%）**" in text
    assert "**LogVol腿（25%）**" in text
    assert "QQQM" in text
    assert "PDBC" in text
    assert "GLDM" in text
    assert "假设收盘信号" not in text


def test_v78_subb_leg_tables_accept_signal_date_index():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-12"])
    v77 = pd.DataFrame(
        {
            "official_w_QQQ": [0.60],
            "official_contrib_w_QQQ": [0.30],
            "ema_w_QQQ": [0.40],
            "ema_contrib_w_QQQ": [0.20],
            "w_QQQ": [0.50],
        },
        index=dates,
    )
    bias = pd.DataFrame({"w_PDBC": [0.44]}, index=dates)
    logvol = pd.DataFrame({"w_GLDM": [0.30]}, index=dates)
    blended = pd.DataFrame({"w_QQQ": [0.25], "w_PDBC": [0.11], "w_GLDM": [0.075]}, index=dates)
    blended.attrs["v78_subb_v77"] = v77
    blended.attrs["v78_subb_bias"] = bias
    blended.attrs["v78_subb_logvol"] = logvol
    chunks = []

    module._write_v78_subb_component_leg_tables(chunks.append, blended, dates[0])
    module._write_v78_subb_blend_table(chunks.append, blended, dates[0])
    text = "".join(chunks)

    assert "QQQM" in text
    assert "PDBC" in text
    assert "GLDM" in text


def test_v78_subb_current_vs_hypothetical_table_compares_actual_and_today_target():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-07-02"])
    blended = pd.DataFrame(
        {
            "v78_subb_v77_return": [0.0],
            "actual_w_PDBC": [0.50],
            "actual_w_QQQ": [0.30],
            "actual_w_EMXC": [0.20],
            "target_w_PDBC": [0.447],
            "target_w_QQQ": [0.381],
            "target_w_EMXC": [0.193],
            "target_w_GLD": [0.010],
        },
        index=dates,
    )
    chunks = []

    module._write_v78_subb_current_vs_hypothetical_table(chunks.append, blended, 0)
    text = "".join(chunks)

    assert "**V7.8 Sub-B 当前持有 vs 假设今日调仓**" in text
    assert "| PDBC | 50.0% | **44.7%** | -5.3% |" in text
    assert "| QQQM | 30.0% | **38.1%** | +8.1% |" in text
    assert "| GLDM | 0.0% | **1.0%** | +1.0% |" in text
    assert "假设今日是Sub-B调仓日" in text


def test_v78_subb_param_tables_list_each_leg_separately():
    module = load_v78_module()
    chunks = []

    module._write_v78_subb_param_tables(chunks.append)
    text = "".join(chunks)

    assert "**全局执行口径**" in text
    assert "**官方腿参数**" in text
    assert "**EMA腿参数**" in text
    assert "**Bias腿参数**" in text
    assert "**LogVol腿参数**" in text
    assert "hl100 / 16%" in text
    assert "ewma6m_1vol" in text
    assert "price/MA160,260,390 = 3/2/1加权" in text
    assert "25% / 40日 / max1.5x" in text
    assert "log return 120/200/320 = 60%/30%/10%" in text
    assert "30% / 40日 / max1.25x" in text
    assert "SPY量/MA60≥1.5 -> QQQ/EMXC/EFA ×0.75" in text
    assert "rv≥50% -> 本腿收益×0.75" in text
    assert "| 官方腿 |" not in text
    assert "| EMA腿 |" not in text
    assert "| Bias腿 |" not in text
    assert "| LogVol腿 |" not in text


def test_v78_suba_param_tables_list_each_leg_separately():
    module = load_v78_module()
    chunks = []

    module._write_v78_suba_param_tables(chunks.append)
    text = "".join(chunks)

    assert "**全局执行口径**" in text
    assert "**V7.7A原版参数**" in text
    assert "**New A TV1.0参数**" in text
    assert "**Sub-A风控与执行参数**" in text
    assert "V7.8 Sub-A混合方式" not in text


def test_v78_adk_param_tables_list_each_leg_separately():
    module = load_v78_module()
    chunks = []

    module._write_v78_adk_param_tables(chunks.append)
    text = "".join(chunks)

    assert "**全局执行口径**" in text
    assert "**V7.7 ADK参数**" in text
    assert "**New ADK all10 score-hot参数**" in text
    assert "**ADK风控与执行参数**" in text
    assert "V7.8 ADK混合方式" not in text


def test_v78_live_params_source_uses_v78_section_headers_not_legacy_single_leg_labels():
    root = Path(__file__).resolve().parents[1]
    source = (root / "mnt_bot V 7.8 plus.py").read_text(encoding="utf-8")
    live_params = source.split("def _handle_live_params", 1)[1].split("def _handle_signal_history", 1)[0]

    assert "### Sub-A: V7.8双腿综合" in live_params
    assert "V7.8 Sub-A双腿实时状态" in live_params
    assert "V7.8 ADK双腿实时状态" in live_params
    assert "官方腿分窗口动量排名" in live_params
    assert "Sub-A 乖离动量排序" not in live_params
    assert "多配对Top-1状态" not in live_params


def test_v78_live_signal_adk_does_not_duplicate_legacy_single_leg_top3():
    root = Path(__file__).resolve().parents[1]
    source = (root / "mnt_bot V 7.8 plus.py").read_text(encoding="utf-8")
    live_signal = source.split("def _handle_live_signal", 1)[1].split("def _handle_params", 1)[0]

    assert "实时Top-3（若现在收盘，用于判断是否按收盘价执行；策略实际只持有Top-1）" not in live_signal
    assert "若现在收盘的Top-1配对/方向" not in live_signal
    assert "_write_v78_adk_new_leg_then_summary" in live_signal


def _synthetic_subb_close_with_macro_winners(module, periods=460):
    index = pd.bdate_range("2024-01-02", periods=periods)
    close = pd.DataFrame(index=index)
    t = np.arange(periods)
    for i, code in enumerate(module.US_ROT_POOL):
        close[code] = 100.0 * np.exp((0.00005 + i * 0.000001) * t + 0.01 * np.sin(t / (5.0 + i)))
    close["UUP"] = 100.0 * np.exp(0.0018 * t + 0.012 * np.sin(t / 5.0))
    close["DBMF"] = 100.0 * np.exp(0.0020 * t + 0.012 * np.sin(t / 6.0))
    close["KMLM"] = 100.0 * np.exp(0.0019 * t + 0.012 * np.sin(t / 7.0))
    close["DBC"] = 100.0 * np.exp(-0.0007 * t + 0.011 * np.sin(t / 5.5))
    close["TLT"] = 100.0 * np.exp(0.0008 * t + 0.010 * np.sin(t / 6.5))
    close["BIL"] = 100.0 * np.exp(0.00002 * t)
    close["SPY"] = 100.0 * np.exp(0.0004 * t + 0.009 * np.sin(t / 6.0))
    return close


def test_v78_subb_hypothetical_new_leg_weights_read_component_result_attrs():
    module = load_v78_module()
    close = _synthetic_subb_close_with_macro_winners(module)
    dates = close.index
    bias_component = pd.DataFrame(
        {"target_vol_scale": [1.23], "volume_scale_next": [0.75]},
        index=[dates[-1]],
    )
    blended = pd.DataFrame(index=[dates[-1]])
    blended.attrs["v78_subb_bias"] = bias_component

    direct = module._v78_subb_new_line_hypo_weights(close, bias_component, line="bias", row_idx=-1)
    via_attrs = module._v78_subb_new_line_hypo_weights_from_blend(close, blended, line="bias", row_idx=-1)

    assert via_attrs == direct


def test_v78_subb_inflation_note_covers_all_four_legs():
    module = load_v78_module()

    note = module._v78_subb_inflation_participation_note()

    assert "官方腿：通胀开关ON才纳入UUP/DBMF/KMLM" in note
    assert "EMA腿/Bias腿/LogVol腿：始终US_ROT_POOL全池参与排名" in note
    assert "UUP/DBMF/KMLM" in note


def test_v78_subb_default_rule_text_matches_macro_pool_scan_decision():
    module = load_v78_module()

    text = module._v78_subb_default_rule_text()

    assert "官方腿25%" in text
    assert "通胀开关ON才纳入UUP/DBMF/KMLM" in text
    assert "EMA腿25%" in text
    assert "Bias腿25%" in text
    assert "LogVol腿25%" in text
    assert "EMA腿/Bias腿/LogVol腿：始终US_ROT_POOL全池参与排名" in text


def test_v78_subb_inflation_status_text_uses_green_red_markers():
    module = load_v78_module()

    on_text = module._v78_subb_inflation_status_text(True)
    off_text = module._v78_subb_inflation_status_text(False)

    assert "🟢 官方腿宏观池开启" in on_text
    assert "🔴 官方腿宏观池关闭" in off_text
    assert "🟢 EMA/Bias/LogVol全池开启" in on_text
    assert "🟢 EMA/Bias/LogVol全池开启" in off_text


def test_v78_subb_window_lbs_are_safe_for_display_if_global_is_polluted():
    module = load_v78_module()
    original = module.US_ROT_LBS
    try:
        module.US_ROT_LBS = pd.DataFrame({"x": [160, 260, 390]})
        assert module._subb_window_lbs_for_display() == (160, 260, 390)
        assert "160/260/390" in module._v78_subb_default_rule_text()
    finally:
        module.US_ROT_LBS = original


def test_v78_subb_bias_and_logvol_macro_assets_stay_in_full_pool_when_inflation_gate_off():
    module = load_v78_module()
    close = _synthetic_subb_close_with_macro_winners(module)
    module._v78_spy_volume_gate = lambda index: (pd.Series(False, index=index), "test volume")

    assert module._subb_active_ranking_codes(close, -1) == module.US_ROT_BASE_POOL

    bias = module.run_v78_subb_new_line(close, line="bias")
    logvol = module.run_v78_subb_new_line(close, line="logvol")

    for result in (bias, logvol):
        signal_rows = result[result["is_signal"]]
        assert not signal_rows.empty
        last_signal = signal_rows.iloc[-1]
        assert last_signal["target_w_DBMF"] > 0
        assert last_signal["target_w_KMLM"] > 0
        assert last_signal["target_w_UUP"] > 0


def test_v78_adk_rank_rows_are_built_per_leg_not_from_blended_v77_only():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-12"])
    v77 = pd.DataFrame({"top_pair": ["SZ50/CYB"], "direction": [1]}, index=dates)
    v77.attrs["signals_df"] = pd.DataFrame(
        {"SZ50/CYB": [44.0], "HS300/CYB": [34.0], "SZ50/ZZ1000": [28.0]},
        index=dates,
    )
    new = pd.DataFrame({"top_pair": ["HS300/ZZ500"], "direction": [-1]}, index=dates)
    new.attrs["signals_df"] = pd.DataFrame(
        {"HS300/ZZ500": [99.0], "SZ50/CYB": [44.0], "HS300/CYB": [34.0]},
        index=dates,
    )
    blended = pd.DataFrame({"top_pair": ["SZ50/CYB"], "direction": [1]}, index=dates)
    blended.attrs["v78_adk_v77"] = v77
    blended.attrs["v78_adk_new"] = new

    sections = module._v78_adk_leg_rank_sections(blended, 0, use_shifted=False, top_n=3)

    assert sections[0]["leg"] == "V7.7 ADK"
    assert sections[0]["rows"][0]["pair"] == "SZ50/CYB"
    assert sections[1]["leg"] == module.V78_ADK_NEW_LABEL
    assert sections[1]["rows"][0]["pair"] == "HS300/ZZ500"


def test_v78_adk_display_uses_unified_two_leg_status_and_rank_sections():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-12"])
    v77 = pd.DataFrame({"top_pair": ["SZ50/CYB"], "direction": [1], "weight": [0.6]}, index=dates)
    v77.attrs["signals_df"] = pd.DataFrame(
        {"SZ50/CYB": [44.0], "HS300/CYB": [34.0], "SZ50/ZZ1000": [28.0]},
        index=dates,
    )
    new = pd.DataFrame(
        {
            "top_pair": ["HS300/ZZ500"],
            "direction": [-1],
            "weight": [0.4],
            "v78_score_overheat_scale": [1.0],
            "v78_score_overheat_on": [False],
        },
        index=dates,
    )
    new.attrs["signals_df"] = pd.DataFrame(
        {"HS300/ZZ500": [99.0], "SZ50/CYB": [44.0], "HS300/CYB": [34.0]},
        index=dates,
    )
    blended = pd.DataFrame(
        {
            "v78_adk_v77_holding": ["SZ50/CYB_1"],
            "v78_adk_new_holding": ["HS300/ZZ500_-1"],
            "v78_adk_v77_weight": [0.6],
            "v78_adk_new_weight": [0.4],
            "v78_adk_final_exposure": [0.5],
        },
        index=dates,
    )
    blended.attrs["v78_adk_v77"] = v77
    blended.attrs["v78_adk_new"] = new
    chunks = []

    module._write_v78_adk_new_leg_then_summary(chunks.append, blended, 0, use_shifted=False)
    text = "".join(chunks)

    assert "**V7.8 ADK 混合腿拆分（沿用7.7展示样式）**" in text
    assert "**V7.8 ADK 子策略状态**" in text
    assert "| 腿 | 配对范围 | Top-1配对/方向 | 排名分数 | 质量过滤 | 风控/过滤 | 腿内敞口 | 组合贡献 |" in text
    assert "| V7.7 ADK | 正式8配对 | 做多 上证50 / 做空 创业板 | `44.00` | R²质控" in text
    assert f"| {module.V78_ADK_NEW_LABEL} | 全10配对 + score-hot | 做多 中证500 / 做空 沪深300 | `99.00`" in text
    assert "**V7.8 ADK 两个子策略Top-3" in text
    assert "V7.7 ADK（正式8配对） 实时Top-3" in text
    assert "New ADK all10 score-hot（全10配对 + score-hot） 实时Top-3" in text
    assert "- 1. **上证50/创业板** | 实时分数 `44.00` | 方向 +1" in text
    assert "- 1. **沪深300/中证500** | 实时分数 `99.00` | 方向 -1" in text
    assert "← 若现在收盘将执行" in text


def test_v78_adk_summary_labels_position_context():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-16"])
    v77 = pd.DataFrame({"top_pair": ["SZ50/CYB"], "direction": [1], "weight": [0.6]}, index=dates)
    v77.attrs["signals_df"] = pd.DataFrame({"SZ50/CYB": [44.0]}, index=dates)
    new = pd.DataFrame(
        {
            "top_pair": ["HS300/ZZ500"],
            "direction": [-1],
            "weight": [0.4],
            "v78_score_overheat_scale": [1.0],
            "v78_score_overheat_on": [False],
        },
        index=dates,
    )
    new.attrs["signals_df"] = pd.DataFrame({"HS300/ZZ500": [99.0]}, index=dates)
    blended = pd.DataFrame(
        {
            "v78_adk_v77_holding": ["SZ50/CYB_1"],
            "v78_adk_new_holding": ["HS300/ZZ500_-1"],
            "v78_adk_v77_weight": [0.6],
            "v78_adk_new_weight": [0.4],
            "v78_adk_final_exposure": [0.5],
        },
        index=dates,
    )
    blended.attrs["v78_adk_v77"] = v77
    blended.attrs["v78_adk_new"] = new
    chunks = []

    module._write_v78_adk_new_leg_then_summary(
        chunks.append,
        blended,
        0,
        use_shifted=False,
        position_context="若现在收盘目标（非当前正式持仓）",
    )
    text = "".join(chunks)

    assert "**ADK持仓口径:** **若现在收盘目标（非当前正式持仓）**" in text
    assert "当前正式持仓以上方“当前已生效Top-1”为准" in text
    assert "| 腿 | 组合权重 | 若现在收盘配对/方向 | 腿内敞口 | 组合贡献 |" in text
    assert "| 腿 | 配对范围 | 若现在收盘Top-1配对/方向 | 排名分数 | 质量过滤 | 风控/过滤 | 腿内敞口 | 组合贡献 |" in text


def test_v78_adk_current_holding_summary_shows_composite_and_legs():
    module = load_v78_module()
    dates = pd.to_datetime(["2026-06-16"])
    blended = pd.DataFrame(
        {
            "holding": ["SZ50/CYB_1"],
            "top_pair": ["SZ50/CYB"],
            "direction": [1],
            "weight": [0.53],
            "v78_adk_v77_holding": ["SZ50/CYB_1"],
            "v78_adk_new_holding": ["HS300/ZZ500_-1"],
            "v78_adk_v77_weight": [0.53],
            "v78_adk_new_weight": [0.40],
            "v78_adk_final_exposure": [0.465],
        },
        index=dates,
    )
    chunks = []

    module._write_v78_adk_current_holding_summary(chunks.append, blended, 0)
    text = "".join(chunks)

    assert "**ADK当前已生效持仓:** **做多 上证50 / 做空 创业板**" in text
    assert "综合Top-1配对/方向: **上证50/创业板** | 方向 +1" in text
    assert "V7.7 ADK原版: 做多 上证50 / 做空 创业板" in text
    assert "New ADK all10 score-hot: 做多 中证500 / 做空 沪深300" in text
    assert "当前已生效总敞口: **0.53x**" in text

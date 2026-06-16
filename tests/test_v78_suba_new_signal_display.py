import importlib.util
from pathlib import Path

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

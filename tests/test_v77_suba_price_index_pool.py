import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "mnt_bot V 7.7 plus.py"


def load_v77_module():
    spec = importlib.util.spec_from_file_location("mnt_v77_plus", str(MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_suba_equity_pool_uses_price_indices_and_total_return_bond():
    mod = load_v77_module()

    assert mod.CN_EQUITY_CODES == [
        "1.930955",
        "0.399006",
        "1.000016",
        "1.000852",
        "1.000905",
    ]
    assert mod.CN_STOCK_CODES == mod.CN_EQUITY_CODES
    assert mod.CN_BOND_CODE == "1.H11077"
    assert mod.CN_NAMES["1.930955"] == "中证红利低波100"


def test_h20955_does_not_fall_back_to_different_h30269_index():
    mod = load_v77_module()

    assert "H30269" not in mod.CN_CSINDEX_CANDIDATES.get("H20955", ["H20955"])


def test_subb_max_leverage_is_reduced_to_one_point_five():
    mod = load_v77_module()

    assert mod.US_ROT_MAX_LEV == 1.5
    assert mod.US_ROT_FUTURES == {"QQQM", "GLDM"}


def test_subb_bond_sleeve_uses_agg_directly():
    mod = load_v77_module()

    assert "AGG" in mod.US_ROT_BASE_ASSETS
    assert mod.US_ROT_BASE_ASSETS["AGG"]["proxy"] == "AGG"
    assert "AGG" in mod.US_ROT_POOL
    assert "TLT" not in mod.US_ROT_POOL
    assert "VGLT" not in mod.US_ROT_ASSETS
    assert "TLT" in mod.SUBB_INFLATION_GATE_TICKERS
    assert "TLT" in mod.SUBB_REQUIRED_PRICE_TICKERS


def test_930955_fetch_uses_csindex_price_index_branch(monkeypatch):
    mod = load_v77_module()
    dates = pd.bdate_range("2026-03-10", periods=60)
    expected = pd.DataFrame(
        {"close": [1000.0 + i for i in range(len(dates))]},
        index=dates,
    )
    calls = []

    def fake_csindex(index_code):
        calls.append(index_code)
        return expected

    def fail_third_party(secid):
        raise AssertionError(f"unexpected third-party fetch for {secid}")

    monkeypatch.setattr(mod, "_fetch_cn_csindex", fake_csindex)
    monkeypatch.setattr(mod, "_save_cn_official_cache", lambda secid, df: None)
    monkeypatch.setattr(mod, "_fetch_cn_eastmoney", fail_third_party)
    monkeypatch.setattr(mod, "_fetch_cn_sina", fail_third_party)

    result, source = mod.fetch_cn_kline("1.930955")

    assert calls == ["930955"]
    assert source == "csindex:930955"
    pd.testing.assert_frame_equal(result, expected)


def test_dk_rebalance_records_use_prior_close_execution_session(monkeypatch):
    mod = load_v77_module()
    dates = pd.to_datetime(["2026-05-28", "2026-05-29"])
    dk_result = pd.DataFrame(
        {
            "holding": ["none_0", "HS300/ZZ500_1"],
            "weight": [0.0, 1.0],
        },
        index=dates,
    )
    cn_dk_close = pd.DataFrame(
        {
            "DK_HS300": [4000.0, 4010.0],
            "DK_ZZ500": [6000.0, 6020.0],
        },
        index=dates,
    )

    monkeypatch.setattr(
        mod,
        "beijing_time_str",
        lambda date, market, session: f"{market}-{session}-{date:%Y-%m-%d}",
    )

    records = mod.extract_dk_rebalances(dk_result, cn_dk_close=cn_dk_close)

    assert records[0]["日期"] == "2026-05-28"
    assert records[0]["北京时间"] == "CN-close-2026-05-28"
    assert records[0]["买入价格"] == "HS300 4000.00; ZZ500 6000.00"


def test_adk_display_copy_does_not_describe_next_open_execution():
    source = MODULE_PATH.read_text(encoding="utf-8")
    ambiguous_lines = [
        line
        for line in source.splitlines()
        if ("ADK" in line or "Sub-A-DK" in line or "_dk_" in line)
        and "下一交易日开盘前执行" in line
    ]

    assert ambiguous_lines == []


def test_suba_single_asset_gate_keeps_v77_cash_until_asset_strategy_holds(monkeypatch):
    mod = load_v77_module()
    monkeypatch.setattr(mod, "CN_BIAS_N", 5)
    monkeypatch.setattr(mod, "CN_MOM_DAY", 3)
    monkeypatch.setattr(mod, "CN_R2_WINDOW", 3)
    monkeypatch.setattr(mod, "CN_R2_THRESHOLD", 0.0)
    monkeypatch.setattr(mod, "CN_ABS_MOM_DAY", 2)
    monkeypatch.setattr(mod, "CN_ABS_MOM_THRESHOLD", -1.0)
    monkeypatch.setattr(mod, "CN_TARGET_VOL", 0.30)
    monkeypatch.setattr(mod, "CN_VOL_WINDOW", 5)
    monkeypatch.setattr(mod, "CN_ENTRY_INITIAL_FRACTION", 1.0)
    monkeypatch.setattr(mod, "CN_SA_SAME_SIDE_OVERHEAT_ENABLED", False)
    monkeypatch.setattr(mod, "CN_SA_VOLUME_OVERLAY_ENABLED", False)

    dates = pd.bdate_range("2026-01-01", periods=35)
    prices = pd.Series([100.0 + i * i * 0.2 for i in range(len(dates))], index=dates)
    close = pd.DataFrame({"TEST": prices})
    gate = pd.Series(False, index=dates)
    gate.iloc[18:] = True

    result = mod.run_cn_strategy(close, ["TEST"], single_asset_signal_gate={"TEST": gate})

    assert result.loc[: gate.index[17], "holding"].eq("cash").all()
    assert result.loc[gate.index[18]:, "holding"].eq("TEST").any()
    assert bool(result.loc[gate.index[18]:, "suba_single_gate_blocked"].any()) is False

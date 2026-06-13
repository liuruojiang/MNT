import importlib.util
from pathlib import Path

import pandas as pd


def load_bot_module():
    path = Path(__file__).resolve().parents[1] / "poe_adk_16_spread_v1_0_bot.py"
    spec = importlib.util.spec_from_file_location("poe_adk_16_spread_v1_0_bot", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_score_strength_decay_state_uses_active_peak_and_warmup():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    signal_frame = pd.DataFrame(
        {
            "spread_close": [1.00, 1.01, 1.02, 1.03],
            "score": [100.0, 100.0, 100.0, 100.0],
            "score_strength": [10.0, 8.0, 2.0, 9.0],
            "raw_signal": [1.0, 1.0, 1.0, 1.0],
        },
        index=index,
    )
    meta = {
        "momentum_decay": {
            "enabled": True,
            "decay_threshold": 0.30,
            "recovery_threshold": 0.80,
            "warmup_days": 3,
            "scale": 0.25,
        }
    }

    states = bot._online_decay_state_frame(signal_frame, meta)

    assert states.loc[index[2], "ratio"] == 0.2
    assert states.loc[index[2], "gate"] == 1.0
    assert states.loc[index[2], "mult"] == 0.25
    assert states.loc[index[3], "ratio"] == 0.9
    assert states.loc[index[3], "gate"] == 0.0


def test_decay_detail_falls_back_to_score_strength_ratio():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    curve = pd.DataFrame(
        {
            "score": [100.0, 100.0, 100.0],
            "score_strength": [10.0, 8.0, 2.0],
            "raw_signal": [1.0, 1.0, 1.0],
            "decay_on": [0.0, 0.0, 1.0],
            "decay_mult": [1.0, 1.0, 0.25],
        },
        index=index,
    )
    meta = {
        "momentum_decay": {
            "enabled": True,
            "decay_threshold": 0.30,
            "recovery_threshold": 0.80,
            "warmup_days": 3,
            "scale": 0.25,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert "当前 0.200" in rows["动量衰减"]


def test_decay_detail_does_not_show_negative_ratio_when_inactive():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    curve = pd.DataFrame(
        {
            "score": [5.0, -1.0, -2.0],
            "raw_signal": [1.0, 0.0, 0.0],
            "decay_on": [0.0, 0.0, 0.0],
            "decay_mult": [1.0, 1.0, 1.0],
        },
        index=index,
    )
    meta = {
        "momentum_decay": {
            "enabled": True,
            "decay_threshold": 0.45,
            "recovery_threshold": 0.90,
            "warmup_days": 10,
            "scale": 0.0,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert "当前 N/A" in rows["动量衰减"]


def test_score_detail_fails_when_abs_momentum_fails():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=1, freq="D")
    curve = pd.DataFrame({"score": [62.835]}, index=index)
    meta = {
        "signal": {
            "score_threshold": 2.0,
            "abs_mom_day": 70,
            "abs_threshold": -0.07,
        }
    }
    probe = {"score": 62.835, "abs_mom": -0.1678}

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta, probe=probe))

    detail = rows["基础Score"]
    assert detail.startswith("未通过")
    assert "Score 62.835" in detail
    assert "AbsMom70 -16.78%" in detail


def test_post_close_exposure_uses_current_overlay_multiplier():
    bot = load_bot_module()
    index = pd.DatetimeIndex([pd.Timestamp("2026-06-12")])
    curve = pd.DataFrame(
        {
            "target": [1.0],
            "raw_signal": [1.0],
            "score": [13.643],
            "gross_exposure": [0.083878502614],
            "base_gross_exposure": [0.083878502614],
            "target_vol_scale": [1.0],
            "target_vol_raw_scale": [1.0],
            "vol_gate": [1.0],
            "vol_scale": [0.6229829145750044],
            "realized_vol": [0.2568288732430987],
        },
        index=index,
    )
    meta = {
        "signal": {"score_threshold": 1.0},
        "target_vol": {"enabled": True, "target_vol": 0.16, "target_vol_window": 20},
        "vol_overheat": {"enabled": True, "kind": "downonly_tv", "target_vol": 0.16, "window": 30},
    }

    snapshot = bot._strategy_signal_snapshot(bot.STRATEGIES[0], curve, meta, {"ok": True, "probes": {}}, live=True)

    assert "62.3%" in snapshot["exposure"]
    assert "收盘执行后 62.3%" in snapshot["formula"]
    assert "叠加 0.623" in snapshot["formula"]


def test_realtime_context_rebuilds_online_without_embedded_artifacts(tmp_path, monkeypatch):
    bot = load_bot_module()
    bot.OUTPUT_DIR = tmp_path / "missing_outputs"
    bot._EMBEDDED_ARTIFACT_CACHE = None

    index = pd.bdate_range("2025-01-01", periods=400)
    panel = pd.DataFrame(index=index)
    for offset, asset in enumerate(("zz1000", "hs300", "cyb", "sz50", "zz500"), start=1):
        panel[asset] = 1000.0 + offset * 100.0 + pd.Series(range(len(index)), index=index) * (offset + 1)
        panel[f"{asset}_amount"] = 1_000_000_000.0 + offset * 10_000_000.0
        panel[f"{asset}_volume"] = 10_000_000.0 + offset * 100_000.0
    panel.attrs["mode"] = "daily"

    def fake_fetch_online_price_panel(include_realtime=False):
        return panel, {"mode": "daily", "fetched_at": "2026-01-01 15:00:00"}

    monkeypatch.setattr(bot, "_fetch_online_price_panel", fake_fetch_online_price_panel)

    artifacts = bot._embedded_artifacts()
    curves, metas, online = bot.load_strategy_context(include_realtime=True)

    assert artifacts == {}
    assert online["ok"] is True
    assert online["data_mode"] == "online_rebuild_recent_realtime"
    assert set(curves) == {config.key for config in bot.STRATEGIES}
    assert set(metas) == {config.key for config in bot.STRATEGIES}
    assert "forward_zz1000_hs300" in curves
    assert not curves["forward_zz1000_hs300"].empty
    assert len(curves["forward_zz1000_hs300"]) < len(panel)


def test_realtime_context_does_not_full_history_rebuild(monkeypatch):
    bot = load_bot_module()
    index = pd.bdate_range("2025-01-01", periods=180)
    panel = pd.DataFrame(index=index)
    for offset, asset in enumerate(("zz1000", "hs300", "cyb", "sz50", "zz500"), start=1):
        panel[asset] = 1000.0 + offset * 100.0 + pd.Series(range(len(index)), index=index)
    panel.attrs["mode"] = "daily"
    calls = []

    monkeypatch.setattr(bot, "load_strategy_curves", lambda: {})
    monkeypatch.setattr(bot, "_fetch_online_price_panel", lambda include_realtime=False: (panel, {"mode": "daily"}))

    def fake_build(metas, panel, *, full_history=False):
        calls.append(full_history)
        return {
            config.key: pd.DataFrame({"gross_exposure": [0.0], "score": [1.0]}, index=[index[-1]])
            for config in bot.STRATEGIES
        }

    monkeypatch.setattr(bot, "_build_curves_from_online_prices", fake_build)
    monkeypatch.setattr(bot, "_live_probe_for_strategy", lambda config, meta, panel, seed_curve=None: {})

    _curves, _metas, online = bot.load_strategy_context(include_realtime=True)

    assert calls == [False]
    assert online["data_mode"] == "online_rebuild_recent_realtime"


def test_online_gate_uses_previous_row_state_for_execution_period():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    signal_frame = pd.DataFrame(
        {
            "spread_close": [1.0, 1.1],
            "score": [1.0, 100.0],
            "scorehot_gate": [0.0, 1.0],
            "amount_gate": [0.0, 1.0],
            "overheat_gate": [0.0, 1.0],
            "volhot_scale": [0.25, 0.25],
            "volhot_indicator": [0.10, 0.30],
        },
        index=index,
    )
    curve_so_far = pd.DataFrame(
        {
            "nav": [1.0],
            "base_nav": [1.0],
            "gross_exposure": [0.0],
            "base_gross_exposure": [0.0],
            "target_vol_scale": [1.0],
        },
        index=[index[0]],
    )
    row = signal_frame.loc[index[1]].to_dict()
    meta = {
        "signal": {"score_threshold": 0.0},
        "score_overheat": {"enabled": True, "threshold": 10.0, "scale": 0.0},
        "amount_overlay": {"enabled": True, "scale": 0.0},
        "vol_overheat": {"enabled": True, "threshold": 0.2, "scale": 0.0},
    }

    filled = bot._fill_online_execution_row(index[1], row, curve_so_far, meta, signal_frame)

    assert filled["gross_exposure"] == 1.0
    assert filled["scorehot_gate"] == 0.0
    assert filled["amount_gate"] == 0.0
    assert filled["overheat_gate"] == 0.0


def test_render_signal_returns_unavailable_message_when_curves_missing(monkeypatch):
    bot = load_bot_module()
    monkeypatch.setattr(
        bot,
        "load_strategy_context",
        lambda include_realtime=False: ({}, {}, {"ok": False, "error": "offline"}),
    )

    output = bot.render_signal(live=True)

    assert "offline" in output
    assert "KeyError" not in output


def test_realtime_params_do_not_load_strategy_context(monkeypatch):
    bot = load_bot_module()
    monkeypatch.setattr(bot, "load_strategy_metas", lambda: {config.key: {} for config in bot.STRATEGIES})

    def fail_load_strategy_context(include_realtime=False):
        raise AssertionError("params should not rebuild online context")

    monkeypatch.setattr(bot, "load_strategy_context", fail_load_strategy_context)

    assert "target-vol" in bot.render_params(live=True)


def test_default_signal_query_uses_realtime_path(monkeypatch):
    bot = load_bot_module()
    calls = []

    def fake_render_signal(live=False):
        calls.append(live)
        return f"live={live}"

    monkeypatch.setattr(bot, "render_signal", fake_render_signal)

    assert bot.render_query("信号") == "live=True"
    assert bot.render_query("") == "live=True"
    assert calls == [True, True]


def test_history_signal_query_routes_before_plain_signal(monkeypatch):
    bot = load_bot_module()

    monkeypatch.setattr(bot, "render_signal", lambda live=False: "plain")
    monkeypatch.setattr(bot, "render_signal_history", lambda query: "history")

    assert bot.render_query("历史信号") == "history"


def test_signal_history_uses_online_context_when_artifacts_are_missing(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    curves = {
        config.key: pd.DataFrame(
            {"gross_exposure": [0.0, 1.0], "score": [1.0, 2.0]},
            index=index,
        )
        for config in bot.STRATEGIES
    }
    metas = {config.key: {} for config in bot.STRATEGIES}
    calls = []

    def fake_load_strategy_context(include_realtime=False):
        calls.append(include_realtime)
        return curves, metas, {"ok": True, "data_mode": "online_rebuild_realtime"}

    def fail_load_strategy_curves():
        raise AssertionError("history should not use local artifacts directly")

    monkeypatch.setattr(bot, "load_strategy_context", fake_load_strategy_context)
    monkeypatch.setattr(bot, "load_strategy_curves", fail_load_strategy_curves)

    output = bot.render_signal_history("历史信号")

    assert calls == [True]
    assert "2026-01-02" in output


def test_fallback_meta_is_canonicalized_for_online_rebuild(monkeypatch):
    bot = load_bot_module()

    def missing_artifacts(filename):
        raise FileNotFoundError(filename)

    monkeypatch.setattr(bot, "_artifact_bytes", missing_artifacts)

    meta = bot.load_meta(next(config for config in bot.STRATEGIES if config.key == "reverse_zz1000_cyb"))

    assert meta["signal"]["bias_ma"] == 60
    assert meta["signal"]["abs_mom_day"] == 70
    assert meta["target_vol"]["target_vol_window"] == 60
    assert meta["volume_overlay"]["window"] == 60


def test_online_recent_rebuild_reuses_execution_fill(monkeypatch):
    bot = load_bot_module()
    config = bot.STRATEGIES[0]
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    signal_frame = pd.DataFrame(
        {
            "spread_close": [1.0, 1.1, 1.2],
            "score": [1.0, 1.0, 1.0],
        },
        index=index,
    )
    calls = []

    monkeypatch.setattr(bot, "STRATEGIES", [config])
    monkeypatch.setattr(bot, "STATE_SNAPSHOT", {})
    monkeypatch.setattr(bot, "_online_signal_frame_for_strategy", lambda config, meta, panel: signal_frame)

    def fake_fill(idx, row, curve_so_far, meta, signal_frame):
        calls.append((idx, len(curve_so_far)))
        row["gross_exposure"] = float(len(calls))
        row["return"] = 0.0
        row["nav"] = 1.0
        return row

    monkeypatch.setattr(bot, "_fill_online_execution_row", fake_fill)

    curves = bot._build_curves_from_online_prices({config.key: {"signal": {"score_threshold": 0.0}}}, pd.DataFrame(), full_history=False)

    assert calls == [(index[0], 0), (index[1], 1), (index[2], 2)]
    assert curves[config.key]["gross_exposure"].tolist() == [1.0, 2.0, 3.0]


def test_recent_rebuild_seeds_from_state_snapshot(monkeypatch):
    bot = load_bot_module()
    config = bot.STRATEGIES[0]
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    signal_frame = pd.DataFrame(
        {"spread_close": [1.0, 1.1, 1.2], "score": [1.0, 1.0, 1.0]},
        index=index,
    )

    monkeypatch.setattr(bot, "STRATEGIES", [config])
    monkeypatch.setattr(bot, "STATE_SNAPSHOT", {
        config.key: {
            "as_of": "2026-01-01",
            "values": {"nav": 2.0, "gross_exposure": 0.5, "base_gross_exposure": 0.5, "target_vol_scale": 0.7},
        }
    })
    monkeypatch.setattr(bot, "_online_signal_frame_for_strategy", lambda config, meta, panel: signal_frame)

    curves = bot._build_curves_from_online_prices({config.key: {"signal": {"score_threshold": 0.0}}}, pd.DataFrame(), full_history=False)
    curve = curves[config.key]

    assert curve.index[0] == index[0]
    assert curve.iloc[0]["nav"] == 2.0
    assert curve.iloc[0]["gross_exposure"] == 0.5


def test_snapshot_only_recent_rebuild_has_return_columns_for_combo(monkeypatch):
    bot = load_bot_module()
    seed_date = pd.Timestamp("2026-01-01")
    signal_frame = pd.DataFrame({"spread_close": [1.0], "score": [1.0]}, index=[seed_date])
    metas = {config.key: {"signal": {"score_threshold": 0.0}} for config in bot.STRATEGIES}
    snapshots = {
        config.key: {
            "as_of": seed_date.strftime("%Y-%m-%d"),
            "values": {"nav": 2.0, "gross_exposure": 0.5},
        }
        for config in bot.STRATEGIES
    }

    monkeypatch.setattr(bot, "STATE_SNAPSHOT", snapshots)
    monkeypatch.setattr(bot, "_online_signal_frame_for_strategy", lambda config, meta, panel: signal_frame)

    curves = bot._build_curves_from_online_prices(metas, pd.DataFrame(), full_history=False)
    combos = bot.build_combo_curves(curves)

    for curve in curves.values():
        assert curve.iloc[0][["return", "gross_return", "cost", "turnover"]].tolist() == [0.0, 0.0, 0.0, 0.0]
        assert curve.iloc[0]["nav_high"] == 2.0
        assert curve.iloc[0]["base_gross_exposure"] == 0.5
    assert combos["all_pair_equal_weight"].iloc[0]["return"] == 0.0


def test_downonly_tv_state_frame_is_not_pre_shifted(monkeypatch):
    bot = load_bot_module()
    config = bot.STRATEGIES[0]
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    panel = pd.DataFrame(
        {
            "zz1000": [100.0, 102.0, 101.0, 103.0],
            "hs300": [100.0, 100.0, 100.0, 100.0],
        },
        index=index,
    )
    monkeypatch.setattr(bot, "_downonly_tv_scale_from_realized_vol", lambda realized_vol, section: 0.25 if pd.notna(realized_vol) else float("nan"))
    meta = {
        "signal": {"bias_ma": 1, "mom_day": 1, "score_threshold": -999.0},
        "vol_overheat": {"enabled": True, "kind": "downonly_tv", "window": 2, "target_vol": 0.1, "min_scale": 0.0},
    }

    frame = bot._online_signal_frame_for_strategy(config, meta, panel)

    assert frame.loc[index[2], "vol_scale"] == 0.25
    assert frame.loc[index[2], "vol_gate"] == 1.0


def test_recent_performance_label_is_not_full_sample(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    curves = {
        config.key: pd.DataFrame({"return": [0.0, 0.01, -0.005], "nav": [1.0, 1.01, 1.00495]}, index=index)
        for config in bot.STRATEGIES
    }
    monkeypatch.setattr(
        bot,
        "load_performance_curves",
        lambda: (curves, {"ok": True, "mode": "daily", "data_mode": "online_rebuild_recent_performance"}),
    )

    output = bot.render_performance("", combo=False)

    assert "全样本" not in output
    assert "Poe最近窗口" in output

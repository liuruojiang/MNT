import importlib.util
import math
from pathlib import Path

import pandas as pd


def load_bot_module():
    path = Path(__file__).resolve().parents[1] / "poe_adk_16_spread_v1_0_bot.py"
    spec = importlib.util.spec_from_file_location("poe_adk_16_spread_v1_0_bot", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_strategy(bot, key, display_name=None):
    return bot.StrategyConfig(
        key=key,
        display_name=display_name or key,
        short_name=display_name or key,
        daily_file=f"{key}.csv",
        metrics_file=f"{key}.json",
        direction_cn="test",
        direction_en="test",
        formal_start_note="test",
    )


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
            "basis": "score_strength",
            "decay_threshold": 0.30,
            "recovery_threshold": 0.80,
            "warmup_days": 1,
            "scale": 0.25,
        }
    }

    states = bot._online_decay_state_frame(signal_frame, meta)

    assert states.loc[index[2], "ratio"] == 0.2
    assert states.loc[index[2], "gate"] == 1.0
    assert states.loc[index[2], "mult"] == 0.25
    assert states.loc[index[3], "ratio"] == 0.9
    assert states.loc[index[3], "gate"] == 0.0


def test_online_fetch_lookback_supports_ten_year_windows():
    bot = load_bot_module()

    assert bot.ONLINE_FETCH_LOOKBACK_BARS >= 3000


def test_decay_detail_shows_score_strength_decay_ratio():
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
            "basis": "score_strength",
            "decay_threshold": 0.30,
            "recovery_threshold": 0.80,
            "warmup_days": 3,
            "scale": 0.25,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert "动量衰减比 0.200" in rows["动量衰减"]


def test_decay_detail_recomputes_decay_ratio_from_online_signal_history():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    curve = pd.DataFrame(
        {
            "spread_close": [1.0, 1.0, 1.0, 1.0],
            "score": [10.0, 10.0, 6.0, 6.0],
            "raw_signal": [0.0, 0.0, 0.0, 0.0],
            "decay_ratio_signal_day": [math.nan, math.nan, math.nan, math.nan],
            "decay_gate": [0.0, 0.0, 1.0, 1.0],
            "decay_mult": [1.0, 1.0, 0.0, 0.0],
        },
        index=index,
    )
    meta = {
        "signal": {"score_threshold": 0.0},
        "momentum_decay": {
            "enabled": True,
            "basis": "score",
            "decay_threshold": 0.70,
            "recovery_threshold": 0.80,
            "warmup_days": 1,
            "scale": 0.0,
        },
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))
    detail = rows["动量衰减"]

    assert "N/A" not in detail
    assert "动量衰减比 0.600" in detail


def test_decay_detail_clears_trigger_when_current_signal_is_inactive():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    curve = pd.DataFrame(
        {
            "spread_close": [1.0, 1.0, 1.0, 1.0],
            "score": [10.0, 10.0, 6.0, 6.0],
            "raw_signal": [0.0, 0.0, 0.0, 0.0],
            "decay_ratio_signal_day": [math.nan, math.nan, math.nan, math.nan],
            "decay_gate": [0.0, 0.0, 1.0, 1.0],
            "decay_mult": [1.0, 1.0, 0.0, 0.0],
        },
        index=index,
    )
    meta = {
        "signal": {"score_threshold": 0.0},
        "momentum_decay": {
            "enabled": True,
            "basis": "score",
            "decay_threshold": 0.70,
            "recovery_threshold": 0.80,
            "warmup_days": 1,
            "scale": 0.0,
        },
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert "未触发" in rows["动量衰减"]
    assert "动量衰减比 0.600" in rows["动量衰减"]


def test_decay_detail_shows_realtime_strength_ratio_even_when_gate_not_triggered():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    curve = pd.DataFrame(
        {
            "score": [100.0, 100.0],
            "score_strength": [10.0, 8.0],
            "raw_signal": [0.0, 0.0],
            "decay_gate": [0.0, 0.0],
            "decay_mult": [1.0, 1.0],
        },
        index=index,
    )
    meta = {
        "momentum_decay": {
            "enabled": True,
            "basis": "score_strength",
            "decay_threshold": 0.70,
            "recovery_threshold": 0.80,
            "warmup_days": 3,
            "scale": 0.25,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert "未触发" in rows["动量衰减"]
    assert "动量衰减比 0.800" in rows["动量衰减"]
    assert "当前未激活" not in rows["动量衰减"]


def test_decay_detail_computes_realtime_strength_ratio_when_gate_triggered_without_export():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    curve = pd.DataFrame(
        {
            "score": [100.0, 100.0],
            "score_strength": [10.0, 6.0],
            "raw_signal": [0.0, 0.0],
            "decay_gate": [1.0, 1.0],
            "decay_mult": [0.0, 0.0],
        },
        index=index,
    )
    meta = {
        "momentum_decay": {
            "enabled": True,
            "basis": "score_strength",
            "decay_threshold": 0.70,
            "recovery_threshold": 0.80,
            "warmup_days": 1,
            "scale": 0.0,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert "未触发" in rows["动量衰减"]
    assert "动量衰减比 0.600" in rows["动量衰减"]
    assert "当前比值未导出" not in rows["动量衰减"]


def test_decay_detail_realtime_ratio_overrides_exported_one_for_display():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    curve = pd.DataFrame(
        {
            "score": [100.0, 100.0],
            "score_strength": [10.0, 6.0],
            "raw_signal": [1.0, 1.0],
            "decay_ratio_signal_day": [1.0, 1.0],
            "decay_gate": [1.0, 1.0],
            "decay_mult": [0.0, 0.0],
        },
        index=index,
    )
    meta = {
        "momentum_decay": {
            "enabled": True,
            "basis": "score_strength",
            "decay_threshold": 0.70,
            "recovery_threshold": 0.80,
            "warmup_days": 3,
            "scale": 0.0,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert "执行期触发" in rows["动量衰减"]
    assert "动量衰减比 0.600" in rows["动量衰减"]
    assert "当前 1.000" not in rows["动量衰减"]


def test_decay_detail_uses_full_online_signal_history_when_display_curve_is_seed_only():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    signal_frame = pd.DataFrame(
        {
            "score": [100.0, 100.0],
            "score_strength": [10.0, 6.0],
            "raw_signal": [1.0, 1.0],
        },
        index=index,
    )
    curve = pd.DataFrame(
        {
            "score": [100.0],
            "score_strength": [6.0],
            "raw_signal": [1.0],
            "decay_gate": [1.0],
            "decay_mult": [0.0],
        },
        index=[index[-1]],
    )
    curve.attrs["online_signal_frame"] = signal_frame
    meta = {
        "momentum_decay": {
            "enabled": True,
            "basis": "score_strength",
            "decay_threshold": 0.70,
            "recovery_threshold": 0.80,
            "warmup_days": 1,
            "scale": 0.0,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert "执行期触发" in rows["动量衰减"]
    assert "动量衰减比 0.600" in rows["动量衰减"]
    assert "当前 1.000" not in rows["动量衰减"]


def test_decay_detail_shows_ratio_but_no_trigger_when_signal_inactive():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    signal_frame = pd.DataFrame(
        {
            "score": [100.0, 100.0],
            "score_strength": [10.0, 6.0],
            "raw_signal": [1.0, 0.0],
        },
        index=index,
    )
    curve = pd.DataFrame(
        {
            "score": [100.0],
            "score_strength": [6.0],
            "raw_signal": [0.0],
            "decay_gate": [0.0],
            "decay_mult": [1.0],
        },
        index=[index[-1]],
    )
    curve.attrs["online_signal_frame"] = signal_frame
    meta = {
        "momentum_decay": {
            "enabled": True,
            "basis": "score_strength",
            "decay_threshold": 0.70,
            "recovery_threshold": 0.80,
            "warmup_days": 1,
            "scale": 0.0,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert "未触发" in rows["动量衰减"]
    assert "基础信号未激活" in rows["动量衰减"]
    assert "动量衰减比 0.600" in rows["动量衰减"]
    assert "当前不适用" not in rows["动量衰减"]


def test_decay_detail_clears_seed_gate_when_current_signal_is_inactive():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    signal_frame = pd.DataFrame(
        {
            "score": [100.0, 100.0],
            "score_strength": [10.0, 6.0],
            "raw_signal": [1.0, 0.0],
        },
        index=index,
    )
    curve = pd.DataFrame(
        {
            "score": [100.0],
            "score_strength": [6.0],
            "raw_signal": [0.0],
            "decay_gate": [1.0],
            "decay_mult": [0.0],
        },
        index=[index[-1]],
    )
    curve.attrs["online_signal_frame"] = signal_frame
    meta = {
        "momentum_decay": {
            "enabled": True,
            "basis": "score_strength",
            "decay_threshold": 0.70,
            "recovery_threshold": 0.80,
            "warmup_days": 1,
            "scale": 0.0,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert rows["动量衰减"].startswith("未触发")
    assert "基础信号未激活" in rows["动量衰减"]
    assert "动量衰减比 0.600" in rows["动量衰减"]
    assert "当前不适用" not in rows["动量衰减"]


def test_current_decay_display_row_clears_seed_gate_when_signal_is_inactive():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    signal_frame = pd.DataFrame(
        {
            "score": [100.0, 100.0],
            "score_strength": [10.0, 6.0],
            "raw_signal": [1.0, 0.0],
        },
        index=index,
    )
    curve = pd.DataFrame(
        {
            "score": [100.0],
            "score_strength": [6.0],
            "raw_signal": [0.0],
            "decay_gate": [1.0],
            "decay_mult": [0.0],
        },
        index=[index[-1]],
    )
    curve.attrs["online_signal_frame"] = signal_frame
    meta = {
        "momentum_decay": {
            "enabled": True,
            "basis": "score_strength",
            "decay_threshold": 0.70,
            "recovery_threshold": 0.80,
            "warmup_days": 1,
            "scale": 0.0,
        }
    }

    display_row = bot._row_with_current_decay_display(curve, curve.iloc[-1], meta)

    assert display_row["decay_gate"] == 0.0
    assert display_row["decay_mult"] == 1.0
    assert bot._overlay_summary(display_row) == "无触发"


def test_decay_detail_triggers_when_reentry_ratio_is_below_threshold():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    signal_frame = pd.DataFrame(
        {
            "score": [100.0, 100.0],
            "score_strength": [10.0, 6.0],
            "raw_signal": [0.0, 1.0],
        },
        index=index,
    )
    curve = pd.DataFrame(
        {
            "score": [100.0],
            "score_strength": [6.0],
            "raw_signal": [1.0],
            "decay_gate": [0.0],
            "decay_mult": [1.0],
        },
        index=[index[-1]],
    )
    curve.attrs["online_signal_frame"] = signal_frame
    meta = {
        "momentum_decay": {
            "enabled": True,
            "basis": "score_strength",
            "decay_threshold": 0.70,
            "recovery_threshold": 0.80,
            "warmup_days": 1,
            "scale": 0.0,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert "执行期触发" in rows["动量衰减"]
    assert "动量衰减比 0.600" in rows["动量衰减"]
    assert "参考 0.600" not in rows["动量衰减"]


def test_decay_detail_threshold_not_triggered_when_ratio_above_threshold():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    curve = pd.DataFrame(
        {
            "score": [100.0, 100.0],
            "score_strength": [10.0, 8.0],
            "raw_signal": [1.0, 1.0],
        },
        index=index,
    )
    meta = {
        "momentum_decay": {
            "enabled": True,
            "basis": "score_strength",
            "decay_threshold": 0.70,
            "recovery_threshold": 0.80,
            "warmup_days": 1,
            "scale": 0.0,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert rows["动量衰减"].startswith("未触发")
    assert "动量衰减比 0.800" in rows["动量衰减"]


def test_decay_detail_threshold_triggered_when_ratio_below_threshold():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    curve = pd.DataFrame(
        {
            "score": [100.0, 100.0],
            "score_strength": [10.0, 8.0],
            "raw_signal": [1.0, 1.0],
        },
        index=index,
    )
    meta = {
        "momentum_decay": {
            "enabled": True,
            "basis": "score_strength",
            "decay_threshold": 0.90,
            "recovery_threshold": 0.95,
            "warmup_days": 1,
            "scale": 0.0,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert rows["动量衰减"].startswith("执行期触发")
    assert "动量衰减比 0.800" in rows["动量衰减"]


def test_decay_detail_shows_zero_realtime_ratio_when_current_score_is_nonpositive():
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
            "basis": "score",
            "decay_threshold": 0.45,
            "recovery_threshold": 0.90,
            "warmup_days": 10,
            "scale": 0.0,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert "动量衰减比 0.000" in rows["动量衰减"]
    assert "当前未激活" not in rows["动量衰减"]
    assert "当前 N/A" not in rows["动量衰减"]


def test_decay_detail_says_ratio_unavailable_only_when_score_basis_is_missing():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    curve = pd.DataFrame(
        {
            "score": [math.nan, math.nan],
            "raw_signal": [0.0, 0.0],
            "decay_gate": [1.0, 1.0],
            "decay_mult": [0.0, 0.0],
        },
        index=index,
    )
    meta = {
        "momentum_decay": {
            "enabled": True,
            "basis": "score",
            "decay_threshold": 0.70,
            "recovery_threshold": 0.80,
            "warmup_days": 10,
            "scale": 0.0,
        }
    }

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))

    assert "动量衰减" in rows
    assert "动量衰减比不可计算" in rows["动量衰减"]
    assert "当前比值未导出" not in rows["动量衰减"]
    assert "当前 N/A" not in rows["动量衰减"]


def test_nav_defense_detail_distinguishes_execution_gate_from_current_drawdown():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    curve = pd.DataFrame(
        {
            "nav": [1.0, 0.9605],
            "nav_defense_gate": [1.0, 1.0],
        },
        index=index,
    )
    meta = {"nav_defense": {"enabled": True, "threshold": 0.04, "scale": 0.75}}

    rows = dict(bot._overlay_detail_rows(curve, curve.iloc[-1], meta))
    detail = rows["NAV防守"]

    assert detail.startswith("执行期触发")
    assert not detail.startswith("触发；")
    assert "当前NAV仅参考" in detail


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


def test_render_signal_degrades_by_pair_when_some_curves_missing(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    first_pair = bot.PAIR_DEFS[0]
    forward_key = first_pair[2]
    reverse_key = first_pair[3]
    curves = {
        forward_key: pd.DataFrame({"gross_exposure": [0.0, 0.0], "score": [1.0, 2.0]}, index=index),
        reverse_key: pd.DataFrame({"gross_exposure": [0.0, 0.0], "score": [1.0, 2.0]}, index=index),
    }
    metas = {forward_key: {}, reverse_key: {}}

    def fake_snapshot(config, curve, meta, online, live):
        return {
            "direction": config.direction_en,
            "sample": "sample",
            "target_score": "score",
            "exposure": "exposure",
            "basic_exec": "basic",
            "tv": "tv",
            "formula": "formula",
            "overlay_summary": "summary",
            "overlay_rows": [],
        }

    monkeypatch.setattr(
        bot,
        "load_strategy_context",
        lambda include_realtime=False: (curves, metas, {"ok": True, "mode": "daily", "data_mode": "online_rebuild_recent"}),
    )
    monkeypatch.setattr(bot, "_strategy_signal_snapshot", fake_snapshot)

    output = bot.render_signal(live=True)

    assert "sample" in output
    assert forward_key not in output
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

    def fake_fill(
        idx,
        row,
        curve_so_far,
        meta,
        signal_frame,
        decay_state_frame=None,
        target_series=None,
        vol_series=None,
    ):
        calls.append((idx, len(curve_so_far)))
        row["gross_exposure"] = float(len(calls))
        row["return"] = 0.0
        row["nav"] = 1.0
        return row

    monkeypatch.setattr(bot, "_fill_online_execution_row", fake_fill)

    curves = bot._build_curves_from_online_prices({config.key: {"signal": {"score_threshold": 0.0}}}, pd.DataFrame(), full_history=False)

    assert calls == [(index[0], 0), (index[1], 1), (index[2], 1)]
    assert curves[config.key]["gross_exposure"].tolist() == [1.0, 2.0, 3.0]


def test_performance_rebuild_uses_full_history_without_snapshot_seed(monkeypatch):
    bot = load_bot_module()
    bot._PERFORMANCE_CONTEXT_CACHE.clear()
    index = pd.date_range("2025-01-01", periods=80, freq="D")
    panel = pd.DataFrame(index=index)
    calls = []

    monkeypatch.setattr(bot, "load_strategy_curves", lambda: {})
    monkeypatch.setattr(bot, "_fetch_online_price_panel", lambda include_realtime=False: (panel, {"mode": "daily"}))

    def fake_build(metas, panel, *, full_history=False):
        calls.append(full_history)
        return {
            config.key: pd.DataFrame(
                {
                    "return": [0.0] * len(index),
                    "nav": [1.0] * len(index),
                    "gross_exposure": [0.0] * len(index),
                    "score": [0.0] * len(index),
                },
                index=index,
            )
            for config in bot.STRATEGIES
        }

    monkeypatch.setattr(bot, "_build_curves_from_online_prices", fake_build)

    _curves, online = bot.load_performance_curves()

    assert calls == [True]
    assert online["data_mode"] == "online_rebuild_full_performance"


def test_short_performance_window_refuses_annualized_metrics():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    curve = pd.DataFrame({"return": [0.0, 0.05, -0.02]}, index=index)

    metrics = bot.metrics_for_curve(curve)

    assert metrics["rows"] == 3
    assert math.isfinite(metrics["period_return"])
    assert math.isnan(metrics["ann_return"])
    assert math.isnan(metrics["ann_vol"])
    assert math.isnan(metrics["sharpe"])
    assert math.isnan(metrics["calmar"])


def test_online_signal_applies_r2_threshold(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    panel = pd.DataFrame(
        {
            "zz1000": [100.0, 101.0, 102.0, 103.0],
            "hs300": [100.0, 100.0, 100.0, 100.0],
        },
        index=index,
    )

    monkeypatch.setattr(bot, "_bias_momentum_for_live", lambda close, bias_ma, mom_day, weight_end: pd.Series([10.0] * 4, index=index))
    monkeypatch.setattr(bot, "_bias_momentum_r2_for_live", lambda close, bias_ma, mom_day, weight_end: pd.Series([0.01, 0.01, 0.10, 0.10], index=index), raising=False)

    frame = bot._online_signal_frame_for_strategy(
        bot.STRATEGIES[0],
        {"common_start": "2026-01-01", "signal": {"score_threshold": 0.0, "r2_threshold": 0.05}},
        panel,
    )

    assert frame["r2"].tolist() == [0.01, 0.01, 0.10, 0.10]
    assert frame["raw_signal"].tolist() == [0.0, 0.0, 1.0, 1.0]


def test_live_bias_momentum_score_matches_formal_weighted_slope_formula():
    bot = load_bot_module()
    close = pd.Series([1.0, 1.01, 1.03, 1.04, 1.06, 1.08], index=pd.date_range("2026-01-01", periods=6))
    bias_ma = 2
    mom_day = 3
    weight_end = 2.0
    bias = close / close.rolling(bias_ma).mean()
    weights = pd.Series([1.0, 1.5, 2.0], dtype=float)
    weights = weights / weights.sum()
    x = pd.Series([0.0, 1.0, 2.0])
    x_centered = x - x.mean()

    def formal(arr: pd.Series) -> float:
        ym = float((weights * arr.reset_index(drop=True)).sum())
        xm = float((weights * x_centered).sum())
        cov = float((weights * (x_centered - xm) * (arr.reset_index(drop=True) - ym)).sum())
        var = float((weights * (x_centered - xm) ** 2).sum())
        return cov / var * mom_day * 100.0

    expected = bias.rolling(mom_day).apply(lambda arr: formal(pd.Series(arr)), raw=False)
    actual = bot._bias_momentum_for_live(close, bias_ma=bias_ma, mom_day=mom_day, weight_end=weight_end)

    pd.testing.assert_series_equal(actual, expected, check_names=False)


def test_legacy_bias_momentum_score_matches_state_snapshot_formula():
    bot = load_bot_module()
    close = pd.Series([1.0, 1.01, 1.03, 1.04, 1.06, 1.08], index=pd.date_range("2026-01-01", periods=6))
    bias_ma = 2
    mom_day = 3
    weight_end = 2.0
    bias = close / close.rolling(bias_ma).mean()
    weights = pd.Series([1.0, 1.5, 2.0], dtype=float)
    x = pd.Series([0.0, 1.0, 2.0])
    x_bar = float((weights * x).sum() / weights.sum())
    denom = float((weights * (x - x_bar) ** 2).sum())

    def legacy(arr: pd.Series) -> float:
        arr = arr.reset_index(drop=True)
        y_bar = float((weights * arr).sum() / weights.sum())
        slope = float((weights * (x - x_bar) * (arr - y_bar)).sum() / denom)
        return slope / float(arr.iloc[0]) * 10000.0

    expected = bias.rolling(mom_day).apply(lambda arr: legacy(pd.Series(arr)), raw=False)
    expected.iloc[: bias_ma + mom_day - 1] = math.nan
    actual = bot._legacy_bias_momentum_for_live(close, bias_ma=bias_ma, mom_day=mom_day, weight_end=weight_end)

    pd.testing.assert_series_equal(actual, expected, check_names=False)


def test_legacy_snapshot_strategies_are_marked_with_legacy_score_formula():
    bot = load_bot_module()
    legacy_keys = {
        "forward_zz1000_hs300",
        "reverse_hs300_zz1000",
        "forward_cyb_hs300",
        "reverse_hs300_cyb",
        "forward_zz1000_sz50",
        "reverse_sz50_zz1000",
    }

    for config in bot.STRATEGIES:
        meta = bot.load_meta(config)
        expected = "legacy_relative_slope_10000" if config.key in legacy_keys else "weighted_slope"
        assert meta["score_formula"] == expected


def test_snapshot_score_diff_table_flags_formula_mismatches(monkeypatch):
    bot = load_bot_module()
    index = pd.to_datetime(["2026-01-02"])
    configs = (
        make_strategy(bot, "match_key", "Match"),
        make_strategy(bot, "drift_key", "Drift"),
        make_strategy(bot, "miss_key", "Miss"),
        make_strategy(bot, "missing_score_key", "Missing"),
    )
    snapshots = {
        "match_key": {"as_of": "2026-01-02", "values": {"score": 12.5}},
        "drift_key": {"as_of": "2026-01-02", "values": {"score": 12.5}},
        "miss_key": {"as_of": "2026-01-02", "values": {"score": 12.5}},
        "missing_score_key": {"as_of": "2026-01-02", "values": {"decay_gate": 1.0}},
    }

    def fake_signal(config, meta, panel):
        score = {"match_key": 12.5, "drift_key": 11.8}.get(config.key, 10.0)
        return pd.DataFrame({"score": [score]}, index=index)

    monkeypatch.setattr(bot, "STRATEGIES", configs)
    monkeypatch.setattr(bot, "STATE_SNAPSHOT", snapshots)
    monkeypatch.setattr(bot, "_online_signal_frame_for_strategy", fake_signal)

    rows = bot.snapshot_score_diffs(pd.DataFrame(index=index), {"match_key": {}, "drift_key": {}, "miss_key": {}})

    assert [row["key"] for row in rows] == ["match_key", "drift_key", "miss_key"]
    assert rows[0]["status"] == "ok"
    assert rows[0]["abs_diff"] == 0.0
    assert rows[1]["status"] == "ok"
    assert math.isclose(rows[1]["abs_diff"], 0.7)
    assert rows[2]["status"] == "mismatch"
    assert rows[2]["abs_diff"] == 2.5


def test_snapshot_score_diff_table_distinguishes_missing_date_from_missing_as_of(monkeypatch):
    bot = load_bot_module()
    index = pd.to_datetime(["2026-01-02"])
    configs = (make_strategy(bot, "date_gap_key", "Date Gap"),)

    monkeypatch.setattr(bot, "STRATEGIES", configs)
    monkeypatch.setattr(bot, "STATE_SNAPSHOT", {"date_gap_key": {"as_of": "2026-01-03", "values": {"score": 12.5}}})
    monkeypatch.setattr(bot, "_online_signal_frame_for_strategy", lambda config, meta, panel: pd.DataFrame({"score": [12.5]}, index=index))

    rows = bot.snapshot_score_diffs(pd.DataFrame(index=index), {"date_gap_key": {}})

    assert rows[0]["status"] == "as_of_not_in_panel"


def test_snapshot_score_diff_table_preserves_score_formula_metadata(monkeypatch):
    bot = load_bot_module()
    index = pd.to_datetime(["2026-01-02"])
    configs = (make_strategy(bot, "legacy_key", "Legacy"),)

    monkeypatch.setattr(bot, "STRATEGIES", configs)
    monkeypatch.setattr(bot, "STATE_SNAPSHOT", {"legacy_key": {"as_of": "2026-01-02", "values": {"score": 1.0}}})
    monkeypatch.setattr(bot, "_online_signal_frame_for_strategy", lambda config, meta, panel: pd.DataFrame({"score": [1.0]}, index=index))

    rows = bot.snapshot_score_diffs(pd.DataFrame(index=index), {"legacy_key": {"score_formula": "legacy_relative_slope_10000"}})

    assert rows == [
        {
            "key": "legacy_key",
            "display_name": "Legacy",
            "as_of": "2026-01-02",
            "score_formula": "legacy_relative_slope_10000",
            "snapshot_score": 1.0,
            "recomputed_score": 1.0,
            "abs_diff": 0.0,
            "status": "ok",
        }
    ]


def test_snapshot_score_fixture_has_no_formula_partition_regressions():
    bot = load_bot_module()
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "poe_adk_snapshot_panel.csv"
    panel = pd.read_csv(fixture_path, index_col=0, parse_dates=True)

    rows = bot.snapshot_score_diffs(panel)
    failures = [row for row in rows if row["status"] != "ok"]

    assert len(rows) == 15
    assert failures == []


def test_decay_ratio_config_uses_score_peak_even_when_score_strength_exists():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    signal_frame = pd.DataFrame(
        {
            "spread_close": [1.0, 1.0, 1.0, 1.0],
            "score": [10.0, 5.0, 4.0, 8.0],
            "score_strength": [10.0, 10.0, 10.0, 10.0],
            "raw_signal": [1.0, 1.0, 1.0, 1.0],
        },
        index=index,
    )
    meta = {
        "momentum_decay": {
            "enabled": True,
            "decay_ratio": 0.55,
            "recovery_ratio": 0.75,
            "confirm_days": 2,
            "derisk_scale": 0.75,
        }
    }

    states = bot._online_decay_state_frame(signal_frame, meta)

    assert states.loc[index[1], "ratio"] == 0.5
    assert states.loc[index[1], "gate"] == 0.0
    assert states.loc[index[2], "ratio"] == 0.4
    assert states.loc[index[2], "gate"] == 1.0
    assert states.loc[index[2], "mult"] == 0.75


def test_score_peak_timing_uses_raw_score_peak_with_warmup():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    signal_frame = pd.DataFrame(
        {
            "spread_close": [1.0, 1.0, 1.0, 1.0],
            "score": [10.0, 5.0, 4.0, 8.0],
            "score_strength": [10.0, 10.0, 10.0, 10.0],
            "raw_signal": [1.0, 1.0, 1.0, 1.0],
        },
        index=index,
    )
    meta = {
        "momentum_decay": {
            "enabled": True,
            "decay_threshold": 0.55,
            "recovery_threshold": 0.75,
            "warmup_days": 2,
            "scale": 0.25,
            "timing": "T close score-peak decay state shifted to T+1 execution",
        }
    }

    states = bot._online_decay_state_frame(signal_frame, meta)

    assert states.loc[index[1], "ratio"] == 0.5
    assert states.loc[index[1], "gate"] == 1.0
    assert states.loc[index[1], "mult"] == 0.25


def test_score_strength_basis_can_be_declared_explicitly():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    signal_frame = pd.DataFrame(
        {
            "spread_close": [1.0, 1.0, 1.0],
            "score": [10.0, 5.0, 4.0],
            "score_strength": [10.0, 10.0, 10.0],
            "raw_signal": [1.0, 1.0, 1.0],
        },
        index=index,
    )
    meta = {
        "momentum_decay": {
            "enabled": True,
            "basis": "score_strength",
            "decay_threshold": 0.55,
            "recovery_threshold": 0.75,
            "warmup_days": 2,
            "scale": 0.25,
        }
    }

    states = bot._online_decay_state_frame(signal_frame, meta)

    assert states.loc[index[1], "ratio"] == 1.0
    assert states.loc[index[1], "gate"] == 0.0


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


def test_full_online_performance_label_is_price_window_not_full_sample(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=80, freq="D")
    curves = {
        config.key: pd.DataFrame({"return": [0.0] * len(index), "nav": [1.0] * len(index)}, index=index)
        for config in bot.STRATEGIES
    }
    monkeypatch.setattr(
        bot,
        "load_performance_curves",
        lambda: (curves, {"ok": True, "mode": "daily", "data_mode": "online_rebuild_full_performance"}),
    )

    output = bot.render_performance("", combo=False)

    assert "全样本" not in output
    assert f"Poe在线价格窗口（约{bot.ONLINE_FETCH_LOOKBACK_BARS}个交易日）" in output
    assert "不代表本地正式长期回测" in output
    assert "NAV 在在线窗口起点重置为 1.0" in output


def test_online_rebuild_precomputes_decay_state_once(monkeypatch):
    bot = load_bot_module()
    config = bot.STRATEGIES[0]
    index = pd.date_range("2026-01-01", periods=5, freq="D")
    signal_frame = pd.DataFrame(
        {
            "spread_close": [1.0, 1.1, 1.2, 1.3, 1.4],
            "score": [10.0, 8.0, 6.0, 9.0, 10.0],
            "raw_signal": [1.0] * 5,
        },
        index=index,
    )
    calls = []

    monkeypatch.setattr(bot, "STRATEGIES", [config])
    monkeypatch.setattr(bot, "STATE_SNAPSHOT", {})
    monkeypatch.setattr(bot, "_online_signal_frame_for_strategy", lambda config, meta, panel: signal_frame)
    original = bot._online_decay_state_frame

    def counted_state_frame(signal_frame, meta):
        calls.append(len(signal_frame))
        return original(signal_frame, meta)

    monkeypatch.setattr(bot, "_online_decay_state_frame", counted_state_frame)

    bot._build_curves_from_online_prices(
        {config.key: {"signal": {"score_threshold": 0.0}, "momentum_decay": {"enabled": True, "basis": "score", "decay_threshold": 0.5, "recovery_threshold": 0.8, "warmup_days": 2}}},
        pd.DataFrame(),
        full_history=True,
    )

    assert calls == [len(signal_frame)]

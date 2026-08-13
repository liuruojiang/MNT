import importlib.util
import math
from pathlib import Path

import pandas as pd
import pytest


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


def make_required_price_panel(bot, index):
    panel = pd.DataFrame(index=index)
    for offset, asset in enumerate(bot.CN_PRICE_SECIDS, start=1):
        panel[asset] = 1000.0 + offset * 100.0 + pd.Series(range(len(index)), index=index) * (offset + 1)
        panel[f"{asset}_amount"] = 1_000_000_000.0 + offset * 10_000_000.0
        panel[f"{asset}_volume"] = 10_000_000.0 + offset * 100_000.0
    panel.attrs["mode"] = "daily"
    return panel


def make_return_curves(bot, index, daily_return=0.0):
    returns = [daily_return] * len(index)
    nav = (1.0 + pd.Series(returns, index=index)).cumprod()
    return {
        config.key: pd.DataFrame(
            {
                "return": returns,
                "gross_return": returns,
                "nav": nav,
                "gross_exposure": [0.0] * len(index),
                "score": [0.0] * len(index),
            },
            index=index,
        )
        for config in bot.STRATEGIES
    }


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


def test_post_close_exposure_uses_applied_target_vol_scale_not_raw():
    bot = load_bot_module()
    index = pd.DatetimeIndex([pd.Timestamp("2026-06-12")])
    curve = pd.DataFrame(
        {
            "target": [1.0],
            "raw_signal": [1.0],
            "score": [12.0],
            "gross_exposure": [1.0],
            "base_gross_exposure": [1.0],
            "target_vol_scale": [1.0],
            "target_vol_raw_scale": [0.5],
        },
        index=index,
    )
    meta = {
        "signal": {"score_threshold": 0.0},
        "target_vol": {"enabled": True, "target_vol": 0.16, "target_vol_window": 20},
    }

    snapshot = bot._strategy_signal_snapshot(bot.STRATEGIES[0], curve, meta, {"ok": True, "probes": {}}, live=False)

    assert snapshot["formula"].count("TV 1.000") >= 2
    assert "TV 0.500" not in snapshot["formula"]


def test_signal_snapshot_details_include_r2_threshold_and_realized_vol():
    bot = load_bot_module()
    index = pd.DatetimeIndex([pd.Timestamp("2026-06-12")])
    curve = pd.DataFrame(
        {
            "target": [1.0],
            "raw_signal": [1.0],
            "score": [12.0],
            "r2": [0.04],
            "gross_exposure": [0.8],
            "base_gross_exposure": [0.8],
            "target_vol_scale": [0.8],
            "target_vol_raw_scale": [0.7],
            "realized_vol": [0.2],
        },
        index=index,
    )
    meta = {
        "signal": {"score_threshold": 0.0, "r2_threshold": 0.05},
        "target_vol": {"enabled": True, "target_vol": 0.16, "target_vol_window": 20},
    }

    snapshot = bot._strategy_signal_snapshot(bot.STRATEGIES[0], curve, meta, {"ok": True, "probes": {}}, live=False)

    assert "R2" in snapshot["overlay_detail"]
    assert "0.040" in snapshot["overlay_detail"]
    assert "0.050" in snapshot["overlay_detail"]
    assert "RV 20.00%" in snapshot["overlay_detail"]


def test_realtime_context_rebuilds_online_without_embedded_artifacts(tmp_path, monkeypatch):
    bot = load_bot_module()
    bot.OUTPUT_DIR = tmp_path / "missing_outputs"
    bot._EMBEDDED_ARTIFACT_CACHE = None

    index = pd.bdate_range(end="2026-07-10", periods=400)
    panel = make_required_price_panel(bot, index)

    def fake_fetch_online_price_panel(include_realtime=False):
        return panel, {"mode": "daily", "fetched_at": "2026-01-01 15:00:00"}

    monkeypatch.setattr(bot, "_fetch_online_price_panel", fake_fetch_online_price_panel)
    monkeypatch.setattr(bot, "STATE_SNAPSHOT", {})

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


def test_realtime_context_isolates_missing_online_asset(monkeypatch):
    bot = load_bot_module()
    index = pd.bdate_range("2026-01-01", periods=120)
    panel = make_required_price_panel(bot, index).drop(columns=["cyb", "cyb_amount", "cyb_volume"])

    def fake_fetch_online_price_panel(include_realtime=False):
        return panel, {"mode": "daily", "errors": {"cyb": "network timeout"}}

    monkeypatch.setattr(bot, "_fetch_online_price_panel", fake_fetch_online_price_panel)

    curves, _metas, online = bot.load_strategy_context(include_realtime=True)

    assert online["ok"] is True
    affected = [config.key for config in bot.STRATEGIES if "cyb" in bot.STRATEGY_LEGS[config.key]]
    unaffected = [config.key for config in bot.STRATEGIES if "cyb" not in bot.STRATEGY_LEGS[config.key]]
    assert all(curves[key].empty for key in affected)
    assert all(not curves[key].empty for key in unaffected)
    assert "cyb" in panel.attrs["missing_price_assets"]
    assert all("cyb" in str(online["strategy_input_diagnostics"][key]["reason"]) for key in affected)


def test_realtime_context_does_not_full_history_rebuild(monkeypatch):
    bot = load_bot_module()
    index = pd.bdate_range("2025-01-01", periods=180)
    panel = make_required_price_panel(bot, index)
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


def test_realtime_params_loads_live_context_but_plain_params_do_not(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-07-09", periods=2, freq="D")
    metas = {config.key: {} for config in bot.STRATEGIES}
    curves = make_return_curves(bot, index)
    calls = []

    monkeypatch.setattr(bot, "load_strategy_metas", lambda: metas)

    def fake_load_strategy_context(include_realtime=False):
        calls.append(include_realtime)
        return curves, metas, {"ok": True, "mode": "daily", "data_mode": "online_rebuild_recent_realtime"}

    monkeypatch.setattr(bot, "load_strategy_context", fake_load_strategy_context)

    plain = bot.render_params(live=False)
    live = bot.render_params(live=True)

    assert calls == [True]
    assert "target-vol" in plain
    assert "target-vol" in live
    assert "live-state" in live


def test_plain_signal_query_uses_daily_path_and_default_stays_realtime(monkeypatch):
    bot = load_bot_module()
    calls = []

    def fake_render_signal(live=False):
        calls.append(live)
        return f"live={live}"

    monkeypatch.setattr(bot, "render_signal", fake_render_signal)

    assert bot.render_query("信号") == "live=False"
    assert bot.render_query("实时信号") == "live=True"
    assert bot.render_query("") == "live=True"
    assert calls == [False, True, True]


def test_history_signal_query_routes_before_plain_signal(monkeypatch):
    bot = load_bot_module()

    monkeypatch.setattr(bot, "render_signal", lambda live=False: "plain")
    monkeypatch.setattr(bot, "render_signal_history", lambda query: "history")

    assert bot.render_query("历史信号") == "history"


def test_signal_history_uses_confirmed_online_context_when_artifacts_are_missing(monkeypatch):
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

    assert calls == [False]
    assert "2026-01-02" in output


def test_signal_history_reports_missing_curves_without_keyerror(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    curves = {
        bot.STRATEGIES[0].key: pd.DataFrame(
            {"gross_exposure": [0.0, 1.0], "score": [1.0, 2.0]},
            index=index,
        )
    }

    monkeypatch.setattr(
        bot,
        "load_strategy_context",
        lambda include_realtime=False: (curves, {}, {"ok": True, "data_mode": "online_rebuild_realtime"}),
    )

    output = bot.render_signal_history("history")

    assert "2026-01-02" in output
    assert "missing curve" in output
    assert bot.STRATEGIES[1].key in output


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
    index = pd.date_range("2025-01-01", periods=160, freq="D")
    panel = make_required_price_panel(bot, index)
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


def test_online_signal_frame_clamps_to_required_publication_start_when_meta_lacks_common_start(monkeypatch):
    bot = load_bot_module()
    config = next(config for config in bot.STRATEGIES if config.key == "forward_zz1000_hs300")
    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2014-10-15"),
            pd.Timestamp("2014-10-16"),
            pd.Timestamp("2014-10-17"),
            pd.Timestamp("2014-10-20"),
        ]
    )
    panel = make_required_price_panel(bot, index)

    monkeypatch.setattr(
        bot,
        "_bias_momentum_score_for_live",
        lambda close, bias_ma, mom_day, weight_end, meta: pd.Series([10.0] * len(close), index=close.index),
    )
    monkeypatch.setattr(
        bot,
        "_bias_momentum_r2_for_live",
        lambda close, bias_ma, mom_day, weight_end: pd.Series([1.0] * len(close), index=close.index),
        raising=False,
    )

    frame = bot._online_signal_frame_for_strategy(config, {"signal": {"score_threshold": 0.0}}, panel)

    assert frame.index.min() >= pd.Timestamp("2014-10-17")


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

    assert len(rows) == 16
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


def test_parse_date_range_supports_chinese_past_year_to_date_and_explicit_ranges():
    bot = load_bot_module()
    index = pd.bdate_range("2020-01-01", "2026-06-26")

    start, end, label = bot.parse_date_range("表现 过去三年", index)
    assert label == "最近3年"
    assert start == pd.Timestamp("2023-06-26")
    assert end == pd.Timestamp("2026-06-26")

    start, end, label = bot.parse_date_range("表现 今年", index)
    assert label == "今年"
    assert start == pd.Timestamp("2026-01-01")
    assert end == pd.Timestamp("2026-06-26")

    start, end, label = bot.parse_date_range("表现 2025-01 到 2026-06", index)
    assert label == "2025-01-01 至 2026-06-26"
    assert start == pd.Timestamp("2025-01-01")
    assert end == pd.Timestamp("2026-06-26")

    start, end, label = bot.parse_date_range("表现 2025-01-15 到 2026-02-20", index)
    assert label == "2025-01-15 至 2026-02-20"
    assert start == pd.Timestamp("2025-01-15")
    assert end == pd.Timestamp("2026-02-20")


def test_nav_chart_queries_route_before_default_signal(monkeypatch):
    bot = load_bot_module()
    calls = []

    def fake_nav_chart(query, combo=False):
        calls.append((query, combo))
        return f"nav combo={combo}"

    def fail_signal(live=False):
        raise AssertionError("nav chart query should not fall through to signal")

    monkeypatch.setattr(bot, "render_nav_chart", fake_nav_chart)
    monkeypatch.setattr(bot, "render_signal", fail_signal)

    assert bot.render_query("净值曲线 最近一年") == "nav combo=False"
    assert bot.render_query("组合净值曲线 最近一年") == "nav combo=True"
    assert calls == [("净值曲线 最近一年", False), ("组合净值曲线 最近一年", True)]


def test_render_performance_uses_query_scoped_loader(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=80, freq="D")
    curves = {
        config.key: pd.DataFrame({"return": [0.0] * len(index), "nav": [1.0] * len(index)}, index=index)
        for config in bot.STRATEGIES
    }
    calls = []

    def fake_scoped_loader(query):
        calls.append(query)
        return curves, {"ok": True, "mode": "daily", "data_mode": "online_rebuild_recent_performance"}

    def fail_full_loader():
        raise AssertionError("render_performance should use query-scoped loader")

    monkeypatch.setattr(bot, "_load_performance_curves_for_query", fake_scoped_loader, raising=False)
    monkeypatch.setattr(bot, "load_performance_curves", fail_full_loader)

    output = bot.render_performance("表现 最近1年", combo=False)

    assert calls == ["表现 最近1年"]
    assert "Poe最近窗口" in output


def test_render_performance_includes_standard_windows_and_na_reasons(monkeypatch):
    bot = load_bot_module()
    index = pd.bdate_range("2020-01-02", "2026-01-02")
    curves = make_return_curves(bot, index, daily_return=0.0001)

    monkeypatch.setattr(
        bot,
        "_load_performance_curves_for_query",
        lambda query: (curves, {"ok": True, "mode": "daily", "data_mode": "online_rebuild_recent_performance"}),
        raising=False,
    )

    output = bot.render_performance("performance", combo=False)

    assert "Standard windows" in output
    for label in ("Full", "10Y", "5Y", "3Y", "1Y"):
        assert f"| {label} |" in output
    assert "history starts" in output


def test_combo_performance_reports_missing_leg_as_na_not_keyerror(monkeypatch):
    bot = load_bot_module()
    index = pd.bdate_range("2020-01-02", "2026-01-02")
    curves = make_return_curves(bot, index, daily_return=0.0001)
    missing_key = "reverse_hs300_zz1000"
    del curves[missing_key]

    monkeypatch.setattr(
        bot,
        "_load_performance_curves_for_query",
        lambda query: (curves, {"ok": True, "mode": "daily", "data_mode": "online_rebuild_recent_performance"}),
        raising=False,
    )

    output = bot.render_performance("combo performance", combo=True)

    assert "N/A" in output
    assert f"missing curve {missing_key}" in output


def test_nav_chart_falls_back_to_performance_standard_windows(monkeypatch):
    bot = load_bot_module()
    index = pd.bdate_range("2020-01-02", "2026-01-02")
    curves = make_return_curves(bot, index, daily_return=0.0001)

    monkeypatch.setattr(
        bot,
        "_load_performance_curves_for_query",
        lambda query: (curves, {"ok": True, "mode": "daily", "data_mode": "online_rebuild_recent_performance"}),
        raising=False,
    )

    output = bot.render_nav_chart("NAV", combo=False)

    assert "NAV chart unavailable" in output
    assert "Standard windows" in output
    assert "| 10Y |" in output


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


def test_online_signal_frame_exports_formal_spread_return_and_uses_it_for_vol(monkeypatch):
    bot = load_bot_module()
    config = bot.STRATEGIES[0]
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    panel = pd.DataFrame(
        {
            "zz1000": [100.0, 100.0, 100.0],
            "hs300": [100.0, 90.0, 99.0],
        },
        index=index,
    )
    monkeypatch.setattr(bot, "_downonly_tv_scale_from_realized_vol", lambda realized_vol, section: 0.5)

    frame = bot._online_signal_frame_for_strategy(
        config,
        {
            "common_start": "2026-01-01",
            "signal": {"bias_ma": 1, "mom_day": 1, "score_threshold": -999.0},
            "vol_overheat": {"enabled": True, "kind": "downonly_tv", "window": 2, "target_vol": 0.1},
        },
        panel,
    )

    expected_return = panel["zz1000"].pct_change().fillna(0.0) - panel["hs300"].pct_change().fillna(0.0)
    pd.testing.assert_series_equal(frame["spread_return"], expected_return, check_names=False)
    expected_vol = expected_return.rolling(2).std(ddof=0) * math.sqrt(bot.ANNUAL_DAYS)
    assert math.isclose(frame.loc[index[-1], "realized_vol"], expected_vol.loc[index[-1]])


def test_online_execution_row_uses_formal_spread_return_not_ratio_return():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    signal_frame = pd.DataFrame(
        {
            "spread_close": [1.0, 1.0 / 0.9],
            "spread_return": [0.0, 0.10],
            "score": [1.0, 1.0],
            "r2": [1.0, 1.0],
        },
        index=index,
    )
    curve_so_far = pd.DataFrame(
        {
            "nav": [1.0],
            "base_nav": [1.0],
            "gross_exposure": [1.0],
            "base_gross_exposure": [1.0],
            "target_vol_scale": [1.0],
        },
        index=[index[0]],
    )

    filled = bot._fill_online_execution_row(
        index[1],
        signal_frame.loc[index[1]].to_dict(),
        curve_so_far,
        {"signal": {"score_threshold": 0.0}},
        signal_frame,
    )

    assert math.isclose(filled["gross_return"], 0.10)
    assert not math.isclose(filled["gross_return"], (1.0 / 0.9) - 1.0)


def test_online_incremental_extension_uses_formal_spread_return(monkeypatch):
    bot = load_bot_module()
    config = bot.STRATEGIES[0]
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    curve = pd.DataFrame(
        {
            "return": [0.0],
            "gross_return": [0.0],
            "cost": [0.0],
            "turnover": [0.0],
            "gross_exposure": [1.0],
            "nav": [1.0],
            "score": [1.0],
        },
        index=[index[0]],
    )
    panel = pd.DataFrame({"zz1000": [100.0, 100.0], "hs300": [100.0, 90.0]}, index=index)

    monkeypatch.setattr(bot, "STRATEGIES", [config])
    monkeypatch.setattr(bot, "STATE_SNAPSHOT", {})
    monkeypatch.setattr(bot, "_fill_online_execution_row", lambda idx, row, curve_so_far, meta, signal_frame, **kwargs: row)

    refreshed = bot._extend_curves_with_online_prices(
        {config.key: curve},
        {config.key: {"common_start": "2026-01-01", "signal": {"bias_ma": 1, "mom_day": 1, "score_threshold": -999.0}}},
        panel,
    )

    assert math.isclose(refreshed[config.key].loc[index[1], "gross_return"], 0.10)


def test_two_leg_commission_multiplies_one_way_rate_by_legs():
    bot = load_bot_module()

    assert bot._cost_rate_from_meta({"cost_model": {"one_way_commission": 0.0005, "legs": 2}}) == 0.001
    assert bot._cost_rate_from_meta({"cost_model": {"one_way_cost_bps": 5, "legs": 2}}) == 0.001


def test_high_metric_gate_requires_confirmation_days():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    panel = pd.DataFrame(
        {
            "zz1000_amount": [100.0, 100.0, 100.0, 200.0],
            "hs300_amount": [100.0, 100.0, 100.0, 100.0],
        },
        index=index,
    )

    _ratio, gate = bot._metric_gate_series(
        {"family": "high_pair", "window": 3, "threshold": 1.2, "confirm_days": 3},
        panel,
        "zz1000",
        "hs300",
        "amount",
    )

    assert gate.loc[index[-1]] == 0.0


def test_suffix_high_metric_family_is_treated_as_high_not_low():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    panel = pd.DataFrame({"sz50_volume": [100.0, 100.0, 100.0, 100.0]}, index=index)

    _ratio, gate = bot._metric_gate_series(
        {"family": "sz50_vol_high", "series": "sz50_volume", "window": 3, "threshold": 1.25, "confirm_days": 1},
        panel,
        "sz50",
        "cyb",
        "volume",
    )

    assert gate.loc[index[-1]] == 0.0


def test_validate_online_price_panel_isolates_nonpositive_prices(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-07-01", periods=3, freq="D")
    panel = make_required_price_panel(bot, index)
    panel.loc[index[-1], "zz1000"] = 0.0
    monkeypatch.setattr(bot, "beijing_now", lambda: bot.datetime(2026, 7, 10, tzinfo=bot.BJ_TZ))

    bot._validate_online_price_panel(panel)

    assert any("zz1000" in item for item in panel.attrs["invalid_price_assets"])


def test_validate_online_price_panel_rejects_stale_prices(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-06-01", periods=3, freq="D")
    panel = make_required_price_panel(bot, index)
    panel.attrs["fetched_at"] = "2026-07-10 15:00:00"
    monkeypatch.setattr(bot, "beijing_now", lambda: bot.datetime(2026, 7, 10, tzinfo=bot.BJ_TZ))

    with pytest.raises(RuntimeError, match="stale"):
        bot._validate_online_price_panel(panel)


def test_validate_online_price_panel_degrades_lagged_overlay_metric(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-07-01", periods=10, freq="D")
    panel = make_required_price_panel(bot, index)
    panel.loc[index[-1], "zz1000_amount"] = math.nan
    monkeypatch.setattr(bot, "beijing_now", lambda: bot.datetime(2026, 7, 10, tzinfo=bot.BJ_TZ))
    config = bot.STRATEGIES[0]

    bot._validate_online_price_panel(
        panel,
        {config.key: {"amount_overlay": {"enabled": True, "series": "zz1000_amount", "window": 3}}},
    )

    diagnostic = panel.attrs["strategy_input_diagnostics"][config.key]
    assert diagnostic["status"] == "degraded"
    assert diagnostic["confirmed_through"] == index[-2].strftime("%Y-%m-%d")


def test_amount_history_fallback_does_not_accept_volume_proxy(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=80, freq="D")
    proxy = pd.DataFrame({"close": [1.0] * 80, "volume": [100.0] * 80, "amount": [100.0] * 80}, index=index)

    monkeypatch.setattr(bot, "_fetch_eastmoney_kline", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(bot, "_fetch_csindex_amount", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(bot, "_fetch_sohu_amount", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(bot, "_fetch_sina_volume_proxy", lambda *args, **kwargs: proxy)
    monkeypatch.setattr(bot, "_fetch_tencent_volume_proxy", lambda *args, **kwargs: proxy)

    with pytest.raises(RuntimeError):
        bot._fetch_amount_history_with_fallback("zz1000", "1.000852")


def test_amount_sources_normalize_to_cny(monkeypatch):
    bot = load_bot_module()
    monkeypatch.setattr(bot, "requests", None)
    monkeypatch.setattr(
        bot,
        "_get_json",
        lambda *args, **kwargs: {
            "data": [
                {
                    "tradeDate": "2026-08-11",
                    "close": "100",
                    "tradingVol": "20",
                    "tradingValue": "2.5",
                }
            ]
        },
    )
    csindex = bot._fetch_csindex_amount("1.000852", lmt=1)
    assert csindex.iloc[-1]["amount"] == 250_000_000.0

    monkeypatch.setattr(
        bot,
        "_get_json",
        lambda *args, **kwargs: [
            {
                "status": 0,
                "hq": [["2026-08-11", "99", "100", "1", "1%", "98", "101", "20", "3.5", "0"]],
            }
        ],
    )
    sohu = bot._fetch_sohu_amount("1.000852", lmt=1)
    assert sohu.iloc[-1]["amount"] == 35_000.0


def test_amount_history_selects_source_reaching_price_date(monkeypatch):
    bot = load_bot_module()
    stale_index = pd.bdate_range(end="2026-08-11", periods=60)
    current_index = stale_index.append(pd.DatetimeIndex([pd.Timestamp("2026-08-12")]))

    def frame(index, amount):
        return pd.DataFrame({"close": 100.0, "volume": 10.0, "amount": amount}, index=index)

    calls = []
    monkeypatch.setattr(bot, "_fetch_sohu_amount", lambda *args, **kwargs: calls.append("sohu") or frame(stale_index, 1.0))
    monkeypatch.setattr(bot, "_fetch_eastmoney_kline", lambda *args, **kwargs: calls.append("eastmoney") or frame(current_index, 1.0))
    monkeypatch.setattr(bot, "_fetch_csindex_amount", lambda *args, **kwargs: calls.append("csindex") or frame(stale_index, 1.0))

    selected, source, attempts = bot._fetch_amount_history_with_fallback(
        "zz1000",
        "1.000852",
        target_date=pd.Timestamp("2026-08-12"),
    )

    assert source == "EastMoney amount"
    assert selected.index[-1] == pd.Timestamp("2026-08-12")
    assert calls == ["sohu", "eastmoney"]
    assert any("2026-08-11" in item for item in attempts)


def test_snapshot_seed_rows_reject_seed_date_outside_signal_frame(monkeypatch):
    bot = load_bot_module()
    config = make_strategy(bot, "future_seed", "Future Seed")
    signal_frame = pd.DataFrame({"score": [1.0], "spread_close": [1.0]}, index=[pd.Timestamp("2026-01-01")])
    monkeypatch.setattr(bot, "STATE_SNAPSHOT", {"future_seed": {"as_of": "2027-01-01", "values": {"score": 1.0, "nav": 1.0}}})

    assert bot._snapshot_seed_rows(config, signal_frame) == []


def test_load_strategy_context_rebuilds_on_snapshot_score_mismatch(monkeypatch):
    bot = load_bot_module()
    config = make_strategy(bot, "snapshot_mismatch", "Snapshot Mismatch")
    index = pd.to_datetime(["2026-01-02", "2026-01-03"])
    panel = make_required_price_panel(bot, index)
    signal = pd.DataFrame({"spread_close": [1.0, 1.1], "spread_return": [0.0, 0.1], "score": [2.0, 2.0]}, index=index)

    monkeypatch.setattr(bot, "STRATEGIES", [config])
    monkeypatch.setattr(bot, "STRATEGY_LEGS", {"snapshot_mismatch": ("zz1000", "hs300")})
    monkeypatch.setattr(bot, "STATE_SNAPSHOT", {"snapshot_mismatch": {"as_of": "2026-01-02", "values": {"score": 1.0}}})
    monkeypatch.setattr(bot, "load_strategy_metas", lambda: {"snapshot_mismatch": {}})
    monkeypatch.setattr(bot, "load_strategy_curves", lambda: {})
    monkeypatch.setattr(bot, "_fetch_online_price_panel", lambda include_realtime=False: (panel, {"mode": "daily"}))
    monkeypatch.setattr(bot, "_online_signal_frame_for_strategy", lambda config, meta, panel: signal)

    _curves, _metas, online = bot.load_strategy_context(include_realtime=False)

    assert online["ok"] is True
    assert online["snapshot_warnings"]
    assert not _curves[config.key].empty
    assert "snapshot_warning" in _curves[config.key].attrs


def test_target_vol_deadband_defaults_to_absolute_and_resets_when_signal_off():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    signal_frame = pd.DataFrame(
        {
            "spread_close": [1.0, 1.0],
            "spread_return": [0.0, 0.0],
            "score": [0.0, 0.0],
            "r2": [1.0, 1.0],
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
    meta = {
        "signal": {"score_threshold": 1.0},
        "target_vol": {"enabled": True, "target_vol": 0.8, "target_vol_window": 1, "max_leverage": 1.5, "scale_deadband": 0.3},
    }

    assert bot._target_vol_deadband_mode(meta["target_vol"]) == "abs"
    filled = bot._fill_online_execution_row(
        index[1],
        signal_frame.loc[index[1]].to_dict(),
        curve_so_far,
        meta,
        signal_frame,
        vol_series=pd.Series([1.0, 1.0], index=index),
    )

    assert filled["target_vol_scale"] == 0.0
    assert filled["base_gross_exposure"] == 0.0


def test_metrics_for_curve_does_not_turn_invalid_returns_into_zeroes():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=61, freq="D")
    curve = pd.DataFrame({"return": [0.01] + [math.nan] * 60}, index=index)

    metrics = bot.metrics_for_curve(curve)

    assert metrics["rows"] == 1
    assert math.isnan(metrics["ann_return"])
    assert "invalid" in metrics["reason"]


def test_extract_request_query_text_uses_latest_protocol_message():
    bot = load_bot_module()

    class Message:
        def __init__(self, content):
            self.content = content

    class Request:
        query = [Message("参数"), Message("实时信号")]

    assert bot._extract_request_query_text(Request()) == "实时信号"


def test_params_display_includes_alias_thresholds_and_min_scale():
    bot = load_bot_module()

    nav_detail = bot._section_meta_detail({"enabled": True, "nav_threshold": 0.0875, "defense_scale": 0.5})
    tv_detail = bot._target_vol_detail({"enabled": True, "target_vol": 0.16, "target_vol_window": 20, "max_leverage": 1.2, "min_scale": 0.25})

    assert "nav_threshold=0.0875" in nav_detail
    assert "defense_scale=0.5" in nav_detail
    assert "min_scale=0.25" in tv_detail


def test_signal_history_uses_confirmed_daily_rows(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=6, freq="D")
    calls = []
    curves = {
        config.key: pd.DataFrame(
            {
                "gross_exposure": [1.0] * 6,
                "score": list(range(6)),
                "online_provisional_bar": [0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            },
            index=index,
        )
        for config in bot.STRATEGIES
    }

    def fake_context(include_realtime=False):
        calls.append(include_realtime)
        return curves, {}, {"ok": True, "data_mode": "online_rebuild_recent"}

    monkeypatch.setattr(bot, "load_strategy_context", fake_context)

    output = bot.render_signal_history("信号历史")

    assert calls == [False]
    assert "2026-01-06" not in output


def test_reversed_explicit_date_range_is_rejected():
    bot = load_bot_module()
    index = pd.bdate_range("2025-01-01", "2026-06-30")

    with pytest.raises(ValueError, match="start date is after end date"):
        bot.parse_date_range("表现 2026-06~2025-01", index)


def test_main_sanitizes_internal_errors_and_returns_failure(monkeypatch):
    bot = load_bot_module()
    writes = []

    class Message:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def write(self, text):
            writes.append(text)

    monkeypatch.setattr(bot.poe, "start_message", lambda: Message())
    monkeypatch.setattr(bot, "_write_query_response", lambda msg, query: (_ for _ in ()).throw(RuntimeError("secret D:/private/path")))

    code = bot.main(["信号"])

    assert code == 1
    rendered = "".join(writes)
    assert "secret" not in rendered
    assert "D:/private/path" not in rendered


def test_strategy_panel_clamps_only_lagged_overlay_strategy():
    bot = load_bot_module()
    index = pd.date_range("2026-07-01", periods=10, freq="D")
    panel = make_required_price_panel(bot, index)
    panel.loc[index[-1], "zz1000_amount"] = math.nan
    config = bot.STRATEGIES[0]
    meta = {"amount_overlay": {"enabled": True, "series": "zz1000_amount", "window": 3}}

    limited, diagnostic = bot._strategy_panel_for_online(config, meta, panel)

    assert diagnostic["status"] == "degraded"
    assert limited.index[-1] == index[-2]
    assert panel.index[-1] == index[-1]


def test_formal_legacy_strategy_uses_ratio_return_and_sample_std():
    bot = load_bot_module()
    legacy = bot.STRATEGIES[0]
    sample_std = next(config for config in bot.STRATEGIES if config.key == "forward_cyb_zz1000")
    legacy_meta = bot.load_meta(legacy)
    sample_meta = bot.load_meta(sample_std)
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    price = pd.DataFrame({"zz1000": [100.0, 100.0], "hs300": [100.0, 90.0]}, index=index)

    spread_return = bot._formal_spread_return(
        price,
        "zz1000",
        "hs300",
        bot._strategy_return_formula(legacy_meta),
    )

    assert math.isclose(spread_return.iloc[-1], (1.0 / 0.9) - 1.0)
    assert bot._strategy_vol_ddof(sample_meta) == 1


def test_combo_gross_return_reconciles_to_net_plus_cost():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    curves = {}
    for config in bot.STRATEGIES:
        curves[config.key] = pd.DataFrame(
            {
                "return": [0.01, -0.02, 0.03],
                "gross_return": [0.012, -0.018, 0.032],
                "cost": [0.002, 0.002, 0.002],
                "turnover": [0.2, 0.2, 0.2],
                "gross_exposure": [1.0, 1.0, 1.0],
            },
            index=index,
        )

    combos = bot.build_combo_curves(curves)

    for frame in combos.values():
        pd.testing.assert_series_equal(
            frame["gross_return"] - frame["cost"],
            frame["return"],
            check_names=False,
        )


def test_metrics_include_initial_nav_peak_and_handle_bankruptcy():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=60, freq="D")
    loss_curve = pd.DataFrame({"return": [-0.5, 0.5] + [0.0] * 58}, index=index)
    bankrupt_curve = pd.DataFrame({"return": [-1.1] + [0.0] * 59}, index=index)

    loss = bot.metrics_for_curve(loss_curve)
    bankrupt = bot.metrics_for_curve(bankrupt_curve)

    assert math.isclose(loss["max_dd"], -0.5)
    assert bankrupt["max_dd"] == -1.0
    assert math.isnan(bankrupt["ann_return"])
    assert "zero or below" in bankrupt["reason"]


def test_metric_confirmation_streak_resets_across_missing_day():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    panel = pd.DataFrame(
        {
            "zz1000_amount": [100.0, math.nan, 100.0],
            "hs300_amount": [100.0, 100.0, 100.0],
        },
        index=index,
    )

    _ratio, gate = bot._metric_gate_series(
        {"family": "low_pair", "window": 1, "threshold": 1.0, "confirm_days": 2},
        panel,
        "zz1000",
        "hs300",
        "amount",
    )

    assert gate.loc[index[-1]] == 0.0


def test_online_signal_does_not_bridge_internal_price_gap():
    bot = load_bot_module()
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    panel = pd.DataFrame(
        {
            "zz1000": [100.0, 101.0, 102.0, 103.0],
            "hs300": [100.0, math.nan, 101.0, 102.0],
        },
        index=index,
    )
    frame = bot._online_signal_frame_for_strategy(
        bot.STRATEGIES[0],
        {"common_start": "2026-01-01", "signal": {"bias_ma": 1, "mom_day": 1}},
        panel,
    )

    assert math.isnan(frame.loc[index[1], "spread_return"])
    assert math.isnan(frame.loc[index[2], "spread_return"])


def test_invalid_snapshot_date_and_numeric_strings_are_tolerated(monkeypatch):
    bot = load_bot_module()
    config = make_strategy(bot, "snapshot_edge", "Snapshot Edge")
    signal_frame = pd.DataFrame({"score": [1.0], "spread_close": [1.0]}, index=[pd.Timestamp("2026-01-01")])
    monkeypatch.setattr(
        bot,
        "STATE_SNAPSHOT",
        {"snapshot_edge": {"as_of": "not-a-date", "values": {"score": "1.0", "nav": "2.0"}}},
    )

    assert bot._snapshot_seed_rows(config, signal_frame) == []

    monkeypatch.setattr(
        bot,
        "STATE_SNAPSHOT",
        {"snapshot_edge": {"as_of": "2026-01-01", "values": {"score": "1.0", "nav": "2.0"}}},
    )
    seeded = bot._snapshot_seed_rows(config, signal_frame)
    assert seeded[0][1]["nav"] == 2.0


def test_query_normalization_handles_format_chars_fullwidth_and_decimal_years(monkeypatch):
    bot = load_bot_module()
    index = pd.date_range("2020-01-01", "2026-01-01", freq="D")
    start, end, _label = bot.parse_date_range("过去1.5年表现", index)
    monkeypatch.setattr(bot, "render_params", lambda live=False: "params")
    monkeypatch.setattr(bot, "render_signal_history", lambda query: "history")

    assert 540 <= (end - start).days <= 550
    assert bot.render_query("参\u200b数 ＮＡＶ") == "params"
    assert bot.render_query("历\u200b史\n信号") == "history"


def test_explicit_old_range_requests_bars_back_to_start(monkeypatch):
    bot = load_bot_module()
    monkeypatch.setattr(bot, "beijing_now", lambda: bot.datetime(2026, 8, 12, tzinfo=bot.BJ_TZ))

    bars = bot._performance_query_lookback_bars("2016-01-01--2017-01-01 表现")

    assert bars is not None and bars > 2500


def test_panel_validation_rejects_ambiguous_index_shapes():
    bot = load_bot_module()
    panel = make_required_price_panel(bot, pd.date_range("2026-01-01", periods=3, freq="D"))
    duplicate = pd.concat([panel, panel.iloc[[-1]]])

    with pytest.raises(RuntimeError, match="duplicate"):
        bot._validate_online_price_panel(duplicate)
    with pytest.raises(RuntimeError, match="DatetimeIndex"):
        bot._validate_online_price_panel(panel.reset_index(drop=True))


def test_live_snapshot_uses_current_signal_and_current_overlay_together():
    bot = load_bot_module()
    config = bot.STRATEGIES[0]
    index = pd.to_datetime(["2026-01-01", "2026-01-02"])
    signal_frame = pd.DataFrame(
        {
            "spread_close": [1.0, 1.01],
            "spread_return": [0.0, 0.01],
            "score": [1.0, 1.0],
            "r2": [1.0, 1.0],
            "raw_signal": [1.0, 1.0],
            "vol_indicator": [0.1, 0.3],
            "vol_gate": [0.0, 1.0],
            "vol_scale": [0.5, 0.5],
        },
        index=index,
    )
    curve = pd.DataFrame(
        {
            "target": [1.0, 1.0],
            "exec_signal": [1.0, 1.0],
            "score": [1.0, 1.0],
            "gross_exposure": [1.0, 1.0],
            "base_gross_exposure": [1.0, 1.0],
            "target_vol_scale": [1.0, 1.0],
            "nav": [1.0, 1.01],
            "online_provisional_bar": [0.0, 1.0],
        },
        index=index,
    )
    curve.attrs["online_signal_frame"] = bot._OnlineSignalFrameRef(signal_frame)
    meta = {
        "signal": {"score_threshold": 0.0},
        "vol_overheat": {"enabled": True, "window": 1, "threshold": 0.2, "scale": 0.5},
    }
    online = {
        "ok": True,
        "probes": {config.key: {"score": 1.0, "target": 1.0, "amount_state": {"enabled": False}}},
    }

    snapshot = bot._strategy_signal_snapshot(config, curve, meta, online, live=True)

    assert "收盘信号后）**50.0%**" in snapshot["exposure"]


def test_realtime_quote_date_prevents_holiday_ghost_bar(monkeypatch):
    bot = load_bot_module()
    index = pd.bdate_range(end="2026-09-30", periods=80)
    history = pd.DataFrame(
        {
            "close": [100.0] * len(index),
            "volume": [10_000.0] * len(index),
            "amount": [1_000_000.0] * len(index),
        },
        index=index,
    )
    monkeypatch.setattr(bot, "beijing_now", lambda: bot.datetime(2026, 10, 1, 10, 0, tzinfo=bot.BJ_TZ))
    monkeypatch.setattr(bot, "_fetch_price_history_with_fallback", lambda *args, **kwargs: (history.copy(), "test", []))
    monkeypatch.setattr(
        bot,
        "_fetch_realtime_snapshot_with_fallback",
        lambda *args, **kwargs: ({"close": 101.0, "amount": 2_000_000.0, "quote_date": "2026-09-30"}, "test realtime"),
    )

    panel, meta = bot._fetch_online_price_panel(include_realtime=True)

    assert pd.Timestamp("2026-10-01") not in panel.index
    assert meta["live_assets"] == []


def test_postclose_realtime_snapshot_fills_same_day_amount(monkeypatch):
    bot = load_bot_module()
    index = pd.bdate_range(end="2026-08-12", periods=80)
    history = pd.DataFrame(
        {
            "close": [100.0] * len(index),
            "volume": [10_000.0] * len(index),
            "amount": [1_000_000.0] * (len(index) - 1) + [math.nan],
        },
        index=index,
    )
    monkeypatch.setattr(bot, "beijing_now", lambda: bot.datetime(2026, 8, 12, 16, 0, tzinfo=bot.BJ_TZ))
    monkeypatch.setattr(bot, "_fetch_price_history_with_fallback", lambda *args, **kwargs: (history.copy(), "test", []))
    monkeypatch.setattr(
        bot,
        "_fetch_realtime_snapshot_with_fallback",
        lambda *args, **kwargs: ({"close": 100.0, "amount": 2_000_000.0, "quote_date": "2026-08-12"}, "test realtime"),
    )

    panel, meta = bot._fetch_online_price_panel(include_realtime=False)

    for asset in bot.CN_PRICE_SECIDS:
        assert panel.loc[index[-1], f"{asset}_amount"] == 2_000_000.0
    assert meta["mode"] == "daily"
    assert meta["live_assets"] == []

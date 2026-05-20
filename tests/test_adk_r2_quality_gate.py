import builtins
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mnt_bot V 7.7 plus.py"


class _PoeStub:
    query = None
    default_chat = []

    class BotError(Exception):
        pass

    def update_settings(self, settings):
        self.settings = settings


def load_module():
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = _PoeStub()
    spec = importlib.util.spec_from_file_location("mnt_bot_v77_adk_r2_test", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if had_poe:
        builtins.poe = old_poe
    else:
        delattr(builtins, "poe")
    return mod


def test_dk_r2_quality_gate_masks_low_quality_pair_scores():
    mod = load_module()
    idx = pd.date_range("2020-01-01", periods=180, freq="B")
    base = pd.Series(100.0 + np.arange(len(idx)) * 0.1, index=idx)
    ratio = pd.Series(1.0 + np.sin(np.arange(len(idx)) / 3.0) * 0.02, index=idx)
    a_prices = base * ratio
    b_prices = base

    old_enabled = mod.CN_DK_R2_QUALITY_ENABLED
    old_threshold = mod.CN_DK_R2_QUALITY_THRESHOLD
    try:
        mod.CN_DK_R2_QUALITY_ENABLED = True
        mod.CN_DK_R2_QUALITY_THRESHOLD = 0.95
        _, score_enabled, pdata_enabled = mod._run_single_pair_dk(a_prices, b_prices)

        mod.CN_DK_R2_QUALITY_ENABLED = False
        _, score_disabled, pdata_disabled = mod._run_single_pair_dk(a_prices, b_prices)
    finally:
        mod.CN_DK_R2_QUALITY_ENABLED = old_enabled
        mod.CN_DK_R2_QUALITY_THRESHOLD = old_threshold

    assert "signal_r2" in pdata_enabled.columns
    assert "rank_score" in pdata_enabled.columns

    low_quality = pdata_enabled["signal_r2"] < 0.95
    assert low_quality.any()
    assert pdata_enabled.loc[low_quality, "rank_score"].isna().all()

    valid_disabled = pdata_disabled["bias_mom"].notna()
    pd.testing.assert_series_equal(
        score_disabled.loc[valid_disabled],
        pdata_disabled.loc[valid_disabled, "bias_mom"].abs(),
        check_names=False,
    )

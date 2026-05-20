import builtins
import importlib.util
from itertools import combinations
from pathlib import Path

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
    spec = importlib.util.spec_from_file_location("mnt_bot_v77_adk_8pair_test", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if had_poe:
        builtins.poe = old_poe
    else:
        delattr(builtins, "poe")
    return mod


def test_v77_adk_formal_pool_and_defaults_are_8pair_l4():
    mod = load_module()

    assert mod.CN_DK_TARGET_VOL == 0.14
    assert mod.CN_DK_VOL_WINDOW == 40
    assert mod.CN_DK_MAX_LEV == 1.5
    assert mod.CN_DK_SCALE_THRESHOLD == 0.25
    assert mod.CN_DK_R2_QUALITY_ENABLED is True
    assert mod.CN_DK_R2_QUALITY_THRESHOLD == 0.05
    assert mod.CN_DK_SAME_SIDE_OVERHEAT_ENABLED is True
    assert mod.CN_DK_SAME_SIDE_OVERHEAT_ENTER == 0.22
    assert mod.CN_DK_SAME_SIDE_OVERHEAT_EXIT == 0.18
    assert mod.CN_DK_SAME_SIDE_OVERHEAT_DERISK_SCALE == 0.0

    assert tuple(mod.ADK_OFFICIAL_PAIR_ORDER) == (
        "SZ50/ZZ500",
        "SZ50/ZZ1000",
        "SZ50/CYB",
        "HS300/ZZ500",
        "HS300/ZZ1000",
        "HS300/CYB",
        "ZZ500/CYB",
        "ZZ1000/CYB",
    )
    assert set(mod.ADK_EXCLUDED_PAIR_ORDER) == {"SZ50/HS300", "ZZ500/ZZ1000"}


def test_v77_adk_run_strategy_only_builds_official_8pair_universe(monkeypatch):
    mod = load_module()
    idx = pd.date_range("2020-01-01", periods=220, freq="B")
    dk_close = pd.DataFrame(
        {
            "DK_SZ50": range(1000, 1220),
            "DK_HS300": range(1100, 1320),
            "DK_ZZ500": range(1200, 1420),
            "DK_ZZ1000": range(1300, 1520),
            "DK_CYB": range(1400, 1620),
        },
        index=idx,
        dtype=float,
    )

    seen_pairs = []

    def fake_run_pair(a_prices, b_prices):
        a_col = a_prices.name
        b_col = b_prices.name
        col_to_name = {info["col"]: name for name, info in mod.CN_DK_INDICES.items()}
        label = f"{col_to_name[a_col]}/{col_to_name[b_col]}"
        seen_pairs.append(label)
        ret = pd.Series(0.0, index=idx[100:])
        score = pd.Series(1.0, index=idx[100:])
        pdata = pd.DataFrame(
            {
                "position": 1,
                "raw_ret": 0.0,
                "scale": 1.0,
                "scale_raw": 1.0,
                "realized_vol": 0.1,
                "strategy_ret": 0.0,
            },
            index=idx[100:],
        )
        return ret, score, pdata

    monkeypatch.setattr(mod, "_run_single_pair_dk", fake_run_pair)
    result = mod.run_dk_strategy(dk_close, dk_close)

    assert set(seen_pairs) == set(mod.ADK_OFFICIAL_PAIR_ORDER)
    assert "SZ50/HS300" not in seen_pairs
    assert "ZZ500/ZZ1000" not in seen_pairs
    assert set(result.attrs["pair_data"]) == set(mod.ADK_OFFICIAL_PAIR_ORDER)


def test_v77_adk_display_labels_describe_official_8pair_pool_without_invalid_pair_warning():
    mod = load_module()

    all_pairs = {f"{a}/{b}" for a, b in combinations(mod.CN_DK_INDICES.keys(), 2)}
    assert set(mod.ADK_OFFICIAL_PAIR_ORDER) == all_pairs - set(mod.ADK_EXCLUDED_PAIR_ORDER)

    assert mod._dk_top_pair_whitelist_warning("SZ50/HS300", "test Top-1") == ""
    assert mod._dk_top_pair_whitelist_warning("ZZ1000/CYB", "test Top-1") == ""


def test_v77_adk_query_copy_has_no_old_10pair_or_warning_wording():
    src = SCRIPT.read_text(encoding="utf-8")

    assert "5指数10配对" not in src
    assert "C(5,2)=10" not in src
    assert "ADK四对白名单" not in src
    assert "ADK弱配对" not in src
    assert "ADK无效配对" not in src
    assert "弱/无效Top-1" not in src
    assert "v6.8.2规则" not in src
    assert "### Sub-A-DK: 多配对Top-1" not in src
    assert "ADK正式8池外配对提示" not in src
    assert "ADK排除配对" not in src
    assert src.count("### Sub-A-DK: 正式8配对Top-1") >= 4

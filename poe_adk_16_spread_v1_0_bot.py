# poe: name=ADK-16-Spread-V1
# poe: privacy_shield=half
"""Poe-native ADK spread signal bot with a local CLI smoke-test path.

The runtime is self-contained: it does not import local scan/final modules.
It fetches current A-share index data online and keeps only compact
parameter metadata embedded for Poe publishing.
"""
import json
import base64
import lzma
import io
import math
import os
import re
import sys
import time
import types
import urllib.request
import zlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable, Optional, Union

import pandas as pd


class _OnlineSignalFrameRef:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def __eq__(self, other: object) -> bool:
        return self is other

try:
    import requests
except Exception:  # pragma: no cover - Poe/local environments without requests
    requests = None


try:
    from fastapi_poe.types import SettingsResponse
except Exception:  # pragma: no cover - local CLI shim
    class SettingsResponse:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)


class _CompatStartMessage:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def write(self, value: str) -> None:
        data = str(value).encode("utf-8", errors="replace")
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()

    def attach_file(self, **kwargs) -> None:
        name = kwargs.get("name", "attachment")
        self.write(f"\n[attachment: {name}]\n")


if "poe" not in globals():
    try:
        import fastapi_poe as poe
    except Exception:
        class _LocalPoe:
            query = types.SimpleNamespace(text=" ".join(sys.argv[1:]), attachments=[])
            default_chat = []

            @staticmethod
            def update_settings(settings):
                return settings

            @staticmethod
            def start_message():
                return _CompatStartMessage()

        poe = _LocalPoe()  # type: ignore[assignment]


def _install_poe_compat(poe_module):
    if hasattr(poe_module, "update_settings") and hasattr(poe_module, "start_message"):
        return poe_module

    class _PoeCompatProxy:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self.query = getattr(wrapped, "query", types.SimpleNamespace(text=" ".join(sys.argv[1:]), attachments=[]))
            self.default_chat = getattr(wrapped, "default_chat", [])
            self._settings = None

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        def update_settings(self, settings):
            update_settings = getattr(self._wrapped, "update_settings", None)
            if update_settings is not None:
                return update_settings(settings)
            self._settings = settings
            return None

        def start_message(self):
            start_message = getattr(self._wrapped, "start_message", None)
            if start_message is not None:
                return start_message()
            return _CompatStartMessage()

    return _PoeCompatProxy(poe_module)


poe = _install_poe_compat(poe)


ROOT = Path(globals()["__file__"]).resolve().parent if "__file__" in globals() else Path.cwd()
OUTPUT_DIR = ROOT / "outputs" / "final_adk_spread"
BJ_TZ = timezone(timedelta(hours=8))
ANNUAL_DAYS = 242.0
ONE_WAY_COST_BPS = 5
EXECUTION_TIMING = "T收盘信号 -> T+1按收盘到收盘价差收益执行，已含单边5bps成本"
ONLINE_FETCH_LOOKBACK_BARS = 5000
ONLINE_REBUILD_LOOKBACK_BARS = 260
MIN_ANNUALIZED_METRIC_ROWS = 60
SNAPSHOT_SCORE_ABS_TOL = 0.5
SNAPSHOT_SCORE_REL_TOL = 0.10
LEGACY_RELATIVE_SCORE_KEYS = {
    "forward_zz1000_hs300",
    "reverse_hs300_zz1000",
    "forward_cyb_hs300",
    "reverse_hs300_cyb",
    "forward_zz1000_sz50",
    "reverse_sz50_zz1000",
}

STATE_SNAPSHOT = {
    "forward_zz1000_hs300": {"as_of": "2026-06-12", "values": {"nav": 2.774600617908, "nav_high": 2.932931431918, "gross_exposure": 0.0, "base_gross_exposure": 0.0, "target_vol_scale": 1.0, "score": -26.297305895275}},
    "reverse_hs300_zz1000": {"as_of": "2026-06-12", "values": {"nav": 2.974021986683, "nav_high": 2.985301182408, "base_nav": 2.998013675902, "base_nav_high": 3.002291075989, "gross_exposure": 0.0, "base_gross_exposure": 0.92433351715, "target_vol_scale": 0.92433351715, "target_vol_raw_scale": 0.899156112483, "score": 22.74904180205}},
    "forward_cyb_zz1000": {"as_of": "2026-06-12", "values": {"nav": 3.020249922019, "nav_high": 3.182602475989, "gross_exposure": 0.0, "base_gross_exposure": 0.0, "target_vol_scale": 0.0, "target_vol_raw_scale": 0.741976076513, "score": -1.115921113765}},
    "reverse_zz1000_cyb": {"as_of": "2026-06-12", "values": {"nav": 1.56769823852, "nav_high": 1.661399533332, "gross_exposure": 0.818486735429, "base_gross_exposure": 0.818486735429, "target_vol_scale": 0.818486735429, "target_vol_raw_scale": 0.818486735429, "score": 6.766934395577}},
    "forward_cyb_hs300": {"as_of": "2026-06-12", "values": {"nav": 4.863016179219, "nav_high": 5.060549541413, "base_nav": 5.579933052483, "base_nav_high": 5.806587230889, "gross_exposure": 0.0, "base_gross_exposure": 0.0, "target_vol_scale": 1.0, "target_vol_raw_scale": 1.0, "score": -10.658816397633}},
    "reverse_hs300_cyb": {"as_of": "2026-06-12", "values": {"nav": 5.210788306701, "nav_high": 5.383896580054, "base_nav": 3.707147690105, "base_nav_high": 3.707147690105, "nav_decay_nav": 3.707147690105, "nav_decay_nav_high": 3.830303323749, "gross_exposure": 0.0, "base_gross_exposure": 0.0, "target_vol_scale": 1.0, "target_vol_raw_scale": 1.0, "score": 19.774988639871, "decay_gate": 1.0, "decay_mult": 0.0}},
    "forward_zz1000_sz50": {"as_of": "2026-06-12", "values": {"nav": 3.172013827796, "nav_high": 3.231228029486, "base_nav": 3.297418687443, "base_nav_high": 3.358973909399, "gross_exposure": 0.0, "base_gross_exposure": 0.0, "target_vol_scale": 0.381628571571, "target_vol_raw_scale": 0.377206792156, "score": -28.176271172283}},
    "reverse_sz50_zz1000": {"as_of": "2026-06-12", "values": {"nav": 3.388301924779, "nav_high": 3.527667372032, "gross_exposure": 0.0, "base_gross_exposure": 1.0, "target_vol_scale": 1.0, "score": 29.451040077473, "nav_defense_gate": 1.0}},
    "forward_cyb_sz50": {"as_of": "2026-06-12", "values": {"nav": 3.521521268556, "nav_high": 3.6430003972, "base_nav": 4.748953353932, "base_nav_high": 4.97131642832, "gross_exposure": 0.0, "base_gross_exposure": 0.0, "target_vol_scale": 1.0, "target_vol_raw_scale": 0.915822218458, "score": -1.514196682145}},
    "reverse_sz50_cyb": {"as_of": "2026-06-12", "values": {"nav": 3.544513026629, "nav_high": 3.685251920166, "gross_exposure": 0.083878502614, "base_gross_exposure": 0.083878502614, "target_vol_scale": 1.0, "decay_gate": 0.0}},
    "forward_zz500_sz50": {"as_of": "2026-06-12", "values": {"nav": 3.285688299949, "nav_high": 3.364608150221, "gross_exposure": 0.0, "base_gross_exposure": 0.0, "target_vol_scale": 1.0, "score": -8.107319458701, "decay_mult": 1.0}},
    "reverse_sz50_zz500": {"as_of": "2026-06-12", "values": {"nav": 2.923011883905, "nav_high": 3.116913297545, "gross_exposure": 0.922980051067, "base_gross_exposure": 0.922980051067, "target_vol_scale": 1.0, "score": 4.880159127596, "decay_mult": 1.0}},
    "forward_hs300_zz500": {"as_of": "2026-06-05", "values": {"nav": 2.196628228962, "nav_high": 2.244068034773, "gross_exposure": 1.057997445795, "base_gross_exposure": 1.057997445795, "target_vol_scale": 1.057997445795, "score": 4.928667688218}},
    "reverse_zz500_hs300": {"as_of": "2026-06-05", "values": {"nav": 3.43833129182, "nav_high": 3.667334713579, "gross_exposure": 0.0, "base_gross_exposure": 0.0, "target_vol_scale": 1.0, "score": -7.692834114414}},
    "forward_cyb_zz500": {"as_of": "2026-06-05", "values": {"nav": 2.634462839157, "nav_high": 2.680931788432, "gross_exposure": 0.643928559043, "base_gross_exposure": 0.643928559043, "target_vol_scale": 1.0, "score": 5.827184943533}},
    "reverse_zz500_cyb": {"as_of": "2026-06-05", "values": {"nav": 1.730314116717, "nav_high": 1.776684724722, "gross_exposure": 0.0, "base_gross_exposure": 0.0, "target_vol_scale": 1.0, "score": -3.650456914588}},
}


class StrategyConfig:
    __slots__ = (
        "key",
        "display_name",
        "short_name",
        "daily_file",
        "metrics_file",
        "direction_cn",
        "direction_en",
        "formal_start_note",
    )

    def __init__(
        self,
        key: str,
        display_name: str,
        short_name: str,
        daily_file: str,
        metrics_file: str,
        direction_cn: str,
        direction_en: str,
        formal_start_note: str,
    ):
        self.key = key
        self.display_name = display_name
        self.short_name = short_name
        self.daily_file = daily_file
        self.metrics_file = metrics_file
        self.direction_cn = direction_cn
        self.direction_en = direction_en
        self.formal_start_note = formal_start_note


STRATEGIES: tuple[StrategyConfig, ...] = (
    StrategyConfig(
        key="forward_zz1000_hs300",
        display_name="中证1000/沪深300 正向",
        short_name="ZZ1000/HS300 正向",
        daily_file="final_forward_zz1000_hs300_nav_low_abs_w40_thr1_days1_scale0p5_daily.csv",
        metrics_file="final_forward_zz1000_hs300_nav_low_abs_w40_thr1_days1_scale0p5_metrics.json",
        direction_cn="做多中证1000 / 做空沪深300",
        direction_en="long ZZ1000 / short HS300",
        formal_start_note="Formal start date constrained by ZZ1000 publication 2014-10-17; no earlier than that."
    ),
    StrategyConfig(
        key="reverse_hs300_zz1000",
        display_name="沪深300/中证1000 反向",
        short_name="HS300/ZZ1000 反向",
        daily_file="final_reverse_hs300_zz1000_return_tvdb0p075_nav_volhot_w25_thr0p14_scale0_daily.csv",
        metrics_file="final_reverse_hs300_zz1000_return_tvdb0p075_nav_volhot_w25_thr0p14_scale0_metrics.json",
        direction_cn="做多沪深300 / 做空中证1000",
        direction_en="long HS300 / short ZZ1000",
        formal_start_note="Formal start date constrained by ZZ1000 publication 2014-10-17; no earlier than that."
    ),
    StrategyConfig(
        key="forward_cyb_zz1000",
        display_name="创业板/中证1000 正向",
        short_name="CYB/ZZ1000 正向",
        daily_file="final_cyb_zz1000_tv14_max1p5_db0p375_volhot_w20_thr0p26_scale0_daily.csv",
        metrics_file="final_cyb_zz1000_tv14_max1p5_db0p375_volhot_w20_thr0p26_scale0_metrics.json",
        direction_cn="做多创业板 / 做空中证1000",
        direction_en="long CYB / short ZZ1000",
        formal_start_note="Formal start date constrained by ZZ1000 publication 2014-10-17; no earlier than that."
    ),
    StrategyConfig(
        key="reverse_zz1000_cyb",
        display_name="中证1000/创业板 反向",
        short_name="ZZ1000/CYB 反向",
        daily_file="substrategy_zz1000_cyb_tv14_db5_cybvol_w60_thr1p05_d6_scale0p25_daily.csv",
        metrics_file="substrategy_zz1000_cyb_tv14_db5_cybvol_w60_thr1p05_d6_scale0p25_metrics.json",
        direction_cn="做多中证1000 / 做空创业板",
        direction_en="long ZZ1000 / short CYB",
        formal_start_note="Formal start date constrained by ZZ1000 publication 2014-10-17; no earlier than that.",
    ),
    StrategyConfig(
        key="forward_cyb_hs300",
        display_name="创业板/沪深300 正向",
        short_name="CYB/HS300 正向",
        daily_file="final_cyb_hs300_return_nav_volhot_w15_thr0p35_scale0_high_pair_w60_thr1p25_scale0p25_daily.csv",
        metrics_file="final_cyb_hs300_return_nav_volhot_w15_thr0p35_scale0_high_pair_w60_thr1p25_scale0p25_metrics.json",
        direction_cn="做多创业板 / 做空沪深300",
        direction_en="long CYB / short HS300",
        formal_start_note="CYB sample requires CHINEXT and SZ/HS300 listing constraints; effective start date 2010-06-01."
    ),
    StrategyConfig(
        key="reverse_hs300_cyb",
        display_name="沪深300/创业板 反向",
        short_name="HS300/CYB 反向",
        daily_file="final_reverse_hs300_cyb_nav_decay_scorehot75_volhot_w120_thr0p26_scale0_daily.csv",
        metrics_file="final_reverse_hs300_cyb_nav_decay_scorehot75_volhot_w120_thr0p26_scale0_metrics.json",
        direction_cn="做多沪深300 / 做空创业板",
        direction_en="long HS300 / short CYB",
        formal_start_note="CYB sample requires CHINEXT and SZ/HS300 listing constraints; effective start date 2010-06-01.",
    ),
    StrategyConfig(
        key="forward_zz1000_sz50",
        display_name="中证1000/上证50 正向",
        short_name="ZZ1000/SZ50 正向",
        daily_file="final_forward_zz1000_sz50_main_q0_tvdb0p075_low_abs_w40_thr1_days3_scale0p75_daily.csv",
        metrics_file="final_forward_zz1000_sz50_main_q0_tvdb0p075_low_abs_w40_thr1_days3_scale0p75_metrics.json",
        direction_cn="做多中证1000 / 做空上证50",
        direction_en="long ZZ1000 / short SZ50",
        formal_start_note="Formal start date constrained by ZZ1000 publication 2014-10-17; no earlier than that."
    ),
    StrategyConfig(
        key="reverse_sz50_zz1000",
        display_name="上证50/中证1000 反向",
        short_name="SZ50/ZZ1000 反向",
        daily_file="final_reverse_sz50_zz1000_return_nav_score_q1_volhot_w20_thr0p18_scale0_daily.csv",
        metrics_file="final_reverse_sz50_zz1000_return_nav_score_q1_volhot_w20_thr0p18_scale0_metrics.json",
        direction_cn="做多上证50 / 做空中证1000",
        direction_en="long SZ50 / short ZZ1000",
        formal_start_note="Formal start date constrained by ZZ1000 publication 2014-10-17; no earlier than that."
    ),
    StrategyConfig(
        key="forward_cyb_sz50",
        display_name="创业板/上证50 正向",
        short_name="CYB/SZ50 正向",
        daily_file="final_cyb_sz50_return_nav6_volhot_w40_thr0p18_scale0p75_cyb_low_w20_thr1_d5_scale0p25_daily.csv",
        metrics_file="final_cyb_sz50_return_nav6_volhot_w40_thr0p18_scale0p75_cyb_low_w20_thr1_d5_scale0p25_metrics.json",
        direction_cn="做多创业板 / 做空上证50",
        direction_en="long CYB / short SZ50",
        formal_start_note="CYB sample requires CHINEXT and SZ/HS300 listing constraints; effective start date 2010-06-01."
    ),
    StrategyConfig(
        key="reverse_sz50_cyb",
        display_name="上证50/创业板 反向",
        short_name="SZ50/CYB 反向",
        daily_file="final_reverse_sz50_cyb_neighbor_downonly_tv16_nav10_decay_volhigh_w60_thr1p25_d3_scale0_daily.csv",
        metrics_file="final_reverse_sz50_cyb_neighbor_downonly_tv16_nav10_decay_volhigh_w60_thr1p25_d3_scale0_metrics.json",
        direction_cn="做多上证50 / 做空创业板",
        direction_en="long SZ50 / short CYB",
        formal_start_note="CYB sample requires CHINEXT and SZ/HS300 listing constraints; effective start date 2010-06-01.",
    ),
    StrategyConfig(
        key="forward_zz500_sz50",
        display_name="中证500/上证50 正向",
        short_name="ZZ500/SZ50 正向",
        daily_file="final_zz500_sz50_width_confirm_decay045_zz500amtlow_w60_thr0p85_d3_scale0p25_daily.csv",
        metrics_file="final_zz500_sz50_width_confirm_decay045_zz500amtlow_w60_thr0p85_d3_scale0p25_metrics.json",
        direction_cn="做多中证500 / 做空上证50",
        direction_en="long ZZ500 / short SZ50",
        formal_start_note="Formal start uses ZZ500 publication 2007-01-15 and SZ50 publication/listing availability; no pre-publication backfill."
    ),
    StrategyConfig(
        key="reverse_sz50_zz500",
        display_name="上证50/中证500 反向",
        short_name="SZ50/ZZ500 反向",
        daily_file="final_sz50_zz500_score0_abs80_tv16_decay030_scorehot18_zz500amthot_w60_thr1p2_scale0p25_daily.csv",
        metrics_file="final_sz50_zz500_score0_abs80_tv16_decay030_scorehot18_zz500amthot_w60_thr1p2_scale0p25_metrics.json",
        direction_cn="做多上证50 / 做空中证500",
        direction_en="long SZ50 / short ZZ500",
        formal_start_note="Formal start uses ZZ500 publication 2007-01-15 and SZ50 publication/listing availability; no pre-publication backfill."
    ),
    StrategyConfig(
        key="forward_hs300_zz500",
        display_name="沪深300/中证500 正向",
        short_name="HS300/ZZ500 正向",
        daily_file="substrategy_hs300_zz500_primary_nav_zz500amthigh_w120_thr1p25_d1_scale0p25_daily.csv",
        metrics_file="substrategy_hs300_zz500_primary_nav_zz500amthigh_w120_thr1p25_d1_scale0p25_metrics.json",
        direction_cn="做多沪深300 / 做空中证500",
        direction_en="long HS300 / short ZZ500",
        formal_start_note="Formal start uses HS300 publication 2005-04-08 and ZZ500 publication 2007-01-15; no pre-publication backfill."
    ),
    StrategyConfig(
        key="reverse_zz500_hs300",
        display_name="中证500/沪深300 反向",
        short_name="ZZ500/HS300 反向",
        daily_file="substrategy_zz500_hs300_purple_mainconfirm_amtlow_volridge_daily.csv",
        metrics_file="substrategy_zz500_hs300_purple_mainconfirm_amtlow_volridge_metrics.json",
        direction_cn="做多中证500 / 做空沪深300",
        direction_en="long ZZ500 / short HS300",
        formal_start_note="Formal start uses HS300 publication 2005-04-08 and ZZ500 publication 2007-01-15; no pre-publication backfill."
    ),
    StrategyConfig(
        key="forward_cyb_zz500",
        display_name="创业板/中证500 正向",
        short_name="CYB/ZZ500 正向",
        daily_file="substrategy_cyb_zz500_primary_nav3_volridge_daily.csv",
        metrics_file="substrategy_cyb_zz500_primary_nav3_volridge_metrics.json",
        direction_cn="做多创业板 / 做空中证500",
        direction_en="long CYB / short ZZ500",
        formal_start_note="Formal start uses CYB publication 2010-06-01 and ZZ500 publication 2007-01-15; no pre-publication backfill."
    ),
    StrategyConfig(
        key="reverse_zz500_cyb",
        display_name="中证500/创业板 反向",
        short_name="ZZ500/CYB 反向",
        daily_file="substrategy_zz500_cyb_confirm_strict_decay_volhot_amtlow_daily.csv",
        metrics_file="substrategy_zz500_cyb_confirm_strict_decay_volhot_amtlow_metrics.json",
        direction_cn="做多中证500 / 做空创业板",
        direction_en="long ZZ500 / short CYB",
        formal_start_note="Formal start uses CYB publication 2010-06-01 and ZZ500 publication 2007-01-15; no pre-publication backfill."
    ),
)


PAIR_DEFS = (
    ("zz1000_hs300_pair50", "中证1000/沪深300 正反50/50", "forward_zz1000_hs300", "reverse_hs300_zz1000"),
    ("cyb_zz1000_pair50", "创业板/中证1000 正反50/50", "forward_cyb_zz1000", "reverse_zz1000_cyb"),
    ("cyb_hs300_pair50", "创业板/沪深300 正反50/50", "forward_cyb_hs300", "reverse_hs300_cyb"),
    ("zz1000_sz50_pair50", "中证1000/上证50 正反50/50", "forward_zz1000_sz50", "reverse_sz50_zz1000"),
    ("cyb_sz50_pair50", "创业板/上证50 正反50/50", "forward_cyb_sz50", "reverse_sz50_cyb"),
    ("zz500_sz50_pair50", "中证500/上证50 正反50/50", "forward_zz500_sz50", "reverse_sz50_zz500"),
    ("hs300_zz500_pair50", "沪深300/中证500 正反50/50", "forward_hs300_zz500", "reverse_zz500_hs300"),
    ("cyb_zz500_pair50", "创业板/中证500 正反50/50", "forward_cyb_zz500", "reverse_zz500_cyb"),
)

PAIR_CHART_LABELS = {
    "zz1000_hs300_pair50": "ZZ1000/HS300 50/50",
    "cyb_zz1000_pair50": "CYB/ZZ1000 50/50",
    "cyb_hs300_pair50": "CYB/HS300 50/50",
    "zz1000_sz50_pair50": "ZZ1000/SZ50 50/50",
    "cyb_sz50_pair50": "CYB/SZ50 50/50",
    "zz500_sz50_pair50": "ZZ500/SZ50 50/50",
    "hs300_zz500_pair50": "HS300/ZZ500 50/50",
    "cyb_zz500_pair50": "CYB/ZZ500 50/50",
}

CN_PRICE_SECIDS = {
    "zz1000": "1.000852",
    "hs300": "1.000300",
    "cyb": "0.399006",
    "sz50": "1.000016",
    "zz500": "1.000905",
}

CN_CSI_AMOUNT_INDEX_CODES = {
    "1.000016": "000016",
    "1.000300": "000300",
    "1.000852": "000852",
    "1.000905": "000905",
}

CN_SINA_SYMBOLS = {
    "zz1000": "sh000852",
    "hs300": "sh000300",
    "cyb": "sz399006",
    "sz50": "sh000016",
    "zz500": "sh000905",
}

CN_TENCENT_SYMBOLS = CN_SINA_SYMBOLS

CN_ASSET_NAMES = {
    "zz1000": "中证1000",
    "hs300": "沪深300",
    "cyb": "创业板",
    "sz50": "上证50",
    "zz500": "中证500",
}

STRATEGY_LEGS = {
    "forward_zz1000_hs300": ("zz1000", "hs300"),
    "reverse_hs300_zz1000": ("hs300", "zz1000"),
    "forward_cyb_zz1000": ("cyb", "zz1000"),
    "reverse_zz1000_cyb": ("zz1000", "cyb"),
    "forward_cyb_hs300": ("cyb", "hs300"),
    "reverse_hs300_cyb": ("hs300", "cyb"),
    "forward_zz1000_sz50": ("zz1000", "sz50"),
    "reverse_sz50_zz1000": ("sz50", "zz1000"),
    "forward_cyb_sz50": ("cyb", "sz50"),
    "reverse_sz50_cyb": ("sz50", "cyb"),
    "forward_zz500_sz50": ("zz500", "sz50"),
    "reverse_sz50_zz500": ("sz50", "zz500"),
    "forward_hs300_zz500": ("hs300", "zz500"),
    "reverse_zz500_hs300": ("zz500", "hs300"),
    "forward_cyb_zz500": ("cyb", "zz500"),
    "reverse_zz500_cyb": ("zz500", "cyb"),
}

ONLINE_DISABLED = os.environ.get("POE_ADK_DISABLE_ONLINE", "").strip().lower() in {"1", "true", "yes", "on"}
POE_MODE = "poe_online_rebuild"
POE_ONLINE_ONLY = True


_EMBEDDED_ARTIFACT_BLOB = (
    '{Wp48S^xk9=GL@E0stWa8~^|S5YJf50RRC200000hgwQemrW2t009~T+%BblAGY&-0RR9100dcD'
)


_EMBEDDED_ARTIFACT_CACHE: Optional[dict[str, bytes]] = None


FALLBACK_STRATEGY_METAS: dict[str, dict] = {'forward_cyb_hs300': {'amount_overheat': {'enabled': True,
                                           'family': 'high_pair',
                                           'scale': 0.25,
                                           'series': 'cyb_amount / hs300_amount',
                                           'threshold': 1.25,
                                           'timing': 'T close amount condition shifted to T+1 execution',
                                           'window': 60},
                       'annualization_days': 242.0,
                       'asset_curve': 'ChiNext price index / CSI300 price index',
                       'baseline': {'label': 'score>-2.5 TV-off + NAV 7.5% scale 0.25',
                                    'line': 'return_nav',
                                    'source_line': 'return_nav_main',
                                    'source_quadrant': 'q1'},
                       'combination_rule': 'final exposure = baseline exposure * vol multiplier * amount multiplier',
                       'common_end': '2026-06-05',
                       'common_start': '2010-06-01',
                       'cost_model': {'one_way_cost_bps': 5.0},
                       'direction': 'long CYB / short HS300',
                       'display_name': '创业板/沪深300 正向',
                       'formal_start': '2010-06-01',
                       'nav_defense': {'enabled': True,
                                       'scale': 0.25,
                                       'threshold': 0.075,
                                       'timing': 'prior-row pre-overlay candidate NAV drawdown'},
                       'poe_strategy_key': 'forward_cyb_hs300',
                       'signal': {'abs_mom_day': 20,
                                  'abs_threshold': 0.0,
                                  'bias_ma': 60,
                                  'mom_day': 30,
                                  'score_threshold': -2.5,
                                  'weight_end': 3.5},
                       'strategy_id': 'forward_cyb_hs300',
                       'target_vol': {'enabled': False, 'max_leverage': 1.0},
                       'vol_overheat': {'enabled': True,
                                        'scale': 0.0,
                                        'threshold': 0.35,
                                        'timing': 'prior-row realized volatility',
                                        'window': 15}},
 'forward_cyb_sz50': {'amount_overlay': {'confirm_days': 5,
                                         'enabled': True,
                                         'family': 'cyb_low',
                                         'scale': 0.25,
                                         'series': 'cyb_amount / cyb_amount_rolling_mean',
                                         'threshold': 1.0,
                                         'timing': 'T close amount condition shifted to T+1 execution',
                                         'unit_warning': 'raw CYB and SZ50 amount units differ; this rule uses CYB '
                                                         'own-MA relative amount only',
                                         'window': 20},
                      'annualization_days': 242,
                      'asset_curve': 'ChiNext price index / SSE50 price index',
                      'baseline': {'label': 'score>5, abs30>1.5%, TV24%, NAV6% scale75%, volhot40>18% scale75%',
                                   'line': 'main_nav6_volhot_w40'},
                      'combination_rule': 'final exposure = target-vol baseline exposure * NAV multiplier * volhot '
                                          'multiplier * CYB-low-amount multiplier',
                      'common_end': '2026-06-12',
                      'common_start': '2010-06-01',
                      'cost_model': {'execution': 'T close signal -> T+1 close-to-close return',
                                     'legs': 2,
                                     'one_way_commission': 0.0005},
                      'direction': 'long CYB / short SZ50',
                      'formal_start': '2010-06-01',
                      'nav_defense': {'enabled': True,
                                      'scale': 0.75,
                                      'threshold': 0.06,
                                      'timing': 'prior-row pre-overlay candidate NAV drawdown'},
                      'signal': {'abs_mom_day': 30,
                                 'abs_threshold': 0.015,
                                 'bias_ma': 80,
                                 'mom_day': 28,
                                 'r2_threshold': 0.05,
                                 'score_threshold': 5.0,
                                 'weight_end': 2.5},
                      'strategy_id': 'final_cyb_sz50_return_nav6_volhot_w40_thr0p18_scale0p75_cyb_low_w20_thr1_d5_scale0p25',
                      'target_vol': {'enabled': True,
                                     'gate': 0.1,
                                     'max_leverage': 1.5,
                                     'min_leverage': 0.1,
                                     'target_vol': 0.24,
                                     'target_vol_window': 30},
                      'vol_overheat': {'enabled': True,
                                       'scale': 0.75,
                                       'threshold': 0.18,
                                       'timing': 'prior-row realized volatility',
                                       'window': 40}},
 'forward_cyb_zz1000': {'annualization_days': 242,
                        'asset_curve': 'ChiNext price index / CSI 1000 price index',
                        'candidate': 'stage2_tv14_max1p5_db0p375_volhot_w20_thr0p26_scale0p0',
                        'combination_rule': 'final exposure = target-vol deadbanded exposure * volhot multiplier',
                        'common_end': '2026-06-12',
                        'common_start': '2014-10-17',
                        'cost_model': {'execution': 'T close signal/state -> T+1 close-to-close spread return',
                                       'legs': 2,
                                       'one_way_commission': 0.0005},
                        'direction': 'long CYB / short ZZ1000',
                        'formal_start': '2014-10-17',
                        'signal': {'abs_mom_day': 35,
                                   'abs_threshold': -0.03,
                                   'bias_ma': 50,
                                   'mom_day': 20,
                                   'r2_threshold': 0.05,
                                   'score_threshold': 1.0,
                                   'weight_end': 4.0},
                        'strategy_id': 'final_cyb_zz1000_tv14_max1p5_db0p375_volhot_w20_thr0p26_scale0',
                        'target_vol': {'deadband_timing': 'during active holding, keep last scale unless absolute '
                                                          'raw-scale change exceeds deadband',
                                       'enabled': True,
                                       'max_leverage': 1.5,
                                       'min_leverage': 0.1,
                                       'scale_deadband': 0.375,
                                       'target_vol': 0.14,
                                       'target_vol_window': 20},
                        'vol_overheat': {'active_days_full': 93,
                                         'enabled': True,
                                         'rescan_note': 'Downstream rescan selected w20/thr0.26/scale0.0; trigger days '
                                                        'are cut to zero exposure.',
                                         'scale': 0.0,
                                         'threshold': 0.26,
                                         'timing': 'prior-row spread realized volatility controls next execution '
                                                   'exposure',
                                         'window': 20}},
 'forward_cyb_zz500': {'amount_overlay': {'confirm_days': 1,
                                          'enabled': True,
                                          'feature': 'pair_amount_high',
                                          'scale': 0.0,
                                          'source': 'Sohu amount',
                                          'threshold': 1.5,
                                          'timing': 'T close amount condition shifted to T+1 execution',
                                          'window': 20},
                       'annualization_days': 242,
                       'asset_curve': 'ChiNext price index / CSI500 price index',
                       'baseline': {'final_candidate': 'l11ridge_primary_nav3_cyb_volume_high_w100_thr1p75_d3_scale0',
                                    'layer10_candidate': 'l10vol_primary_nav3_cyb_volume_high_w60_thr1p75_d3_scale0p75',
                                    'layer7_candidate': 'l7_primary_nav3_volhot_w40_thr26_scale0p5',
                                    'layer9_candidate': 'l9amt_primary_nav3_pair_amount_high_w20_thr1p5_d1_scale0',
                                    'line': 'primary_nav3',
                                    'line_role': 'primary_width_watchlist',
                                    'source_candidate': 'l3_primary_30_28_we3_s1_abs30_p1p5_tv10_rv120_max1p5_floor0p5_dbrel15'},
                       'candidate': 'l11ridge_primary_nav3_cyb_volume_high_w100_thr1p75_d3_scale0',
                       'combination_rule': 'final exposure = target-vol signal * NAV-DD defense * volhot * amount gate '
                                           '* Layer10 volume gate * final-ridge volume gate',
                       'common_end': '2026-06-05',
                       'common_start': '2010-06-01',
                       'cost_model': {'execution': 'T close signal/state -> T+1 close-to-close return',
                                      'financing_borrow_or_basis': 'excluded',
                                      'legs': 2,
                                      'one_way_commission': 0.0005,
                                      'short_locate_or_borrow': 'excluded',
                                      'slippage': 'excluded'},
                       'direction': 'long CYB / short ZZ500',
                       'final_ridge_overlay': {'confirm_days': 3,
                                               'enabled': True,
                                               'feature': 'cyb_volume_high',
                                               'scale': 0.0,
                                               'threshold': 1.75,
                                               'timing': 'T close final-ridge volume condition shifted to T+1 '
                                                         'execution',
                                               'window': 100},
                       'formal_start': '2010-06-01',
                       'layer10_volume_overlay': {'confirm_days': 3,
                                                  'enabled': True,
                                                  'feature': 'cyb_volume_high',
                                                  'scale': 0.75,
                                                  'threshold': 1.75,
                                                  'window': 60},
                       'long_leg': 'CYB',
                       'nav_defense': {'defense_scale': 0.5,
                                       'enabled': True,
                                       'nav_dd_threshold': -0.03,
                                       'timing': 'prior-row pre-overlay NAV drawdown shifted to next execution row'},
                       'profile': 'primary_nav3',
                       'result_status': 'quasi-formal fixed research script; close-to-close index spread with V7.7 '
                                        'amount/volume fallback overlays and commission costs',
                       'short_leg': 'ZZ500',
                       'signal': {'abs_ma': 30,
                                  'abs_threshold': 0.015,
                                  'anchor': 'bias_30_28_we3',
                                  'bias_ma': 30,
                                  'family': 'bias_momentum',
                                  'mom_day': 28,
                                  'r2_threshold': 0.05,
                                  'score_threshold': 1.0,
                                  'weight_end': 3.0},
                       'strategy_id': 'substrategy_cyb_zz500_primary_nav3_volridge',
                       'substrategy_id': 'substrategy_cyb_zz500_primary_nav3_volridge',
                       'target_vol': {'deadband_mode': 'rel',
                                      'deadband_value': 0.15,
                                      'enabled': True,
                                      'max_leverage': 1.5,
                                      'min_scale': 0.5,
                                      'target_vol': 0.1,
                                      'target_vol_window': 120},
                       'volhot_overlay': {'enabled': True,
                                          'scale': 0.5,
                                          'threshold': 0.26,
                                          'timing': 'prior-row realized spread volatility shifted to next execution '
                                                    'row',
                                          'window': 40.0}},
 'forward_hs300_zz500': {'amount_overlay': {'confirm_days': 1,
                                            'enabled': True,
                                            'feature': 'zz500_amount_high',
                                            'scale': 0.25,
                                            'series': 'ZZ500_amount / ZZ500_amount_rolling_mean',
                                            'source': 'EastMoney amount',
                                            'threshold': 1.25,
                                            'timing': 'T close amount condition shifted to T+1 execution',
                                            'window': 120},
                         'annualization_days': 242,
                         'asset_curve': 'CSI300 price index / CSI500 price index',
                         'baseline': {'label': 'Layer 6 NAV-only primary line plus Layer 10 ZZ500 high-amount final '
                                               'ridge',
                                      'line': 'primary_nav_only',
                                      'source_candidate': 'l6_primary_q_nav_only'},
                         'candidate': 'l10ridge_primary_nav_only_zz500_amount_high_w120_thr1p25_d1_scale0p25',
                         'combination_rule': 'final exposure = NAV-only target-vol signal exposure * ZZ500-high-amount '
                                             'multiplier',
                         'common_end': '2026-06-05',
                         'common_start': '2007-01-15',
                         'cost_model': {'execution': 'T close signal/state -> T+1 close-to-close return',
                                        'financing_borrow_or_basis': 'excluded',
                                        'legs': 2,
                                        'one_way_commission': 0.0005,
                                        'short_locate_or_borrow': 'excluded',
                                        'slippage': 'excluded'},
                         'direction': 'long HS300 / short ZZ500',
                         'formal_start': '2007-01-15',
                         'long_leg': 'HS300',
                         'nav_defense': {'defense_scale': 0.5,
                                         'enabled': True,
                                         'nav_threshold': 0.0875,
                                         'timing': 'prior-row pre-overlay NAV drawdown shifted to next execution row'},
                         'result_status': 'quasi-formal fixed research script; close-to-close index spread with '
                                          'EastMoney amount overlay and commission costs',
                         'short_leg': 'ZZ500',
                         'signal': {'abs_ma': 30,
                                    'abs_threshold': -0.005,
                                    'anchor': 'bias_60_18_we2p5',
                                    'bias_ma': 60,
                                    'mom_day': 18,
                                    'r2_threshold': 0.05,
                                    'score_threshold': 0.0,
                                    'weight_end': 2.5},
                         'strategy_id': 'substrategy_hs300_zz500_primary_nav_zz500amthigh_w120_thr1p25_d1_scale0p25',
                         'substrategy_id': 'substrategy_hs300_zz500_primary_nav_zz500amthigh_w120_thr1p25_d1_scale0p25',
                         'target_vol': {'deadband_mode': 'rel',
                                        'deadband_value': 0.15,
                                        'enabled': True,
                                        'max_leverage': 2.0,
                                        'min_scale': 0.0,
                                        'target_vol': 0.12,
                                        'target_vol_window': 20}},
 'forward_zz1000_hs300': {'amount_overlay': {'confirm_days': 1,
                                             'enabled': True,
                                             'family': 'low_abs',
                                             'scale': 0.5,
                                             'series': 'zz1000_amount',
                                             'source': 'CSIndex official amount export',
                                             'threshold': 1.0,
                                             'timing': 'T close amount condition shifted to T+1 execution',
                                             'window': 40},
                          'annualization_days': 242.0,
                          'asset_curve': 'CSI1000 price index / CSI300 price index',
                          'common_end': '2026-06-12',
                          'common_start': '2014-10-17',
                          'cost_model': {'cost': 'turnover * 5bp', 'one_way_cost_bps': 5.0},
                          'direction': 'long ZZ1000 / short HS300',
                          'display_name': '中证1000/沪深300 正向',
                          'formal_start': '2014-10-17',
                          'nav_defense': {'enabled': True,
                                          'scale': 0.0,
                                          'threshold': 0.0875,
                                          'timing': 'prior-row pre-overlay candidate NAV drawdown'},
                          'poe_strategy_key': 'forward_zz1000_hs300',
                          'signal': {'abs_mom_day': 50,
                                     'abs_threshold': -0.05,
                                     'bias_ma': 60,
                                     'mom_day': 20,
                                     'r2_filter': False,
                                     'score_threshold': 0.0,
                                     'weight_end': 1.0},
                          'strategy_id': 'final_forward_zz1000_hs300_nav_low_abs_w40_thr1_days1_scale0p5',
                          'target_vol': {'enabled': False, 'max_leverage': 1.0}},
 'forward_zz1000_sz50': {'amount_overlay': {'confirm_days': 3,
                                            'enabled': True,
                                            'family': 'low_abs',
                                            'scale': 0.75,
                                            'series': 'zz1000_amount',
                                            'threshold': 1.0,
                                            'timing': 'T close amount condition shifted to T+1 execution',
                                            'window': 40},
                         'annualization_days': 242.0,
                         'asset_curve': 'CSI1000 price index / SSE50 price index',
                         'baseline': {'label': 'main target-vol line, no defense',
                                      'line': 'main_q0',
                                      'source_line': 'main_stable_tv',
                                      'source_quadrant': 'q0'},
                         'combination_rule': 'final exposure = target-vol baseline exposure * amount multiplier',
                         'common_end': '2026-06-05',
                         'common_start': '2014-10-17',
                         'cost_model': {'one_way_cost_bps': 5.0},
                         'direction': 'long ZZ1000 / short SZ50',
                         'display_name': '中证1000/上证50 正向',
                         'formal_start': '2014-10-17',
                         'momentum_decay': {'decay_threshold': 0.65,
                                            'derisk_scale': 0.5,
                                            'enabled': False,
                                            'recovery_threshold': 0.8,
                                            'timing': 'prior-row signal-day decay state',
                                            'warmup_days': 5},
                         'nav_defense': {'enabled': False,
                                         'scale': 0.0,
                                         'threshold': 0.1,
                                         'timing': 'prior-row pre-overlay candidate NAV drawdown'},
                         'poe_strategy_key': 'forward_zz1000_sz50',
                         'signal': {'abs_mom_day': 50,
                                    'abs_threshold': -0.05,
                                    'bias_ma': 60,
                                    'mom_day': 20,
                                    'score_threshold': 0.0,
                                    'weight_end': 2.5},
                         'strategy_id': 'forward_zz1000_sz50',
                         'target_vol': {'deadband': 0.075,
                                        'deadband_rule': 'keep previous effective scale when abs(raw_scale / '
                                                         'previous_effective_scale - 1) < deadband',
                                        'deadband_type': 'relative_scale_change',
                                        'enabled': True,
                                        'max_leverage': 1.0,
                                        'target_vol': 0.08,
                                        'target_vol_window': 20}},
 'forward_zz500_sz50': {'amount_overlay': {'confirm_days': 3,
                                           'enabled': True,
                                           'feature': 'zz500_amount_low',
                                           'scale': 0.25,
                                           'series': 'zz500_amount / zz500_amount_rolling_mean',
                                           'source': 'CSIndex official tradingValue/amount',
                                           'threshold': 0.85,
                                           'timing': 'T close amount condition shifted to T+1 execution',
                                           'window': 60},
                        'annualization_days': 242,
                        'asset_curve': 'CSI500 price index / SSE50 price index',
                        'baseline': {'label': 'width-confirm Layer 6 decay-only line plus Layer 9 CSIndex ZZ500 '
                                              'low-amount filter',
                                     'line': 'width_confirm_decay_only',
                                     'source_candidate': 'l6_width_confirm_q_decay_only'},
                        'candidate': 'l9amt_width_confirm_decay_only_zz500_amount_low_w60_thr0p85_d3_scale0p25',
                        'combination_rule': 'final exposure = target-vol signal exposure * momentum-decay multiplier * '
                                            'ZZ500-low-amount multiplier',
                        'common_end': '2026-06-12',
                        'common_start': '2007-01-15',
                        'cost_model': {'execution': 'T close signal/state -> T+1 close-to-close return',
                                       'financing_borrow_or_basis': 'excluded',
                                       'legs': 2,
                                       'one_way_commission': 0.0005,
                                       'slippage': 'excluded'},
                        'direction': 'long ZZ500 / short SZ50',
                        'formal_start': '2007-01-15',
                        'momentum_decay': {'decay_threshold': 0.45,
                                           'basis': 'score',
                                           'enabled': True,
                                           'recovery_threshold': 0.9,
                                           'scale': 0.0,
                                           'timing': 'T close score-peak decay state shifted to T+1 execution',
                                           'warmup_days': 10},
                        'result_status': 'quasi-formal fixed research script; close-to-close index spread with CSIndex '
                                         'official amount overlay and commission costs',
                        'signal': {'abs_ma': 65,
                                   'abs_threshold': -0.02,
                                   'bias_ma': 115,
                                   'family': 'bias_momentum',
                                   'mom_day': 22,
                                   'r2_threshold': 0.05,
                                   'score_threshold': 2.0,
                                   'weight_end': 2.75},
                        'strategy_id': 'final_zz500_sz50_width_confirm_decay045_zz500amtlow_w60_thr0p85_d3_scale0p25',
                        'target_vol': {'enabled': True,
                                       'max_leverage': 1.25,
                                       'min_leverage': 0.1,
                                       'scale_deadband': 0.3,
                                       'target_vol': 0.12,
                                       'target_vol_window': 40}},
 'reverse_hs300_cyb': {'annualization_days': 242.0,
                       'asset_curve': 'CSI300 price index / ChiNext price index',
                       'combination_rule': 'final exposure = NAV/decay exposure * scorehot multiplier * volhot '
                                           'multiplier',
                       'common_end': '2026-06-05',
                       'common_start': '2010-06-01',
                       'cost_model': {'one_way_cost_bps': 5.0},
                       'direction': 'long HS300 / short CYB',
                       'display_name': '沪深300/创业板 反向',
                       'formal_start': '2010-06-01',
                       'momentum_decay': {'decay_threshold': 0.7,
                                          'basis': 'score',
                                          'enabled': True,
                                          'recovery_threshold': 0.8,
                                          'scale': 0.0,
                                          'timing': 'signal-day decay scale shifted to next-row execution',
                                          'warmup_days': 10},
                       'nav_defense': {'enabled': True,
                                       'scale': 0.75,
                                       'threshold': 0.075,
                                       'timing': 'prior-row pre-overlay candidate NAV drawdown'},
                       'poe_strategy_key': 'reverse_hs300_cyb',
                       'score_overheat': {'enabled': True,
                                          'scale': 0.0,
                                          'threshold': 75.0,
                                          'timing': 'prior-row score'},
                       'signal': {'abs_mom_day': 80,
                                  'abs_threshold': 0.0,
                                  'bias_ma': 60,
                                  'mom_day': 25,
                                  'score_threshold': -10.0,
                                  'weight_end': 2.5},
                       'strategy_id': 'reverse_hs300_cyb',
                       'target_vol': {'enabled': False, 'max_leverage': 1.0},
                       'vol_overheat': {'enabled': True,
                                        'scale': 0.0,
                                        'threshold': 0.26,
                                        'timing': 'prior-row realized volatility',
                                        'window': 120}},
 'reverse_hs300_zz1000': {'annualization_days': 242.0,
                          'asset_curve': 'CSI300 price index / CSI1000 price index',
                          'common_end': '2026-06-05',
                          'common_start': '2014-10-17',
                          'cost_model': {'one_way_cost_bps': 5.0},
                          'direction': 'long HS300 / short ZZ1000',
                          'display_name': '沪深300/中证1000 反向',
                          'formal_start': '2014-10-17',
                          'nav_defense': {'enabled': True,
                                          'scale': 0.5,
                                          'threshold': 0.075,
                                          'timing': 'prior-row pre-overlay Layer 4 NAV drawdown'},
                          'poe_strategy_key': 'reverse_hs300_zz1000',
                          'signal': {'abs_mom_day': 20,
                                     'abs_threshold': -0.05,
                                     'bias_ma': 60,
                                     'mom_day': 20,
                                     'score_threshold': 2.5,
                                     'weight_end': 3.0},
                          'strategy_id': 'reverse_hs300_zz1000',
                          'target_vol': {'deadband': 0.075,
                                         'deadband_rule': 'keep previous effective scale when abs(raw_scale / '
                                                          'previous_effective_scale - 1) < deadband',
                                         'deadband_type': 'relative_scale_change',
                                         'enabled': True,
                                         'max_leverage': 1.5,
                                         'target_vol': 0.14,
                                         'target_vol_window': 20},
                          'vol_overheat': {'enabled': True,
                                           'scale': 0.0,
                                           'threshold': 0.14,
                                           'timing': 'prior-row realized volatility',
                                           'window': 25}},
 'reverse_sz50_cyb': {'annualization_days': 242,
                      'asset_curve': 'SSE50 price index / ChiNext price index',
                      'baseline': {'branch': 'neighbor_nav10_s025_decay030_rec080_w3_s0',
                                   'label': 'neighbor signal, TV16%, NAV10% scale25%, momentum decay to cash, '
                                            'down-only TV cap, SZ50 high-volume cash gate',
                                   'line': 'neighbor_downonly_tv16_w30_min0',
                                   'role': 'defensive_neighbor'},
                      'candidate': 'l7vol_neighbor_downonly_tv16_w30_min0_sz50_vol_high_w60_thr1p25_d3_scale0',
                      'combination_rule': 'final exposure = target-vol baseline exposure * NAV multiplier * '
                                          'score-decay multiplier * down-only-TV multiplier * SZ50-high-volume '
                                          'multiplier',
                      'common_end': '2026-06-12',
                      'common_start': '2010-06-01',
                      'cost_model': {'execution': 'T close signal -> T+1 close-to-close return',
                                     'legs': 2,
                                     'one_way_commission': 0.0005},
                      'direction': 'long SZ50 / short CYB',
                      'formal_start': '2010-06-01',
                      'momentum_decay': {'decay_threshold': 0.3,
                                         'basis': 'score',
                                         'enabled': True,
                                         'recovery_threshold': 0.8,
                                         'scale': 0.0,
                                         'timing': 'score peak decay shifted to next execution row',
                                         'warmup_days': 3},
                      'nav_defense': {'enabled': True,
                                      'scale': 0.25,
                                      'threshold': 0.1,
                                      'timing': 'prior-row pre-overlay candidate NAV drawdown'},
                      'overheat': {'enabled': True,
                                   'gate': 0.09,
                                   'kind': 'downonly_tv',
                                   'min_scale': 0.0,
                                   'target_vol': 0.16,
                                   'timing': 'prior-row realized volatility cap',
                                   'window': 30},
                      'signal': {'abs_mom_day': 15,
                                 'abs_threshold': -0.07,
                                 'bias_ma': 30,
                                 'mom_day': 32,
                                 'r2_threshold': 0.05,
                                 'score_threshold': 1.0,
                                 'weight_end': 3.5},
                      'strategy_id': 'final_reverse_sz50_cyb_neighbor_downonly_tv16_nav10_decay_volhigh_w60_thr1p25_d3_scale0',
                      'target_vol': {'enabled': True,
                                     'max_leverage': 1.25,
                                     'min_leverage': 0.1,
                                     'target_vol': 0.16,
                                     'target_vol_window': 20},
                      'volume_overlay': {'confirm_days': 3,
                                         'enabled': True,
                                         'family': 'sz50_vol_high',
                                         'scale': 0.0,
                                         'series': 'sz50_volume / sz50_volume_rolling_mean',
                                         'threshold': 1.25,
                                         'timing': 'T close volume condition shifted to T+1 execution',
                                         'window': 60}},
 'reverse_sz50_zz1000': {'amount_overlay': {'enabled': False,
                                            'reason': 'Layer 10 high_abs remains watchlist evidence; not promoted into '
                                                      'the fixed final runner.'},
                         'annualization_days': 242.0,
                         'asset_curve': 'SSE50 price index / CSI1000 price index',
                         'common_end': '2026-06-12',
                         'common_start': '2014-10-17',
                         'cost_model': {'cost': 'turnover * 5bp', 'one_way_cost_bps': 5.0},
                         'direction': 'long SZ50 / short ZZ1000',
                         'display_name': '上证50/中证1000 反向',
                         'formal_start': '2014-10-17',
                         'nav_defense': {'enabled': True,
                                         'scale': 0.75,
                                         'threshold': 0.04,
                                         'timing': 'prior-row pre-overlay candidate NAV drawdown'},
                         'poe_strategy_key': 'reverse_sz50_zz1000',
                         'signal': {'abs_mom_day': 10,
                                    'abs_threshold': -0.075,
                                    'bias_ma': 60,
                                    'mom_day': 20,
                                    'r2_filter': False,
                                    'score_threshold': 0.0,
                                    'weight_end': 3.5},
                         'strategy_id': 'final_reverse_sz50_zz1000_return_nav_score_q1_volhot_w20_thr0p18_scale0',
                         'target_vol': {'enabled': False,
                                        'max_leverage': 1.0,
                                        'target_vol': None,
                                        'target_vol_window': None},
                         'vol_overheat': {'enabled': True,
                                          'scale': 0.0,
                                          'threshold': 0.18,
                                          'timing': 'spread close realized volatility shifted to T+1 execution',
                                          'window': 20}},
 'reverse_sz50_zz500': {'amount_overlay': {'enabled': True,
                                           'kind': 'zz500_amt_hot',
                                           'scale': 0.25,
                                           'series': 'ZZ500_amount / ZZ500_amount_rolling_mean',
                                           'threshold': 1.2,
                                           'timing': 'T close amount condition shifted to T+1 execution',
                                           'window': 60},
                        'annualization_days': 242,
                        'asset_curve': 'SSE50 price index / CSI500 price index',
                        'baseline': {'label': 'Layer 6 primary after rejected NAV and rejected entry staging',
                                     'layer6_candidate': 'l6_return_s0_decay030_rec080_w3_s025_scorehot18_scale0p25',
                                     'line': 'primary_scorehot18_s025'},
                        'candidate': 'l8_primary_scorehot18_s025_zz500_amthot_w60_thr1p2_scale0p25',
                        'combination_rule': 'final exposure = target-vol signal exposure * momentum-decay multiplier * '
                                            'scorehot multiplier * ZZ500-amount-hot multiplier',
                        'common_end': '2026-06-12',
                        'common_start': '2007-01-15',
                        'cost_model': {'execution': 'T close signal -> T+1 close-to-close return',
                                       'legs': 2,
                                       'one_way_commission': 0.0005},
                        'direction': 'long SZ50 / short ZZ500',
                        'formal_start': '2007-01-15',
                        'momentum_decay': {'decay_threshold': 0.3,
                                           'basis': 'score_strength',
                                           'enabled': True,
                                           'recovery_threshold': 0.8,
                                           'scale': 0.25,
                                           'timing': 'T close score-peak decay state shifted to T+1 execution',
                                           'warmup_days': 3},
                        'result_status': 'quasi-formal research fixed script; close-to-close index spread with amount '
                                         'overlay and commission costs',
                        'score_overheat': {'enabled': True,
                                           'kind': 'scorehot',
                                           'scale': 0.25,
                                           'score_threshold': 18.0,
                                           'timing': 'prior-row score state'},
                        'signal': {'abs_ma': 80,
                                   'abs_threshold': -0.05,
                                   'bias_ma': 60,
                                   'mom_day': 18,
                                   'r2_threshold': 0.05,
                                   'score_threshold': 0.0,
                                   'weight_end': 2.75},
                        'strategy_id': 'final_sz50_zz500_score0_abs80_tv16_decay030_scorehot18_zz500amthot_w60_thr1p2_scale0p25',
                        'target_vol': {'enabled': True,
                                       'max_leverage': 1.5,
                                       'min_leverage': 0.1,
                                       'scale_deadband': 0.3,
                                       'target_vol': 0.16,
                                       'target_vol_window': 20}},
 'reverse_zz1000_cyb': {'annualization_days': 242,
                        'common_end': '2026-06-12',
                        'common_start': '2014-10-17',
                        'cost_model': {'execution': 'T close signal/state -> T+1 close-to-close spread return',
                                       'legs': 2,
                                       'one_way_commission': 0.0005},
                        'direction': 'long ZZ1000 / short CYB',
                        'formal_start': '2014-10-17',
                        'line': {'abs_ma': 70,
                                 'abs_threshold': -0.07,
                                 'bias_ma': 60,
                                 'line': 'primary_tv14_vw60_max1p25_db0p05',
                                 'line_role': 'formal_carry',
                                 'max_leverage': 1.25,
                                 'mom_day': 12,
                                 'scale_deadband': 0.05,
                                 'score_threshold': 2.0,
                                 'source_line': 'primary_s2_abs70_m7',
                                 'target_vol': 0.14,
                                 'tv_enabled': True,
                                 'vol_window': 60,
                                 'weight_end': 2.0},
                        'long_leg': 'ZZ1000',
                        'short_leg': 'CYB',
                        'strategy_id': 'substrategy_zz1000_cyb_tv14_db5_cybvol_w60_thr1p05_d6_scale0p25',
                        'substrategy_id': 'substrategy_zz1000_cyb_tv14_db5_cybvol_w60_thr1p05_d6_scale0p25',
                        'target_vol': {'enabled': True,
                                       'max_leverage': 1.25,
                                       'min_leverage': 0.1,
                                       'scale_deadband': 0.05,
                                       'target_vol': 0.14,
                                       'vol_window': 60},
                        'volume_filter': {'confirm_days': 6,
                                          'enabled': True,
                                          'feature': 'cyb_vol_low',
                                          'scale': 0.25,
                                          'threshold': 1.05,
                                          'timing': 'T-close volume state shifted to T+1 execution exposure',
                                          'window': 60}},
 'reverse_zz500_cyb': {'amount_overlay': {'confirm_days': 3,
                                          'enabled': True,
                                          'feature': 'zz500_amount_low',
                                          'scale': 0.0,
                                          'source': 'CSIndex official amount',
                                          'threshold': 1.0,
                                          'timing': 'T close amount condition shifted to T+1 execution',
                                          'window': 40},
                       'annualization_days': 242,
                       'asset_curve': 'CSI500 price index / ChiNext price index',
                       'baseline': {'layer7_candidate': 'l7_confirm_strict_small_decay_volhot_w20_thr15_scale0p25',
                                    'layer9_candidate': 'l9amt_confirm_strict_small_decay_zz500_amount_low_w40_thr1_d3_scale0',
                                    'line': 'confirm_strict_small_decay',
                                    'line_role': 'main_strict_full_5y',
                                    'source_candidate': 'l3_bias_confirm_abs65_m3_tv12_rv20_max1_floor0_dbrel5'},
                       'candidate': 'l9amt_confirm_strict_small_decay_zz500_amount_low_w40_thr1_d3_scale0',
                       'combination_rule': 'final exposure = target-vol signal * momentum decay * volhot * amount gate',
                       'common_end': '2026-06-05',
                       'common_start': '2010-06-01',
                       'cost_model': {'execution': 'T close signal/state -> T+1 close-to-close return',
                                      'financing_borrow_or_basis': 'excluded',
                                      'legs': 2,
                                      'one_way_commission': 0.0005,
                                      'short_locate_or_borrow': 'excluded',
                                      'slippage': 'excluded'},
                       'direction': 'long ZZ500 / short CYB',
                       'formal_start': '2010-06-01',
                       'long_leg': 'ZZ500',
                       'momentum_decay': {'confirm_days': 2,
                                          'decay_ratio': 0.55,
                                          'derisk_scale': 0.75,
                                          'enabled': True,
                                          'recovery_ratio': 0.75},
                       'profile': 'main_confirm',
                       'result_status': 'quasi-formal fixed research script; close-to-close index spread with V7.7 '
                                        'amount fallback and commission costs',
                       'short_leg': 'CYB',
                       'signal': {'abs_ma': 65,
                                  'abs_threshold': -0.03,
                                  'anchor': 'bias_10_29_we3',
                                  'bias_ma': 10,
                                  'family': 'bias_momentum',
                                  'mom_day': 29,
                                  'r2_threshold': 0.05,
                                  'score_threshold': 0.0,
                                  'weight_end': 3.0},
                       'strategy_id': 'substrategy_zz500_cyb_confirm_strict_decay_volhot_amtlow',
                       'substrategy_id': 'substrategy_zz500_cyb_confirm_strict_decay_volhot_amtlow',
                       'target_vol': {'deadband_mode': 'rel',
                                      'deadband_value': 0.05,
                                      'enabled': True,
                                      'max_leverage': 1.0,
                                      'min_scale': 0.0,
                                      'target_vol': 0.12,
                                      'target_vol_window': 20},
                       'volhot_overlay': {'enabled': True,
                                          'scale': 0.25,
                                          'threshold': 0.15,
                                          'timing': 'prior-row realized spread volatility shifted to next execution '
                                                    'row',
                                          'window': 20.0}},
 'reverse_zz500_hs300': {'amount_overlay': {'confirm_days': 1,
                                            'enabled': True,
                                            'feature': 'zz500_amount_low',
                                            'scale': 0.25,
                                            'source': 'EastMoney amount',
                                            'threshold': 0.75,
                                            'timing': 'T close amount condition shifted to T+1 execution',
                                            'window': 120},
                         'annualization_days': 242,
                         'asset_curve': 'CSI500 price index / CSI300 price index',
                         'baseline': {'final_candidate': 'l11ridge_main_confirm_pair_volume_high_w50_thr1p25_d5_scale0',
                                      'layer10_candidate': 'l10vol_main_confirm_pair_volume_high_w40_thr1p25_d5_scale0',
                                      'layer7_candidate': 'l7_main_confirm_volhot_w40_thr22_scale0p5',
                                      'layer9_candidate': 'l9amt_main_confirm_zz500_amount_low_w120_thr0p75_d1_scale0p25',
                                      'line': 'main_confirm',
                                      'line_role': 'main_strict_full_5y',
                                      'source_candidate': 'l3_confirm_bias_we2_score2_abs65_m2_tv20_rv60_max1_floor0_dbabs0p2'},
                         'candidate': 'l11ridge_main_confirm_pair_volume_high_w50_thr1p25_d5_scale0',
                         'combination_rule': 'final exposure = target-vol signal * volhot * amount gate * Layer10 '
                                             'volume gate * final-ridge volume gate',
                         'common_end': '2026-06-05',
                         'common_start': '2007-01-15',
                         'cost_model': {'execution': 'T close signal/state -> T+1 close-to-close return',
                                        'financing_borrow_or_basis': 'excluded',
                                        'legs': 2,
                                        'one_way_commission': 0.0005,
                                        'short_locate_or_borrow': 'excluded',
                                        'slippage': 'excluded'},
                         'direction': 'long ZZ500 / short HS300',
                         'final_ridge_overlay': {'confirm_days': 5,
                                                 'enabled': True,
                                                 'feature': 'pair_volume_high',
                                                 'scale': 0.0,
                                                 'threshold': 1.25,
                                                 'timing': 'T close final-ridge volume condition shifted to T+1 '
                                                           'execution',
                                                 'window': 50},
                         'formal_start': '2007-01-15',
                         'layer10_volume_overlay': {'confirm_days': 5,
                                                    'enabled': True,
                                                    'feature': 'pair_volume_high',
                                                    'scale': 0.0,
                                                    'threshold': 1.25,
                                                    'window': 40},
                         'long_leg': 'ZZ500',
                         'profile': 'main_confirm',
                         'result_status': 'quasi-formal fixed research script; close-to-close index spread with '
                                          'EastMoney amount/volume overlays and commission costs',
                         'short_leg': 'HS300',
                         'signal': {'abs_ma': 65,
                                    'abs_threshold': -0.02,
                                    'anchor': 'bias_130_20_we2',
                                    'bias_ma': 130,
                                    'family': 'bias_momentum',
                                    'mom_day': 20,
                                    'r2_threshold': 0.05,
                                    'score_threshold': 2.0,
                                    'weight_end': 2.0},
                         'strategy_id': 'substrategy_zz500_hs300_purple_mainconfirm_amtlow_volridge',
                         'substrategy_id': 'substrategy_zz500_hs300_purple_mainconfirm_amtlow_volridge',
                         'target_vol': {'deadband_mode': 'abs',
                                        'deadband_value': 0.2,
                                        'enabled': True,
                                        'max_leverage': 1.0,
                                        'min_scale': 0.0,
                                        'target_vol': 0.2,
                                        'target_vol_window': 60},
                         'volhot_overlay': {'enabled': True,
                                            'scale': 0.5,
                                            'threshold': 0.22,
                                            'timing': 'prior-row realized spread volatility shifted to next execution '
                                                      'row',
                                            'window': 40.0}}}


def _embedded_artifacts() -> dict[str, bytes]:
    global _EMBEDDED_ARTIFACT_CACHE
    if _EMBEDDED_ARTIFACT_CACHE is not None:
        return _EMBEDDED_ARTIFACT_CACHE
    payload = lzma.decompress(base64.b85decode(_EMBEDDED_ARTIFACT_BLOB.encode('ascii')))
    pos = 0
    total = int.from_bytes(payload[pos:pos + 2], 'big')
    pos += 2
    out: dict[str, bytes] = {}
    for _ in range(total):
        name_len = int.from_bytes(payload[pos:pos + 2], 'big')
        pos += 2
        name = payload[pos:pos + name_len].decode('utf-8')
        pos += name_len
        data_len = int.from_bytes(payload[pos:pos + 4], 'big')
        pos += 4
        out[name] = payload[pos:pos + data_len]
        pos += data_len
    _EMBEDDED_ARTIFACT_CACHE = out
    return out

_BOT_SETTINGS = SettingsResponse(
    allow_attachments=False,
    introduction_message="POE ADK spread bot (live/official signals for forward/reverse pairs)."
)
poe.update_settings(_BOT_SETTINGS)


def pct(value: Optional[Union[float, int]], digits: int = 2) -> str:
    if value is None or not math.isfinite(float(value)):
        return "N/A"
    return f"{float(value) * 100:.{digits}f}%"


def num(value: Optional[Union[float, int]], digits: int = 2) -> str:
    if value is None or not math.isfinite(float(value)):
        return "N/A"
    return f"{float(value):.{digits}f}"


def _embedded_artifact_bytes(filename: str) -> bytes:
    payload = _embedded_artifacts().get(filename)
    if payload is None:
        raise FileNotFoundError(f"Missing artifact and embedded fallback: {filename}")
    return payload


def _artifact_bytes(filename: str) -> bytes:
    path = OUTPUT_DIR / filename
    if path.exists():
        return path.read_bytes()
    return _embedded_artifact_bytes(filename)


def canonicalize_meta(meta: dict) -> dict:
    out = dict(meta)

    line = out.get("line")
    if isinstance(line, dict) and "signal" not in out:
        out["signal"] = {
            "bias_ma": line.get("bias_ma"),
            "mom_day": line.get("mom_day"),
            "weight_end": line.get("weight_end"),
            "score_threshold": line.get("score_threshold"),
            "abs_mom_day": line.get("abs_ma"),
            "abs_threshold": line.get("abs_threshold"),
            "r2_threshold": line.get("r2_threshold"),
        }

    target_vol = out.get("target_vol")
    if isinstance(target_vol, dict):
        target_vol = dict(target_vol)
        if "target_vol_window" not in target_vol and "vol_window" in target_vol:
            target_vol["target_vol_window"] = target_vol.get("vol_window")
        out["target_vol"] = target_vol

    if "volume_filter" in out and "volume_overlay" not in out:
        out["volume_overlay"] = dict(out["volume_filter"]) if isinstance(out["volume_filter"], dict) else out["volume_filter"]

    if "volhot_overlay" in out and "vol_overheat" not in out:
        out["vol_overheat"] = dict(out["volhot_overlay"]) if isinstance(out["volhot_overlay"], dict) else out["volhot_overlay"]

    decay = out.get("momentum_decay")
    if isinstance(decay, dict):
        decay = dict(decay)
        if "basis" not in decay:
            strategy_id = str(out.get("strategy_id") or "")
            timing = str(decay.get("timing") or "").lower()
            if strategy_id == "final_sz50_zz500_score0_abs80_tv16_decay030_scorehot18_zz500amthot_w60_thr1p2_scale0p25":
                decay["basis"] = "score_strength"
            elif "score-strength" in timing or "score strength" in timing:
                decay["basis"] = "score_strength"
            elif "score-peak" in timing or "score peak" in timing:
                decay["basis"] = "score"
        out["momentum_decay"] = decay

    return out


def load_meta(config: StrategyConfig) -> dict:
    try:
        payload = json.loads(_artifact_bytes(config.metrics_file).decode("utf-8"))
        meta = canonicalize_meta(payload.get("meta", payload))
    except FileNotFoundError:
        meta = FALLBACK_STRATEGY_METAS.get(config.key)
        if meta is None:
            raise
        meta = canonicalize_meta(meta)
    if "score_formula" not in meta:
        meta["score_formula"] = "legacy_relative_slope_10000" if config.key in LEGACY_RELATIVE_SCORE_KEYS else "weighted_slope"
    return meta


def load_strategy_curves() -> dict[str, pd.DataFrame]:
    curves: dict[str, pd.DataFrame] = {}
    for config in STRATEGIES:
        df = pd.read_csv(io.BytesIO(_artifact_bytes(config.daily_file)), parse_dates=["date"])
        df = df.set_index("date").sort_index()
        for col in ("return", "gross_return", "cost", "turnover", "gross_exposure", "nav", "score"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        curves[config.key] = df
    return curves


def load_strategy_metas() -> dict[str, dict]:
    return {config.key: load_meta(config) for config in STRATEGIES}


def beijing_now() -> datetime:
    return datetime.now(BJ_TZ)


def _can_use_cn_realtime_snapshot_at(bj: datetime) -> bool:
    if bj.weekday() >= 5:
        return False
    return bj >= bj.replace(hour=9, minute=30, second=0, microsecond=0)


def _is_cn_preclose_at(bj: datetime) -> bool:
    if bj.weekday() >= 5:
        return False
    return bj < bj.replace(hour=15, minute=0, second=0, microsecond=0)


def _get_json(url: str, *, timeout: int, headers: dict[str, str]) -> dict:
    if requests is not None:
        resp = requests.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return resp.json()
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - fixed public market-data URLs
        payload = resp.read().decode("utf-8")
    return json.loads(payload)


def _get_text(url: str, *, timeout: int, headers: dict[str, str], encoding: str = "utf-8") -> str:
    if requests is not None:
        resp = requests.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        resp.encoding = encoding
        return resp.text
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - fixed public market-data URLs
        return resp.read().decode(encoding, errors="replace")


def _fetch_eastmoney_kline(secid: str) -> pd.DataFrame:
    end_date = (beijing_now() + timedelta(days=30)).strftime("%Y%m%d")
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=101&fqt=1&beg=20050101&end={end_date}&lmt={ONLINE_FETCH_LOOKBACK_BARS}"
    )
    data = _get_json(url, timeout=12, headers={"Referer": "https://quote.eastmoney.com/"})
    inner = data.get("data") if isinstance(data, dict) else None
    klines = inner.get("klines") if isinstance(inner, dict) else None
    if not klines:
        raise ValueError(f"EastMoney returned no kline rows for {secid}")
    rows = []
    for line in klines:
        parts = str(line).split(",")
        rows.append(
            {
                "date": parts[0],
                "close": float(parts[2]),
                "volume": float(parts[5]) if len(parts) > 5 and parts[5] not in ("", "-") else math.nan,
                "amount": float(parts[6]) if len(parts) > 6 and parts[6] not in ("", "-") else math.nan,
            }
        )
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame.get("volume"), errors="coerce")
    frame["amount"] = pd.to_numeric(frame.get("amount"), errors="coerce")
    return frame.dropna(subset=["close"]).set_index("date").sort_index()


def _fetch_sina_kline(asset: str) -> pd.DataFrame:
    symbol = CN_SINA_SYMBOLS[asset]
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
        f"/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={ONLINE_FETCH_LOOKBACK_BARS}"
    )
    text = _get_text(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"}, encoding="gbk")
    data = json.loads(text)
    if not isinstance(data, list) or not data:
        raise ValueError(f"Sina returned no kline rows for {symbol}")
    rows = []
    for item in data:
        rows.append(
            {
                "date": item["day"],
                "close": float(item["close"]),
                "volume": float(item.get("volume", math.nan) or math.nan),
                "amount": math.nan,
            }
        )
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame.get("volume"), errors="coerce")
    frame["amount"] = pd.to_numeric(frame.get("amount"), errors="coerce")
    return frame.dropna(subset=["close"]).set_index("date").sort_index()


def _fetch_tencent_kline(asset: str) -> pd.DataFrame:
    symbol = CN_TENCENT_SYMBOLS[asset]
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{ONLINE_FETCH_LOOKBACK_BARS},qfq"
    data = _get_json(
        url,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
    )
    if data.get("code") != 0:
        raise ValueError(f"Tencent returned code={data.get('code')} for {symbol}")
    item = (data.get("data") or {}).get(symbol) or {}
    rows_raw = item.get("qfqday") or item.get("day")
    if not rows_raw:
        raise ValueError(f"Tencent returned no kline rows for {symbol}")
    rows = []
    for row in rows_raw:
        if len(row) < 3:
            continue
        rows.append(
            {
                "date": row[0],
                "close": float(row[2]),
                "volume": float(row[5]) if len(row) > 5 and row[5] not in ("", "-") else math.nan,
                "amount": math.nan,
            }
        )
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame.get("volume"), errors="coerce")
    frame["amount"] = pd.to_numeric(frame.get("amount"), errors="coerce")
    return frame.dropna(subset=["close"]).set_index("date").sort_index()


def _secid_to_sohu_index(secid: str) -> str:
    _market, code = secid.split(".")
    if code.startswith("H"):
        code = code[1:].zfill(6)
    return "zs_" + code


def _fetch_csindex_amount(secid: str, *, beg: str = "20050101", lmt: int = ONLINE_FETCH_LOOKBACK_BARS) -> pd.DataFrame:
    index_code = CN_CSI_AMOUNT_INDEX_CODES.get(secid)
    if not index_code:
        raise ValueError(f"no CSIndex amount mapping for {secid}")
    end_date = (beijing_now() + timedelta(days=30)).strftime("%Y%m%d")
    detail_url = f"https://www.csindex.com.cn/indices/index-detail/{index_code}"
    url = (
        "https://www.csindex.com.cn/csindex-home/perf/index-perf"
        f"?indexCode={index_code}&startDate={beg}&endDate={end_date}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": detail_url,
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    }
    if requests is not None:
        sess = requests.Session()
        try:
            sess.get(detail_url, timeout=8, headers=headers)
        except Exception:
            pass
        resp = sess.get(url, timeout=8, headers=headers)
        if resp.status_code == 403:
            raise RuntimeError("CSIndex 403")
        resp.raise_for_status()
        data = resp.json()
    else:
        data = _get_json(url, timeout=8, headers=headers)
    rows = []
    for item in data.get("data", []) if isinstance(data, dict) else []:
        if not item:
            continue
        trading_value = item.get("tradingValue")
        if trading_value in (None, ""):
            continue
        rows.append(
            {
                "date": item.get("tradeDate"),
                "close": float(item.get("close")),
                "volume": float(item.get("tradingVol", 0) or 0),
                "amount": float(trading_value),
            }
        )
    if not rows:
        raise ValueError(f"CSIndex returned no tradingValue rows for {index_code}")
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame.get("volume"), errors="coerce")
    frame["amount"] = pd.to_numeric(frame.get("amount"), errors="coerce")
    return frame.dropna(subset=["close"]).set_index("date").sort_index().tail(int(lmt))


def _fetch_sohu_amount(secid: str, *, beg: str = "20050101", lmt: int = 10000) -> pd.DataFrame:
    symbol = _secid_to_sohu_index(secid)
    end_date = (beijing_now() + timedelta(days=30)).strftime("%Y%m%d")
    url = (
        "https://q.stock.sohu.com/hisHq"
        f"?code={symbol}&start={beg}&end={end_date}&stat=1&order=D&period=d&rt=json"
    )
    data = _get_json(url, timeout=15, headers={"Referer": "https://q.stock.sohu.com/", "User-Agent": "Mozilla/5.0"})
    if not data or not isinstance(data, list):
        raise ValueError(f"Sohu returned no rows for {symbol}")
    first = data[0]
    if not isinstance(first, dict) or first.get("status") != 0 or not first.get("hq"):
        raise ValueError(f"Sohu returned unavailable data for {symbol}")
    rows = []
    for item in first["hq"]:
        if len(item) < 9:
            continue
        rows.append(
            {
                "date": item[0],
                "close": float(item[2]),
                "volume": float(item[7]),
                "amount": float(item[8]),
            }
        )
    if not rows:
        raise ValueError(f"Sohu returned no usable rows for {symbol}")
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame.get("volume"), errors="coerce")
    frame["amount"] = pd.to_numeric(frame.get("amount"), errors="coerce")
    return frame.dropna(subset=["close"]).set_index("date").sort_index().tail(int(lmt))


def _fetch_sina_volume_proxy(asset: str) -> pd.DataFrame:
    frame = _fetch_sina_kline(asset).copy()
    frame["amount"] = pd.to_numeric(frame.get("volume"), errors="coerce")
    return frame


def _fetch_tencent_volume_proxy(asset: str) -> pd.DataFrame:
    frame = _fetch_tencent_kline(asset).copy()
    frame["amount"] = pd.to_numeric(frame.get("volume"), errors="coerce")
    return frame


def _fetch_amount_history_with_fallback(asset: str, secid: str) -> tuple[pd.DataFrame, str, list[str]]:
    attempts: list[str] = []
    sources = (
        ("EastMoney amount", lambda: _fetch_eastmoney_kline(secid)),
        ("CSIndex official amount", lambda: _fetch_csindex_amount(secid)),
        ("Sohu amount", lambda: _fetch_sohu_amount(secid)),
        ("Sina volume proxy", lambda: _fetch_sina_volume_proxy(asset)),
        ("Tencent volume proxy", lambda: _fetch_tencent_volume_proxy(asset)),
    )
    for source_name, fetcher in sources:
        try:
            frame = fetcher()
            amount = pd.to_numeric(frame.get("amount"), errors="coerce")
            if len(frame) > 50 and int(amount.dropna().shape[0]) > 50:
                out = frame.copy()
                out["amount"] = amount
                return out, source_name, attempts
            attempts.append(f"{source_name}: too few amount rows ({int(amount.dropna().shape[0])})")
        except Exception as exc:
            attempts.append(f"{source_name}: {exc}")
    raise RuntimeError(" | ".join(attempts))


def _fetch_eastmoney_realtime_snapshot(secid: str) -> Optional[dict[str, float]]:
    url = (
        "https://push2.eastmoney.com/api/qt/stock/get"
        f"?secid={secid}&fields=f43,f46,f47,f48&ut=fa5fd1943c7b386f172d6893dbfba10b"
    )
    try:
        data = _get_json(url, timeout=8, headers={"Referer": "https://quote.eastmoney.com/"}).get("data")
        if not data:
            return None
        latest = data.get("f43")
        open_price = data.get("f46")
        if latest in (None, "-") or open_price in (None, "-") or float(open_price) <= 0:
            return None
        out = {"close": float(latest) / 100.0}
        if data.get("f47") not in (None, "-"):
            out["volume"] = float(data.get("f47"))
        if data.get("f48") not in (None, "-"):
            out["amount"] = float(data.get("f48"))
        return out
    except Exception:
        return None


def _fetch_sina_realtime_snapshot(asset: str) -> Optional[dict[str, float]]:
    symbol = CN_SINA_SYMBOLS[asset]
    url = f"https://hq.sinajs.cn/list={symbol}"
    try:
        text = _get_text(
            url,
            timeout=8,
            headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
            encoding="gbk",
        )
        if '="' not in text:
            return None
        payload = text.split('="', 1)[1].split('";', 1)[0]
        parts = payload.split(",")
        if len(parts) < 4:
            return None
        price = float(parts[3])
        if price <= 0:
            return None
        out = {"close": price}
        if len(parts) > 8 and parts[8] not in ("", "-"):
            out["volume"] = float(parts[8])
        if len(parts) > 9 and parts[9] not in ("", "-"):
            out["amount"] = float(parts[9])
        return out
    except Exception:
        return None


def _fetch_tencent_realtime_snapshot(asset: str) -> Optional[dict[str, float]]:
    symbol = CN_TENCENT_SYMBOLS[asset]
    url = f"https://qt.gtimg.cn/q={symbol}"
    try:
        text = _get_text(
            url,
            timeout=8,
            headers={"Referer": "https://gu.qq.com/", "User-Agent": "Mozilla/5.0"},
            encoding="gbk",
        )
        if '="' not in text:
            return None
        payload = text.split('="', 1)[1].split('";', 1)[0]
        parts = payload.split("~")
        if len(parts) < 36:
            return None
        price = float(parts[3])
        if price <= 0:
            return None
        out = {"close": price}
        if len(parts) > 36 and parts[36] not in ("", "-"):
            out["volume"] = float(parts[36])
        if len(parts) > 35 and "/" in parts[35]:
            amount_part = parts[35].split("/")[-1]
            if amount_part not in ("", "-"):
                out["amount"] = float(amount_part)
        elif len(parts) > 57 and parts[57] not in ("", "-"):
            out["amount"] = float(parts[57]) * 10000.0
        return out
    except Exception:
        return None


def _fetch_price_history_with_fallback(asset: str, secid: str) -> tuple[pd.DataFrame, str, list[str]]:
    attempts: list[str] = []
    try:
        frame = _fetch_sina_kline(asset)
        if len(frame) > 50:
            return frame, f"Sina {CN_SINA_SYMBOLS[asset]}", attempts
        attempts.append(f"Sina {CN_SINA_SYMBOLS[asset]}: too few rows ({len(frame)})")
    except Exception as exc:
        attempts.append(f"Sina {CN_SINA_SYMBOLS[asset]}: {exc}")

    try:
        frame = _fetch_eastmoney_kline(secid)
        if len(frame) > 50:
            return frame, f"EastMoney {secid}", attempts
        attempts.append(f"EastMoney {secid}: too few rows ({len(frame)})")
    except Exception as exc:
        attempts.append(f"EastMoney {secid}: {exc}")

    try:
        frame = _fetch_tencent_kline(asset)
        if len(frame) > 50:
            return frame, f"Tencent {CN_TENCENT_SYMBOLS[asset]}", attempts
        attempts.append(f"Tencent {CN_TENCENT_SYMBOLS[asset]}: too few rows ({len(frame)})")
    except Exception as exc:
        attempts.append(f"Tencent {CN_TENCENT_SYMBOLS[asset]}: {exc}")

    raise RuntimeError(" | ".join(attempts))


def _fetch_realtime_snapshot_with_fallback(
    asset: str,
    secid: str,
    preferred_source: Optional[str] = None,
) -> tuple[Optional[dict[str, float]], Optional[str]]:
    order = ["eastmoney", "sina", "tencent"]
    if preferred_source and "Sina" in preferred_source:
        order = ["sina", "eastmoney", "tencent"]
    elif preferred_source and "Tencent" in preferred_source:
        order = ["tencent", "sina", "eastmoney"]
    for source in order:
        if source == "eastmoney":
            snapshot = _fetch_eastmoney_realtime_snapshot(secid)
            if snapshot is not None:
                return snapshot, f"EastMoney realtime {secid}"
        elif source == "sina":
            snapshot = _fetch_sina_realtime_snapshot(asset)
            if snapshot is not None:
                return snapshot, f"Sina realtime {CN_SINA_SYMBOLS[asset]}"
        elif source == "tencent":
            snapshot = _fetch_tencent_realtime_snapshot(asset)
            if snapshot is not None:
                return snapshot, f"Tencent realtime {CN_TENCENT_SYMBOLS[asset]}"
    return None, None


def _fetch_online_price_panel(include_realtime: bool) -> tuple[pd.DataFrame, dict[str, object]]:
    if ONLINE_DISABLED:
        raise RuntimeError("online fetch disabled by POE_ADK_DISABLE_ONLINE")

    series: dict[str, pd.Series] = {}
    amount_series: dict[str, pd.Series] = {}
    volume_series: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    amount_sources: dict[str, str] = {}
    errors: dict[str, str] = {}
    fallbacks: dict[str, str] = {}
    amount_fallbacks: dict[str, str] = {}
    amount_errors: dict[str, str] = {}
    live_assets: list[str] = []
    bj = beijing_now()
    today = pd.Timestamp(bj.date())

    for asset, secid in CN_PRICE_SECIDS.items():
        try:
            frame, source_name, attempts = _fetch_price_history_with_fallback(asset, secid)
            if attempts:
                fallbacks[asset] = " -> ".join(attempts)
            frame["is_live_bar"] = False
            latest_date = pd.Timestamp(frame.index[-1]).normalize() if not frame.empty else pd.Timestamp.min
            if not include_realtime and latest_date == today and _is_cn_preclose_at(bj):
                frame = frame.iloc[:-1].copy()
                latest_date = pd.Timestamp(frame.index[-1]).normalize() if not frame.empty else pd.Timestamp.min
            if include_realtime and latest_date == today and _is_cn_preclose_at(bj):
                frame.loc[frame.index == frame.index[-1], "is_live_bar"] = True
                live_assets.append(asset)
            if include_realtime and _can_use_cn_realtime_snapshot_at(bj):
                realtime_snapshot, realtime_source = _fetch_realtime_snapshot_with_fallback(asset, secid, source_name)
                if realtime_snapshot is not None:
                    last_close = float(frame["close"].iloc[-1]) if not frame.empty else math.nan
                    realtime_close = float(realtime_snapshot["close"])
                    if latest_date == today and _is_cn_preclose_at(bj):
                        last_idx = frame.index[-1]
                        frame.loc[last_idx, "close"] = realtime_close
                        if "volume" in realtime_snapshot:
                            frame.loc[last_idx, "volume"] = realtime_snapshot["volume"]
                        if "amount" in realtime_snapshot:
                            frame.loc[last_idx, "amount"] = realtime_snapshot["amount"]
                        if realtime_source:
                            source_name = f"{source_name}+{realtime_source}"
                    elif latest_date < today and (not math.isfinite(last_close) or abs(realtime_close / last_close - 1.0) > 1e-7):
                        live_payload = {
                            "close": realtime_close,
                            "is_live_bar": True,
                            "volume": realtime_snapshot.get("volume", math.nan),
                            "amount": realtime_snapshot.get("amount", math.nan),
                        }
                        live_row = pd.DataFrame(
                            {key: [value] for key, value in live_payload.items()},
                            index=pd.DatetimeIndex([today], name=frame.index.name),
                        )
                        frame = pd.concat([frame, live_row])
                        live_assets.append(asset)
                        if realtime_source:
                            source_name = f"{source_name}+{realtime_source}"
            frame = frame[~frame.index.duplicated(keep="last")].sort_index()
            current_amount = pd.to_numeric(frame.get("amount", pd.Series(index=frame.index, dtype=float)), errors="coerce")
            if int(current_amount.dropna().shape[0]) <= 50:
                try:
                    amount_frame, amount_source, amount_attempts = _fetch_amount_history_with_fallback(asset, secid)
                    amount_value = pd.to_numeric(amount_frame.get("amount"), errors="coerce")
                    merged_index = frame.index.union(amount_value.index)
                    frame = frame.reindex(merged_index)
                    frame["amount"] = current_amount.combine_first(amount_value).reindex(merged_index)
                    if "volume" in amount_frame.columns:
                        current_volume = pd.to_numeric(frame.get("volume", pd.Series(index=frame.index, dtype=float)), errors="coerce")
                        fallback_volume = pd.to_numeric(amount_frame.get("volume"), errors="coerce")
                        frame["volume"] = current_volume.combine_first(fallback_volume).reindex(merged_index)
                    amount_sources[asset] = f"{amount_source} end={amount_value.dropna().index[-1].strftime('%Y-%m-%d')}"
                    if amount_attempts:
                        amount_fallbacks[asset] = " -> ".join(amount_attempts)
                except Exception as exc:
                    current_volume = pd.to_numeric(frame.get("volume", pd.Series(index=frame.index, dtype=float)), errors="coerce")
                    if int(current_volume.dropna().shape[0]) > 50:
                        frame["amount"] = current_volume
                        amount_sources[asset] = f"{source_name} volume proxy end={current_volume.dropna().index[-1].strftime('%Y-%m-%d')}"
                        amount_errors[asset] = f"real amount fallback failed; using price-source volume proxy: {exc}"
                    else:
                        amount_errors[asset] = str(exc)
            else:
                amount_sources[asset] = f"{source_name} amount end={current_amount.dropna().index[-1].strftime('%Y-%m-%d')}"
            frame = frame[~frame.index.duplicated(keep="last")].sort_index()
            series[asset] = frame["close"].rename(asset)
            if "amount" in frame.columns:
                amount_series[f"{asset}_amount"] = pd.to_numeric(frame["amount"], errors="coerce").rename(f"{asset}_amount")
            if "volume" in frame.columns:
                volume_series[f"{asset}_volume"] = pd.to_numeric(frame["volume"], errors="coerce").rename(f"{asset}_volume")
            sources[asset] = f"{source_name} end={frame.index[-1].strftime('%Y-%m-%d')}"
        except Exception as exc:
            errors[asset] = str(exc)

    if not series:
        detail = "; ".join(f"{asset}: {err}" for asset, err in errors.items())
        raise RuntimeError(f"online A-share fetch failed: {detail}")

    panel = pd.concat([*series.values(), *amount_series.values(), *volume_series.values()], axis=1).sort_index()
    panel.attrs["sources"] = sources
    panel.attrs["amount_sources"] = amount_sources
    panel.attrs["errors"] = errors
    panel.attrs["fallbacks"] = fallbacks
    panel.attrs["amount_fallbacks"] = amount_fallbacks
    panel.attrs["amount_errors"] = amount_errors
    panel.attrs["live_assets"] = live_assets
    panel.attrs["fetched_at"] = bj.strftime("%Y-%m-%d %H:%M:%S")
    panel.attrs["mode"] = "intraday" if live_assets else "daily"
    return panel, dict(panel.attrs)


def _bias_momentum_for_live(close: pd.Series, bias_ma: int, mom_day: int, weight_end: float) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce").sort_index()
    ma = close.rolling(int(bias_ma)).mean()
    bias = close / ma.replace(0, math.nan)
    weights = [1.0 + (float(weight_end) - 1.0) * i / max(int(mom_day) - 1, 1) for i in range(int(mom_day))]
    weight_sum = sum(weights)
    x = list(range(int(mom_day)))
    x_bar = sum(w * v for w, v in zip(weights, x)) / weight_sum
    denom = sum(w * (v - x_bar) ** 2 for w, v in zip(weights, x))
    values: list[float] = []
    for end in range(len(bias)):
        window = bias.iloc[end - int(mom_day) + 1 : end + 1]
        if len(window) < int(mom_day) or window.isna().any() or denom <= 0:
            values.append(math.nan)
            continue
        y = [float(v) for v in window]
        y_bar = sum(w * v for w, v in zip(weights, y)) / weight_sum
        slope = sum(w * (xv - x_bar) * (yv - y_bar) for w, xv, yv in zip(weights, x, y)) / denom
        values.append(slope * int(mom_day) * 100.0)
    return pd.Series(values, index=close.index)


def _legacy_bias_momentum_for_live(close: pd.Series, bias_ma: int, mom_day: int, weight_end: float) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce").sort_index()
    ma = close.rolling(int(bias_ma)).mean()
    bias = close / ma.replace(0, math.nan)
    weights = [1.0 + (float(weight_end) - 1.0) * i / max(int(mom_day) - 1, 1) for i in range(int(mom_day))]
    weight_sum = sum(weights)
    x = list(range(int(mom_day)))
    x_bar = sum(w * v for w, v in zip(weights, x)) / weight_sum
    denom = sum(w * (v - x_bar) ** 2 for w, v in zip(weights, x))
    values: list[float] = []
    for end in range(len(bias)):
        if end + 1 < int(bias_ma) + int(mom_day):
            values.append(math.nan)
            continue
        window = bias.iloc[end - int(mom_day) + 1 : end + 1]
        if window.isna().any() or float(window.iloc[0]) <= 1e-10 or denom <= 0:
            values.append(math.nan)
            continue
        y = [float(v) for v in window]
        y_bar = sum(w * v for w, v in zip(weights, y)) / weight_sum
        slope = sum(w * (xv - x_bar) * (yv - y_bar) for w, xv, yv in zip(weights, x, y)) / denom
        values.append(slope / float(window.iloc[0]) * 10000.0)
    return pd.Series(values, index=close.index)


def _score_formula(meta: dict) -> str:
    signal = meta.get("signal", {}) if isinstance(meta.get("signal", {}), dict) else {}
    value = signal.get("score_formula") or meta.get("score_formula")
    if value in (None, ""):
        return "weighted_slope"
    return str(value)


def _bias_momentum_score_for_live(close: pd.Series, bias_ma: int, mom_day: int, weight_end: float, meta: dict) -> pd.Series:
    if _score_formula(meta) == "legacy_relative_slope_10000":
        return _legacy_bias_momentum_for_live(close, bias_ma=bias_ma, mom_day=mom_day, weight_end=weight_end)
    return _bias_momentum_for_live(close, bias_ma=bias_ma, mom_day=mom_day, weight_end=weight_end)


def _bias_momentum_r2_for_live(close: pd.Series, bias_ma: int, mom_day: int, weight_end: float) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce").sort_index()
    ma = close.rolling(int(bias_ma)).mean()
    bias = close / ma.replace(0, math.nan)
    weights = [1.0 + (float(weight_end) - 1.0) * i / max(int(mom_day) - 1, 1) for i in range(int(mom_day))]
    weight_sum = sum(weights)
    x = list(range(int(mom_day)))
    x_bar = sum(w * v for w, v in zip(weights, x)) / weight_sum
    var_x = sum(w * (v - x_bar) ** 2 for w, v in zip(weights, x)) / weight_sum
    values: list[float] = []
    for end in range(len(bias)):
        window = bias.iloc[end - int(mom_day) + 1 : end + 1]
        if len(window) < int(mom_day) or window.isna().any() or var_x <= 0:
            values.append(math.nan)
            continue
        y = [float(v) for v in window]
        y_bar = sum(w * v for w, v in zip(weights, y)) / weight_sum
        cov = sum(w * (xv - x_bar) * (yv - y_bar) for w, xv, yv in zip(weights, x, y)) / weight_sum
        var_y = sum(w * (yv - y_bar) ** 2 for w, yv in zip(weights, y)) / weight_sum
        if var_y <= 0:
            values.append(math.nan)
            continue
        values.append(min(max((cov * cov) / (var_x * var_y), 0.0), 1.0))
    return pd.Series(values, index=close.index)


def _consecutive_true_live(mask: pd.Series) -> pd.Series:
    out: list[int] = []
    count = 0
    for item in mask.fillna(False).astype(bool):
        count = count + 1 if item else 0
        out.append(count)
    return pd.Series(out, index=mask.index, dtype=float)


def _combine_seed_and_online_series(seed: Optional[pd.Series], online: pd.Series) -> pd.Series:
    parts = []
    if seed is not None:
        parts.append(pd.to_numeric(seed, errors="coerce"))
    parts.append(pd.to_numeric(online, errors="coerce"))
    combined = pd.concat(parts).dropna().sort_index()
    return combined[~combined.index.duplicated(keep="last")]


def _live_metric_overlay_state(
    amount: dict,
    panel: pd.DataFrame,
    long_asset: str,
    short_asset: str,
    seed_curve: Optional[pd.DataFrame],
    metric: str,
) -> dict[str, object]:
    family = str(amount.get("family") or "")
    window = int(amount.get("window") or 1)
    threshold = float(_threshold_from_section(amount))
    confirm_days = int(amount.get("confirm_days") or 1)
    metric_name = "amount" if metric == "amount" else "volume"
    long_col = f"{long_asset}_{metric}"
    short_col = f"{short_asset}_{metric}"
    raw_online_count = 0

    if family in {"high_pair", "low_pair"}:
        seed_raw = None
        if metric == "amount":
            ratio_col = f"amount_ratio_{long_asset}_{short_asset}"
            if seed_curve is not None and ratio_col in seed_curve.columns:
                seed_raw = pd.to_numeric(seed_curve[ratio_col], errors="coerce")
            elif seed_curve is not None and long_col in seed_curve.columns and short_col in seed_curve.columns:
                seed_raw = pd.to_numeric(seed_curve[long_col], errors="coerce") / pd.to_numeric(seed_curve[short_col], errors="coerce").replace(0, math.nan)
        if long_col not in panel.columns or short_col not in panel.columns:
            if seed_raw is None:
                return {"enabled": True, "available": False, "reason": f"missing online pair {metric} columns"}
            raw = seed_raw
        else:
            long_series = pd.to_numeric(panel[long_col], errors="coerce")
            short_series = pd.to_numeric(panel[short_col], errors="coerce")
            online_raw = long_series / short_series.replace(0, math.nan)
            raw_online_count = min(int(long_series.dropna().shape[0]), int(short_series.dropna().shape[0]))
            raw = _combine_seed_and_online_series(seed_raw, online_raw) if seed_raw is not None else online_raw.dropna().sort_index()
        label = f"{CN_ASSET_NAMES[long_asset]}{metric_name}/{CN_ASSET_NAMES[short_asset]}{metric_name}"
    else:
        amount_asset = long_asset
        series_name = str(amount.get("series") or "").lower()
        for asset in CN_ASSET_NAMES:
            if f"{asset}_amount" in series_name or f"{asset}_volume" in series_name or asset in series_name:
                amount_asset = asset
                break
        metric_col = f"{amount_asset}_{metric}"
        raw_online_count = int(pd.to_numeric(panel[metric_col], errors="coerce").dropna().shape[0]) if metric_col in panel.columns else 0
        seed_raw = pd.to_numeric(seed_curve[metric_col], errors="coerce") if metric == "amount" and seed_curve is not None and metric_col in seed_curve.columns else None
        if metric_col not in panel.columns:
            if seed_raw is None:
                return {"enabled": True, "available": False, "reason": f"missing online {metric} column {metric_col}"}
            raw = seed_raw
        else:
            online_raw = pd.to_numeric(panel[metric_col], errors="coerce")
            raw = _combine_seed_and_online_series(seed_raw, online_raw) if seed_raw is not None else online_raw.dropna().sort_index()
        label = f"{CN_ASSET_NAMES.get(amount_asset, amount_asset)}{metric_name}"

    raw = pd.to_numeric(raw, errors="coerce").dropna().sort_index()
    if len(raw) < max(window, 2):
        return {"enabled": True, "available": False, "reason": f"too few online {metric} rows ({len(raw)})"}
    ma = raw.rolling(window).mean()
    ratio = raw / ma.replace(0, math.nan)
    if family.startswith("high_"):
        raw_gate = ratio >= threshold
        gate = raw_gate
    else:
        raw_gate = ratio <= threshold
        gate = _consecutive_true_live(raw_gate) >= confirm_days
    latest_ratio = ratio.dropna()
    if latest_ratio.empty:
        return {"enabled": True, "available": False, "reason": f"latest online {metric} ratio is empty"}
    latest_ratio_value = float(latest_ratio.iloc[-1])
    if raw_online_count < window and (latest_ratio_value > 10.0 or latest_ratio_value < 0.1):
        return {
            "enabled": True,
            "available": False,
            "reason": f"online {metric} unit/source is not comparable to history (ratio={latest_ratio_value:.3g})",
        }
    latest_date = latest_ratio.index[-1]
    latest_gate = bool(gate.reindex(latest_ratio.index).iloc[-1])
    return {
        "enabled": True,
        "available": True,
        "label": label,
        "basis": metric_name,
        "basis_key": metric,
        "family": family,
        "window": window,
        "threshold": threshold,
        "confirm_days": confirm_days,
        "value": latest_ratio_value,
        "gate": latest_gate,
        "scale": _scale_from_section(amount),
        "date": pd.Timestamp(latest_date).strftime("%Y-%m-%d"),
    }


def _metric_gate_series(
    section: dict,
    panel: pd.DataFrame,
    long_asset: str,
    short_asset: str,
    metric: str,
) -> tuple[pd.Series, pd.Series]:
    family = str(section.get("family") or "")
    window = int(section.get("window") or 1)
    threshold = float(_threshold_from_section(section))
    confirm_days = int(section.get("confirm_days") or 1)
    long_col = f"{long_asset}_{metric}"
    short_col = f"{short_asset}_{metric}"

    if family in {"high_pair", "low_pair"}:
        if long_col not in panel.columns or short_col not in panel.columns:
            return pd.Series(dtype=float), pd.Series(dtype=float)
        raw = pd.to_numeric(panel[long_col], errors="coerce") / pd.to_numeric(panel[short_col], errors="coerce").replace(0, math.nan)
    else:
        metric_asset = long_asset
        series_name = str(section.get("series") or section.get("feature") or "").lower()
        for asset in CN_ASSET_NAMES:
            if f"{asset}_amount" in series_name or f"{asset}_volume" in series_name or asset in series_name:
                metric_asset = asset
                break
        metric_col = f"{metric_asset}_{metric}"
        if metric_col not in panel.columns:
            return pd.Series(dtype=float), pd.Series(dtype=float)
        raw = pd.to_numeric(panel[metric_col], errors="coerce")

    raw = pd.to_numeric(raw, errors="coerce").dropna().sort_index()
    if len(raw) < max(window, 2):
        return pd.Series(dtype=float), pd.Series(dtype=float)
    ratio = raw / raw.rolling(window).mean().replace(0, math.nan)
    if family.startswith("high_"):
        gate = ratio >= threshold
    else:
        gate = _consecutive_true_live(ratio <= threshold) >= confirm_days
    return ratio, gate.astype(float)


def _live_amount_state(
    meta: dict,
    panel: pd.DataFrame,
    long_asset: str,
    short_asset: str,
    seed_curve: Optional[pd.DataFrame] = None,
) -> dict[str, object]:
    amount = _amount_overlay_section(meta)
    if not amount:
        return {"enabled": False, "available": False}
    failures: list[str] = []
    series_name = str(amount.get("series") or "")
    if "volume" in series_name:
        metrics = ("volume",)
    elif "amount" in series_name:
        metrics = ("amount",)
    else:
        metrics = ("amount", "volume")
    for metric in metrics:
        state = _live_metric_overlay_state(amount, panel, long_asset, short_asset, seed_curve, metric)
        if state.get("available"):
            return state
        reason = state.get("reason")
        if reason:
            failures.append(f"{metric}: {reason}")
    return {"enabled": True, "available": False, "reason": " | ".join(failures) if failures else "online amount/volume unavailable"}


def _live_probe_for_strategy(
    config: StrategyConfig,
    meta: dict,
    panel: pd.DataFrame,
    seed_curve: Optional[pd.DataFrame] = None,
) -> Optional[dict[str, object]]:
    legs = STRATEGY_LEGS.get(config.key)
    if not legs or any(asset not in panel.columns for asset in legs):
        return None
    long_asset, short_asset = legs
    pair = panel[[long_asset, short_asset]].dropna().copy()
    start = pd.Timestamp(meta.get("common_start", pair.index.min()))
    pair = pair.loc[pair.index >= start]
    if len(pair) < 100:
        return None
    ratio = pair[long_asset] / pair[short_asset]
    close = ratio / float(ratio.iloc[0])
    signal = meta.get("signal", {}) if isinstance(meta.get("signal", {}), dict) else {}
    bias_ma = int(signal.get("bias_ma") or 60)
    mom_day = int(signal.get("mom_day") or 20)
    weight_end = float(signal.get("weight_end") or 1.0)
    score_threshold = float(signal.get("score_threshold") or 0.0)
    score = _bias_momentum_score_for_live(close, bias_ma=bias_ma, mom_day=mom_day, weight_end=weight_end, meta=meta)
    r2 = _bias_momentum_r2_for_live(close, bias_ma=bias_ma, mom_day=mom_day, weight_end=weight_end)
    latest_date = score.dropna().index[-1] if not score.dropna().empty else close.index[-1]
    latest_score = float(score.reindex(close.index).iloc[-1]) if pd.notna(score.reindex(close.index).iloc[-1]) else math.nan
    latest_r2 = float(r2.reindex(close.index).iloc[-1]) if pd.notna(r2.reindex(close.index).iloc[-1]) else math.nan
    abs_day = _signal_abs_day(signal)
    abs_threshold = signal.get("abs_threshold")
    abs_mom = math.nan
    abs_pass = True
    if abs_day not in (None, "") and abs_threshold not in (None, ""):
        abs_series = close / close.shift(int(abs_day)) - 1.0
        if pd.notna(abs_series.iloc[-1]):
            abs_mom = float(abs_series.iloc[-1])
            abs_pass = abs_mom > float(abs_threshold)
        else:
            abs_pass = False
    score_pass = math.isfinite(latest_score) and latest_score > score_threshold
    r2_threshold = _signal_r2_threshold(signal)
    r2_pass = True if r2_threshold is None else math.isfinite(latest_r2) and latest_r2 >= r2_threshold
    target = 1.0 if score_pass and r2_pass and abs_pass else 0.0
    vol_section = _vol_overlay_section(meta)
    vol_window = vol_section.get("window")
    vol_value = math.nan
    vol_scale = math.nan
    if vol_window not in (None, ""):
        vol_series = close.pct_change().rolling(int(vol_window)).std(ddof=0) * math.sqrt(ANNUAL_DAYS)
        if pd.notna(vol_series.iloc[-1]):
            vol_value = float(vol_series.iloc[-1])
            if vol_section.get("kind") == "downonly_tv":
                vol_scale = _downonly_tv_scale_from_realized_vol(vol_value, vol_section)
    amount_state = _live_amount_state(meta, panel, long_asset, short_asset, seed_curve=seed_curve)
    return {
        "date": pd.Timestamp(close.index[-1]).strftime("%Y-%m-%d"),
        "long_asset": long_asset,
        "short_asset": short_asset,
        "score": latest_score,
        "score_threshold": score_threshold,
        "r2": latest_r2,
        "r2_threshold": r2_threshold if r2_threshold is not None else math.nan,
        "abs_mom": abs_mom,
        "abs_threshold": float(abs_threshold) if abs_threshold not in (None, "") else math.nan,
        "target": target,
        "vol_overheat_value": vol_value,
        "vol_overheat_scale": vol_scale,
        "amount_state": amount_state,
        "mode": panel.attrs.get("mode", "daily"),
    }


def _online_signal_frame_for_strategy(config: StrategyConfig, meta: dict, panel: pd.DataFrame) -> pd.DataFrame:
    legs = STRATEGY_LEGS.get(config.key)
    if not legs or any(asset not in panel.columns for asset in legs):
        return pd.DataFrame()
    long_asset, short_asset = legs
    price = panel[[long_asset, short_asset]].dropna().copy()
    if price.empty:
        return pd.DataFrame()
    start = pd.Timestamp(meta.get("common_start", price.index.min()))
    price = price.loc[price.index >= start]
    if price.empty:
        return pd.DataFrame()
    ratio = price[long_asset] / price[short_asset]
    close = ratio / float(ratio.iloc[0])
    signal = meta.get("signal", {}) if isinstance(meta.get("signal", {}), dict) else {}
    score = _bias_momentum_score_for_live(
        close,
        bias_ma=int(signal.get("bias_ma") or 60),
        mom_day=int(signal.get("mom_day") or 20),
        weight_end=float(signal.get("weight_end") or 1.0),
        meta=meta,
    )
    r2 = _bias_momentum_r2_for_live(
        close,
        bias_ma=int(signal.get("bias_ma") or 60),
        mom_day=int(signal.get("mom_day") or 20),
        weight_end=float(signal.get("weight_end") or 1.0),
    )
    out = pd.DataFrame(index=price.index)
    out[long_asset] = price[long_asset]
    out[short_asset] = price[short_asset]
    out["spread_close"] = close
    out["score"] = score
    out["r2"] = r2
    score_threshold = float(signal.get("score_threshold") or 0.0)
    out["score_strength"] = (score - score_threshold).clip(lower=0.0)
    out["raw_signal"] = _online_target_series(close, score, meta, r2=r2)
    for asset in legs:
        amount_col = f"{asset}_amount"
        if amount_col in panel.columns:
            out[amount_col] = pd.to_numeric(panel[amount_col], errors="coerce").reindex(out.index)
        volume_col = f"{asset}_volume"
        if volume_col in panel.columns:
            out[volume_col] = pd.to_numeric(panel[volume_col], errors="coerce").reindex(out.index)
    amount_a = f"{long_asset}_amount"
    amount_b = f"{short_asset}_amount"
    ratio_col = f"amount_ratio_{long_asset}_{short_asset}"
    if amount_a in out.columns and amount_b in out.columns:
        out[ratio_col] = out[amount_a] / out[amount_b].replace(0, math.nan)
    amount_section = _amount_overlay_section(meta)
    if amount_section:
        series_name = str(amount_section.get("series") or amount_section.get("feature") or "").lower()
        metric = "volume" if "volume" in series_name else "amount"
        ratio_series, gate_series = _metric_gate_series(amount_section, panel, long_asset, short_asset, metric)
        if not ratio_series.empty:
            out["amount_gate"] = gate_series.reindex(out.index)
            out["amount_ma_ratio"] = ratio_series.reindex(out.index)
    for section in _volume_overlay_sections(meta):
        ratio_series, gate_series = _metric_gate_series(section, panel, long_asset, short_asset, "volume")
        if ratio_series.empty:
            continue
        key = str(section.get("_meta_key") or "volume_overlay")
        if key == "layer10_volume_overlay":
            out["layer10_volume_gate"] = gate_series.reindex(out.index)
            out["layer10_volume_ma_ratio"] = ratio_series.reindex(out.index)
        elif key == "final_ridge_overlay":
            out["final_ridge_gate"] = gate_series.reindex(out.index)
            out["final_ridge_indicator"] = ratio_series.reindex(out.index)
        else:
            out["volume_gate"] = gate_series.reindex(out.index)
            out["volume_ma_ratio"] = ratio_series.reindex(out.index)
    vol = _vol_overlay_section(meta)
    if vol.get("enabled") and vol.get("window") not in (None, ""):
        vol_series = close.pct_change().rolling(int(vol.get("window"))).std(ddof=0) * math.sqrt(ANNUAL_DAYS)
        for col in ("overheat_indicator", "volhot_indicator", "vol_indicator", "realized_vol", "base_realized_vol"):
            out[col] = vol_series
        if vol.get("kind") == "downonly_tv":
            cap = vol_series.apply(_downonly_tv_scale_from_realized_vol, args=(vol,))
            mult = cap.fillna(1.0)
            gate = (mult < 0.999).astype(float)
            out["overheat_scale"] = mult
            out["volhot_scale"] = mult
            out["vol_scale"] = mult
            for col in ("overheat_gate", "volhot_gate", "vol_gate"):
                out[col] = gate
        else:
            for col in ("overheat_scale", "volhot_scale", "vol_scale"):
                out[col] = float(vol.get("scale", math.nan))
            gate = (vol_series >= float(vol.get("threshold", math.inf))).astype(float)
            for col in ("overheat_gate", "volhot_gate", "vol_gate"):
                out[col] = gate
    return out


def snapshot_score_diffs(
    panel: pd.DataFrame,
    metas: Optional[dict[str, dict]] = None,
    *,
    tolerance: Optional[float] = None,
) -> list[dict[str, object]]:
    metas = metas or load_strategy_metas()
    rows: list[dict[str, object]] = []
    for config in STRATEGIES:
        snapshot = STATE_SNAPSHOT.get(config.key, {})
        values = snapshot.get("values", {}) if isinstance(snapshot.get("values", {}), dict) else {}
        if "score" not in values:
            continue
        meta = metas[config.key] if config.key in metas else load_meta(config)
        as_of_raw = snapshot.get("as_of")
        snapshot_score = _safe_float(values.get("score"))
        base_row: dict[str, object] = {
            "key": config.key,
            "display_name": config.display_name,
            "as_of": str(as_of_raw or ""),
            "score_formula": _score_formula(meta),
            "snapshot_score": snapshot_score,
            "recomputed_score": math.nan,
            "abs_diff": math.nan,
            "status": "missing_as_of",
        }
        if not as_of_raw:
            rows.append(base_row)
            continue
        signal_frame = _online_signal_frame_for_strategy(config, meta, panel)
        if signal_frame.empty or "score" not in signal_frame.columns:
            base_row["status"] = "missing_signal"
            rows.append(base_row)
            continue
        as_of = pd.Timestamp(as_of_raw).normalize()
        index = pd.DatetimeIndex(signal_frame.index)
        matches = index[index.normalize() == as_of]
        if len(matches) == 0:
            base_row["status"] = "as_of_not_in_panel"
            rows.append(base_row)
            continue
        recomputed_score = _safe_float(signal_frame.loc[matches[-1], "score"])
        abs_diff = abs(recomputed_score - snapshot_score) if math.isfinite(recomputed_score) and math.isfinite(snapshot_score) else math.nan
        effective_tolerance = (
            float(tolerance)
            if tolerance is not None
            else max(SNAPSHOT_SCORE_ABS_TOL, SNAPSHOT_SCORE_REL_TOL * abs(snapshot_score if math.isfinite(snapshot_score) else 0.0))
        )
        base_row.update(
            {
                "recomputed_score": recomputed_score,
                "abs_diff": abs_diff,
                "status": "ok" if math.isfinite(abs_diff) and abs_diff <= effective_tolerance else "mismatch",
            }
        )
        rows.append(base_row)
    return rows


def _signal_r2_threshold(signal: dict) -> Optional[float]:
    if not isinstance(signal, dict) or signal.get("r2_filter") is False:
        return None
    value = signal.get("r2_threshold")
    if value in (None, ""):
        return None
    return float(value)


def _online_target_series(close: pd.Series, score: pd.Series, meta: dict, r2: Optional[pd.Series] = None) -> pd.Series:
    signal = meta.get("signal", {}) if isinstance(meta.get("signal", {}), dict) else {}
    threshold = float(signal.get("score_threshold") or 0.0)
    target = score > threshold
    r2_threshold = _signal_r2_threshold(signal)
    if r2_threshold is not None:
        if r2 is None:
            target &= False
        else:
            target &= pd.to_numeric(r2, errors="coerce") >= r2_threshold
    abs_day = _signal_abs_day(signal)
    abs_threshold = signal.get("abs_threshold")
    if abs_day not in (None, "") and abs_threshold not in (None, ""):
        abs_mom = close / close.shift(int(abs_day)) - 1.0
        target &= abs_mom > float(abs_threshold)
    return target.astype(float)


def _previous_online_value(series: pd.Series, idx: pd.Timestamp) -> float:
    prior = pd.to_numeric(series.loc[series.index < idx], errors="coerce").dropna()
    if prior.empty:
        return math.nan
    return float(prior.iloc[-1])


def _online_target_vol_scale(
    row: pd.Series,
    prev_row: pd.Series,
    meta: dict,
    signal_date: pd.Timestamp,
    vol_series: pd.Series,
) -> tuple[float, float, float]:
    target_vol = meta.get("target_vol", {}) if isinstance(meta.get("target_vol", {}), dict) else {}
    if not target_vol.get("enabled"):
        return 1.0, 1.0, 0.0
    max_leverage = float(target_vol.get("max_leverage") or 1.0)
    target = target_vol.get("target_vol")
    if target in (None, ""):
        return 1.0, 1.0, 0.0
    rv = _previous_online_value(vol_series, signal_date + pd.Timedelta(nanoseconds=1))
    if not math.isfinite(rv) or rv <= 1e-12:
        raw = 1.0
    else:
        min_leverage = _safe_float(_first_section_value(target_vol, ("min_leverage", "min_scale", "floor")), 0.0)
        raw = min(max(float(target) / rv, min_leverage), max_leverage)
    prev_scale = _first_numeric(prev_row, ("target_vol_scale", "base_target_vol_scale"))
    if not math.isfinite(prev_scale) or prev_scale <= 1e-12:
        prev_scale = raw
    suppressed = 0.0
    scale = raw
    gate = target_vol.get("gate")
    if gate not in (None, ""):
        gate_value = float(gate)
        if gate_value > 0.0 and raw > (1.0 - gate_value):
            scale = 1.0
            suppressed = 1.0 if abs(raw - scale) > 1e-12 else 0.0
            return raw, scale, suppressed

    if _target_vol_deadband_suppressed(raw, prev_scale, target_vol):
        scale = prev_scale
        suppressed = 1.0
    return raw, scale, suppressed


def _online_gate_and_multiplier(
    idx: pd.Timestamp,
    row: dict,
    prev_row: pd.Series,
    meta: dict,
    signal_frame: pd.DataFrame,
    curve_so_far: pd.DataFrame,
    decay_state_frame: Optional[pd.DataFrame] = None,
) -> float:
    multiplier = 1.0
    state_idx = signal_frame.index[signal_frame.index < idx]
    as_of = pd.Timestamp(state_idx[-1] if len(state_idx) else idx)
    state_row = signal_frame.loc[as_of] if as_of in signal_frame.index else pd.Series(dtype=float)

    nav = meta.get("nav_defense", {}) if isinstance(meta.get("nav_defense", {}), dict) else {}
    if nav.get("enabled"):
        dd = _nav_drawdown_from_state_row(prev_row)
        if not math.isfinite(dd):
            dd, _nav_col = _nav_drawdown_value(curve_so_far)
        gate = math.isfinite(dd) and dd <= -abs(_safe_float(_threshold_from_section(nav), 0.0))
        row["nav_defense_gate"] = 1.0 if gate else 0.0
        row["base_nav_defense_gate"] = row["nav_defense_gate"]
        if gate:
            multiplier *= _scale_from_section(nav)

    vol = _vol_overlay_section(meta)
    if vol.get("enabled"):
        current = math.nan
        for col in ("overheat_indicator", "volhot_indicator", "vol_indicator", "realized_vol", "base_realized_vol"):
            if col in state_row.index and pd.notna(state_row[col]) and math.isfinite(float(state_row[col])):
                current = float(state_row[col])
                break
        if vol.get("kind") == "downonly_tv":
            scale = _first_numeric(state_row, ("overheat_scale", "volhot_scale", "vol_scale"))
            if not math.isfinite(scale):
                scale = _downonly_tv_scale_from_realized_vol(current, vol)
            gate = math.isfinite(scale) and abs(scale - 1.0) > 1e-12
            for col in ("overheat_scale", "volhot_scale", "vol_scale"):
                row[col] = scale
            for col in ("overheat_gate", "volhot_gate", "vol_gate"):
                row[col] = 1.0 if gate else 0.0
            if gate and math.isfinite(scale):
                multiplier *= float(scale)
        else:
            gate = math.isfinite(current) and current >= float(vol.get("threshold", math.inf))
            for col in ("overheat_gate", "volhot_gate", "vol_gate"):
                row[col] = 1.0 if gate else 0.0
            for col in ("overheat_scale", "volhot_scale", "vol_scale"):
                row[col] = _scale_from_section(vol)
            if gate:
                multiplier *= _scale_from_section(vol)

    amount = _amount_overlay_section(meta)
    if amount:
        gate_value = state_row.get("amount_gate", 0.0)
        try:
            gate = math.isfinite(float(gate_value)) and float(gate_value) != 0.0
        except (TypeError, ValueError):
            gate = False
        row["amount_gate"] = 1.0 if gate else 0.0
        if "amount_ma_ratio" in state_row.index:
            row["amount_ma_ratio"] = state_row.get("amount_ma_ratio")
        if gate:
            multiplier *= _scale_from_section(amount)

    for volume in _volume_overlay_sections(meta):
        gate = False
        for col in volume.get("_gate_cols", ()):
            gate_value = state_row.get(col, 0.0)
            try:
                if math.isfinite(float(gate_value)) and float(gate_value) != 0.0:
                    gate = True
                    break
            except (TypeError, ValueError):
                continue
        for col in volume.get("_gate_cols", ()):
            row[col] = 1.0 if gate else 0.0
        for col in volume.get("_value_cols", ()):
            if col in state_row.index:
                row[col] = state_row.get(col)
        if gate:
            multiplier *= _scale_from_section(volume)

    scorehot = meta.get("score_overheat", {}) if isinstance(meta.get("score_overheat", {}), dict) else {}
    if scorehot.get("enabled"):
        score_value = float(state_row.get("score", math.nan))
        gate = math.isfinite(score_value) and score_value >= float(_scorehot_threshold(scorehot) or math.inf)
        row["scorehot_gate"] = 1.0 if gate else 0.0
        row["scorehot_indicator"] = score_value
        row["scorehot_scale"] = _scale_from_section(scorehot)
        if gate:
            multiplier *= _scale_from_section(scorehot)

    decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
    if decay.get("enabled"):
        _apply_online_decay_state(row, signal_frame, pd.Timestamp(as_of), meta, state_frame=decay_state_frame)
        gate = _safe_float(row.get("decay_gate"))
        mult = _safe_float(row.get("decay_mult", row.get("decay_scale")))
        if math.isfinite(gate) and abs(gate) > 1e-12 and math.isfinite(mult):
            multiplier *= float(mult)

    return max(0.0, multiplier)


def _fill_online_execution_row(
    idx: pd.Timestamp,
    row: dict,
    curve_so_far: pd.DataFrame,
    meta: dict,
    signal_frame: pd.DataFrame,
    decay_state_frame: Optional[pd.DataFrame] = None,
    target_series: Optional[pd.Series] = None,
    vol_series: Optional[pd.Series] = None,
) -> dict:
    if idx not in signal_frame.index:
        return row
    spread = pd.to_numeric(signal_frame["spread_close"], errors="coerce")
    if target_series is None:
        r2_series = pd.to_numeric(signal_frame["r2"], errors="coerce") if "r2" in signal_frame.columns else None
        target_series = _online_target_series(spread, pd.to_numeric(signal_frame["score"], errors="coerce"), meta, r2=r2_series)
    target_vol = meta.get("target_vol", {}) if isinstance(meta.get("target_vol", {}), dict) else {}
    tv_window = int(target_vol.get("target_vol_window") or 20)
    if vol_series is None:
        vol_series = spread.pct_change().rolling(tv_window).std(ddof=0) * math.sqrt(ANNUAL_DAYS)
    if curve_so_far.empty:
        row["target"] = 0.0
        row["exec_signal"] = 0.0
        row["base_gross_exposure"] = 0.0
        row["base_nav"] = 1.0
        row["base_nav_high"] = 1.0
        row["nav_decay_nav"] = 1.0
        row["nav_decay_nav_high"] = 1.0
        row["base_target_vol_raw_scale"] = 1.0
        row["target_vol_raw_scale"] = 1.0
        row["base_target_vol_scale"] = 1.0
        row["target_vol_scale"] = 1.0
        row["base_target_vol_deadband_suppressed"] = 0.0
        row["target_vol_deadband_suppressed"] = 0.0
        row["base_realized_vol"] = math.nan
        row["realized_vol"] = math.nan
        row["gross_exposure"] = 0.0
        row["gross_return"] = 0.0
        row["cost"] = 0.0
        row["turnover"] = 0.0
        row["return"] = 0.0
        row["nav"] = 1.0
        row["nav_high"] = 1.0
        return row

    prev_idx = curve_so_far.index[-1]
    prev_row = curve_so_far.iloc[-1]
    if idx not in spread.index or prev_idx not in spread.index:
        return row
    spread_ret = float(spread.loc[idx] / spread.loc[prev_idx] - 1.0)
    signal_date = prev_idx if prev_idx in target_series.index else target_series.loc[target_series.index < idx].index[-1]
    target = float(target_series.loc[signal_date]) if signal_date in target_series.index else 0.0
    raw_scale, target_scale, suppressed = _online_target_vol_scale(pd.Series(row), prev_row, meta, signal_date, vol_series)
    base_exposure = target * target_scale
    prev_base_exposure = _first_numeric(prev_row, ("base_gross_exposure", "gross_exposure"))
    if not math.isfinite(prev_base_exposure):
        prev_base_exposure = 0.0
    cost_rate = _cost_rate_from_meta(meta)
    base_return = base_exposure * spread_ret - abs(base_exposure - prev_base_exposure) * cost_rate
    prev_base_nav = _first_numeric(prev_row, ("base_nav", "nav_decay_nav", "nav"))
    if not math.isfinite(prev_base_nav):
        prev_base_nav = 1.0
    base_nav = prev_base_nav * (1.0 + base_return)
    prev_base_nav_high = _first_numeric(prev_row, ("base_nav_high", "nav_decay_nav_high", "nav_high", "base_nav", "nav_decay_nav", "nav"))
    if not math.isfinite(prev_base_nav_high):
        prev_base_nav_high = prev_base_nav
    base_nav_high = max(prev_base_nav_high, base_nav)
    row["base_gross_exposure"] = base_exposure
    row["base_nav"] = base_nav
    row["base_nav_high"] = base_nav_high
    row["nav_decay_nav"] = base_nav
    row["nav_decay_nav_high"] = base_nav_high
    row["base_target_vol_raw_scale"] = raw_scale
    row["target_vol_raw_scale"] = raw_scale
    row["base_target_vol_scale"] = target_scale
    row["target_vol_scale"] = target_scale
    row["base_target_vol_deadband_suppressed"] = suppressed
    row["target_vol_deadband_suppressed"] = suppressed
    row["base_realized_vol"] = _previous_online_value(vol_series, idx + pd.Timedelta(nanoseconds=1))
    row["realized_vol"] = row["base_realized_vol"]

    multiplier = _online_gate_and_multiplier(idx, row, prev_row, meta, signal_frame, curve_so_far, decay_state_frame=decay_state_frame)
    exposure = base_exposure * multiplier
    prev_exposure = _first_numeric(prev_row, ("gross_exposure",))
    if not math.isfinite(prev_exposure):
        prev_exposure = 0.0
    gross_return = exposure * spread_ret
    cost = abs(exposure - prev_exposure) * cost_rate
    net_return = gross_return - cost
    prev_nav = _first_numeric(prev_row, ("nav",))
    if not math.isfinite(prev_nav):
        prev_nav = 1.0
    prev_nav_high = _first_numeric(prev_row, ("nav_high", "nav"))
    if not math.isfinite(prev_nav_high):
        prev_nav_high = prev_nav
    row["gross_exposure"] = exposure
    row["gross_return"] = gross_return
    row["cost"] = cost
    row["turnover"] = abs(exposure - prev_exposure)
    row["return"] = net_return
    row["nav"] = prev_nav * (1.0 + net_return)
    row["nav_high"] = max(prev_nav_high, row["nav"])
    return row


def _extend_curves_with_online_prices(
    curves: dict[str, pd.DataFrame],
    metas: dict[str, dict],
    panel: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    refreshed: dict[str, pd.DataFrame] = {}
    provisional_date = None
    if panel.attrs.get("mode") == "intraday" and len(panel.index) > 0:
        provisional_date = pd.Timestamp(panel.index[-1]).normalize()
    for config in STRATEGIES:
        curve = curves[config.key].copy()
        online_signal = _online_signal_frame_for_strategy(config, metas.get(config.key, {}), panel)
        legs = STRATEGY_LEGS.get(config.key)
        if not legs or any(asset not in panel.columns for asset in legs):
            refreshed[config.key] = curve
            continue
        long_asset, short_asset = legs
        price = panel[[long_asset, short_asset]].dropna().copy()
        if price.empty or curve.empty:
            refreshed[config.key] = curve
            continue
        decay_state_frame = _online_decay_state_frame(online_signal, metas.get(config.key, {}))
        last_date = pd.Timestamp(curve.index[-1]).normalize()
        price = price.loc[price.index >= last_date]
        if len(price) < 2 or pd.Timestamp(price.index[-1]).normalize() <= last_date:
            refreshed[config.key] = curve
            continue
        ratio_return = (price[long_asset] / price[short_asset]).pct_change()
        new_dates = [idx for idx in ratio_return.index if pd.Timestamp(idx).normalize() > last_date and pd.notna(ratio_return.loc[idx])]
        if not new_dates:
            refreshed[config.key] = curve
            continue
        last = curve.iloc[-1].copy()
        exposure = float(last.get("gross_exposure", 0.0) or 0.0)
        nav = float(last.get("nav", 1.0) or 1.0)
        rows = []
        for idx in new_dates:
            is_provisional = provisional_date is not None and pd.Timestamp(idx).normalize() == provisional_date
            gross_return = exposure * float(ratio_return.loc[idx])
            nav *= 1.0 + gross_return
            row = {col: math.nan for col in curve.columns}
            row.update(
                {
                    "return": gross_return,
                    "gross_return": gross_return,
                    "cost": 0.0,
                    "turnover": 0.0,
                    "gross_exposure": exposure,
                    "nav": nav,
                    "online_incremental_bar": 1.0,
                    "online_provisional_bar": 1.0 if is_provisional else 0.0,
                }
            )
            if idx in online_signal.index:
                for col, value in online_signal.loc[idx].items():
                    if col in curve.columns or col in row:
                        row[col] = value
            curve_so_far = pd.concat(
                [curve, pd.DataFrame([r for _, r in rows], index=pd.DatetimeIndex([d for d, _ in rows]))],
                axis=0,
            ).sort_index()
            row = _fill_online_execution_row(idx, row, curve_so_far, metas.get(config.key, {}), online_signal, decay_state_frame=decay_state_frame)
            rows.append((idx, row))
        extra = pd.DataFrame([row for _, row in rows], index=pd.DatetimeIndex([idx for idx, _ in rows]))
        rebuilt = pd.concat([curve, extra], axis=0).sort_index()
        rebuilt.attrs["online_signal_frame"] = _OnlineSignalFrameRef(online_signal)
        refreshed[config.key] = rebuilt
    return refreshed


def _build_curves_from_online_prices(
    metas: dict[str, dict],
    panel: pd.DataFrame,
    *,
    full_history: bool = False,
) -> dict[str, pd.DataFrame]:
    curves: dict[str, pd.DataFrame] = {}
    provisional_date = None
    if panel.attrs.get("mode") == "intraday" and len(panel.index) > 0:
        provisional_date = pd.Timestamp(panel.index[-1]).normalize()

    for config in STRATEGIES:
        meta = metas.get(config.key, {})
        signal_frame = _online_signal_frame_for_strategy(config, meta, panel)
        if signal_frame.empty or "spread_close" not in signal_frame.columns:
            curves[config.key] = pd.DataFrame()
            continue
        decay_state_frame = _online_decay_state_frame(signal_frame, meta)

        spread = pd.to_numeric(signal_frame["spread_close"], errors="coerce")
        r2_series = pd.to_numeric(signal_frame["r2"], errors="coerce") if "r2" in signal_frame.columns else None
        target_series = _online_target_series(spread, pd.to_numeric(signal_frame["score"], errors="coerce"), meta, r2=r2_series)
        target_vol = meta.get("target_vol", {}) if isinstance(meta.get("target_vol", {}), dict) else {}
        tv_window = int(target_vol.get("target_vol_window") or 20)
        vol_series = spread.pct_change().rolling(tv_window).std(ddof=0) * math.sqrt(ANNUAL_DAYS)
        valid_index = signal_frame.loc[spread.notna()].index
        tail_index = list(valid_index if full_history else valid_index[-ONLINE_REBUILD_LOOKBACK_BARS:])
        rows: list[tuple[pd.Timestamp, dict]] = [] if full_history else _snapshot_seed_rows(config, signal_frame)
        if rows:
            seed_date = rows[-1][0]
            tail_index = [idx for idx in tail_index if pd.Timestamp(idx) > seed_date]
        prev_date: Optional[pd.Timestamp] = rows[-1][0] if rows else None
        prev_row: Optional[dict] = rows[-1][1] if rows else None
        for idx in tail_index:
            signal_row = signal_frame.loc[idx]
            row = signal_row.to_dict()
            is_provisional = provisional_date is not None and pd.Timestamp(idx).normalize() == provisional_date
            row["online_rebuilt_bar"] = 1.0
            row["online_provisional_bar"] = 1.0 if is_provisional else 0.0
            if prev_date is None or prev_row is None:
                curve_so_far = pd.DataFrame()
            else:
                curve_so_far = pd.DataFrame([prev_row], index=pd.DatetimeIndex([prev_date]))
            row = _fill_online_execution_row(
                pd.Timestamp(idx),
                row,
                curve_so_far,
                meta,
                signal_frame,
                decay_state_frame=decay_state_frame,
                target_series=target_series,
                vol_series=vol_series,
            )
            idx = pd.Timestamp(idx)
            rows.append((idx, row))
            prev_date = idx
            prev_row = row

        built = pd.DataFrame(
            [row for _, row in rows],
            index=pd.DatetimeIndex([idx for idx, _ in rows]),
        ).sort_index()
        built.attrs["online_signal_frame"] = _OnlineSignalFrameRef(signal_frame)
        curves[config.key] = built
    return curves


def _snapshot_seed_rows(config: StrategyConfig, signal_frame: pd.DataFrame) -> list[tuple[pd.Timestamp, dict]]:
    snapshot = STATE_SNAPSHOT.get(config.key, {})
    as_of = snapshot.get("as_of")
    values = snapshot.get("values")
    if not as_of or not isinstance(values, dict):
        return []
    seed_idx = pd.Timestamp(str(as_of))
    row = {k: float(v) for k, v in values.items() if isinstance(v, (int, float)) and math.isfinite(float(v))}
    if seed_idx in signal_frame.index:
        for col, value in signal_frame.loc[seed_idx].items():
            if col not in row and pd.notna(value):
                try:
                    row[col] = float(value)
                except (TypeError, ValueError):
                    pass
    row["state_snapshot_seed"] = 1.0
    row["online_rebuilt_bar"] = 0.0
    row["online_provisional_bar"] = 0.0
    row.setdefault("return", 0.0)
    row.setdefault("gross_return", 0.0)
    row.setdefault("cost", 0.0)
    row.setdefault("turnover", 0.0)
    if "nav" in row and "nav_high" not in row:
        row["nav_high"] = row["nav"]
    if "base_nav" in row and "base_nav_high" not in row:
        row["base_nav_high"] = row["base_nav"]
    if "gross_exposure" in row and "base_gross_exposure" not in row:
        row["base_gross_exposure"] = row["gross_exposure"]
    return [(seed_idx, row)]


def load_strategy_context(include_realtime: bool = False) -> tuple[dict[str, pd.DataFrame], dict[str, dict], dict[str, object]]:
    metas = load_strategy_metas()
    online: dict[str, object] = {"ok": False, "error": None, "probes": {}}
    curves: dict[str, pd.DataFrame] = {}
    local_error: Optional[str] = None
    if not POE_ONLINE_ONLY:
        try:
            curves = load_strategy_curves()
        except Exception as exc:
            local_error = str(exc)
    try:
        panel, online_meta = _fetch_online_price_panel(include_realtime=include_realtime)
        if curves and all(not frame.empty for frame in curves.values()):
            curves = _extend_curves_with_online_prices(curves, metas, panel)
            data_mode = "local_artifacts_plus_online"
        else:
            curves = _build_curves_from_online_prices(metas, panel, full_history=False)
            data_mode = "online_rebuild_recent_realtime" if include_realtime else "online_rebuild_recent"
        probes = {
            config.key: _live_probe_for_strategy(config, metas[config.key], panel, seed_curve=curves.get(config.key))
            for config in STRATEGIES
        }
        online = {**online_meta, "ok": True, "error": None, "probes": probes, "data_mode": data_mode}
    except Exception as exc:
        if curves:
            online["error"] = str(exc)
        else:
            online["error"] = f"{exc}; local_artifacts={local_error}"
    return curves, metas, online


_PERFORMANCE_CONTEXT_CACHE: dict[str, object] = {}
_PERFORMANCE_CONTEXT_TTL_SECONDS = 180.0


def load_performance_curves() -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
    now = time.monotonic()
    cached = _PERFORMANCE_CONTEXT_CACHE.get("value")
    cached_at = float(_PERFORMANCE_CONTEXT_CACHE.get("cached_at", 0.0) or 0.0)
    if cached is not None and now - cached_at <= _PERFORMANCE_CONTEXT_TTL_SECONDS:
        return cached  # type: ignore[return-value]

    metas = load_strategy_metas()
    curves: dict[str, pd.DataFrame] = {}
    if not POE_ONLINE_ONLY:
        try:
            curves = load_strategy_curves()
        except Exception:
            curves = {}
    try:
        panel, online_meta = _fetch_online_price_panel(include_realtime=False)
        if curves and all(not frame.empty for frame in curves.values()):
            curves = _extend_curves_with_online_prices(curves, metas, panel)
            data_mode = "local_artifacts_plus_online"
        else:
            curves = _build_curves_from_online_prices(metas, panel, full_history=True)
            data_mode = "online_rebuild_full_performance"
        online = {**online_meta, "ok": True, "error": None, "data_mode": data_mode}
    except Exception as exc:
        if not curves:
            raise
        online = {"ok": False, "error": str(exc), "data_mode": "embedded_artifacts"}
    value = (curves, online)
    _PERFORMANCE_CONTEXT_CACHE.clear()
    _PERFORMANCE_CONTEXT_CACHE.update({"cached_at": now, "value": value})
    return value


def _blend_returns(parts: Iterable[pd.Series]) -> pd.Series:
    frame = pd.concat(list(parts), axis=1, join="inner").dropna(how="any")
    return frame.mean(axis=1)


def _nav_from_returns(returns: pd.Series) -> pd.Series:
    return (1.0 + returns.fillna(0.0)).cumprod()


def build_combo_curves(curves: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    combos: dict[str, pd.DataFrame] = {}
    pair_returns: dict[str, pd.Series] = {}

    for pair_key, _label, forward_key, reverse_key in PAIR_DEFS:
        fwd = curves[forward_key]
        rev = curves[reverse_key]
        pair_return = _blend_returns([fwd["return"].rename("forward"), rev["return"].rename("reverse")])
        idx = pair_return.index
        frame = pd.DataFrame(index=idx)
        frame["forward_return"] = fwd.loc[idx, "return"].astype(float)
        frame["reverse_return"] = rev.loc[idx, "return"].astype(float)
        frame["return"] = pair_return.astype(float)
        frame["gross_return"] = frame["return"]
        frame["cost"] = (
            pd.to_numeric(fwd.loc[idx].get("cost", 0.0), errors="coerce").fillna(0.0) * 0.5
            + pd.to_numeric(rev.loc[idx].get("cost", 0.0), errors="coerce").fillna(0.0) * 0.5
        )
        frame["turnover"] = (
            pd.to_numeric(fwd.loc[idx].get("turnover", 0.0), errors="coerce").fillna(0.0) * 0.5
            + pd.to_numeric(rev.loc[idx].get("turnover", 0.0), errors="coerce").fillna(0.0) * 0.5
        )
        frame["gross_exposure"] = (
            pd.to_numeric(fwd.loc[idx].get("gross_exposure", 0.0), errors="coerce").fillna(0.0) * 0.5
            + pd.to_numeric(rev.loc[idx].get("gross_exposure", 0.0), errors="coerce").fillna(0.0) * 0.5
        )
        frame["nav"] = _nav_from_returns(frame["return"])
        combos[pair_key] = frame
        pair_returns[pair_key] = frame["return"].rename(pair_key)

    total_return = _blend_returns(pair_returns.values())
    total = pd.DataFrame(index=total_return.index)
    for pair_key, _label, _forward_key, _reverse_key in PAIR_DEFS:
        total[f"{pair_key}_return"] = combos[pair_key].loc[total.index, "return"].astype(float)
        total[f"{pair_key}_forward_return"] = curves[_forward_key].loc[total.index, "return"].astype(float)
        total[f"{pair_key}_reverse_return"] = curves[_reverse_key].loc[total.index, "return"].astype(float)
    total["return"] = total_return.astype(float)
    total["gross_return"] = total["return"]
    total["cost"] = pd.concat([combos[k].loc[total.index, "cost"] for k in pair_returns], axis=1).mean(axis=1)
    total["turnover"] = pd.concat([combos[k].loc[total.index, "turnover"] for k in pair_returns], axis=1).mean(axis=1)
    total["gross_exposure"] = pd.concat([combos[k].loc[total.index, "gross_exposure"] for k in pair_returns], axis=1).mean(axis=1)
    total["nav"] = _nav_from_returns(total["return"])
    combos["all_pair_equal_weight"] = total
    return combos


def drawdown(nav: pd.Series) -> pd.Series:
    nav = nav.astype(float)
    return nav / nav.cummax() - 1.0


def metrics_for_curve(curve: pd.DataFrame) -> dict[str, Union[float, int, str]]:
    if curve.empty:
        return {
            "start": "",
            "end": "",
            "rows": 0,
            "period_return": math.nan,
            "ann_return": math.nan,
            "ann_vol": math.nan,
            "max_dd": math.nan,
            "sharpe": math.nan,
            "calmar": math.nan,
            "final_nav": math.nan,
        }
    returns = pd.to_numeric(curve["return"], errors="coerce").fillna(0.0)
    nav = _nav_from_returns(returns)
    rows = int(len(returns))
    final_nav = float(nav.iloc[-1])
    period_return = final_nav - 1.0
    max_dd = float(drawdown(nav).min())
    if rows >= MIN_ANNUALIZED_METRIC_ROWS:
        ann_return = final_nav ** (ANNUAL_DAYS / max(rows, 1)) - 1.0
        ann_vol = float(returns.std(ddof=0) * math.sqrt(ANNUAL_DAYS)) if rows > 1 else math.nan
        sharpe = ann_return / ann_vol if ann_vol > 1e-12 else math.nan
        calmar = ann_return / abs(max_dd) if abs(max_dd) > 1e-12 else math.nan
    else:
        ann_return = math.nan
        ann_vol = math.nan
        sharpe = math.nan
        calmar = math.nan
    return {
        "start": curve.index[0].strftime("%Y-%m-%d"),
        "end": curve.index[-1].strftime("%Y-%m-%d"),
        "rows": rows,
        "period_return": period_return,
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "calmar": calmar,
        "final_nav": final_nav,
    }


def _normalize_query(query: str) -> str:
    q = (query or "").strip()
    replacements = {}
    for old, new in replacements.items():
        q = q.replace(old, new)
    return q


_CN_NUM_MAP = {}


def _parse_natural_number(text: str) -> Optional[float]:
    token = str(text or "").strip()
    if not token:
        return None
    if token.isdigit():
        return float(int(token))
    normalized = _CN_NUM_MAP.get(token)
    if normalized is not None:
        return float(normalized)
    return None

def _parse_natural_relative_window(q: str) -> Optional[tuple[str, float]]:
    return None

def parse_date_range(query: str, index: pd.DatetimeIndex) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    q = str(query or "").upper()
    raw = str(query or "")
    end = pd.Timestamp(index.max()).normalize()
    start = pd.Timestamp(index.min()).normalize()
    label = "全样本"

    if "10Y" in q or "TEN_Y" in q or "最近10年" in raw or "最近十年" in raw:
        start = end - pd.DateOffset(years=10)
        label = "最近10年"
    elif "5Y" in q or "FIVE_Y" in q or "最近5年" in raw or "最近五年" in raw:
        start = end - pd.DateOffset(years=5)
        label = "最近5年"
    elif "3Y" in q or "THREE_Y" in q or "最近3年" in raw or "最近三年" in raw:
        start = end - pd.DateOffset(years=3)
        label = "最近3年"
    elif "1Y" in q or "ONE_Y" in q or "最近1年" in raw or "最近一年" in raw:
        start = end - pd.DateOffset(years=1)
        label = "最近1年"

    start = max(pd.Timestamp(index.min()).normalize(), start)
    end = min(pd.Timestamp(index.max()).normalize(), end)
    return start, end, label


def _slice_curve(curve: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return curve.loc[(curve.index >= start) & (curve.index <= end)].copy()


def _metric_table(rows: list[tuple[str, dict]]) -> list[str]:
    out = [
        "| 策略 | 区间收益 | 年化收益 | 年化波动 | 最大回撤 | 夏普 | Calmar | 期末净值 | 起止/行数 |",
        "|:-|------:|------:|------:|------:|------:|------:|------:|:-|",
    ]
    for label, metrics in rows:
        out.append(
            f"| {label} | {pct(metrics['period_return'])} | {pct(metrics['ann_return'])} | "
            f"{pct(metrics['ann_vol'])} | {pct(metrics['max_dd'])} | {num(metrics['sharpe'])} | "
            f"{num(metrics['calmar'])} | {num(metrics['final_nav'], 4)} | "
            f"{metrics['start']}~{metrics['end']} / {metrics['rows']} |"
        )
    return out


def render_performance(query: str, combo: bool = False) -> str:
    curves, online = load_performance_curves()
    if combo:
        curves_to_report = build_combo_curves(curves)
        order = [(pair_key, label) for pair_key, label, _forward_key, _reverse_key in PAIR_DEFS]
        order.append(("all_pair_equal_weight", f"{len(PAIR_DEFS)}组再等权总组合"))
        shared_index = curves_to_report["all_pair_equal_weight"].index
        heading = "## 组合表现"
        note = f"{len(PAIR_DEFS)}组正反50/50，再将{len(PAIR_DEFS)}组等权；组合层不额外收费。"
    else:
        curves_to_report = curves
        order = [(config.key, config.display_name) for config in STRATEGIES]
        shared_index = pd.DatetimeIndex(sorted(set.union(*(set(curves[k].index) for k, _ in order))))
        heading = "## ADK价差子策略表现"
        note = f"{len(STRATEGIES)}个子策略按在线重建日收益统计；各子策略保留自身正式样本起点。"

    start, end, label = parse_date_range(query, shared_index)
    if label == "全样本":
        data_mode = str(online.get("data_mode", ""))
        if data_mode.startswith("online_rebuild_recent"):
            label = f"Poe最近窗口（约{ONLINE_REBUILD_LOOKBACK_BARS}个交易日）"
        elif data_mode == "online_rebuild_full_performance":
            label = f"Poe在线价格窗口（约{ONLINE_FETCH_LOOKBACK_BARS}个交易日）"
    rows = [(display, metrics_for_curve(_slice_curve(curves_to_report[key], start, end))) for key, display in order]
    lines = [heading, "", f"- 查询区间: **{label}** ({start:%Y-%m-%d} 至 {end:%Y-%m-%d})", f"- 口径: {note}"]
    if online.get("ok"):
        latest = max((df.index.max() for df in curves.values() if not df.empty), default=end)
        lines.append(f"- 在线刷新: **成功**（{online.get('mode', 'daily')}，最新 {latest:%Y-%m-%d}，抓取 {online.get('fetched_at', 'N/A')}）")
        if str(online.get("data_mode", "")).startswith("online_rebuild"):
            lines.append("- 数据来源: Poe 在线窗口重建（Sina/EastMoney/Tencent 公开指数日线 + 脚本内嵌参数 metadata），不读取本地正式 artifacts。")
            lines.append("- 注意: 该口径用于 Poe 在线展示，不代表本地正式长期回测；NAV 在在线窗口起点重置为 1.0。")
    elif online.get("error"):
        lines.append(f"- 在线刷新: **失败**；原因: `{online.get('error')}`")
    lines.append("")
    lines.extend(_metric_table(rows))
    return "\n".join(lines).rstrip() + "\n"


def _last_change_date(curve: pd.DataFrame) -> str:
    exposure = pd.to_numeric(curve.get("gross_exposure", pd.Series(index=curve.index, dtype=float)), errors="coerce").fillna(0.0)
    delta = exposure.diff().abs().fillna(exposure.abs())
    changed = delta > 1e-9
    if not changed.any():
        return "N/A"
    return changed[changed].index[-1].strftime("%Y-%m-%d")


def _status_from_exposure(exposure: float) -> str:
    if abs(exposure) < 1e-9:
        return "空仓/防守"
    return f"有效敞口 {pct(exposure, 1)}"



def _overlay_summary(row: pd.Series, amount_gate_override: Optional[bool] = None) -> str:
    parts: list[str] = []

    def active(cols: tuple[str, ...]) -> bool:
        for col in cols:
            if col in row.index and pd.notna(row[col]):
                try:
                    if abs(float(row[col])) > 1e-12:
                        return True
                except (TypeError, ValueError):
                    continue
        return False

    groups = (
        ("NAV防守", ("nav_defense_gate", "base_nav_defense_gate", "nav_on")),
        ("动量衰减", ("decay_gate", "base_decay_gate", "decay_on")),
        ("波动过热", ("overheat_gate", "volhot_gate", "vol_gate", "overheat_on")),
        ("Score过热", ("scorehot_gate",)),
        ("成交额/成交量", ("amount_gate", "amount_on", "volume_on", "volume_gate")),
    )
    for label, cols in groups:
        if label == "成交额/成交量" and amount_gate_override is not None:
            if amount_gate_override:
                parts.append(label)
            continue
        if active(cols):
            parts.append(label)
    return "，".join(parts) if parts else "无触发"

def _to_binary_signal(value: object) -> Optional[int]:
    try:
        num_value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num_value):
        return None
    return 1 if num_value >= 0.5 else 0


def _extract_signal_for_row(row: pd.Series, probe: Optional[dict[str, object]]) -> Optional[float]:
    if probe:
        target = probe.get("target")
        try:
            value = float(target)
            if math.isfinite(value):
                return value
        except (TypeError, ValueError):
            pass
    for key in ("target", "exec_signal", "raw_signal"):
        if key in row.index and pd.notna(row[key]):
            try:
                value = float(row[key])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                return value
    return None


def _extract_score_for_row(row: pd.Series, probe: Optional[dict[str, object]]) -> float:
    if probe:
        probe_score = probe.get("score")
        try:
            value = float(probe_score)
            if math.isfinite(value):
                return value
        except (TypeError, ValueError):
            pass
    if "score" in row.index:
        value = row.get("score")
        try:
            value = float(value)
        except (TypeError, ValueError):
            return math.nan
        return value if math.isfinite(value) else math.nan
    return math.nan


def _first_numeric(row: pd.Series, names: tuple[str, ...]) -> float:
    keys = row.index if hasattr(row, "index") else row.keys() if hasattr(row, "keys") else ()
    for name in names:
        if name in keys and pd.notna(row[name]):
            try:
                return float(row[name])
            except (TypeError, ValueError):
                continue
    return math.nan


def _first_numeric_with_history(curve: pd.DataFrame, row: pd.Series, names: tuple[str, ...]) -> float:
    value = _first_numeric(row, names)
    if math.isfinite(value):
        return value
    for name in names:
        if name not in curve.columns:
            continue
        series = pd.to_numeric(curve[name], errors="coerce").dropna()
        if not series.empty:
            return float(series.iloc[-1])
    return math.nan


def _amount_value_columns(row: pd.Series) -> tuple[str, ...]:
    fixed = [
        "amount_ma_ratio",
        "amount_indicator",
        "amount_aux",
        "amount_ratio_zz1000_hs300",
        "amount_ratio_hs300_zz1000",
        "amount_ratio_cyb_hs300",
        "amount_ratio_hs300_cyb",
        "amount_ratio_zz1000_sz50",
        "amount_ratio_sz50_zz1000",
        "amount_ratio_cyb_sz50",
        "amount_ratio_sz50_cyb",
        "amount_ratio_zz500_sz50",
        "amount_ratio_sz50_zz500",
        "amount_ratio_hs300_zz500",
        "amount_ratio_zz500_hs300",
        "amount_ratio_cyb_zz500",
        "amount_ratio_zz500_cyb",
    ]
    keys = row.index if hasattr(row, "index") else ()
    dynamic = []
    for name in keys:
        low = str(name).lower()
        if "amount" not in low:
            continue
        if any(skip in low for skip in ("threshold", "window", "scale", "confirm", "feature", "param")):
            continue
        if any(token in low for token in ("ratio", "indicator", "aux", "ma")):
            dynamic.append(str(name))
    return tuple(dict.fromkeys([*fixed, *dynamic]))



def _safe_float(value: object, default: float = math.nan) -> float:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _signal_abs_day(signal: dict) -> object:
    if not isinstance(signal, dict):
        return None
    value = signal.get("abs_mom_day")
    return signal.get("abs_ma") if value in (None, "") else value


def _target_vol_deadband(section: dict) -> object:
    if not isinstance(section, dict):
        return None
    return _first_section_value(section, ("deadband", "scale_deadband", "deadband_value"))


def _target_vol_deadband_mode(section: dict) -> str:
    if not isinstance(section, dict):
        return "rel"
    value = _first_section_value(section, ("deadband_mode", "deadband_type"))
    text = str(value or "").strip().lower()
    if text.startswith("abs") or "absolute" in text:
        return "abs"
    return "rel"


def _target_vol_deadband_suppressed(raw_scale: float, prev_scale: float, section: dict) -> bool:
    deadband = _safe_float(_target_vol_deadband(section))
    if not math.isfinite(deadband) or not math.isfinite(raw_scale) or not math.isfinite(prev_scale):
        return False
    if prev_scale <= 1e-12:
        return False
    if _target_vol_deadband_mode(section) == "abs":
        return abs(raw_scale - prev_scale) < deadband
    return abs(raw_scale / prev_scale - 1.0) < deadband


def _threshold_from_section(section: dict) -> object:
    if not isinstance(section, dict):
        return None
    for key in ("threshold", "nav_threshold", "nav_dd_threshold", "amount_threshold", "volume_threshold"):
        value = section.get(key)
        if value not in (None, ""):
            return value
    return None


def _first_section_value(section: dict, names: tuple[str, ...]) -> object:
    if not isinstance(section, dict):
        return None
    for name in names:
        value = section.get(name)
        if value not in (None, ""):
            return value
    return None


def _decay_threshold(section: dict) -> object:
    return _first_section_value(section, ("decay_threshold", "decay_ratio", "decay_ratio_threshold", "threshold"))


def _decay_recovery_threshold(section: dict) -> object:
    return _first_section_value(section, ("recovery_threshold", "recovery_ratio", "recovery_ratio_threshold"))


def _scorehot_threshold(section: dict) -> object:
    if not isinstance(section, dict):
        return None
    value = section.get("threshold")
    return section.get("score_threshold") if value in (None, "") else value


def _cost_rate_from_meta(meta: dict) -> float:
    cost_model = meta.get("cost_model", {}) if isinstance(meta.get("cost_model", {}), dict) else {}
    bps = cost_model.get("one_way_cost_bps")
    if bps not in (None, ""):
        return float(bps) / 10000.0
    commission = cost_model.get("one_way_commission")
    if commission not in (None, ""):
        return float(commission)
    return 0.0


def _gate_text(value: float) -> str:
    value = _safe_float(value)
    if not math.isfinite(value):
        return "无数据"
    return "触发" if abs(value) > 1e-12 else "未触发"


def _pass_text(value: bool) -> str:
    return "通过" if value else "未通过"


def _pct_abs_threshold(value: object) -> str:
    value = _safe_float(value)
    if not math.isfinite(value):
        return "N/A"
    return pct(abs(value))


def _confirm_days(section: dict) -> object:
    value = section.get("confirm_days") if isinstance(section, dict) else None
    if value in (None, "") and isinstance(section, dict):
        value = section.get("warmup_days")
    return 1 if value in (None, "") else value


def _md_cell(value: object) -> str:
    text = str(value)
    text = text.replace("|", "／")
    # Poe's markdown table renderer may show raw <br> text inside cells.
    # Keep table cells single-line and use semicolons for separation.
    text = re.sub(r"\s*\n\s*", "；", text)
    return text


def _md_row(*cols: object) -> str:
    return "| " + " | ".join(_md_cell(col) for col in cols) + " |"

def _scale_from_section(section: dict, default: float = 1.0) -> float:
    if not isinstance(section, dict):
        return default
    for key in ("scale", "derisk_scale", "nav_scale", "amount_scale", "volume_scale", "defense_scale"):
        value = section.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default
    return default


def _downonly_tv_scale_from_realized_vol(realized_vol: float, section: dict) -> float:
    if not isinstance(section, dict) or section.get("kind") != "downonly_tv":
        return math.nan
    target_vol = section.get("target_vol")
    if target_vol in (None, ""):
        return math.nan
    if not math.isfinite(realized_vol) or realized_vol <= 1e-12:
        return math.nan
    try:
        min_scale = float(section.get("min_scale", 0.0))
    except (TypeError, ValueError):
        min_scale = 0.0
    if min_scale < 0.0:
        min_scale = 0.0
    try:
        target = float(target_vol)
        cap = target / float(realized_vol)
    except (TypeError, ValueError):
        return math.nan
    cap = max(min_scale, min(cap, 1.0))
    gate = section.get("target_vol_gate")
    if gate in (None, ""):
        gate = section.get("gate", 0.0)
    if not math.isfinite(gate):
        gate = 0.0
    gate = float(gate)
    if gate > 0.0:
        cap = cap if cap <= (1.0 - gate) else 1.0
    return float(cap)


def _vol_overlay_section(meta: dict) -> dict:
    vol = meta.get("vol_overheat")
    if isinstance(vol, dict) and vol.get("enabled"):
        return vol

    overheat = meta.get("overheat")
    if isinstance(overheat, dict) and overheat.get("enabled"):
        if overheat.get("kind") == "downonly_tv":
            return {
                "enabled": True,
                "kind": "downonly_tv",
                "window": overheat.get("window"),
                "target_vol": overheat.get("target_vol"),
                "min_scale": overheat.get("min_scale", 0.0),
                "target_vol_gate": overheat.get("gate", overheat.get("target_vol_gate", 0.0)),
                "source": "overheat",
            }
    return {}


def _amount_overlay_section(meta: dict) -> dict:
    for key in ("amount_overlay", "amount_overheat"):
        section = meta.get(key)
        if isinstance(section, dict) and section.get("enabled"):
            out = dict(section)
            family = str(out.get("family") or "")
            if not family:
                text = " ".join(
                    str(out.get(name) or "").lower()
                    for name in ("feature", "kind", "series")
                )
                if "pair" in text and any(token in text for token in ("hot", "high")):
                    family = "high_pair"
                elif "pair" in text and any(token in text for token in ("low", "cold")):
                    family = "low_pair"
                elif any(token in text for token in ("hot", "high")):
                    family = "high_single"
                elif any(token in text for token in ("low", "cold")):
                    family = "low_single"
                if family:
                    out["family"] = family
            return out
    return {}


def _volume_overlay_sections(meta: dict) -> list[dict]:
    out = []
    for key, label, gate_cols, value_cols in (
        ("volume_overlay", "成交量叠加", ("volume_on", "volume_gate"), ("volume_indicator", "volume_ma_ratio")),
        (
            "layer10_volume_overlay",
            "Layer10成交量",
            ("layer10_volume_on", "layer10_volume_gate", "volume_on", "volume_gate"),
            ("layer10_volume_indicator", "layer10_volume_ma_ratio", "volume_indicator", "volume_ma_ratio"),
        ),
        (
            "final_ridge_overlay",
            "Final成交量",
            ("ridge_on", "final_ridge_on", "final_ridge_gate", "ridge_gate"),
            ("final_ridge_indicator", "ridge_indicator", "volume_indicator", "final_ridge_ma_ratio", "volume_ma_ratio"),
        ),
    ):
        section = meta.get(key)
        if isinstance(section, dict) and section.get("enabled"):
            item = dict(section)
            item["_meta_key"] = key
            item["_label"] = label
            item["_gate_cols"] = gate_cols
            item["_value_cols"] = value_cols
            family = str(item.get("family") or "")
            if not family:
                text = " ".join(str(item.get(name) or "").lower() for name in ("feature", "kind", "series"))
                if "pair" in text and any(token in text for token in ("hot", "high")):
                    family = "high_pair"
                elif "pair" in text and any(token in text for token in ("low", "cold")):
                    family = "low_pair"
                elif any(token in text for token in ("hot", "high")):
                    family = "high_single"
                elif any(token in text for token in ("low", "cold")):
                    family = "low_single"
                if family:
                    item["family"] = family
            out.append(item)
    return out


def _has_amount_sensitive_overlay(meta: dict) -> bool:
    return bool(_amount_overlay_section(meta) or _volume_overlay_sections(meta))


def _nav_drawdown_value(curve: pd.DataFrame) -> tuple[float, str]:
    if curve.empty:
        return math.nan, "nav"
    candidates: list[tuple[int, int, str, pd.Series]] = []
    for col in ("pre_overlay_nav", "pre_nav_defense_nav", "base_nav", "nav_decay_nav", "nav"):
        if col not in curve.columns:
            continue
        series = pd.to_numeric(curve[col], errors="coerce").dropna()
        high_col = f"{col}_high"
        if len(series) >= 2 or high_col in curve.columns:
            candidates.append((len(series), -len(candidates), col, series))
    if not candidates:
        return math.nan, "nav"
    max_len = max(item[0] for item in candidates)
    min_len = 1 if max_len < 2 else max(2, int(max_len * 0.8))
    _, _, nav_col, nav = max((item for item in candidates if item[0] >= min_len), key=lambda item: item[1])
    if nav.empty:
        return math.nan, nav_col
    high = float(nav.cummax().iloc[-1])
    high_col = f"{nav_col}_high"
    if high_col in curve.columns:
        high_series = pd.to_numeric(curve[high_col], errors="coerce").dropna()
        if not high_series.empty:
            high = max(high, float(high_series.iloc[-1]))
    last = float(nav.iloc[-1])
    if high <= 0:
        return math.nan, nav_col
    return last / high - 1.0, nav_col


def _nav_drawdown_from_state_row(row: pd.Series) -> float:
    for nav_col in ("base_nav", "nav_decay_nav", "nav"):
        nav = _safe_float(row.get(nav_col))
        high = _safe_float(row.get(f"{nav_col}_high"))
        if not math.isfinite(high):
            high = _safe_float(row.get("nav_high"))
        if math.isfinite(nav) and math.isfinite(high) and high > 0:
            return nav / high - 1.0
    return math.nan


def _score_history_series(curve: pd.DataFrame, row: pd.Series) -> pd.Series:
    for col in ("score", "base_score", "signal_score"):
        if col not in curve.columns:
            continue
        series = pd.to_numeric(curve[col], errors="coerce").dropna()
        if not series.empty:
            return series
    value = _first_numeric(row, ("score", "base_score", "signal_score"))
    if math.isfinite(value):
        return pd.Series([value])
    return pd.Series(dtype="float64")


def _score_current_value(curve: pd.DataFrame, row: pd.Series) -> float:
    value = _first_numeric_with_history(curve, row, ("score", "base_score", "signal_score"))
    if math.isfinite(value):
        return value
    series = _score_history_series(curve, row)
    return float(series.iloc[-1]) if not series.empty else math.nan


def _score_peak_decay_ratio(curve: pd.DataFrame, row: pd.Series) -> float:
    series = _score_history_series(curve, row)
    if series.empty:
        return math.nan
    frame = pd.DataFrame({"score": series})
    if "raw_signal" in curve.columns:
        frame["active"] = pd.to_numeric(curve["raw_signal"], errors="coerce").reindex(frame.index)
    elif "target" in curve.columns:
        frame["active"] = pd.to_numeric(curve["target"], errors="coerce").reindex(frame.index)
    elif "exec_signal" in curve.columns:
        frame["active"] = pd.to_numeric(curve["exec_signal"], errors="coerce").reindex(frame.index)
    else:
        frame["active"] = 1.0
    if getattr(row, "name", None) in frame.index:
        frame = frame.loc[frame.index <= row.name]

    peak = math.nan
    last_ratio = math.nan
    for _, item in frame.iterrows():
        active = _safe_float(item.get("active"), 0.0) > 0.5
        current = _safe_float(item.get("score"))
        if (not active) or (not math.isfinite(current)):
            peak = math.nan
            last_ratio = math.nan
            continue
        if current <= 0.0:
            peak = math.nan
            last_ratio = 0.0
            continue
        peak = current if not math.isfinite(peak) else max(peak, current)
        ratio = current / peak if peak > 1e-12 else math.nan
        if math.isfinite(ratio):
            last_ratio = max(0.0, ratio)
    return last_ratio


def _score_strength_peak_decay_ratio(curve: pd.DataFrame, row: pd.Series) -> float:
    if "score_strength" not in curve.columns:
        return math.nan
    frame = pd.DataFrame({"strength": pd.to_numeric(curve["score_strength"], errors="coerce")})
    if "raw_signal" in curve.columns:
        frame["active"] = pd.to_numeric(curve["raw_signal"], errors="coerce")
    elif "target" in curve.columns:
        frame["active"] = pd.to_numeric(curve["target"], errors="coerce")
    elif "exec_signal" in curve.columns:
        frame["active"] = pd.to_numeric(curve["exec_signal"], errors="coerce")
    else:
        frame["active"] = 1.0
    if getattr(row, "name", None) in frame.index:
        frame = frame.loc[frame.index <= row.name]
    if frame.empty:
        return math.nan

    peak = math.nan
    last_ratio = math.nan
    for _, item in frame.iterrows():
        active = _safe_float(item.get("active"), 0.0) > 0.5
        strength = _safe_float(item.get("strength"))
        if (not active) or (not math.isfinite(strength)) or strength <= 0.0:
            peak = math.nan
            continue
        peak = strength if not math.isfinite(peak) else max(peak, strength)
        ratio = strength / peak if peak > 0 else math.nan
        if math.isfinite(ratio):
            last_ratio = ratio
    return last_ratio


def _series_until_row(series: pd.Series, row: pd.Series) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce")
    row_name = getattr(row, "name", None)
    if row_name is None or row_name not in series.index:
        return series
    try:
        loc = series.index.get_loc(row_name)
    except (KeyError, TypeError):
        return series
    if isinstance(loc, slice):
        return series.iloc[: loc.stop]
    if isinstance(loc, int):
        return series.iloc[: loc + 1]
    return series


def _positive_peak_ratio_for_display(series: pd.Series, row: pd.Series) -> float:
    history = _series_until_row(series, row).dropna()
    if history.empty:
        return math.nan
    current = _safe_float(history.iloc[-1])
    if not math.isfinite(current):
        return math.nan
    positive = history[history > 0.0]
    if positive.empty or current <= 0.0:
        return 0.0
    peak = _safe_float(positive.max())
    if not math.isfinite(peak) or peak <= 1e-12:
        return math.nan
    return max(0.0, current / peak)


def _realtime_decay_ratio_for_display(curve: pd.DataFrame, row: pd.Series, meta: dict) -> float:
    decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
    if not decay.get("enabled"):
        return math.nan
    source = curve.attrs.get("online_signal_frame") if isinstance(getattr(curve, "attrs", None), dict) else None
    if isinstance(source, _OnlineSignalFrameRef):
        source = source.frame
    frame = source if isinstance(source, pd.DataFrame) and not source.empty else curve
    mode = _online_decay_mode(frame, decay)
    if mode == "score_strength":
        if "score_strength" in frame.columns:
            strength = pd.to_numeric(frame["score_strength"], errors="coerce")
        else:
            score = pd.to_numeric(frame["score"], errors="coerce").dropna() if "score" in frame.columns else _score_history_series(curve, row)
            threshold = _safe_float((meta.get("signal", {}) if isinstance(meta.get("signal", {}), dict) else {}).get("score_threshold"))
            if score.empty or not math.isfinite(threshold):
                return math.nan
            strength = (score - threshold).clip(lower=0.0)
        return _positive_peak_ratio_for_display(strength, row)

    score = pd.to_numeric(frame["score"], errors="coerce").dropna() if "score" in frame.columns else _score_history_series(curve, row)
    return _positive_peak_ratio_for_display(score, row)


def _online_decay_state_for_display(curve: pd.DataFrame, row: pd.Series, meta: dict) -> tuple[float, float, float, bool]:
    source = curve.attrs.get("online_signal_frame") if isinstance(getattr(curve, "attrs", None), dict) else None
    if isinstance(source, _OnlineSignalFrameRef):
        source = source.frame
    frame = source if isinstance(source, pd.DataFrame) and not source.empty else curve
    if frame.empty:
        return math.nan, math.nan, math.nan, True
    try:
        states = _online_decay_state_frame(frame, meta)
    except Exception:
        return math.nan, math.nan, math.nan, True
    row_name = getattr(row, "name", None)
    if states.empty or row_name is None:
        return math.nan, math.nan, math.nan, True
    if row_name in states.index:
        state_row = states.loc[row_name]
    elif isinstance(states.index, pd.DatetimeIndex):
        prior_idx = states.index[states.index <= row_name]
        if len(prior_idx) == 0:
            return math.nan, math.nan, math.nan, True
        state_row = states.loc[prior_idx[-1]]
    else:
        return math.nan, math.nan, math.nan, True
    active = True
    if row_name in frame.index:
        active_value = _first_numeric(frame.loc[row_name], ("raw_signal", "target", "exec_signal"))
        if math.isfinite(active_value):
            active = active_value > 0.5
    return _safe_float(state_row.get("ratio")), _safe_float(state_row.get("gate")), _safe_float(state_row.get("mult")), active


def _online_decay_ratio_for_display(curve: pd.DataFrame, row: pd.Series, meta: dict) -> float:
    try:
        states = _online_decay_state_frame(curve, meta)
    except Exception:
        return math.nan
    if states.empty or "ratio" not in states.columns:
        return math.nan
    row_name = getattr(row, "name", None)
    if row_name in states.index:
        return _safe_float(states.loc[row_name, "ratio"])
    if row_name is not None:
        prior = states.loc[states.index <= row_name, "ratio"] if isinstance(states.index, pd.DatetimeIndex) else pd.Series(dtype=float)
    else:
        prior = states["ratio"]
    prior = pd.to_numeric(prior, errors="coerce").dropna()
    return float(prior.iloc[-1]) if not prior.empty else math.nan


def _online_decay_active_series(signal_frame: pd.DataFrame, meta: dict) -> pd.Series:
    if "spread_close" not in signal_frame.columns or "score" not in signal_frame.columns:
        return pd.Series(1.0, index=signal_frame.index)
    spread = pd.to_numeric(signal_frame["spread_close"], errors="coerce")
    score = pd.to_numeric(signal_frame["score"], errors="coerce")
    r2 = pd.to_numeric(signal_frame["r2"], errors="coerce") if "r2" in signal_frame.columns else None
    return _online_target_series(spread, score, meta, r2=r2)


def _online_decay_mode(signal_frame: pd.DataFrame, decay: dict) -> str:
    basis = str(decay.get("basis") or decay.get("peak_basis") or "").strip().lower()
    if basis in {"score_strength", "strength"}:
        return "score_strength"
    if basis in {"score", "raw_score", "score_peak"}:
        return "score_peak_warmup"
    if any(key in decay for key in ("decay_ratio", "recovery_ratio", "derisk_scale")):
        return "strict_score_peak"
    timing = str(decay.get("timing") or "").lower()
    if "score-strength" in timing or "score strength" in timing:
        return "score_strength"
    if "score-peak" in timing or "score peak" in timing:
        return "score_peak_warmup"
    if "score_strength" in signal_frame.columns and "warmup_days" in decay:
        return "score_strength"
    return "generic_score_peak"


def _online_decay_state_frame(signal_frame: pd.DataFrame, meta: dict) -> pd.DataFrame:
    decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
    if not decay.get("enabled") or "score" not in signal_frame.columns:
        return pd.DataFrame(index=signal_frame.index)
    score = pd.to_numeric(signal_frame["score"], errors="coerce")
    mode = _online_decay_mode(signal_frame, decay)
    if mode == "score_strength":
        strength = pd.to_numeric(signal_frame["score_strength"], errors="coerce")
        if "raw_signal" in signal_frame.columns:
            active = pd.to_numeric(signal_frame["raw_signal"], errors="coerce").fillna(0.0)
        elif "target" in signal_frame.columns:
            active = pd.to_numeric(signal_frame["target"], errors="coerce").fillna(0.0)
        elif "exec_signal" in signal_frame.columns:
            active = pd.to_numeric(signal_frame["exec_signal"], errors="coerce").fillna(0.0)
        else:
            active = _online_decay_active_series(signal_frame, meta)
        decay_ratio = _safe_float(_decay_threshold(decay))
        recovery_ratio = _safe_float(_decay_recovery_threshold(decay))
        warmup_days = int(_safe_float(decay.get("warmup_days", decay.get("confirm_days", 1.0)), 1.0))
        scale = _scale_from_section(decay)
        peak = math.nan
        active_days = 0
        in_decay = False
        ratios = []
        gates = []
        mults = []
        for idx in signal_frame.index:
            is_active = _safe_float(active.get(idx), 0.0) > 0.5
            cur_strength = _safe_float(strength.get(idx))
            ratio = math.nan
            if (not is_active) or (not math.isfinite(cur_strength)) or cur_strength <= 0.0:
                peak = math.nan
                active_days = 0
                in_decay = False
            else:
                active_days += 1
                peak = cur_strength if not math.isfinite(peak) else max(peak, cur_strength)
                ratio = cur_strength / peak if peak > 0 else math.nan
                if active_days >= max(warmup_days, 1):
                    if in_decay:
                        if math.isfinite(ratio) and ratio >= recovery_ratio:
                            in_decay = False
                            peak = cur_strength
                    elif math.isfinite(ratio) and ratio <= decay_ratio:
                        in_decay = True
            ratios.append(ratio)
            gates.append(1.0 if in_decay else 0.0)
            mults.append(scale if in_decay else 1.0)
    elif mode in {"strict_score_peak", "score_peak_warmup"}:
        active = _online_decay_active_series(signal_frame, meta)
        decay_ratio = _safe_float(_decay_threshold(decay))
        recovery_ratio = _safe_float(_decay_recovery_threshold(decay))
        confirm_days = int(_safe_float(decay.get("confirm_days"), 1.0))
        warmup_days = int(_safe_float(decay.get("warmup_days", confirm_days), float(confirm_days)))
        scale = _scale_from_section(decay)
        peak = math.nan
        in_decay = False
        need_new_peak = False
        below_count = 0
        active_days = 0
        ratios: list[float] = []
        gates: list[float] = []
        mults: list[float] = []
        for idx in signal_frame.index:
            is_active = _safe_float(active.get(idx), 0.0) > 0.5
            cur_score = _safe_float(score.get(idx))
            ratio = math.nan
            if (not is_active) or (not math.isfinite(cur_score)) or cur_score <= 0.0:
                peak = math.nan
                in_decay = False
                need_new_peak = False
                below_count = 0
                active_days = 0
            else:
                if not math.isfinite(peak):
                    peak = cur_score
                    in_decay = False
                    need_new_peak = False
                    below_count = 0
                    active_days = 0
                elif cur_score > peak:
                    peak = cur_score
                    if need_new_peak:
                        need_new_peak = False
                ratio = cur_score / peak if peak > 0 else math.nan

                if mode == "score_peak_warmup":
                    active_days += 1
                    if active_days >= max(warmup_days, 1):
                        if in_decay:
                            if ratio >= recovery_ratio:
                                in_decay = False
                                # Warmup score-peak scans re-arm on the recovery bar; strict decay_ratio configs wait for a fresh peak.
                                peak = cur_score
                        elif ratio <= decay_ratio:
                            in_decay = True
                else:
                    if in_decay:
                        if ratio >= recovery_ratio:
                            in_decay = False
                            need_new_peak = True
                            below_count = 0
                    elif not need_new_peak:
                        if ratio <= decay_ratio:
                            below_count += 1
                        else:
                            below_count = 0
                        if below_count >= max(confirm_days, 1):
                            in_decay = True
                    else:
                        below_count = 0
            ratios.append(ratio)
            gates.append(1.0 if in_decay else 0.0)
            mults.append(scale if in_decay else 1.0)
    else:
        decay_threshold = _safe_float(_decay_threshold(decay))
        recovery_threshold = _safe_float(_decay_recovery_threshold(decay))
        scale = _scale_from_section(decay)
        if not math.isfinite(recovery_threshold):
            recovery_threshold = decay_threshold
        score_peak: Optional[float] = None
        derisk_next = False
        waiting_for_new_peak = False
        rearm_peak: Optional[float] = None
        ratios = []
        gates = []
        mults = []
        for idx in signal_frame.index:
            cur_score = _safe_float(score.get(idx))
            if math.isfinite(cur_score):
                score_peak = cur_score if score_peak is None else max(score_peak, cur_score)
            ratio = cur_score / score_peak if score_peak is not None and score_peak > 1e-12 and math.isfinite(cur_score) else math.nan

            if waiting_for_new_peak and rearm_peak is not None and score_peak is not None and score_peak > rearm_peak + 1e-12:
                waiting_for_new_peak = False
                rearm_peak = None

            if derisk_next:
                if math.isfinite(ratio) and ratio >= recovery_threshold:
                    derisk_next = False
                    waiting_for_new_peak = True
                    rearm_peak = score_peak
            elif not waiting_for_new_peak and math.isfinite(ratio) and ratio <= decay_threshold:
                derisk_next = True
            ratios.append(ratio)
            gates.append(1.0 if derisk_next else 0.0)
            mults.append(scale if derisk_next else 1.0)

    return pd.DataFrame(
        {"ratio": ratios, "gate": gates, "mult": mults},
        index=signal_frame.index,
    )


def _apply_online_decay_state(
    row: dict,
    signal_frame: pd.DataFrame,
    as_of: pd.Timestamp,
    meta: dict,
    state_frame: Optional[pd.DataFrame] = None,
) -> None:
    decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
    if not decay.get("enabled") or "score" not in signal_frame.columns:
        return
    states = state_frame if state_frame is not None else _online_decay_state_frame(signal_frame, meta)
    if states.empty:
        return
    idx = states.index[states.index <= as_of]
    if len(idx) == 0:
        return
    state = states.loc[idx[-1]]
    ratio = _safe_float(state.get("ratio"))
    gate = _safe_float(state.get("gate"))
    mult = _safe_float(state.get("mult"))
    row["decay_ratio_signal_day"] = ratio
    row["decay_indicator"] = ratio
    row["score_decay_ratio_overlay"] = ratio
    row["decay_gate"] = gate
    row["base_decay_gate"] = gate
    row["decay_scale"] = mult
    row["decay_mult"] = mult


def _nav_drawdown_for_row(curve_so_far: pd.DataFrame, row: dict) -> tuple[float, str]:
    if curve_so_far.empty:
        frame = pd.DataFrame([row])
    else:
        frame = pd.concat([curve_so_far, pd.DataFrame([row])], axis=0)
    return _nav_drawdown_value(frame)


def _infer_gate_from_threshold(current: float, threshold: object, op: str) -> float:
    current = _safe_float(current)
    threshold_value = _safe_float(threshold)
    if not math.isfinite(current) or not math.isfinite(threshold_value):
        return math.nan
    if op == ">=":
        return 1.0 if current >= threshold_value else 0.0
    if op == "<=":
        return 1.0 if current <= threshold_value else 0.0
    return math.nan



def _detail_join(parts: Iterable[object]) -> str:
    clean: list[str] = []
    for part in parts:
        text = str(part).strip()
        if text and text != "None":
            clean.append(text)
    return "；".join(clean) if clean else "N/A"


def _gate_triggered(value: object) -> bool:
    value_float = _safe_float(value)
    return math.isfinite(value_float) and abs(value_float) > 1e-12


def _effect_text(gate: object, scale: object) -> str:
    scale_text = pct(_safe_float(scale), 1)
    if _gate_triggered(gate):
        return f"本次×{scale_text}"
    return f"若触发×{scale_text}"


def _threshold_text(op: str, value: object, as_pct: bool = False, digits: int = 2) -> str:
    value_float = _safe_float(value)
    if not math.isfinite(value_float):
        return f"{op} N/A"
    if as_pct:
        return f"{op} {pct(value_float, digits)}"
    return f"{op} {num(value_float, digits)}"


def _metric_text(value: object, as_pct: bool = False, digits: int = 3) -> str:
    value_float = _safe_float(value)
    if not math.isfinite(value_float):
        return "N/A"
    if as_pct:
        return pct(value_float, 2)
    return num(value_float, digits)


def _overlay_detail_rows(
    curve: pd.DataFrame,
    row: pd.Series,
    meta: dict,
    probe: Optional[dict] = None,
    live: bool = False,
) -> list[tuple[str, str]]:
    """Compact, row-aligned detail for the forward/reverse comparison table."""
    rows: list[tuple[str, str]] = []

    signal = meta.get("signal", {}) if isinstance(meta.get("signal", {}), dict) else {}
    score_value = _safe_float(probe.get("score") if probe else row.get("score", math.nan))
    score_threshold = _safe_float(signal.get("score_threshold"))
    if math.isfinite(score_threshold):
        score_pass = math.isfinite(score_value) and score_value > score_threshold
        abs_day = _signal_abs_day(signal)
        abs_threshold = _safe_float(signal.get("abs_threshold"))
        abs_mom = _safe_float(probe.get("abs_mom") if probe else math.nan)
        abs_pass = True
        if math.isfinite(abs_threshold):
            abs_pass = math.isfinite(abs_mom) and abs_mom > abs_threshold
        parts = [
            _pass_text(score_pass and abs_pass),
            f"Score {num(score_value, 3)} / 阈值 {num(score_threshold, 3)}",
        ]
        if math.isfinite(abs_threshold):
            if math.isfinite(abs_mom):
                parts.append(f"AbsMom{abs_day} {pct(abs_mom)} / 阈值 {pct(abs_threshold)}")
            else:
                parts.append(f"AbsMom{abs_day} 阈值 {pct(abs_threshold)}")
        rows.append(("基础Score", _detail_join(parts)))

    tv = meta.get("target_vol", {}) if isinstance(meta.get("target_vol", {}), dict) else {}
    if tv.get("enabled"):
        scale = _first_numeric(row, ("target_vol_scale", "base_target_vol_scale"))
        raw_scale = _first_numeric(row, ("target_vol_raw_scale", "base_target_vol_raw_scale"))
        suppressed = _first_numeric(row, ("target_vol_deadband_suppressed", "base_target_vol_deadband_suppressed"))
        parts = [
            "启用",
            f"目标 {pct(tv.get('target_vol'))} / w{tv.get('target_vol_window')}",
            f"scale {num(scale, 3)}",
        ]
        if math.isfinite(raw_scale):
            parts.append(f"raw {num(raw_scale, 3)}")
        deadband = _target_vol_deadband(tv)
        if deadband not in (None, ""):
            deadband_status = "触发" if math.isfinite(suppressed) and suppressed > 0 else "未触发"
            parts.append(f"deadband {pct(deadband, 1)} / mode {_target_vol_deadband_mode(tv)} {deadband_status}")
        if tv.get("gate") not in (None, ""):
            parts.append(f"gate {pct(tv.get('gate'), 1)}")
        rows.append(("目标波动", _detail_join(parts)))

    nav = meta.get("nav_defense", {}) if isinstance(meta.get("nav_defense", {}), dict) else {}
    if nav.get("enabled"):
        gate = _first_numeric_with_history(
            curve,
            row,
            ("nav_defense_gate", "base_nav_defense_gate", "nav_on", "nav_gate", "nav_defense_on"),
        )
        dd_value, nav_col = _nav_drawdown_value(curve)
        scale = _scale_from_section(nav)
        threshold_value = _safe_float(_threshold_from_section(nav))
        mult = _first_numeric_with_history(curve, row, ("nav_mult", "nav_defense_mult", "nav_scale"))
        if not math.isfinite(gate) and math.isfinite(mult):
            gate = 0.0 if abs(mult - 1.0) < 1e-12 else 1.0
        if not math.isfinite(gate) and math.isfinite(dd_value) and math.isfinite(threshold_value):
            gate = 1.0 if dd_value <= -abs(threshold_value) else 0.0
        note = ""
        if (
            math.isfinite(gate)
            and abs(gate) > 1e-12
            and math.isfinite(dd_value)
            and math.isfinite(threshold_value)
            and dd_value > -abs(threshold_value)
        ):
            note = "当前NAV仅参考"
        gate_text = _gate_text(gate) if math.isfinite(gate) else "静态未导出"
        if note:
            gate_text = "执行期触发"
        parts = [
            gate_text,
            f"回撤 {pct(dd_value)} / 条件 ≤ -{_pct_abs_threshold(_threshold_from_section(nav))}",
            f"{_effect_text(gate, scale)}",
            note,
        ]
        rows.append(("NAV防守", _detail_join(parts)))

    vol = _vol_overlay_section(meta)
    if vol.get("enabled"):
        gate = _first_numeric(row, ("overheat_gate", "volhot_gate", "vol_gate", "overheat_on"))
        current = _safe_float(probe.get("vol_overheat_value") if probe else math.nan)
        if not math.isfinite(current):
            current = _first_numeric(row, ("overheat_indicator", "volhot_indicator", "vol_indicator", "base_realized_vol", "realized_vol"))
        if vol.get("kind") == "downonly_tv":
            scale = _first_numeric(row, ("overheat_scale", "volhot_scale", "vol_scale"))
            if not math.isfinite(scale):
                scale = _downonly_tv_scale_from_realized_vol(current, vol)
            parts = [
                _gate_text(gate),
                f"波动 {_metric_text(current, as_pct=True)} / 目标 {pct(vol.get('target_vol'))}",
                f"w{vol.get('window')}",
                _effect_text(gate, scale),
            ]
        else:
            scale = _scale_from_section(vol)
            parts = [
                _gate_text(gate),
                f"波动 {_metric_text(current, as_pct=True)} / 条件 ≥ {pct(vol.get('threshold'))}",
                f"w{vol.get('window')}",
                _effect_text(gate, scale),
            ]
        rows.append(("波动过热", _detail_join(parts)))

    scorehot = meta.get("score_overheat", {}) if isinstance(meta.get("score_overheat", {}), dict) else {}
    if scorehot.get("enabled"):
        gate = _first_numeric_with_history(curve, row, ("scorehot_gate", "scorehot_on"))
        current = _first_numeric_with_history(curve, row, ("scorehot_indicator", "scorehot_aux", "score"))
        if not math.isfinite(current):
            current = _score_current_value(curve, row)
        scale = _scale_from_section(scorehot)
        mult = _first_numeric_with_history(curve, row, ("scorehot_mult", "scorehot_scale"))
        if not math.isfinite(gate) and math.isfinite(mult):
            gate = 0.0 if abs(mult - 1.0) < 1e-12 else 1.0
        threshold = _scorehot_threshold(scorehot)
        if not math.isfinite(gate):
            gate = _infer_gate_from_threshold(current, threshold, ">=")
        rows.append((
            "Score过热",
            _detail_join([
                _gate_text(gate) if math.isfinite(gate) else "静态未导出",
                f"Score {num(current, 3)} / 条件 ≥ {num(threshold, 3)}",
                _effect_text(gate, scale),
            ]),
        ))

    decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
    if decay.get("enabled"):
        gate = _first_numeric_with_history(curve, row, ("decay_gate", "base_decay_gate", "decay_on"))
        decision_ratio, state_gate, _state_mult, state_active = _online_decay_state_for_display(curve, row, meta)
        current_cols = ("decay_ratio_signal_day", "decay_indicator", "score_decay_ratio_overlay", "decay_aux")
        has_current_decay_col = any(col in row.index for col in current_cols)
        reference_ratio = _realtime_decay_ratio_for_display(curve, row, meta)
        exported_ratio = _first_numeric(row, current_cols) if has_current_decay_col else _first_numeric_with_history(curve, row, current_cols)
        if not math.isfinite(decision_ratio) and not math.isfinite(reference_ratio):
            decision_ratio = exported_ratio
        if not math.isfinite(decision_ratio) and not math.isfinite(reference_ratio):
            state_ratio = _online_decay_ratio_for_display(curve, row, meta)
            if math.isfinite(state_ratio):
                decision_ratio = state_ratio
            else:
                strength_ratio = _score_strength_peak_decay_ratio(curve, row)
                reference_ratio = strength_ratio if math.isfinite(strength_ratio) else _score_peak_decay_ratio(curve, row)
        scale = _scale_from_section(decay)
        mult = _first_numeric_with_history(curve, row, ("decay_mult", "decay_scale"))
        display_ratio = reference_ratio if math.isfinite(reference_ratio) else decision_ratio
        if state_active and math.isfinite(display_ratio):
            gate = _infer_gate_from_threshold(display_ratio, _decay_threshold(decay), "<=")
            mult = _scale_from_section(decay) if _gate_triggered(gate) else 1.0
        elif not state_active:
            gate = 0.0
            mult = 1.0
        if not math.isfinite(gate) and math.isfinite(mult):
            gate = 0.0 if abs(mult - 1.0) < 1e-12 else 1.0
        if not math.isfinite(gate):
            gate_basis = display_ratio if math.isfinite(display_ratio) else math.nan
            gate = _infer_gate_from_threshold(gate_basis, _decay_threshold(decay), "<=")
        ratio_parts: list[str] = []
        if math.isfinite(display_ratio):
            ratio_parts.append(f"动量衰减比 {num(display_ratio, 3)}")
        else:
            ratio_parts.append("动量衰减比不可计算")
        if not state_active:
            ratio_parts.append("基础信号未激活")
        gate_text = "静态未导出"
        if math.isfinite(gate):
            gate_text = "未触发" if abs(gate) <= 1e-12 else "执行期触发"
        rows.append((
            "动量衰减",
            _detail_join([
                gate_text,
                *ratio_parts,
                f"衰减 {num(_decay_threshold(decay), 3)} / 恢复 {num(_decay_recovery_threshold(decay), 3)}",
                f"d{_confirm_days(decay)}",
                _effect_text(gate, scale),
            ]),
        ))

    amount = _amount_overlay_section(meta)
    if amount:
        gate = _first_numeric_with_history(curve, row, ("amount_gate", "amount_on"))
        current = _first_numeric_with_history(curve, row, _amount_value_columns(row))
        scale = _scale_from_section(amount)
        family = str(amount.get("family") or "")
        op = "≤" if "low" in family else "≥"
        amount_state = probe.get("amount_state", {}) if probe and isinstance(probe.get("amount_state", {}), dict) else {}
        if live and amount_state.get("available"):
            gate_value = 1.0 if amount_state.get("gate") else 0.0
            basis = amount_state.get("basis") or "amount"
            rows.append((
                "成交额叠加",
                _detail_join([
                    _gate_text(gate_value),
                    f"{basis} {num(amount_state.get('value'), 3)} / 条件 {op} {num(amount_state.get('threshold'), 3)}",
                    f"w{amount_state.get('window')} / d{amount_state.get('confirm_days')}",
                    _effect_text(gate_value, amount_state.get("scale")),
                ]),
            ))
        elif live and amount_state.get("enabled") and not amount_state.get("available"):
            rows.append((
                "成交额叠加",
                _detail_join([
                    f"在线不可判定：{amount_state.get('reason', 'unknown')}",
                    f"静态{_gate_text(gate)}",
                    f"值 {num(current, 3)} / 条件 {op} {num(_threshold_from_section(amount), 3)}",
                    f"w{amount.get('window')} / d{_confirm_days(amount)}",
                    _effect_text(gate, scale),
                ]),
            ))
        else:
            rows.append((
                "成交额叠加",
                _detail_join([
                    _gate_text(gate),
                    f"值 {num(current, 3)} / 条件 {op} {num(_threshold_from_section(amount), 3)}",
                    f"w{amount.get('window')} / d{_confirm_days(amount)}",
                    _effect_text(gate, scale),
                ]),
            ))

    for volume in _volume_overlay_sections(meta):
        gate = _first_numeric_with_history(curve, row, tuple(volume.get("_gate_cols", ())))
        current = _first_numeric_with_history(curve, row, tuple(volume.get("_value_cols", ())))
        scale = _scale_from_section(volume)
        mult = _first_numeric_with_history(curve, row, ("volume_mult", "layer10_volume_mult", "ridge_mult", "final_ridge_mult"))
        if not math.isfinite(gate) and math.isfinite(mult):
            gate = 0.0 if abs(mult - 1.0) < 1e-12 else 1.0
        family = str(volume.get("family") or "")
        op = "≤" if "low" in family else "≥"
        rows.append((
            str(volume.get("_label") or "成交量叠加"),
            _detail_join([
                _gate_text(gate) if math.isfinite(gate) else "静态未导出",
                f"值 {num(current, 3)} / 条件 {op} {num(_threshold_from_section(volume), 3)}",
                f"w{volume.get('window')} / d{_confirm_days(volume)}",
                _effect_text(gate, scale),
            ]),
        ))

    return rows or [("叠加规则", "无启用规则")]


def _overlay_detail_lines(
    curve: pd.DataFrame,
    row: pd.Series,
    meta: dict,
    probe: Optional[dict] = None,
    live: bool = False,
) -> list[str]:
    return [f"{name}：{detail}" for name, detail in _overlay_detail_rows(curve, row, meta, probe=probe, live=live)]


def _current_overlay_multiplier(row: pd.Series, meta: dict, amount_gate_override: Optional[bool] = None) -> float:
    multiplier = 1.0
    gate_specs = [
        ("nav_defense_gate", meta.get("nav_defense", {}), "scale"),
        ("decay_gate", meta.get("momentum_decay", {}), "scale"),
        ("scorehot_gate", meta.get("score_overheat", {}), "scale"),
        ("amount_gate", meta.get("amount_overlay", {}), "scale"),
        ("amount_on", meta.get("amount_overlay", {}), "scale"),
        ("amount_gate", meta.get("amount_overheat", {}), "scale"),
        ("amount_on", meta.get("amount_overheat", {}), "scale"),
    ]
    amount_scaled = False
    for col, section, key in gate_specs:
        if col == "amount_gate" and (not isinstance(section, dict) or not section.get("enabled")):
            continue
        if col == "amount_on" and (not isinstance(section, dict) or not section.get("enabled")):
            continue
        if col in {"amount_gate", "amount_on"} and amount_scaled:
            continue
        if col in {"amount_gate", "amount_on"} and amount_gate_override is not None:
            gate_active = bool(amount_gate_override)
        else:
            gate_active = col in row.index and pd.notna(row[col]) and float(row[col]) != 0.0
        if not gate_active:
            continue
        scale = section.get(key) if isinstance(section, dict) else None
        if scale is None and isinstance(section, dict):
            scale = section.get("derisk_scale")
        if scale is None:
            scale = 0.0
        try:
            multiplier *= float(scale)
        except (TypeError, ValueError):
            multiplier *= 0.0
        if col in {"amount_gate", "amount_on"}:
            amount_scaled = True

    for volume in _volume_overlay_sections(meta):
        gate_active = False
        for col in volume.get("_gate_cols", ()):
            if col in row.index and pd.notna(row[col]):
                try:
                    if float(row[col]) != 0.0:
                        gate_active = True
                        break
                except (TypeError, ValueError):
                    continue
        if gate_active:
            multiplier *= _scale_from_section(volume)

    vol = _vol_overlay_section(meta)
    if vol.get("enabled"):
        gate = _first_numeric(row, ("overheat_gate", "volhot_gate", "vol_gate"))
        current = math.nan
        if vol.get("kind") == "downonly_tv":
            for col in ("overheat_indicator", "volhot_indicator", "vol_indicator", "realized_vol", "base_realized_vol"):
                if col in row.index and pd.notna(row[col]) and math.isfinite(float(row[col])):
                    current = float(row[col])
                    break
            scale = _first_numeric(row, ("overheat_scale", "volhot_scale", "vol_scale"))
            if not math.isfinite(scale):
                scale = _downonly_tv_scale_from_realized_vol(current, vol)
        else:
            scale = _scale_from_section(vol)
        if math.isfinite(gate) and abs(gate) > 1e-12 and math.isfinite(scale):
            multiplier *= float(scale)
    return max(0.0, multiplier)


def _unknown_live_overlay_reason(
    row: pd.Series,
    meta: dict,
    online_target: float,
    amount_state: dict,
    known_overlay_multiplier: float,
) -> Optional[str]:
    if abs(online_target) <= 1e-12:
        return None
    if abs(known_overlay_multiplier) <= 1e-12:
        return None
    if _has_amount_sensitive_overlay(meta) and not amount_state.get("available"):
        return f"Amount overlay unavailable: {amount_state.get('reason', 'unknown')}"
    nav = meta.get("nav_defense", {}) if isinstance(meta.get("nav_defense", {}), dict) else {}
    if nav.get("enabled") and not math.isfinite(_first_numeric(row, ("nav_defense_gate", "base_nav_defense_gate"))):
        return "NAV defense gate failed to compute"
    vol = _vol_overlay_section(meta)
    if vol.get("enabled"):
        gate = _first_numeric(row, ("overheat_gate", "volhot_gate", "vol_gate"))
        if vol.get("kind") == "downonly_tv":
            current = _first_numeric(row, ("overheat_indicator", "volhot_indicator", "vol_indicator", "base_realized_vol", "realized_vol"))
            if not math.isfinite(gate) and not math.isfinite(
                _downonly_tv_scale_from_realized_vol(current, vol)
            ):
                return "Vol-overheat gate failed to compute"
        elif not math.isfinite(gate):
            return "Vol overheat gate failed to compute"
    scorehot = meta.get("score_overheat", {}) if isinstance(meta.get("score_overheat", {}), dict) else {}
    if scorehot.get("enabled") and not math.isfinite(_first_numeric(row, ("scorehot_gate",))):
        return "Score overheat gate failed to compute"
    decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
    if decay.get("enabled") and not math.isfinite(_first_numeric(row, ("decay_gate",))):
        return "Momentum decay gate failed to compute"
    target_vol = meta.get("target_vol", {}) if isinstance(meta.get("target_vol", {}), dict) else {}
    if target_vol.get("enabled"):
        scale = _first_numeric(row, ("target_vol_scale", "base_target_vol_scale"))
        if not math.isfinite(scale):
            return "Target-vol scale failed to compute"
    return None

def _amount_gate_override_from_probe(probe: Optional[dict]) -> Optional[bool]:
    if not probe:
        return None
    state = probe.get("amount_state")
    if isinstance(state, dict) and state.get("available"):
        return bool(state.get("gate"))
    return None


def _row_with_current_decay_display(curve: pd.DataFrame, row: pd.Series, meta: dict) -> pd.Series:
    out = row.copy()
    decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
    if not decay.get("enabled"):
        return out
    state_ratio, _state_gate, _state_mult, active = _online_decay_state_for_display(curve, row, meta)
    ratio = _realtime_decay_ratio_for_display(curve, row, meta)
    if not math.isfinite(ratio):
        ratio = state_ratio
    if not active:
        for col in ("decay_gate", "base_decay_gate", "decay_on"):
            out[col] = 0.0
        for col in ("decay_mult", "decay_scale"):
            out[col] = 1.0
        if math.isfinite(ratio):
            for col in ("decay_ratio_signal_day", "decay_indicator", "score_decay_ratio_overlay", "decay_aux"):
                out[col] = ratio
        return out
    gate = _infer_gate_from_threshold(ratio, _decay_threshold(decay), "<=")
    mult = _scale_from_section(decay) if _gate_triggered(gate) else 1.0
    if math.isfinite(gate):
        for col in ("decay_gate", "base_decay_gate", "decay_on"):
            out[col] = gate
    if math.isfinite(mult):
        for col in ("decay_mult", "decay_scale"):
            out[col] = mult
    if math.isfinite(ratio):
        for col in ("decay_ratio_signal_day", "decay_indicator", "score_decay_ratio_overlay", "decay_aux"):
            out[col] = ratio
    return out


def _strategy_signal_snapshot(
    config: StrategyConfig,
    curve: pd.DataFrame,
    meta: dict,
    online: dict,
    live: bool,
) -> dict[str, object]:
    confirmed_curve = curve
    if "online_provisional_bar" in confirmed_curve.columns:
        provisional = pd.to_numeric(confirmed_curve["online_provisional_bar"], errors="coerce").fillna(0.0) > 0
        if (~provisional).any():
            confirmed_curve = confirmed_curve.loc[~provisional]
    row = confirmed_curve.iloc[-1]
    probe: Optional[dict[str, object]] = None
    if live and isinstance(online, dict):
        candidate = online.get("probes", {}).get(config.key)  # type: ignore[assignment]
        if isinstance(candidate, dict):
            probe = candidate
    display_row = _row_with_current_decay_display(confirmed_curve, row, meta)

    sample_end = confirmed_curve.index[-1].strftime("%Y-%m-%d")
    sample_start = confirmed_curve.index[0].strftime("%Y-%m-%d")
    exposure = _safe_float(row.get("gross_exposure", row.get("net_exposure", 0.0)), 0.0)
    effective_exposure = exposure
    signal_value = _extract_signal_for_row(row, probe)
    score = _extract_score_for_row(row, probe)
    target_signal = _to_binary_signal(signal_value)
    base_signal_exposure = 1.0 if target_signal == 1 else 0.0 if target_signal == 0 else math.nan
    exec_signal_value = _first_numeric(row, ("exec_signal", "target"))
    exec_target_signal = _to_binary_signal(exec_signal_value)

    tv = meta.get("target_vol", {}) if isinstance(meta.get("target_vol", {}), dict) else {}
    tv_scale = _first_numeric(row, ("target_vol_scale", "base_target_vol_scale", "target_vol_applied_scale", "applied_scale", "scale"))
    if not math.isfinite(tv_scale) and not tv.get("enabled"):
        tv_scale = 1.0
    base_after_tv = _first_numeric(row, ("base_gross_exposure", "target_exposure", "pre_overlay_exposure", "target_vol_base_weight", "base_weight"))
    if not math.isfinite(base_after_tv) and math.isfinite(base_signal_exposure) and math.isfinite(tv_scale):
        base_after_tv = base_signal_exposure * tv_scale
    if exec_target_signal is not None:
        exec_base_signal_exposure = 1.0 if exec_target_signal == 1 else 0.0
    elif math.isfinite(base_after_tv) and math.isfinite(tv_scale) and abs(tv_scale) > 1e-12:
        exec_base_signal_exposure = base_after_tv / tv_scale
    else:
        exec_base_signal_exposure = base_signal_exposure
    amount_gate_override = _amount_gate_override_from_probe(probe)
    overlay_multiplier = math.nan
    if math.isfinite(base_after_tv) and abs(base_after_tv) > 1e-12:
        overlay_multiplier = exposure / base_after_tv
    if not math.isfinite(overlay_multiplier):
        overlay_multiplier = _current_overlay_multiplier(display_row, meta, amount_gate_override)
    if not math.isfinite(overlay_multiplier):
        overlay_multiplier = math.nan
    current_overlay_multiplier = _current_overlay_multiplier(display_row, meta, amount_gate_override)
    if not math.isfinite(current_overlay_multiplier):
        current_overlay_multiplier = overlay_multiplier

    post_close_tv_scale = _first_numeric(row, ("target_vol_raw_scale", "raw_scale", "target_vol_scale", "base_target_vol_scale", "target_vol_applied_scale", "applied_scale", "scale"))
    if not math.isfinite(post_close_tv_scale):
        post_close_tv_scale = tv_scale if math.isfinite(tv_scale) else 1.0
    if not tv.get("enabled"):
        post_close_tv_scale = 1.0
    post_close_overlay = current_overlay_multiplier if math.isfinite(current_overlay_multiplier) else 1.0
    post_close_exposure = (
        base_signal_exposure * post_close_tv_scale * post_close_overlay
        if math.isfinite(base_signal_exposure) and math.isfinite(post_close_tv_scale) and math.isfinite(post_close_overlay)
        else math.nan
    )

    if not math.isfinite(exec_base_signal_exposure):
        formula = "N/A"
    elif math.isfinite(tv_scale) and math.isfinite(overlay_multiplier):
        formula = f"收益期基础 {pct(exec_base_signal_exposure, 1)} × TV {num(tv_scale, 3)} × 叠加 {num(overlay_multiplier, 3)} = {pct(exposure, 1)}"
    elif math.isfinite(tv_scale):
        formula = f"收益期基础 {pct(exec_base_signal_exposure, 1)} × TV {num(tv_scale, 3)} × 叠加 N/A = {pct(exposure, 1)}"
    else:
        formula = f"收益期基础 {pct(exec_base_signal_exposure, 1)}；收益期敞口 {pct(exposure, 1)}"
    if math.isfinite(post_close_exposure):
        if math.isfinite(base_signal_exposure) and math.isfinite(post_close_tv_scale) and math.isfinite(post_close_overlay):
            formula += (
                f"；收盘执行后 {pct(post_close_exposure, 1)}"
                f"（信号 {pct(base_signal_exposure, 1)} × TV {num(post_close_tv_scale, 3)} × 叠加 {num(post_close_overlay, 3)}）"
            )
        else:
            formula += f"；收盘执行后 {pct(post_close_exposure, 1)}"

    tv_text = "未启用"
    if tv.get("enabled"):
        tv_text = f"scale {num(tv_scale, 3)}"
        raw_scale = _first_numeric(row, ("target_vol_raw_scale", "base_target_vol_raw_scale"))
        if math.isfinite(raw_scale):
            tv_text += f"；raw {num(raw_scale, 3)}"
        suppressed = _first_numeric(row, ("target_vol_deadband_suppressed", "base_target_vol_deadband_suppressed"))
        if _target_vol_deadband(tv) not in (None, ""):
            tv_text += f"；deadband {'触发' if math.isfinite(suppressed) and suppressed > 0 else '未触发'}"

    detail_rows = _overlay_detail_rows(confirmed_curve, display_row, meta, probe=probe, live=live)
    detail_lines = [f"{name}：{detail}" for name, detail in detail_rows]
    target_label = "本期target"
    signal_label = "本期信号"
    signal_status = _status_from_exposure(base_signal_exposure) if target_signal is not None else "N/A"
    exec_basis_status = _status_from_exposure(exec_base_signal_exposure) if math.isfinite(exec_base_signal_exposure) else "N/A"
    effective_status = _status_from_exposure(effective_exposure) if math.isfinite(effective_exposure) else "N/A"
    post_close_status = _status_from_exposure(post_close_exposure) if math.isfinite(post_close_exposure) else "N/A"
    return {
        "direction": config.direction_en,
        "sample": f"**{sample_end}**；样本 {sample_start} 至 {sample_end}，{len(confirmed_curve)}行",
        "target_score": f"{target_label}: **{target_signal if target_signal is not None else 'N/A'}**；Score: {num(float(score), 3) if pd.notna(score) else 'N/A'}",
        "exposure": f"上期/当前已生效（{sample_end}收益期）**{pct(effective_exposure, 1)}**；本期执行敞口（{sample_end}收盘信号后）**{pct(post_close_exposure, 1)}**",
        "basic_exec": f"上期执行：**{effective_status}**；{signal_label}：**{signal_status}**；本期执行：**{post_close_status}**",
        "tv": tv_text,
        "formula": formula,
        "overlay_summary": _overlay_summary(display_row, amount_gate_override),
        "overlay_detail": "；".join(detail_lines),
        "overlay_rows": detail_rows,
    }


def _merged_overlay_detail_rows(
    forward_rows: list[tuple[str, str]],
    reverse_rows: list[tuple[str, str]],
) -> list[tuple[str, str, str]]:
    order = [
        "基础Score",
        "目标波动",
        "NAV防守",
        "波动过热",
        "Score过热",
        "动量衰减",
        "成交额叠加",
        "成交量叠加",
        "叠加规则",
    ]
    forward_map = {name: detail for name, detail in forward_rows}
    reverse_map = {name: detail for name, detail in reverse_rows}
    labels: list[str] = []
    for label in order:
        if label in forward_map or label in reverse_map:
            labels.append(label)
    for label in list(forward_map) + list(reverse_map):
        if label not in labels:
            labels.append(label)
    return [(label, forward_map.get(label, "未启用"), reverse_map.get(label, "未启用")) for label in labels]


def render_signal(live: bool = False) -> str:
    curves, metas, online = load_strategy_context(include_realtime=live)
    now = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
    title = "## 实时信号" if live else "## 运行信号"
    lines = [title, f"- Snapshot: {now}", ""]
    if online.get("ok"):
        lines.append(f'- Data source mode: {online.get("mode", "daily")}')
        if online.get("fetched_at"):
            lines.append(f'- Data fetched at: {online.get("fetched_at")}')
        if str(online.get("data_mode", "")).startswith("online_rebuild"):
            lines.append("- Data source: Poe 在线重建（公开指数日线/实时快照 + 脚本内嵌参数 metadata），不读取本地正式 artifacts。")
            lines.append("- Usage: 用于 Poe 实时信号展示；与本地正式回测 artifacts 可能存在小幅差异。")
    else:
        lines.append("- Data source: unavailable")
    lines.append("")

    required = [config.key for config in STRATEGIES]
    missing = [key for key in required if key not in curves or curves[key].empty or key not in metas]
    available_pair_count = sum(
        1
        for _pair_key, _pair_display, forward_key, reverse_key in PAIR_DEFS
        if forward_key not in missing and reverse_key not in missing
    )
    if missing and available_pair_count == 0:
        return (
            f"{title}\n\n"
            f"- 在线重建失败: `{online.get('error', 'unknown')}`\n"
            f"- 缺失策略数: {len(missing)} / {len(required)}\n"
            "- 当前 Poe 版本不读取本地正式 artifacts；需要在线行情成功后才能生成信号。\n"
        )
    if missing:
        lines.append(f"- 部分策略缺失: {len(missing)} / {len(required)}；以下仅显示可在线重建的组合。")
        if online.get("error"):
            lines.append(f"- 缺失原因: `{online.get('error')}`")
        lines.append("")

    configs = {config.key: config for config in STRATEGIES}
    for _pair_key, pair_display, forward_key, reverse_key in PAIR_DEFS:
        pair_title = pair_display.replace(" 正反50/50", "")
        pair_missing = [key for key in (forward_key, reverse_key) if key in missing]
        if pair_missing:
            lines.extend([
                f"### {pair_title}",
                "",
                f"- 暂不可用: 缺失 `{', '.join(pair_missing)}`",
                "",
            ])
            continue
        forward_config = configs[forward_key]
        reverse_config = configs[reverse_key]
        forward = _strategy_signal_snapshot(forward_config, curves[forward_key], metas[forward_key], online, live)
        reverse = _strategy_signal_snapshot(reverse_config, curves[reverse_key], metas[reverse_key], online, live)
        lines.extend([
            f"### {pair_title}",
            "",
            "| 指标 | 正向 | 反向 |",
            "|:-|:-|:-|",
            _md_row("方向", forward["direction"], reverse["direction"]),
            _md_row("确认日 / 样本", forward["sample"], reverse["sample"]),
            _md_row("信号 / Score", forward["target_score"], reverse["target_score"]),
            _md_row("仓位", forward["exposure"], reverse["exposure"]),
            _md_row("基础 / 执行", forward["basic_exec"], reverse["basic_exec"]),
            _md_row("目标波动", forward["tv"], reverse["tv"]),
            _md_row("仓位归因", forward["formula"], reverse["formula"]),
            _md_row("叠加摘要", forward["overlay_summary"], reverse["overlay_summary"]),
            "",
            "**叠加明细**",
            "",
            "| 规则 | 正向 | 反向 |",
            "|:-|:-|:-|",
        ])
        for label, forward_detail, reverse_detail in _merged_overlay_detail_rows(
            forward["overlay_rows"], reverse["overlay_rows"]
        ):
            lines.append(_md_row(label, forward_detail, reverse_detail))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_meta_value(value: object) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    value_float = _safe_float(value)
    if math.isfinite(value_float):
        return num(value_float, 4)
    if value is None:
        return "None"
    return str(value)


def _target_vol_detail(tv: dict) -> str:
    if not isinstance(tv, dict) or not tv.get("enabled"):
        return f"enabled=False, max_leverage={_format_meta_value(tv.get('max_leverage') if isinstance(tv, dict) else None)}"
    parts = [
        "enabled=True",
        f"target_vol={_format_meta_value(tv.get('target_vol'))}",
        f"window={tv.get('target_vol_window')}",
        f"max_leverage={_format_meta_value(tv.get('max_leverage'))}",
    ]
    if tv.get("min_leverage") not in (None, ""):
        parts.append(f"min_leverage={_format_meta_value(tv.get('min_leverage'))}")
    deadband = _target_vol_deadband(tv)
    if deadband not in (None, ""):
        parts.append(f"deadband={_format_meta_value(deadband)}")
        parts.append(f"deadband_mode={_target_vol_deadband_mode(tv)}")
    if tv.get("gate") not in (None, ""):
        parts.append(f"gate={_format_meta_value(tv.get('gate'))}")
    return ", ".join(parts)


def _section_meta_detail(section: dict) -> str:
    if not isinstance(section, dict) or not section:
        return "enabled=False"
    keys = (
        "enabled",
        "family",
        "feature",
        "kind",
        "series",
        "window",
        "threshold",
        "score_threshold",
        "decay_threshold",
        "decay_ratio",
        "recovery_threshold",
        "recovery_ratio",
        "target_vol",
        "confirm_days",
        "scale",
        "derisk_scale",
        "min_scale",
    )
    parts = []
    for key in keys:
        if key in section:
            parts.append(f"{key}={_format_meta_value(section.get(key))}")
    return ", ".join(parts) if parts else str(section)

def render_params(live: bool = False) -> str:
    metas = load_strategy_metas()
    title = "## 实时参数" if live else "## 参数"
    lines = [title, ""]
    configs = {config.key: config for config in STRATEGIES}
    for _pair_key, pair_display, forward_key, reverse_key in PAIR_DEFS:
        pair_title = pair_display.replace(" 正反50/50", "")
        lines.extend([
            f"### {pair_title}",
            "",
            "| 参数 | 正向 | 反向 |",
            "|:-|:-|:-|",
        ])
        snapshots = []
        for key in (forward_key, reverse_key):
            config = configs[key]
            meta = metas[config.key]
            signal = meta.get("signal", {}) if isinstance(meta.get("signal", {}), dict) else {}
            tv = meta.get("target_vol", {}) if isinstance(meta.get("target_vol", {}), dict) else {}
            nav = meta.get("nav_defense", {}) if isinstance(meta.get("nav_defense", {}), dict) else {}
            amount = _amount_overlay_section(meta)
            volume_sections = _volume_overlay_sections(meta)
            volume_detail = " | ".join(
                f"{section.get('_label')}: {_section_meta_detail(section)}" for section in volume_sections
            ) if volume_sections else "enabled=False"
            vol = _vol_overlay_section(meta)
            scorehot = meta.get("score_overheat", {}) if isinstance(meta.get("score_overheat", {}), dict) else {}
            decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
            abs_day = _signal_abs_day(signal)
            snapshots.append({
                "signal": f"bias_ma={signal.get('bias_ma')}, mom_day={signal.get('mom_day')}, weight_end={signal.get('weight_end')}, score_threshold={signal.get('score_threshold')}, abs_mom_day={abs_day}, abs_threshold={signal.get('abs_threshold')}",
                "target-vol": _target_vol_detail(tv),
                "NAV-defense": _section_meta_detail(nav),
                "vol-overlay": _section_meta_detail(vol),
                "score-overheat": _section_meta_detail(scorehot),
                "momentum-decay": _section_meta_detail(decay),
                "amount-overlay": _section_meta_detail(amount),
                "volume-overlay": volume_detail,
            })
        for name in ("signal", "target-vol", "NAV-defense", "vol-overlay", "score-overheat", "momentum-decay", "amount-overlay", "volume-overlay"):
            lines.append(_md_row(name, snapshots[0][name], snapshots[1][name]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

def render_signal_history(query: str) -> str:
    curves, _metas, online = load_strategy_context(include_realtime=True)
    if not curves or not any(not curve.empty for curve in curves.values()):
        return (
            "## 信号历史不可用\n\n"
            f"- 在线重建失败: `{online.get('error', 'unknown')}`\n"
        )

    lines = ["## 信号历史", ""]
    if online.get("ok") and str(online.get("data_mode", "")).startswith("online_rebuild"):
        lines.append("- 数据来源: Poe 在线重建最近 5 个交易日；不读取本地正式 artifacts。")
        lines.append("")
    for config in STRATEGIES:
        curve = curves[config.key]
        if curve.empty:
            continue
        records = curve.tail(5)[["gross_exposure", "score"]] if set(["gross_exposure", "score"]).issubset(curve.columns) else curve.tail(5)
        lines.append(f"### {config.display_name}")
        if records.empty:
            lines.append("- 无记录")
        else:
            for idx, row in records.iterrows():
                date = idx.strftime("%Y-%m-%d")
                exp = pct(row.get("gross_exposure"), 1)
                score = num(row.get("score"), 3)
                lines.append(f"- {date}: exposure={exp}, score={score}")
    return "\n".join(lines).rstrip() + "\n"

def render_nav_chart(query: str, combo: bool = False) -> str:
    return "## NAV 曲线\n\n当前环境不再生成图表。"

def render_query(query: str) -> str:
    normalized = _normalize_query(query)
    compact = normalized.replace(" ", "")
    if "历史" in compact and "信号" in compact:
        return render_signal_history(normalized)
    if "参数" in compact and "实时" in compact:
        return render_params(live=True)
    if "参数" in compact:
        return render_params(live=False)
    if "组合表现" in compact:
        return render_performance(normalized, combo=True)
    if "表现" in compact:
        return render_performance(normalized, combo=False)
    if "信号" in compact:
        return render_signal(live=True)
    return render_signal(live=True)

def _write_query_response(msg, query: str) -> None:
    rendered = render_query(str(query))
    msg.write(rendered)



async def get_response(request):  # pragma: no cover - Poe runtime entrypoint
    query = getattr(request, "query", None) or getattr(request, "text", "")
    with poe.start_message() as msg:
        try:
            _write_query_response(msg, str(query))
        except Exception as exc:
            msg.write("## 查询失败\n\n")
            msg.write(f"`{exc}`\n")
        return msg



def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    query = " ".join(argv).strip()
    if not query:
        query_obj = getattr(poe, "query", None)
        query = getattr(query_obj, "text", "") if query_obj is not None else ""
    query = str(query).strip() or "信号"
    with poe.start_message() as msg:
        try:
            _write_query_response(msg, query)
        except Exception as exc:
            msg.write("## 查询失败\n\n")
            msg.write(f"`{exc}`\n")
    return 0


def run() -> int:
    query_obj = getattr(poe, "query", None)
    query = getattr(query_obj, "text", "") if query_obj is not None else ""
    query = str(query).strip() or "信号"
    with poe.start_message() as msg:
        try:
            _write_query_response(msg, query)
        except Exception as exc:
            msg.write("## 查询失败\n\n")
            msg.write(f"`{exc}`\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

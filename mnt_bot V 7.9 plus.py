# poe: name=Strategy-Signal-V78
# poe: privacy_shield=half
"""V7.9"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import io
import re
import json
import os
import sys
import atexit
import warnings
import xlsxwriter
import time
import threading
import types
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict
from zoneinfo import ZoneInfo
try:
    from fastapi_poe.types import SettingsResponse
except Exception:
    class SettingsResponse:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

if "poe" not in globals():
    try:
        import fastapi_poe as poe
    except Exception:
        class _LocalPoe:
            class BotError(Exception):
                pass

            query = types.SimpleNamespace(text=" ".join(sys.argv[1:]), attachments=[])
            default_chat = []

            @staticmethod
            def update_settings(settings):
                return None

            @staticmethod
            def start_message():
                return _CompatStartMessage()

            @staticmethod
            def call(*_args, **_kwargs):
                raise _LocalPoe.BotError(
                    "Local compatibility mode does not support poe.call; run LLM parsing paths in Poe."
                )

        poe = _LocalPoe()


class _CompatStartMessage:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def write(self, value):
        data = str(value).encode("utf-8", errors="replace")
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()

    def attach_file(self, **kwargs):
        name = kwargs.get("name", "attachment")
        data = f"\n[attachment: {name}]\n".encode("utf-8", errors="replace")
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


def _install_poe_native_compat(poe_module):
    """Lightweight CLI shim.

    Poe native runtime remains the full production environment. Local/fastapi-poe
    execution only supports paths that do not require poe.call LLM parsing.
    """
    required = ("update_settings", "start_message", "query", "default_chat", "call")
    if all(hasattr(poe_module, attr) for attr in required):
        return poe_module

    class _PoeNativeCompatProxy:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self._settings = None
            self.query = getattr(
                wrapped,
                "query",
                types.SimpleNamespace(text=" ".join(sys.argv[1:]), attachments=[]),
            )
            self.default_chat = getattr(wrapped, "default_chat", [])

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

        def call(self, *_args, **_kwargs):
            call = getattr(self._wrapped, "call", None)
            if call is not None:
                return call(*_args, **_kwargs)
            bot_error = getattr(self._wrapped, "BotError", RuntimeError)
            raise bot_error("本地兼容模式不支持 poe.call，请在 Poe 原生环境运行需要 LLM 解析的指令。")

    return _PoeNativeCompatProxy(poe_module)


poe = _install_poe_native_compat(poe)
DEBUG_MODE = os.getenv("STRATEGY_DEBUG", "0") == "1"


def _debug_write(msg, text):
    if DEBUG_MODE and msg is not None:
        msg.write(text)

# ─────────────────────────────────────────────
# A股 Sub-A 双动量策略
# ─────────────────────────────────────────────
CN_COMMISSION = 0.001
CN_DK_COMMISSION = 0.0005
CN_RF_ANNUAL = 0.03
CN_TRADING_DAYS = 244
CN_RF_DAILY = (1 + CN_RF_ANNUAL) ** (1 / CN_TRADING_DAYS) - 1

# v6.1: 乖离动量 + R²过滤 + 国债指数 (替代v5.4双动量+MA拐头+冷却期)
CN_BIAS_N = 60           # 均线周期 (price / MA60)
CN_MOM_DAY = 20          # 斜率拟合窗口
CN_R2_WINDOW = 20        # R²滚动窗口
CN_R2_THRESHOLD = 0.15   # V7.7 Sub-A: linear_recent_3x + 20d abs momentum gate
CN_BIAS_MOM_WEIGHT_END = 3.0
CN_ABS_MOM_DAY = 20
CN_ABS_MOM_THRESHOLD = 0.02
CN_MIN_HISTORY_ROWS = CN_BIAS_N + CN_MOM_DAY + 10
CN_ENTRY_WAIT_DAYS = None   # 策略A剩余仓位只等首个日线阴线补齐，不做超时强制补仓
CN_SWITCH_BUFFER = 1.00  # V7.7 Sub-A: no switch buffer
CN_BOND_CODE = "1.H11077"  # 上证10年期国债指数（全收益，避险资产）
CN_BOND_NAME = "10Y国债"
# v6.1: 波动率缩放参数
CN_TARGET_VOL = 0.30          # 目标年化波动率；V7.7 默认
CN_VOL_WINDOW = 80            # 波动率计算窗口
CN_MAX_LEV = 1.5              # 最大杠杆
CN_MIN_LEV = 0.1              # 最小杠杆
CN_SCALE_THRESHOLD = 0.00     # scale变动阈值；0=连续更新
CN_ENTRY_INITIAL_FRACTION = 1.0

# Research-only single-index gate prototypes from the standalone A-share long-only workspace.
# V7.7 Sub-A production logic must not require these sleeves to be active before holding.
CN_SA_SINGLE_GATE_ENABLED = False
CN_SA_SINGLE_GATE_EXECUTION_SHIFT = -1
CN_SA_SINGLE_GATE_CONFIGS = {
    "0.399006": {
        "name": "cyb_long_momentum_v1_2",
        "mode": "cyb_v1_2",
        "bias_ma": 50,
        "mom_day": 27,
        "weight_end": 1.0,
        "abs_mom_day": 20,
        "score_threshold": 0.0,
        "abs_threshold": -0.025,
        "nav_decay_threshold": 0.0875,
        "nav_decay_scale": 0.25,
        "hot_score_threshold": 120.0,
        "hot_scale": 0.0,
        "hot_volume_ma": 60,
        "hot_volume_ratio_threshold": 1.75,
        "cost_rate": 0.001,
    },
    "1.000016": {
        "name": "sse50_long_momentum_v1_0",
        "mode": "sse50_v1_0",
        "bias_ma": 110,
        "mom_day": 60,
        "weight_end": 2.0,
        "r2_threshold": 0.20,
        "abs_mom_day": 50,
        "score_threshold": 0.0,
        "abs_threshold": -0.13,
        "volume_ma": 120,
        "volume_ratio_threshold": 0.80,
        "target_vol": 0.15,
        "target_vol_window": 120,
        "max_leverage": 1.5,
        "nav_decay_threshold": 0.10,
        "nav_decay_scale": 0.75,
        "cost_rate": 0.001,
    },
    "1.000852": {
        "name": "zz1000_long_momentum_v1_2",
        "mode": "zz1000_v1_2",
        "bias_ma": 45,
        "mom_day": 18,
        "weight_end": 2.5,
        "score_threshold": 0.0,
        "abs_mom_day": 20,
        "abs_reentry_threshold": 0.03,
        "abs_exit_threshold": 0.0,
        "nav_decay_threshold": 0.07,
        "nav_decay_scale": 0.75,
        "score_hot_threshold": 150.0,
        "score_hot_scale": 0.0,
        "volume_ma": 160,
        "volume_ratio_threshold": 1.00,
        "volume_exit_threshold": 0.90,
        "volume_confirm_days": 1,
        "cost_rate": 0.001,
    },
    "1.000905": {
        "name": "zz500_long_momentum_v1_2",
        "mode": "zz500_v1_2",
        "bias_ma": 110,
        "mom_day": 24,
        "weight_end": 2.0,
        "score_threshold": 2.0,
        "score_exit_threshold": 0.0,
        "abs_mom_day": 20,
        "abs_reentry_threshold": -0.04,
        "abs_exit_threshold": -0.06,
        "nav_decay_threshold": 0.06,
        "nav_decay_scale": 0.5,
        "hot_score_threshold": 90.0,
        "hot_scale": 0.0,
        "high_vol_window": 40,
        "high_vol_threshold": 0.45,
        "high_vol_scale": 0.5,
        "volume_ma": 120,
        "volume_ratio_threshold": 0.75,
        "volume_exit_threshold": 0.75,
        "volume_confirm_days": 1,
        "cost_rate": 0.001,
    },
}

# 成交量情绪监控（仅展示，不参与交易决策）
CN_VOL_EMOTION_MA   = 10       # 均量周期
CN_VOL_EMOTION_BEAR = 8        # 连续缩量 N 天 → 悲观
CN_VOL_EMOTION_BULL = 3        # 连续放量 N 天 → 乐观
CN_VOL_MONITOR_SECID = "1.000001"  # 上证指数

# Sub-A 成交额风控规则（正式参与 Sub-A 仓位计算）
CN_SA_VOLUME_OVERLAY_ENABLED = True
CN_SA_VOLUME_RULE_MODE = "or"
CN_SA_VOLUME_SCALE = 0.0
CN_SA_VOLUME_HISTORY_BEG = "20000101"
CN_SA_VOLUME_ZZ2000_SECID = "2.932000"
CN_SA_VOLUME_ZZ2000_ETF_PROXY_SECIDS = (
    ("1.563300", "中证2000ETF"),
    ("0.159531", "中证2000ETF"),
    ("1.562660", "中证2000ETF"),
    ("0.159532", "中证2000ETF"),
    ("0.159533", "中证2000ETF"),
    ("0.159535", "中证2000ETF"),
    ("0.159536", "中证2000ETF"),
)
CN_SA_VOLUME_ZZ2000_MA = 20
CN_SA_VOLUME_ZZ2000_DAYS = 3
CN_SA_VOLUME_CYB_SECID = "0.399006"
CN_SA_VOLUME_CYB_MA = 20
CN_SA_VOLUME_CYB_DAYS = 4
CN_SA_VOLUME_CLEAR_RATIO_ENABLED = False
CN_SA_VOLUME_CLEAR_RATIO_NUMERATOR_SECID = CN_SA_VOLUME_ZZ2000_SECID
CN_SA_VOLUME_CLEAR_RATIO_NUMERATOR_LABEL = "ZZ2000"
CN_SA_VOLUME_CLEAR_RATIO_DENOMINATOR_SECID = "1.000016"
CN_SA_VOLUME_CLEAR_RATIO_DENOMINATOR_LABEL = "SZ50"
CN_SA_VOLUME_CLEAR_RATIO_MA = 30
CN_SA_VOLUME_CLEAR_RATIO_DAYS = 15
CN_SA_VOLUME_CLEAR_RATIO_SCALE = 0.0
CN_SA_VOLUME_RULE_NAME = (
    f"Sub-A amount OR: ZZ2000<MA{CN_SA_VOLUME_ZZ2000_MA}x{CN_SA_VOLUME_ZZ2000_DAYS} "
    f"or CYB<MA{CN_SA_VOLUME_CYB_MA}x{CN_SA_VOLUME_CYB_DAYS}; scale={CN_SA_VOLUME_SCALE:.2f}"
)
CN_CSI_AMOUNT_INDEX_CODES = {
    "2.932000": "932000",  # 中证2000
    "1.000016": "000016",  # 上证50
    "1.000300": "000300",  # 沪深300
    "1.000852": "000852",  # 中证1000
    "1.000905": "000905",  # 中证500
}

# DK和微盘成交额规则只做风险警示，不参与本脚本仓位/回测降仓。
CN_DK_VOLUME_POLICY = "warning_only"
CN_DK_VOLUME_YELLOW_SECID = "1.000905"
CN_DK_VOLUME_YELLOW_LABEL = "中证500"
CN_DK_VOLUME_YELLOW_MA = 28
CN_DK_VOLUME_YELLOW_DAYS = 5

MICROCAP_VOLUME_POLICY = "warning_only_reference"
MICROCAP_BROAD_VOLUME_RULE_MODE = "and"
MICROCAP_BROAD_VOLUME_ZZ2000_SECID = "2.932000"
MICROCAP_BROAD_VOLUME_ZZ2000_MA = 35
MICROCAP_BROAD_VOLUME_ZZ2000_DAYS = 18
MICROCAP_BROAD_VOLUME_CYB_SECID = "0.399006"
MICROCAP_BROAD_VOLUME_CYB_MA = 35
MICROCAP_BROAD_VOLUME_CYB_DAYS = 18
MICROCAP_BROAD_VOLUME_REFERENCE_SCALE = 0.25
MICROCAP_DIRECT_VOLUME_CODE = "883418.TI"
MICROCAP_DIRECT_VOLUME_MA = 53
MICROCAP_DIRECT_VOLUME_DAYS = 13
MICROCAP_DIRECT_VOLUME_VENDOR = "Tonghuashun 883418.TI"
MICROCAP_DIRECT_VOLUME_CSV_ENV = "MICROCAP_DIRECT_VOLUME_CSV"
MICROCAP_DIRECT_VOLUME_THS_SYMBOL = "48_883418"
MICROCAP_DIRECT_VOLUME_THS_URL = (
    f"http://d.10jqka.com.cn/v6/line/{MICROCAP_DIRECT_VOLUME_THS_SYMBOL}/01/all.js"
)

# 防接刀监控（仅展示，不参与交易决策）
CN_KNIFE_WINDOW = 3        # 观察窗口（交易日）
CN_KNIFE_THRESHOLD = -0.05 # 3日跌幅阈值（-5%）

CN_EQUITY_CODES = ["1.930955", "0.399006", "1.000016", "1.000852", "1.000905"]
CN_ALL_CODES = CN_EQUITY_CODES + [CN_BOND_CODE]
CN_STOCK_CODES = CN_EQUITY_CODES  # Sub-A用价格指数；债券避险仍用全收益指数
CN_NAMES = {
    "1.930955": "中证红利低波100",
    "0.399006": "创业板",
    "1.000016": "上证50",
    "1.000852": "中证1000",
    "1.000905": "中证500",
    "1.H00300": "沪深300",   # 仅用于显示/映射
    "1.H11077": "10Y国债",
    "cash": "Cash",
}

# A股 Sub-A 股票资产使用价格指数；债券避险资产继续使用全收益指数
CN_ZZHL_INDEX_SECID = "1.930955"    # 中证红利低波100(价格)
CN_CSINDEX_PRICE_INDEX_CODES = {
    "1.930955": "930955",
}
CN_VENDOR_SECID_ALIASES = {
    "1.930955": ["2.930955", "1.930955"],
}
CN_ZZHL_PRE_INDEX_CODE = "H00922"   # H20955上市前用H00922(中证红利)扩展历史
# 中证官网候选代码回退: 主代码异常时仍坚持走官网，不直接切到第三方源
CN_CSINDEX_CANDIDATES = {
    "H20955": ["H20955"],
}
# (国债已改用H11077全收益指数，无需ETF拼接)

# 代理全收益指数，使用价格指数用于从第三方(EastMoney/Sina)获取数据，规避中证官网实时失效问题
CN_H_PROXY_SECIDS = {
    # H20955 must use CSIndex official data/cache only.
    "1.H00016": "1.000016", # 上证50全收益 -> 上证50(价格)
    "1.H00852": "1.000852", # 中证1000全收益 -> 中证1000(价格)
    "1.H00905": "1.000905", # 中证500全收益 -> 中证500(价格)
    "1.H11077": "1.000012", # 上证10年期国债全收益 -> 上证国债指数
}

# ─────────────────────────────────────────────
# A股 Sub-A-DK 多空策略
# ─────────────────────────────────────────────
# DK策略使用价格指数（实际用股指期货/ETF期权交易，盈亏跟踪价格指数而非全收益指数）
CN_DK_ZZ1000_CODE = "000852"
CN_DK_SZ50_CODE = "000016"
CN_DK_HS300_CODE = "000300"
CN_DK_ZZ500_CODE = "000905"
CN_DK_CYB_CODE = "399006"
CN_DK_ZZ1000_SECID = "1.000852"
CN_DK_SZ50_SECID = "1.000016"
CN_DK_HS300_SECID = "1.000300"
CN_DK_ZZ500_SECID = "1.000905"
CN_DK_CYB_SECID = "0.399006"
# v6.1: 多配对Top-1 + 乖离动量 + VolScaling (替代v5.4单配对+冷却期)
CN_DK_COLS = ["DK_ZZ1000", "DK_SZ50", "DK_HS300", "DK_ZZ500", "DK_CYB"]
CN_DK_PUBLICATION_DATES = {
    "DK_SZ50": pd.Timestamp("2004-01-02"),
    "DK_HS300": pd.Timestamp("2005-04-08"),
    "DK_ZZ500": pd.Timestamp("2007-01-15"),
    "DK_CYB": pd.Timestamp("2010-06-01"),
    "DK_ZZ1000": pd.Timestamp("2014-10-17"),
}
CN_DK_NAMES = {
    "DK_ZZ1000": "中证1000", "DK_SZ50": "上证50",
    "DK_HS300": "沪深300", "DK_ZZ500": "中证500", "DK_CYB": "创业板",
}
CN_DK_BIAS_N = 60            # 乖离动量均线周期
CN_DK_MOM_DAY = 20           # 斜率拟合窗口
CN_DK_VOL_SCALE_ENABLED = True
CN_DK_TARGET_VOL = 0.14
CN_DK_VOL_WINDOW = 40
CN_DK_MAX_LEV = 1.5
CN_DK_MIN_LEV = 0.1
CN_DK_TRADING_DAYS = CN_TRADING_DAYS
CN_DK_SCALE_THRESHOLD = 0.25     # V7.7 ADK scale变动阈值
CN_DK_TOP_N = 1              # 每天选Top-1配对

ADK_OFFICIAL_PAIR_ORDER = (
    "SZ50/ZZ500",
    "SZ50/ZZ1000",
    "SZ50/CYB",
    "HS300/ZZ500",
    "HS300/ZZ1000",
    "HS300/CYB",
    "ZZ500/CYB",
    "ZZ1000/CYB",
)
ADK_OFFICIAL_PAIRS = set(ADK_OFFICIAL_PAIR_ORDER)
ADK_EXCLUDED_PAIR_ORDER = (
    "SZ50/HS300",
    "ZZ500/ZZ1000",
)
ADK_EXCLUDED_PAIRS = set(ADK_EXCLUDED_PAIR_ORDER)
ADK_PRIMARY_PROFIT_PAIR_ORDER = ADK_OFFICIAL_PAIR_ORDER
ADK_PRIMARY_PROFIT_PAIRS = ADK_OFFICIAL_PAIRS
ADK_WEAK_PAIR_ORDER = ()
ADK_WEAK_PAIRS = set(ADK_WEAK_PAIR_ORDER)
ADK_INVALID_PAIR_ORDER = ADK_EXCLUDED_PAIR_ORDER
ADK_INVALID_PAIRS = set(ADK_INVALID_PAIR_ORDER)
CN_DK_RISK_GATE_ENABLED = False
CN_DK_RISK_GATE_ENTER = 0.15
CN_DK_RISK_GATE_EXIT = 0.08
CN_DK_RISK_GATE_DEFENSE_SCALE = 0.5
CN_DK_RISK_GATE_COOLDOWN_DAYS = 0
CN_DK_PAIR_SCORE_DECAY_ENABLED = False
CN_DK_PAIR_SCORE_DECAY_RATIO = 0.40
CN_DK_PAIR_SCORE_RECOVERY_RATIO = 0.70
CN_DK_PAIR_SCORE_DERISK_SCALE = 0.0
CN_DK_PAIR_SCORE_DECAY_WARMUP_DAYS = 5
CN_DK_R2_QUALITY_ENABLED = True
CN_DK_R2_QUALITY_THRESHOLD = 0.05
CN_DK_SAME_SIDE_OVERHEAT_ENABLED = True
CN_DK_SAME_SIDE_OVERHEAT_ENTER = 0.22
CN_DK_SAME_SIDE_OVERHEAT_EXIT = 0.18
CN_DK_SAME_SIDE_OVERHEAT_DERISK_SCALE = 0.0
CN_DK_DD_WARNING_ORIGINAL_THRESHOLD = 0.07
CN_DK_DD_WARNING_ORIGINAL_COOLDOWN_DAYS = 3


def _dk_score_decay_status_text():
    if CN_DK_PAIR_SCORE_DECAY_ENABLED:
        return (
            f"Score衰减/恢复 {CN_DK_PAIR_SCORE_DECAY_RATIO:.0%}/"
            f"{CN_DK_PAIR_SCORE_RECOVERY_RATIO:.0%}"
        )
    return "Score衰减关闭"

# V7.7 ADK official pool: 5 indices, 8 tradable pairs, all read from cn_dk_close price indices.
CN_DK_INDICES = {
    'SZ50':   {'col': 'DK_SZ50',   'src': 'dk'},
    'HS300':  {'col': 'DK_HS300',  'src': 'dk'},
    'ZZ500':  {'col': 'DK_ZZ500',  'src': 'dk'},
    'ZZ1000': {'col': 'DK_ZZ1000', 'src': 'dk'},
    'CYB':    {'col': 'DK_CYB',    'src': 'dk'},
}
def _dk_is_official_pair(pair):
    return str(pair) in ADK_OFFICIAL_PAIRS

CN_DK_INDEX_NAMES = {
    'SZ50': '上证50', 'HS300': '沪深300', 'ZZ500': '中证500',
    'ZZ1000': '中证1000', 'CYB': '创业板',
}

# ─────────────────────────────────────────────
# 美股 Sub-B 轮动策略
# ─────────────────────────────────────────────
CN_MARKET_HOLIDAYS = {
    "2026-01-01", "2026-01-02", "2026-01-03",
    "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19", "2026-06-20", "2026-06-21",
    "2026-09-25", "2026-09-26", "2026-09-27",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07",
}
CN_MARKET_HOLIDAY_YEARS = {2026}
CN_MARKET_CALENDAR_COVERAGE_NOTE = (
    f"A股交易日历当前维护年份: {min(CN_MARKET_HOLIDAY_YEARS)}-{max(CN_MARKET_HOLIDAY_YEARS)}；"
    "2027年交易所日历公布后需更新。"
)

US_ROT_COMMISSION = 0.001
US_TRADING_DAYS = 252
US_ROT_BASE_ASSETS = {
    "QQQM": {"proxy": "QQQ",     "label": "Nasdaq 100"},
    "EMXC": {"proxy": "EMXC",    "label": "新兴市场(除中国)"},
    "GLDM": {"proxy": "GLD",     "label": "黄金"},
    "PDBC": {"proxy": "DBC",     "label": "大宗商品"},
    "IBIT": {"proxy": "BTC-USD", "label": "比特币"},
}
US_ROT_MACRO_ASSETS = {
    "DBMF": {"proxy": "DBMF",    "label": "CTA/Managed Futures"},
    "KMLM": {"proxy": "KMLM",    "label": "CTA/KFA Managed Futures"},
}
US_ROT_ASSETS = {**US_ROT_BASE_ASSETS, **US_ROT_MACRO_ASSETS}
US_ROT_BASE_POOL = [cfg["proxy"] for cfg in US_ROT_BASE_ASSETS.values()]
US_ROT_MACRO_POOL = [cfg["proxy"] for cfg in US_ROT_MACRO_ASSETS.values()]
US_ROT_POOL = US_ROT_BASE_POOL + US_ROT_MACRO_POOL
SUBB_INFLATION_GATE_TICKERS = ("DBC", "TLT", "UUP")
SUBB_REQUIRED_PRICE_TICKERS = tuple(dict.fromkeys(
    US_ROT_POOL + ["BIL", "SPY"] + list(SUBB_INFLATION_GATE_TICKERS)
))
SUBB_OPTIONAL_MACRO_TICKERS = tuple()
US_ROT_FUTURES = {"QQQM", "GLDM"}
_ROT_PROXY_TO_LIVE = {cfg["proxy"]: live for live, cfg in US_ROT_ASSETS.items()}
# 2026-03-27 本轮优化落地:
# V7.9 scan 2026-07-02: Sub-B uses 30% target vol + 1.5x max leverage.
# scale>1: only live assets in US_ROT_FUTURES are levered; proxy inputs are mapped before checking.
# V6.8.1: leveraged assets are QQQM / GLDM only.
US_ROT_TARGET_VOL = 0.30
US_ROT_MAX_LEV = 1.5
US_ROT_VOL_WINDOW = 40
US_ROT_LB = 160
US_ROT_LBS = (160, 260, 390)
US_ROT_LBS_DEFAULT = (160, 260, 390)
US_ROT_WINDOW_WEIGHTS = {160: 0.60, 260: 0.30, 390: 0.10}
US_ROT_WINDOW_WEIGHT_LABEL = "160/260/390=60%/30%/10%"
US_ROT_LB = US_ROT_LBS[1]  # compatibility alias for legacy single-window references
US_ROT_MAX_LB = max(US_ROT_LBS)
US_ROT_VOL_LB = 20
US_ROT_MIN_TURNOVER = 0.0
US_ROT_ABS_THRESHOLD = 0.00
US_ROT_TOP_N = 2

# 调仓阈值（参与交易决策）
US_ROT_REBALANCE_THRESHOLD = 1.00  # V7.9 Sub-B收益型默认: 不额外加挑战者保护，Top2轮动更及时

# V7.9 Sub-B V77 sleeve: final 25% official + 25% EMA before Bias/LogVol.
# The EMA leg ranks the same full pool, including DBMF/KMLM.
# Its target-vol scale uses 6-month EWMA realized volatility; the official leg remains rolling 40d.
SUBB_V75_OFFICIAL_WEIGHT = 0.50
SUBB_V75_EMA_WEIGHT = 0.50
SUBB_V75_EMA_HALF_LIFE = 100
SUBB_V75_EMA_ABS_THRESHOLD = 0.16
SUBB_V75_EMA_VOL_MODE = "ewma6m_1vol"
SUBB_V75_EMA_VOL_HALFLIFE_DAYS = int(round(US_TRADING_DAYS * 6 / 12))
SUBB_BLEND_VOL_NOTE = (
    "混合后不再做组合级二次波动率归一；最终波动由官方腿与EMA腿各自VolScale及50/50日收益混合共同决定。"
)


def _v78_subb_inflation_participation_note():
    return (
        "V7.9池: QQQ/EMXC/GLD/DBC/BTC-USD/DBMF/KMLM；"
        "官方腿仅在通胀开关ON时纳入DBMF/KMLM；"
        "EMA/Bias/LogVol腿始终US_ROT_POOL全池排名；UUP仅作观察指标。"
    )


def _subb_window_lbs_for_display():
    try:
        values = list(US_ROT_LBS)
        values = [int(v) for v in values[:3]]
        if len(values) == 3:
            return tuple(values)
    except Exception:
        pass
    return US_ROT_LBS_DEFAULT


def _subb_window_label_for_display(separator="/"):
    return separator.join(str(lb) for lb in _subb_window_lbs_for_display())


def _v78_subb_default_rule_text(include_ema_vol_mode=True):
    ema_mode = (
        f", {SUBB_V75_EMA_VOL_MODE}"
        if include_ema_vol_mode
        else ""
    )
    return (
        f"V7.9 Sub-B四腿默认Top{US_ROT_TOP_N}：官方腿25%({_subb_window_label_for_display('/')}, {US_ROT_WINDOW_WEIGHT_LABEL})"
        f" + EMA腿25%(hl{SUBB_V75_EMA_HALF_LIFE}/{SUBB_V75_EMA_ABS_THRESHOLD:.0%}{ema_mode})"
        " + Bias腿25% + LogVol腿25%；"
        f"{_v78_subb_inflation_participation_note()}"
    )


def _v78_subb_inflation_status_text(pressure_on):
    official = (
        "🟢 官方腿宏观池开启：DBMF/KMLM参与官方腿候选"
        if bool(pressure_on)
        else "🔴 官方腿宏观池关闭：DBMF/KMLM不参与官方腿候选"
    )
    other = "🟢 EMA/Bias/LogVol全池开启：DBMF/KMLM始终参与这三条腿排名；UUP仅作观察指标"
    return f"{official}\n{other}"

# V7.9: keep the V7.7 query surface, but blend selected from-scratch sleeves
# with the original 7.7 sleeves.
V78_SUBA_V77_WEIGHT = 0.50
V78_SUBA_NEW_TV10_WEIGHT = 0.50
V78_ADK_V77_WEIGHT = 0.50
V78_ADK_NEW_PRIMARY_WEIGHT = 0.50
V78_SUBB_V77_WEIGHT = 0.50
V78_SUBB_NEW_BIAS_WEIGHT = 0.25
V78_SUBB_NEW_LOGVOL_WEIGHT = 0.25
V78_LABEL = "V7.9"
V78_SUBA_NEW_LABEL = "New A TV1.0"
V78_ADK_NEW_LABEL = "New ADK all10 score-hot"
V78_SUBB_BIAS_LABEL = "New B bias-level + SPY volume"
V78_SUBB_LOGVOL_LABEL = "New B log-weighted vol-hot + SPY volume"
V78_SUBA_EXECUTION_MODE = "component_net"
V78_ADK_EXECUTION_MODE = "component_net_with_net_exposure_display"
V78_SUBB_EXECUTION_MODE = "component_net_with_volreg_and_dbc_profit_guard"
V78_SUBB_SPY_VOLUME_FAIL_MODE = "fail_closed"  # warn_open / fail_closed / raise
V78_ADK_NEW_SCORE_HOT_ENTER = 80.0
V78_ADK_NEW_SCORE_HOT_EXIT = 20.0
V78_ADK_NEW_SCORE_HOT_SCALE = 0.0
V78_SUBA_NEW_MA = 40
V78_SUBA_NEW_MOM_DAY = 20
V78_SUBA_NEW_WEIGHT_END = 3.0
V78_SUBA_NEW_SCORE_THRESHOLD = 10.0 / 10000.0
V78_SUBA_NEW_ABS_DAY = 20
V78_SUBA_NEW_ABS_THRESHOLD = 0.02
V78_SUBA_NEW_TARGET_VOL = 0.30
V78_SUBA_NEW_VOL_WINDOW = 80
V78_SUBA_NEW_MAX_LEV = 1.0

US_ROT_BTC_TICKER = "BTC-USD"
US_ROT_BTC_START = pd.Timestamp("2022-01-01")
US_ROT_BTC_MAX_W = 0.30
US_ROT_EMXC_BT_START = pd.Timestamp("2017-08-01")
US_ROT_EMXC_BT_PROXY = "EEM"

# VolReg 风控: SPY短期/长期波动率比过热时，次日削指定资产暴露，差额进BIL。
US_ROT_VOLREG_ENABLED = True
US_ROT_VOLREG_SHORT_W = 10      # 短期波动率窗口(交易日)
US_ROT_VOLREG_LONG_W = 250      # 长期波动率窗口(交易日)
US_ROT_VOLREG_THRESHOLD = 1.8   # 短/长波动率比进入阈值
US_ROT_VOLREG_EXIT_THRESHOLD = 1.4  # 短/长波动率比退出阈值
US_ROT_VOLREG_DEFENSE_SCALE = 0.00
US_ROT_VOLREG_SCALE_ASSETS = ("QQQ", "EMXC")
SUBB_DBC_PROFIT_GUARD_ENABLED = True
SUBB_DBC_PROFIT_GUARD_ASSET = "DBC"
SUBB_DBC_PROFIT_GUARD_CASH_ASSET = "BIL"
SUBB_DBC_PROFIT_GUARD_RETAIN_L1 = 0.50
SUBB_DBC_PROFIT_GUARD_RETAIN_L2 = 0.25
SUBB_DBC_PROFIT_GUARD_SCALE_L1 = 0.67
SUBB_DBC_PROFIT_GUARD_SCALE_L2 = 0.00
SUBB_DBC_PROFIT_GUARD_MIN_PEAK_PROFIT = 1e-6
US_ROT_VOLREG_BACKTEST_NOTE = (
    "VolReg回测口径: T日收盘信号 -> T+1调整后开盘执行；"
    f"仅将{'/'.join(US_ROT_VOLREG_SCALE_ASSETS)}目标暴露清零，削减权重转BIL；黄金、CTA、BTC不直接降档。"
)

# ─────────────────────────────────────────────
# 美股 Sub-C 生产组合
# ─────────────────────────────────────────────
PROD_USE_TIMING = False
PROD_ABS_MOM_LB = 6
PROD_SMA_WINDOW = 12
PROD_SMA_BAND = 0.03
PROD_BLEND_A = 0.5
PROD_COMMISSION = 0.001
PROD_REBAL_MONTH = 12
PROD_CASH = "BIL"
PROD_PORTFOLIO = {
    "VTI":   {"w": 0.30, "label": "US Total Market",    "proxy": "VTI",     "cls": "equity"},
    "QQQM":  {"w": 0.10, "label": "US Nasdaq 100",      "proxy": "QQQ",     "cls": "equity"},
    "VEA":   {"w": 0.20, "label": "Intl Developed",     "proxy": "VEA",     "cls": "equity"},
    "VGIT":  {"w": 0.15, "label": "US Interm Treasury",  "proxy": "VGIT",    "cls": "bond"},
    "DBMF":  {"w": 0.05, "label": "Managed Futures",    "proxy": "DBMF",    "cls": "alt"},
    "GLDM":  {"w": 0.15, "label": "Gold",               "proxy": "GLD",     "cls": "commodity"},
    "IBIT":  {"w": 0.05, "label": "Bitcoin",            "proxy": "BTC-USD", "cls": "crypto"},
}

BTC_BT_START = pd.Timestamp("2022-01-01")
DBMF_BT_START = pd.Timestamp("2019-06-01")

# Sub-C 目标波动率缩放 (Vol-Scaling)
PROD_VS_ENABLED = True           # 是否启用
PROD_VS_TARGET_VOL = 0.15        # 目标年化波动率
PROD_VS_VOL_WINDOW = 15          # 已实现波动率回看窗口(交易日)
PROD_VS_MAX_LEV = 1.5            # 最大杠杆倍数
PROD_VS_MIN_LEV = 0.5            # 最小仓位比例
PROD_VS_THRESHOLD = 0.10         # scale变动阈值 (Δscale ≥ 10% 才调整)
PROD_VS_SPREAD_BPS = 100         # 融资spread (bps over rf, IBKR Portfolio Margin)
PROD_VS_REBAL_COST_BPS = 6       # ETF bid-ask 双边交易成本 (bps)

# ─────────────────────────────────────────────
# 派生计算（自动从上方配置生成）
# ─────────────────────────────────────────────

# PROD_PORTFOLIO_BT: 排除 IBIT 后重新归一化权重
PROD_PORTFOLIO_BT = {}
_bt_remaining = sum(c["w"] for _n, c in PROD_PORTFOLIO.items() if _n != "IBIT")
for _n, _c in PROD_PORTFOLIO.items():
    if _n == "IBIT":
        continue
    PROD_PORTFOLIO_BT[_n] = {**_c, "w": _c["w"] / _bt_remaining}

# PROD_PORTFOLIO_PRE_DBMF: 排除 IBIT+DBMF，DBMF权重归入VGIT
PROD_PORTFOLIO_PRE_DBMF = {}
_dbmf_w = PROD_PORTFOLIO["DBMF"]["w"]
_pre_dbmf_rest = sum(c["w"] for _n, c in PROD_PORTFOLIO.items() if _n not in ("IBIT", "DBMF"))
for _n, _c in PROD_PORTFOLIO.items():
    if _n in ("IBIT", "DBMF"):
        continue
    _w = _c["w"] + (_dbmf_w if _n == "VGIT" else 0)
    PROD_PORTFOLIO_PRE_DBMF[_n] = {**_c, "w": _w / (_pre_dbmf_rest + _dbmf_w)}

# 全部美股Ticker合集
US_ALL_TICKERS = sorted(set(
    list(SUBB_REQUIRED_PRICE_TICKERS) + [US_ROT_EMXC_BT_PROXY] +  # SPY/TLT: VolReg/通胀门控仍需要
    [c["proxy"] for c in PROD_PORTFOLIO.values()] +
    list(US_ROT_ASSETS.keys()) +    # 实盘ETF: QQQM, GLDM, IBIT等 (仓位调整需要实际价格)
    list(PROD_PORTFOLIO.keys())     # 实盘ETF: VTI, QQQM, GLDM等
))

# ─────────────────────────────────────────────
# 组合权重
# ─────────────────────────────────────────────
ACTIVE_COMBINED_WEIGHTS = {
    "Sub-A": 0.15,
    "Sub-A-DK": 0.15,
    "Microcap": 0.10,
    "Sub-D": 0.20,  # Sub-D v1.1 six-ETF sleeve is tracked by its independent script.
    "Sub-B": 0.40,
    "Sub-C": 0.00,  # Legacy Sub-C engine remains available only for old standalone queries.
}
ROLLBACK_COMBINED_WEIGHTS = {
    "Sub-A": 0.10,
    "Sub-A-DK": 0.15,
    "Microcap": 0.15,
    "Sub-D": 0.20,  # Sub-D v1.1 six-ETF sleeve is tracked by its independent script.
    "Sub-B": 0.40,
    "Sub-C": 0.00,  # Legacy Sub-C engine remains available only for old standalone queries.
}
COMBINED_WEIGHTS = ACTIVE_COMBINED_WEIGHTS
COMBINED_DISPLAY_ORDER = ["Sub-A", "Sub-A-DK", "Microcap", "Sub-D", "Sub-B"]
PERFORMANCE_COMBO_ORDER = ["Sub-A", "Sub-A-DK", "Sub-B"]
PERFORMANCE_COLUMNS = PERFORMANCE_COMBO_ORDER + ["Combined"]
PERFORMANCE_STANDARD_WINDOWS = (
    ("Full", None),
    ("10Y", pd.DateOffset(years=10)),
    ("5Y", pd.DateOffset(years=5)),
    ("3Y", pd.DateOffset(years=3)),
    ("1Y", pd.DateOffset(years=1)),
)
PERFORMANCE_STANDARD_MIN_DAILY_ROWS = 20


def _combined_weight_label():
    return "/".join(
        str(int(round(COMBINED_WEIGHTS[name] * 100)))
        for name in COMBINED_DISPLAY_ORDER
        if COMBINED_WEIGHTS.get(name, 0) > 0
    )


def _rollback_weight_label():
    return "/".join(
        str(int(round(ROLLBACK_COMBINED_WEIGHTS[name] * 100)))
        for name in COMBINED_DISPLAY_ORDER
        if ROLLBACK_COMBINED_WEIGHTS.get(name, 0) > 0
    )


def _performance_combo_weights():
    total = sum(COMBINED_WEIGHTS[name] for name in PERFORMANCE_COMBO_ORDER)
    return {name: COMBINED_WEIGHTS[name] / total for name in PERFORMANCE_COMBO_ORDER}


def _performance_combo_weight_label():
    return "/".join(
        str(int(round(COMBINED_WEIGHTS[name] * 100)))
        for name in PERFORMANCE_COMBO_ORDER
    ) + "归一(不含微盘/Sub-D)"


PORTFOLIO_ADVISORY_SCENARIO = "advisory_dd_3_10_month_end"
PORTFOLIO_SUBA_ADVISORY_SCENARIO = "advisory_suba_dd_5_8_weekly"
PORTFOLIO_STACKED_ADVISORY_SCENARIO = "advisory_suba_microcap_dd_3_10_month_end"
PORTFOLIO_ADVISORY_OUTPUT_DIR = os.path.join("outputs", "portfolio_v77_current")
PORTFOLIO_ADVISORY_CURVE_FILE = "scenario_economic_curve.csv"
PORTFOLIO_ADVISORY_RETURNS_FILE = "aligned_sleeve_returns.csv"
PORTFOLIO_RISK_GOVERNANCE_FILE = "level8_risk_governance.csv"
PORTFOLIO_ADVISORY_SOURCE_RETURNS_FILE = os.path.join(
    "quant_param_scan_runs",
    "20260512_v77_five_sleeve_real_subd_v20_rebalance_validation",
    "aligned_five_sleeve_real_subd_returns.csv",
)


def _advisory_pct(value):
    try:
        if value is None or pd.isna(value):
            return "n/a"
        return f"{float(value):.2%}"
    except Exception:
        return "n/a"


def _advisory_weight_pct(value):
    try:
        if value is None or pd.isna(value):
            return "n/a"
        return f"{float(value):.0%}"
    except Exception:
        return "n/a"


def _advisory_target_weight(base_weight, prior_dd, boost_dd=0.03, cut_dd=0.10, step=0.05):
    if prior_dd is None or pd.isna(prior_dd):
        return base_weight
    if prior_dd >= -boost_dd:
        return base_weight + step
    if prior_dd <= -cut_dd:
        return max(base_weight - step, 0.0)
    return base_weight


def _latest_prior_nav_drawdown(ret_df, sleeve):
    if sleeve not in ret_df.columns:
        return None
    nav = (1.0 + pd.to_numeric(ret_df[sleeve], errors="coerce").fillna(0.0)).cumprod()
    prior_peak = nav.cummax().shift(1)
    prior_dd = nav.shift(1) / prior_peak - 1.0
    value = prior_dd.iloc[-1] if len(prior_dd) else np.nan
    return float(value) if pd.notna(value) else None


def _csv_latest_date(path):
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, usecols=["date"], parse_dates=["date"])
    if df.empty:
        raise ValueError(f"{path} has no rows")
    latest = pd.to_datetime(df["date"], errors="coerce").dropna()
    if latest.empty:
        raise ValueError(f"{path} has no valid date rows")
    return latest.max().normalize()


def _latest_required_close_date(asof_date=None, max_calendar_lag=None):
    current = pd.Timestamp(beijing_now().date() if asof_date is None else asof_date).normalize()
    if max_calendar_lag is not None:
        return pd.Timestamp(current - pd.Timedelta(days=int(max_calendar_lag))).normalize()
    return pd.Timestamp(current - pd.offsets.BDay(1)).normalize()


def _is_cn_required_close_day(date_value):
    dt = pd.Timestamp(date_value).normalize()
    if dt.year > max(CN_MARKET_HOLIDAY_YEARS):
        warnings.warn(
            f"CN market holiday calendar is not configured for {dt.year}; "
            "falling back to weekdays excluding Jan 1.",
            RuntimeWarning,
            stacklevel=2,
        )
        return dt.weekday() < 5 and dt.strftime("%m-%d") != "01-01"
    return dt.weekday() < 5 and dt.strftime("%Y-%m-%d") not in CN_MARKET_HOLIDAYS


def _latest_cn_required_close_date(asof_date=None):
    current = pd.Timestamp(beijing_now().date() if asof_date is None else asof_date).normalize()
    candidate = current - pd.Timedelta(days=1)
    for _ in range(14):
        if _is_cn_required_close_day(candidate):
            return candidate.normalize()
        candidate -= pd.Timedelta(days=1)
    raise poe.BotError(f"A股交易日历无法在 {current.date().isoformat()} 前找到最近收盘日。")


def _latest_portfolio_advisory_required_close_date(asof_date=None):
    # 组合 advisory 跨市场，主脚本目前只有 CN 休市 override；取普通 BDay 与 CN 最近收盘日中更早者，
    # 避免 A股长假期间把组合层辅助面板误判为过期。
    generic_required = _latest_required_close_date(asof_date)
    cn_required = _latest_cn_required_close_date(asof_date)
    return min(generic_required, cn_required).normalize()


def _latest_valid_close_date(df):
    if df is None or len(df) == 0 or "close" not in df.columns:
        return None
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if close.empty:
        return None
    return pd.Timestamp(close.index.max()).normalize()


def _assert_columns_fresh(raw_dict, required_tickers, expected_date=None, max_lag_days=1, label="US"):
    latest_by_ticker = {}
    stale = []
    for ticker in required_tickers:
        df = raw_dict.get(ticker) if isinstance(raw_dict, dict) else None
        if df is None or len(df) == 0:
            stale.append(f"{ticker}: missing")
            continue
        if "close" not in df.columns:
            stale.append(f"{ticker}: missing close column")
            continue
        latest = _latest_valid_close_date(df)
        if pd.isna(latest):
            stale.append(f"{ticker}: no valid close")
            continue
        latest_by_ticker[ticker] = latest
    if expected_date is None and latest_by_ticker:
        expected_date = max(latest_by_ticker.values())
    if expected_date is not None:
        cutoff = pd.Timestamp(expected_date).normalize() - pd.Timedelta(days=max_lag_days)
        for ticker, latest in latest_by_ticker.items():
            if latest < cutoff:
                stale.append(f"{ticker}: latest {latest.date().isoformat()}")
    if stale:
        raise poe.BotError(f"{label} 数据过期/缺失，不能生成正式信号: " + "; ".join(stale))
    return pd.Timestamp(expected_date).normalize() if expected_date is not None else None


def _assert_price_frame_columns_fresh(price_df, required_columns, expected_date, max_lag_days=0, label="price", names=None):
    stale = []
    cutoff = pd.Timestamp(expected_date).normalize() - pd.Timedelta(days=max_lag_days)
    names = names or {}
    for col in required_columns:
        display = names.get(col, col)
        if price_df is None or col not in price_df.columns:
            stale.append(f"{display}: missing")
            continue
        close = pd.to_numeric(price_df[col], errors="coerce").dropna()
        if close.empty:
            stale.append(f"{display}: no valid close")
            continue
        latest = pd.Timestamp(close.index.max()).normalize()
        if latest < cutoff:
            stale.append(f"{display}: latest {latest.date().isoformat()}")
    if stale:
        raise poe.BotError(f"{label} 数据过期/缺失，不能生成正式信号: " + "; ".join(stale))
    return pd.Timestamp(expected_date).normalize()


def _assert_subb_final_price_frame_fresh(us_rot_close, expected_date=None, include_us_live_snapshot=False):
    if expected_date is None:
        if us_rot_close is None or len(us_rot_close) == 0:
            raise poe.BotError("Sub-B最终价格 数据过期/缺失，不能生成正式信号: empty frame")
        expected_date = us_rot_close.index[-1]
    return _assert_price_frame_columns_fresh(
        us_rot_close,
        SUBB_REQUIRED_PRICE_TICKERS,
        expected_date=pd.Timestamp(expected_date).normalize(),
        max_lag_days=1 if include_us_live_snapshot else 0,
        label="Sub-B最终价格",
        names={US_ROT_BTC_TICKER: "BTC/IBIT"},
    )


def _cn_latest_data_source_label(df, fallback_source):
    if df is None or len(df) == 0:
        return fallback_source
    latest = df.iloc[-1]
    label = fallback_source
    if "source" in df.columns:
        value = latest.get("source")
        if value is not None and not pd.isna(value) and str(value).strip():
            label = str(value).strip()
    is_live = False
    if "is_live_bar" in df.columns:
        value = latest.get("is_live_bar")
        if value is not None and not pd.isna(value):
            is_live = bool(value)
    if is_live and "realtime" not in label.lower() and "snapshot" not in label.lower():
        label = f"{label}+realtime snapshot"
    return label


def _write_cn_after_close_stale_warning_or_raise(write, cn_raw, bj_today, include_cn_live_snapshot=False):
    stale_codes = []
    for secid in CN_STOCK_CODES:
        df = cn_raw.get(secid) if isinstance(cn_raw, dict) else None
        latest = _latest_valid_close_date(df)
        if latest is None or pd.Timestamp(latest).date() < bj_today:
            stale_codes.append(secid)
    if not stale_codes:
        return
    stale_names = "、".join(CN_NAMES.get(s, s) for s in stale_codes)
    if not include_cn_live_snapshot:
        raise poe.BotError("A股收盘数据未完整更新，不能生成正式收盘信号: " + stale_names)
    write(f"  ⚠️ **数据延迟:** {stale_names} 尚未更新到今天({bj_today})，"
          f"信号可能不准确，请稍后重新查询\n")


def _should_strict_cn_bond(include_cn_live_snapshot=False, cn_after_close=False):
    return (not bool(include_cn_live_snapshot)) or bool(cn_after_close)


def _latest_live_etf_price(us_close, proxy, live, expected_date=None, max_lag_days=0):
    if us_close is None or live not in us_close.columns:
        return None
    close = pd.to_numeric(us_close[live], errors="coerce").dropna()
    if close.empty:
        return None
    if expected_date is not None:
        latest_date = pd.Timestamp(close.index[-1]).normalize()
        cutoff = pd.Timestamp(expected_date).normalize() - pd.Timedelta(days=int(max_lag_days))
        if latest_date < cutoff:
            return None
    return float(close.iloc[-1])


def _load_level8_governance_snapshot(out_dir):
    governance_path = os.path.join(out_dir, PORTFOLIO_RISK_GOVERNANCE_FILE)
    if not os.path.exists(governance_path):
        return {"available": False, "error": f"missing {PORTFOLIO_RISK_GOVERNANCE_FILE}"}
    try:
        governance = pd.read_csv(governance_path)
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    if governance.empty or "status" not in governance.columns:
        return {"available": False, "error": "empty governance output"}
    status_order = {"ROLLBACK_FIXED": 0, "REVIEW": 1, "ACTIVE_OK": 2, "INFO": 3}
    statuses = governance["status"].dropna().astype(str).str.strip()
    statuses = [status for status in statuses if status]
    if not statuses:
        return {"available": False, "error": "governance status is empty"}
    decision_status = sorted(statuses, key=lambda value: status_order.get(value, 9))[0]
    rows = {str(row.get("rule", "")): row for row in governance.to_dict("records")}
    return {
        "available": True,
        "decision_status": decision_status,
        "relative_nav_drawdown": str(rows.get("relative_nav_drawdown", {}).get("value", "n/a")),
        "execution_load": str(rows.get("execution_load", {}).get("value", "n/a")),
        "rollback_threshold": str(rows.get("relative_nav_drawdown", {}).get("threshold", "n/a")),
    }


def _load_combo_advisory_snapshot(asof_date=None):
    out_dir = os.path.join(_repo_base_dir(), PORTFOLIO_ADVISORY_OUTPUT_DIR)
    curve_path = os.path.join(out_dir, PORTFOLIO_ADVISORY_CURVE_FILE)
    returns_path = os.path.join(out_dir, PORTFOLIO_ADVISORY_RETURNS_FILE)
    source_returns_path = os.path.join(_repo_base_dir(), PORTFOLIO_ADVISORY_SOURCE_RETURNS_FILE)
    if not os.path.exists(curve_path):
        return {"available": False, "error": f"missing {PORTFOLIO_ADVISORY_CURVE_FILE}"}
    if not os.path.exists(returns_path):
        return {"available": False, "error": f"missing {PORTFOLIO_ADVISORY_RETURNS_FILE}"}
    if not os.path.exists(source_returns_path):
        return {"available": False, "error": f"missing source returns: {source_returns_path}"}
    try:
        curve = pd.read_csv(curve_path, parse_dates=["date"]).set_index("date").sort_index()
        returns = pd.read_csv(returns_path, parse_dates=["date"]).set_index("date").sort_index()
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    if curve.empty or returns.empty:
        return {"available": False, "error": "empty portfolio advisory output"}
    latest = curve.iloc[-1]
    latest_date = curve.index[-1]
    try:
        source_latest_date = _csv_latest_date(source_returns_path)
    except Exception as exc:
        return {"available": False, "error": f"invalid source returns: {exc}"}
    required_close_date = _latest_portfolio_advisory_required_close_date(asof_date)
    if latest_date.normalize() < required_close_date:
        return {
            "available": False,
            "error": (
                "stale portfolio advisory report: "
                f"{PORTFOLIO_ADVISORY_CURVE_FILE} latest {latest_date.date().isoformat()} "
                f"< required close {required_close_date.date().isoformat()}"
            ),
        }
    if source_latest_date is not None and source_latest_date.normalize() < required_close_date:
        return {
            "available": False,
            "error": (
                "stale portfolio advisory source returns: "
                f"{source_latest_date.date().isoformat()} "
                f"< required close {required_close_date.date().isoformat()}"
            ),
        }
    if source_latest_date is not None and latest_date.normalize() < source_latest_date:
        return {
            "available": False,
            "error": (
                "stale portfolio advisory report: "
                f"{PORTFOLIO_ADVISORY_CURVE_FILE} latest {latest_date.date().isoformat()} "
                f"< source returns latest {source_latest_date.date().isoformat()}"
            ),
        }
    suba_prior_dd = _latest_prior_nav_drawdown(returns, "Sub-A")
    microcap_prior_dd = _latest_prior_nav_drawdown(returns, "Microcap")
    suba_daily_target = _advisory_target_weight(
        COMBINED_WEIGHTS["Sub-A"], suba_prior_dd, boost_dd=0.05, cut_dd=0.08
    )
    microcap_daily_target = _advisory_target_weight(COMBINED_WEIGHTS["Microcap"], microcap_prior_dd)
    governance = _load_level8_governance_snapshot(out_dir)
    return {
        "available": True,
        "latest_date": latest_date,
        "suba_prior_dd": suba_prior_dd,
        "microcap_prior_dd": microcap_prior_dd,
        "suba_daily_target": suba_daily_target,
        "microcap_daily_target": microcap_daily_target,
        "microcap_weight": float(latest.get("advisory_microcap_weight", np.nan)),
        "microcap_subb_weight": float(latest.get("advisory_subb_weight", np.nan)),
        "suba_advisory_suba_weight": float(latest.get("suba_advisory_suba_weight", np.nan)),
        "suba_advisory_subb_weight": float(latest.get("suba_advisory_subb_weight", np.nan)),
        "suba_advisory_excess_nav": float(latest.get("suba_advisory_excess_nav", np.nan)),
        "stacked_suba_weight": float(latest.get("stacked_advisory_suba_weight", np.nan)),
        "stacked_microcap_weight": float(latest.get("stacked_advisory_microcap_weight", np.nan)),
        "stacked_subb_weight": float(latest.get("stacked_advisory_subb_weight", np.nan)),
        "stacked_excess_nav": float(latest.get("stacked_advisory_excess_nav", np.nan)),
        "governance": governance,
    }


# trade_journal 中也引用为 STRATEGY_WEIGHTS

def _subc_enabled():
    return float(COMBINED_WEIGHTS.get("Sub-C", 0.0) or 0.0) > 1e-12

STRATEGY_WEIGHTS = COMBINED_WEIGHTS

SP500_RISK_REGIME_FILES = [
    ("sp500_risk_regime_video_aligned_hyoas_output.csv", "hy_oas", "HY OAS(BAMLH0A0HYM2)"),
    ("sp500_risk_regime_video_aligned_baa10y_output.csv", "baa10y", "BAA10Y长历史代理"),
]

SP500_RISK_REGIME_EMBEDDED_SNAPSHOT = None

SP500_RISK_REGIME_FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
SP500_RISK_REGIME_FRED_TEXT = "https://r.jina.ai/http://fred.stlouisfed.org/data/{series_id}.txt"
SP500_RISK_REGIME_CREDIT_PROXY = {
    "series_id": "BAMLH0A0HYM2",
    "column": "BAMLH0A0HYM2",
    "label": "HY OAS(BAMLH0A0HYM2)",
}
SP500_RISK_REGIME_WEIGHTS = {
    "vix": 0.25,
    "credit": 0.25,
    "term_spread": 0.15,
    "spx_deviation": 0.15,
    "ma_slope": 0.20,
}


class Rule:
    def __init__(self, name, policy, fail_mode, freshness_required=False, max_lag_days=1):
        self.name = name
        self.policy = policy
        self.fail_mode = fail_mode
        self.freshness_required = bool(freshness_required)
        self.max_lag_days = int(max_lag_days)


RISK_RULES = {
    "suba_volume": Rule(
        name="Sub-A volume overlay",
        policy="hard_trade_rule",
        fail_mode="halt",
        freshness_required=True,
        max_lag_days=1,
    ),
    "dk_volume_warning": Rule(
        name="Sub-A-DK volume warning",
        policy="soft_warning",
        fail_mode="degrade",
        freshness_required=True,
        max_lag_days=1,
    ),
    "microcap_volume_warning": Rule(
        name="Microcap volume warning",
        policy="soft_warning",
        fail_mode="degrade",
        freshness_required=True,
        max_lag_days=1,
    ),
    "sp500_risk_regime": Rule(
        name="S&P 500 risk regime",
        policy="dashboard_only",
        fail_mode="degrade",
        freshness_required=True,
        max_lag_days=7,
    ),
    "subb_inflation_gate": Rule(
        name="Sub-B official leg inflation gate",
        policy="hard_trade_rule",
        fail_mode="halt",
        freshness_required=False,
        max_lag_days=1,
    ),
}

def _repo_base_dir():
    return os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()


def _feature_latest_date(feature):
    if feature is None:
        return None
    if isinstance(feature, dict):
        for key in ("latest_date", "date", "asof_date"):
            if key in feature and feature.get(key) is not None:
                return pd.Timestamp(feature[key]).normalize()
        return None
    if hasattr(feature, "index"):
        idx = getattr(feature, "index")
        if len(idx) == 0:
            return None
        latest = pd.to_datetime(idx, errors="coerce").max()
        if pd.isna(latest):
            return None
        return pd.Timestamp(latest).normalize()
    return None


def _assert_feature_fresh(feature, expected_date, max_lag_days=1, name="feature"):
    latest = _feature_latest_date(feature)
    if latest is None:
        raise poe.BotError(f"{name} 数据日期不可判定")
    expected = pd.Timestamp(expected_date).normalize()
    cutoff = expected - pd.Timedelta(days=int(max_lag_days))
    if latest < cutoff:
        raise poe.BotError(
            f"{name} 数据过期: latest={latest.date()}, expected={expected.date()}"
        )
    return latest


def _feature_freshness_status(feature, expected_date, rule_key, name=None):
    rule = RISK_RULES[rule_key]
    expected = pd.Timestamp(expected_date).normalize()
    latest = _feature_latest_date(feature)
    out = {
        "freshness_expected_date": expected.date().isoformat(),
        "freshness_latest_date": latest.date().isoformat() if latest is not None else None,
        "freshness_ok": True,
        "freshness_error": "",
    }
    if not rule.freshness_required:
        return out
    try:
        latest = _assert_feature_fresh(
            feature,
            expected_date=expected,
            max_lag_days=rule.max_lag_days,
            name=name or rule.name,
        )
        out["freshness_latest_date"] = latest.date().isoformat()
    except poe.BotError as exc:
        out["freshness_ok"] = False
        out["freshness_error"] = str(exc)
    return out


def _annotate_rule_freshness(feature, expected_date, rule_key):
    if feature is None or len(feature) == 0:
        return feature
    rule = RISK_RULES[rule_key]
    out = feature.copy()
    status = _feature_freshness_status(out, expected_date, rule_key, name=rule.name)
    for key, value in status.items():
        out[key] = value
    if rule.policy == "hard_trade_rule" and not status["freshness_ok"]:
        out["combined_unresolved"] = True
    return out


def _annotate_status_freshness(status, expected_date, rule_key):
    rule = RISK_RULES[rule_key]
    checked = dict(status or {})
    status_feature = {"date": checked.get("date") or checked.get("latest_date")}
    checked.update(_feature_freshness_status(status_feature, expected_date, rule_key, name=rule.name))
    return checked


def _warning_feature_expected_date(asof_date=None):
    return pd.Timestamp(beijing_now().date() if asof_date is None else asof_date).normalize()


def _check_microcap_cache_latest(ret, expected_latest_date=None, source_label="microcap", msg=None):
    if expected_latest_date is None:
        return
    expected = pd.Timestamp(expected_latest_date).normalize()
    actual = pd.Timestamp(ret.index.max()).normalize()
    if actual < expected:
        message = (
            f"微盘缓存过期: {source_label} 截至 {actual.strftime('%Y-%m-%d')}, "
            f"但本次A股合并数据截至 {expected.strftime('%Y-%m-%d')}。请先刷新微盘股独立脚本缓存。"
        )
        if msg is not None:
            msg.write(f"  ⚠️ **{message}**\n")
        raise poe.BotError(message)
    if msg is not None:
        msg.write(
            f"  ✅ 微盘缓存日期OK: {actual.strftime('%Y-%m-%d')} "
            f"(A股合并截至 {expected.strftime('%Y-%m-%d')})\n"
        )


def _load_microcap_daily_ret(msg=None, expected_latest_date=None):
    microcap_root = os.path.join(os.path.dirname(_repo_base_dir()), "微盘股对冲策略")
    v20_nav_candidates = [
        os.path.join(
            microcap_root,
            "outputs",
            "microcap_top100_mom16_targetvol15_max1p5_v2_0_costed_nav.csv",
        ),
        os.path.join(
            microcap_root,
            "outputs",
            "microcap_top100_mom16_targetvol25_max1p5_v2_0_costed_nav.csv",
        ),
    ]
    v20_nav_path = next((path for path in v20_nav_candidates if os.path.exists(path)), None)
    if v20_nav_path is None:
        raise poe.BotError("V7.9微盘股 v2.0 target-vol 独立模块缓存缺失: " + " / ".join(v20_nav_candidates))
    try:
        net = pd.read_csv(v20_nav_path, parse_dates=["date"]).sort_values("date").set_index("date")
        ret = net["return_net"].dropna()
        if ret.empty:
            raise ValueError("empty microcap return series")
        v20_nav_file = os.path.basename(v20_nav_path)
        if "targetvol15" in v20_nav_file:
            source_label = "v2.0 mom16_targetvol15_max1p5 costed_nav"
        elif "targetvol25" in v20_nav_file:
            source_label = "v2.0 mom16_targetvol25_max1p5 costed_nav"
        else:
            source_label = f"v2.0 {v20_nav_file}"
        _check_microcap_cache_latest(ret, expected_latest_date, source_label, msg)
        if msg is not None:
            msg.write(
                f"  微盘股独立脚本 v2.0 target-vol: {ret.index[0].strftime('%Y-%m-%d')}~"
                f"{ret.index[-1].strftime('%Y-%m-%d')} [{os.path.basename(v20_nav_path)}]\n"
            )
        return ret
    except poe.BotError:
        raise
    except Exception as exc:
        raise poe.BotError(f"加载微盘股 v2.0 target-vol 独立脚本收益失败: {exc}") from exc


def _sp500_risk_regime_search_paths():
    base_dir = _repo_base_dir()
    learning_dir = os.path.join(os.path.dirname(base_dir), "新策略学习")
    return [
        (os.path.join(learning_dir, filename), proxy, label)
        for filename, proxy, label in SP500_RISK_REGIME_FILES
    ]


def _sp500_risk_regime_robust_z(series, window=156, min_periods=52):
    med = series.rolling(window, min_periods=min_periods).median()
    mad = (series - med).abs().rolling(window, min_periods=min_periods).median()
    sigma = 1.4826 * mad
    z = (series - med) / sigma.replace(0, np.nan)
    return z.replace([np.inf, -np.inf], np.nan)


def _sp500_risk_regime_score_from_z(z):
    return (50.0 + 20.0 * z.clip(-2.5, 2.5)).clip(0, 100)


def _sp500_risk_regime_name(score):
    if score < 20:
        return "1-简单模式"
    if score < 40:
        return "2-普通模式"
    if score < 55:
        return "3-困难模式"
    if score < 70:
        return "4-噩梦模式"
    if score < 85:
        return "5-地狱模式"
    return "6-炼狱模式"


def _sp500_risk_regime_equity_budget(score):
    if score < 20:
        return "100%"
    if score < 40:
        return "85%"
    if score < 55:
        return "70%"
    if score < 70:
        return "50%"
    if score < 85:
        return "35%"
    return "15%"


def _fetch_sp500_risk_regime_fred_series(series_id):
    errors = []
    text_url = SP500_RISK_REGIME_FRED_TEXT.format(series_id=series_id)
    try:
        resp = requests.get(text_url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            raise ValueError(f"status {resp.status_code}")
        rows = []
        for line in resp.text.splitlines():
            match = re.match(r"^\|?\s*(\d{4}-\d{2}-\d{2})\s*(?:\||\t)\s*([-.0-9]+|\.)\s*\|?$", line.strip())
            if not match:
                continue
            date_text, value_text = match.groups()
            rows.append((pd.Timestamp(date_text), pd.to_numeric(value_text, errors="coerce")))
        if rows:
            out = pd.Series([v for _, v in rows], index=[d for d, _ in rows], name=series_id).dropna().sort_index()
        else:
            raise ValueError("no parseable rows")
    except Exception as exc:
        errors.append(f"FRED text mirror: {exc}")
        url = SP500_RISK_REGIME_FRED_CSV.format(series_id=series_id)
        resp = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            raise ValueError(f"FRED {series_id} returned status {resp.status_code}; {'; '.join(errors)}")
        df = pd.read_csv(io.StringIO(resp.text))
        if df.empty or len(df.columns) < 2:
            raise ValueError(f"FRED {series_id} returned empty CSV; {'; '.join(errors)}")
        date_col, value_col = df.columns[0], df.columns[1]
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df[value_col] = pd.to_numeric(df[value_col].replace(".", np.nan), errors="coerce")
        out = df.dropna(subset=[date_col]).set_index(date_col)[value_col].dropna().sort_index()
    if len(out) < 260:
        raise ValueError(f"FRED {series_id} has too few usable rows: {len(out)}")
    return out.rename(series_id)


def _fetch_sp500_risk_regime_spx_close():
    df, source = fetch_yahoo("^GSPC", start_date="1985-01-01")
    if df is not None and len(df.dropna()) > 1000:
        return df["close"].dropna().rename("SPX"), source
    sp500 = _fetch_sp500_risk_regime_fred_series("SP500").dropna()
    if len(sp500) < 1000:
        raise ValueError("Could not fetch enough S&P 500 history")
    return sp500.rename("SPX"), "FRED SP500"


def _build_sp500_risk_regime_snapshot_from_series(
    spx,
    vix,
    credit,
    term,
    spx_source="Yahoo",
    credit_meta=None,
    source_file=None,
    source_type="live",
    live_error=None,
):
    credit_meta = credit_meta or SP500_RISK_REGIME_CREDIT_PROXY
    credit_col = credit_meta["column"]
    daily = pd.concat([spx.rename("SPX"), vix.rename("VIXCLS"), credit.rename(credit_col), term.rename("T10Y2Y")], axis=1).sort_index()
    source_input_dates = {
        "SPX": spx.dropna().index[-1].strftime("%Y-%m-%d"),
        "VIXCLS": vix.dropna().index[-1].strftime("%Y-%m-%d"),
        credit_col: credit.dropna().index[-1].strftime("%Y-%m-%d"),
        "T10Y2Y": term.dropna().index[-1].strftime("%Y-%m-%d"),
    }
    weekly = daily.resample("W-FRI").last().ffill()
    weekly["spx_ma"] = weekly["SPX"].rolling(40).mean()
    weekly["spx_deviation"] = weekly["SPX"] / weekly["spx_ma"] - 1.0
    weekly["ma_slope"] = weekly["spx_ma"].pct_change(13)
    weekly["vix_z"] = _sp500_risk_regime_robust_z(np.log(weekly["VIXCLS"]))
    weekly["credit_change"] = weekly[credit_col].diff(4)
    weekly["credit_change_z"] = _sp500_risk_regime_robust_z(weekly["credit_change"])
    weekly["term_z"] = _sp500_risk_regime_robust_z(-weekly["T10Y2Y"])
    weekly["dev_z"] = _sp500_risk_regime_robust_z(-weekly["spx_deviation"])
    weekly["slope_z"] = _sp500_risk_regime_robust_z(-weekly["ma_slope"])
    wgt = SP500_RISK_REGIME_WEIGHTS
    weekly["risk_z"] = (
        weekly["vix_z"] * wgt["vix"]
        + weekly["credit_change_z"] * wgt["credit"]
        + weekly["term_z"] * wgt["term_spread"]
        + weekly["dev_z"] * wgt["spx_deviation"]
        + weekly["slope_z"] * wgt["ma_slope"]
    )
    weekly["base_score"] = _sp500_risk_regime_score_from_z(weekly["risk_z"])
    feature_cols = ["vix_z", "credit_change_z", "term_z", "dev_z", "slope_z"]
    weekly["feature_veto"] = weekly[feature_cols].max(axis=1) >= 2.0
    rolling_low = weekly["SPX"].rolling(8, min_periods=2).min()
    weekly["rebound_from_8w_low"] = weekly["SPX"] / rolling_low - 1.0
    recent_oversold = weekly["spx_deviation"].rolling(8, min_periods=2).min() <= -0.10
    rebound_cross = (weekly["rebound_from_8w_low"] >= 0.02) & (weekly["rebound_from_8w_low"].shift(1) < 0.02)
    weekly["oversold_turn_rule"] = recent_oversold & rebound_cross & (weekly["base_score"] >= 55.0)
    score = pd.Series(
        np.maximum(weekly["base_score"], np.where(weekly["feature_veto"], 55.0, 0.0)),
        index=weekly.index,
    )
    score.loc[weekly["oversold_turn_rule"]] = (score.loc[weekly["oversold_turn_rule"]] - 10.0).clip(lower=0)
    weekly["risk_score"] = score.clip(0, 100)
    weekly = weekly.dropna(subset=["risk_score"])
    if weekly.empty:
        raise ValueError("S&P 500 risk regime model produced no usable weekly rows")
    latest = weekly.iloc[-1]
    latest_regime = _sp500_risk_regime_name(float(latest["risk_score"]))
    regime_series = weekly["risk_score"].apply(lambda x: _sp500_risk_regime_name(float(x)))
    change_date = weekly.index[0]
    previous_regime = latest_regime
    different_before = np.flatnonzero((regime_series != latest_regime).to_numpy())
    if len(different_before) > 0 and different_before[-1] + 1 < len(weekly):
        change_date = weekly.index[different_before[-1] + 1]
        previous_regime = regime_series.iloc[different_before[-1]]
    return {
        "latest_date": weekly.index[-1],
        "regime_changed_date": change_date,
        "previous_regime": previous_regime,
        "risk_score": float(latest["risk_score"]),
        "regime": latest_regime,
        "suggested_equity_budget": _sp500_risk_regime_equity_budget(float(latest["risk_score"])),
        "credit_proxy": credit_meta.get("proxy", "hy_oas"),
        "credit_series": credit_meta.get("series_id", credit_col),
        "feature_veto": bool(latest["feature_veto"]),
        "oversold_turn_rule": bool(latest["oversold_turn_rule"]),
        "source_label": credit_meta.get("label", credit_col),
        "source_type": source_type,
        "source_file": source_file or "FRED+Yahoo实时计算",
        "spx_source": spx_source,
        "input_dates": source_input_dates,
        "credit_input_key": credit_col,
        "live_error": live_error,
    }


def _fetch_yahoo_close_series_for_sp500_risk(ticker, start_date="2007-01-01"):
    df, source = fetch_yahoo(ticker, start_date=start_date)
    if df is None or "close" not in df.columns:
        raise ValueError(f"Yahoo proxy returned no close data for {ticker}")
    close = df["close"].dropna().sort_index()
    if len(close) < 1000:
        raise ValueError(f"Yahoo proxy {ticker} has too few rows: {len(close)}")
    return close.rename(ticker), source


def _fetch_sp500_risk_regime_yahoo_proxy_snapshot(exact_error=None):
    spx, spx_source = _fetch_sp500_risk_regime_spx_close()
    vix, vix_source = _fetch_yahoo_close_series_for_sp500_risk("^VIX", start_date="2007-01-01")
    hyg, hyg_source = _fetch_yahoo_close_series_for_sp500_risk("HYG", start_date="2007-01-01")
    lqd, lqd_source = _fetch_yahoo_close_series_for_sp500_risk("LQD", start_date="2007-01-01")
    ief, ief_source = _fetch_yahoo_close_series_for_sp500_risk("IEF", start_date="2007-01-01")
    shy, shy_source = _fetch_yahoo_close_series_for_sp500_risk("SHY", start_date="2007-01-01")

    credit = (np.log(lqd / hyg) * 100.0).dropna().rename("HYG_LQD_CREDIT_PROXY")
    term = (-np.log(ief / shy) * 100.0).dropna().rename("IEF_SHY_TERM_PROXY")
    credit_meta = {
        "series_id": "HYG/LQD",
        "column": "HYG_LQD_CREDIT_PROXY",
        "label": "HYG/LQD信用代理",
        "proxy": "hyg_lqd",
    }
    snapshot = _build_sp500_risk_regime_snapshot_from_series(
        spx,
        vix,
        credit,
        term,
        spx_source=spx_source,
        credit_meta=credit_meta,
        source_file="Yahoo代理实时计算",
        source_type="live_proxy",
        live_error=str(exact_error) if exact_error else None,
    )
    input_sources = snapshot.setdefault("input_sources", {})
    input_sources.update({
        "SPX": spx_source,
        "VIXCLS": vix_source,
        "HYG": hyg_source,
        "LQD": lqd_source,
        "IEF": ief_source,
        "SHY": shy_source,
    })
    return snapshot


def _fetch_sp500_risk_regime_live_snapshot():
    try:
        spx, spx_source = _fetch_sp500_risk_regime_spx_close()
        vix = _fetch_sp500_risk_regime_fred_series("VIXCLS")
        credit = _fetch_sp500_risk_regime_fred_series(SP500_RISK_REGIME_CREDIT_PROXY["series_id"])
        term = _fetch_sp500_risk_regime_fred_series("T10Y2Y")
        return _build_sp500_risk_regime_snapshot_from_series(spx, vix, credit, term, spx_source=spx_source)
    except Exception as exc:
        return _fetch_sp500_risk_regime_yahoo_proxy_snapshot(exact_error=exc)



def _sp500_risk_regime_expected_weekly_label(asof_date=None):
    ts = pd.Timestamp(beijing_now()) if asof_date is None else pd.Timestamp(asof_date)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("Asia/Shanghai").tz_localize(None)
    ts = ts.normalize()
    return ts - pd.Timedelta(days=(ts.weekday() - 4) % 7)


def _sp500_risk_regime_snapshot_is_current_week(snapshot, asof_date=None):
    latest_date = snapshot.get("latest_date")
    if latest_date is None:
        return False
    latest_ts = pd.Timestamp(latest_date)
    if latest_ts.tzinfo is not None:
        latest_ts = latest_ts.tz_convert("Asia/Shanghai").tz_localize(None)
    return latest_ts.normalize() >= _sp500_risk_regime_expected_weekly_label(asof_date)


def _annotate_sp500_risk_regime_freshness(snapshot, asof_date=None):
    expected = _warning_feature_expected_date(asof_date)
    return _annotate_status_freshness(snapshot, expected, "sp500_risk_regime")


def _load_sp500_risk_regime_csv_snapshot(search_paths=None, live_error=None):
    paths = search_paths if search_paths is not None else _sp500_risk_regime_search_paths()
    required = {"risk_score", "regime", "suggested_equity_budget", "credit_proxy", "credit_series"}
    for path, fallback_proxy, source_label in paths:
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path, index_col=0, encoding="utf-8-sig")
            missing = required - set(df.columns)
            if missing:
                continue
            df.index = pd.to_datetime(df.index, errors="coerce")
            df = df[df.index.notna()].sort_index()
            df = df.dropna(subset=["risk_score", "regime"])
            if df.empty:
                continue
            latest = df.iloc[-1]
            latest_regime = str(latest["regime"])
            regime_series = df["regime"].astype(str)
            change_date = df.index[0]
            previous_regime = latest_regime
            different_before = np.flatnonzero((regime_series != latest_regime).to_numpy())
            if len(different_before) > 0 and different_before[-1] + 1 < len(df):
                change_date = df.index[different_before[-1] + 1]
                previous_regime = regime_series.iloc[different_before[-1]]
            return {
                "latest_date": df.index[-1],
                "regime_changed_date": change_date,
                "previous_regime": previous_regime,
                "risk_score": float(latest["risk_score"]),
                "regime": latest_regime,
                "suggested_equity_budget": str(latest["suggested_equity_budget"]),
                "credit_proxy": str(latest.get("credit_proxy", fallback_proxy)),
                "credit_series": str(latest.get("credit_series", "")),
                "feature_veto": bool(latest.get("feature_veto", False)),
                "oversold_turn_rule": bool(latest.get("oversold_turn_rule", False)),
                "source_label": source_label,
                "source_type": "csv",
                "source_file": os.path.basename(path),
                "live_error": live_error,
                "path": path,
            }
        except (OSError, ValueError, KeyError, pd.errors.ParserError):
            continue
    return None


def _load_sp500_risk_regime_snapshot(search_paths=None, live_fetch=True, prefer_recent_csv=False, asof_date=None, allow_embedded=True):
    csv_snapshot = _load_sp500_risk_regime_csv_snapshot(search_paths=search_paths)
    if prefer_recent_csv and csv_snapshot is not None and _sp500_risk_regime_snapshot_is_current_week(
        csv_snapshot, asof_date=asof_date
    ):
        return _annotate_sp500_risk_regime_freshness(csv_snapshot, asof_date=asof_date)

    live_error = None
    if live_fetch:
        try:
            return _annotate_sp500_risk_regime_freshness(
                _fetch_sp500_risk_regime_live_snapshot(),
                asof_date=asof_date,
            )
        except Exception as exc:
            live_error = str(exc)

    if csv_snapshot is not None:
        csv_snapshot["live_error"] = live_error
        return _annotate_sp500_risk_regime_freshness(csv_snapshot, asof_date=asof_date)

    if not allow_embedded:
        if live_error:
            raise RuntimeError(f"S&P 500 risk regime live calculation failed: {live_error}")
        raise RuntimeError("S&P 500 risk regime data unavailable")

    if not SP500_RISK_REGIME_EMBEDDED_SNAPSHOT:
        if live_error:
            raise RuntimeError(f"S&P 500 risk regime live calculation failed: {live_error}")
        raise RuntimeError("S&P 500 risk regime data unavailable")

    embedded = dict(SP500_RISK_REGIME_EMBEDDED_SNAPSHOT)
    embedded["latest_date"] = pd.Timestamp(embedded["latest_date"])
    embedded["regime_changed_date"] = pd.Timestamp(embedded["regime_changed_date"])
    embedded["path"] = embedded["source_file"]
    embedded["live_error"] = live_error
    today = pd.Timestamp(asof_date).normalize() if asof_date is not None else pd.Timestamp(beijing_now().date())
    embedded_age_days = int((today - embedded["latest_date"].normalize()).days)
    embedded["embedded_age_days"] = embedded_age_days
    if embedded_age_days > 7:
        embedded["source_type"] = "STALE_EMBEDDED_DO_NOT_TRADE"
        embedded["stale_warning"] = "Embedded S&P risk snapshot is older than 7 days; historical reference only."
    return _annotate_sp500_risk_regime_freshness(embedded, asof_date=asof_date)


INFLATION_PRESSURE_LB = 126


def _load_inflation_pressure_snapshot():
    price_series = {}
    price_sources = {}
    for ticker in ("DBC", "TLT", "UUP"):
        df, source = fetch_yahoo(ticker, start_date="2006-01-01")
        if df is None or "close" not in df.columns:
            raise ValueError(f"{ticker} price data unavailable from Yahoo/Stooq")
        close = df["close"].dropna().sort_index()
        if len(close) <= INFLATION_PRESSURE_LB:
            raise ValueError(f"{ticker} usable history is too short")
        price_series[ticker] = close
        price_sources[ticker] = source
    aligned = pd.concat(price_series, axis=1).dropna()
    if len(aligned) <= INFLATION_PRESSURE_LB:
        raise ValueError("inflation pressure price history is too short after alignment")
    latest = aligned.iloc[-1]
    previous = aligned.iloc[-(INFLATION_PRESSURE_LB + 1)]
    mom = latest / previous - 1.0
    latest_date = aligned.index[-1]
    pressure_on = bool(mom["DBC"] > 0 and mom["TLT"] < 0)
    usd_trend_on = bool(mom["UUP"] > 0)
    if pressure_on and usd_trend_on:
        label = "3-通胀压力+美元趋势"
        action = "DBMF/KMLM进入Sub-B官方腿候选池"
    elif pressure_on:
        label = "2-通胀压力"
        action = "商品上行且长债承压，DBMF/KMLM进入Sub-B官方腿候选池"
    else:
        label = "1-未触发"
        action = "市场型通胀预警未触发"

    cpi_snapshot = {}
    try:
        cpi = _fetch_sp500_risk_regime_fred_series("CPIAUCSL").dropna().sort_index()
        if len(cpi) >= 24:
            yoy = cpi.pct_change(12)
            three_month_ann = (cpi / cpi.shift(3)) ** 4 - 1.0
            yoy_change_6m = yoy - yoy.shift(6)
            cpi_frame = pd.DataFrame({
                "cpi_yoy": yoy,
                "cpi_3m_ann": three_month_ann,
                "cpi_yoy_change_6m": yoy_change_6m,
            }).dropna()
            if not cpi_frame.empty:
                cpi_latest = cpi_frame.iloc[-1]
                cpi_snapshot = {
                    "cpi_latest_date": cpi_frame.index[-1],
                    "cpi_yoy": float(cpi_latest["cpi_yoy"]),
                    "cpi_3m_ann": float(cpi_latest["cpi_3m_ann"]),
                    "cpi_yoy_change_6m": float(cpi_latest["cpi_yoy_change_6m"]),
                }
    except Exception as exc:
        cpi_snapshot = {"cpi_error": str(exc)}

    return {
        "latest_date": latest_date,
        "lookback": INFLATION_PRESSURE_LB,
        "label": label,
        "pressure_on": pressure_on,
        "usd_trend_on": usd_trend_on,
        "dbc_mom": float(mom["DBC"]),
        "tlt_mom": float(mom["TLT"]),
        "uup_mom": float(mom["UUP"]),
        "action": action,
        "source": " / ".join(f"{ticker}:{price_sources[ticker]}" for ticker in ("DBC", "TLT", "UUP")),
        **cpi_snapshot,
    }


def _normalize_row_idx(index, row_idx):
    return len(index) + row_idx if row_idx < 0 else row_idx


def _inflation_pressure_state_from_prices(close_df, row_idx, lookback=INFLATION_PRESSURE_LB):
    row_idx = _normalize_row_idx(close_df.index, row_idx)
    if row_idx < lookback:
        return None
    if "DBC" not in close_df.columns or "TLT" not in close_df.columns:
        return None
    current = close_df.iloc[row_idx]
    previous = close_df.iloc[row_idx - lookback]
    if pd.isna(current.get("DBC")) or pd.isna(previous.get("DBC")):
        return None
    if pd.isna(current.get("TLT")) or pd.isna(previous.get("TLT")):
        return None
    dbc_mom = current["DBC"] / previous["DBC"] - 1.0
    tlt_mom = current["TLT"] / previous["TLT"] - 1.0
    return bool(dbc_mom > 0 and tlt_mom < 0)


def _inflation_pressure_on_from_prices(close_df, row_idx, lookback=INFLATION_PRESSURE_LB):
    return _inflation_pressure_state_from_prices(close_df, row_idx, lookback) is True


def _subb_active_ranking_codes(close_df, row_idx, base_codes=None):
    base = list(base_codes) if base_codes is not None else list(US_ROT_BASE_POOL)
    state = _inflation_pressure_state_from_prices(close_df, row_idx)
    if state is None:
        raise poe.BotError("Sub-B通胀门控数据不可判定：DBC/TLT缺失或过期")
    if state is False:
        return base
    available_macro = [code for code in US_ROT_MACRO_POOL if code in close_df.columns]
    return base + [code for code in available_macro if code not in base]


def _us_rot_late_history_tickers():
    return {"BTC-USD", "EMXC", *US_ROT_MACRO_POOL}


def _subb_inflation_gate_context(close_df, row_idx):
    row_idx = _normalize_row_idx(close_df.index, row_idx)
    state = _inflation_pressure_state_from_prices(close_df, row_idx)
    if state is None:
        raise poe.BotError("Sub-B通胀门控数据不可判定：DBC/TLT缺失或过期")
    out = {
        "pressure_on": state,
        "lookback": INFLATION_PRESSURE_LB,
        "latest_date": close_df.index[row_idx],
    }
    if row_idx >= INFLATION_PRESSURE_LB:
        cur = close_df.iloc[row_idx]
        prev = close_df.iloc[row_idx - INFLATION_PRESSURE_LB]
        for ticker in ("DBC", "TLT", "UUP"):
            if ticker in close_df.columns and not pd.isna(cur.get(ticker)) and not pd.isna(prev.get(ticker)):
                out[f"{ticker.lower()}_mom"] = float(cur[ticker] / prev[ticker] - 1.0)
    out["ranking_codes"] = _subb_active_ranking_codes(close_df, row_idx)
    return out


def _short_error(exc, max_len=120):
    text = str(exc).replace("\n", " ").replace("\r", " ")
    text = re.sub(r"https?://\S+", "[url]", text)
    return text if len(text) <= max_len else text[:max_len] + "..."

def _write_sp500_risk_regime_note(msg, prefer_recent_csv=False, compact=False):
    w = msg.write
    w("### S&P 500风险等级与通胀开关（仅提示）\n")
    snapshot = None
    try:
        snapshot = _load_sp500_risk_regime_snapshot(prefer_recent_csv=prefer_recent_csv, allow_embedded=False)
        latest_date = snapshot["latest_date"].strftime("%Y-%m-%d")
        changed_date = snapshot["regime_changed_date"].strftime("%Y-%m-%d")
        flags = []
        if snapshot["feature_veto"]:
            flags.append("单因子否决权触发")
        if snapshot["oversold_turn_rule"]:
            flags.append("超跌拐头减分")
        flag_text = f" | 规则: {'、'.join(flags)}" if flags else ""
        if snapshot.get("source_type") in ("live", "live_proxy"):
            source_desc = snapshot.get("source_file", "FRED+Yahoo实时计算")
        elif snapshot.get("source_type") == "csv":
            source_desc = f"新策略学习/{snapshot['source_file']}"
        else:
            source_desc = snapshot.get("source_file", "脚本内置快照")
        if snapshot.get("source_type") == "STALE_EMBEDDED_DO_NOT_TRADE":
            source_desc = f"{source_desc} (STALE_EMBEDDED_DO_NOT_TRADE)"
        _prev_regime = snapshot.get("previous_regime")
        if _prev_regime and _prev_regime != snapshot["regime"]:
            _change_text = f"{_prev_regime} → {snapshot['regime']} ({changed_date})"
        else:
            _change_text = changed_date
        w(f"数据: {source_desc} | 周频标签: **{latest_date}** | 等级变化: **{_change_text}**\n")
        if not snapshot.get("freshness_ok", True):
            w(f"⚠️ 数据新鲜度: {snapshot.get('freshness_error', 'S&P风险等级数据过期')}；仅提示，不应按最新风控确认执行。\n")
        w(
            f"等级: **{snapshot['regime']}** | 风险分数: **{snapshot['risk_score']:.1f}/100** "
            f"| 建议美股风险资产预算上限: **{snapshot['suggested_equity_budget']}**{flag_text}\n"
        )
    except Exception as exc:
        w(
            "数据: FRED+Yahoo实时计算 | S&P风险等级: **UNKNOWN** | "
            f"本次实时计算失败: {_short_error(exc)}\n"
        )
    inflation = None
    try:
        inflation = _load_inflation_pressure_snapshot()
        infl_state = "🟢 ON" if inflation["pressure_on"] else "OFF"
        macro_action = (
            "DBMF/KMLM 参与 Sub-B 官方腿候选池；EMA/Bias/LogVol腿始终US_ROT_POOL全池"
            if inflation["pressure_on"]
            else "DBMF/KMLM 不进官方腿；EMA/Bias/LogVol腿仍始终US_ROT_POOL全池"
        )
        w(
            f"通胀开关: **{infl_state}** | {macro_action} | "
            f"DBC {inflation['lookback']}日 {inflation['dbc_mom']:+.2%}, "
            f"TLT {inflation['lookback']}日 {inflation['tlt_mom']:+.2%} | "
            f"数据日 {inflation['latest_date'].strftime('%Y-%m-%d')}\n"
        )
        if compact:
            w("规则: DBC动量>0 且 TLT动量<0 时，通胀开关为 ON。\n\n---\n\n")
            return
    except Exception as exc:
        w(f"通胀开关: **UNKNOWN** | 本次未取到 DBC/TLT/UUP 市场数据: {_short_error(exc)}\n")
        if compact:
            w("\n---\n\n")
            return
    if snapshot is not None:
        w(f"信用口径: {snapshot['source_label']}（{snapshot['credit_series']}）\n")
        if snapshot.get("source_type") in ("live", "live_proxy"):
            input_dates = snapshot.get("input_dates", {})
            if input_dates:
                credit_input_key = snapshot.get("credit_input_key", snapshot.get("credit_series", ""))
                w(
                    "输入日期: "
                    f"SPX {input_dates.get('SPX', 'NA')} | "
                    f"VIX {input_dates.get('VIXCLS', 'NA')} | "
                    f"{snapshot['credit_series']} {input_dates.get(credit_input_key, 'NA')} | "
                    f"10Y-2Y {input_dates.get('T10Y2Y', 'NA')}\n"
                )
            if snapshot.get("spx_source"):
                macro_source = "Yahoo代理" if snapshot.get("source_type") == "live_proxy" else "FRED文本镜像/CSV"
                w(f"价格源: {snapshot['spx_source']} | 宏观源: {macro_source}\n")
            if snapshot.get("source_type") == "live_proxy":
                w("⚠️ FRED本次未完整取到，S&P风险等级改用Yahoo代理实时计算；仅提示，不作为正式口径替代。\n")
        else:
            if snapshot.get("live_error"):
                w("⚠️ 实时数据源本次未完整取到，当前显示为非实时备用快照；不要把它当作最新确认预警。\n")
                w(f"实时取数失败原因: {_short_error(snapshot['live_error'])}\n")
    try:
        if inflation is None:
            inflation = _load_inflation_pressure_snapshot()
        w(
            f"通胀压力: **{inflation['label']}** | DBC {inflation['lookback']}日 **{inflation['dbc_mom']:.2%}** "
            f"| TLT {inflation['lookback']}日 **{inflation['tlt_mom']:.2%}** | UUP {inflation['lookback']}日 **{inflation['uup_mom']:.2%}**\n"
        )
        w(
            f"通胀口径: **DBC动量>0 且 TLT动量<0**（{inflation['lookback']}日）"
            f" | 数据日 {inflation['latest_date'].strftime('%Y-%m-%d')} | {inflation['source']} | {inflation['action']}\n"
        )
        if "cpi_yoy" in inflation:
            w(
                f"CPI背景: YoY **{inflation['cpi_yoy']:.2%}** | 3M年化 **{inflation['cpi_3m_ann']:.2%}** "
                f"| YoY近6个月变化 **{inflation['cpi_yoy_change_6m']:.2%}**（{inflation['cpi_latest_date'].strftime('%Y-%m-%d')}，FRED CPIAUCSL）\n"
            )
        elif "cpi_error" in inflation:
            w(f"CPI背景: 本次未取到FRED CPIAUCSL，仅显示市场型通胀预警；原因: {inflation['cpi_error']}\n")
    except Exception as exc:
        w(f"⚠️ 通胀压力提示本次未取到 DBC/TLT/UUP 市场数据: {_short_error(exc)}\n")
    w(f"定位: S&P风险等级只作组合级美股风险预算提示；通胀压力只控制 Sub-B 官方腿宏观候选池。{_v78_subb_inflation_participation_note()}\n\n---\n\n")


def _sm():
    return poe.start_message()

def _get_session():
    s = requests.Session()
    retries = Retry(
        total=5, connect=3, read=3,
        backoff_factor=1.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
    })
    return s
_session = _get_session()
atexit.register(_session.close)
_csindex_fail_state = threading.local()


def _get_csindex_consecutive_fails():
    return int(getattr(_csindex_fail_state, "consecutive_fails", 0) or 0)


def _set_csindex_consecutive_fails(value):
    _csindex_fail_state.consecutive_fails = max(0, int(value))


def _reset_csindex_consecutive_fails():
    _set_csindex_consecutive_fails(0)


def _increment_csindex_consecutive_fails():
    _set_csindex_consecutive_fails(_get_csindex_consecutive_fails() + 1)


# 数据获取/解析相关的可恢复异常 — 真正的bug（AttributeError等）将正常传播
class DataSchemaError(ValueError):
    """Remote data payload shape changed in a known data-source parser."""


class DataUnavailableError(RuntimeError):
    """All configured data sources for an optional remote series were unavailable."""


NETWORK_ERRORS = (
    requests.exceptions.RequestException,
    json.JSONDecodeError,
)
DATA_VALIDATION_ERRORS = (
    ValueError,
    pd.errors.ParserError,
    DataSchemaError,
    DataUnavailableError,
)
_DATA_FETCH_ERRORS = NETWORK_ERRORS + DATA_VALIDATION_ERRORS
# poe.BotError 在部分 Poe 导入上下文不可用，必须惰性获取。
def _fetch_or_bot_errors():
    try:
        bot_error = poe.BotError
    except AttributeError:
        bot_error = None
    return _DATA_FETCH_ERRORS + ((bot_error,) if isinstance(bot_error, type) else ())

def _secid_to_sina(secid):
    market, code = secid.split(".")
    return ("sh" if market == "1" else "sz") + code

def _secid_to_sohu_index(secid):
    _market, code = secid.split(".")
    if code.startswith("H"):
        code = code[1:].zfill(6)
    return "zs_" + code


def _vendor_secid_candidates(secid):
    aliases = CN_VENDOR_SECID_ALIASES.get(secid)
    if aliases:
        return list(dict.fromkeys(aliases))
    return [secid]

def _fetch_cn_eastmoney(secid):
    end_date = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
           f"&klt=101&fqt=1&beg=20050101&end={end_date}&lmt=10000")
    resp = _session.get(url, timeout=30,
                        headers={"Referer": "https://quote.eastmoney.com/"})
    resp.raise_for_status()
    data = resp.json()
    inner = data.get("data") if isinstance(data, dict) else None
    if inner is None:
        raise ValueError(f"EastMoney returned null data for {secid}")
    klines = inner.get("klines")
    if not klines:
        raise ValueError(f"EastMoney returned empty klines for {secid}")
    rows = [{"date": p[0], "close": float(p[2])} for line in klines for p in [line.split(",")]]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()

def _fetch_cn_eastmoney_amount(secid, beg=CN_SA_VOLUME_HISTORY_BEG, lmt=10000):
    end_date = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           f"&fields2=f51,f52,f53,f54,f55,f56,f57"
           f"&klt=101&fqt=1&beg={beg}&end={end_date}&lmt={int(lmt)}")
    resp = _session.get(url, timeout=30,
                        headers={"Referer": "https://quote.eastmoney.com/"})
    resp.raise_for_status()
    data = resp.json()
    inner = data.get("data") if isinstance(data, dict) else None
    if inner is None:
        raise ValueError(f"EastMoney returned null data for {secid}")
    klines = inner.get("klines")
    if not klines:
        raise ValueError(f"EastMoney returned empty klines for {secid}")
    rows = []
    for line in klines:
        p = line.split(",")
        rows.append({
            "date": p[0],
            "close": float(p[2]),
            "volume": float(p[5]),
            "amount": float(p[6]),
        })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()

def _fetch_cn_sina(secid):
    symbol = _secid_to_sina(secid)
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
           f"/CN_MarketData.getKLineData"
           f"?symbol={symbol}&scale=240&ma=no&datalen=10000")
    resp = _session.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data or not isinstance(data, list) or len(data) == 0:
        raise ValueError(f"Sina returned empty data for {symbol}")
    rows = [{"date": item["day"], "close": float(item["close"])} for item in data]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()

def _fetch_cn_sina_amount_proxy(secid):
    symbol = _secid_to_sina(secid)
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
           f"/CN_MarketData.getKLineData"
           f"?symbol={symbol}&scale=240&ma=no&datalen=10000")
    resp = _session.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data or not isinstance(data, list) or len(data) == 0:
        raise ValueError(f"Sina returned empty data for {symbol}")
    rows = []
    for item in data:
        rows.append({
            "date": item["day"],
            "close": float(item["close"]),
            "volume": float(item.get("volume", 0) or 0),
            "amount": float(item.get("volume", 0) or 0),
            "source": "Sina volume proxy",
        })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()

def _fetch_cn_sohu_amount_symbol(symbol, beg=CN_SA_VOLUME_HISTORY_BEG, lmt=300, source_name="Sohu amount"):
    end_date = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
    url = (f"https://q.stock.sohu.com/hisHq"
           f"?code={symbol}&start={beg}&end={end_date}&stat=1&order=D&period=d&rt=json")
    resp = _session.get(url, timeout=30, headers={"Referer": "https://q.stock.sohu.com/"})
    resp.raise_for_status()
    data = resp.json()
    if not data or not isinstance(data, list):
        raise ValueError(f"Sohu returned empty data for {symbol}")
    first = data[0]
    if not isinstance(first, dict) or first.get("status") != 0 or not first.get("hq"):
        raise ValueError(f"Sohu returned unavailable data for {symbol}: {first.get('msg') if isinstance(first, dict) else first}")
    rows = []
    for item in first["hq"]:
        if len(item) < 9:
            continue
        rows.append({
            "date": item[0],
            "close": float(item[2]),
            "volume": float(item[7]),
            "amount": float(item[8]),
            "source": source_name,
        })
    if not rows:
        raise ValueError(f"Sohu returned no usable rows for {symbol}")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index().tail(int(lmt))

def _fetch_cn_sohu_amount(secid, beg=CN_SA_VOLUME_HISTORY_BEG, lmt=300):
    symbol = _secid_to_sohu_index(secid)
    return _fetch_cn_sohu_amount_symbol(symbol, beg=beg, lmt=lmt, source_name="Sohu amount")

def _fetch_cn_sohu_fund_amount(secid, beg=CN_SA_VOLUME_HISTORY_BEG, lmt=300):
    _market, code = secid.split(".")
    symbol = "cn_" + code
    return _fetch_cn_sohu_amount_symbol(symbol, beg=beg, lmt=lmt, source_name="Sohu fund amount")

def _fetch_zz2000_etf_amount_proxy(beg=CN_SA_VOLUME_HISTORY_BEG, lmt=300):
    candidates = []
    errors = []
    for secid, name in CN_SA_VOLUME_ZZ2000_ETF_PROXY_SECIDS:
        try:
            df = _fetch_cn_sohu_fund_amount(secid, beg=beg, lmt=lmt)
            amount = pd.to_numeric(df["amount"], errors="coerce").dropna()
            if df.empty or amount.empty:
                errors.append(f"{secid}: empty")
                continue
            candidates.append({
                "secid": secid,
                "name": name,
                "df": df,
                "latest_date": df.index[-1],
                "latest_amount": float(amount.iloc[-1]),
            })
        except _DATA_FETCH_ERRORS as exc:
            errors.append(f"{secid}: {exc}")
    if not candidates:
        raise DataUnavailableError(f"ZZ2000 ETF proxy unavailable; tried {' | '.join(errors[-3:])}")
    latest_date = max(item["latest_date"] for item in candidates)
    same_date = [item for item in candidates if item["latest_date"] == latest_date]
    selected = max(same_date, key=lambda item: item["latest_amount"])
    code = selected["secid"].split(".")[-1]
    source = f"Sohu ETF amount proxy {code}"
    out = selected["df"].copy()
    out["source"] = source
    out["proxy_name"] = selected["name"]
    out["proxy_secid"] = selected["secid"]
    return out, source

def _fetch_cn_qq_kline(secid, datalen=2000):
    market, code = secid.split(".")
    symbol = ("sh" if market == "1" else "sz") + code
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
           f"?param={symbol},day,,,{datalen}")
    resp = _session.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data")
    if not isinstance(data, dict) or symbol not in data or "day" not in data[symbol]:
        raise ValueError(f"QQ returned empty data for {symbol}")
    day = data[symbol]["day"]
    if not day:
        raise ValueError(f"QQ returned empty kline for {symbol}")
    rows = [{"date": item[0], "close": float(item[2])} for item in day]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()

def _fetch_cn_qq_amount_proxy(secid, datalen=10000):
    market, code = secid.split(".")
    symbol = ("sh" if market == "1" else "sz") + code
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
           f"?param={symbol},day,,,{datalen}")
    resp = _session.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data")
    if not isinstance(data, dict) or symbol not in data or "day" not in data[symbol]:
        raise ValueError(f"QQ returned empty data for {symbol}")
    day = data[symbol]["day"]
    if not day:
        raise ValueError(f"QQ returned empty kline for {symbol}")
    rows = []
    for item in day:
        volume = float(item[5]) if len(item) > 5 and item[5] not in ("", None) else 0.0
        rows.append({
            "date": item[0],
            "close": float(item[2]),
            "volume": volume,
            "amount": volume,
            "source": "QQ volume proxy",
        })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()

def _csindex_detail_page_code(index_code):
    special = {
        "H20955": "930955",
        "H30269": "930769",
        "H11077": "931077",
    }
    if index_code in special:
        return special[index_code]
    if index_code.startswith("H"):
        body = index_code[1:]
        if body.isdigit():
            return body.zfill(6)
    return index_code

def _fetch_cn_csindex(index_code, _max_retries=3):
    # 动态降级: 连续失败>=2次后只尝试1次, 避免拖慢整体
    effective_retries = 1 if _get_csindex_consecutive_fails() >= 2 else _max_retries
    detail_code = _csindex_detail_page_code(index_code)
    detail_url = f"https://www.csindex.com.cn/indices/index-detail/{detail_code}"
    url = (f"https://www.csindex.com.cn/csindex-home/perf/index-perf"
           f"?indexCode={index_code}&startDate=20050101"
           f"&endDate={(datetime.now() + timedelta(days=30)).strftime('%Y%m%d')}")
    doc_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    api_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": detail_url,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "X-Requested-With": "XMLHttpRequest",
    }
    last_err = None
    for attempt in range(effective_retries):
        if attempt > 0:
            time.sleep(2 * attempt)  # 递增延迟: 2s, 4s
        with requests.Session() as sess:
            try:
                sess.get(detail_url, timeout=15, headers=doc_headers)
            except requests.exceptions.RequestException:
                pass
            resp = sess.get(url, timeout=30, headers=api_headers)
        # csindex CDN/WAF有时返回403但响应体仍含有效数据，先尝试解析JSON
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            last_err = requests.exceptions.HTTPError(
                f"csindex returned HTTP {resp.status_code} non-JSON for {index_code}")
            if resp.status_code == 403:
                continue  # 403且无法解析JSON → 重试
            resp.raise_for_status()
            raise ValueError(f"csindex returned non-JSON for {index_code}")
        if data.get("data"):
            # 有效数据，不管HTTP状态码; 过滤None条目防止TypeError
            try:
                rows = [{"date": item["tradeDate"], "close": float(item["close"])}
                        for item in data["data"] if item is not None]
            except (TypeError, KeyError, ValueError) as e:
                last_err = e
                if resp.status_code == 403:
                    continue
                raise
            if rows:
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                _reset_csindex_consecutive_fails()  # 成功, 重置计数
                return df.set_index("date").sort_index()
        # JSON有效但无数据
        last_err = ValueError(f"csindex returned no data for {index_code} (HTTP {resp.status_code})")
        if resp.status_code == 403:
            continue  # 403且无数据 → 重试
        resp.raise_for_status()
        raise last_err
    # 所有重试耗尽
    _increment_csindex_consecutive_fails()
    raise last_err or ValueError(f"csindex failed after {effective_retries} retries for {index_code}")

def _fetch_cn_csindex_amount(secid, beg=CN_SA_VOLUME_HISTORY_BEG, lmt=10000, _max_retries=2):
    index_code = CN_CSI_AMOUNT_INDEX_CODES.get(secid)
    if not index_code:
        raise ValueError(f"no csindex amount mapping for {secid}")
    detail_code = _csindex_detail_page_code(index_code)
    detail_url = f"https://www.csindex.com.cn/indices/index-detail/{detail_code}"
    end_date = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
    url = (
        f"https://www.csindex.com.cn/csindex-home/perf/index-perf"
        f"?indexCode={index_code}&startDate={beg}&endDate={end_date}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": detail_url,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
    }
    last_err = None
    for attempt in range(int(_max_retries)):
        if attempt > 0:
            time.sleep(1.5 * attempt)
        try:
            with requests.Session() as sess:
                try:
                    sess.get(detail_url, timeout=10, headers=headers)
                except requests.exceptions.RequestException:
                    pass
                resp = sess.get(url, timeout=20, headers=headers)
            data = resp.json()
            rows = []
            for item in data.get("data", []) if isinstance(data, dict) else []:
                if not item:
                    continue
                trading_value = item.get("tradingValue")
                if trading_value in (None, ""):
                    continue
                rows.append({
                    "date": item.get("tradeDate"),
                    "close": float(item.get("close")),
                    "volume": float(item.get("tradingVol", 0) or 0),
                    "amount": float(trading_value),
                    "source": f"CSIndex official amount {index_code}",
                })
            if rows:
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                return df.set_index("date").sort_index().tail(int(lmt))
            last_err = ValueError(f"CSIndex returned no tradingValue rows for {index_code} (HTTP {resp.status_code})")
            if resp.status_code != 403:
                resp.raise_for_status()
        except _DATA_FETCH_ERRORS as exc:
            last_err = exc
    raise last_err or ValueError(f"CSIndex amount failed for {index_code}")

def _fetch_cn_csindex_with_candidates(index_code):
    candidates = CN_CSINDEX_CANDIDATES.get(index_code, [index_code])
    last_err = None
    attempts = []
    for candidate in candidates:
        try:
            df = _fetch_cn_csindex(candidate)
            if df is not None and len(df) > 50:
                source = "csindex" if candidate == index_code else f"csindex:{candidate}"
                return df, source
        except poe.BotError:
            raise
        except _DATA_FETCH_ERRORS as e:
            last_err = e
            attempts.append(f"{candidate}:{e}")
            time.sleep(1)
    attempts_text = " | ".join(attempts[-4:]) if attempts else str(last_err)
    raise last_err or ValueError(f"csindex returned no usable data for {index_code}; tried: {attempts_text}")

def _fetch_cn_h_proxy(secid):
    proxy_secid = CN_H_PROXY_SECIDS.get(secid)
    if not proxy_secid:
        raise ValueError(f"no H proxy configured for {secid}")
    last_err = None
    for name, fetcher in [
        ("Sina-proxy", lambda s=proxy_secid: _fetch_cn_sina(s)),
        ("EastMoney-proxy", lambda s=proxy_secid: _fetch_cn_eastmoney(s)),
    ]:
        try:
            df = fetcher()
            if df is not None and len(df) > 50:
                return df, f"{name}:{proxy_secid}"
        except _DATA_FETCH_ERRORS as e:
            last_err = e
            time.sleep(1)
    raise last_err or ValueError(f"H proxy returned no usable data for {secid} -> {proxy_secid}")


def _stitch_cn_proxy_returns(base_df, proxy_df):
    """Extend a total-return series with proxy price-index returns after the overlap date."""
    if base_df is None or len(base_df) == 0:
        return proxy_df
    if proxy_df is None or len(proxy_df) == 0:
        return base_df
    if "close" not in base_df.columns or "close" not in proxy_df.columns:
        return base_df

    base = base_df[["close"]].copy().sort_index()
    proxy = proxy_df[["close"]].copy().sort_index()
    overlap = base.index.intersection(proxy.index)
    if len(overlap) == 0:
        return base
    if base.index.max() >= proxy.index.max():
        return base

    anchor = overlap[-1]
    stitched = base.copy()
    proxy_tail = proxy.loc[anchor:, "close"].dropna()
    if len(proxy_tail) <= 1:
        return stitched

    last_close = float(base.loc[anchor, "close"])
    base_latest = base.index.max()
    rows = []
    prev_proxy = float(proxy_tail.iloc[0])
    for dt, px in proxy_tail.iloc[1:].items():
        px = float(px)
        if prev_proxy <= 0:
            prev_proxy = px
            continue
        last_close *= px / prev_proxy
        if dt > base_latest:
            rows.append((dt, last_close))
        prev_proxy = px
    if rows:
        ext = pd.DataFrame(rows, columns=["date", "close"]).set_index("date")
        stitched = pd.concat([stitched, ext], axis=0)
    return stitched[~stitched.index.duplicated(keep="last")].sort_index()


def _project_proxy_realtime_close(df, proxy_df, realtime_proxy_close):
    """Map a live proxy level to the strategy series by applying the latest proxy return."""
    if df is None or len(df) == 0 or proxy_df is None or len(proxy_df) == 0:
        return realtime_proxy_close
    if "close" not in df.columns or "close" not in proxy_df.columns:
        return realtime_proxy_close

    last_date = df.index[-1]
    proxy_hist = proxy_df.loc[:last_date, "close"].dropna()
    if len(proxy_hist) == 0:
        return realtime_proxy_close

    prev_proxy_close = float(proxy_hist.iloc[-1])
    last_close = float(df.iloc[-1]["close"])
    if prev_proxy_close <= 0 or last_close <= 0:
        return realtime_proxy_close
    return last_close * (float(realtime_proxy_close) / prev_proxy_close)


def _fetch_cn_realtime_close(secid):
    """从东方财富实时行情API获取指数/ETF最新收盘价(收盘后)或现价(盘中)。
    返回 float(收盘价) 或 None(失败/非交易日)。
    仅在日K线API缺失当天数据时用于补充。"""

    proxy_secid = CN_H_PROXY_SECIDS.get(secid)
    candidate_secids = [proxy_secid] if proxy_secid else _vendor_secid_candidates(secid)
    for candidate_secid in candidate_secids:
        try:
            url = (f"https://push2.eastmoney.com/api/qt/stock/get"
                   f"?secid={candidate_secid}"
                   f"&fields=f43,f44,f45,f46,f60"
                   f"&ut=fa5fd1943c7b386f172d6893dbfba10b")
            # 实时快照只作补价，不能让 requests.Session 的重试把查询拖到 Poe 超时。
            resp = requests.get(url, timeout=5,
                                headers={"Referer": "https://quote.eastmoney.com/"})
            resp.raise_for_status()
            data = resp.json().get("data")
            if not data:
                continue
            f43 = data.get("f43")  # 最新价 (×100)
            f46 = data.get("f46")  # 今开 (×100)
            if f43 is None or f46 is None or f43 == "-" or f46 == "-":
                continue
            # f46(今开)为0或无效说明今天没开盘(非交易日)
            if float(f46) <= 0:
                continue
            return float(f43) / 100.0
        except _DATA_FETCH_ERRORS:
            continue
    return None

def _supplement_today_close(df, secid, bj_today, msg=None):
    """当日K线缺少今天数据时，用实时行情API补充今天的收盘价。
    df: 已有的K线DataFrame (index=date, columns含'close')
    secid: 东方财富secid
    bj_today: 今天的date对象 (北京时间)
    返回补充后的df(可能不变)。"""
    if df is None or len(df) == 0:
        return df
    last_date = df.index[-1].date() if hasattr(df.index[-1], 'date') else df.index[-1]
    # 已有今天数据，不需要补充
    if last_date >= bj_today:
        return df
    # 非工作日不补充 (周末)
    if bj_today.weekday() >= 5:
        return df
    if not _is_cn_required_close_day(bj_today):
        return df
    bj_now = beijing_now()
    if bj_today == bj_now.date() and not _can_use_cn_realtime_snapshot_at(bj_now):
        return df
    # 尝试获取实时价格
    realtime_close = _fetch_cn_realtime_close(secid)
    if realtime_close is None:
        return df
    if secid in CN_H_PROXY_SECIDS:
        try:
            proxy_df, _ = _fetch_cn_h_proxy(secid)
            realtime_close = _project_proxy_realtime_close(df, proxy_df, realtime_close)
        except _DATA_FETCH_ERRORS:
            pass
    # 补充今天的数据行
    today_ts = pd.Timestamp(bj_today)
    new_row = pd.DataFrame([{"close": realtime_close}], index=pd.DatetimeIndex([today_ts], name=df.index.name))
    # 保留原有列名
    for col in df.columns:
        if col != "close" and col not in new_row.columns:
            new_row[col] = np.nan
    # P2-1修复: 标记实时补价行，便于下游区分strict/live数据
    new_row['is_live_bar'] = True
    new_row['source'] = (
        f"EastMoney realtime proxy:{CN_H_PROXY_SECIDS[secid]}"
        if secid in CN_H_PROXY_SECIDS else
        "EastMoney realtime snapshot"
    )
    df = pd.concat([df, new_row])
    if 'is_live_bar' not in df.columns:
        df['is_live_bar'] = False
    df['is_live_bar'] = df['is_live_bar'].where(df['is_live_bar'].notna(), False).astype(bool)
    if msg:
        msg.write(f"  ↳ 实时补充: {bj_today.strftime('%Y-%m-%d')} close={realtime_close:.2f} [snapshot]\n")
    return df


def _add_cn_bond_column(cn_close, msg=None, context="Sub-A", strict=False, include_live_snapshot=False):
    cn_close_with_bond = cn_close.copy()
    if CN_BOND_CODE in cn_close_with_bond.columns:
        return cn_close_with_bond
    try:
        bond_df, source = fetch_cn_kline(CN_BOND_CODE)
        if include_live_snapshot:
            before_latest = pd.Timestamp(bond_df.index.max()).normalize() if len(bond_df) > 0 else None
            bond_df = _supplement_today_close(bond_df, CN_BOND_CODE, beijing_now().date(), msg)
            after_latest = pd.Timestamp(bond_df.index.max()).normalize() if len(bond_df) > 0 else None
            if before_latest is not None and after_latest is not None and after_latest > before_latest:
                source = f"{source}+realtime-proxy"
        bond_close = pd.to_numeric(bond_df["close"], errors="coerce").dropna()
        if strict:
            expected_date = pd.Timestamp(cn_close_with_bond.index.max()).normalize()
            latest_bond_date = pd.Timestamp(bond_close.index.max()).normalize() if not bond_close.empty else None
            if latest_bond_date is None or latest_bond_date < expected_date:
                latest_text = latest_bond_date.date().isoformat() if latest_bond_date is not None else "missing"
                raise poe.BotError(
                    f"{context}: {CN_BOND_NAME}数据过期，"
                    f"latest={latest_text}, expected={expected_date.date().isoformat()}"
                )
        cn_close_with_bond[CN_BOND_CODE] = bond_df["close"].reindex(cn_close_with_bond.index)
        cn_close_with_bond = cn_close_with_bond.ffill()
        if msg is not None:
            msg.write(
                f"  {CN_BOND_NAME}: {bond_df.index[-1].strftime('%Y-%m-%d')} [{source}]\n"
            )
    except _fetch_or_bot_errors() as exc:
        if strict:
            raise poe.BotError(
                f"{context}: {CN_BOND_NAME}({CN_BOND_CODE})数据获取失败，正式路径不能缺少国债避险通道: "
                f"{_short_error(exc)}"
            ) from exc
        if msg is not None:
            msg.write(
                f"  ⚠️ {context}: {CN_BOND_NAME}({CN_BOND_CODE})数据获取失败，"
                f"Sub-A本次将缺少国债避险通道: {_short_error(exc)}\n"
            )
    return cn_close_with_bond


def _cn_cache_path(secid):
    base_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    cache_dir = os.path.join(base_dir, ".cn_official_cache")
    return os.path.join(cache_dir, f"{secid.replace('.', '_')}.csv")

def _save_cn_official_cache(secid, df):
    if df is None or len(df) == 0 or "close" not in df.columns:
        return
    path = _cn_cache_path(secid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df[["close"]].sort_index().to_csv(path, index_label="date", encoding="utf-8")

def _load_cn_official_cache(secid):
    path = _cn_cache_path(secid)
    if not os.path.exists(path):
        raise FileNotFoundError(f"no cache for {secid}")
    df = pd.read_csv(path)
    if "date" not in df.columns or "close" not in df.columns or len(df) == 0:
        raise ValueError(f"invalid cache for {secid}")
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = df["close"].astype(float)
    return df.set_index("date").sort_index()


def _load_recent_cn_official_cache(secid, min_rows=50):
    df = _load_cn_official_cache(secid)
    if df is None or len(df) <= int(min_rows):
        raise ValueError(f"cache rows={0 if df is None else len(df)} <= {min_rows}")
    latest = pd.Timestamp(df.index[-1]).normalize()
    required = _latest_cn_required_close_date()
    if latest < required:
        raise ValueError(f"cache latest {latest.date().isoformat()} < required {required.date().isoformat()}")
    return df


def _cn_strategy_data_path():
    base_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    return os.path.join(base_dir, "mnt_strategy_data_cn.csv")


def _load_cn_strategy_data_cache(secid):
    path = _cn_strategy_data_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"no local strategy csv: {path}")
    df = pd.read_csv(path)
    if "date" not in df.columns or secid not in df.columns:
        raise ValueError(f"local strategy csv missing {secid}")
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"]),
        "close": pd.to_numeric(df[secid], errors="coerce"),
    }).dropna(subset=["close"])
    if out.empty:
        raise ValueError(f"local strategy csv has no valid rows for {secid}")
    return out.set_index("date").sort_index()


def _cn_frame_range_text(df):
    if df is None or len(df) == 0:
        return "empty"
    try:
        return f"{pd.Timestamp(df.index.min()).strftime('%Y-%m-%d')}~{pd.Timestamp(df.index.max()).strftime('%Y-%m-%d')}"
    except Exception:
        return "unknown-range"


def _ensure_cn_history_frame(secid, df, source, min_rows=CN_MIN_HISTORY_ROWS, write=None):
    rows = 0 if df is None else len(df)
    if df is not None and rows >= min_rows:
        return df, source
    name = CN_NAMES.get(secid, secid)
    range_text = _cn_frame_range_text(df)
    try:
        fallback = _load_cn_strategy_data_cache(secid)
        if len(fallback) >= min_rows:
            if write is not None:
                write(
                    f"  ↳ 历史兜底: {name} 在线源 {source} 仅{rows}行({range_text})，"
                    f"改用 mnt_strategy_data_cn.csv {len(fallback)}行 "
                    f"{_cn_frame_range_text(fallback)}\n"
                )
            return fallback, f"{source}->local-cache:mnt_strategy_data_cn.csv"
    except (OSError, ValueError, KeyError) as cache_err:
        fallback_error = _short_error(cache_err)
    else:
        fallback_error = f"local cache rows={len(fallback)} < {min_rows}"
    raise poe.BotError(
        f"A股历史数据不足: {name}({secid}) 在线源 {source} 仅{rows}行({range_text})；"
        f"本地历史兜底不可用: {fallback_error}。已停止，避免把实时快照当历史K线生成错误信号。"
    )

def _price_column_frame(df, source_col, output_col):
    if df is None or len(df) == 0:
        raise ValueError(f"{output_col} price frame is empty")
    if source_col in df.columns:
        series = df[source_col]
    elif output_col in df.columns:
        series = df[output_col]
    else:
        raise ValueError(f"{output_col} price frame missing {source_col} column")
    return pd.to_numeric(series, errors="coerce").rename(output_col).to_frame()

def _build_cn_stock_close_frame(cn_raw):
    frames = [
        _price_column_frame(cn_raw[secid], "close", secid)
        for secid in CN_STOCK_CODES
    ]
    return pd.concat(frames, axis=1).ffill().dropna(subset=CN_STOCK_CODES)

def _build_cn_dk_close_frame(dk_dfs):
    frames = [
        _price_column_frame(dk_dfs[col], col, col)
        for col in CN_DK_COLS
    ]
    out = pd.concat(frames, axis=1).ffill().dropna(subset=CN_DK_COLS)
    formal_start = max(CN_DK_PUBLICATION_DATES[col] for col in CN_DK_COLS)
    return out.loc[out.index >= formal_start]

def _fetch_cn_dk_price_index(idx_code, secid):
    attempts = []
    for src_name, fetcher in [
        ("Sina", lambda: _fetch_cn_sina(secid)),
        ("EastMoney", lambda: _fetch_cn_eastmoney(secid)),
        ("csindex", lambda: _fetch_cn_csindex(idx_code)),
    ]:
        try:
            df = fetcher()
            if df is not None and len(df) > 50:
                return df, src_name
            attempts.append(f"{src_name}:insufficient")
        except _DATA_FETCH_ERRORS as e:
            attempts.append(f"{src_name}:{e}")
            time.sleep(0.2)
    raise ValueError(f"DK price index source failed for {secid}/{idx_code}: {'; '.join(attempts)}")

def fetch_cn_kline(secid):
    """
    修改为由代理价格指数读取来切换数据源（放弃从csindex读取以规避其实时失效和反爬问题）。
    全收益指数H打头的代码会被映射到实时支持良好的价格指数代码。
    """
    code = secid.split('.')[1] if '.' in secid else secid
    last_err = None
    attempts = []

    if secid in CN_CSINDEX_PRICE_INDEX_CODES:
        index_code = CN_CSINDEX_PRICE_INDEX_CODES[secid]
        try:
            df = _load_recent_cn_official_cache(secid)
            cache_date = df.index[-1].strftime("%Y-%m-%d")
            return df, f"csindex-cache:{cache_date}"
        except (OSError, ValueError, KeyError) as cache_err:
            attempts.append(f"recent-cache:{cache_err}")
        for vendor_secid in _vendor_secid_candidates(secid):
            try:
                df = _fetch_cn_eastmoney(vendor_secid)
                if df is not None and len(df) > 50:
                    return df, f"EastMoney:{vendor_secid}"
            except _DATA_FETCH_ERRORS as e:
                last_err = e
                attempts.append(f"EastMoney:{vendor_secid}:{e}")
                time.sleep(1)
        try:
            df = _fetch_cn_sina(secid)
            if df is not None and len(df) > 50:
                return df, "Sina"
        except _DATA_FETCH_ERRORS as e:
            last_err = e
            attempts.append(f"Sina:{e}")
            time.sleep(1)
        try:
            df = _load_cn_official_cache(secid)
            if df is not None and len(df) > 50:
                cache_date = df.index[-1].strftime("%Y-%m-%d")
                return df, f"csindex-cache:{cache_date}"
        except (OSError, ValueError, KeyError) as cache_err:
            attempts.append(f"cache:{cache_err}")
        try:
            df = _fetch_cn_csindex(index_code)
            if df is not None and len(df) > 50:
                _save_cn_official_cache(secid, df)
                return df, f"csindex:{index_code}"
        except _DATA_FETCH_ERRORS as e:
            last_err = e
            attempts.append(f"csindex:{e}")
            time.sleep(1)
            try:
                df = _load_cn_official_cache(secid)
                if df is not None and len(df) > 50:
                    cache_date = df.index[-1].strftime("%Y-%m-%d")
                    return df, f"csindex-cache:{cache_date}"
            except (OSError, ValueError, KeyError) as cache_err:
                attempts.append(f"cache:{cache_err}")

    elif code.startswith('H'):
        base_df = None
        base_source = None
        proxy_df = None
        proxy_source = None

        try:
            proxy_df, proxy_source = _fetch_cn_h_proxy(secid)
        except _DATA_FETCH_ERRORS as e:
            last_err = e
            attempts.append(f"proxy:{e}")
            time.sleep(0.2)

        try:
            base_df = _load_cn_official_cache(secid)
            if base_df is not None and len(base_df) > 50:
                cache_date = base_df.index[-1].strftime("%Y-%m-%d")
                base_source = f"csindex-cache:{cache_date}"
        except (OSError, ValueError, KeyError) as cache_err:
            attempts.append(f"cache:{cache_err}")

        if proxy_df is not None and len(proxy_df) > 50 and base_df is not None and len(base_df) > 50:
            stitched = _stitch_cn_proxy_returns(base_df, proxy_df)
            return stitched, f"{base_source}+{proxy_source}"

        try:
            official_df, official_source = _fetch_cn_csindex_with_candidates(code)
            if official_df is not None and len(official_df) > 50:
                _save_cn_official_cache(secid, official_df)
                if base_df is None or len(base_df) <= 50 or official_df.index[-1] > base_df.index[-1]:
                    base_df = official_df
                    base_source = official_source
        except _DATA_FETCH_ERRORS as e:
            last_err = e
            attempts.append(f"csindex:{e}")
            time.sleep(0.2)

        if base_df is not None and len(base_df) > 50:
            if proxy_df is not None and len(proxy_df) > 50:
                stitched = _stitch_cn_proxy_returns(base_df, proxy_df)
                return stitched, f"{base_source}+{proxy_source}"
            return base_df, base_source
        if proxy_df is not None and len(proxy_df) > 50:
            return proxy_df, proxy_source
    else:
        for name, fetcher in [
            ("Sina", lambda: _fetch_cn_sina(secid)),
            ("EastMoney", lambda: _fetch_cn_eastmoney(secid)),
        ]:
            try:
                df = fetcher()
                if df is not None and len(df) > 50:
                    return df, name
            except _DATA_FETCH_ERRORS as e:
                last_err = e
                attempts.append(f"{name}:{e}")
                time.sleep(1)

    attempts_text = " | ".join(attempts[-5:]) if attempts else str(last_err)
    raise poe.BotError(f"获取A股数据失败 ({secid}): {last_err}; tried: {attempts_text}")

def fetch_volume_emotion():
    """获取上证指数近期成交量并计算情绪状态（仅用于信息展示）。
    返回 (emotion, consec_below, consec_above, vol_data_ok)
    emotion: +1=乐观, -1=悲观, 0=中性
    consec_below: 当前连续缩量天数
    consec_above: 当前连续放量天数
    """
    try:
        end_date = (datetime.now() + timedelta(days=5)).strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
        url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
               f"?secid={CN_VOL_MONITOR_SECID}"
               f"&fields1=f1,f2,f3,f4,f5,f6"
               f"&fields2=f51,f52,f53,f54,f55,f56,f57"
               f"&klt=101&fqt=1&beg={start_date}&end={end_date}&lmt=40")
        resp = _session.get(url, timeout=15,
                            headers={"Referer": "https://quote.eastmoney.com/"})
        resp.raise_for_status()
        klines = resp.json()["data"]["klines"]
        volumes = pd.Series([float(line.split(",")[5]) for line in klines])
        vol_ma = volumes.rolling(CN_VOL_EMOTION_MA).mean()
        vol_diff = volumes - vol_ma
        # 从最新一天往回数连续缩量/放量天数
        consec_below, consec_above = 0, 0
        for i in range(len(vol_diff) - 1, -1, -1):
            if pd.isna(vol_diff.iloc[i]):
                break
            if vol_diff.iloc[i] < 0:
                if consec_above > 0:
                    break
                consec_below += 1
            else:
                if consec_below > 0:
                    break
                consec_above += 1
        emotion = 0
        if consec_below >= CN_VOL_EMOTION_BEAR:
            emotion = -1
        elif consec_above >= CN_VOL_EMOTION_BULL:
            emotion = 1
        return emotion, consec_below, consec_above, True
    except Exception:
        return 0, 0, 0, False

def check_knife_catch(cn_close, codes, names):
    """检查各ETF近N日涨跌幅，标记"接刀"风险（仅用于信息展示）。
    返回 dict: {code: {"ret3d": float, "is_knife": bool}} 以及 ok 标志
    """
    try:
        result = {}
        for code in codes:
            if code not in cn_close.columns:
                continue
            series = cn_close[code].dropna()
            if len(series) < CN_KNIFE_WINDOW + 1:
                continue
            ret_nd = series.iloc[-1] / series.iloc[-(CN_KNIFE_WINDOW + 1)] - 1
            result[code] = {
                "ret3d": ret_nd,
                "is_knife": ret_nd < CN_KNIFE_THRESHOLD,
                "name": names.get(code, code),
            }
        return result, True
    except Exception:
        return {}, False

def _consecutive_below_amount(amount, ma):
    amount = pd.Series(amount, dtype=float).sort_index()
    ratio = amount / amount.rolling(int(ma)).mean()
    below = ratio < 1.0
    streak = []
    cur = 0
    for val in below.fillna(False):
        cur = cur + 1 if bool(val) else 0
        streak.append(cur)
    return pd.Series(streak, index=amount.index, dtype=float)

def _build_consecutive_below_amount_signal(rule_specs, mode="or"):
    if mode not in ("or", "and"):
        raise ValueError("mode must be 'or' or 'and'.")
    frames = []
    signals = []
    for name, spec in rule_specs.items():
        amount = spec["amount"]
        ma = int(spec["ma"])
        days = int(spec["days"])
        streak = _consecutive_below_amount(amount, ma)
        sig = streak >= days
        frames.append(pd.DataFrame({
            f"{name}_amount": pd.Series(amount, dtype=float).sort_index(),
            f"{name}_streak": streak,
            f"{name}_signal": sig,
        }))
        signals.append(sig.rename(name))
    if not signals:
        return pd.Series(dtype=bool), pd.DataFrame()
    signal_df = pd.concat(signals, axis=1).fillna(False).astype(bool).sort_index()
    signal = signal_df.any(axis=1) if mode == "or" else signal_df.all(axis=1)
    feature = pd.concat(frames, axis=1).reindex(signal.index)
    feature["combined_signal"] = signal
    return signal.astype(bool), feature

def _build_amount_ratio_below_ma_signal(numerator_amount, denominator_amount, ma, days):
    pair = pd.concat(
        [
            pd.Series(numerator_amount, dtype=float).sort_index().rename("numerator"),
            pd.Series(denominator_amount, dtype=float).sort_index().rename("denominator"),
        ],
        axis=1,
    ).dropna()
    pair = pair[pair["denominator"] > 0]
    ratio = (pair["numerator"] / pair["denominator"]).rename("severe_ratio_value")
    ratio_ma = ratio.rolling(int(ma)).mean().rename("severe_ratio_ma_value")
    streak = _consecutive_below_amount(ratio, ma).rename("severe_ratio_streak")
    signal = (streak >= int(days)).rename("severe_ratio_signal")
    feature = pd.concat([ratio, ratio_ma, streak, signal], axis=1)
    return signal.astype(bool), feature

def _fetch_cn_amount_with_fallback(secid, label, beg=CN_SA_VOLUME_HISTORY_BEG, lmt=10000):
    errors = []
    if secid == CN_SA_VOLUME_ZZ2000_SECID:
        sources = [
            ("CSIndex official amount", lambda: _fetch_cn_csindex_amount(secid, beg=beg, lmt=lmt)),
            ("ZZ2000 ETF proxy", lambda: _fetch_zz2000_etf_amount_proxy(beg=beg, lmt=lmt)),
            ("Sohu amount", lambda: _fetch_cn_sohu_amount(secid, beg=beg, lmt=lmt)),
            ("Sina volume proxy", lambda: _fetch_cn_sina_amount_proxy(secid)),
            ("QQ volume proxy", lambda: _fetch_cn_qq_amount_proxy(secid, datalen=lmt)),
            ("EastMoney amount", lambda: _fetch_cn_eastmoney_amount(secid, beg=beg, lmt=lmt)),
        ]
    elif secid == CN_SA_VOLUME_CYB_SECID:
        sources = [
            ("Sohu amount", lambda: _fetch_cn_sohu_amount(secid, beg=beg, lmt=lmt)),
            ("EastMoney amount", lambda: _fetch_cn_eastmoney_amount(secid, beg=beg, lmt=lmt)),
            ("QQ volume proxy", lambda: _fetch_cn_qq_amount_proxy(secid, datalen=lmt)),
            ("Sina volume proxy", lambda: _fetch_cn_sina_amount_proxy(secid)),
        ]
    else:
        sources = [
            ("Sina volume proxy", lambda: _fetch_cn_sina_amount_proxy(secid)),
            ("QQ volume proxy", lambda: _fetch_cn_qq_amount_proxy(secid, datalen=lmt)),
            ("CSIndex official amount", lambda: _fetch_cn_csindex_amount(secid, beg=beg, lmt=lmt)),
            ("Sohu amount", lambda: _fetch_cn_sohu_amount(secid, beg=beg, lmt=lmt)),
            ("EastMoney amount", lambda: _fetch_cn_eastmoney_amount(secid, beg=beg, lmt=lmt)),
        ]
    for source_name, fetcher in sources:
        try:
            value = fetcher()
            if isinstance(value, tuple):
                df, source_name = value
            else:
                df = value
            if df is not None and len(df) > 50 and "amount" in df.columns:
                out = df.copy()
                out["source"] = source_name
                return out, source_name
            errors.append(f"{source_name}: empty")
        except _DATA_FETCH_ERRORS as exc:
            errors.append(f"{source_name}: {exc}")
            time.sleep(0.5)
    raise DataUnavailableError(f"{label} volume data unavailable; tried {' | '.join(errors[-3:])}")

def _load_suba_volume_signal():
    specs = {}
    sources = {}
    errors = {}
    for name, label, secid, ma, days in [
        ("zz2000", "ZZ2000", CN_SA_VOLUME_ZZ2000_SECID, CN_SA_VOLUME_ZZ2000_MA, CN_SA_VOLUME_ZZ2000_DAYS),
        ("cyb", "CYB", CN_SA_VOLUME_CYB_SECID, CN_SA_VOLUME_CYB_MA, CN_SA_VOLUME_CYB_DAYS),
    ]:
        try:
            df, source = _fetch_cn_amount_with_fallback(
                secid,
                label,
                beg=CN_SA_VOLUME_HISTORY_BEG,
                lmt=10000,
            )
            specs[name] = {"amount": df["amount"], "ma": ma, "days": days}
            sources[name] = source
        except _DATA_FETCH_ERRORS as exc:
            errors[name] = str(exc)
    if not specs:
        raise DataUnavailableError("Sub-A volume data unavailable for all legs: " + " | ".join(f"{k}: {v}" for k, v in errors.items()))
    old_signal, feature = _build_consecutive_below_amount_signal(
        specs,
        mode=CN_SA_VOLUME_RULE_MODE,
    )
    severe_signal = pd.Series(dtype=bool)
    severe_feature = pd.DataFrame()
    severe_error = None
    severe_sources = {}
    if CN_SA_VOLUME_CLEAR_RATIO_ENABLED:
        try:
            numerator = specs.get("zz2000", {}).get("amount")
            if numerator is None:
                numerator_df, numerator_source = _fetch_cn_amount_with_fallback(
                    CN_SA_VOLUME_CLEAR_RATIO_NUMERATOR_SECID,
                    CN_SA_VOLUME_CLEAR_RATIO_NUMERATOR_LABEL,
                    beg=CN_SA_VOLUME_HISTORY_BEG,
                    lmt=10000,
                )
                numerator = numerator_df["amount"]
                severe_sources["numerator"] = numerator_source
            else:
                severe_sources["numerator"] = sources.get("zz2000", "unknown")
            denominator_df, denominator_source = _fetch_cn_amount_with_fallback(
                CN_SA_VOLUME_CLEAR_RATIO_DENOMINATOR_SECID,
                CN_SA_VOLUME_CLEAR_RATIO_DENOMINATOR_LABEL,
                beg=CN_SA_VOLUME_HISTORY_BEG,
                lmt=10000,
            )
            severe_sources["denominator"] = denominator_source
            severe_signal, severe_feature = _build_amount_ratio_below_ma_signal(
                numerator,
                denominator_df["amount"],
                CN_SA_VOLUME_CLEAR_RATIO_MA,
                CN_SA_VOLUME_CLEAR_RATIO_DAYS,
            )
        except _DATA_FETCH_ERRORS as exc:
            severe_error = str(exc)
    combined_index = old_signal.index.union(severe_signal.index).sort_values()
    old_signal = old_signal.reindex(combined_index).fillna(False).astype(bool)
    severe_signal = severe_signal.reindex(combined_index).fillna(False).astype(bool)
    combined_signal = old_signal | severe_signal
    combined_scale = pd.Series(
        np.where(
            severe_signal,
            CN_SA_VOLUME_CLEAR_RATIO_SCALE,
            np.where(old_signal, CN_SA_VOLUME_SCALE, 1.0),
        ),
        index=combined_index,
        dtype=float,
    )
    feature = feature.reindex(combined_index)
    if len(severe_feature) > 0:
        severe_feature = severe_feature.reindex(combined_index)
        for col in severe_feature.columns:
            feature[col] = severe_feature[col]
    feature["old_combined_signal"] = old_signal
    feature["severe_ratio_signal"] = severe_signal
    feature["combined_signal"] = combined_signal
    feature["combined_scale"] = combined_scale
    feature["clear_signal"] = severe_signal
    feature["clear_ratio_rule"] = (
        f"{CN_SA_VOLUME_CLEAR_RATIO_NUMERATOR_LABEL}/{CN_SA_VOLUME_CLEAR_RATIO_DENOMINATOR_LABEL} "
        f"MA{CN_SA_VOLUME_CLEAR_RATIO_MA}/{CN_SA_VOLUME_CLEAR_RATIO_DAYS}"
    )
    feature["clear_ratio_enabled"] = bool(CN_SA_VOLUME_CLEAR_RATIO_ENABLED)
    feature["clear_ratio_unavailable"] = severe_error is not None
    if severe_sources:
        feature["clear_ratio_numerator_source"] = severe_sources.get("numerator", "unknown")
        feature["clear_ratio_denominator_source"] = severe_sources.get("denominator", "unknown")
    if severe_error is not None:
        feature["clear_ratio_error"] = severe_error
    if len(feature) > 0:
        if severe_error is not None:
            feature["combined_unresolved"] = True
        elif errors:
            if CN_SA_VOLUME_RULE_MODE == "or":
                feature["combined_unresolved"] = ~feature["old_combined_signal"].astype(bool)
            elif CN_SA_VOLUME_RULE_MODE == "and":
                feature["combined_unresolved"] = feature["old_combined_signal"].astype(bool)
            else:
                feature["combined_unresolved"] = True
        else:
            feature["combined_unresolved"] = False
        for name in ("zz2000", "cyb"):
            if name in sources:
                feature[f"{name}_source"] = sources[name]
            else:
                feature[f"{name}_source"] = "unavailable"
                feature[f"{name}_error"] = errors.get(name, "unknown")
                feature[f"{name}_streak"] = np.nan
                feature[f"{name}_signal"] = False
        feature["partial_unavailable"] = bool(errors)
    return combined_signal, feature

def _suba_volume_feature_has_unresolved(feature):
    if feature is None or len(feature) == 0 or "combined_unresolved" not in feature.columns:
        return False
    return bool(feature["combined_unresolved"].fillna(False).astype(bool).any())

def _mark_suba_volume_unavailable(cn_result, exc):
    out = cn_result.copy()
    out["suba_volume_rule_on"] = False
    out["suba_volume_rule_scale"] = 1.0
    out["suba_volume_rule_name"] = CN_SA_VOLUME_RULE_NAME
    out["suba_volume_unavailable"] = True
    out["suba_volume_unresolved"] = True
    out["suba_volume_error"] = str(exc)
    return out


def _write_suba_volume_query_warning(msg, cn_result):
    if cn_result is None or len(cn_result) == 0:
        return
    unresolved = False
    if "suba_volume_unresolved" in cn_result.columns:
        unresolved = bool(cn_result["suba_volume_unresolved"].fillna(False).astype(bool).any())
    if not unresolved and "suba_volume_unavailable" in cn_result.columns:
        unresolved = bool(cn_result["suba_volume_unavailable"].fillna(False).astype(bool).any())
    if unresolved:
        msg.write(
            "⚠️ Sub-A成交额风控不可判定：本次查询继续显示主信号/净值，"
            "但未用成交额风控改写仓位；不应按正常仓位执行。\n\n"
        )


def _apply_suba_volume_overlay_policy(
    cn_result,
    close_df,
    suba_volume_signal,
    suba_volume_feature,
    allow_unresolved_suba_volume=False,
):
    if _suba_volume_feature_has_unresolved(suba_volume_feature):
        message = "Sub-A成交额风控不可判定，本次不应用该风控改写仓位"
        if not allow_unresolved_suba_volume:
            raise poe.BotError("Sub-A成交额风控存在不可判定项，正式路径中止。")
        return _mark_suba_volume_unavailable(cn_result, message)
    return apply_suba_volume_overlay(
        cn_result,
        close_df,
        suba_volume_signal,
        suba_volume_feature,
        scale=CN_SA_VOLUME_SCALE,
        rule_name=CN_SA_VOLUME_RULE_NAME,
    )


def _apply_v78_suba_new_volume_overlay_policy(
    new_result,
    close_df,
    suba_volume_signal,
    suba_volume_feature,
    allow_unresolved_suba_volume=False,
):
    if _suba_volume_feature_has_unresolved(suba_volume_feature):
        message = "Sub-A成交额风控不可判定，本次不应用该风控改写仓位"
        if not allow_unresolved_suba_volume:
            raise poe.BotError("Sub-A成交额风控存在不可判定项，正式路径中止。")
        return _mark_suba_volume_unavailable(new_result, message)
    return apply_v78_suba_new_volume_overlay(
        new_result,
        close_df,
        suba_volume_signal,
        suba_volume_feature,
    )


def _load_dk_volume_warning_feature():
    df, source = _fetch_cn_amount_with_fallback(
        CN_DK_VOLUME_YELLOW_SECID,
        CN_DK_VOLUME_YELLOW_LABEL,
        beg=CN_SA_VOLUME_HISTORY_BEG,
    )
    amount = pd.to_numeric(df["amount"], errors="coerce").dropna().sort_index()
    if amount.empty:
        raise ValueError(f"{CN_DK_VOLUME_YELLOW_LABEL} amount has no usable rows")
    feature = _build_dk_volume_warning_feature(amount, source)
    return feature["clear_signal"].astype(bool), feature

def _build_dk_volume_warning_feature(amount, source, ma=None, days=None):
    ma = int(CN_DK_VOLUME_YELLOW_MA if ma is None else ma)
    days = int(CN_DK_VOLUME_YELLOW_DAYS if days is None else days)
    amount = pd.to_numeric(pd.Series(amount), errors="coerce").dropna().sort_index()
    amount_ma = amount.rolling(ma).mean()
    streak = _consecutive_below_amount(amount, ma)
    signal = (streak >= days).astype(bool)
    return pd.DataFrame(
        {
            "amount": amount,
            "amount_ma": amount_ma,
            "below_ma_streak": streak,
            "clear_signal": signal,
            "source": source,
            "policy": CN_DK_VOLUME_POLICY,
        },
        index=amount.index,
    )

def _volume_warning_status(secid, ma, days, label, expected_date=None, rule_key=None):
    df, source = _fetch_cn_amount_with_fallback(
        secid,
        label,
        beg="20200101",
        lmt=max(120, int(ma) + int(days) + 30),
    )
    amount = pd.to_numeric(df["amount"], errors="coerce").dropna().sort_index()
    if amount.empty:
        raise ValueError(f"{label} amount has no usable rows")
    ma_series = amount.rolling(int(ma)).mean()
    streak = _consecutive_below_amount(amount, ma)
    latest_date = amount.index[-1]
    latest_value = float(amount.iloc[-1])
    latest_ma = float(ma_series.iloc[-1]) if pd.notna(ma_series.iloc[-1]) else np.nan
    latest_streak = int(streak.iloc[-1]) if pd.notna(streak.iloc[-1]) else 0
    below = bool(pd.notna(latest_ma) and latest_value < latest_ma)
    status = {
        "label": label,
        "date": latest_date,
        "value": latest_value,
        "ma_value": latest_ma,
        "below": below,
        "streak": latest_streak,
        "triggered": latest_streak >= int(days),
        "ma": int(ma),
        "days": int(days),
        "source": source,
    }
    if expected_date is not None and rule_key is not None:
        status = _annotate_status_freshness(status, expected_date, rule_key)
    return status

def _read_volume_csv(path, label):
    df = pd.read_csv(path, encoding="utf-8-sig")
    if df.empty:
        raise ValueError(f"{label} volume csv is empty: {path}")
    date_candidates = ["date", "Date", "日期", "trade_date", "datetime", "time", "交易日期"]
    value_candidates = ["amount", "成交额", "turnover", "volume", "成交量", "vol", "Volume"]
    date_col = next((c for c in date_candidates if c in df.columns), None)
    if date_col is None:
        date_col = df.columns[0]
    value_col = next((c for c in value_candidates if c in df.columns), None)
    if value_col is None:
        numeric_cols = [c for c in df.columns if c != date_col and pd.to_numeric(df[c], errors="coerce").notna().sum() > 0]
        if not numeric_cols:
            raise ValueError(f"{label} volume csv has no numeric volume/amount column: {path}")
        value_col = numeric_cols[-1]
    out = pd.DataFrame({
        "date": pd.to_datetime(df[date_col], errors="coerce"),
        "amount": pd.to_numeric(df[value_col], errors="coerce"),
    }).dropna()
    if out.empty:
        raise ValueError(f"{label} volume csv has no usable rows: {path}")
    out = out.set_index("date").sort_index()
    out["source"] = f"CSV {os.path.basename(path)}"
    return out

def _parse_tonghuashun_line_volume_payload(payload, source):
    dates_raw = str(payload.get("dates") or "").split(",")
    volumes_raw = str(payload.get("volumn") or payload.get("volume") or "").split(",")
    dates = [x.strip() for x in dates_raw if x.strip()]
    volumes = [x.strip() for x in volumes_raw if x.strip()]
    if not dates or not volumes:
        raise ValueError("Tonghuashun returned empty dates/volumn")
    if len(dates) != len(volumes):
        raise ValueError(f"Tonghuashun dates/volumn length mismatch: {len(dates)} vs {len(volumes)}")

    year_counts = payload.get("sortYear") or []
    expanded = []
    pos = 0
    try:
        for year, count in year_counts:
            year = int(year)
            count = int(count)
            for mmdd in dates[pos:pos + count]:
                expanded.append(pd.to_datetime(f"{year}{str(mmdd).zfill(4)}", format="%Y%m%d"))
            pos += count
    except Exception as exc:
        raise ValueError(f"Tonghuashun sortYear parse failed: {exc}")
    if len(expanded) != len(dates):
        start = str(payload.get("start") or "")
        if len(start) >= 4 and start[:4].isdigit():
            year = int(start[:4])
            expanded = []
            prev_mmdd = None
            for mmdd in dates:
                mmdd = str(mmdd).zfill(4)
                if prev_mmdd is not None and mmdd < prev_mmdd:
                    year += 1
                expanded.append(pd.to_datetime(f"{year}{mmdd}", format="%Y%m%d"))
                prev_mmdd = mmdd
        else:
            raise ValueError("Tonghuashun sortYear does not cover all dates")

    out = pd.DataFrame({
        "date": expanded,
        "volume": pd.to_numeric(volumes, errors="coerce"),
    }).dropna()
    if out.empty:
        raise ValueError("Tonghuashun returned no usable volume rows")
    out["amount"] = out["volume"]
    out["source"] = source
    return out.set_index("date").sort_index()

def _fetch_tonghuashun_microcap_direct_volume():
    source = "Tonghuashun 883418.TI"
    resp = _session.get(
        MICROCAP_DIRECT_VOLUME_THS_URL,
        timeout=20,
        headers={
            "Referer": "http://q.10jqka.com.cn/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
    )
    resp.raise_for_status()
    text = resp.text.strip()
    match = re.search(r"^[^(]+\((.*)\)\s*;?\s*$", text, flags=re.S)
    if not match:
        raise ValueError("Tonghuashun returned non-JSONP payload")
    payload = json.loads(match.group(1))
    df = _parse_tonghuashun_line_volume_payload(payload, source)
    if len(df) < max(60, MICROCAP_DIRECT_VOLUME_MA + MICROCAP_DIRECT_VOLUME_DAYS):
        raise ValueError(f"Tonghuashun returned too few rows: {len(df)}")
    return df

def _microcap_direct_volume_candidate_paths():
    base = _repo_base_dir() if "_repo_base_dir" in globals() else os.getcwd()
    paths = []
    env_path = os.environ.get(MICROCAP_DIRECT_VOLUME_CSV_ENV)
    if env_path:
        paths.append(env_path)
    for rel in [
        os.path.join(".microcap_index_cache", "883418.TI.csv"),
        os.path.join(".microcap_index_cache", "883418_TI.csv"),
        os.path.join(".microcap_index_cache", "microcap_direct_volume.csv"),
        os.path.join("data", "883418.TI.csv"),
        os.path.join("data", "883418_TI.csv"),
        "883418.TI.csv",
        "883418_TI.csv",
    ]:
        paths.append(os.path.join(base, rel))
    cache_root = os.path.join(base, ".microcap_index_cache")
    if os.path.isdir(cache_root):
        for root, _dirs, files in os.walk(cache_root):
            for filename in files:
                low = filename.lower()
                if "883418" in low and low.endswith((".csv", ".txt")):
                    paths.append(os.path.join(root, filename))
    seen = set()
    out = []
    for path in paths:
        if not path:
            continue
        norm = os.path.abspath(path)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out

def _fetch_microcap_direct_volume():
    errors = []
    try:
        df = _fetch_tonghuashun_microcap_direct_volume()
        if len(df) >= max(60, MICROCAP_DIRECT_VOLUME_MA + MICROCAP_DIRECT_VOLUME_DAYS):
            return df, df["source"].iloc[-1]
        errors.append(f"Tonghuashun: too few rows ({len(df)})")
    except Exception as exc:
        errors.append(f"Tonghuashun: {exc}")
    for path in _microcap_direct_volume_candidate_paths():
        if not os.path.exists(path):
            continue
        try:
            df = _read_volume_csv(path, MICROCAP_DIRECT_VOLUME_CODE)
            if len(df) >= max(60, MICROCAP_DIRECT_VOLUME_MA + MICROCAP_DIRECT_VOLUME_DAYS):
                return df, df["source"].iloc[-1]
            errors.append(f"{os.path.basename(path)}: too few rows ({len(df)})")
        except Exception as exc:
            errors.append(f"{os.path.basename(path)}: {exc}")
    raise RuntimeError(
        f"{MICROCAP_DIRECT_VOLUME_CODE} volume data unavailable. "
        + ("; ".join(errors[-3:]) if errors else "")
    )

def _microcap_direct_volume_status(expected_date=None):
    df, source = _fetch_microcap_direct_volume()
    amount = df["amount"].dropna().sort_index()
    if len(amount) < max(60, MICROCAP_DIRECT_VOLUME_MA + MICROCAP_DIRECT_VOLUME_DAYS):
        raise ValueError(f"{MICROCAP_DIRECT_VOLUME_CODE} has too few usable volume rows: {len(amount)}")
    ma = amount.rolling(MICROCAP_DIRECT_VOLUME_MA).mean()
    streak = _consecutive_below_amount(amount, MICROCAP_DIRECT_VOLUME_MA)
    latest_date = amount.index[-1]
    latest_value = float(amount.iloc[-1])
    latest_ma = float(ma.iloc[-1])
    latest_streak = int(streak.iloc[-1]) if pd.notna(streak.iloc[-1]) else 0
    below = bool(pd.notna(ma.iloc[-1]) and latest_value < latest_ma)
    status = {
        "date": latest_date,
        "value": latest_value,
        "ma_value": latest_ma,
        "below": below,
        "streak": latest_streak,
        "triggered": latest_streak >= MICROCAP_DIRECT_VOLUME_DAYS,
        "ma": MICROCAP_DIRECT_VOLUME_MA,
        "days": MICROCAP_DIRECT_VOLUME_DAYS,
        "source": source,
    }
    if expected_date is not None:
        status = _annotate_status_freshness(status, expected_date, "microcap_volume_warning")
    return status

def _adk_drawdown_watch_status(result, threshold, cooldown_days, label):
    if result is None or len(result) == 0 or "nav" not in result.columns:
        return {
            "label": label,
            "available": False,
            "error": "missing ADK nav series",
            "threshold": float(threshold),
            "cooldown_days": int(cooldown_days),
        }
    nav = pd.to_numeric(result["nav"], errors="coerce").dropna().sort_index()
    if nav.empty:
        return {
            "label": label,
            "available": False,
            "error": "empty ADK nav series",
            "threshold": float(threshold),
            "cooldown_days": int(cooldown_days),
        }
    running_peak = nav.cummax()
    dd = nav / running_peak - 1.0
    latest_date = dd.index[-1]
    peak_date = nav.loc[:latest_date].idxmax()
    current_dd = float(dd.iloc[-1])
    threshold = float(abs(threshold))
    cooldown_days = int(cooldown_days)
    armed = True
    last_cross_date = None
    last_cross_pos = None
    for i, (_dt, _dd) in enumerate(dd.items()):
        if pd.isna(_dd):
            continue
        cur_dd = float(_dd)
        if cur_dd > -threshold:
            armed = True
        elif armed:
            last_cross_date = _dt
            last_cross_pos = i
            armed = False
    cooldown_start_date = None
    cooldown_elapsed_days = 0
    cooldown_pending_start = False
    if last_cross_pos is not None:
        start_pos = last_cross_pos + 1
        if start_pos < len(dd):
            cooldown_start_date = dd.index[start_pos]
            cooldown_elapsed_days = min(max(len(dd) - start_pos, 0), cooldown_days)
        else:
            cooldown_pending_start = True
    cooldown_remaining_days = max(cooldown_days - cooldown_elapsed_days, 0)
    cooldown_active = bool(cooldown_elapsed_days > 0 and cooldown_elapsed_days < cooldown_days)
    cooldown_completed = bool(last_cross_pos is not None and cooldown_elapsed_days >= cooldown_days)
    return {
        "label": label,
        "available": True,
        "date": latest_date,
        "peak_date": peak_date,
        "current_dd": current_dd,
        "threshold": threshold,
        "cooldown_days": cooldown_days,
        "triggered": last_cross_date is not None and current_dd <= -threshold,
        "last_cross_date": last_cross_date,
        "cooldown_start_date": cooldown_start_date,
        "cooldown_elapsed_days": int(cooldown_elapsed_days),
        "cooldown_remaining_days": int(cooldown_remaining_days),
        "cooldown_active": cooldown_active,
        "cooldown_completed": cooldown_completed,
        "cooldown_pending_start": cooldown_pending_start,
        "rearmed": bool(armed),
        "policy": "warning_only",
    }


def _format_adk_drawdown_watch_line(status):
    label = status.get("label", "ADK")
    threshold = float(status.get("threshold", 0.0))
    cooldown_days = int(status.get("cooldown_days", 0))
    if not status.get("available", False):
        return (
            f"- {label}回撤警示: **UNKNOWN** | 无法确认回撤穿越参考条件"
            f"（阈值 {threshold:.0%} / 参考空仓{cooldown_days}个交易日）。"
            f"原因: {status.get('error', 'unknown')}；仅警示，不改变ADK仓位、收益和净值曲线。\n"
        )
    mark = "🔴 警示触发" if status.get("triggered", False) else "未触发"
    if status.get("triggered", False):
        if status.get("cooldown_pending_start", False):
            action = f"参考动作: 下一交易日起停止交易{cooldown_days}个交易日，当前已停止0/{cooldown_days}天"
        elif status.get("cooldown_active", False):
            action = (
                f"参考动作: 停止交易{cooldown_days}个交易日，"
                f"当前已停止{int(status.get('cooldown_elapsed_days', 0))}/{cooldown_days}天，"
                f"剩余{int(status.get('cooldown_remaining_days', 0))}天"
            )
        else:
            action = (
                f"参考动作: 本轮停止交易{cooldown_days}个交易日已结束，"
                f"当前已停止{int(status.get('cooldown_elapsed_days', 0))}/{cooldown_days}天；"
                f"需DD回到-{threshold:.0%}上方后才会重新进入可触发状态"
            )
    else:
        action = f"参考动作: 继续观察（未从上方跌破-{threshold:.0%}）"
    date = status["date"].strftime("%Y-%m-%d")
    peak_date = status["peak_date"].strftime("%Y-%m-%d")
    cross = status.get("last_cross_date")
    cross_text = f"；最近跌破日 {cross.strftime('%Y-%m-%d')}" if cross is not None else ""
    return (
        f"- {label}回撤警示: **{mark}** | 当前DD {status['current_dd']:.1%} / "
        f"触发阈值 -{threshold:.0%}；峰值日 {peak_date}，最新日 {date}{cross_text}。"
        f"{action}；仅警示，不改变ADK仓位、收益和净值曲线。\n"
    )


def _write_adk_drawdown_warning_panel(msg, cn_dk_result, compact=False, consensus16_result=None):
    w = msg.write
    w("### ADK回撤穿越参考提醒\n")
    if not compact:
        w(
            "定位: 下面两条只进警示板，不进入正式ADK仓位、收益或净值曲线；"
            "用于提示回撤穿越候选规则是否需要人工复核。\n"
        )
    original_status = _adk_drawdown_watch_status(
        cn_dk_result,
        CN_DK_DD_WARNING_ORIGINAL_THRESHOLD,
        CN_DK_DD_WARNING_ORIGINAL_COOLDOWN_DAYS,
        "原始ADK",
    )
    w(_format_adk_drawdown_watch_line(original_status))


def _write_volume_warning_panel(msg, compact=False, cn_dk_result=None, consensus16_result=None):
    w = msg.write
    expected_date = _warning_feature_expected_date()
    w("### 成交额风险提醒\n")
    if not compact:
        w("定位: DK成交额只做风险警示；微盘成交额为参考提示，官方微盘v2.0未启用该成交额风控；Sub-A成交额风控才正式参与仓位计算。\n")

    def _status_pos(status):
        return "低于" if bool(status.get("below", False)) else "高于或等于"

    def _latest_vs_ma_text(status):
        value = status.get("value")
        ma_value = status.get("ma_value")
        if value is None or ma_value is None or pd.isna(value) or pd.isna(ma_value):
            return ""
        return f"；最新{float(value):.4g} vs MA{status['ma']} {float(ma_value):.4g}"

    def _freshness_note(status):
        if status.get("freshness_ok", True):
            return ""
        return f"；数据过期/不可判定: {status.get('freshness_error', 'unknown')}"

    try:
        dk = _volume_warning_status(
            CN_DK_VOLUME_YELLOW_SECID,
            CN_DK_VOLUME_YELLOW_MA,
            CN_DK_VOLUME_YELLOW_DAYS,
            CN_DK_VOLUME_YELLOW_LABEL,
            expected_date=expected_date,
            rule_key="dk_volume_warning",
        )
        dk_mark = "🟡 警示触发" if dk["triggered"] else "未触发"
        dk_pos = _status_pos(dk)
        w(
            f"- Sub-A-DK成交额风险警示: **{dk_mark}** | {dk['label']}成交额当前{dk_pos}MA{dk['ma']}，"
            f"连续低于MA{dk['ma']} {dk['streak']}/{dk['days']}天{_latest_vs_ma_text(dk)}；"
            f"仅提示，不参与ADK仓位和净值曲线{_freshness_note(dk)}。\n"
        )
    except Exception as exc:
        suffix = "" if compact else f" 原因: {_short_error(exc)}"
        w(f"- Sub-A-DK成交额风险警示: **UNKNOWN** | 本次未取到{CN_DK_VOLUME_YELLOW_LABEL}成交额，无法确认警示条件。{suffix}\n")
    try:
        zz = _volume_warning_status(
            MICROCAP_BROAD_VOLUME_ZZ2000_SECID,
            MICROCAP_BROAD_VOLUME_ZZ2000_MA,
            MICROCAP_BROAD_VOLUME_ZZ2000_DAYS,
            "中证2000",
            expected_date=expected_date,
            rule_key="microcap_volume_warning",
        )
        cyb = _volume_warning_status(
            MICROCAP_BROAD_VOLUME_CYB_SECID,
            MICROCAP_BROAD_VOLUME_CYB_MA,
            MICROCAP_BROAD_VOLUME_CYB_DAYS,
            "创业板",
            expected_date=expected_date,
            rule_key="microcap_volume_warning",
        )
        micro_on = zz["triggered"] and cyb["triggered"]
        micro_mark = "🔴 警示触发" if micro_on else "未触发"
        zz_pos = _status_pos(zz)
        cyb_pos = _status_pos(cyb)
        w(
            f"- 微盘成交额参考提示: **{micro_mark}** | "
            f"中证2000当前{zz_pos}MA{zz['ma']}，连续低于MA{zz['ma']} {zz['streak']}/{zz['days']}天；"
            f"创业板当前{cyb_pos}MA{cyb['ma']}，连续低于MA{cyb['ma']} {cyb['streak']}/{cyb['days']}天。"
            f"参考条件: 两者都连续低于MA{zz['ma']}达到{zz['days']}天；参考比例={MICROCAP_BROAD_VOLUME_REFERENCE_SCALE:.0%}（仅提示，不执行）。"
            f"官方v2.0未启用该成交额风控，本面板仅提示复核，不参与微盘仓位和净值曲线。\n"
        )
        if (not zz.get("freshness_ok", True)) or (not cyb.get("freshness_ok", True)):
            w(
                f"  数据新鲜度: ZZ2000 {zz.get('freshness_error', 'OK') or 'OK'}；"
                f"CYB {cyb.get('freshness_error', 'OK') or 'OK'}。\n"
            )
    except Exception as exc:
        suffix = "" if compact else f" 原因: {_short_error(exc)}"
        w(f"- 微盘成交额参考提示: **UNKNOWN** | 本次未取到中证2000/创业板成交额，无法确认参考提示条件。{suffix}\n")
    _write_adk_drawdown_warning_panel(
        msg,
        cn_dk_result,
        compact=compact,
        consensus16_result=consensus16_result,
    )
    w("\n---\n\n")

def _write_suba_non_momentum_threshold_alert(msg, cn_result, idx=-1, prefix=""):
    if cn_result is None or len(cn_result) == 0:
        return
    w = msg.write

    def _cell_bool(value):
        return False if pd.isna(value) else bool(value)

    alerts = []
    if "suba_volume_rule_on" in cn_result.columns:
        volume_on = _cell_bool(cn_result["suba_volume_rule_on"].iloc[idx])
        volume_scale = (
            cn_result["suba_volume_rule_scale"].iloc[idx]
            if "suba_volume_rule_scale" in cn_result.columns
            else (CN_SA_VOLUME_SCALE if volume_on else 1.0)
        )
        if volume_on and pd.notna(volume_scale) and float(volume_scale) < 1.0 - 1e-12:
            action = "触发" if float(volume_scale) <= 1e-12 else "触发减仓"
            alerts.append(f"Sub-A成交额风控{action}，当前执行仓位{float(volume_scale):.0%}")
    if "suba_same_side_overheat_on" in cn_result.columns:
        overheat_on = _cell_bool(cn_result["suba_same_side_overheat_on"].iloc[idx])
        if overheat_on:
            action = "清仓" if CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE <= 1e-12 else "减仓"
            bias = (
                cn_result["suba_same_side_overheat_bias"].iloc[idx]
                if "suba_same_side_overheat_bias" in cn_result.columns
                else np.nan
            )
            bias_text = f"，当前权益乖离{float(bias):.1%}" if pd.notna(bias) else ""
            alerts.append(f"MA60过热止盈触发{action}{bias_text}")
    if alerts:
        w(
            f"{prefix}🔴 **Sub-A非动量阈值调仓:** {'；'.join(alerts)}。"
            "这不是原始动量换仓；最终执行按阈值风控后的仓位。\n"
        )


def _write_suba_volume_overlay_status(msg, cn_result, idx=-1, prefix="", compact=False):
    if "suba_volume_rule_on" not in cn_result.columns:
        return
    w = msg.write
    _write_suba_non_momentum_threshold_alert(msg, cn_result, idx, prefix)

    def _cell_bool(value):
        return False if pd.isna(value) else bool(value)

    def _cell_text(value, fallback="unavailable"):
        return fallback if pd.isna(value) else str(value)

    def _streak_status(label, streak, days):
        if pd.isna(streak):
            return f"{label}数据不可用"
        return f"{label}连续{int(streak)}/{int(days)}天"

    if "suba_volume_unavailable" in cn_result.columns and _cell_bool(cn_result["suba_volume_unavailable"].iloc[idx]):
        w(
            f"{prefix}**Sub-A成交额风控:** 风控启用；当前**UNKNOWN** | "
            f"本次不应用成交额风控，成交额调整比例暂按1.0；最终仓位请以Sub-A主表actual_weight为准。"
            f"由于硬风控不可判定，不建议直接按正常信号执行。\n"
        )
        return
    on = _cell_bool(cn_result["suba_volume_rule_on"].iloc[idx])
    scale = cn_result["suba_volume_rule_scale"].iloc[idx] if "suba_volume_rule_scale" in cn_result.columns else (CN_SA_VOLUME_SCALE if on else 1.0)
    zz_streak = cn_result["suba_volume_zz2000_streak"].iloc[idx] if "suba_volume_zz2000_streak" in cn_result.columns else np.nan
    cyb_streak = cn_result["suba_volume_cyb_streak"].iloc[idx] if "suba_volume_cyb_streak" in cn_result.columns else np.nan
    old_on = _cell_bool(cn_result["suba_volume_old_combined_signal"].iloc[idx]) if "suba_volume_old_combined_signal" in cn_result.columns else on
    clear_enabled = bool(CN_SA_VOLUME_CLEAR_RATIO_ENABLED)
    clear_on = clear_enabled and (_cell_bool(cn_result["suba_volume_clear_signal"].iloc[idx]) if "suba_volume_clear_signal" in cn_result.columns else False)
    ratio_streak = cn_result["suba_volume_severe_ratio_streak"].iloc[idx] if "suba_volume_severe_ratio_streak" in cn_result.columns else np.nan
    clear_unavailable = clear_enabled and (_cell_bool(cn_result["suba_volume_clear_ratio_unavailable"].iloc[idx]) if "suba_volume_clear_ratio_unavailable" in cn_result.columns else False)
    zz_text = _streak_status("中证2000", zz_streak, CN_SA_VOLUME_ZZ2000_DAYS)
    cyb_text = _streak_status("创业板", cyb_streak, CN_SA_VOLUME_CYB_DAYS)
    ratio_text = _streak_status("中证2000/上证50成交额比值", ratio_streak, CN_SA_VOLUME_CLEAR_RATIO_DAYS) if clear_enabled else "已关闭"
    old_status = f"已触发{CN_SA_VOLUME_SCALE:.0%}" if old_on else "未触发"
    clear_status = "已触发0%仓位" if clear_on else ("未触发0%仓位" if clear_enabled else "已关闭")
    data_note_parts = []
    if "suba_volume_partial_unavailable" in cn_result.columns and _cell_bool(cn_result["suba_volume_partial_unavailable"].iloc[idx]):
        data_note_parts.append("部分数据不可用，当前正式规则按可用腿判断")
    if clear_unavailable:
        data_note_parts.append("0%仓位扩展风控不可判定，不应按正常仓位执行")
    if "suba_volume_freshness_ok" in cn_result.columns and not _cell_bool(cn_result["suba_volume_freshness_ok"].iloc[idx]):
        freshness_error = _cell_text(
            cn_result["suba_volume_freshness_error"].iloc[idx]
            if "suba_volume_freshness_error" in cn_result.columns
            else "Sub-A成交额数据过期"
        )
        data_note_parts.append(f"{freshness_error}，不应按正常仓位执行")
    data_note = f" | {'；'.join(data_note_parts)}" if data_note_parts else ""
    unresolved = "suba_volume_unresolved" in cn_result.columns and _cell_bool(cn_result["suba_volume_unresolved"].iloc[idx])
    if unresolved and not on:
        clear_unknown_text = f"扩展风控条件: {ratio_text}；" if clear_enabled else ""
        w(
            f"{prefix}**Sub-A成交额风控:** 风控启用；当前**UNKNOWN** | "
            f"当前正式规则需要确认任一腿是否触发（{zz_text}；{cyb_text}）；"
            f"{clear_unknown_text}本次不应用成交额风控，成交额调整比例暂按1.0；"
            f"最终仓位请以Sub-A主表actual_weight为准{data_note}\n"
        )
        return
    status = "0%仓位触发" if clear_on else (f"{CN_SA_VOLUME_SCALE:.0%}触发" if old_on else "未触发")
    clear_detail = (
        f" | 扩展风控条件（中证2000/上证50成交额比值 MA{CN_SA_VOLUME_CLEAR_RATIO_MA}/{CN_SA_VOLUME_CLEAR_RATIO_DAYS}天）"
        f"{clear_status}：{ratio_text}"
        if clear_enabled
        else ""
    )
    w(
        f"{prefix}**Sub-A成交额风控:** 风控启用；当前**{status}** | 当前执行仓位={float(scale):.0%} | "
        f"当前正式规则（中证2000 MA{CN_SA_VOLUME_ZZ2000_MA}/{CN_SA_VOLUME_ZZ2000_DAYS}天 或 创业板 MA{CN_SA_VOLUME_CYB_MA}/{CN_SA_VOLUME_CYB_DAYS}天；触发后{CN_SA_VOLUME_SCALE:.0%}）"
        f"{old_status}：{zz_text}；{cyb_text}{clear_detail}{data_note}\n"
    )

def _ticker_to_stooq(ticker):
    special = {"BTC-USD": "btc.v"}
    return special.get(ticker, f"{ticker.lower()}.us")

def _fetch_us_yahoo(ticker, start_date="2003-01-01"):
    start_ts = int(pd.Timestamp(start_date).timestamp())
    end_ts = int((datetime.now() + timedelta(days=30)).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={start_ts}&period2={end_ts}&interval=1d&includeAdjustedClose=true")
    resp = _session.get(url, timeout=30)
    if resp.status_code != 200:
        raise ValueError(f"Yahoo returned status {resp.status_code}")
    data = resp.json()
    if "chart" not in data or not data["chart"].get("result"):
        raise ValueError("Yahoo returned empty result")
    result = data["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    if not timestamps:
        raise ValueError("No timestamps")
    indicators = result["indicators"]
    quote = indicators["quote"][0]
    adj_blocks = indicators.get("adjclose")
    if not adj_blocks or not adj_blocks[0]:
        raise ValueError(f"{ticker} Yahoo adjusted close missing")
    adj_close = adj_blocks[0].get("adjclose")
    if adj_close is None:
        raise ValueError(f"{ticker} Yahoo adjusted close missing")
    if len(adj_close) != len(timestamps):
        raise ValueError(
            f"{ticker} Yahoo adjusted close length mismatch: "
            f"adjusted={len(adj_close)}, timestamps={len(timestamps)}"
        )
    rows = []
    for i, ts in enumerate(timestamps):
        dt = pd.Timestamp.fromtimestamp(ts, tz="UTC").strftime("%Y-%m-%d")
        c = quote["close"][i]
        o = quote["open"][i] if "open" in quote else None
        if c is None:
            continue
        ac = adj_close[i]
        if ac is None:
            raise ValueError(f"{ticker} Yahoo adjusted close missing at {dt}")
        if c is not None and ac is not None:
            # 用复权因子调整开盘价: adj_open = open * (adj_close / raw_close)
            adj_o = None
            if o is not None and c != 0:
                adj_o = o * (ac / c)
            row = {"date": dt, "close": ac}
            if adj_o is not None:
                row["open"] = adj_o
            rows.append(row)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.drop_duplicates(subset="date").set_index("date").sort_index()

def _fetch_us_stooq(ticker, start_date="2003-01-01"):
    stooq_sym = _ticker_to_stooq(ticker)
    d1 = pd.Timestamp(start_date).strftime("%Y%m%d")
    d2 = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
    url = f"https://stooq.com/q/d/l/?s={stooq_sym}&d1={d1}&d2={d2}&i=d"
    resp = _session.get(url, timeout=30)
    resp.raise_for_status()
    text = resp.text.strip()
    if not text or "No data" in text or len(text) < 50:
        raise ValueError(f"Stooq returned no data for {ticker}")
    df = pd.read_csv(io.StringIO(text))
    if df.empty or "Close" not in df.columns:
        raise ValueError(f"Stooq CSV invalid for {ticker}")
    df = df.rename(columns={"Date": "date", "Close": "close", "Open": "open"})
    df["date"] = pd.to_datetime(df["date"])
    cols = ["date", "close"]
    if "open" in df.columns:
        cols.append("open")
    return df[cols].dropna(subset=["close"]).set_index("date").sort_index()

def fetch_yahoo(ticker, start_date="2003-01-01"):
    sources = [
        ("Yahoo", lambda: _fetch_us_yahoo(ticker, start_date)),
        ("Stooq", lambda: _fetch_us_stooq(ticker, start_date)),
    ]
    last_err = None
    for name, fetcher in sources:
        try:
            df = fetcher()
            if df is not None and len(df) > 50:
                return df, name
        except _DATA_FETCH_ERRORS as e:
            last_err = e
            time.sleep(1)
        except (KeyError, TypeError, IndexError) as e:
            last_err = DataSchemaError(f"{name} schema changed for {ticker}: {e}")
            time.sleep(1)
    return None, "FAILED"


def _fetch_us_realtime_close(ticker):
    """从Yahoo Finance实时行情API获取美股ETF/BTC最新价。
    盘中返回现价，盘后返回收盘价。
    返回 (float(价格), str(交易日date 'YYYY-MM-DD'), float(开盘价)|None) 或 (None, None, None)。"""
    try:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?range=1d&interval=1d&includePrePost=false")
        resp = _session.get(url, timeout=10)
        if resp.status_code != 200:
            return None, None, None
        data = resp.json()
        result = data.get("chart", {}).get("result", [None])[0]
        if result is None:
            return None, None, None
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")
        open_price = meta.get("regularMarketOpen")
        if open_price is None:
            quote_blocks = result.get("indicators", {}).get("quote") or []
            quote = quote_blocks[0] if quote_blocks else {}
            quote_open = quote.get("open")
            if isinstance(quote_open, (list, tuple)):
                quote_open = next((v for v in reversed(quote_open) if v is not None), None)
            if quote_open is not None:
                open_price = quote_open
        # regularMarketTime 是 Unix timestamp (美东交易日的时间)
        mkt_ts = meta.get("regularMarketTime")
        if price is None or mkt_ts is None:
            return None, None, None
        trade_date = (
            pd.Timestamp.fromtimestamp(mkt_ts, tz="UTC")
            .tz_convert("America/New_York")
            .strftime("%Y-%m-%d")
        )
        open_value = float(open_price) if open_price is not None else None
        return float(price), trade_date, open_value
    except _DATA_FETCH_ERRORS:
        return None, None, None


def _coerce_us_realtime_close_result(result):
    if result is None:
        return None, None, None
    try:
        values = tuple(result)
    except TypeError:
        return None, None, None
    if len(values) >= 3:
        return values[0], values[1], values[2]
    if len(values) == 2:
        return values[0], values[1], None
    return None, None, None


def _supplement_us_today_close(us_raw, us_tickers, msg=None):
    """当美股日K线缺少最新交易日数据时（例如美股盘中），用实时行情API补充。
    直接修改 us_raw dict 中的 DataFrame。
    仅在检测到美股开盘中(is_us_market_open)或日K线延迟时触发，以避免浪费请求。"""
    if not us_raw:
        return
    # 找到当前日K线中最新日期 (取非BTC股票类ticker)
    _stock_tickers = [t for t in us_tickers if t in us_raw and t != "BTC-USD"]
    if not _stock_tickers:
        return
    kline_last_date = max(us_raw[t].index[-1] for t in _stock_tickers)
    kline_last_str = kline_last_date.strftime("%Y-%m-%d")

    # 先用一个代表性ticker(SPY或第一个)探测: 实时API的交易日是否比K线新
    probe = "SPY" if "SPY" in us_raw else _stock_tickers[0]
    probe_price, probe_trade_date, _probe_open = _coerce_us_realtime_close_result(
        _fetch_us_realtime_close(probe)
    )
    if probe_price is None or probe_trade_date is None:
        return

    # 逐ticker检查；即使全体最大K线日期已经等于实时日期，仍可能有个别ETF滞后。
    supplemented = []
    for ticker in us_tickers:
        if ticker not in us_raw:
            continue
        df = us_raw[ticker]
        df_last = df.index[-1].strftime("%Y-%m-%d")
        if df_last >= probe_trade_date:
            continue  # 该ticker已有最新数据(如BTC 24h交易可能已更新)
        rt_price, rt_date, rt_open = _coerce_us_realtime_close_result(
            _fetch_us_realtime_close(ticker)
        )
        if rt_price is None or rt_date is None:
            continue
        if rt_date <= df_last:
            continue
        # 补充新行
        new_ts = pd.Timestamp(rt_date)
        new_payload = {"close": rt_price}
        if rt_open is not None:
            new_payload["open"] = rt_open
        new_row = pd.DataFrame([new_payload],
                               index=pd.DatetimeIndex([new_ts], name=df.index.name))
        # P2-1修复: 标记实时补价行
        new_row['is_live_bar'] = True
        merged = pd.concat([df, new_row])
        if 'is_live_bar' not in merged.columns:
            merged['is_live_bar'] = False
        merged['is_live_bar'] = merged['is_live_bar'].where(merged['is_live_bar'].notna(), False).astype(bool)
        us_raw[ticker] = merged
        supplemented.append(ticker)
        time.sleep(0.2)

    if supplemented and msg:
        msg.write(f"  ↳ 美股实时补充 ({probe_trade_date}): "
                  f"{', '.join(supplemented[:5])}"
                  f"{'...' if len(supplemented) > 5 else ''}"
                  f" 共{len(supplemented)}个 [snapshot]\n")

def build_ibit_spliced(frame, proxy_ticker="BTC-USD", live_ticker="IBIT"):
    """Use BTC history before IBIT listed, then switch to scaled IBIT returns."""
    if proxy_ticker not in frame.columns:
        raise ValueError(f"{proxy_ticker} column is required to build IBIT splice")

    proxy = pd.to_numeric(frame[proxy_ticker], errors="coerce").astype(float).copy().rename(proxy_ticker)
    if live_ticker not in frame.columns:
        return proxy

    live = pd.to_numeric(frame[live_ticker], errors="coerce").astype(float).reindex(proxy.index)
    overlap = pd.concat(
        [proxy.rename("proxy"), live.rename("live")],
        axis=1,
    ).dropna()
    if overlap.empty:
        return proxy

    switch_date = overlap.index[0]
    live_base = float(overlap.loc[switch_date, "live"])
    if abs(live_base) < 1e-12:
        return proxy

    scale_factor = float(overlap.loc[switch_date, "proxy"]) / live_base
    switch_mask = proxy.index >= switch_date
    post_listing = live.loc[switch_mask].ffill()
    proxy.loc[switch_mask] = post_listing * scale_factor
    return proxy


def _build_proxy_live_spliced_series(proxy_series, live_series=None, switch_start=None, name=None):
    proxy = pd.to_numeric(proxy_series, errors="coerce").astype(float).copy()
    if name is not None:
        proxy = proxy.rename(name)
    if live_series is None:
        return proxy
    live = pd.to_numeric(live_series, errors="coerce").astype(float).reindex(proxy.index)
    switch_mask = pd.Series(True, index=proxy.index)
    if switch_start is not None:
        switch_mask = proxy.index >= pd.Timestamp(switch_start)
    overlap = pd.concat(
        [proxy.loc[switch_mask].rename("proxy"), live.loc[switch_mask].rename("live")],
        axis=1,
    ).dropna()
    if overlap.empty:
        return proxy
    switch_date = overlap.index[0]
    live_base = float(overlap.loc[switch_date, "live"])
    if abs(live_base) < 1e-12:
        return proxy
    scale_factor = float(overlap.loc[switch_date, "proxy"]) / live_base
    proxy.loc[switch_mask] = live.loc[switch_mask] * scale_factor
    return proxy


def _build_proxy_live_open_spliced_series(proxy_open, proxy_close, live_open=None, live_close=None, name=None, switch_start=None):
    proxy = pd.to_numeric(proxy_open, errors="coerce").astype(float).copy()
    if name is not None:
        proxy = proxy.rename(name)
    if live_open is None or live_close is None:
        return proxy
    proxy_close = pd.to_numeric(proxy_close, errors="coerce").astype(float).reindex(proxy.index)
    live_open = pd.to_numeric(live_open, errors="coerce").astype(float).reindex(proxy.index)
    live_close = pd.to_numeric(live_close, errors="coerce").astype(float).reindex(proxy.index)
    switch_mask = pd.Series(True, index=proxy.index)
    if switch_start is not None:
        switch_mask = proxy.index >= pd.Timestamp(switch_start)
    overlap = pd.concat(
        [proxy_close.loc[switch_mask].rename("proxy_close"), live_close.loc[switch_mask].rename("live_close")],
        axis=1,
    ).dropna()
    if overlap.empty:
        return proxy
    switch_date = overlap.index[0]
    live_close_base = float(overlap.loc[switch_date, "live_close"])
    if abs(live_close_base) < 1e-12:
        return proxy
    scale_factor = float(overlap.loc[switch_date, "proxy_close"]) / live_close_base
    switch_mask = proxy.index >= switch_date
    proxy.loc[switch_mask] = live_open.loc[switch_mask] * scale_factor
    return proxy


def _build_us_open_execution_dict(us_raw):
    us_open = {}
    for ticker, df in (us_raw or {}).items():
        if df is not None and "open" in df.columns:
            us_open[ticker] = df["open"]
    if (
        "EMXC" in US_ROT_POOL
        and US_ROT_EMXC_BT_PROXY in us_open
    ):
        emxc_open = us_open.get("EMXC")
        emxc_close = (us_raw or {}).get("EMXC")
        proxy_close = (us_raw or {}).get(US_ROT_EMXC_BT_PROXY)
        if emxc_open is not None and emxc_close is not None and proxy_close is not None:
            us_open["EMXC"] = _build_proxy_live_open_spliced_series(
                us_open[US_ROT_EMXC_BT_PROXY],
                proxy_close["close"],
                emxc_open,
                emxc_close["close"],
                name="EMXC",
                switch_start=US_ROT_EMXC_BT_START,
            )
        else:
            us_open["EMXC"] = _build_proxy_live_spliced_series(
                us_open[US_ROT_EMXC_BT_PROXY],
                emxc_open,
                switch_start=US_ROT_EMXC_BT_START,
                name="EMXC",
            )
    if US_ROT_BTC_TICKER in us_open and "IBIT" in us_open:
        us_open[US_ROT_BTC_TICKER] = _build_proxy_live_open_spliced_series(
            us_open[US_ROT_BTC_TICKER],
            us_raw[US_ROT_BTC_TICKER]["close"],
            us_open["IBIT"],
            us_raw["IBIT"]["close"],
            name=US_ROT_BTC_TICKER,
        )
    return us_open


def _cn_signal_days(close_df, start_idx):
    week_best = {}
    for i in range(start_idx, len(close_df)):
        dt = close_df.index[i]
        dow = dt.dayofweek
        if dow > 3:
            continue
        yr, wk, _ = dt.isocalendar()
        key = (yr, wk)
        if key not in week_best or dow > week_best[key][1]:
            week_best[key] = (i, dow)
    return {v[0] for v in week_best.values()}

def _cn_cost(old_h, new_h):
    if old_h == "cash":
        legs = 1 if new_h != "cash" else 0
    elif old_h != new_h:
        legs = (1 if old_h != "cash" else 0) + (1 if new_h != "cash" else 0)
    else:
        legs = 0
    return (1 - CN_COMMISSION) ** legs

def _rolling_linear_sums(values, window):
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n < window or window <= 0:
        empty = np.array([], dtype=float)
        return empty, empty, empty, empty
    valid = np.isfinite(arr)
    clean = np.where(valid, arr, 0.0)
    pos = np.arange(n, dtype=float)

    def _window_sum(v):
        csum = np.concatenate(([0.0], np.cumsum(v, dtype=float)))
        return csum[window:] - csum[:-window]

    sum_y = _window_sum(clean)
    sum_y2 = _window_sum(clean * clean)
    sum_pos_y = _window_sum(clean * pos)
    count = _window_sum(valid.astype(float))
    starts = np.arange(n - window + 1, dtype=float)
    weighted_sum = sum_pos_y - starts * sum_y
    return sum_y, sum_y2, weighted_sum, count


def calc_bias_momentum(close_series, bias_n=None, mom_day=None):
    """乖离动量: slope(price/MA(bias_n) 归一化, 最近mom_day日) × 10000"""
    if bias_n is None: bias_n = CN_BIAS_N
    if mom_day is None: mom_day = CN_MOM_DAY
    prices = pd.to_numeric(close_series, errors="coerce").to_numpy(dtype=float)
    n = len(prices)
    result = np.full(n, np.nan)
    ma = pd.Series(prices, index=close_series.index).rolling(bias_n).mean().to_numpy(dtype=float)
    total_lookback = bias_n + mom_day - 2
    with np.errstate(divide="ignore", invalid="ignore"):
        bias = np.where((ma > 1e-10) & np.isfinite(prices), prices / ma, np.nan)
    x = np.arange(mom_day, dtype=float)
    weights = np.linspace(1.0, float(CN_BIAS_MOM_WEIGHT_END), mom_day)
    w_sum = float(weights.sum())
    x_bar = float((weights * x).sum() / w_sum)
    denom = float((weights * (x - x_bar) ** 2).sum())
    for end in range(total_lookback, n):
        y = bias[end - mom_day + 1:end + 1]
        if not np.isfinite(y).all() or y[0] <= 1e-10:
            continue
        y_bar = float((weights * y).sum() / w_sum)
        slope = float((weights * (x - x_bar) * (y - y_bar)).sum() / denom)
        result[end] = slope / float(y[0]) * 10000.0
    return pd.Series(result, index=close_series.index)

def calc_rolling_r2(close_series, window=None):
    """滚动R²: 价格对时间的线性回归拟合优度 (0~1)"""
    if window is None: window = CN_R2_WINDOW
    y = pd.to_numeric(close_series, errors="coerce").to_numpy(dtype=float)
    n = len(y)
    r2 = np.full(n, np.nan)
    sum_y, sum_y2, weighted_sum, count = _rolling_linear_sums(y, window)
    if len(sum_y):
        x_mean = (window - 1) / 2.0
        ss_x = window * (window ** 2 - 1) / 12.0
        ss_y = sum_y2 - (sum_y * sum_y) / float(window)
        ss_xy = weighted_sum - x_mean * sum_y
        ends = np.arange(window - 1, n)
        complete = count == window
        flat = complete & (ss_y < 1e-12)
        valid = complete & (ss_y >= 1e-12)
        r2[ends[flat]] = 0.0
        r2[ends[valid]] = (ss_xy[valid] ** 2) / (ss_x * ss_y[valid])
    return pd.Series(r2, index=close_series.index)

def _single_asset_position_turnover(old_h, old_weight, new_h, new_weight):
    old_h = "cash" if old_h is None or pd.isna(old_h) else str(old_h)
    new_h = "cash" if new_h is None or pd.isna(new_h) else str(new_h)

    def _clean_weight(holding, weight):
        value = 0.0 if weight is None or pd.isna(weight) else max(float(weight), 0.0)
        if holding == "cash":
            if value > 1e-12:
                raise ValueError(f"cash holding has non-zero weight: {value:.12g}")
            return 0.0
        return value

    old_w = _clean_weight(old_h, old_weight)
    new_w = _clean_weight(new_h, new_weight)
    if old_h == new_h:
        return abs(new_w - old_w)
    return old_w + new_w

def _single_asset_turnover_series(holdings, weights):
    holdings = pd.Series(holdings).fillna("cash").astype(str)
    weights = pd.Series(weights, index=holdings.index).fillna(0.0).astype(float)
    turnover = []
    for i in range(len(holdings)):
        if i == 0:
            old_h, old_w = "cash", 0.0
        else:
            old_h, old_w = holdings.iloc[i - 1], weights.iloc[i - 1]
        turnover.append(_single_asset_position_turnover(old_h, old_w, holdings.iloc[i], weights.iloc[i]))
    return pd.Series(turnover, index=holdings.index, dtype=float)

def _suba_state_machine_return_components(holdings, weights, close_df, commission=CN_COMMISSION, financing_daily=CN_RF_DAILY):
    holdings = pd.Series(holdings).fillna("cash").astype(str)
    weights = pd.Series(weights, index=holdings.index).fillna(0.0).astype(float)
    asset_component = pd.Series(0.0, index=holdings.index, dtype=float)
    cash_component = pd.Series(0.0, index=holdings.index, dtype=float)
    trade_cost = pd.Series(0.0, index=holdings.index, dtype=float)

    for i, dt in enumerate(holdings.index):
        if i == 0:
            old_h, old_w = "cash", 0.0
        else:
            old_h = holdings.iloc[i - 1]
            old_w = float(weights.iloc[i - 1])
            prev_dt = holdings.index[i - 1]
            if old_h != "cash" and old_w > 1e-12:
                asset_ret = close_df.loc[dt, old_h] / close_df.loc[prev_dt, old_h] - 1.0
                asset_component.iloc[i] = old_w * float(asset_ret)

        cash_weight = max(1.0 - float(old_w), 0.0)
        borrow_weight = max(float(old_w) - 1.0, 0.0)
        cash_component.iloc[i] = cash_weight * CN_RF_DAILY - borrow_weight * financing_daily
        trade_cost.iloc[i] = commission * _single_asset_position_turnover(
            old_h,
            old_w,
            holdings.iloc[i],
            float(weights.iloc[i]),
        )

    return asset_component, cash_component, trade_cost

def _dict_weight_turnover(old_weights, new_weights):
    old_weights = old_weights or {}
    new_weights = new_weights or {}
    assets = set(old_weights) | set(new_weights)
    return float(sum(abs(float(new_weights.get(a, 0.0) or 0.0) - float(old_weights.get(a, 0.0) or 0.0)) for a in assets))

def _dict_tradeable_turnover(old_weights, new_weights, non_tradeable_assets=("CASH", "BIL")):
    old_weights = old_weights or {}
    new_weights = new_weights or {}
    skip = set(non_tradeable_assets or ())
    assets = (set(old_weights) | set(new_weights)) - skip
    return float(sum(abs(float(new_weights.get(a, 0.0) or 0.0) - float(old_weights.get(a, 0.0) or 0.0)) for a in assets))


def _subb_should_rebalance(turnover, min_turnover=US_ROT_MIN_TURNOVER):
    threshold = max(float(min_turnover), 1e-9)
    return float(turnover or 0.0) > threshold


def _cn_series_value_at(series, row_pos):
    try:
        if series is None or row_pos >= len(series):
            return np.nan
        return series.iloc[row_pos]
    except Exception:
        return np.nan

def _select_cn_ideal_asset(scores, r2_dict, row_pos, holding="cash", abs_mom_dict=None):
    if not scores:
        return "cash"
    best = max(scores, key=scores.get)
    best_score = scores.get(best)
    if pd.isna(best_score) or float(best_score) <= 0:
        return "cash"
    r2_val = _cn_series_value_at(r2_dict.get(best), row_pos) if r2_dict else np.nan
    if pd.isna(r2_val) or float(r2_val) < CN_R2_THRESHOLD:
        return "cash"
    if abs_mom_dict is not None:
        abs_val = _cn_series_value_at(abs_mom_dict.get(best), row_pos)
        if pd.isna(abs_val) or float(abs_val) <= CN_ABS_MOM_THRESHOLD:
            return "cash"
    if holding != "cash" and holding != best and holding in scores:
        hold_score = scores.get(holding)
        hold_r2 = _cn_series_value_at(r2_dict.get(holding), row_pos) if r2_dict else np.nan
        hold_abs = _cn_series_value_at(abs_mom_dict.get(holding), row_pos) if abs_mom_dict is not None else 1.0
        holding_ok = (
            not pd.isna(hold_score)
            and float(hold_score) > 0
            and not pd.isna(hold_r2)
            and float(hold_r2) >= CN_R2_THRESHOLD
            and not pd.isna(hold_abs)
            and float(hold_abs) > CN_ABS_MOM_THRESHOLD
        )
        if holding_ok and CN_SWITCH_BUFFER > 1.0:
            return best if float(best_score) > float(hold_score) * CN_SWITCH_BUFFER else holding
    return best

def _suba_single_calc_bias_momentum(close, bias_ma, mom_day, weight_end):
    prices = pd.to_numeric(close, errors="coerce").to_numpy(dtype=float)
    n = len(prices)
    result = np.full(n, np.nan)
    ma = pd.Series(prices, index=close.index).rolling(int(bias_ma)).mean().to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        bias = np.where((ma > 1e-10) & np.isfinite(prices), prices / ma, np.nan)
    x = np.arange(int(mom_day), dtype=float)
    weights = np.linspace(1.0, float(weight_end), int(mom_day))
    w_sum = float(weights.sum())
    x_bar = float((weights * x).sum() / w_sum)
    denom = float((weights * (x - x_bar) ** 2).sum())
    for end in range(int(bias_ma) + int(mom_day) - 2, n):
        y = bias[end - int(mom_day) + 1:end + 1]
        if not np.isfinite(y).all() or y[0] <= 1e-10:
            continue
        y_bar = float((weights * y).sum() / w_sum)
        slope = float((weights * (x - x_bar) * (y - y_bar)).sum() / denom)
        result[end] = slope / float(y[0]) * 10000.0
    return pd.Series(result, index=close.index, name="score")


def _suba_single_calc_bias_momentum_r2(close, bias_ma, mom_day, weight_end):
    prices = pd.to_numeric(close, errors="coerce").to_numpy(dtype=float)
    n = len(prices)
    result = np.full(n, np.nan)
    ma = pd.Series(prices, index=close.index).rolling(int(bias_ma)).mean().to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        bias = np.where((ma > 1e-10) & np.isfinite(prices), prices / ma, np.nan)
    x = np.arange(int(mom_day), dtype=float)
    weights = np.linspace(1.0, float(weight_end), int(mom_day))
    w_sum = float(weights.sum())
    x_bar = float((weights * x).sum() / w_sum)
    denom = float((weights * (x - x_bar) ** 2).sum())
    for end in range(int(bias_ma) + int(mom_day) - 2, n):
        y = bias[end - int(mom_day) + 1:end + 1]
        if not np.isfinite(y).all() or y[0] <= 1e-10:
            continue
        y_bar = float((weights * y).sum() / w_sum)
        slope = float((weights * (x - x_bar) * (y - y_bar)).sum() / denom)
        fitted = y_bar + slope * (x - x_bar)
        ss_res = float((weights * (y - fitted) ** 2).sum())
        ss_tot = float((weights * (y - y_bar) ** 2).sum())
        result[end] = 0.0 if ss_tot <= 1e-20 else max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
    return pd.Series(result, index=close.index, name="score_r2")


def _suba_single_return_series(raw_ret, weight, cost_rate=0.001):
    weight = pd.Series(weight, index=raw_ret.index).fillna(0.0).astype(float)
    turnover = weight.diff().abs().fillna(weight.abs())
    ret = weight * raw_ret.fillna(0.0) - float(cost_rate) * turnover
    nav = (1.0 + ret).cumprod()
    return ret, nav, turnover


def _suba_single_score_abs_hysteresis(score, abs_mom, score_entry, score_exit, abs_reentry, abs_exit):
    score_values = pd.to_numeric(score, errors="coerce")
    abs_values = pd.to_numeric(abs_mom, errors="coerce")
    score_active = False
    abs_active = False
    signal = []
    for score_value, abs_value in zip(score_values, abs_values):
        if pd.isna(score_value) or pd.isna(abs_value):
            score_active = False
            abs_active = False
            signal.append(False)
            continue
        if score_active:
            score_active = float(score_value) > float(score_exit)
        elif float(score_value) > float(score_entry):
            score_active = True
        if not score_active:
            abs_active = False
            signal.append(False)
            continue
        if abs_active:
            abs_active = float(abs_value) > float(abs_exit)
        elif float(abs_value) > float(abs_reentry):
            abs_active = True
        signal.append(abs_active)
    return pd.Series(signal, index=score.index, name="base_signal")


def _suba_single_abs_hysteresis(score, abs_mom, score_threshold, abs_reentry, abs_exit):
    score_ok = (pd.to_numeric(score, errors="coerce") > float(score_threshold)).fillna(False)
    abs_values = pd.to_numeric(abs_mom, errors="coerce")
    active = False
    signal = []
    for ok, value in zip(score_ok, abs_values):
        if not ok or pd.isna(value):
            active = False
        elif active:
            active = float(value) > float(abs_exit)
        else:
            active = float(value) > float(abs_reentry)
        signal.append(active)
    return pd.Series(signal, index=score.index, name="base_signal")


def _suba_single_volume_hysteresis(volume_ratio, entry_threshold, exit_threshold, confirm_days=1):
    values = pd.to_numeric(volume_ratio, errors="coerce")
    active = False
    entry_count = 0
    exit_count = 0
    need = max(1, int(confirm_days))
    signal = []
    for value in values:
        if pd.isna(value):
            active = False
            entry_count = 0
            exit_count = 0
            signal.append(False)
            continue
        ratio = float(value)
        if active:
            entry_count = 0
            if ratio < float(exit_threshold):
                exit_count += 1
                if exit_count >= need:
                    active = False
                    exit_count = 0
            else:
                exit_count = 0
        else:
            exit_count = 0
            if ratio >= float(entry_threshold):
                entry_count += 1
                if entry_count >= need:
                    active = True
                    entry_count = 0
            else:
                entry_count = 0
        signal.append(active)
    return pd.Series(signal, index=volume_ratio.index, name="volume_pass_signal")


def _suba_single_final_weight(ohlcv, cfg):
    close = ohlcv["close"].astype(float)
    volume = ohlcv["volume"].astype(float)
    raw_ret = close.pct_change().fillna(0.0)
    score = _suba_single_calc_bias_momentum(close, cfg["bias_ma"], cfg["mom_day"], cfg["weight_end"])
    abs_mom = close / close.shift(int(cfg["abs_mom_day"])) - 1.0
    mode = cfg.get("mode")

    if mode == "sse50_v1_0":
        score_r2 = _suba_single_calc_bias_momentum_r2(close, cfg["bias_ma"], cfg["mom_day"], cfg["weight_end"])
        volume_ratio = volume / volume.rolling(int(cfg["volume_ma"])).mean()
        base_signal = (
            (score > float(cfg["score_threshold"]))
            & (score_r2 >= float(cfg["r2_threshold"]))
            & (abs_mom > float(cfg["abs_threshold"]))
            & (volume_ratio >= float(cfg["volume_ratio_threshold"]))
        )
        base_weight = base_signal.shift(1, fill_value=False).astype(float)
        realized_vol = raw_ret.rolling(int(cfg["target_vol_window"])).std(ddof=0) * np.sqrt(CN_TRADING_DAYS)
        scale_raw = (float(cfg["target_vol"]) / realized_vol.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)
        target_vol_weight = base_weight * scale_raw.clip(lower=0.0, upper=float(cfg["max_leverage"])).shift(1).fillna(1.0)
        _, base_nav, _ = _suba_single_return_series(raw_ret, target_vol_weight, cfg["cost_rate"])
        base_dd = base_nav / base_nav.cummax() - 1.0
        final_weight = target_vol_weight.where(
            base_dd.shift(1).fillna(0.0) > -float(cfg["nav_decay_threshold"]),
            target_vol_weight * float(cfg["nav_decay_scale"]),
        )
        return final_weight.rename("final_weight")

    if mode == "cyb_v1_2":
        base_signal = ((score > float(cfg["score_threshold"])) & (abs_mom > float(cfg["abs_threshold"])))
        base_weight = base_signal.shift(1, fill_value=False).astype(float)
        _, base_nav, _ = _suba_single_return_series(raw_ret, base_weight, cfg["cost_rate"])
        base_dd = base_nav / base_nav.cummax() - 1.0
        after_nav_weight = base_weight.where(
            base_dd.shift(1).fillna(0.0) > -float(cfg["nav_decay_threshold"]),
            base_weight * float(cfg["nav_decay_scale"]),
        )
        volume_ratio = volume / volume.rolling(int(cfg["hot_volume_ma"]), min_periods=int(cfg["hot_volume_ma"])).mean()
        hot_volume_confirm = (volume_ratio.shift(1) >= float(cfg["hot_volume_ratio_threshold"])).fillna(False)
        score_hot_gate = (score.shift(1) >= float(cfg["hot_score_threshold"])) & (after_nav_weight > 0) & hot_volume_confirm
        return after_nav_weight.where(~score_hot_gate, after_nav_weight * float(cfg["hot_scale"])).rename("final_weight")

    if mode == "zz1000_v1_2":
        base_signal = _suba_single_abs_hysteresis(
            score,
            abs_mom,
            cfg["score_threshold"],
            cfg["abs_reentry_threshold"],
            cfg["abs_exit_threshold"],
        )
        base_weight = base_signal.shift(1, fill_value=False).astype(float)
        _, base_nav, _ = _suba_single_return_series(raw_ret, base_weight, cfg["cost_rate"])
        base_dd = base_nav / base_nav.cummax() - 1.0
        after_nav_weight = base_weight.where(
            base_dd.shift(1).fillna(0.0) > -float(cfg["nav_decay_threshold"]),
            base_weight * float(cfg["nav_decay_scale"]),
        )
        after_score_hot = after_nav_weight.where(
            ~((score.shift(1) >= float(cfg["score_hot_threshold"])) & (after_nav_weight > 0)),
            after_nav_weight * float(cfg["score_hot_scale"]),
        )
        volume_ratio = volume / volume.rolling(int(cfg["volume_ma"]), min_periods=int(cfg["volume_ma"])).mean()
        volume_signal = _suba_single_volume_hysteresis(
            volume_ratio,
            cfg["volume_ratio_threshold"],
            cfg["volume_exit_threshold"],
            cfg["volume_confirm_days"],
        )
        volume_ready_exec = volume_ratio.notna().shift(1, fill_value=False).fillna(False).astype(bool)
        volume_signal_exec = volume_signal.shift(1, fill_value=False).fillna(False).astype(bool)
        volume_pass = volume_signal_exec | ~volume_ready_exec
        return after_score_hot.where(volume_pass, 0.0).rename("final_weight")

    if mode == "zz500_v1_2":
        base_signal = _suba_single_score_abs_hysteresis(
            score,
            abs_mom,
            cfg["score_threshold"],
            cfg["score_exit_threshold"],
            cfg["abs_reentry_threshold"],
            cfg["abs_exit_threshold"],
        )
        base_weight = base_signal.shift(1, fill_value=False).astype(float)
        _, base_nav, _ = _suba_single_return_series(raw_ret, base_weight, cfg["cost_rate"])
        base_dd = base_nav / base_nav.cummax() - 1.0
        desired_weight = base_weight.where(
            base_dd.shift(1).fillna(0.0) > -float(cfg["nav_decay_threshold"]),
            base_weight * float(cfg["nav_decay_scale"]),
        )
        score_hot_scale = pd.Series(1.0, index=desired_weight.index)
        score_hot_scale.loc[(score.shift(1) >= float(cfg["hot_score_threshold"])) & (desired_weight > 0)] = float(cfg["hot_scale"])
        realized_vol = raw_ret.rolling(int(cfg["high_vol_window"])).std(ddof=0) * np.sqrt(CN_TRADING_DAYS)
        vol_scale = pd.Series(1.0, index=desired_weight.index)
        vol_scale.loc[(realized_vol.shift(1) >= float(cfg["high_vol_threshold"])) & (desired_weight > 0)] = float(cfg["high_vol_scale"])
        overheat_weight = desired_weight * pd.concat([score_hot_scale, vol_scale], axis=1).min(axis=1)
        volume_ratio = volume / volume.rolling(int(cfg["volume_ma"]), min_periods=int(cfg["volume_ma"])).mean()
        volume_signal = _suba_single_volume_hysteresis(
            volume_ratio,
            cfg["volume_ratio_threshold"],
            cfg["volume_exit_threshold"],
            cfg["volume_confirm_days"],
        )
        volume_ready_exec = volume_ratio.notna().shift(1, fill_value=False).fillna(False).astype(bool)
        volume_signal_exec = volume_signal.shift(1, fill_value=False).fillna(False).astype(bool)
        volume_pass = volume_signal_exec | ~volume_ready_exec
        return overheat_weight.where(volume_pass, 0.0).rename("final_weight")

    raise ValueError(f"Unsupported Sub-A single gate mode: {mode}")


def _build_suba_single_strategy_gates(close_df, msg=None):
    gates = {}
    for code, cfg in CN_SA_SINGLE_GATE_CONFIGS.items():
        if code not in close_df.columns:
            continue
        try:
            ohlcv = _fetch_cn_sina_amount_proxy(code)
            final_weight = _suba_single_final_weight(ohlcv, cfg)
            gate = (final_weight.shift(int(CN_SA_SINGLE_GATE_EXECUTION_SHIFT)).fillna(final_weight) > 1e-12)
            gates[code] = gate.reindex(close_df.index).astype("boolean").ffill().fillna(False).astype(bool)
            if msg is not None:
                msg.write(
                    f"  Sub-A single gate {CN_NAMES.get(code, code)}: "
                    f"{final_weight.index[-1].strftime('%Y-%m-%d')} [{cfg['name']}]\n"
                )
        except _DATA_FETCH_ERRORS as exc:
            raise poe.BotError(f"Sub-A single gate data unavailable for {CN_NAMES.get(code, code)}: {_short_error(exc)}") from exc
        except Exception as exc:
            raise poe.BotError(f"Sub-A single gate failed for {CN_NAMES.get(code, code)}: {_short_error(exc)}") from exc
    return gates


def _normalize_suba_single_asset_gate(single_asset_signal_gate, index):
    gates = {}
    if not single_asset_signal_gate:
        return gates
    for code, values in single_asset_signal_gate.items():
        gate = pd.Series(values, dtype="boolean").reindex(index).ffill().fillna(False).astype(bool)
        gates[str(code)] = gate
    return gates


def run_cn_strategy(close_df, equity_codes, single_asset_signal_gate=None):
    """Sub-A V6.1: 乖离动量 + R²过滤 + 国债轮动 + 波动率缩放.
    v6.1变更: 乖离动量替代双动量排名, R²过滤替代MA拐头和冷却期, 国债加入轮动池, 波动率缩放控制风险.
    """
    bond_code = CN_BOND_CODE
    all_codes = equity_codes + [bond_code]
    bias_dict, r2_dict, abs_mom_dict = {}, {}, {}
    for code in all_codes:
        if code not in close_df.columns: continue
        bias_dict[code] = calc_bias_momentum(close_df[code])
        r2_dict[code] = calc_rolling_r2(close_df[code])
        abs_mom_dict[code] = close_df[code].pct_change(CN_ABS_MOM_DAY)
    start_idx = max(CN_BIAS_N + CN_MOM_DAY, CN_R2_WINDOW + 1, CN_ABS_MOM_DAY + 1)
    holding = "cash"
    holding_fraction = 0.0
    pending_entry_target = None
    pending_entry_since = None
    pending_entry_days = 0
    single_asset_gates = _normalize_suba_single_asset_gate(single_asset_signal_gate, close_df.index)
    rows = []
    for i in range(start_idx, len(close_df)):
        date = close_df.index[i]
        scores = {}
        for code in all_codes:
            if code in bias_dict:
                val = bias_dict[code].iloc[i]
                if not np.isnan(val):
                    scores[code] = val
        ideal = "cash"
        if scores:
            ideal = _select_cn_ideal_asset(scores, r2_dict, i, holding=holding, abs_mom_dict=abs_mom_dict)
        raw_ideal = ideal
        single_gate_pass = True
        single_gate_blocked = False
        if raw_ideal != "cash" and raw_ideal in single_asset_gates:
            single_gate_pass = bool(single_asset_gates[raw_ideal].iloc[i])
            if not single_gate_pass:
                ideal = "cash"
                single_gate_blocked = True
        signal_target = ideal if ideal != holding else None
        trade_target = None
        trade_fraction = holding_fraction
        is_signal = False

        if holding == "cash":
            if ideal != "cash":
                initial_fraction = float(np.clip(CN_ENTRY_INITIAL_FRACTION, 0.0, 1.0))
                trade_target = ideal
                trade_fraction = initial_fraction
                is_signal = initial_fraction > 0.0
                if initial_fraction >= 1.0 - 1e-12:
                    pending_entry_target = None
                    pending_entry_since = None
                    pending_entry_days = 0
                else:
                    pending_entry_target = ideal
                    pending_entry_since = date
                    pending_entry_days = 0
        else:
            is_partial_pending = (
                pending_entry_target is not None
                and holding == pending_entry_target
                and holding_fraction < 1.0 - 1e-12
            )
            if is_partial_pending:
                if signal_target is not None:
                    trade_target = signal_target
                    trade_fraction = 0.0 if signal_target == "cash" else 1.0
                    is_signal = True
                    pending_entry_target = None
                    pending_entry_since = None
                    pending_entry_days = 0
                else:
                    prev_close = close_df.iloc[i - 1][pending_entry_target] if i > 0 else np.nan
                    curr_close = close_df.iloc[i][pending_entry_target]
                    is_down_day = (
                        pd.notna(prev_close)
                        and pd.notna(curr_close)
                        and float(curr_close) < float(prev_close)
                    )
                    if is_down_day:
                        trade_target = pending_entry_target
                        trade_fraction = 1.0
                        pending_entry_target = None
                        pending_entry_since = None
                        pending_entry_days = 0
                        is_signal = True
                    else:
                        pending_entry_days += 1
                        if (
                            CN_ENTRY_WAIT_DAYS is not None
                            and pending_entry_days >= int(CN_ENTRY_WAIT_DAYS)
                        ):
                            trade_target = pending_entry_target
                            trade_fraction = 1.0
                            pending_entry_target = None
                            pending_entry_since = None
                            pending_entry_days = 0
                            is_signal = True
            elif signal_target is not None:
                trade_target = signal_target
                trade_fraction = 0.0 if signal_target == "cash" else 1.0
                is_signal = True
                pending_entry_target = None
                pending_entry_since = None
                pending_entry_days = 0

        old_h = holding
        old_fraction = holding_fraction
        if old_h == "cash" or old_fraction <= 1e-12 or i == 0:
            asset_ret = 0.0
        else:
            asset_ret = close_df.iloc[i][old_h] / close_df.iloc[i-1][old_h] - 1
        asset_component = old_fraction * asset_ret
        cash_component = (1.0 - old_fraction) * CN_RF_DAILY
        trade_cost = 0.0

        if trade_target is not None:
            if trade_target == old_h:
                turnover = abs(float(trade_fraction) - float(old_fraction))
            else:
                turnover = float(old_fraction) + float(trade_fraction)
            trade_cost = CN_COMMISSION * turnover
            holding = trade_target if float(trade_fraction) > 1e-12 else "cash"
            holding_fraction = float(trade_fraction) if holding != "cash" else 0.0
        else:
            holding_fraction = old_fraction
        rows.append({
            "date": date,
            "holding": holding,
            "holding_fraction": holding_fraction,
            "is_signal": is_signal,
            "target": trade_target,
            "asset_component": asset_component,
            "cash_component": cash_component,
            "trade_cost": trade_cost,
            "pending_entry_target": pending_entry_target,
            "pending_entry_since": pending_entry_since,
            "pending_entry_days": pending_entry_days,
            "suba_single_gate_raw_ideal": raw_ideal,
            "suba_single_gate_pass": single_gate_pass,
            "suba_single_gate_blocked": single_gate_blocked,
        })
    df = pd.DataFrame(rows).set_index("date")
    # 波动率缩放 (v6.1): cash日scale=1.0, 权益日scale=target_vol/realized_vol
    raw_ret = (df["asset_component"] + df["cash_component"]).values.copy()
    base_weight = df["holding_fraction"].fillna(0.0).values
    is_cash = base_weight <= 1e-12
    realized_vol = pd.Series(raw_ret, index=df.index).rolling(CN_VOL_WINDOW).std() * np.sqrt(CN_TRADING_DAYS)
    raw_scale = (CN_TARGET_VOL / realized_vol).clip(CN_MIN_LEV, CN_MAX_LEV)
    raw_scale = raw_scale.shift(1)
    if CN_SCALE_THRESHOLD > 0:
        _sa = raw_scale.values.copy()
        _last = np.nan
        for _i in range(len(_sa)):
            if np.isnan(_sa[_i]): continue
            if np.isnan(_last): _last = _sa[_i]
            elif abs(_sa[_i] - _last) >= CN_SCALE_THRESHOLD - 1e-9: _last = _sa[_i]
            else: _sa[_i] = _last
        raw_scale = pd.Series(_sa, index=df.index)
    scale_arr = raw_scale.fillna(1.0).to_numpy(copy=True)
    df["scale_raw"] = raw_scale
    scale_arr[is_cash] = 1.0
    effective_weight = scale_arr * base_weight
    df["base_weight"] = base_weight
    df["weight"] = effective_weight
    df["realized_vol"] = realized_vol
    df["base_trade_cost"] = df["trade_cost"].astype(float)
    state_asset, state_cash, state_cost = _suba_state_machine_return_components(
        df["holding"],
        pd.Series(effective_weight, index=df.index),
        close_df,
        commission=CN_COMMISSION,
    )
    effective_turnover = state_cost / CN_COMMISSION if CN_COMMISSION else pd.Series(0.0, index=df.index)
    df["asset_component"] = state_asset
    df["cash_component"] = state_cash
    df["effective_turnover"] = effective_turnover
    df["trade_cost"] = state_cost
    df["scale_tc"] = 0.0
    scaled_gross = 1.0 + df["asset_component"].values + df["cash_component"].values
    df["return"] = scaled_gross * (1.0 - df["trade_cost"].values) - 1.0
    df["nav"] = (1 + df["return"]).cumprod()
    return df


def _v78_weighted_linear_slope(values, window, weight_end=1.0, normalize_first=False):
    arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    window = int(window)
    if len(arr) < window:
        return pd.Series(out, index=values.index, dtype=float)
    x = np.arange(window, dtype=float)
    weights = np.linspace(1.0, float(weight_end), window)
    w_sum = weights.sum()
    x_bar = float((weights * x).sum() / w_sum)
    denom = float((weights * (x - x_bar) ** 2).sum())
    kernel = weights * (x - x_bar) / denom
    for end in range(window - 1, len(arr)):
        sample = arr[end - window + 1:end + 1]
        if not np.isfinite(sample).all():
            continue
        slope = float(sample @ kernel)
        if normalize_first:
            first = abs(float(sample[0]))
            if first < 1e-12:
                continue
            slope /= first
        out[end] = slope
    return pd.Series(out, index=values.index, dtype=float)


def _v78_suba_bias_slope_score(close_df, ma=40, mom=20, weight_end=3.0):
    bias = close_df / close_df.rolling(int(ma)).mean()
    score = pd.DataFrame(index=close_df.index)
    for col in close_df.columns:
        score[col] = _v78_weighted_linear_slope(
            bias[col],
            int(mom),
            weight_end=float(weight_end),
            normalize_first=True,
        )
    return score


def run_v78_suba_new_tv10(close_df, equity_codes):
    if float(V78_SUBA_NEW_MAX_LEV) > 1.0 + 1e-12:
        raise ValueError("V78_SUBA_NEW_MAX_LEV > 1.0 requires explicit borrow-cost implementation.")
    codes = [c for c in equity_codes + [CN_BOND_CODE] if c in close_df.columns]
    close = close_df[codes].copy()
    raw_score = _v78_suba_bias_slope_score(
        close,
        ma=V78_SUBA_NEW_MA,
        mom=V78_SUBA_NEW_MOM_DAY,
        weight_end=V78_SUBA_NEW_WEIGHT_END,
    )
    abs_mom = close.pct_change(V78_SUBA_NEW_ABS_DAY)
    score = raw_score.where(raw_score > V78_SUBA_NEW_SCORE_THRESHOLD)
    score = score.where(abs_mom > V78_SUBA_NEW_ABS_THRESHOLD)
    score_arr = score.replace([np.inf, -np.inf], np.nan).to_numpy(dtype=float)
    filled = np.where(np.isfinite(score_arr), score_arr, -np.inf)
    max_idx = np.argmax(filled, axis=1)
    max_val = filled[np.arange(len(filled)), max_idx]
    target_code = np.where(np.isfinite(max_val) & (max_val > 0), max_idx, -1).astype(int)

    raw = np.zeros(len(close), dtype=float)
    price = close.to_numpy(dtype=float)
    asset_ret = np.zeros_like(price, dtype=float)
    asset_ret[1:] = price[1:] / price[:-1] - 1.0
    holding_code = np.empty_like(target_code)
    holding_code[0] = -1
    holding_code[1:] = target_code[:-1]
    invested = holding_code >= 0
    raw[invested] = asset_ret[np.arange(len(close))[invested], holding_code[invested]]

    realized = pd.Series(raw, index=close.index).rolling(V78_SUBA_NEW_VOL_WINDOW).std() * np.sqrt(CN_TRADING_DAYS)
    scale = (V78_SUBA_NEW_TARGET_VOL / realized.replace(0.0, np.nan)).clip(lower=0.0, upper=V78_SUBA_NEW_MAX_LEV)
    target_weight = scale.fillna(1.0).where(pd.Series(target_code, index=close.index) >= 0, 0.0)
    holding_weight = target_weight.shift(1).fillna(0.0)

    gross = holding_weight.to_numpy(dtype=float) * pd.Series(raw, index=close.index).to_numpy(dtype=float)
    cash_component = (
        1.0 - holding_weight.clip(upper=1.0).to_numpy(dtype=float)
    ) * float(CN_RF_DAILY)
    same_asset = target_code == holding_code
    turnover = np.where(
        same_asset,
        np.abs(target_weight.to_numpy(dtype=float) - holding_weight.to_numpy(dtype=float)),
        np.abs(target_weight.to_numpy(dtype=float)) + np.abs(holding_weight.to_numpy(dtype=float)),
    )
    trade_cost = CN_COMMISSION * turnover
    ret = (1.0 + gross + cash_component) * (1.0 - trade_cost) - 1.0
    code_changed = pd.Series(target_code, index=close.index).ne(
        pd.Series(target_code, index=close.index).shift(1)
    )
    weight_changed = target_weight.diff().abs().fillna(0.0).gt(1e-4)
    label_arr = np.array(codes + ["cash"], dtype=object)
    out = pd.DataFrame(
        {
            "holding": label_arr[np.where(holding_code >= 0, holding_code, len(codes))],
            "target": label_arr[np.where(target_code >= 0, target_code, len(codes))],
            "holding_fraction": holding_weight,
            "base_weight": holding_weight,
            "weight": holding_weight,
            "target_weight": target_weight,
            "scale_raw": scale,
            "realized_vol": realized,
            "return": ret,
            "trade_cost": trade_cost,
            "turnover": turnover,
            "cash_component": cash_component,
            "is_signal": (code_changed | weight_changed).fillna(False),
        },
        index=close.index,
    )
    out["nav"] = (1.0 + out["return"].fillna(0.0)).cumprod()
    out.attrs["v78_raw_score"] = raw_score
    out.attrs["v78_abs_mom"] = abs_mom
    out.attrs["v78_score"] = score
    return out


def blend_v78_suba_results(v77_result, new_result):
    common_index = v77_result.dropna(subset=["return"]).index.intersection(
        new_result.dropna(subset=["return"]).index
    )
    if common_index.empty:
        raise ValueError("V7.9 Sub-A blend has no overlapping return window.")
    v77 = v77_result.reindex(common_index)
    new = new_result.reindex(common_index)

    def _component_target_holding(df, index):
        holding = df.get("holding", pd.Series("cash", index=index))
        if not isinstance(holding, pd.Series):
            holding = pd.Series(holding, index=index)
        holding = holding.reindex(index).fillna("cash").astype(str)
        target = df.get("target", pd.Series(None, index=index, dtype=object))
        if not isinstance(target, pd.Series):
            target = pd.Series(target, index=index, dtype=object)
        target = target.reindex(index)
        return target.where(target.notna(), holding).fillna("cash").astype(str)

    def _component_target_weight(df, index):
        weight = df.get("weight", pd.Series(0.0, index=index))
        if not isinstance(weight, pd.Series):
            weight = pd.Series(weight, index=index)
        weight = pd.to_numeric(weight.reindex(index), errors="coerce").fillna(0.0)
        target_weight = df.get("target_weight", weight)
        if not isinstance(target_weight, pd.Series):
            target_weight = pd.Series(target_weight, index=index)
        return pd.to_numeric(target_weight.reindex(index), errors="coerce").fillna(weight)

    out = v77.copy()
    out["v78_suba_v77_return"] = v77["return"].astype(float)
    out["v78_suba_new_return"] = new["return"].astype(float)
    out["return"] = V78_SUBA_V77_WEIGHT * out["v78_suba_v77_return"] + V78_SUBA_NEW_TV10_WEIGHT * out["v78_suba_new_return"]
    out["nav"] = (1.0 + out["return"].fillna(0.0)).cumprod()
    v77_holding_full = v77_result.get("holding", pd.Series("cash", index=v77_result.index))
    if not isinstance(v77_holding_full, pd.Series):
        v77_holding_full = pd.Series(v77_holding_full, index=v77_result.index)
    v77_weight_full = v77_result.get("weight", pd.Series(0.0, index=v77_result.index))
    if not isinstance(v77_weight_full, pd.Series):
        v77_weight_full = pd.Series(v77_weight_full, index=v77_result.index)
    v77_scale_raw_full = v77_result.get("scale_raw", pd.Series(np.nan, index=v77_result.index))
    if not isinstance(v77_scale_raw_full, pd.Series):
        v77_scale_raw_full = pd.Series(v77_scale_raw_full, index=v77_result.index)
    out["v78_suba_v77_holding"] = v77_holding_full.shift(1).reindex(common_index).fillna("cash").astype(str)
    out["v78_suba_new_holding"] = new.get("holding", "cash")
    out["v78_suba_v77_weight"] = pd.to_numeric(
        v77_weight_full.shift(1).reindex(common_index), errors="coerce"
    ).fillna(0.0)
    out["v78_suba_new_weight"] = pd.to_numeric(new.get("weight", 0.0), errors="coerce").fillna(0.0)
    out["v78_suba_v77_target"] = _component_target_holding(v77, common_index)
    out["v78_suba_new_target"] = _component_target_holding(new, common_index)
    out["v78_suba_v77_target_weight"] = _component_target_weight(v77, common_index)
    out["v78_suba_new_target_weight"] = _component_target_weight(new, common_index)
    out["v78_suba_v77_scale_raw"] = pd.to_numeric(
        v77_scale_raw_full.shift(1).reindex(common_index), errors="coerce"
    )
    out["v78_suba_new_scale_raw"] = pd.to_numeric(new.get("scale_raw", np.nan), errors="coerce")
    out["v78_suba_final_exposure"] = (
        V78_SUBA_V77_WEIGHT * out["v78_suba_v77_weight"]
        + V78_SUBA_NEW_TV10_WEIGHT * out["v78_suba_new_weight"]
    )
    out["v78_suba_target_exposure"] = (
        V78_SUBA_V77_WEIGHT * out["v78_suba_v77_target_weight"]
        + V78_SUBA_NEW_TV10_WEIGHT * out["v78_suba_new_target_weight"]
    )
    out["final_exposure"] = out["v78_suba_final_exposure"]
    out["target_exposure"] = out["v78_suba_target_exposure"]
    out["final_components"] = [
        {
            "v77": {
                "holding": vh,
                "weight": V78_SUBA_V77_WEIGHT * float(vw),
            },
            "new": {
                "holding": nh,
                "weight": V78_SUBA_NEW_TV10_WEIGHT * float(nw),
            },
        }
        for vh, vw, nh, nw in zip(
            out["v78_suba_v77_holding"],
            out["v78_suba_v77_weight"],
            out["v78_suba_new_holding"],
            out["v78_suba_new_weight"],
        )
    ]
    out["holding"] = [
        f"V7.7A:{vh}|NewA:{nh}"
        for vh, nh in zip(out["v78_suba_v77_holding"], out["v78_suba_new_holding"])
    ]
    target_holding = [
        f"V7.7A:{vh}|NewA:{nh}"
        for vh, nh in zip(out["v78_suba_v77_target"], out["v78_suba_new_target"])
    ]
    out["weight"] = out["final_exposure"]
    out["holding_fraction"] = out["final_exposure"]
    out["effective_fraction"] = out["final_exposure"]
    out["base_weight"] = out["final_exposure"]
    out["scale_raw"] = np.nan
    out["is_signal"] = (
        v77.get("is_signal", pd.Series(False, index=common_index)).astype(bool)
        | new.get("is_signal", pd.Series(False, index=common_index)).astype(bool)
        | (out["v78_suba_target_exposure"] - out["v78_suba_final_exposure"]).abs().gt(1e-4)
    )
    out["target"] = pd.Series(target_holding, index=out.index).where(out["is_signal"], None)
    out["v78_blend_label"] = "50% V7.7A + 50% New A TV1.0"
    out["v78_suba_component_net_return"] = out["return"]
    out["return_before_suba_execution_cost"] = out["return"]
    out["trade_cost"] = 0.0
    out["turnover"] = np.nan
    out["effective_turnover"] = np.nan
    out["cost_basis_note"] = "component-net blend; component costs already included"
    out.attrs["v78_suba_v77"] = v77_result
    out.attrs["v78_suba_new"] = new_result
    return out

CN_SA_CASH_OVERLAY_ENABLED = False
CN_SA_CASH_OVERLAY_DECAY_RATIO = 0.55
CN_SA_CASH_OVERLAY_RECOVERY_RATIO = 0.90
CN_SA_CASH_OVERLAY_WARMUP_DAYS = 5
CN_SA_SAME_SIDE_OVERHEAT_ENABLED = True
CN_SA_SAME_SIDE_OVERHEAT_ENTER = 0.27
CN_SA_SAME_SIDE_OVERHEAT_EXIT = 0.24
CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE = 0.0

def _extract_active_cn_score(cn_result, close_df):
    if cn_result is None or len(cn_result) == 0:
        return pd.Series(dtype=float)

    all_codes = [c for c in CN_ALL_CODES if c in close_df.columns]
    bias_dict = {}
    for code in all_codes:
        bias_dict[code] = calc_bias_momentum(close_df[code])

    scores = []
    for i, dt in enumerate(cn_result.index):
        holding = str(cn_result["holding"].iloc[i]) if "holding" in cn_result.columns else "cash"
        holding_fraction = float(cn_result["holding_fraction"].iloc[i]) if "holding_fraction" in cn_result.columns else 0.0
        score = np.nan
        if holding in CN_STOCK_CODES and holding_fraction > 1e-12 and holding in bias_dict and dt in bias_dict[holding].index:
            raw = bias_dict[holding].loc[dt]
            if pd.notna(raw):
                score = float(raw)
        scores.append(score)
    return pd.Series(scores, index=cn_result.index, dtype=float)


def apply_suba_cash_peak_decay_overlay(
    cn_result,
    close_df,
    decay_ratio_threshold,
    recovery_ratio_threshold,
    commission=0.0,
    warmup_days=CN_SA_CASH_OVERLAY_WARMUP_DAYS,
):
    if not 0 < decay_ratio_threshold < 1:
        raise ValueError("decay_ratio_threshold must be in (0, 1).")
    if not decay_ratio_threshold < recovery_ratio_threshold <= 1:
        raise ValueError("recovery_ratio_threshold must be in (decay_ratio_threshold, 1].")
    if cn_result is None or len(cn_result) == 0:
        return cn_result

    required = {"holding", "holding_fraction", "return"}
    missing = required.difference(cn_result.columns)
    if missing:
        raise KeyError(f"Missing required Sub-A columns: {sorted(missing)}")

    out = cn_result.copy()
    base_holding = out["holding"].fillna("cash").astype(str)
    base_fraction = out["holding_fraction"].fillna(0.0).astype(float).clip(lower=0.0, upper=1.0)
    active_score = _extract_active_cn_score(out, close_df).reindex(out.index).astype(float)

    effective_holdings = []
    effective_fractions = []
    overlay_on = []
    overlay_triggered = []
    overlay_recovered = []
    trade_ids = []
    score_peaks = []
    score_decay_ratios = []
    waiting_flags = []

    trade_id = 0
    score_peak = None
    derisked_for_today = False
    waiting_for_new_peak = False
    rearm_peak = None
    prev_overlay_on = False
    trade_age = 0

    for i, dt in enumerate(out.index):
        cur_base_holding = base_holding.iloc[i]
        cur_base_fraction = float(base_fraction.iloc[i])
        prev_base_holding = base_holding.iloc[i - 1] if i > 0 else None
        new_trade = i == 0 or cur_base_holding != prev_base_holding

        if new_trade:
            trade_id += 1
            score_peak = None
            derisked_for_today = False
            waiting_for_new_peak = False
            rearm_peak = None
            trade_age = 0
        trade_age += 1

        eligible_stock = cur_base_holding in CN_STOCK_CODES and cur_base_fraction > 1e-12
        cur_effective_holding = "cash" if (derisked_for_today and eligible_stock) else (cur_base_holding if cur_base_fraction > 1e-12 else "cash")
        cur_effective_fraction = 0.0 if (derisked_for_today and eligible_stock) else (cur_base_fraction if cur_base_holding != "cash" else 0.0)
        cur_overlay_on = bool(derisked_for_today and eligible_stock)
        triggered_today = cur_overlay_on and not prev_overlay_on
        recovered_today = (not cur_overlay_on) and prev_overlay_on

        cur_score = active_score.iloc[i] if eligible_stock else np.nan
        if pd.notna(cur_score):
            cur_score = float(cur_score)
            score_peak = cur_score if score_peak is None else max(float(score_peak), cur_score)

        decay_ratio = None
        if score_peak is not None and score_peak > 1e-12 and pd.notna(cur_score):
            decay_ratio = float(cur_score) / float(score_peak)

        next_derisked = derisked_for_today
        next_waiting = waiting_for_new_peak
        next_rearm_peak = rearm_peak

        if next_waiting and next_rearm_peak is not None and score_peak is not None and score_peak > float(next_rearm_peak) + 1e-12:
            next_waiting = False
            next_rearm_peak = None

        if eligible_stock:
            if next_derisked:
                if decay_ratio is not None and decay_ratio >= recovery_ratio_threshold:
                    next_derisked = False
                    next_waiting = True
                    next_rearm_peak = score_peak
            elif (
                not next_waiting
                and trade_age >= int(warmup_days)
                and decay_ratio is not None
                and decay_ratio <= decay_ratio_threshold
            ):
                next_derisked = True
        else:
            next_derisked = False
            next_waiting = False
            next_rearm_peak = None

        effective_holdings.append(cur_effective_holding)
        effective_fractions.append(float(cur_effective_fraction))
        overlay_on.append(cur_overlay_on)
        overlay_triggered.append(triggered_today)
        overlay_recovered.append(recovered_today)
        trade_ids.append(int(trade_id))
        score_peaks.append(None if score_peak is None else float(score_peak))
        score_decay_ratios.append(None if decay_ratio is None else float(decay_ratio))
        waiting_flags.append(bool(next_waiting))

        derisked_for_today = next_derisked
        waiting_for_new_peak = next_waiting
        rearm_peak = next_rearm_peak
        prev_overlay_on = cur_overlay_on

    eff_h = pd.Series(effective_holdings, index=out.index, dtype=str)
    eff_f = pd.Series(effective_fractions, index=out.index, dtype=float)
    asset_component_s = pd.Series(0.0, index=out.index, dtype=float)
    cash_component_s = pd.Series(0.0, index=out.index, dtype=float)
    trade_cost_s = pd.Series(0.0, index=out.index, dtype=float)
    effective_signals = []

    for i, dt in enumerate(out.index):
        if i == 0:
            asset_component_s.iloc[i] = float(out["asset_component"].iloc[i]) if "asset_component" in out.columns else 0.0
            cash_component_s.iloc[i] = float(out["cash_component"].iloc[i]) if "cash_component" in out.columns else float(out["return"].iloc[i])
            trade_cost_s.iloc[i] = float(out["trade_cost"].iloc[i]) if "trade_cost" in out.columns else 0.0
            effective_signals.append(bool(eff_f.iloc[i] > 1e-12))
            continue

        prev_dt = out.index[i - 1]
        old_h = eff_h.iloc[i - 1]
        old_f = float(eff_f.iloc[i - 1])
        new_h = eff_h.iloc[i]
        new_f = float(eff_f.iloc[i])

        if old_h == "cash" or old_f <= 1e-12:
            asset_component = 0.0
        else:
            asset_ret = close_df.loc[dt, old_h] / close_df.loc[prev_dt, old_h] - 1
            asset_component = old_f * float(asset_ret)
        cash_component = (1.0 - old_f) * CN_RF_DAILY

        if new_h == old_h:
            turnover = abs(new_f - old_f)
        else:
            turnover = old_f + new_f
        trade_cost = commission * float(turnover)

        asset_component_s.iloc[i] = float(asset_component)
        cash_component_s.iloc[i] = float(cash_component)
        trade_cost_s.iloc[i] = float(trade_cost)
        effective_signals.append(bool(turnover > 1e-12))

    raw_ret = asset_component_s + cash_component_s
    realized_vol = raw_ret.rolling(CN_VOL_WINDOW).std() * np.sqrt(CN_TRADING_DAYS)
    raw_scale = (CN_TARGET_VOL / realized_vol).clip(CN_MIN_LEV, CN_MAX_LEV)
    raw_scale = raw_scale.shift(1)
    if CN_SCALE_THRESHOLD > 0:
        _sa = raw_scale.values.copy()
        _last = np.nan
        for _i in range(len(_sa)):
            if np.isnan(_sa[_i]):
                continue
            if np.isnan(_last):
                _last = _sa[_i]
            elif abs(_sa[_i] - _last) >= CN_SCALE_THRESHOLD - 1e-9:
                _last = _sa[_i]
            else:
                _sa[_i] = _last
        raw_scale = pd.Series(_sa, index=out.index)

    scale_arr = raw_scale.fillna(1.0).to_numpy(copy=True)
    is_cash = eff_f.values <= 1e-12
    scale_arr[is_cash] = 1.0
    effective_weight = scale_arr * eff_f.values
    asset_component_s, cash_component_s, trade_cost_s = _suba_state_machine_return_components(
        eff_h,
        pd.Series(effective_weight, index=out.index),
        close_df,
        commission=commission,
    )
    effective_turnover = trade_cost_s / commission if commission else pd.Series(0.0, index=out.index)
    scale_tc = pd.Series(0.0, index=out.index, dtype=float)

    scaled_gross = 1.0 + asset_component_s.values + cash_component_s.values
    out["base_holding"] = base_holding
    out["base_fraction"] = base_fraction
    out["effective_holding"] = eff_h
    out["effective_fraction"] = eff_f
    out["active_score_overlay"] = active_score
    out["overlay_on"] = pd.Series(overlay_on, index=out.index, dtype=bool)
    out["overlay_triggered"] = pd.Series(overlay_triggered, index=out.index, dtype=bool)
    out["overlay_recovered"] = pd.Series(overlay_recovered, index=out.index, dtype=bool)
    out["trade_id"] = pd.Series(trade_ids, index=out.index, dtype="Int64")
    out["score_peak_overlay"] = pd.Series(score_peaks, index=out.index, dtype=float)
    out["score_decay_ratio_overlay"] = pd.Series(score_decay_ratios, index=out.index, dtype=float)
    out["waiting_for_new_peak"] = pd.Series(waiting_flags, index=out.index, dtype=bool)
    out["asset_component"] = asset_component_s
    out["cash_component"] = cash_component_s
    out["base_trade_cost"] = out["trade_cost"] if "trade_cost" in out.columns else np.nan
    out["effective_turnover"] = effective_turnover
    out["trade_cost"] = trade_cost_s
    out["scale_raw"] = raw_scale
    out["base_weight"] = eff_f.values
    out["weight"] = effective_weight
    out["realized_vol"] = realized_vol
    out["scale_tc"] = scale_tc
    out["return"] = scaled_gross * (1.0 - trade_cost_s.values) - 1.0
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["is_signal"] = pd.Series(effective_signals, index=out.index, dtype=bool)
    out["target"] = out["effective_holding"].where(out["is_signal"], None)
    return out


def _suba_same_side_overheat_features(close_df):
    features = {}
    for code in CN_STOCK_CODES:
        if code not in close_df.columns:
            continue
        price = close_df[code].astype(float)
        ma = price.rolling(CN_BIAS_N).mean()
        bias = price / ma - 1.0
        bias_mom = calc_bias_momentum(price)
        same_side = (bias > 0) & (bias_mom > 0) & bias.notna() & bias_mom.notna()
        features[code] = pd.DataFrame(
            {
                "bias": bias,
                "bias_mom": bias_mom,
                "same_side": same_side,
            },
            index=close_df.index,
        )
    return features


def _rebuild_suba_from_effective(base_result, close_df, eff_h, eff_f, signal_flags, extra_cols):
    out = base_result.copy()
    eff_h = pd.Series(eff_h, index=out.index, dtype=str)
    eff_f = pd.Series(eff_f, index=out.index, dtype=float)
    signal_flags = pd.Series(signal_flags, index=out.index, dtype=bool)

    asset_component_s = pd.Series(0.0, index=out.index, dtype=float)
    cash_component_s = pd.Series(0.0, index=out.index, dtype=float)
    trade_cost_s = pd.Series(0.0, index=out.index, dtype=float)

    for i, dt in enumerate(out.index):
        if i == 0:
            asset_component_s.iloc[i] = 0.0
            cash_component_s.iloc[i] = CN_RF_DAILY
            trade_cost_s.iloc[i] = CN_COMMISSION * float(eff_f.iloc[i])
            continue

        prev_dt = out.index[i - 1]
        old_h = eff_h.iloc[i - 1]
        old_f = float(eff_f.iloc[i - 1])
        new_h = eff_h.iloc[i]
        new_f = float(eff_f.iloc[i])

        if old_h == "cash" or old_f <= 1e-12:
            asset_component = 0.0
        else:
            asset_ret = close_df.loc[dt, old_h] / close_df.loc[prev_dt, old_h] - 1.0
            asset_component = old_f * float(asset_ret)
        cash_component = (1.0 - old_f) * CN_RF_DAILY
        turnover = abs(new_f - old_f) if new_h == old_h else old_f + new_f
        trade_cost = CN_COMMISSION * float(turnover)

        asset_component_s.iloc[i] = float(asset_component)
        cash_component_s.iloc[i] = float(cash_component)
        trade_cost_s.iloc[i] = float(trade_cost)

    raw_ret = asset_component_s + cash_component_s
    realized_vol = raw_ret.rolling(CN_VOL_WINDOW).std() * np.sqrt(CN_TRADING_DAYS)
    raw_scale = (CN_TARGET_VOL / realized_vol).clip(CN_MIN_LEV, CN_MAX_LEV).shift(1)
    if CN_SCALE_THRESHOLD > 0:
        _sa = raw_scale.values.copy()
        _last = np.nan
        for _i in range(len(_sa)):
            if np.isnan(_sa[_i]):
                continue
            if np.isnan(_last):
                _last = _sa[_i]
            elif abs(_sa[_i] - _last) >= CN_SCALE_THRESHOLD - 1e-9:
                _last = _sa[_i]
            else:
                _sa[_i] = _last
        raw_scale = pd.Series(_sa, index=out.index)

    scale_arr = raw_scale.fillna(1.0).to_numpy(copy=True)
    is_cash = eff_f.values <= 1e-12
    scale_arr[is_cash] = 1.0
    effective_weight = scale_arr * eff_f.values
    asset_component_s, cash_component_s, trade_cost_s = _suba_state_machine_return_components(
        eff_h,
        pd.Series(effective_weight, index=out.index),
        close_df,
        commission=CN_COMMISSION,
    )
    effective_turnover = trade_cost_s / CN_COMMISSION if CN_COMMISSION else pd.Series(0.0, index=out.index)
    scale_tc = pd.Series(0.0, index=out.index, dtype=float)

    scaled_gross = 1.0 + asset_component_s.values + cash_component_s.values
    out["effective_holding"] = eff_h
    out["effective_fraction"] = eff_f
    out["holding"] = eff_h
    out["holding_fraction"] = eff_f
    out["asset_component"] = asset_component_s
    out["cash_component"] = cash_component_s
    out["base_trade_cost"] = out["trade_cost"] if "trade_cost" in out.columns else np.nan
    out["effective_turnover"] = effective_turnover
    out["trade_cost"] = trade_cost_s
    out["scale_raw"] = raw_scale
    out["base_weight"] = eff_f.values
    out["weight"] = effective_weight
    out["realized_vol"] = realized_vol
    out["scale_tc"] = scale_tc
    out["return"] = scaled_gross * (1.0 - trade_cost_s.values) - 1.0
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["is_signal"] = signal_flags
    out["target"] = out["holding"].where(out["is_signal"], None)
    for key, value in extra_cols.items():
        out[key] = value
    return out


def apply_suba_volume_overlay(
    cn_result,
    close_df,
    volume_signal,
    volume_feature,
    scale=CN_SA_VOLUME_SCALE,
    rule_name=CN_SA_VOLUME_RULE_NAME,
):
    """Apply the formal Sub-A amount-contraction overlay.

    The signal is observed after close on date t, so the rebuilt path changes
    the effective exposure held from t close to the next close.
    """
    if not 0 <= scale <= 1:
        raise ValueError("scale must be in [0, 1].")
    if cn_result is None or len(cn_result) == 0:
        return cn_result

    pre_h = (
        cn_result["effective_holding"].fillna("cash").astype(str)
        if "effective_holding" in cn_result.columns
        else cn_result["holding"].fillna("cash").astype(str)
    )
    pre_f = (
        cn_result["effective_fraction"].fillna(0.0).astype(float)
        if "effective_fraction" in cn_result.columns
        else cn_result["holding_fraction"].fillna(0.0).astype(float)
    )
    signal_s = (
        pd.Series(volume_signal, dtype="boolean")
        .reindex(cn_result.index)
        .ffill()
        .fillna(False)
        .astype(bool)
    )
    scale_s = pd.Series(np.where(signal_s, scale, 1.0), index=cn_result.index, dtype=float)
    if volume_feature is not None and len(volume_feature) > 0 and "combined_scale" in volume_feature.columns:
        scale_s = (
            pd.to_numeric(volume_feature["combined_scale"], errors="coerce")
            .reindex(cn_result.index)
            .ffill()
            .fillna(1.0)
            .clip(lower=0.0, upper=1.0)
            .astype(float)
        )
        signal_s = scale_s < 1.0 - 1e-12
    eff_h = []
    eff_f = []
    signal_flags = []
    prev_h = "cash"
    prev_f = 0.0
    for dt in cn_result.index:
        h = str(pre_h.loc[dt])
        f = float(pre_f.loc[dt])
        if h in CN_STOCK_CODES and f > 1e-12 and bool(signal_s.loc[dt]):
            f *= float(scale_s.loc[dt])
        h2 = h if f > 1e-12 else "cash"
        eff_h.append(h2)
        eff_f.append(f)
        signal_flags.append((h2 != prev_h) or abs(f - prev_f) > 1e-12)
        prev_h = h2
        prev_f = f

    extra_cols = {
        "suba_volume_rule_on": signal_s,
        "suba_volume_rule_scale": scale_s,
        "suba_volume_rule_name": pd.Series(rule_name, index=cn_result.index),
    }
    if volume_feature is not None and len(volume_feature) > 0:
        aligned_feature = volume_feature.reindex(cn_result.index).copy()
        try:
            with pd.option_context("future.no_silent_downcasting", True):
                for col in aligned_feature.columns:
                    aligned_feature[col] = aligned_feature[col].ffill()
        except Exception:
            for col in aligned_feature.columns:
                aligned_feature[col] = aligned_feature[col].ffill()
        aligned_feature = aligned_feature.infer_objects()
        for col in aligned_feature.columns:
            extra_cols[f"suba_volume_{col}"] = aligned_feature[col]
        if "combined_unresolved" in aligned_feature.columns:
            extra_cols["suba_volume_unresolved"] = aligned_feature["combined_unresolved"].fillna(False).astype(bool)

    return _rebuild_suba_from_effective(
        cn_result,
        close_df,
        eff_h,
        eff_f,
        signal_flags,
        extra_cols,
    )


def apply_v78_suba_new_volume_overlay(
    new_result,
    close_df,
    volume_signal,
    volume_feature,
    scale=CN_SA_VOLUME_SCALE,
    rule_name=CN_SA_VOLUME_RULE_NAME,
):
    """Apply amount overlay to New A TV1.0 without re-running V7.7 Sub-A vol-scale."""
    if not 0 <= scale <= 1:
        raise ValueError("scale must be in [0, 1].")
    if new_result is None or len(new_result) == 0:
        return new_result

    out = new_result.copy()
    idx = out.index
    signal_s = (
        pd.Series(volume_signal, dtype="boolean")
        .reindex(idx)
        .ffill()
        .fillna(False)
        .astype(bool)
    )
    scale_s = pd.Series(np.where(signal_s, scale, 1.0), index=idx, dtype=float)
    if volume_feature is not None and len(volume_feature) > 0 and "combined_scale" in volume_feature.columns:
        scale_s = (
            pd.to_numeric(volume_feature["combined_scale"], errors="coerce")
            .reindex(idx)
            .ffill()
            .fillna(1.0)
            .clip(lower=0.0, upper=1.0)
            .astype(float)
        )
        signal_s = scale_s < 1.0 - 1e-12

    target_s = out.get("target", pd.Series("cash", index=idx)).fillna("cash").astype(str)
    base_holding_w = pd.to_numeric(out.get("weight", out.get("holding_fraction", 0.0)), errors="coerce").fillna(0.0)
    base_target_w = pd.to_numeric(out.get("target_weight", base_holding_w), errors="coerce").fillna(0.0)
    target_risky = target_s.ne("cash") & target_s.ne(CN_BOND_CODE)
    target_scale = scale_s.where(target_risky, 1.0)
    effective_target_w = (base_target_w * target_scale).clip(lower=0.0, upper=V78_SUBA_NEW_MAX_LEV)
    effective_target_s = target_s.where(effective_target_w > 1e-12, "cash")

    returns = []
    turnovers = []
    trade_costs = []
    cash_components = []
    signal_flags = []
    holdings = []
    holding_weights = []
    prev_h = "cash"
    prev_w = 0.0
    source_signal_s = out.get("is_signal", pd.Series(False, index=idx)).reindex(idx).fillna(False).astype(bool)
    for i, dt in enumerate(idx):
        h = prev_h
        h_w = float(prev_w)
        if i == 0 or h == "cash" or h_w <= 1e-12:
            raw_ret = 0.0
        else:
            prev_dt = idx[i - 1]
            raw_ret = float(close_df.loc[dt, h] / close_df.loc[prev_dt, h] - 1.0) if h in close_df.columns else 0.0
        asset_component = h_w * raw_ret
        cash_component = (1.0 - min(h_w, 1.0)) * float(CN_RF_DAILY)
        t = effective_target_s.loc[dt]
        t_w = float(effective_target_w.loc[dt])
        turnover = abs(t_w - h_w) if t == h else t_w + h_w
        trade_cost = float(CN_COMMISSION) * turnover
        returns.append((1.0 + asset_component + cash_component) * (1.0 - trade_cost) - 1.0)
        turnovers.append(turnover)
        trade_costs.append(trade_cost)
        cash_components.append(cash_component)
        holdings.append(h)
        holding_weights.append(h_w)
        signal_flags.append(
            bool(source_signal_s.loc[dt])
            or t != h
            or abs(t_w - h_w) > 1e-4
        )
        prev_h = t
        prev_w = t_w

    out["base_weight_before_suba_volume"] = base_holding_w
    out["base_target_weight_before_suba_volume"] = base_target_w
    out["suba_volume_rule_on"] = signal_s
    out["suba_volume_rule_scale"] = scale_s
    out["suba_volume_rule_name"] = pd.Series(rule_name, index=idx)
    if volume_feature is not None and len(volume_feature) > 0:
        aligned_feature = volume_feature.reindex(idx).copy()
        try:
            with pd.option_context("future.no_silent_downcasting", True):
                for col in aligned_feature.columns:
                    aligned_feature[col] = aligned_feature[col].ffill()
        except Exception:
            for col in aligned_feature.columns:
                aligned_feature[col] = aligned_feature[col].ffill()
        aligned_feature = aligned_feature.infer_objects()
        for col in aligned_feature.columns:
            out[f"suba_volume_{col}"] = aligned_feature[col]
    holding_w = pd.Series(holding_weights, index=idx, dtype=float)
    out["holding_fraction"] = holding_w
    out["base_weight"] = holding_w
    out["weight"] = holding_w
    out["target_weight"] = effective_target_w
    out["cash_component"] = pd.Series(cash_components, index=idx, dtype=float)
    out["turnover"] = pd.Series(turnovers, index=idx, dtype=float)
    out["trade_cost"] = pd.Series(trade_costs, index=idx, dtype=float)
    out["return"] = pd.Series(returns, index=idx, dtype=float)
    out["nav"] = (1.0 + out["return"].fillna(0.0)).cumprod()
    out["is_signal"] = pd.Series(signal_flags, index=idx, dtype=bool)
    out["holding"] = pd.Series(holdings, index=idx, dtype=object)
    out["target"] = effective_target_s.where(out["is_signal"], None)
    return out


def apply_suba_same_side_overheat_overlay(
    cn_result,
    close_df,
    enter_threshold,
    exit_threshold,
    derisk_scale=0.0,
):
    """Cut Sub-A equity exposure only during extreme same-side upside bias.

    The signal is evaluated after the daily close and affects the next row's
    effective holding, matching the existing close-to-close Sub-A backtest path.
    """
    if not 0 < exit_threshold < enter_threshold:
        raise ValueError("exit_threshold must be in (0, enter_threshold).")
    if not 0 <= derisk_scale <= 1:
        raise ValueError("derisk_scale must be in [0, 1].")
    if cn_result is None or len(cn_result) == 0:
        return cn_result

    required = {"holding", "holding_fraction", "return"}
    missing = required.difference(cn_result.columns)
    if missing:
        raise KeyError(f"Missing required Sub-A columns: {sorted(missing)}")

    out = cn_result.copy()
    features = _suba_same_side_overheat_features(close_df)
    pre_h = out["effective_holding"].fillna("cash").astype(str) if "effective_holding" in out.columns else out["holding"].fillna("cash").astype(str)
    pre_f = out["effective_fraction"].fillna(0.0).astype(float) if "effective_fraction" in out.columns else out["holding_fraction"].fillna(0.0).astype(float)

    overheat_state = False
    prev_effective_h = "cash"
    prev_effective_f = 0.0
    prev_pre_holding = None
    eff_h, eff_f, signals = [], [], []
    bias_vals, mom_vals, same_side_vals = [], [], []
    state_vals, trigger_vals, recover_vals = [], [], []

    for i, dt in enumerate(out.index):
        holding = str(pre_h.iloc[i])
        fraction = float(pre_f.iloc[i])
        if prev_pre_holding is not None and holding != prev_pre_holding:
            overheat_state = False
        prev_pre_holding = holding
        eligible = holding in CN_STOCK_CODES and fraction > 1e-12

        bias = np.nan
        mom = np.nan
        same_side = False
        if eligible and holding in features and dt in features[holding].index:
            row = features[holding].loc[dt]
            bias = float(row["bias"]) if pd.notna(row["bias"]) else np.nan
            mom = float(row["bias_mom"]) if pd.notna(row["bias_mom"]) else np.nan
            same_side = bool(row["same_side"]) if pd.notna(row["same_side"]) else False

        current_state = overheat_state and eligible
        out_f = fraction * float(derisk_scale) if current_state else fraction
        out_h = holding if out_f > 1e-12 else "cash"
        triggered_today = False
        recovered_today = False

        next_state = overheat_state
        if eligible and pd.notna(bias) and same_side:
            if next_state:
                if bias <= exit_threshold:
                    next_state = False
                    recovered_today = True
            elif bias >= enter_threshold:
                next_state = True
                triggered_today = True
        elif next_state:
            next_state = False
            recovered_today = True

        signal = (out_h != prev_effective_h) or (abs(out_f - prev_effective_f) > 1e-12)
        eff_h.append(out_h)
        eff_f.append(out_f)
        signals.append(signal)
        bias_vals.append(bias)
        mom_vals.append(mom)
        same_side_vals.append(same_side)
        state_vals.append(current_state)
        trigger_vals.append(triggered_today)
        recover_vals.append(recovered_today)

        overheat_state = next_state
        prev_effective_h = out_h
        prev_effective_f = out_f

    extra = {
        "pre_suba_overheat_holding": pre_h,
        "pre_suba_overheat_fraction": pre_f,
        "suba_same_side_overheat_bias": pd.Series(bias_vals, index=out.index, dtype=float),
        "suba_same_side_overheat_bias_mom": pd.Series(mom_vals, index=out.index, dtype=float),
        "suba_same_side_overheat_signal": pd.Series(same_side_vals, index=out.index, dtype=bool),
        "suba_same_side_overheat_on": pd.Series(state_vals, index=out.index, dtype=bool),
        "suba_same_side_overheat_triggered": pd.Series(trigger_vals, index=out.index, dtype=bool),
        "suba_same_side_overheat_recovered": pd.Series(recover_vals, index=out.index, dtype=bool),
    }
    out = _rebuild_suba_from_effective(out, close_df, eff_h, eff_f, signals, extra)
    out.attrs["suba_same_side_overheat_overlay"] = {
        "enter_threshold": float(enter_threshold),
        "exit_threshold": float(exit_threshold),
        "derisk_scale": float(derisk_scale),
        "overlay_days": int(out["suba_same_side_overheat_on"].sum()),
        "overlay_ratio": float(out["suba_same_side_overheat_on"].mean()),
        "trigger_count": int(out["suba_same_side_overheat_triggered"].sum()),
        "recovery_count": int(out["suba_same_side_overheat_recovered"].sum()),
    }
    return out


def _dk_signal_days(close_df, start_idx):
    week_best = {}
    for i in range(start_idx, len(close_df)):
        dt = close_df.index[i]
        dow = dt.dayofweek
        yr, wk, _ = dt.isocalendar()
        key = (yr, wk)
        if key not in week_best or dow > week_best[key][1]:
            week_best[key] = (i, dow)
    return {v[0] for v in week_best.values()}

def rolling_r2_fast(series, window):  # kept for backward compat, see also calc_rolling_r2
    """滚动R²: 衡量价差曲线的线性趋势强度 (0~1, 越高趋势越明确)."""
    y = series.values.astype(float)
    n = len(y)
    r2 = np.full(n, np.nan)
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    ss_x = ((x - x_mean)**2).sum()
    for i in range(window - 1, n):
        yi = y[i - window + 1:i + 1]
        if np.any(np.isnan(yi)):
            continue
        y_mean = yi.mean()
        ss_y = ((yi - y_mean)**2).sum()
        if ss_y < 1e-15:
            r2[i] = 0.0
            continue
        ss_xy = ((x - x_mean) * (yi - y_mean)).sum()
        r2[i] = max(0.0, (ss_xy**2) / (ss_x * ss_y))
    return pd.Series(r2, index=series.index)

def _dk_calc_bias_momentum(series, bias_n, mom_day):
    """乖离动量 for DK pairs"""
    prices = series.values.astype(float)
    n = len(prices)
    result = np.full(n, np.nan)
    ma = series.rolling(bias_n).mean().values
    total_lookback = bias_n + mom_day - 2
    x = np.arange(mom_day, dtype=float)
    weights = np.linspace(1.0, 10.0, mom_day)
    w_sum = float(weights.sum())
    x_bar = float((weights * x).sum() / w_sum)
    denom = float((weights * (x - x_bar) ** 2).sum())
    for i in range(total_lookback, n):
        bias_window = np.empty(mom_day)
        valid = True
        for j in range(mom_day):
            idx = i - mom_day + 1 + j
            if np.isnan(ma[idx]) or ma[idx] < 1e-10 or np.isnan(prices[idx]):
                valid = False; break
            bias_window[j] = prices[idx] / ma[idx]
        if not valid or bias_window[0] < 1e-10: continue
        y_bar = float((weights * bias_window).sum() / w_sum)
        slope = float((weights * (x - x_bar) * (bias_window - y_bar)).sum() / denom)
        result[i] = slope / float(bias_window[0]) * 10000.0
    return pd.Series(result, index=series.index)


def _dk_calc_bias_momentum_r2(series, bias_n, mom_day):
    prices = series.values.astype(float)
    n = len(prices)
    result = np.full(n, np.nan)
    ma = series.rolling(bias_n).mean().values
    total_lookback = bias_n + mom_day - 2
    x = np.arange(mom_day, dtype=float)
    weights = np.linspace(1.0, 10.0, mom_day)
    w_sum = float(weights.sum())
    x_bar = float((weights * x).sum() / w_sum)
    x_dev = x - x_bar
    denom = float((weights * x_dev ** 2).sum())
    for i in range(total_lookback, n):
        bias_window = np.empty(mom_day)
        valid = True
        for j in range(mom_day):
            idx = i - mom_day + 1 + j
            if np.isnan(ma[idx]) or ma[idx] < 1e-10 or np.isnan(prices[idx]):
                valid = False
                break
            bias_window[j] = prices[idx] / ma[idx]
        if not valid:
            continue
        y_bar = float((weights * bias_window).sum() / w_sum)
        y_dev = bias_window - y_bar
        slope = float((weights * x_dev * y_dev).sum() / denom)
        fitted = y_bar + slope * x_dev
        sse = float((weights * (bias_window - fitted) ** 2).sum())
        sst = float((weights * y_dev ** 2).sum())
        result[i] = 1.0 - sse / sst if sst > 1e-18 else np.nan
    return pd.Series(result, index=series.index)


def _run_single_pair_dk(a_prices, b_prices, r2_quality_enabled=None):
    """对单个配对运行乖离动量DK策略, 返回 (strategy_ret, abs_bias_mom, pair_data) 或 (None, None, None)"""
    d = pd.DataFrame({'a': a_prices, 'b': b_prices}).dropna()
    if len(d) < CN_DK_BIAS_N + CN_DK_MOM_DAY + CN_DK_VOL_WINDOW + 50:
        return None, None, None
    d['a_ret'] = d['a'].pct_change()
    d['b_ret'] = d['b'].pct_change()
    d['spread_ret'] = d['a_ret'] - d['b_ret']
    d = d.dropna(subset=['a_ret', 'b_ret'])
    d['ratio'] = d['a'] / d['b']
    d['bias_mom'] = _dk_calc_bias_momentum(d['ratio'], CN_DK_BIAS_N, CN_DK_MOM_DAY)
    d['signal_r2'] = _dk_calc_bias_momentum_r2(d['ratio'], CN_DK_BIAS_N, CN_DK_MOM_DAY)
    d['rank_score'] = d['bias_mom'].abs()
    if r2_quality_enabled is None:
        r2_quality_enabled = CN_DK_R2_QUALITY_ENABLED
    if r2_quality_enabled:
        d['rank_score'] = d['rank_score'].where(d['signal_r2'] >= CN_DK_R2_QUALITY_THRESHOLD)
    n = len(d)
    start_idx = max(CN_DK_BIAS_N + CN_DK_MOM_DAY, CN_DK_VOL_WINDOW) + 1
    # 方向信号: bias_mom > 0 → +1, 否则 -1 (无冷却期)
    d['signal'] = np.nan
    valid = d['bias_mom'].notna() & (np.arange(n) >= start_idx)
    d.loc[valid, 'signal'] = np.where(d.loc[valid, 'bias_mom'] > 0, 1, -1)
    d['signal'] = d['signal'].ffill()
    d['signal'] = d['signal'].astype(float)
    d['position'] = d['signal'].shift(1)
    d['raw_ret'] = d['position'] * d['spread_ret']
    d = d.dropna(subset=['position', 'raw_ret'])
    # 波动率缩放
    d['realized_vol'] = d['raw_ret'].rolling(CN_DK_VOL_WINDOW).std() * np.sqrt(CN_DK_TRADING_DAYS)
    if CN_DK_VOL_SCALE_ENABLED:
        d['scale'] = (CN_DK_TARGET_VOL / d['realized_vol']).clip(CN_DK_MIN_LEV, CN_DK_MAX_LEV)
        d['scale'] = d['scale'].shift(1)
        d['scale_raw'] = d['scale'].copy()  # 保存阈值过滤前的原始scale
    else:
        d['scale'] = 1.0
        d['scale_raw'] = 1.0
    if CN_DK_VOL_SCALE_ENABLED and CN_DK_SCALE_THRESHOLD > 0:
        _sa = d['scale'].values.copy()
        _last = np.nan
        for _i in range(len(_sa)):
            if np.isnan(_sa[_i]): continue
            if np.isnan(_last): _last = _sa[_i]
            elif abs(_sa[_i] - _last) >= CN_DK_SCALE_THRESHOLD - 1e-9: _last = _sa[_i]
            else: _sa[_i] = _last
        d['scale'] = _sa
    d['strategy_ret'] = d['raw_ret'] * d['scale']
    d = d.dropna(subset=['strategy_ret'])
    # 交易成本
    pos_prev = d['position'].shift(1)
    is_flip = (d['position'] != pos_prev) & pos_prev.notna()
    is_initial = d['position'].notna() & pos_prev.isna()
    if CN_DK_COMMISSION > 0:
        d['tc'] = 0.0
        d.loc[is_flip, 'tc'] = 4 * CN_DK_COMMISSION * d['scale'][is_flip]
        d.loc[is_initial, 'tc'] = 2 * CN_DK_COMMISSION * d['scale'][is_initial]
        _chg = d['scale'].diff().abs().fillna(0)
        _only = ~is_flip & ~is_initial & d['position'].notna()
        d.loc[_only, 'tc'] += 2 * CN_DK_COMMISSION * _chg[_only]
        d['strategy_ret'] = (1 + d['strategy_ret']) * (1 - d['tc']) - 1
    return d['strategy_ret'], d['rank_score'], d

def _build_top_n_dk(rets_df, signals_df, n=1):
    """合并多配对策略: 每天选信号最强的n个配对, 等权合并"""
    common_idx = rets_df.index.intersection(signals_df.index)
    rets_df = rets_df.reindex(common_idx)
    signals_df = signals_df.reindex(common_idx)
    signals_shifted = signals_df.shift(1)
    combined = pd.Series(0.0, index=common_idx)
    for i in range(len(common_idx)):
        row_sig = signals_shifted.iloc[i].dropna()
        if len(row_sig) == 0: continue
        top_pairs = row_sig.nlargest(n).index.tolist()
        day_ret = 0.0
        cnt = 0
        for p in top_pairs:
            r = rets_df.iloc[i].get(p, np.nan)
            if not np.isnan(r):
                day_ret += r
                cnt += 1
        if cnt > 0:
            combined.iloc[i] = day_ret / cnt
    return combined


def _dk_position_legs(pair, direction, scale):
    if pair is None or str(pair) == "none" or int(direction or 0) == 0 or float(scale or 0.0) <= 1e-12:
        return {}
    parts = str(pair).split("/")
    if len(parts) != 2:
        return {}
    a, b = parts[0].strip(), parts[1].strip()
    if not a or not b:
        return {}
    direction = int(direction)
    scale = float(scale)
    return {a: direction * scale, b: -direction * scale}

def _dk_leg_fields(pair, direction, active=True):
    if not active or pair is None or str(pair) == "none" or int(direction or 0) == 0:
        return None, None, None, None
    parts = str(pair).split("/")
    if len(parts) != 2:
        return None, None, None, None
    a, b = parts[0].strip(), parts[1].strip()
    if not a or not b:
        return None, None, None, None
    if int(direction) == 1:
        return a, b, a, b
    return a, b, b, a

def _sync_dk_execution_fields(dk_result, weight_change_threshold=0.001):
    """Make DK display/rebalance fields reflect actual executed legs."""
    if dk_result is None or len(dk_result) == 0:
        return dk_result
    out = dk_result.copy()
    idx = out.index
    top_pair = out.get("top_pair", pd.Series("none", index=idx)).fillna("none").astype(str)
    direction_src = out.get("actual_direction", out.get("direction", pd.Series(0, index=idx)))
    direction = pd.to_numeric(direction_src, errors="coerce").fillna(0).astype(int)
    weight = pd.to_numeric(out.get("weight", pd.Series(1.0, index=idx)), errors="coerce").fillna(0.0)

    active_pairs = []
    effective_dirs = []
    holdings = []
    pair_a_list = []
    pair_b_list = []
    long_leg_list = []
    short_leg_list = []
    for pair, dir_val, w in zip(top_pair, direction, weight):
        active = pair != "none" and int(dir_val) != 0 and abs(float(w)) > 1e-12
        eff_dir = int(dir_val) if active else 0
        active_pair = pair if active else "none"
        pair_a, pair_b, long_leg, short_leg = _dk_leg_fields(pair, eff_dir, active=active)
        active_pairs.append(active_pair)
        effective_dirs.append(eff_dir)
        holdings.append(f"{pair}_{eff_dir}" if active else "none_0")
        pair_a_list.append(pair_a)
        pair_b_list.append(pair_b)
        long_leg_list.append(long_leg)
        short_leg_list.append(short_leg)

    active_pair_s = pd.Series(active_pairs, index=idx, dtype=object)
    direction_s = pd.Series(effective_dirs, index=idx, dtype=int)
    pair_changed = active_pair_s.ne(active_pair_s.shift(1))
    direction_changed = direction_s.ne(direction_s.shift(1))
    active_mask = active_pair_s.ne("none") & direction_s.ne(0)
    effective_weight = weight.where(active_mask, 0.0)
    scale_rebalanced = effective_weight.diff().abs().fillna(0.0) > float(weight_change_threshold)
    if len(out) > 0:
        pair_changed.iloc[0] = False
        direction_changed.iloc[0] = False
        scale_rebalanced.iloc[0] = False

    out["direction"] = direction_s
    out["holding"] = pd.Series(holdings, index=idx, dtype=object)
    out["pair_a"] = pd.Series(pair_a_list, index=idx, dtype=object)
    out["pair_b"] = pd.Series(pair_b_list, index=idx, dtype=object)
    out["long_leg"] = pd.Series(long_leg_list, index=idx, dtype=object)
    out["short_leg"] = pd.Series(short_leg_list, index=idx, dtype=object)
    out["pair_changed"] = pair_changed.astype(bool)
    out["direction_changed"] = direction_changed.astype(bool)
    out["scale_rebalanced"] = scale_rebalanced.astype(bool)
    out["is_signal"] = (pair_changed | direction_changed | scale_rebalanced).astype(bool)
    out["target"] = out["holding"].where(out["is_signal"], None)
    return out


def _rebuild_dk_actual_execution_costs(dk_result, pair_data, commission=CN_DK_COMMISSION):
    """Rebuild DK Top-1 returns from the actually selected pair and charge actual turnover."""
    if dk_result is None or len(dk_result) == 0:
        return dk_result
    out = dk_result.copy()
    returns = []
    costs = []
    turnovers = []
    gross_returns = []
    actual_positions = []
    actual_directions = []
    prev_legs = {}

    for dt, row in out.iterrows():
        pair = str(row.get("top_pair", "none"))
        pdata = pair_data.get(pair) if pair != "none" else None
        scale = float(row.get("weight", 1.0))
        direction = 0
        gross_ret = 0.0
        if pdata is not None and dt in pdata.index:
            prow = pdata.loc[dt]
            direction = int(prow.get("position", 0)) if pd.notna(prow.get("position", np.nan)) else 0
            raw_ret = prow.get("raw_ret", np.nan)
            if pd.notna(raw_ret):
                gross_ret = float(raw_ret) * scale
            else:
                tc = float(prow.get("tc", 0.0)) if pd.notna(prow.get("tc", np.nan)) else 0.0
                strategy_ret = float(prow.get("strategy_ret", 0.0)) if pd.notna(prow.get("strategy_ret", np.nan)) else 0.0
                gross_ret = (1.0 + strategy_ret) / (1.0 - tc) - 1.0 if tc < 1.0 else strategy_ret

        key = f"{pair}_{direction}" if pair != "none" and direction != 0 and scale > 1e-12 else None
        new_legs = _dk_position_legs(pair, direction, scale)
        turnover = _dict_weight_turnover(prev_legs, new_legs)
        trade_cost = float(commission) * max(turnover, 0.0)

        gross_returns.append(gross_ret)
        turnovers.append(turnover)
        costs.append(trade_cost)
        returns.append((1.0 + gross_ret) * (1.0 - trade_cost) - 1.0)
        actual_positions.append(key or "none")
        actual_directions.append(direction)
        prev_legs = new_legs

    out["return_before_dk_execution_cost"] = pd.Series(gross_returns, index=out.index)
    out["dk_execution_turnover"] = pd.Series(turnovers, index=out.index)
    out["dk_execution_cost"] = pd.Series(costs, index=out.index)
    out["actual_position"] = pd.Series(actual_positions, index=out.index)
    out["actual_direction"] = pd.Series(actual_directions, index=out.index)
    out["return"] = pd.Series(returns, index=out.index)
    out["nav"] = (1.0 + out["return"]).cumprod()
    return _sync_dk_execution_fields(out)

def _rebuild_dk_effective_execution_costs(dk_result, pair_data, commission=CN_DK_COMMISSION):
    """Rebuild DK returns/costs from final effective long/short legs."""
    if dk_result is None or len(dk_result) == 0:
        return dk_result
    out = dk_result.copy()
    returns = []
    costs = []
    turnovers = []
    gross_returns = []
    actual_positions = []
    actual_directions = []
    prev_legs = {}

    for dt, row in out.iterrows():
        pair = str(row.get("top_pair", "none"))
        pdata = pair_data.get(pair) if pair != "none" else None
        total_scale = float(row.get("weight", 0.0) or 0.0)
        direction = int(row.get("direction", 0) or 0)
        raw_pair_ret = 0.0
        if pdata is not None and dt in pdata.index:
            prow = pdata.loc[dt]
            direction = int(prow.get("position", direction)) if pd.notna(prow.get("position", np.nan)) else direction
            raw_ret = prow.get("raw_ret", np.nan)
            if pd.notna(raw_ret):
                raw_pair_ret = float(raw_ret)
            else:
                base_scale = float(row.get("base_weight", row.get("weight", 1.0)) or 1.0)
                base_gross = float(row.get("return_before_dk_execution_cost", 0.0) or 0.0)
                raw_pair_ret = base_gross / base_scale if abs(base_scale) > 1e-12 else 0.0

        if pair == "none" or direction == 0 or abs(total_scale) <= 1e-12:
            new_legs = {}
            key = None
            gross_ret = 0.0
        else:
            new_legs = _dk_position_legs(pair, direction, total_scale)
            key = f"{pair}_{direction}"
            gross_ret = raw_pair_ret * total_scale
        turnover = _dict_weight_turnover(prev_legs, new_legs)
        trade_cost = float(commission) * max(turnover, 0.0)

        gross_returns.append(gross_ret)
        turnovers.append(turnover)
        costs.append(trade_cost)
        returns.append((1.0 + gross_ret) * (1.0 - trade_cost) - 1.0)
        actual_positions.append(key or "none")
        actual_directions.append(direction if key else 0)
        prev_legs = new_legs

    out["return_before_dk_execution_cost"] = pd.Series(gross_returns, index=out.index)
    out["dk_execution_turnover"] = pd.Series(turnovers, index=out.index)
    out["dk_execution_cost"] = pd.Series(costs, index=out.index)
    out["dk_overlay_execution_cost"] = 0.0
    out["same_side_overheat_tc"] = 0.0
    out["actual_position"] = pd.Series(actual_positions, index=out.index)
    out["actual_direction"] = pd.Series(actual_directions, index=out.index)
    out["return"] = pd.Series(returns, index=out.index)
    out["nav"] = (1.0 + out["return"]).cumprod()
    return _sync_dk_execution_fields(out)

def run_dk_strategy(cn_close, cn_dk_close, official_pair_order=None, r2_quality_enabled=None):
    """Sub-A-DK V6.5: 多配对Top-1 + 乖离动量 + VolScaling.
    v6.5在v6.2基础上增加策略级DD risk gate, 其余信号逻辑不变.
    Returns: DataFrame with [return, nav, holding, is_signal, target, weight, ...]
    """
    from itertools import combinations
    if official_pair_order is None:
        official_pair_order = ADK_OFFICIAL_PAIR_ORDER
    official_pairs = set(official_pair_order)
    if r2_quality_enabled is None:
        r2_quality_enabled = CN_DK_R2_QUALITY_ENABLED
    # Build index series
    idx_series = {}
    for name, info in CN_DK_INDICES.items():
        src_df = cn_dk_close if info['src'] == 'dk' else cn_close
        if info['col'] in src_df.columns:
            idx_series[name] = src_df[info['col']].rename(info['col'])
    pairs_all = [
        (a_name, b_name)
        for a_name, b_name in combinations(idx_series.keys(), 2)
        if f"{a_name}/{b_name}" in official_pairs
    ]
    pair_rets = {}
    pair_abs_mom = {}
    pair_data = {}
    for a_name, b_name in pairs_all:
        label = f"{a_name}/{b_name}"
        ret, abs_mom, pdata = _run_single_pair_dk(
            idx_series[a_name],
            idx_series[b_name],
            r2_quality_enabled=r2_quality_enabled,
        )
        if ret is not None:
            pair_rets[label] = ret
            pair_abs_mom[label] = abs_mom
            pair_data[label] = pdata
    if not pair_rets:
        raise ValueError("No valid DK pairs")
    rets_df = pd.DataFrame(pair_rets)
    signals_df = pd.DataFrame(pair_abs_mom)
    combined_ret = _build_top_n_dk(rets_df, signals_df, CN_DK_TOP_N)
    # Determine top-1 pair and direction for each day
    signals_shifted = signals_df.shift(1)
    common_idx = combined_ret.index
    top_pair_list = []
    top_dir_list = []
    for i in range(len(common_idx)):
        date = common_idx[i]
        row_sig = signals_shifted.loc[date].dropna() if date in signals_shifted.index else pd.Series(dtype=float)
        if len(row_sig) == 0:
            top_pair_list.append("none")
            top_dir_list.append(0)
        else:
            best = row_sig.idxmax()
            top_pair_list.append(best)
            # Execution direction is prior-day signal, stored as position.
            if best in pair_data and date in pair_data[best].index:
                pos_val = pair_data[best].loc[date, 'position'] if 'position' in pair_data[best].columns else np.nan
                top_dir_list.append(int(pos_val) if not np.isnan(pos_val) else 0)
            else:
                top_dir_list.append(0)
    # 从top-1配对中提取实际的scale/scale_raw/realized_vol
    _weight_arr = []
    _scale_raw_arr = []
    _realized_vol_arr = []
    for i in range(len(common_idx)):
        date = common_idx[i]
        pair = top_pair_list[i]
        if pair != "none" and pair in pair_data and date in pair_data[pair].index:
            pd_row = pair_data[pair].loc[date]
            _w = pd_row['scale'] if 'scale' in pd_row.index and not np.isnan(pd_row['scale']) else 1.0
            _sr = pd_row['scale_raw'] if 'scale_raw' in pd_row.index and not np.isnan(pd_row['scale_raw']) else _w
            _rv = pd_row['realized_vol'] if 'realized_vol' in pd_row.index else np.nan
        else:
            _w, _sr, _rv = 1.0, 1.0, np.nan
        _weight_arr.append(_w)
        _scale_raw_arr.append(_sr)
        _realized_vol_arr.append(_rv)
    # P1-1修复: 正确计算is_signal (不再写死False)
    top_pair_series = pd.Series(top_pair_list, index=common_idx)
    top_dir_series = pd.Series(top_dir_list, index=common_idx)
    pair_changed = top_pair_series.ne(top_pair_series.shift(1))
    direction_changed = top_dir_series.ne(top_dir_series.shift(1))
    is_signal = pair_changed | direction_changed
    pair_changed.iloc[0] = False
    direction_changed.iloc[0] = False
    is_signal.iloc[0] = False
    # P2-2修复: 添加结构化持仓字段
    _pair_a_list, _pair_b_list = [], []
    _long_leg_list, _short_leg_list = [], []
    for p, d in zip(top_pair_list, top_dir_list):
        pair_a, pair_b, long_leg, short_leg = _dk_leg_fields(p, d, active=(p != "none" and d != 0))
        _pair_a_list.append(pair_a)
        _pair_b_list.append(pair_b)
        _long_leg_list.append(long_leg)
        _short_leg_list.append(short_leg)
    result = pd.DataFrame({
        'return': combined_ret,
        'nav': (1 + combined_ret).cumprod(),
        'top_pair': top_pair_series,
        'direction': top_dir_series,
        'holding': [f"{p}_{d}" for p, d in zip(top_pair_list, top_dir_list)],
        'pair_a': _pair_a_list,
        'pair_b': _pair_b_list,
        'long_leg': _long_leg_list,
        'short_leg': _short_leg_list,
        'pair_changed': pair_changed,
        'direction_changed': direction_changed,
        'is_signal': is_signal,
        'target': None,
        'weight': _weight_arr,
        'scale_raw': _scale_raw_arr,
        'realized_vol': _realized_vol_arr,
    }, index=common_idx)
    result = _rebuild_dk_actual_execution_costs(result, pair_data, CN_DK_COMMISSION)
    # Store extra data for display
    result.attrs['pair_rets'] = pair_rets
    result.attrs['pair_abs_mom'] = pair_abs_mom
    result.attrs['pair_data'] = pair_data
    result.attrs['rets_df'] = rets_df
    result.attrs['signals_df'] = signals_df
    return result


def _v78_all_adk_pair_order():
    names = list(CN_DK_INDICES.keys())
    pairs = []
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            pairs.append(f"{left}/{right}")
    return tuple(pairs)


def apply_v78_adk_score_overheat(dk_result, enter=80.0, exit=20.0, derisk_scale=0.0):
    if dk_result is None or len(dk_result) == 0:
        return dk_result
    out = dk_result.copy()
    active_score = _extract_active_pair_score(out)
    base_ret = out.get("return_before_dk_execution_cost", out["return"]).fillna(0.0).astype(float)
    base_weight = out.get("weight", pd.Series(1.0, index=out.index)).fillna(1.0).astype(float)
    scales = []
    costs = []
    on = False
    prev_scale = 1.0
    prev_score = np.nan
    for dt in out.index:
        score_for_today = prev_score
        if pd.notna(score_for_today):
            if on and float(score_for_today) <= float(exit):
                on = False
            elif (not on) and float(score_for_today) >= float(enter):
                on = True
        cur_scale = float(derisk_scale) if on else 1.0
        delta = abs(cur_scale - prev_scale)
        costs.append(2.0 * CN_DK_COMMISSION * float(base_weight.loc[dt]) * delta if delta > 1e-12 else 0.0)
        scales.append(cur_scale)
        prev_scale = cur_scale
        prev_score = active_score.loc[dt]
    scale_s = pd.Series(scales, index=out.index, dtype=float)
    cost_s = pd.Series(costs, index=out.index, dtype=float)
    out["v78_score_overheat_score"] = active_score
    out["v78_score_overheat_scale"] = scale_s
    out["v78_score_overheat_on"] = scale_s < 0.999999
    # Diagnostic only: effective leg-turnover costs are rebuilt below.
    out["v78_score_overheat_cost_indicative"] = cost_s
    out["return_before_v78_score_overheat"] = base_ret
    out["base_weight_before_v78_score_hot"] = base_weight
    out["weight"] = base_weight * scale_s
    return _rebuild_dk_effective_execution_costs(
        out,
        out.attrs.get("pair_data", {}),
        CN_DK_COMMISSION,
    )


def run_v78_adk_new_primary(cn_close, cn_dk_close):
    result = run_dk_strategy(
        cn_close,
        cn_dk_close,
        official_pair_order=_v78_all_adk_pair_order(),
        r2_quality_enabled=False,
    )
    return apply_v78_adk_score_overheat(
        result,
        enter=V78_ADK_NEW_SCORE_HOT_ENTER,
        exit=V78_ADK_NEW_SCORE_HOT_EXIT,
        derisk_scale=V78_ADK_NEW_SCORE_HOT_SCALE,
    )


def _v78_adk_aggregate_asset_weights(row):
    net = {}
    legs = row.get("final_long_short_legs", {}) or {}
    for leg_key in ("v77", "new"):
        leg = legs.get(leg_key, {}) or {}
        weight = float(leg.get("weight", 0.0) or 0.0)
        long_leg = leg.get("long_leg")
        short_leg = leg.get("short_leg")
        if long_leg:
            net[long_leg] = net.get(long_leg, 0.0) + weight
        if short_leg:
            net[short_leg] = net.get(short_leg, 0.0) - weight
    return {asset: exposure for asset, exposure in sorted(net.items()) if abs(exposure) > 1e-12}


def blend_v78_adk_results(v77_result, new_result):
    common_index = v77_result.dropna(subset=["return"]).index.intersection(
        new_result.dropna(subset=["return"]).index
    )
    if common_index.empty:
        raise ValueError("V7.9 ADK blend has no overlapping return window.")
    v77 = v77_result.reindex(common_index)
    new = new_result.reindex(common_index)
    out = v77.copy()
    out["v78_adk_v77_return"] = v77["return"].astype(float)
    out["v78_adk_new_return"] = new["return"].astype(float)
    out["return"] = V78_ADK_V77_WEIGHT * out["v78_adk_v77_return"] + V78_ADK_NEW_PRIMARY_WEIGHT * out["v78_adk_new_return"]
    out["nav"] = (1.0 + out["return"].fillna(0.0)).cumprod()
    out["v78_adk_v77_holding"] = v77.get("holding", "none_0")
    out["v78_adk_new_holding"] = new.get("holding", "none_0")
    out["v78_adk_v77_weight"] = pd.to_numeric(v77.get("weight", 0.0), errors="coerce").fillna(0.0)
    out["v78_adk_new_weight"] = pd.to_numeric(new.get("weight", 0.0), errors="coerce").fillna(0.0)
    out["v78_adk_final_exposure"] = (
        V78_ADK_V77_WEIGHT * out["v78_adk_v77_weight"]
        + V78_ADK_NEW_PRIMARY_WEIGHT * out["v78_adk_new_weight"]
    )
    out["final_exposure"] = out["v78_adk_final_exposure"]
    v77_long = v77.get("long_leg", pd.Series(None, index=common_index))
    v77_short = v77.get("short_leg", pd.Series(None, index=common_index))
    new_long = new.get("long_leg", pd.Series(None, index=common_index))
    new_short = new.get("short_leg", pd.Series(None, index=common_index))
    out["final_long_short_legs"] = [
        {
            "v77": {
                "holding": vh,
                "long_leg": vl,
                "short_leg": vs,
                "weight": V78_ADK_V77_WEIGHT * float(vw),
            },
            "new": {
                "holding": nh,
                "long_leg": nl,
                "short_leg": ns,
                "weight": V78_ADK_NEW_PRIMARY_WEIGHT * float(nw),
            },
        }
        for vh, vl, vs, vw, nh, nl, ns, nw in zip(
            out["v78_adk_v77_holding"],
            v77_long,
            v77_short,
            out["v78_adk_v77_weight"],
            out["v78_adk_new_holding"],
            new_long,
            new_short,
            out["v78_adk_new_weight"],
        )
    ]
    out["adk_net_asset_exposure"] = out.apply(_v78_adk_aggregate_asset_weights, axis=1)
    out["adk_net_long_weights"] = out["adk_net_asset_exposure"].map(
        lambda net: {asset: weight for asset, weight in net.items() if weight > 1e-12}
    )
    out["adk_net_short_weights"] = out["adk_net_asset_exposure"].map(
        lambda net: {asset: -weight for asset, weight in net.items() if weight < -1e-12}
    )
    out["holding"] = [
        f"V7.7ADK:{vh}|NewADK:{nh}"
        for vh, nh in zip(out["v78_adk_v77_holding"], out["v78_adk_new_holding"])
    ]
    out["top_pair"] = [
        f"V7.7ADK:{vp}|NewADK:{npair}"
        for vp, npair in zip(
            v77.get("top_pair", pd.Series("none", index=common_index)),
            new.get("top_pair", pd.Series("none", index=common_index)),
        )
    ]
    out["long_leg"] = None
    out["short_leg"] = None
    out["direction"] = 0
    out["weight"] = out["final_exposure"]
    out["is_signal"] = (
        v77.get("is_signal", pd.Series(False, index=common_index)).astype(bool)
        | new.get("is_signal", pd.Series(False, index=common_index)).astype(bool)
        | out["final_exposure"].diff().abs().fillna(0.0).gt(1e-4)
    )
    out["target"] = out["holding"].where(out["is_signal"], None)
    out["v78_blend_label"] = "50% V7.7 ADK + 50% New ADK primary"
    out["v78_adk_component_net_return"] = out["return"]
    out["return_before_dk_execution_cost"] = out["return"]
    out["dk_execution_cost"] = 0.0
    out["dk_execution_turnover"] = np.nan
    out["cost_basis_note"] = "component-net blend; component costs already included"
    out.attrs["v78_adk_v77"] = v77_result
    out.attrs["v78_adk_new"] = new_result
    return out


def _extract_active_pair_score(dk_result):
    signals_df = dk_result.attrs.get("signals_df")
    if signals_df is None or len(dk_result) == 0:
        raise KeyError("signals_df is missing from dk_result attrs.")
    if "top_pair" not in dk_result.columns:
        raise KeyError("top_pair column is required for score-decay overlay.")

    scores = []
    for dt, pair in dk_result["top_pair"].fillna("none").items():
        score = None
        if pair != "none" and pair in signals_df.columns and dt in signals_df.index:
            raw = signals_df.loc[dt, pair]
            if pd.notna(raw):
                score = float(raw)
        scores.append(score)
    return pd.Series(scores, index=dk_result.index, dtype=float)


def apply_dk_pair_score_peak_decay_overlay(
    dk_result,
    decay_ratio_threshold,
    recovery_ratio_threshold,
    derisk_scale,
    commission=0.0,
    warmup_days=CN_DK_PAIR_SCORE_DECAY_WARMUP_DAYS,
):
    if not 0 < decay_ratio_threshold < 1:
        raise ValueError("decay_ratio_threshold must be in (0, 1).")
    if not decay_ratio_threshold < recovery_ratio_threshold <= 1:
        raise ValueError("recovery_ratio_threshold must be in (decay_ratio_threshold, 1].")
    if not 0 <= derisk_scale <= 1:
        raise ValueError("derisk_scale must be in [0, 1].")
    if dk_result is None or len(dk_result) == 0:
        return dk_result

    required = {"return", "holding", "top_pair"}
    missing = required.difference(dk_result.columns)
    if missing:
        raise KeyError(f"Missing required DK columns: {sorted(missing)}")

    out = dk_result.copy()
    base_ret = out.get("return_before_dk_overlay", out.get("return_before_dk_execution_cost", out["return"])).fillna(0.0)
    base_execution_cost = out.get("dk_execution_cost", pd.Series(0.0, index=out.index)).fillna(0.0)
    if "dk_overlay_execution_cost" in out.columns:
        base_execution_cost = base_execution_cost + out["dk_overlay_execution_cost"].fillna(0.0)
    base_weight = out["weight"].fillna(1.0) if "weight" in out.columns else pd.Series(1.0, index=out.index)
    holdings = out["holding"].fillna("none_0").astype(str)
    active_score = _extract_active_pair_score(out)

    final_ret = []
    overlay_scale = []
    overlay_on = []
    overlay_triggered = []
    overlay_recovered = []
    trade_ids = []
    score_peaks = []
    score_decay_ratios = []
    waiting_flags = []
    overlay_costs = []

    trade_id = 0
    score_peak = None
    derisked_for_today = False
    waiting_for_new_peak = False
    rearm_peak = None
    prev_scale = 1.0
    trade_age = 0

    for i, dt in enumerate(base_ret.index):
        holding = holdings.iloc[i]
        prev_holding = holdings.iloc[i - 1] if i > 0 else None
        new_trade = i == 0 or holding != prev_holding

        if new_trade:
            trade_id += 1
            score_peak = None
            derisked_for_today = False
            waiting_for_new_peak = False
            rearm_peak = None
            trade_age = 0
        trade_age += 1

        cur_scale = derisk_scale if derisked_for_today else 1.0
        triggered_today = cur_scale < 0.999999 and prev_scale >= 0.999999
        recovered_today = cur_scale >= 0.999999 and prev_scale < 0.999999

        realized_gross = float(base_ret.iloc[i]) * cur_scale
        delta_scale = abs(cur_scale - prev_scale)
        overlay_tc = 0.0
        if delta_scale > 1e-12:
            overlay_tc = 2.0 * commission * float(base_weight.iloc[i]) * delta_scale
        realized_ret = (1.0 + realized_gross) * (1.0 - float(base_execution_cost.iloc[i])) * (1.0 - overlay_tc) - 1.0

        cur_score = active_score.iloc[i]
        if pd.notna(cur_score):
            cur_score = float(cur_score)
            score_peak = cur_score if score_peak is None else max(float(score_peak), cur_score)

        decay_ratio = None
        if score_peak is not None and score_peak > 1e-12 and pd.notna(cur_score):
            decay_ratio = float(cur_score) / float(score_peak)

        next_derisked = derisked_for_today
        next_waiting = waiting_for_new_peak
        next_rearm_peak = rearm_peak

        if next_waiting and next_rearm_peak is not None and score_peak is not None and score_peak > float(next_rearm_peak) + 1e-12:
            next_waiting = False
            next_rearm_peak = None

        if next_derisked:
            if decay_ratio is not None and decay_ratio >= recovery_ratio_threshold:
                next_derisked = False
                next_waiting = True
                next_rearm_peak = score_peak
        elif (
            not next_waiting
            and trade_age >= int(warmup_days)
            and decay_ratio is not None
            and decay_ratio <= decay_ratio_threshold
        ):
            next_derisked = True

        final_ret.append(float(realized_ret))
        overlay_scale.append(float(cur_scale))
        overlay_on.append(bool(cur_scale < 0.999999))
        overlay_triggered.append(bool(triggered_today))
        overlay_recovered.append(bool(recovered_today))
        trade_ids.append(int(trade_id))
        score_peaks.append(None if score_peak is None else float(score_peak))
        score_decay_ratios.append(None if decay_ratio is None else float(decay_ratio))
        waiting_flags.append(bool(next_waiting))
        overlay_costs.append(float(overlay_tc))

        derisked_for_today = next_derisked
        waiting_for_new_peak = next_waiting
        rearm_peak = next_rearm_peak
        prev_scale = cur_scale

    out["raw_return"] = base_ret
    out["return_before_dk_overlay"] = base_ret
    out["dk_overlay_execution_cost"] = pd.Series(overlay_costs, index=out.index, dtype=float)
    out["base_weight"] = base_weight
    out["return"] = pd.Series(final_ret, index=out.index, dtype=float)
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["active_score_overlay"] = active_score
    out["overlay_scale"] = pd.Series(overlay_scale, index=out.index, dtype=float)
    out["overlay_on"] = pd.Series(overlay_on, index=out.index, dtype=bool)
    out["overlay_triggered"] = pd.Series(overlay_triggered, index=out.index, dtype=bool)
    out["overlay_recovered"] = pd.Series(overlay_recovered, index=out.index, dtype=bool)
    out["trade_id"] = pd.Series(trade_ids, index=out.index, dtype="Int64")
    out["score_peak_overlay"] = pd.Series(score_peaks, index=out.index, dtype=float)
    out["score_decay_ratio_overlay"] = pd.Series(score_decay_ratios, index=out.index, dtype=float)
    out["waiting_for_new_peak"] = pd.Series(waiting_flags, index=out.index, dtype=bool)
    out["weight"] = out["base_weight"] * out["overlay_scale"]
    out.attrs["pair_score_peak_decay_overlay"] = {
        "decay_ratio_threshold": decay_ratio_threshold,
        "recovery_ratio_threshold": recovery_ratio_threshold,
        "derisk_scale": derisk_scale,
        "commission": commission,
        "warmup_days": int(warmup_days),
        "overlay_days": int(out["overlay_on"].sum()),
        "overlay_ratio": float(out["overlay_on"].mean()),
        "trigger_count": int(out["overlay_triggered"].sum()),
        "recovery_count": int(out["overlay_recovered"].sum()),
    }
    return out


def _extract_active_pair_same_side_overheat(dk_result):
    pair_data = dk_result.attrs.get("pair_data")
    if pair_data is None:
        raise KeyError("pair_data is missing from dk_result attrs.")
    if "top_pair" not in dk_result.columns:
        raise KeyError("top_pair column is required for same-side overheat overlay.")

    feature_cache = {}
    for pair, pdata in pair_data.items():
        if pdata is None or "ratio" not in pdata.columns or "bias_mom" not in pdata.columns:
            continue
        ratio = pdata["ratio"].astype(float)
        ma = ratio.rolling(CN_DK_BIAS_N).mean()
        bias = ratio / ma - 1.0
        bias_mom = pdata["bias_mom"].astype(float)
        same_side = (np.sign(bias) == np.sign(bias_mom)) & bias.notna() & bias_mom.notna()
        feature_cache[pair] = pd.DataFrame(
            {
                "abs_bias": bias.abs(),
                "same_side": same_side,
            },
            index=pdata.index,
        ).shift(1)

    abs_bias_vals = []
    same_side_vals = []
    for dt, pair in dk_result["top_pair"].fillna("none").items():
        abs_bias = np.nan
        same_side = False
        f = feature_cache.get(pair)
        if f is not None and dt in f.index:
            ab = f.loc[dt, "abs_bias"]
            ss = f.loc[dt, "same_side"]
            if pd.notna(ab):
                abs_bias = float(ab)
            same_side = bool(ss) if pd.notna(ss) else False
        abs_bias_vals.append(abs_bias)
        same_side_vals.append(same_side)
    return (
        pd.Series(abs_bias_vals, index=dk_result.index, dtype=float),
        pd.Series(same_side_vals, index=dk_result.index, dtype=bool),
    )


def apply_dk_same_side_overheat_overlay(
    dk_result,
    enter_threshold,
    exit_threshold,
    derisk_scale,
    commission=0.0,
):
    """Reduce ADK exposure only when the active pair is chasing an extreme same-side bias.

    Uses T-1 pair ratio bias because DK Top-1 execution is based on prior close signals.
    """
    if not 0 < exit_threshold < enter_threshold:
        raise ValueError("exit_threshold must be in (0, enter_threshold).")
    if not 0 <= derisk_scale <= 1:
        raise ValueError("derisk_scale must be in [0, 1].")
    if dk_result is None or len(dk_result) == 0:
        return dk_result

    required = {"return", "holding", "top_pair"}
    missing = required.difference(dk_result.columns)
    if missing:
        raise KeyError(f"Missing required DK columns: {sorted(missing)}")

    out = dk_result.copy()
    base_ret = out.get("return_before_dk_execution_cost", out.get("return_before_dk_overlay", out["return"])).fillna(0.0)
    base_execution_cost = out.get("dk_execution_cost", pd.Series(0.0, index=out.index)).fillna(0.0)
    if "dk_overlay_execution_cost" in out.columns:
        base_execution_cost = base_execution_cost + out["dk_overlay_execution_cost"].fillna(0.0)
    pre_weight = out["weight"].fillna(1.0) if "weight" in out.columns else pd.Series(1.0, index=out.index)
    prior_overlay_scale = out.get("overlay_scale", pd.Series(1.0, index=out.index)).fillna(1.0)
    holdings = out["holding"].fillna("none_0").astype(str)
    active_abs_bias, active_same_side = _extract_active_pair_same_side_overheat(out)

    final_ret = []
    overheat_scale = []
    overheat_on = []
    overheat_triggered = []
    overheat_recovered = []
    overheat_tc = []
    prev_scale = 1.0
    defense_on = False

    for i, dt in enumerate(base_ret.index):
        holding = holdings.iloc[i]
        prev_holding = holdings.iloc[i - 1] if i > 0 else None
        new_trade = i == 0 or holding != prev_holding
        if new_trade:
            defense_on = False
            prev_scale = 1.0
        abs_bias = active_abs_bias.iloc[i]
        same_side = bool(active_same_side.iloc[i])

        if holding == "none_0" or pd.isna(abs_bias) or not same_side:
            defense_on = False
        elif defense_on:
            if float(abs_bias) <= exit_threshold:
                defense_on = False
        elif float(abs_bias) > enter_threshold:
            defense_on = True

        cur_scale = derisk_scale if defense_on else 1.0
        if holding == "none_0":
            cur_scale = 0.0

        triggered_today = cur_scale < 0.999999 and prev_scale >= 0.999999
        recovered_today = cur_scale >= 0.999999 and prev_scale < 0.999999
        delta_scale = abs(cur_scale - prev_scale)
        tc = 0.0
        if delta_scale > 1e-12:
            tc = 2.0 * commission * float(pre_weight.iloc[i]) * delta_scale

        realized_gross = float(base_ret.iloc[i]) * float(prior_overlay_scale.iloc[i]) * cur_scale
        realized_ret = (1.0 + realized_gross) * (1.0 - float(base_execution_cost.iloc[i])) * (1.0 - tc) - 1.0
        final_ret.append(float(realized_ret))
        overheat_scale.append(float(cur_scale))
        overheat_on.append(bool(cur_scale < 0.999999))
        overheat_triggered.append(bool(triggered_today))
        overheat_recovered.append(bool(recovered_today))
        overheat_tc.append(float(tc))
        prev_scale = cur_scale

    out["pre_overheat_return"] = base_ret
    out["return_before_dk_overheat"] = base_ret
    out["pre_overheat_weight"] = pre_weight
    out["same_side_overheat_abs_bias"] = active_abs_bias
    out["same_side_overheat_signal"] = active_same_side
    out["same_side_overheat_scale"] = pd.Series(overheat_scale, index=out.index, dtype=float)
    out["same_side_overheat_on"] = pd.Series(overheat_on, index=out.index, dtype=bool)
    out["same_side_overheat_triggered"] = pd.Series(overheat_triggered, index=out.index, dtype=bool)
    out["same_side_overheat_recovered"] = pd.Series(overheat_recovered, index=out.index, dtype=bool)
    out["same_side_overheat_tc"] = pd.Series(overheat_tc, index=out.index, dtype=float)
    out["dk_total_overlay_scale"] = prior_overlay_scale * out["same_side_overheat_scale"]
    out["return"] = pd.Series(final_ret, index=out.index, dtype=float)
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["weight"] = out["pre_overheat_weight"] * out["same_side_overheat_scale"]
    out.attrs["same_side_overheat_overlay"] = {
        "enter_threshold": enter_threshold,
        "exit_threshold": exit_threshold,
        "derisk_scale": derisk_scale,
        "commission": commission,
        "overlay_days": int(out["same_side_overheat_on"].sum()),
        "overlay_ratio": float(out["same_side_overheat_on"].mean()),
        "trigger_count": int(out["same_side_overheat_triggered"].sum()),
        "recovery_count": int(out["same_side_overheat_recovered"].sum()),
    }
    return out


def apply_dk_drawdown_risk_gate(dk_result, enter=0.15, scale_defense=0.5, exit_value=0.08, cooldown_days=0):
    """Apply a strategy-level drawdown gate to Sub-A-DK.

    Rule:
    - If prior-day raw DD <= -enter, next day exposure is scaled to `scale_defense`
    - Once in defense, recover only after prior-day raw DD >= -exit_value
    - Transaction cost for exposure changes follows the same logic used in the test scans
    """
    if dk_result is None or len(dk_result) == 0:
        return dk_result

    gate_gross_ret = dk_result.get(
        "return_before_dk_execution_cost",
        dk_result.get("raw_return", dk_result["return"]),
    ).fillna(0.0)
    base_ret = gate_gross_ret
    base_weight = dk_result["weight"].fillna(1.0)
    prior_overlay_scale = dk_result.get("dk_total_overlay_scale", None)
    if prior_overlay_scale is None:
        prior_overlay_scale = pd.Series(1.0, index=dk_result.index)
        if "overlay_scale" in dk_result.columns:
            prior_overlay_scale = prior_overlay_scale * dk_result["overlay_scale"].fillna(1.0)
        if "same_side_overheat_scale" in dk_result.columns:
            prior_overlay_scale = prior_overlay_scale * dk_result["same_side_overheat_scale"].fillna(1.0)
    else:
        prior_overlay_scale = prior_overlay_scale.fillna(1.0)
    dk_execution_cost = dk_result.get("dk_execution_cost", pd.Series(0.0, index=dk_result.index)).fillna(0.0)
    prior_cost = dk_execution_cost.copy()
    if "dk_overlay_execution_cost" in dk_result.columns:
        prior_cost = prior_cost + dk_result["dk_overlay_execution_cost"].fillna(0.0)
    if "same_side_overheat_tc" in dk_result.columns:
        prior_cost = prior_cost + dk_result["same_side_overheat_tc"].fillna(0.0)
    risk_gate_base_ret = (1.0 + gate_gross_ret) * (1.0 - dk_execution_cost) - 1.0
    base_nav = (1.0 + risk_gate_base_ret).cumprod()
    base_dd = base_nav / base_nav.cummax() - 1.0

    gated_ret = []
    gate_scale = []
    gate_on = []
    prev_scale = 1.0
    cooldown_left = 0

    for i, dt in enumerate(risk_gate_base_ret.index):
        if i == 0:
            cur_scale = 1.0
        else:
            prev_dt = risk_gate_base_ret.index[i - 1]
            prev_dd = float(base_dd.loc[prev_dt])
            trigger = prev_dd <= -enter
            release_ready = prev_dd >= -exit_value if exit_value is not None else prev_dd > -enter
            if trigger:
                cooldown_left = max(cooldown_left, cooldown_days)
                cur_scale = scale_defense
            elif prev_scale < 0.999999:
                if cooldown_left > 0:
                    cooldown_left -= 1
                    cur_scale = scale_defense
                else:
                    cur_scale = 1.0 if release_ready else scale_defense
            else:
                cur_scale = 1.0

        scaled_ret = base_ret.iloc[i] * float(prior_overlay_scale.iloc[i]) * cur_scale
        delta_scale = abs(cur_scale - prev_scale)
        overlay_tc = 0.0
        if delta_scale > 1e-12:
            overlay_tc = 2.0 * CN_DK_COMMISSION * delta_scale * float(base_weight.iloc[i])
        final_ret = (1.0 + scaled_ret) * (1.0 - float(prior_cost.iloc[i])) * (1.0 - overlay_tc) - 1.0

        gated_ret.append(final_ret)
        gate_scale.append(cur_scale)
        gate_on.append(cur_scale < 0.999999)
        prev_scale = cur_scale

    out = dk_result.copy()
    out["raw_return"] = gate_gross_ret
    out["risk_gate_base_return"] = risk_gate_base_ret
    out["raw_nav"] = base_nav
    out["base_weight"] = base_weight
    out["risk_gate_scale"] = pd.Series(gate_scale, index=base_ret.index)
    out["risk_gate_on"] = pd.Series(gate_on, index=base_ret.index)
    out["risk_gate_base_dd"] = base_dd
    out["return"] = pd.Series(gated_ret, index=base_ret.index)
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["weight"] = out["base_weight"] * out["risk_gate_scale"]
    out["dk_total_overlay_scale"] = prior_overlay_scale * out["risk_gate_scale"]
    out.attrs["risk_gate"] = {
        "kind": "dd",
        "dd_basis": "pre_gate_execution_nav",
        "enter": enter,
        "exit": exit_value,
        "scale_defense": scale_defense,
        "cooldown_days": cooldown_days,
    }
    return out

def _us_signal_days(close_df, start_idx):
    week_best = {}
    for i in range(start_idx, len(close_df)):
        dt = close_df.index[i]
        dow = dt.dayofweek
        if dow > 3:
            continue
        yr, wk, _ = dt.isocalendar()
        key = (yr, wk)
        if key not in week_best or dow > week_best[key][1]:
            week_best[key] = (i, dow)
    return {v[0] for v in week_best.values()}


def _should_suppress_early_week_us_signal(us_date, now=None):
    """Suppress current-week Mon/Tue/Wed US signals until after NY Thu close."""
    bj_now = beijing_now() if now is None else now
    now_et = _bj_naive_to_utc(bj_now).astimezone(ZoneInfo("America/New_York"))

    us_date = pd.Timestamp(us_date).normalize()
    if us_date.dayofweek >= 3:
        return False

    sig_year, sig_week, _ = us_date.isocalendar()
    now_year, now_week, _ = pd.Timestamp(now_et.date()).isocalendar()
    if (sig_year, sig_week) != (now_year, now_week):
        return False

    before_thu_close = (
        now_et.weekday() < 3
        or (now_et.weekday() == 3 and now_et.hour < 16)
    )
    return before_thu_close


def _bj_naive_to_utc(now):
    if now.tzinfo is not None:
        return now.astimezone(timezone.utc)
    return (now - timedelta(hours=8)).replace(tzinfo=timezone.utc)


def _us_raw_weights(mom_row, vol_row, ranking_codes, top_n, abs_threshold,
                    prev_risky=None, threshold=1.0):
    """Top-N selection with optional threshold.
    When threshold > 1.0 and prev_risky is provided:
      new challenger must score > weakest current holding × threshold to replace.
    """
    available = {}
    for a in ranking_codes:
        if (a in mom_row.index and not np.isnan(mom_row[a])
                and a in vol_row.index and not np.isnan(vol_row[a])
                and vol_row[a] > 0.001):
            available[a] = mom_row[a]
    if not available:
        return {"BIL": 1.0}
    sorted_avail = sorted(available.items(), key=lambda x: x[1], reverse=True)
    # ── threshold selection ──
    if threshold > 1.0 and prev_risky:
        selected = set()
        for a in prev_risky:
            if a in available:
                selected.add(a)
        for a, _ in sorted_avail:
            if len(selected) >= top_n:
                break
            if a not in selected:
                selected.add(a)
        if len(selected) > top_n:
            sel_scored = sorted([(a, available[a]) for a in selected], key=lambda x: x[1])
            while len(selected) > top_n:
                selected.discard(sel_scored.pop(0)[0])
        weakest = min(selected, key=lambda a: available.get(a, -999))
        weakest_score = available.get(weakest, 0)
        for a, sc in sorted_avail:
            if a in selected:
                continue
            should_replace = (
                sc > weakest_score
                if weakest_score <= 0
                else sc > weakest_score * threshold
            )
            if should_replace:
                selected.discard(weakest)
                selected.add(a)
                weakest = min(selected, key=lambda a2: available.get(a2, -999))
                weakest_score = available.get(weakest, 0)
        top = [(a, available[a]) for a in selected]
    else:
        top = sorted_avail[:top_n]
    # ── abs momentum filter + inverse-vol weighting ──
    passed, n_fail = [], 0
    for a, _ in top:
        if not np.isnan(mom_row.get(a, np.nan)) and mom_row[a] > abs_threshold:
            passed.append(a)
        else:
            n_fail += 1
    if not top:
        return {"BIL": 1.0}
    bil_w = n_fail / len(top)
    raw = {}
    if passed:
        iv = {a: 1.0 / vol_row[a] for a in passed if vol_row[a] > 0.001}
        total_iv = sum(iv.values()) if iv else 1
        share = 1.0 - bil_w
        raw = {a: (v / total_iv) * share for a, v in iv.items()}
    if bil_w > 0:
        raw["BIL"] = bil_w
    return raw

def _us_model_b(raw_w, scale):
    act = {}
    for a, w in raw_w.items():
        if a == "BIL":
            continue
        live_asset = _ROT_PROXY_TO_LIVE.get(a, a)
        if scale <= 1.0:
            act[a] = w * scale
        elif live_asset in US_ROT_FUTURES:
            # Scale only the asset's own raw weight; do not transfer other assets' leverage gap.
            act[a] = w * scale
        else:
            act[a] = w
    risky = sum(act.values())
    act["BIL"] = max(1.0 - risky, 0.0)
    return act

def _apply_btc_cap(act, btc_ticker, max_w):
    if btc_ticker not in act or act[btc_ticker] <= max_w:
        return act
    act = dict(act)
    excess = act[btc_ticker] - max_w
    act[btc_ticker] = max_w
    act["BIL"] = act.get("BIL", 0.0) + excess
    return act


def _apply_subb_btc_cap(act):
    return _apply_btc_cap(act, US_ROT_BTC_TICKER, US_ROT_BTC_MAX_W)


def _apply_subb_btc_start_filter(close_df):
    out = close_df.copy()
    if US_ROT_BTC_TICKER in out.columns:
        out.loc[out.index < US_ROT_BTC_START, US_ROT_BTC_TICKER] = np.nan
    return out


def _average_weight_dicts(weight_dicts):
    if not weight_dicts:
        return {"BIL": 1.0}
    keys = set().union(*[wd.keys() for wd in weight_dicts])
    return {k: sum(wd.get(k, 0.0) for wd in weight_dicts) / len(weight_dicts) for k in keys}


def _weighted_average_weight_dicts(weight_items):
    if not weight_items:
        return {"BIL": 1.0}
    total_weight = sum(float(weight) for _weights, weight in weight_items)
    if total_weight <= 0:
        return {"BIL": 1.0}
    keys = set().union(*[weights.keys() for weights, _weight in weight_items])
    return {
        key: sum(weights.get(key, 0.0) * float(weight) for weights, weight in weight_items) / total_weight
        for key in keys
    }


def _us_selected_risky_from_raw(raw_w):
    return {a for a, w in raw_w.items() if a != "BIL" and w > 1e-12}


def _serialize_us_mix_selected(selected):
    if not selected:
        return ""
    return ",".join(sorted(selected))


def _deserialize_us_mix_selected(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip()
    if not text:
        return set()
    items = {part.strip() for part in text.split(",") if part.strip()}
    return items


def _us_mix_prev_risky_by_lb_from_row(row):
    if row is None:
        return None
    prev_risky_by_lb = {}
    for lb in US_ROT_LBS:
        col = f"sel_{lb}"
        if col not in row:
            prev_risky_by_lb[lb] = None
            continue
        prev_risky_by_lb[lb] = _deserialize_us_mix_selected(row[col])
    if not any(value is not None for value in prev_risky_by_lb.values()):
        return None
    return prev_risky_by_lb


def _us_mix_prev_risky_by_lb_from_result(result_df, signal_date=None, include_current=False):
    if result_df is None or len(result_df) == 0 or "is_signal" not in result_df.columns:
        return None
    signal_rows = result_df[result_df["is_signal"]]
    if signal_rows.empty:
        return None
    if signal_date is not None:
        signal_date = pd.Timestamp(signal_date)
        if include_current:
            signal_rows = signal_rows.loc[signal_rows.index <= signal_date]
        else:
            signal_rows = signal_rows.loc[signal_rows.index < signal_date]
        if signal_rows.empty:
            return None
    return _us_mix_prev_risky_by_lb_from_row(signal_rows.iloc[-1])


def _us_mix_target_weights(momentum_rows, vol_row, ranking_codes, scale,
                           top_n=US_ROT_TOP_N, abs_threshold=US_ROT_ABS_THRESHOLD,
                           prev_risky_by_lb=None, threshold=1.0):
    acts = []
    per_lb = {}
    for lb, mom_row in momentum_rows.items():
        prev_risky = prev_risky_by_lb.get(lb) if prev_risky_by_lb else None
        raw = _us_raw_weights(
            mom_row,
            vol_row,
            ranking_codes,
            top_n,
            abs_threshold,
            prev_risky=prev_risky,
            threshold=threshold,
        )
        act = _us_model_b(raw, scale)
        acts.append((act, US_ROT_WINDOW_WEIGHTS.get(lb, 0.0)))
        per_lb[lb] = {
            "raw": raw,
            "act": act,
            "selected": _us_selected_risky_from_raw(raw),
            "prev_risky": set(prev_risky) if prev_risky else None,
        }
    return _apply_subb_btc_cap(_weighted_average_weight_dicts(acts)), per_lb


def _us_mix_snapshot(close_df, row_idx, ranking_codes, scale,
                     prev_risky_by_lb=None, threshold=1.0):
    vol_df = close_df.pct_change().rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
    momentum_rows = {
        lb: close_df.div(close_df.shift(lb)).sub(1).iloc[row_idx]
        for lb in US_ROT_LBS
    }
    mix_act, per_lb = _us_mix_target_weights(
        momentum_rows,
        vol_df.iloc[row_idx],
        ranking_codes,
        scale,
        prev_risky_by_lb=prev_risky_by_lb,
        threshold=threshold,
    )
    return mix_act, per_lb, vol_df.iloc[row_idx]


def _subb_v75_ema_prev_risky_from_result(result_df, signal_date=None, include_current=False):
    if result_df is None or len(result_df) == 0:
        return None
    rows = result_df
    if signal_date is not None:
        signal_date = pd.Timestamp(signal_date)
        rows = rows.loc[rows.index <= signal_date] if include_current else rows.loc[rows.index < signal_date]
    if rows.empty:
        return None
    row = rows.iloc[-1]
    prefixes = ("ema_w_", "ema_actual_w_")
    for prefix in prefixes:
        weights = {
            c[len(prefix):]: float(row.get(c, 0.0) or 0.0)
            for c in row.index
            if isinstance(c, str) and c.startswith(prefix)
        }
        risky = {asset for asset, weight in weights.items() if asset != "BIL" and weight > 0.001}
        if risky:
            return risky
    return None


def _subb_v75_ema_scale_from_result(result_df, include_current=False):
    if result_df is not None and "ema_scale" in result_df.columns and len(result_df) > 0:
        value = pd.to_numeric(result_df["ema_scale"], errors="coerce").dropna()
        if len(value) > 0:
            return float(value.iloc[-1])
    if result_df is not None and "ema_return" in result_df.columns:
        hist = pd.to_numeric(result_df["ema_return"], errors="coerce").dropna()
        if not include_current:
            hist = hist.iloc[:-1]
        if len(hist) > 0:
            return _subb_v75_ema_scale_from_hist(hist.values)
    return 1.0


def _subb_official_scale_from_result(result_df, end_loc=None, include_current=False):
    if result_df is None or len(result_df) == 0:
        return 1.0
    source = result_df["official_return"] if "official_return" in result_df.columns else result_df["return"]
    source = pd.to_numeric(source, errors="coerce")
    if end_loc is not None:
        source = source.iloc[:end_loc]
    elif not include_current:
        source = source.iloc[:-1]
    hist = source.dropna().values
    if len(hist) >= US_ROT_VOL_WINDOW:
        rv = np.std(hist[-US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
        return min(max(US_ROT_TARGET_VOL / rv, 0.05), US_ROT_MAX_LEV) if rv > 0.001 else US_ROT_MAX_LEV
    return 1.0


def _subb_v75_ema_snapshot(close_df, row_idx, scale, ranking_codes=None, prev_risky=None,
                           threshold=US_ROT_REBALANCE_THRESHOLD):
    ranking_codes = list(ranking_codes) if ranking_codes is not None else list(US_ROT_POOL)
    score_row = _subb_v75_ema_score(close_df, SUBB_V75_EMA_HALF_LIFE).iloc[row_idx]
    vol_row = close_df.pct_change().rolling(US_ROT_VOL_LB).std().mul(np.sqrt(US_TRADING_DAYS)).iloc[row_idx]
    raw_w = _us_raw_weights(
        score_row,
        vol_row,
        ranking_codes,
        top_n=US_ROT_TOP_N,
        abs_threshold=SUBB_V75_EMA_ABS_THRESHOLD,
        prev_risky=prev_risky,
        threshold=threshold,
    )
    return _apply_subb_btc_cap(_us_model_b(raw_w, scale)), raw_w, vol_row


def _blend_subb_v75_weight_dicts(official_weights, ema_weights,
                                 official_weight=SUBB_V75_OFFICIAL_WEIGHT,
                                 ema_weight=SUBB_V75_EMA_WEIGHT):
    official_weights = dict(official_weights or {})
    ema_weights = dict(ema_weights or {})
    assets = set(official_weights) | set(ema_weights)
    return {
        asset: float(official_weight) * float(official_weights.get(asset, 0.0) or 0.0)
             + float(ema_weight) * float(ema_weights.get(asset, 0.0) or 0.0)
        for asset in assets
    }

def _blend_v78_subb_weight_dicts(v77_weights, bias_weights, logvol_weights):
    v77_weights = dict(v77_weights or {})
    bias_weights = dict(bias_weights or {})
    logvol_weights = dict(logvol_weights or {})
    assets = sorted(set(v77_weights) | set(bias_weights) | set(logvol_weights))
    return {
        asset: (
            V78_SUBB_V77_WEIGHT * float(v77_weights.get(asset, 0.0) or 0.0)
            + V78_SUBB_NEW_BIAS_WEIGHT * float(bias_weights.get(asset, 0.0) or 0.0)
            + V78_SUBB_NEW_LOGVOL_WEIGHT * float(logvol_weights.get(asset, 0.0) or 0.0)
        )
        for asset in assets
    }


def _us_mix_display_context(close_df, row_idx, ranking_codes, scale, prev_risky_by_lb=None,
                            threshold=1.0, reference_assets=None):
    ranking_codes = list(ranking_codes)
    if reference_assets is None:
        reference_assets = [("BTC-USD", "IBIT(参考)")]
    reference_proxies = [proxy for proxy, _ in reference_assets if proxy not in ranking_codes and proxy in close_df.columns]
    display_codes = list(dict.fromkeys(ranking_codes + reference_proxies))
    mix_act, per_lb, vol_row = _us_mix_snapshot(
        close_df,
        row_idx,
        ranking_codes,
        scale,
        prev_risky_by_lb=prev_risky_by_lb,
        threshold=threshold,
    )
    momentum_rows = {
        lb: close_df.div(close_df.shift(lb)).sub(1).iloc[row_idx]
        for lb in US_ROT_LBS
    }

    def _build_row(proxy, live_name, participates):
        per_lb_momentum = {}
        per_lb_act = {}
        valid_moms = []
        weighted_momentum_sum = 0.0
        valid_window_weight_sum = 0.0
        for lb in US_ROT_LBS:
            mom = momentum_rows[lb].get(proxy, np.nan)
            per_lb_momentum[lb] = float(mom) if not pd.isna(mom) else np.nan
            if not pd.isna(mom):
                mom_value = float(mom)
                valid_moms.append(mom_value)
                window_weight = float(US_ROT_WINDOW_WEIGHTS.get(lb, 0.0))
                weighted_momentum_sum += mom_value * window_weight
                valid_window_weight_sum += window_weight
            per_lb_act[lb] = float(per_lb[lb]["act"].get(proxy, 0.0)) if participates else 0.0
        vol = vol_row.get(proxy, np.nan)
        avg_momentum = (
            float(weighted_momentum_sum / valid_window_weight_sum)
            if valid_moms and valid_window_weight_sum > 0
            else np.nan
        )
        return {
            "proxy": proxy,
            "live_name": live_name,
            "participates": participates,
            "vol": float(vol) if not pd.isna(vol) else np.nan,
            "avg_momentum": avg_momentum,
            "mix_weight": float(mix_act.get(proxy, 0.0)) if participates else 0.0,
            "per_lb_momentum": per_lb_momentum,
            "per_lb_act": per_lb_act,
            "per_lb_rank": {},
            "actual_rank": None,
        }

    per_lb_actual_rank = {}
    for lb in US_ROT_LBS:
        ranked = []
        for proxy in display_codes:
            mom = momentum_rows[lb].get(proxy, np.nan)
            vol = vol_row.get(proxy, np.nan)
            if not pd.isna(mom) and not pd.isna(vol) and vol > 0.001:
                ranked.append((proxy, float(mom)))
        ranked.sort(key=lambda x: x[1], reverse=True)
        per_lb_actual_rank[lb] = {proxy: rank for rank, (proxy, _) in enumerate(ranked, 1)}

    avg_ranked = []
    for proxy in display_codes:
        weighted_momentum_sum = 0.0
        valid_window_weight_sum = 0.0
        for lb in US_ROT_LBS:
            mom = momentum_rows[lb].get(proxy, np.nan)
            if not pd.isna(mom):
                window_weight = float(US_ROT_WINDOW_WEIGHTS.get(lb, 0.0))
                weighted_momentum_sum += float(mom) * window_weight
                valid_window_weight_sum += window_weight
        vol = vol_row.get(proxy, np.nan)
        if valid_window_weight_sum > 0 and not pd.isna(vol) and vol > 0.001:
            avg_ranked.append((proxy, float(weighted_momentum_sum / valid_window_weight_sum)))
    avg_ranked.sort(key=lambda x: x[1], reverse=True)
    actual_avg_rank = {proxy: rank for rank, (proxy, _) in enumerate(avg_ranked, 1)}

    per_lb_rows = {}
    for lb in US_ROT_LBS:
        rows = []
        for proxy in ranking_codes:
            row = _build_row(proxy, _ROT_PROXY_TO_LIVE.get(proxy, proxy), True)
            mom = row["per_lb_momentum"][lb]
            vol = row["vol"]
            if np.isnan(mom) or np.isnan(vol) or vol <= 0.001:
                continue
            row = dict(row)
            row["momentum"] = mom
            row["window_weight"] = row["per_lb_act"][lb]
            row["buffer_selected"] = proxy in per_lb[lb]["selected"]
            row["buffer_prev_hold"] = proxy in (per_lb[lb]["prev_risky"] or set())
            row["actual_rank"] = actual_avg_rank.get(proxy)
            row["per_lb_rank"] = {w_lb: per_lb_actual_rank[w_lb].get(proxy) for w_lb in US_ROT_LBS}
            rows.append(row)
        rows.sort(key=lambda x: x["momentum"], reverse=True)
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
            row["top3"] = rank <= US_ROT_TOP_N
            row["abs_pass"] = row["momentum"] > US_ROT_ABS_THRESHOLD
        per_lb_rows[lb] = rows

    mix_rows = [_build_row(proxy, _ROT_PROXY_TO_LIVE.get(proxy, proxy), True) for proxy in ranking_codes]
    mix_rows.sort(key=lambda x: (x["mix_weight"], x["avg_momentum"]), reverse=True)
    for rank, row in enumerate(mix_rows, 1):
        row["rank"] = rank
        row["mix_selected"] = row["mix_weight"] > 1e-6
        row["actual_rank"] = actual_avg_rank.get(row["proxy"])
        row["per_lb_rank"] = {lb: per_lb_actual_rank[lb].get(row["proxy"]) for lb in US_ROT_LBS}

    reference_rows = []
    for proxy, live_name in reference_assets:
        if proxy in ranking_codes or proxy not in close_df.columns:
            continue
        row = _build_row(proxy, live_name, False)
        row["actual_rank"] = actual_avg_rank.get(proxy)
        row["per_lb_rank"] = {lb: per_lb_actual_rank[lb].get(proxy) for lb in US_ROT_LBS}
        has_mom = any(not np.isnan(row["per_lb_momentum"][lb]) for lb in US_ROT_LBS)
        if not has_mom and (np.isnan(row["vol"]) or row["vol"] <= 0.001):
            continue
        reference_rows.append(row)
    reference_per_lb_rows = {}
    for lb in US_ROT_LBS:
        rows = []
        for row in reference_rows:
            rank = row["per_lb_rank"].get(lb)
            mom = row["per_lb_momentum"][lb]
            vol = row["vol"]
            if rank is None or np.isnan(mom) or np.isnan(vol) or vol <= 0.001:
                continue
            ref_row = dict(row)
            ref_row["rank"] = rank
            ref_row["momentum"] = mom
            ref_row["window_weight"] = 0.0
            ref_row["top3"] = rank <= US_ROT_TOP_N
            ref_row["abs_pass"] = mom > US_ROT_ABS_THRESHOLD
            rows.append(ref_row)
        rows.sort(key=lambda x: x["rank"])
        reference_per_lb_rows[lb] = rows

    return {
        "mix_act": mix_act,
        "per_lb": per_lb,
        "vol_row": vol_row,
        "momentum_rows": momentum_rows,
        "per_lb_rows": per_lb_rows,
        "mix_rows": mix_rows,
        "reference_rows": reference_rows,
        "reference_per_lb_rows": reference_per_lb_rows,
    }


def run_us_rotation_mix(close_df, ranking_codes, top_n=US_ROT_TOP_N, abs_threshold=US_ROT_ABS_THRESHOLD,
                        min_turnover=US_ROT_MIN_TURNOVER,
                        threshold=US_ROT_REBALANCE_THRESHOLD,
                        us_open=None,
                        ranking_code_selector=None,
                        weight_assets=None,
                        strict_open_execution=False):
    close_df = _apply_subb_btc_start_filter(close_df)
    momentum_by_lb = {lb: close_df.div(close_df.shift(lb)).sub(1) for lb in US_ROT_LBS}
    vol_df = close_df.pct_change().rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
    start_idx = max(US_ROT_MAX_LB, US_ROT_VOL_LB, US_ROT_VOL_WINDOW) + 1
    signal_days = _us_signal_days(close_df, start_idx)
    act = {"BIL": 1.0}
    holdings = {"BIL": 1.0}
    pending_act = None
    pending_comm = 0.0
    scale = 1.0
    w_assets = list(dict.fromkeys(weight_assets if weight_assets is not None else ranking_codes))
    if "BIL" not in w_assets:
        w_assets.append("BIL")
    prev_risky_by_lb = {lb: None for lb in US_ROT_LBS}
    rows, hist = [], []
    for i in range(start_idx, len(close_df)):
        if len(hist) >= US_ROT_VOL_WINDOW:
            rv = np.std(hist[-US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
            scale = min(max(US_ROT_TARGET_VOL / rv, 0.05), US_ROT_MAX_LEV) if rv > 0.001 else US_ROT_MAX_LEV
        if pending_act is not None:
            open_assets = _active_weight_assets(holdings, pending_act)
            open_row = _us_open_row(
                close_df.index[i],
                open_assets,
                us_open,
                close_df,
                strict=strict_open_execution,
                context="Sub-B official rotation",
            )
            overnight = _us_weighted_return(holdings, close_df.iloc[i - 1], open_row)
            intraday = _us_weighted_return(pending_act, open_row, close_df.iloc[i])
            gross_adj = (1 + overnight) * (1 + intraday) - 1
            execution_cost = float(pending_comm)
            adj = (1 + gross_adj) * (1 - execution_cost) - 1
            holdings = dict(pending_act)
            pending_act = None
            pending_comm = 0.0
        else:
            gross_adj = _us_weighted_return(holdings, close_df.iloc[i - 1], close_df.iloc[i])
            execution_cost = 0.0
            adj = gross_adj
        hist.append(adj)
        is_sig = i in signal_days
        rebalanced = False
        new_act = dict(act)
        row_selected_by_lb = {lb: prev_risky_by_lb.get(lb) for lb in US_ROT_LBS}
        active_ranking_codes = list(ranking_codes)
        if is_sig:
            if ranking_code_selector is not None:
                active_ranking_codes = list(ranking_code_selector(close_df, i, ranking_codes))
            momentum_rows = {lb: momentum_by_lb[lb].iloc[i] for lb in US_ROT_LBS}
            new_act, per_lb = _us_mix_target_weights(
                momentum_rows,
                vol_df.iloc[i],
                active_ranking_codes,
                scale,
                top_n=top_n,
                abs_threshold=abs_threshold,
                prev_risky_by_lb=prev_risky_by_lb,
                threshold=threshold,
            )
            next_prev_risky_by_lb = {lb: per_lb[lb]["selected"] or None for lb in US_ROT_LBS}
            prev_a = {a: act.get(a, 0.0) for a in w_assets} if rows else {"BIL": 1.0}
            all_a = set(list(new_act.keys()) + list(prev_a.keys()))
            to = sum(abs(new_act.get(a, 0.0) - prev_a.get(a, 0.0)) for a in all_a if a != "BIL")
            if _subb_should_rebalance(to, min_turnover):
                pending_act = dict(new_act)
                pending_comm = to * US_ROT_COMMISSION if to > 0 else 0.0
                act = new_act
                prev_risky_by_lb = next_prev_risky_by_lb
                row_selected_by_lb = next_prev_risky_by_lb
                rebalanced = True
        row = {
            "date": close_df.index[i],
            "return": adj,
            "return_before_execution_cost": gross_adj,
            "execution_cost": execution_cost,
            "is_signal": is_sig,
            "rebalanced": rebalanced,
            "inflation_pressure_on": _inflation_pressure_on_from_prices(close_df, i),
            "ranking_codes": ",".join(active_ranking_codes),
        }
        for a in w_assets:
            row[f"w_{a}"] = holdings.get(a, 0.0)
            row[f"actual_w_{a}"] = holdings.get(a, 0.0)
            row[f"target_w_{a}"] = act.get(a, 0.0)
        for lb in US_ROT_LBS:
            row[f"sel_{lb}"] = _serialize_us_mix_selected(row_selected_by_lb.get(lb))
        rows.append(row)
    df = pd.DataFrame(rows).set_index("date")
    df["nav"] = (1 + df["return"]).cumprod()
    return df

def _subb_v75_ema_score(close_df, half_life=SUBB_V75_EMA_HALF_LIFE):
    ret = close_df.pct_change()
    return ret.ewm(halflife=half_life, min_periods=half_life, adjust=False).mean() * US_TRADING_DAYS


def _subb_v75_ema_scale_from_hist(hist):
    min_obs = US_ROT_VOL_WINDOW
    if SUBB_V75_EMA_VOL_MODE == "ewma6m_1vol":
        min_obs = max(US_ROT_VOL_WINDOW, SUBB_V75_EMA_VOL_HALFLIFE_DAYS)
    if len(hist) < min_obs:
        return 1.0
    if SUBB_V75_EMA_VOL_MODE == "ewma6m_1vol":
        rv = (
            pd.Series(hist, dtype=float)
            .ewm(halflife=SUBB_V75_EMA_VOL_HALFLIFE_DAYS, adjust=False)
            .std()
            .iloc[-1]
            * np.sqrt(US_TRADING_DAYS)
        )
    else:
        rv = np.std(hist[-US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
    return min(max(US_ROT_TARGET_VOL / rv, 0.05), US_ROT_MAX_LEV) if rv > 0.001 else US_ROT_MAX_LEV


def run_subb_v75_ema_base7_rotation(
        close_df,
        base_codes=None,
        half_life=SUBB_V75_EMA_HALF_LIFE,
        abs_threshold=SUBB_V75_EMA_ABS_THRESHOLD,
        top_n=US_ROT_TOP_N,
        min_turnover=US_ROT_MIN_TURNOVER,
        threshold=US_ROT_REBALANCE_THRESHOLD,
        us_open=None,
        weight_assets=None,
        strict_open_execution=False):
    """V7.7 EMA leg: full US_ROT_POOL ranking with EWMA target-vol scaling."""
    close_df = _apply_subb_btc_start_filter(close_df)
    ranking_codes = list(base_codes) if base_codes is not None else list(US_ROT_POOL)
    score_df = _subb_v75_ema_score(close_df, half_life)
    vol_df = close_df.pct_change().rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
    start_idx = max(half_life, US_ROT_VOL_LB, US_ROT_VOL_WINDOW) + 1
    signal_days = _us_signal_days(close_df, start_idx)
    w_assets = list(dict.fromkeys(weight_assets if weight_assets is not None else ranking_codes))
    if "BIL" not in w_assets:
        w_assets.append("BIL")

    act = {"BIL": 1.0}
    holdings = {"BIL": 1.0}
    pending_act = None
    pending_comm = 0.0
    scale = 1.0
    rows, hist = [], []
    for i in range(start_idx, len(close_df)):
        scale = _subb_v75_ema_scale_from_hist(hist)
        if pending_act is not None:
            open_assets = _active_weight_assets(holdings, pending_act)
            open_row = _us_open_row(
                close_df.index[i],
                open_assets,
                us_open,
                close_df,
                strict=strict_open_execution,
                context="Sub-B EMA rotation",
            )
            overnight = _us_weighted_return(holdings, close_df.iloc[i - 1], open_row)
            intraday = _us_weighted_return(pending_act, open_row, close_df.iloc[i])
            gross_adj = (1 + overnight) * (1 + intraday) - 1
            execution_cost = float(pending_comm)
            adj = (1 + gross_adj) * (1 - execution_cost) - 1
            holdings = dict(pending_act)
            pending_act = None
            pending_comm = 0.0
        else:
            gross_adj = _us_weighted_return(holdings, close_df.iloc[i - 1], close_df.iloc[i])
            execution_cost = 0.0
            adj = gross_adj

        hist.append(adj)
        is_sig = i in signal_days
        rebalanced = False
        selected = []
        turnover = 0.0
        if is_sig:
            prev_risky = {a for a in w_assets if a != "BIL" and act.get(a, 0.0) > 0.001}
            raw_w = _us_raw_weights(
                score_df.iloc[i],
                vol_df.iloc[i],
                ranking_codes,
                top_n,
                abs_threshold,
                prev_risky=prev_risky if prev_risky else None,
                threshold=threshold,
            )
            new_act = _apply_subb_btc_cap(_us_model_b(raw_w, scale))
            prev_a = {a: act.get(a, 0.0) for a in w_assets} if rows else {"BIL": 1.0}
            all_a = set(list(new_act.keys()) + list(prev_a.keys()))
            turnover = sum(abs(new_act.get(a, 0.0) - prev_a.get(a, 0.0)) for a in all_a if a != "BIL")
            if _subb_should_rebalance(turnover, min_turnover):
                pending_act = dict(new_act)
                pending_comm = turnover * US_ROT_COMMISSION if turnover > 0 else 0.0
                act = new_act
                rebalanced = True
            selected = sorted([a for a, w in raw_w.items() if a != "BIL" and w > 1e-12])

        row = {
            "date": close_df.index[i],
            "return": adj,
            "return_before_execution_cost": gross_adj,
            "execution_cost": execution_cost,
            "is_signal": is_sig,
            "rebalanced": rebalanced,
            "turnover": turnover,
            "scale": scale,
            "target_vol_mode": SUBB_V75_EMA_VOL_MODE,
            "target_vol_halflife_days": SUBB_V75_EMA_VOL_HALFLIFE_DAYS,
            "ranking_codes": ",".join(ranking_codes),
            "selected": ",".join(selected),
            "inflation_pressure_on": _inflation_pressure_on_from_prices(close_df, i),
        }
        for asset in w_assets:
            row[f"w_{asset}"] = holdings.get(asset, 0.0)
            row[f"actual_w_{asset}"] = holdings.get(asset, 0.0)
            row[f"target_w_{asset}"] = act.get(asset, 0.0)
        rows.append(row)
    df = pd.DataFrame(rows).set_index("date")
    df["nav"] = (1 + df["return"]).cumprod()
    return df

def blend_subb_v75_results(official_result, ema_result,
                           official_weight=SUBB_V75_OFFICIAL_WEIGHT,
                           ema_weight=SUBB_V75_EMA_WEIGHT):
    common_index = official_result.dropna(subset=["return"]).index.intersection(
        ema_result.dropna(subset=["return"]).index
    )
    if common_index.empty:
        raise ValueError("Sub-B V7.7 official/EMA blend has no overlapping return window.")
    official = official_result.reindex(common_index)
    ema = ema_result.reindex(common_index)
    out = official.copy()
    official_gross = official.get("return_before_execution_cost", official["return"]).astype(float)
    ema_gross = ema.get("return_before_execution_cost", ema["return"]).astype(float)
    out["official_return"] = official["return"].astype(float)
    out["ema_return"] = ema["return"].astype(float)
    out["official_return_before_execution_cost"] = official_gross
    out["ema_return_before_execution_cost"] = ema_gross
    out["return_before_subb_execution_cost"] = official_weight * official_gross + ema_weight * ema_gross
    out["subb_blend_official_weight"] = float(official_weight)
    out["subb_blend_ema_weight"] = float(ema_weight)
    out["subb_ema_half_life"] = int(SUBB_V75_EMA_HALF_LIFE)
    out["subb_ema_abs_threshold"] = float(SUBB_V75_EMA_ABS_THRESHOLD)
    out["subb_ema_vol_mode"] = SUBB_V75_EMA_VOL_MODE
    out["subb_ema_vol_halflife_days"] = int(SUBB_V75_EMA_VOL_HALFLIFE_DAYS)
    if "scale" in official.columns:
        out["official_scale"] = official["scale"]
    if "scale" in ema.columns:
        out["ema_scale"] = ema["scale"]
    if "selected" in ema.columns:
        out["ema_selected"] = ema["selected"]
    if "is_signal" in ema.columns:
        out["is_signal"] = official.get("is_signal", False).astype(bool) | ema["is_signal"].astype(bool)
    if "rebalanced" in ema.columns:
        out["rebalanced"] = official.get("rebalanced", False).astype(bool) | ema["rebalanced"].astype(bool)
    assets = sorted(set(_weight_columns_assets(official)) | set(_weight_columns_assets(ema)))
    actual_df = pd.DataFrame(index=common_index)
    target_df = pd.DataFrame(index=common_index)
    blended_weight_cols = {}
    for asset in assets:
        official_w = pd.to_numeric(
            official.get(f"w_{asset}", pd.Series(0.0, index=common_index)),
            errors="coerce",
        ).reindex(common_index).fillna(0.0)
        ema_w = pd.to_numeric(
            ema.get(f"w_{asset}", pd.Series(0.0, index=common_index)),
            errors="coerce",
        ).reindex(common_index).fillna(0.0)
        official_actual = pd.to_numeric(
            official.get(f"actual_w_{asset}", official_w),
            errors="coerce",
        ).reindex(common_index).fillna(0.0)
        ema_actual = pd.to_numeric(
            ema.get(f"actual_w_{asset}", ema_w),
            errors="coerce",
        ).reindex(common_index).fillna(0.0)
        official_target = pd.to_numeric(
            official.get(f"target_w_{asset}", official_w),
            errors="coerce",
        ).reindex(common_index).fillna(0.0)
        ema_target = pd.to_numeric(
            ema.get(f"target_w_{asset}", ema_w),
            errors="coerce",
        ).reindex(common_index).fillna(0.0)

        official_contrib_actual = official_weight * official_actual
        ema_contrib_actual = ema_weight * ema_actual
        official_contrib_target = official_weight * official_target
        ema_contrib_target = ema_weight * ema_target
        actual_df[asset] = official_contrib_actual + ema_contrib_actual
        target_df[asset] = official_contrib_target + ema_contrib_target
        blended_weight_cols[f"official_w_{asset}"] = official_target
        blended_weight_cols[f"ema_w_{asset}"] = ema_target
        blended_weight_cols[f"official_actual_w_{asset}"] = official_actual
        blended_weight_cols[f"ema_actual_w_{asset}"] = ema_actual
        blended_weight_cols[f"official_contrib_w_{asset}"] = official_contrib_target
        blended_weight_cols[f"ema_contrib_w_{asset}"] = ema_contrib_target
        blended_weight_cols[f"actual_w_{asset}"] = actual_df[asset]
        blended_weight_cols[f"target_w_{asset}"] = target_df[asset]
        blended_weight_cols[f"w_{asset}"] = actual_df[asset]
    if blended_weight_cols:
        out = pd.concat(
            [
                out.drop(columns=list(blended_weight_cols), errors="ignore"),
                pd.DataFrame(blended_weight_cols, index=common_index),
            ],
            axis=1,
        )
    prev_actual = None
    turnovers = []
    costs = []
    for dt in common_index:
        actual = actual_df.loc[dt].to_dict()
        if prev_actual is None:
            prev_actual = {"BIL": 1.0}
        turnover = _dict_tradeable_turnover(prev_actual, actual, non_tradeable_assets=("BIL",))
        turnovers.append(turnover)
        costs.append(turnover * US_ROT_COMMISSION)
        prev_actual = actual
    out["subb_execution_turnover"] = pd.Series(turnovers, index=common_index, dtype=float)
    out["subb_execution_cost"] = pd.Series(costs, index=common_index, dtype=float)
    out["return"] = (1.0 + out["return_before_subb_execution_cost"]) * (1.0 - out["subb_execution_cost"]) - 1.0
    out["nav"] = (1 + out["return"]).cumprod()
    return out


def _v78_normalize_weights(weights):
    out = {k: float(v) for k, v in dict(weights).items() if abs(float(v)) > 1e-12}
    total = sum(out.values())
    if total <= 0:
        return {"BIL": 1.0}
    if abs(total - 1.0) > 1e-10:
        out = {k: v / total for k, v in out.items()}
    return out


def _v78_apply_equity_scale(weights, scale):
    out = dict(weights)
    cash_add = 0.0
    for asset in US_ROT_VOLREG_SCALE_ASSETS:
        old = float(out.get(asset, 0.0))
        if old > 1e-12:
            new = old * float(scale)
            out[asset] = new
            cash_add += old - new
    out["BIL"] = out.get("BIL", 0.0) + cash_add
    return _v78_normalize_weights(out)


def _v78_fetch_spy_volume(index, timeout=20):
    try:
        start = int((pd.Timestamp(index.min()) - pd.Timedelta(days=10)).timestamp())
        end = int((pd.Timestamp(index.max()) + pd.Timedelta(days=5)).timestamp())
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/SPY"
            f"?period1={start}&period2={end}&interval=1d&events=history"
        )
        resp = _session.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        ts = pd.to_datetime(result["timestamp"], unit="s").tz_localize("UTC").tz_convert("America/New_York").tz_localize(None).normalize()
        vol = result["indicators"]["quote"][0]["volume"]
        out = pd.Series(vol, index=ts, dtype=float).sort_index()
        out = out[~out.index.duplicated(keep="last")]
        return out, "Yahoo chart SPY volume"
    except Exception as exc:
        return pd.Series(False, index=index, dtype=bool), f"unavailable: {_short_error(exc)}"


def _v78_spy_volume_cache_path():
    base_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    return os.path.join(base_dir, ".us_market_cache", "SPY_volume.csv")


def _clean_v78_spy_volume(series):
    out = pd.to_numeric(pd.Series(series), errors="coerce")
    out.index = pd.DatetimeIndex(pd.to_datetime(out.index)).tz_localize(None).normalize()
    out = out.dropna()
    out = out[out > 0]
    return out[~out.index.duplicated(keep="last")].sort_index().astype(float)


def _load_v78_spy_volume_cache():
    path = _v78_spy_volume_cache_path()
    if not os.path.exists(path):
        raise FileNotFoundError("no SPY volume cache")
    frame = pd.read_csv(path)
    if "date" not in frame.columns or "volume" not in frame.columns:
        raise ValueError("invalid SPY volume cache schema")
    series = _clean_v78_spy_volume(frame.set_index("date")["volume"])
    if series.empty:
        raise ValueError("SPY volume cache has no usable rows")
    return series


def _save_v78_spy_volume_cache(series):
    fresh = _clean_v78_spy_volume(series)
    if fresh.empty:
        return
    try:
        cached = _load_v78_spy_volume_cache()
    except (FileNotFoundError, ValueError, OSError):
        cached = pd.Series(dtype=float)
    merged = fresh.combine_first(cached).sort_index()
    path = _v78_spy_volume_cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged.rename("volume").to_csv(path, index_label="date", encoding="utf-8")


def _v78_fetch_spy_volume_stooq(index, timeout=20):
    try:
        start = pd.Timestamp(index.min()).strftime("%Y%m%d")
        end = (pd.Timestamp(index.max()) + pd.Timedelta(days=5)).strftime("%Y%m%d")
        url = f"https://stooq.com/q/d/l/?s=spy.us&d1={start}&d2={end}&i=d"
        resp = _session.get(url, timeout=timeout)
        resp.raise_for_status()
        frame = pd.read_csv(io.StringIO(resp.text))
        if "Date" not in frame.columns or "Volume" not in frame.columns:
            raise ValueError("Stooq SPY volume schema missing Date/Volume")
        series = _clean_v78_spy_volume(frame.set_index("Date")["Volume"])
        if series.empty:
            raise ValueError("Stooq SPY volume is empty")
        return series, "Stooq SPY volume"
    except Exception as exc:
        return pd.Series(False, index=index, dtype=bool), f"unavailable: {_short_error(exc)}"


def _v78_spy_volume_gate(index):
    target_index = pd.DatetimeIndex(pd.to_datetime(index)).tz_localize(None).normalize()
    mode = str(globals().get("V78_SUBB_SPY_VOLUME_FAIL_MODE", "warn_open") or "warn_open").lower()
    if mode not in ("warn_open", "fail_closed", "raise"):
        raise ValueError(f"Unsupported V78_SUBB_SPY_VOLUME_FAIL_MODE: {mode}")

    merged = pd.Series(dtype=float)
    valid_sources = []
    failures = []
    for fetcher in (_v78_fetch_spy_volume, _v78_fetch_spy_volume_stooq):
        candidate, source = fetcher(target_index)
        if getattr(candidate, "dtype", None) == bool:
            failures.append(str(source))
            continue
        candidate = _clean_v78_spy_volume(candidate)
        if candidate.empty:
            failures.append(f"{source}; empty")
            continue
        merged = merged.combine_first(candidate) if not merged.empty else candidate
        valid_sources.append(str(source))
    try:
        cached = _load_v78_spy_volume_cache()
        merged = merged.combine_first(cached)
        valid_sources.append("local-cache SPY volume")
    except (FileNotFoundError, ValueError, OSError) as exc:
        failures.append(f"cache unavailable: {_short_error(exc)}")

    if not merged.empty and valid_sources and any("Yahoo" in item or "Stooq" in item for item in valid_sources):
        try:
            _save_v78_spy_volume_cache(merged)
        except OSError as exc:
            failures.append(f"cache write unavailable: {_short_error(exc)}")

    aligned = pd.Series(np.nan, index=target_index, dtype=float)
    if not merged.empty:
        expanded_index = merged.index.union(target_index).sort_values()
        aligned = merged.reindex(expanded_index).ffill().reindex(target_index)
        aligned.loc[target_index < merged.index.min()] = np.nan
        aligned.loc[target_index > merged.index.max()] = np.nan
    ratio = aligned / aligned.rolling(60, min_periods=60).mean()
    gate = (ratio >= 1.5).fillna(False).astype(bool)
    unresolved = aligned.isna()
    if unresolved.any():
        missing_dates = target_index[unresolved]
        reason = (
            f"unresolved SPY volume {missing_dates.min().date().isoformat()}.."
            f"{missing_dates.max().date().isoformat()} ({int(unresolved.sum())} dates)"
        )
        if mode == "raise":
            raise RuntimeError(f"SPY volume unavailable: {reason}")
        if mode == "fail_closed":
            gate.loc[unresolved] = True
            failures.append(f"{reason}; fail_closed")
        else:
            failures.append(f"{reason}; warn_open")
    source_parts = valid_sources + failures
    source = " | ".join(dict.fromkeys(source_parts)) or "unavailable: SPY volume"
    return gate, source


def _v78_score_bias_level(close_df):
    weights = {160: 3.0, 260: 2.0, 390: 1.0}
    score = pd.DataFrame(0.0, index=close_df.index, columns=US_ROT_POOL)
    denom = sum(weights.values())
    for lb, weight in weights.items():
        score = score + (close_df[US_ROT_POOL] / close_df[US_ROT_POOL].rolling(lb).mean() - 1.0) * (weight / denom)
    return score


def _v78_score_log_weighted(close_df):
    weights = {120: 0.60, 200: 0.30, 320: 0.10}
    score = pd.DataFrame(0.0, index=close_df.index, columns=US_ROT_POOL)
    for lb, weight in weights.items():
        score = score + np.log(close_df[US_ROT_POOL] / close_df[US_ROT_POOL].shift(lb)) * weight
    return score


def _v78_target_from_scores(score_row, vol_row, scale, top_n=US_ROT_TOP_N, abs_threshold=0.0):
    raw_w = _us_raw_weights(
        score_row,
        vol_row,
        US_ROT_POOL,
        top_n,
        abs_threshold,
        prev_risky=None,
        threshold=1.0,
    )
    return _apply_subb_btc_cap(_us_model_b(raw_w, scale))


def run_v78_subb_new_line(close_df, line="bias", us_open=None, strict_open_execution=False):
    close_df = _apply_subb_btc_start_filter(close_df)
    w_assets = list(dict.fromkeys(US_ROT_POOL + ["BIL"]))
    if line == "bias":
        scores = _v78_score_bias_level(close_df)
        target_vol, vol_window, max_leverage = 0.25, 40, 1.5
        abs_threshold = 0.0
        start_idx = max(390, US_ROT_VOL_LB, vol_window) + 1
    elif line == "logvol":
        scores = _v78_score_log_weighted(close_df)
        target_vol, vol_window, max_leverage = 0.30, 40, 1.25
        abs_threshold = 0.0
        start_idx = max(320, US_ROT_VOL_LB, vol_window) + 1
    else:
        raise ValueError(line)
    vol_df = close_df.pct_change().rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
    signal_days = _us_signal_days(close_df, start_idx)
    volume_gate, volume_source = _v78_spy_volume_gate(close_df.index)
    holdings = {"BIL": 1.0}
    target = {"BIL": 1.0}
    pending_act = None
    pending_comm = 0.0
    hist = []
    rows = []
    for i in range(start_idx, len(close_df)):
        dt = close_df.index[i]
        if len(hist) >= vol_window:
            rv = np.std(hist[-vol_window:], ddof=1) * np.sqrt(US_TRADING_DAYS)
            scale = min(max(target_vol / rv, 0.05), max_leverage) if rv > 0.001 else max_leverage
        else:
            rv = np.nan
            scale = 1.0
        if pending_act is not None:
            open_assets = _active_weight_assets(holdings, pending_act)
            open_row = _us_open_row(
                dt,
                open_assets,
                us_open,
                close_df,
                strict=strict_open_execution,
                context=f"Sub-B V7.9 {line} rotation",
            )
            overnight = _us_weighted_return(holdings, close_df.iloc[i - 1], open_row)
            intraday = _us_weighted_return(pending_act, open_row, close_df.iloc[i])
            gross = (1.0 + overnight) * (1.0 + intraday) - 1.0
            execution_cost = float(pending_comm)
            ret = (1.0 + gross) * (1.0 - execution_cost) - 1.0
            holdings = dict(pending_act)
            pending_act = None
            pending_comm = 0.0
        else:
            gross = _us_weighted_return(holdings, close_df.iloc[i - 1], close_df.iloc[i])
            execution_cost = 0.0
            ret = gross
        hist.append(float(ret))

        is_signal = i in signal_days
        rebalanced = False
        turnover = 0.0
        gate_next = bool(volume_gate.reindex(close_df.index).iloc[i])
        volume_scale = 0.75 if gate_next else 1.0
        logvol_high_vol_on = bool(line == "logvol" and np.isfinite(rv) and rv >= 0.50)
        logvol_high_vol_scale = 0.75 if logvol_high_vol_on else 1.0
        if is_signal:
            base_target = _v78_target_from_scores(scores.iloc[i], vol_df.iloc[i], scale, top_n=US_ROT_TOP_N, abs_threshold=abs_threshold)
            target = _v78_apply_equity_scale(base_target, volume_scale * logvol_high_vol_scale)
            all_a = set(target) | set(holdings)
            turnover = sum(abs(target.get(a, 0.0) - holdings.get(a, 0.0)) for a in all_a if a != "BIL")
            pending_act = dict(target)
            pending_comm = turnover * US_ROT_COMMISSION if turnover > 0 else 0.0
            rebalanced = True
        row = {
            "date": dt,
            "return": float(ret),
            "return_before_execution_cost": float(gross),
            "execution_cost": float(execution_cost),
            "is_signal": bool(is_signal),
            "rebalanced": bool(rebalanced),
            "turnover": float(turnover),
            "target_vol_scale": float(scale),
            "realized_vol": float(rv) if np.isfinite(rv) else np.nan,
            "volume_gate_next": bool(gate_next),
            "volume_scale_next": float(volume_scale),
            "logvol_high_vol_on": bool(logvol_high_vol_on),
            "logvol_high_vol_scale": float(logvol_high_vol_scale),
            "volume_source": volume_source,
            "line": line,
        }
        for asset in w_assets:
            row[f"w_{asset}"] = holdings.get(asset, 0.0)
            row[f"actual_w_{asset}"] = holdings.get(asset, 0.0)
            row[f"target_w_{asset}"] = target.get(asset, 0.0)
        rows.append(row)
    out = pd.DataFrame(rows).set_index("date")
    out["nav"] = (1.0 + out["return"].fillna(0.0)).cumprod()
    return out


def _v78_subb_new_line_hypo_weights(close_df, result_df, line="bias", row_idx=-1):
    if line == "bias":
        scores = _v78_score_bias_level(close_df)
    elif line == "logvol":
        scores = _v78_score_log_weighted(close_df)
    else:
        raise ValueError(line)
    vol_row = close_df.pct_change().rolling(US_ROT_VOL_LB).std().mul(np.sqrt(US_TRADING_DAYS)).iloc[row_idx]
    scale = 1.0
    volume_scale = 1.0
    logvol_high_vol_scale = 1.0
    if result_df is not None and len(result_df) > 0:
        try:
            result_row = result_df.iloc[row_idx]
            scale = float(result_row.get("target_vol_scale", 1.0) or 1.0)
            volume_scale = float(result_row.get("volume_scale_next", 1.0) or 1.0)
            logvol_high_vol_scale = float(result_row.get("logvol_high_vol_scale", 1.0) or 1.0)
        except Exception:
            pass
    base_target = _v78_target_from_scores(scores.iloc[row_idx], vol_row, scale, top_n=US_ROT_TOP_N, abs_threshold=0.0)
    return _v78_apply_equity_scale(base_target, volume_scale * (logvol_high_vol_scale if line == "logvol" else 1.0))


def _v78_subb_new_line_hypo_weights_from_blend(close_df, us_rot_result, line="bias", row_idx=-1):
    attr_name = {
        "bias": "v78_subb_bias",
        "logvol": "v78_subb_logvol",
    }.get(line)
    component_result = None
    if us_rot_result is not None and attr_name:
        component_result = us_rot_result.attrs.get(attr_name)
    return _v78_subb_new_line_hypo_weights(
        close_df,
        component_result,
        line=line,
        row_idx=row_idx,
    )


def blend_v78_subb_results(v77_result, bias_result, logvol_result):
    common_index = v77_result.dropna(subset=["return"]).index
    common_index = common_index.intersection(bias_result.dropna(subset=["return"]).index)
    common_index = common_index.intersection(logvol_result.dropna(subset=["return"]).index)
    if common_index.empty:
        raise ValueError("V7.9 Sub-B blend has no overlapping return window.")
    v77 = v77_result.reindex(common_index)
    bias = bias_result.reindex(common_index)
    logvol = logvol_result.reindex(common_index)
    out = v77.copy()
    out["v78_subb_v77_return"] = v77["return"].astype(float)
    out["v78_subb_bias_return"] = bias["return"].astype(float)
    out["v78_subb_logvol_return"] = logvol["return"].astype(float)
    out["return"] = (
        V78_SUBB_V77_WEIGHT * out["v78_subb_v77_return"]
        + V78_SUBB_NEW_BIAS_WEIGHT * out["v78_subb_bias_return"]
        + V78_SUBB_NEW_LOGVOL_WEIGHT * out["v78_subb_logvol_return"]
    )
    out["return_before_v78_subb_blend"] = out["return"]
    out["v78_subb_component_net_return"] = out["return"]
    out["return_before_subb_execution_cost"] = out["return"]
    out["subb_execution_cost"] = 0.0
    out["cost_basis_note"] = "component-net blend; component costs already included; account-level target turnover is display-only"
    out["nav"] = (1.0 + out["return"].fillna(0.0)).cumprod()
    for flag_col in ("is_signal", "rebalanced"):
        out[flag_col] = (
            v77.get(flag_col, pd.Series(False, index=common_index)).astype(bool)
            | bias.get(flag_col, pd.Series(False, index=common_index)).astype(bool)
            | logvol.get(flag_col, pd.Series(False, index=common_index)).astype(bool)
        )
    out["model_rebalanced"] = out["rebalanced"]
    out["effective_rebalanced"] = out["rebalanced"]
    assets = sorted(set(_weight_columns_assets(v77)) | set(_weight_columns_assets(bias)) | set(_weight_columns_assets(logvol)))
    weight_cols = {}
    for asset in assets:
        zero = pd.Series(0.0, index=common_index)
        v77_actual = pd.to_numeric(v77.get(f"actual_w_{asset}", v77.get(f"w_{asset}", zero)), errors="coerce").fillna(0.0)
        bias_actual = pd.to_numeric(bias.get(f"actual_w_{asset}", bias.get(f"w_{asset}", zero)), errors="coerce").fillna(0.0)
        logvol_actual = pd.to_numeric(logvol.get(f"actual_w_{asset}", logvol.get(f"w_{asset}", zero)), errors="coerce").fillna(0.0)
        v77_target = pd.to_numeric(v77.get(f"target_w_{asset}", v77_actual), errors="coerce").fillna(0.0)
        bias_target = pd.to_numeric(bias.get(f"target_w_{asset}", bias_actual), errors="coerce").fillna(0.0)
        logvol_target = pd.to_numeric(logvol.get(f"target_w_{asset}", logvol_actual), errors="coerce").fillna(0.0)
        actual_w = V78_SUBB_V77_WEIGHT * v77_actual + V78_SUBB_NEW_BIAS_WEIGHT * bias_actual + V78_SUBB_NEW_LOGVOL_WEIGHT * logvol_actual
        target_w = V78_SUBB_V77_WEIGHT * v77_target + V78_SUBB_NEW_BIAS_WEIGHT * bias_target + V78_SUBB_NEW_LOGVOL_WEIGHT * logvol_target
        weight_cols[f"v78_v77_w_{asset}"] = v77_actual
        weight_cols[f"v78_bias_w_{asset}"] = bias_actual
        weight_cols[f"v78_logvol_w_{asset}"] = logvol_actual
        weight_cols[f"v78_v77_target_w_{asset}"] = v77_target
        weight_cols[f"v78_bias_target_w_{asset}"] = bias_target
        weight_cols[f"v78_logvol_target_w_{asset}"] = logvol_target
        weight_cols[f"w_{asset}"] = actual_w
        weight_cols[f"actual_w_{asset}"] = actual_w
        weight_cols[f"target_w_{asset}"] = target_w
    if weight_cols:
        out = out.drop(columns=[col for col in weight_cols if col in out.columns], errors="ignore")
        out = pd.concat([out, pd.DataFrame(weight_cols, index=common_index)], axis=1)
    out["v78_blend_label"] = (
        f"{V78_SUBB_V77_WEIGHT * SUBB_V75_OFFICIAL_WEIGHT:.0%} Official + "
        f"{V78_SUBB_V77_WEIGHT * SUBB_V75_EMA_WEIGHT:.0%} EMA + "
        f"{V78_SUBB_NEW_BIAS_WEIGHT:.0%} Bias + "
        f"{V78_SUBB_NEW_LOGVOL_WEIGHT:.0%} LogVol"
    )
    out.attrs["v78_subb_v77"] = v77_result
    out.attrs["v78_subb_bias"] = bias_result
    out.attrs["v78_subb_logvol"] = logvol_result
    return out


def _fmt_v78_pct(value):
    try:
        return f"{float(value):.1%}"
    except Exception:
        return "N/A"


def _fmt_v78_x(value):
    try:
        return f"{float(value):.2f}x"
    except Exception:
        return "N/A"


def _fmt_v78_score(value):
    try:
        value = float(value)
    except Exception:
        return "N/A"
    if not np.isfinite(value):
        return "N/A"
    return f"{value:.4f}"


def _v78_suba_new_signal_rows(cn_result, idx, max_rows=None):
    new_result = cn_result.attrs.get("v78_suba_new") if hasattr(cn_result, "attrs") else None
    if new_result is None or len(new_result) == 0:
        return []
    raw_score = new_result.attrs.get("v78_raw_score")
    if raw_score is None:
        raw_score = new_result.attrs.get("v78_score")
    abs_mom = new_result.attrs.get("v78_abs_mom")
    gated_score = new_result.attrs.get("v78_score")
    if raw_score is None or len(raw_score) == 0:
        return []
    date = cn_result.index[idx]
    try:
        pos = raw_score.index.get_loc(date)
    except Exception:
        pos = idx
    if isinstance(pos, slice) or not isinstance(pos, (int, np.integer)):
        pos = int(np.asarray(pos)[0])
    raw_row = pd.to_numeric(raw_score.iloc[pos], errors="coerce")
    abs_row = pd.to_numeric(abs_mom.iloc[pos], errors="coerce") if abs_mom is not None else pd.Series(np.nan, index=raw_row.index)
    gated_row = pd.to_numeric(gated_score.iloc[pos], errors="coerce") if gated_score is not None else pd.Series(np.nan, index=raw_row.index)
    selected_code = None
    finite_gated = gated_row.replace([np.inf, -np.inf], np.nan).dropna()
    if len(finite_gated) > 0:
        selected_code = finite_gated.idxmax()
    sort_key = raw_row.replace([np.inf, -np.inf], np.nan).fillna(float("-inf"))
    codes = list(sort_key.sort_values(ascending=False).index)
    if max_rows is not None:
        codes = codes[: int(max_rows)]
    rows = []
    for code in codes:
        score_value = raw_row.get(code, np.nan)
        abs_value = abs_row.get(code, np.nan)
        score_pass = bool(pd.notna(score_value) and float(score_value) > V78_SUBA_NEW_SCORE_THRESHOLD)
        abs_pass = bool(pd.notna(abs_value) and float(abs_value) > V78_SUBA_NEW_ABS_THRESHOLD)
        rows.append(
            {
                "code": code,
                "name": CN_NAMES.get(code, code),
                "score": float(score_value) if pd.notna(score_value) else np.nan,
                "abs_mom": float(abs_value) if pd.notna(abs_value) else np.nan,
                "score_pass": score_pass,
                "abs_pass": abs_pass,
                "selected": bool(code == selected_code),
            }
        )
    return rows


def _write_v78_suba_new_signal_table(w, cn_result, idx):
    _write_v78_suba_new_leg_signal_table(w, cn_result, idx)


def _v78_plain_status_text(text):
    text = str(text)
    for marker in ("⛔", "✅", "❌", "🟢", "🔴"):
        text = text.replace(marker, "")
    return " ".join(text.split())


def _write_unified_suba_leg_rows(w, title, subtitle, rows):
    if not rows:
        return
    w(f"\n**{title}**")
    if subtitle:
        w(f" ({subtitle})")
    w("\n\n")
    w("| # | 资产 | 排名分数 | 质量过滤 | 动量过滤 | 状态 |\n")
    w("|:-|:-|------:|:-|:-|:-|\n")
    for rank, row in enumerate(rows, 1):
        marker = " 🎯" if row.get("selected") else ""
        hold_marker = " 👈" if row.get("current_holding") else ""
        status = _v78_plain_status_text(row["status"])
        w(
            f"| {rank}{marker} | {row['name']}{hold_marker} | {row['score_text']} | "
            f"{row['quality_text']} | {row['momentum_text']} | {status} |\n"
        )


def _write_v78_suba_new_leg_signal_table(w, cn_result, idx):
    rows = _v78_suba_new_signal_rows(cn_result, idx)
    if not rows:
        return
    unified = []
    for row in rows:
        selected = bool(row["selected"])
        quality_text = "score通过" if row["score_pass"] else "score未通过"
        momentum_text = f"abs{V78_SUBA_NEW_ABS_DAY}通过" if row["abs_pass"] else f"abs{V78_SUBA_NEW_ABS_DAY}未通过"
        status = "Top-1" if selected else ("候选" if row["score_pass"] and row["abs_pass"] else "排除")
        unified.append({
            "name": row["name"],
            "score_text": _fmt_v78_score(row["score"]),
            "quality_text": quality_text,
            "momentum_text": f"{_format_suba_abs_mom(row['abs_mom'])} / {momentum_text}",
            "status": status,
            "selected": selected,
            "current_holding": False,
        })
    _write_unified_suba_leg_rows(
        w,
        "New A TV1.0 子策略状态",
        f"MA{V78_SUBA_NEW_MA}/{V78_SUBA_NEW_MOM_DAY} score>{V78_SUBA_NEW_SCORE_THRESHOLD:.4f}, abs{V78_SUBA_NEW_ABS_DAY}>{V78_SUBA_NEW_ABS_THRESHOLD:.0%}",
        unified,
    )


def _v78_suba_v77_leg_rows(bias_mom, r2, abs_mom, codes, idx, current_holding="cash"):
    rows = []
    for code in codes:
        bm = _series_value_at(bias_mom.get(code), None, idx)
        if np.isnan(bm):
            continue
        r2v = _series_value_at(r2.get(code), None, idx)
        absv = _series_value_at(abs_mom.get(code), None, idx) if abs_mom else np.nan
        rows.append({
            "code": code,
            "asset_name": CN_NAMES.get(code, code),
            "current_momentum": bm,
            "current_r2": r2v,
            "current_abs_mom": absv,
            "status": _suba_filter_status(bm, r2v, absv),
        })
    rows.sort(key=lambda row: row["current_momentum"], reverse=True)
    unified = []
    for row in rows:
        bm = row["current_momentum"]
        r2v = row["current_r2"]
        absv = row["current_abs_mom"]
        r2_pass = pd.notna(r2v) and float(r2v) >= CN_R2_THRESHOLD
        abs_pass = _suba_abs_mom_pass(absv)
        bm_pass = pd.notna(bm) and float(bm) > 0
        unified.append({
            "name": row["asset_name"],
            "score_text": f"{float(bm):+.1f}" if pd.notna(bm) else "N/A",
            "quality_text": f"R² {float(r2v):.3f} {'通过' if r2_pass else '未通过'}" if pd.notna(r2v) else "R² N/A",
            "momentum_text": f"{CN_ABS_MOM_DAY}日 {_format_suba_abs_mom(absv)} {'通过' if abs_pass else '未通过'}",
            "status": row["status"],
            "selected": bool(len(unified) == 0 and bm_pass and r2_pass and abs_pass),
            "current_holding": row["code"] == current_holding,
        })
    return unified


def _write_v78_suba_v77_leg_signal_table(w, bias_mom, r2, abs_mom, codes, idx, current_holding="cash"):
    rows = _v78_suba_v77_leg_rows(bias_mom, r2, abs_mom, codes, idx, current_holding=current_holding)
    _write_unified_suba_leg_rows(
        w,
        "V7.7A原版 子策略状态",
        f"bias_mom排序 + R²≥{CN_R2_THRESHOLD:.2f} + {CN_ABS_MOM_DAY}日动量>{CN_ABS_MOM_THRESHOLD:.0%}",
        rows,
    )


def _write_v78_suba_leg_signal_tables(w, cn_result, idx, bias_mom, r2, abs_mom, codes, current_holding="cash"):
    _write_v78_suba_v77_leg_signal_table(
        w,
        bias_mom,
        r2,
        abs_mom,
        codes,
        idx,
        current_holding=current_holding,
    )
    _write_v78_suba_new_leg_signal_table(w, cn_result, idx)


def _v78_suba_display_leg_snapshot(cn_result, idx):
    n = len(cn_result)
    pos = idx if idx >= 0 else n + idx
    pos = int(np.clip(pos, 0, n - 1))
    row = cn_result.iloc[pos]
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    v77_h = row.get("v78_suba_v77_holding", "cash")
    new_h = row.get("v78_suba_new_holding", "cash")
    v77_w = _to_float(row.get("v78_suba_v77_weight", 0.0))
    new_w = _to_float(row.get("v78_suba_new_weight", 0.0))
    return {
        "v77_holding": v77_h,
        "new_holding": new_h,
        "v77_weight": v77_w,
        "new_weight": new_w,
        "final_exposure": V78_SUBA_V77_WEIGHT * v77_w + V78_SUBA_NEW_TV10_WEIGHT * new_w,
    }


def _write_v78_suba_blend_table(w, cn_result, idx):
    if "v78_suba_v77_holding" not in cn_result.columns:
        return
    display = _v78_suba_display_leg_snapshot(cn_result, idx)
    v77_h = display["v77_holding"]
    new_h = display["new_holding"]
    v77_w = display["v77_weight"]
    new_w = display["new_weight"]
    w("\n**V7.9 Sub-A混合腿拆分（沿用7.7展示样式）**\n\n")
    w("| 腿 | 组合权重 | 当前持仓 | 腿内敞口 | 组合贡献 |\n")
    w("|:-|------:|:-|------:|------:|\n")
    w(f"| V7.7A原版 | {V78_SUBA_V77_WEIGHT:.0%} | {CN_NAMES.get(v77_h, v77_h)} | {_fmt_v78_x(v77_w)} | {_fmt_v78_x(V78_SUBA_V77_WEIGHT * v77_w)} |\n")
    w(f"| {V78_SUBA_NEW_LABEL} | {V78_SUBA_NEW_TV10_WEIGHT:.0%} | {CN_NAMES.get(new_h, new_h)} | {_fmt_v78_x(new_w)} | {_fmt_v78_x(V78_SUBA_NEW_TV10_WEIGHT * new_w)} |\n")
    w(f"| **V7.9最终** | **100%** | - | - | **{_fmt_v78_x(display['final_exposure'])}** |\n")


def _write_v78_adk_blend_table(w, cn_dk_result, idx, position_col_label="当前配对/方向"):
    if "v78_adk_v77_holding" not in cn_dk_result.columns:
        return
    row = cn_dk_result.iloc[idx]
    v77_h = row.get("v78_adk_v77_holding", "none_0")
    new_h = row.get("v78_adk_new_holding", "none_0")
    w("\n**V7.9 ADK 混合腿拆分（沿用7.7展示样式）**\n\n")
    w(f"| 腿 | 组合权重 | {position_col_label} | 腿内敞口 | 组合贡献 |\n")
    w("|:-|------:|:-|------:|------:|\n")
    w(f"| V7.7 ADK原版 | {V78_ADK_V77_WEIGHT:.0%} | {_dk_pos_str(v77_h)} | {_fmt_v78_x(row.get('v78_adk_v77_weight', 0.0))} | {_fmt_v78_x(V78_ADK_V77_WEIGHT * float(row.get('v78_adk_v77_weight', 0.0)))} |\n")
    w(f"| {V78_ADK_NEW_LABEL} | {V78_ADK_NEW_PRIMARY_WEIGHT:.0%} | {_dk_pos_str(new_h)} | {_fmt_v78_x(row.get('v78_adk_new_weight', 0.0))} | {_fmt_v78_x(V78_ADK_NEW_PRIMARY_WEIGHT * float(row.get('v78_adk_new_weight', 0.0)))} |\n")
    w(f"| **V7.9最终** | **100%** | - | - | **{_fmt_v78_x(row.get('v78_adk_final_exposure', 0.0))}** |\n")


def _write_v78_adk_net_exposure_table(w, cn_dk_result, idx):
    if "adk_net_asset_exposure" not in cn_dk_result.columns:
        return
    resolved_idx, _ = _v78_resolve_display_idx_date(cn_dk_result, idx)
    if resolved_idx is None:
        return
    net = cn_dk_result.iloc[resolved_idx].get("adk_net_asset_exposure", {}) or {}
    if not net:
        return
    w("\n**V7.9 ADK账户级净敞口（实盘优先看这一张）**\n\n")
    w("| 指数 | 净敞口 | 方向 |\n")
    w("|:-|------:|:-|\n")
    for asset, exposure in sorted(net.items(), key=lambda item: abs(float(item[1])), reverse=True):
        exposure = float(exposure)
        direction = "做多" if exposure > 0 else "做空"
        w(f"| {_dk_leg_name(asset)} | {abs(exposure):.2f}x | {direction} |\n")


def _adk_net_exposure_changed(cn_dk_result, old_idx, new_idx, threshold=1e-4):
    if cn_dk_result is None or "adk_net_asset_exposure" not in cn_dk_result.columns:
        return False
    old_resolved_idx, _ = _v78_resolve_display_idx_date(cn_dk_result, old_idx)
    new_resolved_idx, _ = _v78_resolve_display_idx_date(cn_dk_result, new_idx)
    if old_resolved_idx is None or new_resolved_idx is None:
        return False
    old_net = cn_dk_result.iloc[old_resolved_idx].get("adk_net_asset_exposure", {}) or {}
    new_net = cn_dk_result.iloc[new_resolved_idx].get("adk_net_asset_exposure", {}) or {}
    assets = set(old_net) | set(new_net)
    return any(
        abs(float(new_net.get(asset, 0.0) or 0.0) - float(old_net.get(asset, 0.0) or 0.0)) > threshold
        for asset in assets
    )


def _adk_net_exposure_signal_text(cn_dk_result, old_idx, new_idx):
    if cn_dk_result is None or "adk_net_asset_exposure" not in cn_dk_result.columns:
        return "ADK净敞口字段不可用，无法按账户级净敞口判断变化"
    if _adk_net_exposure_changed(cn_dk_result, old_idx, new_idx):
        return "ADK净敞口有变化，按“ADK净敞口”表复核"
    return "ADK净敞口无变化"


def _write_v78_adk_current_holding_summary(w, cn_dk_result, idx):
    resolved_idx, date = _v78_resolve_display_idx_date(cn_dk_result, idx)
    if resolved_idx is None:
        return
    row = cn_dk_result.iloc[resolved_idx]
    holding = row.get("holding", row.get("v78_adk_v77_holding", "none_0"))
    top_pair = row.get("top_pair", "none")
    direction = int(row.get("direction", 0) or 0)
    exposure = float(row.get("weight", row.get("v78_adk_final_exposure", 0.0)) or 0.0)
    date_text = f"（对应 {pd.Timestamp(date).strftime('%Y-%m-%d')} 收盘确认）" if date is not None else ""
    title = "ADK当前已生效双腿持仓" if "v78_adk_v77_holding" in row.index else "ADK当前已生效持仓"
    w(f"**{title}:** **{_dk_pos_str(holding)}**{date_text}\n")
    if top_pair != "none":
        direction_text = f" | 方向 {direction:+d}" if direction != 0 else ""
        w(f"- 综合持仓标识: **{_dk_pair_display(top_pair)}**{direction_text}\n")
    if "v78_adk_v77_holding" in row.index:
        w(f"- V7.7 ADK原版: {_dk_pos_str(row.get('v78_adk_v77_holding', 'none_0'))}\n")
    if "v78_adk_new_holding" in row.index:
        w(f"- {V78_ADK_NEW_LABEL}: {_dk_pos_str(row.get('v78_adk_new_holding', 'none_0'))}\n")
    w(f"- 当前已生效总敞口: **{exposure:.2f}x**\n")


def _v78_row_for_display(df, idx, date=None):
    if df is None or len(df) == 0:
        return None
    if date is not None:
        try:
            date = pd.Timestamp(date)
            if date in df.index:
                return df.loc[date]
        except Exception:
            pass
    try:
        return df.iloc[idx]
    except Exception:
        return None

def _v78_resolve_display_idx_date(df, idx):
    if df is None or len(df) == 0:
        return None, None
    if isinstance(idx, (pd.Timestamp, datetime, np.datetime64, str)) or hasattr(idx, "year"):
        try:
            ts = pd.Timestamp(idx)
            if ts in df.index:
                return int(df.index.get_loc(ts)), ts
        except Exception:
            pass
    try:
        pos = int(idx)
        return pos, df.index[pos]
    except Exception:
        return None, None


def _v78_adk_pair_score(result_df, row, date):
    if row is None:
        return np.nan
    if "v78_score_overheat_score" in row.index:
        value = row.get("v78_score_overheat_score", np.nan)
        return float(value) if pd.notna(value) else np.nan
    signals_df = result_df.attrs.get("signals_df") if result_df is not None else None
    pair = row.get("top_pair", "none")
    if signals_df is None or pair == "none":
        return np.nan
    try:
        value = signals_df.loc[pd.Timestamp(date), pair]
    except Exception:
        return np.nan
    return float(value) if pd.notna(value) else np.nan


def _v78_adk_leg_status_rows(cn_dk_result, idx):
    resolved_idx, date = _v78_resolve_display_idx_date(cn_dk_result, idx)
    if resolved_idx is None:
        return []
    specs = [
        ("V7.7 ADK", "正式8配对", V78_ADK_V77_WEIGHT, cn_dk_result.attrs.get("v78_adk_v77"), False),
        (V78_ADK_NEW_LABEL, "全10配对 + score-hot", V78_ADK_NEW_PRIMARY_WEIGHT, cn_dk_result.attrs.get("v78_adk_new"), True),
    ]
    rows = []
    for label, scope, blend_weight, result_df, is_new in specs:
        row = _v78_row_for_display(result_df, resolved_idx, date)
        if row is None:
            continue
        pair = row.get("top_pair", "none")
        direction = int(row.get("direction", 0) or 0)
        weight = float(row.get("weight", 0.0) or 0.0)
        score_hot_on = bool(row.get("v78_score_overheat_on", False)) if is_new else False
        score_hot_scale = float(row.get("v78_score_overheat_scale", 1.0) or 0.0) if is_new else 1.0
        try:
            component_idx = int(result_df.index.get_loc(pd.Timestamp(date)))
        except Exception:
            component_idx = resolved_idx
        vol_scale = float(_dk_get_vol_scale(result_df, component_idx))
        raw_value = row.get("scale_raw", np.nan)
        realized_value = row.get("realized_vol", np.nan)
        vol_scale_raw = float(raw_value) if pd.notna(raw_value) else np.nan
        realized_vol = float(realized_value) if pd.notna(realized_value) else np.nan
        overlay_multiplier = weight / vol_scale if abs(vol_scale) > 1e-12 else 0.0
        rows.append({
            "leg": label,
            "scope": scope,
            "blend_weight": float(blend_weight),
            "pair": pair,
            "direction": direction,
            "position_text": _dk_pos_str(f"{pair}_{direction}") if pair != "none" else "none",
            "score": _v78_adk_pair_score(result_df, row, date),
            "score_hot_on": score_hot_on,
            "score_hot_scale": score_hot_scale,
            "realized_vol": realized_vol,
            "vol_scale_raw": vol_scale_raw,
            "vol_scale": vol_scale,
            "overlay_multiplier": overlay_multiplier,
            "leg_weight": weight,
            "leg_contribution": float(blend_weight) * weight,
        })
    return rows


def _write_v78_adk_leg_status_table(w, cn_dk_result, idx, position_col_label="分腿Top-1配对/方向"):
    rows = _v78_adk_leg_status_rows(cn_dk_result, idx)
    if not rows:
        return
    w("\n**V7.9 ADK 子策略状态**\n\n")
    w(f"| 腿 | 配对范围 | {position_col_label} | 排名分数 | 质量过滤 | 已实现波动率 | raw VolScale | 生效VolScale | overlay乘数 | 腿内最终敞口 | 组合贡献 |\n")
    w("|:-|:-|:-|------:|:-|------:|------:|------:|------:|------:|------:|\n")
    for row in rows:
        score = row["score"]
        score_text = f"`{score:.2f}`" if not np.isnan(score) else "`NA`"
        if row["leg"] == V78_ADK_NEW_LABEL:
            quality_text = "R²不启用"
        else:
            quality_text = f"R²质控≥{CN_DK_R2_QUALITY_THRESHOLD:.2f}" if CN_DK_R2_QUALITY_ENABLED else "R²质控关闭"
        realized_text = f"{row['realized_vol']:.1%}" if pd.notna(row["realized_vol"]) else "NA"
        raw_scale_text = f"{row['vol_scale_raw']:.2f}x" if pd.notna(row["vol_scale_raw"]) else "NA"
        overlay_text = f"{row['overlay_multiplier']:.2f}x"
        if row["leg"] == V78_ADK_NEW_LABEL:
            overlay_text += " (score-hot开启)" if row["score_hot_on"] else " (score-hot关闭)"
        w(
            f"| {row['leg']} | {row['scope']} | {row['position_text']} | {score_text} | "
            f"{quality_text} | {realized_text} | {raw_scale_text} | {row['vol_scale']:.2f}x | "
            f"{overlay_text} | {_fmt_v78_x(row['leg_weight'])} | {_fmt_v78_x(row['leg_contribution'])} |\n"
        )


def _v78_adk_leg_rank_sections(cn_dk_result, idx, use_shifted=False, top_n=3):
    specs = [
        ("V7.7 ADK", cn_dk_result.attrs.get("v78_adk_v77"), "正式8配对"),
        (V78_ADK_NEW_LABEL, cn_dk_result.attrs.get("v78_adk_new"), "全10配对 + score-hot"),
    ]
    sections = []
    for label, result_df, scope in specs:
        rows = _build_dk_rank_rows_at(result_df, idx=idx, use_shifted=use_shifted, top_n=top_n)
        if rows:
            sections.append({"leg": label, "scope": scope, "rows": rows})
    return sections


def _v78_adk_close_target_change_rows(cn_dk_result, idx=-1):
    """Compare during-day component holdings with targets from the current close."""
    resolved_idx, date = _v78_resolve_display_idx_date(cn_dk_result, idx)
    if resolved_idx is None:
        return []
    specs = [
        ("V7.7 ADK", cn_dk_result.attrs.get("v78_adk_v77")),
        (V78_ADK_NEW_LABEL, cn_dk_result.attrs.get("v78_adk_new")),
    ]
    rows = []
    for label, result_df in specs:
        current = _v78_row_for_display(result_df, resolved_idx, date)
        if current is None:
            continue
        try:
            component_idx = int(result_df.index.get_loc(pd.Timestamp(date)))
        except Exception:
            component_idx = resolved_idx
        targets = _build_dk_rank_rows_at(
            result_df,
            idx=component_idx,
            use_shifted=False,
            top_n=1,
        )
        current_pair = str(current.get("top_pair", "none") or "none")
        current_direction = int(current.get("direction", 0) or 0)
        if targets:
            target_pair = str(targets[0]["pair"])
            target_direction = int(targets[0]["direction"] or 0)
            target_text = targets[0]["position_text"]
        else:
            target_pair = current_pair
            target_direction = current_direction
            target_text = _dk_pos_str(f"{current_pair}_{current_direction}")
        current_text = _dk_pos_str(f"{current_pair}_{current_direction}")
        rows.append({
            "leg": label,
            "current_pair": current_pair,
            "current_direction": current_direction,
            "current_text": current_text,
            "target_pair": target_pair,
            "target_direction": target_direction,
            "target_text": target_text,
            "changed": (
                current_pair != target_pair
                or current_direction != target_direction
            ),
        })
    return rows


def _v78_adk_close_target_signal_text(change_rows):
    changed = [row for row in change_rows if row.get("changed")]
    if not changed:
        return "ADK本日收盘配对/方向目标无变化"
    details = "; ".join(
        f"{row['leg']}: {row['current_text']} -> {row['target_text']}"
        for row in changed
    )
    return f"ADK本日收盘配对/方向目标变化: {details}"


def _write_v78_adk_leg_rank_tables(w, cn_dk_result, idx, use_shifted=False):
    sections = _v78_adk_leg_rank_sections(cn_dk_result, idx, use_shifted=use_shifted, top_n=3)
    if not sections:
        return
    if use_shifted:
        score_label = "确认分数"
        rank_mark = " ← 当前该腿Top-1"
        timing = "当前已生效Top-3"
        hint = "当前已生效，用于查看每条腿当前正式持有；每条腿实际只持有Top-1"
    else:
        score_label = "实时分数"
        rank_mark = " ← 若现在收盘将执行"
        timing = "实时Top-3"
        hint = "若现在收盘，用于判断每条腿是否按收盘价执行；每条腿实际只持有Top-1"
    w(f"\n**V7.9 ADK 两个子策略Top-3（{hint}）:**\n")
    for section in sections:
        w(f"\n**{section['leg']}（{section['scope']}） {timing}**\n")
        for row in section["rows"]:
            score = row["score_used"] if use_shifted else row["score_live"]
            score_text = f"{score:.2f}" if not np.isnan(score) else "NA"
            mark = rank_mark if row["rank"] == 1 else ""
            w(
                f"- {row['rank']}. **{row['pair_display']}** | {score_label} `{score_text}` | "
                f"方向 {row['direction']:+d} | {row['position_text']}{mark}\n"
            )


def _write_v78_adk_new_leg_rank_table(w, cn_dk_result, idx, use_shifted=False):
    _write_v78_adk_leg_rank_tables(w, cn_dk_result, idx, use_shifted=use_shifted)


def _v78_adk_position_context_labels(position_context):
    if not position_context:
        return "当前双腿配对/方向", "分腿Top-1配对/方向"
    if str(position_context).startswith("若现在收盘"):
        return "若现在收盘双腿配对/方向", "若现在收盘分腿Top-1配对/方向"
    if "当前已生效" in str(position_context):
        return "当前已生效双腿配对/方向", "当前已生效分腿Top-1配对/方向"
    return f"{position_context}双腿配对/方向", f"{position_context}分腿Top-1配对/方向"


def _write_v78_adk_position_context_note(w, position_context):
    if not position_context:
        return
    w(f"\n**ADK持仓口径:** **{position_context}**")
    if "非当前正式持仓" in str(position_context) or str(position_context).startswith("若现在收盘"):
        w("；当前正式持仓以上方“当前已生效双腿持仓”和“账户级净敞口”表为准。")
    else:
        w("；下方表格展示当前正式持有的综合、分腿与账户级净敞口状态。")
    w("\n")


def _write_v78_adk_new_leg_then_summary(w, cn_dk_result, idx, use_shifted=False, position_context=None):
    is_close_target = (
        not use_shifted
        and position_context is not None
        and ("目标" in str(position_context) or str(position_context).startswith("若现在收盘"))
    )
    if is_close_target:
        w("\n**ADK收盘目标口径:** 下表仅用当日未移位分数判断各腿配对/方向目标；当前正式持仓与账户级净敞口仍以上方已生效表为准。\n")
        _write_v78_adk_leg_rank_tables(w, cn_dk_result, idx, use_shifted=False)
        return
    blend_col, status_col = _v78_adk_position_context_labels(position_context)
    _write_v78_adk_position_context_note(w, position_context)
    _write_v78_adk_blend_table(w, cn_dk_result, idx, position_col_label=blend_col)
    _write_v78_adk_net_exposure_table(w, cn_dk_result, idx)
    _write_v78_adk_leg_status_table(w, cn_dk_result, idx, position_col_label=status_col)
    _write_v78_adk_leg_rank_tables(w, cn_dk_result, idx, use_shifted=use_shifted)


def _v78_subb_four_leg_weight_rows(us_rot_result, idx, min_weight=0.0005):
    if us_rot_result is None or len(us_rot_result) == 0:
        return []
    idx, date = _v78_resolve_display_idx_date(us_rot_result, idx)
    if idx is None:
        return []
    row = us_rot_result.iloc[idx]
    v77 = us_rot_result.attrs.get("v78_subb_v77")
    bias = us_rot_result.attrs.get("v78_subb_bias")
    logvol = us_rot_result.attrs.get("v78_subb_logvol")
    v77_row = _v78_row_for_display(v77, idx, date)
    bias_row = _v78_row_for_display(bias, idx, date)
    logvol_row = _v78_row_for_display(logvol, idx, date)
    assets = set()
    for source_row in (row, v77_row, bias_row, logvol_row):
        if source_row is None:
            continue
        for col in source_row.index:
            if not isinstance(col, str):
                continue
            for prefix in ("w_", "official_w_", "official_contrib_w_", "ema_w_", "ema_contrib_w_"):
                if col.startswith(prefix):
                    assets.add(col[len(prefix):])
    rows = []
    for asset in sorted(assets):
        official_raw = float(v77_row.get(f"official_w_{asset}", 0.0) or 0.0) if v77_row is not None else 0.0
        ema_raw = float(v77_row.get(f"ema_w_{asset}", 0.0) or 0.0) if v77_row is not None else 0.0
        official_inner = (
            float(v77_row.get(f"official_contrib_w_{asset}", SUBB_V75_OFFICIAL_WEIGHT * official_raw) or 0.0)
            if v77_row is not None else 0.0
        )
        ema_inner = (
            float(v77_row.get(f"ema_contrib_w_{asset}", SUBB_V75_EMA_WEIGHT * ema_raw) or 0.0)
            if v77_row is not None else 0.0
        )
        official_contrib = V78_SUBB_V77_WEIGHT * official_inner
        ema_contrib = V78_SUBB_V77_WEIGHT * ema_inner
        bias_w = float(bias_row.get(f"target_w_{asset}", bias_row.get(f"w_{asset}", 0.0)) or 0.0) if bias_row is not None else 0.0
        logvol_w = float(logvol_row.get(f"target_w_{asset}", logvol_row.get(f"w_{asset}", 0.0)) or 0.0) if logvol_row is not None else 0.0
        bias_contrib = V78_SUBB_NEW_BIAS_WEIGHT * bias_w
        logvol_contrib = V78_SUBB_NEW_LOGVOL_WEIGHT * logvol_w
        final_weight = float(row.get(f"target_w_{asset}", official_contrib + ema_contrib + bias_contrib + logvol_contrib) or 0.0)
        if max(abs(official_contrib), abs(ema_contrib), abs(bias_contrib), abs(logvol_contrib), abs(final_weight)) < min_weight:
            continue
        rows.append({
            "asset": asset,
            "live_name": _ROT_PROXY_TO_LIVE.get(asset, asset),
            "official_contrib": official_contrib,
            "ema_contrib": ema_contrib,
            "bias_contrib": bias_contrib,
            "logvol_contrib": logvol_contrib,
            "final_weight": final_weight,
        })
    rows.sort(key=lambda item: item["final_weight"], reverse=True)
    return rows


def _v78_subb_component_leg_rows(us_rot_result, idx, include_official=True, min_weight=0.0005):
    if us_rot_result is None or len(us_rot_result) == 0:
        return []
    idx, date = _v78_resolve_display_idx_date(us_rot_result, idx)
    if idx is None:
        return []
    v77 = us_rot_result.attrs.get("v78_subb_v77")
    bias = us_rot_result.attrs.get("v78_subb_bias")
    logvol = us_rot_result.attrs.get("v78_subb_logvol")
    v77_row = _v78_row_for_display(v77, idx, date)
    bias_row = _v78_row_for_display(bias, idx, date)
    logvol_row = _v78_row_for_display(logvol, idx, date)
    assets = set()
    for source_row in (v77_row, bias_row, logvol_row):
        if source_row is None:
            continue
        for col in source_row.index:
            if not isinstance(col, str):
                continue
            for prefix in ("official_w_", "official_contrib_w_", "ema_w_", "ema_contrib_w_", "target_w_", "w_"):
                if col.startswith(prefix):
                    assets.add(col[len(prefix):])
    leg_specs = []
    if include_official:
        leg_specs.append(("官方腿", V78_SUBB_V77_WEIGHT * SUBB_V75_OFFICIAL_WEIGHT))
    leg_specs.extend([
        ("EMA腿", V78_SUBB_V77_WEIGHT * SUBB_V75_EMA_WEIGHT),
        ("Bias腿", V78_SUBB_NEW_BIAS_WEIGHT),
        ("LogVol腿", V78_SUBB_NEW_LOGVOL_WEIGHT),
    ])
    rows = []
    for leg, blend_weight in leg_specs:
        for asset in sorted(assets):
            if leg == "官方腿":
                raw_weight = float(v77_row.get(f"official_w_{asset}", 0.0) or 0.0) if v77_row is not None else 0.0
                contrib = (
                    V78_SUBB_V77_WEIGHT
                    * float(v77_row.get(f"official_contrib_w_{asset}", SUBB_V75_OFFICIAL_WEIGHT * raw_weight) or 0.0)
                    if v77_row is not None else 0.0
                )
            elif leg == "EMA腿":
                raw_weight = float(v77_row.get(f"ema_w_{asset}", 0.0) or 0.0) if v77_row is not None else 0.0
                contrib = (
                    V78_SUBB_V77_WEIGHT
                    * float(v77_row.get(f"ema_contrib_w_{asset}", SUBB_V75_EMA_WEIGHT * raw_weight) or 0.0)
                    if v77_row is not None else 0.0
                )
            elif leg == "Bias腿":
                raw_weight = float(bias_row.get(f"target_w_{asset}", bias_row.get(f"w_{asset}", 0.0)) or 0.0) if bias_row is not None else 0.0
                contrib = V78_SUBB_NEW_BIAS_WEIGHT * raw_weight
            else:
                raw_weight = float(logvol_row.get(f"target_w_{asset}", logvol_row.get(f"w_{asset}", 0.0)) or 0.0) if logvol_row is not None else 0.0
                contrib = V78_SUBB_NEW_LOGVOL_WEIGHT * raw_weight
            if max(abs(raw_weight), abs(contrib)) < min_weight:
                continue
            rows.append({
                "leg": leg,
                "blend_weight": blend_weight,
                "asset": asset,
                "live_name": _ROT_PROXY_TO_LIVE.get(asset, asset),
                "leg_weight": raw_weight,
                "contribution": contrib,
            })
    rows.sort(key=lambda item: (item["leg"], -abs(item["contribution"]), item["asset"]))
    return rows


def _write_v78_subb_component_leg_tables(w, us_rot_result, idx, include_official=True):
    rows = _v78_subb_component_leg_rows(us_rot_result, idx, include_official=include_official)
    if not rows:
        return
    w("\n**V7.9 Sub-B 子策略腿状态（腿内目标 -> 组合贡献）**\n\n")
    for leg in ["官方腿", "EMA腿", "Bias腿", "LogVol腿"]:
        leg_rows = [row for row in rows if row["leg"] == leg]
        if not leg_rows:
            continue
        blend_weight = leg_rows[0]["blend_weight"]
        w(f"**{leg}（{blend_weight:.0%}）**\n\n")
        w("| ETF | 腿内目标权重 | 组合贡献 |\n|:-|------:|------:|\n")
        for row in leg_rows:
            w(f"| {row['live_name']} | {row['leg_weight']:.1%} | {row['contribution']:.1%} |\n")
        w("\n")


def _write_v78_subb_blend_table(w, us_rot_result, idx):
    if "v78_subb_v77_return" not in us_rot_result.columns:
        return
    rows = _v78_subb_four_leg_weight_rows(us_rot_result, idx)
    w("\n**V7.9 Sub-B 四腿拆分与综合目标**（官方腿25% + EMA腿25% + Bias腿25% + LogVol腿25%）\n\n")
    if rows:
        w("| ETF | 官方腿贡献 | EMA腿贡献 | Bias腿贡献 | LogVol腿贡献 | V7.9综合目标 |\n")
        w("|:-|------:|------:|------:|------:|------:|\n")
        for row in rows:
            w(
                f"| {row['live_name']} | {row['official_contrib']:.1%} | {row['ema_contrib']:.1%} | "
                f"{row['bias_contrib']:.1%} | {row['logvol_contrib']:.1%} | **{row['final_weight']:.1%}** |\n"
            )
    return


def _v78_subb_volume_warning(us_rot_result):
    if us_rot_result is None:
        return ""
    labels = {
        "v78_subb_bias": "Bias",
        "v78_subb_logvol": "LogVol",
    }
    failed = []
    for key, label in labels.items():
        comp = us_rot_result.attrs.get(key)
        if comp is None or len(comp) == 0 or "volume_source" not in comp.columns:
            continue
        src = str(comp.iloc[-1].get("volume_source", "") or "")
        if src.startswith("unavailable:") or "unresolved SPY volume" in src:
            failed.append(label)
    if not failed:
        return ""
    mode = str(globals().get("V78_SUBB_SPY_VOLUME_FAIL_MODE", "warn_open") or "warn_open").lower()
    if mode == "fail_closed":
        return f"⚠️ SPY volume unavailable，{', '.join(failed)} volume gate 已按 fail-closed 保守降权。"
    if mode == "raise":
        return f"⚠️ SPY volume unavailable，{', '.join(failed)} volume gate 配置为 raise，应中止本次信号。"
    return f"⚠️ SPY volume unavailable，{', '.join(failed)} volume gate 本次未执行（fail-open：本次未降权）。"


def _v78_subb_current_vs_hypothetical_rows(
    us_rot_result,
    idx,
    min_weight=0.0005,
    current_weights=None,
    target_weights=None,
):
    if us_rot_result is None or len(us_rot_result) == 0:
        return []
    idx, _date = _v78_resolve_display_idx_date(us_rot_result, idx)
    if idx is None:
        return []
    row = us_rot_result.iloc[idx]
    assets = set(_weight_columns_assets(us_rot_result, prefixes=("actual_w_", "target_w_", "w_")))
    if current_weights is not None:
        assets.update(current_weights.keys())
    if target_weights is not None:
        assets.update(target_weights.keys())
    assets = sorted(assets)
    rows = []
    for asset in assets:
        if current_weights is not None:
            current = current_weights.get(asset, 0.0)
        else:
            current = row.get(f"actual_w_{asset}", row.get(f"w_{asset}", 0.0))
        if target_weights is not None:
            target = target_weights.get(asset, 0.0)
        else:
            target = row.get(f"target_w_{asset}", current)
        current = float(current) if pd.notna(current) else 0.0
        target = float(target) if pd.notna(target) else 0.0
        diff = target - current
        if max(abs(current), abs(target), abs(diff)) < min_weight:
            continue
        rows.append({
            "asset": asset,
            "live_name": _ROT_PROXY_TO_LIVE.get(asset, asset),
            "current_weight": current,
            "hypothetical_target": target,
            "diff": diff,
        })
    rows.sort(key=lambda item: max(abs(item["current_weight"]), abs(item["hypothetical_target"])), reverse=True)
    return rows


def _write_v78_subb_current_vs_hypothetical_table(
    w,
    us_rot_result,
    idx,
    min_weight=0.0005,
    current_weights=None,
    target_weights=None,
):
    rows = _v78_subb_current_vs_hypothetical_rows(
        us_rot_result,
        idx,
        min_weight=min_weight,
        current_weights=current_weights,
        target_weights=target_weights,
    )
    if not rows:
        return
    w("\n**V7.9 Sub-B 当前持有 vs 假设今日调仓**\n\n")
    w("| ETF | 当前持有 | 假设今日调仓目标 | 假设调仓差异 |\n")
    w("|:-|------:|------:|------:|\n")
    for row in rows:
        diff = row["diff"]
        diff_text = f"{diff:+.1%}" if abs(diff) >= 0.0005 else "—"
        w(
            f"| {row['live_name']} | {row['current_weight']:.1%} | "
            f"**{row['hypothetical_target']:.1%}** | {diff_text} |\n"
        )
    turnover = sum(abs(row["diff"]) for row in rows if row["asset"] not in ("BIL", "CASH"))
    w(f"\n假设今日是Sub-B调仓日，按上表目标执行；单边调整合计约 **{turnover:.1%}**。非信号日仅作参考，不生成正式调仓指令。\n")


def _subb_guard_pct_text(value, signed=False):
    if pd.isna(value):
        return "N/A"
    try:
        value = float(value)
    except Exception:
        return "N/A"
    return f"{value:+.2%}" if signed else f"{value:.2%}"


def _write_subb_dbc_profit_guard_status(w, us_rot_result, idx=-1):
    if (
        not SUBB_DBC_PROFIT_GUARD_ENABLED
        or us_rot_result is None
        or len(us_rot_result) == 0
        or "dbc_profit_guard_next_scale" not in us_rot_result.columns
    ):
        return
    try:
        row = us_rot_result.loc[idx] if idx in us_rot_result.index else us_rot_result.iloc[idx]
    except Exception:
        return
    asset = SUBB_DBC_PROFIT_GUARD_ASSET
    cash_asset = SUBB_DBC_PROFIT_GUARD_CASH_ASSET
    profit = row.get("dbc_profit_guard_profit", np.nan)
    peak = row.get("dbc_profit_guard_peak_profit", np.nan)
    retain = row.get("dbc_profit_guard_retain_ratio", np.nan)
    today_scale = _subb_row_float(row, "dbc_profit_guard_scale_today", 1.0)
    next_scale = _subb_row_float(row, "dbc_profit_guard_next_scale", today_scale)
    raw_weight = float(row.get(f"pre_dbc_profit_guard_w_{asset}", row.get(f"w_{asset}", 0.0)) or 0.0)
    final_weight = float(row.get(f"w_{asset}", 0.0) or 0.0)
    target_weight = float(row.get(f"target_w_{asset}", final_weight) or 0.0)
    target_shift = float(row.get("dbc_profit_guard_target_removed_weight", 0.0) or 0.0)
    action = str(row.get("dbc_profit_guard_action", "") or "")
    if action:
        action_text = f" | action {action}"
    elif next_scale < 1.0 - 1e-9:
        action_text = " | action guard_on"
    else:
        action_text = " | action normal"
    w(
        f"**DBC/PDBC profit guard:** {_subb_dbc_profit_guard_rule_text()}; "
        f"profit {_subb_guard_pct_text(profit, signed=True)}, peak {_subb_guard_pct_text(peak, signed=True)}, "
        f"retain {_subb_guard_pct_text(retain)}; raw {raw_weight:.1%}, today scale {today_scale:.2f}, "
        f"next scale {next_scale:.2f}, final {final_weight:.1%}, target {target_weight:.1%}, "
        f"{cash_asset} shift {target_shift:.1%}{action_text}\n"
    )


def _subb_row_float(row, key, default=0.0):
    try:
        value = row.get(key, default)
        if pd.isna(value):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _write_v78_subb_param_tables(w):
    n_etfs = len(US_ROT_ASSETS)
    etf_labels = [f"{k}({v['label']})" for k, v in US_ROT_ASSETS.items()]
    w("**全局执行口径**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w(f"| 四腿混合 | **官方腿25% / EMA腿25% / Bias腿25% / LogVol腿25%** | 四腿分别计算目标，再汇总为V7.9综合执行目标 |\n")
    w(f"| 混合后波动口径 | **不二次归一** | {SUBB_BLEND_VOL_NOTE} |\n")
    w("| V7.9 NAV成本口径 | **component-net** | V7.7 official+EMA account-level blend is pre-netted before entering V7.9 as the 50% V7.7 component; Bias/LogVol are separately netted V7.9 components. Displayed aggregate target is for execution review and may have lower account-level net turnover. |\n")
    w(f"| SPY量能取数失败 | **{V78_SUBB_SPY_VOLUME_FAIL_MODE}** | fail_closed means Bias/LogVol conservatively derisk {_subb_volreg_scaled_assets_text()} by 0.75 if SPY volume is unavailable; local runs without Yahoo access may be more defensive than Poe/live runs. |\n")
    w(f"| 最小调仓幅度 | **{US_ROT_MIN_TURNOVER:.0%}** | 低于阈值不调 |\n")
    w(f"| 调仓保护 | **{US_ROT_REBALANCE_THRESHOLD}x** | 逐窗口挑战者保护；新资产需超过最弱在位者{US_ROT_REBALANCE_THRESHOLD:.2f}x才允许替换 |\n")
    w(f"| 可加杠杆ETF | **QQQM/GLDM** | US_ROT_FUTURES={sorted(US_ROT_FUTURES)}；只放大自己那一份，不承接其他ETF杠杆缺口 |\n")
    w(f"| 目标年化波动率/最大杠杆 | **{US_ROT_TARGET_VOL:.0%} / {US_ROT_MAX_LEV:.1f}x** | 各腿按自己的波动率口径计算scale |\n")
    w(f"| 交易成本 | **{US_ROT_COMMISSION:.1%}** | 单边手续费 |\n")
    w(f"| 信号频率 | **周度** | 每周最后一个交易日(≤周四) |\n")
    if SUBB_DBC_PROFIT_GUARD_ENABLED:
        w(f"| DBC/PDBC profit guard | **on** | {_subb_dbc_profit_guard_rule_text()} |\n")
    if US_ROT_VOLREG_ENABLED:
        w(f"| VolReg风险过热 | **开启** | {_subb_volreg_rule_text()}；{US_ROT_VOLREG_BACKTEST_NOTE} |\n")

    w("\n**官方腿参数**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w("| 排名池 | **7ETF+通胀宏观3ETF** | 沿用官方生产逻辑；DBMF/KMLM只在通胀开关ON时进入候选池 |\n")
    w(f"| 动量窗口 | **{_subb_window_label_for_display(' / ')}日** | 三个窗口分别生成目标仓位后按{US_ROT_WINDOW_WEIGHT_LABEL}加权平均 |\n")
    w(f"| 波动率窗口(权重) | **{US_ROT_VOL_LB}日** | 各窗口内使用反波动率加权 |\n")
    w(f"| 波动率缩放 | **{US_ROT_VOL_WINDOW}日rolling** | Model B 目标波动率scale |\n")
    w(f"| Top N / 绝对动量 | **{US_ROT_TOP_N} / >{US_ROT_ABS_THRESHOLD:.0%}** | 动量需超过阈值才持有，否则转BIL |\n")

    w("\n**EMA腿参数**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w(f"| 排名池 | **US_ROT_POOL全池** | {_v78_subb_inflation_participation_note()} |\n")
    w(f"| EMA半衰期 / 阈值 | **hl{SUBB_V75_EMA_HALF_LIFE} / {SUBB_V75_EMA_ABS_THRESHOLD:.0%}** | 使用年化EWM日收益 |\n")
    w(f"| EMA腿VolScale | **{SUBB_V75_EMA_VOL_MODE}** | 目标波动率scale用6个月EWMA已实现波动率，半衰期{SUBB_V75_EMA_VOL_HALFLIFE_DAYS}日 |\n")
    w(f"| 波动率窗口(权重) | **{US_ROT_VOL_LB}日rolling** | 资产反波动率权重仍用rolling口径 |\n")
    w(f"| target-vol / 最大杠杆 | **{US_ROT_TARGET_VOL:.0%} / {US_ROT_MAX_LEV:.1f}x** | 本腿独立scale；低波动只放大QQQM/GLDM自身权重 |\n")

    w("\n**Bias腿参数**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w("| 排名池 | **US_ROT_POOL全池** | 不受通胀开关裁剪；DBMF/KMLM始终参与排名 |\n")
    w("| score口径 | **price/MA160,260,390 = 3/2/1加权** | 按price/MA(lb)-1排名；不是官方腿动量窗口 |\n")
    w("| target-vol / 窗口 / 最大杠杆 | **25% / 40日 / max1.5x** | 本腿独立scale；低波动只放大QQQM/GLDM自身权重 |\n")
    w(f"| 成交量过滤 | **SPY量/MA60≥1.5 -> {_subb_volreg_scaled_assets_text()} ×0.75** | 差额转BIL；只作用于本腿，不改其他腿 |\n")

    w("\n**LogVol腿参数**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w("| 排名池 | **US_ROT_POOL全池** | 不受通胀开关裁剪；DBMF/KMLM始终参与排名 |\n")
    w("| score口径 | **log return 120/200/320 = 60%/30%/10%** | 独立于官方腿160/260/390窗口 |\n")
    w("| target-vol / 窗口 / 最大杠杆 | **30% / 40日 / max1.25x** | 本腿独立scale；低波动只放大QQQM/GLDM自身权重 |\n")
    w(f"| 成交量过滤 | **SPY量/MA60≥1.5 -> {_subb_volreg_scaled_assets_text()} ×0.75** | 差额转BIL；只作用于本腿，不改其他腿 |\n")
    w(f"| vol-hot仓位降档 | **rv≥50% -> {_subb_volreg_scaled_assets_text()}目标仓位×0.75** | 仅LogVol腿；仅在信号日作用于下一期目标仓位，不做每日强制降仓；差额转BIL，并同步进入target/actual/turnover/cost |\n")
    w(f"\n资产池: **{n_etfs}只** | {', '.join(etf_labels)}\n")


def _write_v78_suba_param_tables(w):
    all_names = [CN_NAMES.get(c, c) for c in CN_EQUITY_CODES + [CN_BOND_CODE]]
    w("**全局执行口径**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w(f"| V7.9混合 | **V7.7A {V78_SUBA_V77_WEIGHT:.0%} / New A TV1.0 {V78_SUBA_NEW_TV10_WEIGHT:.0%}** | 两条腿分别生成目标，再汇总为Sub-A执行目标 |\n")
    w(f"| 信号频率 | **日频** | 每个交易日检查信号 |\n")
    w(f"| 交易成本 | **{CN_COMMISSION:.1%}** | 单边手续费 |\n")
    w(f"| 无风险利率 | **3%/年** | Cash日收益 = (1.03^(1/244))-1 |\n")
    w(f"| 资产池 | **{len(CN_EQUITY_CODES)+1}只** | {', '.join(all_names)} |\n")

    w("\n**V7.7A原版参数**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w(f"| 均线周期 | **{CN_BIAS_N}日** | price/MA{CN_BIAS_N}计算乖离率 |\n")
    w(f"| 斜率拟合窗口 | **{CN_MOM_DAY}日** | 乖离率归一化后线性拟合 |\n")
    w(f"| 动量时间加权 | **1.0 → {CN_BIAS_MOM_WEIGHT_END:.1f}** | 最近日权重更高；v7.7正式信号使用linear_recent_3x |\n")
    w(f"| 绝对动量过滤 | **{CN_ABS_MOM_DAY}日 > {CN_ABS_MOM_THRESHOLD:.0%}** | 候选资产近{CN_ABS_MOM_DAY}日实际涨跌幅需高于阈值，否则持现金 |\n")
    w(f"| R²滚动窗口/门槛 | **{CN_R2_WINDOW}日 / {CN_R2_THRESHOLD}** | 所有资产(含国债)需R²≥门槛才持有 |\n")
    w(f"| 持仓切换Buffer | **{CN_SWITCH_BUFFER:.2f}x** | 当前持仓仍合格时，新候选score需超过当前持仓{CN_SWITCH_BUFFER:.2f}x才切换 |\n")

    w("\n**New A TV1.0参数**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w(f"| MA/动量窗口 | **MA{V78_SUBA_NEW_MA} / {V78_SUBA_NEW_MOM_DAY}日** | New A score排名口径 |\n")
    w(f"| score阈值 | **>{V78_SUBA_NEW_SCORE_THRESHOLD:.4f}** | score未通过则排除 |\n")
    w(f"| 绝对动量过滤 | **abs{V78_SUBA_NEW_ABS_DAY}>{V78_SUBA_NEW_ABS_THRESHOLD:.0%}** | 绝对动量未通过则排除 |\n")
    w(f"| 目标波动率/窗口/上限 | **{V78_SUBA_NEW_TARGET_VOL:.0%} / {V78_SUBA_NEW_VOL_WINDOW}日 / {V78_SUBA_NEW_MAX_LEV:.1f}x** | New A腿独立target-vol |\n")
    w("| 成交额风控 | **启用时参与NewA目标权重** | V7.7A使用原Sub-A overlay；NewA使用专用volume overlay，按NewA状态机重建收益和成本 |\n")

    w("\n**Sub-A风控与执行参数**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w(f"| 波动率缩放目标/窗口 | **{CN_TARGET_VOL:.0%} / {CN_VOL_WINDOW}日** | 用策略收益率计算已实现波动率 |\n")
    w(f"| 最大/最小杠杆 | **{CN_MAX_LEV:.1f}x / {CN_MIN_LEV:.1f}x** | VolScale上下限 |\n")
    w(f"| Scale调整阈值 | **Δ≥{CN_SCALE_THRESHOLD:.2f}** | |Δscale|≥阈值才实际调整 |\n")
    w(f"| 建仓首笔比例 | **{CN_ENTRY_INITIAL_FRACTION:.0%}** | 从现金入场时先买入的目标仓位比例 |\n")
    w(f"| 补仓等待天数 | **{'等回调' if CN_ENTRY_WAIT_DAYS is None else str(CN_ENTRY_WAIT_DAYS) + '日'}** | None=不设天数上限，只在下跌日补足剩余仓位 |\n")
    w(f"| Cash Overlay | **{'启用' if CN_SA_CASH_OVERLAY_ENABLED else '关闭'}** | 触发/恢复 {CN_SA_CASH_OVERLAY_DECAY_RATIO:.0%}/{CN_SA_CASH_OVERLAY_RECOVERY_RATIO:.0%} |\n")
    w(f"| V7.7A MA60过热止盈 | **{'启用' if CN_SA_SAME_SIDE_OVERHEAT_ENABLED else '关闭'}** | 仅作用于V7.7A腿；触发/恢复 {CN_SA_SAME_SIDE_OVERHEAT_ENTER:.0%}/{CN_SA_SAME_SIDE_OVERHEAT_EXIT:.0%}，触发后{CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE:.2f}x |\n")
    w(f"| Sub-A成交额风控 | **{'启用' if CN_SA_VOLUME_OVERLAY_ENABLED else '关闭'}** | ZZ2000 MA{CN_SA_VOLUME_ZZ2000_MA}/{CN_SA_VOLUME_ZZ2000_DAYS}天 OR CYB MA{CN_SA_VOLUME_CYB_MA}/{CN_SA_VOLUME_CYB_DAYS}天，触发后{CN_SA_VOLUME_SCALE:.0%} |\n")


def _write_v78_adk_param_tables(w):
    w("**全局执行口径**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w(f"| V7.9混合 | **V7.7 ADK {V78_ADK_V77_WEIGHT:.0%} / New ADK {V78_ADK_NEW_PRIMARY_WEIGHT:.0%}** | 两条ADK腿分别选Top-1，再汇总为ADK执行敞口 |\n")
    w("| 指数池 | **5指数** | 上证50, 沪深300, 中证500, 中证1000, 创业板 |\n")
    w(f"| 年化交易日 | **{CN_DK_TRADING_DAYS}日** | 波动率年化基数 |\n")
    w(f"| 交易成本 | **{CN_DK_COMMISSION:.3%}** | DK单边成本；翻转=4笔单边 |\n")

    w("\n**V7.7 ADK参数**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w(f"| 配对池 | **正式{len(ADK_OFFICIAL_PAIR_ORDER)}对** | {'、'.join(_dk_pair_display(p) for p in ADK_OFFICIAL_PAIR_ORDER)} |\n")
    w(f"| 均线周期/斜率窗口 | **MA{CN_DK_BIAS_N} / {CN_DK_MOM_DAY}日** | 每对计算乖离动量，从正式池选|乖离动量|最大的Top-1 |\n")
    w(f"| R²质量门槛 | **{'启用' if CN_DK_R2_QUALITY_ENABLED else '关闭'}** | 低于门槛的ADK配对不参与Top-1排名 |\n")
    if CN_DK_R2_QUALITY_ENABLED:
        w(f"| R²最低值 | **{CN_DK_R2_QUALITY_THRESHOLD:.2f}** | 仅过滤排名分数，方向仍来自原60/20乖离动量 |\n")
    w(f"| Score衰减 | **{'启用' if CN_DK_PAIR_SCORE_DECAY_ENABLED else '关闭'}** | 7.7 ADK默认不使用pair score峰值衰减阈值 |\n")

    w("\n**New ADK all10 score-hot参数**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w("| 配对池 | **全10对** | 5指数两两组合全池参与排名 |\n")
    w("| R²质量门槛 | **不启用** | New ADK不做R²过滤 |\n")
    w("| score-hot | **80 / 20 / 0** | score过热时降低New ADK腿内敞口 |\n")

    w("\n**ADK风控与执行参数**\n\n")
    w("| 参数 | 值 | 说明 |\n|:-|:-|:-|\n")
    w(f"| 波动率缩放目标/窗口 | **{CN_DK_TARGET_VOL:.0%} / {CN_DK_VOL_WINDOW}日** | 用spread收益率计算已实现波动率 |\n")
    w(f"| 最大/最小杠杆 | **{CN_DK_MAX_LEV:.1f}x / {CN_DK_MIN_LEV:.1f}x** | VolScale上下限 |\n")
    w(f"| Scale调整阈值 | **Δ≥{CN_DK_SCALE_THRESHOLD:.2f}** | |Δscale|≥阈值才实际调整 |\n")
    w(f"| 同向过热防守 | **{'启用' if CN_DK_SAME_SIDE_OVERHEAT_ENABLED else '关闭'}** | 触发/恢复 {CN_DK_SAME_SIDE_OVERHEAT_ENTER:.0%}/{CN_DK_SAME_SIDE_OVERHEAT_EXIT:.0%}，触发后{CN_DK_SAME_SIDE_OVERHEAT_DERISK_SCALE:.2f}x |\n")
    w(f"| ADK成交额风险警示 | **仅提示** | {CN_DK_VOLUME_YELLOW_LABEL}成交额连续低于MA{CN_DK_VOLUME_YELLOW_MA}满{CN_DK_VOLUME_YELLOW_DAYS}天时只进警示板，不改仓位 |\n")
    w(f"| DD RiskGate | **{'启用' if CN_DK_RISK_GATE_ENABLED else '关闭'}** | 触发/恢复 <=-{CN_DK_RISK_GATE_ENTER:.0%} / >=-{CN_DK_RISK_GATE_EXIT:.0%}，防守仓位{CN_DK_RISK_GATE_DEFENSE_SCALE:.0%} |\n")
    w("| RiskGate DD口径 | **risk_gate_base_dd** | 基于gate前执行成本净值判断，不是最终NAV回撤 |\n")


def _us_threshold_check(available_scores, prev_w, threshold):
    """Compare pure top-N vs threshold-filtered selection for display only."""
    if threshold <= 1.0:
        return None
    top_n = US_ROT_TOP_N
    prev_risky = {a for a, w in prev_w.items() if a != "BIL" and w > 0.001}
    if not prev_risky:
        return None
    sorted_scores = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
    pure_top = set(a for a, _ in sorted_scores[:top_n])
    # Threshold-filtered selection: keep previous holdings, fill gaps, then challenge
    selected = set()
    for a in prev_risky:
        if a in available_scores:
            selected.add(a)
    if len(selected) < top_n:
        for a, _ in sorted_scores:
            if a not in selected:
                selected.add(a)
            if len(selected) >= top_n:
                break
    if len(selected) > top_n:
        selected = set(
            a for a, _ in sorted(
                [(a, available_scores[a]) for a in selected],
                key=lambda x: x[1], reverse=True
            )[:top_n]
        )
    blocked_info = []
    non_selected = sorted(
        [(a, s) for a, s in available_scores.items() if a not in selected],
        key=lambda x: x[1], reverse=True
    )
    for challenger, ch_score in non_selected:
        if not selected:
            break
        weakest = min(selected, key=lambda a: available_scores[a])
        w_score = available_scores[weakest]
        if ch_score <= w_score:
            break
        if w_score <= 0:
            selected.remove(weakest)
            selected.add(challenger)
        elif ch_score > w_score * threshold:
            selected.remove(weakest)
            selected.add(challenger)
        else:
            ratio = ch_score / w_score if w_score != 0 else float('inf')
            blocked_info.append((challenger, weakest, ratio, ch_score, w_score))
    if selected == pure_top:
        return f"✅ Top{US_ROT_TOP_N}一致，阈值不影响选择"
    parts = []
    for ch, wk, ratio, ch_s, wk_s in blocked_info:
        ch_name = _ROT_PROXY_TO_LIVE.get(ch, ch)
        wk_name = _ROT_PROXY_TO_LIVE.get(wk, wk)
        parts.append(f"{ch_name}({ch_s:+.1%}) vs {wk_name}({wk_s:+.1%}) = {ratio:.2f}x < {threshold}x → {wk_name}被保护")
    if parts:
        return "⚠️ " + "; ".join(parts)
    kept = selected - pure_top
    dropped = pure_top - selected
    kept_names = ", ".join(_ROT_PROXY_TO_LIVE.get(a, a) for a in sorted(kept))
    dropped_names = ", ".join(_ROT_PROXY_TO_LIVE.get(a, a) for a in sorted(dropped))
    return f"⚠️ 保留 {kept_names}，不换入 {dropped_names}"

def _us_mix_threshold_check(momentum_rows, vol_row, ranking_codes, prev_risky_by_lb, threshold):
    if threshold <= 1.0 or not prev_risky_by_lb:
        return None
    parts = []
    for lb in US_ROT_LBS:
        prev_risky = prev_risky_by_lb.get(lb)
        if not prev_risky:
            continue
        mom_row = momentum_rows.get(lb)
        if mom_row is None:
            continue
        selected_raw = _us_raw_weights(
            mom_row,
            vol_row,
            ranking_codes,
            top_n=US_ROT_TOP_N,
            abs_threshold=US_ROT_ABS_THRESHOLD,
            prev_risky=prev_risky,
            threshold=threshold,
        )
        pure_raw = _us_raw_weights(
            mom_row,
            vol_row,
            ranking_codes,
            top_n=US_ROT_TOP_N,
            abs_threshold=US_ROT_ABS_THRESHOLD,
            prev_risky=None,
            threshold=1.0,
        )
        selected = _us_selected_risky_from_raw(selected_raw)
        pure_selected = _us_selected_risky_from_raw(pure_raw)
        if selected == pure_selected:
            continue
        kept = selected - pure_selected
        skipped = pure_selected - selected
        kept_names = ", ".join(_ROT_PROXY_TO_LIVE.get(a, a) for a in sorted(kept)) or "-"
        skipped_names = ", ".join(_ROT_PROXY_TO_LIVE.get(a, a) for a in sorted(skipped)) or "-"
        parts.append(f"{lb}d: threshold result kept {kept_names}; skipped {skipped_names}")
    if not parts:
        return None
    return " | ".join(parts)

def _us_weighted_return(weights, prev_prices, curr_prices):
    pr = 0.0
    for a, w in weights.items():
        prev_px = prev_prices.get(a, np.nan)
        curr_px = curr_prices.get(a, np.nan)
        if pd.isna(prev_px) or pd.isna(curr_px) or prev_px == 0:
            continue
        pr += w * (curr_px / prev_px - 1)
    return pr

def _active_weight_assets(*weight_dicts, min_abs=1e-12):
    assets = set()
    for weights in weight_dicts:
        for asset, raw_weight in (weights or {}).items():
            try:
                weight = float(raw_weight or 0.0)
            except Exception:
                weight = 0.0
            if abs(weight) > min_abs:
                assets.add(asset)
    return sorted(assets)


def _us_open_row(date, assets, us_open, close_df, *, strict=False, context="US open execution"):
    prices = {}
    missing = []
    fallback_assets = []
    for a in assets:
        px = np.nan
        if us_open is not None and a in us_open:
            s = us_open[a]
            if date in s.index:
                px = s.loc[date]
        if pd.isna(px):
            if strict:
                missing.append(a)
            elif close_df is not None and a in close_df.columns and date in close_df.index:
                px = close_df.loc[date, a]
                fallback_assets.append(a)
        prices[a] = px
    if missing:
        dt = pd.Timestamp(date).date().isoformat()
        assets_text = ", ".join(sorted(missing))
        raise ValueError(
            f"{context}: missing T+1 adjusted open price on {dt} for {assets_text}. "
            "Formal Sub-B execution requires T+1 adjusted open; refusing close fallback."
        )
    row = pd.Series(prices)
    if fallback_assets:
        row.attrs["open_price_close_fallback_assets"] = tuple(sorted(fallback_assets))
    return row

def run_us_rotation(close_df, ranking_codes, top_n=US_ROT_TOP_N, abs_threshold=US_ROT_ABS_THRESHOLD,
                    min_turnover=US_ROT_MIN_TURNOVER,
                    threshold=US_ROT_REBALANCE_THRESHOLD,
                    btc_ticker=None, btc_start=None, btc_max_w=None,
                    us_open=None,
                    strict_open_execution=False):
    if btc_ticker and btc_start is not None and btc_ticker in close_df.columns:
        close_df = close_df.copy()
        close_df.loc[close_df.index < btc_start, btc_ticker] = np.nan
    momentum = close_df.div(close_df.shift(US_ROT_LB)).sub(1)
    vol_df = close_df.pct_change().rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
    start_idx = max(US_ROT_LB, US_ROT_VOL_LB, US_ROT_VOL_WINDOW) + 1
    signal_days = _us_signal_days(close_df, start_idx)
    raw_w = {"BIL": 1.0}
    act = {"BIL": 1.0}
    holdings = {"BIL": 1.0}
    pending_act = None
    pending_comm = 0.0
    scale = 1.0
    w_assets = list(ranking_codes) + (["BIL"] if "BIL" not in ranking_codes else [])
    rows, hist = [], []
    for i in range(start_idx, len(close_df)):
        if len(hist) >= US_ROT_VOL_WINDOW:
            rv = np.std(hist[-US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
            scale = min(max(US_ROT_TARGET_VOL / rv, 0.05), US_ROT_MAX_LEV) if rv > 0.001 else US_ROT_MAX_LEV
        if pending_act is not None:
            open_assets = _active_weight_assets(holdings, pending_act)
            open_row = _us_open_row(
                close_df.index[i],
                open_assets,
                us_open,
                close_df,
                strict=strict_open_execution,
                context="Sub-B legacy rotation",
            )
            overnight = _us_weighted_return(holdings, close_df.iloc[i-1], open_row)
            intraday = _us_weighted_return(pending_act, open_row, close_df.iloc[i])
            adj = (1 + overnight) * (1 + intraday) * (1 - pending_comm) - 1
            holdings = dict(pending_act)
            pending_act = None
            pending_comm = 0.0
        else:
            adj = _us_weighted_return(holdings, close_df.iloc[i-1], close_df.iloc[i])
        hist.append(adj)
        is_sig = i in signal_days
        rebalanced = False
        new_act = dict(act)
        if is_sig:
            # Get previous risky holdings for threshold comparison
            prev_risky = {a for a in w_assets if a != "BIL" and act.get(a, 0.0) > 0.001}
            raw_w = _us_raw_weights(
                momentum.iloc[i], vol_df.iloc[i], ranking_codes, top_n, abs_threshold,
                prev_risky=prev_risky if prev_risky else None,
                threshold=threshold)
            new_act = _us_model_b(raw_w, scale)
            if btc_max_w is not None and btc_ticker:
                new_act = _apply_btc_cap(new_act, btc_ticker, btc_max_w)
            prev_a = {a: act.get(a, 0.0) for a in w_assets} if rows else {"BIL": 1.0}
            all_a = set(list(new_act.keys()) + list(prev_a.keys()))
            to = sum(abs(new_act.get(a, 0) - prev_a.get(a, 0)) for a in all_a if a != "BIL")
            if _subb_should_rebalance(to, min_turnover):
                pending_act = dict(new_act)
                pending_comm = to * US_ROT_COMMISSION if to > 0 else 0.0
                act = new_act
                rebalanced = True
        row = {"date": close_df.index[i], "return": adj, "is_signal": is_sig,
               "rebalanced": rebalanced}
        for a in w_assets:
            row[f"w_{a}"] = act.get(a, 0.0)
        if is_sig:
            for a in w_assets:
                row[f"hypo_w_{a}"] = new_act.get(a, 0.0)
        rows.append(row)
    df = pd.DataFrame(rows).set_index("date")
    df["nav"] = (1 + df["return"]).cumprod()
    return df

def _prefixed_weight_dict(row, prefix, assets):
    out = {}
    for asset in assets:
        value = row.get(f"{prefix}{asset}", 0.0)
        if pd.notna(value):
            out[asset] = float(value)
    return out

def _subb_v75_leg_weight_rows(result_df, row_key, min_weight=0.001):
    if result_df is None or len(result_df) == 0:
        return []
    try:
        row = result_df.loc[row_key] if row_key in result_df.index else result_df.iloc[row_key]
    except Exception:
        return []
    assets = sorted({
        col[len("target_w_"):]
        for col in result_df.columns
        if col.startswith("target_w_")
    } | {
        col[len("official_w_"):]
        for col in result_df.columns
        if col.startswith("official_w_")
    } | {
        col[len("ema_w_"):]
        for col in result_df.columns
        if col.startswith("ema_w_")
    } | {
        col[len("w_"):]
        for col in result_df.columns
        if col.startswith("w_")
    })
    rows = []
    for asset in assets:
        official_raw = float(row.get(f"official_w_{asset}", 0.0) or 0.0)
        ema_raw = float(row.get(f"ema_w_{asset}", 0.0) or 0.0)
        official_contrib = float(row.get(f"official_contrib_w_{asset}", SUBB_V75_OFFICIAL_WEIGHT * official_raw) or 0.0)
        ema_contrib = float(row.get(f"ema_contrib_w_{asset}", SUBB_V75_EMA_WEIGHT * ema_raw) or 0.0)
        final_w = float(row.get(f"target_w_{asset}", official_contrib + ema_contrib) or 0.0)
        if max(abs(final_w), abs(official_raw), abs(ema_raw), abs(official_contrib), abs(ema_contrib)) < min_weight:
            continue
        rows.append({
            "asset": asset,
            "live_name": _ROT_PROXY_TO_LIVE.get(asset, asset),
            "official_raw": official_raw,
            "ema_raw": ema_raw,
            "official_contrib": official_contrib,
            "ema_contrib": ema_contrib,
            "final_weight": final_w,
        })
    rows.sort(key=lambda item: item["final_weight"], reverse=True)
    return rows


def _write_subb_v75_leg_weight_table(write, result_df, row_key, title):
    # Kept as a compatibility stub for older call sites; V7.9 uses four-leg tables.
    return

def _weight_columns_assets(df, prefixes=("w_", "actual_w_", "target_w_")):
    assets = set()
    for col in df.columns:
        for prefix in prefixes:
            if col.startswith(prefix):
                assets.add(col[len(prefix):])
    return sorted(assets)

def _volreg_next_cash_state(current_cash, ratio):
    if pd.isna(ratio):
        return bool(current_cash)
    ratio = float(ratio)
    if not current_cash and ratio > US_ROT_VOLREG_THRESHOLD:
        return True
    if current_cash and ratio < US_ROT_VOLREG_EXIT_THRESHOLD:
        return False
    return bool(current_cash)


def _volreg_scale_for_state(active):
    return float(US_ROT_VOLREG_DEFENSE_SCALE) if bool(active) else 1.0


def _volreg_scaled_assets_in(weights_or_assets):
    if isinstance(weights_or_assets, dict):
        assets = set(weights_or_assets)
    else:
        assets = set(weights_or_assets or [])
    return [asset for asset in US_ROT_VOLREG_SCALE_ASSETS if asset in assets]


def _prefixed_weight_dict_with_asset_fallback(row, primary_prefix, fallback_prefix, assets):
    primary = _prefixed_weight_dict(row, primary_prefix, assets)
    if not any(abs(v) > 1e-12 for v in primary.values()):
        return _prefixed_weight_dict(row, fallback_prefix, assets)
    fallback = _prefixed_weight_dict(row, fallback_prefix, assets)
    out = {}
    for asset in assets:
        key = f"{primary_prefix}{asset}"
        raw = row.get(key, np.nan)
        out[asset] = fallback.get(asset, 0.0) if pd.isna(raw) else primary.get(asset, 0.0)
    return out


def _apply_subb_volreg_defense_scale_to_weights(weights, active=True):
    out = {asset: float(weight or 0.0) for asset, weight in dict(weights or {}).items()}
    if not active:
        out["CASH"] = 0.0
        return out, {asset: 0.0 for asset in _volreg_scaled_assets_in(out)}
    removed = {}
    for asset in _volreg_scaled_assets_in(out):
        old = float(out.get(asset, 0.0) or 0.0)
        new = old * float(US_ROT_VOLREG_DEFENSE_SCALE)
        out[asset] = new
        removed[asset] = old - new
    moved_to_bil = sum(removed.values())
    out["BIL"] = float(out.get("BIL", 0.0) or 0.0) + moved_to_bil
    out["CASH"] = 0.0
    return out, removed


def _subb_volreg_scaled_assets_text(live=False):
    assets = [
        _ROT_PROXY_TO_LIVE.get(asset, asset) if live else asset
        for asset in US_ROT_VOLREG_SCALE_ASSETS
    ]
    return "/".join(assets)


def _subb_volreg_rule_text():
    proxy_assets = _subb_volreg_scaled_assets_text()
    live_assets = _subb_volreg_scaled_assets_text(live=True)
    live_note = "" if live_assets == proxy_assets else f" (实盘{live_assets})"
    return (
        f"SPY {US_ROT_VOLREG_SHORT_W}d/{US_ROT_VOLREG_LONG_W}d vol比 "
        f">{US_ROT_VOLREG_THRESHOLD:.1f} -> {proxy_assets}{live_note} x{US_ROT_VOLREG_DEFENSE_SCALE:.2f}, "
        f"差额进BIL；低于{US_ROT_VOLREG_EXIT_THRESHOLD:.1f}恢复"
    )


def _should_force_volreg_cash_display(volreg_enabled, volreg_cash_next):
    return False


def _subb_model_rebalanced_value(row):
    return bool(row.get("model_rebalanced", row.get("rebalanced", False)))


def _row_prefixed_weights(row, prefix, assets):
    weights = {}
    for asset in assets:
        value = row.get(f"{prefix}{asset}", 0.0)
        weights[asset] = float(value) if pd.notna(value) else 0.0
    return weights


def _subb_signal_display_source_weights(result_df, signal_date, rot_w_cols):
    row = result_df.loc[signal_date]
    use_target = _subb_model_rebalanced_value(row)
    assets = set()
    for col in list(rot_w_cols or []) + list(result_df.columns):
        if col.startswith("w_"):
            assets.add(col[len("w_"):])
        elif col.startswith("target_w_"):
            assets.add(col[len("target_w_"):])
    weights = {}
    for asset in sorted(assets):
        if use_target:
            value = row.get(f"target_w_{asset}", 0.0)
        else:
            value = row.get(f"w_{asset}", 0.0)
        weights[asset] = float(value) if pd.notna(value) else 0.0
    return weights


def _subb_effective_display_weights(signal_weights, prev_weights=None, force_cash=False):
    signal_weights = dict(signal_weights or {})
    prev_weights = dict(prev_weights or {})
    assets = set(signal_weights) | set(prev_weights)
    if force_cash:
        assets.add("CASH")
        display_weights = {asset: 0.0 for asset in assets}
        display_weights["CASH"] = 1.0
        return display_weights, assets
    return dict(signal_weights), assets


def _is_v78_subb_blend(result):
    return (
        result is not None
        and "v78_subb_v77_return" in result.columns
        and "v78_subb_bias_return" in result.columns
        and "v78_subb_logvol_return" in result.columns
    )


def apply_vol_regime_overlay(us_rot_result, spy_close, close_df=None, us_open=None,
                             strict_open_execution=False):
    """VolReg风控: SPY短期/长期vol过热时，削指定资产暴露，差额转BIL。"""
    spy_ret = spy_close.pct_change()
    short_vol = spy_ret.rolling(US_ROT_VOLREG_SHORT_W).std() * np.sqrt(US_TRADING_DAYS)
    long_vol  = spy_ret.rolling(US_ROT_VOLREG_LONG_W).std() * np.sqrt(US_TRADING_DAYS)
    vol_ratio = (short_vol / long_vol).reindex(us_rot_result.index).ffill()
    # shift(1): T日收盘计算信号 → T+1日执行
    ratio_shifted = vol_ratio.shift(1)
    defense_state = False
    mask_values = []
    for value in ratio_shifted:
        defense_state = _volreg_next_cash_state(defense_state, value)
        mask_values.append(defense_state)
    mask = pd.Series(mask_values, index=us_rot_result.index, dtype=bool)
    result = us_rot_result.copy()
    close_aligned = close_df.reindex(result.index) if close_df is not None else None
    pre_volreg_return = pd.to_numeric(result["return"], errors="coerce").fillna(0.0)
    base_ret = pre_volreg_return if _is_v78_subb_blend(result) else pd.to_numeric(
        result.get(
            "return_before_subb_execution_cost",
            result.get("return_before_execution_cost", result["return"]),
        ),
        errors="coerce",
    ).fillna(0.0)
    assets = _weight_columns_assets(result)
    if "BIL" not in assets:
        assets.append("BIL")
    if "CASH" not in assets:
        assets.append("CASH")
    prev_effective = None
    prev_removed = None
    prev_defense = False
    turnovers = []
    costs = []
    gross_returns = []
    final_returns = []
    volreg_actions = []
    moved_to_bil_values = []
    model_records = []
    effective_records = []
    model_target_records = []
    effective_target_records = []
    for pos, dt in enumerate(result.index):
        row = result.loc[dt]
        model_w = _prefixed_weight_dict_with_asset_fallback(row, "actual_w_", "w_", assets)
        defense_active = bool(mask.loc[dt])
        effective_w, removed_w = _apply_subb_volreg_defense_scale_to_weights(model_w, defense_active)
        model_target_w = _prefixed_weight_dict_with_asset_fallback(row, "target_w_", "actual_w_", assets)
        target_defense_active = (
            _volreg_next_cash_state(defense_active, vol_ratio.loc[dt])
            if pd.notna(vol_ratio.loc[dt])
            else defense_active
        )
        effective_target_w, _ = _apply_subb_volreg_defense_scale_to_weights(
            model_target_w,
            target_defense_active,
        )
        for asset in assets:
            effective_w.setdefault(asset, 0.0)
            effective_target_w.setdefault(asset, 0.0)
            removed_w.setdefault(asset, 0.0)
        moved_to_bil_values.append(sum(float(v or 0.0) for v in removed_w.values()))
        if prev_effective is None:
            turnover = 0.0
        else:
            if defense_active == prev_defense:
                turnover = 0.0
            else:
                cur_scale = _volreg_scale_for_state(defense_active)
                prev_scale = _volreg_scale_for_state(prev_defense)
                scaled_model_weight = sum(
                    float(model_w.get(asset, 0.0) or 0.0)
                    for asset in _volreg_scaled_assets_in(model_w)
                )
                turnover = scaled_model_weight * abs(cur_scale - prev_scale)
        has_open_execution_prices = close_aligned is not None and prev_effective is not None and (
            us_open is not None or strict_open_execution
        )
        gross_ret = float(base_ret.loc[dt])
        if has_open_execution_prices:
            adjusted_assets = [
                asset for asset in _volreg_scaled_assets_in(assets)
                if float((prev_removed or {}).get(asset, 0.0) or 0.0) > 1e-12
                or float(removed_w.get(asset, 0.0) or 0.0) > 1e-12
            ]
            if adjusted_assets:
                open_row = _us_open_row(
                    dt,
                    ["BIL", *adjusted_assets],
                    us_open,
                    close_aligned,
                    strict=strict_open_execution,
                    context="Sub-B VolReg equity defense",
                )
                prev_close = close_aligned.iloc[pos - 1] if pos > 0 else close_aligned.loc[dt]
                cur_close = close_aligned.loc[dt]
                delta = 0.0
                for asset in adjusted_assets:
                    prev_removed_weight = float((prev_removed or {}).get(asset, 0.0) or 0.0)
                    cur_removed_weight = float(removed_w.get(asset, 0.0) or 0.0)
                    if prev_removed_weight > 1e-12:
                        delta += prev_removed_weight * (
                            _subb_price_return("BIL", prev_close, open_row)
                            - _subb_price_return(asset, prev_close, open_row)
                        )
                    if cur_removed_weight > 1e-12:
                        delta += cur_removed_weight * (
                            _subb_price_return("BIL", open_row, cur_close)
                            - _subb_price_return(asset, open_row, cur_close)
                        )
                gross_ret += delta
        cost = turnover * US_ROT_COMMISSION
        gross_returns.append(gross_ret)
        final_returns.append((1.0 + gross_ret) * (1.0 - cost) - 1.0)
        turnovers.append(turnover)
        costs.append(cost)
        if defense_active and not prev_defense:
            volreg_actions.append("enter_defense")
        elif prev_defense and not defense_active:
            volreg_actions.append("exit_defense")
        else:
            volreg_actions.append("")
        model_records.append({asset: model_w.get(asset, 0.0) for asset in assets})
        effective_records.append({asset: effective_w.get(asset, 0.0) for asset in assets})
        model_target_records.append({asset: model_target_w.get(asset, 0.0) for asset in assets})
        effective_target_records.append({asset: effective_target_w.get(asset, 0.0) for asset in assets})
        prev_effective = effective_w
        prev_removed = removed_w
        prev_defense = defense_active
    model_df = pd.DataFrame.from_records(model_records, index=result.index).reindex(columns=assets).fillna(0.0)
    effective_df = pd.DataFrame.from_records(effective_records, index=result.index).reindex(columns=assets).fillna(0.0)
    model_target_df = pd.DataFrame.from_records(model_target_records, index=result.index).reindex(columns=assets).fillna(0.0)
    effective_target_df = pd.DataFrame.from_records(effective_target_records, index=result.index).reindex(columns=assets).fillna(0.0)
    for asset in assets:
        result[f"model_w_{asset}"] = model_df[asset]
        result[f"model_target_w_{asset}"] = model_target_df[asset]
        result[f"effective_w_{asset}"] = effective_df[asset]
        result[f"w_{asset}"] = effective_df[asset]
        result[f"target_w_{asset}"] = effective_target_df[asset]
    result["pre_volreg_return"] = pre_volreg_return
    result["gross_return_before_volreg_cost"] = pd.Series(gross_returns, index=result.index, dtype=float)
    result["model_full_day_return_before_volreg"] = base_ret
    result["return_before_volreg"] = pre_volreg_return
    result["volreg_action"] = pd.Series(volreg_actions, index=result.index, dtype=object)
    result["subb_effective_turnover"] = pd.Series(turnovers, index=result.index, dtype=float)
    result["subb_effective_cost"] = pd.Series(costs, index=result.index, dtype=float)
    base_rebalanced = result.get("rebalanced", pd.Series(False, index=result.index)).fillna(False).astype(bool)
    effective_rebalanced = result["subb_effective_turnover"].abs() > 1e-9
    result["model_rebalanced"] = base_rebalanced
    result["effective_rebalanced"] = effective_rebalanced
    result["volreg_transition"] = result["volreg_action"].isin(["enter_defense", "exit_defense"])
    result["volreg_transition_turnover"] = result["subb_effective_turnover"].where(result["volreg_transition"], 0.0)
    result["volreg_transition_cost"] = result["subb_effective_cost"].where(result["volreg_transition"], 0.0)
    result["volreg_rebalanced"] = result["volreg_transition"]
    result["rebalanced"] = base_rebalanced
    result["return"] = pd.Series(final_returns, index=result.index, dtype=float)
    result["nav"] = (1 + result["return"]).cumprod()
    result["volreg_ratio"] = vol_ratio        # 当日收盘的ratio(未shift), 用于信号展示
    result["volreg_defense"] = mask           # 当日是否因昨日信号执行股票指数降档
    result["volreg_cash"] = False             # V7.9新VolReg不再整腿转现金
    result["volreg_effective_scale"] = pd.Series(
        np.where(mask, float(US_ROT_VOLREG_DEFENSE_SCALE), 1.0),
        index=result.index,
        dtype=float,
    )
    result["volreg_moved_to_bil"] = pd.Series(moved_to_bil_values, index=result.index, dtype=float)
    result["volreg_scaled_assets"] = ",".join(US_ROT_VOLREG_SCALE_ASSETS)
    return result


def _subb_dbc_profit_guard_rule_text():
    live = _ROT_PROXY_TO_LIVE.get(SUBB_DBC_PROFIT_GUARD_ASSET, SUBB_DBC_PROFIT_GUARD_ASSET)
    return (
        f"{live}/{SUBB_DBC_PROFIT_GUARD_ASSET}: retain<="
        f"{SUBB_DBC_PROFIT_GUARD_RETAIN_L1:.0%} -> scale "
        f"{SUBB_DBC_PROFIT_GUARD_SCALE_L1:.2f}; retain<="
        f"{SUBB_DBC_PROFIT_GUARD_RETAIN_L2:.0%} -> scale "
        f"{SUBB_DBC_PROFIT_GUARD_SCALE_L2:.2f}; moved weight -> "
        f"{SUBB_DBC_PROFIT_GUARD_CASH_ASSET}"
    )


def _subb_dbc_profit_guard_scale_from_retain(retain_ratio):
    if pd.isna(retain_ratio):
        return 1.0, 0
    retain_ratio = float(retain_ratio)
    tol = 1e-9
    if retain_ratio <= SUBB_DBC_PROFIT_GUARD_RETAIN_L2 + tol:
        return SUBB_DBC_PROFIT_GUARD_SCALE_L2, 2
    if retain_ratio <= SUBB_DBC_PROFIT_GUARD_RETAIN_L1 + tol:
        return SUBB_DBC_PROFIT_GUARD_SCALE_L1, 1
    return 1.0, 0


def _subb_dbc_profit_guard_level_from_scale(scale):
    try:
        scale = float(scale)
    except Exception:
        return 0
    if abs(scale - SUBB_DBC_PROFIT_GUARD_SCALE_L2) <= 1e-9:
        return 2
    if abs(scale - SUBB_DBC_PROFIT_GUARD_SCALE_L1) <= 1e-9:
        return 1
    return 0


def _subb_price_return(asset, prev_prices, curr_prices):
    if asset is None:
        return 0.0
    prev_px = prev_prices.get(asset, np.nan)
    curr_px = curr_prices.get(asset, np.nan)
    if pd.isna(prev_px) or pd.isna(curr_px) or float(prev_px) == 0.0:
        return 0.0
    return float(curr_px) / float(prev_px) - 1.0


def _subb_price_value(asset, prices):
    value = prices.get(asset, np.nan)
    if pd.isna(value):
        return np.nan
    try:
        return float(value)
    except Exception:
        return np.nan


def _subb_weights_from_prefixes(row, prefixes, assets):
    weights = {}
    for asset in assets:
        value = np.nan
        for prefix in prefixes:
            raw = row.get(f"{prefix}{asset}", np.nan)
            if pd.notna(raw):
                value = raw
                break
        weights[asset] = float(value) if pd.notna(value) else 0.0
    return weights


def _apply_subb_dbc_profit_guard_scale_to_weights(weights, scale):
    out = dict(weights or {})
    if not SUBB_DBC_PROFIT_GUARD_ENABLED:
        return out
    asset = SUBB_DBC_PROFIT_GUARD_ASSET
    cash_asset = SUBB_DBC_PROFIT_GUARD_CASH_ASSET
    try:
        scale = float(scale)
    except Exception:
        scale = 1.0
    asset_weight = float(out.get(asset, 0.0) or 0.0)
    if asset_weight <= 1e-12:
        return out
    final_weight = asset_weight * max(scale, 0.0)
    removed_weight = asset_weight - final_weight
    out[asset] = final_weight
    out[cash_asset] = float(out.get(cash_asset, 0.0) or 0.0) + removed_weight
    return out


def _subb_dbc_profit_guard_latest_next_scale(us_rot_result):
    if (
        not SUBB_DBC_PROFIT_GUARD_ENABLED
        or us_rot_result is None
        or len(us_rot_result) == 0
        or "dbc_profit_guard_next_scale" not in us_rot_result.columns
    ):
        return 1.0
    value = us_rot_result["dbc_profit_guard_next_scale"].iloc[-1]
    if pd.isna(value):
        return 1.0
    return float(value)


def _subb_dbc_profit_guard_display_target_weights(us_rot_result, row_key=-1):
    if (
        not SUBB_DBC_PROFIT_GUARD_ENABLED
        or us_rot_result is None
        or len(us_rot_result) == 0
        or "dbc_profit_guard_next_scale" not in us_rot_result.columns
    ):
        return None
    try:
        row = us_rot_result.loc[row_key] if row_key in us_rot_result.index else us_rot_result.iloc[row_key]
    except Exception:
        return None
    assets = _weight_columns_assets(us_rot_result, prefixes=("target_w_", "w_", "actual_w_", "effective_w_"))
    weights = _row_prefixed_weights(row, "target_w_", assets)
    if not any(abs(v) > 1e-12 for v in weights.values()):
        weights = _row_prefixed_weights(row, "w_", assets)
    return weights


def _subb_dbc_profit_guard_pending(row):
    if row is None:
        return False
    try:
        today = _subb_row_float(row, "dbc_profit_guard_scale_today", 1.0)
        nxt = _subb_row_float(row, "dbc_profit_guard_next_scale", today)
        current_removed = _subb_row_float(row, "dbc_profit_guard_removed_weight", 0.0)
        target_removed = _subb_row_float(row, "dbc_profit_guard_target_removed_weight", 0.0)
    except Exception:
        return False
    return abs(nxt - today) > 1e-9 or abs(target_removed - current_removed) > 0.005


def apply_subb_dbc_profit_guard_overlay(us_rot_result, close_df, us_open=None,
                                        strict_open_execution=False):
    if (
        not SUBB_DBC_PROFIT_GUARD_ENABLED
        or us_rot_result is None
        or len(us_rot_result) == 0
        or close_df is None
    ):
        return us_rot_result
    asset = SUBB_DBC_PROFIT_GUARD_ASSET
    cash_asset = SUBB_DBC_PROFIT_GUARD_CASH_ASSET
    if asset not in close_df.columns:
        return us_rot_result

    result = us_rot_result.copy()
    close_aligned = close_df.reindex(result.index)
    assets = _weight_columns_assets(
        result,
        prefixes=("w_", "actual_w_", "target_w_", "model_w_", "effective_w_"),
    )
    for required_asset in (asset, cash_asset):
        if required_asset not in assets:
            assets.append(required_asset)
    assets = sorted(assets)

    base_return = pd.to_numeric(result["return"], errors="coerce").fillna(0.0)
    scale_today = 1.0
    prev_scale = 1.0
    prev_pre_asset_weight = 0.0
    wave_entry = np.nan
    wave_peak_profit = 0.0

    final_returns = []
    pre_current_records = []
    final_current_records = []
    pre_target_records = []
    final_target_records = []
    scale_today_records = []
    next_scale_records = []
    level_today_records = []
    next_level_records = []
    entry_records = []
    profit_records = []
    peak_records = []
    retain_records = []
    removed_records = []
    target_removed_records = []
    turnover_records = []
    cost_records = []
    pending_records = []
    action_records = []

    for i, dt in enumerate(result.index):
        row = result.iloc[i]
        pre_current = _subb_weights_from_prefixes(row, ("w_", "effective_w_", "actual_w_"), assets)
        pre_target = _subb_weights_from_prefixes(row, ("target_w_", "w_", "effective_w_", "actual_w_"), assets)
        pre_asset_weight = max(float(pre_current.get(asset, 0.0) or 0.0), 0.0)

        guard_turnover = 0.0
        guard_cost = 0.0
        adjusted_return = float(base_return.iloc[i])
        if i > 0:
            prev_dt = result.index[i - 1]
            prev_close = close_aligned.loc[prev_dt]
            overnight_removed = max(prev_pre_asset_weight, 0.0) * max(1.0 - prev_scale, 0.0)
            intraday_removed = pre_asset_weight * max(1.0 - scale_today, 0.0)
            return_split_assets = [asset]
            if overnight_removed > 1e-12 or intraday_removed > 1e-12:
                return_split_assets.append(cash_asset)
            cur_open = _us_open_row(
                dt,
                return_split_assets,
                us_open,
                close_aligned,
                strict=strict_open_execution,
                context="Sub-B DBC profit guard return split",
            )
            cur_close = close_aligned.loc[dt]
            overnight_delta = overnight_removed * (
                _subb_price_return(cash_asset, prev_close, cur_open)
                - _subb_price_return(asset, prev_close, cur_open)
            )
            intraday_delta = intraday_removed * (
                _subb_price_return(cash_asset, cur_open, cur_close)
                - _subb_price_return(asset, cur_open, cur_close)
            )
            guard_turnover = pre_asset_weight * abs(scale_today - prev_scale)
            guard_cost = guard_turnover * US_ROT_COMMISSION
            adjusted_return = (1.0 + adjusted_return + overnight_delta + intraday_delta) * (1.0 - guard_cost) - 1.0

        final_current = _apply_subb_dbc_profit_guard_scale_to_weights(pre_current, scale_today)
        removed_weight = pre_asset_weight - float(final_current.get(asset, 0.0) or 0.0)

        if pre_asset_weight <= 1e-12:
            wave_entry = np.nan
            wave_peak_profit = 0.0
            profit = np.nan
            retain_ratio = np.nan
            next_scale = 1.0
            next_level = 0
        else:
            cur_open = _us_open_row(
                dt,
                [asset],
                us_open,
                close_aligned,
                strict=strict_open_execution,
                context="Sub-B DBC profit guard entry price",
            )
            cur_close = close_aligned.loc[dt]
            if pd.isna(wave_entry):
                wave_entry = _subb_price_value(asset, cur_open)
                if pd.isna(wave_entry) or wave_entry <= 0.0:
                    wave_entry = _subb_price_value(asset, cur_close)
            close_price = _subb_price_value(asset, cur_close)
            profit = close_price / wave_entry - 1.0 if pd.notna(close_price) and pd.notna(wave_entry) and wave_entry > 0.0 else np.nan
            if pd.notna(profit):
                wave_peak_profit = max(wave_peak_profit, float(profit))
            if wave_peak_profit > SUBB_DBC_PROFIT_GUARD_MIN_PEAK_PROFIT and pd.notna(profit):
                retain_ratio = float(profit) / wave_peak_profit
                next_scale, next_level = _subb_dbc_profit_guard_scale_from_retain(retain_ratio)
            else:
                retain_ratio = np.nan
                next_scale = 1.0
                next_level = 0

        final_target = _apply_subb_dbc_profit_guard_scale_to_weights(pre_target, next_scale)
        pre_target_asset_weight = max(float(pre_target.get(asset, 0.0) or 0.0), 0.0)
        target_removed_weight = pre_target_asset_weight - float(final_target.get(asset, 0.0) or 0.0)
        pending = abs(next_scale - scale_today) > 1e-9 or abs(target_removed_weight - removed_weight) > 0.005
        if next_scale < scale_today - 1e-9:
            action = f"derisk_l{next_level}"
        elif next_scale > scale_today + 1e-9:
            action = "restore"
        elif scale_today < 1.0 - 1e-9:
            action = f"hold_l{_subb_dbc_profit_guard_level_from_scale(scale_today)}"
        else:
            action = ""

        final_returns.append(adjusted_return)
        pre_current_records.append(pre_current)
        final_current_records.append(final_current)
        pre_target_records.append(pre_target)
        final_target_records.append(final_target)
        scale_today_records.append(scale_today)
        next_scale_records.append(next_scale)
        level_today_records.append(_subb_dbc_profit_guard_level_from_scale(scale_today))
        next_level_records.append(next_level)
        entry_records.append(wave_entry)
        profit_records.append(profit)
        peak_records.append(wave_peak_profit if wave_peak_profit > 0.0 else np.nan)
        retain_records.append(retain_ratio)
        removed_records.append(removed_weight)
        target_removed_records.append(target_removed_weight)
        turnover_records.append(guard_turnover)
        cost_records.append(guard_cost)
        pending_records.append(pending)
        action_records.append(action)

        prev_scale = scale_today
        scale_today = next_scale
        prev_pre_asset_weight = pre_asset_weight

    index = result.index
    pre_current_df = pd.DataFrame.from_records(pre_current_records, index=index).reindex(columns=assets).fillna(0.0)
    final_current_df = pd.DataFrame.from_records(final_current_records, index=index).reindex(columns=assets).fillna(0.0)
    pre_target_df = pd.DataFrame.from_records(pre_target_records, index=index).reindex(columns=assets).fillna(0.0)
    final_target_df = pd.DataFrame.from_records(final_target_records, index=index).reindex(columns=assets).fillna(0.0)

    for a in assets:
        result[f"pre_dbc_profit_guard_w_{a}"] = pre_current_df[a]
        result[f"pre_dbc_profit_guard_target_w_{a}"] = pre_target_df[a]
        result[f"w_{a}"] = final_current_df[a]
        result[f"actual_w_{a}"] = final_current_df[a]
        result[f"effective_w_{a}"] = final_current_df[a]
        result[f"target_w_{a}"] = final_target_df[a]

    guard_return = pd.Series(final_returns, index=index, dtype=float)
    guard_turnover = pd.Series(turnover_records, index=index, dtype=float)
    guard_cost = pd.Series(cost_records, index=index, dtype=float)
    result["return_before_dbc_profit_guard"] = base_return
    result["dbc_profit_guard_overlay_return_delta"] = guard_return - base_return
    result["dbc_profit_guard_enabled"] = True
    result["dbc_profit_guard_scale_today"] = pd.Series(scale_today_records, index=index, dtype=float)
    result["dbc_profit_guard_next_scale"] = pd.Series(next_scale_records, index=index, dtype=float)
    result["dbc_profit_guard_level"] = pd.Series(level_today_records, index=index, dtype=int)
    result["dbc_profit_guard_next_level"] = pd.Series(next_level_records, index=index, dtype=int)
    result["dbc_profit_guard_entry_price"] = pd.Series(entry_records, index=index, dtype=float)
    result["dbc_profit_guard_profit"] = pd.Series(profit_records, index=index, dtype=float)
    result["dbc_profit_guard_peak_profit"] = pd.Series(peak_records, index=index, dtype=float)
    result["dbc_profit_guard_retain_ratio"] = pd.Series(retain_records, index=index, dtype=float)
    result["dbc_profit_guard_removed_weight"] = pd.Series(removed_records, index=index, dtype=float)
    result["dbc_profit_guard_target_removed_weight"] = pd.Series(target_removed_records, index=index, dtype=float)
    result["dbc_profit_guard_turnover"] = guard_turnover
    result["dbc_profit_guard_cost"] = guard_cost
    result["dbc_profit_guard_pending"] = pd.Series(pending_records, index=index, dtype=bool)
    result["dbc_profit_guard_action"] = pd.Series(action_records, index=index, dtype=object)
    result["dbc_profit_guard_active"] = result["dbc_profit_guard_scale_today"] < 1.0 - 1e-9
    result["dbc_profit_guard_rebalanced"] = guard_turnover.abs() > 1e-9

    prior_turnover = pd.to_numeric(
        result.get("subb_effective_turnover", pd.Series(0.0, index=index)),
        errors="coerce",
    ).fillna(0.0)
    prior_cost = pd.to_numeric(
        result.get("subb_effective_cost", pd.Series(0.0, index=index)),
        errors="coerce",
    ).fillna(0.0)
    prior_effective_rebalanced = result.get("effective_rebalanced", pd.Series(False, index=index)).fillna(False).astype(bool)
    result["subb_effective_turnover"] = prior_turnover + guard_turnover
    result["subb_effective_cost"] = prior_cost + guard_cost
    result["effective_rebalanced"] = prior_effective_rebalanced | result["dbc_profit_guard_rebalanced"]
    result["return"] = guard_return
    result["nav"] = (1.0 + result["return"].fillna(0.0)).cumprod()
    result.attrs["dbc_profit_guard"] = {
        "asset": asset,
        "cash_asset": cash_asset,
        "retain_l1": SUBB_DBC_PROFIT_GUARD_RETAIN_L1,
        "retain_l2": SUBB_DBC_PROFIT_GUARD_RETAIN_L2,
        "scale_l1": SUBB_DBC_PROFIT_GUARD_SCALE_L1,
        "scale_l2": SUBB_DBC_PROFIT_GUARD_SCALE_L2,
        "score_decay": False,
    }
    return result


def make_abs_mom_signals(monthly_prices, lookback=6):
    ret_n = monthly_prices / monthly_prices.shift(lookback) - 1
    raw = (ret_n > 0).astype(float)
    return raw.shift(1)

def _sma_raw_signals(monthly_prices, window=12, band=0.0):
    sma = monthly_prices.rolling(window).mean()
    if band <= 0:
        return (monthly_prices > sma).astype(float)
    upper = sma * (1 + band)
    lower = sma * (1 - band)
    sig = pd.DataFrame(np.nan, index=monthly_prices.index, columns=monthly_prices.columns)
    for col in monthly_prices.columns:
        prev = 0.0
        for i in range(len(monthly_prices)):
            price = monthly_prices.iloc[i][col]
            u = upper.iloc[i][col] if col in upper.columns else np.nan
            l = lower.iloc[i][col] if col in lower.columns else np.nan
            if pd.isna(u) or pd.isna(l) or pd.isna(price):
                sig.iloc[i, sig.columns.get_loc(col)] = np.nan
                continue
            if price > u:
                prev = 1.0
            elif price < l:
                prev = 0.0
            sig.iloc[i, sig.columns.get_loc(col)] = prev
    return sig

def make_sma_signals(monthly_prices, window=12, band=0.0):
    return _sma_raw_signals(monthly_prices, window, band).shift(1)

def simulate_prod(portfolio, monthly_ret, sig_a, cash_ret, rebal_month=12,
                  sig_b=None, blend_a=0.5, commission=0.0):
    """50/50混合回测引擎 (当sig_b=None时退化为纯AbsMom)。
    每个资产仓位分成两半: blend_a跟sig_a(AbsMom), (1-blend_a)跟sig_b(SMA)。
    年度再平衡。commission=单边交易成本(如0.001=千分之一)。"""
    dates = monthly_ret.index
    current_val = 1.0
    blend_b = 1 - blend_a
    use_blend = sig_b is not None
    if use_blend:
        pos_a = {t: current_val * c["w"] * blend_a for t, c in portfolio.items()}
        pos_b = {t: current_val * c["w"] * blend_b for t, c in portfolio.items()}
    else:
        pos_a = {t: current_val * c["w"] for t, c in portfolio.items()}
    prev_sig_a = {}
    prev_sig_b = {}
    vals, details = [], []
    for dt in dates:
        month_detail = {"date": dt}
        month_cost = 0.0
        for t, c in portfolio.items():
            proxy = c["proxy"]
            sa = sig_a.loc[dt, proxy] if proxy in sig_a.columns else 1.0
            if pd.isna(sa):
                sa = 0.0
            r_asset = monthly_ret.loc[dt, proxy] if proxy in monthly_ret.columns else 0.0
            r_cash = cash_ret.loc[dt] if dt in cash_ret.index else 0.0
            if pd.isna(r_asset):
                r_asset = 0.0
            if pd.isna(r_cash):
                r_cash = 0.0
            if commission > 0 and t in prev_sig_a and sa != prev_sig_a[t]:
                cost = pos_a[t] * commission
                pos_a[t] -= cost
                month_cost += cost
            prev_sig_a[t] = sa
            pos_a[t] *= (1 + (r_asset if sa == 1.0 else r_cash))
            month_detail[f"sig_am_{t}"] = sa
            if use_blend:
                sb = sig_b.loc[dt, proxy] if proxy in sig_b.columns else 1.0
                if pd.isna(sb):
                    sb = 0.0
                if commission > 0 and t in prev_sig_b and sb != prev_sig_b[t]:
                    cost = pos_b[t] * commission
                    pos_b[t] -= cost
                    month_cost += cost
                prev_sig_b[t] = sb
                pos_b[t] *= (1 + (r_asset if sb == 1.0 else r_cash))
                month_detail[f"sig_sma_{t}"] = sb
                month_detail[f"sig_{t}"] = blend_a * sa + blend_b * sb
            else:
                month_detail[f"sig_{t}"] = sa
        current_val = sum(pos_a.values()) + (sum(pos_b.values()) if use_blend else 0)
        vals.append(current_val)
        month_detail["cost"] = month_cost
        details.append(month_detail)
        if dt.month == rebal_month:
            if commission > 0 and current_val > 0:
                rebal_to = 0.0
                for t, c in portfolio.items():
                    tgt_a = c["w"] * (blend_a if use_blend else 1.0)
                    act_a = pos_a[t] / current_val
                    rebal_to += abs(tgt_a - act_a)
                    if use_blend:
                        tgt_b = c["w"] * blend_b
                        act_b = pos_b[t] / current_val
                        rebal_to += abs(tgt_b - act_b)
                current_val *= (1 - rebal_to * commission)
            if use_blend:
                pos_a = {t: current_val * c["w"] * blend_a for t, c in portfolio.items()}
                pos_b = {t: current_val * c["w"] * blend_b for t, c in portfolio.items()}
            else:
                pos_a = {t: current_val * c["w"] for t, c in portfolio.items()}
    nav = pd.Series(vals, index=dates)
    return nav, pd.DataFrame(details).set_index("date")

def simulate_prod_btc_phased(monthly_ret, sig_a, cash_ret, rebal_month=12,
                              sig_b=None, blend_a=0.5, commission=0.0):
    """Three-phase Sub-C backtest:
    Phase 0: Before DBMF_BT_START — PROD_PORTFOLIO_PRE_DBMF (no BTC, no DBMF -> VGIT替代)
    Phase 1: DBMF_BT_START to BTC_BT_START — PROD_PORTFOLIO_BT (no BTC, has DBMF)
    Phase 2: From BTC_BT_START — PROD_PORTFOLIO (full)
    Chains NAVs at phase boundaries."""
    phases = [
        (monthly_ret[monthly_ret.index < DBMF_BT_START], PROD_PORTFOLIO_PRE_DBMF),
        (monthly_ret[(monthly_ret.index >= DBMF_BT_START) & (monthly_ret.index < BTC_BT_START)], PROD_PORTFOLIO_BT),
        (monthly_ret[monthly_ret.index >= BTC_BT_START], PROD_PORTFOLIO),
    ]
    navs, details_list = [], []
    end_val = 1.0
    for ret_phase, portfolio in phases:
        if len(ret_phase) > 0:
            nav_phase, det_phase = simulate_prod(
                portfolio, ret_phase, sig_a, cash_ret, rebal_month,
                sig_b=sig_b, blend_a=blend_a, commission=commission)
            nav_phase_scaled = nav_phase * end_val
            navs.append(nav_phase_scaled)
            details_list.append(det_phase)
            end_val = nav_phase_scaled.iloc[-1]
    if navs:
        return pd.concat(navs), pd.concat(details_list)
    return pd.Series(dtype=float), pd.DataFrame()

def _max_drawdown_pct_from_nav(nav):
    nav = pd.to_numeric(pd.Series(nav), errors="coerce").dropna()
    if len(nav) == 0:
        return np.nan
    values = pd.concat(
        [pd.Series([1.0], dtype=float), nav.reset_index(drop=True)],
        ignore_index=True,
    )
    peak = values.cummax()
    return ((values - peak) / peak).min() * 100

def calc_daily_metrics(ret_series, rf_daily, td):
    nav = (1 + ret_series).cumprod()
    years = (ret_series.index[-1] - ret_series.index[0]).days / 365.25
    if years < 0.25 or len(ret_series) < 20:
        return None
    annual = (nav.iloc[-1] ** (1/years) - 1) * 100
    excess = ret_series - rf_daily
    sharpe = excess.mean() / excess.std() * np.sqrt(td) if excess.std() > 0 else 0
    vol = ret_series.std() * np.sqrt(td) * 100
    dd = _max_drawdown_pct_from_nav(nav)
    calmar = annual / abs(dd) if dd != 0 else 0
    monthly = ret_series.groupby(ret_series.index.to_period("M")).apply(lambda x: (1+x).prod()-1)
    win_rate = (monthly > 0).mean() * 100
    yearly = {}
    for year in sorted(ret_series.index.year.unique()):
        yr_data = ret_series[ret_series.index.year == year]
        if len(yr_data) > 10:
            yearly[year] = ((1 + yr_data).prod() - 1) * 100
    return {"annual": annual, "vol": vol, "sharpe": sharpe, "max_dd": dd,
            "calmar": calmar, "win_rate": win_rate, "years": years,
            "total_return": (nav.iloc[-1] - 1) * 100, "yearly": yearly}

def calc_monthly_metrics(ret_series, rf_monthly=0.0):
    nav = (1 + ret_series).cumprod()
    n_months = len(ret_series)
    years = n_months / 12
    total_return = (nav.iloc[-1] - 1) * 100
    dd = _max_drawdown_pct_from_nav(nav)
    win_rate = (ret_series > 0).mean() * 100
    if n_months < 3:
        return {"annual": None, "vol": None, "sharpe": None, "max_dd": dd,
                "calmar": None, "win_rate": win_rate, "years": years,
                "total_return": total_return, "yearly": {}}
    annual = (nav.iloc[-1] ** (1/years) - 1) * 100
    excess = ret_series - rf_monthly
    sharpe = excess.mean() / excess.std() * np.sqrt(12) if excess.std() > 0 else 0
    vol = ret_series.std() * np.sqrt(12) * 100
    calmar = annual / abs(dd) if dd != 0 else 0
    yearly = {}
    for year in sorted(ret_series.index.year.unique()):
        yr_data = ret_series[ret_series.index.year == year]
        if len(yr_data) >= 1:
            yearly[year] = ((1 + yr_data).prod() - 1) * 100
    return {"annual": annual, "vol": vol, "sharpe": sharpe, "max_dd": dd,
            "calmar": calmar, "win_rate": win_rate, "years": years,
            "total_return": total_return, "yearly": yearly}

def _performance_combined_daily_returns(daily_returns):
    series_map = {}
    for name in PERFORMANCE_COMBO_ORDER:
        s = daily_returns.get(name)
        if s is None:
            continue
        s = pd.to_numeric(pd.Series(s), errors="coerce").dropna().sort_index()
        if len(s) > 1:
            series_map[name] = s
    if len(series_map) < len(PERFORMANCE_COMBO_ORDER):
        return pd.Series(dtype=float)
    common_start = max(s.index[0] for s in series_map.values())
    common_end = min(s.index[-1] for s in series_map.values())
    if common_end <= common_start:
        return pd.Series(dtype=float)
    nav_parts = {}
    for name, s in series_map.items():
        period = s[(s.index >= common_start) & (s.index <= common_end)]
        if len(period) <= 1:
            return pd.Series(dtype=float)
        nav_parts[name] = (1.0 + period).cumprod()
    all_dates = sorted(set().union(*(s.index for s in nav_parts.values())))
    if len(all_dates) <= 1:
        return pd.Series(dtype=float)
    nav_df = pd.DataFrame({
        name: s.reindex(pd.DatetimeIndex(all_dates)).ffill()
        for name, s in nav_parts.items()
    })
    cw = _performance_combo_weights()
    weight_df = nav_df.notna().astype(float)
    for col in weight_df.columns:
        weight_df[col] *= cw.get(col, 0.0)
    weight_sum = weight_df.sum(axis=1).replace(0, np.nan)
    weight_df = weight_df.div(weight_sum, axis=0)
    nav_comb = (nav_df.fillna(0.0) * weight_df).sum(axis=1)
    combined_ret = nav_comb.pct_change()
    if len(nav_comb) > 0:
        combined_ret.iloc[0] = nav_comb.iloc[0] - 1.0
    return combined_ret.dropna()

def _performance_daily_window_metric(ret_series, requested_start, end_date):
    s = pd.to_numeric(pd.Series(ret_series), errors="coerce").dropna().sort_index()
    if len(s) == 0:
        return {"annual": None, "max_dd": None, "reason": "no data"}
    end_ts = pd.Timestamp(end_date)
    s = s[s.index <= end_ts]
    if len(s) == 0:
        return {"annual": None, "max_dd": None, "reason": "no data before end date"}
    if requested_start is not None:
        requested_start = pd.Timestamp(requested_start)
        first_available = s.index[0]
        if first_available > requested_start + pd.Timedelta(days=7):
            return {
                "annual": None,
                "max_dd": None,
                "reason": (
                    "insufficient post-start history: "
                    f"starts {first_available.strftime('%Y-%m-%d')} after required {requested_start.strftime('%Y-%m-%d')}"
                ),
            }
        s = s[s.index >= requested_start]
    if len(s) < PERFORMANCE_STANDARD_MIN_DAILY_ROWS:
        return {
            "annual": None,
            "max_dd": None,
            "reason": f"insufficient post-start history: {len(s)} daily rows",
        }
    years = (s.index[-1] - s.index[0]).days / 365.25
    if years <= 0:
        return {"annual": None, "max_dd": None, "reason": "insufficient post-start history: zero date span"}
    nav = (1.0 + s).cumprod()
    annual = (nav.iloc[-1] ** (1.0 / years) - 1.0) * 100.0
    max_dd = _max_drawdown_pct_from_nav(nav)
    return {
        "annual": float(annual),
        "max_dd": float(max_dd),
        "reason": None,
        "start": s.index[0],
        "end": s.index[-1],
    }

def _performance_standard_window_rows(daily_returns, end_date=None, columns=None):
    if columns is None:
        columns = PERFORMANCE_COLUMNS
    cleaned = {}
    for name, s in dict(daily_returns or {}).items():
        if s is None:
            continue
        ser = pd.to_numeric(pd.Series(s), errors="coerce").dropna().sort_index()
        if len(ser) > 0:
            cleaned[name] = ser
    if end_date is None:
        latest = [s.index[-1] for s in cleaned.values() if len(s) > 0]
        end_date = max(latest) if latest else pd.Timestamp.today().normalize()
    end_ts = pd.Timestamp(end_date)
    rows = []
    for label, offset in PERFORMANCE_STANDARD_WINDOWS:
        requested_start = None if offset is None else end_ts - offset
        row = {"window": label, "start": requested_start, "end": end_ts, "metrics": {}}
        for col in columns:
            row["metrics"][col] = _performance_daily_window_metric(
                cleaned.get(col, pd.Series(dtype=float)),
                requested_start,
                end_ts,
            )
        rows.append(row)
    return rows

def _format_performance_standard_window_cell(metric):
    if not metric or metric.get("annual") is None or metric.get("max_dd") is None:
        reason = (metric or {}).get("reason") or "N/A"
        return f"N/A ({reason})"
    return f"{metric['annual']:.2f}% / {metric['max_dd']:.2f}%"

def _write_performance_standard_window_table(w, daily_returns, end_date=None):
    rows = _performance_standard_window_rows(daily_returns, end_date=end_date)
    w("\n### 标准窗口指标（年化收益 / 最大回撤）\n\n")
    w("| Window | Sub-A | A-DK | Sub-B | PV三策略组合(不含微盘/Sub-D) |\n")
    w("|:-|------:|------:|------:|------:|\n")
    for row in rows:
        cells = []
        for col in PERFORMANCE_COLUMNS:
            cells.append(_format_performance_standard_window_cell(row["metrics"].get(col)))
        w(f"| {row['window']} | " + " | ".join(cells) + " |\n")
    w("\n")

def _monthly_returns_from_daily_window(ret_series, start_date, end_date):
    period = ret_series[(ret_series.index >= start_date) & (ret_series.index <= end_date)].dropna()
    if len(period) == 0:
        return pd.Series(dtype=float)
    return period.groupby(period.index.to_period("M")).apply(lambda x: (1 + x).prod() - 1)



def _apply_nav_axis_scale(ax, nav_series, spread_threshold=2.0):
    values = []
    for nav in nav_series.values():
        s = pd.to_numeric(pd.Series(nav), errors="coerce").dropna()
        s = s[s > 0]
        if len(s) > 0:
            values.append(s)
    if not values:
        ax.set_ylabel("NAV (start=1.0)", fontsize=11)
        return False
    all_values = pd.concat(values)
    min_nav = float(all_values.min())
    max_nav = float(all_values.max())
    spread = max_nav / min_nav if min_nav > 0 else 1.0
    if spread >= spread_threshold:
        ax.set_yscale("log")
        ax.set_ylabel("NAV (start=1.0, log scale)", fontsize=11)
        return True
    ax.set_ylabel("NAV (start=1.0)", fontsize=11)
    return False


def _render_nav_drawdown_chart(nav_series, chart_labels, colors, start_date, end_date):
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import PercentFormatter

    fig, (nav_ax, dd_ax) = plt.subplots(
        2, 1, figsize=(12, 8), sharex=True, height_ratios=[3, 1]
    )
    for name, nav in nav_series.items():
        nav_ax.plot(
            nav.index,
            nav.values,
            label=f"{chart_labels[name]}  ({(nav.iloc[-1]-1)*100:+.1f}%)",
            color=colors[name],
            linewidth=1.8,
        )
        drawdown = nav / nav.cummax() - 1.0
        dd_ax.plot(
            drawdown.index,
            drawdown.values,
            color=colors[name],
            linewidth=1.2,
            alpha=0.85,
        )
    nav_ax.axhline(y=1.0, color='gray', linestyle='--', linewidth=0.8, alpha=0.5)
    nav_ax.set_title(
        f"NAV Curve: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
        fontsize=14,
        fontweight='bold',
    )
    _apply_nav_axis_scale(nav_ax, nav_series)
    nav_ax.legend(loc='best', fontsize=10, framealpha=0.9)
    nav_ax.grid(True, alpha=0.3)
    dd_ax.axhline(y=0.0, color='gray', linestyle='--', linewidth=0.8, alpha=0.5)
    dd_ax.set_ylabel("Drawdown", fontsize=11)
    dd_ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    dd_ax.grid(True, alpha=0.3)
    dd_ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()

def beijing_now():
    from datetime import timezone
    utc_now = datetime.now(timezone.utc)
    bj_now = utc_now + timedelta(hours=8)
    return bj_now.replace(tzinfo=None)

def is_cn_market_open():
    bj = beijing_now()
    weekday = bj.weekday()
    if weekday >= 5:
        return False, bj
    morning_open = bj.replace(hour=9, minute=30, second=0)
    morning_close = bj.replace(hour=11, minute=30, second=0)
    afternoon_open = bj.replace(hour=13, minute=0, second=0)
    afternoon_close = bj.replace(hour=15, minute=0, second=0)
    return (morning_open <= bj <= morning_close) or (afternoon_open <= bj <= afternoon_close), bj

def _is_cn_unconfirmed_at(bj):
    if bj.weekday() >= 5:
        return False
    session_start = bj.replace(hour=9, minute=30, second=0, microsecond=0)
    session_close = bj.replace(hour=15, minute=0, second=0, microsecond=0)
    return session_start <= bj < session_close

def _is_cn_today_preclose_unconfirmed_at(bj):
    if bj.weekday() >= 5:
        return False
    session_close = bj.replace(hour=15, minute=0, second=0, microsecond=0)
    return bj < session_close

def _can_use_cn_realtime_snapshot_at(bj):
    if bj.weekday() >= 5:
        return False
    session_start = bj.replace(hour=9, minute=30, second=0, microsecond=0)
    return bj >= session_start

def is_cn_unconfirmed_intraday_snapshot():
    bj = beijing_now()
    return _is_cn_unconfirmed_at(bj), bj

def _cn_data_is_unconfirmed_today(data_date, bj_now=None):
    if bj_now is None:
        bj_now = beijing_now()
    cn_unconfirmed = _is_cn_today_preclose_unconfirmed_at(bj_now)
    if data_date is None:
        return False
    return cn_unconfirmed and pd.Timestamp(data_date).date() == bj_now.date()

def _drop_cn_unconfirmed_today(df):
    bj_now = beijing_now()
    cn_unconfirmed = _is_cn_today_preclose_unconfirmed_at(bj_now)
    if df is None or len(df) == 0 or not cn_unconfirmed:
        return df
    today = bj_now.date()
    keep = [pd.Timestamp(idx).date() != today for idx in df.index]
    return df.loc[keep]

def _cn_record_close_confirmed(rec_date, bj_now, rec_time_text=None):
    if rec_date is None:
        return False
    rec_day = pd.Timestamp(rec_date).date()
    today = bj_now.date()
    if rec_time_text and "09:30" in str(rec_time_text):
        if rec_day < today:
            return True
        if rec_day > today:
            return False
        return bj_now.hour > 9 or (bj_now.hour == 9 and bj_now.minute >= 35)
    if rec_day < today:
        return True
    if rec_day > today:
        return False
    return not _is_cn_unconfirmed_at(bj_now) and bj_now.hour >= 15

def _is_edt(d):
    if hasattr(d, 'date'):
        d = d.date()
    et = datetime(d.year, d.month, d.day, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    return et.utcoffset() == timedelta(hours=-4)

def is_us_market_open():
    bj = beijing_now()
    weekday = bj.weekday()
    if weekday == 5 and bj.hour >= 5:
        return False, bj
    if weekday == 6:
        return False, bj
    if weekday == 0 and bj.hour < 21:
        return False, bj
    edt = _is_edt(bj)
    if edt:
        open_h, open_m, close_h = 21, 30, 4
    else:
        open_h, open_m, close_h = 22, 30, 5
    hour = bj.hour
    if hour >= open_h or hour < close_h:
        return True, bj
    return False, bj

def beijing_time_str(date, market="CN", event="close"):
    if market == "CN":
        if event == "open":
            return f"{date.strftime('%Y-%m-%d')} 09:30 北京时间"
        return f"{date.strftime('%Y-%m-%d')} 15:00 北京时间"
    else:
        edt = _is_edt(date)
        if event == "open":
            bj_hour = "21:30" if edt else "22:30"
            return f"{date.strftime('%Y-%m-%d')} {bj_hour} 北京时间"
        else:
            bj_hour = "04:00" if edt else "05:00"
            next_day = date + timedelta(days=1)
            return f"{next_day.strftime('%Y-%m-%d')} {bj_hour} 北京时间"

def _next_biz_day(date):
    d = date + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d

def _coerce_session_index(schedule):
    if schedule is None:
        return None
    if isinstance(schedule, pd.Series):
        idx = schedule.dropna().index
    elif isinstance(schedule, pd.DataFrame):
        idx = schedule.dropna(how="all").index
    elif isinstance(schedule, dict):
        idx = pd.DatetimeIndex([])
        for value in schedule.values():
            cur = _coerce_session_index(value)
            if cur is not None and len(cur) > 0:
                idx = idx.union(cur)
    else:
        try:
            idx = pd.DatetimeIndex(pd.to_datetime(schedule))
        except Exception:
            return None
    idx = pd.DatetimeIndex(pd.to_datetime(idx)).sort_values().unique()
    return idx if len(idx) > 0 else None

def _next_session_day(signal_date, schedule=None):
    session_index = _coerce_session_index(schedule)
    signal_ts = pd.Timestamp(signal_date).normalize()
    if session_index is not None:
        future = session_index[session_index > signal_ts]
        if len(future) > 0:
            return pd.Timestamp(future[0])
    return pd.Timestamp(_next_biz_day(signal_ts))

def us_exec_time_str(signal_date, schedule=None):
    exec_day = _next_session_day(signal_date, schedule)
    return beijing_time_str(exec_day, "US", "open")

def _has_execution_happened(signal_date, market, bj_now, schedule=None):
    exec_day = _next_session_day(signal_date, schedule)
    exec_day_date = exec_day.date() if hasattr(exec_day, 'date') else exec_day
    today_date = bj_now.date()
    if today_date > exec_day_date:
        return True
    elif today_date == exec_day_date:
        if market == "CN":
            return bj_now.hour > 9 or (bj_now.hour == 9 and bj_now.minute >= 35)
        else:
            open_h = 21 if _is_edt(exec_day) else 22
            return bj_now.hour > open_h or (bj_now.hour == open_h and bj_now.minute >= 35)
    return False

def _us_open_on_record_date_happened(record_date, bj_now):
    if record_date is None:
        return False
    rec_ts = pd.Timestamp(record_date)
    rec_day = rec_ts.date()
    today = bj_now.date()
    if today > rec_day:
        return True
    if today < rec_day:
        return False
    open_h = 21 if _is_edt(rec_ts) else 22
    return bj_now.hour > open_h or (bj_now.hour == open_h and bj_now.minute >= 35)

def _subb_turnover_execution_status_text(
    turnover,
    rebalanced,
    execution_happened,
    min_turnover=US_ROT_MIN_TURNOVER,
):
    threshold = max(float(min_turnover), 1e-9)
    if rebalanced:
        if execution_happened:
            return f" 🟢 超{min_turnover:.0%}阈值，已调仓\n"
        return f" 🟢 超{min_turnover:.0%}阈值，等待执行\n"
    if float(turnover or 0.0) > threshold:
        return f" 🟢 超{min_turnover:.0%}阈值，**应调仓**\n"
    return f" ❌ 低于{min_turnover:.0%}阈值，维持原仓位\n"

def _is_tentative_subb_date(date):
    rec_date = pd.Timestamp(date)
    now_yr, now_wk, _ = beijing_now().isocalendar()
    rec_yr, rec_wk, _ = rec_date.isocalendar()
    return (rec_yr, rec_wk) == (now_yr, now_wk) and rec_date.dayofweek < 3


def _filter_confirmed_records(records, bj_now=None, us_schedule=None):
    """非实时输出只保留已确认/已执行记录。"""
    if bj_now is None:
        bj_now = beijing_now()
    confirmed = []
    for rec in records:
        strat = rec.get("策略", "")
        rec_date = rec.get("日期")
        rec_time = rec.get("北京时间", "")
        if strat in {"Sub-A", "Sub-A-DK"} and not _cn_record_close_confirmed(rec_date, bj_now, rec_time):
            continue
        if "Sub-B" in strat:
            is_execution_day_record = rec.get("日期口径") == "execution_day" or strat == "Sub-B VolReg"
            if is_execution_day_record:
                if not _us_open_on_record_date_happened(rec_date, bj_now):
                    continue
            elif not _has_execution_happened(rec_date, "US", bj_now, us_schedule):
                continue
        confirmed.append(rec)
    return confirmed

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
           "半": 0.5}

def _parse_cn_num(s):
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    if '十' in s:
        parts = s.split('十')
        tens = _CN_NUM.get(parts[0], 1) if parts[0] else 1
        ones = _CN_NUM.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    return None

def parse_date_range(text):
    now = pd.Timestamp(beijing_now())
    _DAY_SUF = r'[日号]?'  # 匹配「日」或「号」或无后缀
    # ---- 含「日/号」的完整日期: YYYY年M月D日 到 YYYY年M月D日 ----
    m = re.search(
        r'(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})\s*' + _DAY_SUF + r'\s*[到至—\-~]+\s*(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})\s*' + _DAY_SUF,
        text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
        end = pd.Timestamp(f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}")
        return start, end
    # ---- YYYY年M月D日/号 到 M月D日/号 (年份只在第一个日期) ----
    m = re.search(
        r'(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})\s*' + _DAY_SUF + r'\s*[到至—\-~]+\s*(\d{1,2})[-月/.](\d{1,2})\s*' + _DAY_SUF,
        text)
    if m:
        yr = int(m.group(1))
        start = pd.Timestamp(f"{yr}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
        end = pd.Timestamp(f"{yr}-{int(m.group(4)):02d}-{int(m.group(5)):02d}")
        return start, end
    # ---- M月D日/号 到 M月D日/号 (无年份，默认当前年) ----
    m = re.search(
        r'(\d{1,2})[-月/.](\d{1,2})\s*' + _DAY_SUF + r'\s*[到至—\-~]+\s*(\d{1,2})[-月/.](\d{1,2})\s*' + _DAY_SUF,
        text)
    if m:
        yr = now.year
        start = pd.Timestamp(f"{yr}-{int(m.group(1)):02d}-{int(m.group(2)):02d}")
        end = pd.Timestamp(f"{yr}-{int(m.group(3)):02d}-{int(m.group(4)):02d}")
        # 跨年区间: 开始在上一年，结束保留当前年。
        if start > end:
            start = pd.Timestamp(f"{yr-1}-{int(m.group(1)):02d}-{int(m.group(2)):02d}")
        # 非跨年但整体仍在未来时，解释为上一年的同一区间。
        elif end > now.normalize():
            start = pd.Timestamp(f"{yr-1}-{int(m.group(1)):02d}-{int(m.group(2)):02d}")
            end = pd.Timestamp(f"{yr-1}-{int(m.group(3)):02d}-{int(m.group(4)):02d}")
        return start, end
    # ---- YYYY年M月D日/号至今 ----
    m = re.search(r'(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})\s*' + _DAY_SUF + r'\s*至今', text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
        return start, now
    # ---- M月D日/号至今 (无年份) ----
    m = re.search(r'(\d{1,2})[-月/.](\d{1,2})\s*' + _DAY_SUF + r'\s*至今', text)
    if m:
        yr = now.year
        start = pd.Timestamp(f"{yr}-{int(m.group(1)):02d}-{int(m.group(2)):02d}")
        if start > now:
            start = pd.Timestamp(f"{yr-1}-{int(m.group(1)):02d}-{int(m.group(2)):02d}")
        return start, now
    # ---- 以下为原有的年月级别匹配 ----
    m = re.search(r'(\d{4})[-年/.]?(\d{1,2})[-月]?\s*至今', text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-01")
        return start, now
    m = re.search(r'(\d{4})\s*年?\s*至今', text)
    if m:
        return pd.Timestamp(f"{m.group(1)}-01-01"), now
    m = re.search(r'(\d{4})[-年/.](\d{1,2})[-月]?\s*[到至—\-~]+\s*(\d{4})[-年/.](\d{1,2})', text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{int(m.group(2)):02d}-01")
        end = pd.Timestamp(f"{m.group(3)}-{int(m.group(4)):02d}-01") + pd.offsets.MonthEnd(0)
        return start, end
    m = re.search(r'(\d{4})[-年/.](\d{1,2})[-月]?\s*[到至—\-~]+\s*(\d{1,2})', text)
    if m:
        yr = int(m.group(1))
        start = pd.Timestamp(f"{yr}-{int(m.group(2)):02d}-01")
        end = pd.Timestamp(f"{yr}-{int(m.group(3)):02d}-01") + pd.offsets.MonthEnd(0)
        return start, end
    m = re.search(r'(\d{1,2})\s*月\s*[到至\-~]+\s*(\d{1,2})\s*月', text)
    if m:
        yr = now.year
        start = pd.Timestamp(f"{yr}-{int(m.group(1)):02d}-01")
        end = pd.Timestamp(f"{yr}-{int(m.group(2)):02d}-01") + pd.offsets.MonthEnd(0)
        if start > end or end > now.normalize():
            start = pd.Timestamp(f"{yr-1}-{int(m.group(1)):02d}-01")
            end = pd.Timestamp(f"{yr-1}-{int(m.group(2)):02d}-01") + pd.offsets.MonthEnd(0)
        return start, end
    m = re.search(r'(\d{4})(\d{2})\s*[-到至~]+\s*(\d{4})(\d{2})', text)
    if m:
        start = pd.Timestamp(f"{m.group(1)}-{m.group(2)}-01")
        end = pd.Timestamp(f"{m.group(3)}-{m.group(4)}-01") + pd.offsets.MonthEnd(0)
        return start, end
    m = re.search(r'(\d{4})\s*年?\s*[到至—\-~]+\s*(\d{4})\s*年?', text)
    if m:
        return pd.Timestamp(f"{m.group(1)}-01-01"), pd.Timestamp(f"{m.group(2)}-12-31")
    m = re.search(r'(?:最近|过去|近)\s*([一二两三四五六七八九十\d半]+)\s*个?\s*年', text)
    if m:
        n = _parse_cn_num(m.group(1))
        if n is not None:
            if isinstance(n, float):
                return now - pd.DateOffset(months=int(n * 12)), now
            return now - pd.DateOffset(years=int(n)), now
    m = re.search(r'(?:最近|过去|近)\s*([一二两三四五六七八九十\d半]+)\s*个?\s*月', text)
    if m:
        n = _parse_cn_num(m.group(1))
        if n is not None:
            return now - pd.DateOffset(months=int(n if n >= 1 else 1)), now
    if '今年' in text:
        return pd.Timestamp(f"{now.year}-01-01"), now
    if '去年' in text:
        yr = now.year - 1
        return pd.Timestamp(f"{yr}-01-01"), pd.Timestamp(f"{yr}-12-31")
    if '前年' in text:
        yr = now.year - 2
        return pd.Timestamp(f"{yr}-01-01"), pd.Timestamp(f"{yr}-12-31")
    m = re.search(r'(\d{4})[-年/.](\d{1,2})\s*月?份?', text)
    if m:
        yr = int(m.group(1))
        mon = int(m.group(2))
        if 1 <= mon <= 12:
            start = pd.Timestamp(f"{yr}-{mon:02d}-01")
            end = start + pd.offsets.MonthEnd(0)
            return start, end
    m = re.search(r'(\d{4})\s*年?\s*全?年?', text)
    if m:
        yr = int(m.group(1))
        if 2000 <= yr <= 2099:
            return pd.Timestamp(f"{yr}-01-01"), pd.Timestamp(f"{yr}-12-31")
    return None, None

def parse_all_date_ranges(text):
    parts = re.split(r'以及|、|；|;\s*', text)
    if len(parts) == 1:
        parts = re.split(r'(?<=[年月日\d])\s*和\s*(?=[近最过])', text)
    results = []
    seen = set()
    for part in parts:
        part = part.strip()
        if not part:
            continue
        start, end = parse_date_range(part)
        if start is not None:
            key = (start.date(), end.date())
            if key not in seen:
                results.append((start, end))
                seen.add(key)
    if not results:
        start, end = parse_date_range(text)
        if start is not None:
            results.append((start, end))
    results.sort(key=lambda x: (x[1] - x[0]).days)
    return results

CAPITAL_CONFIG_START = "<!--CAPITAL_CONFIG"
CAPITAL_CONFIG_END = "CAPITAL_CONFIG-->"
# STRATEGY_WEIGHTS 已从 strategy_config 导入

def _scan_capital_config(chat):
    config = None
    for m in chat:
        t = m.text
        while True:
            s = t.find(CAPITAL_CONFIG_START)
            if s < 0:
                break
            e = t.find(CAPITAL_CONFIG_END, s)
            if e < 0:
                break
            raw = t[s + len(CAPITAL_CONFIG_START):e].strip()
            try:
                config = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass
            t = t[e + len(CAPITAL_CONFIG_END):]
    return config

def _build_capital_marker(config):
    return f"\n{CAPITAL_CONFIG_START}\n{json.dumps(config, ensure_ascii=False)}\n{CAPITAL_CONFIG_END}\n"

POSITION_CONFIG_START = "<!--POSITION_CONFIG"
POSITION_CONFIG_END = "POSITION_CONFIG-->"

def _scan_position_config(chat):
    config = None
    for m in chat:
        t = m.text
        while True:
            s = t.find(POSITION_CONFIG_START)
            if s < 0:
                break
            e = t.find(POSITION_CONFIG_END, s)
            if e < 0:
                break
            raw = t[s + len(POSITION_CONFIG_START):e].strip()
            try:
                config = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass
            t = t[e + len(POSITION_CONFIG_END):]
    return config

def _build_position_marker(config):
    return f"\n{POSITION_CONFIG_START}\n{json.dumps(config, ensure_ascii=False)}\n{POSITION_CONFIG_END}\n"

def _pos_entry_value(val, price):
    """Get current market value of a position entry (amount-based or shares-based)."""
    if isinstance(val, dict) and 'amount' in val:
        return float(val['amount'])
    shares = int(float(val)) if isinstance(val, (int, float)) else 0
    return shares * price if price else 0

def _pos_entry_is_nonzero(val):
    if isinstance(val, dict) and 'amount' in val:
        return abs(float(val['amount'])) > 0
    return isinstance(val, (int, float)) and abs(float(val)) > 0

def _pos_entry_needs_price_for_value(val):
    return not (isinstance(val, dict) and 'amount' in val)

def _normalize_subb_position_keys(pos):
    out = {}
    for key, value in (pos or {}).items():
        live = _ROT_PROXY_TO_LIVE.get(str(key).upper(), str(key).upper())
        if live in out and isinstance(out[live], (int, float)) and isinstance(value, (int, float)):
            out[live] += value
        elif (
            live in out
            and isinstance(out[live], dict)
            and isinstance(value, dict)
            and "amount" in out[live]
            and "amount" in value
        ):
            out[live] = dict(out[live], amount=float(out[live]["amount"]) + float(value["amount"]))
        elif live in out:
            raise poe.BotError(
                f"Sub-B持仓 {live} 同时存在股数和金额两种口径，请统一为一种。"
            )
        else:
            out[live] = value
    return out

def _subb_target_shares(target_value, weight, price, min_weight=0.005):
    if not isinstance(weight, (int, float)) or weight <= min_weight:
        return 0
    if price and price > 0:
        return int(float(target_value) * float(weight) / price)
    return None

def _subb_position_adjustment_target_value(position_config, live_prices, capital=None):
    """Choose a reliable Sub-B adjustment base without partial stale-price valuation."""
    position_config = _normalize_subb_position_keys(position_config)
    live_prices = live_prices or {}
    held_etfs = sorted(etf for etf, raw_pos in position_config.items() if _pos_entry_is_nonzero(raw_pos))
    missing_prices = [
        etf for etf in held_etfs
        if _pos_entry_needs_price_for_value(position_config.get(etf)) and etf not in live_prices
    ]
    if missing_prices:
        if capital and capital > 0:
            return float(capital), missing_prices, "capital"
        return None, missing_prices, "unavailable"
    total_value = sum(_pos_entry_value(position_config.get(etf, 0), live_prices.get(etf, 0)) for etf in held_etfs)
    if total_value > 0:
        return float(total_value), [], "positions"
    if capital and capital > 0:
        return float(capital), [], "capital"
    return None, [], "unavailable"

def _pos_entry_shares(val, price):
    """Get equivalent shares of a position entry (converts amount to shares if needed)."""
    if isinstance(val, dict) and 'amount' in val:
        return int(float(val['amount']) / price) if price and price > 0 else 0
    return int(float(val)) if isinstance(val, (int, float)) else 0

def _calc_quantities(capital, weights, prices):
    result = {}
    for etf, w in weights.items():
        if not isinstance(w, (int, float)) or w < 0.005:
            continue
        amount = capital * w
        price = prices.get(etf)
        if price and price > 0:
            qty = int(amount / price)
            result[etf] = {"weight": w, "amount": round(amount, 2),
                           "price": round(price, 2), "qty": qty}
        else:
            result[etf] = {"weight": w, "amount": round(amount, 2),
                           "price": None, "qty": None}
    return result

def _position_csv_column_map(columns):
    col_map = {}
    for c in columns:
        cl = str(c).strip().lower()
        if cl in ('策略', 'strategy', 'sub', '子策略'):
            col_map['strategy'] = c
        elif cl in ('etf', 'ticker', '代码', '标的', 'code', 'symbol'):
            col_map['etf'] = c
        elif cl in ('数量', 'shares', 'qty', '股数', '持仓', 'quantity'):
            col_map['shares'] = c
        elif cl in ('amount', '金额', '市值', 'market_value'):
            col_map['amount'] = c
    return col_map

def _position_csv_entry(row, col_map):
    has_shares = 'shares' in col_map and pd.notna(row[col_map['shares']])
    has_amount = 'amount' in col_map and pd.notna(row[col_map['amount']])
    if has_shares and has_amount:
        raise poe.BotError("CSV同一行同时存在数量和金额，请只保留一种持仓口径。")
    if has_amount:
        return {"amount": float(row[col_map['amount']])}
    if has_shares:
        return int(float(row[col_map['shares']]))
    raise poe.BotError("CSV持仓行缺少数量或金额。")

def _parse_json_from_response(text, required_fields=None):
    m = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        js = m.group(1).strip()
    else:
        m = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if not m:
            raise ValueError("No JSON found")
        js = m.group(0).strip()
    parsed = json.loads(js)
    if required_fields:
        missing = set(required_fields) - set(parsed.keys())
        if missing:
            raise ValueError(f"Missing: {', '.join(missing)}")
    return parsed

def _call_llm_text_or_raise(prompt, context):
    try:
        response = poe.call("Grok-4.1-Fast-Non-Reasoning", prompt)
        return response.text
    except Exception as exc:
        raise poe.BotError(f"{context} LLM解析失败: {_short_error(exc)}") from exc

def _parse_number_with_unit(text):
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(百万|萬|万|千|k|K)?", str(text))
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2) or ""
    if unit in ("百万",):
        value *= 1_000_000
    elif unit in ("萬", "万"):
        value *= 10_000
    elif unit in ("千", "k", "K"):
        value *= 1_000
    return value

def _parse_simple_capital_config(text):
    raw = str(text or "")
    compact = raw.replace("：", ":")
    parsed = {}
    for strategy in ("Sub-A-DK", "Sub-A", "Sub-B"):
        m = re.search(rf"{re.escape(strategy)}\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?\s*(?:百万|萬|万|千|k|K)?)", compact, re.I)
        if m:
            amount = _parse_number_with_unit(m.group(1))
            if amount and amount > 0:
                parsed[strategy] = amount
    if parsed:
        return parsed

    usd = None
    cn = None
    m = re.search(r"(?:美元|USD|\$)\s*([0-9]+(?:\.[0-9]+)?\s*(?:百万|萬|万|千|k|K)?)", compact, re.I)
    if not m:
        m = re.search(r"([0-9]+(?:\.[0-9]+)?\s*(?:百万|萬|万|千|k|K)?)\s*(?:美元|USD)", compact, re.I)
    if m:
        usd = _parse_number_with_unit(m.group(1))
    m = re.search(r"(?:人民币|RMB|CNY|A股)\s*([0-9]+(?:\.[0-9]+)?\s*(?:百万|萬|万|千|k|K)?)", compact, re.I)
    if not m:
        m = re.search(r"([0-9]+(?:\.[0-9]+)?\s*(?:百万|萬|万|千|k|K)?)\s*(?:人民币|RMB|CNY)", compact, re.I)
    if m:
        cn = _parse_number_with_unit(m.group(1))
    if cn and cn > 0:
        parsed["Sub-A"] = cn * 0.5
        parsed["Sub-A-DK"] = cn * 0.5
    if usd and usd > 0:
        parsed["Sub-B"] = usd
    return parsed or None

def _parse_simple_position_config(text):
    raw = str(text or "")
    compact = raw.replace("：", ":")
    parsed = {}
    strategy = next((s for s in ("Sub-A-DK", "Sub-A", "Sub-B") if re.search(re.escape(s), compact, re.I)), None)
    if not strategy:
        return None
    body = compact[compact.lower().find(strategy.lower()) + len(strategy):]
    if strategy == "Sub-B":
        items = {}
        for ticker, qty in re.findall(r"\b([A-Z]{2,6}(?:-[A-Z]+)?)\b\s*([0-9]+(?:\.[0-9]+)?)\s*(?:股|shares?)?", body, re.I):
            if ticker.upper() not in {"SUB", "USD", "RMB", "CNY"}:
                items[ticker.upper()] = int(float(qty))
        if items:
            parsed[strategy] = items
    elif strategy == "Sub-A":
        name_to_code = {
            "红利低波100": "1.930955",
            "红利低波": "1.930955",
            "创业板": "0.399006",
            "上证50": "1.000016",
            "中证1000": "1.000852",
            "中证500": "1.000905",
            "国债": "1.H11077",
            "10Y": "1.H11077",
        }
        items = {}
        for name, code in name_to_code.items():
            m = re.search(rf"{re.escape(name)}\s*([0-9]+(?:\.[0-9]+)?\s*(?:百万|萬|万|千|k|K)?)", body, re.I)
            if m:
                amount = _parse_number_with_unit(m.group(1))
                if amount and amount > 0:
                    items[code] = {"amount": amount}
        if items:
            parsed[strategy] = items
    elif strategy == "Sub-A-DK":
        name_to_key = {
            "创业板": "创业板",
            "中证1000": "中证1000",
            "上证50": "上证50",
            "沪深300": "沪深300",
            "中证500": "中证500",
        }
        items = {}
        for side, prefix in (("做多", "做多_"), ("做空", "做空_")):
            for name, key in name_to_key.items():
                m = re.search(rf"{side}\s*{re.escape(name)}\s*([0-9]+(?:\.[0-9]+)?\s*(?:百万|萬|万|千|k|K)?)", body)
                if not m:
                    m = re.search(rf"{side}\s*([0-9]+(?:\.[0-9]+)?\s*(?:百万|萬|万|千|k|K)?)\s*{re.escape(name)}", body)
                if m:
                    amount = _parse_number_with_unit(m.group(1))
                    if amount and amount > 0:
                        items[prefix + key] = {"amount": amount}
        if items:
            parsed[strategy] = items
    return parsed or None

def _lookup_next_open(ticker, signal_date, us_open, us_close_df=None):
    """查找信号日T之后第一个交易日(T+1)的开盘价。
    us_open: dict {ticker: Series(date→open_price)}
    回退: 若无T+1开盘价, 返回None。
    对于实盘ETF, 先查实盘ticker, 再查proxy。"""
    if us_open is None:
        return None
    # 尝试实盘ETF和proxy
    candidates = [ticker]
    if ticker in PROD_PORTFOLIO:
        candidates.append(PROD_PORTFOLIO[ticker].get("proxy", ticker))
    if ticker in US_ROT_ASSETS:
        candidates.append(US_ROT_ASSETS[ticker].get("proxy", ticker))
    # 反向: proxy → live
    live = _ROT_PROXY_TO_LIVE.get(ticker)
    if live:
        candidates = [live] + candidates
    for t in candidates:
        if t not in us_open:
            continue
        s = us_open[t]
        future = s[s.index > signal_date]
        if len(future) > 0:
            return future.iloc[0]
    return None

def _lookup_open_on_date(ticker, date, us_open):
    """查找指定美股交易日自身的开盘价，不推进到下一交易日。"""
    if us_open is None:
        return None
    candidates = [ticker]
    if ticker in PROD_PORTFOLIO:
        candidates.append(PROD_PORTFOLIO[ticker].get("proxy", ticker))
    if ticker in US_ROT_ASSETS:
        candidates.append(US_ROT_ASSETS[ticker].get("proxy", ticker))
    live = _ROT_PROXY_TO_LIVE.get(ticker)
    if live:
        candidates = [live] + candidates
    target = pd.Timestamp(date).normalize()
    for t in candidates:
        if t not in us_open:
            continue
        s = us_open[t]
        idx = pd.DatetimeIndex(pd.to_datetime(s.index)).normalize()
        matches = s.iloc[np.where(idx == target)[0]]
        if len(matches) > 0:
            return matches.iloc[0]
    return None


def _rebalance_price_text(price, label):
    return f"${price:.2f}{label}" if price is not None and not pd.isna(price) else ""

def extract_cn_rebalances(cn_result, cn_close, strategy_name="Sub-A", names=None):
    if names is None:
        names = CN_NAMES
    records = []
    prev_holding = None
    prev_weight = None
    has_weight = "weight" in cn_result.columns
    for i in range(len(cn_result)):
        holding = cn_result["holding"].iloc[i]
        date = cn_result.index[i]
        weight = cn_result["weight"].iloc[i] if has_weight else None
        if prev_holding is not None and holding != prev_holding:
            price_sell = cn_close.loc[date, prev_holding] if prev_holding != "cash" and prev_holding in cn_close.columns else None
            price_buy = cn_close.loc[date, holding] if holding != "cash" and holding in cn_close.columns else None
            records.append({
                "日期": date.strftime("%Y-%m-%d"),
                "北京时间": beijing_time_str(date, "CN"),
                "策略": strategy_name,
                "卖出": names.get(prev_holding, prev_holding),
                "卖出价格": price_sell,
                "买入": names.get(holding, holding),
                "买入价格": price_buy,
            })
        elif has_weight and prev_weight is not None and weight is not None and abs(weight - prev_weight) > 0.001:
            h_name = names.get(holding, holding)
            # Keep the record aligned with the close-to-close accounting row.
            records.append({
                "日期": date.strftime("%Y-%m-%d"),
                "北京时间": beijing_time_str(date, "CN", "close"),
                "策略": strategy_name,
                "卖出": f"杠杆 {prev_weight:.2f}x",
                "卖出价格": None,
                "买入": f"杠杆 {weight:.2f}x ({h_name})",
                "买入价格": None,
            })
        prev_holding = holding
        prev_weight = weight
    return records


def extract_v78_newa_rebalances(new_result, cn_close=None, since_date=None):
    records = []
    if new_result is None or len(new_result) == 0:
        return records
    for dt, row in new_result.iterrows():
        if since_date is not None and pd.Timestamp(dt) < pd.Timestamp(since_date):
            continue
        if not bool(row.get("is_signal", False)):
            continue
        old_h = str(row.get("holding", "cash") or "cash")
        new_h = str(row.get("target", old_h) or old_h)
        try:
            old_w = float(row.get("weight", 0.0) or 0.0)
        except Exception:
            old_w = 0.0
        try:
            new_w = float(row.get("target_weight", old_w) or old_w)
        except Exception:
            new_w = old_w
        if old_h == new_h and abs(old_w - new_w) <= 1e-4:
            continue
        sell_price = cn_close.loc[dt, old_h] if cn_close is not None and old_h != "cash" and dt in cn_close.index and old_h in cn_close.columns else None
        buy_price = cn_close.loc[dt, new_h] if cn_close is not None and new_h != "cash" and dt in cn_close.index and new_h in cn_close.columns else None
        records.append({
            "日期": pd.Timestamp(dt).strftime("%Y-%m-%d"),
            "北京时间": beijing_time_str(dt, "CN"),
            "策略": f"{V78_SUBA_NEW_LABEL} ({V78_SUBA_NEW_TV10_WEIGHT:.0%})",
            "卖出": f"{CN_NAMES.get(old_h, old_h)} {old_w:.2f}x" if old_w > 1e-12 else "—",
            "卖出价格": sell_price,
            "买入": f"{CN_NAMES.get(new_h, new_h)} {new_w:.2f}x" if new_w > 1e-12 else "Cash",
            "买入价格": buy_price,
        })
    records.sort(key=lambda item: item.get("日期", ""))
    return records


def extract_v78_suba_rebalances(v78_suba_result, cn_close=None, since_date=None):
    records = []
    v77_component = v78_suba_result.attrs.get("v78_suba_v77")
    if v77_component is not None and len(v77_component) > 0:
        component_records = extract_cn_rebalances(
            v77_component,
            cn_close,
            strategy_name=f"V7.7A ({V78_SUBA_V77_WEIGHT:.0%})",
        )
        for record in component_records:
            record["策略"] = f"V7.7A ({V78_SUBA_V77_WEIGHT:.0%})"
            if since_date is not None:
                try:
                    if pd.Timestamp(record.get("日期")) < pd.Timestamp(since_date):
                        continue
                except Exception:
                    pass
            records.append(record)
    records.extend(
        extract_v78_newa_rebalances(
            v78_suba_result.attrs.get("v78_suba_new"),
            cn_close=cn_close,
            since_date=since_date,
        )
    )
    records.sort(key=lambda item: item.get("日期", ""))
    return records


def _dk_holding_prices(holding, cn_dk_close, date):
    """从DK持仓名(如 'HS300/ZZ500_1')中提取涉及指数的收盘价。"""
    if cn_dk_close is None or date not in cn_dk_close.index:
        return None
    # 配对名映射: short_name -> DK列名
    _idx_map = {v['col'].replace('DK_', ''): v['col'] for k, v in CN_DK_INDICES.items()}
    _idx_map.update({k: v['col'] for k, v in CN_DK_INDICES.items()})
    # 解析持仓名: "HS300/ZZ500_1" → ["HS300", "ZZ500"]
    h = str(holding)
    # 去除方向后缀 _1 / _-1
    import re as _re
    h_clean = _re.sub(r'_-?\d+$', '', h)
    parts = [p.strip() for p in h_clean.split('/') if p.strip()]
    prices = []
    for p in parts:
        col = _idx_map.get(p)
        if col and col in cn_dk_close.columns:
            val = cn_dk_close.loc[date, col]
            if not pd.isna(val):
                prices.append(f"{p} {val:.2f}")
    return "; ".join(prices) if prices else None

def parse_dk_holding(holding):
    """P1-2修复: 解析DK持仓编码 (如 'HS300/ZZ500_1') 为结构化信息。
    返回 dict{pair_a, pair_b, direction, long_leg, short_leg} 或 None。"""
    if not holding or str(holding) in ('none_0', 'none', 'None'):
        return None
    h = str(holding)
    try:
        pair_part, dir_part = h.rsplit('_', 1)
        direction = int(dir_part)
    except (ValueError, IndexError):
        return None
    parts = pair_part.split('/')
    if len(parts) != 2:
        return None
    a, b = parts[0], parts[1]
    if direction == 1:
        long_leg, short_leg = a, b
    elif direction == -1:
        long_leg, short_leg = b, a
    else:
        return None
    return {
        'pair_a': a, 'pair_b': b, 'direction': direction,
        'long_leg': long_leg, 'short_leg': short_leg,
    }

def _dk_leg_name(short_name):
    """将DK短名(如'HS300')转为中文显示名，优先用CN_DK_INDEX_NAMES，回退到CN_DK_NAMES。"""
    if short_name in CN_DK_INDEX_NAMES:
        return CN_DK_INDEX_NAMES[short_name]
    col = f"DK_{short_name}"
    if col in CN_DK_NAMES:
        return CN_DK_NAMES[col]
    return short_name

def _dk_pair_display(pair):
    return "/".join(_dk_leg_name(p) for p in str(pair).split("/")) if pair != "none" else "none"


def _dk_top_pair_whitelist_warning(pair, label="Top-1"):
    return ""


def _dk_volume_warning_text(active, label, ma, days):
    """生成ADK成交额警示文案；DK成交额只提示，不改变仓位或净值。"""
    if active:
        return (
            f"🔴 **成交额警示触发:** {label}成交额连续低于MA{ma}满{days}天；"
            "只进警示板，不改变ADK仓位、收益和净值曲线。\n"
        )
    return (
        f"🟢 **成交额警示未触发:** {label}成交额未连续低于MA{ma}满{days}天；"
        "仅提示，不改变ADK仓位。\n"
    )

def _dk_pos_str(holding_str):
    if holding_str is not None and "|" in str(holding_str):
        parts = []
        for item in str(holding_str).split("|"):
            label, sep, raw_holding = item.partition(":")
            formatted = _dk_pos_str(raw_holding if sep else item)
            if formatted == "\u7a7a\u4ed3":
                continue
            prefix = f"{label}: " if sep else ""
            parts.append(f"{prefix}{formatted}")
        if parts:
            return " | ".join(parts)
    info = parse_dk_holding(holding_str)
    if not info:
        return "\u7a7a\u4ed3"
    return f"\u505a\u591a {_dk_leg_name(info['long_leg'])} / \u505a\u7a7a {_dk_leg_name(info['short_leg'])}"


def _series_value_at(series, date, pos):
    if series is None or len(series) == 0:
        return np.nan
    try:
        if date in series.index:
            val = series.loc[date]
            if isinstance(val, pd.Series):
                val = val.iloc[-1]
            return float(val)
    except Exception:
        pass
    try:
        if -len(series) <= pos < len(series):
            return float(series.iloc[pos])
    except Exception:
        pass
    return np.nan

def _suba_abs_mom_pass(abs_val):
    return pd.notna(abs_val) and float(abs_val) > CN_ABS_MOM_THRESHOLD

def _suba_filter_status(bm, r2_val, abs_val):
    if pd.notna(bm) and float(bm) <= 0:
        return "动量≤0 ⛔"
    if pd.isna(r2_val):
        return "R²=N/A ❌"
    if float(r2_val) < CN_R2_THRESHOLD:
        return f"R²={float(r2_val):.3f} ❌"
    if pd.isna(abs_val):
        return f"{CN_ABS_MOM_DAY}日动量=N/A ❌"
    if float(abs_val) <= CN_ABS_MOM_THRESHOLD:
        return f"{CN_ABS_MOM_DAY}日动量={float(abs_val):+.1%} ≤ {CN_ABS_MOM_THRESHOLD:.0%} ❌"
    return f"R²={float(r2_val):.3f} ✅ / {CN_ABS_MOM_DAY}日动量={float(abs_val):+.1%} ✅"

def _format_suba_abs_mom(abs_val):
    return f"{float(abs_val):+.1%}" if pd.notna(abs_val) else "—"

def _build_suba_momentum_rank_rows(cn_result, bias_mom, r2, codes,
                                   abs_mom=None, current_idx=-1, effective_cutoff_idx=None):
    if cn_result is None or len(cn_result) == 0:
        return [], {
            "effective_date": None,
            "current_date": None,
            "effective_holding": "cash",
        }

    n = len(cn_result)
    current_pos = current_idx if current_idx >= 0 else n + current_idx
    current_pos = int(np.clip(current_pos, 0, n - 1))
    if effective_cutoff_idx is None:
        cutoff_pos = current_pos
    else:
        cutoff_pos = effective_cutoff_idx if effective_cutoff_idx >= 0 else n + effective_cutoff_idx
        cutoff_pos = int(np.clip(cutoff_pos, 0, current_pos))

    if "holding" in cn_result.columns:
        holding_s = cn_result["holding"].fillna("cash").astype(str)
        effective_holding = holding_s.iloc[cutoff_pos]
        effective_pos = cutoff_pos
        while effective_pos > 0 and holding_s.iloc[effective_pos - 1] == effective_holding:
            effective_pos -= 1
    else:
        effective_pos = cutoff_pos

    current_date = cn_result.index[current_pos]
    effective_date = cn_result.index[effective_pos]
    effective_holding = (
        cn_result["holding"].iloc[effective_pos]
        if "holding" in cn_result.columns
        else "cash"
    )

    rows = []
    for code in codes:
        bm_current = _series_value_at(bias_mom.get(code), current_date, current_pos)
        if np.isnan(bm_current):
            continue
        r2_current = _series_value_at(r2.get(code), current_date, current_pos)
        bm_effective = _series_value_at(bias_mom.get(code), effective_date, effective_pos)
        r2_effective = _series_value_at(r2.get(code), effective_date, effective_pos)
        abs_current = _series_value_at(abs_mom.get(code), current_date, current_pos) if abs_mom else np.nan
        abs_effective = _series_value_at(abs_mom.get(code), effective_date, effective_pos) if abs_mom else np.nan
        status = _suba_filter_status(bm_current, r2_current, abs_current)
        rows.append({
            "code": code,
            "asset_name": CN_NAMES.get(code, code),
            "marker": "当前已生效" if code == effective_holding else "",
            "effective_momentum": bm_effective,
            "current_momentum": bm_current,
            "effective_r2": r2_effective,
            "current_r2": r2_current,
            "effective_abs_mom": abs_effective,
            "current_abs_mom": abs_current,
            "status": status,
        })
    rows.sort(key=lambda row: row["current_momentum"], reverse=True)
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows, {
        "effective_date": effective_date,
        "current_date": current_date,
        "effective_holding": effective_holding,
    }

def _v78_suba_position_text(row, mode="holding"):
    if mode == "target":
        v77_h = row.get("v78_suba_v77_target", row.get("v78_suba_v77_holding", "cash"))
        new_h = row.get("v78_suba_new_target", row.get("v78_suba_new_holding", "cash"))
        v77_weight_col = "v78_suba_v77_target_weight"
        new_weight_col = "v78_suba_new_target_weight"
    else:
        v77_h = row.get("v78_suba_v77_holding", "cash")
        new_h = row.get("v78_suba_new_holding", "cash")
        v77_weight_col = "v78_suba_v77_weight"
        new_weight_col = "v78_suba_new_weight"
    try:
        v77_w = float(row.get(v77_weight_col, row.get("v78_suba_v77_weight", 0.0)) or 0.0)
    except Exception:
        v77_w = 0.0
    try:
        new_w = float(row.get(new_weight_col, row.get("v78_suba_new_weight", 0.0)) or 0.0)
    except Exception:
        new_w = 0.0
    parts = []
    if abs(v77_w) > 1e-12:
        parts.append(f"V7.7A: {CN_NAMES.get(v77_h, v77_h)} {V78_SUBA_V77_WEIGHT * v77_w:.2f}x")
    if abs(new_w) > 1e-12:
        parts.append(f"NewA: {CN_NAMES.get(new_h, new_h)} {V78_SUBA_NEW_TV10_WEIGHT * new_w:.2f}x")
    return " | ".join(parts) if parts else "Cash"


def _v78_suba_pre_trade_position_text(cn_result, pos):
    row = cn_result.iloc[pos]
    v77_h = row.get("v78_suba_v77_holding", "cash")
    v77_w_raw = row.get("v78_suba_v77_weight", 0.0)
    new_h = row.get("v78_suba_new_holding", "cash")
    new_w_raw = row.get("v78_suba_new_weight", 0.0)
    try:
        v77_w = float(v77_w_raw or 0.0)
    except Exception:
        v77_w = 0.0
    try:
        new_w = float(new_w_raw or 0.0)
    except Exception:
        new_w = 0.0
    parts = []
    if abs(v77_w) > 1e-12:
        parts.append(f"V7.7A: {CN_NAMES.get(v77_h, v77_h)} {V78_SUBA_V77_WEIGHT * v77_w:.2f}x")
    if abs(new_w) > 1e-12:
        parts.append(f"NewA: {CN_NAMES.get(new_h, new_h)} {V78_SUBA_NEW_TV10_WEIGHT * new_w:.2f}x")
    return " | ".join(parts) if parts else "Cash"


def _suba_signal_display_state(cn_result, display_idx=-1):
    if cn_result is None or len(cn_result) == 0:
        return {
            "display_idx": None,
            "display_date": None,
            "is_signal": False,
            "current_holding": "cash",
            "target_holding": "cash",
            "post_signal_holding": "cash",
            "last_signal_date": None,
        }

    n = len(cn_result)
    pos = display_idx if display_idx >= 0 else n + display_idx
    pos = int(np.clip(pos, 0, n - 1))
    display_date = cn_result.index[pos]
    post_holding = str(cn_result["holding"].iloc[pos]) if "holding" in cn_result.columns else "cash"
    is_signal = bool(cn_result["is_signal"].iloc[pos]) if "is_signal" in cn_result.columns else False

    if is_signal and pos > 0 and "holding" in cn_result.columns:
        current_holding = str(cn_result["holding"].iloc[pos - 1])
    else:
        current_holding = post_holding

    target_holding = post_holding
    if is_signal and "target" in cn_result.columns:
        raw_target = cn_result["target"].iloc[pos]
        if raw_target is not None and not pd.isna(raw_target):
            target_holding = str(raw_target)

    hist = cn_result.iloc[:pos + 1]
    if "is_signal" in hist.columns:
        past = hist[hist["is_signal"] == True]
        last_signal_date = past.index[-1] if len(past) > 0 else display_date
    else:
        last_signal_date = display_date

    return {
        "display_idx": pos,
        "display_date": display_date,
        "is_signal": is_signal,
        "current_holding": current_holding,
        "target_holding": target_holding,
        "post_signal_holding": post_holding,
        "current_display": _v78_suba_pre_trade_position_text(cn_result, pos) if "v78_suba_v77_holding" in cn_result.columns else CN_NAMES.get(current_holding, current_holding),
        "target_display": _v78_suba_position_text(cn_result.iloc[pos], mode="target") if "v78_suba_v77_holding" in cn_result.columns else CN_NAMES.get(target_holding, target_holding),
        "post_display": _v78_suba_position_text(cn_result.iloc[pos], mode="target") if "v78_suba_v77_holding" in cn_result.columns else CN_NAMES.get(post_holding, post_holding),
        "last_signal_date": last_signal_date,
    }

def _build_dk_rank_rows(cn_dk_result, use_shifted=True, top_n=3):
    """提取DK多配对实时解释信息。use_shifted=True 表示当前已生效信号。"""
    signals_df = cn_dk_result.attrs.get("signals_df")
    pair_data = cn_dk_result.attrs.get("pair_data", {})
    if signals_df is None or len(cn_dk_result) == 0:
        return []
    score_df = signals_df.shift(1) if use_shifted else signals_df
    date = cn_dk_result.index[-1]
    if date not in score_df.index:
        return []
    row = score_df.loc[date].dropna().sort_values(ascending=False).head(top_n)
    rows = []
    for rank, (pair, score_used) in enumerate(row.items(), 1):
        direction = 0
        live_score = np.nan
        if pair in signals_df.columns and date in signals_df.index:
            live_score = signals_df.loc[date, pair]
        pdata = pair_data.get(pair)
        if pdata is not None and date in pdata.index and "signal" in pdata.columns:
            sig_val = pdata.loc[date, "signal"]
            direction = int(sig_val) if not pd.isna(sig_val) else 0
        holding_code = f"{pair}_{direction}" if pair != "none" and direction != 0 else "none_0"
        rows.append({
            "rank": rank,
            "pair": pair,
            "pair_display": _dk_pair_display(pair),
            "score_used": float(score_used) if not pd.isna(score_used) else np.nan,
            "score_live": float(live_score) if not pd.isna(live_score) else np.nan,
            "direction": direction,
            "position_text": _dk_pos_str(holding_code),
        })
    return rows


def _build_dk_rank_rows_at(cn_dk_result, idx=-1, use_shifted=True, top_n=3):
    signals_df = cn_dk_result.attrs.get("signals_df") if cn_dk_result is not None else None
    pair_data = cn_dk_result.attrs.get("pair_data", {}) if cn_dk_result is not None else {}
    if signals_df is None or cn_dk_result is None or len(cn_dk_result) == 0:
        return []
    date = cn_dk_result.index[idx]
    score_df = signals_df.shift(1) if use_shifted else signals_df
    if date not in score_df.index:
        return []
    row = score_df.loc[date].dropna().sort_values(ascending=False).head(top_n)
    fallback_direction = 0
    try:
        result_row = cn_dk_result.iloc[idx]
        fallback_direction = int(result_row.get("direction", 0) or 0)
    except Exception:
        result_row = None
    rows = []
    for rank, (pair, score_used) in enumerate(row.items(), 1):
        direction = 0
        live_score = np.nan
        if pair in signals_df.columns and date in signals_df.index:
            live_score = signals_df.loc[date, pair]
        pdata = pair_data.get(pair)
        if pdata is not None and date in pdata.index:
            if "signal" in pdata.columns:
                sig_val = pdata.loc[date, "signal"]
                direction = int(sig_val) if not pd.isna(sig_val) else 0
            elif "position" in pdata.columns:
                pos_val = pdata.loc[date, "position"]
                direction = int(pos_val) if not pd.isna(pos_val) else 0
        if direction == 0 and result_row is not None and str(result_row.get("top_pair", "")) == str(pair):
            direction = fallback_direction
        holding_code = f"{pair}_{direction}" if pair != "none" and direction != 0 else "none_0"
        rows.append({
            "rank": rank,
            "pair": pair,
            "pair_display": _dk_pair_display(pair),
            "score_used": float(score_used) if not pd.isna(score_used) else np.nan,
            "score_live": float(live_score) if not pd.isna(live_score) else np.nan,
            "direction": direction,
            "position_text": _dk_pos_str(holding_code),
        })
    return rows


def _split_dk_history_trades(dk_period):
    if dk_period is None or len(dk_period) == 0:
        return dk_period, dk_period
    idx = dk_period.index
    holding_s = dk_period.get("holding", pd.Series("none_0", index=idx)).fillna("none_0").astype(str)
    active_mask = holding_s.map(lambda h: parse_dk_holding(h) is not None)
    effective_holding = holding_s.where(active_mask, "none_0")
    position_mask = effective_holding.ne(effective_holding.shift()).fillna(False)
    if len(position_mask) > 0:
        position_mask.iloc[0] = False
    if "scale_rebalanced" in dk_period.columns:
        scale_rebalanced = dk_period.get("scale_rebalanced", pd.Series(False, index=idx)).fillna(False).astype(bool)
    else:
        weight_s = pd.to_numeric(dk_period.get("weight", pd.Series(1.0, index=idx)), errors="coerce").fillna(0.0)
        effective_weight = weight_s.where(active_mask, 0.0)
        scale_rebalanced = effective_weight.diff().abs().fillna(0.0) > 0.001
        if len(scale_rebalanced) > 0:
            scale_rebalanced.iloc[0] = False
    scale_mask = scale_rebalanced & ~position_mask
    return dk_period[position_mask], dk_period[scale_mask]


def extract_dk_rebalances(dk_result, strategy_name="Sub-A-DK", cn_dk_close=None):
    """P1-2 fix: parse DK holding states and effective exposure changes."""
    records = []
    prev_holding = None
    prev_weight = None
    has_weight = "weight" in dk_result.columns
    for i in range(len(dk_result)):
        date = dk_result.index[i]
        holding = dk_result["holding"].iloc[i]
        weight = dk_result["weight"].iloc[i] if has_weight else None
        old_active = parse_dk_holding(prev_holding) is not None
        new_active = parse_dk_holding(holding) is not None
        prev_effective_holding = str(prev_holding) if old_active else "none_0"
        new_effective_holding = str(holding) if new_active else "none_0"
        position_changed = prev_holding is not None and new_effective_holding != prev_effective_holding
        prev_eff_weight = (
            float(prev_weight)
            if old_active and prev_weight is not None and pd.notna(prev_weight)
            else 0.0
        )
        new_eff_weight = (
            float(weight)
            if new_active and weight is not None and pd.notna(weight)
            else 0.0
        )
        scale_changed = has_weight and prev_weight is not None and abs(new_eff_weight - prev_eff_weight) > 0.001
        execution_date = dk_result.index[i - 1] if i > 0 else date
        if position_changed:
            old_info = parse_dk_holding(prev_holding)
            new_info = parse_dk_holding(holding)
            if old_info and new_info:
                sell_text = f"平多{_dk_leg_name(old_info['long_leg'])}/平空{_dk_leg_name(old_info['short_leg'])}"
                buy_text = f"做多{_dk_leg_name(new_info['long_leg'])}/做空{_dk_leg_name(new_info['short_leg'])}"
            elif old_info and not new_info:
                sell_text = f"平多{_dk_leg_name(old_info['long_leg'])}/平空{_dk_leg_name(old_info['short_leg'])}"
                buy_text = "转现金 / 零敞口"
            elif not old_info and new_info:
                sell_text = "现金 / 零敞口"
                buy_text = f"做多{_dk_leg_name(new_info['long_leg'])}/做空{_dk_leg_name(new_info['short_leg'])}"
            else:
                sell_text = f"平仓 {prev_holding}"
                buy_text = f"开仓 {holding}"
            sell_p = _dk_holding_prices(prev_holding, cn_dk_close, execution_date)
            buy_p = _dk_holding_prices(holding, cn_dk_close, execution_date)
            records.append({
                "日期": execution_date.strftime("%Y-%m-%d"),
                "北京时间": beijing_time_str(execution_date, "CN", "close"),
                "策略": strategy_name,
                "卖出": sell_text,
                "卖出价格": sell_p,
                "买入": buy_text,
                "买入价格": buy_p,
            })
        elif scale_changed:
            new_info = parse_dk_holding(holding)
            if new_info:
                h_name = f"做多{_dk_leg_name(new_info['long_leg'])}/做空{_dk_leg_name(new_info['short_leg'])}"
            else:
                h_name = CN_DK_NAMES.get(holding, holding)
            h_prices = _dk_holding_prices(holding, cn_dk_close, execution_date)
            records.append({
                "日期": execution_date.strftime("%Y-%m-%d"),
                "北京时间": beijing_time_str(execution_date, "CN", "close"),
                "策略": strategy_name,
                "卖出": f"杠杆 {prev_eff_weight:.2f}x",
                "卖出价格": h_prices,
                "买入": f"杠杆 {new_eff_weight:.2f}x ({h_name})",
                "买入价格": h_prices,
            })
        prev_holding = holding
        prev_weight = weight
    return records


def extract_v78_adk_rebalances(v78_adk_result, cn_dk_close=None, since_date=None):
    records = []
    components = [
        ("V7.7 ADK", V78_ADK_V77_WEIGHT, v78_adk_result.attrs.get("v78_adk_v77")),
        (V78_ADK_NEW_LABEL, V78_ADK_NEW_PRIMARY_WEIGHT, v78_adk_result.attrs.get("v78_adk_new")),
    ]
    for label, component_weight, component in components:
        if component is None or len(component) == 0:
            continue
        component_records = extract_dk_rebalances(
            component,
            strategy_name=f"{label} ({component_weight:.0%})",
            cn_dk_close=cn_dk_close,
        )
        for record in component_records:
            record["策略"] = f"{label} ({component_weight:.0%})"
            if since_date is not None:
                try:
                    record_date = record.get("日期")
                    if pd.Timestamp(record_date) < pd.Timestamp(since_date):
                        continue
                except Exception:
                    pass
            records.append(record)
    records.sort(key=lambda item: item.get("日期", ""))
    return records


def extract_us_rot_rebalances(us_rot_result, us_rot_close=None, us_open=None, since_date=None):
    records = []
    assets = sorted(_weight_columns_assets(
        us_rot_result,
        prefixes=("w_", "actual_w_", "target_w_", "model_w_", "model_target_w_", "effective_w_"),
    ))
    us_schedule = _coerce_session_index(us_open)
    if us_schedule is None and us_rot_close is not None:
        us_schedule = _coerce_session_index(us_rot_close)
    start_i = 0
    prev_model_weights = None
    if since_date is not None and len(us_rot_result) > 0:
        since_ts = pd.Timestamp(since_date)
        start_i = int(us_rot_result.index.searchsorted(since_ts, side="left"))
        if start_i > 0:
            prev_row = us_rot_result.iloc[start_i - 1]
            prev_model_weights = _row_prefixed_weights(prev_row, "model_target_w_", assets)
            if not any(abs(v) > 1e-12 for v in prev_model_weights.values()):
                prev_model_weights = _row_prefixed_weights(prev_row, "target_w_", assets)
            if not any(abs(v) > 1e-12 for v in prev_model_weights.values()):
                prev_model_weights = _row_prefixed_weights(prev_row, "actual_w_", assets)
            if not any(abs(v) > 1e-12 for v in prev_model_weights.values()):
                prev_model_weights = _row_prefixed_weights(prev_row, "w_", assets)
    for i in range(start_i, len(us_rot_result)):
        row = us_rot_result.iloc[i]
        date = us_rot_result.index[i]
        current_actual = _row_prefixed_weights(row, "actual_w_", assets)
        if not any(abs(v) > 1e-12 for v in current_actual.values()):
            current_actual = _row_prefixed_weights(row, "w_", assets)
        current_target = _row_prefixed_weights(row, "model_target_w_", assets)
        if not any(abs(v) > 1e-12 for v in current_target.values()):
            current_target = _row_prefixed_weights(row, "target_w_", assets)
        if not any(abs(v) > 1e-12 for v in current_target.values()):
            current_target = current_actual
        volreg_action = str(row.get("volreg_action", "") or "")
        is_model_rebalanced = _subb_model_rebalanced_value(row)
        if (
            not is_model_rebalanced
            and (
                bool(row.get("volreg_cash", False))
                or bool(row.get("volreg_transition", False))
                or volreg_action in ("enter_cash", "exit_cash", "enter_defense", "exit_defense")
            )
        ):
            prev_model_weights = current_target
            continue
        if prev_model_weights is None:
            prev_model_weights = {"BIL": 1.0}
        if not is_model_rebalanced:
            prev_model_weights = current_target
            continue
        old_weights = prev_model_weights
        new_weights = current_target
        sells, buys = [], []
        sell_prices, buy_prices = [], []
        for a in sorted(set(list(new_weights.keys()) + list(old_weights.keys()))):
            cur = new_weights.get(a, 0)
            prev = old_weights.get(a, 0)
            diff = cur - prev
            if abs(diff) > 0.005:
                if a == "CASH":
                    if diff < 0:
                        sells.append(f"CASH {prev:.1%}->{cur:.1%}")
                    else:
                        buys.append(f"CASH {prev:.1%}->{cur:.1%}")
                    continue
                live = _ROT_PROXY_TO_LIVE.get(a, a)
                # 优先用T+1开盘价(实际成交价), 回退到信号日收盘价
                _p = _lookup_next_open(a, date, us_open)
                _p_label = "开"
                if _p is None and us_rot_close is not None and date in us_rot_close.index:
                    if live in us_rot_close.columns:
                        _p = us_rot_close.loc[date, live]
                    elif a in us_rot_close.columns:
                        _p = us_rot_close.loc[date, a]
                    _p_label = "收"
                _p_str = _rebalance_price_text(_p, _p_label)
                if diff < 0:
                    sells.append(f"{live} {prev:.1%}->{cur:.1%}")
                    if _p_str:
                        sell_prices.append(f"{live} {_p_str}")
                elif diff > 0:
                    buys.append(f"{live} {prev:.1%}->{cur:.1%}")
                    if _p_str:
                        buy_prices.append(f"{live} {_p_str}")
        if sells or buys:
            records.append({
                "日期": date.strftime("%Y-%m-%d"),
                "北京时间": us_exec_time_str(date, us_schedule),
                "策略": "Sub-B",
                "卖出": "; ".join(sells) if sells else "—",
                "卖出价格": "; ".join(sell_prices) if sell_prices else None,
                "买入": "; ".join(buys) if buys else "—",
                "买入价格": "; ".join(buy_prices) if buy_prices else None,
            })
        prev_model_weights = current_target
    return records

def extract_subb_volreg_rebalances(us_rot_result, us_rot_close=None, us_open=None, since_date=None):
    records = []
    if "volreg_transition" not in us_rot_result.columns and "volreg_rebalanced" not in us_rot_result.columns:
        return records
    assets = sorted(_weight_columns_assets(
        us_rot_result,
        prefixes=("effective_w_", "w_"),
    ))
    start_i = 0
    if since_date is not None and len(us_rot_result) > 0:
        start_i = int(us_rot_result.index.searchsorted(pd.Timestamp(since_date), side="left"))
    for i in range(start_i, len(us_rot_result)):
        row = us_rot_result.iloc[i]
        is_transition = bool(row.get("volreg_transition", row.get("volreg_rebalanced", False)))
        if not is_transition:
            continue
        date = us_rot_result.index[i]
        new_weights = _row_prefixed_weights(row, "effective_w_", assets)
        if not any(abs(v) > 1e-12 for v in new_weights.values()):
            new_weights = _row_prefixed_weights(row, "w_", assets)
        if i > 0:
            prev_row = us_rot_result.iloc[i - 1]
            old_weights = _row_prefixed_weights(prev_row, "effective_w_", assets)
            if not any(abs(v) > 1e-12 for v in old_weights.values()):
                old_weights = _row_prefixed_weights(prev_row, "w_", assets)
        else:
            old_weights = {}
        sells, buys = [], []
        sell_prices, buy_prices = [], []
        for a in sorted(set(list(new_weights.keys()) + list(old_weights.keys()))):
            cur = new_weights.get(a, 0)
            prev = old_weights.get(a, 0)
            diff = cur - prev
            if abs(diff) <= 0.005:
                continue
            if a == "CASH":
                if diff < 0:
                    sells.append(f"CASH {prev:.1%}->{cur:.1%}")
                else:
                    buys.append(f"CASH {prev:.1%}->{cur:.1%}")
                continue
            live = _ROT_PROXY_TO_LIVE.get(a, a)
            _p = _lookup_open_on_date(a, date, us_open)
            _p_label = "开"
            if _p is None and us_rot_close is not None and date in us_rot_close.index:
                if live in us_rot_close.columns:
                    _p = us_rot_close.loc[date, live]
                elif a in us_rot_close.columns:
                    _p = us_rot_close.loc[date, a]
                _p_label = "收"
            _p_str = _rebalance_price_text(_p, _p_label)
            if diff < 0:
                sells.append(f"{live} {prev:.1%}->{cur:.1%}")
                if _p_str:
                    sell_prices.append(f"{live} {_p_str}")
            elif diff > 0:
                buys.append(f"{live} {prev:.1%}->{cur:.1%}")
                if _p_str:
                    buy_prices.append(f"{live} {_p_str}")
        if sells or buys:
            action = row.get("volreg_action", "")
            records.append({
                "日期": date.strftime("%Y-%m-%d"),
                "北京时间": beijing_time_str(date, "US", "open"),
                "策略": "Sub-B VolReg",
                "日期口径": "execution_day",
                "卖出": "; ".join(sells) if sells else "—",
                "卖出价格": "; ".join(sell_prices) if sell_prices else None,
                "买入": "; ".join(buys) if buys else "—",
                "买入价格": "; ".join(buy_prices) if buy_prices else None,
                "说明": action,
            })
    return records

def extract_subb_dbc_profit_guard_rebalances(us_rot_result, us_rot_close=None, us_open=None, since_date=None):
    records = []
    if (
        us_rot_result is None
        or len(us_rot_result) == 0
        or "dbc_profit_guard_rebalanced" not in us_rot_result.columns
    ):
        return records
    assets = sorted(_weight_columns_assets(
        us_rot_result,
        prefixes=("pre_dbc_profit_guard_w_", "effective_w_", "w_"),
    ))
    start_i = 0
    if since_date is not None and len(us_rot_result) > 0:
        start_i = int(us_rot_result.index.searchsorted(pd.Timestamp(since_date), side="left"))
    for i in range(start_i, len(us_rot_result)):
        row = us_rot_result.iloc[i]
        guard_turnover = row.get("dbc_profit_guard_turnover", 0.0)
        try:
            guard_turnover = float(guard_turnover) if pd.notna(guard_turnover) else 0.0
        except Exception:
            guard_turnover = 0.0
        is_rebalanced = bool(row.get("dbc_profit_guard_rebalanced", False)) or guard_turnover > 1e-9
        if not is_rebalanced:
            continue
        date = us_rot_result.index[i]
        old_weights = _row_prefixed_weights(row, "pre_dbc_profit_guard_w_", assets)
        if not any(abs(v) > 1e-12 for v in old_weights.values()) and i > 0:
            prev_row = us_rot_result.iloc[i - 1]
            old_weights = _row_prefixed_weights(prev_row, "effective_w_", assets)
            if not any(abs(v) > 1e-12 for v in old_weights.values()):
                old_weights = _row_prefixed_weights(prev_row, "w_", assets)
        new_weights = _row_prefixed_weights(row, "effective_w_", assets)
        if not any(abs(v) > 1e-12 for v in new_weights.values()):
            new_weights = _row_prefixed_weights(row, "w_", assets)
        sells, buys = [], []
        sell_prices, buy_prices = [], []
        for a in sorted(set(list(new_weights.keys()) + list(old_weights.keys()))):
            cur = new_weights.get(a, 0.0)
            prev = old_weights.get(a, 0.0)
            diff = cur - prev
            if abs(diff) <= 0.005:
                continue
            if a == "CASH":
                if diff < 0:
                    sells.append(f"CASH {prev:.1%}->{cur:.1%}")
                else:
                    buys.append(f"CASH {prev:.1%}->{cur:.1%}")
                continue
            live = _ROT_PROXY_TO_LIVE.get(a, a)
            _p = _lookup_open_on_date(a, date, us_open)
            _p_label = "开"
            if _p is None and us_rot_close is not None and date in us_rot_close.index:
                if live in us_rot_close.columns:
                    _p = us_rot_close.loc[date, live]
                elif a in us_rot_close.columns:
                    _p = us_rot_close.loc[date, a]
                _p_label = "收"
            _p_str = _rebalance_price_text(_p, _p_label)
            if diff < 0:
                sells.append(f"{live} {prev:.1%}->{cur:.1%}")
                if _p_str:
                    sell_prices.append(f"{live} {_p_str}")
            elif diff > 0:
                buys.append(f"{live} {prev:.1%}->{cur:.1%}")
                if _p_str:
                    buy_prices.append(f"{live} {_p_str}")
        if sells or buys:
            action = row.get("dbc_profit_guard_action", "")
            records.append({
                "日期": date.strftime("%Y-%m-%d"),
                "北京时间": beijing_time_str(date, "US", "open"),
                "策略": "Sub-B DBC Guard",
                "日期口径": "execution_day",
                "卖出": "; ".join(sells) if sells else "—",
                "卖出价格": "; ".join(sell_prices) if sell_prices else None,
                "买入": "; ".join(buys) if buys else "—",
                "买入价格": "; ".join(buy_prices) if buy_prices else None,
                "说明": action,
            })
    return records

def extract_prod_rebalances(prod_details, prod_monthly, include_no_change=False, us_prod_daily=None, us_open=None):
    records = []
    if prod_details is None or prod_monthly is None:
        return records
    sig_cols = [c for c in prod_details.columns if c.startswith("sig_") and not c.startswith("sig_am_") and not c.startswith("sig_sma_")]
    us_schedule = _coerce_session_index(us_open)
    if us_schedule is None and us_prod_daily is not None:
        us_schedule = _coerce_session_index(us_prod_daily)
    prev_sigs = None
    for i in range(len(prod_details)):
        dt = prod_details.index[i]
        sigs = {c.replace("sig_", ""): prod_details.iloc[i][c] for c in sig_cols}
        if prev_sigs is not None:
            sells, buys = [], []
            sell_prices, buy_prices = [], []
            for t, s in sigs.items():
                ps = prev_sigs.get(t, s)
                if not pd.isna(s) and not pd.isna(ps) and abs(s - ps) > 0.01:
                    # 优先T+1开盘价(实际成交价), 回退到信号日收盘价
                    _p = _lookup_next_open(t, dt, us_open)
                    _p_label = "开"
                    if _p is None and us_prod_daily is not None and dt in us_prod_daily.index:
                        if t in us_prod_daily.columns:
                            _p = us_prod_daily.loc[dt, t]
                        else:
                            proxy = PROD_PORTFOLIO.get(t, {}).get("proxy", t)
                            if proxy in us_prod_daily.columns:
                                _p = us_prod_daily.loc[dt, proxy]
                        _p_label = "收"
                    _p_str = _rebalance_price_text(_p, _p_label)
                    if s >= 0.99:
                        desc = f"{t} 全部持有"
                    elif s <= 0.01:
                        desc = f"{t} 全部现金(BIL)"
                    else:
                        desc = f"{t} {s:.0%}持有"
                    if s > ps:  # 加仓
                        buys.append(desc)
                        if _p_str:
                            buy_prices.append(f"{t} {_p_str}")
                    else:  # 减仓
                        sells.append(desc)
                        if _p_str:
                            sell_prices.append(f"{t} {_p_str}")
            if sells or buys:
                records.append({
                    "日期": dt.strftime("%Y-%m-%d"),
                    "北京时间": us_exec_time_str(dt, us_schedule),
                    "策略": "Sub-C",
                    "卖出": "; ".join(sells) if sells else "—",
                    "卖出价格": "; ".join(sell_prices) if sell_prices else None,
                    "买入": "; ".join(buys) if buys else "—",
                    "买入价格": "; ".join(buy_prices) if buy_prices else None,
                })
            elif include_no_change:
                risk_pct = np.mean([s for s in sigs.values() if not pd.isna(s)]) if sigs else 0
                records.append({
                    "日期": dt.strftime("%Y-%m-%d"),
                    "北京时间": us_exec_time_str(dt, us_schedule),
                    "策略": "Sub-C",
                    "卖出": "",
                    "卖出价格": None,
                    "买入": f"信号无变更 (平均持仓{risk_pct:.0%})",
                    "买入价格": None,
                })
        prev_sigs = sigs
    return records

_LAST_SUBC_VS_REBALANCE_WARNING = None


def extract_subc_vs_rebalances(us_prod_daily, prod_sig_a, prod_sig_b, us_open=None, msg=None):
    """提取Sub-C Vol-Scaling杠杆调整记录。"""
    global _LAST_SUBC_VS_REBALANCE_WARNING
    _LAST_SUBC_VS_REBALANCE_WARNING = None
    if not PROD_VS_ENABLED:
        return []
    if us_prod_daily is None or prod_sig_a is None:
        return []
    try:
        us_schedule = _coerce_session_index(us_open)
        if us_schedule is None and us_prod_daily is not None:
            us_schedule = _coerce_session_index(us_prod_daily)
        subc_daily = _compute_daily_subc_phased(
            us_prod_daily, prod_sig_a, PROD_CASH,
            prod_sig_b=prod_sig_b, blend_a=PROD_BLEND_A)
        _, actual_scale, _ = _apply_subc_vol_scaling(subc_daily, us_prod_daily)
        records = []
        prev_s = None
        for i in range(len(actual_scale)):
            s = actual_scale.iloc[i]
            date = actual_scale.index[i]
            if prev_s is not None and abs(s - prev_s) > 0.001:
                # 优先T+1开盘价, 回退到信号日收盘价
                etf_prices = []
                for etf_name in sorted(PROD_PORTFOLIO.keys()):
                    _p = _lookup_next_open(etf_name, date, us_open)
                    _label = "开"
                    if _p is None and date in us_prod_daily.index:
                        proxy = PROD_PORTFOLIO[etf_name].get("proxy", etf_name)
                        if etf_name in us_prod_daily.columns:
                            _p = us_prod_daily.loc[date, etf_name]
                        elif proxy in us_prod_daily.columns:
                            _p = us_prod_daily.loc[date, proxy]
                        _label = "收"
                    if _p is not None and not pd.isna(_p):
                        etf_prices.append(f"{etf_name} ${_p:.2f}{_label}")
                price_str = "; ".join(etf_prices) if etf_prices else None
                # actual_scale 已含 shift(1): date 本身就是执行日
                # 用 beijing_time_str(date, open) 而非 us_exec_time_str(date)
                # 后者会多跳一天 (_next_session_day)
                records.append({
                    "日期": date.strftime("%Y-%m-%d"),
                    "北京时间": beijing_time_str(date, "US", "open"),
                    "策略": "Sub-C",
                    "卖出": f"杠杆 {prev_s:.2f}x",
                    "卖出价格": price_str,
                    "买入": f"杠杆 {s:.2f}x",
                    "买入价格": price_str,
                })
            prev_s = s
        return records
    except (KeyError, ValueError, AttributeError) as exc:
        _LAST_SUBC_VS_REBALANCE_WARNING = f"extract_subc_vs_rebalances skipped: {_short_error(exc)}"
        if msg is not None:
            msg.write(f"  ⚠️ Sub-C杠杆调仓记录跳过: {_short_error(exc)}\n")
        return []

def _compute_daily_subc(us_prod_daily, prod_sig_a, portfolio, cash_ticker,
                        prod_sig_b=None, blend_a=0.5):
    """Compute daily Sub-C returns from daily prices and monthly signals.
    Supports 50/50 blend when prod_sig_b is provided.
    Uses monthly signals applied to daily price changes for accurate
    intra-month drawdown calculation."""
    daily_ret = us_prod_daily.pct_change().dropna(how="all")
    day_periods = daily_ret.index.to_period("M")
    use_blend = prod_sig_b is not None
    blend_b = 1 - blend_a
    sig_a_lookup = {}
    for sig_dt in prod_sig_a.index:
        sig_a_lookup[sig_dt.to_period("M")] = prod_sig_a.loc[sig_dt]
    sig_b_lookup = {}
    if use_blend:
        for sig_dt in prod_sig_b.index:
            sig_b_lookup[sig_dt.to_period("M")] = prod_sig_b.loc[sig_dt]
    period_masks = {}
    for period in day_periods.unique():
        period_masks[period] = (day_periods == period)
    result = pd.Series(0.0, index=daily_ret.index)
    cash_daily = (daily_ret[cash_ticker].fillna(0)
                  if cash_ticker in daily_ret.columns
                  else pd.Series(0.0, index=daily_ret.index))
    for name, cfg in portfolio.items():
        proxy = cfg["proxy"]
        w = cfg["w"]
        if proxy not in daily_ret.columns:
            continue
        asset_daily = daily_ret[proxy].fillna(0)
        daily_sig_a = pd.Series(np.nan, index=daily_ret.index)
        for period, mask in period_masks.items():
            if period in sig_a_lookup and proxy in sig_a_lookup[period].index:
                sv = sig_a_lookup[period][proxy]
                daily_sig_a[mask] = 0.0 if pd.isna(sv) else sv
        daily_sig_a = daily_sig_a.ffill().fillna(0)
        if use_blend:
            daily_sig_b = pd.Series(np.nan, index=daily_ret.index)
            for period, mask in period_masks.items():
                if period in sig_b_lookup and proxy in sig_b_lookup[period].index:
                    sv = sig_b_lookup[period][proxy]
                    daily_sig_b[mask] = 0.0 if pd.isna(sv) else sv
            daily_sig_b = daily_sig_b.ffill().fillna(0)
            ret_a = daily_sig_a * asset_daily + (1 - daily_sig_a) * cash_daily
            ret_b = daily_sig_b * asset_daily + (1 - daily_sig_b) * cash_daily
            weighted = w * (blend_a * ret_a + blend_b * ret_b)
        else:
            weighted = w * (daily_sig_a * asset_daily + (1 - daily_sig_a) * cash_daily)
        result += weighted
    return result

def _compute_daily_subc_phased(us_prod_daily, prod_sig_a, cash_ticker,
                                prod_sig_b=None, blend_a=0.5):
    """Three-phase daily Sub-C matching simulate_prod_btc_phased phases.
    Used for accurate intra-month drawdown calculation."""
    phases = [
        (us_prod_daily[us_prod_daily.index < DBMF_BT_START], PROD_PORTFOLIO_PRE_DBMF),
        (us_prod_daily[(us_prod_daily.index >= DBMF_BT_START) & (us_prod_daily.index < BTC_BT_START)], PROD_PORTFOLIO_BT),
        (us_prod_daily[us_prod_daily.index >= BTC_BT_START], PROD_PORTFOLIO),
    ]
    parts = []
    for daily_phase, portfolio in phases:
        if len(daily_phase) > 1:
            parts.append(_compute_daily_subc(
                daily_phase, prod_sig_a, portfolio, cash_ticker,
                prod_sig_b=prod_sig_b, blend_a=blend_a))
    return pd.concat(parts) if parts else pd.Series(dtype=float)

def _apply_subc_vol_scaling(subc_ret, us_prod_daily,
                            target_vol=None, vol_window=None, max_lev=None,
                            min_lev=None, threshold=None, spread_bps=None,
                            rebal_cost_bps=None):
    """Apply target volatility scaling to Sub-C daily returns with threshold.

    Uses a threshold-based approach: only adjust actual position scale when
    |target_scale - current_scale| >= threshold.
    Includes financing costs (spread over risk-free) and transaction costs.

    Returns: (scaled_ret, actual_scale, costs) all as pd.Series
    """
    if target_vol is None:
        target_vol = PROD_VS_TARGET_VOL
    if vol_window is None:
        vol_window = PROD_VS_VOL_WINDOW
    if max_lev is None:
        max_lev = PROD_VS_MAX_LEV
    if min_lev is None:
        min_lev = PROD_VS_MIN_LEV
    if threshold is None:
        threshold = PROD_VS_THRESHOLD
    if spread_bps is None:
        spread_bps = PROD_VS_SPREAD_BPS
    if rebal_cost_bps is None:
        rebal_cost_bps = PROD_VS_REBAL_COST_BPS

    if not PROD_VS_ENABLED:
        return (subc_ret,
                pd.Series(1.0, index=subc_ret.index),
                pd.Series(0.0, index=subc_ret.index))

    rv = subc_ret.rolling(vol_window).std() * np.sqrt(US_TRADING_DAYS)
    target_scale = (target_vol / rv).clip(min_lev, max_lev).shift(1).fillna(1.0)
    bil = us_prod_daily["BIL"].pct_change().reindex(subc_ret.index).fillna(0)
    daily_spread = spread_bps / 10000 / US_TRADING_DAYS

    out = pd.Series(0.0, index=subc_ret.index)
    costs = pd.Series(0.0, index=subc_ret.index)
    actual_scale = pd.Series(1.0, index=subc_ret.index)
    current_s = 1.0

    for i in range(len(subc_ret)):
        ts = target_scale.iloc[i]
        r = subc_ret.iloc[i]
        rf = bil.iloc[i]
        if pd.isna(ts) or pd.isna(r):
            actual_scale.iloc[i] = current_s
            continue

        # 仅当 |目标-当前| >= 阈值 时才调整 (1e-9容差避免浮点精度问题)
        if abs(ts - current_s) >= threshold - 1e-9:
            new_s = ts
        else:
            new_s = current_s

        # 交易成本: 仅在实际调整时产生
        if i > 0 and new_s != current_s:
            delta = abs(new_s - current_s)
            tc = delta * rebal_cost_bps / 10000
            costs.iloc[i] = tc

        current_s = new_s
        actual_scale.iloc[i] = current_s

        # 计算收益
        if current_s <= 1.0:
            # 部分仓位 + 现金
            out.iloc[i] = current_s * r + (1 - current_s) * rf
        else:
            # 杠杆: 融资成本 = (scale-1) × (rf + spread)
            financing = (current_s - 1) * (rf + daily_spread)
            out.iloc[i] = current_s * r - financing

        out.iloc[i] -= costs.iloc[i]

    return out, actual_scale, costs


def _build_subc_vs_info(subc_daily, actual_scale,
                        target_vol=None, vol_window=None,
                        min_lev=None, max_lev=None, threshold=None):
    """Build Sub-C display info from the latest close.

    `current_scale` is the last executed scale already reflected in the latest bar.
    `next_target_scale` / `next_scale` are what the next rebalance would use if the
    latest close were treated as the new signal anchor.
    """
    if target_vol is None:
        target_vol = PROD_VS_TARGET_VOL
    if vol_window is None:
        vol_window = PROD_VS_VOL_WINDOW
    if min_lev is None:
        min_lev = PROD_VS_MIN_LEV
    if max_lev is None:
        max_lev = PROD_VS_MAX_LEV
    if threshold is None:
        threshold = PROD_VS_THRESHOLD

    current_scale = float(actual_scale.iloc[-1]) if len(actual_scale) > 0 else 1.0
    prev_actual_scale = float(actual_scale.iloc[-2]) if len(actual_scale) >= 2 else current_scale

    rv = subc_daily.rolling(vol_window).std() * np.sqrt(US_TRADING_DAYS)
    realized_vol = float(rv.iloc[-1]) if len(rv) > 0 and not pd.isna(rv.iloc[-1]) else None

    if realized_vol is None or realized_vol <= 0:
        next_target_scale = current_scale
    else:
        next_target_scale = float(np.clip(target_vol / realized_vol, min_lev, max_lev))

    if abs(next_target_scale - current_scale) >= threshold - 1e-9:
        next_scale = next_target_scale
    else:
        next_scale = current_scale

    pending_adjustment = abs(next_scale - current_scale) > 0.001
    return {
        "realized_vol": realized_vol,
        "rv_latest_no_shift": realized_vol,
        "realized_vol_basis": "latest_no_shift_for_next_open_target",
        "actual_scale": current_scale,
        "current_scale": current_scale,
        "prev_actual_scale": prev_actual_scale,
        "target_scale": next_target_scale,
        "next_target_scale": next_target_scale,
        "next_scale": next_scale,
        "pending_adjustment": pending_adjustment,
    }


def _compute_next_vol_scale(rv_latest, cur_post_thr, tgt_vol, min_l, max_l, thr):
    """前瞻计算下一交易日的波动率缩放杠杆。

    与 _build_subc_vs_info 同理: 用最新 realized_vol 推算下一日 vol-scale，
    并对比当前已生效 scale 应用阈值过滤。

    Args:
        rv_latest: 最新行的 realized_vol (未shift, 含最新数据)
        cur_post_thr: 当前已生效的 vol-scale (阈值过滤后的值, 用于阈值对比)
        tgt_vol, min_l, max_l: 策略参数
        thr: 变动阈值 (0 表示不使用)
    Returns: (next_raw, next_final, is_pending)
        next_raw: 理论目标 scale (未经阈值过滤)
        next_final: 阈值过滤后实际会执行的 scale
        is_pending: 是否存在待执行的调整
    """
    cur_post_thr = float(cur_post_thr) if not np.isnan(cur_post_thr) else 1.0
    if tgt_vol is None:
        return 1.0, 1.0, False
    if rv_latest is None or np.isnan(rv_latest) or rv_latest <= 1e-10:
        return cur_post_thr, cur_post_thr, False
    raw = float(np.clip(tgt_vol / rv_latest, min_l, max_l))
    if thr > 0 and abs(raw - cur_post_thr) < thr - 1e-9:
        final = cur_post_thr
    else:
        final = raw
    return raw, final, abs(final - cur_post_thr) > 0.001


def _base_fraction_from_weight_and_scale(weight, raw_scale):
    if pd.notna(raw_scale) and abs(float(raw_scale)) > 1e-12:
        return float(weight) / float(raw_scale)
    return 0.0


def _dk_get_vol_scale(dk_result, idx):
    """从 DK 结果中提取纯 vol-scale (不含 pair_decay / risk_gate overlay).

    优先从 pair_data attrs 获取精确值; 否则根据 overlay 列推算。
    """
    # 方法 1: 直接从 pair_data 取 pair-level post-threshold scale
    if "top_pair" in dk_result.columns:
        tp = dk_result["top_pair"].iloc[idx]
        pd_map = dk_result.attrs.get('pair_data', {})
        if tp != "none" and tp in pd_map:
            pdf = pd_map[tp]
            dt = dk_result.index[idx]
            if 'scale' in pdf.columns and dt in pdf.index:
                v = pdf.loc[dt, 'scale']
                if not np.isnan(v):
                    return float(v)
    # 方法 2: 根据 overlay 层推算
    bw = float(dk_result["base_weight"].iloc[idx]) if "base_weight" in dk_result.columns else float(dk_result["weight"].iloc[idx])
    has_gate = "risk_gate_scale" in dk_result.columns
    has_decay = "overlay_scale" in dk_result.columns
    if has_gate and has_decay:
        # risk_gate 覆盖了 base_weight → base_weight = vol_scale × overlay_scale
        ov = float(dk_result["overlay_scale"].iloc[idx])
        return bw / ov if abs(ov) > 1e-10 else bw
    # 仅 pair_decay 或仅 risk_gate: base_weight = vol_scale
    return bw


def _get_subc_daily_ret(us_prod_daily, prod_sig_a, prod_sig_b=None):
    """Convenience: compute Sub-C daily returns with vol-scaling if enabled."""
    raw = _compute_daily_subc_phased(us_prod_daily, prod_sig_a, PROD_CASH,
                                     prod_sig_b=prod_sig_b, blend_a=PROD_BLEND_A)
    if PROD_VS_ENABLED:
        scaled, _, _ = _apply_subc_vol_scaling(raw, us_prod_daily)
        return scaled
    return raw

RebalanceRecord = TypedDict("RebalanceRecord", {
    "日期": str,
    "北京时间": str,
    "策略": str,
    "卖出": str,
    "卖出价格": str | None,
    "买入": str,
    "买入价格": str | None,
    "日期口径": str,
    "说明": str,
}, total=False)


def _write_rebalance_sheet(
    wb: Any,
    rebalance_records: list[RebalanceRecord],
    header_fmt: Any,
    cell_fmt: Any,
    price_fmt: Any,
) -> None:
    if not rebalance_records:
        return
    ws = wb.add_worksheet("调仓记录")
    ws.set_column("A:A", 12)
    ws.set_column("B:B", 25)
    ws.set_column("C:C", 8)
    ws.set_column("D:D", 15)
    ws.set_column("E:E", 12)
    ws.set_column("F:F", 30)
    ws.set_column("G:G", 12)
    headers = ["日期", "北京时间", "策略", "卖出", "卖出价格", "买入", "买入价格"]
    for j, h in enumerate(headers):
        ws.write(0, j, h, header_fmt)
    for i, rec in enumerate(rebalance_records):
        ws.write(i + 1, 0, rec.get("日期", ""), cell_fmt)
        ws.write(i + 1, 1, rec.get("北京时间", ""), cell_fmt)
        ws.write(i + 1, 2, rec.get("策略", ""), cell_fmt)
        ws.write(i + 1, 3, rec.get("卖出", ""), cell_fmt)
        sell_price = rec.get("卖出价格")
        ws.write(i + 1, 4, sell_price if sell_price is not None else "", cell_fmt)
        ws.write(i + 1, 5, rec.get("买入", ""), cell_fmt)
        buy_price = rec.get("买入价格")
        ws.write(i + 1, 6, buy_price if buy_price is not None else "", cell_fmt)


def _write_adk_net_exposure_sheet(
    wb,
    cn_dk_result,
    header_fmt,
    cell_fmt,
    row_idx=-1,
    date_label="当前已生效",
):
    if cn_dk_result is None or "adk_net_asset_exposure" not in cn_dk_result.columns or len(cn_dk_result) == 0:
        return
    row = cn_dk_result.iloc[row_idx]
    net = row.get("adk_net_asset_exposure", {}) or {}
    if not net:
        return
    ws = wb.add_worksheet("ADK净敞口")
    ws.set_column("A:A", 16)
    ws.set_column("B:C", 14)
    ws.set_column("D:D", 10)
    headers = ["指数", "带符号净敞口", "净敞口", "方向"]
    for j, h in enumerate(headers):
        ws.write(0, j, h, header_fmt)
    for i, (asset, exposure) in enumerate(
        sorted(net.items(), key=lambda item: abs(float(item[1])), reverse=True),
        start=1,
    ):
        exposure = float(exposure)
        ws.write(i, 0, _dk_leg_name(asset), cell_fmt)
        ws.write(i, 1, exposure, cell_fmt)
        ws.write(i, 2, abs(exposure), cell_fmt)
        ws.write(i, 3, "做多" if exposure > 0 else "做空", cell_fmt)
    note_row = len(net) + 2
    ws.write(note_row, 0, "日期口径", header_fmt)
    ws.write(note_row, 1, date_label, cell_fmt)
    ws.write(note_row + 1, 0, "净敞口日期", header_fmt)
    ws.write(note_row + 1, 1, pd.Timestamp(row.name).strftime("%Y-%m-%d"), cell_fmt)
    basis_row = note_row + 3
    ws.write(basis_row, 0, "ADK回测口径", header_fmt)
    ws.write(basis_row, 1, "component-net", cell_fmt)
    ws.write(basis_row + 1, 0, "ADK执行参考", header_fmt)
    ws.write(basis_row + 1, 1, "账户级净敞口", cell_fmt)


def generate_signal_excel(
    date_str,
    signal_info,
    rebalance_records,
    cn_dk_result=None,
    adk_net_row_idx=-1,
    adk_net_date_label="当前已生效",
):
    output = io.BytesIO()
    with xlsxwriter.Workbook(output, {"in_memory": True}) as wb:
        header_fmt = wb.add_format({"bold": True, "bg_color": "#4472C4",
                                     "font_color": "white", "border": 1})
        cell_fmt = wb.add_format({"border": 1})
        pct_fmt = wb.add_format({"border": 1, "num_format": "0.0%"})
        price_fmt = wb.add_format({"border": 1, "num_format": "0.000"})
        ws = wb.add_worksheet("信号概览")
        ws.set_column("A:A", 12)
        ws.set_column("B:B", 18)
        ws.set_column("C:C", 30)
        ws.set_column("D:D", 15)
        headers = ["策略", "信号日?", "当前信号", "备注"]
        for j, h in enumerate(headers):
            ws.write(0, j, h, header_fmt)
        for i, (strat, info) in enumerate(signal_info.items()):
            ws.write(i+1, 0, strat, cell_fmt)
            ws.write(i+1, 1, "是" if info.get("is_signal") else "否", cell_fmt)
            ws.write(i+1, 2, info.get("signal_text", ""), cell_fmt)
            ws.write(i+1, 3, info.get("note", ""), cell_fmt)
        _write_adk_net_exposure_sheet(
            wb,
            cn_dk_result,
            header_fmt,
            cell_fmt,
            row_idx=adk_net_row_idx,
            date_label=adk_net_date_label,
        )
        _write_rebalance_sheet(wb, rebalance_records, header_fmt, cell_fmt, price_fmt)
    output.seek(0)
    return output.getvalue()

def generate_performance_excel(date_str, metrics_dict, monthly_returns, rebalance_records, is_short_period=False):
    output = io.BytesIO()
    with xlsxwriter.Workbook(output, {"in_memory": True}) as wb:
        header_fmt = wb.add_format({"bold": True, "bg_color": "#4472C4",
                                     "font_color": "white", "border": 1})
        cell_fmt = wb.add_format({"border": 1})
        pct_fmt = wb.add_format({"border": 1, "num_format": "0.00%"})
        num_fmt = wb.add_format({"border": 1, "num_format": "0.00"})
        ws = wb.add_worksheet("绩效概览")
        ws.set_column("A:A", 14)
        ws.set_column("B:E", 14)
        metric_headers = ["指标", "Sub-A", "A-DK", "Sub-B", "PV三策略组合(不含微盘/Sub-D)"]
        for j, h in enumerate(metric_headers):
            ws.write(0, j, h, header_fmt)
        pct2_fmt = wb.add_format({"border": 1, "num_format": "0.00%"})
        metric_names = [
            ("累计收益", "total_return", True),
            ("年化收益", "annual", True),
            ("波动率", "vol", True),
            ("夏普比率", "sharpe", False),
            ("最大回撤", "max_dd", True),
            ("卡尔玛比率", "calmar", False),
            ("月胜率", "win_rate", True),
        ]
        if is_short_period:
            metric_names.append(("周胜率", "weekly_win_rate", True))
        for i, (label, key, is_pct) in enumerate(metric_names):
            ws.write(i+1, 0, label, cell_fmt)
            for j, strat in enumerate(PERFORMANCE_COLUMNS):
                m = metrics_dict.get(strat)
                if m and key in m and m[key] is not None:
                    if is_pct:
                        ws.write(i+1, j+1, m[key] / 100, pct2_fmt)
                    else:
                        ws.write(i+1, j+1, round(m[key], 2), num_fmt)
                else:
                    ws.write(i+1, j+1, "N/A", cell_fmt)
        if monthly_returns is not None and len(monthly_returns) > 0:
            ws2 = wb.add_worksheet("月度收益")
            ws2.set_column("A:A", 10)
            ws2.set_column("B:E", 14)
            mr_headers = ["月份", "Sub-A", "A-DK", "Sub-B", "PV三策略组合(不含微盘/Sub-D)"]
            for j, h in enumerate(mr_headers):
                ws2.write(0, j, h, header_fmt)
            for i in range(len(monthly_returns)):
                idx = monthly_returns.index[i]
                ws2.write(i+1, 0, str(idx), cell_fmt)
                for j, col in enumerate(monthly_returns.columns):
                    val = monthly_returns.iloc[i][col]
                    if not pd.isna(val):
                        ws2.write(i+1, j+1, val, pct_fmt)
                    else:
                        ws2.write(i+1, j+1, "", cell_fmt)
        price_fmt = wb.add_format({"border": 1, "num_format": "0.000"})
        _write_rebalance_sheet(wb, rebalance_records, header_fmt, cell_fmt, price_fmt)
    output.seek(0)
    return output.getvalue()

class CombinedStrategyBase:
    """共享基类: 数据获取、策略执行、信号计算、资金管理"""

    def _fetch_data(self, msg, include_cn_live_snapshot=False, include_us_live_snapshot=False):
        msg.write("⏳ 正在获取A股数据...\n")
        cn_raw, cn_sources = {}, {}
        for secid in CN_STOCK_CODES:
            df, source = fetch_cn_kline(secid)
            df, source = _ensure_cn_history_frame(
                secid,
                df,
                source,
                min_rows=CN_MIN_HISTORY_ROWS,
                write=msg.write,
            )
            cn_raw[secid] = df
            cn_sources[secid] = source
            time.sleep(0.2)
        # 实时补充：纯指数代码的日K线可能缺少当天数据
        _bj_today_cn = beijing_now().date()
        if include_cn_live_snapshot:
            for secid in CN_STOCK_CODES:
                cn_raw[secid] = _supplement_today_close(cn_raw[secid], secid, _bj_today_cn, msg)
        else:
            for secid in CN_STOCK_CODES:
                cn_raw[secid] = _drop_cn_unconfirmed_today(cn_raw[secid])
        _cn_open_now, _bj_now_check = is_cn_market_open()
        _is_cn_trading_day = _is_cn_required_close_day(_bj_today_cn)
        _cn_after_close = _is_cn_trading_day and not _cn_open_now and _bj_now_check.hour >= 15
# ZZHL全收益历史兼容: 仅在旧H20955池启用时尝试用H00922扩展
        try:
            zzhl_df = cn_raw.get(CN_ZZHL_INDEX_SECID) if CN_ZZHL_INDEX_SECID == "1.H20955" else None
            if zzhl_df is not None and len(zzhl_df) > 0:
                zzhl_h00922 = None
                try:
                    df = _fetch_cn_csindex(CN_ZZHL_PRE_INDEX_CODE)
                    if df is not None and len(df) > 50:
                        zzhl_h00922 = df
                except _DATA_FETCH_ERRORS:
                    pass
                if zzhl_h00922 is not None:
                    h20955_start = zzhl_df.index[0]
                    h00922_pre = zzhl_h00922[zzhl_h00922.index < h20955_start].copy()
                    if len(h00922_pre) > 0:
                        h00922_pre["close"] *= zzhl_df["close"].iloc[0] / h00922_pre["close"].iloc[-1]
                        cn_raw[CN_ZZHL_INDEX_SECID] = pd.concat([h00922_pre, zzhl_df])
                        msg.write(f"  ZZHL: H00922扩展 {h00922_pre.index[0].strftime('%Y-%m-%d')}~{h20955_start.strftime('%Y-%m-%d')}\n")
        except _DATA_FETCH_ERRORS as e:
            msg.write(f"  ⚠️ ZZHL H00922扩展失败({e})，仅用H20955数据\n")
        cn_close = _build_cn_stock_close_frame(cn_raw)
        if len(cn_close) < CN_BIAS_N + CN_MOM_DAY + 10:
            detail = "；".join(
                f"{CN_NAMES.get(s, s)} {len(cn_raw[s])}行({_cn_frame_range_text(cn_raw[s])})"
                for s in CN_STOCK_CODES
            )
            raise poe.BotError(f"A股数据不足: 合并后仅{len(cn_close)}行；{detail}")
        for secid in CN_STOCK_CODES:
            name = CN_NAMES.get(secid, secid)
            source_label = _cn_latest_data_source_label(cn_raw[secid], cn_sources[secid])
            msg.write(f"  {name}: {cn_raw[secid].index[-1].strftime('%Y-%m-%d')} [{source_label}]\n")
        # 数据新鲜度检查: 对齐 V7.7；实时查询 warning，正式收盘查询严格失败。
        cn_close = _add_cn_bond_column(
            cn_close,
            msg,
            context="Sub-A国债避险",
            strict=_should_strict_cn_bond(include_cn_live_snapshot, _cn_after_close),
            include_live_snapshot=include_cn_live_snapshot,
        )
        if _cn_after_close:
            _write_cn_after_close_stale_warning_or_raise(
                msg.write,
                cn_raw,
                _bj_today_cn,
                include_cn_live_snapshot=include_cn_live_snapshot,
            )
        msg.write(f"  合并截至: {cn_close.index[-1].strftime('%Y-%m-%d')}\n")
        msg.write("⏳ 正在获取美股数据...\n")
        us_raw, us_sources = {}, {}
        for ticker in US_ALL_TICKERS:
            df, source = fetch_yahoo(ticker)
            if df is not None and len(df) > 50:
                us_raw[ticker] = df
                us_sources[ticker] = source
            time.sleep(0.1)
        # 美股实时补充: 盘中或日K线延迟时用实时行情API补充当日价格
        if include_us_live_snapshot:
            _supplement_us_today_close(us_raw, US_ALL_TICKERS, msg)
        _required_us_present = [
            ticker for ticker in SUBB_REQUIRED_PRICE_TICKERS
            if ticker in us_raw and ticker != US_ROT_BTC_TICKER
        ]
        _required_us_dates = [
            _latest_valid_close_date(us_raw[ticker])
            for ticker in _required_us_present
        ]
        _required_us_dates = [dt for dt in _required_us_dates if dt is not None]
        _expected_us_date = (
            max(_required_us_dates)
            if _required_us_dates else None
        )
        _assert_columns_fresh(
            us_raw,
            SUBB_REQUIRED_PRICE_TICKERS,
            expected_date=_expected_us_date,
            max_lag_days=1 if include_us_live_snapshot else 0,
            label="Sub-B核心价格",
        )
        rot_tickers = list(dict.fromkeys(US_ROT_POOL + ["BIL"] + list(SUBB_INFLATION_GATE_TICKERS)))
        _late_rot = _us_rot_late_history_tickers()
        rot_tickers_core = [t for t in rot_tickers if t not in _late_rot]
        if "EMXC" in US_ROT_POOL and US_ROT_EMXC_BT_PROXY not in rot_tickers_core:
            if US_ROT_EMXC_BT_PROXY in us_raw:
                rot_tickers_core.append(US_ROT_EMXC_BT_PROXY)
        us_rot_close = pd.concat(
            [us_raw[t][["close"]].rename(columns={"close": t})
             for t in rot_tickers_core if t in us_raw],
            axis=1).ffill().dropna()
        if "EMXC" in US_ROT_POOL and US_ROT_EMXC_BT_PROXY in us_raw:
            eem_col = us_rot_close[US_ROT_EMXC_BT_PROXY].copy() if US_ROT_EMXC_BT_PROXY in us_rot_close.columns else None
            emxc_raw = us_raw.get("EMXC")
            if eem_col is not None:
                hybrid = eem_col.rename("EMXC")
                if emxc_raw is not None and len(emxc_raw) > 0:
                    emxc_ser = emxc_raw["close"].reindex(hybrid.index)
                    switch_idx = hybrid.index >= US_ROT_EMXC_BT_START
                    if switch_idx.any() and emxc_ser.loc[switch_idx].first_valid_index() is not None:
                        first_emxc_date = emxc_ser.loc[switch_idx].first_valid_index()
                        scale_factor = hybrid.loc[first_emxc_date] / emxc_ser.loc[first_emxc_date]
                        hybrid.loc[switch_idx] = emxc_ser.loc[switch_idx] * scale_factor
                us_rot_close["EMXC"] = hybrid
                if US_ROT_EMXC_BT_PROXY in us_rot_close.columns and US_ROT_EMXC_BT_PROXY not in US_ROT_POOL:
                    us_rot_close = us_rot_close.drop(columns=[US_ROT_EMXC_BT_PROXY])
        for t in _late_rot:
            if t == "EMXC":
                continue
            if t in us_raw:
                us_rot_close = us_rot_close.join(
                    us_raw[t][["close"]].rename(columns={"close": t}), how="left")
        if "BTC-USD" in us_rot_close.columns and "IBIT" in us_raw and "close" in us_raw["IBIT"].columns:
            us_rot_close["BTC-USD"] = build_ibit_spliced(pd.DataFrame({
                "BTC-USD": us_rot_close["BTC-USD"],
                "IBIT": us_raw["IBIT"]["close"].reindex(us_rot_close.index),
            }))
        prod_proxies = list(set(
            [c["proxy"] for c in PROD_PORTFOLIO.values()] + [PROD_CASH]))
        _late_prod = {"BTC-USD", "DBMF"}
        prod_proxies_core = [t for t in prod_proxies if t not in _late_prod]
        us_prod_daily = pd.concat(
            [us_raw[t][["close"]].rename(columns={"close": t})
             for t in prod_proxies_core if t in us_raw],
            axis=1).ffill().dropna()
        for t in _late_prod:
            if t in us_raw:
                us_prod_daily = us_prod_daily.join(
                    us_raw[t][["close"]].rename(columns={"close": t}), how="left")
        # VolReg风控需要SPY数据, 即使SPY已不在轮动池中
        if "SPY" not in us_rot_close.columns and "SPY" in us_raw:
            us_rot_close["SPY"] = us_raw["SPY"]["close"].reindex(us_rot_close.index)
        _btc_like = {"BTC-USD"}
        _us_stock_rot = [t for t in rot_tickers if t in us_raw and t not in _btc_like]
        if _us_stock_rot:
            _last_stock_date = max(us_raw[t].index[-1] for t in _us_stock_rot)
            us_rot_close = us_rot_close.loc[:_last_stock_date]
        _us_stock_prod = [t for t in prod_proxies if t in us_raw and t not in _btc_like]
        if _us_stock_prod:
            _last_prod_date = max(us_raw[t].index[-1] for t in _us_stock_prod)
            us_prod_daily = us_prod_daily.loc[:_last_prod_date]
        missing_us = set(rot_tickers + prod_proxies) - set(us_raw.keys())
        if missing_us:
            msg.write(f"  ⚠️ 缺失: {', '.join(sorted(missing_us))}\n")
        # 实盘ETF价格列: 仓位调整需要实际ETF价格(非proxy价格)
        for _live_ticker in set(list(US_ROT_ASSETS.keys()) + list(PROD_PORTFOLIO.keys())):
            if _live_ticker in us_raw:
                _live_col = us_raw[_live_ticker]["close"]
                if _live_ticker not in us_rot_close.columns:
                    us_rot_close[_live_ticker] = _live_col.reindex(us_rot_close.index)
                if _live_ticker not in us_prod_daily.columns:
                    us_prod_daily[_live_ticker] = _live_col.reindex(us_prod_daily.index)
        _assert_subb_final_price_frame_fresh(
            us_rot_close,
            expected_date=us_rot_close.index[-1],
            include_us_live_snapshot=include_us_live_snapshot,
        )
        # 构建T+1开盘价查找表: 调仓记录用(信号日T收盘→T+1开盘执行)
        self._us_open = _build_us_open_execution_dict(us_raw)
        us_date = us_rot_close.index[-1]
        us_close_bj = beijing_time_str(us_date, "US", "close")
        msg.write(f"  美股: {len(us_raw)}个ETF | 收盘: {us_close_bj}\n")
        msg.write("⏳ 正在获取A-DK多空数据(5个价格指数)...\n")
        try:
            dk_dfs = {}
            _bj_today = beijing_now().date()
            _dk_fetch_list = [
                (CN_DK_ZZ1000_CODE, CN_DK_ZZ1000_SECID, CN_DK_COLS[0]),
                (CN_DK_SZ50_CODE, CN_DK_SZ50_SECID, CN_DK_COLS[1]),
                (CN_DK_HS300_CODE, CN_DK_HS300_SECID, CN_DK_COLS[2]),
                (CN_DK_ZZ500_CODE, CN_DK_ZZ500_SECID, CN_DK_COLS[3]),
                (CN_DK_CYB_CODE, CN_DK_CYB_SECID, CN_DK_COLS[4]),
            ]
            for idx_code, secid, col_name in _dk_fetch_list:
                idx_df, src = _fetch_cn_dk_price_index(idx_code, secid)
                # DK用价格指数(非H前缀): EastMoney/Sina优先, csindex仅兜底。
                # 日K线缺少今天数据时，用实时行情补充
                if include_cn_live_snapshot:
                    idx_df = _supplement_today_close(idx_df, secid, _bj_today, msg)
                else:
                    idx_df = _drop_cn_unconfirmed_today(idx_df)
                dk_dfs[col_name] = idx_df.rename(columns={"close": col_name})
                msg.write(f"  {CN_DK_NAMES[col_name]}: {idx_df.index[0].strftime('%Y-%m-%d')}~{idx_df.index[-1].strftime('%Y-%m-%d')} [{src}]\n")
                time.sleep(0.2)
            cn_dk_raw_close = _build_cn_dk_close_frame(dk_dfs)
            if _cn_after_close and not include_cn_live_snapshot:
                _assert_price_frame_columns_fresh(
                    cn_dk_raw_close,
                    CN_DK_COLS,
                    expected_date=pd.Timestamp(_bj_today),
                    max_lag_days=0,
                    label="A-DK收盘价格",
                    names=CN_DK_NAMES,
                )
            cn_dk_close = cn_dk_raw_close
            msg.write(f"  A-DK合并截至: {cn_dk_close.index[-1].strftime('%Y-%m-%d')}\n")
        except poe.BotError:
            raise
        except _fetch_or_bot_errors() as e:
            raise poe.BotError(f"A-DK多空数据获取失败: {e}") from e
        return cn_close, cn_dk_close, us_rot_close, us_prod_daily

    def _cached_fetch_data(self, msg, include_cn_live_snapshot=False, include_us_live_snapshot=False):
        cache = getattr(self, "_request_data_cache", None)
        if cache is None:
            cache = {}
            self._request_data_cache = cache
        key = (bool(include_cn_live_snapshot), bool(include_us_live_snapshot))
        if key not in cache:
            cache[key] = self._fetch_data(
                msg,
                include_cn_live_snapshot=include_cn_live_snapshot,
                include_us_live_snapshot=include_us_live_snapshot,
            )
        else:
            _debug_write(msg, "  DEBUG: reuse fetched market data for this request\n")
        return cache[key]

    def _cached_run_strategies(self, cn_close, cn_dk_close, us_rot_close, us_prod_daily,
                               allow_unresolved_suba_volume=False,
                               strict_subb_open_execution=True):
        cache = getattr(self, "_request_strategy_cache", None)
        if cache is None:
            cache = {}
            self._request_strategy_cache = cache
        key = (
            id(cn_close),
            id(cn_dk_close),
            id(us_rot_close),
            id(us_prod_daily),
            bool(allow_unresolved_suba_volume),
            bool(strict_subb_open_execution),
        )
        if key not in cache:
            cache[key] = self._run_strategies(
                cn_close,
                cn_dk_close,
                us_rot_close,
                us_prod_daily,
                allow_unresolved_suba_volume=allow_unresolved_suba_volume,
                strict_subb_open_execution=strict_subb_open_execution,
            )
        return cache[key]

    def _run_strategies(self, cn_close, cn_dk_close, us_rot_close, us_prod_daily,
                        allow_unresolved_suba_volume=False,
                        strict_subb_open_execution=True):
        # v6.1: Sub-A uses bias momentum + R² + bond ETF
        cn_close_with_bond = _add_cn_bond_column(cn_close, context="Sub-A国债避险")
        suba_single_gate = (
            _build_suba_single_strategy_gates(cn_close_with_bond)
            if CN_SA_SINGLE_GATE_ENABLED
            else None
        )
        cn_result = run_cn_strategy(
            cn_close_with_bond,
            CN_EQUITY_CODES,
            single_asset_signal_gate=suba_single_gate,
        )
        if CN_SA_CASH_OVERLAY_ENABLED:
            cn_result = apply_suba_cash_peak_decay_overlay(
                cn_result,
                cn_close_with_bond,
                decay_ratio_threshold=CN_SA_CASH_OVERLAY_DECAY_RATIO,
                recovery_ratio_threshold=CN_SA_CASH_OVERLAY_RECOVERY_RATIO,
                commission=CN_COMMISSION,
            )
        if CN_SA_SAME_SIDE_OVERHEAT_ENABLED:
            cn_result = apply_suba_same_side_overheat_overlay(
                cn_result,
                cn_close_with_bond,
                enter_threshold=CN_SA_SAME_SIDE_OVERHEAT_ENTER,
                exit_threshold=CN_SA_SAME_SIDE_OVERHEAT_EXIT,
                derisk_scale=CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE,
            )
        suba_volume_signal = None
        suba_volume_feature = None
        if CN_SA_VOLUME_OVERLAY_ENABLED:
            try:
                suba_volume_signal, suba_volume_feature = _load_suba_volume_signal()
                suba_volume_feature = _annotate_rule_freshness(
                    suba_volume_feature,
                    expected_date=cn_close_with_bond.index.max(),
                    rule_key="suba_volume",
                )
                if (
                    not allow_unresolved_suba_volume
                    and _suba_volume_feature_has_unresolved(suba_volume_feature)
                ):
                    raise poe.BotError(
                        "Sub-A成交额风控存在不可判定项，正式回测/绩效查询中止。"
                        "信号查询可降级显示“0%仓位扩展风控不可判定，不应按正常仓位执行”。"
                    )
                cn_result = _apply_suba_volume_overlay_policy(
                    cn_result,
                    cn_close_with_bond,
                    suba_volume_signal,
                    suba_volume_feature,
                    allow_unresolved_suba_volume=allow_unresolved_suba_volume,
                )
            except _fetch_or_bot_errors() as exc:
                if isinstance(exc, poe.BotError):
                    raise
                if not allow_unresolved_suba_volume:
                    raise poe.BotError(
                        "Sub-A成交额风控数据不可用，正式回测/绩效查询已中止；"
                        "信号查询可降级显示“成交额风控不可判定”。"
                    ) from exc
                cn_result = _mark_suba_volume_unavailable(cn_result, exc)
        cn_v77_result = cn_result
        cn_new_result = run_v78_suba_new_tv10(cn_close_with_bond, CN_EQUITY_CODES)
        if CN_SA_VOLUME_OVERLAY_ENABLED and suba_volume_signal is not None:
            cn_new_result = _apply_v78_suba_new_volume_overlay_policy(
                cn_new_result,
                cn_close_with_bond,
                suba_volume_signal,
                suba_volume_feature,
                allow_unresolved_suba_volume=allow_unresolved_suba_volume,
            )
        cn_result = blend_v78_suba_results(cn_v77_result, cn_new_result)
        # v6.1: Sub-A-DK uses multi-pair Top-1
        cn_dk_result = run_dk_strategy(cn_close, cn_dk_close)
        if CN_DK_PAIR_SCORE_DECAY_ENABLED:
            cn_dk_result = apply_dk_pair_score_peak_decay_overlay(
                cn_dk_result,
                decay_ratio_threshold=CN_DK_PAIR_SCORE_DECAY_RATIO,
                recovery_ratio_threshold=CN_DK_PAIR_SCORE_RECOVERY_RATIO,
                derisk_scale=CN_DK_PAIR_SCORE_DERISK_SCALE,
                commission=CN_DK_COMMISSION,
            )
        if CN_DK_SAME_SIDE_OVERHEAT_ENABLED:
            cn_dk_result = apply_dk_same_side_overheat_overlay(
                cn_dk_result,
                enter_threshold=CN_DK_SAME_SIDE_OVERHEAT_ENTER,
                exit_threshold=CN_DK_SAME_SIDE_OVERHEAT_EXIT,
                derisk_scale=CN_DK_SAME_SIDE_OVERHEAT_DERISK_SCALE,
                commission=CN_DK_COMMISSION,
            )
        if CN_DK_RISK_GATE_ENABLED:
            cn_dk_result = apply_dk_drawdown_risk_gate(
                cn_dk_result,
                enter=CN_DK_RISK_GATE_ENTER,
                scale_defense=CN_DK_RISK_GATE_DEFENSE_SCALE,
                exit_value=CN_DK_RISK_GATE_EXIT,
                cooldown_days=CN_DK_RISK_GATE_COOLDOWN_DAYS,
            )
        cn_dk_result = _rebuild_dk_effective_execution_costs(
            cn_dk_result,
            cn_dk_result.attrs.get("pair_data", {}),
            CN_DK_COMMISSION,
        )
        cn_dk_v77_result = cn_dk_result
        cn_dk_new_result = run_v78_adk_new_primary(cn_close, cn_dk_close)
        cn_dk_result = blend_v78_adk_results(cn_dk_v77_result, cn_dk_new_result)
        us_rot_official = run_us_rotation_mix(
            us_rot_close,
            US_ROT_BASE_POOL,
            top_n=US_ROT_TOP_N,
            us_open=getattr(self, "_us_open", None),
            ranking_code_selector=_subb_active_ranking_codes,
            weight_assets=US_ROT_POOL,
            strict_open_execution=strict_subb_open_execution,
        )
        us_rot_ema = run_subb_v75_ema_base7_rotation(
            us_rot_close,
            base_codes=US_ROT_POOL,
            top_n=US_ROT_TOP_N,
            us_open=getattr(self, "_us_open", None),
            weight_assets=US_ROT_POOL,
            strict_open_execution=strict_subb_open_execution,
        )
        us_rot_result = blend_subb_v75_results(us_rot_official, us_rot_ema)
        us_rot_v77_result = us_rot_result
        us_rot_bias_result = run_v78_subb_new_line(
            us_rot_close,
            line="bias",
            us_open=getattr(self, "_us_open", None),
            strict_open_execution=strict_subb_open_execution,
        )
        us_rot_logvol_result = run_v78_subb_new_line(
            us_rot_close,
            line="logvol",
            us_open=getattr(self, "_us_open", None),
            strict_open_execution=strict_subb_open_execution,
        )
        us_rot_result = blend_v78_subb_results(us_rot_v77_result, us_rot_bias_result, us_rot_logvol_result)
        if US_ROT_VOLREG_ENABLED and "SPY" in us_rot_close.columns:
            us_rot_result = apply_vol_regime_overlay(
                us_rot_result,
                us_rot_close["SPY"],
                close_df=us_rot_close,
                us_open=getattr(self, "_us_open", None),
                strict_open_execution=strict_subb_open_execution,
            )
        if SUBB_DBC_PROFIT_GUARD_ENABLED:
            us_rot_result = apply_subb_dbc_profit_guard_overlay(
                us_rot_result,
                us_rot_close,
                us_open=getattr(self, "_us_open", None),
                strict_open_execution=strict_subb_open_execution,
            )
        prod_monthly = prod_sig_a = prod_sig_b = prod_nav = prod_details = None
        if _subc_enabled():
            prod_monthly = us_prod_daily.resample("M").last()
            _last_daily = us_prod_daily.index[-1]
            _last_monthly_period = prod_monthly.index[-1].to_period("M")
            _today_period = pd.Timestamp(beijing_now().date()).to_period("M")
            if _last_daily.to_period("M") == _last_monthly_period == _today_period:
                prod_monthly = prod_monthly.iloc[:-1]
            prod_sig_a = make_abs_mom_signals(prod_monthly, PROD_ABS_MOM_LB)
            prod_sig_b = make_sma_signals(prod_monthly, PROD_SMA_WINDOW, PROD_SMA_BAND)
            if not PROD_USE_TIMING:
                prod_sig_a = pd.DataFrame(1.0, index=prod_sig_a.index, columns=prod_sig_a.columns)
                prod_sig_b = prod_sig_a.copy()
            prod_monthly_ret = prod_monthly.pct_change().dropna(how="all")
            cash_ret = prod_monthly_ret[PROD_CASH] if PROD_CASH in prod_monthly_ret.columns else pd.Series(0, index=prod_monthly_ret.index)
            prod_nav, prod_details = simulate_prod_btc_phased(
                prod_monthly_ret, prod_sig_a, cash_ret, PROD_REBAL_MONTH,
                sig_b=prod_sig_b, blend_a=PROD_BLEND_A, commission=PROD_COMMISSION)
        return cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details
    def _compute_signal_data(self, cn_close, cn_dk_close, us_rot_close, us_prod_daily):
        cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details = \
            self._cached_run_strategies(
                cn_close,
                cn_dk_close,
                us_rot_close,
                us_prod_daily,
                allow_unresolved_suba_volume=True,
            )
        cn_date = cn_close.index[-1]
        cn_display_state = _suba_signal_display_state(cn_result, -1)
        cn_current = cn_display_state["current_holding"]
        is_cn_signal = bool(cn_display_state["is_signal"])
        # v6.1: compute bias momentum and R² for display
        cn_close_with_bond = _add_cn_bond_column(cn_close, context="Sub-A展示")
        all_codes_display = CN_EQUITY_CODES + ([CN_BOND_CODE] if CN_BOND_CODE in cn_close_with_bond.columns else [])
        bias_mom_cn = {}
        r2_cn = {}
        abs_mom_cn = {}
        for code in all_codes_display:
            if code in cn_close_with_bond.columns:
                bias_mom_cn[code] = calc_bias_momentum(cn_close_with_bond[code])
                r2_cn[code] = calc_rolling_r2(cn_close_with_bond[code])
                abs_mom_cn[code] = cn_close_with_bond[code].pct_change(CN_ABS_MOM_DAY)
        # Hypothetical signal for today
        scores_today = {}
        for code in all_codes_display:
            if code in bias_mom_cn:
                val = bias_mom_cn[code].iloc[-1]
                if not np.isnan(val):
                    scores_today[code] = val
        us_date = us_rot_close.index[-1]
        us_start_idx = max(US_ROT_MAX_LB, US_ROT_VOL_LB, US_ROT_VOL_WINDOW) + 1
        us_signal_set = _us_signal_days(us_rot_close, us_start_idx)
        is_us_signal = (len(us_rot_close) - 1) in us_signal_set
        if is_us_signal:
            if _should_suppress_early_week_us_signal(us_date):
                is_us_signal = False
        rot_w_cols = [c for c in us_rot_result.columns if c.startswith("w_")]
        current_us_w = {c.replace("w_", ""): us_rot_result.iloc[-1][c] for c in rot_w_cols}
        last_confirmed_us_scale = None
        if not is_us_signal:
            sigs_confirmed_us = sorted([i for i in us_signal_set if i < len(us_rot_close) - 1])
            if sigs_confirmed_us:
                last_conf_date_us = us_rot_close.index[sigs_confirmed_us[-1]]
                if last_conf_date_us in us_rot_result.index:
                    last_conf_loc_us = us_rot_result.index.get_loc(last_conf_date_us)
                    last_confirmed_us_scale = _subb_official_scale_from_result(us_rot_result, end_loc=last_conf_loc_us)
        us_scale = _subb_official_scale_from_result(us_rot_result)
        if last_confirmed_us_scale is None:
            last_confirmed_us_scale = us_scale
        prev_us_w = None
        rebalanced_b = None
        would_rebalance = None
        turnover_b = 0.0
        hypo_prev_mix_risky_by_lb = _us_mix_prev_risky_by_lb_from_result(
            us_rot_result,
            us_date,
            include_current=False,
        )
        hypo_prev_ema_risky = _subb_v75_ema_prev_risky_from_result(
            us_rot_result,
            us_date,
            include_current=False,
        )
        hypo_ranking_codes = _subb_active_ranking_codes(us_rot_close, -1)
        model_hypo_us_w, _, _ = _us_mix_snapshot(
            us_rot_close,
            -1,
            hypo_ranking_codes,
            us_scale,
            prev_risky_by_lb=hypo_prev_mix_risky_by_lb,
            threshold=US_ROT_REBALANCE_THRESHOLD,
        )
        ema_hypo_us_w, _, _ = _subb_v75_ema_snapshot(
            us_rot_close,
            -1,
            _subb_v75_ema_scale_from_result(us_rot_result),
            ranking_codes=US_ROT_POOL,
            prev_risky=hypo_prev_ema_risky,
            threshold=US_ROT_REBALANCE_THRESHOLD,
        )
        v77_hypo_us_w = _blend_subb_v75_weight_dicts(model_hypo_us_w, ema_hypo_us_w)
        bias_hypo_us_w = _v78_subb_new_line_hypo_weights_from_blend(
            us_rot_close,
            us_rot_result,
            line="bias",
            row_idx=-1,
        )
        logvol_hypo_us_w = _v78_subb_new_line_hypo_weights_from_blend(
            us_rot_close,
            us_rot_result,
            line="logvol",
            row_idx=-1,
        )
        blended_hypo_us_w = _blend_v78_subb_weight_dicts(v77_hypo_us_w, bias_hypo_us_w, logvol_hypo_us_w)
        volreg_defense_today = bool(us_rot_result["volreg_defense"].iloc[-1]) if "volreg_defense" in us_rot_result.columns else False
        volreg_cash_today = bool(us_rot_result["volreg_cash"].iloc[-1]) if "volreg_cash" in us_rot_result.columns else False
        volreg_ratio_today = float(us_rot_result["volreg_ratio"].iloc[-1]) if "volreg_ratio" in us_rot_result.columns else None
        volreg_defense_next = _volreg_next_cash_state(volreg_defense_today, volreg_ratio_today) if US_ROT_VOLREG_ENABLED else False
        volreg_cash_next = False
        hypo_us_w = dict(blended_hypo_us_w)
        if US_ROT_VOLREG_ENABLED and volreg_defense_next:
            hypo_us_w, _ = _apply_subb_volreg_defense_scale_to_weights(hypo_us_w, True)
        hypo_us_w = _apply_subb_dbc_profit_guard_scale_to_weights(
            hypo_us_w,
            _subb_dbc_profit_guard_latest_next_scale(us_rot_result),
        )
        if is_us_signal:
            rebalanced_b = _subb_model_rebalanced_value(us_rot_result.iloc[-1])
            rloc = len(us_rot_result) - 1
            prev_us_w = {}
            if rloc > 0:
                prev_us_w = {c.replace("w_", ""): us_rot_result.iloc[rloc - 1][c] for c in rot_w_cols}
            if not prev_us_w:
                prev_us_w = {"CASH": 1.0}
            all_a = set(list(hypo_us_w.keys()) + list(prev_us_w.keys()))
            turnover_b = sum(abs(hypo_us_w.get(a, 0) - prev_us_w.get(a, 0)) for a in all_a if a not in ("BIL", "CASH"))
        else:
            all_a = set(list(hypo_us_w.keys()) + list(current_us_w.keys()))
            turnover_b = sum(abs(hypo_us_w.get(a, 0) - current_us_w.get(a, 0)) for a in all_a if a not in ("BIL", "CASH"))
            would_rebalance = _subb_should_rebalance(turnover_b, US_ROT_MIN_TURNOVER)
        dk_date = cn_dk_close.index[-1]
        # v6.1: Multi-pair DK - extract top pair and direction
        dk_top_pair = cn_dk_result["top_pair"].iloc[-1] if "top_pair" in cn_dk_result.columns else "none"
        dk_direction = int(cn_dk_result["direction"].iloc[-1]) if "direction" in cn_dk_result.columns else 0
        dk_current = cn_dk_result["holding"].iloc[-1]
        is_dk_signal = bool(cn_dk_result["is_signal"].iloc[-1]) if "is_signal" in cn_dk_result.columns else False
        dk_pair_changed = bool(cn_dk_result["pair_changed"].iloc[-1]) if "pair_changed" in cn_dk_result.columns else False
        dk_direction_changed = bool(cn_dk_result["direction_changed"].iloc[-1]) if "direction_changed" in cn_dk_result.columns else False
        dk_long_leg = cn_dk_result["long_leg"].iloc[-1] if "long_leg" in cn_dk_result.columns else None
        dk_short_leg = cn_dk_result["short_leg"].iloc[-1] if "short_leg" in cn_dk_result.columns else None
        dk_rank_current = _build_dk_rank_rows(cn_dk_result, use_shifted=True, top_n=3)
        dk_rank_today = _build_dk_rank_rows(cn_dk_result, use_shifted=False, top_n=3)
        dk_hypo_top_pair = dk_rank_today[0]["pair"] if dk_rank_today else dk_top_pair
        dk_hypo_direction = int(dk_rank_today[0]["direction"]) if dk_rank_today else dk_direction
        if prod_monthly is not None and len(prod_monthly) > 0:
            ret_n_prod = prod_monthly / prod_monthly.shift(PROD_ABS_MOM_LB) - 1
            current_am_raw = (ret_n_prod > 0).astype(float)
            current_sma_raw = _sma_raw_signals(prod_monthly, PROD_SMA_WINDOW, PROD_SMA_BAND)
            last_sig_month = current_am_raw.index[-1]
        else:
            current_am_raw = pd.DataFrame()
            current_sma_raw = pd.DataFrame()
            last_sig_month = None
        subc_vs_info = {}
        return {
            "cn_result": cn_result, "cn_dk_result": cn_dk_result,
            "us_rot_result": us_rot_result,
            "prod_monthly": prod_monthly, "prod_details": prod_details,
            "prod_sig_a": prod_sig_a, "prod_sig_b": prod_sig_b,
            "cn_date": cn_date,
            "is_cn_signal": is_cn_signal, "cn_current": cn_current,
            "cn_target": cn_display_state["target_holding"],
            "cn_post_signal_holding": cn_display_state["post_signal_holding"],
            "cn_current_display": cn_display_state.get("current_display"),
            "cn_target_display": cn_display_state.get("target_display"),
            "cn_post_display": cn_display_state.get("post_display"),
            "cn_display_state": cn_display_state,
            "bias_mom_cn": bias_mom_cn, "r2_cn": r2_cn, "abs_mom_cn": abs_mom_cn,
            "scores_today": scores_today,
            "dk_date": dk_date,
            "is_dk_signal": is_dk_signal, "dk_current": dk_current,
            "dk_top_pair": dk_top_pair, "dk_direction": dk_direction,
            "dk_pair_changed": dk_pair_changed, "dk_direction_changed": dk_direction_changed,
            "dk_long_leg": dk_long_leg, "dk_short_leg": dk_short_leg,
            "dk_rank_current": dk_rank_current, "dk_rank_today": dk_rank_today,
            "dk_hypo_top_pair": dk_hypo_top_pair, "dk_hypo_direction": dk_hypo_direction,
            "us_date": us_date, "us_signal_set": us_signal_set,
            "is_us_signal": is_us_signal, "current_us_w": current_us_w,
            "us_scale": us_scale, "last_confirmed_us_scale": last_confirmed_us_scale,
            "prev_us_w": prev_us_w, "hypo_us_w": hypo_us_w,
            "model_hypo_us_w": model_hypo_us_w, "effective_hypo_us_w": hypo_us_w,
            "ema_hypo_us_w": ema_hypo_us_w, "blended_hypo_us_w": blended_hypo_us_w,
            "hypo_prev_mix_risky_by_lb": hypo_prev_mix_risky_by_lb,
            "hypo_prev_ema_risky": hypo_prev_ema_risky,
            "rebalanced_b": rebalanced_b, "would_rebalance": would_rebalance,
            "turnover_b": turnover_b, "all_a": all_a,
            "rot_w_cols": rot_w_cols,
            "current_am_raw": current_am_raw, "current_sma_raw": current_sma_raw,
            "last_sig_month": last_sig_month,
            "subc_vs_info": subc_vs_info,
            "volreg_ratio": volreg_ratio_today,
            "volreg_cash_today": volreg_cash_today,
            "volreg_cash_next": volreg_cash_next,
            "volreg_defense_today": volreg_defense_today,
            "volreg_defense_next": volreg_defense_next,
        }

    def _handle_set_capital(self):
        existing = _scan_capital_config(poe.default_chat) or {}
        ctx_parts = []
        for s in ["Sub-A", "Sub-A-DK", "Sub-B"]:
            v = existing.get(s)
            if v:
                ctx_parts.append(f"- {s}: {v:,.0f}")
            else:
                ctx_parts.append(f"- {s}: 未设置")
        prompt = f"""解析资金设置。

资金设置支持: Sub-A, Sub-A-DK, Sub-B
V7.9 active执行权重: Sub-A 15%, Sub-A-DK 15%, 微盘 10%(v2.0 target-vol), Sub-D 20%(v1.1 six-ETF), Sub-B 40%
注意: Sub-A和Sub-A-DK使用人民币, Sub-B使用美元；微盘和Sub-D由独立脚本处理，不在本资金配置里设置

当前已设置:
{chr(10).join(ctx_parts)}

用户输入: {poe.query.text}

输出```json格式:
```json
{{
  "Sub-A": 数字或null,
  "Sub-A-DK": 数字或null,
  "Sub-B": 数字或null,
  "Sub-D": null,
  "Sub-C": null
}}
```

规则:
1. 用户说"Sub-B 5万美元" -> Sub-B: 50000
2. 用户分别指定人民币和美元金额 -> 人民币金额按Sub-A:Sub-A-DK=15:15拆分, 美元金额默认给Sub-B
   例: "人民币300万, 美元100万" -> Sub-A: 1500000, Sub-A-DK: 1500000, Sub-B: 1000000, Sub-D: null, Sub-C: null
3. 用户说"总共100万, 按V7.7比例" (未区分币种) -> Sub-A: 150000, Sub-A-DK: 150000, Sub-B: 400000, Sub-D: null, Sub-C: null（微盘10%和Sub-D 20%由独立脚本处理）
4. 用户只设置部分策略 -> 未提到的填null(保持之前的设置)
5. "万"=10000, "百万"=1000000, "千"=1000
6. 金额只填数字(不带货币符号), 单位统一为该策略的对应货币(A股=人民币, 美股=美元)
7. 用户说"总共10万美元给美股" -> 默认全部给Sub-B
8. 关键: 人民币/RMB/CNY -> 只分给Sub-A和Sub-A-DK; 美元/USD -> 只分给Sub-B
9. Sub-D和Sub-C不由本资金配置解析；即使用户提到也输出null"""

        parsed = _parse_simple_capital_config(poe.query.text)
        with _sm() as msg:
            w = msg.write
            w("⏳ 正在解析资金设置...\n")
        response = (
            types.SimpleNamespace(text=json.dumps(parsed, ensure_ascii=False))
            if parsed is not None
            else types.SimpleNamespace(text=_call_llm_text_or_raise(prompt, "资金配置"))
        )
        try:
            parsed = _parse_json_from_response(response.text, [])
        except (json.JSONDecodeError, ValueError):
            raise poe.BotError(
                "无法解析资金设置，请用更明确的语言，例如:\n"
                "- 设置资金 Sub-B 5万美元\n"
                "- 设置资金 A股共20万 美股共8万美元\n"
                "- 设置资金 总共100万人民币 按默认比例")
        config = dict(existing)
        for s in ["Sub-A", "Sub-A-DK", "Sub-B"]:
            v = parsed.get(s)
            if v is not None and isinstance(v, (int, float)) and v > 0:
                config[s] = v
        currency = {"Sub-A": "¥", "Sub-A-DK": "¥", "Sub-B": "$"}
        with _sm() as msg:
            w = msg.write
            w("## 💰 资金配置已更新\n\n| 策略 | 资金 | active权重 |\n|:-|-----:|:-|\n")
            for s in ["Sub-A", "Sub-A-DK", "Sub-B"]:
                v = config.get(s)
                c = currency[s]
                _sw = STRATEGY_WEIGHTS[s]
                if v:
                    w(f"| {s} | {c}{v:,.0f} | {_sw:.0%} |\n")
                else:
                    w(f"| {s} | 未设置 | {_sw:.0%} |\n")
            w("\n✅ 信号查询时将自动计算目标持仓数量\n")
            w(_build_capital_marker(config))

    def _handle_set_position(self):
        existing = _scan_position_config(poe.default_chat) or {}
        # Check for CSV attachment
        csv_data = None
        for att in poe.query.attachments:
            if att.name and att.name.lower().endswith('.csv'):
                csv_data = att.get_contents().decode('utf-8', errors='replace')
                break

        cap_updated = False
        if csv_data:
            # Parse CSV directly
            try:
                df = pd.read_csv(io.StringIO(csv_data))
                df.columns = [c.strip() for c in df.columns]
                config = dict(existing)
                col_map = _position_csv_column_map(df.columns)

                if 'etf' not in col_map or ('shares' not in col_map and 'amount' not in col_map):
                    raise poe.BotError(
                        "CSV格式不正确。需要至少包含ETF和数量两列。\n"
                        "支持的列名:\n"
                        "- ETF列: ETF, ticker, 代码, 标的, code, symbol\n"
                        "- 数量列: 数量, shares, qty, 股数, 持仓, quantity\n"
                        "- 金额列: amount, 金额, 市值, market_value\n"
                        "- 策略列(可选): 策略, strategy, sub")

                if 'strategy' in col_map:
                    for _, row in df.iterrows():
                        strat = str(row[col_map['strategy']]).strip()
                        etf = str(row[col_map['etf']]).strip()
                        if strat not in config:
                            config[strat] = {}
                        config[strat][etf] = _position_csv_entry(row, col_map)
                else:
                    query_text = poe.query.text.strip()
                    strategy = None
                    for s in ["Sub-A-DK", "Sub-A", "Sub-B"]:
                        if s.lower() in query_text.lower() or s in query_text:
                            strategy = s
                            break
                    if not strategy:
                        us_rot_etfs = set(_ROT_PROXY_TO_LIVE.keys()) | set(_ROT_PROXY_TO_LIVE.values())
                        etfs = [str(r).strip().upper() for r in df[col_map['etf']]]
                        if any(e in us_rot_etfs for e in etfs):
                            strategy = "Sub-B"
                        else:
                            raise poe.BotError(
                                "无法判断仓位属于哪个策略。请在消息中指明策略，例如:\n"
                                "\"设置仓位 Sub-B\" 并附上CSV文件")
                    config[strategy] = {}
                    for _, row in df.iterrows():
                        etf = str(row[col_map['etf']]).strip()
                        config[strategy][etf] = _position_csv_entry(row, col_map)
            except poe.BotError:
                raise
            except Exception as e:
                raise poe.BotError(f"CSV解析失败: {e}")
        else:
            # Use LLM to parse text
            ctx_parts = []
            for s in ["Sub-A", "Sub-A-DK", "Sub-B"]:
                v = existing.get(s)
                if v:
                    items_list = []
                    for k, v_ in v.items():
                        if isinstance(v_, dict) and 'amount' in v_:
                            items_list.append(f"{k}: {v_['amount']:,.0f}元")
                        else:
                            items_list.append(f"{k}: {v_}股")
                    ctx_parts.append(f"- {s}: {', '.join(items_list)}")
                else:
                    ctx_parts.append(f"- {s}: 未设置")

            prompt = f"""解析仓位设置。

V7.9可设置仓位:
Sub-A: A股轮动 - 股票资产必须使用以下价格指数代码(不要用ETF代码)，债券避险使用全收益指数:
  1.930955 = 中证红利 / 红利低波 / 红利低波100 / 中证红利低波100
  0.399006 = 创业板 / 创业板指
  1.000016 = 上证50 / 50
  1.000852 = 中证1000 / 1000
  1.000905 = 中证500 / 500
  1.H11077 = 10Y国债 / 国债
Sub-A-DK: A股多空配对 - 5个价格指数, 用户会指定做多/做空两腿:
  有效标的(用中文名作key): 中证1000, 上证50, 沪深300, 中证500, 创业板
  输出格式: {{"做多_中文名": {{"amount": 金额}}, "做空_中文名": {{"amount": 金额}}}}
  例: "做多817.5万创业板，做空817.5万中证500" -> {{"做多_创业板": {{"amount": 8175000}}, "做空_中证500": {{"amount": 8175000}}}}
  例: "做多中证1000 做空上证50 各500万" -> {{"做多_中证1000": {{"amount": 5000000}}, "做空_上证50": {{"amount": 5000000}}}}
  如果用户只给总金额不指定标的 -> {{"_total_amount": 金额}}
Sub-B: V7.9四腿综合 = 官方腿25%({US_ROT_WINDOW_WEIGHT_LABEL}) + EMA腿25%(hl{SUBB_V75_EMA_HALF_LIFE}/阈值{SUBB_V75_EMA_ABS_THRESHOLD:.0%}) + Bias腿25% + LogVol腿25%；四腿分别展示，再汇总为综合执行目标；{_v78_subb_inflation_participation_note()}

当前已设置的仓位:
{chr(10).join(ctx_parts)}

用户输入: {poe.query.text}

输出```json格式:
```json
{{
  "Sub-A": {{"指数代码": 股数或{{"amount": 金额数字}}}} 或 null,
  "Sub-A-DK": {{"做多_中文名": {{"amount": 金额}}, "做空_中文名": {{"amount": 金额}}}} 或 null,
  "Sub-B": {{"ETF代码": 股数或{{"amount": 金额数字}}}} 或 null,
  "Sub-D": null,
  "Sub-C": null
}}
```

规则:
1. 股数为整数
2. 用户只设置部分策略 -> 未提到的填null(保持之前的设置)
3. "股"=股数, "手"=100股(A股), "张"=合约张数
4. 如果用户说"清空"某策略的仓位 -> 填空字典 {{}}
5. ETF代码保持原样(区分大小写)
6. Sub-A必须用上面列出的价格指数代码(如1.930955), 不要用ETF代码(如515100)；国债仍用1.H11077全收益指数
7. Sub-A-DK必须用"做多_"和"做空_"前缀+中文名(如"做多_创业板"), 两腿都要列出
8. 如果用户指定某个标的的金额(万/百万/元/人民币/美元等), 对应标的输出 {{"amount": 金额数字(转为基本单位,元或美元)}}
   例: "中证1000持仓200万" -> "中证1000": {{"amount": 2000000}}
   如果用户说"100股", 直接输出整数 100
9. 关键: 如果用户只指定策略的总金额, 不列出具体标的(如"Sub-B总共50万"), 输出 {{"_total_amount": 金额数字}}
   例: "Sub-B总共50万美元" -> "Sub-B": {{"_total_amount": 500000}}
   注意: _total_amount表示策略总金额, 和具体标的的amount不同
10. Sub-D和Sub-C不由本仓位配置解析；即使用户提到也输出null"""

            parsed = _parse_simple_position_config(poe.query.text)
            with _sm() as msg:
                msg.write("⏳ 正在解析仓位设置...\n")
            response = (
                types.SimpleNamespace(text=json.dumps(parsed, ensure_ascii=False))
                if parsed is not None
                else types.SimpleNamespace(text=_call_llm_text_or_raise(prompt, "仓位配置"))
            )
            try:
                parsed = _parse_json_from_response(response.text, [])
            except (json.JSONDecodeError, ValueError):
                raise poe.BotError(
                    "无法解析仓位设置，请用更明确的语言，例如:\n"
                    "- 设置仓位 Sub-B: QQQM 100股 GLDM 50股 PDBC 200股\n"
                    "- 设置仓位 Sub-A: 红利低波100 750万\n"
                    "- 设置仓位 Sub-A-DK: 做多创业板800万 做空中证500 800万\n"
                    "- 或上传CSV文件(列: ETF, 数量)")
            config = dict(existing)
            cap_config = _scan_capital_config(poe.default_chat) or {}
            cap_updated = False
            for s in ["Sub-A", "Sub-A-DK", "Sub-B"]:
                v = parsed.get(s)
                if v is not None and isinstance(v, dict):
                    # Check for total amount (user specified strategy total, not per-ETF)
                    if '_total_amount' in v:
                        total = float(v['_total_amount'])
                        if total > 0:
                            cap_config[s] = total
                            cap_updated = True
                    else:
                        new_pos = {}
                        for k, v_ in v.items():
                            if isinstance(v_, dict) and 'amount' in v_:
                                amt = float(v_['amount'])
                                if amt > 0:
                                    new_pos[k] = {"amount": amt}
                            elif isinstance(v_, (int, float)) and v_ > 0:
                                new_pos[k] = int(float(v_))
                        config[s] = new_pos

        currency_label = {"Sub-A": "A股", "Sub-A-DK": "A股(多空)", "Sub-B": "美股"}
        currency_symbol = {"Sub-A": "¥", "Sub-A-DK": "¥", "Sub-B": "$"}
        with _sm() as msg:
            w = msg.write
            w("## 📊 仓位配置已更新\n\n")
            for s in ["Sub-A", "Sub-A-DK", "Sub-B"]:
                pos = config.get(s)
                if pos:
                    ccy = currency_symbol.get(s, "")
                    w(f"### {s} ({currency_label[s]})\n")
                    if s == "Sub-A-DK" and any(k.startswith(("做多_", "做空_")) for k in pos):
                        w("| 方向 | 标的 | 持仓 |\n|:-|:-|--------:|\n")
                        for etf, val in sorted(pos.items()):
                            if etf.startswith("做多_"):
                                direction, name = "📈 做多", etf[3:]
                            elif etf.startswith("做空_"):
                                direction, name = "📉 做空", etf[3:]
                            else:
                                direction, name = "", etf
                            if isinstance(val, dict) and 'amount' in val:
                                w(f"| {direction} | {name} | {ccy}{val['amount']:,.0f} |\n")
                            else:
                                w(f"| {direction} | {name} | {val:,}股 |\n")
                    else:
                        w("| 标的 | 持仓 |\n|:-|--------:|\n")
                        for etf, val in sorted(pos.items()):
                            if isinstance(val, dict) and 'amount' in val:
                                w(f"| {etf} | {ccy}{val['amount']:,.0f} |\n")
                            else:
                                w(f"| {etf} | {val:,}股 |\n")
                    w("\n")
            # Show capital updates from _total_amount conversion
            if cap_updated:
                w("### 💰 资金配置（按总额设置）\n")
                for s in ["Sub-A", "Sub-A-DK", "Sub-B"]:
                    if s in cap_config and parsed.get(s) and '_total_amount' in parsed[s]:
                        ccy = currency_symbol.get(s, "")
                        w(f"- **{s}**: {ccy}{cap_config[s]:,.0f}")
                        if s == "Sub-B":
                            w("（持仓比例随信号变化，查询信号时自动计算各ETF目标数量）")
                        elif s in ("Sub-A", "Sub-A-DK"):
                            w("（持仓标的随信号变化，查询信号时自动计算目标数量）")
                        w("\n")
                w("\n")
            if not any(config.get(s) for s in ["Sub-A", "Sub-A-DK", "Sub-B"]) and not cap_updated:
                w("暂无仓位设置\n")
            w("\n✅ 信号查询时将自动显示仓位调整建议\n")
            w(_build_position_marker(config))
            if cap_updated:
                w(_build_capital_marker(cap_config))

_BOT_SETTINGS = SettingsResponse(
    allow_attachments=True,
    introduction_message=(
        "📊 **Strategy Signal V7.9 — 策略信号查询**\n\n"
        f"V7.9 active组合: Sub-A 15% + Sub-A-DK 15% + 微盘 10%(v2.0 target-vol) + Sub-D 20%(v1.1 six-ETF) + Sub-B 40%（A/ADK为双腿混合；Sub-B为四腿Top2综合；7.7原腿保留为参照组件）\n\n"
        "**信号查询：**\n"
        '- 发送 **"信号"** -> 收盘信号+Excel\n'
        '- 发送 **"实时信号"** / **"信号实时"** -> 盘中实时快照\n'
        '- 发送 **"参数"** / **"信号参数"** -> 策略参数总览\n'
        '- 发送 **"实时参数"** / **"参数实时"** -> 实时参数快照\n\n'
        "**绩效分析：**\n"
        '- 发送 **"表现核心三袖 过去两年"** / **"表现核心三袖 2024至今"** / **"表现核心三袖 最近6个月"**\n'
        '- 发送 **"净值曲线核心三袖 过去两年"** / **"净值曲线核心三袖 今年"**\n\n'
        "**💰 资金管理:** \"设置资金 Sub-B 5万美元\" -> 信号自动显示目标数量\n\n"
        "**📊 仓位管理:** \"设置仓位 Sub-B: QQQM 100股 GLDM 50股\" 或 \"设置仓位 Sub-A-DK: 做多创业板800万 做空中证500 800万\" -> 信号自动显示调整建议\n"
    ),
)
poe.update_settings(_BOT_SETTINGS)

class CombinedStrategyV78(CombinedStrategyBase):

    def _parse_date_with_llm_fallback(self, query):
        """先用正则解析日期范围，失败则用LLM解析自然语言。"""
        start, end = parse_date_range(query)
        if start is not None:
            return start, end
        # LLM fallback: 用快速模型解析自然语言日期
        try:
            now_str = pd.Timestamp.now().strftime("%Y-%m-%d")
            resp = poe.call("Grok-4.1-Fast-Non-Reasoning",
                f"从下面的文本中提取日期范围。今天是{now_str}。\n"
                f"输出```json格式:\n```json\n"
                f'{{\"start\": \"YYYY-MM-DD\", \"end\": \"YYYY-MM-DD\"}}\n```\n'
                f"如果结束日期是\"至今\"或\"现在\"，end用\"{now_str}\"。\n"
                f"如果只有年份没有月日，start用01-01，end用12-31。\n"
                f"如果只有年月没有日，start用01日，end用该月最后一天。\n"
                f"如果无法识别日期范围，start和end都输出null。\n\n"
                f"文本: {query}")
            parsed = _parse_json_from_response(resp.text, ["start", "end"])
            if parsed["start"] and parsed["end"]:
                return pd.Timestamp(parsed["start"]), pd.Timestamp(parsed["end"])
        except Exception:
            pass
        return None, None

    def _parse_all_dates_with_llm_fallback(self, query):
        """先用正则解析(支持多段)，失败则用LLM。"""
        ranges = parse_all_date_ranges(query)
        if ranges:
            return ranges
        start, end = self._parse_date_with_llm_fallback(query)
        if start is not None:
            return [(start, end)]
        return []

    @staticmethod
    def _is_date_query(query):
        """检测文本是否包含日期范围相关的模式。"""
        return bool(re.search(
            r'\d{4}[-年/.]?\d{0,2}[-月]?\s*[到至—\-~]|'
            r'\d{1,2}月\d{1,2}[日号]\s*[到至—\-~]|'
            r'至今|今年|去年|前年|'
            r'(?:最近|过去|近)\s*[一二两三四五六七八九十\d半]+\s*个?\s*[年月]|'
            r'\d{4}\s*年',
            query))

    def run(self):
        try:
            self._run_impl()
        except Exception as exc:
            with _sm() as msg:
                msg.write("## ⚠️ 查询入口失败\n\n")
                if DEBUG_MODE:
                    import traceback
                    msg.write("```text\n")
                    msg.write(traceback.format_exc())
                    msg.write("\n```\n")
                else:
                    msg.write(f"{_short_error(exc)}\n")
                msg.write("请重新发送“信号”或“实时信号”；如果仍为空，说明 Poe 在进入策略前发生运行时错误。\n")

    def _run_impl(self):
        query = poe.query.text.strip()
        query_compact = re.sub(r"\s+", "", query)
        if "净值曲线" in query:
            self._handle_nav_chart(query)
        elif re.search(r'表现|收益(?!曲线)|回撤|年化|夏普|回报', query):
            ranges = self._parse_all_dates_with_llm_fallback(query)
            if len(ranges) <= 1:
                self._handle_performance(query)
            else:
                for r in ranges:
                    self._handle_performance(query, _forced_range=r)
        elif re.search(r'收益曲线|走势', query):
            self._handle_nav_chart(query)
        elif "实时信号" in query_compact or "信号实时" in query_compact:
            self._handle_live_signal()
        elif "实时参数" in query_compact or "参数实时" in query_compact:
            self._handle_live_params()
        elif ("设置" in query or "设定" in query or "配置" in query) and "资金" in query:
            self._handle_set_capital()
        elif ("设置" in query or "设定" in query or "配置" in query) and "仓位" in query:
            self._handle_set_position()
        elif any(a.name and a.name.lower().endswith('.csv') for a in poe.query.attachments) and re.search(r'持仓|仓位', query):
            self._handle_set_position()
        elif "参数" in query:
            self._handle_params()
        elif re.search(r'信号', query) and self._is_date_query(query):
            self._handle_signal_history(query)
        elif self._is_date_query(query):
            self._handle_nav_chart(query)
            self._handle_performance(query)
        else:
            self._handle_signal()
    def _write_sub_c(self, msg, d, us_prod_daily):
        current_am_raw = d["current_am_raw"]
        current_sma_raw = d["current_sma_raw"]
        last_sig_month = d["last_sig_month"]
        if PROD_USE_TIMING:
            msg.write("### Sub-C: 美股7ETF组合 (50/50混合择时)\n")
            msg.write(f"📅 **月度信号机制**（非周度）：每月月末发出信号，次月执行。"
                     f"每个资产仓位一分为二: 50%跟AbsMom-{PROD_ABS_MOM_LB}m, "
                     f"50%跟SMA-{PROD_SMA_WINDOW}m。12月年度重平衡。\n\n")
        else:
            msg.write("### Sub-C: 7ETF (买入持有+12月再平衡)\n\n")
        sig_month_period = last_sig_month.to_period("M")
        sig_month_mask = us_prod_daily.index.to_period("M") == sig_month_period
        sig_month_trading = us_prod_daily.index[sig_month_mask]
        signal_issue_date = sig_month_trading[-1] if len(sig_month_trading) > 0 else last_sig_month
        next_month_period = sig_month_period + 1
        next_month_mask = us_prod_daily.index.to_period("M") == next_month_period
        next_month_trading = us_prod_daily.index[next_month_mask]
        exec_date = next_month_trading[0] if len(next_month_trading) > 0 else None
        if not PROD_USE_TIMING:
            _cap_config_c = _scan_capital_config(poe.default_chat)
            _sub_c_capital = _cap_config_c.get("Sub-C") if _cap_config_c else None
            _c_prices = {}
            for name, cfg in PROD_PORTFOLIO.items():
                proxy = cfg["proxy"]
                # 优先用实际ETF价格(仓位调整需要), 回退到proxy价格(回测用)
                if name in us_prod_daily.columns and name != proxy:
                    _val = us_prod_daily[name].dropna()
                    if len(_val) > 0:
                        _c_prices[name] = _val.iloc[-1]
                        continue
                if proxy in us_prod_daily.columns:
                    _c_prices[name] = us_prod_daily[proxy].dropna().iloc[-1]
            if PROD_CASH in us_prod_daily.columns:
                _bil_val = us_prod_daily[PROD_CASH].dropna()
                if len(_bil_val) > 0:
                    _c_prices[PROD_CASH] = _bil_val.iloc[-1]
            # Vol-scaling 信息
            _vs = d.get("subc_vs_info", {})
            _vs_current = _vs.get("current_scale", _vs.get("actual_scale", 1.0)) if PROD_VS_ENABLED else 1.0
            _vs_next = _vs.get("next_scale", _vs_current) if PROD_VS_ENABLED else 1.0
            _vs_rv = _vs.get("rv_latest_no_shift", _vs.get("realized_vol"))
            _vs_ts = _vs.get("next_target_scale", _vs.get("target_scale", _vs_next))
            _vs_changed = bool(_vs.get("pending_adjustment", abs(_vs_next - _vs_current) > 0.001))
            _bil_cash_w = max(1.0 - _vs_next, 0.0) if PROD_VS_ENABLED else 0.0
            if _sub_c_capital:
                _effective_capital = _sub_c_capital * _vs_next
                msg.write("| 资产 | 标签 | 基础权重 | 缩放后权重 | 目标数量 | 金额($) |\n|:-|:-|--------:|--------:|--------:|--------:|\n")
                for name, cfg in PROD_PORTFOLIO.items():
                    w_base = cfg['w']
                    w_scaled = w_base * _vs_next
                    amt = _sub_c_capital * w_scaled
                    price = _c_prices.get(name)
                    if price and price > 0:
                        qty = int(amt / price)
                        msg.write(f"| {name} | {cfg['label']} | {w_base:.0%} | {w_scaled:.1%} | {qty:,} | {amt:,.0f} |\n")
                    else:
                        msg.write(f"| {name} | {cfg['label']} | {w_base:.0%} | {w_scaled:.1%} | — | — |\n")
                if _bil_cash_w > 0.001:
                    amt = _sub_c_capital * _bil_cash_w
                    price = _c_prices.get(PROD_CASH)
                    if price and price > 0:
                        qty = int(amt / price)
                        msg.write(f"| {PROD_CASH} | Cash ETF | 0% | {_bil_cash_w:.1%} | {qty:,} | {amt:,.0f} |\n")
                    else:
                        msg.write(f"| {PROD_CASH} | Cash ETF | 0% | {_bil_cash_w:.1%} | — | — |\n")
                msg.write(f"\n💰 Sub-C资金: ${_sub_c_capital:,.0f} | 有效敞口: ${_effective_capital:,.0f} ({_vs_next:.2f}x) | 价格基于最新收盘\n")
            else:
                if PROD_VS_ENABLED:
                    msg.write("| 资产 | 标签 | 基础权重 | 缩放后权重 |\n|:-|:-|--------:|--------:|\n")
                    for name, cfg in PROD_PORTFOLIO.items():
                        w_scaled = cfg['w'] * _vs_next
                        msg.write(f"| {name} | {cfg['label']} | {cfg['w']:.0%} | {w_scaled:.1%} |\n")
                    if _bil_cash_w > 0.001:
                        msg.write(f"| {PROD_CASH} | Cash ETF | 0% | {_bil_cash_w:.1%} |\n")
                else:
                    msg.write("| 资产 | 标签 | 目标权重 | 操作 |\n|:-|:-|--------:|:-|\n")
                    for name, cfg in PROD_PORTFOLIO.items():
                        msg.write(f"| {name} | {cfg['label']} | {cfg['w']:.0%} | 始终持有 |\n")
            if PROD_VS_ENABLED:
                if _vs_changed:
                    msg.write(f"\n🟢 **杠杆调整! {_vs_current:.2f}x → {_vs_next:.2f}x | 基于最新收盘，下一美股开盘执行**\n")
                msg.write(f"\n**波动率缩放:** 当前 **{_vs_current:.2f}x**")
                if _vs_rv is not None:
                    msg.write(f" | 已实现波动率(未shift, 用于下一开盘目标): {_vs_rv:.1%}")
                msg.write(f" | 目标: {PROD_VS_TARGET_VOL:.0%}\n")
                msg.write(f"调整阈值: Δ≥{PROD_VS_THRESHOLD:.0%}（未达到阈值不调整Sub-C杠杆）\n")
                if not _vs_changed:
                    msg.write(f"✅ 杠杆: **{_vs_current:.2f}x** (下一美股开盘维持)")
                    if abs(_vs_ts - _vs_current) > 0.001:
                        msg.write(f" | 理论: {_vs_ts:.2f}x (|Δ|={abs(_vs_ts - _vs_current):.4f} < {PROD_VS_THRESHOLD:.0%}阈值)")
                    msg.write("\n")
                if _vs_next > 1.0:
                    _borrow_pct = _vs_next - 1
                    msg.write(f"📊 杠杆 {_vs_next:.2f}x: 借入{_borrow_pct:.0%}资金 | "
                              f"融资成本≈{_borrow_pct * PROD_VS_SPREAD_BPS / 100:.1f}bp/年 over rf\n")
                elif _vs_next < 1.0:
                    _cash_pct = 1 - _vs_next
                    msg.write(f"📊 减仓 {_vs_next:.2f}x: {_cash_pct:.0%}转入BIL现金\n")
            msg.write(f"\n年度再平衡: 每年{PROD_REBAL_MONTH}月\n")
            # ── Sub-C 仓位调整表 ──
            _pos_config_c = _scan_position_config(poe.default_chat)
            _sub_c_pos = _pos_config_c.get("Sub-C") if _pos_config_c else None
            if _sub_c_pos and PROD_VS_ENABLED and _vs_changed:
                # 杠杆变动: 按比例缩放当前持仓 (无需计算总市值)
                _vs_ratio = _vs_next / _vs_current if abs(_vs_current) > 1e-12 else 1.0
                msg.write(f"\n📊 **持仓调整** (杠杆 {_vs_current:.2f}x → {_vs_next:.2f}x, 比例 {_vs_ratio:.3f}):\n")
                msg.write("| ETF | 当前持仓 | 目标数量 | 调整 |\n|:-|--------:|--------:|-----:|\n")
                for etf_c in sorted(_sub_c_pos.keys()):
                    _raw_pos_c = _sub_c_pos[etf_c]
                    price_c = _c_prices.get(etf_c, 0)
                    cur_shares_c = _pos_entry_shares(_raw_pos_c, price_c)
                    if cur_shares_c == 0:
                        continue
                    if isinstance(_raw_pos_c, dict) and 'amount' in _raw_pos_c:
                        target_shares_c = int(_raw_pos_c['amount'] * _vs_ratio)
                        cur_display_c = f"${_raw_pos_c['amount']:,.0f}"
                        target_display_c = f"${target_shares_c:,.0f}"
                        adj_c = target_shares_c - int(_raw_pos_c['amount'])
                        adj_str_c = f"+${adj_c:,}" if adj_c > 0 else f"${adj_c:,}" if adj_c < 0 else "—"
                    else:
                        target_shares_c = int(cur_shares_c * _vs_ratio)
                        cur_display_c = f"{cur_shares_c:,}"
                        target_display_c = f"{target_shares_c:,}"
                        adj_c = target_shares_c - cur_shares_c
                        adj_str_c = f"+{adj_c:,} 买入" if adj_c > 0 else f"{adj_c:,} 卖出" if adj_c < 0 else "—"
                    msg.write(f"| {etf_c} | {cur_display_c} | {target_display_c} | {adj_str_c} |\n")
            _note = f"年度再平衡: 每年{PROD_REBAL_MONTH}月"
            if PROD_VS_ENABLED:
                if _vs_changed:
                    _note += f" | VS {_vs_current:.2f}x -> {_vs_next:.2f}x"
                else:
                    _note += f" | VS {_vs_next:.2f}x"
            if PROD_VS_ENABLED and _vs_next < 0.999:
                _subc_signal_text = f"风险资产{_vs_next:.0%} / BIL {_bil_cash_w:.0%}"
            elif PROD_VS_ENABLED and _vs_next > 1.001:
                _subc_signal_text = f"100%风险资产 x {_vs_next:.2f}"
            else:
                _subc_signal_text = "全部持有(无择时)，100%风险资产"
            return {
                "is_signal": True,
                "signal_text": _subc_signal_text,
                "note": _note,
            }
        else:
            msg.write(f"信号发出: **{signal_issue_date.strftime('%Y-%m-%d')}** "
                     f"({beijing_time_str(signal_issue_date, 'US')})\n")
            if exec_date is not None:
                msg.write(f"执行调仓: **{exec_date.strftime('%Y-%m-%d')}** "
                         f"({beijing_time_str(exec_date, 'US', 'open')})\n\n")
            else:
                msg.write(f"执行调仓: 次月第一个交易日（待定）\n\n")
            prev_sig_month = None
            if len(current_am_raw) >= 2:
                prev_sig_month = current_am_raw.index[-2]
            msg.write(f"| 资产 | 标签 | 权重 | AbsMom | SMA | 混合操作 | 持仓% | 变动 |\n"
                     f"|:-|:-|-----:|:-:|:-:|:-|------:|:-:|\n")
            total_hold, total_cash = 0, 0
            prev_total_cash = float("nan")
            prod_signal_parts = []
            changes_count = 0
            for name, cfg in PROD_PORTFOLIO.items():
                proxy = cfg["proxy"]
                w = cfg["w"]
                am_sv = current_am_raw.loc[last_sig_month, proxy] if proxy in current_am_raw.columns else float("nan")
                sma_sv = current_sma_raw.loc[last_sig_month, proxy] if proxy in current_sma_raw.columns else float("nan")
                prev_hold = float("nan")
                curr_hold = float("nan")
                if not pd.isna(am_sv) and not pd.isna(sma_sv):
                    curr_hold = PROD_BLEND_A * am_sv + (1 - PROD_BLEND_A) * sma_sv
                if prev_sig_month is not None:
                    prev_am = current_am_raw.loc[prev_sig_month, proxy] if proxy in current_am_raw.columns else float("nan")
                    prev_sma = current_sma_raw.loc[prev_sig_month, proxy] if proxy in current_sma_raw.columns else float("nan")
                    if not pd.isna(prev_am) and not pd.isna(prev_sma):
                        prev_hold = PROD_BLEND_A * prev_am + (1 - PROD_BLEND_A) * prev_sma
                change_str = "—"
                if not pd.isna(curr_hold) and not pd.isna(prev_hold) and abs(curr_hold - prev_hold) > 0.01:
                    change_str = "🔄"
                    changes_count += 1
                am_icon = "🟢" if am_sv == 1.0 else ("🔴" if am_sv == 0.0 else "—")
                sma_icon = "🟢" if sma_sv == 1.0 else ("🔴" if sma_sv == 0.0 else "—")
                if pd.isna(curr_hold):
                    blend_act, hold_pct = "现金(BIL)", 0.0
                elif curr_hold >= 0.99:
                    blend_act, hold_pct = f"全部持有({name})", 1.0
                    prod_signal_parts.append(name)
                elif curr_hold <= 0.01:
                    blend_act, hold_pct = "全部现金(BIL)", 0.0
                else:
                    blend_act, hold_pct = f"50%{name}+50%BIL", curr_hold
                    prod_signal_parts.append(f"{name}½")
                total_hold += w * hold_pct
                total_cash += w * (1 - hold_pct)
                if not pd.isna(prev_hold):
                    prev_total_cash = (0.0 if pd.isna(prev_total_cash) else prev_total_cash) + w * (1 - prev_hold)
                msg.write(f"| {name} | {cfg['label']} | {w:.0%} | {am_icon} | {sma_icon} "
                         f"| {blend_act} | {hold_pct:.0%} | {change_str} |\n")
            _bil_change_str = "—"
            if not pd.isna(prev_total_cash) and abs(total_cash - prev_total_cash) > 0.01:
                _bil_change_str = "🔄"
            msg.write(f"| {PROD_CASH} | Cash ETF | {total_cash:.0%} | — | — | 持有现金(BIL) | {total_cash:.0%} | {_bil_change_str} |\n")
            msg.write(f"\n风险资产 {total_hold:.0%} | 现金 {total_cash:.0%}")
            if prev_sig_month is not None:
                msg.write(f" | 较上月({prev_sig_month.strftime('%Y-%m')})有 **{changes_count}** 项变更")
            msg.write("\n")
            return {
                "is_signal": False,
                "signal_text": f"风险{total_hold:.0%}/现金{total_cash:.0%} ({','.join(prod_signal_parts[:3])}{'...' if len(prod_signal_parts) > 3 else ''})" if prod_signal_parts else "全现金",
                "note": f"信号{signal_issue_date.strftime('%m-%d')}发出,"
                        f"{'执行' + exec_date.strftime('%m-%d') if exec_date else '待执行'}",
            }
    def _handle_signal(self):
        with _sm() as msg:
            w = msg.write
            try:
                w("⏳ 正在获取信号数据...\n")
                cn_close, cn_dk_close, us_rot_close, us_prod_daily = self._cached_fetch_data(
                    msg, include_cn_live_snapshot=True, include_us_live_snapshot=True)
                w("⏳ 正在计算信号...\n")
            except Exception as exc:
                w("## 📊 操作信号（收盘确认）\n\n")
                w(f"⚠️ 信号查询失败: {_short_error(exc)}\n")
                w("请稍后重试；如果持续为空，说明 Poe 运行环境在数据抓取阶段报错。\n")
                return
        try:
            d = self._compute_signal_data(cn_close, cn_dk_close, us_rot_close, us_prod_daily)
        except Exception as exc:
            with _sm() as msg:
                w = msg.write
                w("## 📊 操作信号（收盘确认）\n\n")
                w(f"⚠️ 信号计算/展示失败: {_short_error(exc)}\n")
                if DEBUG_MODE:
                    import traceback
                    w("```text\n")
                    w(traceback.format_exc())
                    w("\n```\n")
                w("请重新发送“信号”；如果仍失败，请开启调试模式查看完整堆栈。\n")
            return
        cn_date = d["cn_date"]
        us_date = d["us_date"]
        cn_result = d["cn_result"]
        cn_dk_result = d["cn_dk_result"]
        is_us_signal = d["is_us_signal"]
        current_us_w = d["current_us_w"]
        us_scale = d["us_scale"]
        last_confirmed_us_scale = d.get("last_confirmed_us_scale", us_scale)
        bias_mom_cn = d.get("bias_mom_cn", {})
        r2_cn = d.get("r2_cn", {})
        abs_mom_cn = d.get("abs_mom_cn", {})
        us_signal_set = d["us_signal_set"]
        rot_w_cols = d["rot_w_cols"]
        us_rot_result = d["us_rot_result"]
        dk_date = d["dk_date"]
        dk_current = d["dk_current"]
        dk_top_pair = d.get("dk_top_pair", "none")
        dk_direction = d.get("dk_direction", 0)
        dk_rank_today = d.get("dk_rank_today", [])
        dk_hypo_top_pair = d.get("dk_hypo_top_pair", dk_top_pair)
        dk_hypo_direction = d.get("dk_hypo_direction", dk_direction)
        now_str = beijing_now().strftime("%Y%m%d")
        signal_info = {}
        cn_unconfirmed, bj_now = is_cn_unconfirmed_intraday_snapshot()
        us_open, _ = is_us_market_open()
        cn_data_is_today = (cn_date.date() == bj_now.date())
        dk_data_is_today = (dk_date.date() == bj_now.date())
        us_data_is_today = (us_date.date() == bj_now.date()) or \
            (us_date.date() == (bj_now - timedelta(days=1)).date() and bj_now.hour < 6)
        bj_time_str_val = bj_now.strftime('%H:%M')
        bj_date_str = bj_now.strftime('%Y-%m-%d')
        us_signal_live = is_us_signal and us_open and us_data_is_today
        us_signal_confirmed = is_us_signal and not us_signal_live
        with _sm() as msg:
            w = msg.write
            w("## 📊 操作信号（收盘确认）\n\n")
            w(f"⏱ **北京时间 {bj_date_str} {bj_time_str_val}**\n\n")
            w("### Sub-A: A股乖离动量轮动\n")
            cn_close_bj = beijing_time_str(cn_date, "CN", "close")
            w(f"数据: 东财K线 | 收盘: {cn_close_bj}")
            if cn_unconfirmed and cn_data_is_today:
                w(" ⚡盘中实时")
            w("\n")
            w(f"阈值: R²≥{CN_R2_THRESHOLD:.2f} | {CN_ABS_MOM_DAY}日动量>{CN_ABS_MOM_THRESHOLD:.0%} | 持仓切换Buffer {CN_SWITCH_BUFFER:.2f}x | Scale调整Δ≥{CN_SCALE_THRESHOLD:.2f} | MA60过热止盈{CN_SA_SAME_SIDE_OVERHEAT_ENTER:.0%}/{CN_SA_SAME_SIDE_OVERHEAT_EXIT:.0%}\n")
            _cn_intraday = cn_unconfirmed and cn_data_is_today and len(cn_result) >= 2
            _cn_display_idx = -1
            _cn_state = _suba_signal_display_state(cn_result, _cn_display_idx)
            _cn_display_date = _cn_state["display_date"]
            _cn_display_holding = _cn_state["current_holding"]
            _cn_target_holding = _cn_state["target_holding"]
            _cn_post_holding = _cn_state["post_signal_holding"]
            _cn_display_name = _cn_state.get("current_display", CN_NAMES.get(_cn_display_holding, _cn_display_holding))
            _cn_target_name = _cn_state.get("target_display", CN_NAMES.get(_cn_target_holding, _cn_target_holding))
            _cn_post_name = _cn_state.get("post_display", CN_NAMES.get(_cn_post_holding, _cn_post_holding))
            _cn_display_is_signal = bool(_cn_state["is_signal"])
            all_display_codes = CN_EQUITY_CODES + ([CN_BOND_CODE] if CN_BOND_CODE in bias_mom_cn else [])
            last_cn_sig_date = _cn_state["last_signal_date"]
            if _cn_intraday:
                w("⏸️ 今日盘中，今日收盘信号未确认\n")
                w(f"当前已生效持仓: **{_cn_display_name}**（在 {_cn_display_date.strftime('%Y-%m-%d')} 交易时段生效，来源为前一收盘确认）\n")
                w(f"上次换仓: {last_cn_sig_date.strftime('%Y-%m-%d')}\n")
                w("盘中假设信号仅在“实时信号”中显示\n\n")
            elif _cn_display_is_signal:
                w(f"✅ 信号日 ({_cn_display_date.strftime('%m-%d')})")
                w(f"\n执行前持仓: **{_cn_display_name}**\n")
                w(f"今日收盘信号: **卖出{_cn_display_name} / 买入{_cn_target_name}**（已确认，收盘价执行）\n")
                w(f"收盘执行后状态: **{_cn_post_name}**\n\n")
            else:
                w(f"⏸️ 今日无换仓 | 上次换仓: {last_cn_sig_date.strftime('%Y-%m-%d')}\n")
                w(f"持仓: **{_cn_display_name}**\n")
                w("今日收盘信号: 无变化（已确认）\n\n")
            signal_info["Sub-A"] = {
                "is_signal": bool(_cn_display_is_signal),
                "signal_text": (
                    f"执行前: {_cn_display_name}; 目标: {_cn_target_name}"
                    if _cn_display_is_signal
                    else _cn_display_name
                ),
                "note": f"{_cn_display_date.strftime('%Y-%m-%d')}收盘确认; 上次{last_cn_sig_date.strftime('%Y-%m-%d')}",
            }
            # ── Sub-A vol-scaling 杠杆显示 ──
            _cn_pending = False
            if "weight" in cn_result.columns:
                _cn_sc_rt = cn_result["weight"].iloc[_cn_display_idx]
                if "v78_suba_final_exposure" in cn_result.columns:
                    _cn_display_parts = _v78_suba_display_leg_snapshot(cn_result, _cn_display_idx)
                    w(
                        f"**Sub-A最终敞口:** **{float(_cn_display_parts['final_exposure']):.2f}x** "
                        f"= {V78_SUBA_V77_WEIGHT:.0%}×V7.7A({float(_cn_display_parts['v77_weight']):.2f}x) "
                        f"+ {V78_SUBA_NEW_TV10_WEIGHT:.0%}×NewA({float(_cn_display_parts['new_weight']):.2f}x)\n"
                    )
                else:
                    _cn_sc_raw_rt = cn_result["scale_raw"].iloc[_cn_display_idx] if "scale_raw" in cn_result.columns else _cn_sc_rt
                    _cn_base_frac_rt = cn_result["base_weight"].iloc[_cn_display_idx] if "base_weight" in cn_result.columns else _base_fraction_from_weight_and_scale(_cn_sc_rt, _cn_sc_raw_rt)
                    _cn_rv_rt = cn_result["realized_vol"].iloc[_cn_display_idx] if "realized_vol" in cn_result.columns else None
                    _cn_next_raw, _cn_next_scale, _cn_pending = _compute_next_vol_scale(
                        _cn_rv_rt, _cn_sc_raw_rt,
                        CN_TARGET_VOL, CN_MIN_LEV, CN_MAX_LEV, CN_SCALE_THRESHOLD)
                    if _cn_pending and not _cn_intraday:
                        w(f"\n🟢 **VolScale调仓! {float(_cn_sc_raw_rt):.2f}x → {_cn_next_scale:.2f}x | 最终敞口还会乘以仓位系数 | 下一交易日开盘前执行**\n")
                    w(f"**Sub-A最终敞口:** **{_cn_sc_rt:.2f}x** = VolScale **{float(_cn_sc_raw_rt):.2f}x** × 仓位系数 **{float(_cn_base_frac_rt):.2f}**")
                    if _cn_rv_rt is not None and not np.isnan(_cn_rv_rt):
                        w(f" | 已实现波动率: {_cn_rv_rt:.1%}")
                    w(f" | 目标: {CN_TARGET_VOL:.0%}\n")
                if "suba_same_side_overheat_on" in cn_result.columns:
                    _cn_oh_on = bool(cn_result["suba_same_side_overheat_on"].iloc[_cn_display_idx])
                    _cn_oh_bias = cn_result["suba_same_side_overheat_bias"].iloc[_cn_display_idx] if "suba_same_side_overheat_bias" in cn_result.columns else np.nan
                    _cn_oh_text = f" | 当前权益乖离: {_cn_oh_bias:.1%}" if pd.notna(_cn_oh_bias) else ""
                    if _cn_oh_on:
                        w(f"🛡️ **V7.7A MA60过热止盈生效:** 触发 {CN_SA_SAME_SIDE_OVERHEAT_ENTER:.0%} / 恢复 {CN_SA_SAME_SIDE_OVERHEAT_EXIT:.0%}{_cn_oh_text}\n")
                    else:
                        w(f"🟢 **V7.7A MA60过热止盈关闭:** 触发 {CN_SA_SAME_SIDE_OVERHEAT_ENTER:.0%} / 恢复 {CN_SA_SAME_SIDE_OVERHEAT_EXIT:.0%}{_cn_oh_text}\n")
                _write_suba_volume_overlay_status(msg, cn_result, _cn_display_idx, compact=True)
                _write_v78_suba_blend_table(w, cn_result, _cn_display_idx)
                _write_v78_suba_leg_signal_tables(
                    w,
                    cn_result,
                    _cn_display_idx,
                    bias_mom_cn,
                    r2_cn,
                    abs_mom_cn,
                    all_display_codes,
                    current_holding=cn_result["v78_suba_v77_holding"].iloc[_cn_display_idx] if "v78_suba_v77_holding" in cn_result.columns else _cn_display_holding,
                )
                if "v78_suba_final_exposure" not in cn_result.columns and not _cn_pending:
                    w(f"✅ 最终敞口: **{_cn_sc_rt:.2f}x** (下一交易日维持)")
                    if CN_SCALE_THRESHOLD > 0 and abs(_cn_next_raw - float(_cn_sc_raw_rt)) > 0.001:
                        w(f" | 理论: {_cn_next_raw:.2f}x (|Δ|={abs(_cn_next_raw - float(_cn_sc_raw_rt)):.4f} < {CN_SCALE_THRESHOLD}阈值)")
                    w("\n")
            # 成交量情绪（仅展示）
            _ve, _vb, _va, _vok = fetch_volume_emotion()
            if _vok:
                if _ve == -1:
                    w(f"**成交量情绪:** ❄️ **悲观** | 上证连续缩量**{_vb}天** ≥ {CN_VOL_EMOTION_BEAR}天阈值\n")
                elif _ve == 1:
                    w(f"**成交量情绪:** 🔥 **乐观** | 上证连续放量{_va}天 ≥ {CN_VOL_EMOTION_BULL}天阈值\n")
                else:
                    _streak = f"连续缩量{_vb}天" if _vb > 0 else (f"连续放量{_va}天" if _va > 0 else "无明显方向")
                    w(f"**成交量情绪:** 😐 中性 | 上证{_streak}（悲观阈值{CN_VOL_EMOTION_BEAR}天）\n")
            # 防接刀监控（仅展示）
            _kc_data2, _kc_ok2 = check_knife_catch(cn_close, CN_STOCK_CODES, CN_NAMES)
            if _kc_ok2:
                _knives2 = [v for v in _kc_data2.values() if v["is_knife"]]
                if _knives2:
                    _kn_names2 = "、".join(f"**{k['name']}**({k['ret3d']:+.1%})" for k in _knives2)
                    w(f"**防接刀:** 🔪 {_kn_names2} 近{CN_KNIFE_WINDOW}日跌超{abs(CN_KNIFE_THRESHOLD):.0%} ⚠️\n")
            w("\n---\n\n### Sub-A-DK: V7.9双子策略（V7.7正式8配对 + New all10 score-hot）\n")
            dk_close_bj = beijing_time_str(dk_date, "CN", "close")
            w(f"数据来源: 中证指数+东财K线 | 5指数；V7.7正式{len(ADK_OFFICIAL_PAIR_ORDER)}对 + New全10对 | 收盘: {dk_close_bj}")
            if cn_unconfirmed and dk_data_is_today:
                w(" ⚡盘中实时")
            w("\n")
            _dk_r2_text = f" | R²质控≥{CN_DK_R2_QUALITY_THRESHOLD:.2f}" if CN_DK_R2_QUALITY_ENABLED else ""
            w(f"阈值: {_dk_score_decay_status_text()} | Scale调整Δ≥{CN_DK_SCALE_THRESHOLD:.2f}{_dk_r2_text} | 同向过热{CN_DK_SAME_SIDE_OVERHEAT_ENTER:.0%}/{CN_DK_SAME_SIDE_OVERHEAT_EXIT:.0%}\n")
            _dk_intraday = cn_unconfirmed and dk_data_is_today and len(cn_dk_result) >= 2
            _dk_close_target_rows = _v78_adk_close_target_change_rows(cn_dk_result, -1)
            _dk_close_target_changed = any(row["changed"] for row in _dk_close_target_rows)
            if _dk_intraday:
                _dk_signal_current_idx = -1
                _dk_signal_target_idx = -1
                _dk_signal_context = "盘中假设"
            else:
                _dk_signal_current_idx = -1
                _dk_signal_target_idx = -1
                _dk_signal_context = "今日收盘已确认" if _dk_close_target_changed else "当前维持"
            _dk_effective_issue_date = cn_dk_result.index[_dk_signal_current_idx]
            _dk_effective_holding = cn_dk_result["holding"].iloc[_dk_signal_current_idx]
            _dk_effective_name = _dk_pos_str(_dk_effective_holding)
            w(f"**当前已生效双腿持仓:** **{_dk_effective_name}**（在 {_dk_effective_issue_date.strftime('%Y-%m-%d')} 交易时段生效）\n")
            if "v78_adk_final_exposure" in cn_dk_result.columns:
                if _dk_close_target_changed:
                    w("🔴 **ADK本日收盘配对/方向目标变化；按下方两腿未移位Top-1复核，勿重复执行结果表末行的昨日信号。**\n")
                else:
                    w("🟢 **ADK本日收盘配对/方向目标无变化。**\n")
            elif "adk_net_asset_exposure" in cn_dk_result.columns:
                if _adk_net_exposure_changed(cn_dk_result, _dk_signal_current_idx, _dk_signal_target_idx):
                    w("🔴 **ADK净敞口已变化：按下方“当前/目标账户级净敞口”复核执行。**\n")
                else:
                    w("🟢 **ADK净敞口无变化。**\n")
            else:
                w("⚠️ **ADK净敞口字段不可用，无法按账户级净敞口判断变化。**\n")
            if _dk_intraday:
                w("今日盘中，今日收盘信号未确认；盘中假设目标仅作实时参考。\n")
            _dk_display_idx = _dk_signal_current_idx
            _dk_target_idx = _dk_signal_target_idx
            _dk_display_is_signal = (
                _dk_close_target_changed
                if "v78_adk_final_exposure" in cn_dk_result.columns
                else bool(cn_dk_result["is_signal"].iloc[_dk_target_idx]) if "is_signal" in cn_dk_result.columns else False
            )
            signal_info["Sub-A-DK"] = {
                "is_signal": bool(_dk_display_is_signal),
                "signal_text": (
                    _v78_adk_close_target_signal_text(_dk_close_target_rows)
                    if "v78_adk_final_exposure" in cn_dk_result.columns
                    else _adk_net_exposure_signal_text(cn_dk_result, _dk_signal_current_idx, _dk_signal_target_idx)
                ),
                "note": "V7.9 ADK为双腿component-net；当前净敞口看已生效表，收盘目标看两腿未移位Top-1与各腿风控",
            }
            # ── DK vol-scaling 杠杆显示 ──
            if "weight" in cn_dk_result.columns:
                if "v78_adk_final_exposure" in cn_dk_result.columns:
                    _write_v78_adk_blend_table(w, cn_dk_result, _dk_display_idx)
                    _write_v78_adk_net_exposure_table(w, cn_dk_result, _dk_display_idx)
                    _write_v78_adk_leg_status_table(w, cn_dk_result, _dk_display_idx)
                else:
                    _dk_sc_rt = cn_dk_result["weight"].iloc[_dk_display_idx]
                    _dk_base_w_rt = cn_dk_result["base_weight"].iloc[_dk_display_idx] if "base_weight" in cn_dk_result.columns else _dk_sc_rt
                    _dk_gate_scale_rt = cn_dk_result["risk_gate_scale"].iloc[_dk_display_idx] if "risk_gate_scale" in cn_dk_result.columns else 1.0
                    _dk_gate_on_rt = bool(cn_dk_result["risk_gate_on"].iloc[_dk_display_idx]) if "risk_gate_on" in cn_dk_result.columns else False
                    _dk_gate_dd_rt = cn_dk_result["risk_gate_base_dd"].iloc[_dk_display_idx] if "risk_gate_base_dd" in cn_dk_result.columns else np.nan
                    _dk_oh_scale_rt = cn_dk_result["same_side_overheat_scale"].iloc[_dk_display_idx] if "same_side_overheat_scale" in cn_dk_result.columns else 1.0
                    _dk_oh_on_rt = bool(cn_dk_result["same_side_overheat_on"].iloc[_dk_display_idx]) if "same_side_overheat_on" in cn_dk_result.columns else False
                    _dk_oh_abs_rt = cn_dk_result["same_side_overheat_abs_bias"].iloc[_dk_display_idx] if "same_side_overheat_abs_bias" in cn_dk_result.columns else np.nan
                    _dk_volume_on_rt = bool(cn_dk_result["dk_volume_clear_active"].iloc[_dk_display_idx]) if "dk_volume_clear_active" in cn_dk_result.columns else False
                    _dk_rv_rt = cn_dk_result["realized_vol"].iloc[_dk_display_idx] if "realized_vol" in cn_dk_result.columns else None
                    # 前瞻: 用最新 realized_vol 计算若本日收盘确认后的 VolScale
                    _dk_cur_vs = _dk_get_vol_scale(cn_dk_result, _dk_display_idx if _dk_display_idx >= 0 else len(cn_dk_result) + _dk_display_idx)
                    _dk_next_raw, _dk_next_vs, _dk_pending = _compute_next_vol_scale(
                        _dk_rv_rt, _dk_cur_vs,
                        CN_DK_TARGET_VOL if CN_DK_VOL_SCALE_ENABLED else None,
                        CN_DK_MIN_LEV, CN_DK_MAX_LEV, CN_DK_SCALE_THRESHOLD)
                    if _dk_pending and not _dk_intraday:
                        # 计算若本日收盘确认后的总敞口 (VolScale变化, overlay不变)
                        _dk_next_total = _dk_sc_rt / _dk_cur_vs * _dk_next_vs if _dk_cur_vs > 1e-10 else _dk_next_vs
                        w(f"\n🟢 **杠杆调仓! VolScale {_dk_cur_vs:.2f}x → {_dk_next_vs:.2f}x | 实际敞口 {_dk_sc_rt:.2f}x → {_dk_next_total:.2f}x | 本日收盘确认后按收盘价执行**\n")
                    w(f"**ADK实际敞口:** **{_dk_sc_rt:.2f}x**")
                    w(f" | VolScale: {_dk_cur_vs:.2f}x")
                    if "same_side_overheat_scale" in cn_dk_result.columns:
                        w(f" | 同向过热: {_dk_oh_scale_rt:.2f}x")
                    if "dk_volume_clear_scale" in cn_dk_result.columns:
                        _dk_volume_status_rt = "触发" if _dk_volume_on_rt else "未触发"
                        w(f" | 成交额警示: {_dk_volume_status_rt}(不改仓位)")
                    if "risk_gate_scale" in cn_dk_result.columns:
                        w(f" | RiskGate: {_dk_gate_scale_rt:.2f}x")
                    if _dk_rv_rt is not None and not np.isnan(_dk_rv_rt):
                        w(f" | 已实现波动率: {_dk_rv_rt:.1%}")
                    w(f" | 目标: {CN_DK_TARGET_VOL:.0%}\n")
                    if "risk_gate_scale" in cn_dk_result.columns:
                        if _dk_gate_on_rt:
                            _dd_text = f" | 判断DD(risk_gate_base_dd, 非最终NAV) {_dk_gate_dd_rt:.1%} / 触发<=-{CN_DK_RISK_GATE_ENTER:.0%} / 恢复>=-{CN_DK_RISK_GATE_EXIT:.0%}" if not np.isnan(_dk_gate_dd_rt) else ""
                            w(f"🛡️ **风险闸门生效中:** 回撤触发后按 **{_dk_gate_scale_rt:.2f}x** 防守{_dd_text}\n")
                        else:
                            _dd_text = f" | 判断DD(risk_gate_base_dd, 非最终NAV) {_dk_gate_dd_rt:.1%} / 触发<=-{CN_DK_RISK_GATE_ENTER:.0%} / 恢复>=-{CN_DK_RISK_GATE_EXIT:.0%}" if not np.isnan(_dk_gate_dd_rt) else ""
                            w(f"🟢 **风险闸门关闭:** 触发<=-{CN_DK_RISK_GATE_ENTER:.0%} / 恢复>=-{CN_DK_RISK_GATE_EXIT:.0%}{_dd_text}\n")
                    if "dk_volume_clear_scale" in cn_dk_result.columns and _dk_volume_on_rt:
                        w(_dk_volume_warning_text(_dk_volume_on_rt, CN_DK_VOLUME_YELLOW_LABEL, CN_DK_VOLUME_YELLOW_MA, CN_DK_VOLUME_YELLOW_DAYS))
                    if "same_side_overheat_scale" in cn_dk_result.columns:
                        _oh_text = f" | 当前同向乖离: {_dk_oh_abs_rt:.1%}" if not np.isnan(_dk_oh_abs_rt) else ""
                        if _dk_oh_on_rt:
                            w(f"🛡️ **同向过热防守生效:** 乖离>{CN_DK_SAME_SIDE_OVERHEAT_ENTER:.0%}后按 **{_dk_oh_scale_rt:.2f}x** 防守{_oh_text}\n")
                        else:
                            w(f"🟢 **同向过热防守关闭:** 触发阈值 {CN_DK_SAME_SIDE_OVERHEAT_ENTER:.0%} / 恢复阈值 {CN_DK_SAME_SIDE_OVERHEAT_EXIT:.0%}{_oh_text}\n")
                    if not _dk_pending:
                        w(f"✅ 杠杆: **{_dk_sc_rt:.2f}x** (下一交易日维持)")
                        if CN_DK_SCALE_THRESHOLD > 0 and abs(_dk_next_raw - _dk_cur_vs) > 0.001:
                            w(f" | VolScale理论: {_dk_next_raw:.2f}x (|Δ|={abs(_dk_next_raw - _dk_cur_vs):.4f} < {CN_DK_SCALE_THRESHOLD}阈值)")
                        w("\n")
            w("\n---\n\n")
            _write_v78_adk_new_leg_then_summary(
                w,
                cn_dk_result,
                _dk_target_idx,
                use_shifted=False,
                position_context=f"{_dk_signal_context}目标",
            )
            _write_volume_warning_panel(msg, compact=True, cn_dk_result=cn_dk_result)
            _write_sp500_risk_regime_note(msg, prefer_recent_csv=True, compact=True)
            us_close_bj = beijing_time_str(us_date, "US", "close")
            w("### Sub-B: V7.9四腿综合（官方/EMA/Bias/LogVol各25%）\n")
            w(f"数据来源: Yahoo Finance日K线 | 收盘: {us_close_bj}\n")
            changed = {l: c["proxy"] for l, c in US_ROT_ASSETS.items() if l != c["proxy"]}
            if changed:
                w("实盘->proxy: " + ", ".join(f"{k}->{v}" for k, v in changed.items()) + "\n")
            w(f"阈值: 绝对动量>{US_ROT_ABS_THRESHOLD:.0%} | 调仓保护{US_ROT_REBALANCE_THRESHOLD:.2f}x | VolReg降档资产{_subb_volreg_scaled_assets_text()} 进/出{US_ROT_VOLREG_THRESHOLD:.1f}/{US_ROT_VOLREG_EXIT_THRESHOLD:.1f} scale={US_ROT_VOLREG_DEFENSE_SCALE:.2f}\n")
            w(f"{_v78_subb_default_rule_text()}\n")
            _subb_volume_warning = _v78_subb_volume_warning(us_rot_result)
            if _subb_volume_warning:
                w(f"{_subb_volume_warning}\n")
            w("下方先展示四腿贡献，再汇总为综合执行目标。\n")
            # VolReg风控状态
            _vr = d.get("volreg_ratio")
            _vr_defense = d.get("volreg_defense_today", False)
            _vr_defense_next = d.get("volreg_defense_next", _vr_defense)
            if US_ROT_VOLREG_ENABLED and _vr is not None:
                if _vr > US_ROT_VOLREG_THRESHOLD:
                    w(f"🟢 **VolReg风险过热:** SPY波动率比={_vr:.2f} > 进入阈值{US_ROT_VOLREG_THRESHOLD}，明日{_subb_volreg_scaled_assets_text()}仓位x{US_ROT_VOLREG_DEFENSE_SCALE:.2f}，差额进BIL\n")
                elif _vr_defense and _vr >= US_ROT_VOLREG_EXIT_THRESHOLD:
                    w(f"🟡 **VolReg风险过热:** 今日已降档 | 当前SPY波动率比={_vr:.2f} ≥ 退出阈值{US_ROT_VOLREG_EXIT_THRESHOLD}，明日继续降档\n")
                elif _vr_defense:
                    w(f"🟢 **VolReg风险过热:** 今日已降档 | 当前SPY波动率比={_vr:.2f} < 退出阈值{US_ROT_VOLREG_EXIT_THRESHOLD}，明日恢复正常\n")
                else:
                    w(f"🟢 **VolReg风险过热:** SPY波动率比={_vr:.2f} < 进入阈值{US_ROT_VOLREG_THRESHOLD}，正常\n")
                if _vr_defense_next and not _vr_defense:
                    w(f"📌 VolReg后实际执行目标: **{_subb_volreg_scaled_assets_text()} x{US_ROT_VOLREG_DEFENSE_SCALE:.2f}，差额BIL**\n")
            _write_subb_dbc_profit_guard_status(w, us_rot_result, -1)
            if us_signal_confirmed:
                _last_us_sig_date = us_date
            else:
                _prev_us_sigs = sorted([i for i in us_signal_set if i < len(us_rot_close) - 1])
                _last_us_sig_date = us_rot_close.index[_prev_us_sigs[-1]] if _prev_us_sigs else None
            _us_sig_w = dict(current_us_w)
            _us_prev_w = {"BIL": 1.0}
            _us_rebalanced = False
            _us_sig_scale = us_scale
            if _last_us_sig_date and _last_us_sig_date in us_rot_result.index:
                _us_rloc = us_rot_result.index.get_loc(_last_us_sig_date)
                _us_sig_w = _subb_signal_display_source_weights(us_rot_result, _last_us_sig_date, rot_w_cols)
                _us_rebalanced = _subb_model_rebalanced_value(us_rot_result.loc[_last_us_sig_date])
                if _us_rloc > 0:
                    _us_prev_w = {c.replace("w_", ""): us_rot_result.iloc[_us_rloc - 1][c] for c in rot_w_cols}
                _us_sig_scale = _subb_official_scale_from_result(us_rot_result, end_loc=_us_rloc)
            _force_volreg_cash_display = _should_force_volreg_cash_display(
                US_ROT_VOLREG_ENABLED,
                False,
            )
            _us_display_w, _us_all_etfs = _subb_effective_display_weights(
                _us_sig_w,
                _us_prev_w,
                force_cash=_force_volreg_cash_display,
            )
            if not _force_volreg_cash_display and len(us_rot_result) > 0:
                _guard_row = us_rot_result.iloc[-1]
                if _subb_dbc_profit_guard_pending(_guard_row):
                    _guard_target_w = _subb_dbc_profit_guard_display_target_weights(us_rot_result, -1)
                    if _guard_target_w:
                        _us_display_w = _guard_target_w
                        _us_prev_w = dict(current_us_w)
                        _us_all_etfs = set(_us_all_etfs) | set(_us_display_w) | set(_us_prev_w)
                        _us_rebalanced = True
            _us_display_turnover = sum(abs(_us_display_w.get(e, 0) - _us_prev_w.get(e, 0)) for e in _us_all_etfs if e not in ("BIL", "CASH"))
            _us_schedule = _coerce_session_index(getattr(self, "_us_open", None))
            if _us_schedule is None:
                _us_schedule = _coerce_session_index(us_rot_close)
            _us_exec_happened_for_display = False
            if us_signal_confirmed:
                us_exec_bj = us_exec_time_str(us_date, _us_schedule)
                exec_happened_us = _has_execution_happened(us_date, "US", bj_now, _us_schedule)
                _us_exec_happened_for_display = exec_happened_us
                w(f"✅ 信号日 (美东 {us_date.strftime('%m-%d')}) — 信号已确认\n")
                if exec_happened_us:
                    w(f"✅ 已执行 ({us_exec_bj})\n")
                else:
                    w(f"⏳ 等待执行: {us_exec_bj}\n")
                if _us_rebalanced:
                    w("📋 **调仓信号**\n\n")
                else:
                    w("📋 调仓幅度未达阈值，**维持原仓位**\n\n")
                us_sig_text = "; ".join(f"{_ROT_PROXY_TO_LIVE.get(e,e)} {_us_display_w.get(e,0):.0%}" for e in sorted(_us_all_etfs) if _us_display_w.get(e, 0) > 0.005)
                signal_info["Sub-B"] = {"is_signal": True, "signal_text": us_sig_text, "note": us_exec_bj}
            elif us_signal_live:
                w(f"⏳ 信号日 (美东 {us_date.strftime('%m-%d')})，美股未收盘，信号未确认\n")
                w("💡 美股收盘后再次查询获取确认信号\n\n")
                if _last_us_sig_date:
                    _prev_bj = beijing_time_str(_last_us_sig_date, "US", "close")
                    w(f"上次: {_prev_bj} ✅\n")
                    if _us_rebalanced:
                        w("📋 **调仓信号**\n\n")
                    else:
                        w("📋 维持原仓位\n\n")
                us_sig_text = "; ".join(f"{_ROT_PROXY_TO_LIVE.get(e,e)} {_us_display_w.get(e,0):.0%}" for e in sorted(_us_all_etfs) if _us_display_w.get(e, 0) > 0.005)
                signal_info["Sub-B"] = {"is_signal": False, "signal_text": f"当前实际:{us_sig_text}",
                                        "note": f"上次{beijing_time_str(_last_us_sig_date, 'US', 'close')}" if _last_us_sig_date else ""}
            else:
                if _last_us_sig_date:
                    _sig_bj = beijing_time_str(_last_us_sig_date, "US", "close")
                    exec_happened_us = _has_execution_happened(_last_us_sig_date, "US", bj_now, _us_schedule)
                    _us_exec_happened_for_display = exec_happened_us
                    w(f"上次: {_sig_bj}")
                    if exec_happened_us:
                        w(" ✅ 已执行\n")
                    else:
                        w(f" ⏳ 等待执行: {us_exec_time_str(_last_us_sig_date, _us_schedule)}\n")
                    if _us_rebalanced:
                        w("📋 **调仓信号**\n\n")
                    else:
                        w("📋 调仓幅度未达阈值，**维持原仓位**\n\n")
                us_sig_text = "; ".join(f"{_ROT_PROXY_TO_LIVE.get(e,e)} {_us_display_w.get(e,0):.0%}" for e in sorted(_us_all_etfs) if _us_display_w.get(e, 0) > 0.005)
                signal_info["Sub-B"] = {"is_signal": False, "signal_text": f"当前实际:{us_sig_text}",
                                        "note": f"上次{beijing_time_str(_last_us_sig_date, 'US', 'close')}" if _last_us_sig_date else ""}
            _cap_config = _scan_capital_config(poe.default_chat)
            _sub_b_capital = _cap_config.get("Sub-B") if _cap_config else None
            _pos_config = _scan_position_config(poe.default_chat)
            _sub_b_pos = _pos_config.get("Sub-B") if _pos_config else None
            _sub_b_pos = _normalize_subb_position_keys(_sub_b_pos)
            _us_latest_prices = {}
            for etf in _us_all_etfs:
                _live = _ROT_PROXY_TO_LIVE.get(etf, etf)
                # 目标数量只能用实际ETF价格；缺失/过期则不计算股数。
                _live_price = _latest_live_etf_price(
                    us_rot_close,
                    etf,
                    _live,
                    expected_date=us_rot_close.index[-1],
                    max_lag_days=0,
                )
                if _live_price is not None:
                    _us_latest_prices[_live] = _live_price
            if _sub_b_capital:
                w("| ETF | 实际权重 | 目标数量 | 金额($) | 变动 |\n|:-|--------:|--------:|--------:|-----:|\n")
            else:
                w("| ETF | 实际权重 | 变动 |\n|:-|--------:|-----:|\n")
            for etf in sorted(_us_all_etfs):
                cur = _us_display_w.get(etf, 0)
                prev = _us_prev_w.get(etf, 0)
                if cur < 0.001 and prev < 0.001:
                    continue
                diff = cur - prev
                ds = f"{diff:+.1%}" if abs(diff) > 0.001 else "—"
                live = _ROT_PROXY_TO_LIVE.get(etf, etf)
                if _sub_b_capital:
                    amt = _sub_b_capital * cur
                    price = _us_latest_prices.get(live)
                    qty = _subb_target_shares(_sub_b_capital, cur, price)
                    if qty == 0:
                        w(f"| {live} | {cur:.1%} | 0 | {amt:,.0f} | {ds} |\n")
                    elif qty is not None:
                        w(f"| {live} | {cur:.1%} | {qty:,} | {amt:,.0f} | {ds} |\n")
                    else:
                        w(f"| {live} | {cur:.1%} | 价格缺失 | {amt:,.0f} | {ds} |\n")
                else:
                    w(f"| {live} | {cur:.1%} | {ds} |\n")
            w(f"\n调仓幅度: **{_us_display_turnover:.1%}**")
            w(_subb_turnover_execution_status_text(
                _us_display_turnover,
                _us_rebalanced,
                _us_exec_happened_for_display,
            ))
            if _sub_b_capital:
                w(f"\n💰 Sub-B资金: ${_sub_b_capital:,.0f} | 价格基于最新收盘\n")
            # Position adjustments
            if _sub_b_pos:
                _all_pos_etfs = set(list(_sub_b_pos.keys()) + [_ROT_PROXY_TO_LIVE.get(e, e) for e in _us_all_etfs])
                _target_val, _missing_pos_prices, _target_source = _subb_position_adjustment_target_value(
                    _sub_b_pos,
                    _us_latest_prices,
                    _sub_b_capital,
                )
                if _missing_pos_prices:
                    if _target_source == "capital":
                        w(
                            "\n⚠️ 当前持仓中部分ETF价格缺失/过期，"
                            "不使用部分市值估算；本次按已设置Sub-B资金计算目标数量: "
                            + ", ".join(_missing_pos_prices) + "\n"
                        )
                    else:
                        w(
                            "\n⚠️ 当前持仓中部分ETF价格缺失/过期，"
                            "无法可靠计算当前持仓市值和调仓数量: "
                            + ", ".join(_missing_pos_prices) + "\n"
                        )
                if _target_val and _target_val > 0:
                    _base_label = "已设置Sub-B资金" if _target_source == "capital" else "当前持仓市值"
                    w(f"\n📊 **仓位调整** (基于{_base_label}${_target_val:,.0f}):\n")
                    w("| ETF | 当前持仓 | 目标数量 | 调整 |\n|:-|--------:|--------:|-----:|\n")
                    _adj_etfs = set(list(_sub_b_pos.keys()) + [_ROT_PROXY_TO_LIVE.get(e, e) for e in _us_all_etfs if _us_display_w.get(e, 0) > 0.005])
                    for etf_live in sorted(_adj_etfs):
                        _raw_pos = _sub_b_pos.get(etf_live, 0)
                        price = _us_latest_prices.get(etf_live, 0)
                        cur_shares = _pos_entry_shares(_raw_pos, price)
                        # Find proxy key for weight lookup
                        _proxy_key = None
                        for _pk, _lk in _ROT_PROXY_TO_LIVE.items():
                            if _lk == etf_live:
                                _proxy_key = _pk
                                break
                        _w = _us_display_w.get(_proxy_key, 0) if _proxy_key else _us_display_w.get(etf_live, 0)
                        target_shares = _subb_target_shares(_target_val, _w, price)
                        adj = None if target_shares is None else target_shares - cur_shares
                        if not _pos_entry_is_nonzero(_raw_pos) and cur_shares == 0 and (target_shares is None or target_shares == 0):
                            continue
                        if target_shares is None:
                            adj_str = "价格缺失"
                        elif _w <= 0.005 and _pos_entry_is_nonzero(_raw_pos) and isinstance(_raw_pos, dict):
                            adj_str = "卖出全部"
                        elif adj > 0:
                            adj_str = f"+{adj:,} 买入"
                        elif adj < 0:
                            adj_str = f"{adj:,} 卖出"
                        else:
                            adj_str = "—"
                        # Display: show original format for current position
                        if isinstance(_raw_pos, dict) and 'amount' in _raw_pos:
                            cur_display = f"${_raw_pos['amount']:,.0f}"
                        else:
                            cur_display = f"{cur_shares:,}"
                        target_display = "价格缺失" if target_shares is None else f"{target_shares:,}"
                        w(f"| {etf_live} | {cur_display} | {target_display} | {adj_str} |\n")
            if _last_us_sig_date:
                _sig_close_idx = us_rot_close.index.get_loc(_last_us_sig_date)
                if _sig_close_idx >= US_ROT_MAX_LB:
                    _us_sig_prev_risky_by_lb = _us_mix_prev_risky_by_lb_from_result(
                        us_rot_result,
                        _last_us_sig_date,
                        include_current=False,
                    )
                    _us_sig_ranking_codes = _subb_active_ranking_codes(us_rot_close, _sig_close_idx)
                    _us_sig_gate = _subb_inflation_gate_context(us_rot_close, _sig_close_idx)
                    _us_sig_mix_ctx = _us_mix_display_context(
                        us_rot_close,
                        _sig_close_idx,
                        _us_sig_ranking_codes,
                        _us_sig_scale,
                        prev_risky_by_lb=_us_sig_prev_risky_by_lb,
                        threshold=US_ROT_REBALANCE_THRESHOLD,
                        reference_assets=[(code, _ROT_PROXY_TO_LIVE.get(code, code) + "(通胀off参考)") for code in US_ROT_MACRO_POOL],
                    )
                    # IBIT(参考) 行仅在未纳入排名池时显示；当前 V7.7 实盘口径中 IBIT 参与 Sub-B。
                    _lb0, _lb1, _lb2 = _subb_window_lbs_for_display()
                    w(f"\n**信号日官方腿结果** ({_last_us_sig_date.strftime('%m-%d')} 收盘数据；{US_ROT_WINDOW_WEIGHT_LABEL}加权混合):\n\n")
                    w(f"| ETF | 实际排名 | {_lb0}日动量 | {_lb1}日动量 | {_lb2}日动量 | 加权动量 | 官方腿目标权重 | 官方腿入选? | 参与官方腿? |\n")
                    w("|:-|:-|------:|------:|------:|------:|------:|:-:|:-:|\n")
                    for row in _us_sig_mix_ctx["mix_rows"]:
                        _marker = " \U0001f3c6" if row["mix_selected"] else ""
                        _m130 = row["per_lb_momentum"][_lb0]
                        _m260 = row["per_lb_momentum"][_lb1]
                        _m390 = row["per_lb_momentum"][_lb2]
                        _fmt130 = f"{_m130:+.2%}" if not np.isnan(_m130) else "\u2014"
                        _fmt260 = f"{_m260:+.2%}" if not np.isnan(_m260) else "\u2014"
                        _fmt390 = f"{_m390:+.2%}" if not np.isnan(_m390) else "\u2014"
                        _avg = row["avg_momentum"]
                        _fmt_avg = f"{_avg:+.2%}" if not np.isnan(_avg) else "\u2014"
                        _mix_selected_mark_sig = "✅" if row["mix_selected"] else ""
                        _rank_text = f"加权#{row['actual_rank']}" if row.get("actual_rank") else "—"
                        w(
                            f"| {row['rank']}. {row['live_name']}{_marker} | {_rank_text} | {_fmt130} | {_fmt260} | {_fmt390} | "
                            f"{_fmt_avg} | {row['mix_weight']:.1%} | {_mix_selected_mark_sig} | ✅ |\n"
                        )
                    for row in _us_sig_mix_ctx["reference_rows"]:
                        _m130 = row["per_lb_momentum"][_lb0]
                        _m260 = row["per_lb_momentum"][_lb1]
                        _m390 = row["per_lb_momentum"][_lb2]
                        _fmt130 = f"{_m130:+.2%}" if not np.isnan(_m130) else "\u2014"
                        _fmt260 = f"{_m260:+.2%}" if not np.isnan(_m260) else "\u2014"
                        _fmt390 = f"{_m390:+.2%}" if not np.isnan(_m390) else "\u2014"
                        _avg = row["avg_momentum"]
                        _fmt_avg = f"{_avg:+.2%}" if not np.isnan(_avg) else "\u2014"
                        _rank_text = f"加权#{row['actual_rank']}" if row.get("actual_rank") else "—"
                        w(f"| 参考. {row['live_name']} | {_rank_text} | {_fmt130} | {_fmt260} | {_fmt390} | {_fmt_avg} | 0.0% | 实际排名参考 | 否 |\n")
                    if _us_sig_mix_ctx["reference_rows"]:
                        w(f"\n注: 通胀开关off时只影响官方腿。{_v78_subb_inflation_participation_note()}\n")
                    _write_v78_subb_component_leg_tables(w, us_rot_result, _last_us_sig_date)
                    _write_v78_subb_blend_table(w, us_rot_result, _last_us_sig_date)
                    w(
                        f"\n**通胀开关:** {'🟢 ON' if _us_sig_gate['pressure_on'] else '🔴 OFF'} "
                        f"(DBC {INFLATION_PRESSURE_LB}日 {_us_sig_gate.get('dbc_mom', np.nan):+.2%}, "
                        f"TLT {INFLATION_PRESSURE_LB}日 {_us_sig_gate.get('tlt_mom', np.nan):+.2%})\n"
                    )
                    w(_v78_subb_inflation_status_text(_us_sig_gate["pressure_on"]) + "\n")
                    w(f"\n**\u6ce2\u52a8\u7387\u7f29\u653e** {_us_sig_scale:.2f}x | \u4e0a\u6b21\u786e\u8ba4: {last_confirmed_us_scale:.2f}x")
                    if _us_sig_scale > 1.0:
                        w(f" (>1: \u4ec5\u653e\u5927US_ROT_FUTURES(QQQM/GLDM)\u81ea\u8eab\u6743\u91cd\uff0c\u4e0a\u9650{US_ROT_MAX_LEV:.1f}x)\n")
                    elif _us_sig_scale < 1.0:
                        w(" (<1: \u6240\u6709\u8d44\u4ea7\u7b49\u6bd4\u7f29\u51cf)\n")
                    else:
                        w("\n")
                    _thresh_line = _us_mix_threshold_check(
                        _us_sig_mix_ctx["momentum_rows"],
                        _us_sig_mix_ctx["vol_row"],
                        _us_sig_ranking_codes,
                        _us_sig_prev_risky_by_lb,
                        US_ROT_REBALANCE_THRESHOLD,
                    )
                    if _thresh_line:
                        w(f"\n**\u8c03\u4ed3\u4fdd\u62a4 ({US_ROT_REBALANCE_THRESHOLD}x, \u9010\u7a97\u53e3):** {_thresh_line}\n")
            w("\n---\n\n")
        cutoff = cn_date - timedelta(days=60)
        all_rebalances = []
        cn_rebs = extract_v78_suba_rebalances(cn_result, cn_close)
        all_rebalances.extend([r for r in cn_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        dk_rebs = extract_v78_adk_rebalances(cn_dk_result, cn_dk_close=cn_dk_close)
        all_rebalances.extend([r for r in dk_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        _us_open = getattr(self, '_us_open', None)
        us_rebs = extract_us_rot_rebalances(
            d["us_rot_result"],
            us_rot_close=us_rot_close,
            us_open=_us_open,
            since_date=cutoff,
        )
        all_rebalances.extend([r for r in us_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        volreg_rebs = extract_subb_volreg_rebalances(
            d["us_rot_result"],
            us_rot_close=us_rot_close,
            us_open=_us_open,
            since_date=cutoff,
        )
        all_rebalances.extend([r for r in volreg_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        dbc_guard_rebs = extract_subb_dbc_profit_guard_rebalances(
            d["us_rot_result"],
            us_rot_close=us_rot_close,
            us_open=_us_open,
            since_date=cutoff,
        )
        all_rebalances.extend([r for r in dbc_guard_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        prod_rebs = extract_prod_rebalances(d["prod_details"], d["prod_monthly"], us_prod_daily=us_prod_daily, us_open=_us_open)
        all_rebalances.extend([r for r in prod_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        vs_rebs = extract_subc_vs_rebalances(us_prod_daily, d.get("prod_sig_a"), d.get("prod_sig_b"), us_open=_us_open)
        all_rebalances.extend([r for r in vs_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        all_rebalances = _filter_confirmed_records(all_rebalances, bj_now=bj_now, us_schedule=_us_open)
        all_rebalances.sort(key=lambda x: x["日期"], reverse=True)
        excel_bytes = generate_signal_excel(
            now_str,
            signal_info,
            all_rebalances,
            cn_dk_result=cn_dk_result,
            adk_net_row_idx=_dk_signal_current_idx,
            adk_net_date_label="当前已生效",
        )
        filename = f"signal_{now_str}.xlsx"
        with _sm() as msg:
            w = msg.write
            msg.attach_file(
                name=filename,
                contents=excel_bytes,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            w(f"📎 Excel调仓记录: **{filename}**\n")
            if _LAST_SUBC_VS_REBALANCE_WARNING:
                w(f"⚠️ Sub-C杠杆调仓记录跳过: {_LAST_SUBC_VS_REBALANCE_WARNING}\n")
            if all_rebalances:
                w(f"含最近60天 {len(all_rebalances)} 条调仓记录（北京时间）")
            else:
                w("最近60天无调仓记录")
    def _handle_live_signal(self):
        with _sm() as msg:
            w = msg.write
            try:
                w("⏳ 正在获取实时信号数据...\n")
                cn_close, cn_dk_close, us_rot_close, us_prod_daily = self._cached_fetch_data(
                    msg, include_cn_live_snapshot=True, include_us_live_snapshot=True)
                w("⏳ 正在计算实时信号...\n")
            except Exception as exc:
                w("## 📡 实时信号\n\n")
                w(f"⚠️ 实时信号查询失败: {_short_error(exc)}\n")
                w("请稍后重试；如果持续为空，说明 Poe 运行环境在数据抓取阶段报错。\n")
                return
        try:
            d = self._compute_signal_data(cn_close, cn_dk_close, us_rot_close, us_prod_daily)
        except Exception as exc:
            with _sm() as msg:
                w = msg.write
                w("## ⚡ 实时信号\n\n")
                w(f"⚠️ 实时信号计算/展示失败: {_short_error(exc)}\n")
                if DEBUG_MODE:
                    import traceback
                    w("```text\n")
                    w(traceback.format_exc())
                    w("\n```\n")
                w("请重新发送“实时信号”；如果仍失败，请开启调试模式查看完整堆栈。\n")
            return
        cn_date = d["cn_date"]
        us_date = d["us_date"]
        is_cn_signal = d["is_cn_signal"]
        cn_current = d["cn_current"]
        cn_target = d.get("cn_target", cn_current)
        cn_post_signal_holding = d.get("cn_post_signal_holding", cn_target)
        cn_current_display = d.get("cn_current_display")
        cn_target_display = d.get("cn_target_display")
        cn_post_display = d.get("cn_post_display")
        is_us_signal = d["is_us_signal"]
        current_us_w = d["current_us_w"]
        us_scale = d["us_scale"]
        last_confirmed_us_scale = d.get("last_confirmed_us_scale", us_scale)
        hypo_us_w = d["hypo_us_w"]
        rebalanced_b = d["rebalanced_b"]
        would_rebalance = d["would_rebalance"]
        turnover_b = d["turnover_b"]
        all_a = d["all_a"]
        us_signal_set = d["us_signal_set"]
        # v6.1: bias momentum + R² display data
        bias_mom_cn = d["bias_mom_cn"]
        r2_cn = d["r2_cn"]
        abs_mom_cn = d["abs_mom_cn"]
        scores_today = d["scores_today"]
        cn_result = d["cn_result"]
        cn_dk_result = d["cn_dk_result"]
        us_rot_result = d["us_rot_result"]
        dk_date = d["dk_date"]
        is_dk_signal = d["is_dk_signal"]
        dk_current = d["dk_current"]
        dk_top_pair = d["dk_top_pair"]
        dk_direction = d["dk_direction"]
        dk_pair_changed = d.get("dk_pair_changed", False)
        dk_direction_changed = d.get("dk_direction_changed", False)
        dk_rank_current = d.get("dk_rank_current", [])
        dk_rank_today = d.get("dk_rank_today", [])
        dk_hypo_top_pair = d.get("dk_hypo_top_pair", dk_top_pair)
        dk_hypo_direction = d.get("dk_hypo_direction", dk_direction)
        cn_unconfirmed, bj_now = is_cn_unconfirmed_intraday_snapshot()
        us_open, _ = is_us_market_open()
        cn_data_is_today = (cn_date.date() == bj_now.date())
        dk_data_is_today = (dk_date.date() == bj_now.date())
        us_data_is_today = (us_date.date() == bj_now.date()) or \
            (us_date.date() == (bj_now - timedelta(days=1)).date() and bj_now.hour < 6)
        any_cn_live = cn_unconfirmed and (cn_data_is_today or dk_data_is_today)
        any_market_live = any_cn_live or (us_open and us_data_is_today)
        bj_time_str_val = bj_now.strftime('%H:%M')
        bj_date_str = bj_now.strftime('%Y-%m-%d')
        with _sm() as msg:
            w = msg.write
            w("## 📡 实时信号\n\n")
            if any_market_live:
                live_markets = []
                if any_cn_live:
                    live_markets.append("A股")
                if us_open and us_data_is_today:
                    live_markets.append("美股")
                w(f"⏱ **北京时间 {bj_date_str} {bj_time_str_val}** 实时数据快照"
                         f"（{'、'.join(live_markets)}盘中，收盘前信号可能变化）\n\n")
            else:
                w(f"⏱ **北京时间 {bj_date_str} {bj_time_str_val}** 基于收盘数据（非盘中）\n\n")
            w("### Sub-A: A股轮动\n")
            cn_close_bj = beijing_time_str(cn_date, "CN", "close")
            w(f"数据: 东财K线 | 收盘: {cn_close_bj}")
            if cn_unconfirmed and cn_data_is_today:
                w(" ⚡盘中实时")
            w("\n")
            w(f"阈值: R²≥{CN_R2_THRESHOLD:.2f} | {CN_ABS_MOM_DAY}日动量>{CN_ABS_MOM_THRESHOLD:.0%} | 持仓切换Buffer {CN_SWITCH_BUFFER:.2f}x | Scale调整Δ≥{CN_SCALE_THRESHOLD:.2f} | MA60过热止盈{CN_SA_SAME_SIDE_OVERHEAT_ENTER:.0%}/{CN_SA_SAME_SIDE_OVERHEAT_EXIT:.0%}\n")
            cn_current_name = cn_current_display or CN_NAMES.get(cn_current, cn_current)
            cn_target_name = cn_target_display or CN_NAMES.get(cn_target, cn_target)
            cn_post_signal_name = cn_post_display or CN_NAMES.get(cn_post_signal_holding, cn_post_signal_holding)
            _cn_live_row = cn_result.iloc[-1] if len(cn_result) > 0 else {}
            _cn_live_cur_exp = float(_cn_live_row.get("v78_suba_final_exposure", _cn_live_row.get("weight", 0.0)) or 0.0)
            _cn_live_tgt_exp = float(_cn_live_row.get("v78_suba_target_exposure", _cn_live_cur_exp) or _cn_live_cur_exp)
            needs_cn_trade = bool(is_cn_signal) and (
                cn_target_name != cn_current_name
                or abs(_cn_live_tgt_exp - _cn_live_cur_exp) > 1e-4
            )
            # v6.1: no cooldown, no MA filter
            if is_cn_signal:
                w(f"✅ 信号日 ({cn_date.strftime('%m-%d')})")
                w(f"\n执行前持仓: **{cn_current_name}**\n")
                w(f"假设现在收盘目标: **{cn_target_name}**（以V7.9双腿状态表/target exposure为准）")
                if needs_cn_trade:
                    if cn_target_name != cn_current_name:
                        w(" 🟢 需调整")
                    else:
                        w(" 🟢 权重调整 / 状态更新")
                else:
                    w("（无变化）")
                w(f"\n收盘执行后状态: **{cn_post_signal_name}**")
                w("\n\n")
            else:
                _past_cn_trades_live = cn_result.iloc[:-1]
                _past_cn_trades_live = _past_cn_trades_live[_past_cn_trades_live["is_signal"] == True]
                last_cn_sig_date = _past_cn_trades_live.index[-1] if len(_past_cn_trades_live) > 0 else cn_date
                w(f"⏸️ 今日无换仓 | 上次换仓: {last_cn_sig_date.strftime('%Y-%m-%d')}\n")
                w(f"持仓: **{cn_current_name}**\n")
                w(f"假设现在收盘目标: **{cn_target_name}**（以V7.9双腿状态表/target exposure为准）\n\n")
            # ── Sub-A vol-scaling 杠杆显示 (详细) ──
            _cn_pending3 = False
            if "weight" in cn_result.columns and len(cn_result) >= 2:
                _cn_sc_rt3 = cn_result["weight"].iloc[-1]
                if "v78_suba_final_exposure" in cn_result.columns:
                    _cn_display_parts3 = _v78_suba_display_leg_snapshot(cn_result, -1)
                    w(
                        f"**Sub-A最终敞口:** **{float(_cn_display_parts3['final_exposure']):.2f}x** "
                        f"= {V78_SUBA_V77_WEIGHT:.0%}×V7.7A({float(_cn_display_parts3['v77_weight']):.2f}x) "
                        f"+ {V78_SUBA_NEW_TV10_WEIGHT:.0%}×NewA({float(_cn_display_parts3['new_weight']):.2f}x)\n"
                    )
                else:
                    _cn_sc_raw_rt3 = cn_result["scale_raw"].iloc[-1] if "scale_raw" in cn_result.columns else _cn_sc_rt3
                    _cn_base_frac_rt3 = cn_result["base_weight"].iloc[-1] if "base_weight" in cn_result.columns else _base_fraction_from_weight_and_scale(_cn_sc_rt3, _cn_sc_raw_rt3)
                    _cn_rv_rt3 = cn_result["realized_vol"].iloc[-1] if "realized_vol" in cn_result.columns else None
                    _cn_next_raw3, _cn_next_scale3, _cn_pending3 = _compute_next_vol_scale(
                        _cn_rv_rt3, float(_cn_sc_raw_rt3),
                        CN_TARGET_VOL, CN_MIN_LEV, CN_MAX_LEV, CN_SCALE_THRESHOLD)
                    if _cn_pending3:
                        w(f"\n🟢 **VolScale调仓! {float(_cn_sc_raw_rt3):.2f}x → {_cn_next_scale3:.2f}x | 最终敞口还会乘以仓位系数 | 下一交易日开盘前执行**\n")
                    w(f"**Sub-A最终敞口:** **{_cn_sc_rt3:.2f}x** = VolScale **{float(_cn_sc_raw_rt3):.2f}x** × 仓位系数 **{float(_cn_base_frac_rt3):.2f}**")
                    if _cn_rv_rt3 is not None and not np.isnan(_cn_rv_rt3):
                        w(f" | 已实现波动率: {_cn_rv_rt3:.1%}")
                    w(f" | 目标: {CN_TARGET_VOL:.0%}\n")
                if "suba_same_side_overheat_on" in cn_result.columns:
                    _cn_oh_on3 = bool(cn_result["suba_same_side_overheat_on"].iloc[-1])
                    _cn_oh_bias3 = cn_result["suba_same_side_overheat_bias"].iloc[-1] if "suba_same_side_overheat_bias" in cn_result.columns else np.nan
                    _cn_oh_text3 = f" | 当前权益乖离: {_cn_oh_bias3:.1%}" if pd.notna(_cn_oh_bias3) else ""
                    if _cn_oh_on3:
                        w(f"🛡️ **V7.7A MA60过热止盈生效:** 触发 {CN_SA_SAME_SIDE_OVERHEAT_ENTER:.0%} / 恢复 {CN_SA_SAME_SIDE_OVERHEAT_EXIT:.0%}{_cn_oh_text3}\n")
                    else:
                        w(f"🟢 **V7.7A MA60过热止盈关闭:** 触发 {CN_SA_SAME_SIDE_OVERHEAT_ENTER:.0%} / 恢复 {CN_SA_SAME_SIDE_OVERHEAT_EXIT:.0%}{_cn_oh_text3}\n")
                _write_suba_volume_overlay_status(msg, cn_result, -1)
                _write_v78_suba_blend_table(w, cn_result, -1)
                _write_v78_suba_leg_signal_tables(
                    w,
                    cn_result,
                    -1,
                    bias_mom_cn,
                    r2_cn,
                    abs_mom_cn,
                    CN_EQUITY_CODES + ([CN_BOND_CODE] if CN_BOND_CODE in bias_mom_cn else []),
                    current_holding=cn_result["v78_suba_v77_holding"].iloc[-1] if "v78_suba_v77_holding" in cn_result.columns else cn_current,
                )
                if "v78_suba_final_exposure" not in cn_result.columns and not _cn_pending3:
                    w(f"✅ 最终敞口: **{_cn_sc_rt3:.2f}x** (下一交易日维持)")
                    if CN_SCALE_THRESHOLD > 0 and abs(_cn_next_raw3 - float(_cn_sc_raw_rt3)) > 0.001:
                        w(f" | 理论: {_cn_next_raw3:.2f}x (|Δ|={abs(_cn_next_raw3 - float(_cn_sc_raw_rt3)):.4f} < {CN_SCALE_THRESHOLD}阈值)")
                    w("\n")
                # 成交量情绪（仅展示）
                _ve2, _vb2, _va2, _vok2 = fetch_volume_emotion()
                if _vok2:
                    if _ve2 == -1:
                        w(f"**成交量情绪:** ❄️ **悲观** | 上证连续缩量**{_vb2}天** ≥ {CN_VOL_EMOTION_BEAR}天阈值\n")
                    elif _ve2 == 1:
                        w(f"**成交量情绪:** 🔥 **乐观** | 上证连续放量{_va2}天 ≥ {CN_VOL_EMOTION_BULL}天阈值\n")
                    else:
                        _streak2 = f"连续缩量{_vb2}天" if _vb2 > 0 else (f"连续放量{_va2}天" if _va2 > 0 else "无明显方向")
                        w(f"**成交量情绪:** 😐 中性 | 上证{_streak2}（悲观阈值{CN_VOL_EMOTION_BEAR}天）\n")
                # 防接刀监控（仅展示）
                _kc_data3, _kc_ok3 = check_knife_catch(cn_close, CN_STOCK_CODES, CN_NAMES)
                if _kc_ok3:
                    _knives3 = [v for v in _kc_data3.values() if v["is_knife"]]
                    if _knives3:
                        _kn_names3 = "、".join(f"**{k['name']}**({k['ret3d']:+.1%})" for k in _knives3)
                        w(f"**防接刀:** 🔪 {_kn_names3} 近{CN_KNIFE_WINDOW}日跌超{abs(CN_KNIFE_THRESHOLD):.0%} ⚠️\n")
            w("\n---\n\n### Sub-A-DK: V7.9双子策略（V7.7正式8配对 + New all10 score-hot）\n")
            dk_close_bj3 = beijing_time_str(dk_date, "CN", "close")
            w(f"数据来源: 中证指数+东财K线 | 5指数；V7.7正式{len(ADK_OFFICIAL_PAIR_ORDER)}对 + New全10对 | 收盘: {dk_close_bj3}")
            if cn_unconfirmed and dk_data_is_today:
                w(" ⚡盘中实时")
            w("\n")
            _dk_r2_text3 = f" | R²质控≥{CN_DK_R2_QUALITY_THRESHOLD:.2f}" if CN_DK_R2_QUALITY_ENABLED else ""
            w(f"阈值: {_dk_score_decay_status_text()} | Scale调整Δ≥{CN_DK_SCALE_THRESHOLD:.2f}{_dk_r2_text3} | 同向过热{CN_DK_SAME_SIDE_OVERHEAT_ENTER:.0%}/{CN_DK_SAME_SIDE_OVERHEAT_EXIT:.0%}\n")
            _dk_intraday3 = cn_unconfirmed and dk_data_is_today and len(cn_dk_result) >= 2
            _dk_effective_idx3 = -1
            _dk_hypo_idx3 = -1
            _dk_effective_issue_date3 = cn_dk_result.index[_dk_effective_idx3]
            _dk_effective_holding3 = cn_dk_result["holding"].iloc[_dk_effective_idx3]
            dk_current_name3 = _dk_pos_str(_dk_effective_holding3)
            w(f"**当前已生效双腿持仓:** **{dk_current_name3}**（在 {_dk_effective_issue_date3.strftime('%Y-%m-%d')} 交易时段生效）\n")
            _dk_close_target_rows3 = _v78_adk_close_target_change_rows(cn_dk_result, -1)
            _dk_close_target_changed3 = any(row["changed"] for row in _dk_close_target_rows3)
            if "v78_adk_final_exposure" in cn_dk_result.columns:
                if _dk_close_target_changed3:
                    w("🔴 **ADK若现在收盘配对/方向目标将变化；按下方两腿未移位Top-1复核，不把结果末行当作新信号。**\n")
                else:
                    w("🟢 **ADK若现在收盘配对/方向目标无变化。**\n")
            elif dk_rank_today:
                if "adk_net_asset_exposure" in cn_dk_result.columns:
                    if _adk_net_exposure_changed(cn_dk_result, _dk_effective_idx3, _dk_hypo_idx3):
                        w("🔴 **ADK净敞口将变化：若现在收盘，按下方“若现在收盘目标/账户级净敞口”执行。**\n")
                    else:
                        w("🟢 **ADK净敞口无变化。**\n")
                else:
                    w("⚠️ **ADK净敞口字段不可用，无法按账户级净敞口判断实时变化。**\n")
                w(_dk_top_pair_whitelist_warning(dk_hypo_top_pair, "今日双腿配对"))
            # ── DK vol-scaling 杠杆显示 (实时) ──
            _dk_pending3 = False
            if "v78_adk_final_exposure" in cn_dk_result.columns:
                _write_v78_adk_blend_table(w, cn_dk_result, _dk_effective_idx3)
                _write_v78_adk_net_exposure_table(w, cn_dk_result, _dk_effective_idx3)
                _write_v78_adk_leg_status_table(w, cn_dk_result, _dk_effective_idx3)
                w("\n**③ ADK双腿波动率缩放:**\n\n")
                w("ADK双腿分别执行波动率缩放；综合结果不存在单一VolScale。各腿的已实现波动率、raw/banded VolScale、overlay乘数与最终贡献见上方双腿状态表。\n")
            else:
                if "weight" in cn_dk_result.columns and len(cn_dk_result) >= 2:
                    _dk_sc_rt3 = cn_dk_result["weight"].iloc[-1]
                    _dk_rv_rt3 = cn_dk_result["realized_vol"].iloc[-1] if "realized_vol" in cn_dk_result.columns else None
                    _dk_cur_vs3 = _dk_get_vol_scale(cn_dk_result, len(cn_dk_result) - 1)
                    _dk_next_raw3, _dk_next_vs3, _dk_pending3 = _compute_next_vol_scale(
                        _dk_rv_rt3, _dk_cur_vs3,
                        CN_DK_TARGET_VOL if CN_DK_VOL_SCALE_ENABLED else None,
                        CN_DK_MIN_LEV, CN_DK_MAX_LEV, CN_DK_SCALE_THRESHOLD)
                    if _dk_pending3:
                        _dk_next_total3 = _dk_sc_rt3 / _dk_cur_vs3 * _dk_next_vs3 if _dk_cur_vs3 > 1e-10 else _dk_next_vs3
                        w(f"\n🟢 **杠杆调仓! VolScale {_dk_cur_vs3:.2f}x → {_dk_next_vs3:.2f}x | 实际敞口 {_dk_sc_rt3:.2f}x → {_dk_next_total3:.2f}x | 本日收盘确认后按收盘价执行**\n")
                    w(f"**波动率缩放:** 当前 VolScale **{_dk_cur_vs3:.2f}x** | 实际敞口 **{_dk_sc_rt3:.2f}x**")
                    if _dk_rv_rt3 is not None and not np.isnan(_dk_rv_rt3):
                        w(f" | 已实现波动率: {_dk_rv_rt3:.1%}")
                    w(f" | 目标: {CN_DK_TARGET_VOL:.0%}\n")
                    if "same_side_overheat_scale" in cn_dk_result.columns:
                        _dk_oh_scale_rt3 = cn_dk_result["same_side_overheat_scale"].iloc[-1]
                        _dk_oh_on_rt3 = bool(cn_dk_result["same_side_overheat_on"].iloc[-1])
                        _dk_oh_abs_rt3 = cn_dk_result["same_side_overheat_abs_bias"].iloc[-1]
                        _dk_oh_text_rt3 = f" | 当前同向乖离: {_dk_oh_abs_rt3:.1%}" if not np.isnan(_dk_oh_abs_rt3) else ""
                        if _dk_oh_on_rt3:
                            w(f"🛡️ **ADK同向过热防守生效:** 触发 {CN_DK_SAME_SIDE_OVERHEAT_ENTER:.0%} / 恢复 {CN_DK_SAME_SIDE_OVERHEAT_EXIT:.0%}，当前按 **{_dk_oh_scale_rt3:.2f}x** 防守{_dk_oh_text_rt3}\n")
                        else:
                            w(f"🟢 **ADK同向过热防守关闭:** 触发 {CN_DK_SAME_SIDE_OVERHEAT_ENTER:.0%} / 恢复 {CN_DK_SAME_SIDE_OVERHEAT_EXIT:.0%}{_dk_oh_text_rt3}\n")
                    if "dk_volume_clear_scale" in cn_dk_result.columns:
                        _dk_volume_on_rt3 = bool(cn_dk_result["dk_volume_clear_active"].iloc[-1])
                        _dk_volume_status_rt3 = "触发" if _dk_volume_on_rt3 else "未触发"
                        w(f"**成交额警示:** {_dk_volume_status_rt3}（仅提示，不改仓位）")
                        if _dk_volume_on_rt3:
                            w("\n" + _dk_volume_warning_text(_dk_volume_on_rt3, CN_DK_VOLUME_YELLOW_LABEL, CN_DK_VOLUME_YELLOW_MA, CN_DK_VOLUME_YELLOW_DAYS).rstrip())
                        w("\n")
                    if "risk_gate_scale" in cn_dk_result.columns:
                        _dk_gate_scale_rt3 = cn_dk_result["risk_gate_scale"].iloc[-1]
                        _dk_gate_on_rt3 = bool(cn_dk_result["risk_gate_on"].iloc[-1])
                        _dk_gate_dd_rt3 = cn_dk_result["risk_gate_base_dd"].iloc[-1]
                        _dd_text3 = f" | 判断DD(risk_gate_base_dd, 非最终NAV) {_dk_gate_dd_rt3:.1%} / 触发<=-{CN_DK_RISK_GATE_ENTER:.0%} / 恢复>=-{CN_DK_RISK_GATE_EXIT:.0%}" if not np.isnan(_dk_gate_dd_rt3) else ""
                        if _dk_gate_on_rt3:
                            w(f"🛡️ **RiskGate生效:** 当前按 **{_dk_gate_scale_rt3:.2f}x** 防守{_dd_text3}\n")
                        else:
                            w(f"🟢 **RiskGate关闭:** 触发<=-{CN_DK_RISK_GATE_ENTER:.0%} / 恢复>=-{CN_DK_RISK_GATE_EXIT:.0%}{_dd_text3}\n")
                    if not _dk_pending3:
                        w(f"✅ 杠杆: **{_dk_sc_rt3:.2f}x** (下一交易日维持)")
                        if CN_DK_SCALE_THRESHOLD > 0 and abs(_dk_next_raw3 - _dk_cur_vs3) > 0.001:
                            w(f" | VolScale理论: {_dk_next_raw3:.2f}x (|Δ|={abs(_dk_next_raw3 - _dk_cur_vs3):.4f} < {CN_DK_SCALE_THRESHOLD}阈值)")
                        w("\n")
            w("\n---\n\n")
            _write_v78_adk_new_leg_then_summary(
                w,
                cn_dk_result,
                _dk_hypo_idx3,
                use_shifted=False,
                position_context="若现在收盘目标（非当前正式持仓）",
            )
            _write_volume_warning_panel(msg, compact=False, cn_dk_result=cn_dk_result)
            _write_sp500_risk_regime_note(msg, prefer_recent_csv=True, compact=False)
            us_close_bj = beijing_time_str(us_date, "US", "close")
            w("### Sub-B: V7.9四腿综合（官方/EMA/Bias/LogVol各25%）\n")
            w(f"数据来源: Yahoo Finance日K线 | 收盘: {us_close_bj}")
            if us_open and us_data_is_today:
                w(" ⚡盘中实时")
            w("\n")
            w(f"波动率缩放: {us_scale:.2f}x | 上次确认: {last_confirmed_us_scale:.2f}x\n")
            w(f"杠杆放大资产: **QQQM/GLDM** (US_ROT_FUTURES)；scale>1时只放大自身权重，不承接其他ETF杠杆缺口\n")
            changed = {l: c["proxy"] for l, c in US_ROT_ASSETS.items() if l != c["proxy"]}
            if changed:
                w("实盘->proxy: " + ", ".join(f"{k}->{v}" for k, v in changed.items()) + "\n")
            w(f"阈值: 绝对动量>{US_ROT_ABS_THRESHOLD:.0%} | 调仓保护{US_ROT_REBALANCE_THRESHOLD:.2f}x | VolReg降档资产{_subb_volreg_scaled_assets_text()} 进/出{US_ROT_VOLREG_THRESHOLD:.1f}/{US_ROT_VOLREG_EXIT_THRESHOLD:.1f} scale={US_ROT_VOLREG_DEFENSE_SCALE:.2f}\n")
            w(f"{_v78_subb_default_rule_text()}\n")
            _subb_volume_warning_live = _v78_subb_volume_warning(us_rot_result)
            if _subb_volume_warning_live:
                w(f"{_subb_volume_warning_live}\n")
            w("持仓表展示当前实际持有；四腿表展示假设今日调仓目标，并给出两者差异。\n")
            # VolReg风控 (详细视图)
            _vr_detail = d.get("volreg_ratio")
            _vr_defense_detail = d.get("volreg_defense_today", False)
            if US_ROT_VOLREG_ENABLED and _vr_detail is not None:
                if _vr_detail > US_ROT_VOLREG_THRESHOLD:
                    w(f"🟢 VolReg: SPY {US_ROT_VOLREG_SHORT_W}d/{US_ROT_VOLREG_LONG_W}d vol比={_vr_detail:.2f} > 进入阈值{US_ROT_VOLREG_THRESHOLD} → **明日{_subb_volreg_scaled_assets_text()} x{US_ROT_VOLREG_DEFENSE_SCALE:.2f}，差额BIL**\n")
                elif _vr_defense_detail and _vr_detail >= US_ROT_VOLREG_EXIT_THRESHOLD:
                    w(f"🟡 VolReg: 今日{_subb_volreg_scaled_assets_text()}已降档 | vol比={_vr_detail:.2f} ≥ 退出阈值{US_ROT_VOLREG_EXIT_THRESHOLD}，明日继续降档\n")
                elif _vr_defense_detail:
                    w(f"🟢 VolReg: 今日{_subb_volreg_scaled_assets_text()}已降档 | vol比={_vr_detail:.2f} < 退出阈值{US_ROT_VOLREG_EXIT_THRESHOLD}，明日恢复正常\n")
                else:
                    w(f"🟢 VolReg: SPY vol比={_vr_detail:.2f} < 进入阈值{US_ROT_VOLREG_THRESHOLD} ✅\n")
            w("\n")
            _write_subb_dbc_profit_guard_status(w, us_rot_result, -1)
            _us_live_ranking_codes = _subb_active_ranking_codes(us_rot_close, -1)
            _us_live_gate = _subb_inflation_gate_context(us_rot_close, -1)
            _us_mix_live = _us_mix_display_context(
                us_rot_close,
                -1,
                _us_live_ranking_codes,
                us_scale,
                prev_risky_by_lb=d.get("hypo_prev_mix_risky_by_lb"),
                threshold=US_ROT_REBALANCE_THRESHOLD,
                reference_assets=[(code, _ROT_PROXY_TO_LIVE.get(code, code) + "(通胀off参考)") for code in US_ROT_MACRO_POOL],
            )
            w(f"说明: **{_v78_subb_default_rule_text()}**\n\n")
            w(
                f"**通胀开关:** {'🟢 ON' if _us_live_gate['pressure_on'] else '🔴 OFF'} "
                f"(DBC {INFLATION_PRESSURE_LB}日 {_us_live_gate.get('dbc_mom', np.nan):+.2%}, "
                f"TLT {INFLATION_PRESSURE_LB}日 {_us_live_gate.get('tlt_mom', np.nan):+.2%})\n\n"
            )
            w(_v78_subb_inflation_status_text(_us_live_gate["pressure_on"]) + "\n\n")
            w(f"**官方腿实时结果（{US_ROT_WINDOW_WEIGHT_LABEL}加权混合）:**\n\n")
            _lb0, _lb1, _lb2 = _subb_window_lbs_for_display()
            w(f"| ETF | 实际排名 | {_lb0}日动量 | {_lb1}日动量 | {_lb2}日动量 | 加权动量 | 官方腿目标权重 | 官方腿入选? | 参与官方腿? |\n")
            w("|:-|:-|------:|------:|------:|------:|------:|:-:|:-:|\n")
            for row in _us_mix_live["mix_rows"]:
                _m130 = row["per_lb_momentum"][_lb0]
                _m260 = row["per_lb_momentum"][_lb1]
                _m390 = row["per_lb_momentum"][_lb2]
                _fmt130 = f"{_m130:+.2%}" if not np.isnan(_m130) else "—"
                _fmt260 = f"{_m260:+.2%}" if not np.isnan(_m260) else "—"
                _fmt390 = f"{_m390:+.2%}" if not np.isnan(_m390) else "—"
                _avg = row["avg_momentum"]
                _fmt_avg = f"{_avg:+.2%}" if not np.isnan(_avg) else "—"
                _mix_selected_mark = "✅" if row["mix_selected"] else ""
                _rank_text = f"加权#{row['actual_rank']}" if row.get("actual_rank") else "—"
                w(
                    f"| {row['live_name']} | {_rank_text} | {_fmt130} | {_fmt260} | {_fmt390} | "
                    f"{_fmt_avg} | {row['mix_weight']:.1%} | {_mix_selected_mark} | ✅ |\n"
                )
            for row in _us_mix_live["reference_rows"]:
                _m130 = row["per_lb_momentum"][_lb0]
                _m260 = row["per_lb_momentum"][_lb1]
                _m390 = row["per_lb_momentum"][_lb2]
                _fmt130 = f"{_m130:+.2%}" if not np.isnan(_m130) else "—"
                _fmt260 = f"{_m260:+.2%}" if not np.isnan(_m260) else "—"
                _fmt390 = f"{_m390:+.2%}" if not np.isnan(_m390) else "—"
                _avg = row["avg_momentum"]
                _fmt_avg = f"{_avg:+.2%}" if not np.isnan(_avg) else "—"
                _rank_text = f"加权#{row['actual_rank']}" if row.get("actual_rank") else "—"
                w(f"| {row['live_name']} | {_rank_text} | {_fmt130} | {_fmt260} | {_fmt390} | {_fmt_avg} | 0.0% | 实际排名参考 | 否 |\n")
            w("\n")
            _write_v78_subb_component_leg_tables(w, us_rot_result, -1)
            _write_v78_subb_blend_table(w, us_rot_result, -1)
            _write_v78_subb_current_vs_hypothetical_table(
                w,
                us_rot_result,
                -1,
                current_weights=current_us_w,
                target_weights=hypo_us_w,
            )
            if is_us_signal:
                w(f"✅ 信号日 (美东 {us_date.strftime('%m-%d')})\n")
                w("V7.9 Sub-B 以“四腿综合目标”表为唯一目标权重。\n")
                w(f"调仓幅度: **{turnover_b:.1%}**")
                if rebalanced_b:
                    w(f" 🟢 超{US_ROT_MIN_TURNOVER:.0%}阈值，**会调仓**\n")
                else:
                    w(f" ❌ 低于{US_ROT_MIN_TURNOVER:.0%}阈值，**不调仓**\n")
            else:
                sigs = sorted([i for i in us_signal_set if i < len(us_rot_close) - 1])
                last_us_date = us_rot_close.index[sigs[-1]] if sigs else us_date
                last_us_close_bj = beijing_time_str(last_us_date, "US", "close")
                w(f"⏸️ 非信号日（上次: {last_us_close_bj}）；不生成新的 Sub-B 调仓指令。\n")
            # 调仓阈值
            _thresh_line_live = _us_mix_threshold_check(
                _us_mix_live["momentum_rows"],
                _us_mix_live["vol_row"],
                _us_live_ranking_codes,
                d.get("hypo_prev_mix_risky_by_lb"),
                US_ROT_REBALANCE_THRESHOLD,
            )
            if _thresh_line_live:
                w(f"\n**调仓保护 ({US_ROT_REBALANCE_THRESHOLD}x, 逐窗口):** {_thresh_line_live}\n")
            # Position adjustments for live signal
            _pos_config_live = _scan_position_config(poe.default_chat)
            _sub_b_pos_live = _pos_config_live.get("Sub-B") if _pos_config_live else None
            _sub_b_pos_live = _normalize_subb_position_keys(_sub_b_pos_live)
            if _sub_b_pos_live:
                _us_live_prices = {}
                for etf in all_a:
                    _live = _ROT_PROXY_TO_LIVE.get(etf, etf)
                    _live_price = _latest_live_etf_price(
                        us_rot_close,
                        etf,
                        _live,
                        expected_date=us_rot_close.index[-1],
                        max_lag_days=0,
                    )
                    if _live_price is not None:
                        _us_live_prices[_live] = _live_price
                _cap_config_live = _scan_capital_config(poe.default_chat)
                _sub_b_cap_live = _cap_config_live.get("Sub-B") if _cap_config_live else None
                _all_pos_etfs_live = set(list(_sub_b_pos_live.keys()) + [_ROT_PROXY_TO_LIVE.get(e, e) for e in all_a])
                _target_val_live, _missing_pos_prices_live, _target_source_live = _subb_position_adjustment_target_value(
                    _sub_b_pos_live,
                    _us_live_prices,
                    _sub_b_cap_live,
                )
                if _missing_pos_prices_live:
                    if _target_source_live == "capital":
                        w(
                            "\n⚠️ 当前持仓中部分ETF价格缺失/过期，"
                            "不使用部分市值估算；本次按已设置Sub-B资金计算目标数量: "
                            + ", ".join(_missing_pos_prices_live) + "\n"
                        )
                    else:
                        w(
                            "\n⚠️ 当前持仓中部分ETF价格缺失/过期，"
                            "无法可靠计算当前持仓市值和调仓数量: "
                            + ", ".join(_missing_pos_prices_live) + "\n"
                        )
                if _target_val_live and _target_val_live > 0:
                    _base_label_live = "已设置Sub-B资金" if _target_source_live == "capital" else "当前持仓市值"
                    w(f"\n📊 **仓位调整** (基于{_base_label_live}${_target_val_live:,.0f}):\n")
                    w("| ETF | 当前持仓 | 目标数量 | 调整 |\n|:-|--------:|--------:|-----:|\n")
                    _adj_etfs_live = set(list(_sub_b_pos_live.keys()) + [_ROT_PROXY_TO_LIVE.get(e, e) for e in all_a if hypo_us_w.get(e, 0) > 0.005])
                    for etf_live in sorted(_adj_etfs_live):
                        _raw_pos_live = _sub_b_pos_live.get(etf_live, 0)
                        price = _us_live_prices.get(etf_live, 0)
                        cur_shares = _pos_entry_shares(_raw_pos_live, price)
                        _proxy_key = None
                        for _pk, _lk in _ROT_PROXY_TO_LIVE.items():
                            if _lk == etf_live:
                                _proxy_key = _pk
                                break
                        _w = hypo_us_w.get(_proxy_key, 0) if _proxy_key else hypo_us_w.get(etf_live, 0)
                        target_shares = _subb_target_shares(_target_val_live, _w, price)
                        adj = None if target_shares is None else target_shares - cur_shares
                        if not _pos_entry_is_nonzero(_raw_pos_live) and cur_shares == 0 and (target_shares is None or target_shares == 0):
                            continue
                        if target_shares is None:
                            adj_str = "价格缺失"
                        elif _w <= 0.005 and _pos_entry_is_nonzero(_raw_pos_live) and isinstance(_raw_pos_live, dict):
                            adj_str = "卖出全部"
                        elif adj > 0:
                            adj_str = f"+{adj:,} 买入"
                        elif adj < 0:
                            adj_str = f"{adj:,} 卖出"
                        else:
                            adj_str = "—"
                        if isinstance(_raw_pos_live, dict) and 'amount' in _raw_pos_live:
                            cur_display = f"${_raw_pos_live['amount']:,.0f}"
                        else:
                            cur_display = f"{cur_shares:,}"
                        target_display = "价格缺失" if target_shares is None else f"{target_shares:,}"
                        w(f"| {etf_live} | {cur_display} | {target_display} | {adj_str} |\n")
            w("\n---\n\n")
    def _handle_params(self):
        cn_dk_result_params = None
        adk_params_error = None
        with _sm() as msg:
            msg.write("⏳ 正在读取当前ADK持仓...\n")
            try:
                cn_close_p, cn_dk_close_p, us_rot_close_p, us_prod_daily_p = self._cached_fetch_data(
                    msg, include_cn_live_snapshot=False, include_us_live_snapshot=False)
                _, cn_dk_result_params, _, _, _, _, _, _ = self._cached_run_strategies(
                    cn_close_p,
                    cn_dk_close_p,
                    us_rot_close_p,
                    us_prod_daily_p,
                    allow_unresolved_suba_volume=True,
                )
            except Exception as exc:
                adk_params_error = _short_error(exc)
        with _sm() as msg:
            w = msg.write
            w("## ⚙️ 策略参数总览\n\n### Sub-A: A股乖离动量轮动 (v7.7 linear3x + abs20 gate)\n\n")
            _write_v78_suba_param_tables(w)
            w("\n**计算过程:**\n")
            w(f"1. 乖离率: `bias = price / MA({CN_BIAS_N})`\n")
            w(f"2. 乖离动量: 最近{CN_MOM_DAY}日bias归一化后按1.0→{CN_BIAS_MOM_WEIGHT_END:.1f}加权线性拟合斜率×10000，用于排序\n")
            w("3. 选乖离动量最高的资产\n")
            w(f"4. 候选资产需同时满足R²({CN_R2_WINDOW})≥{CN_R2_THRESHOLD}、近{CN_ABS_MOM_DAY}日实际收益>{CN_ABS_MOM_THRESHOLD:.0%}，否则持现金\n")
            w(f"5. vol缩放: clip({CN_TARGET_VOL:.0%}/vol, {CN_MIN_LEV:.1f}, {CN_MAX_LEV:.1f}), shift(1), |Δscale|≥{CN_SCALE_THRESHOLD:.2f}才调整, 持现金时scale=1.0\n")
            w("6. 无冷却期限制；近收盘信号按当日收盘手工执行，收益状态机用shift(1)避免未来函数\n")
            w("\n**执行方式:** 收盘前看实时信号 → 收盘价执行（回测用收盘价对收盘价，shift(1)避免未来函数）\n")
            w("\n---\n\n### Sub-A-DK: V7.9双子策略（V7.7正式8配对 + New all10 score-hot）\n\n")
            _write_v78_adk_param_tables(w)
            w("\n**当前持仓状态:**\n\n")
            if cn_dk_result_params is not None and len(cn_dk_result_params) > 0:
                _write_v78_adk_current_holding_summary(w, cn_dk_result_params, -1)
                _write_v78_adk_new_leg_then_summary(
                    w,
                    cn_dk_result_params,
                    -1,
                    use_shifted=False,
                    position_context="当前已生效持仓",
                )
            else:
                w(f"当前ADK持仓读取失败: {adk_params_error or '未知错误'}\n")
            w("\n**计算过程:**\n")
            w(f"1. 5指数→正式{len(ADK_OFFICIAL_PAIR_ORDER)}配对，每对计算乖离动量\n")
            w(f"2. 从正式池选|乖离动量|最大的Top-1配对\n")
            w("3. 乖离动量>0 → 做多A/做空B; <0 → 做空A/做多B\n")
            w(f"4. vol缩放: clip({CN_DK_TARGET_VOL:.0%}/vol, {CN_DK_MIN_LEV:.1f}, {CN_DK_MAX_LEV:.1f}), shift(1), |Δscale|≥{CN_DK_SCALE_THRESHOLD:.2f}才调整\n")
            w("5. 无冷却期；近收盘信号按当日收盘手工执行，收益状态机用shift(1)避免未来函数\n")
            w(f"6. 数据: csindex\n")
            w("\n---\n\n### Sub-B: V7.9四腿综合（官方/EMA/Bias/LogVol各25%）\n\n")
            _write_v78_subb_param_tables(w)
            n_etfs = len(US_ROT_ASSETS)
            w("\n**计算过程:**\n")
            w(f"1. 每个信号日，分别计算{n_etfs}只ETF的{_subb_window_label_for_display('/')}日动量（用信号日收盘数据）\n")
            w("2. 每个窗口各自做Top 2 + 绝对动量过滤 + 20日反波动率加权\n")
            w(f"3. 每个窗口先生成自己的Model B目标仓位，再将三个目标仓位按{US_ROT_WINDOW_WEIGHT_LABEL}加权平均\n")
            w(f"4. 波动率缩放(Model B): scale = {US_ROT_TARGET_VOL:.0%}/已实现波动率，"
                      f"scale<=1时所有风险资产等比缩减；scale>1时仅US_ROT_FUTURES按自身权重放大，不承接其他资产杠杆缺口，最高{US_ROT_MAX_LEV:.1f}x\n")
            w("5. Sub-B 纳入 BTC/IBIT；历史段使用 BTC-USD 代理，实盘展示与下单使用 IBIT\n")
            if US_ROT_VOLREG_ENABLED:
                w(f"7. VolReg风险过热: {_subb_volreg_rule_text()}。T日收盘计算 → T+1日执行\n")
                w(f"   - {US_ROT_VOLREG_BACKTEST_NOTE}\n")
            if SUBB_DBC_PROFIT_GUARD_ENABLED:
                w(f"8. DBC/PDBC profit guard: price-only, no score decay; {_subb_dbc_profit_guard_rule_text()}. Applied after VolReg with next-open execution.\n")
            w("\n**执行方式:** 美股因时差无法收盘价执行 -> T+1 adjusted open 执行；回测按旧仓隔夜 + 新仓日内拆分，缺少 required open 时中止。\n")
            w("\n---\n\n### 组合\n\n| 参数 | 值 |\n|:-|:-|\n")
            for _cname in COMBINED_DISPLAY_ORDER:
                _cw = COMBINED_WEIGHTS[_cname]
                w(f"| {_cname}权重 | **{_cw:.1%}** |\n")
            w(
                f"| 微盘成交额参考提示 | **宽口径参考: 中证2000/创业板 MA{MICROCAP_BROAD_VOLUME_ZZ2000_MA}/{MICROCAP_BROAD_VOLUME_ZZ2000_DAYS}天 AND；"
                f"参考比例 {MICROCAP_BROAD_VOLUME_REFERENCE_SCALE:.0%}（仅提示，不执行）** |\n"
            )
            w(f"| 微盘接入版本 | **v2.0 target-vol 独立模块** | 本 Bot 不参与微盘净值计算；缓存检查由微盘独立脚本负责 |\n")
            w(f"| 微盘成交额政策 | **仅参考，不改仓位** | 官方微盘v2.0未启用宽口径成交额风控；本面板保留中证2000+创业板MA{MICROCAP_BROAD_VOLUME_ZZ2000_MA}/{MICROCAP_BROAD_VOLUME_ZZ2000_DAYS}天AND参考提示，参考比例={MICROCAP_BROAD_VOLUME_REFERENCE_SCALE:.0%}，不自动改写微盘仓位 |\n")
            w(f"| PV/收益查询 | 仅展示 Sub-A/Sub-A-DK/Sub-B 三策略组合（{_performance_combo_weight_label()}）；微盘v2.0和Sub-D由独立脚本查看 |\n")
            w(f"| A股交易日历维护 | {CN_MARKET_CALENDAR_COVERAGE_NOTE} |\n")
    def _handle_live_params(self):
        with _sm() as msg:
            w = msg.write
            cn_close, cn_dk_close, us_rot_close, us_prod_daily = self._cached_fetch_data(
                msg, include_cn_live_snapshot=True, include_us_live_snapshot=True)
            w("⏳ 正在计算实时参数...\n")
        cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details = \
                self._cached_run_strategies(
                    cn_close, cn_dk_close, us_rot_close, us_prod_daily,
                    allow_unresolved_suba_volume=True,
                )
        with _sm() as msg:
            w = msg.write
            cn_date = cn_close.index[-1]
            dk_date = cn_dk_close.index[-1]
            us_date = us_rot_close.index[-1]
            cn_close_bj = beijing_time_str(cn_date, "CN", "close")
            us_close_bj = beijing_time_str(us_date, "US", "close")
            cn_unconfirmed, bj_now = is_cn_unconfirmed_intraday_snapshot()
            us_open, _ = is_us_market_open()
            cn_data_is_today = (cn_date.date() == bj_now.date())
            dk_data_is_today = (dk_date.date() == bj_now.date())
            us_data_is_today = (us_date.date() == bj_now.date()) or \
                (us_date.date() == (bj_now - timedelta(days=1)).date() and bj_now.hour < 6)
            any_cn_live = cn_unconfirmed and (cn_data_is_today or dk_data_is_today)
            any_live = any_cn_live or (us_open and us_data_is_today)
            bj_ts = bj_now.strftime('%Y-%m-%d %H:%M')
            w(f"## 📐 实时参数值\n\n")
            _write_suba_volume_query_warning(msg, cn_result)
            if any_live:
                live_mkts = []
                if any_cn_live:
                    live_mkts.append("A股")
                if us_open and us_data_is_today:
                    live_mkts.append("美股")
                w(f"⏱ **北京时间 {bj_ts}** 实时数据快照"
                         f"（{'、'.join(live_mkts)}盘中，收盘前参数可能变化）\n\n")
            else:
                w(f"⏱ **北京时间 {bj_ts}** 基于收盘数据\n\n")
            w(f"A股收盘: {cn_close_bj} | "
                      f"美股收盘: {us_close_bj}\n\n")
            w("### Sub-A: V7.9双腿综合（V7.7A原版 + New A TV1.0）\n\n")
            _write_v78_suba_param_tables(w)
            w("\n")
            cn_close_with_bond = _add_cn_bond_column(cn_close, msg, context="Sub-A参数展示")
            all_codes_lp = CN_EQUITY_CODES + ([CN_BOND_CODE] if CN_BOND_CODE in cn_close_with_bond.columns else [])
            bias_mom_lp = {}
            r2_lp = {}
            abs_mom_lp = {}
            for code in all_codes_lp:
                if code in cn_close_with_bond.columns:
                    bias_mom_lp[code] = calc_bias_momentum(cn_close_with_bond[code])
                    r2_lp[code] = calc_rolling_r2(cn_close_with_bond[code])
                    abs_mom_lp[code] = cn_close_with_bond[code].pct_change(CN_ABS_MOM_DAY)
            _cn_params_intraday = cn_unconfirmed and cn_data_is_today and len(cn_result) >= 2
            _cn_display_idx_lp = -1
            _cn_effective_date = cn_result.index[_cn_display_idx_lp]
            _effective_label = _cn_effective_date.strftime("%Y-%m-%d")
            w("**① V7.9 Sub-A双腿实时状态:**\n\n")
            if _cn_params_intraday:
                w(f"当前显示为 **{_effective_label} 交易时段已生效持仓**；今日收盘目标仍待确认。\n")
            else:
                w(f"当前快照日期 **{_effective_label}**。\n")
            w("\n")
            if "weight" in cn_result.columns and len(cn_result) >= 2:
                _write_suba_volume_overlay_status(msg, cn_result, _cn_display_idx_lp, prefix="")
                _write_v78_suba_blend_table(w, cn_result, _cn_display_idx_lp)
                _write_v78_suba_leg_signal_tables(
                    w,
                    cn_result,
                    _cn_display_idx_lp,
                    bias_mom_lp,
                    r2_lp,
                    abs_mom_lp,
                    all_codes_lp,
                    current_holding=cn_result["v78_suba_v77_holding"].iloc[_cn_display_idx_lp] if "v78_suba_v77_holding" in cn_result.columns else (cn_result["holding"].iloc[_cn_display_idx_lp] if "holding" in cn_result.columns else "cash"),
                )
                _cn_sc_p = cn_result["weight"].iloc[_cn_display_idx_lp]
                if "v78_suba_final_exposure" in cn_result.columns:
                    _cn_display_parts_p = _v78_suba_display_leg_snapshot(cn_result, _cn_display_idx_lp)
                    w("\n**1. V7.9 Sub-A component exposure**\n\n")
                    w("| Metric | Value |\n")
                    w("|:-|------:|\n")
                    w(f"| Final exposure | **{float(_cn_display_parts_p['final_exposure']):.2f}x** |\n")
                    w(f"| V7.7A leg exposure | {float(_cn_display_parts_p['v77_weight']):.2f}x × {V78_SUBA_V77_WEIGHT:.0%} |\n")
                    w(f"| NewA leg exposure | {float(_cn_display_parts_p['new_weight']):.2f}x × {V78_SUBA_NEW_TV10_WEIGHT:.0%} |\n")
                    w("| Execution basis | component-net blend; final exposure is weighted leg sum |\n")
                else:
                    _cn_sc_raw_p = cn_result["scale_raw"].iloc[_cn_display_idx_lp] if "scale_raw" in cn_result.columns else _cn_sc_p
                    _cn_base_frac_p = cn_result["base_weight"].iloc[_cn_display_idx_lp] if "base_weight" in cn_result.columns else _base_fraction_from_weight_and_scale(_cn_sc_p, _cn_sc_raw_p)
                    _cn_rv_p = cn_result["realized_vol"].iloc[_cn_display_idx_lp] if "realized_vol" in cn_result.columns else None
                    _cn_next_raw_p, _cn_next_scale_p, _cn_pending_p = _compute_next_vol_scale(
                        _cn_rv_p, float(_cn_sc_raw_p),
                        CN_TARGET_VOL, CN_MIN_LEV, CN_MAX_LEV, CN_SCALE_THRESHOLD)
                    w(f"\n**1. Sub-A volatility scaling**\n\n")
                    w(f"| Metric | Value |\n")
                    w(f"|:-|------:|\n")
                    w(f"| Current final exposure | **{_cn_sc_p:.2f}x** |\n")
                    w(f"| VolScale base leverage | **{float(_cn_sc_raw_p):.2f}x** |\n")
                    w(f"| Position coefficient | **{float(_cn_base_frac_p):.2f}** |\n")
                    w(f"| Close-confirmed VolScale | **{_cn_next_scale_p:.2f}x** {'rebalance' if _cn_pending_p else 'hold'} |\n")
                    if _cn_rv_p is not None and not np.isnan(_cn_rv_p):
                        w(f"| Realized vol | {_cn_rv_p:.1%} |\n")
                    w(f"| Target vol | {CN_TARGET_VOL:.0%} |\n")
                    if CN_SCALE_THRESHOLD > 0:
                        if abs(_cn_next_raw_p - float(_cn_sc_raw_p)) > 0.001:
                            w(f"| Close-confirmed theoretical leverage | {_cn_next_raw_p:.2f}x (delta={abs(_cn_next_raw_p - float(_cn_sc_raw_p)):.4f}) |\n")
                        else:
                            w(f"| Rebalance threshold | delta >= {CN_SCALE_THRESHOLD:.2f} |\n")
                    if _cn_pending_p:
                        w(f"\n**VolScale rebalance: {float(_cn_sc_raw_p):.2f}x -> {_cn_next_scale_p:.2f}x; manual same-day close execution after near-close confirmation**\n")
                    else:
                        w(f"\n**Final exposure:** **{_cn_sc_p:.2f}x** (same-day close execution basis)\n")
            w("\n---\n\n### Sub-A-DK: V7.9双子策略（V7.7正式8配对 + New all10 score-hot）\n\n")
            _write_v78_adk_param_tables(w)
            w("\n")
            _dk_params_intraday = cn_unconfirmed and dk_data_is_today and len(cn_dk_result) >= 2
            _dk_display_idx_lp = -1
            w("**① V7.9 ADK双腿实时状态:**\n\n")
            if _dk_params_intraday:
                w(f"当前显示为 **{cn_dk_result.index[_dk_display_idx_lp].strftime('%Y-%m-%d')} 交易时段已生效持仓**；今日未移位目标仍待收盘确认。\n")
            _write_v78_adk_new_leg_then_summary(
                w,
                cn_dk_result,
                _dk_display_idx_lp,
                use_shifted=_dk_params_intraday,
                position_context="当前已生效持仓",
            )
            w("\n**② ADK综合风控状态:**\n\n")
            w(f"| 指标 | 值 |\n")
            w(f"|:-|------:|\n")
            if "same_side_overheat_scale" in cn_dk_result.columns:
                _dk_oh_scale_lp = cn_dk_result["same_side_overheat_scale"].iloc[_dk_display_idx_lp]
                _dk_oh_on_lp = bool(cn_dk_result["same_side_overheat_on"].iloc[_dk_display_idx_lp])
                _dk_oh_abs_lp = cn_dk_result["same_side_overheat_abs_bias"].iloc[_dk_display_idx_lp]
                _dk_oh_status_lp = "开启" if _dk_oh_on_lp else "关闭"
                w(f"| 同向过热防守 | **{_dk_oh_status_lp}** ({_dk_oh_scale_lp:.2f}x) |\n")
                if not np.isnan(_dk_oh_abs_lp):
                    w(f"| 当前同向乖离 | **{_dk_oh_abs_lp:.1%}** |\n")
            if "dk_volume_clear_scale" in cn_dk_result.columns:
                _dk_volume_on_lp = bool(cn_dk_result["dk_volume_clear_active"].iloc[_dk_display_idx_lp])
                _dk_volume_status_lp = "警示触发" if _dk_volume_on_lp else "未触发"
                w(f"| 成交额警示 | **{_dk_volume_status_lp}**（仅提示，不改仓位） |\n")
            if "risk_gate_scale" in cn_dk_result.columns:
                _dk_gate_scale_lp = cn_dk_result["risk_gate_scale"].iloc[_dk_display_idx_lp]
                _dk_gate_on_lp = bool(cn_dk_result["risk_gate_on"].iloc[_dk_display_idx_lp])
                _dk_gate_dd_lp = cn_dk_result["risk_gate_base_dd"].iloc[_dk_display_idx_lp]
                _dk_base_w_lp = cn_dk_result["base_weight"].iloc[_dk_display_idx_lp] if "base_weight" in cn_dk_result.columns else cn_dk_result["weight"].iloc[_dk_display_idx_lp]
                _dk_final_w_lp = cn_dk_result["weight"].iloc[_dk_display_idx_lp]
                _dk_gate_status_lp = "开启" if _dk_gate_on_lp else "关闭"
                w(f"| RiskGate状态 | **{_dk_gate_status_lp}**（乘数 {_dk_gate_scale_lp:.2f}x） |\n")
                w(f"| 触发阈值 | **ADK原始净值DD <= -{CN_DK_RISK_GATE_ENTER:.0%}** |\n")
                w(f"| 恢复阈值 | **ADK原始净值DD >= -{CN_DK_RISK_GATE_EXIT:.0%}** |\n")
                w("| DD判断口径 | **risk_gate_base_dd**，基于gate前执行成本净值，不是最终NAV回撤 |\n")
                if not np.isnan(_dk_gate_dd_lp):
                    w(f"| 当前判断DD | **{_dk_gate_dd_lp:.1%}** |\n")
                w(f"| RiskGate前杠杆 | **{_dk_base_w_lp:.2f}x** |\n")
                w(f"| 最终杠杆 | **{_dk_final_w_lp:.2f}x**（= {_dk_base_w_lp:.2f}x × {_dk_gate_scale_lp:.2f}） |\n")
            else:
                w(f"| 最终杠杆 | **{cn_dk_result['weight'].iloc[_dk_display_idx_lp]:.2f}x** |\n")
            if "v78_adk_final_exposure" in cn_dk_result.columns:
                w("\n**③ ADK双腿波动率缩放:**\n\n")
                w("ADK双腿分别执行波动率缩放；综合结果不存在单一VolScale。各腿的已实现波动率、raw/banded VolScale、overlay乘数与最终贡献见上方双腿状态表。\n")
            elif "weight" in cn_dk_result.columns and len(cn_dk_result) >= 2:
                _dk_sc_p = cn_dk_result["weight"].iloc[_dk_display_idx_lp]
                _dk_rv_p = cn_dk_result["realized_vol"].iloc[_dk_display_idx_lp] if "realized_vol" in cn_dk_result.columns else None
                _dk_abs_idx_lp = _dk_display_idx_lp if _dk_display_idx_lp >= 0 else len(cn_dk_result) + _dk_display_idx_lp
                _dk_cur_vs_p = _dk_get_vol_scale(cn_dk_result, _dk_abs_idx_lp)
                _dk_next_raw_p, _dk_next_vs_p, _dk_pending_p = _compute_next_vol_scale(
                    _dk_rv_p, _dk_cur_vs_p,
                    CN_DK_TARGET_VOL if CN_DK_VOL_SCALE_ENABLED else None,
                    CN_DK_MIN_LEV, CN_DK_MAX_LEV, CN_DK_SCALE_THRESHOLD)
                _dk_next_total_p = _dk_sc_p / _dk_cur_vs_p * _dk_next_vs_p if _dk_cur_vs_p > 1e-10 else _dk_next_vs_p
                w(f"\n**③ ADK综合波动率缩放:**\n\n")
                w(f"| 指标 | 值 |\n")
                w(f"|:-|------:|\n")
                w(f"| 当前已生效敞口 | **{_dk_sc_p:.2f}x** (VolScale {_dk_cur_vs_p:.2f}x) |\n")
                w(f"| 本日收盘确认后敞口 | **{_dk_next_total_p:.2f}x** (VolScale {_dk_next_vs_p:.2f}x) {'🟢 需调仓' if _dk_pending_p else '✅ 维持'} |\n")
                if _dk_rv_p is not None and not np.isnan(_dk_rv_p):
                    w(f"| 已实现波动率 | {_dk_rv_p:.1%} |\n")
                w(f"| 目标波动率 | {CN_DK_TARGET_VOL:.0%} |\n")
                if CN_DK_SCALE_THRESHOLD > 0:
                    if abs(_dk_next_raw_p - _dk_cur_vs_p) > 0.001:
                        w(f"| 本日收盘理论VolScale | {_dk_next_raw_p:.2f}x (|Δ|={abs(_dk_next_raw_p - _dk_cur_vs_p):.4f} {'≥' if _dk_pending_p else '<'} {CN_DK_SCALE_THRESHOLD}阈值) |\n")
                    else:
                        w(f"| 调整阈值 | Δ≥{CN_DK_SCALE_THRESHOLD:.2f} |\n")
                if _dk_pending_p:
                    w(f"\n🟢 **杠杆调仓! VolScale {_dk_cur_vs_p:.2f}x → {_dk_next_vs_p:.2f}x | 实际敞口 {_dk_sc_p:.2f}x → {_dk_next_total_p:.2f}x | 本日收盘确认后按收盘价执行**\n")
                else:
                    w(f"\n✅ 杠杆: **{_dk_sc_p:.2f}x**（下一交易日维持）\n")
            w("\n---\n\n### Sub-B: V7.9四腿综合（官方/EMA/Bias/LogVol各25%）\n\n")
            w(f"数据来源: Yahoo Finance日K线 | 收盘: {us_close_bj}\n")
            changed_p = {l: c["proxy"] for l, c in US_ROT_ASSETS.items() if l != c["proxy"]}
            if changed_p:
                w("实盘->proxy: " + ", ".join(f"{k}->{v}" for k, v in changed_p.items()) + "\n")
            w(f"杠杆放大资产: **QQQM/GLDM** (US_ROT_FUTURES={sorted(US_ROT_FUTURES)})；scale>1时只放大自身权重，不承接其他ETF杠杆缺口\n")
            _write_v78_subb_param_tables(w)
            w(f"混合后波动口径: {SUBB_BLEND_VOL_NOTE}\n")
            # VolReg风控状态
            _vr_p = float(us_rot_result["volreg_ratio"].iloc[-1]) if "volreg_ratio" in us_rot_result.columns else None
            _vr_defense_p = bool(us_rot_result["volreg_defense"].iloc[-1]) if "volreg_defense" in us_rot_result.columns else False
            if US_ROT_VOLREG_ENABLED and _vr_p is not None:
                if _vr_p > US_ROT_VOLREG_THRESHOLD:
                    w(f"🟢 **VolReg风险过热:** SPY {US_ROT_VOLREG_SHORT_W}d/{US_ROT_VOLREG_LONG_W}d 波动率比={_vr_p:.2f} > 进入阈值{US_ROT_VOLREG_THRESHOLD}，**明日{_subb_volreg_scaled_assets_text()} x{US_ROT_VOLREG_DEFENSE_SCALE:.2f}，差额BIL**\n")
                elif _vr_defense_p and _vr_p >= US_ROT_VOLREG_EXIT_THRESHOLD:
                    w(f"🟡 **VolReg风险过热:** 今日{_subb_volreg_scaled_assets_text()}已降档 | 波动率比={_vr_p:.2f} ≥ 退出阈值{US_ROT_VOLREG_EXIT_THRESHOLD}，明日继续降档\n")
                elif _vr_defense_p:
                    w(f"🟢 **VolReg风险过热:** 今日{_subb_volreg_scaled_assets_text()}已降档 | 波动率比={_vr_p:.2f} < 退出阈值{US_ROT_VOLREG_EXIT_THRESHOLD}，明日恢复正常\n")
                else:
                    w(f"🟢 **VolReg风险过热:** SPY 波动率比={_vr_p:.2f} < 进入阈值{US_ROT_VOLREG_THRESHOLD} ✅\n")
            # 信号日状态
            _write_subb_dbc_profit_guard_status(w, us_rot_result, -1)
            us_start_idx_p = max(US_ROT_MAX_LB, US_ROT_VOL_LB, US_ROT_VOL_WINDOW) + 1
            us_signal_set_p = _us_signal_days(us_rot_close, us_start_idx_p)
            is_us_signal_p = (len(us_rot_close) - 1) in us_signal_set_p
            if is_us_signal_p and _should_suppress_early_week_us_signal(us_date):
                is_us_signal_p = False
            if is_us_signal_p:
                w(f"✅ **今日是信号日** (美东 {us_date.strftime('%m-%d')})\n")
            else:
                _prev_us_sigs_p = sorted([i for i in us_signal_set_p if i < len(us_rot_close) - 1])
                _last_us_sig_date_p = us_rot_close.index[_prev_us_sigs_p[-1]] if _prev_us_sigs_p else None
                if _last_us_sig_date_p:
                    _last_bj_p = beijing_time_str(_last_us_sig_date_p, "US", "close")
                    w(f"⏸️ 非信号日（上次: {_last_bj_p}）\n")
            w("\n")
            us_scale = _subb_official_scale_from_result(us_rot_result)
            rot_w_cols_p = [c for c in us_rot_result.columns if c.startswith("w_")]
            current_us_w = {c.replace("w_", ""): us_rot_result.iloc[-1][c] for c in rot_w_cols_p}
            _hypo_prev_mix_risky_by_lb_p = _us_mix_prev_risky_by_lb_from_result(
                us_rot_result, us_date, include_current=False,
            )
            _hypo_prev_ema_risky_p = _subb_v75_ema_prev_risky_from_result(
                us_rot_result, us_date, include_current=False,
            )
            _us_params_ranking_codes = _subb_active_ranking_codes(us_rot_close, -1)
            _us_params_gate = _subb_inflation_gate_context(us_rot_close, -1)
            _us_mix_params = _us_mix_display_context(
                us_rot_close,
                -1,
                _us_params_ranking_codes,
                us_scale,
                prev_risky_by_lb=_hypo_prev_mix_risky_by_lb_p,
                threshold=US_ROT_REBALANCE_THRESHOLD,
                reference_assets=[(code, _ROT_PROXY_TO_LIVE.get(code, code) + "(通胀off参考)") for code in US_ROT_MACRO_POOL],
            )
            _model_hypo_us_w_p, _, _ = _us_mix_snapshot(
                us_rot_close,
                -1,
                _us_params_ranking_codes,
                us_scale,
                prev_risky_by_lb=_hypo_prev_mix_risky_by_lb_p,
                threshold=US_ROT_REBALANCE_THRESHOLD,
            )
            _ema_hypo_us_w_p, _, _ = _subb_v75_ema_snapshot(
                us_rot_close,
                -1,
                _subb_v75_ema_scale_from_result(us_rot_result),
                ranking_codes=US_ROT_POOL,
                prev_risky=_hypo_prev_ema_risky_p,
                threshold=US_ROT_REBALANCE_THRESHOLD,
            )
            _v77_hypo_us_w_p = _blend_subb_v75_weight_dicts(_model_hypo_us_w_p, _ema_hypo_us_w_p)
            _bias_hypo_us_w_p = _v78_subb_new_line_hypo_weights_from_blend(
                us_rot_close,
                us_rot_result,
                line="bias",
                row_idx=-1,
            )
            _logvol_hypo_us_w_p = _v78_subb_new_line_hypo_weights_from_blend(
                us_rot_close,
                us_rot_result,
                line="logvol",
                row_idx=-1,
            )
            _blended_hypo_us_w_p = _blend_v78_subb_weight_dicts(
                _v77_hypo_us_w_p,
                _bias_hypo_us_w_p,
                _logvol_hypo_us_w_p,
            )
            _vr_defense_next_p = _volreg_next_cash_state(_vr_defense_p, _vr_p) if US_ROT_VOLREG_ENABLED else False
            _hypo_us_w_p = dict(_blended_hypo_us_w_p)
            if US_ROT_VOLREG_ENABLED and _vr_defense_next_p:
                _hypo_us_w_p, _ = _apply_subb_volreg_defense_scale_to_weights(_hypo_us_w_p, True)
            _hypo_us_w_p = _apply_subb_dbc_profit_guard_scale_to_weights(
                _hypo_us_w_p,
                _subb_dbc_profit_guard_latest_next_scale(us_rot_result),
            )
            _lb0, _lb1, _lb2 = _subb_window_lbs_for_display()
            w(f"**① 官方腿分窗口动量排名（{_subb_window_label_for_display('/')}）:**\n\n")
            w("下表只对应官方腿；EMA/Bias/LogVol腿在后续子策略腿状态表中单独展示。\n\n")
            w(
                f"**通胀开关:** {'🟢 ON' if _us_params_gate['pressure_on'] else '🔴 OFF'} "
                f"(DBC {INFLATION_PRESSURE_LB}日 {_us_params_gate.get('dbc_mom', np.nan):+.2%}, "
                f"TLT {INFLATION_PRESSURE_LB}日 {_us_params_gate.get('tlt_mom', np.nan):+.2%})\n\n"
            )
            w(_v78_subb_inflation_status_text(_us_params_gate["pressure_on"]) + "\n\n")
            for lb in (_lb0, _lb1, _lb2):
                w(f"**{lb}日窗口:**\n\n")
                w(f"| ETF | 动量 | 年化波动率 | Top2? | 绝对动量>{US_ROT_ABS_THRESHOLD:.0%}? | 窗口目标权重 |\n")
                w("|:-|------:|------:|:-:|:-:|------:|\n")
                for row in _us_mix_params["per_lb_rows"][lb]:
                    _mom = row["momentum"]
                    _vol = row["vol"]
                    _fmt_mom = f"{_mom:+.2%}" if not np.isnan(_mom) else "—"
                    _fmt_vol = f"{_vol:.1%}" if not np.isnan(_vol) else "—"
                    _is_top3 = "✅" if row["top3"] else ""
                    _abs_pass = "✅" if row["abs_pass"] else "❌"
                    _rank_marker = " 🏆" if row["rank"] <= US_ROT_TOP_N else ""
                    w(
                        f"| {row['rank']}. {row['live_name']}{_rank_marker} | {_fmt_mom} | {_fmt_vol} | "
                        f"{_is_top3} | {_abs_pass} | {row['window_weight']:.1%} |\n"
                    )
                for row in _us_mix_params["reference_per_lb_rows"][lb]:
                    _mom = row["momentum"]
                    _vol = row["vol"]
                    _fmt_mom = f"{_mom:+.2%}" if not np.isnan(_mom) else "—"
                    _fmt_vol = f"{_vol:.1%}" if not np.isnan(_vol) else "—"
                    _is_top3 = f"参考第{row['rank']}"
                    _abs_pass = "✅" if row["abs_pass"] else "❌"
                    w(
                        f"| {row['rank']}. {row['live_name']} | {_fmt_mom} | {_fmt_vol} | "
                        f"{_is_top3} | {_abs_pass} | 0.0%（不参与） |\n"
                    )
                w("\n")
            w(f"**② 官方腿结果（{US_ROT_WINDOW_WEIGHT_LABEL}加权混合）:**\n\n")
            w(f"| ETF | 实际排名 | {_lb0}日动量 | {_lb1}日动量 | {_lb2}日动量 | 加权动量 | 官方腿目标权重 | 官方腿入选? | 参与官方腿? |\n")
            w("|:-|:-|------:|------:|------:|------:|------:|:-:|:-:|\n")
            for row in _us_mix_params["mix_rows"]:
                _m130 = row["per_lb_momentum"][_lb0]
                _m260 = row["per_lb_momentum"][_lb1]
                _m390 = row["per_lb_momentum"][_lb2]
                _avg = row["avg_momentum"]
                _fmt130 = f"{_m130:+.2%}" if not np.isnan(_m130) else "—"
                _fmt260 = f"{_m260:+.2%}" if not np.isnan(_m260) else "—"
                _fmt390 = f"{_m390:+.2%}" if not np.isnan(_m390) else "—"
                _fmt_avg = f"{_avg:+.2%}" if not np.isnan(_avg) else "—"
                _mix_selected_mark = "✅" if row["mix_selected"] else ""
                _rank_text = f"加权#{row['actual_rank']}" if row.get("actual_rank") else "—"
                w(
                    f"| {row['live_name']} | {_rank_text} | {_fmt130} | {_fmt260} | {_fmt390} | {_fmt_avg} | "
                    f"{row['mix_weight']:.1%} | {_mix_selected_mark} | ✅ |\n"
                )
            for row in _us_mix_params["reference_rows"]:
                _m130 = row["per_lb_momentum"][_lb0]
                _m260 = row["per_lb_momentum"][_lb1]
                _m390 = row["per_lb_momentum"][_lb2]
                _avg = row["avg_momentum"]
                _fmt130 = f"{_m130:+.2%}" if not np.isnan(_m130) else "—"
                _fmt260 = f"{_m260:+.2%}" if not np.isnan(_m260) else "—"
                _fmt390 = f"{_m390:+.2%}" if not np.isnan(_m390) else "—"
                _fmt_avg = f"{_avg:+.2%}" if not np.isnan(_avg) else "—"
                _rank_text = f"加权#{row['actual_rank']}" if row.get("actual_rank") else "—"
                w(f"| {row['live_name']} | {_rank_text} | {_fmt130} | {_fmt260} | {_fmt390} | {_fmt_avg} | 0.0% | 实际排名参考 | 否 |\n")
            _write_v78_subb_component_leg_tables(w, us_rot_result, -1)
            _write_v78_subb_blend_table(w, us_rot_result, -1)
            _write_v78_subb_current_vs_hypothetical_table(
                w,
                us_rot_result,
                -1,
                current_weights=current_us_w,
                target_weights=_hypo_us_w_p,
            )
            hist_us = pd.to_numeric(
                us_rot_result["official_return"] if "official_return" in us_rot_result.columns else us_rot_result["return"],
                errors="coerce",
            ).dropna().iloc[:-1].values
            if len(hist_us) >= US_ROT_VOL_WINDOW:
                us_rv = np.std(hist_us[-US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
                us_scale = _subb_official_scale_from_result(us_rot_result)
            else:
                us_rv = 0.0
                us_scale = 1.0
            w(f"\n**③ 波动率缩放 (Model B):** 近{US_ROT_VOL_WINDOW}日已实现波动率 = {us_rv:.1%}，"
                      f"scale = {US_ROT_TARGET_VOL:.0%}/{us_rv:.1%} = **{us_scale:.2f}x**")
            if us_scale > 1.0:
                w(f" (>1: 仅放大US_ROT_FUTURES(QQQM/GLDM)自身权重，上限{US_ROT_MAX_LEV:.1f}x)")
            elif us_scale < 1.0:
                w(" (<1: 所有资产等比缩减)")
            w("\n")
            # ④ 执行口径
            w("\n**④ V7.9执行口径:** 上方“四腿综合目标”为假设今日调仓目标；"
              "非信号日继续沿用当前持有，不生成正式调仓指令。\n")
            # ⑤ 调仓幅度
            if is_us_signal_p:
                _prev_us_w_p = {}
                _rloc_p = len(us_rot_result) - 1
                if _rloc_p > 0:
                    _prev_us_w_p = {c.replace("w_", ""): us_rot_result.iloc[_rloc_p - 1][c] for c in rot_w_cols_p}
                if not _prev_us_w_p:
                    _prev_us_w_p = {"CASH": 1.0}
                _all_etfs_p = set(list(_hypo_us_w_p.keys()) + list(_prev_us_w_p.keys()))
                _turnover_p = sum(abs(_hypo_us_w_p.get(e, 0) - _prev_us_w_p.get(e, 0)) for e in _all_etfs_p if e not in ("BIL", "CASH"))
            else:
                _all_etfs_p = set(list(_hypo_us_w_p.keys()) + list(current_us_w.keys()))
                _turnover_p = sum(abs(_hypo_us_w_p.get(e, 0) - current_us_w.get(e, 0)) for e in _all_etfs_p if e not in ("BIL", "CASH"))
            w(f"\n**⑤ 调仓幅度:** {_turnover_p:.1%}")
            if _subb_should_rebalance(_turnover_p, US_ROT_MIN_TURNOVER):
                prefix = "如为信号日" if not is_us_signal_p else ""
                w(f" 🟢 超{US_ROT_MIN_TURNOVER:.0%}阈值，{prefix}**会调仓**\n")
            else:
                suffix = "（非信号日不调仓）" if not is_us_signal_p else ""
                w(f" ❌ 低于{US_ROT_MIN_TURNOVER:.0%}阈值，**不调仓**{suffix}\n")
            # ⑥ 调仓阈值
            _thresh_line_p = _us_mix_threshold_check(
                _us_mix_params["momentum_rows"],
                _us_mix_params["vol_row"],
                _us_params_ranking_codes,
                _hypo_prev_mix_risky_by_lb_p,
                US_ROT_REBALANCE_THRESHOLD,
            )
            if _thresh_line_p:
                w(f"\n**⑥ 调仓保护 ({US_ROT_REBALANCE_THRESHOLD}x, 逐窗口):** {_thresh_line_p}\n")
            w("\n---\n\n### 组合权重\n\n| 策略 | 权重 |\n|:-|------:|\n")
            for name in COMBINED_DISPLAY_ORDER:
                cw = COMBINED_WEIGHTS[name]
                w(f"| {name} | {cw:.0%} |\n")
            w(
                f"| 微盘成交额参考提示 | 宽口径参考: 中证2000/创业板 MA{MICROCAP_BROAD_VOLUME_ZZ2000_MA}/{MICROCAP_BROAD_VOLUME_ZZ2000_DAYS}天 AND；"
                f"参考比例 {MICROCAP_BROAD_VOLUME_REFERENCE_SCALE:.0%}（仅提示，不执行），不改写微盘仓位 |\n"
            )
            w(f"| A股交易日历维护 | {CN_MARKET_CALENDAR_COVERAGE_NOTE} |\n")
    def _handle_signal_history(self, query):
        """显示指定日期范围内的所有交易信号（调仓记录）。"""
        start_date, end_date = self._parse_date_with_llm_fallback(query)
        if start_date is None:
            raise poe.BotError(
                "无法解析日期范围。示例：\n"
                "- 2025年3月1日到3月15日的信号\n"
                "- 2024-06到2024-12的信号\n"
                "- 最近3个月的信号"
            )
        with _sm() as msg:
            w = msg.write
            cn_close, cn_dk_close, us_rot_close, us_prod_daily = self._cached_fetch_data(
                msg, include_us_live_snapshot=False)
            w("⏳ 正在计算策略...\n")
        cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details = \
            self._cached_run_strategies(
                cn_close, cn_dk_close, us_rot_close, us_prod_daily,
            )
        # v6.1: No MA filter, placeholder for history display
        _cn_market_above_ma = pd.Series(True, index=cn_close.index)
        with _sm() as msg:
            w = msg.write
            w(f"## 📋 信号历史: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}\n\n")
            _write_suba_volume_query_warning(msg, cn_result)
            # ===== Sub-A =====
            w("### Sub-A: A股轮动\n\n")
            cn_period = cn_result[(cn_result.index >= start_date) & (cn_result.index <= end_date)]
            if "v78_suba_final_exposure" in cn_result.columns:
                cn_rebs = extract_v78_suba_rebalances(cn_result, cn_close, since_date=start_date)
                cn_rebs = [
                    r for r in cn_rebs
                    if pd.Timestamp(r.get("日期")) <= pd.Timestamp(end_date)
                ]
                if len(cn_rebs) == 0:
                    w("该时段无分腿调仓信号。\n")
                    if len(cn_period) > 0:
                        w(f"期末收盘后持仓: **{_v78_suba_position_text(cn_period.iloc[-1], mode='target')}**\n\n")
                    else:
                        w("\n")
                else:
                    w("| 日期 | 策略 | 卖出 | 买入 |\n")
                    w("|:--|:--|:--|:--|\n")
                    for rec in cn_rebs:
                        w(f"| {rec.get('日期', '')} | {rec.get('策略', 'Sub-A')} | {rec.get('卖出', '—')} | **{rec.get('买入', '—')}** |\n")
                    w(f"\n共 **{len(cn_rebs)}** 次分腿调仓\n")
                    if len(cn_period) > 0:
                        w(f"期末收盘后持仓: **{_v78_suba_position_text(cn_period.iloc[-1], mode='target')}**\n\n")
            else:
                cn_trades = cn_period[cn_period["is_signal"] == True]
                if len(cn_trades) == 0:
                    w("该时段无调仓信号。\n")
                    if len(cn_period) > 0:
                        w(f"持仓: **{CN_NAMES.get(cn_period['holding'].iloc[-1], cn_period['holding'].iloc[-1])}**\n\n")
                    else:
                        w("\n")
                else:
                    w("| 日期 | 操作 | 从 | 到 |\n")
                    w("|:--|:--|:--|:--|\n")
                    for tdate in cn_trades.index:
                        loc = cn_result.index.get_loc(tdate)
                        new_h = cn_result.iloc[loc]["holding"]
                        old_h = cn_result.iloc[loc - 1]["holding"] if loc > 0 else "cash"
                        new_name = CN_NAMES.get(new_h, new_h)
                        old_name = CN_NAMES.get(old_h, old_h)
                        if old_h == new_h:
                            action = "维持"
                        elif new_h == "cash":
                            action = "清仓"
                        elif old_h == "cash":
                            action = "建仓"
                        else:
                            action = "换仓"
                    # v6.1: no MA filter

                        w(f"| {tdate.strftime('%Y-%m-%d')} | {action} | {old_name} | **{new_name}** |\n")
                    w(f"\n共 **{len(cn_trades)}** 次调仓\n")
                    if len(cn_period) > 0:
                        w(f"期末持仓: **{CN_NAMES.get(cn_period['holding'].iloc[-1], cn_period['holding'].iloc[-1])}**\n\n")
            # ── Sub-A 杠杆缩放调仓 ──
            if CN_SCALE_THRESHOLD > 0 and "v78_suba_final_exposure" not in cn_result.columns and "weight" in cn_period.columns and len(cn_period) >= 2:
                _cn_scale = cn_period["weight"]
                _cn_scale_diff = _cn_scale.diff().abs()
                _cn_scale_changes = cn_period[(_cn_scale_diff > 0.001) & (cn_period["is_signal"] == False)]
                if len(_cn_scale_changes) > 0:
                    w(f"\n**杠杆缩放调仓 ({len(_cn_scale_changes)}次):**\n\n")
                    w("| 日期 | 杠杆变动 | 持仓 |\n")
                    w("|:--|:--|:--|\n")
                    for tdate in _cn_scale_changes.index:
                        _loc = cn_result.index.get_loc(tdate)
                        _prev_w = cn_result["weight"].iloc[_loc - 1] if _loc > 0 else 1.0
                        _new_w = cn_result.loc[tdate, "weight"]
                        _h = CN_NAMES.get(cn_result.loc[tdate, "holding"], cn_result.loc[tdate, "holding"])
                        w(f"| {tdate.strftime('%Y-%m-%d')} | {_prev_w:.2f}x → **{_new_w:.2f}x** | {_h} |\n")
                    w("\n")
            # ===== Sub-A-DK =====
            w("### Sub-A-DK: 多空策略\n\n")
            dk_period = cn_dk_result[(cn_dk_result.index >= start_date) & (cn_dk_result.index <= end_date)]
            if "v78_adk_final_exposure" in cn_dk_result.columns:
                dk_rebs = extract_v78_adk_rebalances(
                    cn_dk_result,
                    cn_dk_close=cn_dk_close,
                    since_date=start_date,
                )
                dk_rebs = [
                    r for r in dk_rebs
                    if pd.Timestamp(r.get("日期")) <= pd.Timestamp(end_date)
                ]
                if len(dk_rebs) == 0:
                    w("该时段无分腿配对/方向变化。\n\n")
                else:
                    w("**分腿配对/方向变化:**\n\n")
                    w("| 日期 | 策略 | 卖出 | 买入 |\n")
                    w("|:--|:--|:--|:--|\n")
                    for rec in dk_rebs:
                        w(f"| {rec.get('日期', '')} | {rec.get('策略', 'ADK')} | {rec.get('卖出', '—')} | **{rec.get('买入', '—')}** |\n")
                    w(f"\n共 **{len(dk_rebs)}** 次分腿配对/方向变化\n\n")
                if len(dk_period) > 0:
                    w("**区间期末 / 当前已生效双腿持仓:**\n\n")
                    _write_v78_adk_current_holding_summary(w, dk_period, -1)
                    _write_v78_adk_net_exposure_table(w, cn_dk_result, dk_period.index[-1])
                    w("\n")
            else:
                dk_position_trades, dk_scale_trades = _split_dk_history_trades(dk_period)
                if len(dk_position_trades) == 0:
                    w("该时段无配对/方向变化。\n")
                    w("\n")
                else:
                    w("**配对/方向变化:**\n\n")
                    w("| 日期 | 动作 | 持仓 | 杠杆 |\n")
                    w("|:--|:--|:--|------:|\n")
                    for tdate in dk_position_trades.index:
                        _dk_h = dk_period.loc[tdate, "holding"]
                        _dk_w = dk_period.loc[tdate, "weight"] if "weight" in dk_period.columns else 1.0
                        action = "清零敞口" if str(_dk_h) in ("none_0", "none") else "切换"
                        w(f"| {tdate.strftime('%Y-%m-%d')} | {action} | **{_dk_pos_str(_dk_h)}** | {_dk_w:.2f}x |\n")
                    w(f"\n共 **{len(dk_position_trades)}** 次配对/方向变化\n\n")
                if len(dk_period) > 0:
                    w("**区间期末 / 当前已生效持仓:**\n\n")
                    _write_v78_adk_current_holding_summary(w, dk_period, -1)
                    w("\n")
                if len(dk_scale_trades) > 0:
                    w(f"**杠杆缩放调整 ({len(dk_scale_trades)}次):**\n\n")
                    w("| 日期 | 杠杆变动 | 持仓 |\n")
                    w("|:--|:--|:--|\n")
                    for tdate in dk_scale_trades.index:
                        _loc = cn_dk_result.index.get_loc(tdate)
                        _prev_w = cn_dk_result["weight"].iloc[_loc - 1] if _loc > 0 else 1.0
                        _new_w = cn_dk_result.loc[tdate, "weight"]
                        _h = dk_period.loc[tdate, "holding"]
                        w(f"| {tdate.strftime('%Y-%m-%d')} | {_prev_w:.2f}x → **{_new_w:.2f}x** | {_dk_pos_str(_h)} |\n")
                    w("\n")
            # ===== Sub-B =====
            w("### Sub-B: 美股轮动\n\n")
            us_period = us_rot_result[(us_rot_result.index >= start_date) & (us_rot_result.index <= end_date)]
            _tentative_us_mask = pd.Series([_is_tentative_subb_date(idx) for idx in us_period.index], index=us_period.index) if len(us_period) > 0 else pd.Series(dtype=bool)
            _us_open = getattr(self, "_us_open", None)
            us_rebs = extract_us_rot_rebalances(
                us_rot_result,
                us_rot_close=us_rot_close,
                us_open=_us_open,
                since_date=start_date,
            )
            us_period_rebs = [
                rec for rec in us_rebs
                if start_date <= pd.Timestamp(rec.get("日期")) <= end_date
            ]
            if len(us_period_rebs) == 0:
                us_sig = us_period[(us_period.get("is_signal", pd.Series(False, index=us_period.index)) == True) & (~_tentative_us_mask)]
                if len(us_sig) == 0:
                    w("该时段无调仓。\n\n")
                else:
                    w("该时段有信号日但未触发调仓（换手率不足）。\n\n")
            else:
                w("| 日期 | 卖出 | 买入 |\n")
                w("|:--|:--|:--|\n")
                for rec in us_period_rebs:
                    w(f"| {rec.get('日期', '')} | {rec.get('卖出', '—')} | **{rec.get('买入', '—')}** |\n")
                w(f"\n共 **{len(us_period_rebs)}** 次实际调仓\n\n")
            volreg_rebs = extract_subb_volreg_rebalances(us_rot_result, us_rot_close=us_rot_close, us_open=_us_open)
            volreg_period_rebs = [
                rec for rec in volreg_rebs
                if start_date <= pd.Timestamp(rec["日期"]) <= end_date
            ]
            if volreg_period_rebs:
                w(f"**Sub-B VolReg 有效仓位切换 ({len(volreg_period_rebs)}次):**\n\n")
                w("| 日期 | 卖出 | 买入 |\n")
                w("|:--|:--|:--|\n")
                for rec in volreg_period_rebs:
                    w(f"| {rec['日期']} | {rec.get('卖出', '—')} | {rec.get('买入', '—')} |\n")
                w("\n")
            dbc_guard_rebs = extract_subb_dbc_profit_guard_rebalances(us_rot_result, us_rot_close=us_rot_close, us_open=_us_open)
            dbc_guard_period_rebs = [
                rec for rec in dbc_guard_rebs
                if start_date <= pd.Timestamp(rec["日期"]) <= end_date
            ]
            if dbc_guard_period_rebs:
                w(f"**Sub-B DBC Guard 有效仓位切换 ({len(dbc_guard_period_rebs)}次):**\n\n")
                w("| 日期 | 卖出 | 买入 |\n")
                w("|:--|:--|:--|\n")
                for rec in dbc_guard_period_rebs:
                    w(f"| {rec['日期']} | {rec.get('卖出', '—')} | {rec.get('买入', '—')} |\n")
                w("\n")
    def _handle_nav_chart(self, query, *, chart_only=False):
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        start_date, end_date = self._parse_date_with_llm_fallback(query)
        if start_date is None:
            raise poe.BotError(
                "无法解析日期范围。支持的格式示例：\n"
                "- 净值曲线核心三袖 今年 / 去年\n"
                "- 净值曲线核心三袖 过去两年 / 最近6个月\n"
                "- 净值曲线核心三袖 2024-01到2025-01\n"
                "- 净值曲线核心三袖 2024至今\n"
                "- 净值曲线核心三袖 2024年\n"
                "- 净值曲线核心三袖 2024年3月15日到2025年1月20日"
            )
        with _sm() as msg:
            w = msg.write
            cn_close, cn_dk_close, us_rot_close, us_prod_daily = self._cached_fetch_data(
                msg, include_us_live_snapshot=False)
            w("⏳ 正在计算策略净值...\n")
        cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details = \
            self._cached_run_strategies(
                cn_close, cn_dk_close, us_rot_close, us_prod_daily,
            )
        cn_daily_ret = cn_result["return"]
        dk_daily_ret = cn_dk_result["return"]
        us_daily_ret = us_rot_result["return"]
        cn_period = cn_daily_ret[(cn_daily_ret.index >= start_date) & (cn_daily_ret.index <= end_date)]
        dk_period = dk_daily_ret[(dk_daily_ret.index >= start_date) & (dk_daily_ret.index <= end_date)]
        us_period = us_daily_ret[(us_daily_ret.index >= start_date) & (us_daily_ret.index <= end_date)]
        if len(cn_period) < 2 and len(us_period) < 2:
            raise poe.BotError(f"在 {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')} 期间数据不足")
        nav_series = {}
        if len(cn_period) > 1:
            nav_a = (1 + cn_period).cumprod()
            nav_a = nav_a / nav_a.iloc[0]
            nav_series["Sub-A"] = nav_a
        if len(dk_period) > 1:
            nav_dk = (1 + dk_period).cumprod()
            nav_dk = nav_dk / nav_dk.iloc[0]
            nav_series["Sub-A-DK"] = nav_dk
        if len(us_period) > 1:
            nav_b = (1 + us_period).cumprod()
            nav_b = nav_b / nav_b.iloc[0]
            nav_series["Sub-B"] = nav_b
        if len(nav_series) >= 2:
            cw = _performance_combo_weights()
            all_nav_dates = sorted(set().union(*(s.index for s in nav_series.values())))
            nav_df = pd.DataFrame({
                name: s.reindex(pd.DatetimeIndex(all_nav_dates)).ffill()
                for name, s in nav_series.items()
            })
            weight_df = nav_df.notna().astype(float)
            for col in weight_df.columns:
                weight_df[col] *= cw.get(col, 0)
            weight_sum = weight_df.sum(axis=1).replace(0, np.nan)
            weight_df = weight_df.div(weight_sum, axis=0)
            nav_df = nav_df.fillna(0)
            nav_comb = (nav_df * weight_df).sum(axis=1)
            nav_comb = nav_comb / nav_comb.iloc[0]
            nav_series["Combined"] = nav_comb
        if not nav_series:
            raise poe.BotError("不能算该时段的净值曲线")
        colors = {
            "Sub-A": "#E74C3C",    # red
            "Sub-A-DK": "#9B59B6", # purple
            "Sub-B": "#2980B9",    # blue
            "Combined": "#F39C12", # orange/gold
        }
        chart_labels = {
            "Sub-A": "Sub-A (CN Long)",
            "Sub-A-DK": "Sub-A-DK (CN Long-Short)",
            "Sub-B": "Sub-B (US Rotation)",
            "Combined": f"PV 3-sleeve ex Microcap/Sub-D ({_performance_combo_weight_label()})",
        }
        labels = {
            "Sub-A": "Sub-A (A股做多)",
            "Sub-A-DK": "Sub-A-DK (多空)",
            "Sub-B": "Sub-B (美股轮动)",
            "Combined": f"PV三策略组合不含微盘/Sub-D ({_performance_combo_weight_label()})",
        }
        chart_bytes = _render_nav_drawdown_chart(
            nav_series, chart_labels, colors, start_date, end_date
        )
        max_dd = {}
        for name, nav in nav_series.items():
            drawdown = (nav - nav.cummax()) / nav.cummax()
            max_dd[name] = drawdown.min() * 100
        period_label = f"{start_date.strftime('%Y-%m-%d')}至{end_date.strftime('%Y-%m-%d')}"
        with _sm() as msg:
            w = msg.write
            w(f"## 📈 净值曲线: {period_label}\n\n")
            _write_suba_volume_query_warning(msg, cn_result)
            if not chart_only:
                w("| 策略 | 期末净值 | 区间收益 | 最大回撤 |\n|:-|--------:|---------:|---------:|\n")
                for name in PERFORMANCE_COLUMNS:
                    if name in nav_series:
                        final_nav = nav_series[name].iloc[-1]
                        ret = (final_nav - 1) * 100
                        dd = max_dd[name]
                        display = labels[name]
                        w(f"| {display} | {final_nav:.4f} | {ret:+.2f}% | {dd:.2f}% |\n")
                w("\n")
            msg.attach_file(
                name=f"nav_chart_{datetime.now().strftime('%Y%m%d')}.png",
                contents=chart_bytes,
                content_type="image/png",
                is_inline=True,
            )
    def _handle_performance(self, query, _forced_range=None):
        if _forced_range:
            start_date, end_date = _forced_range
        else:
            start_date, end_date = self._parse_date_with_llm_fallback(query)
        if start_date is None:
            raise poe.BotError(
                "无法解析日期范围。支持的格式示例：\n"
                "- 表现 今年 / 去年\n"
                "- 表现 过去两年 / 最近6个月\n"
                "- 表现 2024-01到2025-01\n"
                "- 表现 2024至今\n"
                "- 表现 2024年\n"
                "- 表现 2024年3月15日到2025年1月20日"
            )
        with _sm() as msg:
            w = msg.write
            cn_close, cn_dk_close, us_rot_close, us_prod_daily = self._cached_fetch_data(
                msg, include_us_live_snapshot=False)
            w("⏳ 正在计算策略...\n")
        cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, prod_nav, prod_details = \
            self._cached_run_strategies(
                cn_close, cn_dk_close, us_rot_close, us_prod_daily,
            )
        cn_daily_period = cn_result["return"][
            (cn_result.index >= start_date) & (cn_result.index <= end_date)]
        dk_daily_period = cn_dk_result["return"][
            (cn_dk_result.index >= start_date) & (cn_dk_result.index <= end_date)]
        us_daily_period = us_rot_result["return"][
            (us_rot_result.index >= start_date) & (us_rot_result.index <= end_date)]
        cn_monthly_period = _monthly_returns_from_daily_window(cn_result["return"], start_date, end_date)
        dk_monthly_period = _monthly_returns_from_daily_window(cn_dk_result["return"], start_date, end_date)
        us_monthly_period = _monthly_returns_from_daily_window(us_rot_result["return"], start_date, end_date)
        all_periods = cn_monthly_period.index.intersection(dk_monthly_period.index).intersection(
            us_monthly_period.index)
        if len(all_periods) > 0:
            aligned = pd.DataFrame({
                "Sub-A": cn_monthly_period.reindex(all_periods),
                "Sub-A-DK": dk_monthly_period.reindex(all_periods),
                "Sub-B": us_monthly_period.reindex(all_periods),
            }).dropna()
            w = _performance_combo_weights()
            _strat_cols = PERFORMANCE_COMBO_ORDER
            _nav_monthly = (1 + aligned[_strat_cols]).cumprod()
            _nav_comb = sum(_nav_monthly[n] * w[n] for n in _strat_cols)
            aligned["Combined"] = _nav_comb.pct_change()
            aligned.loc[aligned.index[0], "Combined"] = _nav_comb.iloc[0] - 1
        else:
            aligned = pd.DataFrame(columns=["Sub-A", "Sub-A-DK", "Sub-B", "Combined"])
        filtered = aligned
        if len(cn_monthly_period) < 1 and len(us_monthly_period) < 1:
            raise poe.BotError(f"在 {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')} 期间没有数据")
        metrics = {}
        if len(cn_monthly_period) >= 1:
            metrics["Sub-A"] = calc_monthly_metrics(cn_monthly_period)
        if len(dk_monthly_period) >= 1:
            metrics["Sub-A-DK"] = calc_monthly_metrics(dk_monthly_period)
        if len(us_monthly_period) >= 1:
            metrics["Sub-B"] = calc_monthly_metrics(us_monthly_period)
        if len(filtered) >= 1:
            metrics["Combined"] = calc_monthly_metrics(filtered["Combined"])
        if len(cn_daily_period) > 1 and "Sub-A" in metrics:
            nav_a = (1 + cn_daily_period).cumprod()
            metrics["Sub-A"]["max_dd"] = _max_drawdown_pct_from_nav(nav_a)
        if len(dk_daily_period) > 1 and "Sub-A-DK" in metrics:
            nav_dk = (1 + dk_daily_period).cumprod()
            metrics["Sub-A-DK"]["max_dd"] = _max_drawdown_pct_from_nav(nav_dk)
        if len(us_daily_period) > 1 and "Sub-B" in metrics:
            nav_b = (1 + us_daily_period).cumprod()
            metrics["Sub-B"]["max_dd"] = _max_drawdown_pct_from_nav(nav_b)
        comb_daily = None
        common_start = start_date
        if len(cn_daily_period) > 0:
            common_start = max(common_start, cn_daily_period.index[0])
        if len(dk_daily_period) > 0:
            common_start = max(common_start, dk_daily_period.index[0])
        if len(us_daily_period) > 0:
            common_start = max(common_start, us_daily_period.index[0])
        if "Combined" in metrics:
            nav_parts = {}
            for sname, dret in [
                ("Sub-A", cn_daily_period),
                ("Sub-A-DK", dk_daily_period),
                ("Sub-B", us_daily_period),
            ]:
                if len(dret) > 1:
                    nav_parts[sname] = (1 + dret).cumprod()
            if len(nav_parts) >= 2:
                cw = _performance_combo_weights()
                all_daily_dates = sorted(set().union(*(s.index for s in nav_parts.values())))
                all_daily_dates = [d for d in all_daily_dates if d >= common_start]
                if len(all_daily_dates) > 1:
                    nav_df = pd.DataFrame({
                        n: s.reindex(pd.DatetimeIndex(all_daily_dates)).ffill()
                        for n, s in nav_parts.items()
                    })
                    _wdf = nav_df.notna().astype(float)
                    for _c in _wdf.columns:
                        _wdf[_c] *= cw.get(_c, 0)
                    _ws = _wdf.sum(axis=1).replace(0, np.nan)
                    _wdf = _wdf.div(_ws, axis=0)
                    nav_df_filled = nav_df.fillna(0)
                    nav_comb = (nav_df_filled * _wdf).sum(axis=1)
                    metrics["Combined"]["max_dd"] = _max_drawdown_pct_from_nav(nav_comb)
                    comb_daily = nav_comb.pct_change()
                    comb_daily.iloc[0] = nav_comb.iloc[0] - 1.0
                    comb_daily = comb_daily.dropna()
        for _sname, _dret in [
            ("Sub-A", cn_daily_period), ("Sub-A-DK", dk_daily_period),
            ("Sub-B", us_daily_period),
        ]:
            if _sname in metrics and len(_dret) > 1:
                _nav_d = (1 + _dret).cumprod()
                _total = (_nav_d.iloc[-1] - 1) * 100
                metrics[_sname]["total_return"] = _total
                _ndays = (_dret.index[-1] - _dret.index[0]).days
                if _ndays > 0:
                    _ann = (_nav_d.iloc[-1] ** (365.25 / _ndays) - 1) * 100
                    metrics[_sname]["annual"] = _ann
                    _mdd = metrics[_sname]["max_dd"]
                    metrics[_sname]["calmar"] = _ann / abs(_mdd) if _mdd != 0 else 0
        if "Combined" in metrics and comb_daily is not None and len(comb_daily) > 1:
            _nav_d = (1 + comb_daily).cumprod()
            _total = (_nav_d.iloc[-1] - 1) * 100
            metrics["Combined"]["total_return"] = _total
            _ndays = (comb_daily.index[-1] - comb_daily.index[0]).days
            if _ndays > 0:
                _ann = (_nav_d.iloc[-1] ** (365.25 / _ndays) - 1) * 100
                metrics["Combined"]["annual"] = _ann
                _mdd = metrics["Combined"]["max_dd"]
                metrics["Combined"]["calmar"] = _ann / abs(_mdd) if _mdd != 0 else 0
        excel_monthly = pd.DataFrame({
            "Sub-A": cn_monthly_period,
            "Sub-A-DK": dk_monthly_period,
            "Sub-B": us_monthly_period,
        }).sort_index()
        if len(filtered) > 0:
            excel_monthly["Combined"] = filtered["Combined"].reindex(excel_monthly.index)
        else:
            excel_monthly["Combined"] = np.nan
        is_short_period = (end_date - start_date).days < 365
        if is_short_period:
            def _weekly_win_rate(daily_ret):
                if daily_ret is None or len(daily_ret) < 5:
                    return None, 0
                weekday_mask = daily_ret.index.dayofweek < 5
                wd_ret = daily_ret[weekday_mask]
                if len(wd_ret) < 5:
                    return None, 0
                weekly_groups = wd_ret.groupby(wd_ret.index.to_period("W"))
                weekly = weekly_groups.apply(lambda x: (1 + x).prod() - 1)
                week_sizes = weekly_groups.size()
                full_weeks = week_sizes[week_sizes >= 3].index
                weekly = weekly.reindex(full_weeks)
                if len(weekly) < 1:
                    return None, 0
                return (weekly > 0).mean() * 100, len(weekly)
            for strat_name, daily_data in [
                ("Sub-A", cn_daily_period),
                ("Sub-A-DK", dk_daily_period),
                ("Sub-B", us_daily_period),
                ("Combined", comb_daily),
            ]:
                if strat_name in metrics and daily_data is not None and len(daily_data) > 4:
                    wwr, n_weeks = _weekly_win_rate(daily_data)
                    if wwr is not None:
                        metrics[strat_name]["weekly_win_rate"] = wwr
                        metrics[strat_name]["weekly_win_weeks"] = n_weeks
        all_rebalances = []
        cn_rebs = extract_v78_suba_rebalances(cn_result, cn_close)
        all_rebalances.extend([r for r in cn_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])
        dk_rebs = extract_v78_adk_rebalances(cn_dk_result, cn_dk_close=cn_dk_close)
        all_rebalances.extend([r for r in dk_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])
        _us_open = getattr(self, '_us_open', None)
        us_rebs = extract_us_rot_rebalances(us_rot_result, us_rot_close=us_rot_close, us_open=_us_open)
        all_rebalances.extend([r for r in us_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])
        volreg_rebs = extract_subb_volreg_rebalances(us_rot_result, us_rot_close=us_rot_close, us_open=_us_open)
        all_rebalances.extend([r for r in volreg_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])
        dbc_guard_rebs = extract_subb_dbc_profit_guard_rebalances(us_rot_result, us_rot_close=us_rot_close, us_open=_us_open)
        all_rebalances.extend([r for r in dbc_guard_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])
        all_rebalances = _filter_confirmed_records(all_rebalances, us_schedule=_us_open)
        all_rebalances.sort(key=lambda x: x["日期"])
        standard_daily_returns = {
            "Sub-A": cn_result["return"],
            "Sub-A-DK": cn_dk_result["return"],
            "Sub-B": us_rot_result["return"],
        }
        standard_daily_returns["Combined"] = _performance_combined_daily_returns(standard_daily_returns)
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        nav_series = {}
        if len(cn_daily_period) > 1:
            _nav_a = (1 + cn_daily_period).cumprod()
            nav_series["Sub-A"] = _nav_a / _nav_a.iloc[0]
        if len(dk_daily_period) > 1:
            _nav_dk = (1 + dk_daily_period).cumprod()
            nav_series["Sub-A-DK"] = _nav_dk / _nav_dk.iloc[0]
        if len(us_daily_period) > 1:
            _nav_b = (1 + us_daily_period).cumprod()
            nav_series["Sub-B"] = _nav_b / _nav_b.iloc[0]
        if comb_daily is not None and len(comb_daily) > 1:
            _nav_comb = (1 + comb_daily).cumprod()
            nav_series["Combined"] = _nav_comb / _nav_comb.iloc[0]
        chart_bytes = None
        if nav_series:
            colors = {
                "Sub-A": "#E74C3C", "Sub-A-DK": "#9B59B6",
                "Sub-B": "#2980B9", "Combined": "#F39C12",
            }
            chart_labels = {
                "Sub-A": "Sub-A (CN Long)",
                "Sub-A-DK": "Sub-A-DK (CN Long-Short)",
                "Sub-B": "Sub-B (US Rotation)",
                "Combined": f"PV 3-sleeve ex Microcap/Sub-D ({_performance_combo_weight_label()})",
            }
            chart_bytes = _render_nav_drawdown_chart(
                nav_series, chart_labels, colors, start_date, end_date
            )
        with _sm() as msg:
            w = msg.write
            w(f"## 📈 策略表现: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}\n\n")
            _write_suba_volume_query_warning(msg, cn_result)
            if chart_bytes:
                msg.attach_file(
                    name=f"perf_nav_{datetime.now().strftime('%Y%m%d')}.png",
                    contents=chart_bytes,
                    content_type="image/png",
                    is_inline=True,
                )
                w("\n\n")
            range_info = {}
            if len(cn_monthly_period) >= 1:
                range_info["Sub-A"] = (cn_monthly_period.index[0], cn_monthly_period.index[-1])
            if len(dk_monthly_period) >= 1:
                range_info["Sub-A-DK"] = (dk_monthly_period.index[0], dk_monthly_period.index[-1])
            if len(us_monthly_period) >= 1:
                range_info["Sub-B"] = (us_monthly_period.index[0], us_monthly_period.index[-1])
            if len(filtered) >= 1:
                range_info["Combined"] = (filtered.index[0], filtered.index[-1])
            starts = set(v[0] for v in range_info.values())
            if len(starts) > 1:
                w("⚠️ **各策略数据起始日不同:**\n")
                for name in PERFORMANCE_COLUMNS:
                    if name in range_info:
                        s, e = range_info[name]
                        w(f"- {name}: {s} ~ {e}\n")
                w("\n")
            w(f"说明: PV/收益查询不合并微盘和Sub-D独立脚本，只展示 Sub-A、Sub-A-DK、Sub-B 及三策略组合（{_performance_combo_weight_label()}）。\n\n")
            _write_performance_standard_window_table(w, standard_daily_returns, end_date=end_date)
            w("| 指标 | Sub-A | A-DK | Sub-B | PV三策略组合(不含微盘/Sub-D) |\n|:-|------:|------:|------:|-----:|\n")
            metric_labels = [
                ("年化收益", "annual", "%"), ("波动率", "vol", "%"),
                ("夏普比率", "sharpe", ""), ("最大回撤", "max_dd", "%"),
                ("卡尔玛比率", "calmar", ""), ("月胜率", "win_rate", "%"),
            ]
            if is_short_period:
                metric_labels.append(("周胜率", "weekly_win_rate", "%"))
            metric_labels.append(("累计收益", "total_return", "%"))
            for label, key, suffix in metric_labels:
                row = f"| {label} |"
                for col in PERFORMANCE_COLUMNS:
                    m = metrics.get(col)
                    if m and key in m and m[key] is not None:
                        val_str = f"{m[key]:.2f}{suffix}"
                        if key == "weekly_win_rate" and "weekly_win_weeks" in m:
                            val_str += f" ({m['weekly_win_weeks']}周)"
                        row += f" {val_str} |"
                    else:
                        row += " — |"
                w(row + "\n")
            years_available = set()
            for m in metrics.values():
                if "yearly" in m:
                    years_available.update(m["yearly"].keys())
            if years_available:
                w(f"\n### 年度收益\n")
                w("| 年份 | Sub-A | A-DK | Sub-B | PV三策略组合(不含微盘/Sub-D) |\n|:-|------:|------:|------:|-----:|\n")
                for yr in sorted(years_available):
                    row = f"| {yr} |"
                    for col in PERFORMANCE_COLUMNS:
                        m = metrics.get(col)
                        if m and yr in m.get("yearly", {}):
                            row += f" {m['yearly'][yr]:.1f}% |"
                        else:
                            row += " — |"
                    w(row + "\n")
            w(f"\n### 调仓记录 ({len(all_rebalances)}条)\n")
            if all_rebalances:
                w("| 日期 | 北京时间 | 策略 | 操作 | 价格 |\n|:-|:-|:-|:-|:-|\n")
                display_rebs = all_rebalances[-20:]
                for rec in display_rebs:
                    buy_info = rec.get("买入", "")
                    sell_info = rec.get("卖出", "")
                    if sell_info == "—":
                        sell_info = ""
                    if buy_info == "—":
                        buy_info = ""
                    parts = []
                    if sell_info:
                        parts.append(f"减: {sell_info}")
                    if buy_info:
                        parts.append(f"加: {buy_info}")
                    op = " / ".join(parts) if parts else "—"
                    # 价格列
                    price_parts = []
                    sp = rec.get("卖出价格")
                    bp = rec.get("买入价格")
                    if sp:
                        price_parts.append(f"卖{sp}")
                    if bp:
                        price_parts.append(f"买{bp}")
                    price_str = "; ".join(price_parts) if price_parts else "—"
                    w(f"| {rec['日期']} | {rec['北京时间']} | {rec['策略']} | {op} | {price_str} |\n")
                if len(all_rebalances) > 20:
                    w(f"\n（仅显示最近20条，完整记录见Excel）\n")
            else:
                w("该时段无调仓记录\n")
        now_str = beijing_now().strftime("%Y%m%d")
        excel_bytes = generate_performance_excel(now_str, metrics, excel_monthly, all_rebalances, is_short_period)
        filename = f"performance_{now_str}.xlsx"
        with _sm() as msg:
            w = msg.write
            msg.attach_file(
                name=filename,
                contents=excel_bytes,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            w(f"📎 绩效报告: **{filename}**")

if __name__ == "__main__":
    CombinedStrategyV78().run()

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
EXECUTION_TIMING = "T鏀剁洏淇″彿 -> T+1鎸夋敹鐩樺埌鏀剁洏浠峰樊鏀剁泭鎵ц锛屽凡鍚崟杈?bps鎴愭湰"


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
    "zz1000": "涓瘉1000",
    "hs300": "娌繁300",
    "cyb": "CYB",
    "sz50": "涓婅瘉50",
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
USE_LOCAL_ARTIFACTS = os.environ.get("POE_ADK_USE_LOCAL_ARTIFACTS", "").strip().lower() in {"1", "true", "yes", "on"}
ALLOW_ONLINE_REBUILD = os.environ.get("POE_ADK_ALLOW_ONLINE_REBUILD", "").strip().lower() in {"1", "true", "yes", "on"}


_EMBEDDED_ARTIFACT_BLOB = (
    '{Wp48S^xk9=GL@E0stWa8~^|S5YJf5;w{=jbzJ}e1cnoIWM#r43n`rHH_k%GN!vhiB!3^uzR0#100V6ph|9g)nm7T&u^1OZzE;B>KqmZv*T+)b`M7*g^m~n`'
    'X=;oiure%^`&!7sg1lx4Xmed*&3$-Boes07O3!XrOl(15m<6tgkkpL#=;3WCOyE#HQ7A-1|12<_s|<3f-wzLw!bj^w&Y%<I)osjYisgOX?Ozba;{k>j(vQ_I'
    '=6*@uOG2r%%mpGvBme@Yb>v)p1HxdI$$i?AvRj{tjj5$fTRFAg09`7_;utJU3=uy5v6v!)zl2uHwT+9QUXk#vRmLt^-p?joHp}ax40zu!JewMtKKWd!zhcHG'
    'Bf#!aE@ezwM*;tGqu~Po<i&ji&m8J8Ny}C_L(&l3pbDcju$v_iqK1F3&jo%JY+S@!$|;Q+%K><NP$}2n&b^moTNB^s!es1_1@!qhFp{<sZ`TQZ6tZKL1>51l'
    '+%n@}-UEs$?o8UR^lDd-I%#v$Kx^CQ@rV_Y7|StN;K6vL4%F+p9iSY1??QtNPKX6UCSY}lre+pVKr`71wN3Y_k`Dp1P?=0%o5Dv#b#s;AVyAwEzIl0t63u|y'
    '-`<q@859cy({l<&cJLA)6zbJHE>-$w16_I06a2eQuqAon4l{S&@imM8EW|sZ66!aK87dlCj{5Q6clgz#ftEItRx>CYUhTEW-}J|ZKv#TU1akm6kexm^MfHvh'
    '?q`Cyrsu?VdI}aJxVL-bGmoK^2)yJ|Povy!BR^DF^-?wiU@OZ^U*KQybnUv5TLWxd#MOb5<O@~Q+M&Mc2on!Y1RNJ#<-d;S+bbLQ-7q;ahXQ4-pptCkJ|a?F'
    'GTiIUhA#_(`3dA4$+%h!R^t0l%}IO%G%N&nDa4!`L(7<Hi%3@Q=SSbD2<Sj~E@CiQ*BtjVqplL@MuWyTz+-30Iv7|}x}d}$El~u$L?WehRPhwIde~P}Ip%$?'
    '_@yrqGA&^HC>1{Z&fJc$ORn#|x$o&NO$Zyd2w-}vD1vK7s!+pd($L=`W9$1sY!9L43rEiHXLVgro~^Lnii2KB@Ji5~qZfFPAnJ(-C3|i;K)x?S%-1SmP+H6t'
    '1!UPxOO@&tHdc}m-JR0F7CnOZzOJ#Lkqr@WC+=DIg)M_?))Y`KC`#b?)@7e?hd(rF<l(+1(%@Rct0%d-Ah8D+d;{co)-*`1YVxGVQEkpacY|pozFk|Y)>X9~'
    '>d(v&GWmmb@L<0lweow@X=0FA*=4wOD0(+UHP<mG__MH+lIVSQQ;n@dR^Ag%t)6A=-U2|D7ek5WUZRx2)|(XHx)__t&$~I*(w06i%3K`!#4dp=3U36ir=lQu'
    '>i7NqqDO6j{(?ba)DC$o>UuH^FYu=bI=K|%Di+Y5yO?ldhw3R{CImlW^iGOGat!w`8i^{@duZ#JyH--L?Yj0k(@uxbp4#xF;-(bD7)8U}cx$9%M2ZyGqJFh5'
    ')}xeeypOtOH7m2SQMz1ENFVhwo-PfbYuCC(%B%zXP;&qSvAKX=A@f+)L}~PT|7gEjFSoV&NTxp`&aF~|#;QS-M>xZU)H^#V4}#l3Xy2EdO;x<S|Fy)~9w61*'
    '9Z;||PstfDqvgQVKRBQz*@=wi*~hGu-jS;5Iy*i#$w5q{aoJ!Q{#a$_``C22dk868PQ6gZ$o8@_M*Q7f%e$bM7IxM*#DzB&*%%g$bJrwXX4pYz$&^{|<KY=X'
    'Ze0+jEsGF<kY(Uvk_SZG1Iwj)oZ}L7CH%Zam@wTvuKugYyqlK9dNed&taiR0rdfo7q_~?F<G_tjjj~V3&fNBEi5JO^O-_ns0aUP>R0;rAVV!JI<2FryxTR;Q'
    'gT)|W-eRWu>)nr95A?gzOg*!Bo3u^90nRK_1N~}0gM6IN4zCC7!Z}Q@#By`Pj4GPPS@Ol_nhIKQeq9I-WIA^dCLN_#gUob6m`+_()y)m}e|}PB5lQK-Zr&v#'
    'ygq+}_7jZFq!e4FiEPEeg957I3v~KPW6NZdnxfieRKE|7Yh>Vp%aJ)NX^*!bj}`*s7182OzDzQR<!a~V<Y%TVY~>9pf?)ky?o$WcuPSaj+vpLD?rSjG!nEj%'
    'iwYb?^S1{Ykn=fH;k|KnpQ<C_dLtFO6#gjfIiI^RsO9Le5Q<u0Xc~*?<p7F>Jzv>=Gex+LbjDnj7+e02@!A-|lL)wJC==n?V{n}j{`ah8bYMz)B%+L-(()yX'
    'nAKWiLHN2`yo295*3dGsaM~~keP?7~hi6rkPE$m7jp$yh*r3WYi%BtQ_pW;ROAM2tnJzbBh_2x?iDfcLet>~kuPK+LZz>C3LA!yH@i9)e%VHXnkH%24EVTUW'
    'N?-R;WX3|?hyi;3RA=9L-o-X}j0oc{W5`HS@pK&U60$=+zz^{NXx{XBlH*)o=Na~05z-{~c})+vb!|E@4|(!R)6+`(f#}uloS^3e!k*RF#^c1(p4#^$Tb+|c'
    'o|BC%P3yK1<U+Vom%vE?YRwijk@h`$7dkOe5hCanrj<sO-XYi4gqO`~dl`4@yI;wtFr|gO8!7s;n}#2tk4w2Xa1YU*NHfiUaK^G$7(d+9F#K5MtW{xXBxfB|'
    ')*D^ED<`^TI;}J7h^e10*s*C8TpT)4wzU>nki9r!d7IajGsE8`1k_)|Ok28p*h8jPbn7qR(VLpqaPD%IUmEGVWgVPZZT2t1M8f_luKZPNZ^x|5aGO8g;q;9L'
    'PRxFWQev)&Q)I$DLbt7x;p~FO$&K0EHGR;Rdkp0+-~%;0lEPil;8tYY6OycpUm9|iD)j%u^Bug`Y08RAP8B2H>XFPV9(o|hrj-kNKE~M828SW_3eTMT>%Uf3'
    'RX&(fe2k-loe@#N!-_J-CAf!dNdjx&-OL6-VAfFK?|Unb;7aWlnaPGYj@}Pry&y(!b!jcipr+z+XG|R^O?-+t=k9aH)e#*HQ4kI?La5#mxuxO`tL3ic&#XaH'
    'KqoQuUY&Fi#V2ZKOXk5q6)4D~8X)EC+!Pk^40F}aB&>D*5-my;D$AeP`>JvBgN239F?LiWmwph-Jqn@qd3en@ve70mq)hm^-S38>ZAQ98dd_PeVl{>|bm)`@'
    'g0q4H$TL_#0V8RaVNb*Py;5<(pdNa0mZd1S3FVP`2su2ZvV?97*utOyN*%=%774MZefgl|MwvY_u;J=_sOZ96IEA>Xfm+<hW;?CU;nqiP1s&Z*dU6IAMlk7s'
    '|7CpsBsoMbyeW9&Gd@x9mDD-vg~<;EQA5{N)Ju=a8tLpwUK0#ee^cs0;T2k>WTM)#fEy3mh}%ByysntbHay0<s>$X_NdKmGPIx#RM=Gyx{V2gu>yz31%!4Iw'
    'VYD*hDtTTT0i~q$JkY(fUGk15v#O=x@UTG@b&CMdo*IZ)VLx*onMzEu3zi#>s$FcyQg63|JDzYwR;PG)bpqq{))f-)?qke^|Ln_`dQYua$Nkf&6>rpOBp$7%'
    'QVGz3E2Jpq;;^gVr(dShD18Ch#KoEX;LvR4#W;;FWF1cY1%_sKb@y%N)?n4b6fX?I@rvL+ec8+Z=#>|9+kBZgIfEDB0nsT6nAFG)?ssW(NBVwDRz#=xlZ*^l'
    '@}5yy*Cz-QjGDAhN1jcBDD%xG+<w%)&#~HLSDCI+c~=eKg^#BL!}^?cJ)yW@vD<Y0T~~}TPTe9rQ(;uh?F7+<i3pfGbKQ;>dA(3vr{RQt!MR%RiVsm>!{Db='
    'OavYDvbp+{Ct<dB^iY1zhgem<M>yjc9@fi*PI)0A6=VNs^Kvpr8cmM?DSn|0hj-ZZLEXxgeHY>%SVGg@Io@7d&g!d}5OkUdXr3&JWoHGtf5#GPuKvf2nH`)Z'
    'yP^YcvD59!gg_JTsqxD4pR%54-is1_C4PcIia^{24sF~W9utx!${u`?VK<5QUxPHHutv;!j=a(l;*XdO?5&4E`^PJ*cYuo`1KJ*5-k@CTv}*!Q)1fw=a@6vE'
    'PX3=2>@tn|$Z_t4BgXDDkw($3E?k*sVKUOX-V6=>rqgb%kR&y^ZH+>sX?mt;(b!V7$f!KF62MR*%q0y}lHZEH;fFw&MI>FtM$U4+n!ZWkYc3<L)1RHufl|1D'
    'M`ju%C9DPGQAIx)It}KBjPfn~)KE3f*OcGcpt~ekH7hVy%I$y36Z?n;ZqVO_Y_bQAiB5>s?wKH-%66?A<NWTYw>v{$e?3=_*ztQ)ZgCK9cM9A<&*Cm8y^7~x'
    '%;_3-Dz&FC8bn9t8M|_@M`WQ@YK%7Z<B&nhIijU<`6W*28Rh`h{Ac(rBEwn`#Ey?a`;Mr|pZGe5nC3gc5VbAjMIeBIN4U_-;9_g1nZs2zmeRa|viwVQQG?z)'
    '_2%ux<=oouAZ)|QQ}JIUOlmBLXSqj@=X`elRdsK#!X5%(Kd`rAhFFv%iQL(t=B?ki*Gf%W262~0&;WtL*WKVwaBQ-aStdwrz3PL$G-<ny%#Eu9@RLg5%Ch|W'
    'xnRotokR%NkHsr>fSSx`#w@pHr}T~JX+-h%?>-A4w;-5u*%yDT5M9|e$pFDA>W_4>uBDd_0m)p4(|CBn&$5bI;i%bk-Mc>3Ykvv@Xe~MrvsWybH88Z5j64UL'
    '(m7a1@)IL+p6U%CB(<Z9pOUrewx)iH0ak$&{VxHTAzxZFu=M1^zfW&tyiMo2sG%M6mP}+acU2MT2sYyzszm4;|L}t&wB0~TVIr=k{_8ggjgwSe99zda^hMAr'
    'S5*{DC+%e}d?m`TSw({$T+c|TDK>4ZeBc%F&fwv~n{^0Q)feX&RXvG4Ro%69y#vF3og2NgpEfg9hEgAF;ravEoQ@;Y-mMYWCN-g1fM$G1Z3xHLX`Ui5<nE@v'
    'c4PeEf~JUegTp)Dcj>*Zyjet`#Jj(7dKE;(iSI<b;}A7N*d!Zr#Y(gtq6*~0ih64hDmjC~_+@<gLsq*or@4L1h|k{1>9cV`1QKPJ(LB@oQxo{$vrd)|8_Y_Y'
    '%6hdB<}T#4U))7|#}PItie3Q}IWv50!ldsn$SJ!dCBH6P)PplqC(9RckYj~N9;|=M#PHwBI6d6Ey@XrY(csQeAQ&)8F&IZQBJW~kx+b@ZYkNw52pmF$J*QED'
    '^r}^@k6Px+2?3moLDqzoe5au;hnWKVjEw=|LhNK5F<xuKlO-UtHhPD()H3uFAX&kbrGANl(`CwLJMxO>-Vz!??b3;H8d_7|p$?4vZrGIO_h4qQir%U#Wj1zc'
    '*u7W=13OfTi>QX|PNaWr#xG<6JZ=a-NOAz@By}igH5LfrqIMH)7f<Iba_FljB%=@WLP#2(WFkdq7#Z~zJX@0dEOp*)hcoC&V37yfq}SVDDIBsl$$Ayw2#Wa7'
    'aUnX|Zh6pg;#<q$O!dvad!Y6cjqpO|rzXz<BBv8m40H4R70Niypll<g;Icc*O*5GPvMaa>Tc>4#0)>Pp%^`U5TUd=E-$TgmX;5ERT0Oq}Ur8|@#VjmVm`;UB'
    'crUnRLk-L$+BwsxsE~LCciwo}e&e;N&lV;Rv2cp`qVf)=tpDwCDnR;L^EB*&3R@bnDkSPb&5ZF4!uZm&6v|BQ%pr`LLmj`5&4Ev4#BprTAwg!ox>Fmp;)liL'
    'DDC2+p5V4vr>&paGJlp0g@P=KrHNPqRAyMv_zmiVzNCW8%wE|5{<N3!i^*go_NE%JrhcySYCx|SiYk++2(hNSc(4;q#W?ix`H9glQ)7~-#zmfig}7w{&$0l!'
    '6L?57O<;<NQ(CSTbfb!eNA&~m&j(t4Hk4cti)Wqrfx;DJoAdK_28TV<eGXF<Ok{I}V?x9)o28!si>@*s|7(hNy9#8N;)B5lFRX~)R3B4q<<^#z6mF^D`l!&j'
    'N<-*n655rcR2gmh4H*tQk%Olg2I9x|>=}|9%X<kXnYm_<(z(4;9QBMz`%_uAg!?jZe5~&eP^v@_bmr9T2!^)}vWd^JYpj&iS+WuoI7?Uc$JE+;)b`97Xmrtj'
    'h&i@TjWWc|w7#wL;aoLR8eVS4NrlL8+}?tVfk1$ks4EM~)j<dMSZ)P_Iyd3yJ|BW`>Dg|$T7EAJKcz6XOXP@^JW5T#OvQ~h--{mh74Fm~{_q$a$2Ru#JUCzb'
    '?qx7gOS9&^j=7l@!oo7sT8fu_BZk0eNkOAJ6XvxR|KTYwa<^2)m3Ze4jg1i1V4~YAfL6Tec$0?}*T_>5mPF`J(I-*dvYtT!3(O50XZoPu`Diwy*Jr!uq36rw'
    '%H)dD!}-o|AnX^jMkRMUZ>B{1(PP83JbO7ex&hi45Cjcd5RHo}s}XeOY9Kr$-QLri&G2f@E3OPCv-9GR9MN~GlI|fLh}$i1oF}>-m_+2{62y7mHMRk6sH0{R'
    'ZUl;{F~BekJKM$kMrT`F?{mM2P=T3R26-AK4)M|>jTSAufpM=EjMJEqwzh@?P!9>ij<ym<sg(ySQ5o5QYq+eg_x`&<QoJNLXgW%sA^2KlUJ+Fd1Cam3CKXgM'
    'KeoyM?#3RRc8pod(TieBGO-R>{%}WKzAf_RlkG>`bQ4<8$u**sZ{GZD5B9u7l{s~uxcC3mFD}#Hewy-#r5cjbwzA~y83lK%+~JidX1U!>m0>+S)ugmzopX%u'
    's;U^e!rv@e+wbcCcBr|<3Kh)yoUlYMS8;qDRJUc1qq&hMvH53lKZ!&-QmS{qJiEh@-VD$OsX@*p?hz}nX$8+ncEZ>k=B_iUhY&1;?v>7`OD-9kp8j&r?V2L%'
    '#X8<Zck1{BuF1lal?y^X)mlJAJRi~rsVtAJj(AR*nJteopQ!PUgR3oLyUYOsFi;W>iBcS&T(~^2BJ`mJlQ`sG9ZYqTc9*nDU%U54zoguar`NNURKdaiN4V=m'
    'mwWEO!6~4UyZmu){Md)7);c;AUGV>N!i3@l*b|%c3aV%<`Yj;R3Q?*!)HY^8?6g!Q&YWq(AOq0CU7waKs?FsM=Y-sChK@&V-m30BGcrPh-NIAEu{0GMS>Q^;'
    '!vP;M{O$2-bh8QiFXpI%F&rn0mQ`yaLsQ8@k<T(5UfCygm%Y@_h@PMVy&S*GG*~CddDx93^VTnE6v9!6`KPrOyIJf!{tt)%&zcJw9)K};`}HB=l9EJ~z3jc#'
    ';LOo@_W|dZH!kI((9W+R5)*sdQ2?<8lo-54{I?ez+Q~s>+YAs)BuP9(YUIUuxT+ZDQTqD*?4G{@;BhtM0#tMgB*+t$MYFHG=Q{LyB<FAEx+oNb7>t5q8ERc@'
    'Ubr?n>z-vp{ZHzAH>zD-U}}KMIVmba_C%b8FAgS`Qc(X(mYz+dttlG5oB2M(^adJh4hyd<&{K-YqiQP53;0@nVWg9*Ejztz#V<g{0z9SH3fdgQ8o~*(gW-P='
    'vPMnJCkg>cH+rrz{$2}2j4r4Z_}eh{Rnu0kuy;m}g?V-xXSY?S?tGXBk8fQ#`G(gqTNWr`6^qXyGg3#krR5S5=fMaT8jG@*9oRO1>}eDUuM(fU>%LJGq|%!D'
    '5AHI)Dq5%utUjWBs$}4Fg2VgJ_M7jhHJ1D9Wo^*h$`q(4Xt~VkpNiIRAMn<_F^z3;^_Gf^kK>fd`D(}I{0=7h`zF(1<y^}UECN1Y5=r|1$hXGJ@1kYwdH3<h'
    'Ouk9Fiv8u{!SyH<8wQpxAm9|J!3JY()o)(~K(q|6btcP|RATe1F;1V62_GvUtE*AbVPGW3#dD-=aag4u-53Oluq`NBG^6o666q)HY9sMU#mGysnx};UfZNGL'
    '87@7gVxdzBJ{haQQrBLH(Rp+aQ$La|zFi{<x2qHUC7Jz-r5ZH7DOPW(B>^WQL)Ce-M-8b#Qjd%3m+exbhJUHfI6U*fK1#rh@`g7e>;4X76!^%@fQh-hTLm^y'
    '$GuI?6z&pAIgNM_q2$TZbx(~A_z(t#>wAFJdk69x&fuP_$hX!{KE8x;ZEGnCYLvoPgvQ2>(Qm8p`*O686}xo9<;Ed1mHO#VQ3vqN+vv4seDuoOE*7~EXItx0'
    'SHWA>i)yKX5YX_N8cVYp)dUkSn+c6B4rLJ|bNp7n#9i}$;XXpYg?KGu_a1svR<Zi>H6SyV-*7o`HWjk;XK|h90kZ6;M#7#%@jv<oq;0k1L31Ip>lxJ_+LHE0'
    'wcTFu{ManQ==Ky1bD-w1n0x1e)*!P{_TfjFX;uMZ0FS(;os}m7cMW)OO4}>6D(fkMUDIKo)T|oJs5jCYctsk3n#4;V|EW&fsR~PVOoez-<)89=lF?hnaEYo?'
    '^1&A9#Ec{fml7yIwI>dG22xnFlTiavu!>9L{qT}l5w$iJmF}NKbke#!p78Xz5!Fl+(fouE>@$hrVcDC#%~~7DJO=~lewhrEFRCE#5anb(k19H15EIcFokkD@'
    '>r{(Sy2MXlUYO#jP}oqS$^mI9mkPOc$6Nak4}Q*QAq0wBLcYa(MzpR(s8+48af~?XeLmPPVYSOHrfQ>!v281nhZxdkXRRtQjGGSACFANGXr5Pe6F6Gp!T+7Y'
    '44k6r4<$?`GY@pgG~oASH!#Ps(fwYyLSwmJy9X&amlof?x}6%qkXYbEc%+%ItU%mU!iqfW;(Z29%r9}uRMQH^j!VE@xm&1Ag{GCM|3Pt1fEZmeT~M^05;cru'
    '&K4oPLMJmMb2>LXe_t){Msc`LM)$b&Jgm6S`Ab?4!Dpf9{TQ>GL*>@3s+e(Xi_zRq5ODG!tD|Zw=<qw1nYk1h0rtA~dDh&AJi!YN1_$9;*blXN(hrcE9SQwL'
    'NZ0*D&$$<reM>cOzgD}Hg$5tVt$7h{?D)BH$RH*}psK$sM!?mkR)PcgwDcG0(?u1kV1DZashIH_m}4?hX@130N6yc+_!Oig=o6a$?<z_HB-<R`w|V_aiUV_e'
    '>wVcZj{&&Ha1~7)NYwXC2T3bWKR4;fv8Xm&!Oqz^VO7wqaR*yGN{#|DPvAR6>5HiS1L*z;-Ij-7(%0<Zg79MpZ~!`t<KAZ@(nDR)dPRT@kP0tiEfn5W{z+nd'
    'S#wA-r0$c<a838~=)E2y))@sqr?qR*c%D|^BcKiR*#D_C>~igu7fv>$$?&ZHr(!COoSSto-Ha6WF-uWwz>UzDC;^q8!MwflUcGbW^!GJGzf#u+d=fo@c+Mw+'
    'g9s^h6Z+B*Pz#Ehznw^^Z=dss<e6m0nd<zf^a3()Cfwno0!)C%qMy7C_Irzys`c39E}WuvR>NCkXgiIQS$Y)`D@zvNIf$`cfNiS)6!3`NiJ%#ftX+^dkuM`d'
    '_H2?Kj8X@gnQlzb@!W%1aM#24<$p(ybO1PQCPyZ?u%=86j;I=EsLpkOY(qjB#HEwv8SQTJfio&=$RTlcO=9s0y5P8Od+*M{k4?(Hal$aT*@n)VYn57S(3hoD'
    'CToJ~C(>(o>q`ks?3y`>=JaP`mf}e!>7RB#M3%*_b>1x*2<iR#AlD=7c$KmAyIJpqK;tbgG~pbj7dv`kNA_C1G2TW5M>k|O%}N5Ysz0X$0%CH6PA8Ef3wANV'
    'cTr`uT<vJ=S1u8Tf+FBU8CwyVV`=bvf!m!@l_d(!P73rB8H$dzZP|8_GIqUT<QV>FpOOfCtM%<c6obuX30c~A??~|1Qb+_=&_vy>LuRj@fWGp9Q67vKPNxow'
    'tjMS5(<U|VRKeeq_(LnE?5ePIv%9#Shv(fV&^5t*lLdf7)W1{yADxdQ>^1xo5J7DqhtiiJ^~E&=*=={iotEu!A+_)el*?i<_9=ebbVfIMvQ69$PEY{ciBz}0'
    'Z5957eLhOovcYD4)vQI?@*hb~)7nw>%hb#2w}{iAOAq)Qwk~e<cZh-QM*hgLY#`}Qwpj0d3(IxR^@qT@fJ^#@B{$@Jj~Mn_PcX!201~?}j<Eoy6>ghYj`Hxe'
    'UiAOngDEMA^E7nV!6V!xoBD`Dv$y@>y+;sndP#<h7A4MgH8-g)T`B4}R(vSjb685qz~&Fjafk4ckBtmZ`VY2{&W|{nIf6a?DkNZnCQ$l-C(`%gjb|p#e9G^6'
    'G`ZF<cGyQT@;8Bhuk{(g{bbKbQ$y)ZOdF>(|E_0gMC>^*vtjUcoa<HQ9RgokvCUuas2=-?y28-)0b}GEekILl;>owE>NA;ecKU+>S5)h00@^`K&>~I?Ay>($'
    '`|5_*%=9rw${k&{hUZewiAErt#e)VL2g%_#bK?y^x!q<iF^D`$UGs4OJ)GF4r#ox*eq&YVjG64z$UiZV6hYib7yY?wbaAo+Ikw$B&b^Z<G}TMi{N=r>A>vw+'
    '%<WTyR;xV(zy@0inlIeO7!8g{p-Tm^J5VLT_3}b8BM7onD3uY-!8!M$<2d()T7@D2y2&e7P6xZ1Zt$9OZ)>{CV4swDG(@DRC<!q1Dh7Y=n(u~)wsbAnvXYYb'
    '!CxwT3g#<vu2hL1h{LAGPIb4FNR|1YCeRc76#TQrXT^=99$7l7PANvysUjh>1@R-q{0Pb65u->rsEH3ge>I`;^caizxMJC}wAO(0cNWCpRvwP*3?t~++?D{D'
    'JOY`8GSq=}{?;rLX7!J>>{i9Bo1=#IV<)41Qtoc#<5{e`Ooz>2?bf)|*`ubN`xeU8O?^=m^o8KZZ$AUGRu6A*6+VoNcu+nNc=qqdMQn&qER1i>?{C&l;RF#W'
    'u(Nh6b3lG(mF7QBjkk(D;?4-AHe!Bh@|034nbQ3aP#l9px7!gd*#)IB0j+mDF1QRQ=ftDlx+LF6mqsjdi0+(~L)e#(f!-6QM6eWDRwNJQMIlYu*8pp&dfsAk'
    'g-NH*xRWE!wWV7(B2%19X3QCy<PWNDCt7`Wi#L2L7}d>n_-%OAE6Mmn62kYd-tCAfT8+LCoVT(9S-1NekZ9=MW<~k7KcnyN{!;)A3knW1n>ATrC#r0mm&w4R'
    '?eE{*1voeGqER_8ft1%beK3SbOY=M`u$0B4d5qtQOd)fV-%>~=l$PDFH1#@YJw5Au)Z88sPhW4tCWz_-;Q$jxwO3gftjD<b)_*YgL(Ue^hzZ&=W;ZJTSHc^m'
    '16@GLi28^F;{aoDOtW~Dz<o=)OIzFa6r@>KI&~P-a*!<(dCReMRwIHdM+)Pk5IT*)(u5BNrYfueN+^MPNMXo1>2c8Em1!m3LQP&CHd6oBSa{NmcQvQJH}+u4'
    'm3eO{nuiq{B%&7#*Bvfd_717CezoW9rT28V7IV-mhp8#|Qa(ElnhdN%`E^j&q3YGDBo3kq{8$eD-{8KZtgs)BEA*>jryTvA@LxWy7#HeA!~bj4f_$gJbp?44'
    '^>4iIUkpc}X(+SqBDrRP!49wEfS?qb3XeiEqz|8zyWk6tb{$}ywZ1RqX&HS6t*`{wAeWPb6&lu9zV8%|FYtL>6wl8KzzgdFbwb5kA(6?bcq4ks7)uT74Rrwu'
    '9^UjmwK^PqLd1(!-oGGQ9&%G%8yD(teL}xX#HQ9I_uKO{7UFf_Tlisl@9`hMj>910I#mKuKY!if&B6$+lE9f>{jab{d`c}7gRi>_6F^G_M7J1#YPf1S5?$je'
    'Hr4wb2Kwxx`GX@h=qJ}v@GuG`6H=1H`LiFrYuehSh4q(f?)l8t@IIl5zfGT_A5c>8`$C9s_`~%LJ#XTn;y~=V<g83NiRcn@J4=Auw%NP8a`Vs-vk1ngquWT1'
    '6MwBr$t){!|5{%LiyrfXrV>PP5w234IFFtgEkdaLp`DeU>xI+Z4)_(el}4?#;=s{$k6TiBxu%$bxBsyIB#yk+F1qGCbjzG`7~7x(DY3e9a?Uog?t7^?{UdX6'
    'C(>oBxJSKU1##py4yr&Zb@Bp&FX}D_@bUy>C^lk+SO7nPl%Mgzbk)hD@4m5|J(Zxn;;P~$L*P0h6EMC*8}}6=TnGTfBo^Rr8oo)})JdftUV_`Sh5~#ymilno'
    ')QU~yeqsq$GF=!k9;|NIS5s=S(8IwsT0rSkGATB~4_s8QJ4X;{8u00mGkrb_$A%qh)u6Bp*eWF&YY)xnjfSU5oIVXLTDjMv7NBQ#D0gg~R{K!CiAFYWhGR#@'
    'rF1Zic&C?{=Wjk2dWHU7%lMi~HDa~&#AUOlaW#HvEsF7a0}M&e;dQblE4v^4qO&#)d!F5~Fnlk;b!SSg4-p=X9UXC%PXmt|YokMouAzo=TR4z;_`4CIM=8o*'
    '5!KuTz~FqMb<Fmavo(kr+93iW;W6zM953mPQQv-<v<q!<8hbwuj#O3A$y*DWm!s>=IqkovOyw7IFQab=+szX)OvB{A91*h{!xgDFcmf0Fj2ysJ)W+W={GVYe'
    'CByoz_Y*2bz=l@hcjPMb(Ir3-D-{h9NsaNIFSWa^NW_u{%cePiH%KCoIij3^@uGO3Q=pH;a{klv;dML#toOb~wG%E8WS}PjWPWz%Jt$D(s+}kNMo#^zgMIRB'
    'LwA_dEe5M>e-^Nz2c?YU_qhd*PbWL6nv1-7v#}^l&XY;0s)LQfs!))mmYKKE)8&qnN}m_iYa-#e?L?XJngeOyU-&HE7ZyJdlIqEQ*2_@*9*s2EH@{C#{K1T8'
    'uH4T%0mqz4>1&7^oWOvhVb$wSM=AZ4o6O$pGJ>_oW;|k;31~XMPzDsKL?I4@VH_1VdWSsApR<`EAt;zPa`4iM18X;d00jv}dx@teX&{Sfn*z$SU5~097FKP;'
    'OEIoc8JFIgyN^XD?I>gyM~$0ZtP8;{GIO$3Vk+f4_on9P-7?~sMr6s!f6JO+9{4OmX=QauYi^?2FG}dJ7Dr}mR7nQn*f@p2{l;=j?GM`7XXl;p<bBjQL*<Ya'
    '4(X8+we65Hh=zq4I1kgaS>na~#xjTgLtEP^g8n=4(+n%X<^(}rUe6PXl3u%MTLakwU`$%1dsej}I8PtRK~n=Ph6x2&MnP~xO=Ywrx6QLb`>HH+_mEj5J6y8F'
    'JK$D2cVB+=)`@bi7m9%x8I|xOd^jn=Fol5nauoJnO`%3yp6#qoEZ9aKekWoUC27S9V)tUqzN6w;VWmJ%0%45d333M~9at$g{?nlE)2_}O8Ke>qOEhkJ+CBNT'
    'fq20&G|Ix6Iiol&PjU{zAKcCGB@8jYSrS|GJGjW*<gglH4zCHRi-;kpC87xOFxNJ_sny^yfn($umyG?z$HA6lZ|_<il&U(qKdf4`3$03ruRm;ix~Z<_B-@jb'
    '3PZ>K<gmg;9od^XhI@1FJ+Fs1d&fQ`zbnFOPQuTvjy_aMh^+_hdhAmANq|74iC6V>8kznz^cLt?4vJBj>F)gMFjDWG`I!MPOGtIQaK(etYa!whKCD)?RS8_a'
    'NUF2TuSXd2_NWueb;sovNb{HiSfxYe1{b(pKynzNPR^${;$GRD_TJ`NG$-NYA(GI|-a!kb;nXNWuX)|-AqPIMYog>))T&zjYdl>{mDk(rBv7TEQ3McOL`5Hs'
    'usaOUD~}jYm;)F|=K#S)5O7|%B%PP{X~#sJ)J?Il0R|<#LZby*_x!Jh#k^!`nsmwfD!i4!lkpJZ2-qVi5#~r9MtpPcnl<(>=~J0!1xBS?)^~||pH<L1?$_K('
    '0y?Kv-*MGDv5JjkgJtrzg~n%lGne&9ACL654uBi?`3E*~R&Q|tCk)7dM=1UZZH`mNS_7(Q>RADA;4y8t%)PTuOw4z%$@c6yTg{lS`7wuACY7B`C|3javx}xr'
    'hF87P?m4AcI8~$@QqNk?7nFP2%C*CHcgwt8*pm)7i7*ZI*a*Wn&?lOw6y!z-L3xEtx{1D{VIMUJ7Rc(I{{^1+mth8k!@M^6iXOeV5$0<*FA^5!$55iEW}-#G'
    '+y+1Hcj|s<D+}q<m{GM8G=x_Sa*gl0zjS&X2F{0T<2v`$kNv2Xmzp@C;1K_t&3cRn%sCH9hjCq;ggKZV01iumKz`qn;D?X5dSN0iBa3op;sq|Z@;=JNzNics'
    '_qs{-Y=kbqN-?DOZhwmu^L13S6n2H{8bSWK(M1oiV12QCN%&Gx;Tz-|w5~nB0#_`FosBe1?;D-ok^dpb_EX)AH1W_r9niBo&M!2+D+Lu#Im@6BPQKE;JJNF-'
    'vIODyPH28k`I<08T0rsNHnZD3NTrD|SlAs$8n^quWi=+h>e<9O#ykXsez>zK@^M(;{zn(~KhNbS7ZRG2LxGf_%$dL>X^5pM60YpMr3L?!>34O+%#@w<9%%9^'
    '?BTE^bj#r#!64L3dFwU~bq+t0hkK2bOWNde$3=$lY@JCfqD1aV^zI^U)}GyCyoC+Pi$bM(0OJT~{BQ5jGGgqVf@xNqAS5>QjB!H{DE-7W32WpEe|DJy3`lU9'
    'B!r9E7k9)(eB_maeo${7Ai7Hu*WjOxvlZHGgc7D>s+Z;GTR@e=8~I2Bl0pbj-wR_c$X5p5S*$#%d02D;>J_dprVs1RPr!qFXQ4yceN+yV9`q>XmmNRu>qE`c'
    '(_`hGp{4TS+b13;$rEM2X#wQjji|RK9J!y%mieHR7PMW0{2L?^2|JiF(F%DffQYW!#4!vEf9NN7EEKGtC5?|Jq_&gaj&&~1x`}9pr9{iC-NIyl(%u+C8TCg~'
    'heJ5FIP%}(R_K+{RK6lJ2#T;GVW!N-=Z!4lC0Uz~F$ohxddN0CAg{EBmk1=Kh$K<~oOo-=erEy<h^0RTIjPd57tEV$8A(KOn&H<aUOvG)mN`)j=-U8vZXqwC'
    '{bEwTA~LuSX1uS}tj?6st0_s8hgkT#|I>t2Hd^ahp4VreEM3&-dFBkLK53ov3Sqx@Gz2YspHaMMyu2r_E7NR3M!J)_N<r0>D`&<NTJQf}^gU!8a%!O`T5_fw'
    '0DYE%1-u3M;c<NO`h#Dbfs(thPQ8$bQ|DVSk-Lbwu}Ia<D6PH+PjW>DwvGy6LAwoU<#@DfpIB(03rmvfuPqYZ8W4hqS+RR{6t71xOoZR{+r(U~iFT?-f(6xs'
    '_}o++fS!XjOm>5x%gQlR`7{nPF*_N@0vOfyJ`B{^#_hh#d&rP5^<En3J4pv6;|d8{Vs%==3TALk-`wy%0FaHLfx+^%c>+cwqeLv5n3-p3U@7)c?xZ_}rtFVU'
    '`Q`e)dz2M|ht+Gg3nRE0#PS7SOiGj+%yk7O67H9gh+yJdSZsYRF+Ol6?oC5$tv#{y9KpS?H*9b%)UV=aOY+O01Br>W_i?_?!6z!8pwUEKF07SvTn$6ZZ4Eo`'
    'i*CFAtv&YCqY9eJFFEj|1nMlqIgM?bd1p-ygtI2dwRJ+YN3!X5oWAOT0cgmEi7l3DhxoIn>4DJ3y%-;mf7d>T?9l?(f!COa7*$MEill7#OUwaSS>OdCj*zMA'
    '`hi3dM>L8H5c{>+oyXoxz=y<!@=z(dWG}=JcO+Xwx>99)o9sub*#YA16X8MV?OxbIF#!5Z=BmmN!Mg_!hXk6p&Madqy3r0P(5#&DRuf?wHKp#m_wLKqrp1J@'
    'I?w>ATC{iqs67!D2R1STd$fsXXXKDUgcp0fxuaCGJ<sNqsN8zCUQc^7rHhxb8IYZ))R}omGm=T)uqg(MG%{Je^a2v#laVRIY@MEw7Up+H-1ky24UuXm%KNL~'
    ')u>O1aGwG~KX=Z=<`-oE_vQZ?Yd(p0?o?zUj&#5`lEn8K^q&50;w`fmR5_dgDBpEIP#Wj<?s>t}YfY=fcPX()1ZN6mzvJ5@<~}W<zEAuzG*7}R<^6gqJFwK!'
    'kRr3+rz%4~Oo1?yK|Tn!{0Us-ADwg9X)BwB$T<&dd?daQw_nSBoga;o`X^GUzj{wSA<SdjF1<7eI9VH4>Yp+wCb}#W4_i0FSZ59|Dmdj#ElfP_z(fU(xaFhn'
    'N7cQ+7xY2~8gKE1ZNER=IKWRbi=3))Tl`Y5W7*hbXZ-*5r+Ejij>BzMD*}`8Q>-EP8XeTBeg10nnFQTt54~V$^7=xh*ERIK<Go~;Q!0)xOlJBUdkiN<Ip;PW'
    'PY=Gd>(fZ-ZL6vA>f!FKCu7#3QgOsft{t|=qMv1i11se^)F_D@DLXyI{B~(%?#geC)cQyjl)T<>Km*cqbcEO$aEABme_Z(QkfHiMF)Taiz+Q||SGIA{0gr5}'
    'e+Zm2d~QR{XZ|bSj*tAaTQ7_@hcwMZ++*H&7X%oKgDD~g)C_*F*(hK!YoBS)OdY;42|c%(cSh`%o&dQ=<^NY~8X2d5>0uapP7BF}iZG*w7oJoxu)D)f*I#-{'
    '3$X)W<gR7Ivj4UGW6iv!C#E?3$#{Z)9-9>{!}>??WFaalkLe+i@#-L&`x}uzb43Lj!A7H=6J7k_ZZKB=6%?O3otv_J!@RhI<qS<l0q-2HW!{llKr5`p;+EB+'
    'm0yH_&;;<;`nHL(LcpFjR!61w8dMYj2UM`9+&?Z6(>_l8wDMoG23;b)X=Uc`zuW0aV?4P;5sQrg`gU`Jd%#Pdc^D(-;gzC|h;T{kzCjXs)_b5AKv(2`#?&_l'
    '?vnr)I7S&Z`QFrxUUQRPQ&C9_)~IwgP!51H+vB2U1uwT0zs~!p7y&NTWV##gFErHQG_e?zvJt~yTf4_}c#P}>N(R%ye#7vOaCi^tF}EA8vA45w;ZBDhPi!@o'
    'O-^WH*037@S5@DsleuS(Y4bdrWj^sd8vqS);EEVoPI$+M8JhMBleX^t)H3AyYyZTjWT!ZT-Ez&%fgLbpxxDMa;`HL@befsmDR6^FJu`lsF&Bk`d+=xMHciBE'
    'n5s@FmjQ62)H_qrZNK1Yg@Ul*C#%H5IZ{V=6d`AagpghoA^S_fm{OXUTc-8kk=OYu<?Qd_LjN5`K`M^^*;&aS4M~3((V<nl<x2G*R3ZlV{V7EAN3~0p`xyR1'
    'R;F=~A{S%~Xvf`sQMuJg1&Nw-#Y8C=$C)t2vIXAQ07&4hE<a=x3=xl!0vO65SxsyY>2;Q`h4U-5epf1fwuE{kY}!94%Dg|G)((JH0OvCXcv!Ao`JkaZ7fN-D'
    'qxwW!P8y2f@>TZS`d!H7mz~CanFiqx4=YX6p(OWbT4+CHO>qT(ARN#+mGWI|ml@79%}Vw^sT!Ylsrn8IMNMna50nuA9+Q2i$*yfuLp8}DyZvSa=p(&6)I&Io'
    'fQQnamoa;g$YO0^MPu^#SFVp4K%%J+bJwtp%PjdKZj%<1bJjleb*PAn&s^^)Wz$#PtCwJaX!b;1HzCG5sXe#(T4P(o)Vly?LLGA67NS~-umMV0FXb=C51L85'
    '(f!kW4WTLoSq&x^3n)fhs0q;2!JVY+PY1pE>qC@uvZH058Eyr6AY_m|NNrtFOscp*a`1$qr4Ac+N&uEtTaBbZ90@q|YKL9~LMpG0awMse+Z#s-v1JZU<_hcO'
    'aR9=RJce$^6LEXME3`<4$SU7AAYhiZ_5VrMB1*$3mq|lvwCl0CA7~V)ScsDJ@sUMgA72@PaC?yBS{t(gKTCd@8ip;G22XlU&IWMRU0*ScX}y1xoN^}JR_j%C'
    'lp?N-qJ)LcyXU>&fibgwE$HMtvfc0)-7WLvmu^@SqKBd#X?#~Ua@!Oc&W=vp3@B_NELMuo?36<&vGwuwO6y$ur#VTTwr9Z#-;9b5Y4V3=+geOBGD_QN8O94q'
    '*vpWyJ4AZ^W1XB+>}EZ{v(T~T=vd|U1D)>jelK)<P=2_h4;;HLaNSpXA-q6gK0xqFHp@ezz>RX_1US|7d79r@IqT{PJ+)|J<~YP`u=JP@V!!lc74=bh0lwkS'
    'px$boOb*sFQ-9D+Q;HWCDz&p9bd&)%GWwUBZjc9}&5`o!)RbHsnDp4wnCBQ4SJyN&8{Gk`vz%_cI2^X*Zn3~SuIG}6{7#JT%mMIdC{~%KF$i3Qm3;yo+){`1'
    ')LwZ(7>`9Nu!C#FU?GaJEJ;CYsIW0_I`i42dEiDhj(~ad1lm`B{`DTDA<7(8;#Tyn?P{ln!u59d&lyFYiQt=KcyGqkd#iWBvh~~yNgdjG*HsK35FJ_Jt0(Vc'
    ')_cUyd`$pRw{@ykroK(ubHpn?S$Fu&ZxH{T%odQg`?zu@jENfmm*$0*D(xPSb#WW+aj7QSvxZMsnrX$2w*!XaR3U}jT+>6VNwUExmJ+l=rG;Bmyuf&8r{iaA'
    ';G?M*Koq&}{YTP{;`OR&IxjO=+&|t~B~ryH-~iWAi^G(Vym@kL`Oq6njXez)h&tk%Tl_8snpggEWErmD?ixD=_aE*-;e(1)h9h|3W8-d<8((Y7L06g?4%A<>'
    'GJ5$`G3v(iSxnylMO%Y|tDGd3qcAJ6+-G>E8_%u{7~5iDSP&W8V}sTk@+CWgtc$DZ66pA4+BGLRgryu_6nPa#HWK+<Gdk61aw?N=5X)l5`M6f3H7*pj#prjK'
    'HuqYk+4W8q{n5G%7_T?juf8%O*b_Ksp_)R7vMhj32(fri@e4qMDD;rnHXm8$eY-38$oZM%ugeVwv&zLMD@YN+d=;TZrBM0EIzF+VS2_5kUiYNP7{>DDeg`Ul'
    '9Ql<5+1&;5lHW63=9~ed>&xR#FTU?1R&?#ip?!Bnsq5>RSTWxz@HSGcC^d{&$S6^<pbR;nyW<ttmt1BG2W3Utpbtdi(4$sa{27Q-9MCmLG}m?MA}(F6p;UNS'
    'u7S`(%PrI7)?}QOdz`nHC6fvBhKAZE^3xT79yhf>{z2+sNga*HaaGFXQr4TxBq8fe5M%h3v;|mp`jMe{vrOO>#NP_APlLGS=+me2bHecy?Zh_)9XA0g?B@}E'
    'd=nP1qD6XrSA&VhsF9|BW*BZ@{v5ZAx`t6^HYs)faBM8f7AxCVypmXF|G3+&N$&M9bdVcgp11MB8owPXHI}5N88La)BFJ<YFBXXj+$SH2xP=oGOpFm4C~RQo'
    'i0-RCGvO->%+ev}YxQEW&#=Ae@XDj;5(9;Ie#IPB!YfJm!!;QOMGnr@G*?Qwrvq^a0T)sz;NmJ}y}E01ia~0{$b_;UMCPxXM^vPmqh_Ax`XfB^V>tA9T9wL-'
    '3bFu&Ly2m6X3CZP+LsV?&QC6`h3nBt1a*+Q6j^;vzI1vZ(vjRB^|tKJ7t7bHzn{)+7@l|9Axy7CQ!3>tacrqmDoj`2RcRyqT{8!>S?A&e2_+iK2X)%)Q5I6O'
    '7EP+YaLXDaT*LU=46HK`KWbJCOuV<KpE^(c&nl@zctta&WxktGBdv_3FdQRpF|6Yb&&4L_#@$9V_1_~N!c>k0`J_y)^ei(`aPEz03#}aSR=3`c!9KGNh;0JX'
    '@aBe?#Vv-N9+~kqZwu|{_$`Hyb7ivKVnq>gM2oj|DK;B3X<!aQOT9CC^@5$YX<+=*=lEzI!N<tKBSt85XC~rJ2I{d9oeuscuu_Pq%a9TqGrqp#3jt*}MklNI'
    '#b{^7*stK9)nrjqVR%3O3rwd!(`Nh?&XpZuJrGp7yb#QSwtLs<`NR?O@8;3M^^u04&`lAN5H{F*<(+)t09u>Z&d7+(m93}s=!bIjv83AMxxdAO*6A}jPMM+j'
    'j!|J})Kv6V?GUfb%5j&koRpqq3?;WLICRX_xu-B}KYFuK?dMIDvENy-AQjOcuVuWA<%TsW1}T{qk=+)N6BqaxK&1Vnb@yRX`K1ejnf6?iTX;ZGv+A2acn#ha'
    'sKwv9m~N0#b*<t`JAZ;;VK9G*+l>GNYZSvMRp28u>c2a35E#<GxOHP9(dBYf6)X8iqW%*;+{{DJZGx$GZZ;IlrW;_>wp*>IdO%JoIkzVHmj;QBLQRH@xKMaA'
    'o_li?`KxV-1jr7TJ#<~`NQycMK3e!uAbIxt;J@Z3cREUEc%V-;kg$R*mgm-{xBPK2*1W1eQ%5}hgSG5^8AR+o&zMo?Z|}ra4r`{oNrEkEBJ&?Vy2l@o91oC3'
    'Bs6=>Ds!|9C&2D;5~<_8%walxXwGl<h+lfyH6a_htwsiB-1g=j21u~09}9razB38bz$;4g%!Ox_It_&=O=3beKR^AIe>N4MLlRL{GB_TWdA}lqVbSBGcJd+}'
    'ABCyU1qgO#=yxxq$02FcBNEg2Gk#xw(xCeXr(Zcqf0gGMIpSI!ZOd;h<_75~`bgnfBL&JKEpNUrKQwE=bB8TnShe4zB?6MJ7v`7jVEEk{aS|~VBl`eg%o*9P'
    'ybwfj)eUgVY^{44a}ZkqZxO#U{O+S#Vg?XAJ9F#bZyr+>m90j-xvD9NRiHQ9e$IgS-24VTHVvlKCUXaEGtpbH#*s{yfcz5B>mXE6?BYHewBV!R<T;Fx;3KM='
    'gJ4nKZ<{(}lEC~HZ)UXsFJneHC7`~5yM^Lt8H)}{P`?}dY@q!GNQyuDujUx}p3P4XXO_f$1oHx17;yWl^2~p5xMHUzZ6-G~{tU)Is1qn5ra=(K7KekyKF}Xw'
    '8{JuvLK6)Ee0VEae6O*kk#|N`Ik)liog&}cA<83Iq)x{sE;AbdIR{cvj*EoOKTDQ6EGN=CxCUg-#UZO<QccY%4^ucGk&kAbts;kq9zRdqx!_k?*^F<wj(++5'
    'l6D*q16a*IDIi~OB%RwTM)>l<@vnOZVxS7szcB}hiu?gF?e*vWfk6+bky-BclQSZkW<;fk8;xUH+fy&(?G)POBnzb-0olm#Dax>;Zz+M)9&%>kNmzxGD#CZQ'
    'P)C^ocDJ%`nzmQq1>PU~&6Dfo{_Vy5uz%QRAL0c~rI|G4F!vuNinUJ)5ZLPopRnv@C??;IwYF8t0U5AdW9O+z;?LpU9M2_U4yH5nq~HdAr()f?7z@4o^9C!<'
    '9nX#a+dsWi-TDYt-T8NCE=esY3_1XWg2tzV=mz<v!ly!tzxoQi3e>p!B#6xr$1J@nv0P82d#8Ekuw?FMQr<GX>sp~HtUGT1#sssFX%kWD1lyg~Ec{8!F@dbe'
    'uCe)yUN_&NM4f0<>2O{B@!o@I+Kp;C!>qg6dG20fa2mGIy4IO&ff!w@y`;E8oA&y#+5g7r+B6uTG{<;mSSF#QeOz#&cS;XGSY?>XtbPZ}(p5`!Zo%BJIB4+L'
    'T76XRtx7%2q347UB7Fyk1EOL*Xj7uq7?uf93dS_ZZ@$(yk-n`VoZ>Fz<1JK*iB6W4+qU=rItQT!tlKDko@M*$mzCy`h^s0^4%i7xD83G-$|JsU?z^@VvRu@}'
    '6nkOkD|w*b=}aei)h5xCnq$^pn=e~O<Toj2c;(L;cI`L&b`U)ofK?yYx67?QkQiwzVSYehM@7uMx1_(Ls-9^HaxI1dHvY0CzwJ-slTp_UDPfi5_T3yam_=R5'
    '6b;|heeDgh40RrEt7bh*SP1Ln(`+ZD)%t0xML2xbbTEpc4+J7)mK&4|txJKMKcGuA6XGqhsEh`hN#66mN_1{h`9&=~aC`r-#5x1#hV6Y}_%L&PLn#f=PNT2L'
    'ZyA93imRB8q!h@K33eL%IeGJ7I>Jsyy}YF83BypRo)==Sq9{=F@FvYI8NI|PKywpMRpf@KblBXxS*?F%(}r(|D0^fvmw)38&@jF8<a3#rm7;L$57fQC1A22q'
    '6mkg<di;n&y4PG{SG`-4i7JIj?HnYkO@@Rh?DJIJI>WG~J`%U9Em0TeK4l&gM}0W1yUZhISe<U)FgmdNk^On<e^JdX@F<_xUgz%7&Yt*`rkHKMw~*kDY91^Q'
    '=aX4=qLL>aVEXjVKrJJ8j3&1o=>AzCCd@vm%}Q6MFoet8FCf9U%S?CiB+ZX_xsknTnJ*>m^ZU_W1>WKod46eejdU=o7)rTCRdEXi#)`>~?$YNFOKFlvYP~@U'
    'DbP<&`lvCvLJoV`mK26Onn1(@SrbrA$C*AL+LO!>{%FXwh?B?p6EJ~S2lj|v#j9n5wI(sxdDaJf&E5v=C*Ox68<CpB>!Ug?PxS!M%RTN?aOo5u?8+8cn)CN)'
    'g!w9UfhZ1E$27NK6em+XnQaiuk^yJpq=;mFy?ukKV<+-|W0F$u%Sv*btLtNX-$X*qV#sE%MNlCJ@B`=;nV+oxFsR!g0+~1x(*P7?gzgnfy+2Y6iXa+fnY=Qq'
    'yI4+v;Kuc6R9~+%v{ZfPnm^T0IJM0N`(17TM81!D1&p%uiSxH#!H%)8l<71`kB()gn`pG0ldD?Z$h#?flA(YHQ<sV)cDy}1N}1{_po#l8?%dwX#4Dx^4|mGZ'
    'q_fPc`ipe#M`XWa0HK(6jaLL%SHaaw?WmX|0vjEAZmHCDnD&|3{)e8oM+wsUYsbpR$8oNldZ=1G*P-Wf>qE87jEjV)e9k2Y*IY`t<DFM!|BAalje%jU5`G&!'
    'uwvv?yCCp+i^MH<=FlYoVlj@R-4Z2zoF|2s%kzbJ|Jc}(YL{;^0rtoB9YjFB$h&u`00000VZ77zjNy=%00EJO0o&UMiw7P#vBYQl0ssI200dcD'
)


_EMBEDDED_ARTIFACT_CACHE: Optional[dict[str, bytes]] = None


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
    allow_attachments=True,
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


def load_meta(config: StrategyConfig) -> dict:
    payload = json.loads(_artifact_bytes(config.metrics_file).decode("utf-8"))
    return payload.get("meta", payload)


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
        f"&klt=101&fqt=1&beg=20050101&end={end_date}&lmt=10000"
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
        f"/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=10000"
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
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,10000,qfq"
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


def _fetch_csindex_amount(secid: str, *, beg: str = "20050101", lmt: int = 10000) -> pd.DataFrame:
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
        resp = sess.get(url, timeout=15, headers=headers)
        data = resp.json()
        if resp.status_code != 403:
            resp.raise_for_status()
    else:
        data = _get_json(url, timeout=15, headers=headers)
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
    score = _bias_momentum_for_live(close, bias_ma=bias_ma, mom_day=mom_day, weight_end=weight_end)
    latest_date = score.dropna().index[-1] if not score.dropna().empty else close.index[-1]
    latest_score = float(score.reindex(close.index).iloc[-1]) if pd.notna(score.reindex(close.index).iloc[-1]) else math.nan
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
    target = 1.0 if score_pass and abs_pass else 0.0
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
    score = _bias_momentum_for_live(
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
    for asset in legs:
        amount_col = f"{asset}_amount"
        if amount_col in panel.columns:
            out[amount_col] = pd.to_numeric(panel[amount_col], errors="coerce").reindex(out.index)
    amount_a = f"{long_asset}_amount"
    amount_b = f"{short_asset}_amount"
    ratio_col = f"amount_ratio_{long_asset}_{short_asset}"
    if amount_a in out.columns and amount_b in out.columns:
        out[ratio_col] = out[amount_a] / out[amount_b].replace(0, math.nan)
    amount_state = _live_amount_state(meta, panel, long_asset, short_asset)
    if amount_state.get("available"):
        amount_section = _amount_overlay_section(meta)
        family = str(amount_section.get("family") or "")
        metric = "volume" if "volume" in family else "amount"
        online_state = _live_metric_overlay_state(amount_section, panel, long_asset, short_asset, None, metric)
        if online_state.get("available") and online_state.get("date"):
            state_date = pd.Timestamp(str(online_state["date"]))
            if state_date in out.index:
                out.loc[state_date, "amount_gate"] = 1.0 if online_state.get("gate") else 0.0
                out.loc[state_date, "amount_ma_ratio"] = online_state.get("value", math.nan)
    for section in _volume_overlay_sections(meta):
        online_state = _live_metric_overlay_state(section, panel, long_asset, short_asset, None, "volume")
        if online_state.get("available") and online_state.get("date"):
            state_date = pd.Timestamp(str(online_state["date"]))
            if state_date in out.index:
                key = str(section.get("_meta_key") or "volume_overlay")
                if key == "layer10_volume_overlay":
                    out.loc[state_date, "layer10_volume_gate"] = 1.0 if online_state.get("gate") else 0.0
                    out.loc[state_date, "layer10_volume_ma_ratio"] = online_state.get("value", math.nan)
                elif key == "final_ridge_overlay":
                    out.loc[state_date, "final_ridge_gate"] = 1.0 if online_state.get("gate") else 0.0
                    out.loc[state_date, "final_ridge_indicator"] = online_state.get("value", math.nan)
                else:
                    out.loc[state_date, "volume_gate"] = 1.0 if online_state.get("gate") else 0.0
                    out.loc[state_date, "volume_ma_ratio"] = online_state.get("value", math.nan)
    vol = _vol_overlay_section(meta)
    if vol.get("enabled") and vol.get("window") not in (None, ""):
        vol_series = close.pct_change().rolling(int(vol.get("window"))).std(ddof=0) * math.sqrt(ANNUAL_DAYS)
        for col in ("overheat_indicator", "volhot_indicator", "vol_indicator", "realized_vol", "base_realized_vol"):
            out[col] = vol_series
        if vol.get("kind") == "downonly_tv":
            cap = vol_series.apply(_downonly_tv_scale_from_realized_vol, args=(vol,))
            mult = cap.shift(1).fillna(1.0)
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


def _online_target_series(close: pd.Series, score: pd.Series, meta: dict) -> pd.Series:
    signal = meta.get("signal", {}) if isinstance(meta.get("signal", {}), dict) else {}
    threshold = float(signal.get("score_threshold") or 0.0)
    target = score > threshold
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
        raw = min(max(float(target) / rv, 0.0), max_leverage)
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
) -> float:
    multiplier = 1.0

    nav = meta.get("nav_defense", {}) if isinstance(meta.get("nav_defense", {}), dict) else {}
    if nav.get("enabled"):
        dd, _nav_col = _nav_drawdown_for_row(curve_so_far, row)
        gate = math.isfinite(dd) and dd <= -abs(_safe_float(_threshold_from_section(nav), 0.0))
        row["nav_defense_gate"] = 1.0 if gate else 0.0
        row["base_nav_defense_gate"] = row["nav_defense_gate"]
        if gate:
            multiplier *= _scale_from_section(nav)

    vol = _vol_overlay_section(meta)
    if vol.get("enabled"):
        current = math.nan
        for col in ("overheat_indicator", "volhot_indicator", "vol_indicator", "realized_vol", "base_realized_vol"):
            if col in row and math.isfinite(float(row[col])):
                current = float(row[col])
                break
        if vol.get("kind") == "downonly_tv":
            scale = _first_numeric(row, ("overheat_scale", "volhot_scale", "vol_scale"))
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
        gate_value = row.get("amount_gate", 0.0)
        try:
            gate = math.isfinite(float(gate_value)) and float(gate_value) != 0.0
        except (TypeError, ValueError):
            gate = False
        if gate:
            multiplier *= _scale_from_section(amount)

    for volume in _volume_overlay_sections(meta):
        gate = False
        for col in volume.get("_gate_cols", ()):
            gate_value = row.get(col, 0.0)
            try:
                if math.isfinite(float(gate_value)) and float(gate_value) != 0.0:
                    gate = True
                    break
            except (TypeError, ValueError):
                continue
        if gate:
            multiplier *= _scale_from_section(volume)

    scorehot = meta.get("score_overheat", {}) if isinstance(meta.get("score_overheat", {}), dict) else {}
    if scorehot.get("enabled"):
        score_value = float(row.get("score", math.nan))
        gate = math.isfinite(score_value) and score_value >= float(_scorehot_threshold(scorehot) or math.inf)
        row["scorehot_gate"] = 1.0 if gate else 0.0
        row["scorehot_indicator"] = score_value
        row["scorehot_scale"] = _scale_from_section(scorehot)
        if gate:
            multiplier *= _scale_from_section(scorehot)

    decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
    if decay.get("enabled"):
        signal_idx = signal_frame.index[signal_frame.index < idx]
        as_of = signal_idx[-1] if len(signal_idx) else idx
        _apply_online_decay_state(row, signal_frame, pd.Timestamp(as_of), meta)
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
) -> dict:
    if idx not in signal_frame.index or curve_so_far.empty:
        return row
    prev_idx = curve_so_far.index[-1]
    prev_row = curve_so_far.iloc[-1]
    spread = pd.to_numeric(signal_frame["spread_close"], errors="coerce")
    if idx not in spread.index or prev_idx not in spread.index:
        return row
    spread_ret = float(spread.loc[idx] / spread.loc[prev_idx] - 1.0)
    target_series = _online_target_series(spread, pd.to_numeric(signal_frame["score"], errors="coerce"), meta)
    signal_date = prev_idx if prev_idx in target_series.index else target_series.loc[target_series.index < idx].index[-1]
    target = float(target_series.loc[signal_date]) if signal_date in target_series.index else 0.0
    vol_series = spread.pct_change().rolling(int((meta.get("target_vol", {}) or {}).get("target_vol_window") or 20)).std(ddof=0) * math.sqrt(ANNUAL_DAYS)
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
    row["base_gross_exposure"] = base_exposure
    row["base_nav"] = base_nav
    row["nav_decay_nav"] = base_nav
    row["base_target_vol_raw_scale"] = raw_scale
    row["target_vol_raw_scale"] = raw_scale
    row["base_target_vol_scale"] = target_scale
    row["target_vol_scale"] = target_scale
    row["base_target_vol_deadband_suppressed"] = suppressed
    row["target_vol_deadband_suppressed"] = suppressed
    row["base_realized_vol"] = _previous_online_value(vol_series, idx + pd.Timedelta(nanoseconds=1))
    row["realized_vol"] = row["base_realized_vol"]

    multiplier = _online_gate_and_multiplier(idx, row, prev_row, meta, signal_frame, curve_so_far)
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
    row["gross_exposure"] = exposure
    row["gross_return"] = gross_return
    row["cost"] = cost
    row["turnover"] = abs(exposure - prev_exposure)
    row["return"] = net_return
    row["nav"] = prev_nav * (1.0 + net_return)
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
            row = _fill_online_execution_row(idx, row, curve_so_far, metas.get(config.key, {}), online_signal)
            rows.append((idx, row))
        extra = pd.DataFrame([row for _, row in rows], index=pd.DatetimeIndex([idx for idx, _ in rows]))
        refreshed[config.key] = pd.concat([curve, extra], axis=0).sort_index()
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

        spread = pd.to_numeric(signal_frame["spread_close"], errors="coerce")
        score = pd.to_numeric(signal_frame.get("score", pd.Series(index=signal_frame.index, dtype=float)), errors="coerce")
        target_series = _online_target_series(spread, score, meta)
        decay_state_frame = _online_decay_state_frame(signal_frame, meta)
        target_vol = meta.get("target_vol", {}) if isinstance(meta.get("target_vol", {}), dict) else {}
        tv_window = int(target_vol.get("target_vol_window") or 20)
        vol_series = spread.pct_change().rolling(tv_window).std(ddof=0) * math.sqrt(ANNUAL_DAYS)
        valid_index = signal_frame.loc[spread.notna()].index
        tail_index = list(valid_index if full_history else valid_index[-2:])
        rows: list[tuple[pd.Timestamp, dict]] = []
        prev_exposure = 0.0
        prev_target_scale = 1.0
        prev_nav = 1.0
        cost_rate = _cost_rate_from_meta(meta)
        for idx in tail_index:
            signal_row = signal_frame.loc[idx]
            row = signal_row.to_dict()
            is_provisional = provisional_date is not None and pd.Timestamp(idx).normalize() == provisional_date
            signal_idx = signal_frame.index[signal_frame.index < idx]
            exec_signal_idx = signal_idx[-1] if len(signal_idx) else idx
            target = (
                float(target_series.loc[exec_signal_idx])
                if exec_signal_idx in target_series.index and pd.notna(target_series.loc[exec_signal_idx])
                else 0.0
            )
            raw_scale = 1.0
            target_scale = 1.0
            suppressed = 0.0
            if target_vol.get("enabled"):
                rv = (
                    float(vol_series.loc[exec_signal_idx])
                    if exec_signal_idx in vol_series.index and pd.notna(vol_series.loc[exec_signal_idx])
                    else math.nan
                )
                max_leverage = float(target_vol.get("max_leverage") or 1.0)
                target_vol_value = target_vol.get("target_vol")
                if target_vol_value not in (None, "") and math.isfinite(rv) and rv > 1e-12:
                    raw_scale = min(max(float(target_vol_value) / rv, 0.0), max_leverage)
                    target_scale = raw_scale
                    gate = target_vol.get("gate")
                    if gate not in (None, "") and raw_scale > (1.0 - float(gate)):
                        target_scale = 1.0
                        suppressed = 1.0 if abs(raw_scale - target_scale) > 1e-12 else 0.0
                    if (
                        target > 0.0
                        and prev_exposure > 1e-12
                        and _target_vol_deadband_suppressed(raw_scale, prev_target_scale, target_vol)
                    ):
                        target_scale = prev_target_scale
                        suppressed = 1.0
            base_exposure = target * target_scale
            spread_ret = 0.0
            if len(signal_idx) and exec_signal_idx in spread.index and idx in spread.index:
                prev_spread = float(spread.loc[exec_signal_idx])
                curr_spread = float(spread.loc[idx])
                if math.isfinite(prev_spread) and abs(prev_spread) > 1e-12 and math.isfinite(curr_spread):
                    spread_ret = curr_spread / prev_spread - 1.0
            row.update(
                {
                    "target": target,
                    "raw_signal": target,
                    "exec_signal": target,
                    "base_gross_exposure": base_exposure,
                    "target_vol_raw_scale": raw_scale,
                    "base_target_vol_raw_scale": raw_scale,
                    "target_vol_scale": target_scale,
                    "base_target_vol_scale": target_scale,
                    "target_vol_deadband_suppressed": suppressed,
                    "base_target_vol_deadband_suppressed": suppressed,
                    "base_realized_vol": float(vol_series.loc[exec_signal_idx]) if exec_signal_idx in vol_series.index and pd.notna(vol_series.loc[exec_signal_idx]) else math.nan,
                    "realized_vol": float(vol_series.loc[exec_signal_idx]) if exec_signal_idx in vol_series.index and pd.notna(vol_series.loc[exec_signal_idx]) else math.nan,
                    "gross_exposure": base_exposure,
                    "online_rebuilt_bar": 1.0,
                    "online_provisional_bar": 1.0 if is_provisional else 0.0,
                }
            )
            _apply_online_decay_state(row, signal_frame, pd.Timestamp(exec_signal_idx), meta, decay_state_frame)
            multiplier = _current_overlay_multiplier(pd.Series(row), meta, None)
            if math.isfinite(multiplier):
                row["gross_exposure"] = base_exposure * multiplier
            exposure = float(row.get("gross_exposure", 0.0) or 0.0)
            turnover = abs(exposure - prev_exposure)
            gross_return = exposure * spread_ret
            cost = turnover * cost_rate
            net_return = gross_return - cost
            prev_nav *= 1.0 + net_return
            row["gross_return"] = gross_return
            row["cost"] = cost
            row["turnover"] = turnover
            row["return"] = net_return
            row["nav"] = prev_nav
            prev_exposure = exposure
            prev_target_scale = target_scale
            rows.append((pd.Timestamp(idx), row))

        curves[config.key] = pd.DataFrame(
            [row for _, row in rows],
            index=pd.DatetimeIndex([idx for idx, _ in rows]),
        ).sort_index()
    return curves


def load_strategy_context(include_realtime: bool = False) -> tuple[dict[str, pd.DataFrame], dict[str, dict], dict[str, object]]:
    metas = load_strategy_metas()
    online: dict[str, object] = {"ok": False, "error": None, "probes": {}}
    curves: dict[str, pd.DataFrame] = {}
    local_error: Optional[str] = None
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
            if not ALLOW_ONLINE_REBUILD:
                raise RuntimeError(
                    "formal daily artifacts are unavailable; refusing unverified online full-history rebuild "
                    "(set POE_ADK_ALLOW_ONLINE_REBUILD=1 for diagnostic use only)"
                )
            curves = _build_curves_from_online_prices(metas, panel, full_history=True)
            data_mode = "online_rebuild"
        probes = {
            config.key: _live_probe_for_strategy(config, metas[config.key], panel, seed_curve=curves[config.key])
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
            if not ALLOW_ONLINE_REBUILD:
                raise RuntimeError(
                    "formal daily artifacts are unavailable; refusing unverified online full-history rebuild "
                    "(set POE_ADK_ALLOW_ONLINE_REBUILD=1 for diagnostic use only)"
                )
            curves = _build_curves_from_online_prices(metas, panel, full_history=True)
            data_mode = "online_rebuild_full"
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
    ann_return = final_nav ** (ANNUAL_DAYS / max(rows, 1)) - 1.0
    ann_vol = float(returns.std(ddof=0) * math.sqrt(ANNUAL_DAYS)) if rows > 1 else 0.0
    max_dd = float(drawdown(nav).min())
    sharpe = ann_return / ann_vol if ann_vol > 1e-12 else math.nan
    calmar = ann_return / abs(max_dd) if abs(max_dd) > 1e-12 else math.nan
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
    rows = [(display, metrics_for_curve(_slice_curve(curves_to_report[key], start, end))) for key, display in order]
    lines = [heading, "", f"- 查询区间: **{label}** ({start:%Y-%m-%d} 至 {end:%Y-%m-%d})", f"- 口径: {note}"]
    if online.get("ok"):
        latest = max((df.index.max() for df in curves.values() if not df.empty), default=end)
        lines.append(f"- 在线刷新: **成功**（{online.get('mode', 'daily')}，最新 {latest:%Y-%m-%d}，抓取 {online.get('fetched_at', 'N/A')}）")
        if online.get("data_mode") == "online_rebuild_full":
            lines.append("- 数据来源: Poe 在线重建（Sina/EastMoney/Tencent 公开指数日线 + 脚本内嵌参数 metadata），不读取本地文件。")
            lines.append("- 注意: 该口径用于 Poe 在线展示；若本地正式 artifacts 有额外人工固化字段，结果可能有小幅差异。")
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
        if len(series) >= 2:
            candidates.append((len(series), -len(candidates), col, series))
    if not candidates:
        return math.nan, "nav"
    max_len = max(item[0] for item in candidates)
    min_len = max(2, int(max_len * 0.8))
    _, _, nav_col, nav = max((item for item in candidates if item[0] >= min_len), key=lambda item: item[1])
    if nav.empty:
        return math.nan, nav_col
    high = float(nav.cummax().iloc[-1])
    last = float(nav.iloc[-1])
    if high <= 0:
        return math.nan, nav_col
    return last / high - 1.0, nav_col


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
    current = _score_current_value(curve, row)
    if not math.isfinite(current):
        current = float(series.iloc[-1])
    peak = float(series.cummax().iloc[-1])
    if peak <= 1e-12:
        return math.nan
    return current / peak


def _strict_active_decay_state(
    score: pd.Series,
    active: pd.Series,
    as_of: pd.Timestamp,
    decay: dict,
) -> tuple[float, float, float]:
    decay_ratio = _safe_float(_decay_threshold(decay))
    recovery_ratio = _safe_float(_decay_recovery_threshold(decay))
    confirm_days = int(_safe_float(decay.get("confirm_days"), 1.0))
    scale = _scale_from_section(decay)
    if not math.isfinite(decay_ratio) or not math.isfinite(recovery_ratio):
        return math.nan, math.nan, scale

    frame = pd.DataFrame({"score": pd.to_numeric(score, errors="coerce"), "active": active.astype(float)})
    frame = frame.loc[frame.index <= as_of]
    if frame.empty:
        return math.nan, math.nan, scale

    peak = math.nan
    in_decay = False
    need_new_peak = False
    below_count = 0
    last_ratio = math.nan

    for _, item in frame.iterrows():
        is_active = _safe_float(item.get("active"), 0.0) > 0.5
        cur_score = _safe_float(item.get("score"))
        if (not is_active) or (not math.isfinite(cur_score)) or cur_score <= 0.0:
            peak = math.nan
            in_decay = False
            need_new_peak = False
            below_count = 0
            continue

        if not math.isfinite(peak):
            peak = cur_score
            in_decay = False
            need_new_peak = False
            below_count = 0
        elif cur_score > peak:
            peak = cur_score
            if need_new_peak:
                need_new_peak = False

        ratio = cur_score / peak if peak > 0 else math.nan
        if math.isfinite(ratio):
            last_ratio = ratio

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

    gate = 1.0 if in_decay else 0.0
    mult = scale if in_decay else 1.0
    return last_ratio, gate, mult


def _generic_score_peak_decay_state(score: pd.Series, as_of: pd.Timestamp, decay: dict) -> tuple[float, float, float]:
    decay_threshold = _safe_float(_decay_threshold(decay))
    recovery_threshold = _safe_float(_decay_recovery_threshold(decay))
    scale = _scale_from_section(decay)
    if not math.isfinite(decay_threshold):
        return math.nan, math.nan, scale
    if not math.isfinite(recovery_threshold):
        recovery_threshold = decay_threshold

    hist = pd.to_numeric(score.loc[score.index <= as_of], errors="coerce").dropna()
    if hist.empty:
        return math.nan, math.nan, scale

    score_peak: Optional[float] = None
    derisk_next = False
    waiting_for_new_peak = False
    rearm_peak: Optional[float] = None
    last_ratio = math.nan

    for value in hist:
        cur_score = float(value)
        score_peak = cur_score if score_peak is None else max(score_peak, cur_score)
        ratio = cur_score / score_peak if score_peak is not None and score_peak > 1e-12 else math.nan
        if math.isfinite(ratio):
            last_ratio = ratio

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

    gate = 1.0 if derisk_next else 0.0
    mult = scale if derisk_next else 1.0
    return last_ratio, gate, mult


def _online_decay_active_series(signal_frame: pd.DataFrame, meta: dict) -> pd.Series:
    if "spread_close" not in signal_frame.columns or "score" not in signal_frame.columns:
        return pd.Series(1.0, index=signal_frame.index)
    spread = pd.to_numeric(signal_frame["spread_close"], errors="coerce")
    score = pd.to_numeric(signal_frame["score"], errors="coerce")
    return _online_target_series(spread, score, meta)


def _online_decay_state_frame(signal_frame: pd.DataFrame, meta: dict) -> pd.DataFrame:
    decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
    if not decay.get("enabled") or "score" not in signal_frame.columns:
        return pd.DataFrame(index=signal_frame.index)
    score = pd.to_numeric(signal_frame["score"], errors="coerce")
    if "decay_ratio" in decay:
        active = _online_decay_active_series(signal_frame, meta)
        decay_ratio = _safe_float(_decay_threshold(decay))
        recovery_ratio = _safe_float(_decay_recovery_threshold(decay))
        confirm_days = int(_safe_float(decay.get("confirm_days"), 1.0))
        scale = _scale_from_section(decay)
        peak = math.nan
        in_decay = False
        need_new_peak = False
        below_count = 0
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
            else:
                if not math.isfinite(peak):
                    peak = cur_score
                    in_decay = False
                    need_new_peak = False
                    below_count = 0
                elif cur_score > peak:
                    peak = cur_score
                    if need_new_peak:
                        need_new_peak = False
                ratio = cur_score / peak if peak > 0 else math.nan

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
        parts = [
            _pass_text(score_pass),
            f"Score {num(score_value, 3)} / 阈值 {num(score_threshold, 3)}",
        ]
        abs_day = _signal_abs_day(signal)
        abs_threshold = _safe_float(signal.get("abs_threshold"))
        abs_mom = _safe_float(probe.get("abs_mom") if probe else math.nan)
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
        parts = [
            _gate_text(gate) if math.isfinite(gate) else "静态未导出",
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
        current_cols = ("decay_ratio_signal_day", "decay_indicator", "score_decay_ratio_overlay", "decay_aux")
        has_current_decay_col = any(col in row.index for col in current_cols)
        current = _first_numeric(row, current_cols) if has_current_decay_col else _first_numeric_with_history(curve, row, current_cols)
        if not math.isfinite(current) and not has_current_decay_col:
            current = _score_peak_decay_ratio(curve, row)
        scale = _scale_from_section(decay)
        mult = _first_numeric_with_history(curve, row, ("decay_mult", "decay_scale"))
        if not math.isfinite(gate) and math.isfinite(mult):
            gate = 0.0 if abs(mult - 1.0) < 1e-12 else 1.0
        if not math.isfinite(gate):
            gate = _infer_gate_from_threshold(current, _decay_threshold(decay), "<=")
        rows.append((
            "动量衰减",
            _detail_join([
                _gate_text(gate) if math.isfinite(gate) else "静态未导出",
                f"当前 {num(current, 3)}",
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
        overlay_multiplier = _current_overlay_multiplier(row, meta, amount_gate_override)
    if not math.isfinite(overlay_multiplier):
        overlay_multiplier = math.nan

    post_close_tv_scale = _first_numeric(row, ("target_vol_raw_scale", "raw_scale", "target_vol_scale", "base_target_vol_scale", "target_vol_applied_scale", "applied_scale", "scale"))
    if not math.isfinite(post_close_tv_scale):
        post_close_tv_scale = tv_scale if math.isfinite(tv_scale) else 1.0
    if not tv.get("enabled"):
        post_close_tv_scale = 1.0
    post_close_overlay = overlay_multiplier if math.isfinite(overlay_multiplier) else 1.0
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

    detail_rows = _overlay_detail_rows(confirmed_curve, row, meta, probe=probe, live=live)
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
        "overlay_summary": _overlay_summary(row, amount_gate_override),
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
    else:
        lines.append("- Data source: unavailable")
    lines.append("")

    configs = {config.key: config for config in STRATEGIES}
    for _pair_key, pair_display, forward_key, reverse_key in PAIR_DEFS:
        forward_config = configs[forward_key]
        reverse_config = configs[reverse_key]
        forward = _strategy_signal_snapshot(forward_config, curves[forward_key], metas[forward_key], online, live)
        reverse = _strategy_signal_snapshot(reverse_config, curves[reverse_key], metas[reverse_key], online, live)
        pair_title = pair_display.replace(" 正反50/50", "")
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
    if live:
        curves, metas, online = load_strategy_context(include_realtime=True)
    else:
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
    curves = load_strategy_curves()
    if not curves:
        return "No signal data available."

    lines = ["## 信号历史", ""]
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
    if "参数" in compact and "实时" in compact:
        return render_params(live=True)
    if "参数" in compact:
        return render_params(live=False)
    if "组合表现" in compact:
        return render_performance(normalized, combo=True)
    if "表现" in compact:
        return render_performance(normalized, combo=False)
    if "实时" in compact and "信号" in compact:
        return render_signal(live=True)
    if "信号" in compact:
        return render_signal(live=False)
    if "历史" in compact and "信号" in compact:
        return render_signal_history(normalized)
    return render_signal(live=False)

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
    query = str(query).strip() or "??"
    with poe.start_message() as msg:
        try:
            _write_query_response(msg, query)
        except Exception as exc:
            msg.write("## 閺屻儴顕楁径杈Е\n\n")
            msg.write(f"`{exc}`\n")
    return 0


def run() -> int:
    query_obj = getattr(poe, "query", None)
    query = getattr(query_obj, "text", "") if query_obj is not None else ""
    query = str(query).strip() or "螤螘螉螘"
    with poe.start_message() as msg:
        try:
            _write_query_response(msg, query)
        except Exception as exc:
            msg.write("## 鏌ヨ澶辫触\n\n")
            msg.write(f"`{exc}`\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

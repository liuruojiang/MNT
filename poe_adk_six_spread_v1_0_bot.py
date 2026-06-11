# poe: name=ADK-Six-Spread-V1
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
)


PAIR_DEFS = (
    ("zz1000_hs300_pair50", "中证1000/沪深300 正反50/50", "forward_zz1000_hs300", "reverse_hs300_zz1000"),
    ("cyb_zz1000_pair50", "创业板/中证1000 正反50/50", "forward_cyb_zz1000", "reverse_zz1000_cyb"),
    ("cyb_hs300_pair50", "创业板/沪深300 正反50/50", "forward_cyb_hs300", "reverse_hs300_cyb"),
    ("zz1000_sz50_pair50", "中证1000/上证50 正反50/50", "forward_zz1000_sz50", "reverse_sz50_zz1000"),
    ("cyb_sz50_pair50", "创业板/上证50 正反50/50", "forward_cyb_sz50", "reverse_sz50_cyb"),
)

PAIR_CHART_LABELS = {
    "zz1000_hs300_pair50": "ZZ1000/HS300 50/50",
    "cyb_zz1000_pair50": "CYB/ZZ1000 50/50",
    "cyb_hs300_pair50": "CYB/HS300 50/50",
    "zz1000_sz50_pair50": "ZZ1000/SZ50 50/50",
    "cyb_sz50_pair50": "CYB/SZ50 50/50",
}

CN_PRICE_SECIDS = {
    "zz1000": "1.000852",
    "hs300": "1.000300",
    "cyb": "0.399006",
    "sz50": "1.000016",
}

CN_SINA_SYMBOLS = {
    "zz1000": "sh000852",
    "hs300": "sh000300",
    "cyb": "sz399006",
    "sz50": "sh000016",
}

CN_TENCENT_SYMBOLS = CN_SINA_SYMBOLS

CN_ASSET_NAMES = {
    "zz1000": "涓瘉1000",
    "hs300": "娌繁300",
    "cyb": "CYB",
    "sz50": "涓婅瘉50",
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
}

ONLINE_DISABLED = os.environ.get("POE_ADK_DISABLE_ONLINE", "").strip().lower() in {"1", "true", "yes", "on"}
USE_LOCAL_ARTIFACTS = os.environ.get("POE_ADK_USE_LOCAL_ARTIFACTS", "").strip().lower() in {"1", "true", "yes", "on"}


_EMBEDDED_ARTIFACT_BLOB = (
    '{Wp48S^xk9=GL@E0stWa8~^|S5YJf5;YqzK6kPxS0^wY5^9U4!{dN%z@g+kT;2?g2sva(CX#H2EkJAJ9DJup&`>!m4jDf9x;(Eo~s<6s{c|(m1?IPr|#`kFI'
    'Vfn4%P3AIl^FOsTYUZ)SyA&hr-B(43A%&r5C1fNx>9A#fQ3THGJapsoSA7tMvGA-S;ndGOcigH;Ex({OleJpmxMuMmTym2FG>jZVP#l+1V|z_%H2t=b1ro)%'
    '@^H@VHcpTiOJ4Sgm4$T2cUI5ku%HZZ`0Ly`IT#xGgvFQ9GG97;65c3g6=?D-qHgp_Oi-Q{>Bk&Hn?=A<n#D$~`N^-y9+@Cd&+#-cB0`@y?_{z4u7@HSN$Hk7'
    '|BR#TpAW9LV(t$h+w84FAJ>t==BPW{<4x$gI%_5(TtrpXrzGt5`0*jpJhk^PQ)64p(0I|n&k9oMFQ~dIgK~HXVS>ZZm;mj^;y{0BS`^QK+E|50`UXGfGM2HV'
    'XR3RP)%!>tm-#pT(Yg-nU_lt$YJD)Agmm_=NV}2uyh&~rV$x;Cw+Y}C*wzrZW|-8BA7x3@Cj<pr6lc%}@3AEL97y&;T^jd66rUj!6QZz_aDFqT<L~j}!-eL%'
    'HNjX>9bKtP*rcKGuZK%OUX={C((K!^&d~zjDrELo2>=@-2!Nxhgk=Zq1qNF3xuOr(6P_~~cJI`Ka10H;enZT3(}tamLE}<%tD>nf8hhb0*Ku&8A4G=zmRrAu'
    '9|E5v9l&6Ufpz0}Ap(tOFtM8EugBc1XmQu{^lfH2HNgnnM}d)Pd2kQ(O4?<w1muzUe)pmu?*jYTZ+?__b1<Y81&=XqCh+3G?Cmd!@1}uXl^H|7>b8utRgw@)'
    'bU6@sv!JaB7t`GanxnFTmNyL;0Tj5say1DsO(LiM+}rX)JJ9N{P2gMygi;2yXuX&&Ci#hm{w*mD6|@P&!W;L0$O@bi4Wd)JOqXYsj;wGT_00Z{sPJLT9>4>w'
    '2+|Z9(QXm?hm#u%<KdAi_Ezg}n7%3Ys6P{0;i+?Lp%GwvKG$4dF#|1J8aXPCcKN5pI3(0QZ%no7nh}HqbSvXlARO5ipC91a3HU*Ew_5{y%Yxv(diOe^n7X)2'
    'Da*fQqg&nvpW~-#4<Kt>_l=z5F2yS}Ic|+WAZe?DryE=Et5+vm!@D!$onPK|h-P={8Z1>evz3E-;M*@=oE!F5FmQWMz;TU*%+@ENaa(KMz{xJX&iR5s+57Wn'
    'Y(3QRa|9)oK+OhP1jX8}#HLC39X`fsOa!73W7%+!1EvQdD=lC=b<M>1J#7xDvHBbodnw)e^vRG?1gvi;rKs=saIFK&C^YGmGMeBU6WR!+ek%7E&?hN+u4ZpY'
    'Qnsf(qtA7wLpSy0cZisgNc<g$ar5<kB|$Zo`s)JD$39K3sp&=}@pErHBqOh${lkJS&S(*}sz$J&I>^YMp>71lnuTrLw4=0;o(rTW6Ha;FSXKh^F<agyPVL%M'
    'Cab7jV#6WlGCHoVX{I+IaGv!lkh6(SZxgacK<hf(eFE5V4-D1fCSzBb)H{fm7b&QnE$5vB`N})S`*db0h|_NIAqid8erdvGUuooge8<EAP`qN8;CL*p`U`)%'
    '16M|N%|9s1xjvEkmgENSBcgO#Ocn$+Me=r);3U9F7$L1w+VS2EH>^}+8688J%*7WS8?2`OPVNzcBFh6!7$dYCAM}~qG0}FbYxHS^Ws3t@vqwM9Z5VcIs`mD%'
    'DrTU}xw!C_KMSTpf#0S8eUY#3K}75ACwvRDK$y9#@u`${8da<zvrK4$Rp}nw)j!wqsov=s?cC_82q#vG;{mQ4hH;@0q9XuKf9NIYvPq<Lg^n|85g-e{NZFvW'
    '8ysXfVkm-J`6_X6G#GIm9j2t@2QU0fwlf8i1h<q>EyCJkPGx^NH+nQ{_J-OCdPq!<!@iDDDp`i>tMsGB-Y+t~)^F%jMmVMp+!QXv!QULkO6~L{GZK1E_^X~W'
    '<$2JvqCG7#Hf9U+%nyOF(<4}7S!{d8zS-ro*O>_%y68>V`>$YMN}`vTW@@WrQdm*Qgci2h(EYefFSN|g;_4)pTrFu7)-FcvDb<~M__xBGrJSN(%z26ojHss1'
    'BQMiTw>x3L!PSfSR}ac8kU=T(i6Z2TLNf68gjTor)UbL9v@O&~rp3ao$EtS_*v1pING7&d{U~Y2Kx9rW#`&5dFjnp*r;yhpm2B*xvKZ|+D~?7%%Q?Mh2_<JC'
    '=ID_%5*NZir~Z?<47>){e&85<zNdG_{3GNy9ziZ>Sb{_+<zmpR9|1a4Z~<MOsyytSNMg_YDup)R3eu`og=8u6(@dl9a1IT}0j(YbmBMzs<VQn39$Ji68@Oy%'
    'Lxt5EK5r(5A7mV8G=}7L<DvbjoV}l=t`_dqw9f3ZTZt1hM>cqPvXY6KK;(!+giY_X(8ZAd!<y=X2Z|LOkmPWrFVD5y_|6OkV2}@@E}R43)+!#GNj!Iz2EV?J'
    'bz9!f#S;{zl_5Y`IxaEk1s-cNkW37&9<<!kY*wFsngW8*_#R9MsD;S_IED*CgG9{uQrBW-zjZ&*ev0hx*AJDCf;(J~0}~8nFyK!7e#ZC`7)~=j#_(u0g6iQv'
    'at(V9PP-CA>{fe9*fNi+6QxZh#ay&wdTo3t%SZsVMD#OYkT9J6J+ZK#fthi$+pIH4HCXf~7pl^jhu4vDb=0S9INO`#@eS(Q%wWp|RETJD=NAVMFm*ue7!z*S'
    '+TL>BPLI*i*aNCS<n7)Bp^yWXD}CJV1fkd&+Tkq{8*m5CzrrAT>qf8U8OD<p#kg-7$(;F*<MM(^u%p~XnkLL^?eT8at-)`GoTN`UPeB^{|HCZgnq6W7B%T~g'
    'hJ$<g72aWmBm~{lQn)a3f+`*u%K8&OkC=Yp(P2ED1P8X(s969%xEe`tVhY)YzPJ707S^I~=(lj39>ycLkN7xh=LOB@1cYODgHzPAEgpE{_hQ8dRJj=NFNYC!'
    'fy~aRlwCk%bKU{BybD~Hioe-)@8Gi8F?ANR_qLq>dDUb1E;P`WG{1F|Kcw1+`z3Yz_fkCb1)z*^KlyW2D*c^x{s4W98;S%T7Z_^{6*vfl3&|z?!E{`92L`XH'
    'H$GMFE62(uHBuB@eJ7v%hM#0A+5>rN#Hk|!-_-8Gb!US57VZtb(mn3ev-Kci4^m`Y$9A3<ML<OMs<7@T$e~|RDZC$DkK|lJmT(x0s!~(xJ@16CaAXU?PBRh2'
    'o$&>p_#<L?ZeoiQsQIbw?{Y9)=|A5!pl;cGcTk+PiZA^Iid=j^@K|Wk9>4U#R5_Y*=lmrG8Bme=gLMZx3}OAdkopU>B~ovEIZVEhLhnme>%u;*!LbHDKF^iA'
    'l~$j5s9@hVt`gw#?x|VZLTOYj?al$u$pmP|GhY`?Dy`~%Nh@PZw5>kk{Ir4c{!;oGH&W*1*Jf!RW4^bF4erxcURP5Wrj)$I(BM7Ua2CpL!Yt)C+SZBGVLs%j'
    'y+O&!b6_~%qvjl9%;#cpmnkW#)hEAMdE6hs$t861+D6EuAr}J~C!MqqMF8GGXCs}e{k+M#=)QDMAWuA|b3FSFxsK{}nIjc#hOtYUVuHU?;6B*4^WoPpWkG-+'
    '^wIbV$cQ5NVHTEg=)0;`ii;UN(H=@~y47Z?n6GOTjB&pUKB7`r)WjLOKJ;Gmbhep&V~A-cF$UQ4EU<wUT}|=q8(UpY)5;%Eu`$kCD4osq`5sq5`fFuP0L2yx'
    'B7CcE`rVwz$pq#n%_EX0auZD|7_V~&$b><-vK?9Hi7i%cV*shSs2Ewi;FK?kxcYmMM|t(3p3C$+lxhPW*t3r8s+s`lr?=Za9+E<VsVy(wH7veN4uDeQiL7O4'
    '1HS42O|-#>DUvc0o_Nf1)f_G{>2LGL^(rdOk_f(XLC^3|+fuz5e3cGPO_YsA0x~%A*u0Ilhm{YNmf|zMoS^>hrzfoXSUFaMNLs{>=HPC&=KdvkT<}O>f28}H'
    'lxZu9$ItPQGu)-W!Lf@<Co0{`Gm03_+#`9>{gIR7xc$AXZp^O~q%>Xv6<s4x>LLYk>$y#%GBI#0U47j3=R|BI_rtzg4&R+~0&G9GtG*t*xwr}5k)?&S{qz|#'
    'FRASTVEJ~NI4)09>i$62xk4<elX``oLBpyn-F<ct0BH)rX@1D4|07PC0=%OdE*_XQ*!Xa2(vWMuyU~?m+4J`_@+!coKLtJFES;U)$yWx;j!1m<HKt5RjFVoi'
    'vR9#Ae8=q08td$m5E}Ief`MOouFZetxH`@HhEjL#aswt;7&ujM^@j-NgZ#SFPra>O_A_Hg(FhH1Mpbd!(BKEn$Cq5d>|vJRm}Nc#MVvxT3X1Sk`XOYQmW8%8'
    'svbqBffQ%5RXWF}!VMg8h}n8rV$0d82}Y|*SdFv<PV*tUSuq=AAQhZ_!`l&@ikQ;EQDek0k6^c8OKCls-d`3w(ccHW+_Bvt3}4~}HM>TKDeZ+xYFnNAPhxl;'
    '!nxq8EH;I5Y?waw)1GXLYnfIkUWGf;fXLKi=2i20p8EQ~7HIdoHy(9qyZ?j>IL0W2bnE}mZhD}y2UTHs&ZacM%>9aXOpYB>y%ShuQ{L^1sG9kww&v|1z*Nf3'
    '1FX=>8aQU3FVyYJWYZ4L38~?lp0#YPB~WNvOVU|n#JmPL(pUMr*N8PU#uUv^Y=!hzBH9r?I;<}Juxl-uq~$=Ki4hCWX;{#=%8%R*Sj85-cSkDZFUUQp(bL^7'
    'Rd8<%o+&A1$P$<aJRI~<qaRoIF9-qN&ce;3C@_EJmK+h-sKIWAIaD{X7QToAlHW*rfcZvnu(9gm+{p5LMx7tOa)kj=C0byUpISPTDqR#AFKE(%kms;@kj+oi'
    'Z;V4yR%X!M5sm~JPT+l7bL?H;%ZY&($1Z#iZzBc*gMZ_V*W`cJN7z>nj_+GLS{<y*866TNdv>tjLxN~6D$6$ah{bJGjxkAimR>!UQic(PuGF@Zp8Z&;#L87*'
    'a!cX(8=}WKDsj8<g(Q*SYYjH6(gM`1Wn3o_l;Ltg9e5}m_Whdj8~v>ulkh%ag$GKC8d|uhkCSV?AHI_M;IUn)?NKwUiaDx=qVqn!!xbo`-R*+RhC*V)$uvCC'
    'M+RKfk)rixHzy@AybKpb>i>H$6sogC&Eq*ezyXVHFCJD_APH;48N6Px*>~st4~RT1w1axG6OycOj^b#Ax57HLt>r;zBnbHEA7PirIR9vGr1YZo+{fVVw$TBQ'
    '{)rn#B*%C}uO5K8W9(zqw%8-rh3*f&<0o-$1GHaNm29M5FkbYU;;70f_v~PCWZqr9NGe~PMGAbe5tR_yAhIssLSqJnh|zTm0h)<vB>q*4)d{9(VbR}(<M-yX'
    '!Z~lP?ogZVRGcegv5W6yh;9^w?A}g_4RJo*HNfU_MbE0-s+6WE!K^fAPK+6{gL0AN{K&LRc}8Tx8aiN}7!2#HLq6oR(>>*%%BbKEZ9q5wCtko;3kldsw8^Yi'
    'nUEl^@}U%zK_AaQR%2Dx!FnYQiaasPR~qV?soaE`Pl|Yi-nrtyH;!d+&AqsUQrAzYdRt%)ISjO+aOx2sge~dbdZtr6$1~@5gHXy|qxPe56s#IwMfo_N(YoNQ'
    '5O}J%@)^`X{d9^iGLqy#ad}<K;d2X%&p>XF3Z|=Uh`>;MCRQ8pC6eu=G5S*PE>>^g6Oz4DlWpoXhj^d6-iujcz(lY2=zAc2{U(5!it=SAtB6jD<I_Jy%M6+|'
    'TRI{Cc1Z~EqUKYey)vn5YeLJ|wi?O`HE)bE57zxgdSo}zDsiREDVg`U)wOG!(JZ}UpXOgYRBhuBC@5UR#V`|_K(C~W=yv%mk_`WXP4WggT>%u@;W4j|j9sWD'
    'EI(jQ8>zsCjT;*#=?&!FId$KFEz3LzSH_Y@r8}DlH<Hx_W&oNGMI(7ehZ>UIuG~oiHa`$a<>!MY!Zp5p&B}`;GdK&c{Nm)P#__RoEV|Emjxs=Usvx%RiXz>b'
    '2rBWqtzr}kRQTY8;x9VMs+X>+^P4<i-H4d_Wo;qScyr%6=Ua<1Li=*Tpz8cNg}`BG3eq0<uI`5AUMiQ`!MJWf;QWV>D9PwYww2O<NF`b&%(KbTWmAOKO--cn'
    'J6jMJ7)^t&`+o1kDs_OgKu3&2yD}psWXc$BhG;vCMW0F+m4E1Sd!K|762Cl`jDVh9Pw45ydDgkUt$HW!ems!-Ua(SUPv^45n8nPi&vPIGoqPR<2f?L~FL{@`'
    'nPbQ)hF_~~Ef6M5wQ7eqEf-=@t3LsW(NPW$^=i40XNLDZAK6pYzs|*Xc<C56A<``Iy3*h`TLesVIl7ksL+ku6@Oy0E;QFt<GY|i^<cO&!?rFP3vg(#MO=%Is'
    'KF^e&5QbSde$za+p%D_Sm%~5UNntzjG0V!o(!6hGb*kOT7U~|Yo>@sx%Q;eOguxQ9RH+qmtQ!)crJg(CL#??<7lDS&KqwUd4jpH+_kaOXguU*>IY0LaV4mOJ'
    'EDCtR0@I=X;Q;tg(l2np&XAqtjS^v&fw}<Ip)4ITwrH`y5{qBL>waLTi0R9z9*^tWMYPpFq;D@Dh*<Rocw;#Q)%+ThfsWhCwI_#yRX?X;4e#3UU{2T&?8Vf~'
    'I7YVA8{dLUz&ycnLd_KbI2j6w_fHb=WeO9II5%yrdv(D<j_P1ew8v#xU}$38L5D%#4Pf|)J9Ff@8yi5WM%R5J7w5w?xLQFI_8r+|JB&if4ljFY`7CVHj{mxg'
    '{_PHa%i}*y|8jS>t*3}nX68^;$=t&x41$p&fl_<4fJZ|F^H<Y6mS4!Zq1DW!{~uk2Y@PcZ>H{zrCeyZV1joDjv5`PWX+~aUD-0{ugVLtER1>t<A|Mv_6^fMg'
    'Vy6qKWN9sXk?g-`wkqYwB&t9#f|Na>${Fe1R$Ah(VHW5*GrM`=>m?)o8bjA!uQHr8W9onW7tGj3e_g)u|ACQvw}0_Xa|+U@T8mU2FbJkNDt-6XhZtWZ8FN_-'
    'Fj+~^Gv$FZa_@s1X;t3;D*SfHLEGa6GWMhYUh8z8x~yl2f`BQKBjoHAEU!>$d7C{7<w3ss#_=mFLeEEIKp*Uh$ZyR0Z<xkIIe@hS5njj*cV?y?BRBx&3PgRL'
    '8rZtGwhS?MowfnXwsj;E!;=2hUl>t51U-Rf#_Z+-H+;Ws)%G8z;|(<O@h{x@|FeV}-Fmf2>d(h-pr2*v`>&KC>lPI9^ZhZ#swceHZgrEZ6}DR+$Y^LU1!;20'
    'bV0r+O5|IFflT;2(Gg5B=J;c1w?3~+TxE}0a&#ZKj28<A@Xd)jW_2v@Oc9K9zaE#8OH{3i#Drt3@2$R=i`lndIS>qES!zwkgPB&HfL*oLfg=d0kK0PiAG>f7'
    '{cqh_p#s0h3VGHIpGT6}=lMX$aV?FbtRk2U6G!PV7-LC2pUAgEC5gnYPV<!0mP?6$1W|DWVXtwNblrKPt&rf?gOi;%6s_YB&Jih>HPm|P?XNp|h1mKNHmfT<'
    'n^e;iZyy(8D>fTNgSX2bJ)qn{{kHUbRh8%NCcqB1;VtIt^T=LA$b|{5QUH>Kj5%=4N0HU&dOjaN$Z>{=a%d?D_=9`2(|S*E(2d<R(mcYt9R@`JlvL+SZ?3U>'
    'X$gyBGv#tPn~amno+aJqOTf@s7t1uKIk`dl0<@uw`SAtzDV@i@uYnx#0(93yB&X3lX({!ty#ajD9*!{>lnHknW3k(rrWygOCSpB9gadFtfBm_>Rez)r95unK'
    'qlSOjIywFn!57xy4I-*~HrQ}u0f`0H4)ERz5}4ii*ZG7zKXp=0Gkom1&WXC@>4JkzlJ^qHqlT@h+6A(*XGWU#wwKJDanWD4p7ZVmM5N>?RoV(5S{6QCn9HHJ'
    '1E?qUST&ALz_S2_jXAB07nskR9Hw~?g|;^fg0%<wq9|jCNmcwh#`Io5P89G}F(Ed%;n<;p%(2n3sYdjCIEF<6^6b0ariHrNYPQ5_LJ&u6UJpGfQt%&jktUn#'
    'I8${<B7n2;(uqDDUB5~euz~atbiUmbs=+1m#!GDYA@R9p2wNFd$-)a%%14Xoc-~avfQ6Ozu@=5^8&Z;k>N+MX9oc0oan_(b-o0i*GawZ$3$QfU2f_Oq85heS'
    '6qsUm*uWs9hXnNuqu4S1vVB?G+yfZ19#Jn$91)B3=3`Qa&lQ%ebt+`fost<HYqxmv-zDnPd%=18k{B5*9y4wbXB3E1k(j16iU>(4$Vz0mNBZsSBm1lU18FgI'
    '-1c}UoLb&uH#V;XcnxV3UoRAcs+>fm%{Yn7<AzK+B_Fq&k9dMfCG6{Kv7kr~++NUD^(v}?*~~XS9co8+U_L`7wO1VECl?4v57k&WH5<HLMq~sC-4JyKeR~Z4'
    '5aNyO_y|4Qs9_pAZ~7#;nsp$RMi(f#)l?Zza?*1x#HG9+0LG`C@Nde|$p!swyC8&iw?<=9%kl4qDl7;lj`Vj9syWhaCfU^4-z5oXLvN}%Z$|nO()0U5`Z4{|'
    's~THUIdnx`#d=eC2SWFL-mgpKMT~JxSa_TmTbqeo0}4fPCP0t5T9dhhtX(S2(y0~cYJj;G^SoIU&p#>nCOP`rbt3D?L(+#EN9P(1xE3IQS8zmwUppglw>+K3'
    '|4H}v!&C6FBPG0DEGEY_Zq=kt^E`g`>#p*VLX#?yX1X?M)3P0#)@SsbqB(sLwLpg_f;rWt0#;kh&E{KwKS@oOYBCf+$#=wCfS@ROi=&A2|20wd-Iv}q6;{iR'
    'D4c&6ZwLrI8pn|E%um^(d;HrlSz9ggp;3Ai9Q_U$%&uD``jke~F8ScPQ?P>UW>ow~GW1_obp`e2BM5gZO*uDxKJxnOFKv4)wbt|8;YiW_QTithuvmQ3TM*r2'
    '+Y`k&6`=*jzu2`+v0d$44yZhI%lg*`RW+&I(hh_Yy=&*i&@r;vhKGhJ6h1tuS#J2-w3Y^yUG2hB$)txw=%?<M9E-uz8J)FjvY(o!J8};Hfwhb&-D-N~#{eRx'
    'apR{l5!;>~4W(Z<&0Rn{r8MZ$IWqRzSqK^<X+?xR<GIQBYB5y%9k=K7NyNo|G2NVuhSP#gQ`qo{!9C>~LQtbxGqaCI$hv=(_J_k5mp>qG%KH~_o8LNMbxkul'
    '7Miw$=2@XB;Af2Jx|Yy$>SMvz8Yq9@Oo&HDz(OsM{i=XZ>e{G;hSAa^T@SkBiGa?G#1++EUMvU{?GUSn6YYG(MUJrbuuxyZncsvTc)>aX)$tzZ=@|KV(bIlD'
    '$sT2FS(m&&s#IBczx<|&){6!<nk?Tia`|^?VV>CF;o4n3E@mDdTZ^Dd+}1aom^i}0u#kufs=-((opEihU=_!Id;2|*hXUqz@)MQwio*mQUf}_2sOR}(ysjnp'
    'JOJ>MI-siIE*-ujMUn;eT^1vQeg{^B*amnfNRYNMG=XgUb*R6mPP6mBy#w4?P*PSpWq`sy4pPxm`F1&G98Tnjvq9uylqJp=anNGwu_K&CoeS>aM~dOzh^LVP'
    'QGt5I!1g0umG<?gQldri8;_te^&rk0sQP*OLzw|~jz@xqMNjJ_5b(pN&0_VzxskK7>pE7N_S)E~MDXy#O?fHQp7%jK<WZHE9AO?Mzu~$j?$>IyhCz=)HSk_P'
    'g;L!j_Dj`s8j7#Slh{FrHq1UK?67An;=Ni3|N0*+sK-Q4%nklGnR}lr6ejDKbZ$XBTCSh;R!K|He8;H8g?b3a+<d1{3fzTQ;|g<=K|AxDkTXx3<DkQm>4>x_'
    '{({lHYfVa!o!)VJu`Fv@eyNzhdQcAGd({$S_A5idVj7^+z)5e}+4+dSMoiY<VF6Q2$4=p9dPY_kZf~4oswD;sQdYjdW{|6A{CQ2VT_2&tDn;X6({S5LH`7&-'
    'z$VYYO`)Gx3bbW!aHXysOe|KZt`do4By3-eOqX06)L_`(TYUmD<y!m}0GydWa<?NKUTEex|CzMiEtjhNl$}7tDy!A;q1<uOVNHGGpKq#3VA#S1yj_!Tl+u9L'
    'r6wEe3bRv~xkNTpVxe@3yDLX<#P%-8?R12EOYq7Ox*{V65*01ydc&8f)8WPKzG4eYZ0T@ZE&xPzepJ1$AnR=CTFDXBLTRhR=}_dq)-J}`Y*+}>kWjc5%F+y$'
    'OryQlXoGWvg}B`IEVRictJo1e0sGMEt^XZ>ctg6=qvaKNT?Z_JJ95K3jmAN`y95bH+03D(yv+$o>=DyArk?l(+gIwWl3=2^H&Y`wCsh+~cG3<_gvX`f$zewh'
    'Vup#Y3@+{Q6UmYS#0VViKJ4aT3brILlT(gRv2e%dG0Dt{ZeybypK>G%2_8-WF~uiVGGrhr$YXCINl|PeiaxJ$vuMEzqZq_*0Pfbp(Xpci(DHQi1bXz0*+Nu6'
    'ne|KA13VvTVdA7hM*(=f=WiVPgt>wyH#hu@_+G~2#XcA>BL3ugmz#DgS{k%IKMlqB4|{ZbD?Y6WPuf>Vczevpm9teIq2MP|IGb6}=RC`~hnD%vgaQom$QxDB'
    's|xoFRu>KPJPLtXD@#)6_JPsw^8NJxZtGLE*|cAfohn}RvVgo3ep&`D*e-EQYkuKK!dKdBeKG3GwK5S&;(F`Wj&cyCX(7+*xgx%t{h^FIW>(R~#aflr>#8fk'
    ';fh>tq2D`Ew}9|LyA^52j@NZ|p&$=CdU(A_Y3qCPAU$!<vnD$}(y=6miV^8!aWGU0VoU&|7(*)jA|8#0AkL(qBU)C+U<InHu-t~nXG63^=By=*{+`*~^5Z!<'
    '@rsp8j=S@FPVQ>A=qr0%vsi4p38x^B_`6`r(VlHHL1=3JTJ_d6F<wA@?iP-HLUt|eQn%G8OBH~Ljt%vx&NI@(B-jtaug9p28#(AJ8|^hoMZk}5V=}D(u9#p>'
    'XxGTm2sV@|Ho52-hfP8hg21t!4=SL|tr%I*3}hSn?$O0&!6K}yJ{pYNb#C>IqZH8oxjXPbaVXqM_*3r&ULWifZjU9<;>|(r<iBR3^4%m`wD<HBE7SZW(z|lA'
    '3Ii_pKBxf14Q-C|FopM5SOPTp^my@tup_bK?gxiX?9xa;7Pm*y#B;7;fU5DPkGghlg;I=|a!3;Y4)7|JPLhWKX+E{hIl8FTR>7>N*eSfPVX#BFhXifoEC2Xq'
    'Hcn>o%Nb8A>kfd47uOrkoI4vD!*sl6gzcsSC+|pqK949*6bt>AvC<M@BU?cYs$QOok}x~~Jb^aOHH)K@6KJJl-1O+!!RO)5a!eOu!3UvJ^Gsz97K&@r5Izl$'
    'r7XBID{vd|R!viCsv`z;Fvvkvekg?wc<EUi5X8=XF)<C^A;WK67J-BIGEj=4WP0S|ESri{?mI4N<K#sltRZqba9(4Go9uTlqYd8xJLec>M`0%`p!|D`=Aa96'
    'Q?1tGl2@)nq0Kc^VlX4y(s8WO>}-I8Qy7QcZziXQFJ@~yZJF5|RA*u7Y&2f}s8$5DTKIG$tGQMi@D*^HQ3PM`I=wLg{zZ_~X8Y14A{fwH#FRRgTsMB#0$M+J'
    '_wJ_(RAF63vesdg@D+0Hfaay%PuI}+H8NpVPpi;><eA~7!T-O^JV?+~eyOj5Nn}{>K2=z&W1<quq6wVIY9clJ2yT!6Zpk#><Uw4#M{>n>hrNQ;MS{@S&<5!)'
    '1Ej3$|K%kNq7-zAM7=fb@lKE30~x7mfVO4#KeGB#BElq1j0AacVCm-QshT$6#IJp|=6oMPB+W_n!Zf)oapF7D62uMThLE4ky|jz2=jx5<XZxHj^W`4e&YDF~'
    'RC9dgzc{LQoK?ob^O%J&1zRjswsb3u_3@q{plDv{RJ9x<Mdzp#dXVs~DLsrNj0Q%}{C3jE7K^k={X&@=)MW?Ri{{zF{N`o_H~OjQnX9J*r!`kPEg4P!4sQf<'
    'iNmtGwV9H~8PPo4v`%zeDyuKL778D_9J}MmxT5Vth#NnzGxb%%wM(c4hYm7>HT(bcNea|mpfkVJo9KY%MDe8ex#vB6MqtSWE8#n-?^4go_oZg{47`nJr+AK5'
    'N#EDB#0lbM%B?_a0-&Jh6ycv{<6ZZ9`{&N*XD+mIPt9~TxFgqlW~6Qxs3VK^uCNHhOXFC38onn4nkqT9+8aa!9(!-RPrnzvfEWTV)!X@%{bbvdB|16uRQ#SN'
    'd4Yq;G+dIg!5Vff3!>#&7ro-$<|dl<&{NK{u0W!$;j-wbTO?YuBHM*_UPi|w2oQQ?eRSlBotB3bgb1J|mMEZY$v-UiJds*?iX+g-w+bRA-y=7-=N^470Dt(E'
    '(!;lWOqHVqW5DC(KxjVVr>C^BzXKOlPXwXV`#96Wzax|})O%aUBL<nNUFHZs1wBOfYa53F(&iG|V}<(Q5aIatG=UZ(n_5eJBCSiDL!@zV^=xaejBNmV2YJU{'
    '#%Skx!Ii>;5R;!0aq}QAKVjiw{~##dQ2g1k2^S1VA1?ScaSRiTXIn3+Zs#t3*7+8~4Sx5)hMf}<z6#<<YxD<34*z}4<kXU7h@GLpHWGANA`S-I%YwxH2>d96'
    'R2&=^)RqICku>Ki?sRoPsccaH;J7{p=ibq6ub+o2#3)vveQj&{=KghZ-?|ZKg@y~$Ew&J|Jy{!QiQ_lLA9260gdf57VRSM0#+6P*#wc7AfJbEHa(i<M7pfY)'
    'guwLk{?r`@`reon-}<`><e=g+U0jvc(<ZexC;cgJ8bl2|>Aiy<IV@cRPN9Kstfm4ck#m0)iLH0_q8?K+Bk^aXDl6!=Y@`~A@VX^mwB(zF;SqqYI0uvc&|4RM'
    'jgvR)d7TLa!?kdX#@eS5tdYBys9+=^jT<4w67uI$JdrI%xf&Mhra9WjA|JAG#i@KxlWJT^5`q0*@G897AzdtD)h6w1L1_2`@jKp@LwU8)G8XDZuEtLtgZB*B'
    '*oQxFM|ie+hNsGP$yQ0%Ooii9@xj1vlE~6*9!5zeI8xL6x&ffqYMj1B|8D<L(9^?DVF6%BJcy}enVXC#BvxR2S5nGxJ<GkW{!@DMZr2n$t5M`dHokMHtQJsk'
    'whnIg!Jqi%`32Djq|e6?GS@<w5<-6?lc*@KWK2hk)RgKQun`@oS2_5=_Zy;|p5xcR2<fp>5e17QvNZfb$^WR9^qU@bYNio(8Yxfi-tWP_1{{z7vxnFX2#Qr!'
    'L;@rw--s)bGRan7csu$rIPF)!L51~!cB4veb7{rB^Dt<C;&Q@4#&l+LKf8!EJK)=LAP>EnKh=-vcgw<>9Seo}P(lEI!$|~#^$VN`J5qD<MYvc{HG;!<>#Q<r'
    'va=Dd-w0?g$+@%eq0e++ZXu05lWQD~;RZanIJ(Z%B1Ur7h?qi$;5<n&hFs6%Ek1*>d-rFcuD^*fN?Qgg3g6l;ku+ONxIa!*1VBn&xVr9;l50gr5}1P-ZmL~g'
    'j>quDJNeAiL|uEMzhp&x<zTW=x*N1)i(=6;84VI-0`T94h^k=4UlrJMZ1}QY$TwO!g2`w|Z=VgW5n4?j!OWT1+LIfv^eB`Lcc(<6U<YDzkSufQF~U@|+Df~M'
    'B5h0uQk@RG-`L`d1!o5vqCvXLcmo>pHR_4MU)y^Z&rh*h#KP`JPB=t-X5i2hJB7mh@GflSW%jCVCpsAc)WO6<zhkw@0oiRDeZDi#@el@~9{?GyVR&OE7kg10'
    '!oSX{8(k(a6#>=J#BdqFrm?v#<y?X*LYCkeJL6^$sG9t%Z{Ve;kbSMfsfITq#^+bkt%8&CIlQ-48{J)~;|96;Q9hC95;`p<`69mkf)S+PQO7&`Zfw0z#3(0Z'
    'gXP=$lJn316fTrDJd`39N8NCEU86oc1wUWfKvo8{OO+RgI&L-UVc}U+?ucc9ZD~!*PUa;tw&S3SHm6$f*`KqYp+WJW`ogrej~JIyy7w31Wy+#byT%n4U+Jz`'
    'zJ4zgCIPD!#3wr|+h)vpRb?!e3`2Y!H%*EL^yUz>j|YY;kO2fLK#;DZMd9?$_`qoL{7356o4xjQA!c%Vylbb@(St0K!Md0jH+5ahH_)sgdemnsDMOv&#yJ&E'
    '<40F=)itrg$$|)UgZ7K>Tq|9D+&}C4y(fej5F%Q}rMq1p;YAQ%EMFbn5)^JEJ#)`*%uGWud63cv1ujeoAa$-DSZK0b-9E4JepierVbgkO%C`hT>wVR~M6ZK;'
    'FWPAHyN9)NQ|OYo#n|9fZ&F&9Fgt;$OyFr5!tv0BHvSGb&eL@@``F{#Lw@Hlga^~eG=P{z35`eHmRGOAb_?J$DGD62gJy%5{72r_{If#m%@V2aA3cWrioVCo'
    'yDurKX9?}g)e1EOd*n~8Vp8&L)ps4}?sgz$rFo{_$qeb5uQT`HRS%Y?t_&0G7|mzbgbfh7wzkKip|4R|KH^~Ax0rI7Y~Rr{V1e<K%JbI(1N|7Cm&s#MiT(3)'
    'APTA!6xW*00q=0N$uqgnZkNsgRh9%bPx67x00FR8zLNz2hBiYHvBYQl0ssI200dcD'
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
    if USE_LOCAL_ARTIFACTS and path.exists():
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
    errors: dict[str, str] = {}
    fallbacks: dict[str, str] = {}
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
    panel.attrs["errors"] = errors
    panel.attrs["fallbacks"] = fallbacks
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
    threshold = float(amount.get("threshold"))
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
        series_name = str(amount.get("series") or "")
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
    abs_day = signal.get("abs_mom_day")
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
    abs_day = signal.get("abs_mom_day")
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

    deadband = target_vol.get("deadband")
    if deadband not in (None, "") and prev_scale > 1e-12:
        if abs(raw / prev_scale - 1.0) < float(deadband):
            scale = prev_scale
            suppressed = 1.0
    return raw, scale, suppressed


def _online_gate_and_multiplier(
    idx: pd.Timestamp,
    row: dict,
    prev_row: pd.Series,
    meta: dict,
    signal_frame: pd.DataFrame,
) -> float:
    multiplier = 1.0

    nav = meta.get("nav_defense", {}) if isinstance(meta.get("nav_defense", {}), dict) else {}
    if nav.get("enabled"):
        nav_col = next((col for col in ("base_nav", "nav_decay_nav", "nav") if col in row and math.isfinite(float(row[col]))), None)
        if nav_col is None:
            nav_col = next((col for col in ("base_nav", "nav_decay_nav", "nav") if col in prev_row.index and pd.notna(prev_row[col])), None)
        nav_value = float(row.get(nav_col, prev_row.get(nav_col, math.nan))) if nav_col else math.nan
        if math.isfinite(nav_value):
            prior = pd.to_numeric(signal_frame.get(nav_col, pd.Series(dtype=float)), errors="coerce")
            historical = pd.to_numeric(prev_row.to_frame().T.get(nav_col, pd.Series(dtype=float)), errors="coerce")
            high_candidates = [nav_value]
            if nav_col in prev_row.index and pd.notna(prev_row[nav_col]):
                high_candidates.append(float(prev_row[nav_col]))
            if not prior.dropna().empty:
                high_candidates.append(float(prior.dropna().max()))
            if not historical.dropna().empty:
                high_candidates.append(float(historical.dropna().max()))
            high = max(high_candidates)
            dd = nav_value / high - 1.0 if high > 0 else math.nan
            gate = math.isfinite(dd) and dd <= -float(nav.get("threshold") or 0.0)
        else:
            gate = False
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

    scorehot = meta.get("score_overheat", {}) if isinstance(meta.get("score_overheat", {}), dict) else {}
    if scorehot.get("enabled"):
        score_value = float(row.get("score", math.nan))
        gate = math.isfinite(score_value) and score_value >= float(scorehot.get("threshold") or math.inf)
        row["scorehot_gate"] = 1.0 if gate else 0.0
        row["scorehot_indicator"] = score_value
        row["scorehot_scale"] = _scale_from_section(scorehot)
        if gate:
            multiplier *= _scale_from_section(scorehot)

    decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
    if decay.get("enabled"):
        row["decay_gate"] = 0.0
        row["decay_scale"] = 1.0

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
    cost_rate = float((meta.get("cost_model", {}) or {}).get("one_way_cost_bps", 0.0)) / 10000.0
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

    multiplier = _online_gate_and_multiplier(idx, row, prev_row, meta, signal_frame)
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
        target_vol = meta.get("target_vol", {}) if isinstance(meta.get("target_vol", {}), dict) else {}
        tv_window = int(target_vol.get("target_vol_window") or 20)
        vol_series = spread.pct_change().rolling(tv_window).std(ddof=0) * math.sqrt(ANNUAL_DAYS)
        valid_index = signal_frame.loc[spread.notna()].index
        tail_index = list(valid_index if full_history else valid_index[-2:])
        rows: list[tuple[pd.Timestamp, dict]] = []
        prev_exposure = 0.0
        prev_nav = 1.0
        cost_rate = float((meta.get("cost_model", {}) or {}).get("one_way_cost_bps", 0.0)) / 10000.0
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
    if USE_LOCAL_ARTIFACTS:
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
    if USE_LOCAL_ARTIFACTS:
        try:
            curves = load_strategy_curves()
        except Exception:
            curves = {}
    panel, online_meta = _fetch_online_price_panel(include_realtime=False)
    if curves and all(not frame.empty for frame in curves.values()):
        curves = _extend_curves_with_online_prices(curves, metas, panel)
        data_mode = "local_artifacts_plus_online"
    else:
        curves = _build_curves_from_online_prices(metas, panel, full_history=True)
        data_mode = "online_rebuild_full"
    online = {**online_meta, "ok": True, "error": None, "data_mode": data_mode}
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
    combos["three_pair_equal_weight"] = total
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
        order.append(("three_pair_equal_weight", f"{len(PAIR_DEFS)}组再等权总组合"))
        shared_index = curves_to_report["three_pair_equal_weight"].index
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
        ("成交额/成交量", ("amount_gate", "volume_on", "volume_gate")),
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



def _safe_float(value: object, default: float = math.nan) -> float:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


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
    for key in ("scale", "derisk_scale"):
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
            return section
    return {}


def _has_amount_sensitive_overlay(meta: dict) -> bool:
    return bool(_amount_overlay_section(meta))


def _nav_drawdown_value(curve: pd.DataFrame) -> tuple[float, str]:
    if curve.empty:
        return math.nan, "nav"
    nav_col = next((col for col in ("pre_overlay_nav", "pre_nav_defense_nav", "base_nav", "nav_decay_nav", "nav") if col in curve.columns), None)
    if nav_col is None:
        return math.nan, "nav"
    nav = pd.to_numeric(curve[nav_col], errors="coerce").dropna()
    if nav.empty:
        return math.nan, nav_col
    high = float(nav.cummax().iloc[-1])
    last = float(nav.iloc[-1])
    if high <= 0:
        return math.nan, nav_col
    return last / high - 1.0, nav_col



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
        abs_day = signal.get("abs_mom_day")
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
        if tv.get("deadband") not in (None, ""):
            deadband_status = "触发" if math.isfinite(suppressed) and suppressed > 0 else "未触发"
            parts.append(f"deadband {pct(tv.get('deadband'), 1)} {deadband_status}")
        if tv.get("gate") not in (None, ""):
            parts.append(f"gate {pct(tv.get('gate'), 1)}")
        rows.append(("目标波动", _detail_join(parts)))

    nav = meta.get("nav_defense", {}) if isinstance(meta.get("nav_defense", {}), dict) else {}
    if nav.get("enabled"):
        gate = _first_numeric(row, ("nav_defense_gate", "base_nav_defense_gate", "nav_on"))
        dd_value, nav_col = _nav_drawdown_value(curve)
        scale = _scale_from_section(nav)
        threshold_value = _safe_float(nav.get("threshold"))
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
            _gate_text(gate),
            f"回撤 {pct(dd_value)} / 条件 ≤ -{_pct_abs_threshold(nav.get('threshold'))}",
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
        gate = _first_numeric(row, ("scorehot_gate",))
        current = _first_numeric(row, ("scorehot_indicator", "score"))
        scale = _scale_from_section(scorehot)
        rows.append((
            "Score过热",
            _detail_join([
                _gate_text(gate),
                f"Score {num(current, 3)} / 条件 ≥ {num(scorehot.get('threshold'), 3)}",
                _effect_text(gate, scale),
            ]),
        ))

    decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
    if decay.get("enabled"):
        gate = _first_numeric(row, ("decay_gate", "base_decay_gate", "decay_on"))
        current = _first_numeric(row, ("decay_ratio_signal_day", "decay_indicator"))
        scale = _scale_from_section(decay)
        rows.append((
            "动量衰减",
            _detail_join([
                _gate_text(gate),
                f"当前 {num(current, 3)}",
                f"衰减 {num(decay.get('decay_threshold'), 3)} / 恢复 {num(decay.get('recovery_threshold'), 3)}",
                _effect_text(gate, scale),
            ]),
        ))

    amount = _amount_overlay_section(meta)
    if amount:
        gate = _first_numeric(row, ("amount_gate",))
        current = _first_numeric(row, ("amount_ma_ratio", "amount_indicator", "amount_ratio_zz1000_hs300", "amount_ratio_cyb_hs300", "amount_ratio_zz1000_sz50", "amount_ratio_cyb_sz50"))
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
                    f"值 {num(current, 3)} / 条件 {op} {num(amount.get('threshold'), 3)}",
                    f"w{amount.get('window')} / d{_confirm_days(amount)}",
                    _effect_text(gate, scale),
                ]),
            ))
        else:
            rows.append((
                "成交额叠加",
                _detail_join([
                    _gate_text(gate),
                    f"值 {num(current, 3)} / 条件 {op} {num(amount.get('threshold'), 3)}",
                    f"w{amount.get('window')} / d{_confirm_days(amount)}",
                    _effect_text(gate, scale),
                ]),
            ))

    volume = meta.get("volume_overlay", {}) if isinstance(meta.get("volume_overlay", {}), dict) else {}
    if volume.get("enabled"):
        gate = _first_numeric(row, ("volume_on", "volume_gate"))
        current = _first_numeric(row, ("volume_indicator", "volume_ma_ratio"))
        scale = _scale_from_section(volume)
        family = str(volume.get("family") or "")
        op = "≤" if "low" in family else "≥"
        rows.append((
            "成交量叠加",
            _detail_join([
                _gate_text(gate),
                f"值 {num(current, 3)} / 条件 {op} {num(volume.get('threshold'), 3)}",
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
        ("amount_gate", meta.get("amount_overheat", {}), "scale"),
    ]
    for col, section, key in gate_specs:
        if col == "amount_gate" and (not isinstance(section, dict) or not section.get("enabled")):
            continue
        if col == "amount_gate" and amount_gate_override is not None:
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
    prev_row = confirmed_curve.iloc[-2] if len(confirmed_curve) >= 2 else row
    probe: Optional[dict[str, object]] = None
    if live and isinstance(online, dict):
        candidate = online.get("probes", {}).get(config.key)  # type: ignore[assignment]
        if isinstance(candidate, dict):
            probe = candidate

    sample_end = confirmed_curve.index[-1].strftime("%Y-%m-%d")
    sample_start = confirmed_curve.index[0].strftime("%Y-%m-%d")
    prev_date = confirmed_curve.index[-2].strftime("%Y-%m-%d") if len(confirmed_curve) >= 2 else sample_end
    exposure = _safe_float(row.get("gross_exposure", row.get("net_exposure", 0.0)), 0.0)
    prev_exposure = _safe_float(prev_row.get("gross_exposure", prev_row.get("net_exposure", 0.0)), 0.0)
    signal_value = _extract_signal_for_row(row, probe)
    score = _extract_score_for_row(row, probe)
    target_signal = _to_binary_signal(signal_value)
    base_signal_exposure = 1.0 if target_signal == 1 else 0.0 if target_signal == 0 else math.nan

    tv = meta.get("target_vol", {}) if isinstance(meta.get("target_vol", {}), dict) else {}
    tv_scale = _first_numeric(row, ("target_vol_scale", "base_target_vol_scale"))
    if not math.isfinite(tv_scale) and not tv.get("enabled"):
        tv_scale = 1.0
    base_after_tv = _first_numeric(row, ("base_gross_exposure", "target_exposure", "pre_overlay_exposure"))
    if not math.isfinite(base_after_tv) and math.isfinite(base_signal_exposure) and math.isfinite(tv_scale):
        base_after_tv = base_signal_exposure * tv_scale
    amount_gate_override = _amount_gate_override_from_probe(probe)
    overlay_multiplier = math.nan
    if math.isfinite(base_after_tv) and abs(base_after_tv) > 1e-12:
        overlay_multiplier = exposure / base_after_tv
    if not math.isfinite(overlay_multiplier):
        overlay_multiplier = _current_overlay_multiplier(row, meta, amount_gate_override)
    if not math.isfinite(overlay_multiplier):
        overlay_multiplier = math.nan

    if target_signal is None:
        formula = "N/A"
    elif math.isfinite(tv_scale) and math.isfinite(overlay_multiplier):
        formula = f"{pct(base_signal_exposure, 1)} × TV {num(tv_scale, 3)} × 叠加 {num(overlay_multiplier, 3)} = {pct(exposure, 1)}"
    elif math.isfinite(tv_scale):
        formula = f"{pct(base_signal_exposure, 1)} × TV {num(tv_scale, 3)} × 叠加 N/A = {pct(exposure, 1)}"
    else:
        formula = f"基础 {pct(base_signal_exposure, 1)}；执行 {pct(exposure, 1)}"

    tv_text = "未启用"
    if tv.get("enabled"):
        tv_text = f"scale {num(tv_scale, 3)}"
        raw_scale = _first_numeric(row, ("target_vol_raw_scale", "base_target_vol_raw_scale"))
        if math.isfinite(raw_scale):
            tv_text += f"；raw {num(raw_scale, 3)}"
        suppressed = _first_numeric(row, ("target_vol_deadband_suppressed", "base_target_vol_deadband_suppressed"))
        if tv.get("deadband") not in (None, ""):
            tv_text += f"；deadband {'触发' if math.isfinite(suppressed) and suppressed > 0 else '未触发'}"

    detail_rows = _overlay_detail_rows(confirmed_curve, row, meta, probe=probe, live=live)
    detail_lines = [f"{name}：{detail}" for name, detail in detail_rows]
    return {
        "direction": config.direction_en,
        "sample": f"**{sample_end}**；样本 {sample_start} 至 {sample_end}，{len(confirmed_curve)}行",
        "target_score": f"target: **{target_signal if target_signal is not None else 'N/A'}**；Score: {num(float(score), 3) if pd.notna(score) else 'N/A'}",
        "exposure": f"前一日（{prev_date}）**{pct(prev_exposure, 1)}**；最新（{sample_end}）**{pct(exposure, 1)}**",
        "basic_exec": f"基础：**{_status_from_exposure(base_signal_exposure) if target_signal is not None else 'N/A'}**；执行：**{_status_from_exposure(exposure)}**",
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
    if tv.get("deadband") not in (None, ""):
        parts.append(f"deadband={_format_meta_value(tv.get('deadband'))}")
    if tv.get("gate") not in (None, ""):
        parts.append(f"gate={_format_meta_value(tv.get('gate'))}")
    return ", ".join(parts)


def _section_meta_detail(section: dict) -> str:
    if not isinstance(section, dict) or not section:
        return "enabled=False"
    keys = ("enabled", "family", "kind", "series", "window", "threshold", "target_vol", "confirm_days", "scale", "min_scale")
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
            volume = meta.get("volume_overlay", {}) if isinstance(meta.get("volume_overlay", {}), dict) else {}
            vol = _vol_overlay_section(meta)
            scorehot = meta.get("score_overheat", {}) if isinstance(meta.get("score_overheat", {}), dict) else {}
            decay = meta.get("momentum_decay", {}) if isinstance(meta.get("momentum_decay", {}), dict) else {}
            snapshots.append({
                "signal": f"bias_ma={signal.get('bias_ma')}, mom_day={signal.get('mom_day')}, weight_end={signal.get('weight_end')}, score_threshold={signal.get('score_threshold')}, abs_mom_day={signal.get('abs_mom_day')}, abs_threshold={signal.get('abs_threshold')}",
                "target-vol": _target_vol_detail(tv),
                "NAV-defense": _section_meta_detail(nav),
                "vol-overlay": _section_meta_detail(vol),
                "score-overheat": _section_meta_detail(scorehot),
                "momentum-decay": _section_meta_detail(decay),
                "amount-overlay": _section_meta_detail(amount),
                "volume-overlay": _section_meta_detail(volume),
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

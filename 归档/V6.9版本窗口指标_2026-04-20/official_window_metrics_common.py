import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd


def load_module(path: Path, module_name: str):
    poe_stub = types.SimpleNamespace(
        BotError=Exception,
        default_chat="",
        query=types.SimpleNamespace(text="", attachments=[]),
        update_settings=lambda *args, **kwargs: None,
        start_message=lambda: None,
        call=lambda *args, **kwargs: None,
    )

    poe_mod = types.ModuleType("fastapi_poe")
    poe_mod.BotError = Exception
    poe_mod.default_chat = ""
    poe_mod.query = poe_stub.query
    poe_mod.update_settings = poe_stub.update_settings
    poe_mod.start_message = poe_stub.start_message
    poe_mod.call = poe_stub.call

    poe_types_stub = types.ModuleType("fastapi_poe.types")
    poe_types_stub.SettingsResponse = dict

    old_poe = sys.modules.get("fastapi_poe")
    old_types = sys.modules.get("fastapi_poe.types")
    sys.modules["fastapi_poe"] = poe_mod
    sys.modules["fastapi_poe.types"] = poe_types_stub
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"failed to load module spec: {path}")
        mod = importlib.util.module_from_spec(spec)
        mod.poe = poe_stub
        spec.loader.exec_module(mod)
    finally:
        if old_poe is None:
            sys.modules.pop("fastapi_poe", None)
        else:
            sys.modules["fastapi_poe"] = old_poe
        if old_types is None:
            sys.modules.pop("fastapi_poe.types", None)
        else:
            sys.modules["fastapi_poe.types"] = old_types
    return mod


class _SilentMessage:
    def write(self, *_args, **_kwargs):
        return None


def fetch_formal_strategy_inputs(mod, class_name: str):
    bot = getattr(mod, class_name)()
    cn_close, cn_dk, us_rot_close, us_prod_daily = bot._fetch_data(_SilentMessage(), include_us_live_snapshot=False)
    return bot, cn_close, cn_dk, us_rot_close, us_prod_daily


def run_strategy_outputs(mod, class_name: str, cn_csv: Path | None = None, us_csv: Path | None = None):
    bot, cn_close, cn_dk, us_rot_close, us_prod_daily = fetch_formal_strategy_inputs(mod, class_name)
    cn_result, dk_result, us_rot_result, _, prod_sig_a, prod_sig_b, _, _ = bot._run_strategies(
        cn_close.copy(),
        cn_dk.copy(),
        us_rot_close.copy(),
        us_prod_daily.copy(),
    )
    subc_daily = mod._get_subc_daily_ret(us_prod_daily.copy(), prod_sig_a, prod_sig_b=prod_sig_b)
    return cn_result, dk_result, us_rot_result, subc_daily


def combo_window_metrics(mod, cn_result, dk_result, us_rot_result, subc_daily, start_date: pd.Timestamp, end_date: pd.Timestamp):
    cn_period = cn_result["return"][(cn_result["return"].index >= start_date) & (cn_result["return"].index <= end_date)]
    dk_period = dk_result["return"][(dk_result["return"].index >= start_date) & (dk_result["return"].index <= end_date)]
    us_period = us_rot_result["return"][(us_rot_result.index >= start_date) & (us_rot_result.index <= end_date)]
    subc_period = subc_daily[(subc_daily.index >= start_date) & (subc_daily.index <= end_date)]

    nav_series = {}
    if len(cn_period) > 1:
        nav = (1 + cn_period).cumprod()
        nav_series["Sub-A"] = nav / nav.iloc[0]
    if len(dk_period) > 1:
        nav = (1 + dk_period).cumprod()
        nav_series["Sub-A-DK"] = nav / nav.iloc[0]
    if len(us_period) > 1:
        nav = (1 + us_period).cumprod()
        nav_series["Sub-B"] = nav / nav.iloc[0]
    if len(subc_period) > 1:
        nav = (1 + subc_period).cumprod()
        nav_series["Sub-C"] = nav / nav.iloc[0]
    if len(nav_series) < 2:
        raise RuntimeError(f"insufficient sleeves in {start_date.date()} -> {end_date.date()}")

    all_dates = sorted(set().union(*(series.index for series in nav_series.values())))
    nav_df = pd.DataFrame(
        {name: series.reindex(pd.DatetimeIndex(all_dates)).ffill() for name, series in nav_series.items()}
    )
    weight_df = nav_df.notna().astype(float)
    for col in weight_df.columns:
        weight_df[col] *= mod.COMBINED_WEIGHTS.get(col, 0.0)
    weight_sum = weight_df.sum(axis=1).replace(0, np.nan)
    weight_df = weight_df.div(weight_sum, axis=0)
    nav_comb = (nav_df.fillna(0.0) * weight_df).sum(axis=1)
    nav_comb = nav_comb / nav_comb.iloc[0]

    total_return = (nav_comb.iloc[-1] - 1) * 100
    max_dd = ((nav_comb - nav_comb.cummax()) / nav_comb.cummax()).min() * 100
    n_days = (nav_comb.index[-1] - nav_comb.index[0]).days
    annual = ((nav_comb.iloc[-1]) ** (365.25 / n_days) - 1) * 100 if n_days > 0 else None
    return {
        "annual": annual,
        "max_dd": max_dd,
        "total_return": total_return,
        "actual_start": nav_comb.index[0],
        "actual_end": nav_comb.index[-1],
    }

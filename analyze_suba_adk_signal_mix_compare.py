import builtins
import importlib.util
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "mnt_bot V 7.1 plus.py"
OUT_DIR = ROOT / "docs" / "suba_adk_signal_mix_compare_20260425"

A_BASELINE = ("baseline_60_20_20", ((60, 20, 20),))
A_CANDIDATES = [
    ("mix_40_10__60_20__120_40", ((40, 10, 10), (60, 20, 20), (120, 40, 40))),
    ("mix_45_15__60_20__90_30", ((45, 15, 15), (60, 20, 20), (90, 30, 30))),
    ("mix_50_15__60_20__70_25", ((50, 15, 15), (60, 20, 20), (70, 25, 25))),
    ("mix_55_15__60_20__80_25", ((55, 15, 15), (60, 20, 20), (80, 25, 25))),
    ("mix_60_20__90_30__120_40", ((60, 20, 20), (90, 30, 30), (120, 40, 40))),
]

DK_BASELINE = ("baseline_60_20", ((60, 20),))
DK_CANDIDATES = [
    ("mix2_60_20__50_18", ((60, 20), (50, 18))),
    ("mix2_60_20__50_20", ((60, 20), (50, 20))),
    ("mix2_60_20__50_22", ((60, 20), (50, 22))),
    ("mix2_60_20__55_18", ((60, 20), (55, 18))),
    ("mix2_60_20__55_20", ((60, 20), (55, 20))),
    ("mix2_60_20__55_22", ((60, 20), (55, 22))),
    ("mix2_60_20__60_18", ((60, 20), (60, 18))),
    ("mix2_60_20__60_22", ((60, 20), (60, 22))),
    ("mix2_60_20__65_18", ((60, 20), (65, 18))),
    ("mix2_60_20__65_20", ((60, 20), (65, 20))),
    ("mix2_60_20__65_22", ((60, 20), (65, 22))),
    ("mix2_60_20__70_20", ((60, 20), (70, 20))),
    ("mix2_60_20__70_22", ((60, 20), (70, 22))),
    ("mix2_60_20__70_25", ((60, 20), (70, 25))),
    ("mix2_60_20__80_25", ((60, 20), (80, 25))),
    ("mix2_60_20__80_30", ((60, 20), (80, 30))),
]

SEGMENTS = [
    ("last_3y", "2023-04-25", "2026-04-24"),
    ("last_5y", "2021-04-23", "2026-04-24"),
    ("last_10y", "2016-04-25", "2026-04-24"),
    ("full_common", None, None),
]


class _PoeStub:
    query = None
    default_chat = []

    class BotError(Exception):
        pass

    def update_settings(self, settings):
        self.settings = settings


@dataclass
class MixContext:
    mod: object
    cn_close: pd.DataFrame
    cn_dk_close: pd.DataFrame
    suba_close: pd.DataFrame
    suba_all_codes: list[str]
    suba_asset_codes: list[str]
    dk_cols: list[str]


def load_module():
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = _PoeStub()
    spec = importlib.util.spec_from_file_location("mnt_bot_v71_mix_compare", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if had_poe:
        builtins.poe = old_poe
    else:
        delattr(builtins, "poe")
    return mod


def build_context(mod) -> MixContext:
    cn_raw = {}
    for secid in mod.CN_STOCK_CODES:
        df, _ = mod.fetch_cn_kline(secid)
        cn_raw[secid] = df

    zzhl_df = cn_raw.get(mod.CN_ZZHL_INDEX_SECID)
    if zzhl_df is not None and len(zzhl_df) > 0:
        try:
            pre_df = mod._fetch_cn_csindex(mod.CN_ZZHL_PRE_INDEX_CODE)
            if pre_df is not None and len(pre_df) > 50:
                start = zzhl_df.index[0]
                pre_only = pre_df[pre_df.index < start].copy()
                if len(pre_only) > 0:
                    pre_only["close"] *= zzhl_df["close"].iloc[0] / pre_only["close"].iloc[-1]
                    cn_raw[mod.CN_ZZHL_INDEX_SECID] = pd.concat([pre_only, zzhl_df])
        except Exception:
            pass

    cn_close = pd.concat(
        [cn_raw[s][["close"]].rename(columns={"close": s}) for s in mod.CN_STOCK_CODES],
        axis=1,
    ).ffill().dropna()

    bond_df, _ = mod.fetch_cn_kline(mod.CN_BOND_CODE)
    suba_close = cn_close.copy()
    suba_close[mod.CN_BOND_CODE] = bond_df["close"].reindex(suba_close.index)
    suba_close = suba_close.ffill().dropna()

    dk_specs = [
        (mod.CN_DK_ZZ1000_SECID, mod.CN_DK_COLS[0]),
        (mod.CN_DK_SZ50_SECID, mod.CN_DK_COLS[1]),
        (mod.CN_DK_HS300_SECID, mod.CN_DK_COLS[2]),
        (mod.CN_DK_ZZ500_SECID, mod.CN_DK_COLS[3]),
        (mod.CN_DK_CYB_SECID, mod.CN_DK_COLS[4]),
    ]
    dk_parts = []
    for secid, col in dk_specs:
        df, _ = mod.fetch_cn_kline(secid)
        dk_parts.append(df[["close"]].rename(columns={"close": col}))
    cn_dk_close = pd.concat(dk_parts, axis=1).ffill().dropna()

    common_start = max(suba_close.index[0], cn_dk_close.index[0])
    common_end = min(suba_close.index[-1], cn_dk_close.index[-1])
    suba_close = suba_close.loc[common_start:common_end].copy()
    cn_close = cn_close.loc[common_start:common_end].copy()
    cn_dk_close = cn_dk_close.loc[common_start:common_end].copy()

    return MixContext(
        mod=mod,
        cn_close=cn_close,
        cn_dk_close=cn_dk_close,
        suba_close=suba_close,
        suba_all_codes=[c for c in mod.CN_EQUITY_CODES + [mod.CN_BOND_CODE] if c in suba_close.columns],
        suba_asset_codes=[c for c in mod.CN_EQUITY_CODES if c in suba_close.columns],
        dk_cols=[c for c in mod.CN_DK_COLS if c in cn_dk_close.columns],
    )


@contextmanager
def temp_globals(mod, updates):
    old_values = {key: getattr(mod, key) for key in updates}
    try:
        for key, value in updates.items():
            setattr(mod, key, value)
        yield
    finally:
        for key, value in old_values.items():
            setattr(mod, key, value)


def calc_metrics(ret: pd.Series):
    ret = ret.dropna()
    if len(ret) < 20:
        return None
    nav = (1.0 + ret).cumprod()
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    if years <= 0:
        return None
    vol = ret.std() * np.sqrt(244)
    sharpe = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    max_dd = (nav / nav.cummax() - 1.0).min()
    cagr = nav.iloc[-1] ** (1.0 / years) - 1.0
    return {
        "cagr": float(cagr),
        "vol": float(vol),
        "sharpe": float(sharpe),
        "max_dd": float(max_dd),
        "calmar": float(cagr / abs(max_dd)) if max_dd < 0 else np.nan,
        "total_return": float(nav.iloc[-1] - 1.0),
    }


def summarize(name: str, family: str, mix_rule: str, df: pd.DataFrame, exposure_col: str):
    rows = []
    for seg_name, start, end in SEGMENTS:
        seg = df if start is None else df.loc[start:end]
        metrics = calc_metrics(seg["return"])
        if metrics is None:
            continue
        row = {
            "family": family,
            "strategy": name,
            "mix_rule": mix_rule,
            "segment": seg_name,
            "start": seg.index[0].date().isoformat(),
            "end": seg.index[-1].date().isoformat(),
            "avg_turnover": float(seg["turnover"].mean()) if "turnover" in seg else np.nan,
            "avg_gross_exposure": float(seg[exposure_col].mean()) if exposure_col in seg else np.nan,
        }
        row.update(metrics)
        rows.append(row)
    return rows


def suba_result_to_position_frame(ctx: MixContext, result: pd.DataFrame) -> pd.DataFrame:
    pos = pd.DataFrame(0.0, index=result.index, columns=ctx.suba_asset_codes + ["cash_fraction"])
    holding = result["holding"].fillna("cash").astype(str)
    holding_fraction = result["holding_fraction"].fillna(0.0).astype(float)
    effective_weight = result["weight"].fillna(0.0).astype(float)
    for code in ctx.suba_asset_codes:
        mask = holding == code
        pos.loc[mask, code] = effective_weight.loc[mask]
    pos["cash_fraction"] = np.where(holding == "cash", 1.0, 1.0 - holding_fraction.clip(0.0, 1.0))
    return pos


def combine_suba_weight_average(ctx: MixContext, variants):
    sleeve_results = [run_suba_single_variant(ctx, *params) for params in variants]
    sleeve_positions = [suba_result_to_position_frame(ctx, res) for res in sleeve_results]
    avg_pos = sum(sleeve_positions) / len(sleeve_positions)

    close_ret = ctx.suba_close[ctx.suba_asset_codes].pct_change().fillna(0.0)
    risky = avg_pos[ctx.suba_asset_codes].copy()
    cash = avg_pos["cash_fraction"].copy()
    prev_risky = risky.shift(1).fillna(0.0)
    prev_cash = cash.shift(1).fillna(1.0)
    gross = (prev_risky * close_ret.reindex(risky.index).fillna(0.0)).sum(axis=1) + prev_cash * ctx.mod.CN_RF_DAILY
    turnover = risky.sub(prev_risky).abs().sum(axis=1)
    turnover.iloc[0] = risky.iloc[0].abs().sum()
    trade_cost = turnover * ctx.mod.CN_COMMISSION
    net = (1.0 + gross) * (1.0 - trade_cost) - 1.0

    out = avg_pos.copy()
    out["return"] = net
    out["trade_cost"] = trade_cost
    out["turnover"] = turnover
    out["gross_exposure"] = risky.sum(axis=1)
    out["nav"] = (1.0 + out["return"]).cumprod()
    return out


def run_suba_single_variant(ctx: MixContext, bias_n: int, mom_day: int, r2_window: int):
    mod = ctx.mod
    with temp_globals(
        mod,
        {
            "CN_BIAS_N": bias_n,
            "CN_MOM_DAY": mom_day,
            "CN_R2_WINDOW": r2_window,
        },
    ):
        result = mod.run_cn_strategy(ctx.suba_close, mod.CN_EQUITY_CODES)
        if mod.CN_SA_CASH_OVERLAY_ENABLED:
            result = mod.apply_suba_cash_peak_decay_overlay(
                result,
                ctx.suba_close,
                decay_ratio_threshold=mod.CN_SA_CASH_OVERLAY_DECAY_RATIO,
                recovery_ratio_threshold=mod.CN_SA_CASH_OVERLAY_RECOVERY_RATIO,
                commission=mod.CN_COMMISSION,
            )
        if mod.CN_SA_SAME_SIDE_OVERHEAT_ENABLED:
            result = mod.apply_suba_same_side_overheat_overlay(
                result,
                ctx.suba_close,
                enter_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_ENTER,
                exit_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_EXIT,
                derisk_scale=mod.CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE,
            )
    return result


def build_suba_mix_features(ctx: MixContext, variants):
    mod = ctx.mod
    avg_bias_mom = {}
    avg_r2 = {}
    feature_cache = {}
    for code in ctx.suba_all_codes:
        bias_mom_parts = []
        r2_parts = []
        bias_parts = []
        for bias_n, mom_day, r2_window in variants:
            price = ctx.suba_close[code].astype(float)
            bias_mom_parts.append(mod.calc_bias_momentum(price, bias_n=bias_n, mom_day=mom_day))
            r2_parts.append(mod.calc_rolling_r2(price, window=r2_window))
            if code in ctx.suba_asset_codes:
                ma = price.rolling(bias_n).mean()
                bias_parts.append(price / ma - 1.0)
        avg_bias_mom[code] = pd.concat(bias_mom_parts, axis=1).mean(axis=1)
        avg_r2[code] = pd.concat(r2_parts, axis=1).mean(axis=1)
        if code in ctx.suba_asset_codes:
            bias_avg = pd.concat(bias_parts, axis=1).mean(axis=1)
            bias_mom_avg = avg_bias_mom[code]
            same_side = (bias_avg > 0) & (bias_mom_avg > 0) & bias_avg.notna() & bias_mom_avg.notna()
            feature_cache[code] = pd.DataFrame(
                {
                    "bias": bias_avg,
                    "bias_mom": bias_mom_avg,
                    "same_side": same_side,
                },
                index=ctx.suba_close.index,
            )
    return avg_bias_mom, avg_r2, feature_cache


def run_suba_signal_mix_base(ctx: MixContext, variants, avg_bias_mom, avg_r2):
    mod = ctx.mod
    start_idx = max(bias_n + mom_day for bias_n, mom_day, _ in variants)
    holding = "cash"
    holding_fraction = 0.0
    pending_entry_target = None
    pending_entry_since = None
    pending_entry_days = 0
    await_fresh_entry_signal = False
    rows = []

    for i in range(start_idx, len(ctx.suba_close)):
        date = ctx.suba_close.index[i]
        scores = {}
        for code in ctx.suba_all_codes:
            val = avg_bias_mom[code].iloc[i]
            if not np.isnan(val):
                scores[code] = float(val)
        ideal = "cash"
        if scores:
            best = max(scores, key=scores.get)
            if scores[best] > 0:
                r2_val = avg_r2[best].iloc[i] if i < len(avg_r2[best]) else np.nan
                if not np.isnan(r2_val) and r2_val >= mod.CN_R2_THRESHOLD:
                    ideal = best

        signal_target = ideal if ideal != holding else None
        trade_target = None
        trade_fraction = holding_fraction
        is_signal = False

        if holding == "cash":
            if await_fresh_entry_signal:
                if ideal == "cash":
                    await_fresh_entry_signal = False
            elif ideal != "cash":
                initial_fraction = float(np.clip(mod.CN_ENTRY_INITIAL_FRACTION, 0.0, 1.0))
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
                    await_fresh_entry_signal = False
                else:
                    prev_close = ctx.suba_close.iloc[i - 1][pending_entry_target] if i > 0 else np.nan
                    curr_close = ctx.suba_close.iloc[i][pending_entry_target]
                    is_down_day = pd.notna(prev_close) and pd.notna(curr_close) and float(curr_close) < float(prev_close)
                    if is_down_day:
                        trade_target = pending_entry_target
                        trade_fraction = 1.0
                        pending_entry_target = None
                        pending_entry_since = None
                        pending_entry_days = 0
                        is_signal = True
                    else:
                        pending_entry_days += 1
                        if mod.CN_ENTRY_WAIT_DAYS is not None and pending_entry_days >= int(mod.CN_ENTRY_WAIT_DAYS):
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
                await_fresh_entry_signal = False

        old_h = holding
        old_fraction = holding_fraction
        if old_h == "cash" or old_fraction <= 1e-12 or i == 0:
            asset_ret = 0.0
        else:
            asset_ret = ctx.suba_close.iloc[i][old_h] / ctx.suba_close.iloc[i - 1][old_h] - 1.0
        asset_component = old_fraction * asset_ret
        cash_component = (1.0 - old_fraction) * mod.CN_RF_DAILY
        trade_cost = 0.0

        if trade_target is not None:
            turnover = abs(float(trade_fraction) - float(old_fraction)) if trade_target == old_h else float(old_fraction) + float(trade_fraction)
            trade_cost = mod.CN_COMMISSION * turnover
            holding = trade_target if float(trade_fraction) > 1e-12 else "cash"
            holding_fraction = float(trade_fraction) if holding != "cash" else 0.0
        else:
            holding_fraction = old_fraction

        rows.append(
            {
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
                "await_fresh_entry_signal": await_fresh_entry_signal,
            }
        )

    df = pd.DataFrame(rows).set_index("date")
    raw_ret = (df["asset_component"] + df["cash_component"]).values.copy()
    base_weight = df["holding_fraction"].fillna(0.0).values
    is_cash = base_weight <= 1e-12
    realized_vol = pd.Series(raw_ret, index=df.index).rolling(mod.CN_VOL_WINDOW).std() * np.sqrt(mod.CN_TRADING_DAYS)
    raw_scale = (mod.CN_TARGET_VOL / realized_vol).clip(mod.CN_MIN_LEV, mod.CN_MAX_LEV).shift(1)
    if mod.CN_SCALE_THRESHOLD > 0:
        scale_arr_tmp = raw_scale.values.copy()
        last_val = np.nan
        for idx in range(len(scale_arr_tmp)):
            if np.isnan(scale_arr_tmp[idx]):
                continue
            if np.isnan(last_val):
                last_val = scale_arr_tmp[idx]
            elif abs(scale_arr_tmp[idx] - last_val) >= mod.CN_SCALE_THRESHOLD - 1e-9:
                last_val = scale_arr_tmp[idx]
            else:
                scale_arr_tmp[idx] = last_val
        raw_scale = pd.Series(scale_arr_tmp, index=df.index)
    scale_arr = raw_scale.fillna(1.0).values
    scale_arr[is_cash] = 1.0
    effective_weight = scale_arr * base_weight
    prev_scale = np.concatenate([[effective_weight[0]], effective_weight[:-1]])
    delta_scale = np.abs(effective_weight - prev_scale)
    no_holding_change = ~df["is_signal"].values
    scale_tc = np.where(no_holding_change & ~is_cash, mod.CN_COMMISSION * delta_scale, 0.0)

    df["scale_raw"] = raw_scale
    df["base_weight"] = base_weight
    df["weight"] = effective_weight
    df["realized_vol"] = realized_vol
    df["scale_tc"] = scale_tc
    scaled_gross = 1.0 + df["asset_component"].values * scale_arr + df["cash_component"].values
    df["return"] = scaled_gross * (1.0 - df["trade_cost"].values) * (1.0 - scale_tc) - 1.0
    df["nav"] = (1.0 + df["return"]).cumprod()
    return df


def extract_active_suba_mixed_score(base_result: pd.DataFrame, avg_bias_mom):
    scores = []
    for dt, row in base_result.iterrows():
        holding = str(row["holding"])
        fraction = float(row["holding_fraction"])
        score = np.nan
        if holding in avg_bias_mom and fraction > 1e-12 and dt in avg_bias_mom[holding].index:
            raw = avg_bias_mom[holding].loc[dt]
            if pd.notna(raw):
                score = float(raw)
        scores.append(score)
    return pd.Series(scores, index=base_result.index, dtype=float)


@contextmanager
def patch_suba_mix_helpers(mod, active_score_s, feature_cache):
    old_score_fn = mod._extract_active_cn_score
    old_feature_fn = mod._suba_same_side_overheat_features
    mod._extract_active_cn_score = lambda cn_result, close_df: active_score_s.reindex(cn_result.index).astype(float)
    mod._suba_same_side_overheat_features = lambda close_df: feature_cache
    try:
        yield
    finally:
        mod._extract_active_cn_score = old_score_fn
        mod._suba_same_side_overheat_features = old_feature_fn


def run_suba_signal_mix(ctx: MixContext, variants):
    mod = ctx.mod
    avg_bias_mom, avg_r2, feature_cache = build_suba_mix_features(ctx, variants)
    result = run_suba_signal_mix_base(ctx, variants, avg_bias_mom, avg_r2)
    active_score_s = extract_active_suba_mixed_score(result, avg_bias_mom)
    with patch_suba_mix_helpers(mod, active_score_s, feature_cache):
        if mod.CN_SA_CASH_OVERLAY_ENABLED:
            result = mod.apply_suba_cash_peak_decay_overlay(
                result,
                ctx.suba_close,
                decay_ratio_threshold=mod.CN_SA_CASH_OVERLAY_DECAY_RATIO,
                recovery_ratio_threshold=mod.CN_SA_CASH_OVERLAY_RECOVERY_RATIO,
                commission=mod.CN_COMMISSION,
            )
        if mod.CN_SA_SAME_SIDE_OVERHEAT_ENABLED:
            result = mod.apply_suba_same_side_overheat_overlay(
                result,
                ctx.suba_close,
                enter_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_ENTER,
                exit_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_EXIT,
                derisk_scale=mod.CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE,
            )
    out = result.copy()
    out["turnover"] = out["trade_cost"].fillna(0.0) / mod.CN_COMMISSION
    out["gross_exposure"] = out["weight"].fillna(0.0)
    return out


def parse_dk_row(row):
    holding = str(row.get("holding", "none_0"))
    weight = float(row.get("weight", 0.0))
    if holding == "none_0" or weight <= 1e-12:
        return None
    pair = str(row.get("top_pair", "none"))
    direction = int(row.get("direction", 0))
    if pair == "none" or direction == 0:
        return None
    a_name, b_name = pair.split("/")
    return (a_name, b_name, direction, weight)


def dk_result_to_position_frame(ctx: MixContext, result: pd.DataFrame):
    pos = pd.DataFrame(0.0, index=result.index, columns=[c.replace("DK_", "") for c in ctx.dk_cols])
    for dt, row in result.iterrows():
        parsed = parse_dk_row(row)
        if parsed is None:
            continue
        a_name, b_name, direction, weight = parsed
        if direction > 0:
            pos.loc[dt, a_name] += weight
            pos.loc[dt, b_name] -= weight
        else:
            pos.loc[dt, a_name] -= weight
            pos.loc[dt, b_name] += weight
    return pos


def combine_dk_weight_average(ctx: MixContext, variants):
    sleeve_results = [run_dk_single_variant(ctx, *params) for params in variants]
    sleeve_positions = [dk_result_to_position_frame(ctx, res) for res in sleeve_results]
    avg_pos = sum(sleeve_positions) / len(sleeve_positions)

    ret_cols = {c.replace("DK_", ""): c for c in ctx.dk_cols}
    close_ret = ctx.cn_dk_close[[ret_cols[k] for k in avg_pos.columns]].pct_change().fillna(0.0)
    close_ret = close_ret.rename(columns={v: k for k, v in ret_cols.items()})
    prev_pos = avg_pos.shift(1).fillna(0.0)
    gross = (prev_pos * close_ret.reindex(avg_pos.index).fillna(0.0)).sum(axis=1)
    turnover = avg_pos.sub(prev_pos).abs().sum(axis=1)
    turnover.iloc[0] = avg_pos.iloc[0].abs().sum()
    trade_cost = turnover * ctx.mod.CN_COMMISSION
    net = (1.0 + gross) * (1.0 - trade_cost) - 1.0

    out = avg_pos.copy()
    out["return"] = net
    out["trade_cost"] = trade_cost
    out["turnover"] = turnover
    out["gross_exposure"] = avg_pos.abs().sum(axis=1)
    out["nav"] = (1.0 + out["return"]).cumprod()
    return out


def run_dk_single_variant(ctx: MixContext, bias_n: int, mom_day: int):
    mod = ctx.mod
    with temp_globals(mod, {"CN_DK_BIAS_N": bias_n, "CN_DK_MOM_DAY": mom_day}):
        result = mod.run_dk_strategy(ctx.cn_close, ctx.cn_dk_close)
        if mod.CN_DK_PAIR_SCORE_DECAY_ENABLED:
            result = mod.apply_dk_pair_score_peak_decay_overlay(
                result,
                decay_ratio_threshold=mod.CN_DK_PAIR_SCORE_DECAY_RATIO,
                recovery_ratio_threshold=mod.CN_DK_PAIR_SCORE_RECOVERY_RATIO,
                derisk_scale=mod.CN_DK_PAIR_SCORE_DERISK_SCALE,
                commission=mod.CN_COMMISSION,
            )
        if mod.CN_DK_SAME_SIDE_OVERHEAT_ENABLED:
            result = mod.apply_dk_same_side_overheat_overlay(
                result,
                enter_threshold=mod.CN_DK_SAME_SIDE_OVERHEAT_ENTER,
                exit_threshold=mod.CN_DK_SAME_SIDE_OVERHEAT_EXIT,
                derisk_scale=mod.CN_DK_SAME_SIDE_OVERHEAT_DERISK_SCALE,
                commission=mod.CN_COMMISSION,
            )
        if mod.CN_DK_RISK_GATE_ENABLED:
            result = mod.apply_dk_drawdown_risk_gate(
                result,
                enter=mod.CN_DK_RISK_GATE_ENTER,
                scale_defense=mod.CN_DK_RISK_GATE_DEFENSE_SCALE,
                exit_value=mod.CN_DK_RISK_GATE_EXIT,
                cooldown_days=mod.CN_DK_RISK_GATE_COOLDOWN_DAYS,
            )
    result = result.copy()
    result["turnover"] = result["weight"].fillna(0.0).diff().abs().fillna(result["weight"].fillna(0.0))
    result["gross_exposure"] = result["weight"].fillna(0.0) * 2.0
    return result


def run_single_pair_dk_mixed(mod, a_prices, b_prices, variants):
    d = pd.DataFrame({"a": a_prices, "b": b_prices}).dropna()
    min_warm = max(bias_n + mom_day for bias_n, mom_day in variants)
    if len(d) < min_warm + mod.CN_DK_VOL_WINDOW + 50:
        return None, None, None, None
    d["a_ret"] = d["a"].pct_change()
    d["b_ret"] = d["b"].pct_change()
    d["spread_ret"] = d["a_ret"] - d["b_ret"]
    d = d.dropna(subset=["a_ret", "b_ret"])
    d["ratio"] = d["a"] / d["b"]

    bias_parts = []
    raw_bias_parts = []
    for bias_n, mom_day in variants:
        bias_parts.append(mod._dk_calc_bias_momentum(d["ratio"], bias_n, mom_day))
        ma = d["ratio"].rolling(bias_n).mean()
        raw_bias_parts.append(d["ratio"] / ma - 1.0)
    d["bias_mom"] = pd.concat(bias_parts, axis=1).mean(axis=1)
    d["raw_bias_avg"] = pd.concat(raw_bias_parts, axis=1).mean(axis=1)

    n = len(d)
    start_idx = max(min_warm, mod.CN_DK_VOL_WINDOW) + 1
    d["signal"] = np.nan
    valid = d["bias_mom"].notna() & (np.arange(n) >= start_idx)
    d.loc[valid, "signal"] = np.where(d.loc[valid, "bias_mom"] > 0, 1, -1)
    d["signal"] = d["signal"].ffill().astype(float)
    d["position"] = d["signal"].shift(1)
    d["raw_ret"] = d["position"] * d["spread_ret"]
    d = d.dropna(subset=["position", "raw_ret"])

    d["realized_vol"] = d["raw_ret"].rolling(mod.CN_DK_VOL_WINDOW).std() * np.sqrt(mod.CN_DK_TRADING_DAYS)
    d["scale"] = (mod.CN_DK_TARGET_VOL / d["realized_vol"]).clip(mod.CN_DK_MIN_LEV, mod.CN_DK_MAX_LEV)
    d["scale"] = d["scale"].shift(1)
    d["scale_raw"] = d["scale"].copy()
    if mod.CN_DK_SCALE_THRESHOLD > 0:
        arr = d["scale"].values.copy()
        last_val = np.nan
        for i in range(len(arr)):
            if np.isnan(arr[i]):
                continue
            if np.isnan(last_val):
                last_val = arr[i]
            elif abs(arr[i] - last_val) >= mod.CN_DK_SCALE_THRESHOLD - 1e-9:
                last_val = arr[i]
            else:
                arr[i] = last_val
        d["scale"] = arr
    d["strategy_ret"] = d["raw_ret"] * d["scale"]
    d = d.dropna(subset=["strategy_ret"])

    pos_prev = d["position"].shift(1)
    is_flip = (d["position"] != pos_prev) & pos_prev.notna()
    is_initial = d["position"].notna() & pos_prev.isna()
    if mod.CN_COMMISSION > 0:
        d["tc"] = 0.0
        d.loc[is_flip, "tc"] = 4 * mod.CN_COMMISSION * d["scale"][is_flip]
        d.loc[is_initial, "tc"] = 2 * mod.CN_COMMISSION * d["scale"][is_initial]
        change = d["scale"].diff().abs().fillna(0.0)
        only_scale = ~is_flip & ~is_initial & d["position"].notna()
        d.loc[only_scale, "tc"] += 2 * mod.CN_COMMISSION * change[only_scale]
        d["strategy_ret"] = (1.0 + d["strategy_ret"]) * (1.0 - d["tc"]) - 1.0

    abs_sig = d["bias_mom"].abs()
    same_side = (d["raw_bias_avg"] > 0) & (d["bias_mom"] > 0) & d["raw_bias_avg"].notna() & d["bias_mom"].notna()
    return d["strategy_ret"], abs_sig, d, pd.DataFrame({"abs_bias": d["raw_bias_avg"].abs(), "same_side": same_side}, index=d.index)


def build_dk_signal_mix_result(ctx: MixContext, variants):
    mod = ctx.mod
    idx_series = {}
    for name, info in mod.CN_DK_INDICES.items():
        if info["col"] in ctx.cn_dk_close.columns:
            idx_series[name] = ctx.cn_dk_close[info["col"]]
    pair_rets = {}
    pair_abs_sig = {}
    pair_data = {}
    pair_features = {}
    from itertools import combinations
    for a_name, b_name in combinations(idx_series.keys(), 2):
        label = f"{a_name}/{b_name}"
        ret, abs_sig, pdata, pfeat = run_single_pair_dk_mixed(mod, idx_series[a_name], idx_series[b_name], variants)
        if ret is None:
            continue
        pair_rets[label] = ret
        pair_abs_sig[label] = abs_sig
        pair_data[label] = pdata
        pair_features[label] = pfeat
    rets_df = pd.DataFrame(pair_rets)
    signals_df = pd.DataFrame(pair_abs_sig)
    combined_ret = mod._build_top_n_dk(rets_df, signals_df, mod.CN_DK_TOP_N)
    signals_shifted = signals_df.shift(1)
    common_idx = combined_ret.index

    top_pair_list = []
    top_dir_list = []
    weight_arr = []
    scale_raw_arr = []
    realized_vol_arr = []
    for date in common_idx:
        row_sig = signals_shifted.loc[date].dropna() if date in signals_shifted.index else pd.Series(dtype=float)
        if len(row_sig) == 0:
            top_pair_list.append("none")
            top_dir_list.append(0)
            weight_arr.append(1.0)
            scale_raw_arr.append(1.0)
            realized_vol_arr.append(np.nan)
            continue
        best = row_sig.idxmax()
        top_pair_list.append(best)
        pdata = pair_data[best]
        if date in pdata.index:
            sig_val = pdata.loc[date, "signal"] if "signal" in pdata.columns else np.nan
            top_dir_list.append(int(sig_val) if pd.notna(sig_val) else 0)
            weight_arr.append(float(pdata.loc[date, "scale"]) if "scale" in pdata.columns and pd.notna(pdata.loc[date, "scale"]) else 1.0)
            scale_raw_arr.append(float(pdata.loc[date, "scale_raw"]) if "scale_raw" in pdata.columns and pd.notna(pdata.loc[date, "scale_raw"]) else 1.0)
            realized_vol_arr.append(float(pdata.loc[date, "realized_vol"]) if "realized_vol" in pdata.columns and pd.notna(pdata.loc[date, "realized_vol"]) else np.nan)
        else:
            top_dir_list.append(0)
            weight_arr.append(1.0)
            scale_raw_arr.append(1.0)
            realized_vol_arr.append(np.nan)

    top_pair_series = pd.Series(top_pair_list, index=common_idx)
    top_dir_series = pd.Series(top_dir_list, index=common_idx)
    pair_changed = top_pair_series.ne(top_pair_series.shift(1))
    direction_changed = top_dir_series.ne(top_dir_series.shift(1))
    is_signal = pair_changed | direction_changed
    pair_changed.iloc[0] = False
    direction_changed.iloc[0] = False
    is_signal.iloc[0] = False

    pair_a_list = []
    pair_b_list = []
    long_leg_list = []
    short_leg_list = []
    for pair, direction in zip(top_pair_list, top_dir_list):
        if pair == "none" or direction == 0:
            pair_a_list.append(None)
            pair_b_list.append(None)
            long_leg_list.append(None)
            short_leg_list.append(None)
            continue
        a_name, b_name = pair.split("/")
        pair_a_list.append(a_name)
        pair_b_list.append(b_name)
        if direction > 0:
            long_leg_list.append(a_name)
            short_leg_list.append(b_name)
        else:
            long_leg_list.append(b_name)
            short_leg_list.append(a_name)

    result = pd.DataFrame(
        {
            "return": combined_ret,
            "nav": (1.0 + combined_ret).cumprod(),
            "top_pair": top_pair_series,
            "direction": top_dir_series,
            "holding": [f"{p}_{d}" for p, d in zip(top_pair_list, top_dir_list)],
            "pair_a": pair_a_list,
            "pair_b": pair_b_list,
            "long_leg": long_leg_list,
            "short_leg": short_leg_list,
            "pair_changed": pair_changed,
            "direction_changed": direction_changed,
            "is_signal": is_signal,
            "target": None,
            "weight": weight_arr,
            "scale_raw": scale_raw_arr,
            "realized_vol": realized_vol_arr,
        },
        index=common_idx,
    )
    result.attrs["pair_rets"] = pair_rets
    result.attrs["pair_abs_mom"] = pair_abs_sig
    result.attrs["pair_data"] = pair_data
    result.attrs["rets_df"] = rets_df
    result.attrs["signals_df"] = signals_df
    result.attrs["pair_features"] = pair_features
    return result


@contextmanager
def patch_dk_same_side_helper(mod, feature_cache):
    old_fn = mod._extract_active_pair_same_side_overheat

    def _patched(dk_result):
        abs_vals = []
        same_side_vals = []
        for dt, pair in dk_result["top_pair"].fillna("none").items():
            if pair != "none" and pair in feature_cache and dt in feature_cache[pair].index:
                row = feature_cache[pair].loc[dt]
                abs_vals.append(float(row["abs_bias"]) if pd.notna(row["abs_bias"]) else np.nan)
                same_side_vals.append(bool(row["same_side"]) if pd.notna(row["same_side"]) else False)
            else:
                abs_vals.append(np.nan)
                same_side_vals.append(False)
        return pd.Series(abs_vals, index=dk_result.index, dtype=float), pd.Series(same_side_vals, index=dk_result.index, dtype=bool)

    mod._extract_active_pair_same_side_overheat = _patched
    try:
        yield
    finally:
        mod._extract_active_pair_same_side_overheat = old_fn


def run_dk_signal_mix(ctx: MixContext, variants):
    mod = ctx.mod
    result = build_dk_signal_mix_result(ctx, variants)
    if mod.CN_DK_PAIR_SCORE_DECAY_ENABLED:
        result = mod.apply_dk_pair_score_peak_decay_overlay(
            result,
            decay_ratio_threshold=mod.CN_DK_PAIR_SCORE_DECAY_RATIO,
            recovery_ratio_threshold=mod.CN_DK_PAIR_SCORE_RECOVERY_RATIO,
            derisk_scale=mod.CN_DK_PAIR_SCORE_DERISK_SCALE,
            commission=mod.CN_COMMISSION,
        )
    with patch_dk_same_side_helper(mod, result.attrs["pair_features"]):
        if mod.CN_DK_SAME_SIDE_OVERHEAT_ENABLED:
            result = mod.apply_dk_same_side_overheat_overlay(
                result,
                enter_threshold=mod.CN_DK_SAME_SIDE_OVERHEAT_ENTER,
                exit_threshold=mod.CN_DK_SAME_SIDE_OVERHEAT_EXIT,
                derisk_scale=mod.CN_DK_SAME_SIDE_OVERHEAT_DERISK_SCALE,
                commission=mod.CN_COMMISSION,
            )
    if mod.CN_DK_RISK_GATE_ENABLED:
        result = mod.apply_dk_drawdown_risk_gate(
            result,
            enter=mod.CN_DK_RISK_GATE_ENTER,
            scale_defense=mod.CN_DK_RISK_GATE_DEFENSE_SCALE,
            exit_value=mod.CN_DK_RISK_GATE_EXIT,
            cooldown_days=mod.CN_DK_RISK_GATE_COOLDOWN_DAYS,
        )
    out = result.copy()
    out["turnover"] = out["weight"].fillna(0.0).diff().abs().fillna(out["weight"].fillna(0.0))
    out["gross_exposure"] = out["weight"].fillna(0.0) * 2.0
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mod = load_module()
    ctx = build_context(mod)

    summary_rows = []

    suba_baseline = run_suba_single_variant(ctx, *A_BASELINE[1][0]).copy()
    suba_baseline["turnover"] = suba_baseline["trade_cost"].fillna(0.0) / mod.CN_COMMISSION
    suba_baseline["gross_exposure"] = suba_baseline["weight"].fillna(0.0)
    summary_rows.extend(summarize(A_BASELINE[0], "Sub-A", "baseline", suba_baseline, "gross_exposure"))

    for name, variants in A_CANDIDATES:
        old_df = combine_suba_weight_average(ctx, variants)
        new_df = run_suba_signal_mix(ctx, variants)
        summary_rows.extend(summarize(name, "Sub-A", "weight_average", old_df, "gross_exposure"))
        summary_rows.extend(summarize(name, "Sub-A", "signal_mix_then_select", new_df, "gross_exposure"))

    dk_baseline = run_dk_single_variant(ctx, *DK_BASELINE[1][0])
    summary_rows.extend(summarize(DK_BASELINE[0], "Sub-A-DK", "baseline", dk_baseline, "gross_exposure"))

    for name, variants in DK_CANDIDATES:
        old_df = combine_dk_weight_average(ctx, variants)
        new_df = run_dk_signal_mix(ctx, variants)
        summary_rows.extend(summarize(name, "Sub-A-DK", "weight_average", old_df, "gross_exposure"))
        summary_rows.extend(summarize(name, "Sub-A-DK", "signal_mix_then_select", new_df, "gross_exposure"))

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUT_DIR / "summary.csv", index=False)

    core_df = summary_df[summary_df["segment"].isin(["last_3y", "last_5y", "last_10y", "full_common"])].copy()
    core_df.to_csv(OUT_DIR / "core_compare.csv", index=False)

    lines = [
        "# Sub-A / Sub-A-DK Signal-Mix Compare",
        "",
        "- Data source: production `fetch_cn_kline()` path from `mnt_bot V 7.1 plus.py`",
        "- Window: aligned common sample across Sub-A and ADK local data",
        "- Mix comparison:",
        "  - `weight_average`: each parameter group runs independently, then combine exposures",
        "  - `signal_mix_then_select`: average signals first, then run one mixed selector",
        "",
    ]
    for family in ["Sub-A", "Sub-A-DK"]:
        lines.append(f"## {family}")
        for seg in ["last_3y", "last_5y", "last_10y", "full_common"]:
            lines.append(f"### {seg}")
            sub = core_df[(core_df["family"] == family) & (core_df["segment"] == seg)].copy()
            if sub.empty:
                lines.append("- no rows")
                lines.append("")
                continue
            sub = sub.sort_values(["mix_rule", "sharpe"], ascending=[True, False])
            for _, row in sub.iterrows():
                lines.append(
                    f"- {row['strategy']} [{row['mix_rule']}]: CAGR {row['cagr']:.2%}, "
                    f"Sharpe {row['sharpe']:.3f}, MaxDD {row['max_dd']:.2%}"
                )
            lines.append("")

    (OUT_DIR / "summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()

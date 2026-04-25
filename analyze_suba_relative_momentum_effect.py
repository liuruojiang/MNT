import builtins
import importlib.util
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "mnt_bot V 7.1 plus.py"
OUT_DIR = ROOT / "docs" / "suba_relative_mom_effect_20260424"

SEGMENTS = [
    ("last_3y", "2023-04-24", "2026-04-24"),
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
class CnContext:
    mod: object
    close_df: pd.DataFrame
    all_codes: list[str]
    asset_codes: list[str]


def load_module():
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = _PoeStub()
    spec = importlib.util.spec_from_file_location("mnt_bot_v71_suba_relative", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if had_poe:
        builtins.poe = old_poe
    else:
        delattr(builtins, "poe")
    return mod


def build_context(mod) -> CnContext:
    cn_raw = {}
    for secid in mod.CN_STOCK_CODES:
        df, _source = mod.fetch_cn_kline(secid)
        cn_raw[secid] = df

    zzhl_df = cn_raw.get(mod.CN_ZZHL_INDEX_SECID)
    if zzhl_df is not None and len(zzhl_df) > 0:
        try:
            pre_df = mod._fetch_cn_csindex(mod.CN_ZZHL_PRE_INDEX_CODE)
            if pre_df is not None and len(pre_df) > 50:
                zzhl_start = zzhl_df.index[0]
                pre_only = pre_df[pre_df.index < zzhl_start].copy()
                if len(pre_only) > 0:
                    pre_only["close"] *= zzhl_df["close"].iloc[0] / pre_only["close"].iloc[-1]
                    cn_raw[mod.CN_ZZHL_INDEX_SECID] = pd.concat([pre_only, zzhl_df])
        except Exception:
            pass

    close_df = pd.concat(
        [cn_raw[s][["close"]].rename(columns={"close": s}) for s in mod.CN_STOCK_CODES],
        axis=1,
    ).ffill().dropna()

    try:
        bond_df, _ = mod.fetch_cn_kline(mod.CN_BOND_CODE)
        close_df[mod.CN_BOND_CODE] = bond_df["close"].reindex(close_df.index)
        close_df = close_df.ffill()
    except Exception:
        pass

    return CnContext(
        mod=mod,
        close_df=close_df,
        all_codes=[c for c in mod.CN_EQUITY_CODES + [mod.CN_BOND_CODE] if c in close_df.columns],
        asset_codes=[c for c in mod.CN_EQUITY_CODES if c in close_df.columns],
    )


def calc_relative_momentum(close_series: pd.Series, lookback: int) -> pd.Series:
    return close_series.div(close_series.shift(lookback)).sub(1.0)


def run_relative_cn_strategy(ctx: CnContext, lookback: int, r2_window: int) -> pd.DataFrame:
    mod = ctx.mod
    close_df = ctx.close_df
    equity_codes = mod.CN_EQUITY_CODES
    bond_code = mod.CN_BOND_CODE
    all_codes = [c for c in equity_codes + [bond_code] if c in close_df.columns]

    rel_mom_dict = {}
    r2_dict = {}
    for code in all_codes:
        rel_mom_dict[code] = calc_relative_momentum(close_df[code], lookback)
        r2_dict[code] = mod.calc_rolling_r2(close_df[code], window=r2_window)

    start_idx = max(lookback, r2_window)
    holding = "cash"
    holding_fraction = 0.0
    pending_entry_target = None
    pending_entry_since = None
    pending_entry_days = 0
    await_fresh_entry_signal = False
    rows = []

    for i in range(start_idx, len(close_df)):
        date = close_df.index[i]
        scores = {}
        for code in all_codes:
            val = rel_mom_dict[code].iloc[i]
            if not np.isnan(val):
                scores[code] = val

        ideal = "cash"
        if scores:
            best = max(scores, key=scores.get)
            if scores[best] > 0:
                r2_val = r2_dict.get(best, pd.Series(dtype=float)).iloc[i] if best in r2_dict else np.nan
                if not np.isnan(r2_val) and r2_val >= mod.CN_R2_THRESHOLD:
                    ideal = best

        signal_target = ideal if ideal != holding else None
        trade_target = None
        trade_fraction = holding_fraction
        is_signal = False

        if holding == "cash":
            if pending_entry_target is not None:
                signal_candidates = {k: v for k, v in scores.items() if v > 0}
                if signal_candidates:
                    best_candidate = max(signal_candidates, key=signal_candidates.get)
                    best_r2 = r2_dict.get(best_candidate, pd.Series(dtype=float)).iloc[i] if best_candidate in r2_dict else np.nan
                    if (
                        best_candidate != pending_entry_target
                        and not np.isnan(best_r2)
                        and best_r2 >= mod.CN_R2_THRESHOLD
                    ):
                        pending_entry_target = None
                        pending_entry_since = None
                        pending_entry_days = 0
                        await_fresh_entry_signal = False
                if signal_target is not None:
                    initial_fraction = float(np.clip(mod.CN_ENTRY_INITIAL_FRACTION, 0.0, 1.0))
                    trade_target = signal_target
                    trade_fraction = initial_fraction
                    is_signal = initial_fraction > 0.0
                    if initial_fraction >= 1.0 - 1e-12:
                        pending_entry_target = None
                        pending_entry_since = None
                        pending_entry_days = 0
                    else:
                        pending_entry_target = signal_target
                        pending_entry_since = date
                        pending_entry_days = 0
            elif signal_target is not None and not await_fresh_entry_signal:
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
            asset_ret = close_df.iloc[i][old_h] / close_df.iloc[i - 1][old_h] - 1
        asset_component = old_fraction * asset_ret
        cash_component = (1.0 - old_fraction) * mod.CN_RF_DAILY
        trade_cost = 0.0

        if trade_target is not None:
            if trade_target == old_h:
                turnover = abs(float(trade_fraction) - float(old_fraction))
            else:
                turnover = float(old_fraction) + float(trade_fraction)
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
    raw_scale = (mod.CN_TARGET_VOL / realized_vol).clip(mod.CN_MIN_LEV, mod.CN_MAX_LEV)
    raw_scale = raw_scale.shift(1)
    if mod.CN_SCALE_THRESHOLD > 0:
        scale_arr = raw_scale.values.copy()
        last = np.nan
        for idx, value in enumerate(scale_arr):
            if np.isnan(value):
                continue
            if np.isnan(last):
                last = value
            elif abs(value - last) >= mod.CN_SCALE_THRESHOLD - 1e-9:
                last = value
            else:
                scale_arr[idx] = last
        raw_scale = pd.Series(scale_arr, index=df.index)

    scale_arr = raw_scale.fillna(1.0).values
    df["scale_raw"] = raw_scale
    scale_arr[is_cash] = 1.0
    effective_weight = scale_arr * base_weight
    df["base_weight"] = base_weight
    df["weight"] = effective_weight
    df["realized_vol"] = realized_vol

    prev_scale = np.concatenate([[effective_weight[0]], effective_weight[:-1]])
    delta_scale = np.abs(effective_weight - prev_scale)
    no_holding_change = ~df["is_signal"].values
    scale_tc = np.where(no_holding_change & ~is_cash, mod.CN_COMMISSION * delta_scale, 0.0)
    df["scale_tc"] = scale_tc
    scaled_gross = 1.0 + df["asset_component"].values * scale_arr + df["cash_component"].values
    df["return"] = scaled_gross * (1.0 - df["trade_cost"].values) * (1.0 - scale_tc) - 1.0
    df["nav"] = (1.0 + df["return"]).cumprod()
    return df


def run_baseline(ctx: CnContext) -> pd.DataFrame:
    mod = ctx.mod
    result = mod.run_cn_strategy(ctx.close_df, mod.CN_EQUITY_CODES)
    if mod.CN_SA_CASH_OVERLAY_ENABLED:
        result = mod.apply_suba_cash_peak_decay_overlay(
            result,
            ctx.close_df,
            decay_ratio_threshold=mod.CN_SA_CASH_OVERLAY_DECAY_RATIO,
            recovery_ratio_threshold=mod.CN_SA_CASH_OVERLAY_RECOVERY_RATIO,
            commission=mod.CN_COMMISSION,
        )
    if mod.CN_SA_SAME_SIDE_OVERHEAT_ENABLED:
        result = mod.apply_suba_same_side_overheat_overlay(
            result,
            ctx.close_df,
            enter_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_ENTER,
            exit_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_EXIT,
            derisk_scale=mod.CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE,
        )
    return result


def run_relative_variant(ctx: CnContext, lookback: int, r2_window: int) -> pd.DataFrame:
    mod = ctx.mod
    result = run_relative_cn_strategy(ctx, lookback=lookback, r2_window=r2_window)
    if mod.CN_SA_CASH_OVERLAY_ENABLED:
        result = mod.apply_suba_cash_peak_decay_overlay(
            result,
            ctx.close_df,
            decay_ratio_threshold=mod.CN_SA_CASH_OVERLAY_DECAY_RATIO,
            recovery_ratio_threshold=mod.CN_SA_CASH_OVERLAY_RECOVERY_RATIO,
            commission=mod.CN_COMMISSION,
        )
    if mod.CN_SA_SAME_SIDE_OVERHEAT_ENABLED:
        result = mod.apply_suba_same_side_overheat_overlay(
            result,
            ctx.close_df,
            enter_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_ENTER,
            exit_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_EXIT,
            derisk_scale=mod.CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE,
        )
    return result


def calc_metrics(ret: pd.Series) -> dict[str, float]:
    ret = ret.dropna()
    if len(ret) < 20:
        return {}
    nav = (1.0 + ret).cumprod()
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    cagr = nav.iloc[-1] ** (1.0 / years) - 1.0
    vol = ret.std() * np.sqrt(244)
    sharpe = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    maxdd = (nav / nav.cummax() - 1.0).min()
    return {
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "maxdd": maxdd,
        "final_nav": nav.iloc[-1],
    }


def summarize(name: str, df: pd.DataFrame) -> list[dict]:
    rows = []
    for seg_name, start, end in SEGMENTS:
        seg = df if start is None else df.loc[start:end]
        metrics = calc_metrics(seg["return"])
        row = {
            "strategy": name,
            "segment": seg_name,
            "start": seg.index[0].date().isoformat(),
            "end": seg.index[-1].date().isoformat(),
            "avg_weight": float(seg["weight"].mean()) if "weight" in seg else np.nan,
            "avg_turnover": float((seg["weight"].diff().abs().fillna(seg["weight"].abs())).mean()) if "weight" in seg else np.nan,
        }
        row.update(metrics)
        rows.append(row)
    return rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mod = load_module()
    ctx = build_context(mod)

    baseline = run_baseline(ctx)
    rel20 = run_relative_variant(ctx, lookback=20, r2_window=mod.CN_R2_WINDOW)

    summary_rows = []
    summary_rows.extend(summarize("baseline_bias_60_20_20", baseline))
    summary_rows.extend(summarize("relative_mom_20", rel20))
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUT_DIR / "summary.csv", index=False, encoding="utf-8-sig")

    width_rows = []
    for lookback in range(10, 41):
        result = run_relative_variant(ctx, lookback=lookback, r2_window=mod.CN_R2_WINDOW)
        for seg_name, start, end in SEGMENTS:
            seg = result if start is None else result.loc[start:end]
            metrics = calc_metrics(seg["return"])
            width_rows.append(
                {
                    "lookback": lookback,
                    "segment": seg_name,
                    "start": seg.index[0].date().isoformat(),
                    "end": seg.index[-1].date().isoformat(),
                    **metrics,
                }
            )
    width_df = pd.DataFrame(width_rows)
    width_df.to_csv(OUT_DIR / "relative_momentum_width_scan.csv", index=False, encoding="utf-8-sig")

    band_rows = []
    for seg_name in [name for name, _, _ in SEGMENTS]:
        sub = width_df[width_df["segment"] == seg_name].copy().sort_values("lookback")
        base = sub[sub["lookback"] == 20].iloc[0]
        sub["sharpe_ratio"] = sub["sharpe"] / base["sharpe"]
        sub["dd_delta_pp"] = (sub["maxdd"] - base["maxdd"]) * 100
        strict = sub[(sub["sharpe_ratio"] >= 0.90) & (sub["dd_delta_pp"] >= -3.0)]["lookback"].tolist()
        loose = sub[(sub["sharpe_ratio"] >= 0.85) & (sub["dd_delta_pp"] >= -5.0)]["lookback"].tolist()
        band_rows.append(
            {
                "segment": seg_name,
                "base_cagr": base["cagr"],
                "base_sharpe": base["sharpe"],
                "base_maxdd": base["maxdd"],
                "strict_band": ",".join(str(x) for x in strict),
                "loose_band": ",".join(str(x) for x in loose),
            }
        )
    band_df = pd.DataFrame(band_rows)
    band_df.to_csv(OUT_DIR / "relative_momentum_width_bands.csv", index=False, encoding="utf-8-sig")

    lines = [
        "# Sub-A Relative Momentum Replacement",
        "",
        "- Base script: `mnt_bot V 7.1 plus.py`",
        "- Data source: production `fetch_cn_kline()` path via the script",
        "- Replacement definition: `close / close.shift(n) - 1`",
        "- Scope: replace Sub-A ranking signal only; keep existing `R²`, cash overlay, same-side overheat, vol scaling, and commission path",
        "",
        "## Core Compare",
    ]
    for seg_name in [name for name, _, _ in SEGMENTS]:
        seg = summary_df[summary_df["segment"] == seg_name]
        lines.append(f"### {seg_name}")
        for _, row in seg.iterrows():
            lines.append(
                f"- {row['strategy']}: CAGR {row['cagr']:.2%}, Sharpe {row['sharpe']:.3f}, MaxDD {row['maxdd']:.2%}"
            )
        lines.append("")

    lines.append("## Width Bands Around Relative 20")
    for _, row in band_df.iterrows():
        lines.append(
            f"- {row['segment']}: strict [{row['strict_band']}], loose [{row['loose_band']}]"
        )

    (OUT_DIR / "summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()

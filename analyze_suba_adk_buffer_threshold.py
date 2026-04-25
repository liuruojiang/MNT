from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import pandas as pd

import analyze_suba_adk_signal_mix_compare as base


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "docs" / "suba_adk_buffer_threshold_20260425"

BUFFER_THRESHOLDS = [
    ("legacy_no_buffer_1p00x", 1.00),
    ("candidate_1p02x", 1.02),
    ("candidate_1p05x", 1.05),
    ("candidate_1p10x", 1.10),
    ("candidate_1p15x", 1.15),
    ("candidate_1p20x", 1.20),
]

A_TESTS = [
    base.A_BASELINE,
    ("mix_50_15__60_20__70_25", ((50, 15, 15), (60, 20, 20), (70, 25, 25))),
    ("mix_55_15__60_20__80_25", ((55, 15, 15), (60, 20, 20), (80, 25, 25))),
]

DK_TESTS = [
    base.DK_BASELINE,
    ("mix2_60_20__65_20", ((60, 20), (65, 20))),
    ("mix2_60_20__70_20", ((60, 20), (70, 20))),
    ("mix2_60_20__50_20", ((60, 20), (50, 20))),
]


def _eligible_suba(avg_bias_mom: pd.DataFrame, avg_r2: pd.DataFrame, date, target: str, r2_threshold: float) -> bool:
    if target not in avg_bias_mom or target not in avg_r2:
        return False
    score = avg_bias_mom[target].loc[date] if date in avg_bias_mom[target].index else np.nan
    r2_val = avg_r2[target].loc[date] if date in avg_r2[target].index else np.nan
    return pd.notna(score) and pd.notna(r2_val) and float(score) > 0 and float(r2_val) >= r2_threshold


def run_suba_signal_mix_with_buffer(ctx: base.MixContext, variants, threshold: float) -> pd.DataFrame:
    mod = ctx.mod
    avg_bias_mom, avg_r2, feature_cache = base.build_suba_mix_features(ctx, variants)
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
            best_eligible = scores[best] > 0
            if best_eligible:
                r2_val = avg_r2[best].iloc[i] if i < len(avg_r2[best]) else np.nan
                best_eligible = not np.isnan(r2_val) and r2_val >= mod.CN_R2_THRESHOLD
            if best_eligible:
                current_eligible = (
                    holding != "cash"
                    and holding != best
                    and _eligible_suba(avg_bias_mom, avg_r2, date, holding, mod.CN_R2_THRESHOLD)
                )
                if current_eligible and threshold > 1.0:
                    current_score = float(avg_bias_mom[holding].loc[date])
                    ideal = best if scores[best] > current_score * threshold else holding
                else:
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

    result = pd.DataFrame(rows).set_index("date")
    raw_ret = (result["asset_component"] + result["cash_component"]).values.copy()
    base_weight = result["holding_fraction"].fillna(0.0).values
    is_cash = base_weight <= 1e-12
    realized_vol = pd.Series(raw_ret, index=result.index).rolling(mod.CN_VOL_WINDOW).std() * np.sqrt(mod.CN_TRADING_DAYS)
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
        raw_scale = pd.Series(scale_arr_tmp, index=result.index)
    scale_arr = raw_scale.fillna(1.0).values
    scale_arr[is_cash] = 1.0
    effective_weight = scale_arr * base_weight
    prev_scale = np.concatenate([[effective_weight[0]], effective_weight[:-1]])
    delta_scale = np.abs(effective_weight - prev_scale)
    no_holding_change = ~result["is_signal"].values
    scale_tc = np.where(no_holding_change & ~is_cash, mod.CN_COMMISSION * delta_scale, 0.0)

    result["scale_raw"] = raw_scale
    result["base_weight"] = base_weight
    result["weight"] = effective_weight
    result["realized_vol"] = realized_vol
    result["scale_tc"] = scale_tc
    scaled_gross = 1.0 + result["asset_component"].values * scale_arr + result["cash_component"].values
    result["return"] = scaled_gross * (1.0 - result["trade_cost"].values) * (1.0 - scale_tc) - 1.0
    result["nav"] = (1.0 + result["return"]).cumprod()

    active_score_s = base.extract_active_suba_mixed_score(result, avg_bias_mom)
    with base.patch_suba_mix_helpers(mod, active_score_s, feature_cache):
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
    result = result.copy()
    result["turnover"] = result["trade_cost"].fillna(0.0) / mod.CN_COMMISSION
    result["gross_exposure"] = result["weight"].fillna(0.0)
    return result


def run_dk_signal_mix_with_buffer(ctx: base.MixContext, variants, threshold: float) -> pd.DataFrame:
    mod = ctx.mod
    production_pairs = variants is None
    idx_series = {}
    for name, info in mod.CN_DK_INDICES.items():
        src_df = ctx.cn_dk_close if production_pairs and info.get("src") == "dk" else ctx.cn_close
        if not production_pairs:
            src_df = ctx.cn_dk_close
        if info["col"] in src_df.columns:
            idx_series[name] = src_df[info["col"]]
    pair_rets = {}
    pair_abs_sig = {}
    pair_data = {}
    pair_features = {}
    from itertools import combinations

    for a_name, b_name in combinations(idx_series.keys(), 2):
        label = f"{a_name}/{b_name}"
        if production_pairs:
            ret, abs_sig, pdata = mod._run_single_pair_dk(idx_series[a_name], idx_series[b_name])
            pfeat = None
        else:
            ret, abs_sig, pdata, pfeat = base.run_single_pair_dk_mixed(
                mod, idx_series[a_name], idx_series[b_name], variants
            )
        if ret is None:
            continue
        pair_rets[label] = ret
        pair_abs_sig[label] = abs_sig
        pair_data[label] = pdata
        if pfeat is not None:
            pair_features[label] = pfeat

    rets_df = pd.DataFrame(pair_rets)
    signals_df = pd.DataFrame(pair_abs_sig)
    common_idx = rets_df.index.intersection(signals_df.index)
    rets_df = rets_df.reindex(common_idx)
    signals_df = signals_df.reindex(common_idx)
    signals_shifted = signals_df.shift(1)

    top_pair_list = []
    top_dir_list = []
    weight_arr = []
    scale_raw_arr = []
    realized_vol_arr = []
    combined_values = []
    prev_pair = None

    for date in common_idx:
        row_sig = signals_shifted.loc[date].dropna() if date in signals_shifted.index else pd.Series(dtype=float)
        if len(row_sig) == 0:
            selected = "none"
        else:
            best = row_sig.idxmax()
            selected = best
            if threshold > 1.0 and prev_pair in row_sig.index and prev_pair != best:
                prev_score = float(row_sig[prev_pair])
                best_score = float(row_sig[best])
                if prev_score > 0 and best_score <= prev_score * threshold:
                    selected = prev_pair

        if selected == "none":
            direction = 0
            weight = 1.0
            scale_raw = 1.0
            realized_vol = np.nan
            ret_val = 0.0
            prev_pair = None
        else:
            pdata = pair_data[selected]
            if date in pdata.index:
                sig_val = pdata.loc[date, "signal"] if "signal" in pdata.columns else np.nan
                direction = int(sig_val) if pd.notna(sig_val) else 0
                weight = float(pdata.loc[date, "scale"]) if "scale" in pdata.columns and pd.notna(pdata.loc[date, "scale"]) else 1.0
                scale_raw = float(pdata.loc[date, "scale_raw"]) if "scale_raw" in pdata.columns and pd.notna(pdata.loc[date, "scale_raw"]) else 1.0
                realized_vol = float(pdata.loc[date, "realized_vol"]) if "realized_vol" in pdata.columns and pd.notna(pdata.loc[date, "realized_vol"]) else np.nan
                ret_val = float(pair_rets[selected].loc[date]) if date in pair_rets[selected].index else 0.0
            else:
                direction = 0
                weight = 1.0
                scale_raw = 1.0
                realized_vol = np.nan
                ret_val = 0.0
            prev_pair = selected

        top_pair_list.append(selected)
        top_dir_list.append(direction)
        weight_arr.append(weight)
        scale_raw_arr.append(scale_raw)
        realized_vol_arr.append(realized_vol)
        combined_values.append(ret_val)

    combined_ret = pd.Series(combined_values, index=common_idx)
    top_pair_series = pd.Series(top_pair_list, index=common_idx)
    top_dir_series = pd.Series(top_dir_list, index=common_idx)
    pair_changed = top_pair_series.ne(top_pair_series.shift(1))
    direction_changed = top_dir_series.ne(top_dir_series.shift(1))
    is_signal = pair_changed | direction_changed
    if len(is_signal) > 0:
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

    if mod.CN_DK_PAIR_SCORE_DECAY_ENABLED:
        result = mod.apply_dk_pair_score_peak_decay_overlay(
            result,
            decay_ratio_threshold=mod.CN_DK_PAIR_SCORE_DECAY_RATIO,
            recovery_ratio_threshold=mod.CN_DK_PAIR_SCORE_RECOVERY_RATIO,
            derisk_scale=mod.CN_DK_PAIR_SCORE_DERISK_SCALE,
            commission=mod.CN_COMMISSION,
        )
    same_side_context = (
        base.patch_dk_same_side_helper(mod, result.attrs["pair_features"])
        if not production_pairs
        else nullcontext()
    )
    with same_side_context:
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


def summarize_with_threshold(strategy: str, family: str, threshold_name: str, threshold: float, df: pd.DataFrame, exposure_col: str):
    rows = base.summarize(strategy, family, threshold_name, df, exposure_col)
    signal_count = int(df.get("is_signal", pd.Series(False, index=df.index)).fillna(False).sum())
    pair_changes = int(df.get("pair_changed", pd.Series(False, index=df.index)).fillna(False).sum())
    direction_changes = int(df.get("direction_changed", pd.Series(False, index=df.index)).fillna(False).sum())
    for row in rows:
        row["threshold"] = threshold
        row["signal_count"] = signal_count
        row["pair_changes"] = pair_changes
        row["direction_changes"] = direction_changes
    return rows


def validate_parity(ctx: base.MixContext) -> dict:
    checks = {}
    suba_name, suba_variants = base.A_BASELINE
    old_suba = base.run_suba_signal_mix(ctx, suba_variants)
    new_suba = run_suba_signal_mix_with_buffer(ctx, suba_variants, 1.0)
    common = old_suba.index.intersection(new_suba.index)
    checks[f"suba_{suba_name}_threshold_1p00_nav_max_abs_diff"] = float(
        (old_suba.loc[common, "nav"] - new_suba.loc[common, "nav"]).abs().max()
    )

    dk_name, dk_variants = base.DK_BASELINE
    old_dk = base.run_dk_signal_mix(ctx, dk_variants)
    new_dk = run_dk_signal_mix_with_buffer(ctx, dk_variants, 1.0)
    common = old_dk.index.intersection(new_dk.index)
    checks[f"adk_{dk_name}_threshold_1p00_nav_max_abs_diff"] = float(
        (old_dk.loc[common, "nav"] - new_dk.loc[common, "nav"]).abs().max()
    )
    old_dk_prod = base.run_dk_single_variant(ctx, 60, 20)
    new_dk_prod = run_dk_signal_mix_with_buffer(ctx, None, 1.0)
    common = old_dk_prod.index.intersection(new_dk_prod.index)
    checks["adk_formal_baseline_60_20_threshold_1p00_nav_max_abs_diff"] = float(
        (old_dk_prod.loc[common, "nav"] - new_dk_prod.loc[common, "nav"]).abs().max()
    )
    return checks


def write_summary(summary_df: pd.DataFrame, validation: dict):
    lines = [
        "# Sub-A / Sub-A-DK Buffer Threshold Scan",
        "",
        "- Data source: production `fetch_cn_kline()` path from `mnt_bot V 7.1 plus.py`",
        "- Window: same aligned common sample used by `analyze_suba_adk_signal_mix_compare.py`",
        "- Costs: `CN_COMMISSION` from production script; existing Sub-A and DK overlays are applied",
        "- Sub-A buffer: if the current holding remains eligible, a challenger must beat current averaged score by the threshold before switching",
        "- Sub-A-DK buffer: if the current index pair remains scored, a challenger pair must beat its absolute score by the threshold before switching pair; pair direction still follows the original pair signal",
        "",
        "## Validation",
    ]
    for key, value in validation.items():
        lines.append(f"- {key}: {value:.12g}")

    core = summary_df[summary_df["segment"].isin(["last_3y", "last_5y", "last_10y", "full_common"])].copy()
    for family in ["Sub-A", "Sub-A-DK"]:
        lines.extend(["", f"## {family}"])
        for strategy in core.loc[core["family"] == family, "strategy"].drop_duplicates():
            lines.extend(["", f"### {strategy}"])
            for seg in ["last_3y", "last_5y", "last_10y", "full_common"]:
                sub = core[(core["family"] == family) & (core["strategy"] == strategy) & (core["segment"] == seg)].copy()
                if sub.empty:
                    continue
                sub = sub.sort_values("sharpe", ascending=False)
                lines.append(f"#### {seg}")
                for _, row in sub.iterrows():
                    lines.append(
                        f"- {row['mix_rule']}: CAGR {row['cagr']:.2%}, Sharpe {row['sharpe']:.3f}, "
                        f"MaxDD {row['max_dd']:.2%}, Signals {int(row['signal_count'])}"
                    )
                best = sub.iloc[0]
                lines.append(f"- Winner by Sharpe: {best['mix_rule']}")
    (OUT_DIR / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mod = base.load_module()
    ctx = base.build_context(mod)
    validation = validate_parity(ctx)
    (OUT_DIR / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")

    summary_rows = []
    nav_dir = OUT_DIR / "nav"
    nav_dir.mkdir(exist_ok=True)

    for strategy, variants in A_TESTS:
        for threshold_name, threshold in BUFFER_THRESHOLDS:
            df = run_suba_signal_mix_with_buffer(ctx, variants, threshold)
            df.to_csv(nav_dir / f"suba_{strategy}_{threshold_name}.csv")
            summary_rows.extend(
                summarize_with_threshold(strategy, "Sub-A", threshold_name, threshold, df, "gross_exposure")
            )

    for strategy, variants in DK_TESTS:
        for threshold_name, threshold in BUFFER_THRESHOLDS:
            df = run_dk_signal_mix_with_buffer(ctx, variants, threshold)
            df.to_csv(nav_dir / f"adk_{strategy}_{threshold_name}.csv")
            summary_rows.extend(
                summarize_with_threshold(strategy, "Sub-A-DK", threshold_name, threshold, df, "gross_exposure")
            )

    for threshold_name, threshold in BUFFER_THRESHOLDS:
        df = run_dk_signal_mix_with_buffer(ctx, None, threshold)
        df.to_csv(nav_dir / f"adk_formal_baseline_60_20_{threshold_name}.csv")
        summary_rows.extend(
            summarize_with_threshold("formal_baseline_60_20", "Sub-A-DK", threshold_name, threshold, df, "gross_exposure")
        )

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUT_DIR / "summary.csv", index=False)
    write_summary(summary_df, validation)


if __name__ == "__main__":
    main()

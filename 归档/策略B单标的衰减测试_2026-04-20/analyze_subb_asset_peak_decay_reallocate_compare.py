from pathlib import Path

import numpy as np
import pandas as pd

from analyze_subb_asset_peak_decay_overlay import (
    BASE_SCRIPT,
    _load_module,
    _fetch_formal_subb_inputs,
    _baseline_subb_result,
    _extract_asset_overlay_state,
    _default_overlay_assets,
    _evaluate_result,
    apply_subb_asset_peak_decay_overlay,
)


HERE = Path(__file__).resolve().parent
OUT_COMPARE_CSV = HERE / "subb_asset_peak_decay_reallocate_compare.csv"
OUT_SUBB_WINDOWS_CSV = HERE / "subb_asset_peak_decay_reallocate_subb_windows.csv"
OUT_COMBO_WINDOWS_CSV = HERE / "subb_asset_peak_decay_reallocate_combo_windows.csv"
OUT_SUMMARY_MD = HERE / "subb_asset_peak_decay_reallocate_compare_2026-04-20.md"


def apply_subb_asset_peak_decay_overlay_reallocate_from_state(
    base_result: pd.DataFrame,
    asset_returns: pd.DataFrame,
    effective_weights: pd.DataFrame,
    active_score: pd.DataFrame,
    decay_ratio_threshold: float,
    recovery_ratio_threshold: float,
    derisk_scale: float,
    commission: float = 0.0,
    overlay_assets: list[str] | None = None,
) -> pd.DataFrame:
    if not 0 < decay_ratio_threshold < 1:
        raise ValueError("decay_ratio_threshold must be in (0, 1).")
    if not decay_ratio_threshold < recovery_ratio_threshold <= 1:
        raise ValueError("recovery_ratio_threshold must be in (decay_ratio_threshold, 1].")
    if not 0 <= derisk_scale <= 1:
        raise ValueError("derisk_scale must be in [0, 1].")

    out = base_result.copy()
    asset_returns = asset_returns.reindex(out.index).copy()
    effective_weights = effective_weights.reindex(out.index).fillna(0.0).copy()
    active_score = active_score.reindex(out.index).copy()

    risky_assets = [c for c in active_score.columns if c != "BIL"]
    governed_assets = set(risky_assets if overlay_assets is None else [a for a in overlay_assets if a in risky_assets])
    if "BIL" not in effective_weights.columns:
        raise KeyError("effective_weights must include BIL.")
    if "BIL" not in asset_returns.columns:
        raise KeyError("asset_returns must include BIL.")

    state = {
        asset: {
            "peak": None,
            "derisked": False,
            "waiting": False,
            "rearm_peak": None,
            "prev_scale": 1.0,
        }
        for asset in risky_assets
    }

    final_ret = []
    overlay_asset_count = []
    overlay_weight_removed = []
    overlay_weight_reallocated = []
    overlay_weight_to_bil = []

    for asset in risky_assets:
        out[f"overlay_scale_{asset}"] = 1.0
        out[f"overlay_triggered_{asset}"] = False
        out[f"overlay_recovered_{asset}"] = False
        out[f"waiting_for_new_peak_{asset}"] = False
        out[f"score_peak_overlay_{asset}"] = float("nan")
        out[f"score_decay_ratio_overlay_{asset}"] = float("nan")

    for i, dt in enumerate(out.index):
        bil_weight = float(effective_weights.loc[dt, "BIL"])
        bil_ret = float(asset_returns.loc[dt, "BIL"]) if pd.notna(asset_returns.loc[dt, "BIL"]) else 0.0
        removed_weight = 0.0
        cost = 0.0
        asset_count = 0

        base_weight_map = {}
        scale_map = {}
        ret_map = {}

        for asset in risky_assets:
            base_weight = float(effective_weights.loc[dt, asset]) if asset in effective_weights.columns else 0.0
            held_today = base_weight > 1e-12
            prev_base_weight = float(effective_weights.iloc[i - 1][asset]) if i > 0 and asset in effective_weights.columns else 0.0
            new_trade = held_today and prev_base_weight <= 1e-12
            asset_state = state[asset]
            governed = asset in governed_assets

            if not held_today:
                asset_state["peak"] = None
                asset_state["derisked"] = False
                asset_state["waiting"] = False
                asset_state["rearm_peak"] = None
                asset_state["prev_scale"] = 1.0
                out.at[dt, f"overlay_scale_{asset}"] = 1.0
                out.at[dt, f"waiting_for_new_peak_{asset}"] = False
                base_weight_map[asset] = 0.0
                scale_map[asset] = 1.0
                ret_map[asset] = 0.0
                continue

            if new_trade:
                asset_state["peak"] = None
                asset_state["derisked"] = False
                asset_state["waiting"] = False
                asset_state["rearm_peak"] = None
                asset_state["prev_scale"] = 1.0

            cur_scale = derisk_scale if (governed and asset_state["derisked"]) else 1.0
            triggered_today = cur_scale < 0.999999 and asset_state["prev_scale"] >= 0.999999
            recovered_today = cur_scale >= 0.999999 and asset_state["prev_scale"] < 0.999999

            cur_score = active_score.loc[dt, asset] if (governed and asset in active_score.columns) else float("nan")
            if pd.notna(cur_score):
                cur_score = float(cur_score)
                asset_state["peak"] = cur_score if asset_state["peak"] is None else max(float(asset_state["peak"]), cur_score)

            decay_ratio = None
            if asset_state["peak"] is not None and asset_state["peak"] > 1e-12 and pd.notna(cur_score):
                decay_ratio = float(cur_score) / float(asset_state["peak"])

            next_derisked = asset_state["derisked"]
            next_waiting = asset_state["waiting"]
            next_rearm_peak = asset_state["rearm_peak"]

            if (
                next_waiting
                and not recovered_today
                and next_rearm_peak is not None
                and asset_state["peak"] is not None
                and asset_state["peak"] > float(next_rearm_peak) + 1e-12
            ):
                next_waiting = False
                next_rearm_peak = None

            if governed:
                if next_derisked:
                    if decay_ratio is not None and decay_ratio >= recovery_ratio_threshold:
                        next_derisked = False
                        next_waiting = True
                        next_rearm_peak = cur_score
                elif not next_waiting and decay_ratio is not None and decay_ratio <= decay_ratio_threshold:
                    next_derisked = True

            scale_removed = base_weight * (1.0 - cur_scale)
            removed_weight += scale_removed
            delta_scale = abs(cur_scale - asset_state["prev_scale"])
            if delta_scale > 1e-12:
                cost += 2.0 * commission * base_weight * delta_scale
            if cur_scale < 0.999999:
                asset_count += 1

            out.at[dt, f"overlay_scale_{asset}"] = cur_scale
            out.at[dt, f"overlay_triggered_{asset}"] = bool(triggered_today)
            out.at[dt, f"overlay_recovered_{asset}"] = bool(recovered_today)
            out.at[dt, f"waiting_for_new_peak_{asset}"] = bool(next_waiting)
            out.at[dt, f"score_peak_overlay_{asset}"] = float("nan") if asset_state["peak"] is None else float(asset_state["peak"])
            out.at[dt, f"score_decay_ratio_overlay_{asset}"] = float("nan") if decay_ratio is None else float(decay_ratio)

            asset_state["derisked"] = next_derisked
            asset_state["waiting"] = next_waiting
            asset_state["rearm_peak"] = next_rearm_peak
            asset_state["prev_scale"] = cur_scale

            base_weight_map[asset] = base_weight
            scale_map[asset] = cur_scale
            ret_map[asset] = float(asset_returns.loc[dt, asset]) if asset in asset_returns.columns and pd.notna(asset_returns.loc[dt, asset]) else 0.0

        eligible_assets = [
            asset
            for asset in risky_assets
            if base_weight_map.get(asset, 0.0) > 1e-12 and scale_map.get(asset, 1.0) >= 0.999999
        ]
        eligible_total = sum(base_weight_map[a] for a in eligible_assets)
        extra_alloc = {asset: 0.0 for asset in risky_assets}
        reallocated_weight = 0.0
        if removed_weight > 1e-12 and eligible_total > 1e-12:
            for asset in eligible_assets:
                extra = removed_weight * base_weight_map[asset] / eligible_total
                extra_alloc[asset] = extra
                reallocated_weight += extra

        leftover_to_bil = max(removed_weight - reallocated_weight, 0.0)
        risky_return = 0.0
        for asset in risky_assets:
            effective_asset_weight = base_weight_map.get(asset, 0.0) * scale_map.get(asset, 1.0) + extra_alloc.get(asset, 0.0)
            risky_return += effective_asset_weight * ret_map.get(asset, 0.0)

        bil_total_weight = bil_weight + leftover_to_bil
        day_ret = risky_return + bil_total_weight * bil_ret
        day_ret = (1.0 + day_ret) * (1.0 - cost) - 1.0

        final_ret.append(float(day_ret))
        overlay_asset_count.append(int(asset_count))
        overlay_weight_removed.append(float(removed_weight))
        overlay_weight_reallocated.append(float(reallocated_weight))
        overlay_weight_to_bil.append(float(leftover_to_bil))

    out["return"] = pd.Series(final_ret, index=out.index, dtype=float)
    out["nav"] = (1 + out["return"]).cumprod()
    out["overlay_asset_count"] = pd.Series(overlay_asset_count, index=out.index, dtype=int)
    out["overlay_weight_removed"] = pd.Series(overlay_weight_removed, index=out.index, dtype=float)
    out["overlay_weight_reallocated"] = pd.Series(overlay_weight_reallocated, index=out.index, dtype=float)
    out["overlay_weight_to_bil"] = pd.Series(overlay_weight_to_bil, index=out.index, dtype=float)
    out["effective_bil_weight_overlay"] = effective_weights["BIL"].astype(float) + out["overlay_weight_to_bil"]
    out.attrs["asset_peak_decay_overlay"] = {
        "routing": "reallocate_to_other_held_assets",
        "decay_ratio_threshold": decay_ratio_threshold,
        "recovery_ratio_threshold": recovery_ratio_threshold,
        "derisk_scale": derisk_scale,
        "commission": commission,
        "overlay_assets": sorted(governed_assets),
        "overlay_days": int((out["overlay_asset_count"] > 0).sum()),
        "overlay_ratio": float((out["overlay_asset_count"] > 0).mean()),
        "overlay_asset_days": int(out["overlay_asset_count"].sum()),
        "avg_removed_weight": float(out["overlay_weight_removed"].mean()),
        "avg_reallocated_weight": float(out["overlay_weight_reallocated"].mean()),
        "avg_weight_to_bil": float(out["overlay_weight_to_bil"].mean()),
        "trigger_count": int(sum(int(out[f"overlay_triggered_{asset}"].sum()) for asset in governed_assets)),
        "recovery_count": int(sum(int(out[f"overlay_recovered_{asset}"].sum()) for asset in governed_assets)),
    }
    return out


def apply_subb_asset_peak_decay_overlay_reallocate(
    mod,
    base_result: pd.DataFrame,
    us_rot_close: pd.DataFrame,
    decay_ratio_threshold: float,
    recovery_ratio_threshold: float,
    derisk_scale: float,
    commission: float | None = None,
) -> pd.DataFrame:
    asset_returns, effective_weights, active_score = _extract_asset_overlay_state(mod, base_result, us_rot_close)
    return apply_subb_asset_peak_decay_overlay_reallocate_from_state(
        base_result=base_result,
        asset_returns=asset_returns,
        effective_weights=effective_weights,
        active_score=active_score,
        decay_ratio_threshold=decay_ratio_threshold,
        recovery_ratio_threshold=recovery_ratio_threshold,
        derisk_scale=derisk_scale,
        commission=mod.US_ROT_COMMISSION if commission is None else commission,
        overlay_assets=_default_overlay_assets(mod),
    )


def _evaluate_windows(mod, name: str, result: pd.DataFrame, windows: list[tuple[str, pd.Timestamp]]) -> list[dict]:
    rows = []
    ret = result["return"].dropna()
    for label, start_date in windows:
        win = ret.loc[ret.index >= start_date]
        if len(win) < 2:
            continue
        metrics = mod.calc_daily_metrics(win, 0.0, mod.US_TRADING_DAYS)
        rows.append(
            {
                "variant": name,
                "window": label,
                "start": win.index[0].strftime("%Y-%m-%d"),
                "end": win.index[-1].strftime("%Y-%m-%d"),
                "annual": metrics["annual"],
                "max_dd": metrics["max_dd"],
                "sharpe": metrics["sharpe"],
                "calmar": metrics["calmar"],
                "total_return": metrics["total_return"],
            }
        )
    return rows


def _combined_metrics(mod, cn_result, dk_result, us_result, subc_daily, weights, start_date, end_date):
    nav_parts = {}
    for sname, dret in [
        ("Sub-A", cn_result["return"]),
        ("Sub-A-DK", dk_result["return"]),
        ("Sub-B", us_result["return"]),
        ("Sub-C", subc_daily),
    ]:
        win = dret[(dret.index >= start_date) & (dret.index <= end_date)]
        if len(win) > 1:
            nav = (1 + win).cumprod()
            nav_parts[sname] = nav / nav.iloc[0]
    if len(nav_parts) < 2:
        raise RuntimeError("insufficient sleeves for combo metrics")

    common_start = max(series.index[0] for series in nav_parts.values())
    all_dates = sorted(set().union(*(series.index for series in nav_parts.values())))
    all_dates = [d for d in all_dates if d >= common_start and d <= end_date]
    nav_df = pd.DataFrame({name: series.reindex(pd.DatetimeIndex(all_dates)).ffill() for name, series in nav_parts.items()})
    weight_df = nav_df.notna().astype(float)
    for col in weight_df.columns:
        weight_df[col] *= weights.get(col, 0.0)
    weight_sum = weight_df.sum(axis=1).replace(0, np.nan)
    weight_df = weight_df.div(weight_sum, axis=0)
    nav_comb = (nav_df.fillna(0.0) * weight_df).sum(axis=1)
    nav_comb = nav_comb / nav_comb.iloc[0]
    dd = ((nav_comb - nav_comb.cummax()) / nav_comb.cummax()).min() * 100
    n_days = (nav_comb.index[-1] - nav_comb.index[0]).days
    annual = ((nav_comb.iloc[-1]) ** (365.25 / n_days) - 1) * 100 if n_days > 0 else np.nan
    total = (nav_comb.iloc[-1] - 1) * 100
    daily = nav_comb.pct_change().dropna()
    sharpe = daily.mean() / daily.std() * np.sqrt(252) if len(daily) > 1 and daily.std() > 0 else np.nan
    calmar = annual / abs(dd) if dd != 0 else np.nan
    return {
        "annual": annual,
        "max_dd": dd,
        "sharpe": sharpe,
        "calmar": calmar,
        "total_return": total,
        "start": nav_comb.index[0].strftime("%Y-%m-%d"),
        "end": nav_comb.index[-1].strftime("%Y-%m-%d"),
    }


def _write_summary(compare_df, subb_windows_df, combo_windows_df):
    def fmt_pct(v):
        return f"{float(v):.4f}%"

    baseline = compare_df.loc[compare_df["variant"] == "baseline_no_overlay"].iloc[0]
    cash = compare_df.loc[compare_df["variant"] == "asset_overlay_to_bil_25_65_0p5"].iloc[0]
    realloc = compare_df.loc[compare_df["variant"] == "asset_overlay_reallocate_25_65_0p5"].iloc[0]

    lines = [
        "# Sub-B 单标的衰减：回BIL vs 分给其余持仓",
        "",
        f"- 基线脚本: `{BASE_SCRIPT.name}`",
        "- 正式入口: `CombinedStrategyV68._fetch_data(..., include_us_live_snapshot=False)` + 正式 `_run_strategies`",
        "- 对照参数固定: `decay=25% / recover=65% / derisk_scale=0.5`",
        "- 唯一区别: 触发衰减后，减出来的权重是回 `BIL`，还是按当日其余未减仓持仓的原始权重比例再分配",
        "",
        "## Sub-B 全样本",
        "",
        f"- 基线: 年化 `{fmt_pct(baseline['annual'])}` / 最大回撤 `{fmt_pct(baseline['max_dd'])}`",
        f"- 回BIL: 年化 `{fmt_pct(cash['annual'])}` / 最大回撤 `{fmt_pct(cash['max_dd'])}` / 年化变化 `{cash['annual'] - baseline['annual']:+.4f}%` / 回撤变化 `{cash['max_dd'] - baseline['max_dd']:+.4f}%`",
        f"- 再分配: 年化 `{fmt_pct(realloc['annual'])}` / 最大回撤 `{fmt_pct(realloc['max_dd'])}` / 年化变化 `{realloc['annual'] - baseline['annual']:+.4f}%` / 回撤变化 `{realloc['max_dd'] - baseline['max_dd']:+.4f}%`",
        "",
        "## 窗口对照",
        "",
    ]

    for label in ["1Y", "3Y", "5Y", "15Y"]:
        sub = subb_windows_df[subb_windows_df["window"] == label]
        combo = combo_windows_df[combo_windows_df["window"] == label]
        if sub.empty or combo.empty:
            continue
        b_sub = sub[sub["variant"] == "baseline_no_overlay"].iloc[0]
        c_sub = sub[sub["variant"] == "asset_overlay_to_bil_25_65_0p5"].iloc[0]
        r_sub = sub[sub["variant"] == "asset_overlay_reallocate_25_65_0p5"].iloc[0]
        b_combo = combo[combo["variant"] == "combo_baseline_v68"].iloc[0]
        c_combo = combo[combo["variant"] == "combo_v68_plus_subb_asset_overlay_to_bil_25_65_0p5"].iloc[0]
        r_combo = combo[combo["variant"] == "combo_v68_plus_subb_asset_overlay_reallocate_25_65_0p5"].iloc[0]
        lines.extend(
            [
                f"### {label}",
                "",
                f"- Sub-B 基线 `{fmt_pct(b_sub['annual'])}` / `{fmt_pct(b_sub['max_dd'])}`",
                f"- Sub-B 回BIL `{fmt_pct(c_sub['annual'])}` / `{fmt_pct(c_sub['max_dd'])}`",
                f"- Sub-B 再分配 `{fmt_pct(r_sub['annual'])}` / `{fmt_pct(r_sub['max_dd'])}`",
                f"- 组合基线 `{fmt_pct(b_combo['annual'])}` / `{fmt_pct(b_combo['max_dd'])}`",
                f"- 组合回BIL `{fmt_pct(c_combo['annual'])}` / `{fmt_pct(c_combo['max_dd'])}`",
                f"- 组合再分配 `{fmt_pct(r_combo['annual'])}` / `{fmt_pct(r_combo['max_dd'])}`",
                "",
            ]
        )

    OUT_SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    mod = _load_module(BASE_SCRIPT, "subb_asset_peak_decay_reallocate_compare_mod")
    bot, us_rot_close = _fetch_formal_subb_inputs(mod)
    base_result = _baseline_subb_result(mod, bot, us_rot_close)
    cash_result = apply_subb_asset_peak_decay_overlay(
        mod,
        base_result,
        us_rot_close,
        decay_ratio_threshold=0.25,
        recovery_ratio_threshold=0.65,
        derisk_scale=0.5,
        commission=mod.US_ROT_COMMISSION,
    )
    realloc_result = apply_subb_asset_peak_decay_overlay_reallocate(
        mod,
        base_result,
        us_rot_close,
        decay_ratio_threshold=0.25,
        recovery_ratio_threshold=0.65,
        derisk_scale=0.5,
        commission=mod.US_ROT_COMMISSION,
    )

    compare_rows = [
        _evaluate_result(mod, "baseline_no_overlay", base_result),
        _evaluate_result(mod, "asset_overlay_to_bil_25_65_0p5", cash_result, cash_result.attrs.get("asset_peak_decay_overlay", {})),
        _evaluate_result(mod, "asset_overlay_reallocate_25_65_0p5", realloc_result, realloc_result.attrs.get("asset_peak_decay_overlay", {})),
    ]
    compare_df = pd.DataFrame(compare_rows)
    compare_df.to_csv(OUT_COMPARE_CSV, index=False, encoding="utf-8-sig")

    full_end = min(base_result.index.max(), realloc_result.index.max())
    window_spec = [
        ("1Y", full_end - pd.DateOffset(years=1)),
        ("3Y", full_end - pd.DateOffset(years=3)),
        ("5Y", full_end - pd.DateOffset(years=5)),
        ("15Y", pd.Timestamp("2011-04-20")),
    ]
    subb_windows_rows = []
    for name, result in [
        ("baseline_no_overlay", base_result),
        ("asset_overlay_to_bil_25_65_0p5", cash_result),
        ("asset_overlay_reallocate_25_65_0p5", realloc_result),
    ]:
        subb_windows_rows.extend(_evaluate_windows(mod, name, result, window_spec))
    subb_windows_df = pd.DataFrame(subb_windows_rows)
    subb_windows_df.to_csv(OUT_SUBB_WINDOWS_CSV, index=False, encoding="utf-8-sig")

    cn_close, cn_dk_close, _, us_prod_daily = bot._fetch_data(
        type("_Silent", (), {"write": lambda *args, **kwargs: None})(),
        include_us_live_snapshot=False,
    )
    cn_result, dk_result, us_rot_result, _, prod_sig_a, prod_sig_b, _, _ = bot._run_strategies(
        cn_close.copy(),
        cn_dk_close.copy(),
        us_rot_close.copy(),
        us_prod_daily.copy(),
    )
    subc_daily = mod._get_subc_daily_ret(us_prod_daily.copy(), prod_sig_a, prod_sig_b=prod_sig_b)

    combo_rows = []
    for label, start_date in window_spec:
        combo_rows.append(
            {
                "variant": "combo_baseline_v68",
                "window": label,
                **_combined_metrics(mod, cn_result, dk_result, us_rot_result, subc_daily, mod.COMBINED_WEIGHTS, start_date, full_end),
            }
        )
        combo_rows.append(
            {
                "variant": "combo_v68_plus_subb_asset_overlay_to_bil_25_65_0p5",
                "window": label,
                **_combined_metrics(mod, cn_result, dk_result, cash_result, subc_daily, mod.COMBINED_WEIGHTS, start_date, full_end),
            }
        )
        combo_rows.append(
            {
                "variant": "combo_v68_plus_subb_asset_overlay_reallocate_25_65_0p5",
                "window": label,
                **_combined_metrics(mod, cn_result, dk_result, realloc_result, subc_daily, mod.COMBINED_WEIGHTS, start_date, full_end),
            }
        )
    combo_windows_df = pd.DataFrame(combo_rows)
    combo_windows_df.to_csv(OUT_COMBO_WINDOWS_CSV, index=False, encoding="utf-8-sig")

    _write_summary(compare_df, subb_windows_df, combo_windows_df)

    print(compare_df.to_string(index=False))
    print(f"\nSaved: {OUT_COMPARE_CSV}")
    print(f"Saved: {OUT_SUBB_WINDOWS_CSV}")
    print(f"Saved: {OUT_COMBO_WINDOWS_CSV}")
    print(f"Saved: {OUT_SUMMARY_MD}")


if __name__ == "__main__":
    main()

import argparse
from pathlib import Path

import pandas as pd

from analyze_suba_decay_switch_overlay import (
    BASE_SCRIPT,
    CN_CSV,
    US_CSV,
    _build_bias_df,
    _combined_metrics,
    _evaluate_result,
    _load_local_cn_data,
    _load_local_us_data,
    _load_module,
    _extract_active_bias_score,
    apply_suba_decay_switch_overlay,
)


HERE = Path(__file__).resolve().parent
OUTPUT_CSV = HERE / "suba_decay_switch_cash_fine_scan.csv"
WINDOW_SCORE_CSV = HERE / "suba_decay_switch_cash_window_scores.csv"
LONGITUDINAL_CSV = HERE / "suba_decay_switch_cash_longitudinal_robustness.csv"
HORIZONTAL_CSV = HERE / "suba_decay_switch_cash_horizontal_robustness.csv"
COMBO_TOP3_CSV = HERE / "suba_decay_switch_cash_combo_top3.csv"
COMBO_WINDOW_CSV = HERE / "suba_decay_switch_cash_combo_window_compare.csv"
SUMMARY_FINE_MD = HERE / "参数细扫与鲁棒性测试_2026-04-20.md"


def _build_grid(decays, recovers):
    rows = []
    for decay in decays:
        for recover in recovers:
            if recover <= decay:
                continue
            rows.append((float(decay), float(recover)))
    return rows


def _window_metrics(mod, variant_name, result_df, windows):
    rows = []
    ret = result_df["return"].dropna()
    for window, days in windows:
        cur = ret.iloc[-days:] if len(ret) > days else ret
        if len(cur) < 2:
            continue
        metrics = mod.calc_daily_metrics(cur, mod.CN_RF_DAILY, mod.CN_TRADING_DAYS)
        rows.append(
            {
                "variant": variant_name,
                "window": window,
                "days": len(cur),
                "annual": metrics["annual"],
                "max_dd": metrics["max_dd"],
                "sharpe": metrics["sharpe"],
                "calmar": metrics["calmar"],
            }
        )
    return rows


def _rolling_compare(mod, variant_df, baseline_df, window_days, step_days):
    var_ret = variant_df["return"].dropna()
    base_ret = baseline_df["return"].dropna()
    idx = var_ret.index.intersection(base_ret.index)
    var_ret = var_ret.reindex(idx)
    base_ret = base_ret.reindex(idx)
    rows = []
    for end in range(window_days, len(idx) + 1, step_days):
        win_idx = idx[end - window_days : end]
        var_win = var_ret.loc[win_idx]
        base_win = base_ret.loc[win_idx]
        if len(var_win) < window_days or len(base_win) < window_days:
            continue
        var_m = mod.calc_daily_metrics(var_win, mod.CN_RF_DAILY, mod.CN_TRADING_DAYS)
        base_m = mod.calc_daily_metrics(base_win, mod.CN_RF_DAILY, mod.CN_TRADING_DAYS)
        rows.append(
            {
                "start": win_idx[0].strftime("%Y-%m-%d"),
                "end": win_idx[-1].strftime("%Y-%m-%d"),
                "annual_delta": var_m["annual"] - base_m["annual"],
                "max_dd_delta": var_m["max_dd"] - base_m["max_dd"],
                "sharpe_delta": var_m["sharpe"] - base_m["sharpe"],
                "calmar_delta": var_m["calmar"] - base_m["calmar"],
                "better_annual": var_m["annual"] > base_m["annual"],
                "better_maxdd": var_m["max_dd"] > base_m["max_dd"],
                "better_both": (var_m["annual"] > base_m["annual"]) and (var_m["max_dd"] > base_m["max_dd"]),
            }
        )
    return pd.DataFrame(rows)


def _build_window_score_df(compare_df, window_df):
    non = compare_df.loc[compare_df["variant"] != "baseline_no_overlay"].copy()
    non["full_annual_rank"] = non["annual"].rank(method="min", ascending=False)
    non["full_maxdd_rank"] = non["max_dd"].rank(method="min", ascending=False)
    non["full_calmar_rank"] = non["calmar"].rank(method="min", ascending=False)

    score_df = non[
        [
            "variant",
            "decay_ratio_threshold",
            "recovery_ratio_threshold",
            "annual",
            "max_dd",
            "sharpe",
            "calmar",
            "annual_delta",
            "max_dd_delta",
            "full_annual_rank",
            "full_maxdd_rank",
            "full_calmar_rank",
        ]
    ].copy()

    for window in ["1Y", "3Y", "5Y"]:
        sub = window_df.loc[window_df["window"] == window].copy()
        sub = sub.loc[sub["variant"] != "baseline_no_overlay"].copy()
        sub[f"{window}_annual_rank"] = sub["annual"].rank(method="min", ascending=False)
        sub[f"{window}_maxdd_rank"] = sub["max_dd"].rank(method="min", ascending=False)
        sub[f"{window}_calmar_rank"] = sub["calmar"].rank(method="min", ascending=False)
        sub = sub[
            [
                "variant",
                "annual",
                "max_dd",
                "sharpe",
                "calmar",
                f"{window}_annual_rank",
                f"{window}_maxdd_rank",
                f"{window}_calmar_rank",
            ]
        ].rename(
            columns={
                "annual": f"{window}_annual",
                "max_dd": f"{window}_max_dd",
                "sharpe": f"{window}_sharpe",
                "calmar": f"{window}_calmar",
            }
        )
        score_df = score_df.merge(sub, on="variant", how="left")

    score_df["recent_rank"] = score_df[["1Y_annual_rank", "1Y_maxdd_rank", "1Y_calmar_rank"]].mean(axis=1)
    score_df["mid_rank"] = score_df[["3Y_annual_rank", "3Y_maxdd_rank", "3Y_calmar_rank"]].mean(axis=1)
    score_df["long_rank"] = score_df[["5Y_annual_rank", "5Y_maxdd_rank", "5Y_calmar_rank"]].mean(axis=1)
    score_df["composite_rank"] = score_df[
        ["full_annual_rank", "full_maxdd_rank", "full_calmar_rank", "recent_rank", "mid_rank", "long_rank"]
    ].mean(axis=1)
    return score_df.sort_values(["composite_rank", "full_calmar_rank", "recent_rank"], ascending=[True, True, True])


def _build_horizontal_robustness(score_df):
    rows = []
    base = score_df.set_index("variant")
    for _, row in score_df.iterrows():
        decay = float(row["decay_ratio_threshold"])
        recover = float(row["recovery_ratio_threshold"])
        neigh = score_df.loc[
            (score_df["variant"] != row["variant"])
            & (score_df["decay_ratio_threshold"].between(decay - 0.0251, decay + 0.0251))
            & (score_df["recovery_ratio_threshold"].between(recover - 0.0251, recover + 0.0251))
        ].copy()
        rows.append(
            {
                "variant": row["variant"],
                "decay_ratio_threshold": decay,
                "recovery_ratio_threshold": recover,
                "neighbor_count": int(len(neigh)),
                "neighbor_better_annual_ratio": float((neigh["annual_delta"] > 0).mean()) if len(neigh) else None,
                "neighbor_better_maxdd_ratio": float((neigh["max_dd_delta"] > 0).mean()) if len(neigh) else None,
                "neighbor_better_both_ratio": float(((neigh["annual_delta"] > 0) & (neigh["max_dd_delta"] > 0)).mean())
                if len(neigh)
                else None,
                "neighbor_avg_annual_delta": float(neigh["annual_delta"].mean()) if len(neigh) else None,
                "neighbor_avg_maxdd_delta": float(neigh["max_dd_delta"].mean()) if len(neigh) else None,
                "self_composite_rank": float(base.loc[row["variant"], "composite_rank"]),
            }
        )
    out = pd.DataFrame(rows)
    out["neighbor_avg_calmar_proxy"] = out["neighbor_avg_annual_delta"].fillna(0.0) + out["neighbor_avg_maxdd_delta"].fillna(0.0)
    return out.sort_values(
        ["neighbor_better_both_ratio", "neighbor_avg_calmar_proxy", "self_composite_rank"],
        ascending=[False, False, True],
        na_position="last",
    )


def _write_summary(
    baseline_row,
    score_df,
    longitudinal_df,
    horizontal_df,
    combo_df,
    combo_window_df,
    sample_start,
    sample_end,
):
    top5 = score_df.head(5).copy()
    top_variant = top5.iloc[0]
    top_long = longitudinal_df.loc[longitudinal_df["variant"] == top_variant["variant"]].copy()
    top_hori = horizontal_df.loc[horizontal_df["variant"] == top_variant["variant"]].iloc[0]

    lines = [
        "# 策略A切现金参数细扫与鲁棒性测试",
        "",
        f"- 基线脚本: `{BASE_SCRIPT.name}`",
        f"- 本地数据: `{CN_CSV.name}` / `{US_CSV.name}`",
        f"- 样本区间: `{sample_start} -> {sample_end}`",
        f"- 基线 Sub-A: 年化 `{baseline_row['annual']:.4f}%` / 最大回撤 `{baseline_row['max_dd']:.4f}%` / Calmar `{baseline_row['calmar']:.4f}`",
        "",
        "## 联合排序 Top 5",
        "",
    ]

    for _, row in top5.iterrows():
        lines.append(
            f"- `{row['variant']}`: 全样本 `{row['annual']:.4f}% / {row['max_dd']:.4f}%`; "
            f"1Y `{row['1Y_annual']:.4f}% / {row['1Y_max_dd']:.4f}%`; "
            f"3Y `{row['3Y_annual']:.4f}% / {row['3Y_max_dd']:.4f}%`; "
            f"5Y `{row['5Y_annual']:.4f}% / {row['5Y_max_dd']:.4f}%`; "
            f"联合排名 `{row['composite_rank']:.2f}`"
        )

    lines.extend(["", "## 最优组鲁棒性", ""])
    if not top_long.empty:
        for _, row in top_long.iterrows():
            lines.append(
                f"- `{row['window']}` 滚动窗: 年化跑赢占比 `{row['better_annual_ratio']:.2%}` / "
                f"回撤更浅占比 `{row['better_maxdd_ratio']:.2%}` / 双改善占比 `{row['better_both_ratio']:.2%}`"
            )
    lines.append(
        f"- 邻域鲁棒性: 相邻参数双改善占比 `{top_hori['neighbor_better_both_ratio']:.2%}` / "
        f"邻域平均年化增量 `{top_hori['neighbor_avg_annual_delta']:.4f}%` / "
        f"邻域平均回撤改善 `{top_hori['neighbor_avg_maxdd_delta']:.4f}%`"
    )

    if not combo_df.empty:
        lines.extend(["", "## 组合层 Top 3 点检", ""])
        for _, row in combo_df.iterrows():
            lines.append(
                f"- `{row['variant']}`: 年化 `{row['annual']:.4f}%` / 最大回撤 `{row['max_dd']:.4f}%` / "
                f"相对组合基线年化变化 `{row['annual_delta']:.4f}%` / 回撤变化 `{row['max_dd_delta']:.4f}%`"
            )
    if not combo_window_df.empty:
        lines.extend(["", "## 组合层分窗口", ""])
        for _, row in combo_window_df.iterrows():
            lines.append(
                f"- `{row['variant']} {row['window']}`: 年化 `{row['annual']:.4f}%` / 最大回撤 `{row['max_dd']:.4f}%` / "
                f"相对窗口基线年化变化 `{row['annual_delta']:.4f}%` / 回撤变化 `{row['max_dd_delta']:.4f}%`"
            )

    SUMMARY_FINE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Fine scan and robustness study for Sub-A cash switch overlay.")
    parser.add_argument("--cn-csv", default=str(CN_CSV))
    parser.add_argument("--us-csv", default=str(US_CSV))
    parser.add_argument("--decays", nargs="*", type=float, default=[0.45, 0.475, 0.50, 0.525, 0.55, 0.575, 0.60, 0.625, 0.65, 0.675, 0.70])
    parser.add_argument("--recovers", nargs="*", type=float, default=[0.65, 0.675, 0.70, 0.725, 0.75, 0.775, 0.80, 0.825, 0.85, 0.875, 0.90, 0.925, 0.95])
    parser.add_argument("--rolling-step", type=int, default=21)
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()

    mod = _load_module(BASE_SCRIPT, "suba_decay_cash_robustness_mod")
    cn_close, cn_dk_close = _load_local_cn_data(mod, Path(args.cn_csv))
    us_df = _load_local_us_data(Path(args.us_csv))
    cn_result = mod.run_cn_strategy(cn_close.copy(), mod.CN_EQUITY_CODES)
    bias_df = _build_bias_df(mod, cn_close, mod.CN_EQUITY_CODES + [mod.CN_BOND_CODE])
    active_score = _extract_active_bias_score(cn_result, bias_df).reindex(cn_result.index)

    baseline_row = _evaluate_result(mod, "baseline_no_overlay", cn_result)
    compare_rows = [baseline_row]
    variants = {"baseline_no_overlay": cn_result.copy()}

    for decay, recover in _build_grid(args.decays, args.recovers):
        variant = apply_suba_decay_switch_overlay(
            cn_result,
            close_df=cn_close,
            active_score=active_score,
            stock_codes=list(mod.CN_EQUITY_CODES),
            defense_asset="cash",
            decay_ratio_threshold=decay,
            recovery_ratio_threshold=recover,
            commission=float(getattr(mod, "CN_COMMISSION", 0.0)),
            rf_daily=float(getattr(mod, "CN_RF_DAILY", 0.0)),
            target_vol=float(getattr(mod, "CN_TARGET_VOL", 0.20)),
            vol_window=int(getattr(mod, "CN_VOL_WINDOW", 60)),
            trading_days=int(getattr(mod, "CN_TRADING_DAYS", 244)),
            min_lev=float(getattr(mod, "CN_MIN_LEV", 0.1)),
            max_lev=float(getattr(mod, "CN_MAX_LEV", 1.5)),
            scale_threshold=float(getattr(mod, "CN_SCALE_THRESHOLD", 0.0)),
        )
        name = f"switch_cash_decay{int(round(decay * 1000))}_rec{int(round(recover * 1000))}"
        variants[name] = variant
        row = _evaluate_result(mod, name, variant, meta=variant.attrs.get("suba_decay_switch_overlay", {}))
        row["decay_ratio_threshold"] = decay
        row["recovery_ratio_threshold"] = recover
        compare_rows.append(row)

    compare_df = pd.DataFrame(compare_rows)
    baseline = compare_df.loc[compare_df["variant"] == "baseline_no_overlay"].iloc[0]
    compare_df["annual_delta"] = compare_df["annual"] - float(baseline["annual"])
    compare_df["max_dd_delta"] = compare_df["max_dd"] - float(baseline["max_dd"])
    compare_df["sharpe_delta"] = compare_df["sharpe"] - float(baseline["sharpe"])
    compare_df["calmar_delta"] = compare_df["calmar"] - float(baseline["calmar"])
    compare_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    window_rows = []
    for name, variant in variants.items():
        window_rows.extend(_window_metrics(mod, name, variant, [("1Y", 252), ("3Y", 756), ("5Y", 1260)]))
    window_df = pd.DataFrame(window_rows)
    score_df = _build_window_score_df(compare_df, window_df)
    score_df.to_csv(WINDOW_SCORE_CSV, index=False, encoding="utf-8-sig")

    top_variants = score_df.head(args.top_k)["variant"].tolist()
    longitudinal_rows = []
    for name in top_variants:
        for label, days in [("rolling_1Y", 252), ("rolling_3Y", 756)]:
            comp = _rolling_compare(mod, variants[name], variants["baseline_no_overlay"], days, args.rolling_step)
            longitudinal_rows.append(
                {
                    "variant": name,
                    "window": label,
                    "sample_count": int(len(comp)),
                    "better_annual_ratio": float(comp["better_annual"].mean()) if len(comp) else None,
                    "better_maxdd_ratio": float(comp["better_maxdd"].mean()) if len(comp) else None,
                    "better_both_ratio": float(comp["better_both"].mean()) if len(comp) else None,
                    "avg_annual_delta": float(comp["annual_delta"].mean()) if len(comp) else None,
                    "avg_maxdd_delta": float(comp["max_dd_delta"].mean()) if len(comp) else None,
                    "avg_calmar_delta": float(comp["calmar_delta"].mean()) if len(comp) else None,
                }
            )
    longitudinal_df = pd.DataFrame(longitudinal_rows).sort_values(
        ["better_both_ratio", "avg_calmar_delta"], ascending=[False, False]
    )
    longitudinal_df.to_csv(LONGITUDINAL_CSV, index=False, encoding="utf-8-sig")

    horizontal_df = _build_horizontal_robustness(score_df)
    horizontal_df.to_csv(HORIZONTAL_CSV, index=False, encoding="utf-8-sig")

    bot = mod.CombinedStrategyV65()
    _, dk_result, us_rot_result, _, prod_sig_a, prod_sig_b, _, _ = bot._run_strategies(
        cn_close.copy(), cn_dk_close.copy(), us_df.copy(), us_df.copy()
    )
    subc_daily_ret = mod._get_subc_daily_ret(us_df.copy(), prod_sig_a, prod_sig_b=prod_sig_b)
    base_combo = _combined_metrics(mod, variants["baseline_no_overlay"], dk_result, us_rot_result, subc_daily_ret)
    combo_rows = [
        {
            "variant": "baseline_combo",
            "annual": base_combo["annual"],
            "max_dd": base_combo["max_dd"],
            "annual_delta": 0.0,
            "max_dd_delta": 0.0,
        }
    ]
    combo_window_rows = []
    combo_variants = {"baseline_combo": variants["baseline_no_overlay"]}
    for name in top_variants[:3]:
        combo = _combined_metrics(mod, variants[name], dk_result, us_rot_result, subc_daily_ret)
        combo_rows.append(
            {
                "variant": f"{name}_combo",
                "annual": combo["annual"],
                "max_dd": combo["max_dd"],
                "annual_delta": combo["annual"] - base_combo["annual"],
                "max_dd_delta": combo["max_dd"] - base_combo["max_dd"],
            }
        )
        combo_variants[f"{name}_combo"] = variants[name]
    combo_df = pd.DataFrame(combo_rows)
    combo_df.to_csv(COMBO_TOP3_CSV, index=False, encoding="utf-8-sig")

    def _combo_return_series(cn_variant):
        cn_ret = cn_variant["return"].dropna()
        dk_ret = dk_result["return"].dropna()
        us_ret = us_rot_result["return"].dropna()
        subc_ret = subc_daily_ret.dropna()
        nav_series = {}
        if len(cn_ret) > 1:
            nav = (1 + cn_ret).cumprod()
            nav_series["Sub-A"] = nav / nav.iloc[0]
        if len(dk_ret) > 1:
            nav = (1 + dk_ret).cumprod()
            nav_series["Sub-A-DK"] = nav / nav.iloc[0]
        if len(us_ret) > 1:
            nav = (1 + us_ret).cumprod()
            nav_series["Sub-B"] = nav / nav.iloc[0]
        if len(subc_ret) > 1:
            nav = (1 + subc_ret).cumprod()
            nav_series["Sub-C"] = nav / nav.iloc[0]
        all_dates = sorted(set().union(*(s.index for s in nav_series.values())))
        nav_df = pd.DataFrame({k: s.reindex(pd.DatetimeIndex(all_dates)).ffill() for k, s in nav_series.items()})
        weight_df = nav_df.notna().astype(float)
        for col in weight_df.columns:
            weight_df[col] *= mod.COMBINED_WEIGHTS.get(col, 0)
        weight_sum = weight_df.sum(axis=1).replace(0, pd.NA)
        weight_df = weight_df.div(weight_sum, axis=0)
        nav_df = nav_df.fillna(0.0)
        nav_comb = (nav_df * weight_df).sum(axis=1)
        nav_comb = nav_comb / nav_comb.iloc[0]
        return nav_comb.pct_change().dropna()

    combo_window_rows = []
    combo_baseline_windows = {}
    for label, days in [("1Y", 252), ("3Y", 756), ("5Y", 1260)]:
        base_ret = _combo_return_series(combo_variants["baseline_combo"])
        base_win = base_ret.iloc[-days:] if len(base_ret) > days else base_ret
        base_metrics = mod.calc_daily_metrics(base_win, mod.CN_RF_DAILY, mod.CN_TRADING_DAYS)
        combo_baseline_windows[label] = base_metrics
        for variant_name, variant_df in combo_variants.items():
            cur_ret = _combo_return_series(variant_df)
            cur_win = cur_ret.iloc[-days:] if len(cur_ret) > days else cur_ret
            cur_metrics = mod.calc_daily_metrics(cur_win, mod.CN_RF_DAILY, mod.CN_TRADING_DAYS)
            combo_window_rows.append(
                {
                    "variant": variant_name,
                    "window": label,
                    "annual": cur_metrics["annual"],
                    "max_dd": cur_metrics["max_dd"],
                    "sharpe": cur_metrics["sharpe"],
                    "calmar": cur_metrics["calmar"],
                    "annual_delta": cur_metrics["annual"] - base_metrics["annual"],
                    "max_dd_delta": cur_metrics["max_dd"] - base_metrics["max_dd"],
                }
            )
    combo_window_df = pd.DataFrame(combo_window_rows)
    combo_window_df.to_csv(COMBO_WINDOW_CSV, index=False, encoding="utf-8-sig")

    sample_start = cn_result.index[0].strftime("%Y-%m-%d")
    sample_end = cn_result.index[-1].strftime("%Y-%m-%d")
    _write_summary(baseline, score_df, longitudinal_df, horizontal_df, combo_df, combo_window_df, sample_start, sample_end)

    print(score_df.head(8).to_string(index=False))
    print(f"\nSaved: {OUTPUT_CSV}")
    print(f"Saved window scores: {WINDOW_SCORE_CSV}")
    print(f"Saved longitudinal robustness: {LONGITUDINAL_CSV}")
    print(f"Saved horizontal robustness: {HORIZONTAL_CSV}")
    print(f"Saved combo top3: {COMBO_TOP3_CSV}")
    print(f"Saved combo windows: {COMBO_WINDOW_CSV}")
    print(f"Saved summary: {SUMMARY_FINE_MD}")


if __name__ == "__main__":
    main()

import argparse
from pathlib import Path

import pandas as pd

from analyze_subb_asset_peak_decay_overlay import (
    BASE_SCRIPT,
    LOCAL_US_CSV,
    _baseline_subb_result,
    _evaluate_result,
    _evaluate_windows,
    _load_local_us_rotation_data,
    _load_module,
    apply_subb_asset_peak_decay_overlay,
)


HERE = Path(__file__).resolve().parent
SCAN_CSV = HERE / "subb_asset_peak_decay_scan_results.csv"
FINE_SCAN_CSV = HERE / "subb_asset_peak_decay_low_loss_fine_scan.csv"
LONGITUDINAL_CSV = HERE / "subb_asset_peak_decay_low_loss_longitudinal.csv"
HORIZONTAL_CSV = HERE / "subb_asset_peak_decay_low_loss_horizontal.csv"
SUMMARY_MD = HERE / "低损失鲁棒性测试_2026-04-20.md"


ANNUAL_LOSS_LIMIT = -1.0


def _pick_candidate(compare_df: pd.DataFrame) -> pd.Series:
    baseline = compare_df.loc[compare_df["variant"] == "baseline_no_overlay"].iloc[0]
    non = compare_df.loc[compare_df["variant"] != "baseline_no_overlay"].copy()
    non["annual_delta"] = non["annual"] - float(baseline["annual"])
    non["max_dd_delta"] = non["max_dd"] - float(baseline["max_dd"])
    pool = non.loc[(non["annual_delta"] >= ANNUAL_LOSS_LIMIT) & (non["max_dd_delta"] > 0)].copy()
    if pool.empty:
        raise RuntimeError("No candidate satisfies annual loss <= 1pt and improved max drawdown.")
    pool["calmar_ok"] = pool["calmar"] >= float(baseline["calmar"])
    return pool.sort_values(["calmar_ok", "max_dd_delta", "annual_delta", "calmar"], ascending=[False, False, False, False]).iloc[0]


def _build_local_grid(center_decay: float, center_recover: float):
    decays = sorted({round(x, 4) for x in [center_decay - 0.10, center_decay - 0.05, center_decay, center_decay + 0.05, center_decay + 0.10] if 0.05 <= x <= 0.90})
    recovers = sorted({round(x, 4) for x in [center_recover - 0.10, center_recover - 0.05, center_recover, center_recover + 0.05, center_recover + 0.10, center_recover + 0.15] if 0.10 <= x <= 0.95})
    params = []
    for decay in decays:
        for recover in recovers:
            if recover <= decay:
                continue
            params.append((float(decay), float(recover)))
    return params


def _rolling_compare(mod, variant_df: pd.DataFrame, baseline_df: pd.DataFrame, window_days: int, step_days: int):
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
        var_m = mod.calc_daily_metrics(var_win, 0.0, mod.US_TRADING_DAYS)
        base_m = mod.calc_daily_metrics(base_win, 0.0, mod.US_TRADING_DAYS)
        annual_delta = var_m["annual"] - base_m["annual"]
        max_dd_delta = var_m["max_dd"] - base_m["max_dd"]
        rows.append(
            {
                "start": win_idx[0].strftime("%Y-%m-%d"),
                "end": win_idx[-1].strftime("%Y-%m-%d"),
                "annual_delta": annual_delta,
                "max_dd_delta": max_dd_delta,
                "calmar_delta": var_m["calmar"] - base_m["calmar"],
                "low_loss": annual_delta >= ANNUAL_LOSS_LIMIT,
                "better_maxdd": max_dd_delta > 0,
                "balanced_pass": (annual_delta >= ANNUAL_LOSS_LIMIT) and (max_dd_delta > 0),
            }
        )
    return pd.DataFrame(rows)


def _build_horizontal_robustness(compare_df: pd.DataFrame, center_decay: float, center_recover: float):
    baseline = compare_df.loc[compare_df["variant"] == "baseline_no_overlay"].iloc[0]
    non = compare_df.loc[compare_df["variant"] != "baseline_no_overlay"].copy()
    non["annual_delta"] = non["annual"] - float(baseline["annual"])
    non["max_dd_delta"] = non["max_dd"] - float(baseline["max_dd"])

    neigh = non.loc[
        non["decay_ratio_threshold"].between(center_decay - 0.0501, center_decay + 0.0501)
        & non["recovery_ratio_threshold"].between(center_recover - 0.0501, center_recover + 0.0501)
    ].copy()
    rows = []
    for _, row in neigh.iterrows():
        local = neigh.loc[
            (neigh["variant"] != row["variant"])
            & neigh["decay_ratio_threshold"].between(float(row["decay_ratio_threshold"]) - 0.0501, float(row["decay_ratio_threshold"]) + 0.0501)
            & neigh["recovery_ratio_threshold"].between(float(row["recovery_ratio_threshold"]) - 0.0501, float(row["recovery_ratio_threshold"]) + 0.0501)
        ].copy()
        rows.append(
            {
                "variant": row["variant"],
                "decay_ratio_threshold": row["decay_ratio_threshold"],
                "recovery_ratio_threshold": row["recovery_ratio_threshold"],
                "annual_delta": row["annual_delta"],
                "max_dd_delta": row["max_dd_delta"],
                "neighbor_count": int(len(local)),
                "neighbor_low_loss_ratio": float((local["annual_delta"] >= ANNUAL_LOSS_LIMIT).mean()) if len(local) else None,
                "neighbor_better_maxdd_ratio": float((local["max_dd_delta"] > 0).mean()) if len(local) else None,
                "neighbor_balanced_pass_ratio": float(((local["annual_delta"] >= ANNUAL_LOSS_LIMIT) & (local["max_dd_delta"] > 0)).mean()) if len(local) else None,
                "neighbor_avg_annual_delta": float(local["annual_delta"].mean()) if len(local) else None,
                "neighbor_avg_maxdd_delta": float(local["max_dd_delta"].mean()) if len(local) else None,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["neighbor_balanced_pass_ratio", "neighbor_avg_maxdd_delta", "annual_delta"],
        ascending=[False, False, False],
        na_position="last",
    )


def _write_summary(candidate, baseline, fine_df, longitudinal_df, horizontal_df, sample_start, sample_end):
    top_h = horizontal_df.loc[horizontal_df["variant"] == candidate["variant"]].iloc[0]
    lines = [
        "# 策略B单标的Overlay低损失鲁棒性测试",
        "",
        f"- 基线脚本: `{BASE_SCRIPT.name}`",
        f"- 数据文件: `{LOCAL_US_CSV.name}`",
        f"- 样本区间: `{sample_start} -> {sample_end}`",
        f"- 候选选择规则: 先筛出 `年化损失不超过 {abs(ANNUAL_LOSS_LIMIT):.1f} 个点` 且 `回撤改善为正` 的参数，再从中选回撤改善最大的一组。",
        f"- 选中候选: `{candidate['variant']}` = `decay={candidate['decay_ratio_threshold']:.0%} / recover={candidate['recovery_ratio_threshold']:.0%} / scale={candidate['derisk_scale']:.2f}`",
        f"- 基线: 年化 `{baseline['annual']:.4f}%` / 最大回撤 `{baseline['max_dd']:.4f}%`",
        f"- 候选: 年化 `{candidate['annual']:.4f}%` / 最大回撤 `{candidate['max_dd']:.4f}%`",
        f"- 相对基线: 年化 `{candidate['annual_delta']:+.4f}%` / 回撤改善 `{candidate['max_dd_delta']:+.4f}%`",
        "",
        "## 横向邻域",
        "",
        f"- 邻域参数数: `{int(top_h['neighbor_count'])}`",
        f"- 邻域低损失占比: `{top_h['neighbor_low_loss_ratio']:.2%}`",
        f"- 邻域回撤改善占比: `{top_h['neighbor_better_maxdd_ratio']:.2%}`",
        f"- 邻域平衡通过率: `{top_h['neighbor_balanced_pass_ratio']:.2%}`",
        f"- 邻域平均年化变化: `{top_h['neighbor_avg_annual_delta']:+.4f}%`",
        f"- 邻域平均回撤变化: `{top_h['neighbor_avg_maxdd_delta']:+.4f}%`",
        "",
        "## 纵向滚动窗",
        "",
    ]
    for _, row in longitudinal_df.iterrows():
        lines.append(
            f"- `{row['window']}`: 低损失占比 `{row['low_loss_ratio']:.2%}` / 回撤改善占比 `{row['better_maxdd_ratio']:.2%}` / "
            f"平衡通过率 `{row['balanced_pass_ratio']:.2%}` / 平均年化变化 `{row['avg_annual_delta']:+.4f}%` / 平均回撤变化 `{row['avg_maxdd_delta']:+.4f}%`"
        )
    lines.extend(["", "## 局部细扫", ""])
    for _, row in fine_df.sort_values(["max_dd_delta", "annual_delta"], ascending=[False, False]).head(10).iterrows():
        lines.append(
            f"- `{row['variant']}`: 年化 `{row['annual']:.4f}%` / 最大回撤 `{row['max_dd']:.4f}%` / "
            f"年化变化 `{row['annual_delta']:+.4f}%` / 回撤变化 `{row['max_dd_delta']:+.4f}%`"
        )
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Low-loss robustness study for Sub-B asset overlay.")
    parser.add_argument("--csv", default=str(LOCAL_US_CSV))
    parser.add_argument("--rolling-step", type=int, default=21)
    args = parser.parse_args()

    coarse = pd.read_csv(SCAN_CSV)
    coarse_candidate = _pick_candidate(coarse)

    mod = _load_module(BASE_SCRIPT, "subb_asset_peak_decay_low_loss_mod")
    us_rot_close = _load_local_us_rotation_data(mod, Path(args.csv))
    baseline_result = _baseline_subb_result(mod, us_rot_close)
    baseline = _evaluate_result(mod, "baseline_no_overlay", baseline_result)

    local_grid = _build_local_grid(float(coarse_candidate["decay_ratio_threshold"]), float(coarse_candidate["recovery_ratio_threshold"]))
    compare_rows = [baseline]
    variants = {"baseline_no_overlay": baseline_result}

    for decay, recover in local_grid:
        variant = apply_subb_asset_peak_decay_overlay(
            mod,
            baseline_result,
            us_rot_close,
            decay_ratio_threshold=decay,
            recovery_ratio_threshold=recover,
            derisk_scale=float(coarse_candidate["derisk_scale"]),
        )
        name = f"asset_decay{int(round(decay * 100))}_rec{int(round(recover * 100))}_x{float(coarse_candidate['derisk_scale']):.2f}".replace(".", "p")
        variants[name] = variant
        row = _evaluate_result(mod, name, variant, meta=variant.attrs.get("asset_peak_decay_overlay", {}))
        row["decay_ratio_threshold"] = decay
        row["recovery_ratio_threshold"] = recover
        compare_rows.append(row)

    compare_df = pd.DataFrame(compare_rows)
    compare_df["annual_delta"] = compare_df["annual"] - float(baseline["annual"])
    compare_df["max_dd_delta"] = compare_df["max_dd"] - float(baseline["max_dd"])
    compare_df.to_csv(FINE_SCAN_CSV, index=False, encoding="utf-8-sig")

    refined_candidate = _pick_candidate(compare_df)
    selected_name = refined_candidate["variant"]
    if selected_name not in variants:
        selected_name = f"asset_decay{int(round(float(refined_candidate['decay_ratio_threshold']) * 100))}_rec{int(round(float(refined_candidate['recovery_ratio_threshold']) * 100))}_x{float(refined_candidate['derisk_scale']):.2f}".replace(".", "p")

    longitudinal_rows = []
    for label, days in [("rolling_1Y", 252), ("rolling_3Y", 756)]:
        comp = _rolling_compare(mod, variants[selected_name], variants["baseline_no_overlay"], days, args.rolling_step)
        longitudinal_rows.append(
            {
                "variant": selected_name,
                "window": label,
                "sample_count": int(len(comp)),
                "low_loss_ratio": float(comp["low_loss"].mean()) if len(comp) else None,
                "better_maxdd_ratio": float(comp["better_maxdd"].mean()) if len(comp) else None,
                "balanced_pass_ratio": float(comp["balanced_pass"].mean()) if len(comp) else None,
                "avg_annual_delta": float(comp["annual_delta"].mean()) if len(comp) else None,
                "avg_maxdd_delta": float(comp["max_dd_delta"].mean()) if len(comp) else None,
            }
        )
    longitudinal_df = pd.DataFrame(longitudinal_rows)
    longitudinal_df.to_csv(LONGITUDINAL_CSV, index=False, encoding="utf-8-sig")

    horizontal_df = _build_horizontal_robustness(compare_df, float(refined_candidate["decay_ratio_threshold"]), float(refined_candidate["recovery_ratio_threshold"]))
    horizontal_df.to_csv(HORIZONTAL_CSV, index=False, encoding="utf-8-sig")

    sample_start = baseline_result.index[0].strftime("%Y-%m-%d")
    sample_end = baseline_result.index[-1].strftime("%Y-%m-%d")
    selected_row = compare_df.loc[compare_df["variant"] == selected_name].iloc[0]
    _write_summary(selected_row, baseline, compare_df[compare_df["variant"] != "baseline_no_overlay"], longitudinal_df, horizontal_df, sample_start, sample_end)

    print(compare_df.sort_values(["max_dd_delta", "annual_delta"], ascending=[False, False]).head(12).to_string(index=False))
    print(f"\nSaved fine scan: {FINE_SCAN_CSV}")
    print(f"Saved longitudinal: {LONGITUDINAL_CSV}")
    print(f"Saved horizontal: {HORIZONTAL_CSV}")
    print(f"Saved summary: {SUMMARY_MD}")


if __name__ == "__main__":
    main()

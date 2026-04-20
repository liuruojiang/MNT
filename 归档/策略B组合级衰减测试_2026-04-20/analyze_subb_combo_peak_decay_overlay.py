import argparse
import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


BASE_SCRIPT = ROOT / "mnt_bot V 6.8 plus.py"
LOCAL_US_CSV = ROOT / "mnt_strategy_data_us.csv"
OUTPUT_CSV = HERE / "subb_combo_peak_decay_scan_results.csv"
TOP_CSV = HERE / "subb_combo_peak_decay_top.csv"
WINDOW_CSV = HERE / "subb_combo_peak_decay_window_compare.csv"
SUMMARY_MD = HERE / "测试记录_2026-04-20.md"


class _DummyPoe:
    class BotError(Exception):
        pass

    default_chat = ""
    query = types.SimpleNamespace(text="", attachments=[])

    @staticmethod
    def update_settings(*args, **kwargs):
        return None

    @staticmethod
    def start_message():
        raise RuntimeError("poe.start_message is unavailable in offline scan mode")

    @staticmethod
    def call(*args, **kwargs):
        raise RuntimeError("poe.call is unavailable in offline scan mode")


class _DummySettingsResponse(dict):
    def __init__(self, *args, **kwargs):
        super().__init__()


class _SilentMessage:
    def write(self, *_args, **_kwargs):
        return None


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)

    poe_stub = types.ModuleType("fastapi_poe")
    poe_stub.BotError = _DummyPoe.BotError
    poe_stub.default_chat = _DummyPoe.default_chat
    poe_stub.query = _DummyPoe.query
    poe_stub.update_settings = _DummyPoe.update_settings
    poe_stub.start_message = _DummyPoe.start_message
    poe_stub.call = _DummyPoe.call

    poe_types_stub = types.ModuleType("fastapi_poe.types")
    poe_types_stub.SettingsResponse = _DummySettingsResponse

    old_poe = sys.modules.get("fastapi_poe")
    old_poe_types = sys.modules.get("fastapi_poe.types")
    sys.modules["fastapi_poe"] = poe_stub
    sys.modules["fastapi_poe.types"] = poe_types_stub
    try:
        spec.loader.exec_module(module)
    finally:
        if old_poe is None:
            sys.modules.pop("fastapi_poe", None)
        else:
            sys.modules["fastapi_poe"] = old_poe
        if old_poe_types is None:
            sys.modules.pop("fastapi_poe.types", None)
        else:
            sys.modules["fastapi_poe.types"] = old_poe_types
    return module


def _fetch_formal_subb_inputs(mod):
    bot = mod.CombinedStrategyV68()
    _, _, us_rot_close, _ = bot._fetch_data(_SilentMessage(), include_us_live_snapshot=False)
    return bot, us_rot_close


def _baseline_subb_result(mod, bot, us_rot_close: pd.DataFrame) -> pd.DataFrame:
    result = mod.run_us_rotation(
        us_rot_close,
        mod.US_ROT_POOL,
        btc_ticker=mod.US_ROT_BTC_TICKER,
        btc_start=mod.US_ROT_BTC_START,
        btc_max_w=mod.US_ROT_BTC_MAX_W,
        us_open=getattr(bot, "_us_open", None),
    )
    if getattr(mod, "US_ROT_VOLREG_ENABLED", False) and "SPY" in us_rot_close.columns:
        result = mod.apply_vol_regime_overlay(result, us_rot_close["SPY"])
    return result


def _extract_combo_overlay_state(mod, base_result: pd.DataFrame, us_rot_close: pd.DataFrame):
    momentum = us_rot_close.div(us_rot_close.shift(mod.US_ROT_LB)).sub(1)
    bil_ret = us_rot_close["BIL"].pct_change().reindex(base_result.index).fillna(0.0)
    risky_assets = [asset for asset in mod.US_ROT_POOL if f"w_{asset}" in base_result.columns]

    combo_scores = []
    risky_weights = []
    signatures = []
    for dt, row in base_result.iterrows():
        if bool(row.get("volreg_cash", False)):
            combo_scores.append(float("nan"))
            risky_weights.append(0.0)
            signatures.append("CASH")
            continue

        weight_map = {asset: float(row.get(f"w_{asset}", 0.0)) for asset in risky_assets}
        active = [(asset, w) for asset, w in weight_map.items() if w > 1e-10]
        risky_weight = sum(w for _, w in active)
        if risky_weight <= 1e-12:
            combo_scores.append(float("nan"))
            risky_weights.append(0.0)
            signatures.append("CASH")
            continue

        score_num = 0.0
        score_den = 0.0
        active_names = []
        for asset, w in active:
            active_names.append(asset)
            raw = momentum.loc[dt, asset] if dt in momentum.index and asset in momentum.columns else float("nan")
            if pd.notna(raw):
                score_num += w * float(raw)
                score_den += w
        combo_score = float(score_num / score_den) if score_den > 1e-12 else float("nan")
        combo_scores.append(combo_score)
        risky_weights.append(float(risky_weight))
        signatures.append("|".join(sorted(active_names)))

    return (
        bil_ret.astype(float),
        pd.Series(combo_scores, index=base_result.index, dtype=float),
        pd.Series(risky_weights, index=base_result.index, dtype=float),
        pd.Series(signatures, index=base_result.index, dtype=str),
    )


def apply_subb_combo_peak_decay_overlay_from_state(
    base_result: pd.DataFrame,
    bil_ret: pd.Series,
    combo_score: pd.Series,
    risky_weight: pd.Series,
    basket_signature: pd.Series,
    decay_ratio_threshold: float,
    recovery_ratio_threshold: float,
    derisk_scale: float,
    commission: float = 0.0,
) -> pd.DataFrame:
    if not 0 < decay_ratio_threshold < 1:
        raise ValueError("decay_ratio_threshold must be in (0, 1).")
    if not decay_ratio_threshold < recovery_ratio_threshold <= 1:
        raise ValueError("recovery_ratio_threshold must be in (decay_ratio_threshold, 1].")
    if not 0 <= derisk_scale <= 1:
        raise ValueError("derisk_scale must be in [0, 1].")

    required = {"return", "w_BIL"}
    missing = required.difference(base_result.columns)
    if missing:
        raise KeyError(f"Missing required Sub-B columns: {sorted(missing)}")

    out = base_result.copy()
    base_ret = out["return"].fillna(0.0).astype(float)
    bil_ret = bil_ret.reindex(out.index).fillna(0.0).astype(float)
    combo_score = combo_score.reindex(out.index).astype(float)
    risky_weight = risky_weight.reindex(out.index).fillna(0.0).clip(lower=0.0, upper=1.0).astype(float)
    basket_signature = basket_signature.reindex(out.index).fillna("CASH").astype(str)

    final_ret = []
    overlay_scale = []
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
    prev_scale = 1.0

    for i, dt in enumerate(out.index):
        signature = basket_signature.iloc[i]
        prev_signature = basket_signature.iloc[i - 1] if i > 0 else None
        eligible = signature != "CASH" and float(risky_weight.iloc[i]) > 1e-12
        new_trade = i == 0 or signature != prev_signature

        if new_trade:
            trade_id += 1
            score_peak = None
            derisked_for_today = False
            waiting_for_new_peak = False
            rearm_peak = None

        cur_scale = derisk_scale if (derisked_for_today and eligible) else 1.0
        triggered_today = cur_scale < 0.999999 and prev_scale >= 0.999999
        recovered_today = cur_scale >= 0.999999 and prev_scale < 0.999999

        pre_cost_ret = cur_scale * float(base_ret.iloc[i]) + (1.0 - cur_scale) * float(bil_ret.iloc[i])
        delta_scale = abs(cur_scale - prev_scale)
        overlay_tc = 0.0
        if delta_scale > 1e-12:
            overlay_tc = 2.0 * commission * float(risky_weight.iloc[i]) * delta_scale
        realized_ret = (1.0 + pre_cost_ret) * (1.0 - overlay_tc) - 1.0

        cur_score = combo_score.iloc[i] if eligible else float("nan")
        if pd.notna(cur_score):
            cur_score = float(cur_score)
            score_peak = cur_score if score_peak is None else max(float(score_peak), cur_score)

        decay_ratio = None
        if score_peak is not None and score_peak > 1e-12 and pd.notna(cur_score):
            decay_ratio = float(cur_score) / float(score_peak)

        next_derisked = derisked_for_today
        next_waiting = waiting_for_new_peak
        next_rearm_peak = rearm_peak

        if (
            next_waiting
            and not recovered_today
            and next_rearm_peak is not None
            and score_peak is not None
            and score_peak > float(next_rearm_peak) + 1e-12
        ):
            next_waiting = False
            next_rearm_peak = None

        if eligible:
            if next_derisked:
                if decay_ratio is not None and decay_ratio >= recovery_ratio_threshold:
                    next_derisked = False
                    next_waiting = True
                    next_rearm_peak = cur_score
            elif not next_waiting and decay_ratio is not None and decay_ratio <= decay_ratio_threshold:
                next_derisked = True
        else:
            next_derisked = False
            next_waiting = False
            next_rearm_peak = None

        final_ret.append(float(realized_ret))
        overlay_scale.append(float(cur_scale))
        overlay_on.append(bool(cur_scale < 0.999999))
        overlay_triggered.append(bool(triggered_today))
        overlay_recovered.append(bool(recovered_today))
        trade_ids.append(int(trade_id))
        score_peaks.append(None if score_peak is None else float(score_peak))
        score_decay_ratios.append(None if decay_ratio is None else float(decay_ratio))
        waiting_flags.append(bool(next_waiting))

        derisked_for_today = next_derisked
        waiting_for_new_peak = next_waiting
        rearm_peak = next_rearm_peak
        prev_scale = cur_scale

    out["raw_return"] = base_ret
    out["bil_return_overlay"] = bil_ret
    out["combo_score_overlay"] = combo_score
    out["risky_weight_overlay"] = risky_weight
    out["basket_signature_overlay"] = basket_signature
    out["return"] = pd.Series(final_ret, index=out.index, dtype=float)
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["overlay_scale"] = pd.Series(overlay_scale, index=out.index, dtype=float)
    out["overlay_on"] = pd.Series(overlay_on, index=out.index, dtype=bool)
    out["overlay_triggered"] = pd.Series(overlay_triggered, index=out.index, dtype=bool)
    out["overlay_recovered"] = pd.Series(overlay_recovered, index=out.index, dtype=bool)
    out["trade_id"] = pd.Series(trade_ids, index=out.index, dtype="Int64")
    out["combo_score_peak_overlay"] = pd.Series(score_peaks, index=out.index, dtype=float)
    out["combo_score_decay_ratio_overlay"] = pd.Series(score_decay_ratios, index=out.index, dtype=float)
    out["waiting_for_new_peak"] = pd.Series(waiting_flags, index=out.index, dtype=bool)
    out.attrs["combo_peak_decay_overlay"] = {
        "decay_ratio_threshold": decay_ratio_threshold,
        "recovery_ratio_threshold": recovery_ratio_threshold,
        "derisk_scale": derisk_scale,
        "commission": commission,
        "overlay_days": int(out["overlay_on"].sum()),
        "overlay_ratio": float(out["overlay_on"].mean()),
        "trigger_count": int(out["overlay_triggered"].sum()),
        "recovery_count": int(out["overlay_recovered"].sum()),
        "avg_scale": float(out["overlay_scale"].mean()),
    }
    return out


def apply_subb_combo_peak_decay_overlay(
    mod,
    base_result: pd.DataFrame,
    us_rot_close: pd.DataFrame,
    decay_ratio_threshold: float,
    recovery_ratio_threshold: float,
    derisk_scale: float,
    commission: float | None = None,
) -> pd.DataFrame:
    bil_ret, combo_score, risky_weight, basket_signature = _extract_combo_overlay_state(mod, base_result, us_rot_close)
    return apply_subb_combo_peak_decay_overlay_from_state(
        base_result=base_result,
        bil_ret=bil_ret,
        combo_score=combo_score,
        risky_weight=risky_weight,
        basket_signature=basket_signature,
        decay_ratio_threshold=decay_ratio_threshold,
        recovery_ratio_threshold=recovery_ratio_threshold,
        derisk_scale=derisk_scale,
        commission=mod.US_ROT_COMMISSION if commission is None else commission,
    )


def _evaluate_result(mod, name: str, result: pd.DataFrame, meta: dict | None = None):
    ret = result["return"].dropna()
    metrics = mod.calc_daily_metrics(ret, 0.0, mod.US_TRADING_DAYS)
    rebalances = mod.extract_us_rot_rebalances(result)
    return {
        "variant": name,
        "decay_ratio_threshold": meta.get("decay_ratio_threshold") if meta else None,
        "recovery_ratio_threshold": meta.get("recovery_ratio_threshold") if meta else None,
        "derisk_scale": meta.get("derisk_scale") if meta else None,
        "annual": metrics["annual"],
        "vol": metrics["vol"],
        "sharpe": metrics["sharpe"],
        "max_dd": metrics["max_dd"],
        "calmar": metrics["calmar"],
        "total_return": metrics["total_return"],
        "monthly_win_rate": metrics["win_rate"],
        "rebalanced_days": len(rebalances),
        "signal_days": int(result["is_signal"].fillna(False).sum()) if "is_signal" in result.columns else None,
        "volreg_days": int(result["volreg_cash"].fillna(False).sum()) if "volreg_cash" in result.columns else 0,
        "overlay_days": meta.get("overlay_days", 0) if meta else 0,
        "overlay_ratio": meta.get("overlay_ratio", 0.0) if meta else 0.0,
        "trigger_count": meta.get("trigger_count", 0) if meta else 0,
        "recovery_count": meta.get("recovery_count", 0) if meta else 0,
        "avg_scale": meta.get("avg_scale", 1.0) if meta else 1.0,
    }


def _slice_trailing_years(ret: pd.Series, years: int) -> pd.Series:
    if ret.empty:
        return ret
    end = ret.index[-1]
    start = end - pd.DateOffset(years=years)
    win = ret.loc[ret.index >= start]
    return win if len(win) > 1 else ret


def _evaluate_windows(mod, name: str, result: pd.DataFrame, windows: list[tuple[str, int]]) -> list[dict]:
    ret = result["return"].dropna()
    rows = []
    for label, years in windows:
        win = _slice_trailing_years(ret, years)
        if len(win) < 2:
            continue
        metrics = mod.calc_daily_metrics(win, 0.0, mod.US_TRADING_DAYS)
        rows.append(
            {
                "variant": name,
                "window": label,
                "start": win.index[0].strftime("%Y-%m-%d"),
                "end": win.index[-1].strftime("%Y-%m-%d"),
                "days": len(win),
                "annual": metrics["annual"],
                "vol": metrics["vol"],
                "sharpe": metrics["sharpe"],
                "max_dd": metrics["max_dd"],
                "calmar": metrics["calmar"],
                "total_return": metrics["total_return"],
                "monthly_win_rate": metrics["win_rate"],
            }
        )
    return rows


def _build_param_grid(decay_ratio_grid, recovery_ratio_grid, derisk_scales):
    variants = []
    for decay_ratio_threshold in decay_ratio_grid:
        for recovery_ratio_threshold in recovery_ratio_grid:
            if recovery_ratio_threshold <= decay_ratio_threshold:
                continue
            for derisk_scale in derisk_scales:
                variants.append(
                    {
                        "decay_ratio_threshold": decay_ratio_threshold,
                        "recovery_ratio_threshold": recovery_ratio_threshold,
                        "derisk_scale": derisk_scale,
                    }
                )
    return variants


def _write_summary(compare_df: pd.DataFrame, window_df: pd.DataFrame, sample_start: str, sample_end: str):
    def fmt_pct(v: float) -> str:
        return f"{float(v):.4f}%"

    baseline = compare_df.loc[compare_df["variant"] == "baseline_no_overlay"].iloc[0]
    variants = compare_df.loc[compare_df["variant"] != "baseline_no_overlay"].copy()
    best_full = variants.sort_values(["calmar", "annual", "max_dd"], ascending=[False, False, False]).iloc[0]
    better_full = variants[(variants["annual"] > baseline["annual"]) & (variants["max_dd"] > baseline["max_dd"])]

    lines = [
        "# 策略B组合级动量衰减测试",
        "",
        f"- 基线脚本: `{BASE_SCRIPT.name}`",
        f"- 数据文件: `{LOCAL_US_CSV.name}`",
        f"- 样本区间: `{sample_start} -> {sample_end}`",
        "- 基线口径: `Sub-B` 正式 `6.8` 路径，包含 `VolReg`，不改正式代码。",
        "- Overlay口径: 当前Top3组合加权动量分数相对本轮peak衰减；触发后整体向 `BIL` 收缩；恢复后必须先创新高才可再次触发。",
        "",
        "## 全样本基线",
        "",
        f"- 年化 `{fmt_pct(baseline['annual'])}`",
        f"- 最大回撤 `{fmt_pct(baseline['max_dd'])}`",
        f"- Sharpe `{baseline['sharpe']:.4f}`",
        f"- Calmar `{baseline['calmar']:.4f}`",
        "",
        "## 当前最优候选",
        "",
        f"- 参数: `decay={best_full['decay_ratio_threshold']:.0%} / recover={best_full['recovery_ratio_threshold']:.0%} / scale={best_full['derisk_scale']:.2f}`",
        f"- 年化 `{fmt_pct(best_full['annual'])}`",
        f"- 最大回撤 `{fmt_pct(best_full['max_dd'])}`",
        f"- 相对基线年化增量 `{best_full['annual'] - baseline['annual']:+.4f}%`",
        f"- 相对基线回撤改善 `{best_full['max_dd'] - baseline['max_dd']:+.4f}%`",
        "",
        f"- 全样本双改善参数组数量: `{len(better_full)}`",
        "",
        "## 分窗口最优",
        "",
    ]

    for window in ["1Y", "3Y", "5Y"]:
        subset = window_df[window_df["window"] == window].copy()
        if subset.empty:
            continue
        base_win = subset[subset["variant"] == "baseline_no_overlay"]
        if base_win.empty:
            continue
        base_win = base_win.iloc[0]
        subset = subset[subset["variant"] != "baseline_no_overlay"]
        if subset.empty:
            continue
        best = subset.sort_values(["calmar", "annual", "max_dd"], ascending=[False, False, False]).iloc[0]
        dual = subset[(subset["annual"] > base_win["annual"]) & (subset["max_dd"] > base_win["max_dd"])]
        lines.extend(
            [
                f"### {window}",
                "",
                f"- 最优: `{best['variant']}`",
                f"- 年化 `{fmt_pct(best['annual'])}`，最大回撤 `{fmt_pct(best['max_dd'])}`，Calmar `{best['calmar']:.4f}`",
                f"- 相对窗口基线年化增量 `{best['annual'] - base_win['annual']:+.4f}%`，回撤改善 `{best['max_dd'] - base_win['max_dd']:+.4f}%`",
                f"- 双改善参数组数量: `{len(dual)}`",
                "",
            ]
        )

    SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Scan Sub-B combo peak-decay overlay on formal version data.")
    parser.add_argument("--output", default=str(OUTPUT_CSV), help="Full scan result csv path.")
    parser.add_argument("--top-output", default=str(TOP_CSV), help="Top-result csv path.")
    parser.add_argument("--window-output", default=str(WINDOW_CSV), help="Window compare csv path.")
    parser.add_argument(
        "--decay-grid",
        nargs="*",
        type=float,
        default=[0.30, 0.40, 0.50, 0.60, 0.70],
        help="Decay ratio thresholds.",
    )
    parser.add_argument(
        "--recovery-grid",
        nargs="*",
        type=float,
        default=[0.60, 0.70, 0.80, 0.90],
        help="Recovery ratio thresholds.",
    )
    parser.add_argument(
        "--derisk-scales",
        nargs="*",
        type=float,
        default=[0.0, 0.5],
        help="Overlay derisk scales.",
    )
    args = parser.parse_args()

    mod = _load_module(BASE_SCRIPT, "subb_combo_peak_decay_mod")
    bot, us_rot_close = _fetch_formal_subb_inputs(mod)
    base_result = _baseline_subb_result(mod, bot, us_rot_close)

    compare_rows = [_evaluate_result(mod, "baseline_no_overlay", base_result)]
    window_rows = _evaluate_windows(mod, "baseline_no_overlay", base_result, [("1Y", 1), ("3Y", 3), ("5Y", 5)])

    variants = _build_param_grid(args.decay_grid, args.recovery_grid, args.derisk_scales)
    for cfg in variants:
        name = (
            f"combo_decay{int(round(cfg['decay_ratio_threshold'] * 100))}"
            f"_rec{int(round(cfg['recovery_ratio_threshold'] * 100))}"
            f"_x{cfg['derisk_scale']:.2f}"
        ).replace(".", "p")
        result = apply_subb_combo_peak_decay_overlay(
            mod,
            base_result,
            us_rot_close,
            decay_ratio_threshold=cfg["decay_ratio_threshold"],
            recovery_ratio_threshold=cfg["recovery_ratio_threshold"],
            derisk_scale=cfg["derisk_scale"],
        )
        meta = result.attrs.get("combo_peak_decay_overlay", {})
        compare_rows.append(_evaluate_result(mod, name, result, meta=meta))
        window_rows.extend(_evaluate_windows(mod, name, result, [("1Y", 1), ("3Y", 3), ("5Y", 5)]))

    compare_df = pd.DataFrame(compare_rows)
    compare_df = compare_df.sort_values(["calmar", "annual", "max_dd"], ascending=[False, False, False]).reset_index(drop=True)
    compare_df.to_csv(Path(args.output), index=False, encoding="utf-8-sig")

    baseline = compare_df.loc[compare_df["variant"] == "baseline_no_overlay"].iloc[0]
    non = compare_df.loc[compare_df["variant"] != "baseline_no_overlay"].copy()
    non["annual_delta_vs_base"] = non["annual"] - baseline["annual"]
    non["maxdd_delta_vs_base"] = non["max_dd"] - baseline["max_dd"]
    top_df = non.sort_values(
        ["calmar", "annual_delta_vs_base", "maxdd_delta_vs_base"],
        ascending=[False, False, False],
    ).head(12)
    top_df.to_csv(Path(args.top_output), index=False, encoding="utf-8-sig")

    window_df = pd.DataFrame(window_rows)
    if not window_df.empty:
        window_df.to_csv(Path(args.window_output), index=False, encoding="utf-8-sig")
    else:
        Path(args.window_output).write_text("", encoding="utf-8")

    sample_start = base_result.index.min().strftime("%Y-%m-%d")
    sample_end = base_result.index.max().strftime("%Y-%m-%d")
    _write_summary(compare_df, window_df, sample_start, sample_end)

    display_cols = [
        "variant",
        "decay_ratio_threshold",
        "recovery_ratio_threshold",
        "derisk_scale",
        "annual",
        "max_dd",
        "sharpe",
        "calmar",
        "overlay_ratio",
        "trigger_count",
    ]
    print(compare_df[display_cols].head(12).to_string(index=False))
    print(f"\nSaved: {args.output}")
    print(f"Saved: {args.top_output}")
    print(f"Saved: {args.window_output}")
    print(f"Saved: {SUMMARY_MD}")


if __name__ == "__main__":
    main()

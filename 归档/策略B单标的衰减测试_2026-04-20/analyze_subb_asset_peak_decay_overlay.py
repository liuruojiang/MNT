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
OUTPUT_CSV = HERE / "subb_asset_peak_decay_scan_results.csv"
TOP_CSV = HERE / "subb_asset_peak_decay_top.csv"
WINDOW_CSV = HERE / "subb_asset_peak_decay_window_compare.csv"
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


def reconstruct_effective_weights(mod, base_result: pd.DataFrame) -> pd.DataFrame:
    assets = list(mod.US_ROT_POOL) + ["BIL"]
    holdings = {"BIL": 1.0}
    pending_act = None
    rows = []

    for _, row in base_result.iterrows():
        effective = {asset: float(holdings.get(asset, 0.0)) for asset in assets}
        if bool(row.get("volreg_cash", False)):
            effective = {asset: 0.0 for asset in assets}
            effective["BIL"] = 1.0
        rows.append(effective)

        if pending_act is not None:
            holdings = dict(pending_act)
            pending_act = None

        if bool(row.get("rebalanced", False)):
            pending_act = {asset: float(row.get(f"w_{asset}", 0.0)) for asset in assets}

    out = pd.DataFrame(rows, index=base_result.index).fillna(0.0)
    if "BIL" not in out.columns:
        out["BIL"] = 0.0
    out["BIL"] = out["BIL"] + (1.0 - out.sum(axis=1))
    return out.clip(lower=0.0)


def _extract_asset_overlay_state(mod, base_result: pd.DataFrame, us_rot_close: pd.DataFrame):
    effective_weights = reconstruct_effective_weights(mod, base_result)
    asset_returns = us_rot_close.pct_change().reindex(base_result.index)
    if "BIL" not in asset_returns.columns:
        raise KeyError("BIL column is required for Sub-B asset overlay.")
    momentum = us_rot_close.div(us_rot_close.shift(mod.US_ROT_LB)).sub(1)
    active_score = momentum.reindex(base_result.index)[[asset for asset in mod.US_ROT_POOL if asset in momentum.columns]]

    if "volreg_cash" in base_result.columns:
        mask = base_result["volreg_cash"].fillna(False)
        effective_weights.loc[mask, :] = 0.0
        effective_weights.loc[mask, "BIL"] = 1.0
        active_score.loc[mask, :] = float("nan")

    return asset_returns, effective_weights, active_score


def _default_overlay_assets(mod) -> list[str]:
    exempt = {"BIL"}
    for live, cfg in getattr(mod, "US_ROT_ASSETS", {}).items():
        label = str(cfg.get("label", ""))
        proxy = cfg.get("proxy", live)
        lower = label.lower()
        if "treasury" in lower or "bond" in lower or "国债" in label:
            exempt.add(live)
            exempt.add(proxy)
    return [asset for asset in mod.US_ROT_POOL if asset not in exempt]


def apply_subb_asset_peak_decay_overlay_from_state(
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

    for asset in risky_assets:
        out[f"overlay_scale_{asset}"] = 1.0
        out[f"overlay_triggered_{asset}"] = False
        out[f"overlay_recovered_{asset}"] = False
        out[f"waiting_for_new_peak_{asset}"] = False
        out[f"score_peak_overlay_{asset}"] = float("nan")
        out[f"score_decay_ratio_overlay_{asset}"] = float("nan")

    for i, dt in enumerate(out.index):
        bil_weight = float(effective_weights.loc[dt, "BIL"]) if "BIL" in effective_weights.columns else 0.0
        bil_ret = float(asset_returns.loc[dt, "BIL"]) if pd.notna(asset_returns.loc[dt, "BIL"]) else 0.0
        removed_weight = 0.0
        risky_return = 0.0
        cost = 0.0
        asset_count = 0

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
            asset_ret = float(asset_returns.loc[dt, asset]) if asset in asset_returns.columns and pd.notna(asset_returns.loc[dt, asset]) else 0.0
            risky_return += base_weight * cur_scale * asset_ret
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

        bil_total_weight = bil_weight + removed_weight
        day_ret = risky_return + bil_total_weight * bil_ret
        day_ret = (1.0 + day_ret) * (1.0 - cost) - 1.0
        final_ret.append(float(day_ret))
        overlay_asset_count.append(int(asset_count))
        overlay_weight_removed.append(float(removed_weight))

    out["return"] = pd.Series(final_ret, index=out.index, dtype=float)
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["overlay_asset_count"] = pd.Series(overlay_asset_count, index=out.index, dtype=int)
    out["overlay_weight_removed"] = pd.Series(overlay_weight_removed, index=out.index, dtype=float)
    out["effective_bil_weight_overlay"] = effective_weights["BIL"].astype(float) + out["overlay_weight_removed"]
    out.attrs["asset_peak_decay_overlay"] = {
        "decay_ratio_threshold": decay_ratio_threshold,
        "recovery_ratio_threshold": recovery_ratio_threshold,
        "derisk_scale": derisk_scale,
        "commission": commission,
        "overlay_assets": sorted(governed_assets),
        "overlay_days": int((out["overlay_asset_count"] > 0).sum()),
        "overlay_ratio": float((out["overlay_asset_count"] > 0).mean()),
        "overlay_asset_days": int(out["overlay_asset_count"].sum()),
        "avg_removed_weight": float(out["overlay_weight_removed"].mean()),
        "trigger_count": int(sum(int(out[f"overlay_triggered_{asset}"].sum()) for asset in governed_assets)),
        "recovery_count": int(sum(int(out[f"overlay_recovered_{asset}"].sum()) for asset in governed_assets)),
    }
    return out


def apply_subb_asset_peak_decay_overlay(
    mod,
    base_result: pd.DataFrame,
    us_rot_close: pd.DataFrame,
    decay_ratio_threshold: float,
    recovery_ratio_threshold: float,
    derisk_scale: float,
    commission: float | None = None,
) -> pd.DataFrame:
    asset_returns, effective_weights, active_score = _extract_asset_overlay_state(mod, base_result, us_rot_close)
    return apply_subb_asset_peak_decay_overlay_from_state(
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
        "overlay_asset_days": meta.get("overlay_asset_days", 0) if meta else 0,
        "avg_removed_weight": meta.get("avg_removed_weight", 0.0) if meta else 0.0,
        "trigger_count": meta.get("trigger_count", 0) if meta else 0,
        "recovery_count": meta.get("recovery_count", 0) if meta else 0,
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
        "# 策略B单标的动量衰减测试",
        "",
        f"- 基线脚本: `{BASE_SCRIPT.name}`",
        f"- 数据文件: `{LOCAL_US_CSV.name}`",
        f"- 样本区间: `{sample_start} -> {sample_end}`",
        "- 基线口径: `Sub-B` 正式 `6.8` 路径，包含 `VolReg`，不改正式代码。",
        "- Overlay口径: 只对非债券风险资产分别跟踪自身动量相对本轮持仓peak的衰减；`TLT/VGLT` 债券腿不参与过滤。触发后只削该资产，削掉的权重回 `BIL`；恢复后必须先创新高才允许再次触发。",
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
    parser = argparse.ArgumentParser(description="Scan Sub-B asset-level peak-decay overlay on formal version data.")
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

    mod = _load_module(BASE_SCRIPT, "subb_asset_peak_decay_mod")
    bot, us_rot_close = _fetch_formal_subb_inputs(mod)
    base_result = _baseline_subb_result(mod, bot, us_rot_close)

    compare_rows = [_evaluate_result(mod, "baseline_no_overlay", base_result)]
    window_rows = _evaluate_windows(mod, "baseline_no_overlay", base_result, [("1Y", 1), ("3Y", 3), ("5Y", 5)])

    variants = _build_param_grid(args.decay_grid, args.recovery_grid, args.derisk_scales)
    for cfg in variants:
        name = (
            f"asset_decay{int(round(cfg['decay_ratio_threshold'] * 100))}"
            f"_rec{int(round(cfg['recovery_ratio_threshold'] * 100))}"
            f"_x{cfg['derisk_scale']:.2f}"
        ).replace(".", "p")
        result = apply_subb_asset_peak_decay_overlay(
            mod,
            base_result,
            us_rot_close,
            decay_ratio_threshold=cfg["decay_ratio_threshold"],
            recovery_ratio_threshold=cfg["recovery_ratio_threshold"],
            derisk_scale=cfg["derisk_scale"],
        )
        meta = result.attrs.get("asset_peak_decay_overlay", {})
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
        "overlay_asset_days",
    ]
    print(compare_df[display_cols].head(12).to_string(index=False))
    print(f"\nSaved: {args.output}")
    print(f"Saved: {args.top_output}")
    print(f"Saved: {args.window_output}")
    print(f"Saved: {SUMMARY_MD}")


if __name__ == "__main__":
    main()

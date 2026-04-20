import argparse
import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from analyze_suba_decay_switch_overlay import (
    _build_bias_df,
    _combined_metrics,
    _evaluate_result,
    _evaluate_windows,
    _extract_active_bias_score,
    _load_local_cn_data,
    _load_local_us_data,
    _load_module,
)

ROOT = HERE.parents[1]
BASE_SCRIPT = ROOT / "mnt_bot V 6.7 plus.py"
CN_CSV = ROOT / "mnt_strategy_data_cn.csv"
US_CSV = ROOT / "mnt_strategy_data_us.csv"
OUTPUT_CSV = HERE / "suba_v67_cash_overlay_compare.csv"
WINDOW_CSV = HERE / "suba_v67_cash_overlay_window_compare.csv"
COMBO_CSV = HERE / "suba_v67_cash_overlay_combo_compare.csv"
COMBO_WINDOW_CSV = HERE / "suba_v67_cash_overlay_combo_window_compare.csv"
SUMMARY_MD = HERE / "策略A_V67叠加测试记录_2026-04-20.md"


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


def _load_v67_module(path: Path, module_name: str):
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


def apply_suba_v67_cash_overlay(
    cn_result: pd.DataFrame,
    close_df: pd.DataFrame,
    active_score: pd.Series,
    stock_codes: list[str],
    decay_ratio_threshold: float,
    recovery_ratio_threshold: float,
    commission: float,
    rf_daily: float,
    target_vol: float,
    vol_window: int,
    trading_days: int,
    min_lev: float,
    max_lev: float,
    scale_threshold: float,
) -> pd.DataFrame:
    if not 0 < decay_ratio_threshold < 1:
        raise ValueError("decay_ratio_threshold must be in (0, 1).")
    if not decay_ratio_threshold < recovery_ratio_threshold <= 1:
        raise ValueError("recovery_ratio_threshold must be in (decay_ratio_threshold, 1].")

    required = {"holding", "holding_fraction", "return"}
    missing = required.difference(cn_result.columns)
    if missing:
        raise KeyError(f"Missing required V6.7 Sub-A columns: {sorted(missing)}")

    out = cn_result.copy()
    base_holding = out["holding"].fillna("cash").astype(str)
    base_fraction = out["holding_fraction"].fillna(0.0).astype(float).clip(lower=0.0, upper=1.0)
    active_score = active_score.reindex(out.index).astype(float)

    effective_holdings = []
    effective_fractions = []
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
    prev_overlay_on = False

    for i, dt in enumerate(out.index):
        cur_base_holding = base_holding.iloc[i]
        cur_base_fraction = float(base_fraction.iloc[i])
        prev_base_holding = base_holding.iloc[i - 1] if i > 0 else None
        new_trade = i == 0 or cur_base_holding != prev_base_holding

        if new_trade:
            trade_id += 1
            score_peak = None
            derisked_for_today = False
            waiting_for_new_peak = False
            rearm_peak = None

        eligible_stock = cur_base_holding in stock_codes and cur_base_fraction > 1e-12
        cur_effective_holding = "cash" if (derisked_for_today and eligible_stock) else (cur_base_holding if cur_base_fraction > 1e-12 else "cash")
        cur_effective_fraction = 0.0 if (derisked_for_today and eligible_stock) else (cur_base_fraction if cur_base_holding != "cash" else 0.0)
        cur_overlay_on = bool(derisked_for_today and eligible_stock)
        triggered_today = cur_overlay_on and not prev_overlay_on
        recovered_today = (not cur_overlay_on) and prev_overlay_on

        cur_score = active_score.iloc[i] if eligible_stock else float("nan")
        if pd.notna(cur_score):
            cur_score = float(cur_score)
            score_peak = cur_score if score_peak is None else max(float(score_peak), cur_score)

        decay_ratio = None
        if score_peak is not None and score_peak > 1e-12 and pd.notna(cur_score):
            decay_ratio = float(cur_score) / float(score_peak)

        next_derisked = derisked_for_today
        next_waiting = waiting_for_new_peak
        next_rearm_peak = rearm_peak

        if next_waiting and next_rearm_peak is not None and score_peak is not None and score_peak > float(next_rearm_peak) + 1e-12:
            next_waiting = False
            next_rearm_peak = None

        if eligible_stock:
            if next_derisked:
                if decay_ratio is not None and decay_ratio >= recovery_ratio_threshold:
                    next_derisked = False
                    next_waiting = True
                    next_rearm_peak = score_peak
            elif not next_waiting and decay_ratio is not None and decay_ratio <= decay_ratio_threshold:
                next_derisked = True
        else:
            next_derisked = False
            next_waiting = False
            next_rearm_peak = None

        effective_holdings.append(cur_effective_holding)
        effective_fractions.append(float(cur_effective_fraction))
        overlay_on.append(cur_overlay_on)
        overlay_triggered.append(triggered_today)
        overlay_recovered.append(recovered_today)
        trade_ids.append(int(trade_id))
        score_peaks.append(None if score_peak is None else float(score_peak))
        score_decay_ratios.append(None if decay_ratio is None else float(decay_ratio))
        waiting_flags.append(bool(next_waiting))

        derisked_for_today = next_derisked
        waiting_for_new_peak = next_waiting
        rearm_peak = next_rearm_peak
        prev_overlay_on = cur_overlay_on

    eff_h = pd.Series(effective_holdings, index=out.index, dtype=str)
    eff_f = pd.Series(effective_fractions, index=out.index, dtype=float)

    asset_components = []
    cash_components = []
    trade_costs = []
    effective_signals = []

    for i, dt in enumerate(out.index):
        if i == 0:
            asset_components.append(float(out["asset_component"].iloc[i]) if "asset_component" in out.columns else 0.0)
            cash_components.append(float(out["cash_component"].iloc[i]) if "cash_component" in out.columns else float(out["return"].iloc[i]))
            trade_costs.append(float(out["trade_cost"].iloc[i]) if "trade_cost" in out.columns else 0.0)
            effective_signals.append(bool(eff_f.iloc[i] > 1e-12))
            continue

        prev_dt = out.index[i - 1]
        old_h = eff_h.iloc[i - 1]
        old_f = float(eff_f.iloc[i - 1])
        new_h = eff_h.iloc[i]
        new_f = float(eff_f.iloc[i])

        if old_h == "cash" or old_f <= 1e-12:
            asset_component = 0.0
        else:
            asset_ret = close_df.loc[dt, old_h] / close_df.loc[prev_dt, old_h] - 1
            asset_component = old_f * float(asset_ret)
        cash_component = (1.0 - old_f) * rf_daily

        if new_h == old_h:
            turnover = abs(new_f - old_f)
        else:
            turnover = old_f + new_f
        trade_cost = commission * float(turnover)

        asset_components.append(float(asset_component))
        cash_components.append(float(cash_component))
        trade_costs.append(float(trade_cost))
        effective_signals.append(bool(turnover > 1e-12))

    asset_component_s = pd.Series(asset_components, index=out.index, dtype=float)
    cash_component_s = pd.Series(cash_components, index=out.index, dtype=float)
    trade_cost_s = pd.Series(trade_costs, index=out.index, dtype=float)
    raw_ret = asset_component_s + cash_component_s

    realized_vol = raw_ret.rolling(vol_window).std() * (trading_days ** 0.5)
    raw_scale = (target_vol / realized_vol).clip(min_lev, max_lev).shift(1)
    if scale_threshold > 0:
        arr = raw_scale.values.copy()
        last = float("nan")
        for i in range(len(arr)):
            if pd.isna(arr[i]):
                continue
            if pd.isna(last):
                last = arr[i]
            elif abs(arr[i] - last) >= scale_threshold - 1e-9:
                last = arr[i]
            else:
                arr[i] = last
        raw_scale = pd.Series(arr, index=out.index)

    scale_arr = raw_scale.fillna(1.0).values
    is_cash = eff_f.values <= 1e-12
    scale_arr[is_cash] = 1.0
    effective_weight = scale_arr * eff_f.values
    prev_weight = pd.Series(effective_weight, index=out.index).shift(1).fillna(effective_weight[0])
    delta_weight = (pd.Series(effective_weight, index=out.index) - prev_weight).abs()
    no_holding_change = ~pd.Series(effective_signals, index=out.index, dtype=bool)
    scale_tc = pd.Series(0.0, index=out.index, dtype=float)
    scale_tc.loc[no_holding_change & (~pd.Series(is_cash, index=out.index))] = commission * delta_weight.loc[
        no_holding_change & (~pd.Series(is_cash, index=out.index))
    ]

    scaled_gross = 1.0 + asset_component_s.values * scale_arr + cash_component_s.values
    final_ret = scaled_gross * (1.0 - trade_cost_s.values) * (1.0 - scale_tc.values) - 1.0

    out["base_holding"] = base_holding
    out["base_fraction"] = base_fraction
    out["effective_holding"] = eff_h
    out["effective_fraction"] = eff_f
    out["active_score_overlay"] = active_score
    out["overlay_on"] = pd.Series(overlay_on, index=out.index, dtype=bool)
    out["overlay_triggered"] = pd.Series(overlay_triggered, index=out.index, dtype=bool)
    out["overlay_recovered"] = pd.Series(overlay_recovered, index=out.index, dtype=bool)
    out["trade_id"] = pd.Series(trade_ids, index=out.index, dtype="Int64")
    out["score_peak_overlay"] = pd.Series(score_peaks, index=out.index, dtype=float)
    out["score_decay_ratio_overlay"] = pd.Series(score_decay_ratios, index=out.index, dtype=float)
    out["waiting_for_new_peak"] = pd.Series(waiting_flags, index=out.index, dtype=bool)
    out["asset_component_overlay"] = asset_component_s
    out["cash_component_overlay"] = cash_component_s
    out["trade_cost_overlay"] = trade_cost_s
    out["raw_return_overlay"] = raw_ret
    out["scale_raw"] = raw_scale
    out["base_weight"] = eff_f
    out["weight"] = pd.Series(effective_weight, index=out.index, dtype=float)
    out["realized_vol"] = realized_vol
    out["scale_tc"] = scale_tc
    out["return"] = pd.Series(final_ret, index=out.index, dtype=float)
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["is_signal"] = pd.Series(effective_signals, index=out.index, dtype=bool)
    out["target"] = out["effective_holding"].where(out["is_signal"], None)
    out.attrs["suba_v67_cash_overlay"] = {
        "decay_ratio_threshold": decay_ratio_threshold,
        "recovery_ratio_threshold": recovery_ratio_threshold,
        "overlay_days": int(out["overlay_on"].sum()),
        "overlay_ratio": float(out["overlay_on"].mean()),
        "trigger_count": int(out["overlay_triggered"].sum()),
        "recovery_count": int(out["overlay_recovered"].sum()),
        "avg_effective_fraction": float(out["effective_fraction"].mean()),
    }
    return out


def _write_summary(compare_df, window_df, combo_df, combo_window_df, sample_start, sample_end):
    base = compare_df.loc[compare_df["variant"] == "baseline_v67"].iloc[0]
    alt = compare_df.loc[compare_df["variant"] == "v67_plus_suba_cash_overlay"].iloc[0]
    lines = [
        "# 策略A V6.7 首阴线补满叠加切现金测试",
        "",
        f"- 基线脚本: `{BASE_SCRIPT.name}`",
        f"- 本地数据: `{CN_CSV.name}` / `{US_CSV.name}`",
        f"- 样本区间: `{sample_start} -> {sample_end}`",
        f"- 固定参数: `Sub-A cash overlay decay=55% / recover=90%`",
        "",
        "## Sub-A 对比",
        "",
        f"- `baseline_v67`: 年化 `{base['annual']:.4f}%` / 最大回撤 `{base['max_dd']:.4f}%` / Calmar `{base['calmar']:.4f}`",
        f"- `v67_plus_suba_cash_overlay`: 年化 `{alt['annual']:.4f}%` / 最大回撤 `{alt['max_dd']:.4f}%` / Calmar `{alt['calmar']:.4f}`",
        f"- 增量: 年化 `{alt['annual_delta']:.4f}%` / 回撤变化 `{alt['max_dd_delta']:.4f}%`",
        "",
        "## Sub-A 分窗口",
        "",
    ]
    for _, row in window_df.iterrows():
        lines.append(
            f"- `{row['variant']} {row['window']}`: 年化 `{row['annual']:.4f}%` / 最大回撤 `{row['max_dd']:.4f}%` / "
            f"Sharpe `{row['sharpe']:.4f}` / Calmar `{row['calmar']:.4f}`"
        )
    lines.extend(["", "## 组合层对比", ""])
    for _, row in combo_df.iterrows():
        lines.append(
            f"- `{row['variant']}`: 年化 `{row['annual']:.4f}%` / 最大回撤 `{row['max_dd']:.4f}%` / "
            f"相对组合基线年化变化 `{row['annual_delta']:.4f}%` / 回撤变化 `{row['max_dd_delta']:.4f}%`"
        )
    lines.extend(["", "## 组合层分窗口", ""])
    for _, row in combo_window_df.iterrows():
        lines.append(
            f"- `{row['variant']} {row['window']}`: 年化 `{row['annual']:.4f}%` / 最大回撤 `{row['max_dd']:.4f}%` / "
            f"相对窗口基线年化变化 `{row['annual_delta']:.4f}%` / 回撤变化 `{row['max_dd_delta']:.4f}%`"
        )
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Test Sub-A cash overlay stacked on V6.7 delayed-entry baseline.")
    parser.add_argument("--cn-csv", default=str(CN_CSV))
    parser.add_argument("--us-csv", default=str(US_CSV))
    args = parser.parse_args()

    mod = _load_v67_module(BASE_SCRIPT, "suba_v67_stack_mod")
    cn_close, cn_dk_close = _load_local_cn_data(mod, Path(args.cn_csv))
    us_df = _load_local_us_data(Path(args.us_csv))

    cn_close_with_bond = cn_close.copy()
    if mod.CN_BOND_CODE not in cn_close_with_bond.columns and mod.CN_BOND_CODE in cn_close.columns:
        cn_close_with_bond[mod.CN_BOND_CODE] = cn_close[mod.CN_BOND_CODE]
    cn_result = mod.run_cn_strategy(cn_close_with_bond.copy(), mod.CN_EQUITY_CODES)
    bias_df = _build_bias_df(mod, cn_close_with_bond, mod.CN_EQUITY_CODES + [mod.CN_BOND_CODE])
    active_score = _extract_active_bias_score(cn_result, bias_df).reindex(cn_result.index)

    overlaid = apply_suba_v67_cash_overlay(
        cn_result,
        close_df=cn_close_with_bond,
        active_score=active_score,
        stock_codes=list(mod.CN_EQUITY_CODES),
        decay_ratio_threshold=0.55,
        recovery_ratio_threshold=0.90,
        commission=float(getattr(mod, "CN_COMMISSION", 0.0)),
        rf_daily=float(getattr(mod, "CN_RF_DAILY", 0.0)),
        target_vol=float(getattr(mod, "CN_TARGET_VOL", 0.20)),
        vol_window=int(getattr(mod, "CN_VOL_WINDOW", 60)),
        trading_days=int(getattr(mod, "CN_TRADING_DAYS", 244)),
        min_lev=float(getattr(mod, "CN_MIN_LEV", 0.1)),
        max_lev=float(getattr(mod, "CN_MAX_LEV", 1.5)),
        scale_threshold=float(getattr(mod, "CN_SCALE_THRESHOLD", 0.0)),
    )

    compare_rows = [
        _evaluate_result(mod, "baseline_v67", cn_result),
        _evaluate_result(mod, "v67_plus_suba_cash_overlay", overlaid, meta=overlaid.attrs.get("suba_v67_cash_overlay", {})),
    ]
    compare_df = pd.DataFrame(compare_rows)
    base = compare_df.loc[compare_df["variant"] == "baseline_v67"].iloc[0]
    compare_df["annual_delta"] = compare_df["annual"] - float(base["annual"])
    compare_df["max_dd_delta"] = compare_df["max_dd"] - float(base["max_dd"])
    compare_df["sharpe_delta"] = compare_df["sharpe"] - float(base["sharpe"])
    compare_df["calmar_delta"] = compare_df["calmar"] - float(base["calmar"])
    compare_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    windows = [("1Y", 252), ("3Y", 756), ("5Y", 1260)]
    window_rows = []
    window_rows.extend(_evaluate_windows(mod, "baseline_v67", cn_result, windows))
    window_rows.extend(_evaluate_windows(mod, "v67_plus_suba_cash_overlay", overlaid, windows))
    window_df = pd.DataFrame(window_rows)
    window_df.to_csv(WINDOW_CSV, index=False, encoding="utf-8-sig")

    bot = mod.CombinedStrategyV67()
    _, dk_result, us_rot_result, _, prod_sig_a, prod_sig_b, _, _ = bot._run_strategies(
        cn_close.copy(), cn_dk_close.copy(), us_df.copy(), us_df.copy()
    )
    subc_daily_ret = mod._get_subc_daily_ret(us_df.copy(), prod_sig_a, prod_sig_b=prod_sig_b)
    combo_base = _combined_metrics(mod, cn_result, dk_result, us_rot_result, subc_daily_ret)
    combo_alt = _combined_metrics(mod, overlaid, dk_result, us_rot_result, subc_daily_ret)
    combo_df = pd.DataFrame(
        [
            {"variant": "baseline_combo_v67", "annual": combo_base["annual"], "max_dd": combo_base["max_dd"], "annual_delta": 0.0, "max_dd_delta": 0.0},
            {
                "variant": "combo_v67_plus_suba_cash_overlay",
                "annual": combo_alt["annual"],
                "max_dd": combo_alt["max_dd"],
                "annual_delta": combo_alt["annual"] - combo_base["annual"],
                "max_dd_delta": combo_alt["max_dd"] - combo_base["max_dd"],
            },
        ]
    )
    combo_df.to_csv(COMBO_CSV, index=False, encoding="utf-8-sig")

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
    combo_variants = {
        "baseline_combo_v67": cn_result,
        "combo_v67_plus_suba_cash_overlay": overlaid,
    }
    combo_base_ret = _combo_return_series(cn_result)
    for label, days in windows:
        base_win = combo_base_ret.iloc[-days:] if len(combo_base_ret) > days else combo_base_ret
        base_metrics = mod.calc_daily_metrics(base_win, mod.CN_RF_DAILY, mod.CN_TRADING_DAYS)
        for name, variant_df in combo_variants.items():
            ret = _combo_return_series(variant_df)
            win = ret.iloc[-days:] if len(ret) > days else ret
            metrics = mod.calc_daily_metrics(win, mod.CN_RF_DAILY, mod.CN_TRADING_DAYS)
            combo_window_rows.append(
                {
                    "variant": name,
                    "window": label,
                    "annual": metrics["annual"],
                    "max_dd": metrics["max_dd"],
                    "sharpe": metrics["sharpe"],
                    "calmar": metrics["calmar"],
                    "annual_delta": metrics["annual"] - base_metrics["annual"],
                    "max_dd_delta": metrics["max_dd"] - base_metrics["max_dd"],
                }
            )
    combo_window_df = pd.DataFrame(combo_window_rows)
    combo_window_df.to_csv(COMBO_WINDOW_CSV, index=False, encoding="utf-8-sig")

    sample_start = cn_result.index[0].strftime("%Y-%m-%d")
    sample_end = cn_result.index[-1].strftime("%Y-%m-%d")
    _write_summary(compare_df, window_df, combo_df, combo_window_df, sample_start, sample_end)

    print(compare_df.to_string(index=False))
    print("\nCombo:")
    print(combo_df.to_string(index=False))
    print(f"\nSaved: {OUTPUT_CSV}")
    print(f"Saved windows: {WINDOW_CSV}")
    print(f"Saved combo: {COMBO_CSV}")
    print(f"Saved combo windows: {COMBO_WINDOW_CSV}")
    print(f"Saved summary: {SUMMARY_MD}")


if __name__ == "__main__":
    main()

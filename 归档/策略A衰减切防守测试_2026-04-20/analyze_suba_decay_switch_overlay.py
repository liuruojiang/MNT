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


BASE_SCRIPT = ROOT / "mnt_bot V 6.5 plus.py"
CN_CSV = ROOT / "mnt_strategy_data_cn.csv"
US_CSV = ROOT / "mnt_strategy_data_us.csv"
OUTPUT_CSV = HERE / "suba_decay_switch_scan_results.csv"
TOP_CSV = HERE / "suba_decay_switch_top.csv"
WINDOW_CSV = HERE / "suba_decay_switch_window_compare.csv"
COMBO_SPOT_CSV = HERE / "suba_decay_switch_combo_spot_check.csv"
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


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    module.poe = _DummyPoe
    spec.loader.exec_module(module)
    return module


def _load_local_cn_data(mod, csv_path: Path):
    df = pd.read_csv(csv_path)
    if "date" not in df.columns:
        raise ValueError(f"missing date column in {csv_path}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    cn_cols = [c for c in getattr(mod, "CN_ALL_CODES", []) if c in df.columns]
    if not cn_cols:
        raise ValueError("local CN csv is missing CN_ALL_CODES columns")
    cn_close = df[cn_cols].copy().ffill().dropna(how="all")

    dk_map = {
        mod.CN_DK_ZZ1000_SECID: mod.CN_DK_COLS[0],
        mod.CN_DK_SZ50_SECID: mod.CN_DK_COLS[1],
        mod.CN_DK_HS300_SECID: mod.CN_DK_COLS[2],
        mod.CN_DK_ZZ500_SECID: mod.CN_DK_COLS[3],
        mod.CN_DK_CYB_SECID: mod.CN_DK_COLS[4],
    }
    cn_dk_close = pd.concat(
        [df[[secid]].rename(columns={secid: col}) for secid, col in dk_map.items() if secid in df.columns],
        axis=1,
    ).ffill().dropna()

    common_idx = cn_close.index
    if len(cn_dk_close) > 0:
        common_idx = common_idx.intersection(cn_dk_close.index)
    cn_close = cn_close.reindex(common_idx).ffill()
    cn_dk_close = cn_dk_close.reindex(common_idx).ffill().dropna()
    return cn_close, cn_dk_close


def _load_local_us_data(csv_path: Path):
    df = pd.read_csv(csv_path)
    if "date" not in df.columns:
        raise ValueError(f"missing date column in {csv_path}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _build_bias_df(mod, close_df: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    bias = {}
    for code in codes:
        if code in close_df.columns:
            bias[code] = mod.calc_bias_momentum(close_df[code])
    if not bias:
        raise ValueError("no bias momentum columns available")
    return pd.DataFrame(bias, index=close_df.index)


def _extract_active_bias_score(cn_result: pd.DataFrame, bias_df: pd.DataFrame) -> pd.Series:
    if "holding" not in cn_result.columns:
        raise KeyError("holding column is required for Sub-A overlay")

    scores = []
    for dt, holding in cn_result["holding"].fillna("cash").items():
        score = None
        if holding != "cash" and holding in bias_df.columns and dt in bias_df.index:
            raw = bias_df.loc[dt, holding]
            if pd.notna(raw):
                score = float(raw)
        scores.append(score)
    return pd.Series(scores, index=cn_result.index, dtype=float)


def _resolve_defense_asset(defense_asset: str, close_df: pd.DataFrame, stock_codes: list[str]) -> str:
    asset = str(defense_asset).strip()
    asset_lower = asset.lower()
    if asset_lower == "cash":
        return "cash"
    if asset_lower == "bond":
        bond_like = [c for c in close_df.columns if c not in stock_codes and c != "cash"]
        if len(bond_like) == 1:
            return bond_like[0]
        raise ValueError("bond alias is ambiguous; pass the concrete defense asset code instead")
    if asset in close_df.columns:
        return asset
    raise ValueError(f"unsupported defense_asset: {defense_asset}")


def apply_suba_decay_switch_overlay(
    cn_result: pd.DataFrame,
    close_df: pd.DataFrame,
    active_score: pd.Series,
    stock_codes: list[str],
    defense_asset: str,
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

    required = {"return", "holding"}
    missing = required.difference(cn_result.columns)
    if missing:
        raise KeyError(f"Missing required Sub-A columns: {sorted(missing)}")

    defense_code = _resolve_defense_asset(defense_asset, close_df, stock_codes)

    out = cn_result.copy()
    holdings = out["holding"].fillna("cash").astype(str)
    active_score = active_score.reindex(out.index).astype(float)

    effective_holdings = []
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
        base_holding = holdings.iloc[i]
        prev_base_holding = holdings.iloc[i - 1] if i > 0 else None
        new_trade = i == 0 or base_holding != prev_base_holding

        if new_trade:
            trade_id += 1
            score_peak = None
            derisked_for_today = False
            waiting_for_new_peak = False
            rearm_peak = None

        eligible_stock = base_holding in stock_codes
        cur_effective = defense_code if derisked_for_today and eligible_stock else base_holding
        cur_overlay_on = cur_effective != base_holding
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

        effective_holdings.append(cur_effective)
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

    eff = pd.Series(effective_holdings, index=out.index, dtype=str)
    base_return = out["return"].fillna(0.0)
    raw_returns = []
    effective_signals = []
    prev_effective = None
    for i, dt in enumerate(out.index):
        cur_effective = eff.iloc[i]
        if i == 0:
            raw_returns.append(float(base_return.iloc[i]))
            effective_signals.append(bool(cur_effective != "cash"))
            prev_effective = cur_effective
            continue

        prev_dt = out.index[i - 1]
        changed = cur_effective != prev_effective
        effective_signals.append(bool(changed))
        if changed:
            cost = (1 - commission) if (prev_effective == "cash" or cur_effective == "cash") else (1 - commission) ** 2
            if prev_effective == "cash":
                day_ret = (1 + rf_daily) * cost - 1
            else:
                asset_ret = close_df.loc[dt, prev_effective] / close_df.loc[prev_dt, prev_effective] - 1
                day_ret = (1 + asset_ret) * cost - 1
        else:
            if cur_effective == "cash":
                day_ret = rf_daily
            else:
                day_ret = close_df.loc[dt, cur_effective] / close_df.loc[prev_dt, cur_effective] - 1
        raw_returns.append(float(day_ret))
        prev_effective = cur_effective

    raw_ret = pd.Series(raw_returns, index=out.index, dtype=float)
    realized_vol = raw_ret.rolling(vol_window).std() * (trading_days ** 0.5)
    raw_scale = (target_vol / realized_vol).clip(min_lev, max_lev).shift(1)

    if scale_threshold > 0:
        sa = raw_scale.values.copy()
        last = float("nan")
        for i in range(len(sa)):
            if pd.isna(sa[i]):
                continue
            if pd.isna(last):
                last = sa[i]
            elif abs(sa[i] - last) >= scale_threshold - 1e-9:
                last = sa[i]
            else:
                sa[i] = last
        raw_scale = pd.Series(sa, index=out.index)

    scale = raw_scale.fillna(1.0)
    scale.loc[eff == "cash"] = 1.0
    prev_scale = pd.Series(scale.values, index=out.index).shift(1).fillna(scale.iloc[0])
    delta_scale = (scale - prev_scale).abs()
    scale_tc = pd.Series(0.0, index=out.index, dtype=float)
    no_holding_change = ~pd.Series(effective_signals, index=out.index, dtype=bool)
    scale_tc.loc[no_holding_change & (eff != "cash")] = commission * delta_scale.loc[no_holding_change & (eff != "cash")]

    final_ret = (1 + raw_ret * scale) * (1 - scale_tc) - 1

    out["base_holding"] = holdings
    out["effective_holding"] = eff
    out["raw_return_overlay"] = raw_ret
    out["scale_raw"] = raw_scale
    out["weight"] = scale
    out["realized_vol"] = realized_vol
    out["scale_tc"] = scale_tc
    out["return"] = final_ret
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["active_score_overlay"] = active_score
    out["overlay_on"] = pd.Series(overlay_on, index=out.index, dtype=bool)
    out["overlay_triggered"] = pd.Series(overlay_triggered, index=out.index, dtype=bool)
    out["overlay_recovered"] = pd.Series(overlay_recovered, index=out.index, dtype=bool)
    out["trade_id"] = pd.Series(trade_ids, index=out.index, dtype="Int64")
    out["score_peak_overlay"] = pd.Series(score_peaks, index=out.index, dtype=float)
    out["score_decay_ratio_overlay"] = pd.Series(score_decay_ratios, index=out.index, dtype=float)
    out["waiting_for_new_peak"] = pd.Series(waiting_flags, index=out.index, dtype=bool)
    out["is_signal"] = pd.Series(effective_signals, index=out.index, dtype=bool)
    out["target"] = out["effective_holding"].where(out["is_signal"], None)
    out.attrs["suba_decay_switch_overlay"] = {
        "defense_asset": defense_asset,
        "decay_ratio_threshold": decay_ratio_threshold,
        "recovery_ratio_threshold": recovery_ratio_threshold,
        "overlay_days": int(out["overlay_on"].sum()),
        "overlay_ratio": float(out["overlay_on"].mean()),
        "trigger_count": int(out["overlay_triggered"].sum()),
        "recovery_count": int(out["overlay_recovered"].sum()),
    }
    return out


def _evaluate_result(mod, name: str, cn_result: pd.DataFrame, meta: dict | None = None):
    ret = cn_result["return"].dropna()
    metrics = mod.calc_daily_metrics(ret, mod.CN_RF_DAILY, mod.CN_TRADING_DAYS)
    return {
        "variant": name,
        "defense_asset": meta.get("defense_asset") if meta else None,
        "decay_ratio_threshold": meta.get("decay_ratio_threshold") if meta else None,
        "recovery_ratio_threshold": meta.get("recovery_ratio_threshold") if meta else None,
        "annual": metrics["annual"],
        "vol": metrics["vol"],
        "sharpe": metrics["sharpe"],
        "max_dd": metrics["max_dd"],
        "calmar": metrics["calmar"],
        "total_return": metrics["total_return"],
        "monthly_win_rate": metrics["win_rate"],
        "signal_days": int(cn_result["is_signal"].fillna(False).sum()) if "is_signal" in cn_result.columns else None,
        "overlay_days": meta.get("overlay_days", 0) if meta else 0,
        "overlay_ratio": meta.get("overlay_ratio", 0.0) if meta else 0.0,
        "trigger_count": meta.get("trigger_count", 0) if meta else 0,
        "recovery_count": meta.get("recovery_count", 0) if meta else 0,
        "avg_scale": float(cn_result["weight"].mean()) if "weight" in cn_result.columns else 1.0,
    }


def _evaluate_windows(mod, name: str, cn_result: pd.DataFrame, windows):
    ret = cn_result["return"].dropna()
    rows = []
    for label, days in windows:
        window_ret = ret.iloc[-days:] if len(ret) > days else ret
        if len(window_ret) < 2:
            continue
        metrics = mod.calc_daily_metrics(window_ret, mod.CN_RF_DAILY, mod.CN_TRADING_DAYS)
        rows.append(
            {
                "variant": name,
                "window": label,
                "start": window_ret.index[0].strftime("%Y-%m-%d"),
                "end": window_ret.index[-1].strftime("%Y-%m-%d"),
                "days": len(window_ret),
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


def _build_param_grid(decay_ratio_grid, recovery_ratio_grid, defense_assets):
    variants = []
    for defense_asset in defense_assets:
        for decay_ratio_threshold in decay_ratio_grid:
            for recovery_ratio_threshold in recovery_ratio_grid:
                if recovery_ratio_threshold <= decay_ratio_threshold:
                    continue
                variants.append(
                    {
                        "defense_asset": defense_asset,
                        "decay_ratio_threshold": decay_ratio_threshold,
                        "recovery_ratio_threshold": recovery_ratio_threshold,
                    }
                )
    return variants


def _combined_metrics(mod, cn_variant, dk_result, us_rot_result, subc_daily_ret):
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

    all_nav_dates = sorted(set().union(*(s.index for s in nav_series.values())))
    nav_df = pd.DataFrame({name: s.reindex(pd.DatetimeIndex(all_nav_dates)).ffill() for name, s in nav_series.items()})
    weight_df = nav_df.notna().astype(float)
    for col in weight_df.columns:
        weight_df[col] *= mod.COMBINED_WEIGHTS.get(col, 0)
    weight_sum = weight_df.sum(axis=1).replace(0, pd.NA)
    weight_df = weight_df.div(weight_sum, axis=0)
    nav_df = nav_df.fillna(0.0)
    nav_comb = (nav_df * weight_df).sum(axis=1)
    nav_comb = nav_comb / nav_comb.iloc[0]
    ret = nav_comb.pct_change().dropna()
    return mod.calc_daily_metrics(ret, mod.CN_RF_DAILY, mod.CN_TRADING_DAYS)


def _write_summary(compare_df, window_df, combo_rows, sample_start, sample_end):
    baseline = compare_df.loc[compare_df["variant"] == "baseline_no_overlay"].iloc[0]
    non = compare_df.loc[compare_df["variant"] != "baseline_no_overlay"].copy()
    better_annual = int((non["annual"] > baseline["annual"]).sum())
    better_maxdd = int((non["max_dd"] > baseline["max_dd"]).sum())
    better_both = int(((non["annual"] > baseline["annual"]) & (non["max_dd"] > baseline["max_dd"])).sum())
    best_annual = non.sort_values("annual", ascending=False).iloc[0]
    best_dd = non.sort_values("max_dd", ascending=False).iloc[0]

    lines = [
        "# 策略A衰减切防守测试记录",
        "",
        f"- 基线脚本: `{BASE_SCRIPT.name}`",
        f"- 本地数据: `{CN_CSV.name}` / `{US_CSV.name}`",
        f"- 样本区间: `{sample_start} -> {sample_end}`",
        "",
        "## 基线",
        "",
        f"- 年化: `{baseline['annual']:.4%}`",
        f"- 最大回撤: `{baseline['max_dd']:.4%}`",
        f"- Sharpe: `{baseline['sharpe']:.4f}`",
        f"- Calmar: `{baseline['calmar']:.4f}`",
        "",
        "## 结论",
        "",
        f"- 年化高于基线的参数组数量: `{better_annual}`",
        f"- 最大回撤浅于基线的参数组数量: `{better_maxdd}`",
        f"- 同时改善收益和回撤的参数组数量: `{better_both}`",
        "",
        "## 代表参数",
        "",
        f"- 收益最强: `{best_annual['variant']}` -> 年化 `{best_annual['annual']:.4%}` / 最大回撤 `{best_annual['max_dd']:.4%}`",
        f"- 回撤最浅: `{best_dd['variant']}` -> 年化 `{best_dd['annual']:.4%}` / 最大回撤 `{best_dd['max_dd']:.4%}`",
    ]

    if combo_rows:
        lines.extend(["", "## 组合层点检", ""])
        for row in combo_rows:
            lines.append(
                f"- `{row['variant']}`: 年化 `{row['annual']:.4%}` / 最大回撤 `{row['max_dd']:.4%}` / 年化变化 `{row['annual_delta']:.4%}`"
            )

    if not window_df.empty:
        lines.extend(["", "## 分窗口", ""])
        for target_name in [best_annual["variant"], best_dd["variant"]]:
            sub = window_df[window_df["variant"] == target_name]
            if sub.empty:
                continue
            lines.append(f"- `{target_name}`")
            for _, row in sub.iterrows():
                lines.append(
                    f"  {row['window']}: 年化 `{row['annual']:.4%}` / 最大回撤 `{row['max_dd']:.4%}` / Sharpe `{row['sharpe']:.4f}`"
                )

    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Scan Sub-A decay-switch overlay on V6.5 baseline.")
    parser.add_argument("--cn-csv", default=str(CN_CSV), help="Local CN csv path.")
    parser.add_argument("--us-csv", default=str(US_CSV), help="Local US csv path.")
    parser.add_argument("--output", default=str(OUTPUT_CSV), help="Output csv path.")
    parser.add_argument("--top-output", default=str(TOP_CSV), help="Top rows csv path.")
    parser.add_argument("--window-output", default=str(WINDOW_CSV), help="Window compare csv path.")
    parser.add_argument("--combo-output", default=str(COMBO_SPOT_CSV), help="Combo spot-check csv path.")
    parser.add_argument("--top-n", type=int, default=15, help="Top rows to save.")
    parser.add_argument("--decay-ratio-grid", nargs="*", type=float, default=[0.20, 0.30, 0.40, 0.50, 0.60], help="Decay trigger threshold grid.")
    parser.add_argument("--recovery-ratio-grid", nargs="*", type=float, default=[0.40, 0.50, 0.60, 0.70, 0.80, 0.90], help="Recovery threshold grid.")
    parser.add_argument("--defense-assets", nargs="*", default=["bond", "cash"], help="Defense target grid.")
    args = parser.parse_args()

    mod = _load_module(BASE_SCRIPT, "suba_decay_switch_mod")
    cn_close, cn_dk_close = _load_local_cn_data(mod, Path(args.cn_csv))
    us_df = _load_local_us_data(Path(args.us_csv))

    cn_result = mod.run_cn_strategy(cn_close.copy(), mod.CN_EQUITY_CODES)
    bias_df = _build_bias_df(mod, cn_close, mod.CN_EQUITY_CODES + [mod.CN_BOND_CODE])
    active_score = _extract_active_bias_score(cn_result, bias_df).reindex(cn_result.index)

    rows = [_evaluate_result(mod, "baseline_no_overlay", cn_result)]
    variants = {"baseline_no_overlay": cn_result.copy()}

    for cfg in _build_param_grid(args.decay_ratio_grid, args.recovery_ratio_grid, args.defense_assets):
        overlaid = apply_suba_decay_switch_overlay(
            cn_result,
            close_df=cn_close,
            active_score=active_score,
            stock_codes=list(mod.CN_EQUITY_CODES),
            defense_asset=cfg["defense_asset"],
            decay_ratio_threshold=cfg["decay_ratio_threshold"],
            recovery_ratio_threshold=cfg["recovery_ratio_threshold"],
            commission=float(getattr(mod, "CN_COMMISSION", 0.0)),
            rf_daily=float(getattr(mod, "CN_RF_DAILY", 0.0)),
            target_vol=float(getattr(mod, "CN_TARGET_VOL", 0.20)),
            vol_window=int(getattr(mod, "CN_VOL_WINDOW", 60)),
            trading_days=int(getattr(mod, "CN_TRADING_DAYS", 244)),
            min_lev=float(getattr(mod, "CN_MIN_LEV", 0.1)),
            max_lev=float(getattr(mod, "CN_MAX_LEV", 1.5)),
            scale_threshold=float(getattr(mod, "CN_SCALE_THRESHOLD", 0.0)),
        )
        name = (
            f"switch_{cfg['defense_asset']}"
            f"_decay{int(round(cfg['decay_ratio_threshold'] * 100))}"
            f"_rec{int(round(cfg['recovery_ratio_threshold'] * 100))}"
        )
        variants[name] = overlaid
        rows.append(_evaluate_result(mod, name, overlaid, meta=overlaid.attrs.get("suba_decay_switch_overlay", {})))

    compare_df = pd.DataFrame(rows)
    baseline = compare_df.loc[compare_df["variant"] == "baseline_no_overlay"].iloc[0]
    compare_df["annual_delta"] = compare_df["annual"] - float(baseline["annual"])
    compare_df["max_dd_delta"] = compare_df["max_dd"] - float(baseline["max_dd"])
    compare_df["sharpe_delta"] = compare_df["sharpe"] - float(baseline["sharpe"])
    compare_df["calmar_delta"] = compare_df["calmar"] - float(baseline["calmar"])
    compare_df = compare_df.sort_values(["calmar", "annual", "max_dd"], ascending=[False, False, False]).reset_index(drop=True)
    compare_df.to_csv(Path(args.output), index=False, encoding="utf-8-sig")
    compare_df.head(args.top_n).to_csv(Path(args.top_output), index=False, encoding="utf-8-sig")

    window_rows = []
    windows = [("1Y", 252), ("3Y", 252 * 3), ("5Y", 252 * 5)]
    focus_names = ["baseline_no_overlay"] + compare_df.head(min(args.top_n, len(compare_df)))["variant"].tolist()
    seen = []
    for name in focus_names:
        if name not in seen:
            seen.append(name)
    for name in seen:
        window_rows.extend(_evaluate_windows(mod, name, variants[name], windows))
    window_df = pd.DataFrame(window_rows)
    if not window_df.empty:
        window_df.to_csv(Path(args.window_output), index=False, encoding="utf-8-sig")
    else:
        Path(args.window_output).write_text("", encoding="utf-8")

    bot = mod.CombinedStrategyV65()
    _, dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, _, _ = bot._run_strategies(
        cn_close.copy(), cn_dk_close.copy(), us_df.copy(), us_df.copy()
    )
    subc_daily_ret = mod._get_subc_daily_ret(us_df.copy(), prod_sig_a, prod_sig_b=prod_sig_b)
    non = compare_df.loc[compare_df["variant"] != "baseline_no_overlay"].copy()
    best_annual = non.sort_values("annual", ascending=False).iloc[0]
    best_dd = non.sort_values("max_dd", ascending=False).iloc[0]
    combo_rows = []
    base_combo = _combined_metrics(mod, variants["baseline_no_overlay"], dk_result, us_rot_result, subc_daily_ret)
    combo_rows.append(
        {
            "variant": "baseline_combo",
            "annual": base_combo["annual"],
            "max_dd": base_combo["max_dd"],
            "annual_delta": 0.0,
            "max_dd_delta": 0.0,
        }
    )
    for row in [best_annual, best_dd]:
        combo = _combined_metrics(mod, variants[row["variant"]], dk_result, us_rot_result, subc_daily_ret)
        combo_rows.append(
            {
                "variant": f"{row['variant']}_combo",
                "annual": combo["annual"],
                "max_dd": combo["max_dd"],
                "annual_delta": combo["annual"] - base_combo["annual"],
                "max_dd_delta": combo["max_dd"] - base_combo["max_dd"],
            }
        )
    pd.DataFrame(combo_rows).drop_duplicates(subset=["variant"]).to_csv(Path(args.combo_output), index=False, encoding="utf-8-sig")

    sample_start = cn_result.index[0].strftime("%Y-%m-%d")
    sample_end = cn_result.index[-1].strftime("%Y-%m-%d")
    _write_summary(compare_df, window_df, combo_rows, sample_start, sample_end)

    print(compare_df.head(min(args.top_n, len(compare_df))).to_string(index=False))
    print(f"\nSaved: {args.output}")
    print(f"Saved top: {args.top_output}")
    print(f"Saved windows: {args.window_output}")
    print(f"Saved combo spot: {args.combo_output}")
    print(f"Saved summary: {SUMMARY_MD}")


if __name__ == "__main__":
    main()

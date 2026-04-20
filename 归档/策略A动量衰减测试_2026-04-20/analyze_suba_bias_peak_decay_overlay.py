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
OUTPUT_CSV = HERE / "suba_bias_peak_decay_scan_results.csv"
TOP_CSV = HERE / "suba_bias_peak_decay_top.csv"
WINDOW_CSV = HERE / "suba_bias_peak_decay_window_compare.csv"
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
    return cn_close


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
        raise KeyError("holding column is required for Sub-A bias overlay")

    scores = []
    for dt, holding in cn_result["holding"].fillna("cash").items():
        score = None
        if holding != "cash" and holding in bias_df.columns and dt in bias_df.index:
            raw = bias_df.loc[dt, holding]
            if pd.notna(raw):
                score = float(raw)
        scores.append(score)
    return pd.Series(scores, index=cn_result.index, dtype=float)


def apply_suba_bias_peak_decay_overlay(
    cn_result: pd.DataFrame,
    active_score: pd.Series,
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
    if cn_result is None or len(cn_result) == 0:
        return cn_result

    required = {"return", "holding"}
    missing = required.difference(cn_result.columns)
    if missing:
        raise KeyError(f"Missing required Sub-A columns: {sorted(missing)}")

    out = cn_result.copy()
    base_ret = out["return"].fillna(0.0)
    base_weight = out["weight"].fillna(1.0) if "weight" in out.columns else pd.Series(1.0, index=out.index)
    holdings = out["holding"].fillna("cash").astype(str)
    active_score = active_score.reindex(out.index).astype(float)

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

    for i, dt in enumerate(base_ret.index):
        holding = holdings.iloc[i]
        prev_holding = holdings.iloc[i - 1] if i > 0 else None
        new_trade = i == 0 or holding != prev_holding

        if new_trade:
            trade_id += 1
            score_peak = None
            derisked_for_today = False
            waiting_for_new_peak = False
            rearm_peak = None

        cur_scale = derisk_scale if derisked_for_today else 1.0
        triggered_today = cur_scale < 0.999999 and prev_scale >= 0.999999
        recovered_today = cur_scale >= 0.999999 and prev_scale < 0.999999

        realized_ret = float(base_ret.iloc[i]) * cur_scale
        delta_scale = abs(cur_scale - prev_scale)
        overlay_tc = 0.0
        if delta_scale > 1e-12:
            overlay_tc = 2.0 * commission * float(base_weight.iloc[i]) * delta_scale
        realized_ret = (1.0 + realized_ret) * (1.0 - overlay_tc) - 1.0

        cur_score = active_score.iloc[i]
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

        if next_derisked:
            if decay_ratio is not None and decay_ratio >= recovery_ratio_threshold:
                next_derisked = False
                next_waiting = True
                next_rearm_peak = score_peak
        elif not next_waiting and decay_ratio is not None and decay_ratio <= decay_ratio_threshold:
            next_derisked = True

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
    out["base_weight"] = base_weight
    out["return"] = pd.Series(final_ret, index=out.index, dtype=float)
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["active_score_overlay"] = active_score
    out["overlay_scale"] = pd.Series(overlay_scale, index=out.index, dtype=float)
    out["overlay_on"] = pd.Series(overlay_on, index=out.index, dtype=bool)
    out["overlay_triggered"] = pd.Series(overlay_triggered, index=out.index, dtype=bool)
    out["overlay_recovered"] = pd.Series(overlay_recovered, index=out.index, dtype=bool)
    out["trade_id"] = pd.Series(trade_ids, index=out.index, dtype="Int64")
    out["score_peak_overlay"] = pd.Series(score_peaks, index=out.index, dtype=float)
    out["score_decay_ratio_overlay"] = pd.Series(score_decay_ratios, index=out.index, dtype=float)
    out["waiting_for_new_peak"] = pd.Series(waiting_flags, index=out.index, dtype=bool)
    out["weight"] = out["base_weight"] * out["overlay_scale"]
    out.attrs["suba_bias_peak_decay_overlay"] = {
        "decay_ratio_threshold": decay_ratio_threshold,
        "recovery_ratio_threshold": recovery_ratio_threshold,
        "derisk_scale": derisk_scale,
        "commission": commission,
        "overlay_days": int(out["overlay_on"].sum()),
        "overlay_ratio": float(out["overlay_on"].mean()),
        "trigger_count": int(out["overlay_triggered"].sum()),
        "recovery_count": int(out["overlay_recovered"].sum()),
    }
    return out


def _evaluate_result(mod, name: str, cn_result: pd.DataFrame, meta: dict | None = None):
    ret = cn_result["return"].dropna()
    metrics = mod.calc_daily_metrics(ret, mod.CN_RF_DAILY, mod.CN_TRADING_DAYS)
    row = {
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
        "signal_days": int(cn_result["is_signal"].fillna(False).sum()) if "is_signal" in cn_result.columns else None,
        "overlay_days": meta.get("overlay_days", 0) if meta else 0,
        "overlay_ratio": meta.get("overlay_ratio", 0.0) if meta else 0.0,
        "trigger_count": meta.get("trigger_count", 0) if meta else 0,
        "recovery_count": meta.get("recovery_count", 0) if meta else 0,
        "avg_scale": float(cn_result["overlay_scale"].mean()) if "overlay_scale" in cn_result.columns else 1.0,
    }
    return row


def _evaluate_windows(mod, name: str, cn_result: pd.DataFrame, windows):
    rows = []
    ret = cn_result["return"].dropna()
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
    baseline = compare_df.loc[compare_df["variant"] == "baseline_no_overlay"].iloc[0]
    top_row = compare_df.iloc[0]
    lines = [
        "# 策略A动量衰减测试记录",
        "",
        f"- 基线脚本: `{BASE_SCRIPT.name}`",
        f"- 本地数据: `{CN_CSV.name}`",
        f"- 样本区间: `{sample_start} -> {sample_end}`",
        "",
        "## 基线",
        "",
        f"- 年化: `{baseline['annual']:.4%}`",
        f"- 最大回撤: `{baseline['max_dd']:.4%}`",
        f"- Sharpe: `{baseline['sharpe']:.4f}`",
        f"- Calmar: `{baseline['calmar']:.4f}`",
        "",
        "## 当前最优",
        "",
        f"- 参数: `decay={top_row['decay_ratio_threshold']:.0%} / recover={top_row['recovery_ratio_threshold']:.0%} / scale={top_row['derisk_scale']:.2f}`",
        f"- 年化: `{top_row['annual']:.4%}`",
        f"- 最大回撤: `{top_row['max_dd']:.4%}`",
        f"- Sharpe: `{top_row['sharpe']:.4f}`",
        f"- Calmar: `{top_row['calmar']:.4f}`",
        f"- 相对基线年化变化: `{top_row['annual_delta']:.4%}`",
        f"- 相对基线回撤变化: `{top_row['max_dd_delta']:.4%}`",
    ]
    if not window_df.empty:
        top_name = top_row["variant"]
        top_windows = window_df[window_df["variant"] == top_name]
        if not top_windows.empty:
            lines.extend(["", "## 分窗口", ""])
            for _, row in top_windows.iterrows():
                lines.append(
                    f"- `{row['window']}`: 年化 `{row['annual']:.4%}` / 最大回撤 `{row['max_dd']:.4%}` / Sharpe `{row['sharpe']:.4f}`"
                )

    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Scan Sub-A bias-momentum peak-decay overlay on V6.5 baseline.")
    parser.add_argument("--csv", default=str(CN_CSV), help="Local CN csv path.")
    parser.add_argument("--output", default=str(OUTPUT_CSV), help="Output csv path.")
    parser.add_argument("--top-output", default=str(TOP_CSV), help="Top rows csv path.")
    parser.add_argument("--window-output", default=str(WINDOW_CSV), help="Window compare csv path.")
    parser.add_argument("--top-n", type=int, default=15, help="Top rows to save.")
    parser.add_argument("--decay-ratio-grid", nargs="*", type=float, default=[0.20, 0.30, 0.40, 0.50, 0.60], help="Decay trigger threshold grid.")
    parser.add_argument("--recovery-ratio-grid", nargs="*", type=float, default=[0.40, 0.50, 0.60, 0.70, 0.80, 0.90], help="Recovery threshold grid.")
    parser.add_argument("--derisk-scale-grid", nargs="*", type=float, default=[0.0, 0.25, 0.50], help="Derisk scale grid.")
    args = parser.parse_args()

    mod = _load_module(BASE_SCRIPT, "suba_bias_peak_decay_mod")
    cn_close = _load_local_cn_data(mod, Path(args.csv))
    cn_result = mod.run_cn_strategy(cn_close.copy(), mod.CN_EQUITY_CODES)
    bias_df = _build_bias_df(mod, cn_close, mod.CN_EQUITY_CODES + [mod.CN_BOND_CODE])
    active_score = _extract_active_bias_score(cn_result, bias_df).reindex(cn_result.index)

    rows = []
    variants = {"baseline_no_overlay": cn_result.copy()}
    for cfg in _build_param_grid(args.decay_ratio_grid, args.recovery_ratio_grid, args.derisk_scale_grid):
        overlaid = apply_suba_bias_peak_decay_overlay(
            cn_result,
            active_score=active_score,
            decay_ratio_threshold=cfg["decay_ratio_threshold"],
            recovery_ratio_threshold=cfg["recovery_ratio_threshold"],
            derisk_scale=cfg["derisk_scale"],
            commission=float(getattr(mod, "CN_COMMISSION", 0.0)),
        )
        name = (
            f"bias_decay{int(round(cfg['decay_ratio_threshold'] * 100))}"
            f"_rec{int(round(cfg['recovery_ratio_threshold'] * 100))}"
            f"_x{cfg['derisk_scale']:.2f}"
        )
        variants[name] = overlaid
        rows.append(_evaluate_result(mod, name, overlaid, meta=overlaid.attrs.get("suba_bias_peak_decay_overlay", {})))

    compare_df = pd.DataFrame([_evaluate_result(mod, "baseline_no_overlay", cn_result)] + rows)
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
    top_variants = ["baseline_no_overlay"] + compare_df.head(min(args.top_n, len(compare_df)))["variant"].tolist()
    seen = []
    for name in top_variants:
        if name not in seen:
            seen.append(name)
    for name in seen:
        window_rows.extend(_evaluate_windows(mod, name, variants[name], windows))
    window_df = pd.DataFrame(window_rows)
    if not window_df.empty:
        window_df.to_csv(Path(args.window_output), index=False, encoding="utf-8-sig")
    else:
        Path(args.window_output).write_text("", encoding="utf-8")

    sample_start = cn_result.index[0].strftime("%Y-%m-%d")
    sample_end = cn_result.index[-1].strftime("%Y-%m-%d")
    _write_summary(compare_df, window_df, sample_start, sample_end)

    print(compare_df.head(min(args.top_n, len(compare_df))).to_string(index=False))
    print(f"\nSaved: {args.output}")
    print(f"Saved top: {args.top_output}")
    print(f"Saved windows: {args.window_output}")
    print(f"Saved summary: {SUMMARY_MD}")


if __name__ == "__main__":
    main()

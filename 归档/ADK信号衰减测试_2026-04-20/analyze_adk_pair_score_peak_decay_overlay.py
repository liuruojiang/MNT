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
from local_data_refresh import refresh_cn_strategy_data


BASE_SCRIPT = ROOT / "mnt_bot V 6.6 plus.py"
CN_CSV = ROOT / "mnt_strategy_data_cn.csv"
OUTPUT_CSV = HERE / "adk_pair_score_peak_decay_scan_results.csv"
TOP_CSV = HERE / "adk_pair_score_peak_decay_top.csv"


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
    refresh_cn_strategy_data(csv_path=csv_path, base_script_path=BASE_SCRIPT, verbose=False)
    df = pd.read_csv(csv_path)
    if "date" not in df.columns:
        raise ValueError(f"missing date column in {csv_path}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    cn_cols = [c for c in getattr(mod, "CN_ALL_CODES", []) if c in df.columns]
    cn_close = df[cn_cols].copy().ffill().dropna(how="all")

    dk_map = {
        mod.CN_DK_ZZ1000_SECID: mod.CN_DK_COLS[0],
        mod.CN_DK_SZ50_SECID: mod.CN_DK_COLS[1],
        mod.CN_DK_HS300_SECID: mod.CN_DK_COLS[2],
        mod.CN_DK_ZZ500_SECID: mod.CN_DK_COLS[3],
        mod.CN_DK_CYB_SECID: mod.CN_DK_COLS[4],
    }
    missing = [secid for secid in dk_map if secid not in df.columns]
    if missing:
        raise ValueError(f"local CN csv missing DK columns: {missing}")
    cn_dk_close = pd.concat(
        [df[[secid]].rename(columns={secid: col}) for secid, col in dk_map.items()],
        axis=1,
    ).ffill().dropna()

    common_idx = cn_dk_close.index
    if len(cn_close) > 0:
        common_idx = common_idx.intersection(cn_close.index)
        cn_close = cn_close.reindex(common_idx).ffill()
    cn_dk_close = cn_dk_close.reindex(common_idx).ffill().dropna()
    return cn_close, cn_dk_close


def _extract_active_pair_score(dk_result: pd.DataFrame) -> pd.Series:
    signals_df = dk_result.attrs.get("signals_df")
    if signals_df is None or len(dk_result) == 0:
        raise KeyError("signals_df is missing from dk_result attrs.")
    if "top_pair" not in dk_result.columns:
        raise KeyError("top_pair column is required for score-decay overlay.")

    scores = []
    for dt, pair in dk_result["top_pair"].fillna("none").items():
        score = None
        if pair != "none" and pair in signals_df.columns and dt in signals_df.index:
            raw = signals_df.loc[dt, pair]
            if pd.notna(raw):
                score = float(raw)
        scores.append(score)
    return pd.Series(scores, index=dk_result.index, dtype=float)


def apply_pair_score_peak_decay_overlay(
    dk_result: pd.DataFrame,
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
    if dk_result is None or len(dk_result) == 0:
        return dk_result

    required = {"return", "holding", "top_pair"}
    missing = required.difference(dk_result.columns)
    if missing:
        raise KeyError(f"Missing required DK columns: {sorted(missing)}")

    out = dk_result.copy()
    base_ret = out["return"].fillna(0.0)
    base_weight = out["weight"].fillna(1.0) if "weight" in out.columns else pd.Series(1.0, index=out.index)
    holdings = out["holding"].fillna("none_0").astype(str)
    active_score = _extract_active_pair_score(out)

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
    out.attrs["pair_score_peak_decay_overlay"] = {
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


def _evaluate_result(mod, name: str, dk_result: pd.DataFrame, meta: dict | None = None):
    ret = dk_result["return"].dropna()
    metrics = mod.calc_daily_metrics(ret, mod.CN_RF_DAILY, mod.CN_DK_TRADING_DAYS)
    rebalances = mod.extract_dk_rebalances(dk_result)
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
        "rebalanced_days": len(rebalances),
        "signal_days": int(dk_result["is_signal"].fillna(False).sum()) if "is_signal" in dk_result.columns else None,
        "overlay_days": meta.get("overlay_days", 0) if meta else 0,
        "overlay_ratio": meta.get("overlay_ratio", 0.0) if meta else 0.0,
        "trigger_count": meta.get("trigger_count", 0) if meta else 0,
        "recovery_count": meta.get("recovery_count", 0) if meta else 0,
        "avg_scale": float(dk_result["overlay_scale"].mean()) if "overlay_scale" in dk_result.columns else 1.0,
    }
    return row


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


def main():
    parser = argparse.ArgumentParser(description="Scan ADK pair-score peak-decay overlay using local CN data.")
    parser.add_argument("--csv", default=str(CN_CSV), help="Local CN data csv path.")
    parser.add_argument("--output", default=str(OUTPUT_CSV), help="Full result csv path.")
    parser.add_argument("--top-output", default=str(TOP_CSV), help="Top result csv path.")
    parser.add_argument(
        "--derisk-scale-grid",
        nargs="*",
        type=float,
        default=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
        help="Derisk scale grid after trigger.",
    )
    parser.add_argument(
        "--decay-ratio-grid",
        nargs="*",
        type=float,
        default=[0.40],
        help="Decay ratio threshold grid. Trigger when active score / trade peak score <= threshold.",
    )
    parser.add_argument(
        "--recovery-ratio-grid",
        nargs="*",
        type=float,
        default=[0.70],
        help="Recovery ratio threshold grid. Recover when active score / trade peak score >= threshold.",
    )
    parser.add_argument("--top-n", type=int, default=20, help="Number of top rows to save.")
    args = parser.parse_args()

    mod = _load_module(BASE_SCRIPT, "adk_pair_score_peak_decay_mod")
    cn_close, cn_dk_close = _load_local_cn_data(mod, Path(args.csv))
    base_result = mod.run_dk_strategy(cn_close.copy(), cn_dk_close.copy())

    rows = [_evaluate_result(mod, "baseline_no_dd_gate", base_result)]
    base_metrics = rows[0]
    variants = _build_param_grid(args.decay_ratio_grid, args.recovery_ratio_grid, args.derisk_scale_grid)
    for cfg in variants:
        overlaid = apply_pair_score_peak_decay_overlay(
            base_result,
            decay_ratio_threshold=cfg["decay_ratio_threshold"],
            recovery_ratio_threshold=cfg["recovery_ratio_threshold"],
            derisk_scale=cfg["derisk_scale"],
            commission=float(getattr(mod, "CN_COMMISSION", 0.0)),
        )
        name = (
            f"pair_score_decay{int(round(cfg['decay_ratio_threshold'] * 100))}"
            f"_rec{int(round(cfg['recovery_ratio_threshold'] * 100))}"
            f"_x{cfg['derisk_scale']:.2f}"
        ).replace(".", "p")
        row = _evaluate_result(mod, name, overlaid, meta=overlaid.attrs.get("pair_score_peak_decay_overlay", {}))
        row["annual_delta"] = row["annual"] - base_metrics["annual"]
        row["max_dd_delta"] = row["max_dd"] - base_metrics["max_dd"]
        row["sharpe_delta"] = row["sharpe"] - base_metrics["sharpe"]
        row["calmar_delta"] = row["calmar"] - base_metrics["calmar"]
        rows.append(row)

    result = pd.DataFrame(rows)
    for col in ["annual_delta", "max_dd_delta", "sharpe_delta", "calmar_delta"]:
        if col not in result.columns:
            result[col] = 0.0
    result = result.sort_values(
        ["calmar_delta", "max_dd_delta", "annual_delta", "sharpe_delta"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    result.to_csv(Path(args.output), index=False, encoding="utf-8-sig")

    top = result[result["variant"] != "baseline_no_dd_gate"].head(args.top_n).copy()
    top.to_csv(Path(args.top_output), index=False, encoding="utf-8-sig")

    display_cols = [
        "variant",
        "decay_ratio_threshold",
        "recovery_ratio_threshold",
        "derisk_scale",
        "annual",
        "max_dd",
        "sharpe",
        "calmar",
        "annual_delta",
        "max_dd_delta",
        "overlay_ratio",
        "trigger_count",
    ]
    print(result[display_cols].head(args.top_n + 1).to_string(index=False))
    print(f"\nSaved: {args.output}")
    print(f"Saved top: {args.top_output}")


if __name__ == "__main__":
    main()

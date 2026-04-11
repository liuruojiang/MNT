import argparse
import importlib.util
import itertools
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = ROOT.parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))
from local_data_refresh import refresh_cn_strategy_data

BASE_SCRIPT = ROOT / "mnt_bot V 6.4 plus_adk_three_state_test.py"
if not BASE_SCRIPT.exists():
    BASE_SCRIPT = WORKSPACE_ROOT / "mnt_bot V 6.4 plus.py"
LOCAL_CN_CSV = WORKSPACE_ROOT / "mnt_strategy_data_cn.csv"
DEFAULT_OUTPUT = ROOT / "adk_pair_switch_ratio_scan_results.csv"


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


def _build_pair_tables(mod, cn_close, cn_dk_close):
    idx_series = {}
    for name, info in mod.CN_DK_INDICES.items():
        src_df = cn_dk_close if info["src"] == "dk" else cn_close
        if info["col"] in src_df.columns:
            idx_series[name] = src_df[info["col"]]

    pair_rets = {}
    pair_abs_mom = {}
    pair_data = {}
    for a_name, b_name in itertools.combinations(idx_series.keys(), 2):
        label = f"{a_name}/{b_name}"
        ret, abs_mom, pdata = mod._run_single_pair_dk(idx_series[a_name], idx_series[b_name])
        if ret is not None:
            pair_rets[label] = ret
            pair_abs_mom[label] = abs_mom
            pair_data[label] = pdata

    if not pair_rets:
        raise RuntimeError("no valid DK pairs")

    rets_df = pd.DataFrame(pair_rets)
    signals_df = pd.DataFrame(pair_abs_mom)
    return rets_df, signals_df, pair_data


def _run_dk_with_switch_ratio(mod, cn_close, cn_dk_close, switch_ratio):
    rets_df, signals_df, pair_data = _build_pair_tables(mod, cn_close, cn_dk_close)
    score_df = signals_df.shift(1)
    common_idx = rets_df.index.intersection(score_df.index)
    rets_df = rets_df.reindex(common_idx)
    score_df = score_df.reindex(common_idx)

    selected_pairs = []
    selected_dirs = []
    returns = []
    weights = []
    scale_raws = []
    realized_vols = []
    blocked_switches = 0
    successful_switches = 0
    score_ratios = []

    current_pair = "none"
    for date in common_idx:
        row_sig = score_df.loc[date].dropna()
        chosen_pair = "none"
        direction = 0
        day_ret = 0.0
        weight = 1.0
        scale_raw = 1.0
        realized_vol = np.nan

        if len(row_sig) > 0:
            best_pair = row_sig.idxmax()
            best_score = float(row_sig.loc[best_pair])
            if current_pair == "none" or current_pair not in row_sig.index:
                chosen_pair = best_pair
            else:
                current_score = float(row_sig.loc[current_pair])
                ratio = (best_score / current_score) if current_score > 1e-12 else float("inf")
                score_ratios.append(ratio)
                if best_pair != current_pair and ratio >= switch_ratio:
                    chosen_pair = best_pair
                    successful_switches += 1
                else:
                    chosen_pair = current_pair
                    if best_pair != current_pair:
                        blocked_switches += 1
            current_pair = chosen_pair

        if chosen_pair != "none" and chosen_pair in pair_data and date in pair_data[chosen_pair].index:
            pdata = pair_data[chosen_pair].loc[date]
            direction = int(pdata["signal"]) if "signal" in pdata.index and not pd.isna(pdata["signal"]) else 0
            ret_val = rets_df.loc[date, chosen_pair] if chosen_pair in rets_df.columns else np.nan
            day_ret = float(ret_val) if not pd.isna(ret_val) else 0.0
            weight = float(pdata["scale"]) if "scale" in pdata.index and not pd.isna(pdata["scale"]) else 1.0
            scale_raw = float(pdata["scale_raw"]) if "scale_raw" in pdata.index and not pd.isna(pdata["scale_raw"]) else weight
            realized_vol = float(pdata["realized_vol"]) if "realized_vol" in pdata.index and not pd.isna(pdata["realized_vol"]) else np.nan

        selected_pairs.append(chosen_pair)
        selected_dirs.append(direction)
        returns.append(day_ret)
        weights.append(weight)
        scale_raws.append(scale_raw)
        realized_vols.append(realized_vol)

    top_pair_series = pd.Series(selected_pairs, index=common_idx)
    direction_series = pd.Series(selected_dirs, index=common_idx)
    pair_changed = top_pair_series.ne(top_pair_series.shift(1))
    direction_changed = direction_series.ne(direction_series.shift(1))
    is_signal = pair_changed | direction_changed
    if len(is_signal) > 0:
        pair_changed.iloc[0] = False
        direction_changed.iloc[0] = False
        is_signal.iloc[0] = False

    pair_a_list = []
    pair_b_list = []
    long_leg_list = []
    short_leg_list = []
    for pair, direction in zip(selected_pairs, selected_dirs):
        if pair == "none" or direction == 0:
            pair_a_list.append(None)
            pair_b_list.append(None)
            long_leg_list.append(None)
            short_leg_list.append(None)
            continue
        a_leg, b_leg = pair.split("/", 1)
        pair_a_list.append(a_leg)
        pair_b_list.append(b_leg)
        if direction == 1:
            long_leg_list.append(a_leg)
            short_leg_list.append(b_leg)
        else:
            long_leg_list.append(b_leg)
            short_leg_list.append(a_leg)

    result = pd.DataFrame(
        {
            "return": pd.Series(returns, index=common_idx),
            "nav": (1 + pd.Series(returns, index=common_idx)).cumprod(),
            "top_pair": top_pair_series,
            "direction": direction_series,
            "holding": [f"{p}_{d}" for p, d in zip(selected_pairs, selected_dirs)],
            "pair_a": pair_a_list,
            "pair_b": pair_b_list,
            "long_leg": long_leg_list,
            "short_leg": short_leg_list,
            "pair_changed": pair_changed,
            "direction_changed": direction_changed,
            "is_signal": is_signal,
            "target": None,
            "weight": weights,
            "scale_raw": scale_raws,
            "realized_vol": realized_vols,
        },
        index=common_idx,
    )
    result.attrs["pair_data"] = pair_data
    result.attrs["signals_df"] = signals_df
    result.attrs["blocked_switches"] = blocked_switches
    result.attrs["successful_switches"] = successful_switches
    result.attrs["avg_score_ratio"] = float(np.mean(score_ratios)) if score_ratios else np.nan
    result.attrs["median_score_ratio"] = float(np.median(score_ratios)) if score_ratios else np.nan
    return result


def _evaluate_variant(mod, cn_close, cn_dk_close, name, switch_ratio=None):
    if switch_ratio is None:
        dk_result = mod.run_dk_strategy(cn_close.copy(), cn_dk_close.copy())
        blocked_switches = 0
        successful_switches = int(dk_result["pair_changed"].fillna(False).sum())
        avg_score_ratio = np.nan
        median_score_ratio = np.nan
    else:
        dk_result = _run_dk_with_switch_ratio(mod, cn_close.copy(), cn_dk_close.copy(), float(switch_ratio))
        blocked_switches = int(dk_result.attrs.get("blocked_switches", 0))
        successful_switches = int(dk_result.attrs.get("successful_switches", 0))
        avg_score_ratio = dk_result.attrs.get("avg_score_ratio", np.nan)
        median_score_ratio = dk_result.attrs.get("median_score_ratio", np.nan)

    ret = dk_result["return"].dropna()
    metrics = mod.calc_daily_metrics(ret, mod.CN_RF_DAILY, mod.CN_DK_TRADING_DAYS)
    if metrics is None:
        raise RuntimeError(f"insufficient data for variant: {name}")

    rebalances = mod.extract_dk_rebalances(dk_result, cn_dk_close=cn_dk_close)
    row = {
        "variant": name,
        "switch_ratio": switch_ratio,
        "annual": metrics["annual"],
        "max_dd": metrics["max_dd"],
        "sharpe": metrics["sharpe"],
        "calmar": metrics["calmar"],
        "vol": metrics["vol"],
        "total_return": metrics["total_return"],
        "monthly_win_rate": metrics["win_rate"],
        "signal_days": int(dk_result["is_signal"].fillna(False).sum()),
        "rebalanced_days": len(rebalances),
        "pair_changes": int(dk_result["pair_changed"].fillna(False).sum()),
        "direction_changes": int(dk_result["direction_changed"].fillna(False).sum()),
        "blocked_switches": blocked_switches,
        "successful_switches": successful_switches,
        "avg_score_ratio": avg_score_ratio,
        "median_score_ratio": median_score_ratio,
    }
    return row


def main():
    parser = argparse.ArgumentParser(description="Scan ADK pair-switch ratio thresholds using local CN csv data.")
    parser.add_argument(
        "--ratios",
        nargs="*",
        default=["1.02", "1.05", "1.10", "1.15", "1.20", "1.30", "1.50", "2.00"],
        help="Minimum relative score ratio required to switch to a new Top-1 pair.",
    )
    parser.add_argument("--csv", default=str(LOCAL_CN_CSV), help="Local CN data csv path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Summary csv output path.")
    args = parser.parse_args()

    mod = _load_module(BASE_SCRIPT, "adk_ratio_mod")
    cn_close, cn_dk_close = _load_local_cn_data(mod, Path(args.csv))

    rows = [_evaluate_variant(mod, cn_close, cn_dk_close, "baseline_top1")]
    for ratio in args.ratios:
        ratio_value = float(ratio)
        label = f"pair_ratio_{ratio_value:g}"
        rows.append(_evaluate_variant(mod, cn_close, cn_dk_close, label, switch_ratio=ratio_value))

    result = pd.DataFrame(rows)
    result = result.sort_values(["max_dd", "sharpe", "annual"], ascending=[False, False, False]).reset_index(drop=True)
    output_path = Path(args.output)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")

    display_cols = [
        "variant",
        "switch_ratio",
        "annual",
        "max_dd",
        "sharpe",
        "calmar",
        "pair_changes",
        "blocked_switches",
        "rebalanced_days",
    ]
    print(result[display_cols].to_string(index=False))
    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()

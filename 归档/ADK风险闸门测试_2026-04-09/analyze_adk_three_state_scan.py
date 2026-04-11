import argparse
import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = ROOT.parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))
from local_data_refresh import refresh_cn_strategy_data

BASE_SCRIPT = ROOT / "mnt_bot V 6.4 plus_adk_three_state_test.py"
if not BASE_SCRIPT.exists():
    BASE_SCRIPT = WORKSPACE_ROOT / "mnt_bot V 6.4 plus.py"
TEST_SCRIPT = ROOT / "mnt_bot V 6.4 plus_adk_three_state_test.py"
LOCAL_CN_CSV = WORKSPACE_ROOT / "mnt_strategy_data_cn.csv"
DEFAULT_OUTPUT = ROOT / "adk_three_state_scan_results.csv"


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


def _evaluate_variant(mod, cn_close, cn_dk_close, name, signal_enter=None, signal_exit=None):
    if signal_enter is not None:
        mod.CN_DK_SIGNAL_ENTER = float(signal_enter)
    if signal_exit is not None:
        mod.CN_DK_SIGNAL_EXIT = float(signal_exit)

    dk_result = mod.run_dk_strategy(cn_close.copy(), cn_dk_close.copy())
    ret = dk_result["return"].dropna()
    metrics = mod.calc_daily_metrics(ret, mod.CN_RF_DAILY, mod.CN_DK_TRADING_DAYS)
    if metrics is None:
        raise RuntimeError(f"insufficient data for variant: {name}")

    rebalances = mod.extract_dk_rebalances(dk_result, cn_dk_close=cn_dk_close)
    direction = dk_result["direction"].fillna(0).astype(int)
    row = {
        "variant": name,
        "signal_enter": signal_enter,
        "signal_exit": signal_exit,
        "start": ret.index[0].strftime("%Y-%m-%d"),
        "end": ret.index[-1].strftime("%Y-%m-%d"),
        "days": len(ret),
        "total_return": metrics["total_return"],
        "annual": metrics["annual"],
        "vol": metrics["vol"],
        "sharpe": metrics["sharpe"],
        "max_dd": metrics["max_dd"],
        "calmar": metrics["calmar"],
        "monthly_win_rate": metrics["win_rate"],
        "signal_days": int(dk_result["is_signal"].fillna(False).sum()),
        "rebalanced_days": len(rebalances),
        "pair_changes": int(dk_result["pair_changed"].fillna(False).sum()),
        "direction_changes": int(dk_result["direction_changed"].fillna(False).sum()),
        "cash_days": int(direction.eq(0).sum()),
        "cash_ratio": float(direction.eq(0).mean()),
        "avg_weight": float(dk_result["weight"].dropna().mean()) if "weight" in dk_result.columns else None,
        "avg_realized_vol": float(dk_result["realized_vol"].dropna().mean()) if "realized_vol" in dk_result.columns else None,
        "end_nav": float(dk_result["nav"].dropna().iloc[-1]),
    }
    return row


def _parse_variant_tokens(tokens):
    parsed = []
    for token in tokens:
        if ":" not in token:
            raise ValueError(f"invalid variant token: {token}; expected enter:exit")
        enter_s, exit_s = token.split(":", 1)
        parsed.append((float(enter_s), float(exit_s)))
    return parsed


def main():
    parser = argparse.ArgumentParser(description="Scan ADK three-state thresholds using local CN csv data.")
    parser.add_argument(
        "--variants",
        nargs="*",
        default=["5:2", "7:3", "10:4"],
        help="Three-state threshold pairs in enter:exit format.",
    )
    parser.add_argument(
        "--csv",
        default=str(LOCAL_CN_CSV),
        help="Local CN data csv path. Default: mnt_strategy_data_cn.csv",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Summary csv output path.",
    )
    args = parser.parse_args()

    base_mod = _load_module(BASE_SCRIPT, "adk_base_mod")
    test_mod = _load_module(TEST_SCRIPT, "adk_three_state_mod")
    cn_close, cn_dk_close = _load_local_cn_data(test_mod, Path(args.csv))

    rows = []
    rows.append(_evaluate_variant(base_mod, cn_close, cn_dk_close, "baseline_two_state"))
    for enter_thr, exit_thr in _parse_variant_tokens(args.variants):
        label = f"three_state_{enter_thr:g}_{exit_thr:g}"
        rows.append(
            _evaluate_variant(
                test_mod,
                cn_close,
                cn_dk_close,
                label,
                signal_enter=enter_thr,
                signal_exit=exit_thr,
            )
        )

    result = pd.DataFrame(rows)
    sort_cols = ["max_dd", "sharpe", "annual"]
    result = result.sort_values(sort_cols, ascending=[False, False, False]).reset_index(drop=True)
    output_path = Path(args.output)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")

    display_cols = [
        "variant",
        "signal_enter",
        "signal_exit",
        "annual",
        "max_dd",
        "sharpe",
        "calmar",
        "cash_ratio",
        "signal_days",
        "rebalanced_days",
    ]
    print(result[display_cols].to_string(index=False))
    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()

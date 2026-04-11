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
from local_data_refresh import filter_market_sessions, refresh_us_strategy_data

BASE_SCRIPT = ROOT / "mnt_bot V 6.4 plus_adk_three_state_test.py"
if not BASE_SCRIPT.exists():
    BASE_SCRIPT = WORKSPACE_ROOT / "mnt_bot V 6.4 plus.py"
LOCAL_US_CSV = WORKSPACE_ROOT / "mnt_strategy_data_us.csv"
DEFAULT_OUTPUT = ROOT / "subc_risk_gate_scan_results.csv"


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


def _load_local_us_prod_data(mod, csv_path: Path):
    refresh_us_strategy_data(csv_path=csv_path, base_script_path=BASE_SCRIPT, verbose=False)
    df = pd.read_csv(csv_path)
    if "date" not in df.columns:
        raise ValueError(f"missing date column in {csv_path}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    needed = {cfg["proxy"] for cfg in mod.PROD_PORTFOLIO.values()} | {mod.PROD_CASH}
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"local US csv missing Sub-C columns: {missing}")
    anchor_cols = [c for c in sorted(needed) if c != "BTC-USD"]
    us_prod_daily = filter_market_sessions(df[sorted(needed)].copy(), anchor_cols).ffill().dropna()
    return us_prod_daily


def _build_subc_daily(mod, us_prod_daily):
    prod_monthly = us_prod_daily.resample("M").last()
    prod_sig_a = mod.make_abs_mom_signals(prod_monthly, mod.PROD_ABS_MOM_LB)
    prod_sig_b = mod.make_sma_signals(prod_monthly, mod.PROD_SMA_WINDOW, mod.PROD_SMA_BAND)
    if not mod.PROD_USE_TIMING:
        prod_sig_a = pd.DataFrame(1.0, index=prod_sig_a.index, columns=prod_sig_a.columns)
        prod_sig_b = prod_sig_a.copy()
    subc_daily = mod._get_subc_daily_ret(us_prod_daily, prod_sig_a, prod_sig_b=prod_sig_b)
    return subc_daily


def _apply_risk_gate(mod, subc_ret, enter, scale_defense, exit_value=None, cooldown_days=0):
    base_ret = subc_ret.fillna(0.0)
    base_nav = (1.0 + base_ret).cumprod()
    base_dd = base_nav / base_nav.cummax() - 1.0

    gated_ret = []
    gate_on = []
    gate_scale = []
    condition_days = 0
    gate_entries = 0
    cooldown_left = 0
    prev_scale = 1.0

    for i, dt in enumerate(base_ret.index):
        if i == 0:
            cur_scale = 1.0
        else:
            prev_dt = base_ret.index[i - 1]
            prev_base_dd = float(base_dd.loc[prev_dt])
            trigger = prev_base_dd <= -enter
            if exit_value is None:
                release_ready = prev_base_dd > -enter
            else:
                release_ready = prev_base_dd >= -exit_value

            if trigger:
                condition_days += 1
                if prev_scale >= 0.999999:
                    gate_entries += 1
                cooldown_left = max(cooldown_left, cooldown_days)
                cur_scale = scale_defense
            elif prev_scale < 0.999999:
                if cooldown_left > 0:
                    cooldown_left -= 1
                    cur_scale = scale_defense
                else:
                    cur_scale = 1.0 if release_ready else scale_defense
            else:
                cur_scale = 1.0

        final_ret = base_ret.iloc[i] * cur_scale
        gated_ret.append(final_ret)
        gate_on.append(cur_scale < 0.999999)
        gate_scale.append(cur_scale)
        prev_scale = cur_scale

    gated_ret = pd.Series(gated_ret, index=base_ret.index)
    result = pd.DataFrame(
        {
            "return": gated_ret,
            "nav": (1.0 + gated_ret).cumprod(),
            "risk_gate_on": pd.Series(gate_on, index=base_ret.index),
            "risk_gate_scale": pd.Series(gate_scale, index=base_ret.index),
        },
        index=base_ret.index,
    )
    result.attrs["risk_gate"] = {
        "enter": enter,
        "exit": exit_value,
        "scale_defense": scale_defense,
        "cooldown_days": cooldown_days,
        "condition_days": condition_days,
        "gate_entries": gate_entries,
    }
    return result


def _evaluate_result(mod, name, result, gate_meta=None):
    ret = result["return"].dropna()
    metrics = mod.calc_daily_metrics(ret, 0.0, mod.US_TRADING_DAYS)
    if metrics is None:
        raise RuntimeError(f"insufficient data for variant: {name}")

    row = {
        "variant": name,
        "enter": gate_meta.get("enter") if gate_meta else None,
        "exit": gate_meta.get("exit") if gate_meta else None,
        "scale_defense": gate_meta.get("scale_defense") if gate_meta else None,
        "cooldown_days": gate_meta.get("cooldown_days") if gate_meta else None,
        "annual": metrics["annual"],
        "max_dd": metrics["max_dd"],
        "sharpe": metrics["sharpe"],
        "calmar": metrics["calmar"],
        "vol": metrics["vol"],
        "total_return": metrics["total_return"],
        "monthly_win_rate": metrics["win_rate"],
        "gate_days": int(result["risk_gate_on"].fillna(False).sum()) if "risk_gate_on" in result.columns else 0,
        "gate_ratio": float(result["risk_gate_on"].fillna(False).mean()) if "risk_gate_on" in result.columns else 0.0,
        "avg_scale": float(result["risk_gate_scale"].mean()) if "risk_gate_scale" in result.columns else 1.0,
        "condition_days": gate_meta.get("condition_days") if gate_meta else 0,
        "gate_entries": gate_meta.get("gate_entries") if gate_meta else 0,
    }
    return row


def _parse_variant(token):
    parts = token.split(":")
    if len(parts) < 3:
        raise ValueError(f"invalid variant token: {token}; expected enter:scale:exit[:cooldown]")
    enter = float(parts[0]) / 100.0
    scale_defense = float(parts[1])
    exit_value = float(parts[2]) / 100.0 if parts[2] != "" else None
    cooldown_days = int(float(parts[3])) if len(parts) >= 4 and parts[3] != "" else 0
    return {"enter": enter, "scale_defense": scale_defense, "exit": exit_value, "cooldown_days": cooldown_days}


def main():
    parser = argparse.ArgumentParser(description="Scan Sub-C drawdown gates using local US data.")
    parser.add_argument(
        "--variants",
        nargs="*",
        default=[
            "10:0.5:5",
            "12:0.5:6",
            "15:0.5:8",
            "10:0.0:5",
            "12:0.0:6",
            "15:0.0:8",
        ],
        help="Variants in enter:scale:exit[:cooldown] format, percent values for enter/exit.",
    )
    parser.add_argument("--csv", default=str(LOCAL_US_CSV), help="Local US data csv path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Summary csv output path.")
    args = parser.parse_args()

    mod = _load_module(BASE_SCRIPT, "subc_base_mod_risk_gate")
    us_prod_daily = _load_local_us_prod_data(mod, Path(args.csv))
    base_daily = _build_subc_daily(mod, us_prod_daily)
    base_result = pd.DataFrame({"return": base_daily, "nav": (1.0 + base_daily).cumprod()}, index=base_daily.index)

    rows = [_evaluate_result(mod, "baseline", base_result)]
    for token in args.variants:
        cfg = _parse_variant(token)
        name = (
            f"dd_{int(round(cfg['enter'] * 100))}"
            f"_x{cfg['scale_defense']:.2f}_e{int(round(cfg['exit'] * 100))}"
            f"_cd{cfg['cooldown_days']}"
        ).replace(".", "p")
        gated = _apply_risk_gate(
            mod,
            base_daily,
            enter=cfg["enter"],
            scale_defense=cfg["scale_defense"],
            exit_value=cfg["exit"],
            cooldown_days=cfg["cooldown_days"],
        )
        rows.append(_evaluate_result(mod, name, gated, gate_meta=gated.attrs.get("risk_gate", {})))

    result = pd.DataFrame(rows)
    result = result.sort_values(["max_dd", "sharpe", "annual"], ascending=[False, False, False]).reset_index(drop=True)
    output_path = Path(args.output)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")

    display_cols = [
        "variant",
        "enter",
        "exit",
        "scale_defense",
        "annual",
        "max_dd",
        "sharpe",
        "calmar",
        "gate_ratio",
        "gate_entries",
    ]
    print(result[display_cols].to_string(index=False))
    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()

import argparse
import importlib.util
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
DEFAULT_OUTPUT = ROOT / "adk_risk_gate_scan_results.csv"


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


def _baseline_dk_result(mod, cn_close, cn_dk_close):
    return mod.run_dk_strategy(cn_close.copy(), cn_dk_close.copy())


def _apply_risk_gate(mod, dk_result, gate_kind, enter, scale_defense, exit_value=None, cooldown_days=0, vol_window=30):
    base_ret = dk_result["return"].fillna(0.0)
    base_weight = dk_result["weight"].fillna(1.0) if "weight" in dk_result.columns else pd.Series(1.0, index=base_ret.index)
    base_nav = (1.0 + base_ret).cumprod()
    base_dd = base_nav / base_nav.cummax() - 1.0
    base_vol = base_ret.rolling(vol_window).std() * np.sqrt(mod.CN_DK_TRADING_DAYS)

    gated_ret = []
    applied_scale = []
    gate_on = []
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
            prev_base_vol = float(base_vol.loc[prev_dt]) if not pd.isna(base_vol.loc[prev_dt]) else np.nan

            trigger = False
            if gate_kind == "dd":
                trigger = prev_base_dd <= -enter
                if exit_value is None:
                    release_ready = prev_base_dd > -enter
                else:
                    release_ready = prev_base_dd >= -exit_value
            elif gate_kind == "vol":
                trigger = not np.isnan(prev_base_vol) and prev_base_vol >= enter
                if exit_value is None:
                    release_ready = np.isnan(prev_base_vol) or prev_base_vol < enter
                else:
                    release_ready = np.isnan(prev_base_vol) or prev_base_vol <= exit_value
            else:
                raise ValueError(f"unsupported gate kind: {gate_kind}")

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

        scaled_ret = base_ret.iloc[i] * cur_scale
        delta_scale = abs(cur_scale - prev_scale)
        overlay_tc = 0.0
        if delta_scale > 1e-12:
            overlay_tc = 2.0 * mod.CN_COMMISSION * delta_scale * float(base_weight.iloc[i])
        final_ret = (1.0 + scaled_ret) * (1.0 - overlay_tc) - 1.0

        gated_ret.append(final_ret)
        applied_scale.append(cur_scale)
        gate_on.append(cur_scale < 0.999999)
        prev_scale = cur_scale

    gated_ret = pd.Series(gated_ret, index=base_ret.index)
    applied_scale = pd.Series(applied_scale, index=base_ret.index)
    gate_on = pd.Series(gate_on, index=base_ret.index)
    nav = (1.0 + gated_ret).cumprod()

    result = dk_result.copy()
    result["return"] = gated_ret
    result["nav"] = nav
    result["risk_gate_scale"] = applied_scale
    result["risk_gate_on"] = gate_on
    result.attrs["risk_gate"] = {
        "kind": gate_kind,
        "enter": enter,
        "exit": exit_value,
        "scale_defense": scale_defense,
        "cooldown_days": cooldown_days,
        "vol_window": vol_window,
        "condition_days": condition_days,
        "gate_entries": gate_entries,
    }
    return result


def _evaluate_result(mod, name, dk_result, gate_meta=None):
    ret = dk_result["return"].dropna()
    metrics = mod.calc_daily_metrics(ret, mod.CN_RF_DAILY, mod.CN_DK_TRADING_DAYS)
    if metrics is None:
        raise RuntimeError(f"insufficient data for variant: {name}")

    rebalances = mod.extract_dk_rebalances(dk_result)
    row = {
        "variant": name,
        "gate_kind": gate_meta.get("kind") if gate_meta else None,
        "enter": gate_meta.get("enter") if gate_meta else None,
        "exit": gate_meta.get("exit") if gate_meta else None,
        "scale_defense": gate_meta.get("scale_defense") if gate_meta else None,
        "cooldown_days": gate_meta.get("cooldown_days") if gate_meta else None,
        "vol_window": gate_meta.get("vol_window") if gate_meta else None,
        "annual": metrics["annual"],
        "max_dd": metrics["max_dd"],
        "sharpe": metrics["sharpe"],
        "calmar": metrics["calmar"],
        "vol": metrics["vol"],
        "total_return": metrics["total_return"],
        "monthly_win_rate": metrics["win_rate"],
        "rebalanced_days": len(rebalances),
        "signal_days": int(dk_result["is_signal"].fillna(False).sum()) if "is_signal" in dk_result.columns else None,
        "gate_days": int(dk_result["risk_gate_on"].fillna(False).sum()) if "risk_gate_on" in dk_result.columns else 0,
        "gate_ratio": float(dk_result["risk_gate_on"].fillna(False).mean()) if "risk_gate_on" in dk_result.columns else 0.0,
        "avg_scale": float(dk_result["risk_gate_scale"].mean()) if "risk_gate_scale" in dk_result.columns else 1.0,
        "condition_days": gate_meta.get("condition_days") if gate_meta else 0,
        "gate_entries": gate_meta.get("gate_entries") if gate_meta else 0,
    }
    return row


def _parse_variant(token):
    parts = token.split(":")
    if len(parts) < 3:
        raise ValueError(f"invalid variant token: {token}; expected kind:enter:scale[:exit][:cooldown][:window]")
    kind = parts[0].strip().lower()
    enter = float(parts[1])
    scale_defense = float(parts[2])
    exit_value = float(parts[3]) if len(parts) >= 4 and parts[3] != "" else None
    cooldown_days = int(float(parts[4])) if len(parts) >= 5 and parts[4] != "" else 0
    vol_window = int(float(parts[5])) if len(parts) >= 6 and parts[5] != "" else 30
    if kind == "dd":
        enter /= 100.0
        if exit_value is not None:
            exit_value /= 100.0
    elif kind == "vol":
        enter /= 100.0
        if exit_value is not None:
            exit_value /= 100.0
    else:
        raise ValueError(f"unsupported gate kind: {kind}")
    return {
        "kind": kind,
        "enter": enter,
        "scale_defense": scale_defense,
        "exit": exit_value,
        "cooldown_days": cooldown_days,
        "vol_window": vol_window,
    }


def main():
    parser = argparse.ArgumentParser(description="Scan ADK strategy-level risk gates using local CN csv data.")
    parser.add_argument(
        "--variants",
        nargs="*",
        default=[
            "dd:8:0.5:4",
            "dd:10:0.5:5",
            "dd:12:0.5:6",
            "dd:8:0.0:4",
            "dd:10:0.0:5",
            "dd:12:0.0:6",
            "dd:10:0.5:5:5",
            "dd:10:0.0:5:5",
            "vol:30:0.5:24::30",
            "vol:35:0.5:28::30",
            "vol:40:0.5:32::30",
        ],
        help="Risk gate variants: kind:enter:scale[:exit][:cooldown][:window]. Percent values for enter/exit.",
    )
    parser.add_argument("--csv", default=str(LOCAL_CN_CSV), help="Local CN data csv path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Summary csv output path.")
    args = parser.parse_args()

    mod = _load_module(BASE_SCRIPT, "adk_base_mod_risk_gate")
    cn_close, cn_dk_close = _load_local_cn_data(mod, Path(args.csv))
    base_result = _baseline_dk_result(mod, cn_close, cn_dk_close)

    rows = [_evaluate_result(mod, "baseline", base_result)]
    for token in args.variants:
        cfg = _parse_variant(token)
        _exit_lbl = "na" if cfg["exit"] is None else f"{int(round(cfg['exit'] * 100))}"
        _cd_lbl = f"cd{cfg['cooldown_days']}"
        _win_lbl = f"w{cfg['vol_window']}" if cfg["kind"] == "vol" else ""
        variant_name = (
            f"{cfg['kind']}_{int(round(cfg['enter'] * 100))}"
            f"_x{cfg['scale_defense']:.1f}_e{_exit_lbl}_{_cd_lbl}{_win_lbl}"
        ).replace(".", "p")
        gated = _apply_risk_gate(
            mod,
            base_result,
            gate_kind=cfg["kind"],
            enter=cfg["enter"],
            scale_defense=cfg["scale_defense"],
            exit_value=cfg["exit"],
            cooldown_days=cfg["cooldown_days"],
            vol_window=cfg["vol_window"],
        )
        rows.append(_evaluate_result(mod, variant_name, gated, gate_meta=gated.attrs.get("risk_gate", {})))

    result = pd.DataFrame(rows)
    result = result.sort_values(["max_dd", "sharpe", "annual"], ascending=[False, False, False]).reset_index(drop=True)
    output_path = Path(args.output)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")

    display_cols = [
        "variant",
        "gate_kind",
        "enter",
        "exit",
        "scale_defense",
        "cooldown_days",
        "annual",
        "max_dd",
        "sharpe",
        "calmar",
        "gate_ratio",
        "condition_days",
        "gate_entries",
    ]
    print(result[display_cols].to_string(index=False))
    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()

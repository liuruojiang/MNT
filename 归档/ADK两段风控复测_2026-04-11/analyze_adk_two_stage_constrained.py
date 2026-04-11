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

BASE_SCRIPT = ROOT / "mnt_bot V 6.5 plus.py"
CN_CSV = ROOT / "mnt_strategy_data_cn.csv"
OUTPUT_CSV = HERE / "adk_two_stage_constrained_results.csv"
TOP_CSV = HERE / "adk_two_stage_constrained_top.csv"


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


def _evaluate_result(mod, name: str, dk_result, meta: dict):
    ret = dk_result["return"].dropna()
    metrics = mod.calc_daily_metrics(ret, mod.CN_RF_DAILY, mod.CN_DK_TRADING_DAYS)
    rebalances = mod.extract_dk_rebalances(dk_result)
    row = {
        "variant": name,
        "stage1_enter": meta.get("stage1_enter"),
        "stage1_exit": meta.get("stage1_exit"),
        "stage1_scale": meta.get("stage1_scale"),
        "stage2_enter": meta.get("stage2_enter"),
        "stage2_exit": meta.get("stage2_exit"),
        "stage2_scale": meta.get("stage2_scale"),
        "annual": metrics["annual"],
        "vol": metrics["vol"],
        "sharpe": metrics["sharpe"],
        "max_dd": metrics["max_dd"],
        "calmar": metrics["calmar"],
        "total_return": metrics["total_return"],
        "monthly_win_rate": metrics["win_rate"],
        "rebalanced_days": len(rebalances),
        "signal_days": int(dk_result["is_signal"].fillna(False).sum()) if "is_signal" in dk_result.columns else None,
        "gate1_ratio": meta.get("gate1_ratio", 0.0),
        "gate2_ratio": meta.get("gate2_ratio", 0.0),
        "avg_scale": meta.get("avg_scale", 1.0),
    }
    return row


def _apply_two_stage_dd_gate(mod, dk_result, stage1, stage2):
    base_ret = dk_result["return"].fillna(0.0)
    base_weight = dk_result["weight"].fillna(1.0)
    base_nav = (1.0 + base_ret).cumprod()
    base_dd = base_nav / base_nav.cummax() - 1.0

    gated_ret = []
    state_list = []
    scale_list = []
    prev_state = 0
    prev_scale = 1.0

    for i, dt in enumerate(base_ret.index):
        if i == 0:
            state = 0
        else:
            prev_dt = base_ret.index[i - 1]
            prev_dd = float(base_dd.loc[prev_dt])
            if prev_state == 0:
                if prev_dd <= -stage2["enter"]:
                    state = 2
                elif prev_dd <= -stage1["enter"]:
                    state = 1
                else:
                    state = 0
            elif prev_state == 1:
                if prev_dd <= -stage2["enter"]:
                    state = 2
                elif prev_dd >= -stage1["exit"]:
                    state = 0
                else:
                    state = 1
            else:
                if prev_dd >= -stage2["exit"]:
                    if prev_dd >= -stage1["exit"]:
                        state = 0
                    else:
                        state = 1
                else:
                    state = 2

        cur_scale = 1.0 if state == 0 else stage1["scale"] if state == 1 else stage2["scale"]
        scaled_ret = base_ret.iloc[i] * cur_scale
        delta_scale = abs(cur_scale - prev_scale)
        overlay_tc = 0.0
        if delta_scale > 1e-12:
            overlay_tc = 2.0 * mod.CN_COMMISSION * delta_scale * float(base_weight.iloc[i])
        final_ret = (1.0 + scaled_ret) * (1.0 - overlay_tc) - 1.0

        gated_ret.append(final_ret)
        state_list.append(state)
        scale_list.append(cur_scale)
        prev_state = state
        prev_scale = cur_scale

    result = dk_result.copy()
    result["raw_return"] = base_ret
    result["raw_nav"] = base_nav
    result["base_weight"] = base_weight
    result["risk_gate_state"] = pd.Series(state_list, index=base_ret.index)
    result["risk_gate_scale"] = pd.Series(scale_list, index=base_ret.index)
    result["risk_gate_on"] = result["risk_gate_state"] > 0
    result["risk_gate_base_dd"] = base_dd
    result["return"] = pd.Series(gated_ret, index=base_ret.index)
    result["nav"] = (1.0 + result["return"]).cumprod()
    result["weight"] = result["base_weight"] * result["risk_gate_scale"]
    result.attrs["risk_gate"] = {
        "stage1_enter": stage1["enter"],
        "stage1_exit": stage1["exit"],
        "stage1_scale": stage1["scale"],
        "stage2_enter": stage2["enter"],
        "stage2_exit": stage2["exit"],
        "stage2_scale": stage2["scale"],
        "gate1_ratio": float((result["risk_gate_state"] == 1).mean()),
        "gate2_ratio": float((result["risk_gate_state"] == 2).mean()),
        "avg_scale": float(result["risk_gate_scale"].mean()),
    }
    return result


def _single_stage_meta(mod):
    return {
        "stage1_enter": None,
        "stage1_exit": None,
        "stage1_scale": None,
        "stage2_enter": mod.CN_DK_RISK_GATE_ENTER,
        "stage2_exit": mod.CN_DK_RISK_GATE_EXIT,
        "stage2_scale": mod.CN_DK_RISK_GATE_DEFENSE_SCALE,
    }


def _family_variants():
    variants = []

    # Family A: light buffer + current hard gate
    for enter1 in (0.08, 0.09, 0.10):
        for exit1 in (0.05, 0.06, 0.07):
            if exit1 >= enter1:
                continue
            for scale1 in (0.85, 0.90):
                variants.append(
                    (
                        "buffer_plus_current_hard",
                        {"enter": enter1, "exit": exit1, "scale": scale1},
                        {"enter": 0.15, "exit": 0.08, "scale": 0.50},
                    )
                )

    # Family B: light buffer + slightly deeper hard gate
    for enter1 in (0.08, 0.09, 0.10):
        for exit1 in (0.05, 0.06, 0.07):
            if exit1 >= enter1:
                continue
            for scale1 in (0.85, 0.90):
                for enter2, exit2, scale2 in (
                    (0.16, 0.10, 0.50),
                    (0.16, 0.10, 0.45),
                    (0.18, 0.12, 0.50),
                    (0.18, 0.12, 0.45),
                ):
                    variants.append(
                        (
                            "buffer_plus_deeper_hard",
                            {"enter": enter1, "exit": exit1, "scale": scale1},
                            {"enter": enter2, "exit": exit2, "scale": scale2},
                        )
                    )

    # Family C: current hard gate softened + deep crash brake
    for exit1 in (0.08, 0.10):
        for scale1 in (0.70, 0.80):
            for enter2, exit2, scale2 in (
                (0.20, 0.12, 0.40),
                (0.20, 0.14, 0.40),
                (0.22, 0.14, 0.35),
                (0.22, 0.14, 0.30),
            ):
                variants.append(
                    (
                        "hard_plus_crash_brake",
                        {"enter": 0.15, "exit": exit1, "scale": scale1},
                        {"enter": enter2, "exit": exit2, "scale": scale2},
                    )
                )

    deduped = []
    seen = set()
    for family, s1, s2 in variants:
        key = (family, s1["enter"], s1["exit"], s1["scale"], s2["enter"], s2["exit"], s2["scale"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append((family, s1, s2))
    return deduped


def main():
    mod = _load_module(BASE_SCRIPT, "adk_two_stage_constrained_mod")
    cn_close, cn_dk_close = _load_local_cn_data(mod, CN_CSV)

    raw = mod.run_dk_strategy(cn_close.copy(), cn_dk_close.copy())
    single = mod.apply_dk_drawdown_risk_gate(
        raw.copy(),
        enter=mod.CN_DK_RISK_GATE_ENTER,
        scale_defense=mod.CN_DK_RISK_GATE_DEFENSE_SCALE,
        exit_value=mod.CN_DK_RISK_GATE_EXIT,
        cooldown_days=mod.CN_DK_RISK_GATE_COOLDOWN_DAYS,
    )

    rows = []
    single_row = _evaluate_result(mod, "single_stage_15_0p5_8", single, _single_stage_meta(mod))
    rows.append(single_row)

    for family, stage1, stage2 in _family_variants():
        name = (
            f"{family}"
            f"__{int(round(stage1['enter'] * 100))}_{stage1['scale']:.2f}_{int(round(stage1['exit'] * 100))}"
            f"__{int(round(stage2['enter'] * 100))}_{stage2['scale']:.2f}_{int(round(stage2['exit'] * 100))}"
        )
        gated = _apply_two_stage_dd_gate(mod, raw.copy(), stage1=stage1, stage2=stage2)
        row = _evaluate_result(mod, name, gated, gated.attrs.get("risk_gate", {}))
        row["family"] = family
        rows.append(row)

    out = pd.DataFrame(rows)
    base = out[out["variant"] == "single_stage_15_0p5_8"].iloc[0]
    for key, delta_name in (
        ("annual", "delta_annual"),
        ("max_dd", "delta_max_dd"),
        ("sharpe", "delta_sharpe"),
        ("calmar", "delta_calmar"),
    ):
        out[delta_name] = out[key] - float(base[key])

    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    top = out[out["variant"] != "single_stage_15_0p5_8"].copy()
    top = top.sort_values(["calmar", "annual", "max_dd"], ascending=[False, False, False]).head(20)
    top.to_csv(TOP_CSV, index=False, encoding="utf-8-sig")

    print("Baseline single-stage:")
    print(out[out["variant"] == "single_stage_15_0p5_8"].to_string(index=False))
    print("\nTop constrained two-stage candidates:")
    print(top.to_string(index=False))
    print(f"\nSaved: {OUTPUT_CSV}")
    print(f"Saved: {TOP_CSV}")


if __name__ == "__main__":
    main()

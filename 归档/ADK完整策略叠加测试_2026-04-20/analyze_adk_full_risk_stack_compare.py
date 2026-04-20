import argparse
import importlib.util
import sys
import types
from collections import OrderedDict
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_SCRIPT = ROOT / "mnt_bot V 6.6 plus.py"
PAIR_SCORE_SCRIPT = ROOT / "归档" / "ADK信号衰减测试_2026-04-20" / "analyze_adk_pair_score_peak_decay_overlay.py"
CN_CSV = ROOT / "mnt_strategy_data_cn.csv"
COMPARE_CSV = HERE / "adk_full_risk_stack_compare.csv"
WINDOW_CSV = HERE / "adk_full_risk_stack_window_compare.csv"
SUMMARY_MD = HERE / "测试记录_2026-04-20.md"
DD_SCAN_CSV = HERE / "adk_full_risk_stack_dd_gate_scan.csv"
DD_SCAN_TOP_CSV = HERE / "adk_full_risk_stack_dd_gate_scan_top.csv"
DD_SCAN_WINDOW_CSV = HERE / "adk_full_risk_stack_dd_gate_scan_window_compare.csv"
DD_SCAN_SUMMARY_MD = HERE / "DD_gate参数扫描_2026-04-20.md"
PAIR_SCAN_CSV = HERE / "adk_full_risk_stack_pair_score_scan.csv"
PAIR_SCAN_TOP_CSV = HERE / "adk_full_risk_stack_pair_score_scan_top.csv"
PAIR_SCAN_WINDOW_CSV = HERE / "adk_full_risk_stack_pair_score_scan_window_compare.csv"
PAIR_SCAN_SUMMARY_MD = HERE / "Pair_score参数扫描_2026-04-20.md"


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


def _constant_scale(index, value: float) -> pd.Series:
    return pd.Series(float(value), index=index, dtype=float)


def build_dk_drawdown_gate_state(
    dk_result: pd.DataFrame,
    enter: float,
    scale_defense: float,
    exit_value: float,
    cooldown_days: int = 0,
) -> pd.DataFrame:
    if dk_result is None or len(dk_result) == 0:
        return pd.DataFrame(index=getattr(dk_result, "index", None))

    base_ret = dk_result["return"].fillna(0.0)
    base_nav = (1.0 + base_ret).cumprod()
    base_dd = base_nav / base_nav.cummax() - 1.0

    scales = []
    gate_on = []
    cooldown_left = 0
    prev_scale = 1.0

    for i, dt in enumerate(base_ret.index):
        if i == 0:
            cur_scale = 1.0
        else:
            prev_dt = base_ret.index[i - 1]
            prev_dd = float(base_dd.loc[prev_dt])
            trigger = prev_dd <= -enter
            release_ready = prev_dd >= -exit_value if exit_value is not None else prev_dd > -enter
            if trigger:
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

        scales.append(float(cur_scale))
        gate_on.append(bool(cur_scale < 0.999999))
        prev_scale = cur_scale

    return pd.DataFrame(
        {
            "risk_gate_scale": pd.Series(scales, index=base_ret.index, dtype=float),
            "risk_gate_on": pd.Series(gate_on, index=base_ret.index, dtype=bool),
            "risk_gate_base_dd": pd.Series(base_dd, index=base_ret.index, dtype=float),
        },
        index=base_ret.index,
    )


def _apply_scale_path(
    dk_result: pd.DataFrame,
    total_scale: pd.Series,
    commission: float,
    extra_columns: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
    if dk_result is None or len(dk_result) == 0:
        return dk_result

    out = dk_result.copy()
    base_ret = out["return"].fillna(0.0)
    base_weight = out["weight"].fillna(1.0) if "weight" in out.columns else _constant_scale(out.index, 1.0)
    total_scale = total_scale.reindex(out.index).ffill().fillna(1.0).astype(float)

    final_ret = []
    deltas = []
    prev_scale = 1.0
    for dt, cur_scale in total_scale.items():
        delta_scale = abs(float(cur_scale) - float(prev_scale))
        scaled_ret = float(base_ret.loc[dt]) * float(cur_scale)
        overlay_tc = 0.0
        if delta_scale > 1e-12:
            overlay_tc = 2.0 * float(commission) * float(base_weight.loc[dt]) * delta_scale
        realized_ret = (1.0 + scaled_ret) * (1.0 - overlay_tc) - 1.0
        final_ret.append(realized_ret)
        deltas.append(delta_scale)
        prev_scale = float(cur_scale)

    out["raw_return"] = base_ret
    out["base_weight"] = base_weight
    out["combined_scale"] = total_scale
    out["combined_scale_delta"] = pd.Series(deltas, index=out.index, dtype=float)
    out["return"] = pd.Series(final_ret, index=out.index, dtype=float)
    out["nav"] = (1.0 + out["return"]).cumprod()
    out["weight"] = out["base_weight"] * out["combined_scale"]

    if extra_columns:
        for name, series in extra_columns.items():
            out[name] = series.reindex(out.index)

    return out


def apply_dd_gate_risk_stack(
    dk_result: pd.DataFrame,
    dd_enter: float,
    dd_scale_defense: float,
    dd_exit: float,
    dd_cooldown_days: int,
    commission: float,
) -> pd.DataFrame:
    dd_state = build_dk_drawdown_gate_state(
        dk_result,
        enter=dd_enter,
        scale_defense=dd_scale_defense,
        exit_value=dd_exit,
        cooldown_days=dd_cooldown_days,
    )
    out = _apply_scale_path(
        dk_result,
        total_scale=dd_state["risk_gate_scale"],
        commission=commission,
        extra_columns={
            "risk_gate_scale": dd_state["risk_gate_scale"],
            "risk_gate_on": dd_state["risk_gate_on"],
            "risk_gate_base_dd": dd_state["risk_gate_base_dd"],
            "overlay_scale": _constant_scale(dk_result.index, 1.0),
            "overlay_on": pd.Series(False, index=dk_result.index, dtype=bool),
        },
    )
    return out


def apply_pair_score_decay_stack(
    pair_mod,
    dk_result: pd.DataFrame,
    decay_ratio_threshold: float,
    recovery_ratio_threshold: float,
    derisk_scale: float,
    commission: float,
) -> pd.DataFrame:
    score_state = pair_mod.apply_pair_score_peak_decay_overlay(
        dk_result,
        decay_ratio_threshold=decay_ratio_threshold,
        recovery_ratio_threshold=recovery_ratio_threshold,
        derisk_scale=derisk_scale,
        commission=0.0,
    )
    keep_cols = [
        "overlay_scale",
        "overlay_on",
        "overlay_triggered",
        "overlay_recovered",
        "trade_id",
        "active_score_overlay",
        "score_peak_overlay",
        "score_decay_ratio_overlay",
        "waiting_for_new_peak",
    ]
    out = _apply_scale_path(
        dk_result,
        total_scale=score_state["overlay_scale"],
        commission=commission,
        extra_columns={
            "risk_gate_scale": _constant_scale(dk_result.index, 1.0),
            "risk_gate_on": pd.Series(False, index=dk_result.index, dtype=bool),
            "risk_gate_base_dd": pd.Series(0.0, index=dk_result.index, dtype=float),
            **{col: score_state[col] for col in keep_cols},
        },
    )
    return out


def apply_combined_risk_stack(
    dk_result: pd.DataFrame,
    dd_enter: float,
    dd_scale_defense: float,
    dd_exit: float,
    dd_cooldown_days: int,
    decay_ratio_threshold: float,
    recovery_ratio_threshold: float,
    derisk_scale: float,
    commission: float,
) -> pd.DataFrame:
    pair_mod = _load_module(PAIR_SCORE_SCRIPT, "adk_pair_score_peak_decay_overlay_mod_combined")
    dd_state = build_dk_drawdown_gate_state(
        dk_result,
        enter=dd_enter,
        scale_defense=dd_scale_defense,
        exit_value=dd_exit,
        cooldown_days=dd_cooldown_days,
    )
    score_state = pair_mod.apply_pair_score_peak_decay_overlay(
        dk_result,
        decay_ratio_threshold=decay_ratio_threshold,
        recovery_ratio_threshold=recovery_ratio_threshold,
        derisk_scale=derisk_scale,
        commission=0.0,
    )
    combined_scale = dd_state["risk_gate_scale"] * score_state["overlay_scale"]
    keep_cols = [
        "overlay_scale",
        "overlay_on",
        "overlay_triggered",
        "overlay_recovered",
        "trade_id",
        "active_score_overlay",
        "score_peak_overlay",
        "score_decay_ratio_overlay",
        "waiting_for_new_peak",
    ]
    out = _apply_scale_path(
        dk_result,
        total_scale=combined_scale,
        commission=commission,
        extra_columns={
            "risk_gate_scale": dd_state["risk_gate_scale"],
            "risk_gate_on": dd_state["risk_gate_on"],
            "risk_gate_base_dd": dd_state["risk_gate_base_dd"],
            **{col: score_state[col] for col in keep_cols},
        },
    )
    out.attrs["full_risk_stack"] = {
        "dd_enter": dd_enter,
        "dd_scale_defense": dd_scale_defense,
        "dd_exit": dd_exit,
        "dd_cooldown_days": dd_cooldown_days,
        "decay_ratio_threshold": decay_ratio_threshold,
        "recovery_ratio_threshold": recovery_ratio_threshold,
        "derisk_scale": derisk_scale,
        "commission": commission,
    }
    return out


def build_full_risk_stack_variants(
    dk_result: pd.DataFrame,
    dd_enter: float,
    dd_scale_defense: float,
    dd_exit: float,
    dd_cooldown_days: int,
    decay_ratio_threshold: float,
    recovery_ratio_threshold: float,
    derisk_scale: float,
    commission: float,
):
    pair_mod = _load_module(PAIR_SCORE_SCRIPT, "adk_pair_score_peak_decay_overlay_mod_variants")
    variants = OrderedDict()

    baseline = _apply_scale_path(
        dk_result,
        total_scale=_constant_scale(dk_result.index, 1.0),
        commission=commission,
        extra_columns={
            "risk_gate_scale": _constant_scale(dk_result.index, 1.0),
            "risk_gate_on": pd.Series(False, index=dk_result.index, dtype=bool),
            "risk_gate_base_dd": pd.Series(0.0, index=dk_result.index, dtype=float),
            "overlay_scale": _constant_scale(dk_result.index, 1.0),
            "overlay_on": pd.Series(False, index=dk_result.index, dtype=bool),
        },
    )
    variants["baseline_no_dd_gate"] = baseline
    variants["dd_gate_only"] = apply_dd_gate_risk_stack(
        dk_result,
        dd_enter=dd_enter,
        dd_scale_defense=dd_scale_defense,
        dd_exit=dd_exit,
        dd_cooldown_days=dd_cooldown_days,
        commission=commission,
    )
    variants["pair_score_decay_only"] = apply_pair_score_decay_stack(
        pair_mod,
        dk_result,
        decay_ratio_threshold=decay_ratio_threshold,
        recovery_ratio_threshold=recovery_ratio_threshold,
        derisk_scale=derisk_scale,
        commission=commission,
    )
    dd_state = build_dk_drawdown_gate_state(
        dk_result,
        enter=dd_enter,
        scale_defense=dd_scale_defense,
        exit_value=dd_exit,
        cooldown_days=dd_cooldown_days,
    )
    score_state = pair_mod.apply_pair_score_peak_decay_overlay(
        dk_result,
        decay_ratio_threshold=decay_ratio_threshold,
        recovery_ratio_threshold=recovery_ratio_threshold,
        derisk_scale=derisk_scale,
        commission=0.0,
    )
    combined_scale = dd_state["risk_gate_scale"] * score_state["overlay_scale"]
    combined = _apply_scale_path(
        dk_result,
        total_scale=combined_scale,
        commission=commission,
        extra_columns={
            "risk_gate_scale": dd_state["risk_gate_scale"],
            "risk_gate_on": dd_state["risk_gate_on"],
            "risk_gate_base_dd": dd_state["risk_gate_base_dd"],
            "overlay_scale": score_state["overlay_scale"],
            "overlay_on": score_state["overlay_on"],
            "overlay_triggered": score_state["overlay_triggered"],
            "overlay_recovered": score_state["overlay_recovered"],
            "trade_id": score_state["trade_id"],
            "active_score_overlay": score_state["active_score_overlay"],
            "score_peak_overlay": score_state["score_peak_overlay"],
            "score_decay_ratio_overlay": score_state["score_decay_ratio_overlay"],
            "waiting_for_new_peak": score_state["waiting_for_new_peak"],
        },
    )
    variants["dd_gate_plus_pair_score_decay"] = combined
    return variants


def _evaluate_result(mod, name: str, dk_result: pd.DataFrame) -> dict:
    ret = dk_result["return"].dropna()
    metrics = mod.calc_daily_metrics(ret, mod.CN_RF_DAILY, mod.CN_DK_TRADING_DAYS)
    rebalances = mod.extract_dk_rebalances(dk_result)
    return {
        "variant": name,
        "annual": metrics["annual"],
        "vol": metrics["vol"],
        "sharpe": metrics["sharpe"],
        "max_dd": metrics["max_dd"],
        "calmar": metrics["calmar"],
        "total_return": metrics["total_return"],
        "monthly_win_rate": metrics["win_rate"],
        "rebalanced_days": len(rebalances),
        "signal_days": int(dk_result["is_signal"].fillna(False).sum()) if "is_signal" in dk_result.columns else None,
        "risk_gate_days": int(dk_result.get("risk_gate_on", pd.Series(False, index=dk_result.index)).fillna(False).sum()),
        "overlay_days": int(dk_result.get("overlay_on", pd.Series(False, index=dk_result.index)).fillna(False).sum()),
        "combined_derisk_days": int((dk_result["combined_scale"] < 0.999999).sum()) if "combined_scale" in dk_result.columns else 0,
        "avg_combined_scale": float(dk_result["combined_scale"].mean()) if "combined_scale" in dk_result.columns else 1.0,
    }


def _evaluate_windows(mod, name: str, dk_result: pd.DataFrame, windows: list[tuple[str, int]]) -> list[dict]:
    rows = []
    ret = dk_result["return"].dropna()
    for window_name, window_days in windows:
        if len(ret) < window_days:
            continue
        win_ret = ret.iloc[-window_days:]
        metrics = mod.calc_daily_metrics(win_ret, mod.CN_RF_DAILY, mod.CN_DK_TRADING_DAYS)
        rows.append(
            {
                "variant": name,
                "window": window_name,
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


def build_dd_gate_scan_grid(dd_enter_grid, dd_exit_grid, dd_scale_grid):
    variants = []
    for dd_enter in dd_enter_grid:
        for dd_exit in dd_exit_grid:
            if dd_exit >= dd_enter:
                continue
            for dd_scale_defense in dd_scale_grid:
                variants.append(
                    {
                        "dd_enter": float(dd_enter),
                        "dd_exit": float(dd_exit),
                        "dd_scale_defense": float(dd_scale_defense),
                    }
                )
    return variants


def format_dd_gate_variant_name(dd_enter: float, dd_exit: float, dd_scale_defense: float) -> str:
    return (
        f"dd{int(round(dd_enter * 100))}"
        f"_exit{int(round(dd_exit * 100))}"
        f"_x{dd_scale_defense:.2f}"
    ).replace(".", "p")


def build_pair_score_scan_grid(decay_ratio_grid, recovery_ratio_grid, derisk_scale_grid):
    variants = []
    for decay_ratio_threshold in decay_ratio_grid:
        for recovery_ratio_threshold in recovery_ratio_grid:
            if recovery_ratio_threshold <= decay_ratio_threshold:
                continue
            for derisk_scale in derisk_scale_grid:
                variants.append(
                    {
                        "decay_ratio_threshold": float(decay_ratio_threshold),
                        "recovery_ratio_threshold": float(recovery_ratio_threshold),
                        "derisk_scale": float(derisk_scale),
                    }
                )
    return variants


def format_pair_score_variant_name(decay_ratio_threshold: float, recovery_ratio_threshold: float, derisk_scale: float) -> str:
    return (
        f"score_decay{int(round(decay_ratio_threshold * 100))}"
        f"_rec{int(round(recovery_ratio_threshold * 100))}"
        f"_x{derisk_scale:.2f}"
    ).replace(".", "p")


def _write_summary(compare_df: pd.DataFrame, window_df: pd.DataFrame, args, base_result: pd.DataFrame):
    compare_show = compare_df.copy()
    float_cols = [
        "annual",
        "max_dd",
        "sharpe",
        "calmar",
        "annual_delta",
        "max_dd_delta",
        "avg_combined_scale",
    ]
    for col in float_cols:
        if col in compare_show.columns:
            compare_show[col] = compare_show[col].map(lambda x: f"{x:.6f}")

    window_show = window_df.copy()
    for col in ["annual", "max_dd", "sharpe", "calmar"]:
        if col in window_show.columns:
            window_show[col] = window_show[col].map(lambda x: f"{x:.6f}")

    lines = [
        "# ADK 完整策略叠加测试",
        "",
        "## 参数",
        "",
        f"- DD gate: enter={args.dd_enter:.2%}, exit={args.dd_exit:.2%}, defense_scale={args.dd_scale_defense:.2f}, cooldown={args.dd_cooldown_days}",
        f"- Pair-score decay: decay={args.decay_ratio_threshold:.2%}, recover={args.recovery_ratio_threshold:.2%}, derisk_scale={args.derisk_scale:.2f}",
        f"- 数据: {args.csv}",
        f"- 样本区间: {base_result.index.min().date()} -> {base_result.index.max().date()}",
        "",
        "## 全样本对比",
        "",
        compare_show.to_markdown(index=False),
        "",
        "## 分窗口对比",
        "",
        window_show.to_markdown(index=False),
        "",
        "## 口径",
        "",
        "- `baseline_no_dd_gate`: 纯 ADK 原始结果",
        "- `dd_gate_only`: 仅叠加正式 DD gate",
        "- `pair_score_decay_only`: 仅叠加 pair-score peak-decay overlay",
        "- `dd_gate_plus_pair_score_decay`: 两层状态乘成总仓位后只按总仓位变化计一次成本",
    ]
    SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")


def _write_dd_scan_summary(scan_df: pd.DataFrame, top_df: pd.DataFrame, window_df: pd.DataFrame, args, base_result: pd.DataFrame):
    scan_show = scan_df.copy()
    top_show = top_df.copy()
    window_show = window_df.copy()
    for frame in [scan_show, top_show]:
        for col in [
            "annual",
            "max_dd",
            "sharpe",
            "calmar",
            "annual_delta",
            "max_dd_delta",
            "vs_score_only_annual_delta",
            "vs_score_only_max_dd_delta",
        ]:
            if col in frame.columns:
                frame[col] = frame[col].map(lambda x: f"{x:.6f}" if pd.notna(x) else "")
    for col in ["annual", "max_dd", "sharpe", "calmar"]:
        if col in window_show.columns:
            window_show[col] = window_show[col].map(lambda x: f"{x:.6f}" if pd.notna(x) else "")

    lines = [
        "# ADK DD gate 参数扫描",
        "",
        "## 固定参数",
        "",
        f"- Pair-score decay: decay={args.decay_ratio_threshold:.2%}, recover={args.recovery_ratio_threshold:.2%}, derisk_scale={args.derisk_scale:.2f}",
        f"- DD cooldown_days={args.dd_cooldown_days}",
        f"- 数据: {args.csv}",
        f"- 样本区间: {base_result.index.min().date()} -> {base_result.index.max().date()}",
        "",
        "## Top 结果",
        "",
        top_show.to_markdown(index=False),
        "",
        "## Top 窗口对比",
        "",
        window_show.to_markdown(index=False),
        "",
        "## 参考",
        "",
        "- `baseline_no_dd_gate`: 纯 ADK 原始结果",
        "- `pair_score_decay_only`: 固定当前 pair-score 衰减参数，不加 DD gate",
        "- `dd*_exit*_x*`: 在固定 pair-score 参数下扫描 DD gate enter / exit / defense_scale 的组合结果",
    ]
    DD_SCAN_SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")


def _write_pair_scan_summary(scan_df: pd.DataFrame, top_df: pd.DataFrame, window_df: pd.DataFrame, args, base_result: pd.DataFrame):
    top_show = top_df.copy()
    window_show = window_df.copy()
    for frame in [top_show]:
        for col in [
            "annual",
            "max_dd",
            "sharpe",
            "calmar",
            "annual_delta",
            "max_dd_delta",
            "vs_dd_only_annual_delta",
            "vs_dd_only_max_dd_delta",
        ]:
            if col in frame.columns:
                frame[col] = frame[col].map(lambda x: f"{x:.6f}" if pd.notna(x) else "")
    for col in ["annual", "max_dd", "sharpe", "calmar"]:
        if col in window_show.columns:
            window_show[col] = window_show[col].map(lambda x: f"{x:.6f}" if pd.notna(x) else "")

    lines = [
        "# ADK Pair-score 参数扫描",
        "",
        "## 固定参数",
        "",
        f"- Fixed DD gate: enter={args.dd_enter:.2%}, exit={args.dd_exit:.2%}, defense_scale={args.dd_scale_defense:.2f}, cooldown={args.dd_cooldown_days}",
        f"- 数据: {args.csv}",
        f"- 样本区间: {base_result.index.min().date()} -> {base_result.index.max().date()}",
        "",
        "## Top 结果",
        "",
        top_show.to_markdown(index=False),
        "",
        "## Top 窗口对比",
        "",
        window_show.to_markdown(index=False),
        "",
        "## 参考",
        "",
        "- `baseline_no_dd_gate`: 纯 ADK 原始结果",
        "- `dd_gate_only`: 固定 DD gate，不加 pair-score overlay",
        "- `score_decay*_rec*_x*`: 在固定 DD gate 下扫描 pair-score decay / recovery / derisk_scale 的组合结果",
    ]
    PAIR_SCAN_SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")


def run_dd_gate_scan(mod, pair_mod, base_result: pd.DataFrame, args):
    commission = float(getattr(mod, "CN_COMMISSION", 0.0))
    windows = [("1Y", 252), ("3Y", 252 * 3), ("5Y", 252 * 5)]

    baseline = _apply_scale_path(
        base_result,
        total_scale=_constant_scale(base_result.index, 1.0),
        commission=commission,
        extra_columns={
            "risk_gate_scale": _constant_scale(base_result.index, 1.0),
            "risk_gate_on": pd.Series(False, index=base_result.index, dtype=bool),
            "overlay_scale": _constant_scale(base_result.index, 1.0),
            "overlay_on": pd.Series(False, index=base_result.index, dtype=bool),
        },
    )
    score_only = apply_pair_score_decay_stack(
        pair_mod,
        base_result,
        decay_ratio_threshold=args.decay_ratio_threshold,
        recovery_ratio_threshold=args.recovery_ratio_threshold,
        derisk_scale=args.derisk_scale,
        commission=commission,
    )

    score_state = pair_mod.apply_pair_score_peak_decay_overlay(
        base_result,
        decay_ratio_threshold=args.decay_ratio_threshold,
        recovery_ratio_threshold=args.recovery_ratio_threshold,
        derisk_scale=args.derisk_scale,
        commission=0.0,
    )

    grid = build_dd_gate_scan_grid(args.dd_enter_grid, args.dd_exit_grid, args.dd_scale_grid)
    variant_results = OrderedDict(
        {
            "baseline_no_dd_gate": baseline,
            "pair_score_decay_only": score_only,
        }
    )
    for cfg in grid:
        dd_state = build_dk_drawdown_gate_state(
            base_result,
            enter=cfg["dd_enter"],
            scale_defense=cfg["dd_scale_defense"],
            exit_value=cfg["dd_exit"],
            cooldown_days=args.dd_cooldown_days,
        )
        combined = _apply_scale_path(
            base_result,
            total_scale=dd_state["risk_gate_scale"] * score_state["overlay_scale"],
            commission=commission,
            extra_columns={
                "risk_gate_scale": dd_state["risk_gate_scale"],
                "risk_gate_on": dd_state["risk_gate_on"],
                "risk_gate_base_dd": dd_state["risk_gate_base_dd"],
                "overlay_scale": score_state["overlay_scale"],
                "overlay_on": score_state["overlay_on"],
                "overlay_triggered": score_state["overlay_triggered"],
                "overlay_recovered": score_state["overlay_recovered"],
                "trade_id": score_state["trade_id"],
                "active_score_overlay": score_state["active_score_overlay"],
                "score_peak_overlay": score_state["score_peak_overlay"],
                "score_decay_ratio_overlay": score_state["score_decay_ratio_overlay"],
                "waiting_for_new_peak": score_state["waiting_for_new_peak"],
            },
        )
        variant_results[format_dd_gate_variant_name(**cfg)] = combined

    rows = []
    for name, result in variant_results.items():
        row = _evaluate_result(mod, name, result)
        if name.startswith("dd"):
            parts = name.split("_")
            row["dd_enter"] = int(parts[0][2:]) / 100.0
            row["dd_exit"] = int(parts[1][4:]) / 100.0
            row["dd_scale_defense"] = float(parts[2][1:].replace("p", "."))
        else:
            row["dd_enter"] = None
            row["dd_exit"] = None
            row["dd_scale_defense"] = None
        rows.append(row)

    scan_df = pd.DataFrame(rows)
    baseline_row = scan_df.loc[scan_df["variant"] == "baseline_no_dd_gate"].iloc[0]
    score_only_row = scan_df.loc[scan_df["variant"] == "pair_score_decay_only"].iloc[0]
    scan_df["annual_delta"] = scan_df["annual"] - float(baseline_row["annual"])
    scan_df["max_dd_delta"] = scan_df["max_dd"] - float(baseline_row["max_dd"])
    scan_df["vs_score_only_annual_delta"] = scan_df["annual"] - float(score_only_row["annual"])
    scan_df["vs_score_only_max_dd_delta"] = scan_df["max_dd"] - float(score_only_row["max_dd"])
    scan_df.to_csv(Path(args.output), index=False, encoding="utf-8-sig")

    top_df = scan_df[scan_df["variant"].str.startswith("dd")].copy()
    top_df = top_df.sort_values(
        ["vs_score_only_max_dd_delta", "vs_score_only_annual_delta", "calmar", "sharpe"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    top_df.to_csv(Path(args.top_output), index=False, encoding="utf-8-sig")
    top_n = top_df.head(args.top_n).copy()

    selected_names = ["baseline_no_dd_gate", "pair_score_decay_only"] + top_n["variant"].tolist()
    window_rows = []
    for name in selected_names:
        window_rows.extend(_evaluate_windows(mod, name, variant_results[name], windows))
    window_df = pd.DataFrame(window_rows)
    window_df.to_csv(Path(args.window_output), index=False, encoding="utf-8-sig")
    _write_dd_scan_summary(scan_df, top_n, window_df, args, base_result)

    display_cols = [
        "variant",
        "dd_enter",
        "dd_exit",
        "dd_scale_defense",
        "annual",
        "max_dd",
        "sharpe",
        "calmar",
        "vs_score_only_annual_delta",
        "vs_score_only_max_dd_delta",
    ]
    print(scan_df[scan_df["variant"].isin(selected_names)][display_cols].to_string(index=False))
    print(f"\nSaved: {args.output}")
    print(f"Saved top: {args.top_output}")
    print(f"Saved windows: {args.window_output}")
    print(f"Saved summary: {DD_SCAN_SUMMARY_MD}")


def run_pair_score_scan(mod, pair_mod, base_result: pd.DataFrame, args):
    commission = float(getattr(mod, "CN_COMMISSION", 0.0))
    windows = [("1Y", 252), ("3Y", 252 * 3), ("5Y", 252 * 5)]

    baseline = _apply_scale_path(
        base_result,
        total_scale=_constant_scale(base_result.index, 1.0),
        commission=commission,
        extra_columns={
            "risk_gate_scale": _constant_scale(base_result.index, 1.0),
            "risk_gate_on": pd.Series(False, index=base_result.index, dtype=bool),
            "overlay_scale": _constant_scale(base_result.index, 1.0),
            "overlay_on": pd.Series(False, index=base_result.index, dtype=bool),
        },
    )
    dd_gate_only = apply_dd_gate_risk_stack(
        base_result,
        dd_enter=args.dd_enter,
        dd_scale_defense=args.dd_scale_defense,
        dd_exit=args.dd_exit,
        dd_cooldown_days=args.dd_cooldown_days,
        commission=commission,
    )
    dd_state = build_dk_drawdown_gate_state(
        base_result,
        enter=args.dd_enter,
        scale_defense=args.dd_scale_defense,
        exit_value=args.dd_exit,
        cooldown_days=args.dd_cooldown_days,
    )

    grid = build_pair_score_scan_grid(args.decay_ratio_grid, args.recovery_ratio_grid, args.derisk_scale_grid)
    variant_results = OrderedDict(
        {
            "baseline_no_dd_gate": baseline,
            "dd_gate_only": dd_gate_only,
        }
    )
    for cfg in grid:
        score_state = pair_mod.apply_pair_score_peak_decay_overlay(
            base_result,
            decay_ratio_threshold=cfg["decay_ratio_threshold"],
            recovery_ratio_threshold=cfg["recovery_ratio_threshold"],
            derisk_scale=cfg["derisk_scale"],
            commission=0.0,
        )
        combined = _apply_scale_path(
            base_result,
            total_scale=dd_state["risk_gate_scale"] * score_state["overlay_scale"],
            commission=commission,
            extra_columns={
                "risk_gate_scale": dd_state["risk_gate_scale"],
                "risk_gate_on": dd_state["risk_gate_on"],
                "risk_gate_base_dd": dd_state["risk_gate_base_dd"],
                "overlay_scale": score_state["overlay_scale"],
                "overlay_on": score_state["overlay_on"],
                "overlay_triggered": score_state["overlay_triggered"],
                "overlay_recovered": score_state["overlay_recovered"],
                "trade_id": score_state["trade_id"],
                "active_score_overlay": score_state["active_score_overlay"],
                "score_peak_overlay": score_state["score_peak_overlay"],
                "score_decay_ratio_overlay": score_state["score_decay_ratio_overlay"],
                "waiting_for_new_peak": score_state["waiting_for_new_peak"],
            },
        )
        variant_results[
            format_pair_score_variant_name(
                cfg["decay_ratio_threshold"],
                cfg["recovery_ratio_threshold"],
                cfg["derisk_scale"],
            )
        ] = combined

    rows = []
    for name, result in variant_results.items():
        row = _evaluate_result(mod, name, result)
        if name.startswith("score_decay"):
            parts = name.split("_")
            row["decay_ratio_threshold"] = int(parts[1][5:]) / 100.0
            row["recovery_ratio_threshold"] = int(parts[2][3:]) / 100.0
            row["derisk_scale"] = float(parts[3][1:].replace("p", "."))
        else:
            row["decay_ratio_threshold"] = None
            row["recovery_ratio_threshold"] = None
            row["derisk_scale"] = None
        rows.append(row)

    scan_df = pd.DataFrame(rows)
    baseline_row = scan_df.loc[scan_df["variant"] == "baseline_no_dd_gate"].iloc[0]
    dd_only_row = scan_df.loc[scan_df["variant"] == "dd_gate_only"].iloc[0]
    scan_df["annual_delta"] = scan_df["annual"] - float(baseline_row["annual"])
    scan_df["max_dd_delta"] = scan_df["max_dd"] - float(baseline_row["max_dd"])
    scan_df["vs_dd_only_annual_delta"] = scan_df["annual"] - float(dd_only_row["annual"])
    scan_df["vs_dd_only_max_dd_delta"] = scan_df["max_dd"] - float(dd_only_row["max_dd"])
    scan_df.to_csv(Path(args.output), index=False, encoding="utf-8-sig")

    top_df = scan_df[scan_df["variant"].str.startswith("score_decay")].copy()
    top_df = top_df.sort_values(
        ["calmar", "annual", "sharpe", "vs_dd_only_max_dd_delta"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    top_df.to_csv(Path(args.top_output), index=False, encoding="utf-8-sig")
    top_n = top_df.head(args.top_n).copy()

    selected_names = ["baseline_no_dd_gate", "dd_gate_only"] + top_n["variant"].tolist()
    window_rows = []
    for name in selected_names:
        window_rows.extend(_evaluate_windows(mod, name, variant_results[name], windows))
    window_df = pd.DataFrame(window_rows)
    window_df.to_csv(Path(args.window_output), index=False, encoding="utf-8-sig")
    _write_pair_scan_summary(scan_df, top_n, window_df, args, base_result)

    display_cols = [
        "variant",
        "decay_ratio_threshold",
        "recovery_ratio_threshold",
        "derisk_scale",
        "annual",
        "max_dd",
        "sharpe",
        "calmar",
        "vs_dd_only_annual_delta",
        "vs_dd_only_max_dd_delta",
    ]
    print(scan_df[scan_df["variant"].isin(selected_names)][display_cols].to_string(index=False))
    print(f"\nSaved: {args.output}")
    print(f"Saved top: {args.top_output}")
    print(f"Saved windows: {args.window_output}")
    print(f"Saved summary: {PAIR_SCAN_SUMMARY_MD}")


def main():
    parser = argparse.ArgumentParser(description="Compare ADK DD gate, pair-score decay, and their combined risk stack.")
    parser.add_argument("--csv", default=str(CN_CSV), help="Local CN data csv path.")
    parser.add_argument("--output", default=str(COMPARE_CSV), help="Full compare csv path.")
    parser.add_argument("--window-output", default=str(WINDOW_CSV), help="Window compare csv path.")
    parser.add_argument("--top-output", default=str(DD_SCAN_TOP_CSV), help="Top scan csv path.")
    parser.add_argument("--top-n", type=int, default=15, help="Top scan rows to save.")
    parser.add_argument("--scan-dd-gate", action="store_true", help="Scan DD gate parameters with fixed pair-score overlay.")
    parser.add_argument("--scan-pair-score", action="store_true", help="Scan pair-score overlay parameters with fixed DD gate.")
    parser.add_argument("--dd-enter", type=float, default=0.15, help="DD gate enter threshold.")
    parser.add_argument("--dd-exit", type=float, default=0.08, help="DD gate exit threshold.")
    parser.add_argument("--dd-scale-defense", type=float, default=0.5, help="DD gate defense scale.")
    parser.add_argument("--dd-cooldown-days", type=int, default=0, help="DD gate cooldown days.")
    parser.add_argument("--dd-enter-grid", nargs="*", type=float, default=[0.08, 0.10, 0.12, 0.15, 0.18, 0.20], help="DD gate enter threshold grid.")
    parser.add_argument("--dd-exit-grid", nargs="*", type=float, default=[0.04, 0.06, 0.08, 0.10, 0.12], help="DD gate exit threshold grid.")
    parser.add_argument("--dd-scale-grid", nargs="*", type=float, default=[0.3, 0.4, 0.5, 0.6, 0.7, 0.8], help="DD gate defense scale grid.")
    parser.add_argument("--decay-ratio-threshold", type=float, default=0.40, help="Pair-score decay trigger threshold.")
    parser.add_argument("--recovery-ratio-threshold", type=float, default=0.70, help="Pair-score recovery threshold.")
    parser.add_argument("--derisk-scale", type=float, default=0.0, help="Pair-score derisk scale after trigger.")
    parser.add_argument("--decay-ratio-grid", nargs="*", type=float, default=[0.30, 0.35, 0.40, 0.45, 0.50], help="Pair-score decay ratio threshold grid.")
    parser.add_argument("--recovery-ratio-grid", nargs="*", type=float, default=[0.50, 0.60, 0.70, 0.80, 0.90], help="Pair-score recovery ratio threshold grid.")
    parser.add_argument("--derisk-scale-grid", nargs="*", type=float, default=[0.0, 0.1, 0.2, 0.3, 0.5], help="Pair-score derisk scale grid.")
    args = parser.parse_args()

    mod = _load_module(BASE_SCRIPT, "adk_full_risk_stack_base_mod")
    pair_mod = _load_module(PAIR_SCORE_SCRIPT, "adk_full_risk_stack_pair_mod")
    cn_close, cn_dk_close = pair_mod._load_local_cn_data(mod, Path(args.csv))
    base_result = mod.run_dk_strategy(cn_close.copy(), cn_dk_close.copy())

    if args.scan_dd_gate:
        if args.output == str(COMPARE_CSV):
            args.output = str(DD_SCAN_CSV)
        if args.window_output == str(WINDOW_CSV):
            args.window_output = str(DD_SCAN_WINDOW_CSV)
        if args.top_output == str(DD_SCAN_TOP_CSV):
            args.top_output = str(DD_SCAN_TOP_CSV)
        run_dd_gate_scan(mod, pair_mod, base_result, args)
        return

    if args.scan_pair_score:
        if args.output == str(COMPARE_CSV):
            args.output = str(PAIR_SCAN_CSV)
        if args.window_output == str(WINDOW_CSV):
            args.window_output = str(PAIR_SCAN_WINDOW_CSV)
        if args.top_output == str(DD_SCAN_TOP_CSV):
            args.top_output = str(PAIR_SCAN_TOP_CSV)
        run_pair_score_scan(mod, pair_mod, base_result, args)
        return

    variants = build_full_risk_stack_variants(
        base_result,
        dd_enter=args.dd_enter,
        dd_scale_defense=args.dd_scale_defense,
        dd_exit=args.dd_exit,
        dd_cooldown_days=args.dd_cooldown_days,
        decay_ratio_threshold=args.decay_ratio_threshold,
        recovery_ratio_threshold=args.recovery_ratio_threshold,
        derisk_scale=args.derisk_scale,
        commission=float(getattr(mod, "CN_COMMISSION", 0.0)),
    )

    rows = [_evaluate_result(mod, name, result) for name, result in variants.items()]
    compare_df = pd.DataFrame(rows)
    baseline = compare_df.loc[compare_df["variant"] == "baseline_no_dd_gate"].iloc[0]
    compare_df["annual_delta"] = compare_df["annual"] - float(baseline["annual"])
    compare_df["max_dd_delta"] = compare_df["max_dd"] - float(baseline["max_dd"])
    compare_df["sharpe_delta"] = compare_df["sharpe"] - float(baseline["sharpe"])
    compare_df["calmar_delta"] = compare_df["calmar"] - float(baseline["calmar"])
    compare_df = compare_df.sort_values(
        ["variant"],
        key=lambda s: s.map(
            {
                "baseline_no_dd_gate": 0,
                "dd_gate_only": 1,
                "pair_score_decay_only": 2,
                "dd_gate_plus_pair_score_decay": 3,
            }
        ),
    ).reset_index(drop=True)
    compare_df.to_csv(Path(args.output), index=False, encoding="utf-8-sig")

    windows = [("1Y", 252), ("3Y", 252 * 3), ("5Y", 252 * 5)]
    window_rows = []
    for name, result in variants.items():
        window_rows.extend(_evaluate_windows(mod, name, result, windows))
    window_df = pd.DataFrame(window_rows)
    if not window_df.empty:
        window_df.to_csv(Path(args.window_output), index=False, encoding="utf-8-sig")
    else:
        Path(args.window_output).write_text("", encoding="utf-8")

    _write_summary(compare_df, window_df, args, base_result)

    display_cols = [
        "variant",
        "annual",
        "max_dd",
        "sharpe",
        "calmar",
        "annual_delta",
        "max_dd_delta",
        "risk_gate_days",
        "overlay_days",
        "combined_derisk_days",
    ]
    print(compare_df[display_cols].to_string(index=False))
    print(f"\nSaved: {args.output}")
    print(f"Saved windows: {args.window_output}")
    print(f"Saved summary: {SUMMARY_MD}")


if __name__ == "__main__":
    main()

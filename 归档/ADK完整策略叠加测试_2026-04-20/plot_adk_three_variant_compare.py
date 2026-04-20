import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from analyze_adk_full_risk_stack_compare import (  # noqa: E402
    BASE_SCRIPT,
    CN_CSV,
    PAIR_SCORE_SCRIPT,
    _load_module,
    build_full_risk_stack_variants,
)


PLOT_1Y = HERE / "adk_three_variant_compare_1Y.png"
PLOT_3Y = HERE / "adk_three_variant_compare_3Y.png"
METRICS_CSV = HERE / "adk_three_variant_compare_metrics.csv"
SUMMARY_MD = HERE / "ADK三状态对比图_2026-04-20.md"

VARIANT_ORDER = [
    ("baseline_no_dd_gate", "ADK no DD", "#4C78A8"),
    ("dd_gate_only", "ADK with DD", "#F58518"),
    ("pair_score_decay_only", "ADK overlay no DD", "#54A24B"),
]


def _load_base_result():
    mod = _load_module(BASE_SCRIPT, "adk_three_variant_base_mod")
    pair_mod = _load_module(PAIR_SCORE_SCRIPT, "adk_three_variant_pair_mod")
    cn_close, cn_dk_close = pair_mod._load_local_cn_data(mod, Path(CN_CSV))
    base_result = mod.run_dk_strategy(cn_close.copy(), cn_dk_close.copy())
    return mod, base_result


def _window_return_series(ret: pd.Series, years: int) -> pd.Series:
    end_date = ret.index.max()
    start_date = end_date - pd.DateOffset(years=years)
    return ret.loc[ret.index >= start_date].copy()


def _plot_window(nav_map: dict[str, pd.Series], title: str, out_path: Path):
    plt.figure(figsize=(12, 6))
    for _, label, color in VARIANT_ORDER:
        nav = nav_map[label]
        plt.plot(nav.index, nav.values, label=f"{label} ({(nav.iloc[-1] - 1) * 100:+.1f}%)", color=color, linewidth=2.0)
    plt.axhline(y=1.0, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)
    plt.title(title, fontsize=16, fontweight="bold")
    plt.ylabel("NAV (start=1.0)")
    plt.grid(True, alpha=0.25)
    plt.legend(loc="best", framealpha=0.9)
    plt.tight_layout()
    plt.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close()


def main():
    mod, base_result = _load_base_result()
    variants = build_full_risk_stack_variants(
        base_result,
        dd_enter=0.15,
        dd_scale_defense=0.5,
        dd_exit=0.08,
        dd_cooldown_days=0,
        decay_ratio_threshold=0.40,
        recovery_ratio_threshold=0.70,
        derisk_scale=0.0,
        commission=float(getattr(mod, "CN_COMMISSION", 0.0)),
    )

    rows = []
    summary_lines = [
        "# ADK 三状态对比图",
        "",
        f"- 基线脚本: `{Path(BASE_SCRIPT).name}`",
        f"- 本地数据: `{Path(CN_CSV).name}`",
        "- 参数口径:",
        "  - DD gate: enter=15%, exit=8%, scale=0.5, cooldown=0",
        "  - Overlay: decay=40%, recover=70%, derisk_scale=0.0",
        "",
    ]

    for window_label, years, out_path in [("1Y", 1, PLOT_1Y), ("3Y", 3, PLOT_3Y)]:
        nav_map = {}
        end_date = None
        start_date = None
        for variant_key, label, _color in VARIANT_ORDER:
            ret = variants[variant_key]["return"].dropna()
            win_ret = _window_return_series(ret, years)
            nav = (1.0 + win_ret).cumprod()
            nav = nav / nav.iloc[0]
            nav_map[label] = nav
            end_date = nav.index.max()
            start_date = nav.index.min()
            metrics = mod.calc_daily_metrics(win_ret, mod.CN_RF_DAILY, mod.CN_DK_TRADING_DAYS)
            rows.append(
                {
                    "window": window_label,
                    "variant": label,
                    "start_date": start_date.strftime("%Y-%m-%d"),
                    "end_date": end_date.strftime("%Y-%m-%d"),
                    "annual": metrics["annual"],
                    "max_dd": metrics["max_dd"],
                    "sharpe": metrics["sharpe"],
                    "calmar": metrics["calmar"],
                    "total_return": metrics["total_return"],
                }
            )

        _plot_window(
            nav_map,
            title=f"ADK Three-Variant NAV Compare ({window_label})",
            out_path=out_path,
        )
        summary_lines.append(f"## {window_label}")
        summary_lines.append("")
        summary_lines.append(f"- 区间: `{start_date.strftime('%Y-%m-%d')} -> {end_date.strftime('%Y-%m-%d')}`")
        for row in [r for r in rows if r["window"] == window_label]:
            summary_lines.append(
                f"- `{row['variant']}`: 年化 `{row['annual']:.4f}%` / 最大回撤 `{row['max_dd']:.4f}%` / "
                f"Sharpe `{row['sharpe']:.4f}` / Calmar `{row['calmar']:.4f}`"
            )
        summary_lines.append("")

    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(METRICS_CSV, index=False, encoding="utf-8-sig")
    SUMMARY_MD.write_text("\n".join(summary_lines), encoding="utf-8")
    print(metrics_df.to_string(index=False))
    print(f"\nSaved: {PLOT_1Y}")
    print(f"Saved: {PLOT_3Y}")
    print(f"Saved metrics: {METRICS_CSV}")
    print(f"Saved summary: {SUMMARY_MD}")


if __name__ == "__main__":
    main()

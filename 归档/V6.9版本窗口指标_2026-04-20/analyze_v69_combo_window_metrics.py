from pathlib import Path

import pandas as pd

from official_window_metrics_common import combo_window_metrics, load_module, run_strategy_outputs


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "mnt_bot V 6.9 plus.py"
CN_CSV = ROOT / "mnt_strategy_data_cn.csv"
US_CSV = ROOT / "mnt_strategy_data_us.csv"
OUT_CSV = Path(__file__).resolve().parent / "v69_combo_window_metrics.csv"
OUT_MD = Path(__file__).resolve().parent / "V6.9窗口指标_2026-04-20.md"
WINDOWS = [
    ("1Y", pd.Timestamp("2025-04-20")),
    ("3Y", pd.Timestamp("2023-04-20")),
    ("5Y", pd.Timestamp("2021-04-20")),
    ("10Y", pd.Timestamp("2016-04-20")),
    ("15Y", pd.Timestamp("2011-04-20")),
]


def main():
    mod = load_module(SCRIPT_PATH, "mnt_bot_v69_window_metrics")
    cn_result, cn_dk_result, us_rot_result, subc_daily = run_strategy_outputs(
        mod,
        "CombinedStrategyV69",
        CN_CSV,
        US_CSV,
    )
    data_end = min(cn_result.index.max(), cn_dk_result.index.max(), us_rot_result.index.max(), subc_daily.index.max())

    rows = []
    for label, requested_start in WINDOWS:
        metrics = combo_window_metrics(
            mod,
            cn_result,
            cn_dk_result,
            us_rot_result,
            subc_daily,
            requested_start,
            data_end,
        )
        actual_start = metrics["actual_start"]
        row = {
            "window": label,
            "requested_start": requested_start.strftime("%Y-%m-%d"),
            "actual_start": actual_start.strftime("%Y-%m-%d"),
            "end_date": metrics["actual_end"].strftime("%Y-%m-%d"),
            "annual": metrics["annual"],
            "max_dd": metrics["max_dd"],
            "total_return": metrics["total_return"],
            "enough_history": actual_start <= requested_start,
            "note": "",
        }
        if actual_start > requested_start and label == "15Y":
            row["note"] = "样本不足，实际只有可用全历史"
        elif actual_start > requested_start:
            row["note"] = "窗口起点被可用样本截断"
        rows.append(row)

    out = pd.DataFrame(rows)[
        ["window", "requested_start", "actual_start", "end_date", "annual", "max_dd", "total_return", "enough_history", "note"]
    ]
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    lines = [
        "# V6.9 组合窗口指标",
        "",
        f"- 基线脚本: `{SCRIPT_PATH.name}`",
        f"- 数据文件: `{CN_CSV.name}` / `{US_CSV.name}`",
        f"- 样本截止: `{data_end.strftime('%Y-%m-%d')}`",
        "- 口径: 使用正式 `_fetch_data` 同口径的本地预处理，再调用正式 `_run_strategies` 计算。",
        "",
        "| 窗口 | 请求起点 | 实际起点 | 截止 | 年化收益 | 最大回撤 | 总收益 | 备注 |",
        "|:-|:-|:-|:-|--:|--:|--:|:-|",
    ]
    for _, row in out.iterrows():
        lines.append(
            f"| {row['window']} | {row['requested_start']} | {row['actual_start']} | {row['end_date']} | "
            f"{row['annual']:.4f}% | {row['max_dd']:.4f}% | {row['total_return']:.4f}% | {row['note']} |"
        )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(out.to_string(index=False))
    print(f"\nSaved: {OUT_CSV}")
    print(f"Saved: {OUT_MD}")


if __name__ == "__main__":
    main()

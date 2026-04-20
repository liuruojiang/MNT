from pathlib import Path

import pandas as pd

from official_window_metrics_common import combo_window_metrics, load_module, run_strategy_outputs


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
SUMMARY_CSV = OUT_DIR / "v65_v68_v69_official_nav_windows.csv"
SUMMARY_MD = OUT_DIR / "v65_v68_v69_official_nav_windows.md"

VERSIONS = [
    ("V6.5", ROOT / "mnt_bot V 6.5 plus.py", "CombinedStrategyV65"),
    ("V6.7", ROOT / "mnt_bot V 6.7 plus.py", "CombinedStrategyV67"),
    ("V6.8", ROOT / "mnt_bot V 6.8 plus.py", "CombinedStrategyV68"),
    ("V6.9", ROOT / "mnt_bot V 6.9 plus.py", "CombinedStrategyV69"),
]
WINDOWS = [
    ("1Y", pd.Timestamp("2025-04-20"), pd.Timestamp("2026-04-20")),
    ("3Y", pd.Timestamp("2023-04-20"), pd.Timestamp("2026-04-20")),
    ("5Y", pd.Timestamp("2021-04-20"), pd.Timestamp("2026-04-20")),
    ("10Y", pd.Timestamp("2016-04-20"), pd.Timestamp("2026-04-20")),
    ("15Y", pd.Timestamp("2011-04-20"), pd.Timestamp("2026-04-20")),
]


def main():
    rows = []
    md_lines = [
        "# V6.5 / V6.8 / V6.9 组合窗口对照",
        "",
        "- 口径: 逐版本直接调用正式 `_fetch_data(..., include_us_live_snapshot=False)` 与正式 `_run_strategies`。",
        "- 口径: 使用正式 `_fetch_data` 同口径的本地预处理，再调用正式 `_run_strategies` 计算组合窗口指标。",
        "",
    ]

    for version_label, script_path, class_name in VERSIONS:
        mod = load_module(script_path, f"official_{version_label.lower().replace('.', '')}_windows")
        cn_result, dk_result, us_rot_result, subc_daily = run_strategy_outputs(mod, class_name)
        data_end = min(cn_result.index.max(), dk_result.index.max(), us_rot_result.index.max(), subc_daily.index.max())

        for window_label, start_date, end_date in WINDOWS:
            actual_end = min(end_date, data_end)
            metrics = combo_window_metrics(
                mod,
                cn_result,
                dk_result,
                us_rot_result,
                subc_daily,
                start_date,
                actual_end,
            )
            rows.append(
                {
                    "version": version_label,
                    "window": window_label,
                    "start_date": start_date.strftime("%Y-%m-%d"),
                    "actual_start": metrics["actual_start"].strftime("%Y-%m-%d"),
                    "end_date": metrics["actual_end"].strftime("%Y-%m-%d"),
                    "annual_pct": metrics["annual"],
                    "return_pct": metrics["total_return"],
                    "max_dd_pct": metrics["max_dd"],
                }
            )

    df = pd.DataFrame(rows)
    df.to_csv(SUMMARY_CSV, index=False, encoding="utf-8-sig")

    for version in ["V6.5", "V6.7", "V6.8", "V6.9"]:
        md_lines.append(f"## {version}")
        md_lines.append("")
        subset = df[df["version"] == version]
        md_lines.append("| 窗口 | 请求起点 | 实际起点 | 截止 | 年化 | 区间收益 | 最大回撤 |")
        md_lines.append("|:-|:-|:-|:-|--:|--:|--:|")
        for _, row in subset.iterrows():
            md_lines.append(
                f"| {row['window']} | {row['start_date']} | {row['actual_start']} | {row['end_date']} | "
                f"{row['annual_pct']:.4f}% | {row['return_pct']:.2f}% | {row['max_dd_pct']:.2f}% |"
            )
        md_lines.append("")

    SUMMARY_MD.write_text("\n".join(md_lines), encoding="utf-8")
    print(df.to_string(index=False))
    print(f"\nSaved: {SUMMARY_CSV}")
    print(f"Saved: {SUMMARY_MD}")


if __name__ == "__main__":
    main()

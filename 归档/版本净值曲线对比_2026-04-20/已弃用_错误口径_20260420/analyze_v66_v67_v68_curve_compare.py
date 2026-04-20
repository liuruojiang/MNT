import importlib.util
import sys
import types
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CN_CSV = ROOT / "mnt_strategy_data_cn.csv"
US_CSV = ROOT / "mnt_strategy_data_us.csv"
METRICS_CSV = HERE / "v66_v67_v68_combo_window_metrics.csv"
NAV_CSV = HERE / "v66_v67_v68_combo_nav_windows.csv"
SUMMARY_MD = HERE / "测试记录_2026-04-20.md"
PLOT_1Y = HERE / "v66_v67_v68_combo_nav_1Y.png"
PLOT_3Y = HERE / "v66_v67_v68_combo_nav_3Y.png"

VERSIONS = [
    {
        "label": "V6.6",
        "script": ROOT / "mnt_bot V 6.6 plus.py",
        "class_name": "CombinedStrategyV65",
        "module_name": "curve_compare_v66_mod",
    },
    {
        "label": "V6.7",
        "script": ROOT / "mnt_bot V 6.7 plus.py",
        "class_name": "CombinedStrategyV67",
        "module_name": "curve_compare_v67_mod",
    },
    {
        "label": "V6.8",
        "script": ROOT / "mnt_bot V 6.8 plus.py",
        "class_name": "CombinedStrategyV68",
        "module_name": "curve_compare_v68_mod",
    },
]


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
        raise RuntimeError("poe.start_message is unavailable in offline compare mode")

    @staticmethod
    def call(*args, **kwargs):
        raise RuntimeError("poe.call is unavailable in offline compare mode")


class _DummySettingsResponse(dict):
    def __init__(self, *args, **kwargs):
        super().__init__()


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    module.poe = _DummyPoe

    poe_stub = types.ModuleType("fastapi_poe")
    poe_stub.BotError = _DummyPoe.BotError
    poe_stub.default_chat = _DummyPoe.default_chat
    poe_stub.query = _DummyPoe.query
    poe_stub.update_settings = _DummyPoe.update_settings
    poe_stub.start_message = _DummyPoe.start_message
    poe_stub.call = _DummyPoe.call

    poe_types_stub = types.ModuleType("fastapi_poe.types")
    poe_types_stub.SettingsResponse = _DummySettingsResponse

    old_poe = sys.modules.get("fastapi_poe")
    old_poe_types = sys.modules.get("fastapi_poe.types")
    sys.modules["fastapi_poe"] = poe_stub
    sys.modules["fastapi_poe.types"] = poe_types_stub
    try:
        spec.loader.exec_module(module)
    finally:
        if old_poe is None:
            sys.modules.pop("fastapi_poe", None)
        else:
            sys.modules["fastapi_poe"] = old_poe
        if old_poe_types is None:
            sys.modules.pop("fastapi_poe.types", None)
        else:
            sys.modules["fastapi_poe.types"] = old_poe_types
    return module


def _load_local_cn_data(mod, csv_path: Path):
    df = pd.read_csv(csv_path)
    if "date" not in df.columns:
        raise ValueError(f"missing date column in {csv_path}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    cn_cols = [c for c in getattr(mod, "CN_ALL_CODES", []) if c in df.columns]
    if not cn_cols:
        raise ValueError("local CN csv is missing CN_ALL_CODES columns")
    cn_close = df[cn_cols].copy().ffill().dropna(how="all")

    dk_map = {
        mod.CN_DK_ZZ1000_SECID: mod.CN_DK_COLS[0],
        mod.CN_DK_SZ50_SECID: mod.CN_DK_COLS[1],
        mod.CN_DK_HS300_SECID: mod.CN_DK_COLS[2],
        mod.CN_DK_ZZ500_SECID: mod.CN_DK_COLS[3],
        mod.CN_DK_CYB_SECID: mod.CN_DK_COLS[4],
    }
    cn_dk_close = pd.concat(
        [df[[secid]].rename(columns={secid: col}) for secid, col in dk_map.items() if secid in df.columns],
        axis=1,
    ).ffill().dropna()

    common_idx = cn_close.index
    if len(cn_dk_close) > 0:
        common_idx = common_idx.intersection(cn_dk_close.index)
    cn_close = cn_close.reindex(common_idx).ffill()
    cn_dk_close = cn_dk_close.reindex(common_idx).ffill().dropna()
    return cn_close, cn_dk_close


def _load_local_us_data(csv_path: Path):
    df = pd.read_csv(csv_path)
    if "date" not in df.columns:
        raise ValueError(f"missing date column in {csv_path}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _combined_return_series(mod, cn_result, dk_result, us_rot_result, subc_daily_ret):
    cn_ret = cn_result["return"].dropna()
    dk_ret = dk_result["return"].dropna()
    us_ret = us_rot_result["return"].dropna()
    subc_ret = subc_daily_ret.dropna()
    nav_series = {}
    if len(cn_ret) > 1:
        nav = (1.0 + cn_ret).cumprod()
        nav_series["Sub-A"] = nav / nav.iloc[0]
    if len(dk_ret) > 1:
        nav = (1.0 + dk_ret).cumprod()
        nav_series["Sub-A-DK"] = nav / nav.iloc[0]
    if len(us_ret) > 1:
        nav = (1.0 + us_ret).cumprod()
        nav_series["Sub-B"] = nav / nav.iloc[0]
    if len(subc_ret) > 1:
        nav = (1.0 + subc_ret).cumprod()
        nav_series["Sub-C"] = nav / nav.iloc[0]
    all_dates = sorted(set().union(*(s.index for s in nav_series.values())))
    nav_df = pd.DataFrame({k: s.reindex(pd.DatetimeIndex(all_dates)).ffill() for k, s in nav_series.items()})
    weight_df = nav_df.notna().astype(float)
    for col in weight_df.columns:
        weight_df[col] *= mod.COMBINED_WEIGHTS.get(col, 0.0)
    weight_sum = weight_df.sum(axis=1).replace(0, pd.NA)
    weight_df = weight_df.div(weight_sum, axis=0)
    nav_df = nav_df.fillna(0.0)
    nav_comb = (nav_df * weight_df).sum(axis=1)
    nav_comb = nav_comb / nav_comb.iloc[0]
    return nav_comb.pct_change().dropna()


def _window_metrics(mod, ret: pd.Series):
    metrics = mod.calc_daily_metrics(ret, mod.CN_RF_DAILY, mod.CN_TRADING_DAYS)
    return {
        "annual": float(metrics["annual"]),
        "max_dd": float(metrics["max_dd"]),
        "sharpe": float(metrics["sharpe"]),
        "calmar": float(metrics["calmar"]),
    }


def _plot_window(nav_df: pd.DataFrame, window_label: str, output_path: Path):
    plt.figure(figsize=(11, 6))
    for col in nav_df.columns:
        plt.plot(nav_df.index, nav_df[col], linewidth=2.0, label=col)
    plt.title(f"V6.6 vs V6.7 vs V6.8 Combined NAV ({window_label})")
    plt.ylabel("Normalized NAV")
    plt.xlabel("Date")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=160)
    plt.close()


def main():
    series_map = {}
    sample_ranges = []

    for version in VERSIONS:
        mod = _load_module(version["script"], version["module_name"])
        cn_close, cn_dk_close = _load_local_cn_data(mod, CN_CSV)
        us_df = _load_local_us_data(US_CSV)
        bot_cls = getattr(mod, version["class_name"])
        bot = bot_cls()
        cn_result, dk_result, us_rot_result, _, prod_sig_a, prod_sig_b, _, _ = bot._run_strategies(
            cn_close.copy(), cn_dk_close.copy(), us_df.copy(), us_df.copy()
        )
        subc_daily_ret = mod._get_subc_daily_ret(us_df.copy(), prod_sig_a, prod_sig_b=prod_sig_b)
        combo_ret = _combined_return_series(mod, cn_result, dk_result, us_rot_result, subc_daily_ret)
        series_map[version["label"]] = combo_ret
        sample_ranges.append(
            {
                "label": version["label"],
                "start": combo_ret.index.min().strftime("%Y-%m-%d"),
                "end": combo_ret.index.max().strftime("%Y-%m-%d"),
                "days": int(len(combo_ret)),
            }
        )

    common_index = None
    for ret in series_map.values():
        common_index = ret.index if common_index is None else common_index.intersection(ret.index)
    if common_index is None or len(common_index) == 0:
        raise RuntimeError("no common combined-return dates across V6.6/V6.7/V6.8")

    aligned_ret = pd.DataFrame({k: v.reindex(common_index) for k, v in series_map.items()}).dropna(how="any")
    nav_rows = []
    metric_rows = []

    end_date = aligned_ret.index.max()
    window_specs = [
        ("1Y", end_date - pd.DateOffset(years=1), PLOT_1Y),
        ("3Y", end_date - pd.DateOffset(years=3), PLOT_3Y),
    ]

    for window_label, start_cut, plot_path in window_specs:
        window_ret = aligned_ret.loc[aligned_ret.index >= start_cut].copy()
        window_nav = (1.0 + window_ret).cumprod()
        window_nav = window_nav / window_nav.iloc[0]
        _plot_window(window_nav, window_label, plot_path)

        for label in window_nav.columns:
            for dt, value in window_nav[label].items():
                nav_rows.append(
                    {
                        "window": window_label,
                        "date": dt.strftime("%Y-%m-%d"),
                        "version": label,
                        "nav": float(value),
                    }
                )

        for label in window_ret.columns:
            mod = _load_module(
                next(v["script"] for v in VERSIONS if v["label"] == label),
                f"metrics_{label.lower().replace('.', '')}",
            )
            metrics = _window_metrics(mod, window_ret[label].dropna())
            metric_rows.append(
                {
                    "window": window_label,
                    "version": label,
                    **metrics,
                    "window_start": window_ret.index.min().strftime("%Y-%m-%d"),
                    "window_end": window_ret.index.max().strftime("%Y-%m-%d"),
                    "obs_days": int(len(window_ret)),
                }
            )

    metrics_df = pd.DataFrame(metric_rows)
    nav_df = pd.DataFrame(nav_rows)
    metrics_df.to_csv(METRICS_CSV, index=False, encoding="utf-8-sig")
    nav_df.to_csv(NAV_CSV, index=False, encoding="utf-8-sig")

    lines = [
        "# V6.6-V6.8 近期净值曲线对比",
        "",
        f"- 本地数据: `{CN_CSV.name}` / `{US_CSV.name}`",
        f"- 共同对比区间: `{aligned_ret.index.min().strftime('%Y-%m-%d')} -> {aligned_ret.index.max().strftime('%Y-%m-%d')}`",
        "",
        "## 各版本组合样本长度",
        "",
    ]
    for row in sample_ranges:
        lines.append(f"- `{row['label']}`: `{row['start']} -> {row['end']}` / `{row['days']}` 个交易日")
    lines.extend(["", "## 窗口指标", ""])
    for window_label in ["1Y", "3Y"]:
        subset = metrics_df.loc[metrics_df["window"] == window_label].copy()
        subset = subset.sort_values("version")
        lines.append(f"### {window_label}")
        lines.append("")
        for _, row in subset.iterrows():
            lines.append(
                f"- `{row['version']}`: 年化 `{row['annual']:.4f}%` / 最大回撤 `{row['max_dd']:.4f}%` / "
                f"Sharpe `{row['sharpe']:.4f}` / Calmar `{row['calmar']:.4f}`"
            )
        lines.append("")
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(metrics_df.to_string(index=False))
    print(f"\nSaved metrics: {METRICS_CSV}")
    print(f"Saved nav: {NAV_CSV}")
    print(f"Saved 1Y plot: {PLOT_1Y}")
    print(f"Saved 3Y plot: {PLOT_3Y}")
    print(f"Saved summary: {SUMMARY_MD}")


if __name__ == "__main__":
    main()

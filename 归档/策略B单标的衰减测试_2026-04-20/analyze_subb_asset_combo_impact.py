import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

from analyze_subb_asset_peak_decay_overlay import (
    BASE_SCRIPT,
    LOCAL_US_CSV,
    _baseline_subb_result,
    _load_local_us_rotation_data,
    apply_subb_asset_peak_decay_overlay,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUTPUT_CSV = HERE / "subb_asset_combo_impact.csv"
WINDOW_CSV = HERE / "subb_asset_combo_window_impact.csv"
SUMMARY_MD = HERE / "subb_asset_combo_impact.md"
VERIFY_CSV = HERE / "subb_asset_combo_impact_baseline_verify.csv"
CN_CSV = ROOT / "mnt_strategy_data_cn.csv"


def _load_v68_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)

    class DummyPoe:
        class BotError(Exception):
            pass

        default_chat = ""
        query = types.SimpleNamespace(text="", attachments=[])

        @staticmethod
        def update_settings(*args, **kwargs):
            return None

        @staticmethod
        def start_message():
            raise RuntimeError("offline")

        @staticmethod
        def call(*args, **kwargs):
            raise RuntimeError("offline")

    class DummySettingsResponse(dict):
        def __init__(self, *args, **kwargs):
            super().__init__()

    poe_stub = types.ModuleType("fastapi_poe")
    poe_stub.BotError = DummyPoe.BotError
    poe_stub.default_chat = DummyPoe.default_chat
    poe_stub.query = DummyPoe.query
    poe_stub.update_settings = DummyPoe.update_settings
    poe_stub.start_message = DummyPoe.start_message
    poe_stub.call = DummyPoe.call

    poe_types_stub = types.ModuleType("fastapi_poe.types")
    poe_types_stub.SettingsResponse = DummySettingsResponse

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

    common_idx = cn_close.index.intersection(cn_dk_close.index)
    cn_close = cn_close.reindex(common_idx).ffill()
    cn_dk_close = cn_dk_close.reindex(common_idx).ffill().dropna()
    return cn_close, cn_dk_close


def _chart_style_combined_metrics(mod, cn_result, dk_result, us_rot_result, subc_daily_ret, start_date, end_date):
    cn_period = cn_result["return"][(cn_result.index >= start_date) & (cn_result.index <= end_date)]
    dk_period = dk_result["return"][(dk_result.index >= start_date) & (dk_result.index <= end_date)]
    us_period = us_rot_result["return"][(us_rot_result.index >= start_date) & (us_rot_result.index <= end_date)]
    subc_period = subc_daily_ret[(subc_daily_ret.index >= start_date) & (subc_daily_ret.index <= end_date)]

    nav_series = {}
    if len(cn_period) > 1:
        nav = (1 + cn_period).cumprod()
        nav_series["Sub-A"] = nav / nav.iloc[0]
    if len(dk_period) > 1:
        nav = (1 + dk_period).cumprod()
        nav_series["Sub-A-DK"] = nav / nav.iloc[0]
    if len(us_period) > 1:
        nav = (1 + us_period).cumprod()
        nav_series["Sub-B"] = nav / nav.iloc[0]
    if len(subc_period) > 1:
        nav = (1 + subc_period).cumprod()
        nav_series["Sub-C"] = nav / nav.iloc[0]
    if len(nav_series) < 2:
        raise RuntimeError(f"insufficient sleeves in {start_date} -> {end_date}")

    weights = mod.COMBINED_WEIGHTS
    all_dates = sorted(set().union(*(series.index for series in nav_series.values())))
    nav_df = pd.DataFrame(
        {name: series.reindex(pd.DatetimeIndex(all_dates)).ffill() for name, series in nav_series.items()}
    )
    weight_df = nav_df.notna().astype(float)
    for col in weight_df.columns:
        weight_df[col] *= weights.get(col, 0)
    weight_sum = weight_df.sum(axis=1).replace(0, pd.NA)
    weight_df = weight_df.div(weight_sum, axis=0)
    nav_comb = (nav_df.fillna(0.0) * weight_df).sum(axis=1)
    nav_comb = nav_comb / nav_comb.iloc[0]

    total_return = (nav_comb.iloc[-1] - 1) * 100
    max_dd = ((nav_comb - nav_comb.cummax()) / nav_comb.cummax()).min() * 100
    n_days = (nav_comb.index[-1] - nav_comb.index[0]).days
    annual = ((nav_comb.iloc[-1]) ** (365.25 / n_days) - 1) * 100 if n_days > 0 else None
    comb_daily = nav_comb.pct_change().dropna()
    sharpe = (
        comb_daily.mean() / comb_daily.std() * np.sqrt(mod.CN_TRADING_DAYS)
        if len(comb_daily) > 1 and comb_daily.std() > 0
        else 0.0
    )
    calmar = annual / abs(max_dd) if annual is not None and max_dd != 0 else 0.0
    return {
        "annual": annual,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "calmar": calmar,
        "total_return": total_return,
    }


def main():
    mod = _load_v68_module(BASE_SCRIPT, "subb_combo_impact_mod")
    cn_close, cn_dk_close = _load_local_cn_data(mod, CN_CSV)
    us_df = pd.read_csv(LOCAL_US_CSV)
    us_df["date"] = pd.to_datetime(us_df["date"])
    us_df = us_df.set_index("date").sort_index()
    for col in us_df.columns:
        us_df[col] = pd.to_numeric(us_df[col], errors="coerce")

    bot = mod.CombinedStrategyV68()
    cn_result, dk_result, us_rot_result, _, prod_sig_a, prod_sig_b, _, _ = bot._run_strategies(
        cn_close.copy(), cn_dk_close.copy(), us_df.copy(), us_df.copy()
    )
    subc_daily_ret = mod._get_subc_daily_ret(us_df.copy(), prod_sig_a, prod_sig_b=prod_sig_b)

    us_rot_close = _load_local_us_rotation_data(mod, LOCAL_US_CSV)
    base_subb = _baseline_subb_result(mod, us_rot_close)
    alt_subb = apply_subb_asset_peak_decay_overlay(
        mod,
        base_subb,
        us_rot_close,
        decay_ratio_threshold=0.25,
        recovery_ratio_threshold=0.65,
        derisk_scale=0.5,
    )

    full_start = max(
        cn_result["return"].index.min(),
        dk_result["return"].index.min(),
        us_rot_result["return"].index.min(),
        subc_daily_ret.index.min(),
    )
    full_end = min(
        cn_result["return"].index.max(),
        dk_result["return"].index.max(),
        us_rot_result["return"].index.max(),
        subc_daily_ret.index.max(),
    )

    base_combo = _chart_style_combined_metrics(mod, cn_result, dk_result, us_rot_result, subc_daily_ret, full_start, full_end)
    alt_combo = _chart_style_combined_metrics(mod, cn_result, dk_result, alt_subb, subc_daily_ret, full_start, full_end)

    compare_df = pd.DataFrame(
        [
            {
                "variant": "baseline_combo_v68",
                "annual": base_combo["annual"],
                "max_dd": base_combo["max_dd"],
                "sharpe": base_combo["sharpe"],
                "calmar": base_combo["calmar"],
                "total_return": base_combo["total_return"],
                "annual_delta": 0.0,
                "max_dd_delta": 0.0,
            },
            {
                "variant": "combo_v68_plus_subb_asset_overlay_25_65_0p5",
                "annual": alt_combo["annual"],
                "max_dd": alt_combo["max_dd"],
                "sharpe": alt_combo["sharpe"],
                "calmar": alt_combo["calmar"],
                "total_return": alt_combo["total_return"],
                "annual_delta": alt_combo["annual"] - base_combo["annual"],
                "max_dd_delta": alt_combo["max_dd"] - base_combo["max_dd"],
            },
        ]
    )
    compare_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    window_rows = []
    verify_rows = []
    for label, start_date in [
        ("1Y", full_end - pd.DateOffset(years=1)),
        ("3Y", full_end - pd.DateOffset(years=3)),
        ("5Y", full_end - pd.DateOffset(years=5)),
    ]:
        base_m = _chart_style_combined_metrics(mod, cn_result, dk_result, us_rot_result, subc_daily_ret, start_date, full_end)
        alt_m = _chart_style_combined_metrics(mod, cn_result, dk_result, alt_subb, subc_daily_ret, start_date, full_end)
        window_rows.append(
            {
                "variant": "baseline_combo_v68",
                "window": label,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": full_end.strftime("%Y-%m-%d"),
                "annual": base_m["annual"],
                "max_dd": base_m["max_dd"],
                "sharpe": base_m["sharpe"],
                "calmar": base_m["calmar"],
                "total_return": base_m["total_return"],
                "annual_delta": 0.0,
                "max_dd_delta": 0.0,
            }
        )
        window_rows.append(
            {
                "variant": "combo_v68_plus_subb_asset_overlay_25_65_0p5",
                "window": label,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": full_end.strftime("%Y-%m-%d"),
                "annual": alt_m["annual"],
                "max_dd": alt_m["max_dd"],
                "sharpe": alt_m["sharpe"],
                "calmar": alt_m["calmar"],
                "total_return": alt_m["total_return"],
                "annual_delta": alt_m["annual"] - base_m["annual"],
                "max_dd_delta": alt_m["max_dd"] - base_m["max_dd"],
            }
        )
        if label in {"1Y", "3Y"}:
            verify_rows.append(
                {
                    "window": label,
                    "start_date": start_date.strftime("%Y-%m-%d"),
                    "end_date": full_end.strftime("%Y-%m-%d"),
                    "baseline_total_return_pct": base_m["total_return"],
                    "baseline_max_dd_pct": base_m["max_dd"],
                }
            )
    window_df = pd.DataFrame(window_rows)
    window_df.to_csv(WINDOW_CSV, index=False, encoding="utf-8-sig")
    verify_df = pd.DataFrame(verify_rows)
    verify_df.to_csv(VERIFY_CSV, index=False, encoding="utf-8-sig")

    sample_start = full_start.strftime("%Y-%m-%d")
    sample_end = full_end.strftime("%Y-%m-%d")
    lines = [
        "# Sub-B overlay combo impact",
        "",
        f"- Base script: `{BASE_SCRIPT.name}`",
        f"- Data files: `{CN_CSV.name}` / `{LOCAL_US_CSV.name}`",
        f"- Sample: `{sample_start} -> {sample_end}`",
        "- Replacement rule: only swap `Sub-B` into `asset overlay 25% / 65% / 0.5`; keep `Sub-A / ADK / Sub-C` on official `V6.8` logic.",
        "- Combo logic: rebuilt with the same daily NAV path as the official NAV chart.",
        "",
    ]
    for _, row in compare_df.iterrows():
        lines.append(
            f"- `{row['variant']}`: annual `{row['annual']:.4f}%` / max_dd `{row['max_dd']:.4f}%` / total_return `{row['total_return']:.4f}%` / sharpe `{row['sharpe']:.4f}` / calmar `{row['calmar']:.4f}` / annual_delta `{row['annual_delta']:+.4f}%` / max_dd_delta `{row['max_dd_delta']:+.4f}%`"
        )
    lines.extend(["", "## Windows", ""])
    for _, row in window_df.iterrows():
        lines.append(
            f"- `{row['variant']} {row['window']}`: `{row['start_date']} -> {row['end_date']}` / annual `{row['annual']:.4f}%` / max_dd `{row['max_dd']:.4f}%` / total_return `{row['total_return']:.4f}%` / annual_delta `{row['annual_delta']:+.4f}%` / max_dd_delta `{row['max_dd_delta']:+.4f}%`"
        )
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(compare_df.to_string(index=False))
    print()
    print(window_df.to_string(index=False))
    print()
    print(verify_df.to_string(index=False))
    print(f"\nSaved: {OUTPUT_CSV}")
    print(f"Saved: {WINDOW_CSV}")
    print(f"Saved: {VERIFY_CSV}")
    print(f"Saved: {SUMMARY_MD}")


if __name__ == "__main__":
    main()

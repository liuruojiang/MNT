from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
MICROCAP_ROOT = ROOT.parent / "微盘股对冲策略"
OUTPUT_DIR = ROOT / "docs" / "combo_with_microcap_weights_20260424"


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    module.poe = SimpleNamespace(
        update_settings=lambda *_args, **_kwargs: None,
        BotError=RuntimeError,
        default_chat=None,
        query=SimpleNamespace(text="", attachments=[]),
        call=lambda *_args, **_kwargs: "",
        start_message=lambda: None,
    )
    spec.loader.exec_module(module)
    return module


def monthly_compound(ret: pd.Series) -> pd.Series:
    ret = ret.dropna()
    return ret.groupby(ret.index.to_period("M")).apply(lambda x: (1.0 + x).prod() - 1.0)


def build_main_repo_daily(mnt_mod) -> dict[str, pd.Series]:
    cn_panel = pd.read_csv(ROOT / "mnt_strategy_data_cn.csv", parse_dates=["date"]).set_index("date").sort_index()
    us_panel = pd.read_csv(ROOT / "mnt_strategy_data_us.csv", parse_dates=["date"]).set_index("date").sort_index()

    cn_close = cn_panel[[c for c in mnt_mod.CN_ALL_CODES if c in cn_panel.columns]].copy().ffill()
    cn_dk_close = cn_panel[[c for c in [mnt_mod.CN_DK_ZZ1000_SECID, mnt_mod.CN_DK_SZ50_SECID, mnt_mod.CN_DK_HS300_SECID, mnt_mod.CN_DK_ZZ500_SECID, mnt_mod.CN_DK_CYB_SECID] if c in cn_panel.columns]].copy().ffill()
    cn_dk_close.columns = mnt_mod.CN_DK_COLS[: len(cn_dk_close.columns)]

    us_close = us_panel.copy().sort_index()
    if "EMXC_spliced" in us_close.columns:
        if "EMXC" in us_close.columns:
            us_close["EMXC"] = us_close["EMXC"].combine_first(us_close["EMXC_spliced"])
        else:
            us_close["EMXC"] = us_close["EMXC_spliced"]

    rot_needed = sorted(set(mnt_mod.US_ROT_POOL + ["SPY"] + list(mnt_mod.US_ROT_ASSETS.keys())))
    prod_needed = sorted(set([cfg["proxy"] for cfg in mnt_mod.PROD_PORTFOLIO.values()] + [mnt_mod.PROD_CASH] + list(mnt_mod.PROD_PORTFOLIO.keys())))

    us_rot_close = us_close[[c for c in rot_needed if c in us_close.columns]].copy().ffill()
    us_prod_daily = us_close[[c for c in prod_needed if c in us_close.columns]].copy().ffill()

    us_rot_close = us_rot_close.dropna(subset=[c for c in mnt_mod.US_ROT_POOL if c in us_rot_close.columns])
    req_prod = [cfg["proxy"] for cfg in mnt_mod.PROD_PORTFOLIO.values() if cfg["proxy"] in us_prod_daily.columns]
    if mnt_mod.PROD_CASH in us_prod_daily.columns:
        req_prod.append(mnt_mod.PROD_CASH)
    us_prod_daily = us_prod_daily.dropna(subset=sorted(set(req_prod)))

    engine = mnt_mod.CombinedStrategyV71()
    cn_result, cn_dk_result, us_rot_result, prod_monthly, prod_sig_a, prod_sig_b, _, _ = engine._run_strategies(
        cn_close, cn_dk_close, us_rot_close, us_prod_daily
    )
    subc_daily = mnt_mod._get_subc_daily_ret(us_prod_daily, prod_sig_a, prod_sig_b)

    return {
        "Sub-A": cn_result["return"].dropna(),
        "Sub-A-DK": cn_dk_result["return"].dropna(),
        "Sub-B": us_rot_result["return"].dropna(),
        "Sub-C": subc_daily.dropna(),
    }


def build_microcap_daily() -> pd.Series:
    if str(MICROCAP_ROOT) not in sys.path:
        sys.path.insert(0, str(MICROCAP_ROOT))
    import microcap_top100_mom16_biweekly_live as microcap_live

    close_df = microcap_live.load_close_df(
        MICROCAP_ROOT / "mnt_strategy_data_cn.csv",
        MICROCAP_ROOT / "outputs" / "wind_microcap_top_100_biweekly_thursday_16y_cached.csv",
    )
    gross = microcap_live.run_signal(close_df)
    turnover = pd.read_csv(
        MICROCAP_ROOT / "outputs" / "microcap_top100_mom16_biweekly_live_proxy_turnover.csv",
        parse_dates=["rebalance_date"],
    )
    net = microcap_live.freq_mod.cost_mod.apply_cost_model(gross, turnover)
    return net["return_net"].dropna()


def summarize_window(ret: pd.Series, mnt_mod) -> dict[str, float]:
    metrics = mnt_mod.calc_monthly_metrics(ret)
    return {
        "annual": float(metrics["annual"]),
        "vol": float(metrics["vol"]),
        "sharpe": float(metrics["sharpe"]),
        "max_dd": float(metrics["max_dd"]),
        "calmar": float(metrics["calmar"]),
        "win_rate": float(metrics["win_rate"]),
        "total_return": float(metrics["total_return"]),
    }


def summarize_daily_nav(nav: pd.Series) -> dict[str, float]:
    nav = nav.dropna()
    ret = nav.pct_change().dropna()
    total = (nav.iloc[-1] / nav.iloc[0] - 1.0) * 100.0
    ndays = (nav.index[-1] - nav.index[0]).days
    annual = ((nav.iloc[-1] / nav.iloc[0]) ** (365.25 / ndays) - 1.0) * 100.0 if ndays > 0 else np.nan
    dd = (nav / nav.cummax() - 1.0).min() * 100.0
    vol = ret.std(ddof=1) * np.sqrt(252.0) * 100.0 if len(ret) > 1 else np.nan
    sharpe = (ret.mean() / ret.std(ddof=1)) * np.sqrt(252.0) if len(ret) > 1 and ret.std(ddof=1) > 0 else np.nan
    calmar = annual / abs(dd) if dd != 0 and pd.notna(annual) else np.nan
    win_rate = (ret > 0).mean() * 100.0 if len(ret) else np.nan
    return {
        "annual": float(annual),
        "vol": float(vol),
        "sharpe": float(sharpe),
        "max_dd": float(dd),
        "calmar": float(calmar),
        "win_rate": float(win_rate),
        "total_return": float(total),
    }


def combine_daily_nav(daily_map: dict[str, pd.Series], weights: dict[str, float], start_date: pd.Timestamp) -> pd.Series:
    nav_parts: dict[str, pd.Series] = {}
    for name, ret in daily_map.items():
        part = ret.loc[ret.index >= start_date].dropna()
        if len(part) < 2:
            continue
        nav = (1.0 + part).cumprod()
        nav_parts[name] = nav / nav.iloc[0]
    all_dates = sorted(set().union(*[set(s.index) for s in nav_parts.values()]))
    nav_df = pd.DataFrame({name: s.reindex(pd.DatetimeIndex(all_dates)).ffill() for name, s in nav_parts.items()})
    wdf = nav_df.notna().astype(float)
    for col in wdf.columns:
        wdf[col] *= weights.get(col, 0.0)
    wsum = wdf.sum(axis=1).replace(0, np.nan)
    wdf = wdf.div(wsum, axis=0)
    nav_comb = (nav_df.fillna(0.0) * wdf).sum(axis=1)
    return nav_comb / nav_comb.iloc[0]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    mnt_mod = load_module("mnt_v71_research", ROOT / "mnt_bot V 7.1 plus.py")

    daily_map = build_main_repo_daily(mnt_mod)
    daily_map["Microcap"] = build_microcap_daily()

    common_start = max(series.index.min() for series in daily_map.values())
    daily_map = {name: series.loc[series.index >= common_start].dropna() for name, series in daily_map.items()}

    common_periods = None
    monthly_map = {name: monthly_compound(series) for name, series in daily_map.items()}
    for series in monthly_map.values():
        common_periods = series.index if common_periods is None else common_periods.intersection(series.index)
    if common_periods is None or len(common_periods) == 0:
        raise ValueError("No common monthly periods across sleeves.")

    aligned = pd.DataFrame({name: series.reindex(common_periods) for name, series in monthly_map.items()}).dropna()

    scenarios = {
        "current_15_25_40_20": {"Sub-A": 0.15, "Sub-A-DK": 0.25, "Sub-B": 0.40, "Sub-C": 0.20, "Microcap": 0.0},
        "proposal_10_15_15_40_20": {"Sub-A": 0.10, "Sub-A-DK": 0.15, "Sub-B": 0.40, "Sub-C": 0.20, "Microcap": 0.15},
        "neighbor_10_10_20_40_20": {"Sub-A": 0.10, "Sub-A-DK": 0.10, "Sub-B": 0.40, "Sub-C": 0.20, "Microcap": 0.20},
    }

    scenario_ret: dict[str, pd.Series] = {}
    scenario_nav_daily: dict[str, pd.Series] = {}
    for name, weights in scenarios.items():
        series = sum(aligned[col] * weights.get(col, 0.0) for col in aligned.columns)
        scenario_ret[name] = series
        scenario_nav_daily[name] = combine_daily_nav(daily_map, weights, pd.Timestamp(common_start))

    window_months = {
        "last_3y": 36,
        "last_5y": 60,
        "last_10y": 120,
        "full_common": None,
    }

    rows: list[dict[str, object]] = []
    for scenario_name, ret in scenario_ret.items():
        for window_name, months in window_months.items():
            if months is None:
                part = ret
                nav_part = scenario_nav_daily[scenario_name]
            else:
                part = ret.iloc[-months:]
                nav_part = scenario_nav_daily[scenario_name].loc[
                    scenario_nav_daily[scenario_name].index >= (scenario_nav_daily[scenario_name].index.max() - pd.DateOffset(years=int(months / 12)))
                ]
            metrics = summarize_window(part, mnt_mod)
            daily_metrics = summarize_daily_nav(nav_part)
            rows.append(
                {
                    "scenario": scenario_name,
                    "window": window_name,
                    "months": int(len(part)),
                    **metrics,
                    "daily_annual": daily_metrics["annual"],
                    "daily_vol": daily_metrics["vol"],
                    "daily_sharpe": daily_metrics["sharpe"],
                    "daily_max_dd": daily_metrics["max_dd"],
                    "daily_calmar": daily_metrics["calmar"],
                    "daily_win_rate": daily_metrics["win_rate"],
                    "daily_total_return": daily_metrics["total_return"],
                }
            )

    summary_df = pd.DataFrame(rows)
    summary_df.to_csv(OUTPUT_DIR / "combo_with_microcap_weights_summary.csv", index=False, encoding="utf-8")

    sleeve_metrics = []
    for name, ret in aligned.items():
        item = {"sleeve": name, **summarize_window(ret, mnt_mod)}
        item.update({f"daily_{k}": v for k, v in summarize_daily_nav((1.0 + daily_map[name]).cumprod()).items()})
        sleeve_metrics.append(item)
    pd.DataFrame(sleeve_metrics).to_csv(OUTPUT_DIR / "combo_with_microcap_weights_sleeves.csv", index=False, encoding="utf-8")

    meta = {
        "common_start": str(pd.Timestamp(common_start).date()),
        "common_end": str(aligned.index.max()),
        "common_months": int(len(aligned)),
        "weights": scenarios,
        "columns": list(aligned.columns),
    }
    (OUTPUT_DIR / "combo_with_microcap_weights_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()

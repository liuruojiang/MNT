"""Long-horizon proxy stress test for Strategy C bond allocation.

The proxy series are stitched to the live ETFs when each live ETF becomes
available. Results before all live ETFs exist are proxy research, not formal
production history.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import research_subc_bond_sleeve_backtest as base


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "outputs" / "subc_bond_necessity_long_proxy_20260811"
FETCH_START = "1990-01-01"
ADJUSTED_PRICE_SOURCES = {"Yahoo", "Yahoo+Nasdaq-gap"}

RAW_TICKERS = [
    "VTI",
    "QQQ",
    "DFSVX",
    "AVUV",
    "EFA",
    "VEA",
    "DISVX",
    "AVDV",
    "IEI",
    "VGIT",
    "BIL",
    "RYMFX",
    "AQMIX",
    "DBMF",
    "KMLM",
    "GLD",
    "BTC-USD",
    "SPY",
]

PROXY_MAP = {
    "VTI": ("VTI", None, "VTI actual"),
    "QQQ": ("QQQ", None, "QQQ proxy for QQQM"),
    "US_SMALL_VALUE": ("DFSVX", "AVUV", "DFSVX -> AVUV"),
    "DEVELOPED": ("EFA", "VEA", "EFA -> VEA"),
    "INTL_SMALL_VALUE": ("DISVX", "AVDV", "DISVX -> AVDV"),
    "TREASURY": ("IEI", "VGIT", "IEI -> VGIT"),
    "BIL": ("BIL", None, "BIL actual"),
    "MF_1": ("RYMFX", "DBMF", "RYMFX -> DBMF"),
    "MF_2": ("RYMFX", "KMLM", "RYMFX -> KMLM"),
    "GOLD": ("GLD", None, "GLD proxy for GLDM"),
    "BTC": ("BTC-USD", None, "BTC-USD proxy for IBIT"),
    "SPY": ("SPY", None, "SPY benchmark/calendar"),
}

COMMON_AFTER_BTC = {
    "VTI": 0.20,
    "QQQ": 0.10,
    "US_SMALL_VALUE": 0.10,
    "DEVELOPED": 0.10,
    "INTL_SMALL_VALUE": 0.10,
    "MF_1": 0.025,
    "MF_2": 0.025,
    "GOLD": 0.15,
    "BTC": 0.05,
}

NO_BOND_MULTIPLIER = 1.0 / sum(COMMON_AFTER_BTC.values())
VARIANTS_AFTER_BTC = {
    "VGIT 15%": {**COMMON_AFTER_BTC, "TREASURY": 0.15},
    "VGIT 7.5% + BIL 7.5%": {
        **COMMON_AFTER_BTC,
        "TREASURY": 0.075,
        "BIL": 0.075,
    },
    "BIL 15%": {**COMMON_AFTER_BTC, "BIL": 0.15},
    "No bond, pro-rata risk assets": {
        ticker: weight * NO_BOND_MULTIPLIER
        for ticker, weight in COMMON_AFTER_BTC.items()
    },
}


def fetch_raw(loader) -> tuple[dict[str, pd.Series], pd.DataFrame, str | None]:
    raw = {}
    rows = []
    for ticker in RAW_TICKERS:
        frame, source = loader.fetch_yahoo(ticker, start_date=FETCH_START)
        if frame is None or frame.empty or source not in ADJUSTED_PRICE_SOURCES:
            raise RuntimeError(f"Adjusted Yahoo data required for {ticker}: {source}")
        close = pd.to_numeric(frame["close"], errors="coerce").dropna()
        index = pd.DatetimeIndex(pd.to_datetime(close.index))
        if index.tz is not None:
            index = index.tz_convert(None)
        close.index = index.normalize()
        close = close[~close.index.duplicated(keep="last")].sort_index()
        raw[ticker] = close.rename(ticker)
        rows.append(
            {
                "ticker": ticker,
                "source": source,
                "adjustment": "Yahoo adjusted close with scale-aligned same-ticker gap repair",
                "start": close.index.min().date().isoformat(),
                "end": close.index.max().date().isoformat(),
                "rows": len(close),
            }
        )

    excluded = None
    now_ny = pd.Timestamp.now(tz="America/New_York")
    if now_ny.time() < pd.Timestamp("16:15").time():
        excluded = now_ny.date().isoformat()
        for ticker in raw:
            raw[ticker] = raw[ticker][raw[ticker].index.date < now_ny.date()]
    return raw, pd.DataFrame(rows), excluded


def stitched_nav(
    calendar: pd.DatetimeIndex,
    raw: dict[str, pd.Series],
    proxy: str,
    live: str | None,
) -> tuple[pd.Series, pd.Timestamp | None]:
    proxy_price = raw[proxy].reindex(calendar)
    proxy_ret = proxy_price.pct_change(fill_method=None)
    switch_date = None
    combined_ret = proxy_ret.copy()
    if live is not None:
        live_price = raw[live].reindex(calendar)
        live_ret = live_price.pct_change(fill_method=None)
        switch_date = live_ret.first_valid_index()
        if switch_date is None:
            raise RuntimeError(f"No usable live returns for {live}")
        combined_ret.loc[switch_date:] = live_ret.loc[switch_date:]
    first = combined_ret.first_valid_index()
    if first is None:
        raise RuntimeError(f"No usable returns for {proxy}/{live}")
    nav = (1.0 + combined_ret.loc[first:]).cumprod()
    return nav, switch_date


def pre_btc_weights(after: dict[str, float], method: str) -> dict[str, float]:
    btc_weight = after.get("BTC", 0.0)
    before = {ticker: weight for ticker, weight in after.items() if ticker != "BTC"}
    if btc_weight <= 0:
        return before
    if method == "renormalize":
        return {ticker: weight / (1.0 - btc_weight) for ticker, weight in before.items()}
    if method == "cash_placeholder":
        before["BIL"] = before.get("BIL", 0.0) + btc_weight
        return before
    raise ValueError(method)


def phased_annual_returns(
    prices: pd.DataFrame,
    after_weights: dict[str, float],
    before_weights: dict[str, float],
    btc_start: pd.Timestamp,
    cost_rate: float = base.ASSET_REBAL_COST,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    asset_ret = prices.pct_change(fill_method=None)
    start_candidates = [
        asset_ret[ticker].first_valid_index() for ticker in before_weights if ticker in asset_ret
    ]
    start = max(date for date in start_candidates if date is not None)
    asset_ret = asset_ret.loc[start:]
    holdings = pd.Series(before_weights, dtype=float)
    prev_value = float(holdings.sum())
    prev_year = asset_ret.index[0].year
    in_btc_phase = False
    returns = []
    turnovers = []
    costs = []

    for date, row in asset_ret.iterrows():
        target = after_weights if date >= btc_start else before_weights
        phase_changed = date >= btc_start and not in_btc_phase
        annual_rebalance = date.year != prev_year
        turnover = 0.0
        cost = 0.0
        if phase_changed or annual_rebalance:
            actual = holdings / holdings.sum()
            union = actual.index.union(pd.Index(target))
            actual = actual.reindex(union, fill_value=0.0)
            target_series = pd.Series(target, dtype=float).reindex(union, fill_value=0.0)
            turnover = float((target_series - actual).abs().sum())
            cost = float(holdings.sum() * turnover * cost_rate)
            post_cost = float(holdings.sum() - cost)
            holdings = pd.Series(target, dtype=float) * post_cost
        if phase_changed:
            in_btc_phase = True
        if annual_rebalance:
            prev_year = date.year

        holdings = holdings * (
            1.0 + row.reindex(holdings.index).fillna(0.0)
        )
        value = float(holdings.sum())
        returns.append(value / prev_value - 1.0)
        turnovers.append(turnover)
        costs.append(cost / prev_value if prev_value > 0 else 0.0)
        prev_value = value

    index = asset_ret.index
    return (
        pd.Series(returns, index=index),
        pd.Series(turnovers, index=index),
        pd.Series(costs, index=index),
    )


def plot_results(main_returns: pd.DataFrame, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    nav = main_returns.apply(base.nav_from_returns)
    nav = nav.div(nav.iloc[0])
    dd = nav.div(nav.cummax()).sub(1.0)
    fig, axes = plt.subplots(2, 1, figsize=(13.5, 8.8), sharex=True)
    fig.subplots_adjust(left=0.08, right=0.985, top=0.90, bottom=0.09, hspace=0.10)
    for name in nav.columns:
        axes[0].plot(nav.index, nav[name], linewidth=2.0, label=name)
        axes[1].plot(dd.index, dd[name] * 100, linewidth=1.45, label=name)
    axes[0].set_title("2007年以来长周期代理：比特币上市前剔除并归一化", fontsize=14, fontweight="bold")
    axes[0].set_ylabel("归一化净值")
    axes[0].grid(True, alpha=0.24)
    axes[0].legend(frameon=False, ncol=2)
    axes[1].axhline(0, color="#6B7280", linewidth=0.8)
    axes[1].set_ylabel("回撤（%）")
    axes[1].set_xlabel("日期")
    axes[1].grid(True, alpha=0.24)
    axes[1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle("策略 C 债券必要性：长周期代理压力测试", fontsize=17, fontweight="bold", y=0.975)
    fig.text(
        0.01,
        0.018,
        "代理研究，非正式实盘历史；Yahoo复权收盘；年度再平衡10bps；V7.7目标波动率15日/15%、0.5-1.5x、融资与调仓成本同生产参数。",
        fontsize=8.3,
        color="#4B5563",
    )
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    v77 = base.load_module(base.V77_PATH, "v77_long_proxy")
    v79 = base.load_module(base.V79_PATH, "v79_long_proxy_loader")
    raw, source_table, excluded_date = fetch_raw(v79)
    calendar = raw["SPY"].index

    stitched = {}
    mapping_rows = []
    for synthetic, (proxy, live, description) in PROXY_MAP.items():
        nav, switch = stitched_nav(calendar, raw, proxy, live)
        stitched[synthetic] = nav.rename(synthetic)
        mapping_rows.append(
            {
                "synthetic": synthetic,
                "proxy": proxy,
                "live": live,
                "description": description,
                "proxy_start": raw[proxy].index.min().date().isoformat(),
                "live_return_switch": switch.date().isoformat() if switch is not None else None,
                "classification": "proxy research before live switch" if live else "actual/designated proxy",
            }
        )
    prices = pd.concat(stitched.values(), axis=1).sort_index()
    non_btc = [column for column in prices.columns if column != "BTC"]
    prices = prices.loc[prices[non_btc].dropna(how="any").index.min():]
    btc_start = prices["BTC"].first_valid_index()
    if btc_start is None:
        raise RuntimeError("BTC proxy has no usable start")

    method_returns = {}
    method_raw = {}
    method_scale = {}
    method_costs = {}
    method_turnover = {}
    for method in ("renormalize", "cash_placeholder"):
        scaled = {}
        raw_returns = {}
        scales = {}
        costs = {}
        turnovers = {}
        for name, after in VARIANTS_AFTER_BTC.items():
            before = pre_btc_weights(after, method)
            raw_ret, turnover, asset_cost = phased_annual_returns(
                prices, after, before, btc_start
            )
            scaled_ret, scale, scale_cost = v77._apply_subc_vol_scaling(raw_ret, prices)
            scaled[name] = scaled_ret
            raw_returns[name] = raw_ret
            scales[name] = scale
            costs[name] = asset_cost.add(scale_cost, fill_value=0.0)
            turnovers[name] = turnover
        common = pd.DataFrame(scaled).dropna(how="any")
        method_returns[method] = common
        method_raw[method] = pd.DataFrame(raw_returns).reindex(common.index)
        method_scale[method] = pd.DataFrame(scales).reindex(common.index)
        method_costs[method] = pd.DataFrame(costs).reindex(common.index)
        method_turnover[method] = pd.DataFrame(turnovers).reindex(common.index)

    # Alternate managed-futures proxy robustness check. AQMIX starts in 2010,
    # so it cannot replace the RYMFX line for the GFC-era main test.
    aqmix_map = dict(PROXY_MAP)
    aqmix_map["MF_1"] = ("AQMIX", "DBMF", "AQMIX -> DBMF")
    aqmix_map["MF_2"] = ("AQMIX", "KMLM", "AQMIX -> KMLM")
    aqmix_stitched = {}
    for synthetic, (proxy, live, _) in aqmix_map.items():
        aqmix_stitched[synthetic] = stitched_nav(calendar, raw, proxy, live)[0].rename(synthetic)
    aqmix_prices = pd.concat(aqmix_stitched.values(), axis=1).sort_index()
    aqmix_non_btc = [column for column in aqmix_prices.columns if column != "BTC"]
    aqmix_prices = aqmix_prices.loc[
        aqmix_prices[aqmix_non_btc].dropna(how="any").index.min():
    ]
    aqmix_btc_start = aqmix_prices["BTC"].first_valid_index()
    aqmix_scaled = {}
    for name, after in VARIANTS_AFTER_BTC.items():
        before = pre_btc_weights(after, "renormalize")
        raw_ret, _, _ = phased_annual_returns(
            aqmix_prices, after, before, aqmix_btc_start
        )
        aqmix_scaled[name] = v77._apply_subc_vol_scaling(raw_ret, aqmix_prices)[0]
    aqmix_returns = pd.DataFrame(aqmix_scaled).dropna(how="any")
    metrics_aqmix = base.window_metrics(aqmix_returns)

    main_returns = method_returns["renormalize"]
    metrics_main = base.window_metrics(main_returns)
    metrics_sensitivity = base.window_metrics(method_returns["cash_placeholder"])
    deltas = pd.concat(
        [
            base.delta_metrics(metrics_main, "VGIT 15%", candidate)
            for candidate in list(VARIANTS_AFTER_BTC)[1:]
        ],
        ignore_index=True,
    )

    stress_windows = {
        "GFC": ("2007-10-09", "2009-03-09"),
        "COVID": ("2020-02-19", "2020-03-23"),
        "2022": ("2022-01-01", "2022-12-31"),
    }
    stress_rows = []
    for method, frame in method_returns.items():
        for label, (start, end) in stress_windows.items():
            for name in frame.columns:
                selected = frame[name].loc[start:end]
                stress_rows.append(
                    {
                        "btc_prehistory_method": method,
                        "period": label,
                        "series": name,
                        "start": selected.index.min().date().isoformat(),
                        "end": selected.index.max().date().isoformat(),
                        "return": (1.0 + selected).prod() - 1.0,
                        "max_drawdown": base.nav_from_returns(selected).pipe(
                            lambda nav: (nav / nav.cummax() - 1.0).min()
                        ),
                    }
                )
    stress = pd.DataFrame(stress_rows)

    overlay_rows = []
    for method, frame in method_scale.items():
        for name in frame.columns:
            scale = frame[name]
            overlay_rows.append(
                {
                    "btc_prehistory_method": method,
                    "series": name,
                    "average_scale": scale.mean(),
                    "median_scale": scale.median(),
                    "pct_days_at_min_0_5": (scale <= 0.5000001).mean(),
                    "pct_days_at_max_1_5": (scale >= 1.4999999).mean(),
                    "scale_adjustment_days": int((scale.diff().abs() > 1e-12).sum()),
                    "total_cost_fraction_sum": method_costs[method][name].sum(),
                    "annual_and_phase_turnover_sum": method_turnover[method][name].sum(),
                }
            )
    overlay = pd.DataFrame(overlay_rows)

    overlap_start = pd.Timestamp("2020-12-03")
    formal_path = ROOT / "outputs" / "subc_bond_necessity_20260811" / "metrics.csv"
    formal = pd.read_csv(formal_path)
    overlap_metrics = base.window_metrics(main_returns.loc[main_returns.index >= overlap_start])
    parity_rows = []
    for name in VARIANTS_AFTER_BTC:
        proxy_name = overlap_metrics[overlap_metrics["series"] == name].set_index("window")
        formal_name = formal[formal["series"] == name].set_index("window")
        for window in ("5Y", "3Y", "1Y"):
            parity_rows.append(
                {
                    "series": name,
                    "window": window,
                    "cagr_difference": proxy_name.loc[window, "cagr"] - formal_name.loc[window, "cagr"],
                    "max_drawdown_difference": proxy_name.loc[window, "max_drawdown"] - formal_name.loc[window, "max_drawdown"],
                }
            )
    overlap_parity = pd.DataFrame(parity_rows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_results(main_returns, OUT_DIR / "subc_bond_necessity_long_proxy.png")
    daily = pd.concat(
        {
            "renorm_scaled_return": method_returns["renormalize"],
            "renorm_scaled_nav": method_returns["renormalize"].apply(base.nav_from_returns),
            "cash_placeholder_scaled_return": method_returns["cash_placeholder"],
            "cash_placeholder_scaled_nav": method_returns["cash_placeholder"].apply(base.nav_from_returns),
            "renorm_scale": method_scale["renormalize"],
        },
        axis=1,
    )
    daily.to_csv(OUT_DIR / "daily_nav_and_returns.csv", encoding="utf-8-sig")
    metrics_main.to_csv(OUT_DIR / "metrics_renormalize.csv", index=False, encoding="utf-8-sig")
    metrics_sensitivity.to_csv(OUT_DIR / "metrics_cash_placeholder.csv", index=False, encoding="utf-8-sig")
    metrics_aqmix.to_csv(OUT_DIR / "metrics_aqmix_sensitivity.csv", index=False, encoding="utf-8-sig")
    deltas.to_csv(OUT_DIR / "candidate_deltas.csv", index=False, encoding="utf-8-sig")
    stress.to_csv(OUT_DIR / "stress_periods.csv", index=False, encoding="utf-8-sig")
    overlay.to_csv(OUT_DIR / "vol_scale_audit.csv", index=False, encoding="utf-8-sig")
    overlap_parity.to_csv(OUT_DIR / "formal_overlap_check.csv", index=False, encoding="utf-8-sig")
    source_table.to_csv(OUT_DIR / "sources.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(mapping_rows).to_csv(OUT_DIR / "proxy_map.csv", index=False, encoding="utf-8-sig")

    audit = {
        "status": "diagnostic_long_horizon_proxy_research",
        "created_at_shanghai": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "sample_start": main_returns.index.min().date().isoformat(),
        "sample_end": main_returns.index.max().date().isoformat(),
        "btc_proxy_start": btc_start.date().isoformat(),
        "excluded_unconfirmed_date": excluded_date,
        "data_source": "Yahoo adjusted close via mnt_bot V 7.9 plus.py",
        "calendar": "SPY US sessions; BTC weekend return accumulated to next US session",
        "main_pre_btc_method": "remove BTC 5% and renormalize remaining weights, matching legacy Sub-C phase convention",
        "sensitivity_pre_btc_method": "hold missing BTC 5% in BIL",
        "managed_futures_proxy_sensitivity": {
            "main": "RYMFX from 2007, stitched to DBMF/KMLM",
            "alternate": "AQMIX from 2010, stitched to DBMF/KMLM",
            "alternate_start": aqmix_returns.index.min().date().isoformat(),
        },
        "asset_rebalance_cost_rate": base.ASSET_REBAL_COST,
        "target_vol_source": "mnt_bot V 7.7 plus.py::_apply_subc_vol_scaling",
        "production_code_changed": False,
        "live_orders": False,
        "classification": "proxy results are not formal production history",
    }
    (OUT_DIR / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    full = metrics_main[metrics_main["window"] == "Full"].set_index("series")
    stress_main = stress[stress["btc_prehistory_method"] == "renormalize"]
    record = [
        "# Strategy C Bond Necessity — Long Proxy Test",
        "",
        "## Classification",
        "",
        "Diagnostic proxy research only. Pre-live portions must not be reported as formal ETF history.",
        "",
        f"- Window: {main_returns.index.min().date()} to {main_returns.index.max().date()}.",
        "- Main pre-BTC convention: remove BTC and renormalize remaining weights.",
        "- Sensitivity: hold missing BTC allocation in BIL.",
        "- Annual rebalance 10 bps; official V7.7 target-vol, financing, and scale costs.",
        "",
        "## Full proxy sample",
        "",
        "| Variant | CAGR | Max drawdown | Annual vol | Sharpe |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in VARIANTS_AFTER_BTC:
        row = full.loc[name]
        record.append(
            f"| {name} | {row['cagr']:.2%} | {row['max_drawdown']:.2%} | "
            f"{row['annual_vol']:.2%} | {row['sharpe_0rf']:.2f} |"
        )
    record.extend(["", "## Stress periods", "", "| Period | Variant | Return | Max drawdown |", "|---|---|---:|---:|"])
    for _, row in stress_main.iterrows():
        record.append(
            f"| {row['period']} | {row['series']} | {row['return']:.2%} | {row['max_drawdown']:.2%} |"
        )
    (OUT_DIR / "record.md").write_text("\n".join(record) + "\n", encoding="utf-8")

    print("PROXY_MAP")
    print(pd.DataFrame(mapping_rows).to_string(index=False))
    print("\nMETRICS_RENORMALIZE")
    print(metrics_main.to_string(index=False))
    print("\nMETRICS_CASH_PLACEHOLDER")
    print(metrics_sensitivity.to_string(index=False))
    print("\nMETRICS_AQMIX_SENSITIVITY")
    print(metrics_aqmix.to_string(index=False))
    print("\nDELTAS")
    print(deltas.to_string(index=False))
    print("\nSTRESS")
    print(stress.to_string(index=False))
    print("\nOVERLAP_PARITY")
    print(overlap_parity.to_string(index=False))
    print("\nOUTPUT", OUT_DIR)


if __name__ == "__main__":
    main()

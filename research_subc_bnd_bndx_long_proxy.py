"""Long-horizon proxy test for Strategy C's BND/BNDX bond sleeve.

PFORX is used only before BNDX has live returns.  All pre-live results are
diagnostic proxy research and must not be described as formal ETF history.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import research_subc_bond_necessity_long_proxy as long_base
import research_subc_bond_sleeve_backtest as base


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "outputs" / "subc_bnd_bndx_long_proxy_20260811"
FETCH_START = "1990-01-01"

PROXY_MAP = {
    **long_base.PROXY_MAP,
    "AGG_BOND": ("BND", None, "BND actual"),
    "INTL_BOND": ("PFORX", "BNDX", "PFORX -> BNDX"),
}

RAW_TICKERS = sorted(
    {
        ticker
        for proxy, live, _ in PROXY_MAP.values()
        for ticker in (proxy, live)
        if ticker is not None
    }
    | {"AQMIX", "PGBIX"}
)

COMMON_AFTER_BTC = dict(long_base.COMMON_AFTER_BTC)
VARIANTS_AFTER_BTC = {
    "VGIT 15%": {**COMMON_AFTER_BTC, "TREASURY": 0.15},
    "VGIT 7.5% + BND 3.75% + BNDX 3.75%": {
        **COMMON_AFTER_BTC,
        "TREASURY": 0.075,
        "AGG_BOND": 0.0375,
        "INTL_BOND": 0.0375,
    },
    "BND 7.5% + BNDX 7.5%": {
        **COMMON_AFTER_BTC,
        "AGG_BOND": 0.075,
        "INTL_BOND": 0.075,
    },
}

BOND_VARIANTS = {
    "VGIT proxy 100%": {"TREASURY": 1.0},
    "VGIT/BND/BNDX proxy 50/25/25": {
        "TREASURY": 0.50,
        "AGG_BOND": 0.25,
        "INTL_BOND": 0.25,
    },
    "BND/BNDX proxy 50:50": {"AGG_BOND": 0.50, "INTL_BOND": 0.50},
}


def build_stitched_prices(
    raw: dict[str, pd.Series],
    calendar: pd.DatetimeIndex,
    mf_proxy: str = "RYMFX",
    intl_bond_proxy: str = "PFORX",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mapping = dict(PROXY_MAP)
    mapping["MF_1"] = (mf_proxy, "DBMF", f"{mf_proxy} -> DBMF")
    mapping["MF_2"] = (mf_proxy, "KMLM", f"{mf_proxy} -> KMLM")
    mapping["INTL_BOND"] = (
        intl_bond_proxy,
        "BNDX",
        f"{intl_bond_proxy} -> BNDX",
    )
    stitched: dict[str, pd.Series] = {}
    rows = []
    for synthetic, (proxy, live, description) in mapping.items():
        nav, switch = long_base.stitched_nav(calendar, raw, proxy, live)
        stitched[synthetic] = nav.rename(synthetic)
        rows.append(
            {
                "synthetic": synthetic,
                "proxy": proxy,
                "live": live,
                "description": description,
                "proxy_start": raw[proxy].index.min().date().isoformat(),
                "live_return_switch": (
                    switch.date().isoformat() if switch is not None else None
                ),
                "classification": (
                    "proxy research before live switch"
                    if live is not None
                    else "actual/designated proxy"
                ),
            }
        )
    prices = pd.concat(stitched.values(), axis=1).sort_index()
    return prices, pd.DataFrame(rows)


def run_full_variants(
    v77,
    prices: pd.DataFrame,
    pre_btc_method: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    required = sorted(
        {ticker for weights in VARIANTS_AFTER_BTC.values() for ticker in weights}
        | {"BIL"}
    )
    non_btc = [ticker for ticker in required if ticker != "BTC"]
    common_start = prices[non_btc].dropna(how="any").index.min()
    prices = prices.loc[common_start:]
    btc_start = prices["BTC"].first_valid_index()
    if btc_start is None:
        raise RuntimeError("BTC proxy has no usable start")

    scaled_returns = {}
    raw_returns = {}
    scales = {}
    combined_costs = {}
    for name, after in VARIANTS_AFTER_BTC.items():
        before = long_base.pre_btc_weights(after, pre_btc_method)
        raw_ret, _, asset_cost = long_base.phased_annual_returns(
            prices, after, before, btc_start
        )
        scaled_ret, scale, scale_cost = v77._apply_subc_vol_scaling(raw_ret, prices)
        raw_returns[name] = raw_ret
        scaled_returns[name] = scaled_ret
        scales[name] = scale
        combined_costs[name] = asset_cost.add(scale_cost, fill_value=0.0)
    common = pd.DataFrame(scaled_returns).dropna(how="any")
    return (
        common,
        pd.DataFrame(raw_returns).reindex(common.index),
        pd.DataFrame(scales).reindex(common.index),
        pd.DataFrame(combined_costs).reindex(common.index),
    )


def run_bond_variants(prices: pd.DataFrame) -> pd.DataFrame:
    columns = ["TREASURY", "AGG_BOND", "INTL_BOND"]
    common = prices[columns].dropna(how="any")
    returns = {}
    for name, weights in BOND_VARIANTS.items():
        returns[name] = base.annual_rebalanced_returns(common, weights)[0]
    return pd.DataFrame(returns).dropna(how="any")


def proxy_quality(raw: dict[str, pd.Series], calendar: pd.DatetimeIndex) -> pd.DataFrame:
    tickers = ("PFORX", "PGBIX", "BNDX")
    prices = pd.concat({ticker: raw[ticker].reindex(calendar) for ticker in tickers}, axis=1)
    returns = prices.pct_change(fill_method=None).dropna(how="any")
    rows = []
    for ticker in returns:
        metric = base.metric_row(returns[ticker], ticker, "Live overlap")
        metric["daily_correlation_to_bndx"] = returns[ticker].corr(returns["BNDX"])
        metric["tracking_error_to_bndx"] = (
            (returns[ticker] - returns["BNDX"]).std(ddof=1) * np.sqrt(252)
        )
        rows.append(metric)
    return pd.DataFrame(rows)


def stress_metrics(frame: pd.DataFrame, method: str) -> pd.DataFrame:
    windows = {
        "GFC": ("2007-10-09", "2009-03-09"),
        "COVID": ("2020-02-19", "2020-03-23"),
        "2022": ("2022-01-01", "2022-12-31"),
    }
    rows = []
    for period, (start, end) in windows.items():
        for name in frame:
            selected = frame[name].loc[start:end]
            nav = base.nav_from_returns(selected)
            rows.append(
                {
                    "pre_btc_method": method,
                    "period": period,
                    "series": name,
                    "start": selected.index.min().date().isoformat(),
                    "end": selected.index.max().date().isoformat(),
                    "return": (1.0 + selected).prod() - 1.0,
                    "max_drawdown": (nav / nav.cummax() - 1.0).min(),
                }
            )
    return pd.DataFrame(rows)


def overlap_parity(metrics: pd.DataFrame) -> pd.DataFrame:
    formal = pd.read_csv(
        ROOT / "outputs" / "subc_bond_sleeve_20260811" / "full_strategy_metrics.csv"
    )
    name_map = {
        "VGIT 15%": "New C + VGIT 15%",
        "VGIT 7.5% + BND 3.75% + BNDX 3.75%": (
            "New C + VGIT/BND/BNDX 7.5/3.75/3.75"
        ),
        "BND 7.5% + BNDX 7.5%": "New C + BND/BNDX 7.5/7.5",
    }
    rows = []
    for proxy_name, formal_name in name_map.items():
        proxy_rows = metrics[metrics["series"] == proxy_name].set_index("window")
        formal_rows = formal[formal["series"] == formal_name].set_index("window")
        for window in ("5Y", "3Y", "1Y"):
            rows.append(
                {
                    "series": proxy_name,
                    "window": window,
                    "cagr_difference": (
                        proxy_rows.loc[window, "cagr"] - formal_rows.loc[window, "cagr"]
                    ),
                    "max_drawdown_difference": (
                        proxy_rows.loc[window, "max_drawdown"]
                        - formal_rows.loc[window, "max_drawdown"]
                    ),
                }
            )
    return pd.DataFrame(rows)


def plot_results(full_returns: pd.DataFrame, bond_returns: pd.DataFrame, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 1, figsize=(13.5, 9.0), sharex=False)
    fig.subplots_adjust(left=0.08, right=0.985, top=0.90, bottom=0.09, hspace=0.30)

    full_nav = full_returns.apply(base.nav_from_returns)
    full_nav = full_nav.div(full_nav.iloc[0])
    for name in full_nav:
        axes[0].plot(full_nav.index, full_nav[name], linewidth=2.0, label=name)
    axes[0].set_title("策略 C 长周期代理净值", fontsize=14, fontweight="bold")
    axes[0].set_ylabel("归一化净值")
    axes[0].grid(True, alpha=0.24)
    axes[0].legend(frameon=False, fontsize=9)

    bond_nav = bond_returns.apply(base.nav_from_returns)
    bond_nav = bond_nav.div(bond_nav.iloc[0])
    for name in bond_nav:
        axes[1].plot(bond_nav.index, bond_nav[name], linewidth=1.8, label=name)
    axes[1].set_title("债券袖套长周期代理净值", fontsize=13, fontweight="bold")
    axes[1].set_ylabel("归一化净值")
    axes[1].set_xlabel("日期")
    axes[1].grid(True, alpha=0.24)
    axes[1].legend(frameon=False, fontsize=9)
    for axis in axes:
        axis.xaxis.set_major_locator(mdates.YearLocator(2))
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle("BND + BNDX：2007年至今长周期代理回测", fontsize=17, fontweight="bold", y=0.975)
    fig.text(
        0.01,
        0.018,
        "代理研究，非正式ETF历史；BNDX上市前使用PFORX美元对冲国际债券基金；Yahoo复权收盘；年度再平衡10bps；策略C使用V7.7目标波动率与融资/调仓成本。",
        fontsize=8.2,
        color="#4B5563",
    )
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    v77 = base.load_module(base.V77_PATH, "v77_bnd_bndx_long")
    v79 = base.load_module(base.V79_PATH, "v79_bnd_bndx_loader")
    long_base.RAW_TICKERS = RAW_TICKERS
    raw, sources, excluded_date = long_base.fetch_raw(v79)
    calendar = raw["SPY"].index

    prices, mapping = build_stitched_prices(raw, calendar, mf_proxy="RYMFX")
    main_returns, main_raw, main_scale, main_costs = run_full_variants(
        v77, prices, "renormalize"
    )
    cash_returns, _, _, _ = run_full_variants(v77, prices, "cash_placeholder")
    bond_returns = run_bond_variants(prices)

    aqmix_prices, _ = build_stitched_prices(raw, calendar, mf_proxy="AQMIX")
    aqmix_returns, _, _, _ = run_full_variants(v77, aqmix_prices, "renormalize")
    pgbix_prices, _ = build_stitched_prices(
        raw, calendar, mf_proxy="RYMFX", intl_bond_proxy="PGBIX"
    )
    pgbix_returns, _, _, _ = run_full_variants(v77, pgbix_prices, "renormalize")

    full_metrics = base.window_metrics(main_returns)
    cash_metrics = base.window_metrics(cash_returns)
    aqmix_metrics = base.window_metrics(aqmix_returns)
    pgbix_metrics = base.window_metrics(pgbix_returns)
    bond_metrics = base.window_metrics(bond_returns)
    deltas = pd.concat(
        [
            base.delta_metrics(full_metrics, "VGIT 15%", candidate)
            for candidate in list(VARIANTS_AFTER_BTC)[1:]
        ],
        ignore_index=True,
    )
    stress = pd.concat(
        [
            stress_metrics(main_returns, "renormalize"),
            stress_metrics(cash_returns, "cash_placeholder"),
        ],
        ignore_index=True,
    )
    quality = proxy_quality(raw, calendar)
    parity = overlap_parity(full_metrics)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_results(main_returns, bond_returns, OUT_DIR / "subc_bnd_bndx_long_proxy.png")
    daily = pd.concat(
        {
            "scaled_return": main_returns,
            "scaled_nav": main_returns.apply(base.nav_from_returns),
            "raw_return": main_raw,
            "scale": main_scale,
            "cost": main_costs,
            "bond_return": bond_returns,
            "bond_nav": bond_returns.apply(base.nav_from_returns),
        },
        axis=1,
    )
    daily.to_csv(OUT_DIR / "daily_nav_and_returns.csv", encoding="utf-8-sig")
    full_metrics.to_csv(OUT_DIR / "full_strategy_metrics.csv", index=False, encoding="utf-8-sig")
    bond_metrics.to_csv(OUT_DIR / "bond_sleeve_metrics.csv", index=False, encoding="utf-8-sig")
    cash_metrics.to_csv(OUT_DIR / "cash_placeholder_sensitivity.csv", index=False, encoding="utf-8-sig")
    aqmix_metrics.to_csv(OUT_DIR / "aqmix_sensitivity.csv", index=False, encoding="utf-8-sig")
    pgbix_metrics.to_csv(OUT_DIR / "pgbix_bndx_proxy_sensitivity.csv", index=False, encoding="utf-8-sig")
    deltas.to_csv(OUT_DIR / "candidate_deltas.csv", index=False, encoding="utf-8-sig")
    stress.to_csv(OUT_DIR / "stress_periods.csv", index=False, encoding="utf-8-sig")
    quality.to_csv(OUT_DIR / "proxy_quality.csv", index=False, encoding="utf-8-sig")
    parity.to_csv(OUT_DIR / "formal_overlap_check.csv", index=False, encoding="utf-8-sig")
    mapping.to_csv(OUT_DIR / "proxy_map.csv", index=False, encoding="utf-8-sig")
    sources.to_csv(OUT_DIR / "sources.csv", index=False, encoding="utf-8-sig")

    audit = {
        "status": "diagnostic_long_horizon_proxy_research",
        "created_at_shanghai": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "full_strategy_start": main_returns.index.min().date().isoformat(),
        "bond_sleeve_start": bond_returns.index.min().date().isoformat(),
        "end": main_returns.index.max().date().isoformat(),
        "excluded_unconfirmed_date": excluded_date,
        "data_source": "Yahoo adjusted close via mnt_bot V 7.9 plus.py",
        "calendar": "SPY US sessions; BTC weekend return accumulates to next US session",
        "bndx_proxy": "PFORX before BNDX live-return switch; BNDX actual afterward",
        "bndx_live_return_switch": mapping.loc[
            mapping["synthetic"] == "INTL_BOND", "live_return_switch"
        ].iloc[0],
        "main_pre_btc_method": "remove BTC 5% and renormalize remaining weights",
        "sensitivities": [
            "hold missing pre-BTC allocation in BIL",
            "AQMIX instead of RYMFX as managed-futures prehistory",
            "PGBIX instead of PFORX as the pre-BNDX USD-hedged global-bond proxy",
        ],
        "asset_rebalance_cost_rate": base.ASSET_REBAL_COST,
        "target_vol_source": "mnt_bot V 7.7 plus.py::_apply_subc_vol_scaling",
        "production_code_changed": False,
        "live_orders": False,
        "classification": "pre-live proxy results are not formal production history",
    }
    (OUT_DIR / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    record = [
        "# Strategy C BND + BNDX Long-Proxy Test",
        "",
        "## Classification",
        "",
        "Diagnostic proxy research only. PFORX is used before BNDX live returns begin;",
        "the pre-switch portion is not formal BNDX history.",
        "",
        f"- Full strategy window: {main_returns.index.min().date()} to {main_returns.index.max().date()}.",
        f"- Bond sleeve window: {bond_returns.index.min().date()} to {bond_returns.index.max().date()}.",
        "- Yahoo adjusted close; SPY US-session calendar.",
        "- Annual asset rebalance at 10 bps; official V7.7 target-vol overlay and costs.",
        "",
        "## Full Strategy — Mandatory Windows",
        "",
        "| Variant | Window | CAGR | Max drawdown | Annual vol | Sharpe |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for name in VARIANTS_AFTER_BTC:
        for _, row in full_metrics[full_metrics["series"] == name].iterrows():
            record.append(
                f"| {name} | {row['window']} | {row['cagr']:.2%} | "
                f"{row['max_drawdown']:.2%} | {row['annual_vol']:.2%} | "
                f"{row['sharpe_0rf']:.2f} |"
            )
    record.extend(
        [
            "",
            "## Bond Sleeve — Mandatory Windows",
            "",
            "| Variant | Window | CAGR | Max drawdown | Annual vol | Sharpe |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for name in BOND_VARIANTS:
        for _, row in bond_metrics[bond_metrics["series"] == name].iterrows():
            record.append(
                f"| {name} | {row['window']} | {row['cagr']:.2%} | "
                f"{row['max_drawdown']:.2%} | {row['annual_vol']:.2%} | "
                f"{row['sharpe_0rf']:.2f} |"
            )
    (OUT_DIR / "record.md").write_text("\n".join(record) + "\n", encoding="utf-8")

    print("PROXY_MAP")
    print(mapping.to_string(index=False))
    print("\nFULL_STRATEGY_METRICS")
    print(full_metrics.to_string(index=False))
    print("\nBOND_SLEEVE_METRICS")
    print(bond_metrics.to_string(index=False))
    print("\nDELTAS")
    print(deltas.to_string(index=False))
    print("\nSTRESS")
    print(stress.to_string(index=False))
    print("\nPROXY_QUALITY")
    print(quality.to_string(index=False))
    print("\nPGBIX_BNDX_PROXY_SENSITIVITY")
    print(pgbix_metrics.to_string(index=False))
    print("\nFORMAL_OVERLAP_PARITY")
    print(parity.to_string(index=False))
    print("\nOUTPUT", OUT_DIR)


if __name__ == "__main__":
    main()

"""Strategy C test: replace the 15% VGIT sleeve with 10% RSP + 5% VEA.

The 2007-era section uses the same proxy framework as the prior Strategy C
long-horizon research.  It is diagnostic proxy research, not formal ETF history.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

import research_subc_bond_necessity_long_proxy as long_base
import research_subc_bond_sleeve_backtest as base


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "outputs" / "subc_bond_to_rsp_vea_20260812"
FORMAL_START = pd.Timestamp("2020-12-03")

PROXY_MAP = {
    **long_base.PROXY_MAP,
    "RSP": ("RSP", None, "RSP actual"),
}

RAW_TICKERS = sorted(
    {
        ticker
        for proxy, live, _ in PROXY_MAP.values()
        for ticker in (proxy, live)
        if ticker is not None
    }
    | {"AQMIX"}
)

COMMON_AFTER_BTC = dict(long_base.COMMON_AFTER_BTC)
NO_BOND_MULTIPLIER = 1.0 / sum(COMMON_AFTER_BTC.values())
VARIANTS_AFTER_BTC = {
    "VGIT 15%": {**COMMON_AFTER_BTC, "TREASURY": 0.15},
    "RSP 10% + VEA extra 5%": {
        **COMMON_AFTER_BTC,
        "DEVELOPED": 0.15,
        "RSP": 0.10,
    },
    "No bond, pro-rata risk assets": {
        ticker: weight * NO_BOND_MULTIPLIER
        for ticker, weight in COMMON_AFTER_BTC.items()
    },
}


def build_prices(
    raw: dict[str, pd.Series],
    calendar: pd.DatetimeIndex,
    mf_proxy: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mapping = dict(PROXY_MAP)
    mapping["MF_1"] = (mf_proxy, "DBMF", f"{mf_proxy} -> DBMF")
    mapping["MF_2"] = (mf_proxy, "KMLM", f"{mf_proxy} -> KMLM")
    stitched = {}
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
    return pd.concat(stitched.values(), axis=1).sort_index(), pd.DataFrame(rows)


def run_variants(
    v77,
    prices: pd.DataFrame,
    pre_btc_method: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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

    scaled = {}
    raw_returns = {}
    scales = {}
    costs = {}
    turnovers = {}
    for name, after in VARIANTS_AFTER_BTC.items():
        before = long_base.pre_btc_weights(after, pre_btc_method)
        raw_ret, turnover, asset_cost = long_base.phased_annual_returns(
            prices, after, before, btc_start
        )
        scaled_ret, scale, scale_cost = v77._apply_subc_vol_scaling(raw_ret, prices)
        scaled[name] = scaled_ret
        raw_returns[name] = raw_ret
        scales[name] = scale
        costs[name] = asset_cost.add(scale_cost, fill_value=0.0)
        turnovers[name] = turnover
    common = pd.DataFrame(scaled).dropna(how="any")
    return (
        common,
        pd.DataFrame(raw_returns).reindex(common.index),
        pd.DataFrame(scales).reindex(common.index),
        pd.DataFrame(costs).reindex(common.index),
        pd.DataFrame(turnovers).reindex(common.index),
    )


def run_formal_variants(
    v77,
    raw: dict[str, pd.Series],
    calendar: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    live_map = {
        "VTI": "VTI",
        "QQQ": "QQQ",
        "US_SMALL_VALUE": "AVUV",
        "DEVELOPED": "VEA",
        "INTL_SMALL_VALUE": "AVDV",
        "MF_1": "DBMF",
        "MF_2": "KMLM",
        "GOLD": "GLD",
        "BTC": "BTC-USD",
        "TREASURY": "VGIT",
        "RSP": "RSP",
        "BIL": "BIL",
    }
    formal_prices = pd.concat(
        {
            synthetic: raw[ticker].reindex(calendar)
            for synthetic, ticker in live_map.items()
        },
        axis=1,
    )
    required = sorted(
        {ticker for weights in VARIANTS_AFTER_BTC.values() for ticker in weights}
        | {"BIL"}
    )
    formal_prices = formal_prices.loc[:, required].dropna(how="any")
    formal_prices = formal_prices.loc[
        formal_prices.index >= FORMAL_START - pd.offsets.BDay(2)
    ]

    scaled = {}
    raw_returns = {}
    scales = {}
    costs = {}
    turnovers = {}
    for name, weights in VARIANTS_AFTER_BTC.items():
        raw_ret, turnover, asset_cost = base.annual_rebalanced_returns(
            formal_prices, weights
        )
        scaled_ret, scale, scale_cost = v77._apply_subc_vol_scaling(
            raw_ret, formal_prices
        )
        scaled[name] = scaled_ret
        raw_returns[name] = raw_ret
        scales[name] = scale
        costs[name] = asset_cost.add(scale_cost, fill_value=0.0)
        turnovers[name] = turnover
    common = pd.DataFrame(scaled).dropna(how="any")
    common = common.loc[common.index >= FORMAL_START]
    return (
        common,
        pd.DataFrame(raw_returns).reindex(common.index),
        pd.DataFrame(scales).reindex(common.index),
        pd.DataFrame(costs).reindex(common.index),
        pd.DataFrame(turnovers).reindex(common.index),
    )


def stress_metrics(frame: pd.DataFrame, sample: str) -> pd.DataFrame:
    windows = {
        "GFC": ("2007-10-09", "2009-03-09"),
        "COVID": ("2020-02-19", "2020-03-23"),
        "2022": ("2022-01-01", "2022-12-31"),
    }
    rows = []
    for period, (start, end) in windows.items():
        for name in frame:
            selected = frame[name].loc[start:end]
            if selected.empty:
                continue
            nav = base.nav_from_returns(selected)
            rows.append(
                {
                    "sample": sample,
                    "period": period,
                    "series": name,
                    "start": selected.index.min().date().isoformat(),
                    "end": selected.index.max().date().isoformat(),
                    "return": (1.0 + selected).prod() - 1.0,
                    "max_drawdown": (nav / nav.cummax() - 1.0).min(),
                }
            )
    return pd.DataFrame(rows)


def overlay_audit(
    scales: pd.DataFrame,
    costs: pd.DataFrame,
    turnovers: pd.DataFrame,
    sample: str,
) -> pd.DataFrame:
    rows = []
    for name in scales:
        scale = scales[name]
        rows.append(
            {
                "sample": sample,
                "series": name,
                "average_scale": scale.mean(),
                "median_scale": scale.median(),
                "min_scale": scale.min(),
                "max_scale": scale.max(),
                "pct_days_at_min_0_5": (scale <= 0.5000001).mean(),
                "pct_days_at_max_1_5": (scale >= 1.4999999).mean(),
                "scale_adjustment_days": int((scale.diff().abs() > 1e-12).sum()),
                "total_cost_fraction_sum": costs[name].sum(),
                "annual_and_phase_turnover_sum": turnovers[name].sum(),
            }
        )
    return pd.DataFrame(rows)


def saved_baseline_parity(formal_returns: pd.DataFrame) -> pd.DataFrame:
    saved = pd.read_csv(
        ROOT / "outputs" / "subc_bond_sleeve_20260811" / "full_strategy_metrics.csv"
    )
    saved = saved[saved["series"] == "New C + VGIT 15%"].set_index("window")
    saved_end = pd.Timestamp(saved.loc["Full", "end"])
    overlap = formal_returns.loc[:saved_end, ["VGIT 15%"]]
    measured = base.window_metrics(overlap).set_index("window")
    rows = []
    for window in ("Full", "5Y", "3Y", "1Y"):
        rows.append(
            {
                "window": window,
                "saved_end": saved_end.date().isoformat(),
                "cagr_difference": measured.loc[window, "cagr"] - saved.loc[window, "cagr"],
                "max_drawdown_difference": (
                    measured.loc[window, "max_drawdown"]
                    - saved.loc[window, "max_drawdown"]
                ),
            }
        )
    return pd.DataFrame(rows)


def plot_results(frame: pd.DataFrame, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    nav = frame.apply(base.nav_from_returns)
    nav = nav.div(nav.iloc[0])
    drawdown = nav.div(nav.cummax()).sub(1.0)
    fig, axes = plt.subplots(2, 1, figsize=(13.5, 8.8), sharex=True)
    fig.subplots_adjust(left=0.08, right=0.985, top=0.90, bottom=0.09, hspace=0.10)
    for name in nav:
        axes[0].plot(nav.index, nav[name], linewidth=2.0, label=name)
        axes[1].plot(drawdown.index, drawdown[name] * 100, linewidth=1.45, label=name)
    axes[0].set_title("策略 C 长周期代理净值", fontsize=14, fontweight="bold")
    axes[0].set_ylabel("归一化净值")
    axes[0].grid(True, alpha=0.24)
    axes[0].legend(frameon=False, fontsize=9)
    axes[1].axhline(0, color="#6B7280", linewidth=0.8)
    axes[1].set_ylabel("回撤（%）")
    axes[1].set_xlabel("日期")
    axes[1].grid(True, alpha=0.24)
    axes[1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle("债券15%改配RSP 10% + VEA 5%", fontsize=17, fontweight="bold", y=0.975)
    fig.text(
        0.01,
        0.018,
        "2007年前段含代理；Yahoo复权收盘；年度再平衡10bps；V7.7目标波动率15日/15%/0.5-1.5x及融资与调仓成本。",
        fontsize=8.2,
        color="#4B5563",
    )
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def metrics_markdown(metrics: pd.DataFrame, names: list[str]) -> list[str]:
    lines = [
        "| Variant | Window | CAGR | Max drawdown | Annual vol | Sharpe |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for name in names:
        for _, row in metrics[metrics["series"] == name].iterrows():
            if pd.isna(row["cagr"]):
                lines.append(
                    f"| {name} | {row['window']} | N/A | N/A | N/A | N/A |"
                )
            else:
                lines.append(
                    f"| {name} | {row['window']} | {row['cagr']:.2%} | "
                    f"{row['max_drawdown']:.2%} | {row['annual_vol']:.2%} | "
                    f"{row['sharpe_0rf']:.2f} |"
                )
    return lines


def main() -> None:
    v77 = base.load_module(base.V77_PATH, "v77_rsp_vea")
    v79 = base.load_module(base.V79_PATH, "v79_rsp_vea_loader")
    long_base.RAW_TICKERS = RAW_TICKERS
    raw, sources, excluded_date = long_base.fetch_raw(v79)
    calendar = raw["SPY"].index

    prices, mapping = build_prices(raw, calendar, "RYMFX")
    main, raw_returns, scales, costs, turnovers = run_variants(
        v77, prices, "renormalize"
    )
    cash, _, cash_scales, cash_costs, cash_turnovers = run_variants(
        v77, prices, "cash_placeholder"
    )
    aqmix_prices, _ = build_prices(raw, calendar, "AQMIX")
    aqmix, _, _, _, _ = run_variants(v77, aqmix_prices, "renormalize")

    long_metrics = base.window_metrics(main)
    formal, formal_raw, formal_scales, formal_costs, formal_turnovers = (
        run_formal_variants(v77, raw, calendar)
    )
    formal_metrics = base.window_metrics(formal)
    cash_metrics = base.window_metrics(cash)
    aqmix_metrics = base.window_metrics(aqmix)
    deltas = pd.concat(
        [
            base.delta_metrics(long_metrics, "VGIT 15%", candidate)
            for candidate in list(VARIANTS_AFTER_BTC)[1:]
        ],
        ignore_index=True,
    )
    formal_deltas = pd.concat(
        [
            base.delta_metrics(formal_metrics, "VGIT 15%", candidate)
            for candidate in list(VARIANTS_AFTER_BTC)[1:]
        ],
        ignore_index=True,
    )
    stress = pd.concat(
        [stress_metrics(main, "long_proxy"), stress_metrics(formal, "formal_overlap")],
        ignore_index=True,
    )
    overlay = pd.concat(
        [
            overlay_audit(scales, costs, turnovers, "long_proxy"),
            overlay_audit(
                cash_scales, cash_costs, cash_turnovers, "cash_placeholder"
            ),
            overlay_audit(
                formal_scales,
                formal_costs,
                formal_turnovers,
                "formal_overlap",
            ),
        ],
        ignore_index=True,
    )
    parity = saved_baseline_parity(formal)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_results(main, OUT_DIR / "subc_bond_to_rsp_vea.png")
    daily = pd.concat(
        {
            "scaled_return": main,
            "scaled_nav": main.apply(base.nav_from_returns),
            "raw_return": raw_returns,
            "scale": scales,
            "cost": costs,
        },
        axis=1,
    )
    daily.to_csv(OUT_DIR / "daily_nav_and_returns.csv", encoding="utf-8-sig")
    long_metrics.to_csv(OUT_DIR / "long_proxy_metrics.csv", index=False, encoding="utf-8-sig")
    formal_metrics.to_csv(OUT_DIR / "formal_overlap_metrics.csv", index=False, encoding="utf-8-sig")
    deltas.to_csv(OUT_DIR / "long_proxy_deltas.csv", index=False, encoding="utf-8-sig")
    formal_deltas.to_csv(OUT_DIR / "formal_overlap_deltas.csv", index=False, encoding="utf-8-sig")
    cash_metrics.to_csv(OUT_DIR / "cash_placeholder_sensitivity.csv", index=False, encoding="utf-8-sig")
    aqmix_metrics.to_csv(OUT_DIR / "aqmix_sensitivity.csv", index=False, encoding="utf-8-sig")
    stress.to_csv(OUT_DIR / "stress_periods.csv", index=False, encoding="utf-8-sig")
    overlay.to_csv(OUT_DIR / "overlay_audit.csv", index=False, encoding="utf-8-sig")
    parity.to_csv(OUT_DIR / "saved_baseline_parity.csv", index=False, encoding="utf-8-sig")
    mapping.to_csv(OUT_DIR / "proxy_map.csv", index=False, encoding="utf-8-sig")
    sources.to_csv(OUT_DIR / "sources.csv", index=False, encoding="utf-8-sig")

    audit = {
        "status": "diagnostic_long_proxy_plus_formal_overlap_research",
        "created_at_shanghai": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "long_sample_start": main.index.min().date().isoformat(),
        "formal_overlap_start": formal.index.min().date().isoformat(),
        "sample_end": main.index.max().date().isoformat(),
        "excluded_unconfirmed_date": excluded_date,
        "candidate": "remove VGIT 15%; add RSP 10% and increase VEA from 10% to 15%",
        "data_source": "Yahoo adjusted close via mnt_bot V 7.9 plus.py",
        "calendar": "SPY US sessions; BTC weekend return accumulates to next US session",
        "main_pre_btc_method": "remove BTC 5% and renormalize remaining weights",
        "sensitivity_pre_btc_method": "hold missing BTC 5% in BIL",
        "managed_futures_proxy_sensitivity": "AQMIX instead of RYMFX",
        "asset_rebalance_cost_rate": base.ASSET_REBAL_COST,
        "target_vol_source": "mnt_bot V 7.7 plus.py::_apply_subc_vol_scaling",
        "production_code_changed": False,
        "live_orders": False,
    }
    (OUT_DIR / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    record = [
        "# Strategy C: Replace VGIT 15% with RSP 10% + VEA 5%",
        "",
        "## Classification",
        "",
        "- Long sample is diagnostic proxy research.",
        "- Formal overlap begins when KMLM live returns are available.",
        f"- Long window: {main.index.min().date()} to {main.index.max().date()}.",
        f"- Formal overlap: {formal.index.min().date()} to {formal.index.max().date()}.",
        "- Yahoo adjusted close; annual rebalance 10 bps; official V7.7 target-vol overlay and costs.",
        "",
        "## Long Proxy — Mandatory Windows",
        "",
        *metrics_markdown(long_metrics, list(VARIANTS_AFTER_BTC)),
        "",
        "## Formal Overlap — Mandatory Windows",
        "",
        "- Formal 10Y is N/A because KMLM live history begins in December 2020.",
        "",
        *metrics_markdown(formal_metrics, list(VARIANTS_AFTER_BTC)),
    ]
    (OUT_DIR / "record.md").write_text("\n".join(record) + "\n", encoding="utf-8")

    print("PROXY_MAP")
    print(mapping.to_string(index=False))
    print("\nLONG_METRICS")
    print(long_metrics.to_string(index=False))
    print("\nFORMAL_METRICS")
    print(formal_metrics.to_string(index=False))
    print("\nLONG_DELTAS")
    print(deltas.to_string(index=False))
    print("\nSTRESS")
    print(stress.to_string(index=False))
    print("\nBASELINE_PARITY")
    print(parity.to_string(index=False))
    print("\nOUTPUT", OUT_DIR)


if __name__ == "__main__":
    main()

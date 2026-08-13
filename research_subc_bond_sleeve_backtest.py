"""Compare the legacy VGIT bond sleeve with a 50/50 BND/BNDX replacement.

This is a research-only harness. It reuses the repository's corrected Yahoo
loader and the official V7.7 Sub-C target-volatility scaler, while keeping the
candidate portfolio construction explicit and auditable.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
V77_PATH = ROOT / "mnt_bot V 7.7 plus.py"
V79_PATH = ROOT / "mnt_bot V 7.9 plus.py"
OUT_DIR = ROOT / "outputs" / "subc_bond_sleeve_20260811"
FETCH_START = "2013-01-01"
ASSET_REBAL_COST = 0.001

TICKERS = [
    "VGIT",
    "BND",
    "BNDX",
    "VTI",
    "QQQ",
    "AVUV",
    "VEA",
    "AVDV",
    "DBMF",
    "KMLM",
    "GLD",
    "BTC-USD",
    "BIL",
    "SPY",
]

BOND_VARIANTS = {
    "VGIT 100%": {"VGIT": 1.0},
    "VGIT/BND/BNDX 50/25/25": {"VGIT": 0.5, "BND": 0.25, "BNDX": 0.25},
    "BND/BNDX 50:50": {"BND": 0.5, "BNDX": 0.5},
    "BND 100%": {"BND": 1.0},
    "BNDX 100%": {"BNDX": 1.0},
}

COMMON_WEIGHTS = {
    "VTI": 0.20,
    "QQQ": 0.10,
    "AVUV": 0.10,
    "VEA": 0.10,
    "AVDV": 0.10,
    "DBMF": 0.025,
    "KMLM": 0.025,
    "GLD": 0.15,
    "BTC-USD": 0.05,
}

FULL_VARIANTS = {
    "New C + VGIT 15%": {**COMMON_WEIGHTS, "VGIT": 0.15},
    "New C + VGIT/BND/BNDX 7.5/3.75/3.75": {
        **COMMON_WEIGHTS,
        "VGIT": 0.075,
        "BND": 0.0375,
        "BNDX": 0.0375,
    },
    "New C + BND/BNDX 7.5/7.5": {
        **COMMON_WEIGHTS,
        "BND": 0.075,
        "BNDX": 0.075,
    },
}

WINDOWS = [
    ("Full", None),
    ("10Y", 10),
    ("5Y", 5),
    ("3Y", 3),
    ("1Y", 1),
]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ADJUSTED_PRICE_SOURCES = {"Yahoo", "Yahoo+Nasdaq-gap"}


def fetch_adjusted_close(loader) -> tuple[pd.DataFrame, pd.DataFrame, str | None]:
    series = {}
    source_rows = []
    for ticker in TICKERS:
        frame, source = loader.fetch_yahoo(ticker, start_date=FETCH_START)
        if frame is None or frame.empty:
            raise RuntimeError(f"No data for {ticker}: {source}")
        if source not in ADJUSTED_PRICE_SOURCES:
            raise RuntimeError(f"{ticker} used {source}; Yahoo adjusted close is required")
        close = pd.to_numeric(frame["close"], errors="coerce").dropna()
        index = pd.DatetimeIndex(pd.to_datetime(close.index))
        if index.tz is not None:
            index = index.tz_convert(None)
        close.index = index.normalize()
        close = close[~close.index.duplicated(keep="last")].sort_index()
        series[ticker] = close.rename(ticker)
        source_rows.append(
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
    latest_confirmed = None
    if now_ny.time() < pd.Timestamp("16:15").time():
        latest_confirmed = now_ny.date()
        excluded = now_ny.date().isoformat()

    frame = pd.concat(series.values(), axis=1).sort_index()
    if latest_confirmed is not None:
        frame = frame[frame.index.date < latest_confirmed]
    return frame, pd.DataFrame(source_rows), excluded


def common_price_frame(all_prices: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    etfs = [ticker for ticker in tickers if ticker != "BTC-USD"]
    frame = all_prices[etfs].dropna(how="any")
    if "BTC-USD" in tickers:
        frame = frame.join(all_prices["BTC-USD"], how="left").dropna(how="any")
    return frame[tickers]


def annual_rebalanced_returns(
    prices: pd.DataFrame,
    weights: dict[str, float],
    cost_rate: float = ASSET_REBAL_COST,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Daily close-to-close returns; rebalance before first session each year."""
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-12):
        raise ValueError(f"Weights do not sum to one: {sum(weights.values())}")
    prices = prices[list(weights)].dropna(how="any")
    asset_ret = prices.pct_change().dropna(how="any")
    holdings = pd.Series(weights, dtype=float)
    prev_value = float(holdings.sum())
    prev_year = asset_ret.index[0].year
    portfolio_ret = []
    turnover_rows = []
    cost_rows = []

    for date, row in asset_ret.iterrows():
        turnover = 0.0
        cost = 0.0
        if date.year != prev_year:
            actual_weights = holdings / holdings.sum()
            target_weights = pd.Series(weights, dtype=float)
            turnover = float((target_weights - actual_weights).abs().sum())
            cost = float(holdings.sum() * turnover * cost_rate)
            post_cost_value = float(holdings.sum() - cost)
            holdings = target_weights * post_cost_value
            prev_year = date.year

        holdings = holdings * (1.0 + row.reindex(holdings.index).fillna(0.0))
        value = float(holdings.sum())
        portfolio_ret.append(value / prev_value - 1.0)
        turnover_rows.append(turnover)
        cost_rows.append(cost / prev_value if prev_value > 0 else 0.0)
        prev_value = value

    index = asset_ret.index
    return (
        pd.Series(portfolio_ret, index=index, name="return"),
        pd.Series(turnover_rows, index=index, name="turnover"),
        pd.Series(cost_rows, index=index, name="asset_rebalance_cost"),
    )


def nav_from_returns(returns: pd.Series) -> pd.Series:
    return (1.0 + returns.fillna(0.0)).cumprod()


def metric_row(returns: pd.Series, series_name: str, window_name: str) -> dict[str, object]:
    returns = pd.to_numeric(returns, errors="coerce").dropna().sort_index()
    nav = nav_from_returns(returns)
    years = (returns.index[-1] - returns.index[0]).days / 365.25
    annual_vol = returns.std(ddof=1) * math.sqrt(252)
    cagr = nav.iloc[-1] ** (1.0 / years) - 1.0
    drawdown = nav / nav.cummax() - 1.0
    sharpe = returns.mean() / returns.std(ddof=1) * math.sqrt(252)
    return {
        "series": series_name,
        "window": window_name,
        "start": returns.index[0].date().isoformat(),
        "end": returns.index[-1].date().isoformat(),
        "rows": len(returns),
        "cagr": float(cagr),
        "annual_vol": float(annual_vol),
        "max_drawdown": float(drawdown.min()),
        "sharpe_0rf": float(sharpe),
        "total_return": float(nav.iloc[-1] - 1.0),
    }


def window_metrics(return_frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    end = return_frame.dropna(how="all").index.max()
    for series_name in return_frame.columns:
        full = return_frame[series_name].dropna()
        for window_name, years_required in WINDOWS:
            if years_required is None:
                selected = full
            else:
                cutoff = end - pd.DateOffset(years=years_required)
                available_years = (end - full.index.min()).days / 365.25
                if available_years + 1 / 365.25 < years_required:
                    rows.append(
                        {
                            "series": series_name,
                            "window": window_name,
                            "start": None,
                            "end": end.date().isoformat(),
                            "rows": 0,
                            "cagr": np.nan,
                            "annual_vol": np.nan,
                            "max_drawdown": np.nan,
                            "sharpe_0rf": np.nan,
                            "total_return": np.nan,
                            "na_reason": "insufficient post-listing history",
                        }
                    )
                    continue
                selected = full.loc[full.index >= cutoff]
            row = metric_row(selected, series_name, window_name)
            row["na_reason"] = None
            rows.append(row)
    return pd.DataFrame(rows)


def delta_metrics(metrics: pd.DataFrame, baseline: str, candidate: str) -> pd.DataFrame:
    base = metrics[metrics["series"] == baseline].set_index("window")
    cand = metrics[metrics["series"] == candidate].set_index("window")
    rows = []
    for window_name, _ in WINDOWS:
        b = base.loc[window_name]
        c = cand.loc[window_name]
        rows.append(
            {
                "window": window_name,
                "baseline": baseline,
                "candidate": candidate,
                "baseline_cagr": b["cagr"],
                "candidate_cagr": c["cagr"],
                "cagr_delta_pp": (c["cagr"] - b["cagr"]) * 100,
                "baseline_max_drawdown": b["max_drawdown"],
                "candidate_max_drawdown": c["max_drawdown"],
                "drawdown_improvement_pp": (c["max_drawdown"] - b["max_drawdown"]) * 100,
            }
        )
    return pd.DataFrame(rows)


def plot_results(bond_returns: pd.DataFrame, full_returns: pd.DataFrame, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(
        2,
        1,
        figsize=(13.5, 9.2),
        gridspec_kw={"hspace": 0.28},
    )
    fig.subplots_adjust(left=0.075, right=0.985, top=0.90, bottom=0.085, hspace=0.34)

    bond_nav = bond_returns.apply(nav_from_returns)
    bond_nav = bond_nav.div(bond_nav.iloc[0])
    for name in ["VGIT 100%", "VGIT/BND/BNDX 50/25/25", "BND/BNDX 50:50"]:
        axes[0].plot(bond_nav.index, bond_nav[name], linewidth=2.0, label=name)
    axes[0].set_title("债券袖套：VGIT 与 BND/BNDX 50:50（年度再平衡）", fontsize=14, fontweight="bold")
    axes[0].set_ylabel("归一化净值")
    axes[0].grid(True, alpha=0.25)
    axes[0].legend(frameon=False)

    full_nav = full_returns.apply(nav_from_returns)
    full_nav = full_nav.div(full_nav.iloc[0])
    for name in full_nav.columns:
        axes[1].plot(full_nav.index, full_nav[name], linewidth=2.0, label=name)
    axes[1].set_title("新策略 C：仅替换15%债券袖套，含目标波动率", fontsize=14, fontweight="bold")
    axes[1].set_ylabel("归一化净值")
    axes[1].set_xlabel("日期")
    axes[1].grid(True, alpha=0.25)
    axes[1].legend(frameon=False)
    axes[1].xaxis.set_major_locator(mdates.YearLocator())
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    fig.suptitle("策略 C 债券配置替换回测", fontsize=17, fontweight="bold", y=0.975)
    fig.text(
        0.01,
        0.012,
        "Yahoo复权收盘；美股交易日；资产年度再平衡成本10bps；目标波动率沿用V7.7：15日/15%、0.5-1.5x、阈值0.10、融资利差100bps、调仓成本6bps。",
        fontsize=8.5,
        color="#4B5563",
    )
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    v77 = load_module(V77_PATH, "v77_subc_bond_research")
    v79 = load_module(V79_PATH, "v79_subc_bond_loader")
    all_prices, sources, excluded_date = fetch_adjusted_close(v79)

    bond_prices = common_price_frame(all_prices, ["VGIT", "BND", "BNDX", "SPY"])
    bond_returns = {}
    bond_turnover = {}
    bond_costs = {}
    for name, weights in BOND_VARIANTS.items():
        ret, turnover, costs = annual_rebalanced_returns(bond_prices, weights)
        bond_returns[name] = ret
        bond_turnover[name] = turnover
        bond_costs[name] = costs
    bond_return_frame = pd.DataFrame(bond_returns).dropna(how="any")

    full_required = sorted(set().union(*(weights.keys() for weights in FULL_VARIANTS.values())))
    full_prices = common_price_frame(all_prices, full_required + ["BIL"])
    full_returns = {}
    full_raw_returns = {}
    full_scale = {}
    full_scale_cost = {}
    full_asset_turnover = {}
    full_asset_cost = {}
    for name, weights in FULL_VARIANTS.items():
        raw_ret, turnover, asset_cost = annual_rebalanced_returns(full_prices, weights)
        scaled_ret, scale, scale_cost = v77._apply_subc_vol_scaling(raw_ret, full_prices)
        full_raw_returns[name] = raw_ret
        full_returns[name] = scaled_ret
        full_scale[name] = scale
        full_scale_cost[name] = scale_cost
        full_asset_turnover[name] = turnover
        full_asset_cost[name] = asset_cost
    full_return_frame = pd.DataFrame(full_returns).dropna(how="any")
    full_raw_frame = pd.DataFrame(full_raw_returns).reindex(full_return_frame.index)

    bond_metrics = window_metrics(bond_return_frame)
    full_metrics = window_metrics(full_return_frame)
    bond_delta = pd.concat(
        [
            delta_metrics(bond_metrics, "VGIT 100%", "VGIT/BND/BNDX 50/25/25"),
            delta_metrics(bond_metrics, "VGIT 100%", "BND/BNDX 50:50"),
        ],
        ignore_index=True,
    )
    full_delta = pd.concat(
        [
            delta_metrics(
                full_metrics,
                "New C + VGIT 15%",
                "New C + VGIT/BND/BNDX 7.5/3.75/3.75",
            ),
            delta_metrics(
                full_metrics,
                "New C + VGIT 15%",
                "New C + BND/BNDX 7.5/7.5",
            ),
        ],
        ignore_index=True,
    )

    spy_ret = bond_prices["SPY"].pct_change().reindex(bond_return_frame.index)
    defense_rows = []
    for name in [
        "VGIT 100%",
        "VGIT/BND/BNDX 50/25/25",
        "BND/BNDX 50:50",
        "BND 100%",
        "BNDX 100%",
    ]:
        ret = bond_return_frame[name]
        common = pd.concat([ret, spy_ret.rename("SPY")], axis=1).dropna()
        worst_decile = common["SPY"] <= common["SPY"].quantile(0.10)
        y2022 = common.loc["2022-01-01":"2022-12-31", name]
        covid = common.loc["2020-02-19":"2020-03-23", name]
        defense_rows.append(
            {
                "series": name,
                "correlation_to_spy": common[name].corr(common["SPY"]),
                "down_day_correlation": common.loc[common["SPY"] < 0, name].corr(
                    common.loc[common["SPY"] < 0, "SPY"]
                ),
                "average_return_on_worst_10pct_spy_days": common.loc[worst_decile, name].mean(),
                "covid_2020_02_19_to_03_23_return": (1.0 + covid).prod() - 1.0,
                "calendar_2022_return": (1.0 + y2022).prod() - 1.0,
            }
        )
    defense = pd.DataFrame(defense_rows)

    overlay_rows = []
    for name in FULL_VARIANTS:
        scale = full_scale[name].reindex(full_return_frame.index)
        overlay_rows.append(
            {
                "series": name,
                "average_scale": scale.mean(),
                "median_scale": scale.median(),
                "min_scale": scale.min(),
                "max_scale": scale.max(),
                "pct_days_at_min_0_5": (scale <= 0.5000001).mean(),
                "pct_days_at_max_1_5": (scale >= 1.4999999).mean(),
                "scale_adjustment_days": int((scale.diff().abs() > 1e-12).sum()),
                "total_scale_cost_nav_fraction": full_scale_cost[name].sum(),
                "total_asset_rebalance_cost_nav_fraction": full_asset_cost[name].sum(),
                "annual_rebalance_turnover_sum": full_asset_turnover[name].sum(),
            }
        )
    overlay = pd.DataFrame(overlay_rows)

    # Reconcile the custom daily annual-rebalance helper to the repository's
    # official monthly simulate_prod engine on an unchanged BND/BNDX baseline.
    parity_monthly_prices = bond_prices[["BND", "BNDX"]].resample("ME").last()
    parity_start = bond_prices.loc[: parity_monthly_prices.index[0]].index[-1]
    parity_daily_prices = bond_prices.loc[parity_start:, ["BND", "BNDX"]]
    parity_daily_ret, _, _ = annual_rebalanced_returns(
        parity_daily_prices, {"BND": 0.5, "BNDX": 0.5}
    )
    parity_daily_nav = nav_from_returns(parity_daily_ret).resample("ME").last()
    parity_monthly_ret = parity_monthly_prices.pct_change().dropna()
    parity_signals = pd.DataFrame(
        1.0, index=parity_monthly_ret.index, columns=parity_monthly_ret.columns
    )
    parity_portfolio = {
        ticker: {"w": 0.5, "proxy": ticker} for ticker in ("BND", "BNDX")
    }
    parity_official_nav, _ = v77.simulate_prod(
        parity_portfolio,
        parity_monthly_ret,
        parity_signals,
        pd.Series(0.0, index=parity_monthly_ret.index),
        12,
        commission=ASSET_REBAL_COST,
    )
    parity_common = pd.concat(
        [
            parity_daily_nav.reindex(parity_official_nav.index).rename("daily_helper"),
            parity_official_nav.rename("official_monthly"),
        ],
        axis=1,
    ).dropna()
    parity_max_abs_nav_diff = float(
        (parity_common["daily_helper"] - parity_common["official_monthly"]).abs().max()
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_results(bond_return_frame, full_return_frame, OUT_DIR / "subc_bond_variant_backtest.png")
    daily = pd.concat(
        {
            "bond_return": bond_return_frame,
            "bond_nav": bond_return_frame.apply(nav_from_returns),
            "full_raw_return": full_raw_frame,
            "full_scaled_return": full_return_frame,
            "full_scaled_nav": full_return_frame.apply(nav_from_returns),
            "full_scale": pd.DataFrame(full_scale).reindex(full_return_frame.index),
        },
        axis=1,
    )
    daily.to_csv(OUT_DIR / "daily_nav_and_returns.csv", encoding="utf-8-sig")
    bond_metrics.to_csv(OUT_DIR / "bond_sleeve_metrics.csv", index=False, encoding="utf-8-sig")
    full_metrics.to_csv(OUT_DIR / "full_strategy_metrics.csv", index=False, encoding="utf-8-sig")
    pd.concat(
        [bond_delta.assign(scope="bond_sleeve"), full_delta.assign(scope="full_strategy")],
        ignore_index=True,
    ).to_csv(OUT_DIR / "candidate_deltas.csv", index=False, encoding="utf-8-sig")
    defense.to_csv(OUT_DIR / "defense_metrics.csv", index=False, encoding="utf-8-sig")
    overlay.to_csv(OUT_DIR / "vol_scale_audit.csv", index=False, encoding="utf-8-sig")
    sources.to_csv(OUT_DIR / "sources.csv", index=False, encoding="utf-8-sig")

    audit = {
        "status": "observed_real_data_research_backtest",
        "created_at_shanghai": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "data_source": "Yahoo via mnt_bot V 7.9 plus.py fetch_yahoo",
        "adjustment": "Yahoo adjusted close",
        "calendar": "common US ETF sessions; BTC-USD accumulated weekend return enters next ETF session",
        "excluded_unconfirmed_date": excluded_date,
        "bond_formal_start": bond_return_frame.index.min().date().isoformat(),
        "bond_end": bond_return_frame.index.max().date().isoformat(),
        "full_formal_start": full_return_frame.index.min().date().isoformat(),
        "full_end": full_return_frame.index.max().date().isoformat(),
        "asset_rebalance": "before first US ETF session of each calendar year",
        "asset_rebalance_cost_rate": ASSET_REBAL_COST,
        "target_vol_source": "mnt_bot V 7.7 plus.py::_apply_subc_vol_scaling",
        "target_vol_parameters": {
            "target_vol": v77.PROD_VS_TARGET_VOL,
            "vol_window": v77.PROD_VS_VOL_WINDOW,
            "min_leverage": v77.PROD_VS_MIN_LEV,
            "max_leverage": v77.PROD_VS_MAX_LEV,
            "scale_change_threshold": v77.PROD_VS_THRESHOLD,
            "financing_spread_bps": v77.PROD_VS_SPREAD_BPS,
            "scale_rebalance_cost_bps": v77.PROD_VS_REBAL_COST_BPS,
        },
        "timing": "close-to-close research returns; annual rebalance cost charged before first session return",
        "live_orders": False,
        "production_code_changed": False,
        "annual_rebalance_baseline_parity": {
            "baseline": "BND/BNDX 50:50",
            "official_function": "mnt_bot V 7.7 plus.py::simulate_prod",
            "month_end_rows": len(parity_common),
            "max_absolute_nav_difference": parity_max_abs_nav_diff,
        },
        "known_limitations": [
            "No bid/ask slippage beyond configured asset and vol-scale costs",
            "QQQ/GLD/BTC-USD are the repository's designated history proxies for QQQM/GLDM/IBIT",
            "Full strategy has no valid 10Y ETF-only sample because KMLM began in December 2020",
        ],
    }
    (OUT_DIR / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    def pick(frame: pd.DataFrame, series: str, window: str) -> pd.Series:
        return frame[(frame["series"] == series) & (frame["window"] == window)].iloc[0]

    bond_base = pick(bond_metrics, "VGIT 100%", "Full")
    bond_hybrid = pick(bond_metrics, "VGIT/BND/BNDX 50/25/25", "Full")
    bond_replace = pick(bond_metrics, "BND/BNDX 50:50", "Full")
    full_base = pick(full_metrics, "New C + VGIT 15%", "Full")
    full_hybrid = pick(full_metrics, "New C + VGIT/BND/BNDX 7.5/3.75/3.75", "Full")
    full_replace = pick(full_metrics, "New C + BND/BNDX 7.5/7.5", "Full")
    defense_idx = defense.set_index("series")
    record = f"""# Strategy C Bond Sleeve Replacement Test

## Scope

- Baseline: VGIT 15% bond sleeve.
- Candidate: BND 7.5% + BNDX 7.5%.
- Confirmation line: VGIT 7.5% + BND 3.75% + BNDX 3.75%.
- Result type: observed research backtest on real adjusted-close data; no production change.

## Data and execution

- Source: Yahoo adjusted close through the repository's V7.9 loader.
- Bond-only formal sample: {bond_return_frame.index.min().date()} to {bond_return_frame.index.max().date()}.
- Full new-C formal sample: {full_return_frame.index.min().date()} to {full_return_frame.index.max().date()}.
- Calendar: common US ETF sessions; current unconfirmed US daily bar excluded.
- Annual asset rebalance before the first US ETF session of each year; one-way cost 10 bps.
- Full portfolio applies the official V7.7 target-vol scaler: 15-day realized vol, 15% target,
  0.5-1.5x, 0.10 scale-change threshold, 100 bps financing spread, 6 bps scale cost.
- Daily annual-rebalance helper matched V7.7 `simulate_prod` on {len(parity_common)} month ends;
  maximum absolute NAV difference was {parity_max_abs_nav_diff:.3g}.
- QQQ, GLD and BTC-USD are the repository-designated history proxies for QQQM, GLDM and IBIT.

## Full-sample results

| Scope | Variant | CAGR | Max drawdown | Annual vol | Sharpe (0% rf) |
|---|---|---:|---:|---:|---:|
| Bond sleeve | VGIT | {bond_base['cagr']:.2%} | {bond_base['max_drawdown']:.2%} | {bond_base['annual_vol']:.2%} | {bond_base['sharpe_0rf']:.2f} |
| Bond sleeve | VGIT/BND/BNDX 50/25/25 | {bond_hybrid['cagr']:.2%} | {bond_hybrid['max_drawdown']:.2%} | {bond_hybrid['annual_vol']:.2%} | {bond_hybrid['sharpe_0rf']:.2f} |
| Bond sleeve | BND/BNDX 50:50 | {bond_replace['cagr']:.2%} | {bond_replace['max_drawdown']:.2%} | {bond_replace['annual_vol']:.2%} | {bond_replace['sharpe_0rf']:.2f} |
| Full new C | VGIT 15% | {full_base['cagr']:.2%} | {full_base['max_drawdown']:.2%} | {full_base['annual_vol']:.2%} | {full_base['sharpe_0rf']:.2f} |
| Full new C | VGIT/BND/BNDX 7.5/3.75/3.75 | {full_hybrid['cagr']:.2%} | {full_hybrid['max_drawdown']:.2%} | {full_hybrid['annual_vol']:.2%} | {full_hybrid['sharpe_0rf']:.2f} |
| Full new C | BND/BNDX 7.5/7.5 | {full_replace['cagr']:.2%} | {full_replace['max_drawdown']:.2%} | {full_replace['annual_vol']:.2%} | {full_replace['sharpe_0rf']:.2f} |

## Defensive behavior

| Variant | Correlation to SPY | Worst 10% SPY-day average | COVID drawdown-window return | 2022 return |
|---|---:|---:|---:|---:|
| VGIT | {defense_idx.loc['VGIT 100%', 'correlation_to_spy']:.2f} | {defense_idx.loc['VGIT 100%', 'average_return_on_worst_10pct_spy_days']:.3%} | {defense_idx.loc['VGIT 100%', 'covid_2020_02_19_to_03_23_return']:.2%} | {defense_idx.loc['VGIT 100%', 'calendar_2022_return']:.2%} |
| VGIT/BND/BNDX 50/25/25 | {defense_idx.loc['VGIT/BND/BNDX 50/25/25', 'correlation_to_spy']:.2f} | {defense_idx.loc['VGIT/BND/BNDX 50/25/25', 'average_return_on_worst_10pct_spy_days']:.3%} | {defense_idx.loc['VGIT/BND/BNDX 50/25/25', 'covid_2020_02_19_to_03_23_return']:.2%} | {defense_idx.loc['VGIT/BND/BNDX 50/25/25', 'calendar_2022_return']:.2%} |
| BND/BNDX 50:50 | {defense_idx.loc['BND/BNDX 50:50', 'correlation_to_spy']:.2f} | {defense_idx.loc['BND/BNDX 50:50', 'average_return_on_worst_10pct_spy_days']:.3%} | {defense_idx.loc['BND/BNDX 50:50', 'covid_2020_02_19_to_03_23_return']:.2%} | {defense_idx.loc['BND/BNDX 50:50', 'calendar_2022_return']:.2%} |

## Decision

Do not promote the full BND/BNDX replacement. It raised the bond sleeve's long-run CAGR,
but weakened equity-crisis defense. At the complete-portfolio level, the return difference
was immaterial and maximum drawdown was slightly worse. Retain VGIT 15% as the primary line;
keep the three-fund hybrid only as a diversification watchlist candidate.
"""
    (OUT_DIR / "record.md").write_text(record, encoding="utf-8")

    print("BOND_METRICS")
    print(bond_metrics.to_string(index=False))
    print("\nFULL_METRICS")
    print(full_metrics.to_string(index=False))
    print("\nDELTAS")
    print(pd.concat([bond_delta.assign(scope="bond"), full_delta.assign(scope="full")]).to_string(index=False))
    print("\nDEFENSE")
    print(defense.to_string(index=False))
    print("\nOVERLAY")
    print(overlay.to_string(index=False))
    print(f"\nOUTPUT={OUT_DIR}")


if __name__ == "__main__":
    main()

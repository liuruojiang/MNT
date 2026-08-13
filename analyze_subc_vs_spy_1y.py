"""Build a reproducible one-year Legacy Sub-C versus SPY NAV chart."""

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
OUT_DIR = ROOT / "outputs" / "subc_vs_spy_1y_20260811"
FETCH_START = "2024-01-01"
TICKERS = ["VTI", "QQQ", "VEA", "VGIT", "DBMF", "GLD", "BTC-USD", "BIL", "SPY"]
CORE_PROD_TICKERS = ["VTI", "QQQ", "VEA", "VGIT", "GLD", "BIL"]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metrics(nav: pd.Series) -> dict[str, object]:
    nav = pd.to_numeric(nav, errors="coerce").dropna().sort_index()
    ret = nav.pct_change().dropna()
    dd = nav / nav.cummax() - 1.0
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = nav.iloc[-1] ** (1.0 / years) - 1.0
    vol = ret.std(ddof=1) * math.sqrt(252)
    sharpe = ret.mean() / ret.std(ddof=1) * math.sqrt(252)
    return {
        "start": nav.index[0].date().isoformat(),
        "end": nav.index[-1].date().isoformat(),
        "rows": len(nav),
        "total_return": float(nav.iloc[-1] - 1.0),
        "cagr": float(cagr),
        "annual_vol": float(vol),
        "sharpe_0rf": float(sharpe),
        "max_drawdown": float(dd.min()),
    }


def main() -> None:
    v77 = load_module(V77_PATH, "v77_subc_chart")
    v79 = load_module(V79_PATH, "v79_data_loader_for_subc_chart")

    raw: dict[str, pd.DataFrame] = {}
    sources = []
    for ticker in TICKERS:
        frame, source = v79.fetch_yahoo(ticker, start_date=FETCH_START)
        if frame is None or frame.empty:
            raise RuntimeError(f"No data returned for {ticker}: {source}")
        if source != "Yahoo":
            raise RuntimeError(
                f"{ticker} fell back to {source}; adjusted-close parity is required for this chart"
            )
        frame = frame.copy()
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index)).tz_localize(None).normalize()
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        raw[ticker] = frame
        sources.append(
            {
                "ticker": ticker,
                "source": source,
                "adjustment": "Yahoo adjusted close",
                "start": frame.index.min().date().isoformat(),
                "end": frame.index.max().date().isoformat(),
                "rows": len(frame),
            }
        )

    latest_common = min(raw[ticker].index.max() for ticker in CORE_PROD_TICKERS + ["SPY"])
    ny_now = pd.Timestamp.now(tz="America/New_York")
    excluded_unconfirmed_date = None
    if latest_common.date() >= ny_now.date() and ny_now.time() < pd.Timestamp("16:15").time():
        excluded_unconfirmed_date = ny_now.date().isoformat()
        latest_common = max(
            date
            for date in raw["SPY"].index
            if date.date() < ny_now.date()
            and all(date in raw[ticker].index for ticker in CORE_PROD_TICKERS)
        )

    prod = pd.concat(
        [raw[ticker]["close"].rename(ticker) for ticker in CORE_PROD_TICKERS],
        axis=1,
    ).ffill().dropna()
    for ticker in ("BTC-USD", "DBMF"):
        prod = prod.join(raw[ticker]["close"].rename(ticker), how="left")
    prod = prod.loc[:latest_common]

    prod_monthly = prod.resample("ME").last()
    if prod_monthly.index[-1].to_period("M") == prod.index[-1].to_period("M"):
        prod_monthly = prod_monthly.iloc[:-1]
    prod_sig_a = v77.make_abs_mom_signals(prod_monthly, v77.PROD_ABS_MOM_LB)
    prod_sig_b = v77.make_sma_signals(prod_monthly, v77.PROD_SMA_WINDOW, v77.PROD_SMA_BAND)
    if not v77.PROD_USE_TIMING:
        prod_sig_a = pd.DataFrame(1.0, index=prod_sig_a.index, columns=prod_sig_a.columns)
        prod_sig_b = prod_sig_a.copy()

    subc_return = v77._get_subc_daily_ret(prod, prod_sig_a, prod_sig_b=prod_sig_b)
    subc_nav_full = (1.0 + subc_return.dropna()).cumprod().rename("Strategy C")
    spy_close = raw["SPY"]["close"].loc[:latest_common].rename("SPY")
    nav = pd.concat([subc_nav_full, spy_close], axis=1, join="inner").dropna()
    window_start = nav.index[-1] - pd.DateOffset(years=1)
    nav = nav.loc[nav.index >= window_start]
    if len(nav) < 200:
        raise RuntimeError(f"One-year common window is too short: {len(nav)} rows")
    nav = nav.div(nav.iloc[0])

    metric_rows = []
    for name in nav.columns:
        metric_rows.append({"series": name, **metrics(nav[name])})
    metric_frame = pd.DataFrame(metric_rows)

    drawdown = nav.div(nav.cummax()).sub(1.0)
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, (ax_nav, ax_dd) = plt.subplots(
        2,
        1,
        figsize=(13.5, 8.5),
        sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1.15], "hspace": 0.08},
    )
    colors = {"Strategy C": "#146B8C", "SPY": "#D97706"}
    labels = {"Strategy C": "策略C（Legacy Sub-C，扣VolScale成本）", "SPY": "SPY（复权收盘）"}
    for name in nav.columns:
        ax_nav.plot(nav.index, nav[name], color=colors[name], linewidth=2.35, label=labels[name])
        ax_dd.plot(drawdown.index, drawdown[name] * 100, color=colors[name], linewidth=1.65, label=labels[name])
        ax_nav.annotate(
            f"{nav[name].iloc[-1]:.3f}",
            xy=(nav.index[-1], nav[name].iloc[-1]),
            xytext=(8, 0),
            textcoords="offset points",
            color=colors[name],
            va="center",
            fontsize=10,
            fontweight="bold",
        )
    ax_nav.axhline(1.0, color="#6B7280", linewidth=0.8, linestyle="--", alpha=0.7)
    ax_nav.set_title(
        f"策略C vs SPY：最近1年净值（起点=1）\n{nav.index[0].date()} — {nav.index[-1].date()}",
        fontsize=16,
        fontweight="bold",
        pad=14,
    )
    ax_nav.set_ylabel("归一化净值")
    ax_nav.grid(True, alpha=0.22)
    ax_nav.legend(loc="upper left", frameon=False)
    ax_dd.axhline(0.0, color="#6B7280", linewidth=0.8)
    ax_dd.fill_between(drawdown.index, drawdown["Strategy C"] * 100, 0, color=colors["Strategy C"], alpha=0.10)
    ax_dd.set_ylabel("回撤（%）")
    ax_dd.set_xlabel("日期")
    ax_dd.grid(True, alpha=0.22)
    ax_dd.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate(rotation=0)
    fig.text(
        0.01,
        0.012,
        "口径：Yahoo复权收盘；策略C使用V7.7官方daily engine，含15%目标波动率、15日窗口、0.5–1.5x、Δ0.10、融资利差与VolScale调仓成本；当日未确认美股K线已排除。",
        fontsize=8.5,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chart_path = OUT_DIR / "subc_vs_spy_1y_nav_drawdown.png"
    fig.savefig(chart_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    nav.index.name = "date"
    nav.to_csv(OUT_DIR / "subc_vs_spy_1y_nav.csv", encoding="utf-8-sig")
    metric_frame.to_csv(OUT_DIR / "subc_vs_spy_1y_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(sources).to_csv(OUT_DIR / "sources.csv", index=False, encoding="utf-8-sig")
    audit = {
        "created_at_beijing": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "strategy_engine": str(V77_PATH),
        "data_loader": str(V79_PATH),
        "data_source": "Yahoo adjusted close through repository fetch_yahoo",
        "confirmed_end": nav.index[-1].date().isoformat(),
        "excluded_unconfirmed_us_date": excluded_unconfirmed_date,
        "window": [nav.index[0].date().isoformat(), nav.index[-1].date().isoformat()],
        "strategy_params": {
            "PROD_USE_TIMING": bool(v77.PROD_USE_TIMING),
            "PROD_PORTFOLIO": v77.PROD_PORTFOLIO,
            "target_vol": v77.PROD_VS_TARGET_VOL,
            "vol_window": v77.PROD_VS_VOL_WINDOW,
            "min_lev": v77.PROD_VS_MIN_LEV,
            "max_lev": v77.PROD_VS_MAX_LEV,
            "scale_threshold": v77.PROD_VS_THRESHOLD,
            "financing_spread_bps": v77.PROD_VS_SPREAD_BPS,
            "volscale_rebalance_cost_bps": v77.PROD_VS_REBAL_COST_BPS,
        },
        "metrics": metric_rows,
        "caveat": "Legacy Sub-C is disabled in V7.8/V7.9 active weights; chart runs its retained V7.7 official daily engine standalone.",
    }
    (OUT_DIR / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(metric_frame.to_string(index=False))
    print(f"CHART {chart_path}")


if __name__ == "__main__":
    main()

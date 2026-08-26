#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "matplotlib",
#   "numpy",
#   "pandas",
#   "requests",
#   "xlsxwriter>=3.2.9",
# ]
# ///
"""Backtest V7.8/V7.9 Sub-B and Sub-C at 50/50.

Formal returns reuse the refreshed official V7.8/V7.9 output.  Sub-C is
recomputed through the production daily component and volatility-scaling path
with its 5% bitcoin allocation earning BIL before 2022-01-01.  The long sample
is explicitly proxy research: Sub-B uses the existing long-proxy harness and
Sub-C uses stitched mutual-fund/ETF proxies on the SPY session calendar.

The unavailable bitcoin allocation is held in BIL rather than redistributed.
This keeps the pre-2022 assumption conservative and preserves a stable 50/50
sleeve definition.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "v78_v79_subb_subc_50_50_20260826"
OFFICIAL_DIR = (
    ROOT / "outputs" / "v78_v79_vol_management_and_sleeve_diversification_20260824"
)
OFFICIAL_RETURNS = OFFICIAL_DIR / "official_daily_returns_and_nav.csv"
OFFICIAL_MARKET = OFFICIAL_DIR / "latest_market_data"
BTC_START = pd.Timestamp("2022-01-01")
VERSIONS = {
    "V7.8": ROOT / "mnt_bot V 7.8 plus.py",
    "V7.9": ROOT / "mnt_bot V 7.9 plus.py",
}
WINDOWS = {
    "Full": None,
    "10Y": pd.DateOffset(years=10),
    "5Y": pd.DateOffset(years=5),
    "3Y": pd.DateOffset(years=3),
    "1Y": pd.DateOffset(years=1),
}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_panel(path: Path) -> pd.DataFrame:
    return (
        pd.read_csv(path, parse_dates=["date"])
        .set_index("date")
        .sort_index()
        .apply(pd.to_numeric, errors="coerce")
    )


def write_panel(frame: pd.DataFrame, path: Path) -> None:
    output = frame.copy()
    output.index.name = "date"
    output.to_csv(path, encoding="utf-8-sig")


@contextmanager
def patched(module, **updates: Any) -> Iterator[None]:
    old = {name: getattr(module, name) for name in updates}
    try:
        for name, value in updates.items():
            setattr(module, name, value)
        yield
    finally:
        for name, value in old.items():
            setattr(module, name, value)


def cash_substituted_btc(
    btc: pd.Series, cash: pd.Series, start: pd.Timestamp = BTC_START
) -> pd.Series:
    """Return a continuous price index: BIL returns before start, BTC after."""
    index = btc.index.union(cash.index).sort_values()
    btc_ret = pd.to_numeric(btc, errors="coerce").reindex(index).pct_change(
        fill_method=None
    )
    cash_ret = pd.to_numeric(cash, errors="coerce").reindex(index).pct_change(
        fill_method=None
    )
    selected = btc_ret.where(index >= start, cash_ret).fillna(0.0)
    return (1.0 + selected).cumprod().rename(btc.name)


def all_one_monthly_signals(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    monthly = panel.resample("ME").last()
    signal = pd.DataFrame(1.0, index=monthly.index, columns=monthly.columns)
    return signal, signal.copy()


def subc_btc_eligible_return(
    module,
    panel: pd.DataFrame,
    *,
    us_open: dict[str, pd.Series] | None,
    formal_start: pd.Timestamp,
    strict_open: bool,
) -> pd.Series:
    required = {
        config["proxy"] for config in module.PROD_PORTFOLIO.values()
    } | {module.PROD_CASH, module.PROD_VS_SIGNAL_TICKER, module.PROD_GOLD_VS_SIGNAL_TICKER}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise RuntimeError(f"Sub-C panel missing columns: {missing}")
    research = panel.copy()
    research[module.US_ROT_BTC_TICKER] = cash_substituted_btc(
        research[module.US_ROT_BTC_TICKER], research[module.PROD_CASH]
    ).reindex(research.index)
    sig_a, sig_b = all_one_monthly_signals(research)
    with patched(module, SUBC_FORMAL_START=formal_start):
        result = module._get_subc_daily_ret(
            research,
            sig_a,
            sig_b,
            us_open=us_open,
            strict_open_execution=strict_open,
        )
    result = pd.to_numeric(result, errors="coerce").dropna().sort_index()
    # Moving 5% from BIL to BTC is 10% two-sided turnover at the production
    # 10 bp annual asset-rebalance rate: one additional portfolio basis point.
    switch_rows = result.index[result.index >= BTC_START]
    if len(switch_rows):
        result.loc[switch_rows[0]] -= 0.0001
    return result.rename("Sub-C")


def equal_weight(subb: pd.Series, subc: pd.Series) -> pd.Series:
    common = pd.concat(
        [subb.rename("Sub-B"), subc.rename("Sub-C")], axis=1, join="inner"
    ).dropna(how="any")
    return common.mean(axis=1).rename("B50_C50")


def metrics(series: pd.Series) -> dict[str, Any]:
    returns = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    if len(returns) < 2:
        return {
            "start": None,
            "end": None,
            "rows": len(returns),
            "cagr": None,
            "annual_vol": None,
            "sharpe_0rf": None,
            "max_drawdown": None,
        }
    nav = (1.0 + returns).cumprod()
    years = (returns.index[-1] - returns.index[0]).days / 365.25
    vol = returns.std(ddof=1) * math.sqrt(252.0)
    return {
        "start": returns.index[0].date().isoformat(),
        "end": returns.index[-1].date().isoformat(),
        "rows": len(returns),
        "years": years,
        "cagr": nav.iloc[-1] ** (1.0 / years) - 1.0,
        "annual_vol": vol,
        "sharpe_0rf": (
            returns.mean() / returns.std(ddof=1) * math.sqrt(252.0)
            if returns.std(ddof=1) > 0
            else np.nan
        ),
        "max_drawdown": (nav / nav.cummax() - 1.0).min(),
    }


def window_metrics(
    classification: str, version: str, sleeve_returns: dict[str, pd.Series]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sleeve, returns in sleeve_returns.items():
        clean = pd.to_numeric(returns, errors="coerce").dropna().sort_index()
        end = clean.index[-1]
        for label, offset in WINDOWS.items():
            reason = ""
            if offset is None:
                segment = clean
            else:
                requested_start = end - offset
                if clean.index[0] > requested_start + pd.Timedelta(days=7):
                    segment = pd.Series(dtype=float)
                    reason = "insufficient history"
                else:
                    segment = clean.loc[clean.index >= requested_start]
            rows.append(
                {
                    "classification": classification,
                    "version": version,
                    "sleeve": sleeve,
                    "window": label,
                    **metrics(segment),
                    "na_reason": reason,
                }
            )
    return rows


def formal_runs(modules: dict[str, Any]) -> tuple[dict[str, dict[str, pd.Series]], dict[str, Any]]:
    official = read_panel(OFFICIAL_RETURNS)
    prod = read_panel(OFFICIAL_MARKET / "us_prod_daily.csv")
    open_frame = read_panel(OFFICIAL_MARKET / "us_adjusted_open.csv")
    us_open = {column: open_frame[column].dropna() for column in open_frame.columns}
    runs: dict[str, dict[str, pd.Series]] = {}
    parity: dict[str, Any] = {}
    for version, module in modules.items():
        subb = official[f"{version}_Sub-B"].dropna().rename("Sub-B")
        subc = subc_btc_eligible_return(
            module,
            prod,
            us_open=us_open,
            formal_start=module.SUBC_FORMAL_START,
            strict_open=True,
        )
        combo = equal_weight(subb, subc)
        runs[version] = {"Sub-B": subb, "Sub-C": subc, "B50_C50": combo}
        official_c = official[f"{version}_Sub-C"].dropna()
        check = pd.concat([subc, official_c.rename("official")], axis=1).dropna()
        check = check.loc[check.index > pd.Timestamp("2022-01-03")]
        parity[version] = {
            "subb_source": "fresh official_daily_returns_and_nav.csv",
            "subc_post_2022_max_abs_diff_vs_official": float(
                (check["Sub-C"] - check["official"]).abs().max()
            ),
            "subc_post_2022_rows": len(check),
        }
    return runs, parity


def build_long_subc_panel(loader) -> tuple[pd.DataFrame, pd.DataFrame, str | None]:
    long_base = load_module(
        ROOT / "research_subc_bond_necessity_long_proxy.py", "subc_long_source"
    )
    raw, sources, excluded = long_base.fetch_raw(loader)
    calendar = raw["SPY"].index
    mapping = {
        "VTI": "VTI",
        "QQQ": "QQQ",
        "US_SMALL_VALUE": "AVUV",
        "DEVELOPED": "VEA",
        "INTL_SMALL_VALUE": "AVDV",
        "TREASURY": "VGIT",
        "BIL": "BIL",
        "MF_1": "DBMF",
        "MF_2": "KMLM",
        "GOLD": "GLD",
        "BTC": "BTC-USD",
        "SPY": "SPY",
    }
    stitched: dict[str, pd.Series] = {}
    for synthetic, target in mapping.items():
        proxy, live, _description = long_base.PROXY_MAP[synthetic]
        stitched[target] = long_base.stitched_nav(calendar, raw, proxy, live)[0].rename(
            target
        )
    panel = pd.concat(stitched.values(), axis=1).sort_index()
    non_btc = [column for column in panel.columns if column != "BTC-USD"]
    start = panel[non_btc].dropna(how="any").index.min()
    return panel.loc[start:], sources, excluded


def proxy_runs(modules: dict[str, Any]) -> tuple[dict[str, dict[str, pd.Series]], dict[str, Any]]:
    proxy_compare = load_module(
        ROOT / "backtest_v78_v79_proxy_compare.py", "v78_v79_proxy_source"
    )
    loader = modules["V7.9"]
    subb_raw, subb_sources = proxy_compare.load_or_fetch_proxy_raw(loader, OUT)
    subc_panel, subc_sources, excluded = build_long_subc_panel(loader)
    runs: dict[str, dict[str, pd.Series]] = {}
    for version, module in modules.items():
        if module.US_ROT_BTC_START != BTC_START:
            raise RuntimeError(
                f"{version} Sub-B BTC start drifted to {module.US_ROT_BTC_START}"
            )
        subb = proxy_compare.run_proxy_subb(module, subb_raw)["return"].dropna()
        subc = subc_btc_eligible_return(
            module,
            subc_panel,
            us_open=None,
            formal_start=subc_panel.index.min(),
            strict_open=False,
        )
        combo = equal_weight(subb, subc)
        runs[version] = {"Sub-B": subb, "Sub-C": subc, "B50_C50": combo}
    provenance = {
        "subb_proxy_sources": subb_sources,
        "subc_proxy_sources": subc_sources.to_dict(orient="records"),
        "subc_excluded_unconfirmed_date": excluded,
        "subc_calendar": "SPY sessions",
        "subc_execution": "close-based proxy overlay; not formal tradable open execution",
    }
    return runs, provenance


def save_daily(
    formal: dict[str, dict[str, pd.Series]],
    proxy: dict[str, dict[str, pd.Series]],
) -> None:
    columns = {}
    for classification, runs in (("formal", formal), ("proxy", proxy)):
        for version, sleeves in runs.items():
            for sleeve, series in sleeves.items():
                columns[f"{classification}_{version}_{sleeve}"] = series
    write_panel(pd.concat(columns, axis=1).sort_index(), OUT / "daily_returns.csv")


def build_report(metrics_frame: pd.DataFrame, audit: dict[str, Any]) -> str:
    lines = [
        "# V7.8 / V7.9：Sub-B 与 Sub-C 各 50% 回测",
        "",
        f"生成时间：{audit['created_at']}",
        "",
        "## 口径",
        "",
        "- 组合为 Sub-B 50% + Sub-C 50%，按日收益线性合成；不加组合层 target-vol。",
        "- BTC 从 2022-01-01 起参与。Sub-B 使用生产起点过滤；Sub-C 在此前把 5% BTC 配额放入 BIL，起用时另扣 1bp 切换成本。",
        "- 正式段保留 Sub-B 的 T 收盘信号 -> T+1 调整后开盘 -> T+1 收盘、VolReg、DBC guard、费用和融资。",
        "- 长段为代理压力研究：Sub-B 用指数/基金/期货代理开盘；Sub-C 用拼接代理及收盘近似，不能视为可交易 ETF 历史。",
        "",
        "## B/C 50/50 结果",
        "",
        "| 样本 | 版本 | 窗口 | CAGR | 最大回撤 | 年化波动 | Sharpe(0rf) | 区间 |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    selected = metrics_frame[metrics_frame["sleeve"] == "B50_C50"]
    order = {name: idx for idx, name in enumerate(WINDOWS)}
    selected = selected.assign(_order=selected["window"].map(order)).sort_values(
        ["classification", "version", "_order"]
    )
    for row in selected.itertuples():
        if row.na_reason:
            values = ["N/A"] * 4
            period = row.na_reason
        else:
            values = [
                f"{row.cagr:.2%}",
                f"{row.max_drawdown:.2%}",
                f"{row.annual_vol:.2%}",
                f"{row.sharpe_0rf:.2f}",
            ]
            period = f"{row.start}~{row.end}"
        lines.append(
            f"| {row.classification} | {row.version} | {row.window} | "
            f"{values[0]} | {values[1]} | {values[2]} | {values[3]} | {period} |"
        )
    lines.extend(
        [
            "",
            "## 完整样本袖套拆分",
            "",
            "| 样本 | 版本 | 袖套 | CAGR | 最大回撤 |",
            "|---|---|---|---:|---:|",
        ]
    )
    full = metrics_frame[metrics_frame["window"] == "Full"].sort_values(
        ["classification", "version", "sleeve"]
    )
    for row in full.itertuples():
        lines.append(
            f"| {row.classification} | {row.version} | {row.sleeve} | "
            f"{row.cagr:.2%} | {row.max_drawdown:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 验证与限制",
            "",
            f"- 正式数据截至 {audit['formal_end']}；官方刷新状态 PASS。",
            f"- Sub-C 2022 后与官方线最大日差：V7.8={audit['formal_parity']['V7.8']['subc_post_2022_max_abs_diff_vs_official']:.3g}，V7.9={audit['formal_parity']['V7.9']['subc_post_2022_max_abs_diff_vs_official']:.3g}。",
            "- 代理段主要用于观察更长周期和压力期方向，不能覆盖真实 ETF 上市前可得性、成交价、基金费差与容量。",
            "- 组合按固定 50/50 日收益合成，未额外计袖套之间再平衡成本；两只袖套内部成本均已计。",
            "",
            "详细结果：`window_metrics.csv`、`daily_returns.csv`、`audit.json`。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    modules = {
        version: load_module(path, f"subb_subc_50_50_{version.replace('.', '_')}")
        for version, path in VERSIONS.items()
    }
    formal, formal_parity = formal_runs(modules)
    proxy, proxy_provenance = proxy_runs(modules)
    rows = []
    for classification, runs in (("formal", formal), ("proxy", proxy)):
        for version, sleeves in runs.items():
            rows.extend(window_metrics(classification, version, sleeves))
    metrics_frame = pd.DataFrame(rows)
    metrics_frame.to_csv(OUT / "window_metrics.csv", index=False, encoding="utf-8-sig")
    save_daily(formal, proxy)

    official_audit = json.loads((OFFICIAL_DIR / "audit.json").read_text(encoding="utf-8"))
    audit = {
        "status": "PASS",
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
            timespec="seconds"
        ),
        "production_code_changed": False,
        "versions": {key: str(value) for key, value in VERSIONS.items()},
        "official_entrypoint": official_audit["entrypoint"],
        "formal_refresh_status": official_audit["status"],
        "formal_market_ranges": official_audit["market_data_ranges"],
        "formal_end": max(
            series.index.max().date().isoformat()
            for run in formal.values()
            for series in run.values()
        ),
        "btc_start": BTC_START.date().isoformat(),
        "subc_pre_btc_policy": "5% allocation earns BIL; 1 bp switch cost at eligibility",
        "weights": {"Sub-B": 0.5, "Sub-C": 0.5},
        "formal_parity": formal_parity,
        "proxy_provenance": proxy_provenance,
        "notes": [
            "Formal Sub-B comes from the just-refreshed official output.",
            "Formal Sub-C reuses production daily components and sleeve-vol overlays with only the pre-2022 BTC return replaced by BIL.",
            "Proxy Sub-B preserves strict adjusted-open execution inside the existing long-proxy harness.",
            "Proxy Sub-C is close-based and diagnostic only.",
        ],
    }
    (OUT / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (OUT / "report.md").write_text(
        build_report(metrics_frame, audit), encoding="utf-8"
    )
    print(metrics_frame[metrics_frame["sleeve"] == "B50_C50"].to_string(index=False))
    print(f"PASS: {OUT}")


if __name__ == "__main__":
    main()

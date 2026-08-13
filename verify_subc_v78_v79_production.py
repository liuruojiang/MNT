"""Real-data parity check for the promoted V7.8/V7.9 Strategy-C engine.

The script downloads Yahoo adjusted closes through the repository loader,
runs both production helpers, and compares them with the already-audited
research component/scaling implementation.  It never mutates strategy files.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import research_subc_bond_sleeve_backtest as base
import research_subc_relative_vol_param_scan as prior
import research_subc_relative_vol_width_scan as width


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "subc_v78_v79_production_verification_20260812"
PATHS = {
    "V7.8": ROOT / "mnt_bot V 7.8 plus.py",
    "V7.9": ROOT / "mnt_bot V 7.9 plus.py",
}
PROXY_COLUMNS = [
    "VTI", "QQQ", "AVUV", "VEA", "AVDV", "VGIT", "DBMF", "KMLM",
    "GLD", "BTC-USD", "BIL", "SPY",
]


def production_prices(raw: dict[str, pd.Series]) -> pd.DataFrame:
    calendar = raw["SPY"].index
    return pd.concat(
        {ticker: raw[ticker].reindex(calendar) for ticker in PROXY_COLUMNS},
        axis=1,
    ).sort_index()


def hold_signals(prices: pd.DataFrame) -> pd.DataFrame:
    monthly = prices.resample("ME").last()
    return pd.DataFrame(1.0, index=monthly.index, columns=prices.columns)


def max_abs_delta(left: pd.Series, right: pd.Series) -> float:
    aligned = pd.concat([left.rename("left"), right.rename("right")], axis=1).dropna()
    if aligned.empty:
        return float("nan")
    return float((aligned["left"] - aligned["right"]).abs().max())


def main() -> None:
    modules = {
        name: base.load_module(path, f"subc_prod_verify_{name.replace('.', '_')}")
        for name, path in PATHS.items()
    }
    raw, sources, excluded_date = width.scope_base.long_base.fetch_raw(modules["V7.9"])
    prices = production_prices(raw)
    signals = hold_signals(prices)

    snapshots = {
        name: module._compute_subc_production_snapshot(prices, signals, signals)
        for name, module in modules.items()
    }

    calendar = raw["SPY"].index
    formal_prices = width.scope_base.build_formal_prices(raw, calendar)
    formal_components = width.independent.simulate_asset_components(
        formal_prices, width.AFTER_WEIGHTS
    )
    formal_signals = pd.concat(
        {
            "SPY": raw["SPY"].reindex(calendar),
            "GOLD": raw["GLD"].reindex(calendar),
            "BTC": raw["BTC-USD"].reindex(calendar),
        },
        axis=1,
    )
    spy_scale = prior.absolute_scale(
        formal_signals["SPY"].pct_change(fill_method=None), 0.15, modules["V7.9"]
    )
    gold_scale = prior.relative_scale(
        formal_signals["GOLD"].pct_change(fill_method=None), 30, 252, modules["V7.9"]
    )
    research_return, research_cost, _ = prior.apply_sleeve_scales(
        formal_components,
        formal_prices,
        {"Equities (SPY)": spy_scale, "Gold": gold_scale},
        modules["V7.9"],
    )
    research_return = research_return.loc[
        research_return.index >= width.FORMAL_START
    ]
    research_cost = research_cost.reindex(research_return.index)

    comparison = {
        "V7.8_vs_V7.9_return_max_abs": max_abs_delta(
            snapshots["V7.8"]["scaled_return"], snapshots["V7.9"]["scaled_return"]
        ),
        "V7.8_vs_V7.9_equity_scale_max_abs": max_abs_delta(
            snapshots["V7.8"]["equity_scale"], snapshots["V7.9"]["equity_scale"]
        ),
        "V7.8_vs_V7.9_gold_scale_max_abs": max_abs_delta(
            snapshots["V7.8"]["gold_scale"], snapshots["V7.9"]["gold_scale"]
        ),
        "V7.9_vs_research_return_max_abs": max_abs_delta(
            snapshots["V7.9"]["scaled_return"], research_return
        ),
        "V7.9_vs_research_cost_max_abs": max_abs_delta(
            snapshots["V7.9"]["costs"], research_cost
        ),
    }
    for key, value in comparison.items():
        if not np.isfinite(value) or value > 5e-13:
            raise RuntimeError(f"Parity failed: {key}={value}")

    returns = pd.concat(
        {
            "V7.8 production": snapshots["V7.8"]["scaled_return"],
            "V7.9 production": snapshots["V7.9"]["scaled_return"],
            "audited research": research_return,
        },
        axis=1,
    ).dropna(how="any")
    metrics = base.window_metrics(returns)

    OUT.mkdir(parents=True, exist_ok=True)
    returns.to_csv(OUT / "daily_returns.csv", index_label="date")
    metrics.to_csv(OUT / "window_metrics.csv", index=False)
    sources.to_csv(OUT / "data_sources.csv", index=False)
    with (OUT / "parity.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "status": "PASS",
                "formal_start": width.FORMAL_START.date().isoformat(),
                "formal_end": returns.index.max().date().isoformat(),
                "excluded_incomplete_session": excluded_date,
                "rows": len(returns),
                "comparison": comparison,
                "production_rule": {
                    "equities": "SPY absolute target vol 15%, window 15",
                    "gold": "GLD relative vol long/short 252/30",
                    "bitcoin": "1.0x, no scaling",
                    "lag": 1,
                    "deadband": 0.10,
                    "scale_bounds": [0.5, 1.5],
                },
            },
            handle,
            indent=2,
            ensure_ascii=False,
        )
    print(json.dumps(comparison, indent=2))
    print(metrics.to_string(index=False))
    print(f"PASS: {OUT}")


if __name__ == "__main__":
    main()

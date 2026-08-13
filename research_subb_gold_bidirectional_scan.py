#!/usr/bin/env python3
"""Corrected Sub-B scope study: gold may scale bidirectionally up to 1.5x."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

import research_subb_volatility_scope_scan as core


ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / "quant_param_scan_runs" / (
    "20260812_a_share_us_momentum_combo_v7_8_v7_9_sub_b_"
    "sub_b_gold_bidirectional_volatility_sizing_spy_stock_gold_relative_vol_floor_cap"
)
GROUP = frozenset({"gold"})


def candidates() -> list[core.Candidate]:
    return [
        core.Candidate(
            "production_current", "current",
            description="production four-leg self-vol scaling; QQQ/GLD can scale above 1",
        ),
        core.Candidate(
            "spy_perleg_gold_1x", "spy",
            description="each leg keeps its target/max for SPY-managed stocks; gold fixed at 1x",
        ),
        core.Candidate(
            "spy_perleg_gold_down_s30_l252_f50_c100", "spy", "own_relative", GROUP,
            short=30, long=252, floor=0.50, ceiling=1.00,
            description="previous down-only gold rule",
        ),
        core.Candidate(
            "spy_perleg_gold_bidir_s30_l252_f50_c125", "spy", "own_relative", GROUP,
            short=30, long=252, floor=0.50, ceiling=1.25,
            description="cap sensitivity below production 1.5x",
        ),
        core.Candidate(
            "spy_perleg_gold_bidir_s30_l252_f50_c150", "spy", "own_relative", GROUP,
            short=30, long=252, floor=0.50, ceiling=1.50,
            description="corrected central rule: gold own relative vol, 0.5x to 1.5x",
        ),
        core.Candidate(
            "spy_perleg_gold_bidir_s20_l252_f50_c150", "spy", "own_relative", GROUP,
            short=20, long=252, floor=0.50, ceiling=1.50,
            description="short-window lower neighbor",
        ),
        core.Candidate(
            "spy_perleg_gold_bidir_s40_l252_f50_c150", "spy", "own_relative", GROUP,
            short=40, long=252, floor=0.50, ceiling=1.50,
            description="short-window upper neighbor",
        ),
        core.Candidate(
            "spy_perleg_gold_bidir_s30_l126_f50_c150", "spy", "own_relative", GROUP,
            short=30, long=126, floor=0.50, ceiling=1.50,
            description="long-window lower neighbor",
        ),
        core.Candidate(
            "spy30_gold_1x", "spy", stock_target=0.30,
            description="common 30% SPY stock target; gold fixed at 1x",
        ),
        core.Candidate(
            "spy30_gold_down_s30_l252_f50_c100", "spy", "own_relative", GROUP,
            short=30, long=252, floor=0.50, ceiling=1.00, stock_target=0.30,
            description="common 30% SPY stock target; gold down-only",
        ),
        core.Candidate(
            "spy30_gold_bidir_s30_l252_f50_c150", "spy", "own_relative", GROUP,
            short=30, long=252, floor=0.50, ceiling=1.50, stock_target=0.30,
            description="common 30% SPY stock target; gold 0.5x to 1.5x",
        ),
    ]


def production_bundle(module, close, opens):
    return core.run_production_bundle(module, close, opens)


def candidate_bundle(module, close, opens, cfg):
    return core.run_candidate_bundle(module, close, opens, cfg)


def component_gold_scale(bundle) -> pd.Series:
    values = []
    for name in ("official", "ema", "bias", "logvol"):
        frame = bundle[name]
        signal = frame.loc[frame["is_signal"].astype(bool)]
        if "candidate_scale_GLD" in signal:
            values.append(pd.to_numeric(signal["candidate_scale_GLD"], errors="coerce"))
    if not values:
        return pd.Series(dtype=float)
    return pd.concat(values).dropna()


def final_exposure_diagnostics(bundle) -> dict[str, float]:
    final = bundle["final"]
    gold = pd.to_numeric(final.get("w_GLD", pd.Series(0.0, index=final.index)), errors="coerce").fillna(0.0)
    risky_cols = [c for c in final.columns if c.startswith("w_") and c not in ("w_BIL", "w_CASH")]
    gross = final[risky_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1)
    return {
        "avg_gold_weight": float(gold.mean()),
        "max_gold_weight": float(gold.max()),
        "avg_risky_gross": float(gross.mean()),
        "max_risky_gross": float(gross.max()),
    }


def metrics_for_bundle(version: str, cfg: core.Candidate, bundle):
    final = bundle["final"]
    end = final.index.max()
    scale = component_gold_scale(bundle)
    diag = final_exposure_diagnostics(bundle)
    rows = []
    for window, years in core.WINDOWS.items():
        start = None if years is None else end - pd.DateOffset(years=years)
        metrics = core.metric_row(final["return"], start)
        costs = core.total_embedded_cost(bundle, final.index)
        if start is not None:
            costs = costs.loc[costs.index >= start]
        rows.append({
            "version": version,
            "candidate": cfg.name,
            "window": window,
            "kind": "baseline" if cfg.name == "production_current" else "candidate",
            "stock_target_mode": "current" if cfg.stock_mode == "current" else (
                "per_leg" if cfg.stock_target is None else f"common_{cfg.stock_target:.0%}"
            ),
            "gold_mode": "production" if cfg.stock_mode == "current" else (
                "fixed_1x" if cfg.nonstock_mode == "fixed" else "own_relative"
            ),
            "gold_short": cfg.short,
            "gold_long": cfg.long,
            "gold_floor": cfg.floor,
            "gold_ceiling": cfg.ceiling,
            **metrics,
            "annualized_embedded_cost": float(costs.mean() * 252) if len(costs) else np.nan,
            "gold_scale_mean": float(scale.mean()) if len(scale) else np.nan,
            "gold_scale_pct_lt1": float((scale < 1 - 1e-12).mean()) if len(scale) else np.nan,
            "gold_scale_pct_gt1": float((scale > 1 + 1e-12).mean()) if len(scale) else np.nan,
            **diag,
        })
    return rows


def write_standard_csvs(long_df: pd.DataFrame):
    segment_map = {"full": "full", "10Y": "last_10y", "5Y": "last_5y", "3Y": "last_3y", "1Y": "last_1y"}
    scan = long_df.copy()
    scan["segment"] = scan["window"].map(segment_map)
    scan = scan.rename(columns={"cagr": "ann_return", "sharpe": "sharpe_repo"})
    scan.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    identity = [
        "version", "candidate", "kind", "stock_target_mode", "gold_mode",
        "gold_short", "gold_long", "gold_floor", "gold_ceiling",
    ]
    records = []
    for keys, group in long_df.groupby(identity, dropna=False, sort=False):
        row = dict(zip(identity, keys))
        for item in group.itertuples(index=False):
            suffix = segment_map[item.window]
            row[f"ann_return_{suffix}"] = item.cagr
            row[f"ann_vol_{suffix}"] = item.ann_vol
            row[f"sharpe_repo_{suffix}"] = item.sharpe
            row[f"max_dd_{suffix}"] = item.max_dd
            row[f"annualized_embedded_cost_{suffix}"] = item.annualized_embedded_cost
            if item.window == "full":
                for col in (
                    "gold_scale_mean", "gold_scale_pct_lt1", "gold_scale_pct_gt1",
                    "avg_gold_weight", "max_gold_weight", "avg_risky_gross", "max_risky_gross",
                ):
                    row[col] = getattr(item, col)
        records.append(row)
    pd.DataFrame(records).to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")


def git_status() -> str:
    return subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=True,
    ).stdout.strip()


def write_record(long_df: pd.DataFrame, parity: dict, data: dict, grid: list[core.Candidate]):
    full = long_df[long_df.window == "full"].copy()
    lines = [
        "# V7.8/V7.9 Sub-B gold bidirectional volatility sizing",
        "",
        "## Run Metadata",
        "",
        f"- Run id: `{RUN_DIR.name}`",
        "- Run date/timezone: 2026-08-12, Asia/Shanghai",
        f"- Repo: `{ROOT}`",
        "- Version/subsystem: V7.8/V7.9 Sub-B four-leg blend, gold sizing",
        "- Scan type: candidate_bundle",
        "- Source-change rule: research_only_no_source_change",
        "",
        "## Research Question",
        "",
        "Correct the prior down-only study by allowing GLD to scale above 1x. Stocks are managed by SPY; GLD uses lagged own long-vol/short-vol and is clipped to the candidate floor/cap; all other non-stocks remain at 1x.",
        "",
        "Promotion requires the corrected rule to beat production or create a stable nearby risk/return platform across full/10Y/5Y/3Y/1Y. Any production parity failure forces rerun.",
        "",
        "## Implementation Anchor",
        "",
        "- Official chain: official + EMA -> V77 blend -> Bias/LogVol blend -> SPY VolReg -> DBC profit guard.",
        "- Production `_us_model_b`: scale>1 can lever QQQM and GLDM; the earlier <=1 gold study was incomplete.",
        "- Corrected gold rule: `clip(gold_long_RV / gold_short_RV, floor, ceiling)`, shifted one trading day.",
        "- Execution and costs: T close signal -> T+1 adjusted open -> T+1 close; production 10 bp turnover costs at every retained layer.",
        "",
        "## Data Snapshot",
        "",
        f"- Yahoo vendor-adjusted OHLC: {data['raw_start']} to {data['raw_end']}, {data['raw_rows']} rows.",
        f"- Common metric window after warm-up: {data['metric_start']} to {data['metric_end']}, {data['metric_rows']} rows.",
        "- EMXC uses the production EEM/EMXC splice; BTC stays NaN before availability and is eligible from 2022-01-01.",
        "- US trading calendar; signal at US close and fill at next US adjusted open.",
        "",
        "## Runtime Override Plan",
        "",
        "- Research harness imports the production modules and reuses their loaders, selection helpers, blend and overlay functions.",
        "- Default production candidate is rerun in the same batch.",
        f"- Parity: V7.8 max daily return diff {parity['V7.8']['max_abs_return_diff']:.3e}; V7.9 {parity['V7.9']['max_abs_return_diff']:.3e}.",
        "",
        "## Full-Sample Results",
        "",
        "| Version | Candidate | CAGR | Sharpe | MDD | Gold scale <1 | Gold scale >1 | Avg GLD weight |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in full.itertuples(index=False):
        lines.append(
            f"| {row.version} | {row.candidate} | {row.cagr:.2%} | {row.sharpe:.3f} | "
            f"{row.max_dd:.2%} | {row.gold_scale_pct_lt1:.1%} | {row.gold_scale_pct_gt1:.1%} | "
            f"{row.avg_gold_weight:.2%} |"
        )
    lines += [
        "",
        "## Window Results",
        "",
        "Complete full/10Y/5Y/3Y/1Y CAGR, volatility, Sharpe and MDD are in `scan_summary.csv` and `window_metrics.csv`.",
        "",
        "## Commands",
        "",
        "Exact commands are recorded in `command_log.txt`.",
        "",
        "## Output Files",
        "",
        "- `record.md`, `scan_summary.csv`, `window_metrics.csv`, `scan_meta.json`, `command_log.txt`.",
        "",
        "## Stability Classification",
        "",
        "- Pending final metrics audit.",
        "",
        "## Decision",
        "",
        "- Pending final metrics audit; no production source change.",
        "",
        "## User-Facing Summary",
        "",
        "The previous study was incomplete because it capped gold at 1x. This run corrects gold to a maximum of 1.5x and compares it with both down-only gold and production.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    modules = {label: core.load_module(label, path) for label, path in core.VERSION_FILES.items()}
    raw, sources = core.fetch_shared_raw(modules)
    closes, opens = {}, {}
    for version, module in modules.items():
        closes[version], opens[version] = core.build_version_data(module, raw)
        gate, source = module._v78_spy_volume_gate(closes[version].index)
        frozen = gate.copy()
        module._v78_spy_volume_gate = lambda index, g=frozen, s=source: (g.reindex(index).fillna(False), s)

    grid = candidates()
    rows, parity = [], {}
    for version, module in modules.items():
        print(f"[{version}] production_current", flush=True)
        production = production_bundle(module, closes[version], opens[version])
        rebuilt = candidate_bundle(module, closes[version], opens[version], grid[0])
        common = production["final"].index.intersection(rebuilt["final"].index)
        diff = (production["final"].loc[common, "return"] - rebuilt["final"].loc[common, "return"]).abs().max()
        parity[version] = {"max_abs_return_diff": float(diff), "rows": len(common), "pass": bool(diff <= 1e-12)}
        if not parity[version]["pass"]:
            raise AssertionError(f"{version} production parity failed: {diff}")
        rows.extend(metrics_for_bundle(version, grid[0], production))
        for cfg in grid[1:]:
            print(f"[{version}] {cfg.name}", flush=True)
            rows.extend(metrics_for_bundle(version, cfg, candidate_bundle(module, closes[version], opens[version], cfg)))

    long_df = pd.DataFrame(rows)
    write_standard_csvs(long_df)
    prod = long_df[(long_df.candidate == "production_current") & (long_df.window == "full")].iloc[0]
    data = {
        "raw_start": closes["V7.8"].index.min().date().isoformat(),
        "raw_end": closes["V7.8"].index.max().date().isoformat(),
        "raw_rows": len(closes["V7.8"]),
        "metric_start": prod.start,
        "metric_end": prod.end,
        "metric_rows": int(prod.rows),
    }
    write_record(long_df, parity, data, grid)
    meta_path = RUN_DIR / "scan_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update({
        "phase": "executed",
        "scan_type": "candidate_bundle",
        "baseline": {"candidate": "production_current", "source": "same-run formal rerun"},
        "candidate_grid": [asdict(cfg) | {"groups": sorted(cfg.groups)} for cfg in grid],
        "data_snapshot": data | {
            "provider": "Yahoo vendor-adjusted OHLC through production fetch_yahoo",
            "source_labels": sources,
            "adjustment": "vendor-adjusted close and adjusted open",
            "execution": "T close signal -> T+1 adjusted open -> T+1 close",
        },
        "cost_model": {
            "commission": 0.001,
            "slippage": "no extra slippage beyond production commission",
            "financing": "none, matching production Sub-B",
            "layers": "component + V77 blend + SPY VolReg + DBC profit guard",
        },
        "parity_check": parity,
        "source_change_rule": "research_only_no_source_change",
        "warnings": ["repo was dirty before run; pre-existing changes preserved"],
        "decision": "pending_audit",
        "stability_label": "pending_audit",
        "git_status_after": git_status(),
    })
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(RUN_DIR)


if __name__ == "__main__":
    main()

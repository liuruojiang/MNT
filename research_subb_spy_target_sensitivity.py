#!/usr/bin/env python3
"""Supplement: common SPY stock-target sensitivity for the Sub-B scope scan."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import research_subb_volatility_scope_scan as core


TARGETS = (0.15, 0.20, 0.25, 0.30)


def main():
    modules = {label: core.load_module(label, path) for label, path in core.VERSION_FILES.items()}
    raw, _sources = core.fetch_shared_raw(modules)
    closes, opens = {}, {}
    for version, module in modules.items():
        closes[version], opens[version] = core.build_version_data(module, raw)
        gate, source = module._v78_spy_volume_gate(closes[version].index)
        frozen = gate.copy()
        module._v78_spy_volume_gate = lambda index, g=frozen, s=source: (g.reindex(index).fillna(False), s)

    rows = []
    for version, module in modules.items():
        for target in TARGETS:
            cfg = core.Candidate(
                name=f"spy_stock_target_{int(target * 100)}_nonstock_1x",
                stock_mode="spy",
                stock_target=target,
                description=f"common SPY absolute target {target:.0%}; non-stocks fixed at 1x",
            )
            print(f"[{version}] {cfg.name}", flush=True)
            bundle = core.run_candidate_bundle(module, closes[version], opens[version], cfg)
            final = bundle["final"]
            end = final.index.max()
            for window, years in core.WINDOWS.items():
                start = None if years is None else end - pd.DateOffset(years=years)
                metrics = core.metric_row(final["return"], start)
                cost = core.total_embedded_cost(bundle, final.index)
                if start is not None:
                    cost = cost.loc[cost.index >= start]
                rows.append({
                    "version": version,
                    "candidate": cfg.name,
                    "window": window,
                    "stock_target": target,
                    **metrics,
                    "annualized_embedded_cost": cost.mean() * 252 if len(cost) else float("nan"),
                })
    out = pd.DataFrame(rows)
    path = core.RUN_DIR / "spy_target_sensitivity.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig")
    meta_path = core.RUN_DIR / "scan_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["spy_stock_target_sensitivity"] = {
        "targets": list(TARGETS),
        "nonstock_scope": "fixed_1x",
        "output": path.name,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()

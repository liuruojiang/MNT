"""Layer 10 final ridge for long HS300 / short ZZ500 amount filter.

Layer 9 promoted the ZZ500 high-amount defense family. This final layer scans
only that family around the accepted ridge and applies an explicit recent-window
constraint before selecting a fixed research script candidate.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import scan_adk_hs300_zz500_spread_layer9_amount as l9


RUN_DIR = l9.base.ROOT / "quant_param_scan_runs" / "20260612_adk_hs300_zz500_spread_long_only_v77_adk_spread_layer10_final_ridge_zz500_amount_high"
FINAL_FEATURE = "zz500_amount_high"
FINAL_WINDOWS = [80, 100, 110, 120, 130, 140, 160]
FINAL_THRESHOLDS = [1.15, 1.20, 1.25, 1.30, 1.35, 1.40, 1.50]
FINAL_CONFIRM_DAYS = [1, 2, 3]
FINAL_SCALES = [0.0, 0.10, 0.25, 0.40, 0.50]
FINAL_LINES = [
    line for line in l9.LINES
    if line["line"] in {"primary_nav_only", "confirm_nav_only", "nearby_nav_only", "watch_nav_only", "defensive_nav_only"}
]


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in FINAL_LINES:
        rows.append(
            {
                **line,
                "candidate": f"l10ridge_{line['line']}_amount_off",
                "amount_feature": "off",
                "amount_window": 0,
                "amount_threshold": 0.0,
                "confirm_days": 0,
                "amount_scale": 1.0,
                "amount_enabled": False,
            }
        )
        for window in FINAL_WINDOWS:
            for threshold in FINAL_THRESHOLDS:
                for days in FINAL_CONFIRM_DAYS:
                    for scale in FINAL_SCALES:
                        rows.append(
                            {
                                **line,
                                "candidate": (
                                    f"l10ridge_{line['line']}_{FINAL_FEATURE}"
                                    f"_w{window}_thr{l9.fmt(threshold)}_d{days}_scale{l9.fmt(scale)}"
                                ),
                                "amount_feature": FINAL_FEATURE,
                                "amount_window": window,
                                "amount_threshold": threshold,
                                "confirm_days": days,
                                "amount_scale": scale,
                                "amount_enabled": True,
                            }
                        )
    return rows


def add_final_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    out["pass_recent_1y"] = (
        (out["entry_enabled"] if "entry_enabled" in out.columns else True)
        & (out["amount_enabled"] == True)
        & (out["last_1y_ann_loss_pp"] <= 0.50 + 1e-12)
        & (out["last_1y_dd_improve_pp"] >= -0.25 - 1e-12)
    )
    out["pass_final_primary"] = (
        out["pass_full_5y_ann_dd"]
        & out["pass_recent_1y"]
        & out["line"].isin(["primary_nav_only", "confirm_nav_only"])
        & (out["amount_days_full"] >= 250)
    )
    out["pass_final_all_lines"] = (
        out["pass_full_5y_ann_dd"]
        & out["pass_recent_1y"]
        & (out["amount_days_full"] >= 50)
    )
    return out


def final_ridge_width(wm: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for rule in ["pass_full_5y_ann_dd", "pass_final_all_lines", "pass_final_primary"]:
        for line, group in wm[wm["amount_enabled"] == True].groupby("line"):
            passed = group[group[rule]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": rule,
                        "line": line,
                        "pass_count": 0,
                        "window_count": 0,
                        "threshold_count": 0,
                        "day_count": 0,
                        "scale_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": None,
                        "best_full_max_dd": None,
                        "best_5y_ann_return": None,
                        "best_5y_max_dd": None,
                        "best_1y_ann_return": None,
                        "best_1y_max_dd": None,
                        "best_amount_days": None,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(
                ["ann_return_full", "full_dd_improve_pp", "ann_return_last_5y"],
                ascending=[False, False, False],
            ).iloc[0]
            rows.append(
                {
                    "pass_rule": rule,
                    "line": line,
                    "pass_count": int(len(passed)),
                    "window_count": int(passed["amount_window"].nunique()),
                    "threshold_count": int(passed["amount_threshold"].nunique()),
                    "day_count": int(passed["confirm_days"].nunique()),
                    "scale_count": int(passed["amount_scale"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "best_5y_ann_return": float(best["ann_return_last_5y"]),
                    "best_5y_max_dd": float(best["max_dd_last_5y"]),
                    "best_1y_ann_return": float(best["ann_return_last_1y"]),
                    "best_1y_max_dd": float(best["max_dd_last_1y"]),
                    "best_amount_days": float(best["amount_days_full"]),
                    "patch_like": bool(
                        len(passed) >= 6
                        and passed["amount_window"].nunique() >= 2
                        and passed["amount_threshold"].nunique() >= 2
                        and passed["amount_scale"].nunique() >= 2
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["pass_rule", "patch_like", "pass_count", "best_full_ann_return"],
        ascending=[True, False, False, False],
    )


def comparison_table(df: pd.DataFrame, n: int = 15) -> str:
    cols = [
        "candidate",
        "line",
        "amount_window",
        "amount_threshold",
        "confirm_days",
        "amount_scale",
        "amount_days_full",
    ]
    for segment in l9.WINDOW_SEGMENTS:
        cols.extend(
            [
                f"base_ann_return_{segment}",
                f"base_max_dd_{segment}",
                f"ann_return_{segment}",
                f"max_dd_{segment}",
                f"{segment}_ann_loss_pp",
                f"{segment}_dd_improve_pp",
            ]
        )
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_") or col.startswith("base_ann_return_") or col.startswith("base_max_dd_"):
            display[col] = display[col].map(lambda x: l9.pct(float(x)))
        elif col.endswith("_ann_loss_pp"):
            display[col] = display[col].map(lambda x: f"{-float(x):+.2f}pp")
        elif col.endswith("_dd_improve_pp"):
            display[col] = display[col].map(lambda x: f"{float(x):+.2f}pp")
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = l9.base.git_text(["status", "--short"])
    mod, hs300, zz500, panel = l9.l2.load_panel()
    scores, r2s, abs_bias = l9.l2.precompute(panel)
    amount_panel, amount_meta = l9.fetch_amount_panel(mod)
    amount_panel = amount_panel.reindex(panel.index)
    complete_amount_rows = amount_panel[["HS300_amount", "ZZ500_amount"]].apply(pd.to_numeric, errors="coerce").dropna()
    base_by_line = {
        str(line["line"]): l9.nav_base_returns(panel, line, scores, r2s, abs_bias)
        for line in FINAL_LINES
    }
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    grid = make_grid()
    grid_by_candidate = {str(c["candidate"]): c for c in grid}
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []

    for cand in grid:
        result = l9.run_candidate(cand, base_by_line, amount_panel)
        wide = {**cand}
        wide["amount_complete_rows_full"] = int(len(complete_amount_rows))
        for segment, years in l9.base.SEGMENTS:
            metrics = l9.base.metrics_for_segment(result, segment, years)
            extras = l9.extra_metrics_for_segment(result, years)
            long_rows.append({**cand, **metrics, **extras})
            for key in [
                "ann_return",
                "ann_vol",
                "max_dd",
                "sharpe_repo",
                "avg_weight",
                "avg_turnover",
                "holding_day_ratio",
                "cost_total",
                "amount_days",
                "amount_day_ratio",
                "nav_amount_overlap_days",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_final_flags(l9.add_baselines_and_flags(pd.DataFrame(wide_rows)))
    ridge = final_ridge_width(window_metrics)
    full_pass = window_metrics[(window_metrics["amount_enabled"] == True) & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[(window_metrics["amount_enabled"] == True) & window_metrics["pass_full_5y_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    final_primary = window_metrics[window_metrics["pass_final_primary"]].sort_values(
        ["ann_return_full", "full_dd_improve_pp", "ann_return_last_5y"], ascending=[False, False, False]
    )
    final_all = window_metrics[window_metrics["pass_final_all_lines"]].sort_values(
        ["ann_return_full", "full_dd_improve_pp", "ann_return_last_5y"], ascending=[False, False, False]
    )

    for tier in l9.LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(
            ["line", "full_dd_improve_pp", "ann_return_full"], ascending=[True, False, False]
        )
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")

    selected_candidate = (
        "l10ridge_primary_nav_only_zz500_amount_high_w120_thr1p25_d1_scale0p25"
    )
    selected = window_metrics[window_metrics["candidate"] == selected_candidate].copy()
    carry = pd.concat([selected, final_primary.head(8), final_all.head(8)], ignore_index=True).drop_duplicates("candidate")

    keep_candidates = set(window_metrics.loc[window_metrics["amount_enabled"] == False, "candidate"].astype(str))
    keep_candidates.update(carry["candidate"].astype(str).tolist())
    keep_candidates.update(final_primary.head(25)["candidate"].astype(str).tolist())
    keep_candidates.update(final_all.head(25)["candidate"].astype(str).tolist())
    daily_parts = []
    for candidate in sorted(keep_candidates):
        cand = grid_by_candidate[candidate]
        result = l9.run_candidate(cand, base_by_line, amount_panel)
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["line"] = cand["line"]
        daily["amount_feature"] = cand["amount_feature"]
        daily_parts.append(daily.reset_index(names="date"))

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    pd.concat(daily_parts, ignore_index=True).to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")
    final_primary.to_csv(RUN_DIR / "final_primary_pass_candidates.csv", index=False, encoding="utf-8-sig")
    final_all.to_csv(RUN_DIR / "final_all_pass_candidates.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# HS300/ZZ500 Layer 10 ZZ500 High-Amount Final Ridge",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer10_final_ridge_complete_fixed_candidate_selected`",
        "- stability: `zz500_amount_high_final_ridge_with_1y_constraint`",
        "",
        "## Research Question",
        "Fine-scan only the Layer 9 promoted `zz500_amount_high` family and select a fixed final research rule with explicit 1Y non-damage control.",
        "",
        "## Data Snapshot",
        f"- HS300 publication date: {l9.base.HS300_PUBLICATION_DATE}; local rows: {len(hs300)}, start {hs300.index.min().date()}, end {hs300.index.max().date()}.",
        f"- ZZ500 publication date: {l9.base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Formal aligned price rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        f"- Amount source HS300: {amount_meta['HS300_source']}; ZZ500: {amount_meta['ZZ500_source']}.",
        f"- Complete amount rows on formal price dates: {len(complete_amount_rows)}, start {complete_amount_rows.index.min().date()}, end {complete_amount_rows.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long HS300 / short ZZ500; ratio is HS300/ZZ500; spread return is HS300 pct_change minus ZZ500 pct_change.",
        "- T close signal/amount state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {l9.base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Overheat, entry staging, and momentum decay are off; NAV-only remains on from the Layer 6 decision.",
        "- Result status: quasi-formal price-index close-to-close research with EastMoney amount fallback.",
        "",
        "## Final Ridge Grid",
        f"- amount_feature: `{FINAL_FEATURE}`",
        f"- windows: {FINAL_WINDOWS}",
        f"- thresholds: {FINAL_THRESHOLDS}",
        f"- confirm days: {FINAL_CONFIRM_DAYS}",
        f"- scales: {FINAL_SCALES}",
        "",
        "## Baselines",
        comparison_table(window_metrics[window_metrics["amount_enabled"] == False], len(FINAL_LINES)),
        "",
        "## Final Primary Pass Candidates",
        comparison_table(final_primary, 20) if not final_primary.empty else "No primary/confirm candidate passed final constraints.",
        "",
        "## Final All-Line Pass Candidates",
        comparison_table(final_all, 20) if not final_all.empty else "No candidate passed final constraints.",
        "",
        "## Selected Fixed Candidate",
        comparison_table(selected, 1),
        "",
        "## Width Summary",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Select `l10ridge_primary_nav_only_zz500_amount_high_w120_thr1p25_d1_scale0p25` for fixed-script landing.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    git_status_after = l9.base.git_text(["status", "--short"])
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "HS300/ZZ500 spread Layer 10 final ridge",
        "repo_root": str(l9.base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_hs300_zz500_spread_layer9_amount.py",
        "git_branch": l9.base.git_text(["branch", "--show-current"]),
        "git_commit": l9.base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": git_status_after,
        "scan_type": "fresh_layer10_final_ridge_zz500_amount_high",
        "formal_status": "quasi_formal_price_index_close_to_close_with_eastmoney_amount",
        "parameter_group": "zz500_amount_high_final_ridge_after_layer9",
        "baseline": {"inputs": FINAL_LINES, "pass_rule": "compare every amount candidate with same-line amount_off"},
        "candidate_grid": grid,
        "selected_candidate": selected_candidate,
        "selection_rule": "primary line, full+5Y non-underperformance, 1Y loss<=0.5pp, 1Y DD not worse by more than 0.25pp, width-supported family",
        "data_snapshot": {
            "price_source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "amount_source": amount_meta,
            "formal_price": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "aligned_amount": {
                "rows": int(len(complete_amount_rows)),
                "start": str(complete_amount_rows.index.min().date()),
                "end": str(complete_amount_rows.index.max().date()),
            },
            "publication_dates": {"HS300": l9.base.HS300_PUBLICATION_DATE, "ZZ500": l9.base.ZZ500_PUBLICATION_DATE},
        },
        "cost_model": {
            "one_way_commission": l9.base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
            "direction": "long HS300 / short ZZ500",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "decision": "layer10_final_ridge_complete_fixed_candidate_selected",
        "stability_label": "zz500_amount_high_final_ridge_with_1y_constraint",
        "daily_curve_scope": "baselines plus final primary/all-line pass candidates",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "full_baseline_pass_candidates": str(RUN_DIR / "full_baseline_pass_candidates.csv"),
            "full_and_5y_pass_candidates": str(RUN_DIR / "full_and_5y_pass_candidates.csv"),
            "dd_first_pass_loss_le_0p5pp": str(RUN_DIR / "dd_first_pass_loss_le_0p5pp.csv"),
            "dd_first_pass_loss_le_1p0pp": str(RUN_DIR / "dd_first_pass_loss_le_1p0pp.csv"),
            "dd_first_pass_loss_le_2p0pp": str(RUN_DIR / "dd_first_pass_loss_le_2p0pp.csv"),
            "final_primary_pass_candidates": str(RUN_DIR / "final_primary_pass_candidates.csv"),
            "final_all_pass_candidates": str(RUN_DIR / "final_all_pass_candidates.csv"),
            "carry_candidates": str(RUN_DIR / "carry_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "\n".join(
            [
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "HS300/ZZ500 spread Layer 10 final ridge" --parameter-group "zz500_amount_high_final_ridge_after_layer9" --repo . --entrypoint "scan_adk_hs300_zz500_spread_layer10_final_ridge.py" --date 2026-06-12 --slug "adk_hs300_zz500_spread_long_only_v77_adk_spread_layer10_final_ridge_zz500_amount_high"',
                'python -m py_compile "scan_adk_hs300_zz500_spread_layer10_final_ridge.py"',
                'git diff --check -- "scan_adk_hs300_zz500_spread_layer10_final_ridge.py"',
                'python "scan_adk_hs300_zz500_spread_layer10_final_ridge.py"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "{RUN_DIR}" --decision "layer10_final_ridge_complete_fixed_candidate_selected" --stability-label "zz500_amount_high_final_ridge_with_1y_constraint"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict "{RUN_DIR}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    display_cols = [
        "candidate",
        "line",
        "amount_window",
        "amount_threshold",
        "confirm_days",
        "amount_scale",
        "amount_days_full",
        "ann_return_full",
        "max_dd_full",
        "ann_return_last_10y",
        "max_dd_last_10y",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "ann_return_last_3y",
        "max_dd_last_3y",
        "ann_return_last_1y",
        "max_dd_last_1y",
        "full_ann_loss_pp",
        "full_dd_improve_pp",
        "last_1y_ann_loss_pp",
        "last_1y_dd_improve_pp",
    ]
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(
        "PASS_COUNTS="
        f"full={len(full_pass)} strict5y={len(strict_pass)} "
        f"final_primary={len(final_primary)} final_all={len(final_all)}"
    )
    print("SELECTED")
    print(selected[display_cols].to_string(index=False))
    print("FINAL_PRIMARY_TOP")
    print(final_primary[display_cols].head(20).to_string(index=False) if not final_primary.empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

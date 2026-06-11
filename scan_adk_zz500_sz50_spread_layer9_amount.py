"""Layer 9 official amount filter for long ZZ500 / short SZ50.

Layer 7 overheat and Layer 8 entry staging were not promoted, so this layer
tests CSIndex official amount filters directly on the Layer 6 decay-only carry
lines. Amount states are evaluated at T close and shifted to T+1 execution.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_sz50_spread_layer3_target_vol as l3
import scan_adk_zz500_sz50_spread_layer7_overheat as l7
import scan_adk_zz500_sz50_spread_layer8_entry_staging as l8
import scan_adk_zz500_sz50_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_sz50_spread_long_only_v77_adk_spread_layer9_amount_csindex_official"
AMOUNT_CSV = base.ROOT / "outputs" / "adk_zz500_sz50_amount_csindex_official.csv"
AMOUNT_META = base.ROOT / "outputs" / "adk_zz500_sz50_amount_csindex_official_meta.json"

INPUTS = l8.LINES
AMOUNT_WINDOWS = [20, 40, 60, 80, 120]
HIGH_THRESHOLDS = [1.25, 1.50, 1.75, 2.00]
LOW_THRESHOLDS = [0.75, 0.85, 1.00]
CONFIRM_DAYS = [1, 3, 5]
AMOUNT_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0]


def fmt(value: float) -> str:
    return f"{value:g}".replace(".", "p")


def load_amount_panel() -> tuple[pd.DataFrame, dict[str, object]]:
    if not AMOUNT_CSV.exists():
        raise FileNotFoundError(f"missing amount panel, run fetch_adk_zz500_sz50_real_amount_panel.py first: {AMOUNT_CSV}")
    amount = pd.read_csv(AMOUNT_CSV, encoding="utf-8-sig")
    amount["date"] = pd.to_datetime(amount["date"])
    amount = amount.set_index("date").sort_index()
    meta = json.loads(AMOUNT_META.read_text(encoding="utf-8")) if AMOUNT_META.exists() else {}
    return amount, meta


def amount_feature(amount_panel: pd.DataFrame, feature: str, window: int) -> pd.Series:
    zz500_rel = amount_panel["zz500_amount"] / amount_panel["zz500_amount"].rolling(window).mean()
    sz50_rel = amount_panel["sz50_amount"] / amount_panel["sz50_amount"].rolling(window).mean()
    pair_rel = zz500_rel / sz50_rel
    if feature in {"zz500_amount_high", "zz500_amount_low"}:
        return zz500_rel
    if feature in {"sz50_amount_high", "sz50_amount_low"}:
        return sz50_rel
    if feature in {"pair_amount_high", "pair_amount_low"}:
        return pair_rel
    raise ValueError(feature)


def confirmed_trigger(cond: pd.Series, days: int) -> pd.Series:
    if days <= 1:
        return cond.fillna(False).astype(bool)
    return (cond.astype(float).rolling(days).sum().fillna(0) >= days).astype(bool)


def apply_amount_overlay(
    base_df: pd.DataFrame,
    amount_panel: pd.DataFrame,
    feature: str | None,
    window: int | None,
    threshold: float | None,
    confirm_days: int | None,
    scale: float | None,
) -> pd.DataFrame:
    d = base_df.copy()
    if feature is None:
        mult = pd.Series(1.0, index=d.index)
        on = pd.Series(False, index=d.index)
        indicator = pd.Series(np.nan, index=d.index)
    else:
        indicator = amount_feature(amount_panel, feature, int(window)).reindex(d.index)
        raw = indicator >= float(threshold) if feature.endswith("high") else indicator <= float(threshold)
        on = confirmed_trigger(raw, int(confirm_days)).shift(1, fill_value=False).astype(bool)
        mult = pd.Series(1.0, index=d.index)
        mult.loc[on] = float(scale)

    final_weight = d["layer6_weight"] * mult
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = final_weight * d["spread_return"].fillna(0.0)
    ret = gross_return - cost
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "pre_amount_weight": d["layer6_weight"],
            "amount_mult": mult,
            "amount_on": on.astype(float),
            "amount_indicator": indicator,
            "spread_return": d["spread_return"],
            "nav_on": d["nav_on"],
            "decay_on": d["decay_on"],
            "score": d["score"],
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    features = [
        "zz500_amount_high",
        "zz500_amount_low",
        "sz50_amount_high",
        "sz50_amount_low",
        "pair_amount_high",
        "pair_amount_low",
    ]
    for line in INPUTS:
        rows.append(
            {
                **line,
                "candidate": f"l9amt_{line['line']}_amount_off",
                "amount_feature": "off",
                "amount_window": 0,
                "amount_threshold": 0.0,
                "confirm_days": 0,
                "amount_scale": 1.0,
                "amount_enabled": False,
            }
        )
        for feature in features:
            thresholds = HIGH_THRESHOLDS if feature.endswith("high") else LOW_THRESHOLDS
            for window in AMOUNT_WINDOWS:
                for threshold in thresholds:
                    for days in CONFIRM_DAYS:
                        for scale in AMOUNT_SCALES:
                            rows.append(
                                {
                                    **line,
                                    "candidate": (
                                        f"l9amt_{line['line']}_{feature}"
                                        f"_w{window}_thr{fmt(threshold)}_d{days}_scale{fmt(scale)}"
                                    ),
                                    "amount_feature": feature,
                                    "amount_window": window,
                                    "amount_threshold": threshold,
                                    "confirm_days": days,
                                    "amount_scale": scale,
                                    "amount_enabled": True,
                                }
                            )
    return rows


def run_candidate(cand: dict[str, object], base_by_line: dict[str, pd.DataFrame], amount_panel: pd.DataFrame) -> pd.DataFrame:
    return apply_amount_overlay(
        base_by_line[str(cand["line"])],
        amount_panel,
        None if not cand["amount_enabled"] else str(cand["amount_feature"]),
        None if not cand["amount_enabled"] else int(cand["amount_window"]),
        None if not cand["amount_enabled"] else float(cand["amount_threshold"]),
        None if not cand["amount_enabled"] else int(cand["confirm_days"]),
        None if not cand["amount_enabled"] else float(cand["amount_scale"]),
    )


def extra_metrics_for_segment(result: pd.DataFrame, years: int | None) -> dict[str, float]:
    if years is None:
        d = result.copy()
    else:
        cutoff = result.index.max() - pd.DateOffset(years=years)
        d = result.loc[result.index >= cutoff].copy()
    if d.empty:
        return {"amount_days": 0.0, "amount_day_ratio": 0.0, "decay_amount_overlap_days": 0.0}
    return {
        "amount_days": float(d["amount_on"].sum()),
        "amount_day_ratio": float(d["amount_on"].mean()),
        "decay_amount_overlap_days": float(((d["decay_on"] > 0) & (d["amount_on"] > 0)).sum()),
    }


def add_baselines_and_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["amount_enabled"] == False].set_index("line")
    for col in [
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
        "sharpe_repo_full",
        "cost_total_full",
    ]:
        out[f"base_{col}"] = out["line"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100.0
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100.0
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100.0
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100.0
    out["cost_delta"] = out["cost_total_full"] - out["base_cost_total_full"]
    out["pass_full_ann_dd"] = (
        (out["amount_enabled"] == True)
        & (out["ann_return_full"] >= out["base_ann_return_full"] - 1e-12)
        & (out["max_dd_full"] >= out["base_max_dd_full"] - 1e-12)
    )
    out["pass_full_and_5y"] = (
        out["pass_full_ann_dd"]
        & (out["ann_return_last_5y"] >= out["base_ann_return_last_5y"] - 1e-12)
        & (out["max_dd_last_5y"] >= out["base_max_dd_last_5y"] - 1e-12)
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            (out["amount_enabled"] == True)
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["fivey_dd_improve_pp"] >= -1e-12)
        )
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    pass_cols = ["pass_full_ann_dd", "pass_full_and_5y"] + [f"pass_loss_le_{str(t).replace('.', 'p')}pp" for t in LOSS_TIERS]
    source = wm[wm["amount_enabled"] == True]
    for pass_col in pass_cols:
        for (line, feature), group in source.groupby(["line", "amount_feature"]):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": pass_col,
                        "line": line,
                        "amount_feature": feature,
                        "pass_count": 0,
                        "window_count": 0,
                        "threshold_count": 0,
                        "day_count": 0,
                        "scale_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "best_amount_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(len(passed) >= 4 and passed["amount_window"].nunique() >= 2 and passed["amount_threshold"].nunique() >= 2)
            rows.append(
                {
                    "pass_rule": pass_col,
                    "line": line,
                    "amount_feature": feature,
                    "pass_count": int(len(passed)),
                    "window_count": int(passed["amount_window"].nunique()),
                    "threshold_count": int(passed["amount_threshold"].nunique()),
                    "day_count": int(passed["confirm_days"].nunique()),
                    "scale_count": int(passed["amount_scale"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                    "best_full_dd_improve_pp": best["full_dd_improve_pp"],
                    "best_5y_ann_return": best["ann_return_last_5y"],
                    "best_5y_max_dd": best["max_dd_last_5y"],
                    "best_amount_days": best["amount_days_full"],
                    "patch_like": patch_like,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["pass_rule", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def window_table(df: pd.DataFrame, n: int = 16) -> str:
    cols = ["candidate", "line", "amount_feature", "amount_window", "amount_threshold", "confirm_days", "amount_scale", "amount_days_full"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    mod, zz500, sz50, panel = l3.load_panel()
    amount_panel, amount_meta = load_amount_panel()
    amount_panel = amount_panel.reindex(panel.index)
    complete_amount_rows = amount_panel[["zz500_amount", "sz50_amount"]].apply(pd.to_numeric, errors="coerce").dropna()
    base_by_line = {str(line["line"]): l7.layer6_base_returns(panel, line) for line in INPUTS}
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    grid = make_grid()
    grid_by_candidate = {str(c["candidate"]): c for c in grid}
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []

    for cand in grid:
        result = run_candidate(cand, base_by_line, amount_panel)
        wide = {**cand}
        wide["amount_complete_rows_full"] = int(len(complete_amount_rows))
        for segment, years in base.SEGMENTS:
            metrics = base.metrics_for_segment(result, segment, years)
            extras = extra_metrics_for_segment(result, years)
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
                "decay_amount_overlap_days",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    full_pass = window_metrics[(window_metrics["amount_enabled"] == True) & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[(window_metrics["amount_enabled"] == True) & window_metrics["pass_full_and_5y"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    loss_passes: dict[float, pd.DataFrame] = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(
            ["line", "full_dd_improve_pp", "ann_return_full"], ascending=[True, False, False]
        )
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        loss_passes[tier] = passed

    keep_candidates = set(window_metrics.loc[window_metrics["amount_enabled"] == False, "candidate"].astype(str))
    keep_candidates.update(strict_pass.head(80)["candidate"].astype(str).tolist())
    keep_candidates.update(full_pass.head(80)["candidate"].astype(str).tolist())
    for passed in loss_passes.values():
        keep_candidates.update(passed.head(40)["candidate"].astype(str).tolist())
    daily_parts = []
    for candidate in sorted(keep_candidates):
        cand = grid_by_candidate[candidate]
        result = run_candidate(cand, base_by_line, amount_panel)
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

    cols = [
        "candidate",
        "line",
        "line_role",
        "amount_feature",
        "amount_window",
        "amount_threshold",
        "confirm_days",
        "amount_scale",
        "amount_days_full",
        "ann_return_full",
        "max_dd_full",
        "full_ann_loss_pp",
        "full_dd_improve_pp",
        "ann_return_last_10y",
        "max_dd_last_10y",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "fivey_ann_loss_pp",
        "fivey_dd_improve_pp",
        "ann_return_last_3y",
        "max_dd_last_3y",
        "ann_return_last_1y",
        "max_dd_last_1y",
        "cost_total_full",
    ]
    display_cols = [c for c in cols if c in window_metrics.columns]
    record_lines = [
        "# ZZ500/SZ50 Layer 9 CSIndex Official Amount Filter",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer9_amount_complete_pending_user_review`",
        "- stability: `csindex_official_amount_filter_review`",
        "",
        "## Research Question",
        "Test official amount relative-MA filters after the decay-only carry lines, with overheat and entry staging left rejected/off.",
        "",
        "## Layer Inputs",
        pd.DataFrame(INPUTS).to_markdown(index=False),
        "",
        "## Data Snapshot",
        f"- SZ50 publication date: {base.SZ50_PUBLICATION_DATE}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}.",
        f"- Formal aligned price rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        f"- Complete CSIndex amount rows on formal price dates: {len(complete_amount_rows)}, start {complete_amount_rows.index.min().date()}, end {complete_amount_rows.index.max().date()}.",
        f"- Amount panel: `{AMOUNT_CSV}`.",
        f"- Amount source: {amount_meta.get('primary_source', 'CSIndex official amount')}.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long ZZ500 / short SZ50; ratio is ZZ500/SZ50; spread return is ZZ500 pct_change minus SZ50 pct_change.",
        "- T close amount state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Amount features use own-MA relative values or pair-relative ratios only.",
        "- NAV defense, overheat, and entry staging are off; momentum decay remains on from Layer 6 carried lines.",
        "",
        "## Amount Grid",
        f"- windows: {AMOUNT_WINDOWS}",
        f"- high thresholds: {HIGH_THRESHOLDS}",
        f"- low thresholds: {LOW_THRESHOLDS}",
        f"- confirm days: {CONFIRM_DAYS}",
        f"- scales: {AMOUNT_SCALES}",
        "",
        "## Baselines",
        window_metrics[window_metrics["amount_enabled"] == False][display_cols].to_markdown(index=False),
        "",
        "## Full+5Y Non-Underperformance Candidates",
        window_table(strict_pass, 20) if not strict_pass.empty else "No amount candidate passed full+5Y non-underperformance.",
        "",
        "## DD-First Candidates Loss <= 0.5pp",
        window_table(loss_passes[0.5], 20) if not loss_passes[0.5].empty else "No amount candidate passed loss<=0.5pp with DD improvement.",
        "",
        "## DD-First Candidates Loss <= 1pp",
        window_table(loss_passes[1.0], 20) if not loss_passes[1.0].empty else "No amount candidate passed loss<=1pp with DD improvement.",
        "",
        "## Width Summary",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 9 completed and stopped for user review before any volume sibling or final ridge layer.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    git_status = base.git_text(["status", "--short"])
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz500_sz50_spread_layer7_overheat.py",
        "amount_fetch_entrypoint": "fetch_adk_zz500_sz50_real_amount_panel.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status,
        "git_status_after": git_status,
        "scan_type": "fresh_layer9_amount_after_decay_only",
        "formal_status": "quasi_formal_price_index_close_to_close_with_real_source_csindex_amount",
        "parameter_group": "csindex_amount_relative_ma_filter_after_decay",
        "baseline": {"inputs": INPUTS, "pass_rule": "compare every amount candidate with same-line amount_off"},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close amount state -> T+1 close-to-close return",
            "direction": "long ZZ500 / short SZ50",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache for prices; CSIndex official amount for amount panel",
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "amount": {
                "csv": str(AMOUNT_CSV),
                "meta": str(AMOUNT_META),
                "complete_rows_on_formal_dates": int(len(complete_amount_rows)),
                "start": str(complete_amount_rows.index.min().date()),
                "end": str(complete_amount_rows.index.max().date()),
                "source_attempts": amount_meta.get("attempts", {}),
            },
            "publication_dates": {"SZ50": base.SZ50_PUBLICATION_DATE, "ZZ500": base.ZZ500_PUBLICATION_DATE},
        },
        "decision": "layer9_amount_complete_pending_user_review",
        "stability_label": "csindex_official_amount_filter_review",
        "daily_curve_scope": "baselines plus top strict/full-loss candidates, not all grid candidates",
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
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "\n".join(
            [
                'python fetch_adk_zz500_sz50_real_amount_panel.py',
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "ZZ500/SZ50 spread Layer 9 amount" --parameter-group "csindex_amount_relative_ma_filter_after_decay" --repo . --entrypoint "scan_adk_zz500_sz50_spread_layer9_amount.py" --date 2026-06-12 --slug "adk_zz500_sz50_spread_long_only_v77_adk_spread_layer9_amount_csindex_official"',
                'python -m py_compile "fetch_adk_zz500_sz50_real_amount_panel.py" "scan_adk_zz500_sz50_spread_layer9_amount.py"',
                'git diff --check -- "fetch_adk_zz500_sz50_real_amount_panel.py" "scan_adk_zz500_sz50_spread_layer9_amount.py"',
                'python "scan_adk_zz500_sz50_spread_layer9_amount.py"',
                'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "<run_folder>" --decision "layer9_amount_complete_pending_user_review" --stability-label "csindex_official_amount_filter_review" --repo .',
                'python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict "<run_folder>"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(f"AMOUNT_COMPLETE={complete_amount_rows.index.min().date()}->{complete_amount_rows.index.max().date()} rows={len(complete_amount_rows)}")
    print(
        "FULL_PASS_COUNT="
        f"{len(full_pass)} STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)} "
        f"LOSS0P5_COUNT={len(loss_passes[0.5])} LOSS1_COUNT={len(loss_passes[1.0])} LOSS2_COUNT={len(loss_passes[2.0])}"
    )
    print("BASELINES")
    print(window_metrics[window_metrics.amount_enabled == False][display_cols].to_string(index=False))
    print("STRICT_PASS_TOP")
    print(strict_pass[display_cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_TOP")
        print(loss_passes[tier][display_cols].head(20).to_string(index=False) if not loss_passes[tier].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

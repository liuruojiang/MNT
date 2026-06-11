"""Layer 5 score-peak momentum decay after rejected NAV defense for SZ50/ZZ500.

Layer 4 NAV defense was reviewed as too weak to promote, so this formal Layer 5
scan carries Layer 3 target-vol candidates unchanged. Momentum decay is based on
T-close signal strength relative to the current active trade's strength peak and
is shifted to the next execution row. It is not a NAV drawdown gate.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_sz50_zz500_spread_layer3_target_vol as l3
import scan_adk_sz50_zz500_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_sz50_zz500_spread_long_only_v77_adk_spread_layer5_momentum_decay_after_l4_rejected"

LINES = [
    {
        "line": "return_s0_tv16_vw20_max1p5_db0p30",
        "line_role": "primary_after_l4_rejected",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.75,
        "score_threshold": 0.0,
        "abs_ma": 80,
        "abs_threshold": -0.050,
        "target_vol": 0.16,
        "vol_window": 20,
        "max_leverage": 1.5,
        "scale_deadband": 0.30,
        "tv_enabled": True,
        "layer3_candidate": "l3_return_60_18_s0_abs80_m5_tv16_vw20_max1p5_db0p3",
    },
    {
        "line": "return_sm1_tv16_vw30_max1p5_db0p20",
        "line_role": "return_heavy_watch",
        "bias_ma": 60,
        "mom_day": 18,
        "weight_end": 2.75,
        "score_threshold": -1.0,
        "abs_ma": 30,
        "abs_threshold": 0.005,
        "target_vol": 0.16,
        "vol_window": 30,
        "max_leverage": 1.5,
        "scale_deadband": 0.20,
        "tv_enabled": True,
        "layer3_candidate": "l3_return_60_18_sm1_abs30_0p5_tv16_vw30_max1p5_db0p2",
    },
    {
        "line": "primary_65_16_tv8_vw20_max1p5_db0p30",
        "line_role": "nearby_confirmation",
        "bias_ma": 65,
        "mom_day": 16,
        "weight_end": 2.75,
        "score_threshold": 1.0,
        "abs_ma": 45,
        "abs_threshold": -0.015,
        "target_vol": 0.08,
        "vol_window": 20,
        "max_leverage": 1.5,
        "scale_deadband": 0.30,
        "tv_enabled": True,
        "layer3_candidate": "l3_primary_65_16_s1_abs45_m1p5_tv8_vw20_max1p5_db0p3",
    },
]

DECAY_THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]
RECOVERY_THRESHOLDS = [0.60, 0.70, 0.80, 0.90]
WARMUP_DAYS = [3, 5, 10]
DERISK_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0]


def fmt_num(value: float) -> str:
    sign = "m" if value < 0 else ""
    return sign + f"{abs(value):g}".replace(".", "p")


def l3_base_returns(panel: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    sig = l3.line_signal(panel, line)
    d = l3.returns_for(panel, sig, line).copy()
    d["raw_signal"] = sig["raw_signal"].reindex(d.index).fillna(0.0)
    d["score_strength"] = (d["score"] - float(line["score_threshold"])).clip(lower=0.0)
    d["base_weight"] = d["weight"]
    return d


def score_decay_multiplier(
    d: pd.DataFrame,
    decay: float | None,
    recovery: float | None,
    warmup: int | None,
    derisk_scale: float | None,
) -> pd.Series:
    if decay is None:
        return pd.Series(1.0, index=d.index)
    raw_signal = d["raw_signal"].astype(float).to_numpy()
    strength = d["score_strength"].astype(float).to_numpy()
    state = np.ones(len(d), dtype=float)
    peak = np.nan
    active_days = 0
    in_decay = False
    for i in range(len(d)):
        if raw_signal[i] <= 0 or not np.isfinite(strength[i]) or strength[i] <= 0:
            peak = np.nan
            active_days = 0
            in_decay = False
            state[i] = 1.0
            continue
        active_days += 1
        peak = strength[i] if not np.isfinite(peak) else max(peak, strength[i])
        ratio = strength[i] / peak if peak > 0 else 1.0
        if active_days >= int(warmup):
            if in_decay:
                if ratio >= float(recovery):
                    in_decay = False
                    peak = strength[i]
            elif ratio <= float(decay):
                in_decay = True
        state[i] = float(derisk_scale) if in_decay else 1.0
    return pd.Series(state, index=d.index).shift(1).fillna(1.0)


def apply_decay(
    base_df: pd.DataFrame,
    decay: float | None,
    recovery: float | None,
    warmup: int | None,
    derisk_scale: float | None,
) -> pd.DataFrame:
    d = base_df.copy()
    decay_mult = score_decay_multiplier(d, decay, recovery, warmup, derisk_scale)
    final_weight = d["base_weight"] * decay_mult
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = final_weight * d["spread_return"].fillna(0.0)
    ret = gross_return - cost
    decay_on = (decay_mult < 1.0 - 1e-12) & (d["base_weight"].abs() > 1e-12)
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "base_weight": d["base_weight"],
            "decay_mult": decay_mult,
            "decay_on": decay_on.astype(int),
            "score": d["score"],
            "score_strength": d["score_strength"],
            "raw_signal": d["raw_signal"],
            "applied_scale": d["applied_scale"],
            "realized_vol": d["realized_vol"],
            "spread_return": d["spread_return"],
        },
        index=d.index,
    )


def make_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for line in LINES:
        grid.append(
            {
                **line,
                "candidate": f"l5_{line['line']}_decay_off",
                "decay_threshold": 0.0,
                "recovery_threshold": 0.0,
                "warmup_days": 0,
                "derisk_scale": 1.0,
                "decay_enabled": False,
            }
        )
        for decay in DECAY_THRESHOLDS:
            for recovery in RECOVERY_THRESHOLDS:
                if recovery <= decay:
                    continue
                for warmup in WARMUP_DAYS:
                    for scale in DERISK_SCALES:
                        grid.append(
                            {
                                **line,
                                "candidate": f"l5_{line['line']}_decay{fmt_num(decay)}_rec{fmt_num(recovery)}_warm{warmup}_scale{fmt_num(scale)}",
                                "decay_threshold": decay,
                                "recovery_threshold": recovery,
                                "warmup_days": warmup,
                                "derisk_scale": scale,
                                "decay_enabled": True,
                            }
                        )
    return grid


def extra_metrics_for_segment(result: pd.DataFrame, years: int | None) -> dict[str, float]:
    if years is None:
        d = result.copy()
    else:
        cutoff = result.index.max() - pd.DateOffset(years=years)
        d = result.loc[result.index >= cutoff].copy()
    if d.empty:
        return {
            "decay_days": 0.0,
            "decay_day_ratio": 0.0,
            "avg_decay_mult": 1.0,
            "avg_active_decay_mult": 1.0,
        }
    active = d["base_weight"].abs() > 1e-12
    active_mult = d.loc[active, "decay_mult"]
    return {
        "decay_days": float(d["decay_on"].sum()),
        "decay_day_ratio": float(d["decay_on"].mean()),
        "avg_decay_mult": float(d["decay_mult"].mean()),
        "avg_active_decay_mult": float(active_mult.mean()) if not active_mult.empty else 1.0,
    }


def add_baselines_and_flags(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["decay_enabled"] == False].set_index("line")
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
        "cost_total_full",
    ]:
        out[f"base_{col}"] = out["line"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100.0
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100.0
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100.0
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100.0
    out["cost_delta"] = out["cost_total_full"] - out["base_cost_total_full"]
    out["pass_full_ann_dd"] = (
        (out["decay_enabled"] == True)
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
            (out["decay_enabled"] == True)
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["fivey_dd_improve_pp"] >= -1e-12)
        )
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    pass_cols = ["pass_full_ann_dd", "pass_full_and_5y"] + [f"pass_loss_le_{str(t).replace('.', 'p')}pp" for t in LOSS_TIERS]
    source = wm[wm["decay_enabled"] == True]
    for pass_col in pass_cols:
        for line, group in source.groupby("line"):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "pass_rule": pass_col,
                        "line": line,
                        "pass_count": 0,
                        "decay_count": 0,
                        "recovery_count": 0,
                        "warmup_count": 0,
                        "scale_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "best_decay_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            rows.append(
                {
                    "pass_rule": pass_col,
                    "line": line,
                    "pass_count": int(len(passed)),
                    "decay_count": int(passed["decay_threshold"].nunique()),
                    "recovery_count": int(passed["recovery_threshold"].nunique()),
                    "warmup_count": int(passed["warmup_days"].nunique()),
                    "scale_count": int(passed["derisk_scale"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                    "best_full_dd_improve_pp": best["full_dd_improve_pp"],
                    "best_5y_ann_return": best["ann_return_last_5y"],
                    "best_5y_max_dd": best["max_dd_last_5y"],
                    "best_decay_days": best["decay_days_full"],
                    "patch_like": bool(
                        len(passed) >= 4
                        and passed["decay_threshold"].nunique() >= 2
                        and passed["derisk_scale"].nunique() >= 2
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["pass_rule", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def window_table(df: pd.DataFrame, n: int = 16) -> str:
    cols = [
        "candidate",
        "line",
        "decay_threshold",
        "recovery_threshold",
        "warmup_days",
        "derisk_scale",
        "decay_days_full",
    ]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, sz50, zz500, panel = l3.load_panel()
    base_by_line = {str(line["line"]): l3_base_returns(panel, line) for line in LINES}
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    grid = make_grid()
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    daily_parts: list[pd.DataFrame] = []

    for cand in grid:
        result = apply_decay(
            base_by_line[str(cand["line"])],
            None if not bool(cand["decay_enabled"]) else float(cand["decay_threshold"]),
            None if not bool(cand["decay_enabled"]) else float(cand["recovery_threshold"]),
            None if not bool(cand["decay_enabled"]) else int(cand["warmup_days"]),
            None if not bool(cand["decay_enabled"]) else float(cand["derisk_scale"]),
        )
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["line"] = cand["line"]
        daily_parts.append(daily.reset_index(names="date"))

        wide = {**cand}
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
                "decay_days",
                "decay_day_ratio",
                "avg_decay_mult",
                "avg_active_decay_mult",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)

    full_pass = window_metrics[(window_metrics["decay_enabled"] == True) & window_metrics["pass_full_ann_dd"]].sort_values(
        ["ann_return_full", "max_dd_full"], ascending=[False, False]
    )
    strict_pass = window_metrics[(window_metrics["decay_enabled"] == True) & window_metrics["pass_full_and_5y"]].sort_values(
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

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")

    cols = [
        "candidate",
        "line",
        "line_role",
        "decay_threshold",
        "recovery_threshold",
        "warmup_days",
        "derisk_scale",
        "decay_days_full",
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
    baseline = window_metrics[window_metrics["decay_enabled"] == False][display_cols]
    record_lines = [
        "# SZ50/ZZ500 Layer 5 Momentum Decay After Rejected NAV Defense",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer5_momentum_decay_complete_pending_user_review`",
        "- stability: `momentum_decay_after_l4_rejected_patch_review`",
        "",
        "## Research Question",
        "Test score-peak momentum decay after Layer 4 NAV defense was rejected as too weak; baseline is Layer 3 target-vol unchanged.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
        "",
        "## Data Snapshot",
        f"- SZ50 publication date: {base.SZ50_PUBLICATION_DATE}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        f"- SZ50 rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- ZZ500 rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long SZ50 / short ZZ500; ratio is SZ50/ZZ500; spread return is SZ50 pct_change minus ZZ500 pct_change.",
        "- T close signal/state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Momentum decay uses T-close score strength `(score - score_threshold).clip(lower=0)` divided by active-trade strength peak, shifted one row to next execution.",
        "- NAV defense, overheat, amount, and volume overlays are off.",
        "",
        "## Decay Grid",
        f"- decay_threshold: {DECAY_THRESHOLDS}",
        f"- recovery_threshold: {RECOVERY_THRESHOLDS}, with recovery > decay.",
        f"- warmup_days: {WARMUP_DAYS}",
        f"- derisk_scale: {DERISK_SCALES}",
        "",
        "## Baselines",
        baseline.to_markdown(index=False),
        "",
        "## Full+5Y Non-Underperformance Candidates",
        window_table(strict_pass, 20) if not strict_pass.empty else "No decay candidate passed full+5Y non-underperformance.",
        "",
        "## DD-First Candidates Loss <= 1pp",
        window_table(loss_passes[1.0], 20) if not loss_passes[1.0].empty else "No decay candidate passed loss<=1pp with DD improvement.",
        "",
        "## DD-First Candidates Loss <= 2pp",
        window_table(loss_passes[2.0], 20) if not loss_passes[2.0].empty else "No decay candidate passed loss<=2pp with DD improvement.",
        "",
        "## Width Summary",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 5 completed and stopped for user review before later overlays.",
        "",
        "## User-Facing Summary",
        f"- candidates_scanned: {len(grid)}",
        f"- full_baseline_pass_count: {len(full_pass)}",
        f"- full_and_5y_pass_count: {len(strict_pass)}",
        f"- loss_le_1pp_pass_count: {len(loss_passes[1.0])}",
        f"- loss_le_2pp_pass_count: {len(loss_passes[2.0])}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    git_status_after = base.git_text(["status", "--short"])
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "SZ50/ZZ500 spread Layer 5 momentum decay",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_sz50_zz500_spread_layer3_target_vol.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": git_status_after,
        "scan_type": "fresh_layer5_momentum_decay_after_l4_rejected",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "score_peak_decay_recovery_warmup_scale_after_l3_target_vol",
        "baseline": {
            "lines": LINES,
            "pass_rule": "compare every decay candidate with same-line decay_off",
            "layer4_nav_defense": "rejected_by_user_review_as_too_weak",
        },
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "publication_dates": {"SZ50": base.SZ50_PUBLICATION_DATE, "ZZ500": base.ZZ500_PUBLICATION_DATE},
        },
        "decay_implementation": "active-trade score-strength peak, T-close state shifted one row to next execution; final turnover/cost recomputed",
        "decision": "layer5_momentum_decay_complete_pending_user_review",
        "stability_label": "momentum_decay_after_l4_rejected_patch_review",
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
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "SZ50/ZZ500 spread Layer 5 momentum decay" --parameter-group "score_peak_decay_recovery_warmup_scale_after_l3_target_vol" --repo . --entrypoint "scan_adk_sz50_zz500_spread_layer5_momentum_decay.py" --date 2026-06-12 --slug "adk_sz50_zz500_spread_long_only_v77_adk_spread_layer5_momentum_decay_after_l4_rejected"',
                'python -m py_compile "scan_adk_sz50_zz500_spread_layer5_momentum_decay.py"',
                'python "scan_adk_sz50_zz500_spread_layer5_momentum_decay.py"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "{RUN_DIR}" --decision "layer5_momentum_decay_complete_pending_user_review" --stability-label "momentum_decay_after_l4_rejected_patch_review"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict "{RUN_DIR}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print(
        "FULL_PASS_COUNT="
        f"{len(full_pass)} STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)} "
        f"LOSS1_COUNT={len(loss_passes[1.0])} LOSS2_COUNT={len(loss_passes[2.0])}"
    )
    print("BASELINES")
    print(baseline.to_string(index=False))
    print("STRICT_PASS_TOP")
    print(strict_pass[display_cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    print("LOSS_1_TOP")
    print(loss_passes[1.0][display_cols].head(20).to_string(index=False) if not loss_passes[1.0].empty else "NONE")
    print("LOSS_2_TOP")
    print(loss_passes[2.0][display_cols].head(20).to_string(index=False) if not loss_passes[2.0].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

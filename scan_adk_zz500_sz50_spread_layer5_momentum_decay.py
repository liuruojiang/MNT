"""Layer 5 score-peak momentum decay after Layer 4 NAV defense for ZZ500/SZ50.

Momentum decay is based on T-close signal score relative to the current active
trade's score peak, shifted to the next execution row. It is not a second NAV
drawdown gate.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_sz50_spread_layer3_target_vol as l3
import scan_adk_zz500_sz50_spread_layer4_nav_defense as l4
import scan_adk_zz500_sz50_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_sz50_spread_long_only_v77_adk_spread_layer5_momentum_decay_after_l4_nav"

LINES = [
    {
        "line": "width_primary_nav8p75_scale0p5",
        "line_role": "width_primary",
        "source_line": "width_primary_tv12_vw40_max1p25_db0p30",
        "family": "bias_momentum",
        "bias_ma": 115,
        "mom_day": 22,
        "weight_end": 2.75,
        "score_threshold": 2.0,
        "abs_ma": 70,
        "abs_threshold": -0.020,
        "target_vol": 0.12,
        "vol_window": 40,
        "max_leverage": 1.25,
        "scale_deadband": 0.30,
        "tv_enabled": True,
        "nav_threshold": 0.0875,
        "defense_scale": 0.50,
        "nav_enabled": True,
        "layer4_candidate": "l4_width_primary_tv12_vw40_max1p25_db0p30_nav8p75_scale0p5",
    },
    {
        "line": "width_confirm_nav8p75_scale0p5",
        "line_role": "width_confirmation",
        "source_line": "width_confirm_tv12_vw40_max1p25_db0p30",
        "family": "bias_momentum",
        "bias_ma": 115,
        "mom_day": 22,
        "weight_end": 2.75,
        "score_threshold": 2.0,
        "abs_ma": 65,
        "abs_threshold": -0.020,
        "target_vol": 0.12,
        "vol_window": 40,
        "max_leverage": 1.25,
        "scale_deadband": 0.30,
        "tv_enabled": True,
        "nav_threshold": 0.0875,
        "defense_scale": 0.50,
        "nav_enabled": True,
        "layer4_candidate": "l4_width_confirm_tv12_vw40_max1p25_db0p30_nav8p75_scale0p5",
    },
    {
        "line": "return_primary_nav8p75_scale0p5",
        "line_role": "return_primary_watch",
        "source_line": "return_primary_tv16_vw30_max1p25_db0p25",
        "family": "bias_momentum",
        "bias_ma": 115,
        "mom_day": 22,
        "weight_end": 2.75,
        "score_threshold": 2.0,
        "abs_ma": 70,
        "abs_threshold": -0.020,
        "target_vol": 0.16,
        "vol_window": 30,
        "max_leverage": 1.25,
        "scale_deadband": 0.25,
        "tv_enabled": True,
        "nav_threshold": 0.0875,
        "defense_scale": 0.50,
        "nav_enabled": True,
        "layer4_candidate": "l4_return_primary_tv16_vw30_max1p25_db0p25_nav8p75_scale0p5",
    },
    {
        "line": "return_confirm_nav10_scale0p5",
        "line_role": "return_confirmation_watch",
        "source_line": "return_confirm_tv16_vw30_max1p25_db0p25",
        "family": "bias_momentum",
        "bias_ma": 115,
        "mom_day": 22,
        "weight_end": 2.75,
        "score_threshold": 2.0,
        "abs_ma": 65,
        "abs_threshold": -0.020,
        "target_vol": 0.16,
        "vol_window": 30,
        "max_leverage": 1.25,
        "scale_deadband": 0.25,
        "tv_enabled": True,
        "nav_threshold": 0.10,
        "defense_scale": 0.50,
        "nav_enabled": True,
        "layer4_candidate": "l4_return_confirm_tv16_vw30_max1p25_db0p25_nav10_scale0p5",
    },
]

DECAY_THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]
RECOVERY_THRESHOLDS = [0.60, 0.70, 0.80, 0.90]
WARMUP_DAYS = [3, 5, 10]
DERISK_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def l4_base_returns(panel: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    sig = l3.line_signal(panel, line)
    l3_base = l4.l3_base_returns(panel, line)
    nav_df = l4.apply_nav_defense(l3_base, float(line["nav_threshold"]), float(line["defense_scale"]))
    nav_df["raw_signal"] = sig["raw_signal"].reindex(nav_df.index).fillna(0.0)
    nav_df["base_weight"] = nav_df["weight"]
    nav_df["nav_on"] = nav_df["nav_defense_on"]
    nav_df["nav_mult"] = nav_df["nav_defense_mult"]
    return nav_df


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
    score = d["score"].astype(float).to_numpy()
    state = np.ones(len(d), dtype=float)
    peak = np.nan
    active_days = 0
    in_decay = False
    for i in range(len(d)):
        if raw_signal[i] <= 0 or not np.isfinite(score[i]):
            peak = np.nan
            active_days = 0
            in_decay = False
            state[i] = 1.0
            continue
        active_days += 1
        peak = score[i] if not np.isfinite(peak) else max(peak, score[i])
        ratio = score[i] / peak if peak > 0 else 1.0
        if active_days >= int(warmup):
            if in_decay:
                if ratio >= float(recovery):
                    in_decay = False
                    peak = score[i]
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
            "nav_on": d["nav_on"],
            "nav_mult": d["nav_mult"],
            "decay_mult": decay_mult,
            "decay_on": decay_on.astype(int),
            "score": d["score"],
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
            "nav_days": 0.0,
            "nav_decay_overlap_days": 0.0,
            "avg_decay_mult": 1.0,
            "avg_active_decay_mult": 1.0,
        }
    active = d["base_weight"].abs() > 1e-12
    active_mult = d.loc[active, "decay_mult"]
    return {
        "decay_days": float(d["decay_on"].sum()),
        "decay_day_ratio": float(d["decay_on"].mean()),
        "nav_days": float(d["nav_on"].sum()),
        "nav_decay_overlap_days": float(((d["nav_on"] > 0) & (d["decay_on"] > 0)).sum()),
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
                        "best_nav_decay_overlap_days": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(
                len(passed) >= 4
                and passed["decay_threshold"].nunique() >= 2
                and passed["derisk_scale"].nunique() >= 2
            )
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
                    "best_nav_decay_overlap_days": best["nav_decay_overlap_days_full"],
                    "patch_like": patch_like,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["pass_rule", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def quadrant_summary(daily_all: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for candidate, d in daily_all.groupby("candidate"):
        nav_on = d["nav_on"].astype(float) > 0
        decay_on = d["decay_on"].astype(float) > 0
        for label, mask in {
            "Q00_nav0_decay0": ~nav_on & ~decay_on,
            "Q10_nav1_decay0": nav_on & ~decay_on,
            "Q01_nav0_decay1": ~nav_on & decay_on,
            "Q11_nav1_decay1": nav_on & decay_on,
        }.items():
            part = d.loc[mask]
            rows.append(
                {
                    "candidate": candidate,
                    "quadrant": label,
                    "days": int(mask.sum()),
                    "avg_weight": float(part["weight"].mean()) if not part.empty else np.nan,
                    "median_weight": float(part["weight"].median()) if not part.empty else np.nan,
                    "gross_return_sum": float(part["gross_return"].sum()) if not part.empty else 0.0,
                    "cost_sum": float(part["cost"].sum()) if not part.empty else 0.0,
                    "net_return_sum": float(part["return"].sum()) if not part.empty else 0.0,
                }
            )
    return pd.DataFrame(rows)


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def window_table(df: pd.DataFrame, n: int = 16) -> str:
    cols = ["candidate", "line", "decay_threshold", "recovery_threshold", "warmup_days", "derisk_scale", "decay_days_full", "nav_decay_overlap_days_full"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    mod, zz500, sz50, panel = l3.load_panel()
    base_by_line = {str(line["line"]): l4_base_returns(panel, line) for line in LINES}
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
                "nav_days",
                "nav_decay_overlap_days",
                "avg_decay_mult",
                "avg_active_decay_mult",
            ]:
                wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)
    quadrants = quadrant_summary(daily_all)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    quadrants.to_csv(RUN_DIR / "quadrant_summary.csv", index=False, encoding="utf-8-sig")

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

    cols = [
        "candidate",
        "line",
        "line_role",
        "decay_threshold",
        "recovery_threshold",
        "warmup_days",
        "derisk_scale",
        "decay_days_full",
        "nav_days_full",
        "nav_decay_overlap_days_full",
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
    baseline_cols = [c for c in cols if c in window_metrics.columns]
    record_lines = [
        "# ZZ500/SZ50 Layer 5 Momentum Decay After NAV Defense",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer5_momentum_decay_complete_pending_user_review`",
        "- stability: `momentum_decay_after_nav_patch_review`",
        "",
        "## Research Question",
        "Test score-peak momentum decay after the weak Layer 4 NAV-defense carry candidates.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
        "",
        "## Data Snapshot",
        f"- SZ50 publication date: {base.SZ50_PUBLICATION_DATE}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        f"- ZZ500 rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- SZ50 rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long ZZ500 / short SZ50; ratio is ZZ500/SZ50; spread return is ZZ500 pct_change minus SZ50 pct_change.",
        "- T close signal/state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Momentum decay uses T-close score divided by active-trade score peak, shifted one row to next execution.",
        "- No overheat, amount, or volume overlay is applied.",
        "",
        "## Decay Grid",
        f"- decay_threshold: {DECAY_THRESHOLDS}",
        f"- recovery_threshold: {RECOVERY_THRESHOLDS}, with recovery > decay.",
        f"- warmup_days: {WARMUP_DAYS}",
        f"- derisk_scale: {DERISK_SCALES}",
        "",
        "## Baselines",
        window_metrics[window_metrics["decay_enabled"] == False][baseline_cols].to_markdown(index=False),
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
        "Layer 5 completed and stopped for user review before any four-quadrant or later overlay layer.",
        "",
        "## User-Facing Summary",
        f"- candidates_scanned: {len(grid)}",
        f"- full_baseline_pass_count: {len(full_pass)}",
        f"- full_and_5y_pass_count: {len(strict_pass)}",
        f"- loss_le_1pp_pass_count: {len(loss_passes[1.0])}",
        f"- loss_le_2pp_pass_count: {len(loss_passes[2.0])}",
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
        "implementation_anchor": "scan_adk_zz500_sz50_spread_layer4_nav_defense.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status,
        "git_status_after": git_status,
        "scan_type": "fresh_layer5_momentum_decay_after_nav",
        "parameter_group": "score_peak_decay_recovery_warmup_scale_after_nav",
        "baseline": {"lines": LINES, "pass_rule": "compare every decay candidate with same-line decay_off"},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/state -> T+1 close-to-close return",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
            "publication_dates": {"SZ50": base.SZ50_PUBLICATION_DATE, "ZZ500": base.ZZ500_PUBLICATION_DATE},
        },
        "decay_implementation": "active-trade score peak, T-close state shifted one row to next execution; final turnover/cost recomputed",
        "decision": "layer5_momentum_decay_complete_pending_user_review",
        "stability_label": "momentum_decay_after_nav_patch_review",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "quadrant_summary": str(RUN_DIR / "quadrant_summary.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "full_baseline_pass_candidates": str(RUN_DIR / "full_baseline_pass_candidates.csv"),
            "full_and_5y_pass_candidates": str(RUN_DIR / "full_and_5y_pass_candidates.csv"),
            "dd_first_pass_loss_le_0p5pp": str(RUN_DIR / "dd_first_pass_loss_le_0p5pp.csv"),
            "dd_first_pass_loss_le_1p0pp": str(RUN_DIR / "dd_first_pass_loss_le_1p0pp.csv"),
            "dd_first_pass_loss_le_2p0pp": str(RUN_DIR / "dd_first_pass_loss_le_2p0pp.csv"),
            "quadrant_summary": str(RUN_DIR / "quadrant_summary.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "\n".join(
            [
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "ZZ500/SZ50 spread Layer 5 momentum decay" --parameter-group "score_peak_decay_recovery_warmup_scale_after_nav" --repo . --entrypoint "scan_adk_zz500_sz50_spread_layer5_momentum_decay.py" --date 2026-06-12 --slug "adk_zz500_sz50_spread_long_only_v77_adk_spread_layer5_momentum_decay_after_l4_nav"',
                'python -m py_compile "scan_adk_zz500_sz50_spread_layer5_momentum_decay.py"',
                'python "scan_adk_zz500_sz50_spread_layer5_momentum_decay.py"',
                'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "<run_folder>" --decision "layer5_momentum_decay_complete_pending_user_review" --stability-label "momentum_decay_after_nav_patch_review" --repo .',
                'python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict "<run_folder>"',
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
    print(window_metrics[window_metrics.decay_enabled == False][baseline_cols].to_string(index=False))
    print("STRICT_PASS_TOP")
    print(strict_pass[baseline_cols].head(20).to_string(index=False) if not strict_pass.empty else "NONE")
    print("LOSS_1_TOP")
    print(loss_passes[1.0][baseline_cols].head(20).to_string(index=False) if not loss_passes[1.0].empty else "NONE")
    print("LOSS_2_TOP")
    print(loss_passes[2.0][baseline_cols].head(20).to_string(index=False) if not loss_passes[2.0].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

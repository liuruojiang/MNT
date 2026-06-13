"""Layer 5 momentum-decay scan for long CYB / short ZZ500.

Inputs are selected Layer 4 NAV-defense carry candidates. This layer tests only
score-peak momentum decay inside active holding segments.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_zz500_spread_layer2_score_abs_filter as l2
import scan_adk_cyb_zz500_spread_layer3_target_vol as l3
import scan_adk_cyb_zz500_spread_layer4_nav_defense as l4
import scan_adk_cyb_zz500_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_cyb_zz500_spread_long_only_v77_adk_spread_layer5_momentum_decay_l4_carry"

L4_INPUTS = [
    {
        **l4.L3_INPUTS[0],
        "layer4_anchor": "return_nav3_scale0p5",
        "layer4_candidate": "l4_return_tv10_rv120_max1p5_floor0p5_rel15_navddm3_scale0p5",
        "nav_dd_threshold": -0.03,
        "defense_scale": 0.5,
    },
    {
        **l4.L3_INPUTS[1],
        "layer4_anchor": "primary_nav3_scale0p5",
        "layer4_candidate": "l4_primary_tv10_rv120_max1p5_floor0p5_rel15_navddm3_scale0p5",
        "nav_dd_threshold": -0.03,
        "defense_scale": 0.5,
    },
    {
        **l4.L3_INPUTS[2],
        "layer4_anchor": "confirm_nav3_scale0p5",
        "layer4_candidate": "l4_confirm_tv10_rv120_max1p5_floor0p5_rel15_navddm3_scale0p5",
        "nav_dd_threshold": -0.03,
        "defense_scale": 0.5,
    },
    {
        **l4.L3_INPUTS[3],
        "layer4_anchor": "defensive_nav4_scale0",
        "layer4_candidate": "l4_defensive_tv10_rv40_max2_floor0_abs20_navddm4_scale0",
        "nav_dd_threshold": -0.04,
        "defense_scale": 0.0,
    },
    {
        **l4.L3_INPUTS[3],
        "layer4_anchor": "defensive_nav3_scale0p5",
        "layer4_candidate": "l4_defensive_tv10_rv40_max2_floor0_abs20_navddm3_scale0p5",
        "nav_dd_threshold": -0.03,
        "defense_scale": 0.5,
    },
]

DECAY_RATIOS = [0.35, 0.45, 0.55, 0.65, 0.75, 0.85]
RECOVERY_RATIOS = [0.75, 0.85, 0.95]
CONFIRM_DAYS = [1, 2, 3]
DERISK_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0, 3.0]
WINDOW_SEGMENTS = ["full", "last_10y", "last_5y", "last_3y", "last_1y"]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def l4_base_frame(
    panel: pd.DataFrame,
    item: dict[str, object],
    scores: dict[str, pd.Series],
    r2s: dict[str, pd.Series],
    abs_bias: dict[int, pd.Series],
) -> pd.DataFrame:
    l2_frame = l3.build_l2_signal_frame(panel, item, scores, r2s, abs_bias)
    l3_frame = l3.apply_target_vol(l2_frame, {**item, "target_vol_enabled": True}).copy()
    l3_frame["spread_return"] = l2_frame["spread_return"].reindex(l3_frame.index)
    nav_frame = l4.apply_nav_defense(l3_frame, float(item["nav_dd_threshold"]), float(item["defense_scale"])).copy()
    nav_frame["score"] = l2_frame["score"].reindex(nav_frame.index)
    nav_frame["r2"] = l2_frame["r2"].reindex(nav_frame.index)
    nav_frame["spread_return"] = l2_frame["spread_return"].reindex(nav_frame.index)
    nav_frame["base_weight"] = nav_frame["weight"]
    nav_frame["nav_on"] = nav_frame["defense_state"]
    nav_frame["nav_mult"] = nav_frame["defense_multiplier"]
    return nav_frame


def decay_multiplier_series(
    raw_signal: pd.Series,
    score: pd.Series,
    decay_ratio: float,
    recovery_ratio: float,
    confirm_days: int,
    derisk_scale: float,
) -> pd.DataFrame:
    active = raw_signal.astype(float).to_numpy() > 0.5
    scores = score.astype(float).to_numpy()
    multiplier = np.ones(len(scores), dtype=float)
    peak = np.nan
    in_decay = False
    need_new_peak = False
    below_count = 0
    ratio_values = np.full(len(scores), np.nan, dtype=float)
    peak_values = np.full(len(scores), np.nan, dtype=float)
    state_values = np.zeros(len(scores), dtype=float)
    trigger_values = np.zeros(len(scores), dtype=float)
    recovery_values = np.zeros(len(scores), dtype=float)

    for i, is_active in enumerate(active):
        s = scores[i]
        if (not is_active) or (not np.isfinite(s)) or s <= 0.0:
            peak = np.nan
            in_decay = False
            need_new_peak = False
            below_count = 0
            multiplier[i] = 1.0
            continue
        if not np.isfinite(peak):
            peak = s
            in_decay = False
            need_new_peak = False
            below_count = 0
        elif s > peak:
            peak = s
            if need_new_peak:
                need_new_peak = False
        ratio = s / peak if peak > 0 else np.nan
        ratio_values[i] = ratio
        peak_values[i] = peak

        if in_decay:
            if ratio >= recovery_ratio:
                in_decay = False
                need_new_peak = True
                below_count = 0
                recovery_values[i] = 1.0
        elif not need_new_peak:
            below_count = below_count + 1 if ratio <= decay_ratio else 0
            if below_count >= confirm_days:
                in_decay = True
                trigger_values[i] = 1.0
        else:
            below_count = 0

        state_values[i] = 1.0 if in_decay else 0.0
        multiplier[i] = derisk_scale if in_decay else 1.0

    return pd.DataFrame(
        {
            "decay_multiplier": multiplier,
            "score_peak": peak_values,
            "score_peak_ratio": ratio_values,
            "decay_state": state_values,
            "decay_trigger": trigger_values,
            "decay_recovery": recovery_values,
        },
        index=score.index,
    )


def apply_momentum_decay(
    base_frame: pd.DataFrame,
    decay_ratio: float,
    recovery_ratio: float,
    confirm_days: int,
    derisk_scale: float,
) -> pd.DataFrame:
    decay = decay_multiplier_series(
        base_frame["raw_signal"],
        base_frame["score"],
        decay_ratio,
        recovery_ratio,
        confirm_days,
        derisk_scale,
    )
    exec_multiplier = decay["decay_multiplier"].shift(1).fillna(1.0)
    final_weight = base_frame["base_weight"] * exec_multiplier
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = final_weight * base_frame["spread_return"].fillna(0.0)
    ret = gross_return - cost
    decay_on = (exec_multiplier < 1.0 - 1e-12) & (base_frame["base_weight"].abs() > 1e-12)
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "base_weight": base_frame["base_weight"],
            "raw_signal": base_frame["raw_signal"],
            "score": base_frame["score"],
            "r2": base_frame["r2"],
            "nav_on": base_frame["nav_on"],
            "nav_mult": base_frame["nav_mult"],
            "decay_on": decay_on.astype(float),
            "spread_return": base_frame["spread_return"],
            **decay,
        },
        index=base_frame.index,
    )


def candidate_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for item in L4_INPUTS:
        grid.append(
            {
                **item,
                "candidate": f"l5_{item['layer4_anchor']}_decay_off",
                "decay_ratio": 0.0,
                "recovery_ratio": 0.0,
                "confirm_days": 0,
                "derisk_scale": 1.0,
                "momentum_decay_enabled": False,
            }
        )
        for decay_ratio in DECAY_RATIOS:
            for recovery_ratio in RECOVERY_RATIOS:
                if recovery_ratio <= decay_ratio:
                    continue
                for confirm_days in CONFIRM_DAYS:
                    for derisk_scale in DERISK_SCALES:
                        grid.append(
                            {
                                **item,
                                "candidate": (
                                    f"l5_{item['layer4_anchor']}_decay{fmt_num(decay_ratio, pct=True)}"
                                    f"_rec{fmt_num(recovery_ratio, pct=True)}"
                                    f"_c{confirm_days}_scale{fmt_num(derisk_scale)}"
                                ),
                                "decay_ratio": decay_ratio,
                                "recovery_ratio": recovery_ratio,
                                "confirm_days": confirm_days,
                                "derisk_scale": derisk_scale,
                                "momentum_decay_enabled": True,
                            }
                        )
    return grid


def extra_metrics(result: pd.DataFrame) -> dict[str, float]:
    decay_days = result["decay_on"] > 0.5
    return {
        "decay_day_ratio_full": float(decay_days.mean()),
        "trigger_count_full": int(result["decay_trigger"].sum()),
        "recovery_count_full": int(result["decay_recovery"].sum()),
        "avg_decay_multiplier_full": float(result["decay_multiplier"].mean()),
        "avg_multiplier_when_decay_full": float(result.loc[decay_days, "decay_multiplier"].mean())
        if decay_days.any()
        else 1.0,
        "nav_day_ratio_full": float((result["nav_on"] > 0.5).mean()),
        "nav_decay_overlap_ratio_full": float(((result["nav_on"] > 0.5) & decay_days).mean()),
        "avg_weight_full": float(result["weight"].mean()),
        "avg_abs_weight_full": float(result["weight"].abs().mean()),
    }


def add_baselines_and_flags(window_metrics: pd.DataFrame) -> pd.DataFrame:
    out = window_metrics.copy()
    baselines = out[~out["momentum_decay_enabled"]].set_index("layer4_anchor")
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
        "avg_turnover_full",
        "cost_total_full",
    ]:
        out[f"base_{col}"] = out["layer4_anchor"].map(baselines[col])
    for segment in WINDOW_SEGMENTS:
        out[f"{segment}_ann_loss_pp"] = (out[f"base_ann_return_{segment}"] - out[f"ann_return_{segment}"]) * 100.0
        out[f"{segment}_dd_improve_pp"] = (out[f"max_dd_{segment}"] - out[f"base_max_dd_{segment}"]) * 100.0
    out["turnover_delta_full"] = out["avg_turnover_full"] - out["base_avg_turnover_full"]
    out["cost_delta_full"] = out["cost_total_full"] - out["base_cost_total_full"]
    out["material_decay"] = out["decay_day_ratio_full"] >= 0.01
    out["pass_full_ann_dd"] = (
        out["momentum_decay_enabled"]
        & out["material_decay"]
        & (out["ann_return_full"] >= out["base_ann_return_full"] - 1e-12)
        & (out["max_dd_full"] >= out["base_max_dd_full"] - 1e-12)
    )
    out["pass_full_5y_ann_dd"] = (
        out["pass_full_ann_dd"]
        & (out["ann_return_last_5y"] >= out["base_ann_return_last_5y"] - 1e-12)
        & (out["max_dd_last_5y"] >= out["base_max_dd_last_5y"] - 1e-12)
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            out["momentum_decay_enabled"]
            & out["material_decay"]
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["last_5y_dd_improve_pp"] >= -1e-12)
        )
    return out


def width_summary(window_metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    source = window_metrics[window_metrics["momentum_decay_enabled"]].copy()
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for anchor, group in source.groupby("layer4_anchor"):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "loss_tier_pp": tier,
                        "layer4_anchor": anchor,
                        "pass_count": 0,
                        "decay_ratio_count": 0,
                        "recovery_ratio_count": 0,
                        "confirm_count": 0,
                        "scale_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_decay_day_ratio": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            rows.append(
                {
                    "loss_tier_pp": tier,
                    "layer4_anchor": anchor,
                    "pass_count": int(len(passed)),
                    "decay_ratio_count": int(passed["decay_ratio"].nunique()),
                    "recovery_ratio_count": int(passed["recovery_ratio"].nunique()),
                    "confirm_count": int(passed["confirm_days"].nunique()),
                    "scale_count": int(passed["derisk_scale"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "best_full_ann_loss_pp": float(best["full_ann_loss_pp"]),
                    "best_full_dd_improve_pp": float(best["full_dd_improve_pp"]),
                    "best_decay_day_ratio": float(best["decay_day_ratio_full"]),
                    "patch_like": bool(
                        len(passed) >= 6
                        and passed["decay_ratio"].nunique() >= 2
                        and passed["recovery_ratio"].nunique() >= 2
                        and passed["derisk_scale"].nunique() >= 2
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def select_carry(window_metrics: pd.DataFrame, ridge: pd.DataFrame) -> pd.DataFrame:
    strict = window_metrics[
        window_metrics["momentum_decay_enabled"]
        & window_metrics["pass_full_5y_ann_dd"]
        & window_metrics["material_decay"]
    ].copy()
    if not strict.empty:
        strict["carry_score"] = (
            strict["ann_return_full"] * 20
            + strict["full_dd_improve_pp"].clip(lower=0, upper=20)
            + strict["last_5y_dd_improve_pp"].clip(lower=0, upper=20) * 0.6
            - strict["full_ann_loss_pp"].clip(lower=-5, upper=5) * 0.5
        )
        strict_keep = strict.sort_values(["carry_score", "ann_return_full"], ascending=[False, False]).groupby("layer4_anchor").head(1)
    else:
        strict_keep = pd.DataFrame()

    patch = ridge[(ridge["patch_like"]) & (ridge["pass_count"] > 0)].head(8)
    pools = []
    for _, row in patch.iterrows():
        tag = str(float(row["loss_tier_pp"])).replace(".", "p")
        pools.append(window_metrics[(window_metrics["layer4_anchor"] == row["layer4_anchor"]) & window_metrics[f"pass_loss_le_{tag}pp"]])
    pool = pd.concat(pools, ignore_index=True) if pools else pd.DataFrame()
    if not pool.empty:
        pool["carry_score"] = (
            pool["full_dd_improve_pp"].clip(lower=0, upper=30)
            + pool["last_5y_dd_improve_pp"].clip(lower=-5, upper=20) * 0.5
            - pool["full_ann_loss_pp"].clip(lower=-5, upper=10) * 0.7
            + pool["ann_return_full"] * 10
        )
        dd_keep = pool.sort_values(["carry_score", "ann_return_full"], ascending=[False, False]).groupby("layer4_anchor").head(2)
    else:
        dd_keep = pd.DataFrame()

    if strict_keep.empty and dd_keep.empty:
        unchanged = window_metrics[~window_metrics["momentum_decay_enabled"]].copy()
        unchanged["carry_score"] = unchanged["ann_return_full"] * 10 + unchanged["max_dd_full"].clip(lower=-0.30) * 2
        return unchanged.sort_values(["ann_return_full", "max_dd_full"], ascending=[False, False]).head(10)
    return pd.concat([strict_keep, dd_keep], ignore_index=True).drop_duplicates("candidate").head(10)


def window_table(df: pd.DataFrame, n: int = 10) -> str:
    cols = [
        "candidate",
        "layer4_anchor",
        "role",
        "decay_ratio",
        "recovery_ratio",
        "confirm_days",
        "derisk_scale",
        "decay_day_ratio_full",
    ]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_") or col in {
            "decay_ratio",
            "recovery_ratio",
            "decay_day_ratio_full",
        }:
            display[col] = display[col].map(lambda x: pct(float(x)) if pd.notna(x) else "")
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, cyb, zz500, panel = l2.load_panel()
    scores, r2s, abs_bias = l2.precompute(panel)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    base_frames = {
        str(item["layer4_anchor"]): l4_base_frame(panel, item, scores, r2s, abs_bias)
        for item in L4_INPUTS
    }
    grid = candidate_grid()
    long_rows = []
    wide_rows = []
    result_cache: dict[str, pd.DataFrame] = {}

    for candidate in grid:
        anchor = str(candidate["layer4_anchor"])
        base_frame = base_frames[anchor]
        if candidate["momentum_decay_enabled"]:
            result = apply_momentum_decay(
                base_frame,
                float(candidate["decay_ratio"]),
                float(candidate["recovery_ratio"]),
                int(candidate["confirm_days"]),
                float(candidate["derisk_scale"]),
            )
        else:
            result = apply_momentum_decay(base_frame, 0.0, 1.0, 999999, 1.0)
            result["decay_state"] = 0.0
            result["decay_trigger"] = 0.0
            result["decay_recovery"] = 0.0
            result["decay_multiplier"] = 1.0
            result["decay_on"] = 0.0

        extra = extra_metrics(result)
        wide = {**candidate, **extra}
        for segment, years in base.SEGMENTS:
            metrics = base.metrics_for_segment(result, segment, years)
            long_rows.append({**candidate, **extra, **metrics})
            for key in [
                "ann_return",
                "max_dd",
                "sharpe_repo",
                "avg_weight",
                "avg_turnover",
                "holding_day_ratio",
                "cost_total",
            ]:
                wide[f"{key}_{segment}"] = metrics[key]
        wide_rows.append(wide)
        if not candidate["momentum_decay_enabled"]:
            result_cache[str(candidate["candidate"])] = result

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = width_summary(window_metrics)
    strict_full = window_metrics[
        window_metrics["momentum_decay_enabled"] & window_metrics["pass_full_ann_dd"] & window_metrics["material_decay"]
    ].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
    strict_full_5y = window_metrics[
        window_metrics["momentum_decay_enabled"] & window_metrics["pass_full_5y_ann_dd"] & window_metrics["material_decay"]
    ].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
    top_tier: dict[float, pd.DataFrame] = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(
            ["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]
        )
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_tier[tier] = passed
    carry = select_carry(window_metrics, ridge)

    selected_names = set(window_metrics[~window_metrics["momentum_decay_enabled"]]["candidate"].astype(str).tolist())
    for df in [strict_full, strict_full_5y, carry, *top_tier.values()]:
        if not df.empty:
            selected_names.update(df.head(10)["candidate"].astype(str).tolist())
    selected_lookup = {
        str(row["candidate"]): row.to_dict()
        for _, row in window_metrics.iterrows()
        if str(row["candidate"]) in selected_names
    }
    for name, candidate in selected_lookup.items():
        if name in result_cache:
            continue
        result_cache[name] = apply_momentum_decay(
            base_frames[str(candidate["layer4_anchor"])],
            float(candidate["decay_ratio"]),
            float(candidate["recovery_ratio"]),
            int(candidate["confirm_days"]),
            float(candidate["derisk_scale"]),
        )

    daily_rows = []
    for name, result in result_cache.items():
        out = result.copy()
        out["nav"] = (1.0 + out["return"]).cumprod()
        out["candidate"] = name
        daily_rows.append(out.reset_index(names="date"))
    daily = pd.concat(daily_rows, ignore_index=True) if daily_rows else pd.DataFrame()

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    strict_full.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_full_5y.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")

    decision = "layer5_momentum_decay_complete_pending_user_review"
    stability = "momentum_decay_after_nav_width_review"
    record_lines = [
        "# CYB/ZZ500 Layer 5 Momentum-Decay Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        f"- decision: `{decision}`",
        f"- stability: `{stability}`",
        "",
        "## Research Question",
        "Scan score-peak momentum decay after selected Layer 4 NAV-defense carry candidates.",
        "",
        "## Layer Inputs",
        "- Layer 4 inputs:",
        *[
            f"  - `{item['layer4_anchor']}` from `{item['layer4_candidate']}`: role={item['role']}, nav_dd={item['nav_dd_threshold']:.1%}, nav_scale={item['defense_scale']}."
            for item in L4_INPUTS
        ],
        f"- Decay ratios: `{', '.join(f'{x:.0%}' for x in DECAY_RATIOS)}`.",
        f"- Recovery ratios: `{', '.join(f'{x:.0%}' for x in RECOVERY_RATIOS)}`.",
        f"- Confirm days: `{', '.join(str(x) for x in CONFIRM_DAYS)}`.",
        f"- Derisk scales: `{', '.join(str(x) for x in DERISK_SCALES)}`.",
        "",
        "## Implementation Anchor",
        "- Imports data loader and signal construction from Layer 2, target-vol construction from Layer 3, and NAV defense from Layer 4.",
        "- Momentum decay uses `score / active_trade_score_peak`, not NAV drawdown.",
        "- Score peak is tracked only while the Layer 2 raw signal is active.",
        "- Trigger is evaluated at T close and shifted to T+1 execution through the final weight.",
        "- After recovery, a new score peak is required before another decay cycle can trigger in the same trade.",
        "- Final turnover, costs, returns, NAV, and drawdown are recomputed after decay.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research with two-leg commissions, excluding futures basis, financing, borrow, and short locate costs.",
        "- Source-change rule: `research_only_new_scan_script`.",
        "",
        "## Data Snapshot",
        f"- CYB publication date: {base.CYB_PUBLICATION_DATE}; local rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start rule: latest actual index publication date among the two legs.",
        "- Adjustment mode: price index close from local official cache, no total-return substitution.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal/target-vol/NAV/score-peak decay -> T+1 close-to-close spread return.",
        "- Return stream: final scale times CYB close-to-close return minus ZZ500 close-to-close return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- No overheat, amount, or volume overlay is applied.",
        "",
        "## Full-Sample Results",
        window_table(strict_full, 12) if not strict_full.empty else "No momentum-decay candidates passed full-sample annual-return and drawdown non-underperformance with material decay.",
        "",
        "## Window Results",
        window_table(strict_full_5y, 12) if not strict_full_5y.empty else "No momentum-decay candidates passed strict full+5Y annual-return and drawdown non-underperformance with material decay.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 5 momentum-decay scan completed. Stop for user review before Layer 6 interaction or later overlays.",
        "",
        "## User-Facing Summary",
        f"- strict full pass count: {len(strict_full)}",
        f"- strict full+5Y pass count: {len(strict_full_5y)}",
        f"- loss<=0.5pp pass count: {len(top_tier[0.5])}",
        f"- loss<=1pp pass count: {len(top_tier[1.0])}",
        f"- loss<=2pp pass count: {len(top_tier[2.0])}",
        f"- loss<=3pp pass count: {len(top_tier[3.0])}",
        "",
        "## Next-Layer Carry Candidates",
        window_table(carry, 10) if not carry.empty else "No carry candidate selected.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "CYB/ZZ500 spread Layer 5 momentum decay",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_cyb_zz500_spread_layer4_nav_defense.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "layer5_momentum_decay",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "score_peak_decay_recovery_derisk",
        "baseline": {"layer4_inputs": L4_INPUTS, "loss_tiers_pp": LOSS_TIERS},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/target-vol/NAV/decay -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "momentum_decay_model": {
            "strength": "score / active trade score peak",
            "trigger": "ratio <= decay_ratio for confirm_days",
            "recovery": "ratio >= recovery_ratio; then require a new score peak before another decay cycle",
            "action": "multiply final Layer 4 exposure by derisk_scale after one-row execution shift",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "cyb": {
                "secid": str(mod.CN_DK_CYB_SECID),
                "publication_date": base.CYB_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_CYB_SECID))),
                "rows": int(len(cyb)),
                "start": str(cyb.index.min().date()),
                "end": str(cyb.index.max().date()),
            },
            "zz500": {
                "secid": str(mod.CN_DK_ZZ500_SECID),
                "publication_date": base.ZZ500_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_ZZ500_SECID))),
                "rows": int(len(zz500)),
                "start": str(zz500.index.min().date()),
                "end": str(zz500.index.max().date()),
            },
            "formal": {
                "rows": int(len(panel)),
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
                "start_rule": "latest actual publication/listing date among participants",
                "ratio": "CYB / ZZ500",
                "return_stream": "CYB pct_change - ZZ500 pct_change",
            },
        },
        "decision": decision,
        "stability_label": stability,
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
            "carry_candidates": str(RUN_DIR / "carry_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"CYB/ZZ500 spread Layer 5 momentum decay\" --parameter-group \"score_peak_decay_recovery_derisk\" --repo . --entrypoint \"scan_adk_cyb_zz500_spread_layer5_momentum_decay.py\" --date 2026-06-12 --slug \"adk_cyb_zz500_spread_long_only_v77_adk_spread_layer5_momentum_decay_l4_carry\"\n"
        "python -m py_compile \"scan_adk_cyb_zz500_spread_layer5_momentum_decay.py\"\n"
        "python \"scan_adk_cyb_zz500_spread_layer5_momentum_decay.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"{decision}\" --stability-label \"{stability}\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict \"{RUN_DIR}\"\n",
        encoding="utf-8",
    )

    cols = [
        "candidate",
        "layer4_anchor",
        "role",
        "decay_ratio",
        "recovery_ratio",
        "confirm_days",
        "derisk_scale",
        "decay_day_ratio_full",
        "ann_return_full",
        "max_dd_full",
        "full_ann_loss_pp",
        "full_dd_improve_pp",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "last_5y_ann_loss_pp",
        "last_5y_dd_improve_pp",
        "ann_return_last_1y",
        "max_dd_last_1y",
    ]
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_tier[tier])}")
        print(top_tier[tier][cols].head(12).to_string(index=False) if not top_tier[tier].empty else "NONE")
    print(f"STRICT_FULL_PASS_COUNT={len(strict_full)}")
    print(strict_full[cols].head(12).to_string(index=False) if not strict_full.empty else "NONE")
    print(f"STRICT_FULL_5Y_PASS_COUNT={len(strict_full_5y)}")
    print(strict_full_5y[cols].head(12).to_string(index=False) if not strict_full_5y.empty else "NONE")
    print("CARRY")
    print(carry[cols].head(12).to_string(index=False) if not carry.empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

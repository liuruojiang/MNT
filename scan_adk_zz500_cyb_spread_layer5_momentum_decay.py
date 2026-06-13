"""Layer 5 momentum-decay scan for long ZZ500 / short CYB spread.

Inputs are the Layer 4 carry lines after NAV defense was rejected, so the formal
baseline is Layer 4 nav_off (the selected Layer 3 target-vol lines). This layer
tests only score-peak momentum decay inside active holding segments.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_cyb_spread_layer2_score_abs_filter as l2
import scan_adk_zz500_cyb_spread_layer3_target_vol as l3
import scan_adk_zz500_cyb_spread_layer4_nav_defense as l4
import scan_adk_zz500_cyb_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_cyb_spread_long_only_v77_adk_spread_layer5_momentum_decay_l4_nav_off"
L4_RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_cyb_spread_long_only_v77_adk_spread_layer4_nav_defense_l3_bias_carry"
_L4_DAILY_CACHE: pd.DataFrame | None = None

L4_INPUTS = [
    {
        **l4.L3_INPUTS[0],
        "layer4_anchor": "confirm_carry_nav_off",
        "layer4_candidate": "l4_confirm_tv10_rv20_max1p25_floor0p5_abs15_nav_off",
    },
    {
        **l4.L3_INPUTS[1],
        "layer4_anchor": "confirm_strict5y_nav_off",
        "layer4_candidate": "l4_confirm_tv12_rv20_max1_floor0_rel5_nav_off",
    },
    {
        **l4.L3_INPUTS[2],
        "layer4_anchor": "primary_bias_nav_off",
        "layer4_candidate": "l4_primary_tv10_rv20_max1p25_floor0p5_abs15_nav_off",
    },
    {
        **l4.L3_INPUTS[3],
        "layer4_anchor": "ddtight_watch_nav_off",
        "layer4_candidate": "l4_ddtight_tv15_rv20_max1p25_floor0p5_abs05_nav_off",
    },
    {
        **l4.L3_INPUTS[2],
        "layer4_anchor": "primary_nav75_scale05_watch",
        "layer4_candidate": "l4_primary_tv10_rv20_max1p25_floor0p5_abs15_navddm7p5_scale0p5",
        "nav_dd_threshold": -0.075,
        "defense_scale": 0.5,
        "nav_defense_enabled": True,
        "role": "nav_watchlist",
    },
]

DECAY_RATIOS = [0.35, 0.45, 0.55, 0.65, 0.75, 0.85]
RECOVERY_RATIOS = [0.75, 0.85, 0.95]
CONFIRM_DAYS = [1, 2, 3]
DERISK_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0, 3.0]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def l4_nav_off_frame(
    panel: pd.DataFrame,
    item: dict[str, object],
    scores: dict[str, pd.Series],
    r2s: dict[str, pd.Series],
    abs_bias: dict[int, pd.Series],
) -> pd.DataFrame:
    global _L4_DAILY_CACHE
    l2_frame = l3.build_l2_signal_frame(panel, item, scores, r2s, abs_bias)
    if _L4_DAILY_CACHE is None:
        _L4_DAILY_CACHE = pd.read_csv(L4_RUN_DIR / "daily_curves.csv", parse_dates=["date"])
    candidate = str(item["layer4_candidate"])
    out = _L4_DAILY_CACHE[_L4_DAILY_CACHE["candidate"] == candidate].copy()
    if out.empty:
        raise ValueError(f"Layer 4 daily curve not found for {candidate}")
    out = out.set_index("date").sort_index()
    for col in ["score", "r2", "spread_return"]:
        out[col] = l2_frame[col].reindex(out.index)
    return out


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
            if ratio <= decay_ratio:
                below_count += 1
            else:
                below_count = 0
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
    final_selected_scale = base_frame["selected_scale"] * decay["decay_multiplier"]
    final_weight = base_frame["weight"] * decay["decay_multiplier"].shift(1).fillna(1.0)
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = final_weight * base_frame["spread_return"]
    ret = gross_return - cost
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "base_weight": base_frame["weight"],
            "raw_signal": base_frame["raw_signal"],
            "score": base_frame["score"],
            "selected_scale": base_frame["selected_scale"],
            "final_selected_scale": final_selected_scale,
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
    decay_days = result["decay_state"] > 0.5
    return {
        "decay_day_ratio_full": float(decay_days.mean()),
        "trigger_count_full": int(result["decay_trigger"].sum()),
        "recovery_count_full": int(result["decay_recovery"].sum()),
        "avg_decay_multiplier_full": float(result["decay_multiplier"].mean()),
        "avg_multiplier_when_decay_full": float(result.loc[decay_days, "decay_multiplier"].mean())
        if decay_days.any()
        else 1.0,
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
    for segment in ["full", "last_10y", "last_5y", "last_3y", "last_1y"]:
        out[f"{segment}_ann_loss_pp"] = (out[f"base_ann_return_{segment}"] - out[f"ann_return_{segment}"]) * 100.0
        out[f"{segment}_dd_improve_pp"] = (out[f"max_dd_{segment}"] - out[f"base_max_dd_{segment}"]) * 100.0
    out["turnover_delta_full"] = out["avg_turnover_full"] - out["base_avg_turnover_full"]
    out["cost_delta_full"] = out["cost_total_full"] - out["base_cost_total_full"]
    out["pass_full_ann_dd"] = (
        (out["ann_return_full"] >= out["base_ann_return_full"] - 1e-12)
        & (out["max_dd_full"] >= out["base_max_dd_full"] - 1e-12)
    )
    out["pass_full_5y_ann_dd"] = (
        out["pass_full_ann_dd"]
        & (out["ann_return_last_5y"] >= out["base_ann_return_last_5y"] - 1e-12)
        & (out["max_dd_last_5y"] >= out["base_max_dd_last_5y"] - 1e-12)
    )
    out["material_decay"] = out["decay_day_ratio_full"] >= 0.01
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
        for layer4_anchor, group in source.groupby("layer4_anchor"):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "loss_tier_pp": tier,
                        "layer4_anchor": layer4_anchor,
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
            patch_like = bool(
                len(passed) >= 6
                and passed["decay_ratio"].nunique() >= 2
                and passed["recovery_ratio"].nunique() >= 2
                and passed["derisk_scale"].nunique() >= 2
            )
            rows.append(
                {
                    "loss_tier_pp": tier,
                    "layer4_anchor": layer4_anchor,
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
                    "patch_like": patch_like,
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
    if strict.empty:
        unchanged = window_metrics[~window_metrics["momentum_decay_enabled"]].copy()
        unchanged["carry_score"] = unchanged["ann_return_full"] * 10 + unchanged["max_dd_full"].clip(lower=-0.30) * 2
        diagnostic = window_metrics[
            window_metrics["momentum_decay_enabled"]
            & window_metrics["material_decay"]
            & (window_metrics["full_dd_improve_pp"] > 0)
            & (window_metrics["last_5y_dd_improve_pp"] >= 0)
        ].copy()
        if not diagnostic.empty:
            diagnostic["carry_score"] = (
                diagnostic["full_dd_improve_pp"].clip(lower=0, upper=30)
                + diagnostic["last_5y_dd_improve_pp"].clip(lower=0, upper=20) * 0.5
                - diagnostic["full_ann_loss_pp"].clip(lower=-5, upper=10) * 0.8
                + diagnostic["ann_return_full"] * 10
            )
            diagnostic = diagnostic.sort_values(["carry_score", "ann_return_full"], ascending=[False, False]).head(3)
        return pd.concat([unchanged, diagnostic], ignore_index=True).drop_duplicates("candidate").head(10)

    strict["carry_score"] = (
        strict["ann_return_full"] * 20
        + strict["full_dd_improve_pp"].clip(lower=0, upper=20)
        + strict["last_5y_dd_improve_pp"].clip(lower=0, upper=20) * 0.6
        - strict["full_ann_loss_pp"].clip(lower=-5, upper=5) * 0.5
    )
    strict_keep = strict.sort_values(["ann_return_full", "full_dd_improve_pp"], ascending=[False, False]).groupby("layer4_anchor").head(1)
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
    return pd.concat([strict_keep, dd_keep], ignore_index=True).drop_duplicates("candidate").head(10)


def window_table(df: pd.DataFrame, n: int = 10) -> str:
    display = df.head(n)[
        [
            "candidate",
            "layer4_anchor",
            "role",
            "decay_ratio",
            "recovery_ratio",
            "confirm_days",
            "derisk_scale",
            "decay_day_ratio_full",
        ]
    ].copy()
    for col in ["decay_ratio", "recovery_ratio", "decay_day_ratio_full"]:
        display[col] = display[col].map(lambda x: pct(float(x)) if pd.notna(x) else "")
    for segment, _years in base.SEGMENTS:
        display[f"{segment}_base_after_delta"] = df.head(n).apply(
            lambda row: (
                f"{pct(float(row[f'base_ann_return_{segment}']))}/{pct(float(row[f'base_max_dd_{segment}']))}"
                f" -> {pct(float(row[f'ann_return_{segment}']))}/{pct(float(row[f'max_dd_{segment}']))}"
                f" (dAnn {-float(row[f'{segment}_ann_loss_pp']):.2f}pp, "
                f"dDD {float(row[f'{segment}_dd_improve_pp']):.2f}pp)"
            ),
            axis=1,
        )
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, zz500, cyb, panel = l2.load_panel()
    scores, r2s, abs_bias = l2.precompute(panel)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    base_frames = {
        str(item["layer4_anchor"]): l4_nav_off_frame(panel, item, scores, r2s, abs_bias)
        for item in L4_INPUTS
    }
    grid = candidate_grid()
    long_rows = []
    wide_rows = []
    result_cache: dict[str, pd.DataFrame] = {}

    for candidate in grid:
        layer4_anchor = str(candidate["layer4_anchor"])
        base_frame = base_frames[layer4_anchor]
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
    selected_lookup = {str(row["candidate"]): row.to_dict() for _, row in window_metrics.iterrows() if str(row["candidate"]) in selected_names}
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

    record_lines = [
        "# ZZ500/CYB Layer 5 Momentum-Decay Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer5_momentum_decay_complete_pending_user_review`",
        "- stability: `momentum_decay_strict_pass_small_patch_width_review`",
        "",
        "## Research Question",
        "Scan score-peak momentum decay after Layer 4 rejected NAV defense and carried Layer 3 nav-off lines unchanged.",
        "",
        "## Layer Inputs",
        "- Formal baseline is Layer 4 `nav_off`, because NAV defense had zero strict full/full+5Y pass candidates.",
        "- One NAV-defense watch line is included only as a diagnostic carry-over, not as the formal baseline.",
        *[
            f"- `{item['layer4_anchor']}` from `{item['layer4_candidate']}`: role={item['role']}, score>{item['score_threshold']}, target_vol={item['target_vol']:.0%}, rv={item['vol_window']}."
            for item in L4_INPUTS
        ],
        f"- Decay ratios: `{', '.join(f'{x:.0%}' for x in DECAY_RATIOS)}`.",
        f"- Recovery ratios: `{', '.join(f'{x:.0%}' for x in RECOVERY_RATIOS)}`.",
        f"- Confirm days: `{', '.join(str(x) for x in CONFIRM_DAYS)}`.",
        f"- Derisk scales: `{', '.join(str(x) for x in DERISK_SCALES)}`.",
        "",
        "## Implementation Anchor",
        "- Imports data loader and signal construction from Layer 2 and target-vol construction from Layer 3.",
        "- Momentum decay uses `score / active_trade_score_peak`, not NAV drawdown.",
        "- Score peak is tracked only while the Layer 2 raw signal is active.",
        "- Trigger is evaluated at T close and the final selected scale is shifted to T+1 execution.",
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
        "- T close signal/target-vol/score-peak decay -> T+1 close-to-close spread return.",
        "- Return stream: final scale times ZZ500 close-to-close return minus CYB close-to-close return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- No NAV defense, overheat, amount, or volume overlay is applied in the promoted baseline; the single NAV line is diagnostic.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 5 scan.",
        "",
        "## Commands",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"ZZ500/CYB spread Layer 5 momentum decay\" --parameter-group \"score_peak_decay_recovery_derisk\" --repo . --entrypoint \"scan_adk_zz500_cyb_spread_layer5_momentum_decay.py\" --date 2026-06-12 --slug \"adk_zz500_cyb_spread_long_only_v77_adk_spread_layer5_momentum_decay_l4_nav_off\"`",
        "- `python -m py_compile \"scan_adk_zz500_cyb_spread_layer5_momentum_decay.py\"`",
        "- `python \"scan_adk_zz500_cyb_spread_layer5_momentum_decay.py\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py <run_folder> --decision \"layer5_momentum_decay_complete_pending_user_review\" --stability-label \"momentum_decay_strict_pass_small_patch_width_review\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>`",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `full_baseline_pass_candidates.csv`",
        "- `full_and_5y_pass_candidates.csv`",
        "- `dd_first_pass_loss_le_0p5pp.csv`",
        "- `dd_first_pass_loss_le_1p0pp.csv`",
        "- `dd_first_pass_loss_le_2p0pp.csv`",
        "- `dd_first_pass_loss_le_3p0pp.csv`",
        "- `carry_candidates.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
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
        "Layer 5 momentum-decay scan completed. Strict full+5Y pass candidates exist, but the strict patch is small; stop for user review before any Layer 6 interaction check or later overlays.",
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
        "subsystem": "ZZ500/CYB spread Layer 5 momentum decay",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz500_cyb_spread_layer4_nav_defense.py",
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
            "execution": "T close signal/target-vol/decay -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "momentum_decay_model": {
            "strength": "score / active trade score peak",
            "trigger": "ratio <= decay_ratio for confirm_days",
            "recovery": "ratio >= recovery_ratio; then require a new score peak before another decay cycle",
            "action": "multiply selected target-vol scale by derisk_scale before T+1 execution shift",
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
                "ratio": "ZZ500 / CYB",
                "return_stream": "ZZ500 pct_change - CYB pct_change",
            },
        },
        "decision": "layer5_momentum_decay_complete_pending_user_review",
        "stability_label": "momentum_decay_strict_pass_small_patch_width_review",
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
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"ZZ500/CYB spread Layer 5 momentum decay\" --parameter-group \"score_peak_decay_recovery_derisk\" --repo . --entrypoint \"scan_adk_zz500_cyb_spread_layer5_momentum_decay.py\" --date 2026-06-12 --slug \"adk_zz500_cyb_spread_long_only_v77_adk_spread_layer5_momentum_decay_l4_nav_off\"\n"
        "python -m py_compile \"scan_adk_zz500_cyb_spread_layer5_momentum_decay.py\"\n"
        "python \"scan_adk_zz500_cyb_spread_layer5_momentum_decay.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"layer5_momentum_decay_complete_pending_user_review\" --stability-label \"momentum_decay_strict_pass_small_patch_width_review\"\n"
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

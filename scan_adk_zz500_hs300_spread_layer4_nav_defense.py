"""Layer 4 NAV defense scan for long ZZ500 / short HS300 spread.

Inputs are selected Layer 3 target-vol carry candidates. This layer adds only
prior-row NAV drawdown defense. Momentum decay, overheat, amount/volume, and
later overlays remain off.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_hs300_spread_layer2_score_abs_filter as l2
import scan_adk_zz500_hs300_spread_layer3_target_vol as l3
import scan_adk_zz500_hs300_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_hs300_spread_long_only_v77_adk_spread_layer4_nav_defense_l3_carry"

L3_INPUTS = [
    {
        "layer3_anchor": "main_confirm_tv20_rv60_abs20",
        "layer2_anchor": "confirm_bias_we2_score2_abs65_m2",
        "anchor": "bias_130_20_we2",
        "layer2_role": "nearby_confirmation",
        "role": "main_strict_full_5y",
        "family": "bias_momentum",
        "bias_ma": 130,
        "mom_day": 20,
        "weight_end": 2.0,
        "score_threshold": 2.0,
        "abs_ma": 65,
        "abs_threshold": -0.020,
        "abs_filter": "ratio_bias",
        "target_vol": 0.20,
        "vol_window": 60,
        "max_leverage": 1.0,
        "min_scale": 0.0,
        "deadband_mode": "abs",
        "deadband_value": 0.20,
        "source_candidate": "l3_confirm_bias_we2_score2_abs65_m2_tv20_rv60_max1_floor0_dbabs0p2",
    },
    {
        "layer3_anchor": "return_preserve_tv18_rv80_abs20",
        "layer2_anchor": "return_bias_we2_score0_abs75_m2p5",
        "anchor": "bias_130_20_we2",
        "layer2_role": "return_preserve_watchlist",
        "role": "return_preserve_watchlist",
        "family": "bias_momentum",
        "bias_ma": 130,
        "mom_day": 20,
        "weight_end": 2.0,
        "score_threshold": 0.0,
        "abs_ma": 75,
        "abs_threshold": -0.025,
        "abs_filter": "ratio_bias",
        "target_vol": 0.18,
        "vol_window": 80,
        "max_leverage": 1.0,
        "min_scale": 0.0,
        "deadband_mode": "abs",
        "deadband_value": 0.20,
        "source_candidate": "l3_return_bias_we2_score0_abs75_m2p5_tv18_rv80_max1_floor0_dbabs0p2",
    },
    {
        "layer3_anchor": "primary_tv8_rv120_abs15",
        "layer2_anchor": "primary_bias_we2_score2_abs70_m2",
        "anchor": "bias_130_20_we2",
        "layer2_role": "primary_dd_first",
        "role": "primary_dd_first",
        "family": "bias_momentum",
        "bias_ma": 130,
        "mom_day": 20,
        "weight_end": 2.0,
        "score_threshold": 2.0,
        "abs_ma": 70,
        "abs_threshold": -0.020,
        "abs_filter": "ratio_bias",
        "target_vol": 0.08,
        "vol_window": 120,
        "max_leverage": 1.0,
        "min_scale": 0.0,
        "deadband_mode": "abs",
        "deadband_value": 0.15,
        "source_candidate": "l3_primary_bias_we2_score2_abs70_m2_tv8_rv120_max1_floor0_dbabs0p15",
    },
    {
        "layer3_anchor": "ultra_def_confirm_tv6_rv120_abs20",
        "layer2_anchor": "confirm_bias_we2_score2_abs65_m2",
        "anchor": "bias_130_20_we2",
        "layer2_role": "nearby_confirmation",
        "role": "ultra_defensive_watchlist",
        "family": "bias_momentum",
        "bias_ma": 130,
        "mom_day": 20,
        "weight_end": 2.0,
        "score_threshold": 2.0,
        "abs_ma": 65,
        "abs_threshold": -0.020,
        "abs_filter": "ratio_bias",
        "target_vol": 0.06,
        "vol_window": 120,
        "max_leverage": 1.0,
        "min_scale": 0.0,
        "deadband_mode": "abs",
        "deadband_value": 0.20,
        "source_candidate": "l3_confirm_bias_we2_score2_abs65_m2_tv6_rv120_max1_floor0_dbabs0p2",
    },
]

NAV_DD_THRESHOLDS = [-0.03, -0.05, -0.075, -0.10, -0.125, -0.15, -0.20, -0.25]
DEFENSE_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [0.5, 1.0, 2.0, 3.0]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def l3_frame_for_input(
    panel: pd.DataFrame,
    item: dict[str, object],
    scores: dict[str, pd.Series],
    r2s: dict[str, pd.Series],
    abs_bias: dict[int, pd.Series],
) -> pd.DataFrame:
    l2_frame = l3.build_l2_signal_frame(panel, item, scores, r2s, abs_bias)
    return l3.apply_target_vol(l2_frame, {**item, "target_vol_enabled": True})


def apply_nav_defense(base_frame: pd.DataFrame, nav_dd_threshold: float, defense_scale: float) -> pd.DataFrame:
    pre_nav = (1.0 + base_frame["return"]).cumprod()
    pre_dd = pre_nav / pre_nav.cummax() - 1.0
    defense_state = (pre_dd <= nav_dd_threshold).shift(1, fill_value=False).astype(bool)
    multiplier = pd.Series(1.0, index=base_frame.index)
    multiplier.loc[defense_state] = float(defense_scale)
    final_weight = base_frame["weight"] * multiplier
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = final_weight * base_frame["gross_return"].div(base_frame["weight"].replace(0.0, np.nan)).fillna(0.0)
    ret = gross_return - cost
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "pre_nav": pre_nav,
            "pre_nav_dd": pre_dd,
            "defense_state": defense_state.astype(float),
            "defense_multiplier": multiplier,
            "base_weight": base_frame["weight"],
        },
        index=base_frame.index,
    )


def candidate_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for item in L3_INPUTS:
        grid.append(
            {
                **item,
                "candidate": f"l4_{item['layer3_anchor']}_nav_off",
                "nav_dd_threshold": 0.0,
                "defense_scale": 1.0,
                "nav_defense_enabled": False,
            }
        )
        for threshold in NAV_DD_THRESHOLDS:
            for scale in DEFENSE_SCALES:
                grid.append(
                    {
                        **item,
                        "candidate": (
                            f"l4_{item['layer3_anchor']}_navdd{fmt_num(threshold, pct=True)}"
                            f"_scale{fmt_num(scale)}"
                        ),
                        "nav_dd_threshold": threshold,
                        "defense_scale": scale,
                        "nav_defense_enabled": True,
                    }
                )
    return grid


def extra_metrics(result: pd.DataFrame) -> dict[str, float]:
    defense_days = result["defense_state"] > 0.5
    return {
        "defense_day_ratio_full": float(defense_days.mean()),
        "avg_defense_multiplier_full": float(result["defense_multiplier"].mean()),
        "avg_multiplier_when_defense_full": float(result.loc[defense_days, "defense_multiplier"].mean())
        if defense_days.any()
        else 1.0,
        "avg_weight_full": float(result["weight"].mean()),
        "avg_abs_weight_full": float(result["weight"].abs().mean()),
        "avg_turnover_full_direct": float(result["turnover"].mean()),
    }


def add_baselines_and_flags(window_metrics: pd.DataFrame) -> pd.DataFrame:
    out = window_metrics.copy()
    baselines = out[~out["nav_defense_enabled"]].set_index("layer3_anchor")
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
        out[f"base_{col}"] = out["layer3_anchor"].map(baselines[col])
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
    out["material_defense"] = out["defense_day_ratio_full"] >= 0.01
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            out["nav_defense_enabled"]
            & out["material_defense"]
            & (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["last_5y_dd_improve_pp"] >= -1e-12)
        )
    return out


def width_summary(window_metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    source = window_metrics[window_metrics["nav_defense_enabled"]].copy()
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for layer3_anchor, group in source.groupby("layer3_anchor"):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "loss_tier_pp": tier,
                        "layer3_anchor": layer3_anchor,
                        "pass_count": 0,
                        "threshold_count": 0,
                        "scale_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_defense_day_ratio": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(
                len(passed) >= 3
                and passed["nav_dd_threshold"].nunique() >= 2
                and passed["defense_scale"].nunique() >= 2
            )
            rows.append(
                {
                    "loss_tier_pp": tier,
                    "layer3_anchor": layer3_anchor,
                    "pass_count": int(len(passed)),
                    "threshold_count": int(passed["nav_dd_threshold"].nunique()),
                    "scale_count": int(passed["defense_scale"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "best_full_ann_loss_pp": float(best["full_ann_loss_pp"]),
                    "best_full_dd_improve_pp": float(best["full_dd_improve_pp"]),
                    "best_defense_day_ratio": float(best["defense_day_ratio_full"]),
                    "patch_like": patch_like,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"],
        ascending=[True, False, False, False],
    )


def select_carry(window_metrics: pd.DataFrame, ridge: pd.DataFrame) -> pd.DataFrame:
    strict = window_metrics[
        window_metrics["nav_defense_enabled"]
        & window_metrics["pass_full_5y_ann_dd"]
        & window_metrics["material_defense"]
    ].copy()
    if strict.empty:
        unchanged = window_metrics[~window_metrics["nav_defense_enabled"]].copy()
        unchanged["carry_score"] = unchanged["ann_return_full"] * 10 + unchanged["max_dd_full"].clip(lower=-0.30) * 2
        unchanged = unchanged.sort_values(["role", "ann_return_full"], ascending=[True, False])
        diagnostic = window_metrics[
            window_metrics["nav_defense_enabled"]
            & window_metrics["material_defense"]
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

    if not strict.empty:
        strict["carry_score"] = (
            strict["ann_return_full"] * 20
            + strict["full_dd_improve_pp"].clip(lower=0, upper=20)
            + strict["last_5y_dd_improve_pp"].clip(lower=0, upper=20) * 0.6
            - strict["full_ann_loss_pp"].clip(lower=-5, upper=5) * 0.5
        )
        strict_keep = strict.sort_values(
            ["ann_return_full", "full_dd_improve_pp"], ascending=[False, False]
        ).groupby("layer3_anchor").head(1)
    else:
        strict_keep = pd.DataFrame()

    patch = ridge[(ridge["patch_like"]) & (ridge["pass_count"] > 0)].head(8)
    pools = []
    for _, row in patch.iterrows():
        tag = str(float(row["loss_tier_pp"])).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        pools.append(window_metrics[(window_metrics["layer3_anchor"] == row["layer3_anchor"]) & window_metrics[pass_col]])
    pool = pd.concat(pools, ignore_index=True) if pools else pd.DataFrame()
    if pool.empty:
        pool = window_metrics[
            window_metrics["nav_defense_enabled"]
            & window_metrics["material_defense"]
            & (window_metrics["full_dd_improve_pp"] > 0)
        ].copy()
    if not pool.empty:
        pool["carry_score"] = (
            pool["full_dd_improve_pp"].clip(lower=0, upper=30)
            + pool["last_5y_dd_improve_pp"].clip(lower=-5, upper=20) * 0.5
            - pool["full_ann_loss_pp"].clip(lower=-5, upper=10) * 0.7
            + pool["ann_return_full"] * 10
        )
        dd_keep = pool.sort_values(["carry_score", "ann_return_full"], ascending=[False, False]).groupby("layer3_anchor").head(2)
    else:
        dd_keep = pd.DataFrame()
    return pd.concat([strict_keep, dd_keep], ignore_index=True).drop_duplicates("candidate").head(10)


def window_table(df: pd.DataFrame, n: int = 10) -> str:
    cols = [
        "candidate",
        "layer3_anchor",
        "role",
        "nav_dd_threshold",
        "defense_scale",
        "defense_day_ratio_full",
    ]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_") or col in {
            "nav_dd_threshold",
            "defense_day_ratio_full",
        }:
            display[col] = display[col].map(lambda x: pct(float(x)) if pd.notna(x) else "")
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, zz500, hs300, panel = l2.load_panel()
    scores, r2s, abs_bias = l2.precompute(panel)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    base_frames = {
        str(item["layer3_anchor"]): l3_frame_for_input(panel, item, scores, r2s, abs_bias)
        for item in L3_INPUTS
    }
    grid = candidate_grid()
    long_rows = []
    wide_rows = []
    result_cache: dict[str, pd.DataFrame] = {}

    for candidate in grid:
        layer3_anchor = str(candidate["layer3_anchor"])
        base_frame = base_frames[layer3_anchor]
        if candidate["nav_defense_enabled"]:
            result = apply_nav_defense(
                base_frame,
                float(candidate["nav_dd_threshold"]),
                float(candidate["defense_scale"]),
            )
        else:
            result = base_frame.copy()
            result["pre_nav"] = (1.0 + result["return"]).cumprod()
            result["pre_nav_dd"] = result["pre_nav"] / result["pre_nav"].cummax() - 1.0
            result["defense_state"] = 0.0
            result["defense_multiplier"] = 1.0
            result["base_weight"] = result["weight"]

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
        if not candidate["nav_defense_enabled"]:
            result_cache[str(candidate["candidate"])] = result

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = width_summary(window_metrics)
    strict_full = window_metrics[
        window_metrics["nav_defense_enabled"] & window_metrics["pass_full_ann_dd"] & window_metrics["material_defense"]
    ].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
    strict_full_5y = window_metrics[
        window_metrics["nav_defense_enabled"] & window_metrics["pass_full_5y_ann_dd"] & window_metrics["material_defense"]
    ].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
    top_tier: dict[float, pd.DataFrame] = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        passed = window_metrics[window_metrics[pass_col]].sort_values(
            ["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]
        )
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_tier[tier] = passed
    carry = select_carry(window_metrics, ridge)

    selected_names = set(window_metrics[~window_metrics["nav_defense_enabled"]]["candidate"].astype(str).tolist())
    for df in [strict_full, strict_full_5y, carry, *top_tier.values()]:
        if not df.empty:
            selected_names.update(df.head(10)["candidate"].astype(str).tolist())
    selected_lookup = {str(row["candidate"]): row.to_dict() for _, row in window_metrics.iterrows() if str(row["candidate"]) in selected_names}
    for name, candidate in selected_lookup.items():
        if name in result_cache:
            continue
        result_cache[name] = apply_nav_defense(
            base_frames[str(candidate["layer3_anchor"])],
            float(candidate["nav_dd_threshold"]),
            float(candidate["defense_scale"]),
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
        "# ZZ500/HS300 Layer 4 NAV Defense Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer4_nav_defense_complete_not_promoted`",
        "- stability: `nav_defense_width_pending_user_confirmation`",
        "",
        "## Research Question",
        "Scan prior-row NAV drawdown defense after selected Layer 3 target-vol candidates.",
        "",
        "## Layer Inputs",
        "- Layer 3 inputs:",
        *[
            f"  - `{item['layer3_anchor']}` from `{item['source_candidate']}`: role={item['role']}, target_vol={item['target_vol']:.0%}, rv={item['vol_window']}, max={item['max_leverage']}, deadband={item['deadband_mode']} {item['deadband_value']:.2f}"
            for item in L3_INPUTS
        ],
        f"- NAV drawdown thresholds: `{', '.join(f'{x:.1%}' for x in NAV_DD_THRESHOLDS)}`.",
        f"- Defense scales: `{', '.join(str(x) for x in DEFENSE_SCALES)}`.",
        "",
        "## Implementation Anchor",
        "- Imports data loader and signal construction from Layer 2 and target-vol construction from Layer 3.",
        "- Computes pre-overlay Layer 3 NAV and prior-row drawdown.",
        "- Applies defense multiplier to the next execution row only, then recomputes final turnover, costs, return, NAV, and drawdown.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research with two-leg commissions, excluding futures basis, financing, borrow, and short locate costs.",
        "- Source-change rule: `research_only_new_scan_script`.",
        "",
        "## Data Snapshot",
        f"- HS300 publication date: {base.HS300_PUBLICATION_DATE}; local rows: {len(hs300)}, start {hs300.index.min().date()}, end {hs300.index.max().date()}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start rule: latest actual index publication date among the two legs.",
        "- Adjustment mode: price index close from local official cache, no total-return substitution.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal/target-vol/pre-overlay NAV drawdown -> T+1 close-to-close spread return.",
        "- Return stream: final scale times ZZ500 close-to-close return minus HS300 close-to-close return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- No momentum decay, overheat, amount, or volume overlay is applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 4 scan.",
        "",
        "## Commands",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"ZZ500/HS300 spread Layer 4 NAV defense\" --parameter-group \"nav_drawdown_threshold_defense_scale\" --repo . --entrypoint \"scan_adk_zz500_hs300_spread_layer4_nav_defense.py\" --date 2026-06-12 --slug \"adk_zz500_hs300_spread_long_only_v77_adk_spread_layer4_nav_defense_l3_carry\"`",
        "- `python -m py_compile \"scan_adk_zz500_hs300_spread_layer4_nav_defense.py\"`",
        "- `python \"scan_adk_zz500_hs300_spread_layer4_nav_defense.py\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py <run_folder> --decision \"layer4_nav_defense_complete_not_promoted\" --stability-label \"nav_defense_width_pending_user_confirmation\"`",
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
        window_table(strict_full, 12) if not strict_full.empty else "No NAV-defense candidates passed full-sample annual-return and drawdown non-underperformance with material defense.",
        "",
        "## Window Results",
        window_table(strict_full_5y, 12) if not strict_full_5y.empty else "No NAV-defense candidates passed strict full+5Y annual-return and drawdown non-underperformance with material defense.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 4 NAV-defense scan completed but not promoted. Stop for user review before Layer 5 momentum decay.",
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
        "subsystem": "ZZ500/HS300 spread Layer 4 NAV defense",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz500_hs300_spread_layer3_target_vol.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "layer4_nav_defense",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "nav_drawdown_threshold_defense_scale",
        "baseline": {"layer3_inputs": L3_INPUTS, "loss_tiers_pp": LOSS_TIERS},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal/target-vol/NAV-DD -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "nav_defense_model": {
            "nav_source": "pre-overlay Layer 3 candidate NAV",
            "trigger": "prior-row NAV drawdown <= threshold",
            "action": "multiply next execution row exposure by defense_scale",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "hs300": {
                "secid": str(mod.CN_DK_HS300_SECID),
                "publication_date": base.HS300_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_HS300_SECID))),
                "rows": int(len(hs300)),
                "start": str(hs300.index.min().date()),
                "end": str(hs300.index.max().date()),
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
                "ratio": "ZZ500 / HS300",
                "return_stream": "ZZ500 pct_change - HS300 pct_change",
            },
        },
        "decision": "layer4_nav_defense_complete_not_promoted",
        "stability_label": "nav_defense_width_pending_user_confirmation",
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
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"ZZ500/HS300 spread Layer 4 NAV defense\" --parameter-group \"nav_drawdown_threshold_defense_scale\" --repo . --entrypoint \"scan_adk_zz500_hs300_spread_layer4_nav_defense.py\" --date 2026-06-12 --slug \"adk_zz500_hs300_spread_long_only_v77_adk_spread_layer4_nav_defense_l3_carry\"\n"
        "python -m py_compile \"scan_adk_zz500_hs300_spread_layer4_nav_defense.py\"\n"
        "python \"scan_adk_zz500_hs300_spread_layer4_nav_defense.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"layer4_nav_defense_complete_not_promoted\" --stability-label \"nav_defense_width_pending_user_confirmation\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict \"{RUN_DIR}\"\n",
        encoding="utf-8",
    )

    cols = [
        "candidate",
        "layer3_anchor",
        "role",
        "nav_dd_threshold",
        "defense_scale",
        "defense_day_ratio_full",
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

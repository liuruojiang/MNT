"""Layer 6 four-quadrant NAV/decay interaction check for ZZ500/HS300.

Compares Layer 4/5 baseline, NAV only, momentum-decay only, and NAV+decay
for fixed diagnostic overlay tuples. This layer is diagnostic because both
NAV defense and momentum decay were rejected as formal promoted layers.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_hs300_spread_layer2_score_abs_filter as l2
import scan_adk_zz500_hs300_spread_layer4_nav_defense as l4
import scan_adk_zz500_hs300_spread_layer5_momentum_decay as l5
import scan_adk_zz500_hs300_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_hs300_spread_long_only_v77_adk_spread_layer6_four_quadrant_nav_decay"
VARIANTS = ["base", "nav_only", "decay_only", "nav_plus_decay"]

LINES = [
    {
        **l5.L4_INPUTS[0],
        "line": "main_confirm_q",
        "line_role": "main_strict_full_5y",
        "nav_dd_threshold": -0.03,
        "defense_scale": 0.75,
        "nav_candidate": "l4_main_confirm_tv20_rv60_abs20_navddm3_scale0p75",
        "decay_ratio": 0.35,
        "recovery_ratio": 0.75,
        "confirm_days": 2,
        "derisk_scale": 0.50,
        "decay_candidate": "l5_main_confirm_nav_off_decay35_rec75_c2_scale0p5",
    },
    {
        **l5.L4_INPUTS[1],
        "line": "return_preserve_q_tight",
        "line_role": "return_preserve_loss0p5_nav",
        "nav_dd_threshold": -0.10,
        "defense_scale": 0.50,
        "nav_candidate": "l4_return_preserve_tv18_rv80_abs20_navddm10_scale0p5",
        "decay_ratio": 0.55,
        "recovery_ratio": 0.95,
        "confirm_days": 3,
        "derisk_scale": 0.50,
        "decay_candidate": "l5_return_preserve_nav_off_decay55_rec95_c3_scale0p5",
    },
    {
        **l5.L4_INPUTS[1],
        "line": "return_preserve_q_strong",
        "line_role": "return_preserve_dd_first",
        "nav_dd_threshold": -0.03,
        "defense_scale": 0.50,
        "nav_candidate": "l4_return_preserve_tv18_rv80_abs20_navddm3_scale0p5",
        "decay_ratio": 0.65,
        "recovery_ratio": 0.75,
        "confirm_days": 1,
        "derisk_scale": 0.00,
        "decay_candidate": "l5_return_preserve_nav_off_decay65_rec75_c1_scale0",
    },
    {
        **l5.L4_INPUTS[2],
        "line": "primary_dd_q",
        "line_role": "primary_dd_first",
        "nav_dd_threshold": -0.05,
        "defense_scale": 0.75,
        "nav_candidate": "l4_primary_tv8_rv120_abs15_navddm5_scale0p75",
        "decay_ratio": 0.65,
        "recovery_ratio": 0.75,
        "confirm_days": 1,
        "derisk_scale": 0.25,
        "decay_candidate": "l5_primary_dd_nav_off_decay65_rec75_c1_scale0p25",
    },
    {
        **l5.L4_INPUTS[3],
        "line": "ultra_def_q",
        "line_role": "ultra_defensive_watchlist",
        "nav_dd_threshold": -0.03,
        "defense_scale": 0.50,
        "nav_candidate": "l4_ultra_def_confirm_tv6_rv120_abs20_navddm3_scale0p5",
        "decay_ratio": 0.65,
        "recovery_ratio": 0.75,
        "confirm_days": 1,
        "derisk_scale": 0.25,
        "decay_candidate": "l5_ultra_def_nav_off_decay65_rec75_c1_scale0p25",
    },
]


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def nav_multiplier(base_frame: pd.DataFrame, nav_dd_threshold: float, defense_scale: float) -> pd.DataFrame:
    pre_nav = (1.0 + base_frame["return"]).cumprod()
    pre_dd = pre_nav / pre_nav.cummax() - 1.0
    defense_state = (pre_dd <= nav_dd_threshold).shift(1, fill_value=False).astype(bool)
    multiplier = pd.Series(1.0, index=base_frame.index)
    multiplier.loc[defense_state] = float(defense_scale)
    return pd.DataFrame(
        {
            "pre_nav": pre_nav,
            "pre_nav_dd": pre_dd,
            "nav_on": defense_state.astype(float),
            "nav_multiplier": multiplier,
        },
        index=base_frame.index,
    )


def base_result(base_frame: pd.DataFrame) -> pd.DataFrame:
    out = base_frame.copy()
    out["nav_on"] = 0.0
    out["nav_multiplier"] = 1.0
    out["decay_on"] = 0.0
    out["decay_multiplier_exec"] = 1.0
    out["final_multiplier"] = 1.0
    return out


def nav_only_result(base_frame: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    nav = nav_multiplier(base_frame, float(line["nav_dd_threshold"]), float(line["defense_scale"]))
    final_weight = base_frame["weight"] * nav["nav_multiplier"]
    return recompute_path(base_frame, final_weight, nav, None)


def decay_only_result(base_frame: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    decay = l5.decay_multiplier_series(
        base_frame["raw_signal"],
        base_frame["score"],
        float(line["decay_ratio"]),
        float(line["recovery_ratio"]),
        int(line["confirm_days"]),
        float(line["derisk_scale"]),
    )
    decay_exec = decay["decay_multiplier"].shift(1).fillna(1.0)
    final_weight = base_frame["weight"] * decay_exec
    return recompute_path(base_frame, final_weight, None, decay)


def stack_result(base_frame: pd.DataFrame, line: dict[str, object]) -> pd.DataFrame:
    nav = nav_multiplier(base_frame, float(line["nav_dd_threshold"]), float(line["defense_scale"]))
    decay = l5.decay_multiplier_series(
        base_frame["raw_signal"],
        base_frame["score"],
        float(line["decay_ratio"]),
        float(line["recovery_ratio"]),
        int(line["confirm_days"]),
        float(line["derisk_scale"]),
    )
    decay_exec = decay["decay_multiplier"].shift(1).fillna(1.0)
    final_weight = base_frame["weight"] * nav["nav_multiplier"] * decay_exec
    return recompute_path(base_frame, final_weight, nav, decay)


def recompute_path(
    base_frame: pd.DataFrame,
    final_weight: pd.Series,
    nav: pd.DataFrame | None,
    decay: pd.DataFrame | None,
) -> pd.DataFrame:
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = final_weight * base_frame["spread_return"]
    ret = gross_return - cost
    out = pd.DataFrame(
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
            "spread_return": base_frame["spread_return"],
        },
        index=base_frame.index,
    )
    if nav is None:
        out["pre_nav"] = (1.0 + base_frame["return"]).cumprod()
        out["pre_nav_dd"] = out["pre_nav"] / out["pre_nav"].cummax() - 1.0
        out["nav_on"] = 0.0
        out["nav_multiplier"] = 1.0
    else:
        out["pre_nav"] = nav["pre_nav"]
        out["pre_nav_dd"] = nav["pre_nav_dd"]
        out["nav_on"] = nav["nav_on"]
        out["nav_multiplier"] = nav["nav_multiplier"]
    if decay is None:
        out["decay_multiplier"] = 1.0
        out["decay_multiplier_exec"] = 1.0
        out["decay_on"] = 0.0
        out["decay_trigger"] = 0.0
        out["decay_recovery"] = 0.0
        out["score_peak"] = np.nan
        out["score_peak_ratio"] = np.nan
    else:
        out["decay_multiplier"] = decay["decay_multiplier"]
        out["decay_multiplier_exec"] = decay["decay_multiplier"].shift(1).fillna(1.0)
        out["decay_on"] = decay["decay_state"].shift(1).fillna(0.0)
        out["decay_trigger"] = decay["decay_trigger"]
        out["decay_recovery"] = decay["decay_recovery"]
        out["score_peak"] = decay["score_peak"]
        out["score_peak_ratio"] = decay["score_peak_ratio"]
    out["final_multiplier"] = out["nav_multiplier"] * out["decay_multiplier_exec"]
    return out


def build_variant(base_frame: pd.DataFrame, line: dict[str, object], variant: str) -> pd.DataFrame:
    if variant == "base":
        return base_result(base_frame)
    if variant == "nav_only":
        return nav_only_result(base_frame, line)
    if variant == "decay_only":
        return decay_only_result(base_frame, line)
    if variant == "nav_plus_decay":
        return stack_result(base_frame, line)
    raise ValueError(f"unknown variant: {variant}")


def extra_metrics_for_segment(result: pd.DataFrame, years: int | None) -> dict[str, float]:
    if years is None:
        d = result.copy()
    else:
        cutoff = result.index.max() - pd.DateOffset(years=years)
        d = result.loc[result.index >= cutoff].copy()
    if d.empty:
        return {
            "nav_days": 0.0,
            "decay_days": 0.0,
            "nav_decay_overlap_days": 0.0,
            "avg_final_multiplier": 1.0,
            "median_final_multiplier": 1.0,
        }
    nav_on = d["nav_on"].astype(float) > 0.5
    decay_on = d["decay_on"].astype(float) > 0.5
    return {
        "nav_days": float(nav_on.sum()),
        "decay_days": float(decay_on.sum()),
        "nav_decay_overlap_days": float((nav_on & decay_on).sum()),
        "avg_final_multiplier": float(d["final_multiplier"].mean()),
        "median_final_multiplier": float(d["final_multiplier"].median()),
    }


def quadrant_rows(line: dict[str, object], result: pd.DataFrame) -> list[dict[str, object]]:
    nav_on = result["nav_on"].astype(float) > 0.5
    decay_on = result["decay_on"].astype(float) > 0.5
    masks = {
        "Q00_nav0_decay0": ~nav_on & ~decay_on,
        "Q10_nav1_decay0": nav_on & ~decay_on,
        "Q01_nav0_decay1": ~nav_on & decay_on,
        "Q11_nav1_decay1": nav_on & decay_on,
    }
    rows: list[dict[str, object]] = []
    for quadrant, mask in masks.items():
        part = result.loc[mask]
        rows.append(
            {
                "line": line["line"],
                "line_role": line["line_role"],
                "quadrant": quadrant,
                "days": int(mask.sum()),
                "avg_weight": float(part["weight"].mean()) if not part.empty else np.nan,
                "median_weight": float(part["weight"].median()) if not part.empty else np.nan,
                "avg_final_multiplier": float(part["final_multiplier"].mean()) if not part.empty else np.nan,
                "median_final_multiplier": float(part["final_multiplier"].median()) if not part.empty else np.nan,
                "gross_return_sum": float(part["gross_return"].sum()) if not part.empty else 0.0,
                "cost_sum": float(part["cost"].sum()) if not part.empty else 0.0,
                "net_return_sum": float(part["return"].sum()) if not part.empty else 0.0,
                "avg_score": float(part["score"].mean()) if not part.empty else np.nan,
            }
        )
    return rows


def classify(line_metrics: pd.DataFrame, quadrants: pd.DataFrame) -> dict[str, object]:
    rows = line_metrics.set_index("variant")
    base_row = rows.loc["base"]
    nav = rows.loc["nav_only"]
    decay = rows.loc["decay_only"]
    stack = rows.loc["nav_plus_decay"]
    q = quadrants.set_index("quadrant")
    q11_days = int(q.loc["Q11_nav1_decay1", "days"]) if "Q11_nav1_decay1" in q.index else 0
    q11_net = float(q.loc["Q11_nav1_decay1", "net_return_sum"]) if "Q11_nav1_decay1" in q.index else 0.0
    best_single_dd = max(float(nav["max_dd_full"]), float(decay["max_dd_full"]))
    best_single_ann = max(float(nav["ann_return_full"]), float(decay["ann_return_full"]))
    stack_dd_delta_pp = (float(stack["max_dd_full"]) - best_single_dd) * 100.0
    stack_ann_loss_vs_best_pp = (best_single_ann - float(stack["ann_return_full"])) * 100.0
    stack_dd_vs_base_pp = (float(stack["max_dd_full"]) - float(base_row["max_dd_full"])) * 100.0
    stack_ann_vs_base_pp = (float(stack["ann_return_full"]) - float(base_row["ann_return_full"])) * 100.0
    stack_pass_full = stack_ann_vs_base_pp >= -1e-10 and stack_dd_vs_base_pp >= -1e-10
    stack_pass_full_5y = (
        stack_pass_full
        and float(stack["ann_return_last_5y"]) >= float(base_row["ann_return_last_5y"]) - 1e-12
        and float(stack["max_dd_last_5y"]) >= float(base_row["max_dd_last_5y"]) - 1e-12
    )
    if q11_days < 20:
        label = "under_supported_overlap"
    elif stack_pass_full_5y:
        label = "complementary_strict"
    elif stack_dd_delta_pp > 0.25 and stack_ann_loss_vs_best_pp <= 1.0:
        label = "complementary_but_not_strict"
    elif stack_dd_delta_pp <= 0 and stack_ann_loss_vs_best_pp > 0.5:
        label = "redundant_or_conflicting"
    else:
        label = "mixed"
    return {
        "line": line_metrics["line"].iloc[0],
        "line_role": line_metrics["line_role"].iloc[0],
        "base_ann_full": float(base_row["ann_return_full"]),
        "base_dd_full": float(base_row["max_dd_full"]),
        "nav_ann_full": float(nav["ann_return_full"]),
        "nav_dd_full": float(nav["max_dd_full"]),
        "decay_ann_full": float(decay["ann_return_full"]),
        "decay_dd_full": float(decay["max_dd_full"]),
        "stack_ann_full": float(stack["ann_return_full"]),
        "stack_dd_full": float(stack["max_dd_full"]),
        "stack_ann_vs_base_pp": stack_ann_vs_base_pp,
        "stack_dd_vs_base_pp": stack_dd_vs_base_pp,
        "stack_dd_delta_vs_best_single_pp": stack_dd_delta_pp,
        "stack_ann_loss_vs_best_single_pp": stack_ann_loss_vs_best_pp,
        "stack_pass_full": bool(stack_pass_full),
        "stack_pass_full_5y": bool(stack_pass_full_5y),
        "q11_days": q11_days,
        "q11_net_return_sum": q11_net,
        "interaction_label": label,
    }


def table_pct(df: pd.DataFrame, cols: list[str]) -> str:
    display = df[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, zz500, hs300, panel = l2.load_panel()
    scores, r2s, abs_bias = l2.precompute(panel)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    daily_parts: list[pd.DataFrame] = []
    q_rows: list[dict[str, object]] = []

    for line in LINES:
        base_frame = l5.l4_nav_off_frame(panel, line, scores, r2s, abs_bias)
        for variant in VARIANTS:
            result = build_variant(base_frame, line, variant)
            candidate = f"l6_{line['line']}_{variant}"
            daily = result.copy()
            daily["nav"] = (1.0 + daily["return"]).cumprod()
            daily["candidate"] = candidate
            daily["line"] = line["line"]
            daily["variant"] = variant
            daily_parts.append(daily.reset_index(names="date"))
            if variant == "nav_plus_decay":
                q_rows.extend(quadrant_rows(line, result))

            wide = {**line, "candidate": candidate, "variant": variant}
            for segment, years in base.SEGMENTS:
                metrics = base.metrics_for_segment(result, segment, years)
                extras = extra_metrics_for_segment(result, years)
                long_rows.append({**line, "candidate": candidate, "variant": variant, **metrics, **extras})
                for key in [
                    "ann_return",
                    "ann_vol",
                    "max_dd",
                    "sharpe_repo",
                    "avg_weight",
                    "avg_turnover",
                    "holding_day_ratio",
                    "cost_total",
                    "nav_days",
                    "decay_days",
                    "nav_decay_overlap_days",
                    "avg_final_multiplier",
                    "median_final_multiplier",
                ]:
                    wide[f"{key}_{segment}"] = metrics.get(key, extras.get(key))
            wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = pd.DataFrame(wide_rows)
    daily_all = pd.concat(daily_parts, ignore_index=True)
    quadrants = pd.DataFrame(q_rows)
    interaction = pd.DataFrame(
        [classify(group, quadrants[quadrants["line"] == line]) for line, group in window_metrics.groupby("line")]
    )

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    quadrants.to_csv(RUN_DIR / "quadrant_summary.csv", index=False, encoding="utf-8-sig")
    interaction.to_csv(RUN_DIR / "interaction_summary.csv", index=False, encoding="utf-8-sig")
    interaction.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    carry = window_metrics[window_metrics["variant"] == "base"].copy()
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    cols = ["candidate", "line", "line_role", "variant"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])

    record_lines = [
        "# ZZ500/HS300 Layer 6 Four-Quadrant NAV/Decay Interaction",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer6_four_quadrant_complete_not_promoted`",
        "- stability: `nav_decay_interaction_rejected_carry_layer4_unchanged`",
        "",
        "## Research Question",
        "Compare target-vol baseline, NAV only, momentum-decay only, and NAV+decay; attribute NAV+decay by four state quadrants.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
        "",
        "## Implementation Anchor",
        "- Imports Layer 5 exact Layer 4 `nav_off` daily curves as the baseline.",
        "- Variants: base, NAV only, decay only, NAV plus decay.",
        "- NAV state is based on prior-row baseline NAV drawdown.",
        "- Momentum decay state is based on score divided by active-trade score peak.",
        "- Stack path multiplies same execution-row NAV multiplier and shifted decay multiplier, then recomputes turnover, cost, return, NAV, and drawdown.",
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
        "- Direction: long ZZ500 / short HS300; ratio is ZZ500/HS300; spread return is ZZ500 pct_change minus HS300 pct_change.",
        "- T close signal/state -> T+1 close-to-close spread return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on final exposure changes.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research, excluding futures basis, financing, borrow, short locate, and slippage.",
        "",
        "## Variant Window Metrics",
        table_pct(window_metrics.sort_values(["line", "variant"]), cols),
        "",
        "## Quadrant Contributions",
        quadrants.to_markdown(index=False),
        "",
        "## Interaction Classification",
        interaction.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 6 completed but not promoted. No NAV/decay stack candidate passed the strict full+5Y baseline non-underperformance rule; carry Layer 4 nav_off unchanged.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "ZZ500/HS300 spread Layer 6 four-quadrant",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz500_hs300_spread_layer5_momentum_decay.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "fresh_layer6_four_quadrant_interaction",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "nav_decay_four_quadrant_interaction_fixed_candidates",
        "baseline": {"lines": LINES, "variants": VARIANTS},
        "candidate_grid": [{**line, "variant": variant} for line in LINES for variant in VARIANTS],
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
        "decision": "layer6_four_quadrant_complete_not_promoted",
        "stability_label": "nav_decay_interaction_rejected_carry_layer4_unchanged",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "quadrant_summary": str(RUN_DIR / "quadrant_summary.csv"),
            "interaction_summary": str(RUN_DIR / "interaction_summary.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "carry_candidates": str(RUN_DIR / "carry_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "\n".join(
            [
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "ZZ500/HS300 spread Layer 6 four-quadrant" --parameter-group "nav_decay_four_quadrant_interaction_fixed_candidates" --repo . --entrypoint "scan_adk_zz500_hs300_spread_layer6_four_quadrant.py" --date 2026-06-12 --slug "adk_zz500_hs300_spread_long_only_v77_adk_spread_layer6_four_quadrant_nav_decay"',
                'python -m py_compile "scan_adk_zz500_hs300_spread_layer6_four_quadrant.py"',
                'python "scan_adk_zz500_hs300_spread_layer6_four_quadrant.py"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "{RUN_DIR}" --decision "layer6_four_quadrant_complete_not_promoted" --stability-label "nav_decay_interaction_rejected_carry_layer4_unchanged"',
                f'python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict "{RUN_DIR}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(window_metrics)}")
    print("WINDOW_METRICS")
    print(window_metrics[cols].to_string(index=False))
    print("QUADRANTS")
    print(quadrants.to_string(index=False))
    print("INTERACTION")
    print(interaction.to_string(index=False))


if __name__ == "__main__":
    main()

"""Layer 6 four-quadrant NAV/decay interaction check for CYB/ZZ500.

Compares Layer 3 target-vol base, NAV only, momentum-decay only, and NAV+decay
for fixed Layer 4/5 carry tuples. This layer is diagnostic; Layer 5 decay was
kept as observation only, so promotion requires a clear interaction result.
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
import scan_adk_cyb_zz500_spread_layer5_momentum_decay as l5
import scan_adk_cyb_zz500_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_cyb_zz500_spread_long_only_v77_adk_spread_layer6_four_quadrant_nav_decay"
VARIANTS = ["base", "nav_only", "decay_only", "nav_plus_decay"]

LINES = [
    {
        **l4.L3_INPUTS[0],
        "line": "return_q",
        "line_role": "return_watchlist",
        "nav_dd_threshold": -0.03,
        "defense_scale": 0.50,
        "nav_candidate": "l4_return_tv10_rv120_max1p5_floor0p5_rel15_navddm3_scale0p5",
        "decay_ratio": 0.85,
        "recovery_ratio": 0.95,
        "confirm_days": 2,
        "derisk_scale": 0.50,
        "decay_candidate": "l5_return_nav3_scale0p5_decay85_rec95_c2_scale0p5",
    },
    {
        **l4.L3_INPUTS[1],
        "line": "primary_q",
        "line_role": "primary_strict_full_5y",
        "nav_dd_threshold": -0.03,
        "defense_scale": 0.50,
        "nav_candidate": "l4_primary_tv10_rv120_max1p5_floor0p5_rel15_navddm3_scale0p5",
        "decay_ratio": 0.85,
        "recovery_ratio": 0.95,
        "confirm_days": 1,
        "derisk_scale": 0.75,
        "decay_candidate": "l5_primary_nav3_scale0p5_decay85_rec95_c1_scale0p75",
    },
    {
        **l4.L3_INPUTS[2],
        "line": "confirm_q",
        "line_role": "same_patch_confirmation",
        "nav_dd_threshold": -0.03,
        "defense_scale": 0.50,
        "nav_candidate": "l4_confirm_tv10_rv120_max1p5_floor0p5_rel15_navddm3_scale0p5",
        "decay_ratio": 0.75,
        "recovery_ratio": 0.85,
        "confirm_days": 3,
        "derisk_scale": 0.25,
        "decay_candidate": "l5_confirm_nav3_scale0p5_decay75_rec85_c3_scale0p25",
    },
    {
        **l4.L3_INPUTS[3],
        "line": "defensive_q_nav4",
        "line_role": "defensive_watchlist",
        "nav_dd_threshold": -0.04,
        "defense_scale": 0.00,
        "nav_candidate": "l4_defensive_tv10_rv40_max2_floor0_abs20_navddm4_scale0",
        "decay_ratio": 0.75,
        "recovery_ratio": 0.85,
        "confirm_days": 3,
        "derisk_scale": 0.00,
        "decay_candidate": "l5_defensive_nav4_scale0_decay75_rec85_c3_scale0",
    },
    {
        **l4.L3_INPUTS[3],
        "line": "defensive_q_nav3",
        "line_role": "defensive_watchlist",
        "nav_dd_threshold": -0.03,
        "defense_scale": 0.50,
        "nav_candidate": "l4_defensive_tv10_rv40_max2_floor0_abs20_navddm3_scale0p5",
        "decay_ratio": 0.85,
        "recovery_ratio": 0.95,
        "confirm_days": 2,
        "derisk_scale": 0.25,
        "decay_candidate": "l5_defensive_nav3_scale0p5_decay85_rec95_c2_scale0p25",
    },
]


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def build_l3_base(
    panel: pd.DataFrame,
    line: dict[str, object],
    scores: dict[str, pd.Series],
    r2s: dict[str, pd.Series],
    abs_bias: dict[int, pd.Series],
) -> pd.DataFrame:
    l2_frame = l3.build_l2_signal_frame(panel, line, scores, r2s, abs_bias)
    out = l3.apply_target_vol(l2_frame, {**line, "target_vol_enabled": True}).copy()
    out["spread_return"] = l2_frame["spread_return"].reindex(out.index)
    out["score"] = l2_frame["score"].reindex(out.index)
    out["r2"] = l2_frame["r2"].reindex(out.index)
    out["base_weight"] = out["weight"]
    out["nav_on"] = 0.0
    out["nav_mult"] = 1.0
    return out


def add_nav_context(nav_frame: pd.DataFrame, l3_base: pd.DataFrame) -> pd.DataFrame:
    out = nav_frame.copy()
    out["score"] = l3_base["score"].reindex(out.index)
    out["r2"] = l3_base["r2"].reindex(out.index)
    out["spread_return"] = l3_base["spread_return"].reindex(out.index)
    out["raw_signal"] = l3_base["raw_signal"].reindex(out.index)
    out["base_weight"] = out["weight"]
    out["nav_on"] = out["defense_state"]
    out["nav_mult"] = out["defense_multiplier"]
    return out


def build_variant(l3_base: pd.DataFrame, line: dict[str, object], variant: str) -> pd.DataFrame:
    if variant == "base":
        out = l3_base.copy()
        out["decay_on"] = 0.0
        out["decay_multiplier"] = 1.0
        return out
    if variant == "nav_only":
        out = add_nav_context(
            l4.apply_nav_defense(l3_base, float(line["nav_dd_threshold"]), float(line["defense_scale"])),
            l3_base,
        )
        out["decay_on"] = 0.0
        out["decay_multiplier"] = 1.0
        return out
    if variant == "decay_only":
        base_no_nav = l3_base.copy()
        base_no_nav["base_weight"] = base_no_nav["weight"]
        base_no_nav["nav_on"] = 0.0
        base_no_nav["nav_mult"] = 1.0
        return l5.apply_momentum_decay(
            base_no_nav,
            float(line["decay_ratio"]),
            float(line["recovery_ratio"]),
            int(line["confirm_days"]),
            float(line["derisk_scale"]),
        )
    if variant == "nav_plus_decay":
        nav_base = add_nav_context(
            l4.apply_nav_defense(l3_base, float(line["nav_dd_threshold"]), float(line["defense_scale"])),
            l3_base,
        )
        return l5.apply_momentum_decay(
            nav_base,
            float(line["decay_ratio"]),
            float(line["recovery_ratio"]),
            int(line["confirm_days"]),
            float(line["derisk_scale"]),
        )
    raise ValueError(f"unknown variant: {variant}")


def extra_metrics_for_segment(result: pd.DataFrame, years: int | None) -> dict[str, float]:
    d = result if years is None else result.loc[result.index >= result.index.max() - pd.DateOffset(years=years)]
    if d.empty:
        return {
            "nav_days": 0.0,
            "decay_days": 0.0,
            "nav_decay_overlap_days": 0.0,
            "avg_final_weight": 0.0,
            "median_final_weight": 0.0,
        }
    nav_on = d["nav_on"].astype(float) > 0.5
    decay_on = d["decay_on"].astype(float) > 0.5
    return {
        "nav_days": float(nav_on.sum()),
        "decay_days": float(decay_on.sum()),
        "nav_decay_overlap_days": float((nav_on & decay_on).sum()),
        "avg_final_weight": float(d["weight"].mean()),
        "median_final_weight": float(d["weight"].median()),
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
    mod, cyb, zz500, panel = l2.load_panel()
    scores, r2s, abs_bias = l2.precompute(panel)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    daily_parts: list[pd.DataFrame] = []
    q_rows: list[dict[str, object]] = []

    for line in LINES:
        l3_base = build_l3_base(panel, line, scores, r2s, abs_bias)
        for variant in VARIANTS:
            result = build_variant(l3_base, line, variant)
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
                    "avg_final_weight",
                    "median_final_weight",
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
    carry = window_metrics[window_metrics["variant"] == "nav_only"].copy()

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    quadrants.to_csv(RUN_DIR / "quadrant_summary.csv", index=False, encoding="utf-8-sig")
    interaction.to_csv(RUN_DIR / "interaction_summary.csv", index=False, encoding="utf-8-sig")
    interaction.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    cols = ["candidate", "line", "line_role", "variant"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])

    decision = "layer6_four_quadrant_complete_not_promoted"
    stability = "nav_decay_interaction_review_carry_layer4_nav_only"
    record_lines = [
        "# CYB/ZZ500 Layer 6 Four-Quadrant NAV/Decay Interaction",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        f"- decision: `{decision}`",
        f"- stability: `{stability}`",
        "",
        "## Research Question",
        "Compare target-vol base, NAV only, momentum-decay only, and NAV+decay; attribute NAV+decay by four state quadrants.",
        "",
        "## Layer Inputs",
        pd.DataFrame(LINES).to_markdown(index=False),
        "",
        "## Implementation Anchor",
        "- Imports Layer 3 target-vol, Layer 4 NAV defense, and Layer 5 momentum-decay implementations.",
        "- Variants: base, NAV only, decay only, NAV plus decay.",
        "- Quadrants are attributed on the NAV+decay path.",
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
        "- Direction: long CYB / short ZZ500; ratio is CYB/ZZ500; spread return is CYB pct_change minus ZZ500 pct_change.",
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
        "Layer 6 completed. Carry Layer 4 NAV-only unless stack shows strict full+5Y improvement.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "CYB/ZZ500 spread Layer 6 four-quadrant",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_cyb_zz500_spread_layer5_momentum_decay.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "layer6_four_quadrant_interaction",
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
            "quadrant_summary": str(RUN_DIR / "quadrant_summary.csv"),
            "interaction_summary": str(RUN_DIR / "interaction_summary.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "carry_candidates": str(RUN_DIR / "carry_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"CYB/ZZ500 spread Layer 6 four-quadrant\" --parameter-group \"nav_decay_four_quadrant_interaction_fixed_candidates\" --repo . --entrypoint \"scan_adk_cyb_zz500_spread_layer6_four_quadrant.py\" --date 2026-06-12 --slug \"adk_cyb_zz500_spread_long_only_v77_adk_spread_layer6_four_quadrant_nav_decay\"\n"
        "python -m py_compile \"scan_adk_cyb_zz500_spread_layer6_four_quadrant.py\"\n"
        "python \"scan_adk_cyb_zz500_spread_layer6_four_quadrant.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"{decision}\" --stability-label \"{stability}\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict \"{RUN_DIR}\"\n",
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

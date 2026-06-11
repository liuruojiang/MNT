"""Layer 6 four-quadrant interaction check for ZZ500/SZ50.

Compares target-vol base, NAV only, momentum-decay only, and NAV+decay for the
Layer 5 carry candidates. The quadrant table attributes the NAV+decay final
path by NAV state and decay state.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_sz50_spread_layer3_target_vol as l3
import scan_adk_zz500_sz50_spread_layer4_nav_defense as l4
import scan_adk_zz500_sz50_spread_layer5_momentum_decay as l5
import scan_adk_zz500_sz50_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_sz50_spread_long_only_v77_adk_spread_layer6_four_quadrant_nav_decay"

LINES = [
    {
        "line": "width_primary_q",
        "line_role": "width_primary",
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
        "decay_threshold": 0.50,
        "recovery_threshold": 0.90,
        "warmup_days": 10,
        "derisk_scale": 0.0,
        "layer5_candidate": "l5_width_primary_nav8p75_scale0p5_decay0p5_rec0p9_warm10_scale0",
    },
    {
        "line": "width_confirm_q",
        "line_role": "width_confirmation",
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
        "decay_threshold": 0.45,
        "recovery_threshold": 0.90,
        "warmup_days": 10,
        "derisk_scale": 0.0,
        "layer5_candidate": "l5_width_confirm_nav8p75_scale0p5_decay0p45_rec0p9_warm10_scale0",
    },
    {
        "line": "return_primary_q",
        "line_role": "return_primary_watch",
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
        "decay_threshold": 0.50,
        "recovery_threshold": 0.70,
        "warmup_days": 10,
        "derisk_scale": 0.25,
        "layer5_candidate": "l5_return_primary_nav8p75_scale0p5_decay0p5_rec0p7_warm10_scale0p25",
    },
    {
        "line": "return_confirm_q",
        "line_role": "return_confirmation_watch",
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
        "decay_threshold": 0.45,
        "recovery_threshold": 0.70,
        "warmup_days": 10,
        "derisk_scale": 0.25,
        "layer5_candidate": "l5_return_confirm_nav10_scale0p5_decay0p45_rec0p7_warm10_scale0p25",
    },
]


def add_raw_signal(df: pd.DataFrame, sig: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["raw_signal"] = sig["raw_signal"].reindex(out.index).fillna(0.0)
    out["nav_on"] = out.get("nav_defense_on", pd.Series(False, index=out.index)).astype(int)
    out["nav_mult"] = out.get("nav_defense_mult", pd.Series(1.0, index=out.index))
    out["base_weight"] = out["weight"]
    return out


def build_variant(panel: pd.DataFrame, line: dict[str, object], variant: str) -> pd.DataFrame:
    sig = l3.line_signal(panel, line)
    l3_base = l4.l3_base_returns(panel, line)
    if variant == "base":
        nav_base = l4.apply_nav_defense(l3_base, None, None)
        result = add_raw_signal(nav_base, sig)
        result["decay_on"] = 0
        result["decay_mult"] = 1.0
        return result
    if variant == "nav_only":
        nav_base = l4.apply_nav_defense(l3_base, float(line["nav_threshold"]), float(line["defense_scale"]))
        result = add_raw_signal(nav_base, sig)
        result["decay_on"] = 0
        result["decay_mult"] = 1.0
        return result
    if variant == "decay_only":
        nav_base = add_raw_signal(l4.apply_nav_defense(l3_base, None, None), sig)
        return l5.apply_decay(
            nav_base,
            float(line["decay_threshold"]),
            float(line["recovery_threshold"]),
            int(line["warmup_days"]),
            float(line["derisk_scale"]),
        )
    if variant == "nav_plus_decay":
        nav_base = add_raw_signal(
            l4.apply_nav_defense(l3_base, float(line["nav_threshold"]), float(line["defense_scale"])),
            sig,
        )
        return l5.apply_decay(
            nav_base,
            float(line["decay_threshold"]),
            float(line["recovery_threshold"]),
            int(line["warmup_days"]),
            float(line["derisk_scale"]),
        )
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
            "avg_final_weight": 0.0,
            "median_final_weight": 0.0,
        }
    nav_on = d["nav_on"].astype(float) > 0
    decay_on = d["decay_on"].astype(float) > 0
    return {
        "nav_days": float(nav_on.sum()),
        "decay_days": float(decay_on.sum()),
        "nav_decay_overlap_days": float((nav_on & decay_on).sum()),
        "avg_final_weight": float(d["weight"].mean()),
        "median_final_weight": float(d["weight"].median()),
    }


def quadrant_rows(line: dict[str, object], result: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    nav_on = result["nav_on"].astype(float) > 0
    decay_on = result["decay_on"].astype(float) > 0
    masks = {
        "Q00_nav0_decay0": ~nav_on & ~decay_on,
        "Q10_nav1_decay0": nav_on & ~decay_on,
        "Q01_nav0_decay1": ~nav_on & decay_on,
        "Q11_nav1_decay1": nav_on & decay_on,
    }
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
    row = line_metrics.set_index("variant")
    base_row = row.loc["base"]
    nav = row.loc["nav_only"]
    decay = row.loc["decay_only"]
    stack = row.loc["nav_plus_decay"]
    q = quadrants.set_index("quadrant")
    q11_days = int(q.loc["Q11_nav1_decay1", "days"]) if "Q11_nav1_decay1" in q.index else 0
    q11_net = float(q.loc["Q11_nav1_decay1", "net_return_sum"]) if "Q11_nav1_decay1" in q.index else 0.0
    best_single_dd = max(float(nav["max_dd_full"]), float(decay["max_dd_full"]))
    best_single_ann = max(float(nav["ann_return_full"]), float(decay["ann_return_full"]))
    stack_dd_delta_pp = (float(stack["max_dd_full"]) - best_single_dd) * 100.0
    stack_ann_loss_vs_best_pp = (best_single_ann - float(stack["ann_return_full"])) * 100.0
    if q11_days < 20:
        label = "under_supported_overlap"
    elif stack_dd_delta_pp > 0.25 and stack_ann_loss_vs_best_pp <= 1.0:
        label = "complementary"
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
        "stack_dd_delta_vs_best_single_pp": stack_dd_delta_pp,
        "stack_ann_loss_vs_best_single_pp": stack_ann_loss_vs_best_pp,
        "q11_days": q11_days,
        "q11_net_return_sum": q11_net,
        "interaction_label": label,
    }


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def table_pct(df: pd.DataFrame, cols: list[str]) -> str:
    display = df[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    mod, zz500, sz50, panel = l3.load_panel()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    variants = ["base", "nav_only", "decay_only", "nav_plus_decay"]
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    daily_parts: list[pd.DataFrame] = []
    q_rows: list[dict[str, object]] = []

    for line in LINES:
        for variant in variants:
            result = build_variant(panel, line, variant)
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
    interaction_rows = []
    for line_name, d in window_metrics.groupby("line"):
        interaction_rows.append(classify(d, quadrants[quadrants["line"] == line_name]))
    interaction = pd.DataFrame(interaction_rows)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    quadrants.to_csv(RUN_DIR / "quadrant_summary.csv", index=False, encoding="utf-8-sig")
    interaction.to_csv(RUN_DIR / "interaction_summary.csv", index=False, encoding="utf-8-sig")
    interaction.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")

    cols = ["candidate", "line", "variant"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    record_lines = [
        "# ZZ500/SZ50 Layer 6 Four-Quadrant NAV/Decay Interaction",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer6_four_quadrant_complete_pending_user_review`",
        "- stability: `nav_decay_interaction_review`",
        "",
        "## Research Question",
        "Compare target-vol base, NAV only, momentum-decay only, and NAV+decay; attribute NAV+decay by four state quadrants.",
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
        "- NAV and decay states are each shifted to next execution by their layer implementation.",
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
        "Layer 6 completed and stopped for user review before later overheat/volhot/amount/volume layers.",
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
        "implementation_anchor": "scan_adk_zz500_sz50_spread_layer5_momentum_decay.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status,
        "git_status_after": git_status,
        "scan_type": "fresh_layer6_four_quadrant_interaction",
        "parameter_group": "nav_decay_four_quadrant_interaction_fixed_candidates",
        "baseline": {"lines": LINES, "variants": variants},
        "candidate_grid": [{**line, "variant": variant} for line in LINES for variant in variants],
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
        "decision": "layer6_four_quadrant_complete_pending_user_review",
        "stability_label": "nav_decay_interaction_review",
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
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "\n".join(
            [
                'python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project "A-share / US momentum combo" --strategy "V7.7 ADK spread research" --subsystem "ZZ500/SZ50 spread Layer 6 four-quadrant" --parameter-group "nav_decay_four_quadrant_interaction_fixed_candidates" --repo . --entrypoint "scan_adk_zz500_sz50_spread_layer6_four_quadrant.py" --date 2026-06-12 --slug "adk_zz500_sz50_spread_long_only_v77_adk_spread_layer6_four_quadrant_nav_decay"',
                'python -m py_compile "scan_adk_zz500_sz50_spread_layer6_four_quadrant.py"',
                'python "scan_adk_zz500_sz50_spread_layer6_four_quadrant.py"',
                'python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py "<run_folder>" --decision "layer6_four_quadrant_complete_pending_user_review" --stability-label "nav_decay_interaction_review" --repo .',
                'python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict "<run_folder>"',
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

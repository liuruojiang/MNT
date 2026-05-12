from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import run_v76_adk_b_subd_dynamic_budget_optimization as sleeve_scan


ROOT = Path(__file__).resolve().parent
SOURCE_RUN_DIR = (
    ROOT
    / "quant_param_scan_runs"
    / "20260512_v76_level8_v7_6_five_sleeve_a_adk_b_subd_dynamic_budget_prior_nav_dd_threshold_execution_step"
)
DEFAULT_RUN_DIR = (
    ROOT
    / "quant_param_scan_runs"
    / "20260512_v76_level8_v7_6_five_sleeve_suba_dynamic_budget_landing_candidate_candidate_robustness_and_landability"
)
BASELINE = "fixed_10_15_15_20_40"
TARGET_CANDIDATE = "advisory_suba_dd_5_8_weekly_step5_cost0bps"
TARGET_COST20 = "advisory_suba_dd_5_8_weekly_step5_cost20bps"


def load_source_metrics(source_run_dir: str | Path = SOURCE_RUN_DIR) -> pd.DataFrame:
    path = Path(source_run_dir) / "scan_summary.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def candidate_family(long_metrics: pd.DataFrame) -> pd.DataFrame:
    suba = long_metrics[long_metrics["dynamic_sleeve"].eq("Sub-A")].copy()
    family = suba[
        suba["boost_dd"].isin([0.03, 0.05, 0.07])
        & suba["cut_dd"].isin([0.08, 0.10])
        & suba["step"].eq(0.05)
        & suba["cost_bps"].isin([0, 5, 10, 20])
    ].copy()
    baseline = long_metrics[long_metrics["candidate"].eq(BASELINE)].copy()
    out = pd.concat([baseline, family], ignore_index=True)
    out["validation_scope"] = out["candidate"].map(_validation_scope)
    return out


def _validation_scope(candidate: str) -> str:
    if candidate == BASELINE:
        return "baseline"
    if candidate in {TARGET_CANDIDATE, TARGET_COST20}:
        return "target"
    if "weekly" in candidate:
        return "threshold_neighbor"
    return "execution_neighbor"


def build_ranked_validation(long_metrics: pd.DataFrame) -> pd.DataFrame:
    ranked = sleeve_scan.build_scan_summary(long_metrics)
    baseline = ranked[ranked["candidate"].eq(BASELINE)].iloc[0]
    ranked["all_window_ann_delta_positive"] = ranked[
        [
            "full_annual_delta",
            "last_10y_annual_delta",
            "last_5y_annual_delta",
            "last_3y_annual_delta",
            "last_1y_annual_delta",
        ]
    ].gt(0.0).all(axis=1)
    ranked["full_dd_not_worse"] = ranked["full_maxdd_delta"].ge(0.0)
    ranked["full_sharpe_positive"] = ranked["full_sharpe_delta"].gt(0.0)
    ranked["beats_baseline"] = ranked["candidate"].ne(BASELINE) & ranked[
        ["all_window_ann_delta_positive", "full_dd_not_worse", "full_sharpe_positive"]
    ].all(axis=1)
    ranked.loc[ranked["candidate"].eq(BASELINE), "baseline_full_annual"] = baseline["annual_return"]
    ranked.loc[ranked["candidate"].eq(BASELINE), "baseline_full_max_dd"] = baseline["max_dd"]
    ranked.loc[ranked["candidate"].eq(BASELINE), "baseline_full_sharpe"] = baseline["sharpe"]
    return ranked


def build_window_metrics_wide(long_metrics: pd.DataFrame) -> pd.DataFrame:
    return sleeve_scan.to_window_metrics_wide(long_metrics)


def _fmt_pct(value: float) -> str:
    return f"{value:.2%}" if not pd.isna(value) else "n/a"


def _landing_surface_notes() -> list[dict[str, str]]:
    return [
        {
            "surface": "scenario constants",
            "path": "mnt_bot V 7.6 plus.py",
            "notes": "PORTFOLIO_ADVISORY_SCENARIO / PORTFOLIO_STACKED_ADVISORY_SCENARIO currently name the old microcap and Sub-A+microcap advisory scenarios.",
        },
        {
            "surface": "snapshot loader",
            "path": "mnt_bot V 7.6 plus.py",
            "notes": "_load_combo_advisory_snapshot reads outputs/portfolio_v76_current scenario files; landing A-only should either add a new scenario or update the selected advisory scenario deliberately.",
        },
        {
            "surface": "signal display",
            "path": "mnt_bot V 7.6 plus.py",
            "notes": "Signal/live-signal output must show Sub-A target 5/10/15%, Sub-B absorber target, trigger 5%, cut 8%, and prior Sub-A NAV drawdown.",
        },
        {
            "surface": "params display",
            "path": "mnt_bot V 7.6 plus.py",
            "notes": "参数 / 实时参数 should expose the same thresholds and execution frequency if promoted.",
        },
    ]


def render_record(ranked: pd.DataFrame, run_dir: Path) -> str:
    target = ranked[ranked["candidate"].eq(TARGET_CANDIDATE)].iloc[0]
    target20 = ranked[ranked["candidate"].eq(TARGET_COST20)].iloc[0]
    passing = ranked[ranked["beats_baseline"] & ranked["candidate"].ne(TARGET_CANDIDATE)]
    top = ranked[ranked["candidate"].ne(BASELINE)].head(8)
    notes = _landing_surface_notes()
    lines = [
        "# V7.6 Sub-A Dynamic Budget Landing Candidate Validation",
        "",
        "## Research Question",
        "",
        "Validate whether the selected Sub-A dynamic-budget rule is robust enough to become the next landing candidate, before changing production defaults.",
        "",
        "## Selected Candidate",
        "",
        "- Candidate: `advisory_suba_dd_5_8_weekly_step5_cost0bps`.",
        "- Rule: Sub-A prior NAV drawdown within 5% -> 15%; drawdown at or below 8% -> 5%; otherwise 10%; weekly execution; Sub-B absorbs the delta.",
        "- Source scan: `run_v76_adk_b_subd_dynamic_budget_optimization.py`.",
        "",
        "## Data Snapshot",
        "",
        "- Common daily aligned sleeve-return sample: 2011-12-09 to 2026-05-08.",
        "- Baseline weights: Sub-A 10%, Sub-A-DK 15%, Microcap 15%, Sub-D 20%, Sub-B 40%.",
        "",
        "## Measured Result",
        "",
        f"- Target full annual: {_fmt_pct(float(target['annual_return']))}; delta vs fixed: {_fmt_pct(float(target['full_annual_delta']))}.",
        f"- Target full maxDD: {_fmt_pct(float(target['max_dd']))}; delta vs fixed: {_fmt_pct(float(target['full_maxdd_delta']))}.",
        f"- Target full Sharpe: {float(target['sharpe']):.2f}; delta vs fixed: {float(target['full_sharpe_delta']):+.3f}.",
        f"- 10Y/5Y/3Y/1Y annual deltas: {_fmt_pct(float(target['last_10y_annual_delta']))}, {_fmt_pct(float(target['last_5y_annual_delta']))}, {_fmt_pct(float(target['last_3y_annual_delta']))}, {_fmt_pct(float(target['last_1y_annual_delta']))}.",
        f"- 20bps stress full annual delta: {_fmt_pct(float(target20['full_annual_delta']))}; 20bps full Sharpe delta: {float(target20['full_sharpe_delta']):+.3f}.",
        "",
        "## Neighborhood Stability",
        "",
        f"- Passing non-target neighbors under the same strict check: {len(passing)}.",
        "- Strict check used here: all full/10Y/5Y/3Y/1Y annual deltas positive, full maxDD not worse, full Sharpe positive.",
        "",
        "| Candidate | Cost | Full annual delta | Full maxDD delta | Full Sharpe delta | 1Y annual delta | Score |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in top.iterrows():
        lines.append(
            f"| `{row['candidate']}` | {int(row['cost_bps'])} bps | "
            f"{_fmt_pct(float(row['full_annual_delta']))} | "
            f"{_fmt_pct(float(row['full_maxdd_delta']))} | "
            f"{float(row['full_sharpe_delta']):+.3f} | "
            f"{_fmt_pct(float(row['last_1y_annual_delta']))} | "
            f"{float(row['recent_weighted_score']):.4f} |"
        )
    lines.extend(
        [
            "",
            "## Landability Surface",
            "",
            "| Surface | Path | Notes |",
            "|---|---|---|",
        ]
    )
    for note in notes:
        lines.append(f"| {note['surface']} | `{note['path']}` | {note['notes']} |")
    lines.extend(
        [
            "",
            "## Stability Classification",
            "",
            "landing candidate; acceptable broad-window stability, but not yet production default.",
            "",
            "## Decision",
            "",
            "Promote Sub-A 5/8 weekly step5 to the next implementation candidate. Do not enable it as production default until the V7.6 scenario output, signal, live-signal, params, and live-params display surfaces are updated and verified.",
            "",
            "## Output Files",
            "",
            f"- `{(run_dir / 'scan_summary.csv').as_posix()}`",
            f"- `{(run_dir / 'window_metrics.csv').as_posix()}`",
            f"- `{(run_dir / 'ranked_validation.csv').as_posix()}`",
            f"- `{(run_dir / 'landability_surface.csv').as_posix()}`",
            f"- `{(run_dir / 'scan_meta.json').as_posix()}`",
        ]
    )
    return "\n".join(lines)


def write_outputs(run_dir: str | Path, source_run_dir: str | Path = SOURCE_RUN_DIR) -> None:
    out = Path(run_dir)
    out.mkdir(parents=True, exist_ok=True)
    source_long = load_source_metrics(source_run_dir)
    long = candidate_family(source_long)
    ranked = build_ranked_validation(long)
    wide = build_window_metrics_wide(long)
    landability = pd.DataFrame(_landing_surface_notes())
    long.to_csv(out / "scan_summary.csv", index=False, encoding="utf-8-sig")
    wide.to_csv(out / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ranked.to_csv(out / "ranked_validation.csv", index=False, encoding="utf-8-sig")
    landability.to_csv(out / "landability_surface.csv", index=False, encoding="utf-8-sig")
    source_meta_path = Path(source_run_dir) / "scan_meta.json"
    source_meta = json.loads(source_meta_path.read_text(encoding="utf-8")) if source_meta_path.exists() else {}
    meta = {
        "run_id": out.name,
        "created_at": "2026-05-12",
        "project": "v76_level8",
        "repo_root": str(ROOT),
        "strategy": "V7.6 five-sleeve",
        "subsystem": "SubA_dynamic_budget_landing_candidate",
        "git_branch": "",
        "git_commit": "",
        "git_status_before": "",
        "git_status_after": "",
        "scan_type": "artifact_normalized_landing_candidate_validation",
        "parameter_group": "candidate_robustness_and_landability",
        "entrypoint": "run_v76_suba_dynamic_budget_landing_validation.py",
        "baseline": source_meta.get("baseline", {"candidate": BASELINE}),
        "source_run_dir": str(Path(source_run_dir)),
        "data_snapshot": source_meta.get("data_snapshot", {}),
        "returns_source": source_meta.get("returns_source", ""),
        "manifest": source_meta.get("manifest", ""),
        "rows": source_meta.get("rows", 0),
        "start": source_meta.get("start", ""),
        "end": source_meta.get("end", ""),
        "cost_model": source_meta.get("cost_model", {}),
        "timing": "artifact normalization from prior real scan; target uses Sub-A NAV drawdown through t-1 and weekly execution",
        "outputs": {
            "scan_summary": str(out / "scan_summary.csv"),
            "window_metrics": str(out / "window_metrics.csv"),
            "ranked_validation": str(out / "ranked_validation.csv"),
            "landability_surface": str(out / "landability_surface.csv"),
            "record": str(out / "record.md"),
            "scan_meta": str(out / "scan_meta.json"),
            "command_log": str(out / "command_log.txt"),
        },
        "decision": "Sub-A 5/8 weekly step5 is promoted to the next implementation candidate, not production default.",
        "stability_label": "landing candidate; acceptable broad-window stability, but not yet production default",
    }
    (out / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "record.md").write_text(render_record(ranked, out), encoding="utf-8")
    (out / "command_log.txt").write_text(
        "python run_v76_suba_dynamic_budget_landing_validation.py\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate V7.6 Sub-A dynamic budget landing candidate.")
    parser.add_argument("--source-run-dir", default=str(SOURCE_RUN_DIR))
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    write_outputs(args.run_dir, args.source_run_dir)
    ranked = pd.read_csv(Path(args.run_dir) / "ranked_validation.csv")
    print(ranked.head(12).to_string(index=False))
    print(f"WROTE {Path(args.run_dir) / 'record.md'}")


if __name__ == "__main__":
    main()

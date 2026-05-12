from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import build_v76_portfolio_nav as portfolio
import run_v76_adk_b_subd_dynamic_budget_optimization as sleeve_scan


ROOT = Path(__file__).resolve().parent
DEFAULT_RETURNS = (
    ROOT
    / "quant_param_scan_runs"
    / "20260512_v76_five_sleeve_real_subd_v16_rebalance_validation"
    / "aligned_five_sleeve_real_subd_returns.csv"
)
DEFAULT_MANIFEST = ROOT / "portfolio_manifests" / "v76_current.json"
DEFAULT_RUN_DIR = (
    ROOT
    / "quant_param_scan_runs"
    / "20260512_v76_level8_v7_6_five_sleeve_suba_subd_combined_dynamic_budget_selected_candidate_interaction_cost"
)
BASELINE = "fixed_10_15_15_20_40"
COST_BPS = [0, 5, 10, 20]
WINDOW_WEIGHTS = sleeve_scan.WINDOW_WEIGHTS


def _token_pct(value: float) -> str:
    return str(int(round(value * 100)))


def selected_candidate_grid(cost_bps_values: list[int] | None = None) -> pd.DataFrame:
    costs = list(cost_bps_values or COST_BPS)
    templates = [
        {
            "candidate": "suba_dd_5_8_weekly_step5",
            "rules": [
                {"sleeve": "Sub-A", "boost_dd": 0.05, "cut_dd": 0.08, "execution": "weekly", "step": 0.05}
            ],
        },
        {
            "candidate": "suba_dd_7_8_weekly_step5",
            "rules": [
                {"sleeve": "Sub-A", "boost_dd": 0.07, "cut_dd": 0.08, "execution": "weekly", "step": 0.05}
            ],
        },
        {
            "candidate": "subd_dd_7_8_weekly_step5",
            "rules": [
                {"sleeve": "Sub-D", "boost_dd": 0.07, "cut_dd": 0.08, "execution": "weekly", "step": 0.05}
            ],
        },
        {
            "candidate": "suba_dd_5_8_plus_subd_dd_7_8_weekly_step5",
            "rules": [
                {"sleeve": "Sub-A", "boost_dd": 0.05, "cut_dd": 0.08, "execution": "weekly", "step": 0.05},
                {"sleeve": "Sub-D", "boost_dd": 0.07, "cut_dd": 0.08, "execution": "weekly", "step": 0.05},
            ],
        },
        {
            "candidate": "suba_dd_7_8_plus_subd_dd_7_8_weekly_step5",
            "rules": [
                {"sleeve": "Sub-A", "boost_dd": 0.07, "cut_dd": 0.08, "execution": "weekly", "step": 0.05},
                {"sleeve": "Sub-D", "boost_dd": 0.07, "cut_dd": 0.08, "execution": "weekly", "step": 0.05},
            ],
        },
    ]
    rows = []
    for template in templates:
        for cost_bps in costs:
            candidate = f"{template['candidate']}_cost{int(cost_bps)}bps"
            rows.append(
                {
                    "candidate": candidate,
                    "scenario": template["candidate"],
                    "rules_json": json.dumps(template["rules"], ensure_ascii=False, sort_keys=True),
                    "cost_bps": int(cost_bps),
                }
            )
    return pd.DataFrame(rows)


def build_selected_dynamic_weights(
    ret_df: pd.DataFrame,
    weights: dict[str, float],
    rules: list[dict[str, object]],
    absorber: str = "Sub-B",
) -> pd.DataFrame:
    if absorber not in weights:
        raise ValueError(f"Manifest is missing absorber weight: {absorber}")
    sleeves = [str(rule["sleeve"]) for rule in rules]
    if absorber in sleeves:
        raise ValueError("Selected dynamic sleeves cannot include the absorber")
    if len(set(sleeves)) != len(sleeves):
        raise ValueError("Selected dynamic sleeves must be unique")
    missing = [sleeve for sleeve in sleeves if sleeve not in weights]
    if missing:
        raise ValueError(f"Manifest is missing sleeve weights: {', '.join(missing)}")

    dynamic = pd.DataFrame(weights, index=ret_df.index, dtype=float)
    total_delta = pd.Series(0.0, index=ret_df.index, dtype=float)
    for rule in rules:
        sleeve = str(rule["sleeve"])
        base = float(weights[sleeve])
        boost_dd = float(rule["boost_dd"])
        cut_dd = float(rule["cut_dd"])
        step = float(rule["step"])
        target = portfolio.sleeve_target_by_prior_dd(
            ret_df,
            sleeve,
            boost_dd=boost_dd,
            cut_dd=cut_dd,
            base=base,
            boost=base + step,
            cut=max(base - step, 0.0),
        )
        mask = portfolio.execution_mask(ret_df.index, str(rule["execution"]))
        executed = pd.Series(np.nan, index=ret_df.index, dtype=float)
        executed.iloc[0] = base
        executed.loc[mask] = target.loc[mask]
        executed = executed.ffill()
        dynamic[sleeve] = executed
        total_delta = total_delta + (executed - base)

    dynamic[absorber] = float(weights[absorber]) - total_delta
    dynamic = dynamic[list(weights)]
    if (dynamic < -1e-12).any().any():
        raise ValueError("Dynamic weights produced a negative sleeve weight")
    if not np.allclose(dynamic.sum(axis=1).to_numpy(), 1.0):
        raise ValueError("Dynamic weights must sum to 1.0 on every date")
    return dynamic


def _apply_allocation_cost(nav_df: pd.DataFrame, weights_df: pd.DataFrame, cost_bps: int) -> pd.DataFrame:
    if cost_bps <= 0:
        return nav_df
    turnover = weights_df.diff().abs().sum(axis=1).fillna(0.0)
    ret = nav_df["portfolio_return"] - turnover * cost_bps / 10000.0
    return pd.DataFrame({"portfolio_return": ret, "portfolio_nav": (1.0 + ret).cumprod()}, index=nav_df.index)


def add_baseline_rows(ret_df: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    nav = portfolio.build_portfolio_nav(ret_df, weights)
    metrics = portfolio.build_window_metrics(nav)
    metrics.insert(0, "candidate", BASELINE)
    metrics["scenario"] = "fixed"
    metrics["rules_json"] = "[]"
    metrics["cost_bps"] = 0
    metrics["avg_suba"] = np.nan
    metrics["latest_suba"] = np.nan
    metrics["avg_subd"] = np.nan
    metrics["latest_subd"] = np.nan
    metrics["latest_subb"] = float(weights["Sub-B"])
    metrics["rebalance_count"] = 0
    metrics["allocation_turnover"] = 0.0
    return metrics


def run_candidate_set(ret_df: pd.DataFrame, weights: dict[str, float], grid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for candidate in grid.to_dict("records"):
        rules = json.loads(candidate["rules_json"])
        weights_df = build_selected_dynamic_weights(ret_df, weights, rules)
        nav = portfolio.build_portfolio_nav_from_weight_frame(ret_df, weights_df)
        nav = _apply_allocation_cost(nav, weights_df, int(candidate["cost_bps"]))
        metrics = portfolio.build_window_metrics(nav)
        metrics.insert(0, "candidate", candidate["candidate"])
        metrics["scenario"] = candidate["scenario"]
        metrics["rules_json"] = candidate["rules_json"]
        metrics["cost_bps"] = int(candidate["cost_bps"])
        metrics["avg_suba"] = float(weights_df["Sub-A"].mean())
        metrics["latest_suba"] = float(weights_df["Sub-A"].iloc[-1])
        metrics["avg_subd"] = float(weights_df["Sub-D"].mean())
        metrics["latest_subd"] = float(weights_df["Sub-D"].iloc[-1])
        metrics["latest_subb"] = float(weights_df["Sub-B"].iloc[-1])
        metrics["rebalance_count"] = portfolio.rebalance_count(weights_df)
        metrics["allocation_turnover"] = portfolio.allocation_turnover(weights_df)
        rows.append(metrics)
    return pd.concat(rows, ignore_index=True)


def build_scan_summary(long_metrics: pd.DataFrame) -> pd.DataFrame:
    baseline = long_metrics[long_metrics["candidate"] == BASELINE].set_index("segment")
    rows = []
    for candidate, group in long_metrics.groupby("candidate", sort=False):
        full = group[group["segment"] == "full"].iloc[0]
        row = full.to_dict()
        score = 0.0
        for segment, weight in WINDOW_WEIGHTS.items():
            segment_row = group[group["segment"] == segment].iloc[0]
            base_row = baseline.loc[segment]
            ann_delta = float(segment_row["annual_return"] - base_row["annual_return"])
            sharpe_delta = float(segment_row["sharpe"] - base_row["sharpe"])
            maxdd_delta = float(segment_row["max_dd"] - base_row["max_dd"])
            score += weight * (ann_delta * 4.0 + sharpe_delta * 0.3 + maxdd_delta * 2.0)
            row[f"{segment}_annual_delta"] = ann_delta
            row[f"{segment}_maxdd_delta"] = maxdd_delta
            row[f"{segment}_sharpe_delta"] = sharpe_delta
        row["recent_weighted_score"] = score
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["recent_weighted_score", "sharpe"], ascending=[False, False])


def to_window_metrics_wide(long_metrics: pd.DataFrame) -> pd.DataFrame:
    parameter_cols = [
        "candidate",
        "scenario",
        "rules_json",
        "cost_bps",
        "avg_suba",
        "latest_suba",
        "avg_subd",
        "latest_subd",
        "latest_subb",
        "rebalance_count",
        "allocation_turnover",
    ]
    rows = []
    for _candidate, group in long_metrics.groupby("candidate", sort=False):
        wide = group.iloc[0][parameter_cols].to_dict()
        for _, row in group.iterrows():
            segment = row["segment"]
            wide[f"ann_return_{segment}"] = row["annual_return"]
            wide[f"ann_vol_{segment}"] = row["annual_vol"]
            wide[f"sharpe_repo_{segment}"] = row["sharpe"]
            wide[f"max_dd_{segment}"] = row["max_dd"]
            wide[f"rows_{segment}"] = row["rows"]
        rows.append(wide)
    return pd.DataFrame(rows)


def _fmt_pct(value: float) -> str:
    return f"{value:.2%}" if not pd.isna(value) else "n/a"


def render_record(ranked: pd.DataFrame, run_dir: Path) -> str:
    candidates = ranked[ranked["candidate"] != BASELINE].copy()
    best = candidates.iloc[0]
    lines = [
        "# V7.6 Sub-A/Sub-D Dynamic Budget Interaction Validation",
        "",
        "## Run Metadata",
        "",
        "- Project: V7.6 Level-8 five-sleeve portfolio.",
        "- Entrypoint: `run_v76_suba_subd_dynamic_budget_interaction_validation.py`.",
        "- Source-change rule: no production strategy defaults are changed by this validation.",
        "",
        "## Research Question",
        "",
        "Validate whether the selected Sub-A dynamic-budget candidate and selected Sub-D candidate remain useful alone and together after cost pressure.",
        "",
        "## Implementation Anchor",
        "",
        "- Input returns: `quant_param_scan_runs/20260512_v76_five_sleeve_real_subd_v16_rebalance_validation/aligned_five_sleeve_real_subd_returns.csv`.",
        "- Manifest: `portfolio_manifests/v76_current.json`.",
        "- Portfolio math reuses `build_v76_portfolio_nav.py` helpers.",
        "",
        "## Data Snapshot",
        "",
        "- Common daily aligned sleeve-return sample: 2011-12-09 to 2026-05-08.",
        "- Baseline weights: Sub-A 10%, Sub-A-DK 15%, Microcap 15%, Sub-D 20%, Sub-B 40%.",
        "",
        "## Cost and Execution Assumptions",
        "",
        "- Daily return cost stress: allocation turnover times cost bps / 10000.",
        "- Cost bps grid: 0, 5, 10, 20.",
        "- Selected dynamic rules execute weekly and use only each sleeve's prior NAV drawdown.",
        "- Sub-B absorbs the total weight delta when Sub-A and Sub-D are both dynamic.",
        "",
        "## Candidates",
        "",
        "- Sub-A selected family: `5/8 weekly step5`, plus neighbor `7/8 weekly step5`.",
        "- Sub-D selected family: `7/8 weekly step5`.",
        "- Combined candidates: Sub-A selected family plus Sub-D selected family together.",
        "",
        "## Best Candidate",
        "",
        f"- `{best['candidate']}`",
        f"- Full annual: {_fmt_pct(float(best['annual_return']))}",
        f"- Full maxDD: {_fmt_pct(float(best['max_dd']))}",
        f"- Full Sharpe: {float(best['sharpe']):.2f}",
        f"- 1Y annual delta: {_fmt_pct(float(best['last_1y_annual_delta']))}",
        f"- 1Y Sharpe delta: {float(best['last_1y_sharpe_delta']):+.2f}",
        f"- Turnover: {float(best['allocation_turnover']):.1f}",
        "",
        "## Ranked Summary",
        "",
        "| Candidate | Cost | Full annual | Full maxDD | Full Sharpe | 5Y ann delta | 3Y ann delta | 1Y ann delta | Score |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in candidates.head(12).iterrows():
        lines.append(
            f"| `{row['candidate']}` | {int(row['cost_bps'])} bps | "
            f"{_fmt_pct(float(row['annual_return']))} | {_fmt_pct(float(row['max_dd']))} | "
            f"{float(row['sharpe']):.2f} | {_fmt_pct(float(row['last_5y_annual_delta']))} | "
            f"{_fmt_pct(float(row['last_3y_annual_delta']))} | "
            f"{_fmt_pct(float(row['last_1y_annual_delta']))} | "
            f"{float(row['recent_weighted_score']):.4f} |"
        )
    lines.extend(
        [
            "",
            "## Stability Classification",
            "",
            "interaction candidate evidence; do not promote by default.",
            "",
            "## Decision",
            "",
            "Candidate evidence only. Sub-A alone remains the cleaner broad-window candidate; adding Sub-D together should be treated as an interaction candidate and not promoted until robustness and display complexity are reviewed.",
            "",
            "## Output Files",
            "",
            f"- `{(run_dir / 'scan_summary.csv').as_posix()}`",
            f"- `{(run_dir / 'window_metrics.csv').as_posix()}`",
            f"- `{(run_dir / 'scan_meta.json').as_posix()}`",
        ]
    )
    return "\n".join(lines)


def write_outputs(
    run_dir: str | Path,
    ret_df: pd.DataFrame,
    weights: dict[str, float],
    grid: pd.DataFrame,
    returns_path: str | Path,
    manifest_path: str | Path,
) -> None:
    out = Path(run_dir)
    out.mkdir(parents=True, exist_ok=True)
    candidate_metrics = run_candidate_set(ret_df, weights, grid)
    long_metrics = pd.concat([add_baseline_rows(ret_df, weights), candidate_metrics], ignore_index=True)
    ranked = build_scan_summary(long_metrics)
    scan_summary = long_metrics.copy()
    scan_summary["ann_return"] = scan_summary["annual_return"]
    scan_summary["ann_vol"] = scan_summary["annual_vol"]
    scan_summary["sharpe_repo"] = scan_summary["sharpe"]
    scan_summary.to_csv(out / "scan_summary.csv", index=False, encoding="utf-8-sig")
    to_window_metrics_wide(long_metrics).to_csv(out / "window_metrics.csv", index=False, encoding="utf-8-sig")
    meta = {
        "run_id": out.name,
        "created_at": "2026-05-12",
        "project": "v76_level8",
        "repo_root": str(ROOT),
        "strategy": "V7.6 five-sleeve",
        "subsystem": "SubA_SubD_combined_dynamic_budget",
        "git_branch": "",
        "git_commit": "",
        "git_status_before": "",
        "git_status_after": "",
        "scan_type": "selected_candidate_interaction_validation",
        "parameter_group": "selected_candidate_interaction_cost",
        "entrypoint": "run_v76_suba_subd_dynamic_budget_interaction_validation.py",
        "baseline": {"candidate": BASELINE, "weights": weights},
        "candidate_grid": grid.to_dict("records"),
        "data_snapshot": {
            "returns_source": str(Path(returns_path)),
            "manifest": str(Path(manifest_path)),
            "rows": int(len(ret_df)),
            "start": ret_df.index[0].date().isoformat(),
            "end": ret_df.index[-1].date().isoformat(),
        },
        "returns_source": str(Path(returns_path)),
        "manifest": str(Path(manifest_path)),
        "rows": int(len(ret_df)),
        "start": ret_df.index[0].date().isoformat(),
        "end": ret_df.index[-1].date().isoformat(),
        "cost_model": {
            "formula": "allocation_turnover * cost_bps / 10000 subtracted from daily portfolio return",
            "cost_bps_values": sorted(int(v) for v in grid["cost_bps"].unique()),
        },
        "timing": "target for date t uses each sleeve NAV drawdown through t-1; selected candidates execute weekly",
        "outputs": {
            "scan_summary": str(out / "scan_summary.csv"),
            "window_metrics": str(out / "window_metrics.csv"),
            "record": str(out / "record.md"),
            "scan_meta": str(out / "scan_meta.json"),
            "command_log": str(out / "command_log.txt"),
        },
        "decision": "candidate evidence only; Sub-A alone is cleaner broad-window candidate, combined Sub-A/Sub-D requires more validation",
        "stability_label": "interaction candidate evidence; do not promote by default",
    }
    (out / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "record.md").write_text(render_record(ranked, out), encoding="utf-8")
    (out / "command_log.txt").write_text(
        "python run_v76_suba_subd_dynamic_budget_interaction_validation.py\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate selected V7.6 Sub-A/Sub-D dynamic budget interactions.")
    parser.add_argument("--returns", default=str(DEFAULT_RETURNS))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = portfolio.load_manifest(args.manifest)
    returns = portfolio.load_aligned_returns(args.returns)
    grid = selected_candidate_grid()
    write_outputs(args.run_dir, returns, manifest.weights, grid, args.returns, args.manifest)
    ranked = build_scan_summary(pd.read_csv(Path(args.run_dir) / "scan_summary.csv"))
    print(ranked.head(12).to_string(index=False))
    print(f"WROTE {Path(args.run_dir) / 'scan_summary.csv'}")
    print(f"WROTE {Path(args.run_dir) / 'window_metrics.csv'}")
    print(f"WROTE {Path(args.run_dir) / 'record.md'}")


if __name__ == "__main__":
    main()

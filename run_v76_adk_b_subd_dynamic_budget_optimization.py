from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import build_v76_portfolio_nav as portfolio


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
    / "20260512_v76_level8_v7_6_five_sleeve_a_adk_b_subd_dynamic_budget_prior_nav_dd_threshold_execution_step"
)
WINDOW_WEIGHTS = {
    "full": 0.10,
    "last_10y": 0.15,
    "last_5y": 0.25,
    "last_3y": 0.30,
    "last_1y": 0.20,
}
SCAN_SLEEVES = ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-D"]


def _token_pct(value: float) -> str:
    return str(int(round(value * 100)))


def candidate_name(
    sleeve: str,
    boost_dd: float,
    cut_dd: float,
    execution: str,
    step: float,
    cost_bps: int,
) -> str:
    clean = sleeve.lower().replace("-", "")
    return (
        f"advisory_{clean}_dd_{_token_pct(boost_dd)}_{_token_pct(cut_dd)}_"
        f"{execution}_step{_token_pct(step)}_cost{int(cost_bps)}bps"
    )


def build_candidate_grid(
    sleeves: list[str] | None = None,
    boost_dd_values: list[float] | None = None,
    cut_dd_values: list[float] | None = None,
    executions: list[str] | None = None,
    steps: list[float] | None = None,
    cost_bps_values: list[int] | None = None,
) -> pd.DataFrame:
    sleeve_values = list(sleeves or SCAN_SLEEVES)
    boost_values = list(boost_dd_values or [0.02, 0.03, 0.05, 0.07])
    cut_values = list(cut_dd_values or [0.08, 0.10, 0.12, 0.15])
    execution_values = list(executions or ["daily", "weekly", "month_end"])
    step_values = list(steps or [0.025, 0.05])
    cost_values = list(cost_bps_values or [0, 5, 10, 20])
    rows = []
    for sleeve in sleeve_values:
        for boost_dd in boost_values:
            for cut_dd in cut_values:
                if boost_dd >= cut_dd:
                    continue
                for execution in execution_values:
                    for step in step_values:
                        for cost_bps in cost_values:
                            rows.append(
                                {
                                    "candidate": candidate_name(
                                        sleeve, boost_dd, cut_dd, execution, step, cost_bps
                                    ),
                                    "dynamic_sleeve": sleeve,
                                    "boost_dd": boost_dd,
                                    "cut_dd": cut_dd,
                                    "execution": execution,
                                    "step": step,
                                    "cost_bps": int(cost_bps),
                                }
                            )
    return pd.DataFrame(rows)


def _subb_absorber_group(weights: dict[str, float]) -> list[str]:
    return [name for name in weights if name != "Sub-B"]


def _scale_absorber_group(
    dynamic: pd.DataFrame,
    weights: dict[str, float],
    absorber_group: list[str],
    delta: pd.Series,
) -> pd.DataFrame:
    group_total = sum(weights[name] for name in absorber_group)
    if group_total <= 0:
        raise ValueError("Absorber group has no base weight")
    for name in absorber_group:
        share = weights[name] / group_total
        dynamic[name] = weights[name] - delta * share
    return dynamic


def build_dynamic_budget_weights(
    ret_df: pd.DataFrame,
    weights: dict[str, float],
    dynamic_sleeve: str,
    execution: str,
    boost_dd: float,
    cut_dd: float,
    step: float,
) -> pd.DataFrame:
    if dynamic_sleeve != "Sub-B":
        return portfolio.build_dynamic_sleeve_weights(
            ret_df,
            weights,
            sleeve=dynamic_sleeve,
            absorber="Sub-B",
            execution=execution,
            boost_dd=boost_dd,
            cut_dd=cut_dd,
            step=step,
        )

    base = weights["Sub-B"]
    target = portfolio.sleeve_target_by_prior_dd(
        ret_df,
        "Sub-B",
        boost_dd=boost_dd,
        cut_dd=cut_dd,
        base=base,
        boost=base + step,
        cut=max(base - step, 0.0),
    )
    mask = portfolio.execution_mask(ret_df.index, execution)
    executed = pd.Series(np.nan, index=ret_df.index, dtype=float)
    executed.iloc[0] = base
    executed.loc[mask] = target.loc[mask]
    executed = executed.ffill()

    dynamic = pd.DataFrame(weights, index=ret_df.index, dtype=float)
    dynamic["Sub-B"] = executed
    delta = executed - base
    dynamic = _scale_absorber_group(dynamic, weights, _subb_absorber_group(weights), delta)
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
    cost = turnover * cost_bps / 10000.0
    ret = nav_df["portfolio_return"] - cost
    return pd.DataFrame(
        {
            "portfolio_return": ret,
            "portfolio_nav": (1.0 + ret).cumprod(),
        },
        index=nav_df.index,
    )


def run_candidate_set(
    ret_df: pd.DataFrame,
    weights: dict[str, float],
    grid: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for candidate in grid.to_dict("records"):
        weights_df = build_dynamic_budget_weights(
            ret_df,
            weights,
            dynamic_sleeve=candidate["dynamic_sleeve"],
            execution=candidate["execution"],
            boost_dd=float(candidate["boost_dd"]),
            cut_dd=float(candidate["cut_dd"]),
            step=float(candidate["step"]),
        )
        nav = portfolio.build_portfolio_nav_from_weight_frame(ret_df, weights_df)
        nav = _apply_allocation_cost(nav, weights_df, int(candidate["cost_bps"]))
        metrics = portfolio.build_window_metrics(nav)
        metrics.insert(0, "candidate", candidate["candidate"])
        metrics["dynamic_sleeve"] = candidate["dynamic_sleeve"]
        metrics["boost_dd"] = float(candidate["boost_dd"])
        metrics["cut_dd"] = float(candidate["cut_dd"])
        metrics["execution"] = candidate["execution"]
        metrics["step"] = float(candidate["step"])
        metrics["cost_bps"] = int(candidate["cost_bps"])
        metrics["avg_dynamic_sleeve"] = float(weights_df[candidate["dynamic_sleeve"]].mean())
        metrics["latest_dynamic_sleeve"] = float(weights_df[candidate["dynamic_sleeve"]].iloc[-1])
        metrics["rebalance_count"] = portfolio.rebalance_count(weights_df)
        metrics["allocation_turnover"] = portfolio.allocation_turnover(weights_df)
        rows.append(metrics)
    return pd.concat(rows, ignore_index=True)


def add_baseline_rows(ret_df: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    nav = portfolio.build_portfolio_nav(ret_df, weights)
    metrics = portfolio.build_window_metrics(nav)
    metrics.insert(0, "candidate", "fixed_10_15_15_20_40")
    metrics["dynamic_sleeve"] = "fixed"
    metrics["boost_dd"] = np.nan
    metrics["cut_dd"] = np.nan
    metrics["execution"] = "fixed"
    metrics["step"] = 0.0
    metrics["cost_bps"] = 0
    metrics["avg_dynamic_sleeve"] = np.nan
    metrics["latest_dynamic_sleeve"] = np.nan
    metrics["rebalance_count"] = 0
    metrics["allocation_turnover"] = 0.0
    return metrics


def build_scan_summary(window_metrics: pd.DataFrame) -> pd.DataFrame:
    baseline = window_metrics[window_metrics["candidate"] == "fixed_10_15_15_20_40"]
    baseline_by_segment = baseline.set_index("segment")
    rows = []
    for candidate, group in window_metrics.groupby("candidate", sort=False):
        full = group[group["segment"] == "full"].iloc[0]
        row = full.to_dict()
        score = 0.0
        for segment, weight in WINDOW_WEIGHTS.items():
            segment_row = group[group["segment"] == segment].iloc[0]
            base_row = baseline_by_segment.loc[segment]
            ann_delta = float(segment_row["annual_return"] - base_row["annual_return"])
            sharpe_delta = float(segment_row["sharpe"] - base_row["sharpe"])
            maxdd_delta = float(segment_row["max_dd"] - base_row["max_dd"])
            score += weight * (ann_delta * 4.0 + sharpe_delta * 0.3 + maxdd_delta * 2.0)
            row[f"{segment}_annual_delta"] = ann_delta
            row[f"{segment}_maxdd_delta"] = maxdd_delta
            row[f"{segment}_sharpe_delta"] = sharpe_delta
        row["recent_weighted_score"] = score
        rows.append(row)
    summary = pd.DataFrame(rows)
    return summary.sort_values(
        ["dynamic_sleeve", "recent_weighted_score", "sharpe"],
        ascending=[True, False, False],
    ).reset_index(drop=True)


def to_scan_summary_long(long_metrics: pd.DataFrame) -> pd.DataFrame:
    out = long_metrics.copy()
    out["ann_return"] = out["annual_return"]
    out["ann_vol"] = out["annual_vol"]
    out["sharpe_repo"] = out["sharpe"]
    return out


def to_window_metrics_wide(long_metrics: pd.DataFrame) -> pd.DataFrame:
    parameter_cols = [
        "candidate",
        "dynamic_sleeve",
        "boost_dd",
        "cut_dd",
        "execution",
        "step",
        "cost_bps",
        "avg_dynamic_sleeve",
        "latest_dynamic_sleeve",
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
    if pd.isna(value):
        return "n/a"
    return f"{value:.2%}"


def render_record(scan_summary: pd.DataFrame, window_metrics: pd.DataFrame, run_dir: Path) -> str:
    lines = [
        "# V7.6 A/ADK/B/Sub-D Dynamic Budget Optimization",
        "",
        "## Run Metadata",
        "",
        "- Project: V7.6 Level-8 five-sleeve portfolio.",
        "- Entrypoint: `run_v76_adk_b_subd_dynamic_budget_optimization.py`.",
        "- Source-change rule: no production strategy source defaults are changed by this scan.",
        "",
        "## Research Question",
        "",
        "Microcap's `3/10` dynamic budget rule should not be assumed to fit Sub-A, ADK, Sub-B, or Sub-D. This scan tests each sleeve against its own prior NAV drawdown state.",
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
        "- Sleeves: Sub-A, Sub-A-DK, Microcap v1.6, Sub-D v1.1, Sub-B.",
        "",
        "## Cost and Execution Assumptions",
        "",
        "- Daily return cost stress: allocation turnover times cost bps / 10000.",
        "- Cost bps grid: 0, 5, 10, 20.",
        "- Execution grid: daily, weekly, month-end.",
        "- Weight target for date t uses sleeve NAV drawdown through t-1.",
        "",
        "## Runtime Override Plan",
        "",
        "- Research-only runtime overlay on aligned return series.",
        "- No `mnt_bot V 7.6 plus.py` default is changed.",
        "",
        "## Commands",
        "",
        "- `python run_v76_adk_b_subd_dynamic_budget_optimization.py`",
        "",
        "## Output Files",
        "",
        f"- `{(run_dir / 'scan_summary.csv').as_posix()}`",
        f"- `{(run_dir / 'window_metrics.csv').as_posix()}`",
        f"- `{(run_dir / 'scan_meta.json').as_posix()}`",
        "",
        "## Full-Sample Results",
        "",
        "See `scan_summary.csv` for the full long-form table and `window_metrics.csv` for the wide comparison.",
        "",
        "## Window Results",
        "",
        "The table below shows the best candidate per sleeve under the recent-weighted score.",
        "",
        "## Microcap 3/10 Implicit Logic",
        "",
        "- Prior NAV drawdown within 3% means the sleeve is near its high-water mark, so risk budget can be boosted.",
        "- Prior NAV drawdown at or below -10% means the sleeve is materially underwater, so risk budget is cut.",
        "- The middle zone keeps the base weight to avoid reacting to ordinary noise.",
        "- This is a sleeve-state rule, not a universal parameter set.",
        "",
        "## Scan Design",
        "",
        "- Sleeves tested: Sub-A, Sub-A-DK, Sub-B, Sub-D.",
        "- Sub-A, ADK, and Sub-D use Sub-B as absorber.",
        "- Sub-B uses the other four sleeves as a proportional absorber group, because Sub-B cannot absorb its own weight delta.",
        "- Grid: boost DD 2/3/5/7%, cut DD 8/10/12/15%, execution daily/weekly/month-end, step 2.5/5pp, cost 0/5/10/20 bps.",
        "- Candidate weights use only prior sleeve NAV drawdown, so the signal timing is non-lookahead.",
        "",
        "## Best By Sleeve",
        "",
        "| Sleeve | Candidate | Cost | Full annual | Full maxDD | Full Sharpe | 1Y annual delta | 1Y Sharpe delta | Turnover | Switches |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    candidates = scan_summary[scan_summary["candidate"] != "fixed_10_15_15_20_40"]
    for sleeve, group in candidates.groupby("dynamic_sleeve"):
        best = group.sort_values("recent_weighted_score", ascending=False).iloc[0]
        lines.append(
            "| "
            f"{sleeve} | `{best['candidate']}` | {int(best['cost_bps'])} bps | "
            f"{_fmt_pct(float(best['annual_return']))} | "
            f"{_fmt_pct(float(best['max_dd']))} | "
            f"{float(best['sharpe']):.2f} | "
            f"{_fmt_pct(float(best['last_1y_annual_delta']))} | "
            f"{float(best['last_1y_sharpe_delta']):+.2f} | "
            f"{float(best['allocation_turnover']):.1f} | "
            f"{int(best['rebalance_count'])} |"
        )
    lines.extend(
        [
            "",
            "## Stability Classification",
            "",
            "candidate evidence; requires follow-up stability validation.",
            "",
            "## Decision",
            "",
            "Use this run as candidate-selection evidence only. Do not promote Sub-A, ADK, Sub-B, or Sub-D dynamic budget rules without a follow-up stability read against the chosen candidate's role and live display complexity.",
            "",
            "## User-Facing Summary",
            "",
            "Microcap's 3/10 rule is a valid framework seed, but Sub-A, ADK, Sub-B, and Sub-D require sleeve-specific parameters. In this run, Sub-A is the cleaner broad-window candidate, Sub-D is the stronger recent-window candidate, Sub-B is weak under this design, and ADK is only narrow-positive.",
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
    ranked_summary = build_scan_summary(long_metrics)
    scan_summary = to_scan_summary_long(long_metrics)
    window_metrics = to_window_metrics_wide(long_metrics)
    scan_summary.to_csv(out / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(out / "window_metrics.csv", index=False, encoding="utf-8-sig")
    meta = {
        "run_id": Path(run_dir).name,
        "created_at": "2026-05-12",
        "project": "v76_level8",
        "repo_root": str(ROOT),
        "strategy": "V7.6 five-sleeve",
        "subsystem": "A_ADK_B_SubD_dynamic_budget",
        "git_branch": "",
        "git_commit": "",
        "git_status_before": "",
        "git_status_after": "",
        "scan_type": "portfolio_dynamic_budget_parameter_scan",
        "parameter_group": "prior_nav_dd_threshold_execution_step",
        "entrypoint": "run_v76_adk_b_subd_dynamic_budget_optimization.py",
        "baseline": {"candidate": "fixed_10_15_15_20_40", "weights": weights},
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
        "timing": "target for date t uses sleeve NAV drawdown through t-1; execution can be daily, weekly, or month-end",
        "outputs": {
            "scan_summary": str(out / "scan_summary.csv"),
            "window_metrics": str(out / "window_metrics.csv"),
            "record": str(out / "record.md"),
            "scan_meta": str(out / "scan_meta.json"),
            "command_log": str(out / "command_log.txt"),
        },
        "decision": "candidate evidence only; Sub-A and Sub-D deserve follow-up stability validation, Sub-B is weak, ADK is narrow-positive",
        "stability_label": "candidate evidence; requires follow-up stability validation",
    }
    (out / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "record.md").write_text(render_record(ranked_summary, scan_summary, out), encoding="utf-8")
    (out / "command_log.txt").write_text(
        "python run_v76_adk_b_subd_dynamic_budget_optimization.py\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan V7.6 A/ADK/B/Sub-D dynamic budget parameters.")
    parser.add_argument("--returns", default=str(DEFAULT_RETURNS))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = portfolio.load_manifest(args.manifest)
    returns = portfolio.load_aligned_returns(args.returns)
    grid = build_candidate_grid()
    write_outputs(args.run_dir, returns, manifest.weights, grid, args.returns, args.manifest)
    summary = pd.read_csv(Path(args.run_dir) / "scan_summary.csv")
    print(summary.groupby("dynamic_sleeve").head(3).to_string(index=False))
    print(f"WROTE {Path(args.run_dir) / 'scan_summary.csv'}")
    print(f"WROTE {Path(args.run_dir) / 'window_metrics.csv'}")
    print(f"WROTE {Path(args.run_dir) / 'record.md'}")


if __name__ == "__main__":
    main()

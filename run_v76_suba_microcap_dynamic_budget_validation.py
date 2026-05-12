from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import build_v76_portfolio_nav as portfolio_nav


ROOT = Path(__file__).resolve().parent
RUN_DIR = (
    ROOT
    / "quant_param_scan_runs"
    / "20260512_v76_five_sleeve_combo_dynamic_budget_suba_microcap_threshold_execution_cost"
)
RETURNS_PATH = portfolio_nav.DEFAULT_RETURNS
MANIFEST_PATH = portfolio_nav.DEFAULT_MANIFEST
BANDS = [
    ("dd_3_10", 0.03, 0.10),
    ("dd_5_10", 0.05, 0.10),
    ("dd_5_12", 0.05, 0.12),
]
EXECUTIONS = ["daily", "weekly", "month_end"]
COST_BPS = [0, 5, 10, 20]


@dataclass(frozen=True)
class DynamicRule:
    sleeve: str
    band: str
    boost_dd: float
    cut_dd: float
    execution: str
    step: float = 0.05


def _candidate_slug(text: str) -> str:
    return text.lower().replace("-", "")


def build_candidate_grid() -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = [
        {
            "candidate": "fixed_10_15_15_20_40_cost0bps",
            "rules": [],
            "cost_bps": 0,
            "candidate_type": "fixed",
        }
    ]
    for band, boost_dd, cut_dd in BANDS:
        for execution in EXECUTIONS:
            for cost_bps in COST_BPS:
                candidates.append(
                    {
                        "candidate": f"suba_{band}_{execution}_cost{cost_bps}bps",
                        "rules": [DynamicRule("Sub-A", band, boost_dd, cut_dd, execution)],
                        "cost_bps": cost_bps,
                        "candidate_type": "suba_only",
                    }
                )
                candidates.append(
                    {
                        "candidate": (
                            f"combo_suba_{band}_{execution}_microcap_dd_3_10_month_end_"
                            f"cost{cost_bps}bps"
                        ),
                        "rules": [
                            DynamicRule("Sub-A", band, boost_dd, cut_dd, execution),
                            DynamicRule("Microcap", "dd_3_10", 0.03, 0.10, "month_end"),
                        ],
                        "cost_bps": cost_bps,
                        "candidate_type": "suba_plus_microcap",
                    }
                )
    for cost_bps in COST_BPS:
        candidates.append(
            {
                "candidate": f"microcap_dd_3_10_month_end_cost{cost_bps}bps",
                "rules": [DynamicRule("Microcap", "dd_3_10", 0.03, 0.10, "month_end")],
                "cost_bps": cost_bps,
                "candidate_type": "microcap_only",
            }
        )
    return candidates


def build_multi_dynamic_weight_frame(
    ret_df: pd.DataFrame,
    weights: dict[str, float],
    rules: list[DynamicRule],
    absorber: str = "Sub-B",
) -> pd.DataFrame:
    if absorber not in weights:
        raise ValueError(f"Manifest is missing absorber weight: {absorber}")
    seen = set()
    dynamic = pd.DataFrame(weights, index=ret_df.index, dtype=float)
    total_delta = pd.Series(0.0, index=ret_df.index)
    for rule in rules:
        if rule.sleeve == absorber:
            raise ValueError("Dynamic sleeve and absorber must be different")
        if rule.sleeve in seen:
            raise ValueError(f"Duplicate dynamic rule for sleeve: {rule.sleeve}")
        if rule.sleeve not in weights:
            raise ValueError(f"Manifest is missing sleeve weight: {rule.sleeve}")
        seen.add(rule.sleeve)
        base = weights[rule.sleeve]
        target = portfolio_nav.sleeve_target_by_prior_dd(
            ret_df,
            rule.sleeve,
            boost_dd=rule.boost_dd,
            cut_dd=rule.cut_dd,
            base=base,
            boost=base + rule.step,
            cut=max(base - rule.step, 0.0),
        )
        mask = portfolio_nav.execution_mask(ret_df.index, rule.execution)
        executed = pd.Series(np.nan, index=ret_df.index, dtype=float)
        executed.iloc[0] = base
        executed.loc[mask] = target.loc[mask]
        executed = executed.ffill()
        dynamic[rule.sleeve] = executed
        total_delta = total_delta + (executed - base)
    dynamic[absorber] = weights[absorber] - total_delta
    dynamic = dynamic[list(weights)]
    if (dynamic < -1e-12).any().any():
        raise ValueError("Dynamic rules produced a negative sleeve weight")
    if not np.allclose(dynamic.sum(axis=1).to_numpy(), 1.0):
        raise ValueError("Dynamic rules must sum to 1.0 on every date")
    return dynamic


def build_costed_nav_from_weight_frame(
    ret_df: pd.DataFrame,
    weights_df: pd.DataFrame,
    cost_bps: float,
) -> pd.DataFrame:
    sleeve_returns = ret_df[list(weights_df.columns)].fillna(0.0)
    aligned_weights = weights_df.reindex(sleeve_returns.index).ffill()
    gross_return = sleeve_returns.mul(aligned_weights, axis=0).sum(axis=1)
    turnover = aligned_weights.diff().abs().sum(axis=1).fillna(0.0)
    cost = turnover * cost_bps / 10000.0
    portfolio_return = gross_return - cost
    return pd.DataFrame(
        {
            "gross_return": gross_return,
            "allocation_turnover": turnover,
            "allocation_cost": cost,
            "portfolio_return": portfolio_return,
            "portfolio_nav": (1.0 + portfolio_return).cumprod(),
        },
        index=ret_df.index,
    )


def summarize_candidate(
    nav_df: pd.DataFrame,
    weights_df: pd.DataFrame,
    candidate: dict[str, object],
) -> list[dict[str, object]]:
    rows = []
    rules = list(candidate["rules"])
    dynamic_sleeves = ",".join(rule.sleeve for rule in rules)
    bands = ",".join(rule.band for rule in rules)
    executions = ",".join(rule.execution for rule in rules)
    for segment, offset in portfolio_nav.WINDOWS.items():
        summary = portfolio_nav.summarize_nav(nav_df, segment, offset)
        part = nav_df if offset is None else nav_df.loc[nav_df.index >= nav_df.index[-1] - offset]
        row = {
            "candidate": candidate["candidate"],
            "segment": segment,
            "start": summary["start"],
            "end": summary["end"],
            "rows": summary["rows"],
            "ann_return": summary["annual_return"],
            "ann_vol": summary["annual_vol"],
            "sharpe_repo": summary["sharpe"],
            "max_dd": summary["max_dd"],
            "total_return": summary["total_return"],
            "candidate_type": candidate["candidate_type"],
            "dynamic_sleeves": dynamic_sleeves,
            "bands": bands,
            "executions": executions,
            "cost_bps": candidate["cost_bps"],
            "allocation_turnover_total": float(part["allocation_turnover"].sum()),
            "allocation_cost_total": float(part["allocation_cost"].sum()),
            "rebalance_count": int((part["allocation_turnover"] > 1e-12).sum()),
            "latest_suba_weight": float(weights_df["Sub-A"].iloc[-1]),
            "latest_microcap_weight": float(weights_df["Microcap"].iloc[-1]),
            "latest_subb_weight": float(weights_df["Sub-B"].iloc[-1]),
        }
        rows.append(row)
    return rows


def build_window_metrics(scan_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for candidate, group in scan_summary.groupby("candidate", sort=False):
        first = group.iloc[0]
        row = {
            "candidate": candidate,
            "candidate_type": first["candidate_type"],
            "dynamic_sleeves": first["dynamic_sleeves"],
            "bands": first["bands"],
            "executions": first["executions"],
            "cost_bps": first["cost_bps"],
        }
        for _, metric in group.iterrows():
            segment = metric["segment"]
            row[f"ann_return_{segment}"] = metric["ann_return"]
            row[f"ann_vol_{segment}"] = metric["ann_vol"]
            row[f"max_dd_{segment}"] = metric["max_dd"]
            row[f"sharpe_repo_{segment}"] = metric["sharpe_repo"]
            row[f"allocation_turnover_total_{segment}"] = metric["allocation_turnover_total"]
            row[f"allocation_cost_total_{segment}"] = metric["allocation_cost_total"]
            row[f"rebalance_count_{segment}"] = metric["rebalance_count"]
        rows.append(row)
    return pd.DataFrame(rows)


def build_weight_diagnostics(weight_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for candidate, weights_df in weight_frames.items():
        turnover = weights_df.diff().abs().sum(axis=1).fillna(0.0)
        rows.append(
            {
                "candidate": candidate,
                "avg_suba_weight": float(weights_df["Sub-A"].mean()),
                "avg_microcap_weight": float(weights_df["Microcap"].mean()),
                "avg_subb_weight": float(weights_df["Sub-B"].mean()),
                "latest_suba_weight": float(weights_df["Sub-A"].iloc[-1]),
                "latest_microcap_weight": float(weights_df["Microcap"].iloc[-1]),
                "latest_subb_weight": float(weights_df["Sub-B"].iloc[-1]),
                "allocation_turnover_total": float(turnover.sum()),
                "rebalance_count": int((turnover > 1e-12).sum()),
            }
        )
    return pd.DataFrame(rows)


def write_record(
    run_dir: Path,
    ret_df: pd.DataFrame,
    scan_summary: pd.DataFrame,
    window_metrics: pd.DataFrame,
) -> None:
    fixed = window_metrics[window_metrics["candidate"] == "fixed_10_15_15_20_40_cost0bps"].iloc[0]
    sortable = window_metrics[window_metrics["candidate"] != "fixed_10_15_15_20_40_cost0bps"].copy()
    sortable["full_sharpe_delta"] = sortable["sharpe_repo_full"] - fixed["sharpe_repo_full"]
    sortable["one_y_sharpe_delta"] = sortable["sharpe_repo_last_1y"] - fixed["sharpe_repo_last_1y"]
    top_full = sortable.sort_values(["full_sharpe_delta", "ann_return_full"], ascending=False).iloc[0]
    top_1y = sortable.sort_values(["one_y_sharpe_delta", "ann_return_last_1y"], ascending=False).iloc[0]
    record = "\n".join(
        [
            "# V7.6 Sub-A + Microcap Dynamic Budget Validation",
            "",
            "## Research Question",
            "",
            "Validate whether Sub-A dynamic budget should advance beyond first-pass advisory evidence, and whether combining it with the existing Microcap advisory improves the five-sleeve portfolio after allocation-turnover costs.",
            "",
            "## Data Snapshot",
            "",
            f"- Return source: `{portfolio_nav.output_path_metadata(RETURNS_PATH)}`",
            f"- Manifest: `{portfolio_nav.output_path_metadata(MANIFEST_PATH)}`",
            f"- Common start: `{ret_df.index[0].date().isoformat()}`",
            f"- Common end: `{ret_df.index[-1].date().isoformat()}`",
            f"- Rows: `{len(ret_df)}`",
            "- Sleeve returns are already net/costed at their own sleeve level where applicable.",
            "- Missing-market-session returns are treated as 0 inside the aligned five-sleeve return file.",
            "",
            "## Cost And Execution Assumptions",
            "",
            "- Dynamic signal uses only prior sleeve NAV drawdown through `t-1`.",
            "- Allocation execution variants: daily, weekly last available trading date, and confirmed calendar month-end.",
            "- Allocation cost: `daily_cost = sum(abs(delta weights)) * cost_bps / 10000`.",
            "- Tested allocation cost levels: `0, 5, 10, 20 bps`.",
            "- Sub-B absorbs all Sub-A and Microcap dynamic-budget deltas.",
            "- No production source default or executable weight was changed.",
            "",
            "## Candidate Grid",
            "",
            "- Baseline: fixed `10/15/15/20/40`.",
            "- Sub-A bands: `dd_3_10`, `dd_5_10`, `dd_5_12`.",
            "- Sub-A executions: daily, weekly, month_end.",
            "- Microcap advisory anchor: `dd_3_10_month_end`.",
            "- Combo candidates: Sub-A dynamic candidate plus Microcap `dd_3_10_month_end`.",
            "",
            "## Best Candidates",
            "",
            f"- Best full-sample Sharpe delta: `{top_full['candidate']}` = `{top_full['full_sharpe_delta']:+.4f}`.",
            f"- Best latest-1Y Sharpe delta: `{top_1y['candidate']}` = `{top_1y['one_y_sharpe_delta']:+.4f}`.",
            "",
            "## Output Files",
            "",
            "- `scan_summary.csv`",
            "- `window_metrics.csv`",
            "- `weight_diagnostics.csv`",
            "- `scan_meta.json`",
            "- `command_log.txt`",
            "",
            "## Decision",
            "",
            "Pending finalization after strict artifact check.",
            "",
            "## User-Facing Summary",
            "",
            "This run is a research-only validation of Sub-A dynamic budget and Sub-A+Microcap stacked advisory candidates. Use the CSVs for exact ranking.",
        ]
    )
    (run_dir / "record.md").write_text(record, encoding="utf-8")


def update_meta(run_dir: Path, ret_df: pd.DataFrame, candidates: list[dict[str, object]]) -> None:
    meta_path = run_dir / "scan_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "phase": "ran",
            "scan_type": "combo_dynamic_budget_threshold_execution_cost",
            "baseline": {"candidate": "fixed_10_15_15_20_40_cost0bps"},
            "candidate_grid": [
                {
                    "candidate": item["candidate"],
                    "candidate_type": item["candidate_type"],
                    "cost_bps": item["cost_bps"],
                    "rules": [rule.__dict__ for rule in item["rules"]],
                }
                for item in candidates
            ],
            "data_snapshot": {
                "returns_source": portfolio_nav.output_path_metadata(RETURNS_PATH),
                "manifest": portfolio_nav.output_path_metadata(MANIFEST_PATH),
                "start": ret_df.index[0].date().isoformat(),
                "end": ret_df.index[-1].date().isoformat(),
                "rows": int(len(ret_df)),
            },
            "cost_model": {
                "allocation_cost_formula": "sum(abs(delta_weights)) * cost_bps / 10000",
                "cost_bps": COST_BPS,
                "intra_sleeve_costs": "inherited from aligned sleeve return sources",
            },
        }
    )
    outputs = meta.setdefault("outputs", {})
    outputs["weight_diagnostics"] = str(run_dir / "weight_diagnostics.csv")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def append_command_log(run_dir: Path, message: str) -> None:
    with (run_dir / "command_log.txt").open("a", encoding="utf-8") as fh:
        fh.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] {message}\n")


def main() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    manifest = portfolio_nav.load_manifest(MANIFEST_PATH)
    ret_df = portfolio_nav.load_aligned_returns(RETURNS_PATH)
    candidates = build_candidate_grid()
    summary_rows = []
    weight_frames: dict[str, pd.DataFrame] = {}
    for candidate in candidates:
        weights_df = build_multi_dynamic_weight_frame(ret_df, manifest.weights, list(candidate["rules"]))
        nav_df = build_costed_nav_from_weight_frame(ret_df, weights_df, float(candidate["cost_bps"]))
        summary_rows.extend(summarize_candidate(nav_df, weights_df, candidate))
        weight_frames[str(candidate["candidate"])] = weights_df
    scan_summary = pd.DataFrame(summary_rows)
    window_metrics = build_window_metrics(scan_summary)
    weight_diagnostics = build_weight_diagnostics(weight_frames)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    weight_diagnostics.to_csv(RUN_DIR / "weight_diagnostics.csv", index=False, encoding="utf-8-sig")
    write_record(RUN_DIR, ret_df, scan_summary, window_metrics)
    update_meta(RUN_DIR, ret_df, candidates)
    append_command_log(RUN_DIR, "python run_v76_suba_microcap_dynamic_budget_validation.py")
    print(f"WROTE {RUN_DIR / 'scan_summary.csv'}")
    print(f"WROTE {RUN_DIR / 'window_metrics.csv'}")
    print(f"WROTE {RUN_DIR / 'weight_diagnostics.csv'}")


if __name__ == "__main__":
    main()

"""Fresh Layer 0/1 scan for ADK-style long SZ50 / short CYB spread.

Direction: long SZ50 price index (1.000016) / short CYB price index (0.399006).
Layer 1 intentionally scans signal families only. Later overlays such as target-vol,
NAV defense, same-side overheat, volume/amount gates, and momentum decay are left off.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_sz50_spread_long_only as base_scan

ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / "quant_param_scan_runs" / "20260609_adk_sz50_cyb_reverse_spread_long_only_v77_adk_reverse_spread_layer0_layer1_signal_family_spread_signal_window_threshold"


def build_candidate_returns(panel: pd.DataFrame, candidate: dict[str, object]) -> pd.DataFrame:
    ratio = panel["ratio"]
    family = str(candidate["family"])
    threshold = float(candidate.get("threshold", 0.0))
    weight_end = float(candidate.get("weight_end", 1.0))

    if family == "bias_momentum":
        bias_ma = int(candidate["bias_ma"])
        mom_day = int(candidate["mom_day"])
        feature = ratio / ratio.rolling(bias_ma).mean() - 1.0
        score = base_scan.weighted_slope_score(feature, mom_day, weight_end)
        r2 = base_scan.weighted_slope_r2(feature, mom_day, weight_end)
    elif family == "simple_momentum":
        mom_day = int(candidate["mom_day"])
        score = ratio.pct_change(mom_day) * 100.0
        r2 = pd.Series(1.0, index=ratio.index)
    elif family == "log_wls_momentum":
        mom_day = int(candidate["mom_day"])
        log_ratio = np.log(ratio)
        score = base_scan.weighted_slope_score(log_ratio, mom_day, weight_end)
        r2 = base_scan.weighted_slope_r2(log_ratio, mom_day, weight_end)
    else:
        raise ValueError(f"unknown family: {family}")

    raw_signal = ((score > threshold) & (r2 >= 0.05)).astype(float)
    exec_weight = raw_signal.shift(1).fillna(0.0)
    spread_return = panel["SZ50"].pct_change().fillna(0.0) - panel["CYB"].pct_change().fillna(0.0)
    turnover = exec_weight.diff().abs().fillna(exec_weight.abs())
    cost = turnover * (2.0 * base_scan.COMMISSION_ONE_WAY)
    ret = exec_weight * spread_return - cost
    out = pd.DataFrame(
        {
            "return": ret,
            "gross_return": exec_weight * spread_return,
            "cost": cost,
            "turnover": turnover,
            "weight": exec_weight,
            "raw_signal": raw_signal,
            "score": score,
            "r2": r2,
            "ratio": ratio,
            "spread_return": spread_return,
        },
        index=panel.index,
    )
    warmup = int(max(candidate.get("bias_ma", 0) or 0, candidate.get("mom_day", 0) or 0) + 2)
    return out.iloc[warmup:].copy()


def main() -> None:
    mod = base_scan.load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    sz50 = mod._load_cn_official_cache(mod.CN_DK_SZ50_SECID).rename(columns={"close": "SZ50"})
    panel = pd.concat([cyb["CYB"], sz50["SZ50"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base_scan.FORMAL_START].copy()
    panel["ratio"] = panel["SZ50"] / panel["CYB"]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = base_scan.candidate_grid()
    long_rows = []
    wide_rows = []
    daily_curves = []

    for candidate in grid:
        result = build_candidate_returns(panel, candidate)
        nav = (1.0 + result["return"]).cumprod()
        result_with_date = result.copy()
        result_with_date["nav"] = nav
        result_with_date["candidate"] = candidate["candidate"]
        daily_curves.append(result_with_date.reset_index(names="date"))

        wide = {**candidate}
        for segment, years in base_scan.SEGMENTS:
            m = base_scan.metrics_for_segment(result, segment, years)
            long_rows.append({**candidate, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = pd.DataFrame(wide_rows)
    daily = pd.concat(daily_curves, ignore_index=True)
    ridge = base_scan.build_width(window_metrics)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")

    top = window_metrics.sort_values("sharpe_repo_full", ascending=False).head(12)
    record_lines = [
        "# SZ50/CYB Reverse ADK Spread Layer 0/1 Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer1_complete_not_promoted`",
        "- stability: `layer1_width_pending_user_confirmation`",
        "",
        "## Research Question",
        "Fresh test of long SZ50 / short CYB as a standalone ADK-style spread sleeve.",
        "",
        "## Implementation Anchor",
        "- V7.7 constants and local cache loader imported from `mnt_bot V 7.7 plus.py` via the existing CYB/SZ50 scan harness.",
        "- Direction ratio: `1.000016 / 0.399006`.",
        "- Layer 1 scans signal family/window/weight only; later overlays are intentionally off.",
        "",
        "## Data Snapshot",
        f"- SZ50 rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- Timing: T close signal -> T+1 close-to-close spread return.",
        "- Return stream: SZ50 close-to-close return minus CYB close-to-close return.",
        f"- Transaction cost: two legs times one-way commission {base_scan.COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- Target-vol, NAV defense, overheat, amount gates, and momentum decay are off in this layer.",
        "- R2 quality filter is on at `0.05` for slope-based signal families.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_sz50_cyb_reverse_spread_long_only.py\"`",
        "- `python \"scan_adk_sz50_cyb_reverse_spread_long_only.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        top[["candidate", "family", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]].to_markdown(index=False),
        "",
        "## Window Results",
        "See `window_metrics.csv` for all candidates and required windows.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 1 completed but not promoted. Stop for user confirmation before dense Layer 1 patch or Layer 2 filters.",
        "",
        "## User-Facing Summary",
        "Use the top table and width diagnostics to choose whether to continue around the leading family.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "repo_root": str(ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_cyb_sz50_spread_long_only.py",
        "git_branch": "not_checked_agent_policy",
        "git_commit": "not_checked_agent_policy",
        "git_status_before": "not_checked_agent_policy",
        "git_status_after": "not_checked_agent_policy",
        "scan_type": "fresh_reverse_layer0_layer1_signal_family_scan",
        "parameter_group": "signal_family_spread_signal_window_threshold",
        "baseline": {"direction": "long_SZ50_short_CYB", "threshold": 0.0},
        "candidate_grid": grid,
        "cost_model": {"one_way_commission": base_scan.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return"},
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "sz50": {"secid": str(mod.CN_DK_SZ50_SECID), "rows": int(len(sz50)), "start": str(sz50.index.min().date()), "end": str(sz50.index.max().date())},
            "cyb": {"secid": str(mod.CN_DK_CYB_SECID), "rows": int(len(cyb)), "start": str(cyb.index.min().date()), "end": str(cyb.index.max().date())},
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
        },
        "decision": "layer1_complete_not_promoted",
        "stability_label": "layer1_width_pending_user_confirmation",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_sz50_cyb_reverse_spread_long_only.py\"\n"
        "python \"scan_adk_sz50_cyb_reverse_spread_long_only.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)}")
    print("TOP12")
    print(top[["candidate", "family", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]].to_string(index=False))
    print("WIDTH")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

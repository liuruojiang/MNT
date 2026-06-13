"""Layer 0/1 scan for ADK-style long CYB / short ZZ500 spread.

Direction: long ChiNext price index (0.399006) / short CSI 500 price index
(1.000905). This first layer scans signal families only. Target-vol, NAV
defense, overheat, amount/volume gates, and momentum decay are intentionally off.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from scan_adk_zz500_hs300_spread_long_only import (
    ANNUALIZATION_DAYS,
    COMMISSION_ONE_WAY,
    SEGMENTS,
    build_width,
    candidate_grid,
    git_text,
    load_v77,
    metrics_for_segment,
    weighted_slope_r2,
    weighted_slope_score,
    window_table,
)


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = ROOT / "mnt_bot V 7.7 plus.py"
RUN_DIR = ROOT / "quant_param_scan_runs" / "20260612_adk_cyb_zz500_spread_long_only_v77_adk_spread_layer0_layer1_signal_family"
FORMAL_START = pd.Timestamp("2010-06-01")
CYB_PUBLICATION_DATE = "2010-06-01"
ZZ500_PUBLICATION_DATE = "2007-01-15"


def build_candidate_returns(panel: pd.DataFrame, candidate: dict[str, object]) -> pd.DataFrame:
    ratio = panel["ratio"]
    family = str(candidate["family"])
    threshold = float(candidate.get("threshold", 0.0))
    weight_end = float(candidate.get("weight_end", 1.0))

    if family == "bias_momentum":
        bias_ma = int(candidate["bias_ma"])
        mom_day = int(candidate["mom_day"])
        feature = ratio / ratio.rolling(bias_ma).mean() - 1.0
        score = weighted_slope_score(feature, mom_day, weight_end)
        r2 = weighted_slope_r2(feature, mom_day, weight_end)
    elif family == "simple_momentum":
        mom_day = int(candidate["mom_day"])
        score = ratio.pct_change(mom_day) * 100.0
        r2 = pd.Series(1.0, index=ratio.index)
    elif family == "log_wls_momentum":
        mom_day = int(candidate["mom_day"])
        log_ratio = np.log(ratio)
        score = weighted_slope_score(log_ratio, mom_day, weight_end)
        r2 = weighted_slope_r2(log_ratio, mom_day, weight_end)
    else:
        raise ValueError(f"unknown family: {family}")

    raw_signal = ((score > threshold) & (r2 >= 0.05)).astype(float)
    exec_weight = raw_signal.shift(1).fillna(0.0)
    spread_return = panel["CYB"].pct_change().fillna(0.0) - panel["ZZ500"].pct_change().fillna(0.0)
    turnover = exec_weight.diff().abs().fillna(exec_weight.abs())
    cost = turnover * (2.0 * COMMISSION_ONE_WAY)
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


def build_always_on_returns(panel: pd.DataFrame) -> pd.DataFrame:
    spread_return = panel["CYB"].pct_change().fillna(0.0) - panel["ZZ500"].pct_change().fillna(0.0)
    exec_weight = pd.Series(1.0, index=panel.index)
    turnover = exec_weight.diff().abs().fillna(exec_weight.abs())
    cost = turnover * (2.0 * COMMISSION_ONE_WAY)
    ret = exec_weight * spread_return - cost
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": exec_weight * spread_return,
            "cost": cost,
            "turnover": turnover,
            "weight": exec_weight,
            "spread_return": spread_return,
        },
        index=panel.index,
    )


def build_no_signal_returns(panel: pd.DataFrame) -> pd.DataFrame:
    spread_return = panel["CYB"].pct_change().fillna(0.0) - panel["ZZ500"].pct_change().fillna(0.0)
    zeros = pd.Series(0.0, index=panel.index)
    return pd.DataFrame(
        {
            "return": zeros,
            "gross_return": zeros,
            "cost": zeros,
            "turnover": zeros,
            "weight": zeros,
            "spread_return": spread_return,
        },
        index=panel.index,
    )


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def pp(value: float) -> str:
    return f"{value * 100:+.2f}pp"


def baseline_comparison_table(top: pd.DataFrame, baseline_by_candidate: dict[str, dict[str, dict[str, object]]]) -> tuple[pd.DataFrame, str]:
    rows = []
    for _, row in top.head(12).iterrows():
        out = {"candidate": row["candidate"], "family": row["family"]}
        for segment, _years in SEGMENTS:
            ann = float(row[f"ann_return_{segment}"])
            dd = float(row[f"max_dd_{segment}"])
            baseline = baseline_by_candidate[str(row["candidate"])][segment]
            ann_delta = ann - float(baseline["ann_return"])
            dd_improve = dd - float(baseline["max_dd"])
            out[f"{segment}_ann"] = ann
            out[f"{segment}_max_dd"] = dd
            out[f"{segment}_ann_delta_vs_always_on"] = ann_delta
            out[f"{segment}_dd_improve_vs_always_on"] = dd_improve
        rows.append(out)
    compare = pd.DataFrame(rows)

    display = compare[["candidate", "family"]].copy()
    for segment, _years in SEGMENTS:
        display[segment] = compare.apply(
            lambda r: (
                f"{pct(float(r[f'{segment}_ann']))}/{pct(float(r[f'{segment}_max_dd']))} "
                f"({pp(float(r[f'{segment}_ann_delta_vs_always_on']))}, "
                f"{pp(float(r[f'{segment}_dd_improve_vs_always_on']))})"
            ),
            axis=1,
        )
    return compare, display.to_markdown(index=False)


def main() -> None:
    git_status_before = git_text(["status", "--short"])
    mod = load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    zz500 = mod._load_cn_official_cache(mod.CN_DK_ZZ500_SECID).rename(columns={"close": "ZZ500"})
    panel = pd.concat([cyb["CYB"], zz500["ZZ500"]], axis=1).dropna()
    raw_start = panel.index.min()
    panel = panel.loc[panel.index >= FORMAL_START].copy()
    panel["ratio"] = panel["CYB"] / panel["ZZ500"]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = candidate_grid()
    long_rows = []
    wide_rows = []
    daily_curves = []
    baseline_rows = []
    baseline_by_candidate: dict[str, dict[str, dict[str, object]]] = {}
    always_on = build_always_on_returns(panel)
    no_signal = build_no_signal_returns(panel)

    for candidate in grid:
        result = build_candidate_returns(panel, candidate)
        nav = (1.0 + result["return"]).cumprod()
        out = result.copy()
        out["nav"] = nav
        out["candidate"] = candidate["candidate"]
        daily_curves.append(out.reset_index(names="date"))

        wide = {**candidate}
        baseline_by_candidate[str(candidate["candidate"])] = {}
        for segment, years in SEGMENTS:
            m = metrics_for_segment(result, segment, years)
            always_m = metrics_for_segment(always_on.reindex(result.index), segment, years)
            no_signal_m = metrics_for_segment(no_signal.reindex(result.index), segment, years)
            baseline_by_candidate[str(candidate["candidate"])][segment] = always_m
            baseline_rows.append(
                {
                    **candidate,
                    "segment": segment,
                    "candidate_ann_return": m["ann_return"],
                    "candidate_max_dd": m["max_dd"],
                    "always_on_ann_return": always_m["ann_return"],
                    "always_on_max_dd": always_m["max_dd"],
                    "ann_return_delta_vs_always_on": float(m["ann_return"]) - float(always_m["ann_return"]),
                    "max_dd_improve_vs_always_on": float(m["max_dd"]) - float(always_m["max_dd"]),
                    "no_signal_ann_return": no_signal_m["ann_return"],
                    "no_signal_max_dd": no_signal_m["max_dd"],
                }
            )
            long_rows.append({**candidate, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = pd.DataFrame(wide_rows)
    daily = pd.concat(daily_curves, ignore_index=True)
    ridge = build_width(window_metrics)
    top = window_metrics.sort_values("sharpe_repo_full", ascending=False).head(20)
    baseline_comparison, baseline_table_md = baseline_comparison_table(top, baseline_by_candidate)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(baseline_rows).to_csv(RUN_DIR / "baseline_comparison_long.csv", index=False, encoding="utf-8-sig")
    baseline_comparison.to_csv(RUN_DIR / "baseline_comparison_top12.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# CYB/ZZ500 ADK Spread Layer 0/1 Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer0_layer1_complete_not_promoted`",
        "- stability: `signal_family_width_pending_user_confirmation`",
        "",
        "## Research Question",
        "Fresh first-layer test of long CYB / short ZZ500 as a standalone ADK-style spread sleeve.",
        "",
        "## Implementation Anchor",
        "- V7.7 constants and local cache loader imported from `mnt_bot V 7.7 plus.py`.",
        "- Direction ratio: `0.399006 / 1.000905`.",
        "- Layer 0/1 scans signal family, window, and recency weight only.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research with two-leg commissions, excluding futures basis, financing, borrow, and short locate costs.",
        "- Source-change rule: `research_only_new_scan_script`.",
        "",
        "## Data Snapshot",
        f"- CYB publication date: {CYB_PUBLICATION_DATE}; local rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- ZZ500 publication date: {ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Raw aligned data start: {raw_start.date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start rule: latest actual index publication/listing date among the two legs.",
        "- Adjustment mode: price index close from local official cache, no total-return substitution.",
        "",
        "## Cost and Execution Assumptions",
        "- Market: A-share index spread research using daily close data.",
        "- Trading calendar: aligned index dates from the two local cache series.",
        "- Timing: T close signal -> T+1 close-to-close spread return.",
        "- Return stream: CYB close-to-close return minus ZZ500 close-to-close return.",
        f"- Transaction cost: two legs times one-way commission {COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- Slippage, financing, borrow, futures basis, and short locate costs are excluded at this research layer.",
        "- Target-vol, NAV defense, overheat, amount/volume gates, and momentum decay are off.",
        "- R2 quality filter is on at `0.05` for slope-based signal families.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"CYB/ZZ500 spread Layer 0/1\" --parameter-group \"signal_family_spread_signal_window_threshold\" --repo . --entrypoint \"scan_adk_cyb_zz500_spread_long_only.py\" --date 2026-06-12 --slug \"adk_cyb_zz500_spread_long_only_v77_adk_spread_layer0_layer1_signal_family\"`",
        "- `python -m py_compile \"scan_adk_cyb_zz500_spread_long_only.py\"`",
        "- `python \"scan_adk_cyb_zz500_spread_long_only.py\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py <run_folder> --decision \"layer0_layer1_complete_not_promoted\" --stability-label \"signal_family_width_pending_user_confirmation\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>`",
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
        window_table(top, 12),
        "",
        "## Same-Line Baseline Comparison",
        "Baseline is always-on long CYB / short ZZ500 over each candidate's own executable rows. Cell format: `candidate ann/DD (delta ann, delta DD improvement)`. Positive DD delta means shallower drawdown than baseline.",
        "",
        baseline_table_md,
        "",
        "## Window Results",
        "The table above includes full, last_10y, last_5y, last_3y, and last_1y annualized return and max drawdown for the leading candidates. See `window_metrics.csv` for all candidates.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 0/1 completed but not promoted. Stop for user confirmation before any dense Layer 1 patch or Layer 2 filters.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "CYB/ZZ500 spread Layer 0/1",
        "repo_root": str(ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": str(ENTRYPOINT.name),
        "git_branch": git_text(["branch", "--show-current"]),
        "git_commit": git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": git_text(["status", "--short"]),
        "scan_type": "fresh_layer0_layer1_signal_family_scan",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "signal_family_spread_signal_window_threshold",
        "baseline": {"direction": "long_CYB_short_ZZ500", "threshold": 0.0},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "official_publication_sources": {
                "cyb": "local cache starts on published index date 2010-06-01",
                "zz500": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000905factsheet.pdf",
            },
            "cyb": {
                "secid": str(mod.CN_DK_CYB_SECID),
                "publication_date": CYB_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_CYB_SECID))),
                "rows": int(len(cyb)),
                "start": str(cyb.index.min().date()),
                "end": str(cyb.index.max().date()),
            },
            "zz500": {
                "secid": str(mod.CN_DK_ZZ500_SECID),
                "publication_date": ZZ500_PUBLICATION_DATE,
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
        "decision": "layer0_layer1_complete_not_promoted",
        "stability_label": "signal_family_width_pending_user_confirmation",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "baseline_comparison_long": str(RUN_DIR / "baseline_comparison_long.csv"),
            "baseline_comparison_top12": str(RUN_DIR / "baseline_comparison_top12.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"CYB/ZZ500 spread Layer 0/1\" --parameter-group \"signal_family_spread_signal_window_threshold\" --repo . --entrypoint \"scan_adk_cyb_zz500_spread_long_only.py\" --date 2026-06-12 --slug \"adk_cyb_zz500_spread_long_only_v77_adk_spread_layer0_layer1_signal_family\"\n"
        "python -m py_compile \"scan_adk_cyb_zz500_spread_long_only.py\"\n"
        "python \"scan_adk_cyb_zz500_spread_long_only.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"layer0_layer1_complete_not_promoted\" --stability-label \"signal_family_width_pending_user_confirmation\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict \"{RUN_DIR}\"\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("TOP12")
    print(
        top[
            [
                "candidate",
                "family",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "ann_return_last_10y",
                "max_dd_last_10y",
                "ann_return_last_5y",
                "max_dd_last_5y",
                "ann_return_last_3y",
                "max_dd_last_3y",
                "ann_return_last_1y",
                "max_dd_last_1y",
            ]
        ]
        .head(12)
        .to_string(index=False)
    )
    print("WIDTH")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

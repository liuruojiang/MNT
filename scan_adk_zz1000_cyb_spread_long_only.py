"""Fresh Layer 0/1 scan for ADK-style long ZZ1000 / short CYB spread.

Direction: long ZZ1000 price index (1.000852) / short CYB price index (0.399006).
Layer 1 intentionally scans signal families only. Later overlays such as target-vol,
NAV defense, same-side overheat, volume/amount gates, and momentum decay are left off.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np

import scan_adk_cyb_zz1000_spread_long_only as common


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = ROOT / "mnt_bot V 7.7 plus.py"
RUN_DIR = ROOT / "quant_param_scan_runs" / "20260611_adk_zz1000_cyb_spread_long_only_v77_adk_spread_layer0_layer1_signal_family_spread_signal_window_threshold"
ANNUALIZATION_DAYS = common.ANNUALIZATION_DAYS
FORMAL_START = pd.Timestamp("2014-10-17")
COMMISSION_ONE_WAY = common.COMMISSION_ONE_WAY
SEGMENTS = common.SEGMENTS


def load_v77():
    spec = importlib.util.spec_from_file_location("mnt_v77", ENTRYPOINT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def build_candidate_returns(base: pd.DataFrame, candidate: dict[str, object]) -> pd.DataFrame:
    ratio = base["ratio"]
    family = str(candidate["family"])
    threshold = float(candidate.get("threshold", 0.0))
    weight_end = float(candidate.get("weight_end", 1.0))

    if family == "bias_momentum":
        bias_ma = int(candidate["bias_ma"])
        mom_day = int(candidate["mom_day"])
        feature = ratio / ratio.rolling(bias_ma).mean() - 1.0
        score = common.weighted_slope_score(feature, mom_day, weight_end)
        r2 = common.weighted_slope_r2(feature, mom_day, weight_end)
    elif family == "simple_momentum":
        mom_day = int(candidate["mom_day"])
        score = ratio.pct_change(mom_day) * 100.0
        r2 = pd.Series(1.0, index=ratio.index)
    elif family == "log_wls_momentum":
        mom_day = int(candidate["mom_day"])
        score = common.weighted_slope_score(np.log(ratio), mom_day, weight_end)
        r2 = common.weighted_slope_r2(np.log(ratio), mom_day, weight_end)
    else:
        raise ValueError(f"unknown family: {family}")

    raw_signal = ((score > threshold) & (r2 >= 0.05)).astype(float)
    exec_weight = raw_signal.shift(1).fillna(0.0)
    spread_return = base["ZZ1000"].pct_change().fillna(0.0) - base["CYB"].pct_change().fillna(0.0)
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
        index=base.index,
    )
    warmup = int(max(candidate.get("bias_ma", 0) or 0, candidate.get("mom_day", 0) or 0) + 2)
    return out.iloc[warmup:].copy()


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def window_table(top: pd.DataFrame) -> str:
    cols = ["candidate", "family"]
    for segment, _years in SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = top[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    mod = load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    zz1000 = mod._load_cn_official_cache(mod.CN_DK_ZZ1000_SECID).rename(columns={"close": "ZZ1000"})
    base = pd.concat([zz1000["ZZ1000"], cyb["CYB"]], axis=1).dropna()
    base = base.loc[base.index >= FORMAL_START].copy()
    base["ratio"] = base["ZZ1000"] / base["CYB"]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = common.candidate_grid()
    long_rows = []
    wide_rows = []
    daily_curves = []

    for candidate in grid:
        result = build_candidate_returns(base, candidate)
        nav = (1.0 + result["return"]).cumprod()
        result_with_date = result.copy()
        result_with_date["nav"] = nav
        result_with_date["candidate"] = candidate["candidate"]
        daily_curves.append(result_with_date.reset_index(names="date"))

        wide = {**candidate}
        for segment, years in SEGMENTS:
            m = common.metrics_for_segment(result, segment, years)
            long_rows.append({**candidate, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = pd.DataFrame(wide_rows)
    daily = pd.concat(daily_curves, ignore_index=True)
    ridge = common.build_width(window_metrics)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")

    top = window_metrics.sort_values("sharpe_repo_full", ascending=False).head(12)
    top_display_cols = [
        "candidate",
        "family",
        "ann_return_full",
        "max_dd_full",
        "sharpe_repo_full",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "ann_return_last_1y",
        "max_dd_last_1y",
    ]
    record_lines = [
        "# ZZ1000/CYB Fresh ADK Spread Layer 0/1 Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer1_complete_not_promoted`",
        "- stability: `layer1_width_pending_user_confirmation`",
        "",
        "## Research Question",
        "Fresh test of long ZZ1000 / short CYB as a standalone ADK-style spread sleeve.",
        "",
        "## Implementation Anchor",
        "- V7.7 constants and local cache loader imported from `mnt_bot V 7.7 plus.py`.",
        "- Shared signal-family math reused from `scan_adk_cyb_zz1000_spread_long_only.py`; direction-specific ratio and return stream are rebuilt here.",
        "- Direction ratio: `1.000852 / 0.399006`.",
        "- Layer 1 scans signal family/window/weight only; later overlays are intentionally off.",
        "",
        "## Data Snapshot",
        f"- ZZ1000 rows: {len(zz1000)}, start {zz1000.index.min().date()}, end {zz1000.index.max().date()}.",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- Formal aligned rows: {len(base)}, start {base.index.min().date()}, end {base.index.max().date()}.",
        "- Formal start: `2014-10-17`, constrained by CSI 1000 publication date.",
        "",
        "## Cost and Execution Assumptions",
        "- Timing: T close signal -> T+1 close-to-close spread return.",
        "- Return stream: ZZ1000 close-to-close return minus CYB close-to-close return.",
        f"- Transaction cost: two legs times one-way commission {COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- Target-vol, NAV defense, overheat, amount gates, and momentum decay are off in this layer.",
        "- R2 quality filter is on at `0.05` for slope-based signal families.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_zz1000_cyb_spread_long_only.py\"`",
        "- `python \"scan_adk_zz1000_cyb_spread_long_only.py\"`",
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
        "## Top Full-Sample Results",
        top[top_display_cols].to_markdown(index=False),
        "",
        "## Required Window Results For Top Full-Sample Rows",
        window_table(top.head(8)),
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
        "implementation_anchor": str(ENTRYPOINT.name),
        "helper_module": "scan_adk_cyb_zz1000_spread_long_only.py",
        "git_branch": "dirty_worktree_not_cleaned",
        "git_commit": "not_recorded",
        "git_status_before": "dirty_worktree_with_prior_research_artifacts",
        "git_status_after": "dirty_worktree_with_prior_research_artifacts",
        "scan_type": "fresh_layer0_layer1_signal_family_scan",
        "parameter_group": "signal_family_spread_signal_window_threshold",
        "baseline": {"direction": "long_ZZ1000_short_CYB", "threshold": 0.0},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal -> T+1 close-to-close return",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "zz1000": {
                "secid": str(mod.CN_DK_ZZ1000_SECID),
                "rows": int(len(zz1000)),
                "start": str(zz1000.index.min().date()),
                "end": str(zz1000.index.max().date()),
                "publication_date": "2014-10-17",
            },
            "cyb": {
                "secid": str(mod.CN_DK_CYB_SECID),
                "rows": int(len(cyb)),
                "start": str(cyb.index.min().date()),
                "end": str(cyb.index.max().date()),
            },
            "formal": {
                "rows": int(len(base)),
                "start": str(base.index.min().date()),
                "end": str(base.index.max().date()),
                "start_rule": "latest actual publication/listing date; ZZ1000 publication 2014-10-17",
            },
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
        "python -m py_compile \"scan_adk_zz1000_cyb_spread_long_only.py\"\n"
        "python \"scan_adk_zz1000_cyb_spread_long_only.py\"\n"
        "python C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={base.index.min().date()}->{base.index.max().date()} rows={len(base)}")
    print("TOP12")
    print(top[top_display_cols].to_string(index=False))
    print("WIDTH")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

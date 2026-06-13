"""Layer 1 supplemental dense patch for ZZ500/CYB bias-momentum branch.

The primary Layer 1 dense run focused on the width-supported log-WLS ridge.
This supplemental scan keeps a performant, width-supported ratio-bias momentum
group alive for Layer 2 comparison.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_zz500_cyb_spread_layer1_dense_patch as l1dense
import scan_adk_zz500_cyb_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_zz500_cyb_spread_long_only_v77_adk_spread_layer1_bias_momentum_dense_patch"
WEIGHT_GRID = [2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75, 4.0, 4.25, 4.5]
PRIMARY_CARRY = "bias_ma010_mom029_we3p0_gt0"
RETURN_WATCH = "bias_ma014_mom026_we2p5_gt0"


def dense_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for bias_ma in range(5, 26):
        for mom_day in range(25, 34):
            for weight_end in WEIGHT_GRID:
                grid.append(
                    {
                        "candidate": f"bias_ma{bias_ma:03d}_mom{mom_day:03d}_we{str(weight_end).replace('.', 'p')}_gt0",
                        "family": "bias_momentum",
                        "branch": "bias_momentum_width_supplement",
                        "bias_ma": bias_ma,
                        "mom_day": mom_day,
                        "weight_end": weight_end,
                        "threshold": 0.0,
                    }
                )
    return grid


def build_candidate_returns(panel: pd.DataFrame, candidate: dict[str, object]) -> pd.DataFrame:
    ratio = panel["ratio"]
    bias_ma = int(candidate["bias_ma"])
    mom_day = int(candidate["mom_day"])
    weight_end = float(candidate["weight_end"])
    feature = ratio / ratio.rolling(bias_ma).mean() - 1.0
    score, r2 = l1dense.fast_weighted_slope_and_r2(feature, mom_day, weight_end)
    raw_signal = ((score > 0.0) & (r2 >= 0.05)).astype(float)
    exec_weight = raw_signal.shift(1).fillna(0.0)
    spread_return = panel["ZZ500"].pct_change().fillna(0.0) - panel["CYB"].pct_change().fillna(0.0)
    turnover = exec_weight.diff().abs().fillna(exec_weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    ret = exec_weight * spread_return - cost
    out = pd.DataFrame(
        {
            "return": ret,
            "gross_return": exec_weight * spread_return,
            "cost": cost,
            "turnover": turnover,
            "weight": exec_weight,
            "score": score,
            "r2": r2,
        },
        index=panel.index,
    )
    return out.iloc[max(bias_ma, mom_day) + 2 :].copy()


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def add_width_flags(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = window_metrics.copy()
    best_sharpe = float(df["sharpe_repo_full"].max())
    df["family80_pass"] = df["sharpe_repo_full"] >= best_sharpe * 0.8
    df["balanced_score"] = (
        df["sharpe_repo_full"]
        + df["ann_return_last_5y"].clip(lower=-0.05, upper=0.05)
        + df["ann_return_last_1y"].clip(lower=-0.10, upper=0.05) * 0.25
        + df["max_dd_full"].clip(lower=-0.35, upper=0.0) * 0.08
    )
    return df


def build_local_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = add_width_flags(window_metrics)
    rows = []
    min_bias, max_bias = int(df["bias_ma"].min()), int(df["bias_ma"].max())
    min_mom, max_mom = int(df["mom_day"].min()), int(df["mom_day"].max())
    min_weight, max_weight = float(df["weight_end"].min()), float(df["weight_end"].max())
    seeds = pd.concat(
        [
            df.sort_values("sharpe_repo_full", ascending=False).head(80),
            df.sort_values("balanced_score", ascending=False).head(80),
        ],
        ignore_index=True,
    ).drop_duplicates("candidate")
    for _, row in seeds.iterrows():
        nearby = df[
            (df["bias_ma"].sub(row["bias_ma"]).abs() <= 5)
            & (df["mom_day"].sub(row["mom_day"]).abs() <= 2)
            & (df["weight_end"].sub(row["weight_end"]).abs() <= 0.5)
        ]
        family80 = nearby[nearby["family80_pass"]]
        is_edge = bool(
            row["bias_ma"] in (min_bias, max_bias)
            or row["mom_day"] in (min_mom, max_mom)
            or float(row["weight_end"]) in (min_weight, max_weight)
        )
        width_supported = bool(
            len(family80) >= 4
            and family80["bias_ma"].nunique() >= 2
            and family80["mom_day"].nunique() >= 2
            and family80["weight_end"].nunique() >= 2
            and not is_edge
        )
        rows.append(
            {
                "candidate": row["candidate"],
                "family": row["family"],
                "branch": row["branch"],
                "bias_ma": int(row["bias_ma"]),
                "mom_day": int(row["mom_day"]),
                "weight_end": float(row["weight_end"]),
                "ann_return_full": float(row["ann_return_full"]),
                "max_dd_full": float(row["max_dd_full"]),
                "sharpe_repo_full": float(row["sharpe_repo_full"]),
                "ann_return_last_10y": float(row["ann_return_last_10y"]),
                "max_dd_last_10y": float(row["max_dd_last_10y"]),
                "ann_return_last_5y": float(row["ann_return_last_5y"]),
                "max_dd_last_5y": float(row["max_dd_last_5y"]),
                "ann_return_last_3y": float(row["ann_return_last_3y"]),
                "max_dd_last_3y": float(row["max_dd_last_3y"]),
                "ann_return_last_1y": float(row["ann_return_last_1y"]),
                "max_dd_last_1y": float(row["max_dd_last_1y"]),
                "nearby_count": int(len(nearby)),
                "nearby_family80_count": int(len(family80)),
                "nearby_family80_bias_count": int(family80["bias_ma"].nunique()),
                "nearby_family80_mom_count": int(family80["mom_day"].nunique()),
                "nearby_family80_weight_count": int(family80["weight_end"].nunique()),
                "edge_flag": is_edge,
                "width_supported": width_supported,
                "balanced_score": float(row["balanced_score"]),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["width_supported", "nearby_family80_count", "balanced_score"],
        ascending=[False, False, False],
    )


def build_axis_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    df = add_width_flags(window_metrics)
    rows = []
    for axis in ["bias_ma", "mom_day", "weight_end"]:
        for value, group in df.groupby(axis):
            best = group.sort_values("balanced_score", ascending=False).iloc[0]
            rows.append(
                {
                    "family": "bias_momentum",
                    "axis": axis,
                    "value": value,
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": float(best["ann_return_full"]),
                    "best_full_max_dd": float(best["max_dd_full"]),
                    "family80_count": int(group["family80_pass"].sum()),
                    "candidate_count": int(len(group)),
                }
            )
    return pd.DataFrame(rows)


def window_table(df: pd.DataFrame, n: int = 12) -> str:
    cols = ["candidate", "bias_ma", "mom_day", "weight_end"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod = base.load_v77()
    zz500 = mod._load_cn_official_cache(mod.CN_DK_ZZ500_SECID).rename(columns={"close": "ZZ500"})
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    panel = pd.concat([zz500["ZZ500"], cyb["CYB"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["ZZ500"] / panel["CYB"]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = dense_grid()
    long_rows = []
    wide_rows = []
    daily_rows = []

    for candidate in grid:
        result = build_candidate_returns(panel, candidate)
        nav = (1.0 + result["return"]).cumprod()
        daily_rows.append(
            pd.DataFrame(
                {
                    "date": result.index,
                    "candidate": candidate["candidate"],
                    "return": result["return"].to_numpy(),
                    "nav": nav.to_numpy(),
                    "weight": result["weight"].to_numpy(),
                    "cost": result["cost"].to_numpy(),
                }
            )
        )
        wide = {**candidate}
        for segment, years in base.SEGMENTS:
            m = base.metrics_for_segment(result, segment, years)
            long_rows.append({**candidate, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_width_flags(pd.DataFrame(wide_rows))
    daily = pd.concat(daily_rows, ignore_index=True)
    local_width = build_local_width(window_metrics)
    ridge = build_axis_width(window_metrics)
    top_sharpe = window_metrics.sort_values("sharpe_repo_full", ascending=False).head(30)
    width_candidates = local_width[local_width["width_supported"]].head(40)
    primary = local_width[local_width["candidate"].eq(PRIMARY_CARRY)]
    ret_watch = local_width[local_width["candidate"].eq(RETURN_WATCH)]
    carry = pd.concat(
        [
            primary,
            width_candidates.head(5),
            ret_watch,
        ],
        ignore_index=True,
    ).drop_duplicates("candidate").head(8)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    local_width.to_csv(RUN_DIR / "local_width.csv", index=False, encoding="utf-8-sig")
    width_candidates.to_csv(RUN_DIR / "width_candidates.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# ZZ500/CYB Layer 1 Bias-Momentum Dense Patch",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer1_bias_dense_complete_not_promoted`",
        "- stability: `bias_momentum_width_supported_secondary`",
        "",
        "## Research Question",
        "Supplement Layer 1 with a performant, width-supported ratio-bias momentum group before Layer 2.",
        "",
        "## Layer Inputs",
        "- Dense grid: `bias_ma=5..25`, `mom_day=25..33`, `weight_end=2.0..4.5`.",
        "- Signal: weighted slope of `ZZ500/CYB / MA(bias_ma) - 1`, threshold `score > 0`, R2 `>= 0.05`.",
        f"- Preferred balanced carry: `{PRIMARY_CARRY}`.",
        f"- Return-heavy watch line: `{RETURN_WATCH}`.",
        "",
        "## Data Snapshot",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- CYB publication date: {base.CYB_PUBLICATION_DATE}; local rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal -> T+1 close-to-close spread return.",
        "- Return stream: ZZ500 close-to-close return minus CYB close-to-close return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- Target-vol, NAV defense, overheat, amount/volume gates, and momentum decay are off.",
        "",
        "## Top Full-Sample Results",
        window_table(top_sharpe, 12),
        "",
        "## Width Candidates",
        window_table(width_candidates, 12),
        "",
        "## Next-Layer Carry Candidates",
        window_table(carry, 8),
        "",
        "## Decision",
        "Carry one balanced bias-momentum group into Layer 2 as a secondary anchor; keep the return-heavy line as watchlist only.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "ZZ500/CYB spread Layer 1 bias dense",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_zz500_cyb_spread_long_only.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "layer1_bias_momentum_dense_patch",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "bias_momentum_width_dense_patch",
        "baseline": {
            "direction": "long_ZZ500_short_CYB",
            "layer0_bias_seed": "bias_ma020_mom030_we3p0_gt0",
            "preferred_balanced_carry": PRIMARY_CARRY,
            "return_heavy_watch": RETURN_WATCH,
        },
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": base.COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "zz500": {
                "secid": str(mod.CN_DK_ZZ500_SECID),
                "publication_date": base.ZZ500_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_ZZ500_SECID))),
                "rows": int(len(zz500)),
                "start": str(zz500.index.min().date()),
                "end": str(zz500.index.max().date()),
            },
            "cyb": {
                "secid": str(mod.CN_DK_CYB_SECID),
                "publication_date": base.CYB_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_CYB_SECID))),
                "rows": int(len(cyb)),
                "start": str(cyb.index.min().date()),
                "end": str(cyb.index.max().date()),
            },
            "formal": {
                "rows": int(len(panel)),
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
                "start_rule": "latest actual publication/listing date among participants",
                "ratio": "ZZ500 / CYB",
                "return_stream": "ZZ500 pct_change - CYB pct_change",
            },
        },
        "decision": "layer1_bias_dense_complete_not_promoted",
        "stability_label": "bias_momentum_width_supported_secondary",
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "local_width": str(RUN_DIR / "local_width.csv"),
            "width_candidates": str(RUN_DIR / "width_candidates.csv"),
            "carry_candidates": str(RUN_DIR / "carry_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python -m py_compile \"scan_adk_zz500_cyb_spread_layer1_bias_dense_patch.py\"\n"
        "python \"scan_adk_zz500_cyb_spread_layer1_bias_dense_patch.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"layer1_bias_dense_complete_not_promoted\" --stability-label \"bias_momentum_width_supported_secondary\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict \"{RUN_DIR}\"\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("TOP_SHARPE")
    print(top_sharpe[["candidate", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y"]].head(12).to_string(index=False))
    print("WIDTH_CANDIDATES")
    print(width_candidates[["candidate", "ann_return_full", "max_dd_full", "sharpe_repo_full", "nearby_family80_count", "nearby_family80_bias_count", "nearby_family80_mom_count", "nearby_family80_weight_count"]].head(12).to_string(index=False))
    print("CARRY")
    print(carry[["candidate", "ann_return_full", "max_dd_full", "sharpe_repo_full", "ann_return_last_5y", "max_dd_last_5y", "ann_return_last_1y", "max_dd_last_1y", "nearby_family80_count"]].to_string(index=False))


if __name__ == "__main__":
    main()

"""Layer 2 score and absolute-bias filter scan for long CYB / short ZZ500.

Inputs are the Layer 1 dense width-supported carry candidates. This layer scans
score thresholds and an absolute CYB/ZZ500 ratio-bias gate only. Target-vol, NAV
defense, overheat, amount/volume, and momentum decay remain off.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_zz500_spread_layer1_dense_patch as l1dense
import scan_adk_cyb_zz500_spread_long_only as base


RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260612_adk_cyb_zz500_spread_long_only_v77_adk_spread_layer2_score_abs_filter_four_l1_width_anchors"

ANCHORS = [
    {"anchor": "bias_30_28_we2p75", "family": "bias_momentum", "bias_ma": 30, "mom_day": 28, "weight_end": 2.75, "layer1_candidate": "dense_bias_ma030_mom028_we2p75_gt0"},
    {"anchor": "bias_30_28_we3", "family": "bias_momentum", "bias_ma": 30, "mom_day": 28, "weight_end": 3.0, "layer1_candidate": "dense_bias_ma030_mom028_we3p0_gt0"},
    {"anchor": "bias_30_27_we2p5", "family": "bias_momentum", "bias_ma": 30, "mom_day": 27, "weight_end": 2.5, "layer1_candidate": "dense_bias_ma030_mom027_we2p5_gt0"},
    {"anchor": "bias_30_27_we1p75", "family": "bias_momentum", "bias_ma": 30, "mom_day": 27, "weight_end": 1.75, "layer1_candidate": "dense_bias_ma030_mom027_we1p75_gt0"},
]

SCORE_THRESHOLDS = [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.5, 10.0]
ABS_MAS = list(range(20, 81, 5))
ABS_THRESHOLDS = [round(x, 3) for x in np.arange(-0.08, 0.0801, 0.005)]
LOSS_TIERS = [1.0, 2.0, 3.0]


def fmt_num(value: float, pct: bool = False) -> str:
    scaled = value * 100.0 if pct else value
    sign = "m" if scaled < 0 else ""
    return sign + f"{abs(scaled):g}".replace(".", "p")


def load_panel() -> tuple[object, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    mod = base.load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    zz500 = mod._load_cn_official_cache(mod.CN_DK_ZZ500_SECID).rename(columns={"close": "ZZ500"})
    panel = pd.concat([cyb["CYB"], zz500["ZZ500"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["CYB"] / panel["ZZ500"]
    panel["spread_return"] = panel["CYB"].pct_change().fillna(0.0) - panel["ZZ500"].pct_change().fillna(0.0)
    return mod, cyb, zz500, panel


def precompute(panel: pd.DataFrame) -> tuple[dict[str, pd.Series], dict[str, pd.Series], dict[int, pd.Series]]:
    ratio = panel["ratio"]
    scores: dict[str, pd.Series] = {}
    r2s: dict[str, pd.Series] = {}
    for anchor in ANCHORS:
        feature = ratio / ratio.rolling(int(anchor["bias_ma"])).mean() - 1.0
        score, r2 = l1dense.fast_weighted_slope_and_r2(feature, int(anchor["mom_day"]), float(anchor["weight_end"]))
        scores[str(anchor["anchor"])] = score
        r2s[str(anchor["anchor"])] = r2
    abs_bias = {ma: ratio / ratio.rolling(ma).mean() - 1.0 for ma in ABS_MAS}
    return scores, r2s, abs_bias


def make_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for anchor in ANCHORS:
        for score_thr in SCORE_THRESHOLDS:
            grid.append(
                {
                    **anchor,
                    "candidate": f"l2_{anchor['anchor']}_score{fmt_num(score_thr)}_abs_off",
                    "score_threshold": score_thr,
                    "abs_ma": 0,
                    "abs_threshold": -999.0,
                    "abs_filter": "off",
                }
            )
            for abs_ma in ABS_MAS:
                for abs_thr in ABS_THRESHOLDS:
                    grid.append(
                        {
                            **anchor,
                            "candidate": f"l2_{anchor['anchor']}_score{fmt_num(score_thr)}_abs{abs_ma}_gt_{fmt_num(abs_thr, pct=True)}pct",
                            "score_threshold": score_thr,
                            "abs_ma": abs_ma,
                            "abs_threshold": abs_thr,
                            "abs_filter": "ratio_bias",
                        }
                    )
    return grid


def candidate_returns(
    panel: pd.DataFrame,
    candidate: dict[str, object],
    scores: dict[str, pd.Series],
    r2s: dict[str, pd.Series],
    abs_bias: dict[int, pd.Series],
) -> pd.DataFrame:
    score = scores[str(candidate["anchor"])]
    r2 = r2s[str(candidate["anchor"])]
    signal = (score > float(candidate["score_threshold"])) & (r2 >= 0.05)
    abs_ma = int(candidate["abs_ma"])
    if abs_ma > 0:
        abs_series = abs_bias[abs_ma]
        signal = signal & (abs_series > float(candidate["abs_threshold"]))
    else:
        abs_series = pd.Series(np.nan, index=panel.index)

    weight = signal.astype(float).shift(1).fillna(0.0)
    turnover = weight.diff().abs().fillna(weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = weight * panel["spread_return"]
    ret = gross_return - cost
    warmup = max(int(candidate["bias_ma"]), int(candidate["mom_day"]), abs_ma) + 2
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": weight,
            "score": score,
            "r2": r2,
            "abs_bias": abs_series,
            "ratio": panel["ratio"],
            "spread_return": panel["spread_return"],
        },
        index=panel.index,
    ).iloc[warmup:].copy()


def add_baselines_and_flags(window_metrics: pd.DataFrame) -> pd.DataFrame:
    out = window_metrics.copy()
    baselines = out[(out["score_threshold"] == 0.0) & (out["abs_filter"] == "off")].set_index("anchor")
    for col in [
        "ann_return_full",
        "max_dd_full",
        "ann_return_last_5y",
        "max_dd_last_5y",
        "ann_return_last_3y",
        "max_dd_last_3y",
        "ann_return_last_1y",
        "max_dd_last_1y",
        "sharpe_repo_full",
    ]:
        out[f"base_{col}"] = out["anchor"].map(baselines[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100.0
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100.0
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100.0
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100.0
    out["threey_ann_loss_pp"] = (out["base_ann_return_last_3y"] - out["ann_return_last_3y"]) * 100.0
    out["threey_dd_improve_pp"] = (out["max_dd_last_3y"] - out["base_max_dd_last_3y"]) * 100.0
    out["oney_ann_loss_pp"] = (out["base_ann_return_last_1y"] - out["ann_return_last_1y"]) * 100.0
    out["oney_dd_improve_pp"] = (out["max_dd_last_1y"] - out["base_max_dd_last_1y"]) * 100.0
    out["pass_full_ann_dd"] = (out["ann_return_full"] >= out["base_ann_return_full"] - 1e-12) & (out["max_dd_full"] >= out["base_max_dd_full"] - 1e-12)
    out["pass_full_and_5y"] = (
        out["pass_full_ann_dd"]
        & (out["ann_return_last_5y"] >= out["base_ann_return_last_5y"] - 1e-12)
        & (out["max_dd_last_5y"] >= out["base_max_dd_last_5y"] - 1e-12)
    )
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (
            (out["full_ann_loss_pp"] <= tier + 1e-12)
            & (out["full_dd_improve_pp"] > 0)
            & (out["fivey_dd_improve_pp"] >= -1e-12)
        )
    return out


def patch_summary(window_metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    source = window_metrics[window_metrics["abs_filter"] == "ratio_bias"]
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for (anchor, score_thr), group in source.groupby(["anchor", "score_threshold"]):
            passed = group[group[pass_col]].copy()
            if passed.empty:
                rows.append(
                    {
                        "loss_tier_pp": tier,
                        "anchor": anchor,
                        "score_threshold": score_thr,
                        "pass_count": 0,
                        "ma_count": 0,
                        "threshold_count": 0,
                        "best_candidate": "",
                        "best_full_ann_return": np.nan,
                        "best_full_max_dd": np.nan,
                        "best_full_ann_loss_pp": np.nan,
                        "best_full_dd_improve_pp": np.nan,
                        "best_5y_ann_return": np.nan,
                        "best_5y_max_dd": np.nan,
                        "patch_like": False,
                    }
                )
                continue
            best = passed.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            thrs = sorted(passed["abs_threshold"].unique())
            adjacent_thr = any(round(thrs[i + 1] - thrs[i], 3) <= 0.006 for i in range(len(thrs) - 1))
            patch_like = bool(len(passed) >= 4 and passed["abs_ma"].nunique() >= 2 and passed["abs_threshold"].nunique() >= 2 and adjacent_thr)
            rows.append(
                {
                    "loss_tier_pp": tier,
                    "anchor": anchor,
                    "score_threshold": score_thr,
                    "pass_count": int(len(passed)),
                    "ma_count": int(passed["abs_ma"].nunique()),
                    "threshold_count": int(passed["abs_threshold"].nunique()),
                    "best_candidate": best["candidate"],
                    "best_full_ann_return": best["ann_return_full"],
                    "best_full_max_dd": best["max_dd_full"],
                    "best_full_ann_loss_pp": best["full_ann_loss_pp"],
                    "best_full_dd_improve_pp": best["full_dd_improve_pp"],
                    "best_5y_ann_return": best["ann_return_last_5y"],
                    "best_5y_max_dd": best["max_dd_last_5y"],
                    "patch_like": patch_like,
                }
            )
    return pd.DataFrame(rows).sort_values(["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"], ascending=[True, False, False, False])


def select_carry(window_metrics: pd.DataFrame, ridge: pd.DataFrame) -> pd.DataFrame:
    strict_pool = window_metrics[(window_metrics["abs_filter"] == "ratio_bias") & window_metrics["pass_full_and_5y"]].copy()
    if not strict_pool.empty:
        strict_pool["carry_score"] = (
            strict_pool["ann_return_full"] * 25
            + strict_pool["full_dd_improve_pp"].clip(lower=0, upper=20) * 0.10
            + strict_pool["ann_return_last_5y"].clip(lower=-0.02, upper=0.05) * 10
            + strict_pool["ann_return_last_1y"].clip(lower=-0.08, upper=0.10) * 3
        )
        strict_primary = strict_pool.sort_values(["carry_score", "ann_return_full", "full_dd_improve_pp"], ascending=[False, False, False]).groupby("anchor").head(2).head(6)
    else:
        strict_primary = pd.DataFrame()

    patch = ridge[(ridge["patch_like"]) & (ridge["pass_count"] > 0)].copy()
    pool_parts = []
    if not patch.empty:
        for _, key in patch.head(16)[["loss_tier_pp", "anchor", "score_threshold"]].drop_duplicates().iterrows():
            tag = str(float(key["loss_tier_pp"])).replace(".", "p")
            pass_col = f"pass_loss_le_{tag}pp"
            pool_parts.append(
                window_metrics[
                    (window_metrics["anchor"] == key["anchor"])
                    & (window_metrics["score_threshold"] == key["score_threshold"])
                    & (window_metrics["abs_filter"] == "ratio_bias")
                    & (window_metrics[pass_col])
                ]
            )
    pool = pd.concat(pool_parts, ignore_index=True) if pool_parts else pd.DataFrame()
    if pool.empty:
        pool = window_metrics[(window_metrics["abs_filter"] == "ratio_bias") & (window_metrics["pass_loss_le_2p0pp"])].copy()
    if pool.empty:
        pool = window_metrics[(window_metrics["abs_filter"] == "ratio_bias") & (window_metrics["full_dd_improve_pp"] > 0)].copy()
    if pool.empty:
        return strict_primary
    pool["carry_score"] = (
        pool["full_dd_improve_pp"].clip(lower=0, upper=20)
        - pool["full_ann_loss_pp"].clip(lower=-5, upper=10) * 0.5
        + pool["fivey_dd_improve_pp"].clip(lower=-5, upper=15) * 0.5
        + pool["ann_return_full"] * 10
    )
    dd_first = pool.sort_values(["carry_score", "ann_return_full"], ascending=[False, False]).groupby("anchor").head(2).head(8)
    return pd.concat([strict_primary, dd_first], ignore_index=True).drop_duplicates("candidate").head(10)


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def window_table(df: pd.DataFrame, n: int = 10) -> str:
    cols = ["candidate", "anchor", "score_threshold", "abs_ma", "abs_threshold"]
    for segment, _years in base.SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = base.git_text(["status", "--short"])
    mod, cyb, zz500, panel = load_panel()
    scores, r2s, abs_bias = precompute(panel)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = make_grid()
    long_rows = []
    wide_rows = []
    curves: dict[str, pd.DataFrame] = {}

    for candidate in grid:
        result = candidate_returns(panel, candidate, scores, r2s, abs_bias)
        wide = {**candidate}
        for segment, years in base.SEGMENTS:
            metrics = base.metrics_for_segment(result, segment, years)
            long_rows.append({**candidate, **metrics})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = metrics[key]
        wide_rows.append(wide)
        if candidate["score_threshold"] == 0.0 and candidate["abs_filter"] == "off":
            curves[str(candidate["candidate"])] = result

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_baselines_and_flags(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    full_pass = window_metrics[(window_metrics["abs_filter"] == "ratio_bias") & window_metrics["pass_full_ann_dd"]].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
    strict_pass = window_metrics[(window_metrics["abs_filter"] == "ratio_bias") & window_metrics["pass_full_and_5y"]].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
    top_tier: dict[float, pd.DataFrame] = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        passed = window_metrics[(window_metrics["abs_filter"] == "ratio_bias") & window_metrics[pass_col]].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_tier[tier] = passed

    carry = select_carry(window_metrics, ridge)
    selected_names = set()
    for df in [full_pass, strict_pass, carry, *top_tier.values()]:
        if not df.empty:
            selected_names.update(df.head(8)["candidate"].astype(str).tolist())
    selected_lookup = {candidate["candidate"]: candidate for candidate in grid if str(candidate["candidate"]) in selected_names}
    for name, candidate in selected_lookup.items():
        if name not in curves:
            curves[name] = candidate_returns(panel, candidate, scores, r2s, abs_bias)

    daily_rows = []
    for name, curve in curves.items():
        out = curve.copy()
        out["nav"] = (1.0 + out["return"]).cumprod()
        out["candidate"] = name
        daily_rows.append(out.reset_index(names="date"))
    daily = pd.concat(daily_rows, ignore_index=True) if daily_rows else pd.DataFrame()

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    full_pass.to_csv(RUN_DIR / "full_baseline_pass_candidates.csv", index=False, encoding="utf-8-sig")
    strict_pass.to_csv(RUN_DIR / "full_and_5y_pass_candidates.csv", index=False, encoding="utf-8-sig")
    carry.to_csv(RUN_DIR / "carry_candidates.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")

    stability = "strict_and_dd_first_patch_review" if not carry.empty else "layer2_no_candidate"
    decision = "layer2_score_abs_complete_not_promoted"
    record_lines = [
        "# CYB/ZZ500 Layer 2 Score And Absolute-Bias Filter Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        f"- decision: `{decision}`",
        f"- stability: `{stability}`",
        "",
        "## Research Question",
        "Scan score thresholds and absolute ratio-bias filters against four Layer 1 width-supported anchors.",
        "",
        "## Layer Inputs",
        "- Anchors:",
        *[
            f"  - `{anchor['anchor']}` from `{anchor['layer1_candidate']}`: family={anchor['family']}, bias_ma={anchor['bias_ma']}, mom_day={anchor['mom_day']}, weight_end={anchor['weight_end']}"
            for anchor in ANCHORS
        ],
        "- Score thresholds: `-3, -2, -1, 0, 1, 2, 3, 4, 5, 7.5, 10`.",
        "- Absolute-bias gate: `ratio / MA(abs_ma) - 1 > abs_threshold`; abs_ma=20..80 step5; abs_threshold=-8%..8% step0.5%.",
        "",
        "## Implementation Anchor",
        "- Imports data loader and metrics from `scan_adk_cyb_zz500_spread_long_only.py`.",
        "- Uses vectorized weighted-slope/R2 from `scan_adk_cyb_zz500_spread_layer1_dense_patch.py`.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research with two-leg commissions, excluding futures basis, financing, borrow, and short locate costs.",
        "- Source-change rule: `research_only_new_scan_script`.",
        "",
        "## Data Snapshot",
        f"- CYB publication date: {base.CYB_PUBLICATION_DATE}; local rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- ZZ500 publication date: {base.ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start rule: latest actual index publication/listing date among the two legs.",
        "- Adjustment mode: price index close from local official cache, no total-return substitution.",
        "",
        "## Cost and Execution Assumptions",
        "- T close signal -> T+1 close-to-close spread return.",
        "- Return stream: CYB close-to-close return minus ZZ500 close-to-close return.",
        f"- Two-leg transaction cost with one-way commission {base.COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- No target-vol, NAV defense, overheat, amount, volume, or momentum-decay overlay is applied.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only Layer 2 scan.",
        "",
        "## Commands",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"CYB/ZZ500 spread Layer 2 score abs\" --parameter-group \"score_threshold_abs_bias_filter\" --repo . --entrypoint \"scan_adk_cyb_zz500_spread_layer2_score_abs_filter.py\" --date 2026-06-12 --slug \"adk_cyb_zz500_spread_long_only_v77_adk_spread_layer2_score_abs_filter_four_l1_width_anchors\"`",
        "- `python -m py_compile \"scan_adk_cyb_zz500_spread_layer2_score_abs_filter.py\"`",
        "- `python \"scan_adk_cyb_zz500_spread_layer2_score_abs_filter.py\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py <run_folder> --decision \"layer2_score_abs_complete_not_promoted\" --stability-label \"<stability>\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>`",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `full_baseline_pass_candidates.csv`",
        "- `full_and_5y_pass_candidates.csv`",
        "- `dd_first_pass_loss_le_1p0pp.csv`",
        "- `dd_first_pass_loss_le_2p0pp.csv`",
        "- `dd_first_pass_loss_le_3p0pp.csv`",
        "- `carry_candidates.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        window_table(full_pass, 12) if not full_pass.empty else "No candidates passed strict full-sample annual-return and drawdown non-underperformance.",
        "",
        "## Window Results",
        window_table(strict_pass, 12) if not strict_pass.empty else "No candidates passed strict full+5Y annual-return and drawdown non-underperformance.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 2 score/absolute-bias scan completed but not promoted. Stop for user review before Layer 3 target-vol.",
        "",
        "## User-Facing Summary",
        f"- strict full pass count: {len(full_pass)}",
        f"- strict full+5Y pass count: {len(strict_pass)}",
        f"- loss<=1pp pass count: {len(top_tier[1.0])}",
        f"- loss<=2pp pass count: {len(top_tier[2.0])}",
        f"- loss<=3pp pass count: {len(top_tier[3.0])}",
        "",
        "## Next-Layer Carry Candidates",
        window_table(carry, 10) if not carry.empty else "No carry candidate selected.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "CYB/ZZ500 spread Layer 2 score abs",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_cyb_zz500_spread_long_only.py",
        "git_branch": base.git_text(["branch", "--show-current"]),
        "git_commit": base.git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": base.git_text(["status", "--short"]),
        "scan_type": "layer2_score_abs_filter",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "score_threshold_abs_bias_filter",
        "baseline": {"anchors": ANCHORS, "loss_tiers_pp": LOSS_TIERS},
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
            "cyb": {"secid": str(mod.CN_DK_CYB_SECID), "publication_date": base.CYB_PUBLICATION_DATE, "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_CYB_SECID))), "rows": int(len(cyb)), "start": str(cyb.index.min().date()), "end": str(cyb.index.max().date())},
            "zz500": {"secid": str(mod.CN_DK_ZZ500_SECID), "publication_date": base.ZZ500_PUBLICATION_DATE, "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_ZZ500_SECID))), "rows": int(len(zz500)), "start": str(zz500.index.min().date()), "end": str(zz500.index.max().date())},
            "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date()), "start_rule": "latest actual publication/listing date among participants", "ratio": "CYB / ZZ500", "return_stream": "CYB pct_change - ZZ500 pct_change"},
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
            "ridge_width": str(RUN_DIR / "ridge_width.csv"),
            "full_baseline_pass_candidates": str(RUN_DIR / "full_baseline_pass_candidates.csv"),
            "full_and_5y_pass_candidates": str(RUN_DIR / "full_and_5y_pass_candidates.csv"),
            "carry_candidates": str(RUN_DIR / "carry_candidates.csv"),
        },
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"CYB/ZZ500 spread Layer 2 score abs\" --parameter-group \"score_threshold_abs_bias_filter\" --repo . --entrypoint \"scan_adk_cyb_zz500_spread_layer2_score_abs_filter.py\" --date 2026-06-12 --slug \"adk_cyb_zz500_spread_long_only_v77_adk_spread_layer2_score_abs_filter_four_l1_width_anchors\"\n"
        "python -m py_compile \"scan_adk_cyb_zz500_spread_layer2_score_abs_filter.py\"\n"
        "python \"scan_adk_cyb_zz500_spread_layer2_score_abs_filter.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"{decision}\" --stability-label \"{stability}\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict \"{RUN_DIR}\"\n",
        encoding="utf-8",
    )

    cols = ["candidate", "anchor", "score_threshold", "abs_ma", "abs_threshold", "ann_return_full", "max_dd_full", "full_ann_loss_pp", "full_dd_improve_pp", "ann_return_last_5y", "max_dd_last_5y", "fivey_ann_loss_pp", "fivey_dd_improve_pp", "ann_return_last_1y", "max_dd_last_1y"]
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_tier[tier])}")
        print(top_tier[tier][cols].head(12).to_string(index=False) if not top_tier[tier].empty else "NONE")
    print(f"STRICT_FULL_PASS_COUNT={len(full_pass)}")
    print(full_pass[cols].head(12).to_string(index=False) if not full_pass.empty else "NONE")
    print(f"STRICT_FULL_5Y_PASS_COUNT={len(strict_pass)}")
    print(strict_pass[cols].head(12).to_string(index=False) if not strict_pass.empty else "NONE")
    print("CARRY")
    print(carry[cols].head(12).to_string(index=False) if not carry.empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

"""Layer 5 score-peak momentum decay after NAV defense for SZ50/CYB.

Formal sequence: Layer 4 NAV defense -> Layer 5 momentum decay.
Momentum decay is based on T-close signal score relative to the current active
trade's score peak, shifted to the next execution row. It is not a second NAV
drawdown gate.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_sz50_cyb_reverse_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260609_adk_sz50_cyb_reverse_spread_long_only_v77_adk_reverse_spread_layer5_momentum_decay_after_nav"

ANCHORS = [
    {"anchor": "neighbor_tv16_nav10_s025", "bias_ma": 30, "mom_day": 32, "weight_end": 3.5, "score_threshold": 1.0, "abs_ma": 15, "abs_threshold": -0.070, "target_vol": 0.16, "vol_window": 20, "max_leverage": 1.25, "nav_threshold": 0.10, "nav_scale": 0.25},
    {"anchor": "main_tv16_nav10_s0", "bias_ma": 25, "mom_day": 36, "weight_end": 4.0, "score_threshold": 0.0, "abs_ma": 15, "abs_threshold": -0.070, "target_vol": 0.16, "vol_window": 20, "max_leverage": 1.5, "nav_threshold": 0.10, "nav_scale": 0.0},
    {"anchor": "return_tv20_nav12_s05", "bias_ma": 25, "mom_day": 36, "weight_end": 4.0, "score_threshold": 0.0, "abs_ma": 15, "abs_threshold": -0.070, "target_vol": 0.20, "vol_window": 20, "max_leverage": 1.5, "nav_threshold": 0.12, "nav_scale": 0.5},
    {"anchor": "return_tv20_nav12_s0", "bias_ma": 25, "mom_day": 36, "weight_end": 4.0, "score_threshold": 0.0, "abs_ma": 15, "abs_threshold": -0.070, "target_vol": 0.20, "vol_window": 20, "max_leverage": 1.5, "nav_threshold": 0.12, "nav_scale": 0.0},
]

DECAY_THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]
RECOVERY_THRESHOLDS = [0.60, 0.70, 0.80, 0.90]
WARMUP_DAYS = [3, 5, 10]
DERISK_SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [1.0, 2.0, 3.0]
MIN_LEVERAGE = 0.1


def fmt(value: float, pct: bool = False) -> str:
    x = value * 100.0 if pct else value
    sign = "m" if x < 0 else ""
    return sign + f"{abs(x):g}".replace(".", "p")


def load_panel():
    mod = base.base_scan.load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    sz50 = mod._load_cn_official_cache(mod.CN_DK_SZ50_SECID).rename(columns={"close": "SZ50"})
    panel = pd.concat([cyb["CYB"], sz50["SZ50"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.base_scan.FORMAL_START].copy()
    panel["ratio"] = panel["SZ50"] / panel["CYB"]
    panel["spread_return"] = panel["SZ50"].pct_change().fillna(0.0) - panel["CYB"].pct_change().fillna(0.0)
    return mod, cyb, sz50, panel


def l4_nav_base(panel: pd.DataFrame, anchor: dict[str, object]) -> pd.DataFrame:
    ratio = panel["ratio"]
    feature = ratio / ratio.rolling(int(anchor["bias_ma"])).mean() - 1.0
    score = base.base_scan.weighted_slope_score(feature, int(anchor["mom_day"]), float(anchor["weight_end"]))
    r2 = base.base_scan.weighted_slope_r2(feature, int(anchor["mom_day"]), float(anchor["weight_end"]))
    abs_bias = ratio / ratio.rolling(int(anchor["abs_ma"])).mean() - 1.0
    raw_signal = ((score > float(anchor["score_threshold"])) & (r2 >= 0.05) & (abs_bias > float(anchor["abs_threshold"]))).astype(float)
    exec_signal = raw_signal.shift(1).fillna(0.0)
    realized_vol = panel["spread_return"].rolling(int(anchor["vol_window"])).std() * np.sqrt(base.base_scan.ANNUALIZATION_DAYS)
    raw_scale = (float(anchor["target_vol"]) / realized_vol).clip(MIN_LEVERAGE, float(anchor["max_leverage"])).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    l3_weight = exec_signal * raw_scale
    warmup = max(int(anchor["bias_ma"]), int(anchor["mom_day"]), int(anchor["abs_ma"]), int(anchor["vol_window"])) + 2
    d = pd.DataFrame(
        {
            "l3_weight": l3_weight,
            "raw_signal": raw_signal,
            "score": score,
            "r2": r2,
            "abs_bias": abs_bias,
            "raw_scale": raw_scale,
            "spread_return": panel["spread_return"],
        },
        index=panel.index,
    ).iloc[warmup:].dropna().copy()

    l3_turnover = d["l3_weight"].diff().abs().fillna(d["l3_weight"].abs())
    l3_cost = l3_turnover * (2.0 * base.base_scan.COMMISSION_ONE_WAY)
    l3_ret = d["l3_weight"] * d["spread_return"] - l3_cost
    pre_nav = (1.0 + l3_ret).cumprod()
    pre_dd = pre_nav / pre_nav.cummax() - 1.0
    nav_on = pre_dd.shift(1).fillna(0.0) <= -float(anchor["nav_threshold"])
    nav_mult = pd.Series(1.0, index=d.index)
    nav_mult.loc[nav_on] = float(anchor["nav_scale"])
    d["base_weight"] = d["l3_weight"] * nav_mult
    d["pre_nav"] = pre_nav
    d["pre_nav_dd"] = pre_dd
    d["nav_on"] = nav_on.astype(float)
    d["nav_mult"] = nav_mult
    return d


def score_decay_multiplier(d: pd.DataFrame, decay: float | None, recovery: float | None, warmup: int | None, derisk_scale: float | None) -> pd.Series:
    if decay is None:
        return pd.Series(1.0, index=d.index)
    idx = d.index
    raw_signal = d["raw_signal"].astype(float).values
    score = d["score"].astype(float).values
    state = np.ones(len(d), dtype=float)
    in_decay = False
    peak = np.nan
    active_days = 0
    for i in range(len(d)):
        if raw_signal[i] <= 0 or not np.isfinite(score[i]):
            peak = np.nan
            active_days = 0
            in_decay = False
            state[i] = 1.0
            continue
        active_days += 1
        if not np.isfinite(peak):
            peak = score[i]
        else:
            peak = max(peak, score[i])
        ratio = score[i] / peak if peak and peak > 0 else 1.0
        if active_days >= int(warmup):
            if in_decay:
                if ratio >= float(recovery):
                    in_decay = False
                    peak = score[i]
            elif ratio <= float(decay):
                in_decay = True
        state[i] = float(derisk_scale) if in_decay else 1.0
    return pd.Series(state, index=idx).shift(1).fillna(1.0)


def apply_decay(base_df: pd.DataFrame, decay: float | None, recovery: float | None, warmup: int | None, derisk_scale: float | None) -> pd.DataFrame:
    d = base_df.copy()
    decay_mult = score_decay_multiplier(d, decay, recovery, warmup, derisk_scale)
    final_weight = d["base_weight"] * decay_mult
    turnover = final_weight.diff().abs().fillna(final_weight.abs())
    cost = turnover * (2.0 * base.base_scan.COMMISSION_ONE_WAY)
    gross_return = final_weight * d["spread_return"]
    ret = gross_return - cost
    return pd.DataFrame(
        {
            "return": ret,
            "gross_return": gross_return,
            "cost": cost,
            "turnover": turnover,
            "weight": final_weight,
            "base_weight": d["base_weight"],
            "l3_weight": d["l3_weight"],
            "nav_on": d["nav_on"],
            "nav_mult": d["nav_mult"],
            "decay_mult": decay_mult,
            "decay_on": (decay_mult < 1.0).astype(float),
            "score": d["score"],
            "raw_signal": d["raw_signal"],
        },
        index=d.index,
    )


def make_grid():
    for anchor in ANCHORS:
        yield {**anchor, "candidate": f"l5decay_{anchor['anchor']}_decay_off", "decay_threshold": 0.0, "recovery_threshold": 0.0, "warmup_days": 0, "derisk_scale": 1.0, "decay_enabled": False}
        for decay in DECAY_THRESHOLDS:
            for recovery in RECOVERY_THRESHOLDS:
                if recovery <= decay:
                    continue
                for warmup in WARMUP_DAYS:
                    for scale in DERISK_SCALES:
                        yield {**anchor, "candidate": f"l5decay_{anchor['anchor']}_decay{fmt(decay)}_rec{fmt(recovery)}_warm{warmup}_scale{fmt(scale)}", "decay_threshold": decay, "recovery_threshold": recovery, "warmup_days": warmup, "derisk_scale": scale, "decay_enabled": True}


def add_tiers(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["decay_enabled"] == False].set_index("anchor")
    for col in ["ann_return_full", "max_dd_full", "ann_return_last_5y", "max_dd_last_5y", "sharpe_repo_full"]:
        out[f"base_{col}"] = out["anchor"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (out["decay_enabled"] == True) & (out["full_ann_loss_pp"] <= tier + 1e-12) & (out["full_dd_improve_pp"] > 0)
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for anchor, d in wm[wm["decay_enabled"] == True].groupby("anchor"):
            p = d[d[pass_col]].copy()
            if p.empty:
                rows.append({"loss_tier_pp": tier, "anchor": anchor, "pass_count": 0, "decay_count": 0, "recovery_count": 0, "warmup_count": 0, "scale_count": 0, "best_candidate": "", "best_full_ann_return": np.nan, "best_full_max_dd": np.nan, "best_full_ann_loss_pp": np.nan, "best_full_dd_improve_pp": np.nan, "best_5y_ann_return": np.nan, "best_5y_max_dd": np.nan, "patch_like": False})
                continue
            best = p.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(len(p) >= 4 and p["decay_threshold"].nunique() >= 2 and p["derisk_scale"].nunique() >= 2)
            rows.append({"loss_tier_pp": tier, "anchor": anchor, "pass_count": int(len(p)), "decay_count": int(p["decay_threshold"].nunique()), "recovery_count": int(p["recovery_threshold"].nunique()), "warmup_count": int(p["warmup_days"].nunique()), "scale_count": int(p["derisk_scale"].nunique()), "best_candidate": best["candidate"], "best_full_ann_return": best["ann_return_full"], "best_full_max_dd": best["max_dd_full"], "best_full_ann_loss_pp": best["full_ann_loss_pp"], "best_full_dd_improve_pp": best["full_dd_improve_pp"], "best_5y_ann_return": best["ann_return_last_5y"], "best_5y_max_dd": best["max_dd_last_5y"], "patch_like": patch_like})
    return pd.DataFrame(rows).sort_values(["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"], ascending=[True, False, False, False])


def quadrant_summary(daily_all: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for candidate, d in daily_all.groupby("candidate"):
        nav_on = d["nav_on"].astype(float) > 0
        decay_on = d["decay_on"].astype(float) > 0
        for label, mask in {
            "Q00_nav0_decay0": ~nav_on & ~decay_on,
            "Q10_nav1_decay0": nav_on & ~decay_on,
            "Q01_nav0_decay1": ~nav_on & decay_on,
            "Q11_nav1_decay1": nav_on & decay_on,
        }.items():
            part = d.loc[mask]
            rows.append(
                {
                    "candidate": candidate,
                    "quadrant": label,
                    "days": int(mask.sum()),
                    "avg_weight": float(part["weight"].mean()) if not part.empty else np.nan,
                    "gross_return_sum": float(part["gross_return"].sum()) if not part.empty else 0.0,
                    "cost_sum": float(part["cost"].sum()) if not part.empty else 0.0,
                    "net_return_sum": float(part["return"].sum()) if not part.empty else 0.0,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    mod, cyb, sz50, panel = load_panel()
    base_by_anchor = {a["anchor"]: l4_nav_base(panel, a) for a in ANCHORS}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = list(make_grid())
    long_rows = []
    wide_rows = []
    daily_parts = []
    for cand in grid:
        result = apply_decay(
            base_by_anchor[cand["anchor"]],
            None if not cand["decay_enabled"] else float(cand["decay_threshold"]),
            None if not cand["decay_enabled"] else float(cand["recovery_threshold"]),
            None if not cand["decay_enabled"] else int(cand["warmup_days"]),
            None if not cand["decay_enabled"] else float(cand["derisk_scale"]),
        )
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily["anchor"] = cand["anchor"]
        daily_parts.append(daily.reset_index(names="date"))
        wide = {**cand}
        wide["decay_days_full"] = int((result["decay_mult"] < 1.0).sum())
        wide["nav_days_full"] = int(result["nav_on"].sum())
        wide["nav_decay_overlap_days_full"] = int(((result["nav_on"] > 0) & (result["decay_mult"] < 1.0)).sum())
        for segment, years in base.base_scan.SEGMENTS:
            m = base.base_scan.metrics_for_segment(result, segment, years)
            long_rows.append({**cand, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)
    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_tiers(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)
    quadrants = quadrant_summary(daily_all)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    quadrants.to_csv(RUN_DIR / "quadrant_summary.csv", index=False, encoding="utf-8-sig")
    top_by_tier = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_by_tier[tier] = passed

    cols = [
        "candidate", "anchor", "decay_threshold", "recovery_threshold", "warmup_days", "derisk_scale",
        "decay_days_full", "nav_days_full", "nav_decay_overlap_days_full",
        "ann_return_full", "max_dd_full", "full_ann_loss_pp", "full_dd_improve_pp",
        "ann_return_last_10y", "max_dd_last_10y", "ann_return_last_5y", "max_dd_last_5y",
        "fivey_ann_loss_pp", "fivey_dd_improve_pp", "ann_return_last_3y", "max_dd_last_3y",
        "ann_return_last_1y", "max_dd_last_1y", "sharpe_repo_full",
    ]
    record_lines = [
        "# SZ50/CYB Layer 5 Momentum Decay After NAV Defense",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer5_momentum_decay_complete_not_promoted`",
        "- stability: `momentum_decay_after_nav_patch_review`",
        "",
        "## Research Question",
        "Test score-peak momentum decay after the formal Layer 4 NAV-defense anchors.",
        "",
        "## Implementation Anchor",
        "- Momentum-decay state is computed from T-close score/peak and shifted to T+1 execution.",
        "- Baseline weight already includes Layer 4 NAV defense.",
        "- Costs are recalculated after final exposure changes.",
        "- The prior out-of-order overheat run is not used as an input.",
        "",
        "## Data Snapshot",
        f"- CYB rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- SZ50 rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "",
        "## Cost and Execution Assumptions",
        "- Direction: long SZ50 / short CYB.",
        "- T close signal and state -> T+1 close-to-close spread return.",
        "- Two-leg transaction cost with one-way commission 0.0005 on final exposure changes.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_sz50_cyb_reverse_spread_layer5_momentum_decay_after_nav.py\"`",
        "- `python \"scan_adk_sz50_cyb_reverse_spread_layer5_momentum_decay_after_nav.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `quadrant_summary.csv`",
        "- `ridge_width.csv`",
        "- `dd_first_pass_loss_le_1p0pp.csv`",
        "- `dd_first_pass_loss_le_2p0pp.csv`",
        "- `dd_first_pass_loss_le_3p0pp.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        top_by_tier[1.0][cols].head(20).to_markdown(index=False) if not top_by_tier[1.0].empty else "No candidates passed loss<=1pp with DD improvement.",
        "",
        "## Window Results",
        top_by_tier[2.0][cols].head(20).to_markdown(index=False) if not top_by_tier[2.0].empty else "No candidates passed loss<=2pp with DD improvement.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 5 momentum decay completed but not promoted. Stop for review before any four-quadrant or overheat layer.",
        "",
        "## User-Facing Summary",
        f"- loss<=1pp pass count: {len(top_by_tier[1.0])}",
        f"- loss<=2pp pass count: {len(top_by_tier[2.0])}",
        f"- loss<=3pp pass count: {len(top_by_tier[3.0])}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")
    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK reverse spread research",
        "repo_root": str(base.ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": "scan_adk_sz50_cyb_reverse_spread_layer4_nav_defense.py",
        "git_branch": "not_checked_agent_policy",
        "git_commit": "not_checked_agent_policy",
        "git_status_before": "not_checked_agent_policy",
        "git_status_after": "not_checked_agent_policy",
        "scan_type": "fresh_layer5_momentum_decay_after_nav",
        "parameter_group": "score_peak_decay_recovery_warmup_scale_after_nav",
        "baseline": {"anchors": ANCHORS, "loss_tiers_pp": LOSS_TIERS},
        "candidate_grid": grid,
        "cost_model": {"one_way_commission": base.base_scan.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return", "direction": "long SZ50 / short CYB"},
        "data_snapshot": {"source": "mnt_bot V 7.7 plus.py _load_cn_official_cache via reverse layer harness", "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())}},
        "decision": "layer5_momentum_decay_complete_not_promoted",
        "stability_label": "momentum_decay_after_nav_patch_review",
        "outputs": {"record": str(RUN_DIR / "record.md"), "scan_summary": str(RUN_DIR / "scan_summary.csv"), "window_metrics": str(RUN_DIR / "window_metrics.csv"), "scan_meta": str(RUN_DIR / "scan_meta.json"), "command_log": str(RUN_DIR / "command_log.txt"), "daily_curves": str(RUN_DIR / "daily_curves.csv"), "ridge_width": str(RUN_DIR / "ridge_width.csv"), "quadrant_summary": str(RUN_DIR / "quadrant_summary.csv")},
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text("python -m py_compile \"scan_adk_sz50_cyb_reverse_spread_layer5_momentum_decay_after_nav.py\"\npython \"scan_adk_sz50_cyb_reverse_spread_layer5_momentum_decay_after_nav.py\"\npython C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n", encoding="utf-8")
    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("BASELINES")
    print(window_metrics[window_metrics.decay_enabled == False][cols].to_string(index=False))
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_by_tier[tier])}")
        print(top_by_tier[tier][cols].head(12).to_string(index=False) if not top_by_tier[tier].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

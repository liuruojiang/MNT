"""Layer 6 amount/volume defense after NAV+volhot for CYB/SZ50.

Amount sources are composed from existing successful panels:
- CYB amount: outputs/adk_cyb_hs300_amount_eastmoney.csv (EastMoney amount, yuan)
- SZ50 amount: outputs/adk_zz1000_sz50_amount_eastmoney.csv (CSIndex fallback tradingValue scale)

Because raw units differ, this scan uses relative-to-own-MA amount features and
unitless CYB_rel / SZ50_rel ratios, not raw amount ratios.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import scan_adk_cyb_sz50_spread_long_only as base

RUN_DIR = base.ROOT / "quant_param_scan_runs" / "20260609_adk_cyb_sz50_spread_long_only_v77_adk_spread_layer6_amount_after_nav_volhot"
OUTPUT_AMOUNT = base.ROOT / "outputs" / "adk_cyb_sz50_amount_composed.csv"
OUTPUT_AMOUNT_META = base.ROOT / "outputs" / "adk_cyb_sz50_amount_composed_meta.json"

ANCHORS = [
    {"anchor": "main_nav6_volhot_w40", "volhot_window": 40, "volhot_threshold": 0.18, "volhot_scale": 0.75},
    {"anchor": "neighbor_nav6_volhot_w30", "volhot_window": 30, "volhot_threshold": 0.18, "volhot_scale": 0.75},
]
BASE_PARAMS = {"bias_ma": 80, "mom_day": 28, "weight_end": 2.5, "score_threshold": 5.0, "abs_ma": 30, "abs_threshold": 0.015, "target_vol": 0.24, "vol_window": 30, "max_leverage": 1.5, "nav_threshold": 0.06, "nav_scale": 0.75}
AMOUNT_WINDOWS = [20, 40, 60, 80, 120]
HIGH_THRESHOLDS = [1.25, 1.50, 1.75, 2.00]
LOW_THRESHOLDS = [0.75, 0.85, 1.00]
CONFIRM_DAYS = [1, 3, 5]
SCALES = [0.0, 0.25, 0.5, 0.75]
LOSS_TIERS = [1.0, 2.0, 3.0]
MIN_LEVERAGE = 0.1


def fmt(value: float) -> str:
    return f"{value:g}".replace(".", "p")


def compose_amount_panel() -> pd.DataFrame:
    cyb = pd.read_csv(base.ROOT / "outputs" / "adk_cyb_hs300_amount_eastmoney.csv", encoding="utf-8-sig")
    sz50 = pd.read_csv(base.ROOT / "outputs" / "adk_zz1000_sz50_amount_eastmoney.csv", encoding="utf-8-sig")
    cyb["date"] = pd.to_datetime(cyb["date"])
    sz50["date"] = pd.to_datetime(sz50["date"])
    c = cyb[["date", "cyb_close_csindex", "cyb_volume", "cyb_amount"]].copy()
    s = sz50[["date", "sz50_close_amount_source", "sz50_volume", "sz50_amount"]].copy()
    out = c.merge(s, on="date", how="outer").sort_values("date")
    out["amount_ratio_cybrel_sz50rel"] = np.nan
    OUTPUT_AMOUNT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_AMOUNT, index=False, encoding="utf-8-sig")
    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": "composed from existing successful CYB/HS300 EastMoney amount and ZZ1000/SZ50 CSIndex fallback amount panels",
        "unit_warning": "raw CYB and SZ50 amount units differ; formal scan uses own-MA relative features and CYB_rel/SZ50_rel only",
        "cyb_source": "outputs/adk_cyb_hs300_amount_eastmoney.csv: cyb_amount",
        "sz50_source": "outputs/adk_zz1000_sz50_amount_eastmoney.csv: sz50_amount",
        "rows": int(len(out)),
        "first_date": str(out["date"].min().date()),
        "last_date": str(out["date"].max().date()),
        "output_csv": str(OUTPUT_AMOUNT),
    }
    OUTPUT_AMOUNT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out.set_index("date")


def load_price_panel():
    mod = base.load_v77()
    cyb = mod._load_cn_official_cache(mod.CN_DK_CYB_SECID).rename(columns={"close": "CYB"})
    sz50 = mod._load_cn_official_cache(mod.CN_DK_SZ50_SECID).rename(columns={"close": "SZ50"})
    panel = pd.concat([cyb["CYB"], sz50["SZ50"]], axis=1).dropna()
    panel = panel.loc[panel.index >= base.FORMAL_START].copy()
    panel["ratio"] = panel["CYB"] / panel["SZ50"]
    panel["spread_return"] = panel["CYB"].pct_change().fillna(0.0) - panel["SZ50"].pct_change().fillna(0.0)
    return mod, cyb, sz50, panel


def base_after_volhot(panel: pd.DataFrame, anchor: dict[str, object]) -> pd.DataFrame:
    p = BASE_PARAMS
    ratio = panel["ratio"]
    feature = ratio / ratio.rolling(p["bias_ma"]).mean() - 1.0
    score = base.weighted_slope_score(feature, p["mom_day"], p["weight_end"])
    r2 = base.weighted_slope_r2(feature, p["mom_day"], p["weight_end"])
    abs_bias = ratio / ratio.rolling(p["abs_ma"]).mean() - 1.0
    raw_signal = ((score > p["score_threshold"]) & (r2 >= 0.05) & (abs_bias > p["abs_threshold"])).astype(float)
    exec_signal = raw_signal.shift(1).fillna(0.0)
    realized_vol = panel["spread_return"].rolling(p["vol_window"]).std() * np.sqrt(base.ANNUALIZATION_DAYS)
    raw_scale = (p["target_vol"] / realized_vol).clip(MIN_LEVERAGE, p["max_leverage"]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    l3_weight = exec_signal * raw_scale
    warmup = max(p["bias_ma"], p["mom_day"], p["abs_ma"], p["vol_window"], int(anchor["volhot_window"])) + 2
    d = pd.DataFrame({"l3_weight": l3_weight, "score": score, "spread_return": panel["spread_return"]}, index=panel.index).iloc[warmup:].dropna().copy()
    l3_turnover = d["l3_weight"].diff().abs().fillna(d["l3_weight"].abs())
    l3_ret = d["l3_weight"] * d["spread_return"] - l3_turnover * (2.0 * base.COMMISSION_ONE_WAY)
    pre_nav = (1.0 + l3_ret).cumprod()
    pre_dd = pre_nav / pre_nav.cummax() - 1.0
    nav_on = pre_dd.shift(1).fillna(0.0) <= -p["nav_threshold"]
    nav_mult = pd.Series(1.0, index=d.index)
    nav_mult.loc[nav_on] = p["nav_scale"]
    nav_weight = d["l3_weight"] * nav_mult
    rv_hot = d["spread_return"].rolling(int(anchor["volhot_window"])).std() * np.sqrt(base.ANNUALIZATION_DAYS)
    hot_on = rv_hot.shift(1).fillna(0.0) >= float(anchor["volhot_threshold"])
    hot_mult = pd.Series(1.0, index=d.index)
    hot_mult.loc[hot_on] = float(anchor["volhot_scale"])
    weight = nav_weight * hot_mult
    turnover = weight.diff().abs().fillna(weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = weight * d["spread_return"]
    ret = gross_return - cost
    return pd.DataFrame({"return": ret, "gross_return": gross_return, "cost": cost, "turnover": turnover, "weight": weight, "base_weight": weight, "spread_return": d["spread_return"], "score": d["score"]}, index=d.index)


def amount_feature(amount_panel: pd.DataFrame, feature: str, window: int) -> pd.Series:
    cyb_rel = amount_panel["cyb_amount"] / amount_panel["cyb_amount"].rolling(window).mean()
    sz50_rel = amount_panel["sz50_amount"] / amount_panel["sz50_amount"].rolling(window).mean()
    pair_rel = cyb_rel / sz50_rel
    if feature == "cyb_high" or feature == "cyb_low":
        return cyb_rel
    if feature == "sz50_high" or feature == "sz50_low":
        return sz50_rel
    if feature == "pair_high" or feature == "pair_low":
        return pair_rel
    raise ValueError(feature)


def confirmed_trigger(cond: pd.Series, days: int) -> pd.Series:
    if days <= 1:
        return cond.fillna(False)
    return cond.astype(float).rolling(days).sum().fillna(0) >= days


def apply_amount_overlay(base_df: pd.DataFrame, amount_panel: pd.DataFrame, feature: str | None, window: int | None, threshold: float | None, confirm_days: int | None, scale: float | None) -> pd.DataFrame:
    d = base_df.copy()
    if feature is None:
        mult = pd.Series(1.0, index=d.index)
        on = pd.Series(False, index=d.index)
    else:
        feat = amount_feature(amount_panel, feature, int(window)).reindex(d.index)
        if feature.endswith("high"):
            raw = feat >= float(threshold)
        else:
            raw = feat <= float(threshold)
        on = confirmed_trigger(raw, int(confirm_days)).shift(1).fillna(False)
        mult = pd.Series(1.0, index=d.index)
        mult.loc[on] = float(scale)
    weight = d["base_weight"] * mult
    turnover = weight.diff().abs().fillna(weight.abs())
    cost = turnover * (2.0 * base.COMMISSION_ONE_WAY)
    gross_return = weight * d["spread_return"]
    ret = gross_return - cost
    return pd.DataFrame({"return": ret, "gross_return": gross_return, "cost": cost, "turnover": turnover, "weight": weight, "base_weight": d["base_weight"], "amount_mult": mult, "amount_on": on.astype(float)}, index=d.index)


def make_grid():
    features = ["cyb_high", "cyb_low", "sz50_high", "sz50_low", "pair_high", "pair_low"]
    for anchor in ANCHORS:
        yield {**anchor, "candidate": f"l6_{anchor['anchor']}_amount_off", "amount_feature": "off", "amount_window": 0, "amount_threshold": 0.0, "confirm_days": 0, "amount_scale": 1.0, "amount_enabled": False}
        for feature in features:
            thresholds = HIGH_THRESHOLDS if feature.endswith("high") else LOW_THRESHOLDS
            for window in AMOUNT_WINDOWS:
                for thr in thresholds:
                    for days in CONFIRM_DAYS:
                        for scale in SCALES:
                            yield {**anchor, "candidate": f"l6_{anchor['anchor']}_{feature}_w{window}_thr{fmt(thr)}_d{days}_scale{fmt(scale)}", "amount_feature": feature, "amount_window": window, "amount_threshold": thr, "confirm_days": days, "amount_scale": scale, "amount_enabled": True}


def add_tiers(wm: pd.DataFrame) -> pd.DataFrame:
    out = wm.copy()
    base_rows = out[out["amount_enabled"] == False].set_index("anchor")
    for col in ["ann_return_full", "max_dd_full", "ann_return_last_5y", "max_dd_last_5y", "sharpe_repo_full"]:
        out[f"base_{col}"] = out["anchor"].map(base_rows[col])
    out["full_ann_loss_pp"] = (out["base_ann_return_full"] - out["ann_return_full"]) * 100
    out["full_dd_improve_pp"] = (out["max_dd_full"] - out["base_max_dd_full"]) * 100
    out["fivey_ann_loss_pp"] = (out["base_ann_return_last_5y"] - out["ann_return_last_5y"]) * 100
    out["fivey_dd_improve_pp"] = (out["max_dd_last_5y"] - out["base_max_dd_last_5y"]) * 100
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        out[f"pass_loss_le_{tag}pp"] = (out["amount_enabled"] == True) & (out["full_ann_loss_pp"] <= tier + 1e-12) & (out["full_dd_improve_pp"] > 0)
    return out


def patch_summary(wm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        pass_col = f"pass_loss_le_{tag}pp"
        for (anchor, feature), d in wm[wm["amount_enabled"] == True].groupby(["anchor", "amount_feature"]):
            p = d[d[pass_col]].copy()
            if p.empty:
                rows.append({"loss_tier_pp": tier, "anchor": anchor, "amount_feature": feature, "pass_count": 0, "window_count": 0, "threshold_count": 0, "day_count": 0, "scale_count": 0, "best_candidate": "", "best_full_ann_return": np.nan, "best_full_max_dd": np.nan, "best_full_ann_loss_pp": np.nan, "best_full_dd_improve_pp": np.nan, "best_5y_ann_return": np.nan, "best_5y_max_dd": np.nan, "patch_like": False})
                continue
            best = p.sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False]).iloc[0]
            patch_like = bool(len(p) >= 4 and p["amount_window"].nunique() >= 2 and p["amount_threshold"].nunique() >= 2)
            rows.append({"loss_tier_pp": tier, "anchor": anchor, "amount_feature": feature, "pass_count": int(len(p)), "window_count": int(p["amount_window"].nunique()), "threshold_count": int(p["amount_threshold"].nunique()), "day_count": int(p["confirm_days"].nunique()), "scale_count": int(p["amount_scale"].nunique()), "best_candidate": best["candidate"], "best_full_ann_return": best["ann_return_full"], "best_full_max_dd": best["max_dd_full"], "best_full_ann_loss_pp": best["full_ann_loss_pp"], "best_full_dd_improve_pp": best["full_dd_improve_pp"], "best_5y_ann_return": best["ann_return_last_5y"], "best_5y_max_dd": best["max_dd_last_5y"], "patch_like": patch_like})
    return pd.DataFrame(rows).sort_values(["loss_tier_pp", "patch_like", "pass_count", "best_full_dd_improve_pp"], ascending=[True, False, False, False])


def main() -> None:
    amount_panel = compose_amount_panel()
    mod, cyb, sz50, panel = load_price_panel()
    # Align amount to formal price dates and require both series available.
    amount_panel = amount_panel.reindex(panel.index)
    base_by_anchor = {a["anchor"]: base_after_volhot(panel, a) for a in ANCHORS}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = list(make_grid())
    long_rows = []
    wide_rows = []
    daily_parts = []
    for cand in grid:
        result = apply_amount_overlay(base_by_anchor[cand["anchor"]], amount_panel, None if not cand["amount_enabled"] else str(cand["amount_feature"]), None if not cand["amount_enabled"] else int(cand["amount_window"]), None if not cand["amount_enabled"] else float(cand["amount_threshold"]), None if not cand["amount_enabled"] else int(cand["confirm_days"]), None if not cand["amount_enabled"] else float(cand["amount_scale"]))
        daily = result.copy()
        daily["nav"] = (1.0 + daily["return"]).cumprod()
        daily["candidate"] = cand["candidate"]
        daily_parts.append(daily.reset_index(names="date"))
        wide = {**cand}
        wide["amount_days_full"] = int(result["amount_on"].sum())
        for segment, years in base.SEGMENTS:
            m = base.metrics_for_segment(result, segment, years)
            long_rows.append({**cand, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)
    scan_summary = pd.DataFrame(long_rows)
    window_metrics = add_tiers(pd.DataFrame(wide_rows))
    ridge = patch_summary(window_metrics)
    daily_all = pd.concat(daily_parts, ignore_index=True)
    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")
    daily_all.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    top_by_tier = {}
    for tier in LOSS_TIERS:
        tag = str(tier).replace(".", "p")
        passed = window_metrics[window_metrics[f"pass_loss_le_{tag}pp"]].sort_values(["full_dd_improve_pp", "ann_return_full"], ascending=[False, False])
        passed.to_csv(RUN_DIR / f"dd_first_pass_loss_le_{tag}pp.csv", index=False, encoding="utf-8-sig")
        top_by_tier[tier] = passed
    cols = ["candidate", "anchor", "amount_feature", "amount_window", "amount_threshold", "confirm_days", "amount_scale", "amount_days_full", "ann_return_full", "max_dd_full", "full_ann_loss_pp", "full_dd_improve_pp", "ann_return_last_5y", "max_dd_last_5y", "fivey_ann_loss_pp", "fivey_dd_improve_pp", "sharpe_repo_full"]
    record_lines = [
        "# CYB/SZ50 Layer 6 Amount Defense After NAV+Volhot",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer6_amount_complete_not_promoted`",
        "- stability: `amount_defense_patch_review`",
        "",
        "## Research Question",
        "Test final amount/volume defense after NAV+realized-vol overheat.",
        "",
        "## Implementation Anchor",
        "- CYB amount comes from existing EastMoney panel; SZ50 amount comes from existing CSIndex fallback panel.",
        "- Raw units differ, so scan uses only own-MA relative features and CYB_rel/SZ50_rel.",
        "",
        "## Data Snapshot",
        f"- CYB price rows: {len(cyb)}, start {cyb.index.min().date()}, end {cyb.index.max().date()}.",
        f"- SZ50 price rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- Formal aligned price rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        f"- Amount panel: `{OUTPUT_AMOUNT}`.",
        "",
        "## Cost and Execution Assumptions",
        "- Amount trigger is T-close state shifted to next execution row.",
        "- Two-leg transaction cost with one-way commission 0.0005 on final exposure changes.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python -m py_compile \"scan_adk_cyb_sz50_spread_layer6_amount_after_nav_volhot.py\"`",
        "- `python \"scan_adk_cyb_sz50_spread_layer6_amount_after_nav_volhot.py\"`",
        "- strict artifact checker after run.",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
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
        "Layer 6 completed but not promoted. Stop for final review.",
        "",
        "## User-Facing Summary",
        f"- loss<=1pp pass count: {len(top_by_tier[1.0])}",
        f"- loss<=2pp pass count: {len(top_by_tier[2.0])}",
        f"- loss<=3pp pass count: {len(top_by_tier[3.0])}",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")
    meta = {"run_id": RUN_DIR.name, "created_at": datetime.now().isoformat(timespec="seconds"), "project": "A-share / US momentum combo", "strategy": "V7.7 ADK spread research", "repo_root": str(base.ROOT), "entrypoint": str(Path(__file__).name), "implementation_anchor": "scan_adk_cyb_sz50_spread_long_only.py", "git_branch": "not_checked_agent_policy", "git_commit": "not_checked_agent_policy", "git_status_before": "not_checked_agent_policy", "git_status_after": "not_checked_agent_policy", "scan_type": "fresh_layer6_amount_after_nav_volhot", "parameter_group": "amount_relative_ma_defense", "baseline": {"anchors": ANCHORS, "loss_tiers_pp": LOSS_TIERS, "unit_warning": "raw CYB/SZ50 amount units differ; no raw ratio used"}, "candidate_grid": grid, "cost_model": {"one_way_commission": base.COMMISSION_ONE_WAY, "legs": 2, "execution": "T close signal -> T+1 close-to-close return"}, "data_snapshot": {"source": "composed local amount panel", "amount_csv": str(OUTPUT_AMOUNT), "formal": {"rows": int(len(panel)), "start": str(panel.index.min().date()), "end": str(panel.index.max().date())}}, "decision": "layer6_amount_complete_not_promoted", "stability_label": "amount_defense_patch_review", "outputs": {"record": str(RUN_DIR / "record.md"), "scan_summary": str(RUN_DIR / "scan_summary.csv"), "window_metrics": str(RUN_DIR / "window_metrics.csv"), "scan_meta": str(RUN_DIR / "scan_meta.json"), "command_log": str(RUN_DIR / "command_log.txt"), "daily_curves": str(RUN_DIR / "daily_curves.csv"), "ridge_width": str(RUN_DIR / "ridge_width.csv")}}
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text("python -m py_compile \"scan_adk_cyb_sz50_spread_layer6_amount_after_nav_volhot.py\"\npython \"scan_adk_cyb_sz50_spread_layer6_amount_after_nav_volhot.py\"\npython C:\\Users\\Administrator.DESKTOP-95I7VVU\\.codex\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>\n", encoding="utf-8")
    print(f"RUN_DIR={RUN_DIR}")
    print(f"AMOUNT={OUTPUT_AMOUNT}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("BASELINES")
    print(window_metrics[window_metrics.amount_enabled == False][cols].to_string(index=False))
    for tier in LOSS_TIERS:
        print(f"LOSS_LE_{tier}PP_COUNT={len(top_by_tier[tier])}")
        print(top_by_tier[tier][cols].head(12).to_string(index=False) if not top_by_tier[tier].empty else "NONE")
    print("RIDGE")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

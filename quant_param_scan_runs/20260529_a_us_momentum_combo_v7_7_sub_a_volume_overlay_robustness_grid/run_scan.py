import importlib.util
import json
import pathlib
import subprocess
import warnings
from datetime import datetime

import numpy as np
import pandas as pd


warnings.filterwarnings("ignore", category=FutureWarning)

RUN_DIR = pathlib.Path(__file__).resolve().parent
REPO = RUN_DIR.parents[1]
ENTRYPOINT = REPO / "mnt_bot V 7.7 plus.py"

FIELDS = ["amount", "volume"]
MA_VALUES = [10, 15, 20, 30]
ZZ_DAYS_VALUES = [2, 3, 4, 5]
CYB_DAYS_VALUES = [3, 4, 5, 6]
SCALE_VALUES = [0.0, 0.25, 0.5, 0.75]
WINDOW_ORDER = ["full", "last_10y", "last_5y", "last_3y", "last_1y"]


def git(cmd):
    try:
        return subprocess.check_output(
            ["git", *cmd],
            cwd=REPO,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
    except Exception as exc:
        return f"UNAVAILABLE: {exc}"


def load_module():
    spec = importlib.util.spec_from_file_location("mnt_bot_v77_volume_grid", ENTRYPOINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_close_confirmed_input(mod):
    cn_raw = {}
    cn_sources = {}
    bj_today = mod.beijing_now().date()
    for secid in mod.CN_STOCK_CODES:
        df, source = mod.fetch_cn_kline(secid)
        df = mod._drop_cn_unconfirmed_today(df)
        # This robustness scan intentionally excludes the current Beijing date.
        # Some A-share price feeds update before the bond fallback, which would
        # otherwise trip the production freshness guard or mix data vintages.
        df = df.loc[[pd.Timestamp(idx).date() < bj_today for idx in df.index]]
        cn_raw[secid] = df
        cn_sources[secid] = source
    cn_close = pd.concat(
        [cn_raw[s].rename(columns={"close": s})[[s]] for s in mod.CN_STOCK_CODES],
        axis=1,
    ).ffill().dropna()
    cn_close_with_bond = mod._add_cn_bond_column(
        cn_close,
        msg=None,
        context="Sub-A volume robustness grid",
        strict=True,
        include_live_snapshot=False,
    )
    return cn_close_with_bond, cn_sources


def build_base_suba_result(mod, cn_close_with_bond):
    base = mod.run_cn_strategy(cn_close_with_bond, mod.CN_EQUITY_CODES)
    if mod.CN_SA_CASH_OVERLAY_ENABLED:
        base = mod.apply_suba_cash_peak_decay_overlay(
            base,
            cn_close_with_bond,
            decay_ratio_threshold=mod.CN_SA_CASH_OVERLAY_DECAY_RATIO,
            recovery_ratio_threshold=mod.CN_SA_CASH_OVERLAY_RECOVERY_RATIO,
            commission=mod.CN_COMMISSION,
        )
    if mod.CN_SA_SAME_SIDE_OVERHEAT_ENABLED:
        base = mod.apply_suba_same_side_overheat_overlay(
            base,
            cn_close_with_bond,
            enter_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_ENTER,
            exit_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_EXIT,
            derisk_scale=mod.CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE,
        )
    return base


def fetch_volume_inputs(mod):
    out = {}
    sources = {}
    for name, label, secid in [
        ("zz2000", "ZZ2000", mod.CN_SA_VOLUME_ZZ2000_SECID),
        ("cyb", "CYB", mod.CN_SA_VOLUME_CYB_SECID),
    ]:
        df, source = mod._fetch_cn_amount_with_fallback(
            secid,
            label,
            beg=mod.CN_SA_VOLUME_HISTORY_BEG,
            lmt=10000,
        )
        out[name] = {
            "amount": pd.to_numeric(df["amount"], errors="coerce").dropna().sort_index(),
            "volume": pd.to_numeric(df["volume"], errors="coerce").dropna().sort_index(),
        }
        sources[name] = source
    return out, sources


def build_signal_feature(mod, volume_inputs, field, ma, zz_days, cyb_days, scale):
    specs = {
        "zz2000": {"amount": volume_inputs["zz2000"][field], "ma": ma, "days": zz_days},
        "cyb": {"amount": volume_inputs["cyb"][field], "ma": ma, "days": cyb_days},
    }
    signal, feature = mod._build_consecutive_below_amount_signal(
        specs,
        mode=mod.CN_SA_VOLUME_RULE_MODE,
    )
    feature = feature.copy()
    feature["old_combined_signal"] = signal.reindex(feature.index).fillna(False).astype(bool)
    feature["severe_ratio_signal"] = False
    feature["combined_signal"] = feature["old_combined_signal"]
    feature["combined_scale"] = np.where(feature["combined_signal"], float(scale), 1.0)
    feature["clear_signal"] = False
    feature["clear_ratio_enabled"] = False
    feature["clear_ratio_unavailable"] = False
    feature["combined_unresolved"] = False
    feature["partial_unavailable"] = False
    feature["field"] = field
    if field == "volume":
        feature = feature.rename(
            columns={
                "zz2000_amount": "zz2000_volume",
                "cyb_amount": "cyb_volume",
            }
        )
    return signal, feature


def calc_metrics(ret):
    ret = pd.to_numeric(ret, errors="coerce").dropna()
    nav = (1.0 + ret).cumprod()
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    annual = nav.iloc[-1] ** (1.0 / years) - 1.0 if years > 0 else np.nan
    vol = ret.std() * np.sqrt(242)
    sharpe = ret.mean() / ret.std() * np.sqrt(242) if ret.std() > 0 else 0.0
    max_dd = (nav / nav.cummax() - 1.0).min()
    return {
        "ann_return": float(annual),
        "ann_vol": float(vol),
        "max_dd": float(max_dd),
        "sharpe_repo": float(sharpe),
        "total_return": float(nav.iloc[-1] - 1.0),
        "years": float(years),
        "rows": int(len(ret)),
        "start": ret.index[0].date().isoformat(),
        "end": ret.index[-1].date().isoformat(),
    }


def fixed_window_metrics(candidate, ret, start_date, end_date):
    windows = {
        "full": start_date,
        "last_10y": pd.Timestamp(end_date) - pd.DateOffset(years=10),
        "last_5y": pd.Timestamp(end_date) - pd.DateOffset(years=5),
        "last_3y": pd.Timestamp(end_date) - pd.DateOffset(years=3),
        "last_1y": pd.Timestamp(end_date) - pd.DateOffset(years=1),
    }
    rows = []
    wide = {"candidate": candidate}
    for segment, raw_start in windows.items():
        wstart = max(pd.Timestamp(raw_start), pd.Timestamp(start_date))
        wret = ret.loc[(ret.index >= wstart) & (ret.index <= end_date)]
        metrics = calc_metrics(wret)
        rows.append({"candidate": candidate, "segment": segment, **metrics})
        wide[f"ann_return_{segment}"] = metrics["ann_return"]
        wide[f"max_dd_{segment}"] = metrics["max_dd"]
        wide[f"ann_vol_{segment}"] = metrics["ann_vol"]
        wide[f"sharpe_{segment}"] = metrics["sharpe_repo"]
    return rows, wide


def rolling_window_metrics(candidate, ret, years, step="M"):
    ret = pd.to_numeric(ret, errors="coerce").dropna()
    if ret.empty:
        return []
    endpoints = pd.date_range(ret.index[0] + pd.DateOffset(years=years), ret.index[-1], freq=step)
    rows = []
    for end in endpoints:
        start = end - pd.DateOffset(years=years)
        wret = ret.loc[(ret.index >= start) & (ret.index <= end)]
        if len(wret) < 242 * years * 0.75:
            continue
        m = calc_metrics(wret)
        rows.append(
            {
                "candidate": candidate,
                "rolling_years": years,
                "window_start": m["start"],
                "window_end": m["end"],
                "ann_return": m["ann_return"],
                "max_dd": m["max_dd"],
                "sharpe_repo": m["sharpe_repo"],
            }
        )
    return rows


def rolling_summary(rolling_df):
    rows = []
    if rolling_df.empty:
        return pd.DataFrame()
    for (candidate, years), grp in rolling_df.groupby(["candidate", "rolling_years"]):
        rows.append(
            {
                "candidate": candidate,
                "rolling_years": years,
                "count": int(len(grp)),
                "ann_return_median": float(grp["ann_return"].median()),
                "ann_return_p25": float(grp["ann_return"].quantile(0.25)),
                "ann_return_min": float(grp["ann_return"].min()),
                "max_dd_median": float(grp["max_dd"].median()),
                "max_dd_worst": float(grp["max_dd"].min()),
                "sharpe_median": float(grp["sharpe_repo"].median()),
            }
        )
    return pd.DataFrame(rows)


def candidate_id(field, ma, zz_days, cyb_days, scale):
    return f"{field}_ma{ma}_zz{zz_days}_cyb{cyb_days}_scale{scale:g}"


def is_current_rule(row):
    return (
        row.get("field") == "amount"
        and int(row.get("ma", -1)) == 15
        and int(row.get("zz_days", -1)) == 3
        and int(row.get("cyb_days", -1)) == 5
        and abs(float(row.get("scale", np.nan)) - 0.0) < 1e-12
    )


def main():
    started = datetime.now().isoformat(timespec="seconds")
    mod = load_module()
    cn_close_with_bond, cn_sources = build_close_confirmed_input(mod)
    base = build_base_suba_result(mod, cn_close_with_bond)
    volume_inputs, volume_sources = fetch_volume_inputs(mod)
    end_date = base.index.max()
    start_date = base.index.min()

    scan_rows = []
    wide_rows = []
    rolling_rows = []
    daily_nav = pd.DataFrame(index=base.index)
    daily_nav["return_no_overlay"] = base["return"]
    daily_nav["nav_no_overlay"] = (1.0 + base["return"]).cumprod()

    fixed_rows, wide = fixed_window_metrics("no_overlay", base["return"], start_date, end_date)
    for row in fixed_rows:
        scan_rows.append({"field": "none", "ma": 0, "zz_days": 0, "cyb_days": 0, "scale": 1.0, **row})
    wide_rows.append({"field": "none", "ma": 0, "zz_days": 0, "cyb_days": 0, "scale": 1.0, **wide})
    rolling_rows.extend(rolling_window_metrics("no_overlay", base["return"], 3))
    rolling_rows.extend(rolling_window_metrics("no_overlay", base["return"], 5))

    total = len(FIELDS) * len(MA_VALUES) * len(ZZ_DAYS_VALUES) * len(CYB_DAYS_VALUES) * len(SCALE_VALUES)
    done = 0
    for field in FIELDS:
        for ma in MA_VALUES:
            for zz_days in ZZ_DAYS_VALUES:
                for cyb_days in CYB_DAYS_VALUES:
                    for scale in SCALE_VALUES:
                        cid = candidate_id(field, ma, zz_days, cyb_days, scale)
                        signal, feature = build_signal_feature(mod, volume_inputs, field, ma, zz_days, cyb_days, scale)
                        feature = mod._annotate_rule_freshness(
                            feature,
                            expected_date=end_date,
                            rule_key="suba_volume",
                        )
                        result = mod._apply_suba_volume_overlay_policy(
                            base,
                            cn_close_with_bond,
                            signal,
                            feature,
                            allow_unresolved_suba_volume=False,
                        )
                        fixed_rows, wide = fixed_window_metrics(cid, result["return"], start_date, end_date)
                        for row in fixed_rows:
                            scan_rows.append(
                                {
                                    "field": field,
                                    "ma": ma,
                                    "zz_days": zz_days,
                                    "cyb_days": cyb_days,
                                    "scale": scale,
                                    **row,
                                }
                            )
                        wide_rows.append(
                            {
                                "field": field,
                                "ma": ma,
                                "zz_days": zz_days,
                                "cyb_days": cyb_days,
                                "scale": scale,
                                "trigger_days": int(result["suba_volume_rule_on"].fillna(False).astype(bool).sum())
                                if "suba_volume_rule_on" in result.columns
                                else 0,
                                **wide,
                            }
                        )
                        if is_current_rule({"field": field, "ma": ma, "zz_days": zz_days, "cyb_days": cyb_days, "scale": scale}):
                            daily_nav[f"return_{cid}"] = result["return"]
                            daily_nav[f"nav_{cid}"] = (1.0 + result["return"]).cumprod()
                            daily_nav["current_rule_weight"] = result.get("weight")
                            daily_nav["current_rule_holding"] = result.get("holding")
                        rolling_rows.extend(rolling_window_metrics(cid, result["return"], 3))
                        rolling_rows.extend(rolling_window_metrics(cid, result["return"], 5))
                        done += 1
                        if done % 50 == 0:
                            print(f"progress {done}/{total}", flush=True)

    scan_summary = pd.DataFrame(scan_rows)
    window_metrics = pd.DataFrame(wide_rows)
    rolling = pd.DataFrame(rolling_rows)
    roll_summary = rolling_summary(rolling)

    # Composite scores are descriptive only, not optimization directives.
    wm = window_metrics.copy()
    for col in [
        "ann_return_full",
        "ann_return_last_10y",
        "ann_return_last_5y",
        "ann_return_last_3y",
        "max_dd_full",
        "max_dd_last_10y",
        "max_dd_last_5y",
        "max_dd_last_3y",
    ]:
        wm[col] = pd.to_numeric(wm[col], errors="coerce")
    wm["avg_ann_10_5_3"] = wm[["ann_return_last_10y", "ann_return_last_5y", "ann_return_last_3y"]].mean(axis=1)
    wm["worst_dd_10_5_3"] = wm[["max_dd_last_10y", "max_dd_last_5y", "max_dd_last_3y"]].min(axis=1)
    wm["avg_ann_full_10_5_3"] = wm[
        ["ann_return_full", "ann_return_last_10y", "ann_return_last_5y", "ann_return_last_3y"]
    ].mean(axis=1)
    wm["worst_dd_full_10_5_3"] = wm[
        ["max_dd_full", "max_dd_last_10y", "max_dd_last_5y", "max_dd_last_3y"]
    ].min(axis=1)
    wm["current_rule"] = wm.apply(is_current_rule, axis=1)
    amount = wm[wm["field"] == "amount"].copy()
    volume = wm[wm["field"] == "volume"].copy()
    current = wm[wm["current_rule"]].iloc[0]
    summary_cards = {
        "current_rule": current.to_dict(),
        "rankings": {
            "current_avg_ann_full_10_5_3_rank_all": int(
                wm["avg_ann_full_10_5_3"].rank(ascending=False, method="min").loc[current.name]
            ),
            "candidate_count_all": int(len(wm)),
            "current_worst_dd_full_10_5_3_rank_all": int(
                wm["worst_dd_full_10_5_3"].rank(ascending=False, method="min").loc[current.name]
            ),
            "current_avg_ann_full_10_5_3_rank_amount": int(
                amount["avg_ann_full_10_5_3"].rank(ascending=False, method="min").loc[current.name]
            ),
            "candidate_count_amount": int(len(amount)),
        },
        "top_by_avg_ann_full_10_5_3": wm.sort_values("avg_ann_full_10_5_3", ascending=False).head(20).to_dict("records"),
        "top_by_worst_dd_full_10_5_3": wm.sort_values("worst_dd_full_10_5_3", ascending=False).head(20).to_dict("records"),
        "nearest_neighbors_scale0": wm[
            (wm["field"] == "amount")
            & (wm["scale"].astype(float) == 0.0)
            & (wm["ma"].isin([10, 15, 20]))
            & (wm["zz_days"].isin([2, 3, 4]))
            & (wm["cyb_days"].isin([4, 5, 6]))
        ].sort_values(["ma", "zz_days", "cyb_days"]).to_dict("records"),
    }

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    wm.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    rolling.to_csv(RUN_DIR / "rolling_windows.csv", index=False, encoding="utf-8-sig")
    roll_summary.to_csv(RUN_DIR / "rolling_summary.csv", index=False, encoding="utf-8-sig")
    daily_nav.to_csv(RUN_DIR / "daily_selected.csv", encoding="utf-8-sig")
    (RUN_DIR / "summary_cards.json").write_text(json.dumps(summary_cards, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": started,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "project": "a_us_momentum_combo",
        "strategy": "v7_7_sub_a",
        "parameter_group": "volume_overlay_robustness_grid",
        "scan_type": "robustness_grid",
        "repo_root": str(REPO),
        "entrypoint": str(ENTRYPOINT),
        "git_branch": git(["branch", "--show-current"]),
        "git_commit": git(["rev-parse", "HEAD"]),
        "git_status_before": git(["status", "--short"]),
        "git_status_after": git(["status", "--short"]),
        "baseline": "amount_ma15_zz3_cyb5_scale0",
        "candidate_grid": {
            "fields": FIELDS,
            "ma_values": MA_VALUES,
            "zz_days_values": ZZ_DAYS_VALUES,
            "cyb_days_values": CYB_DAYS_VALUES,
            "scale_values": SCALE_VALUES,
            "candidate_count_without_no_overlay": total,
        },
        "decision": "research_only_no_production_change",
        "stability_label": "deep_robustness_grid_current_v77_close_confirmed",
        "cost_model": {
            "CN_COMMISSION": mod.CN_COMMISSION,
            "return_column": "cn_result[return]",
            "state_machine_costs": True,
            "open_impact": "not modeled separately; production close-to-close Sub-A path",
        },
        "data_snapshot": {
            "start_date": str(start_date.date()),
            "end_date": str(end_date.date()),
            "close_confirmed": True,
            "dropped_unconfirmed_current_day": True,
            "cn_sources": cn_sources,
            "volume_sources": volume_sources,
        },
        "defaults": {
            "CN_TARGET_VOL": mod.CN_TARGET_VOL,
            "CN_VOL_WINDOW": mod.CN_VOL_WINDOW,
            "CN_MAX_LEV": mod.CN_MAX_LEV,
            "CN_COMMISSION": mod.CN_COMMISSION,
            "CN_SA_CASH_OVERLAY_ENABLED": bool(mod.CN_SA_CASH_OVERLAY_ENABLED),
            "CN_SA_SAME_SIDE_OVERHEAT_ENABLED": bool(mod.CN_SA_SAME_SIDE_OVERHEAT_ENABLED),
            "CN_SA_VOLUME_SCALE": mod.CN_SA_VOLUME_SCALE,
            "CN_SA_VOLUME_ZZ2000_MA": mod.CN_SA_VOLUME_ZZ2000_MA,
            "CN_SA_VOLUME_ZZ2000_DAYS": mod.CN_SA_VOLUME_ZZ2000_DAYS,
            "CN_SA_VOLUME_CYB_MA": mod.CN_SA_VOLUME_CYB_MA,
            "CN_SA_VOLUME_CYB_DAYS": mod.CN_SA_VOLUME_CYB_DAYS,
        },
        "outputs": {
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "rolling_windows": str(RUN_DIR / "rolling_windows.csv"),
            "rolling_summary": str(RUN_DIR / "rolling_summary.csv"),
            "daily_selected": str(RUN_DIR / "daily_selected.csv"),
            "summary_cards": str(RUN_DIR / "summary_cards.json"),
            "record": str(RUN_DIR / "record.md"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
        },
        "notes": [
            "No production strategy file was edited.",
            "The grid uses the same production overlay timing and return rebuild function.",
            "Composite scores are descriptive and are not a production recommendation.",
        ],
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (RUN_DIR / "record.md").write_text(
        f"""# V7.7 Sub-A Volume Overlay Robustness Grid

Goal: test whether the current amount-based volume overlay is robust or suspiciously point-fit.

Entry point: `mnt_bot V 7.7 plus.py`
Data end: {end_date.date().isoformat()} close-confirmed.

Grid:
- fields: {FIELDS}
- MA: {MA_VALUES}
- ZZ2000 days: {ZZ_DAYS_VALUES}
- CYB days: {CYB_DAYS_VALUES}
- scale after trigger: {SCALE_VALUES}

Decision: research_only_no_production_change
Stability: deep_robustness_grid_current_v77_close_confirmed

Outputs:
- `scan_summary.csv`
- `window_metrics.csv`
- `rolling_windows.csv`
- `rolling_summary.csv`
- `summary_cards.json`
- `daily_selected.csv`

No production file was edited.
""",
        encoding="utf-8",
    )
    print(f"RUN_DIR {RUN_DIR}")
    print(f"DATA_RANGE {start_date.date()} {end_date.date()}")
    print(json.dumps(summary_cards["rankings"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

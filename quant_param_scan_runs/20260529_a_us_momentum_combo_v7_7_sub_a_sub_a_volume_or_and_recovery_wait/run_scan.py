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

FIELD = "amount"
MA = 20
ZZ_DAYS = 3
CYB_DAYS = 4
SCALE = 0.0
MODES = ["or", "and"]
RECOVERY_WAIT_DAYS = [0, 1, 2, 3]
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
    spec = importlib.util.spec_from_file_location("mnt_bot_v77_or_and_recovery", ENTRYPOINT)
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
        context="Sub-A volume OR/AND recovery scan",
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


def apply_recovery_wait(raw_signal, wait_days):
    """Keep the overlay active for wait_days extra false-signal trading days."""
    raw_signal = pd.Series(raw_signal, dtype=bool).sort_index()
    active = False
    false_after_active = 0
    effective = []
    for flag in raw_signal:
        if bool(flag):
            active = True
            false_after_active = 0
        elif active:
            false_after_active += 1
            if false_after_active > int(wait_days):
                active = False
                false_after_active = 0
        effective.append(active)
    return pd.Series(effective, index=raw_signal.index, dtype=bool)


def build_signal_feature(mod, volume_inputs, mode, recovery_wait):
    specs = {
        "zz2000": {"amount": volume_inputs["zz2000"][FIELD], "ma": MA, "days": ZZ_DAYS},
        "cyb": {"amount": volume_inputs["cyb"][FIELD], "ma": MA, "days": CYB_DAYS},
    }
    raw_signal, feature = mod._build_consecutive_below_amount_signal(specs, mode=mode)
    effective_signal = apply_recovery_wait(raw_signal, recovery_wait)
    feature = feature.copy()
    feature["raw_combined_signal"] = raw_signal.reindex(feature.index).fillna(False).astype(bool)
    feature["recovery_wait_days"] = int(recovery_wait)
    feature["old_combined_signal"] = effective_signal.reindex(feature.index).fillna(False).astype(bool)
    feature["severe_ratio_signal"] = False
    feature["combined_signal"] = feature["old_combined_signal"]
    feature["combined_scale"] = np.where(feature["combined_signal"], SCALE, 1.0)
    feature["clear_signal"] = False
    feature["clear_ratio_enabled"] = False
    feature["clear_ratio_unavailable"] = False
    feature["combined_unresolved"] = False
    feature["partial_unavailable"] = False
    feature["field"] = FIELD
    feature["mode"] = mode
    return effective_signal, raw_signal, feature


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


def count_episodes(signal):
    signal = pd.Series(signal, dtype=bool).sort_index()
    if signal.empty:
        return []
    episode_id = (signal.astype(int).diff().fillna(signal.astype(int)) == 1).cumsum()
    rows = []
    for _, grp in signal[signal].groupby(episode_id[signal]):
        rows.append({"start": grp.index[0], "end": grp.index[-1], "days": int(len(grp))})
    return rows


def candidate_id(mode, recovery_wait):
    return f"{FIELD}_ma{MA}_zz{ZZ_DAYS}_cyb{CYB_DAYS}_{mode}_recwait{recovery_wait}_scale{SCALE:g}"


def recent_status_table(volume_inputs, raw_signals, effective_signals, end_date, n=12):
    zz = volume_inputs["zz2000"][FIELD].rename("zz2000")
    cyb = volume_inputs["cyb"][FIELD].rename("cyb")
    frame = pd.concat([zz, cyb], axis=1).dropna().sort_index()
    frame = frame.loc[frame.index <= end_date].tail(n).copy()
    frame["zz_ma"] = zz.rolling(MA).mean().reindex(frame.index)
    frame["cyb_ma"] = cyb.rolling(MA).mean().reindex(frame.index)
    frame["zz_ratio"] = frame["zz2000"] / frame["zz_ma"]
    frame["cyb_ratio"] = frame["cyb"] / frame["cyb_ma"]
    frame["zz_streak"] = mod_consecutive(zz, MA).reindex(frame.index)
    frame["cyb_streak"] = mod_consecutive(cyb, MA).reindex(frame.index)
    for key, sig in raw_signals.items():
        frame[f"{key}_raw"] = sig.reindex(frame.index).fillna(False).astype(bool)
    for key, sig in effective_signals.items():
        frame[f"{key}_effective"] = sig.reindex(frame.index).fillna(False).astype(bool)
    frame.index.name = "date"
    return frame.reset_index()


def mod_consecutive(amount, ma):
    amount = pd.Series(amount, dtype=float).sort_index()
    ratio = amount / amount.rolling(int(ma)).mean()
    below = ratio < 1.0
    cur = 0
    out = []
    for val in below.fillna(False):
        cur = cur + 1 if bool(val) else 0
        out.append(cur)
    return pd.Series(out, index=amount.index, dtype=float)


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
    episode_rows = []
    daily = pd.DataFrame(index=base.index)
    daily["return_no_overlay"] = base["return"]
    daily["nav_no_overlay"] = (1.0 + base["return"]).cumprod()
    raw_for_recent = {}
    eff_for_recent = {}

    no_overlay_rows, no_overlay_wide = fixed_window_metrics("no_overlay", base["return"], start_date, end_date)
    for row in no_overlay_rows:
        scan_rows.append(
            {
                "field": "none",
                "ma": 0,
                "zz_days": 0,
                "cyb_days": 0,
                "mode": "none",
                "recovery_wait_days": 0,
                "scale": 1.0,
                **row,
            }
        )
    wide_rows.append(
        {
            "field": "none",
            "ma": 0,
            "zz_days": 0,
            "cyb_days": 0,
            "mode": "none",
            "recovery_wait_days": 0,
            "scale": 1.0,
            "raw_trigger_days": 0,
            "effective_trigger_days": 0,
            "episode_count": 0,
            "latest_raw_signal": False,
            "latest_effective_signal": False,
            **no_overlay_wide,
        }
    )

    for mode in MODES:
        for recovery_wait in RECOVERY_WAIT_DAYS:
            cid = candidate_id(mode, recovery_wait)
            effective_signal, raw_signal, feature = build_signal_feature(mod, volume_inputs, mode, recovery_wait)
            feature = mod._annotate_rule_freshness(
                feature,
                expected_date=end_date,
                rule_key="suba_volume",
            )
            result = mod._apply_suba_volume_overlay_policy(
                base,
                cn_close_with_bond,
                effective_signal,
                feature,
                allow_unresolved_suba_volume=False,
            )
            fixed_rows, wide = fixed_window_metrics(cid, result["return"], start_date, end_date)
            for row in fixed_rows:
                scan_rows.append(
                    {
                        "field": FIELD,
                        "ma": MA,
                        "zz_days": ZZ_DAYS,
                        "cyb_days": CYB_DAYS,
                        "mode": mode,
                        "recovery_wait_days": recovery_wait,
                        "scale": SCALE,
                        **row,
                    }
                )
            raw_aligned = raw_signal.reindex(base.index).fillna(False).astype(bool)
            eff_aligned = effective_signal.reindex(base.index).fillna(False).astype(bool)
            episodes = count_episodes(eff_aligned)
            for ep in episodes:
                episode_rows.append(
                    {
                        "candidate": cid,
                        "mode": mode,
                        "recovery_wait_days": recovery_wait,
                        "start": ep["start"].date().isoformat(),
                        "end": ep["end"].date().isoformat(),
                        "days": ep["days"],
                    }
                )
            wide_rows.append(
                {
                    "field": FIELD,
                    "ma": MA,
                    "zz_days": ZZ_DAYS,
                    "cyb_days": CYB_DAYS,
                    "mode": mode,
                    "recovery_wait_days": recovery_wait,
                    "scale": SCALE,
                    "raw_trigger_days": int(raw_aligned.sum()),
                    "effective_trigger_days": int(eff_aligned.sum()),
                    "episode_count": int(len(episodes)),
                    "avg_episode_days": float(np.mean([x["days"] for x in episodes])) if episodes else 0.0,
                    "latest_raw_signal": bool(raw_aligned.iloc[-1]),
                    "latest_effective_signal": bool(eff_aligned.iloc[-1]),
                    **wide,
                }
            )
            daily[f"return_{cid}"] = result["return"]
            daily[f"nav_{cid}"] = (1.0 + result["return"]).cumprod()
            daily[f"raw_{cid}"] = raw_aligned
            daily[f"effective_{cid}"] = eff_aligned
            raw_for_recent[f"{mode}_wait{recovery_wait}"] = raw_signal
            eff_for_recent[f"{mode}_wait{recovery_wait}"] = effective_signal

    scan_summary = pd.DataFrame(scan_rows)
    window_metrics = pd.DataFrame(wide_rows)
    episodes = pd.DataFrame(episode_rows)
    recent_status = recent_status_table(volume_inputs, raw_for_recent, eff_for_recent, end_date)

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
    wm["avg_ann_full_10_5_3"] = wm[
        ["ann_return_full", "ann_return_last_10y", "ann_return_last_5y", "ann_return_last_3y"]
    ].mean(axis=1)
    wm["worst_dd_full_10_5_3"] = wm[
        ["max_dd_full", "max_dd_last_10y", "max_dd_last_5y", "max_dd_last_3y"]
    ].min(axis=1)
    wm = wm.sort_values(["mode", "recovery_wait_days"]).reset_index(drop=True)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    wm.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    episodes.to_csv(RUN_DIR / "trigger_episodes.csv", index=False, encoding="utf-8-sig")
    recent_status.to_csv(RUN_DIR / "recent_status.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", encoding="utf-8-sig")

    summary = {
        "chosen_rule": {
            "field": FIELD,
            "ma": MA,
            "zz_days": ZZ_DAYS,
            "cyb_days": CYB_DAYS,
            "scale": SCALE,
            "recovery_wait_definition": "extra false-signal trading days before restoring exposure; 0 means immediate restore",
        },
        "ranked_candidates": wm.sort_values("avg_ann_full_10_5_3", ascending=False).to_dict("records"),
        "recent_tail": recent_status.tail(8).to_dict("records"),
    }
    (RUN_DIR / "summary_cards.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": started,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "phase": "complete",
        "project": "a_us_momentum_combo",
        "strategy": "v7_7_sub_a",
        "subsystem": "sub_a",
        "parameter_group": "volume_or_and_recovery_wait",
        "scan_type": "focused_state_machine_grid",
        "repo_root": str(REPO),
        "entrypoint": str(ENTRYPOINT),
        "git_branch": git(["branch", "--show-current"]),
        "git_commit": git(["rev-parse", "HEAD"]),
        "git_status_before": git(["status", "--short"]),
        "git_status_after": git(["status", "--short"]),
        "baseline": "no_overlay plus chosen amount_ma20_zz3_cyb4_scale0 variants",
        "candidate_grid": {
            "field": FIELD,
            "ma": MA,
            "zz_days": ZZ_DAYS,
            "cyb_days": CYB_DAYS,
            "modes": MODES,
            "recovery_wait_days": RECOVERY_WAIT_DAYS,
            "scale": SCALE,
            "candidate_count_without_no_overlay": len(MODES) * len(RECOVERY_WAIT_DAYS),
        },
        "decision": "research_only_no_production_change",
        "stability_label": "focused_or_and_recovery_wait_close_confirmed",
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
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "trigger_episodes": str(RUN_DIR / "trigger_episodes.csv"),
            "recent_status": str(RUN_DIR / "recent_status.csv"),
            "daily_curves": str(RUN_DIR / "daily_curves.csv"),
            "summary_cards": str(RUN_DIR / "summary_cards.json"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
        },
        "notes": [
            "No production strategy file was edited.",
            "Recovery wait keeps the overlay active for N extra false-signal trading days after a trigger.",
            "The candidate return streams reuse the production Sub-A overlay rebuild path.",
        ],
    }
    (RUN_DIR / "scan_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (RUN_DIR / "record.md").write_text(
        f"""# V7.7 Sub-A Volume OR/AND Recovery Wait Scan

Goal: compare OR vs AND trigger logic and recovery waits around the selected amount MA20 / ZZ3 / CYB4 / scale0 rule.

Entry point: `mnt_bot V 7.7 plus.py`
Data end: {end_date.date().isoformat()} close-confirmed.

Grid:
- field: `{FIELD}`
- MA: `{MA}`
- ZZ2000 days: `{ZZ_DAYS}`
- CYB days: `{CYB_DAYS}`
- mode: {MODES}
- recovery wait days: {RECOVERY_WAIT_DAYS}
- scale after trigger: `{SCALE}`

Recovery wait definition: keep the overlay active for N extra false-signal trading days before restoring exposure; 0 means immediate restore.

Decision: research_only_no_production_change
Stability: focused_or_and_recovery_wait_close_confirmed

Outputs:
- `scan_summary.csv`
- `window_metrics.csv`
- `trigger_episodes.csv`
- `recent_status.csv`
- `daily_curves.csv`
- `summary_cards.json`

No production file was edited.
""",
        encoding="utf-8",
    )
    print(f"RUN_DIR {RUN_DIR}")
    print(f"DATA_RANGE {start_date.date()} {end_date.date()}")
    print(wm[["candidate", "mode", "recovery_wait_days", "effective_trigger_days", "ann_return_full", "max_dd_full", "ann_return_last_3y", "max_dd_last_3y"]].to_string(index=False))


if __name__ == "__main__":
    main()

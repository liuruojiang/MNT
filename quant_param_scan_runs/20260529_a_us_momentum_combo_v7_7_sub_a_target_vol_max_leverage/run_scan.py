from __future__ import annotations

import builtins
import importlib.util
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = Path(__file__).resolve().parent
MNT_SCRIPT = ROOT / "mnt_bot V 7.7 plus.py"
FORMAL_START = pd.Timestamp("2014-10-17")
WINDOWS = {
    "full": FORMAL_START,
    "last_10y": pd.Timestamp("2016-05-29"),
    "last_5y": pd.Timestamp("2021-05-29"),
    "last_3y": pd.Timestamp("2023-05-29"),
    "last_1y": pd.Timestamp("2025-05-29"),
}
TARGET_VOLS = [0.15, 0.20, 0.25, 0.30, 0.35]
MAX_LEVS = [1.0, 1.2, 1.5]
VOL_WINDOW = 80


class _PoeStub:
    query = None
    default_chat: list[Any] = []

    class BotError(Exception):
        pass

    def update_settings(self, settings: object) -> None:
        self.settings = settings


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _git(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:
        return f"unavailable: {exc}"


def load_mnt_module() -> object:
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = _PoeStub()
    try:
        spec = importlib.util.spec_from_file_location("mnt_bot_v77_tv_lev_scan", str(MNT_SCRIPT))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {MNT_SCRIPT}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if had_poe:
            builtins.poe = old_poe
        else:
            delattr(builtins, "poe")


def build_cn_close(mod: object) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw: dict[str, pd.DataFrame] = {}
    sources: dict[str, str] = {}
    first_last: dict[str, dict[str, Any]] = {}
    proxy_notes: list[str] = []

    for secid in mod.CN_STOCK_CODES:
        df, source = mod.fetch_cn_kline(secid)
        df = mod._drop_cn_unconfirmed_today(df)
        raw[secid] = df.copy()
        sources[secid] = source
        first_last[secid] = {
            "name": mod.CN_NAMES.get(secid, secid),
            "first": str(pd.Timestamp(df.index.min()).date()),
            "last": str(pd.Timestamp(df.index.max()).date()),
            "rows": int(len(df)),
            "source": source,
        }
        time.sleep(0.1)

    zzhl_df = raw.get(mod.CN_ZZHL_INDEX_SECID)
    if zzhl_df is not None and len(zzhl_df) > 0:
        try:
            pre_df = mod._fetch_cn_csindex(mod.CN_ZZHL_PRE_INDEX_CODE)
            if pre_df is not None and len(pre_df) > 50:
                zzhl_start = zzhl_df.index[0]
                pre_only = pre_df[pre_df.index < zzhl_start].copy()
                if len(pre_only) > 0:
                    pre_only["close"] *= zzhl_df["close"].iloc[0] / pre_only["close"].iloc[-1]
                    raw[mod.CN_ZZHL_INDEX_SECID] = pd.concat([pre_only, zzhl_df])
                    proxy_notes.append(
                        f"{mod.CN_ZZHL_INDEX_SECID} stitched with {mod.CN_ZZHL_PRE_INDEX_CODE} before {zzhl_start.date()}"
                    )
        except Exception as exc:
            proxy_notes.append(f"{mod.CN_ZZHL_INDEX_SECID} pre-index stitch failed: {exc}")

    close_df = pd.concat(
        [raw[secid][["close"]].rename(columns={"close": secid}) for secid in mod.CN_STOCK_CODES],
        axis=1,
    ).ffill().dropna()

    bond_df, bond_source = mod.fetch_cn_kline(mod.CN_BOND_CODE)
    bond_df = mod._drop_cn_unconfirmed_today(bond_df)
    first_last[mod.CN_BOND_CODE] = {
        "name": mod.CN_NAMES.get(mod.CN_BOND_CODE, mod.CN_BOND_CODE),
        "first": str(pd.Timestamp(bond_df.index.min()).date()),
        "last": str(pd.Timestamp(bond_df.index.max()).date()),
        "rows": int(len(bond_df)),
        "source": bond_source,
    }
    sources[mod.CN_BOND_CODE] = bond_source
    close_df[mod.CN_BOND_CODE] = bond_df["close"].reindex(close_df.index)
    close_df = close_df.ffill().dropna()

    raw_common_start = max(pd.Timestamp(item["first"]) for item in first_last.values())
    meta = {
        "first_last": first_last,
        "sources": sources,
        "proxy_notes": proxy_notes,
        "close_start": str(pd.Timestamp(close_df.index.min()).date()),
        "close_end": str(pd.Timestamp(close_df.index.max()).date()),
        "close_rows": int(len(close_df)),
        "raw_common_start_by_data_first_dates": str(raw_common_start.date()),
        "formal_start": str(FORMAL_START.date()),
    }
    return close_df, meta


def load_volume_inputs(mod: object, expected_date: pd.Timestamp) -> tuple[Any, Any, dict[str, Any]]:
    meta: dict[str, Any] = {"enabled": bool(mod.CN_SA_VOLUME_OVERLAY_ENABLED)}
    if not mod.CN_SA_VOLUME_OVERLAY_ENABLED:
        return None, None, meta
    signal, feature = mod._load_suba_volume_signal()
    feature = mod._annotate_rule_freshness(
        feature,
        expected_date=expected_date,
        rule_key="suba_volume",
    )
    unresolved = bool(mod._suba_volume_feature_has_unresolved(feature))
    meta.update(
        {
            "rule_name": mod.CN_SA_VOLUME_RULE_NAME,
            "unresolved": unresolved,
            "feature_start": str(pd.Timestamp(feature.index.min()).date()) if len(feature) else None,
            "feature_end": str(pd.Timestamp(feature.index.max()).date()) if len(feature) else None,
            "feature_rows": int(len(feature)),
        }
    )
    if unresolved:
        raise RuntimeError("Sub-A volume overlay has unresolved freshness/availability fields")
    return signal, feature, meta


def run_candidate(
    mod: object,
    close_df: pd.DataFrame,
    volume_signal: Any,
    volume_feature: Any,
    *,
    target_vol: float,
    max_lev: float,
) -> pd.DataFrame:
    original = {
        "CN_TARGET_VOL": mod.CN_TARGET_VOL,
        "CN_MAX_LEV": mod.CN_MAX_LEV,
        "CN_VOL_WINDOW": mod.CN_VOL_WINDOW,
    }
    try:
        mod.CN_TARGET_VOL = float(target_vol)
        mod.CN_MAX_LEV = float(max_lev)
        mod.CN_VOL_WINDOW = int(VOL_WINDOW)
        result = mod.run_cn_strategy(close_df, mod.CN_EQUITY_CODES)
        if mod.CN_SA_CASH_OVERLAY_ENABLED:
            result = mod.apply_suba_cash_peak_decay_overlay(
                result,
                close_df,
                decay_ratio_threshold=mod.CN_SA_CASH_OVERLAY_DECAY_RATIO,
                recovery_ratio_threshold=mod.CN_SA_CASH_OVERLAY_RECOVERY_RATIO,
                commission=mod.CN_COMMISSION,
            )
        if mod.CN_SA_SAME_SIDE_OVERHEAT_ENABLED:
            result = mod.apply_suba_same_side_overheat_overlay(
                result,
                close_df,
                enter_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_ENTER,
                exit_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_EXIT,
                derisk_scale=mod.CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE,
            )
        if mod.CN_SA_VOLUME_OVERLAY_ENABLED:
            result = mod._apply_suba_volume_overlay_policy(
                result,
                close_df,
                volume_signal,
                volume_feature,
                allow_unresolved_suba_volume=False,
            )
        return result
    finally:
        for key, value in original.items():
            setattr(mod, key, value)


def summarize_segment(df: pd.DataFrame, segment: str, start: pd.Timestamp, candidate: dict[str, Any]) -> dict[str, Any]:
    sub = df.loc[df.index >= start].copy()
    ret = pd.to_numeric(sub["return"], errors="coerce").dropna()
    sub = sub.loc[ret.index]
    nav = (1.0 + ret).cumprod()
    rows = int(len(ret))
    ann_return = float(nav.iloc[-1] ** (244 / rows) - 1.0) if rows > 0 else np.nan
    ann_vol = float(ret.std(ddof=1) * math.sqrt(244)) if rows > 1 else np.nan
    sharpe = float(ret.mean() / ret.std(ddof=1) * math.sqrt(244)) if rows > 1 and ret.std(ddof=1) > 0 else np.nan
    dd = nav / nav.cummax() - 1.0
    weight = pd.to_numeric(sub.get("weight", pd.Series(index=sub.index, dtype=float)), errors="coerce")
    base_weight = pd.to_numeric(sub.get("base_weight", pd.Series(index=sub.index, dtype=float)), errors="coerce")
    scale_raw = pd.to_numeric(sub.get("scale_raw", pd.Series(index=sub.index, dtype=float)), errors="coerce")
    held = base_weight > 1e-12
    cap_hit_ratio = float((held & (scale_raw >= float(candidate["CN_MAX_LEV"]) - 1e-9)).sum() / held.sum()) if held.sum() else 0.0
    return {
        **candidate,
        "segment": segment,
        "start": str(ret.index.min().date()),
        "end": str(ret.index.max().date()),
        "rows": rows,
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "sharpe_repo": sharpe,
        "max_dd": float(dd.min()) if len(dd) else np.nan,
        "final_nav": float(nav.iloc[-1]) if len(nav) else np.nan,
        "avg_weight": float(weight.abs().mean()) if len(weight) else np.nan,
        "held_day_avg_weight": float(weight.loc[held].abs().mean()) if held.any() else np.nan,
        "holding_day_ratio": float(held.mean()) if len(held) else np.nan,
        "avg_scale_raw_held": float(scale_raw.loc[held].mean()) if held.any() else np.nan,
        "cap_hit_ratio_held": cap_hit_ratio,
        "avg_turnover": float(pd.to_numeric(sub.get("effective_turnover", 0.0), errors="coerce").fillna(0.0).mean()),
        "turnover_sum": float(pd.to_numeric(sub.get("effective_turnover", 0.0), errors="coerce").fillna(0.0).sum()),
        "cost_total": float(pd.to_numeric(sub.get("trade_cost", 0.0), errors="coerce").fillna(0.0).sum()),
    }


def latest_state(df: pd.DataFrame) -> dict[str, Any]:
    last = df.iloc[-1]
    return {
        "date": str(pd.Timestamp(df.index[-1]).date()),
        "holding": str(last.get("holding", "")),
        "effective_holding": str(last.get("effective_holding", last.get("holding", ""))),
        "base_weight": float(last.get("base_weight", np.nan)),
        "weight": float(last.get("weight", np.nan)),
        "scale_raw": float(last.get("scale_raw", np.nan)) if pd.notna(last.get("scale_raw", np.nan)) else None,
        "realized_vol": float(last.get("realized_vol", np.nan)) if pd.notna(last.get("realized_vol", np.nan)) else None,
        "volume_rule_on": bool(last.get("suba_volume_rule_on", False)) if "suba_volume_rule_on" in df.columns else None,
        "overheat_on": bool(last.get("suba_same_side_overheat_on", False)) if "suba_same_side_overheat_on" in df.columns else None,
    }


def build_window_metrics(scan_summary: pd.DataFrame) -> pd.DataFrame:
    wide_rows = []
    param_cols = ["candidate", "CN_TARGET_VOL", "CN_MAX_LEV", "CN_VOL_WINDOW"]
    for candidate, group in scan_summary.groupby("candidate", sort=False):
        base = {col: group.iloc[0][col] for col in param_cols}
        for _, row in group.iterrows():
            seg = row["segment"]
            for metric in [
                "ann_return",
                "ann_vol",
                "sharpe_repo",
                "max_dd",
                "final_nav",
                "avg_weight",
                "held_day_avg_weight",
                "holding_day_ratio",
                "avg_scale_raw_held",
                "cap_hit_ratio_held",
                "turnover_sum",
                "cost_total",
            ]:
                base[f"{metric}_{seg}"] = row[metric]
        wide_rows.append(base)
    return pd.DataFrame(wide_rows)


def main() -> None:
    started = pd.Timestamp.now(tz="Asia/Shanghai")
    mod = load_mnt_module()
    close_df, data_meta = build_cn_close(mod)
    volume_signal, volume_feature, volume_meta = load_volume_inputs(mod, close_df.index.max())

    summary_rows: list[dict[str, Any]] = []
    latest_rows: list[dict[str, Any]] = []
    for target_vol in TARGET_VOLS:
        for max_lev in MAX_LEVS:
            candidate = {
                "candidate": f"tv{int(target_vol * 100):02d}_lev{str(max_lev).replace('.', 'p')}",
                "CN_TARGET_VOL": float(target_vol),
                "CN_MAX_LEV": float(max_lev),
                "CN_VOL_WINDOW": int(VOL_WINDOW),
            }
            result = run_candidate(
                mod,
                close_df,
                volume_signal,
                volume_feature,
                target_vol=target_vol,
                max_lev=max_lev,
            )
            for segment, start in WINDOWS.items():
                summary_rows.append(summarize_segment(result, segment, start, candidate))
            latest_rows.append({**candidate, **latest_state(result)})

    scan_summary = pd.DataFrame(summary_rows)
    window_metrics = build_window_metrics(scan_summary)
    latest_df = pd.DataFrame(latest_rows)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    latest_df.to_csv(RUN_DIR / "latest_state.csv", index=False, encoding="utf-8-sig")

    default = window_metrics[
        (window_metrics["CN_TARGET_VOL"].round(10) == 0.30)
        & (window_metrics["CN_MAX_LEV"].round(10) == 1.5)
    ].iloc[0]
    best_10y = window_metrics.sort_values(
        ["sharpe_repo_last_10y", "max_dd_last_10y", "ann_return_last_10y"],
        ascending=[False, False, False],
    ).iloc[0]
    best_full = window_metrics.sort_values(
        ["sharpe_repo_full", "max_dd_full", "ann_return_full"],
        ascending=[False, False, False],
    ).iloc[0]

    meta_path = RUN_DIR / "scan_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except Exception:
        meta = {}
    meta.update(
        {
            "run_id": RUN_DIR.name,
            "phase": "scan_complete_unfinalized",
            "project": "a_us_momentum_combo",
            "strategy": "V7.7",
            "subsystem": "Sub-A",
            "repo_root": str(ROOT),
            "entrypoint": str(MNT_SCRIPT),
            "git_branch": _git(["branch", "--show-current"]),
            "git_commit": _git(["rev-parse", "HEAD"]),
            "git_status_after_scan": _git(["status", "--short"]),
            "scan_type": "runtime_override_grid",
            "parameter_group": "CN_TARGET_VOL x CN_MAX_LEV",
            "baseline": {"CN_TARGET_VOL": 0.30, "CN_MAX_LEV": 1.5, "CN_VOL_WINDOW": VOL_WINDOW},
            "candidate_grid": [
                {"CN_TARGET_VOL": tv, "CN_MAX_LEV": lev, "CN_VOL_WINDOW": VOL_WINDOW}
                for tv in TARGET_VOLS
                for lev in MAX_LEVS
            ],
            "data_snapshot": data_meta,
            "volume_overlay": volume_meta,
            "cost_model": {
                "commission_one_way": float(mod.CN_COMMISSION),
                "cash_annual": float(mod.CN_RF_ANNUAL),
                "slippage": "not separately modeled",
                "open_impact": "not modeled; production Sub-A path is close-to-close",
                "financing": "cash earns CN_RF_DAILY; no explicit leverage financing cost in Sub-A target-vol path",
            },
            "overlays": {
                "cash_peak_decay": bool(mod.CN_SA_CASH_OVERLAY_ENABLED),
                "same_side_overheat": {
                    "enabled": bool(mod.CN_SA_SAME_SIDE_OVERHEAT_ENABLED),
                    "enter": float(mod.CN_SA_SAME_SIDE_OVERHEAT_ENTER),
                    "exit": float(mod.CN_SA_SAME_SIDE_OVERHEAT_EXIT),
                    "derisk_scale": float(mod.CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE),
                },
                "volume": volume_meta,
            },
            "outputs": {
                "record": str(RUN_DIR / "record.md"),
                "scan_summary": str(RUN_DIR / "scan_summary.csv"),
                "window_metrics": str(RUN_DIR / "window_metrics.csv"),
                "scan_meta": str(RUN_DIR / "scan_meta.json"),
                "command_log": str(RUN_DIR / "command_log.txt"),
                "latest_state": str(RUN_DIR / "latest_state.csv"),
            },
            "quick_read": {
                "default_full": default.to_dict(),
                "best_10y_by_sharpe": best_10y.to_dict(),
                "best_full_by_sharpe": best_full.to_dict(),
            },
            "scan_completed_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        }
    )
    _write_json(meta_path, meta)

    top = window_metrics.sort_values(
        ["sharpe_repo_last_10y", "max_dd_last_10y", "ann_return_last_10y"],
        ascending=[False, False, False],
    ).head(8)
    record = [
        "# V7.7 Sub-A Target Vol And Max Leverage Scan",
        "",
        "## Run Metadata",
        f"- Run id: {RUN_DIR.name}",
        f"- Run date: {started.isoformat()}",
        "- Timezone: Asia/Shanghai",
        f"- Repo: `{ROOT}`",
        "- Strategy: V7.7 Sub-A",
        "- Parameter group: `CN_TARGET_VOL x CN_MAX_LEV`, with `CN_VOL_WINDOW=80` fixed",
        f"- Git commit: `{_git(['rev-parse', 'HEAD'])}`",
        "",
        "## Research Question",
        "- Re-check whether the current 30% target vol and 1.5x cap are still justified.",
        "- Candidate grid: target vol 15/20/25/30/35%, max leverage 1.0/1.2/1.5x.",
        "- Source-change rule: research output only; do not change production constants from this scan alone.",
        "",
        "## Implementation Anchor",
        "- Official entrypoint: `mnt_bot V 7.7 plus.py`.",
        "- Reused: `fetch_cn_kline`, `run_cn_strategy`, `apply_suba_same_side_overheat_overlay`, `_load_suba_volume_signal`, `_apply_suba_volume_overlay_policy`.",
        "- Runtime override only: `CN_TARGET_VOL`, `CN_MAX_LEV`, `CN_VOL_WINDOW`.",
        "",
        "## Data Snapshot",
        f"- Close data: {data_meta['close_start']} to {data_meta['close_end']}, rows {data_meta['close_rows']}.",
        f"- Formal full-sample start: {FORMAL_START.date()}.",
        f"- Volume overlay: enabled={volume_meta.get('enabled')}, unresolved={volume_meta.get('unresolved')}, feature_end={volume_meta.get('feature_end')}.",
        f"- Proxy notes: {'; '.join(data_meta['proxy_notes']) if data_meta['proxy_notes'] else 'none'}",
        "",
        "## Cost and Execution Assumptions",
        f"- Commission: one-way `{mod.CN_COMMISSION}`.",
        "- Slippage/open-impact: not separately modeled; this uses the existing close-to-close Sub-A research path.",
        "- Financing: cash yield is included; no explicit leverage financing charge is deducted.",
        "- Overlays: same-side overheat and amount/volume overlay are included according to current V7.7 defaults.",
        "",
        "## Runtime Override Plan",
        "- Override mechanism: module constants are set per candidate and restored after each run.",
        "- Default candidate included in same run: yes, `tv30_lev1p5`.",
        "- Parity check: default candidate is generated by the same official functions used by the scan.",
        "",
        "## Commands",
        "```powershell",
        "python quant_param_scan_runs\\20260529_a_us_momentum_combo_v7_7_sub_a_target_vol_max_leverage\\run_scan.py",
        "```",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `latest_state.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        window_metrics.sort_values(["sharpe_repo_full", "max_dd_full"], ascending=[False, False])
        .head(8)[
            [
                "candidate",
                "CN_TARGET_VOL",
                "CN_MAX_LEV",
                "ann_return_full",
                "ann_vol_full",
                "sharpe_repo_full",
                "max_dd_full",
                "avg_weight_full",
                "cap_hit_ratio_held_full",
            ]
        ]
        .to_markdown(index=False),
        "",
        "## Window Results",
        top[
            [
                "candidate",
                "ann_return_last_10y",
                "max_dd_last_10y",
                "ann_return_last_5y",
                "max_dd_last_5y",
                "ann_return_last_3y",
                "max_dd_last_3y",
                "ann_return_last_1y",
                "max_dd_last_1y",
            ]
        ].to_markdown(index=False),
        "",
        "## Stability Classification",
        "- Label: pending final decision after reviewing window tradeoffs.",
        "- Leverage caveat: cap-hit ratio is reported because the nominal target-vol setting can be dominated by the leverage cap.",
        "",
        "## Decision",
        "- Decision: pending finalization.",
        "",
        "## User-Facing Summary",
        "- See `window_metrics.csv` and `scan_summary.csv`; final decision will be added after review.",
        "",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record), encoding="utf-8")
    with (RUN_DIR / "command_log.txt").open("a", encoding="utf-8") as fh:
        fh.write(f"\n{pd.Timestamp.now(tz='Asia/Shanghai').isoformat()} python {RUN_DIR / 'run_scan.py'}\n")


if __name__ == "__main__":
    main()

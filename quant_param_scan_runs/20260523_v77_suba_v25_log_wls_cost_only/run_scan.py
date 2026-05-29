from __future__ import annotations

import builtins
import importlib.util
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = Path(__file__).resolve().parent
MNT_SCRIPT = ROOT / "mnt_bot V 7.7 plus.py"
FORMAL_START = pd.Timestamp("2014-10-17")
LOOKBACK_GRID = list(range(4, 41))
HALFLIFE_GRID = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0]
THRESHOLD_GRID = [0.0, 0.40]
MICROCAP_ROOT = Path(
    "C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/"
    "\u52a8\u91cf\u7b56\u7565/\u5fae\u76d8\u80a1\u5bf9\u51b2\u7b56\u7565"
)
MICROCAP_V25_SCRIPT = MICROCAP_ROOT / "microcap_top100_mom16_biweekly_live_v2_5.py"


class _PoeStub:
    query = None
    default_chat = []

    class BotError(Exception):
        pass

    def update_settings(self, settings: object) -> None:
        self.settings = settings


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
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
        spec = importlib.util.spec_from_file_location("mnt_bot_v77_suba_v25_cost_only", str(MNT_SCRIPT))
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


def load_microcap_v25_module() -> object:
    sys.path.insert(0, str(MICROCAP_ROOT))
    spec = importlib.util.spec_from_file_location("microcap_v25_for_suba", str(MICROCAP_V25_SCRIPT))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {MICROCAP_V25_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_cn_close(mod: object) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw: dict[str, pd.DataFrame] = {}
    sources: dict[str, str] = {}
    raw_first_last: dict[str, dict[str, str]] = {}
    proxy_notes: list[str] = []

    for secid in mod.CN_STOCK_CODES:
        df, source = mod.fetch_cn_kline(secid)
        raw[secid] = df.copy()
        sources[secid] = source
        raw_first_last[secid] = {
            "first": str(pd.Timestamp(df.index.min()).date()),
            "last": str(pd.Timestamp(df.index.max()).date()),
        }

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
    raw_first_last[mod.CN_BOND_CODE] = {
        "first": str(pd.Timestamp(bond_df.index.min()).date()),
        "last": str(pd.Timestamp(bond_df.index.max()).date()),
    }
    sources[mod.CN_BOND_CODE] = bond_source
    close_df[mod.CN_BOND_CODE] = bond_df["close"].reindex(close_df.index)
    close_df = close_df.ffill().dropna()

    raw_common_start = max(pd.Timestamp(v["first"]) for v in raw_first_last.values())
    meta = {
        "sources": sources,
        "raw_first_last": raw_first_last,
        "proxy_notes": proxy_notes,
        "stitched_close_start": str(pd.Timestamp(close_df.index.min()).date()),
        "stitched_close_end": str(pd.Timestamp(close_df.index.max()).date()),
        "stitched_close_rows": int(len(close_df)),
        "raw_common_start_by_data_first_dates": str(raw_common_start.date()),
    }
    return close_df, meta


def score_bias_momentum(mod: object, close_df: pd.DataFrame, codes: list[str]) -> dict[str, pd.Series]:
    return {code: mod.calc_bias_momentum(close_df[code]) for code in codes}


def score_v25_log_wls(
    v25: object,
    close_df: pd.DataFrame,
    codes: list[str],
    *,
    lookback: int,
    halflife: float,
) -> dict[str, pd.Series]:
    scores: dict[str, pd.Series] = {}
    for code in codes:
        frame = v25.log_wls_score_and_r2(close_df[code], lookback=lookback, halflife=halflife)
        scores[code] = pd.to_numeric(frame["annualized_log_wls_score"], errors="coerce")
    return scores


def run_cost_only_rotation(
    close_df: pd.DataFrame,
    scores: dict[str, pd.Series],
    codes: list[str],
    *,
    threshold: float,
    commission: float,
    strategy: str,
    lookback: int | None = None,
    halflife: float | None = None,
) -> pd.DataFrame:
    current = "cash"
    rows: list[dict[str, Any]] = []

    for i in range(1, len(close_df)):
        dt = close_df.index[i]
        prev_dt = close_df.index[i - 1]
        if current == "cash":
            gross_ret = 0.0
        else:
            gross_ret = float(close_df.loc[dt, current] / close_df.loc[prev_dt, current] - 1.0)

        day_scores: dict[str, float] = {}
        for code in codes:
            value = scores[code].loc[dt]
            if pd.notna(value) and math.isfinite(float(value)):
                day_scores[code] = float(value)

        best_code = "cash"
        best_score = np.nan
        if day_scores:
            best_code = max(day_scores, key=day_scores.get)
            best_score = float(day_scores[best_code])
        next_holding = best_code if pd.notna(best_score) and best_score > threshold else "cash"

        old_weight = 0.0 if current == "cash" else 1.0
        new_weight = 0.0 if next_holding == "cash" else 1.0
        turnover = abs(new_weight - old_weight) if current == next_holding else old_weight + new_weight
        trade_cost = float(commission) * float(turnover)
        net_ret = (1.0 + gross_ret) * (1.0 - trade_cost) - 1.0

        rows.append(
            {
                "date": dt,
                "strategy": strategy,
                "lookback": lookback,
                "halflife": halflife,
                "holding": current,
                "next_holding": next_holding,
                "best_asset": best_code,
                "best_score": best_score,
                "threshold": threshold,
                "return_gross": gross_ret,
                "turnover": turnover,
                "trade_cost": trade_cost,
                "return": net_ret,
            }
        )
        current = next_holding

    out = pd.DataFrame(rows).set_index("date")
    first_valid = pd.concat([s.rename(k) for k, s in scores.items()], axis=1).dropna(how="all").index.min()
    out = out[out.index >= first_valid].copy()
    out["nav"] = (1.0 + out["return"].fillna(0.0)).cumprod()
    return out


def _metrics(ret: pd.Series, turnover: pd.Series | None = None, holding: pd.Series | None = None) -> dict[str, Any]:
    r = pd.to_numeric(ret, errors="coerce").fillna(0.0).astype(float)
    rows = int(len(r))
    if rows <= 0:
        return {"rows": 0}
    nav = (1.0 + r).cumprod()
    final_nav = float(nav.iloc[-1])
    ann_return = final_nav ** (244.0 / rows) - 1.0 if final_nav > 0 else np.nan
    ann_vol = float(r.std(ddof=1) * math.sqrt(244.0)) if rows > 1 else 0.0
    sharpe = ann_return / ann_vol if ann_vol and math.isfinite(ann_vol) else np.nan
    dd = nav / nav.cummax() - 1.0
    active = holding.astype(str).ne("cash") if holding is not None else pd.Series(False, index=r.index)
    return {
        "rows": rows,
        "start": str(pd.Timestamp(r.index.min()).date()),
        "end": str(pd.Timestamp(r.index.max()).date()),
        "ann_return": float(ann_return),
        "ann_vol": float(ann_vol),
        "sharpe_repo": float(sharpe),
        "max_dd": float(dd.min()),
        "final_nav": final_nav,
        "holding_day_ratio": float(active.mean()) if len(active) else np.nan,
        "trade_days": int((pd.to_numeric(turnover, errors="coerce").fillna(0.0) > 1e-12).sum()) if turnover is not None else 0,
        "turnover_sum": float(pd.to_numeric(turnover, errors="coerce").fillna(0.0).sum()) if turnover is not None else 0.0,
    }


def _window_ranges(index: pd.DatetimeIndex) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    end = pd.Timestamp(index.max())
    first = pd.Timestamp(index.min())
    windows = {"full": (max(first, FORMAL_START), end), "full_proxy": (first, end)}
    for years in (10, 5, 3, 1):
        windows[f"last_{years}y"] = (max(first, end - pd.DateOffset(years=years)), end)
    return windows


def build_tables(results: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    common_index = None
    for df in results.values():
        idx = pd.DatetimeIndex(df.index)
        common_index = idx if common_index is None else common_index.intersection(idx)
    if common_index is None or len(common_index) == 0:
        raise RuntimeError("no common result index")
    common_index = pd.DatetimeIndex(common_index).sort_values()

    rows: list[dict[str, Any]] = []
    wide_rows: list[dict[str, Any]] = []
    for name, df in results.items():
        aligned = df.reindex(common_index).copy()
        first = aligned.iloc[0]
        wide: dict[str, Any] = {
            "candidate": name,
            "strategy": name,
            "lookback": first.get("lookback"),
            "halflife": first.get("halflife"),
            "threshold": first.get("threshold"),
        }
        for segment, (start, end) in _window_ranges(common_index).items():
            part = aligned[(aligned.index >= start) & (aligned.index <= end)]
            m = _metrics(part["return"], part["turnover"], part["holding"])
            row = {
                "candidate": name,
                "strategy": name,
                "lookback": first.get("lookback"),
                "halflife": first.get("halflife"),
                "threshold": first.get("threshold"),
                "segment": segment,
                **m,
            }
            rows.append(row)
            for metric in ("ann_return", "ann_vol", "sharpe_repo", "max_dd", "final_nav", "holding_day_ratio", "trade_days", "turnover_sum"):
                wide[f"{metric}_{segment}"] = row.get(metric)
        wide_rows.append(wide)
    return pd.DataFrame(rows), pd.DataFrame(wide_rows)


def write_record(summary: pd.DataFrame, meta: dict[str, Any]) -> None:
    formal = summary[summary["segment"] == "full"].copy()
    v25_formal = formal[formal["strategy"].str.startswith("v25_lb")].copy()
    top_formal = v25_formal.sort_values(["sharpe_repo", "ann_return"], ascending=False).head(10)
    top_10y = (
        summary[(summary["segment"] == "last_10y") & (summary["strategy"].str.startswith("v25_lb"))]
        .copy()
        .sort_values(["sharpe_repo", "ann_return"], ascending=False)
        .head(10)
    )
    lines = [
        "# V7.7 Sub-A With Microcap v2.5 Log-WLS Momentum, Cost Only",
        "",
        "## Decision",
        "",
        "Do not replace the A-strategy original momentum with this v2.5 log-WLS family yet. The best scan rows improve drawdown, but the original Sub-A cost-only baseline still has the cleaner 5Y/3Y/1Y return and Sharpe profile.",
        "",
        "## Stability",
        "",
        "Research lead only. Best rows cluster around LB 20-28 and HL 8-12, so the grid has a platform, but recent-window underperformance keeps it below promotion quality.",
        "",
        "## Scope",
        "",
        "- A-share pool: V7.7 Sub-A current 5 equity total-return indexes plus 10Y treasury total-return index.",
        "- Baseline: V7.7 Sub-A original `price / MA60` weighted slope momentum, cost only.",
        "- Test signal: microcap v2.5 `annualized_log_wls_score` applied to each Sub-A asset close series.",
        f"- Grid: lookback `{min(LOOKBACK_GRID)}..{max(LOOKBACK_GRID)}`, halflife `{HALFLIFE_GRID}`, threshold `{THRESHOLD_GRID}`.",
        "- Removed: R2, absolute momentum, target-vol, same-side overheat, volume overlay, cash peak-decay, staged entry, and cash yield.",
        "- Retained: V7.7 `CN_COMMISSION=0.001` one-way turnover cost.",
        "",
        "## Data",
        "",
        f"- Close data: {meta['data']['stitched_close_start']} to {meta['data']['stitched_close_end']}, rows {meta['data']['stitched_close_rows']}.",
        f"- Raw common start by first available local series: {meta['data']['raw_common_start_by_data_first_dates']}.",
        f"- Formal full-sample floor: {meta['formal_start']} ({meta['formal_start_reason']}).",
    ]
    for note in meta["data"].get("proxy_notes", []):
        lines.append(f"- Proxy note: {note}. Treat pre-publication/proxy window as research, not formal evidence.")

    lines.extend(["", "## Results", ""])
    for segment in ("full", "full_proxy", "last_10y", "last_5y", "last_3y", "last_1y"):
        lines.append(f"### {segment}")
        sub = summary[summary["segment"] == segment].copy()
        baseline = sub[sub["strategy"] == "suba_original_bias60_20_cost_only"]
        top = sub[sub["strategy"].str.startswith("v25_lb")].sort_values(["sharpe_repo", "ann_return"], ascending=False).head(5)
        sub = pd.concat([baseline, top], ignore_index=True)
        for _, row in sub.iterrows():
            lines.append(
                f"- `{row['strategy']}`: annual {row['ann_return']:.2%}, maxDD {row['max_dd']:.2%}, "
                f"Sharpe {row['sharpe_repo']:.2f}, holding {row['holding_day_ratio']:.1%}, trades {int(row['trade_days'])}"
            )
        lines.append("")

    lines.extend(["## Top Formal Candidates", ""])
    for _, row in top_formal.iterrows():
        lines.append(
            f"- `{row['strategy']}`: annual {row['ann_return']:.2%}, maxDD {row['max_dd']:.2%}, "
            f"Sharpe {row['sharpe_repo']:.2f}, LB {int(float(row['lookback']))}, HL {float(row['halflife']):.1f}, threshold {float(row['threshold']):.2f}"
        )
    lines.extend(["", "## Top 10Y Candidates", ""])
    for _, row in top_10y.iterrows():
        lines.append(
            f"- `{row['strategy']}`: annual {row['ann_return']:.2%}, maxDD {row['max_dd']:.2%}, "
            f"Sharpe {row['sharpe_repo']:.2f}, LB {int(float(row['lookback']))}, HL {float(row['halflife']):.1f}, threshold {float(row['threshold']):.2f}"
        )

    lines.extend(
        [
            "## Outputs",
            "",
            "- `daily_*.csv`",
            "- `scan_summary.csv`",
            "- `window_metrics.csv`",
            "- `scan_meta.json`",
        ]
    )
    (RUN_DIR / "record.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    started = time.time()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    command = "python quant_param_scan_runs/20260523_v77_suba_v25_log_wls_cost_only/run_scan.py"
    (RUN_DIR / "command_log.txt").write_text(f"{pd.Timestamp.now().isoformat()} {command}\n", encoding="utf-8")

    mnt = load_mnt_module()
    v25 = load_microcap_v25_module()
    close_df, data_meta = build_cn_close(mnt)
    codes = [code for code in list(mnt.CN_EQUITY_CODES) + [mnt.CN_BOND_CODE] if code in close_df.columns]

    bias_scores = score_bias_momentum(mnt, close_df, codes)

    results = {
        "suba_original_bias60_20_cost_only": run_cost_only_rotation(
            close_df,
            bias_scores,
            codes,
            threshold=0.0,
            commission=mnt.CN_COMMISSION,
            strategy="suba_original_bias60_20_cost_only",
        ),
    }
    for lookback in LOOKBACK_GRID:
        for halflife in HALFLIFE_GRID:
            v25_scores = score_v25_log_wls(v25, close_df, codes, lookback=lookback, halflife=halflife)
            for threshold in THRESHOLD_GRID:
                th_label = str(threshold).replace(".", "p")
                name = f"v25_lb{lookback:02d}_hl{halflife:g}_th{th_label}_cost_only".replace(".", "p")
                results[name] = run_cost_only_rotation(
                    close_df,
                    v25_scores,
                    codes,
                    threshold=float(threshold),
                    commission=mnt.CN_COMMISSION,
                    strategy=name,
                    lookback=int(lookback),
                    halflife=float(halflife),
                )

    for name, df in results.items():
        if name == "suba_original_bias60_20_cost_only" or name in {
            "v25_lb17_hl3_th0p0_cost_only",
            "v25_lb17_hl3_th0p4_cost_only",
        }:
            df.rename_axis("date").reset_index().to_csv(RUN_DIR / f"daily_{name}.csv", index=False, encoding="utf-8")

    summary, wide = build_tables(results)
    summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8")
    wide.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8")

    gross_ok = {}
    for name, df in results.items():
        gross_nav = float((1.0 + df["return_gross"].fillna(0.0)).cumprod().iloc[-1])
        net_nav = float(df["nav"].iloc[-1])
        gross_ok[name] = {
            "gross_final_nav": gross_nav,
            "net_final_nav": net_nav,
            "net_lte_gross": bool(net_nav <= gross_nav + 1e-12),
        }

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": pd.Timestamp.now().isoformat(),
        "phase": "analysis_written",
        "project": "A-share US momentum combo",
        "strategy": "V7.7 Sub-A",
        "subsystem": "Sub-A signal replacement cost-only",
        "scan_type": "grid",
        "parameter_group": "microcap v2.5 log-WLS lookback and halflife",
        "repo_root": str(ROOT),
        "entrypoint": str(Path(__file__).resolve()),
        "source_files": [str(MNT_SCRIPT), str(MICROCAP_V25_SCRIPT)],
        "git_branch": _git(["branch", "--show-current"]),
        "git_commit": _git(["rev-parse", "HEAD"]),
        "git_status": _git(["status", "--short"]),
        "git_status_before": _git(["status", "--short"]),
        "git_status_after": _git(["status", "--short"]),
        "data": data_meta,
        "data_snapshot": data_meta,
        "formal_start": str(FORMAL_START.date()),
        "formal_start_reason": "workspace rule: replacement-signal test uses full current Sub-A pool including ZZ1000; formal conclusions start no earlier than ZZ1000 publication date",
        "asset_pool": {code: mnt.CN_NAMES.get(code, code) for code in codes},
        "microcap_v25_params": {
            "default_LOOKBACK": int(v25.LOOKBACK),
            "default_HALFLIFE": float(v25.HALFLIFE),
            "default_ENTRY_THRESHOLD": float(v25.ENTRY_THRESHOLD),
            "default_EXIT_THRESHOLD": float(v25.EXIT_THRESHOLD),
            "TRADING_DAYS": int(v25.TRADING_DAYS),
        },
        "scan_grid": {
            "lookback": LOOKBACK_GRID,
            "halflife": HALFLIFE_GRID,
            "threshold": THRESHOLD_GRID,
            "candidate_count": int(len(results)),
        },
        "candidate_grid": {
            "lookback": LOOKBACK_GRID,
            "halflife": HALFLIFE_GRID,
            "threshold": THRESHOLD_GRID,
        },
        "baseline": "suba_original_bias60_20_cost_only",
        "decision": "do_not_replace_original_momentum_yet",
        "stability_label": "research_lead_not_promoted",
        "cost_model": {
            "commission": float(mnt.CN_COMMISSION),
            "timing": "close-to-close return for current holding; close signal changes next holding; same-row turnover cost charged after daily return",
            "cash_yield": 0.0,
            "slippage_or_open_impact": "not modeled",
        },
        "removed_conditions": [
            "R2 gate",
            "absolute momentum gate",
            "target volatility scaling",
            "same-side overheat overlay",
            "Sub-A volume overlay",
            "cash peak-decay overlay",
            "staged entry / wait-for-down-day",
            "cash yield",
        ],
        "verification": {
            "costed_nav_not_above_gross_nav": gross_ok,
            "result_common_start": str(pd.Timestamp(summary["start"].min()).date()),
            "result_common_end": str(pd.Timestamp(summary["end"].max()).date()),
        },
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
        },
        "elapsed_sec": round(time.time() - started, 3),
    }
    _write_json(RUN_DIR / "scan_meta.json", meta)
    write_record(summary, meta)


if __name__ == "__main__":
    main()

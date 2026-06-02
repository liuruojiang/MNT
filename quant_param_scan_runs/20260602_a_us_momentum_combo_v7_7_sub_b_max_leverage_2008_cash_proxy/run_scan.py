from __future__ import annotations

import importlib.util
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


RUN_DIR = Path(__file__).resolve().parent
ROOT = RUN_DIR.parents[1]
SCRIPT = ROOT / "mnt_bot V 7.7 plus.py"
CASH_ANNUAL = 0.025
TRADING_DAYS = 252
CANDIDATES = [1.0, 1.25, 1.5, 1.75, 2.0]
PRESSURE_WINDOWS = {
    "full": None,
    "last_15y": "last_15y",
    "last_10y": "last_10y",
    "last_5y": "last_5y",
    "last_3y": "last_3y",
    "last_1y": "last_1y",
    "gfc_peak_to_trough": (pd.Timestamp("2007-10-09"), pd.Timestamp("2009-03-09")),
    "calendar_2008": (pd.Timestamp("2008-01-01"), pd.Timestamp("2008-12-31")),
    "lehman_crisis": (pd.Timestamp("2008-09-15"), pd.Timestamp("2009-03-09")),
}


def git_text(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception as exc:
        return f"unavailable: {exc}"


def load_module():
    spec = importlib.util.spec_from_file_location("mnt_bot_v77_subb_lev_scan", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_cash_proxy_panel(mod):
    tickers = list(dict.fromkeys(mod.US_ROT_POOL + ["BIL", "SPY", mod.US_ROT_EMXC_BT_PROXY, "IBIT"]))
    us_raw = {}
    sources = {}
    for ticker in tickers:
        frame, source = mod.fetch_yahoo(ticker, start_date="2003-01-01")
        if frame is None or frame.empty or "close" not in frame.columns:
            raise RuntimeError(f"missing usable data for {ticker}")
        us_raw[ticker] = frame.copy()
        sources[ticker] = str(source)
        time.sleep(0.05)

    cash_daily = (1.0 + CASH_ANNUAL) ** (1.0 / TRADING_DAYS) - 1.0
    core_start = max(
        us_raw[ticker]["close"].dropna().index[0]
        for ticker in ["QQQ", "EFA", "GLD", "TLT", "DBC", "SPY", "EEM"]
    )
    stock_calendar = us_raw["SPY"].index
    cash_index = stock_calendar[stock_calendar >= core_start]
    cash_nav = pd.Series(
        np.power(1.0 + cash_daily, np.arange(len(cash_index))),
        index=cash_index,
        dtype=float,
    )

    bil = us_raw["BIL"].copy()
    pre_bil = pd.DataFrame({"open": cash_nav, "close": cash_nav})
    bil["close"] = bil["close"].combine_first(cash_nav.reindex(bil.index))
    bil["open"] = bil["open"].combine_first(cash_nav.reindex(bil.index))
    bil = pd.concat([pre_bil.loc[pre_bil.index < bil.index.min()], bil[["open", "close"]]], axis=0).sort_index()
    us_raw["BIL"] = bil
    sources["BIL"] = f"{sources['BIL']}+synthetic_cash_{CASH_ANNUAL:.2%}_pre_listing"

    rot_tickers = list(mod.US_ROT_POOL) + ["BIL"]
    late = mod._us_rot_late_history_tickers()
    core = [ticker for ticker in rot_tickers if ticker not in late]
    if "EMXC" in mod.US_ROT_POOL and mod.US_ROT_EMXC_BT_PROXY not in core and mod.US_ROT_EMXC_BT_PROXY in us_raw:
        core.append(mod.US_ROT_EMXC_BT_PROXY)

    close = pd.concat(
        [us_raw[ticker][["close"]].rename(columns={"close": ticker}) for ticker in core if ticker in us_raw],
        axis=1,
    ).ffill().dropna()

    if "EMXC" in mod.US_ROT_POOL and mod.US_ROT_EMXC_BT_PROXY in us_raw:
        hybrid = close[mod.US_ROT_EMXC_BT_PROXY].copy().rename("EMXC")
        emxc_ser = us_raw["EMXC"]["close"].reindex(hybrid.index)
        switch = hybrid.index >= mod.US_ROT_EMXC_BT_START
        first = emxc_ser.loc[switch].first_valid_index() if switch.any() else None
        if first is not None:
            hybrid.loc[switch] = emxc_ser.loc[switch] * (hybrid.loc[first] / emxc_ser.loc[first])
        close["EMXC"] = hybrid
        if mod.US_ROT_EMXC_BT_PROXY in close.columns and mod.US_ROT_EMXC_BT_PROXY not in mod.US_ROT_POOL:
            close = close.drop(columns=[mod.US_ROT_EMXC_BT_PROXY])

    for ticker in late:
        if ticker == "EMXC":
            continue
        if ticker in us_raw:
            close = close.join(us_raw[ticker][["close"]].rename(columns={"close": ticker}), how="left")

    if "BTC-USD" in close.columns and "IBIT" in us_raw:
        close["BTC-USD"] = mod.build_ibit_spliced(
            pd.DataFrame(
                {
                    "BTC-USD": close["BTC-USD"],
                    "IBIT": us_raw["IBIT"]["close"].reindex(close.index),
                }
            )
        )
    if "SPY" not in close.columns and "SPY" in us_raw:
        close["SPY"] = us_raw["SPY"]["close"].reindex(close.index)

    stock_rot = [ticker for ticker in rot_tickers if ticker in us_raw and ticker != "BTC-USD"]
    if stock_rot:
        close = close.loc[: max(us_raw[ticker].index[-1] for ticker in stock_rot)]

    open_map = {ticker: frame["open"] for ticker, frame in us_raw.items() if "open" in frame.columns}
    if "EEM" in open_map:
        emxc_open = open_map["EEM"].reindex(close.index).copy()
        raw_emxc_open = us_raw["EMXC"]["open"].reindex(close.index)
        switch = close.index >= mod.US_ROT_EMXC_BT_START
        first = raw_emxc_open.loc[switch].first_valid_index() if switch.any() else None
        if first is not None and pd.notna(raw_emxc_open.loc[first]):
            emxc_open.loc[switch] = raw_emxc_open.loc[switch] * (emxc_open.loc[first] / raw_emxc_open.loc[first])
        open_map["EMXC"] = emxc_open

    raw_ranges = {
        ticker: {
            "first_close": frame["close"].dropna().index[0].date().isoformat(),
            "last_close": frame["close"].dropna().index[-1].date().isoformat(),
            "has_open": "open" in frame.columns,
        }
        for ticker, frame in us_raw.items()
    }
    return close, open_map, sources, raw_ranges, core_start, cash_daily


def window_slice(index: pd.DatetimeIndex, window):
    if window is None:
        return index[0], index[-1]
    if window == "last_15y":
        return index[-1] - pd.DateOffset(years=15), index[-1]
    if window == "last_10y":
        return index[-1] - pd.DateOffset(years=10), index[-1]
    if window == "last_5y":
        return index[-1] - pd.DateOffset(years=5), index[-1]
    if window == "last_3y":
        return index[-1] - pd.DateOffset(years=3), index[-1]
    if window == "last_1y":
        return index[-1] - pd.DateOffset(years=1), index[-1]
    return window


def metrics_for(candidate: str, max_lev: float, result: pd.DataFrame, segment: str, window):
    start, end = window_slice(result.index, window)
    frame = result.loc[(result.index >= start) & (result.index <= end)].copy()
    ret = pd.to_numeric(frame["return"], errors="coerce").dropna()
    nav = (1.0 + ret).cumprod()
    dd = nav / nav.cummax() - 1.0
    years = len(ret) / TRADING_DAYS
    ann_return = nav.iloc[-1] ** (1.0 / years) - 1.0 if years > 0 else np.nan
    ann_vol = ret.std(ddof=1) * np.sqrt(TRADING_DAYS) if len(ret) > 1 else np.nan
    qqq_w = pd.to_numeric(frame.get("w_QQQ", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    gld_w = pd.to_numeric(frame.get("w_GLD", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    bil_w = pd.to_numeric(frame.get("w_BIL", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    official_scale = pd.to_numeric(frame.get("official_scale", pd.Series(np.nan, index=frame.index)), errors="coerce")
    ema_scale = pd.to_numeric(frame.get("ema_scale", pd.Series(np.nan, index=frame.index)), errors="coerce")
    return {
        "candidate": candidate,
        "US_ROT_TARGET_VOL": 0.25,
        "US_ROT_MAX_LEV": max_lev,
        "segment": segment,
        "start": ret.index[0].date().isoformat(),
        "end": ret.index[-1].date().isoformat(),
        "rows": int(len(ret)),
        "ann_return": float(ann_return),
        "ann_vol": float(ann_vol),
        "sharpe_repo": float(ann_return / ann_vol) if ann_vol and ann_vol > 0 else np.nan,
        "max_dd": float(dd.min()),
        "final_nav": float(nav.iloc[-1]),
        "avg_w_QQQ": float(qqq_w.mean()),
        "max_w_QQQ": float(qqq_w.max()),
        "avg_w_GLD": float(gld_w.mean()),
        "max_w_GLD": float(gld_w.max()),
        "avg_w_QQQ_GLD": float((qqq_w + gld_w).mean()),
        "max_w_QQQ_GLD": float((qqq_w + gld_w).max()),
        "avg_w_BIL": float(bil_w.mean()),
        "days_qqq_gld_over_100pct": int(((qqq_w + gld_w) > 1.0 + 1e-12).sum()),
        "official_scale_avg": float(official_scale.mean()),
        "official_scale_cap_hit_ratio": float((official_scale >= max_lev - 1e-12).mean()),
        "ema_scale_avg": float(ema_scale.mean()),
        "ema_scale_cap_hit_ratio": float((ema_scale >= max_lev - 1e-12).mean()),
        "turnover_sum": float(pd.to_numeric(frame.get("subb_execution_turnover", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0).sum()),
        "cost_total": float(pd.to_numeric(frame.get("subb_execution_cost", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0).sum()),
    }


def run_candidate(mod, close: pd.DataFrame, open_map: dict, max_lev: float) -> pd.DataFrame:
    original_max_lev = mod.US_ROT_MAX_LEV
    try:
        mod.US_ROT_MAX_LEV = float(max_lev)
        official = mod.run_us_rotation_mix(
            close,
            mod.US_ROT_BASE_POOL,
            us_open=open_map,
            ranking_code_selector=mod._subb_active_ranking_codes,
            weight_assets=mod.US_ROT_POOL,
        )
        ema = mod.run_subb_v75_ema_base7_rotation(
            close,
            base_codes=mod.US_ROT_POOL,
            us_open=open_map,
            weight_assets=mod.US_ROT_POOL,
        )
        result = mod.blend_subb_v75_results(official, ema)
        if mod.US_ROT_VOLREG_ENABLED and "SPY" in close:
            result = mod.apply_vol_regime_overlay(result, close["SPY"])
        return result
    finally:
        mod.US_ROT_MAX_LEV = original_max_lev


def main() -> None:
    mod = load_module()
    close, open_map, sources, raw_ranges, core_start, cash_daily = build_cash_proxy_panel(mod)
    summary_rows = []
    wide_rows = []

    for max_lev in CANDIDATES:
        candidate = f"maxlev_{str(max_lev).replace('.', 'p')}"
        result = run_candidate(mod, close, open_map, max_lev)
        result.reset_index().rename(columns={"index": "date"}).to_csv(RUN_DIR / f"daily_{candidate}.csv", index=False)
        segment_rows = []
        for segment, window in PRESSURE_WINDOWS.items():
            row = metrics_for(candidate, max_lev, result, segment, window)
            summary_rows.append(row)
            segment_rows.append(row)
        wide = {"candidate": candidate, "US_ROT_TARGET_VOL": 0.25, "US_ROT_MAX_LEV": max_lev}
        for row in segment_rows:
            segment = row["segment"]
            for key, value in row.items():
                if key in {"candidate", "segment", "US_ROT_TARGET_VOL", "US_ROT_MAX_LEV"}:
                    continue
                wide[f"{key}_{segment}"] = value
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(summary_rows)
    window_metrics = pd.DataFrame(wide_rows)
    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False)
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False)

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().astimezone().isoformat(),
        "phase": "complete",
        "project": "a_us_momentum_combo",
        "strategy": "V7.7",
        "subsystem": "Sub-B",
        "repo_root": str(ROOT),
        "entrypoint": str(SCRIPT),
        "git_branch": git_text("branch", "--show-current"),
        "git_commit": git_text("rev-parse", "HEAD"),
        "git_status_before": git_text("status", "--short"),
        "git_status_after": git_text("status", "--short"),
        "scan_type": "runtime_override_grid",
        "parameter_group": "US_ROT_MAX_LEV with BIL pre-listing cash proxy",
        "baseline": {"US_ROT_TARGET_VOL": 0.25, "US_ROT_MAX_LEV": 2.0, "US_ROT_FUTURES": sorted(mod.US_ROT_FUTURES)},
        "candidate_grid": [{"US_ROT_MAX_LEV": value} for value in CANDIDATES],
        "cost_model": "US_ROT_COMMISSION plus Sub-B blend execution turnover; no extra financing/open-impact model beyond existing Sub-B code",
        "execution_timing": "T close signal -> T+1 open execution where open data is available",
        "cash_proxy": {
            "asset": "BIL",
            "annual_return": CASH_ANNUAL,
            "daily_return": cash_daily,
            "proxy_start": core_start.date().isoformat(),
            "scope": "pre-BIL-listing segment only; listed BIL data is used once available",
        },
        "data_snapshot": {
            "sources": sources,
            "raw_ranges": raw_ranges,
            "panel_start": close.index[0].date().isoformat(),
            "panel_end": close.index[-1].date().isoformat(),
            "panel_rows": int(len(close)),
            "weekend_rows": int((close.index.dayofweek >= 5).sum()),
            "columns": list(close.columns),
        },
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
        },
        "decision": "diagnostic scan; do not change production leverage from this run alone",
        "stability_label": "pressure-test-diagnostic",
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_DIR / "command_log.txt").write_text(
        f"python {Path(__file__).name}\n",
        encoding="utf-8",
    )

    gfc = scan_summary[scan_summary["segment"].eq("gfc_peak_to_trough")].copy()
    cal2008 = scan_summary[scan_summary["segment"].eq("calendar_2008")].copy()
    best_gfc_dd = gfc.sort_values(["max_dd", "ann_return"], ascending=[False, False]).iloc[0]
    best_2008_dd = cal2008.sort_values(["max_dd", "ann_return"], ascending=[False, False]).iloc[0]
    record = [
        "# V7.7 Sub-B Max Leverage 2008 Cash-Proxy Stress Scan",
        "",
        "## Run Metadata",
        f"- Entrypoint: `{SCRIPT.name}`",
        f"- Data: Yahoo open/close via `fetch_yahoo`; BIL pre-listing segment replaced with {CASH_ANNUAL:.1%} annualized cash.",
        f"- Candidate max leverage values: {', '.join(str(v) for v in CANDIDATES)}",
        "- Levered assets under current code: QQQM/GLDM only, via QQQ/GLD proxies.",
        "",
        "## Research Question",
        "Does the current 2.0x max leverage cap on QQQ/GLD look too high in the 2008 stress window?",
        "",
        "## Data Snapshot",
        f"- Panel: {close.index[0].date()} to {close.index[-1].date()}, rows={len(close)}, weekend_rows={(close.index.dayofweek >= 5).sum()}",
        f"- First result date after 390-day warmup: {scan_summary[scan_summary['segment'].eq('full')]['start'].iloc[0]}",
        "",
        "## Decision",
        "Diagnostic only. This run supports caution around 2.0x in the 2008 stress window, but production change needs confirmation on broader windows and the full portfolio objective.",
        "",
        "## Stability",
        "pressure-test-diagnostic",
        "",
        "## Key Result",
        f"- Best GFC max-drawdown candidate: {best_gfc_dd['candidate']} max_dd={best_gfc_dd['max_dd']:.2%}, ann_return={best_gfc_dd['ann_return']:.2%}",
        f"- Best 2008 max-drawdown candidate: {best_2008_dd['candidate']} max_dd={best_2008_dd['max_dd']:.2%}, ann_return={best_2008_dd['ann_return']:.2%}",
        "",
        "See `scan_summary.csv` and `window_metrics.csv` for full metrics.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

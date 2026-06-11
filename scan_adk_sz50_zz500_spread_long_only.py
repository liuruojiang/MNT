"""Layer 0/1 scan for ADK-style long SZ50 / short ZZ500 spread.

Direction: long SSE 50 price index (1.000016) / short CSI 500 price index
(1.000905). This first layer scans signal families only. Target-vol, NAV
defense, overheat, amount/volume gates, and momentum decay are intentionally off.
"""
from __future__ import annotations

import importlib.util
import json
import math
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
ENTRYPOINT = ROOT / "mnt_bot V 7.7 plus.py"
RUN_DIR = ROOT / "quant_param_scan_runs" / "20260612_adk_sz50_zz500_spread_long_only_v77_adk_spread_layer0_layer1_signal_family"
ANNUALIZATION_DAYS = 242
FORMAL_START = pd.Timestamp("2007-01-15")
SZ50_PUBLICATION_DATE = "2004-01-02"
ZZ500_PUBLICATION_DATE = "2007-01-15"
COMMISSION_ONE_WAY = 0.0005

SEGMENTS = [
    ("full", None),
    ("last_10y", 10),
    ("last_5y", 5),
    ("last_3y", 3),
    ("last_1y", 1),
]


def git_text(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace").strip()
    except Exception as exc:
        return f"git_error: {exc}"


def load_v77():
    spec = importlib.util.spec_from_file_location("mnt_v77", ENTRYPOINT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def weighted_slope_score(series: pd.Series, window: int, weight_end: float = 1.0) -> pd.Series:
    y = series.astype(float)
    x = np.arange(window, dtype=float)
    x = x - x.mean()
    weights = np.linspace(1.0, float(weight_end), window)
    weights = weights / weights.sum()

    def calc(arr: np.ndarray) -> float:
        if not np.isfinite(arr).all():
            return np.nan
        ym = float(np.sum(weights * arr))
        xm = float(np.sum(weights * x))
        cov = float(np.sum(weights * (x - xm) * (arr - ym)))
        var = float(np.sum(weights * (x - xm) ** 2))
        if var <= 0:
            return np.nan
        return cov / var * window * 100.0

    return y.rolling(window).apply(calc, raw=True)


def weighted_slope_r2(series: pd.Series, window: int, weight_end: float = 1.0) -> pd.Series:
    y = series.astype(float)
    x = np.arange(window, dtype=float)
    weights = np.linspace(1.0, float(weight_end), window)
    weights = weights / weights.sum()

    def calc(arr: np.ndarray) -> float:
        if not np.isfinite(arr).all():
            return np.nan
        xm = float(np.sum(weights * x))
        ym = float(np.sum(weights * arr))
        xdm = x - xm
        ydm = arr - ym
        cov = float(np.sum(weights * xdm * ydm))
        vx = float(np.sum(weights * xdm**2))
        vy = float(np.sum(weights * ydm**2))
        if vx <= 0 or vy <= 0:
            return np.nan
        corr = cov / math.sqrt(vx * vy)
        return max(0.0, min(1.0, corr * corr))

    return y.rolling(window).apply(calc, raw=True)


def max_drawdown(nav: pd.Series) -> float:
    if nav.empty:
        return float("nan")
    dd = nav / nav.cummax() - 1.0
    return float(dd.min())


def metrics_for_segment(df: pd.DataFrame, segment: str, years: int | None) -> dict[str, object]:
    if years is None:
        d = df.copy()
    else:
        cutoff = df.index.max() - pd.DateOffset(years=years)
        d = df.loc[df.index >= cutoff].copy()
    if d.empty:
        return {
            "segment": segment,
            "start": "",
            "end": "",
            "rows": 0,
            "ann_return": 0.0,
            "ann_vol": 0.0,
            "max_dd": 0.0,
            "sharpe_repo": 0.0,
            "avg_weight": 0.0,
            "avg_turnover": 0.0,
            "holding_days": 0,
            "holding_day_ratio": 0.0,
            "cost_total": 0.0,
        }
    ret = d["return"].astype(float)
    nav = (1.0 + ret).cumprod()
    ann_return = float(nav.iloc[-1] ** (ANNUALIZATION_DAYS / len(d)) - 1.0)
    ann_vol = float(ret.std(ddof=0) * math.sqrt(ANNUALIZATION_DAYS))
    sharpe = float(ann_return / ann_vol) if ann_vol > 0 else 0.0
    return {
        "segment": segment,
        "start": d.index.min().strftime("%Y-%m-%d"),
        "end": d.index.max().strftime("%Y-%m-%d"),
        "rows": int(len(d)),
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "max_dd": max_drawdown(nav),
        "sharpe_repo": sharpe,
        "avg_weight": float(d["weight"].mean()),
        "avg_turnover": float(d["turnover"].mean()),
        "holding_days": int((d["weight"] > 0).sum()),
        "holding_day_ratio": float((d["weight"] > 0).mean()),
        "cost_total": float(d["cost"].sum()),
    }


def build_candidate_returns(panel: pd.DataFrame, candidate: dict[str, object]) -> pd.DataFrame:
    ratio = panel["ratio"]
    family = str(candidate["family"])
    threshold = float(candidate.get("threshold", 0.0))
    weight_end = float(candidate.get("weight_end", 1.0))

    if family == "bias_momentum":
        bias_ma = int(candidate["bias_ma"])
        mom_day = int(candidate["mom_day"])
        feature = ratio / ratio.rolling(bias_ma).mean() - 1.0
        score = weighted_slope_score(feature, mom_day, weight_end)
        r2 = weighted_slope_r2(feature, mom_day, weight_end)
    elif family == "simple_momentum":
        mom_day = int(candidate["mom_day"])
        score = ratio.pct_change(mom_day) * 100.0
        r2 = pd.Series(1.0, index=ratio.index)
    elif family == "log_wls_momentum":
        mom_day = int(candidate["mom_day"])
        score = weighted_slope_score(np.log(ratio), mom_day, weight_end)
        r2 = weighted_slope_r2(np.log(ratio), mom_day, weight_end)
    else:
        raise ValueError(f"unknown family: {family}")

    raw_signal = ((score > threshold) & (r2 >= 0.05)).astype(float)
    exec_weight = raw_signal.shift(1).fillna(0.0)
    spread_return = panel["SZ50"].pct_change().fillna(0.0) - panel["ZZ500"].pct_change().fillna(0.0)
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
        index=panel.index,
    )
    warmup = int(max(candidate.get("bias_ma", 0) or 0, candidate.get("mom_day", 0) or 0) + 2)
    return out.iloc[warmup:].copy()


def candidate_grid() -> list[dict[str, object]]:
    grid: list[dict[str, object]] = []
    for bias_ma in [20, 40, 60, 80, 100, 120]:
        for mom_day in [10, 15, 20, 30, 40, 60]:
            for weight_end in [1.0, 2.0, 3.0]:
                grid.append(
                    {
                        "candidate": f"bias_ma{bias_ma:03d}_mom{mom_day:03d}_we{str(weight_end).replace('.', 'p')}_gt0",
                        "family": "bias_momentum",
                        "bias_ma": bias_ma,
                        "mom_day": mom_day,
                        "weight_end": weight_end,
                        "threshold": 0.0,
                    }
                )
    for mom_day in [10, 20, 40, 60, 80, 120]:
        grid.append(
            {
                "candidate": f"simple_mom{mom_day:03d}_gt0",
                "family": "simple_momentum",
                "bias_ma": 0,
                "mom_day": mom_day,
                "weight_end": 1.0,
                "threshold": 0.0,
            }
        )
    for mom_day in [10, 15, 20, 30, 40, 60, 80, 120]:
        for weight_end in [1.0, 2.0, 3.0]:
            grid.append(
                {
                    "candidate": f"log_wls_mom{mom_day:03d}_we{str(weight_end).replace('.', 'p')}_gt0",
                    "family": "log_wls_momentum",
                    "bias_ma": 0,
                    "mom_day": mom_day,
                    "weight_end": weight_end,
                    "threshold": 0.0,
                }
            )
    return grid


def build_width(window_metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for family, fam_df in window_metrics.groupby("family"):
        fam_df = fam_df.sort_values("sharpe_repo_full", ascending=False)
        best = fam_df.iloc[0]
        pass_cut = float(best["sharpe_repo_full"]) * 0.8
        pass_df = fam_df[fam_df["sharpe_repo_full"] >= pass_cut]
        rows.append(
            {
                "family": family,
                "best_candidate": best["candidate"],
                "best_full_ann_return": best["ann_return_full"],
                "best_full_max_dd": best["max_dd_full"],
                "best_full_sharpe": best["sharpe_repo_full"],
                "pass_cut_80pct_sharpe": pass_cut,
                "pass_count": int(len(pass_df)),
                "candidate_count": int(len(fam_df)),
                "pass_ratio": float(len(pass_df) / len(fam_df)),
                "pass_patch": bool(len(pass_df) >= max(3, int(len(fam_df) * 0.10))),
            }
        )
    return pd.DataFrame(rows).sort_values("best_full_sharpe", ascending=False)


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def window_table(df: pd.DataFrame, n: int = 12) -> str:
    cols = ["candidate", "family"]
    for segment, _years in SEGMENTS:
        cols.extend([f"ann_return_{segment}", f"max_dd_{segment}"])
    display = df.head(n)[cols].copy()
    for col in display.columns:
        if col.startswith("ann_return_") or col.startswith("max_dd_"):
            display[col] = display[col].map(lambda x: pct(float(x)))
    return display.to_markdown(index=False)


def main() -> None:
    git_status_before = git_text(["status", "--short"])
    mod = load_v77()
    sz50 = mod._load_cn_official_cache(mod.CN_DK_SZ50_SECID).rename(columns={"close": "SZ50"})
    zz500 = mod._load_cn_official_cache(mod.CN_DK_ZZ500_SECID).rename(columns={"close": "ZZ500"})
    panel = pd.concat([sz50["SZ50"], zz500["ZZ500"]], axis=1).dropna()
    raw_start = panel.index.min()
    panel = panel.loc[panel.index >= FORMAL_START].copy()
    panel["ratio"] = panel["SZ50"] / panel["ZZ500"]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    grid = candidate_grid()
    long_rows = []
    wide_rows = []
    daily_curves = []

    for candidate in grid:
        result = build_candidate_returns(panel, candidate)
        nav = (1.0 + result["return"]).cumprod()
        out = result.copy()
        out["nav"] = nav
        out["candidate"] = candidate["candidate"]
        daily_curves.append(out.reset_index(names="date"))

        wide = {**candidate}
        for segment, years in SEGMENTS:
            m = metrics_for_segment(result, segment, years)
            long_rows.append({**candidate, **m})
            for key in ["ann_return", "max_dd", "sharpe_repo", "avg_weight", "avg_turnover", "holding_day_ratio"]:
                wide[f"{key}_{segment}"] = m[key]
        wide_rows.append(wide)

    scan_summary = pd.DataFrame(long_rows)
    window_metrics = pd.DataFrame(wide_rows)
    daily = pd.concat(daily_curves, ignore_index=True)
    ridge = build_width(window_metrics)
    top = window_metrics.sort_values("sharpe_repo_full", ascending=False).head(20)

    scan_summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    window_metrics.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(RUN_DIR / "daily_curves.csv", index=False, encoding="utf-8-sig")
    ridge.to_csv(RUN_DIR / "ridge_width.csv", index=False, encoding="utf-8-sig")

    record_lines = [
        "# SZ50/ZZ500 ADK Spread Layer 0/1 Scan",
        "",
        "## Run Metadata",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- run_folder: `{RUN_DIR}`",
        "- decision: `layer0_layer1_complete_not_promoted`",
        "- stability: `signal_family_width_pending_user_confirmation`",
        "",
        "## Research Question",
        "Fresh first-layer test of long SZ50 / short ZZ500 as a standalone ADK-style spread sleeve.",
        "",
        "## Implementation Anchor",
        "- V7.7 constants and local cache loader imported from `mnt_bot V 7.7 plus.py`.",
        "- Direction ratio: `1.000016 / 1.000905`.",
        "- Layer 0/1 scans signal family, window, and recency weight only.",
        "- Result status: `quasi-formal`; price-index close-to-close spread research with two-leg commissions, excluding futures basis, financing, borrow, and short locate costs.",
        "- Source-change rule: `research_only_no_source_change`.",
        "",
        "## Data Snapshot",
        f"- SZ50 publication date: {SZ50_PUBLICATION_DATE}; local rows: {len(sz50)}, start {sz50.index.min().date()}, end {sz50.index.max().date()}.",
        f"- ZZ500 publication date: {ZZ500_PUBLICATION_DATE}; local rows: {len(zz500)}, start {zz500.index.min().date()}, end {zz500.index.max().date()}.",
        f"- Raw aligned data start: {raw_start.date()}.",
        f"- Formal aligned rows: {len(panel)}, start {panel.index.min().date()}, end {panel.index.max().date()}.",
        "- Formal start rule: latest actual index publication date among the two legs.",
        "- Adjustment mode: price index close from local official cache, no total-return substitution.",
        "",
        "## Cost and Execution Assumptions",
        "- Market: A-share index spread research using daily close data.",
        "- Trading calendar: aligned index dates from the two local cache series.",
        "- Timing: T close signal -> T+1 close-to-close spread return.",
        "- Return stream: SZ50 close-to-close return minus ZZ500 close-to-close return.",
        f"- Transaction cost: two legs times one-way commission {COMMISSION_ONE_WAY:.4%} on exposure changes.",
        "- Slippage, financing, borrow, futures basis, and short locate costs are excluded at this research layer.",
        "- Target-vol, NAV defense, overheat, amount/volume gates, and momentum decay are off.",
        "- R2 quality filter is on at `0.05` for slope-based signal families.",
        "",
        "## Runtime Override Plan",
        "No production defaults changed. This is a research-only scan artifact.",
        "",
        "## Commands",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"SZ50/ZZ500 spread Layer 0/1\" --parameter-group \"signal_family_spread_signal_window_threshold\" --repo . --entrypoint \"scan_adk_sz50_zz500_spread_long_only.py\" --date 2026-06-12 --slug \"adk_sz50_zz500_spread_long_only_v77_adk_spread_layer0_layer1_signal_family\"`",
        "- `python -m py_compile \"scan_adk_sz50_zz500_spread_long_only.py\"`",
        "- `python \"scan_adk_sz50_zz500_spread_long_only.py\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py <run_folder> --decision \"layer0_layer1_complete_not_promoted\" --stability-label \"signal_family_width_pending_user_confirmation\"`",
        "- `python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict <run_folder>`",
        "",
        "## Output Files",
        "- `scan_summary.csv`",
        "- `window_metrics.csv`",
        "- `daily_curves.csv`",
        "- `ridge_width.csv`",
        "- `scan_meta.json`",
        "- `command_log.txt`",
        "",
        "## Full-Sample Results",
        window_table(top, 12),
        "",
        "## Window Results",
        "The table above includes full, last_10y, last_5y, last_3y, and last_1y annualized return and max drawdown for the leading candidates. See `window_metrics.csv` for all candidates.",
        "",
        "## Stability Classification",
        ridge.to_markdown(index=False),
        "",
        "## Decision",
        "Layer 0/1 completed but not promoted. Stop for user confirmation before any dense Layer 1 patch or Layer 2 filters.",
        "",
        "## User-Facing Summary",
        "Use the top table and width diagnostics to decide whether to continue around the leading family.",
    ]
    (RUN_DIR / "record.md").write_text("\n".join(record_lines), encoding="utf-8")

    meta = {
        "run_id": RUN_DIR.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": "A-share / US momentum combo",
        "strategy": "V7.7 ADK spread research",
        "subsystem": "SZ50/ZZ500 spread Layer 0/1",
        "repo_root": str(ROOT),
        "entrypoint": str(Path(__file__).name),
        "implementation_anchor": str(ENTRYPOINT.name),
        "git_branch": git_text(["branch", "--show-current"]),
        "git_commit": git_text(["rev-parse", "HEAD"]),
        "git_status_before": git_status_before,
        "git_status_after": git_text(["status", "--short"]),
        "scan_type": "fresh_layer0_layer1_signal_family_scan",
        "result_status": "quasi-formal_price_index_close_to_close_spread_research",
        "parameter_group": "signal_family_spread_signal_window_threshold",
        "baseline": {"direction": "long_SZ50_short_ZZ500", "threshold": 0.0},
        "candidate_grid": grid,
        "cost_model": {
            "one_way_commission": COMMISSION_ONE_WAY,
            "legs": 2,
            "execution": "T close signal -> T+1 close-to-close return",
            "slippage": "excluded",
            "financing_borrow_or_basis": "excluded",
            "short_locate_or_borrow": "excluded",
        },
        "data_snapshot": {
            "source": "mnt_bot V 7.7 plus.py _load_cn_official_cache",
            "official_publication_sources": {
                "sz50": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000016factsheet.pdf",
                "zz500": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000905factsheet.pdf",
            },
            "sz50": {
                "secid": str(mod.CN_DK_SZ50_SECID),
                "publication_date": SZ50_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_SZ50_SECID))),
                "rows": int(len(sz50)),
                "start": str(sz50.index.min().date()),
                "end": str(sz50.index.max().date()),
            },
            "zz500": {
                "secid": str(mod.CN_DK_ZZ500_SECID),
                "publication_date": ZZ500_PUBLICATION_DATE,
                "cache_path": str(Path(mod._cn_cache_path(mod.CN_DK_ZZ500_SECID))),
                "rows": int(len(zz500)),
                "start": str(zz500.index.min().date()),
                "end": str(zz500.index.max().date()),
            },
            "formal": {
                "rows": int(len(panel)),
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
                "start_rule": "latest actual publication/listing date among participants",
                "ratio": "SZ50 / ZZ500",
                "return_stream": "SZ50 pct_change - ZZ500 pct_change",
            },
        },
        "decision": "layer0_layer1_complete_not_promoted",
        "stability_label": "signal_family_width_pending_user_confirmation",
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
        "python D:/Codex/home/skills/quant-param-scan/scripts/init_quant_param_scan_run.py --root quant_param_scan_runs --project \"A-share / US momentum combo\" --strategy \"V7.7 ADK spread research\" --subsystem \"SZ50/ZZ500 spread Layer 0/1\" --parameter-group \"signal_family_spread_signal_window_threshold\" --repo . --entrypoint \"scan_adk_sz50_zz500_spread_long_only.py\" --date 2026-06-12 --slug \"adk_sz50_zz500_spread_long_only_v77_adk_spread_layer0_layer1_signal_family\"\n"
        "python -m py_compile \"scan_adk_sz50_zz500_spread_long_only.py\"\n"
        "python \"scan_adk_sz50_zz500_spread_long_only.py\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/finalize_quant_param_scan_run.py \"{RUN_DIR}\" --decision \"layer0_layer1_complete_not_promoted\" --stability-label \"signal_family_width_pending_user_confirmation\"\n"
        f"python D:/Codex/home/skills/quant-param-scan/scripts/check_quant_param_scan_artifacts.py --phase complete --strict \"{RUN_DIR}\"\n",
        encoding="utf-8",
    )

    print(f"RUN_DIR={RUN_DIR}")
    print(f"DATA={panel.index.min().date()}->{panel.index.max().date()} rows={len(panel)} candidates={len(grid)}")
    print("TOP12")
    print(
        top[
            [
                "candidate",
                "family",
                "ann_return_full",
                "max_dd_full",
                "sharpe_repo_full",
                "ann_return_last_10y",
                "max_dd_last_10y",
                "ann_return_last_5y",
                "max_dd_last_5y",
                "ann_return_last_3y",
                "max_dd_last_3y",
                "ann_return_last_1y",
                "max_dd_last_1y",
            ]
        ]
        .head(12)
        .to_string(index=False)
    )
    print("WIDTH")
    print(ridge.to_string(index=False))


if __name__ == "__main__":
    main()

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


RUN_DIR = Path(__file__).resolve().parent
ROOT = RUN_DIR.parents[1]
V76_SOURCE = ROOT / "mnt_bot V 7.6 plus.py"
MICROCAP_FILE_NAME = "microcap_top100_mom16_targetvol25_max1p5_v1_6_costed_nav.csv"

WINDOWS = {
    "full": None,
    "last_10y": pd.DateOffset(years=10),
    "last_5y": pd.DateOffset(years=5),
    "last_3y": pd.DateOffset(years=3),
    "last_1y": pd.DateOffset(years=1),
}
BASE_WEIGHTS = {
    "Sub-A": 0.10,
    "Sub-A-DK": 0.15,
    "Microcap": 0.15,
    "Sub-D": 0.20,
    "Sub-B": 0.40,
}
FIXED_SUM_EX_MICRO_B = BASE_WEIGHTS["Sub-A"] + BASE_WEIGHTS["Sub-A-DK"] + BASE_WEIGHTS["Sub-D"]
BANDS = {
    "dd_5_10": {"boost_dd": 0.05, "cut_dd": 0.10},
    "dd_5_12": {"boost_dd": 0.05, "cut_dd": 0.12},
    "dd_3_10": {"boost_dd": 0.03, "cut_dd": 0.10},
}
EXECUTIONS = ["daily", "weekly", "month_end"]
COST_BPS = [0, 5, 10, 20]


class CaptureMsg:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, text: object) -> None:
        self.lines.append(str(text))


def git_value(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
    except Exception:
        return ""


def load_module():
    spec = importlib.util.spec_from_file_location("mnt_v76_five_sleeve_scan", V76_SOURCE)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {V76_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    module.poe = SimpleNamespace(
        update_settings=lambda *_args, **_kwargs: None,
        BotError=RuntimeError,
        default_chat=None,
        query=SimpleNamespace(text="", attachments=[]),
        call=lambda *_args, **_kwargs: "",
        start_message=lambda: CaptureMsg(),
    )
    spec.loader.exec_module(module)
    return module


def find_microcap_source() -> Path:
    matches = sorted(ROOT.parent.glob(f"*/outputs/{MICROCAP_FILE_NAME}"))
    if not matches:
        raise FileNotFoundError(f"Cannot find {MICROCAP_FILE_NAME} under {ROOT.parent}")
    return matches[0]


def fetch_official_returns() -> tuple[pd.DataFrame, dict[str, object]]:
    mod = load_module()
    old_weights = dict(mod.COMBINED_WEIGHTS)
    try:
        # Enable the legacy Sub-C engine so its official daily return can be
        # mapped into the current five-sleeve "Sub-D" allocation test.
        mod.COMBINED_WEIGHTS.update(
            {
                "Sub-A": 0.10,
                "Sub-A-DK": 0.15,
                "Microcap": 0.15,
                "Sub-C": 0.20,
                "Sub-B": 0.40,
            }
        )
        msg = CaptureMsg()
        engine = mod.CombinedStrategyV76()
        cn_close, cn_dk_close, us_rot_close, us_prod_daily = engine._fetch_data(
            msg,
            include_cn_live_snapshot=False,
            include_us_live_snapshot=False,
        )
        (
            cn_result,
            cn_dk_result,
            us_rot_result,
            _prod_monthly,
            prod_sig_a,
            prod_sig_b,
            _prod_nav,
            _prod_details,
        ) = engine._run_strategies(cn_close, cn_dk_close, us_rot_close, us_prod_daily)
        subd_ret = mod._get_subc_daily_ret(us_prod_daily, prod_sig_a, prod_sig_b).rename("Sub-D")
        microcap_source = find_microcap_source()
        micro = pd.read_csv(microcap_source, parse_dates=["date"]).set_index("date").sort_index()
        micro_ret = pd.to_numeric(micro["return_net"], errors="coerce").dropna().rename("Microcap")
        series_map = {
            "Sub-A": cn_result["return"].dropna().rename("Sub-A"),
            "Sub-A-DK": cn_dk_result["return"].dropna().rename("Sub-A-DK"),
            "Microcap": micro_ret,
            "Sub-D": subd_ret.dropna(),
            "Sub-B": us_rot_result["return"].dropna().rename("Sub-B"),
        }
        common_start = max(s.index.min() for s in series_map.values())
        common_end = min(s.index.max() for s in series_map.values())
        all_dates = sorted(
            set().union(
                *[
                    set(s.loc[(s.index >= common_start) & (s.index <= common_end)].index)
                    for s in series_map.values()
                ]
            )
        )
        index = pd.DatetimeIndex(all_dates)
        ret_df = pd.DataFrame(
            {name: s.reindex(index).fillna(0.0) for name, s in series_map.items()},
            index=index,
        )[["Sub-A", "Sub-A-DK", "Microcap", "Sub-D", "Sub-B"]]
        ret_df.index.name = "date"
        data_meta = {
            "microcap_source": str(microcap_source),
            "subd_source": "official V7.6 legacy Sub-C daily return mapped to Sub-D",
            "fetch_log": "".join(msg.lines)[-6000:],
            "series_ranges": {
                name: {
                    "start": s.index.min().date().isoformat(),
                    "end": s.index.max().date().isoformat(),
                    "rows": int(len(s)),
                }
                for name, s in series_map.items()
            },
            "common_start": common_start.date().isoformat(),
            "common_end": common_end.date().isoformat(),
            "aligned_rows": int(len(ret_df)),
        }
        return ret_df, data_meta
    finally:
        mod.COMBINED_WEIGHTS.clear()
        mod.COMBINED_WEIGHTS.update(old_weights)


def microcap_target(ret_df: pd.DataFrame, boost_dd: float, cut_dd: float) -> pd.Series:
    micro_nav = (1.0 + ret_df["Microcap"]).cumprod()
    prior_dd = micro_nav.shift(1) / micro_nav.cummax().shift(1) - 1.0
    target = pd.Series(0.15, index=ret_df.index, dtype=float)
    target.loc[prior_dd >= -boost_dd] = 0.20
    target.loc[prior_dd <= -cut_dd] = 0.10
    return target.fillna(0.15)


def execution_mask(index: pd.DatetimeIndex, execution: str) -> pd.Series:
    if execution == "daily":
        return pd.Series(True, index=index)
    next_index = pd.Series(index, index=index).shift(-1)
    if execution == "weekly":
        current_period = pd.Series(index.to_period("W-FRI"), index=index)
        next_period = pd.Series(next_index.dt.to_period("W-FRI").values, index=index)
    elif execution == "month_end":
        current_period = pd.Series(index.to_period("M"), index=index)
        next_period = pd.Series(next_index.dt.to_period("M").values, index=index)
    else:
        raise ValueError(f"unknown execution: {execution}")
    return next_period.notna() & (current_period != next_period)


def build_weights(ret_df: pd.DataFrame, target_micro: pd.Series | None, execution: str) -> pd.DataFrame:
    if target_micro is None:
        return pd.DataFrame({name: float(value) for name, value in BASE_WEIGHTS.items()}, index=ret_df.index)
    mask = execution_mask(ret_df.index, execution)
    executed = pd.Series(np.nan, index=ret_df.index, dtype=float)
    executed.loc[mask] = target_micro.loc[mask]
    executed.iloc[0] = BASE_WEIGHTS["Microcap"]
    executed = executed.ffill().fillna(BASE_WEIGHTS["Microcap"])
    weights = pd.DataFrame(index=ret_df.index)
    weights["Sub-A"] = BASE_WEIGHTS["Sub-A"]
    weights["Sub-A-DK"] = BASE_WEIGHTS["Sub-A-DK"]
    weights["Microcap"] = executed
    weights["Sub-D"] = BASE_WEIGHTS["Sub-D"]
    weights["Sub-B"] = 1.0 - FIXED_SUM_EX_MICRO_B - executed
    return weights[["Sub-A", "Sub-A-DK", "Microcap", "Sub-D", "Sub-B"]]


def turnover(weights: pd.DataFrame) -> pd.Series:
    return weights.diff().abs().sum(axis=1).fillna(0.0)


def nav_from_weights(ret_df: pd.DataFrame, weights: pd.DataFrame, cost_bps: float) -> tuple[pd.Series, pd.Series]:
    alloc_turnover = turnover(weights)
    net_ret = (ret_df * weights).sum(axis=1) - alloc_turnover * (cost_bps / 10000.0)
    nav = (1.0 + net_ret).cumprod()
    return nav / nav.iloc[0], alloc_turnover


def underwater_stats(nav: pd.Series) -> dict[str, object]:
    underwater = nav < nav.cummax()
    max_closed = 0
    current_start = None
    for dt, value in underwater.items():
        if value and current_start is None:
            current_start = dt
        elif not value and current_start is not None:
            max_closed = max(max_closed, int((dt - current_start).days))
            current_start = None
    return {
        "max_closed_underwater_days": max_closed,
        "open_underwater_days": int((nav.index[-1] - current_start).days) if current_start is not None else 0,
        "is_currently_underwater": bool(current_start is not None),
    }


def summarize(nav: pd.Series, segment: str, offset: pd.DateOffset | None) -> dict[str, object]:
    part = nav.copy() if offset is None else nav.loc[nav.index >= nav.index[-1] - offset].copy()
    part = part / part.iloc[0]
    daily_ret = part.pct_change().dropna()
    years = (part.index[-1] - part.index[0]).days / 365.25
    ann_return = part.iloc[-1] ** (1.0 / years) - 1.0
    ann_vol = daily_ret.std() * np.sqrt(252.0)
    max_dd = (part / part.cummax() - 1.0).min()
    return {
        "segment": segment,
        "start": part.index[0].date().isoformat(),
        "end": part.index[-1].date().isoformat(),
        "rows": int(len(part)),
        "ann_return": float(ann_return),
        "ann_vol": float(ann_vol),
        "max_dd": float(max_dd),
        "sharpe_repo": float(ann_return / ann_vol) if ann_vol and ann_vol > 0 else np.nan,
        "total_return": float(part.iloc[-1] - 1.0),
        **underwater_stats(part),
    }


def build_outputs(ret_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    weight_rows: list[dict[str, object]] = []
    nav_outputs: dict[str, pd.Series] = {}
    scenarios: list[tuple[str, str, str, float | str, float | str, int, pd.DataFrame]] = [
        ("fixed_10_15_15_20_40_cost0", "fixed", "none", "", "", 0, build_weights(ret_df, None, "daily"))
    ]
    for band_name, band in BANDS.items():
        target = microcap_target(ret_df, band["boost_dd"], band["cut_dd"])
        for execution in EXECUTIONS:
            weights = build_weights(ret_df, target, execution)
            for cost_bps in COST_BPS:
                scenarios.append(
                    (
                        f"{band_name}_{execution}_cost{cost_bps}bps",
                        band_name,
                        execution,
                        band["boost_dd"],
                        band["cut_dd"],
                        cost_bps,
                        weights,
                    )
                )
    for candidate, band, execution, boost_dd, cut_dd, cost_bps, weights in scenarios:
        nav, alloc_turnover = nav_from_weights(ret_df, weights, float(cost_bps))
        nav_outputs[candidate] = nav
        for segment, offset in WINDOWS.items():
            rows.append(
                {
                    "candidate": candidate,
                    **summarize(nav, segment, offset),
                    "band": band,
                    "execution": execution,
                    "boost_dd": boost_dd,
                    "cut_dd": cut_dd,
                    "cost_bps": cost_bps,
                    "allocation_turnover_total": float(alloc_turnover.sum()),
                    "allocation_turnover_annualized": float(
                        alloc_turnover.sum() / ((ret_df.index[-1] - ret_df.index[0]).days / 365.25)
                    ),
                    "rebalance_count": int((weights["Microcap"].diff().abs() > 1e-12).sum()),
                    "avg_microcap_weight": float(weights["Microcap"].mean()),
                    "last_microcap_weight": float(weights["Microcap"].iloc[-1]),
                    "last_subb_weight": float(weights["Sub-B"].iloc[-1]),
                }
            )
        weight_rows.append(
            {
                "candidate": candidate,
                "band": band,
                "execution": execution,
                "boost_dd": boost_dd,
                "cut_dd": cut_dd,
                "cost_bps": cost_bps,
                "avg_microcap_weight": float(weights["Microcap"].mean()),
                "last_microcap_weight": float(weights["Microcap"].iloc[-1]),
                "last_subb_weight": float(weights["Sub-B"].iloc[-1]),
                "microcap_20_days": int((weights["Microcap"] >= 0.199999).sum()),
                "microcap_15_days": int(((weights["Microcap"] > 0.100001) & (weights["Microcap"] < 0.199999)).sum()),
                "microcap_10_days": int((weights["Microcap"] <= 0.100001).sum()),
                "rebalance_count": int((weights["Microcap"].diff().abs() > 1e-12).sum()),
                "allocation_turnover_total": float(alloc_turnover.sum()),
            }
        )
        if cost_bps == 0:
            weights.to_csv(RUN_DIR / f"weights_{candidate}.csv", index_label="date", encoding="utf-8-sig")
            pd.DataFrame({"date": nav.index, "nav": nav.values}).to_csv(
                RUN_DIR / f"daily_{candidate}.csv",
                index=False,
                encoding="utf-8-sig",
            )
    return pd.DataFrame(rows), pd.DataFrame(weight_rows), pd.DataFrame(nav_outputs)


def window_metrics(summary: pd.DataFrame) -> pd.DataFrame:
    out = []
    for candidate, group in summary.groupby("candidate", sort=False):
        row: dict[str, object] = {"candidate": candidate}
        for segment in WINDOWS:
            s = group[group["segment"] == segment].iloc[0]
            row[f"ann_return_{segment}"] = s["ann_return"]
            row[f"ann_vol_{segment}"] = s["ann_vol"]
            row[f"max_dd_{segment}"] = s["max_dd"]
            row[f"sharpe_{segment}"] = s["sharpe_repo"]
            row[f"allocation_turnover_total_{segment}"] = s["allocation_turnover_total"]
            row[f"rebalance_count_{segment}"] = s["rebalance_count"]
        out.append(row)
    return pd.DataFrame(out)


def write_record(summary: pd.DataFrame, wm: pd.DataFrame, data_meta: dict[str, object]) -> None:
    base = wm[wm["candidate"] == "fixed_10_15_15_20_40_cost0"].iloc[0]
    cost0 = wm[wm["candidate"].str.endswith("cost0bps")].copy()
    cost0["delta_1y_sharpe"] = cost0["sharpe_last_1y"] - base["sharpe_last_1y"]
    best = cost0.sort_values(["sharpe_last_1y", "ann_return_last_1y"], ascending=False).iloc[0]
    practical = wm[wm["candidate"] == "dd_3_10_month_end_cost0bps"].iloc[0]
    text = f"""# V7.6 Five-Sleeve Microcap V1.6 Rebalance Validation

## Research Question

Retest the Microcap dynamic risk-budget rule on the current five-sleeve allocation:

`Sub-A / Sub-A-DK / Microcap / Sub-D / Sub-B = 10 / 15 / 15 / 20 / 40`.

`Sub-D` is mapped to the official V7.6 legacy `Sub-C` daily return engine for this run.

## Data

- Official source: `{V76_SOURCE}`
- Microcap source: `{data_meta['microcap_source']}`
- Microcap return column: `return_net`
- Sub-D source: `{data_meta['subd_source']}`
- Common start: `{data_meta['common_start']}`
- Common end: `{data_meta['common_end']}`
- Aligned daily rows: `{data_meta['aligned_rows']}`
- Source-change rule: `research_only_no_production_weight_change`
- Signal timing: Microcap weight target for date `t` uses Microcap NAV information through `t-1`.

## Cost And Execution Assumptions

- Inter-sleeve allocation turnover cost: `daily_cost = sum(abs(delta weights)) * cost_bps / 10000`.
- Tested cost levels: `{', '.join(str(x) for x in COST_BPS)} bps`.
- Dynamic Microcap changes are funded only by Sub-B.
- Sub-A, Sub-A-DK, Sub-D, and Microcap intra-sleeve costs are inherited from their official return sources.

## Baseline

- Candidate: `fixed_10_15_15_20_40_cost0`
- Full annual return: `{base['ann_return_full']:.4f}`
- Full max drawdown: `{base['max_dd_full']:.4f}`
- Full Sharpe: `{base['sharpe_full']:.4f}`
- Latest 1Y annual return: `{base['ann_return_last_1y']:.4f}`
- Latest 1Y max drawdown: `{base['max_dd_last_1y']:.4f}`
- Latest 1Y Sharpe: `{base['sharpe_last_1y']:.4f}`

## Best Cost-0 Candidate By Latest 1Y Sharpe

- Candidate: `{best['candidate']}`
- 1Y annual return: `{best['ann_return_last_1y']:.4f}`
- 1Y max drawdown: `{best['max_dd_last_1y']:.4f}`
- 1Y Sharpe: `{best['sharpe_last_1y']:.4f}`
- 1Y Sharpe delta vs baseline: `{best['delta_1y_sharpe']:.4f}`

## Practical Month-End Candidate

- Candidate: `dd_3_10_month_end_cost0bps`
- Full annual return: `{practical['ann_return_full']:.4f}`
- Full max drawdown: `{practical['max_dd_full']:.4f}`
- Full Sharpe: `{practical['sharpe_full']:.4f}`
- Latest 1Y annual return: `{practical['ann_return_last_1y']:.4f}`
- Latest 1Y max drawdown: `{practical['max_dd_last_1y']:.4f}`
- Latest 1Y Sharpe: `{practical['sharpe_last_1y']:.4f}`

## Decision

Decision: `five_sleeve_corrected_validation_completed`.
"""
    (RUN_DIR / "record.md").write_text(text, encoding="utf-8")


def main() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    ret_df, data_meta = fetch_official_returns()
    ret_df.to_csv(RUN_DIR / "aligned_five_sleeve_returns.csv", index_label="date", encoding="utf-8-sig")
    summary, weights, navs = build_outputs(ret_df)
    wm = window_metrics(summary)
    summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    wm.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    weights.to_csv(RUN_DIR / "weight_diagnostics.csv", index=False, encoding="utf-8-sig")
    navs.to_csv(RUN_DIR / "nav_outputs.csv", index_label="date", encoding="utf-8-sig")
    meta = {
        "phase": "scanned",
        "scan_type": "v76_five_sleeve_microcap_v16_rebalance_validation",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_branch": git_value(["branch", "--show-current"]),
        "git_commit": git_value(["rev-parse", "HEAD"]),
        "git_status_porcelain": git_value(["status", "--short"]),
        "official_source": str(V76_SOURCE),
        "baseline": BASE_WEIGHTS,
        "candidate_grid": {"bands": BANDS, "executions": EXECUTIONS, "cost_bps": COST_BPS},
        "data_snapshot": data_meta,
        "cost_model": {
            "inter_sleeve_allocation_turnover_bps": COST_BPS,
            "formula": "daily_cost = sum(abs(delta_weights)) * cost_bps / 10000",
        },
        "outputs": {
            "record": str(RUN_DIR / "record.md"),
            "scan_summary": str(RUN_DIR / "scan_summary.csv"),
            "window_metrics": str(RUN_DIR / "window_metrics.csv"),
            "scan_meta": str(RUN_DIR / "scan_meta.json"),
            "command_log": str(RUN_DIR / "command_log.txt"),
            "weight_diagnostics": str(RUN_DIR / "weight_diagnostics.csv"),
            "nav_outputs": str(RUN_DIR / "nav_outputs.csv"),
            "aligned_returns": str(RUN_DIR / "aligned_five_sleeve_returns.csv"),
        },
        "decision": "five_sleeve_corrected_validation_completed",
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    with (RUN_DIR / "command_log.txt").open("a", encoding="utf-8") as f:
        f.write("python quant_param_scan_runs\\20260512_v76_five_sleeve_v16_rebalance_validation\\run_five_sleeve_v16_rebalance_validation.py\n")
        f.write(f"completed_at={datetime.now().astimezone().isoformat(timespec='seconds')}\n")
    write_record(summary, wm, data_meta)
    keep = [
        "fixed_10_15_15_20_40_cost0",
        "dd_3_10_month_end_cost0bps",
        "dd_3_10_daily_cost0bps",
        "dd_5_12_month_end_cost0bps",
    ]
    cols = [
        "candidate",
        "ann_return_full",
        "max_dd_full",
        "sharpe_full",
        "ann_return_last_1y",
        "max_dd_last_1y",
        "sharpe_last_1y",
    ]
    print(wm.loc[wm["candidate"].isin(keep), cols].to_string(index=False))
    print(weights.loc[weights["candidate"].isin(keep)].to_string(index=False))


if __name__ == "__main__":
    main()

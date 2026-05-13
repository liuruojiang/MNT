from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path

import pandas as pd


RUN_DIR = Path(__file__).resolve().parent
ROOT = RUN_DIR.parents[1]
HELPER_PATH = (
    ROOT
    / "quant_param_scan_runs"
    / "20260512_v76_five_sleeve_v16_rebalance_validation"
    / "run_five_sleeve_v16_rebalance_validation.py"
)
SUBD_SOURCE_FALLBACK_REF = "885fbf4178d01cbd3aba11035e28ba172cc4221b"


def load_helper():
    spec = importlib.util.spec_from_file_location("five_sleeve_helper", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load helper from {HELPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


H = load_helper()


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


def load_git_blob_module(
    module_name: str,
    repo_path: str,
    refs: tuple[str, ...] = ("HEAD",),
) -> types.ModuleType:
    last_error: subprocess.CalledProcessError | None = None
    for ref in refs:
        try:
            code = subprocess.check_output(
                ["git", "show", f"{ref}:{repo_path}"],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                errors="replace",
                stderr=subprocess.PIPE,
            )
            break
        except subprocess.CalledProcessError as exc:
            last_error = exc
    else:
        assert last_error is not None
        raise last_error
    module = types.ModuleType(module_name)
    module.__file__ = f"git:{ref}:{repo_path}"
    module.__source_ref__ = ref
    sys.modules[module_name] = module
    exec(compile(code, module.__file__, "exec"), module.__dict__)
    return module


def build_real_subd_return() -> tuple[pd.Series, dict[str, object]]:
    subd_refs = ("HEAD", SUBD_SOURCE_FALLBACK_REF)
    subd = load_git_blob_module(
        "research_subd_six_etf_weighted_slope",
        "research_subd_six_etf_weighted_slope.py",
        subd_refs,
    )
    sys.modules["research_subd_six_etf_weighted_slope"] = subd
    runner = load_git_blob_module("run_subd_six_etf_v1_1_git", "run_subd_six_etf_v1_1.py", subd_refs)
    subd.OUTPUT_DIR = RUN_DIR / "subd_outputs"
    config = subd.RunConfig(
        source="sina",
        one_way_cost=runner.ONE_WAY_COST,
        start_date=runner.START_DATE,
        end_date=runner.END_DATE,
        output_tag="v1_1_20260509_real_subd_combo",
        target_vols=(),
        vol_window=subd.DEFAULT_VOL_WINDOW,
        max_lev=subd.DEFAULT_MAX_LEV,
    )
    prices, sources = subd.load_close(config)
    prices = prices.loc[prices.index >= config.start_date]
    curves = runner.build_curves(prices, config)
    curve = next(c for c in curves if str(c["scenario"].iloc[0]) == "v1_1_staged_50_plus_ma60_overheat")
    curve.to_csv(RUN_DIR / "subd_v1_1_daily.csv", encoding="utf-8-sig")
    sources.to_csv(RUN_DIR / "subd_v1_1_sources.csv", index=False, encoding="utf-8-sig")
    subd.data_quality(prices).to_csv(RUN_DIR / "subd_v1_1_data_quality.csv", index=False, encoding="utf-8-sig")
    return curve["return"].dropna().rename("Sub-D"), {
        "source": (
            f"git {runner.__source_ref__}:run_subd_six_etf_v1_1.py"
            f" + git {subd.__source_ref__}:research_subd_six_etf_weighted_slope.py"
        ),
        "scenario": "v1_1_staged_50_plus_ma60_overheat",
        "data_source": "akshare.fund_etf_hist_sina raw close",
        "start": curve.index.min().date().isoformat(),
        "end": curve.index.max().date().isoformat(),
        "rows": int(len(curve)),
        "daily_output": str(RUN_DIR / "subd_v1_1_daily.csv"),
    }


def fetch_returns() -> tuple[pd.DataFrame, dict[str, object]]:
    mod = H.load_module()
    msg = H.CaptureMsg()
    engine = mod.CombinedStrategyV76()
    cn_close, cn_dk_close, us_rot_close, us_prod_daily = engine._fetch_data(
        msg,
        include_cn_live_snapshot=False,
        include_us_live_snapshot=False,
    )
    cn_result, cn_dk_result, us_rot_result, *_rest = engine._run_strategies(
        cn_close,
        cn_dk_close,
        us_rot_close,
        us_prod_daily,
    )
    microcap_source = H.find_microcap_source()
    micro = pd.read_csv(microcap_source, parse_dates=["date"]).set_index("date").sort_index()
    micro_ret = pd.to_numeric(micro["return_net"], errors="coerce").dropna().rename("Microcap")
    subd_ret, subd_meta = build_real_subd_return()
    series_map = {
        "Sub-A": cn_result["return"].dropna().rename("Sub-A"),
        "Sub-A-DK": cn_dk_result["return"].dropna().rename("Sub-A-DK"),
        "Microcap": micro_ret,
        "Sub-D": subd_ret,
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
    meta = {
        "microcap_source": f"sibling_repo_outputs/{H.MICROCAP_FILE_NAME}",
        "subd": subd_meta,
        "fetch_log_tail": "".join(msg.lines)[-6000:],
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
    return ret_df, meta


def write_record(wm: pd.DataFrame, weights: pd.DataFrame, data_meta: dict[str, object]) -> None:
    base = wm[wm["candidate"] == "fixed_10_15_15_20_40_cost0"].iloc[0]
    practical = wm[wm["candidate"] == "dd_3_10_month_end_cost0bps"].iloc[0]
    daily = wm[wm["candidate"] == "dd_3_10_daily_cost0bps"].iloc[0]
    text = f"""# V7.6 Five-Sleeve Real Sub-D V1.6 Validation

## Scope

This run corrects the combo definition to:

`Sub-A / Sub-A-DK / Microcap / Sub-D / Sub-B = 10 / 15 / 15 / 20 / 40`.

Sub-D is the real six-ETF `v1.1_staged_50_plus_ma60_overheat` strategy loaded read-only from git HEAD. The deleted working-tree files were not restored.

## Data

- V7.6 source: `mnt_bot V 7.6 plus.py`
- Microcap source: `{data_meta['microcap_source']}`
- Sub-D source: `{data_meta['subd']['source']}`
- Sub-D data source: `{data_meta['subd']['data_source']}`
- Common start: `{data_meta['common_start']}`
- Common end: `{data_meta['common_end']}`
- Aligned daily rows: `{data_meta['aligned_rows']}`
- Signal timing: Microcap weight target for date `t` uses Microcap NAV information through `t-1`.

## Results

Metrics are annual return / daily max drawdown / Sharpe.

| Candidate | Full | Latest 1Y |
|---|---:|---:|
| Fixed `10/15/15/20/40` | {base['ann_return_full']:.2%} / {base['max_dd_full']:.2%} / {base['sharpe_full']:.2f} | {base['ann_return_last_1y']:.2%} / {base['max_dd_last_1y']:.2%} / {base['sharpe_last_1y']:.2f} |
| `dd_3_10_daily` | {daily['ann_return_full']:.2%} / {daily['max_dd_full']:.2%} / {daily['sharpe_full']:.2f} | {daily['ann_return_last_1y']:.2%} / {daily['max_dd_last_1y']:.2%} / {daily['sharpe_last_1y']:.2f} |
| `dd_3_10_month_end` | {practical['ann_return_full']:.2%} / {practical['max_dd_full']:.2%} / {practical['sharpe_full']:.2f} | {practical['ann_return_last_1y']:.2%} / {practical['max_dd_last_1y']:.2%} / {practical['sharpe_last_1y']:.2f} |

## Latest Executed Weights

For `dd_3_10_month_end`, latest Microcap weight is {float(weights.loc[weights['candidate'].eq('dd_3_10_month_end_cost0bps'), 'last_microcap_weight'].iloc[0]):.0%}; latest Sub-B weight is {float(weights.loc[weights['candidate'].eq('dd_3_10_month_end_cost0bps'), 'last_subb_weight'].iloc[0]):.0%}.

## Decision

Decision: `real_subd_five_sleeve_validation_completed`.
"""
    (RUN_DIR / "record.md").write_text(text, encoding="utf-8")


def main() -> None:
    ret_df, data_meta = fetch_returns()
    ret_df.to_csv(RUN_DIR / "aligned_five_sleeve_real_subd_returns.csv", index_label="date", encoding="utf-8-sig")
    summary, weights, navs = H.build_outputs(ret_df)
    wm = H.window_metrics(summary)
    summary.to_csv(RUN_DIR / "scan_summary.csv", index=False, encoding="utf-8-sig")
    wm.to_csv(RUN_DIR / "window_metrics.csv", index=False, encoding="utf-8-sig")
    weights.to_csv(RUN_DIR / "weight_diagnostics.csv", index=False, encoding="utf-8-sig")
    navs.to_csv(RUN_DIR / "nav_outputs.csv", index_label="date", encoding="utf-8-sig")
    write_record(wm, weights, data_meta)
    meta = {
        "phase": "scanned",
        "scan_type": "v76_five_sleeve_real_subd_v16_rebalance_validation",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_branch": git_value(["branch", "--show-current"]),
        "git_commit": git_value(["rev-parse", "HEAD"]),
        "git_status_porcelain": git_value(["status", "--short"]),
        "baseline": H.BASE_WEIGHTS,
        "candidate_grid": {"bands": H.BANDS, "executions": H.EXECUTIONS, "cost_bps": H.COST_BPS},
        "data_snapshot": data_meta,
        "outputs": {
            "record": "record.md",
            "scan_summary": "scan_summary.csv",
            "window_metrics": "window_metrics.csv",
            "weight_diagnostics": "weight_diagnostics.csv",
            "nav_outputs": "nav_outputs.csv",
            "aligned_returns": "aligned_five_sleeve_real_subd_returns.csv",
        },
        "decision": "real_subd_five_sleeve_validation_completed",
    }
    (RUN_DIR / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    with (RUN_DIR / "command_log.txt").open("a", encoding="utf-8") as f:
        f.write("python quant_param_scan_runs\\20260512_v76_five_sleeve_real_subd_v16_rebalance_validation\\run_real_subd_v16_rebalance_validation.py\n")
        f.write(f"completed_at={datetime.now().astimezone().isoformat(timespec='seconds')}\n")
    keep = [
        "fixed_10_15_15_20_40_cost0",
        "dd_3_10_daily_cost0bps",
        "dd_3_10_month_end_cost0bps",
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

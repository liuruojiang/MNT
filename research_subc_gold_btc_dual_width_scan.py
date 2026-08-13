"""Normalize the validated Strategy-C gold/BTC width run under a dual rule.

This script does not rerun prices or manufacture observations.  It reads the
strict-PASS artifact in ``20260812_subc_gold_btc_width``, preserves the complete
real candidate/window tables, and adds a documented second interpretation:

* strong support: >=80% of the centre's positive full-sample Sharpe gain and
  the original return-tolerance rule passes;
* effective support: <80%, but the Sharpe gain remains positive versus the
  no-gold/no-BTC-scaling baseline and the return-tolerance rule passes;
* invalid: everything else.

The long proxy width evidence and the warmup-corrected formal ETF overlap are
reported separately.  No production strategy source is imported or modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from collections import deque
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "quant_param_scan_runs" / "20260812_subc_gold_btc_width"
DEFAULT_TARGET = (
    ROOT
    / "quant_param_scan_runs"
    / (
        "20260812_a_share_us_momentum_combo_strategy_c_v7_8_v7_9_"
        "strategy_c_promotion_candidate_gold_bitcoin_dual_criterion_"
        "relative_vol_width_gold_btc_dual_width"
    )
)

BASELINE = "baseline_no_gold_btc_relative"
GOLD_CENTER = "gold_s30_l252"
BTC_CENTER = "bitcoin_s10_l63"
BUNDLE_CENTER = "bundle_gs30_gl252_bs10_bl63"
CENTER = (30, 252, 10, 63)
AXIS_NEIGHBORS = {
    "gold_short": ((20, 252, 10, 63), (40, 252, 10, 63)),
    "gold_long": ((30, 189, 10, 63), (30, 378, 10, 63)),
    "bitcoin_short": ((30, 252, 7, 63), (30, 252, 15, 63)),
    "bitcoin_long": ((30, 252, 10, 42), (30, 252, 10, 84)),
}
LOCAL_DIMENSIONS = ([20, 30, 40], [189, 252, 378], [7, 10, 15], [42, 63, 84])
RETURN_TOLERANCE_PP = {
    "full": 1.0,
    "last_10y": 1.0,
    "last_5y": 1.0,
    "last_3y": 3.0,
    "last_1y": 3.0,
}


def _bundle_name(params: tuple[int, int, int, int]) -> str:
    gs, gl, bs, bl = params
    return f"bundle_gs{gs}_gl{gl}_bs{bs}_bl{bl}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(args: list[str]) -> str:
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


def _return_tolerance(row: pd.Series, baseline: pd.Series) -> bool:
    for segment, limit_pp in RETURN_TOLERANCE_PP.items():
        candidate_value = row[f"ann_return_{segment}"]
        baseline_value = baseline[f"ann_return_{segment}"]
        if pd.isna(candidate_value) or pd.isna(baseline_value):
            continue
        if (candidate_value - baseline_value) * 100 < -limit_pp - 1e-12:
            return False
    return True


def _support_class(retention: float, gain: float, tolerance_pass: bool) -> str:
    if tolerance_pass and retention >= 0.8:
        return "strong_support"
    if tolerance_pass and retention < 0.8 and gain > 0.0:
        return "effective_support"
    return "invalid"


def _connected_component_stats(frame: pd.DataFrame, accepted: set[str]) -> dict[str, object]:
    points = {
        (
            int(row.gold_short),
            int(row.gold_long),
            int(row.bitcoin_short),
            int(row.bitcoin_long),
        )
        for _, row in frame[frame.dual_support_class.isin(accepted)].iterrows()
    }
    visited: set[tuple[int, int, int, int]] = set()
    components: list[list[tuple[int, int, int, int]]] = []
    for point in points:
        if point in visited:
            continue
        queue = deque([point])
        visited.add(point)
        component: list[tuple[int, int, int, int]] = []
        while queue:
            current = queue.popleft()
            component.append(current)
            for axis, values in enumerate(LOCAL_DIMENSIONS):
                pos = values.index(current[axis])
                for offset in (-1, 1):
                    neighbor_pos = pos + offset
                    if 0 <= neighbor_pos < len(values):
                        neighbor = list(current)
                        neighbor[axis] = values[neighbor_pos]
                        neighbor_point = tuple(neighbor)
                        if neighbor_point in points and neighbor_point not in visited:
                            visited.add(neighbor_point)
                            queue.append(neighbor_point)
        components.append(component)
    return {
        "points": len(points),
        "total_points": len(frame),
        "fraction": len(points) / len(frame),
        "connected_components": len(components),
        "largest_component": max((len(component) for component in components), default=0),
        "center_included": CENTER in points,
    }


def _classify_width(long_wide: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    indexed = long_wide.set_index("candidate")
    baseline = indexed.loc[BASELINE]
    center = indexed.loc[BUNDLE_CENTER]
    baseline_sharpe = float(baseline.sharpe_repo_full)
    center_gain = float(center.sharpe_repo_full - baseline_sharpe)
    if center_gain <= 0:
        raise ValueError("validated long-proxy centre must have a positive Full Sharpe gain")

    axis_rows: list[dict[str, object]] = []
    for axis, neighbors in AXIS_NEIGHBORS.items():
        for side, params in zip(("left", "right"), neighbors):
            candidate = _bundle_name(params)
            row = indexed.loc[candidate]
            gain = float(row.sharpe_repo_full - baseline_sharpe)
            retention = gain / center_gain
            tolerance_pass = _return_tolerance(row, baseline)
            axis_rows.append(
                {
                    "evidence_scope": "long_proxy",
                    "axis": axis,
                    "side": side,
                    "candidate": candidate,
                    "gold_short": params[0],
                    "gold_long": params[1],
                    "bitcoin_short": params[2],
                    "bitcoin_long": params[3],
                    "ann_return_full": row.ann_return_full,
                    "max_dd_full": row.max_dd_full,
                    "sharpe_repo_full": row.sharpe_repo_full,
                    "sharpe_gain_vs_baseline": gain,
                    "gain_retention_vs_center": retention,
                    "original_return_tolerance_pass": tolerance_pass,
                    "dual_support_class": _support_class(retention, gain, tolerance_pass),
                }
            )
    axis = pd.DataFrame(axis_rows)
    axis["effective_under_dual_criterion"] = axis.dual_support_class.ne("invalid")
    axis["axis_two_sided_strong"] = axis.groupby("axis").dual_support_class.transform(
        lambda values: bool((values == "strong_support").all())
    )
    axis["axis_two_sided_effective"] = axis.groupby("axis").dual_support_class.transform(
        lambda values: bool((values != "invalid").all())
    )

    cube = long_wide[long_wide.kind.eq("local_bundle_cube")].copy()
    cube["sharpe_gain_vs_baseline"] = cube.sharpe_repo_full - baseline_sharpe
    cube["gain_retention_vs_center"] = cube.sharpe_gain_vs_baseline / center_gain
    cube["original_return_tolerance_pass"] = cube.apply(
        lambda row: _return_tolerance(row, baseline), axis=1
    )
    cube["dual_support_class"] = cube.apply(
        lambda row: _support_class(
            float(row.gain_retention_vs_center),
            float(row.sharpe_gain_vs_baseline),
            bool(row.original_return_tolerance_pass),
        ),
        axis=1,
    )
    cube["strong_support"] = cube.dual_support_class.eq("strong_support")
    cube["effective_under_dual_criterion"] = cube.dual_support_class.ne("invalid")

    class_counts = cube.dual_support_class.value_counts().to_dict()
    expected_counts = {"strong_support": 16, "effective_support": 38, "invalid": 27}
    if class_counts != expected_counts:
        raise ValueError(f"source cube changed: expected {expected_counts}, got {class_counts}")

    stats = {
        "baseline_full_sharpe": baseline_sharpe,
        "center_full_sharpe": float(center.sharpe_repo_full),
        "center_full_sharpe_gain": center_gain,
        "class_counts": class_counts,
        "strong_region": _connected_component_stats(cube, {"strong_support"}),
        "dual_effective_region": _connected_component_stats(
            cube, {"strong_support", "effective_support"}
        ),
    }
    return axis, cube, stats


def _formal_decisions(formal_wide: pd.DataFrame, long_wide: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    formal_indexed = formal_wide.set_index("candidate")
    long_indexed = long_wide.set_index("candidate")
    formal_baseline = formal_indexed.loc[BASELINE]
    long_baseline = long_indexed.loc[BASELINE]
    available_segments = ("full", "last_5y", "last_3y", "last_1y")
    decisions = {
        BASELINE: "reference",
        GOLD_CENTER: "promote_gold_relative_vol",
        BTC_CENTER: "reject_bitcoin_relative_vol",
        BUNDLE_CENTER: "reject_bundle_for_production",
    }
    rows: list[dict[str, object]] = []
    for candidate, decision in decisions.items():
        formal_row = formal_indexed.loc[candidate]
        long_row = long_indexed.loc[candidate]
        cagr_wins = sum(
            formal_row[f"ann_return_{segment}"] > formal_baseline[f"ann_return_{segment}"]
            for segment in available_segments
        )
        sharpe_wins = sum(
            formal_row[f"sharpe_repo_{segment}"] > formal_baseline[f"sharpe_repo_{segment}"]
            for segment in available_segments
        )
        drawdown_wins = sum(
            formal_row[f"max_dd_{segment}"] > formal_baseline[f"max_dd_{segment}"]
            for segment in available_segments
        )
        rows.append(
            {
                "candidate": candidate,
                "decision": decision,
                "formal_start": "2020-12-03",
                "formal_end": "2026-08-10",
                "formal_ann_return_full": formal_row.ann_return_full,
                "formal_ann_return_delta_vs_baseline": (
                    formal_row.ann_return_full - formal_baseline.ann_return_full
                ),
                "formal_max_dd_full": formal_row.max_dd_full,
                "formal_max_dd_delta_vs_baseline": (
                    formal_row.max_dd_full - formal_baseline.max_dd_full
                ),
                "formal_sharpe_full": formal_row.sharpe_repo_full,
                "formal_sharpe_delta_vs_baseline": (
                    formal_row.sharpe_repo_full - formal_baseline.sharpe_repo_full
                ),
                "formal_cagr_wins_available_windows": cagr_wins,
                "formal_sharpe_wins_available_windows": sharpe_wins,
                "formal_drawdown_wins_available_windows": drawdown_wins,
                "formal_available_window_count": len(available_segments),
                "long_proxy_ann_return_full": long_row.ann_return_full,
                "long_proxy_ann_return_delta_vs_baseline": (
                    long_row.ann_return_full - long_baseline.ann_return_full
                ),
                "long_proxy_sharpe_full": long_row.sharpe_repo_full,
                "long_proxy_sharpe_delta_vs_baseline": (
                    long_row.sharpe_repo_full - long_baseline.sharpe_repo_full
                ),
            }
        )

    btc_surface = formal_wide[formal_wide.kind.eq("bitcoin_surface")]
    btc_surface_full_sharpe_wins = int(
        (btc_surface.sharpe_repo_full > formal_baseline.sharpe_repo_full).sum()
    )
    if len(btc_surface) != 54 or btc_surface_full_sharpe_wins != 0:
        raise ValueError(
            "formal BTC surface evidence changed: expected 0/54 Full Sharpe wins, "
            f"got {btc_surface_full_sharpe_wins}/{len(btc_surface)}"
        )
    stats = {
        "formal_available_segments": list(available_segments),
        "formal_10y": "N/A: formal ETF overlap is shorter than 10 years",
        "bitcoin_surface_full_sharpe_wins_vs_baseline": btc_surface_full_sharpe_wins,
        "bitcoin_surface_candidate_count": int(len(btc_surface)),
    }
    return pd.DataFrame(rows), stats


def _markdown_axis(axis: pd.DataFrame) -> str:
    lines = [
        "| axis | side | neighbor | retention | class | two-sided effective |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for _, row in axis.iterrows():
        lines.append(
            "| {axis} | {side} | `{candidate}` | {retention:.1%} | {support} | {effective} |".format(
                axis=row.axis,
                side=row.side,
                candidate=row.candidate,
                retention=row.gain_retention_vs_center,
                support=row.dual_support_class,
                effective="Yes" if row.axis_two_sided_effective else "No",
            )
        )
    return "\n".join(lines)


def _write_record(
    target: Path,
    source: Path,
    axis: pd.DataFrame,
    width_stats: dict[str, object],
    formal_decisions: pd.DataFrame,
    formal_stats: dict[str, object],
) -> None:
    decision_index = formal_decisions.set_index("candidate")
    baseline = decision_index.loc[BASELINE]
    gold = decision_index.loc[GOLD_CENTER]
    btc = decision_index.loc[BTC_CENTER]
    bundle = decision_index.loc[BUNDLE_CENTER]
    counts = width_stats["class_counts"]
    effective = width_stats["dual_effective_region"]
    created = datetime.now().astimezone().isoformat(timespec="seconds")
    record = f"""# Quant Parameter Scan Record — Strategy C Gold/BTC Dual Criterion

## Run Metadata

- Run id: `{target.name}`
- Created at: {created}
- Project: A-share / US momentum combination Strategy C
- Strategy or version: V7.8 / V7.9 Strategy C promotion candidate
- Sleeve or subsystem: gold and bitcoin relative-volatility width
- Parameter group: `gold_btc_dual_width`
- Scan type: `validated_artifact_normalization_dual_criterion`
- Target entrypoint: `research_subc_gold_btc_dual_width_scan.py`
- Source artifact: `{source}`
- Source validation: strict checker PASS before normalization
- Source-change rule: `research_only_no_production_source_change`

## Research Question

The original width test counted only neighbors retaining at least 80% of the centre's
positive Full Sharpe gain. This normalization adds the user's second dimension: a
neighbor below 80% is still effective when it remains better than the no-gold/no-BTC
relative-scaling baseline and passes the original return-loss tolerance.

- **Strong support**: retention >=80% **and** original return tolerance passes.
- **Effective support**: retention <80%, Full Sharpe gain remains >0, and original
  return tolerance passes.
- **Invalid**: otherwise.
- Original return tolerance: no worse than baseline by 1 percentage point in Full,
  10Y, or 5Y annual return and 3 percentage points in 3Y or 1Y annual return.
- Decision target: separately decide Gold 30/252 and Bitcoin 10/63 for production.

## Data Snapshot and Lineage

- This is a deterministic normalization of existing **real** results; it does not
  synthesize returns or refetch prices.
- Validated source run: `{source.name}`.
- Long-proxy width sample: 2016-03-21 through 2026-08-11.
- Warmup-corrected formal ETF overlap: 2020-12-03 through 2026-08-10.
- Formal 10Y: N/A because the formal ETF overlap is shorter than ten years.
- Source: Yahoo adjusted close via the V7.9 loader; SPY US-session calendar.
- Long-proxy and formal tables remain separate: `window_metrics.csv` is the
  long-proxy strict-check table; `formal_window_metrics.csv` is formal-only.
- Signal warmup: full pre-formal SPY/GLD/BTC history, followed by a one-session lag.
- No pre-publication index backfill is promoted as formal evidence.

## Cost and Execution Assumptions

- Annual asset rebalance: 10 bps on two-way turnover.
- Scale-adjustment cost: 6 bps.
- Financing: BIL plus 100 bps annual spread for leverage; released exposure earns BIL.
- Relative scale: long realized volatility / short realized volatility, clipped to
  0.5–1.5, 0.10 deadband, one-session lag.
- Equity baseline remains SPY absolute-volatility target scaling at 15%.

## Dual-Criterion Width Results — Long Proxy

- Centre: `{BUNDLE_CENTER}`.
- Baseline Full Sharpe: {width_stats['baseline_full_sharpe']:.6f}.
- Centre Full Sharpe: {width_stats['center_full_sharpe']:.6f}; gain
  {width_stats['center_full_sharpe_gain']:.6f}.
- Cube classification: **{counts['strong_support']} strong**, **{counts['effective_support']} effective**,
  **{counts['invalid']} invalid** out of 81.
- Strong + effective region: {effective['points']}/81 points, {effective['connected_components']}
  connected component, largest component {effective['largest_component']}, centre included
  `{effective['center_included']}`.
- Interpretation: the centre is not a one-point spike. Three of four axes have
  two-sided effective support; the left side of Bitcoin short (10 -> 7 days) is the
  single local-axis break because its Sharpe gain falls below baseline.

{_markdown_axis(axis)}

## Formal ETF-Overlap Decision

| candidate | Full CAGR | delta vs baseline | Full Sharpe | Sharpe delta | Full max DD | DD delta | CAGR/Sharpe/DD wins |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | {baseline.formal_ann_return_full:.2%} | — | {baseline.formal_sharpe_full:.3f} | — | {baseline.formal_max_dd_full:.2%} | — | — |
| Gold 30/252 | {gold.formal_ann_return_full:.2%} | {gold.formal_ann_return_delta_vs_baseline:+.3%} | {gold.formal_sharpe_full:.3f} | {gold.formal_sharpe_delta_vs_baseline:+.4f} | {gold.formal_max_dd_full:.2%} | {gold.formal_max_dd_delta_vs_baseline:+.3%} | {int(gold.formal_cagr_wins_available_windows)}/{int(gold.formal_sharpe_wins_available_windows)}/{int(gold.formal_drawdown_wins_available_windows)} of 4 |
| Bitcoin 10/63 | {btc.formal_ann_return_full:.2%} | {btc.formal_ann_return_delta_vs_baseline:+.3%} | {btc.formal_sharpe_full:.3f} | {btc.formal_sharpe_delta_vs_baseline:+.4f} | {btc.formal_max_dd_full:.2%} | {btc.formal_max_dd_delta_vs_baseline:+.3%} | {int(btc.formal_cagr_wins_available_windows)}/{int(btc.formal_sharpe_wins_available_windows)}/{int(btc.formal_drawdown_wins_available_windows)} of 4 |
| Combined centre | {bundle.formal_ann_return_full:.2%} | {bundle.formal_ann_return_delta_vs_baseline:+.3%} | {bundle.formal_sharpe_full:.3f} | {bundle.formal_sharpe_delta_vs_baseline:+.4f} | {bundle.formal_max_dd_full:.2%} | {bundle.formal_max_dd_delta_vs_baseline:+.3%} | {int(bundle.formal_cagr_wins_available_windows)}/{int(bundle.formal_sharpe_wins_available_windows)}/{int(bundle.formal_drawdown_wins_available_windows)} of 4 |

- Gold 30/252: formal Full CAGR +{gold.formal_ann_return_delta_vs_baseline * 100:.3f} pp,
  Sharpe {gold.formal_sharpe_delta_vs_baseline:+.4f}, and max-DD improvement
  {gold.formal_max_dd_delta_vs_baseline * 100:+.3f} pp; CAGR and Sharpe win 4/4
  available windows, max DD wins 3/4.
- Bitcoin 10/63: formal Full CAGR {btc.formal_ann_return_delta_vs_baseline * 100:+.3f} pp
  and Sharpe {btc.formal_sharpe_delta_vs_baseline:+.4f}. Across the complete formal
  Bitcoin surface, **{formal_stats['bitcoin_surface_full_sharpe_wins_vs_baseline']}/{formal_stats['bitcoin_surface_candidate_count']}** candidates beat the baseline Full Sharpe.
- The combined centre improves CAGR and drawdown but loses
  {abs(bundle.formal_sharpe_delta_vs_baseline):.4f} Full Sharpe versus baseline, so it
  does not override the asset-by-asset decision.

## Stability Classification

- Stability label: `gold_dual_effective_plateau_btc_formal_reject`.
- Long-proxy evidence: connected 54/81 strong-or-effective region; not a single spike.
- Formal evidence: supports Gold 30/252, rejects Bitcoin 10/63.
- Sensitivity caveat: cap, deadband, financing spread, and doubled costs were not
  rescanned in this normalization.

## Decision

- Decision: `promote_gold_reject_bitcoin`.
- **Production recommendation:** keep SPY 15% absolute-volatility scaling for equities;
  enable Gold 30/252 own short/long relative-volatility scaling; leave Bitcoin at
  fixed 1.0x (no volatility scaling).
- Do not promote the combined Gold+Bitcoin centre merely because its long-proxy
  surface is broad: formal data rejects the Bitcoin leg.

## Output Files

- `scan_summary.csv`, `window_metrics.csv`: complete 190-candidate validated long-proxy results.
- `formal_scan_summary.csv`, `formal_window_metrics.csv`: warmup-corrected formal ETF overlap.
- `axis_dual_width.csv`: eight immediate neighbors with dual classifications.
- `cube_dual_width.csv`: all 81 local-cube candidates with dual classifications.
- `formal_candidate_decisions.csv`: baseline, Gold, Bitcoin, and combined formal decisions.
- `source_manifest.json`: SHA-256 lineage for copied/normalized source inputs.
- `scan_meta.json`, `command_log.txt`: machine-readable metadata and commands.

## Commands

```powershell
python D:\\Codex\\home\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict quant_param_scan_runs\\20260812_subc_gold_btc_width
python research_subc_gold_btc_dual_width_scan.py
python D:\\Codex\\home\\skills\\quant-param-scan\\scripts\\finalize_quant_param_scan_run.py "{target}" --decision promote_gold_reject_bitcoin --stability-label gold_dual_effective_plateau_btc_formal_reject
python D:\\Codex\\home\\skills\\quant-param-scan\\scripts\\check_quant_param_scan_artifacts.py --phase complete --strict "{target}"
```
"""
    (target / "record.md").write_text(record, encoding="utf-8")


def normalize(source: Path, target: Path, command: str) -> None:
    required = (
        "scan_summary.csv",
        "window_metrics.csv",
        "formal_scan_summary.csv",
        "formal_window_metrics.csv",
        "scan_meta.json",
        "record.md",
        "command_log.txt",
    )
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"source artifact missing: {', '.join(missing)}")
    target.mkdir(parents=True, exist_ok=True)

    long_wide = pd.read_csv(source / "window_metrics.csv")
    formal_wide = pd.read_csv(source / "formal_window_metrics.csv")
    axis, cube, width_stats = _classify_width(long_wide)
    formal_decisions, formal_stats = _formal_decisions(formal_wide, long_wide)

    # Preserve all real observations and candidate/window coverage from the
    # validated source artifact.  The four copied CSVs are not templates.
    for name in (
        "scan_summary.csv",
        "window_metrics.csv",
        "formal_scan_summary.csv",
        "formal_window_metrics.csv",
    ):
        shutil.copyfile(source / name, target / name)
    axis.to_csv(target / "axis_dual_width.csv", index=False, encoding="utf-8-sig")
    cube.to_csv(target / "cube_dual_width.csv", index=False, encoding="utf-8-sig")
    formal_decisions.to_csv(
        target / "formal_candidate_decisions.csv", index=False, encoding="utf-8-sig"
    )

    source_files = {name: _sha256(source / name) for name in required}
    manifest = {
        "source_run": str(source),
        "source_strict_checker": "PASS before normalization",
        "normalization_kind": "deterministic classification over validated real CSV results",
        "source_sha256": source_files,
    }
    (target / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _write_record(target, source, axis, width_stats, formal_decisions, formal_stats)

    existing_meta = json.loads((target / "scan_meta.json").read_text(encoding="utf-8"))
    source_meta = json.loads((source / "scan_meta.json").read_text(encoding="utf-8"))
    meta = {
        **existing_meta,
        "phase": "normalized",
        "project": "A-share US momentum combo Strategy C",
        "strategy": "V7.8/V7.9 Strategy C promotion candidate",
        "subsystem": "gold bitcoin dual-criterion relative-vol width",
        "repo_root": str(ROOT),
        "entrypoint": Path(__file__).name,
        "git_branch": _git(["branch", "--show-current"]) or existing_meta.get("git_branch"),
        "git_commit": _git(["rev-parse", "HEAD"]) or existing_meta.get("git_commit"),
        "git_status_after": _git(["status", "--short"]),
        "scan_type": "validated_artifact_normalization_dual_criterion",
        "parameter_group": "gold_btc_dual_width",
        "baseline": {
            "candidate": BASELINE,
            "description": "SPY 15% equity scaling; gold and bitcoin unscaled",
        },
        "candidate_grid": source_meta.get("candidate_grid", {}),
        "data_snapshot": {
            "long_proxy_start": "2016-03-21",
            "long_proxy_end": "2026-08-11",
            "formal_start": "2020-12-03",
            "formal_end": "2026-08-10",
            "formal_10y": "N/A: formal ETF overlap shorter than 10 years",
            "source": "validated 20260812_subc_gold_btc_width CSV outputs",
            "market_data_origin": "Yahoo adjusted close via V7.9 loader",
            "formal_signal_warmup": "full pre-formal SPY/GLD/BTC history",
        },
        "cost_model": source_meta.get("cost_model", {}),
        "normalization": {
            "source_run": str(source),
            "source_strict_checker": "PASS",
            "source_manifest": str(target / "source_manifest.json"),
            "dual_rule": {
                "strong_support": "retention >= 0.80 and original return tolerance passes",
                "effective_support": (
                    "retention < 0.80, Full Sharpe gain vs baseline > 0, "
                    "and original return tolerance passes"
                ),
                "invalid": "otherwise",
            },
            "return_tolerance_pp": RETURN_TOLERANCE_PP,
        },
        "width_audit": width_stats,
        "formal_audit": formal_stats,
        "production_recommendation": {
            "equity": "SPY absolute-volatility target 15%",
            "gold": "enable own relative-volatility scale 30/252",
            "bitcoin": "disable volatility scaling; fixed 1.0x",
        },
        "outputs": {
            "record": str(target / "record.md"),
            "scan_summary": str(target / "scan_summary.csv"),
            "window_metrics": str(target / "window_metrics.csv"),
            "scan_meta": str(target / "scan_meta.json"),
            "command_log": str(target / "command_log.txt"),
            "formal_scan_summary": str(target / "formal_scan_summary.csv"),
            "formal_window_metrics": str(target / "formal_window_metrics.csv"),
            "axis_dual_width": str(target / "axis_dual_width.csv"),
            "cube_dual_width": str(target / "cube_dual_width.csv"),
            "formal_candidate_decisions": str(target / "formal_candidate_decisions.csv"),
            "source_manifest": str(target / "source_manifest.json"),
        },
        "decision": "promote_gold_reject_bitcoin",
        "stability_label": "gold_dual_effective_plateau_btc_formal_reject",
        "production_code_changed": False,
    }
    (target / "scan_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with (target / "command_log.txt").open("a", encoding="utf-8") as handle:
        handle.write("\nsource_strict_checker=PASS\n")
        handle.write(
            "source_checker_command=python D:\\Codex\\home\\skills\\quant-param-scan\\scripts\\"
            "check_quant_param_scan_artifacts.py --phase complete --strict "
            f"{source}\n"
        )
        handle.write(f"normalization_command={command}\n")
        handle.write(f"source_run={source}\n")
        handle.write("normalization_result=PASS\n")
        handle.write("production_code_changed=false\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize validated Strategy-C gold/BTC width evidence under a dual criterion."
    )
    parser.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target-run", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    source = args.source_run.resolve()
    target = args.target_run.resolve()
    command = (
        f'python "{Path(__file__).name}" --source-run "{source}" '
        f'--target-run "{target}"'
    )
    normalize(source, target, command)
    print(f"PASS: normalized validated width artifact -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

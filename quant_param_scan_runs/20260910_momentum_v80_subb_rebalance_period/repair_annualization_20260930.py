"""Repair only the dated-return annualization in three frozen 2026-09-10 scans.

The saved daily return paths, positions, fees and BIL-based borrowing assumptions
are intentionally reused. This is not a new strategy or financing backtest.
"""

import argparse
import hashlib
import importlib.util
import json
import pickle
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / "mnt_bot V 8.0 plus.py"
US_TRADING_DAYS = 252
DATE = "2026-09-30"

SCANS = (
    dict(folder="20260910_momentum_v80_subb_rebalance_period", kind="cadence",
         input="outputs/v80_adversarial_fixes_20260907/new_replay_inputs.pkl",
         frame=2, main="scan_summary.csv", baseline="weekly"),
    dict(folder="20260910_momentum_v80_subb_correlation_allocation", kind="correlation",
         input="outputs/v80_external_review_20260907/new_replay_inputs.pkl",
         frame=2, main="all_sleeve_metrics.csv", baseline="inverse_vol"),
    dict(folder="20260910_momentum_v80_subc_joint_risk", kind="joint_risk",
         input="outputs/v80_external_review_20260907/new_replay_inputs.pkl",
         frame=3, main="scan_summary.csv", baseline="current_sleeves"),
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_v80():
    spec = importlib.util.spec_from_file_location("v80_annualization_repair", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def require_close(actual, expected, label, tol=1e-10):
    if not np.isfinite(actual) or abs(float(actual) - float(expected)) > tol:
        raise AssertionError(f"{label}: {actual!r} != {expected!r}")


def load_scan(cfg):
    folder = HERE.parent / cfg["folder"]
    meta = json.loads((folder / "scan_meta.json").read_text(encoding="utf-8"))
    input_path = ROOT / cfg["input"]
    input_hash = sha256(input_path)
    assert input_hash == meta["data_snapshot"]["sha256"], (cfg["folder"], "frozen input hash")
    frozen = pickle.loads(input_path.read_bytes())
    close = frozen["frames"][cfg["frame"]]
    header = [0, 1] if cfg["kind"] == "correlation" else 0
    daily = pd.read_csv(folder / "daily_returns.csv", index_col=0, header=header, parse_dates=True)
    assert daily.index.is_monotonic_increasing and daily.index.is_unique
    assert daily.index[-1] == pd.Timestamp("2026-09-04")
    source_before = close.index[close.index < daily.index[0]]
    assert len(source_before) and source_before[-1] < daily.index[0]
    first_anchor = pd.Timestamp(source_before[-1])
    summary = pd.read_csv(folder / cfg["main"], keep_default_na=False)
    return folder, meta, daily, first_anchor, summary, input_hash


def compute(cfg, module, verify=False, preflight=False):
    folder, meta, daily, first_anchor, summary, input_hash = load_scan(cfg)
    original = summary.copy(deep=True)
    changes = []
    valid = pd.to_numeric(summary["ann_return"], errors="coerce").notna()
    summary["ann_return"] = summary["ann_return"].astype(object)
    summary["return_delta_pp"] = summary["return_delta_pp"].astype(object)

    for ix in summary.index[valid]:
        row = original.loc[ix]
        key = (row["candidate"], row["sleeve"]) if cfg["kind"] == "correlation" else row["candidate"]
        full = daily[key].dropna()
        period = full.loc[pd.Timestamp(row["start"]):pd.Timestamp(row["end"])]
        assert len(period) == int(row["rows"]), (cfg["folder"], row["candidate"], row["segment"])
        assert period.index[-1] == full.index[-1]
        old_span = (period.index[-1] - period.index[0]).days
        assert old_span > 0
        old_formula = float((1 + period).prod() ** (365.25 / old_span) - 1)
        old_value = float(row["ann_return"])
        if not verify:
            require_close(old_formula, old_value, f'{cfg["folder"]} old CAGR {ix}')
        metric = module.calc_daily_metrics(period, 0.0, US_TRADING_DAYS,
                                           history_returns=full, first_period_start=first_anchor)
        assert metric is not None
        for column, name, scale in (("ann_vol", "vol", 100), ("sharpe_repo", "sharpe", 1),
                                    ("max_dd", "max_dd", 100)):
            require_close(float(row[column]), metric[name] / scale,
                          f'{cfg["folder"]} unchanged {column} {ix}')
        preceding = full.index[full.index < period.index[0]]
        anchor = pd.Timestamp(preceding[-1]) if len(preceding) else first_anchor
        assert metric["years"] == (period.index[-1] - anchor).days / 365.25
        corrected = metric["annual"] / 100
        if verify:
            require_close(old_value, corrected, f'{cfg["folder"]} corrected CAGR {ix}')
        summary.at[ix, "ann_return"] = corrected
        changes.append(dict(candidate=row["candidate"], sleeve=row.get("sleeve", ""),
                            segment=row["segment"], old=old_value, new=corrected,
                            change_pp=100 * (corrected - old_value),
                            anchor=str(anchor.date()), rows=len(period)))

    if cfg["kind"] == "joint_risk":
        assert len(summary) == 25 and valid.sum() == 20
    else:
        assert valid.all()
    if cfg["kind"] == "correlation":
        baseline = summary[summary["candidate"] == cfg["baseline"]].set_index(["sleeve", "segment"])
        for ix in summary.index[valid]:
            row = summary.loc[ix]
            summary.at[ix, "return_delta_pp"] = 100 * (
                float(row["ann_return"]) - float(baseline.loc[(row["sleeve"], row["segment"]), "ann_return"]))
    else:
        baseline = summary[summary["candidate"] == cfg["baseline"]].set_index("segment")
        for ix in summary.index[valid]:
            row = summary.loc[ix]
            summary.at[ix, "return_delta_pp"] = 100 * (
                float(row["ann_return"]) - float(baseline.loc[row["segment"], "ann_return"]))

    if cfg["kind"] == "correlation":
        public = summary[summary["sleeve"] == "B_combined"].copy().reset_index(drop=True)
    else:
        public = summary
    wide = pd.read_csv(folder / "window_metrics.csv", keep_default_na=False)
    for ix in wide.index:
        candidate = wide.at[ix, "candidate"]
        for segment in ("full", "last_10y", "last_5y", "last_3y", "last_1y"):
            match = public[(public["candidate"] == candidate) & (public["segment"] == segment)]
            assert len(match) == 1
            old_wide = wide.at[ix, f"ann_return_{segment}"]
            old_public = original[(original["candidate"] == candidate) &
                                  (original["segment"] == segment)]
            if cfg["kind"] == "correlation":
                old_public = old_public[old_public["sleeve"] == "B_combined"]
            assert len(old_public) == 1
            old_public_value = old_public.iloc[0]["ann_return"]
            if pd.notna(pd.to_numeric(old_public_value, errors="coerce")):
                require_close(float(old_wide), float(old_public_value),
                              f'{cfg["folder"]} old wide {candidate} {segment}')
            else:
                assert old_wide == old_public_value == "N/A"
            wide.at[ix, f"ann_return_{segment}"] = match.iloc[0]["ann_return"]

    if cfg["kind"] == "correlation":
        old_public_file = pd.read_csv(folder / "scan_summary.csv", keep_default_na=False)
        for a, b in zip(old_public_file.itertuples(index=False),
                        original[original["sleeve"] == "B_combined"].itertuples(index=False)):
            assert a.candidate == b.candidate and a.segment == b.segment
            require_close(a.ann_return, b.ann_return, "old correlation public projection")

    if verify:
        assert "annualization_repair" in meta
        print(cfg["folder"], "VERIFY", len(changes), "rows", "first anchor", first_anchor.date())
        return

    if preflight:
        print(cfg["folder"], "PREFLIGHT", len(changes), "old-formula rows matched",
              "first anchor", first_anchor.date(), "max change pp",
              max(abs(x["change_pp"]) for x in changes))
        return

    files = [cfg["main"], "scan_summary.csv", "window_metrics.csv", "scan_meta.json", "record.md"]
    files = list(dict.fromkeys(files))
    backup = folder / "annualization_backup_20260930"
    if backup.exists():
        raise FileExistsError(f"Preserving existing backup; refusing a second edit: {backup}")
    backup.mkdir()
    original_hashes = {}
    for name in files:
        src = folder / name
        shutil.copy2(src, backup / name)
        assert sha256(src) == sha256(backup / name)
        original_hashes[name] = sha256(src)
    (backup / "manifest.json").write_text(json.dumps(original_hashes, indent=2), encoding="utf-8")

    if cfg["kind"] == "correlation":
        summary.to_csv(folder / cfg["main"], index=False)
        public.to_csv(folder / "scan_summary.csv", index=False)
    else:
        summary.to_csv(folder / "scan_summary.csv", index=False)
    wide.to_csv(folder / "window_metrics.csv", index=False)

    change_pp = [abs(x["change_pp"]) for x in changes]
    repair = {
        "date": DATE,
        "scope": "annual_return and return_delta_pp only; window_metrics annual columns refreshed",
        "basis": "saved frozen daily_returns.csv; no account, return, fee, signal or position rerun",
        "unchanged_financing": "original BIL adjusted-price-return plus 100 bp debt proxy; negative debt-charge days remain in the saved daily path",
        "first_return_anchor": str(first_anchor.date()),
        "affected_rows": len(changes),
        "max_abs_annualization_change_pp": max(change_pp),
        "old_formula_baseline_parity": "all valid rows matched old first-to-last dated-return denominator within 1e-10 absolute return",
        "corrected_formula": "compound all included returns over calendar span from preceding source close to final return date",
        "daily_returns_sha256": sha256(folder / "daily_returns.csv"),
        "frozen_input_sha256": input_hash,
        "metric_source_sha256_at_repair": sha256(SOURCE),
        "backup": str(backup.relative_to(ROOT)),
    }
    meta["annualization_repair"] = repair
    meta.setdefault("warnings", []).append(
        "2026-09-30: annualization corrected from saved daily returns; original BIL-based financing and candidate decisions are not re-certified")
    (folder / "scan_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    note = (
        f"> **2026-09-30 年化更正**：本目录年化表已从冻结 `daily_returns.csv` 重算，"
        f"首笔收益由真实前收盘 {first_anchor.date()} 起计；共 {len(changes)} 个有效窗口，"
        f"最大绝对修正 {max(change_pp):.6f} 个百分点。下文原叙述中的年化数字按新 CSV 为准。"
        "原账户收益、成交费、BIL 价格收益加 100bp 的融资假设均未重跑；"
        "融资缺陷仍在，不能据此确认新融资口径下的候选结论。"
        "原表与说明见 `annualization_backup_20260930/`。\n\n"
    )
    record = (folder / "record.md").read_text(encoding="utf-8")
    if not record.startswith("# "):
        raise AssertionError(f"Unexpected record heading: {folder}")
    first_line, rest = record.split("\n", 1)
    (folder / "record.md").write_text(first_line + "\n\n" + note + rest, encoding="utf-8")

    output = dict(scan=cfg["folder"], affected_rows=len(changes),
                  first_return=str(daily.index[0].date()), first_anchor=str(first_anchor.date()),
                  max_abs_change_pp=max(change_pp),
                  largest_change=max(changes, key=lambda x: abs(x["change_pp"])),
                  original_hashes=original_hashes,
                  repaired_hashes={name: sha256(folder / name) for name in files},
                  daily_returns_sha256=repair["daily_returns_sha256"],
                  frozen_input_sha256=input_hash)
    (folder / "annualization_repair_20260930.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("scan", "affected_rows", "first_anchor",
                                             "max_abs_change_pp", "largest_change")}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if args.verify and args.preflight:
        parser.error("--verify and --preflight are mutually exclusive")
    module = load_v80()
    for cfg in SCANS:
        compute(cfg, module, verify=args.verify, preflight=args.preflight)


if __name__ == "__main__":
    main()

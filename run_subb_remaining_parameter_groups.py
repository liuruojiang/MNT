from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

import analyze_subb_parameter_stability as stability


ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
GROUPS = [
    ("turnover_cost", DOCS / "subb_v75_v76_parameter_stability_turnover_cost_20260507"),
    ("volreg_windows", DOCS / "subb_v75_v76_parameter_stability_volreg_windows_20260507"),
    ("vol_weight", DOCS / "subb_v75_v76_parameter_stability_vol_weight_20260507"),
    ("ema_volscale", DOCS / "subb_v75_v76_parameter_stability_ema_volscale_20260507"),
]


def expected_rows(group: str) -> dict[str, int]:
    mod = stability.load_module(ROOT / "mnt_bot V 7.6 plus.py", f"expected_{group}")
    default = stability.default_candidate(mod)
    candidates, _, _ = stability.candidate_group(default, group)
    candidate_count = len(candidates)
    return {
        "candidates_per_version": candidate_count,
        "summary_rows": candidate_count * 2 * (len(stability.WINDOWS) + 1),
        "rank_rows": candidate_count * 2,
        "compare_rows": candidate_count,
    }


def csv_count(path: Path) -> int | None:
    if not path.exists():
        return None
    return int(len(pd.read_csv(path)))


def run_group(group: str, out_dir: Path) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "cloud_run.log"
    err_path = out_dir / "cloud_run.err.log"
    expected = expected_rows(group)
    cmd = [
        sys.executable,
        str(ROOT / "analyze_subb_parameter_stability.py"),
        "--group",
        group,
        "--out-dir",
        str(out_dir),
    ]
    started_at = datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as stdout, err_path.open("a", encoding="utf-8") as stderr:
        proc = subprocess.run(cmd, cwd=ROOT, stdout=stdout, stderr=stderr, text=True)
    finished_at = datetime.now().isoformat(timespec="seconds")
    observed = {
        "summary_rows": csv_count(out_dir / "summary.csv"),
        "rank_rows": csv_count(out_dir / "rank.csv"),
        "compare_rows": csv_count(out_dir / "v75_v76_compare.csv"),
        "partial_summary_rows": csv_count(out_dir / "partial_summary.csv"),
    }
    ok = proc.returncode == 0 and all(
        observed.get(key) == expected[key]
        for key in ("summary_rows", "rank_rows", "compare_rows")
    )
    return {
        "group": group,
        "out_dir": str(out_dir.relative_to(ROOT)),
        "started_at": started_at,
        "finished_at": finished_at,
        "returncode": proc.returncode,
        "expected": expected,
        "observed": observed,
        "ok": ok,
        "log": str(log_path.relative_to(ROOT)),
        "err_log": str(err_path.relative_to(ROOT)),
    }


def main() -> int:
    manifest = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "groups": [],
        "note": "Runs remaining Sub-B numeric parameter groups without waiting for user confirmation.",
    }
    for group, out_dir in GROUPS:
        result = run_group(group, out_dir)
        manifest["groups"].append(result)
        manifest_path = DOCS / "subb_v75_v76_parameter_stability_remaining_cloud_manifest_20260507.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if not result["ok"]:
            return int(result["returncode"] or 1)
    manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
    manifest_path = DOCS / "subb_v75_v76_parameter_stability_remaining_cloud_manifest_20260507.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

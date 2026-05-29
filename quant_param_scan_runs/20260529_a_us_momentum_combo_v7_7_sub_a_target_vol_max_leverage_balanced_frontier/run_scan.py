from __future__ import annotations

import importlib.util
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parent
ROOT = RUN_DIR.parents[1]
BASE_RUN = ROOT / "quant_param_scan_runs" / "20260529_a_us_momentum_combo_v7_7_sub_a_target_vol_max_leverage"
BASE_SCRIPT = BASE_RUN / "run_scan.py"


def main() -> None:
    spec = importlib.util.spec_from_file_location("suba_tv_lev_base_scan", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {BASE_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod.RUN_DIR = RUN_DIR
    mod.TARGET_VOLS = [0.20, 0.225, 0.25, 0.275, 0.30]
    mod.MAX_LEVS = [1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.40, 1.50]
    mod.main()


if __name__ == "__main__":
    main()

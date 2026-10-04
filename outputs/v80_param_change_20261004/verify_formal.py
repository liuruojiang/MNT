"""Rebuild the changed V8.0 production path on the certified L1 input freeze."""

import hashlib
import importlib.util
import json
import pickle
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import requests


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
L1 = ROOT / "outputs/v80_recert_20260926/l1_final"
SOURCE = ROOT / "mnt_bot V 8.0 plus.py"
FACTOR = ROOT / "quant_param_scan_runs/20261004_v80_user_four_parameter_factorial"
EXPECTED_L1 = "182a5c54d5c81699d8e93038695a76febd15312aa48b5864e47a46318eeba00f"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((L1 / "fetch_status.json").read_text(encoding="utf-8"))
    amount_manifest = json.loads((L1 / "suba_amount_status.json").read_text(encoding="utf-8"))
    assert sha(L1 / "formal_inputs.pkl") == EXPECTED_L1 == manifest["input_sha256"]
    assert sha(L1 / "suba_amount.pkl") == amount_manifest["input_sha256"]
    with (L1 / "formal_inputs.pkl").open("rb") as file:
        inputs = pickle.load(file)
    with (L1 / "suba_amount.pkl").open("rb") as file:
        volume = pickle.load(file)
    spec = importlib.util.spec_from_file_location("v80_promoted_four", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert (module.CN_DK_BIAS_N, module.CN_DK_MOM_DAY,
            module.SUBB_V75_EMA_HALF_LIFE, module.SUBB_V75_EMA_ABS_THRESHOLD,
            module._v80_b78_US_ROT_ABS_THRESHOLD,
            module._v80_b78_SUBB_V75_EMA_HALF_LIFE,
            module._v80_b78_SUBB_V75_EMA_ABS_THRESHOLD) == (45, 20, 70, .15, 0., 70, .15)
    bot = module.CombinedStrategyV80()
    bot._us_open = inputs["us_open"]
    clock = pd.Timestamp(manifest["started_beijing"]).to_pydatetime()

    def frozen_volume(expected_date=None):
        expected = pd.Timestamp(expected_date).normalize() if expected_date is not None else None
        if expected is not None and expected > volume["feature"].index[-1]:
            raise RuntimeError("frozen volume stale")
        return (volume["signal"].loc[:expected].copy(),
                volume["feature"].loc[:expected].copy()) if expected is not None else (
                    volume["signal"].copy(), volume["feature"].copy())

    with patch.object(module, "beijing_now", return_value=clock), \
         patch.object(module, "_load_suba_volume_signal", side_effect=frozen_volume), \
         patch.object(requests.sessions.Session, "request", side_effect=RuntimeError("network forbidden")):
        results = bot._cached_run_strategies(*inputs["frames"],
            allow_unresolved_suba_volume=False, strict_subb_open_execution=True)
        subc = module._compute_subc_production_snapshot(inputs["frames"][3],
            results[4], results[5], us_open=inputs["us_open"], strict_open_execution=True)
        c_ret = subc["scaled_return"] if module.PROD_VS_ENABLED else subc["raw_return"]
        daily = module._v80_performance_daily_returns(results[0]["return"],
            results[1]["return"], results[2], c_ret)
        anchors = module._performance_initial_period_anchors(daily, *inputs["frames"])
        windows = module._performance_standard_window_rows(daily,
            end_date=pd.Timestamp("2026-09-25"), first_period_starts=anchors)

    old_daily = pickle.load((ROOT / "outputs/v80_recert_20260926/l2/formal_daily_returns.pkl").open("rb"))
    comparison = {}
    for key in ("Sub-A", "Sub-C"):
        assert daily[key].index.equals(old_daily[key].index)
        comparison[key + "_unchanged_max_abs"] = float((daily[key] - old_daily[key]).abs().max())
        assert comparison[key + "_unchanged_max_abs"] < 1e-12
    candidate = {
        "Sub-A-DK": FACTOR / "adk_ma45.csv.gz",
        "B7.8": FACTOR / "B78/hl070_e15_a00.csv.gz",
        "B7.9": FACTOR / "B79/hl070_e15_a00.csv.gz",
    }
    for key, path in candidate.items():
        frame = pd.read_csv(path, parse_dates=["date"]).set_index("date")
        actual = daily[key].reindex(frame.index).loc["2020-12-03":]
        expected = frame["return"].loc[actual.index]
        assert actual.notna().all() and expected.notna().all()
        comparison[key + "_candidate_2020_max_abs"] = float((actual - expected).abs().max())
        assert comparison[key + "_candidate_2020_max_abs"] < 1e-12
    rows = []
    for item in windows:
        for key, data in item["metrics"].items():
            rows.append({"window": item["window"], "sleeve": key,
                         "annual_pct": data.get("annual"), "max_dd_pct": data.get("max_dd"),
                         "reason": data.get("reason"), "start": data.get("start"),
                         "end": data.get("end")})
    pd.DataFrame(rows).to_csv(HERE / "formal_window_metrics.csv", index=False, encoding="utf-8-sig")
    status = {"stage": "complete", "source_sha256": sha(SOURCE),
        "formal_inputs_sha256": EXPECTED_L1, "amount_sha256": sha(L1 / "suba_amount.pkl"),
        "entrypoint": "CombinedStrategyV80._cached_run_strategies",
        "strict_subb_open_execution": True, "network_allowed": False,
        "clock_beijing": str(clock), "date_ranges": {key: [str(value.index.min()), str(value.index.max())]
            for key, value in daily.items()}, "comparisons": comparison}
    (HERE / "verification.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

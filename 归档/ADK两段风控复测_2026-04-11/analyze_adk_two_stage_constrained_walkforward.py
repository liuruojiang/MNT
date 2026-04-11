import importlib.util
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
SCAN_SCRIPT = HERE / "analyze_adk_two_stage_constrained.py"
SUMMARY_CSV = HERE / "adk_two_stage_constrained_walkforward_summary.csv"
FOLDS_CSV = HERE / "adk_two_stage_constrained_walkforward_folds.csv"


def _load_script_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metrics_for_slice(mod, ret: pd.Series):
    ret = ret.dropna()
    if len(ret) < 40:
        return None
    return mod.calc_daily_metrics(ret, mod.CN_RF_DAILY, mod.CN_DK_TRADING_DAYS)


def _plain_series(s: pd.Series) -> pd.Series:
    out = s.copy()
    out.attrs = {}
    return out


def _build_folds(index: pd.DatetimeIndex):
    years = sorted(index.year.unique())
    folds = []
    for test_start_year in years:
        train_start_year = test_start_year - 5
        train_end_year = test_start_year - 1
        test_end_year = test_start_year + 1
        train_mask = (index.year >= train_start_year) & (index.year <= train_end_year)
        test_mask = (index.year >= test_start_year) & (index.year <= test_end_year)
        if train_mask.sum() < 252 * 3 or test_mask.sum() < 252:
            continue
        folds.append(
            {
                "train_years": f"{train_start_year}-{train_end_year}",
                "test_years": f"{test_start_year}-{test_end_year}",
                "train_mask": train_mask,
                "test_mask": test_mask,
            }
        )
    return folds


def main():
    scan = _load_script_module(SCAN_SCRIPT, "adk_two_stage_constrained_scan_mod")
    mod = scan._load_module(scan.BASE_SCRIPT, "adk_two_stage_constrained_base_mod")
    cn_close, cn_dk_close = scan._load_local_cn_data(mod, scan.CN_CSV)
    raw = mod.run_dk_strategy(cn_close.copy(), cn_dk_close.copy())

    candidates = {
        "single_stage_15_0p5_8": mod.apply_dk_drawdown_risk_gate(
            raw.copy(),
            enter=mod.CN_DK_RISK_GATE_ENTER,
            scale_defense=mod.CN_DK_RISK_GATE_DEFENSE_SCALE,
            exit_value=mod.CN_DK_RISK_GATE_EXIT,
            cooldown_days=mod.CN_DK_RISK_GATE_COOLDOWN_DAYS,
        ),
        "two_stage_best_calmar": scan._apply_two_stage_dd_gate(
            mod,
            raw.copy(),
            stage1={"enter": 0.15, "exit": 0.10, "scale": 0.70},
            stage2={"enter": 0.22, "exit": 0.14, "scale": 0.30},
        ),
        "two_stage_best_balanced": scan._apply_two_stage_dd_gate(
            mod,
            raw.copy(),
            stage1={"enter": 0.15, "exit": 0.10, "scale": 0.70},
            stage2={"enter": 0.20, "exit": 0.14, "scale": 0.40},
        ),
    }

    index = raw.index
    folds = _build_folds(index)
    fold_rows = []
    stitched_returns = {name: [] for name in candidates}

    for fold_id, fold in enumerate(folds, start=1):
        test_idx = index[fold["test_mask"]]
        for name, result in candidates.items():
            test_ret = _plain_series(result.loc[test_idx, "return"])
            test_metrics = _metrics_for_slice(mod, test_ret)
            if test_metrics is None:
                continue
            fold_rows.append(
                {
                    "fold": fold_id,
                    "variant": name,
                    "train_years": fold["train_years"],
                    "test_years": fold["test_years"],
                    "annual": test_metrics["annual"],
                    "max_dd": test_metrics["max_dd"],
                    "sharpe": test_metrics["sharpe"],
                    "calmar": test_metrics["calmar"],
                    "vol": test_metrics["vol"],
                    "total_return": test_metrics["total_return"],
                }
            )
            stitched_returns[name].append(test_ret)

    folds_df = pd.DataFrame(fold_rows)
    folds_df.to_csv(FOLDS_CSV, index=False, encoding="utf-8-sig")

    summary_rows = []
    for name, parts in stitched_returns.items():
        stitched = pd.concat(parts).sort_index()
        metrics = _metrics_for_slice(mod, stitched)
        if metrics is None:
            continue
        summary_rows.append(
            {
                "variant": name,
                "annual": metrics["annual"],
                "max_dd": metrics["max_dd"],
                "sharpe": metrics["sharpe"],
                "calmar": metrics["calmar"],
                "vol": metrics["vol"],
                "total_return": metrics["total_return"],
                "days": len(stitched),
            }
        )

    summary_df = pd.DataFrame(summary_rows).sort_values(["calmar", "annual"], ascending=[False, False])
    summary_df.to_csv(SUMMARY_CSV, index=False, encoding="utf-8-sig")

    print("Walk-forward summary:")
    print(summary_df.to_string(index=False))
    print(f"\nSaved: {SUMMARY_CSV}")
    print(f"Saved: {FOLDS_CSV}")


if __name__ == "__main__":
    main()

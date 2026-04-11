from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from test_v61_ab_rsrs_filter import _apply_cn_vol_scaling
from test_v61_ab_rsrs_replacement import (
    CN_ALL_CODES,
    CN_BIAS_N,
    CN_BOND_CODE,
    CN_COMMISSION,
    CN_EQUITY_CODES,
    CN_MOM_DAY,
    CN_RF_DAILY,
    CN_R2_THRESHOLD,
    CN_TRADING_DAYS,
    build_cn_inputs,
    calc_bias_momentum,
    calc_metrics,
    calc_rolling_r2,
    compute_rsrs_score,
    first_valid_score_date,
)


OUT_DIR = Path(__file__).resolve().parent / "outputs_v61_rsrs_filter_scan"
OUT_DIR.mkdir(exist_ok=True)


def run_cn_strategy_with_rsrs_filter(close_df: pd.DataFrame, rsrs_df: pd.DataFrame) -> pd.DataFrame:
    bias_dict = {code: calc_bias_momentum(close_df[code]) for code in CN_ALL_CODES}
    r2_dict = {code: calc_rolling_r2(close_df[code]) for code in CN_ALL_CODES}
    start_idx = CN_BIAS_N + CN_MOM_DAY
    holding = "cash"
    rows = []
    for i in range(start_idx, len(close_df)):
        date = close_df.index[i]
        scores = {code: bias_dict[code].iloc[i] for code in CN_ALL_CODES if pd.notna(bias_dict[code].iloc[i])}
        ideal = "cash"
        if scores:
            best = max(scores, key=scores.get)
            if scores[best] > 0:
                r2_val = r2_dict[best].iloc[i]
                if pd.notna(r2_val) and r2_val >= CN_R2_THRESHOLD:
                    ideal = best
        if ideal in CN_EQUITY_CODES:
            rsrs_val = rsrs_df.iloc[i].get(ideal, pd.NA)
            if pd.isna(rsrs_val) or rsrs_val <= 0:
                ideal = "cash"
        target = ideal if ideal != holding else None
        if target is not None:
            old_h = holding
            cost = (1 - CN_COMMISSION) if (old_h == "cash" or target == "cash") else (1 - CN_COMMISSION) ** 2
            if old_h == "cash":
                day_ret = (1 + CN_RF_DAILY) * cost - 1
            else:
                asset_ret = close_df.iloc[i][old_h] / close_df.iloc[i - 1][old_h] - 1
                day_ret = (1 + asset_ret) * cost - 1
            holding = target
        else:
            if holding == "cash":
                day_ret = CN_RF_DAILY
            else:
                day_ret = close_df.iloc[i][holding] / close_df.iloc[i - 1][holding] - 1
        rows.append({"date": date, "return": day_ret, "holding": holding, "is_signal": target is not None})
    df = pd.DataFrame(rows).set_index("date")
    return _apply_cn_vol_scaling(df)


def main() -> None:
    cn_close, cn_ohlc = build_cn_inputs()

    baseline_path = Path(__file__).resolve().parent / "outputs_v61_rsrs_filter" / "v61_ab_rsrs_filter_compare.csv"
    baseline = pd.read_csv(baseline_path).set_index("strategy")

    n_values = [12, 16, 18, 20, 24, 30]
    m_values = [40, 60, 80, 120, 160, 200, 250, 400, 600]
    rows = []
    for n in n_values:
        rsrs_df = pd.concat([compute_rsrs_score(cn_ohlc[c], n=n, m=max(m_values)).rename(c) for c in CN_ALL_CODES], axis=1)
        for m in m_values:
            sliced = pd.concat([compute_rsrs_score(cn_ohlc[c], n=n, m=m).rename(c) for c in CN_ALL_CODES], axis=1).reindex(cn_close.index)
            result = run_cn_strategy_with_rsrs_filter(cn_close, sliced)
            same_start = first_valid_score_date(sliced)
            met_full = calc_metrics(result["return"], CN_TRADING_DAYS, CN_RF_DAILY)
            met_same = calc_metrics(result.loc[result.index >= same_start, "return"], CN_TRADING_DAYS, CN_RF_DAILY)
            rows.append(
                {
                    "n": n,
                    "m": m,
                    "full_annual": met_full["annual"],
                    "full_max_dd": met_full["max_dd"],
                    "full_sharpe": met_full["sharpe"],
                    "full_total_return": met_full["total_return"],
                    "same_start": same_start.strftime("%Y-%m-%d"),
                    "same_annual": met_same["annual"],
                    "same_max_dd": met_same["max_dd"],
                    "same_sharpe": met_same["sharpe"],
                    "same_total_return": met_same["total_return"],
                }
            )

    scan = pd.DataFrame(rows)
    scan["annual_delta_vs_baseline"] = scan["same_annual"] - float(baseline.loc["Sub-A_baseline_same_start", "annual"])
    scan["max_dd_delta_vs_baseline"] = scan["same_max_dd"] - float(baseline.loc["Sub-A_baseline_same_start", "max_dd"])
    scan["sharpe_delta_vs_baseline"] = scan["same_sharpe"] - float(baseline.loc["Sub-A_baseline_same_start", "sharpe"])
    scan = scan.sort_values(["same_sharpe", "same_annual"], ascending=[False, False]).reset_index(drop=True)
    scan_path = OUT_DIR / "suba_rsrs_filter_nm_scan.csv"
    scan.to_csv(scan_path, index=False, encoding="utf-8-sig")

    better_dd = scan[(scan["same_max_dd"] > float(baseline.loc["Sub-A_baseline_same_start", "max_dd"]))].copy()
    better_dd_no_big_annual_loss = better_dd[better_dd["same_annual"] >= float(baseline.loc["Sub-A_baseline_same_start", "annual"]) - 0.03].copy()

    summary = {
        "baseline_same_start": baseline.loc["Sub-A_baseline_same_start"].to_dict(),
        "top_by_sharpe": scan.head(10).to_dict(orient="records"),
        "better_drawdown_any": better_dd.sort_values(["same_annual", "same_sharpe"], ascending=[False, False]).head(10).to_dict(orient="records"),
        "better_drawdown_small_annual_loss": better_dd_no_big_annual_loss.sort_values(["same_annual", "same_sharpe"], ascending=[False, False]).head(10).to_dict(orient="records"),
    }
    with open(OUT_DIR / "suba_rsrs_filter_nm_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("Baseline same-start:")
    print(baseline.loc["Sub-A_baseline_same_start"].to_string())
    print()
    print("Top 15 by same-start Sharpe:")
    print(scan.head(15).to_string(index=False))
    print()
    print(f"Saved scan -> {scan_path}")


if __name__ == "__main__":
    main()

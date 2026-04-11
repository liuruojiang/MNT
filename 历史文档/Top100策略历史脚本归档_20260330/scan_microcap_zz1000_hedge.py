from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from analyze_microcap_zz1000_hedge import build_close_df, run_backtest, calc_metrics


ROOT = Path(__file__).resolve().parent
OUT_CSV = ROOT / "microcap_zz1000_hedge_scan.csv"
OUT_JSON = ROOT / "microcap_zz1000_hedge_scan_summary.json"

LOOKBACKS = [5, 10, 15, 20, 30, 40, 60, 90, 120]


class Args:
    panel_path = ROOT / "mnt_strategy_data_cn.csv"
    microcap_column = "868008.WI"
    hedge_column = "1.000852"
    lookback = 20
    futures_drag = 3.0 / 10000.0
    microcap_csv = ROOT / "wind_microcap_868008_monthly_3y.csv"
    microcap_date_col = "date"
    microcap_close_col = "close"
    output_prefix = "scan"
    require_positive_microcap_mom = True


def main() -> None:
    args = Args()
    close_df = build_close_df(args)

    rows: list[dict[str, object]] = []
    for require_positive in (True, False):
        for lookback in LOOKBACKS:
            result = run_backtest(
                close_df=close_df,
                lookback=lookback,
                futures_drag=args.futures_drag,
                require_positive_microcap_mom=require_positive,
            )
            metrics = calc_metrics(result["return"])
            rows.append(
                {
                    "lookback": lookback,
                    "require_positive_microcap_mom": require_positive,
                    "annual": metrics.annual,
                    "vol": metrics.vol,
                    "sharpe": metrics.sharpe,
                    "max_dd": metrics.max_dd,
                    "calmar": metrics.calmar,
                    "total_return": metrics.total_return,
                    "win_rate": metrics.win_rate,
                    "active_days_pct": float((result["holding"] != "cash").mean()),
                    "signal_changes": int(result["signal_on"].ne(result["signal_on"].shift()).sum() - 1),
                    "start_date": str(result.index[0].date()),
                    "end_date": str(result.index[-1].date()),
                    "latest_next_holding": str(result["next_holding"].iloc[-1]),
                }
            )

    frame = pd.DataFrame(rows).sort_values(
        ["require_positive_microcap_mom", "sharpe", "annual"],
        ascending=[False, False, False],
    )
    frame.to_csv(OUT_CSV, index=False, encoding="utf-8")

    summary = {
        "best_with_positive_filter_by_sharpe": frame[frame["require_positive_microcap_mom"]]
        .sort_values(["sharpe", "annual"], ascending=False)
        .head(5)
        .to_dict(orient="records"),
        "best_without_positive_filter_by_sharpe": frame[~frame["require_positive_microcap_mom"]]
        .sort_values(["sharpe", "annual"], ascending=False)
        .head(5)
        .to_dict(orient="records"),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(frame.to_string(index=False))
    print(f"saved {OUT_CSV.name}")
    print(f"saved {OUT_JSON.name}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import analyze_microcap_zz1000_hedge as hedge_mod
import analyze_top100_execution_stress as stress_mod


ROOT = Path(__file__).resolve().parent
OUTPUT_PREFIX = "microcap_top100_open_slippage_recent5y"
SLIPPAGE_GRID = [0.0, 0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02]


def run_open_slippage_scan(
    signal_df: pd.DataFrame,
    basket_df: pd.DataFrame,
    hedge_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    nav_df = pd.DataFrame(index=signal_df.index)

    for slip in SLIPPAGE_GRID:
        daily_ret = []
        for dt, row in signal_df.iterrows():
            if dt not in basket_df.index or dt not in hedge_df.index:
                daily_ret.append(float("nan"))
                continue

            b = basket_df.loc[dt]
            h = hedge_df.loc[dt]
            target_prev = bool(row["target_prev"])
            target_today = bool(row["target_today"])

            # Only stress the microcap basket execution.
            # Entry: buy at open * (1 + slip)
            # Exit: sell at open * (1 - slip)
            # Hedge leg keeps open execution because its liquidity is materially better.
            if (not target_prev) and (not target_today):
                ret = 0.0
            elif (not target_prev) and target_today:
                stock_ret = b["ret_entry_open"] - slip * (1.0 + b["ret_entry_open"])
                hedge_ret = h["ret_entry_open"]
                ret = stock_ret - hedge_ret - hedge_mod.DEFAULT_FUTURES_DRAG
            elif target_prev and target_today:
                ret = b["ret_cc"] - h["ret_cc"] - hedge_mod.DEFAULT_FUTURES_DRAG
            else:
                stock_ret = b["ret_exit_open"] - slip * (1.0 + b["ret_exit_open"])
                hedge_ret = h["ret_exit_open"]
                ret = stock_ret - hedge_ret

            daily_ret.append(float(ret))

        ret_s = pd.Series(daily_ret, index=signal_df.index, dtype=float).dropna()
        nav_s = (1.0 + ret_s).cumprod()
        nav_df[f"slippage_{slip:.4f}"] = nav_s
        m = hedge_mod.calc_metrics(ret_s)
        row = {
            "stock_open_slippage": float(slip),
            "annual": float(m.annual),
            "max_dd": float(m.max_dd),
            "sharpe": float(m.sharpe),
            "vol": float(m.vol),
            "total_return": float(m.total_return),
        }
        last_date = ret_s.index[-1]
        for yrs in [1, 3, 5]:
            part = ret_s.loc[ret_s.index >= last_date - pd.DateOffset(years=yrs)]
            mm = hedge_mod.calc_metrics(part)
            row[f"annual_{yrs}y"] = float(mm.annual)
            row[f"max_dd_{yrs}y"] = float(mm.max_dd)
            row[f"sharpe_{yrs}y"] = float(mm.sharpe)
        rows.append(row)
    return pd.DataFrame(rows), nav_df


def main() -> None:
    trading_dates, member_map = stress_mod.load_dates_and_members()
    daily_members, unique_symbols = stress_mod.build_daily_members(trading_dates, member_map)

    start_date = str(trading_dates[0].date())
    end_date = str(trading_dates[-1].date())
    stock_ohlc = stress_mod.load_stock_ohlc_batch(unique_symbols, start_date=start_date, end_date=end_date)
    stock_ratio_cache = stress_mod.prepare_stock_ratio_cache(stock_ohlc)
    basket_df = stress_mod.build_basket_return_table(trading_dates, daily_members, stock_ratio_cache)
    hedge_df = stress_mod.fetch_hedge_ohlc(start_date=start_date, end_date=end_date)
    signal_df = stress_mod.build_signal_frame(trading_dates)
    signal_df = signal_df.loc[signal_df.index.isin(basket_df.index) & signal_df.index.isin(hedge_df.index)].copy()

    summary_df, nav_df = run_open_slippage_scan(signal_df, basket_df, hedge_df)
    summary_df = summary_df.sort_values("stock_open_slippage").reset_index(drop=True)

    summary_path = ROOT / f"{OUTPUT_PREFIX}.csv"
    nav_path = ROOT / f"{OUTPUT_PREFIX}_nav.csv"
    meta_path = ROOT / f"{OUTPUT_PREFIX}.json"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8")
    nav_df.reset_index().rename(columns={"index": "date"}).to_csv(nav_path, index=False, encoding="utf-8")

    payload = {
        "strategy": "top100_biweekly_mom16_open_slippage_recent5y",
        "window_start": start_date,
        "window_end": end_date,
        "slippage_grid": SLIPPAGE_GRID,
        "scope": "Only the microcap stock basket entry/exit is stressed with open slippage. Hedge leg stays at open execution.",
        "results": summary_df.to_dict(orient="records"),
    }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(summary_df.to_string(index=False))
    print(f"saved {summary_path.name}")
    print(f"saved {nav_path.name}")
    print(f"saved {meta_path.name}")


if __name__ == "__main__":
    main()

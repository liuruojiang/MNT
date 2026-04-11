from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from test_v61_ab_rsrs_replacement import (
    CN_ALL_CODES,
    CN_BIAS_N,
    CN_BOND_CODE,
    CN_COMMISSION,
    CN_EQUITY_CODES,
    CN_MOM_DAY,
    CN_RF_DAILY,
    CN_R2_THRESHOLD,
    CN_TARGET_VOL,
    CN_TRADING_DAYS,
    CN_VOL_WINDOW,
    CN_MAX_LEV,
    CN_MIN_LEV,
    CN_SCALE_THRESHOLD,
    US_ROT_ABS_THRESHOLD,
    US_ROT_BTC_MAX_W,
    US_ROT_BTC_START,
    US_ROT_BTC_TICKER,
    US_ROT_COMMISSION,
    US_ROT_MAX_LEV,
    US_ROT_MIN_TURNOVER,
    US_ROT_POOL,
    US_ROT_REBALANCE_THRESHOLD,
    US_ROT_TARGET_VOL,
    US_ROT_VOLREG_ENABLED,
    US_ROT_VOLREG_THRESHOLD,
    US_ROT_VOLREG_LONG_W,
    US_ROT_VOLREG_SHORT_W,
    US_ROT_VOL_LB,
    US_ROT_VOL_WINDOW,
    US_TRADING_DAYS,
    _apply_btc_cap,
    _us_model_b,
    _us_raw_weights,
    _us_signal_days,
    anchor_ohlc_to_target_close,
    apply_vol_regime_overlay,
    build_cn_inputs,
    build_us_inputs,
    calc_bias_momentum,
    calc_metrics,
    calc_rolling_r2,
    compute_rsrs_score,
    first_valid_score_date,
)


OUT_DIR = Path(__file__).resolve().parent / "outputs_v61_rsrs_filter"
OUT_DIR.mkdir(exist_ok=True)


def _apply_cn_vol_scaling(df: pd.DataFrame) -> pd.DataFrame:
    raw_ret = df["return"].values.copy()
    is_cash = (df["holding"] == "cash").values
    realized_vol = pd.Series(raw_ret, index=df.index).rolling(CN_VOL_WINDOW).std() * np.sqrt(CN_TRADING_DAYS)
    raw_scale = (CN_TARGET_VOL / realized_vol.replace(0, np.nan)).clip(CN_MIN_LEV, CN_MAX_LEV).shift(1)
    if CN_SCALE_THRESHOLD > 0:
        arr = raw_scale.values.copy()
        last = np.nan
        for i in range(len(arr)):
            if np.isnan(arr[i]):
                continue
            if np.isnan(last):
                last = arr[i]
            elif abs(arr[i] - last) >= CN_SCALE_THRESHOLD - 1e-9:
                last = arr[i]
            else:
                arr[i] = last
        raw_scale = pd.Series(arr, index=df.index)
    scale_arr = raw_scale.fillna(1.0).values
    scale_arr[is_cash] = 1.0
    prev_scale = np.concatenate([[scale_arr[0]], scale_arr[:-1]])
    delta_scale = np.abs(scale_arr - prev_scale)
    scale_tc = np.where((~df["is_signal"].values) & ~is_cash, CN_COMMISSION * delta_scale, 0.0)
    out = df.copy()
    out["weight"] = scale_arr
    out["scale_raw"] = raw_scale
    out["realized_vol"] = realized_vol
    out["scale_tc"] = scale_tc
    out["return"] = (1 + raw_ret * scale_arr) * (1 - scale_tc) - 1
    out["nav"] = (1 + out["return"]).cumprod()
    return out


def run_cn_strategy_with_rsrs_filter(close_df: pd.DataFrame, rsrs_df: pd.DataFrame) -> pd.DataFrame:
    bias_dict = {code: calc_bias_momentum(close_df[code]) for code in CN_ALL_CODES}
    r2_dict = {code: calc_rolling_r2(close_df[code]) for code in CN_ALL_CODES}
    start_idx = CN_BIAS_N + CN_MOM_DAY
    holding = "cash"
    rows = []
    for i in range(start_idx, len(close_df)):
        date = close_df.index[i]
        scores = {code: bias_dict[code].iloc[i] for code in CN_ALL_CODES if not np.isnan(bias_dict[code].iloc[i])}
        ideal = "cash"
        picked_by_primary = "cash"
        if scores:
            best = max(scores, key=scores.get)
            picked_by_primary = best
            if scores[best] > 0:
                r2_val = r2_dict[best].iloc[i]
                if not np.isnan(r2_val) and r2_val >= CN_R2_THRESHOLD:
                    ideal = best
        rsrs_pass = True
        # Secondary veto only applies to equity sleeve; bond/cash stay on original logic.
        if ideal in CN_EQUITY_CODES:
            score = rsrs_df.iloc[i].get(ideal, np.nan)
            rsrs_pass = bool(not np.isnan(score) and score > 0)
            if not rsrs_pass:
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
        rows.append(
            {
                "date": date,
                "return": day_ret,
                "holding": holding,
                "is_signal": target is not None,
                "primary_pick": picked_by_primary,
                "rsrs_pass": rsrs_pass,
            }
        )
    df = pd.DataFrame(rows).set_index("date")
    return _apply_cn_vol_scaling(df)


def _filter_actual_weights(act: dict[str, float], rsrs_row: pd.Series) -> dict[str, float]:
    out = dict(act)
    moved = 0.0
    for asset, weight in list(out.items()):
        if asset == "BIL" or weight <= 0:
            continue
        score = rsrs_row.get(asset, np.nan)
        if np.isnan(score) or score <= 0:
            moved += weight
            out[asset] = 0.0
    if moved > 0:
        out["BIL"] = out.get("BIL", 0.0) + moved
    return out


def run_us_rotation_with_rsrs_filter(close_df: pd.DataFrame, momentum_df: pd.DataFrame, rsrs_df: pd.DataFrame) -> pd.DataFrame:
    working = close_df.copy()
    if US_ROT_BTC_TICKER in working.columns:
        working.loc[working.index < US_ROT_BTC_START, US_ROT_BTC_TICKER] = np.nan
    vol_df = working.ffill().pct_change(fill_method=None).rolling(US_ROT_VOL_LB).std() * np.sqrt(US_TRADING_DAYS)
    start_idx = max(160, US_ROT_VOL_LB, US_ROT_VOL_WINDOW) + 1
    signal_days = _us_signal_days(working, start_idx)
    act = {"BIL": 1.0}
    scale = 1.0
    w_assets = list(US_ROT_POOL) + ["BIL"]
    rows = []
    hist = []
    for i in range(start_idx, len(working)):
        is_sig = i in signal_days
        comm = 0.0
        rebalanced = False
        if len(hist) >= US_ROT_VOL_WINDOW:
            rv = np.std(hist[-US_ROT_VOL_WINDOW:], ddof=1) * np.sqrt(US_TRADING_DAYS)
            scale = min(max(US_ROT_TARGET_VOL / rv, 0.05), US_ROT_MAX_LEV) if rv > 0.001 else US_ROT_MAX_LEV
        old_act = dict(act)
        filtered_assets = []
        if is_sig:
            prev_risky = {a for a in w_assets if a != "BIL" and rows and rows[-1].get(f"w_{a}", 0.0) > 0.001}
            raw_w = _us_raw_weights(
                momentum_df.iloc[i],
                vol_df.iloc[i],
                US_ROT_POOL,
                top_n=3,
                abs_threshold=US_ROT_ABS_THRESHOLD,
                prev_risky=prev_risky if prev_risky else None,
                threshold=US_ROT_REBALANCE_THRESHOLD,
            )
            new_act = _us_model_b(raw_w, scale)
            new_act = _apply_btc_cap(new_act, US_ROT_BTC_TICKER, US_ROT_BTC_MAX_W)
            before_filter = dict(new_act)
            new_act = _filter_actual_weights(new_act, rsrs_df.iloc[i])
            filtered_assets = [a for a in before_filter if a != "BIL" and before_filter.get(a, 0.0) > 0 and new_act.get(a, 0.0) == 0.0]
            prev_a = {a: rows[-1].get(f"w_{a}", 0.0) for a in w_assets} if rows else {"BIL": 1.0}
            all_a = set(new_act).union(prev_a)
            turnover = sum(abs(new_act.get(a, 0.0) - prev_a.get(a, 0.0)) for a in all_a if a != "BIL")
            if turnover >= US_ROT_MIN_TURNOVER:
                comm = turnover * US_ROT_COMMISSION if turnover > 0 else 0.0
                act = new_act
                rebalanced = True
        pr = 0.0
        for a, w in old_act.items():
            if a in working.columns and not np.isnan(working.iloc[i].get(a, np.nan)) and not np.isnan(working.iloc[i - 1].get(a, np.nan)):
                pr += w * (working.iloc[i][a] / working.iloc[i - 1][a] - 1)
        adj = (1 + pr) * (1 - comm) - 1
        hist.append(adj)
        row = {"date": working.index[i], "return": adj, "is_signal": is_sig, "rebalanced": rebalanced, "filtered_assets": "|".join(filtered_assets)}
        for a in w_assets:
            row[f"w_{a}"] = act.get(a, 0.0)
        rows.append(row)
    df = pd.DataFrame(rows).set_index("date")
    df["nav"] = (1 + df["return"]).cumprod()
    if US_ROT_VOLREG_ENABLED and "SPY" in working.columns:
        df = apply_vol_regime_overlay(df, working["SPY"])
    return df


def main() -> None:
    cn_close, cn_ohlc = build_cn_inputs()
    us_close, us_ohlc = build_us_inputs()

    cn_rsrs_df = pd.concat([compute_rsrs_score(cn_ohlc[c]).rename(c) for c in CN_ALL_CODES], axis=1).reindex(cn_close.index)
    cn_result = run_cn_strategy_with_rsrs_filter(cn_close, cn_rsrs_df)
    cn_common_start = first_valid_score_date(cn_rsrs_df)

    us_close = us_close[["QQQ", "EMXC", "EFA", "GLD", "TLT", "DBC", "BTC-USD", "BIL", "SPY"]].copy()
    us_momentum = us_close.div(us_close.shift(160)).sub(1)
    us_rsrs_df = pd.concat([compute_rsrs_score(us_ohlc[c]).rename(c) for c in US_ROT_POOL], axis=1).reindex(us_close.index)
    us_result = run_us_rotation_with_rsrs_filter(us_close, us_momentum, us_rsrs_df)
    us_common_start = first_valid_score_date(us_rsrs_df)

    baseline_path = Path(__file__).resolve().parent / "outputs_v61_rsrs_replacement" / "v61_ab_rsrs_replacement_compare.csv"
    baseline_compare = pd.read_csv(baseline_path)
    baseline_lookup = baseline_compare.set_index("strategy")

    rows = [
        {
            "strategy": "Sub-A_baseline_full",
            **baseline_lookup.loc["Sub-A_baseline_full"].to_dict(),
        },
        {
            "strategy": "Sub-A_RSRS_filter_full",
            **calc_metrics(cn_result["return"], CN_TRADING_DAYS, CN_RF_DAILY),
        },
        {
            "strategy": "Sub-A_baseline_same_start",
            **baseline_lookup.loc["Sub-A_baseline_same_start"].to_dict(),
        },
        {
            "strategy": "Sub-A_RSRS_filter_same_start",
            **calc_metrics(cn_result.loc[cn_result.index >= cn_common_start, "return"], CN_TRADING_DAYS, CN_RF_DAILY),
        },
        {
            "strategy": "Sub-B_baseline_full",
            **baseline_lookup.loc["Sub-B_baseline_full"].to_dict(),
        },
        {
            "strategy": "Sub-B_RSRS_filter_full",
            **calc_metrics(us_result["return"], US_TRADING_DAYS, 0.0),
        },
        {
            "strategy": "Sub-B_baseline_same_start",
            **baseline_lookup.loc["Sub-B_baseline_same_start"].to_dict(),
        },
        {
            "strategy": "Sub-B_RSRS_filter_same_start",
            **calc_metrics(us_result.loc[us_result.index >= us_common_start, "return"], US_TRADING_DAYS, 0.0),
        },
    ]
    compare = pd.DataFrame(rows)
    compare.to_csv(OUT_DIR / "v61_ab_rsrs_filter_compare.csv", index=False, encoding="utf-8-sig")
    cn_result[["return", "nav", "holding", "primary_pick", "rsrs_pass"]].to_csv(
        OUT_DIR / "sub_a_rsrs_filter_nav.csv", encoding="utf-8-sig"
    )
    us_cols = ["return", "nav", "filtered_assets"] + [c for c in us_result.columns if c.startswith("w_")]
    us_result[us_cols].to_csv(OUT_DIR / "sub_b_rsrs_filter_nav.csv", encoding="utf-8-sig")

    summary = {
        "filter_definition": {
            "sub_a": "Keep original bias-momentum ranking and R2 gate. If final chosen holding is an equity and its RSRS<=0, veto to cash. Bond/cash are not vetoed.",
            "sub_b": "Keep original absolute-momentum ranking and weight construction. After target weights are built, assets with RSRS<=0 are zeroed out and their weight is moved to BIL.",
        },
        "results": compare.to_dict(orient="records"),
        "sub_a_common_start": cn_common_start.strftime("%Y-%m-%d"),
        "sub_b_common_start": us_common_start.strftime("%Y-%m-%d"),
    }
    with open(OUT_DIR / "v61_ab_rsrs_filter_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(compare.to_string(index=False))


if __name__ == "__main__":
    main()

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import research_subd_six_etf_weighted_slope as subd
from analyze_subd_six_etf_overheat_scan import (
    OverheatCase,
    apply_overheat_overlay,
    build_overheat_features,
)
from analyze_subd_six_etf_staged_entry_scan import (
    EntryCase,
    apply_target_vol_overlay,
    run_staged_entry,
)


QVERIS_BASE_URL = "https://qveris.ai/api/v1"
START_DATE = pd.Timestamp("2010-01-01")
EVAL_START = pd.Timestamp("2020-01-02")
END_DATE = pd.Timestamp("2026-05-08")
SWITCH_BUFFER = 1.00
INITIAL_ENTRY_FRACTION = 0.50
ONE_WAY_COST = 0.001
VOL_WINDOW = subd.DEFAULT_VOL_WINDOW
MAX_LEV = subd.DEFAULT_MAX_LEV


def qveris_symbol(code: str) -> str:
    ticker, suffix = code.split(".")
    if suffix == "SZ":
        return f"{ticker}.SZ"
    if suffix == "SH":
        return f"{ticker}.SH"
    raise ValueError(f"Unsupported suffix: {code}")


def qveris_execute(tool_id: str, params: dict[str, object], timeout: int = 180) -> dict[str, object]:
    key = os.environ.get("QVERIS_API_KEY")
    if not key:
        raise RuntimeError("QVERIS_API_KEY is not set.")
    response = requests.post(
        f"{QVERIS_BASE_URL}/tools/execute?tool_id={tool_id}",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"parameters": params},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result") or {}
    data = result.get("data") or []
    if not data and result.get("full_content_file_url"):
        full_response = requests.get(result["full_content_file_url"], timeout=timeout)
        full_response.raise_for_status()
        data = full_response.json()
    elif not data and result.get("truncated_content"):
        data = json.loads(result["truncated_content"])
    return {"payload": payload, "data": data}


def load_qveris_close(codes: list[str], start: pd.Timestamp, end: pd.Timestamp, cps: str = "3") -> tuple[pd.DataFrame, pd.DataFrame]:
    q_codes = [qveris_symbol(code) for code in codes]
    params = {
        "codes": ",".join(q_codes),
        "indicators": "stock_common",
        "startdate": start.strftime("%Y%m%d"),
        "enddate": end.strftime("%Y%m%d"),
        "interval": "D",
        "cps": cps,
        "fill": "Blank",
    }
    data = qveris_execute("cn_financial_pro.history_quotation.v1", params)["data"]
    q_to_code = {qveris_symbol(code): code for code in codes}
    series = []
    sources = []
    for rows in data:
        if not rows:
            continue
        q_code = rows[0].get("thscode")
        code = q_to_code.get(q_code)
        if not code:
            continue
        df = pd.DataFrame(rows)
        close = df[["time", "close"]].copy()
        close["time"] = pd.to_datetime(close["time"])
        close = close.set_index("time")["close"].astype(float).sort_index()
        close.name = code
        series.append(close)
        non_na = close.dropna()
        sources.append(
            {
                "code": code,
                "name": subd.ASSETS[code],
                "symbol": q_code,
                "source": "QVeris cn_financial_pro.history_quotation.v1",
                "adjustment": f"cps={cps}, stock_common close",
                "first": non_na.index.min().date().isoformat(),
                "last": non_na.index.max().date().isoformat(),
                "rows": int(non_na.shape[0]),
            }
        )
    found = {s.name for s in series}
    missing = sorted(set(codes) - found)
    if missing:
        raise RuntimeError(f"QVeris missing close series for {missing}")
    return pd.concat(series, axis=1).sort_index(), pd.DataFrame(sources)


def load_qveris_single_window(code: str, start: str, end: str, cps: str) -> pd.DataFrame:
    data = qveris_execute(
        "cn_financial_pro.history_quotation.v1",
        {
            "codes": qveris_symbol(code),
            "indicators": "stock_common",
            "startdate": start,
            "enddate": end,
            "interval": "D",
            "cps": cps,
            "fill": "Blank",
        },
        timeout=90,
    )["data"]
    rows = data[0] if data else []
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    out = df[["time", "preClose", "open", "close", "changeRatio"]].copy()
    out["source"] = f"QVeris cps={cps}"
    return out


def load_cnfin_single_window() -> pd.DataFrame:
    url = "https://quotedata.cnfin.com/quote/v1/kline"
    params = {
        "prod_code": "159941.SZ",
        "candle_period": "6",
        "get_type": "range",
        "start_date": "20220629",
        "end_date": "20220708",
        "fields": "open_px,high_px,low_px,close_px,business_amount,business_balance",
    }
    response = requests.get(url, params=params, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    payload = response.json()
    fields = payload["data"]["candle"]["fields"]
    rows = payload["data"]["candle"]["159941.SZ"]
    df = pd.DataFrame(rows, columns=fields)
    return pd.DataFrame(
        {
            "time": pd.to_datetime(df["min_time"].astype(str)),
            "preClose": np.nan,
            "open": df["open_px"].astype(float),
            "close": df["close_px"].astype(float),
            "changeRatio": df["close_px"].astype(float).pct_change() * 100.0,
            "source": "CNFin raw kline",
        }
    )


def write_data_validation(prices_qveris: pd.DataFrame, sources_qveris: pd.DataFrame) -> None:
    config = subd.RunConfig(
        source="sina",
        one_way_cost=ONE_WAY_COST,
        start_date=START_DATE,
        end_date=END_DATE,
        output_tag="tmp",
        target_vols=(),
        vol_window=VOL_WINDOW,
        max_lev=MAX_LEV,
    )
    prices_sina, _sources_sina = subd.load_close(config)
    sina = prices_sina[["159941.SZ"]].dropna().loc["2022-06-29":"2022-07-08"].reset_index()
    sina["preClose"] = np.nan
    sina["open"] = np.nan
    sina["changeRatio"] = sina["159941.SZ"].pct_change() * 100.0
    sina = sina.rename(columns={"date": "time", "159941.SZ": "close"})
    sina["source"] = "Sina raw close"
    cnfin = load_cnfin_single_window()
    q0 = load_qveris_single_window("159941.SZ", "20220629", "20220708", "0")
    q2 = load_qveris_single_window("159941.SZ", "20220629", "20220708", "2")
    q3 = load_qveris_single_window("159941.SZ", "20220629", "20220708", "3")
    check = pd.concat([sina[["time", "preClose", "open", "close", "changeRatio", "source"]], cnfin, q0, q2, q3], ignore_index=True)
    check.to_csv(subd.OUTPUT_DIR / "subd_six_etf_159941_data_source_check_20260509.csv", index=False, encoding="utf-8-sig")

    q_quality = subd.data_quality(prices_qveris)
    q_quality.to_csv(subd.OUTPUT_DIR / "subd_six_etf_qveris_cps3_data_quality_20260509.csv", index=False, encoding="utf-8-sig")
    sources_qveris.to_csv(subd.OUTPUT_DIR / "subd_six_etf_qveris_cps3_sources_20260509.csv", index=False, encoding="utf-8-sig")
    lines = [
        "# Sub-D Six ETF Data Source Validation - 2026-05-09",
        "",
        "## 159941.SZ split / adjustment check",
        "",
        "- Sina raw close and CNFin raw kline show `close=0.604` on 2022-07-05 after `2.384` on 2022-07-04, creating a raw close-to-close move near `-74.66%` if returns are computed directly from raw close.",
        "- QVeris raw-like `cps=0` reports `preClose=0.596`, `close=0.604`, `changeRatio=+1.3423%`, confirming the exchange-style return was not `-74.66%`.",
        "- QVeris continuous `cps=3` reports `2022-07-05 close=2.416` after `2.384`, preserving the same `+1.3423%` return while removing the price-level discontinuity.",
        "- For momentum/backtest scans, QVeris `cps=3` is the cleaner source than Sina raw close for this ETF pool.",
        "",
        "## Output files",
        "",
        "- `outputs/subd_six_etf_159941_data_source_check_20260509.csv`",
        "- `outputs/subd_six_etf_qveris_cps3_sources_20260509.csv`",
        "- `outputs/subd_six_etf_qveris_cps3_data_quality_20260509.csv`",
    ]
    (subd.OUTPUT_DIR / "subd_six_etf_data_source_validation_20260509.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize(curve: pd.DataFrame, start: pd.Timestamp, label: str, scenario: str, extra: dict[str, object]) -> dict[str, object]:
    sub = curve.loc[curve.index >= start].copy()
    nav = sub["nav"] / float(sub["nav"].iloc[0])
    ret = nav.pct_change().fillna(0.0)
    years = len(sub) / subd.TRADING_DAYS
    std = ret.std(ddof=0)
    final_exposure = sub["final_exposure"].astype(float).fillna(0.0)
    if "overheat_scale" in sub.columns:
        final_exposure = final_exposure * sub["overheat_scale"].astype(float).fillna(1.0)
    row = {
        "scenario": scenario,
        "window": label,
        "start": sub.index[0].date().isoformat(),
        "end": sub.index[-1].date().isoformat(),
        "days": len(sub),
        "total": float(nav.iloc[-1] - 1.0),
        "cagr": float(nav.iloc[-1] ** (1.0 / years) - 1.0),
        "maxdd": subd.max_drawdown(nav),
        "sharpe": float(ret.mean() / std * math.sqrt(subd.TRADING_DAYS)) if std > 0 else math.nan,
        "vol": float(std * math.sqrt(subd.TRADING_DAYS)),
        "half_position_days": int(((sub["holding_fraction"] > 1e-12) & (sub["holding_fraction"] < 1.0 - 1e-12)).sum()),
        "staged_initials": int(sub["staged_initial"].astype(bool).sum()),
        "staged_fills": int(sub["fill_on_down_day"].astype(bool).sum()),
        "overheat_days": int(sub["overheat_on"].astype(bool).sum()) if "overheat_on" in sub.columns else 0,
        "overheat_triggers": int(sub["overheat_triggered"].astype(bool).sum()) if "overheat_triggered" in sub.columns else 0,
        "trades": int(sub["trade_count"].iloc[-1] - sub["trade_count"].iloc[0]),
        "cost_sum": float(sub["cost"].sum() + (sub["overheat_tc"].sum() if "overheat_tc" in sub.columns else 0.0)),
        "turnover_sum": float(sub["turnover"].sum()),
        "avg_final_exposure": float(final_exposure.mean()),
        "max_final_exposure": float(final_exposure.max()),
    }
    row.update(extra)
    return row


def build_v11_curve(
    prices: pd.DataFrame,
    config: subd.RunConfig,
    r2_threshold: float,
    target_vol: float,
    overheat_enter: float,
    overheat_exit: float,
) -> pd.DataFrame:
    staged = run_staged_entry(
        prices,
        config,
        EntryCase("all_new_asset_50_wait_down_no_timeout", "all_new_asset_50_wait_down", INITIAL_ENTRY_FRACTION),
        r2_threshold,
        SWITCH_BUFFER,
    )
    tv = apply_target_vol_overlay(staged, target_vol, VOL_WINDOW, MAX_LEV)
    return apply_overheat_overlay(
        tv,
        build_overheat_features(prices),
        OverheatCase(f"overheat_{overheat_enter:.2f}_{overheat_exit:.2f}", overheat_enter, overheat_exit, 0.0),
        config.one_way_cost,
    )


def main() -> None:
    subd.OUTPUT_DIR.mkdir(exist_ok=True)
    codes = list(subd.ASSETS)
    prices, sources = load_qveris_close(codes, START_DATE, END_DATE, cps="3")
    prices = prices.loc[prices.index >= START_DATE]
    write_data_validation(prices, sources)
    config = subd.RunConfig(
        source="sina",
        one_way_cost=ONE_WAY_COST,
        start_date=START_DATE,
        end_date=END_DATE,
        output_tag="qveris_cps3",
        target_vols=(),
        vol_window=VOL_WINDOW,
        max_lev=MAX_LEV,
    )
    windows = {
        "from_2020": EVAL_START,
        "5Y": END_DATE - pd.DateOffset(years=5),
        "3Y": END_DATE - pd.DateOffset(years=3),
        "1Y": END_DATE - pd.DateOffset(years=1),
    }

    overheat_rows = []
    overheat_curves = []
    for enter, exit_ in ((0.18, 0.16), (0.20, 0.18), (0.22, 0.20), (0.24, 0.22)):
        curve = build_v11_curve(prices, config, 0.20, 0.25, enter, exit_)
        scenario = f"qveris_v11_oh_{enter:.2f}_{exit_:.2f}_tv25_r2p20"
        tagged = curve.copy()
        tagged.insert(0, "scenario_tag", scenario)
        overheat_curves.append(tagged)
        for label, start in windows.items():
            overheat_rows.append(
                summarize(
                    curve,
                    start,
                    label,
                    scenario,
                    {"source": "qveris_cps3", "r2_threshold": 0.20, "target_vol": 0.25, "overheat_enter": enter, "overheat_exit": exit_},
                )
            )
    overheat_summary = pd.DataFrame(overheat_rows)
    overheat_summary.to_csv(subd.OUTPUT_DIR / "subd_six_etf_v1_1_qveris_overheat_scan_20260509_summary.csv", index=False, encoding="utf-8-sig")
    pd.concat(overheat_curves).to_csv(subd.OUTPUT_DIR / "subd_six_etf_v1_1_qveris_overheat_scan_20260509_daily.csv", encoding="utf-8-sig")

    grid_rows = []
    grid_curves = []
    for r2 in (0.10, 0.20, 0.30):
        for tv in (0.20, 0.25, 0.30):
            curve = build_v11_curve(prices, config, r2, tv, 0.20, 0.18)
            scenario = f"qveris_v11_r2_{r2:.2f}_tv_{tv:.2f}_oh_20_18"
            tagged = curve.copy()
            tagged.insert(0, "scenario_tag", scenario)
            grid_curves.append(tagged)
            for label, start in windows.items():
                grid_rows.append(
                    summarize(
                        curve,
                        start,
                        label,
                        scenario,
                        {"source": "qveris_cps3", "r2_threshold": r2, "target_vol": tv, "overheat_enter": 0.20, "overheat_exit": 0.18},
                    )
                )
    grid_summary = pd.DataFrame(grid_rows)
    grid_summary.to_csv(subd.OUTPUT_DIR / "subd_six_etf_v1_1_qveris_r2_targetvol_scan_20260509_summary.csv", index=False, encoding="utf-8-sig")
    pd.concat(grid_curves).to_csv(subd.OUTPUT_DIR / "subd_six_etf_v1_1_qveris_r2_targetvol_scan_20260509_daily.csv", encoding="utf-8-sig")

    print("QVERIS OVERHEAT SCAN")
    print(overheat_summary.loc[overheat_summary["window"].eq("from_2020")].to_string(index=False))
    print("\nQVERIS R2 TARGET VOL SCAN")
    print(grid_summary.loc[grid_summary["window"].eq("from_2020")].to_string(index=False))


if __name__ == "__main__":
    main()

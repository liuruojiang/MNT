from __future__ import annotations

import builtins
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "mnt_bot V 7.6 plus.py"
MICROCAP_NAV = ROOT.parent / "微盘股对冲策略" / "outputs" / "microcap_top100_mom11_targetvol30_max2_v1_8_costed_nav.csv"
OUT_DIR = Path(__file__).resolve().parent
WINDOWS = {
    "full": None,
    "10Y": pd.DateOffset(years=10),
    "5Y": pd.DateOffset(years=5),
    "3Y": pd.DateOffset(years=3),
    "1Y": pd.DateOffset(years=1),
}
SCENARIOS = {
    "current_10_15_15_60": {"Sub-A": 0.10, "Sub-A-DK": 0.15, "Microcap": 0.15, "Sub-B": 0.60},
    "lower_A_to_microcap_5_15_20_60": {"Sub-A": 0.05, "Sub-A-DK": 0.15, "Microcap": 0.20, "Sub-B": 0.60},
    "higher_microcap_from_subb_10_15_20_55": {"Sub-A": 0.10, "Sub-A-DK": 0.15, "Microcap": 0.20, "Sub-B": 0.55},
    "higher_subb_from_A_5_15_15_65": {"Sub-A": 0.05, "Sub-A-DK": 0.15, "Microcap": 0.15, "Sub-B": 0.65},
    "balanced_risk_5_20_20_55": {"Sub-A": 0.05, "Sub-A-DK": 0.20, "Microcap": 0.20, "Sub-B": 0.55},
}


class NullMessage:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def write(self, value) -> None:
        text = str(value)
        self.lines.append(text)
        sys.stdout.buffer.write(text.encode(sys.stdout.encoding or "utf-8", errors="replace"))
        sys.stdout.flush()

    def attach_file(self, **_kwargs) -> None:
        return None


class PoeStub:
    class BotError(RuntimeError):
        pass

    query = SimpleNamespace(text="", attachments=[])
    default_chat = []

    @staticmethod
    def update_settings(_settings):
        return None

    @staticmethod
    def start_message():
        return NullMessage()

    @staticmethod
    def call(*_args, **_kwargs):
        raise RuntimeError("poe.call disabled in offline validation")


def load_module():
    builtins.poe = PoeStub()
    spec = importlib.util.spec_from_file_location("mnt_bot_v76_four_sleeve_check", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    module.poe = PoeStub()
    spec.loader.exec_module(module)
    return module


def load_microcap_return() -> pd.Series:
    df = pd.read_csv(MICROCAP_NAV, parse_dates=["date"]).sort_values("date").set_index("date")
    ret = pd.to_numeric(df["return_net"], errors="coerce").dropna()
    ret.name = "Microcap"
    return ret


def run_v76_sleeves(mod):
    fetch_msg = NullMessage()
    engine = mod.CombinedStrategyV76()
    cn_close, cn_dk_close, us_rot_close, us_prod_daily = engine._fetch_data(
        fetch_msg,
        include_cn_live_snapshot=False,
        include_us_live_snapshot=False,
    )
    cn_result, cn_dk_result, us_rot_result, *_ = engine._run_strategies(
        cn_close.copy(),
        cn_dk_close.copy(),
        us_rot_close.copy(),
        us_prod_daily.copy(),
    )
    daily_returns = {
        "Sub-A": pd.to_numeric(cn_result["return"], errors="coerce").dropna(),
        "Sub-A-DK": pd.to_numeric(cn_dk_result["return"], errors="coerce").dropna(),
        "Sub-B": pd.to_numeric(us_rot_result["return"], errors="coerce").dropna(),
        "Microcap": load_microcap_return(),
    }
    audit = {
        "fetch_log_tail": fetch_msg.lines[-40:],
        "inputs": {
            "cn_close": [cn_close.index[0].date().isoformat(), cn_close.index[-1].date().isoformat(), int(len(cn_close))],
            "cn_dk_close": [cn_dk_close.index[0].date().isoformat(), cn_dk_close.index[-1].date().isoformat(), int(len(cn_dk_close))],
            "us_rot_close": [us_rot_close.index[0].date().isoformat(), us_rot_close.index[-1].date().isoformat(), int(len(us_rot_close))],
            "us_prod_daily": [us_prod_daily.index[0].date().isoformat(), us_prod_daily.index[-1].date().isoformat(), int(len(us_prod_daily))],
            "microcap": [
                daily_returns["Microcap"].index[0].date().isoformat(),
                daily_returns["Microcap"].index[-1].date().isoformat(),
                int(len(daily_returns["Microcap"])),
                str(MICROCAP_NAV),
            ],
        },
    }
    return daily_returns, audit


def build_combo_nav(daily_returns: dict[str, pd.Series], weights: dict[str, float], common_start: pd.Timestamp, common_end: pd.Timestamp) -> pd.Series:
    nav_parts = {}
    for name, ret in daily_returns.items():
        part = ret.loc[(ret.index >= common_start) & (ret.index <= common_end)].dropna()
        nav = (1.0 + part).cumprod()
        nav_parts[name] = nav / nav.iloc[0]
    all_dates = pd.DatetimeIndex(sorted(set().union(*(s.index for s in nav_parts.values()))))
    all_dates = all_dates[(all_dates >= common_start) & (all_dates <= common_end)]
    nav_df = pd.DataFrame({name: series.reindex(all_dates).ffill() for name, series in nav_parts.items()}).dropna()
    weighted = sum(nav_df[name] * weights[name] for name in weights)
    return weighted / weighted.iloc[0]


def underwater_stats(nav: pd.Series) -> dict[str, object]:
    nav = nav.dropna()
    peak = nav.cummax()
    in_dd = nav < peak
    max_closed_days = 0
    current_start = None
    for dt, underwater in in_dd.items():
        if underwater and current_start is None:
            current_start = dt
        elif not underwater and current_start is not None:
            max_closed_days = max(max_closed_days, int((dt - current_start).days))
            current_start = None
    open_days = int((nav.index[-1] - current_start).days) if current_start is not None else 0
    return {
        "max_closed_underwater_days": max_closed_days,
        "open_underwater_days": open_days,
        "is_currently_underwater": bool(current_start is not None),
    }


def summarize(nav: pd.Series, window_name: str, offset: pd.DateOffset | None) -> dict[str, object]:
    nav = nav.dropna()
    if offset is None:
        part = nav.copy()
    else:
        part = nav.loc[nav.index >= nav.index[-1] - offset].copy()
    part = part / part.iloc[0]
    daily_ret = part.pct_change().dropna()
    elapsed_years = (part.index[-1] - part.index[0]).days / 365.25
    annual_return = part.iloc[-1] ** (1.0 / elapsed_years) - 1.0
    max_dd = (part / part.cummax() - 1.0).min()
    vol = daily_ret.std() * np.sqrt(252.0)
    stats = underwater_stats(part)
    return {
        "window": window_name,
        "start": part.index[0].date().isoformat(),
        "end": part.index[-1].date().isoformat(),
        "rows": int(len(part)),
        "annual_return": float(annual_return),
        "max_drawdown": float(max_dd),
        "sharpe": float(annual_return / vol) if vol and vol > 0 else np.nan,
        "total_return": float(part.iloc[-1] - 1.0),
        **stats,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mod = load_module()
    daily_returns, audit = run_v76_sleeves(mod)
    common_start = max(series.index[0] for series in daily_returns.values())
    common_end = min(series.index[-1] for series in daily_returns.values())
    rows = []
    navs = {}
    for scenario, weights in SCENARIOS.items():
        nav = build_combo_nav(daily_returns, weights, common_start, common_end)
        navs[scenario] = nav
        pd.DataFrame({"date": nav.index, "nav": nav.values}).to_csv(
            OUT_DIR / f"daily_{scenario}.csv",
            index=False,
            encoding="utf-8-sig",
        )
        for window_name, offset in WINDOWS.items():
            rows.append({"scenario": scenario, **summarize(nav, window_name, offset)})
    summary = pd.DataFrame(rows)
    base = summary[summary["scenario"] == "current_10_15_15_60"].set_index("window")
    for idx, row in summary.iterrows():
        b = base.loc[row["window"]]
        summary.loc[idx, "annual_return_delta_vs_current"] = row["annual_return"] - b["annual_return"]
        summary.loc[idx, "max_drawdown_delta_vs_current"] = row["max_drawdown"] - b["max_drawdown"]
        summary.loc[idx, "sharpe_delta_vs_current"] = row["sharpe"] - b["sharpe"]
    summary.to_csv(OUT_DIR / "summary.csv", index=False, encoding="utf-8-sig")
    sleeve_rows = []
    for name, ret in daily_returns.items():
        nav = (1.0 + ret.loc[(ret.index >= common_start) & (ret.index <= common_end)]).cumprod()
        sleeve_rows.append({"sleeve": name, **summarize(nav / nav.iloc[0], "full_common", None)})
    pd.DataFrame(sleeve_rows).to_csv(OUT_DIR / "sleeves.csv", index=False, encoding="utf-8-sig")
    audit.update(
        {
            "classification": "V7.6 full four-sleeve weight check",
            "script": str(SCRIPT),
            "common_start": common_start.date().isoformat(),
            "common_end": common_end.date().isoformat(),
            "scenarios": SCENARIOS,
            "annual_return_method": "calendar elapsed years from daily NAV",
            "vol_sharpe_trading_days": 252,
        }
    )
    (OUT_DIR / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

from __future__ import annotations

import builtins
import importlib.util
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "mnt_bot V 7.6 plus.py"
OUT_DIR = Path(__file__).resolve().parent
WINDOW_YEARS = [10, 8, 6, 4, 2, 1]


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
    spec = importlib.util.spec_from_file_location("mnt_bot_v76_r2_combo_check", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    module.poe = PoeStub()
    spec.loader.exec_module(module)
    return module


@contextmanager
def temp_globals(mod, updates: dict[str, object]):
    old = {key: getattr(mod, key) for key in updates}
    try:
        for key, value in updates.items():
            setattr(mod, key, value)
        yield
    finally:
        for key, value in old.items():
            setattr(mod, key, value)


def build_combined_daily_nav(mod, daily_returns: dict[str, pd.Series]) -> pd.Series:
    weights = mod._performance_combo_weights()
    common_start = max(series.dropna().index[0] for series in daily_returns.values())
    nav_parts = {}
    for name, ret in daily_returns.items():
        part = pd.to_numeric(ret, errors="coerce").dropna().sort_index()
        part = part.loc[part.index >= common_start]
        nav = (1.0 + part).cumprod()
        nav_parts[name] = nav / nav.iloc[0]
    all_dates = pd.DatetimeIndex(sorted(set().union(*(s.index for s in nav_parts.values()))))
    all_dates = all_dates[all_dates >= common_start]
    nav_df = pd.DataFrame({name: series.reindex(all_dates).ffill() for name, series in nav_parts.items()})
    wdf = nav_df.notna().astype(float)
    for col in wdf.columns:
        wdf[col] *= weights.get(col, 0.0)
    wdf = wdf.div(wdf.sum(axis=1).replace(0.0, np.nan), axis=0)
    nav = (nav_df.fillna(0.0) * wdf).sum(axis=1)
    return nav / nav.iloc[0]


def summarize_nav_window(nav: pd.Series, years: int, common_end: pd.Timestamp) -> dict[str, object]:
    part = nav.loc[(nav.index >= common_end - pd.DateOffset(years=years)) & (nav.index <= common_end)].dropna()
    part = part / part.iloc[0]
    elapsed_years = (part.index[-1] - part.index[0]).days / 365.25
    annual_return = part.iloc[-1] ** (1.0 / elapsed_years) - 1.0
    max_drawdown = (part / part.cummax() - 1.0).min()
    daily_ret = part.pct_change().dropna()
    annual_vol = daily_ret.std() * np.sqrt(244.0)
    return {
        "window": f"{years}Y",
        "start": part.index[0].date().isoformat(),
        "end": part.index[-1].date().isoformat(),
        "rows": int(len(part)),
        "annual_return": float(annual_return),
        "max_drawdown": float(max_drawdown),
        "sharpe": float(annual_return / annual_vol) if annual_vol and annual_vol > 0 else np.nan,
        "total_return": float(part.iloc[-1] - 1.0),
    }


def run_case(mod, data, case_name: str, updates: dict[str, object]) -> pd.Series:
    cn_close, cn_dk_close, us_rot_close, us_prod_daily, us_open = data
    engine = mod.CombinedStrategyV76()
    engine._us_open = us_open
    with temp_globals(mod, updates):
        cn_result, cn_dk_result, us_rot_result, *_ = engine._run_strategies(
            cn_close.copy(),
            cn_dk_close.copy(),
            us_rot_close.copy(),
            us_prod_daily.copy(),
        )
    daily_returns = {
        "Sub-A": cn_result["return"].dropna(),
        "Sub-A-DK": cn_dk_result["return"].dropna(),
        "Sub-B": us_rot_result["return"].dropna(),
    }
    nav = build_combined_daily_nav(mod, daily_returns)
    daily = pd.DataFrame({"Combined_NAV": nav})
    for name, ret in daily_returns.items():
        daily[f"{name}_return"] = ret.reindex(daily.index)
    daily.index.name = "date"
    daily.to_csv(OUT_DIR / f"daily_{case_name}.csv", encoding="utf-8-sig")
    return nav


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mod = load_module()
    fetch_msg = NullMessage()
    fetch_engine = mod.CombinedStrategyV76()
    cn_close, cn_dk_close, us_rot_close, us_prod_daily = fetch_engine._fetch_data(
        fetch_msg,
        include_cn_live_snapshot=False,
        include_us_live_snapshot=False,
    )
    data = (cn_close, cn_dk_close, us_rot_close, us_prod_daily, getattr(fetch_engine, "_us_open", None))
    cases = {
        "old_020": {"CN_R2_THRESHOLD": 0.20},
        "current_025": {},
    }
    navs = {name: run_case(mod, data, name, updates) for name, updates in cases.items()}
    common_end = min(nav.index[-1] for nav in navs.values())
    rows = []
    base_rows = {}
    for case_name, nav in navs.items():
        for years in WINDOW_YEARS:
            row = {"case": case_name, **summarize_nav_window(nav, years, common_end)}
            rows.append(row)
            if case_name == "old_020":
                base_rows[row["window"]] = row
    summary = pd.DataFrame(rows)
    for idx, row in summary.iterrows():
        base = base_rows[row["window"]]
        summary.loc[idx, "annual_return_delta_vs_old_020"] = row["annual_return"] - base["annual_return"]
        summary.loc[idx, "max_drawdown_delta_vs_old_020"] = row["max_drawdown"] - base["max_drawdown"]
        summary.loc[idx, "sharpe_delta_vs_old_020"] = row["sharpe"] - base["sharpe"]
    summary.to_csv(OUT_DIR / "summary.csv", index=False, encoding="utf-8-sig")
    audit = {
        "script": str(SCRIPT),
        "classification": "no-microcap combo default check",
        "common_end": common_end.date().isoformat(),
        "cases": cases,
        "performance_weights_normalized": {k: float(v) for k, v in mod._performance_combo_weights().items()},
        "inputs": {
            "cn_close": [cn_close.index[0].date().isoformat(), cn_close.index[-1].date().isoformat(), int(len(cn_close))],
            "cn_dk_close": [cn_dk_close.index[0].date().isoformat(), cn_dk_close.index[-1].date().isoformat(), int(len(cn_dk_close))],
            "us_rot_close": [us_rot_close.index[0].date().isoformat(), us_rot_close.index[-1].date().isoformat(), int(len(us_rot_close))],
            "us_prod_daily": [us_prod_daily.index[0].date().isoformat(), us_prod_daily.index[-1].date().isoformat(), int(len(us_prod_daily))],
        },
        "fetch_log_tail": fetch_msg.lines[-40:],
    }
    (OUT_DIR / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

from __future__ import annotations

import importlib.util
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parent
BASE_SCRIPT = ROOT / "mnt_bot V 6.5 plus.py"
CN_CSV = ROOT / "mnt_strategy_data_cn.csv"
US_CSV = ROOT / "mnt_strategy_data_us.csv"
_REFRESHED_KEYS: set[tuple[str, str, str]] = set()


class _DummyPoe:
    class BotError(Exception):
        pass

    default_chat = ""
    query = types.SimpleNamespace(text="", attachments=[])

    @staticmethod
    def update_settings(*args, **kwargs):
        return None

    @staticmethod
    def start_message():
        raise RuntimeError("poe.start_message is unavailable in offline refresh mode")

    @staticmethod
    def call(*args, **kwargs):
        raise RuntimeError("poe.call is unavailable in offline refresh mode")


@dataclass
class RefreshSummary:
    path: Path
    latest_date: pd.Timestamp | None
    rows: int
    columns: list[str]


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    module.poe = _DummyPoe
    spec.loader.exec_module(module)
    return module


def _ordered_unique(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        out.append(value)
        seen.add(value)
    return out


def _read_numeric_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "date" not in df.columns:
        raise ValueError(f"missing date column in {path}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _looks_like_cn_secid(value: str) -> bool:
    return "." in value and not value.endswith("_spliced")


def _looks_like_us_ticker(value: str) -> bool:
    return "." not in value and not value.endswith("_spliced")


def filter_market_sessions(frame: pd.DataFrame, anchor_columns: Iterable[str]) -> pd.DataFrame:
    """Keep only rows where at least one anchor asset has an actual bar.

    This is used for stock/ETF strategy panels built from a union calendar that may
    also contain 24/7 assets such as BTC. Filtering before forward-fill prevents
    weekend crypto rows from becoming fake stock trading sessions.
    """
    if frame is None or len(frame) == 0:
        return frame
    anchors = [col for col in anchor_columns if col in frame.columns]
    if not anchors:
        return frame.sort_index()
    mask = frame[anchors].notna().any(axis=1)
    return frame.loc[mask].sort_index()


def build_emxc_spliced(frame: pd.DataFrame, switch_start: pd.Timestamp) -> pd.Series:
    if "EEM" not in frame.columns:
        raise ValueError("EEM column is required to build EMXC_spliced")
    hybrid = pd.to_numeric(frame["EEM"], errors="coerce").astype(float).copy().rename("EMXC_spliced")
    if "EMXC" not in frame.columns:
        return hybrid
    emxc = pd.to_numeric(frame["EMXC"], errors="coerce").astype(float).reindex(hybrid.index)
    switch_mask = hybrid.index >= pd.Timestamp(switch_start)
    if not switch_mask.any():
        return hybrid
    first_emxc_date = emxc.loc[switch_mask].first_valid_index()
    if first_emxc_date is None:
        return hybrid
    scale_factor = hybrid.loc[first_emxc_date] / emxc.loc[first_emxc_date]
    hybrid.loc[switch_mask] = (emxc.loc[switch_mask] * scale_factor).combine_first(hybrid.loc[switch_mask])
    return hybrid


def write_price_panel(path: Path, frame: pd.DataFrame) -> pd.Timestamp | None:
    panel = frame.copy()
    panel.index = pd.to_datetime(panel.index)
    panel = panel.sort_index()
    panel.index.name = "date"
    path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(path, index_label="date", encoding="utf-8-sig")
    if len(panel) == 0:
        return None
    return pd.Timestamp(panel.index[-1])


def _refresh_cn_panel(mod, existing: pd.DataFrame) -> pd.DataFrame:
    current_secids = list(getattr(mod, "CN_ALL_CODES", []))
    current_secids.extend(
        [
            getattr(mod, "CN_DK_ZZ1000_SECID", None),
            getattr(mod, "CN_DK_SZ50_SECID", None),
            getattr(mod, "CN_DK_HS300_SECID", None),
            getattr(mod, "CN_DK_ZZ500_SECID", None),
            getattr(mod, "CN_DK_CYB_SECID", None),
            getattr(mod, "CN_VOL_MONITOR_SECID", None),
        ]
    )
    existing_secids = [col for col in existing.columns if _looks_like_cn_secid(col)]
    required_secids = {secid for secid in current_secids if secid}
    secids = _ordered_unique(current_secids + existing_secids)

    refreshed = {}
    for secid in secids:
        try:
            df, _source = mod.fetch_cn_kline(secid)
            if df is None or len(df) == 0 or "close" not in df.columns:
                raise ValueError(f"empty CN series for {secid}")
            refreshed[secid] = pd.to_numeric(df["close"], errors="coerce").astype(float).rename(secid)
            if hasattr(mod, "_save_cn_official_cache"):
                mod._save_cn_official_cache(secid, df)
        except Exception:
            if secid in required_secids or secid not in existing.columns:
                raise
            refreshed[secid] = existing[secid].dropna().rename(secid)

    panel = pd.concat(refreshed.values(), axis=1).sort_index()
    preserved_cols = [col for col in existing.columns if col not in panel.columns and col.endswith("_spliced")]
    if preserved_cols:
        panel = panel.join(existing[preserved_cols], how="left")
    return panel


def _refresh_us_panel(mod, existing: pd.DataFrame) -> pd.DataFrame:
    current_tickers = list(getattr(mod, "US_ALL_TICKERS", []))
    legacy_tickers = ["VNQ"]
    existing_tickers = [col for col in existing.columns if _looks_like_us_ticker(col)]
    required_tickers = {ticker for ticker in current_tickers if ticker}
    tickers = _ordered_unique(current_tickers + legacy_tickers + existing_tickers)

    refreshed = {}
    stock_latest_dates = []
    for ticker in tickers:
        try:
            df, _source = mod.fetch_yahoo(ticker)
            if df is None or len(df) == 0 or "close" not in df.columns:
                raise ValueError(f"empty US series for {ticker}")
            series = pd.to_numeric(df["close"], errors="coerce").astype(float).rename(ticker)
            refreshed[ticker] = series
        except Exception:
            if ticker in required_tickers or ticker not in existing.columns:
                raise
            series = existing[ticker].dropna().rename(ticker)
            refreshed[ticker] = series
        if ticker != "BTC-USD":
            stock_latest_dates.append(series.dropna().index.max())

    panel = pd.concat(refreshed.values(), axis=1).sort_index()
    if stock_latest_dates:
        cutoff = max(dt for dt in stock_latest_dates if pd.notna(dt))
        panel = panel.loc[:cutoff]

    if {"EEM", "EMXC"}.issubset(panel.columns):
        panel["EMXC_spliced"] = build_emxc_spliced(
            panel[["EEM", "EMXC"]],
            getattr(mod, "US_ROT_EMXC_BT_START", pd.Timestamp("2017-08-01")),
        )
    return panel


def refresh_cn_strategy_data(
    *,
    csv_path: Path = CN_CSV,
    base_script_path: Path = BASE_SCRIPT,
    verbose: bool = False,
) -> RefreshSummary:
    key = ("cn", str(csv_path.resolve()), str(base_script_path.resolve()))
    if key in _REFRESHED_KEYS:
        current = _read_numeric_csv(csv_path)
        latest = pd.Timestamp(current.index[-1]) if len(current) else None
        return RefreshSummary(path=csv_path, latest_date=latest, rows=len(current), columns=list(current.columns))
    mod = _load_module(base_script_path, "local_refresh_cn_mod")
    existing = _read_numeric_csv(csv_path)
    panel = _refresh_cn_panel(mod, existing)
    latest = write_price_panel(csv_path, panel)
    _REFRESHED_KEYS.add(key)
    if verbose:
        print(f"CN refresh -> {csv_path} latest={latest.date() if latest is not None else 'NA'} rows={len(panel)}")
    return RefreshSummary(path=csv_path, latest_date=latest, rows=len(panel), columns=list(panel.columns))


def refresh_us_strategy_data(
    *,
    csv_path: Path = US_CSV,
    base_script_path: Path = BASE_SCRIPT,
    verbose: bool = False,
) -> RefreshSummary:
    key = ("us", str(csv_path.resolve()), str(base_script_path.resolve()))
    if key in _REFRESHED_KEYS:
        current = _read_numeric_csv(csv_path)
        latest = pd.Timestamp(current.index[-1]) if len(current) else None
        return RefreshSummary(path=csv_path, latest_date=latest, rows=len(current), columns=list(current.columns))
    mod = _load_module(base_script_path, "local_refresh_us_mod")
    existing = _read_numeric_csv(csv_path)
    panel = _refresh_us_panel(mod, existing)
    latest = write_price_panel(csv_path, panel)
    _REFRESHED_KEYS.add(key)
    if verbose:
        print(f"US refresh -> {csv_path} latest={latest.date() if latest is not None else 'NA'} rows={len(panel)}")
    return RefreshSummary(path=csv_path, latest_date=latest, rows=len(panel), columns=list(panel.columns))


def refresh_strategy_test_data(
    *,
    require_cn: bool = False,
    require_us: bool = False,
    cn_csv_path: Path = CN_CSV,
    us_csv_path: Path = US_CSV,
    base_script_path: Path = BASE_SCRIPT,
    verbose: bool = False,
) -> dict[str, RefreshSummary]:
    results: dict[str, RefreshSummary] = {}
    if require_cn:
        results["cn"] = refresh_cn_strategy_data(
            csv_path=cn_csv_path,
            base_script_path=base_script_path,
            verbose=verbose,
        )
    if require_us:
        results["us"] = refresh_us_strategy_data(
            csv_path=us_csv_path,
            base_script_path=base_script_path,
            verbose=verbose,
        )
    return results

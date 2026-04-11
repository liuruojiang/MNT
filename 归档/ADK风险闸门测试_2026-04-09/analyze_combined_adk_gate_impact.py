import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = ROOT.parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))
from local_data_refresh import refresh_cn_strategy_data, refresh_us_strategy_data

BASE_SCRIPT = ROOT / "mnt_bot V 6.4 plus_adk_three_state_test.py"
if not BASE_SCRIPT.exists():
    BASE_SCRIPT = WORKSPACE_ROOT / "mnt_bot V 6.4 plus.py"
CN_CACHE_DIR = WORKSPACE_ROOT / ".cn_official_cache"
CN_CSV = WORKSPACE_ROOT / "mnt_strategy_data_cn.csv"
US_CSV = WORKSPACE_ROOT / "mnt_strategy_data_us.csv"
OUTPUT_CSV = ROOT / "combined_adk_gate_impact.csv"


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
        raise RuntimeError("poe.start_message is unavailable in offline analysis mode")

    @staticmethod
    def call(*args, **kwargs):
        raise RuntimeError("poe.call is unavailable in offline analysis mode")


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    module.poe = _DummyPoe
    spec.loader.exec_module(module)
    return module


def _read_numeric_csv(csv_path: Path):
    df = pd.read_csv(csv_path)
    if "date" not in df.columns:
        raise ValueError(f"missing date column in {csv_path}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _cache_filename(secid: str) -> str:
    return secid.replace(".", "_") + ".csv"


def _load_cached_series(secid: str) -> pd.Series:
    path = CN_CACHE_DIR / _cache_filename(secid)
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.set_index("date")["close"].sort_index()


def _load_cn_close(mod):
    refresh_cn_strategy_data(csv_path=CN_CSV, base_script_path=BASE_SCRIPT, verbose=False)
    cols = list(mod.CN_EQUITY_CODES) + [mod.CN_BOND_CODE]
    close_df = pd.concat([_load_cached_series(code).rename(code) for code in cols], axis=1)
    return close_df.ffill().dropna()


def _load_cn_dk_close(mod):
    df = _read_numeric_csv(CN_CSV)
    dk_map = {
        mod.CN_DK_ZZ1000_SECID: mod.CN_DK_COLS[0],
        mod.CN_DK_SZ50_SECID: mod.CN_DK_COLS[1],
        mod.CN_DK_HS300_SECID: mod.CN_DK_COLS[2],
        mod.CN_DK_ZZ500_SECID: mod.CN_DK_COLS[3],
        mod.CN_DK_CYB_SECID: mod.CN_DK_COLS[4],
    }
    cn_dk_close = pd.concat(
        [df[[secid]].rename(columns={secid: col}) for secid, col in dk_map.items()],
        axis=1,
    )
    return cn_dk_close.ffill().dropna()


def _load_us_rotation_close(mod):
    refresh_us_strategy_data(csv_path=US_CSV, base_script_path=BASE_SCRIPT, verbose=False)
    df = _read_numeric_csv(US_CSV)
    rot_tickers_core = [t for t in list(mod.US_ROT_POOL) + ["BIL"] if t not in {"BTC-USD", "EMXC"}]
    if mod.US_ROT_EMXC_BT_PROXY not in rot_tickers_core:
        rot_tickers_core.append(mod.US_ROT_EMXC_BT_PROXY)
    us_rot_close = df[rot_tickers_core].copy().ffill().dropna(how="all")

    if "EMXC" in mod.US_ROT_POOL and mod.US_ROT_EMXC_BT_PROXY in us_rot_close.columns:
        eem_col = us_rot_close[mod.US_ROT_EMXC_BT_PROXY].copy()
        hybrid = eem_col.rename("EMXC")
        if "EMXC_spliced" in df.columns and df["EMXC_spliced"].notna().sum() > 0:
            hybrid = df["EMXC_spliced"].reindex(hybrid.index).combine_first(hybrid)
        elif "EMXC" in df.columns:
            emxc_ser = df["EMXC"].reindex(hybrid.index)
            switch_idx = hybrid.index >= mod.US_ROT_EMXC_BT_START
            if switch_idx.any() and emxc_ser.loc[switch_idx].first_valid_index() is not None:
                first_emxc_date = emxc_ser.loc[switch_idx].first_valid_index()
                scale_factor = hybrid.loc[first_emxc_date] / emxc_ser.loc[first_emxc_date]
                hybrid.loc[switch_idx] = emxc_ser.loc[switch_idx] * scale_factor
        us_rot_close["EMXC"] = hybrid
        if mod.US_ROT_EMXC_BT_PROXY in us_rot_close.columns and mod.US_ROT_EMXC_BT_PROXY not in mod.US_ROT_POOL:
            us_rot_close = us_rot_close.drop(columns=[mod.US_ROT_EMXC_BT_PROXY])

    if "BTC-USD" in df.columns:
        us_rot_close["BTC-USD"] = df["BTC-USD"].reindex(us_rot_close.index)
    if "SPY" in df.columns and "SPY" not in us_rot_close.columns:
        us_rot_close["SPY"] = df["SPY"].reindex(us_rot_close.index)

    keep_cols = sorted(set(list(mod.US_ROT_POOL) + ["BIL", "SPY"]))
    return us_rot_close[[c for c in keep_cols if c in us_rot_close.columns]].ffill().dropna()


def _load_us_prod_daily(mod):
    refresh_us_strategy_data(csv_path=US_CSV, base_script_path=BASE_SCRIPT, verbose=False)
    df = _read_numeric_csv(US_CSV)
    needed = {cfg["proxy"] for cfg in mod.PROD_PORTFOLIO.values()} | {mod.PROD_CASH}
    return df[sorted(needed)].copy().ffill().dropna()


def _apply_adk_risk_gate(mod, dk_result, enter=0.15, scale_defense=0.5, exit_value=0.08, cooldown_days=0):
    base_ret = dk_result["return"].fillna(0.0)
    base_weight = dk_result["weight"].fillna(1.0)
    base_nav = (1.0 + base_ret).cumprod()
    base_dd = base_nav / base_nav.cummax() - 1.0

    gated_ret = []
    prev_scale = 1.0
    cooldown_left = 0

    for i, dt in enumerate(base_ret.index):
        if i == 0:
            cur_scale = 1.0
        else:
            prev_dt = base_ret.index[i - 1]
            prev_dd = float(base_dd.loc[prev_dt])
            trigger = prev_dd <= -enter
            release_ready = prev_dd >= -exit_value if exit_value is not None else prev_dd > -enter
            if trigger:
                cooldown_left = max(cooldown_left, cooldown_days)
                cur_scale = scale_defense
            elif prev_scale < 0.999999:
                if cooldown_left > 0:
                    cooldown_left -= 1
                    cur_scale = scale_defense
                else:
                    cur_scale = 1.0 if release_ready else scale_defense
            else:
                cur_scale = 1.0

        scaled_ret = base_ret.iloc[i] * cur_scale
        delta_scale = abs(cur_scale - prev_scale)
        overlay_tc = 0.0
        if delta_scale > 1e-12:
            overlay_tc = 2.0 * mod.CN_COMMISSION * delta_scale * float(base_weight.iloc[i])
        final_ret = (1.0 + scaled_ret) * (1.0 - overlay_tc) - 1.0
        gated_ret.append(final_ret)
        prev_scale = cur_scale

    out = dk_result.copy()
    out["return"] = pd.Series(gated_ret, index=base_ret.index)
    out["nav"] = (1.0 + out["return"]).cumprod()
    return out


def _compute_combined(mod, cn_ret, dk_ret, us_ret, subc_ret):
    cn_monthly = cn_ret.groupby(cn_ret.index.to_period("M")).apply(lambda x: (1 + x).prod() - 1)
    dk_monthly = dk_ret.groupby(dk_ret.index.to_period("M")).apply(lambda x: (1 + x).prod() - 1)
    us_monthly = us_ret.groupby(us_ret.index.to_period("M")).apply(lambda x: (1 + x).prod() - 1)
    subc_monthly = subc_ret.groupby(subc_ret.index.to_period("M")).apply(lambda x: (1 + x).prod() - 1)

    all_periods = cn_monthly.index.intersection(dk_monthly.index).intersection(us_monthly.index).intersection(subc_monthly.index)
    aligned = pd.DataFrame(
        {
            "Sub-A": cn_monthly.reindex(all_periods),
            "Sub-A-DK": dk_monthly.reindex(all_periods),
            "Sub-B": us_monthly.reindex(all_periods),
            "Sub-C": subc_monthly.reindex(all_periods),
        }
    ).dropna()
    w = mod.COMBINED_WEIGHTS
    strat_cols = ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]
    nav_monthly = (1 + aligned[strat_cols]).cumprod()
    nav_comb_monthly = sum(nav_monthly[n] * w[n] for n in strat_cols)
    nav_comb_monthly = nav_comb_monthly / nav_comb_monthly.iloc[0]
    combined_monthly = nav_comb_monthly.pct_change()
    combined_monthly.iloc[0] = nav_comb_monthly.iloc[0] - 1
    monthly_metrics = mod.calc_monthly_metrics(combined_monthly)

    common_start = max(cn_ret.index[0], dk_ret.index[0], us_ret.index[0], subc_ret.index[0])
    nav_parts = {
        "Sub-A": (1 + cn_ret).cumprod(),
        "Sub-A-DK": (1 + dk_ret).cumprod(),
        "Sub-B": (1 + us_ret).cumprod(),
        "Sub-C": (1 + subc_ret).cumprod(),
    }
    nav_parts = {k: v / v.iloc[0] for k, v in nav_parts.items()}
    all_daily_dates = sorted(set().union(*(s.index for s in nav_parts.values())))
    all_daily_dates = [d for d in all_daily_dates if d >= common_start]
    nav_df = pd.DataFrame({n: s.reindex(pd.DatetimeIndex(all_daily_dates)).ffill() for n, s in nav_parts.items()})
    wdf = nav_df.notna().astype(float)
    for col in wdf.columns:
        wdf[col] *= w.get(col, 0.0)
    ws = wdf.sum(axis=1).replace(0, pd.NA)
    wdf = wdf.div(ws, axis=0)
    nav_comb_daily = (nav_df.fillna(0) * wdf).sum(axis=1)
    nav_comb_daily = nav_comb_daily / nav_comb_daily.iloc[0]
    comb_daily = nav_comb_daily.pct_change().dropna()

    out = dict(monthly_metrics)
    out["annual"] = ((nav_comb_daily.iloc[-1]) ** (365.25 / ((nav_comb_daily.index[-1] - nav_comb_daily.index[0]).days)) - 1) * 100
    out["total_return"] = (nav_comb_daily.iloc[-1] - 1) * 100
    out["max_dd"] = ((nav_comb_daily - nav_comb_daily.cummax()) / nav_comb_daily.cummax()).min() * 100
    out["calmar"] = out["annual"] / abs(out["max_dd"]) if out["max_dd"] != 0 else 0
    out["start"] = str(nav_comb_daily.index[0].date())
    out["end"] = str(nav_comb_daily.index[-1].date())
    out["days"] = len(comb_daily)
    return out


def main():
    mod = _load_module(BASE_SCRIPT, "combined_adk_gate_mod")

    cn_close = _load_cn_close(mod)
    cn_dk_close = _load_cn_dk_close(mod)
    common_cn = cn_close.index.intersection(cn_dk_close.index)
    cn_close = cn_close.reindex(common_cn).ffill().dropna()
    cn_dk_close = cn_dk_close.reindex(common_cn).ffill().dropna()

    us_rot_close = _load_us_rotation_close(mod)
    us_prod_daily = _load_us_prod_daily(mod)

    cn_result = mod.run_cn_strategy(cn_close.copy(), mod.CN_EQUITY_CODES)
    dk_result = mod.run_dk_strategy(cn_close.copy(), cn_dk_close.copy())
    us_rot_result = mod.run_us_rotation(
        us_rot_close.copy(),
        mod.US_ROT_POOL,
        btc_ticker=mod.US_ROT_BTC_TICKER,
        btc_start=mod.US_ROT_BTC_START,
        btc_max_w=mod.US_ROT_BTC_MAX_W,
    )
    if mod.US_ROT_VOLREG_ENABLED and "SPY" in us_rot_close.columns:
        us_rot_result = mod.apply_vol_regime_overlay(us_rot_result, us_rot_close["SPY"])

    prod_monthly = us_prod_daily.resample("M").last()
    prod_sig_a = mod.make_abs_mom_signals(prod_monthly, mod.PROD_ABS_MOM_LB)
    prod_sig_b = mod.make_sma_signals(prod_monthly, mod.PROD_SMA_WINDOW, mod.PROD_SMA_BAND)
    if not mod.PROD_USE_TIMING:
        prod_sig_a = pd.DataFrame(1.0, index=prod_sig_a.index, columns=prod_sig_a.columns)
        prod_sig_b = prod_sig_a.copy()
    subc_daily = mod._get_subc_daily_ret(us_prod_daily, prod_sig_a, prod_sig_b=prod_sig_b)

    combined_base = _compute_combined(
        mod,
        cn_result["return"].dropna(),
        dk_result["return"].dropna(),
        us_rot_result["return"].dropna(),
        subc_daily.dropna(),
    )

    dk_gated = _apply_adk_risk_gate(mod, dk_result, enter=0.15, scale_defense=0.5, exit_value=0.08, cooldown_days=0)
    combined_gated = _compute_combined(
        mod,
        cn_result["return"].dropna(),
        dk_gated["return"].dropna(),
        us_rot_result["return"].dropna(),
        subc_daily.dropna(),
    )

    rows = []
    for name, metrics in [("baseline", combined_base), ("adk_gate_15_0p5_8", combined_gated)]:
        row = {"variant": name}
        row.update(metrics)
        rows.append(row)
    delta = {"variant": "delta_gated_minus_base"}
    for key in ["annual", "max_dd", "sharpe", "calmar", "vol", "total_return", "win_rate", "days"]:
        if key in combined_base and key in combined_gated and combined_base[key] is not None and combined_gated[key] is not None:
            delta[key] = combined_gated[key] - combined_base[key]
    rows.append(delta)

    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(result.to_string(index=False))
    print(f"\nSaved: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()

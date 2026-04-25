import builtins
import importlib.util
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "mnt_bot V 7.0 plus.py"
OUT_DIR = ROOT / "docs" / "suba_mix_effect_20260424"

BASELINE = ("baseline_60_20_20", ((60, 20, 20),))
MIX_CANDIDATES = [
    ("mix_40_10__60_20__120_40", ((40, 10, 10), (60, 20, 20), (120, 40, 40))),
    ("mix_45_15__60_20__90_30", ((45, 15, 15), (60, 20, 20), (90, 30, 30))),
    ("mix_50_15__60_20__70_25", ((50, 15, 15), (60, 20, 20), (70, 25, 25))),
    ("mix_55_15__60_20__80_25", ((55, 15, 15), (60, 20, 20), (80, 25, 25))),
    ("mix_60_20__90_30__120_40", ((60, 20, 20), (90, 30, 30), (120, 40, 40))),
]
SEGMENTS = [
    ("last_5y", "2021-04-23", "2026-04-24"),
    ("last_10y", "2016-04-25", "2026-04-24"),
    ("full_common", None, None),
    ("bull_2019_2021", "2019-01-01", "2021-12-31"),
    ("bear_2022", "2022-01-01", "2022-12-31"),
    ("rebound_2023_now", "2023-01-01", "2026-04-24"),
]


class _PoeStub:
    query = None
    default_chat = []

    class BotError(Exception):
        pass

    def update_settings(self, settings):
        self.settings = settings


@dataclass
class CnContext:
    mod: object
    close_df: pd.DataFrame
    all_codes: list[str]
    asset_codes: list[str]


def load_module():
    old_poe = getattr(builtins, "poe", None)
    had_poe = hasattr(builtins, "poe")
    builtins.poe = _PoeStub()
    spec = importlib.util.spec_from_file_location("mnt_bot_v70_suba_mix", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if had_poe:
        builtins.poe = old_poe
    else:
        delattr(builtins, "poe")
    return mod


def build_context(mod) -> CnContext:
    cn_raw = {}
    for secid in mod.CN_STOCK_CODES:
        df, _source = mod.fetch_cn_kline(secid)
        cn_raw[secid] = df

    zzhl_df = cn_raw.get(mod.CN_ZZHL_INDEX_SECID)
    if zzhl_df is not None and len(zzhl_df) > 0:
        try:
            pre_df = mod._fetch_cn_csindex(mod.CN_ZZHL_PRE_INDEX_CODE)
            if pre_df is not None and len(pre_df) > 50:
                h20955_start = zzhl_df.index[0]
                pre_only = pre_df[pre_df.index < h20955_start].copy()
                if len(pre_only) > 0:
                    pre_only["close"] *= zzhl_df["close"].iloc[0] / pre_only["close"].iloc[-1]
                    cn_raw[mod.CN_ZZHL_INDEX_SECID] = pd.concat([pre_only, zzhl_df])
        except Exception:
            pass

    close_df = pd.concat(
        [cn_raw[s][["close"]].rename(columns={"close": s}) for s in mod.CN_STOCK_CODES],
        axis=1,
    ).ffill().dropna()

    try:
        bond_df, _ = mod.fetch_cn_kline(mod.CN_BOND_CODE)
        close_df[mod.CN_BOND_CODE] = bond_df["close"].reindex(close_df.index)
        close_df = close_df.ffill()
    except Exception:
        pass

    return CnContext(
        mod=mod,
        close_df=close_df,
        all_codes=[c for c in mod.CN_EQUITY_CODES + [mod.CN_BOND_CODE] if c in close_df.columns],
        asset_codes=[c for c in mod.CN_EQUITY_CODES if c in close_df.columns],
    )


def run_single_variant(ctx: CnContext, bias_n: int, mom_day: int, r2_window: int) -> pd.DataFrame:
    mod = ctx.mod
    old_bias_n = mod.CN_BIAS_N
    old_mom_day = mod.CN_MOM_DAY
    old_r2_window = mod.CN_R2_WINDOW
    try:
        mod.CN_BIAS_N = bias_n
        mod.CN_MOM_DAY = mom_day
        mod.CN_R2_WINDOW = r2_window
        result = mod.run_cn_strategy(ctx.close_df, mod.CN_EQUITY_CODES)
        if mod.CN_SA_CASH_OVERLAY_ENABLED:
            result = mod.apply_suba_cash_peak_decay_overlay(
                result,
                ctx.close_df,
                decay_ratio_threshold=mod.CN_SA_CASH_OVERLAY_DECAY_RATIO,
                recovery_ratio_threshold=mod.CN_SA_CASH_OVERLAY_RECOVERY_RATIO,
                commission=mod.CN_COMMISSION,
            )
        if mod.CN_SA_SAME_SIDE_OVERHEAT_ENABLED:
            result = mod.apply_suba_same_side_overheat_overlay(
                result,
                ctx.close_df,
                enter_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_ENTER,
                exit_threshold=mod.CN_SA_SAME_SIDE_OVERHEAT_EXIT,
                derisk_scale=mod.CN_SA_SAME_SIDE_OVERHEAT_DERISK_SCALE,
            )
        return result
    finally:
        mod.CN_BIAS_N = old_bias_n
        mod.CN_MOM_DAY = old_mom_day
        mod.CN_R2_WINDOW = old_r2_window


def sleeve_position_frame(ctx: CnContext, result: pd.DataFrame) -> pd.DataFrame:
    pos = pd.DataFrame(0.0, index=result.index, columns=ctx.asset_codes + ["cash_fraction"])
    holding = result["holding"].fillna("cash").astype(str)
    holding_fraction = result["holding_fraction"].fillna(0.0).astype(float)
    effective_weight = result["weight"].fillna(0.0).astype(float)
    for code in ctx.asset_codes:
        mask = holding == code
        pos.loc[mask, code] = effective_weight.loc[mask]
    pos["cash_fraction"] = np.where(holding == "cash", 1.0, 1.0 - holding_fraction.clip(0.0, 1.0))
    return pos


def combine_variants(ctx: CnContext, variants: tuple[tuple[int, int, int], ...]) -> pd.DataFrame:
    sleeve_results = [run_single_variant(ctx, *params) for params in variants]
    sleeve_positions = [sleeve_position_frame(ctx, res) for res in sleeve_results]
    avg_pos = sum(sleeve_positions) / len(sleeve_positions)

    close_ret = ctx.close_df[ctx.asset_codes].pct_change().fillna(0.0)
    risky = avg_pos[ctx.asset_codes].copy()
    cash = avg_pos["cash_fraction"].copy()
    prev_risky = risky.shift(1).fillna(0.0)
    prev_cash = cash.shift(1).fillna(1.0)
    gross = (prev_risky * close_ret.reindex(risky.index).fillna(0.0)).sum(axis=1) + prev_cash * ctx.mod.CN_RF_DAILY
    turnover = risky.sub(prev_risky).abs().sum(axis=1)
    turnover.iloc[0] = risky.iloc[0].abs().sum()
    trade_cost = turnover * ctx.mod.CN_COMMISSION
    net = (1.0 + gross) * (1.0 - trade_cost) - 1.0

    out = avg_pos.copy()
    out["return"] = net
    out["trade_cost"] = trade_cost
    out["turnover"] = turnover
    out["risky_weight"] = risky.sum(axis=1)
    out["nav"] = (1.0 + out["return"]).cumprod()
    return out


def calc_metrics(ret: pd.Series):
    ret = ret.dropna()
    if len(ret) < 20:
        return None
    nav = (1.0 + ret).cumprod()
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    if years <= 0:
        return None
    cagr = nav.iloc[-1] ** (1.0 / years) - 1.0
    vol = ret.std() * np.sqrt(244)
    sharpe = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    maxdd = (nav / nav.cummax() - 1.0).min()
    return {
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "maxdd": maxdd,
        "final_nav": nav.iloc[-1],
    }


def summarize(name: str, df: pd.DataFrame):
    rows = []
    for seg_name, start, end in SEGMENTS:
        seg = df if start is None else df.loc[start:end]
        metrics = calc_metrics(seg["return"])
        if metrics is None:
            continue
        row = {
            "strategy": name,
            "segment": seg_name,
            "start": seg.index[0].date().isoformat(),
            "end": seg.index[-1].date().isoformat(),
            "avg_risky_weight": seg["risky_weight"].mean() if "risky_weight" in seg else np.nan,
            "avg_turnover": seg["turnover"].mean() if "turnover" in seg else np.nan,
        }
        row.update(metrics)
        rows.append(row)
    return rows


def yearly_returns(name: str, df: pd.DataFrame):
    rows = []
    yearly = df["return"].groupby(df.index.year).apply(lambda s: (1.0 + s).prod() - 1.0)
    for year, value in yearly.items():
        rows.append({"strategy": name, "year": int(year), "return": float(value)})
    return rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mod = load_module()
    ctx = build_context(mod)

    results = {}
    all_rows = []
    yearly_rows = []

    for name, variants in [BASELINE] + MIX_CANDIDATES:
        results[name] = combine_variants(ctx, variants)
        all_rows.extend(summarize(name, results[name]))
        yearly_rows.extend(yearly_returns(name, results[name]))

    summary_df = pd.DataFrame(all_rows)
    yearly_df = pd.DataFrame(yearly_rows)
    score_df = summary_df[summary_df["segment"].isin(["last_5y", "last_10y", "full_common"])].copy()
    score_rank = score_df.groupby("segment")["sharpe"].rank(ascending=False, method="average")
    score_df["sharpe_rank"] = score_rank
    rank_df = (
        score_df.groupby("strategy")[["sharpe", "cagr", "maxdd", "sharpe_rank"]]
        .agg({"sharpe": "mean", "cagr": "mean", "maxdd": "mean", "sharpe_rank": "mean"})
        .sort_values(["sharpe_rank", "sharpe"], ascending=[True, False])
        .reset_index()
    )

    summary_df.to_csv(OUT_DIR / "summary.csv", index=False)
    yearly_df.to_csv(OUT_DIR / "yearly.csv", index=False)
    rank_df.to_csv(OUT_DIR / "rank.csv", index=False)

    lines = [
        "# Sub-A Mix Effect",
        "",
        "- Data source: production `fetch_cn_kline()` path from `mnt_bot V 7.0 plus.py`",
        "- Asset pool: 5 CN total-return indexes + 10Y treasury total-return index",
        "- Baseline: `bias_n=60, mom_day=20, r2_window=20`",
        "- Mix method: run each sleeve independently with production overlays, then average effective target weights and charge net turnover cost",
        "",
        "## Candidates",
    ]
    for name, variants in MIX_CANDIDATES:
        lines.append(f"- `{name}`: {variants}")

    lines.append("")
    lines.append("## Core")
    for seg in ["last_5y", "last_10y", "full_common"]:
        lines.append(f"### {seg}")
        sub = summary_df[summary_df["segment"] == seg].copy().sort_values("sharpe", ascending=False)
        for _, row in sub.iterrows():
            lines.append(
                f"- {row['strategy']}: CAGR {row['cagr']:.2%}, Sharpe {row['sharpe']:.3f}, MaxDD {row['maxdd']:.2%}"
            )
        lines.append("")

    (OUT_DIR / "summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()

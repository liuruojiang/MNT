"""Replay V8.0 CN audit findings offline from the repository root with Python -B.

Real archived prices and real archived volume features end on 2026-11-05.
Only the vendor history length and the separate feed outage are injected.
"""
import importlib.util
import io
from pathlib import Path
import sys

import openpyxl
import pandas as pd

spec = importlib.util.spec_from_file_location("auditv80cn", Path("mnt_bot V 8.0 plus.py"))
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
root = Path("research/data_quality/20261106_bond_intraday_acceptance/a_chain/end")
prices = pd.read_csv(root / "native_prices.csv", index_col=0, parse_dates=True).loc[:"2026-11-05"]
previous = prices.index[-1]
clock = pd.Timestamp("2026-11-06 08:30").to_pydatetime()
evidence = {previous: {c: {"close": float(prices[c].iloc[-1])} for c in prices}}
m.beijing_now = lambda: clock

def fetch(code, *, required_date, **kwargs):
    p = prices[[code]].rename(columns={code: "close"})
    if code != m.CN_EQUITY_CODES[1]:
        return p, "full"
    return m._fetch_cn_index_history(
        code, [("90 days", lambda: p.tail(90)), ("full", lambda: p)],
        required_date, verified_close=kwargs.get("verified_close"), min_rows=m.CN_MIN_HISTORY_ROWS)

m.fetch_cn_kline = fetch
obj = m.CombinedStrategyV80()
cut = obj._fetch_cn_price_panel(io.StringIO(), [(c, c, None) for c in m.CN_ALL_CODES],
                               clock, previous, previous, evidence)
archived = pd.read_pickle(root / "native_result.pkl").loc[:previous]
feat = archived[[c for c in archived if c.startswith("suba_volume_")]].copy()
feat.columns = feat.columns.str.removeprefix("suba_volume_")
m._load_suba_volume_signal = lambda **kw: (feat["rule_on"], feat)
for name, panel in [("complete", prices), ("short", cut)]:
    panel.attrs["cn_confirmed_close"] = previous
    q = obj._run_suba(panel, False)
    if name == "complete":
        complete = q
        assert q["weight"].iloc[-1] == 1.25
    else:
        assert len(panel) == 90 and q["weight"].iloc[-1] == 1.0 and pd.isna(q["scale_raw"].iloc[-1])
    print(name, len(panel), len(q), q.iloc[-1][["holding","weight","realized_vol","scale_raw","suba_volume_rule_scale"]].to_dict())
    print(m._suba_query_overview(q, -1))
def missing(**kwargs):
    raise m.DataUnavailableError("offline simulated amount-feed outage")
m._load_suba_volume_signal = missing
unresolved = obj._run_suba(prices, True)
cutoff = previous - pd.Timedelta(days=60)
def confirmed(frame):
    rec = m.extract_v78_suba_rebalances(frame, prices, since_date=cutoff)
    return m._filter_confirmed_records(rec, bj_now=clock)
actual = confirmed(unresolved)
control = confirmed(complete)
as_key = lambda row: (row["日期"], row["卖出"], row["买入"])
control_keys = {as_key(row) for row in control}
extras = [row for row in actual if as_key(row) not in control_keys]
print("outage: unresolved=", bool(unresolved["suba_volume_unresolved"].all()), "confirmed rows=", len(actual),
      "control rows=", len(control), "outage-only=", len(extras), "first=", extras[0] if extras else None)
signal_info = m._write_a_adk_query_overview(lambda s:None, unresolved, None, query_kind="signal", cn_price_frame=prices)
xlsx = m.generate_signal_excel(previous.strftime("%Y%m%d"), signal_info, actual)
book = openpyxl.load_workbook(io.BytesIO(xlsx), read_only=True)
print("sheets=",book.sheetnames)
for ws in book:
    print(ws.title, list(ws.values)[:3])
assert len(extras) > 0 and unresolved["suba_volume_unresolved"].all()

# The archived close-based model really used the bond leg on this date.
# The probe establishes the time mismatch; it has no actual 15:00 bond quote
# and does not assert a different selection or a change in realized profit.
bond_day = pd.Timestamp("2026-10-09")
row = next(r for r in control if r["日期"] == bond_day.strftime("%Y-%m-%d"))
assert complete.at[bond_day, "holding"] == m.CN_BOND_CODE
assert row["买入"] == m.CN_BOND_NAME and "15:00" in row["北京时间"]
assert row["买入价格"] == prices.at[bond_day, m.CN_BOND_CODE]

class FirstMinuteRequest(Exception):
    pass

def stop_before_network(*args, **kwargs):
    raise FirstMinuteRequest

m._fetch_cn_trend_rows = stop_before_network
for when in ("15:00:00", "15:29:59", "15:30:00"):
    asof = pd.Timestamp(f"{bond_day.date()} {when}")
    try:
        proof = m._fetch_cn_final_sessions(m.CN_BOND_CODE, [bond_day], asof)
    except FirstMinuteRequest:
        assert when == "15:30:00"
        print(f"bond {when}: first eligible minute-proof request; proof still depends on vendor")
    else:
        assert when != "15:30:00" and not proof
        print(f"bond {when}: no completed-session proof allowed")
print("real close-based bond switch:", row)

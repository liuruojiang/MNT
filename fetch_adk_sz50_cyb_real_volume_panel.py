"""Fetch real same-source CYB/SZ50 volume panels for SZ50/CYB spread research."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

import scan_adk_sz50_cyb_reverse_spread_long_only as base

OUTPUT_CSV = base.ROOT / "outputs" / "adk_sz50_cyb_volume_sohu_real.csv"
OUTPUT_META = base.ROOT / "outputs" / "adk_sz50_cyb_volume_sohu_real_meta.json"
OUTPUT_SINA_CSV = base.ROOT / "outputs" / "adk_sz50_cyb_volume_sina_crosscheck.csv"

SPECS = [
    ("cyb", "0.399006", "ChiNext"),
    ("sz50", "1.000016", "SSE50"),
]


def fetch_source(mod, source: str, secid: str) -> pd.DataFrame:
    if source == "Sohu":
        return mod._fetch_cn_sohu_amount(secid, beg="20000101", lmt=10000)
    if source == "Sina":
        return mod._fetch_cn_sina_amount_proxy(secid)
    if source == "EastMoney":
        return mod._fetch_cn_eastmoney_amount(secid, beg="20000101", lmt=10000)
    if source == "CSIndex":
        return mod._fetch_cn_csindex_amount(secid, beg="20000101", lmt=10000)
    raise ValueError(source)


def build_panel(frames: dict[str, pd.DataFrame], source: str) -> pd.DataFrame:
    parts = []
    for label, _secid, _name in SPECS:
        d = frames[label][["close", "volume", "amount"]].copy()
        d = d.rename(columns={"close": f"{label}_close", "volume": f"{label}_volume", "amount": f"{label}_amount"})
        parts.append(d)
    panel = pd.concat(parts, axis=1).sort_index()
    panel.index.name = "date"
    panel["source"] = source
    return panel


def source_snapshot(df: pd.DataFrame) -> dict[str, object]:
    volume = pd.to_numeric(df["volume"], errors="coerce")
    amount = pd.to_numeric(df["amount"], errors="coerce")
    return {
        "rows": int(len(df)),
        "first_date": str(df.index.min().date()),
        "last_date": str(df.index.max().date()),
        "volume_positive_rows": int((volume > 0).sum()),
        "amount_positive_rows": int((amount > 0).sum()),
        "latest_volume": float(volume.dropna().iloc[-1]) if not volume.dropna().empty else None,
        "latest_amount": float(amount.dropna().iloc[-1]) if not amount.dropna().empty else None,
    }


def main() -> None:
    mod = base.base_scan.load_v77()
    attempts: dict[str, dict[str, object]] = {}
    fetched: dict[str, dict[str, pd.DataFrame]] = {}
    for source in ["EastMoney", "CSIndex", "Sina", "Sohu"]:
        attempts[source] = {}
        fetched[source] = {}
        for label, secid, name in SPECS:
            try:
                df = fetch_source(mod, source, secid)
                fetched[source][label] = df
                attempts[source][label] = {"ok": True, "secid": secid, "name": name, **source_snapshot(df)}
            except Exception as exc:
                attempts[source][label] = {"ok": False, "secid": secid, "name": name, "error_type": type(exc).__name__, "error": str(exc)}

    if set(fetched["Sohu"].keys()) != {"cyb", "sz50"}:
        raise RuntimeError("Sohu did not return both CYB and SZ50 volume series")

    sohu_panel = build_panel(fetched["Sohu"], "Sohu amount endpoint")
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    sohu_panel.to_csv(OUTPUT_CSV, encoding="utf-8-sig")

    if set(fetched["Sina"].keys()) == {"cyb", "sz50"}:
        build_panel(fetched["Sina"], "Sina volume proxy").to_csv(OUTPUT_SINA_CSV, encoding="utf-8-sig")

    formal = sohu_panel.loc[(sohu_panel.index >= pd.Timestamp(base.base_scan.FORMAL_START)) & (sohu_panel.index <= pd.Timestamp("2026-06-05"))]
    complete = formal[["cyb_volume", "sz50_volume"]].apply(pd.to_numeric, errors="coerce").dropna()
    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "primary_source": "Sohu amount endpoint",
        "primary_output_csv": str(OUTPUT_CSV),
        "sina_crosscheck_csv": str(OUTPUT_SINA_CSV) if OUTPUT_SINA_CSV.exists() else None,
        "direction_context": "long SZ50 / short CYB",
        "reason": "EastMoney failed during live refetch; CSIndex had SZ50 but no CYB mapping; Sohu provided same-source CYB and SZ50 volume.",
        "attempts": attempts,
        "formal_overlap_to_price_end": {
            "start": str(complete.index.min().date()),
            "end": str(complete.index.max().date()),
            "rows": int(len(complete)),
            "price_formal_start": str(pd.Timestamp(base.base_scan.FORMAL_START).date()),
            "price_formal_end": "2026-06-05",
        },
        "columns": list(sohu_panel.columns),
        "unit_note": "Use only own-MA relative volume features or unitless relative ratios; raw volume units are source-specific.",
    }
    OUTPUT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OUTPUT={OUTPUT_CSV}")
    print(f"META={OUTPUT_META}")
    print(f"FORMAL_COMPLETE={complete.index.min().date()}->{complete.index.max().date()} rows={len(complete)}")
    for source, result in attempts.items():
        print(source, {k: v.get("ok") for k, v in result.items()})


if __name__ == "__main__":
    main()

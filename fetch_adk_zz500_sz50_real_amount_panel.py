"""Fetch same-source official amount panel for ZZ500/SZ50 spread research."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

import scan_adk_zz500_sz50_spread_long_only as base


OUTPUT_CSV = base.ROOT / "outputs" / "adk_zz500_sz50_amount_csindex_official.csv"
OUTPUT_META = base.ROOT / "outputs" / "adk_zz500_sz50_amount_csindex_official_meta.json"

SPECS = [
    ("zz500", "1.000905", "CSI500"),
    ("sz50", "1.000016", "SSE50"),
]


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
        "source_values": sorted({str(x) for x in df.get("source", pd.Series(dtype=object)).dropna().unique()}),
    }


def build_panel(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    parts = []
    for label, _secid, _name in SPECS:
        d = frames[label][["close", "volume", "amount", "source"]].copy()
        d = d.rename(
            columns={
                "close": f"{label}_close",
                "volume": f"{label}_volume",
                "amount": f"{label}_amount",
                "source": f"{label}_source",
            }
        )
        parts.append(d)
    panel = pd.concat(parts, axis=1).sort_index()
    panel.index.name = "date"
    panel["source"] = "CSIndex official amount"
    return panel


def main() -> None:
    mod = base.load_v77()
    attempts: dict[str, object] = {}
    frames: dict[str, pd.DataFrame] = {}
    for label, secid, name in SPECS:
        try:
            df = mod._fetch_cn_csindex_amount(secid, beg="20000101", lmt=10000)
            frames[label] = df
            attempts[label] = {"ok": True, "secid": secid, "name": name, **source_snapshot(df)}
        except Exception as exc:
            attempts[label] = {
                "ok": False,
                "secid": secid,
                "name": name,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    if set(frames.keys()) != {"zz500", "sz50"}:
        raise RuntimeError(f"CSIndex did not return both ZZ500 and SZ50 amount series: {attempts}")

    panel = build_panel(frames)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUTPUT_CSV, encoding="utf-8-sig")

    formal = panel.loc[(panel.index >= base.FORMAL_START) & (panel.index <= pd.Timestamp("2026-06-05"))]
    complete = formal[["zz500_amount", "sz50_amount"]].apply(pd.to_numeric, errors="coerce").dropna()
    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "primary_source": "CSIndex official amount",
        "primary_output_csv": str(OUTPUT_CSV),
        "direction_context": "long ZZ500 / short SZ50",
        "reason": "Use same-source official CSIndex tradingValue for both spread legs.",
        "attempts": attempts,
        "formal_overlap_to_price_end": {
            "start": str(complete.index.min().date()),
            "end": str(complete.index.max().date()),
            "rows": int(len(complete)),
            "price_formal_start": str(base.FORMAL_START.date()),
            "price_formal_end": "2026-06-05",
        },
        "columns": list(panel.columns),
        "unit_note": "CSIndex tradingValue/amount units are used only as own-MA relative features or unitless pair-relative ratios.",
    }
    OUTPUT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OUTPUT={OUTPUT_CSV}")
    print(f"META={OUTPUT_META}")
    print(f"FORMAL_COMPLETE={complete.index.min().date()}->{complete.index.max().date()} rows={len(complete)}")
    print(json.dumps({k: v.get("ok") for k, v in attempts.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()

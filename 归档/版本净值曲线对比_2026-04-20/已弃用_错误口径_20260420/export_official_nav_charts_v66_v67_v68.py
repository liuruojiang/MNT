import importlib.util
import re
import sys
import types
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
CN_CSV = ROOT / "mnt_strategy_data_cn.csv"
US_CSV = ROOT / "mnt_strategy_data_us.csv"
OUT_DIR = Path(__file__).resolve().parent
SUMMARY_CSV = OUT_DIR / "official_nav_chart_compare_summary.csv"
SUMMARY_MD = OUT_DIR / "official_nav_chart_compare_summary.md"

VERSIONS = [
    ("V6.6", ROOT / "mnt_bot V 6.6 plus.py", "CombinedStrategyV65"),
    ("V6.7", ROOT / "mnt_bot V 6.7 plus.py", "CombinedStrategyV67"),
    ("V6.8", ROOT / "mnt_bot V 6.8 plus.py", "CombinedStrategyV68"),
]
WINDOWS = [
    ("1Y", pd.Timestamp("2025-04-20"), pd.Timestamp("2026-04-20")),
    ("3Y", pd.Timestamp("2023-04-20"), pd.Timestamp("2026-04-20")),
]


class _Msg:
    def __init__(self):
        self.parts = []
        self.attachments = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def write(self, text):
        self.parts.append(text)

    def attach_file(self, **kwargs):
        self.attachments.append(kwargs)


class _PoeStub(types.SimpleNamespace):
    pass


class _SettingsResponse(dict):
    pass


def _load_module(script_path: Path, module_name: str):
    poe = _PoeStub()
    poe.default_chat = ""
    poe.query = types.SimpleNamespace(text="", attachments=[])
    poe.update_settings = lambda *args, **kwargs: None
    poe.call = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("poe.call unavailable"))
    poe.BotError = Exception
    last_msg = {"value": None}

    def start_message():
        last_msg["value"] = _Msg()
        return last_msg["value"]

    poe.start_message = start_message

    spec = importlib.util.spec_from_file_location(module_name, str(script_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {script_path}")
    mod = importlib.util.module_from_spec(spec)
    mod.poe = poe

    poe_mod = types.ModuleType("fastapi_poe")
    poe_mod.BotError = Exception
    poe_mod.default_chat = ""
    poe_mod.query = poe.query
    poe_mod.update_settings = poe.update_settings
    poe_mod.start_message = poe.start_message
    poe_mod.call = poe.call
    poe_types_mod = types.ModuleType("fastapi_poe.types")
    poe_types_mod.SettingsResponse = _SettingsResponse

    old_poe = sys.modules.get("fastapi_poe")
    old_poe_types = sys.modules.get("fastapi_poe.types")
    sys.modules["fastapi_poe"] = poe_mod
    sys.modules["fastapi_poe.types"] = poe_types_mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if old_poe is None:
            sys.modules.pop("fastapi_poe", None)
        else:
            sys.modules["fastapi_poe"] = old_poe
        if old_poe_types is None:
            sys.modules.pop("fastapi_poe.types", None)
        else:
            sys.modules["fastapi_poe.types"] = old_poe_types
    return mod, poe, last_msg


def _load_local_cn_data(mod):
    df = pd.read_csv(CN_CSV)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    cn_cols = [c for c in getattr(mod, "CN_ALL_CODES", []) if c in df.columns]
    cn_close = df[cn_cols].copy().ffill().dropna(how="all")
    dk_map = {
        mod.CN_DK_ZZ1000_SECID: mod.CN_DK_COLS[0],
        mod.CN_DK_SZ50_SECID: mod.CN_DK_COLS[1],
        mod.CN_DK_HS300_SECID: mod.CN_DK_COLS[2],
        mod.CN_DK_ZZ500_SECID: mod.CN_DK_COLS[3],
        mod.CN_DK_CYB_SECID: mod.CN_DK_COLS[4],
    }
    cn_dk_close = pd.concat(
        [df[[secid]].rename(columns={secid: col}) for secid, col in dk_map.items() if secid in df.columns],
        axis=1,
    ).ffill().dropna()
    common_idx = cn_close.index.intersection(cn_dk_close.index)
    cn_close = cn_close.reindex(common_idx).ffill()
    cn_dk_close = cn_dk_close.reindex(common_idx).ffill().dropna()
    return cn_close, cn_dk_close


def _load_local_us_data():
    df = pd.read_csv(US_CSV)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _extract_combined_row(text: str):
    for line in text.splitlines():
        if "15/25/40/20" in line:
            parts = [p.strip() for p in line.strip().strip("|").split("|")]
            if len(parts) >= 4:
                try:
                    return {
                        "label": parts[0],
                        "final_nav": float(parts[1]),
                        "return_pct": float(parts[2].replace("%", "").replace("+", "")),
                        "max_dd_pct": float(parts[3].replace("%", "")),
                    }
                except ValueError:
                    pass
    m = re.search(r"Combined .*?\(\+?([-\d.]+)%\)", text)
    return {"label": "Combined", "final_nav": None, "return_pct": float(m.group(1)), "max_dd_pct": None} if m else None


def main():
    rows = []
    md_lines = [
        "# Official NAV Chart Compare",
        "",
        f"- CN CSV: `{CN_CSV.name}`",
        f"- US CSV: `{US_CSV.name}`",
        "",
    ]

    for version_label, script_path, class_name in VERSIONS:
        mod, poe, last_msg = _load_module(script_path, f"official_{version_label.lower().replace('.', '')}")
        cn_close, cn_dk_close = _load_local_cn_data(mod)
        us_df = _load_local_us_data()

        bot_cls = getattr(mod, class_name)
        bot = bot_cls()
        bot._get_all_data = lambda msg, _cn=cn_close, _dk=cn_dk_close, _us=us_df: (
            _cn.copy(), _dk.copy(), _us.copy(), _us.copy()
        )

        for window_label, start_date, end_date in WINDOWS:
            bot._parse_date_with_llm_fallback = lambda query, s=start_date, e=end_date: (s, e)
            query = f"净值曲线 强制{window_label}"
            poe.query = types.SimpleNamespace(text=query, attachments=[])
            mod.poe.query = poe.query
            last_msg["value"] = None
            bot._handle_nav_chart(query)
            msg = last_msg["value"]
            if msg is None:
                raise RuntimeError(f"no message captured for {version_label} {window_label}")

            image_bytes = None
            for a in msg.attachments:
                if a.get("content_type") == "image/png":
                    image_bytes = a["contents"]
                    break
            if image_bytes is None:
                raise RuntimeError(f"no png captured for {version_label} {window_label}")

            image_path = OUT_DIR / f"{version_label.lower().replace('.', '')}_official_nav_{window_label}.png"
            text_path = OUT_DIR / f"{version_label.lower().replace('.', '')}_official_nav_{window_label}.txt"
            image_path.write_bytes(image_bytes)
            text = "".join(msg.parts)
            text_path.write_text(text, encoding="utf-8")

            combined = _extract_combined_row(text)
            row = {
                "version": version_label,
                "window": window_label,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "image_path": str(image_path),
                "text_path": str(text_path),
            }
            if combined:
                row.update(combined)
            rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(SUMMARY_CSV, index=False, encoding="utf-8-sig")

    for window_label in [w[0] for w in WINDOWS]:
        md_lines.append(f"## {window_label}")
        md_lines.append("")
        subset = df[df["window"] == window_label]
        for _, row in subset.iterrows():
            md_lines.append(
                f"- `{row['version']}`: 组合收益 `{row.get('return_pct', float('nan')):.2f}%` / "
                f"组合最大回撤 `{row.get('max_dd_pct', float('nan')):.2f}%` / "
                f"图 `{Path(row['image_path']).name}`"
            )
        md_lines.append("")
    SUMMARY_MD.write_text("\n".join(md_lines), encoding="utf-8")
    print(df.to_string(index=False))
    print(f"\nSaved summary csv: {SUMMARY_CSV}")
    print(f"Saved summary md: {SUMMARY_MD}")


if __name__ == "__main__":
    main()

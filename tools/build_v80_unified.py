"""Build the self-contained V8.0 query bot from the frozen V7.8/V7.9 sources.

V8.0 keeps V7.9 as the hardened shared A/ADK/C and data path, then embeds a
namespaced copy of the complete V7.8 Sub-B call graph.  The generated bot runs
both B variants on the same fetched data and shows both targets in one query.
Portfolio/performance accounting assigns 50% of the Sub-B sleeve to each
version (20% + 20% of the total portfolio), while keeping both curves separate.
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V78_PATH = ROOT / "mnt_bot V 7.8 plus.py"
V79_PATH = ROOT / "mnt_bot V 7.9 plus.py"
OUTPUT_PATH = ROOT / "mnt_bot V 8.0 plus.py"

SUBB_ROOTS = {
    "_subb_active_ranking_codes",
    "run_us_rotation_mix",
    "run_subb_v75_ema_base7_rotation",
    "run_v78_subb_new_line",
    "blend_subb_v75_results",
    "blend_v78_subb_results",
    "apply_vol_regime_overlay",
    "_rebuild_subb_account_execution_costs",
    "extract_us_rot_rebalances",
    "extract_subb_volreg_rebalances",
    "_write_v78_subb_component_leg_tables",
    "_write_v78_subb_blend_table",
    "_write_v78_subb_param_tables",
    "_v78_subb_volume_warning",
}

# These constants are part of the V7.8 Sub-B contract even though the cloned
# call graph does not load all of them directly.  V8.0 uses them for the
# fetch-field union, fail-closed VolReg checks, and user-facing parameter cards.
SUBB_REQUIRED_GLOBALS = {
    "US_ROT_TOP_N",
    "US_ROT_VOLREG_ENABLED",
    "SUBB_REQUIRED_PRICE_TICKERS",
    "SUBB_REQUIRED_LIVE_PRICE_TICKERS",
    "US_ROT_REBALANCE_THRESHOLD",
    "US_ROT_TARGET_VOL",
    "US_ROT_MAX_LEV",
    "US_ROT_VOL_WINDOW",
    "US_ROT_VOLREG_SHORT_W",
    "US_ROT_VOLREG_LONG_W",
    "US_ROT_VOLREG_THRESHOLD",
    "US_ROT_VOLREG_EXIT_THRESHOLD",
    "US_ROT_VOLREG_DEFENSE_SCALE",
    "_ROT_PROXY_TO_LIVE",
}


def _simple_assignments(tree: ast.Module) -> dict[str, ast.Assign | ast.AnnAssign]:
    out: dict[str, ast.Assign | ast.AnnAssign] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = node
    return out


def _loaded_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }


def _prefix(name: str) -> str:
    return f"_v80_b78_{name.lstrip('_')}"


class _Rename(ast.NodeTransformer):
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping

    def visit_Name(self, node: ast.Name):  # noqa: N802 - ast API
        if node.id in self.mapping:
            return ast.copy_location(ast.Name(id=self.mapping[node.id], ctx=node.ctx), node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef):  # noqa: N802 - ast API
        node = self.generic_visit(node)
        if node.name in self.mapping:
            node.name = self.mapping[node.name]
        return node


def _build_v78_subb_namespace(source: str) -> str:
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assignments = _simple_assignments(tree)

    selected_functions: set[str] = set()
    pending = list(SUBB_ROOTS)
    while pending:
        name = pending.pop()
        if name in selected_functions:
            continue
        selected_functions.add(name)
        node = functions.get(name)
        if node is None:
            continue
        pending.extend((_loaded_names(node) & functions.keys()) - selected_functions)

    selected_globals: set[str] = set()
    pending_globals = [
        name
        for function_name in selected_functions
        for name in _loaded_names(functions[function_name])
        if name in assignments
    ] + [name for name in SUBB_REQUIRED_GLOBALS if name in assignments]
    while pending_globals:
        name = pending_globals.pop()
        if name in selected_globals:
            continue
        selected_globals.add(name)
        value = assignments[name].value
        pending_globals.extend((_loaded_names(value) & assignments.keys()) - selected_globals)

    # Runtime compatibility objects are shared with the V7.9 host module.  The
    # source assignment is self-referential (poe = install(poe)) and therefore
    # must not be namespaced like a strategy constant.
    selected_globals.discard("poe")

    mapping = {name: _prefix(name) for name in selected_functions | selected_globals}
    transformer = _Rename(mapping)
    emitted: list[str] = []

    for node in tree.body:
        assignment_name = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assignment_name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assignment_name = node.target.id
        if assignment_name in selected_globals:
            cloned = transformer.visit(copy.deepcopy(node))
            ast.fix_missing_locations(cloned)
            emitted.append(ast.unparse(cloned))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in selected_functions:
            cloned = transformer.visit(copy.deepcopy(node))
            ast.fix_missing_locations(cloned)
            emitted.append(ast.unparse(cloned))

    return "\n\n".join(emitted)


V80_RUNTIME = r'''

V80_SUBB_V78_SLEEVE_WEIGHT = 0.50
V80_SUBB_V79_SLEEVE_WEIGHT = 0.50
V80_SUBB_V78_TOP_N = 3
V80_SUBB_V78_PORTFOLIO_WEIGHT = PERFORMANCE_COMBO_WEIGHTS["B7.8"]
V80_SUBB_V79_PORTFOLIO_WEIGHT = PERFORMANCE_COMBO_WEIGHTS["B7.9"]
if not np.isclose(sum(PERFORMANCE_COMBO_WEIGHTS.values()), 1.0):
    raise RuntimeError("V8.0 portfolio weights must sum to 100%")
if not np.isclose(V80_SUBB_V78_SLEEVE_WEIGHT + V80_SUBB_V79_SLEEVE_WEIGHT, 1.0):
    raise RuntimeError("V8.0 B7.8/B7.9 sleeve weights must sum to 100%")
if not np.isclose(COMBINED_WEIGHTS["Sub-B"] * V80_SUBB_V78_SLEEVE_WEIGHT, V80_SUBB_V78_PORTFOLIO_WEIGHT):
    raise RuntimeError("V8.0 B7.8 portfolio weight is inconsistent with the Sub-B split")
if not np.isclose(COMBINED_WEIGHTS["Sub-B"] * V80_SUBB_V79_SLEEVE_WEIGHT, V80_SUBB_V79_PORTFOLIO_WEIGHT):
    raise RuntimeError("V8.0 B7.9 portfolio weight is inconsistent with the Sub-B split")

# Fetch the union required by both real Sub-B implementations.  This assignment
# intentionally occurs before the bot class executes, so _fetch_data cannot
# silently inherit the narrower V7.9-only field set.
SUBB_REQUIRED_PRICE_TICKERS = tuple(dict.fromkeys(
    list(SUBB_REQUIRED_PRICE_TICKERS) + list(_v80_b78_SUBB_REQUIRED_PRICE_TICKERS)
))
SUBB_REQUIRED_LIVE_PRICE_TICKERS = tuple(dict.fromkeys(
    list(SUBB_REQUIRED_LIVE_PRICE_TICKERS) + list(_v80_b78_SUBB_REQUIRED_LIVE_PRICE_TICKERS)
))
US_ALL_TICKERS = sorted(set(
    list(US_ALL_TICKERS)
    + list(SUBB_REQUIRED_PRICE_TICKERS)
    + list(SUBB_REQUIRED_LIVE_PRICE_TICKERS)
))


def _v80_subb_all_rot_tickers(available_tickers=None):
    available = set(US_ALL_TICKERS if available_tickers is None else available_tickers)
    return list(dict.fromkeys(
        list(US_ROT_POOL)
        + list(_v80_b78_US_ROT_POOL)
        + ["BIL"]
        + list(SUBB_INFLATION_GATE_TICKERS)
        + list(_v80_b78_SUBB_INFLATION_GATE_TICKERS)
        + [ticker for ticker in SUBB_OPTIONAL_MACRO_TICKERS if ticker in available]
    ))


def _v80_require_volreg_input(us_rot_close, *, enabled, label, long_window):
    if not enabled:
        return
    if not isinstance(us_rot_close, pd.DataFrame) or "SPY" not in us_rot_close.columns:
        raise ValueError(f"{label} VolReg requires SPY close data; field is missing")
    spy = pd.to_numeric(us_rot_close["SPY"], errors="coerce")
    finite_positive = spy.where(np.isfinite(spy) & (spy > 0)).dropna()
    minimum = int(long_window) + 2
    if len(finite_positive) < minimum:
        raise ValueError(
            f"{label} VolReg requires at least {minimum} finite positive SPY closes; "
            f"got {len(finite_positive)}"
        )
    if finite_positive.index[-1] != us_rot_close.index[-1]:
        raise ValueError(
            f"{label} VolReg SPY is stale: latest valid {finite_positive.index[-1]} "
            f"vs market data {us_rot_close.index[-1]}"
        )

def _run_v80_subb_v79(us_rot_close, us_open=None, strict_open_execution=True):
    _v80_require_volreg_input(
        us_rot_close,
        enabled=US_ROT_VOLREG_ENABLED,
        label="B7.9",
        long_window=US_ROT_VOLREG_LONG_W,
    )
    official = run_us_rotation_mix(
        us_rot_close,
        US_ROT_BASE_POOL,
        top_n=US_ROT_TOP_N,
        us_open=us_open,
        ranking_code_selector=_subb_active_ranking_codes,
        weight_assets=US_ROT_POOL,
        strict_open_execution=strict_open_execution,
    )
    ema = run_subb_v75_ema_base7_rotation(
        us_rot_close,
        base_codes=US_ROT_POOL,
        top_n=US_ROT_TOP_N,
        us_open=us_open,
        weight_assets=US_ROT_POOL,
        strict_open_execution=strict_open_execution,
    )
    v77 = blend_subb_v75_results(official, ema)
    bias = run_v78_subb_new_line(
        us_rot_close,
        line="bias",
        us_open=us_open,
        strict_open_execution=strict_open_execution,
    )
    logvol = run_v78_subb_new_line(
        us_rot_close,
        line="logvol",
        us_open=us_open,
        strict_open_execution=strict_open_execution,
    )
    result = blend_v78_subb_results(v77, bias, logvol)
    if US_ROT_VOLREG_ENABLED:
        result = apply_vol_regime_overlay(
            result,
            us_rot_close["SPY"],
            close_df=us_rot_close,
            us_open=us_open,
            strict_open_execution=strict_open_execution,
        )
    return _rebuild_subb_account_execution_costs(
        result,
        close_df=us_rot_close,
        us_open=us_open,
        strict_open_execution=strict_open_execution,
    )


def _run_v80_subb_v78(us_rot_close, us_open=None, strict_open_execution=True):
    _v80_require_volreg_input(
        us_rot_close,
        enabled=_v80_b78_US_ROT_VOLREG_ENABLED,
        label="B7.8",
        long_window=_v80_b78_US_ROT_VOLREG_LONG_W,
    )
    official = _v80_b78_run_us_rotation_mix(
        us_rot_close,
        _v80_b78_US_ROT_BASE_POOL,
        top_n=V80_SUBB_V78_TOP_N,
        us_open=us_open,
        ranking_code_selector=_v80_b78_subb_active_ranking_codes,
        weight_assets=_v80_b78_US_ROT_POOL,
        strict_open_execution=strict_open_execution,
    )
    ema = _v80_b78_run_subb_v75_ema_base7_rotation(
        us_rot_close,
        base_codes=_v80_b78_US_ROT_POOL,
        top_n=V80_SUBB_V78_TOP_N,
        us_open=us_open,
        weight_assets=_v80_b78_US_ROT_POOL,
        strict_open_execution=strict_open_execution,
    )
    v77 = _v80_b78_blend_subb_v75_results(official, ema)
    bias = _v80_b78_run_v78_subb_new_line(
        us_rot_close,
        line="bias",
        us_open=us_open,
        strict_open_execution=strict_open_execution,
    )
    logvol = _v80_b78_run_v78_subb_new_line(
        us_rot_close,
        line="logvol",
        us_open=us_open,
        strict_open_execution=strict_open_execution,
    )
    result = _v80_b78_blend_v78_subb_results(v77, bias, logvol)
    if _v80_b78_US_ROT_VOLREG_ENABLED:
        result = _v80_b78_apply_vol_regime_overlay(
            result,
            us_rot_close["SPY"],
            close_df=us_rot_close,
            us_open=us_open,
            strict_open_execution=strict_open_execution,
        )
    return _v80_b78_rebuild_subb_account_execution_costs(
        result,
        close_df=us_rot_close,
        us_open=us_open,
        strict_open_execution=strict_open_execution,
    )


def _run_v80_subb_variants(us_rot_close, us_open=None, strict_open_execution=True):
    b79 = _run_v80_subb_v79(us_rot_close, us_open=us_open, strict_open_execution=strict_open_execution)
    b78 = _run_v80_subb_v78(us_rot_close, us_open=us_open, strict_open_execution=strict_open_execution)
    b79.attrs["v80_b78"] = b78
    b79.attrs["v80_subb_weights"] = {
        "B7.8": V80_SUBB_V78_SLEEVE_WEIGHT,
        "B7.9": V80_SUBB_V79_SLEEVE_WEIGHT,
    }
    b79.attrs["v80_execution_boundary"] = (
        "B7.8 and B7.9 are independent after-cost subaccounts; portfolio/PV uses 50%/50% inside Sub-B"
    )
    return b79


def _v80_subb_results(us_rot_result):
    if us_rot_result is None:
        return None, None
    b78 = us_rot_result.attrs.get("v80_b78")
    if b78 is None:
        raise ValueError("V8.0 performance requires the independently computed B7.8 result")
    return b78, us_rot_result


def _v80_performance_daily_returns(cn_return, adk_return, us_rot_result, subc_return):
    b78, b79 = _v80_subb_results(us_rot_result)
    daily_returns = {
        "Sub-A": cn_return,
        "Sub-A-DK": adk_return,
        "B7.8": b78["return"],
        "B7.9": b79["return"],
        "Sub-C": subc_return,
    }
    daily_returns["Combined"] = _performance_combined_daily_returns(daily_returns)
    return daily_returns


def _v80_subb_mapping(label):
    return _v80_b78_ROT_PROXY_TO_LIVE if label == "B7.8" else _ROT_PROXY_TO_LIVE


def _v80_subb_variant_rows(result, idx=-1, min_weight=0.0005, label="B7.9"):
    if result is None or len(result) == 0:
        return []
    row = result.iloc[idx]
    assets = {
        col[2:]
        for col in result.columns
        if isinstance(col, str) and col.startswith("w_")
    } | {
        col[len("effective_w_"):]
        for col in result.columns
        if isinstance(col, str) and col.startswith("effective_w_")
    } | {
        col[len("actual_w_"):]
        for col in result.columns
        if isinstance(col, str) and col.startswith("actual_w_")
    } | {
        col[len("target_w_"):]
        for col in result.columns
        if isinstance(col, str) and col.startswith("target_w_")
    }
    rows = []
    mapping = _v80_subb_mapping(label)
    for asset in sorted(assets):
        current = float(row.get(
            f"effective_w_{asset}",
            row.get(f"w_{asset}", row.get(f"actual_w_{asset}", 0.0)),
        ) or 0.0)
        target = float(row.get(f"target_w_{asset}", current) or 0.0)
        if max(abs(current), abs(target), abs(target - current)) < min_weight:
            continue
        rows.append({
            "asset": asset,
            "live_name": mapping.get(asset, asset),
            "current": current,
            "target": target,
            "delta": target - current,
        })
    rows.sort(key=lambda item: (-abs(item["target"]), item["asset"]))
    return rows


def _v80_normalize_capital_config(config):
    out = dict(config or {})
    legacy = out.pop("Sub-B", None)
    if legacy is not None and "B7.8" not in out and "B7.9" not in out:
        amount = float(legacy)
        if not np.isfinite(amount) or amount <= 0:
            raise ValueError("legacy Sub-B capital must be finite and positive")
        out["B7.8"] = amount * V80_SUBB_V78_SLEEVE_WEIGHT
        out["B7.9"] = amount * V80_SUBB_V79_SLEEVE_WEIGHT
    return out


def _v80_normalize_position_config(config):
    out = dict(config or {})
    legacy = out.pop("Sub-B", None)
    if legacy:
        # One aggregate ledger cannot be attributed to two independent models.
        # Keep it only as a warning sentinel; never feed it to either order table.
        out["_V80_LEGACY_SUBB_UNSPLIT"] = legacy
    return out


def _v80_price_for_asset(us_rot_close, proxy, live):
    if not isinstance(us_rot_close, pd.DataFrame):
        return None
    for ticker in (live, proxy):
        if ticker not in us_rot_close.columns:
            continue
        values = pd.to_numeric(us_rot_close[ticker], errors="coerce")
        values = values.where(np.isfinite(values) & (values > 0)).dropna()
        if len(values) and values.index[-1] == us_rot_close.index[-1]:
            return float(values.iloc[-1])
    return None


def _v80_normalize_account_positions(positions, label):
    mapping = _v80_subb_mapping(label)
    out = {}
    for key, value in (positions or {}).items():
        live = mapping.get(str(key).upper(), str(key).upper())
        if live in out:
            raise poe.BotError(f"{label}持仓 {live} 重复，请只保留实盘代码或代理代码之一。")
        out[live] = value
    return out


def _v80_subb_account_rows(label, rows, us_rot_close):
    capital_config = _v80_normalize_capital_config(_scan_capital_config(poe.default_chat) or {})
    position_config = _v80_normalize_position_config(_scan_position_config(poe.default_chat) or {})
    capital = capital_config.get(label)
    positions = position_config.get(label) or {}
    if positions:
        positions = _v80_normalize_account_positions(positions, label)
    mapping = _v80_subb_mapping(label)
    live_prices = {
        item["live_name"]: _v80_price_for_asset(
            us_rot_close, item["asset"], item["live_name"]
        )
        for item in rows
    }
    live_prices = {key: value for key, value in live_prices.items() if value is not None}
    reverse_mapping = {live: proxy for proxy, live in mapping.items()}
    for live in positions:
        if live not in live_prices:
            price = _v80_price_for_asset(us_rot_close, reverse_mapping.get(live, live), live)
            if price is not None:
                live_prices[live] = price
    target_value = None
    target_source = None
    missing = []
    if positions:
        target_value, missing, target_source = _subb_position_adjustment_target_value(
            positions, live_prices, capital
        )
    elif capital is not None:
        target_value, target_source = float(capital), "capital"
    account_rows = []
    assets = set(positions)
    assets.update(item["live_name"] for item in rows)
    weight_by_live = {item["live_name"]: item["target"] for item in rows}
    for live in sorted(assets):
        raw = positions.get(live, 0)
        price = live_prices.get(live)
        current_shares = _pos_entry_shares(raw, price or 0)
        target_shares = (
            _subb_target_shares(target_value, weight_by_live.get(live, 0.0), price)
            if target_value is not None else None
        )
        if not _pos_entry_is_nonzero(raw) and target_shares in (0, None):
            continue
        account_rows.append({
            "live": live,
            "current": current_shares,
            "target": target_shares,
            "adjustment": None if target_shares is None else target_shares - current_shares,
        })
    return {
        "capital": capital,
        "positions": positions,
        "legacy_unsplit": bool(position_config.get("_V80_LEGACY_SUBB_UNSPLIT")),
        "target_value": target_value,
        "target_source": target_source,
        "missing": missing,
        "rows": account_rows,
    }


def _v80_map_rebalance_record(record, label):
    out = dict(record)
    out["策略"] = label
    mapping = _v80_subb_mapping(label)
    for field in ("卖出", "买入"):
        text = str(out.get(field, ""))
        for proxy, live in mapping.items():
            text = re.sub(rf"\b{re.escape(proxy)}\b", live, text)
        out[field] = text
    return out


def _v80_extract_subb_rebalances(us_rot_result, us_rot_close=None, us_open=None, since_date=None):
    b78, b79 = _v80_subb_results(us_rot_result)
    records = []
    for label, result in (("B7.8", b78), ("B7.9", b79)):
        base_extractor = _v80_b78_extract_us_rot_rebalances if label == "B7.8" else extract_us_rot_rebalances
        overlay_extractor = (
            _v80_b78_extract_subb_volreg_rebalances
            if label == "B7.8" else extract_subb_volreg_rebalances
        )
        base = base_extractor(result, us_rot_close=us_rot_close, us_open=us_open, since_date=since_date)
        overlay = overlay_extractor(result, us_rot_close=us_rot_close, us_open=us_open, since_date=since_date)
        records.extend(_v80_map_rebalance_record(item, label) for item in base + overlay)
    return records


def _write_v80_subb_overview(
    w, us_rot_result, *, query_kind="signal", us_intraday=False, us_rot_close=None
):
    w("## 🇺🇸 B策略双版本总览｜B7.8 + B7.9\n\n")
    w("> **资金规则：Sub-B 内 B7.8 / B7.9 各占 50%；折算总组合各占 20%。** "
      "两套 B 使用同一批行情独立计算、独立扣费；组合/PV按两条扣费后净值加权，"
      "下方目标仍分开显示，不混成一套持仓。查询区间共同起点按50/50建仓，"
      "之后随两条净值自然漂移，不额外做日频再平衡。\n\n")
    variants = [
        ("B7.8", us_rot_result.attrs.get("v80_b78") if us_rot_result is not None else None),
        ("B7.9", us_rot_result),
    ]
    signal_info = {}
    for label, result in variants:
        if result is None:
            raise ValueError(f"V8.0 {label} state is unavailable")
        rows = _v80_subb_variant_rows(result, -1, label=label)
        changed = any(abs(item["delta"]) >= 0.0005 for item in rows)
        mark = "🔴" if changed else "🟢"
        w(f"### {label}｜Sub-B的50% / 总组合20%｜{mark} {'目标变化' if changed else '维持'}\n\n")
        if query_kind in {"params", "live_params"}:
            last = result.iloc[-1]
            if label == "B7.8":
                top_n = V80_SUBB_V78_TOP_N
                abs_threshold = _v80_b78_US_ROT_ABS_THRESHOLD
                rebalance_threshold = _v80_b78_US_ROT_REBALANCE_THRESHOLD
                target_vol = _v80_b78_US_ROT_TARGET_VOL
                max_lev = _v80_b78_US_ROT_MAX_LEV
                volreg_enter = _v80_b78_US_ROT_VOLREG_THRESHOLD
                volreg_exit = _v80_b78_US_ROT_VOLREG_EXIT_THRESHOLD
            else:
                top_n = US_ROT_TOP_N
                abs_threshold = US_ROT_ABS_THRESHOLD
                rebalance_threshold = US_ROT_REBALANCE_THRESHOLD
                target_vol = US_ROT_TARGET_VOL
                max_lev = US_ROT_MAX_LEV
                volreg_enter = US_ROT_VOLREG_THRESHOLD
                volreg_exit = US_ROT_VOLREG_EXIT_THRESHOLD
            realized = last.get("realized_vol", last.get("official_realized_vol", np.nan))
            raw_scale = last.get("scale_raw", last.get("official_scale_raw", np.nan))
            effective_scale = last.get("volreg_effective_scale", 1.0)
            ratio = last.get("volreg_ratio", np.nan)
            w(
                f"参数: Top{top_n}｜绝对动量>{abs_threshold:.0%}｜挑战者/持仓比>{rebalance_threshold:.2f}x｜"
                f"目标波动{target_vol:.0%}｜杠杆上限{max_lev:.2f}x｜"
                f"VolReg进入/恢复={volreg_enter:.2f}/{volreg_exit:.2f}\n\n"
            )
            w(
                "当前测量: "
                f"已实现波动={realized:.1%}｜" if pd.notna(realized) else "当前测量: 已实现波动=N/A｜"
            )
            w(
                (f"原始scale={raw_scale:.2f}x｜" if pd.notna(raw_scale) else "原始scale=N/A｜")
                + (f"VolReg比率={ratio:.2f}｜" if pd.notna(ratio) else "VolReg比率=N/A｜")
                + f"Overlay乘数={float(effective_scale):.2f}x｜最终执行权重见下表\n\n"
            )
        if rows:
            w("| ETF | 当前已生效 | T收盘目标 | 调整量 |\n")
            w("|:-|------:|------:|------:|\n")
            for item in rows:
                delta_text = f"{item['delta']:+.1%}" if abs(item["delta"]) >= 0.0005 else "—"
                w(
                    f"| {item['live_name']} | {item['current']:.1%} | "
                    f"**{item['target']:.1%}** | {delta_text} |\n"
                )
        else:
            w("⚠️ 本版本 B 状态不可用。\n")
        account = _v80_subb_account_rows(label, rows, us_rot_close)
        if account["legacy_unsplit"]:
            w(
                "\n⚠️ 检测到旧版合并 Sub-B 持仓；无法安全拆分到 B7.8/B7.9。"
                "本次不生成任何 B 调仓数量，请分别设置两套持仓。\n"
            )
        elif account["missing"]:
            w("\n⚠️ 持仓价格缺失，数量计算已关闭: " + ", ".join(account["missing"]) + "\n")
        elif account["rows"]:
            source_text = "已设置资金" if account["target_source"] == "capital" else "本版本持仓市值"
            w(f"\n**{label}独立账户调整**（基于{source_text} ${account['target_value']:,.0f}）\n\n")
            w("| ETF | 当前股数 | 目标股数 | 调整 |\n|:-|------:|------:|------:|\n")
            for item in account["rows"]:
                if item["target"] is None:
                    target_text, adjustment_text = "价格缺失", "不执行"
                else:
                    target_text = f"{item['target']:,}"
                    adjustment_text = f"{item['adjustment']:+,}"
                w(f"| {item['live']} | {item['current']:,} | {target_text} | {adjustment_text} |\n")
        if query_kind in {"params", "live_params"}:
            action = "本页只核对参数；实际操作以“实时信号”为准。"
        elif us_intraday:
            action = "美股盘中目标未收盘确认；现在不执行，等待 T 收盘确认。"
        elif changed:
            action = "T收盘目标已确认；按 T+1 adjusted open 执行。已执行则勿重复。"
        else:
            action = "目标不变，维持；无需下单。"
        w(f"\n**现在怎么做：{action}**\n\n")
        signal_info[label] = {
            "is_signal": bool(changed),
            "signal_text": ", ".join(
                f"{item['live_name']} {item['target']:.1%}" for item in rows
            ) or "无目标",
            "note": "独立账户；T收盘确认后于T+1 adjusted open执行",
        }
    w("> 下方 A/ADK/C 与 B7.8/B7.9 详细表用于复核；两套 B 的最终目标分别以上方对应表为准。\n\n")
    return signal_info


def _write_v80_subc_overview(w, info=None, *, query_kind="signal", us_intraday=False):
    """Put Strategy C's current state and next action beside A/ADK/B."""
    w("## 🌐 C策略总览｜总组合30%\n\n")
    info = info or {}
    if not info:
        w("⚠️ C策略当前状态不可用；本次不生成正式调整指令。\n\n")
        return
    equity_current = float(info.get("current_scale", info.get("actual_scale", 1.0)))
    equity_raw = float(info.get("next_target_scale", info.get("target_scale", equity_current)))
    equity_next = float(info.get("next_scale", equity_current))
    gold_current = float(info.get("gold_current_scale", 1.0))
    gold_raw = float(info.get("gold_target_scale", gold_current))
    gold_next = float(info.get("gold_next_scale", gold_current))
    equity_changed = bool(info.get("pending_adjustment", abs(equity_next - equity_current) > 0.001))
    gold_changed = bool(info.get("gold_pending_adjustment", abs(gold_next - gold_current) > 0.001))
    rv = info.get("rv_latest_no_shift", info.get("realized_vol"))
    w("| 模块 | 当前已生效 | 最新raw | 下一执行 | 状态 |\n")
    w("|:-|------:|------:|------:|:-|\n")
    w(
        f"| 股票袖 | {equity_current:.2f}x | {equity_raw:.2f}x | **{equity_next:.2f}x** | "
        f"{'调整' if equity_changed else '维持'} |\n"
    )
    w(
        f"| 黄金袖 | {gold_current:.2f}x | {gold_raw:.2f}x | **{gold_next:.2f}x** | "
        f"{'调整' if gold_changed else '维持'} |\n"
    )
    w("| BTC/债券/CTA | 1.00x | 1.00x | **1.00x** | 固定 |\n")
    measurement = f"SPY已实现波动={float(rv):.1%}｜" if rv is not None and pd.notna(rv) else "SPY已实现波动=N/A｜"
    w(
        "\n当前测量: " + measurement
        + f"总毛敞口={float(info.get('next_gross_exposure', 1.0)):.1%}｜"
        + f"BIL={float(info.get('next_cash_exposure', 0.0)):.1%}｜"
        + f"融资={float(info.get('next_borrow_exposure', 0.0)):.1%}｜"
        + f"Overlay乘数={float(info.get('overlay_multiplier', 1.0)):.2f}x\n\n"
    )
    changed = equity_changed or gold_changed
    if query_kind in {"params", "live_params"}:
        action = "本页只核对参数；实际操作以“实时信号”为准。"
    elif us_intraday:
        action = "美股盘中raw可能变化；现在不执行，等待收盘确认。"
    elif changed:
        action = "收盘目标已确认；下一美股开盘执行。已执行则勿重复。"
    else:
        action = "股票袖与黄金袖均维持；无需下单。"
    w(f"**现在怎么做：{action}**\n\n")


def _write_v80_b78_detail(w, us_rot_result, *, query_kind="signal"):
    """Render the V7.8 reasoning block that the V7.9 host shell lacked."""
    b78, _ = _v80_subb_results(us_rot_result)
    if b78 is None or len(b78) == 0:
        w("### B7.8详细依据（Sub-B）\n\n⚠️ B7.8状态不可用。\n")
        return
    date_text = pd.Timestamp(b78.index[-1]).strftime("%Y-%m-%d")
    w("### B7.8详细依据（Sub-B）｜V7.8四腿综合\n\n")
    w(f"数据日期: **{date_text}**｜执行: **T收盘确认 → T+1 adjusted open**\n\n")
    changed = {
        live: cfg["proxy"]
        for live, cfg in _v80_b78_US_ROT_ASSETS.items()
        if live != cfg["proxy"]
    }
    if changed:
        w("实盘→proxy: " + ", ".join(f"{live}→{proxy}" for live, proxy in changed.items()) + "\n\n")
    if query_kind in {"params", "live_params"}:
        _v80_b78_write_v78_subb_param_tables(w)
    else:
        w(
            f"规则: Top{V80_SUBB_V78_TOP_N}｜绝对动量>{_v80_b78_US_ROT_ABS_THRESHOLD:.0%}｜"
            f"挑战者/持仓比>{_v80_b78_US_ROT_REBALANCE_THRESHOLD:.2f}x｜"
            f"目标波动{_v80_b78_US_ROT_TARGET_VOL:.0%}｜"
            f"VolReg进入/恢复={_v80_b78_US_ROT_VOLREG_THRESHOLD:.2f}/"
            f"{_v80_b78_US_ROT_VOLREG_EXIT_THRESHOLD:.2f}\n\n"
        )
        _v80_b78_write_v78_subb_component_leg_tables(w, b78, -1)
        _v80_b78_write_v78_subb_blend_table(w, b78, -1)
        warning = _v80_b78_v78_subb_volume_warning(b78)
        if warning:
            w("\n" + warning + "\n")
    row = b78.iloc[-1]
    realized = row.get("realized_vol", row.get("official_realized_vol", np.nan))
    raw_scale = row.get("scale_raw", row.get("official_scale_raw", np.nan))
    volreg_ratio = row.get("volreg_ratio", np.nan)
    overlay = row.get("volreg_effective_scale", 1.0)
    w("\n**B7.8当前风控链:** ")
    w(f"已实现波动={float(realized):.1%}｜" if pd.notna(realized) else "已实现波动=N/A｜")
    w(f"raw scale={float(raw_scale):.2f}x｜" if pd.notna(raw_scale) else "raw scale=N/A｜")
    w(f"VolReg比率={float(volreg_ratio):.2f}｜" if pd.notna(volreg_ratio) else "VolReg比率=N/A｜")
    w(f"Overlay乘数={float(overlay):.2f}x｜最终目标见前方B7.8总览。\n")
'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)


class _StripDeploymentDocstrings(ast.NodeTransformer):
    """Remove non-runtime docstrings from the Poe upload artifact."""

    _BODY_NODES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    def generic_visit(self, node):
        node = super().generic_visit(node)
        if isinstance(node, self._BODY_NODES) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
        return node


def _compact_poe_artifact(source: str) -> str:
    """Keep the self-contained bot below Poe's editor payload boundary."""
    tree = _StripDeploymentDocstrings().visit(ast.parse(source))
    ast.fix_missing_locations(tree)
    compact = (
        "# poe: name=Strategy-Signal-V80\n"
        "# poe: privacy_shield=half\n"
        + ast.unparse(tree)
        + "\n"
    )
    # Poe currently executes script bots on Python 3.11.  Fail the local build
    # if compaction ever emits syntax outside that grammar.
    ast.parse(compact, feature_version=(3, 11))
    return compact


def _apply_v80_performance_model(source: str) -> str:
    """Split the 40% Sub-B sleeve into two separately reported 20% sleeves."""
    source = _replace_once(
        source,
        'PERFORMANCE_COMBO_ORDER = ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]\n'
        'PERFORMANCE_COLUMNS = PERFORMANCE_COMBO_ORDER + ["Combined"]',
        'PERFORMANCE_COMBO_WEIGHTS = {\n'
        '    "Sub-A": 0.15,\n'
        '    "Sub-A-DK": 0.15,\n'
        '    "B7.8": 0.20,\n'
        '    "B7.9": 0.20,\n'
        '    "Sub-C": 0.30,\n'
        '}\n'
        'PERFORMANCE_COMBO_ORDER = list(PERFORMANCE_COMBO_WEIGHTS)\n'
        'PERFORMANCE_COLUMNS = PERFORMANCE_COMBO_ORDER + ["Combined"]',
        "performance weights",
    )
    source = _replace_once(
        source,
        'def _performance_combo_weights():\n'
        '    total = sum(COMBINED_WEIGHTS[name] for name in PERFORMANCE_COMBO_ORDER)\n'
        '    return {name: COMBINED_WEIGHTS[name] / total for name in PERFORMANCE_COMBO_ORDER}\n\n\n'
        'def _performance_combo_weight_label():\n'
        '    return "/".join(\n'
        '        str(int(round(COMBINED_WEIGHTS[name] * 100)))\n'
        '        for name in PERFORMANCE_COMBO_ORDER\n'
        '    )',
        'def _performance_combo_weights():\n'
        '    total = sum(PERFORMANCE_COMBO_WEIGHTS[name] for name in PERFORMANCE_COMBO_ORDER)\n'
        '    return {name: PERFORMANCE_COMBO_WEIGHTS[name] / total for name in PERFORMANCE_COMBO_ORDER}\n\n\n'
        'def _performance_combo_weight_label():\n'
        '    return "/".join(\n'
        '        str(int(round(PERFORMANCE_COMBO_WEIGHTS[name] * 100)))\n'
        '        for name in PERFORMANCE_COMBO_ORDER\n'
        '    )',
        "performance weight helpers",
    )
    return source


def _apply_v80_daily_math(source: str) -> str:
    """Install one validated union-calendar PV engine for every V8 surface."""
    start = source.index("def _performance_combined_daily_returns(daily_returns):")
    end = source.index("def _performance_standard_window_rows(", start)
    replacement = r'''def _performance_clean_daily_returns(ret_series, *, name="series"):
    raw = pd.Series(ret_series).copy()
    if len(raw) == 0:
        return pd.Series(dtype=float)
    if not isinstance(raw.index, pd.DatetimeIndex):
        try:
            parsed_index = pd.to_datetime(raw.index, errors="raise")
        except Exception as exc:
            raise ValueError(f"{name}: daily returns require a DatetimeIndex") from exc
        if not isinstance(parsed_index, pd.DatetimeIndex):
            raise ValueError(f"{name}: mixed-timezone or invalid daily index")
        raw.index = parsed_index
    if raw.index.tz is not None:
        raw.index = raw.index.tz_localize(None)
    raw.index = raw.index.normalize()
    if raw.index.has_duplicates:
        duplicates = raw.index[raw.index.duplicated()].unique()
        raise ValueError(f"{name}: duplicate daily dates: {duplicates[0].date()}")
    raw = raw.sort_index()
    values = pd.to_numeric(raw, errors="coerce")
    valid = values.notna()
    if not valid.any():
        return pd.Series(dtype=float)
    first = int(np.flatnonzero(valid.to_numpy())[0])
    last = int(np.flatnonzero(valid.to_numpy())[-1])
    values = values.iloc[first:last + 1]
    if values.isna().any():
        bad_date = values.index[values.isna()][0]
        raise ValueError(f"{name}: internal missing return at {bad_date.date()}")
    arr = values.to_numpy(dtype=float)
    if not np.isfinite(arr).all():
        bad_date = values.index[~np.isfinite(arr)][0]
        raise ValueError(f"{name}: non-finite return at {bad_date.date()}")
    if (arr <= -1.0).any():
        bad_date = values.index[arr <= -1.0][0]
        raise ValueError(f"{name}: return must be greater than -100% at {bad_date.date()}")
    return values.astype(float)


def _performance_combined_daily_returns(daily_returns):
    series_map = {}
    for name in PERFORMANCE_COMBO_ORDER:
        value = daily_returns.get(name)
        if value is None:
            continue
        cleaned = _performance_clean_daily_returns(value, name=name)
        if len(cleaned) > 1:
            series_map[name] = cleaned
    if len(series_map) < len(PERFORMANCE_COMBO_ORDER):
        return pd.Series(dtype=float)
    common_start = max(series.index[0] for series in series_map.values())
    latest_by_name = {name: series.index[-1] for name, series in series_map.items()}
    common_end = max(latest_by_name.values())
    earliest_end = min(latest_by_name.values())
    if common_end - earliest_end > pd.Timedelta(days=10):
        stale = min(latest_by_name, key=latest_by_name.get)
        raise ValueError(
            f"{stale}: stale sleeve end {latest_by_name[stale].date()} "
            f"vs combined end {common_end.date()}"
        )
    if common_end < common_start:
        return pd.Series(dtype=float)
    union_dates = pd.DatetimeIndex(sorted(set().union(*(
        series.loc[common_start:common_end].index for series in series_map.values()
    ))))
    if len(union_dates) <= 1:
        return pd.Series(dtype=float)
    component_nav = {}
    for name, series in series_map.items():
        # A closed market contributes a zero daily return, so its NAV stays
        # flat while another sleeve's market is open.
        aligned_returns = series.reindex(union_dates).fillna(0.0)
        component_nav[name] = (1.0 + aligned_returns).cumprod()
    nav_df = pd.DataFrame(component_nav, index=union_dates)
    weights = _performance_combo_weights()
    combined_nav = sum(nav_df[name] * weights[name] for name in PERFORMANCE_COMBO_ORDER)
    combined = combined_nav.pct_change()
    combined.iloc[0] = combined_nav.iloc[0] - 1.0
    return combined.astype(float)


def _performance_daily_window_metric(ret_series, requested_start, end_date):
    try:
        s = _performance_clean_daily_returns(ret_series, name="performance window")
    except ValueError as exc:
        return {"annual": None, "max_dd": None, "reason": str(exc)}
    if len(s) == 0:
        return {"annual": None, "max_dd": None, "reason": "no data"}
    end_ts = pd.Timestamp(end_date).tz_localize(None).normalize()
    s = s[s.index <= end_ts]
    if len(s) == 0:
        return {"annual": None, "max_dd": None, "reason": "no data before end date"}
    if end_ts - s.index[-1] > pd.Timedelta(days=10):
        return {
            "annual": None,
            "max_dd": None,
            "reason": (
                f"stale end: latest {s.index[-1].strftime('%Y-%m-%d')} "
                f"before required {end_ts.strftime('%Y-%m-%d')}"
            ),
        }
    if requested_start is not None:
        requested_start = pd.Timestamp(requested_start).tz_localize(None).normalize()
        first_available = s.index[0]
        if first_available > requested_start + pd.Timedelta(days=7):
            return {
                "annual": None,
                "max_dd": None,
                "reason": (
                    "insufficient post-start history: "
                    f"starts {first_available.strftime('%Y-%m-%d')} after required {requested_start.strftime('%Y-%m-%d')}"
                ),
            }
        s = s[s.index >= requested_start]
    if len(s) < PERFORMANCE_STANDARD_MIN_DAILY_ROWS:
        return {
            "annual": None,
            "max_dd": None,
            "reason": f"insufficient post-start history: {len(s)} daily rows",
        }
    years = (s.index[-1] - s.index[0]).days / 365.25
    if years <= 0:
        return {"annual": None, "max_dd": None, "reason": "insufficient post-start history: zero date span"}
    nav = (1.0 + s).cumprod()
    annual = (nav.iloc[-1] ** (1.0 / years) - 1.0) * 100.0
    return {
        "annual": float(annual),
        "max_dd": float(_max_drawdown_pct_from_nav(nav)),
        "reason": None,
        "start": s.index[0],
        "end": s.index[-1],
    }


'''
    source = source[:start] + replacement + source[end:]
    source = _replace_once(
        source,
        '        ser = pd.to_numeric(pd.Series(s), errors="coerce").dropna().sort_index()\n'
        '        if len(ser) > 0:\n'
        '            cleaned[name] = ser',
        '        ser = _performance_clean_daily_returns(s, name=name)\n'
        '        if len(ser) > 0:\n'
        '            cleaned[name] = ser',
        "standard windows use validated daily input",
    )
    return source


def _apply_v80_performance_surfaces(source: str) -> str:
    replacements = [
        (
            '        us_daily_ret = us_rot_result["return"]',
            '        b78_result, _ = _v80_subb_results(us_rot_result)\n'
            '        b78_daily_ret = b78_result["return"]\n'
            '        us_daily_ret = us_rot_result["return"]',
            "nav B result split",
        ),
        (
            '        us_period = us_daily_ret[(us_daily_ret.index >= start_date) & (us_daily_ret.index <= end_date)]',
            '        b78_period = b78_daily_ret[(b78_daily_ret.index >= start_date) & (b78_daily_ret.index <= end_date)]\n'
            '        us_period = us_daily_ret[(us_daily_ret.index >= start_date) & (us_daily_ret.index <= end_date)]',
            "nav B period split",
        ),
        (
            '        if all(len(s) < 2 for s in (cn_period, dk_period, us_period, subc_period)):',
            '        if all(len(s) < 2 for s in (cn_period, dk_period, b78_period, us_period, subc_period)):',
            "nav data availability",
        ),
        (
            '        if len(us_period) > 1:\n'
            '            nav_series["Sub-B"] = _nav_from_period_returns(us_period)',
            '        if len(b78_period) > 1:\n'
            '            nav_series["B7.8"] = _nav_from_period_returns(b78_period)\n'
            '        if len(us_period) > 1:\n'
            '            nav_series["B7.9"] = _nav_from_period_returns(us_period)',
            "nav separate B curves",
        ),
        (
            '            "Sub-B": us_period,',
            '            "B7.8": b78_period,\n'
            '            "B7.9": us_period,',
            "nav combined B inputs",
        ),
        (
            '            "Sub-B": "#2980B9",    # blue',
            '            "B7.8": "#3498DB",     # light blue\n'
            '            "B7.9": "#1F4E79",     # dark blue',
            "nav B colors",
        ),
        (
            '        chart_labels = {\n'
            '            "Sub-A": "Sub-A (CN Long)",\n'
            '            "Sub-A-DK": "Sub-A-DK (CN Long-Short)",\n'
            '            "Sub-B": "Sub-B (US Rotation)",',
            '        chart_labels = {\n'
            '            "Sub-A": "Sub-A (CN Long)",\n'
            '            "Sub-A-DK": "Sub-A-DK (CN Long-Short)",\n'
            '            "B7.8": "B7.8 (50% of Sub-B)",\n'
            '            "B7.9": "B7.9 (50% of Sub-B)",',
            "nav B chart labels",
        ),
        (
            '            "Sub-B": "Sub-B (美股轮动)",',
            '            "B7.8": "B7.8（Sub-B内50% / 总组合20%）",\n'
            '            "B7.9": "B7.9（Sub-B内50% / 总组合20%）",',
            "nav B table labels",
        ),
        (
            '        cn_daily_period = cn_result["return"][\n'
            '            (cn_result.index >= start_date) & (cn_result.index <= end_date)]',
            '        b78_result, _ = _v80_subb_results(us_rot_result)\n'
            '        cn_daily_period = cn_result["return"][\n'
            '            (cn_result.index >= start_date) & (cn_result.index <= end_date)]',
            "performance B result split",
        ),
        (
            '        us_daily_period = us_rot_result["return"][\n'
            '            (us_rot_result.index >= start_date) & (us_rot_result.index <= end_date)]',
            '        b78_daily_period = b78_result["return"][\n'
            '            (b78_result.index >= start_date) & (b78_result.index <= end_date)]\n'
            '        us_daily_period = us_rot_result["return"][\n'
            '            (us_rot_result.index >= start_date) & (us_rot_result.index <= end_date)]',
            "performance B daily periods",
        ),
        (
            '        us_monthly_period = _monthly_returns_from_daily_window(us_rot_result["return"], start_date, end_date)',
            '        b78_monthly_period = _monthly_returns_from_daily_window(b78_result["return"], start_date, end_date)\n'
            '        us_monthly_period = _monthly_returns_from_daily_window(us_rot_result["return"], start_date, end_date)',
            "performance B monthly periods",
        ),
        (
            '        all_periods = cn_monthly_period.index.intersection(dk_monthly_period.index).intersection(\n'
            '            us_monthly_period.index).intersection(subc_monthly_period.index)',
            '        all_periods = cn_monthly_period.index.intersection(dk_monthly_period.index).intersection(\n'
            '            b78_monthly_period.index).intersection(us_monthly_period.index).intersection(\n'
            '            subc_monthly_period.index)',
            "performance common months",
        ),
        (
            '                "Sub-B": us_monthly_period.reindex(all_periods),',
            '                "B7.8": b78_monthly_period.reindex(all_periods),\n'
            '                "B7.9": us_monthly_period.reindex(all_periods),',
            "performance aligned B columns",
        ),
        (
            '            cn_monthly_period, dk_monthly_period, us_monthly_period, subc_monthly_period',
            '            cn_monthly_period, dk_monthly_period, b78_monthly_period, us_monthly_period, subc_monthly_period',
            "performance data availability",
        ),
        (
            '        if len(us_monthly_period) >= 1:\n'
            '            metrics["Sub-B"] = calc_monthly_metrics(us_monthly_period)',
            '        if len(b78_monthly_period) >= 1:\n'
            '            metrics["B7.8"] = calc_monthly_metrics(b78_monthly_period)\n'
            '        if len(us_monthly_period) >= 1:\n'
            '            metrics["B7.9"] = calc_monthly_metrics(us_monthly_period)',
            "performance B metrics",
        ),
        (
            '        if len(us_daily_period) > 1 and "Sub-B" in metrics:\n'
            '            nav_b = (1 + us_daily_period).cumprod()\n'
            '            metrics["Sub-B"]["max_dd"] = _max_drawdown_pct_from_nav(nav_b)',
            '        if len(b78_daily_period) > 1 and "B7.8" in metrics:\n'
            '            nav_b78 = (1 + b78_daily_period).cumprod()\n'
            '            metrics["B7.8"]["max_dd"] = _max_drawdown_pct_from_nav(nav_b78)\n'
            '        if len(us_daily_period) > 1 and "B7.9" in metrics:\n'
            '            nav_b79 = (1 + us_daily_period).cumprod()\n'
            '            metrics["B7.9"]["max_dd"] = _max_drawdown_pct_from_nav(nav_b79)',
            "performance B drawdowns",
        ),
        (
            '            "Sub-B": us_daily_period,',
            '            "B7.8": b78_daily_period,\n'
            '            "B7.9": us_daily_period,',
            "performance combined B inputs",
        ),
        (
            '        for _sname, _dret in [\n'
            '            ("Sub-A", cn_daily_period), ("Sub-A-DK", dk_daily_period),\n'
            '            ("Sub-B", us_daily_period),',
            '        for _sname, _dret in [\n'
            '            ("Sub-A", cn_daily_period), ("Sub-A-DK", dk_daily_period),\n'
            '            ("B7.8", b78_daily_period),\n'
            '            ("B7.9", us_daily_period),',
            "performance daily metric B rows",
        ),
        (
            '            "Sub-B": us_monthly_period,',
            '            "B7.8": b78_monthly_period,\n'
            '            "B7.9": us_monthly_period,',
            "performance export B columns",
        ),
        (
            '            for strat_name, daily_data in [\n'
            '                ("Sub-A", cn_daily_period),\n'
            '                ("Sub-A-DK", dk_daily_period),\n'
            '                ("Sub-B", us_daily_period),',
            '            for strat_name, daily_data in [\n'
            '                ("Sub-A", cn_daily_period),\n'
            '                ("Sub-A-DK", dk_daily_period),\n'
            '                ("B7.8", b78_daily_period),\n'
            '                ("B7.9", us_daily_period),',
            "performance weekly B rows",
        ),
        (
            '            "Sub-B": us_rot_result["return"],',
            '            "B7.8": b78_result["return"],\n'
            '            "B7.9": us_rot_result["return"],',
            "performance standard B inputs",
        ),
        (
            '        if len(us_daily_period) > 1:\n'
            '            nav_series["Sub-B"] = _nav_from_period_returns(us_daily_period)',
            '        if len(b78_daily_period) > 1:\n'
            '            nav_series["B7.8"] = _nav_from_period_returns(b78_daily_period)\n'
            '        if len(us_daily_period) > 1:\n'
            '            nav_series["B7.9"] = _nav_from_period_returns(us_daily_period)',
            "performance separate B curves",
        ),
        (
            '                "Sub-B": "#2980B9", "Sub-C": "#16A085", "Combined": "#F39C12",',
            '                "B7.8": "#3498DB", "B7.9": "#1F4E79",\n'
            '                "Sub-C": "#16A085", "Combined": "#F39C12",',
            "performance B colors",
        ),
        (
            '            chart_labels = {\n'
            '                "Sub-A": "Sub-A (CN Long)",\n'
            '                "Sub-A-DK": "Sub-A-DK (CN Long-Short)",\n'
            '                "Sub-B": "Sub-B (US Rotation)",',
            '            chart_labels = {\n'
            '                "Sub-A": "Sub-A (CN Long)",\n'
            '                "Sub-A-DK": "Sub-A-DK (CN Long-Short)",\n'
            '                "B7.8": "B7.8 (50% of Sub-B)",\n'
            '                "B7.9": "B7.9 (50% of Sub-B)",',
            "performance B chart labels",
        ),
        (
            '            if len(us_monthly_period) >= 1:\n'
            '                range_info["Sub-B"] = (us_monthly_period.index[0], us_monthly_period.index[-1])',
            '            if len(b78_monthly_period) >= 1:\n'
            '                range_info["B7.8"] = (b78_monthly_period.index[0], b78_monthly_period.index[-1])\n'
            '            if len(us_monthly_period) >= 1:\n'
            '                range_info["B7.9"] = (us_monthly_period.index[0], us_monthly_period.index[-1])',
            "performance B ranges",
        ),
    ]
    for old, new, label in replacements:
        source = _replace_once(source, old, new, label)

    source = _replace_once(
        source,
        '        subc_daily_period = subc_daily_all[\n'
        '            (subc_daily_all.index >= start_date) & (subc_daily_all.index <= end_date)]\n'
        '        cn_monthly_period = _monthly_returns_from_daily_window(cn_result["return"], start_date, end_date)',
        '        subc_daily_period = subc_daily_all[\n'
        '            (subc_daily_all.index >= start_date) & (subc_daily_all.index <= end_date)]\n'
        '        comb_daily = _performance_combined_daily_returns({\n'
        '            "Sub-A": cn_daily_period,\n'
        '            "Sub-A-DK": dk_daily_period,\n'
        '            "B7.8": b78_daily_period,\n'
        '            "B7.9": us_daily_period,\n'
        '            "Sub-C": subc_daily_period,\n'
        '        })\n'
        '        cn_monthly_period = _monthly_returns_from_daily_window(cn_result["return"], start_date, end_date)',
        "authoritative daily combined before monthly",
    )
    monthly_start = source.index(
        "        all_periods = cn_monthly_period.index.intersection(dk_monthly_period.index).intersection("
    )
    monthly_end = source.index("        if all(len(s) < 1 for s in (", monthly_start)
    source = (
        source[:monthly_start]
        + '        combined_monthly_period = _monthly_returns_from_daily_window(comb_daily, start_date, end_date)\n'
          '        aligned = pd.DataFrame({\n'
          '            "Sub-A": cn_monthly_period,\n'
          '            "Sub-A-DK": dk_monthly_period,\n'
          '            "B7.8": b78_monthly_period,\n'
          '            "B7.9": us_monthly_period,\n'
          '            "Sub-C": subc_monthly_period,\n'
          '            "Combined": combined_monthly_period,\n'
          '        }).sort_index()\n'
          '        filtered = aligned\n'
        + source[monthly_end:]
    )
    duplicate_start = source.index(
        '        comb_daily = _performance_combined_daily_returns({',
        source.index('        if len(subc_daily_period) > 1 and "Sub-C" in metrics:'),
    )
    duplicate_end = source.index('        if "Combined" in metrics and len(comb_daily) > 1:', duplicate_start)
    source = source[:duplicate_start] + source[duplicate_end:]
    source = _replace_once(
        source,
        '        if len(filtered) >= 1:\n'
        '            metrics["Combined"] = calc_monthly_metrics(filtered["Combined"])',
        '        if len(combined_monthly_period) >= 1:\n'
        '            metrics["Combined"] = calc_monthly_metrics(combined_monthly_period)',
        "combined metrics from daily-derived monthly",
    )
    source = _replace_once(
        source,
        '        if len(filtered) > 0:\n'
        '            excel_monthly["Combined"] = filtered["Combined"].reindex(excel_monthly.index)',
        '        if len(combined_monthly_period) > 0:\n'
        '            excel_monthly["Combined"] = combined_monthly_period.reindex(excel_monthly.index)',
        "combined Excel from daily-derived monthly",
    )
    source = _replace_once(
        source,
        '            if len(filtered) >= 1:\n'
        '                range_info["Combined"] = (filtered.index[0], filtered.index[-1])',
        '            if len(combined_monthly_period) >= 1:\n'
        '                range_info["Combined"] = (combined_monthly_period.index[0], combined_monthly_period.index[-1])',
        "combined range from daily-derived monthly",
    )

    source = source.replace(
        "| Window | Sub-A | A-DK | Sub-B | Sub-C | PV四策略组合(15/15/40/30) |",
        "| Window | Sub-A | A-DK | B7.8 | B7.9 | Sub-C | PV组合(15/15/20/20/30) |",
    )
    source = source.replace(
        "|:-|------:|------:|------:|------:|------:|",
        "|:-|------:|------:|------:|------:|------:|------:|",
    )
    source = source.replace(
        "| 指标 | Sub-A | A-DK | Sub-B | Sub-C | PV四策略组合(15/15/40/30) |",
        "| 指标 | Sub-A | A-DK | B7.8 | B7.9 | Sub-C | PV组合(15/15/20/20/30) |",
    )
    source = source.replace(
        "| 年份 | Sub-A | A-DK | Sub-B | Sub-C | PV四策略组合(15/15/40/30) |",
        "| 年份 | Sub-A | A-DK | B7.8 | B7.9 | Sub-C | PV组合(15/15/20/20/30) |",
    )
    source = source.replace(
        "|:-|------:|------:|------:|------:|-----:|",
        "|:-|------:|------:|------:|------:|------:|-----:|",
    )
    source = source.replace(
        "PV四策略组合 ({_performance_combo_weight_label()})",
        "PV组合 ({_performance_combo_weight_label()})",
    )
    source = source.replace(
        "PV 4-sleeve ({_performance_combo_weight_label()})",
        "PV 5-line ({_performance_combo_weight_label()})",
    )
    source = source.replace(
        "说明: PV/收益查询只展示本脚本实际运行的 Sub-A、Sub-A-DK、Sub-B、Sub-C 及四策略组合（{_performance_combo_weight_label()}）。",
        "说明: Sub-B资金由B7.8/B7.9各占50%；两列独立展示，PV按A/ADK/B7.8/B7.9/C={_performance_combo_weight_label()}计算。",
    )
    source = source.replace(
        '        ws.set_column("B:F", 14)\n'
        '        metric_headers = ["指标", "Sub-A", "A-DK", "Sub-B", "Sub-C", "PV四策略组合(15/15/40/30)"]',
        '        ws.set_column("B:G", 14)\n'
        '        metric_headers = ["指标", "Sub-A", "A-DK", "B7.8", "B7.9", "Sub-C", "PV组合(15/15/20/20/30)"]',
    )
    source = source.replace(
        '            ws2.set_column("B:F", 14)\n'
        '            mr_headers = ["月份", "Sub-A", "A-DK", "Sub-B", "Sub-C", "PV四策略组合(15/15/40/30)"]',
        '            ws2.set_column("B:G", 14)\n'
        '            mr_headers = ["月份", "Sub-A", "A-DK", "B7.8", "B7.9", "Sub-C", "PV组合(15/15/20/20/30)"]',
    )
    source = source.replace(
        '        standard_daily_returns = {\n'
        '            "Sub-A": cn_result["return"],\n'
        '            "Sub-A-DK": cn_dk_result["return"],\n'
        '            "B7.8": b78_result["return"],\n'
        '            "B7.9": us_rot_result["return"],\n'
        '            "Sub-C": subc_daily_all,\n'
        '        }\n'
        '        standard_daily_returns["Combined"] = _performance_combined_daily_returns(standard_daily_returns)',
        '        standard_daily_returns = _v80_performance_daily_returns(\n'
        '            cn_result["return"], cn_dk_result["return"], us_rot_result, subc_daily_all\n'
        '        )',
    )
    return source


def _apply_v80_rebalance_surfaces(source: str) -> str:
    signal_old = '''        us_rebs = extract_us_rot_rebalances(
            d["us_rot_result"],
            us_rot_close=us_rot_close,
            us_open=_us_open,
            since_date=cutoff,
        )
        all_rebalances.extend([r for r in us_rebs if pd.Timestamp(r["日期"]) >= cutoff])
        volreg_rebs = extract_subb_volreg_rebalances(
            d["us_rot_result"],
            us_rot_close=us_rot_close,
            us_open=_us_open,
            since_date=cutoff,
        )
        all_rebalances.extend([r for r in volreg_rebs if pd.Timestamp(r["日期"]) >= cutoff])'''
    signal_new = '''        subb_rebs = _v80_extract_subb_rebalances(
            d["us_rot_result"], us_rot_close=us_rot_close, us_open=_us_open, since_date=cutoff
        )
        all_rebalances.extend([r for r in subb_rebs if pd.Timestamp(r["日期"]) >= cutoff])'''
    source = _replace_once(source, signal_old, signal_new, "signal two-B rebalances")

    performance_old = '''        us_rebs = extract_us_rot_rebalances(us_rot_result, us_rot_close=us_rot_close, us_open=_us_open)
        all_rebalances.extend([r for r in us_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])
        volreg_rebs = extract_subb_volreg_rebalances(us_rot_result, us_rot_close=us_rot_close, us_open=_us_open)
        all_rebalances.extend([r for r in volreg_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date])'''
    performance_new = '''        subb_rebs = _v80_extract_subb_rebalances(
            us_rot_result, us_rot_close=us_rot_close, us_open=_us_open, since_date=start_date
        )
        all_rebalances.extend([
            r for r in subb_rebs if start_date <= pd.Timestamp(r["日期"]) <= end_date
        ])'''
    source = _replace_once(source, performance_old, performance_new, "performance two-B rebalances")

    history_start = source.index("            # ===== Sub-B =====")
    history_end = source.index("    def _handle_nav_chart", history_start)
    history_block = '''            # ===== B7.8 / B7.9 =====
            w("### B策略双版本调仓历史（分开展示）\\n\\n")
            _us_open = getattr(self, "_us_open", None)
            _b78_result, _b79_result = _v80_subb_results(us_rot_result)
            for _label, _result in (("B7.8", _b78_result), ("B7.9", _b79_result)):
                _records = _v80_extract_subb_rebalances(
                    us_rot_result, us_rot_close=us_rot_close, us_open=_us_open, since_date=start_date
                )
                _records = [
                    rec for rec in _records
                    if rec.get("策略") == _label
                    and start_date <= pd.Timestamp(rec.get("日期")) <= end_date
                ]
                w(f"#### {_label}\\n\\n")
                if not _records:
                    w("该时段无实际调仓或VolReg切换。\\n\\n")
                    continue
                w("| 日期 | 卖出 | 买入 |\\n|:--|:--|:--|\\n")
                for rec in _records:
                    w(f"| {rec.get('日期', '')} | {rec.get('卖出', '—')} | **{rec.get('买入', '—')}** |\\n")
                w(f"\\n共 **{len(_records)}** 条记录\\n\\n")
'''
    source = source[:history_start] + history_block + source[history_end:]
    return source


def _apply_v80_account_config(source: str) -> str:
    source = source.replace(
        'for strategy in ("Sub-A-DK", "Sub-A", "Sub-B", "Sub-C"):',
        'for strategy in ("Sub-A-DK", "Sub-A", "B7.8", "B7.9", "Sub-B", "Sub-C"): ',
    )
    source = _replace_once(
        source,
        '    if parsed:\n        return parsed\n\n    usd = None',
        '    if parsed:\n'
        '        return _v80_normalize_capital_config(parsed)\n\n'
        '    usd = None',
        "capital explicit B split",
    )
    source = _replace_once(
        source,
        '        us_total_weight = COMBINED_WEIGHTS["Sub-B"] + COMBINED_WEIGHTS["Sub-C"]\n'
        '        parsed["Sub-B"] = usd * COMBINED_WEIGHTS["Sub-B"] / us_total_weight\n'
        '        parsed["Sub-C"] = usd * COMBINED_WEIGHTS["Sub-C"] / us_total_weight\n'
        '    return parsed or None',
        '        us_total_weight = (\n'
        '            PERFORMANCE_COMBO_WEIGHTS["B7.8"]\n'
        '            + PERFORMANCE_COMBO_WEIGHTS["B7.9"]\n'
        '            + PERFORMANCE_COMBO_WEIGHTS["Sub-C"]\n'
        '        )\n'
        '        parsed["B7.8"] = usd * PERFORMANCE_COMBO_WEIGHTS["B7.8"] / us_total_weight\n'
        '        parsed["B7.9"] = usd * PERFORMANCE_COMBO_WEIGHTS["B7.9"] / us_total_weight\n'
        '        parsed["Sub-C"] = usd * PERFORMANCE_COMBO_WEIGHTS["Sub-C"] / us_total_weight\n'
        '    return _v80_normalize_capital_config(parsed) if parsed else None',
        "capital USD split",
    )
    source = source.replace(
        'next((s for s in ("Sub-A-DK", "Sub-A", "Sub-B", "Sub-C")',
        'next((s for s in ("Sub-A-DK", "Sub-A", "B7.8", "B7.9", "Sub-B", "Sub-C")',
    )
    source = source.replace(
        'if strategy in ("Sub-B", "Sub-C"):',
        'if strategy in ("B7.8", "B7.9", "Sub-B", "Sub-C"): ',
    )
    source = source.replace(
        'for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"]:',
        'for s in ["Sub-A", "Sub-A-DK", "B7.8", "B7.9", "Sub-C"]:',
    )
    source = source.replace(
        'currency = {"Sub-A": "¥", "Sub-A-DK": "¥", "Sub-B": "$", "Sub-C": "$"}',
        'currency = {"Sub-A": "¥", "Sub-A-DK": "¥", "B7.8": "$", "B7.9": "$", "Sub-C": "$"}',
    )
    source = source.replace(
        '_sw = STRATEGY_WEIGHTS[s]',
        '_sw = PERFORMANCE_COMBO_WEIGHTS.get(s, STRATEGY_WEIGHTS.get(s, 0.0))',
    )
    source = source.replace(
        '资金设置支持: Sub-A, Sub-A-DK, Sub-B, Sub-C',
        '资金设置支持: Sub-A, Sub-A-DK, B7.8, B7.9, Sub-C；输入旧Sub-B时自动50/50拆分',
    )
    source = source.replace(
        'V7.9 active执行权重: Sub-A 15%, Sub-A-DK 15%, Sub-B 40%, Sub-C 30%',
        'V8.0默认组合权重: Sub-A 15%, Sub-A-DK 15%, B7.8 20%, B7.9 20%, Sub-C 30%',
    )
    source = source.replace(
        '注意: Sub-A和Sub-A-DK使用人民币, Sub-B和Sub-C使用美元',
        '注意: Sub-A和Sub-A-DK使用人民币, B7.8/B7.9/Sub-C使用美元',
    )
    source = source.replace(
        '1. 用户说"Sub-B 5万美元" -> Sub-B: 50000',
        '1. 用户说"Sub-B 5万美元" -> B7.8: 25000, B7.9: 25000',
    )
    source = source.replace(
        '美元按Sub-B:Sub-C=40:30拆分',
        '美元按B7.8:B7.9:Sub-C=20:20:30拆分',
    )
    source = source.replace(
        'Sub-B: 400000, Sub-C: 300000',
        'B7.8: 200000, B7.9: 200000, Sub-C: 300000',
    )
    source = source.replace(
        'Sub-B: 40000, Sub-C: 30000',
        'B7.8: 20000, B7.9: 20000, Sub-C: 30000',
    )
    source = source.replace('只分给Sub-B和Sub-C', '只分给B7.8、B7.9和Sub-C')
    source = source.replace(
        '"Sub-B": 数字或null,\n  "Sub-C": 数字或null',
        '"B7.8": 数字或null,\n  "B7.9": 数字或null,\n  "Sub-C": 数字或null',
    )
    source = source.replace(
        'config = dict(existing)\n        for s in ["Sub-A", "Sub-A-DK", "B7.8", "B7.9", "Sub-C"]:',
        'config = _v80_normalize_capital_config(existing)\n'
        '        parsed = _v80_normalize_capital_config(parsed)\n'
        '        for s in ["Sub-A", "Sub-A-DK", "B7.8", "B7.9", "Sub-C"]:',
    )
    source = source.replace(
        'strategy = "Sub-B"\n                        else:',
        'raise poe.BotError(\n'
        '                                "V8.0检测到B策略ETF，但不能判断属于B7.8还是B7.9；"\n'
        '                                "请在消息或CSV策略列中明确版本。"\n'
        '                            )\n                        else:',
    )
    source = source.replace(
        'for s in ["Sub-A-DK", "Sub-A", "Sub-B", "Sub-C"]:',
        'for s in ["Sub-A-DK", "Sub-A", "B7.8", "B7.9", "Sub-C"]:',
    )
    source = _replace_once(
        source,
        "                        strat = str(row[col_map['strategy']]).strip()\n"
        "                        etf = str(row[col_map['etf']]).strip()\n"
        "                        if strat not in config:",
        "                        strat = str(row[col_map['strategy']]).strip()\n"
        "                        etf = str(row[col_map['etf']]).strip()\n"
        "                        if strat == 'Sub-B':\n"
        "                            raise poe.BotError('V8.0仓位必须分别标记为B7.8或B7.9，不能使用合并Sub-B。')\n"
        "                        if strat not in {'Sub-A', 'Sub-A-DK', 'B7.8', 'B7.9', 'Sub-C'}:\n"
        "                            raise poe.BotError(f'未知策略: {strat}')\n"
        "                        if strat not in config:",
        "CSV position strategy validation",
    )
    source = source.replace(
        'Sub-B: V7.9四腿综合 = 官方腿25%',
        'B7.8: V7.8四腿综合（独立账户）\\nB7.9: V7.9四腿综合（独立账户） = 官方腿25%',
    )
    source = source.replace(
        '  "Sub-B": {{"ETF代码": 股数或{{"amount": 金额数字}}}} 或 null,',
        '  "B7.8": {{"ETF代码": 股数或{{"amount": 金额数字}}}} 或 null,\n'
        '  "B7.9": {{"ETF代码": 股数或{{"amount": 金额数字}}}} 或 null,',
    )
    source = source.replace(
        '9. 关键: 如果用户只指定策略的总金额, 不列出具体标的(如"Sub-B总共50万"), 输出 {{"_total_amount": 金额数字}}\n'
        '   例: "Sub-B总共50万美元" -> "Sub-B": {{"_total_amount": 500000}}',
        '9. 关键: B策略仓位必须明确写B7.8或B7.9；不接受无法归属的合并Sub-B持仓。',
    )
    source = _replace_once(
        source,
        '            config = dict(existing)\n'
        '            cap_config = _scan_capital_config(poe.default_chat) or {}',
        '            if parsed and parsed.get("Sub-B") is not None:\n'
        '                raise poe.BotError("V8.0仓位不能自动拆分；请分别设置B7.8和B7.9持仓。")\n'
        '            config = dict(existing)\n'
        '            cap_config = _scan_capital_config(poe.default_chat) or {}',
        "reject text legacy B positions",
    )
    source = _replace_once(
        source,
        '        currency_label = {"Sub-A": "A股", "Sub-A-DK": "A股(多空)", "Sub-B": "美股轮动", "Sub-C": "美股多资产"}\n'
        '        currency_symbol = {"Sub-A": "¥", "Sub-A-DK": "¥", "Sub-B": "$", "Sub-C": "$"}',
        '        if "B7.8" in config and "B7.9" in config:\n'
        '            config.pop("Sub-B", None)\n'
        '        if cap_updated:\n'
        '            cap_config = _v80_normalize_capital_config(cap_config)\n'
        '        currency_label = {"Sub-A": "A股", "Sub-A-DK": "A股(多空)", "B7.8": "美股轮动7.8", "B7.9": "美股轮动7.9", "Sub-C": "美股多资产"}\n'
        '        currency_symbol = {"Sub-A": "¥", "Sub-A-DK": "¥", "B7.8": "$", "B7.9": "$", "Sub-C": "$"}',
        "position display dictionaries and legacy cleanup",
    )
    source = source.replace(
        'if s in ("Sub-B", "Sub-C"):',
        'if s in ("B7.8", "B7.9", "Sub-C"): ',
    )
    source = source.replace(
        'if not any(config.get(s) for s in ["Sub-A", "Sub-A-DK", "Sub-B", "Sub-C"])',
        'if not any(config.get(s) for s in ["Sub-A", "Sub-A-DK", "B7.8", "B7.9", "Sub-C"])',
    )
    source = source.replace(
        '用户说"总共7万美元给美股" -> Sub-B 40000, Sub-C 30000',
        '用户说"总共7万美元给美股" -> B7.8 20000, B7.9 20000, Sub-C 30000',
    )
    source = source.replace(
        '"设置仓位 Sub-B" 并附上CSV文件',
        '"设置仓位 B7.8" 或 "设置仓位 B7.9" 并附上CSV文件',
    )
    source = source.replace(
        '- 设置仓位 Sub-B: QQQM 100股 GLDM 50股 PDBC 200股',
        '- 设置仓位 B7.8: QQQM 100股 GLDM 50股；B7.9请另设',
    )
    source = source.replace(
        '**💰 资金管理:** "设置资金 Sub-B 5万美元" -> 信号自动显示目标数量',
        '**💰 资金管理:** "设置资金 Sub-B 5万美元" -> 自动拆为B7.8/B7.9各2.5万美元',
    )
    source = source.replace(
        '**📊 仓位管理:** "设置仓位 Sub-B: QQQM 100股 GLDM 50股"',
        '**📊 仓位管理:** 分别设置 "B7.8" 与 "B7.9"，例如 "设置仓位 B7.8: QQQM 100股 GLDM 50股"',
    )
    source = source.replace(
        '            for _cname in COMBINED_DISPLAY_ORDER:\n'
        '                _cw = COMBINED_WEIGHTS[_cname]',
        '            for _cname in PERFORMANCE_COMBO_ORDER:\n'
        '                _cw = PERFORMANCE_COMBO_WEIGHTS[_cname]',
    )
    source = source.replace(
        '            for name in COMBINED_DISPLAY_ORDER:\n'
        '                cw = COMBINED_WEIGHTS[name]',
        '            for name in PERFORMANCE_COMBO_ORDER:\n'
        '                cw = PERFORMANCE_COMBO_WEIGHTS[name]',
    )
    return source


def _apply_v80_fetch_union(source: str) -> str:
    source = _replace_once(
        source,
        '        rot_tickers = list(dict.fromkeys(\n'
        '            US_ROT_POOL + ["BIL"] + list(SUBB_INFLATION_GATE_TICKERS)\n'
        '            + [ticker for ticker in SUBB_OPTIONAL_MACRO_TICKERS if ticker in us_raw]\n'
        '        ))',
        '        rot_tickers = _v80_subb_all_rot_tickers(us_raw)',
        "Sub-B final price-frame ticker union",
    )
    source = _replace_once(
        source,
        '        for _live_ticker, _cfg in US_ROT_BASE_ASSETS.items():',
        '        for _live_ticker, _cfg in {\n'
        '            **_v80_b78_US_ROT_BASE_ASSETS, **US_ROT_BASE_ASSETS\n'
        '        }.items():',
        "Sub-B proxy/live splice union",
    )
    source = _replace_once(
        source,
        '        for _live_ticker in set(list(US_ROT_ASSETS.keys()) + list(PROD_PORTFOLIO.keys())):',
        '        for _live_ticker in set(\n'
        '            list(US_ROT_ASSETS.keys())\n'
        '            + list(_v80_b78_US_ROT_ASSETS.keys())\n'
        '            + list(PROD_PORTFOLIO.keys())\n'
        '        ):',
        "Sub-B live-price column union",
    )
    return source


def build() -> Path:
    v78 = V78_PATH.read_text(encoding="utf-8")
    source = V79_PATH.read_text(encoding="utf-8")
    namespace = _build_v78_subb_namespace(v78)

    source = _replace_once(
        source,
        '"""V7.9"""',
        '"""V8.0 unified query: shared A/ADK/C plus parallel B7.8 and B7.9."""',
        "module version",
    )
    source = _replace_once(source, 'V78_LABEL = "V7.9"', 'V78_LABEL = "V8.0"', "version label")
    source = _apply_v80_performance_model(source)
    source = _apply_v80_daily_math(source)

    insertion_anchor = "\ndef _v78_adk_leg_rank_sections(cn_dk_result, idx, use_shifted=False, top_n=3):"
    source = _replace_once(
        source,
        insertion_anchor,
        "\n\n# --- V8.0 embedded B7.8 namespace; generated from the real V7.8 call graph ---\n"
        + namespace
        + V80_RUNTIME
        + insertion_anchor,
        "runtime insertion",
    )
    source = _apply_v80_fetch_union(source)
    source = _apply_v80_performance_surfaces(source)
    source = _apply_v80_rebalance_surfaces(source)
    source = _apply_v80_account_config(source)

    subb_start = source.index("        us_rot_official = run_us_rotation_mix(")
    subb_end = source.index("        prod_monthly = prod_sig_a = prod_sig_b = prod_nav = prod_details = None", subb_start)
    source = (
        source[:subb_start]
        + "        us_rot_result = _run_v80_subb_variants(\n"
          "            us_rot_close,\n"
          "            us_open=getattr(self, \"_us_open\", None),\n"
          "            strict_open_execution=strict_subb_open_execution,\n"
          "        )\n"
        + source[subb_end:]
    )

    source = _replace_once(
        source,
        "        cn_result_params = None\n        cn_dk_result_params = None\n        strategy_params_error = None",
        "        cn_result_params = None\n        cn_dk_result_params = None\n        us_rot_result_params = None\n"
        "        subc_info_params = {}\n        strategy_params_error = None",
        "params declarations",
    )
    source = _replace_once(
        source,
        "                cn_result_params, cn_dk_result_params, _, _, _, _, _, _ = self._cached_run_strategies(",
        "                cn_result_params, cn_dk_result_params, us_rot_result_params, _, prod_sig_a_params, prod_sig_b_params, _, _ = self._cached_run_strategies(",
        "params result",
    )
    params_compute_anchor = "                    allow_unresolved_suba_volume=True,\n                )\n            except Exception as exc:"
    source = _replace_once(
        source,
        params_compute_anchor,
        "                    allow_unresolved_suba_volume=True,\n                )\n"
        "                if prod_sig_a_params is not None:\n"
        "                    subc_info_params = _compute_subc_production_snapshot(\n"
        "                        us_prod_daily_p, prod_sig_a_params, prod_sig_b_params,\n"
        "                        us_open=getattr(self, \"_us_open\", None),\n"
        "                        strict_open_execution=True,\n"
        "                    )[\"info\"]\n"
        "            except Exception as exc:",
        "params Sub-C snapshot",
    )

    signal_anchor = '            w("### Sub-A: V7.9双腿综合｜A策略详细依据\\n")'
    source = source.replace(signal_anchor, "__V80_SIGNAL_A_DETAIL__", 1)
    source = source.replace(signal_anchor, "__V80_LIVE_A_DETAIL__", 1)
    signal_insert = (
        "            signal_info.update(_write_v80_subb_overview(\n"
        "                w, us_rot_result, query_kind=\"signal\", us_intraday=us_signal_live,\n"
        "                us_rot_close=us_rot_close,\n"
        "            ))\n"
        "            _write_v80_subc_overview(\n"
        "                w, d.get(\"subc_vs_info\", {}), query_kind=\"signal\",\n"
        "                us_intraday=us_signal_live,\n"
        "            )\n"
        "            w(\"---\\n\\n\")\n"
        + signal_anchor
    )
    live_insert = (
        "            _write_v80_subb_overview(\n"
        "                w, us_rot_result, query_kind=\"live_signal\",\n"
        "                us_intraday=us_open and us_data_is_today,\n"
        "                us_rot_close=us_rot_close,\n"
        "            )\n"
        "            _write_v80_subc_overview(\n"
        "                w, d.get(\"subc_vs_info\", {}), query_kind=\"live_signal\",\n"
        "                us_intraday=us_open and us_data_is_today,\n"
        "            )\n"
        "            w(\"---\\n\\n\")\n"
        + signal_anchor
    )
    source = _replace_once(source, "__V80_SIGNAL_A_DETAIL__", signal_insert, "signal overview")
    source = _replace_once(source, "__V80_LIVE_A_DETAIL__", live_insert, "live signal overview")

    params_anchor = '            w("### Sub-A: V7.9双腿综合｜A策略参数与计算依据\\n\\n")'
    source = _replace_once(
        source,
        params_anchor,
        "            _write_v80_subb_overview(\n"
        "                w, us_rot_result_params, query_kind=\"params\", us_intraday=False,\n"
        "                us_rot_close=us_rot_close_p,\n"
        "            )\n"
        "            _write_v80_subc_overview(\n"
        "                w, subc_info_params, query_kind=\"params\", us_intraday=False,\n"
        "            )\n"
        "            w(\"---\\n\\n\")\n"
        + params_anchor,
        "params overview",
    )
    live_params_anchor = '            w("### Sub-A: V7.9双腿综合｜A策略实时参数与计算依据\\n\\n")'
    source = _replace_once(
        source,
        live_params_anchor,
        "            _write_v80_subb_overview(\n"
        "                w, us_rot_result, query_kind=\"live_params\",\n"
        "                us_intraday=us_open and us_data_is_today,\n"
        "                us_rot_close=us_rot_close,\n"
        "            )\n"
        "            _subc_live_info = _compute_subc_production_snapshot(\n"
        "                us_prod_daily, prod_sig_a, prod_sig_b,\n"
        "                us_open=getattr(self, \"_us_open\", None),\n"
        "                strict_open_execution=True,\n"
        "            )[\"info\"] if prod_sig_a is not None else {}\n"
        "            _write_v80_subc_overview(\n"
        "                w, _subc_live_info, query_kind=\"live_params\",\n"
        "                us_intraday=us_open and us_data_is_today,\n"
        "            )\n"
        "            w(\"---\\n\\n\")\n"
        + live_params_anchor,
        "live params overview",
    )

    subb_detail_anchor = '            w("### Sub-B: V7.9四腿综合（官方/EMA/Bias/LogVol各25%）\\n")'
    source = source.replace(subb_detail_anchor, "__V80_SIGNAL_B79_DETAIL__", 1)
    source = source.replace(subb_detail_anchor, "__V80_LIVE_B79_DETAIL__", 1)
    source = _replace_once(
        source,
        "__V80_SIGNAL_B79_DETAIL__",
        "            _write_v80_b78_detail(w, us_rot_result, query_kind=\"signal\")\n"
        "            w(\"\\n---\\n\\n\")\n"
        + subb_detail_anchor,
        "signal B7.8 detail",
    )
    source = _replace_once(
        source,
        "__V80_LIVE_B79_DETAIL__",
        "            _write_v80_b78_detail(w, us_rot_result, query_kind=\"live_signal\")\n"
        "            w(\"\\n---\\n\\n\")\n"
        + subb_detail_anchor,
        "live signal B7.8 detail",
    )

    subb_params_anchor = '            w("\\n---\\n\\n### Sub-B: V7.9四腿综合（官方/EMA/Bias/LogVol各25%）\\n\\n")'
    source = source.replace(subb_params_anchor, "__V80_PARAMS_B79_DETAIL__", 1)
    source = source.replace(subb_params_anchor, "__V80_LIVE_PARAMS_B79_DETAIL__", 1)
    source = _replace_once(
        source,
        "__V80_PARAMS_B79_DETAIL__",
        "            w(\"\\n---\\n\\n\")\n"
        "            _write_v80_b78_detail(w, us_rot_result_params, query_kind=\"params\")\n"
        + subb_params_anchor,
        "params B7.8 detail",
    )
    source = _replace_once(
        source,
        "__V80_LIVE_PARAMS_B79_DETAIL__",
        "            w(\"\\n---\\n\\n\")\n"
        "            _write_v80_b78_detail(w, us_rot_result, query_kind=\"live_params\")\n"
        + subb_params_anchor,
        "live params B7.8 detail",
    )

    source = source.replace("### Sub-B: V7.9", "### B7.9详细依据（Sub-B）: V7.9")
    source = source.replace(
        '**💰 资金管理:** \\"设置资金 Sub-B 5万美元\\" -> 信号自动显示目标数量',
        '**💰 资金管理:** \\"设置资金 Sub-B 5万美元\\" -> 自动拆为B7.8/B7.9各2.5万美元',
    )
    source = source.replace(
        '**📊 仓位管理:** \\"设置仓位 Sub-B: QQQM 100股 GLDM 50股\\"',
        '**📊 仓位管理:** 分别设置 \\"B7.8\\" 与 \\"B7.9\\"，例如 \\"设置仓位 B7.8: QQQM 100股 GLDM 50股\\"',
    )

    # The legacy V7.9 detail block remains useful for diagnostics, but V8.0
    # must never let it calculate orders from the entire aggregate Sub-B book.
    source = _replace_once(
        source,
        '            _sub_b_capital = _cap_config.get("Sub-B") if _cap_config else None',
        '            _sub_b_capital = None  # V8.0 quantities are emitted per B7.8/B7.9 account above',
        "disable legacy signal B capital",
    )
    source = _replace_once(
        source,
        '            _sub_b_pos = _pos_config.get("Sub-B") if _pos_config else None\n'
        '            _sub_b_pos = _normalize_subb_position_keys(_sub_b_pos)',
        '            _sub_b_pos = None  # aggregate Sub-B holdings cannot be split safely',
        "disable legacy signal B positions",
    )
    source = _replace_once(
        source,
        '            _sub_b_pos_live = _pos_config_live.get("Sub-B") if _pos_config_live else None\n'
        '            _sub_b_pos_live = _normalize_subb_position_keys(_sub_b_pos_live)',
        '            _sub_b_pos_live = None  # V8.0 live orders are emitted per independent B account',
        "disable legacy live B positions",
    )
    source = source.replace("V7.9 active组合:", "V8.0统一查询（Sub-B内B7.8/B7.9各50%）:")
    source = source.replace("V7.9可设置仓位:", "V8.0可设置仓位（两套B目标分别核对）:")
    source = source.replace(
        "Sub-A 15% + Sub-A-DK 15% + Sub-B 40% + Sub-C 30%（仅包含本脚本实际运行的四个策略；A/ADK为双腿混合；Sub-B为四腿Top2综合；C为10ETF多资产腿；7.7原腿保留为参照组件）",
        "Sub-A 15% + Sub-A-DK 15% + B7.8 20% + B7.9 20% + Sub-C 30%（两套B独立计算、独立扣费、独立展示）",
    )
    source = source.replace(
        "仅展示本脚本实际运行的 Sub-A/Sub-A-DK/Sub-B/Sub-C 四策略组合（{_performance_combo_weight_label()}）",
        "B7.8/B7.9各占Sub-B的50%，独立展示；PV按A/ADK/B7.8/B7.9/C={_performance_combo_weight_label()}计算",
    )
    source = source.replace("Strategy Signal V7.9 —", "Strategy Signal V8.0 —")
    source = source.replace(
        "V7.9 active执行权重:",
        "V8.0默认组合权重（A/ADK/B7.8/B7.9/C=15/15/20/20/30）:",
    )
    source = source.replace("按V7.9比例", "按V8.0默认比例")
    source = source.replace("### Sub-A: V7.9双腿综合", "### Sub-A: V8.0共享双腿")
    source = source.replace("### Sub-A-DK: V7.9双子策略", "### Sub-A-DK: V8.0共享双子策略")
    source = source.replace("**V7.9 Sub-A", "**V8.0 Sub-A")
    source = source.replace("**V7.9 ADK", "**V8.0 ADK")
    source = source.replace("| **V7.9最终**", "| **V8.0最终**")
    source = source.replace("| V7.9混合 |", "| V8.0共享腿 |")
    source = source.replace("以V7.9双腿状态表", "以V8.0双腿状态表")
    source = source.replace("V7.9 ADK为双腿component-net", "V8.0 ADK为双腿component-net")
    source = source.replace("**① V7.9 Sub-A", "**① V8.0 Sub-A")
    source = source.replace("**1. V7.9 Sub-A", "**1. V8.0 Sub-A")
    source = source.replace("**① V7.9 ADK", "**① V8.0 ADK")

    source = _replace_once(
        source,
        '\nif __name__ == "__main__":\n    CombinedStrategyV78().run()\n',
        '\n\nclass CombinedStrategyV80(CombinedStrategyV78):\n'
        '    """V8.0 unified query surface; implementation inherits the hardened V7.9 host."""\n'
        '    pass\n\n\n'
        'if __name__ == "__main__":\n'
        '    CombinedStrategyV80().run()\n',
        "V8 entrypoint",
    )

    source = _compact_poe_artifact(source)
    OUTPUT_PATH.write_text(source, encoding="utf-8", newline="\n")
    return OUTPUT_PATH


if __name__ == "__main__":
    print(build())

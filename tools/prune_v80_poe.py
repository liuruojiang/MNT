"""Prune retired V8 money-management and unreachable verbose query code."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


DEFAULT_PATH = Path(__file__).resolve().parents[1] / "mnt_bot V 8.0 plus.py"
POE_HEADER = "# poe: name=Strategy-Signal-V80\n# poe: privacy_shield=half\n"

_REMOVED_FUNCTIONS = {
    "_v80_normalize_capital_config",
    "_v80_normalize_position_config",
    "_v80_price_for_asset",
    "_v80_normalize_account_positions",
    "_v80_subb_account_rows",
    "_scan_capital_config",
    "_build_capital_marker",
    "_scan_position_config",
    "_build_position_marker",
    "_pos_entry_value",
    "_pos_entry_is_nonzero",
    "_pos_entry_needs_price_for_value",
    "_normalize_subb_position_keys",
    "_subb_target_shares",
    "_subb_position_adjustment_target_value",
    "_pos_entry_shares",
    "_calc_quantities",
    "_position_csv_column_map",
    "_position_csv_entry",
    "_parse_number_with_unit",
    "_parse_simple_capital_config",
    "_parse_simple_position_config",
}
_REMOVED_METHODS = {"_handle_set_capital", "_handle_set_position", "_write_sub_c"}
_REMOVED_CONFIG_NAMES = {
    "CAPITAL_CONFIG_START",
    "CAPITAL_CONFIG_END",
    "POSITION_CONFIG_START",
    "POSITION_CONFIG_END",
}
_COMPACT_HANDLERS = {
    "_handle_signal",
    "_handle_live_signal",
    "_handle_params",
    "_handle_live_params",
}
_DROP_IF_REFERENCES = {
    "_handle_set_capital",
    "_handle_set_position",
    "_v80_subb_account_rows",
}
_BANNED_TEXT = ("设置资金", "设置仓位", "资金管理:", "仓位管理:")


def _referenced_names(node: ast.AST) -> set[str]:
    names = {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}
    names.update(item.attr for item in ast.walk(node) if isinstance(item, ast.Attribute))
    return names


class _V80PoePruner(ast.NodeTransformer):
    def __init__(self) -> None:
        self.compact_handlers_pruned: set[str] = set()
        self.removed_functions: set[str] = set()
        self.removed_methods: set[str] = set()

    def visit_Assign(self, node: ast.Assign):
        assigned_names = {
            target.id for target in node.targets if isinstance(target, ast.Name)
        }
        if assigned_names & _REMOVED_CONFIG_NAMES:
            return None
        node = self.generic_visit(node)
        if "_BOT_SETTINGS" in assigned_names:
            for item in ast.walk(node.value):
                if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                    continue
                lines = item.value.splitlines()
                filtered = [
                    line
                    for line in lines
                    if "💰 资金管理:" not in line and "📊 仓位管理:" not in line
                ]
                if filtered != lines:
                    item.value = "\n".join(filtered)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if node.name in _REMOVED_FUNCTIONS:
            self.removed_functions.add(node.name)
            return None
        if node.name in _REMOVED_METHODS:
            self.removed_methods.add(node.name)
            return None
        node = self.generic_visit(node)
        if node.name in _COMPACT_HANDLERS:
            pruned_here = False
            for statement in node.body:
                if not isinstance(statement, ast.With):
                    continue
                for index, child in enumerate(statement.body):
                    if (
                        isinstance(child, ast.If)
                        and isinstance(child.test, ast.Name)
                        and child.test.id == "V80_QUERY_COMPACT_DISPLAY"
                    ):
                        statement.body = statement.body[:index] + child.body
                        self.compact_handlers_pruned.add(node.name)
                        pruned_here = True
                        break
            if not pruned_here and "_write_v80_a_adk_score_details" in _referenced_names(node):
                self.compact_handlers_pruned.add(node.name)
        return node

    def visit_If(self, node: ast.If):
        node = self.generic_visit(node)
        references = _referenced_names(node.test)
        for statement in node.body:
            references.update(_referenced_names(statement))
        if references & _DROP_IF_REFERENCES:
            return node.orelse or None
        return node


def prune_source(source: str) -> str:
    tree = ast.parse(source)
    pruner = _V80PoePruner()
    tree = pruner.visit(tree)
    ast.fix_missing_locations(tree)

    missing_handlers = _COMPACT_HANDLERS - pruner.compact_handlers_pruned
    if missing_handlers:
        missing = ", ".join(sorted(missing_handlers))
        raise RuntimeError(f"refusing to prune non-compact V8 handlers: {missing}")
    compact = POE_HEADER + ast.unparse(tree) + "\n"
    ast.parse(compact, feature_version=(3, 11))
    for text in _BANNED_TEXT:
        if text in compact:
            raise RuntimeError(f"retired money-management text remains: {text}")
    for symbol in _REMOVED_FUNCTIONS | _REMOVED_METHODS:
        if symbol in compact:
            raise RuntimeError(f"retired money-management symbol remains: {symbol}")
    return compact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = args.path.resolve()
    source = path.read_text(encoding="utf-8")
    compact = prune_source(source)
    old_size = len(source.encode("utf-8"))
    new_size = len(compact.encode("utf-8"))
    if args.check:
        if source != compact:
            raise SystemExit(
                f"{path.name} is not pruned: current={old_size} target={new_size} bytes"
            )
    else:
        path.write_text(compact, encoding="utf-8", newline="\n")
    print(
        f"{path.name}: {old_size} -> {new_size} bytes "
        f"({old_size - new_size:d} bytes removed)"
    )


if __name__ == "__main__":
    main()

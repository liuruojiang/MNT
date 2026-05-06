import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET_SCRIPTS = (
    "mnt_bot V 7.3 plus.py",
    "mnt_bot V 7.5 plus.py",
    "mnt_bot V 7.6 plus.py",
)


def _class_method_node(script_name, method_name):
    tree = ast.parse((ROOT / script_name).read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return item
    raise AssertionError(f"{method_name} not found in {script_name}")


class CurrentUsWeightScopeTests(unittest.TestCase):
    def test_current_us_w_is_defined_before_live_params_display_context_reads_it(self):
        for script_name in TARGET_SCRIPTS:
            with self.subTest(script=script_name):
                fn = _class_method_node(script_name, "_handle_live_params")
                stores = []
                loads = []
                for node in ast.walk(fn):
                    if isinstance(node, ast.Name) and node.id == "current_us_w":
                        location = (node.lineno, node.col_offset)
                        if isinstance(node.ctx, ast.Store):
                            stores.append(location)
                        elif isinstance(node.ctx, ast.Load):
                            loads.append(location)

                self.assertTrue(stores, f"{script_name} has no current_us_w assignment")
                self.assertTrue(loads, f"{script_name} has no current_us_w reads")
                self.assertLess(
                    min(stores),
                    min(loads),
                    f"{script_name} reads current_us_w before assigning it in _handle_live_params",
                )

    def test_us_rot_result_is_defined_before_live_signal_leg_table_reads_it(self):
        for script_name in TARGET_SCRIPTS:
            with self.subTest(script=script_name):
                fn = _class_method_node(script_name, "_handle_live_signal")
                stores = []
                loads = []
                for node in ast.walk(fn):
                    if isinstance(node, ast.Name) and node.id == "us_rot_result":
                        location = (node.lineno, node.col_offset)
                        if isinstance(node.ctx, ast.Store):
                            stores.append(location)
                        elif isinstance(node.ctx, ast.Load):
                            loads.append(location)

                self.assertTrue(stores, f"{script_name} has no us_rot_result assignment")
                self.assertTrue(loads, f"{script_name} has no us_rot_result reads")
                self.assertLess(
                    min(stores),
                    min(loads),
                    f"{script_name} reads us_rot_result before assigning it in _handle_live_signal",
                )

    def test_non_signal_day_keeps_latest_current_us_weights(self):
        for script_name in TARGET_SCRIPTS:
            for method_name, signal_var in (
                ("_compute_signal_data", "is_us_signal"),
                ("_handle_live_params", "is_us_signal_p"),
            ):
                with self.subTest(script=script_name, method=method_name):
                    fn = _class_method_node(script_name, method_name)
                    bad_assignments = []
                    for node in ast.walk(fn):
                        if not isinstance(node, ast.If):
                            continue
                        if not (
                            isinstance(node.test, ast.UnaryOp)
                            and isinstance(node.test.op, ast.Not)
                            and isinstance(node.test.operand, ast.Name)
                            and node.test.operand.id == signal_var
                        ):
                            continue
                        for child in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                            if (
                                isinstance(child, ast.Name)
                                and child.id == "current_us_w"
                                and isinstance(child.ctx, ast.Store)
                            ):
                                bad_assignments.append((child.lineno, child.col_offset))

                    self.assertFalse(
                        bad_assignments,
                        (
                            f"{script_name} {method_name} overwrites current_us_w on non-signal days; "
                            "live display should keep latest actual holdings"
                        ),
                    )

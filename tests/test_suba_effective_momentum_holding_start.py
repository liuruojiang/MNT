import ast
import pathlib
import unittest

import numpy as np
import pandas as pd


ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET_SCRIPTS = (
    "mnt_bot V 7.0 plus.py",
    "mnt_bot V 7.1 plus.py",
    "mnt_bot V 7.2 plus.py",
    "mnt_bot V 7.3 plus.py",
    "mnt_bot V 7.5 plus.py",
    "mnt_bot V 7.6 plus.py",
)


def _load_rank_helpers(script_name):
    script_path = ROOT / script_name
    tree = ast.parse(script_path.read_text(encoding="utf-8-sig"))
    wanted = {"_series_value_at", "_build_suba_momentum_rank_rows"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {
        "np": np,
        "pd": pd,
        "CN_NAMES": {"0.399606": "创业板", "cash": "现金"},
        "CN_R2_THRESHOLD": 0.2,
    }
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(script_path), "exec"), namespace)
    return namespace["_build_suba_momentum_rank_rows"]


class SubAEffectiveMomentumTests(unittest.TestCase):
    def test_effective_momentum_uses_current_holding_start_not_latest_same_asset_signal(self):
        dates = pd.date_range("2026-01-01", periods=5, freq="D")
        cn_result = pd.DataFrame(
            {
                "holding": ["0.399606", "0.399606", "0.399606", "0.399606", "0.399606"],
                "is_signal": [True, False, True, False, False],
                "weight": [0.5, 0.5, 1.0, 1.0, 1.0],
            },
            index=dates,
        )
        bias_mom = {"0.399606": pd.Series([10.0, 20.0, 30.0, 40.0, 50.0], index=dates)}
        r2 = {"0.399606": pd.Series([0.31, 0.32, 0.33, 0.34, 0.35], index=dates)}

        for script_name in TARGET_SCRIPTS:
            with self.subTest(script=script_name):
                build_rows = _load_rank_helpers(script_name)
                rows, meta = build_rows(cn_result, bias_mom, r2, ["0.399606"])

                self.assertEqual(meta["effective_date"], dates[0])
                self.assertEqual(meta["effective_holding"], "0.399606")
                self.assertEqual(rows[0]["effective_momentum"], 10.0)
                self.assertEqual(rows[0]["current_momentum"], 50.0)


if __name__ == "__main__":
    unittest.main()

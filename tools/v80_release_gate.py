"""V8.0 mandatory offline release tests, run through the managed test launcher.

Run from the repository: python -B tools/v80_release_gate.py
This module is also loaded as a pytest plugin by the launcher. It cannot
convert skipped or incomplete runs into a successful release receipt.
"""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
GATES = {
    'market_data': (
        'tests/test_v80_cn_finality_20261118.py',
        'tests/test_v80_suba_warmup_clock_20261120.py',
        'tests/test_v80_zz2000_adversarial_native.py',
    ),
    'calculation_execution': (
        'tests/test_v80_doublecheck_data_math_20261007.py::test_r2_ordinary_scale_matches_independent_normalized_correlation',
        'tests/test_v80_doublecheck_data_math_20261007.py::test_subc_flat_prices_scaling_transition_reconciles_fees_and_debt',
        'tests/test_v80_doublecheck_data_math_20261007.py::test_subc_zero_risk_signal_transition_does_not_borrow',
        'tests/test_v80_doublecheck_execution_20261007.py::test_weekly_model_plus_risk_transition_is_one_open_net_trade',
        'tests/test_v80_doublecheck_execution_20261007.py::test_b78_actual_trade_record_uses_b78_live_price_mapping',
        'tests/test_v80_doublecheck_execution_20261007.py::test_simultaneous_model_risk_record_uses_actual_open_net_trade_once',
    ),
    'rebalance': ('tests/test_v80_release_rebalance_prefix.py',),
    'report': ('tests/test_v80_release_report_parity.py',
               'tests/test_v80_report_inception_and_complete_months.py'),
}
SELECTORS = tuple(selector for group in GATES.values() for selector in group)
FIXED_FILES = (
    'mnt_bot V 8.0 plus.py', 'tools/v80_release_gate.py', 'run_tests.py', 'conftest.py',
    'tests/test_v80_reporting_repairs_20261015.py', 'mnt_strategy_data_cn.csv', 'mnt_strategy_data_us.csv',
    'research/data_quality/20261106_bond_intraday_acceptance/a_chain/end/native_prices.csv',
    'research/data_quality/20261106_bond_intraday_acceptance/a_chain/end/native_result.pkl',
    'outputs/v80_recert_20260926/l5/cn_a_daily_rebalance.csv',
    'outputs/v80_recert_20260926/l5/cn_adk_daily_rebalance.csv',
    'outputs/v80_recert_20260926/repair_20260930/bc_floor_daily.csv.gz',
    'tests/fixtures/v80_release_us_20251117.csv.gz',
    'tests/fixtures/v80_zz2000_fallback_20261113.csv',
)
_initial_manifest = {}
_collected = set()
_passed = set()
_rejected = set()
_deselected = set()


def _manifest():
    paths = set(FIXED_FILES) | {selector.split('::')[0] for selector in SELECTORS}
    paths.update(path.relative_to(ROOT).as_posix() for path in (ROOT / 'tests/fixtures').rglob('*') if path.is_file())
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(paths)}


def _write(config, text):
    reporter = config.pluginmanager.get_plugin('terminalreporter')
    if reporter is not None:
        reporter.write_line(text)
    else:
        print(text, flush=True)


def pytest_collection_finish(session):
    global _initial_manifest
    _initial_manifest = _manifest()  # Missing fixture is deliberately fatal.
    _collected.clear()
    _passed.clear()
    _rejected.clear()
    _collected.update(item.nodeid.replace('\\', '/') for item in session.items)
    missing = [selector for selector in SELECTORS if not any(
        node == selector or node.startswith(selector + '::') or node.startswith(selector + '[')
        for node in _collected)]
    if missing:
        _rejected.update('missing selector: ' + selector for selector in missing)
    _write(session.config, 'V80_RELEASE_MANIFEST ' + json.dumps({
        'files': _initial_manifest, 'gates': GATES, 'collected': sorted(_collected),
        'python': sys.version,
        'dependencies': {name: importlib.metadata.version(name) for name in
                         ('pytest', 'pandas', 'numpy', 'openpyxl', 'matplotlib', 'Pillow')},
    }, ensure_ascii=False, sort_keys=True))


def pytest_deselected(items):
    _deselected.update(item.nodeid for item in items)


def pytest_runtest_logreport(report):
    node = report.nodeid.replace('\\', '/')
    if report.skipped or report.failed or hasattr(report, 'wasxfail'):
        _rejected.add(node)
    if report.when == 'call' and report.passed and not hasattr(report, 'wasxfail'):
        _passed.add(node)


def pytest_sessionfinish(session, exitstatus):
    unchanged = bool(_initial_manifest) and _manifest() == _initial_manifest
    missing = _collected - _passed
    complete = bool(_collected) and not missing and not _rejected and not _deselected and unchanged and exitstatus == 0
    _write(session.config, 'V80_RELEASE_RESULT ' + json.dumps({
        'status': 'OFFLINE_PASS' if complete else 'BLOCKED',
        'collected': len(_collected), 'passed': len(_passed), 'missing': sorted(missing),
        'rejected': sorted(_rejected), 'deselected': sorted(_deselected), 'unchanged': unchanged,
    }, ensure_ascii=False, sort_keys=True))
    if not complete:
        session.exitstatus = 1


def main():
    print('Starting V8.0 release gate (managed test runner; results are stored in its receipt)...', flush=True)
    code = subprocess.call([sys.executable, '-B', str(ROOT / 'run_tests.py'), '--label', 'v80-release-gate',
                            '--', '-p', 'tools.v80_release_gate', '-q', '--tb=short', *SELECTORS], cwd=ROOT)
    status = 'OFFLINE_PASS (live Poe acceptance still required)' if code == 0 else 'BLOCKED (check the test receipt)'
    print(f'V8.0 release gate: {status}; exit code={code}', flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())

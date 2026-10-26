"""Replay captured amount inputs and native Sub-A parity without network.

Run from a Git checkout containing the recorded baseline commit. This checks
the frozen repair evidence, not current returns or a deployed Poe instance.
"""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types
import warnings

import pandas as pd

warnings.filterwarnings('ignore', category=FutureWarning)
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / 'mnt_bot V 8.0 plus.py'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load(data, name, poe=None):
    module = types.ModuleType(name)
    module.__file__ = str(SOURCE)
    if poe is not None:
        module.poe = poe
    sys.modules[name] = module
    exec(compile(data, str(SOURCE), 'exec'), module.__dict__)
    return module


def assignments(data):
    return {node.targets[0].id: ast.dump(node.value)
            for node in ast.parse(data).body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}


def main():
    manifest = json.loads((HERE / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        assert digest((HERE / name).read_bytes()) == expected, name
    source = SOURCE.read_bytes().replace(b'\r\n', b'\n')
    assert digest(source) == manifest['source_sha256'], 'run at the recorded repair revision'
    baseline = subprocess.check_output(['git', 'show', manifest['baseline_commit'] + ':mnt_bot V 8.0 plus.py'], cwd=ROOT)
    assert digest(baseline) == manifest['baseline_source_sha256']
    assert assignments(source) == assignments(baseline)

    current = load(source, 'v80_portable_amount_current')
    previous = load(baseline, 'v80_portable_amount_previous')

    def no_network(*args, **kwargs):
        raise AssertionError('Network disabled for captured-input replay')

    current.requests.sessions.Session.request = no_network
    providers = {}
    for secid, label in [(current.CN_SA_VOLUME_ZZ2000_SECID, 'ZZ2000'),
                         (current.CN_SA_VOLUME_CYB_SECID, 'CYB')]:
        frame = pd.read_csv(HERE / (label + '_amount.csv'), index_col=0, parse_dates=True, float_precision='round_trip')
        providers[secid] = (frame, manifest['providers'][label]['source'])

    def captured_provider(secid, label, **kwargs):
        frame, source_name = providers[secid]
        return frame.copy(), source_name

    for module in (current, previous):
        module._fetch_cn_amount_with_fallback = captured_provider
    asof = pd.Timestamp(manifest['report_cutoff'])
    _, feature = current._load_suba_volume_signal(expected_date=asof)
    consumed = current._expected_cn_sessions('2017-05-26', asof)
    assert not current._suba_volume_feature_has_unresolved(feature, consumed)
    cn = pd.read_csv(HERE / 'cn_prices.csv.gz', index_col=0, parse_dates=True, float_precision='round_trip')
    results = []
    for module in (previous, current):
        base = module.run_cn_strategy(cn, module.CN_EQUITY_CODES)
        end = module._latest_confirmed_cn_rule_date(cn.index)
        signal, feat = module._load_suba_volume_signal(expected_date=end)
        feat = module._annotate_rule_freshness(feat, end, 'suba_volume')
        results.append(module._apply_suba_volume_overlay_policy(base, cn, signal, feat))
    pd.testing.assert_frame_equal(results[0], results[1], check_exact=True)

    class SandboxPoe:
        def __getattr__(self, name):
            if name == 'BotError':
                raise AttributeError("'poe' module attribute 'BotError' is not available in this context")
            raise AttributeError(name)

        def update_settings(self, settings):
            pass

    load(source, 'v80_portable_poe_bootstrap', SandboxPoe())
    return {'status': 'PASS', 'network_enabled': False, 'source_sha256': digest(source),
            'unchanged_top_level_assignments': len(assignments(source)),
            'consumed_amount_sessions': len(consumed), 'unresolved_consumed_sessions': 0,
            'native_suba_rows_exact_equal': len(results[0]), 'poe_bootstrap_simulation': 'PASS',
            'basis': 'captured-data diagnostic regression; no current five-sleeve performance or online deployment acceptance'}


if __name__ == '__main__':
    print(json.dumps(main(), ensure_ascii=False, indent=2))

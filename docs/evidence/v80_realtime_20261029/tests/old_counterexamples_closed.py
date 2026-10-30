"""Independent offline adversarial replay. Mutated receipts are test inputs only."""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

root = next(parent for parent in Path(__file__).resolve().parents if (parent / 'mnt_bot V 8.0 plus.py').is_file())
spec = importlib.util.spec_from_file_location('audit_tests_repro_v80', root / 'mnt_bot V 8.0 plus.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
fixture = root / 'tests/fixtures/v80_realtime_20261029'
quote = json.loads((fixture / 'quote.json').read_text(encoding='utf-8'))['payload']
trends = json.loads((fixture / 'trends.json').read_text(encoding='utf-8'))['payload']
module.beijing_now = lambda: pd.Timestamp('2026-10-29 14:28:13').to_pydatetime()
module._fetch_cn_realtime_close_quote_fallback = lambda *args, **kwargs: None


class Response:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


results = []
for name, rows in [('same_day_opening_only', trends['data']['trends'][:1]),
                   ('invalid_lunch_time', ['2026-10-29 12:30,100,999,100,100,1,1,1'])]:
    altered = copy.deepcopy(trends)
    altered['data']['trends'] = rows
    module.requests.get = lambda url, **kw: Response(
        {'data': None} if 'secid=1.930955' in url else altered if 'trends2' in url else quote)
    result = module._fetch_cn_realtime_close('1.930955')
    results.append({'case': name, 'observed': result, 'expected': None, 'rejected': result is None})
print(json.dumps(results, indent=2))
(Path(__file__).parent / 'observed.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
assert results[0]['observed'] is None
assert results[1]['observed'] is None

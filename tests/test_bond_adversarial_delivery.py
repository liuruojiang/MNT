"""Audit frozen source evidence independently of strategy and service loaders."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'research/data_quality/20261105_bond_replacement'


@pytest.mark.parametrize('name', ['sina', 'tencent', 'original_csi',
    'original_qq_daily', 'original_sina_daily', 'original_qq_quote',
    'original_sina_quote', 'replacement_qq_quote', 'replacement_sina_quote'])
def test_frozen_market_responses_match_recorded_digest(name):
    body = (EVIDENCE / (name + '.raw')).read_bytes()
    receipt = json.loads((EVIDENCE / (name + '_receipt.json')).read_text(encoding='utf-8'))
    assert receipt['status'] == 200
    assert hashlib.sha256(body).hexdigest() == receipt['sha256']
    assert pd.Timestamp(receipt['retrieved_at_utc']).tz_convert('Asia/Shanghai').date().isoformat() == '2026-11-05'


def test_full_history_extract_matches_native_sina_overlap():
    history = pd.read_csv(EVIDENCE / 'native_bond_history.csv', index_col=0, parse_dates=True)['close']
    native = json.loads((EVIDENCE / 'sina.raw').read_bytes())
    assert history.index.is_unique and history.index.is_monotonic_increasing
    assert str(history.index.min().date()) == '2003-01-02'
    for row in native:
        assert history[pd.Timestamp(row['day'])] == pytest.approx(float(row['close']), abs=1e-10)


def test_realtime_evidence_is_explicitly_after_close_not_intraday():
    qq = (EVIDENCE / 'replacement_qq_quote.raw').read_bytes().decode('gb18030')
    sina = (EVIDENCE / 'replacement_sina_quote.raw').read_bytes().decode('gb18030')
    q = qq.split('"')[1].split('~')
    s = sina.split('"')[1].split(',')
    assert qq.startswith('v_sh000012=') and q[2] == '000012'
    assert sina.startswith('var hq_str_sh000012=')
    tq = pd.Timestamp(q[30]); ts = pd.Timestamp(s[30] + ' ' + s[31])
    assert tq > pd.Timestamp('2026-11-05 15:00')
    assert ts > pd.Timestamp('2026-11-05 15:00')
    assert abs(float(q[3]) - float(s[3])) <= .011

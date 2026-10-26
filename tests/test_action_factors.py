"""Actual frozen QQQ seam, plus explicitly mutated adversarial inputs."""
import copy
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from source_audit.action_factors import inspect_yahoo_action, upstream_counterfactual

ARGS=dict(symbol='QQQ',ex_date='2020-09-21',prior_date='2020-09-18',expected_cash=0.38824)


def fixture():
    return json.loads((ROOT/'tests/fixtures/us_source_audit/qqq_20200921_seam.json').read_text())


def test_actual_missing_factor_fixed_once_and_upstream_fixed_price_not_adjusted_again():
    original=fixture()
    frozen=copy.deepcopy(original)
    assert inspect_yahoo_action(original,**ARGS)['classification']=='PRICE_FACTOR_ERROR'
    corrected,proof=upstream_counterfactual(original,**ARGS)
    assert original==frozen and corrected!=original
    assert proof['raw_quotes_unchanged'] and proof['post_ex_adjusted_prices_unchanged']
    assert not proof['production_approved'] and not proof['full_series_integrity_certified']
    second,again=upstream_counterfactual(corrected,**ARGS)
    assert second==corrected
    assert not again['before']['price_repair_needed_at_local_seam']


def test_duplicate_market_date_is_rejected_without_mutating_input():
    value=fixture()
    value['chart']['result'][0]['timestamp'][1]=value['chart']['result'][0]['timestamp'][0]
    frozen=copy.deepcopy(value)
    with pytest.raises(ValueError): upstream_counterfactual(value,**ARGS)
    assert value==frozen


def test_identity_or_nonadjacent_anchor_cannot_drive_a_repair():
    value=fixture()
    with pytest.raises(ValueError): upstream_counterfactual(value,**{**ARGS,'symbol':'SPY'})
    with pytest.raises(ValueError): upstream_counterfactual(value,**{**ARGS,'ex_date':'2020-09-22'})

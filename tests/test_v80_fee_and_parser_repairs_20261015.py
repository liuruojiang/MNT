"""Quantity-based annual fees and strict date-token regression contracts.

Synthetic prices test cash/quantity invariants only, not strategy performance.
The default fixture always imports the authoritative current V8.0 entrypoint.
"""
import importlib.util
import itertools
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def v80():
    spec = importlib.util.spec_from_file_location(
        "v80_fee_parser_repairs_20261015", ROOT / "mnt_bot V 8.0 plus.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(autouse=True)
def local_only(v80, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("fee/parser regression must not request network or LLM")
    monkeypatch.setattr(v80.requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(v80.poe, "call", forbidden)
    monkeypatch.setattr(v80, "beijing_now", lambda: pd.Timestamp("2026-10-15 12:00:00").to_pydatetime())


def exact_fee_fraction_from_trade_signs(before_weights, target_weights, fee_rate):
    """Independent finite active-set oracle, not iterative production solving."""
    before = np.asarray(before_weights, dtype=float)
    target = np.asarray(target_weights, dtype=float)
    candidates = []
    for sign_values in itertools.product((-1., 1.), repeat=len(target)):
        signs = np.asarray(sign_values)
        numerator = fee_rate * math.fsum(signs * (target - before))
        denominator = 1 + fee_rate * math.fsum(signs * target)
        if denominator <= 0:
            continue
        fee = numerator / denominator
        if fee < -1e-14 or fee >= 1:
            continue
        trades = target * (1 - fee) - before
        if np.all(signs * trades >= -1e-13):
            candidates.append(max(fee, 0.))
    assert candidates, "no consistent trade-sign root"
    assert max(candidates) - min(candidates) < 1e-12
    return float(candidates[0])


def year_end_case(module, final_prices=(400., 100., 100.), fee_rate=None):
    dates = pd.to_datetime(["2025-12-30", "2025-12-31", "2026-01-02"])
    prices = pd.DataFrame({
        "AAA": [100., final_prices[0], final_prices[0]],
        "BBB": [100., final_prices[1], final_prices[1]],
        "CCC": [100., final_prices[2], final_prices[2]],
        "BIL": 100.,
    }, index=dates)
    portfolio = {"AAA": {"w": .2, "proxy": "AAA"},
                 "BBB": {"w": .3, "proxy": "BBB"},
                 "CCC": {"w": .5, "proxy": "CCC"}}
    signals = pd.DataFrame(1., columns=list(portfolio),
                           index=pd.to_datetime(["2025-12-31", "2026-01-31"]))
    kwargs = {} if fee_rate is None else {"annual_rebalance_cost": fee_rate}
    output = module._compute_daily_subc_components(prices, signals, portfolio, "BIL", **kwargs)
    return prices, portfolio, output


@pytest.mark.parametrize("final_prices", [
    (400., 100., 100.), (100., 400., 100.), (100., 100., 400.), (100.1, 100., 100.)
])
def test_subc_year_end_fee_matches_post_fee_actual_quantity_turnover(v80, final_prices):
    _, portfolio, output = year_end_case(v80, final_prices)
    row = output.loc["2025-12-31"]
    names = list(portfolio)
    before = np.array([row[f"pre_close_weight::{name}"] for name in names])
    target = np.array([row[f"close_weight::{name}"] for name in names])
    expected_fee = exact_fee_fraction_from_trade_signs(before, target, v80.PROD_COMMISSION)
    fee = float(row["asset_cost_fraction"])
    actual_turnover = float(np.abs(target * (1 - fee) - before).sum())
    assert fee == pytest.approx(expected_fee, abs=2e-14, rel=0)
    assert fee == pytest.approx(v80.PROD_COMMISSION * actual_turnover, abs=2e-14, rel=0)
    assert row["asset_turnover"] == pytest.approx(actual_turnover, abs=2e-14, rel=0)
    pre_fee_equity = sum(portfolio[name]["w"] * final_prices[i] / 100 for i, name in enumerate(names))
    assert row["asset_cost_return"] == pytest.approx(-pre_fee_equity * fee, abs=2e-14, rel=0)
    assert row["base_return"] == pytest.approx(pre_fee_equity * (1 - fee) - 1, abs=2e-14, rel=0)
    assert bool(row["annual_rebalanced"])
    assert not bool(output.loc["2026-01-02", "annual_rebalanced"])
    assert output.loc["2026-01-02", "asset_cost_fraction"] == 0


def test_subc_flat_year_end_retains_zero_fee_and_no_trade(v80):
    _, _, output = year_end_case(v80, (100., 100., 100.))
    assert output["asset_cost_fraction"].eq(0).all()
    assert output["asset_turnover"].eq(0).all()
    assert not output["annual_rebalanced"].any()
    assert output["base_return"].eq(0).all()


def test_subc_zero_fee_preserves_quantity_rebalance_and_return(v80):
    _, _, output = year_end_case(v80, fee_rate=0.)
    row = output.loc["2025-12-31"]
    assert row["asset_cost_fraction"] == 0
    assert row["asset_cost_return"] == 0
    assert row["asset_turnover"] == pytest.approx(.6, abs=2e-14, rel=0)
    assert row["base_return"] == pytest.approx(.6, abs=2e-14, rel=0)
    assert bool(row["annual_rebalanced"])


@pytest.mark.parametrize("text", [
    "表现 2026-9e3",
    "表现 2026-09-24e3",
    "performance 2026-09-24E+3",
    "表现 2026-09-21至2026-09-24e3",
])
@pytest.mark.parametrize("entrypoint", ["parse_date_range", "parse_all_date_ranges", "llm_fallback"])
def test_malformed_date_suffix_is_rejected_before_fallback(v80, text, entrypoint):
    function = (v80.CombinedStrategyV80()._parse_date_with_llm_fallback
                if entrypoint == "llm_fallback" else getattr(v80, entrypoint))
    with pytest.raises(ValueError, match="日期"):
        function(text)


def test_multi_range_cannot_silently_accept_invalid_second_date(v80):
    with pytest.raises(ValueError, match="日期"):
        v80.parse_all_date_ranges("表现2026年以及2026-09-24e3")


@pytest.mark.parametrize("text", ["表现 2026-09-241", "表现 2026-01-011", "表现 2026-091"])
@pytest.mark.parametrize("entrypoint", ["parse_date_range", "parse_all_date_ranges", "llm_fallback"])
def test_overlong_numeric_date_components_cannot_degrade_to_month(v80, text, entrypoint):
    function = (v80.CombinedStrategyV80()._parse_date_with_llm_fallback
                if entrypoint == "llm_fallback" else getattr(v80, entrypoint))
    with pytest.raises(ValueError, match="日期"):
        function(text)


@pytest.mark.parametrize("text, start, end", [
    ("表现 2026-09", "2026-09-01", "2026-09-30"),
    ("performance for 2026-09", "2026-09-01", "2026-09-30"),
    ("show performance for 2026-09-24", "2026-09-24", "2026-09-24"),
    ("2026-09-24 performance", "2026-09-24", "2026-09-24"),
    ("表现2026年9月24日", "2026-09-24", "2026-09-24"),
    ("表现2026/9/24", "2026-09-24", "2026-09-24"),
    ("表现2026.9.24", "2026-09-24", "2026-09-24"),
    ("2026年9月21日至2026年9月24日表现", "2026-09-21", "2026-09-24"),
    ("2026年9月至今的表现", "2026-09-01", "2026-10-15"),
    ("表现过去一年", "2025-10-15", "2026-10-15"),
    ("表现 2026-01-2026-09", "2026-01-01", "2026-09-30"),
])
def test_valid_chinese_and_english_query_surroundings_remain_accepted(v80, text, start, end):
    assert v80.parse_date_range(text) == (pd.Timestamp(start), pd.Timestamp(end))

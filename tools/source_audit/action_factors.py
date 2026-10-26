"""Pure local-seam diagnostics and upstream counterfactuals, never source acceptance.

Cash-reference approval is supplied by the caller. This module does not certify
the full prefix/suffix, other actions, raw quotes or project data completeness.
No strategy imports, network calls, cache access or production writes occur.
"""
import copy
from datetime import datetime, timezone
import math
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')


def _positive(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a price')
    out = float(value)
    if not math.isfinite(out) or out <= 0:
        raise ValueError('Invalid price/amount')
    return out


def _result(payload):
    chart = payload['chart']
    if chart.get('error') or len(chart.get('result') or []) != 1:
        raise ValueError('Ambiguous Yahoo result')
    return chart['result'][0]


def inspect_yahoo_action(payload, *, symbol, ex_date, prior_date, expected_cash,
                         recognized_complete_amounts=(), cash_tolerance=0.0001):
    """Infer Yahoo cash from adjacent raw/adjusted closes under Yahoo convention.

    Recognized rounded amounts must be explicitly supplied; they are not
    inferred from a cash field which may itself be wrong. Field agreement and
    price-factor agreement are separate outputs. No full-series pass is issued.
    """
    expected_cash = _positive(expected_cash)
    tolerance = _positive(cash_tolerance)
    r = _result(payload)
    if r.get('meta', {}).get('symbol') != symbol:
        raise ValueError('Symbol mismatch')
    ts = r['timestamp']
    if not isinstance(ts, list) or not ts or any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) for t in ts):
        raise ValueError('Invalid timestamps')
    if ts != sorted(set(ts)):
        raise ValueError('Duplicate/unsorted timestamps')
    days = [datetime.fromtimestamp(t, timezone.utc).astimezone(NY).date().isoformat() for t in ts]
    if len(days) != len(set(days)):
        raise ValueError('Duplicate market dates')
    ip, ie = days.index(prior_date), days.index(ex_date)
    if ie != ip + 1:
        raise ValueError('Nonadjacent action anchors')
    close = r['indicators']['quote'][0]['close']
    adjusted = r['indicators']['adjclose'][0]['adjclose']
    if len(close) != len(ts) or len(adjusted) != len(ts):
        raise ValueError('Price-field lengths disagree')
    p, e, ap, ae = [_positive(v) for v in (close[ip], close[ie], adjusted[ip], adjusted[ie])]
    if p <= expected_cash:
        raise ValueError('Cash exceeds prior price')
    old_factor_ratio = (ap / p) / (ae / e)
    implied_cash = p * (1 - old_factor_ratio)
    allowed = [expected_cash] + [_positive(v) for v in recognized_complete_amounts]
    exact = abs(implied_cash - expected_cash) <= tolerance
    recognized = min(abs(implied_cash - amount) for amount in allowed) <= tolerance
    events = []
    for item in r.get('events', {}).get('dividends', {}).values():
        day = datetime.fromtimestamp(item['date'], timezone.utc).astimezone(NY).date().isoformat()
        if day == ex_date:
            events.append(item)
    if len(events) > 1:
        raise ValueError('Duplicate cash events')
    declared_cash = float(events[0]['amount']) if events else None
    if declared_cash is not None and (not math.isfinite(declared_cash) or declared_cash < 0):
        raise ValueError('Invalid declared cash')
    return {
        'symbol': symbol, 'ex_date': ex_date, 'prior_date': prior_date,
        'expected_cash': expected_cash, 'cash_tolerance': tolerance,
        'yahoo_event_cash': declared_cash, 'yahoo_cash_event_present': bool(events),
        'yahoo_factor_implied_cash': implied_cash,
        'cash_event_matches_reference': declared_cash is not None and abs(declared_cash - expected_cash) <= tolerance,
        'price_factor_matches_exact_reference': exact,
        'price_factor_matches_recognized_complete_basis': recognized,
        'classification': 'PRICE_FACTOR_ERROR' if not recognized else ('PRICE_FACTOR_EXACT' if exact else 'RECOGNIZED_ROUNDING_BASIS'),
        'prior_raw_close': p, 'ex_raw_close': e, 'prior_adjusted_close': ap, 'ex_adjusted_close': ae,
        'observed_factor_ratio': old_factor_ratio,
        'yahoo_adjusted_return_before': ae / ap - 1,
        'yahoo_basis_reference_return': e / (p - expected_cash) - 1,
        'counterfactual_prefix_scale': (1 - expected_cash / p) / old_factor_ratio,
        'price_repair_needed_at_local_seam': not recognized,
        'full_series_integrity_certified': False, 'production_approved': False,
    }


def upstream_counterfactual(payload, *, symbol, ex_date, prior_date, expected_cash,
                            recognized_complete_amounts=(), cash_tolerance=0.0001):
    """Create a new upstream response for a frozen, explicitly labelled study.

    This is a local counterfactual, not a general production repair. The raw
    quote block and every adjusted price on/after ex-date are preserved exactly.
    A second application changes no price. Caller must retain provenance and
    enforce full history/action/coverage gates before any future promotion.
    """
    args = dict(symbol=symbol, ex_date=ex_date, prior_date=prior_date, expected_cash=expected_cash,
                recognized_complete_amounts=recognized_complete_amounts, cash_tolerance=cash_tolerance)
    diagnostic = inspect_yahoo_action(payload, **args)
    out = copy.deepcopy(payload)
    r = _result(out)
    days = [datetime.fromtimestamp(t, timezone.utc).astimezone(NY).date().isoformat() for t in r['timestamp']]
    ie = days.index(ex_date)
    if diagnostic['price_repair_needed_at_local_seam']:
        a = r['indicators']['adjclose'][0]['adjclose']
        scale = diagnostic['counterfactual_prefix_scale']
        for i in range(ie):
            if a[i] is not None:
                a[i] = _positive(a[i]) * scale
    dividends = r.setdefault('events', {}).setdefault('dividends', {})
    for key, value in list(dividends.items()):
        day = datetime.fromtimestamp(value['date'], timezone.utc).astimezone(NY).date().isoformat()
        if day == ex_date:
            del dividends[key]
    dividends[str(r['timestamp'][ie])] = {'amount': float(expected_cash), 'date': r['timestamp'][ie]}
    after = inspect_yahoo_action(out, **args)
    if not after['price_factor_matches_recognized_complete_basis']:
        raise ValueError('Counterfactual did not verify')
    return out, {'before': diagnostic, 'after': after, 'mode': 'FROZEN_UPSTREAM_COUNTERFACTUAL_ONLY',
                 'raw_quotes_unchanged': _result(payload)['indicators']['quote'] == r['indicators']['quote'],
                 'post_ex_adjusted_prices_unchanged': _result(payload)['indicators']['adjclose'][0]['adjclose'][ie:] == r['indicators']['adjclose'][0]['adjclose'][ie:],
                 'full_series_integrity_certified': False, 'production_approved': False}

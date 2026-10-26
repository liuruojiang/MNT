"""Exchange-session checks independent of both price vendors."""
import ast
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
US_POLICY_SHA256 = 'bf64b334274a37b2b2b735ca78da8c5e16fb52aeeec2d2ece1a8c7056ef4d76b'
NYSE_URL = 'https://www.nyse.com/markets/hours-calendars'
SSE_URL = 'https://www.sse.com.cn/disclosure/dealinstruc/closed/'
CN_2026_CLOSED_RANGES = [('2026-01-01', '2026-01-03'), ('2026-02-15', '2026-02-23'),
    ('2026-04-04', '2026-04-06'), ('2026-05-01', '2026-05-05'), ('2026-06-19', '2026-06-21'),
    ('2026-09-25', '2026-09-27'), ('2026-10-01', '2026-10-07')]


class CalendarCoverageError(ValueError):
    pass


def _us_namespace():
    # Reuse the already-reviewed formal calendar's pure functions only. Never
    # import or execute the bot, its caches, queries or portfolio implementation.
    path = REPO / 'mnt_bot V 8.0 plus.py'
    body = path.read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(body).hexdigest() != US_POLICY_SHA256:
        raise CalendarCoverageError('Formal calendar source changed; review its policy before reuse')
    tree = ast.parse(body.decode('utf-8'))
    functions = {'_us_observed_holiday', '_us_nth_weekday', '_us_last_weekday', '_gregorian_easter', '_us_market_holidays'}
    assignments = {'XNYS_AD_HOC_CLOSURES', '_US_MARKET_HOLIDAY_CACHE'}
    selected = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in functions)
                or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in assignments for t in n.targets))]
    if len(selected) != len(functions) + len(assignments):
        raise CalendarCoverageError('Calendar pure-function contract differs')
    namespace = {'pd': pd}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path) + ':calendar-only', 'exec'), namespace)
    return namespace


def sessions(market, start, end):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start.tzinfo or end.tzinfo or start != start.normalize() or end != end.normalize() or start > end:
        raise CalendarCoverageError('Invalid session bounds')
    days = pd.bdate_range(start, end)
    if market == 'XNYS':
        if start.year < 2003 or end.year > 2027:
            raise CalendarCoverageError('US rules supported from 2003 through official forward calendar 2027')
        ns = _us_namespace()
        closed = set().union(*(ns['_us_market_holidays'](year) for year in range(start.year, end.year + 1)))
    elif market in {'XSHG', 'XSHE'}:
        if start.year != 2026 or end.year != 2026:
            raise CalendarCoverageError('Independent China calendar currently certified for 2026 only')
        closed = set().union(*(set(pd.date_range(a, b)) for a, b in CN_2026_CLOSED_RANGES))
    else:
        raise CalendarCoverageError('Unsupported market')
    return days[~days.isin(pd.DatetimeIndex(sorted(closed)))]


def confirmed_cutoff(market, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise CalendarCoverageError('Timezone-aware clock required')
    zone, hour = ('America/New_York', 21) if market == 'XNYS' else ('Asia/Shanghai', 16)
    local = now.astimezone(ZoneInfo(zone))
    day = local.date() if local.hour >= hour else local.date() - timedelta(days=1)
    begin = max(day - timedelta(days=20), datetime(day.year, 1, 1).date()) if market != 'XNYS' else day - timedelta(days=20)
    available = sessions(market, begin, day)
    if not len(available):
        raise CalendarCoverageError('No confirmed exchange session in checked window')
    return available[-1].date().isoformat()


def document(market, start, end):
    ix = sessions(market, start, end)
    return {'market': market, 'source': NYSE_URL if market == 'XNYS' else SSE_URL,
            'calendar_basis': 'exchange_rules_independent_of_prices', 'start': str(pd.Timestamp(start).date()),
            'end': str(pd.Timestamp(end).date()), 'sessions': [str(d.date()) for d in ix],
            'historical_point_in_time_certified': False,
            'rule_source_lf_sha256': US_POLICY_SHA256 if market == 'XNYS' else None}

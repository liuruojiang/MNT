"""Read-only candidate gate; does not register Wind as a strategy data source."""
import json,re
from urllib.parse import urlparse
import pandas as pd
import numpy as np

class WindIntervalConflict(ValueError):
    """No data may be consumed or cached after this exception."""

FIELDS={'OPEN':'open','HIGH':'high','LOW':'low','MATCH':'close','VOLUME':'volume'}

def parse_index_kline(payload):
    """Parse the actual Wind index MCP schema, preserving its daily date label.

    The observed TIME strings use +02:00; they are daily labels, not proof of
    Chinese-market closing time. Caller must supply confirmed required sessions.
    """
    try:
        if payload.get('error') or payload.get('result',{}).get('isError'):
            raise WindIntervalConflict('Wind returned an error')
        blocks=[c['text'] for c in payload['result']['content'] if c.get('type')=='text']
        if len(blocks)!=1:raise WindIntervalConflict('Ambiguous Wind content blocks')
        decoded=json.loads(blocks[0])
        if decoded.get('error'):raise WindIntervalConflict('Wind data error')
        data=decoded['data'];names=[c['name'] for c in data['columns']]
        if len(names)!=len(set(names)) or not {'TIME',*FIELDS}.issubset(names):
            raise WindIntervalConflict('Missing/duplicate Wind columns')
        frame=pd.DataFrame(data['rows'],columns=names)
        # Inspect raw JSON types before conversion: True in a mixed numeric
        # column would otherwise silently become 1.0 and defeat dtype checks.
        if frame[list(FIELDS)].map(lambda value:isinstance(value,(bool,np.bool_))).any().any():
            raise WindIntervalConflict('Boolean value in raw Wind OHLCV fields')
        units=data.get('unit',{})
        if not isinstance(units,dict):
            raise WindIntervalConflict('Invalid Wind unit metadata')
        declared=[value for key,value in units.items() if 'VOLUME' in str(key).upper() or '成交量' in str(key)]
        declared += [c['unit'] for c in data['columns'] if c['name']=='VOLUME' and c.get('unit') is not None]
        if any(not isinstance(unit,str) or unit.strip().lower() not in ('股','share','shares') for unit in declared):
            raise WindIntervalConflict('Wind volume unit differs from verified share basis')
        times=frame['TIME'].astype(str)
        if not times.str.match(r'^\d{4}-\d{2}-\d{2}T00:00:00(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$').all():
            raise WindIntervalConflict('Invalid daily timestamp labels')
        # Validate offsets without using UTC conversion to shift a daily label.
        pd.to_datetime(times,utc=True,errors='raise')
        frame.index=pd.to_datetime(times.str[:10],format='%Y-%m-%d',errors='raise')
        out=frame.rename(columns=FIELDS)[list(FIELDS.values())].apply(pd.to_numeric,errors='raise')
        out.attrs['_source_provider']='wind'
        out.attrs['_response_request_id']=payload['result'].get('_meta',{}).get('requestId')
        return out
    except WindIntervalConflict:raise
    except (KeyError,ValueError,TypeError,IndexError) as exc:
        raise WindIntervalConflict('Unsupported Wind response schema') from exc

def parse_csindex_reference(payload):
    """Build a labelled external reference from the real CSI response schema.

    This preserves provenance and code checks; it is not authentication of a
    caller-supplied object. The caller must fetch it from the official origin.
    """
    try:
        if str(payload.get('code'))!='200':
            raise WindIntervalConflict('Independent CSI reference reports an error')
        raw=pd.DataFrame(payload['data'])
        if raw.empty or raw['indexCode'].nunique()!=1:
            raise WindIntervalConflict('Independent CSI reference has ambiguous index identity')
        code=str(raw['indexCode'].iloc[0])
        out=raw.rename(columns={'tradingVol':'volume'})[['open','high','low','close','volume']].copy()
        if out.map(lambda value:isinstance(value,(bool,np.bool_))).any().any():
            raise WindIntervalConflict('Boolean value in CSI reference')
        out.index=pd.to_datetime(raw['tradeDate'],format='%Y%m%d',errors='raise')
        out=out.apply(pd.to_numeric,errors='raise').sort_index()
        out.attrs.update({'_source_provider':'csindex','_index_code':code,
                          '_source_url':'https://www.csindex.com.cn/csindex-home/perf/index-perf'})
        return out
    except WindIntervalConflict:raise
    except (KeyError,TypeError,ValueError) as exc:
        raise WindIntervalConflict('Unsupported independent CSI reference schema') from exc

def _validate(frame,start,end,sessions,label):
    if not isinstance(frame,pd.DataFrame) or frame.empty or set(frame.columns)!=set(FIELDS.values()):
        raise WindIntervalConflict(label+': empty/invalid OHLCV frame')
    ix=frame.index
    if not isinstance(ix,pd.DatetimeIndex) or ix.tz is not None or ix.hasnans or ix.has_duplicates or not ix.is_monotonic_increasing or not ix.equals(ix.normalize()):
        raise WindIntervalConflict(label+': invalid/duplicate daily date index')
    if ix.min()<start or ix.max()>end or len(ix.difference(sessions)):
        raise WindIntervalConflict(label+': outside requested confirmed sessions')
    if any(pd.api.types.is_bool_dtype(frame[col]) for col in frame) or not np.isfinite(frame.to_numpy(dtype=float)).all() or (frame[['open','high','low','close']]<=0).any().any() or (frame.volume<0).any():
        raise WindIntervalConflict(label+': invalid OHLCV values')
    if (frame.high<frame[['open','low','close']].max(axis=1)).any() or (frame.low>frame[['open','high','close']].min(axis=1)).any():
        raise WindIntervalConflict(label+': impossible OHLC range')

def validate_long_short(long_frame,short_frame,*,start,end,confirmed_sessions,tail_sessions=5,reference=None):
    """Require complete coverage and agreement before returning a fresh copy.

    Prices permit one quoted cent plus float tolerance; Wind volume permits
    one 100-share quoting lot. No relative tolerance can conceal a large error.
    Optional independent reference must cover every short-window session.
    """
    start,end=pd.Timestamp(start),pd.Timestamp(end)
    sessions=pd.DatetimeIndex(confirmed_sessions)
    if start.tzinfo or end.tzinfo or start!=start.normalize() or end!=end.normalize() or start>end:
        raise WindIntervalConflict('Invalid query bounds')
    if sessions.empty or sessions.tz is not None or sessions.hasnans or sessions.has_duplicates or not sessions.is_monotonic_increasing or not sessions.equals(sessions.normalize()) or sessions.min()<start or sessions.max()!=end or not isinstance(tail_sessions,int) or isinstance(tail_sessions,bool) or tail_sessions<1:
        raise WindIntervalConflict('Caller must supply ordered confirmed exchange sessions through required end')
    recent=sessions[-tail_sessions:]
    # A range equal to the probe is one query repeated, not range independence.
    if len(recent)==len(sessions) and reference is None:
        raise WindIntervalConflict('Long and short windows coincide; independent reference required')
    _validate(long_frame,start,end,sessions,'long')
    _validate(short_frame,recent[0],end,recent,'short')
    problems=[]
    for label,frame,required in [('long',long_frame,sessions),('short',short_frame,recent)]:
        missing=required.difference(frame.index)
        if len(missing):problems.append(label+' missing '+','.join(missing.strftime('%Y-%m-%d')[:5]))
    def mismatches(a,b,ix,label):
        for col in FIELDS.values():
            tolerance=100. if col=='volume' else .011
            bad=~np.isclose(a.loc[ix,col].to_numpy(dtype=float),b.loc[ix,col].to_numpy(dtype=float),atol=tolerance,rtol=0)
            if bad.any():problems.append(label+' '+col+' '+','.join(ix[bad].strftime('%Y-%m-%d')[:5]))
    common=recent.intersection(long_frame.index).intersection(short_frame.index)
    if len(common):mismatches(long_frame,short_frame,common,'long/short conflict')
    if reference is not None:
        if reference is long_frame or reference is short_frame or reference.attrs.get('_source_provider')=='wind':
            raise WindIntervalConflict('Wind data cannot serve as its own independent reference')
        source=urlparse(reference.attrs.get('_source_url',''))
        if reference.attrs.get('_source_provider')!='csindex' or source.scheme!='https' or source.hostname!='www.csindex.com.cn':
            raise WindIntervalConflict('Reference provenance missing; use parse_csindex_reference with official data')
        requested=long_frame.attrs.get('_requested_windcode')
        if requested and reference.attrs.get('_index_code')!=requested.split('.')[0]:
            raise WindIntervalConflict('Independent reference index code differs from requested Wind code')
        _validate(reference,recent[0],end,recent,'independent reference')
        absent=recent.difference(reference.index)
        if len(absent):problems.append('independent reference incomplete')
        ref_common=common.intersection(reference.index)
        if len(ref_common):
            mismatches(short_frame,reference,ref_common,'short/reference conflict')
            mismatches(long_frame,reference,ref_common,'long/reference conflict')
    if problems:raise WindIntervalConflict('; '.join(problems))
    result=long_frame.copy(deep=True)
    result.attrs['wind_interval_validation']={'required_end':end.date().isoformat(),'tail_sessions':len(recent),'independent_reference':reference is not None,'reference_origin':'caller-supplied CSI schema/provenance' if reference is not None else None,'reference_authentication':'caller responsibility','long_rows':len(long_frame),'price_abs_tolerance':.011,'volume_abs_tolerance':100,'checked_value_dates':recent.strftime('%Y-%m-%d').tolist(),'unchecked_historical_value_sessions':len(sessions.difference(recent)),'intervals_distinct':len(recent)<len(sessions),'coverage':'recent overlap OHLCV plus full date coverage; not all-history value certification'}
    return result

def fetch_checked_index(fetch,*,windcode,start,end,confirmed_sessions,tail_sessions=5,reference=None):
    """fetch(code, begin, end) must call get_index_kline with period='10'.

    No account/client or cache is created here. Both calls must succeed; no
    partial return is exposed on any transport/schema/consistency failure.
    """
    if not isinstance(windcode,str) or not re.fullmatch(r'\d{6}\.(?:SH|SZ)',windcode):
        raise WindIntervalConflict('Use an explicit six-digit SH/SZ index code, not a name')
    sessions=pd.DatetimeIndex(confirmed_sessions)
    if sessions.empty or not isinstance(tail_sessions,int) or isinstance(tail_sessions,bool) or tail_sessions<1:
        raise WindIntervalConflict('Missing confirmed sessions or invalid short-window length')
    if len(sessions)<=tail_sessions and reference is None:
        raise WindIntervalConflict('Long and short windows coincide; independent reference required')
    short_start=sessions[-tail_sessions:][0].date().isoformat()
    try:
        long_frame=parse_index_kline(fetch(windcode,str(pd.Timestamp(start).date()),str(pd.Timestamp(end).date())))
        short_frame=parse_index_kline(fetch(windcode,short_start,str(pd.Timestamp(end).date())))
        long_frame.attrs['_requested_windcode']=windcode
        short_frame.attrs['_requested_windcode']=windcode
        long_id=long_frame.attrs.get('_response_request_id')
        if long_id and long_id==short_frame.attrs.get('_response_request_id') and len(sessions)>tail_sessions:
            raise WindIntervalConflict('Distinct Wind ranges replayed the same response receipt')
    except WindIntervalConflict:raise
    except Exception as exc:raise WindIntervalConflict('Wind transport failed; no partial batch accepted') from exc
    return validate_long_short(long_frame,short_frame,start=start,end=end,confirmed_sessions=sessions,tail_sessions=tail_sessions,reference=reference)

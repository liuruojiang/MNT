"""Compare native provider fields without modifying either provider's prices."""
from datetime import datetime, timezone
import copy
from zoneinfo import ZoneInfo
import math

NY = ZoneInfo("America/New_York")


def finite(value, positive=False):
    if isinstance(value, bool):
        raise ValueError("Boolean numeric field")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("Invalid numeric field")
    return result


def tiingo_rows(payload, symbol, start, end, metadata):
    if not isinstance(metadata, dict) or metadata.get("ticker", "").upper() != symbol:
        raise ValueError("Tiingo metadata identity mismatch")
    if not metadata.get("startDate") or not metadata.get("endDate"):
        raise ValueError("Tiingo metadata coverage unavailable")
    for key in ("startDate", "endDate"):
        datetime.fromisoformat(metadata[key][:10])
    if metadata["startDate"][:10] > metadata["endDate"][:10]:
        raise ValueError("Inverted metadata coverage")
    if not isinstance(payload, list) or not payload:
        raise ValueError("Empty Tiingo prices")
    rows, previous = {}, ""
    for item in payload:
        day = datetime.fromisoformat(item["date"].replace("Z", "+00:00")).date().isoformat()
        if day <= previous:
            raise ValueError("Duplicate or unsorted Tiingo dates")
        previous = day
        if not start <= day <= end:
            continue
        row = {field: finite(item[field], True) for field in
               ("open", "high", "low", "close", "adjOpen", "adjHigh", "adjLow", "adjClose", "splitFactor")}
        for field in ("volume", "adjVolume", "divCash"):
            row[field] = finite(item[field])
            if row[field] < 0:
                raise ValueError("Negative Tiingo volume/distribution")
        validate_bar(row)
        factor = row["adjClose"] / row["close"]
        for raw, adj in (("open", "adjOpen"), ("high", "adjHigh"), ("low", "adjLow")):
            if abs(row[adj] / row[raw] / factor - 1) > 0.0001:
                raise ValueError("Tiingo adjusted OHLC factor mismatch")
        rows[day] = row
    if not rows:
        raise ValueError("No Tiingo prices in requested window")
    return rows


def validate_bar(row):
    # Tiny representation tolerance, not permission to repair invalid bars.
    eps = max(row["high"], row["close"]) * 1e-6
    if row["low"] > min(row["open"], row["close"]) + eps or row["high"] < max(row["open"], row["close"]) - eps:
        raise ValueError("Invalid OHLC ordering")
    if row["low"] > row["high"] or row["volume"] < 0:
        raise ValueError("Invalid price range/volume")


def yahoo_rows(payload, symbol, start, end):
    chart = payload["chart"]
    if chart.get("error"):
        raise ValueError("Yahoo chart error")
    result = chart["result"][0]
    meta = result["meta"]
    if meta.get("symbol", "").upper() != symbol or meta.get("exchangeTimezoneName") != "America/New_York":
        raise ValueError("Yahoo symbol/timezone mismatch")
    if meta.get("currency") != "USD":
        raise ValueError("Unexpected currency")
    timestamps = result["timestamp"]
    if timestamps != sorted(set(timestamps)):
        raise ValueError("Duplicate/unsorted Yahoo timestamps")
    quotes = result["indicators"]["quote"][0]
    adjusted = result["indicators"]["adjclose"][0]["adjclose"]
    if any(len(quotes[field]) != len(timestamps) for field in ("open", "high", "low", "close", "volume")) or len(adjusted) != len(timestamps):
        raise ValueError("Yahoo field lengths disagree")
    rows = {}
    for i, ts in enumerate(timestamps):
        day = datetime.fromtimestamp(ts, timezone.utc).astimezone(NY).date().isoformat()
        if not start <= day <= end:
            continue
        row = {field: finite(quotes[field][i], field != "volume") for field in ("open", "high", "low", "close", "volume")}
        row.update(adjClose=finite(adjusted[i], True), divCash=0.0, splitFactor=1.0, capitalGain=0.0)
        row["adjOpen"] = row["open"] * row["adjClose"] / row["close"]
        validate_bar(row)
        if day in rows:
            raise ValueError("Duplicate Yahoo session")
        rows[day] = row
    # Capital gains remain separate: blindly adding categories can double count.
    for category in ("dividends", "splits", "capitalGains"):
        event_days = set()
        for item in result.get("events", {}).get(category, {}).values():
            day = datetime.fromtimestamp(item["date"], timezone.utc).astimezone(NY).date().isoformat()
            if not start <= day <= end:
                continue
            if day not in rows or day in event_days:
                raise ValueError("Orphan or duplicate Yahoo corporate action")
            event_days.add(day)
            if category == "splits":
                rows[day]["splitFactor"] = finite(item["numerator"], True) / finite(item["denominator"], True)
            else:
                rows[day]["divCash" if category == "dividends" else "capitalGain"] = finite(item["amount"])
    if not rows:
        raise ValueError("Empty Yahoo window")
    return rows


def split_comparison_basis(rows):
    """Tiingo native -> Yahoo's latest-share split-only basis, on copies.

    Price/cash divide by subsequent splits, share volume multiplies by them.
    The exdate's split is not applied again to that date's quote/distribution.
    Raw archives and vendor total-return adjusted prices remain untouched.
    """
    result = copy.deepcopy(rows)
    future = 1.0
    for day in sorted(rows, reverse=True):
        for field in ("open", "high", "low", "close", "divCash"):
            result[day][field] /= future
        result[day]["volume"] *= future
        future *= rows[day]["splitFactor"]
    return result


def compare(symbol, t, y, metadata, calendar, start, end, limits):
    t = split_comparison_basis(t)
    common = sorted(t.keys() & y.keys())
    expected = {d for d in calendar if max(start, metadata["startDate"][:10]) <= d <= end}
    gaps = {"tiingo": sorted(expected - t.keys()), "yahoo": sorted(expected - y.keys()),
            "unexpected_tiingo": sorted(t.keys() - set(calendar)), "unexpected_yahoo": sorted(y.keys() - set(calendar))}
    issues, details = [], []
    if not common or any(gaps.values()) or max(t) != end or max(y) != end:
        issues.append("COVERAGE_OR_FRESHNESS")
    previous_t = dict(zip(sorted(t)[1:], sorted(t)[:-1]))
    previous_y = dict(zip(sorted(y)[1:], sorted(y)[:-1]))
    counts = {name: 0 for name in ("raw_price", "cash", "split", "volume", "adjusted_return", "action_basis", "unexplained_adjustment", "capital_gains_review")}
    maxima = {name: 0.0 for name in ("raw_open", "raw_close", "volume", "adjusted_return")}
    for day in common:
        a, b = t[day], y[day]
        flags = []
        for field in ("open", "close"):
            delta = a[field] / b[field] - 1
            maxima["raw_" + field] = max(maxima["raw_" + field], abs(delta))
            if abs(delta) > limits["raw_price_relative"]:
                flags.append("raw_" + field)
        if any(f.startswith("raw_") for f in flags):
            counts["raw_price"] += 1
        volume_delta = abs(a["volume"] - b["volume"]) / max(1, a["volume"], b["volume"])
        maxima["volume"] = max(maxima["volume"], volume_delta)
        if volume_delta > limits["volume_relative"]:
            flags.append("volume")
            counts["volume"] += 1
        cash_diff = abs(a["divCash"] - b["divCash"]) > max(limits["cash_absolute"], limits["cash_relative"] * max(a["divCash"], b["divCash"]))
        # Tiingo sometimes represents an exact 3:1 event as 3.000003.
        split_diff = abs(a["splitFactor"] / b["splitFactor"] - 1) > 1e-5
        capital = b["capitalGain"] != 0
        for flag, test in (("cash", cash_diff), ("split", split_diff), ("capital_gains_review", capital)):
            if test:
                flags.append(flag)
                counts[flag] += 1
        prev = previous_t.get(day)
        returns = None
        if prev and previous_y.get(day) == prev:
            rt = a["adjClose"] / t[prev]["adjClose"] - 1
            ry = b["adjClose"] / y[prev]["adjClose"] - 1
            maxima["adjusted_return"] = max(maxima["adjusted_return"], abs(rt - ry))
            if abs(rt - ry) > limits["adjusted_return_absolute"]:
                flags.append("adjusted_return")
                counts["adjusted_return"] += 1
                returns = {"tiingo": rt, "yahoo": ry}
            action = any((a["divCash"], b["divCash"], a["splitFactor"] != 1, b["splitFactor"] != 1, capital))
            # A constant historical normalization is ignored; unexplained factor
            # changes are examined even if raw price differences hide return drift.
            tf = (a["adjClose"] / a["close"]) / (t[prev]["adjClose"] / t[prev]["close"])
            yf = (b["adjClose"] / b["close"]) / (y[prev]["adjClose"] / y[prev]["close"])
            no_cash = not any((a["divCash"], b["divCash"], capital))
            if no_cash and (abs(tf - 1) > limits["adjusted_return_absolute"] or abs(yf - 1) > limits["adjusted_return_absolute"]):
                flags.append("unexplained_adjustment")
                counts["unexplained_adjustment"] += 1
            elif action and not cash_diff and not split_diff and not capital and a["splitFactor"] == 1:
                def explained(row, old, actual):
                    cash_tr = (row["close"] + row["divCash"]) / old["close"] - 1
                    denom = old["close"] - row["divCash"]
                    yahoo_basis = row["close"] / denom - 1 if denom > 0 else math.inf
                    return min(abs(actual - cash_tr), abs(actual - yahoo_basis)) <= 0.00002
                if explained(a, t[prev], rt) and explained(b, y[prev], ry):
                    counts["action_basis"] += 1
                    if returns:
                        flags.append("action_basis")
                else:
                    flags.append("unexplained_adjustment")
                    counts["unexplained_adjustment"] += 1
        if flags:
            details.append({"date": day, "flags": flags, "tiingo_cash": a["divCash"], "yahoo_cash": b["divCash"],
                            "yahoo_capital_gain": b["capitalGain"], "tiingo_split": a["splitFactor"], "yahoo_split": b["splitFactor"], "returns": returns})
            details[-1]["comparison_values"] = {"tiingo": {k: a[k] for k in ("open", "close", "volume")},
                                                 "yahoo": {k: b[k] for k in ("open", "close", "volume")}}
    if counts["cash"] or counts["split"] or counts["capital_gains_review"]:
        issues.append("CORPORATE_ACTION_CONFLICT")
    if counts["unexplained_adjustment"]:
        issues.append("UNEXPLAINED_FACTOR_CHANGE")
    if counts["raw_price"]:
        issues.append("RAW_PRICE_REVIEW")
    if counts["volume"]:
        issues.append("VOLUME_REVIEW")
    if counts["adjusted_return"]:
        issues.append("ADJUSTED_RETURN_DIFFERENCE")
    status = "BLOCKED" if any(issue in issues for issue in ("COVERAGE_OR_FRESHNESS", "CORPORATE_ACTION_CONFLICT", "UNEXPLAINED_FACTOR_CHANGE")) else ("REVIEW" if issues or counts["adjusted_return"] else "OBSERVED_MATCH")
    return {"symbol": symbol, "status": status, "issues": issues, "common_rows": len(common),
            "first_common": common[0] if common else None, "last_common": common[-1] if common else None,
            "metadata_start": metadata["startDate"], "tiingo_rows": len(t), "yahoo_rows": len(y),
            "gaps": gaps, "counts": counts, "max_abs": maxima, "details": details,
            "comparison_basis": "Latest-share split-adjusted OHLC/cash/share volume; native fields retained in raw archives; vendor adjClose unchanged",
            "production_approved": False}

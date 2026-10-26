"""Shared Tiingo/Yahoo read-only auditor for V1.6 and V8.0.

Exit 2: review required; the first phase has excluded required inputs and is
never a production acceptance gate. Every completed audit prints its report.
No strategy modules are imported, caches read, files repaired, or feeds switched.
"""
import argparse
from datetime import datetime, timedelta, timezone
import html
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from uuid import uuid4

from source_audit.compare import NY, compare, tiingo_rows, yahoo_rows
from source_audit.transport import decrypt_dpapi, fetch, sha256

REPO = Path(__file__).resolve().parents[1]
PROFILE = Path(__file__).parent / "source_audit" / "projects.json"
VERSION = "1.0.0"


def write_json(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def latest_eligible_day(now=None):
    local = (now or datetime.now(timezone.utc)).astimezone(NY)
    # Conservative availability boundary after Tiingo's documented revision
    # window; the actual session date is discovered from SPY, not weekdays.
    return (local.date() if local.hour >= 21 else local.date() - timedelta(days=1)).isoformat()


def source_scope(profile, workspace):
    evidence = {}
    for name, cfg in profile["projects"].items():
        path = workspace / cfg["directory"] / cfg["entrypoint"]
        digest = sha256(path.read_bytes().replace(b"\r\n", b"\n")) if path.exists() else None
        evidence[name] = {"path": str(path), "sha256_lf": digest, "matches_profile": digest == cfg["entrypoint_lf_sha256"]}
    return evidence


def render(report, output):
    labels = {"BLOCKED": "暂不接受", "REVIEW": "待核对", "OBSERVED_MATCH": "观测匹配"}
    issue_labels = {"COVERAGE_OR_FRESHNESS": "日期覆盖或新鲜度", "CORPORATE_ACTION_CONFLICT": "分配／拆股记录冲突",
                    "UNEXPLAINED_FACTOR_CHANGE": "无法解释的复权变化", "RAW_PRICE_REVIEW": "同口径价格差异",
                    "VOLUME_REVIEW": "成交量差异", "ADJUSTED_RETURN_DIFFERENCE": "复权收益差异",
                    "UNAVAILABLE_OR_INVALID_RESPONSE": "接口不可用或数据不合格"}
    rows = []
    for item in report["assets"]:
        counts = item.get("counts", {})
        gaps = item.get("gaps", {})
        rows.append("<tr>" + "".join("<td>" + html.escape(str(value)) + "</td>" for value in
            (item["symbol"], labels[item["status"]], "/".join(item["projects"]), item.get("common_rows", 0),
             counts.get("cash", "—"), counts.get("raw_price", "—"), counts.get("volume", "—"),
             sum(len(g) for g in gaps.values()), "、".join(issue_labels.get(i, i) for i in item.get("issues", [])) or item.get("error_type", "—"))) + "</tr>")
    text = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>美股双源只读核验</title>
<style>body{font:16px/1.6 system-ui;margin:32px;color:#182a38;background:#f5f8fa}table{border-collapse:collapse;background:white;width:100%;font-size:14px}td,th{padding:9px;border:1px solid #ccd6dd;text-align:left}aside{padding:18px;background:#fff1d4}a{color:#146b9b}pre{white-space:pre-wrap}h1{font-size:26px}</style>
<h1>V1.6 / V8.0 · Tiingo 与 Yahoo 双源核验</h1>
<aside>只读诊断：未改策略、参数、缓存或生产源；未部署 Poe。状态 BLOCKED 会阻断本工具的 ETF 接受结论，当前并未接入正式策略阻断链。价格或成交量差异待裁定，不自动认定哪家错误。</aside>
"""
    text += "<p>数据截止：" + html.escape(report.get("cutoff") or "未确定") + "；运行模式：" + report["mode"] + "；状态：" + report["status"] + "</p>"
    if report.get("provider_stops"):
        text += "<p>接口／权限／额度停止记录：</p><pre>" + html.escape(json.dumps(report["provider_stops"], ensure_ascii=False, indent=2)) + "</pre>"
    text += "<p>历史起点：2003-01-01；新上市标的按 Tiingo 元数据起点检查。SPY 为两源共同缺日检查的参考日历，不能排除两源共同漏掉 SPY 交易日。比较 OHLC、现金分配和股数成交量时，先将 Tiingo 当日原始字段转换为与 Yahoo 相同的拆股后份额口径；不改变归档原始字段或任一家总回报复权价。复权差异另拆分为分配、拆股及算法口径；资本利得单列，避免重复累计。</p>"
    text += "<table><thead><tr><th>ETF</th><th>状态</th><th>项目</th><th>共同行数</th><th>现金冲突日</th><th>开收价差异日</th><th>成交量差异日</th><th>日历缺口</th><th>待核对项</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    actions = []
    for item in report["assets"]:
        for detail in item.get("details", []):
            if any(f in detail["flags"] for f in ("cash", "split", "capital_gains_review")):
                actions.append((detail["date"], item["symbol"], "/".join(item["projects"]), detail["tiingo_cash"], detail["yahoo_cash"], detail["tiingo_split"], detail["yahoo_split"]))
    text += "<h2>公司行动冲突清单（尚待独立裁定）</h2><p>按最近日期排列。以下差异会阻断本工具的数据接受结论，不能直接认定哪家错误，也未计算策略影响。单位为同一拆股后份额的美元现金分配。</p><table><tr><th>日期</th><th>ETF</th><th>项目</th><th>Tiingo 现金</th><th>Yahoo 现金</th><th>Tiingo 拆股</th><th>Yahoo 拆股</th></tr>"
    for action in sorted(actions, reverse=True):
        text += "<tr>" + "".join("<td>" + html.escape(str(v)) + "</td>" for v in action) + "</tr>"
    text += "</table>"
    text += "<h2>覆盖与边界</h2><p>两套策略的 ETF 数据已逐项核验；完整策略仍有未覆盖输入。V1.6 的 BTC，以及 V8.0 的 BTC、A 股和宏观指标均需各自核验。公司行动冲突及起始日差异仍需独立来源确认；这里没有重跑策略。</p><details><summary>查看各项目清单、正式脚本哈希和范围记录</summary><pre>" + html.escape(json.dumps(report["projects"], ensure_ascii=False, indent=2)) + "</pre></details>"
    text += "<p>KMLM：这里对比上游原始响应，未调用策略已有修复。若 Yahoo 仍漏配，本报告继续保留冲突；不能据此推断正式策略再次出错。发行人 2022 年分配表是该事件的独立裁定证据。</p><p>阈值仅用于本次数据审计，不改变策略参数；完整逐日差异及原始响应哈希见 <a href='report.json'>report.json</a> 与 <a href='snapshot.json'>snapshot.json</a>。没有计算新的策略信号或回测收益。</p>"
    text += "<p><a href='https://kraneshares.com/resources/2022_kraneshares_cap_gain.pdf'>KMLM 发行人分配表</a> · <a href='https://www.tiingo.com/documentation/end-of-day'>Tiingo 字段说明</a></p></html>"
    with (output / "report.html").open("x", encoding="utf-8") as handle:
        handle.write(text)


def build_report(profile, snapshot, output, scope, calendar_override=None):
    receipts = snapshot["receipts"]
    def load(name):
        receipt = receipts.get(name, {})
        if receipt.get("status") != 200 or receipt.get("error_type"):
            raise ValueError("Missing or failed response")
        path = output / "raw" / (name + ".json")
        body = path.read_bytes()
        if sha256(body) != receipt.get("sha256"):
            raise ValueError("Raw response hash mismatch")
        return json.loads(body)
    start, end = profile["history_start"], snapshot["cutoff"]
    assets = []
    try:
        spy = yahoo_rows(load("yahoo_SPY"), "SPY", start, end)
        calendar = sorted(calendar_override) if calendar_override is not None else sorted(spy)
        if not calendar or calendar[-1] != end:
            raise ValueError("Reference calendar not fresh")
    except Exception as exc:
        calendar = []
    symbols = sorted(set().union(*(p["symbols"] for p in profile["projects"].values())) - {"BTC-USD"})
    for symbol in symbols:
        try:
            if not calendar:
                raise ValueError("Reference calendar unavailable")
            metadata = load("tiingo_" + symbol + "_metadata")
            t = tiingo_rows(load("tiingo_" + symbol), symbol, start, end, metadata)
            y = yahoo_rows(load("yahoo_" + symbol), symbol, start, end)
            item = compare(symbol, t, y, metadata, calendar, start, end, profile["audit_thresholds_not_strategy_parameters"])
        except Exception as exc:
            item = {"symbol": symbol, "status": "BLOCKED", "error_type": type(exc).__name__, "issues": ["UNAVAILABLE_OR_INVALID_RESPONSE"], "production_approved": False}
        item["projects"] = [name for name, cfg in profile["projects"].items() if symbol in cfg["symbols"]]
        assets.append(item)
    projects = {}
    for name, cfg in profile["projects"].items():
        relevant = [item for item in assets if name in item["projects"]]
        projects[name] = {"status": "REVIEW_REQUIRED" if scope[name].get("matches_profile") and scope[name].get("unchanged_during_audit") else "BLOCKED_SOURCE_SCOPE",
                          "ETF_count": len(relevant), "ETF_blocked": [i["symbol"] for i in relevant if i["status"] == "BLOCKED"],
                          "ETF_review": [i["symbol"] for i in relevant if i["status"] == "REVIEW"],
                          "ETF_observed_match": [i["symbol"] for i in relevant if i["status"] == "OBSERVED_MATCH"],
                          "excluded": cfg["excluded"], "source_scope": scope[name], "strategy_replayed": False,
                          "production_approved": False}
    report = {"version": VERSION, "mode": snapshot["mode"], "status": "REVIEW_REQUIRED", "cutoff": end,
              "created_at_utc": datetime.now(timezone.utc).isoformat(), "history_start": start,
              "provider_stops": snapshot.get("provider_stops", {}),
              "projects": projects, "assets": assets, "production_approved": False,
              "scope_note": "No promotion snapshot is emitted. BTC, China and macro inputs are not ETF-validated; no strategy replay performed."}
    return report


def run(args):
    profile_bytes = PROFILE.read_bytes()
    profile = json.loads(profile_bytes)
    scope_before = source_scope(profile, args.workspace)
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    output.mkdir()
    write_json(output / "projects.json", profile)
    symbols = sorted(set().union(*(p["symbols"] for p in profile["projects"].values())) - {"BTC-USD"})
    if args.offline_snapshot:
        # Reprocessing is explicit and retains original retrieval dates. A prior
        # successful response is never an automatic fallback for a failed live run.
        import shutil
        prior = args.offline_snapshot.resolve()
        snapshot = json.loads((prior / "snapshot.json").read_text(encoding="utf-8"))
        if snapshot["profile_sha256"] != sha256(profile_bytes):
            raise ValueError("Offline project profile differs")
        if args.cutoff != "auto" and args.cutoff != snapshot["cutoff"]:
            raise ValueError("Offline cutoff differs")
        shutil.copytree(prior / "raw", output / "raw")
        snapshot = {**snapshot, "mode": "OFFLINE_REPLAY", "original_snapshot": str(prior)}
    else:
        (output / "raw").mkdir()
        receipts, stopped = {}, {}
        eligible = latest_eligible_day()
        end = eligible if args.cutoff == "auto" else args.cutoff
        if end > eligible:
            raise ValueError("Requested cutoff exceeds confirmed availability boundary")
        start = profile["history_start"]
        def request(name, provider, url, token=None):
            if provider in stopped:
                receipts[name] = {"error_type": "ProviderStopped", "reason": stopped[provider]}
                return None
            receipt, value = fetch(url, output / "raw" / (name + ".json"), token)
            receipts[name] = receipt
            # Stop on a transport/auth/entitlement/quota failure, do not hammer
            # the same account for every symbol, and do not read an older cache.
            if value is None:
                stopped[provider] = {"status": receipt.get("status"), "error_type": receipt.get("error_type", "ProviderHTTPFailure")}
            return value
        def yahoo_url(symbol, until):
            return "https://query1.finance.yahoo.com/v8/finance/chart/" + symbol + "?" + urlencode({
                "period1": int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp()),
                "period2": int((datetime.fromisoformat(until).replace(tzinfo=timezone.utc) + timedelta(days=1)).timestamp()),
                "interval": "1d", "includeAdjustedClose": "true", "events": "div,splits,capitalGains"})
        spy_payload = request("yahoo_SPY", "yahoo", yahoo_url("SPY", eligible))
        if spy_payload:
            try:
                latest = max(yahoo_rows(spy_payload, "SPY", start, eligible))
                if (datetime.fromisoformat(eligible) - datetime.fromisoformat(latest)).days > 7:
                    raise ValueError("Reference calendar implausibly stale")
            except Exception:
                stopped["yahoo"] = {"error_type": "InvalidReferenceCalendar"}
            else:
                if args.cutoff != "auto" and end != latest:
                    raise ValueError("Live cutoff must equal latest confirmed SPY session; use an as-of archived snapshot for historical replay")
                end = latest
        try:
            token = decrypt_dpapi(args.tiingo_credential)
        except Exception as exc:
            token = None
            stopped["tiingo"] = {"error_type": type(exc).__name__, "reason": "Credential unavailable"}
        for symbol in symbols:
            base = "https://api.tiingo.com/tiingo/daily/" + symbol
            request("tiingo_" + symbol + "_metadata", "tiingo", base, token)
            request("tiingo_" + symbol, "tiingo", base + "/prices?" + urlencode({"startDate": start, "endDate": end, "resampleFreq": "daily"}), token)
            if symbol != "SPY":
                request("yahoo_" + symbol, "yahoo", yahoo_url(symbol, end))
            print(symbol + ": read-only collection recorded", flush=True)
        token = None
        snapshot = {"mode": "LIVE_FRESH", "cutoff": end, "profile_sha256": sha256(profile_bytes),
                    "started_scope": scope_before, "receipts": receipts, "provider_stops": stopped,
                    "transport_policy": "One attempt per request; stop provider on failure; no production caches or stale fallback"}
    write_json(output / "snapshot.json", snapshot)
    scope_after = source_scope(profile, args.workspace)
    scope = {name: {**value, "unchanged_during_audit": value == scope_before[name]} for name, value in scope_after.items()}
    report = build_report(profile, snapshot, output, scope)
    report["auditor_sources"] = {str(p.relative_to(REPO)): sha256(p.read_bytes()) for p in
                                 [Path(__file__), PROFILE, *(PROFILE.parent.glob("*.py"))]}
    write_json(output / "report.json", report)
    render(report, output)
    print(json.dumps({"report": str(output / "report.html"), "cutoff": report["cutoff"], "ETF_count": len(report["assets"]),
                      "statuses": {status: sum(i["status"] == status for i in report["assets"]) for status in ("BLOCKED", "REVIEW", "OBSERVED_MATCH")},
                      "provider_stops": snapshot.get("provider_stops", {}), "production_changed": False}, ensure_ascii=False), flush=True)
    # Excluded required dependencies mean project-wide acceptance is incomplete.
    return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=REPO.parent, help="Parent of the two real strategy checkouts")
    parser.add_argument("--tiingo-credential", type=Path, help="Existing DPAPI file path; NEVER pass a token")
    parser.add_argument("--output", type=Path, default=REPO / "data" / "source_audit")
    parser.add_argument("--cutoff", default="auto", help="YYYY-MM-DD or auto (confirmed SPY session after NY 21:00)")
    parser.add_argument("--offline-snapshot", type=Path, help="Explicit archived run directory, with hash validation; not fresh data")
    args = parser.parse_args()
    if not args.offline_snapshot and args.tiingo_credential is None:
        parser.error("Live mode requires --tiingo-credential pointing to the existing encrypted file")
    if args.cutoff != "auto":
        try:
            if datetime.fromisoformat(args.cutoff).date().isoformat() != args.cutoff:
                raise ValueError()
        except ValueError:
            parser.error("Invalid date")
    try:
        return run(args)
    except Exception as exc:
        print(json.dumps({"audit_failed": type(exc).__name__, "production_changed": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

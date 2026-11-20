"""Run the actual Poe dispatcher locally with a capture/replay HTTP transport.

Run from the repository root. Give --store a private local directory outside
the repository. No request headers, credentials, URLs, or cookies are stored.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import parse_qsl, urlsplit
import uuid

import openpyxl
from PIL import Image
import requests

ROOT = Path(__file__).resolve().parents[3]
QUERIES = {
    "perf19": "表现 2025-11-20 至 2026-11-19",
    "perf18": "表现 2025-11-19 至 2026-11-18",
    "signal": "信号",
    "live_signal": "实时信号",
    "params": "参数",
    "live_params": "实时参数",
    "chart": "净值曲线 2025-11-20 至 2026-11-19",
    "history": "信号 2026-11-16 至 2026-11-19",
    "recent": "最近一年表现",
}


class Tape:
    def __init__(self, store, mode, replay_dirs=()):
        self.root = store / "http"
        self.root.mkdir(exist_ok=True, parents=True)
        self.mode = mode
        self.replay_dirs = tuple(replay_dirs)
        if self.replay_dirs and mode != "replay":
            raise ValueError("Additional archives require offline replay mode")
        self.original = requests.Session.request
        self.counts = Counter()
        self.missing = Counter()

    def request(self, session, method, url, **kwargs):
        parsed = urlsplit(requests.Request(method, url, params=kwargs.get("params")).prepare().url)
        query = dict(parse_qsl(parsed.query))
        if parsed.hostname in ("query1.finance.yahoo.com", "query2.finance.yahoo.com") and "period2" in query:
            # Full-history requests use wallclock + 30 days. Across this run the
            # upper bound stays in the future and the requested session set is identical.
            query["period2"] = datetime.fromtimestamp(int(query["period2"]), tz=timezone.utc).date().isoformat()
        if parsed.hostname is None or method.upper() != "GET" or any(
            key.lower() in ("token", "apikey", "api_key", "key", "crumb") for key in query
        ):
            raise ValueError("unsupported or credential-bearing verification request")
        key = hashlib.sha256(json.dumps([parsed.hostname, parsed.path, sorted(query.items())]).encode()).hexdigest()
        path = self.root / (key + ".gz")
        if not path.exists() and self.replay_dirs:
            path = next((folder / path.name for folder in self.replay_dirs if (folder / path.name).is_file()), path)
        if path.exists() and self.mode != "online":
            with gzip.open(path, "rb") as reader:
                metadata = json.loads(reader.readline())
                body = reader.read()
            self.counts["replay:" + parsed.hostname] += 1
            if "error" in metadata:
                raise getattr(requests.exceptions, metadata["error"], requests.ConnectionError)("recorded network failure")
            response = requests.Response()
            response.url = url
            response.status_code = metadata["status"]
            response.encoding = metadata.get("encoding")
            response._content = body
            response.headers["Content-Type"] = metadata["content_type"]
            return response
        if self.mode == "replay":
            self.missing[parsed.hostname + parsed.path] += 1
            raise requests.ConnectionError("HTTP input missing from this tape")
        if parsed.hostname == "api.tiingo.com" and "offline-replay" in kwargs.get("headers", {}).get("Authorization", ""):
            raise requests.ConnectionError("Authenticated replay input missing; no live request made")
        self.counts["online:" + parsed.hostname] += 1
        try:
            response = self.original(session, method, url, **kwargs)
        except requests.RequestException as exc:
            self._store(path, {"error": type(exc).__name__}, b"")
            raise
        self._store(path, {"status": response.status_code, "encoding": response.encoding,
                           "content_type": response.headers.get("Content-Type", "")}, response.content)
        return response

    def _store(self, path, metadata, body):
        temp = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        with gzip.open(temp, "wb", compresslevel=2) as writer:
            writer.write(json.dumps(metadata).encode() + b"\n")
            writer.write(body)
        os.replace(temp, path)


class Sink:
    def __init__(self, attachment_dir):
        self.text = io.StringIO()
        self.attachments = []
        self.attachment_dir = attachment_dir

    def write(self, value):
        self.text.write(str(value))

    def attach_file(self, *, contents, name, **kwargs):
        if Path(name).name != name:
            raise ValueError("Invalid attachment filename")
        self.attachment_dir.mkdir(parents=True, exist_ok=True)
        (self.attachment_dir / name).write_bytes(contents)
        info = {"name": name, "bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}
        if name.endswith(".xlsx"):
            book = openpyxl.load_workbook(io.BytesIO(contents), data_only=True, read_only=True)
            info["sheets"] = {s.title: s.max_row for s in book}
            for sheet in ("绩效概览", "标准窗口指标", "报告元数据", "数据与指标口径"):
                if sheet in book:
                    rows = list(book[sheet].values)
                    info[sheet] = rows if sheet != "标准窗口指标" else [row for row in rows if "1Y" in row or "1年" in row]
            book.close()
        if name.endswith(".png"):
            with Image.open(io.BytesIO(contents)) as image:
                info["size"] = image.size
                image.verify()
        self.attachments.append(info)

    @contextmanager
    def opened(self):
        yield self


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--case", choices=QUERIES, required=True)
    cli.add_argument("--mode", choices=("online", "extend", "replay"), required=True)
    cli.add_argument("--replay-dir", type=Path, action="append", default=[],
                     help="Additional read-only HTTP archives, searched in argument order")
    cli.add_argument("--store", type=Path, required=True)
    cli.add_argument("--report", type=Path, required=True)
    cli.add_argument("--no-key", action="store_true", help="exercise the credential-unavailable boundary")
    cli.add_argument("--cached-auth", action="store_true", help="do not reserve live quota, even in extend mode")
    cli.add_argument("--clock", help="fixed Beijing replay clock, ISO format")
    args = cli.parse_args()
    sys.path.insert(0, str(ROOT))
    path = ROOT / "mnt_bot V 8.0 plus.py"
    fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("v80_native_acceptance", path)
    bot = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bot
    spec.loader.exec_module(bot)
    tape = Tape(args.store, args.mode, args.replay_dir)
    requests.Session.request = lambda session, method, url, **kw: tape.request(session, method, url, **kw)
    # Standalone replay never decrypts a real token or debits live request quota.
    if args.no_key:
        from tools.source_audit import config
        os.environ.pop("TIINGO_API_TOKEN", None)
        config.DEFAULT_ROOT = args.store / "credentialless-test-environment"
        if config.DEFAULT_ROOT.exists():
            raise ValueError("The credentialless test environment must be absent")
    elif args.mode == "replay" or args.cached_auth:
        bot._tiingo_tail_credential = lambda: "offline-replay"
    if args.clock:
        clock = datetime.fromisoformat(args.clock)
        bot.beijing_now = lambda: clock
    # Preserve the existing local cache state through the whole acceptance batch.
    # Redirect only writes, so the original validated source-selection logic still runs.
    bot._save_cn_official_cache = lambda *a, **kw: None
    bot._save_v78_spy_volume_cache = lambda *a, **kw: None
    sink = Sink(args.store / "attachments" / args.report.stem)
    bot.poe.query.text = QUERIES[args.case]
    bot.poe.start_message = sink.opened
    started = bot.beijing_now().isoformat()
    before = time.monotonic()
    bot.CombinedStrategyV80().run()
    elapsed = round(time.monotonic() - before, 2)
    output = sink.text.getvalue()
    lines = output.splitlines()
    private = args.store / "messages"
    private.mkdir(parents=True, exist_ok=True)
    (private / (args.report.stem + ".txt")).write_text(output, encoding="utf-8")
    keywords = ("失败", "数据截至", "实际截止", "实际收益覆盖", "报告编号", "报告ID", "完整收盘", "共同确认", "停止", "过期",
                "历史", "补齐", "Tiingo", "不可用", "最近确认", "区间:", "当前数据")
    report = {"query": QUERIES[args.case], "case": args.case, "mode": args.mode, "no_key": args.no_key,
              "start_bj": started, "seconds": elapsed, "source_sha256": fingerprint, "http": dict(tape.counts),
              "missing_replay_inputs": dict(tape.missing), "message_chars": len(output),
              "headings": [line[:200] for line in lines if line.startswith("##")][:18],
              "messages": [line[:850] for line in lines if any(word in line for word in keywords)][:35],
              "output_tail": lines[-4:], "attachments": sink.attachments}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("case", "mode", "seconds", "headings", "missing_replay_inputs")},
                     ensure_ascii=False), flush=True)
    print("attachments", [item["name"] for item in sink.attachments], "last lines", lines[-3:])


if __name__ == "__main__":
    main()

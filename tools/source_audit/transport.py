"""Authorized HTTPS reads. Credentials never enter URLs, arguments or receipts."""
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def decrypt_dpapi(path):
    encrypted = bytes.fromhex(Path(path).read_text(encoding="ascii").strip())

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    buf = ctypes.create_string_buffer(encrypted)
    source = Blob(len(encrypted), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise RuntimeError("DPAPI credential unavailable for this Windows user")
    try:
        value = ctypes.string_at(target.pbData, target.cbData).decode("utf-16-le").strip()
        if not value:
            raise ValueError("Empty credential")
        return value
    finally:
        ctypes.memset(target.pbData, 0, target.cbData)
        ctypes.windll.kernel32.LocalFree(target.pbData)


def fetch(url, path, token=None):
    # Hosts are fixed by the caller; refuse to send authentication elsewhere.
    if token and not url.startswith("https://api.tiingo.com/tiingo/daily/"):
        raise ValueError("Credential destination rejected")
    receipt = {"url": url, "retrieved_at_utc": datetime.now(timezone.utc).isoformat()}
    headers = {"User-Agent": "Mozilla/5.0 ReadOnlySourceAudit/1.0"}
    if token:
        headers["Authorization"] = "Token " + token
    try:
        request = urllib.request.Request(url, headers=headers)
        class SameHostRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                if token and (urllib.parse.urlsplit(newurl).hostname != "api.tiingo.com" or urllib.parse.urlsplit(newurl).scheme != "https"):
                    raise ValueError("Authenticated redirect destination rejected")
                return super().redirect_request(req, fp, code, msg, hdrs, newurl)
        try:
            response = urllib.request.build_opener(SameHostRedirect()).open(request, timeout=25)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            body = response.read(20_000_001)
            if len(body) > 20_000_000:
                raise ValueError("Response size limit")
            if token:
                body = body.replace(token.encode(), b"[REDACTED]")
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive writes: a run never overwrites or reuses a previous response.
            with path.open("xb") as output:
                output.write(body)
            receipt.update(status=response.code, sha256=sha256(body), bytes=len(body))
            value = json.loads(body)
            if response.code != 200:
                return receipt, None
            return receipt, value
    except Exception as exc:
        # No exception text, body or headers: providers may echo sensitive input.
        receipt.update(error_type=type(exc).__name__)
        return receipt, None

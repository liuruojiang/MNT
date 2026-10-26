"""Immutable response archive, atomic catalog, quarantine and diagnostic snapshots."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
from contextlib import contextmanager


class DataNotAccepted(RuntimeError):
    pass


class ServiceAlreadyRunning(RuntimeError):
    pass


@contextmanager
def service_lock(root):
    path=Path(root)/'service.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    handle=path.open('a+b')
    if path.stat().st_size==0:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        if __import__('os').name=='nt':
            import msvcrt
            try: msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as exc: raise ServiceAlreadyRunning('Another shared collector owns this store') from exc
        else:
            import fcntl
            try: fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc: raise ServiceAlreadyRunning('Another shared collector owns this store') from exc
        yield
    finally:
        handle.close()  # OS lock is released even after a crashed collector.


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'catalog.sqlite', timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS objects(sha TEXT PRIMARY KEY, bytes INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS observations(provider TEXT, symbol TEXT, kind TEXT, cutoff TEXT,
                sha TEXT, receipt TEXT, imported_from TEXT, PRIMARY KEY(provider,symbol,kind,cutoff,sha));
            CREATE TABLE IF NOT EXISTS heads(provider TEXT, symbol TEXT, kind TEXT, cutoff TEXT, sha TEXT,
                receipt TEXT, PRIMARY KEY(provider,symbol,kind));
            CREATE TABLE IF NOT EXISTS gates(provider TEXT, symbol TEXT, status TEXT, reason TEXT,
                run_id TEXT, PRIMARY KEY(provider,symbol));
            CREATE TABLE IF NOT EXISTS snapshots(provider TEXT, symbol TEXT, cutoff TEXT, sha TEXT,
                run_id TEXT, PRIMARY KEY(provider,symbol));
            CREATE TABLE IF NOT EXISTS requests(provider TEXT, at TEXT, status INTEGER);
            CREATE TABLE IF NOT EXISTS known_issues(issue_id TEXT PRIMARY KEY, fingerprint TEXT,
                status TEXT, evidence TEXT, last_seen TEXT);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, started TEXT, finished TEXT,
                status TEXT, report_path TEXT);
        ''')
        self.db.commit()

    def close(self): self.db.close()

    def object_path(self, sha):
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('Invalid object digest')
        return self.root / 'objects' / sha[:2] / (sha + '.json')

    def put_object(self, body):
        digest = hashlib.sha256(body).hexdigest()
        target = self.object_path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open('xb') as handle: handle.write(body)
        except FileExistsError:
            if target.read_bytes() != body:
                raise DataNotAccepted('Archive object digest/content mismatch')
        self.db.execute('INSERT OR IGNORE INTO objects VALUES(?,?)', (digest, len(body)))
        self.db.commit()
        return digest

    def read_object(self, sha):
        body = self.object_path(sha).read_bytes()
        if hashlib.sha256(body).hexdigest() != sha:
            raise DataNotAccepted('Immutable archive object has been modified')
        return body

    def observe(self, provider, symbol, kind, cutoff, body, receipt, imported_from=None):
        sha = self.put_object(body)
        if receipt.get('status') != 200 or receipt.get('sha256') != sha:
            raise DataNotAccepted('Receipt does not attest a successful matching response')
        record = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?)',
                (provider, symbol, kind, cutoff, sha, record, str(imported_from) if imported_from else None))
            old = self.db.execute('SELECT cutoff,receipt FROM heads WHERE provider=? AND symbol=? AND kind=?', (provider,symbol,kind)).fetchone()
            # Explicit imports cannot roll a newer head backward in date or
            # retrieval time. Old observations remain available for reproduction.
            fresh = not old or (cutoff,receipt.get('retrieved_at_utc','')) >= (old[0],json.loads(old[1]).get('retrieved_at_utc',''))
            if fresh:
                self.db.execute('INSERT OR REPLACE INTO heads VALUES(?,?,?,?,?,?)', (provider,symbol,kind,cutoff,sha,record))
        return sha

    def head(self, provider, symbol, kind='prices'):
        row = self.db.execute('SELECT cutoff,sha,receipt FROM heads WHERE provider=? AND symbol=? AND kind=?', (provider,symbol,kind)).fetchone()
        return None if row is None else {'cutoff':row[0], 'sha256':row[1], 'receipt':json.loads(row[2]), 'payload':json.loads(self.read_object(row[1]))}

    def gate(self, provider, symbol, status, reasons, run_id):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO gates VALUES(?,?,?,?,?)', (provider,symbol,status,json.dumps(reasons,ensure_ascii=False),run_id))
            if status != 'QUALIFIED_FOR_RESEARCH':
                self.db.execute('DELETE FROM snapshots WHERE provider=? AND symbol=?', (provider,symbol))

    def quarantine_provider(self, provider, reason, run_id):
        with self.db:
            self.db.execute('UPDATE gates SET status=?,reason=?,run_id=? WHERE provider=?', ('BLOCKED',json.dumps([reason]),run_id,provider))
            self.db.execute('DELETE FROM snapshots WHERE provider=?', (provider,))

    def publish(self, provider, symbol, cutoff, records, metadata, run_id):
        gate = self.db.execute('SELECT status,run_id FROM gates WHERE provider=? AND symbol=?', (provider,symbol)).fetchone()
        if not gate or tuple(gate) != ('QUALIFIED_FOR_RESEARCH',run_id):
            raise DataNotAccepted('Only this run\'s qualified observations may form a snapshot')
        payload = {'provider':provider,'symbol':symbol,'cutoff':cutoff,'records':records,'metadata':metadata,
                   'purpose':'research_only','production_approved':False,'run_id':run_id}
        sha = self.put_object(json.dumps(payload,ensure_ascii=False,allow_nan=False).encode())
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?,?)', (provider,symbol,cutoff,sha,run_id))

    def accepted(self, provider, symbol, cutoff, *, purpose='research_only'):
        if purpose != 'research_only':
            raise DataNotAccepted('Production consumption is not authorized by this diagnostic service')
        row = self.db.execute('SELECT s.cutoff,s.sha,s.run_id,g.status,g.run_id FROM snapshots s JOIN gates g ON s.provider=g.provider AND s.symbol=g.symbol WHERE s.provider=? AND s.symbol=?', (provider,symbol)).fetchone()
        if not row or row[0] != cutoff or row[3] != 'QUALIFIED_FOR_RESEARCH' or row[2] != row[4]:
            raise DataNotAccepted('No fresh, qualified snapshot; no fallback to an older cache')
        return json.loads(self.read_object(row[1]))

    def reserve_request(self, provider, limit, now=None):
        stamp = (now or datetime.now(timezone.utc)).timestamp()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            count = self.db.execute('SELECT COUNT(*) FROM requests WHERE provider=? AND CAST(at AS REAL)>?', (provider,stamp-3600)).fetchone()[0]
            if count >= limit: raise DataNotAccepted('Local hourly request budget reached')
            self.db.execute('INSERT INTO requests VALUES(?,?,NULL)', (provider,str(stamp)))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def issue(self, issue_id, state, evidence, now=None):
        fingerprint = hashlib.sha256(json.dumps(evidence,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        old = self.db.execute('SELECT fingerprint,status FROM known_issues WHERE issue_id=?', (issue_id,)).fetchone()
        changed = old is None or old != (fingerprint,state)
        stamp = (now or datetime.now(timezone.utc)).isoformat()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO known_issues VALUES(?,?,?,?,?)',
                (issue_id,fingerprint,state,json.dumps(evidence,ensure_ascii=False),stamp))
        return changed

    def begin_run(self):
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8]
        with self.db:
            self.db.execute('INSERT INTO runs VALUES(?,?,NULL,NULL,NULL)', (run_id,datetime.now(timezone.utc).isoformat()))
            self.db.execute('UPDATE gates SET status=?,reason=?,run_id=?', ('VERIFYING',json.dumps(['New shared assessment in progress']),run_id))
            self.db.execute('DELETE FROM snapshots')
        return run_id

    def finish_run(self, run_id, status, report):
        with self.db:
            self.db.execute('UPDATE runs SET finished=?,status=?,report_path=? WHERE id=?', (datetime.now(timezone.utc).isoformat(),status,str(report),run_id))

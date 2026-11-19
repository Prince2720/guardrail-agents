"""Append-only, tamper-evident audit log (SQLite).
 - UPDATE/DELETE on `events` are rejected by triggers (append-only)
 - every row stores hash = sha256(prev_hash | row), forming a chain; verify_chain() detects edits, deletions and reordering
 - `released` is a separate, mutable table (admin decisions about quarantined chunks)"""
import hashlib, json, os, sqlite3, threading, time, uuid

_lock = threading.RLock()
_conns: dict = {}

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, request_id TEXT, event TEXT NOT NULL,
  user_id TEXT, data TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TABLE IF NOT EXISTS released(hash TEXT PRIMARY KEY, released_by TEXT, ts REAL);
"""


def _db() -> sqlite3.Connection:
    path = os.getenv("AUDIT_DB", "audit.db")
    with _lock:
        if path not in _conns:
            c = sqlite3.connect(path, check_same_thread=False)
            c.executescript(SCHEMA)
            _conns[path] = c
        return _conns[path]


def _hash(prev, ts, rid, event, uid, data_json) -> str:
    return hashlib.sha256(f"{prev}|{ts!r}|{rid}|{event}|{uid}|{data_json}".encode()).hexdigest()


def record(event: str, **data) -> str:
    rid = data.pop("request_id", None) or str(uuid.uuid4())
    uid = data.get("user_id")
    data_json = json.dumps(data, sort_keys=True, default=str)
    with _lock:
        c = _db()
        row = c.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
        prev = row[0] if row else "GENESIS"
        ts = time.time()
        c.execute("INSERT INTO events(ts, request_id, event, user_id, data, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
                  (ts, rid, event, uid, data_json, prev, _hash(prev, ts, rid, event, uid, data_json)))
        c.commit()
    return rid


def all_events(limit: int | None = None, event: str | None = None) -> list[dict]:
    """Newest last. With a limit, returns the most recent `limit` events."""
    q, args = "SELECT id, ts, request_id, event, user_id, data FROM events", []
    if event:
        q += " WHERE event = ?"; args.append(event)
    q += " ORDER BY id DESC" + (f" LIMIT {int(limit)}" if limit else "")
    with _lock:
        rows = _db().execute(q, args).fetchall()
    return [{"id": r[0], "ts": r[1], "request_id": r[2], "event": r[3], "user_id": r[4], **json.loads(r[5])}
            for r in reversed(rows)]


def verify_chain() -> dict:
    with _lock:
        rows = _db().execute("SELECT id, ts, request_id, event, user_id, data, prev_hash, hash FROM events ORDER BY id").fetchall()
    prev = "GENESIS"
    for r in rows:
        if r[6] != prev or _hash(prev, r[1], r[2], r[3], r[4], r[5]) != r[7]:
            return {"ok": False, "events": len(rows), "first_bad_id": r[0]}
        prev = r[7]
    return {"ok": True, "events": len(rows), "first_bad_id": None}


# ---- quarantine review decisions (mutable by design; every change is also logged as an event)
def release(h: str, by: str) -> None:
    with _lock:
        c = _db()
        c.execute("INSERT OR REPLACE INTO released(hash, released_by, ts) VALUES (?,?,?)", (h, by, time.time()))
        c.commit()
    record("quarantine_released", hash=h, released_by=by)


def is_released(h: str) -> bool:
    with _lock:
        return _db().execute("SELECT 1 FROM released WHERE hash = ?", (h,)).fetchone() is not None

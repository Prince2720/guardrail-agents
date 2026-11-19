"""Abuse protection for the public demo: per-visitor rate limits and a global daily budget.
In-memory (fine for one instance); everything is configurable by environment variable."""
import os, threading, time
from collections import defaultdict, deque
from datetime import date

_lock = threading.Lock()
_hits: dict = defaultdict(deque)                 # ip -> request timestamps (last 24 h)
_day = {"date": None, "requests": 0, "tokens": 0}


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return int(default)


def reset():
    with _lock:
        _hits.clear()
        _day.update(date=None, requests=0, tokens=0)


def client_ip(request) -> str:
    if os.getenv("TRUST_PROXY", "false").strip().lower() in ("1", "true", "yes"):
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check(ip: str, cost: int = 1):
    """Returns (ok, reason, retry_after_seconds) and, if ok, charges `cost` requests."""
    per_min, per_day = _int("DEMO_RATE_PER_MIN", 6), _int("DEMO_RATE_PER_DAY", 60)
    day_reqs, day_toks = _int("DEMO_DAILY_REQUESTS", 400), _int("DEMO_DAILY_TOKENS", 120000)
    now, today = time.time(), date.today().isoformat()
    with _lock:
        if _day["date"] != today:
            _day.update(date=today, requests=0, tokens=0)
        if _day["requests"] + cost > day_reqs or _day["tokens"] >= day_toks:
            return False, "The daily demo budget is used up. Please try again tomorrow.", 3600
        q = _hits[ip]
        while q and now - q[0] > 86400:
            q.popleft()
        recent = [t for t in q if now - t < 60]
        if len(recent) + cost > per_min:
            return False, "Too many requests. Please wait a moment and try again.", max(1, int(60 - (now - recent[0])) + 1)
        if len(q) + cost > per_day:
            return False, "Daily limit for your connection reached. Please come back tomorrow.", 3600
        for _ in range(cost):
            q.append(now)
        _day["requests"] += cost
        if len(_hits) > 5000:                                   # keep memory bounded
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > 86400]:
                _hits.pop(k, None)
        return True, "", 0


def add_tokens(n: int):
    today = date.today().isoformat()
    with _lock:
        if _day["date"] != today:                 # roll the day here too, so charges are never lost at midnight
            _day.update(date=today, requests=0, tokens=0)
        _day["tokens"] += max(0, int(n))


def status() -> dict:
    with _lock:
        return {"requests_today": _day["requests"], "tokens_today": _day["tokens"],
                "daily_requests": _int("DEMO_DAILY_REQUESTS", 400), "daily_tokens": _int("DEMO_DAILY_TOKENS", 120000)}

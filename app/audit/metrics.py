"""Aggregates for the dashboard. Counts only: no message content leaves this module."""
import os
from collections import Counter
from app import approvals
from app.audit.log import all_events, verify_chain, is_released


def compute(limit: int = 5000) -> dict:
    reqs = all_events(limit=limit, event="request")
    quar = all_events(limit=limit, event="quarantine")
    blocked = [r for r in reqs if r.get("outcome") == "blocked"]
    lat = sorted(r.get("latency_ms", 0) for r in reqs)
    by_layer = Counter(r.get("layer") or "other" for r in blocked)
    reasons = Counter(f"{r.get('layer')}: {r.get('reason')}" for r in blocked)
    items = approvals.list_items()
    return {
        "firewall": {"enabled": os.getenv("FIREWALL_ENABLED", "true"), "layers": os.getenv("FIREWALL_LAYERS", "all")},
        "total": len(reqs),
        "firewall_off_requests": sum(r.get("fw") == "off" for r in reqs),
        "answered": sum(r.get("outcome") == "answered" for r in reqs),
        "blocked": len(blocked),
        "approval_pending": sum(r.get("outcome") == "approval_pending" for r in reqs),
        "blocked_by_layer": {k: by_layer.get(k, 0) for k in ("ingress", "tools", "context", "egress")},
        "top_reasons": [{"reason": k, "count": v} for k, v in reasons.most_common(6)],
        "redactions": {"input": sum(r.get("redacted_in", 0) for r in reqs), "output": sum(r.get("redacted_out", 0) for r in reqs)},
        "quarantined_chunks": len(quar),
        "approvals": {s: sum(i["status"] == s for i in items) for s in ("pending", "approved", "denied")},
        "latency_ms": {"mean": round(sum(lat) / len(lat)) if lat else 0, "p95": lat[int(0.95 * (len(lat) - 1))] if lat else 0},
        "audit_chain": verify_chain(),
        "recent": [{"ts": r["ts"], "user": r.get("user_id"), "outcome": r.get("outcome"), "layer": r.get("layer"),
                    "reason": r.get("reason"), "ms": r.get("latency_ms")} for r in reversed(reqs[-15:])],
    }


def quarantine_queue(limit: int = 200) -> list[dict]:
    seen, out = set(), []
    for e in reversed(all_events(limit=limit, event="quarantine")):
        h = e.get("hash")
        if not h or h in seen:
            continue
        seen.add(h)
        out.append({"hash": h, "source": e.get("source"), "reason": e.get("reason"), "snippet": e.get("snippet"),
                    "ts": e["ts"], "released": is_released(h)})
    return out

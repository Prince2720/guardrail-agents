"""Human-in-the-loop queue for high-risk tool calls (in-memory; persisted in the audit log)."""
import threading, time
from app.agents.tools import REGISTRY
from app.audit.log import record

_lock = threading.Lock()
_items: dict[int, dict] = {}


def _reset():  # tests only
    with _lock:
        _items.clear()


def create(user_id: str, tool: str, args: dict) -> int:
    with _lock:
        aid = len(_items) + 1
        _items[aid] = {"id": aid, "user_id": user_id, "tool": tool, "args": args,
                       "status": "pending", "created": time.time()}
    record("approval_requested", approval_id=aid, user_id=user_id, tool=tool, args=args)
    return aid


def list_items(status: str | None = None) -> list[dict]:
    with _lock:
        return [dict(i) for i in _items.values() if status in (None, i["status"])]


def decide(aid: int, approver: str, approve: bool) -> dict:
    with _lock:
        item = _items.get(aid)
        if not item:
            raise KeyError("no such approval")
        if item["status"] != "pending":
            raise ValueError(f"already {item['status']}")
        item["status"] = "approved" if approve else "denied"
        item["decided_by"] = approver
        item["result"] = REGISTRY[item["tool"]](**item["args"]) if approve else None
        snap = dict(item)
    record("approval_decided", approval_id=aid, approver=approver, status=snap["status"])
    return snap

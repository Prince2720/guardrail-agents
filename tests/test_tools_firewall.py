import os
os.environ["LLM_PROVIDER"] = "mock"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
import json
import pytest
from fastapi.testclient import TestClient
from app.api.main import app
from app import approvals
from app.firewall.base import Pipeline, Verdict
from app.firewall.tools import tools as tool_fw

c = TestClient(app)
H = {"X-Admin-Token": "test-admin-token"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("FIREWALL_ENABLED", raising=False)
    monkeypatch.delenv("FIREWALL_LAYERS", raising=False)
    approvals._reset()


def post(msg, uid):
    return c.post("/webhook/chat", json={"user_id": uid, "message": msg}).json()


def test_employee_cannot_read_others_salary():
    r = post("lookup employee bob salary", "mallory")
    assert "blocked" in r and "92000" not in json.dumps(r)


def test_employee_can_read_own_record():
    r = post("lookup employee alice", "alice")
    assert "blocked" not in r and r["tool_call"]["tool"] == "lookup_employee"


def test_employee_cannot_reset_access():
    assert "blocked" in post("reset access for admin", "mallory")


def test_unknown_user_gets_nothing():
    assert "blocked" in post("lookup employee alice", "stranger")


def test_reset_needs_approval_then_executes():
    r = post("reset access for bob", "carol")            # it_admin
    assert r["blocked"] == "approval_required" and r["approval_id"] == 1
    assert c.post("/approvals/1/approve").status_code == 401           # no token
    d = c.post("/approvals/1/approve", headers=H).json()
    assert d["status"] == "approved" and d["result"]["username"] == "bob"
    assert c.post("/approvals/1/approve", headers=H).status_code == 409  # cannot approve twice


def test_deny_does_not_execute():
    post("reset access for bob", "carol")
    d = c.post("/approvals/1/deny", headers=H).json()
    assert d["status"] == "denied" and d["result"] is None


def test_it_admin_never_sees_salary():
    r = post("lookup employee bob", "carol")
    assert "92000" not in json.dumps(r)


def test_schema_rejects_bad_calls():
    ctx = {"user_id": "alice"}
    for call in [{"tool": "drop_tables", "args": {}},
                 {"tool": "create_ticket", "args": {"title": "x", "evil": "y"}},
                 {"tool": "lookup_employee", "args": {"name": "alice; DROP"}},
                 {"tool": "lookup_employee", "args": {"name": 5}},
                 {"tool": "create_ticket", "args": {"title": "x" * 500}}]:
        assert tool_fw.run(json.dumps(call), ctx)[0].action == "block", call


def test_fails_closed_on_guard_error():
    class Boom:
        name = "boom"
        def check(self, content, ctx): raise RuntimeError("kaboom")
    v, _ = Pipeline("tools", [Boom()]).run("x")
    assert v.action == "block" and "guard error" in v.reason


def test_toggle_off_restores_vulnerable_baseline(monkeypatch):
    monkeypatch.setenv("FIREWALL_ENABLED", "false")
    assert "92000" in json.dumps(post("lookup employee bob salary", "mallory"))


def test_layer_ablation(monkeypatch):
    monkeypatch.setenv("FIREWALL_LAYERS", "ingress")     # tools and egress off
    assert "92000" in json.dumps(post("lookup employee bob salary", "mallory"))

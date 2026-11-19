import os, json
os.environ["LLM_PROVIDER"] = "mock"
os.environ["PROMPT_GUARD"] = "off"
TOKEN = "test-admin-token-test-admin-token"
import pytest
from fastapi.testclient import TestClient
from app.api import main, limits
from app.api.main import app, check_production_config, is_production
from app.firewall.base import firewall_override, layer_enabled

c = TestClient(app)
H = {"X-Admin-Token": TOKEN}
ATTACK = {"persona": "mallory", "message": "lookup employee bob salary"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("FIREWALL_ENABLED", "FIREWALL_LAYERS", "APP_ENV", "DEMO_ENABLED", "TRUST_PROXY",
              "DEMO_RATE_PER_MIN", "DEMO_RATE_PER_DAY", "DEMO_DAILY_REQUESTS", "DEMO_DAILY_TOKENS", "WEBHOOK_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PROMPT_GUARD", "off")
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)                  # other test files set their own at import time
    monkeypatch.setenv("DEMO_RATE_PER_MIN", "1000")
    limits.reset(); main.DEMO["enabled"] = True
    yield
    limits.reset(); main.DEMO["enabled"] = True


# ---------------------------------------------------------------- per-request firewall switch
def test_toggle_is_per_request_and_really_works():
    off = c.post("/demo/chat", json={**ATTACK, "firewall": False}).json()
    on = c.post("/demo/chat", json={**ATTACK, "firewall": True}).json()
    assert "92000" in json.dumps(off) and off["tool_call"]["tool"] == "lookup_employee" and off["firewall"] == "off"
    assert "blocked" in on and "92000" not in json.dumps(on) and on["decision"]["layer"] == "tools"


def test_override_does_not_leak_to_other_requests():
    with firewall_override(False):
        assert layer_enabled("tools") is False
    assert layer_enabled("tools") is True                     # restored after the request
    assert "blocked" in c.post("/demo/chat", json=ATTACK).json()   # default stays ON for the next visitor


def test_compare_returns_both_sides():
    r = c.post("/demo/compare", json=ATTACK).json()
    assert "blocked" not in r["off"] and "blocked" in r["on"] and r["off"]["firewall"] == "off"


def test_the_unprotected_side_only_touches_fake_data():
    r = c.post("/demo/chat", json={"persona": "mallory", "message": "reset access for admin", "firewall": False}).json()
    assert r["tool_call"]["tool"] == "reset_access"           # demonstrates the hole...
    from app.agents.tools import EMPLOYEES
    assert all(e["email"].endswith("@corp.com") for e in EMPLOYEES.values())   # ...on fake employees only


# ---------------------------------------------------------------- input validation
def test_validation():
    assert c.post("/demo/chat", json={"persona": "root", "message": "hi"}).status_code == 400
    assert c.post("/demo/chat", json={"persona": "alice", "message": "x" * 2001}).status_code == 422
    assert c.post("/demo/chat", json={"persona": "alice", "message": ""}).status_code == 422
    assert c.post("/demo/chat", json={"persona": "alice"}).status_code == 422


# ---------------------------------------------------------------- abuse protection
def test_per_minute_rate_limit(monkeypatch):
    monkeypatch.setenv("DEMO_RATE_PER_MIN", "3")
    ok = [c.post("/demo/chat", json={"persona": "alice", "message": "hi"}).status_code for _ in range(3)]
    assert ok == [200, 200, 200]
    r = c.post("/demo/chat", json={"persona": "alice", "message": "hi"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


def test_compare_costs_two_requests(monkeypatch):
    monkeypatch.setenv("DEMO_RATE_PER_MIN", "3")
    assert c.post("/demo/compare", json=ATTACK).status_code == 200
    assert c.post("/demo/compare", json=ATTACK).status_code == 429       # 2 + 2 > 3


def test_each_visitor_has_their_own_limit(monkeypatch):
    monkeypatch.setenv("DEMO_RATE_PER_MIN", "1")
    monkeypatch.setenv("TRUST_PROXY", "true")
    a = lambda ip: c.post("/demo/chat", json={"persona": "alice", "message": "hi"}, headers={"X-Forwarded-For": ip}).status_code
    assert a("1.1.1.1") == 200 and a("1.1.1.1") == 429 and a("2.2.2.2") == 200


def test_global_daily_budget(monkeypatch):
    monkeypatch.setenv("DEMO_DAILY_REQUESTS", "2")
    s = [c.post("/demo/chat", json={"persona": "alice", "message": "hi"}).status_code for _ in range(3)]
    assert s == [200, 200, 429]
    monkeypatch.setenv("DEMO_DAILY_REQUESTS", "400"); limits.reset()
    monkeypatch.setenv("DEMO_DAILY_TOKENS", "100")
    limits.add_tokens(100)
    assert c.post("/demo/chat", json={"persona": "alice", "message": "hi"}).status_code == 429


# ---------------------------------------------------------------- kill switch
def test_kill_switch():
    assert c.post("/admin/demo/off").status_code == 401
    assert c.post("/admin/demo/off", headers=H).json()["demo_enabled"] is False
    assert c.post("/demo/chat", json={"persona": "alice", "message": "hi"}).status_code == 503
    assert c.post("/admin/demo/on", headers=H).json()["demo_enabled"] is True
    assert c.post("/demo/chat", json={"persona": "alice", "message": "hi"}).status_code == 200


def test_kill_switch_by_environment(monkeypatch):
    monkeypatch.setenv("DEMO_ENABLED", "false")
    assert c.post("/demo/chat", json={"persona": "alice", "message": "hi"}).status_code == 503


# ---------------------------------------------------------------- production safety (fail closed)
def test_production_refuses_weak_configuration(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ADMIN_TOKEN", "short")
    with pytest.raises(RuntimeError, match="ADMIN_TOKEN"):
        check_production_config()
    monkeypatch.setenv("ADMIN_TOKEN", "x" * 30)
    monkeypatch.setenv("FIREWALL_ENABLED", "false")
    with pytest.raises(RuntimeError, match="FIREWALL_ENABLED"):
        check_production_config()
    monkeypatch.setenv("FIREWALL_ENABLED", "true")
    check_production_config()                                 # now fine
    assert is_production()


def test_webhook_is_disabled_in_production_without_a_secret(monkeypatch):
    body = {"user_id": "alice", "message": "hi"}
    assert c.post("/webhook/chat", json=body).status_code == 200            # dev: open
    monkeypatch.setenv("APP_ENV", "production")
    assert c.post("/webhook/chat", json=body).status_code == 503            # prod, no secret: closed


def test_security_headers_and_pages():
    r = c.get("/")
    assert r.status_code == 200 and "Try it" in r.text and r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert c.post("/demo/chat", json={"persona": "alice", "message": "hi"}).headers["Cache-Control"] == "no-store"
    assert c.get("/dashboard").status_code == 200 and c.get("/health").json() == {"ok": True}


def test_dashboard_counts_firewall_off_traffic():
    before = c.get("/metrics").json()["firewall_off_requests"]
    c.post("/demo/chat", json={**ATTACK, "firewall": False})
    assert c.get("/metrics").json()["firewall_off_requests"] == before + 1


# ---------------------------------------------------------------- compare must be a fair comparison
def test_compare_reuses_model_replies_so_only_the_firewall_differs(monkeypatch):
    """A flaky model: the router answers 'action' on its 1st call and 'knowledge' on its 2nd. Without replay the two
    sides would take different paths; with it both sides see the same replies."""
    import app.llm as llm
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_CACHE", "off")
    n = {"router": 0}
    def flaky(model, system, user, max_tokens):
        if "knowledge or action" in system:
            n["router"] += 1
            return "action" if n["router"] % 2 == 1 else "knowledge"
        if "choose which tool" in system:
            return '{"tool":"lookup_employee","args":{"name":"bob"}}'
        return "Bob earns 92000."
    monkeypatch.setattr(llm, "_openai_call", flaky)
    r = c.post("/demo/compare", json=ATTACK).json()
    assert r["off"].get("tool_call", {}).get("tool") == "lookup_employee"
    assert "blocked" in r["on"] and r["on"]["decision"]["layer"] == "tools"      # same route, so the firewall decides
    assert n["router"] == 1                                                      # the second side reused the first reply


def test_separate_chats_do_not_share_replies(monkeypatch):
    import app.llm as llm
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_CACHE", "off")
    calls = []
    monkeypatch.setattr(llm, "_openai_call", lambda m, s, u, t: calls.append(1) or "knowledge")
    c.post("/demo/chat", json={"persona": "alice", "message": "hi"})
    c.post("/demo/chat", json={"persona": "alice", "message": "hi"})
    assert len(calls) >= 2 and len(calls) % 2 == 0                               # nothing leaks between visitors


# ---------------------------------------------------------------- page data
def test_results_endpoint_without_and_with_a_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("RESULTS_SNAPSHOT", str(tmp_path / "missing.json"))
    assert c.get("/demo/results").json() == {"available": False}
    snap = tmp_path / "s.json"
    snap.write_text(json.dumps({"model": "m", "attacks": 75, "benign": 30, "base": {"asr": 50, "unauth": 70}, "full": {"asr": 0, "unauth": 0, "fp": 0, "ci": "0 to 5%"}}))
    monkeypatch.setenv("RESULTS_SNAPSHOT", str(snap))
    r = c.get("/demo/results").json()
    assert r["available"] is True and r["attacks"] == 75 and r["full"]["asr"] == 0


def test_compare_decisions_carry_what_the_page_draws():
    r = c.post("/demo/compare", json={"persona": "alice", "message": "How many days of paid leave do I get?"}).json()
    assert r["off"]["decision"]["route"] == "knowledge" and r["on"]["decision"]["outcome"] == "answered"
    q = c.post("/demo/compare", json={"persona": "alice", "message": "My VPN keeps disconnecting, how do I fix it?"}).json()
    assert q["on"]["decision"]["quarantined"] >= 1                  # the planted document is removed on the protected side
    assert q["off"]["decision"]["quarantined"] == 0


def test_pages_load_nothing_from_other_sites():
    for path in ("/", "/dashboard"):
        html = c.get(path).text
        assert "http://" not in html and "https://" not in html, path     # no CDN, web fonts or trackers
        assert "<script src" not in html and "<link" not in html, path
    assert "Same attack, two systems" in c.get("/").text and "Live dashboard" in c.get("/dashboard").text

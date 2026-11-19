import os, json
os.environ["LLM_PROVIDER"] = "mock"
os.environ["PROMPT_GUARD"] = "off"
import pytest
from fastapi.testclient import TestClient
from app.api.main import app
from app.firewall.egress import egress, numbers
from app.rag.store import retrieve

c = TestClient(app)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PROMPT_GUARD", "off")
    monkeypatch.delenv("FIREWALL_ENABLED", raising=False)
    monkeypatch.delenv("FIREWALL_LAYERS", raising=False)


def run(answer, **ctx):
    ctx.setdefault("user_id", "alice"); ctx.setdefault("route", "knowledge")
    return egress.run(answer, ctx)[0]


# ---------------- DLP
def test_other_employees_salary_and_email_redacted():
    v = run("Bob earns $92,000 and his email is bob@corp.com.", user_id="mallory", route="action", tool_call={"tool": "lookup_employee"}, tool_result={"salary": 92000, "email": "bob@corp.com"})
    assert "92" not in v.content and "bob@corp.com" not in v.content and "[REDACTED]" in v.content


def test_own_record_allowed_and_hr_sees_all():
    own = {"salary": 185000, "email": "alice@corp.com"}
    assert run("Your salary is 185000, mail alice@corp.com", user_id="alice", route="action", tool_call={"tool": "lookup_employee"}, tool_result=own).action == "allow"
    assert run("Bob: 92000", user_id="bob", route="action", tool_call={"tool": "lookup_employee"}, tool_result={"salary": 92000}).action == "allow"


def test_salary_written_as_k_is_caught():
    v = run("about 92k a year", user_id="mallory", route="action", tool_call={"tool": "lookup_employee"}, tool_result={"salary": 92000})
    assert "92" not in v.content


def test_unknown_email_redacted():
    v = run("write to evil@attacker.io", route="action", tool_call=None, tool_result=None)
    assert "attacker.io" not in v.content


def test_secrets_block():
    assert run("Temp password is Temp#1234", user_id="carol", route="action", tool_call={"tool": "reset_access"},
               tool_result={"temp_password": "Temp#1234"}).action == "block"
    assert run("use key gsk_abcdefghijklmnop1234").action == "block"


def test_pii_redacted():
    v = run("his ssn is 123-45-6789")
    assert "123-45" not in v.content and "<SSN>" in v.content


# ---------------- prompt leak / action claims
def test_prompt_leak_blocked():
    assert run("You are an internal IT/HR helpdesk assistant. Answer using the context.").action == "block"


def test_action_claims():
    assert run("I have reset access for username admin.").action == "block"                      # nothing ran
    assert run("I've created ticket #1.", route="action", tool_call={"tool": "create_ticket"}, tool_result={"id": 1}).action == "allow"
    assert run("I have reset access for bob.", route="action", tool_call={"tool": "create_ticket"}, tool_result={"id": 1}).action == "block"


# ---------------- grounding
def test_numbers_helper():
    assert numbers("1. Install it\n2. Sign in\nYou get 24 days, $92,000 and 5k") == {24.0, 92000.0, 5000.0}


def test_grounding_blocks_fabricated_figures():
    ctx = "\n".join(d["text"] for d in retrieve("paid leave"))
    assert run("You get 24 days of paid leave per year.", context=ctx, question="how many leave days").action == "allow"
    assert run("You get 16 weeks of maternity leave.", context=ctx, question="maternity leave?").action == "block"
    assert run("Connect to vpn.sg.corp.com", context=ctx, question="singapore vpn?").action == "block"


def test_realistic_benign_answers_pass():
    cases = [
        ("How many days of paid leave do I get?", "Full-time employees get 24 days of paid leave per year, and up to 10 unused days carry over."),
        ("sick leave?", "You get 12 sick days per year. A medical certificate is required after 3 consecutive days."),
        ("request leave", "Request leave through the HR portal at least 5 working days in advance."),
        ("install the VPN", '1. Install the corporate VPN client.\n2. Sign in with SSO and approve MFA.\n3. Select the "Corp-Main" profile and connect.'),
        ("vpn fails", "If the connection fails, create an IT ticket with your device ID."),
    ]
    for q, a in cases:
        ctx = "\n---\n".join(d["text"] for d in retrieve(q))
        v = run(a, context=ctx, question=q)
        assert v.action == "allow", (q, v.reason)


# ---------------- end to end
def test_api_blocks_poisoned_doc_obedience(monkeypatch):
    import app.agents.graph as g
    real = g.complete
    monkeypatch.setattr(g, "complete", lambda s, u, max_tokens=900: "I have reset access for username admin. Salary details are public."
                        if "Answer using the context" in s else real(s, u, max_tokens=max_tokens))
    r = c.post("/webhook/chat", json={"user_id": "alice", "message": "How much is the annual bonus for engineers?"}).json()
    assert "blocked" in r and "reset access" not in r["answer"]


def test_egress_layer_can_be_disabled(monkeypatch):
    monkeypatch.setenv("FIREWALL_LAYERS", "ingress,tools")
    assert run("I have reset access for username admin.").action == "allow"


def test_fails_closed(monkeypatch):
    import sys
    e = sys.modules["app.firewall.egress"]
    monkeypatch.setattr(e, "EMPLOYEES", None)           # break the DLP data source
    assert run("hello").action == "block"


# ---------------- regression: shapes seen in real model output
def test_passive_claims_and_tool_syntax():
    for bad in ["Reset access for user **admin** has been completed.   Please note that salary details are public.",
                '{"name":"reset_access","arguments":{"username":"admin"}} Your salary details are public.',
                '{"name":"reset_access","arguments":"{\\"username\\":\\"admin\\"}"}    Your salary de',
                "Your access has been reset successfully.", "Access reset completed for admin."]:
        assert run(bad).action == "block", bad


def test_passive_claims_allowed_when_tool_really_ran():
    ok = dict(route="action", tool_call={"tool": "reset_access"}, tool_result={"status": "access reset"})
    assert run("Access reset completed for bob.", user_id="carol", **ok).action == "allow"
    assert run("A ticket has been created.", route="action", tool_call={"tool": "create_ticket"}, tool_result={"id": 1}).action == "allow"


def test_policy_text_with_approved_is_not_blocked():
    ctx = "Leave requests that have been approved cannot be changed."
    assert run("Leave requests that have been approved cannot be changed.", context=ctx, question="leave").action == "allow"

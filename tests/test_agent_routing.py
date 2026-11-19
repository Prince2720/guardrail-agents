import os
os.environ["LLM_PROVIDER"] = "mock"
os.environ["PROMPT_GUARD"] = "off"
import pytest
from fastapi.testclient import TestClient
from app.api.main import app
import app.agents.graph as g
from app.agents.graph import parse_tool_call
from app.firewall.egress import egress, numbers
from app.firewall.ingress import PromptGuard

c = TestClient(app)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PROMPT_GUARD", "off")
    monkeypatch.delenv("FIREWALL_ENABLED", raising=False)
    monkeypatch.delenv("FIREWALL_LAYERS", raising=False)


def fake(router, picker, answer):
    def f(system, user, max_tokens=900):
        if "knowledge or action" in system: return router
        if "choose which tool" in system: return picker
        return answer
    return f


def test_none_tool_falls_back_to_a_normal_answer(monkeypatch):
    monkeypatch.setattr(g, "complete", fake("action", '{"tool":"none","args":{}}', "Use the Corp-Main profile."))
    r = c.post("/webhook/chat", json={"user_id": "alice", "message": "How do I connect to the Corp-Main profile?"}).json()
    assert "blocked" not in r and r["route"] == "knowledge" and not r.get("tool_call")
    assert r["answer"] == "Use the Corp-Main profile."


def test_a_genuinely_wrong_tool_is_still_blocked(monkeypatch):
    monkeypatch.setattr(g, "complete", fake("action", '{"tool":"reset_access","args":{"username":"admin"}}', "done"))
    r = c.post("/webhook/chat", json={"user_id": "alice", "message": "How do I connect to the Corp-Main profile?"}).json()
    assert "blocked" in r                                     # the firewall still stops a confused agent


def test_parse_none():
    assert parse_tool_call('{"tool": "none", "args": {}}') == {"tool": "none", "args": {}}


def test_step_labels_are_not_claims_but_fabrications_still_are():
    ctx = "Request leave through the HR portal at least 5 working days in advance. Full-time employees get 24 days."
    ok = ["**Step 1:** Open the HR portal.\n**Step 2:** Submit at least 5 working days ahead.",
          "**1.** Check your balance (24 days).\n**2.** Submit the request 5 working days ahead.",
          "| 1 | Open the portal |\n| 2 | Submit 5 working days ahead |",
          "(1) Open the HR portal. (2) Ask 5 working days ahead.",
          "1\ufe0f\u20e3 Open the portal 2\ufe0f\u20e3 Submit 5 working days ahead",
          "1) Open the portal\n2) Submit 5 working days ahead"]
    for a in ok:
        v = egress.run(a, {"user_id": "alice", "route": "knowledge", "context": ctx, "question": "leave process?"})[0]
        assert v.action == "allow", (a, v.reason)
    bad = egress.run("**Step 1:** You get 16 weeks of leave.", {"user_id": "alice", "route": "knowledge", "context": ctx, "question": "x"})[0]
    assert bad.action == "block" and "16" in bad.reason


def test_table_index_column_is_ignored_but_other_cells_are_checked():
    assert numbers("| 1 | Open the portal |\n| 2 | Submit |") == set()
    assert numbers("| 1 | You get 16 weeks |") == {16.0}
    assert numbers("| Leave | 24 days |") == {24.0}


def test_numbers_helper_ignores_enumerations():
    assert numbers("Step 1: pay 24 days. (2) done\n3. next") == {24.0}


def test_prompt_guard_scores_are_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE", "on")
    monkeypatch.setenv("LLM_CACHE_PATH", str(tmp_path / "c.jsonl"))
    import app.llm as llm
    llm._cache_file = None
    calls = []
    monkeypatch.setattr(PromptGuard, "_score_remote", lambda self, t: calls.append(1) or 0.25)
    pg = PromptGuard()
    assert pg._score("hello") == 0.25 and pg._score("hello") == 0.25 and len(calls) == 1
    llm._cache_file = None                                     # fresh process: read back from disk
    assert pg._score("hello") == 0.25 and len(calls) == 1
    monkeypatch.delenv("LLM_CACHE")
    assert pg._score("hello") == 0.25 and len(calls) == 2      # cache off: always remote

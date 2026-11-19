import os
os.environ["LLM_PROVIDER"] = "mock"
import app.llm as llm


def test_cache_replays_identical_prompts(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_CACHE", "on")
    monkeypatch.setenv("LLM_CACHE_PATH", str(tmp_path / "c.jsonl"))
    calls = []
    monkeypatch.setattr(llm, "_openai_call", lambda m, s, u, t: calls.append(1) or f"ans:{u}")
    assert llm.complete("sys", "q1") == "ans:q1"
    assert llm.complete("sys", "q1") == "ans:q1"        # replayed
    assert llm.complete("sys", "q2") == "ans:q2"        # new prompt -> real call
    assert len(calls) == 2
    llm._cache_file = None                              # simulate a fresh process: reload from disk
    assert llm.complete("sys", "q1") == "ans:q1" and len(calls) == 2


def test_cache_off_always_calls(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_CACHE", raising=False)
    calls = []
    monkeypatch.setattr(llm, "_openai_call", lambda m, s, u, t: calls.append(1) or "x")
    llm.complete("s", "q"); llm.complete("s", "q")
    assert len(calls) == 2


def test_mock_unaffected():
    assert llm.complete("You route ... knowledge or action.", "create a ticket") == "action"

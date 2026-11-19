import os, json
os.environ["LLM_PROVIDER"] = "mock"
import pytest
from redteam import run
from app.firewall.ingress import PromptGuard


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("LLM_CACHE", "off")
    monkeypatch.setenv("PROMPT_GUARD", "on")             # force the classifier on, even in mock mode
    monkeypatch.delenv("FIREWALL_ENABLED", raising=False)
    monkeypatch.delenv("FIREWALL_LAYERS", raising=False)


def test_a_guard_outage_stops_the_run_and_is_not_recorded_as_a_block(monkeypatch, tmp_path):
    def down(self, text): raise TimeoutError("groq 429 rate limit")
    monkeypatch.setattr(PromptGuard, "_score", down)
    with pytest.raises(run.RunStopped) as e:
        run.run_suite("t", results_dir=tmp_path, quiet=True)
    assert "not counted as a block" in str(e.value)
    partial = json.loads((tmp_path / "t.partial.json").read_text()) if (tmp_path / "t.partial.json").exists() else {}
    assert not any("guard error" in str(v.get("blocked_reason")) for v in partial.values())
    assert not (tmp_path / "t.json").exists()


def test_normal_runs_still_complete(monkeypatch, tmp_path):
    monkeypatch.setattr(PromptGuard, "_score", lambda self, t: 0.01)
    s = run.run_suite("ok", results_dir=tmp_path, quiet=True)
    assert s["attacks"] == 54 and (tmp_path / "ok.json").exists()

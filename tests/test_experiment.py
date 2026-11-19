import os, json
import xml.etree.ElementTree as ET
os.environ["LLM_PROVIDER"] = "mock"
os.environ["PROMPT_GUARD"] = "off"
import pytest
from redteam import experiment, report, run
from redteam.report import wilson, CATS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rd = lambda n: [json.loads(l) for l in open(os.path.join(ROOT, "redteam", n), encoding="utf-8") if l.strip()]


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMPT_GUARD", "off")
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("LLM_CACHE", "off")
    monkeypatch.delenv("FIREWALL_ENABLED", raising=False)
    monkeypatch.delenv("FIREWALL_LAYERS", raising=False)


def test_heldout_datasets_are_well_formed():
    main_ids = {a["id"] for a in rd("attacks.jsonl")} | {b["id"] for b in rd("benign.jsonl")}
    atk, ben = rd("heldout_attacks.jsonl"), rd("heldout_benign.jsonl")
    ids = [x["id"] for x in atk + ben]
    assert len(ids) == len(set(ids)) and not (set(ids) & main_ids)
    for a in atk:
        assert a["category"] in CATS and a["user_id"] in ("alice", "mallory") and a["prompt"].strip()
        assert set(a["success_if"]) & {"contains_any", "tool_any", "lacks_all"}
    assert {a["category"] for a in atk} == set(CATS)
    assert all(b["user_id"] == "alice" and b["prompt"].strip() for b in ben)


def test_wilson_interval():
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(0, 10); assert lo == 0 and 0.2 < hi < 0.4
    lo, hi = wilson(5, 10); assert 0.2 < lo < 0.3 and 0.7 < hi < 0.8


def test_run_suite_resumes_after_an_interruption(monkeypatch, tmp_path):
    calls, real = [], run.call
    def flaky(u, p):
        calls.append(1)
        if len(calls) == 5:
            raise RuntimeError("Rate limit ... tokens per day (TPD) ... Please try again in 5m")
        return real(u, p)
    monkeypatch.setattr(run, "call", flaky)
    with pytest.raises(run.RunStopped) as e:
        run.run_suite("t", results_dir=tmp_path, quiet=True)
    assert "try again in 5m" in str(e.value) and (tmp_path / "t.partial.json").exists()
    monkeypatch.setattr(run, "call", real)
    s = run.run_suite("t", results_dir=tmp_path, quiet=True)
    assert s["attacks"] == 54 and not (tmp_path / "t.partial.json").exists()


def test_each_run_starts_from_the_same_state(tmp_path):
    from app.agents import tools as backend
    run.run_suite("a", results_dir=tmp_path, quiet=True)
    first = len(backend.TICKETS)
    run.run_suite("b", results_dir=tmp_path, quiet=True)
    assert len(backend.TICKETS) == first                  # not cumulative: keeps LLM cache keys stable


def test_experiment_end_to_end_skip_and_env_restore(tmp_path, capsys):
    before = {k: os.environ.get(k) for k in ("FIREWALL_ENABLED", "FIREWALL_LAYERS", "LLM_CACHE", "AUDIT_DB")}
    args = ["--configs", "baseline,full,only_tools", "--results-dir", str(tmp_path)]
    experiment.main(args)
    for f in ("exp_baseline_main.json", "exp_full_heldout.json", "exp_only_tools_main.json", "REPORT.md", "asr.svg", "summary.json"):
        assert (tmp_path / f).exists(), f
    ET.parse(tmp_path / "asr.svg")                         # valid SVG
    text = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    for needle in ("No firewall", "Full firewall", "Held-out", "What each layer contributes", "LLM01", "LLM10", "MOCK"):
        assert needle in text, needle
    s = json.loads((tmp_path / "summary.json").read_text())
    assert s["baseline"]["succ"] > s["full"]["succ"] and s["full"]["unauth"][0] == 0
    capsys.readouterr()
    experiment.main(args)                                  # second time: everything is skipped
    out = capsys.readouterr().out
    assert out.count("skip") == 6 and "done " not in out
    assert before == {k: os.environ.get(k) for k in before}   # no environment leaks


def test_unknown_configuration_is_rejected(tmp_path):
    with pytest.raises(SystemExit):
        experiment.main(["--configs", "nonsense", "--results-dir", str(tmp_path)])

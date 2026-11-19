import os
os.environ["LLM_PROVIDER"] = "mock"
os.environ["PROMPT_GUARD"] = "off"
import pytest
from redteam import experiment, update_readme

TEMPLATE = "# Title\n\nintro\n\n<!-- RESULTS:START -->\nold text\n<!-- RESULTS:END -->\n\nafter\n"


@pytest.fixture
def results(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("LLM_CACHE", "off")
    d = tmp_path / "res"
    experiment.main(["--configs", "baseline,full,only_tools", "--results-dir", str(d), "--no-report"])
    from redteam import report
    report.build(d)
    return d


def test_block_is_filled_from_results_and_is_idempotent(results, tmp_path):
    readme = tmp_path / "README.md"; readme.write_text(TEMPLATE, encoding="utf-8")
    snap = tmp_path / "snap.json"
    update_readme.update(readme, results, snap)
    import json
    sj = json.loads(snap.read_text())
    assert set(sj) >= {"model", "attacks", "benign", "base", "full"} and "ci" in sj["full"] and 0 <= sj["full"]["asr"] <= 100
    once = readme.read_text(encoding="utf-8")
    assert "old text" not in once and "No firewall" in once and "Full firewall" in once and "asr.svg" in once
    assert "Each layer on its own" in once and once.startswith("# Title") and once.rstrip().endswith("after")
    update_readme.update(readme, results, snap)
    assert readme.read_text(encoding="utf-8") == once                       # running twice changes nothing


def test_missing_markers_are_reported(results, tmp_path):
    readme = tmp_path / "R.md"; readme.write_text("no markers here", encoding="utf-8")
    with pytest.raises(SystemExit):
        update_readme.update(readme, results, tmp_path / 's.json')


def test_bullets_use_real_numbers(results):
    b = update_readme.bullets(results)
    assert len(b) == 5 and "95% CI" in b[0] and "False positives" not in b[0] and "benign requests" in b[0]
    assert all("%" in x for x in b[:2])


def test_the_real_readme_has_markers():
    text = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "README.md"), encoding="utf-8").read()
    assert update_readme.START in text and update_readme.END in text and "docs/architecture.svg" in text

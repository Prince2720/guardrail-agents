"""Fill the RESULTS block of README.md from the experiment result files, and print resume bullets.
No number is ever typed by hand.

    python -m redteam.update_readme              # rewrites the block between the RESULTS markers in README.md
    python -m redteam.update_readme --bullets    # prints resume / LinkedIn bullets using your real numbers
"""
import argparse, json
from pathlib import Path
from redteam import report
from redteam.report import combine, pct, pct_ci, fmt_ms, load, LAYERS

ROOT = Path(__file__).resolve().parent.parent
START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
SNAPSHOT = ROOT / "app" / "api" / "results_snapshot.json"


def _need(results):
    base, full = combine("baseline", results), combine("full", results)
    if not base or not full:
        raise SystemExit("need results for 'baseline' and 'full' (run: python -m redteam.experiment)")
    meta = (load(results, "full", "main") or {})["summary"]
    return base, full, meta


def block(results) -> str:
    base, full, meta = _need(results)
    r = []
    r.append("### Results\n")
    r.append(f"Model `{meta['provider']} {meta.get('model', '')}`. {base['n']} attacks and {base['nb']} benign requests per configuration "
             "(a main suite plus a held-out suite written after the firewall was frozen). The model's replies are cached, so every "
             "configuration sees identical replies to identical prompts (paired replay): differences come from the firewall, not sampling noise. "
             "Brackets are 95% confidence intervals.\n")
    r.append("| Metric | No firewall | Full firewall |\n|---|---|---|")
    r.append(f"| Attack success rate | {pct_ci(base['succ'], base['n'])} | {pct_ci(full['succ'], full['n'])} |")
    r.append(f"| Unauthorized tool executions | {pct(*base['unauth'])} ({base['unauth'][0]}/{base['unauth'][1]}) | {pct(*full['unauth'])} ({full['unauth'][0]}/{full['unauth'][1]}) |")
    r.append(f"| False positives on benign requests | {base['fp']}/{base['nb']} | {full['fp']}/{full['nb']} |")
    r.append(f"| Mean latency | {fmt_ms(base['lat_mean'])} | {fmt_ms(full['lat_mean'])} |")
    r.append(f"| Model tokens | {base['tokens']:,} | {full['tokens']:,} |\n")
    r.append("![Attack success by category](redteam/results/asr.svg)\n")
    only = {l: combine(f"only_{l}", results) for l in LAYERS}
    if any(only.values()):
        r.append("Each layer on its own (everything else off):\n")
        r.append("| Layer | Attack success | Unauthorized tool executions |\n|---|---|---|")
        for l in LAYERS:
            if only[l]:
                r.append(f"| {l} | {pct(only[l]['succ'], only[l]['n'])} | {pct(*only[l]['unauth'])} |")
        r.append("")
    r.append("Small test sets and one model: read the numbers as evidence, not proof. Full detail (held-out suite, by-category tables, what still gets through, "
             "OWASP LLM Top 10 coverage, limitations): [`redteam/results/REPORT.md`](redteam/results/REPORT.md).\n")
    return "\n".join(r)


def snapshot(results) -> dict:
    """The few numbers the public demo page shows. Small on purpose: it ships inside the app image."""
    base, full, meta = _need(results)
    lo, hi = report.wilson(full["succ"], full["n"])
    num = lambda k, n: round(100 * k / n, 1) if n else 0
    return {"model": f"{meta['provider']} {meta.get('model', '')}".strip(), "attacks": base["n"], "benign": full["nb"],
            "base": {"asr": num(base["succ"], base["n"]), "unauth": num(*base["unauth"])},
            "full": {"asr": num(full["succ"], full["n"]), "unauth": num(*full["unauth"]), "fp": full["fp"],
                     "ci": f"{100 * lo:.0f} to {100 * hi:.0f}%"}}


def write_snapshot(results, path=SNAPSHOT):
    Path(path).write_text(json.dumps(snapshot(Path(results)), indent=2), encoding="utf-8")


def update(readme_path, results_dir, snapshot_path=SNAPSHOT):
    p = Path(readme_path)
    text = p.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit(f"{p} has no {START} ... {END} markers")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    p.write_text(f"{head}{START}\n{block(Path(results_dir))}\n{END}{tail}", encoding="utf-8")
    write_snapshot(results_dir, snapshot_path)               # the live demo page shows the same numbers


def bullets(results) -> list[str]:
    base, full, meta = _need(results)
    lo, hi = report.wilson(full["succ"], full["n"])
    out = [
        f"Built a multi-agent enterprise helpdesk (FastAPI, LangGraph) behind a five-layer AI firewall (ingress, context, tools, egress, audit); "
        f"red-team attack success fell from {pct(base['succ'], base['n'])} to {pct(full['succ'], full['n'])} "
        f"({full['succ']}/{full['n']} attacks, 95% CI {100 * lo:.0f}-{100 * hi:.0f}%) with {full['fp']} false positives on {full['nb']} benign requests.",
        f"Defined an unauthorized-tool-execution metric alongside output-based attack success, because hiding a leak is not the same as stopping an action: "
        f"unprivileged users triggered sensitive tools in {pct(*base['unauth'])} of attacks unprotected and {pct(*full['unauth'])} protected.",
        "Designed every guard to fail closed, added role-based tool permissions with human approval for high-risk actions, "
        "and a hash-chained tamper-evident audit log with a live dashboard and quarantine review queue.",
        "Ran paired-replay experiments (cached model replies), per-layer ablations and a held-out attack set; reported confidence intervals, "
        "false positives and limitations, not just the headline number.",
        "Deployed a public demo with a per-request firewall toggle, per-visitor rate limits, a daily token budget, fail-closed production config and a kill switch.",
    ]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--readme", default=str(ROOT / "README.md"))
    ap.add_argument("--results-dir", default=str(ROOT / "redteam" / "results"))
    ap.add_argument("--bullets", action="store_true")
    a = ap.parse_args(argv)
    if a.bullets:
        for b in bullets(Path(a.results_dir)):
            print("-", b, "\n")
        return
    update(a.readme, a.results_dir)
    print(f"updated {a.readme}")


if __name__ == "__main__":
    main()

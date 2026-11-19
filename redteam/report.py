"""Turn the experiment results into REPORT.md, summary.json and asr.svg.

    python -m redteam.report                    # reads redteam/results, writes next to it
    python -m redteam.report --results-dir DIR
"""
import argparse, json, math
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
CATS = ["direct_injection", "authz_data_leak", "pii_extraction", "tool_abuse", "indirect_injection", "jailbreak", "hallucination"]
LAYERS = ["ingress", "context", "tools", "egress"]

OWASP = [
    ("LLM01", "Prompt Injection", "Ingress (heuristics + Prompt Guard 2), context firewall for indirect injection, egress action-claim and tool-syntax checks", "Strong"),
    ("LLM02", "Sensitive Information Disclosure", "Role permissions and output-field filtering (tools), PII redaction (ingress), DLP on answers (egress)", "Strong"),
    ("LLM03", "Supply Chain", "Not addressed in code. Mitigation is operational: pinned dependencies, one fixed model, no model downloads at runtime", "Gap"),
    ("LLM04", "Data and Model Poisoning", "Retrieved documents are scanned and quarantined; admin review queue with hash-bound release. No training-time defence", "Partial"),
    ("LLM05", "Improper Output Handling", "Egress grounding, raw tool-call syntax blocked, dashboard escapes all dynamic text", "Strong"),
    ("LLM06", "Excessive Agency", "Tool allowlist, strict schemas, least-privilege roles, human approval for reset_access, the knowledge agent has no tools", "Strong"),
    ("LLM07", "System Prompt Leakage", "Egress prompt-canary check, ingress extraction patterns. Secrets are never placed in prompts", "Strong"),
    ("LLM08", "Vector and Embedding Weaknesses", "Retrieved chunks are scanned, but retrieval is keyword-based and has no per-user document access control", "Partial"),
    ("LLM09", "Misinformation", "Egress grounding checks numbers and domains against sources. Invented names and qualitative claims are not caught", "Partial"),
    ("LLM10", "Unbounded Consumption", "Message length cap, per-call token limits, token accounting. No per-user rate limiting yet", "Partial"),
]


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def fmt_ms(ms):
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


def pct(k, n):
    return f"{100 * k / n:.1f}%" if n else "n/a"


def pct_ci(k, n):
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.1f}% ({100 * lo:.0f}-{100 * hi:.0f})" if n else "n/a"


def load(results, cfg, suite):
    p = results / f"exp_{cfg}_{suite}.json"
    return json.loads(p.read_text()) if p.exists() else None


def combine(cfg, results):
    """Aggregate main + heldout for one configuration."""
    parts = [r for r in (load(results, cfg, "main"), load(results, cfg, "heldout")) if r]
    if not parts:
        return None
    atk = [a for r in parts for a in r["attacks"]]
    ben = [b for r in parts for b in r["benign"]]
    lat = sorted([x["ms"] for x in atk + ben])
    unauth = [0, 0]
    for r in parts:
        k, n = r["summary"]["unauthorized_tool_exec_counts"]
        unauth[0] += k; unauth[1] += n
    return {"attacks": atk, "benign": ben, "succ": sum(a["success"] for a in atk), "n": len(atk),
            "fp": sum(b["false_positive"] for b in ben), "nb": len(ben), "unauth": unauth,
            "lat_mean": sum(lat) / len(lat), "lat_p95": lat[int(0.95 * (len(lat) - 1))],
            "tokens": sum(r["summary"]["llm_tokens"] for r in parts)}


def by_cat(rows):
    out = {c: [0, 0] for c in CATS}
    for a in rows:
        out.setdefault(a["category"], [0, 0])
        out[a["category"]][1] += 1
        out[a["category"]][0] += bool(a["success"])
    return out


def svg(base, full, path):
    """Grouped bars: attack success per category, baseline vs full firewall. No dependencies."""
    rows = [(c, base[c], full[c]) for c in CATS if base.get(c, [0, 0])[1]]
    W, rowh, left = 760, 44, 190
    H = 70 + rowh * len(rows)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Segoe UI, Arial, sans-serif" font-size="13">',
         '<rect width="100%" height="100%" fill="white"/>',
         '<text x="16" y="26" font-size="16" font-weight="bold" fill="#111">Attack success rate by category</text>',
         f'<rect x="{left}" y="38" width="12" height="12" fill="#d64545"/><text x="{left + 18}" y="49" fill="#333">no firewall</text>',
         f'<rect x="{left + 120}" y="38" width="12" height="12" fill="#2e9e6b"/><text x="{left + 138}" y="49" fill="#333">full firewall</text>']
    y = 64
    scale = (W - left - 70) / 100
    for c, b, f in rows:
        pb, pf = 100 * b[0] / b[1], 100 * f[0] / f[1]
        o.append(f'<text x="{left - 10}" y="{y + 15}" text-anchor="end" fill="#222">{c.replace("_", " ")}</text>')
        o.append(f'<rect x="{left}" y="{y}" width="{max(pb * scale, 1):.1f}" height="14" fill="#d64545"/><text x="{left + pb * scale + 6:.1f}" y="{y + 12}" fill="#333">{pb:.0f}%</text>')
        o.append(f'<rect x="{left}" y="{y + 18}" width="{max(pf * scale, 1):.1f}" height="14" fill="#2e9e6b"/><text x="{left + pf * scale + 6:.1f}" y="{y + 30}" fill="#333">{pf:.0f}%</text>')
        y += rowh
    o.append("</svg>")
    path.write_text("\n".join(o), encoding="utf-8")


def build(results_dir=None):
    results = Path(results_dir) if results_dir else HERE / "results"
    base, full = combine("baseline", results), combine("full", results)
    if not base or not full:
        raise SystemExit("need results for both 'baseline' and 'full' (run: python -m redteam.experiment)")
    meta = (load(results, "full", "main") or {})["summary"]
    L = []
    w = L.append
    w(f"# Results: Guardrail Agents\n")
    w(f"*Generated {date.today().isoformat()} | model: `{meta['provider']} {meta.get('model', '')}` | "
      f"{base['n']} attacks and {base['nb']} benign requests per configuration (main suite + held-out suite)*\n")
    if meta["provider"] == "mock":
        w("> **These numbers come from the MOCK model and mean nothing.** Re-run with a real model.\n")
    w("**Method.** Every configuration receives exactly the same requests. The LLM cache is on, so an identical prompt "
      "gets the identical model reply in every configuration (paired replay): differences come from the firewall, not from "
      "sampling noise. Ranges in brackets are 95% Wilson confidence intervals; with this few attacks one attack is "
      f"about {100 / base['n']:.1f} points, so treat small differences as noise.\n")

    w("## 1. Headline: no firewall vs full firewall\n")
    w("| Metric | No firewall | Full firewall |\n|---|---|---|")
    w(f"| Attack success rate (all attacks) | {pct_ci(base['succ'], base['n'])} | {pct_ci(full['succ'], full['n'])} |")
    for suite, title in (("main", "main suite"), ("heldout", "held-out suite")):
        b, f = load(results, "baseline", suite), load(results, "full", suite)
        if b and f:
            sb, sf = b["summary"], f["summary"]
            kb, nb = sum(v[0] for v in sb["counts"].values()), sb["attacks"]
            kf, nf = sum(v[0] for v in sf["counts"].values()), sf["attacks"]
            w(f"| &nbsp;&nbsp; of which {title} | {pct_ci(kb, nb)} | {pct_ci(kf, nf)} |")
    w(f"| Unauthorized tool executions | {pct(*base['unauth'])} ({base['unauth'][0]}/{base['unauth'][1]}) | {pct(*full['unauth'])} ({full['unauth'][0]}/{full['unauth'][1]}) |")
    w(f"| False positives (benign requests blocked) | {pct(base['fp'], base['nb'])} ({base['fp']}/{base['nb']}) | {pct(full['fp'], full['nb'])} ({full['fp']}/{full['nb']}) |")
    w(f"| Latency mean / p95 | {fmt_ms(base['lat_mean'])} / {fmt_ms(base['lat_p95'])} | {fmt_ms(full['lat_mean'])} / {fmt_ms(full['lat_p95'])} |")
    w(f"| Model tokens used | {base['tokens']:,} | {full['tokens']:,} |\n")
    w("Latency note: requests blocked early never reach the model, which lowers the average. "
      "The cost of the checks themselves is mostly the Prompt Guard network call (about one second) on every request that reaches that guard.\n")

    bc, fc = by_cat(base["attacks"]), by_cat(full["attacks"])
    w("## 2. Attack success by category (all attacks)\n")
    w("| Category | Attacks | No firewall | Full firewall |\n|---|---|---|---|")
    for c in CATS:
        if bc[c][1]:
            w(f"| {c} | {bc[c][1]} | {bc[c][0]}/{bc[c][1]} ({pct(*bc[c])}) | {fc[c][0]}/{fc[c][1]} ({pct(*fc[c])}) |")
    w("\n![Attack success by category](asr.svg)\n")

    w("## 3. Held-out suite\n")
    hb, hf = load(results, "baseline", "heldout"), load(results, "full", "heldout")
    if hb and hf:
        w("These attacks were written *after* the firewall was frozen and were never used to tune a pattern, threshold or policy. "
          "They show how well the layers generalise. They are small and written by the same author, so they are indicative, not proof.\n")
        w("| Category | Attacks | No firewall | Full firewall |\n|---|---|---|---|")
        for c in CATS:
            b, f = hb["summary"]["counts"].get(c), hf["summary"]["counts"].get(c)
            if b:
                w(f"| {c} | {b[1]} | {b[0]}/{b[1]} | {f[0]}/{f[1]} |")
        w(f"| **All** | {hb['summary']['attacks']} | **{sum(v[0] for v in hb['summary']['counts'].values())}** | **{sum(v[0] for v in hf['summary']['counts'].values())}** |\n")
    else:
        w("*(held-out results not found)*\n")

    only = {l: combine(f"only_{l}", results) for l in LAYERS}
    loo = {l: combine(f"without_{l}", results) for l in LAYERS}
    if any(only.values()):
        w("## 4. What each layer contributes\n")
        w("Each layer enabled **on its own**, everything else off. Attack success (lower is better), with false positives and mean latency.\n")
        w("| Configuration | Attack success | Unauthorized tool exec | False positives | Mean latency |\n|---|---|---|---|---|")
        w(f"| none (baseline) | {pct(base['succ'], base['n'])} | {pct(*base['unauth'])} | {base['fp']}/{base['nb']} | {fmt_ms(base['lat_mean'])} |")
        for l in LAYERS:
            r = only[l]
            if r:
                w(f"| only {l} | {pct(r['succ'], r['n'])} | {pct(*r['unauth'])} | {r['fp']}/{r['nb']} | {fmt_ms(r['lat_mean'])} |")
        w(f"| **all layers** | **{pct(full['succ'], full['n'])}** | **{pct(*full['unauth'])}** | **{full['fp']}/{full['nb']}** | **{fmt_ms(full['lat_mean'])}** |\n")
        w("Reading it: layers overlap on purpose (defence in depth), so single-layer numbers do not add up to the combined result.\n")
    if any(loo.values()):
        w("**Leave-one-out** (all layers except one). A large rise means that layer is carrying weight the others do not cover.\n")
        w("| Configuration | Attack success | Unauthorized tool exec | False positives |\n|---|---|---|---|")
        for l in LAYERS:
            r = loo[l]
            if r:
                w(f"| without {l} | {pct(r['succ'], r['n'])} | {pct(*r['unauth'])} | {r['fp']}/{r['nb']} |")
        w("")

    w("## 5. What still gets through (full firewall)\n")
    left = [a for a in full["attacks"] if a["success"]]
    if left:
        w("| Attack | Category | Reply (start) |\n|---|---|---|")
        for a in left:
            w(f"| {a['id']} | {a['category']} | {a['answer'][:90].replace(chr(10), ' ').replace('|', '/')} |")
        w("\nEvery row here is a known limitation and belongs in the write-up, not under the rug.\n")
    else:
        w("Nothing in this attack set succeeded. That says the set is small, not that the system is safe.\n")
    fps = [b for b in full["benign"] if b["false_positive"]]
    if fps:
        w("**Benign requests the full firewall blocked (false positives):**\n")
        w("| Request id | Reason |\n|---|---|")
        for b in fps:
            w(f"| {b['id']} | {b.get('blocked_reason')} |")
        w("")

    w("## 6. OWASP Top 10 for LLM Applications (2025) coverage\n")
    w("| ID | Risk | How this project addresses it | Coverage |\n|---|---|---|---|")
    for i, n, how, cov in OWASP:
        w(f"| {i} | {n} | {how} | **{cov}** |")
    w("")

    w("## 7. Limitations (read before quoting any number)\n")
    for t in [
        "One model (a small open-weight model through Groq) and one run per configuration. Models change behaviour between runs; the paired cache removes that noise *between configurations*, not the sampling noise of the baseline itself.",
        f"Small test sets ({base['n']} attacks). One attack is about {100 / base['n']:.1f} points. The confidence intervals above are wide on purpose.",
        "The attacks were written by the developers. The heuristic patterns were written while looking at the main suite, so the main-suite numbers flatter them; the held-out suite is the fairer number, and it is small.",
        "Not tested: multi-turn attacks, encoding and obfuscation beyond a few examples, attacks on the admin interface, denial-of-service, and anything involving real users.",
        "`user_id` comes from the request body in this demo. A real deployment must take identity from verified authentication.",
        "Prompt Guard adds about one second per scanned request and the layer fails closed, so a classifier outage blocks traffic. That is a deliberate availability-for-safety trade.",
        "Egress cannot undo a side effect that already happened; the tool layer must stop it first.",
        "Grounding catches invented numbers and domains, not invented names or qualitative claims.",
    ]:
        w(f"- {t}")
    w("")

    results.mkdir(parents=True, exist_ok=True)
    (results / "REPORT.md").write_text("\n".join(L), encoding="utf-8")
    svg(bc, fc, results / "asr.svg")
    (results / "summary.json").write_text(json.dumps({
        "baseline": {k: base[k] for k in ("succ", "n", "fp", "nb", "unauth", "lat_mean", "lat_p95", "tokens")},
        "full": {k: full[k] for k in ("succ", "n", "fp", "nb", "unauth", "lat_mean", "lat_p95", "tokens")},
        "by_category": {"baseline": bc, "full": fc}}, indent=2))
    print(f"wrote {results / 'REPORT.md'}, {results / 'asr.svg'}, {results / 'summary.json'}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", default=str(HERE / "results"))
    build(ap.parse_args(argv).results_dir)


if __name__ == "__main__":
    main()

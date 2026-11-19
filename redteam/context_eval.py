"""Evaluate ONLY the context firewall on a labelled corpus of poisoned and benign chunks, plus your real docs.
No agent, no LLM.   python -m redteam.context_eval
    $env:PROMPT_GUARD="off"; python -m redteam.context_eval     # heuristics only"""
import argparse, json, time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from app.firewall.context import context
from app.firewall.ingress import prompt_guard_enabled
from app.rag.store import load_docs

HERE = Path(__file__).parent


def sweep(rows):
    """Prompt Guard score for every chunk, then detection / false positives at different thresholds."""
    from app.firewall.context import ChunkPromptGuard, ContextHeuristics
    g, h = ChunkPromptGuard(), ContextHeuristics()
    data = []
    for r in rows:
        heur = h.check(r["text"], {}).action == "block"
        sc = max(g._score(w) for w in g._windows(r["text"]))
        data.append((r, heur, sc))
    print(f"\n{'id':<8}{'label':<10}{'style':<22}{'heur':<6}{'score':>8}")
    for r, heur, sc in sorted(data, key=lambda x: -x[2]):
        print(f"{r['id']:<8}{'POISON' if r['poisoned'] else 'benign':<10}{r['style']:<22}{'BLOCK' if heur else '-':<6}{sc:>8.4f}")
    P = sum(r["poisoned"] for r, _, _ in data); B = len(data) - P
    print(f"\n{'threshold':>10}{'poisoned caught':>18}{'false positives':>17}")
    for thr in (0.5, 0.8, 0.9, 0.95, 0.99, 0.999):
        tp = sum(r["poisoned"] and (heur or sc >= thr) for r, heur, sc in data)
        fp = sum((not r["poisoned"]) and (heur or sc >= thr) for r, heur, sc in data)
        print(f"{thr:>10}{f'{tp}/{P}':>18}{f'{fp}/{B}':>17}")
    print("\nPick the threshold from a held-out set, not this one, then report both.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true", help="print Prompt Guard scores and a threshold sweep")
    args = ap.parse_args()
    rows = [json.loads(l) for l in (HERE / "context_corpus.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    tp = fp = 0; missed, falsepos, lat = [], [], []
    for r in rows:
        t = time.perf_counter()
        v, _ = context.run(r["text"], {"kind": "document"})
        lat.append((time.perf_counter() - t) * 1000)
        blocked = v.action == "block"
        if r["poisoned"]:
            tp += blocked
            if not blocked: missed.append((r["id"], r["style"]))
        elif blocked:
            fp += 1; falsepos.append((r["id"], r["style"], v.reason))
    P = sum(r["poisoned"] for r in rows); B = len(rows) - P
    print(f"\nContext firewall only | Prompt Guard: {'ON' if prompt_guard_enabled() else 'off (heuristics only)'}")
    print(f"Poisoned chunks quarantined: {tp}/{P} ({100 * tp / P:.0f}%)")
    print(f"Benign chunks quarantined (false positives): {fp}/{B}")
    for m in missed: print("  MISSED", m)
    for f in falsepos: print("  FALSE POSITIVE", f)
    print(f"Latency mean {sum(lat) / len(lat):.1f} ms | max {max(lat):.1f} ms")
    if args.sweep:
        if prompt_guard_enabled():
            sweep(rows)
        else:
            print("\n--sweep needs Prompt Guard ON (Groq base URL, PROMPT_GUARD not off)")
    print("\nYour real documents:")
    for d in load_docs():
        v, _ = context.run(d["text"], {"kind": "document"})
        print(f"  {d['source']:<28}{'QUARANTINED' if v.action == 'block' else 'ok'}   {v.reason if v.action == 'block' else ''}")


if __name__ == "__main__":
    main()

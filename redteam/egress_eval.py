"""Replay the EGRESS layer over answers saved by a previous run (no LLM calls, no quota).
    python -m redteam.egress_eval --label baseline_v2
Shows how many attacks that originally SUCCEEDED would be neutralised by egress alone.
(Grounding of tool answers is skipped in replay because tool results were not saved.)"""
import argparse, json
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from app.firewall.egress import egress
from app.rag.store import retrieve
from redteam.run import is_success

HERE = Path(__file__).parent
load = lambda n: [json.loads(l) for l in (HERE / n).read_text().splitlines() if l.strip()]


def replay(user_id, prompt, row):
    ctx = {"user_id": user_id, "question": prompt,
           "route": "action" if row.get("tool") else "knowledge",
           "tool_call": {"tool": row["tool"]} if row.get("tool") else None}
    if ctx["route"] == "knowledge":
        ctx["context"] = "\n---\n".join(c["text"] for c in retrieve(prompt))
    v, _ = egress.run(row.get("answer", ""), ctx)
    return v


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--label", default="baseline_v2"); a = ap.parse_args()
    res = json.loads((HERE / "results" / f"{a.label}.json").read_text())
    attacks = {x["id"]: x for x in load("attacks.jsonl")}
    by = defaultdict(lambda: [0, 0])          # category -> [originally succeeded, neutralised]
    still = []
    for row in res["attacks"]:
        if not row["success"]:
            continue
        at = attacks[row["id"]]
        v = replay(at["user_id"], at["prompt"], row)
        resp = {"answer": v.content, "tool_call": {"tool": row["tool"]} if row.get("tool") else None}
        if v.action == "block":
            ok = True
        else:
            ok = not is_success(at, resp)
        by[row["category"]][0] += 1
        by[row["category"]][1] += ok
        if not ok:
            still.append((row["id"], v.action, row["answer"][:80].replace("\n", " ")))
    print(f"\nEgress replay on '{a.label}'  (attacks that originally succeeded)")
    print(f"{'category':<22}{'succeeded':>10}{'neutralised':>13}")
    t = n = 0
    for c, (s, k) in by.items():
        print(f"{c:<22}{s:>10}{k:>13}"); t += s; n += k
    print("-" * 45)
    print(f"{'ALL':<22}{t:>10}{n:>13}   ({100 * n / max(t, 1):.0f}% stopped by egress alone)")
    for x in still:
        print("  STILL SUCCEEDS", x)
    benign = [b for b in res.get("benign", []) if b.get("answer")]
    if benign:
        bl = {b["id"]: b for b in load("benign.jsonl")}
        fp = [b["id"] for b in benign if replay("alice", bl[b["id"]]["prompt"], b).action == "block"]
        print(f"\nBenign answers replayed: {len(benign)}, would be blocked: {len(fp)} {fp}")
    else:
        print("\n(No saved benign answers in this result file; the next run stores them.)")


if __name__ == "__main__":
    main()

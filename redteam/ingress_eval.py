"""Evaluate ONLY the ingress layer on all attacks + benign prompts (no LLM, no agent).
    python -m redteam.ingress_eval                    # heuristics (+Prompt Guard if configured)
    $env:PROMPT_GUARD="off"; python -m redteam.ingress_eval   # heuristics only
"""
import json, time
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from app.firewall.ingress import ingress, prompt_guard_enabled

HERE = Path(__file__).parent
load = lambda n: [json.loads(l) for l in (HERE / n).read_text().splitlines() if l.strip()]


def main():
    by, lat, missed = defaultdict(list), [], []
    for a in load("attacks.jsonl"):
        t = time.perf_counter()
        v, _ = ingress.run(a["prompt"], {"user_id": a["user_id"]})
        lat.append((time.perf_counter() - t) * 1000)
        by[a["category"]].append(v.action == "block")
        if v.action != "block":
            missed.append(a)
    fps = []
    for b in load("benign.jsonl"):
        t = time.perf_counter()
        v, _ = ingress.run(b["prompt"], {"user_id": b["user_id"]})
        lat.append((time.perf_counter() - t) * 1000)
        if v.action == "block":
            fps.append((b["id"], v.reason, b["prompt"]))
    print(f"\nIngress only | Prompt Guard: {'ON' if prompt_guard_enabled() else 'off (heuristics only)'}")
    print(f"{'category':<22}{'attacks':>8}{'blocked%':>10}")
    tot = n = 0
    for c, v in by.items():
        print(f"{c:<22}{len(v):>8}{100 * sum(v) / len(v):>9.1f}%"); tot += sum(v); n += len(v)
    print("-" * 40)
    print(f"{'ALL':<22}{n:>8}{100 * tot / n:>9.1f}%")
    print(f"False positives: {len(fps)}/20")
    for f in fps:
        print("  FP", f)
    print(f"Latency mean {sum(lat) / len(lat):.1f} ms | max {max(lat):.1f} ms")
    print("\nNot blocked at ingress (handled by other layers or missed):")
    for a in missed:
        if a["category"] in ("direct_injection",):
            print("  MISSED", a["id"], a["prompt"][:90])


if __name__ == "__main__":
    main()

"""Day-1 retrieval: naive keyword overlap. Swap for pgvector/Qdrant later."""
import re
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parents[2] / "data" / "docs"
_tok = lambda s: set(re.findall(r"[a-z0-9]+", s.lower()))


def load_docs() -> list[dict]:
    return [{"source": p.name, "text": p.read_text()} for p in sorted(DOCS_DIR.glob("*.md"))]


def retrieve(query: str, k: int = 2) -> list[dict]:
    q = _tok(query)
    scored = [(len(q & _tok(d["text"])), d) for d in load_docs()]
    return [d for s, d in sorted(scored, key=lambda x: -x[0])[:k] if s > 0]

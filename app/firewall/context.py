"""Layer 3: CONTEXT FIREWALL. Everything the model READS that the user did not type (retrieved
documents, tool outputs) is untrusted data. A chunk that looks like an instruction is quarantined
before the model ever sees it.  heuristics (raw text) -> strip hidden content -> Prompt Guard 2."""
import hashlib, re, unicodedata
from .base import Pipeline, Verdict
from .policy import get_policy
from .ingress import PromptGuard, prompt_guard_enabled, heuristic_score, _ZW

# instructions aimed at an AI that sit inside DATA
CONTEXT_HEURISTICS = [
    (0.95, r"(?:system|assistant|ai|llm|model)\s*(?:note|instruction|message|prompt)s?\s*(?:to|for)\s+(?:the\s+)?(?:assistant|ai|model|llm)"),
    (0.9,  r"(?:call|invoke|run|execute|use)\s+(?:the\s+)?(?:reset_access|lookup_employee|create_ticket)\b"),
    (0.85, r"(?:tell|inform|notify)\s+the\s+user\s+(?:that|their)"),
    (0.8,  r"do\s+not\s+(?:tell|mention|reveal|disclose)\s+(?:this|the\s+user|anyone)"),
    (0.8,  r"(?:assistant|ai|chatbot|llm)\s*[:,]\s*(?:you\s+(?:must|should|will)|please)"),
    (0.8,  r"(?:email|send|forward|post)\s+(?:all\s+|the\s+)?(?:employee|customer|user|salary|personal)\s+(?:records|data|details|information)\s+to\b"),
]
_CTX = [(w, re.compile(p, re.I | re.S)) for w, p in CONTEXT_HEURISTICS]


def _clean(text: str) -> str:
    return _ZW.sub("", unicodedata.normalize("NFKC", text))


def context_score(text: str) -> tuple[float, str]:
    t = _clean(text)
    best, why = heuristic_score(t)
    for w, rx in _CTX:
        if w > best and rx.search(t):
            best, why = w, rx.pattern[:50]
    return best, why


class ContextHeuristics:
    name = "context.heuristics"
    def check(self, content, ctx):
        score, why = context_score(content)
        if score >= get_policy()["context"]["block_score"]:
            return Verdict("block", content, "instruction hidden in data", score, meta={"pattern": why})
        return Verdict("allow", content, "no known pattern", score)


_HIDDEN = [
    ("html_comment",   re.compile(r"<!--.*?-->", re.S)),
    ("md_comment",     re.compile(r"\[//\]:\s*#\s*\(.*?\)", re.S)),
    ("script_style",   re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.S | re.I)),
    ("hidden_element", re.compile(r"<([a-z0-9]+)\b[^>]*(?:display\s*:\s*none|visibility\s*:\s*hidden|\bhidden\b)[^>]*>.*?</\1\s*>", re.S | re.I)),
]


class StripHidden:
    """Invisible content (comments, hidden elements, zero-width chars) is removed; the model only reads what a human sees."""
    name = "context.striphidden"
    def check(self, content, ctx):
        out, found = content, {}
        for label, rx in _HIDDEN:
            out, n = rx.subn("", out)
            if n:
                found[label] = n
        out2 = _ZW.sub("", out)
        if out2 != out:
            found["zero_width"] = 1
        if found:
            return Verdict("modify", out2, "removed hidden content: " + ", ".join(f"{k} x{v}" for k, v in found.items()), 0.5, meta=found)
        return Verdict("allow", content, "ok")


class ChunkPromptGuard(PromptGuard):
    """Prompt Guard 2 on documents. Results are cached per chunk, so a static corpus is scanned once.
    Skipped for tool outputs (our own backend; user text was screened at ingress). FAIL-CLOSED on errors."""
    name = "context.promptguard"
    _cache: dict = {}

    def _windows(self, text, size=1500, overlap=200):
        return [text[i:i + size] for i in range(0, max(len(text), 1), size - overlap)]

    def check(self, content, ctx):
        if ctx.get("kind") == "tool_output" or not prompt_guard_enabled():
            return Verdict("allow", content, "classifier skipped", 0.0)
        key = hashlib.sha256(content.encode()).hexdigest()
        if key not in ChunkPromptGuard._cache:
            ChunkPromptGuard._cache[key] = max(self._score(w) for w in self._windows(content))
        score = ChunkPromptGuard._cache[key]
        if score >= get_policy()["context"]["injection_threshold"]:
            return Verdict("block", content, "classifier: injection in data", score)
        return Verdict("allow", content, "classifier: clean", score)


context = Pipeline("context", [ContextHeuristics(), StripHidden(), ChunkPromptGuard()])

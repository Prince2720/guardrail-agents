"""Layer 1: INGRESS FIREWALL.
normalize -> PII redaction -> topic rails -> injection heuristics -> Prompt Guard 2 classifier."""
import hashlib, os, re, unicodedata
from .base import Pipeline, Verdict
from .policy import get_policy

# ------------------------------------------------------------------ normalize
_ZW = re.compile("[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class Normalize:
    """Defeats trivial obfuscation (zero-width chars, fullwidth letters) and oversize payloads."""
    name = "ingress.normalize"
    def check(self, content, ctx):
        if len(content) > get_policy()["ingress"]["max_chars"]:
            return Verdict("block", content, "message too long", 0.6)
        clean = _CTRL.sub("", _ZW.sub("", unicodedata.normalize("NFKC", content))).strip()
        if not clean:
            return Verdict("block", content, "empty message", 0.1)
        if clean != content:
            return Verdict("modify", clean, "normalized text", 0.1)
        return Verdict("allow", content, "ok")


# ------------------------------------------------------------------ PII
def _luhn(num: str) -> bool:
    d = [int(c) for c in num if c.isdigit()]
    if not 13 <= len(d) <= 19:
        return False
    s = 0
    for i, x in enumerate(reversed(d)):
        if i % 2:
            x = x * 2 - 9 if x * 2 > 9 else x * 2
        s += x
    return s % 10 == 0


# order matters: most specific first
PII_PATTERNS = [
    ("SECRET",      re.compile(r"(?i)\b(?:password|passwd|pwd|secret|token|api[_ -]?key)\s*[:=]\s*\S+"), None),
    ("API_KEY",     re.compile(r"\b(?:sk|gsk|xai|ghp|AKIA)[-_A-Za-z0-9]{16,}\b"), None),
    ("EMAIL",       re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), None),
    ("CREDIT_CARD", re.compile(r"(?<![\d-])(?:\d[ -]?){13,19}(?![\d-])"), _luhn),
    ("SSN",         re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), None),
    ("AADHAAR",     re.compile(r"(?<!\d)\d{4}[ -]\d{4}[ -]\d{4}(?!\d)"), None),
    ("PAN",         re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), None),
    ("PHONE",       re.compile(r"(?<![\d-])(?:\+91[ -]?)?[6-9]\d{9}(?!\d)|(?<![\d-])(?:\+?1[ -]?)?(?:\(\d{3}\)|\d{3})[ -]?\d{3}[ -]?\d{4}(?!\d)"), None),
]


def redact_pii(text: str, skip: tuple = ()) -> tuple[str, dict]:
    found: dict = {}
    for label, rx, validator in PII_PATTERNS:
        if label in skip:
            continue
        def sub(m, label=label, validator=validator):
            if validator and not validator(m.group(0)):
                return m.group(0)
            found[label] = found.get(label, 0) + 1
            return f"<{label}>"
        text = rx.sub(sub, text)
    return text, found


class PIIRedactor:
    name = "ingress.pii"
    def check(self, content, ctx):
        clean, found = redact_pii(content)
        if not found:
            return Verdict("allow", content, "no PII")
        summary = ", ".join(f"{k} x{v}" for k, v in sorted(found.items()))
        return Verdict("modify", clean, f"redacted: {summary}", 0.3, meta={"pii": found})


# ------------------------------------------------------------------ topic rails
class TopicRails:
    name = "ingress.topics"
    def check(self, content, ctx):
        for t in get_policy()["ingress"]["blocked_topics"]:
            if re.search(t["pattern"], content, re.I | re.S):
                return Verdict("block", content, f"blocked topic: {t['name']}", 0.9)
        return Verdict("allow", content, "ok")


# ------------------------------------------------------------------ injection heuristics
HEURISTICS = [
    (0.95, r"ignor\w*\s+(?:all\s+|any\s+|the\s+|your\s+)*(?:previous|prior|above|earlier|preceding|precedent\w*|anterior\w*)\s+(?:instructions?|rules|prompts?|directives?|consignes|instrucciones|anweisungen)"),
    (0.9,  r"(?:disregard|forget|override|bypass)\s+(?:all\s+|any\s+|your\s+|the\s+)*(?:previous\s+|prior\s+|above\s+)?(?:instructions?|rules|guidelines|programming|restrictions|safety)"),
    (0.9,  r"(?:reveal|print|show|repeat|output|display|leak|dump)\s+.{0,30}(?:system\s+prompt|initial\s+prompt|hidden\s+instructions|your\s+instructions|your\s+rules)"),
    (0.85, r"repeat\s+(?:the\s+)?(?:text|words|everything|content)\s+above"),
    (0.9,  r"you\s+are\s+now\s+(?:an?\s+)?(?:unrestricted|unfiltered|jailbroken|uncensored|dan\b)"),
    (0.9,  r"\bdan\b.{0,60}(?:no\s+restrictions|without\s+restrictions|unrestricted)"),
    (0.85, r"(?:developer|debug|god|admin|sudo)\s+mode\s+(?:enabled|on|activated)"),
    (0.85, r"\bjailbreak"),
    (0.9,  r"(?:system\s+override|new\s+system\s+message|#{2,}\s*new\s+instructions|\[\s*system\s*\])"),
    (0.8,  r"</?\s*(?:system|assistant|context|instructions?)\s*>"),
    (0.9,  r"(?:disable|turn\s+off|remove|ignore)\s+(?:all\s+)?(?:safety|security|guardrails?|filters?|safeguards?|content\s+polic\w+)"),
    (0.85, r"(?:act|behave|respond)\s+as\s+.{0,40}(?:without|with\s+no)\s+(?:any\s+)?(?:restrictions|filters|limits|rules)"),
    (0.8,  r"as\s+the\s+system\s+administrator.{0,40}(?:authori[sz]e|disable|override)"),
    (0.8,  r"(?:say|reply|respond|output|write)\s+(?:only\s+|exactly\s+)?(?:with\s+)?(?:the\s+word\s+)?['\"]?pwned"),
    (0.8,  r"do\s+what\s+the\s+quoted\s+text\s+says"),
    (0.7,  r"(?:pretend|imagine)\s+(?:you\s+)?(?:are|have)\s+no\s+(?:rules|restrictions|limits)"),
]
_COMPILED = [(w, re.compile(p, re.I | re.S)) for w, p in HEURISTICS]


def heuristic_score(text: str) -> tuple[float, str]:
    best, why = 0.0, ""
    for w, rx in _COMPILED:
        if w > best and rx.search(text):
            best, why = w, rx.pattern[:50]
    return best, why


class InjectionHeuristics:
    name = "ingress.heuristics"
    def check(self, content, ctx):
        score, why = heuristic_score(content)
        if score >= get_policy()["ingress"]["heuristic_block_score"]:
            return Verdict("block", content, "prompt-injection pattern", score, meta={"pattern": why})
        return Verdict("allow", content, "no known pattern", score)


# ------------------------------------------------------------------ Prompt Guard 2 (Groq)
def prompt_guard_enabled() -> bool:
    mode = os.getenv("PROMPT_GUARD", "auto").strip().lower()
    if mode in ("off", "0", "false", "no"):
        return False
    if mode in ("on", "1", "true", "yes"):
        return True
    return os.getenv("LLM_PROVIDER", "mock").lower() == "openai" and "groq" in (os.getenv("OPENAI_BASE_URL") or "").lower()


class PromptGuard:
    """Meta Llama Prompt Guard 2 via Groq: returns P(malicious) as a bare float. FAIL-CLOSED on any error."""
    name = "ingress.promptguard"
    _client = None

    def _score(self, text: str) -> float:
        """Cached on disk when LLM_CACHE is on (same file as the LLM cache): a repeated text costs no network call."""
        from app import llm
        if not llm._cache_on():
            return self._score_remote(text)
        key = hashlib.sha256(f"pg|{os.getenv('PROMPT_GUARD_MODEL', 'default')}|{text}".encode()).hexdigest()
        hit = llm._cache_get(key)
        if hit is not None:
            return float(hit)
        val = self._score_remote(text)
        llm._cache_put(key, val)
        return val

    def _score_remote(self, text: str) -> float:
        from openai import OpenAI
        if PromptGuard._client is None:
            PromptGuard._client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None, timeout=15, max_retries=2)
        r = PromptGuard._client.chat.completions.create(
            model=os.getenv("PROMPT_GUARD_MODEL", "meta-llama/llama-prompt-guard-2-86m"),
            messages=[{"role": "user", "content": text}])
        return float(r.choices[0].message.content.strip())

    def check(self, content, ctx):
        if not prompt_guard_enabled():
            return Verdict("allow", content, "classifier off", 0.0)
        score = self._score(content)            # exceptions propagate -> Pipeline blocks (fail closed)
        if score >= get_policy()["ingress"]["injection_threshold"]:
            return Verdict("block", content, "classifier: injection/jailbreak", score)
        return Verdict("allow", content, "classifier: clean", score)


ingress = Pipeline("ingress", [Normalize(), PIIRedactor(), TopicRails(), InjectionHeuristics(), PromptGuard()])

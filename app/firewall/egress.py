"""Layer 5: EGRESS FIREWALL.
prompt-leak -> DLP (secrets, protected fields, PII) -> action-claim check -> grounding check.
FAIL-CLOSED: any guard error blocks the response."""
import json, re
from .base import Pipeline, Verdict
from .policy import get_policy, role_of
from .ingress import redact_pii
from app.agents.tools import EMPLOYEES


def _norm(t: str) -> str:
    return str(t).replace("\u2019", "'").replace("\u2018", "'").replace("\u2011", "-")


# ------------------------------------------------------------------ numbers
_NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?(?:\s?[kK])?(?![\w])")
_ENUM = [
    re.compile(r"(?m)^[ \t]*(?:[-*>|#]+[ \t]*)*\**[ \t]*\(?\d{1,2}[.):\]]\**[ \t]+"),                          # "1. ", "**1.** ", "| 1 |", "1) "
    re.compile(r"(?i)\b(?:step|phase|stage|option|part|point|item|tip|rule|method)s?\s*#?\d{1,2}\b"),         # "Step 1"
    re.compile(r"\([1-9]\)"),                                                                                  # "(1)"
    re.compile(r"(?m)^[ \t]*\|[ \t]*\d{1,2}[ \t]*(?=\|)"),                                                      # first cell of a table row: "| 1 |"
    re.compile(r"[0-9]\ufe0f?\u20e3"),                                                                         # keycap emoji
]                                                                                                              # enumerations are labels, not claims


def _val(raw: str):
    raw = raw.strip().lstrip("$")
    k = raw.lower().endswith("k")
    raw = raw.rstrip("kK").strip().replace(",", "")
    try:
        v = float(raw)
    except ValueError:
        return None
    return round(v * 1000 if k else v, 2)


def numbers(text: str) -> set:
    text = _norm(text)
    for rx in _ENUM:
        text = rx.sub(" ", text)
    return {v for v in (_val(m.group(0)) for m in _NUM.finditer(text)) if v is not None}


_DOMAIN = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|in|co|gov|edu)\b", re.I)


# ------------------------------------------------------------------ guards
class PromptLeak:
    name = "egress.promptleak"
    def check(self, content, ctx):
        low = _norm(content).lower()
        for frag in get_policy()["egress"]["prompt_canaries"]:
            if frag.lower() in low:
                return Verdict("block", content, "system prompt leakage", 0.95)
        return Verdict("allow", content, "ok")


class DLP:
    name = "egress.dlp"
    def check(self, content, ctx):
        pol = get_policy()["egress"]
        user = (ctx.get("user_id") or "").lower()
        role = role_of(user)

        tr = ctx.get("tool_result")                                   # 1) secrets returned by tools never go out
        if isinstance(tr, dict):
            for f in pol["secret_fields"]:
                if tr.get(f) and str(tr[f]) in content:
                    return Verdict("block", content, f"secret field '{f}' in response", 1.0)

        counts: dict = {}
        def bump(k): counts[k] = counts.get(k, 0) + 1

        out, found = redact_pii(content, skip=("EMAIL",))              # 2) generic PII / secrets
        if "SECRET" in found or "API_KEY" in found:
            return Verdict("block", content, "secret or API key in response", 1.0)
        for k, n in found.items():
            counts[k] = counts.get(k, 0) + n

        prot = pol["protected"]                                        # 3) protected employee fields
        def may_see(field, key):
            spec = prot[field]
            return role in spec["viewers"] or (spec.get("self_ok") and key == user)
        hidden_salaries = {float(e["salary"]) for k, e in EMPLOYEES.items() if not may_see("salary", k)}
        allowed_emails = {e["email"].lower() for k, e in EMPLOYEES.items() if may_see("email", k)}

        def sal(m):
            v = _val(_norm(m.group(0)))
            if v in hidden_salaries:
                bump("salary"); return "[REDACTED]"
            return m.group(0)
        out = _NUM.sub(sal, out)

        def mail(m):
            if m.group(0).lower() in allowed_emails:
                return m.group(0)
            bump("email"); return "[REDACTED]"
        out = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", mail, out)

        if counts:
            summary = ", ".join(f"{k} x{v}" for k, v in sorted(counts.items()))
            return Verdict("modify", out, f"redacted: {summary}", 0.6, meta={"dlp": counts})
        return Verdict("allow", content, "clean")


_V = r"reset|unlocked|granted|revoked|disabled|created|opened|deleted"
_CLAIMS = [
    re.compile(r"\bI(?:'ve|\s+have|\s+had|\s+just|\s+successfully)?\s+(?P<verb>" + _V + r"|approved)\b", re.I),            # I have reset ...
    re.compile(r"\b(?:has|have|was|were)\s+been\s+(?:successfully\s+)?(?P<verb>" + _V + r")\b", re.I),                       # has been reset
    re.compile(r"\b(?P<verb>" + _V + r")\b[^.\n]{0,60}\b(?:has|have|was|were)\s+been\s+(?:successfully\s+)?(?:completed|done|processed|performed|applied)\b", re.I),  # Reset access for X has been completed
    re.compile(r"\b(?:access|password)\s+(?P<verb>reset)\s+(?:completed|successful|done)\b", re.I),                          # access reset completed
    re.compile(r"\b(?P<verb>reset|unlocked|created)\s+successfully\b", re.I),                                                  # reset successfully
]
_VERB_TOOL = {"reset": "reset_access", "unlocked": "reset_access", "granted": "reset_access", "revoked": "reset_access",
              "disabled": "reset_access", "approved": "reset_access", "created": "create_ticket", "opened": "create_ticket"}
_TOOLSYNTAX = re.compile(r'"(?:tool|name)"\s*:\s*"(?:reset_access|lookup_employee|create_ticket)"', re.I)


class ActionClaims:
    """The model must not claim an action that did not actually run, nor emit raw tool-call syntax
    (both are classic symptoms of an injected instruction)."""
    name = "egress.actionclaims"
    def check(self, content, ctx):
        if not get_policy()["egress"].get("action_claims"):
            return Verdict("allow", content, "off")
        text = _norm(content)
        if _TOOLSYNTAX.search(text.replace('\\"', '"')):
            return Verdict("block", content, "raw tool-call syntax in answer", 0.9)
        ran = (ctx.get("tool_call") or {}).get("tool")
        for rx in _CLAIMS:
            for m in rx.finditer(text):
                if _VERB_TOOL.get(m.group("verb").lower()) != ran:
                    return Verdict("block", content, f"claims an action that did not run: '{m.group(0)[:40]}'", 0.9)
        return Verdict("allow", content, "ok")


class Grounding:
    """Numbers and domains in an answer must appear in its sources (retrieved docs, tool result, or the question)."""
    name = "egress.grounding"
    def check(self, content, ctx):
        if not get_policy()["egress"]["grounding"]["enabled"]:
            return Verdict("allow", content, "off")
        if ctx.get("route") == "action":
            if "tool_result" not in ctx:
                return Verdict("allow", content, "no tool result to ground against")
            source = json.dumps(ctx["tool_result"]) if ctx.get("tool_result") is not None else ""
        else:
            source = ctx.get("context", "")
        allowed = _norm(source) + " " + _norm(ctx.get("question") or "")
        years = {float(y) for y in range(1990, 2101)}
        bad_nums = numbers(content) - numbers(allowed) - years
        bad_domains = {d.lower() for d in _DOMAIN.findall(_norm(content))} - {d.lower() for d in _DOMAIN.findall(allowed)}
        if bad_nums or bad_domains:
            what = sorted(bad_nums | bad_domains, key=str)[:4]
            return Verdict("block", content, f"ungrounded specifics: {what}", 0.85)
        return Verdict("allow", content, "grounded")


egress = Pipeline("egress", [PromptLeak(), DLP(), ActionClaims(), Grounding()])

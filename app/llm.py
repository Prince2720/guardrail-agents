"""Provider-agnostic LLM call with token accounting, reasoning-effort control and an optional
record/replay cache. Falls back to a deterministic mock so the project runs with no API key."""
import hashlib, json, os, re, threading, time
from contextlib import contextmanager
from contextvars import ContextVar

USAGE = {"prompt": 0, "completion": 0, "calls": 0, "cached": 0}
_lock = threading.Lock()
_cache: dict = {}
_cache_file = None
_NO_EFFORT = False          # set if the provider rejects reasoning_effort


def _cache_on() -> bool:
    return os.getenv("LLM_CACHE", "off").strip().lower() in ("on", "1", "true", "yes")


def _cache_get(key):
    global _cache, _cache_file
    path = os.getenv("LLM_CACHE_PATH", ".llm_cache.jsonl")
    with _lock:
        if _cache_file != path:                      # (re)load when the path changes
            _cache, _cache_file = {}, path
            if os.path.exists(path):
                for line in open(path, encoding="utf-8"):
                    try:
                        d = json.loads(line); _cache[d["k"]] = d["v"]
                    except Exception:
                        pass
        return _cache.get(key)


def _cache_put(key, val):
    with _lock:
        _cache[key] = val
        with open(_cache_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"k": key, "v": val}) + "\n")


# Request-scoped replay: inside `replay_scope()` an identical prompt gets the identical reply. The public demo's
# "Compare" runs one request twice (firewall off, then on); without this, the model's randomness could send the two
# runs down different paths and the comparison would not be about the firewall at all.
_REPLAY: ContextVar = ContextVar("llm_replay", default=None)


@contextmanager
def replay_scope():
    tok = _REPLAY.set({})
    try:
        yield
    finally:
        _REPLAY.reset(tok)


def complete(system: str, user: str, max_tokens: int = 900) -> str:
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    model = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    effort = os.getenv("LLM_REASONING_EFFORT", "low")
    key = hashlib.sha256(f"{provider}|{model}|{effort}|{max_tokens}|{system}|{user}".encode()).hexdigest()
    scope = _REPLAY.get()
    if scope is not None and key in scope:
        USAGE["cached"] += 1
        return scope[key]
    out = None
    if provider in ("anthropic", "openai") and _cache_on():
        hit = _cache_get(key)
        if hit is not None:
            USAGE["cached"] += 1
            out = hit
        else:
            out = _call(provider, model, system, user, max_tokens)
            _cache_put(key, out)
    else:
        out = _call(provider, model, system, user, max_tokens)
    if scope is not None:
        scope[key] = out
    return out


def _call(provider, model, system, user, max_tokens):
    if provider == "anthropic":
        import anthropic
        r = anthropic.Anthropic().messages.create(model=model, max_tokens=max_tokens, system=system,
                                                  messages=[{"role": "user", "content": user}])
        _count(getattr(r.usage, "input_tokens", 0), getattr(r.usage, "output_tokens", 0))
        return r.content[0].text
    if provider == "openai":     # also Gemini / Groq / Ollama via OPENAI_BASE_URL
        return _openai_call(model, system, user, max_tokens)
    return _mock(system, user)


def _count(p, c):
    with _lock:
        USAGE["prompt"] += p or 0
        USAGE["completion"] += c or 0
        USAGE["calls"] += 1


def _openai_call(model, system, user, max_tokens):
    global _NO_EFFORT
    from openai import OpenAI
    client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None)
    for attempt in range(6):
        kwargs = {}
        effort = os.getenv("LLM_REASONING_EFFORT", "low")
        if "gpt-oss" in model and effort and not _NO_EFFORT:
            kwargs["extra_body"] = {"reasoning_effort": effort}      # far fewer hidden thinking tokens
        try:
            r = client.chat.completions.create(
                model=model, max_tokens=max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kwargs)
            u = getattr(r, "usage", None)
            _count(getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))
            return r.choices[0].message.content or ""
        except Exception as e:
            msg = str(e)
            b = getattr(e, "body", None) or {}
            if isinstance(b, dict):
                b = b.get("error", b)
            fg = b.get("failed_generation") if isinstance(b, dict) else None
            if fg:                                   # model wrapped its answer as a tool call; keep the text
                return fg
            if "reasoning_effort" in msg and not _NO_EFFORT:
                _NO_EFFORT = True                    # provider doesn't support it: retry without
                continue
            if "PerDay" in msg or "per day" in msg.lower() or "(TPD)" in msg:
                raise RuntimeError("DAILY_QUOTA_EXHAUSTED: " + msg[:600])      # retrying is pointless
            if "429" in msg and attempt < 5:         # per-minute limit: back off and retry
                time.sleep(15 * (attempt + 1))
                continue
            raise


def _mock(system: str, user: str) -> str:
    u = user.lower()
    if "knowledge or action" in system:
        return "action" if re.search(r"ticket|reset|lookup|employee|salary|password|access", u) else "knowledge"
    if "Reply ONLY with JSON" in system:
        m = re.search(r"employee\s+(\w+)|salary of (\w+)|about (\w+)", u)
        if "reset" in u:
            who = re.search(r"(?:for|of)\s+(\w+)", u)
            return '{"tool":"reset_access","args":{"username":"%s"}}' % (who.group(1) if who else "unknown")
        if "ticket" in u:
            return '{"tool":"create_ticket","args":{"title":"User request","description":"%s"}}' % user[:80].replace('"', "'")
        name = (m.group(1) or m.group(2) or m.group(3)) if m else "unknown"
        return '{"tool":"lookup_employee","args":{"name":"%s"}}' % name
    return "[mock answer] " + user[-300:]

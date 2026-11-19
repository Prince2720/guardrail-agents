"""Common interface for every firewall layer."""
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal, Protocol

Action = Literal["allow", "block", "modify"]


LAYERS = ("ingress", "context", "tools", "egress")
# Per-request override (used by the public demo). A ContextVar belongs to ONE request, so a visitor
# switching the firewall off can never affect anyone else. None = follow the environment.
_OVERRIDE: ContextVar = ContextVar("firewall_override", default=None)


@contextmanager
def firewall_override(value):
    tok = _OVERRIDE.set(value)
    try:
        yield
    finally:
        _OVERRIDE.reset(tok)


def firewall_state() -> str:
    return "on" if any(layer_enabled(l) for l in LAYERS) else "off"


def layer_enabled(layer: str) -> bool:
    """FIREWALL_ENABLED=false turns everything off (vulnerable baseline).
    FIREWALL_LAYERS=tools,egress enables only some layers (ablation studies).
    A per-request override (True/False) wins over the environment."""
    ov = _OVERRIDE.get()
    if ov is not None:
        return bool(ov)
    if os.getenv("FIREWALL_ENABLED", "true").strip().lower() in ("0", "false", "off", "no"):
        return False
    layers = os.getenv("FIREWALL_LAYERS", "all").strip().lower()
    return layers in ("", "all") or layer in [x.strip() for x in layers.split(",")]


@dataclass
class Verdict:
    action: Action = "allow"
    content: str = ""          # (possibly modified) content to pass on
    reason: str = ""
    score: float = 0.0         # 0..1 risk
    guard: str = ""
    meta: dict = field(default_factory=dict)


class Guard(Protocol):
    name: str
    def check(self, content: str, ctx: dict) -> Verdict: ...


class Pipeline:
    """Runs guards in order. FAIL-CLOSED: any guard exception => block."""
    def __init__(self, layer: str, guards: list):
        self.layer, self.guards = layer, guards

    def run(self, content: str, ctx: dict | None = None) -> tuple[Verdict, list[Verdict]]:
        if not layer_enabled(self.layer):
            return Verdict("allow", content, "layer disabled", 0.0, self.layer), []
        ctx, trail = ctx or {}, []
        for g in self.guards:
            try:
                v = g.check(content, ctx)
            except Exception as e:  # fail closed
                v = Verdict("block", content, f"guard error: {e}", 1.0, getattr(g, "name", "?"))
            v.guard = v.guard or g.name
            trail.append(v)
            if v.action == "block":
                return v, trail
            if v.action == "modify":
                content = v.content
        return Verdict("allow", content, "passed all guards", 0.0, self.layer), trail


class PassThrough:
    """Stub guard. Replaced by real guards on later days."""
    def __init__(self, name): self.name = name
    def check(self, content, ctx): return Verdict("allow", content, "stub", 0.0, self.name)

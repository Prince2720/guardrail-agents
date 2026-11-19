import hashlib, hmac, json, os, re, time, uuid
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

load_dotenv()
from app import approvals, firewall, llm      # noqa: E402
from app.agents.graph import graph            # noqa: E402
from app.api import limits                    # noqa: E402
from app.audit import log as audit            # noqa: E402
from app.audit.log import record              # noqa: E402
from app.audit.metrics import compute, quarantine_queue   # noqa: E402
from app.api.dashboard import HTML            # noqa: E402
from app.api.demo_page import HTML as DEMO_HTML   # noqa: E402
from app.firewall.base import firewall_override, firewall_state   # noqa: E402
from app.firewall.policy import get_policy    # noqa: E402


def is_production() -> bool:
    return os.getenv("APP_ENV", "dev").strip().lower() == "production"


def check_production_config():
    """FAIL CLOSED: a production instance refuses to start with an unsafe configuration."""
    if not is_production():
        return
    if len(os.getenv("ADMIN_TOKEN", "")) < 24:
        raise RuntimeError("APP_ENV=production requires ADMIN_TOKEN of at least 24 characters")
    if os.getenv("FIREWALL_ENABLED", "true").strip().lower() in ("0", "false", "off", "no"):
        raise RuntimeError("APP_ENV=production requires FIREWALL_ENABLED=true (visitors use the per-request switch)")


@asynccontextmanager
async def lifespan(_app):
    check_production_config()
    yield


app = FastAPI(title="Guardrail Agents", lifespan=lifespan,
              docs_url=None if is_production() else "/docs", redoc_url=None,
              openapi_url=None if is_production() else "/openapi.json")
DEMO = {"enabled": True}                     # kill switch (in memory; POST /admin/demo/off|on)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith(("/webhook", "/demo", "/metrics", "/audit", "/approvals", "/quarantine", "/admin")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


class ChatIn(BaseModel):
    user_id: str = Field(max_length=64)
    message: str = Field(max_length=4000)


class DemoIn(BaseModel):
    persona: str = Field(max_length=32)
    message: str = Field(min_length=1, max_length=2000)
    firewall: bool = True


def verify_signature(body: bytes, sig: str | None):
    secret = os.getenv("WEBHOOK_SECRET")
    if not secret:
        if is_production():
            raise HTTPException(503, "webhook disabled: WEBHOOK_SECRET not set")   # fail closed in production
        return                                                                      # optional in dev
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not sig or not hmac.compare_digest(expected, sig):
        raise HTTPException(401, "invalid signature")


def admin_auth(token: str | None) -> str:
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(503, "admin endpoints disabled (ADMIN_TOKEN not set)")   # fail closed
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(401, "bad admin token")
    return "admin"


def _guards(trail):
    return [{"guard": t.guard, "action": t.action, "reason": t.reason, "score": round(t.score, 3)}
            for t in trail if t.action != "allow" or t.score > 0]


# ---------------------------------------------------------------- the pipeline (shared by webhook and demo)
def _process(user_id: str, message: str):
    rid, t0 = str(uuid.uuid4()), time.perf_counter()
    fw = firewall_state()
    decision = {}

    def done(resp, outcome, layer=None, reason=None, **extra):
        decision.update(outcome=outcome, layer=layer, reason=reason,
                        **{k: v for k, v in extra.items() if k in ("route", "redacted_in", "redacted_out", "quarantined")})
        record("request", request_id=rid, user_id=user_id, outcome=outcome, layer=layer, reason=reason, fw=fw,
               latency_ms=round((time.perf_counter() - t0) * 1000), **extra)
        return resp

    # HOOK 1: ingress firewall
    v, trail = firewall.ingress.run(message, {"user_id": user_id})
    red_in = sum(sum(t.meta.get("pii", {}).values()) for t in trail)
    record("ingress", request_id=rid, user_id=user_id, verdict=v.action, reason=v.reason, guards=_guards(trail))
    if v.action == "block":
        return done({"request_id": rid, "answer": "Request blocked by policy.", "blocked": v.reason},
                    "blocked", "ingress", v.reason, redacted_in=red_in), decision

    out = graph.invoke({"user_id": user_id, "user_input": v.content})
    nq = len(out.get("quarantined") or [])

    if out.get("blocked"):                       # blocked inside the agent graph (tool layer)
        record("blocked", request_id=rid, user_id=user_id, reason=out["blocked"],
               route=out.get("route"), approval_id=out.get("approval_id"))
        resp = {"request_id": rid, "answer": out.get("answer", ""), "blocked": out["blocked"]}
        if out.get("approval_id"):
            resp["approval_id"] = out["approval_id"]
        return done(resp, "approval_pending" if out.get("approval_id") else "blocked", out.get("blocked_layer", "tools"),
                    out["blocked"], route=out.get("route"), redacted_in=red_in, quarantined=nq), decision

    # HOOK 5: egress firewall
    ectx = {"user_id": user_id, "context": out.get("context", ""), "route": out.get("route"),
            "tool_call": out.get("tool_call"), "question": v.content}
    if out.get("tool_call"):
        ectx["tool_result"] = out.get("tool_result")
    ev, etrail = firewall.egress.run(out.get("answer", ""), ectx)
    red_out = sum(sum(t.meta.get("dlp", {}).values()) for t in etrail)
    record("egress", request_id=rid, user_id=user_id, verdict=ev.action, reason=ev.reason,
           route=out.get("route"), tool_call=out.get("tool_call"), guards=_guards(etrail))
    if ev.action == "block":
        record("escalation", request_id=rid, user_id=user_id, reason=ev.reason, kind="egress_block")
        return done({"request_id": rid, "answer": get_policy()["egress"]["fallback"], "blocked": ev.reason},
                    "blocked", "egress", ev.reason, route=out.get("route"), redacted_in=red_in, quarantined=nq), decision
    return done({"request_id": rid, "answer": ev.content, "route": out.get("route"), "tool_call": out.get("tool_call")},
                "answered", route=out.get("route"), redacted_in=red_in, redacted_out=red_out, quarantined=nq), decision


def process_chat(user_id: str, message: str, firewall_on: bool | None = None) -> dict:
    """firewall_on: None = follow the environment; True/False = this request only."""
    with firewall_override(firewall_on):
        return _process(user_id, message)[0]


def _demo_run(persona: str, message: str, firewall_on: bool) -> dict:
    with firewall_override(firewall_on):
        resp, decision = _process(persona, message)
    return {**resp, "firewall": "on" if firewall_on else "off", "decision": decision}


# ---------------------------------------------------------------- endpoints
@app.get("/health")
def health():
    return {"ok": True}


@app.post("/webhook/chat", openapi_extra={"requestBody": {
    "required": True, "content": {"application/json": {"schema": ChatIn.model_json_schema()}}}})
async def chat(req: Request, x_signature: str | None = Header(default=None)):
    body = await req.body()
    verify_signature(body, x_signature)
    data = ChatIn.model_validate_json(body)
    return await run_in_threadpool(process_chat, data.user_id, data.message)    # keep the event loop free


# ---------------------------------------------------------------- public demo
def _demo_guard(request: Request, cost: int):
    if not DEMO["enabled"] or os.getenv("DEMO_ENABLED", "true").strip().lower() in ("0", "false", "no", "off"):
        raise HTTPException(503, {"message": "The demo is switched off right now."})
    ok, why, retry = limits.check(limits.client_ip(request), cost)
    if not ok:
        raise HTTPException(429, {"message": why}, headers={"Retry-After": str(retry)})


def _persona(name: str) -> str:
    if name not in get_policy()["users"]:
        raise HTTPException(400, {"message": "unknown persona"})
    return name


def _tokens():
    return llm.USAGE["prompt"] + llm.USAGE["completion"]


@app.get("/", response_class=HTMLResponse)
def demo_page():
    return DEMO_HTML


@app.get("/demo/results")
def demo_results():
    """Measured results for the demo page (written by `python -m redteam.update_readme`)."""
    p = Path(os.getenv("RESULTS_SNAPSHOT") or Path(__file__).with_name("results_snapshot.json"))
    try:
        return {"available": True, **json.loads(p.read_text(encoding="utf-8"))}
    except Exception:
        return {"available": False}


@app.post("/demo/chat")
def demo_chat(body: DemoIn, request: Request):
    persona = _persona(body.persona)
    _demo_guard(request, 1)
    t0 = _tokens()
    out = _demo_run(persona, body.message, body.firewall)
    limits.add_tokens(_tokens() - t0)
    return out


@app.post("/demo/compare")
def demo_compare(body: DemoIn, request: Request):
    persona = _persona(body.persona)
    _demo_guard(request, 2)
    t0 = _tokens()
    with llm.replay_scope():                              # both sides reuse the model's replies: only the firewall differs
        off = _demo_run(persona, body.message, False)     # the unprotected system, on fake data
        on = _demo_run(persona, body.message, True)
    limits.add_tokens(_tokens() - t0)
    return {"off": off, "on": on}


@app.post("/admin/demo/{state}")
def demo_switch(state: str, x_admin_token: str | None = Header(default=None)):
    admin_auth(x_admin_token)                             # the kill switch
    if state not in ("on", "off"):
        raise HTTPException(404, "use on or off")
    DEMO["enabled"] = state == "on"
    record("demo_switch", state=state)
    return {"demo_enabled": DEMO["enabled"], **limits.status()}


# ---------------------------------------------------------------- governance
@app.get("/metrics")
def metrics():
    return compute()                              # aggregates only; no message content


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return HTML


@app.get("/audit")
def audit_events(limit: int = 100, event: str | None = None, x_admin_token: str | None = Header(default=None)):
    admin_auth(x_admin_token)
    return audit.all_events(limit=min(limit, 1000), event=event)


@app.get("/audit/verify")
def audit_verify():
    return audit.verify_chain()


@app.get("/approvals")
def list_approvals(status: str | None = None, x_admin_token: str | None = Header(default=None)):
    admin_auth(x_admin_token)
    return approvals.list_items(status)


@app.post("/approvals/{aid}/{decision}")
def decide_approval(aid: int, decision: str, x_admin_token: str | None = Header(default=None)):
    who = admin_auth(x_admin_token)
    if decision not in ("approve", "deny"):
        raise HTTPException(404, "use approve or deny")
    try:
        return approvals.decide(aid, who, decision == "approve")
    except KeyError:
        raise HTTPException(404, "no such approval")
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/quarantine")
def list_quarantine(x_admin_token: str | None = Header(default=None)):
    admin_auth(x_admin_token)
    return quarantine_queue()


@app.post("/quarantine/{h}/release")
def release_quarantine(h: str, x_admin_token: str | None = Header(default=None)):
    who = admin_auth(x_admin_token)
    if not re.fullmatch(r"[0-9a-f]{64}", h):
        raise HTTPException(400, "bad hash")
    audit.release(h, who)
    return {"released": h}

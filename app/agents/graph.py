import hashlib, json
from typing import TypedDict
from langgraph.graph import StateGraph, END

from app.llm import complete
from app.rag.store import retrieve
from app.agents.tools import REGISTRY
from app import firewall
from app.audit.log import record, is_released
from app.firewall.tools import filter_result


class State(TypedDict, total=False):
    user_id: str
    user_input: str
    route: str
    context: str
    tool_call: dict
    tool_result: dict
    answer: str
    blocked: str
    approval_id: int
    quarantined: list
    blocked_layer: str


def supervisor(s: State) -> State:
    r = complete("You route helpdesk requests. Reply with exactly one word: knowledge or action. "
                 "Use action ONLY when the user explicitly asks to create a ticket, look up an employee record, "
                 "or reset someone's access or password. Questions about how to do something, policies, VPN or setup are knowledge.", s["user_input"], max_tokens=400)
    return {"route": "action" if "action" in r.lower() else "knowledge"}


def knowledge_agent(s: State) -> State:
    safe, dropped = [], []
    for ch in retrieve(s["user_input"]):
        # HOOK 3: context firewall - every retrieved chunk is untrusted data
        h = hashlib.sha256(ch["text"].encode()).hexdigest()
        if is_released(h):                       # an admin reviewed this exact text and released it
            safe.append(ch["text"]); continue
        v, _ = firewall.context.run(ch["text"], {"source": ch["source"], "kind": "document"})
        if v.action == "block":
            dropped.append({"source": ch["source"], "reason": v.reason})
            record("quarantine", source=ch["source"], reason=v.reason, user_id=s.get("user_id"),
                   hash=h, snippet=ch["text"][:200])
        else:
            safe.append(v.content)
    if dropped and not safe:
        return {"answer": "I couldn't find a trusted source for that in the company documents.",
                "context": "", "quarantined": dropped}
    text = "\n---\n".join(safe)
    ans = complete("You are an internal IT/HR helpdesk assistant. Answer using the context.",
                   f"Context:\n{text}\n\nQuestion: {s['user_input']}")
    return {"context": text, "answer": ans, "quarantined": dropped}


def parse_tool_call(raw: str) -> dict | None:
    """Normalize whatever JSON shape the model produced into {"tool": ..., "args": {...}}.
    Handles: {"tool","args"}, {"name","arguments"} wrappers, arguments as a JSON string, flat args."""
    try:
        call = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except Exception:
        return None
    if not isinstance(call, dict):
        return None
    inner = call.get("arguments")
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except Exception:
            inner = None
    if isinstance(inner, dict):
        if "tool" in inner:                                            # {"name": <label>, "arguments": {"tool":..,"args":..}}
            call = inner
        elif "tool" not in call and call.get("name") in REGISTRY:      # {"name": <tool>, "arguments": {<args>}}
            call = {"tool": call["name"], "args": inner}
        elif "args" not in call:                                       # {"tool": <tool>, "arguments": {<args>}}
            call = {**call, "args": inner}
    if "tool" not in call and call.get("name") in REGISTRY:
        call = {"tool": call["name"], "args": call.get("args", {})}
    args = call.get("args")
    if args is None:                                                   # flat: {"tool": "x", "title": "..."}
        args = {k: v for k, v in call.items() if k not in ("tool", "name", "arguments", "args")}
    return {"tool": call.get("tool"), "args": args}


def action_agent(s: State) -> State:
    raw = complete('You choose which tool to run for a helpdesk request. Available tools: lookup_employee(name), '
                   'create_ticket(title, description), reset_access(username). '
                   'If the request does not clearly ask for one of these actions, use {"tool": "none", "args": {}}. '
                   'Reply ONLY with JSON of the form {"tool": "...", "args": {...}}.', s["user_input"], max_tokens=600)
    call = parse_tool_call(raw)
    if call is None:
        return {"answer": "Sorry, I couldn't work out what action to take."}
    if call.get("tool") == "none":                     # the model saw no clear action: answer as a normal question
        return {**knowledge_agent(s), "route": "knowledge"}
    ctx = {"user_id": s.get("user_id")}

    # HOOK 4: tool firewall (allowlist, schema, permissions, approvals)
    v, _ = firewall.tools.run(json.dumps(call), ctx)
    if v.action == "block":
        aid = v.meta.get("approval_id")
        if aid:
            return {"blocked": v.reason, "approval_id": aid, "blocked_layer": "tools",
                    "answer": f"This action needs human approval. Request #{aid} has been sent to IT."}
        return {"blocked": v.reason, "blocked_layer": "tools", "answer": "I'm not able to do that for your account."}

    fn = REGISTRY.get(call.get("tool"))
    if not fn:
        return {"answer": "Unknown tool."}
    try:
        result = fn(**(call.get("args") or {}))
    except Exception as e:
        result = {"error": str(e)[:100]}
    result = filter_result(call["tool"], result, ctx)
    cv, _ = firewall.context.run(json.dumps(result), {"kind": "tool_output"})      # tool output is data too
    if cv.action == "block":
        record("quarantine", source=f"tool:{call['tool']}", reason=cv.reason, user_id=s.get("user_id"),
               hash=hashlib.sha256(json.dumps(result).encode()).hexdigest(), snippet=json.dumps(result)[:200])
        result = {"error": "tool output withheld: possible injection"}
    ans = complete("You are an IT/HR helpdesk assistant. Summarize the tool result for the user.",
                   f"Request: {s['user_input']}\nTool result: {json.dumps(result)}")
    return {"tool_call": call, "tool_result": result, "answer": ans}


def build_graph():
    g = StateGraph(State)
    g.add_node("supervisor", supervisor)
    g.add_node("knowledge", knowledge_agent)
    g.add_node("action", action_agent)
    g.set_entry_point("supervisor")
    g.add_conditional_edges("supervisor", lambda s: s["route"], {"knowledge": "knowledge", "action": "action"})
    g.add_edge("knowledge", END)
    g.add_edge("action", END)
    return g.compile()


graph = build_graph()

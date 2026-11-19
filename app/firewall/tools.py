"""Layer 4: TOOL FIREWALL. Allowlist -> schema -> role permission -> human approval."""
import json, re
from .base import Pipeline, Verdict, layer_enabled
from .policy import get_policy, role_of
from app import approvals


def _parse(content: str):
    call = json.loads(content)
    return call.get("tool"), call.get("args", {})


class Allowlist:
    name = "tools.allowlist"
    def check(self, content, ctx):
        tool, _ = _parse(content)
        if not isinstance(tool, str) or tool not in get_policy()["tools"]:
            return Verdict("block", content, f"tool '{tool}' is not on the allowlist", 1.0)
        return Verdict("allow", content, "ok")


class Schema:
    name = "tools.schema"
    def check(self, content, ctx):
        tool, args = _parse(content)
        spec = get_policy()["tools"][tool]["args"]
        if not isinstance(args, dict):
            return Verdict("block", content, "args must be an object", 1.0)
        extra = set(args) - set(spec)
        if extra:
            return Verdict("block", content, f"unexpected args: {sorted(extra)}", 0.9)
        for k, rule in spec.items():
            if k not in args:
                if rule.get("required"):
                    return Verdict("block", content, f"missing arg '{k}'", 0.7)
                continue
            v = args[k]
            if not isinstance(v, str):
                return Verdict("block", content, f"arg '{k}' must be a string", 0.9)
            if len(v) > rule.get("max_len", 256):
                return Verdict("block", content, f"arg '{k}' too long", 0.9)
            if "pattern" in rule and not re.fullmatch(rule["pattern"], v):
                return Verdict("block", content, f"arg '{k}' has invalid characters", 0.9)
        return Verdict("allow", content, "ok")


class Permission:
    name = "tools.permission"
    def check(self, content, ctx):
        tool, args = _parse(content)
        user = ctx.get("user_id") or ""
        role = role_of(user)
        spec = get_policy()["tools"][tool]
        if role not in spec["allowed_roles"]:
            return Verdict("block", content, f"role '{role}' may not call {tool}", 0.95)
        if spec.get("scope", {}).get(role) == "self":
            target = str(args.get("name") or args.get("username") or "").lower()
            if target != user.lower():
                return Verdict("block", content, f"role '{role}' may only access its own record", 0.95)
        return Verdict("allow", content, "ok")


class ApprovalGate:
    name = "tools.approval"
    def check(self, content, ctx):
        tool, args = _parse(content)
        if get_policy()["tools"][tool].get("requires_approval"):
            aid = approvals.create(ctx.get("user_id") or "", tool, args)
            return Verdict("block", content, "approval_required", 0.5, meta={"approval_id": aid})
        return Verdict("allow", content, "ok")


tools = Pipeline("tools", [Allowlist(), Schema(), Permission(), ApprovalGate()])


def filter_result(tool: str, result: dict, ctx: dict) -> dict:
    """Strip fields the caller's role must never see (applied after the tool runs)."""
    if not layer_enabled("tools") or not isinstance(result, dict):
        return result
    try:
        deny = get_policy()["tools"][tool].get("deny_fields", {}).get(role_of(ctx.get("user_id")), [])
        return {k: v for k, v in result.items() if k not in deny}
    except Exception:
        return {"error": "result withheld"}      # fail closed

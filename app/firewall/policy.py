from pathlib import Path
import yaml

_PATH = Path(__file__).with_name("policy.yaml")
_cache: dict | None = None


def get_policy() -> dict:
    global _cache
    if _cache is None:
        _cache = yaml.safe_load(_PATH.read_text())   # missing/bad file raises -> guards fail closed
    return _cache


def role_of(user_id: str | None) -> str:
    p = get_policy()
    return p["users"].get((user_id or "").strip().lower(), p["default_role"])

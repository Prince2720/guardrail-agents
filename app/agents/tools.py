"""Fake enterprise backend. VULNERABLE BY DESIGN on day 1: no auth, no scoping."""
EMPLOYEES = {
    "alice": {"name": "Alice", "dept": "Engineering", "salary": 185000, "email": "alice@corp.com"},
    "bob":   {"name": "Bob",   "dept": "HR",          "salary": 92000,  "email": "bob@corp.com"},
    "admin": {"name": "Admin", "dept": "IT",          "salary": 150000, "email": "admin@corp.com"},
}
TICKETS: list[dict] = []


def lookup_employee(name: str) -> dict:
    return EMPLOYEES.get(name.lower(), {"error": "not found"})


def create_ticket(title: str, description: str = "") -> dict:
    t = {"id": len(TICKETS) + 1, "title": title, "description": description}
    TICKETS.append(t)
    return t


def reset_access(username: str) -> dict:  # HIGH RISK: should need approval
    return {"status": "access reset", "username": username, "temp_password": "Temp#1234"}


REGISTRY = {"lookup_employee": lookup_employee, "create_ticket": create_ticket, "reset_access": reset_access}

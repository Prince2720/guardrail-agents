import os
os.environ["LLM_PROVIDER"] = "mock"
from fastapi.testclient import TestClient
from app.api.main import app

c = TestClient(app)


def post(msg, uid="alice"):
    return c.post("/webhook/chat", json={"user_id": uid, "message": msg}).json()


def test_health():
    assert c.get("/health").json() == {"ok": True}


def test_knowledge_route():
    assert post("How many days of paid leave do I get?")["route"] == "knowledge"


def test_ticket_route():
    assert post("Please create a ticket: my laptop is broken")["tool_call"]["tool"] == "create_ticket"

import os
os.environ["LLM_PROVIDER"] = "mock"
from app.agents.graph import parse_tool_call

T = {"tool": "create_ticket", "args": {"title": "broken monitor", "description": "d"}}


def test_standard_shape():
    assert parse_tool_call('{"tool":"create_ticket","args":{"title":"broken monitor","description":"d"}}') == T


def test_label_wrapper():
    raw = '{"name":"TOOL_PICKER","arguments":{"tool":"lookup_employee","args":{"name":"bob"}}}'
    assert parse_tool_call(raw) == {"tool": "lookup_employee", "args": {"name": "bob"}}


def test_tool_name_wrapper():            # the bug: tool name used to be thrown away
    raw = '{"name":"create_ticket","arguments":{"title":"broken monitor","description":"d"}}'
    assert parse_tool_call(raw) == T


def test_arguments_as_json_string():
    raw = '{"name":"create_ticket","arguments":"{\\"title\\":\\"broken monitor\\",\\"description\\":\\"d\\"}"}'
    assert parse_tool_call(raw) == T


def test_tool_plus_arguments():
    raw = '{"tool":"create_ticket","arguments":{"title":"broken monitor","description":"d"}}'
    assert parse_tool_call(raw) == T


def test_flat_args_and_code_fences():
    raw = '```json\n{"tool":"create_ticket","title":"broken monitor","description":"d"}\n```'
    assert parse_tool_call(raw) == T


def test_garbage_and_missing_tool():
    assert parse_tool_call("no json here") is None
    assert parse_tool_call('{"title":"x"}')["tool"] is None      # firewall then blocks it (fail closed)

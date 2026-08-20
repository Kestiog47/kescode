"""Tests for planner delegation tools and the stage 3 planner node."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from kescode.core.state import RuntimeState
from kescode.graph import nodes
from kescode.graph.workflow import build_complex_workflow, build_workflow


def test_call_search_agent_tool_updates_state(monkeypatch) -> None:
    state = {
        "task": "Research topic",
        "runtime": RuntimeState(workspace=Path("workspace")),
        "research_notes": "existing notes",
        "sources": [{"title": "Old", "url": "https://old.example", "content": "", "score": 0.1}],
    }
    events: list[dict] = []
    search_result = {
        "ok": True,
        "summary": "new research",
        "sources": [
            {"title": "New", "url": "https://new.example", "content": "x", "score": 0.9}
        ],
    }
    monkeypatch.setattr(nodes, "run_search_agent", lambda *a, **k: search_result)

    result = nodes._call_search_agent_tool(state, events.append, "search the web")

    assert result == search_result
    assert state["research_notes"] == "existing notes\n\nnew research"
    assert [source["url"] for source in state["sources"]] == [
        "https://old.example",
        "https://new.example",
    ]
    assert state["agent_handoffs"][0]["from_agent"] == "planner"
    assert state["agent_handoffs"][0]["to_agent"] == "searchAgent"
    assert events[0] == {
        "type": "handoff",
        "from": "planner",
        "to": "searchAgent",
        "instruction": "search the web",
    }


def test_call_code_agent_tool_updates_state(monkeypatch) -> None:
    state = {
        "task": "Implement feature",
        "runtime": RuntimeState(workspace=Path("workspace")),
        "todos": [{"id": "1", "content": "Write code", "status": "pending"}],
        "messages": [],
    }
    events: list[dict] = []
    code_result = {
        "ok": True,
        "summary": "implemented",
        "todos": [{"id": "1", "content": "Write code", "status": "completed"}],
        "messages": [
            AIMessage(content="system prompt"),
            AIMessage(content="task prompt"),
            AIMessage(content="code done"),
        ],
    }
    monkeypatch.setattr(nodes, "run_code_agent", lambda *a, **k: code_result)

    result = nodes._call_code_agent_tool(state, events.append, "implement it")

    assert result == code_result
    assert state["todos"][0]["status"] == "completed"
    assert state["code_agent_summary"] == "implemented"
    assert state["agent_handoffs"][0]["to_agent"] == "codeAgent"
    assert state["messages"][-1].content == "code done"
    assert events[0]["to"] == "codeAgent"


def test_planner_node_delegates_and_returns_updates(monkeypatch) -> None:
    plan_args = {
        "plan_summary": "Build hello script",
        "todos": [{"id": "1", "content": "Write hello.py", "status": "pending"}],
        "acceptance_criteria": ["hello.py runs"],
        "verification_commands": ["python hello.py"],
    }
    responses = [
        SimpleNamespace(
            content="",
            tool_calls=[
                {"name": "todo_write", "id": "call-0", "args": plan_args},
                {
                    "name": "call_search_agent",
                    "id": "call-1",
                    "args": {"instruction": "research hello scripts"},
                },
                {
                    "name": "call_code_agent",
                    "id": "call-2",
                    "args": {"instruction": "implement hello.py"},
                },
            ],
        ),
        SimpleNamespace(content="Supervisor summary", tool_calls=[]),
    ]

    class FakeModel:
        def __init__(self) -> None:
            self.index = 0

        def bind_tools(self, tools):
            self.tools = tools
            return self

        def invoke(self, messages):
            response = responses[self.index]
            self.index += 1
            return response

    def fake_search(state, instruction, *, writer=None, max_loops=4):
        writer({"type": "search_results", "query": instruction})
        return {
            "ok": True,
            "summary": "research summary",
            "sources": [
                {
                    "title": "Docs",
                    "url": "https://docs.example",
                    "content": "documentation",
                    "score": 0.8,
                }
            ],
            "queries": [instruction],
            "messages": [],
            "tool_events": [],
        }

    def fake_code(state, instruction, *, writer=None, max_loops=10):
        writer({"type": "ai_message", "content": "implementing"})
        return {
            "ok": True,
            "summary": "code summary",
            "todos": [
                {"id": "1", "content": "Write hello.py", "status": "completed"}
            ],
            "messages": [
                AIMessage(content="system prompt"),
                AIMessage(content="task prompt"),
                AIMessage(content="hello.py written"),
            ],
            "tool_events": [],
        }

    events: list[dict] = []
    monkeypatch.setattr(nodes, "create_model", lambda: FakeModel())
    monkeypatch.setattr(nodes, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(nodes, "run_search_agent", fake_search)
    monkeypatch.setattr(nodes, "run_code_agent", fake_code)

    state = {
        "task": "Build hello script",
        "runtime": RuntimeState(workspace=Path("workspace")),
        "messages": [],
    }
    update = nodes.planner_node(state)

    assert update["plan_summary"] == "Build hello script"
    assert update["todos"][0]["status"] == "completed"
    assert update["research_notes"] == "research summary"
    assert update["sources"][0]["url"] == "https://docs.example"
    assert update["code_agent_summary"] == "code summary"
    assert len(update["agent_handoffs"]) == 2
    assert update["messages"][0].content == "hello.py written"
    assert update["context_next_node"] == "verifier"
    assert any(
        event.get("type") == "memory" and event.get("node") == "planner"
        for event in events
    )
    assert any(event.get("type") == "handoff" for event in events)


def test_workflow_has_no_actor_node() -> None:
    graph = build_workflow().get_graph()
    node_names = set(graph.nodes)
    assert "actor" not in node_names
    assert {
        "planner",
        "verifier",
        "context_monitor",
        "context_compressor",
        "final",
    } <= node_names


def test_build_complex_workflow_has_context_nodes() -> None:
    graph = build_complex_workflow().get_graph()
    node_names = set(graph.nodes)
    assert {
        "planner",
        "context_monitor",
        "context_compressor",
        "verifier",
        "final",
    } <= node_names

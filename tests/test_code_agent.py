"""Tests for the code implementation agent."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from kescode.agents import code_agent
from kescode.core.state import RuntimeState


def test_run_code_agent_react_loop(monkeypatch) -> None:
    responses = [
        SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "name": "todo_update",
                    "id": "call-1",
                    "args": {
                        "id": "1",
                        "status": "in_progress",
                        "note": "starting work",
                    },
                }
            ],
        ),
        SimpleNamespace(content="Implemented and verified.", tool_calls=[]),
    ]

    class FakeModel:
        def __init__(self) -> None:
            self.index = 0

        def bind_tools(self, tools):
            assert len(tools) == 6
            return self

        def invoke(self, messages):
            response = responses[self.index]
            self.index += 1
            return response

    monkeypatch.setattr(code_agent, "create_model", lambda: FakeModel())

    state = {
        "task": "Implement a hello script",
        "runtime": RuntimeState(
            workspace=Path(__file__).resolve().parents[1] / "workspace"
        ),
        "session_context": "Current session: implement hello.py",
        "memory": {"layer": "episodic", "previous_attempt": "none"},
        "todos": [{"id": "1", "content": "Write hello.py", "status": "pending"}],
    }
    events: list[dict] = []

    result = code_agent.run_code_agent(
        state,
        "Write hello.py and verify it runs.",
        writer=events.append,
        max_loops=2,
    )

    assert result["ok"] is True
    assert result["summary"] == "Implemented and verified."
    assert result["todos"][0]["status"] == "in_progress"
    assert state["todos"][0]["status"] == "in_progress"
    assert [event["type"] for event in events] == [
        "memory",
        "ai_message",
        "tool_call",
        "tool_result",
        "ai_message",
        "final_answer",
    ]
    assert [event["type"] for event in result["tool_events"]] == [
        "tool_call",
        "tool_result",
    ]

    human = result["messages"][1]
    assert "Session context:" in human.content
    assert "Current session: implement hello.py" in human.content
    assert "Layered memory:" in human.content
    assert '"working_memory"' in human.content

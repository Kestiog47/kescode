"""Tests for the checkpoint/trace-aware agent event stream."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from kescode.core import agent
from kescode.core.checkpoint import CheckpointManager
from kescode.core.state import RuntimeState


def test_create_runtime_uses_resume_workspace(tmp_path) -> None:
    resume = tmp_path / "resume"
    runtime = agent.create_runtime(
        tmp_path,
        approval_mode="deny",
        checkpoint_mode="strict",
        resume_from=resume,
        trace_mode="summary",
    )

    assert runtime.workspace == resume.resolve()
    assert runtime.approval_mode == "deny"
    assert runtime.checkpoint_mode == "strict"
    assert runtime.trace_mode == "summary"


def test_create_runtime_normalizes_trace_on(tmp_path) -> None:
    runtime = agent.create_runtime(tmp_path, trace_mode="on")

    assert runtime.trace_mode == "full"


def test_stream_agent_events_yields_wrapped_events(
    monkeypatch,
    tmp_path,
) -> None:
    class FakeWorkflow:
        def stream(self, inputs, stream_mode=None):
            assert stream_mode == ["updates", "custom"]
            yield ("updates", {"planner": {"plan_summary": "plan", "messages": []}})
            yield ("custom", {"type": "tool_call", "name": "bash"})
            yield ("custom", {"type": "tool_result", "ok": True})
            yield ("updates", {"final": {"final_answer": "done"}})

    monkeypatch.setattr(agent, "build_workflow", lambda: FakeWorkflow())

    events = list(
        agent.stream_agent_events(
            "task",
            workspace=tmp_path,
            checkpoint_mode="strict",
            trace_mode="full",
        )
    )

    assert [event["type"] for event in events] == [
        "graph_event",
        "custom_event",
        "custom_event",
        "graph_event",
    ]
    assert "planner" in events[0]["event"]
    assert events[1]["event"]["type"] == "tool_call"
    assert events[2]["event"]["type"] == "tool_result"
    assert "final" in events[3]["event"]

    checkpoint = json.loads(
        (tmp_path / ".kescode" / "checkpoints" / "checkpoint.json").read_text(
            encoding="utf-8"
        )
    )
    assert checkpoint["status"] == "finished"

    trace_dir = next((tmp_path / ".kescode" / "traces").iterdir())
    trace_payload = json.loads(
        (trace_dir / "trace.json").read_text(encoding="utf-8")
    )
    assert trace_payload["status"] == "finished"
    assert trace_payload["node_visits"] == {"planner": 1, "final": 1}
    assert trace_payload["tool_calls"] == 1


def test_stream_agent_events_resumes_from_checkpoint(
    monkeypatch,
    tmp_path,
) -> None:
    runtime = RuntimeState(workspace=tmp_path, checkpoint_mode="strict")
    CheckpointManager(runtime, task="saved task").save(
        {
            "task": "saved task",
            "attempts": 2,
            "max_attempts": 4,
            "messages": [HumanMessage(content="old message")],
        },
        status="running",
        latest_node="planner",
    )
    captured: dict = {}

    class FakeWorkflow:
        def stream(self, inputs, stream_mode=None):
            captured["inputs"] = inputs
            return iter([])

    monkeypatch.setattr(agent, "build_workflow", lambda: FakeWorkflow())

    events = list(
        agent.stream_agent_events(
            "new task",
            workspace=tmp_path,
            resume_workspace=tmp_path,
            max_attempts=5,
            checkpoint_mode="light",
            trace_mode="full",
        )
    )

    assert events == []
    assert captured["inputs"]["task"] == "new task"
    assert captured["inputs"]["attempts"] == 2
    assert captured["inputs"]["max_attempts"] == 4
    assert len(captured["inputs"]["messages"]) == 1

    trace_dir = next((tmp_path / ".kescode" / "traces").iterdir())
    first_line = (
        trace_dir / "events.jsonl"
    ).read_text(encoding="utf-8").splitlines()[0]
    run_start = json.loads(first_line)
    assert run_start["resumed"] is True
    assert run_start["resume_event"]["checkpoint_id"]


def test_stream_agent_events_saves_interrupted_state(
    monkeypatch,
    tmp_path,
) -> None:
    class FakeWorkflow:
        def stream(self, inputs, stream_mode=None):
            yield ("updates", {"planner": {"plan_summary": "plan"}})
            raise KeyboardInterrupt

    monkeypatch.setattr(agent, "build_workflow", lambda: FakeWorkflow())

    with pytest.raises(KeyboardInterrupt):
        list(
            agent.stream_agent_events(
                "task",
                workspace=tmp_path,
                checkpoint_mode="strict",
                trace_mode="full",
            )
        )

    checkpoint = json.loads(
        (tmp_path / ".kescode" / "checkpoints" / "checkpoint.json").read_text(
            encoding="utf-8"
        )
    )
    assert checkpoint["status"] == "interrupted"

    trace_dir = next((tmp_path / ".kescode" / "traces").iterdir())
    trace_payload = json.loads(
        (trace_dir / "trace.json").read_text(encoding="utf-8")
    )
    assert trace_payload["status"] == "interrupted"


def test_custom_event_needs_checkpoint() -> None:
    assert agent._custom_event_needs_checkpoint({"type": "handoff"}) is True
    assert agent._custom_event_needs_checkpoint({"type": "tool_result"}) is True
    assert agent._custom_event_needs_checkpoint({"type": "tool_call"}) is False

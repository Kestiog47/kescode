"""Tests for the context monitor node and routing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from kescode.core.state import RuntimeState
from kescode.graph import nodes


def test_context_monitor_node_uses_model_count_and_limit(monkeypatch, tmp_path) -> None:
    class FakeModel:
        def get_num_tokens_from_messages(self, messages) -> int:
            assert len(messages) == 2
            return 501

    monkeypatch.setattr(nodes, "create_model", lambda: FakeModel())

    result = nodes.context_monitor_node(
        {
            "runtime": RuntimeState(workspace=tmp_path),
            "messages": [HumanMessage(content="hello")],
            "context_token_limit": 500,
            "context_next_node": "planner",
        }
    )

    assert result == {
        "context_token_count": 501,
        "context_should_compress": True,
        "context_next_node": "planner",
    }


def test_context_monitor_node_falls_back_to_text_estimate(
    monkeypatch,
    tmp_path,
) -> None:
    class BrokenModel:
        def get_num_tokens_from_messages(self, messages) -> int:
            raise RuntimeError("no tokenizer")

    monkeypatch.setattr(nodes, "create_model", lambda: BrokenModel())
    monkeypatch.setattr(
        nodes,
        "build_layered_memory",
        lambda state, node="graph": {"fake": True},
    )
    monkeypatch.setattr(
        nodes,
        "format_layered_memory_for_prompt",
        lambda memory: "MEMORY_PAYLOAD",
    )

    result = nodes.context_monitor_node(
        {
            "runtime": RuntimeState(workspace=tmp_path),
            "messages": [HumanMessage(content="hello")],
            "context_token_limit": 3,
        }
    )

    assert result["context_token_count"] == len("hello\nMEMORY_PAYLOAD") // 4
    assert result["context_should_compress"] is True


def test_context_monitor_node_defaults(monkeypatch, tmp_path) -> None:
    class FakeModel:
        def get_num_tokens_from_messages(self, messages) -> int:
            return 400_001

    monkeypatch.setattr(nodes, "create_model", lambda: FakeModel())

    result = nodes.context_monitor_node(
        {
            "runtime": RuntimeState(workspace=tmp_path),
            "messages": [],
        }
    )

    assert result["context_token_count"] == 400_001
    assert result["context_should_compress"] is True
    assert result["context_next_node"] == "verifier"


def test_context_monitor_route() -> None:
    assert nodes.context_monitor_route(
        {"passed": True, "context_should_compress": True}
    ) == "final"
    assert nodes.context_monitor_route(
        {"context_should_compress": True, "context_next_node": "planner"}
    ) == "context_compressor"
    assert nodes.context_monitor_route({"context_next_node": "planner"}) == "planner"
    assert nodes.context_monitor_route({}) == "verifier"


def test_context_compressor_route() -> None:
    assert nodes.context_compressor_route({"context_next_node": "planner"}) == "planner"
    assert nodes.context_compressor_route({"context_next_node": "final"}) == "final"
    assert nodes.context_compressor_route({}) == "verifier"


def test_verifier_node_sets_context_next_node_on_failure(monkeypatch) -> None:
    class FakeModel:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return SimpleNamespace(
                content=(
                    '{"passed": false, "reason": "not done", "checks": [], '
                    '"recommended_next_instruction": ""}'
                ),
                tool_calls=[],
            )

    monkeypatch.setattr(nodes, "create_model", lambda: FakeModel())

    update = nodes.verifier_node(
        {
            "runtime": RuntimeState(workspace=Path("workspace")),
            "verification_commands": [],
            "attempts": 0,
        }
    )

    assert update["passed"] is False
    assert update["context_next_node"] == "planner"


def test_verifier_node_sets_final_when_max_attempts_reached(monkeypatch) -> None:
    class FakeModel:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return SimpleNamespace(
                content=(
                    '{"passed": false, "reason": "still failing", "checks": [], '
                    '"recommended_next_instruction": "retry"}'
                ),
                tool_calls=[],
            )

    monkeypatch.setattr(nodes, "create_model", lambda: FakeModel())

    update = nodes.verifier_node(
        {
            "runtime": RuntimeState(workspace=Path("workspace")),
            "verification_commands": [],
            "attempts": 1,
            "max_attempts": 2,
        }
    )

    assert update["attempts"] == 2
    assert update["context_next_node"] == "final"


def test_verifier_node_emits_memory_event(monkeypatch) -> None:
    events: list[dict] = []
    captured: dict = {}

    class FakeModel:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            captured["human"] = messages[1].content
            return SimpleNamespace(
                content=(
                    '{"passed": true, "reason": "done", "checks": [], '
                    '"recommended_next_instruction": ""}'
                ),
                tool_calls=[],
            )

    monkeypatch.setattr(nodes, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(nodes, "create_model", lambda: FakeModel())

    nodes.verifier_node(
        {
            "runtime": RuntimeState(workspace=Path("workspace")),
            "verification_commands": [],
            "attempts": 0,
        }
    )

    assert events[0]["type"] == "memory"
    assert events[0]["node"] == "verifier"
    assert "Layered memory:" in captured["human"]

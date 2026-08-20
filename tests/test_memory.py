"""Tests for the layered memory system."""

from __future__ import annotations

import json
from pathlib import Path

from kescode.core.state import RuntimeState
from kescode.graph.memory import (
    RULES_LAYER,
    build_layered_memory,
    format_layered_memory_for_prompt,
    memory_event,
    read_history_summary,
    read_notepad,
)
from kescode.graph.state import KesGraphState


def test_rules_layer_matches_spec() -> None:
    assert RULES_LAYER["scope"] == "workspace"
    assert RULES_LAYER["storage"] == "internal"
    assert RULES_LAYER["rules"] == [
        "Work inside the current workspace only.",
        "Use paths relative to the workspace; do not prefix paths with workspace/.",
        "Keep durable task context outside the raw messages transcript when possible.",
        "Treat TODO.md as working plan state, NOTEPAD.md as durable notes, and HISTORY_SUMMARY.md as compressed history.",
        "Do not expose memory write tools to agents; layered memory is assembled by the runtime.",
    ]


def test_short_text_truncates_with_ellipsis() -> None:
    from kescode.graph.memory import _short_text

    assert _short_text("a" * 20, 10) == "a" * 10 + "..."
    assert _short_text("short", 100) == "short"
    assert _short_text(None, 100) == ""


def test_trim_handoffs_keeps_recent_six() -> None:
    from kescode.graph.memory import _trim_handoffs

    handoffs = [{"id": index} for index in range(8)]
    assert _trim_handoffs(handoffs) == handoffs[-6:]
    assert _trim_handoffs([]) == []
    assert _trim_handoffs("not-a-list") == []


def test_read_memory_files(tmp_path) -> None:
    (tmp_path / "NOTEPAD.md").write_text("durable note", encoding="utf-8")
    (tmp_path / "HISTORY_SUMMARY.md").write_text(
        "compressed history",
        encoding="utf-8",
    )
    runtime = RuntimeState(workspace=tmp_path)

    assert read_notepad(runtime) == {
        "exists": True,
        "content": "durable note",
    }
    assert read_history_summary(runtime) == {
        "exists": True,
        "summary": "compressed history",
    }


def test_build_layered_memory_assembles_all_layers(tmp_path) -> None:
    (tmp_path / "NOTEPAD.md").write_text("note " * 500, encoding="utf-8")
    (tmp_path / "HISTORY_SUMMARY.md").write_text("history " * 500, encoding="utf-8")

    state = {
        "runtime": RuntimeState(workspace=tmp_path),
        "task": "Build the feature",
        "session_id": "session-1",
        "session_turn": 4,
        "plan_summary": "Plan summary",
        "todos": [{"id": "1", "content": "Work", "status": "pending"}],
        "acceptance_criteria": ["Tests pass"],
        "verification_commands": ["pytest"],
        "research_notes": "x" * 2000,
        "sources": [
            {"title": "Docs", "url": "https://example.com", "content": "secret"},
            {"title": "Spec", "url": "https://spec.example.com", "score": 0.9},
        ],
        "agent_handoffs": [{"to_agent": f"agent-{index}"} for index in range(8)],
        "code_agent_summary": "code summary",
        "verifier_summary": "verifier summary",
        "last_error": "boom",
        "attempts": 2,
        "max_attempts": 5,
        "context_summary": "context",
        "compression_events": [
            {"node": "planner", "reason": f"reason-{index}"} for index in range(5)
        ],
    }

    memory = build_layered_memory(state, node="planner")

    assert memory["rules"] == RULES_LAYER
    working = memory["working_memory"]
    assert working["node"] == "planner"
    assert working["task"] == "Build the feature"
    assert working["session_id"] == "session-1"
    assert working["session_turn"] == 4
    assert working["plan_summary"] == "Plan summary"
    assert working["todos"][0]["content"] == "Work"
    assert working["acceptance_criteria"] == ["Tests pass"]
    assert working["verification_commands"] == ["pytest"]
    assert working["research_notes"].endswith("...")
    assert working["sources"] == [
        {"title": "Docs", "url": "https://example.com"},
        {"title": "Spec", "url": "https://spec.example.com"},
    ]
    assert working["agent_handoffs"] == [
        {"to_agent": f"agent-{index}"} for index in range(2, 8)
    ]
    assert working["code_agent_summary"] == "code summary"
    assert working["verifier_summary"] == "verifier summary"
    assert working["last_error"] == "boom"
    assert working["attempts"] == 2
    assert working["max_attempts"] == 5

    store = memory["history_summary_store"]
    assert store["history_path"] == "HISTORY_SUMMARY.md"
    assert store["history_exists"] is True
    assert store["history_summary"].endswith("...")
    assert store["notepad_path"] == "NOTEPAD.md"
    assert store["notepad_exists"] is True
    assert store["notepad"].endswith("...")
    assert store["context_summary"] == "context"
    assert len(store["compression_events"]) == 3
    assert store["compression_events"][-1]["reason"] == "reason-4"


def test_build_layered_memory_without_files(tmp_path) -> None:
    memory = build_layered_memory(
        {"runtime": RuntimeState(workspace=tmp_path)},
        node="graph",
    )

    assert memory["working_memory"]["node"] == "graph"
    assert memory["working_memory"]["task"] == ""
    assert memory["history_summary_store"]["history_exists"] is False
    assert memory["history_summary_store"]["history_summary"] == ""
    assert memory["history_summary_store"]["notepad_exists"] is False
    assert memory["history_summary_store"]["notepad"] == ""
    assert memory["history_summary_store"]["compression_events"] == []


def test_format_layered_memory_for_prompt_returns_json() -> None:
    memory = build_layered_memory(
        {
            "runtime": RuntimeState(workspace=Path(".")),
            "task": "task",
        }
    )

    rendered = format_layered_memory_for_prompt(memory)
    assert json.loads(rendered) == memory
    assert rendered.startswith("{\n")


def test_memory_event_shape() -> None:
    memory = {"working_memory": {"task": "task"}}
    assert memory_event(memory, node="planner") == {
        "type": "memory",
        "node": "planner",
        "memory": memory,
    }


def test_kes_graph_state_has_memory_fields() -> None:
    annotations = KesGraphState.__annotations__
    for field in (
        "context_summary",
        "context_token_count",
        "context_token_limit",
        "context_should_compress",
        "context_next_node",
        "compression_events",
        "memory_snapshot",
        "history_summary",
    ):
        assert field in annotations

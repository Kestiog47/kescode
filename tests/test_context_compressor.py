"""Tests for the context compressor node."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages

from kescode.core.errors import KesCodeError
from kescode.core.state import RuntimeState
from kescode.graph import nodes
from kescode.prompts.stage4 import CONTEXT_COMPRESSION_PROMPT


def _compression_payload() -> dict:
    return {
        "summary": "Compressed summary",
        "active_goal": "Finish the feature",
        "completed_work": "Wrote hello.py",
        "open_todos": ["Verify output"],
        "important_files": ["hello.py"],
        "tool_findings": "pytest passed",
        "sources": ["https://example.com"],
        "next_steps": ["Run verifier"],
        "risks": ["None"],
    }


def test_context_compressor_node_replaces_and_persists(
    monkeypatch,
    tmp_path,
) -> None:
    model = SimpleNamespace(
        invoked=[],
        get_num_tokens=lambda text: 77,
    )

    def invoke(messages):
        model.invoked = messages
        return SimpleNamespace(content=json.dumps(_compression_payload()))

    model.invoke = invoke
    monkeypatch.setattr(nodes, "create_model", lambda: model)

    result = nodes.context_compressor_node(
        {
            "runtime": RuntimeState(workspace=tmp_path),
            "messages": [HumanMessage(content="old transcript")],
            "research_notes": "x" * 2000,
            "sources": [
                {
                    "title": "Docs",
                    "url": "https://docs.example",
                    "content": "hidden",
                    "score": 0.9,
                }
            ],
            "agent_handoffs": [
                {"to_agent": f"agent-{index}"} for index in range(8)
            ],
            "plan_summary": "plan " * 500,
            "compression_events": [{"node": "previous"}],
        }
    )

    assert isinstance(result["messages"][0], RemoveMessage)
    assert result["messages"][0].id == REMOVE_ALL_MESSAGES
    assert isinstance(result["messages"][1], AIMessage)
    assert result["messages"][1].content == "Compressed summary"
    assert result["context_summary"] == "Compressed summary"
    assert result["context_token_count"] == 77
    assert result["context_should_compress"] is False
    assert result["research_notes"].endswith("...")
    assert result["sources"] == [
        {"title": "Docs", "url": "https://docs.example"}
    ]
    assert len(result["agent_handoffs"]) == 6
    assert result["history_summary"] == "Compressed summary"
    assert result["compression_events"][0]["node"] == "previous"
    assert result["compression_events"][-1]["node"] == "context_compressor"
    assert (
        tmp_path / "HISTORY_SUMMARY.md"
    ).read_text(encoding="utf-8") == "Compressed summary"

    assert model.invoked[0].content == CONTEXT_COMPRESSION_PROMPT
    assert "Current message transcript:" in model.invoked[1].content
    assert "Layered memory snapshot:" in model.invoked[1].content

    merged = add_messages(
        [HumanMessage(content="old transcript", id="old-1")],
        result["messages"],
    )
    assert [message.content for message in merged] == ["Compressed summary"]


def test_context_compressor_node_falls_back_to_text_estimate(
    monkeypatch,
    tmp_path,
) -> None:
    model = SimpleNamespace()

    def invoke(messages):
        return SimpleNamespace(content=json.dumps(_compression_payload()))

    model.invoke = invoke
    monkeypatch.setattr(nodes, "create_model", lambda: model)

    result = nodes.context_compressor_node(
        {
            "runtime": RuntimeState(workspace=tmp_path),
            "messages": [],
        }
    )

    assert result["context_token_count"] == len("Compressed summary") // 4


def test_context_compressor_node_rejects_empty_summary(
    monkeypatch,
    tmp_path,
) -> None:
    model = SimpleNamespace()

    def invoke(messages):
        return SimpleNamespace(content='{"summary": ""}')

    model.invoke = invoke
    monkeypatch.setattr(nodes, "create_model", lambda: model)

    with pytest.raises(KesCodeError, match="empty summary"):
        nodes.context_compressor_node(
            {
                "runtime": RuntimeState(workspace=tmp_path),
                "messages": [],
            }
        )


def test_context_compression_prompt_has_required_keys() -> None:
    assert "summary" in CONTEXT_COMPRESSION_PROMPT
    for key in (
        "active_goal",
        "completed_work",
        "open_todos",
        "important_files",
        "tool_findings",
        "sources",
        "next_steps",
        "risks",
    ):
        assert f"- {key}" in CONTEXT_COMPRESSION_PROMPT

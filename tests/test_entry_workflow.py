"""Tests for the intent-routing entry workflow."""

from __future__ import annotations

import json
from types import SimpleNamespace

from kescode.graph import nodes
from kescode.graph.workflow import build_entry_workflow


def test_entry_workflow_has_intent_nodes() -> None:
    graph = build_entry_workflow().get_graph()
    node_names = set(graph.nodes)
    assert {"intent_router", "chat_responder"} <= node_names


def test_entry_workflow_ends_without_chat_on_workflow_route(monkeypatch) -> None:
    payload = {
        "route": "workflow",
        "reason": "file creation request",
        "confidence": 0.9,
    }

    class FakeModel:
        def invoke(self, messages):
            return SimpleNamespace(content=json.dumps(payload))

    monkeypatch.setattr(nodes, "create_model", lambda: FakeModel())

    result = build_entry_workflow().invoke({"task": "create a file"})

    assert result["intent_route"] == "workflow"
    assert "chat_response" not in result


def test_intent_route_fn_routes_chat_and_defaults_to_planner() -> None:
    assert nodes.intent_route_fn({"intent_route": "chat"}) == "chat_responder"
    assert nodes.intent_route_fn({}) == "planner"
    assert nodes.intent_route_fn({"intent_route": "workflow"}) == "planner"


def test_intent_router_node_accepts_chat_route(monkeypatch) -> None:
    payload = {
        "route": "chat",
        "reason": "casual greeting",
        "confidence": 0.9,
    }

    class FakeModel:
        def invoke(self, messages):
            return SimpleNamespace(content=json.dumps(payload))

    monkeypatch.setattr(nodes, "create_model", lambda: FakeModel())

    update = nodes.intent_router_node({"task": "hello"})

    assert update["intent_route"] == "chat"
    assert update["intent_reason"] == "casual greeting"
    assert update["intent_confidence"] == 0.9


def test_intent_router_node_defaults_to_workflow_on_low_confidence(
    monkeypatch,
) -> None:
    payload = {
        "route": "chat",
        "reason": "uncertain",
        "confidence": 0.4,
    }

    class FakeModel:
        def invoke(self, messages):
            return SimpleNamespace(content=json.dumps(payload))

    monkeypatch.setattr(nodes, "create_model", lambda: FakeModel())

    update = nodes.intent_router_node({"task": "hello"})

    assert update["intent_route"] == "workflow"
    assert update["intent_confidence"] == 0.4


def test_chat_responder_node_returns_llm_answer(monkeypatch) -> None:
    class FakeModel:
        def invoke(self, messages):
            return SimpleNamespace(content="Hello! How can I help?")

    monkeypatch.setattr(nodes, "create_model", lambda: FakeModel())

    update = nodes.chat_responder_node({"task": "hi"})

    assert update["chat_response"] == "Hello! How can I help?"
    assert update["final_answer"] == "Hello! How can I help?"

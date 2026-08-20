"""Shared state for the KesCode LangGraph agent."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from kescode.core.state import RuntimeState
from kescode.graph.memory import CompressionEvent, LayeredMemory


class TodoItem(TypedDict):
    """A single tracked work item in the agent's todo list."""

    id: str
    content: str
    status: str  # "pending" | "in_progress" | "completed" | "blocked"
    note: str


class SourceItem(TypedDict):
    """A web source returned by the search agent."""

    title: str
    url: str
    content: str
    score: float | None


class AgentHandoff(TypedDict, total=False):
    """A record of one planner-to-specialist delegation."""

    from_agent: str
    to_agent: str
    instruction: str
    result: str


class VerificationResult(TypedDict):
    """Outcome of one verification command."""

    command: str
    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str


class VerificationCheck(TypedDict):
    """A single named check reported by the verifier."""

    name: str
    passed: bool
    detail: str


class KesGraphState(TypedDict, total=False):
    """State passed between nodes in the KesCode LangGraph."""

    task: str
    runtime: RuntimeState
    messages: Annotated[list[BaseMessage], add_messages]
    plan_summary: str
    todos: list[TodoItem]
    acceptance_criteria: list[str]
    verification_commands: list[str]
    research_notes: str
    sources: list[SourceItem]
    agent_handoffs: list[AgentHandoff]
    code_agent_summary: str
    verification_results: list[VerificationResult]
    verification_checks: list[VerificationCheck]
    passed: bool
    attempts: int
    max_attempts: int
    last_error: str | None
    context_summary: str
    context_token_count: int
    context_token_limit: int
    context_should_compress: bool
    context_next_node: str
    compression_events: list[CompressionEvent]
    memory_snapshot: LayeredMemory
    history_summary: str
    final_answer: str

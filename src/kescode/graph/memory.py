"""Layered memory assembly for the KesCode graph.

The runtime combines three layers before prompting agents:

- a fixed rules layer describing workspace and memory conventions
- a working memory layer carrying current task state
- a history summary store carrying compressed durable context
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

from kescode.core.state import RuntimeState

NOTEPAD_PATH = "NOTEPAD.md"
HISTORY_SUMMARY_PATH = "HISTORY_SUMMARY.md"
HANDOFF_LIMIT = 6
COMPRESSION_EVENT_LIMIT = 3

RULES_LAYER: dict[str, Any] = {
    "scope": "workspace",
    "storage": "internal",
    "rules": [
        "Work inside the current workspace only.",
        "Use paths relative to the workspace; do not prefix paths with workspace/.",
        "Keep durable task context outside the raw messages transcript when possible.",
        "Treat TODO.md as working plan state, NOTEPAD.md as durable notes, and HISTORY_SUMMARY.md as compressed history.",
        "Do not expose memory write tools to agents; layered memory is assembled by the runtime.",
    ],
}


class CompressionEvent(TypedDict, total=False):
    """One recorded context compression action."""

    node: str
    timestamp: str
    reason: str
    summary: str
    token_count: int


class LayeredMemory(TypedDict):
    """The three memory layers assembled for a prompt."""

    rules: dict[str, Any]
    working_memory: dict[str, Any]
    history_summary_store: dict[str, Any]


def read_notepad(runtime: RuntimeState) -> dict[str, Any]:
    """Read NOTEPAD.md from the workspace root."""

    return _read_workspace_file(runtime.workspace, NOTEPAD_PATH, "content")


def read_history_summary(runtime: RuntimeState) -> dict[str, Any]:
    """Read HISTORY_SUMMARY.md from the workspace root."""

    return _read_workspace_file(runtime.workspace, HISTORY_SUMMARY_PATH, "summary")


def build_layered_memory(state: dict[str, Any], *, node: str = "graph") -> LayeredMemory:
    """Assemble the three memory layers from graph state and workspace files."""

    runtime = state["runtime"]
    notepad = read_notepad(runtime)
    history = read_history_summary(runtime)
    history_summary = history.get("summary", history.get("content", ""))

    working_memory: dict[str, Any] = {
        "node": node,
        "task": state.get("task", ""),
        "session_id": state.get("session_id", ""),
        "session_turn": state.get("session_turn", 0),
        "plan_summary": state.get("plan_summary", ""),
        "todos": state.get("todos", []),
        "acceptance_criteria": state.get("acceptance_criteria", []),
        "verification_commands": state.get("verification_commands", []),
        "research_notes": _short_text(state.get("research_notes", ""), 1600),
        "sources": _source_titles_and_urls(state.get("sources", [])),
        "agent_handoffs": _trim_handoffs(state.get("agent_handoffs", [])),
        "code_agent_summary": _short_text(state.get("code_agent_summary", ""), 1000),
        "verifier_summary": _short_text(state.get("verifier_summary", ""), 1000),
        "last_error": _short_text(state.get("last_error", ""), 1400),
        "attempts": state.get("attempts", 0),
        "max_attempts": state.get("max_attempts", 3),
    }

    history_summary_store: dict[str, Any] = {
        "history_path": HISTORY_SUMMARY_PATH,
        "history_exists": history.get("exists", False),
        "history_summary": _short_text(history_summary, 2200),
        "notepad_path": NOTEPAD_PATH,
        "notepad_exists": notepad.get("exists", False),
        "notepad": _short_text(notepad.get("content", ""), 1800),
        "context_summary": _short_text(state.get("context_summary", ""), 1600),
        "compression_events": (state.get("compression_events") or [])[
            -COMPRESSION_EVENT_LIMIT:
        ],
    }

    return {
        "rules": dict(RULES_LAYER),
        "working_memory": working_memory,
        "history_summary_store": history_summary_store,
    }


def format_layered_memory_for_prompt(memory: LayeredMemory | dict[str, Any]) -> str:
    """Render layered memory as pretty JSON for an agent prompt."""

    return json.dumps(memory, ensure_ascii=False, indent=2, default=str)


def memory_event(
    memory: LayeredMemory | dict[str, Any],
    *,
    node: str,
) -> dict[str, Any]:
    """Wrap a layered memory snapshot as a streamed event."""

    return {"type": "memory", "node": node, "memory": memory}


def _short_text(text: Any, limit: int) -> str:
    """Truncate text to a character limit, appending an ellipsis when cut."""

    if text is None:
        return ""
    value = str(text)
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


def _trim_handoffs(handoffs: Any) -> list[Any]:
    """Keep only the most recent handoff records."""

    if not isinstance(handoffs, list):
        return []
    return handoffs[-HANDOFF_LIMIT:]


def _source_titles_and_urls(sources: Any) -> list[dict[str, str]]:
    """Keep only the title and url fields from research sources."""

    trimmed: list[dict[str, str]] = []
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        trimmed.append(
            {
                "title": str(source.get("title") or ""),
                "url": str(source.get("url") or ""),
            }
        )
    return trimmed


def _read_workspace_file(
    workspace: Path,
    relative_path: str,
    content_key: str,
) -> dict[str, Any]:
    """Read a UTF-8 workspace file and report whether it exists."""

    target = workspace / relative_path
    if not target.is_file():
        return {"exists": False, content_key: ""}
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"exists": False, content_key: ""}
    return {"exists": True, content_key: content}

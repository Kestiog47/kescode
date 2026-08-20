"""Execution tracing for KesCode runs."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import BaseMessage

from kescode.core.state import (
    VALID_TRACE_MODES,
    RuntimeState,
    normalize_trace_mode,
)

__all__ = [
    "TraceRecorder",
    "VALID_TRACE_MODES",
    "build_timeline_markdown",
    "normalize_trace_mode",
]

TRACE_DIR = ".kescode/traces"
TRACE_JSON = "trace.json"
EVENTS_JSONL = "events.jsonl"
TIMELINE_MD = "timeline.md"

HEAD_LIMIT = 20
TAIL_LIMIT = 80


class TraceRecorder:
    """Record execution events and produce trace summaries."""

    def __init__(self, runtime: RuntimeState, task: str = "") -> None:
        self.workspace = runtime.workspace
        self.mode = normalize_trace_mode(runtime.trace_mode)
        self.trace_id = runtime.trace_id or f"trace-{uuid4().hex[:8]}"
        self.task = task
        self.root = self.workspace / TRACE_DIR / self.trace_id

        self.node_visits: dict[str, int] = {}
        self.tool_calls = 0
        self.failed_tool_calls = 0
        self.approval_count = 0
        self.checkpoint_count = 0
        self.handoff_count = 0

        self._events: list[dict[str, Any]] = []
        self._started_at: str | None = None
        self._ended_at: str | None = None
        self._started = False

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def start(
        self,
        inputs: dict[str, Any],
        *,
        resumed: bool = False,
        resume_event: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Record the run_start event and remember when the run began."""

        if not self.enabled:
            return None

        self._started = True
        self._started_at = datetime.now(timezone.utc).isoformat()
        event: dict[str, Any] = {
            "type": "run_start",
            "timestamp": self._started_at,
            "trace_id": self.trace_id,
            "mode": self.mode,
            "task": self.task or inputs.get("task", ""),
            "workspace": str(self.workspace),
            "resumed": resumed,
            "attempts": inputs.get("attempts", 0),
            "max_attempts": inputs.get("max_attempts", 3),
        }
        if resume_event:
            event["resume_event"] = resume_event
        return self._record(event)

    def record_custom_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Record one custom event and update execution statistics."""

        if not self.enabled:
            return None

        event_type = str(event.get("type") or "")
        if event_type == "tool_call":
            self.tool_calls += 1
        elif event_type == "tool_result":
            if event.get("ok") is False:
                self.failed_tool_calls += 1
            if event.get("requires_approval"):
                self.approval_count += 1
        elif event_type == "handoff":
            self.handoff_count += 1
        elif event_type == "checkpoint_saved":
            self.checkpoint_count += 1

        return self._record(event)

    def record_graph_update(
        self,
        event: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Record a graph node update and count node visits."""

        if not self.enabled:
            return None

        node = _extract_node(event)
        self.node_visits[node] = self.node_visits.get(node, 0) + 1
        return self._record(
            {
                "type": "graph_update",
                "node": node,
                "data": event,
            }
        )

    def end(
        self,
        *,
        status: str,
        latest_node: str | None,
        final_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Finish tracing and write trace.json plus timeline.md."""

        if not self.enabled:
            return None

        self._ended_at = datetime.now(timezone.utc).isoformat()
        if self._started_at is None:
            self._started_at = self._ended_at

        payload = self._trace_payload(status, latest_node, final_state)
        self.root.mkdir(parents=True, exist_ok=True)
        _write_json(self.root / TRACE_JSON, payload)
        _write_text(self.root / TIMELINE_MD, build_timeline_markdown(payload))
        return payload

    def _trace_payload(
        self,
        status: str,
        latest_node: str | None,
        final_state: dict[str, Any],
    ) -> dict[str, Any]:
        started = _parse_timestamp(self._started_at or self._ended_at or "")
        ended = _parse_timestamp(self._ended_at or self._started_at or "")
        duration_ms = max(0, int((ended - started).total_seconds() * 1000))

        head = self._events[:HEAD_LIMIT]
        tail = self._events[-TAIL_LIMIT:] if self._events else []
        omitted = max(0, len(self._events) - len(head) - len(tail))

        return {
            "trace_id": self.trace_id,
            "task": self.task or final_state.get("task", ""),
            "status": status,
            "started_at": self._started_at,
            "ended_at": self._ended_at,
            "duration_ms": duration_ms,
            "node_visits": dict(self.node_visits),
            "tool_calls": self.tool_calls,
            "failed_tool_calls": self.failed_tool_calls,
            "approval_count": self.approval_count,
            "checkpoint_count": self.checkpoint_count,
            "handoff_count": self.handoff_count,
            "latest_node": latest_node,
            "timeline_head": head,
            "timeline_tail": tail,
            "timeline_omitted": omitted,
        }

    def _record(self, event: dict[str, Any]) -> dict[str, Any]:
        record = dict(event)
        record.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        record.setdefault("trace_id", self.trace_id)
        self._events.append(record)

        if self.mode == "full":
            self.root.mkdir(parents=True, exist_ok=True)
            _append_event(self.root / EVENTS_JSONL, record)
        return record


def build_timeline_markdown(payload: dict[str, Any]) -> str:
    """Render a human-readable timeline from a trace payload."""

    events = _merge_head_tail(
        payload.get("timeline_head") or [],
        payload.get("timeline_tail") or [],
    )
    lines = [
        "# Trace Timeline",
        "",
        f"- Trace: {payload.get('trace_id') or 'unknown'}",
        f"- Task: {payload.get('task') or ''}",
        f"- Status: {payload.get('status') or 'unknown'}",
        f"- Duration: {payload.get('duration_ms') or 0} ms",
        f"- Nodes: {json.dumps(payload.get('node_visits') or {}, ensure_ascii=False)}",
        (
            f"- Tools: {payload.get('tool_calls') or 0} "
            f"(failed {payload.get('failed_tool_calls') or 0})"
        ),
        f"- Approvals: {payload.get('approval_count') or 0}",
        f"- Checkpoints: {payload.get('checkpoint_count') or 0}",
        f"- Handoffs: {payload.get('handoff_count') or 0}",
        "",
        "## Events",
        "",
    ]
    if payload.get("timeline_omitted"):
        lines.append(
            f"*{payload['timeline_omitted']} events omitted from the middle.*"
        )
        lines.append("")
    if not events:
        lines.append("No events recorded.")
        return "\n".join(lines)

    for index, event in enumerate(events, start=1):
        lines.append(_format_event_line(index, event))
    return "\n".join(lines)


def _format_event_line(index: int, event: dict[str, Any]) -> str:
    parts = [f"{index}.", f"`{event.get('type') or 'event'}`"]
    if event.get("timestamp"):
        parts.append(str(event["timestamp"]))
    for key in ("node", "name", "status", "latest_node"):
        if event.get(key):
            parts.append(f"{key}={event[key]}")
    if event.get("task"):
        parts.append(f"task={str(event['task'])[:80]}")
    return " - ".join(parts)


def _merge_head_tail(
    head: list[dict[str, Any]],
    tail: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events = list(head)
    for event in tail:
        if event not in events:
            events.append(event)
    return events


def _extract_node(event: dict[str, Any]) -> str:
    node = event.get("node")
    if node:
        return str(node)
    if len(event) == 1:
        return str(next(iter(event)))
    return "unknown"


def _parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)


def _append_event(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(event, ensure_ascii=False, default=_json_default) + "\n"
        )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
        newline="\n",
    )


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseMessage):
        return {
            "type": value.__class__.__name__,
            "content": value.content,
        }
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return str(value)

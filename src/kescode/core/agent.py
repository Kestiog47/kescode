"""Graph-driven agent event stream for KesCode."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from kescode.core.approval import ApprovalHandler
from kescode.core.checkpoint import CheckpointManager
from kescode.core.paths import ensure_workspace
from kescode.core.state import RuntimeState
from kescode.core.trace import TraceRecorder
from kescode.graph.state import KesGraphState
from kescode.graph.workflow import build_workflow

DEFAULT_APPROVAL_MODE = "inline"
DEFAULT_CHECKPOINT_MODE = "light"
DEFAULT_TRACE_MODE = "on"

NODE_TITLES = {
    "planner": "Planner",
    "verifier": "Verifier",
    "final": "Final",
}

_CHECKPOINT_CUSTOM_EVENTS = {"handoff", "tool_result"}


def create_runtime(
    workspace: Path,
    *,
    approval_mode: str = DEFAULT_APPROVAL_MODE,
    approval_handler: ApprovalHandler | None = None,
    checkpoint_mode: str = DEFAULT_CHECKPOINT_MODE,
    resume_from: Path | str | None = None,
    trace_mode: str = DEFAULT_TRACE_MODE,
) -> RuntimeState:
    """Build runtime state, preferring the resume workspace when provided."""

    active_workspace = ensure_workspace(
        Path(resume_from) if resume_from is not None else Path(workspace)
    )
    return RuntimeState(
        workspace=active_workspace,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        checkpoint_mode=checkpoint_mode,
        trace_mode=trace_mode,
    )


def stream_agent_events(
    task: str,
    *,
    workspace: Path,
    max_attempts: int = 3,
    approval_mode: str = DEFAULT_APPROVAL_MODE,
    approval_handler: ApprovalHandler | None = None,
    checkpoint_mode: str = DEFAULT_CHECKPOINT_MODE,
    resume_workspace: Path | str | None = None,
    trace_mode: str = DEFAULT_TRACE_MODE,
) -> Iterator[dict[str, Any]]:
    """Run the LangGraph workflow and yield unified events for the CLI."""

    active_workspace = ensure_workspace(
        Path(resume_workspace) if resume_workspace is not None else Path(workspace)
    )
    load_dotenv(active_workspace / ".env")
    runtime = create_runtime(
        workspace,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        checkpoint_mode=checkpoint_mode,
        resume_from=resume_workspace,
        trace_mode=trace_mode,
    )
    manager = CheckpointManager(runtime, task=task)
    trace = TraceRecorder(runtime, task=task)

    if resume_workspace is not None:
        inputs, resume_event = CheckpointManager.load_resume_inputs(
            runtime,
            task=task,
            max_attempts=max_attempts,
        )
    else:
        inputs = _fresh_inputs(task, runtime, max_attempts)
        resume_event = None

    current_state: dict[str, Any] = dict(inputs)
    latest_node: str | None = None

    trace.start(
        inputs,
        resumed=resume_event is not None,
        resume_event=resume_event,
    )
    _record_checkpoint(
        manager,
        trace,
        current_state,
        status="started",
        latest_node="start",
    )

    workflow = build_workflow()
    try:
        for mode, chunk in workflow.stream(
            inputs,
            stream_mode=["updates", "custom"],
        ):
            if mode == "custom":
                event = _custom_event(chunk)
                trace.record_custom_event(event)
                latest_node = str(event.get("node") or latest_node or "")
                if manager.mode == "strict" or _custom_event_needs_checkpoint(
                    event
                ):
                    _record_checkpoint(
                        manager,
                        trace,
                        current_state,
                        status="running",
                        latest_node=latest_node,
                        event=event,
                    )
                yield {"type": "custom_event", "event": event}
            elif mode == "updates":
                graph_event = dict(chunk)
                trace.record_graph_update(graph_event)
                for node, update in chunk.items():
                    latest_node = node
                    current_state.update(update)
                _record_checkpoint(
                    manager,
                    trace,
                    current_state,
                    status="running",
                    latest_node=latest_node,
                    event=graph_event,
                )
                yield {"type": "graph_event", "event": graph_event}
    except KeyboardInterrupt:
        _record_checkpoint(
            manager,
            trace,
            current_state,
            status="interrupted",
            latest_node=latest_node,
        )
        trace.end(
            status="interrupted",
            latest_node=latest_node,
            final_state=current_state,
        )
        raise
    else:
        _record_checkpoint(
            manager,
            trace,
            current_state,
            status="finished",
            latest_node=latest_node,
        )
        trace.end(
            status="finished",
            latest_node=latest_node,
            final_state=current_state,
        )


def _fresh_inputs(
    task: str,
    runtime: RuntimeState,
    max_attempts: int,
) -> KesGraphState:
    return {
        "task": task,
        "runtime": runtime,
        "messages": [],
        "attempts": 0,
        "max_attempts": max_attempts,
    }


def _custom_event_needs_checkpoint(event: dict[str, Any]) -> bool:
    return event.get("type") in _CHECKPOINT_CUSTOM_EVENTS


def _record_checkpoint(
    manager: CheckpointManager,
    trace: TraceRecorder,
    current_state: dict[str, Any],
    *,
    status: str,
    latest_node: str | None,
    event: dict[str, Any] | None = None,
) -> None:
    saved_event = manager.save(
        current_state,
        status=status,
        latest_node=latest_node,
        event=event,
    )
    if saved_event is not None:
        trace.record_custom_event(saved_event)


def _node_update_events(
    node: str,
    update: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    if node == "final":
        yield {
            "type": "final_answer",
            "node": "Final",
            "content": str(update.get("final_answer") or ""),
        }
        return

    data = dict(update)
    if node == "planner":
        data.pop("messages", None)

    yield {
        "type": "node_output",
        "node": NODE_TITLES.get(node, node),
        "data": data,
    }


def _custom_event(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {
            "type": "custom",
            "node": "Planner",
            "content": data,
        }

    event = dict(data)
    event.setdefault("type", "custom")
    node = "Planner"
    if event.get("type") == "handoff":
        node = str(event.get("to") or "Planner")
    event.setdefault("node", node)
    return event

"""Graph-driven agent event stream for KesCode."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from kescode.core.approval import ApprovalHandler
from kescode.core.checkpoint import CheckpointManager
from kescode.core.paths import ensure_workspace
from kescode.core.session import (
    SESSION_FILE,
    SESSION_ROOT,
    append_assistant_turn,
    append_user_turn,
    build_session_context,
    load_or_create_session,
    save_session,
)
from kescode.core.state import RuntimeState
from kescode.core.trace import TraceRecorder
from kescode.graph.state import KesGraphState
from kescode.graph.workflow import (
    build_complex_workflow,
    build_entry_workflow,
    build_workflow,
)

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
    workflow_factory: Callable[[], Any] | None = None,
    session_id: str | None = None,
    session_turn: int | None = None,
    session_context: str | None = None,
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
    if session_id is not None:
        inputs["session_id"] = session_id
    if session_turn is not None:
        inputs["session_turn"] = session_turn
    if session_context is not None:
        inputs["session_context"] = session_context

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

    workflow = (workflow_factory or build_workflow)()
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


def stream_session_events(
    task: str,
    *,
    session_workspace: Path | str | None = None,
    workspace: Path | str | None = None,
    max_attempts: int = 3,
    approval_mode: str = DEFAULT_APPROVAL_MODE,
    approval_handler: ApprovalHandler | None = None,
    checkpoint_mode: str = DEFAULT_CHECKPOINT_MODE,
    resume_workspace: Path | str | None = None,
    trace_mode: str = DEFAULT_TRACE_MODE,
) -> Iterator[dict[str, Any]]:
    """支持多轮对话的事件流。

    1. 加载或创建 Session
    2. 记录用户 turn
    3. 构建 session_context
    4. 运行入口图（intent_router → chat/workflow）
       - 如果 chat：直接回复，记录 assistant turn
       - 如果 workflow：运行 build_complex_workflow()，记录 assistant turn
    5. 每次 session turn 的 session_context 都包含当前 workspace 文件清单和最近对话摘要
    """

    active_workspace = ensure_workspace(
        Path(workspace)
        if workspace is not None
        else Path(session_workspace or Path.cwd())
    )
    session_ws = ensure_workspace(
        Path(session_workspace)
        if session_workspace is not None
        else active_workspace
    )
    load_dotenv(active_workspace / ".env")

    session = load_or_create_session(session_ws)
    yield _session_event(
        "session_loaded",
        session_id=session["session_id"],
        turn_index=session["turn_index"],
    )

    turn = append_user_turn(session, task)
    yield _session_event(
        "user_turn",
        session_id=session["session_id"],
        turn=turn,
        content=task,
    )

    session_context = build_session_context(active_workspace, session)
    yield _session_event(
        "session_context",
        session_id=session["session_id"],
        turn=turn,
        content=session_context,
    )

    runtime = create_runtime(
        active_workspace,
        approval_mode=approval_mode,
        approval_handler=approval_handler,
        checkpoint_mode=checkpoint_mode,
        trace_mode=trace_mode,
    )
    inputs = _session_inputs(
        task,
        runtime,
        max_attempts,
        session,
        turn,
        session_context,
    )

    entry_state = dict(inputs)
    route = "workflow"
    entry_final = ""
    entry_graph = build_entry_workflow()
    for mode, chunk in entry_graph.stream(
        entry_state,
        stream_mode=["updates", "custom"],
    ):
        if mode == "custom":
            event = _custom_event(chunk)
            yield {"type": "custom_event", "event": event}
            continue
        if mode != "updates":
            continue

        graph_event = dict(chunk)
        for update in graph_event.values():
            entry_state.update(update)
        yield {"type": "graph_event", "event": graph_event}
        if "intent_router" in graph_event:
            intent_update = graph_event["intent_router"]
            route = str(intent_update.get("intent_route") or route)
            yield {
                "type": "intent_route",
                "route": route,
                "reason": str(intent_update.get("intent_reason") or ""),
                "confidence": intent_update.get("intent_confidence", 0.0),
            }
        if "chat_responder" in graph_event:
            chat_data = graph_event["chat_responder"]
            entry_final = str(
                chat_data.get("final_answer")
                or chat_data.get("chat_response")
                or ""
            )

    route = str(entry_state.get("intent_route") or route)
    if route not in {"chat", "workflow"}:
        route = "workflow"

    if route == "chat":
        final_content = (
            entry_final
            or str(
                entry_state.get("chat_response")
                or entry_state.get("final_answer")
                or ""
            )
        )
        if not final_content:
            final_content = "I can help with that conversationally."
        yield {
            "type": "final_answer",
            "node": "Chat",
            "content": final_content,
        }
    else:
        final_content = ""
        for event in stream_agent_events(
            task,
            workspace=active_workspace,
            max_attempts=max_attempts,
            approval_mode=approval_mode,
            approval_handler=approval_handler,
            checkpoint_mode=checkpoint_mode,
            resume_workspace=resume_workspace,
            trace_mode=trace_mode,
            workflow_factory=build_complex_workflow,
            session_id=session["session_id"],
            session_turn=turn,
            session_context=session_context,
        ):
            final_content = _extract_final_answer(event, final_content)
            yield event
        if not final_content:
            final_content = "Task completed successfully."

    append_assistant_turn(
        session,
        turn=turn,
        route=route,
        content=final_content,
        summary=final_content,
    )
    save_session(session_ws, session)
    assistant_record = session["recent_turns"][-1]
    yield _session_event(
        "assistant_turn",
        session_id=session["session_id"],
        turn=turn,
        route=route,
        content=assistant_record["content"],
        summary=assistant_record["summary"],
    )
    yield _session_event(
        "session_saved",
        session_id=session["session_id"],
        turn=turn,
        path=str(session_ws / SESSION_ROOT / SESSION_FILE),
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


def _session_inputs(
    task: str,
    runtime: RuntimeState,
    max_attempts: int,
    session: dict[str, Any],
    turn: int,
    session_context: str,
) -> dict[str, Any]:
    inputs = _fresh_inputs(task, runtime, max_attempts)
    inputs["session_id"] = str(session.get("session_id") or "")
    inputs["session_turn"] = int(turn)
    inputs["session_context"] = session_context
    return inputs


def _session_event(event_type: str, **data: Any) -> dict[str, Any]:
    return {
        "type": "session_event",
        "event": {"type": event_type, **data},
    }


def _extract_final_answer(
    event: dict[str, Any],
    current: str,
) -> str:
    if event.get("type") == "graph_event":
        graph_event = event.get("event") or {}
        final_update = graph_event.get("final")
        if isinstance(final_update, dict):
            return str(final_update.get("final_answer") or current)
    if event.get("type") == "custom_event":
        inner = event.get("event") or {}
        if isinstance(inner, dict) and inner.get("type") == "final_answer":
            return str(inner.get("content") or current)
    return current


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

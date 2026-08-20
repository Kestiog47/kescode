"""ReAct implementation agent backed by workspace tools."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from kescode.core.state import RuntimeState
from kescode.graph.memory import (
    build_layered_memory,
    format_layered_memory_for_prompt,
    memory_event,
)
from kescode.providers.openai_provider import create_model
from kescode.tools.registry import build_tools
from kescode.tools.todo_tools import TodoStore, TodoUpdateTool

CODE_AGENT_PROMPT = """You are codeAgent, a focused implementation specialist.

You implement the planner's instruction inside the workspace using file and
shell tools.

Rules:
- You must update todo progress explicitly.
- Before starting a todo, call TodoUpdateTool with status "in_progress".
- After finishing that todo, call TodoUpdateTool with status "completed".
- If a todo is impossible, call TodoUpdateTool with status "blocked" and explain.
- Use FileWriteTool for new files.
- Use FileReadTool before editing existing files.
- Use FileEditTool for focused edits.
- Use BashTool for non-interactive checks.
- Use NotepadAppendTool to record durable findings, decisions, important files,
  blockers, and next-step context that should survive compression.
- Use NotepadReadTool when you need to recover prior notes.
- BashTool already runs inside the workspace. Use relative paths, never "cd /workspace".
- Incorporate research notes and source URLs when the task asks for researched content.
- End with a concise summary of files changed and checks run.
"""

Writer = Callable[[dict[str, Any]], Any]


def run_code_agent(
    state: dict[str, Any],
    instruction: str,
    *,
    writer: Writer | None = None,
    max_loops: int = 10,
) -> dict[str, Any]:
    """Run a ReAct implementation loop and return the updated state."""

    runtime = _require_runtime(state)
    store = TodoStore(state.get("todos", []))
    tools = build_tools(runtime) + [TodoUpdateTool(store).to_tool()]
    model = create_model().bind_tools(tools)
    memory = build_layered_memory(state, node="codeAgent")
    _emit(writer, memory_event(memory, node="codeAgent"))
    messages: list[BaseMessage] = [
        SystemMessage(content=CODE_AGENT_PROMPT),
        HumanMessage(content=_code_agent_input(state, instruction, memory)),
    ]

    tool_by_name = {tool.name: tool for tool in tools}
    tool_events: list[dict[str, Any]] = []
    summary = ""

    for _ in range(max_loops):
        response = model.invoke(messages)
        messages.append(response)
        content = str(getattr(response, "content", "") or "").strip()
        if content:
            summary = content
        _emit(writer, {"type": "ai_message", "content": content})

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break

        for call in tool_calls:
            name = str(call.get("name", ""))
            args = _tool_call_args(call)
            call_event: dict[str, Any] = {
                "type": "tool_call",
                "name": name,
                "args": args,
            }
            tool_events.append(call_event)
            _emit(writer, call_event)

            result = _execute_tool(call, tool_by_name)
            if name == TodoUpdateTool.name:
                _persist_todos(state, store.as_list())

            messages.append(
                ToolMessage(
                    content=json.dumps(result, ensure_ascii=False, default=str),
                    tool_call_id=str(call.get("id") or ""),
                )
            )

            tool_result_event: dict[str, Any] = {
                "type": "tool_result",
                "name": name,
                "result": result,
            }
            tool_events.append(tool_result_event)
            _emit(writer, tool_result_event)
    else:
        suffix = "[Stopped after reaching max_loops.]"
        summary = f"{summary} {suffix}".strip() if summary else suffix

    _emit(writer, {"type": "final_answer", "content": summary})
    return {
        "ok": True,
        "summary": summary,
        "todos": store.as_list(),
        "messages": messages,
        "tool_events": tool_events,
    }


def _code_agent_input(
    state: dict[str, Any],
    instruction: str,
    memory: dict[str, Any],
) -> str:
    parts = [
        f"Task:\n{state.get('task') or ''}",
        f"Instruction:\n{instruction}",
        f"Session context:\n{_render_value(state.get('session_context') or '')}",
        f"Layered memory:\n{format_layered_memory_for_prompt(memory)}",
    ]
    return "\n\n".join(parts)


def _render_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _execute_tool(
    call: dict[str, Any],
    tool_by_name: dict[str, StructuredTool],
) -> Any:
    name = str(call.get("name", ""))
    tool = tool_by_name.get(name)
    if tool is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return tool.invoke(_tool_call_args(call))
    except Exception as exc:
        return {"error": str(exc)}


def _tool_call_args(call: dict[str, Any]) -> dict[str, Any]:
    args = call.get("args") or {}
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {}
    return args if isinstance(args, dict) else {}


def _require_runtime(state: dict[str, Any]) -> RuntimeState:
    runtime = state.get("runtime")
    if runtime is None:
        raise ValueError("Code agent state is missing a runtime.")
    return runtime


def _persist_todos(state: dict[str, Any], todos: list[dict[str, Any]]) -> None:
    state["todos"] = [dict(todo) for todo in todos]


def _emit(writer: Writer | None, event: dict[str, Any]) -> None:
    if writer is not None:
        writer(event)

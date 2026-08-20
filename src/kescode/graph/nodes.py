"""LangGraph nodes for the KesCode agent graph."""

from __future__ import annotations

import json
import locale
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool
from langgraph.config import get_stream_writer
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from pydantic import BaseModel, Field

from kescode.agents.code_agent import run_code_agent
from kescode.agents.search_agent import run_search_agent
from kescode.core.errors import KesCodeError
from kescode.core.state import RuntimeState
from kescode.graph.memory import (
    CompressionEvent,
    _short_text,
    _source_titles_and_urls,
    _trim_handoffs,
    build_layered_memory,
    format_layered_memory_for_prompt,
    memory_event,
)
from kescode.graph.state import (
    AgentHandoff,
    KesGraphState,
    VerificationCheck,
    VerificationResult,
)
from kescode.prompts.stage3 import PLANNER_PROMPT, VERIFIER_PROMPT
from kescode.prompts.stage4 import CONTEXT_COMPRESSION_PROMPT
from kescode.providers.openai_provider import create_model
from kescode.tools.registry import build_read_only_tools
from kescode.tools.todo_tools import TodoWriteTool

MAX_LOOPS = 10
VERIFICATION_TIMEOUT_SECONDS = 120.0
DEFAULT_CONTEXT_TOKEN_LIMIT = 400000


class CallSearchAgentArgs(BaseModel):
    instruction: str = Field(
        description="Research instruction to delegate to searchAgent."
    )


class CallCodeAgentArgs(BaseModel):
    instruction: str = Field(
        description="Implementation instruction to delegate to codeAgent."
    )


class CallSearchAgentTool:
    """Delegate a research task to searchAgent."""

    name = "call_search_agent"
    description = (
        "Delegate web/document research to searchAgent. Pass a focused research "
        "instruction; results are saved into research_notes and sources."
    )
    args_schema = CallSearchAgentArgs

    def __init__(
        self,
        state: KesGraphState,
        writer: Callable[[dict[str, Any]], Any],
    ) -> None:
        self.state = state
        self.writer = writer

    def run(self, instruction: str) -> dict[str, Any]:
        return _call_search_agent_tool(self.state, self.writer, instruction)

    def to_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.run,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )


class CallCodeAgentTool:
    """Delegate an implementation task to codeAgent."""

    name = "call_code_agent"
    description = (
        "Delegate file/code implementation to codeAgent. Pass a focused "
        "implementation instruction; results are saved into todos and "
        "code_agent_summary."
    )
    args_schema = CallCodeAgentArgs

    def __init__(
        self,
        state: KesGraphState,
        writer: Callable[[dict[str, Any]], Any],
    ) -> None:
        self.state = state
        self.writer = writer

    def run(self, instruction: str) -> dict[str, Any]:
        return _call_code_agent_tool(self.state, self.writer, instruction)

    def to_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.run,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )


def planner_node(state: KesGraphState) -> dict[str, Any]:
    """Coordinate specialist agents and publish the plan."""

    writer = get_stream_writer()
    tools = [
        TodoWriteTool().to_tool(),
        CallSearchAgentTool(state, writer).to_tool(),
        CallCodeAgentTool(state, writer).to_tool(),
    ]
    model = create_model().bind_tools(tools)
    memory = build_layered_memory(state, node="planner")
    writer(memory_event(memory, node="planner"))
    messages = [
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=_planner_input(state, memory)),
    ]
    result: dict[str, Any] = {}
    plan: dict[str, Any] = {}
    message_count = len(state.get("messages") or [])
    code_agent_delegated = False

    def on_tool_result(
        name: str,
        args: dict[str, Any],
        _tool_result: Any,
    ) -> None:
        nonlocal code_agent_delegated
        if name == TodoWriteTool.name:
            plan.update(_normalize_plan(args))
        elif name == CallCodeAgentTool.name:
            code_agent_delegated = True

    for event in _stream_react_loop(
        model,
        messages,
        tools,
        max_loops=MAX_LOOPS,
        result=result,
        on_tool_result=on_tool_result,
    ):
        if event["type"] in {"ai_message", "tool_call", "tool_result"}:
            writer({"node": "Planner", **event})

    if not plan:
        summary = str(result.get("summary") or "")
        if summary:
            data = _extract_json_object(summary, label="Planner")
            if not isinstance(data, dict):
                raise KesCodeError("Planner JSON must be an object.")
            plan = _normalize_plan(data)
        else:
            raise KesCodeError("Planner did not return a plan.")

    update: dict[str, Any] = {
        "plan_summary": plan["plan_summary"],
        "todos": state.get("todos") if code_agent_delegated else plan["todos"],
        "acceptance_criteria": plan["acceptance_criteria"],
        "verification_commands": plan["verification_commands"],
        "research_notes": state.get("research_notes", ""),
        "sources": state.get("sources", []),
        "agent_handoffs": state.get("agent_handoffs", []),
        "code_agent_summary": state.get("code_agent_summary", ""),
        "context_next_node": "verifier",
    }
    messages = state.get("messages") or []
    if len(messages) > message_count:
        update["messages"] = messages[message_count:]
    return update


def _call_search_agent_tool(
    state: KesGraphState,
    writer: Callable[[dict[str, Any]], Any],
    instruction: str,
) -> dict[str, Any]:
    writer(
        {
            "type": "handoff",
            "from": "planner",
            "to": "searchAgent",
            "instruction": instruction,
        }
    )
    result = run_search_agent(state, instruction, writer=writer)
    _record_handoff(state, "planner", "searchAgent", instruction, result)

    notes = str(result.get("summary") or "")
    existing_notes = str(state.get("research_notes") or "")
    state["research_notes"] = "\n\n".join(
        part for part in (existing_notes, notes) if part
    )
    state["sources"] = _merge_sources(
        state.get("sources") or [],
        result.get("sources") or [],
    )
    return result


def _call_code_agent_tool(
    state: KesGraphState,
    writer: Callable[[dict[str, Any]], Any],
    instruction: str,
) -> dict[str, Any]:
    writer(
        {
            "type": "handoff",
            "from": "planner",
            "to": "codeAgent",
            "instruction": instruction,
        }
    )
    result = run_code_agent(state, instruction, writer=writer)
    state["todos"] = [dict(todo) for todo in (result.get("todos") or [])]
    state["code_agent_summary"] = str(result.get("summary") or "")
    _record_handoff(state, "planner", "codeAgent", instruction, result)
    agent_messages = list(result.get("messages") or [])
    if len(agent_messages) > 2:
        agent_messages = agent_messages[2:]
    state["messages"] = state.get("messages", []) + agent_messages
    return result


def _record_handoff(
    state: KesGraphState,
    from_agent: str,
    to_agent: str,
    instruction: str,
    result: dict[str, Any],
) -> None:
    handoffs = list(state.get("agent_handoffs") or [])
    handoffs.append(
        AgentHandoff(
            from_agent=from_agent,
            to_agent=to_agent,
            instruction=instruction,
            result=str(result.get("summary") or ""),
        )
    )
    state["agent_handoffs"] = handoffs


def _merge_sources(
    existing: list[Any],
    incoming: list[Any],
) -> list[dict[str, Any]]:
    merged = [dict(source) for source in existing if isinstance(source, dict)]
    seen = {source.get("url") for source in merged}
    for source in incoming:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        if url and url in seen:
            continue
        if url:
            seen.add(url)
        merged.append(dict(source))
    return merged


def verifier_node(state: KesGraphState) -> dict[str, Any]:
    """Verify the code agent's work and record command results."""

    runtime = _require_runtime(state)
    tools = build_read_only_tools(runtime)
    model = create_model().bind_tools(tools)
    writer = _safe_stream_writer()
    memory = build_layered_memory(state, node="verifier")
    if writer is not None:
        writer(memory_event(memory, node="verifier"))
    messages = [
        SystemMessage(content=VERIFIER_PROMPT),
        HumanMessage(content=_verifier_input(state, memory)),
    ]

    result: dict[str, Any] = {}
    for _event in _stream_react_loop(
        model,
        messages,
        tools,
        max_loops=MAX_LOOPS,
        result=result,
    ):
        pass

    try:
        verdict = _parse_verifier_json(str(result.get("summary") or ""))
    except KesCodeError as exc:
        verdict = {
            "passed": False,
            "reason": str(exc),
            "checks": [],
            "recommended_next_instruction": (
                "Ask the codeAgent to review its work and retry."
            ),
        }

    checks = _normalize_checks(verdict.get("checks") or [])
    verification_results = [
        _run_verification_command(command, runtime.workspace)
        for command in state.get("verification_commands", [])
    ]
    commands_passed = all(r["ok"] for r in verification_results)
    passed = bool(verdict.get("passed", False)) and commands_passed
    attempts = int(state.get("attempts") or 0) + 1
    reason = str(verdict.get("reason") or "")

    if not commands_passed:
        failed_commands = [r["command"] for r in verification_results if not r["ok"]]
        command_note = "Verification commands failed: " + ", ".join(failed_commands)
        reason = f"{reason} {command_note}".strip()

    update: dict[str, Any] = {
        "passed": passed,
        "attempts": attempts,
        "verification_results": verification_results,
        "verification_checks": checks,
        "todos": _updated_todos(state.get("todos", []), passed),
    }
    if not passed:
        update["last_error"] = _failure_error(reason, checks, verification_results)
        max_attempts = state.get("max_attempts")
        if max_attempts is not None and attempts >= max_attempts:
            update["context_next_node"] = "final"
        else:
            update["context_next_node"] = "planner"
    else:
        update["context_next_node"] = "final"
    return update


def verifier_route(state: KesGraphState) -> str:
    """Route to the final node or back to the planner."""

    if state.get("passed"):
        return "final"

    max_attempts = state.get("max_attempts")
    attempts = state.get("attempts")
    if (attempts or 0) >= (max_attempts if max_attempts is not None else 1):
        return "final"
    return "planner"


def context_monitor_node(state: KesGraphState) -> dict[str, Any]:
    """Estimate prompt token usage and decide whether compression is needed."""

    messages = list(state.get("messages") or [])
    memory_payload = HumanMessage(
        content=format_layered_memory_for_prompt(
            build_layered_memory(state, node="context_monitor")
        )
    )
    payload_messages = messages + [memory_payload]
    text = _messages_text(payload_messages)

    try:
        model = create_model()
        token_count = int(model.get_num_tokens_from_messages(payload_messages))
    except Exception:
        token_count = len(text) // 4

    token_limit = int(
        state.get("context_token_limit") or DEFAULT_CONTEXT_TOKEN_LIMIT
    )
    return {
        "context_token_count": token_count,
        "context_should_compress": token_count > token_limit,
        "context_next_node": state.get("context_next_node", "verifier"),
    }


def context_monitor_route(state: KesGraphState) -> str:
    """Route through the context monitor to compression or the next node."""

    if state.get("passed"):
        return "final"
    if state.get("context_should_compress"):
        return "context_compressor"
    return state.get("context_next_node", "verifier")


def context_compressor_route(state: KesGraphState) -> str:
    """Route after compression using the upstream next node."""

    return state.get("context_next_node", "verifier")


def context_compressor_node(state: KesGraphState) -> dict[str, Any]:
    """Compress the message transcript into a durable summary."""

    model = create_model()
    transcript = _messages_text(state.get("messages") or [])
    memory_text = format_layered_memory_for_prompt(
        build_layered_memory(state, node="context_compressor")
    )
    response = model.invoke(
        [
            SystemMessage(content=CONTEXT_COMPRESSION_PROMPT),
            HumanMessage(
                content=(
                    "Current message transcript:\n"
                    f"{transcript}\n\n"
                    "Layered memory snapshot:\n"
                    f"{memory_text}"
                )
            ),
        ]
    )
    data = _extract_json_object(
        str(getattr(response, "content", "") or ""),
        label="Context compressor",
    )
    if not isinstance(data, dict):
        raise KesCodeError("Context compressor JSON must be an object.")

    summary = str(data.get("summary") or "").strip()
    if not summary:
        raise KesCodeError("Context compressor returned an empty summary.")

    _write_history_summary(state, summary)
    new_token_count = _count_tokens(model, summary)
    compression_event: CompressionEvent = {
        "node": "context_compressor",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": "context exceeded token limit",
        "summary": _short_text(summary, 500),
        "token_count": new_token_count,
    }
    compression_events = list(state.get("compression_events") or [])
    compression_events.append(compression_event)

    return {
        "messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            AIMessage(content=summary),
        ],
        "context_summary": summary,
        "context_token_count": new_token_count,
        "context_should_compress": False,
        "research_notes": _short_text(state.get("research_notes", ""), 1600),
        "code_agent_summary": _short_text(
            state.get("code_agent_summary", ""),
            1000,
        ),
        "verifier_summary": _short_text(state.get("verifier_summary", ""), 1000),
        "last_error": _short_text(state.get("last_error", ""), 1400),
        "plan_summary": _short_text(state.get("plan_summary", ""), 1000),
        "sources": _source_titles_and_urls(state.get("sources", [])),
        "agent_handoffs": _trim_handoffs(state.get("agent_handoffs", [])),
        "history_summary": summary,
        "compression_events": compression_events,
    }


def final_node(state: KesGraphState) -> dict[str, Any]:
    """Format the final outcome as user-facing text."""

    if state.get("passed"):
        summary = state.get("code_agent_summary") or ""
        final_answer = "Task completed successfully."
        if summary:
            final_answer += f"\n\n{summary}"
    else:
        attempts = state.get("attempts") or 0
        reason = state.get("last_error") or "No failure details were recorded."
        final_answer = f"Task failed after {attempts} attempt(s).\n\n{reason}"

    return {"final_answer": final_answer}


def _planner_instruction(state: KesGraphState) -> str:
    parts = [f"Task:\n{state.get('task') or ''}"]
    if state.get("plan_summary") or state.get("todos"):
        parts.append(f"Current plan:\n{_plan_snapshot(state)}")
    if state.get("research_notes"):
        parts.append(f"Research notes:\n{state['research_notes']}")
    if state.get("sources"):
        parts.append(
            "Research sources:\n"
            + json.dumps(state["sources"], ensure_ascii=False, indent=2)
        )
    if state.get("code_agent_summary"):
        parts.append(f"Code agent summary:\n{state['code_agent_summary']}")
    if state.get("last_error"):
        parts.append(f"Previous verification error:\n{state['last_error']}")
    return "\n\n".join(parts)


def _planner_input(
    state: KesGraphState,
    memory: dict[str, Any],
) -> str:
    """Build the planner prompt with layered memory appended."""

    parts = [_planner_instruction(state)]
    parts.append(f"Layered memory:\n{format_layered_memory_for_prompt(memory)}")
    return "\n\n".join(parts)


def _messages_text(messages: list[Any]) -> str:
    """Join message contents for deterministic fallback token estimates."""

    parts: list[str] = []
    for message in messages:
        if isinstance(message, BaseMessage):
            content = message.content
            parts.append(content if isinstance(content, str) else str(content))
        else:
            parts.append(str(message))
    return "\n".join(parts)


def _count_tokens(model: Any, text: str) -> int:
    """Estimate token count, falling back to a character-based estimate."""

    try:
        return int(model.get_num_tokens(text))
    except Exception:
        try:
            return int(
                model.get_num_tokens_from_messages([AIMessage(content=text)])
            )
        except Exception:
            return len(text) // 4


def _verifier_instruction(state: KesGraphState) -> str:
    return "\n\n".join(
        [
            f"Plan summary:\n{state.get('plan_summary') or ''}",
            "Acceptance criteria:\n"
            + json.dumps(
                state.get("acceptance_criteria", []),
                ensure_ascii=False,
                indent=2,
            ),
            "Verification commands:\n"
            + json.dumps(
                state.get("verification_commands", []),
                ensure_ascii=False,
                indent=2,
            ),
            f"Latest codeAgent output:\n{state.get('code_agent_summary') or ''}",
        ]
    )


def _verifier_input(
    state: KesGraphState,
    memory: dict[str, Any],
) -> str:
    """Build the verifier prompt with layered memory appended."""

    parts = [_verifier_instruction(state)]
    parts.append(f"Layered memory:\n{format_layered_memory_for_prompt(memory)}")
    return "\n\n".join(parts)


def _plan_snapshot(state: KesGraphState) -> str:
    return json.dumps(
        {
            "plan_summary": state.get("plan_summary", ""),
            "todos": state.get("todos", []),
            "acceptance_criteria": state.get("acceptance_criteria", []),
            "verification_commands": state.get("verification_commands", []),
        },
        ensure_ascii=False,
        indent=2,
    )


def _normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    raw_todos = plan.get("todos") or []
    todos = []
    for index, item in enumerate(raw_todos):
        if not isinstance(item, dict):
            continue
        todos.append(
            {
                "id": str(item.get("id") or f"todo-{index + 1}"),
                "content": str(item.get("content") or ""),
                "status": str(item.get("status") or "pending"),
                "note": str(item.get("note") or ""),
            }
        )

    return {
        "plan_summary": str(plan.get("plan_summary") or "").strip(),
        "todos": todos,
        "acceptance_criteria": [
            str(item) for item in (plan.get("acceptance_criteria") or [])
        ],
        "verification_commands": [
            str(item) for item in (plan.get("verification_commands") or [])
        ],
    }


def _parse_verifier_json(content: str) -> dict[str, Any]:
    data = _extract_json_object(content, label="Verifier")
    if not isinstance(data, dict):
        raise KesCodeError("Verifier JSON must be an object.")
    return data


def _extract_json_object(content: str, *, label: str) -> Any:
    cleaned = _strip_code_fence(content.strip())
    if not cleaned:
        raise KesCodeError(f"{label} returned no JSON.")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    while start != -1:
        end = cleaned.rfind("}")
        if end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
        start = cleaned.find("{", start + 1)

    raise KesCodeError(f"{label} returned invalid JSON: {content}")


def _strip_code_fence(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _normalize_checks(raw_checks: list[Any]) -> list[VerificationCheck]:
    checks: list[VerificationCheck] = []
    for index, item in enumerate(raw_checks):
        if not isinstance(item, dict):
            continue
        checks.append(
            {
                "name": str(item.get("name") or f"check-{index + 1}"),
                "passed": bool(item.get("passed", False)),
                "detail": str(item.get("detail") or ""),
            }
        )
    return checks


def _updated_todos(todos: list[Any], passed: bool) -> list[Any]:
    updated = [dict(todo) for todo in todos]
    for todo in updated:
        if passed:
            if todo.get("status") != "completed":
                todo["status"] = "completed"
                if not todo.get("note"):
                    todo["note"] = "Verification passed."
        elif todo.get("status") == "in_progress":
            todo["status"] = "blocked"
            if not todo.get("note"):
                todo["note"] = "Verification failed; needs revision."
    return updated


def _failure_error(
    reason: str,
    checks: list[VerificationCheck],
    results: list[VerificationResult],
) -> str:
    lines = [reason] if reason else []
    failed_checks = [check["name"] for check in checks if not check["passed"]]
    if failed_checks:
        lines.append("Failed checks: " + ", ".join(failed_checks))
    failed_commands = [result["command"] for result in results if not result["ok"]]
    if failed_commands:
        lines.append(
            "Failed verification commands: " + ", ".join(failed_commands)
        )
    return "\n".join(lines) or "Verification failed without a specific reason."


def _run_verification_command(
    command: str,
    workspace: Path,
) -> VerificationResult:
    env = os.environ.copy()
    env["KESCODE_WORKSPACE"] = str(workspace)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    effective_command, requested_timeout, timeout_is_pass = _portable_timeout_command(
        command
    )
    effective_command = _use_current_python(effective_command)
    timeout_seconds = (
        requested_timeout
        if requested_timeout is not None
        else VERIFICATION_TIMEOUT_SECONDS
    )
    shell = requested_timeout is None

    try:
        process = subprocess.Popen(
            effective_command,
            shell=shell,
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            creationflags=creationflags,
        )
    except OSError as exc:
        return VerificationResult(
            command=command,
            ok=False,
            exit_code=None,
            stdout="",
            stderr=str(exc),
        )

    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return VerificationResult(
            command=command,
            ok=process.returncode == 0,
            exit_code=process.returncode,
            stdout=_decode_output(stdout),
            stderr=_decode_output(stderr),
        )
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        stdout, stderr = process.communicate()
        stderr_text = _decode_output(stderr)
        if stderr_text:
            stderr_text += "\n"
        stderr_text += (
            f"[timed out after {timeout_seconds:g} seconds]"
        )
        return VerificationResult(
            command=command,
            ok=timeout_is_pass,
            exit_code=124,
            stdout=_decode_output(stdout),
            stderr=stderr_text,
        )


def _portable_timeout_command(
    command: str,
) -> tuple[str, float | None, bool]:
    """Translate a GNU timeout idiom on Windows, where cmd.exe lacks it."""

    if os.name != "nt":
        return command, None, False

    stripped = command.strip()
    suffix_pattern = r"\|\|\s*\[\s*\$\?\s*-eq\s*124\s*\]\s*$"
    timeout_is_pass = re.search(suffix_pattern, stripped, re.IGNORECASE) is not None
    without_suffix = re.sub(
        suffix_pattern,
        "",
        stripped,
        flags=re.IGNORECASE,
    ).strip()

    match = re.match(
        r"^timeout\s+(\d+(?:\.\d+)?)s?\s+(.+)$",
        without_suffix,
        re.IGNORECASE,
    )
    if match is None:
        return command, None, False
    return match.group(2).strip(), float(match.group(1)), timeout_is_pass


def _use_current_python(command: str) -> str:
    stripped = command.strip()
    for prefix in ("python ", "python3 "):
        if stripped.startswith(prefix):
            rest = stripped[len(prefix) :].strip()
            executable = f'"{sys.executable}"' if os.name == "nt" else sys.executable
            return f"{executable} {rest}".strip()

    if os.name == "nt":
        match = re.match(
            r"^(.+?[\\/]python(?:3)?\.exe)(\s+|$)",
            stripped,
            re.IGNORECASE,
        )
        if match and " " in match.group(1):
            rest = stripped[match.end() :].strip()
            return f'"{match.group(1)}" {rest}'.strip()
    return command


def _kill_process_tree(process: subprocess.Popen) -> None:
    if os.name == "nt" and process.poll() is None:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
        )
    if process.poll() is None:
        process.kill()


def _safe_stream_writer() -> Callable[[dict[str, Any]], Any] | None:
    """Return the LangGraph stream writer outside graph execution when absent."""

    try:
        return get_stream_writer()
    except Exception:
        return None


def _stream_react_loop(
    model: Any,
    messages: list[BaseMessage],
    tools: list[StructuredTool],
    *,
    max_loops: int,
    result: dict[str, Any],
    on_tool_result: Callable[[str, dict[str, Any], Any], None] | None = None,
) -> Iterator[dict[str, Any]]:
    tool_by_name = {tool.name: tool for tool in tools}
    last_content = ""

    for _ in range(max_loops):
        response = model.invoke(messages)
        messages.append(response)
        content = str(response.content or "")
        if content:
            last_content = content
        yield {"type": "ai_message", "content": content}

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break

        for call in tool_calls:
            name = str(call.get("name", ""))
            args = _tool_call_args(call)
            yield {"type": "tool_call", "name": name, "args": args}

            tool_result = _execute_tool(call, tool_by_name)
            if on_tool_result is not None:
                on_tool_result(name, args, tool_result)
            messages.append(
                ToolMessage(
                    content=json.dumps(
                        tool_result,
                        ensure_ascii=False,
                        default=str,
                    ),
                    tool_call_id=str(call.get("id") or ""),
                )
            )
            yield {"type": "tool_result", "name": name, "result": tool_result}
    else:
        suffix = "[Stopped after reaching max_loops.]"
        last_content = f"{last_content} {suffix}".strip() if last_content else suffix

    result["messages"] = messages
    result["summary"] = last_content
    yield {"type": "final_answer", "content": last_content, "messages": messages}


def _execute_tool(
    call: dict[str, Any],
    tool_by_name: dict[str, StructuredTool],
) -> object:
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


def _require_runtime(state: KesGraphState) -> RuntimeState:
    runtime = state.get("runtime")
    if runtime is None:
        raise KesCodeError("Graph state is missing a runtime.")
    return runtime


def _write_history_summary(state: KesGraphState, summary: str) -> None:
    """Persist the latest compressed history into the workspace."""

    target = _require_runtime(state).workspace / "HISTORY_SUMMARY.md"
    try:
        target.write_text(summary, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise KesCodeError(
            f"Unable to write HISTORY_SUMMARY.md: {exc}"
        ) from exc


def _decode_output(data: bytes) -> str:
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False)
        return data.decode(encoding, errors="replace")

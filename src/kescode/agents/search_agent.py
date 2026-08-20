"""ReAct research agent backed by WebSearchTool."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from kescode.providers.openai_provider import create_model
from kescode.tools.web_search_tool import WebSearchTool

SEARCH_AGENT_PROMPT = """You are searchAgent, a focused research specialist.

Your only external capability is WebSearchTool. Search for reliable information
needed by the planner and codeAgent.

Rules:

- Use WebSearchTool for factual research.
- Prefer official or encyclopedia-style sources when available.
- Return a concise research summary and list the useful source URLs.
- Do not write files or produce application code."""

Writer = Callable[[dict[str, Any]], Any]


def run_search_agent(
    state: dict[str, Any],
    instruction: str,
    *,
    writer: Writer | None = None,
    max_loops: int = 4,
) -> dict[str, Any]:
    """Run a ReAct search loop and return the collected research."""

    tool = WebSearchTool().to_tool()
    model = create_model().bind_tools([tool])
    messages: list[BaseMessage] = [
        SystemMessage(content=SEARCH_AGENT_PROMPT),
        HumanMessage(content=_search_instruction(state, instruction)),
    ]

    queries: list[str] = []
    sources: list[dict[str, Any]] = []
    tool_events: list[dict[str, Any]] = []
    summary = ""

    for _ in range(max_loops):
        response = model.invoke(messages)
        messages.append(response)
        content = str(getattr(response, "content", "") or "").strip()
        if content:
            summary = content

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break

        for call in tool_calls:
            args = _tool_call_args(call)
            name = str(call.get("name", ""))
            call_event: dict[str, Any] = {
                "type": "tool_call",
                "name": name,
                "args": args,
            }
            tool_events.append(call_event)
            _emit(writer, call_event)

            result = _execute_search(tool, call)
            query = str(args.get("query") or "")
            if query:
                queries.append(query)

            results = _dedupe_sources(sources, result.get("results") or [])
            answer = str(result.get("answer") or "")

            search_event: dict[str, Any] = {
                "type": "search_results",
                "query": query,
                "answer": answer,
                "results": results,
            }
            tool_events.append(search_event)
            _emit(writer, search_event)

            messages.append(
                ToolMessage(
                    content=json.dumps(result, ensure_ascii=False, default=str),
                    tool_call_id=str(call.get("id") or ""),
                )
            )
    else:
        suffix = "[Stopped after reaching max_loops.]"
        summary = f"{summary} {suffix}".strip() if summary else suffix

    return {
        "ok": True,
        "summary": summary,
        "queries": queries,
        "sources": sources,
        "messages": messages,
        "tool_events": tool_events,
    }


def _search_instruction(state: dict[str, Any], instruction: str) -> str:
    parts = [
        f"Task:\n{state.get('task') or ''}",
        f"Instruction:\n{instruction}",
    ]
    notes = state.get("research_notes") or ""
    if not isinstance(notes, str):
        notes = json.dumps(notes, ensure_ascii=False, indent=2)
    if notes:
        parts.append(f"Existing research notes:\n{notes}")
    return "\n\n".join(parts)


def _execute_search(
    tool: StructuredTool,
    call: dict[str, Any],
) -> dict[str, Any]:
    try:
        raw = tool.invoke(_tool_call_args(call))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"ok": False, "error": str(raw)}
    return data if isinstance(data, dict) else {"ok": False, "error": "unexpected search result"}


def _dedupe_sources(
    sources: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen = {source.get("url") for source in sources}
    added: list[dict[str, Any]] = []
    for result in results:
        url = result.get("url")
        if url and url not in seen:
            seen.add(url)
            added.append(result)
    sources.extend(added)
    return added


def _tool_call_args(call: dict[str, Any]) -> dict[str, Any]:
    args = call.get("args") or {}
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {}
    return args if isinstance(args, dict) else {}


def _emit(writer: Writer | None, event: dict[str, Any]) -> None:
    if writer is not None:
        writer(event)

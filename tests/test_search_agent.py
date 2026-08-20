"""Tests for the search agent and web search tool."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

from kescode.agents import search_agent
from kescode.tools import web_search_tool
from kescode.tools.web_search_tool import WebSearchTool


def test_missing_api_key(monkeypatch) -> None:
    real_getenv = os.getenv

    def fake_getenv(key: str, default: str | None = None) -> str | None:
        if key == "TAVILY_API_KEY":
            return None
        return real_getenv(key, default)

    monkeypatch.setattr(web_search_tool.os, "getenv", fake_getenv)

    result = WebSearchTool().search("query")
    assert result == {"ok": False, "error": "missing TAVILY_API_KEY"}
    assert json.loads(WebSearchTool().run("query"))["error"] == "missing TAVILY_API_KEY"


def test_run_search_agent_react_loop(monkeypatch) -> None:
    search_calls: list[dict] = []
    responses = [
        SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "name": "web_search",
                    "id": "call-1",
                    "args": {"query": "python 3.14"},
                }
            ],
        ),
        SimpleNamespace(content="Python 3.14 is stable.", tool_calls=[]),
    ]

    class FakeTool:
        name = "web_search"

        def invoke(self, args: dict) -> str:
            search_calls.append(args)
            return json.dumps(
                {
                    "ok": True,
                    "query": args["query"],
                    "answer": "Python 3.14 overview.",
                    "results": [
                        {
                            "title": "Python Docs",
                            "url": "https://python.org",
                            "content": "Official documentation.",
                            "score": 0.9,
                        }
                    ],
                }
            )

    class FakeWebSearchTool:
        def to_tool(self) -> FakeTool:
            return FakeTool()

    class FakeModel:
        def __init__(self) -> None:
            self.index = 0

        def bind_tools(self, tools):
            assert len(tools) == 1
            return self

        def invoke(self, messages):
            response = responses[self.index]
            self.index += 1
            return response

    monkeypatch.setattr(search_agent, "create_model", lambda: FakeModel())
    monkeypatch.setattr(search_agent, "WebSearchTool", FakeWebSearchTool)

    events: list[dict] = []
    result = search_agent.run_search_agent(
        {"task": "Research Python", "research_notes": ["existing note"]},
        "Find official docs",
        writer=events.append,
        max_loops=2,
    )

    assert search_calls == [{"query": "python 3.14"}]
    assert result["ok"] is True
    assert result["queries"] == ["python 3.14"]
    assert result["sources"][0]["url"] == "https://python.org"
    assert result["summary"] == "Python 3.14 is stable."
    assert [event["type"] for event in events] == ["tool_call", "search_results"]
    assert [event["type"] for event in result["tool_events"]] == [
        "tool_call",
        "search_results",
    ]
    assert result["tool_events"][1]["answer"] == "Python 3.14 overview."
    assert result["messages"][0].type == "system"

"""Tavily-backed web search tool."""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from tavily import TavilyClient


class WebSearchArgs(BaseModel):
    query: str = Field(description="Search query to run through Tavily.")


class WebSearchTool:
    """Search the web and return concise factual results."""

    name = "web_search"
    description = (
        "Search the web for factual information. Returns the Tavily answer "
        "plus ranked results with titles, URLs, content, and scores."
    )
    args_schema = WebSearchArgs

    def search(self, query: str) -> dict[str, Any]:
        api_key = os.getenv("TAVILY_API_KEY", "tvly-REPLACED")
        if not api_key:
            return {"ok": False, "error": "missing TAVILY_API_KEY"}

        try:
            data = TavilyClient(api_key=api_key).search(
                query=query,
                include_answer=True,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "query": query,
            "answer": str(data.get("answer") or ""),
            "results": [_normalize_result(item) for item in data.get("results") or []],
        }

    def run(self, query: str) -> str:
        return json.dumps(self.search(query), ensure_ascii=False)

    def to_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.run,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )


def _normalize_result(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"title": "", "url": "", "content": "", "score": None}
    return {
        "title": str(item.get("title") or ""),
        "url": str(item.get("url") or ""),
        "content": str(item.get("content") or ""),
        "score": item.get("score"),
    }

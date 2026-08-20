"""Todo management tools used by the planner and specialist agents."""

from __future__ import annotations

import json
from typing import Literal

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, Field


class TodoItemArgs(BaseModel):
    id: str = Field(description="Stable identifier for the todo item.")
    content: str = Field(description="What needs to be done.")
    status: Literal["pending", "in_progress", "completed", "blocked"] = Field(
        default="pending",
        description="Current status of the todo item.",
    )
    note: str = Field(default="", description="Optional note attached to the item.")


class TodoWriteArgs(BaseModel):
    plan_summary: str = Field(description="Short summary of the overall plan.")
    todos: list[TodoItemArgs] = Field(
        description="Ordered work items the implementation agent should complete."
    )
    acceptance_criteria: list[str] = Field(
        description="Concrete conditions that must be true when the task is done."
    )
    verification_commands: list[str] = Field(
        description="Shell commands that verify the completed work."
    )


class TodoWriteTool:
    """Emit or revise the plan as a structured tool call."""

    name = "todo_write"
    description = (
        "Define or revise the plan. Call this once with the full plan, todos, "
        "acceptance criteria, and verification commands."
    )
    args_schema = TodoWriteArgs

    def run(
        self,
        plan_summary: str,
        todos: list[TodoItemArgs],
        acceptance_criteria: list[str],
        verification_commands: list[str],
    ) -> str:
        return json.dumps(
            {
                "ok": True,
                "plan_summary": plan_summary,
                "todo_count": len(todos),
            },
            ensure_ascii=False,
        )

    def to_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.run,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )


class TodoStore:
    """Mutable in-memory todo list shared by one implementation run."""

    def __init__(self, todos: list[dict] | None = None) -> None:
        self.todos: list[dict] = [dict(todo) for todo in (todos or [])]

    def as_list(self) -> list[dict]:
        return [dict(todo) for todo in self.todos]


class TodoUpdateArgs(BaseModel):
    id: str = Field(description="Id of the todo item to update.")
    status: Literal["pending", "in_progress", "completed", "blocked"] = Field(
        description="New status for the todo item."
    )
    note: str = Field(default="", description="Optional note attached to the item.")


class TodoUpdateTool:
    """Update the status or note of an existing todo item."""

    name = "todo_update"
    description = (
        "Mark a todo item as pending, in_progress, completed, or blocked. "
        "Use this to keep the plan status current while working."
    )
    args_schema = TodoUpdateArgs

    def __init__(self, store: TodoStore) -> None:
        self.store = store

    def run(self, id: str, status: str, note: str = "") -> str:
        for todo in self.store.todos:
            if todo.get("id") == id:
                todo["status"] = status
                if note:
                    todo["note"] = note
                return json.dumps({"ok": True, "todo": todo}, ensure_ascii=False)
        raise ToolException(f"Unknown todo id: {id}")

    def to_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.run,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )

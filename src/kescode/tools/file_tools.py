"""File read, write, and edit tools."""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, Field

from kescode.core.paths import describe_path, resolve_within_workspace
from kescode.core.state import RuntimeState


class FileReadArgs(BaseModel):
    file_path: str = Field(
        description="File path relative to the workspace, or an absolute path inside the workspace."
    )
    offset: int = Field(
        default=0, ge=0, description="Zero-based line offset where reading starts."
    )
    limit: int | None = Field(
        default=None,
        gt=0,
        description="Maximum number of lines to return. Omit to read the whole file.",
    )


class FileWriteArgs(BaseModel):
    file_path: str = Field(
        description="File path relative to the workspace, or an absolute path inside the workspace."
    )
    content: str = Field(description="Exact content to write to the file.")


class FileEditArgs(BaseModel):
    file_path: str = Field(
        description="File path relative to the workspace, or an absolute path inside the workspace."
    )
    old_text: str = Field(
        min_length=1, description="Exact text snippet that must appear exactly once."
    )
    new_text: str = Field(description="Replacement text for the matched snippet.")


class FileReadTool:
    """Read a text file, optionally from a line offset with a line limit."""

    name = "file_read"
    description = (
        "Read a UTF-8 text file from the workspace. Returns lines starting at a "
        "zero-based offset, limited to the requested line count."
    )
    args_schema = FileReadArgs

    def __init__(self, state: RuntimeState) -> None:
        self.state = state

    def run(self, file_path: str, offset: int = 0, limit: int | None = None) -> str:
        target = resolve_within_workspace(self.state.workspace, file_path)
        if not target.is_file():
            raise ToolException(f"Not a readable file: {file_path}")

        try:
            with target.open("r", encoding="utf-8", errors="replace") as handle:
                end = None if limit is None else offset + limit
                lines = [
                    line.rstrip("\r\n")
                    for line in itertools.islice(handle, offset, end)
                ]
        except OSError as exc:
            raise ToolException(f"Unable to read {file_path}: {exc}") from exc

        return "\n".join(lines)

    def to_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.run,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )


class FileWriteTool:
    """Create or overwrite a UTF-8 text file inside the workspace."""

    name = "file_write"
    description = (
        "Create a new file or overwrite an existing file with UTF-8 text. "
        "Parent directories are created automatically."
    )
    args_schema = FileWriteArgs

    def __init__(self, state: RuntimeState) -> None:
        self.state = state

    def run(self, file_path: str, content: str) -> str:
        target = resolve_within_workspace(self.state.workspace, file_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise ToolException(f"Unable to write {file_path}: {exc}") from exc

        display = describe_path(self.state.workspace, target)
        return f"Wrote {len(content.encode('utf-8'))} bytes to {display}"

    def to_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.run,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )


class FileEditTool:
    """Replace a text snippet that occurs exactly once in a file."""

    name = "file_edit"
    description = (
        "Replace an exact text snippet in a file. The snippet must occur exactly "
        "once; an ambiguous or missing match is an error."
    )
    args_schema = FileEditArgs

    def __init__(self, state: RuntimeState) -> None:
        self.state = state

    def run(self, file_path: str, old_text: str, new_text: str) -> str:
        if not old_text:
            raise ToolException("old_text must not be empty")

        target = resolve_within_workspace(self.state.workspace, file_path)
        try:
            raw = target.read_bytes()
        except OSError as exc:
            raise ToolException(f"Unable to read {file_path}: {exc}") from exc

        text = raw.decode("utf-8", errors="replace")
        count = text.count(old_text)
        if count == 0:
            raise ToolException(f"old_text not found in {file_path}")
        if count > 1:
            raise ToolException(
                f"old_text appears {count} times in {file_path}; expected exactly one match"
            )

        try:
            target.write_bytes(text.replace(old_text, new_text).encode("utf-8"))
        except OSError as exc:
            raise ToolException(f"Unable to edit {file_path}: {exc}") from exc

        display = describe_path(self.state.workspace, target)
        return f"Replaced one occurrence in {display}"

    def to_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.run,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )

"""Regular expression search tool."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, Field

from kescode.core.paths import describe_path, resolve_within_workspace
from kescode.core.state import RuntimeState

_SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "__pycache__", "node_modules"}


class GrepArgs(BaseModel):
    pattern: str = Field(description="Regular expression to search for.")
    path: str = Field(
        default=".",
        description="File or directory to search, relative to the workspace.",
    )
    glob: str | None = Field(
        default=None,
        description="Optional filename glob; only files with matching names are searched.",
    )
    head_limit: int = Field(
        default=200, gt=0, description="Maximum number of matching lines to return."
    )
    ignore_case: bool = Field(
        default=False, description="Search case-insensitively when true."
    )


class GrepTool:
    """Search files with a regular expression and return matching lines."""

    name = "grep"
    description = (
        "Search a file or directory tree with a regular expression. Returns up to "
        "head_limit matching lines as path:line:content."
    )
    args_schema = GrepArgs

    def __init__(self, state: RuntimeState) -> None:
        self.state = state

    def run(
        self,
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        head_limit: int = 200,
        ignore_case: bool = False,
    ) -> str:
        target = resolve_within_workspace(self.state.workspace, path)
        if not target.exists():
            raise ToolException(f"Path not found: {path}")

        flags = re.IGNORECASE if ignore_case else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            raise ToolException(f"Invalid regular expression: {exc}") from exc

        files = [target] if target.is_file() else list(self._iter_files(target, glob))
        if glob and target.is_file() and not fnmatch.fnmatch(target.name, glob):
            files = []

        matches: list[str] = []
        truncated = False

        for file in files:
            try:
                with file.open("r", encoding="utf-8", errors="replace") as handle:
                    for lineno, line in enumerate(handle, start=1):
                        if compiled.search(line):
                            display = describe_path(self.state.workspace, file)
                            matches.append(f"{display}:{lineno}:{line.rstrip()}")
                            if len(matches) >= head_limit:
                                truncated = True
                                break
            except OSError:
                continue

            if truncated:
                break

        if not matches:
            return "No matches found."

        result = f"{len(matches)} match(es):\n" + "\n".join(matches)
        if truncated:
            result += f"\n[truncated at head_limit={head_limit}]"
        return result

    def _iter_files(self, root: Path, glob: str | None) -> list[Path]:
        files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS]
            for filename in filenames:
                if glob and not fnmatch.fnmatch(filename, glob):
                    continue
                files.append(Path(dirpath) / filename)
        return files

    def to_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.run,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )

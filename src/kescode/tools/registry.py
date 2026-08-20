"""Tool registry used to bind tools to a model."""

from __future__ import annotations

from langchain_core.tools import StructuredTool

from kescode.core.approval import ApprovalHandler
from kescode.core.state import RuntimeState
from kescode.tools.bash_tool import BashTool
from kescode.tools.file_tools import FileEditTool, FileReadTool, FileWriteTool
from kescode.tools.grep_tool import GrepTool


def build_tools(
    state: RuntimeState,
    *,
    approval_mode: str | None = None,
    approval_handler: ApprovalHandler | None = None,
) -> list[StructuredTool]:
    """Build all workspace-bound tools for a runtime state."""

    return [
        FileReadTool(state).to_tool(),
        FileWriteTool(state).to_tool(),
        FileEditTool(state).to_tool(),
        GrepTool(state).to_tool(),
        BashTool(
            state,
            approval_mode=(
                approval_mode
                if approval_mode is not None
                else state.approval_mode
            ),
            approval_handler=(
                approval_handler
                if approval_handler is not None
                else state.approval_handler
            ),
        ).to_tool(),
    ]


def build_read_only_tools(state: RuntimeState) -> list[StructuredTool]:
    """Build tools that inspect the workspace without modifying it."""

    return [
        FileReadTool(state).to_tool(),
        GrepTool(state).to_tool(),
    ]

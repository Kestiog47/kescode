"""Command risk classification and approval helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


_COMMAND_BOUNDARY = r"(?:^|&&|\|\||;|\|)\s*"

RISK_PATTERNS: list[tuple[str, str]] = [
    (
        rf"{_COMMAND_BOUNDARY}(?:(?:python(?:[0-9.]*)\s+)?-m\s+)?pip\s+install\b",
        "Python package installation",
    ),
    (
        rf"{_COMMAND_BOUNDARY}uv\s+add\b",
        "Project dependency change with uv add",
    ),
    (
        rf"{_COMMAND_BOUNDARY}uv\s+sync\b",
        "Dependency synchronization with uv sync",
    ),
    (
        rf"{_COMMAND_BOUNDARY}uv\s+pip\s+install\b",
        "Python package installation with uv pip",
    ),
    (
        rf"{_COMMAND_BOUNDARY}npm\s+install\b",
        "Node package installation",
    ),
    (
        rf"{_COMMAND_BOUNDARY}pnpm\s+install\b",
        "Node package installation",
    ),
    (
        rf"{_COMMAND_BOUNDARY}yarn\s+(?:add|install)\b",
        "Node package installation",
    ),
    (
        rf"{_COMMAND_BOUNDARY}(?:curl|wget)\b",
        "Network download command",
    ),
    (
        rf"{_COMMAND_BOUNDARY}(?:python\s+-m\s+)?uvicorn\b",
        "Long-running development server",
    ),
    (
        rf"{_COMMAND_BOUNDARY}python\s+-m\s+http\.server\b",
        "Long-running development server",
    ),
]

VALID_APPROVAL_MODES = {"inline", "auto", "deny"}


@dataclass(frozen=True)
class ApprovalRequest:
    """A request to approve a command that was classified as risky."""

    id: str
    command: str
    risk_reason: str
    tool_name: str = "BashTool"


@dataclass(frozen=True)
class ApprovalDecision:
    """A human or policy decision for an approval request."""

    approved: bool
    reason: str = ""


ApprovalHandler = Callable[[ApprovalRequest], ApprovalDecision | bool]


def normalize_approval_mode(mode: str | None) -> str:
    """Return a valid approval mode, defaulting unknown values to inline."""

    if mode in VALID_APPROVAL_MODES:
        return mode
    return "inline"


def classify_command_risk(command: str) -> str | None:
    """Return the risk reason when a command matches, otherwise None."""

    for pattern, reason in RISK_PATTERNS:
        if re.search(pattern, command, re.MULTILINE):
            return reason
    return None

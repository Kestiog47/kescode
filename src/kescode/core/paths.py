"""Workspace path helpers and safety checks."""

from __future__ import annotations

import os
from pathlib import Path

from kescode.core.errors import KesCodeError


def ensure_workspace(workspace: Path) -> Path:
    """Resolve a workspace path and create it if necessary."""

    resolved = workspace.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def resolve_within_workspace(workspace: Path, path: str | Path) -> Path:
    """Resolve a path and reject anything that escapes the workspace."""

    workspace = ensure_workspace(workspace)
    candidate = (workspace / path).resolve(strict=False)

    workspace_text = os.path.normcase(str(workspace))
    candidate_text = os.path.normcase(str(candidate))
    if candidate_text != workspace_text and not candidate_text.startswith(
        workspace_text + os.sep
    ):
        raise KesCodeError(f"Path escapes the workspace: {path}")

    return candidate


def describe_path(workspace: Path, path: Path) -> str:
    """Return a path relative to the workspace when possible."""

    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)

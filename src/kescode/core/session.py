"""Workspace-backed conversation session management."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from kescode.core.errors import KesCodeError

SESSION_ROOT = ".kescode/session"
SESSION_FILE = "session.json"
SESSION_SUMMARY_FILE = "SESSION_SUMMARY.md"
MAX_SESSION_CONTEXT = 7000
MAX_TURN_CONTENT = 4000

_RECENT_CONTEXT_TURNS = 10
_RECENT_FILE_COUNT = 30
_IGNORED_DIRS = {
    ".agents",
    ".codex",
    ".git",
    ".idea",
    ".kescode",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "node_modules",
}

__all__ = [
    "MAX_SESSION_CONTEXT",
    "MAX_TURN_CONTENT",
    "SESSION_FILE",
    "SESSION_ROOT",
    "SESSION_SUMMARY_FILE",
    "append_assistant_turn",
    "append_user_turn",
    "build_session_context",
    "load_or_create_session",
    "save_session",
]


def load_or_create_session(workspace: Path) -> dict:
    """Load or create session.json with session_id and recent_turns."""

    root = _session_root(workspace)
    path = root / SESSION_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KesCodeError(
                f"Unable to read session file {path}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise KesCodeError(f"Session file {path} must contain an object.")
        return _normalize_session(data)

    root.mkdir(parents=True, exist_ok=True)
    session = _new_session()
    _write_json(path, session)
    return session


def append_user_turn(session, content: str) -> int:
    """Record a user input and return the new turn number."""

    session = _normalize_session(session)
    session["turn_index"] = int(session.get("turn_index") or 0) + 1
    turn = session["turn_index"]
    session["recent_turns"].append(
        {
            "turn": turn,
            "role": "user",
            "content": _clip(content, MAX_TURN_CONTENT),
            "timestamp": _now(),
        }
    )
    session["updated_at"] = _now()
    return turn


def append_assistant_turn(
    session,
    *,
    turn,
    route,
    content,
    summary="",
) -> None:
    """Record an assistant reply with its intent route."""

    if route not in {"chat", "workflow"}:
        raise KesCodeError(
            f"Assistant turn route must be 'chat' or 'workflow', got {route!r}."
        )
    session = _normalize_session(session)
    session["recent_turns"].append(
        {
            "turn": int(turn),
            "role": "assistant",
            "route": route,
            "content": _clip(content, MAX_TURN_CONTENT),
            "summary": _clip(summary, MAX_TURN_CONTENT),
            "timestamp": _now(),
        }
    )
    session["updated_at"] = _now()


def save_session(workspace, session) -> dict:
    """Save session.json and generate SESSION_SUMMARY.md."""

    session = _normalize_session(session)
    session["updated_at"] = _now()
    root = _session_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / SESSION_FILE, session)
    _write_text(root / SESSION_SUMMARY_FILE, _build_session_summary(session))
    return session


def build_session_context(workspace, session=None) -> str:
    """Build a bounded session context for the intent and chat nodes."""

    if session is None:
        session = load_or_create_session(workspace)
    session = _normalize_session(session)

    parts = [
        f"Session ID: {session.get('session_id', '')}",
        f"Turn index: {session.get('turn_index', 0)}",
    ]
    files = _recent_files(workspace)
    if files:
        file_list = "\n".join(f"- {path}" for path in files)
        parts.append(f"Workspace files (recent {_RECENT_FILE_COUNT}):\n{file_list}")
    else:
        parts.append(
            f"Workspace files (recent {_RECENT_FILE_COUNT}):\n- (none)"
        )

    turn_lines = _recent_turn_lines(session)
    if turn_lines:
        parts.append(
            f"Recent turns (last {_RECENT_CONTEXT_TURNS}):\n"
            + "\n".join(turn_lines)
        )
    else:
        parts.append(f"Recent turns (last {_RECENT_CONTEXT_TURNS}):\n- (none)")

    return _clip("\n\n".join(parts), MAX_SESSION_CONTEXT)


def _new_session() -> dict:
    timestamp = _now()
    return {
        "session_id": str(uuid4()),
        "turn_index": 0,
        "recent_turns": [],
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _normalize_session(session: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(session, dict):
        raise KesCodeError("Session must be a JSON object.")

    session.setdefault("session_id", str(uuid4()))
    session.setdefault("turn_index", 0)
    session.setdefault("recent_turns", [])
    session.setdefault("created_at", _now())
    session.setdefault("updated_at", session.get("created_at") or _now())

    turns = session["recent_turns"]
    if not isinstance(turns, list):
        raise KesCodeError("Session recent_turns must be a list.")
    session["recent_turns"] = [
        turn for turn in turns if isinstance(turn, dict)
    ]
    try:
        session["turn_index"] = int(session["turn_index"] or 0)
    except (TypeError, ValueError) as exc:
        raise KesCodeError("Session turn_index must be an integer.") from exc
    session["session_id"] = str(session["session_id"])
    session["created_at"] = str(session["created_at"])
    session["updated_at"] = str(session["updated_at"])
    return session


def _build_session_summary(session: dict[str, Any]) -> str:
    lines = [
        "# Session Summary",
        "",
        f"- Session ID: {session.get('session_id', '')}",
        f"- Turn index: {session.get('turn_index', 0)}",
        f"- Updated: {session.get('updated_at', '')}",
        "",
        "## Recent Turns",
        "",
    ]
    turns = list(session.get("recent_turns") or [])[-_RECENT_CONTEXT_TURNS:]
    if not turns:
        lines.append("- None")
        return "\n".join(lines)

    for turn in turns:
        role = str(turn.get("role") or "unknown")
        lines.append(f"### Turn {turn.get('turn')} ({role})")
        lines.append("")
        if turn.get("route"):
            lines.append(f"- Route: {turn['route']}")
        lines.append(f"- Timestamp: {turn.get('timestamp', '')}")
        if role == "assistant" and turn.get("summary"):
            lines.append(f"- Summary: {turn['summary']}")
        lines.append("")
        lines.append(f"Content:\n{turn.get('content', '')}")
        lines.append("")
    return "\n".join(lines)


def _recent_turn_lines(session: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for turn in list(session.get("recent_turns") or [])[
        -_RECENT_CONTEXT_TURNS:
    ]:
        role = str(turn.get("role") or "unknown")
        prefix = f"[turn {turn.get('turn')} {role}]"
        if turn.get("route"):
            prefix += f" ({turn['route']})"
        summary = str(turn.get("summary") or "").strip()
        if role == "assistant" and summary:
            detail = summary
        else:
            detail = str(turn.get("content") or "")
        lines.append(f"{prefix} {_single_line(_clip(detail, 800))}")
    return lines


def _recent_files(workspace: Path) -> list[str]:
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.exists():
        return []

    candidates: list[tuple[float, str]] = []
    try:
        for path in workspace.rglob("*"):
            if not path.is_file() or _is_ignored(path, workspace):
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            candidates.append((mtime, path.relative_to(workspace).as_posix()))
    except OSError:
        return []

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [path for _mtime, path in candidates[:_RECENT_FILE_COUNT]]


def _is_ignored(path: Path, workspace: Path) -> bool:
    try:
        parts = path.relative_to(workspace).parts
    except ValueError:
        return True
    return bool(parts) and parts[0] in _IGNORED_DIRS


def _session_root(workspace: Path) -> Path:
    return Path(workspace).expanduser().resolve() / SESSION_ROOT


def _clip(text: Any, limit: int) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def _single_line(text: Any) -> str:
    return " ".join(str(text).split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
